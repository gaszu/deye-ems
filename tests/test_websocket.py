"""Offline checks for the HA 2026.11 WebSocket authorization boundary.

The real admin decorator is synchronous and raises Unauthorized before the
async-response wrapper schedules its coroutine. ActiveConnection has no
require_admin method; keep the stub limited to its actual handler interface.
"""
import ast
import asyncio
from functools import wraps
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


ROOT = Path(__file__).resolve().parents[1] / "custom_components/deye_ems"
CONSTANTS = {}
exec((ROOT / "const.py").read_text(encoding="utf-8"), CONSTANTS)


class Unauthorized(Exception):
    """The synchronous exception raised by HA's require_admin decorator."""


class HomeAssistantError(Exception):
    pass


class Connection:
    __slots__ = ("user", "results", "errors")

    def __init__(self, user):
        self.user = user
        self.results = []
        self.errors = []

    def send_result(self, message_id, payload):
        self.results.append((message_id, payload))

    def send_error(self, message_id, code, message):
        self.errors.append((message_id, code, message))


class Hass:
    def __init__(self, coordinator=None):
        self.data = {CONSTANTS["DOMAIN"]: {"entry": coordinator}} if coordinator else {}
        self.tasks = []
        self.scheduled = 0

    def async_create_task(self, coroutine):
        self.scheduled += 1
        task = asyncio.create_task(coroutine)
        self.tasks.append(task)
        return task

    async def drain(self):
        if self.tasks:
            await asyncio.gather(*self.tasks)


class API:
    def __init__(self):
        self.registered = []

    @staticmethod
    def websocket_command(schema):
        def decorate(func):
            func.schema = schema
            return func
        return decorate

    @staticmethod
    def require_admin(func):
        # HA Core 2026.11 decorators.py:49-64. This check must remain outside
        # async_response; placing it inside would schedule unauthorized work.
        @wraps(func)
        def with_admin(hass, connection, msg):
            user = connection.user
            if user is None or not user.is_admin:
                raise Unauthorized
            func(hass, connection, msg)
        return with_admin

    @staticmethod
    def async_response(func):
        @wraps(func)
        def schedule(hass, connection, msg):
            hass.async_create_task(func(hass, connection, msg))
        return schedule

    def async_register_command(self, hass, handler):
        self.registered.append(handler)


def load_module():
    api = API()
    values = {
        **CONSTANTS,
        "websocket_api": api,
        "callback": lambda func: func,
        "HomeAssistantError": HomeAssistantError,
        "vol": SimpleNamespace(
            Required=lambda key: key, Optional=lambda key: key,
            In=lambda values: values, Any=lambda *values: values),
    }
    tree = ast.parse((ROOT / "websocket.py").read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body
                 if not isinstance(node, (ast.Import, ast.ImportFrom))]
    exec(compile(tree, "websocket.py", "exec"), values)
    return values, api


def coordinator():
    return SimpleNamespace(
        mode="shadow", data={"status": "shadow", "inputs": {"soc": 65}},
        options={"min_soc_percent": 50, "sources": {"soc": "sensor.test_soc"},
                 "api_key": "synthetic-private-top-key",
                 "password": "synthetic-private-password",
                 "solcast": {"api_key": "synthetic-private-solcast-key"}},
        async_recalculate=AsyncMock(), async_set_mode=AsyncMock(),
        async_set_option=AsyncMock())


class WebSocketTests(unittest.IsolatedAsyncioTestCase):
    def test_handlers_declare_admin_check_before_async_response(self):
        tree = ast.parse((ROOT / "websocket.py").read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.AsyncFunctionDef) and node.name in ("status", "command"):
                names = [getattr(item.func if isinstance(item, ast.Call) else item, "attr", None)
                         for item in node.decorator_list]
                self.assertEqual(names, ["websocket_command", "require_admin", "async_response"])

    async def test_admin_reads_status_with_real_connection_interface(self):
        module, _ = load_module()
        co = coordinator()
        hass, connection = Hass(co), Connection(SimpleNamespace(is_admin=True))
        module["status"](hass, connection, {"id": 1, "type": "deye_ems/status"})
        await hass.drain()
        self.assertEqual(hass.scheduled, 1)
        self.assertEqual(connection.errors, [])
        self.assertEqual(connection.results[0][0], 1)
        self.assertEqual(connection.results[0][1]["data"]["inputs"]["soc"], 65)
        self.assertFalse(hasattr(connection, "require_admin"))
        co.async_recalculate.assert_not_awaited()
        co.async_set_mode.assert_not_awaited()
        co.async_set_option.assert_not_awaited()

    async def test_admin_commands_dispatch_only_the_selected_operation(self):
        for command, fields, method, arguments in (
            ("recalculate", {}, "async_recalculate", ()),
            ("mode", {"mode": "active"}, "async_set_mode", ("active",)),
            ("option", {"key": "min_soc_percent", "value": 55},
             "async_set_option", ("min_soc_percent", 55)),
        ):
            with self.subTest(command=command):
                module, _ = load_module()
                co = coordinator()
                hass, connection = Hass(co), Connection(SimpleNamespace(is_admin=True))
                module["command"](hass, connection, {
                    "id": 2, "type": "deye_ems/command", "command": command, **fields})
                await hass.drain()
                getattr(co, method).assert_awaited_once_with(*arguments)
                for other in ("async_recalculate", "async_set_mode", "async_set_option"):
                    if other != method:
                        getattr(co, other).assert_not_awaited()
                self.assertEqual(connection.errors, [])
                self.assertEqual(connection.results[0][0], 2)

    async def test_nonadmin_and_missing_user_are_rejected_before_lookup_or_scheduling(self):
        for user in (SimpleNamespace(is_admin=False), None):
            for handler, message in (
                ("status", {"id": 3, "type": "deye_ems/status"}),
                ("command", {"id": 4, "type": "deye_ems/command", "command": "recalculate"}),
                ("command", {"id": 5, "type": "deye_ems/command", "command": "mode", "mode": "active"}),
                ("command", {"id": 6, "type": "deye_ems/command", "command": "option",
                             "key": "min_soc_percent", "value": 55}),
            ):
                with self.subTest(admin=user is not None, handler=handler, message=message["id"]):
                    module, _ = load_module()
                    co = coordinator()
                    lookup = Mock(side_effect=AssertionError("Unauthorized coordinator lookup"))
                    module["_coordinator"] = lookup
                    hass, connection = Hass(co), Connection(user)
                    with self.assertRaises(Unauthorized):
                        module[handler](hass, connection, message)
                    lookup.assert_not_called()
                    self.assertEqual(hass.scheduled, 0)
                    self.assertEqual(hass.tasks, [])
                    self.assertEqual(connection.results, [])
                    self.assertEqual(connection.errors, [])
                    co.async_recalculate.assert_not_awaited()
                    co.async_set_mode.assert_not_awaited()
                    co.async_set_option.assert_not_awaited()

    async def test_admin_without_loaded_integration_receives_not_loaded(self):
        for handler, message in (
            ("status", {"id": 7, "type": "deye_ems/status"}),
            ("command", {"id": 8, "type": "deye_ems/command", "command": "recalculate"}),
        ):
            with self.subTest(handler=handler):
                module, _ = load_module()
                hass, connection = Hass(), Connection(SimpleNamespace(is_admin=True))
                module[handler](hass, connection, message)
                await hass.drain()
                self.assertEqual(connection.errors, [(message["id"], "not_loaded", "Deye EMS is not loaded")])
                self.assertEqual(connection.results, [])

    async def test_rejected_admin_command_returns_validation_error(self):
        module, _ = load_module()
        co = coordinator()
        co.async_set_option.side_effect = ValueError("Invalid option")
        hass, connection = Hass(co), Connection(SimpleNamespace(is_admin=True))
        module["command"](hass, connection, {
            "id": 9, "type": "deye_ems/command", "command": "option",
            "key": "min_soc_percent", "value": 99})
        await hass.drain()
        self.assertEqual(connection.errors, [(9, "invalid_request", "Invalid option")])
        self.assertEqual(connection.results, [])

    def test_payload_allowlist_omits_private_configuration(self):
        module, _ = load_module()
        co = coordinator()
        payload = module["_payload"](co)
        self.assertEqual(set(payload), {"mode", "data", "options", "sources"})
        self.assertEqual(set(payload["options"]), set(CONSTANTS["DEFAULT_OPTIONS"]))
        self.assertEqual(payload["options"]["min_soc_percent"], 50)
        self.assertEqual(payload["sources"]["soc"], "sensor.test_soc")
        serialized = json.dumps(payload)
        for private in ("synthetic-private", "api_key", "password"):
            self.assertNotIn(private, serialized)
        self.assertNotIn("solcast", payload["options"])
        self.assertIn("solcast", co.options)

    def test_registers_both_guarded_handlers(self):
        module, api = load_module()
        module["async_register"](Hass())
        self.assertEqual(api.registered, [module["status"], module["command"]])
