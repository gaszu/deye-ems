"""Sidebar preferences must not reload or operate the energy controller."""
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

from test_appearance import load_appearance, MemoryStore, HomeAssistantError
import test_installable as boundary


class Sidebar(unittest.IsolatedAsyncioTestCase):
    def manager(self, store=None):
        module, _ = load_appearance()
        return module["AppearanceManager"](object(), store=store or MemoryStore())

    async def test_default_visible_and_hidden_preference_survives_theme_change_restart(self):
        store = MemoryStore()
        manager = self.manager(store)
        self.assertTrue(manager.sidebar_visible)
        await manager.async_set_sidebar_visible(False)
        await manager.async_set_theme("synthetic-night")
        restored = self.manager(store)
        await restored.async_load()
        self.assertFalse(restored.sidebar_visible)
        self.assertEqual(restored.appearance, {"theme": "synthetic-night"})
        await restored.async_set_sidebar_visible(True)
        self.assertEqual(store.saved, {"theme": "synthetic-night"})

    async def test_failed_or_invalid_save_keeps_published_visibility(self):
        store = MemoryStore()
        manager = self.manager(store)
        for value in (None, 1, "true"):
            with self.assertRaises(ValueError):
                await manager.async_set_sidebar_visible(value)
        store.fail = True
        with self.assertRaises(HomeAssistantError):
            await manager.async_set_sidebar_visible(False)
        self.assertTrue(manager.sidebar_visible)

    async def test_native_flow_saves_in_active_without_changing_options(self):
        values = boundary.Installation().flow()
        manager, update = self.manager(), AsyncMock()
        values.update(DATA_APPEARANCE="appearance", HomeAssistantError=HomeAssistantError,
                      async_update_panel=update)
        flow = values["DeyeEMSOptionsFlow"]()
        flow.hass = SimpleNamespace(data={"appearance": manager})
        original = {"min_soc_percent": 50, "sources": {"soc": "sensor.synthetic_soc"}}
        flow.config_entry = SimpleNamespace(options=original,
                                            runtime_data=SimpleNamespace(mode="active"))
        form = await flow.async_step_sidebar()
        self.assertEqual(form["step_id"], "sidebar")
        result = await flow.async_step_sidebar({"sidebar_visible": False})
        self.assertEqual(result, {"type": "abort", "reason": "sidebar_saved"})
        self.assertIs(flow.config_entry.options, original)
        self.assertEqual(flow.config_entry.runtime_data.mode, "active")
        update.assert_awaited_once_with(flow.hass)
        self.assertFalse(manager.sidebar_visible)

    async def test_failed_flow_save_does_not_refresh_navigation(self):
        values = boundary.Installation().flow()
        store = MemoryStore()
        store.fail = True
        manager, update = self.manager(store), AsyncMock()
        values.update(DATA_APPEARANCE="appearance", HomeAssistantError=HomeAssistantError,
                      async_update_panel=update)
        flow = values["DeyeEMSOptionsFlow"]()
        flow.hass = SimpleNamespace(data={"appearance": manager})
        result = await flow.async_step_sidebar({"sidebar_visible": False})
        self.assertEqual(result["errors"], {"base": "sidebar_save_failed"})
        update.assert_not_awaited()

    async def test_hidden_panel_keeps_route_and_admin_guard_without_runtime_work(self):
        panel, remove = AsyncMock(), Mock()
        hass = SimpleNamespace(data={"appearance": SimpleNamespace(sidebar_visible=False),
                                     "deye_ems_panel": True})
        values = boundary.load("__init__.py", {**boundary.C, "__name__": "offline_sidebar",
            "DATA_APPEARANCE": "appearance",
            "frontend": SimpleNamespace(async_remove_panel=remove),
            "panel_custom": SimpleNamespace(async_register_panel=panel)})
        await values["async_update_panel"](hass)
        remove.assert_called_once_with(hass, "deye-ems")
        self.assertIsNone(panel.await_args.kwargs["sidebar_title"])
        self.assertEqual(panel.await_args.kwargs["frontend_url_path"], "deye-ems")
        self.assertTrue(panel.await_args.kwargs["require_admin"])
        hass.data["appearance"].sidebar_visible = True
        await values["async_update_panel"](hass)
        self.assertEqual(panel.await_args.kwargs["sidebar_title"], "Deye EMS")
