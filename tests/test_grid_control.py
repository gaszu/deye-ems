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
calculate_grid_charge_increase_cap = module.calculate_grid_charge_increase_cap


def snapshot(**changes):
    data = dict(now_ts=1000., winter=True, cheap_window=True,
                emergency_allowed=False, soc_valid=True, soc=50., target_soc=75.,
                remaining_h=4., bms_cap_a=108., telemetry_valid=True,
                deye_cap_a=108., actuator_cap_a=240.,
                load_w=2000., load_phases_w=[1000., 600., 400.],
                grid_w=2000., grid_phases_w=[1000., 600., 400.],
                battery_voltage_v=54., current_a=0.,
                last_attempt_ts=400., last_attempt_a=0.,
                ordinary_history_known=True, ordinary_last_possible_ts=400.,
                ordinary_last_not_sent_ts=None, grid_charge_active=True,
                pending_current_a=None)
    data.update(changes)
    for native, source in (("grid_port_w", "grid_w"),
                           ("grid_port_phases_w", "grid_phases_w"),
                           ("grid_port_load_w", "load_w"),
                           ("grid_port_load_phases_w", "load_phases_w")):
        data.setdefault(native, copy.deepcopy(data[source]))
    data.setdefault("inverter_grid_import_limit_w", 12000.)
    data.setdefault("inverter_grid_phase_limit_w", 5000.)
    if "ordinary_last_possible_ts" not in changes:
        data["ordinary_last_possible_ts"] = data["last_attempt_ts"]
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
            self.assertEqual(result["next_a"], 20)
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
        self.assertEqual(below["next_a"], 20)
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

    def test_house_load_step_bypasses_normal_ten_minute_wait(self):
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
            result = calculate_grid_charge(snapshot(**fields, ordinary_last_possible_ts=400))
            self.assertFalse(result["write"])
            self.assertEqual(result["next_a"], 0)
            self.assertEqual(result["reason"], "ledger_missing_or_future")

    def test_unconfirmed_write_retries_same_proposal_without_escalation(self):
        waiting = snapshot(current_a=27, last_attempt_a=37, last_attempt_ts=995)
        self.assertFalse(calculate_grid_charge(waiting)["write"])
        waiting["now_ts"] = 1594
        self.assertFalse(calculate_grid_charge(waiting)["write"])
        waiting["now_ts"] = 1595
        retry = calculate_grid_charge(waiting)
        self.assertTrue(retry["write"])
        self.assertEqual(retry["next_a"], 37)
        self.assertEqual(retry["reason"], "retry_unconfirmed")

    def test_old_high_proposal_cannot_jump_up_after_manual_zero(self):
        g = snapshot(current_a=0, last_attempt_a=108, last_attempt_ts=989,
                     remaining_h=.1)
        early = calculate_grid_charge(g)
        self.assertFalse(early["write"])
        g["now_ts"] = 1588
        self.assertFalse(calculate_grid_charge(g)["write"])
        g["now_ts"] = 1589
        rebased = calculate_grid_charge(g)
        self.assertTrue(rebased["write"])
        self.assertEqual(rebased["next_a"], 20)

    def test_identical_failed_safety_write_has_ten_second_retry_gate(self):
        g = snapshot(current_a=40, last_attempt_a=0, last_attempt_ts=995,
                     load_w=12000, load_phases_w=[5000, 4000, 3000])
        first = calculate_grid_charge(g)
        self.assertEqual(first["next_a"], 0)
        self.assertFalse(first["write"])
        g["now_ts"] = 1005
        self.assertTrue(calculate_grid_charge(g)["write"])

    def test_small_need_variations_and_ordinary_downward_changes_are_bounded(self):
        # 74->75% in 20 min needs 39 A at54V and95% storage efficiency.
        g = snapshot(soc=74, target_soc=75, remaining_h=1/3,
                     current_a=40, last_attempt_a=40)
        result = calculate_grid_charge(g)
        self.assertEqual(result["need_a"], 39)
        self.assertFalse(result["write"])
        result = calculate_grid_charge(snapshot(current_a=60, last_attempt_a=60,
                                                soc=74, remaining_h=1))
        self.assertEqual(result["next_a"], 40)
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
                    self.assertLessEqual(proposed-last, 20)
                    self.assertGreaterEqual(proposed-last, 5)
                    self.assertGreaterEqual(g["now_ts"]-g["ordinary_last_possible_ts"], 600)
                g.update(last_attempt_ts=g["now_ts"], last_attempt_a=proposed,
                         ordinary_last_possible_ts=g["now_ts"])
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

    def test_first_dispatch_is_immediate_only_with_a_validated_empty_history(self):
        first = snapshot(last_attempt_ts=None, last_attempt_a=None,
                         ordinary_last_possible_ts=None)
        decision = calculate_grid_charge(first)
        self.assertTrue(decision["write"])
        self.assertEqual(decision["next_a"], 20)
        for change in ({"ordinary_history_known": False},
                       {"ordinary_last_possible_ts": 999},
                       {"last_attempt_a": 20}, {"last_attempt_ts": 999}):
            with self.subTest(change=change):
                self.assertFalse(calculate_grid_charge({**first, **change})["write"])

    def test_ordinary_interval_boundary_is_six_hundred_seconds(self):
        for current, expected in ((20, 40), (60, 40)):
            g = snapshot(current_a=current, last_attempt_a=current,
                         last_attempt_ts=995, soc=74 if current == 60 else 50,
                         remaining_h=1 if current == 60 else 4)
            for at in (1000, 1025, 1594.999):
                with self.subTest(current=current, at=at):
                    self.assertFalse(calculate_grid_charge({**g, "now_ts": at})["write"])
            ready = calculate_grid_charge({**g, "now_ts": 1595})
            self.assertTrue(ready["write"])
            self.assertEqual(ready["next_a"], expected)

    def test_acknowledgement_time_does_not_replace_dispatch_clock(self):
        # A late register report does not restart a matured dispatch interval.
        g = snapshot(current_a=20, last_attempt_a=20, last_attempt_ts=995,
                     ordinary_last_possible_ts=400)
        self.assertTrue(calculate_grid_charge(g)["write"])
        # Conversely an old ACK cannot bypass a recently sent safety setting.
        g.update(last_attempt_ts=400, ordinary_last_possible_ts=995)
        self.assertFalse(calculate_grid_charge(g)["write"])

    def test_five_amp_deadband_applies_in_both_directions(self):
        # This deadline needs 13 A. Test both sides of the actual 5 A threshold.
        for current, should_write in ((8.01, False), (8, True),
                                      (17.99, False), (18, True)):
            with self.subTest(current=current):
                result = calculate_grid_charge(snapshot(
                    soc=74, remaining_h=1, current_a=current, last_attempt_a=current))
                self.assertEqual(result["need_a"], 13)
                self.assertEqual(result["write"], should_write)
                if should_write:
                    self.assertEqual(result["next_a"], 13)

    def test_grid_clipping_to_less_than_five_amps_does_not_trigger_a_write(self):
        g = snapshot(current_a=20, last_attempt_a=20, grid_w=6500,
                     grid_phases_w=[4570, 1000, 930])
        result = calculate_grid_charge(g)
        self.assertFalse(result["write"])
        self.assertEqual(result["grid_step_headroom_a"], 3)
        self.assertEqual(result["reason"], "grid_step_headroom")
        g["grid_phases_w"] = [4450, 1100, 950]
        g["grid_port_phases_w"] = list(g["grid_phases_w"])
        result = calculate_grid_charge(g)
        self.assertTrue(result["write"])
        self.assertEqual(result["next_a"], 25)

    def test_safe_start_below_five_amps_is_allowed_without_bypassing_the_clock(self):
        # A small BMS/GRID budget must not disable charging forever at zero.
        cases = [dict(bms_cap_a=3),
                 dict(grid_w=6500, grid_phases_w=[4570, 1000, 930])]
        for fields in cases:
            with self.subTest(fields=fields):
                g = snapshot(current_a=0, last_attempt_a=0, soc=39, **fields)
                result = calculate_grid_charge(g)
                self.assertTrue(result["write"])
                self.assertEqual(result["next_a"], 3)
                self.assertFalse(result["safety"])
                g["ordinary_last_possible_ts"] = 999
                self.assertFalse(calculate_grid_charge(g)["write"])
                g.update(now_ts=1599)
                self.assertTrue(calculate_grid_charge(g)["write"])

    def test_total_actual_grid_budget_bounds_only_the_additional_import(self):
        g = snapshot(current_a=42, last_attempt_a=42, grid_charge_balanced=True,
                     grid_w=11200, grid_phases_w=[3800, 3700, 3700])
        bound = calculate_grid_charge_increase_cap(g)
        result = calculate_grid_charge(g)
        self.assertEqual(bound["grid_step_headroom_a"], 5)
        self.assertEqual(bound["increase_cap_a"], 47)
        self.assertEqual(result["next_a"], 47)
        added_ac = (result["next_a"] - g["current_a"]) * 54 / .9
        self.assertLessEqual(g["grid_w"] + added_ac, 11500)
        self.assertLessEqual(max(g["grid_phases_w"]) + added_ac / 3, 4750)

    def test_balanced_phase_increment_is_distributed_and_fallback_is_conservative(self):
        g = snapshot(current_a=20, last_attempt_a=20, grid_w=9600,
                     grid_phases_w=[4600, 2500, 2500])
        fallback = calculate_grid_charge(g)
        balanced = calculate_grid_charge({**g, "grid_charge_balanced": True})
        self.assertFalse(fallback["write"])
        self.assertEqual(fallback["grid_step_headroom_a"], 2)
        self.assertTrue(balanced["write"])
        self.assertEqual(balanced["next_a"], 27)
        self.assertEqual(balanced["grid_step_headroom_a"], 7)

    def test_actual_grid_uses_the_larger_total_sensor_or_phase_sum(self):
        for grid, phases in ((9000, [3760, 3760, 3760]),
                             (11280, [3000, 3000, 3000])):
            with self.subTest(grid=grid, phases=phases):
                bound = calculate_grid_charge_increase_cap(snapshot(
                    current_a=42, grid_charge_balanced=True,
                    grid_w=grid, grid_phases_w=phases))
                self.assertEqual(bound["grid_step_headroom_a"], 3)
                self.assertEqual(bound["increase_cap_a"], 45)

    def test_export_and_register_setting_do_not_relax_full_load_caps(self):
        for current in (0, 42, 108):
            bound = calculate_grid_charge_increase_cap(snapshot(
                current_a=current, load_w=5000, load_phases_w=[4200, 400, 400],
                grid_w=-8000, grid_phases_w=[-3000, -3000, -2000]))
            self.assertEqual(bound["increase_cap_a"], 9)

    def test_inactive_grid_charge_recovers_a_register_that_would_not_fit_when_enabled(self):
        g = snapshot(current_a=42, last_attempt_a=42, last_attempt_ts=999,
                     grid_charge_active=False, grid_w=6000,
                     grid_phases_w=[4270, 865, 865])
        result = calculate_grid_charge(g)
        self.assertEqual(calculate_grid_charge_cap(g)["cap_a"], 62)
        self.assertTrue(result["safety"])
        self.assertTrue(result["write"])
        self.assertEqual(result["next_a"], 8)
        # A later ACK of 8 A fits the separate full-request GC turn-on guard.
        g.update(current_a=8, last_attempt_a=8)
        self.assertEqual(calculate_grid_charge(g)["next_a"], 8)
        self.assertFalse(calculate_grid_charge(g)["write"])
        bound = calculate_grid_charge_increase_cap({**g, "current_a": 0})
        self.assertEqual(bound["increase_cap_a"], 8)
        for inactive in (None, "on", 1):
            g.update(current_a=42, last_attempt_a=42, grid_charge_active=inactive)
            self.assertEqual(calculate_grid_charge(g)["next_a"], 8)

    def test_possible_unsafe_pending_setting_is_cancelled_without_an_increase(self):
        for current, pending, bms in ((42, 62, 50), (0, 108, 100)):
            with self.subTest(current=current):
                g = snapshot(current_a=current, last_attempt_a=pending,
                             last_attempt_ts=999, pending_current_a=pending,
                             bms_cap_a=bms, grid_charge_balanced=True,
                             load_w=1000, load_phases_w=[400, 300, 300],
                             grid_w=1000, grid_phases_w=[400, 300, 300])
                for safety_only in (False, True):
                    result = calculate_grid_charge({**g, "safety_only": safety_only})
                    self.assertTrue(result["safety"])
                    self.assertTrue(result["write"])
                    self.assertEqual(result["next_a"], current)
                # The same certainly not-sent value creates no latent hazard.
                g.update(pending_current_a=None, ordinary_last_not_sent_ts=999)
                result = calculate_grid_charge(g)
                self.assertFalse(result["write"])
                self.assertFalse(result["safety"])

    def test_pending_setting_is_cancelled_when_the_target_is_reached_even_at_zero_readback(self):
        result = calculate_grid_charge(snapshot(
            soc=75, current_a=0, last_attempt_a=20, last_attempt_ts=999,
            pending_current_a=20))
        self.assertTrue(result["write"])
        self.assertTrue(result["safety"])
        self.assertEqual(result["next_a"], 0)

    def test_invalid_pending_metadata_fails_closed(self):
        for pending in (True, -1, 1001, float("nan"), "42"):
            with self.subTest(pending=pending):
                result = calculate_grid_charge(snapshot(
                    current_a=42, last_attempt_a=42, pending_current_a=pending))
                self.assertTrue(result["safety"])
                self.assertTrue(result["write"])
                self.assertEqual(result["next_a"], 0)

    def test_certainly_not_sent_retry_uses_sixty_seconds_not_six_hundred(self):
        g = snapshot(current_a=20, last_attempt_a=40, last_attempt_ts=995,
                     ordinary_last_possible_ts=400, ordinary_last_not_sent_ts=995)
        self.assertFalse(calculate_grid_charge({**g, "now_ts": 1054.999})["write"])
        result = calculate_grid_charge({**g, "now_ts": 1055})
        self.assertTrue(result["write"])
        self.assertEqual(result["next_a"], 40)
        # A not-sent attempt never erases a preceding real dispatch window.
        g["ordinary_last_possible_ts"] = 900
        self.assertFalse(calculate_grid_charge({**g, "now_ts": 1055})["write"])
        self.assertTrue(calculate_grid_charge({**g, "now_ts": 1500})["write"])

    def test_invalid_or_missing_dispatch_history_blocks_ordinary_but_not_safety(self):
        cases = [dict(ordinary_history_known=False), dict(ordinary_history_known=1),
                 dict(ordinary_last_possible_ts=float("nan")),
                 dict(ordinary_last_possible_ts=1001), dict(ordinary_last_possible_ts=-1),
                 dict(ordinary_last_not_sent_ts=True), dict(ordinary_last_not_sent_ts="900")]
        missing = snapshot()
        missing.pop("ordinary_last_possible_ts")
        self.assertFalse(calculate_grid_charge(missing)["write"])
        for fields in cases:
            with self.subTest(fields=fields):
                g = snapshot(current_a=50, last_attempt_a=50, **fields)
                self.assertFalse(calculate_grid_charge(g)["write"])
                reduction = calculate_grid_charge({**g, "bms_cap_a": 49})
                self.assertTrue(reduction["safety"])
                self.assertTrue(reduction["write"])
                self.assertEqual(reduction["next_a"], 49)

    def test_one_amp_safety_reduction_bypasses_both_dispatch_backoffs(self):
        result = calculate_grid_charge(snapshot(
            current_a=50, last_attempt_a=50, last_attempt_ts=999,
            ordinary_last_not_sent_ts=999, bms_cap_a=49))
        self.assertTrue(result["write"])
        self.assertTrue(result["safety"])
        self.assertEqual(result["next_a"], 49)

    def test_fractional_readback_does_not_expand_the_maximum_ordinary_step(self):
        g = snapshot(soc=74, remaining_h=1, current_a=60.9, last_attempt_a=60.9)
        result = calculate_grid_charge(g)
        self.assertTrue(result["write"])
        self.assertEqual(result["next_a"], 41)
        self.assertLessEqual(g["current_a"] - result["next_a"], 20)


if __name__ == "__main__":
    unittest.main()
