"""Rolling decisions, hysteresis, recovery and live runtime boundaries."""
from copy import deepcopy
import unittest

from test_runtime import Harness, SOURCES, runtime
calculate_grid_charge = runtime.calculate_grid_charge
_ordinary = calculate_grid_charge.__globals__["_ordinary"]
update_policy = runtime.update_policy
dispatch_ready = runtime.dispatch_ready


def snapshot(**changes):
    h = Harness()
    h.set("asymmetric_phase_feeding", "on")
    g = h.co._grid_input(h.co._read_inputs(h.now), h.now, 85, False)
    g.update(changes)
    return g


class ScheduledCurrent(unittest.TestCase):
    def test_direct_start_is_bounded_to_ten_amps(self):
        g = snapshot()
        result = calculate_grid_charge(g)
        self.assertTrue(result["write"])
        self.assertEqual(result["next_a"], 10)
        self.assertEqual(result["reason"], "initial_charge_start")

    def test_rolling_interval_has_no_half_hour_or_first_minute_restriction(self):
        t = snapshot()["now_ts"]
        for delta in (0, 59.99, 60, 599, 600, 1799, 1800):
            self.assertTrue(dispatch_ready(t+delta, None, None, None))
        self.assertFalse(dispatch_ready(t+599, t, None, t))
        self.assertTrue(dispatch_ready(t+600, t, None, t))
        self.assertFalse(dispatch_ready(t+1800, t+1790, None, t))
        self.assertFalse(dispatch_ready(t, t+1, None, None))

    def test_ordinary_change_does_not_wait_for_a_wall_clock_boundary(self):
        g = snapshot()
        g["now_ts"] += 600
        g["current_policy"]["observed_at"] = g["now_ts"]
        self.assertTrue(calculate_grid_charge(g)["write"])

    def test_quantized_changes_stay_within_ten_amps(self):
        g = snapshot(current_a=50, last_attempt_a=50, last_attempt_ts=1,
                     ordinary_last_possible_ts=1)
        self.assertLessEqual(abs(calculate_grid_charge(g)["next_a"]-50), 10)
        g["soc"] = 45
        result = calculate_grid_charge(g)
        self.assertTrue(result["write"])
        self.assertGreaterEqual(abs(result["next_a"]-50), 10)
        self.assertEqual(result["next_a"] % 5, 0)

    def test_rounding_never_exceeds_hardware_cap(self):
        for cap in range(1, 109):
            result = calculate_grid_charge(snapshot(bms_cap_a=cap, soc=35))
            self.assertLessEqual(result["next_a"], cap)
            if result["write"] and cap >= 5:
                self.assertEqual(result["next_a"] % 5, 0)

    def test_ordinary_five_amp_corrections_hold_the_confirmed_setting(self):
        for current, demand in ((15, 20), (20, 15), (70, 75)):
            with self.subTest(current=current, demand=demand):
                g = snapshot(current_a=current, last_attempt_a=current,
                             ordinary_last_possible_ts=1)
                result = _ordinary(g, {"need_a": demand, "cap_a": 100})
                self.assertEqual((result["next_a"], result["write"], result["reason"]),
                                 (current, False, "scheduled_deadband"))

    def test_taper_steps_down_from_an_off_grid_setting(self):
        g = snapshot(current_a=12, last_attempt_a=12,
                     ordinary_last_possible_ts=1, taper_to_zero=True)
        result = _ordinary(g, {"need_a": 0, "cap_a": 100})
        self.assertEqual((result["next_a"], result["write"], result["reason"]),
                         (5, True, "target_taper"))

    def test_material_increase_can_align_to_the_grid_within_the_ramp(self):
        g = snapshot(current_a=3, last_attempt_a=3, ordinary_last_possible_ts=1)
        result = _ordinary(g, {"need_a": 50, "cap_a": 100})
        self.assertEqual((result["next_a"], result["write"]), (10, True))

    def test_safety_bypasses_schedule_and_deadband(self):
        g = snapshot(current_a=60, last_attempt_a=60, bms_cap_a=59)
        g["now_ts"] += 120
        result = calculate_grid_charge(g)
        self.assertTrue(result["safety"])
        self.assertTrue(result["write"])
        self.assertEqual(result["next_a"], 55)
        g["telemetry_valid"] = False
        self.assertEqual(calculate_grid_charge(g)["next_a"], 0)

    def test_uncertain_command_cannot_stack_an_increase(self):
        g = snapshot(last_attempt_a=40, last_attempt_ts=1, ordinary_last_possible_ts=1)
        self.assertLessEqual(calculate_grid_charge(g)["next_a"], 40)

    def test_target_latches_until_five_pp_below_or_reserve_emergency(self):
        g = snapshot(soc=85)
        state = update_policy(g, {})
        self.assertTrue(state["stopped"])
        g.update(soc=84, current_policy=state)
        state = update_policy(g, state)
        self.assertTrue(state["stopped"])
        self.assertEqual(calculate_grid_charge({**g, "current_policy": state})["next_a"], 0)
        g["soc"] = 80
        self.assertFalse(update_policy(g, state)["stopped"])
        g.update(target_soc=40, minimum_soc_percent=40, soc=39)
        self.assertFalse(update_policy(g, state)["stopped"])

    def test_target_changes_do_not_reset_latch_near_target(self):
        g = snapshot(soc=85)
        state = update_policy(g, {})
        g["target_soc"] = 86
        self.assertTrue(update_policy(g, state)["stopped"])
        g["target_soc"] = 90
        self.assertFalse(update_policy(g, state)["stopped"])

    def test_small_topup_waits_but_final_hour_and_reserve_do_not(self):
        g = snapshot(soc=73, target_soc=75, capacity_kwh=16, minimum_soc_percent=18,
                     remaining_h=4.5, battery_power_w=0)
        result = calculate_grid_charge(g)
        self.assertEqual((result["reason"], result["next_a"], result["write"]), ("batch_wait", 0, False))
        g["remaining_h"] = 1
        result = calculate_grid_charge(g)
        self.assertTrue(result["write"])
        self.assertGreater(result["next_a"], 0)
        self.assertLessEqual(result["next_a"], result["cap_a"])
        g.update(remaining_h=4.5, minimum_soc_percent=70)
        self.assertNotEqual(calculate_grid_charge(g)["reason"], "batch_wait")

    def test_batch_never_stops_an_existing_charge_or_delays_low_cap(self):
        g = snapshot(soc=73, target_soc=75, capacity_kwh=16, minimum_soc_percent=18,
                     remaining_h=4.5, battery_power_w=0)
        self.assertEqual(calculate_grid_charge(g)["reason"], "batch_wait")
        self.assertNotEqual(calculate_grid_charge({**g, "current_a": 5})["reason"], "batch_wait")
        self.assertNotEqual(calculate_grid_charge({**g, "bms_cap_a": 1})["reason"], "batch_wait")
        failed = calculate_grid_charge({**g, "current_a": 5, "telemetry_valid": False})
        self.assertTrue(failed["safety"])
        self.assertEqual(failed["next_a"], 0)

    def test_final_hour_releases_latch_once_then_keeps_five_pp_band(self):
        g = snapshot(soc=75, target_soc=75, remaining_h=4)
        state = update_policy(g, {})
        self.assertTrue(state["stopped"])
        g.update(soc=73, remaining_h=1)
        state = update_policy(g, state)
        self.assertFalse(state["stopped"])
        g["soc"] = 75
        state = update_policy(g, state)
        g["soc"] = 74
        self.assertTrue(update_policy(g, state)["stopped"])
        g["soc"] = 70
        self.assertFalse(update_policy(g, state)["stopped"])

    def test_wait_description_rejects_malformed_deadline(self):
        g = snapshot(soc=73, target_soc=75, capacity_kwh=16, minimum_soc_percent=18,
                     remaining_h=4.5, battery_power_w=0)
        describe = runtime.describe_current_wait
        for deadline in (None, "bad", "2026-11-16T07:00:00"):
            self.assertIsNone(describe({**g, "policy_deadline": deadline})["next_current_change_at"])

    def test_current_snapshot_replaces_invalid_or_old_observation(self):
        g = snapshot()
        for state in (None, {"observed_at": "oops"}, {"version": 1, "deadline": "x", "stopped": True,
                                                   "safe_since": g["now_ts"]-500, "observed_at": "oops"}):
            updated = update_policy(g, state)
            self.assertEqual(updated["observed_at"], g["now_ts"])
        state = deepcopy(g["current_policy"])
        g["now_ts"] += 31
        self.assertEqual(update_policy(g, state)["observed_at"], g["now_ts"])


class ScheduledRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_safety_readback_keeps_current_snapshot_and_command_history(self):
        h = Harness()
        h.active()
        h.set("grid_current_number", 60, "A")
        h.set("bms_charge_current", 10, "A")
        await h.tick()
        self.assertEqual(h.current_calls(), [10])
        self.assertEqual(h.co._memory["current_policy"]["observed_at"], h.now.timestamp())

    async def test_first_start_uses_fresh_snapshot_without_timer(self):
        h = Harness()
        h.co._memory["current_policy"] = {}
        h.active()
        await h.tick()
        self.assertEqual(len(h.current_calls()), 1)
        self.assertEqual(h.current_calls()[0], 10)

    async def test_latch_survives_restart_and_disables_grid(self):
        h = Harness()
        h.active()
        h.set("grid_current_number", 60, "A")
        h.set("soc", 85, "%")
        await h.tick()
        self.assertTrue(h.store.saved["current_policy"]["stopped"])
        h.set("soc", 84, "%")
        await h.co.async_initialize()
        self.assertTrue(h.co._memory["current_policy"]["stopped"])
        self.assertIsNone(h.co._memory["current_policy"]["observed_at"])
        await h.tick()
        self.assertTrue(all(a == 0 for a in h.current_calls()))

    async def test_store_crossing_dispatch_window_cancels_request(self):
        h = Harness()
        h.active()
        h.store.on_save = lambda: h.advance(61)
        self.assertFalse(await h.co._grid_attempt(55, h.now.timestamp()))
        self.assertEqual(h.current_calls(), [])

    async def test_changed_bms_after_save_still_blocks_large_direct_start(self):
        h = Harness()
        h.active()
        h.store.on_save = lambda: h.set("bms_charge_current", 10, "A")
        self.assertFalse(await h.co._grid_attempt(55, h.now.timestamp()))
        self.assertEqual(h.current_calls(), [])

    async def test_policy_save_failure_blocks_start_but_allows_stop(self):
        h = Harness()
        h.active()
        h.co._memory["current_policy"] = {}
        h.store.fail = True
        await h.tick()
        self.assertEqual(h.current_calls(), [])
        self.assertTrue(h.co._memory["current_policy"]["stopped"])
