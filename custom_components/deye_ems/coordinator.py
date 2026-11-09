"""Independent EMS runtime: read, plan, journal attempts, then command one owner.

The default is shadow. No operation takes ownership by disabling another
controller. Persisted attempts are not acknowledgements of physical charging.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import partial
import logging
import math
from zoneinfo import ZoneInfo

from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DEFAULT_OPTIONS, DEFAULT_SOURCES, DOMAIN, OWNER_ENTITIES, OPTION_RANGES
from .grid_control import calculate_grid_charge, calculate_grid_charge_cap
from .planner import plan_energy
from .slot_meter import update_slot_measurements

_LOGGER = logging.getLogger(__name__)
_UTC = timezone.utc
_TZ = ZoneInfo("Europe/Warsaw")
_BAD = {"unknown", "unavailable", "none", ""}


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (ValueError, TypeError):
        return None


def _stamp(value):
    if isinstance(value, datetime):
        return value.timestamp() if value.tzinfo is not None else None
    if isinstance(value, str):
        try:
            return _stamp(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return None
    result = _number(value)
    result = result / 1000 if result is not None and result > 10**11 else result
    return result if result is not None and 0 <= result < 253402214400 else None


class DeyeEMSCoordinator(DataUpdateCoordinator):
    """One durable runtime per config entry; service writes are always guarded."""

    def __init__(self, hass, entry, *, store=None, clock=None,
                 planner=None, controller=None, statistics_provider=None):
        self.entry = entry
        initial = dict(getattr(entry, "data", {}))
        self._options = {**DEFAULT_OPTIONS, **initial, **dict(entry.options)}
        self._sources = {**DEFAULT_SOURCES, **initial.get("sources", {}),
                         **dict(entry.options).get("sources", {})}
        self._options["sources"] = dict(self._sources)
        self._clock = clock or (lambda: datetime.now(_UTC))
        self._store = store or Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.runtime")
        self._planner = planner or plan_energy
        self._controller = controller or calculate_grid_charge
        self._statistics_provider = statistics_provider or self._recorder_statistics
        self._lock = asyncio.Lock()
        self._stopped = False
        self._plan_due = 0.0
        self._memory = {"mode": "shadow", "target_cache": {}, "forecast_cache": {},
                        "load_profiles": {}, "ledger": {}, "plan": {}, "observed_owners": {},
                        "slot_measurements": {}, "safety_raise": {}}
        self._last_save_ts = 0
        self._last_error = None
        super().__init__(hass, _LOGGER, name="Deye EMS", config_entry=entry,
                         update_interval=timedelta(seconds=self._update_seconds()))
        self.data = {"mode": "shadow", "status": "initializing", "owner": "shadow",
                     "inputs": {}, "plan": {}, "control": {}}

    def _now(self):
        value = self._clock()
        if value.tzinfo is None:
            raise ValueError("EMS requires an aware clock")
        return value.astimezone(_TZ)

    def _update_seconds(self):
        return max(5, min(300, int(self._options.get("update_seconds", 10))))

    @property
    def options(self):
        return deepcopy(self._options)

    @property
    def mode(self):
        return self._memory.get("mode", "shadow")

    async def async_initialize(self):
        """Load state only. The caller performs the first coordinator refresh."""
        saved = await self._store.async_load()
        if isinstance(saved, dict):
            for key in self._memory:
                if key == "mode":
                    if saved.get(key) in ("shadow", "active"):
                        self._memory[key] = saved[key]
                elif isinstance(saved.get(key), dict):
                    self._memory[key] = saved[key]
        # A restart does not grant authority over another controller, nor does
        # a restored active mode allow writes with unavailable telemetry.
        if self.mode == "active":
            try:
                self._preflight()
            except ValueError:
                self._memory["mode"] = "shadow"
                self._last_error = "restored_active_preflight_failed"
                await self._save()

    async def async_shutdown(self):
        """Cancel future work, without emitting hardware commands on unload."""
        self._stopped = True
        shutdown = getattr(super(), "async_shutdown", None)
        if shutdown is not None:
            await shutdown()

    async def async_set_option(self, key, value):
        if key not in DEFAULT_OPTIONS and key not in ("sources", "extra_loads"):
            raise ValueError("Unknown EMS setting")
        if key == "sources":
            if not isinstance(value, dict) or any(k not in DEFAULT_SOURCES for k in value):
                raise ValueError("Invalid source mapping")
            if any(not isinstance(v, str) or (v and "." not in v) for v in value.values()):
                raise ValueError("Sources must be entity IDs")
        elif key == "extra_loads":
            if not isinstance(value, list) or len(value) > 32:
                raise ValueError("Expected a list of up to 32 extra loads")
            seen = set()
            for channel in value:
                if not isinstance(channel, dict):
                    raise ValueError("Invalid extra load")
                entity = channel.get("energy_entity")
                power = channel.get("power_entity", "")
                if (not isinstance(entity, str) or not entity.startswith("sensor.") or entity in seen
                        or not isinstance(channel.get("included_in_load", True), bool)
                        or not isinstance(power, str) or (power and not power.startswith("sensor."))):
                    raise ValueError("Extra loads require unique energy sensors and valid power sensors")
                seen.add(entity)
        else:
            number = _number(value)
            low, high = OPTION_RANGES.get(key, (5, 300))[:2]
            if number is None or not low <= number <= high:
                raise ValueError("Setting outside its allowed range")
            value = int(number) if key == "update_seconds" else number
        async with self._lock:
            if key in ("sources", "extra_loads") and self.mode == "active":
                raise ValueError("Switch to shadow before changing hardware mappings")
            if key == "sources":
                value = {**self._sources, **value}
            candidate = {**self._options, key: value}
            if candidate["min_soc_percent"] + candidate["reserve_margin_soc_percent"] > candidate["grid_max_soc_percent"]:
                raise ValueError("Minimum SoC plus reserve must not exceed the grid target ceiling")
            self._options[key] = value
            self._sources = {**DEFAULT_SOURCES, **self._options.get("sources", {})}
            if key in ("min_soc_percent", "reserve_margin_soc_percent", "sources", "extra_loads"):
                self._memory["target_cache"] = {}
                self._memory["safety_raise"] = {}
                self._memory["load_profiles"] = {}
            self._plan_due = 0
            self.update_interval = timedelta(seconds=self._update_seconds())
            self.hass.config_entries.async_update_entry(self.entry, options=dict(self._options))
            await self._save()
        await self.async_request_refresh()

    async def async_set_mode(self, mode):
        if mode not in ("shadow", "active"):
            raise ValueError("Choose shadow or active")
        async with self._lock:
            if mode == "active":
                self._preflight(retake=True)
                self._memory["observed_owners"] = {entity: True for entity in OWNER_ENTITIES
                                                    if self.hass.states.get(entity) is not None}
            elif self.mode == "active" and not self._owner_conflicts():
                # Explicit relinquishing is cleaned up while we still own the
                # hardware. A conflict is different: never touch another owner.
                await self._disable_gc()
                await self._grid_attempt(0, self._now().timestamp(), force=True)
            self._memory["mode"] = mode
            await self._save()
        await self.async_request_refresh()

    async def async_recalculate(self):
        self._plan_due = 0
        await self.async_request_refresh()

    async def _save(self):
        await self._store.async_save(deepcopy(self._memory))
        self._last_save_ts = self._now().timestamp()

    def _state(self, key):
        entity_id = self._sources.get(key)
        return self.hass.states.get(entity_id) if entity_id else None

    def _measurement(self, key, now, *, unit=None, age=None, low=None, high=None):
        return self._entity_measurement(self._sources.get(key), now, unit=unit, age=age, low=low, high=high)

    def _entity_measurement(self, entity_id, now, *, unit=None, age=None, low=None, high=None):
        state = self.hass.states.get(entity_id) if entity_id else None
        if state is None or state.attributes.get("restored", False):
            return None
        value = _number(state.state)
        report = _stamp(getattr(state, "last_reported", None) or state.last_updated)
        if value is None or report is None or report > now.timestamp():
            return None
        if unit is not None and state.attributes.get("unit_of_measurement") != unit:
            return None
        if age is not None and not 0 <= now.timestamp() - report <= age:
            return None
        if low is not None and value < low or high is not None and value > high:
            return None
        return value

    def _read_inputs(self, now):
        voltage = self._measurement("voltage", now, unit="V", age=120, low=40, high=65)
        soc = self._measurement("soc", now, unit="%", low=0, high=100)
        soc_state = self._state("soc")
        soc_at = _stamp(getattr(soc_state, "last_reported", None) or
                        getattr(soc_state, "last_updated", None))
        soc_valid = soc is not None and soc_at is not None and (
            0 <= now.timestamp() - soc_at <= 1200 or voltage is not None)
        powers = {key: self._measurement(key, now, unit="W", age=30,
                                        low=-60000 if key.startswith("grid") else -200,
                                        high=60000)
                  for key in ("grid_power", "load_power", "grid_l1_power", "grid_l2_power",
                              "grid_l3_power", "load_l1_power", "load_l2_power", "load_l3_power")}
        charge = self._measurement("bms_charge_current", now, unit="A", low=0, high=1000)
        block = self._measurement("bms_blocking_charge", now, age=120, low=0, high=1000)
        deye = self._measurement("max_charge_current_number", now, unit="A", low=0, high=1000)
        bms_valid = voltage is not None and None not in (charge, block, deye)
        cap = min(108, self._options["grid_current_max_a"], charge, deye) if bms_valid and block == 0 else 0
        current = self._measurement("grid_current_number", now, unit="A", low=0, high=1000)
        battery = self._measurement("battery_power", now, unit="W", age=30, low=-60000, high=60000)
        outside, outside_valid = 0, True
        for channel in self._channels():
            if channel["included_in_load"]:
                continue
            entity = channel.get("power_entity")
            state = self.hass.states.get(entity) if entity else None
            unit = state.attributes.get("unit_of_measurement") if state else None
            power = self._entity_measurement(entity, now, unit=unit, age=30, low=0, high=60000) if unit in ("W", "kW") else None
            if power is None:
                outside_valid = False
            else:
                outside += power * (1000 if unit == "kW" else 1)
        raw_load = powers["load_power"]
        return {**powers, "soc": soc, "soc_valid": bool(soc_valid), "voltage": voltage,
                "current_a": current, "bms_cap_a": cap, "bms_valid": bms_valid,
                "battery_power": battery,
                "outside_load_w": outside, "outside_power_valid": outside_valid, "raw_load_power": raw_load,
                "total_load_with_outside_w": None if raw_load is None else raw_load+outside,
                "telemetry_valid": voltage is not None and current is not None and
                bms_valid and outside_valid and all(v is not None for v in powers.values())}

    def _channels(self):
        """Configured meters, with the default pump included at most once."""
        channels, seen = [], set()
        for raw in self._options.get("extra_loads", []):
            if not isinstance(raw, dict):
                continue
            entity = raw.get("energy_entity")
            if not isinstance(entity, str) or not entity or entity in seen:
                continue
            seen.add(entity)
            channels.append({"name": str(raw.get("name") or entity), "energy_entity": entity,
                "power_entity": raw.get("power_entity", ""), "included_in_load": raw.get("included_in_load", True) is True})
        pump = self._sources.get("pc_energy_total")
        if pump and pump not in seen:
            channels.append({"name": "Pompa ciepła", "energy_entity": pump,
                             "power_entity": "", "included_in_load": True})
        return channels

    def _owner_conflicts(self, *, ignore_missing=False):
        return [entity_id for entity_id in OWNER_ENTITIES
                if ((state := self.hass.states.get(entity_id)) is not None and state.state != "off")
                or (not ignore_missing and state is None and entity_id in self._memory["observed_owners"])]

    def _hardware_modes_ok(self):
        required = {"solar_sell": "on", "tou_enabled": "on",
                    "energy_priority": "Load First", "work_mode": "Zero Export To Load"}
        return all((state := self._state(key)) is not None and state.state == expected
                   and not state.attributes.get("restored", False)
                   for key, expected in required.items())

    def _clocks_ok(self, now):
        winter = self._window(now)[0]
        clocks = ("00:00:00", "04:00:00", "07:00:00", "13:00:00",
                  "16:00:00" if winter else "19:00:00", "21:00:00" if winter else "22:00:00")
        return all((state := self._state(f"tou_time_{slot}")) is not None and
                   state.state == clock and not state.attributes.get("restored", False)
                   for slot, clock in enumerate(clocks, 1))

    def _preflight(self, *, retake=False):
        if self._owner_conflicts(ignore_missing=retake):
            raise ValueError("Existing previous controllers must be OFF and observed controllers available")
        now = self._now()
        inputs = self._read_inputs(now)
        if not inputs["telemetry_valid"] or not inputs["soc_valid"]:
            raise ValueError("Activation requires fresh, valid power and battery measurements")
        if not self._hardware_modes_ok():
            raise ValueError("Inverter modes do not match the EMS model")
        writable = [self._sources.get("grid_current_number")]
        for slot in range(1, 7):
            writable += [self._sources.get(f"tou_soc_{slot}"), self._sources.get(f"tou_gc_{slot}"),
                         self._sources.get(f"tou_time_{slot}")]
        if len(set(writable)) != len(writable) or any(
                not entity_id or (state := self.hass.states.get(entity_id)) is None or
                state.state in _BAD for entity_id in writable):
            raise ValueError("Every writable source must exist and have a unique mapping")

    async def _service(self, entity_id, action, value=None):
        conflicts = self._owner_conflicts()
        if conflicts and self.mode == "active":
            self._memory["mode"] = "shadow"
            self._last_error = "ownership_conflict"
            try:
                await self._save()
            except Exception:
                self._last_error = "ownership_conflict_store_failed"
            return False
        if self._stopped or self.mode != "active" or conflicts:
            return False
        # No await is allowed between these current-state checks and dispatch.
        # A slow Store/recorder call may have crossed a tariff boundary or a
        # BMS permission update since the caller calculated its request.
        now = self._now()
        inputs = self._read_inputs(now)
        winter, night, afternoon, _, active_slot = self._window(now)
        target, emergency, _ = self._target(now)
        floor = self._options["min_soc_percent"]
        allowed = (night or afternoon) and (winter or emergency or
                   inputs["soc"] is not None and inputs["soc"] < floor)
        cap = calculate_grid_charge_cap(self._grid_input(inputs, now, target, emergency))
        if entity_id == self._sources["grid_current_number"] and value > 0:
            if not (allowed and inputs["soc_valid"] and inputs["telemetry_valid"] and
                    inputs["soc"] < target and self._hardware_modes_ok() and value <= cap["cap_a"]):
                self._last_error = "last_moment_current_guard"
                return False
        if action == "turn_on":
            requested = self._memory["ledger"].get(self._sources["grid_current_number"], {}).get("a", 0)
            setting = self._measurement(f"tou_soc_{active_slot}", now, unit="%", low=0, high=100)
            expected_time = ("00:00:00", "04:00:00", "07:00:00", "13:00:00",
                             "16:00:00" if winter else "19:00:00", "21:00:00" if winter else "22:00:00")[active_slot - 1]
            clock = self._state(f"tou_time_{active_slot}")
            if not (entity_id == self._sources[f"tou_gc_{active_slot}"] and active_slot not in (3, 5)
                    and allowed and self._hardware_modes_ok() and self._clocks_ok(now) and inputs["soc_valid"]
                    and inputs["soc"] < target and
                    self._settled_grid(inputs, now, requested) and requested <= cap["cap_a"] and
                    setting is not None and abs(setting - target) < 2 and
                    clock is not None and clock.state == expected_time):
                self._last_error = "last_moment_gc_guard"
                return False
        if entity_id in [self._sources[f"tou_soc_{slot}"] for slot in range(1, 7)]:
            if value < floor or not self._hardware_modes_ok():
                return False
        if entity_id in [self._sources[f"tou_time_{slot}"] for slot in range(1, 7)] and not self._hardware_modes_ok():
            return False
        domain = entity_id.split(".", 1)[0]
        data = {"entity_id": entity_id}
        if value is not None:
            data["time" if domain == "time" else "value"] = value
        try:
            await asyncio.wait_for(self.hass.services.async_call(
                domain, action, data, blocking=True), timeout=10)
            return True
        except Exception as error:  # The persisted attempt survives transport failure.
            self._last_error = f"command_failed:{type(error).__name__}"
            return False

    async def _attempt(self, entity_id, action, value, now_ts, *, cooldown, force=False):
        old = self._memory["ledger"].get(entity_id, {})
        if not isinstance(old, dict):
            self._last_error = "invalid_attempt_ledger"
            return False
        attempted, previous = _number(old.get("at")), old.get("a")
        if attempted is not None:
            if attempted > now_ts:
                self._last_error = "future_attempt_ledger"
                return False
            # Even safety retries must not flood the device with an identical
            # unacknowledged command. Ordinary writes have their own cooldown.
            identical = previous == value and old.get("action") == action
            if now_ts - attempted < (10 if force and identical else cooldown if not force else 0):
                return False
        self._memory["ledger"][entity_id] = {"at": now_ts, "a": value, "action": action}
        try:
            await self._save()  # Mandatory durable journal BEFORE every command.
        except Exception:
            self._last_error = "attempt_store_failed"
            return False
        return await self._service(entity_id, action, value)

    async def _grid_attempt(self, value, now_ts, *, force=False):
        return await self._attempt(self._sources["grid_current_number"], "set_value", int(value),
                                   now_ts, cooldown=10, force=force)

    async def _gc(self, slot, enabled):
        key = f"tou_gc_{slot}"
        state = self._state(key)
        wanted = "on" if enabled else "off"
        if state is None or state.state == wanted:
            return
        await self._attempt(self._sources[key], "turn_on" if enabled else "turn_off", None,
                            self._now().timestamp(), cooldown=10, force=not enabled)

    async def _disable_gc(self):
        for slot in range(1, 7):
            await self._gc(slot, False)

    async def _repair_floor(self, now):
        floor = self._options["min_soc_percent"]
        for slot in range(1, 7):
            key = f"tou_soc_{slot}"
            value = self._measurement(key, now, unit="%", low=0, high=100)
            if value is not None and value < floor:
                await self._attempt(self._sources[key], "set_value", floor, now.timestamp(),
                                    cooldown=600, force=True)
        # Protected slots are restored before selecting or persisting any plan.
        for slot in (3, 5):
            await self._gc(slot, False)
            key = f"tou_soc_{slot}"
            value = self._measurement(key, now, unit="%", low=0, high=100)
            if value is not None and abs(value - floor) >= 2:
                await self._attempt(self._sources[key], "set_value", floor,
                                    now.timestamp(), cooldown=600)

    @staticmethod
    def _window(now):
        winter = now.month in (10, 11, 12, 1, 2, 3)
        peak, late = (16, 21) if winter else (19, 22)
        hour = now.hour + now.minute / 60 + now.second / 3600
        night = hour >= late or hour < 7
        afternoon = 13 <= hour < peak
        deadline = now.replace(hour=7 if night else peak, minute=0, second=0, microsecond=0)
        if night and hour >= late:
            deadline += timedelta(days=1)
        slot = next(i for i, end in enumerate((4, 7, 13, peak, late, 24), 1) if hour < end)
        return winter, night, afternoon, deadline, slot

    def _grid_input(self, inputs, now, target, emergency, *, safety_only=False):
        winter, night, afternoon, deadline, _ = self._window(now)
        ledger = self._memory["ledger"].get(self._sources["grid_current_number"], {})
        if not isinstance(ledger, dict):
            ledger = {"at": None, "a": None}
        # A newly created ledger starts at zero. Invalid persisted data remains
        # invalid and inhibits increases in the pure controller.
        return {"now_ts": now.timestamp(), "winter": winter, "cheap_window": night or afternoon,
                "emergency_allowed": emergency, "safety_only": safety_only,
                "soc_valid": inputs["soc_valid"], "soc": inputs["soc"], "target_soc": target,
                "remaining_h": (deadline.timestamp() - now.timestamp()) / 3600,
                "minimum_soc_percent": self._options["min_soc_percent"],
                "capacity_kwh": self._options["capacity_kwh"],
                "bms_cap_a": inputs["bms_cap_a"], "telemetry_valid": inputs["telemetry_valid"],
                "load_w": inputs["load_power"], "grid_w": inputs["grid_power"],
                "outside_load_w": inputs["outside_load_w"],
                "load_phases_w": [inputs[f"load_l{i}_power"] for i in (1, 2, 3)],
                "grid_phases_w": [inputs[f"grid_l{i}_power"] for i in (1, 2, 3)],
                "battery_voltage_v": inputs["voltage"], "current_a": inputs["current_a"],
                "last_attempt_ts": ledger.get("at", 0), "last_attempt_a": ledger.get("a", 0),
                "total_limit_w": self._options["grid_import_limit_kw"] * 1000,
                "phase_limit_w": self._options["grid_phase_limit_kw"] * 1000,
                "headroom_w": 500, "phase_headroom_w": 250, "charge_efficiency": .9}

    def _settled_grid(self, inputs, now, requested):
        requested = _number(requested)
        if requested is None:
            return False
        ledger = self._memory["ledger"].get(self._sources["grid_current_number"], {})
        if not isinstance(ledger, dict):
            return False
        at = _number(ledger.get("at"))
        state = self._state("grid_current_number")
        report = _stamp(getattr(state, "last_reported", None) or getattr(state, "last_updated", None))
        return (inputs["telemetry_valid"] and requested > 0 and at is not None and
                10 <= now.timestamp() - at and report is not None and report >= at and
                inputs["current_a"] is not None and abs(inputs["current_a"] - requested) < .01)

    async def _run_driver(self, inputs, control, target, emergency, now):
        winter, night, afternoon, _, active_slot = self._window(now)
        floor = self._options["min_soc_percent"]
        if control.get("write"):
            await self._grid_attempt(control["next_a"], now.timestamp(), force=control.get("safety", False))
        times = ("00:00:00", "04:00:00", "07:00:00", "13:00:00",
                 "16:00:00" if winter else "19:00:00", "21:00:00" if winter else "22:00:00")
        for slot, clock in enumerate(times, 1):
            key = f"tou_time_{slot}"
            state = self._state(key)
            if state is not None and state.state not in _BAD and state.state != clock:
                await self._attempt(self._sources[key], "set_value", clock, now.timestamp(), cooldown=600)
            value = target if (night and slot in (1, 2, 6) or afternoon and slot == 4) else floor
            old = self._measurement(f"tou_soc_{slot}", now, unit="%", low=0, high=100)
            if old is not None and abs(old - value) >= 2:
                await self._attempt(self._sources[f"tou_soc_{slot}"], "set_value", value,
                                    now.timestamp(), cooldown=600, force=old < floor)
        # Re-read settings after commands; they remain readbacks of registers,
        # not a claim that the inverter has physically delivered the energy.
        observed = self._read_inputs(self._now())
        ready = self._settled_grid(observed, self._now(), control.get("next_a", 0))
        soc_read = self._measurement(f"tou_soc_{active_slot}", self._now(), unit="%", low=0, high=100)
        clock_read = self._state(f"tou_time_{active_slot}")
        ready = (ready and inputs["soc_valid"] and soc_read is not None and abs(soc_read - target) < 2
                 and clock_read is not None and clock_read.state == times[active_slot - 1]
                 and control.get("telemetry_ok", False) and self._hardware_modes_ok() and self._clocks_ok(self._now()))
        permitted = (night or afternoon) and (winter or emergency or
                                              inputs["soc"] is not None and inputs["soc"] < floor)
        active_gc = self._state(f"tou_gc_{active_slot}")
        cap = calculate_grid_charge_cap(self._grid_input(observed, self._now(), target, emergency))
        # A safe current ramp must not pulse an already enabled charger OFF for
        # ten seconds every thirty seconds. Initial enabling still requires the
        # exact requested setting to settle; continuing is a separate decision.
        continuing = (active_gc is not None and active_gc.state == "on" and permitted and
                      observed["telemetry_valid"] and observed["soc_valid"] and
                      observed["soc"] < target and
                      observed["current_a"] is not None and 0 < observed["current_a"] <= cap["cap_a"] and
                      0 < control.get("next_a", 0) <= cap["cap_a"] and
                      soc_read is not None and abs(soc_read - target) < 2 and
                      clock_read is not None and clock_read.state == times[active_slot - 1] and
                      self._hardware_modes_ok() and self._clocks_ok(self._now()))
        for slot in range(1, 7):
            await self._gc(slot, bool((ready or continuing) and permitted and slot == active_slot and slot not in (3, 5)))
        control["setting_settled"] = bool(ready)
        control["actual_battery_w"] = observed["battery_power"]
        control["read_setting_a"] = observed["current_a"]
        if permitted and control.get("next_a", 0) > 0 and not ready:
            control["runtime_reason"] = "waiting_setting_readback"

    async def _recorder_statistics(self, now, load_entity, pc_entity):
        """Read recorder in its executor; never run database work on HA's loop."""
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder.statistics import statistics_during_period
        job = partial(statistics_during_period, self.hass,
                      start_time=(now - timedelta(days=7)).replace(minute=0, second=0, microsecond=0).astimezone(_UTC),
                      end_time=now.astimezone(_UTC), statistic_ids={load_entity, *(c["energy_entity"] for c in self._channels())},
                      period="hour", units={"power": "W", "energy": "kWh"}, types={"mean", "change"})
        return await get_instance(self.hass).async_add_executor_job(job)

    def _record_slot_measurements(self, now, inputs):
        self._memory["slot_measurements"] = update_slot_measurements(
            self._memory["slot_measurements"], {"at": now,
                "battery_w": inputs["battery_power"], "grid_w": inputs["grid_power"],
                "telemetry_valid": inputs["battery_power"] is not None and inputs["grid_power"] is not None})

    async def _load_profile(self, now):
        signature = {"load": self._sources["load_power"], "channels": self._channels()}
        try:
            stats = await asyncio.wait_for(self._statistics_provider(
                now, self._sources["load_power"], self._sources.get("pc_energy_total")), timeout=15)
            if isinstance(stats, dict) and isinstance(stats.get("statistics"), dict):
                stats = stats["statistics"]

            def hourly(items, field, scale=1):
                output = {}
                for item in items:
                    start, end, value = _stamp(item.get("start")), _stamp(item.get("end")), _number(item.get(field))
                    if None not in (start, end, value) and 3599 <= end-start <= 3601 and (
                            now.timestamp()-8*86400 <= start < end <= now.timestamp()) and value >= 0:
                        if start in output:
                            raise ValueError("duplicate_hourly_statistics")
                        output[start] = (start, end, value*scale)
                return output

            load = hourly(stats.get(self._sources["load_power"], []), "mean")
            rows = list(load.values())
            if not rows or now.timestamp()-max(x[1] for x in rows) > 10800:
                raise ValueError("load_statistics_missing")
            midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
            reference = midnight-timedelta(days=1)
            expected = round((midnight.timestamp()-reference.timestamp())/3600)
            channels = []
            for channel in self._channels():
                state = self.hass.states.get(channel["energy_entity"])
                unit_ok = (state is not None and not state.attributes.get("restored", False) and
                           state.attributes.get("unit_of_measurement") in ("Wh", "kWh") and _number(state.state) is not None)
                # Recorder is explicitly asked for kWh, even for a Wh source.
                values = hourly(stats.get(channel["energy_entity"], []), "change", 1000) if unit_ok else {}
                if not channel["included_in_load"] and (not values or now.timestamp()-max(x[1] for x in values.values()) > 10800):
                    raise ValueError("outside_load_history_missing")
                by_hour = {}
                yesterday = [x for x in values.values() if reference.timestamp() <= x[0] < midnight.timestamp()]
                for at, _, power in yesterday:
                    by_hour.setdefault(datetime.fromtimestamp(at, _TZ).hour, []).append(power)
                current = [x for x in values.values() if x[0] >= midnight.timestamp()]
                ratio = 1.0
                if len(current) >= 3 and all(datetime.fromtimestamp(x[0], _TZ).hour in by_hour for x in current):
                    denominator = sum(sum(by_hour[datetime.fromtimestamp(x[0], _TZ).hour]) /
                                      len(by_hour[datetime.fromtimestamp(x[0], _TZ).hour]) for x in current)
                    if denominator > 0:
                        ratio = sum(x[2] for x in current)/denominator
                channels.append({**channel, "values": values, "by_hour": by_hour, "ratio": ratio,
                                 "reference_complete": len(yesterday) == expected and len(by_hour) >= 23})
            included = [c for c in channels if c["included_in_load"]]
            outside = [c for c in channels if not c["included_in_load"]]
            included_ready = bool(included) and all(all(at in c["values"] for c in included) and
                    sum(c["values"][at][2] for c in included) <= row[2] for at, row in load.items())
            profiles, used = {}, set()
            for weekend in (False, True):
                values = []
                for hour in range(24):
                    candidates = [x for x in rows if datetime.fromtimestamp(x[0], _TZ).hour == hour]
                    matched = [x for x in candidates if (datetime.fromtimestamp(x[0], _TZ).weekday() >= 5) == weekend]
                    use = matched if len({datetime.fromtimestamp(x[0], _TZ).date() for x in matched}) >= 3 else candidates
                    if len({datetime.fromtimestamp(x[0], _TZ).date() for x in use}) < 3:
                        raise ValueError("load_hour_history_insufficient")
                    weighted = [(x, .85**((now.timestamp()-x[0])/86400)) for x in use]
                    denominator = sum(w for _, w in weighted)
                    total = sum(x[2]*w for x, w in weighted)/denominator
                    # Missing any included series retains whole LOAD; none of
                    # the included channels is added to it a second time.
                    if included_ready:
                        total = sum((x[2]-sum(c["values"][x[0]][2] for c in included))*w
                                    for x, w in weighted)/denominator
                    for channel in (included if included_ready else []) + outside:
                        if channel["included_in_load"]:
                            channel_rows = [channel["values"][x[0]] for x in use]
                        else:
                            channel_rows = [x for x in channel["values"].values()
                                            if datetime.fromtimestamp(x[0], _TZ).hour == hour]
                        if len({datetime.fromtimestamp(x[0], _TZ).date() for x in channel_rows}) < 3:
                            raise ValueError("outside_load_history_insufficient")
                        if channel["reference_complete"] and hour in channel["by_hour"]:
                            forecast = sum(channel["by_hour"][hour])/len(channel["by_hour"][hour])*channel["ratio"]
                        else:
                            cw = [(x, .85**((now.timestamp()-x[0])/86400)) for x in channel_rows]
                            forecast = sum(x[2]*w for x, w in cw)/sum(w for _, w in cw)
                        total += forecast
                        used.add(channel["energy_entity"])
                    values.append(total/1000)
                profiles[str(weekend)] = values
            result = {"profiles": profiles, "through": max(x[1] for x in rows),
                      "signature": signature,
                      "pc_applied": self._sources.get("pc_energy_total") in used,
                      "pc_ratio": next((c["ratio"] for c in channels if c["energy_entity"] == self._sources.get("pc_energy_total")), 1),
                      "extra_loads": [{k: c[k] for k in ("name", "energy_entity", "included_in_load")}
                          | {"used": c["energy_entity"] in used, "trend_ratio": c["ratio"],
                             "reason": "profile_applied_once" if c["energy_entity"] in used else "whole_load_fallback"}
                          for c in channels]}
            self._memory["load_profiles"] = result
            return result
        except Exception as error:
            previous = self._memory.get("load_profiles", {})
            through = _number(previous.get("through"))
            if isinstance(error, ValueError) and str(error).startswith("outside_"):
                self._last_error = str(error)
                return {}
            if (through is not None and 0 <= now.timestamp()-through <= 10800 and previous.get("profiles")
                    and previous.get("signature") == signature):
                return {**previous, "cached": True}
            self._last_error = f"load_profile_unavailable:{type(error).__name__}"
            return {}

    def _solar_points(self, now):
        live, bad = {}, False
        for key in ("pv_today", "pv_tomorrow", "pv_day3"):
            state = self._state(key)
            if state is None:
                continue
            periods = state.attributes.get("detailedForecast", [])
            if not isinstance(periods, list):
                bad = True
                continue
            for row in periods:
                at = _stamp(row.get("period_start")) if isinstance(row, dict) else None
                p10, p50 = (_number(row.get("pv_estimate10")), _number(row.get("pv_estimate"))) if isinstance(row, dict) else (None, None)
                if None in (at, p10, p50) or at % 1800 or not 0 <= p10 <= p50:
                    bad = True
                    continue
                value = {"p10": p10, "p50": p50}
                if str(int(at)) in live and live[str(int(at))] != value:
                    bad = True
                live[str(int(at))] = value
        start = int(now.timestamp() // 1800) * 1800
        saved = self._memory.get("forecast_cache", {})
        saved = {k: v for k, v in saved.items() if _number(k) is not None and
                 start <= float(k) <= start + 3 * 86400 and isinstance(v, dict)}
        # Invalid current rows cannot poison an already validated dated cache.
        if not bad:
            saved.update(live)
        saved = {k: v for k, v in saved.items() if start <= float(k) <= start + 3 * 86400}
        self._memory["forecast_cache"] = saved
        return saved

    async def _make_plan(self, now, inputs):
        profiles = await self._load_profile(now)
        points = self._solar_points(now)
        rows = []
        start = int(now.timestamp() // 1800) * 1800
        for index in range(96):
            at = start + index * 1800
            when = datetime.fromtimestamp(at, _TZ)
            point = points.get(str(at))
            profile = profiles.get("profiles", {}).get(str(when.weekday() >= 5))
            if point is None or not isinstance(profile, list) or len(profile) != 24:
                rows = []
                break
            rows.append({"timestamp": when.isoformat(), "pv_p10_kw": point.get("p10"),
                         "pv_p50_kw": point.get("p50"), "load_kw": profile[when.hour]})
        config = {**self._options, "minimum_soc_percent": self._options["min_soc_percent"],
                  "margin_soc_percent": self._options["reserve_margin_soc_percent"],
                  "grid_import_max_kw": self._options["grid_import_limit_kw"],
                  "inverter_max_kw": 12, "grid_export_max_kw": 9}
        plan = self._planner({"now": now, "soc_percent": inputs["soc"], "soc_valid": inputs["soc_valid"],
                              "forecast": rows, "config": config,
                              "retained_targets": self._memory["target_cache"]})
        old_plan = self._memory["plan"]
        old_cache = deepcopy(self._memory["target_cache"])
        old_raise = deepcopy(self._memory["safety_raise"])
        self._memory["plan"] = plan
        self._accept_targets(plan, now)
        if plan.get("quality") == "valid" and plan.get("source") == "own_deterministic_planner":
            for key, record in plan.get("targets", {}).items():
                if not isinstance(record, dict) or key not in self._deadlines(now):
                    continue
                if self._live_record(plan, key, now):
                    if plan.get("status") == "ok":
                        self._memory["safety_raise"].pop(key, None)
                    elif plan.get("status") == "unreachable":
                        self._memory["safety_raise"][key] = {**record,
                            "generated_at": plan["generated_at"], "deadline": record["deadline"]}
        try:
            await self._save()
        except Exception:
            self._memory["plan"] = old_plan
            self._memory["target_cache"] = old_cache
            self._memory["safety_raise"] = old_raise
            self._last_error = "plan_store_failed"
            raise
        self._plan_due = now.timestamp() + 300
        return plan

    def _deadlines(self, now):
        peak = 16 if now.month in (10, 11, 12, 1, 2, 3) else 19
        return {key: (at if at > now else at + timedelta(days=1)).timestamp()
                for key, hour in (("night", 7), ("peak", peak))
                for at in [now.replace(hour=hour, minute=0, second=0, microsecond=0)]}

    def _accept_targets(self, plan, now):
        if (plan.get("status") != "ok" or plan.get("quality") != "valid" or
                plan.get("source") != "own_deterministic_planner"):
            return
        generated = _stamp(plan.get("generated_at"))
        if generated is None or not 0 <= now.timestamp() - generated <= 900:
            return
        deadlines = self._deadlines(now)
        for key, record in plan.get("targets", {}).items():
            if not isinstance(record, dict):
                continue
            value, deadline = _number(record.get("soc_percent")), _stamp(record.get("deadline"))
            if (key in deadlines and value is not None and self._options["min_soc_percent"] <= value <= 95
                    and deadline == deadlines[key] and record.get("unreachable") is False
                    and record.get("source") == "own_deterministic_planner"):
                self._memory["target_cache"][key] = {**record, "soc_percent": value,
                    "deadline": datetime.fromtimestamp(deadline, _TZ).isoformat(),
                    "accepted_at": generated, "season": plan.get("season"),
                    "source": "own_deterministic_planner", "generated_at": plan["generated_at"]}

    def _target(self, now):
        winter, night, _, _, _ = self._window(now)
        key = "night" if night else "peak"
        saved = self._memory["target_cache"].get(key, {})
        if not isinstance(saved, dict):
            saved = {}
        value = _number(saved.get("soc_percent"))
        deadline, accepted = _stamp(saved.get("deadline")), _stamp(saved.get("generated_at"))
        floor = self._options["min_soc_percent"]
        minimum_target = min(95, floor + self._options["reserve_margin_soc_percent"])
        generated = datetime.fromtimestamp(accepted, _TZ) if accepted is not None else None
        summer_normal = not winter and value == floor and saved.get("emergency") is False
        valid_cache = (None not in (value, deadline, accepted) and floor <= value <= 95 and
                (value >= minimum_target or summer_normal) and
                deadline == self._deadlines(now)[key] and 0 <= now.timestamp() - accepted <= 86400
                and accepted < deadline and self._deadlines(generated)[key] == deadline
                and (generated.month in (10, 11, 12, 1, 2, 3)) == winter
                and saved.get("season") == ("winter" if winter else "summer")
                and saved.get("source") == "own_deterministic_planner" and saved.get("unreachable") is False
                and isinstance(saved.get("emergency"), bool) and isinstance(saved.get("grid_charge_allowed"), bool)
                and (winter or saved["emergency"] is (not summer_normal)))
        retained = [self._measurement(f"tou_soc_{slot}", now, unit="%", low=floor, high=95)
                    for slot in ((1, 2, 6) if night else (4,))]
        fallback = min(95, max(self._options["winter_weather_soc_percent"], minimum_target,
                              *(value for value in retained if value is not None))) if winter else 95
        selected, emergency, source = (value, saved.get("emergency") is True, "dated_cache") if valid_cache else (
            fallback, not winter, "winter_fallback" if winter else "summer_emergency_fallback")
        plan = self._memory.get("plan", {})
        live = self._live_record(plan, key, now)
        if live and plan.get("status") == "ok" and valid_cache:
            source = "own_plan"
        elif winter and valid_cache:
            selected = max([selected, *(x for x in retained if x is not None)])
            if selected > value:
                source = "dated_cache_with_retained_raise"
        raised = self._memory["safety_raise"].get(key, {})
        if isinstance(raised, dict):
            raised_value, raised_deadline = _number(raised.get("soc_percent")), _stamp(raised.get("deadline"))
            generated = _stamp(raised.get("generated_at"))
            if (raised_value is not None and selected < raised_value <= 95 and
                    raised_deadline == self._deadlines(now)[key] and generated is not None and
                    0 <= now.timestamp()-generated <= 86400 and
                    raised.get("source") == "own_deterministic_planner"):
                return raised_value, not winter, "unreachable_plan_raise"
        return selected, emergency, source

    def _live_record(self, plan, key, now):
        if not isinstance(plan, dict) or plan.get("source") != "own_deterministic_planner" or plan.get("quality") != "valid":
            return None
        if plan.get("season") != ("winter" if self._window(now)[0] else "summer"):
            return None
        generated = _stamp(plan.get("generated_at"))
        targets = plan.get("targets")
        record = targets.get(key) if isinstance(targets, dict) else None
        if generated is None or not 0 <= now.timestamp()-generated <= 300 or not isinstance(record, dict):
            return None
        value = _number(record.get("soc_percent"))
        if (value is None or not self._options["min_soc_percent"] <= value <= 95 or
                _stamp(record.get("deadline")) != self._deadlines(now)[key] or
                record.get("source") != "own_deterministic_planner"):
            return None
        return record

    async def _async_update_data(self):
        async with self._lock:
            if self._stopped:
                return self.data
            now = self._now()
            inputs = self._read_inputs(now)
            self._record_slot_measurements(now, inputs)
            conflicts = self._owner_conflicts()
            if self.mode == "active" and conflicts:
                self._memory["mode"] = "shadow"
                self._last_error = "ownership_conflict"
                await self._save()
            active = self.mode == "active"
            floor = self._options["min_soc_percent"]
            safety = self._controller(self._grid_input(inputs, now, floor, False, safety_only=True))
            modes_ok = self._hardware_modes_ok()
            if active and not modes_ok:
                await self._disable_gc()
                await self._grid_attempt(0, now.timestamp(), force=True)
            elif active:
                if safety.get("write"):
                    await self._grid_attempt(safety["next_a"], now.timestamp(), force=True)
                _, night, afternoon, _, _ = self._window(now)
                if not (night or afternoon) or not inputs["telemetry_valid"]:
                    await self._disable_gc()
                await self._repair_floor(now)
            plan = self._memory.get("plan", {})
            plan_saved = True
            if now.timestamp() >= self._plan_due:
                try:
                    plan = await self._make_plan(now, inputs)
                except Exception:
                    plan_saved = False
                    if self.mode == "active":
                        await self._disable_gc()
                        await self._grid_attempt(0, self._now().timestamp(), force=True)
            # Recorder may take time. Re-read all control measurements before
            # evaluating any normal command or readback gate.
            now = self._now()
            inputs = self._read_inputs(now)
            target, emergency, target_source = self._target(now)
            control = self._controller(self._grid_input(inputs, now, target, emergency))
            modes_ok = self._hardware_modes_ok()
            active = self.mode == "active"
            if active and (not modes_ok or not plan_saved):
                await self._disable_gc()
                await self._grid_attempt(0, now.timestamp(), force=True)
                control["runtime_reason"] = "hardware_mode_mismatch" if not modes_ok else "plan_store_failed"
            elif active:
                await self._run_driver(inputs, control, target, emergency, now)
            active = self.mode == "active"
            if now.timestamp()-self._last_save_ts >= 60:
                try:
                    await self._save()
                except Exception:
                    self._last_error = "periodic_store_failed"
            target_key = "night" if self._window(now)[1] else "peak"
            target_deadline = datetime.fromtimestamp(self._deadlines(now)[target_key], _TZ).isoformat()
            return {"mode": self.mode, "owner": {"active": active, "conflicts": self._owner_conflicts()},
                    "status": control.get("runtime_reason", "active" if active else "shadow"),
                    "error": self._last_error, "conflicts": conflicts,
                    "inputs": inputs, "plan": plan, "control": {**control, "target_soc": target,
                        "target_source": target_source, "deadline": target_deadline,
                        "target_deadline": target_deadline, "target_key": target_key,
                        "requested_a": control.get("next_a"), "read_setting_a": inputs["current_a"],
                        "actual_battery_w": inputs["battery_power"]},
                    "slot_measurements": deepcopy(self._memory["slot_measurements"]),
                    "profiles": deepcopy(self._memory["load_profiles"]),
                    "settings": deepcopy(self._options), "sources": dict(self._sources),
                    "updated_at": now.isoformat(), "physical_confirmation": False}
