"""Reserve follows the inverter's low-SoC setting, with a five-point margin."""
from types import SimpleNamespace
import unittest

from test_runtime import Harness, SOURCES, runtime
import test_installable as boundary
import test_planner as planner_tests


class DynamicSOC(unittest.IsolatedAsyncioTestCase):
    def test_planner_validates_fifteen_percent_only_with_explicit_lower_bound(self):
        data = planner_tests.fixture()
        data["config"].update(minimum_soc_percent=15, minimum_soc_lower_bound=15)
        self.assertEqual(planner_tests.plan_energy(data)["quality"], "valid")
        data["config"]["minimum_soc_percent"] = 14
        self.assertEqual(planner_tests.plan_energy(data)["quality"], "invalid")

    async def test_ten_percent_low_allows_fifteen_but_rejects_fourteen(self):
        h = Harness()
        await h.co.async_set_option("min_soc_percent", 15)
        self.assertEqual(h.co.options["min_soc_percent"], 15)
        self.assertEqual(h.co.options["min_soc_lower_bound"], 15)
        self.assertEqual(h.co.options["effective_min_soc_percent"], 15)
        with self.assertRaisesRegex(ValueError, "Battery low SOC"):
            await h.co.async_set_option("min_soc_percent", 14)
        self.assertEqual(h.co.options["min_soc_percent"], 15)
        self.assertEqual(h.calls, [])

    async def test_threshold_rise_raises_effective_floor_and_protected_tou(self):
        h = Harness(options={"min_soc_percent": 15})
        h.active()
        h.set("battery_low_soc", 20, "%")
        for slot in (3, 5):
            h.set(f"tou_soc_{slot}", 15, "%")
        self.assertEqual(h.co._effective_min_soc(), 25)
        await h.co._repair_floor(h.now)
        for slot in (3, 5):
            self.assertEqual(h.states[SOURCES[f"tou_soc_{slot}"]].state, "25")
        self.assertEqual(h.co.options["min_soc_percent"], 15)

    async def test_planner_receives_low_reserve_and_explicit_validated_lower_bound(self):
        h = Harness(options={"min_soc_percent": 15})
        seen = []
        def planner(inputs):
            seen.append(inputs["config"])
            return {"status": "invalid", "targets": {}}
        h.co._planner = planner
        await h.co._make_plan(h.now, h.co._read_inputs(h.now))
        self.assertEqual(seen[0]["minimum_soc_percent"], 15)
        self.assertEqual(seen[0]["minimum_soc_lower_bound"], 15)
        g = h.co._grid_input(h.co._read_inputs(h.now), h.now, 20, False)
        g["soc"] = 17
        decision = runtime.calculate_grid_charge(g)
        self.assertNotEqual(decision["reason"], "window_or_policy_blocked")
        self.assertGreater(decision["need_a"], 0)

    async def test_unavailable_or_restored_threshold_blocks_activation_and_save(self):
        for state, attributes in (("unavailable", {}), ("10", {"restored": True}), ("86", {})):
            with self.subTest(state=state, attributes=attributes):
                h = Harness(options={"min_soc_percent": 15})
                h.set("battery_low_soc", state, "%", attributes=attributes)
                self.assertFalse(h.co.options["min_soc_bound_valid"])
                with self.assertRaises(ValueError):
                    h.co._preflight()
                with self.assertRaises(ValueError):
                    await h.co.async_set_option("min_soc_percent", 15)

    async def test_lost_threshold_does_not_lower_tou_and_stops_grid_charging(self):
        h = Harness(options={"min_soc_percent": 15})
        h.active()
        h.co._memory["soc_floor_guard"] = {"lower_bound": 55}
        h.set("grid_current_number", 30, "A")
        h.set("tou_gc_6", "on")
        h.set("tou_soc_3", 60, "%")
        h.set("battery_low_soc", "unavailable", "%")
        await h.tick()
        self.assertEqual(h.co._effective_min_soc(), 55)
        self.assertEqual(h.current_calls(), [0])
        self.assertEqual(h.states[SOURCES["tou_gc_6"]].state, "off")
        self.assertEqual(h.states[SOURCES["tou_soc_3"]].state, "60")

    async def test_native_flow_uses_dynamic_minimum_and_rejects_invalid_save(self):
        flow = boundary.Installation().flow()["DeyeEMSOptionsFlow"]()
        flow.config_entry = SimpleNamespace(data={}, options={}, runtime_data=None)
        flow.hass = SimpleNamespace(states=SimpleNamespace(get=lambda entity: SimpleNamespace(
            state="10", attributes={"unit_of_measurement": "%"})))
        form = await flow.async_step_parameters()
        selector = next(v for k, v in form["data_schema"].items() if k.key == "min_soc_percent")
        self.assertEqual(selector["args"][0]["min"], 15)
        result = await flow.async_step_parameters({"min_soc_percent": 15})
        self.assertEqual(result["type"], "create_entry")
        result = await flow.async_step_parameters({"min_soc_percent": 14})
        self.assertEqual(result["errors"]["min_soc_percent"], "reserve_below_low_soc")

    def test_fractional_threshold_rounds_margin_up_and_prefix_includes_low_soc(self):
        h = Harness()
        h.set("battery_low_soc", 10.2, "%")
        self.assertEqual(h.co._soc_lower_bound(), 16)
        values = boundary.Installation().flow()
        _, mapping = values["_deye_prefix_sources"]("second_")
        self.assertEqual(mapping["battery_low_soc"], "number.second_battery_low_soc")
