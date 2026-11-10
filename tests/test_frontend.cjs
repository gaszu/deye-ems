/* Offline component checks. No browser, HA server or external network is used. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../custom_components/deye_ems/frontend/deye-ems-panel.js"), "utf8");
const NOW = Date.parse("2026-11-10T22:00:00+01:00");
const decode = value => value.replaceAll("&quot;", '"').replaceAll("&#39;", "'").replaceAll("&lt;", "<").replaceAll("&gt;", ">").replaceAll("&amp;", "&");

class FakeNode {
  constructor(attrs) {this.attrs=attrs;this.dataset={};this.events={};this.value=decode(attrs.value??"");this.open=attrs.tag==="details"&&attrs.open===true;this.checked=attrs.checked===true;this.disabled=attrs.disabled===true;this.required=attrs.required===true;for(const [key,value] of Object.entries(attrs))if(key.startsWith("data-"))this.dataset[key.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=value;}
  addEventListener(type,callback) {this.events[type]=callback;}
  reportValidity() {const n=Number(this.value);return this.value!==""&&Number.isFinite(n)&&n>=Number(this.attrs.min)&&n<=Number(this.attrs.max);}
  matches(selector) {return selector.split(",").some(s=>s==="input[data-key]"&&this.dataset.key!==undefined||s==="input[data-load-field]"&&this.dataset.loadField!==undefined);}
}

class FakeShadow {
  constructor() {this.activeElement=null;this.html="";this.nodes=[];}
  set innerHTML(html) {this.html=html;this.nodes=[];for(const match of html.matchAll(/<(input|button|details|form)\b([^>]*)>/g)){const attrs={tag:match[1]};for(const pair of match[2].matchAll(/([\w-]+)="([^"]*)"/g))attrs[pair[1]]=pair[2];for(const flag of ["open","checked","disabled","required"])attrs[flag]=new RegExp('(?:^|\\s)'+flag+'(?:\\s|$)').test(match[2]);this.nodes.push(new FakeNode(attrs));}}
  get innerHTML() {return this.html;}
  getElementById(id) {return this.nodes.find(n=>n.attrs.id===id);}
  querySelector(selector) {if(selector==="details")return this.nodes.find(n=>n.attrs.tag==="details");const field=/\[data-load-field="([^"]+)"\]/.exec(selector)?.[1];if(field)return this.nodes.find(n=>n.dataset.loadField===field);const key=/input\[data-key="([^"]+)"\]/.exec(selector)?.[1];return this.nodes.find(n=>n.attrs.tag==="input"&&n.dataset.key===key);}
  querySelectorAll(selector) {const data=/^\[data-([a-z-]+)\]$/.exec(selector)?.[1];if(data){const key=data.replace(/-([a-z])/g,(_,c)=>c.toUpperCase());return this.nodes.filter(n=>n.dataset[key]!==undefined);}return this.nodes.filter(n=>selector==="input[data-key]"&&n.attrs.tag==="input"&&n.dataset.key!==undefined);}
}

function fixture(previousElements = []) {
  const registry = new Map(previousElements);
  class HTMLElement {attachShadow(){this.shadowRoot=new FakeShadow();return this.shadowRoot;}}
  class ClockDate extends Date {static now(){return NOW;}}
  const context = vm.createContext({HTMLElement,Date:ClockDate,console,
    customElements:{get:name=>registry.get(name),define:(name,type)=>registry.set(name,type)},
    setInterval:()=>1,clearInterval:()=>{},fetch:()=>{throw Error("External requests are forbidden");}});
  vm.runInContext(source,context,{filename:"deye-ems-panel.js"});
  const Panel = registry.get("deye-ems-panel-1-0-3");
  const panel = new Panel();
  const calls=[];
  panel._hass={states:{"sensor.raw_stale":{state:"99",attributes:{friendly_name:"Raw stale reading"}}},
    callWS:async message=>{calls.push(message);return panel.payload;}};
  panel.payload={mode:"shadow",effective_loads:[],loads_revision:"revision-1",options:{min_soc_percent:50,grid_import_limit_kw:12,grid_phase_limit_kw:5,extra_loads:[]},
    sources:{soc:"sensor.raw_stale"},data:{updated_at:new Date(NOW).toISOString(),
      inputs:{soc:62,soc_valid:true,telemetry_valid:true,grid_power:0,load_power:2800,current_a:27,battery_power:-1400},
      control:{next_a:29,cap_a:45,read_setting_a:27,target_soc:75,target_deadline:"2026-11-11T07:00:00+01:00",target_source:"dated_cache",reason:"ramp_up"},
      plan:{status:"ok",quality:"valid",generated_at:new Date(NOW).toISOString(),targets:{night:{soc_percent:80,deadline:"2026-11-11T07:00:00+01:00"},peak:{soc_percent:65,deadline:"2026-11-11T16:00:00+01:00"}},rows:[]}}};
  panel.render();
  return {panel,calls,registry};
}

test("an existing browser session registers the updated panel alongside the old element",()=>{
  class LegacyPanel {}
  const {panel,registry}=fixture([["deye-ems-panel",LegacyPanel],["deye-ems-panel-1-0-1",LegacyPanel]]);
  assert.equal(registry.get("deye-ems-panel"),LegacyPanel);
  assert.equal(registry.get("deye-ems-panel-1-0-1"),LegacyPanel);
  assert.notEqual(registry.get("deye-ems-panel-1-0-3"),LegacyPanel);
  assert.match(panel.shadowRoot.innerHTML,/Wersja 1\.0\.3/);
});

test("renders four simple primary facts and leaves technical settings collapsed",()=>{
  const {panel}=fixture();
  const html=panel.shadowRoot.innerHTML;
  const stats=html.split('<div class="grid stats">')[1].split('</div>')[0];
  assert.equal((stats.match(/<article>/g)||[]).length,4);
  assert.match(stats,/Akumulator/);assert.match(stats,/Sieć \/ dom/);assert.match(stats,/Wybrany cel SoC/);assert.match(stats,/Tryb/);
  assert.match(html,/<details><summary>Ustawienia zaawansowane/);
  assert.doesNotMatch(html,/<details[^>]*\bopen\b/);
  assert.equal(panel.shadowRoot.querySelector("details").open,false);
  const beforeAdvanced=html.split("<details>")[0];
  assert.equal((beforeAdvanced.match(/<input /g)||[]).length,3);
  assert.match(beforeAdvanced,/data-key="min_soc_percent"/);
  assert.match(beforeAdvanced,/data-key="capacity_kwh"/);
  assert.match(beforeAdvanced,/data-key="pv_peak_kwp"/);
});

test("an expanded details section survives polling while measurements update",async()=>{
  const {panel}=fixture();
  const previous=panel.shadowRoot.querySelector("details");
  previous.open=true;
  panel._hass.callWS=async()=>({...panel.payload,data:{...panel.payload.data,
    inputs:{...panel.payload.data.inputs,soc:63}}});
  await panel.refresh();
  const current=panel.shadowRoot.querySelector("details");
  assert.notEqual(current,previous);
  assert.equal(current.open,true);
  assert.equal(panel.measurement("soc"),63);
  await panel.refresh();
  assert.equal(panel.shadowRoot.querySelector("details").open,true);
});

test("polling respects a manually closed details section after it was open",async()=>{
  const {panel}=fixture();
  panel.shadowRoot.querySelector("details").open=true;
  await panel.refresh();
  panel.shadowRoot.querySelector("details").open=false;
  await panel.refresh();
  assert.equal(panel.shadowRoot.querySelector("details").open,false);
  await panel.refresh();
  assert.equal(panel.shadowRoot.querySelector("details").open,false);
});

test("successful and failed commands preserve the current details state",async()=>{
  for(const open of [true,false])for(const fails of [false,true]){
    const {panel}=fixture();
    panel.shadowRoot.querySelector("details").open=open;
    let finish;
    panel._hass.callWS=()=>new Promise((resolve,reject)=>{
      finish=()=>fails?reject(new Error("Synthetic command failure")):resolve(panel.payload);
    });
    const pending=panel.command({command:"recalculate"});
    assert.equal(panel.busy,true);
    assert.equal(panel.shadowRoot.querySelector("details").open,open);
    finish();
    await pending;
    assert.equal(panel.busy,false);
    assert.equal(panel.shadowRoot.querySelector("details").open,open);
    assert.equal(Boolean(panel.error),fails);
    panel._hass.callWS=async()=>panel.payload;
    await panel.refresh();
    assert.equal(panel.shadowRoot.querySelector("details").open,open);
  }
});

test("command completion respects closing details while the command is pending",async()=>{
  const {panel}=fixture();
  panel.shadowRoot.querySelector("details").open=true;
  let finish;
  panel._hass.callWS=()=>new Promise(resolve=>{finish=()=>resolve(panel.payload);});
  const pending=panel.command({command:"recalculate"});
  panel.shadowRoot.querySelector("details").open=false;
  finish();
  await pending;
  assert.equal(panel.shadowRoot.querySelector("details").open,false);
});

test("distinguishes selected target, forecast target, request, register and physical power",()=>{
  const {panel}=fixture();
  const html=panel.shadowRoot.innerHTML;
  assert.match(html,/Wybrany cel SoC/);assert.match(html,/Modelowy cel przed 07:00/);
  assert.match(html,/ostatni poprawny plan/);
  assert.match(html,/Żądany limit ładowania/);assert.match(html,/Odczyt nastawy: 27 A/);
  assert.match(html,/pomiar baterii:/);
  assert.doesNotMatch(html,/execution confirmed|physical confirmation|dated_cache/);
});

test("unverified fallback targets are not presented as forecasts",()=>{
  const {panel}=fixture();
  panel.payload.data.plan.quality="invalid";
  panel.payload.data.plan.targets.night.soc_percent=95;
  panel.payload.data.control.target_soc=50;
  panel.render();
  assert.match(panel.shadowRoot.innerHTML,/Wybrany cel SoC/);
  assert.match(panel.shadowRoot.innerHTML,/Brak kompletnej prognozy/);
  assert.doesNotMatch(panel.shadowRoot.innerHTML,/Modelowy cel przed 07:00/);
});

test("missing numeric values stay missing, while real zero remains zero",()=>{
  const {panel}=fixture();
  assert.equal(panel.measurement("grid_power"),0);
  assert.equal(panel.kw("grid_power"),0);
  panel.payload.data.inputs.grid_power=null;
  assert.equal(panel.measurement("grid_power"),null);
  assert.equal(panel.kw("grid_power"),null);
  panel.payload.data.inputs.grid_power="";
  assert.equal(panel.kw("grid_power"),null);
  panel.payload.data.inputs.grid_power=false;
  assert.equal(panel.kw("grid_power"),null);
});

test("uses validated runtime measurements rather than numeric raw HA states",()=>{
  const {panel}=fixture();
  assert.equal(panel.measurement("soc"),62);
  panel.payload.data.inputs.soc_valid=false;
  assert.equal(panel.measurement("soc"),null);
  panel.payload.data.inputs.telemetry_valid=false;
  assert.equal(panel.kw("load_power"),null);
});

test("whole-home card uses only the native total LOAD regardless of receiver metadata",()=>{
  const {panel}=fixture();
  panel.payload.data.inputs.outside_load_w=500;
  panel.payload.data.inputs.total_load_with_outside_w=3300;
  assert.equal(panel.kw("load_power"),2.8);
  assert.equal(panel.kw("grid_power"),0);
});

test("rejects snapshots over thirty seconds old and future timestamps",()=>{
  const {panel}=fixture();
  panel.payload.data.updated_at=new Date(NOW-30001).toISOString();
  assert.equal(panel.measurement("soc"),null);
  assert.equal(panel.kw("grid_power"),null);
  panel.render();assert.match(panel.shadowRoot.innerHTML,/Brak aktualnego odczytu/);
  panel.payload.data.updated_at=new Date(NOW+1).toISOString();
  assert.equal(panel.snapshotFresh(),false);
  panel.payload.data.updated_at=new Date(NOW-30000).toISOString();
  assert.equal(panel.snapshotFresh(),true);
});

test("unknown reason codes do not leak into the simple panel",()=>{
  const {panel}=fixture();
  panel.payload.data.control.reason="private_internal_rule_xyz";
  panel.render();
  assert.match(panel.shadowRoot.innerHTML,/Silnik sprawdza plan i dostępne dane/);
  assert.doesNotMatch(panel.shadowRoot.innerHTML,/private_internal_rule_xyz/);
  panel.payload.data.control.reason="constructor";
  panel.payload.data.control.target_source="__proto__";
  panel.render();
  assert.match(panel.shadowRoot.innerHTML,/Silnik sprawdza plan i dostępne dane/);
  assert.doesNotMatch(panel.shadowRoot.innerHTML,/function Object|\[object Object\]/);
});

test("escapes names, source errors and user-visible data",async()=>{
  const {panel}=fixture();
  const attack='<img src=x onerror="alert(1)">';
  panel.payload.effective_loads=[{name:attack,energy_entity:"sensor.test",included_in_load:true}];
  panel.payload.data.control.reason=attack;
  panel.error=attack;
  panel.render();
  assert.doesNotMatch(panel.shadowRoot.innerHTML,/<img/);
  assert.match(panel.shadowRoot.innerHTML,/&lt;img/);
  assert.match(panel.shadowRoot.innerHTML,/&quot;alert\(1\)&quot;/);
});

test("polling keeps a focused input and preserves its draft after blur",async()=>{
  const {panel}=fixture();
  const input=panel.shadowRoot.querySelector('input[data-key="min_soc_percent"]');
  input.value="55";input.events.input();
  panel.shadowRoot.activeElement=input;
  const html=panel.shadowRoot.innerHTML;
  await panel.refresh();
  assert.equal(panel.shadowRoot.innerHTML,html);
  assert.equal(input.value,"55");
  panel.shadowRoot.activeElement=null;
  panel.render();
  assert.equal(panel.shadowRoot.querySelector('input[data-key="min_soc_percent"]').value,"55");
});

test("successful save clears only that draft and uses the confirmed option",async()=>{
  const {panel,calls}=fixture();
  panel.drafts={min_soc_percent:"55",capacity_kwh:"70"};
  panel._hass.callWS=async message=>{calls.push(message);return {...panel.payload,options:{...panel.payload.options,min_soc_percent:55}};};
  await panel.command({command:"option",key:"min_soc_percent",value:55},"min_soc_percent");
  assert.equal(panel.drafts.min_soc_percent,undefined);
  assert.equal(panel.drafts.capacity_kwh,"70");
  assert.equal(panel.shadowRoot.querySelector('input[data-key="min_soc_percent"]').value,"55");
  assert.equal(calls[0].value,55);
});

test("an old in-flight status cannot overwrite a confirmed option save",async()=>{
  const {panel}=fixture();
  const old=panel.payload;
  let resolveStatus;
  panel._hass.callWS=message=>message.type==="deye_ems/status"?new Promise(resolve=>{resolveStatus=resolve;}):Promise.resolve({...old,options:{...old.options,min_soc_percent:55}});
  const status=panel.refresh();
  await panel.command({command:"option",key:"min_soc_percent",value:55},"min_soc_percent");
  resolveStatus(old);
  await status;
  assert.equal(panel.payload.options.min_soc_percent,55);
  assert.equal(panel.shadowRoot.querySelector('input[data-key="min_soc_percent"]').value,"55");
});

test("command errors retain the requested input and escape the error",async()=>{
  const {panel}=fixture();
  panel.drafts.min_soc_percent="55";
  panel._hass.callWS=async()=>{throw new Error('<script>fail()</script>');};
  await panel.command({command:"option",key:"min_soc_percent",value:55},"min_soc_percent");
  assert.equal(panel.busy,false);
  assert.equal(panel.drafts.min_soc_percent,"55");
  assert.equal(panel.shadowRoot.querySelector('input[data-key="min_soc_percent"]').value,"55");
  assert.doesNotMatch(panel.shadowRoot.innerHTML,/<script>/);
  assert.match(panel.shadowRoot.innerHTML,/&lt;script&gt;/);
});

test("additional-load management is inline and has no external requests",()=>{
  const {panel}=fixture();
  assert.match(panel.loadsHtml(),/id="load-add"/);
  assert.doesNotMatch(panel.loadsHtml(),/href=/);
  assert.doesNotMatch(source,/https?:\/\/|\bfetch\(|XMLHttpRequest|import\s*\(/);
});

const PUMP={id:"configured_heatpump",name:"Pompa ciepła",energy_entity:"sensor.pump_energy",power_entity:"",included_in_load:true};
test("shows effective default pump even when raw extra_loads is empty",()=>{
  const {panel}=fixture();panel.payload.effective_loads=[PUMP];panel.render();
  assert.match(panel.loadsHtml(),/Pompa ciepła/);assert.match(panel.loadsHtml(),/sensor\.pump_energy/);
  assert.match(panel.loadsHtml(),/data-load-edit="0"/);assert.match(panel.loadsHtml(),/data-load-delete="0"/);
  assert.doesNotMatch(panel.loadsHtml(),/Brak skonfigurowanych/);
});
test("saving a new receiver sends only its fields and the captured revision",async()=>{
  const {panel,calls}=fixture();panel.editLoad();
  Object.assign(panel.loadDraft,{name:"CWU",energy_entity:"sensor.hotwater_energy",power_entity:"sensor.hotwater_power"});
  panel._hass.callWS=async message=>{calls.push(message);return {...panel.payload,loads_revision:"revision-2",effective_loads:[message.channel]};};
  await panel.saveLoad();
  assert.deepEqual(JSON.parse(JSON.stringify(calls[0])),{type:"deye_ems/command",command:"load_save",original_energy_entity:"",channel:{name:"CWU",energy_entity:"sensor.hotwater_energy",power_entity:"sensor.hotwater_power",included_in_load:true,enabled:true},expected_loads_revision:"revision-1"});
  assert.equal(panel.loadDraft,null);assert.equal(panel.payload.effective_loads.length,1);
});
test("editing uses original identity and replaces the list only with server confirmation",async()=>{
  const {panel,calls}=fixture();panel.payload.effective_loads=[PUMP];panel.editLoad(PUMP);panel.loadDraft.name="Ogrzewanie";
  assert.equal(panel.payload.effective_loads[0].name,"Pompa ciepła");
  panel._hass.callWS=async message=>{calls.push(message);return {...panel.payload,effective_loads:[{...PUMP,...message.channel}],loads_revision:"revision-2"};};
  await panel.saveLoad();assert.equal(calls[0].original_energy_entity,PUMP.energy_entity);assert.equal(panel.payload.effective_loads.length,1);assert.equal(panel.payload.effective_loads[0].name,"Ogrzewanie");
});
test("deletion requires the inline confirmation and never targets the source entity",async()=>{
  const {panel,calls}=fixture();panel.payload.effective_loads=[PUMP];panel.render();
  panel.shadowRoot.querySelectorAll("[data-load-delete]")[0].events.click();
  assert.equal(calls.length,0);assert.match(panel.loadsHtml(),/Źródłowe encje pomiarowe i ich historia pozostaną/);
  panel._hass.callWS=async message=>{calls.push(message);return {...panel.payload,effective_loads:[],loads_revision:"revision-2"};};
  await panel.deleteLoad();assert.equal(calls[0].command,"load_delete");assert.equal(calls[0].original_energy_entity,PUMP.energy_entity);assert.equal(calls[0].expected_loads_revision,"revision-1");assert.equal(panel.loadDelete,null);assert.equal(panel.payload.effective_loads.length,0);
});
test("active mode blocks mutations and offers an explicit observation action",async()=>{
  const {panel,calls}=fixture();panel.editLoad();panel.payload.mode="active";panel.render();
  assert.match(panel.loadsHtml(),/Przejdź do obserwacji/);await panel.saveLoad();assert.equal(calls.length,0);
  panel.loadDraft=null;panel.editLoad(PUMP);assert.equal(panel.loadDraft,null);
  panel.loadDelete={...PUMP,revision:"revision-1"};await panel.deleteLoad();assert.equal(calls.length,0);
  await panel.shadowRoot.getElementById("loads-observe").events.click();assert.equal(calls[0].command,"mode");assert.equal(calls[0].mode,"shadow");
});
test("load editor drafts and focus survive polling and blur",async()=>{
  const {panel}=fixture();panel.editLoad();const input=panel.shadowRoot.querySelector('[data-load-field="name"]');input.value="Klimatyzacja";input.events.input();panel.shadowRoot.activeElement=input;
  const html=panel.shadowRoot.innerHTML;await panel.refresh();assert.equal(panel.shadowRoot.innerHTML,html);
  panel.shadowRoot.activeElement=null;panel.render();assert.equal(panel.shadowRoot.querySelector('[data-load-field="name"]').value,"Klimatyzacja");
});
test("load validation failure preserves draft, original revision and escaped error",async()=>{
  const {panel}=fixture();panel.editLoad();panel.loadDraft.name="Nowy";panel.payload.loads_revision="revision-2";
  let sent;panel._hass.callWS=async message=>{sent=message;throw Error('<script>conflict</script>');};
  await panel.saveLoad();assert.equal(sent.expected_loads_revision,"revision-1");assert.equal(panel.loadDraft.name,"Nowy");assert.match(panel.loadsHtml(),/&lt;script&gt;conflict/);assert.doesNotMatch(panel.loadsHtml(),/<script>/);
});
test("receiver form models SoC and never offers adding its demand to total LOAD",()=>{
  const {panel}=fixture();panel.editLoad(PUMP);
  assert.equal(panel.shadowRoot.querySelector('[data-load-field="included_in_load"]'),undefined);
  assert.equal(panel.shadowRoot.querySelector('[data-load-field="power_entity"]').required,false);
  assert.equal(panel.loadDraft.energy_entity,PUMP.energy_entity);assert.match(panel.loadsHtml(),/prognozy SoC/);
});
test("ON/OFF checkbox sends a toggle and keeps the configured receiver",async()=>{
  const {panel,calls}=fixture();panel.payload.effective_loads=[PUMP];panel.render();
  const input=panel.shadowRoot.querySelectorAll("[data-load-toggle]")[0];assert.equal(input.checked,true);
  panel._hass.callWS=async message=>{calls.push(message);return {...panel.payload,effective_loads:[{...PUMP,enabled:message.enabled}],loads_revision:"revision-2"};};
  input.checked=false;await input.events.change();
  assert.equal(calls[0].command,"load_toggle");assert.equal(calls[0].enabled,false);assert.equal(calls[0].expected_loads_revision,"revision-1");
  assert.equal(panel.payload.effective_loads.length,1);assert.equal(panel.payload.effective_loads[0].energy_entity,PUMP.energy_entity);assert.equal(panel.shadowRoot.querySelectorAll("[data-load-toggle]")[0].checked,false);
  panel.editLoad(panel.payload.effective_loads[0]);assert.equal(panel.loadDraft.enabled,false);
});
test("old rendered rows retain their matching revision after a focused poll",async()=>{
  for(const action of ["edit","delete","toggle"]){
    const {panel}=fixture();panel.payload.effective_loads=[PUMP];panel.render();
    const node=panel.shadowRoot.querySelectorAll('[data-load-'+action+']')[0];
    panel.shadowRoot.activeElement=panel.shadowRoot.querySelector('input[data-key="capacity_kwh"]');
    panel._hass.callWS=async()=>({...panel.payload,effective_loads:[{...PUMP,name:"Changed in another tab"}],loads_revision:"revision-2"});
    await panel.refresh();assert.equal(panel.payload.loads_revision,"revision-2");
    panel.shadowRoot.activeElement=null;
    if(action==="edit"){node.events.click();assert.equal(panel.loadDraft.name,PUMP.name);assert.equal(panel.loadDraft.revision,"revision-1");}
    if(action==="delete"){node.events.click();assert.equal(panel.loadDelete.revision,"revision-1");}
    if(action==="toggle"){let sent;panel._hass.callWS=async message=>{sent=message;throw Error("Stale list");};node.checked=false;await node.events.change();assert.equal(sent.expected_loads_revision,"revision-1");}
  }
});
test("mode changes are displayed during editing and cancellation stays available",async()=>{
  const {panel}=fixture();panel.editLoad(PUMP);const field=panel.shadowRoot.querySelector('[data-load-field="name"]');field.value="Draft";field.events.input();panel.shadowRoot.activeElement=field;
  panel._hass.callWS=async()=>({...panel.payload,mode:"active"});await panel.refresh();
  assert.match(panel.loadsHtml(),/Przejdź do obserwacji/);assert.equal(panel.loadDraft.name,"Draft");assert.equal(panel.shadowRoot.getElementById("load-cancel").disabled,false);
  panel.shadowRoot.activeElement=null;panel.shadowRoot.getElementById("load-cancel").events.click();assert.equal(panel.loadDraft,null);
});
test("phase model requires a fresh explicit runtime confirmation",()=>{
  const {panel}=fixture();panel.payload.data.inputs.grid_charge_balanced=true;panel.render();assert.match(panel.shadowRoot.innerHTML,/Bilansowanie poboru GRID potwierdzone/);
  panel.payload.data.updated_at=new Date(NOW-30001).toISOString();panel.render();assert.doesNotMatch(panel.shadowRoot.innerHTML,/Bilansowanie poboru GRID potwierdzone/);assert.match(panel.shadowRoot.innerHTML,/bilansowanie GRID niepotwierdzone/);
});
