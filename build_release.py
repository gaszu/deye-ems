"""Build a standalone ZIP; only integration sources and public docs are included."""
import ast
import importlib.util
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
COMPONENT = ROOT / "custom_components" / "deye_ems"
spec = importlib.util.spec_from_file_location("ems_release_constants", COMPONENT / "const.py")
const = importlib.util.module_from_spec(spec)
spec.loader.exec_module(const)

data_pl = dict(const.OPTION_LABELS)
data_pl.update({key: key.replace("_", " ") for key in const.DEFAULT_SOURCES})
data_pl.update({"name": "Nazwa odbiornika", "energy_entity": "Encja licznika energii",
    "power_entity": "Encja chwilowej mocy (opcjonalnie)",
    "included_in_load": "Zużycie jest już ujęte w głównym pomiarze LOAD",
    "load_id": "Odbiornik do usunięcia"})
descriptions = {
    "user": ("Deye EMS — własny silnik", "Lokalny EMS bez EMHASS, helperów i automatyzacji. Minimalny bezpieczny SoC jest stałą rezerwą; cele pogodowe są osobne. Po dodaniu integracja tylko obserwuje. Encje i pozostałe parametry można uzupełnić później."),
    "parameters": ("Parametry silnika", "Rezerwa SoC obowiązuje we wszystkich slotach. Maksymalny cel musi być nie mniejszy niż rezerwa plus bufor."),
    "sources": ("Pomiary i sterowanie", "Wskaż istniejące encje Deye, YamBMS i prognoz PV. Nie są wymagane żadne helpery ani automatyzacje EMS. Zmiany przypisań wykonuj w trybie obserwacji."),
    "add_load": ("Dodatkowe zużycia", "Dodaj pompę ciepła, CWU, klimatyzację lub inny odbiornik. Licznik energii powinien podawać Wh lub kWh. Zaznaczenie LOAD zapobiega podwójnemu doliczaniu. Odbiornik poza LOAD wymaga również pomiaru mocy dla ograniczania importu."),
    "remove_load": ("Usuń dodatkowe zużycie", "Usunięcie kanału nie usuwa encji źródłowej ani jej historii."),
}
step_fields = {
    "user": ["min_soc_percent", "capacity_kwh", "grid_import_limit_kw", "grid_phase_limit_kw"],
    "parameters": list(const.OPTION_RANGES), "sources": list(const.DEFAULT_SOURCES),
    "add_load": ["name", "energy_entity", "power_entity", "included_in_load"],
    "remove_load": ["load_id"],
}
steps = {key: {"title": title, "description": description, "data": {k: data_pl[k] for k in step_fields[key]}}
    for key, (title, description) in descriptions.items()}
doc = {"title": "Deye EMS",
    "config": {"step": {"user": steps["user"]},
        "error": {"invalid_soc_limits": "Rezerwa SoC plus bufor przekracza maksymalny cel."},
        "abort": {"already_configured": "Integracja Deye EMS jest już skonfigurowana."}},
    "options": {"step": {key: steps[key] for key in descriptions if key != "user"},
        "error": {"invalid_soc_limits": "Rezerwa SoC plus bufor przekracza maksymalny cel.",
                  "duplicate_load": "Ten licznik energii jest już dodany."},
        "abort": {"no_extra_loads": "Brak dodatkowych odbiorników do usunięcia.",
            "stop_before_mapping": "Najpierw zatrzymaj sterowanie i wybierz obserwację. Następnie zmień przypisania lub odbiorniki."}}}
doc["options"]["step"]["init"] = {"title": "Deye EMS",
    "menu_options": {"parameters": "Parametry i bezpieczny SoC", "sources": "Encje pomiarowe i sterujące",
        "add_load": "Dodaj dodatkowe zużycie", "remove_load": "Usuń dodatkowe zużycie"}}
COMPONENT.joinpath("translations").mkdir(exist_ok=True)
for path in (COMPONENT/"strings.json", COMPONENT/"translations/pl.json"):
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
ROOT.joinpath("hacs.json").write_text(json.dumps({"name":"Deye EMS","homeassistant":"2026.11.0","render_readme":True}, indent=2)+"\n",encoding="utf-8")

manifest = json.loads((COMPONENT/"manifest.json").read_text(encoding="utf-8"))
for path in COMPONENT.rglob("*.py"):
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
for path in COMPONENT.rglob("*.json"):
    json.loads(path.read_text(encoding="utf-8"))
assert manifest["domain"] == "deye_ems" and manifest["config_flow"]
assert manifest["requirements"] == []
for platform in const.PLATFORMS:
    assert COMPONENT.joinpath(platform+".py").is_file(), platform

dist = ROOT/"dist"
dist.mkdir(exist_ok=True)
archive = dist/f"deye-ems-{manifest['version']}.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
    for path in sorted(COMPONENT.rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            z.write(path, path.relative_to(ROOT).as_posix())
    for name in ("README.md","INSTALL.md","MIGRATION.md","VALIDATION.md","LICENSE"):
        if (ROOT/name).is_file():
            z.write(ROOT/name,name)
with zipfile.ZipFile(archive) as z:
    assert "custom_components/deye_ems/manifest.json" in z.namelist()
    assert not any("test" in p or "__pycache__" in p for p in z.namelist())
print(json.dumps({"archive": str(archive), "bytes": archive.stat().st_size,
    "files": len(zipfile.ZipFile(archive).namelist()), "version": manifest["version"]}))

