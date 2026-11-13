"""Exercise the real panel payload with coordinator output and stubbed HA API."""

from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from test_installable import C, load, CALENDAR
from test_websocket import POST_SAVE
from test_runtime import Harness
from test_single_phase_runtime import single_harness


def websocket_module():
    identity = lambda func: func
    return load("websocket.py", {
        **C, "HomeAssistantError": RuntimeError, "callback": identity,
        "vol": SimpleNamespace(Required=lambda key: key, Optional=lambda key: key,
                               In=lambda values: values, Any=lambda *values: values),
        "websocket_api": SimpleNamespace(websocket_command=lambda _schema: identity,
                                          require_admin=identity, async_response=identity),
        "DATA_APPEARANCE": "test_appearance", "DATA_UPDATES": "test_updates",
        "calendar_operators": CALENDAR.calendar_operators,
        "calendar_profiles": CALENDAR.calendar_profiles,
        "post_save_status": POST_SAVE.post_save_status,
        "cancel_all_post_save": POST_SAVE.cancel_all_post_save,
    })


class PanelPayload(unittest.TestCase):
    def setUp(self):
        self.module = websocket_module()
        self.payload = self.module["_payload"]

    def test_single_phase_hardware_limits_and_calendar_reach_real_payload(self):
        h = single_harness()
        h.hass.data = {}
        expected = h.co.options
        payload = self.payload(h.co)
        for key in ("hardware_profile", "effective_hardware_limits", "tariff_calendar"):
            self.assertEqual(payload["options"][key], expected[key], key)
        self.assertEqual(payload["options"]["hardware_profile"]["phases"], 1)
        self.assertEqual(payload["options"]["effective_hardware_limits"]["inverter_max_power_kw"], 5)
        self.assertEqual(len(payload["options"]["tariff_calendar"]["today"]), 6)
        self.assertEqual(payload["options"]["tariff_calendar"]["profile_id"], "legacy_g13")
        self.assertTrue(payload["options"]["tariff_calendar"]["runtime_allowed"])
        self.assertEqual(payload["mode"], h.co.mode)

    def test_custom_profile_and_existing_options_are_preserved(self):
        h = Harness(options={"inverter_max_power_kw": 9, "grid_import_limit_kw": 13.5})
        h.hass.data = {}
        payload = self.payload(h.co)
        self.assertEqual(payload["options"]["hardware_profile"]["phases"], 3)
        self.assertEqual(payload["options"]["effective_hardware_limits"]["inverter_max_power_kw"], 9)
        self.assertEqual(payload["options"]["grid_import_limit_kw"], 13.5)
        self.assertEqual(payload["options"]["effective_min_soc_percent"], h.co.options["effective_min_soc_percent"])
        self.assertEqual(payload["sources"], {**C["DEFAULT_SOURCES"], **h.co.options["sources"]})

    def test_unknown_or_secret_options_are_not_exposed_even_if_coordinator_returns_them(self):
        h = single_harness()
        options = {**h.co.options, "solcast": {"api_key": "synthetic-private-solcast-key"},
                   "internal_admin_token": "synthetic-private-admin-token",
                   "unknown_diagnostic_dump": {"password": "synthetic-private-password"}}
        before = deepcopy(options)

        class Facade:
            entry, mode, data = h.co.entry, h.co.mode, h.co.data
            effective_loads, loads_revision = h.co.effective_loads, h.co.loads_revision
            reads = 0

            @property
            def options(self):
                self.reads += 1
                return options

        coordinator = Facade()
        payload = self.payload(coordinator)
        rendered = json.dumps(payload)
        for secret in ("synthetic-private-solcast-key", "synthetic-private-admin-token", "synthetic-private-password"):
            self.assertNotIn(secret, rendered)
        for key in ("solcast", "internal_admin_token", "unknown_diagnostic_dump"):
            self.assertNotIn(key, payload["options"])
        self.assertEqual(options, before)
        self.assertEqual(coordinator.reads, 1)


class WebsocketStatus(unittest.IsolatedAsyncioTestCase):
    async def test_authenticated_status_contains_computed_options_and_report_stream(self):
        h = single_harness()
        stream = {"status": "connected", "providers": 1, "connected_providers": 1,
                  "bindings": 4, "verified_sources": 4}
        h.co.data = {"inputs": {"report_stream": stream}}
        h.hass.data = {C["DOMAIN"]: {h.co.entry.entry_id: h.co}}
        connection = SimpleNamespace(send_result=Mock(), send_error=Mock())
        module = websocket_module()
        await module["status"](h.hass, connection, {"id": 7, "type": "deye_ems/status"})
        connection.send_error.assert_not_called()
        message_id, payload = connection.send_result.call_args.args
        self.assertEqual(message_id, 7)
        self.assertEqual(payload["options"]["hardware_profile"]["phases"], 1)
        self.assertEqual(payload["options"]["tariff_calendar"]["profile_id"], "legacy_g13")
        self.assertEqual(payload["data"]["inputs"]["report_stream"], stream)


if __name__ == "__main__":
    unittest.main()
