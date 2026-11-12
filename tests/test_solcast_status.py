"""The API counter projection reveals no credentials and performs no HTTP."""
from copy import deepcopy
import json
import unittest
from unittest.mock import AsyncMock

from test_runtime import Harness


class SolcastStatus(unittest.IsolatedAsyncioTestCase):
    async def test_enabled_counter_is_read_only_and_key_is_never_in_status(self):
        key = "synthetic-private-api-key"
        h = Harness(options={"solcast": {"api_key": key, "enabled": True}})
        h.co._solcast_fetcher = AsyncMock(side_effect=AssertionError("Unexpected HTTP"))
        h.co._solcast_status = {"status": "unavailable", "reason": "daily_quota_exhausted",
            "quota": {"limit": 8, "utc": {"day": "2026-11-10", "used": 8}}}
        h.co._memory["solcast_cache"] = {"quota": {"utc": {"day": "2026-11-10", "used": 8}}}
        before = deepcopy(h.co._memory["solcast_cache"])
        first, second = await h.tick(), await h.tick()
        self.assertEqual(first["solcast"], second["solcast"])
        self.assertTrue(second["solcast"]["api_configured"])
        self.assertTrue(second["solcast"]["api_enabled"])
        self.assertEqual(second["solcast"]["quota"]["utc"]["used"], 8)
        self.assertNotIn(key, json.dumps(second))
        self.assertEqual(h.co._memory["solcast_cache"], before)
        h.co._solcast_fetcher.assert_not_awaited()
        self.assertEqual(h.calls, [])

    async def test_disabled_api_is_distinct_from_unconfigured_api(self):
        for configured in (False, True):
            with self.subTest(configured=configured):
                cfg = {"api_key": "synthetic-key", "enabled": False} if configured else {}
                h = Harness(options={"solcast": cfg})
                h.co._solcast_status = {"status": "ha_entities", "configured": False}
                status = (await h.tick())["solcast"]
                self.assertEqual(status["api_configured"], configured)
                self.assertFalse(status["api_enabled"])
                self.assertNotIn("quota", status)
                self.assertNotIn("api_key", status)

    async def test_initializing_or_failed_client_does_not_invent_a_counter(self):
        h = Harness(options={"solcast": {"api_key": "synthetic-key"}})
        h.co._solcast_status = {"status": "unavailable", "reason": "quota_store_failed"}
        status = (await h.tick())["solcast"]
        self.assertTrue(status["api_enabled"])
        self.assertNotIn("quota", status)
