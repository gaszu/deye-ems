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
    def test_balanced_port_does_not_treat_native_load_as_a_single_phase_charger(self):
        h = ct_harness()
        h.set("asymmetric_phase_feeding", "on")
        h.set("load_power", 3104, "W")
        h.set("grid_power", 4966, "W")
        h.set("ct_grid_power", 4966, "W")
        h.set("grid_current_number", 35, "A")
        for i, load, port in ((1, 143, 1651), (2, 2581, 1662), (3, 380, 1653)):
            h.set(f"load_l{i}_power", load, "W")
            h.set(f"grid_l{i}_power", port, "W")
            h.set(f"ct_grid_l{i}_power", port, "W")
        inputs = h.co._read_inputs(h.now)
        self.assertIs(inputs["grid_charge_balanced"], True)
        grid = h.co._grid_input(inputs, h.now, 75, False)
        cap = runtime.calculate_grid_charge_increase_cap(grid)
        watts_per_amp = grid["battery_voltage_v"] / grid.get("charge_efficiency", .9)
        self.assertGreater(cap["increase_cap_a"], 70)
        self.assertLessEqual(cap["increase_cap_a"] * watts_per_amp, 9500 - 3104)
        h.set("ct_grid_l2_power", 4550, "W")
        h.set("ct_grid_power", 7854, "W")
        grid = h.co._grid_input(h.co._read_inputs(h.now), h.now, 75, False)
        cap = runtime.calculate_grid_charge_increase_cap(grid)
        self.assertLessEqual((cap["increase_cap_a"] - 35) * watts_per_amp / 3 + 4550, 4750)
        self.assertLessEqual(runtime.calculate_grid_charge_cap(grid)["cap_a"] * watts_per_amp,
                             3 * (4750 - (4550 - 1662)) - 3104)
        h.set("grid_l2_power", 2000, "W")
        h.set("grid_power", 5304, "W")
        self.assertIs(h.co._read_inputs(h.now)["grid_charge_balanced"], False)

    def test_grid_export_to_ct_branch_consumes_the_shared_conversion_budget(self):
        h = ct_harness()
        h.set("grid_current_number", 35, "A")
        h.set("load_power", 3000, "W")
        for export in (6000, 7000, 10000):
            with self.subTest(export=export):
                h.set("grid_power", -export, "W")
                for i in (1, 2, 3):
                    h.set(f"grid_l{i}_power", -export / 3, "W")
                grid = h.co._grid_input(h.co._read_inputs(h.now), h.now, 75, False)
                cap = runtime.calculate_grid_charge_cap(grid)
                self.assertTrue(cap["telemetry_ok"])
                headroom = max(10000 - 3000 - export, 0)
                self.assertEqual(cap["converter_cap_a"], int(headroom / cap["power_per_a_w"]))
                self.assertLessEqual(cap["cap_a"], cap["converter_cap_a"])
                if headroom == 0:
                    result = runtime.calculate_grid_charge({**grid, "safety_only": True})
                    self.assertEqual(result["next_a"], 0)
                    self.assertTrue(result["write"])

    async def test_connection_limit_can_exceed_inverter_rating_without_raising_converter_cap(self):
        h = ct_harness()
        await h.co.async_set_option("grid_import_limit_kw", 16)
        await h.co.async_set_option("grid_phase_limit_kw", 7)
        # The14kW utility import includes5kW of the passive CT branch;
        # only9kW traverses the10kW inverter's GRID port.
        h.set("grid_power", 9000, "W")
        h.set("ct_grid_power", 14000, "W")
        for i in (1, 2, 3):
            h.set(f"grid_l{i}_power", 3000, "W")
            h.set(f"ct_grid_l{i}_power", 14000/3, "W")
        inputs = h.co._read_inputs(h.now)
        self.assertTrue(inputs["telemetry_valid"])
        g = h.co._grid_input(inputs, h.now, 85, False)
        cap = runtime.calculate_grid_charge_cap(g)
        self.assertEqual(g["total_limit_w"], 16000)
        self.assertEqual(g["conversion_total_limit_w"], 10000)
        self.assertEqual(g["inverter_grid_import_limit_w"], 10000)
        self.assertTrue(cap["inverter_port_within_limits"])
        self.assertTrue(cap["grid_within_limits"])
        self.assertGreater(cap["cap_a"], 0)
        low = runtime.calculate_grid_charge_cap({**g, "total_limit_w": 10000})
        self.assertFalse(low["grid_within_limits"])
        self.assertLess(low["cap_a"], cap["cap_a"])

    async def test_saved_ct_selection_survives_coordinator_reload_and_activation(self):
        h = ct_harness()
        h.entry.options = {**h.entry.options, "topology": "load_only"}
        h.co._options["topology"] = "load_only"
        await h.co.async_set_option("topology", "load_with_external_ct")
        self.assertEqual(h.entry.options["topology"], "load_with_external_ct")
        await h.co.async_shutdown()
        h.co = fixtures.Coordinator(h.hass, h.entry, store=h.store, clock=lambda: h.now,
                                    statistics_provider=h.statistics)
        await h.co.async_initialize()
        h.co._plan_due = h.now.timestamp()+10000
        await h.co.async_request_refresh()
        self.assertEqual(h.co.options["topology"], "load_with_external_ct")
        self.assertEqual(h.co._hardware_mode_issues(), [])
        await h.co.async_set_mode("active")
        self.assertEqual(h.co.mode, "active")

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

    def test_ct_sequential_power_reports_keep_twenty_second_boundary(self):
        for skew, valid in ((10.5, True), (20, True), (20.001, False), (31, False)):
            with self.subTest(skew=skew):
                h = ct_harness()
                h.set("ct_grid_l1_power", 0, "W", age=skew)
                self.assertEqual(h.co._read_inputs(h.now)["telemetry_valid"], valid)

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
                    h.co._sources["ct_grid_power"] = h.co._sources["grid_power"]
                else:
                    h.set("ct_grid_l1_power", 0, "W", age=21)
                self.assertFalse(h.co._read_inputs(h.now)["telemetry_valid"])
                with self.assertRaisesRegex(ValueError, "Topologia CT"):
                    h.co._preflight()

    def test_legacy_aliases_cannot_feed_port_limit_in_ct_mode(self):
        h = ct_harness()
        h.set("grid_power", 6000, "W")
        h.set("ct_grid_power", 13000, "W")
        for phase, port, utility in ((1, 2000, 4400), (2, 2000, 4300), (3, 2000, 4300)):
            h.set(f"grid_l{phase}_power", port, "W")
            h.set(f"ct_grid_l{phase}_power", utility, "W")
            h.set_entity(SOURCES[f"grid_l{phase}_power"], utility, "W")
        h.set_entity(SOURCES["grid_power"], 13000, "W")
        inputs = h.co._read_inputs(h.now)
        self.assertTrue(inputs["telemetry_valid"])
        self.assertEqual(inputs["grid_port_power"], 6000)
        self.assertEqual(inputs["grid_power"], 13000)
        self.assertEqual(inputs["outside_load_w"], 7000)
        self.assertEqual(h.co._options["sources"]["grid_power"], SOURCES["grid_power"])
        self.assertEqual(h.co.options["sources"]["grid_power"], "sensor.deye_inverter_internal_ct_power")
        del h.states[h.co._sources["grid_power"]]
        self.assertFalse(h.co._read_inputs(h.now)["telemetry_valid"])

    def test_custom_ct_port_mapping_and_load_defaults_are_preserved(self):
        manual = "sensor.independent_grid_port_meter"
        h = Harness(options={"topology": "load_with_external_ct",
                             "sources": {"grid_power": manual}})
        self.assertEqual(h.co._sources["grid_power"], manual)
        self.assertEqual(Harness().co._sources["grid_power"], SOURCES["grid_power"])

    def test_negative_branch_on_one_phase_cannot_be_hidden_by_other_phases(self):
        with self.assertRaises(ValueError):
            runtime.ct_load_balance(3000, [1000]*3, 0, [500, -500, 0], 2000, [0, 2000, 0])

    async def test_profile_adds_external_branch_once_using_signed_history(self):
        h = ct_harness()
        async def provider(*args):
            rows = fixtures.ProfilesAndCache().rows
            return {SOURCES["load_power"]: rows(h.now, 3000),
                    SOURCES["ct_grid_power"]: rows(h.now, 0),
                    h.co._sources["grid_power"]: rows(h.now, -2000)}
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
