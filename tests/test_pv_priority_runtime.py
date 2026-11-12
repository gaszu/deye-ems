"""Offline freshness, meter selection and durable live PV-priority checks."""
from datetime import datetime
import unittest
from unittest.mock import AsyncMock

from test_runtime import Harness, SOURCES, TZ, runtime


def grid(h):
    return h.co._grid_input(h.co._read_inputs(h.now), h.now, 75, False)


def native_grid(h, watts, *, age=0):
    h.set("grid_power", watts, "W", age=age)
    for phase in (1, 2, 3):
        h.set(f"grid_l{phase}_power", watts / 3, "W", age=age)


class PVPriorityRuntime(unittest.IsolatedAsyncioTestCase):
    def test_handoff_uses_signed_battery_power_and_independent_total_current_limit(self):
        h = Harness()
        h.set("max_charge_current_number", 101, "A")
        h.set("bms_charge_current", 180, "A")
        h.set("grid_current_number", 0, "A", attributes={"max": 40})
        h.set("battery_power", -4000, "W")
        snapshot = grid(h)
        self.assertTrue(snapshot["telemetry_valid"])
        self.assertEqual(snapshot["battery_power_w"], -4000)
        self.assertEqual(snapshot["battery_total_cap_a"], 101)
        self.assertEqual(snapshot["deye_cap_a"], 95)
        self.assertEqual(snapshot["actuator_cap_a"], 40)
        self.assertEqual(h.calls, [])

    def test_battery_and_native_grid_alignment_boundaries(self):
        for battery_age, port_age, valid in ((0, 10, True), (0, 10.001, False),
                                              (30, 20, True), (30.001, 20, False),
                                              (20, 20, True)):
            with self.subTest(battery_age=battery_age, port_age=port_age):
                h = Harness()
                h.set("battery_power", -2000, "W", age=battery_age)
                native_grid(h, 1800, age=port_age)
                inputs = h.co._read_inputs(h.now)
                self.assertEqual(inputs["charge_power_valid"], valid)
                self.assertEqual(inputs["telemetry_valid"], valid)

    def test_one_misaligned_native_phase_invalidates_the_combined_snapshot(self):
        h = Harness()
        h.set("battery_power", -2000, "W")
        h.set("grid_l2_power", 600, "W", age=11)
        inputs = h.co._read_inputs(h.now)
        self.assertFalse(inputs["charge_power_valid"])
        self.assertFalse(inputs["telemetry_valid"])
        self.assertIsNone(inputs["grid_charge_balanced"])

    def test_battery_and_native_grid_sources_must_not_be_aliased(self):
        for key in ("grid_power", "grid_l1_power", "grid_l2_power", "grid_l3_power"):
            with self.subTest(key=key):
                h = Harness()
                h.co._sources["battery_power"] = SOURCES[key]
                inputs = h.co._read_inputs(h.now)
                self.assertFalse(inputs["charge_power_valid"])
                self.assertFalse(inputs["telemetry_valid"])
                self.assertIsNone(inputs["grid_charge_balanced"])

    def test_invalid_battery_power_cannot_be_used_as_a_pv_credit(self):
        for mutation in ("missing", "unavailable", "future", "restored", "unit", "range"):
            with self.subTest(mutation=mutation):
                h = Harness()
                if mutation == "missing":
                    del h.states[SOURCES["battery_power"]]
                elif mutation == "unavailable":
                    h.set("battery_power", "unavailable", "W")
                elif mutation == "future":
                    h.set("battery_power", -2000, "W", age=-1)
                elif mutation == "restored":
                    h.set("battery_power", -2000, "W", attributes={"restored": True})
                elif mutation == "unit":
                    h.set("battery_power", -2000, "kW")
                else:
                    h.set("battery_power", -60001, "W")
                inputs = h.co._read_inputs(h.now)
                self.assertFalse(inputs["charge_power_valid"])
                self.assertFalse(inputs["telemetry_valid"])
                snapshot = h.co._grid_input(inputs, h.now, 75, False)
                result = runtime.calculate_grid_charge(snapshot)
                self.assertFalse(result["telemetry_ok"])
                self.assertEqual(result["next_a"], 0)
                self.assertEqual(h.calls, [])

    def test_total_charge_limit_keeps_a_genuine_bms_block(self):
        h = Harness()
        h.set("bms_blocking_charge", 1)
        h.set("battery_power", -2000, "W")
        snapshot = grid(h)
        self.assertEqual(snapshot["battery_total_cap_a"], 0)
        self.assertEqual(runtime.calculate_grid_charge(snapshot)["next_a"], 0)

    def test_ct_import_does_not_replace_native_grid_for_pv_priority(self):
        h = Harness(options={"topology": "load_with_external_ct",
                             "grid_import_limit_kw": 30, "grid_phase_limit_kw": 15})
        h.set("work_mode", "Zero Export To CT")
        native_grid(h, -2000)
        h.set("battery_power", -4000, "W")
        h.set("ct_grid_power", 10000, "W")
        for phase in (1, 2, 3):
            h.set(f"ct_grid_l{phase}_power", 10000 / 3, "W")
        snapshot = grid(h)
        self.assertTrue(snapshot["telemetry_valid"])
        self.assertEqual(snapshot["grid_w"], 10000)
        self.assertEqual(snapshot["grid_port_w"], -2000)
        result = runtime.calculate_grid_charge(snapshot)
        self.assertEqual(result["pv_surplus_credit_w"], 3800)
        self.assertEqual(h.calls, [])

    async def test_pv_cover_reduces_immediately_with_durable_attempt_and_no_slow_reads(self):
        h = Harness(when=datetime(2026, 11, 10, 22, 7, tzinfo=TZ))
        native_grid(h, 0)
        h.set("battery_power", -5000, "W")
        h.set("grid_current_number", 60, "A")
        h.set("tou_gc_6", "on")
        h.co._solar_points = AsyncMock(side_effect=AssertionError("No PV HTTP in current control"))
        h.co._load_profile = AsyncMock(side_effect=AssertionError("No history in current control"))
        h.active()
        result = await h.tick()
        self.assertEqual(result["control"]["reason"], "pv_covers_charge_need")
        self.assertEqual(h.current_calls(), [0])
        self.assertEqual(h.states[SOURCES["tou_gc_6"]].state, "off")
        self.assertFalse(any(action == "turn_on" for _, action, _ in h.calls))
        self.assertEqual(h.store.saved["ledger"][SOURCES["grid_current_number"]]["a"], 0)
        self.assertFalse(h.co._memory["current_policy"].get("stopped"))
        h.co._solar_points.assert_not_awaited()
        h.co._load_profile.assert_not_awaited()
        # Loss of PV does not grant an ordinary increase outside :00/:30.
        h.advance(120)
        native_grid(h, 1800)
        h.set("battery_power", 0, "W")
        await h.tick()
        self.assertEqual(h.current_calls(), [0])
        self.assertEqual(h.co.mode, "active")

    async def test_genuine_zero_battery_power_keeps_night_grid_charging_available(self):
        h = Harness(when=datetime(2026, 11, 10, 22, 0, tzinfo=TZ))
        h.set("battery_power", 0, "W")
        h.active()
        result = await h.tick()
        self.assertTrue(result["inputs"]["charge_power_valid"])
        self.assertEqual(result["control"]["pv_surplus_credit_w"], 0)
        self.assertTrue(any(current > 0 for current in h.current_calls()))
        self.assertEqual(h.co.mode, "active")

    async def test_pv_growth_during_store_blocks_old_positive_grid_increase(self):
        for battery_charge_w in (1200, 5000):
            with self.subTest(battery_charge_w=battery_charge_w):
                h = Harness()
                h.set("battery_power", 0, "W")
                h.active()

                def pv_grows():
                    native_grid(h, 0)
                    h.set("battery_power", -battery_charge_w, "W")

                h.store.on_save = pv_grows
                self.assertFalse(await h.co._grid_attempt(40, h.now.timestamp()))
                self.assertEqual(h.current_calls(), [])
                self.assertEqual(h.co._memory["grid_dispatch"]["outcome"], "not_sent")
                latest = runtime.calculate_grid_charge(grid(h))
                self.assertLess(latest["need_a"], 40)
                if battery_charge_w == 1200:
                    self.assertGreater(latest["need_a"], 0)
                else:
                    self.assertEqual(latest["need_a"], 0)

    async def test_pv_growth_during_store_blocks_old_grid_charge_enable(self):
        for battery_charge_w in (1200, 5000):
            with self.subTest(battery_charge_w=battery_charge_w):
                h = Harness()
                h.set("battery_power", 0, "W")
                h.set("grid_current_number", 40, "A")
                h.set("tou_soc_6", 75, "%")
                h.co._memory["ledger"][SOURCES["grid_current_number"]] = {
                    "at": h.now.timestamp() - 600, "a": 40, "action": "set_value"}
                h.active()

                def pv_grows():
                    native_grid(h, 0)
                    h.set("battery_power", -battery_charge_w, "W")

                h.store.on_save = pv_grows
                await h.co._gc(6, True)
                self.assertFalse(any(action == "turn_on" for _, action, _ in h.calls))
                self.assertEqual(h.states[SOURCES["tou_gc_6"]].state, "off")
                self.assertEqual(h.current_calls(), [])
