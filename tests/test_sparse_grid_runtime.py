"""Sparse current commands: durable intent, dispatch uncertainty and fresh guards."""
from copy import deepcopy
from datetime import timedelta
import unittest

from test_runtime import Coordinator, Harness, SOURCES, runtime


def setup():
    h = Harness(options={"winter_weather_soc_percent": 85})
    h.set("asymmetric_phase_feeding", "on")
    h.active()
    return h


def grid(h):
    return h.co._grid_input(h.co._read_inputs(h.now), h.now, 85, False)


class SparseGridRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_accepted_ordinary_is_durable_and_not_repeated_before_next_half_hour(self):
        h = setup()
        await h.tick()
        self.assertEqual(h.current_calls(), [55])
        prepared = next(s["grid_dispatch"] for s in h.store.history
                        if s.get("grid_dispatch", {}).get("outcome") == "prepared")
        self.assertEqual(prepared["possible_a"], 55)
        self.assertEqual(h.store.saved["grid_dispatch"]["outcome"], "accepted")
        for seconds in (10, 100, 489):
            h.advance(seconds)
            await h.tick()
            self.assertEqual(h.current_calls(), [55])
        h.advance(1201)
        h.set("soc", 45, "%")
        h.co._memory["current_policy"].update(safe_since=h.now.timestamp()-120, observed_at=h.now.timestamp())
        await h.tick()
        self.assertEqual(h.current_calls(), [55, 65])

    async def test_store_failure_is_not_sent_and_retry_waits_for_next_half_hour(self):
        h = setup()
        h.store.fail = True
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
        self.assertEqual(h.current_calls(), [])
        self.assertEqual(h.co._memory["grid_dispatch"]["outcome"], "not_sent")
        self.assertIsNone(grid(h)["ordinary_last_possible_ts"])
        h.store.fail = False
        h.advance(59)
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
        h.advance(1741)
        h.co._memory["current_policy"].update(safe_since=h.now.timestamp()-120, observed_at=h.now.timestamp())
        self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp()))
        self.assertEqual(h.current_calls(), [20])

    async def test_post_store_preflight_rejection_is_not_sent(self):
        h = setup()
        h.store.on_save = lambda: h.set("bms_blocking_charge", 1)
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
        self.assertEqual(h.current_calls(), [])
        self.assertIsNone(grid(h)["ordinary_last_possible_ts"])
        self.assertEqual(h.co._memory["grid_dispatch"]["outcome"], "not_sent")

    async def test_transport_failure_is_uncertain_and_blocks_ordinary_for_600_seconds(self):
        h = setup()
        h.fail_service = True
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
        self.assertEqual(h.co._memory["grid_dispatch"]["outcome"], "uncertain")
        self.assertEqual(grid(h)["pending_current_a"], 20)
        h.fail_service = False
        h.advance(599)
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
        h.advance(1)
        h.co._memory["current_policy"].update(safe_since=h.now.timestamp()-120, observed_at=h.now.timestamp())
        self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp()))
        self.assertEqual(h.current_calls(), [20, 20])

    async def test_safety_does_not_wait_and_restarts_the_recovery_clock(self):
        h = setup()
        self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp()))
        h.advance(590)
        self.assertTrue(await h.co._grid_attempt(0, h.now.timestamp(), force=True))
        self.assertEqual(h.current_calls(), [20, 0])
        h.advance(119)
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
        h.advance(1)
        h.co._memory["current_policy"].update(safe_since=h.now.timestamp()-120, observed_at=h.now.timestamp())
        self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp()))

    async def test_sure_not_sent_preserves_earlier_possible_dispatch(self):
        h = setup()
        self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp()))
        sent_at = grid(h)["ordinary_last_possible_ts"]
        h.advance(100)
        h.store.fail = True
        self.assertFalse(await h.co._grid_attempt(0, h.now.timestamp(), force=True))
        self.assertEqual(grid(h)["ordinary_last_possible_ts"], sent_at)
        self.assertEqual(h.co._memory["grid_dispatch"]["possible_a"], 20)
        h.store.fail = False
        h.advance(60)
        self.assertFalse(await h.co._grid_attempt(40, h.now.timestamp()))

    async def test_prepared_restart_is_uncertain_and_cannot_bypass_cooldown(self):
        h = setup()
        self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp()))
        prepared = next(deepcopy(s) for s in h.store.history
                        if s.get("grid_dispatch", {}).get("outcome") == "prepared")
        h.advance(900)
        h.store.saved = prepared
        restored = Coordinator(h.hass, h.entry, store=h.store, clock=lambda: h.now)
        await restored.async_initialize()
        self.assertEqual(restored._memory["grid_dispatch"]["outcome"], "uncertain")
        self.assertEqual(restored._memory["grid_dispatch"]["possible_at"], h.now.timestamp())
        self.assertFalse(await restored._grid_attempt(40, h.now.timestamp()))

    async def test_legacy_attempt_and_malformed_future_history_are_conservative(self):
        for bad in (False, True, "future"):
            h = setup()
            h.co._memory["ledger"][SOURCES["grid_current_number"]] = {
                "at": h.now.timestamp()-10, "a": 0, "action": "set_value"}
            if bad is True:
                h.co._memory["grid_dispatch"] = {"invalid": True}
            elif bad == "future":
                h.co._memory["ledger"][SOURCES["grid_current_number"]]["at"] = h.now.timestamp()+1
            self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
            self.assertEqual(h.current_calls(), [])

    async def test_slow_store_uses_actual_dispatch_time_and_rechecks_actual_grid(self):
        h = setup()
        once = [False]
        def delayed_store():
            if not once[0]:
                once[0] = True
                h.advance(601)
        h.store.on_save = delayed_store
        before = h.now.timestamp()
        self.assertFalse(await h.co._grid_attempt(20, before))
        self.assertIsNone(h.co._memory["grid_dispatch"]["possible_at"])
        self.assertEqual(h.current_calls(), [])
        h.advance(599)
        self.assertFalse(await h.co._grid_attempt(40, h.now.timestamp()))
        h = setup()
        h.store.on_save = lambda: h.set("grid_l1_power", 4740, "W")
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
        self.assertEqual(h.current_calls(), [])
        self.assertEqual(h.co._memory["grid_dispatch"]["outcome"], "not_sent")

    async def test_new_dispatch_marker_during_store_is_not_ignored_or_overwritten(self):
        h = setup()
        def another_dispatch():
            state = h.co._memory["grid_dispatch"]
            state.update(id="another", outcome="accepted", possible_at=h.now.timestamp(), possible_a=10,
                         unconfirmed_upper_a=10)
        h.store.on_save = another_dispatch
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
        self.assertEqual(h.current_calls(), [])
        self.assertEqual(h.co._memory["grid_dispatch"]["id"], "another")

    async def test_post_store_safety_reduction_cannot_turn_into_a_large_increase(self):
        h = setup()
        h.set("grid_current_number", 80, "A")
        h.set("bms_charge_current", 50, "A")
        h.co._memory["ledger"][SOURCES["grid_current_number"]] = {
            "at": h.now.timestamp()-5, "a": 80, "action": "set_value"}
        h.store.on_save = lambda: h.set("grid_current_number", 0, "A")
        self.assertFalse(await h.co._grid_attempt(50, h.now.timestamp(), force=True))
        self.assertEqual(h.current_calls(), [])
        self.assertEqual(h.co._memory["grid_dispatch"]["outcome"], "not_sent")
        self.assertEqual(grid(h)["pending_current_a"], 80)

    async def test_stricter_zero_is_not_delayed_by_a_future_ledger(self):
        h = setup()
        h.set("grid_current_number", 20, "A")
        h.co._memory["ledger"][SOURCES["grid_current_number"]] = {
            "at": h.now.timestamp()+100, "a": 0, "action": "set_value"}
        self.assertTrue(await h.co._grid_attempt(0, h.now.timestamp(), force=True))
        self.assertEqual(h.current_calls(), [0])

    async def test_small_start_and_safety_zero_ignore_only_the_amplitude_deadband(self):
        h = setup()
        h.set("bms_charge_current", 3, "A")
        await h.tick()
        self.assertEqual(h.current_calls(), [3])
        self.assertTrue(await h.co._grid_attempt(0, h.now.timestamp(), force=True))
        self.assertEqual(h.current_calls(), [3, 0])

    async def test_gc_enable_checks_full_setting_after_store_and_recovery_reduces_it(self):
        h = setup()
        h.set("grid_current_number", 42, "A")
        h.co._memory["ledger"][SOURCES["grid_current_number"]] = {
            "at": h.now.timestamp()-1000, "a": 42, "action": "set_value"}
        h.set("grid_power", 11020, "W")
        for i, power in enumerate((3674, 3673, 3673), 1):
            h.set(f"grid_l{i}_power", power, "W")
        await h.tick()
        self.assertEqual(h.current_calls(), [8])
        self.assertEqual(h.states[SOURCES["tou_gc_6"]].state, "off")
        for _ in range(12):
            h.advance(10)
            await h.tick()
        self.assertEqual(h.states[SOURCES["tou_gc_6"]].state, "on")

    async def test_pending_higher_command_survives_uncertain_and_not_sent_cancel_until_fresh_ack(self):
        for outcome in ("accepted", "uncertain", "not_sent"):
            with self.subTest(outcome=outcome):
                h = setup()
                # This SoC needs 65 A to the deadline, so the original command
                # satisfies the live-demand guard before its ACK is lost.
                h.set("soc", 40, "%")
                h.set("grid_current_number", 42, "A")
                h.set("tou_gc_6", "on")
                h.co._memory["ledger"][SOURCES["grid_current_number"]] = {
                    "at": h.now.timestamp()-1000, "a": 42, "action": "set_value"}
                original = h.hass.services.async_call
                async def no_register(domain, action, data, **kwargs):
                    if data["entity_id"] == SOURCES["grid_current_number"]:
                        h.calls.append((domain, action, deepcopy(data)))
                        if h.fail_service:
                            raise OSError("synthetic uncertain cancel")
                        return
                    return await original(domain, action, data, **kwargs)
                h.hass.services.async_call = no_register
                self.assertTrue(await h.co._grid_attempt(65, h.now.timestamp()))
                h.advance(10)
                h.set("bms_charge_current", 50, "A")
                h.fail_service = outcome == "uncertain"
                h.store.fail = outcome == "not_sent"
                data = grid(h)
                control = runtime.calculate_grid_charge(data)
                self.assertEqual(control["next_a"], 42)
                self.assertTrue(control["write"])
                await h.co._grid_attempt(42, h.now.timestamp(), force=True)
                self.assertEqual(grid(h)["pending_current_a"], 65)
                # Restore transport/storage so this assertion checks the GC
                # permission decision, not an intentionally failed OFF call.
                h.store.fail = h.fail_service = False
                observed = h.co._read_inputs(h.now)
                next_control = runtime.calculate_grid_charge(grid(h))
                await h.co._run_driver(observed, next_control, 85, False, h.now)
                self.assertEqual(h.states[SOURCES["tou_gc_6"]].state, "off")
                h.store.fail = h.fail_service = False
                if outcome == "not_sent":
                    h.advance(10)
                    await h.co._grid_attempt(42, h.now.timestamp(), force=True)
                h.advance(1)
                h.set("grid_current_number", 42, "A")
                self.assertIsNone(grid(h)["pending_current_a"])
