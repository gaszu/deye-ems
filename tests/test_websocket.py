"""Offline checks for the HA 2026.11 WebSocket authorization boundary.

The real admin decorator is synchronous and raises Unauthorized before the
async-response wrapper schedules its coroutine. ActiveConnection has no
require_admin method; keep the stub limited to its actual handler interface.
"""
import ast
import asyncio
from copy import deepcopy
from functools import wraps
import json
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


ROOT = Path(__file__).resolve().parents[1] / "custom_components/deye_ems"
CONSTANTS = {}
exec((ROOT / "const.py").read_text(encoding="utf-8"), CONSTANTS)
from test_installable import CALENDAR
_post_spec = importlib.util.spec_from_file_location("offline_ws_post_save", ROOT / "post_save.py")
POST_SAVE = importlib.util.module_from_spec(_post_spec)
_post_spec.loader.exec_module(POST_SAVE)


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
            @wraps(func)
            def validated(hass, connection, msg):
                allowed = schema.get("value")
                if "value" in msg and isinstance(allowed, tuple) and not isinstance(msg["value"], allowed):
                    raise ValueError("invalid WebSocket value type")
                return func(hass, connection, msg)
            validated.schema = schema
            return validated
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
        "DATA_APPEARANCE": "deye_ems_appearance",
        "DATA_UPDATES": "deye_ems_updates",
        "calendar_operators": CALENDAR.calendar_operators,
        "calendar_profiles": CALENDAR.calendar_profiles,
        "post_save_status": POST_SAVE.post_save_status,
        "cancel_all_post_save": POST_SAVE.cancel_all_post_save,
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
        entry=SimpleNamespace(entry_id="synthetic-ems-entry"),
        mode="shadow", data={"status": "shadow", "inputs": {"soc": 65}},
        options={"min_soc_percent": 50, "sources": {"soc": "sensor.test_soc"},
                 "api_key": "synthetic-private-top-key",
                 "password": "synthetic-private-password",
                 "solcast": {"api_key": "synthetic-private-solcast-key"}},
        effective_loads=[], loads_revision="synthetic-load-revision",
        async_recalculate=AsyncMock(), async_set_mode=AsyncMock(),
        async_set_option=AsyncMock(), async_save_load=AsyncMock(), async_delete_load=AsyncMock(),
        async_toggle_load=AsyncMock())


class WebSocketTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_exposes_running_version_and_cached_updates_without_checking(self):
        module, _ = load_module()
        co = coordinator()
        hass, connection = Hass(co), Connection(SimpleNamespace(is_admin=True))
        cached = {"status": "available", "latest_version": "1.0.18", "checked_at": "2026-11-12T12:00:00+00:00",
                  "retry_at": None, "reason": None,
                  "release_url": "https://github.com/gaszu/deye-ems/releases/tag/v1.0.18",
                  "marketplace_url": "/marketplace"}

        class CachedUpdates:
            async_check = AsyncMock(side_effect=AssertionError("Polling must not query GitHub"))
            @property
            def status(self):
                return deepcopy(cached)

        manager = CachedUpdates()
        hass.data[module["DATA_UPDATES"]] = manager
        for message_id in (30, 31):
            module["status"](hass, connection, {"id": message_id, "type": "deye_ems/status"})
            await hass.drain()
            payload = connection.results[-1][1]
            self.assertEqual(payload["backend_version"], CONSTANTS["VERSION"])
            self.assertEqual(payload["updates"], cached)
            payload["updates"]["latest_version"] = "changed-client-copy"
        self.assertEqual(cached["latest_version"], "1.0.18")
        manager.async_check.assert_not_awaited()
        for method in ("async_recalculate", "async_set_mode", "async_set_option",
                       "async_save_load", "async_delete_load", "async_toggle_load"):
            getattr(co, method).assert_not_awaited()

    async def test_explicit_update_check_in_active_mode_does_not_touch_energy_engine(self):
        module, _ = load_module()
        co = coordinator()
        co.mode = "active"
        hass, connection = Hass(co), Connection(SimpleNamespace(is_admin=True))
        hass.services = SimpleNamespace(async_call=AsyncMock(side_effect=AssertionError("No hardware service")))
        updates = SimpleNamespace(status={"status": "not_checked", "latest_version": None})
        async def checked():
            updates.status = {"status": "available", "latest_version": "1.0.18"}
        updates.async_check = AsyncMock(side_effect=checked)
        hass.data[module["DATA_UPDATES"]] = updates
        before = deepcopy(co.options)
        module["command"](hass, connection, {"id": 32, "type": "deye_ems/command", "command": "check_updates"})
        await hass.drain()
        updates.async_check.assert_awaited_once_with()
        self.assertEqual(connection.errors, [])
        self.assertEqual(connection.results[0][1]["updates"], updates.status)
        self.assertEqual(connection.results[0][1]["backend_version"], CONSTANTS["VERSION"])
        self.assertEqual(connection.results[0][1]["mode"], "active")
        self.assertEqual(co.options, before)
        hass.services.async_call.assert_not_awaited()
        for method in ("async_recalculate", "async_set_mode", "async_set_option",
                       "async_save_load", "async_delete_load", "async_toggle_load"):
            getattr(co, method).assert_not_awaited()

    async def test_update_check_missing_manager_returns_safe_error_without_engine_work(self):
        module, _ = load_module()
        co = coordinator()
        hass, connection = Hass(co), Connection(SimpleNamespace(is_admin=True))
        module["command"](hass, connection, {"id": 33, "type": "deye_ems/command", "command": "check_updates"})
        await hass.drain()
        self.assertEqual(connection.results, [])
        self.assertEqual(connection.errors, [(33, "invalid_request", "Sprawdzanie aktualizacji nie jest jeszcze dostępne. Odśwież panel.")])
        self.assertEqual(co.mode, "shadow")
        co.async_recalculate.assert_not_awaited()
        co.async_set_mode.assert_not_awaited()
        co.async_set_option.assert_not_awaited()

    async def test_update_check_unexpected_failure_never_echoes_exception_or_provider_details(self):
        module, _ = load_module()
        co = coordinator()
        hass, connection = Hass(co), Connection(SimpleNamespace(is_admin=True))
        updates = SimpleNamespace(status={"status": "not_checked"},
            async_check=AsyncMock(side_effect=RuntimeError("private-token-provider-body-unexpected")))
        hass.data[module["DATA_UPDATES"]] = updates
        module["command"](hass, connection, {"id": 34, "type": "deye_ems/command", "command": "check_updates"})
        await hass.drain()
        self.assertEqual(connection.results, [])
        self.assertEqual(connection.errors, [(34, "update_check_failed", "Nie udało się sprawdzić aktualizacji.")])
        self.assertNotIn("private-token", repr(connection.errors))
        self.assertEqual(co.mode, "shadow")

    def test_missing_update_manager_is_not_an_assertion_that_software_is_current(self):
        module, _ = load_module()
        payload = module["_payload"](coordinator())
        self.assertEqual(payload["backend_version"], CONSTANTS["VERSION"])
        self.assertEqual(payload["updates"]["status"], "not_checked")
        self.assertIsNone(payload["updates"]["latest_version"])
        self.assertIsNone(payload["updates"]["checked_at"])
        self.assertEqual(payload["updates"]["marketplace_url"], "/marketplace")

    async def test_topology_strings_pass_wire_validation_and_reach_coordinator(self):
        for value in ("load_only", "load_with_external_ct"):
            module, _ = load_module()
            co = coordinator()
            hass, connection = Hass(co), Connection(SimpleNamespace(is_admin=True))
            module["command"](hass, connection, {"id": 10, "type": "deye_ems/command",
                "command": "option", "key": "topology", "value": value})
            await hass.drain()
            co.async_set_option.assert_awaited_once_with("topology", value)
            self.assertEqual(connection.errors, [])

    def test_object_values_remain_rejected_before_dispatch(self):
        module, _ = load_module()
        hass, connection = Hass(coordinator()), Connection(SimpleNamespace(is_admin=True))
        with self.assertRaises(ValueError):
            module["command"](hass, connection, {"id": 11, "type": "deye_ems/command",
                "command": "option", "key": "topology", "value": {"unexpected": True}})
        self.assertEqual(hass.scheduled, 0)

    def test_dynamic_soc_limits_reach_panel_without_private_options(self):
        module, _ = load_module()
        co = coordinator()
        co.options.update(min_soc_lower_bound=15, min_soc_bound_valid=True,
                          effective_min_soc_percent=15)
        payload = module["_payload"](co)
        self.assertEqual(payload["options"]["min_soc_lower_bound"], 15)
        self.assertTrue(payload["options"]["min_soc_bound_valid"])
        self.assertEqual(payload["options"]["effective_min_soc_percent"], 15)
        self.assertNotIn("api_key", payload["options"])
        self.assertNotIn("solcast", payload["options"])

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
        self.assertEqual(connection.results[0][1]["entry_id"], "synthetic-ems-entry")
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
                ("command", {"id": 10, "type": "deye_ems/command", "command": "load_save",
                             "original_energy_entity": "", "channel": {}, "expected_loads_revision": "old"}),
                ("command", {"id": 11, "type": "deye_ems/command", "command": "load_delete",
                             "original_energy_entity": "sensor.test", "expected_loads_revision": "old"}),
                ("command", {"id": 13, "type": "deye_ems/command", "command": "load_toggle",
                             "original_energy_entity": "sensor.test", "enabled": False,
                             "expected_loads_revision": "old"}),
                ("command", {"id": 14, "type": "deye_ems/command", "command": "appearance",
                             "theme": "synthetic-night"}),
                ("command", {"id": 15, "type": "deye_ems/command", "command": "check_updates"}),
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
                    co.async_save_load.assert_not_awaited()
                    co.async_delete_load.assert_not_awaited()
                    co.async_toggle_load.assert_not_awaited()

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
        self.assertEqual(set(payload), {"entry_id", "mode", "data", "options", "sources", "effective_loads", "loads_revision", "appearance", "backend_version", "updates", "post_save_activation"})
        self.assertEqual(payload["appearance"], {"theme": ""})
        self.assertEqual(set(payload["options"]), set(CONSTANTS["DEFAULT_OPTIONS"]) | {
            "effective_min_soc_percent", "min_soc_bound_valid", "min_soc_lower_bound",
            "hardware_profile", "effective_hardware_limits", "tariff_calendar", "physical_tou"})
        self.assertEqual(payload["options"]["min_soc_percent"], 50)
        self.assertEqual(payload["sources"]["soc"], "sensor.test_soc")
        serialized = json.dumps(payload)
        for private in ("synthetic-private", "api_key", "password"):
            self.assertNotIn(private, serialized)
        self.assertNotIn("solcast", payload["options"])
        self.assertIn("solcast", co.options)

    async def test_admin_load_commands_forward_revision_and_return_current_list(self):
        for command in ("load_save", "load_delete", "load_toggle"):
            with self.subTest(command=command):
                module, _ = load_module()
                co = coordinator()
                channel = {"name": "CWU", "energy_entity": "sensor.cwu_energy",
                           "power_entity": "", "included_in_load": True}
                async def changed(*args, **kwargs):
                    co.effective_loads = [channel] if command == "load_save" else []
                    co.loads_revision = "new-revision"
                method = {"load_save": co.async_save_load, "load_delete": co.async_delete_load,
                          "load_toggle": co.async_toggle_load}[command]
                method.side_effect = changed
                hass, connection = Hass(co), Connection(SimpleNamespace(is_admin=True))
                module["command"](hass, connection, {
                    "id": 12, "type": "deye_ems/command", "command": command,
                    "original_energy_entity": "sensor.original", "channel": channel,
                    "expected_loads_revision": "old-revision", "enabled": False})
                await hass.drain()
                if command == "load_save":
                    method.assert_awaited_once_with("sensor.original", channel, expected_revision="old-revision")
                elif command == "load_delete":
                    method.assert_awaited_once_with("sensor.original", expected_revision="old-revision")
                else:
                    method.assert_awaited_once_with("sensor.original", False, expected_revision="old-revision")
                self.assertEqual(connection.errors, [])
                self.assertEqual(connection.results[0][1]["effective_loads"], co.effective_loads)
                self.assertEqual(connection.results[0][1]["loads_revision"], "new-revision")

    def test_registers_all_guarded_handlers(self):
        module, api = load_module()
        module["async_register"](Hass())
        self.assertEqual(api.registered, [module["status"], module["command"], module["tariff_catalog"]])

    async def test_tariff_catalog_admin_reads_only_embedded_five_operator_rules(self):
        module, _ = load_module()
        hass, connection = Hass(), Connection(SimpleNamespace(is_admin=True))
        module["tariff_catalog"](hass, connection, {"id": 15, "type": "deye_ems/tariff_catalog"})
        await hass.drain()
        result = connection.results[0][1]
        self.assertEqual(result["backend_version"], CONSTANTS["VERSION"])
        self.assertEqual({row["operator_id"] for row in result["operators"]},
            {"custom", "pge_dystrybucja", "tauron_dystrybucja", "enea_operator",
             "energa_operator", "pge_energetyka_kolejowa"})
        self.assertTrue(any(row["profile_id"] == "tauron_g13_2026" for row in result["profiles"]))
        self.assertNotIn("stoen", json.dumps(result).lower())
        self.assertEqual(hass.data, {})

    async def test_tariff_catalog_nonadmin_cannot_schedule_work(self):
        module, _ = load_module()
        hass = Hass()
        for user in (None, SimpleNamespace(is_admin=False)):
            with self.assertRaises(Unauthorized):
                module["tariff_catalog"](hass, Connection(user), {"id": 2, "type": "deye_ems/tariff_catalog"})
        self.assertEqual(hass.scheduled, 0)

    async def test_manual_stop_cancels_intent_even_during_empty_coordinator_reload(self):
        module, _ = load_module()
        hass, connection = Hass(), Connection(SimpleNamespace(is_admin=True))
        manager = SimpleNamespace(cancel_all=Mock())
        hass.data[POST_SAVE.DATA_POST_SAVE] = manager
        module["command"](hass, connection, {"id": 3, "type": "deye_ems/command", "command": "mode", "mode": "shadow"})
        await hass.drain()
        manager.cancel_all.assert_called_once()
        self.assertEqual(connection.errors[0][1], "not_loaded")

    async def test_appearance_changes_in_active_mode_without_energy_engine_calls(self):
        module, _ = load_module()
        co = coordinator()
        co.mode = "active"
        hass, connection = Hass(co), Connection(SimpleNamespace(is_admin=True))
        appearance = SimpleNamespace(appearance={"theme": ""})
        async def save(theme):
            appearance.appearance = {"theme": theme}
        appearance.async_set_theme = AsyncMock(side_effect=save)
        hass.data[module["DATA_APPEARANCE"]] = appearance
        before = json.dumps(co.options, sort_keys=True)
        for message_id, theme in ((20, "synthetic-night"), (21, "")):
            module["command"](hass, connection, {"id": message_id, "type": "deye_ems/command",
                "command": "appearance", "theme": theme})
            await hass.drain()
            self.assertEqual(connection.results[-1][1]["appearance"], {"theme": theme})
            self.assertEqual(connection.results[-1][1]["mode"], "active")
        module["status"](hass, connection, {"id": 22, "type": "deye_ems/status"})
        await hass.drain()
        self.assertEqual(connection.results[-1][1]["appearance"], {"theme": ""})
        self.assertEqual(connection.errors, [])
        self.assertEqual(json.dumps(co.options, sort_keys=True), before)
        for method in ("async_recalculate", "async_set_mode", "async_set_option",
                       "async_save_load", "async_delete_load", "async_toggle_load"):
            getattr(co, method).assert_not_awaited()

    async def test_appearance_validation_and_save_errors_do_not_publish_success(self):
        for error in (ValueError("Unknown theme"), HomeAssistantError("Save failed")):
            with self.subTest(error=type(error).__name__):
                module, _ = load_module()
                co = coordinator()
                hass, connection = Hass(co), Connection(SimpleNamespace(is_admin=True))
                appearance = SimpleNamespace(appearance={"theme": "synthetic-night"},
                    async_set_theme=AsyncMock(side_effect=error))
                hass.data[module["DATA_APPEARANCE"]] = appearance
                module["command"](hass, connection, {"id": 23, "type": "deye_ems/command",
                    "command": "appearance", "theme": "unknown-theme"})
                await hass.drain()
                self.assertEqual(connection.results, [])
                self.assertEqual(connection.errors, [(23, "invalid_request", str(error))])
                self.assertEqual(appearance.appearance, {"theme": "synthetic-night"})
                co.async_set_option.assert_not_awaited()
