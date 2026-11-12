"""Physical limits are independent of the obsolete108A charger model."""
import math
import random
import unittest

from test_grid_control import snapshot, calculate_grid_charge_cap, calculate_grid_charge, calculate_grid_charge_increase_cap


def roomy(**changes):
    base = dict(deye_cap_a=190, actuator_cap_a=190, bms_cap_a=300,
        grid_charge_balanced=True, load_w=0, load_phases_w=[0, 0, 0],
        grid_w=0, grid_phases_w=[0, 0, 0], grid_port_w=0,
        grid_port_phases_w=[0, 0, 0], grid_port_load_w=0,
        grid_port_load_phases_w=[0, 0, 0], total_limit_w=30000,
        phase_limit_w=15000, inverter_grid_import_limit_w=12000,
        inverter_grid_phase_limit_w=5000, conversion_total_limit_w=12000,
        conversion_phase_limit_w=5000)
    base.update(changes)
    return snapshot(**base)


class DynamicCurrentLimits(unittest.TestCase):
    def test_dynamic_limit_above108_reaches190_under_independent_budgets(self):
        cap = calculate_grid_charge_cap(roomy())
        self.assertEqual(cap["cap_a"], 190)
        self.assertEqual(cap["deye_cap_a"], 190)
        self.assertGreater(cap["hard_current_cap_a"], 108)

    def test_deye_bms_and_writable_entity_limits_each_bind_independently(self):
        for key in ("deye_cap_a", "bms_cap_a", "actuator_cap_a"):
            with self.subTest(key=key):
                self.assertEqual(calculate_grid_charge_cap(roomy(**{key: 95}))["cap_a"], 95)
                self.assertEqual(calculate_grid_charge_cap(roomy(**{key: 0}))["cap_a"], 0)

    def test_required_live_limits_and_native_port_measurements_fail_closed(self):
        fields = ("deye_cap_a", "actuator_cap_a", "grid_port_w", "grid_port_phases_w",
                  "grid_port_load_w", "grid_port_load_phases_w",
                  "inverter_grid_import_limit_w", "inverter_grid_phase_limit_w")
        for key in fields:
            with self.subTest(key=key):
                g = roomy(current_a=150, last_attempt_a=150)
                g.pop(key)
                result = calculate_grid_charge(g)
                self.assertFalse(result["telemetry_ok"])
                self.assertTrue(result["safety"])
                self.assertEqual(result["next_a"], 0)

    def test_limit_shrink_reduces_immediately_outside_ordinary_clock(self):
        result = calculate_grid_charge(roomy(current_a=180, last_attempt_a=180,
            last_attempt_ts=999, deye_cap_a=95))
        self.assertTrue(result["safety"])
        self.assertTrue(result["write"])
        self.assertEqual(result["next_a"], 95)

    def test_grid_port_overload_reduces_even_when_utility_ct_has_room(self):
        result = calculate_grid_charge(roomy(current_a=100, last_attempt_a=100,
            last_attempt_ts=999, grid_w=8000, grid_phases_w=[2700, 2700, 2600],
            grid_port_w=11700, grid_port_phases_w=[3900, 3900, 3900]))
        self.assertEqual(result["connection_grid_excess_w"], 0)
        self.assertEqual(result["inverter_port_excess_w"], 200)
        self.assertEqual(result["cap_a"], 96)
        self.assertEqual(result["reason"], "inverter_grid_headroom")
        self.assertTrue(result["write"])

    def test_utility_limit_remains_independent_of_safe_inverter_port(self):
        result = calculate_grid_charge_cap(roomy(current_a=100,
            total_limit_w=12000, grid_w=14000, grid_phases_w=[4700, 4700, 4600],
            grid_port_w=8000, grid_port_phases_w=[2700, 2700, 2600]))
        self.assertEqual(result["inverter_port_excess_w"], 0)
        self.assertEqual(result["connection_grid_excess_w"], 2500)
        self.assertFalse(result["grid_within_limits"])
        self.assertEqual(result["cap_a"], 58)

    def test_port_phase_overload_cannot_hide_inside_a_safe_total(self):
        cap = calculate_grid_charge_cap(roomy(current_a=100,
            grid_port_w=8000, grid_port_phases_w=[4800, 1600, 1600]))
        self.assertEqual(cap["inverter_port_excess_w"], 150)
        self.assertEqual(cap["cap_a"], 97)

    def test_ct_outside_branch_does_not_consume_native_port_load_budget_twice(self):
        native = dict(inverter_grid_import_limit_w=10000,
            conversion_total_limit_w=10000, grid_port_load_w=3000,
            grid_port_load_phases_w=[1000, 1000, 1000])
        small = calculate_grid_charge_cap(roomy(load_w=3000,
            load_phases_w=[1000, 1000, 1000], **native))
        outside = calculate_grid_charge_cap(roomy(load_w=13000,
            load_phases_w=[5000, 4000, 4000], **native))
        self.assertEqual(small["inverter_port_planning_cap_a"], 108)
        self.assertEqual(outside["inverter_port_planning_cap_a"], 108)
        self.assertEqual(outside["cap_a"], small["cap_a"])

    def test_port_export_cannot_borrow_pv_for_a_larger_proactive_setting(self):
        common = roomy(grid_port_load_w=10000,
            grid_port_load_phases_w=[3400, 3300, 3300])
        normal = calculate_grid_charge_cap(common)
        exporting = calculate_grid_charge_cap({**common, "grid_port_w": -8000,
            "grid_port_phases_w": [-3000, -3000, -2000]})
        self.assertEqual(normal["cap_a"], 25)
        self.assertEqual(exporting["cap_a"], normal["cap_a"])

    def test_initial_enable_budgets_entire_register_setting_at_the_port(self):
        g = roomy(current_a=114, last_attempt_a=114, last_attempt_ts=999,
            grid_charge_active=False, grid_port_w=10800,
            grid_port_phases_w=[3600, 3600, 3600])
        result = calculate_grid_charge(g)
        self.assertTrue(result["safety"])
        self.assertEqual(result["next_a"], 11)
        self.assertEqual(calculate_grid_charge_increase_cap({**g, "current_a": 0})["increase_cap_a"], 11)

    def test_need_and_projection_use_voltage_and_storage_efficiency_once(self):
        for voltage in (50, 60):
            with self.subTest(voltage=voltage):
                g = roomy(soc=50, target_soc=51, remaining_h=1,
                    deye_cap_a=10, battery_voltage_v=voltage, charge_storage_efficiency=.95)
                r = calculate_grid_charge(g)
                self.assertEqual(r["need_a"], math.ceil(.66*1000/(voltage*.95)))
                self.assertAlmostEqual(r["projected_soc"], round(50+10*voltage/1000*.95/.66, 3))

    def test_random_dynamic_caps_never_exceed_either_current_or_power_bound(self):
        rng = random.Random(9513108)
        for _ in range(300):
            g = roomy(deye_cap_a=rng.randrange(301), actuator_cap_a=rng.randrange(301),
                bms_cap_a=rng.randrange(301), battery_voltage_v=rng.uniform(40, 65),
                grid_port_load_w=rng.randrange(12001),
                grid_port_load_phases_w=[rng.randrange(5001) for _ in range(3)])
            r = calculate_grid_charge_cap(g)
            self.assertGreaterEqual(r["cap_a"], 0)
            self.assertLessEqual(r["cap_a"], min(g["deye_cap_a"], g["actuator_cap_a"], g["bms_cap_a"]))
            self.assertLessEqual(r["cap_a"]*g["battery_voltage_v"]/.9,
                max(g["inverter_grid_import_limit_w"]-500-max(g["grid_port_load_w"],sum(g["grid_port_load_phases_w"])),0)+1e-9)
