"""Hardware catalog boundaries cannot increase installation limits."""
from copy import deepcopy
import math
import unittest

from test_installable import MODELS as models


class InverterModels(unittest.TestCase):
    def test_unset_profile_keeps_legacy_three_phase_lv_contract(self):
        profile = models.hardware_profile({})
        self.assertEqual((profile["model_id"], profile["phases"], profile["connection_phases"]),
                         ("custom", 3, 3))
        self.assertEqual((profile["battery_min_v"], profile["battery_max_v"]), (40, 65))
        self.assertIsNone(profile["max_charge_current_a"])
        self.assertTrue(profile["control_supported"])
        before = dict(inverter_max_power_kw=9, inverter_phase_max_power_kw=4,
                      discharge_max_kw=7, combined_output_limit_kw=8)
        self.assertEqual(models.applied_limits(before), before)

    def test_catalog_has_exact_eu_lv_ids_and_primary_source_ratings(self):
        choices = models.model_choices()
        self.assertEqual(len({v["value"] for v in choices}), len(choices))
        for key, model in models.INVERTER_MODELS.items():
            with self.subTest(model=key):
                self.assertIn("EU", key)
                self.assertNotIn("24-EU", key)
                self.assertEqual(model["battery_min_v"], 40)
                self.assertEqual(model["battery_max_v"], 60)
                self.assertTrue(model["source_url"].startswith((
                    "https://www.deyeinverter.com/", "https://deye.com/")))
                self.assertGreater(model["max_charge_current_a"], 0)
                self.assertEqual(model["tou_periods"], 6)

    def test_model_choice_derives_phases_without_guessing_connection(self):
        selected = models.model_selection(dict(inverter_model="SUN-5K-SG04LP1-EU",
            inverter_phases="3", connection_phases="3", inverter_phase="L2"))
        self.assertEqual(selected["inverter_phases"], 1)
        self.assertEqual(models.hardware_profile(selected)["inverter_phase"], "L2")
        with self.assertRaisesRegex(ValueError, "invalid_connection_phases"):
            models.model_selection(dict(inverter_model="SUN-12K-SG04LP3-EU", connection_phases="1"))

    def test_catalog_clamps_power_but_never_increases_lower_user_values(self):
        base = dict(inverter_model="SUN-5K-SG04LP1-EU", inverter_phases=1,
                    inverter_max_power_kw=12, inverter_phase_max_power_kw=8,
                    discharge_max_kw=10, combined_output_limit_kw=10)
        before = deepcopy(base)
        limited = models.applied_limits(base)
        self.assertEqual(set(limited.values()), {5.})
        self.assertEqual(base, before)
        for key in limited:
            base[key] = 2.
        self.assertEqual(set(models.applied_limits(base).values()), {2.})

    def test_manual_single_phase_still_cannot_exceed_its_total_power(self):
        values = dict(inverter_phases=1, inverter_max_power_kw=4, inverter_phase_max_power_kw=8)
        self.assertEqual(models.applied_limits(values)["inverter_phase_max_power_kw"], 4)

    def test_three_phase_catalog_phase_ceiling_is_separate_from_total(self):
        options = dict(inverter_model="SUN-12K-SG04LP3-EU", inverter_phases=3,
                       inverter_max_power_kw=12, inverter_phase_max_power_kw=10)
        self.assertEqual(models.applied_limits(options),
                         dict(inverter_max_power_kw=12, inverter_phase_max_power_kw=6,
                              combined_output_limit_kw=12, discharge_max_kw=12))
        options["inverter_phase_max_power_kw"] = 5
        self.assertEqual(models.applied_limits(options)["inverter_phase_max_power_kw"], 5)

    def test_invalid_unknown_hv_or_inconsistent_profile_fails_closed(self):
        invalid = ({"inverter_model": "SUN-25K-SG01HP3-EU-AM2"},
                   {"inverter_model": "typo"}, {"inverter_model": []},
                   {"inverter_phases": True}, {"inverter_phases": 2},
                   {"connection_phases": False}, {"connection_phases": 1},
                   {"inverter_phase": "L4"},
                   {"inverter_model": "SUN-5K-SG04LP1-EU", "inverter_phases": 3},
                   {"inverter_phases": 1, "connection_phases": 1, "inverter_phase": "L2"})
        for options in invalid:
            with self.subTest(options=options), self.assertRaises(ValueError):
                models.hardware_profile(options)
        for value in (True, -1, 0, math.inf, math.nan, "12"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                models.applied_limits({"inverter_max_power_kw": value})

