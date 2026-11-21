import unittest
from unittest.mock import AsyncMock

from test_runtime import Harness


class StartupControl(unittest.IsolatedAsyncioTestCase):
    async def test_saved_active_waits_without_writes_then_recovers_automatically(self):
        h = Harness()
        h.store.saved = {"mode": "active"}
        h.set("voltage", "unavailable", "V")
        h.co._run_driver = AsyncMock()
        await h.co.async_initialize()
        await h.co.async_request_refresh()
        self.assertEqual(h.co.mode, "active")
        self.assertEqual(h.store.saved["mode"], "active")
        self.assertFalse(h.co.data["owner"]["active"])
        self.assertEqual(h.co.data["status"], "waiting_for_startup_control")
        self.assertTrue(h.co.data["startup_control_issue"])
        self.assertFalse(await h.co._service(h.co._sources["grid_current_number"], "set_value", 10))
        self.assertEqual(h.calls, [])
        h.co._run_driver.assert_not_awaited()

        h.set("voltage", 54, "V")
        await h.co.async_request_refresh()
        self.assertEqual(h.co.mode, "active")
        self.assertTrue(h.co.data["owner"]["active"])
        self.assertIsNone(h.co.data["startup_control_issue"])
        h.co._run_driver.assert_awaited_once()

    async def test_manual_stop_cancels_startup_resume_and_survives_restart(self):
        h = Harness()
        h.store.saved = {"mode": "active"}
        h.set("voltage", "unavailable", "V")
        await h.co.async_initialize()
        await h.co.async_set_mode("shadow")
        h.set("voltage", 54, "V")
        await h.co.async_initialize()
        await h.co.async_request_refresh()
        self.assertEqual(h.co.mode, "shadow")
        self.assertEqual(h.store.saved["mode"], "shadow")
        self.assertFalse(h.co.data["owner"]["active"])
        self.assertEqual(h.calls, [])
