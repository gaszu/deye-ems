"""Install/configuration boundary checks with HA interfaces stubbed."""
import ast
from copy import deepcopy
import json
import importlib.util
from pathlib import Path
import shutil
from string import Formatter
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock
from uuid import uuid4
import zipfile

ROOT = Path(__file__).resolve().parents[1] / "custom_components/deye_ems"
C = {}
exec((ROOT/"const.py").read_text(encoding="utf-8"), C)
spec = importlib.util.spec_from_file_location("offline_solcast", ROOT/"solcast.py")
SOLCAST = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SOLCAST)
spec = importlib.util.spec_from_file_location("offline_soc_policy", ROOT/"soc_policy.py")
SOC_POLICY = importlib.util.module_from_spec(spec)
spec.loader.exec_module(SOC_POLICY)
spec = importlib.util.spec_from_file_location("offline_solcast_import", ROOT/"solcast_import.py")
IMPORTER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(IMPORTER)
spec = importlib.util.spec_from_file_location("offline_inverter_models", ROOT/"inverter_models.py")
MODELS = importlib.util.module_from_spec(spec)
spec.loader.exec_module(MODELS)

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
    def async_show_form(self, **kw): return {"type":"form", **kw}

class Marker:
    def __init__(self, key, **kw): self.key, self.kw = key, kw

class Schema(dict):
    def extend(self, fields): return Schema({**self, **fields})

class Selectors:
    NumberSelectorMode = SimpleNamespace(BOX="box")
    TextSelectorType = SimpleNamespace(PASSWORD="password")
    def __getattr__(self, name):
        return lambda *args, **kw: {"kind": name, "args": args, **kw}

class Coordinator:
    def __init__(self, hass, entry): self.mode, self.data = "shadow", {}
    async def async_initialize(self): pass
    async def async_config_entry_first_refresh(self): pass
    async def async_shutdown(self): pass

class Installation(unittest.IsolatedAsyncioTestCase):
    def flow(self):
        return load("config_flow.py", {**C, "__name__":"offline_flow",
            **{name: getattr(MODELS, name) for name in
                ("HARDWARE_KEYS", "applied_limits", "hardware_profile", "model_choices", "model_selection")},
            "reserve_bound_from_state": SOC_POLICY.reserve_bound_from_state,
            "uuid4": uuid4, "validate_config": SOLCAST.validate_config,
            "import_existing_options": IMPORTER.import_existing_options,
            "er": SimpleNamespace(async_get=lambda h:None, async_entries_for_config_entry=lambda r,e:[
                SimpleNamespace(platform="solcast_solar",unique_id="dampen",entity_id="sensor.corrections")]),
            "vol": SimpleNamespace(Required=Marker,Optional=Marker,Secret=lambda k:k,Schema=Schema),
            "selector": Selectors(),
            "callback": lambda f:f, "config_entries": SimpleNamespace(ConfigFlow=Flow,OptionsFlow=Flow)})

    async def test_setup_keeps_entered_minimum_without_helper_or_active_mode(self):
        result = await self.flow()["DeyeEMSConfigFlow"]().async_step_user(
            dict(min_soc_percent=60,capacity_kwh=99,grid_import_limit_kw=12,grid_phase_limit_kw=5))
        self.assertEqual(result["data"]["min_soc_percent"],60)
        self.assertEqual(result["data"]["capacity_kwh"],99)
        self.assertNotIn("active",result["data"])
        self.assertTrue(all(not s.startswith(("input_","automation.","sensor.ems_"))
            for s in result["data"]["sources"].values()))

    async def test_active_flow_cannot_bypass_mapping_change_lock(self):
        flow = self.flow()["DeyeEMSOptionsFlow"]()
        flow.config_entry = SimpleNamespace(runtime_data=SimpleNamespace(mode="active"),options={},data={})
        before = deepcopy(flow.config_entry.options)
        for method in ("async_step_sources","async_step_add_load","async_step_remove_load",
                "async_step_solcast", "async_step_solcast_manual", "async_step_solcast_import", "async_step_solcast_disable"):
            r = await getattr(flow,method)({"ignored":"unsafe mapping"})
            self.assertEqual(r,dict(type="abort",reason="stop_before_mapping"))
        self.assertEqual(flow.config_entry.options,before)

    async def test_solcast_configuration_keeps_private_key_and_changes_generation(self):
        normalize = self.flow()["_solcast_input"]
        previous = {"api_key": "synthetic-key-for-test", "config_generation": "old"}
        values = {"resource_ids": "site-a; site-b\nsite-c", "initial_requests_used": 7}
        a, b = normalize(values, previous), normalize(values, previous)
        self.assertEqual(a["resource_ids"], ["site-a", "site-b", "site-c"])
        self.assertEqual(a["api_key"], previous["api_key"])
        self.assertEqual(a["initial_requests_used"], 7)
        self.assertEqual(a["hourly_factors"], [1.] * 24)
        self.assertNotEqual(a["config_generation"], b["config_generation"])
        self.assertEqual(previous["config_generation"], "old")

    async def test_solcast_configuration_rejects_bad_corrections_and_missing_key(self):
        normalize = self.flow()["_solcast_input"]
        for values in ({}, {"api_key":"synthetic-key-for-test", "hourly_factors":"1 2"},
                {"api_key":"synthetic-key-for-test", "resource_ids":"../private"},
                {"api_key":"synthetic-key-for-test", "initial_requests_used":-1}):
            with self.assertRaises(ValueError):
                normalize(values, {})

    async def test_solcast_disable_retains_credentials_without_enabling_other_controller(self):
        flow = self.flow()["DeyeEMSOptionsFlow"]()
        flow.config_entry = SimpleNamespace(options={"solcast":{"api_key":"synthetic-key-for-test", "enabled":True}}, data={})
        r = await flow.async_step_solcast_disable()
        self.assertFalse(r["data"]["solcast"]["enabled"])
        self.assertEqual(r["data"]["solcast"]["api_key"], "synthetic-key-for-test")
        self.assertEqual(flow.config_entry.options["solcast"]["enabled"], True)

    async def test_solcast_form_never_prefills_or_echoes_saved_or_submitted_key(self):
        flow = self.flow()["DeyeEMSOptionsFlow"]()
        flow.config_entry = SimpleNamespace(options={"solcast":{"api_key":"synthetic-secret-saved", "resource_ids":["site-a"]}}, data={})
        for values in (None, {"api_key":"synthetic-secret-new", "hourly_factors":"1"}):
            r = await flow.async_step_solcast_manual(values)
            fields = {m.key:(m.kw, config) for m,config in r["data_schema"].items()}
            self.assertEqual(fields["api_key"][0], {})
            self.assertEqual(fields["api_key"][1]["args"][0]["type"], "password")
            self.assertNotIn("synthetic-secret", repr(fields))
        self.assertEqual(flow.config_entry.options["solcast"]["api_key"], "synthetic-secret-saved")

    async def test_import_warns_before_replacing_adaptive_calibration(self):
        flow = self.flow()["DeyeEMSOptionsFlow"]()
        flow.config_entry = SimpleNamespace(options={},data={})
        old = SimpleNamespace(entry_id="old",title="Solcast",data={}, options={
            "api_key":"synthetic-key-for-test", "auto_dampen":True,"damp12":.7})
        flow.hass = SimpleNamespace(config_entries=SimpleNamespace(async_entries=lambda _: [old]),
            states=SimpleNamespace(get=lambda _: SimpleNamespace(state="on", attributes={"integration_automated":True,
                "factors":[{"interval":f"{i//2:02}:{i%2*30:02}","factor":1.} for i in range(48)]})))
        r = await flow.async_step_solcast_import({"source_entry":"old"})
        self.assertIn("zostały odczytane i skopiowane", r["description_placeholders"]["import_note"])
        self.assertNotIn("synthetic-key-for-test", repr(r))
        r = await flow.async_step_solcast_manual({"resource_ids":"site-a"})
        self.assertEqual(r["errors"]["base"], "import_calibration_required")
        r = await flow.async_step_solcast_manual({"resource_ids":"site-a", "accept_manual_calibration":True})
        self.assertEqual(r["type"], "create_entry")
        self.assertEqual(r["data"]["solcast"]["api_key"], "synthetic-key-for-test")
        self.assertEqual(r["data"]["solcast"]["hourly_factors"], [1.] * 24)
        self.assertEqual(r["data"]["solcast"]["half_hourly_factors"], [1.] * 48)
        self.assertTrue(old.options["auto_dampen"])

    async def test_inconsistent_soc_settings_are_rejected(self):
        errors = self.flow()["_errors"]
        self.assertTrue(errors(dict(min_soc_percent=90,reserve_margin_soc_percent=10,grid_max_soc_percent=95)))
        self.assertFalse(errors(dict(min_soc_percent=90,reserve_margin_soc_percent=5,grid_max_soc_percent=95)))

    async def test_reload_registers_panel_again_but_static_path_only_once(self):
        static,panel = AsyncMock(),AsyncMock()
        appearance = SimpleNamespace(async_load=AsyncMock(), appearance={"theme": "synthetic-night"})
        appearance_factory = Mock(return_value=appearance)
        updates = SimpleNamespace(status={"status": "not_checked"}, async_check=AsyncMock(),
            async_start=Mock(), async_stop=AsyncMock())
        updates_factory = Mock(return_value=updates)
        h=SimpleNamespace(data={},is_running=True,bus=SimpleNamespace(async_listen_once=Mock(return_value=Mock())),http=SimpleNamespace(async_register_static_paths=static),
            config_entries=SimpleNamespace(async_forward_entry_setups=AsyncMock(),
                async_unload_platforms_or_raise=AsyncMock(),async_reload=AsyncMock()))
        m=load("__init__.py",{**C,"__name__":"offline_init","__file__":str(ROOT/"__init__.py"),
            "Path":Path,"Platform":lambda p:p,"DeyeEMSCoordinator":Coordinator,
            "AppearanceManager": appearance_factory, "DATA_APPEARANCE": "deye_ems_appearance",
            "UpdateManager": updates_factory, "DATA_UPDATES": "deye_ems_updates",
            "EVENT_HOMEASSISTANT_STARTED": "homeassistant_started", "EVENT_HOMEASSISTANT_STOP": "homeassistant_stop",
            "StaticPathConfig":lambda *a:a,"async_register":Mock(),
            "frontend":SimpleNamespace(async_remove_panel=Mock()),
            "panel_custom":SimpleNamespace(async_register_panel=panel)})
        e=SimpleNamespace(entry_id="one",async_on_unload=Mock(),add_update_listener=Mock())
        self.assertIsNone(await m["async_setup_entry"](h,e))
        await m["async_unload_entry"](h,e)
        await m["async_setup_entry"](h,e)
        self.assertEqual(static.await_count,1)
        appearance_factory.assert_called_once_with(h)
        appearance.async_load.assert_awaited_once_with()
        self.assertIs(h.data["deye_ems_appearance"], appearance)
        updates_factory.assert_called_once_with(h)
        updates.async_check.assert_not_awaited()
        self.assertEqual(updates.async_start.call_count,2)
        updates.async_stop.assert_awaited_once_with()
        self.assertIs(h.data["deye_ems_updates"], updates)
        self.assertEqual(panel.await_count,2)
        self.assertTrue(panel.await_args.kwargs["require_admin"])
        self.assertEqual(panel.await_args.kwargs["webcomponent_name"],
            "deye-ems-panel-" + C["VERSION"].replace(".", "-"))
        self.assertIn("?v=" + C["VERSION"], panel.await_args.kwargs["module_url"])
        self.assertIn('const PANEL_TAG = "' + panel.await_args.kwargs["webcomponent_name"] + '"',
            (ROOT/"frontend/deye-ems-panel.js").read_text(encoding="utf-8"))
        self.assertEqual(e.runtime_data.mode,"shadow")

    async def test_manifest_platforms_and_bundled_panel_exist(self):
        manifest=json.loads((ROOT/"manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["config_flow"])
        self.assertEqual(manifest["requirements"],[])
        self.assertEqual(set(manifest["after_dependencies"]), {"esphome", "zeroconf"})
        for platform in C["PLATFORMS"]:
            self.assertTrue((ROOT/(platform+".py")).is_file())
        self.assertTrue((ROOT/"frontend/deye-ems-panel.js").is_file())

    async def test_release_translations_show_sidebar_notice_in_actual_initial_flow(self):
        """Verify the generated install artifact, including HA's English fallback."""
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary)
            shutil.copytree(ROOT, checkout/"custom_components/deye_ems",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            shutil.copy2(ROOT.parents[1]/"build_release.py", checkout/"build_release.py")
            output = subprocess.check_output([sys.executable, str(checkout/"build_release.py")],
                cwd=checkout, text=True, encoding="utf-8")
            with zipfile.ZipFile(json.loads(output)["archive"]) as archive:
                translations = {language: json.loads(archive.read(
                    f"custom_components/deye_ems/translations/{language}.json"))
                    for language in ("en", "pl")}
                self.assertEqual(translations["en"], json.loads(archive.read(
                    "custom_components/deye_ems/strings.json")))

        def leaves(value, prefix=""):
            return {key: text for name, child in value.items()
                for key, text in (leaves(child, prefix+name+".").items()
                    if isinstance(child, dict) else [(prefix+name, child)])}

        english, polish = (leaves(translations[language]) for language in ("en", "pl"))
        self.assertEqual(english.keys(), polish.keys(), "English fallback must cover every translated key")
        for key in english:
            placeholders = lambda text: {field for _, field, _, _ in Formatter().parse(text) if field}
            self.assertEqual(placeholders(english[key]), placeholders(polish[key]), key)
            self.assertNotIn("[%key:", english[key], "Custom integrations cannot compile references")

        flow = self.flow()["DeyeEMSConfigFlow"]()
        forms = [await flow.async_step_user(), await flow.async_step_user({"min_soc_percent": 1})]
        self.assertTrue(forms[1]["errors"], "Exercise the form after rejected input too")
        notices = {"pl": "Po instalacji panel Deye EMS znajdziesz w lewym menu Home Assistant",
            "en": "After installation, find the Deye EMS panel in the Home Assistant left menu"}
        for form in forms:
            self.assertEqual(form["type"], "form")
            fields = {marker.key for marker in form["data_schema"]}
            for language, translation in translations.items():
                step = translation["config"]["step"][form["step_id"]]
                description = step["description"].format_map(form["description_placeholders"])
                self.assertIn(notices[language], description.split("\n\n", 1)[0])
                self.assertTrue(step["title"])
                self.assertTrue(fields <= step["data"].keys(), "Actual form fields need translated labels")
                success = translation["config"]["create_entry"]["default"]
                self.assertIn(notices[language], success)
                self.assertIn("/deye-ems", success)

    async def test_phase_balancing_source_selector_accepts_switch_entities(self):
        flow = self.flow()["DeyeEMSOptionsFlow"]()
        flow.hass = SimpleNamespace(states=SimpleNamespace(get=lambda _: None))
        flow.config_entry = SimpleNamespace(runtime_data=SimpleNamespace(mode="shadow"), options={}, data={})
        result = await flow.async_step_sources()
        domains = {marker.key: field["args"][0]["domain"]
            for marker, field in result["data_schema"].items()}
        self.assertEqual(domains["asymmetric_phase_feeding"], "switch")
        self.assertEqual(domains["grid_power"], "sensor")

