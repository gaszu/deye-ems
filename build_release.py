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
data_pl["battery_source_profile"] = "Źródło danych baterii — Deye / opcjonalny YamBMS / własne"
data_pl.update({"soc": "Poziom naładowania baterii (%)", "voltage": "Napięcie baterii (V)",
    "bms_charge_current": "Bieżący dopuszczalny prąd ładowania BMS (A)",
    "bms_blocking_charge": "Blokada ładowania YamBMS / własna (0 = zgoda; opcjonalna w profilu Deye)",
    "battery_alarm": "Deye — alarm baterii (OFF = brak alarmu)",
    "battery_fault": "Deye — błąd baterii (OFF = brak błędu)"})
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
    "entity_prefix": ("Prefiks encji Deye", "Wpisz część nazwy bez domeny, np. deye_inverter_ lub deye_dom_. Przykład: deye_dom_ tworzy sensor.deye_dom_load_power i number.deye_dom_maximum_battery_grid_charge_current. Następny ekran pokaże przypisania oraz znalezione i brakujące encje. Zapis następuje dopiero po zatwierdzeniu tego ekranu. Profil Deye korzysta z odczytów baterii falownika. YamBMS jest opcją; profil własny zachowuje ręczne przypisania. Prefiks nie zmienia Solcast ani dodatkowych odbiorników."),
    "user": ("Panel w lewym menu Home Assistant", "**Po instalacji panel Deye EMS znajdziesz w lewym menu Home Assistant.**\n\nPanel jest dostępny dla administratorów. Jeśli nie widzisz wpisu, odśwież stronę lub sprawdź ustawienie „Panel boczny” w opcjach integracji oraz edycję paska bocznego HA. Bezpośredni adres panelu: `/deye-ems`.\n\nLokalny EMS bez EMHASS, helperów i automatyzacji. Minimalny bezpieczny SoC jest stałą rezerwą; cele pogodowe są osobne. Po dodaniu integracja tylko obserwuje. Encje i pozostałe parametry można uzupełnić później."),
    "parameters": ("Parametry silnika", "Rezerwa SoC obowiązuje we wszystkich slotach. Maksymalny cel musi być nie mniejszy niż rezerwa plus bufor."),
    "sources": ("Pomiary i sterowanie", "Wskaż istniejące encje Deye albo opcjonalnego YamBMS oraz prognoz PV. Wybrany LOAD powinien obejmować całe zużycie modelowanego domu; sprawdź zakres pomiaru dla topologii LOAD/CT. Kanałów odbiorników nie doliczamy ponownie. Nie są wymagane helpery ani automatyzacje EMS. Zmiany przypisań wykonuj w trybie obserwacji."),
    "add_load": ("Dodatkowe zużycia", "Dodaj pompę ciepła, CWU, klimatyzację lub inny odbiornik do modelowania prognozy SoC. Główny LOAD obejmuje całe zużycie domu; kanałów nie doliczamy ponownie. Licznik energii powinien podawać Wh lub kWh; pomiar mocy jest opcjonalny. Przełączniki ON/OFF i edycja są dostępne w panelu Deye EMS."),
    "remove_load": ("Usuń dodatkowe zużycie", "Usunięcie kanału nie usuwa encji źródłowej ani jej historii."),
    "solcast_manual": ("Solcast wewnątrz EMS", "Wbudowany klient nie wymaga osobnej integracji Solcast. Klucz i identyfikatory znajdziesz w toolkit.solcast.com.au. Moc AC/DC, kierunek i nachylenie paneli ustaw w portalu Solcast; EMS pobiera prognozę dla zapisanej tam instalacji. Zwykły limit Hobbyist: 10 zapytań na dobę UTC, każde pobranie dla każdej instalacji zużywa osobne zapytanie. Nie odpytuj równocześnie tego konta innym klientem. Przy nieznanym zużyciu pozostaw 10; klient zaczeka na nową dobę UTC. Wpisane zużycie nie zmniejsza rejestru; po zmianie konfiguracji może go podnieść. {import_note}"),
    "solcast_import": ("Import dostępnych ustawień Solcast", "Klucz, limit konta i wykluczenia są kopiowane lokalnie w HA. Kreator odczytuje bieżące współczynniki z sensora korekt przypisanego do wybranej integracji. Przenosi ich stan, bez pełnej historii i mechanizmu dalszego samouczenia. Prognozy sensorów HA są już skorygowane — nie korygujemy ich ponownie. Import nie wyłącza dotychczasowej integracji ani nie zeruje limitu konta."),
}
step_fields = {
    "topology": ["topology", "inverter_max_power_kw", "combined_output_limit_kw"],
    "user": ["min_soc_percent", "capacity_kwh", "pv_peak_kwp", "inverter_max_power_kw", "inverter_phase_max_power_kw", "grid_import_limit_kw", "grid_phase_limit_kw", "entity_prefix", "battery_source_profile"],
    "entity_prefix": ["entity_prefix", "battery_source_profile"],
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
doc["options"]["step"]["sidebar"]["data_description"] = {"sidebar_visible": "Po instalacji panel Deye EMS znajdziesz w lewym menu Home Assistant. Widoczny dla administratorów; bezpośredni adres: /deye-ems."}
doc["config"]["create_entry"] = {"default": "Po instalacji panel Deye EMS znajdziesz w lewym menu Home Assistant. Otwórz Deye EMS lub przejdź do /deye-ems. Panel jest dostępny dla administratorów. Integracja rozpoczyna pracę w obserwacji."}
doc["options"]["abort"].update({"sidebar_saved": "Zapisano widoczność panelu. Otwórz /deye-ems lub odśwież menu boczne. Sterowanie pozostaje w dotychczasowym trybie.", "panel_not_ready": "Integracja nie zakończyła ładowania. Sprawdź jej stan i dzienniki HA."})
doc["options"]["error"]["sidebar_save_failed"] = "Nie udało się zapisać lub odświeżyć panelu. Spróbuj ponownie."
for section in ("config", "options"):
    doc[section]["error"]["invalid_entity_prefix"] = "Wpisz prefiks bez domeny, używając liter a–z, cyfr i podkreśleń, np. deye_dom_."
    doc[section]["error"]["reserve_below_low_soc"] = "Rezerwa EMS musi wynosić co najmniej Battery low SOC + 5 p.p. Bez poprawnego odczytu nie obniżaj rezerwy."
    doc[section]["error"]["battery_low_soc_unavailable"] = "Brak poprawnego odczytu Battery low SOC. Sprawdź przypisanie encji, stan i jednostkę %."
doc["options"]["step"]["init"] = {"title": "Deye EMS",
    "menu_options": {"parameters": "Parametry i bezpieczny SoC", "sources": "Encje pomiarowe i sterujące",
        "solcast": "Solcast — połączenie i ustawienia", "add_load": "Dodaj dodatkowe zużycie", "remove_load": "Usuń dodatkowe zużycie",
        "sidebar": "Panel boczny", "entity_prefix": "Prefiks encji Deye", "topology": "Topologia i moc falownika"}}
doc["options"]["step"]["solcast"] = {"title": "Solcast wewnątrz EMS", "menu_options": {
    "solcast_manual": "Połącz / zmień ustawienia", "solcast_import": "Importuj dostępne ustawienia z HA",
    "solcast_disable": "Wyłącz pobieranie przez EMS"}}
doc["options"]["abort"]["invalid_topology"] = "Wybierz poprawną topologię instalacji."

# Custom integrations load translations/<language>.json, never strings.json.
# Ship a complete English fallback as well as the Polish UI.
labels_en = {key: key.replace("_", " ") for key in data_pl}
labels_en.update({
    "battery_source_profile": "Battery data source — Deye / optional YamBMS / manual",
    "soc": "Battery state of charge (%)", "voltage": "Battery voltage (V)",
    "bms_charge_current": "Current BMS charge allowance (A)",
    "bms_blocking_charge": "YamBMS / custom charge blocking (0 = permitted; optional in Deye profile)",
    "battery_alarm": "Deye battery alarm (OFF = clear)",
    "battery_fault": "Deye battery fault (OFF = clear)",
    "combined_output_limit_kw": "Combined model limit for LOAD and consumers before GRID",
    "min_soc_percent": "Minimum safe SoC", "capacity_kwh": "Battery capacity",
    "pv_peak_kwp": "Installed PV capacity", "pv_forecast_reference_kwp": "Forecast reference PV capacity",
    "grid_import_limit_kw": "Maximum grid import", "grid_phase_limit_kw": "Grid import limit per phase",
    "inverter_max_power_kw": "Total inverter power", "inverter_phase_max_power_kw": "Inverter power per phase",
    "reserve_margin_soc_percent": "Additional forecast reserve", "winter_weather_soc_percent": "Winter target with poor PV forecast",
    "discharge_max_kw": "Model battery discharge limit", "grid_max_soc_percent": "Maximum grid charging target",
    "battery_source_profile": "Battery data source — Deye / optional YamBMS / manual",
    "entity_prefix": "Deye entity prefix", "topology": "Installation topology",
    "ct_grid_power": "CT grid exchange total (+ import, - export)",
    "battery_low_soc": "Inverter Battery low SOC (EMS reserve at least 5 percentage points higher)",
    "grid_power": "Inverter GRID port (+ into inverter, - out of inverter)",
    "load_power": "LOAD/UPS output excluding consumers between GRID and CT",
    "name": "Consumer name", "energy_entity": "Energy meter entity",
    "asymmetric_phase_feeding": "Deye grid phase balancing status switch",
    "power_entity": "Instantaneous power entity (optional)",
    "included_in_load": "Consumption is already included in the main LOAD measurement",
    "load_id": "Consumer to remove", "pv_forecast_mode": "PV forecast interpretation",
    "api_key": "Solcast API key (leave blank to keep saved key)",
    "resource_ids": "Solcast site IDs (comma separated; blank for discovery)",
    "poll_interval_minutes": "Polling interval (minutes)", "max_requests_per_day": "Daily account request limit (UTC)",
    "initial_requests_used": "Requests already used today (UTC)", "dampening_factor": "Fixed forecast correction multiplier",
    "hourly_factors": "24 hourly multipliers 00-23 (space separated; blank for 1)",
    "accept_manual_calibration": "I understand the imported corrections and that previous self-learning will not continue",
    "source_entry": "Existing Solcast integration", "sidebar_visible": "Show Deye EMS in the sidebar",
})
descriptions_en = {
    "topology": ("Topology and inverter power", "Choose where grid exchange is measured. For hot water consumers between GRID and CT, choose Zero Export To CT and map CT and GRID separately, including totals and phases. Positive power means import into the home or inverter. LOAD must measure only the LOAD/UPS output. Rated power covers the entire inverter, home and hot water. The combined limit is a model limit; it does not write device power settings. Inconsistent measurements block control. Changes require observation; resume control explicitly."),
    "entity_prefix": ("Deye entity prefix", "Enter the entity name prefix without a domain, for example deye_inverter_ or deye_home_. The next screen previews mapped, found and missing entities. Nothing is saved until you confirm that screen. Deye uses battery readings from the inverter. YamBMS is optional; manual mode keeps custom mappings. The prefix does not affect Solcast or additional consumers."),
    "user": ("Panel in the Home Assistant left menu", "**After installation, find the Deye EMS panel in the Home Assistant left menu.**\n\nThe panel is available to administrators. If it is missing, refresh the page and check Sidebar in the integration options and your Home Assistant sidebar settings. Direct panel path: `/deye-ems`.\n\nA local EMS without EMHASS, helpers or automations. Minimum safe SoC is a fixed reserve; weather targets are separate. The integration starts in observation. You can configure entities and other parameters later."),
    "parameters": ("Engine parameters", "The SoC reserve applies to every slot. The maximum target must be at least the reserve plus its margin."),
    "sources": ("Measurements and control", "Select existing Deye or optional YamBMS entities and PV forecast entities. LOAD must cover the total modeled home consumption; verify its scope for the LOAD/CT topology. Do not add consumer channels to the total again. No EMS helpers or automations are required. Change mappings in observation mode.\n\n{prefix_preview}"),
    "add_load": ("Additional consumption", "Add a heat pump, hot water, air conditioning or other consumer to the SoC forecast model. Main LOAD already includes home consumption; channels are not added to it again. Energy meters must report Wh or kWh; power measurement is optional. Enable, disable and edit channels in the Deye EMS panel."),
    "remove_load": ("Remove additional consumption", "Removing a channel does not delete its source entity or history."),
    "solcast_manual": ("Solcast inside EMS", "The built-in client does not need a separate Solcast integration. Find your key and site IDs in the Solcast toolkit. Configure AC/DC power, orientation and tilt in the Solcast portal. A typical Hobbyist limit is 10 requests per UTC day; every fetch for every site consumes a request. Do not use another client on the same account at the same time. If usage is unknown, leave 10; the client waits for the next UTC day. Entered usage never reduces recorded usage. {import_note}"),
    "solcast_import": ("Import available Solcast settings", "The key, account limit and exclusions are copied locally in Home Assistant. Current correction factors are read from the selected integration correction sensor. Only their current state is imported, without full history or continued self-learning. Home Assistant sensor forecasts are already corrected and are not corrected again. Import does not disable the other integration or reset account usage."),
    "sidebar": ("Sidebar", "Show or hide Deye EMS in the administrator sidebar. You can always open /deye-ems on your instance. Saving does not reload the controller or change its operating mode. If your personal Home Assistant sidebar settings hide the panel, restore it there too."),
}
doc_en = json.loads(json.dumps(doc))
for section in ("config", "options"):
    for step_id, step in doc_en[section]["step"].items():
        if step_id in descriptions_en:
            step["title"], step["description"] = descriptions_en[step_id]
        if "data" in step:
            step["data"] = {key: labels_en[key] for key in step["data"]}
doc_en["options"]["step"]["sidebar"]["data_description"] = {"sidebar_visible": "After installation, find Deye EMS in the Home Assistant left menu. Available to administrators; direct path: /deye-ems."}
menu_en = {"parameters": "Parameters and safe SoC", "sources": "Measurement and control entities",
    "solcast": "Solcast connection and settings", "add_load": "Add consumption", "remove_load": "Remove consumption",
    "sidebar": "Sidebar", "entity_prefix": "Deye entity prefix", "topology": "Topology and inverter power",
    "solcast_manual": "Connect or change settings", "solcast_import": "Import available settings from Home Assistant",
    "solcast_disable": "Disable EMS forecast polling"}
for step_id in ("init", "solcast"):
    step = doc_en["options"]["step"][step_id]
    step["title"] = "Deye EMS" if step_id == "init" else "Solcast inside EMS"
    step["menu_options"] = {key: menu_en[key] for key in step["menu_options"]}
errors_en = {
    "invalid_soc_limits": "The SoC reserve plus its margin exceeds the maximum target.",
    "duplicate_load": "This energy meter has already been added.",
    "pv_reference_required": "Enter the forecast reference capacity before enabling scaling.",
    "invalid_solcast": "Check the key, site IDs, limits and multipliers. Provide exactly 24 hourly multipliers, each between 0 and 2.",
    "import_calibration_required": "Review the imported corrections and confirm that previous self-learning will not continue.",
    "sidebar_save_failed": "Could not save or refresh the panel. Try again.",
    "invalid_entity_prefix": "Enter a prefix without a domain using a-z, digits and underscores, for example deye_home_.",
    "reserve_below_low_soc": "The EMS reserve must be at least Battery low SOC plus 5 percentage points. Do not lower it without a valid reading.",
    "battery_low_soc_unavailable": "No valid Battery low SOC reading. Check the mapped entity, its state and percent unit.",
}
aborts_en = {
    "already_configured": "Deye EMS is already configured.",
    "no_extra_loads": "No additional consumption channels to remove.",
    "stop_before_mapping": "Stop control and select observation before changing mappings or consumers.",
    "no_solcast_to_import": "No configured solcast_solar integration. Choose manual connection.",
    "solcast_import_incomplete": "Could not read complete valid Solcast corrections. Use manual configuration; missing factors are not replaced with zero or one.",
    "sidebar_saved": "Panel visibility saved. Open /deye-ems or refresh the sidebar. The operating mode is unchanged.",
    "panel_not_ready": "The integration has not finished loading. Check its status and Home Assistant logs.",
    "invalid_topology": "Choose a valid installation topology.",
}
for section in ("config", "options"):
    doc_en[section]["error"] = {key: errors_en[key] for key in doc[section]["error"]}
    doc_en[section]["abort"] = {key: aborts_en[key] for key in doc[section]["abort"]}
doc_en["config"]["create_entry"] = {"default": "After installation, find the Deye EMS panel in the Home Assistant left menu. Open Deye EMS or go to /deye-ems. The panel is available to administrators. The integration starts in observation."}
COMPONENT.joinpath("translations").mkdir(exist_ok=True)
for path, content in ((COMPONENT/"strings.json", doc_en), (COMPONENT/"translations/en.json", doc_en),
        (COMPONENT/"translations/pl.json", doc)):
    path.write_text(json.dumps(content, ensure_ascii=False, indent=2)+"\n", encoding="utf-8", newline="\n")
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

