"""Offline contract and physical-balance checks for the independent planner."""
import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

PATH = Path(__file__).parents[1] / "custom_components/deye_ems/planner.py"
SPEC = importlib.util.spec_from_file_location("deye_ems_planner_under_test", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
plan_energy = MODULE.plan_energy


def fixture(now="2026-11-10T01:00:00+01:00", soc=75, load=.5, pv=0):
    clock = datetime.fromisoformat(now)
    base = int(clock.timestamp() // 1800) * 1800
    rows = []
    for i in range(96):
        t = datetime.fromtimestamp(base + i * 1800, timezone.utc)
        rows.append(dict(timestamp=t.isoformat(), pv_p10_kw=pv, pv_p50_kw=pv, load_kw=load))
    return dict(now=now, soc_percent=soc, forecast=rows,
                config={"pv_peak_kwp": 20, "pv_forecast_reference_kwp": 20,
                        "battery_voltage_v": 54, "grid_current_max_a": 108})


class PlannerTests(unittest.TestCase):
    def test_winter_weather_target_is_separate_from_floor(self):
        result = plan_energy(fixture())
        self.assertEqual(result["quality"], "valid")
        self.assertEqual(result["targets"]["night"]["soc_percent"], 75)
        self.assertEqual(result["targets"]["night"]["deadline"], "2026-11-10T07:00:00+01:00")
        self.assertEqual(len(result["rows"]), 96)

    def test_winter_strong_solar_lowers_weather_target(self):
        result = plan_energy(fixture(load=.2, pv=1))
        self.assertEqual(result["targets"]["night"]["soc_percent"], 45)

    def test_winter_energy_deficit_can_raise_target_above75(self):
        result = plan_energy(fixture(soc=95, load=3.8))
        self.assertGreater(result["targets"]["night"]["required_soc_percent"], 75)

    def test_unreachable_keeps_real_protected_import(self):
        result = plan_energy(fixture(soc=40, load=20))
        self.assertTrue(result["unreachable"])
        self.assertGreater(result["p10"]["protected_import_kwh"], 0)
        self.assertTrue(any(r["protected"] and r["grid_import_kw"] > 0 for r in result["rows"]))

    def test_no_grid_charge_in_protected_windows(self):
        result = plan_energy(fixture(soc=60, load=1))
        self.assertTrue(all(r["grid_charge_kw"] == 0 for r in result["rows"] if r["protected"]))

    def test_first_half_hour_is_partial(self):
        result = plan_energy(fixture(now="2026-11-10T01:15:00+01:00"))
        self.assertAlmostEqual(result["rows"][0]["duration_h"], .25)

    def test_summer_abundant_pv_never_grid_precharges_for_export(self):
        result = plan_energy(fixture(now="2026-07-10T01:00:00+02:00", soc=95, load=.2, pv=3))
        self.assertEqual(result["targets"]["night"]["soc_percent"], 40)
        self.assertFalse(result["targets"]["night"]["emergency"])
        self.assertEqual(result["p50"]["grid_charge_kwh"], 0)
        self.assertGreater(result["p50"]["export_kwh"], 0)
        self.assertAlmostEqual(result["p50"]["maximum_soc_percent"], 100)

    def test_summer_high_soc_low_load_no_emergency_even_without_pv(self):
        result = plan_energy(fixture(now="2026-07-10T01:00:00+02:00", soc=95, load=.1))
        self.assertFalse(result["targets"]["night"]["emergency"])
        self.assertEqual(result["targets"]["night"]["soc_percent"], 40)

    def test_summer_low_reserve_requests_emergency_in_cheap_window(self):
        result = plan_energy(fixture(now="2026-07-10T01:00:00+02:00", soc=40, load=1))
        self.assertTrue(result["targets"]["night"]["emergency"])
        self.assertTrue(result["summer_emergency_window"]["active"])
        self.assertGreaterEqual(result["targets"]["night"]["soc_percent"], 45)
        self.assertEqual(result["baseline_p10"]["grid_charge_kwh"], 0)

    def test_summer_fallback_never_activates_grid_during_protection(self):
        inputs = fixture(now="2026-07-10T08:00:00+02:00")
        inputs["forecast"] = []
        result = plan_energy(inputs)
        self.assertEqual(result["status"], "fallback")
        self.assertFalse(result["summer_emergency_window"]["active"])
        self.assertEqual(result["targets"]["night"]["soc_percent"], 95)
        self.assertEqual(result["rows"], [])

    def test_invalid_forecast_does_not_invent_zero_pv(self):
        inputs = fixture()
        del inputs["forecast"][5]["pv_p10_kw"]
        inputs["retained_targets"] = {"night": 86}
        result = plan_energy(inputs)
        self.assertEqual(result["quality"], "invalid")
        self.assertEqual(result["rows"], [])
        self.assertIsNone(result["p10"])
        self.assertEqual(result["targets"]["night"]["soc_percent"], 86)

    def test_stale_axis_rejected_even_with96rows(self):
        inputs = fixture()
        for r in inputs["forecast"]:
            r["timestamp"] = (datetime.fromisoformat(r["timestamp"]) - timedelta(days=1)).isoformat()
        self.assertIn("axis", plan_energy(inputs)["reason"])

    def test_wrong_risk_quantile_rejected(self):
        inputs = fixture()
        inputs["forecast"][0]["pv_p10_kw"] = 1
        self.assertEqual(plan_energy(inputs)["quality"], "invalid")

    def test_zero_soc_is_real_deficit_not_invalid_default(self):
        result = plan_energy(fixture(soc=0, load=.2))
        self.assertEqual(result["quality"], "valid")
        self.assertTrue(result["unreachable"])
        self.assertLess(result["rows"][0]["soc_percent"], 40)

    def test_stale_soc_without_fresh_voltage_rejected(self):
        inputs = fixture()
        inputs["soc_updated_at"] = "2026-11-09T22:00:00+01:00"
        self.assertEqual(plan_energy(inputs)["quality"], "invalid")
        inputs["voltage_updated_at"] = "2026-11-10T00:59:30+01:00"
        self.assertEqual(plan_energy(inputs)["quality"], "valid")

    def test_dst_repeated_hour_uses_epoch_axis(self):
        inputs = fixture(now="2026-10-25T02:15:00+02:00")
        result = plan_energy(inputs)
        self.assertEqual(result["quality"], "valid")
        stamps = [datetime.fromisoformat(r["timestamp"]).timestamp() for r in result["rows"]]
        self.assertTrue(all(b - a == 1800 for a, b in zip(stamps, stamps[1:])))
        self.assertEqual(result["targets"]["night"]["deadline"], "2026-10-25T07:00:00+01:00")

    def test_load_pc_is_never_added_again(self):
        inputs = fixture(load=2)
        inputs["heatpump_kw"] = 999
        inputs["today_heatpump_kwh"] = 999
        inputs["yesterday_heatpump_kwh"] = 999
        result = plan_energy(inputs)
        self.assertTrue(all(r["load_kw"] == 2 for r in result["rows"]))

    def test_0659_cannot_claim_deadline_achieved(self):
        result = plan_energy(fixture(now="2026-11-10T06:59:00+01:00", soc=40, load=.5))
        self.assertTrue(result["targets"]["night"]["unreachable"])
        self.assertLess(result["targets"]["night"]["projected_p10_deadline_soc_percent"], 75)

    def test_configured90percent_floor_is_respected_in_winter(self):
        inputs = fixture(soc=95, load=.1, pv=1)
        inputs["config"].update({"minimum_soc_percent": 90})
        result = plan_energy(inputs)
        self.assertEqual(result["quality"], "valid")
        self.assertEqual(result["targets"]["night"]["soc_percent"], 95)
        self.assertGreaterEqual(result["p10"]["minimum_soc_percent"], 90)

    def test_summer_normal_target_uses_configured_floor(self):
        inputs = fixture(now="2026-07-10T01:00:00+02:00", soc=100, load=.1, pv=1)
        inputs["config"].update({"minimum_soc_percent": 90})
        result = plan_energy(inputs)
        self.assertEqual(result["targets"]["night"]["soc_percent"], 90)
        self.assertFalse(result["targets"]["night"]["emergency"])
        self.assertEqual(result["p10"]["grid_charge_kwh"], 0)

    def test_fallback_winter_target_cannot_undercut_configured_floor(self):
        inputs = fixture(soc=95)
        inputs["config"].update({"minimum_soc_percent": 90})
        inputs["forecast"] = []
        result = plan_energy(inputs)
        self.assertEqual(result["targets"]["night"]["soc_percent"], 95)
        self.assertEqual(result["rows"], [])

    def test_old_retrieval_cache_is_allowed_with_current_covered_axis(self):
        inputs = fixture()
        inputs["forecast_retrieved_at"] = "2026-10-01T01:00:00+02:00"
        self.assertEqual(plan_energy(inputs)["quality"], "valid")

    def test_near_deadline_summer_deficit_is_not_claimed_feasible(self):
        inputs = fixture(now="2026-07-10T06:59:00+02:00", soc=40, load=1)
        result = plan_energy(inputs)
        self.assertTrue(result["targets"]["night"]["emergency"])
        self.assertTrue(result["targets"]["night"]["unreachable"])
        self.assertGreater(result["p10"]["protected_import_kwh"], 0)

    def test_load_energy_balance_is_never_clipped_to_grid_limit(self):
        inputs = fixture(load=20, soc=40)
        result = plan_energy(inputs)
        self.assertGreater(result["p10"]["grid_limit_excess_kwh"], 0)
        self.assertTrue(result["unreachable"])
        for row in result["rows"]:
            supplied = row["grid_import_kw"] + row["battery_discharge_kw"] * .96 + min(row["pv_kw"] * .96, row["load_kw"], 12)
            supplied -= row["grid_charge_kw"] / .96
            self.assertAlmostEqual(supplied, row["load_kw"], places=7)

    def test_protected25kw_load_allows13kw_ct_import_beyond12kw_inverter_supply(self):
        # A large synthetic battery isolates the inverter's power constraint.
        # The outside branch may receive12kW from GRID-port export and13kW
        # directly from the utility; the entire25kW does not traverse GRID.
        inputs = fixture(now="2026-11-10T07:00:00+01:00", soc=95, load=25, pv=0)
        inputs["config"].update(capacity_kwh=1000, inverter_max_kw=12,
            discharge_max_kw=30, grid_import_max_kw=30)
        result = plan_energy(inputs)
        self.assertEqual(result["quality"], "valid")
        protected = [row for row in result["rows"] if row["protected"]]
        self.assertTrue(protected)
        self.assertAlmostEqual(protected[0]["battery_discharge_kw"] * .96, 12)
        self.assertAlmostEqual(protected[0]["grid_import_kw"], 13)
        for row in protected:
            self.assertEqual(row["grid_charge_kw"], 0)
            self.assertLessEqual(row["battery_discharge_kw"] * .96, 12 + 1e-9)
            self.assertAlmostEqual(row["grid_import_kw"] + row["battery_discharge_kw"] * .96, 25)
        self.assertGreater(result["p10"]["protected_import_kwh"], 0)
        self.assertEqual(result["p10"]["grid_limit_excess_kwh"], 0)

    def test_invalid_unrelated_config_does_not_erase90percent_floor(self):
        inputs = fixture(soc=95)
        inputs["config"].update({"minimum_soc_percent": 90, "eta_charge": 0})
        result = plan_energy(inputs)
        self.assertEqual(result["quality"], "invalid")
        self.assertEqual(result["targets"]["night"]["soc_percent"], 95)

    def test_fallback_respects_configured_grid_charge_ceiling(self):
        inputs = fixture()
        inputs["config"].update({"grid_max_soc_percent": 80})
        inputs["forecast"] = []
        inputs["retained_targets"] = {"night": 90}
        self.assertEqual(plan_energy(inputs)["targets"]["night"]["soc_percent"], 80)

    def test_configurable_winter_weak_weather_target85(self):
        inputs = fixture(soc=95)
        inputs["config"].update({"winter_weather_soc_percent": 85})
        result = plan_energy(inputs)
        self.assertEqual(result["targets"]["night"]["soc_percent"], 85)
        self.assertEqual(result["targets"]["night"]["weather_target_percent"], 85)

    def test_bright_weather_target_is_selected_floor_plus_margin(self):
        inputs = fixture(soc=95, load=.2, pv=1)
        inputs["config"].update({"winter_weather_soc_percent": 85,
                                "minimum_soc_percent": 60, "margin_soc_percent": 5})
        result = plan_energy(inputs)
        self.assertEqual(result["targets"]["night"]["soc_percent"], 65)

    def test_weather_interpolates_between85_and45(self):
        inputs = fixture(soc=95, load=.5, pv=.390625)
        inputs["config"].update({"winter_weather_soc_percent": 85})
        result = plan_energy(inputs)
        self.assertAlmostEqual(result["targets"]["night"]["weather_target_percent"], 65)
        self.assertEqual(result["targets"]["night"]["soc_percent"], 65)

    def test_fallback_keeps_configured_weak_weather_target(self):
        inputs = fixture()
        inputs["config"].update({"winter_weather_soc_percent": 85})
        inputs["forecast"] = []
        self.assertEqual(plan_energy(inputs)["targets"]["night"]["soc_percent"], 85)

    def test_pv_charge_setting12kw_respects_live_current_times_voltage(self):
        inputs = fixture(soc=40, load=.1)
        inputs["config"].update({"charge_max_kw": 12, "grid_import_max_kw": 20})
        result = plan_energy(inputs)
        self.assertEqual(result["quality"], "valid")
        self.assertTrue(all(row["grid_charge_kw"] <= 54 * 108 / 1000 + 1e-9 for row in result["rows"]))

    def test_grid_current54amps_halves_dc_terminal_budget(self):
        inputs = fixture(soc=40, load=.1)
        inputs["config"].update({"charge_max_kw": 12, "grid_import_max_kw": 20,
                                "grid_current_max_a": 54})
        result = plan_energy(inputs)
        self.assertEqual(result["quality"], "valid")
        self.assertTrue(all(row["grid_charge_kw"] <= 54 * 54 / 1000 + 1e-9 for row in result["rows"]))

    def test_dynamic_limit_above108_has_no_hidden_legacy_charger_ceiling(self):
        inputs = fixture(soc=40, load=.1)
        inputs["config"].update(charge_max_kw=12, grid_import_max_kw=30,
            grid_current_max_a=190, battery_voltage_v=54, winter_weather_soc_percent=95)
        result = plan_energy(inputs)
        self.assertEqual(result["quality"], "valid")
        self.assertTrue(any(row["grid_charge_kw"] > 5.3 for row in result["rows"]))
        self.assertTrue(all(row["grid_charge_kw"] <= 10.26 + 1e-9 for row in result["rows"]))

    def test_current_voltage_power_and_conversion_efficiencies_apply_once(self):
        inputs = fixture(soc=40, load=.1)
        inputs["config"].update(charge_max_kw=12, grid_import_max_kw=30,
            grid_current_max_a=100, battery_voltage_v=50, winter_weather_soc_percent=95,
            eta_charge=.95, eta_ac_dc=.9)
        first = plan_energy(inputs)["rows"][0]
        self.assertAlmostEqual(first["grid_charge_kw"], 5)
        self.assertAlmostEqual(first["grid_import_kw"], .1+5/.9)
        self.assertAlmostEqual(first["soc_percent"], 40 + 5*.95*.5/.66, places=5)

    def test_actual_voltage_is_required_without_legacy_power_fallback(self):
        for voltage in (None, "54", float("nan"), 39.9, 65.1):
            with self.subTest(voltage=voltage):
                inputs = fixture()
                inputs["config"]["battery_voltage_v"] = voltage
                self.assertEqual(plan_energy(inputs)["quality"], "invalid")
        inputs = fixture()
        inputs["config"].pop("battery_voltage_v")
        self.assertEqual(plan_energy(inputs)["quality"], "invalid")

    def test_model_charge_power_setting_remains_an_independent_cap(self):
        inputs = fixture(soc=40, load=0)
        inputs["config"].update(grid_current_max_a=250, battery_voltage_v=54,
            charge_max_kw=5.3, winter_weather_soc_percent=95)
        result = plan_energy(inputs)
        self.assertEqual(result["quality"], "valid")
        self.assertTrue(all(row["grid_charge_kw"] <= 5.3 + 1e-9 for row in result["rows"]))

    def test_projected_grid_charge_reserves_house_power_inside_inverter_rating(self):
        inputs = fixture(soc=40, load=3)
        inputs["config"].update(grid_current_max_a=250, battery_voltage_v=54,
            charge_max_kw=12, inverter_max_kw=6, grid_import_max_kw=30,
            winter_weather_soc_percent=95)
        result = plan_energy(inputs)
        self.assertEqual(result["quality"], "valid")
        self.assertTrue(any(row["grid_charge_kw"] > 0 for row in result["rows"]))
        self.assertTrue(all(row["grid_import_kw"] <= 6 + 1e-9 for row in result["rows"]))

    def test_grid_current_zero_never_predicts_grid_charging(self):
        inputs = fixture(soc=40, load=1)
        inputs["config"].update({"grid_current_max_a": 0})
        result = plan_energy(inputs)
        self.assertEqual(result["p10"]["grid_charge_kwh"], 0)
        self.assertTrue(result["targets"]["night"]["unreachable"])

    def test_high_pv_charging_can_use_its_own12kw_budget(self):
        inputs = fixture(now="2026-07-10T01:00:00+02:00", soc=40, load=.1, pv=15)
        inputs["config"].update({"charge_max_kw": 12, "grid_current_max_a": 0})
        result = plan_energy(inputs)
        self.assertEqual(result["p50"]["grid_charge_kwh"], 0)
        self.assertGreater(result["rows"][0]["pv_charge_kw"], 5.3)
        self.assertLessEqual(result["rows"][0]["pv_charge_kw"], 12)

    def _summer_cache(self):
        inputs = fixture(now="2026-07-10T01:00:00+02:00", soc=95, load=.1)
        valid = plan_energy(inputs)
        inputs["retained_targets"] = valid["targets"]
        inputs["forecast"] = []
        return inputs, valid

    def test_valid_summer_cache40_prevents_unnecessary95grid_emergency(self):
        inputs, valid = self._summer_cache()
        result = plan_energy(inputs)
        target = result["targets"]["night"]
        self.assertEqual(target["soc_percent"], 40)
        self.assertFalse(target["emergency"])
        self.assertFalse(result["summer_emergency_window"]["active"])
        self.assertEqual(target["generated_at"], valid["targets"]["night"]["generated_at"])
        self.assertEqual(target["selection_source"], "validated_cache")

    def test_valid_summer_cache50_is_preserved_without_refreshing_age(self):
        inputs, valid = self._summer_cache()
        record = inputs["retained_targets"]["night"]
        record.update(soc_percent=50, emergency=True, grid_charge_allowed=True)
        inputs["now"] = "2026-07-10T02:00:00+02:00"
        result = plan_energy(inputs)
        self.assertEqual(result["targets"]["night"]["soc_percent"], 50)
        self.assertTrue(result["summer_emergency_window"]["active"])
        self.assertEqual(result["targets"]["night"]["generated_at"], "2026-07-10T01:00:00+02:00")

    def test_cache_wrong_date_or_source_or_reachability_is_rejected(self):
        for change in ({"deadline": "2026-07-11T07:00:00+02:00"},
                       {"generated_at": "2026-07-08T01:00:00+02:00"},
                       {"generated_at": "2026-07-10T02:00:00+02:00"},
                       {"source": "old_ems"}, {"season": "winter"},
                       {"unreachable": True}, {"soc_percent": 42},
                       {"emergency": True}):
            with self.subTest(change=change):
                inputs, _ = self._summer_cache()
                inputs["retained_targets"]["night"].update(change)
                result = plan_energy(inputs)
                self.assertEqual(result["targets"]["night"]["soc_percent"], 95)
                self.assertEqual(result["targets"]["night"]["selection_source"], "conservative_fallback")

    def test_changed_floor_invalidates_previous_normal_cache(self):
        inputs, _ = self._summer_cache()
        inputs["config"].update({"minimum_soc_percent": 80})
        result = plan_energy(inputs)
        self.assertEqual(result["targets"]["night"]["soc_percent"], 95)

    def test_wrong_season_generation_is_not_revived_as_winter_cache(self):
        inputs = fixture(now="2026-10-01T01:00:00+02:00", soc=95)
        inputs["forecast"] = []
        inputs["retained_targets"] = {"night": dict(soc_percent=95,
            deadline="2026-10-01T07:00:00+02:00", generated_at="2026-09-30T23:00:00+02:00",
            season="winter", source="own_deterministic_planner", unreachable=False,
            emergency=False, grid_charge_allowed=True)}
        self.assertEqual(plan_energy(inputs)["targets"]["night"]["soc_percent"], 75)

    def test_valid_winter_cache_must_respect_selected_floor_and_buffer(self):
        inputs = fixture(soc=95, load=.1, pv=1)
        inputs["config"].update({"minimum_soc_percent": 80})
        valid = plan_energy(inputs)
        self.assertEqual(valid["targets"]["night"]["soc_percent"], 85)
        inputs["forecast"] = []
        inputs["retained_targets"] = valid["targets"]
        self.assertEqual(plan_energy(inputs)["targets"]["night"]["selection_source"], "validated_cache")
        inputs["config"]["minimum_soc_percent"] = 81
        result = plan_energy(inputs)
        self.assertEqual(result["targets"]["night"]["soc_percent"], 86)
        self.assertEqual(result["targets"]["night"]["selection_source"], "conservative_fallback")

    def test_runtime_epoch_cache_preserves_original_generation(self):
        inputs, _ = self._summer_cache()
        record = inputs["retained_targets"]["night"]
        record["deadline"] = datetime.fromisoformat(record["deadline"]).timestamp()
        record["generated_at"] = datetime.fromisoformat(record["generated_at"]).timestamp()
        result = plan_energy(inputs)
        self.assertEqual(result["targets"]["night"]["soc_percent"], 40)
        self.assertEqual(result["targets"]["night"]["generated_at"], record["generated_at"])
        self.assertFalse(result["summer_emergency_window"]["active"])

    def test_whole_system_preserves_raw_pv_even_when_reference_differs(self):
        inputs = fixture(pv=1)
        inputs["config"].update(pv_peak_kwp=20, pv_forecast_reference_kwp=10)
        result = plan_energy(inputs)
        self.assertEqual(result["quality"], "valid")
        self.assertTrue(all(row["pv_kw"] == 1 for row in result["rows"]))
        self.assertEqual(result["forecast_normalization"]["factor"], 1)
        self.assertIn("pv_reference_differs_whole_system_not_scaled", result["warnings"])

    def test_whole_system_reference_capacity_is_optional(self):
        inputs = fixture(pv=1)
        inputs["config"]["pv_forecast_reference_kwp"] = None
        result = plan_energy(inputs)
        self.assertEqual(result["quality"], "valid")
        self.assertEqual(result["rows"][0]["pv_kw"], 1)

    def test_specific_profile_scales_each_power_point_once(self):
        inputs = fixture(pv=.4, load=.5, soc=95)
        inputs["config"].update(pv_forecast_mode="specific_profile",
                                pv_peak_kwp=20, pv_forecast_reference_kwp=10)
        result = plan_energy(inputs)
        self.assertTrue(all(abs(row["pv_kw"] - .8) < 1e-12 for row in result["rows"]))
        self.assertEqual(result["forecast_normalization"]["factor"], 2)
        self.assertEqual(result["targets"]["night"]["soc_percent"], 45)
        inputs["config"]["pv_peak_kwp"] = 5
        reduced = plan_energy(inputs)
        self.assertTrue(all(abs(row["pv_kw"] - .2) < 1e-12 for row in reduced["rows"]))
        self.assertGreater(reduced["targets"]["night"]["soc_percent"],
                           result["targets"]["night"]["soc_percent"])
        self.assertLess(reduced["p10"]["final_soc_percent"], result["p10"]["final_soc_percent"])

    def test_specific_profile_equal_capacities_never_double_pv(self):
        inputs = fixture(pv=1)
        inputs["config"].update(pv_forecast_mode="specific_profile",
                                pv_peak_kwp=10, pv_forecast_reference_kwp=10)
        result = plan_energy(inputs)
        self.assertEqual(result["quality"], "valid")
        self.assertTrue(all(row["pv_kw"] == 1 for row in result["rows"]))

    def test_specific_profile_requires_reference_and_all_modes_require_installed(self):
        inputs = fixture(pv=1)
        inputs["config"]["pv_peak_kwp"] = None
        self.assertEqual(plan_energy(inputs)["reason"], "pv_capacity_missing")
        inputs["config"].update(pv_peak_kwp=20, pv_forecast_mode="specific_profile",
                                pv_forecast_reference_kwp=None)
        result = plan_energy(inputs)
        self.assertEqual(result["reason"], "pv_capacity_missing")
        self.assertEqual(result["rows"], [])

    def test_bad_capacity_or_excessive_raw_peak_returns_explicit_fallback(self):
        for value in (0, -.1, True, float("nan"), 1001):
            with self.subTest(value=value):
                inputs = fixture(pv=1)
                inputs["config"]["pv_peak_kwp"] = value
                self.assertEqual(plan_energy(inputs)["quality"], "invalid")
                self.assertEqual(plan_energy(inputs)["rows"], [])
        inputs = fixture(pv=16)
        inputs["config"].update(pv_forecast_mode="specific_profile",
                                pv_peak_kwp=20, pv_forecast_reference_kwp=10)
        self.assertEqual(plan_energy(inputs)["reason"], "forecast_capacity_mismatch")

    def test_pv_parameter_or_mode_change_invalidates_cached_target(self):
        for change in ({"pv_peak_kwp": 10}, {"pv_forecast_reference_kwp": 10},
                       {"pv_forecast_mode": "specific_profile"}):
            with self.subTest(change=change):
                inputs, _ = self._summer_cache()
                inputs["config"].update(change)
                result = plan_energy(inputs)
                self.assertEqual(result["targets"]["night"]["soc_percent"], 95)
                self.assertEqual(result["targets"]["night"]["selection_source"], "conservative_fallback")

    def test_whole_system_cache_without_reference_preserves_generation(self):
        inputs = fixture(now="2026-07-10T01:00:00+02:00", soc=95, load=.1)
        inputs["config"]["pv_forecast_reference_kwp"] = None
        valid = plan_energy(inputs)
        inputs["retained_targets"] = valid["targets"]
        inputs["forecast"] = []
        result = plan_energy(inputs)
        self.assertEqual(result["targets"]["night"]["soc_percent"], 40)
        self.assertEqual(result["targets"]["night"]["selection_source"], "validated_cache")


if __name__ == "__main__":
    unittest.main()
