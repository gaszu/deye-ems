"""Independent EMS runtime: read, plan, journal attempts, then command one owner.

The default is shadow. No operation takes ownership by disabling another
controller. Persisted attempts are not acknowledgements of physical charging.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import partial
from hashlib import sha256
import json
import logging
import math
import re
from urllib.parse import urlsplit
from uuid import uuid4
from zoneinfo import ZoneInfo

from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DEFAULT_OPTIONS, DEFAULT_SOURCES, DOMAIN, OWNER_ENTITIES, OPTION_RANGES
from .grid_control import (calculate_grid_charge_cap, calculate_grid_charge_increase_cap,
                           calculate_grid_charge as calculate_grid_charge_demand)
from .scheduled_current import (calculate_grid_charge, update_policy, dispatch_ready, initial_dispatch_ready,
                                DEADBAND_A, QUANTUM_A)
from .planner import plan_energy
from .slot_meter import update_slot_measurements
from .topology import ct_load_balance
from .soc_policy import reserve_lower_bound

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
                 planner=None, controller=None, statistics_provider=None,
                 solcast_factory=None, solcast_fetcher=None):
        self.entry = entry
        initial = dict(getattr(entry, "data", {}))
        self._options = {**DEFAULT_OPTIONS, **initial, **dict(entry.options)}
        self._sources = {**DEFAULT_SOURCES, **initial.get("sources", {}),
                         **dict(entry.options).get("sources", {})}
        self._options["sources"] = dict(self._sources)
        self._options["solcast"] = {**initial.get("solcast", {}),
                                   **dict(entry.options).get("solcast", {})}
        self._solcast_factory = solcast_factory
        self._solcast_fetcher = solcast_fetcher or self._solcast_fetch_json
        self._solcast_client = None
        self._solcast_status = {"status": "not_configured"}
        self._clock = clock or (lambda: datetime.now(_UTC))
        self._store = store or Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.runtime")
        self._planner = planner or plan_energy
        self._controller = controller or calculate_grid_charge
        self._statistics_provider = statistics_provider or self._recorder_statistics
        self._lock = asyncio.Lock()
        self._store_lock = asyncio.Lock()
        self._plan_task = None
        self._planning_revision = 0
        self._stopped = False
        self._plan_due = 0.0
        self._memory = {"mode": "shadow", "target_cache": {}, "forecast_cache": {},
                        "load_profiles": {}, "ledger": {}, "plan": {}, "observed_owners": {},
                        "slot_measurements": {}, "safety_raise": {},
                        "solcast_cache": {}, "solcast_context": {}, "solcast_seed": {},
                        "grid_dispatch": {}, "current_policy": {}, "initial_charge_window": {},
                        "metering_context": {}, "soc_floor_guard": {}}
        self._last_save_ts = 0
        self._last_error = None
        # Evidence of an accepted service call, never a physical charging ACK.
        # Kept only in RAM: a restart must re-establish settled readback.
        self._pending_grid_reduction = None
        self._grid_reduction_chain = None
        self._current_grid_attempt = None
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
        public = {key: self._options[key] for key in {*DEFAULT_OPTIONS, "sources", "extra_loads"}
                  if key != "solcast" and key in self._options}
        config = self._options.get("solcast", {})
        public["solcast_configured"] = self._solcast_configured()
        public["solcast_site_count"] = len(config.get("resource_ids", []))
        bound = self._soc_lower_bound()
        public.update(min_soc_lower_bound=bound, min_soc_bound_valid=bound is not None,
                      effective_min_soc_percent=self._effective_min_soc())
        return self._redact(public)

    def _soc_lower_bound(self):
        low = self._measurement("battery_low_soc", self._now(), unit="%", low=0, high=85)
        return reserve_lower_bound(low) if low is not None else None

    def _effective_min_soc(self):
        bound = self._soc_lower_bound()
        if bound is None:
            retained = _number(self._memory.get("soc_floor_guard", {}).get("lower_bound"))
            bound = max(40, retained if retained is not None and 5 <= retained <= 90 else 40)
        return max(self._options["min_soc_percent"], bound)

    @property
    def effective_loads(self):
        """The public, effective meters, including any legacy default pump."""
        return self._redact(self._configured_channels())

    @property
    def loads_revision(self):
        snapshot = json.dumps(self.effective_loads, sort_keys=True, separators=(",", ":"))
        return sha256(snapshot.encode("utf-8")).hexdigest()[:24]

    def _redact(self, value):
        """Secrets stay exclusively in the private ConfigEntry options."""
        if isinstance(value, dict):
            return {k: self._redact(v) for k, v in value.items()
                    if str(k).lower() not in ("api_key", "apikey", "authorization", "access_token", "password", "token")}
        if isinstance(value, (list, tuple)):
            return [self._redact(item) for item in value]
        if isinstance(value, str):
            secret = self._options.get("solcast", {}).get("api_key")
            if isinstance(secret, str):
                for candidate in (secret, secret.strip()):
                    if candidate:
                        value = value.replace(candidate, "[redacted]")
            return value
        return deepcopy(value)

    def _solcast_configured(self):
        config = self._options.get("solcast", {})
        return bool(config.get("api_key")) and config.get("enabled", True) is not False

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
                elif key in ("grid_dispatch", "initial_charge_window") and key in saved and not isinstance(saved[key], dict):
                    self._memory[key] = {"invalid": True}
                elif isinstance(saved.get(key), dict):
                    self._memory[key] = saved[key]
        self._memory = self._redact(self._memory)
        # A restart retains the target latch, but cannot prove continuous safety.
        self._memory["current_policy"]["safe_since"] = None
        dispatch = self._memory["grid_dispatch"]
        if (dispatch.get("outcome") in ("prepared", "accepted", "uncertain")
                and isinstance(dispatch.get("positive_deadline"), str)):
            at = _number(dispatch.get("attempt_at"))
            if at is not None and at <= self._now().timestamp():
                self._memory["initial_charge_window"] = {"version": 1,
                    "deadline": dispatch["positive_deadline"], "at": at,
                    "id": dispatch.get("id"), "spent": True}
        if dispatch.get("outcome") == "prepared" and self._dispatch_history(self._now())["known"]:
            # A crash may have happened after a slow Store and actual dispatch.
            # An unfinished write-ahead record cannot grant an early retry.
            dispatch.update(outcome="uncertain", possible_at=self._now().timestamp())
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
        self._pending_grid_reduction = None
        self._grid_reduction_chain = None
        await self._cancel_planning()
        shutdown = getattr(super(), "async_shutdown", None)
        if shutdown is not None:
            await shutdown()

    async def async_set_option(self, key, value):
        if key not in DEFAULT_OPTIONS and key not in ("sources", "extra_loads"):
            raise ValueError("Unknown EMS setting")
        if key == "extra_loads":
            async with self._lock:
                await self._commit_loads_locked(value)
            await self.async_request_refresh()
            return
        if key == "sources":
            if not isinstance(value, dict) or any(k not in DEFAULT_SOURCES for k in value):
                raise ValueError("Invalid source mapping")
            if any(not isinstance(v, str) or (v and "." not in v) for v in value.values()):
                raise ValueError("Sources must be entity IDs")
        elif key == "solcast":
            raise ValueError("Configure credentials in the integration setup")
        elif key == "topology":
            if value not in ("load_only", "load_with_external_ct"):
                raise ValueError("Invalid metering topology")
        elif key == "pv_forecast_mode":
            if value not in ("whole_system", "specific_profile"):
                raise ValueError("Invalid PV forecast mode")
        elif key in ("pv_peak_kwp", "pv_forecast_reference_kwp") and value is None:
            if key == "pv_peak_kwp" and self.mode == "active":
                raise ValueError("Switch to shadow before clearing PV capacity")
        else:
            number = _number(value)
            low, high = OPTION_RANGES.get(key, (5, 300))[:2]
            if number is None or not low <= number <= high:
                raise ValueError("Setting outside its allowed range")
            value = int(number) if key == "update_seconds" else number
        async with self._lock:
            if key in ("sources", "extra_loads", "topology", "combined_output_limit_kw") and self.mode == "active":
                raise ValueError("Switch to shadow before changing hardware mappings")
            if key == "sources":
                value = {**self._sources, **value}
            candidate = {**self._options, key: value}
            if key == "min_soc_percent":
                bound = self._soc_lower_bound()
                if bound is None or value < bound:
                    raise ValueError("Rezerwa musi wynosić co najmniej Battery low SOC + 5 p.p.; wymagany poprawny odczyt encji.")
            if max(candidate["min_soc_percent"], self._soc_lower_bound() or 40) + candidate["reserve_margin_soc_percent"] > candidate["grid_max_soc_percent"]:
                raise ValueError("Minimum SoC plus reserve must not exceed the grid target ceiling")
            await self._cancel_planning()
            self._planning_revision += 1
            self._options[key] = value
            if key != "update_seconds":
                self._memory["plan"] = {}
            self._sources = {**DEFAULT_SOURCES, **self._options.get("sources", {})}
            if key in ("min_soc_percent", "reserve_margin_soc_percent", "sources", "extra_loads",
                       "pv_peak_kwp", "pv_forecast_reference_kwp", "pv_forecast_mode"):
                self._memory["target_cache"] = {}
                self._memory["safety_raise"] = {}
                self._memory["load_profiles"] = {}
            self._plan_due = 0
            self.update_interval = timedelta(seconds=self._update_seconds())
            self.hass.config_entries.async_update_entry(self.entry, options=dict(self._options))
            await self._save()
        await self.async_request_refresh()

    def _check_load_revision(self, expected):
        if not isinstance(expected, str) or expected != self.loads_revision:
            raise ValueError("Lista zużyć zmieniła się. Odśwież panel i spróbuj ponownie.")

    def _validate_loads(self, channels):
        if not isinstance(channels, list) or len(channels) > 32:
            raise ValueError("Lista może zawierać najwyżej 32 obwody.")
        previous = self._configured_channels()
        existing = {item["energy_entity"]: item["id"] for item in previous}
        previous_by_id = {item["id"]: item for item in previous}
        normalized, seen, ids, powers = [], set(), set(), set()
        for raw in channels:
            if not isinstance(raw, dict) or set(raw) - {
                    "id", "name", "energy_entity", "power_entity", "included_in_load", "enabled"}:
                raise ValueError("Nieprawidłowe pola obwodu.")
            name, energy = raw.get("name"), raw.get("energy_entity")
            power, included = raw.get("power_entity", ""), raw.get("included_in_load", True)
            if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 80
                    or any(ord(char) < 32 or ord(char) == 127 for char in name)):
                raise ValueError("Podaj nazwę obwodu od 1 do 80 znaków.")
            if not isinstance(energy, str) or not re.fullmatch(r"sensor\.[a-z0-9_]+", energy):
                raise ValueError("Wybierz prawidłowy sensor energii.")
            if energy in seen:
                raise ValueError("Ten licznik energii jest już używany przez inny obwód.")
            if not isinstance(included, bool):
                raise ValueError("Określ, czy obwód jest już zawarty w pomiarze domu.")
            # The installation's LOAD meter includes every appliance. Keep the
            # old field readable, but never treat any channel as extra demand.
            included = True
            if not isinstance(power, str) or (power and not re.fullmatch(r"sensor\.[a-z0-9_]+", power)):
                raise ValueError("Wybierz prawidłowy sensor mocy.")
            if power:
                if power in powers:
                    raise ValueError("Ten sensor mocy jest już używany przez inny obwód.")
                powers.add(power)
            channel_id = raw.get("id") or existing.get(energy) or uuid4().hex
            if (not isinstance(channel_id, str) or not 1 <= len(channel_id) <= 128
                    or not re.fullmatch(r"[a-zA-Z0-9_.-]+", channel_id) or channel_id in ids):
                raise ValueError("Nieprawidłowy lub powtórzony identyfikator obwodu.")
            seen.add(energy)
            ids.add(channel_id)
            old = previous_by_id.get(channel_id, {})
            enabled = raw.get("enabled", old.get("enabled", True))
            if not isinstance(enabled, bool):
                raise ValueError("Stan obserwacji obwodu musi być włączony lub wyłączony.")
            value = {"id": channel_id, "name": name.strip(), "energy_entity": energy,
                     "power_entity": power, "included_in_load": included, "enabled": enabled}
            # An unrelated broken/removed meter must never prevent repairing
            # or deleting another row. Validate metadata only for changed rows.
            source_fields = ("name", "energy_entity", "power_entity", "included_in_load")
            if enabled and any(old.get(key) != value[key] for key in source_fields):
                state = self.hass.states.get(energy)
                if state is None or state.attributes.get("unit_of_measurement") not in ("Wh", "kWh"):
                    raise ValueError("Sensor energii musi istnieć i mieć jednostkę Wh lub kWh.")
                if power:
                    state = self.hass.states.get(power)
                    if state is None or state.attributes.get("unit_of_measurement") not in ("W", "kW"):
                        raise ValueError("Sensor mocy musi istnieć i mieć jednostkę W lub kW.")
            normalized.append(value)
        return normalized

    async def _commit_loads_locked(self, channels):
        """Validate and persist under _lock, before an options reload can run."""
        if self.mode != "shadow":
            raise ValueError("Przełącz EMS w tryb obserwacji przed zmianą zużyć.")
        channels = self._validate_loads(channels)
        await self._cancel_planning()
        old_options, old_due = deepcopy(self._options), self._plan_due
        invalidated = ("plan", "target_cache", "safety_raise", "load_profiles")
        previous = {key: deepcopy(self._memory[key]) for key in invalidated}
        self._planning_revision += 1
        self._options.update(extra_loads=channels, extra_loads_managed=True)
        for key in invalidated:
            self._memory[key] = {}
        self._plan_due = 0
        try:
            await self._save()
        except BaseException:
            self._options = old_options
            self._memory.update(previous)
            self._plan_due = old_due
            raise
        self.hass.config_entries.async_update_entry(self.entry, options=deepcopy(self._options))

    async def async_save_load(self, original_energy_entity, channel, *, expected_revision):
        async with self._lock:
            if self.mode != "shadow":
                raise ValueError("Przełącz EMS w tryb obserwacji przed zmianą zużyć.")
            self._check_load_revision(expected_revision)
            if not isinstance(original_energy_entity, str) or not isinstance(channel, dict):
                raise ValueError("Nieprawidłowe dane obwodu.")
            if set(channel) - {"name", "energy_entity", "power_entity", "included_in_load", "enabled"}:
                raise ValueError("Nieprawidłowe pola obwodu.")
            channels = self._configured_channels()
            value = deepcopy(channel)
            if original_energy_entity:
                index = next((i for i, item in enumerate(channels)
                              if item["energy_entity"] == original_energy_entity), None)
                if index is None:
                    raise ValueError("Ten obwód nie istnieje już na liście. Odśwież panel.")
                value["id"] = channels[index]["id"]
                value.setdefault("enabled", channels[index]["enabled"])
                channels[index] = value
            else:
                value["id"] = uuid4().hex
                channels.append(value)
            await self._commit_loads_locked(channels)
        await self.async_request_refresh()

    async def async_delete_load(self, original_energy_entity, *, expected_revision):
        async with self._lock:
            if self.mode != "shadow":
                raise ValueError("Przełącz EMS w tryb obserwacji przed zmianą zużyć.")
            self._check_load_revision(expected_revision)
            channels = self._configured_channels()
            remaining = [item for item in channels if item["energy_entity"] != original_energy_entity]
            if len(remaining) == len(channels):
                raise ValueError("Ten obwód nie istnieje już na liście. Odśwież panel.")
            await self._commit_loads_locked(remaining)
        await self.async_request_refresh()

    async def async_toggle_load(self, original_energy_entity, enabled, *, expected_revision):
        async with self._lock:
            if self.mode != "shadow":
                raise ValueError("Przełącz EMS w tryb obserwacji przed zmianą zużyć.")
            self._check_load_revision(expected_revision)
            if not isinstance(enabled, bool):
                raise ValueError("Stan obserwacji obwodu musi być włączony lub wyłączony.")
            channels = self._configured_channels()
            index = next((i for i, item in enumerate(channels)
                          if item["energy_entity"] == original_energy_entity), None)
            if index is None:
                raise ValueError("Ten obwód nie istnieje już na liście. Odśwież panel.")
            channels[index]["enabled"] = enabled
            await self._commit_loads_locked(channels)
        await self.async_request_refresh()

    async def async_set_mode(self, mode):
        if mode not in ("shadow", "active"):
            raise ValueError("Choose shadow or active")
        async with self._lock:
            if mode == "active":
                self._preflight(retake=True)
                self._memory["observed_owners"] = {entity: True for entity in OWNER_ENTITIES
                                                    if self.hass.states.get(entity) is not None}
                if self.mode != "active" and self._memory["initial_charge_window"] == {}:
                    now = self._now()
                    inputs = self._read_inputs(now)
                    history = self._dispatch_history(now)
                    _, night, afternoon, deadline, _ = self._window(now)
                    if (night or afternoon) and inputs["current_a"] == 0 and history["known"] and (
                            history.get("upper_a") is None or history["upper_a"] == 0):
                        # Explicit activation may grant the one missing v16
                        # permission. Restoring an active mode never does this.
                        self._memory["initial_charge_window"] = {"version": 1,
                            "deadline": deadline.isoformat(), "at": now.timestamp(),
                            "id": uuid4().hex, "spent": False}
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
        async with self._store_lock:
            # Snapshot only after acquiring the lock. A queued forecast save
            # must include every newer quota reservation and hardware ledger.
            writing = asyncio.create_task(self._store.async_save(self._redact(self._memory)))
            try:
                await asyncio.shield(writing)
            except asyncio.CancelledError:
                # Do not release the writer lock while the actual disk write
                # is still running; a newer ledger must be written after it.
                await writing
                raise
            self._last_save_ts = self._now().timestamp()

    async def _cancel_planning(self):
        task = self._plan_task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._plan_task = None

    def _start_planning(self, now, inputs):
        if self._stopped or self._plan_task is not None and not self._plan_task.done():
            return
        self._plan_due = now.timestamp()+300
        coroutine = self._background_plan(now, deepcopy(inputs))
        if hasattr(self.hass, "async_create_background_task"):
            self._plan_task = self.hass.async_create_background_task(coroutine, "Deye EMS forecast and plan")
        elif hasattr(self.hass, "async_create_task"):
            self._plan_task = self.hass.async_create_task(coroutine, "Deye EMS forecast and plan")
        else:  # Offline framework stub.
            self._plan_task = asyncio.create_task(coroutine, name="Deye EMS forecast and plan")

    async def _background_plan(self, now, inputs):
        try:
            await self._make_plan(now, inputs)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self._last_error = f"background_plan_failed:{type(error).__name__}"
            self._plan_due = self._now().timestamp()+60

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

    def _grid_charge_setting_limits(self, now, *, deye_live):
        """Read the independent Deye limit; never use the controlled setpoint.

        Number settings can be latched for hours. Their availability, units and
        report timestamp are checked, while native GRID and LOAD powers from
        the same inverter must establish current communication independently.
        Broad HA number ranges are only API limits, not hardware authority.
        """
        deye = self._measurement("max_charge_current_number", now, unit="A", low=0, high=1000)
        distinct = (self._sources.get("max_charge_current_number")
                    and self._sources.get("max_charge_current_number") != self._sources.get("grid_current_number"))
        deye_cap = math.floor(deye * 95 / 100) if deye is not None and distinct and deye_live else None
        actuator = self._state("grid_current_number")
        actuator_cap = None
        if deye_cap is not None and actuator is not None:
            if "max" not in actuator.attributes:
                actuator_cap = deye_cap
            else:
                maximum = _number(actuator.attributes["max"])
                if maximum is not None and maximum >= 0:
                    actuator_cap = min(deye_cap, math.floor(maximum))
        return {"deye_max_charge_current_a": deye,
                "deye_grid_charge_limit_a": deye_cap,
                "grid_charge_actuator_max_a": actuator_cap,
                "grid_charge_limit_valid": deye_cap is not None and actuator_cap is not None}

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
        # ESPHome can publish this latched flag only on change. Its available,
        # non-restored setting is anchored by the same BMS's live voltage.
        block = self._measurement("bms_blocking_charge", now, low=0, high=1000)
        bms_valid = voltage is not None and None not in (charge, block)
        cap = charge if bms_valid and block == 0 else 0
        current = self._measurement("grid_current_number", now, unit="A", low=0, high=1000)
        battery = self._measurement("battery_power", now, unit="W", age=30, low=-60000, high=60000)
        raw_load = powers["load_power"]
        limits = self._grid_charge_setting_limits(now, deye_live=all(v is not None for v in powers.values()))
        limits["grid_charge_limit_valid"] = limits["grid_charge_limit_valid"] and current is not None
        inputs = {**powers, "soc": soc, "soc_valid": bool(soc_valid), "voltage": voltage,
                "current_a": current, "bms_cap_a": cap, "bms_valid": bms_valid,
                **limits,
                "battery_power": battery,
                "outside_load_w": 0, "outside_power_valid": True, "raw_load_power": raw_load,
                "total_load_with_outside_w": raw_load,
                "telemetry_valid": voltage is not None and current is not None and
                bms_valid and limits["grid_charge_limit_valid"] and all(v is not None for v in powers.values())}
        inputs["grid_charge_balanced"] = self._grid_charge_balanced(inputs, now)
        inputs["topology"] = self._options["topology"]
        mode_state = self._state("work_mode")
        inputs["inverter_work_mode"] = (mode_state.state if mode_state is not None
            and not mode_state.attributes.get("restored", False) and mode_state.state not in _BAD else None)
        inputs["grid_port_power"] = powers["grid_power"]
        # Keep the physical port and its native LOAD intact when CT replaces
        # the public utility balance and full-house LOAD below.
        for i in (1, 2, 3):
            inputs[f"grid_port_l{i}_power"] = powers[f"grid_l{i}_power"]
            inputs[f"raw_load_l{i}_power"] = powers[f"load_l{i}_power"]
        inputs["topology_error"] = None
        inputs["load_and_grid_output_w"] = None
        if self._options["topology"] == "load_with_external_ct":
            keys = ("ct_grid_power", "ct_grid_l1_power", "ct_grid_l2_power", "ct_grid_l3_power")
            ct = {key: self._measurement(key, now, unit="W", age=30, low=-60000, high=60000)
                  for key in keys}
            try:
                meter_keys = (*keys, "grid_power", "grid_l1_power", "grid_l2_power", "grid_l3_power")
                ids = [self._sources.get(key) for key in meter_keys]
                if any(not entity for entity in ids) or len(set(ids)) != len(ids):
                    raise ValueError("ct_and_grid_port_require_distinct_meters")
                reports = [_stamp(getattr(self._state(key), "last_reported", None) or
                                  getattr(self._state(key), "last_updated", None)) for key in meter_keys]
                if None in reports or max(reports)-min(reports) > 10:
                    raise ValueError("ct_and_grid_port_not_synchronised")
                balance = ct_load_balance(raw_load, [powers[f"load_l{i}_power"] for i in (1, 2, 3)],
                    powers["grid_power"], [powers[f"grid_l{i}_power"] for i in (1, 2, 3)],
                    ct["ct_grid_power"], [ct[f"ct_grid_l{i}_power"] for i in (1, 2, 3)])
                inputs.update(outside_load_w=balance["outside_load_w"],
                    load_power=balance["total_load_w"], total_load_with_outside_w=balance["total_load_w"],
                    grid_power=balance["grid_w"], load_and_grid_output_w=balance["load_and_grid_output_w"])
                for i in (1, 2, 3):
                    inputs[f"load_l{i}_power"] = balance["total_load_phases_w"][i-1]
                    inputs[f"grid_l{i}_power"] = balance["grid_phases_w"][i-1]
            except (ValueError, TypeError):
                inputs.update(telemetry_valid=False, outside_power_valid=False,
                              outside_load_w=None, load_power=None, grid_power=None,
                              total_load_with_outside_w=None, topology_error="invalid_ct_grid_balance")
            # CT phase regulation is not inferred from the Load-mode switch.
            inputs["grid_charge_balanced"] = False
        bound = self._soc_lower_bound()
        inputs.update(min_soc_lower_bound=bound, effective_min_soc_percent=self._effective_min_soc())
        if bound is None or self._effective_min_soc() + self._options["reserve_margin_soc_percent"] > self._options["grid_max_soc_percent"]:
            inputs["telemetry_valid"] = False
            inputs["grid_charge_balanced"] = None
        # A solar/local charging credit must compare the same physical instant.
        # Use the inverter GRID port, never utility CT (which includes bypass
        # loads). _measurement already validates availability, units and age.
        charge_keys = ("battery_power", "grid_power", "grid_l1_power", "grid_l2_power", "grid_l3_power")
        reports = [_stamp(getattr(self._state(key), "last_reported", None) or
                          getattr(self._state(key), "last_updated", None)) for key in charge_keys]
        charge_ids = [self._sources.get(key) for key in charge_keys]
        inputs["charge_power_valid"] = (battery is not None and all(v is not None for v in powers.values())
            and all(charge_ids) and len(set(charge_ids)) == len(charge_ids)
            and all(at is not None and 0 <= now.timestamp() - at <= 30 for at in reports)
            and max(reports) - min(reports) <= 10)
        if not inputs["charge_power_valid"]:
            inputs["telemetry_valid"] = False
            inputs["grid_charge_balanced"] = None
        return inputs

    def _grid_charge_balanced(self, inputs, now):
        flag, mode = self._state("asymmetric_phase_feeding"), self._state("work_mode")
        if (flag is None or flag.state not in ("on", "off") or flag.attributes.get("restored", False)
                or mode is None or mode.state in _BAD or mode.attributes.get("restored", False)):
            return None
        report = _stamp(getattr(flag, "last_reported", None) or getattr(flag, "last_updated", None))
        if report is None or report > now.timestamp():
            return None
        if flag.state == "off" or mode.state != "Zero Export To Load":
            return False
        # The switch is latched; its available value is anchored by fresh live
        # power/BMS telemetry, rather than expiring an unchanged ON setting.
        return True if inputs["telemetry_valid"] else None

    def _configured_channels(self):
        """Full meter configuration, including OFF rows and the legacy pump."""
        channels, seen = [], set()
        for raw in self._options.get("extra_loads", []):
            if not isinstance(raw, dict):
                continue
            entity = raw.get("energy_entity")
            if not isinstance(entity, str) or not entity or entity in seen:
                continue
            seen.add(entity)
            channels.append({"id": raw.get("id") or entity,
                "name": str(raw.get("name") or entity), "energy_entity": entity,
                "power_entity": raw.get("power_entity", ""), "included_in_load": True,
                "enabled": raw.get("enabled", True) is True})
        pump = self._sources.get("pc_energy_total")
        if pump and pump not in seen and self._options.get("extra_loads_managed") is not True:
            channels.append({"id": "configured_heatpump", "name": "Pompa ciepła", "energy_entity": pump,
                             "power_entity": "", "included_in_load": True, "enabled": True})
        return channels

    def _channels(self):
        """Only enabled meters are observed or separately modelled."""
        return [channel for channel in self._configured_channels() if channel["enabled"]]

    def _owner_conflicts(self, *, ignore_missing=False):
        return [entity_id for entity_id in OWNER_ENTITIES
                if ((state := self.hass.states.get(entity_id)) is not None and state.state != "off")
                or (not ignore_missing and state is None and entity_id in self._memory["observed_owners"])]

    def _hardware_modes_ok(self):
        return not self._hardware_mode_issues()

    def _hardware_mode_issues(self):
        expected_mode = ("Zero Export To CT" if self._options["topology"] == "load_with_external_ct"
                         else "Zero Export To Load")
        required = (("solar_sell", "Solar Sell", "on"),
                    ("tou_enabled", "Time of Use", "on"),
                    ("energy_priority", "Energy Management Priority", "Load First"),
                    ("work_mode", "System Work Mode", expected_mode))
        issues = []
        for key, label, expected in required:
            state = self._state(key)
            if state is None:
                actual = "brak encji — sprawdź przypisanie w Źródłach"
            elif state.attributes.get("restored", False):
                actual = "stan odtworzony po restarcie — oczekiwanie na odczyt"
            elif state.state != expected:
                actual = str(state.state)
            else:
                continue
            entity = self._sources.get(key) or "nie przypisano encji"
            issues.append(f"{label} ({entity}): odczyt [{actual}], wymagane [{expected}]")
        return issues

    def _clocks_ok(self, now):
        winter = self._window(now)[0]
        clocks = ("00:00:00", "04:00:00", "07:00:00", "13:00:00",
                  "16:00:00" if winter else "19:00:00", "21:00:00" if winter else "22:00:00")
        return all((state := self._state(f"tou_time_{slot}")) is not None and
                   state.state == clock and not state.attributes.get("restored", False)
                   for slot, clock in enumerate(clocks, 1))

    def _preflight(self, *, retake=False):
        if self._soc_lower_bound() is None:
            raise ValueError("Wymagany poprawny odczyt Battery low SOC; sprawdź przypisanie encji i jednostkę %.")
        if self._effective_min_soc() + self._options["reserve_margin_soc_percent"] > self._options["grid_max_soc_percent"]:
            raise ValueError("Rezerwa Battery low SOC + 5 p.p. wraz z buforem przekracza maksymalny cel ładowania.")
        if self._options["topology"] not in ("load_only", "load_with_external_ct"):
            raise ValueError("Unknown metering topology")
        if self._owner_conflicts(ignore_missing=retake):
            raise ValueError("Existing previous controllers must be OFF and observed controllers available")
        now = self._now()
        installed = _number(self._options.get("pv_peak_kwp"))
        if installed is None or not .1 <= installed <= 1000:
            raise ValueError("Enter the installed PV capacity before activating control")
        if self._options.get("pv_forecast_mode", "whole_system") == "specific_profile":
            reference = _number(self._options.get("pv_forecast_reference_kwp"))
            if reference is None or not .1 <= reference <= 1000:
                raise ValueError("A specific PV profile requires its reference capacity")
        inputs = self._read_inputs(now)
        if inputs.get("topology_error"):
            raise ValueError("Topologia CT: wymagane są osobne świeże pomiary CT i portu GRID (suma i fazy), zgodne kierunki i bilans faz")
        if not inputs["telemetry_valid"] or not inputs["soc_valid"]:
            raise ValueError("Activation requires fresh, valid power and battery measurements")
        mode_issues = self._hardware_mode_issues()
        if mode_issues:
            raise ValueError("Nie można włączyć sterowania. " + "; ".join(mode_issues))
        writable = [self._sources.get("grid_current_number")]
        for slot in range(1, 7):
            writable += [self._sources.get(f"tou_soc_{slot}"), self._sources.get(f"tou_gc_{slot}"),
                         self._sources.get(f"tou_time_{slot}")]
        if len(set(writable)) != len(writable) or any(
                not entity_id or (state := self.hass.states.get(entity_id)) is None or
                state.state in _BAD for entity_id in writable):
            raise ValueError("Every writable source must exist and have a unique mapping")

    def _dispatch_history(self, now, *, own_attempt=None):
        """Keep the last possible command separate from register readback ACK."""
        epoch = now.timestamp()
        def valid_time(value):
            return (value is None or isinstance(value, (int, float)) and not isinstance(value, bool)
                    and math.isfinite(value) and 0 <= value <= epoch)
        state = self._memory.get("grid_dispatch")
        if state == {}:
            old = self._memory["ledger"].get(self._sources["grid_current_number"], {})
            if old == {}:
                return {"known": True, "possible_at": None, "possible_a": None, "upper_a": None, "not_sent_at": None}
            at, amps = (old.get("at"), old.get("a")) if isinstance(old, dict) else (None, None)
            if (isinstance(old, dict) and at is not None and valid_time(at)
                    and isinstance(amps, (int, float)) and not isinstance(amps, bool)
                    and math.isfinite(amps) and 0 <= amps <= 1000):
                return {"known": True, "possible_at": at, "possible_a": amps, "upper_a": amps, "not_sent_at": None}
            return {"known": False}
        if not isinstance(state, dict) or state.get("outcome") not in ("prepared", "accepted", "uncertain", "not_sent"):
            return {"known": False}
        if not all(key in state for key in ("possible_at", "possible_a", "not_sent_at", "attempt_at")):
            return {"known": False}
        if state["attempt_at"] is None or not all(valid_time(state.get(key)) for key in
                ("possible_at", "not_sent_at", "attempt_at", "previous_possible_at")):
            return {"known": False}
        at, amps = state["possible_at"], state["possible_a"]
        if ((at is None) != (amps is None) or amps is not None and
                (not isinstance(amps, (int, float)) or isinstance(amps, bool)
                 or not math.isfinite(amps) or not 0 <= amps <= 1000)):
            return {"known": False}
        upper = state.get("unconfirmed_upper_a", amps)
        if ((amps is None) != (upper is None) or upper is not None and
                (not isinstance(upper, (int, float)) or isinstance(upper, bool)
                 or not math.isfinite(upper) or not amps <= upper <= 1000)):
            return {"known": False}
        if (own_attempt is not None and state.get("id") == own_attempt["id"]
                and state["outcome"] == "prepared" and at == state["attempt_at"]):
            at, amps = state.get("previous_possible_at"), state.get("previous_possible_a")
            upper = state.get("previous_upper_a", amps)
        return {"known": True, "possible_at": at, "possible_a": amps, "upper_a": upper,
                "not_sent_at": state["not_sent_at"]}

    def _initial_record_valid(self, record, now):
        if (not isinstance(record, dict) or record.get("version") != 1
                or not isinstance(record.get("deadline"), str)
                or not isinstance(record.get("id"), str) or not record["id"]
                or not isinstance(record.get("spent"), bool)
                or _number(record.get("at")) is None
                or not 0 <= record["at"] <= now.timestamp()):
            return False
        try:
            at = datetime.fromtimestamp(record["at"], _TZ)
            _, night, afternoon, deadline, _ = self._window(at)
            return (night or afternoon) and record["deadline"] == deadline.isoformat()
        except (ValueError, OverflowError, OSError):
            return False

    def _new_initial_window_proven(self, now):
        _, night, afternoon, _, _ = self._window(now)
        if not (night or afternoon):
            return False
        if afternoon:
            begin = now.replace(hour=13, minute=0, second=0, microsecond=0)
        else:
            # Before07:00 the night began on the previous calendar date;
            # its season, not today's month, determines21:00 versus22:00.
            begin_date = now - timedelta(days=1) if now.hour < 7 else now
            late = 21 if begin_date.month in (10, 11, 12, 1, 2, 3) else 22
            begin = begin_date.replace(hour=late, minute=0, second=0, microsecond=0)
        own = self._current_grid_attempt
        if own is not None and own["outcome"] != "not_sent":
            own = None
        history = self._dispatch_history(now, own_attempt=own)
        return history["known"] and (history.get("possible_at") is None or
                                      history["possible_at"] < begin.timestamp())

    def _initial_window_started(self, now):
        record = self._memory.get("initial_charge_window")
        if record == {}:
            return not self._new_initial_window_proven(now)
        if not self._initial_record_valid(record, now):
            return True  # Malformed/future permission records fail closed.
        if record["deadline"] == self._window(now)[3].isoformat():
            return record["spent"]
        return not self._new_initial_window_proven(now)

    def _prepare_initial_window(self, now):
        record = self._memory["initial_charge_window"]
        if record != {} and not self._initial_record_valid(record, now):
            return False
        if record and record["deadline"] == self._window(now)[3].isoformat():
            return False
        if not self._new_initial_window_proven(now):
            return False
        self._memory["initial_charge_window"] = {"version": 1,
            "deadline": self._window(now)[3].isoformat(), "at": now.timestamp(),
            "id": uuid4().hex, "spent": False}
        return True

    def _ordinary_dispatch_ready(self, now, *, own_attempt=None):
        history = self._dispatch_history(now, own_attempt=own_attempt)
        if not history["known"]:
            return False
        if dispatch_ready(now.timestamp(), history.get("possible_at"), history.get("not_sent_at")):
            return True
        inputs = self._read_inputs(now)
        target, emergency, _ = self._target(now)
        g = self._grid_input(inputs, now, target, emergency)
        return (initial_dispatch_ready(g) and (own_attempt is None or
                own_attempt.get("initial_permission") is True and
                own_attempt.get("initial_deadline") == g["policy_deadline"]))

    async def _service(self, entity_id, action, value=None):
        if (self._soc_lower_bound() is None and entity_id != self._sources["grid_current_number"]
                and action != "turn_off"):
            self._last_error = "battery_low_soc_unavailable"
            return False
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
        floor = self._effective_min_soc()
        allowed = (night or afternoon) and (winter or emergency or
                   inputs["soc"] is not None and inputs["soc"] < floor)
        live_grid = self._grid_input(inputs, now, target, emergency)
        cap = calculate_grid_charge_cap(live_grid)
        live_need = calculate_grid_charge_demand(live_grid)["need_a"]
        rounded_need = math.ceil(live_need / QUANTUM_A) * QUANTUM_A
        if entity_id == self._sources["grid_current_number"] and value > 0:
            if (live_need <= 0 or inputs["current_a"] is not None
                    and value > inputs["current_a"] and value > rounded_need):
                self._last_error = "last_moment_charge_need_guard"
                return False
            context = self._current_grid_attempt
            if (context is not None and not context["ordinary"]
                    and (inputs["current_a"] is None or value > inputs["current_a"])):
                # A reduction prepared before Store must not become an
                # unthrottled increase after a new register report arrives.
                self._last_error = "last_moment_safety_direction_guard"
                return False
            if context is not None and context["ordinary"]:
                if (context.get("positive_deadline") is not None and
                        context["positive_deadline"] != live_grid["policy_deadline"]):
                    self._last_error = "last_moment_initial_window_guard"
                    return False
                if (context.get("initial_start") is True and
                        (inputs["current_a"] != 0 or context.get("initial_deadline") != live_grid["policy_deadline"])):
                    self._last_error = "last_moment_initial_start_guard"
                    return False
                delta = abs(value - inputs["current_a"]) if inputs["current_a"] is not None else None
                starting_small = inputs["current_a"] == 0 and value > 0
                if (not self._ordinary_dispatch_ready(now, own_attempt=context)
                        or inputs["current_a"] is None
                        or not (starting_small or delta >= DEADBAND_A)
                        or value >= QUANTUM_A and value % QUANTUM_A != 0
                        or self._memory["current_policy"].get("stopped", True)
                        or not self._current_policy_stable(now)):
                    self._last_error = "last_moment_dispatch_guard"
                    return False
            if inputs["current_a"] is not None and value > inputs["current_a"]:
                g = self._grid_input(inputs, now, target, emergency)
                if value > calculate_grid_charge_increase_cap(g)["increase_cap_a"]:
                    self._last_error = "last_moment_grid_step_guard"
                    return False
            reducing_safely = (inputs["current_a"] is not None and 0 < value < inputs["current_a"]
                               and cap["grid_within_limits"] and value <= cap["hard_current_cap_a"])
            if not (allowed and inputs["soc_valid"] and inputs["telemetry_valid"] and
                    inputs["soc"] < target and self._hardware_modes_ok()
                    and (value <= cap["cap_a"] or reducing_safely)):
                self._last_error = "last_moment_current_guard"
                return False
        if action == "turn_on":
            if self._memory["current_policy"].get("stopped", True):
                return False
            requested = self._memory["ledger"].get(self._sources["grid_current_number"], {}).get("a", 0)
            setting = self._measurement(f"tou_soc_{active_slot}", now, unit="%", low=0, high=100)
            expected_time = ("00:00:00", "04:00:00", "07:00:00", "13:00:00",
                             "16:00:00" if winter else "19:00:00", "21:00:00" if winter else "22:00:00")[active_slot - 1]
            clock = self._state(f"tou_time_{active_slot}")
            starting = self._grid_input(inputs, now, target, emergency)
            starting["current_a"] = 0
            start_cap = calculate_grid_charge_increase_cap(starting)["increase_cap_a"]
            pending = starting["pending_current_a"]
            if not (entity_id == self._sources[f"tou_gc_{active_slot}"] and active_slot not in (3, 5)
                    and allowed and self._hardware_modes_ok() and self._clocks_ok(now) and inputs["soc_valid"]
                    and inputs["soc"] < target and
                    live_need > 0 and requested <= rounded_need and
                    self._settled_grid(inputs, now, requested) and requested <= cap["cap_a"] and requested <= start_cap
                    and (pending is None or pending <= start_cap) and
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
            current_attempt = self._current_grid_attempt if entity_id == self._sources["grid_current_number"] else None
            if current_attempt is not None:
                current_attempt.update(outcome="uncertain", dispatch_at=self._now().timestamp())
                if current_attempt.get("positive_deadline") is not None:
                    self._memory["initial_charge_window"] = {"version": 1,
                        "deadline": current_attempt["positive_deadline"],
                        "at": current_attempt["dispatch_at"], "id": current_attempt["id"], "spent": True}
                    self._memory["current_policy"]["initial_started"] = True
            await asyncio.wait_for(self.hass.services.async_call(
                domain, action, data, blocking=True), timeout=10)
            if current_attempt is not None:
                current_attempt["outcome"] = "accepted"
            return True
        except Exception as error:  # The persisted attempt survives transport failure.
            self._last_error = f"command_failed:{type(error).__name__}"
            return False

    async def _attempt(self, entity_id, action, value, now_ts, *, cooldown, force=False, current_attempt=None):
        old = self._memory["ledger"].get(entity_id, {})
        if not isinstance(old, dict):
            self._last_error = "invalid_attempt_ledger"
            return False
        attempted, previous = _number(old.get("at")), old.get("a")
        if attempted is not None:
            if attempted > now_ts:
                if force and value == 0 and entity_id == self._sources["grid_current_number"]:
                    attempted = None  # An invalid clock must not delay a stricter zero.
                else:
                    self._last_error = "future_attempt_ledger"
                    return False
        if attempted is not None:
            # Even safety retries must not flood the device with an identical
            # unacknowledged command. Ordinary writes have their own cooldown.
            identical = previous == value and old.get("action") == action
            if now_ts - attempted < (10 if force and identical else cooldown if not force else 0):
                return False
        if current_attempt is not None:
            previous = current_attempt["previous"]
            self._memory["grid_dispatch"] = {
                "id": current_attempt["id"], "outcome": "prepared", "attempt_at": now_ts,
                "possible_at": now_ts, "possible_a": value,
                "previous_possible_at": previous.get("possible_at"),
                "previous_possible_a": previous.get("possible_a"),
                "unconfirmed_upper_a": max(value, previous.get("upper_a") or 0),
                "previous_upper_a": previous.get("upper_a"),
                "initial_start": current_attempt.get("initial_start", False),
                "initial_deadline": current_attempt.get("initial_deadline"),
                "positive_deadline": current_attempt.get("positive_deadline"),
                "not_sent_at": previous.get("not_sent_at")}
            current_attempt.update(prepared=True, prepared_at=now_ts)
        self._memory["ledger"][entity_id] = {"at": now_ts, "a": value, "action": action}
        try:
            await self._save()  # Mandatory durable journal BEFORE every command.
        except Exception:
            self._last_error = "attempt_store_failed"
            return False
        return await self._service(entity_id, action, value)

    def _observe_reduction_readback(self, inputs):
        chain = self._grid_reduction_chain
        if chain is None:
            return
        state = self._state("grid_current_number")
        report = _stamp(getattr(state, "last_reported", None) or getattr(state, "last_updated", None))
        current = inputs["current_a"]
        if (current is not None and 0 <= current <= chain["to_a"]
                and report is not None and report >= chain["attempt_at"]):
            # A register read confirms the requested setting, never physical
            # battery current. Only this observation closes the timed chain.
            self._grid_reduction_chain = None
            self._pending_grid_reduction = None

    async def _grid_attempt(self, value, now_ts, *, force=False):
        value = int(value)
        before = self._read_inputs(self._now())
        self._observe_reduction_readback(before)
        chain = self._grid_reduction_chain
        old_ledger = deepcopy(self._memory["ledger"].get(self._sources["grid_current_number"], {}))
        ordinary = value > 0 and not (force and before["current_a"] is not None and value <= before["current_a"])
        if not ordinary:
            # A synchronous register readback after a safety reduction must not
            # hide the interruption from this tick's later policy observation.
            self._memory["current_policy"]["safe_since"] = None
        now = self._now()
        if ordinary and not self._ordinary_dispatch_ready(now):
            return False
        target, emergency, _ = self._target(now)
        initial_grid = self._grid_input(before, now, target, emergency)
        initial = ordinary and before["current_a"] == 0 and not self._initial_window_started(now)
        context = {"id": uuid4().hex, "ordinary": ordinary, "outcome": "not_sent", "prepared": False,
                   "previous": self._dispatch_history(now),
                   "initial_start": initial, "initial_permission": initial_dispatch_ready(initial_grid),
                   "initial_deadline": initial_grid["policy_deadline"] if initial else None,
                   "positive_deadline": initial_grid["policy_deadline"] if value > 0 and initial_grid["cheap_window"] else None}
        if value <= 0:
            self._pending_grid_reduction = None
        self._current_grid_attempt = context
        try:
            accepted = await self._attempt(self._sources["grid_current_number"], "set_value", value,
                                           now_ts, cooldown=10, force=force, current_attempt=context)
        finally:
            self._current_grid_attempt = None
        state = self._memory["grid_dispatch"]
        if (context["prepared"] and state.get("id") == context["id"]
                and state.get("outcome") == "prepared" and state.get("possible_at") == context["prepared_at"]):
            state["outcome"] = context["outcome"]
            if context["outcome"] == "not_sent":
                state.update(possible_at=context["previous"].get("possible_at"),
                             possible_a=context["previous"].get("possible_a"),
                             unconfirmed_upper_a=context["previous"].get("upper_a"), not_sent_at=self._now().timestamp())
            else:
                state.update(possible_at=context["dispatch_at"], possible_a=value)
            try:
                await self._save()
            except Exception:
                # The durable prepared record remains conservative on restart.
                self._last_error = "grid_outcome_store_failed"
        ledger = self._memory["ledger"].get(self._sources["grid_current_number"], {})
        if accepted:
            current = before["current_a"]
            unexpected = (chain is not None and current is not None
                          and current > chain["last_observed_a"] + .01)
            if chain is not None:
                chain.update(to_a=value, attempt_at=ledger.get("at"))
            if (before["grid_charge_balanced"] is True and current is not None
                    and 0 < value < current and not unexpected):
                if chain is None:
                    chain = {"started_at": context.get("dispatch_at", self._now().timestamp()), "to_a": value,
                             "attempt_at": ledger.get("at"), "last_observed_a": current}
                    self._grid_reduction_chain = chain
                self._pending_grid_reduction = {
                    "from_a": current, "to_a": value, "last_observed_a": current,
                    "started_at": chain["started_at"], "attempt_at": ledger.get("at"),
                }
            else:
                self._pending_grid_reduction = None
        elif ledger != old_ledger:
            # A durable attempt alone proves nothing about dispatch success.
            # Keep the independent chain clock: failure is not readback ACK.
            self._pending_grid_reduction = None
        return accepted

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
        floor = self._effective_min_soc()
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
        winter, night, afternoon, deadline, active_slot = self._window(now)
        ledger = self._memory["ledger"].get(self._sources["grid_current_number"], {})
        if not isinstance(ledger, dict):
            ledger = {"at": None, "a": None}
        # A newly created ledger starts at zero. Invalid persisted data remains
        # invalid and inhibits increases in the pure controller.
        own = self._current_grid_attempt
        if own is not None and own["outcome"] != "not_sent":
            own = None
        history = self._dispatch_history(now, own_attempt=own)
        possible = history.get("possible_a")
        state = self._state("grid_current_number")
        report = _stamp(getattr(state, "last_reported", None) or getattr(state, "last_updated", None))
        confirmed = (possible is not None and inputs["current_a"] == possible and report is not None
                     and history.get("possible_at") is not None and report > history["possible_at"])
        if confirmed and self._memory["grid_dispatch"] and own is None:
            self._memory["grid_dispatch"]["unconfirmed_upper_a"] = possible
        gc = self._state(f"tou_gc_{active_slot}")
        gc_report = _stamp(getattr(gc, "last_reported", None) or getattr(gc, "last_updated", None))
        charging = (gc is not None and gc.state == "on" and not gc.attributes.get("restored", False)
                    and gc_report is not None and gc_report <= now.timestamp() and inputs["telemetry_valid"])
        initial_started = self._initial_window_started(now)
        policy = {**self._memory["current_policy"], "initial_started": initial_started}
        return {"now_ts": now.timestamp(), "winter": winter, "cheap_window": night or afternoon,
                "policy_deadline": deadline.isoformat(),
                "current_policy": policy, "initial_window_started": initial_started,
                "hardware_ok": self._hardware_modes_ok(),
                "ordinary_history_known": history["known"],
                "ordinary_last_possible_ts": history.get("possible_at"),
                "ordinary_last_not_sent_ts": history.get("not_sent_at"),
                "pending_current_a": None if confirmed else history.get("upper_a"),
                "grid_charge_active": bool(charging),
                "emergency_allowed": emergency, "safety_only": safety_only,
                "soc_valid": inputs["soc_valid"], "soc": inputs["soc"], "target_soc": target,
                "remaining_h": (deadline.timestamp() - now.timestamp()) / 3600,
                "minimum_soc_percent": self._effective_min_soc(),
                "minimum_soc_lower_bound": self._soc_lower_bound(),
                "capacity_kwh": self._options["capacity_kwh"],
                "bms_cap_a": inputs["bms_cap_a"], "telemetry_valid": inputs["telemetry_valid"],
                "deye_cap_a": inputs["deye_grid_charge_limit_a"],
                "actuator_cap_a": inputs["grid_charge_actuator_max_a"],
                "load_w": inputs["load_power"], "grid_w": inputs["grid_power"],
                "outside_load_w": 0 if self._options["topology"] == "load_with_external_ct" else inputs["outside_load_w"],
                "load_phases_w": [inputs[f"load_l{i}_power"] for i in (1, 2, 3)],
                "grid_phases_w": [inputs[f"grid_l{i}_power"] for i in (1, 2, 3)],
                "grid_port_w": inputs["grid_port_power"],
                "grid_port_phases_w": [inputs[f"grid_port_l{i}_power"] for i in (1, 2, 3)],
                "grid_port_load_w": inputs["raw_load_power"],
                "grid_port_load_phases_w": [inputs[f"raw_load_l{i}_power"] for i in (1, 2, 3)],
                "battery_voltage_v": inputs["voltage"], "current_a": inputs["current_a"],
                "battery_power_w": inputs.get("battery_power"),
                "battery_total_cap_a": (min(inputs["bms_cap_a"], inputs["deye_max_charge_current_a"])
                    if inputs["telemetry_valid"] and inputs.get("bms_valid") is True
                    and inputs.get("grid_charge_limit_valid") is True
                    and inputs.get("bms_cap_a") is not None and inputs.get("deye_max_charge_current_a") is not None else None),
                "grid_charge_balanced": inputs.get("grid_charge_balanced"),
                "last_attempt_ts": ledger.get("at", 0), "last_attempt_a": ledger.get("a", 0),
                "total_limit_w": self._options["grid_import_limit_kw"] * 1000,
                "phase_limit_w": self._options["grid_phase_limit_kw"] * 1000,
                "inverter_grid_import_limit_w": self._options["inverter_max_power_kw"] * 1000,
                "inverter_grid_phase_limit_w": self._options["inverter_phase_max_power_kw"] * 1000,
                "conversion_total_limit_w": min(self._options.get("inverter_max_power_kw", 12),
                    self._options["combined_output_limit_kw"] if self._options["topology"] == "load_with_external_ct"
                    else self._options.get("inverter_max_power_kw", 12)) * 1000,
                "conversion_phase_limit_w": self._options.get("inverter_phase_max_power_kw", 5) * 1000,
                "headroom_w": 500, "phase_headroom_w": 250,
                "charge_efficiency": .9, "charge_storage_efficiency": .95}

    def _current_policy_stable(self, now):
        policy = self._memory["current_policy"]
        since, observed = _number(policy.get("safe_since")), _number(policy.get("observed_at"))
        return (since is not None and observed is not None
                and 0 <= now.timestamp() - observed <= 30
                and 120 <= now.timestamp() - since)

    def _pending_reduction_ok(self, inputs, now, requested, cap):
        self._observe_reduction_readback(inputs)
        pending = self._pending_grid_reduction
        if pending is None:
            return False
        ledger = self._memory["ledger"].get(self._sources["grid_current_number"], {})
        current = inputs["current_a"]
        valid = (not self._stopped and self.mode == "active" and not self._owner_conflicts()
                 and inputs["grid_charge_balanced"] is True
                 and cap["telemetry_ok"] and cap["grid_within_limits"]
                 and 0 <= now.timestamp() - pending["started_at"] <= 30
                 and ledger.get("at") == pending["attempt_at"] and ledger.get("a") == pending["to_a"]
                 and ledger.get("action") == "set_value"
                 and current is not None and 0 < current <= pending["last_observed_a"] + .01
                 and current <= cap["hard_current_cap_a"] and 0 < requested <= cap["hard_current_cap_a"])
        if valid:
            pending["last_observed_a"] = current
            if self._grid_reduction_chain is not None:
                self._grid_reduction_chain["last_observed_a"] = current
        else:
            self._pending_grid_reduction = None
        # The separate unconfirmed chain survives expired/failed proof. Thus
        # neither a transport failure nor a new accepted retry renews 30s.
        return bool(valid)

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
        floor = self._effective_min_soc()
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
        current_winter, current_night, current_afternoon, _, _ = self._window(self._now())
        permitted = (current_night or current_afternoon) and (current_winter or emergency or
                                              observed["soc"] is not None and observed["soc"] < floor)
        active_gc = self._state(f"tou_gc_{active_slot}")
        observed_grid = self._grid_input(observed, self._now(), target, emergency)
        cap = calculate_grid_charge_cap(observed_grid)
        observed_need = calculate_grid_charge_demand(observed_grid)["need_a"]
        observed_rounded_need = math.ceil(observed_need / QUANTUM_A) * QUANTUM_A
        pending_a = observed_grid["pending_current_a"]
        potential_hard_safe = pending_a is None or pending_a <= cap["hard_current_cap_a"]
        potential_plan_safe = pending_a is None or pending_a <= cap["cap_a"]
        ready = (ready and observed_need > 0 and control.get("next_a", 0) <= observed_rounded_need
                 and cap["grid_within_limits"] and observed["soc_valid"]
                 and not self._memory["current_policy"].get("stopped", True)
                 and potential_hard_safe and potential_plan_safe
                 and observed["soc"] < target and observed["current_a"] is not None
                 and 0 < observed["current_a"] <= cap["hard_current_cap_a"]
                 and 0 < control.get("next_a", 0) <= cap["cap_a"])
        pending_reduction = self._pending_reduction_ok(
            observed, self._now(), control.get("next_a", 0), cap)
        # A safe current ramp must not pulse an already enabled charger OFF for
        # ten seconds every thirty seconds. Initial enabling still requires the
        # exact requested setting to settle; continuing is a separate decision.
        continuing = (active_gc is not None and active_gc.state == "on" and permitted and observed_need > 0 and
                      not self._memory["current_policy"].get("stopped", True) and
                      potential_hard_safe and
                      observed["telemetry_valid"] and observed["soc_valid"] and
                      observed["soc"] < target and
                      ((observed["current_a"] is not None and 0 < observed["current_a"] <= cap["cap_a"]
                        and 0 < control.get("next_a", 0) <= cap["cap_a"] and potential_plan_safe)
                       or pending_reduction) and cap["grid_within_limits"] and
                      soc_read is not None and abs(soc_read - target) < 2 and
                      clock_read is not None and clock_read.state == times[active_slot - 1] and
                      self._hardware_modes_ok() and self._clocks_ok(self._now()))
        for slot in range(1, 7):
            await self._gc(slot, bool((ready or continuing) and permitted and slot == active_slot and slot not in (3, 5)))
        control["setting_settled"] = bool(ready)
        control["reduction_pending"] = pending_reduction
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
                      end_time=now.astimezone(_UTC), statistic_ids={load_entity, *(c["energy_entity"] for c in self._channels()),
                          *([self._sources["ct_grid_power"], self._sources["grid_power"]]
                            if self._options["topology"] == "load_with_external_ct" else [])},
                      period="hour", units={"power": "W", "energy": "kWh"}, types={"mean", "change"})
        return await get_instance(self.hass).async_add_executor_job(job)

    def _record_slot_measurements(self, now, inputs):
        self._memory["slot_measurements"] = update_slot_measurements(
            self._memory["slot_measurements"], {"at": now,
                "battery_w": inputs["battery_power"], "grid_w": inputs["grid_power"],
                "telemetry_valid": inputs["telemetry_valid"] and inputs["battery_power"] is not None and inputs["grid_power"] is not None})

    async def _solcast_fetch_json(self, url, *, headers, params):
        """HA HTTP boundary: fixed official host, TLS, no redirects or key URL."""
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname != "api.solcast.com.au" or
                parsed.port not in (None, 443) or parsed.username or parsed.password or
                parsed.query or parsed.fragment or not parsed.path.startswith("/rooftop_sites") or
                any(str(key).lower() in ("api_key", "apikey", "token") for key in params)):
            raise ValueError("Invalid Solcast request destination")
        from homeassistant.helpers.aiohttp_client import async_get_clientsession
        session = async_get_clientsession(self.hass)
        async with session.get(url, headers=headers, params=params, ssl=True,
                               allow_redirects=False, timeout=20) as response:
            data = await response.json(content_type=None)
            return {"status": response.status, "data": data,
                    "headers": {"Retry-After": response.headers.get("Retry-After", "")}}

    async def _persist_solcast(self, state):
        if not isinstance(state, dict):
            raise ValueError("Invalid Solcast cache")
        self._memory["solcast_cache"] = self._redact(state)
        await self._save()  # Client must await this BEFORE making its request.

    def _forecast_context(self):
        config = self._options.get("solcast", {})
        return {"provider": "solcast_api" if self._solcast_configured() else "ha_entities",
                "configuration_generation": config.get("config_generation"),
                "resource_ids": sorted(config.get("resource_ids", [])),
                "dampening_factor": config.get("dampening_factor", 1),
                "hourly_factors": config.get("hourly_factors")}

    def _ensure_forecast_context(self):
        context = self._redact(self._forecast_context())
        previous = self._memory["solcast_context"]
        if previous != context and (previous or self._solcast_configured()):
            self._memory["forecast_cache"] = {}
            self._memory["target_cache"] = {}
            self._memory["safety_raise"] = {}
            self._memory["plan"] = {}
            # Ownership of a credential budget is conservative: changing site
            # config never grants a new daily request quota.
            self._memory["solcast_cache"].pop("per_site", None)
            self._memory["solcast_cache"].pop("sites", None)
            self._solcast_client = None
            generation = context.get("configuration_generation")
            if (self._solcast_configured() and generation and
                    generation != previous.get("configuration_generation") and
                    generation != self._memory["solcast_seed"].get("generation")):
                self._seed_imported_quota()
                self._memory["solcast_seed"] = {"generation": generation,
                    "utc_day": self._now().astimezone(_UTC).date().isoformat()}
        self._memory["solcast_context"] = context

    def _seed_imported_quota(self):
        """A re-import may raise today's known usage, never grant new calls."""
        initial = _number(self._options["solcast"].get("initial_requests_used"))
        quota = self._memory["solcast_cache"].get("quota")
        if initial is None or int(initial) != initial or not 0 <= initial <= 1000 or not isinstance(quota, dict):
            return
        now = self._now()
        for label, zone in (("utc", _UTC), ("warsaw", _TZ)):
            old = quota.get(label)
            if not isinstance(old, dict) or not isinstance(old.get("day"), str):
                continue
            used = _number(old.get("used"))
            day = now.astimezone(zone).date().isoformat()
            if used is None or used < 0 or int(used) != used or old["day"] > day:
                continue  # The client rejects future/corrupt records unchanged.
            quota[label] = {"day": day, "used": max(int(used), int(initial)) if old["day"] == day else int(initial)}

    async def _direct_solar_periods(self, now):
        if self._solcast_client is None:
            factory = self._solcast_factory
            if factory is None:
                from .solcast import SolcastClient
                factory = SolcastClient
            self._solcast_client = factory(self._solcast_fetcher, self._persist_solcast,
                                          state=deepcopy(self._memory["solcast_cache"]))
        try:
            result = await self._solcast_client.async_forecast(self._options["solcast"], now)
        except Exception as error:
            self._solcast_status = {"status": "unavailable", "reason": f"client_{type(error).__name__}"}
            return []
        if not isinstance(result, dict):
            self._solcast_status = {"status": "unavailable", "reason": "invalid_client_result"}
            return []
        self._solcast_status = self._redact({key: result[key] for key in
            ("status", "reason", "quota", "sites", "source") if key in result})
        return result.get("periods", [])

    async def _load_profile(self, now):
        signature = {"load": self._sources["load_power"], "channels": self._channels()}
        if self._options["topology"] == "load_with_external_ct":
            signature["ct"] = self._sources["ct_grid_power"]
            signature["grid_port"] = self._sources["grid_power"]
        try:
            stats = await asyncio.wait_for(self._statistics_provider(
                now, self._sources["load_power"], self._sources.get("pc_energy_total")), timeout=15)
            if isinstance(stats, dict) and isinstance(stats.get("statistics"), dict):
                stats = stats["statistics"]

            def hourly(items, field, scale=1, signed=False):
                output = {}
                for item in items:
                    start, end, value = _stamp(item.get("start")), _stamp(item.get("end")), _number(item.get(field))
                    if None not in (start, end, value) and 3599 <= end-start <= 3601 and (
                            now.timestamp()-8*86400 <= start < end <= now.timestamp()) and (signed or value >= 0):
                        if start in output:
                            raise ValueError("duplicate_hourly_statistics")
                        output[start] = (start, end, value*scale)
                return output

            load = hourly(stats.get(self._sources["load_power"], []), "mean")
            if self._options["topology"] == "load_with_external_ct":
                ct = hourly(stats.get(self._sources["ct_grid_power"], []), "mean", signed=True)
                port = hourly(stats.get(self._sources["grid_power"], []), "mean", signed=True)
                for at, row in list(load.items()):
                    if at not in ct or at not in port or ct[at][2]-port[at][2] < -200:
                        raise ValueError("ct_branch_history_missing_or_inconsistent")
                    load[at] = (*row[:2], row[2]+max(ct[at][2]-port[at][2], 0))
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
            included = channels
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
                    for channel in included if included_ready else []:
                        channel_rows = [channel["values"][x[0]] for x in use]
                        if len({datetime.fromtimestamp(x[0], _TZ).date() for x in channel_rows}) < 3:
                            raise ValueError("channel_load_history_insufficient")
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
            if (through is not None and 0 <= now.timestamp()-through <= 10800 and previous.get("profiles")
                    and previous.get("signature") == signature):
                return {**previous, "cached": True}
            self._last_error = f"load_profile_unavailable:{type(error).__name__}"
            return {}

    async def _solar_points(self, now):
        self._ensure_forecast_context()
        requested_context = self._forecast_context()
        live, bad = {}, False
        groups = []
        if self._solcast_configured():
            groups.append(await self._direct_solar_periods(now))
            if requested_context != self._forecast_context() or self._stopped:
                self._solcast_status = {"status": "unavailable", "reason": "configuration_changed"}
                return {}
        else:
            self._solcast_status = {"status": "ha_entities", "configured": False}
            for key in ("pv_today", "pv_tomorrow", "pv_day3"):
                state = self._state(key)
                if state is not None:
                    groups.append(state.attributes.get("detailedForecast", []))
        for periods in groups:
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
        revision = self._planning_revision
        options = deepcopy(self._options)
        sources = dict(self._sources)
        profiles = await self._load_profile(now)
        points = await self._solar_points(now)
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
        config = {key: self._options.get(key) for key in (
                    "capacity_kwh", "winter_weather_soc_percent",
                    "discharge_max_kw", "grid_max_soc_percent",
                    "pv_peak_kwp", "pv_forecast_reference_kwp", "pv_forecast_mode")}
        rated = self._options.get("inverter_max_power_kw", 12)
        if self._options["topology"] == "load_with_external_ct":
            rated = min(rated, self._options["combined_output_limit_kw"])
        # Hardware limits can change while slow history/PV reads are awaited.
        # They inform planning; the service path independently rechecks them.
        charging_inputs = self._read_inputs(self._now())
        # General Deye/BMS current limits cover PV and grid together. The
        # grid-only register and its 95% ceiling must not cap PV a second time.
        total_caps = [charging_inputs["bms_cap_a"], charging_inputs["deye_max_charge_current_a"]]
        grid_caps = [charging_inputs["bms_cap_a"], charging_inputs["deye_grid_charge_limit_a"],
                     charging_inputs["grid_charge_actuator_max_a"]]
        valid = charging_inputs["telemetry_valid"] and charging_inputs["bms_valid"]
        config["battery_charge_max_a"] = (min(total_caps) if valid
                                           and all(value is not None for value in total_caps) else None)
        config["grid_current_max_a"] = (min(grid_caps) if valid
                                        and all(value is not None for value in grid_caps) else None)
        config["battery_voltage_v"] = charging_inputs["voltage"]
        # Match the live controller's AC/DC and stored-energy assumptions.
        config["eta_ac_dc"] = .9
        config["eta_charge"] = .95
        config["discharge_max_kw"] = min(config["discharge_max_kw"], rated)
        config.update({"minimum_soc_percent": self._effective_min_soc(),
                  "minimum_soc_lower_bound": self._soc_lower_bound() if self._soc_lower_bound() is not None else 40,
                  "margin_soc_percent": self._options["reserve_margin_soc_percent"],
                  "grid_import_max_kw": self._options["grid_import_limit_kw"],
                  "inverter_max_kw": rated, "grid_export_max_kw": min(9, rated)})
        plan = self._planner({"now": now, "soc_percent": inputs["soc"], "soc_valid": inputs["soc_valid"],
                              "forecast": rows, "config": config,
                              "retained_targets": self._memory["target_cache"]})
        async with self._lock:
            if (self._stopped or revision != self._planning_revision or options != self._options or sources != self._sources):
                self._last_error = "stale_planning_snapshot"
                return plan
            old_plan = self._memory["plan"]
            old_cache = deepcopy(self._memory["target_cache"])
            old_raise = deepcopy(self._memory["safety_raise"])
            self._memory["plan"] = plan
            accepted_now = self._now()
            self._accept_targets(plan, accepted_now)
            if plan.get("quality") == "valid" and plan.get("source") == "own_deterministic_planner":
                for key, record in plan.get("targets", {}).items():
                    if not isinstance(record, dict) or key not in self._deadlines(accepted_now):
                        continue
                    if self._live_record(plan, key, accepted_now):
                        if plan.get("status") == "ok":
                            self._memory["safety_raise"].pop(key, None)
                        elif plan.get("status") == "unreachable":
                            self._memory["safety_raise"][key] = {**record,
                                "generated_at": plan["generated_at"], "deadline": record["deadline"]}
            try:
                await self._save()
            except BaseException as error:
                self._memory["plan"] = old_plan
                self._memory["target_cache"] = old_cache
                self._memory["safety_raise"] = old_raise
                if not isinstance(error, asyncio.CancelledError):
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
            if (key in deadlines and value is not None and self._effective_min_soc() <= value <= 95
                    and deadline == deadlines[key] and record.get("unreachable") is False
                    and record.get("source") == "own_deterministic_planner" and self._pv_metadata_matches(record)):
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
        floor = self._effective_min_soc()
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
                and self._pv_metadata_matches(saved)
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
                    raised.get("source") == "own_deterministic_planner" and self._pv_metadata_matches(raised)):
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
        if (value is None or not self._effective_min_soc() <= value <= 95 or
                _stamp(record.get("deadline")) != self._deadlines(now)[key] or
                record.get("source") != "own_deterministic_planner" or not self._pv_metadata_matches(record)):
            return None
        return record

    def _pv_metadata_matches(self, record):
        mode = self._options.get("pv_forecast_mode", "whole_system")
        if record.get("pv_forecast_mode") != mode:
            return False
        installed = _number(self._options.get("pv_peak_kwp"))
        if installed is None or installed != _number(record.get("pv_peak_kwp")):
            return False
        reference = self._options.get("pv_forecast_reference_kwp")
        if mode == "whole_system" and reference is None:
            return "pv_forecast_reference_kwp" in record and record["pv_forecast_reference_kwp"] is None
        return _number(reference) is not None and _number(reference) == _number(record.get("pv_forecast_reference_kwp"))

    async def _async_update_data(self):
        async with self._lock:
            if self._stopped:
                return self.data
            now = self._now()
            initial_record_changed = self._prepare_initial_window(now)
            bound = self._soc_lower_bound()
            guard = self._memory["soc_floor_guard"]
            if bound is not None and bound != guard.get("lower_bound"):
                self._memory["soc_floor_guard"] = {"lower_bound": bound}
                if guard.get("lower_bound") is not None:
                    self._memory["plan"] = {}
                    self._memory["target_cache"] = {}
                    self._memory["safety_raise"] = {}
                    self._plan_due = 0
            context = {"topology": self._options["topology"], "sources": self._sources,
                       "combined_output_limit_kw": self._options["combined_output_limit_kw"]}
            previous_context = self._memory["metering_context"]
            if context != previous_context:
                if previous_context or self._options["topology"] == "load_with_external_ct":
                    self._memory["mode"] = "shadow"
                    self._memory["plan"] = {}
                    self._memory["target_cache"] = {}
                    self._memory["safety_raise"] = {}
                    self._memory["load_profiles"] = {}
                    self._memory["current_policy"] = {}
                self._memory["metering_context"] = deepcopy(context)
            self._ensure_forecast_context()
            inputs = self._read_inputs(now)
            self._record_slot_measurements(now, inputs)
            conflicts = self._owner_conflicts()
            if self.mode == "active" and conflicts:
                self._memory["mode"] = "shadow"
                self._last_error = "ownership_conflict"
                await self._save()
            active = self.mode == "active"
            floor = self._effective_min_soc()
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
            if now.timestamp() >= self._plan_due:
                self._start_planning(now, inputs)
            # Forecast network/database IO runs in a separate task. Safety and
            # the actuator always use a new local state snapshot every tick.
            now = self._now()
            inputs = self._read_inputs(now)
            target, emergency, target_source = self._target(now)
            previous_policy = self._memory["current_policy"]
            policy = update_policy(self._grid_input(inputs, now, target, emergency), previous_policy)
            self._memory["current_policy"] = policy
            # Persist latch transitions before any hardware action. Store failure
            # blocks ordinary starts; stopping and immediate safety remain allowed.
            if initial_record_changed or any(previous_policy.get(k) != policy.get(k) for k in ("deadline", "stopped")):
                try:
                    await self._save()
                except Exception:
                    self._memory["current_policy"] = {**policy, "stopped": True, "safe_since": None}
                    self._last_error = "current_policy_store_failed"
            control = self._controller(self._grid_input(inputs, now, target, emergency))
            modes_ok = self._hardware_modes_ok()
            active = self.mode == "active"
            if active and not modes_ok:
                await self._disable_gc()
                await self._grid_attempt(0, now.timestamp(), force=True)
                control["runtime_reason"] = "hardware_mode_mismatch"
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
                    "effective_loads": self.effective_loads, "loads_revision": self.loads_revision,
                    "planning": self._plan_task is not None and not self._plan_task.done(),
                    "solcast": {**self._redact(self._solcast_status),
                        "api_configured": bool(self._options.get("solcast", {}).get("api_key")),
                        "api_enabled": self._solcast_configured()},
                    "settings": self.options, "sources": dict(self._sources),
                    "updated_at": now.isoformat(), "physical_confirmation": False}
