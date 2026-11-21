import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from test_runtime import Harness


class StartupPlanningInputs(unittest.IsolatedAsyncioTestCase):
    async def test_startup_waits_for_valid_current_limit(self):
        h = Harness()
        h.set("max_charge_current_number", "unavailable", "A")
        await h.co.async_initialize()
        previous = h.co._memory["plan"]

        async def report_current(delay):
            self.assertEqual(delay, 5)
            self.assertTrue(h.co._waiting_for_plan_inputs)
            self.assertIs(h.co._memory["plan"], previous)
            self.assertIn("max_charge_current_number", {
                issue["source"] for issue in h.co._last_telemetry_fault["issues"]})
            h.set("max_charge_current_number", 120, "A")

        with patch.object(asyncio, "sleep", AsyncMock(side_effect=report_current)) as retry:
            inputs = await h.co._read_planning_inputs()
        retry.assert_awaited_once()
        self.assertEqual(inputs["deye_max_charge_current_a"], 120)
        self.assertFalse(h.co._waiting_for_plan_inputs)
        self.assertEqual(h.calls, [])

    async def test_expired_startup_window_returns_invalid_snapshot_without_waiting(self):
        h = Harness()
        h.set("max_charge_current_number", "unavailable", "A")
        await h.co.async_initialize()

        async def reach_deadline(delay):
            h.co._startup_plan_deadline = asyncio.get_running_loop().time()

        with patch.object(asyncio, "sleep", AsyncMock(side_effect=reach_deadline)) as retry:
            inputs = await h.co._read_planning_inputs()
            await h.co._read_planning_inputs()
        retry.assert_awaited_once()
        self.assertFalse(inputs["telemetry_valid"])
        self.assertFalse(h.co._waiting_for_plan_inputs)
        self.assertEqual(h.calls, [])
