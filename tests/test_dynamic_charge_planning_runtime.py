"""Offline boundary checks for hardware-derived planner charging budgets.

The framework is stubbed, but real telemetry validation and planning handoff
run. No test dispatches a command or claims a physical device response.
"""
from copy import deepcopy
import unittest

from test_runtime import Harness, SOURCES


def charging_harness(**options):
    h = Harness(options=options)
    h.set("max_charge_current_number", 200, "A")
    h.set("bms_charge_current", 180, "A")
    return h


async def captured_settings(h, during_points=None):
    captured = []

    def planner(value):
        captured.append(deepcopy(value["config"]))
        # Deliberately isolate the runtime handoff from planner projections.
        return {"status": "fallback", "quality": "invalid",
                "source": "offline_boundary_stub", "targets": {}, "rows": []}

    async def points(now):
        if during_points is not None:
            during_points()
        return {}

    h.co._planner = planner
    h.co._solar_points = points
    await h.co._make_plan(h.now, h.co._read_inputs(h.now))
    if len(captured) != 1:
        raise AssertionError("Expected exactly one planner handoff")
    if h.calls:
        raise AssertionError("Planning must not dispatch hardware commands")
    return captured[0]


class DynamicChargePlanningRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_total_pv_budget_does_not_inherit_grid_actuator_range(self):
        h = charging_harness()
        h.set("grid_current_number", 0, "A", attributes={"max": 40})
        settings = await captured_settings(h)
        self.assertEqual(settings["battery_charge_max_a"], 180)
        self.assertEqual(settings["grid_current_max_a"], 40)
        self.assertEqual(settings["battery_voltage_v"], 54)
        live = h.co._grid_input(h.co._read_inputs(h.now), h.now, 75, False)
        self.assertEqual(settings["eta_ac_dc"], live["charge_efficiency"])
        self.assertEqual(settings["eta_charge"], live["charge_storage_efficiency"])
        self.assertNotIn("charge_max_kw", settings)

    async def test_general_deye_limit_differs_from_grid_ninety_five_percent(self):
        h = charging_harness()
        h.set("max_charge_current_number", 101, "A")
        settings = await captured_settings(h)
        self.assertEqual(settings["battery_charge_max_a"], 101)
        self.assertEqual(settings["grid_current_max_a"], 95)

    async def test_hardware_limits_and_voltage_are_re_read_after_slow_forecast(self):
        h = charging_harness()

        def changed():
            h.set("max_charge_current_number", 100, "A")
            h.set("bms_charge_current", 130, "A")
            h.set("grid_current_number", 0, "A", attributes={"max": 70})
            h.set("voltage", 50, "V")

        settings = await captured_settings(h, changed)
        self.assertEqual(settings["battery_charge_max_a"], 100)
        self.assertEqual(settings["grid_current_max_a"], 70)
        self.assertEqual(settings["battery_voltage_v"], 50)

    async def test_bms_block_and_zero_charge_allowance_block_both_budgets(self):
        for key, value in (("bms_blocking_charge", 1), ("bms_charge_current", 0)):
            with self.subTest(key=key):
                h = charging_harness()
                h.set(key, value, "A" if key == "bms_charge_current" else None)
                settings = await captured_settings(h)
                self.assertEqual(settings["battery_charge_max_a"], 0)
                self.assertEqual(settings["grid_current_max_a"], 0)

    async def test_invalid_general_deye_source_never_restores_fixed_power(self):
        for mutation in ("missing", "wrong_unit", "restored", "future", "alias"):
            with self.subTest(mutation=mutation):
                h = charging_harness(charge_max_kw=5.3)
                if mutation == "missing":
                    del h.states[SOURCES["max_charge_current_number"]]
                elif mutation == "wrong_unit":
                    h.set("max_charge_current_number", 200, "W")
                elif mutation == "restored":
                    h.set("max_charge_current_number", 200, "A", attributes={"restored": True})
                elif mutation == "future":
                    h.set("max_charge_current_number", 200, "A", age=-1)
                else:
                    h.co._sources["max_charge_current_number"] = SOURCES["grid_current_number"]
                settings = await captured_settings(h)
                self.assertIsNone(settings["battery_charge_max_a"])
                self.assertIsNone(settings["grid_current_max_a"])
                self.assertNotIn("charge_max_kw", settings)

    async def test_last_minute_telemetry_loss_cannot_keep_previous_power_budget(self):
        for key, value, unit in (("load_l1_power", "unavailable", "W"),
                                 ("voltage", "unavailable", "V"),
                                 ("bms_charge_current", "unavailable", "A")):
            with self.subTest(key=key):
                h = charging_harness()
                settings = await captured_settings(h, lambda: h.set(key, value, unit))
                self.assertIsNone(settings["battery_charge_max_a"])
                self.assertIsNone(settings["grid_current_max_a"])

    async def test_bad_actuator_metadata_fails_closed_instead_of_using_legacy_limit(self):
        h = charging_harness(charge_max_kw=12)
        h.set("grid_current_number", 0, "A", attributes={"max": "unknown"})
        settings = await captured_settings(h)
        self.assertIsNone(settings["battery_charge_max_a"])
        self.assertIsNone(settings["grid_current_max_a"])

    async def test_legacy_fixed_power_is_ignored_while_capacity_and_reserve_are_preserved(self):
        captures = []
        for legacy in (.1, 5.3, 12, "obsolete"):
            with self.subTest(legacy=legacy):
                h = charging_harness(charge_max_kw=legacy, capacity_kwh=80,
                                     min_soc_percent=55, reserve_margin_soc_percent=7)
                before = deepcopy(h.entry.options)
                settings = await captured_settings(h)
                captures.append(settings)
                self.assertEqual(settings["capacity_kwh"], 80)
                self.assertEqual(settings["minimum_soc_percent"], 55)
                self.assertEqual(settings["margin_soc_percent"], 7)
                self.assertEqual(h.entry.options, before)
                self.assertEqual(h.co.mode, "shadow")
                self.assertNotIn("charge_max_kw", settings)
        self.assertTrue(all(item == captures[0] for item in captures))
