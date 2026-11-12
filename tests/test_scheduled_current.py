"""Half-hour decisions, hysteresis, recovery and live runtime boundaries."""
from copy import deepcopy
import unittest

from test_runtime import Harness, SOURCES, runtime
calculate_grid_charge = runtime.calculate_grid_charge
update_policy = runtime.update_policy
dispatch_ready = runtime.dispatch_ready


def snapshot(**changes):
    h = Harness()
    h.set("asymmetric_phase_feeding", "on")
    g = h.co._grid_input(h.co._read_inputs(h.now), h.now, 85, False)
    g.update(changes)
    return g


class ScheduledCurrent(unittest.TestCase):
    def test_direct_start_uses_demand_not_twenty_amp_steps(self):
        g = snapshot()
        result = calculate_grid_charge(g)
        self.assertTrue(result["write"])
        self.assertEqual(result["next_a"], 55)
        self.assertEqual(result["reason"], "scheduled_setpoint")

    def test_only_first_minute_of_each_half_hour_and_one_possible_command(self):
        t = snapshot()["now_ts"]
        for delta, ready in ((0, True), (59.99, True), (60, False), (1799, False), (1800, True)):
            self.assertEqual(dispatch_ready(t+delta, None, None), ready)
        self.assertFalse(dispatch_ready(t+10, t, None))
        self.assertFalse(dispatch_ready(t+1800, t+1790, None))
        self.assertFalse(dispatch_ready(t, t+1, None))

    def test_no_ordinary_change_outside_schedule(self):
        g = snapshot()
        g["now_ts"] += 600
        self.assertFalse(calculate_grid_charge(g)["write"])

    def test_deadband_is_ten_amps_after_quantization_and_headroom(self):
        g = snapshot(current_a=50, last_attempt_a=50, last_attempt_ts=1,
                     ordinary_last_possible_ts=1)
        self.assertEqual(calculate_grid_charge(g)["reason"], "scheduled_deadband")
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

    def test_safety_bypasses_schedule_and_deadband(self):
        g = snapshot(current_a=60, last_attempt_a=60, bms_cap_a=59)
        g["now_ts"] += 120
        result = calculate_grid_charge(g)
        self.assertTrue(result["safety"])
        self.assertTrue(result["write"])
        self.assertEqual(result["next_a"], 59)
        g["telemetry_valid"] = False
        self.assertEqual(calculate_grid_charge(g)["next_a"], 0)

    def test_uncertain_command_cannot_stack_an_increase(self):
        g = snapshot(last_attempt_a=40, last_attempt_ts=1, ordinary_last_possible_ts=1)
        self.assertLessEqual(calculate_grid_charge(g)["next_a"], 40)

    def test_target_latches_until_two_pp_below_or_reserve_emergency(self):
        g = snapshot(soc=85)
        state = update_policy(g, {})
        self.assertTrue(state["stopped"])
        g.update(soc=84, current_policy=state)
        state = update_policy(g, state)
        self.assertTrue(state["stopped"])
        self.assertEqual(calculate_grid_charge({**g, "current_policy": state})["next_a"], 0)
        g["soc"] = 83
        self.assertFalse(update_policy(g, state)["stopped"])
        g.update(target_soc=40, minimum_soc_percent=40, soc=39)
        self.assertFalse(update_policy(g, state)["stopped"])

    def test_target_changes_do_not_reset_latch_near_target(self):
        g = snapshot(soc=85)
        state = update_policy(g, {})
        g["target_soc"] = 86
        self.assertTrue(update_policy(g, state)["stopped"])
        g["target_soc"] = 87
        self.assertFalse(update_policy(g, state)["stopped"])

    def test_bad_policy_and_observation_gap_restart_recovery(self):
        g = snapshot()
        for state in (None, {"observed_at": "oops"}, {"version": 1, "deadline": "x", "stopped": True,
                                                   "safe_since": g["now_ts"]-500, "observed_at": "oops"}):
            updated = update_policy(g, state)
            self.assertEqual(updated["safe_since"], g["now_ts"])
        state = deepcopy(g["current_policy"])
        g["now_ts"] += 31
        self.assertEqual(update_policy(g, state)["safe_since"], g["now_ts"])


class ScheduledRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_safety_readback_in_same_tick_restarts_stability_timer(self):
        h = Harness()
        h.active()
        h.set("grid_current_number", 60, "A")
        h.set("bms_charge_current", 10, "A")
        await h.tick()
        self.assertEqual(h.current_calls(), [10])
        self.assertEqual(h.co._memory["current_policy"]["safe_since"], h.now.timestamp())

    async def test_first_start_observes_two_minutes_without_waiting_for_next_boundary(self):
        h = Harness()
        h.co._memory["current_policy"] = {}
        h.active()
        await h.tick()
        self.assertEqual(h.current_calls(), [])
        for _ in range(11):
            h.advance(10)
            await h.tick()
        self.assertEqual(h.current_calls(), [])
        h.advance(10)
        await h.tick()
        self.assertEqual(len(h.current_calls()), 1)
        self.assertGreater(h.current_calls()[0], 20)

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
        self.assertIsNone(h.co._memory["current_policy"]["safe_since"])
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
