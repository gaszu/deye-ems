"""Activation reports actual mapped mode mismatches without changing hardware."""
import unittest
from test_runtime import Harness, SOURCES


class ActivationModes(unittest.IsolatedAsyncioTestCase):
    async def test_each_incompatible_mode_names_entity_actual_and_expected(self):
        cases = (("solar_sell", "off", "on"), ("tou_enabled", "off", "on"),
                 ("energy_priority", "Battery First", "Load First"),
                 ("work_mode", "Selling First", "Zero Export To Load"))
        for key, actual, expected in cases:
            with self.subTest(key=key):
                h = Harness()
                h.set(key, actual)
                with self.assertRaises(ValueError) as error:
                    await h.co.async_set_mode("active")
                message = str(error.exception)
                self.assertIn(SOURCES[key], message)
                self.assertIn(f"odczyt [{actual}]", message)
                self.assertIn(f"wymagane [{expected}]", message)
                self.assertEqual(h.co.mode, "shadow")
                self.assertEqual(h.calls, [])

    def test_missing_restored_and_unavailable_are_distinguished_and_all_reported(self):
        h = Harness()
        del h.states[SOURCES["solar_sell"]]
        h.set("tou_enabled", "on", attributes={"restored": True})
        h.set("energy_priority", "unavailable")
        issues = h.co._hardware_mode_issues()
        self.assertEqual(len(issues), 3)
        self.assertIn("brak encji", issues[0])
        self.assertIn("stan odtworzony", issues[1])
        self.assertIn("unavailable", issues[2])
        self.assertFalse(h.co._hardware_modes_ok())
        self.assertEqual(h.calls, [])

    def test_other_instance_mappings_are_used_instead_of_default_entity_ids(self):
        h = Harness(initial={"sources": {"work_mode": "select.second_inverter_mode"}})
        h.set("work_mode", "Selling First")
        message = h.co._hardware_mode_issues()[0]
        self.assertIn("select.second_inverter_mode", message)
        self.assertNotIn(SOURCES["work_mode"], message)

    def test_matching_modes_have_no_issues(self):
        h = Harness()
        self.assertEqual(h.co._hardware_mode_issues(), [])
        self.assertTrue(h.co._hardware_modes_ok())
