"""Automatic release notices, without timers, credentials or device authority."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from test_installable import C, load
import test_updates as update_boundary
from test_updates import Response, release


class StepSleep:
    def __init__(self):
        self.calls = []
        self.gates = []

    async def __call__(self, delay):
        self.calls.append(delay)
        gate = asyncio.Event()
        self.gates.append(gate)
        await gate.wait()

    def advance(self):
        self.gates[-1].set()


async def settle():
    for _ in range(8):
        await asyncio.sleep(0)


class BackgroundUpdates(unittest.IsolatedAsyncioTestCase):
    fixture = update_boundary.Updates.fixture
    async def test_start_waits_without_http_then_checks_hourly_and_is_idempotent(self):
        module, manager, session = self.fixture(Response(release()), Response(release("v1.0.19")))
        sleeper = StepSleep()
        manager._sleep = sleeper
        manager.async_start()
        runner = manager._runner
        manager.async_start()
        self.assertIs(manager._runner, runner)
        self.assertEqual(session.calls, [])
        await settle()
        self.assertEqual(sleeper.calls, [module["STARTUP_DELAY_SECONDS"]])
        self.assertTrue(manager.status["automatic"])
        self.assertEqual(manager.status["interval_seconds"], 3600)
        self.now += timedelta(seconds=module["STARTUP_DELAY_SECONDS"])
        sleeper.advance()
        await settle()
        self.assertEqual(manager.status["latest_version"], "1.0.18")
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(sleeper.calls[-1], 3600)
        self.now += timedelta(hours=1)
        sleeper.advance()
        await settle()
        self.assertEqual(manager.status["latest_version"], "1.0.19")
        self.assertEqual(len(session.calls), 2)
        await manager.async_stop()
        self.assertFalse(manager.status["automatic"])
        self.assertIsNone(manager.status["next_check_at"])

    async def test_automatic_and_manual_checks_share_the_same_inflight_request(self):
        gate = asyncio.Event()
        _, manager, session = self.fixture(Response(release(), event=gate))
        sleeper = StepSleep()
        manager._sleep = sleeper
        manager.async_start()
        await settle()
        self.now += timedelta(seconds=30)
        sleeper.advance()
        await settle()
        manual = asyncio.create_task(manager.async_check())
        await settle()
        self.assertEqual(len(session.calls), 1)
        gate.set()
        self.assertEqual((await manual)["status"], "available")
        await settle()
        self.assertEqual(len(session.calls), 1)
        await manager.async_stop()

    async def test_stop_cancels_a_hanging_http_and_prevents_late_manual_requests(self):
        _, manager, session = self.fixture(Response(release(), event=asyncio.Event()))
        sleeper = StepSleep()
        manager._sleep = sleeper
        manager.async_start()
        await settle()
        self.now += timedelta(seconds=30)
        sleeper.advance()
        await settle()
        request, runner = manager._task, manager._runner
        self.assertEqual(len(session.calls), 1)
        await manager.async_stop()
        self.assertTrue(request.cancelled())
        self.assertTrue(runner.cancelled())
        self.now += timedelta(days=1)
        await manager.async_check()
        self.assertEqual(len(session.calls), 1)
        self.assertIsNone(manager.status["next_check_at"])

    async def test_reload_reuses_pending_hour_and_rate_limit_cooldown(self):
        _, manager, session = self.fixture(Response(release()), Response(release("v1.0.19")))
        sleeper = StepSleep()
        manager._sleep = sleeper
        manager.async_start()
        await settle()
        self.now += timedelta(seconds=30)
        sleeper.advance()
        await settle()
        await manager.async_stop()
        self.now += timedelta(seconds=5)
        manager.async_start()
        await settle()
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(sleeper.calls[-1], 3595)
        await manager.async_stop()
        # A request backoff is also respected if no automatic run happened yet.
        _, manager, session = self.fixture(Response(status=429, headers={"Retry-After": "3600"}))
        await manager.async_check()
        manager._sleep = StepSleep()
        manager.async_start()
        await settle()
        self.assertEqual(manager._sleep.calls, [3600])
        self.assertEqual(len(session.calls), 1)
        await manager.async_stop()

    async def test_readonly_listeners_receive_changes_and_can_unsubscribe(self):
        _, manager, session = self.fixture(Response(release()))
        snapshots = []
        remove = manager.async_add_listener(lambda: snapshots.append(manager.status))
        manager.async_add_listener(lambda: (_ for _ in ()).throw(RuntimeError("private-listener-text")))
        await manager.async_check()
        self.assertEqual([s["status"] for s in snapshots], ["checking", "available"])
        remove()
        await manager.async_stop()
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(len(session.calls), 1)

    async def test_manual_rate_limit_postpones_an_already_sleeping_automatic_timer(self):
        _, manager, session = self.fixture(Response(release()),
            Response(status=429, headers={"Retry-After": "3600"}), Response(release("v1.0.19")))
        sleeper = StepSleep()
        manager._sleep = sleeper
        manager.async_start()
        await settle()
        self.now += timedelta(seconds=30)
        sleeper.advance()
        await settle()
        self.now += timedelta(seconds=3500)
        await manager.async_check()
        self.assertEqual(manager.status["next_check_at"], (self.now+timedelta(hours=1)).isoformat())
        self.now += timedelta(seconds=100)
        sleeper.advance()
        await settle()
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(sleeper.calls[-1], 3500)
        self.now += timedelta(seconds=3500)
        sleeper.advance()
        await settle()
        self.assertEqual(len(session.calls), 3)
        self.assertEqual(manager.status["latest_version"], "1.0.19")
        await manager.async_stop()


class Bus:
    def __init__(self):
        self.callbacks = {}

    def async_listen_once(self, name, callback):
        self.callbacks.setdefault(name, []).append(callback)

        def cancel():
            if callback in self.callbacks.get(name, []):
                self.callbacks[name].remove(callback)

        return cancel

    async def fire(self, name):
        callbacks = self.callbacks.pop(name, [])
        for callback in callbacks:
            await callback(None)


class UpdateLifecycle(unittest.IsolatedAsyncioTestCase):
    def fixture(self, running=False):
        manager = SimpleNamespace(async_start=Mock(), async_stop=AsyncMock())
        hass = SimpleNamespace(data={"deye_ems_updates": manager}, bus=Bus(), is_running=running)
        module = load("__init__.py", {"__name__": "offline_update_lifecycle", **C,
            "DATA_UPDATES": "deye_ems_updates", "EVENT_HOMEASSISTANT_STARTED": "started",
            "EVENT_HOMEASSISTANT_STOP": "stop"})
        return module, hass, manager

    async def test_waits_for_started_and_stops_on_ha_shutdown(self):
        module, hass, manager = self.fixture()
        await module["_async_enable_update_checks"](hass)
        manager.async_start.assert_not_called()
        self.assertEqual(len(hass.bus.callbacks["started"]), 1)
        await hass.bus.fire("started")
        manager.async_start.assert_called_once_with()
        await hass.bus.fire("stop")
        manager.async_stop.assert_awaited_once_with()
        self.assertNotIn("deye_ems_updates_stop", hass.data)

    async def test_unload_or_stop_before_started_removes_pending_start(self):
        for operation in ("unload", "stop"):
            module, hass, manager = self.fixture()
            await module["_async_enable_update_checks"](hass)
            if operation == "unload":
                await module["_async_disable_update_checks"](hass)
            else:
                await hass.bus.fire("stop")
            await hass.bus.fire("started")
            manager.async_start.assert_not_called()
            manager.async_stop.assert_awaited_once_with()

    async def test_running_setup_has_one_stop_listener_and_no_start_listener(self):
        module, hass, manager = self.fixture(running=True)
        await module["_async_enable_update_checks"](hass)
        await module["_async_enable_update_checks"](hass)
        self.assertEqual(len(hass.bus.callbacks["stop"]), 1)
        self.assertNotIn("started", hass.bus.callbacks)
        manager.async_stop.assert_not_awaited()


class FakeUpdateEntity:
    async def async_added_to_hass(self):
        self.remove_callbacks = []
        self.writes = 0

    def async_on_remove(self, callback):
        self.remove_callbacks.append(callback)

    def async_write_ha_state(self):
        self.writes += 1


class NativeUpdateEntity(unittest.IsolatedAsyncioTestCase):
    async def test_update_entity_is_readonly_and_uses_the_existing_manager(self):
        from enum import IntFlag
        class Features(IntFlag):
            INSTALL = 1
            PROGRESS = 4
        state = {"latest_version": "2.0.5", "release_url": "https://github.com/gaszu/deye-ems/releases/tag/v2.0.5",
                 "status": "available", "checked_at": "2026-11-13T09:00:00+00:00", "automatic": True,
                 "interval_seconds": 3600, "next_check_at": "2026-11-13T10:00:00+00:00", "stale": False}
        manager = SimpleNamespace(status=state, async_check=AsyncMock(), async_add_listener=Mock(return_value=Mock()))
        values = {**C, "DATA_UPDATES": "deye_ems_updates", "UpdateEntity": FakeUpdateEntity,
                  "UpdateEntityFeature": Features,
                  "EntityCategory": SimpleNamespace(DIAGNOSTIC="diagnostic"), "DeviceInfo": lambda **kw:kw,
                  "callback": lambda fn:fn}
        module = load("update.py", values)
        added = []
        await module["async_setup_entry"](SimpleNamespace(data={"deye_ems_updates": manager}),
            SimpleNamespace(entry_id="entry-one"), added.extend)
        entity = added[0]
        self.assertEqual(entity._attr_supported_features, 0)
        # HA 2026.11 checks feature membership while adding an update entity.
        # Bare int(0) compares equal but raises TypeError at this real boundary.
        self.assertIsInstance(entity._attr_supported_features, IntFlag)
        self.assertNotIn(Features.PROGRESS, entity._attr_supported_features)
        self.assertNotIn(Features.INSTALL, entity._attr_supported_features)
        self.assertFalse(entity._attr_should_poll)
        self.assertEqual(entity.installed_version, C["VERSION"])
        self.assertEqual(entity.latest_version, "2.0.5")
        self.assertEqual(entity._attr_device_info["identifiers"], {(C["DOMAIN"], "entry-one")})
        manager.async_check.assert_not_awaited()
        await entity.async_added_to_hass()
        manager.async_add_listener.assert_called_once()
        manager.async_add_listener.call_args.args[0]()
        self.assertEqual(entity.writes, 1)
        await entity.async_update()
        manager.async_check.assert_awaited_once_with()
        self.assertNotIn("async_install", type(entity).__dict__)
        self.assertEqual(entity.extra_state_attributes["interval_seconds"], 3600)
        self.assertIn("nie instaluje", entity.release_summary)
        state.update(status="error", stale=True, private_error="secret-provider-text")
        self.assertIn("nieaktualna", entity.release_summary)
        self.assertNotIn("secret-provider-text", entity.release_summary)


if __name__ == "__main__":
    unittest.main()
