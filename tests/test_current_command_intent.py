"""Offline service-boundary regressions; HA echoes are not physical ACKs."""
from copy import deepcopy
from datetime import timedelta
import json
import unittest

from test_runtime import Harness, SOURCES


def setup(*, outcome="accepted"):
    h = Harness()
    h.set("asymmetric_phase_feeding", "on")
    h.set("grid_current_number", 40, "A")
    h.co._memory["ledger"][SOURCES["grid_current_number"]] = {
        "at": h.now.timestamp()-1000, "a": 40, "action": "set_value"}
    h.active()

    async def delayed(domain, action, data, **kwargs):
        # The service returns or fails without changing the observed HA state.
        # Every actual service still requires a durable write-ahead record.
        assert h.store.saved["ledger"][data["entity_id"]]["action"] == action
        h.calls.append((domain, action, deepcopy(data)))
        if outcome == "uncertain":
            raise OSError("offline transport failure")
    h.hass.services.async_call = delayed
    return h


class CurrentCommandIntent(unittest.IsolatedAsyncioTestCase):
    async def test_possible_zero_never_bounces_to_positive_on_stale_high_ha(self):
        h = setup()
        self.assertTrue(await h.co._grid_attempt(0, h.now.timestamp(), force=True))
        journal = deepcopy(h.co._memory["grid_dispatch"])
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp(), force=True))
        self.assertEqual(h.current_calls(), [0])
        self.assertEqual(h.co._memory["grid_dispatch"], journal)
        h.advance(1000)  # Expiring settling never turns0->20 into protection.
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp(), force=True))
        self.assertEqual(h.current_calls(), [0])

    async def test_accepted_identical_pending_command_settles_for_thirty_seconds(self):
        h = setup()
        self.assertTrue(await h.co._grid_attempt(0, h.now.timestamp(), force=True))
        at = h.co._memory["grid_dispatch"]["possible_at"]
        for elapsed in (10, 19.999):
            h.advance(elapsed)
            self.assertFalse(await h.co._grid_attempt(0, h.now.timestamp(), force=True))
            self.assertEqual(h.co._memory["grid_dispatch"]["possible_at"], at)
        h.advance(.001)
        self.assertTrue(await h.co._grid_attempt(0, h.now.timestamp(), force=True))
        self.assertEqual(h.current_calls(), [0, 0])

    async def test_uncertain_identical_command_retains_ten_second_retry(self):
        h = setup(outcome="uncertain")
        self.assertFalse(await h.co._grid_attempt(0, h.now.timestamp(), force=True))
        self.assertEqual(h.co._memory["grid_dispatch"]["outcome"], "uncertain")
        h.advance(9.999)
        self.assertFalse(await h.co._grid_attempt(0, h.now.timestamp(), force=True))
        self.assertEqual(h.current_calls(), [0])
        h.advance(.001)
        self.assertFalse(await h.co._grid_attempt(0, h.now.timestamp(), force=True))
        self.assertEqual(h.current_calls(), [0, 0])

    async def test_stricter_positive_and_zero_are_not_delayed_by_settling(self):
        h = setup()
        h.set("bms_charge_current", 27, "A")
        self.assertTrue(await h.co._grid_attempt(25, h.now.timestamp(), force=True))
        h.set("bms_charge_current", 24, "A")
        self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp(), force=True))
        h.set("bms_charge_current", 0, "A")
        self.assertTrue(await h.co._grid_attempt(0, h.now.timestamp(), force=True))
        self.assertEqual(h.current_calls(), [25, 20, 0])

    async def test_matching_ha_observation_skips_identical_command_without_physical_claim(self):
        h = setup()
        await h.co._grid_attempt(0, h.now.timestamp(), force=True)
        h.advance(60)
        h.set("grid_current_number", 0, "A")
        self.assertFalse(await h.co._grid_attempt(0, h.now.timestamp(), force=True))
        self.assertEqual(h.current_calls(), [0])
        observed = h.co._command_diagnostics["readback"]
        self.assertEqual(observed["source"], "home_assistant_state")
        self.assertEqual(observed["status"], "matched")
        self.assertFalse(observed["physical_confirmation"])

    async def test_new_mismatching_echo_does_not_raise_intent_or_flood_retry(self):
        h = setup()
        await h.co._grid_attempt(0, h.now.timestamp(), force=True)
        h.advance(10)
        self.assertFalse(await h.co._grid_attempt(0, h.now.timestamp(), force=True))
        self.assertEqual(h.co._command_diagnostics["readback"]["status"], "mismatch")
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp(), force=True))
        self.assertEqual(h.current_calls(), [0])

    async def test_certainly_not_sent_preserves_previous_possible_intent(self):
        h = setup()
        def invalidate():
            h.set("work_mode", "Selling First")
        h.store.on_save = invalidate
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp(), force=True))
        dispatch = h.co._memory["grid_dispatch"]
        self.assertEqual(dispatch["outcome"], "not_sent")
        self.assertEqual(dispatch["possible_a"], 40)
        self.assertEqual(h.current_calls(), [])
        h.store.on_save = None
        h.set("work_mode", "Zero Export To Load")
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp(), force=True))
        h.advance(10)
        self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp(), force=True))
        self.assertEqual(h.current_calls(), [20])

    async def test_unknown_and_future_history_allow_only_immediate_zero(self):
        for corrupt in ({"invalid": True}, None):
            with self.subTest(corrupt=corrupt):
                h = setup()
                if corrupt is None:
                    h.co._memory["ledger"][SOURCES["grid_current_number"]]["at"] = h.now.timestamp()+100
                else:
                    h.co._memory["grid_dispatch"] = corrupt
                self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp(), force=True))
                self.assertTrue(await h.co._grid_attempt(0, h.now.timestamp(), force=True))
                self.assertEqual(h.current_calls(), [0])

    async def test_store_replaces_journal_with_lower_other_intent_before_service(self):
        h = setup()
        def replace():
            state = deepcopy(h.co._memory["grid_dispatch"])
            state.update(id="other-intent", outcome="accepted", possible_a=0)
            h.co._set_ordinary_positive_history(state, known=True, kind="safety",
                at=state["ordinary_positive_history"]["possible_at"],
                previous=state["ordinary_positive_history"]["previous_possible_at"])
            h.co._memory["grid_dispatch"] = state
        h.store.on_save = replace
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp(), force=True))
        self.assertEqual(h.current_calls(), [])
        self.assertEqual(h.co._memory["grid_dispatch"]["possible_a"], 0)

    async def test_store_corrupts_own_previous_tuple_or_witness_before_service(self):
        for field in ("previous_possible_a", "witness"):
            with self.subTest(field=field):
                h = setup()
                def corrupt():
                    state = h.co._memory["grid_dispatch"]
                    if field == "witness":
                        state["ordinary_positive_history"]["witness"]["id"] = "changed"
                    else:
                        state[field] = None
                h.store.on_save = corrupt
                self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp(), force=True))
                self.assertEqual(h.current_calls(), [])
                h.store.on_save = None
                h.advance(30)
                self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp(), force=True))
                self.assertTrue(await h.co._grid_attempt(0, h.now.timestamp(), force=True))

    async def test_restart_retains_accepted_settling_and_resets_only_ram_trace(self):
        h = setup()
        await h.co._grid_attempt(0, h.now.timestamp(), force=True)
        restored = setup()
        restored.now = h.now + timedelta(seconds=5)
        restored.advance(0)
        restored.store.saved = deepcopy(h.store.saved)
        await restored.co.async_initialize()
        self.assertFalse(await restored.co._grid_attempt(0, restored.now.timestamp(), force=True))
        self.assertEqual(restored.current_calls(), [])
        self.assertEqual(restored.co._command_diagnostics["attempts"], [])
        restored.advance(25)
        self.assertTrue(await restored.co._grid_attempt(0, restored.now.timestamp(), force=True))
        self.assertEqual(restored.current_calls(), [0])

    async def test_prepared_restart_recovery_uses_uncertain_backoff(self):
        h = setup()
        await h.co._grid_attempt(0, h.now.timestamp(), force=True)
        saved = deepcopy(h.store.saved)
        saved["grid_dispatch"]["outcome"] = "prepared"
        saved["grid_dispatch"]["ordinary_positive_history"]["witness"]["outcome"] = "prepared"
        restored = setup()
        restored.now = h.now + timedelta(seconds=20)
        restored.advance(0)
        restored.store.saved = saved
        await restored.co.async_initialize()
        self.assertEqual(restored.co._memory["grid_dispatch"]["outcome"], "uncertain")
        self.assertFalse(await restored.co._grid_attempt(0, restored.now.timestamp(), force=True))
        restored.advance(10)
        self.assertTrue(await restored.co._grid_attempt(0, restored.now.timestamp(), force=True))

    async def test_private_trace_is_bounded_ram_only_and_has_no_old_history(self):
        h = setup()
        for index in range(25):
            await h.co._grid_attempt(0, h.now.timestamp(), force=True, reason="telemetry_invalid")
            h.advance(30)
        trace = h.co._command_diagnostics
        self.assertEqual(trace["retention"], "since_boot")
        self.assertEqual(trace["counts"]["accepted"], 25)
        self.assertEqual(len(trace["attempts"]), 20)
        self.assertTrue(all(row["reason"] == "telemetry_invalid" for row in trace["attempts"]))
        self.assertNotIn("command_diagnostics", h.store.saved)
        self.assertNotIn(SOURCES["grid_current_number"], json.dumps(trace))

    async def test_first_safety_phase_records_the_cause_of_the_actual_service(self):
        h = setup()
        h.set("grid_power", "unavailable", "W")
        data = await h.tick()
        self.assertEqual(h.current_calls(), [0])
        trace = data["command_diagnostics"]
        self.assertEqual(trace["counts"]["accepted"], 1)
        self.assertEqual(trace["attempts"][0]["reason"], "safety_telemetry_invalid")
        self.assertEqual(trace["attempts"][0]["outcome"], "accepted")
        self.assertNotIn("command_diagnostics", h.store.saved)


if __name__ == "__main__":
    unittest.main()
