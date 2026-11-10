"""Panel-only preference storage with no HA instance or energy engine."""
import ast
import asyncio
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[1] / "custom_components/deye_ems"


class HomeAssistantError(Exception):
    pass


class MemoryStore:
    def __init__(self, saved=None):
        self.saved = deepcopy(saved)
        self.writes = []
        self.fail = False
        self.started = None
        self.release = None

    async def async_load(self):
        return deepcopy(self.saved)

    async def async_save(self, value):
        self.writes.append(deepcopy(value))
        if self.started is not None:
            self.started.set()
            await self.release.wait()
        if self.fail:
            raise OSError("synthetic private storage detail")
        self.saved = deepcopy(value)


def load_appearance(names=("synthetic-night", "synthetic-light"), store_factory=None):
    names_callback = Mock(return_value=list(names))
    values = {"asyncio": asyncio, "frontend": SimpleNamespace(async_get_theme_names=names_callback),
              "HomeAssistantError": HomeAssistantError, "Store": store_factory or Mock()}
    tree = ast.parse((ROOT / "appearance.py").read_text(encoding="utf-8"))
    tree.body = [node for node in tree.body
                 if not isinstance(node, (ast.Import, ast.ImportFrom))]
    exec(compile(tree, "appearance.py", "exec"), values)
    return values, names_callback


class AppearanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_separate_store_key_and_no_energy_configuration(self):
        store, hass = MemoryStore(), object()
        factory = Mock(return_value=store)
        module, _ = load_appearance(store_factory=factory)
        manager = module["AppearanceManager"](hass)
        factory.assert_called_once_with(hass, 1, "deye_ems_appearance")
        await manager.async_load()
        self.assertEqual(manager.appearance, {"theme": ""})
        self.assertEqual(store.writes, [])

    async def test_restore_only_preference_and_return_a_copy(self):
        module, names = load_appearance()
        manager = module["AppearanceManager"](object(), store=MemoryStore({
            "theme": "synthetic-night", "unexpected_private_field": "ignored"}))
        await manager.async_load()
        response = manager.appearance
        response["theme"] = "changed outside manager"
        self.assertEqual(manager.appearance, {"theme": "synthetic-night"})
        names.assert_not_called()

    async def test_malformed_saved_preference_is_ignored(self):
        module, _ = load_appearance()
        for saved in (None, [], {"theme": None}, {"theme": False}, {"theme": "x" * 257}):
            with self.subTest(saved_type=type(saved).__name__):
                manager = module["AppearanceManager"](object(), store=MemoryStore(saved))
                await manager.async_load()
                self.assertEqual(manager.appearance, {"theme": ""})

    async def test_unreadable_appearance_store_cannot_block_integration_start(self):
        module, _ = load_appearance()
        store = MemoryStore()
        store.async_load = AsyncMock(side_effect=OSError("synthetic read failure"))
        manager = module["AppearanceManager"](object(), store=store)
        await manager.async_load()
        self.assertEqual(manager.appearance, {"theme": ""})
        self.assertEqual(store.writes, [])

    async def test_named_and_profile_theme_survive_new_manager(self):
        module, names = load_appearance()
        hass, store = object(), MemoryStore()
        for theme in ("synthetic-night", ""):
            manager = module["AppearanceManager"](hass, store=store)
            await manager.async_load()
            await manager.async_set_theme(theme)
            restored = module["AppearanceManager"](hass, store=store)
            await restored.async_load()
            self.assertEqual(restored.appearance, {"theme": theme})
            self.assertEqual(store.saved, {"theme": theme})
        names.assert_called_once_with(hass)

    async def test_unknown_default_and_invalid_values_never_write(self):
        module, _ = load_appearance()
        store = MemoryStore({"theme": "synthetic-night"})
        manager = module["AppearanceManager"](object(), store=store)
        await manager.async_load()
        for theme in ("unknown-theme", "default", None, False, 42, {}, "x" * 257):
            with self.subTest(value_type=type(theme).__name__):
                with self.assertRaises(ValueError):
                    await manager.async_set_theme(theme)
                self.assertEqual(manager.appearance, {"theme": "synthetic-night"})
        self.assertEqual(store.writes, [])

    async def test_failed_save_preserves_published_and_durable_value(self):
        module, _ = load_appearance()
        store = MemoryStore({"theme": "synthetic-night"})
        manager = module["AppearanceManager"](object(), store=store)
        await manager.async_load()
        store.fail = True
        with self.assertRaises(HomeAssistantError) as caught:
            await manager.async_set_theme("synthetic-light")
        self.assertNotIn("private", str(caught.exception))
        self.assertEqual(manager.appearance, {"theme": "synthetic-night"})
        self.assertEqual(store.saved, {"theme": "synthetic-night"})
        store.fail = False
        await manager.async_set_theme("synthetic-light")
        self.assertEqual(manager.appearance, {"theme": "synthetic-light"})

    async def test_parallel_writes_are_serial_and_not_published_before_save(self):
        module, _ = load_appearance()
        store = MemoryStore({"theme": ""})
        store.started, store.release = asyncio.Event(), asyncio.Event()
        manager = module["AppearanceManager"](object(), store=store)
        await manager.async_load()
        first = asyncio.create_task(manager.async_set_theme("synthetic-night"))
        await store.started.wait()
        second = asyncio.create_task(manager.async_set_theme("synthetic-light"))
        await asyncio.sleep(0)
        self.assertEqual(manager.appearance, {"theme": ""})
        self.assertEqual(store.writes, [{"theme": "synthetic-night"}])
        store.release.set()
        await asyncio.gather(first, second)
        self.assertEqual(store.writes, [{"theme": "synthetic-night"}, {"theme": "synthetic-light"}])
        self.assertEqual(store.saved, {"theme": "synthetic-light"})
        self.assertEqual(manager.appearance, {"theme": "synthetic-light"})
