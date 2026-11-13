"""Portable Deye naming with an explicit preview/save boundary."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
import test_installable as boundary


def source_input(form):
    """Submit the full form, omitting blanks as HA EntitySelector requires."""
    return {marker.key: marker.kw["description"]["suggested_value"]
            for marker in form["data_schema"]
            if marker.kw.get("description", {}).get("suggested_value")}


class EntityPrefix(unittest.IsolatedAsyncioTestCase):
    def flow(self, active=False):
        values = boundary.Installation().flow()
        flow = values["DeyeEMSOptionsFlow"]()
        flow.config_entry = SimpleNamespace(data={}, options={
            "capacity_kwh": 80, "sources": {"soc": "sensor.custom_bms_soc",
                                          "load_power": "sensor.old_load"}},
            runtime_data=SimpleNamespace(mode="active" if active else "shadow"))
        flow.hass = SimpleNamespace(states=SimpleNamespace(get=lambda entity:
            object() if entity == "time.second_time_of_use_1_start" else None))
        return flow, values

    def test_prefix_changes_only_deye_object_names_and_preserves_domains(self):
        _, values = self.flow()
        prefix, mapping = values["_deye_prefix_sources"](" Second_ ")
        self.assertEqual(prefix, "second_")
        self.assertEqual(mapping["load_power"], "sensor.second_load_power")
        self.assertEqual(mapping["grid_current_number"], "number.second_maximum_battery_grid_charge_current")
        self.assertEqual(mapping["tou_time_1"], "time.second_time_of_use_1_start")
        self.assertEqual(mapping["tou_gc_6"], "switch.second_time_of_use_6_grid_charge")
        for key in ("bms_blocking_charge", "pv_today", "pc_energy_total"):
            self.assertNotIn(key, mapping)
        self.assertEqual(mapping["soc"], "sensor.second_battery_bms_soc")
        self.assertEqual(mapping["voltage"], "sensor.second_battery_voltage")
        self.assertEqual(mapping["bms_charge_current"], "sensor.second_battery_bms_charging_current")

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
        self.assertNotIn("load_power", flow._source_mapping_draft)
        fields = {marker.key: marker for marker in result["data_schema"]}
        self.assertEqual(fields["load_power"].kw["description"]["suggested_value"],
                         "sensor.old_load")
        self.assertEqual(flow.config_entry.options, before)

    async def test_previous_prefix_from_data_or_options_updates_its_generated_mappings(self):
        for location in ("data", "options"):
            with self.subTest(location=location):
                flow, _ = self.flow()
                stored = getattr(flow.config_entry, location)
                stored["entity_prefix"] = "first_"
                stored.setdefault("sources", {}).update(
                    grid_current_number="number.first_maximum_battery_grid_charge_current",
                    tou_time_1="time.first_time_of_use_1_start")
                before_data, before_options = (deepcopy(flow.config_entry.data),
                                               deepcopy(flow.config_entry.options))
                shown = await flow.async_step_entity_prefix()
                marker = next(marker for marker in shown["data_schema"] if marker.key == "entity_prefix")
                self.assertEqual(marker.kw["default"], "first_")
                shown = await flow.async_step_entity_prefix({"entity_prefix": "second"})
                saved = (await flow.async_step_sources(source_input(shown)))["data"]
                self.assertEqual(saved["entity_prefix"], "second_")
                self.assertEqual(saved["sources"]["grid_current_number"],
                                 "number.second_maximum_battery_grid_charge_current")
                self.assertEqual(saved["sources"]["tou_time_1"], "time.second_time_of_use_1_start")
                self.assertEqual(saved["sources"]["load_power"], "sensor.old_load")
                self.assertEqual(flow.config_entry.data, before_data)
                self.assertEqual(flow.config_entry.options, before_options)

    async def test_options_prefix_takes_precedence_over_initial_data_prefix(self):
        flow, _ = self.flow()
        flow.config_entry.data["entity_prefix"] = "initial_"
        flow.config_entry.options.update(entity_prefix="current_")
        flow.config_entry.options["sources"]["grid_current_number"] = (
            "number.current_maximum_battery_grid_charge_current")
        shown = await flow.async_step_entity_prefix()
        marker = next(marker for marker in shown["data_schema"] if marker.key == "entity_prefix")
        self.assertEqual(marker.kw["default"], "current_")
        shown = await flow.async_step_entity_prefix({"entity_prefix": "second"})
        saved = (await flow.async_step_sources(source_input(shown)))["data"]
        self.assertEqual(saved["sources"]["grid_current_number"],
                         "number.second_maximum_battery_grid_charge_current")

    async def test_prefix_preserves_explicitly_disabled_and_manual_sources(self):
        flow, _ = self.flow()
        preserved = {"ct_grid_power": "", "pc_energy_total": "", "pc_energy_today": "",
                     "pc_energy_yesterday": "", "load_power": "sensor.old_load",
                     "soc": "sensor.custom_bms_soc", "voltage": "sensor.custom_bms_voltage",
                     "bms_charge_current": "sensor.custom_bms_charge_current",
                     "bms_blocking_charge": "sensor.custom_bms_blocking_charge",
                     "pv_today": "sensor.saved_pv_forecast"}
        flow.config_entry.options["sources"].update(preserved)
        shown = await flow.async_step_entity_prefix({"entity_prefix": "second"})
        saved = (await flow.async_step_sources(source_input(shown)))["data"]
        self.assertEqual({key: saved["sources"][key] for key in preserved}, preserved)
        self.assertFalse(set(preserved) & set(flow._source_mapping_draft))

    async def test_save_allows_manual_override_and_preserves_other_sources_options(self):
        flow, _ = self.flow()
        shown = await flow.async_step_entity_prefix({"entity_prefix": "second"})
        result = await flow.async_step_sources({**source_input(shown),
                                              "load_power": "sensor.manual_load"})
        saved = result["data"]
        self.assertEqual(saved["entity_prefix"], "second_")
        self.assertEqual(saved["sources"]["load_power"], "sensor.manual_load")
        self.assertEqual(saved["sources"]["soc"], "sensor.custom_bms_soc")
        self.assertEqual(saved["sources"]["pv_today"], boundary.C["DEFAULT_SOURCES"]["pv_today"])
        self.assertEqual(saved["capacity_kwh"], 80)
        self.assertEqual(flow.config_entry.runtime_data.mode, "shadow")

    async def test_clearing_optional_fields_omits_entity_ids_and_disables_saved_sources(self):
        flow, _ = self.flow()
        flow.config_entry.options["sources"]["pc_energy_total"] = "sensor.saved_pump"
        before = deepcopy(flow.config_entry.options)
        shown = await flow.async_step_sources()
        submitted = source_input(shown)
        submitted.pop("pc_energy_total")
        submitted.pop("load_power")
        self.assertTrue(all(submitted.values()))
        self.assertEqual(flow.config_entry.options, before)
        result = await flow.async_step_sources(submitted)
        self.assertEqual(result["data"]["sources"]["pc_energy_total"], "")
        self.assertEqual(result["data"]["sources"]["load_power"], "")
        self.assertEqual(result["data"]["sources"]["soc"], "sensor.custom_bms_soc")
        self.assertEqual(flow.config_entry.options, before)

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
        result = await boundary.complete_initial_tariff(flow, result)
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
