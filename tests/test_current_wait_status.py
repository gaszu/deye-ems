"""Read-only waiting diagnostics; no service calls or control-policy changes."""
from copy import deepcopy
from datetime import datetime, timedelta
import unittest

from test_scheduled_current import snapshot
from test_runtime import Harness, runtime


class CurrentWaitStatus(unittest.TestCase):
    def sample(self, *, elapsed=120, started=False, **changes):
        g = snapshot()
        g["now_ts"] += 420  # 22:07 proves that no wall-clock boundary is needed.
        g["initial_window_started"] = started
        g["current_policy"].update(initial_started=started, stopped=False,
            safe_since=g["now_ts"]-elapsed, observed_at=g["now_ts"])
        g.update(changes)
        return g

    def test_unspent_initial_permission_waits_for_observed_recovery(self):
        g = self.sample(elapsed=60)
        status = runtime.describe_current_wait(g)
        self.assertEqual(status["current_hold_reason"], "waiting_stable_measurements")
        self.assertEqual(status["recovery_remaining_s"], 60)
        self.assertEqual(datetime.fromisoformat(status["next_current_change_at"]).timestamp(), g["now_ts"]+60)
        g = self.sample()
        self.assertEqual(runtime.describe_current_wait(g)["current_hold_reason"], "initial_start")

    def test_spent_permission_can_resume_when_rolling_clocks_are_ready(self):
        g = self.sample(started=True)
        status = runtime.describe_current_wait(g)
        self.assertEqual(status["current_hold_reason"], "ready")
        self.assertEqual(datetime.fromisoformat(status["next_current_change_at"]).timestamp(), g["now_ts"])
        recovering = runtime.describe_current_wait(self.sample(started=True, elapsed=60))
        self.assertEqual(recovering["current_hold_reason"], "waiting_stable_measurements")
        self.assertEqual(recovering["recovery_remaining_s"], 60)

    def test_missing_recovery_cannot_invent_a_countdown(self):
        g = self.sample()
        g["current_policy"]["safe_since"] = None
        status = runtime.describe_current_wait(g)
        self.assertIsNone(status["recovery_remaining_s"])
        self.assertIsNone(status["next_current_change_at"])

    def test_readback_and_unknown_history_have_no_prediction(self):
        for change in (dict(pending_current_a=20), dict(ordinary_history_known=False)):
            status = runtime.describe_current_wait(self.sample(**change))
            self.assertEqual(status["current_hold_reason"], "waiting_readback")
            self.assertIsNone(status["next_current_change_at"])

    def test_initial_retry_respects_possible_and_not_sent_delays(self):
        g = self.sample()
        g.update(ordinary_last_possible_ts=g["now_ts"]-30, ordinary_last_not_sent_ts=g["now_ts"]-10)
        status = runtime.describe_current_wait(g)
        self.assertEqual(status["current_hold_reason"], "waiting_retry")
        self.assertEqual(datetime.fromisoformat(status["next_current_change_at"]).timestamp(), g["now_ts"]+90)

    def test_no_prediction_across_protected_tariff_deadline(self):
        g = self.sample(started=True)
        g["ordinary_last_positive_possible_ts"] = g["now_ts"]-500
        g["policy_deadline"] = datetime.fromtimestamp(g["now_ts"]+60, runtime._TZ).isoformat()
        g["current_policy"]["deadline"] = g["policy_deadline"]
        self.assertIsNone(runtime.describe_current_wait(g)["next_current_change_at"])

    def test_describing_does_not_mutate_input_or_control_decision(self):
        g = self.sample()
        original = deepcopy(g)
        before = runtime.calculate_grid_charge(g)
        runtime.describe_current_wait(g)
        self.assertEqual(g, original)
        self.assertEqual(runtime.calculate_grid_charge(g), before)

    def test_gc_tristate_requires_fresh_native_telemetry(self):
        h = Harness()
        for state, expected in (("on", True), ("off", False), ("unknown", None)):
            h.set("tou_gc_6", state, age=7200)
            g = h.co._grid_input(h.co._read_inputs(h.now), h.now, 85, False)
            self.assertIs(g["grid_charge_enabled"], expected)
        h.set("tou_gc_6", "on", attributes={"restored": True})
        self.assertIsNone(h.co._grid_input(h.co._read_inputs(h.now), h.now, 85, False)["grid_charge_enabled"])
        h.set("tou_gc_6", "on", age=-1)
        self.assertIsNone(h.co._grid_input(h.co._read_inputs(h.now), h.now, 85, False)["grid_charge_enabled"])
        h.set("tou_gc_6", "on")
        h.set("battery_power", 0, "W", age=31)
        self.assertIsNone(h.co._grid_input(h.co._read_inputs(h.now), h.now, 85, False)["grid_charge_enabled"])

    def test_controlled_measurement_issues_explain_existing_rejection(self):
        for args, reason in ((dict(age=31), "stale"), (dict(age=-1), "future"),
                             (dict(attributes={"restored": True}), "restored")):
            h = Harness()
            h.set("battery_power", 0, "W", **args)
            data = h.co._read_inputs(h.now)
            self.assertFalse(data["telemetry_valid"])
            self.assertIn(dict(source="battery_power", reason=reason), data["telemetry_issues"])
        h = Harness()
        h.set("battery_power", 0, "kW")
        self.assertIn(dict(source="battery_power", reason="wrong_unit"), h.co._read_inputs(h.now)["telemetry_issues"])
        h = Harness()
        h.set("battery_power", 0, "W", age=11)
        data = h.co._read_inputs(h.now)
        self.assertFalse(data["telemetry_valid"])
        self.assertIn(dict(source="charge_power", reason="time_skew"), data["telemetry_issues"])
        for issue in data["telemetry_issues"]:
            self.assertEqual(set(issue), {"source", "reason"})


if __name__ == "__main__":
    unittest.main()
