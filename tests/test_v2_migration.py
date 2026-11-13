"""Existing 1.x settings and source ownership survive the 2.x hardware layer.

Synthetic fixtures only. These checks compare the production coordinator's
actual readings/controller snapshots, not a second implementation of control.
"""
from copy import deepcopy
import json
import unittest

from test_runtime import Harness


LEGACY_OPTIONS = {
    "capacity_kwh": 41.5, "pv_peak_kwp": 9.25, "min_soc_percent": 55,
    "reserve_margin_soc_percent": 4, "winter_weather_soc_percent": 82,
    "grid_max_soc_percent": 93, "grid_import_limit_kw": 13.5,
    "grid_phase_limit_kw": 4.25, "inverter_max_power_kw": 9,
    "inverter_phase_max_power_kw": 3.75, "combined_output_limit_kw": 7.5,
    "discharge_max_kw": 6, "topology": "load_only",
    "extra_loads": [{"id": "saved_optional", "name": "Synthetic receiver",
                     "energy_entity": "sensor.synthetic_receiver_total",
                     "power_entity": "sensor.synthetic_receiver_power",
                     "enabled": False, "included_in_load": True}],
}
HARDWARE_DEFAULTS = {"inverter_model": "custom", "inverter_phases": 3,
                     "connection_phases": 3, "inverter_phase": "L1"}


class V2Migration(unittest.IsolatedAsyncioTestCase):
    async def test_loading_old_entry_does_not_write_new_defaults_or_mutate_old_settings(self):
        for mode in ("shadow", "active"):
            with self.subTest(mode=mode):
                h = Harness(options=deepcopy(LEGACY_OPTIONS))
                data_before, options_before = deepcopy(h.entry.data), deepcopy(h.entry.options)
                mappings = deepcopy(h.co._sources)
                h.store.saved = {"mode": mode, "current_policy": {"safe_since": 1},
                                 "target_cache": {"synthetic": {"soc_percent": 77}}}
                await h.co.async_initialize()
                self.assertEqual(h.co.mode, mode)
                self.assertEqual(h.entry.data, data_before)
                self.assertEqual(h.entry.options, options_before)
                self.assertFalse(set(HARDWARE_DEFAULTS) & set(h.entry.options))
                self.assertEqual(h.co._sources, mappings)
                self.assertEqual(h.co.options["battery_source_profile"], "manual")
                for key, value in LEGACY_OPTIONS.items():
                    self.assertEqual(h.co.options[key], value, key)
                self.assertEqual(h.co._memory["target_cache"]["synthetic"]["soc_percent"], 77)
                self.assertIsNone(h.co._memory["current_policy"]["safe_since"])
                self.assertEqual(h.calls, [])

    def test_missing_model_fields_match_explicit_legacy_hardware_in_all_control_inputs(self):
        legacy = Harness(options=deepcopy(LEGACY_OPTIONS))
        explicit = Harness(options={**deepcopy(LEGACY_OPTIONS), **HARDWARE_DEFAULTS})
        a, b = legacy.co._read_inputs(legacy.now), explicit.co._read_inputs(explicit.now)
        self.assertEqual(a, b)
        ga = legacy.co._grid_input(a, legacy.now, 82, False)
        gb = explicit.co._grid_input(b, explicit.now, 82, False)
        self.assertEqual(ga, gb)
        self.assertEqual(legacy.co._controller(ga), explicit.co._controller(gb))
        self.assertEqual(legacy.co.options["effective_hardware_limits"], {
            "inverter_max_power_kw": 9, "inverter_phase_max_power_kw": 3.75,
            "combined_output_limit_kw": 7.5, "discharge_max_kw": 6})

    def test_legacy_profile_is_never_replaced_by_operator_holiday_rules(self):
        h = Harness(options=deepcopy(LEGACY_OPTIONS))
        calendar = h.co.options["tariff_calendar"]
        self.assertEqual(calendar["profile_id"], "legacy_g13")
        self.assertTrue(calendar["runtime_allowed"])
        self.assertFalse(calendar["preview_only"])
        self.assertEqual(len(calendar["today"]), 6)
        self.assertEqual([row["legacy_slot"] for row in calendar["today"]], list(range(1, 7)))

    async def test_invalid_saved_model_never_falls_back_to_controllable_three_phase(self):
        for damaged in ({"inverter_model": "not-a-supported-inverter"},
                        {"inverter_phases": 2},
                        {"inverter_model": "SUN-5K-SG04LP3-EU", "inverter_phases": 1},
                        {"inverter_phases": 3, "connection_phases": 1}):
            with self.subTest(damaged=damaged):
                h = Harness(options={**deepcopy(LEGACY_OPTIONS), **damaged})
                h.store.saved = {"mode": "active"}
                await h.co.async_initialize()
                self.assertEqual(h.co.mode, "shadow")
                readings = h.co._read_inputs(h.now)
                self.assertFalse(readings["hardware_valid"])
                self.assertFalse(readings["telemetry_valid"])
                grid = h.co._grid_input(readings, h.now, 82, False)
                control = h.co._controller(grid)
                self.assertFalse(control["telemetry_ok"])
                self.assertEqual(control["next_a"], 0)
                self.assertEqual(h.calls, [])

    async def test_saved_forecast_credential_and_optional_disabled_receiver_are_preserved(self):
        options = {**deepcopy(LEGACY_OPTIONS), "solcast": {
            "api_key": "synthetic-test-only-key", "enabled": True,
            "resource_ids": ["synthetic-site"], "max_requests_per_day": 7}}
        h = Harness(options=options)
        before = deepcopy(h.entry.options)
        await h.co.async_initialize()
        self.assertEqual(h.entry.options, before)
        self.assertEqual(h.co._options["solcast"], before["solcast"])
        self.assertNotIn("synthetic-test-only-key", json.dumps(h.co.options))
        self.assertEqual(h.co.effective_loads[0]["enabled"], False)
        self.assertFalse(any(row["energy_entity"] == "sensor.synthetic_receiver_total"
                             for row in h.co._channels()))
        # Harness represents an actual saved legacy PC meter. Migration must
        # retain it, independently of a different receiver deliberately OFF.
        self.assertTrue(any(row["id"] == "configured_heatpump" for row in h.co._channels()))
        self.assertEqual(h.calls, [])


if __name__ == "__main__":
    unittest.main()
