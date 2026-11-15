"""Protective requests cannot rebound while a prior intent may still settle.

These synthetic pure-controller tests distinguish an observed setting from the
last possibly dispatched intent. They make no Home Assistant or device calls.
"""
import unittest

from test_grid_control import calculate_grid_charge, snapshot


def intent_snapshot(**changes):
    values = dict(current_a=30, last_attempt_a=30, last_attempt_ts=999,
                  current_intent_known=True, last_possible_current_a=30)
    values.update(changes)
    return snapshot(**values)


class ProtectiveCurrentIntent(unittest.TestCase):
    def decisions(self, inputs):
        for safety_only in (False, True):
            yield safety_only, calculate_grid_charge({**inputs, "safety_only": safety_only})

    def test_reduction_rounds_cap_down_without_changing_the_hard_cap(self):
        for safety_only, result in self.decisions(intent_snapshot(bms_cap_a=27)):
            with self.subTest(safety_only=safety_only):
                self.assertEqual(result["cap_a"], 27)
                self.assertEqual(result["next_a"], 25)
                self.assertTrue(result["safety"])
                self.assertTrue(result["write"])

    def test_stale_readback_does_not_raise_the_previous_protective_intent(self):
        inputs = intent_snapshot(bms_cap_a=26, last_possible_current_a=25,
                                 last_attempt_a=25, pending_current_a=25)
        for safety_only, result in self.decisions(inputs):
            with self.subTest(safety_only=safety_only):
                self.assertEqual(result["next_a"], 25)
                self.assertTrue(result["safety"])
                self.assertFalse(result["write"])

    def test_stricter_positive_reduction_is_immediate_during_settling(self):
        inputs = intent_snapshot(bms_cap_a=24, last_possible_current_a=25,
                                 last_attempt_a=25, pending_current_a=25)
        for safety_only, result in self.decisions(inputs):
            with self.subTest(safety_only=safety_only):
                self.assertEqual(result["next_a"], 20)
                self.assertTrue(result["safety"])
                self.assertTrue(result["write"])

    def test_relaxed_cap_does_not_bypass_the_ordinary_clock_after_reduction(self):
        result = calculate_grid_charge(intent_snapshot(
            bms_cap_a=40, last_possible_current_a=25, last_attempt_a=25,
            pending_current_a=25))
        self.assertFalse(result["write"])

    def test_possible_zero_cannot_bounce_to_positive_with_a_stale_high_readback(self):
        inputs = intent_snapshot(current_a=40, bms_cap_a=20,
                                 last_possible_current_a=0, last_attempt_a=0,
                                 pending_current_a=0)
        for safety_only, result in self.decisions(inputs):
            with self.subTest(safety_only=safety_only):
                self.assertEqual(result["next_a"], 0)
                self.assertTrue(result["safety"])
                self.assertFalse(result["write"])

    def test_stricter_zero_bypasses_settling_and_ordinary_clocks(self):
        inputs = intent_snapshot(current_a=40, bms_cap_a=20,
                                 last_possible_current_a=20, last_attempt_a=20,
                                 pending_current_a=20, telemetry_valid=False)
        for safety_only, result in self.decisions(inputs):
            with self.subTest(safety_only=safety_only):
                self.assertEqual(result["next_a"], 0)
                self.assertTrue(result["safety"])
                self.assertTrue(result["write"])

    def test_policy_stop_cannot_be_replaced_by_a_positive_cap_correction(self):
        result = calculate_grid_charge(intent_snapshot(
            current_a=40, bms_cap_a=20, last_possible_current_a=20,
            last_attempt_a=20, pending_current_a=20, cheap_window=False))
        self.assertEqual(result["next_a"], 0)
        self.assertTrue(result["safety"])
        self.assertTrue(result["write"])

    def test_quantization_does_not_create_a_reduction_below_a_safe_raw_cap(self):
        inputs = intent_snapshot(current_a=46, bms_cap_a=49,
                                 last_possible_current_a=46, last_attempt_a=46)
        for safety_only, result in self.decisions(inputs):
            with self.subTest(safety_only=safety_only):
                self.assertEqual(result["cap_a"], 49)
                self.assertEqual(result["next_a"], 46)
                self.assertFalse(result["write"])

    def test_cancelling_an_unsafe_pending_increase_keeps_a_safe_current(self):
        inputs = intent_snapshot(current_a=42, bms_cap_a=50,
                                 last_possible_current_a=62, last_attempt_a=62,
                                 pending_current_a=62)
        for safety_only, result in self.decisions(inputs):
            with self.subTest(safety_only=safety_only):
                self.assertEqual(result["next_a"], 42)
                self.assertTrue(result["safety"])
                self.assertTrue(result["write"])

    def test_sub_quantum_caps_still_allow_safe_integer_reductions(self):
        for cap in (1, 2, 3, 4):
            for safety_only, result in self.decisions(intent_snapshot(bms_cap_a=cap)):
                with self.subTest(cap=cap, safety_only=safety_only):
                    self.assertEqual(result["cap_a"], cap)
                    self.assertEqual(result["next_a"], cap)
                    self.assertTrue(result["safety"])
                    self.assertTrue(result["write"])

    def test_unknown_or_corrupt_intent_cannot_authorize_a_positive_reduction(self):
        cases = [dict(current_intent_known=False), dict(current_intent_known=1),
                 dict(current_intent_known=None), dict(current_intent_known="true"),
                 dict(last_possible_current_a=None), dict(last_possible_current_a=True),
                 dict(last_possible_current_a=-1), dict(last_possible_current_a=1001),
                 dict(last_possible_current_a="20"),
                 dict(last_possible_current_a=float("nan")),
                 dict(last_possible_current_a=float("inf"))]
        for change in cases:
            for safety_only, result in self.decisions(intent_snapshot(bms_cap_a=20, **change)):
                with self.subTest(change=change, safety_only=safety_only):
                    self.assertEqual(result["next_a"], 0)
                    self.assertTrue(result["safety"])

    def test_partial_explicit_intent_metadata_is_not_a_legacy_snapshot(self):
        for field in ("current_intent_known", "last_possible_current_a"):
            inputs = intent_snapshot(bms_cap_a=20)
            inputs.pop(field)
            for safety_only, result in self.decisions(inputs):
                with self.subTest(missing=field, safety_only=safety_only):
                    self.assertEqual(result["next_a"], 0)
                    self.assertTrue(result["safety"])

    def test_future_history_cannot_authorize_a_positive_reduction(self):
        for field in ("last_attempt_ts", "ordinary_last_possible_ts",
                      "ordinary_last_not_sent_ts"):
            for safety_only, result in self.decisions(intent_snapshot(
                    bms_cap_a=20, **{field: 1001})):
                with self.subTest(field=field, safety_only=safety_only):
                    self.assertEqual(result["next_a"], 0)
                    self.assertTrue(result["safety"])

    def test_explicit_validated_virgin_history_is_not_corrupt_intent(self):
        inputs = intent_snapshot(current_a=40, bms_cap_a=20,
                                 last_possible_current_a=None,
                                 current_intent_virgin=True,
                                 last_attempt_ts=None, last_attempt_a=None,
                                 ordinary_last_possible_ts=None,
                                 ordinary_last_not_sent_ts=None)
        for safety_only, result in self.decisions(inputs):
            with self.subTest(safety_only=safety_only):
                self.assertEqual(result["next_a"], 20)
                self.assertTrue(result["safety"])
                self.assertTrue(result["write"])


if __name__ == "__main__":
    unittest.main()
