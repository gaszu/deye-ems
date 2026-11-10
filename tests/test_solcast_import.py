"""Synthetic import snapshots; no HA, API, filesystem reads or credentials."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[1]/"custom_components/deye_ems/solcast_import.py"
SPEC = importlib.util.spec_from_file_location("pure_solcast_import", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
import_existing_options = MODULE.import_existing_options
KEY = "synthetic-private-import-key"


def options(**changes):
    return {"api_key": KEY, "api_limit": "8", "auto_dampen": True,
            "site_damp": True, "exclude_sites": [], **changes}


def snapshot(values=None):
    values = list(values) if values is not None else [1.]*48
    return {"integration_automated": True, "last_updated": "2026-11-10T12:30:00+01:00",
            "factors": [{"interval": f"{i//2:02}:{30*(i%2):02}", "factor": value}
                        for i, value in enumerate(values)]}


class SolcastImport(unittest.TestCase):
    def test_actual_sensor_schema_preserves_48_values_without_averaging(self):
        values = [0., .25, .5, .75]*12
        result = import_existing_options(options(), snapshot(values))
        config, report = result["config"], result["report"]
        self.assertEqual(config["half_hourly_factors"], values)
        self.assertEqual(config["hourly_factors"], [1.]*24)
        self.assertEqual(config["dampening_factor"], 1)
        self.assertTrue(report["calibration_imported"])
        self.assertTrue(report["needs_manual_review"])
        self.assertEqual(report["calibration_kind"], "global_snapshot")
        self.assertIn("automatic_learning_not_migrated", report["warnings"])

    def test_true_zero_is_not_missing_or_replaced_by_one(self):
        result = import_existing_options(options(), snapshot([0.]*48))
        self.assertEqual(result["config"]["half_hourly_factors"], [0.]*48)

    def test_24_factors_expand_each_hour_into_two_distinct_half_hours(self):
        result = import_existing_options(options(), {"hourly_factors": [.25, 1.]*12})
        self.assertEqual(result["config"]["half_hourly_factors"], [.25, .25, 1., 1.]*12)

    def test_clock_keyed_map_and_unsorted_records_normalize_by_time(self):
        attrs = snapshot([i/24 for i in range(48)])
        attrs["factors"].reverse()
        expected = [i/24 for i in range(48)]
        self.assertEqual(import_existing_options(options(), attrs)["config"]["half_hourly_factors"], expected)
        keyed = {row["interval"]: row["factor"] for row in attrs["factors"]}
        self.assertEqual(import_existing_options(options(), {"factors": keyed})["config"]["half_hourly_factors"], expected)

    def test_explicit_global_scalar_expands_to_48(self):
        result = import_existing_options(options(), {"dampening_factor": .8})
        self.assertEqual(result["config"]["half_hourly_factors"], [.8]*48)

    def test_all_overrides_site_factors_instead_of_multiplying_them(self):
        result = import_existing_options(options(), {"site_factors": {"ALL": [.5]*48, "roof-a": [.2]*48}})
        self.assertEqual(result["config"]["half_hourly_factors"], [.5]*48)
        self.assertEqual(result["config"]["site_factors"], {})
        self.assertTrue(result["report"]["global_override"])
        self.assertEqual(result["report"]["ignored_site_factor_count"], 1)

    def test_sensor_global_table_overrides_separate_site_tables(self):
        attrs = {**snapshot([.8]*48), "site_factors": {"roof-a": [.4]*48}}
        result = import_existing_options(options(), attrs)
        self.assertEqual(result["config"]["site_factors"], {})
        self.assertEqual(result["config"]["half_hourly_factors"], [.8]*48)

    def test_per_site_curves_keep_separate_ids_and_neutralize_global_layers(self):
        result = import_existing_options(options(), {"site_factors": {"roof-a": [.4]*24, "roof-b": .8}})
        self.assertEqual(result["config"]["site_factors"], {"roof-a": [.4]*48, "roof-b": [.8]*48})
        self.assertEqual(result["config"]["half_hourly_factors"], [1.]*48)
        self.assertEqual(result["report"]["calibration_kind"], "per_site_snapshot")
        self.assertEqual(result["report"]["site_factor_count"], 2)

    def test_canonical_api_limit_and_excluded_sites_are_imported_without_report_ids(self):
        result = import_existing_options(options(api_quota="10", exclude_sites=["roof-private"]), snapshot())
        self.assertEqual(result["config"]["max_requests_per_day"], 8)
        self.assertEqual(result["config"]["initial_requests_used"], 8)
        self.assertEqual(result["config"]["exclude_sites"], ["roof-private"])
        self.assertNotIn("roof-private", json.dumps(result["report"]))
        self.assertFalse(result["report"]["quota_usage_known"])

    def test_legacy_quota_alias_is_supported_when_canonical_absent(self):
        source = options(api_quota="7")
        del source["api_limit"]
        self.assertEqual(import_existing_options(source, snapshot())["config"]["max_requests_per_day"], 7)

    def test_fixed_options_are_accepted_only_when_complete_and_not_adaptive(self):
        source = options(auto_dampen=False, site_damp=False)
        source.update({f"damp{i:02}": i/24 for i in range(24)})
        result = import_existing_options(source)
        self.assertEqual(result["report"]["calibration_kind"], "fixed_options")
        self.assertFalse(result["report"]["needs_manual_review"])
        self.assertEqual(result["config"]["half_hourly_factors"][2:4], [1/24]*2)
        del source["damp12"]
        with self.assertRaisesRegex(ValueError, "incomplete_fixed_calibration"):
            import_existing_options(source)

    def test_adaptive_missing_sensor_never_falls_back_to_static_option_ones(self):
        source = options(**{f"damp{i:02}": 1 for i in range(24)})
        for attrs in (None, {}, {"factors": []}):
            with self.assertRaises(ValueError):
                import_existing_options(source, attrs)

    def test_missing_duplicate_and_invalid_intervals_are_rejected(self):
        for mutation in (lambda rows: rows.pop(), lambda rows: rows[1].update(interval="00:00"),
                         lambda rows: rows[1].update(interval="00:15"), lambda rows: rows[1].pop("factor")):
            attrs = snapshot()
            mutation(attrs["factors"])
            with self.assertRaises(ValueError):
                import_existing_options(options(), attrs)

    def test_out_of_range_nonfinite_boolean_and_missing_factors_are_rejected(self):
        for value in (-.01, 2.01, float("nan"), float("inf"), None, True, "nan"):
            attrs = snapshot()
            attrs["factors"][7]["factor"] = value
            with self.assertRaises(ValueError):
                import_existing_options(options(), attrs)

    def test_bounds_and_conflicting_sources_fail_without_echoing_values(self):
        for attrs in ({"factors": [1]*100000}, {"site_factors": {str(i): [1]*48 for i in range(34)}},
                      {"factors": [.5]*48, "ALL": [.8]*48}):
            with self.assertRaises(ValueError) as caught:
                import_existing_options(options(), attrs)
            self.assertNotIn(KEY, str(caught.exception))

    def test_private_key_and_suppression_entity_never_enter_report(self):
        attrs = {**snapshot(), "api_key": KEY, "token": KEY,
                 "friendly_name": KEY, "automated_dampening_suppression_entity": "input_boolean.private_solcast_suppression",
                 "automated_dampening_model_days": 14, "automated_dampening_adaptive_model_exclude": ["roof-private"]}
        result = import_existing_options(options(), attrs)
        report = json.dumps(result["report"])
        for secret in (KEY, "input_boolean.private_solcast_suppression", "roof-private"):
            self.assertNotIn(secret, report)
        self.assertEqual(result["config"]["api_key"], KEY)
        self.assertEqual(result["config"]["import_metadata"]["automated_dampening_suppression_entity"],
                         "input_boolean.private_solcast_suppression")
        self.assertIn("source_suppression_not_implemented", result["report"]["warnings"])
        self.assertTrue(result["report"]["needs_manual_review"])

    def test_forecast_rows_and_physical_capacity_are_never_imported_or_invented(self):
        result = import_existing_options({**options(), "capacity": 13.5, "capacity_dc": 13.5,
                    "latitude": 50, "longitude": 20}, {**snapshot(), "detailedForecast": [{"pv_estimate": 99}]})
        serialized = json.dumps(result)
        for name in ("pv_peak_kwp", "pv_forecast_reference_kwp", "latitude", "longitude", "detailedForecast"):
            self.assertNotIn(name, serialized)
        self.assertEqual(result["report"]["corrections_apply_to"], "raw_solcast_api_only")
        self.assertTrue(result["report"]["ha_forecast_already_calibrated"])
        self.assertNotIn("config_generation", result["config"])

    def test_import_does_not_mutate_inputs_or_share_arrays(self):
        source, attrs = options(), snapshot()
        before = deepcopy((source, attrs))
        result = import_existing_options(source, attrs)
        result["config"]["half_hourly_factors"][0] = .1
        self.assertEqual((source, attrs), before)

    def test_invalid_keys_ids_and_limits_fail_with_sanitized_errors(self):
        for changes in ({"api_key": ""}, {"exclude_sites": ["../bad"]}, {"exclude_sites": ["roof-a", "roof-a"]},
                        {"api_limit": KEY}, {"api_limit": 0}, {"api_limit": 8.5}):
            with self.assertRaises(ValueError) as caught:
                import_existing_options(options(**changes), snapshot())
            self.assertNotIn(KEY, str(caught.exception))


if __name__ == "__main__":
    unittest.main()
