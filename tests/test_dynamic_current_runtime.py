"""Live Deye limits and physical GRID-port guards at the service boundary."""
from copy import deepcopy
from datetime import datetime
import unittest

from test_runtime import Coordinator, Harness, SOURCES, TZ, runtime


def roomy(*, when=None):
    h = Harness(when=when, options={"inverter_max_power_kw": 30,
                "inverter_phase_max_power_kw": 10, "grid_import_limit_kw": 30,
                "grid_phase_limit_kw": 10, "winter_weather_soc_percent": 85,
                "grid_current_max_a": 108})  # Persisted legacy value is ignored.
    h.set("max_charge_current_number", 200, "A")
    h.set("bms_charge_current", 300, "A")
    h.set("asymmetric_phase_feeding", "on")
    return h


def grid(h):
    return h.co._grid_input(h.co._read_inputs(h.now), h.now, 85, False)


class DynamicCurrentRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_dynamic_limit_exceeds_legacy108_and_is_not_actuator_feedback(self):
        h = roomy()
        for current in (0, 50, 180):
            h.set("grid_current_number", current, "A")
            inputs = h.co._read_inputs(h.now)
            self.assertEqual(inputs["deye_max_charge_current_a"], 200)
            self.assertEqual(inputs["deye_grid_charge_limit_a"], 190)
            self.assertEqual(runtime.calculate_grid_charge_cap(grid(h))["cap_a"], 190)
        h.set("max_charge_current_number", 150, "A")
        self.assertEqual(h.co._read_inputs(h.now)["deye_grid_charge_limit_a"], 142)
        h.set("bms_charge_current", 75, "A")
        self.assertEqual(runtime.calculate_grid_charge_cap(grid(h))["cap_a"], 75)
        self.assertEqual(h.calls, [])

    async def test_number_api_max_is_only_an_additional_upper_bound(self):
        for metadata, expected in (({}, 190), ({"max": 16777220, "min": -16777220}, 190),
                                   ({"max": 150.5}, 150), ({"max": 0}, 0)):
            with self.subTest(metadata=metadata):
                h = roomy()
                h.set("grid_current_number", 0, "A", attributes=metadata)
                inputs = h.co._read_inputs(h.now)
                self.assertTrue(inputs["grid_charge_limit_valid"])
                self.assertEqual(inputs["grid_charge_actuator_max_a"], expected)
                self.assertEqual(runtime.calculate_grid_charge_cap(grid(h))["cap_a"], expected)

    async def test_malformed_present_api_max_fails_closed(self):
        for invalid in (True, "unknown", None, float("nan"), float("inf"), -1):
            with self.subTest(invalid=invalid):
                h = roomy()
                h.set("grid_current_number", 40, "A", attributes={"max": invalid})
                inputs = h.co._read_inputs(h.now)
                self.assertFalse(inputs["grid_charge_limit_valid"])
                self.assertFalse(inputs["telemetry_valid"])
                self.assertEqual(runtime.calculate_grid_charge_cap(grid(h))["cap_a"], 0)

    async def test_latched_deye_setting_requires_live_same_inverter_powers(self):
        h = roomy()
        h.set("max_charge_current_number", 200, "A", age=12*3600)
        self.assertTrue(h.co._read_inputs(h.now)["grid_charge_limit_valid"])
        # BMS voltage remains live: it cannot establish Deye communication.
        h.set("grid_l2_power", 600, "W", age=31)
        inputs = h.co._read_inputs(h.now)
        self.assertTrue(inputs["bms_valid"])
        self.assertFalse(inputs["grid_charge_limit_valid"])
        self.assertFalse(inputs["telemetry_valid"])

    async def test_invalid_or_aliased_setting_does_not_create_a_limit(self):
        for mutation in ("missing", "restored", "unavailable", "unit", "future", "alias"):
            with self.subTest(mutation=mutation):
                h = roomy()
                if mutation == "missing":
                    del h.states[SOURCES["max_charge_current_number"]]
                elif mutation == "restored":
                    h.set("max_charge_current_number", 200, "A", attributes={"restored": True})
                elif mutation == "unavailable":
                    h.set("max_charge_current_number", "unavailable", "A")
                elif mutation == "unit":
                    h.set("max_charge_current_number", 200, "W")
                elif mutation == "future":
                    h.set("max_charge_current_number", 200, "A", age=-1)
                else:
                    h.co._sources["max_charge_current_number"] = SOURCES["grid_current_number"]
                self.assertFalse(h.co._read_inputs(h.now)["grid_charge_limit_valid"])
                with self.assertRaises(ValueError):
                    h.co._preflight()
                self.assertEqual(h.calls, [])

    async def test_deye_reduction_bypasses_half_hour_schedule(self):
        h = roomy(when=datetime(2026, 11, 10, 22, 7, tzinfo=TZ))
        h.set("grid_current_number", 180, "A")
        h.active()
        h.set("max_charge_current_number", 100, "A")
        await h.tick()
        self.assertEqual(h.current_calls(), [95])

    async def test_post_store_deye_limit_drop_blocks_positive_write(self):
        h = roomy()
        h.active()
        h.store.on_save = lambda: h.set("max_charge_current_number", 100, "A")
        self.assertFalse(await h.co._grid_attempt(150, h.now.timestamp()))
        self.assertEqual(h.current_calls(), [])
        self.assertEqual(h.co._memory["grid_dispatch"]["outcome"], "not_sent")

    async def test_post_store_native_port_increase_blocks_write_with_loose_connection(self):
        h = roomy()
        h.co._options.update(inverter_max_power_kw=12, inverter_phase_max_power_kw=5)
        h.active()
        def overloaded_port():
            h.set("grid_power", 11990, "W")
            for i in (1, 2, 3):
                h.set(f"grid_l{i}_power", 11990/3, "W")
        h.store.on_save = overloaded_port
        self.assertFalse(await h.co._grid_attempt(150, h.now.timestamp()))
        self.assertEqual(h.current_calls(), [])
        cap = runtime.calculate_grid_charge_cap(grid(h))
        self.assertEqual(cap["connection_grid_excess_w"], 0)
        self.assertGreater(cap["inverter_port_excess_w"], 0)

    async def test_port_overrun_reduces_current_outside_schedule_without_connection_overrun(self):
        h = roomy(when=datetime(2026, 11, 10, 22, 7, tzinfo=TZ))
        h.co._options.update(inverter_max_power_kw=12, inverter_phase_max_power_kw=5)
        h.set("grid_current_number", 150, "A")
        h.set("tou_gc_6", "on")
        h.set("grid_power", 12100, "W")
        for i in (1, 2, 3):
            h.set(f"grid_l{i}_power", 12100/3, "W")
        h.active()
        inputs = h.co._read_inputs(h.now)
        control = h.co._controller(h.co._grid_input(inputs, h.now, 85, False))
        await h.co._run_driver(inputs, control, 85, False, h.now)
        self.assertEqual(h.current_calls(), [140])
        self.assertEqual(h.states[SOURCES["tou_gc_6"]].state, "off")

    async def test_post_store_metadata_limit_drop_blocks_write(self):
        h = roomy()
        h.active()
        h.store.on_save = lambda: h.set("grid_current_number", 0, "A", attributes={"max": 50})
        self.assertFalse(await h.co._grid_attempt(150, h.now.timestamp()))
        self.assertEqual(h.current_calls(), [])

    async def test_invalid_deye_setting_never_blocks_stricter_zero(self):
        h = roomy(when=datetime(2026, 11, 10, 22, 7, tzinfo=TZ))
        h.set("grid_current_number", 100, "A")
        h.active()
        h.set("max_charge_current_number", "unavailable", "A")
        await h.tick()
        self.assertEqual(h.current_calls(), [0])

    async def test_ct_preserves_native_port_and_load_for_separate_rating_guard(self):
        h = roomy()
        h.co._options["topology"] = "load_with_external_ct"
        h.set("work_mode", "Zero Export To CT")
        h.set("grid_power", 1000, "W")
        h.set("ct_grid_power", 3000, "W")
        for i in (1, 2, 3):
            h.set(f"grid_l{i}_power", 1000/3, "W")
            h.set(f"ct_grid_l{i}_power", 1000, "W")
        inputs = h.co._read_inputs(h.now)
        g = h.co._grid_input(inputs, h.now, 85, False)
        self.assertTrue(inputs["telemetry_valid"])
        self.assertAlmostEqual(g["grid_w"], 3000)
        self.assertAlmostEqual(g["grid_port_w"], 1000)
        self.assertAlmostEqual(g["grid_port_load_w"], 1800)
        self.assertAlmostEqual(g["load_w"], 3800)
        self.assertEqual(g["outside_load_w"], 0)

    async def test_protected_slot_allows_25kw_ct_branch_with_12kw_inverter_supply(self):
        h = roomy(when=datetime(2026, 11, 10, 8, 30, tzinfo=TZ))
        h.co._options.update(topology="load_with_external_ct", inverter_max_power_kw=12,
                             inverter_phase_max_power_kw=5, combined_output_limit_kw=12)
        h.set("work_mode", "Zero Export To CT")
        h.set("soc", 60, "%")
        h.set("load_power", 0, "W")
        h.set("grid_power", -12000, "W")
        h.set("ct_grid_power", 13000, "W")
        for i in (1, 2, 3):
            h.set(f"load_l{i}_power", 0, "W")
            h.set(f"grid_l{i}_power", -4000, "W")
            h.set(f"ct_grid_l{i}_power", 13000/3, "W")
        # Establish the configured metering context in observation first.
        # This is an existing approved CT installation, not a topology change.
        await h.tick()
        h.active()
        h.calls.clear()
        result = await h.tick()
        inputs = result["inputs"]
        self.assertTrue(inputs["telemetry_valid"])
        self.assertIsNone(inputs["topology_error"])
        self.assertAlmostEqual(inputs["outside_load_w"], 25000)
        self.assertAlmostEqual(inputs["load_power"], 25000)
        self.assertEqual(inputs["grid_port_power"], -12000)
        self.assertEqual(inputs["grid_power"], 13000)
        self.assertEqual(inputs["load_and_grid_output_w"], 12000)
        cap = runtime.calculate_grid_charge_cap(grid(h))
        self.assertTrue(cap["grid_within_limits"])
        self.assertTrue(cap["inverter_port_within_limits"])
        self.assertEqual(h.co.mode, "active")
        self.assertEqual(h.states[SOURCES["work_mode"]].state, "Zero Export To CT")
        self.assertEqual(h.current_calls(), [])
        self.assertFalse(any(action == "turn_on" for _, action, _ in h.calls))
        for slot in range(1, 7):
            self.assertEqual(h.states[SOURCES[f"tou_gc_{slot}"]].state, "off")
        self.assertEqual(float(h.states[SOURCES["tou_soc_3"]].state), 40)
        self.assertFalse(any(data["entity_id"] == SOURCES["work_mode"] for _, _, data in h.calls))

    async def test_grid_on_checks_entire_setting_after_store_limit_change(self):
        h = roomy()
        h.set("grid_current_number", 150, "A")
        h.co._memory["ledger"][SOURCES["grid_current_number"]] = {
            "at": h.now.timestamp()-100, "a": 150, "action": "set_value"}
        h.set("tou_soc_6", 85, "%")
        h.active()
        h.store.on_save = lambda: h.set("max_charge_current_number", 100, "A")
        await h.co._gc(6, True)
        self.assertFalse(any(action == "turn_on" for _, action, _ in h.calls))

    async def test_unconfirmed_higher_setting_blocks_gc_after_deye_limit_drop(self):
        h = roomy()
        # A genuine reserve-recovery demand permits the initial high command;
        # the test then isolates cancellation of its unconfirmed register.
        h.set("soc", 30, "%")
        h.set("grid_current_number", 42, "A")
        h.set("tou_gc_6", "on")
        h.set("tou_soc_6", 85, "%")
        h.active()
        original = h.hass.services.async_call
        async def accepted_without_register(domain, action, data, **kwargs):
            if data["entity_id"] == SOURCES["grid_current_number"]:
                h.calls.append((domain, action, deepcopy(data)))
                return
            return await original(domain, action, data, **kwargs)
        h.hass.services.async_call = accepted_without_register
        self.assertTrue(await h.co._grid_attempt(150, h.now.timestamp()))
        h.advance(10)
        h.set("max_charge_current_number", 100, "A")
        inputs = h.co._read_inputs(h.now)
        control = h.co._controller(h.co._grid_input(inputs, h.now, 85, False))
        self.assertEqual(control["next_a"], 42)
        self.assertTrue(control["write"])
        await h.co._run_driver(inputs, control, 85, False, h.now)
        self.assertEqual(h.current_calls(), [150, 42])
        self.assertEqual(grid(h)["pending_current_a"], 150)
        self.assertEqual(h.states[SOURCES["tou_gc_6"]].state, "off")

    async def test_plan_receives_dynamic_hardware_limit_and_voltage_after_slow_reads(self):
        h = roomy()
        captured = []
        original = h.co._planner
        def planner(value):
            captured.append(deepcopy(value["config"]))
            return original(value)
        h.co._planner = planner
        async def delayed_points(now):
            h.set("max_charge_current_number", 150, "A")
            return {}
        h.co._solar_points = delayed_points
        await h.co._make_plan(h.now, h.co._read_inputs(h.now))
        self.assertEqual(captured[0]["grid_current_max_a"], 142)
        self.assertEqual(captured[0]["battery_voltage_v"], 54)

    async def test_legacy_manual_option_is_rejected_when_no_longer_supported(self):
        h = roomy()
        with self.assertRaises(ValueError):
            await h.co.async_set_option("grid_current_max_a", 50)
