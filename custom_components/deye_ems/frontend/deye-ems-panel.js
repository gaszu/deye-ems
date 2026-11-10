/* Deye EMS panel: native web component, no CDN, framework or external service. */
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
  load_headroom:"Priorytet zasilania domu", bms_cap:"Limit baterii / falownika",
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

class DeyeEMSPanel extends HTMLElement {
  constructor(){super();this.attachShadow({mode:"open"});this.busy=false;this.error="";this.payload=null;this.drafts={};this.requestSequence=0;}
  set hass(value){this._hass=value;if(this.isConnected&&!this.started){this.started=true;this.refresh();this.timer=setInterval(()=>this.refresh(),10000);}}
  connectedCallback(){if(this._hass&&!this.started){this.started=true;this.refresh();this.timer=setInterval(()=>this.refresh(),10000);}else this.render();}
  disconnectedCallback(){clearInterval(this.timer);this.started=false;}
  async refresh(){if(!this._hass||this.busy)return;const request=++this.requestSequence;try{const payload=await this._hass.callWS({type:"deye_ems/status"});if(request!==this.requestSequence||this.busy)return;this.payload=payload;this.error="";}catch(e){if(request!==this.requestSequence||this.busy)return;this.error=e.message||String(e);}this.render();}
  async command(args,draftKey=null){if(this.busy)return;++this.requestSequence;this.busy=true;this.error="";this.render();try{this.payload=await this._hass.callWS({type:"deye_ems/command",...args});if(draftKey!==null)delete this.drafts[draftKey];}catch(e){this.error=e.message||String(e);}finally{this.busy=false;this.render();}}
  snapshotFresh(){const at=this.payload?.data?.updated_at;if(!at)return false;const age=Date.now()-new Date(at).getTime();return Number.isFinite(age)&&age>=0&&age<=30000;}
  measurement(key){const input=this.payload?.data?.inputs;if(!this.snapshotFresh()||!input)return null;if(key==="soc"?input.soc_valid!==true:input.telemetry_valid!==true)return null;return numeric(key==="load_power"?input.total_load_with_outside_w??input.load_power:input[key]);}
  kw(key){const v=this.measurement(key);return v===null?null:v/1000;}
  render(){
    // A polling response must not replace a focused input or its caret. Drafts
    // also survive rendering after blur, failed commands and later refreshes.
    if(this.shadowRoot.activeElement?.matches?.("input[data-key]"))return;
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
    const extraLoads=Array.isArray(o.extra_loads)?o.extra_loads:[];
    const solcast=d.solcast||{},quota=solcast.quota||{};
    const solcastLabels={ok:"Prognoza pobrana",cached:"Prognoza z datowanego cache",unavailable:"Brak aktualnej prognozy API",not_configured:"Połączenie nieustawione",ha_entities:"Prognoza z wybranych encji HA",disabled:"Pobieranie wyłączone"};
    const solcastStatus=Object.hasOwn(solcastLabels,solcast.status)?solcastLabels[solcast.status]:"Oczekiwanie na prognozę";
    const sourceNames={own_plan:"bieżący plan",dated_cache:"ostatni poprawny plan",dated_cache_with_retained_raise:"plan z dodatkowym zapasem",unreachable_plan_raise:"podwyższony zapas",winter_fallback:"zapas na zimę",summer_emergency_fallback:"awaryjne doładowanie",own_deterministic_planner:"bieżący plan"};
    const selectedSource=Object.hasOwn(sourceNames,c.target_source)?sourceNames[c.target_source]:"oczekiwanie na plan";
    const mode=active?"Sterowanie aktywne":"Obserwacja";
    const basicField=(key,button)=>{const r=ranges[key],value=Object.hasOwn(this.drafts,key)?this.drafts[key]:o[key]??"";return '<label>'+esc(labels[key])+'<input data-key="'+key+'" type="number" min="'+r[0]+'" max="'+r[1]+'" step="'+r[2]+'" value="'+esc(value)+'"><button data-save="'+key+'" '+(this.busy?'disabled':'')+'>'+esc(button)+'</button></label>';};
    this.shadowRoot.innerHTML='<style>'+
      ':host{display:block;background:var(--primary-background-color,#f3f6f7);color:var(--primary-text-color,#182b33);font:15px system-ui;min-height:100vh}*{box-sizing:border-box}main{max-width:1180px;margin:auto;padding:32px 24px 64px}header{display:flex;align-items:center;justify-content:space-between;gap:18px;margin-bottom:24px}h1{font-size:28px;margin:0}h2{font-size:19px;margin:0 0 16px}.eyebrow{color:var(--secondary-text-color,#64787f);font-size:12px;letter-spacing:1.7px;text-transform:uppercase;margin-bottom:8px}.pill{padding:9px 14px;border-radius:100px;background:#dff2eb;color:#12664b;font-weight:650}.pill.shadow{background:#e6edf4;color:#39566e}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:16px}.stats{grid-template-columns:repeat(4,minmax(0,1fr))}article,section{background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#e1e7e9);border-radius:16px;padding:22px}.label,.sub{display:block;color:var(--secondary-text-color,#627780);font-size:13px}.sub{margin-top:10px;min-height:16px}strong{display:block;font-size:32px;line-height:1.5;letter-spacing:-1px}strong small{font-weight:450;letter-spacing:0;font-size:16px;margin-left:5px}section{margin-top:18px}.notice{padding:14px 18px;background:var(--secondary-background-color,#eaf0f2);border-radius:12px;line-height:1.6;margin:18px 0}.error,.warning{background:#fff0d7;color:#774e0c}.actions{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0}button{font:inherit;cursor:pointer;border:0;border-radius:10px;padding:11px 16px;background:#147a64;color:white;font-weight:600}button.secondary{background:var(--secondary-background-color,#e7edef);color:var(--primary-text-color,#294750)}button[disabled]{opacity:.5;cursor:wait}svg{width:100%;height:230px;display:block}.legend{font-size:12px;color:var(--secondary-text-color,#627780)}.fields{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}label{display:block;font-size:13px;color:var(--secondary-text-color,#627780)}input{margin-top:7px;width:100%;border:1px solid var(--divider-color,#d9e2e5);border-radius:8px;background:var(--primary-background-color,#f6f8f9);color:var(--primary-text-color,#192d35);padding:10px;font:inherit}label button{margin-top:8px;padding:7px 10px;font-size:12px}.table{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{text-align:right;white-space:nowrap;padding:9px 12px;border-bottom:1px solid var(--divider-color,#e1e7e9)}th:first-child,td:first-child{text-align:left}footer{color:var(--secondary-text-color,#627780);font-size:12px;line-height:1.7;margin-top:24px}a{color:#18876f}@media(max-width:760px){main{padding:24px 14px}.grid,.stats,.fields{grid-template-columns:repeat(2,minmax(0,1fr))}header{align-items:flex-start}h1{font-size:24px}article,section{padding:16px}strong{font-size:27px}}@media(max-width:420px){.fields{grid-template-columns:1fr}.pill{font-size:12px;padding:8px}header{gap:8px}.sub{font-size:11px}}'+
      'summary{cursor:pointer;padding:18px 2px;font-weight:650}.reserve label{max-width:320px}</style><main><header><div><div class="eyebrow">Silnik lokalny · G13 · Deye</div><h1>Energia pod kontrolą</h1></div><div class="pill '+(active?'':'shadow')+'">'+mode+'</div></header>'+
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
      '<p class="legend">Prognoza Solcast dla tej instalacji jest używana bez ponownego skalowania przez kWp. Moc służy do powiązania profilu z instalacją. Skalowanie profilu referencyjnego można włączyć w konfiguracji.</p><a href="/config/integrations/integration/deye_ems">Połącz i skonfiguruj Solcast</a></section>'+
      '<section><h2>Dodatkowe zużycia</h2><ul>'+extraLoads.map(load=>'<li>'+esc(load.name||load.energy_entity||"Obwód")+' <span class="legend">'+(load.included_in_load?'już w pomiarze domu':'dodatkowy obwód')+'</span></li>').join("")+'</ul>'+
      (!extraLoads.length?'<p class="legend">Brak dodatkowych obwodów. Podstawą pozostaje pomiar domu.</p>':'')+'<a href="/config/integrations/integration/deye_ems">Dodaj lub usuń obwód</a></section>'+
      '<section><h2>Prognoza modelu</h2>'+(plan.quality==="valid"?'<div class="grid">'+card("Modelowy cel przed 07:00",num(targets.night?.soc_percent),"%",time(targets.night?.deadline))+
      card("Modelowy cel przed szczytem",num(targets.peak?.soc_percent),"%",time(targets.peak?.deadline))+
      '</div>':'')+
      (rows.length?'<svg viewBox="0 0 960 230" preserveAspectRatio="none" role="img" aria-label="Prognozowany SoC">'+(floor!==null?'<line x1="0" x2="960" y1="'+(220-floor*2)+'" y2="'+(220-floor*2)+'" stroke="#cf8455" stroke-dasharray="7 7"/>':'')+'<polyline points="'+points+'" fill="none" stroke="#189c80" stroke-width="3" vector-effect="non-scaling-stroke"/></svg><div class="legend">Zielona linia: projekcja SoC · Przerywana: stała rezerwa · To prognoza, nie pomiar.</div>':'<div class="notice">Brak kompletnej prognozy. Silnik pokazuje zachowawcze cele i przyczynę braku planu.</div>')+
      '</section><details><summary>Ustawienia zaawansowane i szczegóły</summary><section><h2>Limity i model</h2><div class="fields">'+Object.entries(labels).filter(([key])=>!["min_soc_percent","capacity_kwh","pv_peak_kwp"].includes(key)).map(([key,label])=>{
        const r=ranges[key],value=Object.prototype.hasOwnProperty.call(this.drafts,key)?this.drafts[key]:o[key]??"";return '<label>'+esc(label)+'<input data-key="'+key+'" type="number" min="'+r[0]+'" max="'+r[1]+'" step="'+r[2]+'" value="'+esc(value)+'"><button data-save="'+key+'" class="secondary" '+(this.busy?'disabled':'')+'>Zapisz</button></label>';
      }).join("")+'</div><p class="legend">Przypisanie encji: Ustawienia → Urządzenia i usługi → Deye EMS → Konfiguruj.</p><button id="recalculate" class="secondary" '+(this.busy?'disabled':'')+'>Przelicz plan</button></section>'+
      '<section><h2>Regulacja ładowania</h2>'+card("Żądany limit ładowania",num(request,0),"A",'Odczyt nastawy: '+num(readSetting,0)+' A · dostępne do '+num(fresh?c.cap_a:null,0)+' A · pomiar baterii: '+num(this.kw("battery_power"))+' kW')+'<p class="legend">Wyliczone żądanie, odczyt nastawy i pomiar baterii opisują różne etapy działania.</p></section>'+
      '<section><h2>Prognozowane przepływy</h2><div class="table"><table><thead><tr><th>Termin</th><th>PV kW</th><th>Dom kW</th><th>SoC %</th><th>Grid kW</th></tr></thead><tbody>'+
      rows.filter((_,i)=>i%2===0).map(r=>'<tr><td>'+esc(time(r.timestamp))+'</td><td>'+num(r.pv_kw)+'</td><td>'+num(r.load_kw)+'</td><td>'+num(r.soc_percent)+'</td><td>'+num(r.grid_import_kw)+'</td></tr>').join("")+
      '</tbody></table></div></section></details><footer>Własny silnik Deye EMS · Plan '+esc(time(plan.generated_at))+
      '<br>Bez EMHASS i zewnętrznej usługi obliczeniowej. Ograniczenie importu reaguje na pomiary; nie zastępuje zabezpieczeń falownika i BMS. Wersja 0.1.0.</footer></main>';
    this.shadowRoot.getElementById("recalculate")?.addEventListener("click",()=>this.command({command:"recalculate"}));
    this.shadowRoot.getElementById("mode")?.addEventListener("click",()=>this.command({command:"mode",mode:active?"shadow":"active"}));
    this.shadowRoot.querySelectorAll("input[data-key]").forEach(input=>input.addEventListener("input",()=>{this.drafts[input.dataset.key]=input.value;}));
    this.shadowRoot.querySelectorAll("[data-save]").forEach(b=>b.addEventListener("click",()=>{
      const key=b.dataset.save,input=this.shadowRoot.querySelector('input[data-key="'+key+'"]');
      if(input.reportValidity())this.command({command:"option",key,value:Number(input.value)},key);
    }));
  }
}
if(!customElements.get("deye-ems-panel"))customElements.define("deye-ems-panel",DeyeEMSPanel);

