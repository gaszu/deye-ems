"""Existing 1P aliases are editable proposals, never migrations or BMS bypasses."""

from copy import deepcopy
from types import SimpleNamespace
import unittest

import test_installable as boundary
from test_entity_prefix import source_input


class SinglePhaseSuggestions(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.module = boundary.Installation().flow()
        self.prefix, self.generated = self.module["_deye_prefix_sources"]("sample_")
        self.existing = {"sensor.sample_battery", *(
            f"switch.sample_time_of_use_{slot}_charge_enable" for slot in range(1, 7))}
        self.get_state = lambda entity: object() if entity in self.existing else None

    def suggest(self, values=None, phases=1, profile="deye"):
        return self.module["_single_phase_source_suggestions"](
            self.generated if values is None else values, self.prefix, phases, profile, self.get_state)

    def flow(self, *, profile="deye", saved=None):
        flow = self.module["DeyeEMSOptionsFlow"]()
        flow.config_entry = SimpleNamespace(data={}, options={
            "inverter_phases": 1, "entity_prefix": self.prefix, "battery_source_profile": profile,
            "sources": deepcopy(self.generated if saved is None else saved)},
            runtime_data=SimpleNamespace(mode="shadow"))
        flow.hass = SimpleNamespace(states=SimpleNamespace(get=self.get_state))
        return flow

    def test_known_aliases_exist_and_never_invent_bms_cap_or_faults(self):
        suggestions = self.suggest()
        self.assertEqual(suggestions["soc"], "sensor.sample_battery")
        for slot in range(1, 7):
            self.assertEqual(suggestions[f"tou_gc_{slot}"], f"switch.sample_time_of_use_{slot}_charge_enable")
        self.assertEqual(len(suggestions), 7)
        self.assertTrue(all(entity in self.existing for entity in suggestions.values()))
        self.assertNotIn("bms_charge_current", suggestions)
        self.assertNotIn("battery_alarm", suggestions)
        self.assertNotIn("battery_fault", suggestions)

    def test_absent_alternative_and_existing_original_are_not_changed(self):
        self.existing.clear()
        self.assertEqual(self.suggest(), {})
        self.existing.update({"sensor.sample_battery", self.generated["soc"]})
        self.assertNotIn("soc", self.suggest())

    def test_manual_ids_empty_fields_and_other_profiles_remain_unchanged(self):
        values = {**self.generated, "soc": "sensor.custom_battery_soc", "tou_gc_1": "",
                  "tou_gc_2": "switch.custom_slot_2"}
        suggestions = self.suggest(values)
        for key in ("soc", "tou_gc_1", "tou_gc_2"):
            self.assertNotIn(key, suggestions)
        for profile in ("manual", "yambms"):
            self.assertEqual(self.suggest(profile=profile), {})
        self.assertEqual(self.suggest(phases=3), {})

    async def test_source_preview_proposes_existing_aliases_without_mutating_saved_sources(self):
        flow = self.flow()
        before = deepcopy(flow.config_entry.options)
        form = await flow.async_step_sources()
        fields = source_input(form)
        self.assertEqual(fields["soc"], "sensor.sample_battery")
        self.assertEqual(fields["tou_gc_6"], "switch.sample_time_of_use_6_charge_enable")
        preview = form["description_placeholders"]["prefix_preview"]
        self.assertIn("jednofazowego", preview)
        self.assertIn("bms_charge_current", preview)
        self.assertIn("95%", preview)
        self.assertIn("maksymalnego prądu ładowania odczytanego z ustawień Deye", preview)
        self.assertIn("brak poprawnych odczytów alarmu i błędu blokuje sterowanie", preview)
        self.assertEqual(flow.config_entry.options, before)
        result = await flow.async_step_sources(fields)
        self.assertEqual(result["data"]["sources"]["soc"], "sensor.sample_battery")
        self.assertEqual(result["data"]["sources"]["bms_charge_current"], self.generated["bms_charge_current"])
        self.assertEqual(flow.config_entry.options, before)

    async def test_existing_ccl_preview_keeps_lower_limit_and_zero_invalid_guards(self):
        self.existing.add(self.generated["bms_charge_current"])
        form = await self.flow().async_step_sources()
        preview = form["description_placeholders"]["prefix_preview"]
        self.assertNotIn("Brak encji bieżącego limitu BMS", preview)
        self.assertIn("Przypisany bieżący limit BMS dodatkowo ogranicza limit Deye", preview)
        self.assertIn("błędnym lub niedostępnym odczytem nie pozwala", preview)
        self.assertIn("CCL równy 0 A blokuje ładowanie", preview)

    async def test_manual_and_yambms_preview_do_not_offer_deye_limit_substitution(self):
        for profile in ("manual", "yambms"):
            with self.subTest(profile=profile):
                form = await self.flow(profile=profile).async_step_sources()
                preview = form["description_placeholders"]["prefix_preview"]
                self.assertNotIn("95%", preview)
                self.assertNotIn("sam limit Deye", preview)

    async def test_existing_inverter_alarm_sensors_are_proposed_and_selectable_only_in_native_one_phase(self):
        self.existing.update({"sensor.sample_device_alarm", "sensor.sample_device_fault"})
        suggestions = self.suggest()
        self.assertEqual(suggestions["battery_alarm"], "sensor.sample_device_alarm")
        self.assertEqual(suggestions["battery_fault"], "sensor.sample_device_fault")
        form = await self.flow().async_step_sources()
        fields = {marker.key: selector for marker, selector in form["data_schema"].items()}
        for key in ("battery_alarm", "battery_fault"):
            self.assertEqual(fields[key]["args"][0]["domain"], ["binary_sensor", "sensor"])
        self.assertIn("opisują cały falownik", form["description_placeholders"]["prefix_preview"])
        self.assertIn("Tylko stan OK", form["description_placeholders"]["prefix_preview"])
        self.assertNotIn("Brak źródeł alarmu", form["description_placeholders"]["prefix_preview"])
        values = {**self.generated, "battery_alarm": "", "battery_fault": "binary_sensor.manual_fault"}
        self.assertNotIn("battery_alarm", self.suggest(values))
        self.assertNotIn("battery_fault", self.suggest(values))
        self.existing.add(self.generated["battery_alarm"])
        self.assertNotIn("battery_alarm", self.suggest())
        for profile in ("manual", "yambms"):
            other = await self.flow(profile=profile).async_step_sources()
            fields = {marker.key: selector for marker, selector in other["data_schema"].items()}
            self.assertEqual(fields["battery_alarm"]["args"][0]["domain"], "binary_sensor")

    async def test_manual_override_on_save_is_authoritative(self):
        flow = self.flow()
        form = await flow.async_step_sources()
        result = await flow.async_step_sources({**source_input(form), "soc": "sensor.chosen_soc",
                                               "tou_gc_1": "switch.chosen_charge"})
        self.assertEqual(result["data"]["sources"]["soc"], "sensor.chosen_soc")
        self.assertEqual(result["data"]["sources"]["tou_gc_1"], "switch.chosen_charge")

    async def test_fresh_install_uses_existing_one_phase_aliases_after_selected_model(self):
        flow = self.module["DeyeEMSConfigFlow"]()
        flow.hass = SimpleNamespace(states=SimpleNamespace(get=self.get_state))
        form = await flow.async_step_user({"inverter_model": "SUN-5K-SG04LP1-EU",
            "inverter_phases": "3", "connection_phases": "1", "inverter_phase": "L1",
            "entity_prefix": self.prefix, "battery_source_profile": "deye", "min_soc_percent": 40})
        self.assertEqual(form["step_id"], "user_inverter_confirm")
        result = await flow.async_step_user_inverter_confirm({"confirm_model": True})
        self.assertEqual(result["data"]["inverter_phases"], 1)
        self.assertEqual(result["data"]["sources"]["soc"], "sensor.sample_battery")
        self.assertEqual(result["data"]["sources"]["tou_gc_1"], "switch.sample_time_of_use_1_charge_enable")
        self.assertNotIn("active", result["data"])


if __name__ == "__main__":
    unittest.main()
