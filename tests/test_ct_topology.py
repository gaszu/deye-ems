"""CT metering separates public-grid exchange from the inverter GRID port."""
from copy import deepcopy
from datetime import timedelta
import unittest

from test_runtime import Harness, SOURCES, runtime
import test_runtime as fixtures
import test_installable as boundary


def ct_harness():
    h = Harness(options={"topology": "load_with_external_ct", "inverter_max_power_kw": 10,
                         "extra_loads_managed": True, "extra_loads": []})
    h.set("work_mode", "Zero Export To CT")
    h.set("load_power", 3000, "W")
    h.set("grid_power", -2000, "W")
    h.set("ct_grid_power", 0, "W")
    for i, load, port in ((1, 1000, -2000), (2, 1000, 0), (3, 1000, 0)):
        h.set(f"load_l{i}_power", load, "W")
        h.set(f"grid_l{i}_power", port, "W")
        h.set(f"ct_grid_l{i}_power", 0, "W")
    return h


class CTTopology(unittest.IsolatedAsyncioTestCase):
    def test_inverter_exports_to_cwu_while_ct_reports_zero_import(self):
        h = ct_harness()
        inputs = h.co._read_inputs(h.now)
        self.assertTrue(inputs["telemetry_valid"])
        self.assertEqual(inputs["grid_power"], 0)
        self.assertEqual(inputs["grid_port_power"], -2000)
        self.assertEqual(inputs["outside_load_w"], 2000)
        self.assertEqual(inputs["load_power"], 5000)
        self.assertEqual(inputs["raw_load_power"], 3000)
        self.assertEqual(inputs["load_and_grid_output_w"], 5000)
        self.assertFalse(inputs["grid_charge_balanced"])
        g = h.co._grid_input(inputs, h.now, 85, False)
        self.assertEqual(g["load_w"], 5000)
        self.assertEqual(g["outside_load_w"], 0)  # already included once
        self.assertEqual(sum(g["load_phases_w"]), 5000)

    def test_ct_import_is_not_confused_with_inverter_port_import(self):
        h = ct_harness()
        h.set("grid_power", 1000, "W")
        h.set("grid_l1_power", 1000, "W")
        h.set("ct_grid_power", 3000, "W")
        h.set("ct_grid_l1_power", 3000, "W")
        inputs = h.co._read_inputs(h.now)
        self.assertEqual(inputs["outside_load_w"], 2000)
        self.assertEqual(inputs["grid_power"], 3000)
        self.assertEqual(inputs["grid_port_power"], 1000)

    def test_ct_work_mode_requires_explicit_ct_topology(self):
        h = ct_harness()
        h.co._preflight()
        h.co._options["topology"] = "load_only"
        with self.assertRaisesRegex(ValueError, "Zero Export To Load"):
            h.co._preflight()
        self.assertEqual(h.calls, [])

    def test_missing_stale_restored_wrong_unit_and_swapped_ct_fail_closed(self):
        for mutation in ("missing", "stale", "restored", "unit", "direction", "same_meter", "skew"):
            with self.subTest(mutation=mutation):
                h = ct_harness()
                if mutation == "missing":
                    del h.states[SOURCES["ct_grid_l1_power"]]
                elif mutation == "stale":
                    h.set("ct_grid_l1_power", 0, "W", age=31)
                elif mutation == "restored":
                    h.set("ct_grid_l1_power", 0, "W", attributes={"restored": True})
                elif mutation == "unit":
                    h.set("ct_grid_l1_power", 0, "kW")
                elif mutation == "direction":
                    h.set("grid_l1_power", 2000, "W")
                    h.set("grid_power", 2000, "W")
                elif mutation == "same_meter":
                    h.co._sources["ct_grid_power"] = SOURCES["grid_power"]
                else:
                    h.set("ct_grid_l1_power", 0, "W", age=11)
                self.assertFalse(h.co._read_inputs(h.now)["telemetry_valid"])
                with self.assertRaisesRegex(ValueError, "Topologia CT"):
                    h.co._preflight()

    def test_negative_branch_on_one_phase_cannot_be_hidden_by_other_phases(self):
        with self.assertRaises(ValueError):
            runtime.ct_load_balance(3000, [1000]*3, 0, [500, -500, 0], 2000, [0, 2000, 0])

    async def test_profile_adds_external_branch_once_using_signed_history(self):
        h = ct_harness()
        async def provider(*args):
            rows = fixtures.ProfilesAndCache().rows
            return {SOURCES["load_power"]: rows(h.now, 3000),
                    SOURCES["ct_grid_power"]: rows(h.now, 0),
                    SOURCES["grid_power"]: rows(h.now, -2000)}
        h.co._statistics_provider = provider
        result = await h.co._load_profile(h.now)
        self.assertTrue(result["profiles"])
        self.assertTrue(all(abs(v-5) < 1e-9 for profile in result["profiles"].values() for v in profile))
        h.co._statistics_provider = lambda *args: None

    async def test_missing_branch_history_does_not_use_load_only_profile(self):
        h = ct_harness()
        async def provider(*args):
            return {SOURCES["load_power"]: fixtures.ProfilesAndCache().rows(h.now, 3000)}
        h.co._statistics_provider = provider
        self.assertEqual(await h.co._load_profile(h.now), {})

    async def test_new_topology_invalidates_old_plan_and_never_auto_resumes(self):
        h = ct_harness()
        h.co._memory["mode"] = "active"
        h.co._memory["plan"] = {"status": "old"}
        h.co._memory["target_cache"] = {"night": {"soc_percent": 75}}
        await h.tick()
        self.assertEqual(h.co.mode, "shadow")
        self.assertEqual(h.co._memory["target_cache"], {})
        self.assertEqual(h.calls, [])

    async def test_plan_receives_one_shared_ten_kw_converter_limit(self):
        h = ct_harness()
        seen = []
        def planner(data):
            seen.append(data["config"])
            return {"status": "invalid", "targets": {}}
        h.co._planner = planner
        await h.co._make_plan(h.now, h.co._read_inputs(h.now))
        self.assertEqual(seen[0]["inverter_max_kw"], 10)
        self.assertLessEqual(seen[0]["discharge_max_kw"], 10)

    async def test_topology_flow_requires_observation(self):
        flow = boundary.Installation().flow()["DeyeEMSOptionsFlow"]()
        flow.config_entry = type("Entry", (), {"runtime_data": type("Runtime", (), {"mode": "active"})(),
                                               "options": {}, "data": {}})()
        result = await flow.async_step_topology({"topology": "load_with_external_ct"})
        self.assertEqual(result["reason"], "stop_before_mapping")
        result = await flow.async_step_parameters({"combined_output_limit_kw": 9})
        self.assertEqual(result["reason"], "stop_before_mapping")
        h = ct_harness()
        h.active()
        with self.assertRaises(ValueError):
            await h.co.async_set_option("combined_output_limit_kw", 9)
