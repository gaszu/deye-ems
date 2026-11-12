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
data_pl["entity_prefix"] = "Prefiks encji Deye"
data_pl["topology"] = "Układ instalacji"
data_pl.update({"ct_grid_power": "Wymiana z siecią na CT — suma (+ import, − eksport)",
    "battery_low_soc": "Battery low SOC — próg falownika (odczyt, rezerwa EMS co najmniej +5 p.p.)",
    "grid_power": "Port GRID falownika — suma (+ do falownika, − z falownika)",
    "load_power": "Wyjście LOAD/UPS — bez odbiorów między GRID a CT"})
for phase in (1, 2, 3):
    data_pl[f"ct_grid_l{phase}_power"] = f"Wymiana z siecią na CT — L{phase}"
data_pl.update({"name": "Nazwa odbiornika", "energy_entity": "Encja licznika energii",
    "asymmetric_phase_feeding": "Bilansowanie faz GRID w Deye — przełącznik stanu",
    "load_power": "Wyjście LOAD/UPS — bez odbiorów między GRID a CT",
    "grid_power": "Port GRID falownika (+ do falownika, − z falownika)",
    "power_entity": "Encja chwilowej mocy (opcjonalnie)",
    "included_in_load": "Zużycie jest już ujęte w głównym pomiarze LOAD",
    "load_id": "Odbiornik do usunięcia", "pv_forecast_mode": "Sposób interpretacji prognozy PV",
    "api_key": "Klucz API Solcast (puste pole zachowuje zapisany)",
    "resource_ids": "Identyfikatory instalacji Solcast (oddzielone przecinkami; puste = wykrywanie)",
    "poll_interval_minutes": "Odstęp pobierania (minuty)",
    "max_requests_per_day": "Limit zapytań konta na dobę UTC",
    "initial_requests_used": "Zapytania już wykorzystane dziś na koncie (UTC)",
    "dampening_factor": "Stały mnożnik korekty prognozy",
    "hourly_factors": "24 mnożniki godzinowe 00–23 (oddzielone spacjami; puste = 1)",
    "accept_manual_calibration": "Rozumiem zakres importu współczynników i brak kontynuacji poprzedniego samouczenia",
    "source_entry": "Obecna integracja Solcast"})
descriptions = {
    "topology": ("Topologia i moc falownika", "Wybierz miejsce pomiaru wymiany z siecią. Dla CWU między GRID a CT wybierz Zero Export To CT i w Źródłach przypisz osobno CT oraz port GRID (sumy i fazy). Oba kierunki dodatnie oznaczają pobór z sieci/do falownika. LOAD musi mierzyć samo wyjście LOAD/UPS. Moc znamionowa dotyczy całego falownika, łącznie domu i CWU. Wspólny limit jest limitem modelu; nie zapisuje ustawień mocy urządzenia. Brak zgodnych pomiarów blokuje sterowanie. Zmiana wymaga obserwacji, a wznowienie jest ręczne."),
    "entity_prefix": ("Prefiks encji Deye", "Wpisz część nazwy bez domeny, np. deye_inverter_ lub deye_dom_. Przykład: deye_dom_ tworzy sensor.deye_dom_load_power i number.deye_dom_maximum_battery_grid_charge_current. Następny ekran pokaże przypisania oraz znalezione i brakujące encje. Zapis następuje dopiero po zatwierdzeniu tego ekranu. Prefiks nie zmienia encji BMS, Solcast ani pompy."),
    "user": ("Deye EMS — własny silnik", "**Po dodaniu integracji panel Deye EMS znajdziesz na pasku bocznym Home Assistanta.**\n\nPanel jest dostępny dla administratorów. Jeśli nie widzisz wpisu, odśwież stronę lub sprawdź ustawienie „Panel boczny” w opcjach integracji oraz edycję paska bocznego HA. Bezpośredni adres panelu: `/deye-ems`.\n\nLokalny EMS bez EMHASS, helperów i automatyzacji. Minimalny bezpieczny SoC jest stałą rezerwą; cele pogodowe są osobne. Po dodaniu integracja tylko obserwuje. Encje i pozostałe parametry można uzupełnić później."),
    "parameters": ("Parametry silnika", "Rezerwa SoC obowiązuje we wszystkich slotach. Maksymalny cel musi być nie mniejszy niż rezerwa plus bufor."),
    "sources": ("Pomiary i sterowanie", "Wskaż istniejące encje Deye, YamBMS i prognoz PV. Wybrany LOAD powinien obejmować całe zużycie modelowanego domu; sprawdź zakres pomiaru dla topologii LOAD/CT. Kanałów odbiorników nie doliczamy ponownie. Nie są wymagane helpery ani automatyzacje EMS. Zmiany przypisań wykonuj w trybie obserwacji."),
    "add_load": ("Dodatkowe zużycia", "Dodaj pompę ciepła, CWU, klimatyzację lub inny odbiornik do modelowania prognozy SoC. Główny LOAD obejmuje całe zużycie domu; kanałów nie doliczamy ponownie. Licznik energii powinien podawać Wh lub kWh; pomiar mocy jest opcjonalny. Przełączniki ON/OFF i edycja są dostępne w panelu Deye EMS."),
    "remove_load": ("Usuń dodatkowe zużycie", "Usunięcie kanału nie usuwa encji źródłowej ani jej historii."),
    "solcast_manual": ("Solcast wewnątrz EMS", "Wbudowany klient nie wymaga osobnej integracji Solcast. Klucz i identyfikatory znajdziesz w toolkit.solcast.com.au. Moc AC/DC, kierunek i nachylenie paneli ustaw w portalu Solcast; EMS pobiera prognozę dla zapisanej tam instalacji. Zwykły limit Hobbyist: 10 zapytań na dobę UTC, każde pobranie dla każdej instalacji zużywa osobne zapytanie. Nie odpytuj równocześnie tego konta innym klientem. Przy nieznanym zużyciu pozostaw 10; klient zaczeka na nową dobę UTC. Wpisane zużycie nie zmniejsza rejestru; po zmianie konfiguracji może go podnieść. {import_note}"),
    "solcast_import": ("Import dostępnych ustawień Solcast", "Klucz, limit konta i wykluczenia są kopiowane lokalnie w HA. Kreator odczytuje bieżące współczynniki z sensora korekt przypisanego do wybranej integracji. Przenosi ich stan, bez pełnej historii i mechanizmu dalszego samouczenia. Prognozy sensorów HA są już skorygowane — nie korygujemy ich ponownie. Import nie wyłącza dotychczasowej integracji ani nie zeruje limitu konta."),
}
step_fields = {
    "topology": ["topology", "inverter_max_power_kw", "combined_output_limit_kw"],
    "user": ["min_soc_percent", "capacity_kwh", "pv_peak_kwp", "inverter_max_power_kw", "inverter_phase_max_power_kw", "grid_import_limit_kw", "grid_phase_limit_kw", "entity_prefix"],
    "entity_prefix": ["entity_prefix"],
    "parameters": [*const.OPTION_RANGES, "pv_forecast_mode"], "sources": list(const.DEFAULT_SOURCES),
    "add_load": ["name", "energy_entity", "power_entity"],
    "remove_load": ["load_id"],
    "solcast_manual": ["api_key", "resource_ids", "poll_interval_minutes", "max_requests_per_day", "initial_requests_used", "dampening_factor", "hourly_factors", "accept_manual_calibration"],
    "solcast_import": ["source_entry"],
}
steps = {key: {"title": title, "description": description, "data": {k: data_pl[k] for k in step_fields[key]}}
    for key, (title, description) in descriptions.items()}
steps["sources"]["description"] += "\n\n{prefix_preview}"
doc = {"title": "Deye EMS",
    "config": {"step": {"user": steps["user"]},
        "error": {"invalid_soc_limits": "Rezerwa SoC plus bufor przekracza maksymalny cel."},
        "abort": {"already_configured": "Integracja Deye EMS jest już skonfigurowana."}},
    "options": {"step": {key: steps[key] for key in descriptions if key != "user"},
        "error": {"invalid_soc_limits": "Rezerwa SoC plus bufor przekracza maksymalny cel.",
                  "duplicate_load": "Ten licznik energii jest już dodany.",
                  "pv_reference_required": "Wpisz moc referencyjną profilu przed włączeniem skalowania.",
                  "invalid_solcast": "Sprawdź klucz, identyfikatory oraz limity i mnożniki. Mnożników godzinowych musi być dokładnie 24, każdy od 0 do 2.",
                  "import_calibration_required": "Sprawdź zaimportowany stan korekt i potwierdź brak przeniesienia poprzedniego mechanizmu samouczenia."},
        "abort": {"no_extra_loads": "Brak dodatkowych odbiorników do usunięcia.",
            "stop_before_mapping": "Najpierw zatrzymaj sterowanie i wybierz obserwację. Następnie zmień przypisania lub odbiorniki."}}}
doc["options"]["abort"]["no_solcast_to_import"] = "Brak skonfigurowanej integracji solcast_solar. Wybierz ręczne połączenie."
doc["options"]["abort"]["solcast_import_incomplete"] = "Brak kompletnego, poprawnego odczytu korekt Solcast. Użyj ręcznej konfiguracji; brakujących współczynników nie zastępujemy zerem ani jedynką."
doc["options"]["step"]["sidebar"] = {"title": "Panel boczny", "description": "Pokaż lub ukryj Deye EMS w menu bocznym administratorów. Panel zawsze otworzysz pod adresem /deye-ems swojej instancji. Zapis nie przeładowuje sterownika ani nie zmienia sterowania. Jeżeli wpis został ukryty w osobistym profilu HA, przywróć go również w edycji menu bocznego.", "data": {"sidebar_visible": "Pokaż Deye EMS w panelu bocznym"}}
doc["options"]["abort"].update({"sidebar_saved": "Zapisano widoczność panelu. Otwórz /deye-ems lub odśwież menu boczne. Sterowanie pozostaje w dotychczasowym trybie.", "panel_not_ready": "Integracja nie zakończyła ładowania. Sprawdź jej stan i dzienniki HA."})
doc["options"]["error"]["sidebar_save_failed"] = "Nie udało się zapisać lub odświeżyć panelu. Spróbuj ponownie."
for section in ("config", "options"):
    doc[section]["error"]["invalid_entity_prefix"] = "Wpisz prefiks bez domeny, używając liter a–z, cyfr i podkreśleń, np. deye_dom_."
    doc[section]["error"]["reserve_below_low_soc"] = "Rezerwa EMS musi wynosić co najmniej Battery low SOC + 5 p.p. Bez poprawnego odczytu nie obniżaj rezerwy."
    doc[section]["error"]["battery_low_soc_unavailable"] = "Brak poprawnego odczytu Battery low SOC. Sprawdź przypisanie encji, stan i jednostkę %."
doc["options"]["step"]["init"] = {"title": "Deye EMS",
    "menu_options": {"parameters": "Parametry i bezpieczny SoC", "sources": "Encje pomiarowe i sterujące",
        "solcast": "Solcast — połączenie i ustawienia", "add_load": "Dodaj dodatkowe zużycie", "remove_load": "Usuń dodatkowe zużycie"}}
doc["options"]["step"]["solcast"] = {"title": "Solcast wewnątrz EMS", "menu_options": {
    "solcast_manual": "Połącz / zmień ustawienia", "solcast_import": "Importuj dostępne ustawienia z HA",
    "solcast_disable": "Wyłącz pobieranie przez EMS", "sidebar": "Panel boczny", "entity_prefix": "Prefiks encji Deye", "topology": "Topologia i moc falownika"}}
doc["options"]["abort"]["invalid_topology"] = "Wybierz poprawną topologię instalacji."
COMPONENT.joinpath("translations").mkdir(exist_ok=True)
for path in (COMPONENT/"strings.json", COMPONENT/"translations/pl.json"):
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")
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
    for name in ("README.md","INSTALL.md","MIGRATION.md","VALIDATION.md","SPECIFICATION.md","LICENSE"):
        if (ROOT/name).is_file():
            z.write(ROOT/name,name)
with zipfile.ZipFile(archive) as z:
    assert "custom_components/deye_ems/manifest.json" in z.namelist()
    assert not any("test" in p or "__pycache__" in p for p in z.namelist())
print(json.dumps({"archive": str(archive), "bytes": archive.stat().st_size,
    "files": len(zipfile.ZipFile(archive).namelist()), "version": manifest["version"]}))

