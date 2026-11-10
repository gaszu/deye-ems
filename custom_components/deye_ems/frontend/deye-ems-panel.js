/* Deye EMS panel: native web component, no CDN, framework or external service. */
const PANEL_TAG = "deye-ems-panel-1-0-4";
const labels = {
  min_soc_percent: "Minimalny bezpieczny SoC (%)",
  capacity_kwh: "Pojemność magazynu (kWh)",
  pv_peak_kwp: "Moc paneli PV (kWp)",
  pv_forecast_reference_kwp: "Moc referencyjna profilu PV (kWp)",
  grid_import_limit_kw: "Limit importu razem (kW)",
  grid_phase_limit_kw: "Limit importu na fazę (kW)",
  inverter_max_power_kw: "Moc falownika łącznie (kW)",
  inverter_phase_max_power_kw: "Dopuszczalna moc na fazę (kW)",
  reserve_margin_soc_percent: "Bufor prognozy (p.p.)",
  winter_weather_soc_percent: "Zimowy cel przy słabym PV (%)",
  grid_current_max_a: "Limit prądu z sieci (A)",
  charge_max_kw: "Modelowy limit ładowania (kW)",
  discharge_max_kw: "Modelowy limit rozładowania (kW)",
  grid_max_soc_percent: "Maksymalny cel ładowania z sieci (%)"
};
const ranges = {
  min_soc_percent:[40,90,1], capacity_kwh:[1,1000,.1],
  pv_peak_kwp:[.1,1000,.1],pv_forecast_reference_kwp:[.1,1000,.1],
  grid_import_limit_kw:[1,12,.1],grid_phase_limit_kw:[.5,5,.1],
  inverter_max_power_kw:[.1,1000,.1],inverter_phase_max_power_kw:[.1,500,.1],
  reserve_margin_soc_percent:[0,10,1],winter_weather_soc_percent:[45,95,1],
  grid_current_max_a:[0,108,1],charge_max_kw:[.1,12,.1],
  discharge_max_kw:[.1,12,.1],grid_max_soc_percent:[45,95,1]
};
const reasons = {
  planned:"Plan gotowy", initializing:"Uruchamianie", shadow:"Obserwacja",
  telemetry_invalid:"Brak poprawnych, świeżych pomiarów",
  bms_blocked:"BMS blokuje ładowanie", grid_headroom:"Ograniczenie poborem z sieci",
  load_headroom:"Priorytet zasilania domu", bms_cap:"Limit baterii / falownika",converter_cap:"Limit mocy konwersji falownika",
  ramp_up:"Stopniowe zwiększanie prądu", ramp_down:"Stopniowe zmniejszanie prądu",
  ramp_wait:"Oczekiwanie na kolejny krok", target_reached:"Cel SoC osiągnięty",
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

class DeyeEMSPanel extends HTMLElement {
  constructor(){super();this.attachShadow({mode:"open"});this.busy=false;this.error="";this.payload=null;this.drafts={};this.requestSequence=0;this.loadDraft=null;this.loadDelete=null;this.loadError="";this.solcastOpen=false;this.solcastBusy=false;this.solcastCommitting=false;this.solcastFlow=null;this.solcastDraft={};this.solcastSecret="";this.solcastError="";this.solcastNotice="";this.solcastSequence=0;this.solcastConfirmDisable=false;this.solcastRefreshTimer=null;this.solcastSavedAt=0;}
  set hass(value){this._hass=value;if(this.isConnected&&!this.started){this.started=true;this.refresh();this.timer=setInterval(()=>this.refresh(),10000);}}
  connectedCallback(){if(this._hass&&!this.started){this.started=true;this.refresh();this.timer=setInterval(()=>this.refresh(),10000);}else this.render();}
  disconnectedCallback(){clearInterval(this.timer);this.started=false;void this.cancelSolcast(false,true);}
  async refresh(){if(!this._hass||this.busy)return;const request=++this.requestSequence;try{const payload=await this._hass.callWS({type:"deye_ems/status"});if(request!==this.requestSequence||this.busy)return;this.payload=payload;this.error="";}catch(e){if(request!==this.requestSequence||this.busy)return;this.error=e.message||String(e);}this.render();}
  async command(args,draftKey=null){if(this.busy)return false;++this.requestSequence;this.busy=true;this.error="";this.render();try{this.payload=await this._hass.callWS({type:"deye_ems/command",...args});if(draftKey!==null)delete this.drafts[draftKey];return true;}catch(e){this.error=e.message||String(e);return false;}finally{this.busy=false;this.render();}}
  snapshotFresh(){const at=this.payload?.data?.updated_at;if(!at)return false;const age=Date.now()-new Date(at).getTime();return Number.isFinite(age)&&age>=0&&age<=30000;}
  measurement(key){const input=this.payload?.data?.inputs;if(!this.snapshotFresh()||!input)return null;if(key==="soc"?input.soc_valid!==true:input.telemetry_valid!==true)return null;return numeric(input[key]);}
  kw(key){const v=this.measurement(key);return v===null?null:v/1000;}
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
      this.payload=payload;this.error="";
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
    const solcastStage=[this.solcastOpen,this.solcastFlow?.type,this.solcastFlow?.step_id,this.solcastConfirmDisable].join(":");
    const urgent=this.renderedMode!==this.payload?.mode||this.renderedError!==this.error||this.renderedLoadsReady!==Array.isArray(this.payload?.effective_loads)||this.renderedSolcastStage!==solcastStage||this.renderedSolcastError!==this.solcastError||this.renderedSolcastNotice!==this.solcastNotice;
    if(!urgent&&!this.busy&&this.shadowRoot.activeElement?.matches?.("input[data-key],input[data-load-field],input[data-solcast-field],select[data-solcast-field]"))return;
    this.renderedMode=this.payload?.mode;this.renderedError=this.error;this.renderedLoadsReady=Array.isArray(this.payload?.effective_loads);
    this.renderedSolcastStage=solcastStage;this.renderedSolcastError=this.solcastError;this.renderedSolcastNotice=this.solcastNotice;
    const detailsOpen=this.shadowRoot.querySelector("details")?.open===true;
    const p=this.payload||{},d=p.data||{},plan=d.plan||{},c=d.control||{},o=p.options||{};
    const active=p.mode==="active", targets=plan.targets||{}, rows=plan.rows||[];
    const rawFloor=numeric(o.min_soc_percent),floor=rawFloor!==null&&rawFloor>=40&&rawFloor<=90?rawFloor:null;
    const fresh=this.snapshotFresh(),request=fresh?c.next_a:null,readSetting=fresh&&d.inputs?.telemetry_valid===true?c.read_setting_a??d.inputs.current_a:null;
    const points=rows.map((r,i)=>(i/(Math.max(rows.length-1,1))*960).toFixed(1)+","+(220-Number(r.soc_percent||0)*2).toFixed(1)).join(" ");
    const card=(name,value,unit,sub)=>'<article><span class="label">'+esc(name)+'</span><strong>'+esc(value)+'<small>'+esc(unit)+'</small></strong><span class="sub">'+esc(sub||"")+'</span></article>';
    const reason=c.runtime_reason||c.reason||d.reason||d.status||"initializing";
    const owners=d.owner?.conflicts||d.owner?.blocking||d.conflicts||[];
    const safeReason=String(reason).replace(/^safety_/,"");
    const statusText=Object.hasOwn(reasons,reason)?reasons[reason]:Object.hasOwn(reasons,safeReason)?reasons[safeReason]:"Silnik sprawdza plan i dostępne dane";
    const solcast=d.solcast||{},quota=solcast.quota||{};
    const solcastLabels={ok:"Prognoza pobrana",cached:"Prognoza z datowanego cache",unavailable:"Brak aktualnej prognozy API",not_configured:"Połączenie nieustawione",ha_entities:"Prognoza z wybranych encji HA",disabled:"Pobieranie wyłączone"};
    const solcastStatus=Object.hasOwn(solcastLabels,solcast.status)?solcastLabels[solcast.status]:"Oczekiwanie na prognozę";
    const sourceNames={own_plan:"bieżący plan",dated_cache:"ostatni poprawny plan",dated_cache_with_retained_raise:"plan z dodatkowym zapasem",unreachable_plan_raise:"podwyższony zapas",winter_fallback:"zapas na zimę",summer_emergency_fallback:"awaryjne doładowanie",own_deterministic_planner:"bieżący plan"};
    const selectedSource=Object.hasOwn(sourceNames,c.target_source)?sourceNames[c.target_source]:"oczekiwanie na plan";
    const mode=active?"Sterowanie aktywne":"Obserwacja";
    const phaseModel=fresh&&d.inputs?.grid_charge_balanced===true?"Bilansowanie poboru GRID potwierdzone":"Wariant zachowawczy — bilansowanie GRID niepotwierdzone";
    const basicField=(key,button)=>{const r=ranges[key],value=Object.hasOwn(this.drafts,key)?this.drafts[key]:o[key]??"";return '<label>'+esc(labels[key])+'<input data-key="'+key+'" type="number" min="'+r[0]+'" max="'+r[1]+'" step="'+r[2]+'" value="'+esc(value)+'"><button data-save="'+key+'" '+(this.busy?'disabled':'')+'>'+esc(button)+'</button></label>';};
    this.shadowRoot.innerHTML='<style>'+
      'select{margin-top:7px;width:100%;border:1px solid var(--divider-color,#ded9e7);border-radius:8px;background:var(--ems-field);color:var(--ems-text);padding:10px;font:inherit}.solcast-editor{border-top:1px solid var(--divider-color,#e1deea);margin-top:18px;padding-top:6px}.solcast-note{white-space:pre-line}'+
      ':host{--ems-page:var(--primary-background-color,#f4f2f8);--ems-card:var(--card-background-color,#faf9fd);--ems-text:var(--primary-text-color,#38343f);--ems-accent:var(--primary-color,#a29bbc);--ems-button-bg:var(--secondary-background-color,#e7e3ef);--ems-button-hover:var(--secondary-background-color,#ded9ea);--ems-secondary-button-bg:var(--secondary-background-color,#eeebf5);--ems-button-border:var(--divider-color,#d9d4e4);--ems-active-bg:var(--secondary-background-color,#e4ece6);--ems-observe-bg:var(--secondary-background-color,#e6eaf2);--ems-notice:var(--secondary-background-color,#ece9f2);--ems-warning-bg:var(--secondary-background-color,#f3ede2);--ems-error-bg:var(--secondary-background-color,#f2e6eb);--ems-field:var(--primary-background-color,#f5f3f9);--ems-check:var(--primary-color,#8784a5);--ems-chart-color:#789587;--ems-reserve-color:#a79172;--ems-link:var(--primary-text-color,#514c65);--ems-focus:var(--ems-text);display:block;background:var(--ems-page);color:var(--ems-text);font:15px system-ui;min-height:100vh}*{box-sizing:border-box}main{max-width:1180px;margin:auto;padding:32px 24px 64px}header{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:24px}h1{font-size:28px;margin:0}h2{font-size:19px;margin:0 0 16px}.eyebrow{color:var(--secondary-text-color,#77717e);font-size:12px;letter-spacing:1.7px;text-transform:uppercase;margin-bottom:8px}.pill{padding:9px 14px;border-radius:100px;background:var(--ems-active-bg);color:var(--ems-text);font-weight:650}.pill.shadow{background:var(--ems-observe-bg);color:var(--ems-text)}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.stats{grid-template-columns:repeat(4,minmax(0,1fr))}article,section{background:var(--ems-card);border:1px solid var(--divider-color,#e1deea);border-radius:16px;padding:22px}.label,.sub{display:block;color:var(--secondary-text-color,#716b79);font-size:13px}.sub{margin-top:10px;min-height:16px}strong{display:block;font-size:32px;line-height:1.5;letter-spacing:-1px}strong small{font-weight:450;letter-spacing:0;font-size:16px;margin-left:5px}section{margin-top:18px}.notice{padding:14px 18px;background:var(--ems-notice);border-radius:12px;line-height:1.6;margin:18px 0}.error,.warning{background:var(--ems-warning-bg);color:var(--ems-text)}.actions{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}button{font:inherit;cursor:pointer;border:1px solid var(--ems-button-border);border-radius:10px;padding:11px 16px;background:var(--ems-button-bg);color:var(--ems-text);font-weight:600}button.secondary{background:var(--ems-secondary-button-bg);color:var(--ems-text)}button[disabled]{opacity:1;cursor:not-allowed}svg{width:100%;height:230px;display:block}.legend{font-size:12px;color:var(--secondary-text-color,#716b79)}.fields{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}label{display:block;font-size:13px;color:var(--secondary-text-color,#716b79)}input{margin-top:7px;width:100%;border:1px solid var(--divider-color,#ded9e7);border-radius:8px;background:var(--ems-field);color:var(--ems-text);padding:10px;font:inherit}label button{margin-top:8px;padding:7px 10px;font-size:12px}.table{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:right;white-space:nowrap;padding:9px 12px;border-bottom:1px solid var(--divider-color,#e1deea)}th:first-child,td:first-child{text-align:left}footer{color:var(--secondary-text-color,#716b79);font-size:12px;line-height:1.7;margin-top:24px}a{color:var(--ems-link);text-decoration-color:var(--ems-accent);text-decoration-thickness:2px;text-underline-offset:3px}@media(max-width:760px){main{padding:24px 14px}.grid,.stats,.fields{grid-template-columns:repeat(2,minmax(0,1fr))}header{align-items:flex-start}h1{font-size:24px}article,section{padding:16px}strong{font-size:27px}}@media(max-width:420px){.fields{grid-template-columns:1fr}.pill{font-size:12px;padding:8px}header{gap:8px}.sub{font-size:11px}}'+
      'summary{cursor:pointer;padding:18px 2px;font-weight:650}.reserve label{max-width:320px}.loads{list-style:none;padding:0}.load-row{display:flex;justify-content:space-between;align-items:center;gap:16px;border-bottom:1px solid var(--divider-color,#e1deea);padding:14px 0}.load-row .actions{margin:0;flex-shrink:0}.load-switch{display:flex;align-items:center;gap:7px;min-width:65px}.load-switch input{width:20px;height:20px;margin:0;accent-color:var(--ems-check)}code{overflow-wrap:anywhere}fieldset{border:0;padding:0;margin:0}.check{display:flex;align-items:center;gap:10px;margin-top:20px}.check input{width:auto;margin:0}form{border-top:1px solid var(--divider-color,#e1deea);margin-top:18px;padding-top:6px}@media(max-width:600px){.load-row{align-items:flex-start;flex-direction:column}}@supports(background:color-mix(in srgb,#000,#fff)){:host{--ems-page:color-mix(in srgb,var(--ems-accent) 3%,var(--primary-background-color,#f4f2f8));--ems-card:color-mix(in srgb,var(--ems-accent) 3%,var(--card-background-color,#faf9fd));--ems-button-bg:color-mix(in srgb,var(--ems-accent) 17%,var(--ems-card));--ems-button-hover:color-mix(in srgb,var(--ems-accent) 25%,var(--ems-card));--ems-secondary-button-bg:color-mix(in srgb,var(--ems-accent) 7%,var(--ems-card));--ems-button-border:color-mix(in srgb,var(--ems-accent) 32%,var(--divider-color,#d9d4e4));--ems-active-bg:color-mix(in srgb,#9eb4a6 19%,var(--ems-card));--ems-observe-bg:color-mix(in srgb,#a7b6cd 18%,var(--ems-card));--ems-notice:color-mix(in srgb,var(--ems-accent) 9%,var(--ems-card));--ems-warning-bg:color-mix(in srgb,var(--warning-color,#c9ab7c) 13%,var(--ems-card));--ems-error-bg:color-mix(in srgb,var(--error-color,#bd939d) 10%,var(--ems-card));--ems-field:color-mix(in srgb,var(--ems-accent) 4%,var(--primary-background-color,#f5f3f9));--ems-check:color-mix(in srgb,var(--ems-accent) 65%,#8fa89d);--ems-focus:color-mix(in srgb,var(--ems-accent) 60%,var(--ems-text));--ems-chart-color:color-mix(in srgb,#8fa89d 75%,var(--ems-text));--ems-reserve-color:color-mix(in srgb,#b7a27d 75%,var(--ems-text));}}.pill{border:1px solid var(--ems-button-border)}.warning{border:1px solid var(--ems-button-border)}.error{background:var(--ems-error-bg);border:1px solid var(--ems-button-border)}button:hover:not(:disabled){background:var(--ems-button-hover)}button:focus-visible,a:focus-visible,input:focus-visible,select:focus-visible,summary:focus-visible{outline:2px solid var(--ems-focus);outline-offset:3px}button:disabled,input:disabled,select:disabled{opacity:1;color:var(--secondary-text-color,#74707d);background:var(--ems-notice);border-color:var(--divider-color,#d9d4e4);cursor:not-allowed}input,select{caret-color:var(--ems-check);accent-color:var(--ems-check)}svg polyline{stroke:var(--ems-chart-color)}svg line{stroke:var(--ems-reserve-color)}a:hover{background:var(--ems-button-bg)}::selection{background:var(--ems-button-bg);color:var(--ems-text)}</style><main><header><div><div class="eyebrow">Silnik lokalny · G13 · Deye</div><h1>Energia pod kontrolą</h1></div><div class="pill '+(active?'':'shadow')+'">'+mode+'</div></header>'+
      (this.error?'<div role="alert" class="notice error">'+esc(this.error)+'</div>':'')+
      '<div class="grid stats">'+card("Akumulator",num(this.measurement("soc")),"%",'Stała rezerwa '+num(floor)+'%')+
      card("Sieć / dom",num(this.kw("grid_power"))+' / '+num(this.kw("load_power")),"kW","Sieć: + pobór, − eksport · dom: wszystkie wybrane obwody")+
      card("Wybrany cel SoC",num(fresh?c.target_soc:null),"%",time(fresh?c.target_deadline:null)+' · '+selectedSource)+
      card("Tryb",active?"Aktywny":"Obserwacja","",active?"Sterowanie falownikiem":"Planowanie bez poleceń do falownika")+'</div>'+
      (!fresh?'<div class="notice warning">Brak aktualnego odczytu silnika. Pomiary wymagają aktualizacji z ostatnich 30 sekund.</div>':'')+
      '<div class="notice">'+esc(statusText)+(active?'':' · Obliczenia bez poleceń do falownika.')+'</div>'+
      (owners.length?'<div class="notice warning">Przejęcie sterowania blokują: '+owners.map(esc).join(", ")+'</div>':'')+
      ((plan.unreachable||c.unreachable)?'<div class="notice warning">Dostępna energia lub moc może nie wystarczyć do osiągnięcia celu. Limit poboru ma pierwszeństwo.</div>':'')+
      '<div class="actions"><button id="mode" '+(this.busy?'disabled':'')+'>'+(active?'Zatrzymaj i obserwuj':'Włącz sterowanie')+'</button></div>'+
      '<section class="reserve"><h2>Magazyn energii</h2><div class="fields" style="grid-template-columns:repeat(auto-fit,minmax(220px,1fr))">'+basicField("min_soc_percent","Zapisz rezerwę")+basicField("capacity_kwh","Zapisz pojemność")+'</div><p class="legend">Rezerwa jest dolną granicą niezależną od pogody. Pojemność służy do przeliczania procentów na energię.</p></section>'+
      '<section><h2>Fotowoltaika i Solcast</h2><div class="fields">'+basicField("pv_peak_kwp","Zapisz moc PV")+'</div><p>'+esc(solcastStatus)+'</p>'+
      (numeric(quota.utc?.used)!==null?'<p class="legend">Zapytania dziś (UTC): '+num(quota.utc.used,0)+' / '+num(quota.limit,0)+'</p>':'')+
      '<p class="legend">Prognoza Solcast dla tej instalacji jest używana bez ponownego skalowania przez kWp. Moc służy do powiązania profilu z instalacją. Skalowanie profilu referencyjnego można włączyć w konfiguracji.</p>'+this.solcastHtml()+'</section>'+
      this.loadsHtml()+
      '<section><h2>Prognoza modelu</h2>'+(plan.quality==="valid"?'<div class="grid">'+card("Modelowy cel przed 07:00",num(targets.night?.soc_percent),"%",time(targets.night?.deadline))+
      card("Modelowy cel przed szczytem",num(targets.peak?.soc_percent),"%",time(targets.peak?.deadline))+
      '</div>':'')+
      (rows.length?'<svg viewBox="0 0 960 230" preserveAspectRatio="none" role="img" aria-label="Prognozowany SoC">'+(floor!==null?'<line x1="0" x2="960" y1="'+(220-floor*2)+'" y2="'+(220-floor*2)+'" stroke="#cf8455" stroke-dasharray="7 7"/>':'')+'<polyline points="'+points+'" fill="none" stroke="#189c80" stroke-width="3" vector-effect="non-scaling-stroke"/></svg><div class="legend">Zielona linia: projekcja SoC · Przerywana: stała rezerwa · To prognoza, nie pomiar.</div>':'<div class="notice">Brak kompletnej prognozy. Silnik pokazuje zachowawcze cele i przyczynę braku planu.</div>')+
      '</section><details><summary>Ustawienia zaawansowane i szczegóły</summary><section><h2>Limity i model</h2><div class="fields">'+Object.entries(labels).filter(([key])=>!["min_soc_percent","capacity_kwh","pv_peak_kwp"].includes(key)).map(([key,label])=>{
        const r=ranges[key],value=Object.prototype.hasOwnProperty.call(this.drafts,key)?this.drafts[key]:o[key]??"";return '<label>'+esc(label)+'<input data-key="'+key+'" type="number" min="'+r[0]+'" max="'+r[1]+'" step="'+r[2]+'" value="'+esc(value)+'"><button data-save="'+key+'" class="secondary" '+(this.busy?'disabled':'')+'>Zapisz</button></label>';
      }).join("")+'</div><p class="legend">Przypisanie encji: Ustawienia → Urządzenia i usługi → Deye EMS → Konfiguruj.</p><button id="recalculate" class="secondary" '+(this.busy?'disabled':'')+'>Przelicz plan</button></section>'+
      '<section><h2>Regulacja ładowania</h2>'+card("Żądany limit ładowania",num(request,0),"A",'Odczyt nastawy: '+num(readSetting,0)+' A · dostępne do '+num(fresh?c.cap_a:null,0)+' A · pomiar baterii: '+num(this.kw("battery_power"))+' kW')+'<p>'+esc(phaseModel)+'</p><p class="legend">GRID L1 / L2 / L3: '+num(this.kw("grid_l1_power"))+' / '+num(this.kw("grid_l2_power"))+' / '+num(this.kw("grid_l3_power"))+' kW · limity importu: '+num(o.grid_import_limit_kw)+' kW łącznie / '+num(o.grid_phase_limit_kw)+' kW na fazę.</p><p class="legend">Wyliczone żądanie, odczyt nastawy i pomiar baterii opisują różne etapy działania.</p></section>'+
      '<section><h2>Prognozowane przepływy</h2><div class="table"><table><thead><tr><th>Termin</th><th>PV kW</th><th>Dom kW</th><th>SoC %</th><th>Grid kW</th></tr></thead><tbody>'+
      rows.filter((_,i)=>i%2===0).map(r=>'<tr><td>'+esc(time(r.timestamp))+'</td><td>'+num(r.pv_kw)+'</td><td>'+num(r.load_kw)+'</td><td>'+num(r.soc_percent)+'</td><td>'+num(r.grid_import_kw)+'</td></tr>').join("")+
      '</tbody></table></div></section></details><footer>Własny silnik Deye EMS · Plan '+esc(time(plan.generated_at))+
      '<br>Bez EMHASS i zewnętrznej usługi obliczeniowej. Ograniczenie importu reaguje na pomiary; nie zastępuje zabezpieczeń falownika i BMS. Wersja 1.0.4.</footer></main>';
    const details=this.shadowRoot.querySelector("details");
    if(details)details.open=detailsOpen;
    this.bindLoads();
    this.bindSolcast();
    this.shadowRoot.getElementById("recalculate")?.addEventListener("click",()=>this.command({command:"recalculate"}));
    this.shadowRoot.getElementById("mode")?.addEventListener("click",()=>this.command({command:"mode",mode:active?"shadow":"active"}));
    this.shadowRoot.querySelectorAll("input[data-key]").forEach(input=>input.addEventListener("input",()=>{this.drafts[input.dataset.key]=input.value;}));
    this.shadowRoot.querySelectorAll("[data-save]").forEach(b=>b.addEventListener("click",()=>{
      const key=b.dataset.save,input=this.shadowRoot.querySelector('input[data-key="'+key+'"]');
      if(input.reportValidity())this.command({command:"option",key,value:Number(input.value)},key);
    }));
  }
}
if(!customElements.get(PANEL_TAG))customElements.define(PANEL_TAG,DeyeEMSPanel);

