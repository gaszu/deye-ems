"""Fresh installs use native Deye battery data without household pump mappings.

Use the real coordinator and native flows, with HA stubbed at the boundary.
Legacy runtime fixtures explicitly carry saved BMS and PC mappings; these tests
clear that fixture mapping when exercising actual new-installation defaults.
"""
from copy import deepcopy
from types import SimpleNamespace
import unittest

import test_installable as boundary
from test_entity_prefix import source_input
from test_runtime import BMS_SOURCES, Coordinator, Harness, PC_SOURCES, runtime
from test_telemetry_loads import channel_entities


PC_KEYS = tuple(PC_SOURCES)
BMS_KEYS = tuple(BMS_SOURCES)
UNASSIGNED_KEYS = ("bms_blocking_charge", *PC_KEYS)
DEYE_BMS_SOURCES = {
    "soc": "sensor.deye_inverter_battery_bms_soc",
    "voltage": "sensor.deye_inverter_battery_voltage",
    "bms_charge_current": "sensor.deye_inverter_battery_bms_charging_current",
    "bms_blocking_charge": "",
    "battery_alarm": "binary_sensor.deye_inverter_battery_alarm",
    "battery_fault": "binary_sensor.deye_inverter_battery_fault",
}
YAM_BMS_SOURCES = {
    "soc": "sensor.yambms_1_battery_soc",
    "voltage": "sensor.yambms_1_total_voltage",
    "bms_charge_current": "sensor.yambms_1_max_charge_current",
    "bms_blocking_charge": "sensor.yambms_1_bms_blocking_charge",
    "battery_alarm": "", "battery_fault": "",
}


def fresh_harness(*, options=None, data=None):
    """Override the saved legacy mapping used by older runtime regressions."""
    return Harness(initial={"sources": {}, **(data or {})}, options=options)


def native_flow(harness=None, *, data=None, options=None):
    flow = boundary.Installation().flow()["DeyeEMSOptionsFlow"]()
    flow.config_entry = SimpleNamespace(
        data=deepcopy(data or {}), options=deepcopy(options or {}), runtime_data=None)
    flow.hass = harness.hass if harness else SimpleNamespace(
        states=SimpleNamespace(get=lambda entity: None))
    return flow


def hourly_rows(now, watts):
    end = now.replace(minute=0, second=0, microsecond=0).timestamp()
    return [{"start": end-(index+1)*3600, "end": end-index*3600,
             "mean": watts, "change": watts/1000} for index in range(168)]


class FreshInstallDefaults(unittest.IsolatedAsyncioTestCase):
    def test_default_optional_pump_sources_and_load_list_are_empty(self):
        self.assertEqual({key: runtime.DEFAULT_SOURCES[key] for key in PC_KEYS},
                         dict.fromkeys(PC_KEYS, ""))
        self.assertEqual(runtime.DEFAULT_OPTIONS["extra_loads"], [])
        self.assertFalse(set(PC_SOURCES.values()) & set(runtime.DEFAULT_SOURCES.values()))

    def test_bms_defaults_use_native_deye_can_limits_without_household_mapping(self):
        self.assertEqual({key: runtime.DEFAULT_SOURCES[key] for key in DEYE_BMS_SOURCES},
                         DEYE_BMS_SOURCES)
        self.assertFalse(any("yambms_1_" in entity for entity in runtime.DEFAULT_SOURCES.values()))

    async def test_initial_setup_with_default_or_custom_prefix_has_no_pump(self):
        flow_class = boundary.Installation().flow()["DeyeEMSConfigFlow"]
        for supplied in ({}, {"entity_prefix": "another_inverter_"}):
            with self.subTest(supplied=supplied):
                result = await flow_class().async_step_user(supplied)
                self.assertEqual(result["type"], "create_entry")
                data = result["data"]
                self.assertEqual({key: data["sources"][key] for key in UNASSIGNED_KEYS},
                                 dict.fromkeys(UNASSIGNED_KEYS, ""))
                self.assertEqual(data["extra_loads"], [])
                self.assertNotIn("active", data)
                h = fresh_harness(data=data)
                self.assertEqual(h.co.mode, "shadow")
                self.assertTrue(h.co._read_inputs(h.now)["soc_valid"])
                self.assertTrue(h.co._read_inputs(h.now)["telemetry_valid"])
                self.assertEqual(h.co.effective_loads, [])
                self.assertEqual(native_flow(data=data)._loads(), [])

    async def test_yambms_is_explicit_optional_profile_and_manual_setup_has_no_guessed_inputs(self):
        flow_class = boundary.Installation().flow()["DeyeEMSConfigFlow"]
        for profile in ("yambms", "manual"):
            with self.subTest(profile=profile):
                result = await flow_class().async_step_user({"battery_source_profile": profile})
                data = result["data"]
                self.assertEqual(data["battery_source_profile"], profile)
                expected = (YAM_BMS_SOURCES if profile == "yambms"
                            else dict.fromkeys(DEYE_BMS_SOURCES, ""))
                self.assertEqual({key: data["sources"][key] for key in expected}, expected)
                self.assertEqual({key: data["sources"][key] for key in PC_KEYS},
                                 dict.fromkeys(PC_KEYS, ""))
                h = fresh_harness(data=data)
                self.assertEqual(h.co.mode, "shadow")
                self.assertEqual(h.co._read_inputs(h.now)["bms_valid"], profile == "yambms")
                self.assertEqual(h.calls, [])

    async def test_battery_profile_change_is_preview_only_until_sources_confirmed(self):
        for profile in ("deye", "yambms"):
            with self.subTest(profile=profile):
                data = {"battery_source_profile": "manual", "sources": {**BMS_SOURCES, **PC_SOURCES}}
                flow = native_flow(data=data, options={"capacity_kwh": 80})
                before_data, before_options = deepcopy(flow.config_entry.data), deepcopy(flow.config_entry.options)
                shown = await flow.async_step_entity_prefix({
                    "entity_prefix": "second_", "battery_source_profile": profile})
                self.assertEqual(shown["step_id"], "sources")
                self.assertEqual(flow.config_entry.data, before_data)
                self.assertEqual(flow.config_entry.options, before_options)
                expected = ({key: entity.replace(".deye_inverter_", ".second_")
                             for key, entity in DEYE_BMS_SOURCES.items()}
                            if profile == "deye" else YAM_BMS_SOURCES)
                saved = (await flow.async_step_sources(source_input(shown)))["data"]
                self.assertEqual(saved["battery_source_profile"], profile)
                self.assertEqual({key: saved["sources"][key] for key in expected}, expected)
                self.assertEqual({key: saved["sources"][key] for key in PC_KEYS}, PC_SOURCES)
                self.assertEqual(saved["capacity_kwh"], 80)
                self.assertEqual(flow.config_entry.data, before_data)
                self.assertEqual(flow.config_entry.options, before_options)

    def test_coincidental_old_pump_sensors_cannot_create_a_fresh_channel(self):
        for options in ({}, {"sources": {}}, {"sources": dict.fromkeys(PC_KEYS, "")},
                        {"extra_loads": []}, {"extra_loads_managed": True}):
            with self.subTest(options=options):
                h = fresh_harness(options=options)
                for entity in PC_SOURCES.values():
                    h.set_entity(entity, 123, "kWh")
                before = deepcopy(h.entry.options)
                self.assertEqual(h.co.effective_loads, [])
                self.assertEqual(h.co._channels(), [])
                self.assertEqual(channel_entities(h), [])
                self.assertEqual(native_flow(h, options=options)._loads(), [])
                self.assertEqual(h.entry.options, before)
                self.assertEqual(h.calls, [])
                self.assertEqual(h.store.history, [])

    async def test_unconfigured_optional_fields_have_no_suggested_entity(self):
        shown = await native_flow().async_step_sources()
        fields = {marker.key: marker for marker in shown["data_schema"]}
        for key in UNASSIGNED_KEYS:
            with self.subTest(key=key):
                self.assertNotIn("default", fields[key].kw)
                self.assertNotIn("suggested_value", fields[key].kw.get("description", {}))

    async def test_prefix_preview_and_save_keep_optional_sources_empty(self):
        h = fresh_harness()
        flow = native_flow(h)
        before = deepcopy(flow.config_entry.options)
        shown = await flow.async_step_entity_prefix({"entity_prefix": "another_"})
        self.assertEqual(shown["step_id"], "sources")
        self.assertFalse(set(PC_KEYS) & set(flow._source_mapping_draft))
        self.assertEqual(flow.config_entry.options, before)
        submitted = source_input(shown)
        self.assertFalse(set(UNASSIGNED_KEYS) & set(submitted))
        self.assertTrue(all(submitted.values()))
        saved = (await flow.async_step_sources(submitted))["data"]
        self.assertEqual({key: saved["sources"][key] for key in UNASSIGNED_KEYS},
                         dict.fromkeys(UNASSIGNED_KEYS, ""))
        self.assertEqual(saved["sources"]["load_power"], "sensor.another_load_power")
        self.assertEqual(saved["sources"]["soc"], "sensor.another_battery_bms_soc")
        self.assertEqual(saved["sources"]["bms_charge_current"],
                         "sensor.another_battery_bms_charging_current")
        self.assertEqual(native_flow(options=saved)._loads(), [])

    async def test_missing_native_bms_requires_valid_profile_mapping_and_fails_without_writes(self):
        h = fresh_harness()
        for entity in DEYE_BMS_SOURCES.values():
            if entity:
                h.states.pop(entity, None)
        readings = {"soc": (50, "%"), "voltage": (54, "V"),
                    "bms_charge_current": (108, "A"), "bms_blocking_charge": (0, None)}
        legacy = {"soc": "sensor.yambms_1_battery_soc", "voltage": "sensor.yambms_1_total_voltage",
                  "bms_charge_current": "sensor.yambms_1_max_charge_current",
                  "bms_blocking_charge": "sensor.yambms_1_bms_blocking_charge"}
        for key, (value, unit) in readings.items():
            h.set_entity(legacy[key], value, unit)
            h.set_entity(BMS_SOURCES[key], value, unit)
        self.assertFalse(h.co._read_inputs(h.now)["soc_valid"])
        self.assertFalse(h.co._read_inputs(h.now)["bms_valid"])
        with self.assertRaises(ValueError) as error:
            h.co._preflight()
        self.assertIn("W Źródłach wybierz encje swojej instalacji", str(error.exception))
        for key in ("soc", "voltage", "bms_charge_current"):
            self.assertIn(f"({key})", str(error.exception))
        self.assertEqual(h.co.mode, "shadow")
        self.assertEqual(h.calls, [])
        self.assertEqual(h.store.history, [])
        flow = native_flow(h)
        shown = await flow.async_step_entity_prefix({
            "entity_prefix": "deye_inverter_", "battery_source_profile": "manual"})
        submitted = {**source_input(shown), **BMS_SOURCES}
        h.entry.options = (await flow.async_step_sources(submitted))["data"]
        self.assertEqual(h.entry.options["battery_source_profile"], "manual")
        h.co = Coordinator(h.hass, h.entry, store=h.store, clock=lambda: h.now)
        inputs = h.co._read_inputs(h.now)
        self.assertTrue(inputs["soc_valid"])
        self.assertTrue(inputs["bms_valid"])
        self.assertTrue(inputs["telemetry_valid"])
        h.co._preflight()
        self.assertEqual(h.co.mode, "shadow")
        self.assertEqual(h.calls, [])
        self.assertEqual(h.store.history, [])

    def test_deye_alarm_fault_and_zero_can_limit_block_positive_cap(self):
        for key in ("battery_alarm", "battery_fault"):
            for state, attributes in (("on", {}), ("unknown", {}), ("unavailable", {}),
                                      ("off", {"restored": True})):
                with self.subTest(key=key, state=state, attributes=attributes):
                    h = fresh_harness()
                    h.set(key, state, attributes=attributes)
                    self.assertEqual(h.co._read_inputs(h.now)["bms_cap_a"], 0)
                    self.assertEqual(h.calls, [])
        for key in ("battery_alarm", "battery_fault", "bms_charge_current"):
            with self.subTest(missing=key):
                h = fresh_harness()
                del h.states[h.co._sources[key]]
                inputs = h.co._read_inputs(h.now)
                self.assertFalse(inputs["bms_valid"])
                self.assertEqual(inputs["bms_cap_a"], 0)
                with self.assertRaises(ValueError):
                    h.co._preflight()
                self.assertEqual(h.calls, [])
        h = fresh_harness()
        h.set("bms_charge_current", 0, "A")
        self.assertEqual(h.co._read_inputs(h.now)["bms_cap_a"], 0)
        self.assertEqual(h.calls, [])

    async def test_saved_bms_mapping_survives_source_save_and_reload_from_data_or_options(self):
        for data, options in (({"sources": dict(BMS_SOURCES)}, {}),
                              ({}, {"sources": dict(BMS_SOURCES)}),
                              ({"sources": dict.fromkeys(BMS_KEYS, "sensor.previous_bms")},
                               {"sources": dict(BMS_SOURCES)})):
            with self.subTest(data=data, options=options):
                h = fresh_harness(data=data, options=deepcopy(options))
                self.assertEqual(h.co.options["battery_source_profile"], "manual")
                self.assertTrue(h.co._read_inputs(h.now)["soc_valid"])
                self.assertTrue(h.co._read_inputs(h.now)["bms_valid"])
                flow = native_flow(h, data=data, options=options)
                shown = await flow.async_step_sources()
                saved = (await flow.async_step_sources(source_input(shown)))["data"]
                self.assertEqual({key: saved["sources"][key] for key in BMS_KEYS}, BMS_SOURCES)
                h.entry.options = saved
                reloaded = Coordinator(h.hass, h.entry, store=h.store, clock=lambda: h.now)
                self.assertEqual({key: reloaded._sources[key] for key in BMS_KEYS}, BMS_SOURCES)
                self.assertTrue(reloaded._read_inputs(h.now)["telemetry_valid"])
                self.assertEqual(reloaded.options["battery_source_profile"], "manual")
                h.set("bms_blocking_charge", 1)
                self.assertEqual(reloaded._read_inputs(h.now)["bms_cap_a"], 0)
                self.assertEqual(h.calls, [])
                self.assertEqual(h.store.history, [])

    async def test_explicit_saved_legacy_mappings_survive_source_save_and_reload(self):
        for data, options in (({"sources": PC_SOURCES}, {}),
                              ({}, {"sources": PC_SOURCES}),
                              ({"sources": {"pc_energy_total": "sensor.old_saved_pump"}},
                               {"sources": PC_SOURCES})):
            with self.subTest(data=data, options=options):
                h = fresh_harness(data=data, options=options)
                before_data, before_options = deepcopy(h.entry.data), deepcopy(h.entry.options)
                expected = h.co.effective_loads
                self.assertEqual(len(expected), 1)
                self.assertEqual(expected[0]["id"], "configured_heatpump")
                self.assertEqual(expected[0]["energy_entity"], PC_SOURCES["pc_energy_total"])
                self.assertEqual(native_flow(data=data, options=options)._loads(), expected)
                flow = native_flow(data=data, options=options)
                shown = await flow.async_step_sources()
                saved = (await flow.async_step_sources(source_input(shown)))["data"]
                self.assertEqual({key: saved["sources"][key] for key in PC_KEYS}, PC_SOURCES)
                h.entry.options = saved
                reloaded = Coordinator(h.hass, h.entry, store=h.store, clock=lambda: h.now)
                self.assertEqual(reloaded.effective_loads, expected)
                self.assertEqual(h.entry.data, before_data)
                self.assertEqual(options, before_options)
                self.assertEqual(h.calls, [])

    async def test_cleared_pump_fields_are_omitted_and_stay_disabled_after_reload(self):
        for data, options in (({"sources": dict(PC_SOURCES)}, {}),
                              ({}, {"sources": dict(PC_SOURCES)})):
            with self.subTest(data=data, options=options):
                h = fresh_harness(data=data, options=deepcopy(options))
                for entity in PC_SOURCES.values():
                    h.set_entity(entity, 123, "kWh")
                self.assertEqual(len(h.co.effective_loads), 1)
                flow = native_flow(h, data=data, options=options)
                before_data, before_options = (deepcopy(flow.config_entry.data),
                                               deepcopy(flow.config_entry.options))
                shown = await flow.async_step_sources()
                submitted = source_input(shown)
                for key in PC_KEYS:
                    submitted.pop(key)
                self.assertTrue(all(submitted.values()))
                self.assertEqual(flow.config_entry.data, before_data)
                self.assertEqual(flow.config_entry.options, before_options)
                saved = (await flow.async_step_sources(submitted))["data"]
                self.assertEqual({key: saved["sources"][key] for key in PC_KEYS},
                                 dict.fromkeys(PC_KEYS, ""))
                self.assertEqual(saved["sources"]["load_power"],
                                 runtime.DEFAULT_SOURCES["load_power"])
                self.assertEqual(flow.config_entry.data, before_data)
                self.assertEqual(flow.config_entry.options, before_options)
                h.entry.options = saved
                h.co = Coordinator(h.hass, h.entry, store=h.store, clock=lambda: h.now)
                self.assertEqual(h.co.effective_loads, [])
                self.assertEqual(h.co._channels(), [])
                self.assertEqual(channel_entities(h), [])
                self.assertEqual(native_flow(data=data, options=saved)._loads(), [])
                reloaded_form = await native_flow(data=data, options=saved).async_step_sources()
                self.assertFalse(set(PC_KEYS) & set(source_input(reloaded_form)))
                self.assertEqual(h.calls, [])
                self.assertEqual(h.store.history, [])

    def test_explicit_blank_override_and_managed_empty_list_do_not_resurrect_pump(self):
        for options in ({"sources": dict.fromkeys(PC_KEYS, "")},
                        {"extra_loads_managed": True, "extra_loads": []}):
            with self.subTest(options=options):
                data = {"sources": dict(PC_SOURCES)}
                h = fresh_harness(data=data, options=options)
                self.assertEqual(h.co.effective_loads, [])
                self.assertEqual(h.co._channels(), [])
                self.assertEqual(native_flow(data=data, options=options)._loads(), [])
                reloaded = Coordinator(h.hass, h.entry, store=h.store, clock=lambda: h.now)
                self.assertEqual(reloaded.effective_loads, [])
                self.assertEqual(h.entry.options, options)

    async def test_saved_enabled_and_off_rows_keep_identity_mapping_and_state(self):
        rows = [
            {"id": "existing-pump", "name": "Pompa", "energy_entity": PC_SOURCES["pc_energy_total"],
             "power_entity": "sensor.saved_pump_power", "included_in_load": True, "enabled": False},
            {"id": "existing-cwu", "name": "CWU", "energy_entity": "sensor.saved_cwu_energy",
             "power_entity": "sensor.saved_cwu_power", "included_in_load": True, "enabled": True},
        ]
        options = {"sources": dict(PC_SOURCES), "extra_loads_managed": True, "extra_loads": rows}
        h = fresh_harness(options=deepcopy(options))
        self.assertEqual(h.co.effective_loads, rows)
        self.assertEqual(h.co._channels(), [rows[1]])
        self.assertEqual(native_flow(options=options)._loads(), rows)
        flow = native_flow(options=options)
        shown = await flow.async_step_sources()
        saved = (await flow.async_step_sources(source_input(shown)))["data"]
        self.assertEqual({key: saved["sources"][key] for key in PC_KEYS}, PC_SOURCES)
        self.assertEqual(saved["extra_loads"], rows)
        self.assertTrue(saved["extra_loads_managed"])
        h.entry.options = saved
        reloaded = Coordinator(h.hass, h.entry, store=h.store, clock=lambda: h.now)
        self.assertEqual(reloaded.effective_loads, rows)
        self.assertEqual(reloaded._channels(), [rows[1]])
        self.assertEqual(h.calls, [])
        self.assertEqual(h.store.history, [])

    async def test_fresh_history_ignores_coincidental_pump_and_retains_whole_load(self):
        h = fresh_harness()
        h.set_entity(PC_SOURCES["pc_energy_total"], 123, "kWh")
        requested = []

        async def statistics(now, load, pc):
            requested.append((load, pc))
            return {load: hourly_rows(now, 2000),
                    PC_SOURCES["pc_energy_total"]: hourly_rows(now, 1000)}

        h.co._statistics_provider = statistics
        result = await h.co._load_profile(h.now)
        self.assertEqual(requested, [(h.co._sources["load_power"], "")])
        self.assertFalse(result["pc_applied"])
        self.assertEqual(result["extra_loads"], [])
        for profile in result["profiles"].values():
            self.assertTrue(all(abs(value-2) < 1e-10 for value in profile))
        self.assertEqual(h.calls, [])

    def test_optional_saved_channels_never_add_their_power_to_total_load(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled):
                options = {"sources": dict(BMS_SOURCES), "extra_loads_managed": True, "extra_loads": [{
                    "id": "saved-pump", "name": "Pompa", "energy_entity": PC_SOURCES["pc_energy_total"],
                    "power_entity": "sensor.saved_pump_power", "included_in_load": True, "enabled": enabled}]}
                h = fresh_harness(options=options)
                h.set_entity(PC_SOURCES["pc_energy_total"], 123, "kWh")
                h.set_entity("sensor.saved_pump_power", 9000, "W")
                observed = []

                def state(entity):
                    observed.append(entity)
                    return h.states.get(entity)

                h.hass.states.get = state
                inputs = h.co._read_inputs(h.now)
                self.assertTrue(inputs["telemetry_valid"])
                self.assertEqual(inputs["load_power"], 1800)
                self.assertEqual(inputs["total_load_with_outside_w"], 1800)
                self.assertEqual(inputs["outside_load_w"], 0)
                self.assertNotIn("sensor.saved_pump_power", observed)
                self.assertEqual(h.calls, [])


if __name__ == "__main__":
    unittest.main()
