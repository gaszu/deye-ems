"""TOP BALANCE uses real coordinator guards with an offline inverter."""
from datetime import datetime
import unittest

from test_runtime import Harness, TZ


class TopBalance(unittest.IsolatedAsyncioTestCase):
    def prepare(self):
        h = Harness(when=datetime(2026, 11, 10, 17, tzinfo=TZ))
        h.set("tou_soc_5", 40, "%", attributes={"max": 100})
        h.active()
        return h

    async def test_protected_slot_charges_then_restores_at_100_percent(self):
        h = self.prepare()
        await h.co.async_set_top_balance(True, 100)
        for _ in range(6):
            h.advance(10)
            await h.tick()
        self.assertEqual(h.co._state("tou_gc_5").state, "on")
        self.assertEqual(float(h.co._state("tou_soc_5").state), 100)
        self.assertGreater(h.current_calls()[-1], 10)
        h.set("soc", 100, "%")
        for _ in range(6):
            h.advance(10)
            await h.tick()
        self.assertEqual(h.current_calls()[-1], 0)
        self.assertEqual(h.co._state("tou_gc_5").state, "off")
        self.assertEqual(float(h.co._state("tou_soc_5").state), 40)
        self.assertEqual(h.co._memory["top_balance"], {})

    async def test_rejects_goal_above_actuator_limit(self):
        h = self.prepare()
        h.set("tou_soc_5", 40, "%", attributes={"max": 95})
        with self.assertRaisesRegex(ValueError, "falownik"):
            await h.co.async_set_top_balance(True, 100)
        self.assertFalse(h.calls)

    async def test_manual_stop_recalculates_charge_from_live_soc(self):
        h = Harness(options={"winter_weather_soc_percent": 75})
        h.set("tou_soc_6", 95, "%", attributes={"max": 100})
        h.set("soc", 66, "%")
        h.active()
        await h.co.async_set_top_balance(True, 100)
        for _ in range(6):
            h.advance(10)
            await h.tick()
        self.assertEqual(h.co._state("tou_gc_6").state, "on")
        await h.co.async_set_top_balance(False)
        for _ in range(6):
            h.advance(10)
            await h.tick()
        self.assertEqual(h.co._memory["top_balance"], {})
        self.assertEqual(float(h.co._state("tou_soc_6").state), 95)
        self.assertLess(h.co.data["control"]["target_soc"], 100)
        h.advance(600)
        await h.tick()
        self.assertGreater(h.current_calls()[-1], 0)

    async def test_slot_transition_restores_old_slot_before_arming_new_one(self):
        h = Harness(when=datetime(2026, 11, 10, 20, 58, tzinfo=TZ))
        h.set("tou_soc_5", 40, "%", attributes={"max": 100})
        h.set("tou_soc_6", 95, "%", attributes={"max": 100})
        h.active()
        await h.co.async_set_top_balance(True, 100)
        for _ in range(6):
            h.advance(10)
            await h.tick()
        self.assertEqual(h.co._state("tou_gc_5").state, "on")
        h.advance(60)
        for _ in range(10):
            h.advance(10)
            await h.tick()
        self.assertEqual(h.co._state("tou_gc_5").state, "off")
        self.assertEqual(float(h.co._state("tou_soc_5").state), 40)
        self.assertEqual(h.co._state("tou_gc_6").state, "on")
        self.assertEqual(float(h.co._state("tou_soc_6").state), 100)
