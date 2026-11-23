"""User-requested 10 A / 600 s ramps with real controller and mocked I/O."""
from copy import deepcopy
import unittest
from test_scheduled_current import snapshot, calculate_grid_charge, update_policy
from test_runtime import Harness, SOURCES


def dispatch(g, amps):
    g.update(current_a=amps, last_attempt_a=amps, last_attempt_ts=g["now_ts"],
             ordinary_last_possible_ts=g["now_ts"],
             ordinary_last_positive_possible_ts=g["now_ts"], pending_current_a=None)


def observe(g, seconds=0):
    g["now_ts"] += seconds
    g["current_policy"] = update_policy(g, g.get("current_policy", {}))


class OrdinaryRamp(unittest.TestCase):
    def test_increase_is_ten_amps_per_600_seconds(self):
        g = snapshot(soc=40, target_soc=90, capacity_kwh=100, remaining_h=3)
        for expected in (10, 20, 30, 40):
            observe(g)
            out = calculate_grid_charge(g)
            self.assertTrue(out["write"])
            self.assertEqual(out["next_a"], expected)
            dispatch(g, expected)
            observe(g, 599)
            self.assertFalse(calculate_grid_charge(g)["write"])
            observe(g, 1)

    def test_target_tapers_without_raising_software_target(self):
        g = snapshot(soc=86, target_soc=85, current_a=40, last_attempt_a=40,
                     last_attempt_ts=1, ordinary_last_possible_ts=1,
                     grid_charge_active=True, grid_max_soc_percent=95)
        for expected in (30, 20, 10, 0):
            observe(g)
            out = calculate_grid_charge(g)
            self.assertFalse(out["safety"])
            self.assertTrue(out["write"])
            self.assertEqual(out["next_a"], expected)
            self.assertEqual(g["target_soc"], 85)
            dispatch(g, expected)
            if expected:
                observe(g, 599)
                held = calculate_grid_charge(g)
                self.assertFalse(held["write"])
                self.assertEqual(held["next_a"], expected)
                observe(g, 1)
        g["grid_charge_active"] = False
        observe(g, 600)
        self.assertEqual(calculate_grid_charge(g)["next_a"], 0)

    def test_sudden_cap_drop_is_immediate_and_recovery_keeps_ordinary_clock(self):
        g = snapshot(soc=40, current_a=60, last_attempt_a=60, bms_cap_a=15)
        g["ordinary_last_positive_possible_ts"] = g["now_ts"]-300
        observe(g)
        low = calculate_grid_charge(g)
        self.assertTrue(low["safety"])
        self.assertLessEqual(low["next_a"], 15)
        ordinary_at = g["ordinary_last_positive_possible_ts"]
        g.update(current_a=low["next_a"], last_attempt_a=low["next_a"],
                 last_attempt_ts=g["now_ts"], ordinary_last_possible_ts=g["now_ts"], bms_cap_a=108)
        observe(g, 299)
        self.assertFalse(calculate_grid_charge(g)["write"])
        observe(g, 1)
        resumed = calculate_grid_charge(g)
        self.assertTrue(resumed["write"])
        self.assertGreater(resumed["next_a"], low["next_a"])
        self.assertLessEqual(resumed["next_a"]-low["next_a"], 10)
        self.assertEqual(g["ordinary_last_positive_possible_ts"], ordinary_at)

    def test_hard_ceiling_bad_data_or_window_end_stops_immediately(self):
        g = snapshot(soc=86, target_soc=85, current_a=40, last_attempt_a=40,
                     grid_charge_active=True)
        observe(g)
        for changes in ({"soc": 95}, {"telemetry_valid": False},
                        {"cheap_window": False}, {"bms_cap_a": 0}):
            with self.subTest(changes=changes):
                out = calculate_grid_charge({**g, **changes})
                self.assertTrue(out["safety"])
                self.assertEqual(out["next_a"], 0)


class RampRuntime(unittest.IsolatedAsyncioTestCase):
    async def test_start_increase_taper_and_zero_keep_gc_continuous(self):
        h = Harness(options={"winter_weather_soc_percent": 85})
        h.active()
        for expected in (10, 20, 30, 40):
            await h.tick()
            self.assertEqual(h.current_calls()[-1], expected)
            h.advance(10)
            await h.tick()
            self.assertEqual(h.states[SOURCES["tou_gc_6"]].state, "on")
            self.assertEqual(float(h.states[SOURCES["tou_soc_6"]].state), 95)
            h.advance(590)
        h.set("soc", 86, "%")
        for expected in (30, 20, 10, 0):
            await h.tick()
            self.assertEqual(h.current_calls()[-1], expected)
            self.assertEqual(h.states[SOURCES["tou_gc_6"]].state, "on" if expected else "off")
            self.assertEqual(h.co.data["control"]["target_soc"], 85)
            if expected:
                h.advance(10)
                await h.tick()
                self.assertEqual(h.states[SOURCES["tou_gc_6"]].state, "on")
                h.advance(590)

    async def test_tou_ceiling_does_not_become_tariff_fallback_target(self):
        h = Harness(options={"winter_weather_soc_percent": 75,
            "tariff_profile": "tauron_g13_2026", "tariff_clock_basis": "local",
            "tariff_contract_confirmed": True})
        for slot in (1, 2, 4, 6):
            h.set(f"tou_soc_{slot}", 95, "%")
        self.assertEqual(h.co._target(h.now)[0], 75)

    async def test_last_moment_changed_readback_cannot_turn_step_into_large_jump(self):
        h = Harness(options={"winter_weather_soc_percent": 85})
        h.active()
        await h.tick()
        h.advance(10)
        await h.tick()
        h.advance(590)
        h.store.on_save = lambda: h.set("grid_current_number", 0, "A")
        await h.tick()
        self.assertEqual(h.current_calls(), [10])
        self.assertEqual(h.co._last_error, "last_moment_dispatch_guard")
        h.store.on_save = None
        h.set("grid_current_number", 10, "A")
        h.set("tou_gc_6", "on")
        h.advance(10)
        await h.tick()
        self.assertEqual(h.co.data["error"], "last_moment_dispatch_guard")
        h.advance(590)
        await h.tick()
        self.assertEqual(h.current_calls(), [10, 20])
        self.assertEqual(h.co.data["error"], "last_moment_dispatch_guard")
        h.advance(10)
        await h.tick()
        self.assertIsNone(h.co.data["error"])
