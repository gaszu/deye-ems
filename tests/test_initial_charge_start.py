"""Durable one-per-window initial starts; all device effects are mocked."""
from copy import deepcopy
from datetime import datetime, timedelta
import unittest

from test_runtime import Harness, Coordinator, SOURCES, TZ


def setup(at="2026-11-10T22:07:00+01:00"):
    h = Harness(when=datetime.fromisoformat(at).astimezone(TZ),
                options={"winter_weather_soc_percent": 85})
    h.set("asymmetric_phase_feeding", "on")
    h.active()
    return h


def stable(h):
    h.co._memory["current_policy"].update(safe_since=h.now.timestamp()-120,
        observed_at=h.now.timestamp())


def legacy_zero(h, at=None):
    at = h.now.timestamp()-300 if at is None else at
    h.co._memory["ledger"][SOURCES["grid_current_number"]] = {
        "at": at, "a": 0, "action": "set_value"}


class InitialChargeStart(unittest.IsolatedAsyncioTestCase):
    async def test_missed_boundary_first_start_uses_live_demand_after_stable_observation(self):
        h = setup()
        await h.tick()
        self.assertEqual(len(h.current_calls()), 1)
        self.assertGreater(h.current_calls()[0], 20)
        self.assertEqual(h.co.data["control"]["reason"], "initial_charge_start")
        self.assertTrue(h.store.saved["initial_charge_window"]["spent"])
        prepared = next(s["grid_dispatch"] for s in h.store.history
                        if s.get("grid_dispatch", {}).get("outcome") == "prepared")
        self.assertTrue(prepared["initial_start"])
        self.assertEqual(prepared["positive_deadline"], h.co._window(h.now)[3].isoformat())

    async def test_first_start_waits_120_seconds_of_fresh_observation(self):
        h = setup()
        h.co._memory["current_policy"] = {}
        await h.tick()
        for _ in range(11):
            h.advance(10)
            await h.tick()
        self.assertEqual(h.current_calls(), [])
        h.advance(10)
        await h.tick()
        self.assertEqual(len(h.current_calls()), 1)

    async def test_pv_stop_zero_and_cloud_do_not_refund_initial_permission(self):
        h = setup()
        await h.tick()
        h.advance(10)
        h.set("battery_power", -9000, "W")
        await h.tick()
        self.assertEqual(h.current_calls()[-1], 0)
        h.set("battery_power", 0, "W")
        for _ in range(20):
            h.advance(10)
            await h.tick()
        self.assertEqual(len([a for a in h.current_calls() if a > 0]), 1)
        self.assertTrue(h.co._memory["initial_charge_window"]["spent"])

    async def test_any_positive_ordinary_correction_spends_the_window(self):
        h = setup("2026-11-10T22:00:00+01:00")
        h.set("grid_current_number", 5, "A")
        self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp()))
        self.assertTrue(h.store.saved["initial_charge_window"]["spent"])
        h.advance(10)
        self.assertTrue(await h.co._grid_attempt(0, h.now.timestamp(), force=True))
        h.advance(130)
        stable(h)
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))

    async def test_restart_restores_spent_permission_and_observation_timer(self):
        h = setup()
        await h.tick()
        h.advance(10)
        await h.co._grid_attempt(0, h.now.timestamp(), force=True)
        restored = Coordinator(h.hass, h.entry, store=h.store, clock=lambda:h.now)
        await restored.async_initialize()
        h.co = restored
        self.assertTrue(h.co._initial_window_started(h.now))
        self.assertIsNone(h.co._memory["current_policy"]["safe_since"])
        h.advance(130)
        stable(h)
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))

    async def test_prepared_positive_restart_conservatively_spends_permission(self):
        h = setup()
        await h.tick()
        prepared = next(deepcopy(s) for s in h.store.history
                        if s.get("grid_dispatch", {}).get("outcome") == "prepared")
        self.assertFalse(prepared.get("initial_charge_window", {}).get("spent", False))
        h.store.saved = prepared
        h.advance(10)
        restored = Coordinator(h.hass, h.entry, store=h.store, clock=lambda:h.now)
        await restored.async_initialize()
        self.assertTrue(restored._initial_window_started(h.now))
        self.assertTrue(restored._memory["initial_charge_window"]["spent"])

    async def test_uncertain_positive_dispatch_does_not_regrant_early_retry(self):
        h = setup()
        h.fail_service = True
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
        self.assertEqual(h.co._memory["grid_dispatch"]["outcome"], "uncertain")
        self.assertTrue(h.co._memory["initial_charge_window"]["spent"])
        h.fail_service = False
        h.advance(130)
        stable(h)
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))

    async def test_certain_not_sent_does_not_spend_but_obeys_60_second_retry(self):
        h = setup()
        h.store.fail = True
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
        self.assertFalse(h.co._initial_window_started(h.now))
        self.assertEqual(h.co._memory["grid_dispatch"]["outcome"], "not_sent")
        h.store.fail = False
        h.advance(59)
        stable(h)
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
        h.advance(1)
        stable(h)
        self.assertTrue(await h.co._grid_attempt(20, h.now.timestamp()))

    async def test_old_positive_pending_provenance_prevents_initial_start(self):
        h = setup()
        h.co._memory["ledger"][SOURCES["grid_current_number"]] = {
            "at": h.now.timestamp()-300, "a": 55, "action": "set_value"}
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
        self.assertEqual(h.current_calls(), [])

    async def test_legacy_zero_and_explicit_activation_cannot_bypass_rolling_interval(self):
        h = setup()
        legacy_zero(h)
        await h.co._save()
        restored = Coordinator(h.hass, h.entry, store=h.store, clock=lambda:h.now)
        await restored.async_initialize()
        h.co = restored
        h.advance(130)
        stable(h)
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
        h.co._memory["mode"] = "shadow"
        await h.co.async_set_mode("active")
        self.assertEqual(h.current_calls(), [])
        h.advance(170)  # 300 before restart +130 observed +170 =600 since legacy upper bound.
        stable(h)
        await h.tick()
        self.assertTrue(h.current_calls())
        self.assertTrue(h.store.saved["initial_charge_window"]["spent"])
        h.advance(10)
        await h.co.async_set_mode("shadow")
        h.advance(130)
        stable(h)
        await h.co.async_set_mode("active")
        self.assertEqual(len([a for a in h.current_calls() if a > 0]), 1)

    async def test_new_window_allows_one_new_start_but_midnight_does_not_reset(self):
        h = setup("2026-11-10T23:57:00+01:00")
        await h.tick()
        h.advance(10)
        await h.co._grid_attempt(0, h.now.timestamp(), force=True)
        h.advance(300)
        stable(h)
        self.assertTrue(h.co._initial_window_started(h.now))
        self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
        h.now = h.now.replace(hour=13, minute=7, second=0)
        h.advance(0)
        h.co._memory["current_policy"].update(deadline=h.co._window(h.now)[3].isoformat())
        stable(h)
        await h.tick()
        self.assertEqual(len([a for a in h.current_calls() if a > 0]), 2)

    async def test_late_store_changes_cancel_initial_permission_without_spending(self):
        for change in ("bms", "pv", "register", "protected"):
            with self.subTest(change=change):
                h = setup("2026-11-10T06:59:59+01:00" if change=="protected"
                          else "2026-11-10T22:07:00+01:00")
                def mutate():
                    if change == "bms":
                        h.set("bms_blocking_charge", 1)
                    elif change == "pv":
                        h.set("battery_power", -9000, "W")
                    elif change == "register":
                        h.set("grid_current_number", 5, "A")
                    else:
                        h.advance(2)
                h.store.on_save = mutate
                self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
                self.assertEqual(h.current_calls(), [])
                self.assertEqual(h.co._memory["grid_dispatch"]["outcome"], "not_sent")
                self.assertNotEqual(h.co._memory["initial_charge_window"].get("spent"), True)

    async def test_corrupt_future_or_wrong_scope_marker_fails_closed(self):
        for change in ("future", "deadline", "bad_type", "nonnumeric_time"):
            with self.subTest(change=change):
                h = setup()
                record = {"version": 1, "deadline": h.co._window(h.now)[3].isoformat(),
                          "at": h.now.timestamp(), "id": "synthetic", "spent": False}
                if change == "future":
                    record["at"] += 1
                elif change == "deadline":
                    record["deadline"] = (h.now+timedelta(days=2)).isoformat()
                elif change == "bad_type":
                    record["spent"] = "false"
                else:
                    record["at"] = "1"
                h.co._memory["initial_charge_window"] = record
                self.assertFalse(await h.co._grid_attempt(20, h.now.timestamp()))
                self.assertEqual(h.current_calls(), [])

    async def test_april_night_start_uses_march_winter_hour_for_legacy_history(self):
        h = setup("2026-04-01T02:07:00+02:00")
        previous_zero = (h.now-timedelta(days=1)).replace(hour=21, minute=45, second=0)
        legacy_zero(h, previous_zero.timestamp())
        self.assertFalse(h.co._new_initial_window_proven(h.now))
        self.assertTrue(h.co._initial_window_started(h.now))

    async def test_october_night_start_uses_september_summer_hour_for_legacy_history(self):
        h = setup("2026-10-01T02:07:00+02:00")
        previous_zero = (h.now-timedelta(days=1)).replace(hour=21, minute=45, second=0)
        legacy_zero(h, previous_zero.timestamp())
        self.assertTrue(h.co._new_initial_window_proven(h.now))
        self.assertFalse(h.co._initial_window_started(h.now))


if __name__ == "__main__":
    unittest.main()
