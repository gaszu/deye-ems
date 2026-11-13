/* Deye EMS panel: native web component, no CDN, framework or external service. */
const PANEL_TAG = "deye-ems-panel-2-0-1";
const PANEL_VERSION = "2.0.1";
const labels = {
  min_soc_percent: "Minimalny bezpieczny SoC (%)",
  capacity_kwh: "Pojemność magazynu (kWh)",
  pv_peak_kwp: "Moc paneli PV (kWp)",
  pv_forecast_reference_kwp: "Moc referencyjna profilu PV (kWp)",
  grid_import_limit_kw: "Moc przyłącza — maksymalny pobór z sieci (kW)",
  grid_phase_limit_kw: "Limit przyłącza na fazę (kW)",
  inverter_max_power_kw: "Moc falownika łącznie (kW)",
  inverter_phase_max_power_kw: "Dopuszczalna moc na fazę (kW)",
  reserve_margin_soc_percent: "Bufor prognozy (p.p.)",
  winter_weather_soc_percent: "Zimowy cel przy słabym PV (%)",
  discharge_max_kw: "Modelowy limit rozładowania (kW)",
  grid_max_soc_percent: "Maksymalny cel ładowania z sieci (%)"
};
const ranges = {
  min_soc_percent:[5,90,1], capacity_kwh:[1,1000,.1],
  pv_peak_kwp:[.1,1000,.1],pv_forecast_reference_kwp:[.1,1000,.1],
  grid_import_limit_kw:[1,30,.1],grid_phase_limit_kw:[.5,15,.1],
  inverter_max_power_kw:[.1,1000,.1],inverter_phase_max_power_kw:[.1,500,.1],
  reserve_margin_soc_percent:[0,10,1],winter_weather_soc_percent:[45,95,1],
  discharge_max_kw:[.1,12,.1],grid_max_soc_percent:[45,95,1]
};
const reasons = {
  planned:"Plan gotowy", initializing:"Uruchamianie", shadow:"Obserwacja",
  telemetry_invalid:"Brak poprawnych, świeżych pomiarów",
  bms_blocked:"BMS blokuje ładowanie", grid_headroom:"Ograniczenie poborem z sieci",
  connection_other_phase_headroom:"Ograniczenie przyłącza na fazie poza falownikiem — ładowanie wstrzymane",
  deye_charge_cap:"Limit Deye po odjęciu 5%", actuator_cap:"Zakres nastawy ładowania w Deye",
  inverter_grid_headroom:"Limit mocy pobieranej przez port GRID falownika",
  inverter_grid_load_headroom:"Zapas portu GRID po zasileniu LOAD",
  load_headroom:"Priorytet zasilania domu", bms_cap:"Limit baterii / falownika",converter_cap:"Limit mocy konwersji falownika",
  battery_charge_headroom:"Ograniczenie łącznej mocy ładowania baterii",
  ramp_up:"Stopniowe zwiększanie prądu", ramp_down:"Stopniowe zmniejszanie prądu",
  scheduled_hold:"Oczekiwanie na dozwolony termin korekty prądu", scheduled_setpoint:"Wyliczona nastawa na bieżące pół godziny",
  initial_charge_start:"Przygotowanie pierwszego startu ładowania w tanim oknie",
  scheduled_retry:"Ponowienie niepotwierdzonej nastawy", scheduled_deadband:"Zmiana mniejsza niż 10 A — utrzymanie nastawy",
  recovery_wait:"Oczekiwanie na 2 minuty stabilnych warunków", target_hysteresis:"Cel osiągnięty — wznowienie po spadku o 2 p.p. SoC",
  ramp_wait:"Historyczna przerwa regulacji", target_reached:"Cel SoC osiągnięty",
  pv_covers_charge_need:"PV pokrywa potrzebę ładowania",
  dispatch_retry_wait:"Oczekiwanie po niewysłanej próbie", dispatch_history_unknown:"Weryfikacja historii poleceń",
  grid_step_headroom:"Za mały zapas sieci na zwiększenie prądu", grid_start_headroom:"Ograniczenie prądu przed włączeniem ładowania",
  pending_current_invalid:"Brak poprawnego potwierdzenia poprzedniej nastawy",
  pending_readback:"Oczekiwanie na odczyt nastawy", safety_hold:"Nastawa bezpieczna",
  awaiting_readback:"Oczekiwanie na odczyt nastawy", retry_unconfirmed:"Ponowienie niepotwierdzonej nastawy",
  waiting_setting_readback:"Oczekiwanie na odczyt nastawy", deadband:"Nastawa w dopuszczalnym przedziale",
  ledger_missing_or_future:"Brak poprawnego rejestru poprzedniej próby",
  window_or_policy_blocked:"Ładowanie z sieci teraz niedozwolone",
  hardware_mode_mismatch:"Tryby falownika wymagają sprawdzenia",
  owner_conflict:"Działa inny sterownik", ownership_conflict:"Konflikt sterowników",
  forecast_energy_or_power_deficit:"Prognoza wskazuje niedobór energii lub mocy",
  no_grid_permission:"Brak zgody na ładowanie z sieci", solar_reserve_sufficient:"Wystarcza zapas ze słońca"
};
const esc = v => String(v ?? "—").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const numeric = v => (typeof v === "number" || typeof v === "string" && v.trim() !== "") && Number.isFinite(Number(v)) ? Number(v) : null;
const num = (v,d=1) => numeric(v) === null ? "—" : numeric(v).toLocaleString("pl-PL",{maximumFractionDigits:d});
const time = v => v && Number.isFinite(new Date(v).getTime()) ? new Date(v).toLocaleString("pl-PL",{timeZone:"Europe/Warsaw",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit"}) : "—";
const releaseVersion = value => typeof value==="string"&&/^(0|[1-9]\d{0,4})\.(0|[1-9]\d{0,4})\.(0|[1-9]\d{0,4})$/.test(value)?value:null;
const compareVersions = (a,b) => {const left=a.split(".").map(Number),right=b.split(".").map(Number);for(let i=0;i<3;i++)if(left[i]!==right[i])return Math.sign(left[i]-right[i]);return 0;};
const updateTimestamp = value => typeof value==="string"&&/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(value)&&Number.isFinite(Date.parse(value))?Date.parse(value):null;
const solcastFields = {
  api_key:"Klucz API Solcast",resource_ids:"Identyfikatory instalacji (puste: wykrywanie)",
  poll_interval_minutes:"Odstęp pobierania (minuty)",max_requests_per_day:"Limit zapytań na dobę UTC",
  initial_requests_used:"Zapytania już wykorzystane dziś na koncie (UTC)",dampening_factor:"Stały mnożnik korekty",
  hourly_factors:"24 mnożniki godzinowe (puste: 1)",source_entry:"Integracja Solcast do importu",
  accept_manual_calibration:"Rozumiem zakres importu i brak dalszego samouczenia"
};
const solcastMessages = {
  invalid_solcast:"Sprawdź klucz, identyfikatory, limity i mnożniki. Podaj dokładnie 24 poprawne mnożniki albo pozostaw pole puste.",
  import_calibration_required:"Potwierdź zakres importowanej kalibracji przed zapisaniem.",
  no_solcast_to_import:"Nie znaleziono skonfigurowanej integracji Solcast do importu. Możesz połączyć konto ręcznie.",
  solcast_import_incomplete:"Brakuje poprawnego odczytu kalibracji źródłowej. Uzupełnij ją w źródle albo połącz konto ręcznie.",
  stop_before_mapping:"Przełącz EMS w tryb obserwacji przed zmianą Solcast.",
  already_in_progress:"Kreator jest już otwarty. Zamknij poprzednią konfigurację i spróbuj ponownie."
};
const sourceLabels = {
  soc:"SoC baterii",voltage:"Napięcie baterii",battery_power:"Moc baterii",bms_charge_current:"Dopuszczalny prąd ładowania baterii",bms_blocking_charge:"Blokada ładowania baterii",
  grid_power:"Moc portu GRID",load_power:"Moc LOAD",grid_current_number:"Nastawa prądu ładowania z sieci",max_charge_current_number:"Maksymalny prąd ładowania Deye",battery_low_soc:"Battery low SOC",
  ct_grid_power:"Wymiana z siecią na CT",pv_today:"Prognoza PV na dziś",pv_tomorrow:"Prognoza PV na jutro",pv_day3:"Prognoza PV na pojutrze",
  pc_energy_total:"Opcjonalny odbiornik — licznik energii",pc_energy_today:"Opcjonalny odbiornik — energia dziś",pc_energy_yesterday:"Opcjonalny odbiornik — energia wczoraj",
  solar_sell:"Sprzedaż energii PV",tou_enabled:"Harmonogram TOU",energy_priority:"Priorytet energii",work_mode:"Tryb pracy falownika",asymmetric_phase_feeding:"Bilansowanie faz GRID"
};
const sourceMessages = {
  invalid_entity_prefix:"Wpisz prefiks bez domeny, np. deye_dom_. Użyj liter a–z, cyfr i podkreśleń.",
  invalid_battery_source_profile:"Wybierz źródło danych baterii z listy.",
  stop_before_mapping:"Przełącz EMS w tryb obserwacji przed zmianą prefiksu lub przypisań.",
  already_in_progress:"Kreator jest już otwarty. Zamknij poprzednią konfigurację i spróbuj ponownie."
};
const hardwareLabels={inverter_model:"Model falownika",inverter_phases:"Liczba faz falownika (dla konfiguracji własnej)",connection_phases:"Liczba faz przyłącza",inverter_phase:"Faza podłączenia falownika jednofazowego",confirm_model:"Potwierdzam zapis wybranego modelu i ograniczeń po sprawdzeniu podglądu"};
const hardwareMessages={
  stop_before_mapping:"Przełącz EMS w tryb obserwacji przed zmianą modelu falownika.",
  invalid_inverter_model:"Wybierz dostępny model lub konfigurację własną.",
  invalid_inverter_phases:"Wybierz jedną lub trzy fazy falownika.",
  invalid_connection_phases:"Liczba faz przyłącza musi odpowiadać podłączeniu falownika.",
  invalid_inverter_phase:"Wybierz poprawną fazę podłączenia; dla przyłącza jednofazowego wybierz L1.",
  inverter_model_phase_mismatch:"Liczba faz nie odpowiada wybranemu modelowi.",
  invalid_inverter_limits:"Sprawdź limity mocy falownika.",
  confirm_model_required:"Sprawdź podgląd i zaznacz potwierdzenie przed zapisaniem.",
  already_in_progress:"Kreator jest już otwarty. Zamknij poprzednią konfigurację i spróbuj ponownie."
};

class DeyeEMSPanel extends HTMLElement {
  telemetryExpanded=false;
  hardwareOpen=false;hardwareBusy=false;hardwareCommitting=false;hardwareFlow=null;
  hardwareDraft={};hardwareError="";hardwareNotice="";hardwareSequence=0;
  constructor(){super();this.attachShadow({mode:"open"});this.busy=false;this.error="";this.payload=null;this.drafts={};this.requestSequence=0;this.loadDraft=null;this.loadDelete=null;this.loadError="";this.solcastOpen=false;this.solcastBusy=false;this.solcastCommitting=false;this.solcastFlow=null;this.solcastDraft={};this.solcastSecret="";this.solcastError="";this.solcastNotice="";this.solcastSequence=0;this.solcastConfirmDisable=false;this.solcastRefreshTimer=null;this.solcastSavedAt=0;this.appearanceDraft=null;this.appearanceError="";this.appliedThemeValues=new Map();this.appearanceMissing=false;this.updatesBusy=false;this.updatesError="";this.updatesSequence=0;this.sourceOpen=false;this.sourceBusy=false;this.sourceCommitting=false;this.sourceFlow=null;this.sourceDraft={};this.sourceError="";this.sourceNotice="";this.sourceSequence=0;}
  set hass(value){this._hass=value;const themeChanged=this.applyPanelTheme();if(this.isConnected&&!this.started){this.started=true;this.refresh();this.timer=setInterval(()=>this.refresh(),10000);}else if(themeChanged)this.render();}
  connectedCallback(){if(this._hass&&!this.started){this.started=true;this.refresh();this.timer=setInterval(()=>this.refresh(),10000);}else this.render();}
  disconnectedCallback(){++this.updatesSequence;this.updatesBusy=false;clearInterval(this.timer);this.started=false;void this.cancelSolcast(false,true);void this.cancelSources(false,true);void this.cancelHardware(false,true);}
  async refresh(){if(!this._hass||this.busy)return;const request=++this.requestSequence;try{const payload=await this._hass.callWS({type:"deye_ems/status"});if(request!==this.requestSequence||this.busy)return;this.payload=this.mergeUpdateStatus(payload);this.error="";}catch(e){if(request!==this.requestSequence||this.busy)return;this.error=e.message||String(e);}this.render();}
  async command(args,draftKey=null,errorMessage=null){if(this.busy)return false;++this.requestSequence;this.busy=true;this.error="";this.render();try{this.payload=this.mergeUpdateStatus(await this._hass.callWS({type:"deye_ems/command",...args}));if(draftKey!==null)delete this.drafts[draftKey];return true;}catch(e){this.error=errorMessage||e.message||String(e);return false;}finally{this.busy=false;this.render();}}
  snapshotFresh(){const at=this.payload?.data?.updated_at;if(!at)return false;const age=Date.now()-new Date(at).getTime();return Number.isFinite(age)&&age>=0&&age<=30000;}
  measurement(key){const input=this.payload?.data?.inputs;if(!this.snapshotFresh()||!input)return null;if(key==="soc"?input.soc_valid!==true:input.telemetry_valid!==true)return null;return numeric(input[key]);}
  telemetryIssueText(){
    const sourceNames={battery_power:"moc baterii",grid_power:"moc portu GRID",grid_l1_power:"GRID L1",grid_l2_power:"GRID L2",grid_l3_power:"GRID L3",load_power:"moc LOAD",load_l1_power:"LOAD L1",load_l2_power:"LOAD L2",load_l3_power:"LOAD L3",voltage:"napięcie baterii",bms_charge_current:"limit BMS",bms_blocking_charge:"zgoda BMS",max_charge_current_number:"limit Deye",grid_current_number:"nastawa prądu",battery_low_soc:"próg Battery low SOC",soc:"SoC baterii",reserve:"rezerwa SoC",ct_balance:"bilans CT",charge_power:"zgodność czasowa mocy",ct_grid_power:"moc CT",ct_grid_l1_power:"CT L1",ct_grid_l2_power:"CT L2",ct_grid_l3_power:"CT L3"};
    const issueNames={missing:"brak odczytu",restored:"odczyt przywrócony",wrong_unit:"błędna jednostka",invalid:"błędny odczyt",future:"błędny czas odczytu",stale:"za stary odczyt",time_skew:"odczyty z różnych chwil",alias:"powtórzone przypisanie"};
    const issues=this.payload?.data?.inputs?.telemetry_issues;
    if(!Array.isArray(issues))return "";
    const messages=issues.filter(v=>v&&typeof v==="object"&&Object.hasOwn(sourceNames,v.source)&&Object.hasOwn(issueNames,v.reason)).map(v=>sourceNames[v.source]+": "+issueNames[v.reason]);
    return [...new Set(messages)].slice(0,3).join("; ");
  }
  telemetryDetailRows(){
    const details=this.payload?.data?.inputs?.telemetry_details;
    return (Array.isArray(details)?details:[]).slice(0,80).filter(row=>row&&typeof row==="object"&&!Array.isArray(row)&&typeof row.source==="string");
  }
  telemetryDiagnosticStage(){
    return [this.snapshotFresh(),this.payload?.data?.inputs?.telemetry_valid,this.telemetryExpanded,
      this.telemetryDetailRows().filter(row=>row.valid!==true).map(row=>row.source+":"+String(row.reason)).join("|")].join(":");
  }
  telemetryDiagnosticsHtml(){
    const heading='<section aria-label="Diagnostyka pomiarów"><h2>Diagnostyka pomiarów</h2>';
    if(!this.snapshotFresh())return heading+'<p class="notice warning">Brak bieżącej diagnostyki. Ostatni stan silnika jest nieaktualny lub ma nieprawidłowy czas. Oczekiwanie na świeży odczyt z HA.</p></section>';
    const rows=this.telemetryDetailRows(),failed=rows.filter(row=>row.valid!==true),healthy=rows.length-failed.length;
    if(!rows.length)return heading+'<p>Brak szczegółów pomiarów w bieżącym odczycie silnika.</p></section>';
    const reasonNames={missing:"Brak odczytu",restored:"Odczyt przywrócony po uruchomieniu",wrong_unit:"Błędna jednostka",invalid:"Nieprawidłowa wartość",future:"Czas odczytu w przyszłości",stale:"Odczyt starszy niż dopuszczalny limit",time_skew:"Odczyty pochodzą z różnych chwil",alias:"Powtórzone przypisanie encji"};
    const finite=value=>typeof value==="number"&&Number.isFinite(value);
    const seconds=value=>finite(value)&&value>=0?num(value,1)+" s":"—";
    const reported=value=>{const stamp=updateTimestamp(value);return stamp===null?"brak czasu odczytu":new Date(stamp).toLocaleString("pl-PL",{timeZone:"Europe/Warsaw",year:"numeric",month:"2-digit",day:"2-digit",hour:"2-digit",minute:"2-digit",second:"2-digit"});};
    const visible=this.telemetryExpanded?rows:failed;
    const table=visible.length?'<div class="table" id="telemetry-diagnostics-table"><table><thead><tr><th>Źródło / encja</th><th>Odczyt źródła</th><th>Ostatni raport</th><th>Wiek przy sprawdzeniu</th><th>Dopuszczalny wiek</th><th>Wynik kontroli</th></tr></thead><tbody>'+visible.map(row=>{
      const unit=typeof row.unit==="string"?row.unit:"",entity=typeof row.entity_id==="string"&&row.entity_id?row.entity_id:"brak przypisanej encji";
      const value=finite(row.value)?num(row.value,3):"—",platform=typeof row.platform==="string"&&row.platform?row.platform:null;
      let reason=row.valid===true?"Prawidłowy":Object.hasOwn(reasonNames,row.reason)?reasonNames[row.reason]:"Wymaga sprawdzenia";
      if(row.reason==="wrong_unit"&&typeof row.expected_unit==="string")reason+=" — oczekiwano "+row.expected_unit;
      if(row.reason==="time_skew"&&finite(row.observed_time_skew_seconds)&&finite(row.max_time_skew_seconds))reason+=" — różnica "+seconds(row.observed_time_skew_seconds)+", limit "+seconds(row.max_time_skew_seconds);
      return '<tr><td>'+esc(this.sourceFieldLabel(row.source))+'<br><code>'+esc(entity)+'</code>'+(platform?'<br><span class="legend">Integracja: '+esc(platform)+'</span>':'')+'</td><td>'+esc(value)+(unit?' '+esc(unit):'')+'</td><td>'+esc(reported(row.last_reported))+'</td><td>'+esc(seconds(row.age_seconds))+'</td><td>'+esc(row.max_age_seconds===null?'bez stałego limitu':seconds(row.max_age_seconds))+'</td><td>'+esc(reason)+'</td></tr>';
    }).join("")+'</tbody></table></div>':'';
    const hints=(Array.isArray(this.payload?.data?.inputs?.telemetry_hints)?this.payload.data.inputs.telemetry_hints:[]).slice(0,8).filter(hint=>hint&&["esphome","generic"].includes(hint.provider)&&["stale","time_skew"].includes(hint.reason)&&Array.isArray(hint.sources)).map(hint=>{
      const relevant=hint.reason==="time_skew"?failed.some(row=>row.reason==="time_skew"):true;
      const matches=relevant?rows.filter(row=>hint.sources.includes(row.source)&&(hint.reason!=="stale"||row.valid!==true&&row.reason==="stale")&&(hint.provider!=="esphome"||row.platform==="esphome")):[];
      if(!matches.length)return "";
      const names=[...new Set(matches.map(row=>this.sourceFieldLabel(row.source)))].join(", ");
      const advice=hint.provider==="esphome"?'Źródło ESPHome: sprawdź częstotliwość publikacji pomiarów i ustawienia update_interval oraz force_update: true dla wskazanych czujników. Następnie sprawdź, czy HA otrzymuje nowe raporty.':'Sprawdź dostępność encji i częstotliwość raportowania w integracji źródłowej. Odświeżenie panelu nie odświeża fizycznego pomiaru.';
      return '<p class="notice">'+esc(names)+': '+esc(advice)+'</p>';
    });
    const notice=failed.length?'<p class="notice warning">Pomiary wymagające sprawdzenia: '+failed.length+'. Szczegóły poniżej wyjaśniają blokadę; wartości źródłowe z błędem nie są potwierdzonym pomiarem do sterowania.</p>':this.payload?.data?.inputs?.telemetry_valid===true?'<p>Wszystkie pokazane źródła spełniają bieżące kontrole pomiarów.</p>':'<p class="notice warning">Lista szczegółów nie wskazuje błędnego odczytu, ale silnik nie potwierdza kompletu pomiarów. Sprawdź komunikat sterowania.</p>';
    const button=healthy?'<button id="telemetry-diagnostics-toggle" class="secondary" aria-expanded="'+(this.telemetryExpanded?'true':'false')+'" aria-controls="telemetry-diagnostics-table">'+(this.telemetryExpanded?'Ukryj prawidłowe pomiary':failed.length?'Pokaż także prawidłowe pomiary ('+healthy+')':'Pokaż pomiary ('+healthy+')')+'</button>':'';
    return heading+notice+'<p class="legend">Wiek dotyczy ostatniego sprawdzenia silnika: '+esc(reported(this.payload?.data?.updated_at))+'. Limity bezpieczeństwa pozostają bez zmian.</p>'+button+table+(failed.length||this.payload?.data?.inputs?.telemetry_valid!==true?[...new Set(hints)].join(""):'')+'</section>';
  }
  bindTelemetryDiagnostics(){
    this.shadowRoot.getElementById("telemetry-diagnostics-toggle")?.addEventListener("click",()=>{this.telemetryExpanded=!this.telemetryExpanded;this.render();});
  }
  nextCurrentChangeText(){
    const at=updateTimestamp(this.payload?.data?.control?.next_current_change_at),now=Date.now();
    if(at===null||at<=now||at-now>48*3600000)return "";
    const date=new Date(at),today=new Date(now);
    const day=d=>new Intl.DateTimeFormat("pl-PL",{timeZone:"Europe/Warsaw",year:"numeric",month:"2-digit",day:"2-digit"}).format(d);
    const clock=new Intl.DateTimeFormat("pl-PL",{timeZone:"Europe/Warsaw",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}).format(date);
    return day(date)===day(today)?"o "+clock:"dnia "+day(date)+" o "+clock;
  }
  currentStatusText(reason){
    const p=this.payload||{},d=p.data||{},c=d.control||{},input=d.inputs||{};
    if(p.mode!=="active")return "Tryb obserwacji — EMS nie steruje ładowaniem.";
    if(!this.snapshotFresh())return "Brak aktualnego stanu sterowania. Oczekiwanie na świeży odczyt.";
    const plain=String(reason).replace(/^safety_/,"");
    const hard=new Set(["bms_blocked","hardware_mode_mismatch","owner_conflict","ownership_conflict","grid_headroom","inverter_grid_headroom","deye_charge_cap","actuator_cap","converter_cap","battery_charge_headroom"]);
    if(hard.has(plain)&&Object.hasOwn(reasons,plain))return reasons[plain];
    if(input.telemetry_valid!==true||c.current_hold_reason==="telemetry_invalid"){const issues=this.telemetryIssueText();return "Brak poprawnych, świeżych pomiarów."+(issues?" "+issues+".":"");}
    const routine=new Set(["scheduled_hold","scheduled_setpoint","scheduled_retry","scheduled_deadband","initial_charge_start","recovery_wait","ramp_wait","dispatch_retry_wait","pending_readback","awaiting_readback","retry_unconfirmed","waiting_setting_readback","deadband","ramp_up","ramp_down","active","initializing"]);
    if(!routine.has(plain))return Object.hasOwn(reasons,reason)?reasons[reason]:Object.hasOwn(reasons,plain)?reasons[plain]:"Silnik sprawdza plan i dostępne dane";
    const rawSetting=c.read_setting_a??input.current_a;
    const setting=typeof rawSetting==="number"&&Number.isFinite(rawSetting)&&rawSetting>=0?rawSetting:null;
    const flag=c.grid_charge_enabled;
    let state=flag===true?"Doładowanie baterii z sieci jest włączone." :flag===false?"Doładowanie baterii z sieci jest wyłączone.":"Brak potwierdzenia włączenia doładowania z sieci.";
    if(setting!==null&&setting>0)state=flag===false?"Limit "+num(setting,0)+" A zapisany, doładowanie baterii z sieci jest wyłączone.":state+" Limit "+num(setting,0)+" A.";
    const hold=c.current_hold_reason;
    const next=this.nextCurrentChangeText();
    if(hold==="waiting_stable_measurements"){
      const left=c.recovery_remaining_s;
      return state+" Oczekiwanie na stabilne pomiary"+(typeof left==="number"&&Number.isFinite(left)&&left>0&&left<=120?" — pozostało co najmniej "+Math.ceil(left)+" s.":".");
    }
    const notes={policy_blocked:"Ładowanie z sieci jest teraz niedozwolone.",target_reached:"Cel SoC został osiągnięty.",pv_covers_charge_need:"PV pokrywa potrzebę ładowania.",waiting_readback:"Oczekiwanie na potwierdzenie nastawy z falownika.",waiting_retry:"Oczekiwanie po poprzedniej próbie polecenia.",initial_start:"Przygotowanie pierwszego startu w tanim oknie.",ready:"Regulator może teraz zmienić prąd."};
    if(Object.hasOwn(notes,hold))state+=" "+notes[hold];
    if(next)return state+" Następna zmiana prądu najwcześniej "+next+".";
    if(hold==="scheduled_regular"||plain==="scheduled_hold")return state+" Termin kolejnej zmiany prądu nie jest jeszcze potwierdzony.";
    return state;
  }
  kw(key){const v=this.measurement(key);return v===null?null:v/1000;}
  mergeUpdateStatus(payload){
    const previous=this.payload;
    if(!payload||payload.backend_version!==previous?.backend_version)return payload;
    const oldTime=updateTimestamp(previous?.updates?.checked_at),newTime=updateTimestamp(payload.updates?.checked_at);
    return oldTime!==null&&(newTime===null||oldTime>newTime)?{...payload,updates:previous.updates}:payload;
  }
  updatesRetrySeconds(){
    const at=updateTimestamp(this.payload?.updates?.retry_at),remaining=at===null?0:at-Date.now();
    return remaining>0&&remaining<=86400000?Math.ceil(remaining/1000):0;
  }
  hasUnsavedChanges(){return Boolean(this.hardwareOpen||this.sourceOpen||this.solcastOpen||this.loadDraft||this.loadDelete||this.appearanceDraft!==null||Object.keys(this.drafts).length);}
  async checkUpdates(){
    const version=releaseVersion(this.payload?.backend_version);
    if(!this._hass||this.busy||this.updatesBusy||!version||this.updatesRetrySeconds()>0)return false;
    const request=++this.updatesSequence;this.updatesBusy=true;this.updatesError="";this.render();
    try{
      const response=await this._hass.callWS({type:"deye_ems/command",command:"check_updates"});
      if(request!==this.updatesSequence)return false;
      if(this.payload?.backend_version!==version||response?.backend_version!==version||!response.updates||typeof response.updates!=="object"||Array.isArray(response.updates)){
        this.updatesError="Wersja HA mogła się zmienić. Odśwież panel i sprawdź ponownie.";return false;
      }
      // A long release check must not replace newer mode, settings or telemetry.
      this.payload=this.mergeUpdateStatus({...this.payload,updates:response.updates});
      return true;
    }catch{
      if(request===this.updatesSequence)this.updatesError="Nie udało się sprawdzić aktualizacji. Spróbuj ponownie później.";
      return false;
    }finally{
      if(request===this.updatesSequence){this.updatesBusy=false;this.render();}
    }
  }
  reloadInterface(){
    if(this.busy||this.hasUnsavedChanges())return false;
    globalThis.location?.reload();return true;
  }
  updatesHtml(){
    const p=this.payload||{},u=p.updates||{},running=releaseVersion(p.backend_version),latest=releaseVersion(u.latest_version);
    const checked=updateTimestamp(u.checked_at),knownCheck=checked!==null&&checked<=Date.now();
    const comparison=running?compareVersions(running,PANEL_VERSION):null;
    const mismatch=comparison!==null&&comparison!==0;
    const pending=this.updatesBusy||u.status==="checking",retry=this.updatesRetrySeconds();
    const good=u.stale!==true&&knownCheck&&running&&latest;
    let message="Nie sprawdzono jeszcze dostępności aktualizacji.";
    if(!running)message="Brak potwierdzonej wersji uruchomionej w HA. Odśwież panel lub zakończ aktualizację i restart HA.";
    else if(pending)message="Sprawdzanie dostępnych wydań…";
    else if(u.status==="error"||this.updatesError){
      const errors={rate_limited:"Osiągnięto limit sprawdzania wydań. Spróbuj ponownie później.",network:"Nie udało się połączyć z serwisem wydań.",invalid_response:"Nie otrzymano poprawnej informacji o wydaniu."};
      message=this.updatesError||(Object.hasOwn(errors,u.reason)?errors[u.reason]:"Nie udało się sprawdzić aktualizacji. Spróbuj ponownie później.");
    }else if(good&&u.status==="available"&&compareVersions(latest,running)>0)message="Dostępna aktualizacja: "+latest+".";
    else if(good&&u.status==="current"&&compareVersions(latest,running)===0)message="Ostatnie sprawdzenie: brak nowszego wydania.";
    else if(good&&u.status==="ahead"&&compareVersions(latest,running)<0)message="Uruchomiona wersja HA jest nowsza niż ostatnie wydanie publiczne.";
    const releaseLink=latest&&knownCheck?'<a href="https://github.com/gaszu/deye-ems/releases/tag/v'+latest+'" target="_blank" rel="noopener noreferrer">Opis wydania '+esc(latest)+'</a>':'';
    const warning=mismatch?'<p class="notice warning">'+(comparison>0?'Otwarta karta ma starszy interfejs niż wersja uruchomiona w HA. Odśwież interfejs.':'Interfejs jest nowszy niż wersja uruchomiona w HA. Sprawdź w Marketplace, czy po aktualizacji wymagany jest restart HA.')+'</p>':'';
    const lastKnown=latest&&knownCheck&&(u.status==="error"||u.stale===true)?'<p class="legend">Ostatnio znane wydanie: '+esc(latest)+'. Ta informacja może być nieaktualna.</p>':'';
    const disabled=this.busy||pending||!running||retry>0;
    return '<section aria-label="Wersja i aktualizacje"><h2>Wersja i aktualizacje</h2><p>Uruchomiona w HA: <b>'+esc(running)+'</b> · Interfejs tej karty: <b>'+PANEL_VERSION+'</b>.</p>'+warning+
      '<p role="status">'+esc(message)+'</p>'+lastKnown+(knownCheck?'<p class="legend">Ostatnia próba sprawdzenia: '+esc(time(u.checked_at))+(u.stale===true?' · wynik nieaktualny':'')+'.</p>':'')+
      (retry?'<p class="legend">Ponowne sprawdzenie za '+retry+' s.</p>':'')+
      '<div class="actions"><button id="updates-check" class="secondary" '+(disabled?'disabled':'')+'>'+(pending?'Sprawdzanie…':'Sprawdź aktualizacje')+'</button><a href="/marketplace">Otwórz Marketplace</a>'+releaseLink+
      '<button id="updates-reload" class="secondary" '+(this.busy||this.hasUnsavedChanges()?'disabled':'')+'>Odśwież interfejs</button></div><p class="legend">Sprawdzenie odczytuje publiczne wydania GitHub. Instalację i ewentualny restart wykonuje się w Marketplace tej instancji. Przed odświeżeniem interfejsu zapisz lub anuluj edytowane zmiany.</p></section>';
  }
  bindUpdates(){
    this.shadowRoot.getElementById("updates-check")?.addEventListener("click",()=>this.checkUpdates());
    this.shadowRoot.getElementById("updates-reload")?.addEventListener("click",()=>this.reloadInterface());
  }
  pvPriorityHtml(){
    const d=this.payload?.data,c=d?.control;
    const ready=this.snapshotFresh()&&d?.inputs?.telemetry_valid===true;
    const power=key=>ready&&typeof c?.[key]==="number"&&Number.isFinite(c[key])&&c[key]>=0?c[key]/1000:null;
    return '<div aria-label="Priorytet PV"><p><b>Nadwyżka PV do ładowania — szacunek zachowawczy:</b> '+num(power("pv_surplus_credit_w"))+' kW · <b>Wyliczona potrzeba doładowania z sieci:</b> '+num(power("net_grid_need_w"))+' kW.</p><p class="legend">PV po zasileniu domu zmniejsza potrzebę ładowania z sieci. Obie wartości dotyczą mocy po stronie baterii. Szacunek wynika z bilansu baterii i portu GRID; nie jest osobnym pomiarem energii PV. Potrzeba mocy z sieci jest pokazywana przed ograniczeniami sprzętowymi.</p></div>';
  }
  topologyKw(key){
    const topology=this.payload?.options?.topology,input=this.payload?.data?.inputs;
    if(!["load_only","load_with_external_ct"].includes(topology)||input?.topology!==topology)return null;
    if(key==="outside_load_w"&&(topology!=="load_with_external_ct"||input.outside_power_valid!==true))return null;
    return this.kw(key);
  }
  gridPhaseReadoutHtml(){
    const o=this.payload?.options||{},h=o.hardware_profile||{},ct=o.topology==="load_with_external_ct",load=o.topology==="load_only";
    const phases=h.phases??o.inverter_phases,connection=h.connection_phases??o.connection_phases;
    // The other inverter phases are structural zeroes in a one-phase layout,
    // not measurements of utility phases. Only a three-phase CT supplies all
    // three actual utility readouts for a single-phase inverter installation.
    if(phases===1&&(load||ct&&connection===1)){
      const phase=h.inverter_phase??o.inverter_phase;
      if(!["L1","L2","L3"].includes(phase))return "Faza podłączenia niepotwierdzona: — kW";
      return (ct?"CT ":"GRID ")+phase+(ct?" (przyłącze jednofazowe)":" (port jednofazowy)")+": "+num(this.topologyKw("grid_"+phase.toLowerCase()+"_power"))+" kW";
    }
    return (ct?"CT":load?"GRID":"Sieć")+" L1 / L2 / L3: "+num(this.topologyKw("grid_l1_power"))+" / "+num(this.topologyKw("grid_l2_power"))+" / "+num(this.topologyKw("grid_l3_power"))+" kW";
  }
  topologyHtml(){
    const o=this.payload?.options||{},input=this.payload?.data?.inputs,topology=o.topology;
    const ct=topology==="load_with_external_ct",load=topology==="load_only",known=ct||load;
    const fresh=this.snapshotFresh(),savedMode=ct?"Zero Export To CT":load?"Zero Export To Load":null;
    const rawMode=input?.inverter_work_mode,actualMode=fresh&&typeof rawMode==="string"&&rawMode.trim()&&!['unknown','unavailable'].includes(rawMode.trim().toLowerCase())?rawMode.trim():null;
    const mismatch=known&&actualMode!==null&&actualMode!==savedMode;
    const topologyError=fresh&&Boolean(input?.topology_error);
    const heading=ct?"Układ LOAD i CT":load?"Układ LOAD":"Układ instalacji";
    const outside=ct?num(this.topologyKw("outside_load_w"))+" kW":load?"nieobliczane w układzie LOAD":"nieustalone";
    const exchange=ct?"Sieć na CT":load?"Sieć na porcie GRID":"Wymiana z siecią";
    let notice="";
    if(!known)notice="Nie rozpoznano zapisanego układu instalacji. Pomiary nie są przypisane do układu LOAD ani CT.";
    else if(!fresh)notice="Brak aktualnego odczytu układu. Pomiary wymagają aktualizacji z ostatnich 30 sekund.";
    else if(!input||input.topology!==topology)notice="Brak odczytu zgodnego z zapisanym układem. Oczekiwanie na aktualizację pomiarów.";
    else if(input.telemetry_valid!==true)notice="Brak poprawnych pomiarów układu. Nieprawidłowe odczyty są pokazane jako —.";
    else if(ct&&input.outside_power_valid!==true)notice="Brak poprawnego bilansu CT i portu GRID. Moc odbiorów między GRID a CT jest nieznana.";
    return '<section aria-label="Układ instalacji"><h2>'+heading+'</h2><p>Zapisany układ EMS: '+esc(savedMode??"nierozpoznany")+' · odczyt trybu falownika: '+esc(actualMode??(fresh?"brak poprawnego odczytu":"brak aktualnego odczytu"))+'.</p>'+
      '<p>LOAD: '+num(this.topologyKw("raw_load_power"))+' kW · odbiory między GRID a CT: '+outside+' · port GRID falownika: '+num(this.topologyKw("grid_port_power"))+' kW.</p>'+
      '<p>Dom w modelu EMS: '+num(this.topologyKw("load_power"))+' kW · '+exchange+': '+num(this.topologyKw("grid_power"))+' kW.</p>'+
      '<p class="legend">Dodatnia moc GRID oznacza pobór, ujemna — wypływ z falownika. '+(ct?'O wymianie z siecią decyduje pomiar CT. Dom obejmuje LOAD i odbiory między GRID a CT.':load?'Wymiana z siecią jest mierzona na porcie GRID. Dom obejmuje pomiar LOAD; odbiory poza LOAD nie są wyliczane.':'Źródło wymiany z siecią i zakres pomiaru domu wymagają rozpoznania zapisanego układu.')+'</p>'+
      '<p class="legend">Moc znamionowa falownika '+num(numeric(o.inverter_max_power_kw))+' kW jest wspólna dla wyjścia LOAD i oddawania przez port GRID.'+(ct?' Odbiory między GRID a CT mogą pobrać pozostałą moc bezpośrednio z sieci; ta część nie przechodzi przez falownik.':'')+'</p>'+
      (notice?'<p class="notice warning">'+notice+'</p>':'')+
      (mismatch?'<p class="notice warning">Niezgodność trybu falownika z zapisanym układem EMS. Wymagany tryb: '+esc(savedMode)+'. Sprawdź konfigurację przed uruchomieniem sterowania.</p>':'')+
      (topologyError?'<p class="notice warning">Błąd pomiarów układu. Bilans LOAD, portu GRID i CT wymaga sprawdzenia.</p>':'')+'</section>';
  }
  hardwareHtml(){
    const o=this.payload?.options||{},h=o.hardware_profile||{},limits=o.effective_hardware_limits||{};
    const phases=h.phases===1?"Jednofazowy":h.phases===3?"Trójfazowy":"Liczba faz niepotwierdzona";
    const connection=h.connection_phases===1?"jednofazowe":h.connection_phases===3?"trójfazowe":"niepotwierdzone";
    const source=typeof h.source_url==="string"&&/^https:\/\/(?:www\.)?(?:deyeinverter\.com|deye\.com)\//.test(h.source_url)&&!/[\s<>"']/.test(h.source_url)?h.source_url:null;
    const ratings='<p>Moc katalogowa: '+num(h.rated_power_kw)+' kW · moc katalogowa na fazę: '+num(h.phase_max_power_kw)+' kW · maksymalny prąd ładowania producenta: '+num(h.max_charge_current_a,0)+' A.</p>';
    const effective='<p>Skuteczny limit falownika: '+num(limits.inverter_max_power_kw)+' kW · na fazę: '+num(limits.inverter_phase_max_power_kw)+' kW. Limit przyłącza: '+num(o.grid_import_limit_kw)+' kW · na fazę: '+num(o.grid_phase_limit_kw)+' kW.</p>';
    return '<section aria-label="Falownik i ograniczenia"><h2>Falownik i ograniczenia</h2><p><b>'+esc(h.label||"Własne / dotychczasowe parametry")+'</b> · '+phases+(h.phases===1?' · podłączenie '+esc(h.inverter_phase):'')+' · przyłącze '+connection+'.</p>'+
      '<p>Bateria '+esc(h.battery_type||"LV")+': '+num(h.battery_min_v)+'–'+num(h.battery_max_v)+' V.</p>'+ratings+effective+
      '<p class="legend">Limity modelu nie podnoszą niższych ustawień instalacji. Obowiązują również bieżące limity Deye −5%, BMS i świeże pomiary.'+(source?' <a href="'+esc(source)+'" target="_blank" rel="noopener noreferrer">Dokumentacja producenta</a>.':'')+'</p>'+
      (numeric(h.grid_passthrough_a)!==null?'<p class="legend">Przepustowość GRID→LOAD z dokumentacji: '+num(h.grid_passthrough_a,0)+' A. Informacja sprzętowa; nie podwyższa zapisanego limitu poboru portu GRID.</p>':'')+
      (h.control_supported===false?'<p class="notice warning">Ten profil nie ma potwierdzonej obsługi sterowania. Pozostaw EMS w obserwacji.</p>':'')+this.hardwareEditorHtml()+'</section>';
  }
  tariffCalendarHtml(){
    const calendar=this.payload?.options?.tariff_calendar;
    if(!calendar||typeof calendar!=="object"||Array.isArray(calendar))return '<section aria-label="Harmonogram taryfy"><h2>Harmonogram taryfy</h2><p>Oczekiwanie na kalendarz silnika. Wybór operatora i taryfy będzie dostępny w kolejnym etapie.</p></section>';
    const zones={off_peak:"Poza szczytem",morning_peak:"Szczyt przedpołudniowy",afternoon_peak:"Szczyt popołudniowy",peak:"Szczyt",cheap:"Poza szczytem",protected:"Chronione okno",night:"Noc",day:"Dzień"};
    const clock={local:"Czas lokalny Europe/Warsaw",local_time:"Czas lokalny Europe/Warsaw",fixed_cet:"Stały czas zimowy",fixed_winter:"Stały czas zimowy",unconfirmed:"Podstawa zegara niepotwierdzona"};
    const clockLabel=Object.hasOwn(clock,calendar.clock_basis)?clock[calendar.clock_basis]:"Podstawa zegara: "+String(calendar.clock_basis??"niepotwierdzona");
    const reasonLabel=value=>value==="winter"?"Sezon zimowy":value==="summer"?"Sezon letni":value==="weekend"?"Dzień wolny":typeof value==="string"&&value.startsWith("holiday:")?"Święto":"Reguła profilu";
    const rows=values=>(Array.isArray(values)?values:[]).slice(0,32).filter(row=>row&&typeof row==="object"&&updateTimestamp(row.start)!==null&&updateTimestamp(row.end)>updateTimestamp(row.start)).map(row=>'<tr><td>'+esc(time(row.start))+'–'+esc(time(row.end))+'</td><td>'+esc(Object.hasOwn(zones,row.zone)?zones[row.zone]:row.zone)+'</td><td>'+(row.grid_charge_allowed===true?'Dozwolone według zasad sezonu':'Zablokowane')+'</td><td>'+reasonLabel(row.reason)+(Number.isInteger(row.legacy_slot)&&row.legacy_slot>=1&&row.legacy_slot<=6?' · slot '+row.legacy_slot:'')+'</td></tr>').join("");
    const tables=[["Dziś",calendar.today],["Jutro",calendar.tomorrow]].map(([label,values])=>'<h3>'+label+'</h3><div class="table"><table><thead><tr><th>Przedział</th><th>Strefa</th><th>Ładowanie z sieci</th><th>Reguła</th></tr></thead><tbody>'+(rows(values)||'<tr><td colspan="4">Brak poprawnych przedziałów.</td></tr>')+'</tbody></table></div>').join("");
    return '<section aria-label="Harmonogram taryfy"><h2>Harmonogram taryfy</h2><p><b>'+esc(calendar.label||calendar.profile_id||"Zachowany harmonogram")+'</b> · wersja '+esc(calendar.version||"niepotwierdzona")+'.</p><p>'+esc(clockLabel)+'.</p>'+
      '<p>Aktualna strefa: '+esc(Object.hasOwn(zones,calendar.current_zone)?zones[calendar.current_zone]:calendar.current_zone??"niepotwierdzona")+' · następna zmiana: '+esc(time(calendar.next_change))+'.</p>'+
      (calendar.preview_only===true||calendar.runtime_allowed===false?'<p class="notice warning">Podgląd kalendarza; nie jest potwierdzeniem zgody na sterowanie dla tego profilu.</p>':'')+
      '<p class="legend">'+(calendar.profile_id==="legacy_g13"?'Zachowany profil G13 z wersji 1.x, codziennie bez automatycznych wyjątków operatora. ':'')+'Wybór operatora i katalog zweryfikowanych taryf pojawią się w kolejnym etapie. Zgoda w harmonogramie nie oznacza ciągłego ładowania; decydują także SoC, sezon, PV i limity.</p>'+tables+'</section>';
  }
  panelThemeNames(){return Object.keys(this._hass?.themes?.themes||{}).sort((a,b)=>a.localeCompare(b));}
  savedPanelTheme(){return typeof this.payload?.appearance?.theme==="string"?this.payload.appearance.theme:"";}
  applyPanelTheme(){
    // Local equivalent of HA applyThemesOnElement's custom-theme path:
    // base rules, then current-mode rules, CSSOM on this host, stale-key reset.
    // HA's existing profile supplies native defaults; no global theme is set.
    const name=this.savedPanelTheme(),themes=this._hass?.themes,themesByName=themes?.themes||{};
    const present=!!name&&Object.hasOwn(themesByName,name)&&themesByName[name]&&typeof themesByName[name]==="object";
    const missing=!!name&&!present;
    const values=new Map();
    if(present){
      const theme=themesByName[name],dark=typeof this._hass?.selectedTheme?.dark==="boolean"?
        this._hass.selectedTheme.dark:themes.darkMode===true;
      const {modes,...base}=theme;
      const rules={...base,...(modes?.[dark?"dark":"light"]||{})};
      for(const [key,value] of Object.entries(rules)){
        if(!/^[A-Za-z_][A-Za-z0-9_-]*$/.test(key)||!["string","number","boolean"].includes(typeof value))continue;
        values.set("--"+key,String(value));
        if(typeof value==="string"&&/^#(?:[0-9a-f]{3}|[0-9a-f]{6})$/i.test(value)&&!Object.hasOwn(rules,"rgb-"+key)){
          const hex=value.slice(1),expanded=hex.length===3?hex.split("").map(char=>char+char).join(""):hex;
          values.set("--rgb-"+key,[0,2,4].map(index=>parseInt(expanded.slice(index,index+2),16)).join(","));
        }
      }
      // Rebind the filled HA button's few palette references locally. An
      // inherited computed semantic color would otherwise keep the profile's
      // palette instead of this named theme's palette.
      const normal=dark?"10":"90",hover=dark?"20":"80",ink=dark?"60":"40";
      values.set("--ems-button-background",Object.hasOwn(rules,"ha-color-primary-"+normal)?
        "var(--ha-color-primary-"+normal+")":"var(--secondary-background-color,var(--card-background-color))");
      values.set("--ems-button-hover",Object.hasOwn(rules,"ha-color-primary-"+hover)?
        "var(--ha-color-primary-"+hover+")":"var(--secondary-background-color,var(--card-background-color))");
      values.set("--ems-button-text",Object.hasOwn(rules,"ha-color-primary-"+ink)?
        "var(--ha-color-primary-"+ink+")":"var(--primary-color)");
      values.set("color-scheme",dark?"dark":"light");
    }
    let changed=missing!==this.appearanceMissing;
    for(const key of this.appliedThemeValues.keys())if(!values.has(key)){this.style.removeProperty(key);changed=true;}
    for(const [key,value] of values)if(this.appliedThemeValues.get(key)!==value){this.style.setProperty(key,value);changed=true;}
    this.appliedThemeValues=values;this.appearanceMissing=missing;
    return changed;
  }
  async saveAppearance(){
    if(this.busy||this.appearanceDraft===null)return;
    const theme=this.appearanceDraft;
    if(theme!==""&&!this.panelThemeNames().includes(theme)){
      this.appearanceError="Ten motyw nie jest już dostępny w HA. Wybierz inny motyw.";
      this.render();return;
    }
    const ok=await this.command({command:"appearance",theme},null,
      "Nie udało się zapisać motywu panelu. Odśwież listę motywów HA i spróbuj ponownie.");
    if(ok){this.appearanceDraft=null;this.appearanceError="";}
    else this.appearanceError=this.error;
    this.render();
  }
  appearanceHtml(){
    const saved=this.savedPanelTheme(),selected=this.appearanceDraft??saved,names=this.panelThemeNames();
    const missing=selected!==""&&!names.includes(selected);
    const options='<option value="" '+(selected===""?'selected':'')+'>Bieżący motyw HA</option>'+
      names.map(name=>'<option value="'+esc(name)+'" '+(selected===name?'selected':'')+'>'+esc(name)+'</option>').join("")+
      (missing?'<option value="'+esc(selected)+'" selected disabled>'+esc(selected)+' — niedostępny</option>':'');
    return '<section><h2>Wygląd panelu</h2><label>Motyw panelu<select id="panel-theme" data-appearance-theme="true" '+(this.busy?'disabled':'')+'>'+options+'</select></label>'+
      '<p class="legend">Motyw dotyczy tylko tego panelu. Możesz wybrać ten sam motyw co w swoim widoku HA. Nie zmienia sterowania ani motywu całego HA.</p>'+
      (this.appearanceMissing?'<p role="status" class="notice warning">Zapisany motyw jest niedostępny. Panel używa bieżącego motywu HA.</p>':'')+
      (this.appearanceError?'<p role="alert" class="notice error">'+esc(this.appearanceError)+'</p>':'')+
      '<button id="appearance-save" '+(this.busy||missing||this.appearanceDraft===null||selected===saved?'disabled':'')+'>Zapisz motyw panelu</button></section>';
  }
  bindAppearance(){
    const select=this.shadowRoot.getElementById("panel-theme");
    select?.addEventListener("change",()=>{this.appearanceDraft=select.value;this.appearanceError="";this.render();});
    this.shadowRoot.getElementById("appearance-save")?.addEventListener("click",()=>this.saveAppearance());
  }
  solcastUsageHtml(){
    const solcast=this.payload?.data?.solcast||{},quota=solcast.quota||{},utc=quota.utc||{};
    const today=new Date(Date.now()).toISOString().slice(0,10),day=utc.day;
    const validDay=typeof day==="string"&&/^\d{4}-\d{2}-\d{2}$/.test(day)&&day===today;
    const count=value=>typeof value==="number"&&Number.isSafeInteger(value)&&value>=0;
    const invalidState=["invalid_quota_state","clock_moved_backwards"].includes(solcast.reason);
    const fresh=this.snapshotFresh(),valid=fresh&&!invalidState&&validDay&&count(utc.used)&&count(quota.limit)&&quota.limit>0;
    const used=valid?utc.used:null,limit=valid?quota.limit:null,remaining=valid?Math.max(limit-used,0):null;
    const reset=valid?new Date(Date.parse(day+"T00:00:00Z")+86400000).toISOString():null;
    const configured=solcast.api_configured===true,enabled=solcast.api_enabled===true;
    const ha=solcast.status==="ha_entities";
    const source=enabled?"Licznik klienta API EMS.":configured?
      "Pobieranie API EMS wyłączone. Prognoza z encji HA.":ha?
      "Prognoza z encji HA. EMS nie otrzymuje licznika zapytań tej integracji.":
      solcast.api_configured===false||solcast.status==="not_configured"?
      "Klient API EMS nie jest skonfigurowany.":"Licznik klienta API EMS.";
    const missing=!fresh?"Brak aktualnego odczytu licznika.":invalidState?"Stan licznika wymaga sprawdzenia. Liczba dostępnych zapytań jest nieznana.":
      utc.day&&utc.day!==today?"Licznik dotyczy innej doby UTC. Oczekiwanie na aktualny odczyt.":
      "Brak danych licznika API EMS.";
    const card=(name,value)=>'<article><span class="label">'+name+'</span><strong>'+num(value,0)+'</strong></article>';
    return '<div class="api-usage" aria-label="Zapytania API Solcast"><h3>Zapytania API Solcast</h3><p class="legend">'+source+'</p>'+
      '<div class="grid">'+card("Wykorzystano dziś",used)+card("Limit na dobę UTC",limit)+card("Pozostało",remaining)+'</div>'+
      (valid?'<p class="legend">Doba UTC: '+esc(day)+' · Odnowienie limitu: '+esc(time(reset))+' (Europe/Warsaw).</p>':
        '<p class="legend" role="status">'+missing+'</p>')+
      (valid&&(remaining===0||solcast.reason==="daily_quota_exhausted")?'<p class="notice warning" role="status">Limit zapytań API EMS wyczerpany.</p>':'')+
      '<p class="legend">Lokalny rejestr obejmuje próby zapytań i początkowy lub importowany stan wykorzystania. To nie licznik udanych pobrań ani odczyt wykorzystania całego konta Solcast. Zapytania innych klientów nie są tu automatycznie doliczane.</p></div>';
  }
  clearSolcastSecret(){
    this.solcastSecret="";
    this.shadowRoot.querySelectorAll("[data-solcast-secret]").forEach(input=>{input.value="";});
  }
  async cleanupSolcastFlow(id){
    if(typeof id!=="string"||!id)return;
    try{await this._hass.callApi("DELETE","config/config_entries/options/flow/"+encodeURIComponent(id));}catch{/* A completed or already cancelled flow may be absent. */}
  }
  async cancelSolcast(render=true,force=false){
    if(this.solcastCommitting&&!force)return;
    ++this.solcastSequence;
    const id=this.solcastFlow?.flow_id;
    clearTimeout(this.solcastRefreshTimer);this.solcastRefreshTimer=null;
    this.clearSolcastSecret();this.solcastOpen=false;this.solcastFlow=null;this.solcastDraft={};
    this.solcastError="";this.solcastNotice="";this.solcastConfirmDisable=false;
    if(this.solcastBusy)this.busy=false;
    this.solcastBusy=false;this.solcastCommitting=false;
    if(render)this.render();
    await this.cleanupSolcastFlow(id);
  }
  applySolcastResult(result,sequence){
    if(sequence!==this.solcastSequence||!this.solcastOpen){
      if(result?.flow_id!==this.solcastFlow?.flow_id)void this.cleanupSolcastFlow(result?.flow_id);
      return false;
    }
    if(!result||!["menu","form","abort","create_entry"].includes(result.type))throw Error("unsupported_flow");
    const previous=this.solcastFlow;
    // Never retain raw flow results: a terminal result may contain private
    // server-side data. Password defaults/suggestions are discarded as well.
    const flow={type:result.type,flow_id:typeof result.flow_id==="string"?result.flow_id:previous?.flow_id,
      step_id:result.step_id,reason:Object.hasOwn(solcastMessages,result.reason)?result.reason:undefined,menu_options:[],data_schema:[],errors:[],note:""};
    this.solcastFlow=flow;
    if(result.type==="menu"){
      flow.menu_options=(Array.isArray(result.menu_options)?result.menu_options:[])
        .filter(name=>["solcast","solcast_manual","solcast_import","solcast_disable"].includes(name));
    }
    if(result.type==="form"){
      try{
        if(!Array.isArray(result.data_schema))throw Error("unsupported_schema");
        flow.data_schema=result.data_schema.map(field=>{
        if(!field||!Object.hasOwn(solcastFields,field.name))throw Error("unsupported_field");
        const selector=field.selector||{},types=Object.keys(selector);
        if(types.length!==1||!["text","number","boolean","select"].includes(types[0]))throw Error("unsupported_selector");
        const type=types[0],config=selector[type]||{},secret=field.name==="api_key"||field.secret===true||type==="text"&&config.type==="password";
        const clean={name:field.name,type,required:field.required===true,secret};
        if(type==="number")for(const key of ["min","max","step"])if(numeric(config[key])!==null)clean[key]=Number(config[key]);
        if(type==="select"){
          if(!Array.isArray(config.options))throw Error("unsupported_options");
          clean.options=config.options.map(option=>typeof option==="string"?{value:option,label:option}:
            {value:option.value,label:String(option.label??option.value)});
          if(clean.options.some(option=>!["string","number"].includes(typeof option.value)))throw Error("unsupported_option");
        }
        if(!secret){
          const value=Object.hasOwn(field,"default")?field.default:field.description?.suggested_value;
          if(["string","number","boolean"].includes(typeof value))clean.default=value;
        }
        return clean;
        });
      }catch{
        flow.type="abort";flow.data_schema=[];this.clearSolcastSecret();this.solcastDraft={};
        this.solcastError="Kreator zawiera nieobsługiwane pole. Zaktualizuj panel albo użyj konfiguracji integracji HA.";
        return true;
      }
      const retain=previous?.type==="form"&&previous.step_id===flow.step_id;
      const draft={};
      for(const field of flow.data_schema)if(!field.secret){
        draft[field.name]=retain&&Object.hasOwn(this.solcastDraft,field.name)?this.solcastDraft[field.name]:
          field.default??(field.type==="boolean"?false:"");
      }
      this.solcastDraft=draft;
      flow.errors=Object.values(result.errors||{}).map(code=>Object.hasOwn(solcastMessages,code)?solcastMessages[code]:"Sprawdź dane formularza i spróbuj ponownie.");
      if(typeof result.description_placeholders?.import_note==="string")flow.note=result.description_placeholders.import_note;
    }
    if(result.type==="abort"){
      this.clearSolcastSecret();this.solcastDraft={};
      this.solcastError=Object.hasOwn(solcastMessages,result.reason)?solcastMessages[result.reason]:"Kreator został zakończony. Otwórz go ponownie, aby spróbować jeszcze raz.";
    }
    if(result.type==="create_entry"){
      this.clearSolcastSecret();this.solcastDraft={};flow.flow_id=null;
      this.solcastNotice=this.solcastConfirmDisable?"Pobieranie przez EMS zostało wyłączone. Zapisany klucz i kalibracja pozostają zachowane.":
        "Zapisano i włączono pobieranie przez EMS. Poczekaj na odczyt silnika i sprawdź plan przed włączeniem sterowania.";
      this.solcastConfirmDisable=false;
    }
    return true;
  }
  async runSolcast(operation,committing=false){
    if(this.busy||this.payload?.mode==="active")return false;
    const sequence=++this.solcastSequence;
    this.solcastBusy=true;this.solcastCommitting=committing;this.busy=true;this.solcastError="";this.render();
    try{await operation(sequence);return sequence===this.solcastSequence;}
    catch{
      if(sequence===this.solcastSequence&&this.solcastOpen)this.solcastError="Nie udało się wykonać kroku konfiguracji. Sprawdź połączenie z HA i spróbuj ponownie.";
      return false;
    }finally{
      if(sequence===this.solcastSequence){
        this.solcastBusy=false;this.solcastCommitting=false;this.busy=false;this.render();
        if(this.solcastFlow?.type==="create_entry")void this.refreshAfterSolcast(sequence);
      }
    }
  }
  async openSolcast(){
    if(this.busy)return;
    if(this.hardwareOpen)await this.cancelHardware(false);
    if(this.sourceOpen)await this.cancelSources(false);
    const cleanup=this.cancelSolcast(false),openingSequence=this.solcastSequence;
    await cleanup;
    if(openingSequence!==this.solcastSequence)return;
    this.solcastOpen=true;
    if(this.payload?.mode==="active"){this.render();return;}
    if(typeof this.payload?.entry_id!=="string"||!this.payload.entry_id){this.solcastError="Poczekaj na odczyt integracji i ponów otwarcie kreatora.";this.render();return;}
    return this.runSolcast(async sequence=>{
      const first=await this._hass.callApi("POST","config/config_entries/options/flow",{handler:this.payload.entry_id});
      if(!this.applySolcastResult(first,sequence))return;
      if(first.type==="menu"&&first.step_id==="init"&&this.solcastFlow.menu_options.includes("solcast")){
        const result=await this._hass.callApi("POST","config/config_entries/options/flow/"+encodeURIComponent(this.solcastFlow.flow_id),{next_step_id:"solcast"});
        this.applySolcastResult(result,sequence);
      }
    });
  }
  async advanceSolcast(data){
    if(!this.solcastOpen||!this.solcastFlow?.flow_id||this.busy||this.payload?.mode==="active")return;
    const id=this.solcastFlow.flow_id;
    const committing=this.solcastFlow.type==="form"&&this.solcastFlow.step_id==="solcast_manual"||data.next_step_id==="solcast_disable";
    if(committing){this.solcastSavedAt=Date.now();this.solcastPreviousPlan=this.payload?.data?.plan?.generated_at;}
    return this.runSolcast(async sequence=>{
      const result=await this._hass.callApi("POST","config/config_entries/options/flow/"+encodeURIComponent(id),data);
      this.applySolcastResult(result,sequence);
    },committing);
  }
  async submitSolcast(){
    if(this.solcastFlow?.type!=="form"||this.busy||this.payload?.mode==="active")return;
    const data={};
    for(const field of this.solcastFlow.data_schema){
      if(field.secret){if(this.solcastSecret)data[field.name]=this.solcastSecret;continue;}
      const value=this.solcastDraft[field.name];
      if(field.type==="boolean")data[field.name]=value===true;
      else if(field.type==="number"){
        if(value===""&&!field.required)continue;
        const number=numeric(value);
        if(number===null||field.min!==undefined&&number<field.min||field.max!==undefined&&number>field.max){this.solcastError="Uzupełnij poprawnie pola liczbowe formularza.";this.render();return;}
        data[field.name]=number;
      }else if(field.type==="select"){
        const option=field.options.find(item=>String(item.value)===String(value));
        if(!option){if(!field.required&&value==="")continue;this.solcastError="Wybierz pozycję z listy.";this.render();return;}
        data[field.name]=option.value;
      }else data[field.name]=String(value??"");
    }
    return this.advanceSolcast(data);
  }
  async refreshAfterSolcast(sequence,attempt=0){
    if(sequence!==this.solcastSequence||!this.solcastOpen)return;
    const request=++this.requestSequence;
    let ready=false;
    try{
      const payload=await this._hass.callWS({type:"deye_ems/status"});
      if(sequence!==this.solcastSequence||request!==this.requestSequence||!this.solcastOpen)return;
      this.payload=this.mergeUpdateStatus(payload);this.error="";
      ready=this.solcastPlanReady();
    }catch{/* Reload can briefly remove the coordinator; status is retried. */}
    if(sequence!==this.solcastSequence||!this.solcastOpen)return;
    this.render();
    if(!ready&&attempt<5)this.solcastRefreshTimer=setTimeout(()=>void this.refreshAfterSolcast(sequence,attempt+1),1000*Math.min(2**attempt,8));
  }
  solcastPlanReady(){
    const plan=this.payload?.data?.plan||{},generated=new Date(plan.generated_at).getTime();
    return this.snapshotFresh()&&plan.quality==="valid"&&plan.status==="ok"&&!this.payload?.data?.planning&&Number.isFinite(generated)&&generated>=this.solcastSavedAt&&plan.generated_at!==this.solcastPreviousPlan;
  }
  solcastFieldHtml(field){
    const value=this.solcastDraft[field.name]??"",label=esc(solcastFields[field.name]),name=esc(field.name),required=field.required?'required':'';
    if(field.type==="boolean")return '<label class="check"><input type="checkbox" data-solcast-field="'+name+'" '+(value===true?'checked':'')+'> '+label+'</label>';
    if(field.type==="select")return '<label>'+label+'<select data-solcast-field="'+name+'" '+required+'><option value="">Wybierz…</option>'+field.options.map(option=>'<option value="'+esc(option.value)+'" '+(String(option.value)===String(value)?'selected':'')+'>'+esc(option.label)+'</option>').join("")+'</select></label>';
    if(field.secret)return '<label>'+label+'<input type="password" data-solcast-field="'+name+'" data-solcast-secret="true" autocomplete="new-password" placeholder="'+(this.solcastSecret?'Wpisany klucz pozostaje w pamięci do zapisu':'Puste pole zachowuje zapisany klucz')+'"></label>';
    const attributes=field.type==="number"?["min","max","step"].filter(key=>field[key]!==undefined).map(key=>key+'="'+field[key]+'"').join(" "):'';
    return '<label>'+label+'<input type="'+(field.type==="number"?'number':'text')+'" data-solcast-field="'+name+'" '+required+' '+attributes+' value="'+esc(value)+'"></label>';
  }
  solcastHtml(){
    if(!this.solcastOpen)return '<button id="solcast-open" class="secondary" '+(this.busy?'disabled':'')+'>Połącz i skonfiguruj Solcast</button>';
    const flow=this.solcastFlow,active=this.payload?.mode==="active",disabled=this.busy||active;
    const locked=active?'<div class="notice">Konfiguracja Solcast wymaga trybu obserwacji. <button id="solcast-observe" class="secondary" '+(this.busy?'disabled':'')+'>Przejdź do obserwacji</button></div>':'';
    let body='';
    if(flow?.type==="menu")body='<div class="actions">'+[["solcast_manual","Połącz / zmień ustawienia"],["solcast_import","Importuj ustawienia z HA"],["solcast_disable","Wyłącz pobieranie przez EMS"]].filter(([key])=>flow.menu_options.includes(key)).map(([key,label])=>'<button type="button" class="secondary" data-solcast-step="'+key+'" '+(disabled?'disabled':'')+'>'+label+'</button>').join("")+'</div>';
    if(flow?.type==="form")body='<form id="solcast-form"><fieldset '+(disabled?'disabled':'')+'><div class="fields">'+flow.data_schema.map(field=>this.solcastFieldHtml(field)).join("")+'</div></fieldset>'+flow.errors.map(message=>'<p role="alert" class="notice error">'+esc(message)+'</p>').join("")+(flow.note?'<p class="notice solcast-note">'+esc(flow.note)+'</p>':'')+'<p class="legend">Pobieranie po zapisie może zużyć limit API. Nieznane wykorzystanie pozostaw jako pełny limit doby UTC. Import nie wyłącza pobierania przez inne integracje.</p><div class="actions"><button type="submit" '+(disabled?'disabled':'')+'>'+(flow.step_id==="solcast_import"?'Wczytaj ustawienia do podglądu':'Zapisz i włącz pobieranie API')+'</button></div></form>';
    if(this.solcastConfirmDisable)body='<div role="alert" class="notice">Wyłączyć pobieranie prognozy przez EMS? Zapisany klucz i kalibracja pozostaną zachowane.<div class="actions"><button id="solcast-disable-confirm" '+(disabled?'disabled':'')+'>Tak, wyłącz pobieranie</button><button id="solcast-disable-back" class="secondary" '+(this.busy?'disabled':'')+'>Wróć</button></div></div>';
    if(flow?.type==="abort")body='<button id="solcast-reopen" class="secondary" '+(disabled?'disabled':'')+'>Otwórz kreator ponownie</button>';
    if(flow?.type==="create_entry"&&!active){
      const ready=this.solcastPlanReady();
      body='<p class="legend">EMS pozostaje w trybie obserwacji. Sprawdź nowy plan; sterowanie włącza się osobno.</p><button id="solcast-resume" '+(this.busy||!ready?'disabled':'')+'>Włącz sterowanie po konfiguracji</button>';
    }
    return '<div class="solcast-editor"><h3>Konfiguracja Solcast</h3>'+locked+(this.solcastError?'<p role="alert" class="notice error">'+esc(this.solcastError)+'</p>':'')+(this.solcastNotice?'<p role="status" class="notice">'+esc(this.solcastNotice)+'</p>':'')+(this.solcastBusy?'<p role="status">'+(this.solcastCommitting?'Zapisywanie ustawień w HA…':'Łączenie z kreatorem HA…')+'</p>':'')+body+'<div class="actions"><button id="solcast-cancel" type="button" class="secondary" '+(this.solcastCommitting?'disabled':'')+'>'+(flow?.type==="create_entry"?'Zamknij kreator':'Anuluj kreator')+'</button></div></div>';
  }
  bindSolcast(){
    const root=this.shadowRoot;
    root.getElementById("solcast-open")?.addEventListener("click",()=>this.openSolcast());
    root.getElementById("solcast-reopen")?.addEventListener("click",()=>this.openSolcast());
    root.getElementById("solcast-cancel")?.addEventListener("click",()=>this.cancelSolcast());
    root.getElementById("solcast-observe")?.addEventListener("click",async()=>{if(await this.command({command:"mode",mode:"shadow"})){if(!this.solcastFlow||this.solcastFlow.type==="abort")await this.openSolcast();else this.render();}});
    root.getElementById("solcast-resume")?.addEventListener("click",()=>{if(this.solcastPlanReady())this.command({command:"mode",mode:"active"});});
    root.querySelectorAll("[data-solcast-step]").forEach(button=>button.addEventListener("click",()=>{if(this.busy||this.payload?.mode==="active")return;if(button.dataset.solcastStep==="solcast_disable"){this.solcastConfirmDisable=true;this.render();}else this.advanceSolcast({next_step_id:button.dataset.solcastStep});}));
    root.getElementById("solcast-disable-confirm")?.addEventListener("click",()=>this.advanceSolcast({next_step_id:"solcast_disable"}));
    root.getElementById("solcast-disable-back")?.addEventListener("click",()=>{this.solcastConfirmDisable=false;this.render();});
    root.querySelectorAll("[data-solcast-field]").forEach(input=>input.addEventListener("input",()=>{
      const field=this.solcastFlow?.data_schema.find(item=>item.name===input.dataset.solcastField);
      if(!field)return;
      if(field.secret)this.solcastSecret=input.value;
      else this.solcastDraft[field.name]=field.type==="boolean"?input.checked:input.value;
    }));
    root.getElementById("solcast-form")?.addEventListener("submit",event=>{event.preventDefault();this.submitSolcast();});
  }
  async cancelHardware(render=true,force=false){
    if(this.hardwareCommitting&&!force)return;
    ++this.hardwareSequence;const id=this.hardwareFlow?.flow_id;
    this.hardwareOpen=false;this.hardwareFlow=null;this.hardwareDraft={};this.hardwareError="";this.hardwareNotice="";
    if(this.hardwareBusy)this.busy=false;
    this.hardwareBusy=false;this.hardwareCommitting=false;
    if(render)this.render();await this.cleanupSolcastFlow(id);
  }
  applyHardwareResult(result,sequence){
    if(sequence!==this.hardwareSequence||!this.hardwareOpen){void this.cleanupSolcastFlow(result?.flow_id);return false;}
    if(!result||!["menu","form","abort","create_entry"].includes(result.type))throw Error("unsupported_flow");
    const previous=this.hardwareFlow,flow={type:result.type,flow_id:typeof result.flow_id==="string"?result.flow_id:previous?.flow_id,step_id:result.step_id,fields:[],errors:[],note:""};
    if(result.type==="menu"&&(result.step_id!=="init"||!result.menu_options?.includes("inverter")))throw Error("unsupported_menu");
    if(result.type==="form"){
      if(!["inverter","inverter_confirm"].includes(result.step_id)||!Array.isArray(result.data_schema)||!result.data_schema.length)throw Error("unsupported_form");
      const names=new Set();
      flow.fields=result.data_schema.map(field=>{
        const selector=field?.selector||{},type=Object.keys(selector)[0],confirm=result.step_id==="inverter_confirm";
        if(!field||Object.keys(selector).length!==1||names.has(field.name)||!Object.hasOwn(hardwareLabels,field.name)||
          (confirm?field.name!=="confirm_model"||type!=="boolean":field.name==="confirm_model"||type!=="select"))throw Error("unsupported_field");
        names.add(field.name);
        const value=Object.hasOwn(field,"default")?field.default:field.description?.suggested_value;
        const options=type==="select"&&Array.isArray(selector.select.options)?selector.select.options.map(option=>typeof option==="string"?{value:option,label:option}:{value:option?.value,label:String(option?.label??option?.value)}):[];
        if(type==="select"&&(!options.length||options.some(option=>typeof option.value!=="string")))throw Error("unsupported_options");
        return {name:field.name,type,options,required:field.required===true,value:type==="boolean"?false:typeof value==="string"?value:""};
      });
      const expected=result.step_id==="inverter_confirm"?["confirm_model"]:["inverter_model","inverter_phases","connection_phases","inverter_phase"];
      if(expected.some(name=>!names.has(name))||names.size!==expected.length)throw Error("incomplete_form");
      const retain=previous?.type==="form"&&previous.step_id===flow.step_id;
      this.hardwareDraft=Object.fromEntries(flow.fields.map(field=>[field.name,retain&&Object.hasOwn(this.hardwareDraft,field.name)?this.hardwareDraft[field.name]:field.value]));
      flow.errors=Object.values(result.errors||{}).map(code=>Object.hasOwn(hardwareMessages,code)?hardwareMessages[code]:"Sprawdź wybór modelu i parametry instalacji.");
      if(typeof result.description_placeholders?.model_preview==="string")flow.note=result.description_placeholders.model_preview;
    }
    if(result.type==="abort")this.hardwareError=Object.hasOwn(hardwareMessages,result.reason)?hardwareMessages[result.reason]:"Kreator został zakończony. Otwórz go ponownie, aby sprawdzić konfigurację.";
    if(result.type==="create_entry"){
      flow.flow_id=null;this.hardwareDraft={};this.hardwareNotice="Zapisano model falownika. EMS pozostaje w obserwacji. Sprawdź świeże pomiary, limity i plan przed osobnym włączeniem sterowania.";
    }
    this.hardwareFlow=flow;return true;
  }
  async runHardware(operation,committing=false){
    if(this.busy||this.payload?.mode==="active")return false;
    const sequence=++this.hardwareSequence;this.hardwareBusy=true;this.hardwareCommitting=committing;this.busy=true;this.hardwareError="";this.render();
    try{await operation(sequence);return sequence===this.hardwareSequence;}
    catch{if(sequence===this.hardwareSequence&&this.hardwareOpen)this.hardwareError="Nie udało się otworzyć lub zapisać modelu. Sprawdź połączenie z HA i spróbuj ponownie.";return false;}
    finally{if(sequence===this.hardwareSequence){this.hardwareBusy=false;this.hardwareCommitting=false;this.busy=false;this.render();if(this.hardwareFlow?.type==="create_entry")void this.refresh();}}
  }
  async openHardware(){
    if(this.busy)return;
    if(this.solcastOpen)await this.cancelSolcast(false);
    if(this.sourceOpen)await this.cancelSources(false);
    const cleanup=this.cancelHardware(false),sequence=this.hardwareSequence;await cleanup;if(sequence!==this.hardwareSequence)return;
    this.hardwareOpen=true;
    if(this.payload?.mode==="active"){this.render();return;}
    if(typeof this.payload?.entry_id!=="string"||!this.payload.entry_id){this.hardwareError="Poczekaj na odczyt integracji i ponów otwarcie kreatora.";this.render();return;}
    return this.runHardware(async request=>{
      const first=await this._hass.callApi("POST","config/config_entries/options/flow",{handler:this.payload.entry_id});
      if(!this.applyHardwareResult(first,request)||first.type!=="menu")return;
      const result=await this._hass.callApi("POST","config/config_entries/options/flow/"+encodeURIComponent(this.hardwareFlow.flow_id),{next_step_id:"inverter"});
      this.applyHardwareResult(result,request);
    });
  }
  async submitHardware(){
    if(this.hardwareFlow?.type!=="form"||!this.hardwareFlow.flow_id||this.busy||this.payload?.mode==="active")return;
    const id=this.hardwareFlow.flow_id,data={},confirm=this.hardwareFlow.step_id==="inverter_confirm";
    for(const field of this.hardwareFlow.fields){
      if(field.type==="boolean"){
        if(this.hardwareDraft[field.name]!==true){this.hardwareError=hardwareMessages.confirm_model_required;this.render();return;}
        data[field.name]=true;
      }else{
        const value=String(this.hardwareDraft[field.name]??"").trim();
        if(!field.options.some(option=>option.value===value)){this.hardwareError="Wybierz poprawne pozycje z list modelu, faz i przyłącza.";this.render();return;}
        data[field.name]=value;
      }
    }
    return this.runHardware(async sequence=>{
      const result=await this._hass.callApi("POST","config/config_entries/options/flow/"+encodeURIComponent(id),data);
      this.applyHardwareResult(result,sequence);
    },confirm);
  }
  hardwareEditorHtml(){
    if(!this.hardwareOpen)return '<button id="hardware-open" class="secondary" '+(this.busy?'disabled':'')+'>Wybierz model falownika</button>';
    const flow=this.hardwareFlow,active=this.payload?.mode==="active",disabled=this.busy||active;
    let body=active?'<p class="notice">Zmiana modelu wymaga obserwacji. <button id="hardware-observe" class="secondary" '+(this.busy?'disabled':'')+'>Przejdź do obserwacji</button></p>':'';
    if(flow?.type==="form"){
      const fields=flow.fields.map(field=>field.type==="boolean"?'<label class="check"><input type="checkbox" data-hardware-field="'+esc(field.name)+'" '+(this.hardwareDraft[field.name]===true?'checked':'')+'>'+esc(hardwareLabels[field.name])+'</label>':'<label>'+esc(hardwareLabels[field.name])+'<select data-hardware-field="'+esc(field.name)+'" '+(field.required?'required':'')+'>'+field.options.map(option=>'<option value="'+esc(option.value)+'" '+(option.value===this.hardwareDraft[field.name]?'selected':'')+'>'+esc(option.label)+'</option>').join("")+'</select></label>').join("");
      body+='<form id="hardware-form">'+(flow.note?'<p class="notice solcast-note">'+esc(flow.note)+'</p>':'')+'<fieldset '+(disabled?'disabled':'')+'><div class="fields">'+fields+'</div></fieldset>'+flow.errors.map(error=>'<p role="alert" class="notice error">'+esc(error)+'</p>').join("")+'<p class="legend">'+(flow.step_id==="inverter"?'Wybór modelu określa liczbę faz falownika. Dla modelu własnego ustaw ją ręcznie. Faza L1/L2/L3 ma znaczenie dla falownika jednofazowego przy przyłączu trójfazowym. Podgląd nie zapisuje konfiguracji.':'Sprawdź model i niższe limity instalacji. Zapis zachowa rezerwę SoC, topologię oraz przypisania encji; sterowanie włączysz osobno.')+'</p><button type="submit" '+(disabled?'disabled':'')+'>'+(flow.step_id==="inverter"?'Pokaż parametry modelu':'Zapisz model i ograniczenia')+'</button></form>';
    }
    if(flow?.type==="abort")body+='<button id="hardware-reopen" class="secondary" '+(disabled?'disabled':'')+'>Otwórz kreator ponownie</button>';
    return '<div class="hardware-editor">'+(this.hardwareError?'<p role="alert" class="notice error">'+esc(this.hardwareError)+'</p>':'')+(this.hardwareNotice?'<p role="status" class="notice">'+esc(this.hardwareNotice)+'</p>':'')+(this.hardwareBusy?'<p role="status">'+(this.hardwareCommitting?'Zapisywanie modelu w HA…':'Łączenie z kreatorem HA…')+'</p>':'')+body+'<div class="actions"><button id="hardware-cancel" type="button" class="secondary" '+(this.hardwareCommitting?'disabled':'')+'>'+(flow?.type==="create_entry"?'Zamknij kreator':'Anuluj kreator')+'</button></div></div>';
  }
  bindHardware(){
    const root=this.shadowRoot;
    root.getElementById("hardware-open")?.addEventListener("click",()=>this.openHardware());
    root.getElementById("hardware-reopen")?.addEventListener("click",()=>this.openHardware());
    root.getElementById("hardware-cancel")?.addEventListener("click",()=>this.cancelHardware());
    root.getElementById("hardware-observe")?.addEventListener("click",async()=>{if(await this.command({command:"mode",mode:"shadow"}))await this.openHardware();});
    root.querySelectorAll("[data-hardware-field]").forEach(input=>input.addEventListener("input",()=>{this.hardwareDraft[input.dataset.hardwareField]=input.type==="checkbox"?input.checked:input.value;}));
    root.getElementById("hardware-form")?.addEventListener("submit",event=>{event.preventDefault();return this.submitHardware();});
  }
  async cancelSources(render=true,force=false){
    if(this.sourceCommitting&&!force)return;
    this.sourceSequence=(this.sourceSequence||0)+1;
    const id=this.sourceFlow?.flow_id;
    this.sourceOpen=false;this.sourceFlow=null;this.sourceDraft={};this.sourceError="";this.sourceNotice="";
    if(this.sourceBusy)this.busy=false;
    this.sourceBusy=false;this.sourceCommitting=false;
    if(render)this.render();
    await this.cleanupSolcastFlow(id);
  }
  applySourcesResult(result,sequence){
    if(sequence!==this.sourceSequence||!this.sourceOpen){void this.cleanupSolcastFlow(result?.flow_id);return false;}
    if(!result||!["menu","form","abort","create_entry"].includes(result.type))throw Error("unsupported_flow");
    const previous=this.sourceFlow;
    const flow={type:result.type,flow_id:typeof result.flow_id==="string"?result.flow_id:previous?.flow_id,step_id:result.step_id,fields:[],errors:[],note:""};
    if(result.type==="menu"&&(result.step_id!=="init"||!result.menu_options?.includes("entity_prefix")))throw Error("unsupported_menu");
    if(result.type==="form"){
      if(!["entity_prefix","sources"].includes(result.step_id)||!Array.isArray(result.data_schema)||!result.data_schema.length)throw Error("unsupported_form");
      flow.fields=result.data_schema.map(field=>{
        const prefix=result.step_id==="entity_prefix",selector=field?.selector||{},type=Object.keys(selector)[0];
        if(!field||Object.keys(selector).length!==1||
          (prefix?!(field.name==="entity_prefix"&&type==="text"||field.name==="battery_source_profile"&&type==="select"):type!=="entity"||!/^[a-z][a-z0-9_]*$/.test(field.name)))throw Error("unsupported_field");
        const domain=selector.entity?.domain,domains=Array.isArray(domain)?domain:typeof domain==="string"?[domain]:[];
        const value=Object.hasOwn(field,"default")?field.default:field.description?.suggested_value;
        const options=type==="select"&&Array.isArray(selector.select.options)?selector.select.options.map(option=>typeof option==="string"?{value:option,label:option}:{value:option?.value,label:String(option?.label??option?.value)}):[];
        if(type==="select"&&(!options.length||options.some(option=>typeof option.value!=="string")))throw Error("unsupported_options");
        return {name:field.name,type,options,required:field.required===true,domains:domains.filter(item=>/^[a-z_]+$/.test(item)),value:typeof value==="string"?value:""};
      });
      const retain=previous?.type==="form"&&previous.step_id===flow.step_id;
      this.sourceDraft=Object.fromEntries(flow.fields.map(field=>[field.name,retain&&Object.hasOwn(this.sourceDraft,field.name)?this.sourceDraft[field.name]:field.value]));
      flow.errors=Object.values(result.errors||{}).map(code=>Object.hasOwn(sourceMessages,code)?sourceMessages[code]:"Sprawdź przypisania i spróbuj ponownie.");
      if(typeof result.description_placeholders?.prefix_preview==="string")flow.note=result.description_placeholders.prefix_preview;
    }
    if(result.type==="abort")this.sourceError=Object.hasOwn(sourceMessages,result.reason)?sourceMessages[result.reason]:"Kreator został zakończony. Otwórz go ponownie, aby spróbować jeszcze raz.";
    if(result.type==="create_entry"){
      flow.flow_id=null;this.sourceDraft={};this.sourceNotice="Zapisano prefiks i przypisania. EMS pozostaje w obserwacji. Poczekaj na świeże pomiary i sprawdź plan przed osobnym włączeniem sterowania.";
    }
    this.sourceFlow=flow;return true;
  }
  async runSources(operation,committing=false){
    if(this.busy||this.payload?.mode==="active")return false;
    const sequence=++this.sourceSequence;
    this.sourceBusy=true;this.sourceCommitting=committing;this.busy=true;this.sourceError="";this.render();
    try{await operation(sequence);return sequence===this.sourceSequence;}
    catch{if(sequence===this.sourceSequence&&this.sourceOpen)this.sourceError="Nie udało się otworzyć lub zapisać konfiguracji źródeł. Sprawdź połączenie z HA i spróbuj ponownie.";return false;}
    finally{if(sequence===this.sourceSequence){this.sourceBusy=false;this.sourceCommitting=false;this.busy=false;this.render();if(this.sourceFlow?.type==="create_entry")void this.refresh();}}
  }
  async openSources(){
    if(this.busy)return;
    if(this.hardwareOpen)await this.cancelHardware(false);
    if(this.solcastOpen)await this.cancelSolcast(false);
    const cleanup=this.cancelSources(false),sequence=this.sourceSequence;
    await cleanup;if(sequence!==this.sourceSequence)return;
    this.sourceOpen=true;
    if(this.payload?.mode==="active"){this.render();return;}
    if(typeof this.payload?.entry_id!=="string"||!this.payload.entry_id){this.sourceError="Poczekaj na odczyt integracji i ponów otwarcie kreatora.";this.render();return;}
    return this.runSources(async request=>{
      const first=await this._hass.callApi("POST","config/config_entries/options/flow",{handler:this.payload.entry_id});
      if(!this.applySourcesResult(first,request))return;
      if(first.type!=="menu")return;
      const result=await this._hass.callApi("POST","config/config_entries/options/flow/"+encodeURIComponent(this.sourceFlow.flow_id),{next_step_id:"entity_prefix"});
      this.applySourcesResult(result,request);
    });
  }
  async submitSources(){
    if(this.sourceFlow?.type!=="form"||!this.sourceFlow.flow_id||this.busy||this.payload?.mode==="active")return;
    const id=this.sourceFlow.flow_id,data={};
    for(const field of this.sourceFlow.fields){
      const value=String(this.sourceDraft[field.name]??"").trim();
      if(field.type==="select"&&!field.options.some(option=>option.value===value)){this.sourceError="Wybierz źródło danych baterii z listy.";this.render();return;}
      if(value||field.required)data[field.name]=value;
    }
    // Prefix submission only previews HA's proposed mappings. Only the sources
    // form confirmation saves them. HA requires empty optional entity selectors
    // to be omitted; the native sources step clears those omitted selections.
    return this.runSources(async sequence=>{
      const result=await this._hass.callApi("POST","config/config_entries/options/flow/"+encodeURIComponent(id),data);
      this.applySourcesResult(result,sequence);
    },this.sourceFlow.step_id==="sources");
  }
  sourceFieldLabel(name){
    if(name==="entity_prefix")return "Prefiks encji Deye";
    if(name==="battery_source_profile")return "Źródło danych baterii";
    if(Object.hasOwn(sourceLabels,name))return sourceLabels[name];
    const phase=/^(grid|load|ct_grid)_l([123])_power$/.exec(name),tou=/^tou_(soc|gc|time)_([1-6])$/.exec(name);
    if(phase)return ({grid:"GRID",load:"LOAD",ct_grid:"CT"})[phase[1]]+" — moc L"+phase[2];
    if(tou)return "TOU "+tou[2]+" — "+({soc:"cel SoC",gc:"ładowanie z sieci",time:"godzina"})[tou[1]];
    return name.replaceAll("_"," ");
  }
  sourcesHtml(){
    const active=this.payload?.mode==="active",disabled=this.busy||active,flow=this.sourceFlow;
    let body='<button id="sources-open" class="secondary" '+(this.busy?'disabled':'')+'>Ustaw prefiks i encje Deye</button>';
    if(this.sourceOpen){
      body=active?'<p class="notice">Zmiana źródeł wymaga obserwacji. <button id="sources-observe" class="secondary" '+(this.busy?'disabled':'')+'>Przejdź do obserwacji</button></p>':'';
      if(flow?.type==="form"){
        const lists=new Map(),fields=flow.fields.map(field=>{
          if(field.type==="select")return '<label>'+esc(this.sourceFieldLabel(field.name))+'<select data-source-field="'+esc(field.name)+'" '+(field.required?'required':'')+'>'+field.options.map(option=>'<option value="'+esc(option.value)+'" '+(option.value===this.sourceDraft[field.name]?'selected':'')+'>'+esc(option.label)+'</option>').join("")+'</select></label>';
          const prefix=field.name==="entity_prefix",list="source-"+(field.domains.join("-")||"all");
          if(!prefix&&!lists.has(list))lists.set(list,'<datalist id="'+list+'">'+Object.entries(this._hass?.states||{}).filter(([id])=>!field.domains.length||field.domains.includes(id.split(".")[0])).map(([id,state])=>'<option value="'+esc(id)+'">'+esc(state.attributes?.friendly_name||id)+'</option>').join("")+'</datalist>');
          return '<label>'+esc(this.sourceFieldLabel(field.name))+'<input type="text" data-source-field="'+esc(field.name)+'" '+(field.required?'required':'')+' value="'+esc(this.sourceDraft[field.name])+'" '+(prefix?'placeholder="np. deye_dom_" autocomplete="off"':'list="'+list+'" placeholder="Brak przypisania (opcjonalnie)"')+'></label>';
        }).join("");
        body+='<form id="sources-form"><fieldset '+(disabled?'disabled':'')+'><div class="fields">'+fields+'</div>'+[...lists.values()].join("")+'</fieldset>'+flow.errors.map(error=>'<p role="alert" class="notice error">'+esc(error)+'</p>').join("")+(flow.note?'<p class="notice solcast-note">'+esc(flow.note)+'</p>':'')+'<p class="legend">'+(flow.step_id==="entity_prefix"?'Dane baterii mogą pochodzić z Deye. YamBMS jest opcjonalny. Wpisz prefiks bez sensor., np. deye_dom_. Następny krok pokaże propozycje; zapis wymaga osobnego potwierdzenia.':'Sprawdź propozycje i własne przypisania. Puste pole wyłącza dane źródło. Prognozy PV, dodatkowy BMS i opcjonalne odbiorniki mają osobne encje.')+'</p><button type="submit" '+(disabled?'disabled':'')+'>'+(flow.step_id==="entity_prefix"?'Pokaż przypisania dla prefiksu':'Zapisz prefiks i przypisania')+'</button></form>';
      }
      if(flow?.type==="abort")body+='<button id="sources-reopen" class="secondary" '+(disabled?'disabled':'')+'>Otwórz kreator ponownie</button>';
      body=(this.sourceError?'<p role="alert" class="notice error">'+esc(this.sourceError)+'</p>':'')+(this.sourceNotice?'<p role="status" class="notice">'+esc(this.sourceNotice)+'</p>':'')+(this.sourceBusy?'<p role="status">'+(this.sourceCommitting?'Zapisywanie przypisań w HA…':'Łączenie z kreatorem HA…')+'</p>':'')+body+'<div class="actions"><button id="sources-cancel" type="button" class="secondary" '+(this.sourceCommitting?'disabled':'')+'>'+(flow?.type==="create_entry"?'Zamknij kreator':'Anuluj kreator')+'</button></div>';
    }
    return '<section><h2>Źródła danych</h2><p class="legend">Wybierz prefiks swojej integracji Deye i sprawdź przypisania pomiarów oraz sterowania.</p>'+body+'</section>';
  }
  bindSources(){
    const root=this.shadowRoot;
    root.getElementById("sources-open")?.addEventListener("click",()=>this.openSources());
    root.getElementById("sources-reopen")?.addEventListener("click",()=>this.openSources());
    root.getElementById("sources-cancel")?.addEventListener("click",()=>this.cancelSources());
    root.getElementById("sources-observe")?.addEventListener("click",async()=>{if(await this.command({command:"mode",mode:"shadow"}))await this.openSources();});
    root.querySelectorAll("[data-source-field]").forEach(input=>input.addEventListener("input",()=>{this.sourceDraft[input.dataset.sourceField]=input.value;}));
    root.getElementById("sources-form")?.addEventListener("submit",event=>{event.preventDefault();return this.submitSources();});
  }
  editLoad(channel=null,revision=this.payload?.loads_revision){
    if(this.busy||this.payload?.mode==="active"||!Array.isArray(this.payload?.effective_loads))return;
    this.loadDraft={original_energy_entity:channel?.energy_entity||"",name:channel?.name||"",energy_entity:channel?.energy_entity||"",power_entity:channel?.power_entity||"",enabled:channel?.enabled!==false,revision};
    this.loadDelete=null;this.loadError="";this.render();
  }
  async saveLoad(){
    if(!this.loadDraft||this.busy||this.payload?.mode==="active")return;
    const draft={...this.loadDraft};
    const ok=await this.command({command:"load_save",original_energy_entity:draft.original_energy_entity,
      channel:{name:draft.name.trim(),energy_entity:draft.energy_entity.trim(),power_entity:draft.power_entity.trim(),included_in_load:true,enabled:draft.enabled},expected_loads_revision:draft.revision});
    if(ok){this.loadDraft=null;this.loadError="";}else this.loadError=this.error;
    this.render();
  }
  async deleteLoad(){
    if(!this.loadDelete||this.busy||this.payload?.mode==="active")return;
    const chosen=this.loadDelete;
    const ok=await this.command({command:"load_delete",original_energy_entity:chosen.energy_entity,expected_loads_revision:chosen.revision});
    if(ok){this.loadDelete=null;this.loadError="";}else this.loadError=this.error;
    this.render();
  }
  async toggleLoad(channel,enabled,revision){
    if(this.busy||this.payload?.mode==="active")return;
    const ok=await this.command({command:"load_toggle",original_energy_entity:channel.energy_entity,enabled,expected_loads_revision:revision});
    this.loadError=ok?"":this.error;this.render();
  }
  loadsHtml(){
    const p=this.payload||{},ready=Array.isArray(p.effective_loads),loads=ready?p.effective_loads:[],active=p.mode==="active",disabled=this.busy||active||!ready;
    const locked=active?'<div class="notice">Zmiana odbiorników wymaga trybu obserwacji. <button id="loads-observe" class="secondary" '+(this.busy?'disabled':'')+'>Przejdź do obserwacji</button></div>':'<div class="notice">Tryb obserwacji. Po zakończeniu zmian włącz sterowanie. <button id="loads-resume" '+(this.busy||!ready||this.loadDraft||this.loadDelete?'disabled':'')+'>Włącz sterowanie po edycji</button></div>';
    const list=loads.map((load,index)=>'<li class="load-row"><div><b>'+esc(load.name||load.energy_entity)+'</b><div class="legend">Licznik energii: <code>'+esc(load.energy_entity)+'</code></div>'+(load.power_entity?'<div class="legend">Pomiar mocy: <code>'+esc(load.power_entity)+'</code></div>':'')+'<div class="legend">Profil do prognozy SoC. Zużycie jest już w głównym LOAD.</div></div><div class="actions"><button class="secondary" data-load-edit="'+index+'" '+(disabled?'disabled':'')+'>Edytuj</button><button class="secondary" data-load-delete="'+index+'" '+(disabled?'disabled':'')+'>Usuń</button><label class="load-switch"><input type="checkbox" data-load-toggle="'+index+'" aria-label="Uwzględniaj '+esc(load.name||load.energy_entity)+' w prognozie SoC" '+(load.enabled!==false?'checked':'')+' '+(disabled?'disabled':'')+'><b>'+(load.enabled!==false?'ON':'OFF')+'</b></label></div></li>').join("");
    const choices=units=>Object.entries(this._hass?.states||{}).filter(([id,s])=>id.startsWith("sensor.")&&units.includes(s.attributes?.unit_of_measurement)).map(([id,s])=>'<option value="'+esc(id)+'" label="'+esc(s.attributes?.friendly_name||id)+' · '+esc(s.attributes?.unit_of_measurement)+'"></option>').join("");
    const draft=this.loadDraft;
    const editor=draft?'<form id="load-form"><h3>'+(draft.original_energy_entity?'Edytuj odbiornik':'Nowy odbiornik')+'</h3><fieldset '+(disabled?'disabled':'')+'><div class="fields"><label>Nazwa odbiornika<input data-load-field="name" required maxlength="80" value="'+esc(draft.name)+'"></label><label>Encja licznika energii (Wh / kWh)<input data-load-field="energy_entity" required pattern="sensor\\.[a-z0-9_]+" list="load-energy-options" placeholder="sensor.licznik_energii" value="'+esc(draft.energy_entity)+'"></label><label>Encja pomiaru mocy (W / kW, opcjonalna)<input data-load-field="power_entity" pattern="sensor\\.[a-z0-9_]+" list="load-power-options" placeholder="Opcjonalna" value="'+esc(draft.power_entity)+'"></label></div><p class="legend">Dane odbiornika służą modelowaniu prognozy SoC. Całe zużycie domu jest już zawarte w głównym pomiarze LOAD.</p></fieldset><div class="actions"><button type="submit" '+(disabled?'disabled':'')+'>Zapisz odbiornik</button><button type="button" id="load-cancel" class="secondary" '+(this.busy?'disabled':'')+'>Anuluj</button></div><datalist id="load-energy-options">'+choices(["Wh","kWh"])+'</datalist><datalist id="load-power-options">'+choices(["W","kW"])+'</datalist></form>':'';
    const confirmation=this.loadDelete?'<div role="alert" class="notice">Usunąć „'+esc(this.loadDelete.name)+'” z EMS? Źródłowe encje pomiarowe i ich historia pozostaną w HA.<div class="actions"><button id="load-confirm-delete" '+(disabled?'disabled':'')+'>Usuń z EMS</button><button id="load-cancel-delete" class="secondary" '+(this.busy?'disabled':'')+'>Anuluj</button></div></div>':'';
    return '<section><h2>Dodatkowe zużycia</h2><p class="legend">ON: uwzględniaj profil w prognozie SoC. OFF: pomiń profil, zachowując konfigurację. Całe zużycie domu odczytujemy wyłącznie z LOAD. Przełącznik nie steruje zasilaniem urządzenia.</p>'+locked+(this.loadError?'<div role="alert" class="notice error">'+esc(this.loadError)+'</div>':'')+(loads.length?'<ul class="loads">'+list+'</ul>':'<p class="legend">'+(ready?'Brak skonfigurowanych odbiorników. Podstawą pozostaje pomiar domu.':'Oczekiwanie na listę odbiorników…')+'</p>')+confirmation+(!draft?'<button id="load-add" class="secondary" '+(disabled?'disabled':'')+'>Dodaj odbiornik</button>':'')+editor+'</section>';
  }
  bindLoads(){
    const root=this.shadowRoot,loads=this.payload?.effective_loads||[],revision=this.payload?.loads_revision;
    root.getElementById("loads-observe")?.addEventListener("click",()=>this.command({command:"mode",mode:"shadow"}));
    root.getElementById("loads-resume")?.addEventListener("click",()=>this.command({command:"mode",mode:"active"}));
    root.getElementById("load-add")?.addEventListener("click",()=>this.editLoad(null,revision));
    root.querySelectorAll("[data-load-edit]").forEach(button=>button.addEventListener("click",()=>this.editLoad(loads[Number(button.dataset.loadEdit)],revision)));
    root.querySelectorAll("[data-load-delete]").forEach(button=>button.addEventListener("click",()=>{if(this.busy||this.payload.mode==="active")return;const load=loads[Number(button.dataset.loadDelete)];this.loadDelete={energy_entity:load.energy_entity,name:load.name||load.energy_entity,revision};this.loadDraft=null;this.loadError="";this.render();}));
    root.querySelectorAll("[data-load-toggle]").forEach(input=>input.addEventListener("change",()=>this.toggleLoad(loads[Number(input.dataset.loadToggle)],input.checked,revision)));
    root.getElementById("load-cancel")?.addEventListener("click",()=>{this.loadDraft=null;this.loadError="";this.render();});
    root.getElementById("load-cancel-delete")?.addEventListener("click",()=>{this.loadDelete=null;this.loadError="";this.render();});
    root.getElementById("load-confirm-delete")?.addEventListener("click",()=>this.deleteLoad());
    root.querySelectorAll("[data-load-field]").forEach(input=>input.addEventListener("input",()=>{if(this.loadDraft)this.loadDraft[input.dataset.loadField]=input.value;}));
    root.getElementById("load-form")?.addEventListener("submit",event=>{event.preventDefault();this.saveLoad();});
  }
  render(){
    // A polling response must not replace a focused input or its caret. Drafts
    // also survive rendering after blur, failed commands and later refreshes.
    this.applyPanelTheme();
    const solcastStage=[this.solcastOpen,this.solcastFlow?.type,this.solcastFlow?.step_id,this.solcastConfirmDisable].join(":");
    const sourceStage=[this.sourceOpen,this.sourceFlow?.type,this.sourceFlow?.step_id,this.sourceError,this.sourceNotice,this.sourceFlow?.errors?.join("|")].join(":");
    const hardwareStage=[this.hardwareOpen,this.hardwareFlow?.type,this.hardwareFlow?.step_id,this.hardwareError,this.hardwareNotice,this.hardwareFlow?.errors?.join("|")].join(":");
    const telemetryStage=this.telemetryDiagnosticStage();
    const appearanceStage=[this.savedPanelTheme(),this.appearanceMissing,this.panelThemeNames().join("|"),this.appearanceError,this.appearanceDraft].join(":");
    const urgent=this.renderedMode!==this.payload?.mode||this.renderedError!==this.error||this.renderedLoadsReady!==Array.isArray(this.payload?.effective_loads)||this.renderedSolcastStage!==solcastStage||this.renderedSourceStage!==sourceStage||this.renderedSolcastError!==this.solcastError||this.renderedSolcastNotice!==this.solcastNotice||this.renderedAppearanceStage!==appearanceStage||this.renderedHardwareStage!==hardwareStage||this.renderedTelemetryStage!==telemetryStage;
    if(!urgent&&!this.busy&&this.shadowRoot.activeElement?.matches?.("input[data-key],input[data-load-field],input[data-source-field],select[data-source-field],input[data-hardware-field],select[data-hardware-field],input[data-solcast-field],select[data-solcast-field],select[data-appearance-theme],select[data-topology]"))return;
    this.renderedMode=this.payload?.mode;this.renderedError=this.error;this.renderedLoadsReady=Array.isArray(this.payload?.effective_loads);
    this.renderedSolcastStage=solcastStage;this.renderedSolcastError=this.solcastError;this.renderedSolcastNotice=this.solcastNotice;
    this.renderedSourceStage=sourceStage;this.renderedHardwareStage=hardwareStage;this.renderedTelemetryStage=telemetryStage;
    this.renderedAppearanceStage=appearanceStage;
    const detailsOpen=this.shadowRoot.querySelector("details")?.open===true;
    const p=this.payload||{},d=p.data||{},plan=d.plan||{},c=d.control||{},o=p.options||{};
    const active=p.mode==="active", targets=plan.targets||{}, rows=plan.rows||[];
    const lowerBound=numeric(o.min_soc_lower_bound),boundValid=o.min_soc_bound_valid===true&&lowerBound!==null&&lowerBound>=5&&lowerBound<=90;
    const rawFloor=numeric(o.effective_min_soc_percent)??numeric(o.min_soc_percent),floor=rawFloor!==null&&rawFloor>=5&&rawFloor<=90?rawFloor:null;
    const fresh=this.snapshotFresh(),request=fresh?c.next_a:null,readSetting=fresh&&d.inputs?.telemetry_valid===true?c.read_setting_a??d.inputs.current_a:null;
    const deyeLimitValid=fresh&&d.inputs?.grid_charge_limit_valid===true;
    const deyeLimit=deyeLimitValid?numeric(d.inputs.deye_grid_charge_limit_a):null;
    const deyeSetting=deyeLimitValid?numeric(d.inputs.deye_max_charge_current_a):null;
    const ctTopology=o.topology==="load_with_external_ct",loadTopology=o.topology==="load_only";
    const selectedTopology=this.drafts.topology??o.topology??"load_only";
    const savedTopologyLabel=o.topology==="load_with_external_ct"?"Zero Export To CT":o.topology==="load_only"?"Zero Export To Load":"brak odczytu";
    const points=rows.map((r,i)=>(i/(Math.max(rows.length-1,1))*960).toFixed(1)+","+(220-Number(r.soc_percent||0)*2).toFixed(1)).join(" ");
    const card=(name,value,unit,sub)=>'<article><span class="label">'+esc(name)+'</span><strong>'+esc(value)+'<small>'+esc(unit)+'</small></strong><span class="sub">'+esc(sub||"")+'</span></article>';
    const reason=c.runtime_reason||c.reason||d.reason||d.status||"initializing";
    const owners=d.owner?.conflicts||d.owner?.blocking||d.conflicts||[];
    const statusText=this.currentStatusText(reason);
    const solcast=d.solcast||{};
    const solcastLabels={ok:"Prognoza pobrana",cached:"Prognoza z datowanego cache",unavailable:"Brak aktualnej prognozy API",not_configured:"Połączenie nieustawione",ha_entities:"Prognoza z wybranych encji HA",disabled:"Pobieranie wyłączone"};
    const solcastStatus=Object.hasOwn(solcastLabels,solcast.status)?solcastLabels[solcast.status]:"Oczekiwanie na prognozę";
    const sourceNames={own_plan:"bieżący plan",dated_cache:"ostatni poprawny plan",dated_cache_with_retained_raise:"plan z dodatkowym zapasem",unreachable_plan_raise:"podwyższony zapas",winter_fallback:"zapas na zimę",summer_emergency_fallback:"awaryjne doładowanie",own_deterministic_planner:"bieżący plan"};
    const selectedSource=Object.hasOwn(sourceNames,c.target_source)?sourceNames[c.target_source]:"oczekiwanie na plan";
    const mode=active?"Sterowanie aktywne":"Obserwacja";
    const phaseModel=o.hardware_profile?.phases===1?"Falownik jednofazowy — faza "+(o.hardware_profile.inverter_phase||"niepotwierdzona"):fresh&&d.inputs?.grid_charge_balanced===true?"Bilansowanie poboru GRID potwierdzone":"Wariant zachowawczy — bilansowanie GRID niepotwierdzone";
    const basicField=(key,button)=>{const r=key==="min_soc_percent"?[boundValid?lowerBound:40,90,1]:ranges[key],value=Object.hasOwn(this.drafts,key)?this.drafts[key]:(key==="min_soc_percent"?Math.max(numeric(o[key])??40,r[0]):o[key]??"");return '<label>'+esc(labels[key])+'<input data-key="'+key+'" type="number" min="'+r[0]+'" max="'+r[1]+'" step="'+r[2]+'" value="'+esc(value)+'"><button data-save="'+key+'" '+(this.busy||key==="min_soc_percent"&&!boundValid?'disabled':'')+'>'+esc(button)+'</button></label>';};
    this.shadowRoot.innerHTML='<style>'+
      ":host{display:block;min-height:100vh;background:var(--lovelace-background,var(--primary-background-color,#fafafa));color:var(--primary-text-color,#212121);font:15px var(--primary-font-family,var(--ha-font-family-body,system-ui))}*{box-sizing:border-box}main{max-width:1180px;margin:auto;padding:32px 24px 64px}header{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:24px}h1{font-size:28px;margin:0}h2{font-size:19px;margin:0 0 16px}.eyebrow{color:var(--secondary-text-color);font-size:12px;letter-spacing:1.7px;text-transform:uppercase;margin-bottom:8px}.pill{padding:9px 14px;border-radius:var(--ha-border-radius-pill,100px);background:var(--label-badge-background-color,var(--secondary-background-color));color:var(--label-badge-text-color,var(--primary-text-color));border:1px solid var(--divider-color);font-weight:650}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.stats{grid-template-columns:repeat(4,minmax(0,1fr))}article,section{background:var(--ha-card-background,var(--card-background-color,#fff));backdrop-filter:var(--ha-card-backdrop-filter,none);border-width:var(--ha-card-border-width,1px);border-style:solid;border-color:var(--ha-card-border-color,var(--divider-color,#e0e0e0));border-radius:var(--ha-card-border-radius,var(--ha-border-radius-lg,12px));box-shadow:var(--ha-card-box-shadow,none);color:var(--primary-text-color);padding:22px}.label,.sub{display:block;color:var(--secondary-text-color);font-size:13px}.sub{margin-top:10px;min-height:16px}strong{display:block;font-size:32px;line-height:1.5;letter-spacing:-1px}strong small{font-weight:450;letter-spacing:0;font-size:16px;margin-left:5px}section{margin-top:18px}.notice{padding:14px 18px;background:var(--secondary-background-color);color:var(--primary-text-color);border-radius:var(--ha-card-border-radius,12px);line-height:1.6;margin:18px 0}.warning{border-inline-start:4px solid var(--warning-color)}.error{border-inline-start:4px solid var(--error-color)}.actions{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}"+
      "button{font:inherit;cursor:pointer;border:1px solid transparent;border-radius:var(--ha-button-border-radius,var(--ha-border-radius-pill,20px));padding:11px 16px;background:var(--ems-button-background,var(--ha-color-fill-primary-normal-resting,var(--secondary-background-color)));color:var(--ems-button-text,var(--ha-color-on-primary-normal,var(--primary-color)));font-weight:var(--ha-font-weight-medium,600);box-shadow:var(--ha-button-box-shadow,none)}button.secondary{background:transparent;color:var(--primary-color);border-color:var(--divider-color)}button:hover:not(:disabled){background:var(--ems-button-hover,var(--ha-color-fill-primary-normal-hover,var(--secondary-background-color)))}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:2px solid var(--ha-color-focus,var(--primary-color));outline-offset:3px}button:disabled,input:disabled,select:disabled{opacity:1;color:var(--input-disabled-ink-color,var(--secondary-text-color));background:var(--input-disabled-fill-color,var(--secondary-background-color));border-color:var(--divider-color);cursor:not-allowed}svg{width:100%;height:230px;display:block}svg polyline{stroke:var(--primary-color)}svg line{stroke:var(--warning-color,var(--secondary-text-color))}.legend{font-size:12px;color:var(--secondary-text-color)}.fields{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}label{display:block;font-size:13px;color:var(--input-label-ink-color,var(--secondary-text-color))}input,select{margin-top:7px;width:100%;border:1px solid var(--input-idle-line-color,var(--divider-color));border-radius:var(--ha-border-radius-md,8px);background:var(--input-fill-color,var(--ha-color-form-background,var(--secondary-background-color)));color:var(--input-ink-color,var(--primary-text-color));padding:10px;font:inherit;caret-color:var(--primary-color);accent-color:var(--primary-color)}select option,optgroup{background:var(--primary-background-color,Canvas);color:var(--primary-text-color,CanvasText)}select option:disabled{color:var(--secondary-text-color,GrayText)}label button{margin-top:8px;padding:7px 10px;font-size:12px}.table{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:right;white-space:nowrap;padding:9px 12px;border-bottom:1px solid var(--divider-color)}th:first-child,td:first-child{text-align:left}footer{color:var(--secondary-text-color);font-size:12px;line-height:1.7;margin-top:24px}a{color:var(--primary-color);text-underline-offset:3px}summary{cursor:pointer;padding:18px 2px;font-weight:650}.reserve label{max-width:320px}.loads{list-style:none;padding:0}.load-row{display:flex;justify-content:space-between;align-items:center;gap:16px;border-bottom:1px solid var(--divider-color);padding:14px 0}.load-row .actions{margin:0;flex-shrink:0}.load-switch{display:flex;align-items:center;gap:7px;min-width:65px}.load-switch input{width:20px;height:20px;margin:0}code{overflow-wrap:anywhere}fieldset{border:0;padding:0;margin:0}.check{display:flex;align-items:center;gap:10px;margin-top:20px}.check input{width:auto;margin:0}form,.solcast-editor{border-top:1px solid var(--divider-color);margin-top:18px;padding-top:6px}.solcast-note{white-space:pre-line}"+
      "@media(max-width:760px){main{padding:24px 14px}.grid,.stats,.fields{grid-template-columns:repeat(2,minmax(0,1fr))}header{align-items:flex-start}h1{font-size:24px}article,section{padding:16px}strong{font-size:27px}}@media(max-width:600px){.load-row{align-items:flex-start;flex-direction:column}}@media(max-width:420px){.fields{grid-template-columns:1fr}.pill{font-size:12px;padding:8px}header{gap:8px}.sub{font-size:11px}}"+
      '</style><main><header><div><div class="eyebrow">Silnik lokalny · G13 · Deye</div><h1>Energia pod kontrolą</h1></div><div class="pill '+(active?'':'shadow')+'">'+mode+'</div></header>'+
      (this.error?'<div role="alert" class="notice error">'+esc(this.error)+'</div>':'')+
      '<div class="grid stats">'+card("Akumulator",num(this.measurement("soc")),"%",'Rezerwa EMS '+num(floor)+'%')+
      card("Sieć / dom",num(this.topologyKw("grid_power"))+' / '+num(this.topologyKw("load_power")),"kW",ctTopology?"Sieć mierzona na CT · dom: LOAD + odbiory między GRID a CT":loadTopology?"Sieć na porcie GRID: + pobór, − eksport · dom: pomiar LOAD":"Oczekiwanie na rozpoznanie zapisanego układu")+
      card("Wybrany cel SoC",num(fresh?c.target_soc:null),"%",time(fresh?c.target_deadline:null)+' · '+selectedSource)+
      card("Tryb",active?"Aktywny":"Obserwacja","",active?"Sterowanie falownikiem":"Planowanie bez poleceń do falownika")+'</div>'+
      this.updatesHtml()+this.telemetryDiagnosticsHtml()+this.topologyHtml()+this.hardwareHtml()+this.tariffCalendarHtml()+
      (!fresh?'<div class="notice warning">Brak aktualnego odczytu silnika. Pomiary wymagają aktualizacji z ostatnich 30 sekund.</div>':'')+
      '<div class="notice">'+esc(statusText)+'</div>'+
      (owners.length?'<div class="notice warning">Przejęcie sterowania blokują: '+owners.map(esc).join(", ")+'</div>':'')+
      ((plan.unreachable||c.unreachable)?'<div class="notice warning">Dostępna energia lub moc może nie wystarczyć do osiągnięcia celu. Limit poboru ma pierwszeństwo.</div>':'')+
      '<div class="actions"><button id="mode" '+(this.busy?'disabled':'')+'>'+(active?'Zatrzymaj i obserwuj':'Włącz sterowanie')+'</button></div>'+
      '<section><h2>Pomiar i sterowanie</h2><label>Tryb pomiaru EMS<select id="topology" data-topology="true" '+(active||this.busy?'disabled':'')+'><option value="load_only" '+(selectedTopology==="load_only"?'selected':'')+'>Zero Export To Load</option><option value="load_with_external_ct" '+(selectedTopology==="load_with_external_ct"?'selected':'')+'>Zero Export To CT</option></select></label><p>Zapisany tryb EMS: '+esc(savedTopologyLabel)+'. '+(selectedTopology!==(o.topology??"load_only")?'Niezapisana zmiana.':'')+'</p><p>Odczyt trybu falownika: '+esc(fresh?d.inputs?.inverter_work_mode??"brak odczytu":"brak aktualnego odczytu")+'</p><p class="legend">LOAD: dom na wyjściu LOAD. CT: pomiar przy przyłączu i odbiory między CT a portem GRID. Wybór konfiguruje model EMS; przed włączeniem sterowania tryb falownika musi być zgodny. Zmiana wymaga obserwacji i sprawdzenia przypisań pomiarów.</p><button id="topology-save" '+(active||this.busy?'disabled':'')+'>Zapisz tryb pomiaru</button></section>'+
      this.sourcesHtml()+
      '<section class="reserve"><h2>Magazyn energii</h2><div class="fields" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr))">'+basicField("min_soc_percent","Zapisz rezerwę")+basicField("capacity_kwh","Zapisz pojemność")+'</div><p class="legend">Minimalna dopuszczalna rezerwa: '+(boundValid?num(lowerBound)+'% (Battery low SOC + 5 p.p.)':'brak poprawnego odczytu Battery low SOC — zapis rezerwy zablokowany')+'. Skuteczna rezerwa: '+num(floor)+'%. Pojemność służy do przeliczania procentów na energię.</p></section>'+
      '<section><h2>Ładowanie akumulatora z sieci</h2><div class="grid">'+card("Automatyczny limit Deye −5%",num(deyeLimit,0),"A",'Maksymalny prąd ładowania ustawiony w Deye: '+num(deyeSetting,0)+' A.')+card("Limit BMS",num(fresh&&d.inputs?.bms_valid===true?d.inputs.bms_cap_a:null,0),"A","Dopuszczalny prąd baterii.")+card("Bieżący dostępny prąd",num(deyeLimitValid&&d.inputs?.telemetry_valid===true?c.cap_a:null,0),"A","Po uwzględnieniu BMS, falownika i przyłącza.")+'</div><p class="legend">Limit jest odczytywany automatycznie z Deye. Algorytm dobiera niższą nastawę do potrzeb i dostępnej mocy. Prognoza SoC wyznacza moc ładowania z aktualnych limitów Deye i BMS oraz napięcia baterii; ładowanie z PV i sieci korzysta ze wspólnego budżetu baterii. Moc portu GRID falownika: '+num(this.kw("grid_port_power"))+' kW (+ pobór, − oddawanie) · limit mocy falownika: '+num(o.inverter_max_power_kw)+' kW. Limit przyłącza pozostaje osobny.</p>'+this.pvPriorityHtml()+(!deyeLimitValid?'<p class="notice warning">Brak poprawnego odczytu limitu Deye. Ładowanie z sieci pozostaje zablokowane.</p>':'')+'</section>'+
      '<section><h2>Fotowoltaika i Solcast</h2><div class="fields">'+basicField("pv_peak_kwp","Zapisz moc PV")+'</div><p>'+esc(solcastStatus)+'</p>'+
      this.solcastUsageHtml()+
      '<p class="legend">Prognoza Solcast dla tej instalacji jest używana bez ponownego skalowania przez kWp. Moc służy do powiązania profilu z instalacją. Skalowanie profilu referencyjnego można włączyć w konfiguracji.</p>'+this.solcastHtml()+'</section>'+
      '<section><h2>Przyłącze sieciowe</h2><div class="fields">'+basicField("grid_import_limit_kw","Zapisz limit łączny")+basicField("grid_phase_limit_kw","Zapisz limit fazowy")+'</div><p class="legend">Maksymalny dozwolony pobór całej instalacji z sieci, niezależny od mocy falownika. Obowiązuje w LOAD i CT. W CT obejmuje również odbiory między przyłączem a portem GRID. Wpisz limity swojego przyłącza; regulator zachowuje zapas 0,5 kW łącznie i 0,25 kW na fazę. Moc falownika, limit ładowarki i BMS pozostają osobnymi ograniczeniami.</p></section>'+
      this.loadsHtml()+
      '<section><h2>Prognoza modelu</h2>'+(plan.quality==="valid"?'<div class="grid">'+card("Modelowy cel przed 07:00",num(targets.night?.soc_percent),"%",time(targets.night?.deadline))+
      card("Modelowy cel przed szczytem",num(targets.peak?.soc_percent),"%",time(targets.peak?.deadline))+
      '</div>':'')+
      (rows.length?'<svg viewBox="0 0 960 230" preserveAspectRatio="none" role="img" aria-label="Prognozowany SoC">'+(floor!==null?'<line x1="0" x2="960" y1="'+(220-floor*2)+'" y2="'+(220-floor*2)+'" stroke-dasharray="7 7"/>':'')+'<polyline points="'+points+'" fill="none" stroke-width="3" vector-effect="non-scaling-stroke"/></svg><div class="legend">Linia ciągła: projekcja SoC · Przerywana: stała rezerwa · To prognoza, nie pomiar.</div>':'<div class="notice">Brak kompletnej prognozy. Silnik pokazuje zachowawcze cele i przyczynę braku planu.</div>')+
      '</section><details><summary>Ustawienia zaawansowane i szczegóły</summary>'+this.appearanceHtml()+'<section><h2>Limity i model</h2><div class="fields">'+Object.entries(labels).filter(([key])=>!["min_soc_percent","capacity_kwh","pv_peak_kwp","grid_import_limit_kw","grid_phase_limit_kw"].includes(key)).map(([key,label])=>{
        const r=ranges[key],value=Object.prototype.hasOwnProperty.call(this.drafts,key)?this.drafts[key]:o[key]??"";return '<label>'+esc(label)+'<input data-key="'+key+'" type="number" min="'+r[0]+'" max="'+r[1]+'" step="'+r[2]+'" value="'+esc(value)+'"><button data-save="'+key+'" class="secondary" '+(this.busy?'disabled':'')+'>Zapisz</button></label>';
      }).join("")+'</div><p class="legend">Przypisanie encji: Ustawienia → Urządzenia i usługi → Deye EMS → Konfiguruj.</p><button id="recalculate" class="secondary" '+(this.busy?'disabled':'')+'>Przelicz plan</button></section>'+
      '<section><h2>Regulacja ładowania</h2>'+card("Żądany limit ładowania",num(request,0),"A",'Odczyt nastawy: '+num(readSetting,0)+' A · dostępne do '+num(fresh?c.cap_a:null,0)+' A · pomiar baterii: '+num(this.kw("battery_power"))+' kW')+'<p>'+esc(phaseModel)+'</p><p class="legend">'+this.gridPhaseReadoutHtml()+' · limity importu: '+num(o.grid_import_limit_kw)+' kW łącznie / '+num(o.grid_phase_limit_kw)+' kW na fazę.</p><p class="legend">Zwykłe zmiany o :00 i :30: wyliczona nastawa bez rampy, zaokrąglenie do 5 A i korekta od 10 A. Bezpieczny start może mieć mniej niż 5 A. Po ograniczeniu wymagane są 2 minuty stabilnych warunków; po osiągnięciu celu wznowienie wymaga spadku SoC o 2 p.p. Redukcje ochronne i zakończenie ładowania działają od razu. Wyliczone żądanie, odczyt nastawy i pomiar baterii opisują różne etapy działania.</p></section>'+
      '<section><h2>Prognozowane przepływy</h2><div class="table"><table><thead><tr><th>Termin</th><th>PV kW</th><th>Dom kW</th><th>SoC %</th><th>Grid kW</th></tr></thead><tbody>'+
      rows.filter((_,i)=>i%2===0).map(r=>'<tr><td>'+esc(time(r.timestamp))+'</td><td>'+num(r.pv_kw)+'</td><td>'+num(r.load_kw)+'</td><td>'+num(r.soc_percent)+'</td><td>'+num(r.grid_import_kw)+'</td></tr>').join("")+
      '</tbody></table></div></section></details><footer>Własny silnik Deye EMS · Plan '+esc(time(plan.generated_at))+
      '<br>Bez EMHASS i zewnętrznej usługi obliczeniowej. Ograniczenie importu reaguje na pomiary; nie zastępuje zabezpieczeń falownika i BMS. Wersja '+PANEL_VERSION+'.</footer></main>';
    const details=this.shadowRoot.querySelector("details");
    if(details)details.open=detailsOpen;
    this.bindLoads();
    this.bindSolcast();
    this.bindSources();
    this.bindHardware();
    this.bindAppearance();
    this.bindUpdates();
    this.bindTelemetryDiagnostics();
    this.shadowRoot.getElementById("recalculate")?.addEventListener("click",()=>this.command({command:"recalculate"}));
    this.shadowRoot.getElementById("mode")?.addEventListener("click",()=>this.command({command:"mode",mode:active?"shadow":"active"}));
    this.shadowRoot.getElementById("topology")?.addEventListener("change",event=>{this.drafts.topology=event.target.value;});
    this.shadowRoot.getElementById("topology-save")?.addEventListener("click",()=>{
      if(active||this.busy)return;
      const value=this.shadowRoot.getElementById("topology")?.value;
      if(["load_only","load_with_external_ct"].includes(value))
        this.command({command:"option",key:"topology",value},"topology");
    });
    this.shadowRoot.querySelectorAll("input[data-key]").forEach(input=>input.addEventListener("input",()=>{this.drafts[input.dataset.key]=input.value;}));
    this.shadowRoot.querySelectorAll("[data-save]").forEach(b=>b.addEventListener("click",()=>{
      const key=b.dataset.save,input=this.shadowRoot.querySelector('input[data-key="'+key+'"]');
      if(input.reportValidity())this.command({command:"option",key,value:Number(input.value)},key);
    }));
  }
}
if(!customElements.get(PANEL_TAG))customElements.define(PANEL_TAG,DeyeEMSPanel);

