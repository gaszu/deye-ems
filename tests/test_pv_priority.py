"""Offline PV-priority attribution and reduce-only physical feedback.

No source meter claims or device responses are inferred from a current setting.
"""
import math
import unittest

from test_grid_control import snapshot, calculate_grid_charge, calculate_grid_charge_cap, calculate_grid_charge_increase_cap


def charging(**changes):
    values = dict(capacity_kwh=100, soc=50, target_soc=69, remaining_h=4,
        battery_voltage_v=50, bms_cap_a=180, deye_cap_a=190,
        actuator_cap_a=240, battery_total_cap_a=200,
        grid_charge_balanced=True, load_w=0, load_phases_w=[0, 0, 0],
        grid_w=0, grid_phases_w=[0, 0, 0], grid_port_w=0,
        grid_port_phases_w=[0, 0, 0], grid_port_load_w=0,
        grid_port_load_phases_w=[0, 0, 0], total_limit_w=30000,
        phase_limit_w=15000, inverter_grid_import_limit_w=12000,
        inverter_grid_phase_limit_w=5000, conversion_total_limit_w=12000,
        conversion_phase_limit_w=5000)
    values.update(changes)
    return snapshot(**values)


class PVPriority(unittest.TestCase):
    def test_night_zero_and_battery_discharge_receive_no_pv_credit(self):
        for battery in (0, 1500):
            with self.subTest(battery=battery):
                result = calculate_grid_charge(charging(battery_power_w=battery))
                self.assertEqual(result["pv_surplus_credit_w"], 0)
                self.assertAlmostEqual(result["total_charge_pace_w"], 5000)
                self.assertAlmostEqual(result["net_grid_need_w"], 5000)
                self.assertEqual(result["need_a"], 100)

    def test_pv_credit_subtracts_all_native_import_and_storage_efficiency_once(self):
        result = calculate_grid_charge(charging(battery_power_w=-7000,
            grid_port_w=3500, grid_port_phases_w=[1200, 1200, 1100]))
        self.assertEqual(result["pv_surplus_credit_w"], 3300)
        self.assertAlmostEqual(result["total_charge_pace_w"], 5000)
        self.assertAlmostEqual(result["net_grid_need_w"], 1700)
        self.assertEqual(result["need_a"], 34)

    def test_load_bypass_does_not_count_grid_freed_pv_as_an_independent_source(self):
        # PV8/LOAD4/GRID+3.5 can physically charge ~7kW while the net
        # converter still outputs +0.5kW. Crediting all7 would shut grid OFF
        # and then turn it back ON when PV must supply the whole LOAD.
        first = charging(battery_power_w=-7000, grid_port_w=3500,
            grid_port_phases_w=[1200, 1200, 1100],
            grid_port_load_w=4000, grid_port_load_phases_w=[1400, 1300, 1300])
        a = calculate_grid_charge(first)
        # A unity-conversion counterfactual reduction of GRID by2kW also
        # removes2kW battery input; the attributed surplus stays stable.
        second = {**first, "battery_power_w": -5000, "grid_port_w": 1500,
                  "grid_port_phases_w": [500, 500, 500]}
        b = calculate_grid_charge(second)
        self.assertEqual(a["pv_surplus_credit_w"], b["pv_surplus_credit_w"])
        self.assertEqual(a["need_a"], b["need_a"])
        self.assertGreater(a["need_a"], 0)

    def test_setting_readback_is_never_used_as_a_physical_grid_charge_measurement(self):
        credits, needs = set(), set()
        for current in (0, 30, 100):
            result = calculate_grid_charge(charging(current_a=current,
                last_attempt_a=current, battery_power_w=-7000,
                grid_port_w=3500, grid_port_phases_w=[1200, 1200, 1100]))
            credits.add(result["pv_surplus_credit_w"])
            needs.add(result["need_a"])
        self.assertEqual(credits, {3300})
        self.assertEqual(needs, {34})

    def test_ct_and_direct_external_consumption_do_not_enter_pv_attribution(self):
        values = []
        for utility in (0, 13000):
            result = calculate_grid_charge(charging(battery_power_w=-3000,
                grid_w=utility, grid_phases_w=[utility/3]*3,
                grid_port_w=-2000, grid_port_phases_w=[-700, -700, -600]))
            values.append((result["pv_surplus_credit_w"], result["need_a"]))
        self.assertEqual(values, [(2800, 44), (2800, 44)])

    def test_import_sum_of_phases_can_only_reduce_the_credit(self):
        g = charging(battery_power_w=-7000, grid_port_w=3000,
                     grid_port_phases_w=[1400, 1300, 1300])
        self.assertEqual(calculate_grid_charge(g)["pv_surplus_credit_w"], 2800)
        g.update(grid_port_w=-1000, grid_port_phases_w=[1000, 500, 500])
        self.assertEqual(calculate_grid_charge(g)["pv_surplus_credit_w"], 4800)

    def test_power_deadband_does_not_invent_small_pv_credit(self):
        for charging_w, credit in ((200, 0), (201, 1), (150, 0)):
            with self.subTest(charging_w=charging_w):
                result = calculate_grid_charge(charging(battery_power_w=-charging_w))
                self.assertEqual(result["pv_surplus_credit_w"], credit)

    def test_pv_covers_need_stops_grid_immediately_without_claiming_soc_target_reached(self):
        result = calculate_grid_charge(charging(battery_power_w=-6000,
            current_a=80, last_attempt_a=80, last_attempt_ts=999))
        self.assertEqual(result["need_a"], 0)
        self.assertEqual(result["next_a"], 0)
        self.assertTrue(result["safety"])
        self.assertTrue(result["write"])
        self.assertEqual(result["reason"], "pv_covers_charge_need")
        self.assertGreater(result["gap_kwh"], 0)

    def test_actual_total_charge_excess_authorizes_immediate_reduction_only(self):
        g = charging(battery_total_cap_a=100, battery_power_w=-5800,
            current_a=80, last_attempt_a=80, last_attempt_ts=999,
            grid_port_w=3000, grid_port_phases_w=[1000]*3)
        result = calculate_grid_charge(g)
        self.assertEqual(result["battery_charge_excess_a"], 12)
        self.assertEqual(result["cap_a"], 68)
        self.assertEqual(result["next_a"], 68)
        self.assertTrue(result["safety"])
        self.assertTrue(result["write"])
        self.assertEqual(result["reason"], "battery_charge_headroom")
        g.update(current_a=0, last_attempt_a=0)
        self.assertEqual(calculate_grid_charge(g)["next_a"], 0)
        self.assertEqual(calculate_grid_charge_increase_cap(g)["increase_cap_a"], 0)

    def test_bms_block_reason_is_not_masked_when_local_charging_covers_pace(self):
        result = calculate_grid_charge(charging(bms_cap_a=0,
            battery_power_w=-6000, current_a=80, last_attempt_a=80,
            last_attempt_ts=999))
        self.assertEqual(result["need_a"], 0)
        self.assertEqual(result["cap_a"], 0)
        self.assertEqual(result["next_a"], 0)
        self.assertTrue(result["write"])
        self.assertEqual(result["reason"], "bms_blocked")

    def test_total_overcharge_reason_is_not_masked_when_local_charging_covers_pace(self):
        result = calculate_grid_charge(charging(battery_total_cap_a=100,
            battery_power_w=-6000, current_a=80, last_attempt_a=80,
            last_attempt_ts=999))
        self.assertEqual(result["need_a"], 0)
        self.assertGreater(result["battery_charge_excess_a"], 0)
        self.assertGreater(result["cap_a"], 0)
        self.assertEqual(result["next_a"], 0)
        self.assertTrue(result["write"])
        self.assertEqual(result["reason"], "battery_charge_headroom")

    def test_aggregate_power_noise_tolerance_does_not_relax_hard_current_caps(self):
        for power, excess in ((5200, 0), (5201, .02)):
            g = charging(battery_total_cap_a=100, bms_cap_a=100,
                battery_power_w=-power, current_a=80, last_attempt_a=80,
                grid_port_w=3000, grid_port_phases_w=[1000]*3)
            result = calculate_grid_charge_cap(g)
            self.assertAlmostEqual(result["battery_charge_excess_a"], excess)
            self.assertLessEqual(result["hard_current_cap_a"], 100)
            self.assertEqual(result["cap_a"], 80 - math.ceil(excess) if excess else 100)

    def test_missing_invalid_battery_measurement_or_total_cap_fails_closed(self):
        for key in ("battery_power_w", "battery_total_cap_a"):
            for value in (None, True, "0", float("nan"), float("inf"), "missing"):
                with self.subTest(key=key, value=value):
                    g = charging(current_a=80, last_attempt_a=80, last_attempt_ts=999)
                    if value == "missing":
                        del g[key]
                    else:
                        g[key] = value
                    result = calculate_grid_charge(g)
                    self.assertFalse(result["telemetry_ok"])
                    self.assertIsNone(result["pv_surplus_credit_w"])
                    self.assertEqual(result["next_a"], 0)
                    self.assertTrue(result["safety"])
        for field, value in (("battery_power_w", -60001), ("battery_total_cap_a", -1),
                             ("battery_total_cap_a", 1001)):
            self.assertFalse(calculate_grid_charge_cap(charging(**{field: value}))["telemetry_ok"])

    def test_true_zero_total_allowance_blocks_grid_without_changing_telemetry_validity(self):
        result = calculate_grid_charge(charging(battery_total_cap_a=0,
            current_a=40, last_attempt_a=40, last_attempt_ts=999))
        self.assertTrue(result["telemetry_ok"])
        self.assertEqual(result["hard_current_cap_a"], 0)
        self.assertEqual(result["next_a"], 0)
        self.assertTrue(result["write"])

    def test_pv_never_grants_extra_grid_load_or_port_headroom(self):
        g = charging(load_w=10000, load_phases_w=[3400, 3300, 3300],
            grid_port_load_w=10000, grid_port_load_phases_w=[3400, 3300, 3300])
        before = calculate_grid_charge_cap(g)
        after = calculate_grid_charge_cap({**g, "battery_power_w": -7000})
        self.assertEqual(after["cap_a"], before["cap_a"])
        self.assertEqual(after["planning_cap_a"], before["planning_cap_a"])

    def test_below_reserve_requests_maximum_total_charge_but_pv_still_displaces_grid(self):
        for pv_battery_w, grid_need in ((0, 180), (5000, 84), (9000, 4)):
            with self.subTest(pv_battery_w=pv_battery_w):
                g = charging(soc=39, target_soc=40,
                             battery_power_w=-pv_battery_w)
                emergency = calculate_grid_charge(g)
                self.assertAlmostEqual(emergency["total_charge_pace_w"], 9000)
                self.assertEqual(emergency["need_a"], grid_need)
                self.assertAlmostEqual(emergency["net_grid_need_w"], grid_need * 50)

    def test_protected_slots_still_block_grid_with_pv_and_below_reserve(self):
        g = charging(soc=39, target_soc=69, battery_power_w=-8000)
        g.update(cheap_window=False, current_a=60, last_attempt_a=60,
                 last_attempt_ts=999)
        blocked = calculate_grid_charge(g)
        self.assertEqual(blocked["next_a"], 0)
        self.assertTrue(blocked["write"])
        self.assertEqual(blocked["reason"], "window_or_policy_blocked")

    def test_partial_pv_correction_keeps_rolling_interval_and_covering_need_does_not_latch_soc(self):
        from test_scheduled_current import snapshot as scheduled_snapshot
        from test_scheduled_current import calculate_grid_charge as scheduled_calculate, update_policy
        g = scheduled_snapshot(capacity_kwh=100, soc=50, target_soc=69,
            remaining_h=4, battery_voltage_v=50, bms_cap_a=180,
            deye_cap_a=190, actuator_cap_a=240, battery_total_cap_a=200,
            battery_power_w=-7000, grid_port_w=3500,
            grid_port_phases_w=[1200, 1200, 1100],
            current_a=80, last_attempt_a=80, last_attempt_ts=1,
            ordinary_last_possible_ts=1)
        on_boundary = scheduled_calculate(g)
        self.assertTrue(on_boundary["write"])
        self.assertEqual(on_boundary["next_a"], 35)
        # A pure proposal does not write the journal. Represent the possible
        # dispatch explicitly before checking the next ordinary opportunity.
        g.update(ordinary_last_positive_possible_ts=g["now_ts"],
                 ordinary_last_possible_ts=g["now_ts"], last_attempt_ts=g["now_ts"], last_attempt_a=35)
        g["now_ts"] += 120
        g["current_policy"]["observed_at"] = g["now_ts"]
        held = scheduled_calculate(g)
        self.assertFalse(held["write"])
        self.assertEqual(held["reason"], "scheduled_hold")
        g.update(battery_power_w=-9000, grid_port_w=0,
                 grid_port_phases_w=[0, 0, 0])
        covered = scheduled_calculate(g)
        self.assertEqual(covered["next_a"], 0)
        self.assertTrue(covered["safety"])
        self.assertEqual(covered["reason"], "pv_covers_charge_need")
        policy = update_policy(g, g["current_policy"])
        self.assertFalse(policy["stopped"])


if __name__ == "__main__":
    unittest.main()
