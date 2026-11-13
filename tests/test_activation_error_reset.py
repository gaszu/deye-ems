"""Clear only a superseded startup diagnostic after durable explicit activation."""
import unittest

from test_runtime import Harness


class ActivationErrorReset(unittest.IsolatedAsyncioTestCase):
    async def test_successful_explicit_activation_clears_historical_startup_error(self):
        h = Harness()
        h.co._last_error = "restored_active_preflight_failed"
        await h.co.async_set_mode("active")
        self.assertEqual(h.co.mode, "active")
        self.assertEqual(h.store.saved["mode"], "active")
        self.assertIsNone(h.co._last_error)
        self.assertIsNone(h.co.data["error"])

    async def test_failed_preflight_keeps_historical_error_and_performs_no_save(self):
        h = Harness()
        h.co._last_error = "restored_active_preflight_failed"
        h.set("voltage", "unavailable", "V")
        with self.assertRaises(ValueError):
            await h.co.async_set_mode("active")
        self.assertEqual(h.co._last_error, "restored_active_preflight_failed")
        self.assertEqual(h.co.mode, "shadow")
        self.assertEqual(h.store.history, [])
        self.assertEqual(h.calls, [])

    async def test_failed_mode_save_does_not_clear_historical_error(self):
        h = Harness()
        h.co._last_error = "restored_active_preflight_failed"
        h.store.fail = True
        with self.assertRaises(OSError):
            await h.co.async_set_mode("active")
        self.assertEqual(h.co._last_error, "restored_active_preflight_failed")
        self.assertEqual(h.store.history, [])
        self.assertEqual(h.calls, [])

    async def test_other_errors_and_shadow_selection_are_not_cleared(self):
        h = Harness()
        h.co._last_error = "command_failed:OSError"
        await h.co.async_set_mode("active")
        self.assertEqual(h.co._last_error, "command_failed:OSError")
        h = Harness()
        h.co._last_error = "restored_active_preflight_failed"
        await h.co.async_set_mode("shadow")
        self.assertEqual(h.co._last_error, "restored_active_preflight_failed")
