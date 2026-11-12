"""Dynamic charge ceilings, shared PV/grid power and energy conservation."""
from copy import deepcopy
import random
import unittest

from test_planner import fixture, plan_energy, MODULE


class DynamicChargePlanner(unittest.TestCase):
    def test_obsolete_fixed_limit_is_ignored_even_when_malformed(self):
        inputs = fixture(soc=40, load=.1)
        inputs["config"].update(grid_current_max_a=180, battery_charge_max_a=180,
            battery_voltage_v=54, winter_weather_soc_percent=95)
        expected = plan_energy(inputs)
        self.assertTrue(any(row["grid_charge_kw"] > 5.3 for row in expected["rows"]))
        self.assertNotIn("charge_max_kw", MODULE.DEFAULTS)
        for old in (5.3, 0, 1000, None, True, "5.3", float("nan"), {"old": 5.3}):
            with self.subTest(old=old):
                inputs["config"]["charge_max_kw"] = old
                self.assertEqual(plan_energy(inputs), expected)

    def test_missing_or_malformed_current_ceiling_has_no_projection_fallback(self):
        for key in ("battery_charge_max_a", "grid_current_max_a"):
            for value in (None, True, "180", -1, 1001, float("nan"), float("inf")):
                with self.subTest(key=key, value=value):
                    inputs = fixture(soc=60)
                    inputs["config"].update(minimum_soc_percent=55, grid_max_soc_percent=80,
                        winter_weather_soc_percent=85)
                    inputs["config"][key] = value
                    result = plan_energy(inputs)
                    self.assertEqual(result["quality"], "invalid")
                    self.assertEqual(result["rows"], [])
                    self.assertIsNone(result["p10"])
                    self.assertEqual(result["targets"]["night"]["soc_percent"], 80)
            inputs = fixture()
            inputs["config"].pop(key)
            result = plan_energy(inputs)
            self.assertEqual(result["rows"], [])
            self.assertEqual(result["quality"], "invalid")

    def test_zero_total_current_blocks_pv_and_grid_even_with_positive_grid_cap(self):
        inputs = fixture(soc=40, load=.1, pv=10)
        inputs["config"].update(battery_charge_max_a=0, grid_current_max_a=180)
        result = plan_energy(inputs)
        self.assertEqual(result["quality"], "valid")
        self.assertTrue(all(row["pv_charge_kw"] == row["grid_charge_kw"] == 0
                            for row in result["rows"]))

    def test_grid_actuator_ceiling_does_not_limit_pv_charging(self):
        inputs = fixture(soc=40, load=.1, pv=15)
        inputs["config"].update(battery_charge_max_a=200, grid_current_max_a=0,
            battery_voltage_v=54)
        result = plan_energy(inputs)
        self.assertAlmostEqual(result["rows"][0]["pv_charge_kw"], 10.8)
        self.assertTrue(all(row["grid_charge_kw"] == 0 for row in result["rows"]))
        inputs = fixture(soc=40, load=.1)
        inputs["config"].update(battery_charge_max_a=200, grid_current_max_a=40,
            battery_voltage_v=50, winter_weather_soc_percent=95)
        first = plan_energy(inputs)["rows"][0]
        self.assertAlmostEqual(first["grid_charge_kw"], 2)

    def test_total_power_follows_actual_voltage_and_inverter_rating(self):
        for volts, rated, expected in ((40, 12, 4), (65, 12, 6.5), (65, 3, 3)):
            with self.subTest(volts=volts, rated=rated):
                inputs = fixture(soc=40, load=.1, pv=15)
                inputs["config"].update(battery_charge_max_a=100, grid_current_max_a=0,
                    battery_voltage_v=volts, inverter_max_kw=rated)
                result = plan_energy(inputs)
                self.assertEqual(result["quality"], "valid")
                self.assertAlmostEqual(result["rows"][0]["pv_charge_kw"], expected)

    def test_pv_and_grid_share_total_budget_with_efficiency_applied_once(self):
        inputs = fixture(now="2026-11-10T06:00:00+01:00", soc=40, load=.1)
        inputs["config"].update(battery_charge_max_a=100, grid_current_max_a=90,
            battery_voltage_v=50, winter_weather_soc_percent=95, eta_charge=.95,
            eta_ac_dc=.9)
        inputs["forecast"][0].update(pv_p10_kw=3, pv_p50_kw=3)
        first = plan_energy(inputs)["rows"][0]
        self.assertGreater(first["pv_charge_kw"], 0)
        self.assertGreater(first["grid_charge_kw"], 0)
        self.assertAlmostEqual(first["pv_charge_kw"] + first["grid_charge_kw"], 5)
        self.assertAlmostEqual(first["soc_percent"], 40 + 5 * .95 * .5 / .66, places=5)
        self.assertAlmostEqual(first["grid_import_kw"], first["grid_charge_kw"] / .9)

    def test_total_current_also_bounds_grid_when_its_separate_setting_is_higher(self):
        inputs = fixture(soc=40, load=.1)
        inputs["config"].update(battery_charge_max_a=40, grid_current_max_a=190,
            battery_voltage_v=50, winter_weather_soc_percent=95)
        result = plan_energy(inputs)
        self.assertAlmostEqual(result["rows"][0]["grid_charge_kw"], 2)
        self.assertTrue(all(row["grid_charge_kw"] <= 2 + 1e-9 for row in result["rows"]))

    def test_lower_total_budget_cannot_invent_more_energy_before_protected_window(self):
        inputs = fixture(soc=70, load=5, pv=0)
        # A brief PV surplus is followed by load; the prefix-energy test must
        # use the same total charge ceiling as the forward projection.
        inputs["forecast"][12].update(pv_p10_kw=15, pv_p50_kw=15)
        low = deepcopy(inputs)
        low["config"]["battery_charge_max_a"] = 10
        high = deepcopy(inputs)
        high["config"]["battery_charge_max_a"] = 200
        lower, higher = plan_energy(low), plan_energy(high)
        self.assertGreater(lower["targets"]["night"]["required_soc_percent"],
                           higher["targets"]["night"]["required_soc_percent"])

    def test_varied_profiles_preserve_power_energy_and_shared_budgets(self):
        rng = random.Random(1515)
        for amps, grid_amps, voltage in ((60, 40, 50), (180, 170, 54), (200, 0, 60)):
            inputs = fixture(soc=50, load=.1)
            inputs["config"].update(battery_charge_max_a=amps, grid_current_max_a=grid_amps,
                battery_voltage_v=voltage, winter_weather_soc_percent=95)
            for row in inputs["forecast"]:
                pv = rng.uniform(0, 15)
                row.update(pv_p10_kw=pv, pv_p50_kw=pv, load_kw=rng.uniform(.1, 4))
            result = plan_energy(inputs)
            self.assertEqual(result["quality"], "valid")
            energy = 50 * .66
            total = min(12, amps * voltage / 1000)
            grid = min(total, grid_amps * voltage / 1000)
            for row in result["rows"]:
                self.assertLessEqual(row["pv_charge_kw"] + row["grid_charge_kw"], total + 1e-9)
                self.assertLessEqual(row["grid_charge_kw"], grid + 1e-9)
                if row["protected"]:
                    self.assertEqual(row["grid_charge_kw"], 0)
                served = min(row["load_kw"], row["pv_kw"] * .96, 12)
                served += row["battery_discharge_kw"] * .96
                served += row["grid_import_kw"] - row["grid_charge_kw"] / .96
                self.assertAlmostEqual(served, row["load_kw"], places=7)
                energy += ((row["pv_charge_kw"] + row["grid_charge_kw"]) * .95
                           - row["battery_discharge_kw"] / .95) * row["duration_h"]
                self.assertAlmostEqual(energy / .66, row["soc_percent"], places=5)


if __name__ == "__main__":
    unittest.main()
