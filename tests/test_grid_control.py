"""Synthetic load-step, acknowledgement and deadline tests for grid charging.

These prove controller decisions, not physical inverter reaction time.  The
simulation deliberately changes LOAD faster than a normal upward ramp.
"""
import copy
import json
import math
from pathlib import Path
import random
import sys
import unittest

# Import the pure module directly: HA is unnecessary for offline tests, and
# importing the component package itself would execute its HA entry point.
import importlib.util
MODULE_PATH = Path(__file__).resolve().parents[1] / "custom_components/deye_ems/grid_control.py"
spec = importlib.util.spec_from_file_location("deye_ems_pure_grid_control", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
calculate_grid_charge = module.calculate_grid_charge
calculate_grid_charge_cap = module.calculate_grid_charge_cap


def snapshot(**changes):
    data = dict(now_ts=1000., winter=True, cheap_window=True,
                emergency_allowed=False, soc_valid=True, soc=50., target_soc=75.,
                remaining_h=4., bms_cap_a=108., telemetry_valid=True,
                load_w=2000., load_phases_w=[1000., 600., 400.],
                grid_w=2000., grid_phases_w=[1000., 600., 400.],
                battery_voltage_v=54., current_a=0.,
                last_attempt_ts=900., last_attempt_a=0.)
    data.update(changes)
    return data


class GridChargeScenarios(unittest.TestCase):
    def test_confirmed_balanced_grid_does_not_charge_the_worst_load_phase(self):
        g = snapshot(load_w=5500, load_phases_w=[500, 4500, 500],
                     grid_w=6000, grid_phases_w=[2000, 2000, 2000])
        conservative = calculate_grid_charge_cap(g)
        balanced = calculate_grid_charge_cap({**g, "grid_charge_balanced": True})
        self.assertEqual(conservative["planning_cap_a"], 4)
        self.assertEqual(balanced["planning_cap_a"], 100)
        self.assertEqual(balanced["cap_a"], 100)
        self.assertTrue(balanced["grid_within_limits"])
        self.assertEqual(balanced["phase_model"], "balanced")
        for flag in (None, False, 1, "on"):
            self.assertEqual(calculate_grid_charge_cap({**g, "grid_charge_balanced": flag})["cap_a"],
                             conservative["cap_a"])

    def test_balanced_phase_excess_is_converted_to_total_three_phase_correction(self):
        g = snapshot(current_a=50, load_w=1500, load_phases_w=[500, 500, 500],
                     grid_w=8000, grid_phases_w=[4800, 1600, 1600])
        balanced = calculate_grid_charge_cap({**g, "grid_charge_balanced": True})
        conservative = calculate_grid_charge_cap(g)
        self.assertEqual(balanced["grid_excess_w"], 150)
        self.assertEqual(conservative["grid_excess_w"], 50)
        self.assertEqual(balanced["feedback_cap_a"], 47)
        self.assertEqual(conservative["feedback_cap_a"], 49)
        self.assertFalse(balanced["grid_within_limits"])
        self.assertEqual(balanced["reason"], "grid_headroom")

    def test_balanced_total_excess_is_not_multiplied_by_three(self):
        g = snapshot(current_a=50, grid_w=11700, grid_phases_w=[3900, 3900, 3900],
                     grid_charge_balanced=True)
        result = calculate_grid_charge_cap(g)
        self.assertEqual(result["grid_excess_w"], 200)
        self.assertEqual(result["feedback_cap_a"], 46)
        self.assertFalse(result["grid_within_limits"])

    def test_current_register_cannot_create_extra_balanced_load_headroom(self):
        common = snapshot(grid_charge_balanced=True, grid_w=3000, grid_phases_w=[1000]*3)
        low = calculate_grid_charge_cap({**common, "current_a": 0})
        high = calculate_grid_charge_cap({**common, "current_a": 108})
        self.assertEqual(low["planning_cap_a"], high["planning_cap_a"])
        self.assertEqual(low["cap_a"], high["cap_a"])

    def test_converter_rating_is_separate_from_import_and_from_house_load(self):
        common = snapshot(load_w=1800, load_phases_w=[600]*3,
                          conversion_total_limit_w=4000, conversion_phase_limit_w=1500)
        balanced = calculate_grid_charge_cap({**common, "grid_charge_balanced": True})
        conservative = calculate_grid_charge_cap(common)
        self.assertEqual(balanced["converter_cap_a"], 66)
        self.assertEqual(conservative["converter_cap_a"], 25)
        self.assertEqual(balanced["cap_a"], 66)
        self.assertEqual(balanced["reason"], "converter_cap")
        self.assertEqual(balanced["planning_cap_a"], 108)

    def test_start_and_low_soc_emergency_do_not_jump_to_full_current(self):
        for g in (snapshot(), snapshot(soc=38., remaining_h=.5),
                  snapshot(winter=False, emergency_allowed=True)):
            result = calculate_grid_charge(g)
            self.assertTrue(result["write"])
            self.assertEqual(result["next_a"], 2)
            self.assertLessEqual(result["next_a"], result["cap_a"])

    def test_only_cheap_windows_and_summer_emergency_allow_grid(self):
        for g in (snapshot(cheap_window=False), snapshot(winter=False),
                  snapshot(soc_valid=False), snapshot(remaining_h=0)):
            g.update(current_a=28, last_attempt_a=28)
            result = calculate_grid_charge(g)
            self.assertTrue(result["write"])
            self.assertEqual(result["next_a"], 0)

    def test_configured_fifty_percent_floor_drives_emergency_and_target_validation(self):
        g = snapshot(minimum_soc_percent=50, winter=False, emergency_allowed=False,
                     soc=49, target_soc=50, current_a=0, last_attempt_a=0)
        below = calculate_grid_charge(g)
        self.assertTrue(below["write"])
        self.assertEqual(below["next_a"], 2)
        self.assertEqual(below["need_a"], below["cap_a"])
        g.update(soc=50, current_a=28, last_attempt_a=28)
        at_floor = calculate_grid_charge(g)
        self.assertEqual(at_floor["next_a"], 0)
        self.assertTrue(at_floor["write"])
        g.update(soc=49, winter=True, target_soc=45)
        wrong_target = calculate_grid_charge(g)
        self.assertEqual(wrong_target["next_a"], 0)
        self.assertEqual(wrong_target["reason"], "window_or_policy_blocked")

    def test_configured_floor_cannot_relax_below_forty_or_exceed_ninety(self):
        for minimum in (39, 91, None, "50", float("nan")):
            result = calculate_grid_charge(snapshot(minimum_soc_percent=minimum,
                                                   current_a=28, last_attempt_a=28))
            self.assertEqual(result["next_a"], 0)
            self.assertTrue(result["write"])

    def test_reached_target_stops_grid_without_another_long_ramp(self):
        result = calculate_grid_charge(snapshot(soc=75, current_a=80,
                                              last_attempt_a=80, last_attempt_ts=999))
        self.assertEqual(result["next_a"], 0)
        self.assertTrue(result["write"])
        self.assertEqual(result["reason"], "target_reached")

    def test_house_load_step_bypasses_normal_thirty_second_wait(self):
        g = snapshot(current_a=60., last_attempt_a=60., last_attempt_ts=999.,
                     load_w=10000., load_phases_w=[4500., 3000., 2500.],
                     grid_w=13000., grid_phases_w=[5500., 4000., 3500.])
        result = calculate_grid_charge(g)
        self.assertTrue(result["safety"])
        self.assertTrue(result["write"])
        self.assertLessEqual(result["next_a"], 4)
        self.assertLess(result["next_a"], 60 - 5)

    def test_single_phase_excess_limits_even_when_total_is_low(self):
        result = calculate_grid_charge(snapshot(
            current_a=50, last_attempt_a=50, load_w=5200,
            load_phases_w=[4800, 200, 200], grid_w=7000,
            grid_phases_w=[5200, 900, 900]))
        self.assertEqual(result["cap_a"], 0)
        self.assertEqual(result["next_a"], 0)
        self.assertTrue(result["write"])

    def test_bms_and_voltage_are_real_limits_independent_of_deadline(self):
        g = snapshot(soc=39, remaining_h=.1, current_a=50, last_attempt_a=50,
                     bms_cap_a=17)
        result = calculate_grid_charge(g)
        self.assertEqual(result["cap_a"], 17)
        self.assertEqual(result["next_a"], 17)
        low_v = calculate_grid_charge_cap(snapshot(battery_voltage_v=40))
        high_v = calculate_grid_charge_cap(snapshot(battery_voltage_v=65))
        self.assertLess(high_v["cap_a"], low_v["cap_a"])

    def test_bad_or_stale_measurement_fails_closed(self):
        cases = [dict(telemetry_valid=False), dict(grid_w=None),
                 dict(grid_w=float("nan")), dict(battery_voltage_v=39.9),
                 dict(load_phases_w=[100, 200]), dict(load_phases_w="123"),
                 dict(grid_phases_w=[0, "unknown", 0]), dict(grid_w="5000"),
                 dict(current_a="unavailable")]
        for case in cases:
            with self.subTest(case=case):
                g = snapshot(current_a=50, last_attempt_a=50, **case) if "current_a" not in case else snapshot(last_attempt_a=50, **case)
                result = calculate_grid_charge(g)
                self.assertEqual(result["cap_a"], 0)
                self.assertEqual(result["next_a"], 0)
                self.assertFalse(result["telemetry_ok"])

    def test_export_is_valid_but_does_not_inflate_load_budget(self):
        baseline = calculate_grid_charge_cap(snapshot())
        exporting = calculate_grid_charge_cap(snapshot(grid_w=-8000,
                                             grid_phases_w=[-3000, -3000, -2000]))
        self.assertTrue(exporting["telemetry_ok"])
        self.assertEqual(exporting["cap_a"], baseline["cap_a"])

    def test_outside_load_uses_total_budget_once_and_phase_budget_conservatively(self):
        # Sum has 3.3 kW headroom, phase has 4.4 kW before the 1 kW
        # additional load. Total, not a tripled additional load, binds at38A.
        g = snapshot(total_limit_w=5000, load_w=1200,
                     load_phases_w=[400, 400, 400], outside_load_w=1000)
        result = calculate_grid_charge_cap(g)
        self.assertEqual(result["cap_a"], 38)
        # A single heavily loaded native phase binds independently: the full
        # additional 1 kW is reserved on that phase without guessing balancing.
        g.update(total_limit_w=12000, load_w=4500,
                 load_phases_w=[3500, 500, 500])
        self.assertEqual(calculate_grid_charge_cap(g)["cap_a"], 4)

    def test_unknown_or_negative_outside_load_fails_closed(self):
        for outside in (None, -1, float("nan"), "500"):
            result = calculate_grid_charge(snapshot(outside_load_w=outside,
                                                   current_a=20, last_attempt_a=20))
            self.assertEqual(result["next_a"], 0)
            self.assertFalse(result["telemetry_ok"])

    def test_missing_and_future_ledgers_never_grant_a_new_increase(self):
        for fields in (dict(last_attempt_ts=None), dict(last_attempt_ts=1001),
                       dict(last_attempt_a=None)):
            result = calculate_grid_charge(snapshot(**fields))
            self.assertFalse(result["write"])
            self.assertEqual(result["next_a"], 0)
            self.assertEqual(result["reason"], "ledger_missing_or_future")

    def test_unconfirmed_write_retries_same_proposal_without_escalation(self):
        waiting = snapshot(current_a=27, last_attempt_a=29, last_attempt_ts=995)
        self.assertFalse(calculate_grid_charge(waiting)["write"])
        waiting["now_ts"] = 1006
        retry = calculate_grid_charge(waiting)
        self.assertTrue(retry["write"])
        self.assertEqual(retry["next_a"], 29)
        self.assertEqual(retry["reason"], "retry_unconfirmed")

    def test_old_high_proposal_cannot_jump_up_after_manual_zero(self):
        g = snapshot(current_a=0, last_attempt_a=108, last_attempt_ts=989,
                     remaining_h=.1)
        early = calculate_grid_charge(g)
        self.assertFalse(early["write"])
        self.assertEqual(early["next_a"], 2)
        g["now_ts"] = 1020
        rebased = calculate_grid_charge(g)
        self.assertTrue(rebased["write"])
        self.assertEqual(rebased["next_a"], 2)

    def test_identical_failed_safety_write_has_ten_second_retry_gate(self):
        g = snapshot(current_a=40, last_attempt_a=0, last_attempt_ts=995,
                     load_w=12000, load_phases_w=[5000, 4000, 3000])
        first = calculate_grid_charge(g)
        self.assertEqual(first["next_a"], 0)
        self.assertFalse(first["write"])
        g["now_ts"] = 1005
        self.assertTrue(calculate_grid_charge(g)["write"])

    def test_small_need_variations_and_ordinary_downward_changes_are_bounded(self):
        # 74->75% in 20 min needs 41 A; a 40 A setting is within the deadband.
        g = snapshot(soc=74, target_soc=75, remaining_h=1/3,
                     current_a=40, last_attempt_a=40)
        result = calculate_grid_charge(g)
        self.assertEqual(result["need_a"], 41)
        self.assertFalse(result["write"])
        result = calculate_grid_charge(snapshot(current_a=60, last_attempt_a=60,
                                                soc=74, remaining_h=1))
        self.assertEqual(result["next_a"], 55)
        self.assertTrue(result["write"])

    def test_unreachable_target_reports_current_constraint_without_overriding_it(self):
        result = calculate_grid_charge(snapshot(soc=40, target_soc=95, remaining_h=.2,
                                                bms_cap_a=10))
        self.assertTrue(result["unreachable"])
        self.assertGreater(result["need_a"], result["cap_a"])
        self.assertLessEqual(result["next_a"], 10)
        self.assertLess(result["projected_soc"], 95)

    def test_pre_cache_safety_has_no_target_dependency_and_never_increases(self):
        g = snapshot(safety_only=True, soc_valid=False, target_soc=None,
                     remaining_h=0, current_a=40, last_attempt_a=40)
        r = calculate_grid_charge(g)
        self.assertFalse(r["write"])
        self.assertEqual(r["next_a"], 40)
        g.update(load_phases_w=[5100, 0, 0], load_w=5100)
        r = calculate_grid_charge(g)
        self.assertEqual(r["next_a"], 0)
        self.assertTrue(r["write"])

    def test_load_step_simulation_preserves_budgets_after_each_control_response(self):
        g = snapshot(soc=40, target_soc=95, remaining_h=8)
        last = 0
        for seconds in range(0, 3600, 6):
            phase_load = [1000, 1000, 1000] if seconds < 900 or seconds >= 1800 else [4400, 3500, 2500]
            per_a = g["battery_voltage_v"] / .9
            # Deliberately put all incremental charger power on the most
            # loaded phase: the controller does not rely on phase balancing.
            phase_grid = list(phase_load)
            phase_grid[0] += last * per_a
            g.update(now_ts=1000+seconds, load_w=sum(phase_load),
                     load_phases_w=phase_load, grid_w=sum(phase_grid),
                     grid_phases_w=phase_grid, current_a=last)
            decision = calculate_grid_charge(g)
            if decision["write"]:
                proposed = decision["next_a"]
                if proposed > last:
                    self.assertLessEqual(proposed-last, 2)
                    self.assertGreaterEqual(g["now_ts"]-g["last_attempt_ts"], 30)
                g.update(last_attempt_ts=g["now_ts"], last_attempt_a=proposed)
                last = proposed  # successful actuator/readback in this case
            after = list(phase_load)
            after[0] += last * per_a
            self.assertLessEqual(sum(after), 12000)
            self.assertLessEqual(max(after), 5000)

    def test_randomized_decisions_never_exceed_physical_or_load_caps(self):
        rng = random.Random(120005000)
        for _ in range(600):
            phases = [rng.uniform(0, 6000) for _ in range(3)]
            g = snapshot(load_w=sum(phases), load_phases_w=phases,
                         current_a=rng.randrange(109), bms_cap_a=rng.randrange(109),
                         battery_voltage_v=rng.uniform(40, 65), soc=rng.uniform(30, 95))
            g["last_attempt_a"] = g["current_a"]
            result = calculate_grid_charge(g)
            self.assertGreaterEqual(result["cap_a"], 0)
            self.assertLessEqual(result["cap_a"], min(g["bms_cap_a"], 108))
            if result["write"]:
                self.assertLessEqual(result["next_a"], result["cap_a"])
                self.assertGreaterEqual(result["next_a"], 0)


    def test_measured_grid_excess_can_reduce_below_the_load_only_budget(self):
        baseline = calculate_grid_charge_cap(snapshot(current_a=70, last_attempt_a=70))
        feedback = calculate_grid_charge(snapshot(
            current_a=70, last_attempt_a=70, last_attempt_ts=999,
            grid_w=12600, grid_phases_w=[5100, 4000, 3500]))
        self.assertLess(feedback["cap_a"], baseline["cap_a"])
        self.assertEqual(feedback["reason"], "grid_headroom")
        self.assertTrue(feedback["write"])
        self.assertTrue(feedback["safety"])
        self.assertLess(feedback["next_a"], 70)


if __name__ == "__main__":
    unittest.main()
