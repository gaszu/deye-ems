"""Portable Deye naming with an explicit preview/save boundary."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
import test_installable as boundary


class EntityPrefix(unittest.IsolatedAsyncioTestCase):
    def flow(self, active=False):
        values = boundary.Installation().flow()
        flow = values["DeyeEMSOptionsFlow"]()
        flow.config_entry = SimpleNamespace(data={}, options={
            "capacity_kwh": 80, "sources": {"soc": "sensor.custom_bms_soc",
                                          "load_power": "sensor.old_load"}},
            runtime_data=SimpleNamespace(mode="active" if active else "shadow"))
        flow.hass = SimpleNamespace(states=SimpleNamespace(get=lambda entity:
            object() if entity == "sensor.second_load_power" else None))
        return flow, values

    def test_prefix_changes_only_deye_object_names_and_preserves_domains(self):
        _, values = self.flow()
        prefix, mapping = values["_deye_prefix_sources"](" Second_ ")
        self.assertEqual(prefix, "second_")
        self.assertEqual(mapping["load_power"], "sensor.second_load_power")
        self.assertEqual(mapping["grid_current_number"], "number.second_maximum_battery_grid_charge_current")
        self.assertEqual(mapping["tou_time_1"], "time.second_time_of_use_1_start")
        self.assertEqual(mapping["tou_gc_6"], "switch.second_time_of_use_6_grid_charge")
        for key in ("soc", "voltage", "bms_charge_current", "pv_today", "pc_energy_total"):
            self.assertNotIn(key, mapping)

    def test_invalid_prefixes_are_rejected(self):
        _, values = self.flow()
        for prefix in (None, True, "", "___", "sensor.second_", "second inverter", "zażółć", "a"*101):
            with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                values["_deye_prefix_sources"](prefix)

    async def test_preview_counts_missing_and_does_not_save_or_mutate_entry(self):
        flow, _ = self.flow()
        before = deepcopy(flow.config_entry.options)
        result = await flow.async_step_entity_prefix({"entity_prefix": "second_"})
        self.assertEqual(result["type"], "form")
        self.assertEqual(result["step_id"], "sources")
        preview = result["description_placeholders"]["prefix_preview"]
        self.assertIn("Znaleziono 1/", preview)
        self.assertIn("number.second_maximum_battery_grid_charge_current", preview)
        self.assertEqual(flow.config_entry.options, before)

    async def test_save_allows_manual_override_and_preserves_other_sources_options(self):
        flow, _ = self.flow()
        await flow.async_step_entity_prefix({"entity_prefix": "second"})
        result = await flow.async_step_sources({"load_power": "sensor.manual_load"})
        saved = result["data"]
        self.assertEqual(saved["entity_prefix"], "second_")
        self.assertEqual(saved["sources"]["load_power"], "sensor.manual_load")
        self.assertEqual(saved["sources"]["soc"], "sensor.custom_bms_soc")
        self.assertEqual(saved["sources"]["pv_today"], boundary.C["DEFAULT_SOURCES"]["pv_today"])
        self.assertEqual(saved["capacity_kwh"], 80)
        self.assertEqual(flow.config_entry.runtime_data.mode, "shadow")

    async def test_active_mode_blocks_preview_and_later_confirmation(self):
        flow, _ = self.flow(True)
        result = await flow.async_step_entity_prefix({"entity_prefix": "second"})
        self.assertEqual(result["reason"], "stop_before_mapping")
        flow.config_entry.runtime_data.mode = "shadow"
        await flow.async_step_entity_prefix({"entity_prefix": "second"})
        flow.config_entry.runtime_data.mode = "active"
        result = await flow.async_step_sources({})
        self.assertEqual(result["reason"], "stop_before_mapping")

    async def test_initial_setup_supports_prefix_and_starts_with_default_observation(self):
        _, values = self.flow()
        flow = values["DeyeEMSConfigFlow"]()
        result = await flow.async_step_user({"entity_prefix": "second", "min_soc_percent": 40})
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["sources"]["work_mode"], "select.second_system_work_mode")
        self.assertEqual(result["data"]["entity_prefix"], "second_")
        self.assertNotIn("active", result["data"])

    async def test_invalid_input_keeps_form_open(self):
        flow, values = self.flow()
        result = await flow.async_step_entity_prefix({"entity_prefix": "sensor.bad"})
        self.assertEqual(result["errors"], {"base": "invalid_entity_prefix"})
        result = await values["DeyeEMSConfigFlow"]().async_step_user({"entity_prefix": "sensor.bad"})
        self.assertEqual(result["errors"]["entity_prefix"], "invalid_entity_prefix")
