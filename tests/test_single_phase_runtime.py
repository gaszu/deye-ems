"""Exercise the real coordinator, guards and limiter with absent native L2/L3.

The HA boundary and service acknowledgements are synthetic, never hardware.
"""
from copy import deepcopy
import unittest

from test_runtime import Harness, SOURCES


def single_harness(*, connection=1, phase="L1", topology="load_only", **options):
    h = Harness(options={"inverter_model": "SUN-5K-SG04LP1-EU", "inverter_phases": 1,
                         "connection_phases": connection, "inverter_phase": phase,
                         "topology": topology, **options})
    # A real single-phase meter needs just its aggregate port readings.
    for kind in ("grid", "load"):
        for i in (1, 2, 3):
            h.states.pop(SOURCES[f"{kind}_l{i}_power"], None)
    h.states.pop(SOURCES["asymmetric_phase_feeding"], None)
    if topology == "load_with_external_ct":
        h.set("work_mode", "Zero Export To CT")
        if connection == 1:
            h.set("ct_grid_power", 2800, "W")
            for i in (1, 2, 3):
                h.states.pop(SOURCES[f"ct_grid_l{i}_power"], None)
        else:
            ct = [700, 500, 500]
            ct[int(phase[-1])-1] += 1800
            h.set("ct_grid_power", sum(ct), "W")
            for i, watts in enumerate(ct, 1):
                h.set(f"ct_grid_l{i}_power", watts, "W")
    return h


class SinglePhaseRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_native_aggregate_readings_activate_without_phase_or_balancing_entities(self):
        h = single_harness()
        inputs = h.co._read_inputs(h.now)
        self.assertTrue(inputs["telemetry_valid"])
        self.assertTrue(inputs["charge_power_valid"])
        self.assertFalse(inputs["grid_charge_balanced"])
        self.assertEqual(inputs["telemetry_issues"], [])
        self.assertEqual([inputs[f"grid_port_l{i}_power"] for i in (1, 2, 3)], [1800, 0, 0])
        await h.co.async_set_mode("active")
        data = await h.tick()
        self.assertEqual(h.co.mode, "active")
        self.assertNotEqual(data["status"], "telemetry_invalid")
        self.assertEqual(data["control"]["phase_model"], "single_phase")

    async def test_single_phase_ct_does_not_require_three_ct_phase_sensors(self):
        h = single_harness(topology="load_with_external_ct")
        inputs = h.co._read_inputs(h.now)
        self.assertTrue(inputs["telemetry_valid"])
        self.assertEqual(inputs["outside_load_w"], 1000)
        self.assertEqual(inputs["load_power"], 2800)
        self.assertEqual(inputs["grid_power"], 2800)
        h.active()
        data = await h.tick()
        self.assertTrue(data["control"]["telemetry_ok"])

    async def test_single_phase_inverter_on_l2_with_three_phase_ct_preserves_all_house_phases(self):
        h = single_harness(connection=3, phase="L2", topology="load_with_external_ct")
        inputs = h.co._read_inputs(h.now)
        self.assertTrue(inputs["telemetry_valid"])
        self.assertEqual([inputs[f"grid_port_l{i}_power"] for i in (1, 2, 3)], [0, 1800, 0])
        self.assertEqual([inputs[f"grid_l{i}_power"] for i in (1, 2, 3)], [700, 2300, 500])
        self.assertEqual(inputs["outside_load_w"], 1700)
        self.assertEqual(inputs["load_power"], 3500)
        h.active()
        data = await h.tick()
        self.assertEqual(data["control"]["phase_model"], "single_phase")
        self.assertTrue(data["control"]["telemetry_ok"])

    async def test_missing_stale_or_aliased_native_port_readings_prevent_activation(self):
        for error in ("missing", "stale", "alias"):
            with self.subTest(error=error):
                h = single_harness()
                if error == "missing":
                    h.states.pop(SOURCES["grid_power"])
                elif error == "stale":
                    h.set("grid_power", 1800, "W", age=31)
                else:
                    h.co._sources["battery_power"] = h.co._sources["grid_power"]
                self.assertFalse(h.co._read_inputs(h.now)["telemetry_valid"])
                with self.assertRaises(ValueError):
                    h.active()
                await h.tick()
                self.assertEqual(h.calls, [])

    async def test_three_phase_ct_requires_all_real_phase_measurements(self):
        h = single_harness(connection=3, phase="L2", topology="load_with_external_ct")
        h.states.pop(SOURCES["ct_grid_l3_power"])
        self.assertFalse(h.co._read_inputs(h.now)["telemetry_valid"])
        with self.assertRaises(ValueError):
            h.active()

    async def test_live_catalog_limits_bound_controller_and_plan_without_rewriting_diagnostics(self):
        h = single_harness(inverter_max_power_kw=12, inverter_phase_max_power_kw=12)
        h.set("bms_charge_current", 300, "A")
        h.set("max_charge_current_number", 300, "A")
        h.set("voltage", 41, "V")
        inputs = h.co._read_inputs(h.now)
        self.assertEqual(inputs["bms_cap_a"], 300)
        self.assertEqual(inputs["deye_max_charge_current_a"], 300)
        g = h.co._grid_input(inputs, h.now, 75, False)
        self.assertEqual(g["battery_total_cap_a"], 120)
        self.assertEqual(g["conversion_total_limit_w"], 5000)
        self.assertEqual(g["inverter_grid_import_limit_w"], 5000)
        recorded = []
        h.co._planner = lambda payload: recorded.append(deepcopy(payload)) or {
            "quality": "invalid", "targets": {}, "rows": []}
        await h.co._make_plan(h.now, inputs)
        self.assertEqual(recorded[0]["config"]["battery_charge_max_a"], 120)
        self.assertEqual(recorded[0]["config"]["grid_current_max_a"], 120)
        self.assertEqual(recorded[0]["config"]["inverter_max_kw"], 5000 / 1000)

    async def test_catalog_voltage_and_unknown_or_mismatched_model_fail_closed(self):
        for setting in ({"inverter_model": "SUN-NONEXISTENT"}, {"inverter_phases": 3},
                        {"connection_phases": 1, "inverter_phase": "L2"}):
            with self.subTest(setting=setting):
                h = single_harness(**setting)
                self.assertFalse(h.co._read_inputs(h.now)["telemetry_valid"])
                with self.assertRaises(ValueError):
                    h.active()
        h = single_harness()
        h.set("voltage", 61, "V")
        self.assertFalse(h.co._read_inputs(h.now)["telemetry_valid"])

    async def test_phase_configuration_cannot_be_mutated_one_field_at_a_time(self):
        h = single_harness()
        for mode in ("shadow", "active"):
            h.co._memory["mode"] = mode
            for key, value in (("inverter_phases", 3), ("connection_phases", 3),
                               ("inverter_model", "custom"), ("inverter_phase", "L2")):
                with self.subTest(mode=mode, key=key):
                    with self.assertRaisesRegex(ValueError, "kreator"):
                        await h.co.async_set_option(key, value)

    async def test_explicit_hardware_change_invalidates_old_targets_but_retains_api_accounting(self):
        h = Harness()
        await h.tick()
        h.co._memory.update(target_cache={"old": {"soc_percent": 80}},
                            load_profiles={"profiles": {"False": [9] * 24}},
                            solcast_seed={"used": 4})
        h.co._options.update(inverter_phases=1, connection_phases=1)
        await h.tick()
        self.assertNotIn("old", h.co._memory["target_cache"])
        self.assertEqual(h.co._memory["solcast_seed"], {"used": 4})
        self.assertEqual(h.co.mode, "shadow")


if __name__ == "__main__":
    unittest.main()
