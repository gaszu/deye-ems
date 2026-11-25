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

    def test_unspent_initial_permission_uses_valid_current_snapshot(self):
        g = self.sample(elapsed=60)
        status = runtime.describe_current_wait(g)
        self.assertEqual(status["current_hold_reason"], "initial_start")
        self.assertNotIn("recovery_remaining_s", status)
        self.assertEqual(datetime.fromisoformat(status["next_current_change_at"]).timestamp(), g["now_ts"])
        g = self.sample()
        self.assertEqual(runtime.describe_current_wait(g)["current_hold_reason"], "initial_start")

    def test_spent_permission_can_resume_when_rolling_clocks_are_ready(self):
        g = self.sample(started=True)
        status = runtime.describe_current_wait(g)
        self.assertEqual(status["current_hold_reason"], "ready")
        self.assertEqual(datetime.fromisoformat(status["next_current_change_at"]).timestamp(), g["now_ts"])
        recovering = runtime.describe_current_wait(self.sample(started=True, elapsed=60))
        self.assertEqual(recovering["current_hold_reason"], "ready")
        self.assertNotIn("recovery_remaining_s", recovering)

    def test_missing_recovery_cannot_invent_a_countdown(self):
        g = self.sample()
        g["current_policy"]["observed_at"] = None
        status = runtime.describe_current_wait(g)
        self.assertNotIn("recovery_remaining_s", status)
        self.assertIsNone(status["next_current_change_at"])

    def test_connection_phase_headroom_explains_pause_with_enabled_switch(self):
        g = self.sample(grid_w=5900, grid_phases_w=[4800, 600, 500],
                        grid_charge_enabled=True, grid_charge_active=True,
                        battery_power_w=-42)
        g["current_policy"]["observed_at"] = None
        status = runtime.describe_current_wait(g)
        self.assertEqual(status["current_hold_reason"], "connection_headroom_blocked")
        self.assertIsNone(status["next_current_change_at"])
        for changes in (dict(battery_power_w=-1200), dict(telemetry_valid=False),
                        dict(grid_w=1700, grid_phases_w=[600, 600, 500])):
            status = runtime.describe_current_wait({**g, **changes})
            self.assertNotEqual(status["current_hold_reason"], "connection_headroom_blocked")

    def test_total_connection_limit_with_three_phases_below_phase_limits(self):
        g = self.sample(total_limit_w=12000, grid_w=11700,
                        grid_phases_w=[3900, 3900, 3900])
        self.assertEqual(runtime.describe_current_wait(g)["current_hold_reason"],
                         "connection_headroom_blocked")

    def test_inverter_port_limit_with_remaining_connection_headroom(self):
        g = self.sample(total_limit_w=16000, grid_w=12900,
                        grid_phases_w=[4300, 4300, 4300],
                        inverter_grid_import_limit_w=10000, grid_port_w=12900,
                        grid_port_phases_w=[4300, 4300, 4300],
                        grid_charge_active=True, grid_charge_enabled=True,
                        battery_power_w=-42)
        g["current_policy"]["observed_at"] = None
        status = runtime.describe_current_wait(g)
        self.assertEqual(status["current_hold_reason"], "inverter_grid_headroom_blocked")
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
        h.set("battery_power", 0, "W", age=21)
        data = h.co._read_inputs(h.now)
        self.assertFalse(data["telemetry_valid"])
        self.assertIn(dict(source="charge_power", reason="time_skew"), data["telemetry_issues"])
        for issue in data["telemetry_issues"]:
            self.assertEqual(set(issue), {"source", "reason"})


if __name__ == "__main__":
    unittest.main()
