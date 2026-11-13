"""Post-save intent races and lifecycle; no HA server, network or hardware."""
import asyncio
import ast
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock


ROOT = Path(__file__).parents[1] / "custom_components/deye_ems"
SPEC = importlib.util.spec_from_file_location("offline_post_save", ROOT / "post_save.py")
POST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(POST)


class Authority:
    def __init__(self, verdicts=None):
        self.mode = "shadow"
        self.verdicts = list(verdicts or [{"ready": True, "recalculated": True}])
        self.recalculations = []
        self.activations = 0
        self.prepare_hook = None
        self.activation_hook = None

    async def async_prepare_activation(self, *, recalculate=True):
        self.recalculations.append(recalculate)
        if self.prepare_hook:
            await self.prepare_hook()
        return self.verdicts.pop(0) if len(self.verdicts) > 1 else self.verdicts[0]

    async def async_set_mode(self, mode, *, activation_guard=None):
        self.activations += 1
        if not activation_guard():
            raise ValueError("activation cancelled")
        if self.activation_hook:
            await self.activation_hook()
        # Simulates the public authority's guard after a durable write.
        self.mode = mode if activation_guard() else "shadow"


class Harness:
    def __init__(self, *, timeout=20):
        self.elapsed = 0
        self.old = Authority()
        self.entry = SimpleNamespace(entry_id="synthetic", data={"name": "synthetic"},
            options={"solcast": {"api_key": "synthetic-private-secret"}},
            runtime_data=self.old, state=SimpleNamespace(value="loaded"), disabled_by=None)
        self.entries = {self.entry.entry_id: self.entry}
        self.hass = SimpleNamespace(data={}, config_entries=SimpleNamespace(async_get_entry=self.entries.get))
        self.manager = POST.PostSaveActivationManager(self.hass, monotonic=lambda: self.elapsed,
            utcnow=lambda: datetime(2026, 11, 13, tzinfo=timezone.utc) + timedelta(seconds=self.elapsed),
            sleep=self.sleep, timeout_seconds=timeout, interval_seconds=5)
        self.hass.data[POST.DATA_POST_SAVE] = self.manager

    async def sleep(self, seconds):
        self.elapsed += seconds
        await asyncio.sleep(0)

    def start(self, authority=None):
        ticket = self.manager.begin(self.entry)
        self.entry.runtime_data = authority or Authority()
        self.manager.after_reload(ticket, True)
        return ticket

    async def finish(self, ticket):
        if ticket.task:
            await ticket.task
        return self.manager.get_status(self.entry.entry_id)


class PostSaveTests(unittest.IsolatedAsyncioTestCase):
    async def test_success_uses_new_coordinator_prepare_and_guarded_normal_activation(self):
        h = Harness()
        ticket = h.start()
        co = h.entry.runtime_data
        status = await h.finish(ticket)
        self.assertEqual(status["status"], "active")
        self.assertEqual(status["reason"], "activation_completed")
        self.assertEqual(co.recalculations, [True])
        self.assertEqual(co.activations, 1)
        self.assertEqual(h.old.activations, 0)

    async def test_fresh_measurements_then_one_recalculation_then_existing_plan_checks(self):
        co = Authority([{"ready": False, "reason": "waiting_for_measurements", "recalculated": False},
                        {"ready": False, "reason": "waiting_for_plan", "recalculated": True},
                        {"ready": True, "recalculated": False}])
        h = Harness()
        status = await h.finish(h.start(co))
        self.assertEqual(status["status"], "active")
        self.assertEqual(co.recalculations, [True, True, False])

    async def test_old_runtime_is_never_activated_when_reload_did_not_replace_it(self):
        h = Harness(timeout=10)
        ticket = h.manager.begin(h.entry)
        h.manager.after_reload(ticket, True)
        status = await h.finish(ticket)
        self.assertEqual(status["status"], "blocked")
        self.assertEqual(status["reason"], "waiting_for_reload")
        self.assertEqual(h.old.activations, 0)

    async def test_failed_reload_has_no_job_or_activation(self):
        for result in (False, None, 1):
            h = Harness()
            ticket = h.manager.begin(h.entry)
            h.manager.after_reload(ticket, result)
            self.assertIsNone(ticket.task)
            self.assertEqual(h.manager.get_status("synthetic")["reason"], "configuration_reload_failed")

    async def test_wait_timeout_is_bounded_and_does_not_grant_mode(self):
        h = Harness(timeout=12)
        co = Authority([{"ready": False, "reason": "waiting_for_plan", "recalculated": True}])
        status = await h.finish(h.start(co))
        self.assertEqual(status["status"], "blocked")
        self.assertEqual(status["reason"], "waiting_for_plan")
        self.assertLessEqual(h.elapsed, 15)
        self.assertEqual(co.activations, 0)

    async def test_manual_stop_during_prepare_synchronously_revokes_intent(self):
        h = Harness()
        entered, release = asyncio.Event(), asyncio.Event()
        co = Authority()
        async def pause():
            entered.set()
            await release.wait()
        co.prepare_hook = pause
        ticket = h.start(co)
        await entered.wait()
        POST.cancel_post_save(h.hass, "synthetic", "manual_stop")
        self.assertEqual(h.manager.get_status("synthetic")["status"], "cancelled")
        self.assertFalse(ticket.task.cancelled())
        release.set()
        await h.finish(ticket)
        self.assertEqual(co.activations, 0)

    async def test_manual_stop_while_mode_store_in_flight_is_not_task_cancellation(self):
        h = Harness()
        entered, release = asyncio.Event(), asyncio.Event()
        co = Authority()
        async def pause():
            entered.set()
            await release.wait()
        co.activation_hook = pause
        ticket = h.start(co)
        await entered.wait()
        POST.cancel_post_save(h.hass, "synthetic")
        self.assertFalse(ticket.task.cancelled())
        release.set()
        status = await h.finish(ticket)
        self.assertEqual(co.mode, "shadow")
        self.assertEqual(status["status"], "cancelled")

    async def test_new_save_revokes_old_generation_without_overwriting_new_status(self):
        h = Harness()
        entered, release = asyncio.Event(), asyncio.Event()
        old_job_co = Authority()
        async def pause():
            entered.set()
            await release.wait()
        old_job_co.prepare_hook = pause
        old_ticket = h.start(old_job_co)
        await entered.wait()
        h.entry.options = {**h.entry.options, "capacity_kwh": 20}
        new_ticket = h.manager.begin(h.entry)
        new_co = Authority()
        h.entry.runtime_data = new_co
        h.manager.after_reload(new_ticket, True)
        await h.finish(new_ticket)
        release.set()
        await h.finish(old_ticket)
        self.assertEqual(h.manager.get_status("synthetic")["status"], "active")
        self.assertEqual(old_job_co.activations, 0)
        self.assertEqual(new_co.activations, 1)

    async def test_options_changed_without_new_job_cannot_activate_old_fingerprint(self):
        h = Harness()
        ticket = h.start()
        h.entry.options["capacity_kwh"] = 99
        status = await h.finish(ticket)
        self.assertEqual(status["status"], "cancelled")
        self.assertEqual(status["reason"], "configuration_changed")
        self.assertEqual(h.entry.runtime_data.activations, 0)

    async def test_removed_or_disabled_entry_invalidates_intent_while_loaded_state_lingers(self):
        for remove in (False, True):
            h = Harness()
            ticket = h.start()
            if remove:
                h.entries.clear()
            else:
                h.entry.disabled_by = "user"
            status = await h.finish(ticket)
            self.assertEqual(status["status"], "cancelled")
            self.assertEqual(h.entry.runtime_data.activations, 0)

    async def test_status_sanitizes_issues_and_never_includes_configuration_or_exception(self):
        co = Authority([{"ready": False, "reason": "waiting_for_measurements", "issues": [
            {"source": "voltage", "reason": "stale", "value": "synthetic-private-secret"},
            {"source": "sensor.synthetic_private_secret", "reason": "missing"},
            {"source": "soc", "reason": "synthetic-private-secret"}]}])
        h = Harness(timeout=5)
        status = await h.finish(h.start(co))
        self.assertEqual(status["issues"], [{"source": "voltage", "reason": "stale"}])
        self.assertEqual(set(status), {"status", "reason", "issues", "updated_at", "plan_source", "plan_reason"})
        self.assertNotIn("synthetic-private-secret", json.dumps(status))
        self.assertNotIn("fingerprint", json.dumps(status))
        status["issues"].clear()
        self.assertTrue(h.manager.get_status("synthetic")["issues"])

    async def test_prepare_and_activation_errors_are_controlled_and_not_retried_as_success(self):
        for stage in ("prepare", "activation"):
            h = Harness()
            co = Authority()
            async def failure():
                raise ValueError("synthetic-private-secret")
            if stage == "prepare":
                co.prepare_hook = failure
            else:
                co.activation_hook = failure
            status = await h.finish(h.start(co))
            self.assertEqual(status["status"], "blocked")
            self.assertEqual(status["reason"], "activation_conditions_failed" if stage == "prepare" else "activation_failed")
            self.assertNotIn("synthetic-private-secret", json.dumps(status))

    async def test_duplicate_after_reload_is_single_flight(self):
        h = Harness()
        ticket = h.start()
        h.manager.after_reload(ticket, True)
        await h.finish(ticket)
        h.manager.after_reload(ticket, True)
        self.assertEqual(h.entry.runtime_data.activations, 1)

    async def test_initial_install_can_use_fully_setup_current_runtime(self):
        h = Harness()
        ticket = h.manager.begin(h.entry, previous_runtime=None)
        h.manager.after_reload(ticket, True)
        self.assertEqual((await h.finish(ticket))["status"], "active")

    async def test_shutdown_revokes_job_without_interrupting_durable_activation(self):
        h = Harness()
        entered, release = asyncio.Event(), asyncio.Event()
        co = Authority()
        async def pause():
            entered.set()
            await release.wait()
        co.activation_hook = pause
        ticket = h.start(co)
        await entered.wait()
        close_task = asyncio.create_task(h.manager.async_close())
        await asyncio.sleep(0)
        self.assertFalse(ticket.task.cancelled())
        self.assertFalse(close_task.done())
        release.set()
        await close_task
        self.assertEqual(co.mode, "shadow")
        self.assertEqual(h.manager.get_status("synthetic")["status"], "cancelled")

    async def test_public_idle_and_cancel_helpers_do_not_create_intent(self):
        hass = SimpleNamespace(data={})
        self.assertEqual(POST.post_save_status(hass, "absent"),
            {"status": "idle", "reason": None, "issues": [], "updated_at": None,
             "plan_source": None, "plan_reason": None})
        POST.cancel_post_save(hass, "absent")
        self.assertEqual(hass.data, {})

    async def test_options_listener_creates_ticket_before_reload_and_cancels_on_failure(self):
        tree = ast.parse((ROOT / "__init__.py").read_text(encoding="utf-8"))
        tree.body = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                     and node.name == "_async_options_changed"]
        h = Harness()
        manager = Mock()
        ticket = object()
        manager.begin.return_value = ticket
        async def reload(entry_id):
            manager.begin.assert_called_once_with(h.entry)
            self.assertEqual(entry_id, "synthetic")
            return True
        h.hass.config_entries.async_reload = reload
        namespace = {"get_post_save_manager": lambda _: manager}
        exec(compile(tree, "__init__.py", "exec"), namespace)
        await namespace["_async_options_changed"](h.hass, h.entry)
        manager.after_reload.assert_called_once_with(ticket, True)
        manager.reset_mock()
        async def failed(_):
            raise ValueError("synthetic failure")
        h.hass.config_entries.async_reload = failed
        with self.assertRaises(ValueError):
            await namespace["_async_options_changed"](h.hass, h.entry)
        manager.after_reload.assert_called_once_with(ticket, False)

    def setup_boundary(self, flag=None, *, fail=False):
        events, manager = [], Mock()
        tree = ast.parse((ROOT / "__init__.py").read_text(encoding="utf-8"))
        tree.body = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                     and node.name == "async_setup_entry"]
        entry = SimpleNamespace(entry_id="synthetic", data={"saved": "retained"}, options={},
            async_on_unload=Mock(), add_update_listener=Mock())
        if flag is not None:
            entry.data["activate_after_install"] = flag
        def consume(target, *, data):
            events.append("consume")
            target.data = data
        async def initialize():
            events.append("initialize")
            if flag is True:
                self.assertNotIn("activate_after_install", entry.data)
            if fail:
                raise ValueError("setup incomplete")
        coordinator = SimpleNamespace(async_initialize=initialize,
            async_config_entry_first_refresh=AsyncMock(), mode="shadow")
        hass = SimpleNamespace(data={"updates": object(), "appearance": object(),
            "deye_ems_static": True, "deye_ems_panel": True},
            config_entries=SimpleNamespace(async_update_entry=consume, async_forward_entry_setups=AsyncMock()))
        async def checks(_):
            events.append("setup_completed")
        def begin(*args, **kwargs):
            events.append("begin")
            self.assertEqual(events[-2], "setup_completed")
            return object()
        manager.begin.side_effect = begin
        get_manager = Mock(return_value=manager)
        namespace = {"DATA_UPDATES": "updates", "DATA_APPEARANCE": "appearance", "DOMAIN": "deye_ems",
            "PLATFORMS": ["sensor"], "Platform": lambda p:p, "DeyeEMSCoordinator": lambda *_:coordinator,
            "get_post_save_manager": get_manager, "_async_enable_update_checks": checks,
            "_async_options_changed": Mock()}
        exec(compile(tree, "__init__.py", "exec"), namespace)
        return namespace["async_setup_entry"], hass, entry, manager, get_manager, events

    async def test_initial_install_intent_is_consumed_before_initialization_and_started_after_full_setup(self):
        setup, hass, entry, manager, _, events = self.setup_boundary(True)
        await setup(hass, entry)
        self.assertEqual(events, ["consume", "initialize", "setup_completed", "begin"])
        self.assertEqual(entry.data, {"saved": "retained"})
        manager.begin.assert_called_once_with(entry, previous_runtime=None)
        self.assertIs(manager.after_reload.call_args.args[1], True)

    async def test_plain_restart_or_nonboolean_install_flag_does_not_manufacture_activation_intent(self):
        for flag in (None, False, "true", 1):
            setup, hass, entry, manager, get_manager, _ = self.setup_boundary(flag)
            await setup(hass, entry)
            manager.begin.assert_not_called()
            get_manager.assert_not_called()

    async def test_interrupted_install_consumes_intent_but_does_not_retry_activation(self):
        setup, hass, entry, manager, _, _ = self.setup_boundary(True, fail=True)
        with self.assertRaises(ValueError):
            await setup(hass, entry)
        self.assertNotIn("activate_after_install", entry.data)
        manager.begin.assert_not_called()

    async def test_timeout_after_slow_preparation_cannot_activate_late(self):
        h = Harness(timeout=10)
        co = Authority()
        async def slow():
            h.elapsed = 20
        co.prepare_hook = slow
        status = await h.finish(h.start(co))
        self.assertEqual(status["status"], "blocked")
        self.assertEqual(co.activations, 0)

    async def test_active_status_explains_known_conservative_plan_with_controlled_reason_only(self):
        for source, reason, expected_source, expected_reason in (
            ("own_conservative_fallback", "incomplete_48h_forecast", "own_conservative_fallback", "incomplete_48h_forecast"),
            ("own_deterministic_planner", "planned", "own_deterministic_planner", "planned"),
            ("own_conservative_fallback", "synthetic-private-secret", "own_conservative_fallback", None),
            ("synthetic-private-secret", "planned", None, None)):
            with self.subTest(source=source, reason=reason):
                h = Harness()
                co = Authority([{"ready": True, "recalculated": True, "plan_source": source, "plan_reason": reason}])
                status = await h.finish(h.start(co))
                self.assertEqual(status["status"], "active")
                self.assertEqual(status["plan_source"], expected_source)
                self.assertEqual(status["plan_reason"], expected_reason)
                self.assertNotIn("synthetic-private-secret", json.dumps(status))

    async def test_stop_after_save_before_reload_completion_does_not_start_job(self):
        h = Harness()
        ticket = h.manager.begin(h.entry)
        POST.cancel_post_save(h.hass, "synthetic")
        h.entry.runtime_data = Authority()
        h.manager.after_reload(ticket, True)
        self.assertIsNone(ticket.task)
        self.assertEqual(h.entry.runtime_data.activations, 0)

    async def test_global_stop_revokes_pending_reload_even_with_empty_coordinator_mapping(self):
        h = Harness()
        h.hass.data["deye_ems"] = {}
        ticket = h.manager.begin(h.entry)
        POST.cancel_all_post_save(h.hass)
        self.assertTrue(ticket.cancelled)
        self.assertEqual(POST.post_save_status(h.hass, h.entry.entry_id)["status"], "cancelled")
        h.entry.runtime_data = Authority()
        h.manager.after_reload(ticket, True)
        self.assertIsNone(ticket.task)
        self.assertEqual(h.entry.runtime_data.activations, 0)

    async def test_global_stop_during_pending_preparation_does_not_cancel_durable_task(self):
        h = Harness()
        entered, release = asyncio.Event(), asyncio.Event()
        co = Authority()
        async def pause():
            entered.set()
            await release.wait()
        co.prepare_hook = pause
        ticket = h.start(co)
        await entered.wait()
        h.hass.data["deye_ems"] = {}
        POST.cancel_all_post_save(h.hass)
        self.assertFalse(ticket.task.cancelled())
        release.set()
        await h.finish(ticket)
        self.assertEqual(co.activations, 0)

    def listener(self, h):
        tree = ast.parse((ROOT / "__init__.py").read_text(encoding="utf-8"))
        tree.body = [node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                     and node.name == "_async_options_changed"]
        namespace = {"get_post_save_manager": lambda _: h.manager}
        exec(compile(tree, "__init__.py", "exec"), namespace)
        return namespace["_async_options_changed"]

    async def test_active_options_reload_waits_for_confirmed_shadow_before_unloading_owner(self):
        h, order = Harness(), []
        h.old.mode = "active"
        async def pause(mode, *, activation_guard):
            self.assertEqual(mode, "shadow")
            self.assertTrue(activation_guard())
            order.extend(("gc_off_readback", "current_zero_readback"))
            h.old.mode = "shadow"
        h.old.async_set_mode = pause
        async def reload(_):
            self.assertEqual(order, ["gc_off_readback", "current_zero_readback"])
            order.append("unload_old_owner")
            h.entry.runtime_data = Authority()
            return True
        h.hass.config_entries.async_reload = reload
        await self.listener(h)(h.hass, h.entry)
        await next(iter(h.manager._tasks))
        self.assertEqual(order[-1], "unload_old_owner")
        self.assertEqual(h.manager.get_status("synthetic")["status"], "active")

    async def test_unconfirmed_pause_blocks_reload_and_records_controlled_persistent_reason(self):
        h = Harness()
        h.old.mode = "active"
        async def pause(*args, **kwargs):
            h.old.mode = "shadow"
            raise ValueError("configuration_pause_unconfirmed: synthetic-private-secret")
        h.old.async_set_mode = pause
        h.hass.config_entries.async_reload = AsyncMock()
        await self.listener(h)(h.hass, h.entry)
        h.hass.config_entries.async_reload.assert_not_awaited()
        status = h.manager.get_status("synthetic")
        self.assertEqual((status["status"], status["reason"]), ("blocked", "configuration_pause_failed"))
        self.assertNotIn("synthetic-private-secret", json.dumps(status))
        self.assertEqual(h.old.mode, "shadow")
        self.assertEqual(h.manager._tasks, set())

    async def test_manual_stop_during_internal_pause_wins_and_never_unloads_owner(self):
        h = Harness()
        h.old.mode = "active"
        entered, release = asyncio.Event(), asyncio.Event()
        async def pause(*args, activation_guard, **kwargs):
            entered.set()
            await release.wait()
            h.old.mode = "shadow"
            self.assertFalse(activation_guard())
            raise ValueError("activation_cancelled")
        h.old.async_set_mode = pause
        h.hass.config_entries.async_reload = AsyncMock()
        task = asyncio.create_task(self.listener(h)(h.hass, h.entry))
        await entered.wait()
        POST.cancel_all_post_save(h.hass)
        release.set()
        await task
        h.hass.config_entries.async_reload.assert_not_awaited()
        self.assertEqual(h.manager.get_status("synthetic")["status"], "cancelled")
        self.assertEqual(h.manager._tasks, set())

    async def test_new_save_supersedes_old_pause_and_old_failure_cannot_block_new_intent(self):
        h = Harness()
        h.old.mode = "active"
        entered, release = asyncio.Event(), asyncio.Event()
        async def pause(*args, activation_guard, **kwargs):
            entered.set()
            await release.wait()
            h.old.mode = "shadow"
            self.assertFalse(activation_guard())
            raise ValueError("activation_cancelled")
        h.old.async_set_mode = pause
        h.hass.config_entries.async_reload = AsyncMock()
        task = asyncio.create_task(self.listener(h)(h.hass, h.entry))
        await entered.wait()
        h.entry.options = {**h.entry.options, "capacity_kwh": 77}
        newer = h.manager.begin(h.entry)
        release.set()
        await task
        self.assertEqual(h.manager.get_status("synthetic")["status"], "waiting")
        self.assertTrue(h.manager.is_current(newer))
        h.hass.config_entries.async_reload.assert_not_awaited()

    async def test_old_runtime_requires_reload_after_failed_or_cancelled_pause_but_new_identity_does_not(self):
        for outcome in ("failed", "cancelled", "pending"):
            with self.subTest(outcome=outcome):
                h = Harness()
                self.assertFalse(POST.configuration_requires_reload(h.hass, "synthetic", h.old))
                ticket = h.manager.begin(h.entry)
                if outcome == "failed":
                    h.manager.pause_failed(ticket)
                elif outcome == "cancelled":
                    POST.cancel_all_post_save(h.hass)
                self.assertTrue(POST.configuration_requires_reload(h.hass, "synthetic", h.old))
                new_runtime = Authority()
                h.entry.runtime_data = new_runtime
                self.assertFalse(POST.configuration_requires_reload(h.hass, "synthetic", new_runtime))
                self.assertTrue(POST.configuration_requires_reload(h.hass, "synthetic", h.old))

    async def test_fresh_initial_setup_uses_real_manager_and_existing_new_runtime_can_activate(self):
        setup, hass, entry, _, _, _ = self.setup_boundary(True)
        co = Authority()
        co.async_initialize = AsyncMock()
        co.async_config_entry_first_refresh = AsyncMock()
        entry.state = SimpleNamespace(value="loaded")
        hass.config_entries.async_get_entry = lambda entry_id: entry if entry_id == entry.entry_id else None
        manager = POST.PostSaveActivationManager(hass)
        hass.data[POST.DATA_POST_SAVE] = manager
        setup.__globals__["get_post_save_manager"] = lambda _:manager
        setup.__globals__["DeyeEMSCoordinator"] = lambda *_:co
        await setup(hass, entry)
        self.assertIs(entry.runtime_data, co)
        self.assertNotIn("activate_after_install", entry.data)
        self.assertFalse(POST.configuration_requires_reload(hass, entry.entry_id, co))
        await next(iter(manager._tasks))
        self.assertEqual(manager.get_status(entry.entry_id)["status"], "active")
        self.assertEqual(co.activations, 1)
        self.assertEqual(co.recalculations, [True])


if __name__ == "__main__":
    unittest.main()
