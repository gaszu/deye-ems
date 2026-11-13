"""Offline runtime checks: ownership, durable attempts and setting readbacks.

HA is stubbed only at the framework boundary; the real planner and current
controller execute. These tests make no assertion about physical inverter ACKs.
"""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class FakeDUC:
    def __init__(self, hass, logger, **kwargs):
        self.hass = hass
        self.data = {}
        self.update_interval = kwargs.get("update_interval")

    async def async_request_refresh(self):
        self.data = await self._async_update_data()

    async def async_config_entry_first_refresh(self):
        await self.async_request_refresh()

    async def async_shutdown(self):
        pass


folder = Path(__file__).resolve().parents[1] / "custom_components/deye_ems"
try:
    TZ = ZoneInfo("Europe/Warsaw")
except ZoneInfoNotFoundError:
    # Minimal Windows Python has no IANA database. These tests exercise local
    # tariff hours and use a fixed offset only at this framework boundary.
    TZ = timezone(timedelta(hours=1))
package = ModuleType("runtime_offline")
package.__path__ = [str(folder)]
stubs = {"runtime_offline": package}
for name in ("homeassistant", "homeassistant.helpers", "homeassistant.helpers.storage",
             "homeassistant.helpers.update_coordinator"):
    stubs[name] = ModuleType(name)
stubs["homeassistant.helpers.storage"].Store = object
stubs["homeassistant.helpers.update_coordinator"].DataUpdateCoordinator = FakeDUC
with patch.dict(sys.modules, stubs), patch("zoneinfo.ZoneInfo", return_value=TZ):
    spec = importlib.util.spec_from_file_location("runtime_offline.coordinator", folder / "coordinator.py")
    runtime = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runtime
    spec.loader.exec_module(runtime)
Coordinator = runtime.DeyeEMSCoordinator
# Existing-runtime regressions explicitly represent saved BMS and pump mappings.
# Keep this fixture independent from the deliberately empty installation defaults.
BMS_SOURCES = {
    "soc": "sensor.fixture_battery_soc",
    "voltage": "sensor.fixture_battery_voltage",
    "bms_charge_current": "sensor.fixture_bms_charge_current",
    "bms_blocking_charge": "sensor.fixture_bms_blocking_charge",
}
PC_SOURCES = {
    "pc_energy_total": "sensor.pc_faza2_energy_total",
    "pc_energy_today": "sensor.pc_faza2_energy_today",
    "pc_energy_yesterday": "sensor.pc_faza2_energy_yesterday",
}
SOURCES = {**runtime.DEFAULT_SOURCES, **BMS_SOURCES, **PC_SOURCES}
OWNERS = runtime.OWNER_ENTITIES


class Store:
    def __init__(self, saved=None):
        self.saved = deepcopy(saved)
        self.history = []
        self.fail = False
        self.on_save = None

    async def async_load(self):
        return deepcopy(self.saved)

    async def async_save(self, value):
        if self.fail:
            raise OSError("synthetic storage failure")
        self.saved = deepcopy(value)
        self.history.append(deepcopy(value))
        if self.on_save:
            self.on_save()


class Harness:
    def __init__(self, *, when=None, options=None, initial=None):
        self.now = when or datetime(2026, 11, 10, 22, 0, tzinfo=TZ)
        self.states = {}
        self.calls = []
        self.fail_service = False
        self.store = Store()
        self.hass = SimpleNamespace(states=SimpleNamespace(get=self.states.get),
                                    services=SimpleNamespace(async_call=self.call),
                                    config_entries=SimpleNamespace(async_update_entry=self.update_entry))
        defaults = {"pv_peak_kwp": 20., "pv_forecast_reference_kwp": None,
                    "pv_forecast_mode": "whole_system", "sources": {**BMS_SOURCES, **PC_SOURCES}}
        self.entry = SimpleNamespace(entry_id="offline", data={**defaults, **(initial or {})}, options=options or {})
        self.co = Coordinator(self.hass, self.entry, store=self.store, clock=lambda: self.now,
                              statistics_provider=self.statistics)
        for entity in OWNERS:
            self.set_entity(entity, "off")
        for key in SOURCES:
            value, unit = 0, None
            if key.endswith("power"):
                value, unit = (1800 if key in ("grid_power", "load_power") else 600), "W"
            if key == "soc":
                value, unit = 50, "%"
            if key == "battery_low_soc":
                value, unit = 10, "%"
            if key == "voltage":
                value, unit = 54, "V"
            if key == "bms_charge_current":
                value, unit = 108, "A"
            if key == "max_charge_current_number":
                value, unit = 120, "A"  # 95%=114 A; the fixture's BMS still limits108 A.
            if key == "grid_current_number":
                value, unit = 0, "A"
            if key.startswith("tou_soc_"):
                value, unit = 40, "%"
            if key.startswith("pc_energy_"):
                value, unit = 10, "kWh"
            if key in ("battery_alarm", "battery_fault"):
                value = "off"
            if key.startswith("tou_gc_"):
                value = "off"
            if key.startswith("tou_time_"):
                value = ("00:00:00", "04:00:00", "07:00:00", "13:00:00", "16:00:00", "21:00:00")[int(key[-1])-1]
            if key in ("solar_sell", "tou_enabled"):
                value = "on"
            if key == "energy_priority":
                value = "Load First"
            if key == "work_mode":
                value = "Zero Export To Load"
            self.set(key, value, unit)
        self.co._plan_due = self.now.timestamp() + 10000
        # Most regression scenarios start with two minutes of healthy prior
        # observation. Startup/restart tests explicitly clear this state.
        self.co._memory["current_policy"] = {
            "version": 1, "deadline": self.co._window(self.now)[3].isoformat(),
            "stopped": False, "safe_since": self.now.timestamp()-120,
            "observed_at": self.now.timestamp()}

    def update_entry(self, entry, *, options):
        entry.options = options

    def set_entity(self, entity, value, unit=None, *, age=0, attributes=None):
        attrs = dict(attributes or {})
        if unit:
            attrs["unit_of_measurement"] = unit
        report = self.now - timedelta(seconds=age)
        self.states[entity] = SimpleNamespace(state=str(value), attributes=attrs,
                                              last_reported=report, last_updated=report)

    def set(self, key, value, unit=None, **kw):
        self.set_entity(self.co._sources[key], value, unit, **kw)

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)
        for state in self.states.values():
            state.last_reported = self.now

    async def call(self, domain, action, data, **kwargs):
        # Every hardware call must have its exact attempt already durable.
        entry = self.store.saved["ledger"].get(data["entity_id"])
        assert entry and entry["action"] == action
        self.calls.append((domain, action, deepcopy(data)))
        if self.fail_service:
            raise OSError("synthetic transport failure")
        old = self.states[data["entity_id"]]
        value = data.get("value", data.get("time", "on" if action == "turn_on" else "off"))
        self.set_entity(data["entity_id"], value, attributes=old.attributes)

    async def statistics(self, now, load, pc):
        return {}

    def active(self):
        self.co._preflight()
        self.co._memory["observed_owners"] = {e: True for e in OWNERS if e in self.states}
        self.co._memory["mode"] = "active"

    async def tick(self):
        self.co.data = await self.co._async_update_data()
        if self.co._plan_task is not None:
            await self.co._plan_task
            self.co.data = await self.co._async_update_data()
        return self.co.data

    def current_calls(self):
        return [data["value"] for _, action, data in self.calls
                if data["entity_id"] == SOURCES["grid_current_number"]]


class RuntimeSafety(unittest.IsolatedAsyncioTestCase):
    async def test_shadow_never_commands_even_with_stale_or_bad_inputs(self):
        h = Harness()
        h.set("load_l1_power", "unavailable", "W")
        await h.tick()
        self.assertEqual(h.calls, [])
        self.assertEqual(h.co.mode, "shadow")

    async def test_initial_config_data_and_source_mapping_are_not_ignored(self):
        h = Harness(initial={"min_soc_percent": 60, "sources": {"soc": "sensor.custom_soc"}})
        self.assertEqual(h.co.options["min_soc_percent"], 60)
        self.assertEqual(h.co._sources["soc"], "sensor.custom_soc")

    async def test_fresh_install_has_no_legacy_automation_requirement(self):
        h = Harness()
        for entity in OWNERS:
            del h.states[entity]
        await h.co.async_set_mode("active")
        self.assertEqual(h.co.mode, "active")

    async def test_existing_owner_on_or_unavailable_blocks_activation(self):
        for state in ("on", "unavailable", "unknown"):
            h = Harness()
            h.set_entity(OWNERS[0], state)
            with self.assertRaises(ValueError):
                await h.co.async_set_mode("active")
            self.assertEqual(h.calls, [])

    async def test_disappearing_observed_owner_relinquishes_without_commands(self):
        h = Harness()
        h.active()
        del h.states[OWNERS[0]]
        await h.tick()
        self.assertEqual(h.co.mode, "shadow")
        self.assertEqual(h.calls, [])

    async def test_explicit_reactivation_can_reaffirm_deliberately_removed_old_controllers(self):
        h = Harness()
        h.active()
        del h.states[OWNERS[0]]
        await h.tick()
        self.assertEqual(h.co.mode, "shadow")
        await h.co.async_set_mode("active")
        self.assertEqual(h.co.mode, "active")
        self.assertNotIn(OWNERS[0], h.co._memory["observed_owners"])

    async def test_conflict_after_durable_ledger_is_checked_before_dispatch(self):
        h = Harness()
        h.active()
        h.store.on_save = lambda: h.set_entity(OWNERS[0], "on")
        self.assertFalse(await h.co._grid_attempt(2, h.now.timestamp()))
        self.assertEqual(h.calls, [])
        self.assertEqual(h.co.mode, "shadow")

    async def test_bms_drop_during_store_blocks_positive_request(self):
        h = Harness()
        h.active()
        h.store.on_save = lambda: h.set("bms_blocking_charge", 1)
        self.assertFalse(await h.co._grid_attempt(2, h.now.timestamp()))
        self.assertEqual(h.calls, [])

    async def test_latched_bms_zero_is_valid_with_live_voltage(self):
        h = Harness()
        h.set("bms_blocking_charge", 0, age=12*3600)
        inputs = h.co._read_inputs(h.now)
        self.assertTrue(inputs["bms_valid"])
        self.assertTrue(inputs["telemetry_valid"])
        self.assertEqual(inputs["bms_cap_a"], 108)
        h.co._preflight()
        self.assertEqual(h.calls, [])

    async def test_latched_bms_nonzero_still_blocks_charging(self):
        h = Harness()
        h.set("bms_blocking_charge", 1, age=12*3600)
        inputs = h.co._read_inputs(h.now)
        self.assertTrue(inputs["bms_valid"])
        self.assertEqual(inputs["bms_cap_a"], 0)

    async def test_latched_bms_requires_live_voltage_and_nonrestored_numeric_flag(self):
        for failure in ("voltage_missing", "voltage_stale", "block_missing", "block_restored",
                        "block_unavailable", "block_nonnumeric", "block_future"):
            with self.subTest(failure=failure):
                h = Harness()
                h.set("bms_blocking_charge", 0, age=12*3600)
                if failure == "voltage_missing":
                    del h.states[SOURCES["voltage"]]
                elif failure == "voltage_stale":
                    h.set("voltage", 54, "V", age=121)
                elif failure == "block_missing":
                    del h.states[SOURCES["bms_blocking_charge"]]
                elif failure == "block_restored":
                    h.set("bms_blocking_charge", 0, attributes={"restored": True})
                elif failure == "block_unavailable":
                    h.set("bms_blocking_charge", "unavailable")
                elif failure == "block_nonnumeric":
                    h.set("bms_blocking_charge", "bad")
                else:
                    h.set("bms_blocking_charge", 0, age=-1)
                inputs = h.co._read_inputs(h.now)
                self.assertFalse(inputs["bms_valid"])
                self.assertFalse(inputs["telemetry_valid"])
                self.assertEqual(inputs["bms_cap_a"], 0)

    async def test_soc_reaching_target_during_store_blocks_positive_request(self):
        h = Harness()
        h.active()
        h.store.on_save = lambda: h.set("soc", 95, "%")
        self.assertFalse(await h.co._grid_attempt(2, h.now.timestamp()))
        self.assertEqual(h.calls, [])

    async def test_explicit_shadow_cleanup_only_while_still_owner(self):
        for conflict in (False, True):
            h = Harness()
            h.active()
            h.set("grid_current_number", 20, "A")
            h.set("tou_gc_6", "on")
            if conflict:
                h.set_entity(OWNERS[0], "on")
            await h.co.async_set_mode("shadow")
            self.assertEqual(h.co.mode, "shadow")
            if conflict:
                self.assertEqual(h.calls, [])
            else:
                self.assertEqual(h.current_calls(), [0])
                self.assertEqual(h.states[SOURCES["tou_gc_6"]].state, "off")

    async def test_tariff_boundary_during_store_blocks_positive_request(self):
        h = Harness(when=datetime(2026, 11, 10, 6, 59, 59, tzinfo=TZ))
        h.active()
        h.store.on_save = lambda: h.advance(2)
        self.assertFalse(await h.co._grid_attempt(2, h.now.timestamp()))
        self.assertEqual(h.calls, [])

    async def test_storage_failure_sends_no_command(self):
        h = Harness()
        h.active()
        h.store.fail = True
        self.assertFalse(await h.co._grid_attempt(2, h.now.timestamp()))
        self.assertEqual(h.calls, [])

    async def test_uncertain_command_keeps_journal_and_waits_next_half_hour(self):
        h = Harness()
        h.active()
        h.fail_service = True
        await h.tick()
        self.assertEqual(h.current_calls(), [40])
        self.assertEqual(h.co._memory["grid_dispatch"]["outcome"], "uncertain")
        h.advance(1799)
        await h.tick()
        self.assertEqual(h.current_calls(), [40])
        h.advance(1)
        h.co._memory["current_policy"].update(safe_since=h.now.timestamp()-120, observed_at=h.now.timestamp())
        await h.tick()
        self.assertEqual(h.current_calls(), [40, 40])

    async def test_current_is_set_directly_and_held_without_pulsing_grid_charge(self):
        h = Harness()
        h.active()
        await h.tick()
        self.assertEqual(h.current_calls(), [40])
        self.assertFalse(any(a == "turn_on" for _, a, _ in h.calls))
        h.advance(10)
        await h.tick()
        self.assertEqual(h.states[SOURCES["tou_gc_6"]].state, "on")
        h.advance(589)
        await h.tick()
        self.assertEqual(h.current_calls(), [40])
        h.advance(1)
        await h.tick()
        self.assertEqual(h.current_calls(), [40])
        self.assertEqual(h.states[SOURCES["tou_gc_6"]].state, "on")

    async def test_incoming_protected_clock_mismatch_blocks_enabling_grid_charge(self):
        h = Harness()
        h.active()
        await h.tick()
        h.advance(10)
        h.set("tou_time_3", "07:05:00")
        h.fail_service = True
        await h.tick()
        self.assertFalse(any(action == "turn_on" for _, action, _ in h.calls))

    async def test_safety_reduction_precedes_forecast_loading_and_ignores_soc(self):
        h = Harness()
        h.set("grid_current_number", 80, "A")
        h.set("bms_charge_current", 10, "A")
        h.set("soc", 35, "%")
        h.active()
        observed = []
        async def provider(*args):
            observed.extend(h.current_calls())
            return {}
        h.co._statistics_provider = provider
        h.co._plan_due = 0
        await h.tick()
        self.assertEqual(observed[0], 10)
        self.assertTrue(all(value <= 10 for value in h.current_calls()))

    async def test_minimum_is_configurable_and_protected_slots_restore_before_cache(self):
        h = Harness(options={"min_soc_percent": 50})
        h.set("tou_soc_3", 80, "%")
        h.set("tou_gc_3", "on")
        h.active()
        await h.tick()
        for slot in range(1, 7):
            self.assertGreaterEqual(float(h.states[SOURCES[f"tou_soc_{slot}"]].state), 50)
        self.assertEqual(float(h.states[SOURCES["tou_soc_3"]].state), 50)
        self.assertEqual(h.states[SOURCES["tou_gc_3"]].state, "off")

    async def test_gc_off_after_on_is_not_identical_retry(self):
        h = Harness()
        h.active()
        await h.co._attempt(SOURCES["tou_gc_6"], "turn_on", None, h.now.timestamp(), cooldown=10)
        # Even if a turn_on attempt failed its gate, OFF is a different action.
        h.set("tou_gc_6", "on")
        await h.co._gc(6, False)
        self.assertEqual(h.states[SOURCES["tou_gc_6"]].state, "off")

    async def test_stale_wrong_units_restored_and_future_power_fail_closed(self):
        for changes in ({"age": 31}, {"unit": "kW"}, {"attributes": {"restored": True}}, {"age": -1}):
            h = Harness()
            h.active()
            h.set("grid_current_number", 20, "A")
            h.set("tou_gc_6", "on")
            unit = changes.pop("unit", "W")
            h.set("load_l1_power", 600, unit, **changes)
            await h.tick()
            self.assertIn(0, h.current_calls())
            self.assertEqual(h.states[SOURCES["tou_gc_6"]].state, "off")

    async def test_hardware_mode_mismatch_only_disables_and_zeroes(self):
        h = Harness()
        h.active()
        h.set("energy_priority", "Battery First")
        h.set("grid_current_number", 20, "A")
        h.set("tou_gc_6", "on")
        result = await h.tick()
        self.assertEqual(result["status"], "hardware_mode_mismatch")
        self.assertIn(0, h.current_calls())
        self.assertFalse(any(data["entity_id"] == SOURCES["energy_priority"] for _, _, data in h.calls))

    async def test_restored_active_requires_complete_preflight(self):
        h = Harness()
        h.store.saved = {"mode": "active"}
        h.set("tou_enabled", "off")
        await h.co.async_initialize()
        self.assertEqual(h.co.mode, "shadow")
        self.assertEqual(h.calls, [])

    async def test_future_ledger_blocks_writes(self):
        h = Harness()
        h.active()
        h.co._memory["ledger"][SOURCES["grid_current_number"]] = {"at": h.now.timestamp()+1, "a": 0}
        await h.tick()
        self.assertEqual(h.current_calls(), [])

    async def test_shutdown_does_not_command(self):
        h = Harness()
        h.active()
        await h.co.async_shutdown()
        await h.tick()
        self.assertEqual(h.calls, [])

    async def test_inverter_output_ratings_do_not_replace_grid_import_limits(self):
        h = Harness(options={"inverter_max_power_kw": 4, "inverter_phase_max_power_kw": 1.5})
        inputs = h.co._read_inputs(h.now)
        g = h.co._grid_input(inputs, h.now, 75, False)
        self.assertEqual(g["total_limit_w"], 12000)
        self.assertEqual(g["phase_limit_w"], 5000)
        self.assertEqual(g["conversion_total_limit_w"], 4000)
        self.assertEqual(g["conversion_phase_limit_w"], 1500)
        self.assertEqual(g["inverter_grid_import_limit_w"], 4000)
        self.assertEqual(g["inverter_grid_phase_limit_w"], 1500)
        # The1.5kW port phase also supplies the fixture's600W native LOAD.
        # Its250W reserve leaves650W /60W-per-A =10A for charging.
        self.assertEqual(runtime.calculate_grid_charge_cap(g)["cap_a"], 10)
        captured = []
        planner = h.co._planner
        def calculate(value):
            captured.append(deepcopy(value["config"]))
            return planner(value)
        h.co._planner = calculate
        await h.co._make_plan(h.now, inputs)
        self.assertEqual(captured[0]["inverter_max_kw"], 4)
        self.assertEqual(captured[0]["grid_import_max_kw"], 12)
        self.assertNotIn("charge_max_kw", captured[0])
        self.assertEqual(captured[0]["battery_charge_max_a"], 108)
        self.assertEqual(captured[0]["grid_current_max_a"], 108)
        self.assertEqual(captured[0]["discharge_max_kw"], 4)

    async def test_connection_limit_above_twelve_reaches_load_controller_and_planner(self):
        h = Harness(options={"inverter_max_power_kw": 10})
        await h.co.async_set_option("grid_import_limit_kw", 16)
        await h.co.async_set_option("grid_phase_limit_kw", 7)
        inputs = h.co._read_inputs(h.now)
        g = h.co._grid_input(inputs, h.now, 75, False)
        self.assertEqual(g["total_limit_w"], 16000)
        self.assertEqual(g["phase_limit_w"], 7000)
        self.assertEqual(g["conversion_total_limit_w"], 10000)
        captured = []
        planner = h.co._planner
        def calculate(value):
            captured.append(deepcopy(value["config"]))
            return planner(value)
        h.co._planner = calculate
        await h.co._make_plan(h.now, inputs)
        self.assertEqual(captured[0]["grid_import_max_kw"], 16)
        self.assertEqual(captured[0]["inverter_max_kw"], 10)


class ProfilesAndCache(unittest.IsolatedAsyncioTestCase):
    def rows(self, now, value):
        end = now.replace(minute=0, second=0, microsecond=0).timestamp()
        return [{"start": end-(index+1)*3600, "end": end-index*3600,
                 "mean": value, "change": value/1000} for index in range(168)]

    async def test_optional_missing_pc_keeps_whole_load(self):
        h = Harness()
        async def provider(*args):
            return {SOURCES["load_power"]: self.rows(h.now, 2000)}
        h.co._statistics_provider = provider
        result = await h.co._load_profile(h.now)
        self.assertFalse(result["pc_applied"])
        for values in result["profiles"].values():
            self.assertTrue(all(abs(value-2) < 1e-10 for value in values))

    async def test_pump_is_replaced_once_not_added_to_whole_load(self):
        h = Harness()
        async def provider(*args):
            return {SOURCES["load_power"]: self.rows(h.now, 3000),
                    SOURCES["pc_energy_total"]: self.rows(h.now, 1000)}
        h.co._statistics_provider = provider
        result = await h.co._load_profile(h.now)
        self.assertTrue(result["pc_applied"])
        for values in result["profiles"].values():
            self.assertTrue(all(abs(value-3) < 1e-10 for value in values))

    async def test_multiple_included_channels_and_duplicate_default_pump_are_counted_once(self):
        extras = [{"name": "PC", "energy_entity": SOURCES["pc_energy_total"], "included_in_load": True},
                  {"name": "CWU", "energy_entity": "sensor.cwu_energy", "included_in_load": True}]
        h = Harness(options={"extra_loads": extras})
        h.set_entity("sensor.cwu_energy", 10, "Wh")
        async def provider(*args):
            return {SOURCES["load_power"]: self.rows(h.now, 4000),
                    SOURCES["pc_energy_total"]: self.rows(h.now, 1000),
                    "sensor.cwu_energy": self.rows(h.now, 500)}
        h.co._statistics_provider = provider
        result = await h.co._load_profile(h.now)
        self.assertEqual(len(result["extra_loads"]), 2)
        for values in result["profiles"].values():
            self.assertTrue(all(abs(value-4) < 1e-10 for value in values))

    async def test_missing_included_channel_retains_whole_load_without_adding_pump(self):
        h = Harness(options={"extra_loads": [{"name": "CWU", "energy_entity": "sensor.cwu_energy", "included_in_load": True}]})
        async def provider(*args):
            return {SOURCES["load_power"]: self.rows(h.now, 3000),
                    SOURCES["pc_energy_total"]: self.rows(h.now, 1000)}
        h.co._statistics_provider = provider
        result = await h.co._load_profile(h.now)
        self.assertFalse(result["pc_applied"])
        self.assertTrue(all(abs(v-3) < 1e-10 for v in result["profiles"]["False"]))

    async def test_legacy_outside_flag_never_adds_to_whole_load_forecast_or_budget(self):
        h = Harness(options={"extra_loads": [{"name": "Klima", "energy_entity": "sensor.klima_energy",
                       "power_entity": "sensor.klima_power", "included_in_load": False}]})
        h.set_entity("sensor.klima_energy", 100, "kWh")
        h.set_entity("sensor.klima_power", .5, "kW")
        async def provider(*args):
            return {SOURCES["load_power"]: self.rows(h.now, 2000),
                    "sensor.klima_energy": self.rows(h.now, 500),
                    SOURCES["pc_energy_total"]: self.rows(h.now, 500)}
        h.co._statistics_provider = provider
        result = await h.co._load_profile(h.now)
        self.assertTrue(all(abs(v-2) < 1e-10 for v in result["profiles"]["False"]))
        self.assertTrue(all(channel["included_in_load"] for channel in h.co.effective_loads))
        inputs = h.co._read_inputs(h.now)
        self.assertEqual(inputs["grid_power"], 1800)
        self.assertEqual(inputs["load_power"], 1800)
        self.assertEqual(inputs["outside_load_w"], 0)
        self.assertEqual(inputs["total_load_with_outside_w"], 1800)

    async def test_optional_missing_channel_power_and_energy_keep_whole_load_and_allow_activation(self):
        h = Harness(options={"extra_loads": [{"name": "Klima", "energy_entity": "sensor.klima_energy", "included_in_load": False}]})
        async def provider(*args):
            return {SOURCES["load_power"]: self.rows(h.now, 2000)}
        h.co._statistics_provider = provider
        result = await h.co._load_profile(h.now)
        self.assertTrue(all(abs(v-2) < 1e-10 for v in result["profiles"]["False"]))
        self.assertFalse(result["pc_applied"])
        self.assertTrue(h.co._read_inputs(h.now)["telemetry_valid"])
        await h.co.async_set_mode("active")
        self.assertEqual(h.co.mode, "active")

    async def test_invalid_solar_rows_do_not_poison_dated_cache(self):
        h = Harness()
        at = int(h.now.timestamp()//1800)*1800
        h.co._memory["forecast_cache"] = {str(at): {"p10": 1, "p50": 2}}
        h.set("pv_today", 0, attributes={"detailedForecast": [{"period_start": h.now.isoformat(), "pv_estimate10": 3, "pv_estimate": 1}]})
        self.assertEqual((await h.co._solar_points(h.now))[str(at)], {"p10": 1, "p50": 2})

    async def test_unreachable_and_foreign_plans_are_not_cached(self):
        h = Harness()
        for status, source in (("unreachable", "own_deterministic_planner"), ("ok", "foreign")):
            h.co._accept_targets({"status": status, "quality": "valid", "source": source,
                                  "generated_at": h.now.isoformat(), "targets": {"night": {"soc_percent": 50}}}, h.now)
            self.assertEqual(h.co._memory["target_cache"], {})

    async def test_failed_plan_save_rolls_back_targets(self):
        h = Harness()
        h.store.fail = True
        before = deepcopy(h.co._memory["target_cache"])
        with self.assertRaises(OSError):
            await h.co._make_plan(h.now, h.co._read_inputs(h.now))
        self.assertEqual(h.co._memory["target_cache"], before)

    def plan(self, h, target, *, status="ok", age=0):
        generated = h.now-timedelta(seconds=age)
        winter = h.now.month in (10, 11, 12, 1, 2, 3)
        records = {key: {"soc_percent": target,
                        "deadline": datetime.fromtimestamp(deadline, TZ).isoformat(),
                        "generated_at": generated.isoformat(),
                        "source": "own_deterministic_planner", "season": "winter" if winter else "summer",
                        "emergency": not winter and target > h.co.options["min_soc_percent"],
                        "grid_charge_allowed": winter or target > h.co.options["min_soc_percent"],
                        "pv_peak_kwp": h.co.options["pv_peak_kwp"],
                        "pv_forecast_reference_kwp": h.co.options["pv_forecast_reference_kwp"],
                        "pv_forecast_mode": h.co.options["pv_forecast_mode"],
                        "unreachable": status == "unreachable"}
                   for key, deadline in h.co._deadlines(h.now).items()}
        return {"status": status, "quality": "valid", "source": "own_deterministic_planner",
                "season": "winter" if winter else "summer", "generated_at": generated.isoformat(),
                "targets": records, "rows": []}

    async def test_exact_valid_summer_normal_cache_is_used_then_foreign_cache_rejected(self):
        h = Harness(when=datetime(2026, 7, 10, 23, 0, tzinfo=TZ))
        plan = self.plan(h, 40)
        h.co._accept_targets(plan, h.now)
        h.co._memory["plan"] = plan
        self.assertEqual(h.co._target(h.now), (40, False, "own_plan"))
        h.co._memory["target_cache"]["night"]["source"] = "foreign"
        self.assertEqual(h.co._target(h.now), (95, True, "summer_emergency_fallback"))

    async def test_fresh_unreachable_raises_older_cache_without_overriding_cap(self):
        h = Harness()
        for slot in (1, 2, 6):
            h.set(f"tou_soc_{slot}", 45, "%")
        h.co._accept_targets(self.plan(h, 45, age=600), h.now)
        h.co._planner = lambda inputs: self.plan(h, 95, status="unreachable")
        h.co._plan_due = 0
        h.active()
        result = await h.tick()
        self.assertEqual(result["control"]["target_soc"], 95)
        self.assertEqual(result["control"]["target_source"], "unreachable_plan_raise")
        self.assertEqual(h.co._memory["target_cache"]["night"]["soc_percent"], 45)
        self.assertEqual(h.current_calls(), [65])
        self.assertLessEqual(result["control"]["next_a"], result["control"]["cap_a"])

    async def test_invalid_plan_keeps_winter_higher_setting_until_fresh_valid_counterplan(self):
        h = Harness()
        h.co._accept_targets(self.plan(h, 45, age=600), h.now)
        h.set("tou_soc_6", 95, "%")
        self.assertEqual(h.co._target(h.now)[0], 95)
        fresh = self.plan(h, 45)
        h.co._accept_targets(fresh, h.now)
        h.co._memory["plan"] = fresh
        self.assertEqual(h.co._target(h.now)[0], 45)

    async def test_minimum_and_reserve_combination_rejected_without_mutation(self):
        h = Harness(options={"reserve_margin_soc_percent": 10})
        with self.assertRaises(ValueError):
            await h.co.async_set_option("min_soc_percent", 90)
        self.assertEqual(h.co.options["min_soc_percent"], 40)

    async def test_slot_meter_uses_actual_power_and_persists_without_services(self):
        h = Harness()
        h.set("battery_power", -600, "W")
        await h.tick()
        h.advance(10)
        result = await h.tick()
        records = result["slot_measurements"]["slots"]
        current = records[result["slot_measurements"]["current_slot"]]
        self.assertAlmostEqual(current["battery_charge_kwh"], 600*10/3600000)
        self.assertEqual(h.calls, [])
        h.advance(60)
        await h.tick()
        self.assertEqual(h.store.saved["slot_measurements"], h.co._memory["slot_measurements"])

    async def test_summer_fallback_cannot_enable_grid_in_protected_hours(self):
        h = Harness(when=datetime(2026, 7, 10, 10, 0, tzinfo=TZ))
        h.active()
        h.set("grid_current_number", 20, "A")
        h.set("tou_gc_3", "on")
        result = await h.tick()
        self.assertEqual(result["control"]["target_soc"], 95)
        self.assertEqual(result["control"]["next_a"], 0)
        self.assertEqual(h.states[SOURCES["tou_gc_3"]].state, "off")


class DirectSolcastBridge(unittest.IsolatedAsyncioTestCase):
    secret = "synthetic-solcast-private-api-key"

    def harness(self, **changes):
        config = {"api_key": self.secret, "resource_ids": ["site-1"], "enabled": True,
                  "poll_interval_minutes": 360, "max_requests_per_day": 10,
                  "dampening_factor": 1, "initial_requests_used": 0, "config_generation": "one"}
        config.update(changes)
        h = Harness(options={"solcast": config})
        self.requests = []
        self.configs = []
        outer = self

        async def fetch(url, *, headers, params):
            outer.requests.append((url, headers, params))
            # A durable quota reservation already exists when HTTP begins.
            assert h.store.saved["solcast_cache"]["quota"]["used"] >= 1
            return {"status": 200, "data": {"periods": [
                {"period_start": h.now.isoformat(), "pv_estimate": 1., "pv_estimate10": .5}]}, "headers": {}}

        class Client:
            def __init__(self, fetch_json, persist, state=None):
                self.fetch = fetch_json
                self.persist = persist
                self.state = deepcopy(state or {})

            async def async_forecast(self, cfg, now):
                outer.configs.append(deepcopy(cfg))
                if self.state.get("periods") and now.timestamp()-self.state["at"] < 360*60:
                    return {"status": "cached", "periods": self.state["periods"], "source": "solcast_cache"}
                self.state["quota"] = {"used": self.state.get("quota", {}).get("used", 0)+1}
                await self.persist(self.state)
                result = await self.fetch("https://api.solcast.com.au/rooftop_sites/site-1/forecasts",
                                          headers={"Authorization": f"Bearer {cfg['api_key']}"}, params={"format": "json"})
                self.state.update(periods=result["data"]["periods"], at=now.timestamp())
                await self.persist(self.state)
                return {"status": "ok", "periods": self.state["periods"], "source": "solcast_api",
                        "sites": [{"resource_id": "site-1", "api_key": cfg["api_key"]}],
                        "reason": f"synthetic response {cfg['api_key']}"}

        h.co._solcast_factory = Client
        h.co._solcast_fetcher = fetch
        return h

    async def test_direct_provider_reserves_quota_and_never_reads_legacy_solcast_entities(self):
        h = self.harness()
        legacy = {SOURCES[key] for key in ("pv_today", "pv_tomorrow", "pv_day3")}
        def get_state(entity):
            if entity in legacy:
                raise AssertionError("Configured direct provider read a legacy Solcast entity")
            return h.states.get(entity)
        h.hass.states.get = get_state
        points = await h.co._solar_points(h.now)
        self.assertEqual(points[str(int(h.now.timestamp()))], {"p10": .5, "p50": 1.})
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0][1]["Authorization"], f"Bearer {self.secret}")
        self.assertNotIn("api_key", self.requests[0][2])
        self.assertEqual(h.calls, [])

    async def test_api_key_absent_from_public_options_data_cache_and_planner_inputs(self):
        h = self.harness()
        captured = []
        planner = h.co._planner
        def calculate(inputs):
            captured.append(deepcopy(inputs))
            return planner(inputs)
        h.co._planner = calculate
        h.co._plan_due = 0
        await h.tick()
        for value in (h.co.options, h.co.data, h.co._memory, h.store.saved):
            self.assertNotIn(self.secret, json.dumps(value))
        self.assertNotIn(self.secret, json.dumps(captured, default=str))
        self.assertNotIn("solcast", h.co.options)
        self.assertTrue(h.co.options["solcast_configured"])
        self.assertEqual(h.co.options["solcast_site_count"], 1)
        self.assertNotIn("solcast", captured[0]["config"])

    async def test_failed_durable_quota_reservation_prevents_http(self):
        h = self.harness()
        h.store.fail = True
        self.assertEqual(await h.co._solar_points(h.now), {})
        self.assertEqual(self.requests, [])
        self.assertEqual(h.co._solcast_status["status"], "unavailable")

    async def test_five_minute_planning_does_not_force_provider_polling(self):
        h = self.harness()
        await h.co._solar_points(h.now)
        h.advance(300)
        await h.co._solar_points(h.now)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(h.co._solcast_status["status"], "cached")

    async def test_new_configuration_clears_site_forecasts_but_preserves_consumed_quota(self):
        h = self.harness()
        h.co._ensure_forecast_context()
        h.co._memory["solcast_cache"] = {"quota": {"used": 8}, "per_site": {"old": {}}, "sites": {"old": {}}}
        h.co._memory["forecast_cache"] = {"old": {"p10": 1, "p50": 2}}
        h.co._memory["target_cache"] = {"night": {"soc_percent": 45}}
        h.co._options["solcast"]["config_generation"] = "two"
        h.co._ensure_forecast_context()
        self.assertEqual(h.co._memory["solcast_cache"], {"quota": {"used": 8}})
        self.assertEqual(h.co._memory["forecast_cache"], {})
        self.assertEqual(h.co._memory["target_cache"], {})

    async def test_capacity_change_does_not_rescale_raw_provider_points(self):
        h = self.harness()
        h.co._options.update(pv_peak_kwp=40, pv_forecast_reference_kwp=20, pv_forecast_mode="whole_system")
        points = await h.co._solar_points(h.now)
        self.assertEqual(points[str(int(h.now.timestamp()))]["p50"], 1.)

    async def test_reimport_quota_seed_raises_existing_usage_without_resetting_cooldown(self):
        h = self.harness(initial_requests_used=10)
        h.co._ensure_forecast_context()
        day = h.now.date().isoformat()
        utc_day = h.now.astimezone(timezone.utc).date().isoformat()
        previous_request = h.now.timestamp()-60
        retry = h.now.timestamp()+600
        h.co._memory["solcast_cache"] = {"quota": {
            "utc": {"day": utc_day, "used": 2}, "warsaw": {"day": day, "used": 4}},
            "last_request_ts": previous_request, "retry_after": retry}
        h.co._options["solcast"]["config_generation"] = "new-import"
        h.co._ensure_forecast_context()
        saved = h.co._memory["solcast_cache"]
        self.assertEqual(saved["quota"]["utc"]["used"], 10)
        self.assertEqual(saved["quota"]["warsaw"]["used"], 10)
        self.assertEqual(saved["last_request_ts"], previous_request)
        self.assertEqual(saved["retry_after"], retry)
        h.co._options["solcast"].update(initial_requests_used=1, config_generation="third-import")
        h.co._ensure_forecast_context()
        self.assertEqual(saved["quota"]["utc"]["used"], 10)

    async def test_reimport_does_not_reapply_seed_each_new_calendar_day_or_repair_future_ledger(self):
        h = self.harness(initial_requests_used=10)
        h.co._ensure_forecast_context()
        h.co._memory["solcast_cache"] = {"quota": {"utc": {"day": "2026-11-11", "used": 12},
                                                                  "warsaw": {"day": "2026-11-10", "used": 10}}}
        h.co._options["solcast"]["config_generation"] = "new-import"
        h.co._ensure_forecast_context()
        self.assertEqual(h.co._memory["solcast_cache"]["quota"]["utc"], {"day": "2026-11-11", "used": 12})
        h.advance(86400)
        h.co._memory["solcast_cache"]["quota"]["utc"]["used"] = 1
        h.co._ensure_forecast_context()
        self.assertEqual(h.co._memory["solcast_cache"]["quota"]["utc"]["used"], 1)

    async def test_enabled_false_uses_selected_ha_forecast_without_direct_http(self):
        h = self.harness(enabled=False)
        h.set("pv_today", 0, attributes={"detailedForecast": [
            {"period_start": h.now.isoformat(), "pv_estimate": 2., "pv_estimate10": 1.}]})
        points = await h.co._solar_points(h.now)
        self.assertEqual(points[str(int(h.now.timestamp()))]["p50"], 2.)
        self.assertEqual(self.requests, [])
        self.assertFalse(h.co.options["solcast_configured"])
        self.assertEqual(h.co._solcast_status["status"], "ha_entities")

    async def test_quota_seed_is_once_per_explicit_generation_not_context_or_restart(self):
        h = self.harness(initial_requests_used=10)
        h.co._ensure_forecast_context()
        day = h.now.astimezone(timezone.utc).date().isoformat()
        h.co._memory["solcast_cache"] = {"quota": {
            "utc": {"day": day, "used": 2}, "warsaw": {"day": h.now.date().isoformat(), "used": 2}}}
        h.co._options["solcast"]["dampening_factor"] = .9
        h.co._ensure_forecast_context()  # Context changed; generation did not.
        self.assertEqual(h.co._memory["solcast_cache"]["quota"]["utc"]["used"], 2)
        await h.co._save()
        h.advance(86400)
        await h.co.async_initialize()  # Same generation on the next day.
        h.co._options["solcast"]["dampening_factor"] = .8
        h.co._ensure_forecast_context()
        self.assertEqual(h.co._memory["solcast_cache"]["quota"]["utc"], {"day": day, "used": 2})
        self.assertEqual(h.co._memory["solcast_seed"]["generation"], "one")

    async def test_activation_requires_explicit_installed_capacity(self):
        h = Harness(initial={"pv_peak_kwp": None})
        with self.assertRaises(ValueError):
            await h.co.async_set_mode("active")
        self.assertEqual(h.calls, [])

    async def test_http_adapter_rejects_nonofficial_hosts_redirect_targets_and_query_keys(self):
        h = self.harness()
        for url in ("http://api.solcast.com.au/rooftop_sites", "https://evil.example/rooftop_sites",
                    "https://api.solcast.com.au/rooftop_sites?api_key=forbidden",
                    "https://api.solcast.com.au:8443/rooftop_sites"):
            with self.assertRaises(ValueError):
                await h.co._solcast_fetch_json(url, headers={}, params={})
        with self.assertRaises(ValueError):
            await h.co._solcast_fetch_json("https://api.solcast.com.au/rooftop_sites", headers={}, params={"api_key": "forbidden"})

    async def test_cache_generated_for_other_pv_capacity_is_rejected(self):
        h = Harness()
        plan = ProfilesAndCache().plan(h, 45)
        h.co._accept_targets(plan, h.now)
        self.assertEqual(h.co._target(h.now)[0], 45)
        h.co._options["pv_peak_kwp"] = 30
        self.assertEqual(h.co._target(h.now)[2], "winter_fallback")

    async def test_real_solcast_client_bridge_with_http_stub_and_durable_actual_quota_schema(self):
        path = folder/"solcast.py"
        spec = importlib.util.spec_from_file_location("runtime_real_solcast", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        h = self.harness()
        calls = []
        async def http(url, *, headers, params):
            quota = h.store.saved["solcast_cache"]["quota"]
            self.assertEqual(quota["utc"]["used"], 1)
            self.assertEqual(quota["warsaw"]["used"], 1)
            calls.append(url)
            rows = [{"period_end": (h.now+timedelta(minutes=30*(i+1))).isoformat(),
                     "period": "PT30M", "pv_estimate": 1., "pv_estimate10": .5}
                    for i in range(144)]
            return {"status": 200, "data": {"forecasts": rows}, "headers": {}}
        h.co._solcast_factory = module.SolcastClient
        h.co._solcast_fetcher = http
        points = await h.co._solar_points(h.now)
        self.assertGreaterEqual(len(points), 96)
        self.assertEqual(h.co._solcast_status["status"], "ok")
        h.advance(300)
        await h.co._solar_points(h.now)
        self.assertEqual(len(calls), 1)
        self.assertEqual(h.co._solcast_status["status"], "cached")
        self.assertNotIn(self.secret, json.dumps(h.co._memory))
        self.assertNotIn(self.secret, json.dumps(h.store.saved))

    async def test_blocked_forecast_http_does_not_block_overload_safety_and_shutdown_cancels_it(self):
        h = self.harness()
        entered, released, cancelled = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def blocked(url, *, headers, params):
            entered.set()
            try:
                await released.wait()
            finally:
                cancelled.set()
            return {"status": 200, "data": {"periods": []}, "headers": {}}
        h.co._solcast_fetcher = blocked
        h.co._plan_due = 0
        h.active()
        await asyncio.wait_for(h.co._async_update_data(), .5)
        await asyncio.wait_for(entered.wait(), .5)
        task = h.co._plan_task
        self.assertFalse(task.done())
        h.advance(10)
        h.set("grid_power", 13000, "W")
        h.set("grid_l1_power", 5500, "W")
        h.set("grid_l2_power", 4000, "W")
        h.set("grid_l3_power", 3500, "W")
        await asyncio.wait_for(h.co._async_update_data(), .5)
        self.assertEqual(h.current_calls()[-1], 0)
        self.assertFalse(task.done())
        await asyncio.wait_for(h.co.async_shutdown(), .5)
        self.assertTrue(task.cancelled())
        self.assertTrue(cancelled.is_set())
        self.assertIsNone(h.co._plan_task)

    async def test_old_inflight_configuration_cannot_publish_new_plan_or_forecast(self):
        h = self.harness()
        entered, released = asyncio.Event(), asyncio.Event()
        async def blocked(url, *, headers, params):
            entered.set()
            await released.wait()
            return {"status": 200, "data": {"periods": [
                {"period_start": h.now.isoformat(), "pv_estimate": 1., "pv_estimate10": .5}]}, "headers": {}}
        h.co._solcast_fetcher = blocked
        h.co._planner = lambda inputs: ProfilesAndCache().plan(h, 95)
        h.co._plan_due = 0
        await asyncio.wait_for(h.co._async_update_data(), .5)
        await asyncio.wait_for(entered.wait(), .5)
        task = h.co._plan_task
        h.co._options["solcast"]["config_generation"] = "changed-inflight"
        released.set()
        await asyncio.wait_for(task, .5)
        self.assertEqual(h.co._memory["target_cache"], {})
        self.assertEqual(h.co._memory["forecast_cache"], {})
        self.assertEqual(h.co._memory["plan"], {})
        self.assertEqual(h.co._last_error, "stale_planning_snapshot")
        await h.co.async_shutdown()

    async def test_serial_store_snapshot_keeps_newer_attempt_ledger_and_quota(self):
        h = Harness()
        entered, released = asyncio.Event(), asyncio.Event()
        calls = []
        async def save(value):
            calls.append(deepcopy(value))
            if len(calls) == 1:
                entered.set()
                await released.wait()
            h.store.saved = deepcopy(value)
        h.store.async_save = save
        entity = SOURCES["grid_current_number"]
        h.co._memory["ledger"][entity] = {"at": h.now.timestamp(), "a": 2}
        first = asyncio.create_task(h.co._save())
        await asyncio.wait_for(entered.wait(), .5)
        h.co._memory["ledger"][entity]["a"] = 4
        h.co._memory["solcast_cache"] = {"quota": {"utc": {"used": 8}}}
        second = asyncio.create_task(h.co._save())
        await asyncio.sleep(0)
        released.set()
        await asyncio.wait_for(asyncio.gather(first, second), .5)
        self.assertEqual(h.store.saved["ledger"][entity]["a"], 4)
        self.assertEqual(h.store.saved["solcast_cache"]["quota"]["utc"]["used"], 8)
        self.assertEqual(calls[0]["ledger"][entity]["a"], 2)
        self.assertEqual(calls[1]["ledger"][entity]["a"], 4)


if __name__ == "__main__":
    unittest.main()
