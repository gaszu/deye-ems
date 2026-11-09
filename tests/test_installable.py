"""Install/configuration boundary checks with HA interfaces stubbed."""
import ast
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock

ROOT = Path(__file__).resolve().parents[1] / "custom_components/deye_ems"
C = {}
exec((ROOT/"const.py").read_text(encoding="utf-8"), C)

def load(filename, values):
    tree = ast.parse((ROOT/filename).read_text(encoding="utf-8"))
    tree.body = [n for n in tree.body if not isinstance(n, (ast.Import, ast.ImportFrom))]
    exec(compile(tree, filename, "exec"), values)
    return values

class Flow:
    def __init_subclass__(cls, **kwargs): super().__init_subclass__()
    async def async_set_unique_id(self, value): self.unique_id = value
    def _abort_if_unique_id_configured(self): pass
    def async_create_entry(self, **kw): return {"type":"create_entry", **kw}
    def async_abort(self, **kw): return {"type":"abort", **kw}

class Coordinator:
    def __init__(self, hass, entry): self.mode, self.data = "shadow", {}
    async def async_initialize(self): pass
    async def async_config_entry_first_refresh(self): pass
    async def async_shutdown(self): pass

class Installation(unittest.IsolatedAsyncioTestCase):
    def flow(self):
        return load("config_flow.py", {**C, "__name__":"offline_flow",
            "callback": lambda f:f, "config_entries": SimpleNamespace(ConfigFlow=Flow,OptionsFlow=Flow)})

    async def test_setup_keeps_entered_minimum_without_helper_or_active_mode(self):
        result = await self.flow()["DeyeEMSConfigFlow"]().async_step_user(
            dict(min_soc_percent=60,capacity_kwh=66,grid_import_limit_kw=12,grid_phase_limit_kw=5))
        self.assertEqual(result["data"]["min_soc_percent"],60)
        self.assertNotIn("active",result["data"])
        self.assertTrue(all(not s.startswith(("input_","automation.","sensor.ems_"))
            for s in result["data"]["sources"].values()))

    async def test_active_flow_cannot_bypass_mapping_change_lock(self):
        flow = self.flow()["DeyeEMSOptionsFlow"]()
        flow.config_entry = SimpleNamespace(runtime_data=SimpleNamespace(mode="active"),options={},data={})
        before = deepcopy(flow.config_entry.options)
        for method in ("async_step_sources","async_step_add_load","async_step_remove_load"):
            r = await getattr(flow,method)({"ignored":"unsafe mapping"})
            self.assertEqual(r,dict(type="abort",reason="stop_before_mapping"))
        self.assertEqual(flow.config_entry.options,before)

    async def test_inconsistent_soc_settings_are_rejected(self):
        errors = self.flow()["_errors"]
        self.assertTrue(errors(dict(min_soc_percent=90,reserve_margin_soc_percent=10,grid_max_soc_percent=95)))
        self.assertFalse(errors(dict(min_soc_percent=90,reserve_margin_soc_percent=5,grid_max_soc_percent=95)))

    async def test_reload_registers_panel_again_but_static_path_only_once(self):
        static,panel = AsyncMock(),AsyncMock()
        h=SimpleNamespace(data={},http=SimpleNamespace(async_register_static_paths=static),
            config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock(),
                async_unload_platforms_or_raise=AsyncMock(),async_reload=AsyncMock()))
        m=load("__init__.py",{**C,"__name__":"offline_init","__file__":str(ROOT/"__init__.py"),
            "Path":Path,"Platform":lambda p:p,"DeyeEMSCoordinator":Coordinator,
            "StaticPathConfig":lambda *a:a,"async_register":Mock(),
            "frontend":SimpleNamespace(async_remove_panel=Mock()),
            "panel_custom":SimpleNamespace(async_register_panel=panel)})
        e=SimpleNamespace(entry_id="one",async_on_unload=Mock(),add_update_listener=Mock())
        self.assertIsNone(await m["async_setup_entry"](h,e))
        await m["async_unload_entry"](h,e)
        await m["async_setup_entry"](h,e)
        self.assertEqual(static.await_count,1)
        self.assertEqual(panel.await_count,2)
        self.assertTrue(panel.await_args.kwargs["require_admin"])
        self.assertEqual(e.runtime_data.mode,"shadow")

    async def test_manifest_platforms_and_bundled_panel_exist(self):
        manifest=json.loads((ROOT/"manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["config_flow"])
        self.assertEqual(manifest["requirements"],[])
        for platform in C["PLATFORMS"]:
            self.assertTrue((ROOT/(platform+".py")).is_file())
        self.assertTrue((ROOT/"frontend/deye-ems-panel.js").is_file())

