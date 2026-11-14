"""Synthetic rolling-clock, journal migration and hardware-boundary regressions."""
from copy import deepcopy
from datetime import timedelta
import unittest

from test_runtime import Coordinator, Harness, SOURCES, runtime


def setup():
    h = Harness(options={"winter_weather_soc_percent": 85})
    h.now = h.now.replace(minute=7)
    h.advance(0)
    h.set("asymmetric_phase_feeding", "on")
    h.active()
    stable(h)
    return h


def stable(h):
    h.co._memory["current_policy"].update(safe_since=h.now.timestamp()-120,
        observed_at=h.now.timestamp())


def grid(h):
    return h.co._grid_input(h.co._read_inputs(h.now), h.now, 85, False)


class RollingClock(unittest.TestCase):
    def test_599_600_seconds_and_any_possible_not_sent_boundaries(self):
        ready = runtime.dispatch_ready
        self.assertFalse(ready(1000, 401, None, 401))
        self.assertTrue(ready(1000, 400, None, 400))
        self.assertFalse(ready(1000, 881, None, 1))
        self.assertTrue(ready(1000, 880, None, 1))
        self.assertFalse(ready(1000, 1, 941, 1))
        self.assertTrue(ready(1000, 1, 940, 1))
        for invalid in (True, -1, 1001, float("nan"), "1"):
            self.assertFalse(ready(1000, 1, None, invalid))


class RollingRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_safety_zero_does_not_move_ordinary_clock_or_refund_initial(self):
        h = setup()
        self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp()))
        ordinary_at = grid(h)["ordinary_last_positive_possible_ts"]
        h.advance(470)
        self.assertTrue(await h.co._grid_attempt(0, h.now.timestamp(), force=True))
        self.assertEqual(grid(h)["ordinary_last_positive_possible_ts"], ordinary_at)
        h.advance(129)
        stable(h)
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
        h.advance(1)
        stable(h)
        self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp()))
        self.assertEqual(h.current_calls(), [20, 0, 20])
        self.assertTrue(h.co._initial_window_started(h.now))

    async def test_safety_positive_reduction_has_separate_classification(self):
        h = setup()
        self.assertTrue(await h.co._grid_attempt(40, h.now.timestamp()))

    async def test_1520_zero_and_1529_telemetry_gap_resume_at_153118(self):
        h = setup()
        h.now = h.now.replace(hour=15, minute=0, second=0)
        h.advance(0)
        stable(h)
        self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp()))
        h.advance(1200)
        self.assertTrue(await h.co._grid_attempt(0, h.now.timestamp(), force=True))
        h.advance(548)
        h.set("grid_power", "unavailable", "W")
        await h.tick()
        self.assertFalse(h.co.data["inputs"]["telemetry_valid"])
        h.advance(10)
        h.set("grid_power", 1800, "W")
        await h.tick()
        positives = len([a for a in h.current_calls() if a > 0])
        for _ in range(11):
            h.advance(10)
            await h.tick()
            self.assertEqual(len([a for a in h.current_calls() if a > 0]), positives)
        h.advance(10)
        await h.tick()
        self.assertEqual((h.now.hour, h.now.minute, h.now.second), (15, 31, 18))
        self.assertEqual(len([a for a in h.current_calls() if a > 0]), positives+1)
        ordinary_at = grid(h)["ordinary_last_positive_possible_ts"]
        h.advance(100)
        self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp(), force=True))
        self.assertEqual(grid(h)["ordinary_last_positive_possible_ts"], ordinary_at)
        self.assertEqual(h.store.saved["grid_dispatch"]["ordinary_positive_history"]["kind"], "safety")
        h.advance(499)
        stable(h)
        self.assertFalse(await h.co._grid_attempt(40, h.now.timestamp()))
        h.advance(1)
        stable(h)
        self.assertTrue(await h.co._grid_attempt(40, h.now.timestamp()))

    async def test_live_pv_stop_and_cloud_restart_after_120_seconds_without_boundary(self):
        h = setup()
        await h.tick()
        self.assertTrue(any(a > 0 for a in h.current_calls()))
        h.advance(610)
        h.set("battery_power", -9000, "W")
        await h.tick()
        self.assertEqual(h.current_calls()[-1], 0)
        h.set("battery_power", 0, "W")
        positives = len([a for a in h.current_calls() if a > 0])
        for _ in range(12):
            h.advance(10)
            await h.tick()
            self.assertEqual(len([a for a in h.current_calls() if a > 0]), positives)
        h.advance(10)
        await h.tick()
        self.assertEqual(len([a for a in h.current_calls() if a > 0]), positives+1)
        self.assertNotIn(h.now.minute, (0, 30))

    async def test_restart_new_deadline_and_stop_cannot_bypass_600_seconds(self):
        h = setup()
        self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp()))
        h.advance(10)
        await h.co.async_set_mode("shadow")
        h.advance(130)
        await h.co.async_set_mode("active")
        h.co._memory["initial_charge_window"] = {}  # Even a fresh marker is no cooldown permission.
        stable(h)
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
        await h.co._save()
        restored = Coordinator(h.hass, h.entry, store=h.store, clock=lambda: h.now)
        await restored.async_initialize()
        h.co = restored
        stable(h)
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
        g = grid(h)
        g.update(initial_window_started=False, policy_deadline=(h.now+timedelta(days=1)).isoformat())
        g["current_policy"].update(initial_started=False, deadline=g["policy_deadline"])
        self.assertFalse(runtime.initial_dispatch_ready(g))

    async def test_certain_not_sent_restores_both_clocks_and_60_second_backoff(self):
        h = setup()
        self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp()))
        old = grid(h)["ordinary_last_positive_possible_ts"]
        h.advance(600)
        stable(h)
        h.store.on_save = lambda: h.set("bms_blocking_charge", 1)
        self.assertFalse(await h.co._grid_attempt(40, h.now.timestamp()))
        self.assertEqual(grid(h)["ordinary_last_positive_possible_ts"], old)
        self.assertEqual(grid(h)["ordinary_last_possible_ts"], old)
        h.store.on_save = None
        h.set("bms_blocking_charge", 0)
        h.advance(59)
        stable(h)
        self.assertFalse(await h.co._grid_attempt(40, h.now.timestamp()))
        h.advance(1)
        stable(h)
        self.assertTrue(await h.co._grid_attempt(40, h.now.timestamp()))

    async def test_legacy_zero_migration_is_conservative_and_carried_by_new_safety(self):
        h = setup()
        legacy_at = h.now.timestamp()-300
        h.co._memory["ledger"][SOURCES["grid_current_number"]] = {
            "at": legacy_at, "a": 0, "action": "set_value"}
        self.assertEqual(grid(h)["ordinary_last_positive_possible_ts"], legacy_at)
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
        await h.co._grid_attempt(0, h.now.timestamp(), force=True)
        self.assertEqual(grid(h)["ordinary_last_positive_possible_ts"], legacy_at)
        h.advance(300)
        stable(h)
        self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp()))

    async def test_prepared_crash_and_213_recovery_use_conservative_current_time(self):
        for old_recovery in (False, True):
            with self.subTest(old_recovery=old_recovery):
                h = setup()
                self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp()))
                saved = next(deepcopy(s) for s in h.store.history
                             if s.get("grid_dispatch", {}).get("outcome") == "prepared")
                h.advance(900)
                if old_recovery:
                    # The old release preserved extras during PREPARED recovery.
                    saved["grid_dispatch"].update(outcome="uncertain", possible_at=h.now.timestamp())
                h.store.saved = saved
                restored = Coordinator(h.hass, h.entry, store=h.store, clock=lambda: h.now)
                await restored.async_initialize()
                h.co = restored
                self.assertEqual(grid(h)["ordinary_last_positive_possible_ts"], h.now.timestamp())
                h.set("grid_current_number", 0, "A")  # The possible command has no register ACK.
                h.advance(599)
                stable(h)
                self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
                h.advance(1)
                stable(h)
                self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp()))

    async def test_downgrade_legacy_write_drops_extra_and_reupgrade_uses_latest_any(self):
        h = setup()
        self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp()))
        h.advance(650)
        # 2.1.3 reconstructs this literal record, ignoring/dropping new extras.
        state = {k: v for k, v in h.co._memory["grid_dispatch"].items() if k != "ordinary_positive_history"}
        state.update(id="synthetic-legacy-zero", outcome="accepted", attempt_at=h.now.timestamp(),
                     possible_at=h.now.timestamp(), possible_a=0, unconfirmed_upper_a=0)
        h.co._memory["grid_dispatch"] = state
        h.set("grid_current_number", 0, "A")
        self.assertEqual(grid(h)["ordinary_last_positive_possible_ts"], h.now.timestamp())
        h.advance(599)
        stable(h)
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
        h.advance(1)
        stable(h)
        self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp()))

    async def test_corrupt_history_cannot_be_laundered_by_safety_zero_or_enable_gc(self):
        for corrupt in (None, {"version": 1}, "future"):
            with self.subTest(corrupt=corrupt):
                h = setup()
                self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp()))
                if corrupt == "future":
                    h.co._memory["grid_dispatch"]["ordinary_positive_history"]["possible_at"] = h.now.timestamp()+1
                else:
                    h.co._memory["grid_dispatch"]["ordinary_positive_history"] = corrupt
                h.advance(1000)
                stable(h)
                # Positive ledger/register are settled, but unknown provenance forbids GC ON.
                for slot in (1, 2, 6):
                    h.set(f"tou_soc_{slot}", 85, "%")
                self.assertFalse(grid(h)["ordinary_history_known"])
                self.assertFalse(await h.co._service(SOURCES["tou_gc_6"], "turn_on"))
                self.assertFalse(await h.co._grid_attempt(30, h.now.timestamp()))
                self.assertTrue(await h.co._grid_attempt(0, h.now.timestamp(), force=True))
                h.advance(1000)
                stable(h)
                self.assertFalse(grid(h)["ordinary_history_known"])
                self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))

    async def test_partial_nonnumeric_and_witness_mismatches_fail_closed(self):
        h = setup()
        self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp()))
        good = deepcopy(h.co._memory["grid_dispatch"])
        for field, value in (("possible_at", None), ("possible_at", "1"),
                             ("previous_possible_at", True), ("version", True),
                             ("witness", {}), ("kind", "unknown")):
            with self.subTest(field=field, value=value):
                h.co._memory["grid_dispatch"] = deepcopy(good)
                h.co._memory["grid_dispatch"]["ordinary_positive_history"][field] = value
                self.assertFalse(grid(h)["ordinary_history_known"])
        h.co._memory["grid_dispatch"] = deepcopy(good)
        h.co._memory["grid_dispatch"]["id"] = "unrelated-attempt"
        self.assertFalse(grid(h)["ordinary_history_known"])

    async def test_unknown_history_blocks_new_and_continuing_gc(self):
        for existing_gc in ("off", "on"):
            with self.subTest(existing_gc=existing_gc):
                h = setup()
                self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp()))
                h.advance(1000)
                stable(h)
                for slot in (1, 2, 6):
                    h.set(f"tou_soc_{slot}", 85, "%")
                h.set("tou_gc_6", existing_gc)
                h.co._memory["grid_dispatch"]["ordinary_positive_history"] = {"version": 1}
                await h.tick()
                self.assertEqual(h.states[SOURCES["tou_gc_6"]].state, "off")
                self.assertFalse(any(action == "turn_on" for _, action, _ in h.calls))
                self.assertEqual(h.current_calls(), [20])

    async def test_positive_register_and_old_ledger_cannot_enable_gc_before_120_stable_seconds(self):
        h = setup()
        h.set("grid_current_number", 20, "A")
        h.co._memory["ledger"][SOURCES["grid_current_number"]] = {
            "at": h.now.timestamp()-1000, "a": 20, "action": "set_value"}
        for slot in (1, 2, 6):
            h.set(f"tou_soc_{slot}", 85, "%")
        h.co._memory["current_policy"].update(safe_since=h.now.timestamp()-30, observed_at=h.now.timestamp())
        self.assertFalse(await h.co._service(SOURCES["tou_gc_6"], "turn_on"))
        await h.tick()
        self.assertEqual(h.states[SOURCES["tou_gc_6"]].state, "off")
