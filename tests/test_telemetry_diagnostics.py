"""Read-only telemetry explanations preserve all existing control decisions."""
from copy import deepcopy
from datetime import timedelta, timezone
import json
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from test_runtime import Harness, runtime

diag = SimpleNamespace(_UTC=timezone.utc, activation_diagnostics=runtime.activation_diagnostics)


def registry_stubs(module):
    helpers = ModuleType("homeassistant.helpers")
    helpers.entity_registry = module
    return {"homeassistant": ModuleType("homeassistant"), "homeassistant.helpers": helpers,
            "homeassistant.helpers.entity_registry": module}


def by_source(inputs):
    return {row["source"]: row for row in inputs["telemetry_details"]}


class TelemetryDiagnostics(unittest.IsolatedAsyncioTestCase):
    async def test_stale_voltage_explains_actual_age_and_existing_limit(self):
        h = Harness()
        h.set("voltage", 54, "V", age=175)
        inputs = h.co._read_inputs(h.now)
        row = by_source(inputs)["voltage"]
        self.assertEqual((row["age_seconds"], row["max_age_seconds"]), (175, 120))
        self.assertEqual((row["value"], row["unit"], row["reason"], row["valid"]),
                         (54, "V", "stale", False))
        self.assertEqual(row["last_reported"],
                         (h.now-timedelta(seconds=175)).astimezone(diag._UTC).isoformat())
        self.assertFalse(inputs["telemetry_valid"])
        with self.assertRaisesRegex(ValueError, r"voltage.*175 s.*120 s"):
            h.co._preflight()
        self.assertEqual(h.calls, [])

    async def test_missing_future_restored_wrong_unit_and_invalid_values(self):
        for reason in ("missing", "future", "restored", "wrong_unit", "invalid"):
            with self.subTest(reason=reason):
                h = Harness()
                if reason == "missing":
                    h.states.pop(h.co._sources["grid_power"])
                elif reason == "future":
                    h.set("grid_power", 1800, "W", age=-3)
                elif reason == "restored":
                    h.set("grid_power", 1800, "W", attributes={"restored": True})
                elif reason == "wrong_unit":
                    h.set("grid_power", 1.8, "kW")
                else:
                    h.set("grid_power", "unknown", "W")
                inputs = h.co._read_inputs(h.now)
                row = by_source(inputs)["grid_power"]
                self.assertEqual(row["reason"], reason)
                self.assertFalse(row["valid"])
                self.assertFalse(inputs["telemetry_valid"])
                if reason == "future":
                    self.assertEqual(row["age_seconds"], -3)
                if reason == "wrong_unit":
                    self.assertEqual((row["unit"], row["expected_unit"]), ("kW", "W"))
                with self.assertRaises(ValueError):
                    h.co._preflight()
                self.assertEqual(h.calls, [])

    async def test_ct_activation_error_also_explains_stale_sensor_age(self):
        h = Harness(options={"topology": "load_with_external_ct"})
        h.set("work_mode", "Zero Export To CT")
        h.set("ct_grid_power", 2800, "W", age=35)
        for i in (1, 2, 3):
            h.set(f"ct_grid_l{i}_power", 2800/3, "W")
        inputs = h.co._read_inputs(h.now)
        self.assertEqual(inputs["topology_error"], "invalid_ct_grid_balance")
        self.assertFalse(inputs["telemetry_valid"])
        with self.assertRaisesRegex(ValueError, r"Topologia CT:.*ct_grid_power.*35 s.*30 s"):
            h.co._preflight()
        self.assertEqual(h.calls, [])

    async def test_bogus_provider_state_unit_and_attributes_never_leak(self):
        secret = "synthetic_secret_bad_sensor_payload"
        h = Harness()
        h.set("grid_power", secret, secret, attributes={"provider_response": secret})
        inputs = h.co._read_inputs(h.now)
        encoded = json.dumps(inputs["telemetry_details"])
        self.assertNotIn(secret, encoded)
        row = by_source(inputs)["grid_power"]
        self.assertIsNone(row["value"])
        self.assertIsNone(row["unit"])
        with self.assertRaises(ValueError) as raised:
            h.co._preflight()
        self.assertNotIn(secret, str(raised.exception))
        # Even finite numeric values outside the expected range are not echoed.
        h.set("grid_power", 123456789012345, "W")
        self.assertIsNone(by_source(h.co._read_inputs(h.now))["grid_power"]["value"])

    async def test_alias_and_coherence_rows_do_not_weaken_original_guards(self):
        h = Harness()
        h.co._sources["max_charge_current_number"] = h.co._sources["grid_current_number"]
        inputs = h.co._read_inputs(h.now)
        self.assertEqual(by_source(inputs)["max_charge_current_number"]["reason"], "alias")
        self.assertFalse(inputs["telemetry_valid"])
        h = Harness()
        h.set("grid_power", 1800, "W", age=11)
        inputs = h.co._read_inputs(h.now)
        rows = by_source(inputs)
        self.assertTrue(rows["grid_power"]["valid"])
        self.assertEqual((rows["charge_power"]["reason"], rows["charge_power"]["observed_time_skew_seconds"],
                          rows["charge_power"]["max_time_skew_seconds"]), ("time_skew", 11, 10))
        self.assertFalse(inputs["charge_power_valid"])
        self.assertFalse(inputs["telemetry_valid"])
        self.assertIn("11 s, dopuszczalne 10 s", diag.activation_diagnostics(inputs["telemetry_details"]))

    async def test_latched_sources_show_age_without_inventing_expiry(self):
        h = Harness()
        h.set("bms_charge_current", 108, "A", age=3600)
        h.set("bms_blocking_charge", 0, age=3600)
        rows = by_source(h.co._read_inputs(h.now))
        for key in ("bms_charge_current", "bms_blocking_charge"):
            self.assertTrue(rows[key]["valid"])
            self.assertEqual(rows[key]["age_seconds"], 3600)
            self.assertIsNone(rows[key]["max_age_seconds"])

    async def test_esphome_hint_requires_real_registry_platform_and_failure(self):
        h = Harness()
        module = ModuleType("homeassistant.helpers.entity_registry")
        module.async_get = lambda hass: SimpleNamespace(async_get=lambda entity:
            SimpleNamespace(platform="esphome"))
        with patch.dict(sys.modules, registry_stubs(module)):
            self.assertEqual(h.co._read_inputs(h.now)["telemetry_hints"], [])
            h.set("voltage", 54, "V", age=175)
            inputs = h.co._read_inputs(h.now)
            row = by_source(inputs)["voltage"]
            self.assertEqual(row["platform"], "esphome")
            self.assertEqual(len(inputs["telemetry_hints"]), 1)
            hint = inputs["telemetry_hints"][0]
            self.assertEqual((hint["provider"], hint["reason"], hint["sources"]),
                             ("esphome", "stale", ["voltage"]))
            self.assertIn("force_update: true", hint["message"])
            self.assertFalse(inputs["telemetry_valid"])
        # An ESPHome-looking entity name alone is not provider evidence.
        self.assertTrue(all(hint["provider"] == "generic"
                            for hint in h.co._read_inputs(h.now)["telemetry_hints"]))

    async def test_registry_failure_is_optional_and_cannot_interrupt_control(self):
        h = Harness()
        h.set("voltage", 54, "V", age=175)
        module = ModuleType("homeassistant.helpers.entity_registry")
        module.async_get = lambda hass: (_ for _ in ()).throw(AssertionError("synthetic_registry_failure"))
        with patch.dict(sys.modules, registry_stubs(module)):
            inputs = h.co._read_inputs(h.now)
            self.assertFalse(inputs["telemetry_valid"])
            self.assertIsNone(by_source(inputs)["voltage"]["platform"])
            self.assertTrue(all(hint["provider"] == "generic" for hint in inputs["telemetry_hints"]))

    async def test_diagnostics_leave_inputs_settings_and_controller_output_unchanged(self):
        enabled, disabled = Harness(), Harness()
        before_options, before_memory = deepcopy(enabled.co._options), deepcopy(enabled.co._memory)
        with patch.object(runtime, "describe_telemetry", return_value=([], [])):
            baseline = disabled.co._read_inputs(disabled.now)
        observed = enabled.co._read_inputs(enabled.now)
        pruned = {key: value for key, value in observed.items()
                  if key not in ("telemetry_details", "telemetry_hints")}
        expected = {key: value for key, value in baseline.items()
                    if key not in ("telemetry_details", "telemetry_hints")}
        self.assertEqual(pruned, expected)
        first = enabled.co._grid_input(observed, enabled.now, 75, False)
        second = disabled.co._grid_input(baseline, disabled.now, 75, False)
        self.assertEqual(enabled.co._controller(first), disabled.co._controller(second))
        self.assertEqual(enabled.co._options, before_options)
        self.assertEqual(enabled.co._memory, before_memory)
        self.assertEqual(enabled.calls, [])

