"""Native Deye-only battery permission without guessing external BMS data."""
from copy import deepcopy
import unittest

from test_fresh_install_defaults import fresh_harness
from test_runtime import Harness


def native_harness(*, text_flags=False, ccl="missing"):
    sources = ({"battery_alarm": "sensor.fixture_device_alarm",
                "battery_fault": "sensor.fixture_device_fault"} if text_flags else {})
    options = {"battery_source_profile": "deye", "sources": sources}
    if text_flags:
        options.update(inverter_model="SUN-5K-SG04LP1-EU", inverter_phases=1, connection_phases=1)
    h = fresh_harness(options=options)
    if text_flags:
        h.set("battery_alarm", "OK")
        h.set("battery_fault", "OK")
    if ccl == "missing":
        h.states.pop(h.co._sources["bms_charge_current"], None)
    elif ccl == "disabled":
        h.co._sources["bms_charge_current"] = ""
    h.set("max_charge_current_number", 200, "A")
    return h


class DeyeSettingFallback(unittest.IsolatedAsyncioTestCase):
    async def test_missing_or_explicitly_disabled_native_ccl_uses_raw_deye_setting(self):
        for ccl in ("missing", "disabled"):
            with self.subTest(ccl=ccl):
                h = native_harness(ccl=ccl)
                before = deepcopy(h.co._options)
                inputs = h.co._read_inputs(h.now)
                self.assertTrue(inputs["telemetry_valid"])
                self.assertTrue(inputs["bms_valid"])
                self.assertEqual(inputs["battery_limit_source"], "deye_setting")
                self.assertEqual(inputs["bms_cap_a"], 200)
                self.assertEqual(inputs["deye_grid_charge_limit_a"], 190)
                self.assertFalse(any(row["source"] == "bms_charge_current" for row in inputs["telemetry_issues"]))
                self.assertEqual(h.co._options, before)
                self.assertEqual(h.calls, [])

    async def test_real_lower_native_ccl_and_zero_continue_to_bind(self):
        for amps in (80, 0):
            with self.subTest(amps=amps):
                h = native_harness(ccl="present")
                h.set("bms_charge_current", amps, "A")
                inputs = h.co._read_inputs(h.now)
                self.assertTrue(inputs["bms_valid"])
                self.assertEqual(inputs["bms_cap_a"], amps)
                self.assertEqual(inputs["battery_limit_source"], "deye_bms")
                control = h.co._controller(h.co._grid_input(inputs, h.now, 75, False))
                self.assertLessEqual(control["cap_a"], amps)

    async def test_existing_bad_ccl_never_falls_back_to_setting(self):
        for issue in ("unknown", "unavailable", "restored", "wrong_unit", "future", "invalid"):
            with self.subTest(issue=issue):
                h = native_harness(ccl="present")
                if issue in ("unknown", "unavailable"):
                    h.set("bms_charge_current", issue, "A")
                elif issue == "restored":
                    h.set("bms_charge_current", 80, "A", attributes={"restored": True})
                elif issue == "wrong_unit":
                    h.set("bms_charge_current", 80, "W")
                elif issue == "future":
                    h.set("bms_charge_current", 80, "A", age=-1)
                else:
                    h.set("bms_charge_current", -1, "A")
                inputs = h.co._read_inputs(h.now)
                self.assertFalse(inputs["bms_valid"])
                self.assertFalse(inputs["telemetry_valid"])
                self.assertEqual(inputs["bms_cap_a"], 0)
                self.assertEqual(inputs["battery_limit_source"], "deye_bms")
                self.assertEqual(h.calls, [])

    async def test_native_setting_fallback_still_requires_independent_live_valid_deye_data(self):
        for issue in ("setting_unavailable", "setting_wrong_unit", "setting_future", "setting_restored",
                      "aliased_setting", "stale_power", "stale_voltage", "missing_alarm"):
            with self.subTest(issue=issue):
                h = native_harness()
                if issue == "setting_unavailable":
                    h.set("max_charge_current_number", "unavailable", "A")
                elif issue == "setting_wrong_unit":
                    h.set("max_charge_current_number", 200, "W")
                elif issue == "setting_future":
                    h.set("max_charge_current_number", 200, "A", age=-1)
                elif issue == "setting_restored":
                    h.set("max_charge_current_number", 200, "A", attributes={"restored": True})
                elif issue == "aliased_setting":
                    h.co._sources["max_charge_current_number"] = h.co._sources["grid_current_number"]
                elif issue == "stale_power":
                    h.set("grid_power", 1800, "W", age=31)
                elif issue == "stale_voltage":
                    h.set("voltage", 54, "V", age=121)
                else:
                    h.states.pop(h.co._sources["battery_alarm"])
                inputs = h.co._read_inputs(h.now)
                self.assertFalse(inputs["telemetry_valid"])
                self.assertFalse(inputs["bms_valid"])
                self.assertEqual(inputs["bms_cap_a"], 0)
                self.assertEqual(h.calls, [])

    async def test_deye_setting_zero_is_valid_but_cannot_authorize_charge(self):
        h = native_harness()
        h.set("max_charge_current_number", 0, "A")
        inputs = h.co._read_inputs(h.now)
        self.assertTrue(inputs["bms_valid"])
        self.assertEqual(inputs["bms_cap_a"], 0)
        self.assertEqual(inputs["deye_grid_charge_limit_a"], 0)
        self.assertEqual(h.co._controller(h.co._grid_input(inputs, h.now, 75, False))["cap_a"], 0)

    async def test_external_and_manual_profiles_never_use_native_setting_fallback(self):
        for profile in ("manual", "yambms"):
            with self.subTest(profile=profile):
                h = Harness(options={"battery_source_profile": profile})
                h.states.pop(h.co._sources["bms_charge_current"])
                h.set("max_charge_current_number", 200, "A")
                inputs = h.co._read_inputs(h.now)
                self.assertFalse(inputs["bms_valid"])
                self.assertEqual(inputs["battery_limit_source"], "external_bms")
                self.assertEqual(inputs["bms_cap_a"], 0)

    async def test_one_phase_device_status_literal_ok_allows_dedicated_setting_limit(self):
        h = native_harness(text_flags=True)
        inputs = h.co._read_inputs(h.now)
        self.assertTrue(inputs["telemetry_valid"])
        self.assertTrue(inputs["bms_valid"])
        self.assertEqual((inputs["battery_limit_source"], inputs["bms_cap_a"]), ("deye_setting", 200))
        self.assertEqual(h.calls, [])

    async def test_one_phase_alarm_fault_active_or_invalid_text_always_blocks(self):
        for source in ("battery_alarm", "battery_fault"):
            for value in ("Error", "Over voltage", "unknown", "unavailable", "N/A", "ok", "OK ", "0"):
                with self.subTest(source=source, value=value):
                    h = native_harness(text_flags=True)
                    h.set(source, value)
                    inputs = h.co._read_inputs(h.now)
                    self.assertEqual(inputs["bms_cap_a"], 0)
                    control = h.co._controller(h.co._grid_input(inputs, h.now, 75, False))
                    self.assertEqual(control["cap_a"], 0)
                    self.assertEqual(h.calls, [])

    async def test_one_phase_text_flag_still_checks_restored_future_and_no_numeric_unit(self):
        for issue in ("restored", "future", "wrong_unit"):
            with self.subTest(issue=issue):
                h = native_harness(text_flags=True)
                if issue == "restored":
                    h.set("battery_fault", "OK", attributes={"restored": True})
                elif issue == "future":
                    h.set("battery_fault", "OK", age=-1)
                else:
                    h.set("battery_fault", "OK", "A")
                inputs = h.co._read_inputs(h.now)
                self.assertFalse(inputs["bms_valid"])
                self.assertFalse(inputs["telemetry_valid"])
                self.assertEqual(inputs["bms_cap_a"], 0)

    async def test_three_phase_text_ok_is_not_silently_accepted_as_binary_flag(self):
        h = native_harness()
        h.co._sources["battery_alarm"] = "sensor.fixture_device_alarm"
        h.set("battery_alarm", "OK")
        inputs = h.co._read_inputs(h.now)
        self.assertFalse(inputs["bms_valid"])
        self.assertEqual(inputs["bms_cap_a"], 0)
