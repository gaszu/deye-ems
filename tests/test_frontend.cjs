/* Offline component checks. No browser, HA server or external network is used. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "../custom_components/deye_ems/frontend/deye-ems-panel.js"), "utf8");
const NOW = Date.parse("2026-11-10T22:00:00+01:00");
const decode = value => value.replaceAll("&quot;", '"').replaceAll("&#39;", "'").replaceAll("&lt;", "<").replaceAll("&gt;", ">").replaceAll("&amp;", "&");
class FakeStyle {
  constructor(){this.values=new Map();}
  setProperty(key,value){this.values.set(key,value);}
  removeProperty(key){const previous=this.values.get(key);this.values.delete(key);return previous||"";}
  getPropertyValue(key){return this.values.get(key)||"";}
}

class FakeNode {
  constructor(attrs) {this.attrs=attrs;this.dataset={};this.events={};this.value=decode(attrs.value??"");this.open=attrs.tag==="details"&&attrs.open===true;this.checked=attrs.checked===true;this.disabled=attrs.disabled===true;this.required=attrs.required===true;for(const [key,value] of Object.entries(attrs))if(key.startsWith("data-"))this.dataset[key.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=value;}
  addEventListener(type,callback) {this.events[type]=callback;}
  reportValidity() {const n=Number(this.value);return this.value!==""&&Number.isFinite(n)&&n>=Number(this.attrs.min)&&n<=Number(this.attrs.max);}
  matches(selector) {return selector.split(",").some(s=>{const match=/^(input|select)\[data-([a-z-]+)\]$/.exec(s);return match&&this.attrs.tag===match[1]&&this.dataset[match[2].replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]!==undefined;});}
}

class FakeShadow {
  constructor() {this.activeElement=null;this.html="";this.nodes=[];}
  set innerHTML(html) {this.html=html;this.nodes=[];for(const match of html.matchAll(/<(input|select|button|details|form)\b([^>]*)>/g)){const attrs={tag:match[1]};for(const pair of match[2].matchAll(/([\w-]+)="([^"]*)"/g))attrs[pair[1]]=pair[2];for(const flag of ["open","checked","disabled","required"])attrs[flag]=new RegExp('(?:^|\\s)'+flag+'(?:\\s|$)').test(match[2]);this.nodes.push(new FakeNode(attrs));}for(const match of html.matchAll(/<select\b([^>]*)>([\s\S]*?)<\/select>/g)){const name=/data-solcast-field="([^"]+)"/.exec(match[1])?.[1],id=/\bid="([^"]+)"/.exec(match[1])?.[1],node=name?this.nodes.find(n=>n.dataset.solcastField===name):this.nodes.find(n=>n.attrs.id===id);const selected=/<option\b([^>]*\bselected\b[^>]*)>/.exec(match[2]);if(node&&selected)node.value=decode(/value="([^"]*)"/.exec(selected[1])?.[1]??"");}}
  get innerHTML() {return this.html;}
  getElementById(id) {return this.nodes.find(n=>n.attrs.id===id);}
  querySelector(selector) {if(selector==="details")return this.nodes.find(n=>n.attrs.tag==="details");const solcast=/\[data-solcast-field="([^"]+)"\]/.exec(selector)?.[1];if(solcast)return this.nodes.find(n=>n.dataset.solcastField===solcast);const field=/\[data-load-field="([^"]+)"\]/.exec(selector)?.[1];if(field)return this.nodes.find(n=>n.dataset.loadField===field);const key=/input\[data-key="([^"]+)"\]/.exec(selector)?.[1];return this.nodes.find(n=>n.attrs.tag==="input"&&n.dataset.key===key);}
  querySelectorAll(selector) {const data=/^\[data-([a-z-]+)\]$/.exec(selector)?.[1];if(data){const key=data.replace(/-([a-z])/g,(_,c)=>c.toUpperCase());return this.nodes.filter(n=>n.dataset[key]!==undefined);}return this.nodes.filter(n=>selector==="input[data-key]"&&n.attrs.tag==="input"&&n.dataset.key!==undefined);}
}

function fixture(previousElements = []) {
  const registry = new Map(previousElements);
  class HTMLElement {constructor(){this.style=new FakeStyle();}attachShadow(){this.shadowRoot=new FakeShadow();return this.shadowRoot;}}
  class ClockDate extends Date {static now(){return NOW;}}
  const context = vm.createContext({HTMLElement,Date:ClockDate,console,
    customElements:{get:name=>registry.get(name),define:(name,type)=>registry.set(name,type)},
    setInterval:()=>1,clearInterval:()=>{},setTimeout:()=>1,clearTimeout:()=>{},fetch:()=>{throw Error("External requests are forbidden");}});
  vm.runInContext(source,context,{filename:"deye-ems-panel.js"});
  const Panel = registry.get("deye-ems-panel-1-0-10");
  const panel = new Panel();
  const calls=[];
  panel._hass={themes:{themes:{},darkMode:false,theme:"default"},selectedTheme:{dark:false},
    states:{"sensor.raw_stale":{state:"99",attributes:{friendly_name:"Raw stale reading"}}},
    callWS:async message=>{calls.push(message);return panel.payload;}};
  panel.payload={entry_id:"test-entry",appearance:{theme:""},mode:"shadow",effective_loads:[],loads_revision:"revision-1",options:{min_soc_lower_bound:15,min_soc_bound_valid:true,min_soc_percent:50,grid_import_limit_kw:12,grid_phase_limit_kw:5,extra_loads:[]},
    sources:{soc:"sensor.raw_stale"},data:{updated_at:new Date(NOW).toISOString(),
      inputs:{soc:62,soc_valid:true,telemetry_valid:true,grid_power:0,load_power:2800,current_a:27,battery_power:-1400},
      control:{next_a:29,cap_a:45,read_setting_a:27,target_soc:75,target_deadline:"2026-11-11T07:00:00+01:00",target_source:"dated_cache",reason:"ramp_up"},
      plan:{status:"ok",quality:"valid",generated_at:new Date(NOW).toISOString(),targets:{night:{soc_percent:80,deadline:"2026-11-11T07:00:00+01:00"},peak:{soc_percent:65,deadline:"2026-11-11T16:00:00+01:00"}},rows:[]}}};
  panel.render();
  return {panel,calls,registry};
}

test("an existing browser session registers the updated panel alongside the old element",()=>{
  class LegacyPanel {}
  const {panel,registry}=fixture([["deye-ems-panel",LegacyPanel],["deye-ems-panel-1-0-1",LegacyPanel],["deye-ems-panel-1-0-5",LegacyPanel]]);
  assert.equal(registry.get("deye-ems-panel"),LegacyPanel);
  assert.equal(registry.get("deye-ems-panel-1-0-1"),LegacyPanel);
  assert.equal(registry.get("deye-ems-panel-1-0-5"),LegacyPanel);
  assert.notEqual(registry.get("deye-ems-panel-1-0-10"),LegacyPanel);
  assert.match(panel.shadowRoot.innerHTML,/Wersja 1\.0\.10/);
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
  assert.equal((beforeAdvanced.match(/<input /g)||[]).length,5);
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

test("reserve editor uses Battery low SOC margin rather than a fixed forty percent",()=>{
  const {panel}=fixture();
  Object.assign(panel.payload.options,{min_soc_percent:15,min_soc_lower_bound:15,
    min_soc_bound_valid:true,effective_min_soc_percent:15});
  panel.render();
  assert.match(panel.shadowRoot.innerHTML,/data-key="min_soc_percent" type="number" min="15"/);
  assert.match(panel.shadowRoot.innerHTML,/Battery low SOC \+ 5 p.p./);
  panel.payload.options.min_soc_lower_bound=25;
  panel.payload.options.effective_min_soc_percent=25;
  panel.render();
  assert.equal(panel.shadowRoot.querySelector('input[data-key="min_soc_percent"]').value,"25");
});

test("missing low-SOC readback disables the reserve save button",()=>{
  const {panel}=fixture();
  Object.assign(panel.payload.options,{min_soc_bound_valid:false,min_soc_lower_bound:null});
  panel.render();
  assert.match(panel.shadowRoot.innerHTML,/brak poprawnego odczytu Battery low SOC/);
  assert.match(panel.shadowRoot.innerHTML,/data-save="min_soc_percent" disabled/);
});

test("connection limits are visible for both topologies and permit sixteen kilowatts",()=>{
  for(const topology of ["load_only","load_with_external_ct"]){
    const {panel}=fixture();panel.payload.options.topology=topology;panel.render();
    const basic=panel.shadowRoot.innerHTML.split("<details>")[0];
    assert.match(basic,/Przyłącze sieciowe/);
    assert.match(basic,/data-key="grid_import_limit_kw" type="number" min="1" max="30"/);
    assert.match(basic,/data-key="grid_phase_limit_kw" type="number" min="0.5" max="15"/);
    const input=panel.shadowRoot.querySelector('input[data-key="grid_import_limit_kw"]');
    input.value="16";assert.equal(input.reportValidity(),true);
    assert.equal((panel.shadowRoot.innerHTML.match(/data-key="grid_import_limit_kw"/g)||[]).length,1);
  }
});

test("panel offers LOAD and CT selection and saves only the explicit EMS option",()=>{
  const {panel}=fixture();const calls=[];
  panel.command=async args=>{calls.push(args);};
  const select=panel.shadowRoot.getElementById("topology");
  assert.equal(select.value,"load_only");
  select.value="load_with_external_ct";
  select.events.change({target:select});
  assert.equal(calls.length,0);
  panel.shadowRoot.getElementById("topology-save").events.click();
  assert.equal(calls.length,1);
  assert.equal(calls[0].command,"option");
  assert.equal(calls[0].key,"topology");
  assert.equal(calls[0].value,"load_with_external_ct");
});

test("failed topology save distinguishes the retained draft from the saved LOAD model",async()=>{
  const {panel}=fixture();
  panel.payload.options.topology="load_only";
  panel.drafts.topology="load_with_external_ct";
  panel._hass.callWS=async()=>{throw Error("expected float or int at 'value'");};
  await panel.command({command:"option",key:"topology",value:"load_with_external_ct"},"topology");
  assert.equal(panel.shadowRoot.getElementById("topology").value,"load_with_external_ct");
  assert.match(panel.shadowRoot.innerHTML,/Zapisany tryb EMS: Zero Export To Load/);
  assert.match(panel.shadowRoot.innerHTML,/Niezapisana zmiana/);
});

test("successful topology save shows the confirmed CT model and clears its draft",async()=>{
  const {panel}=fixture();
  panel.drafts.topology="load_with_external_ct";
  panel._hass.callWS=async()=>({...panel.payload,options:{...panel.payload.options,topology:"load_with_external_ct"}});
  await panel.command({command:"option",key:"topology",value:"load_with_external_ct"},"topology");
  assert.equal(panel.drafts.topology,undefined);
  assert.match(panel.shadowRoot.innerHTML,/Zapisany tryb EMS: Zero Export To CT/);
  assert.doesNotMatch(panel.shadowRoot.innerHTML,/Niezapisana zmiana/);
});

test("active mode prevents topology save even if a disabled button event is forced",()=>{
  const {panel}=fixture();const calls=[];
  panel.payload.mode="active";panel.render();
  panel.command=async args=>{calls.push(args);};
  assert.equal(panel.shadowRoot.getElementById("topology").disabled,true);
  panel.shadowRoot.getElementById("topology-save").events.click();
  assert.equal(calls.length,0);
});

test("CT topology separates zero utility exchange from GRID export feeding an external branch",()=>{
  const {panel}=fixture();
  Object.assign(panel.payload.data.inputs,{topology:"load_with_external_ct",grid_power:0,
    load_power:5000,raw_load_power:3000,outside_load_w:2000,grid_port_power:-2000});
  panel.payload.options.inverter_max_power_kw=10;
  panel.render();
  assert.equal(panel.kw("grid_power"),0);
  assert.equal(panel.kw("grid_port_power"),-2);
  assert.equal(panel.kw("load_power"),5);
  assert.match(panel.shadowRoot.innerHTML,/Sieć mierzona na CT/);
  assert.match(panel.shadowRoot.innerHTML,/port GRID falownika: -2/);
  panel.payload.data.inputs.telemetry_valid=false;
  assert.equal(panel.kw("grid_port_power"),null);
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

const flush=()=>new Promise(resolve=>setImmediate(resolve));
const nativeMenu=(id="native-flow",step="solcast")=>({type:"menu",flow_id:id,step_id:step,
  menu_options:step==="init"?["parameters","solcast","sources"]:["solcast_manual","solcast_import","solcast_disable"]});
function manualForm(id="native-flow",imported=false,errors={}){
  const schema=[
    {name:"api_key",required:false,default:"saved-key-must-never-appear",description:{suggested_value:"saved-key-suggestion"},selector:{text:{type:"password"}}},
    {name:"resource_ids",default:"roof-one",selector:{text:{}}},
    {name:"poll_interval_minutes",required:true,default:360,selector:{number:{min:15,max:1440,step:1,mode:"box"}}},
    {name:"max_requests_per_day",required:true,default:10,selector:{number:{min:1,max:1000,step:1}}},
    {name:"initial_requests_used",required:true,default:10,selector:{number:{min:0,max:1000,step:1}}},
    {name:"dampening_factor",required:true,default:1,selector:{number:{min:0,max:2,step:0.01}}},
    {name:"hourly_factors",default:"1 ".repeat(23)+"1",selector:{text:{}}}
  ];
  if(imported)schema.push({name:"accept_manual_calibration",required:true,default:false,selector:{boolean:{}}});
  return {type:"form",flow_id:id,step_id:"solcast_manual",data_schema:schema,errors,
    description_placeholders:{import_note:imported?"Skopiowano stan współczynników, bez dalszego samouczenia.":"Puste pole zachowuje zapisany klucz."}};
}
function nativeSolcast(panel,{id="native-flow",manual,finish}={}){
  const apiCalls=[],effects={writes:0};
  panel._hass.callApi=async(method,route,data)=>{
    apiCalls.push({method,route,data});
    if(method==="DELETE")return {message:"Flow aborted"};
    if(route==="config/config_entries/options/flow")return nativeMenu(id,"init");
    if(data.next_step_id==="solcast")return nativeMenu(id);
    if(data.next_step_id==="solcast_manual")return manualForm(id);
    if(data.next_step_id==="solcast_import")return {type:"form",flow_id:id,step_id:"solcast_import",errors:{},
      data_schema:[{name:"source_entry",required:true,selector:{select:{options:[{value:"source-one",label:"Solcast z HA"}]}}}]};
    if(data.source_entry)return manualForm(id,true);
    if(data.next_step_id==="solcast_disable"||!data.next_step_id){
      if(manual&&!data.next_step_id)return manual(data);
      effects.writes++;
      return finish?finish(data):{type:"create_entry",flow_id:id,data:{solcast:{api_key:"private-server-result"}}};
    }
    throw Error("Unexpected synthetic API request");
  };
  return {apiCalls,effects};
}
function solcastInput(panel,name,value){
  const input=panel.shadowRoot.querySelector('[data-solcast-field="'+name+'"]');
  assert.ok(input,name);
  if(typeof value==="boolean")input.checked=value;else input.value=value;
  input.events.input();
  return input;
}
async function openManual(panel){
  await panel.openSolcast();
  await panel.advanceSolcast({next_step_id:"solcast_manual"});
}

test("Solcast opens the native options menu without changing source or mode",async()=>{
  const {panel,calls}=fixture(),before=JSON.stringify(panel.payload),{apiCalls,effects}=nativeSolcast(panel);
  await panel.openSolcast();
  assert.deepEqual(JSON.parse(JSON.stringify(apiCalls)),[
    {method:"POST",route:"config/config_entries/options/flow",data:{handler:"test-entry"}},
    {method:"POST",route:"config/config_entries/options/flow/native-flow",data:{next_step_id:"solcast"}}
  ]);
  assert.equal(effects.writes,0);assert.equal(calls.length,0);assert.equal(JSON.stringify(panel.payload),before);
  assert.equal(panel.solcastFlow.step_id,"solcast");
  assert.match(panel.solcastHtml(),/Importuj ustawienia z HA/);
  assert.doesNotMatch(panel.solcastHtml(),/href=/);
});

test("Solcast renders native text and number fields without password defaults or suggestions",async()=>{
  const {panel}=fixture();nativeSolcast(panel);await openManual(panel);
  const key=panel.shadowRoot.querySelector('[data-solcast-field="api_key"]');
  assert.equal(key.attrs.type,"password");assert.equal(key.attrs.value,undefined);assert.equal(key.value,"");
  assert.equal(panel.solcastSecret,"");
  assert.doesNotMatch(panel.shadowRoot.innerHTML,/saved-key-must-never-appear|saved-key-suggestion/);
  assert.doesNotMatch(JSON.stringify(panel.solcastFlow),/saved-key-must-never-appear|saved-key-suggestion/);
  assert.equal(panel.shadowRoot.querySelector('[data-solcast-field="poll_interval_minutes"]').value,"360");
  assert.match(panel.solcastHtml(),/Zapisz i włącz pobieranie API/);
});

test("Solcast posts every visible native field using its actual type and clears ephemeral secrets after save",async()=>{
  const {panel}=fixture(),{apiCalls,effects}=nativeSolcast(panel);await openManual(panel);
  solcastInput(panel,"api_key","synthetic-user-key");
  solcastInput(panel,"poll_interval_minutes","420");
  solcastInput(panel,"initial_requests_used","7");
  assert.doesNotMatch(panel.shadowRoot.innerHTML,/synthetic-user-key/);
  assert.equal(panel.drafts.api_key,undefined);assert.equal(panel.payload.api_key,undefined);
  await panel.submitSolcast();await flush();
  const sent=apiCalls.at(-1).data;
  assert.deepEqual(JSON.parse(JSON.stringify(sent)),{api_key:"synthetic-user-key",resource_ids:"roof-one",
    poll_interval_minutes:420,max_requests_per_day:10,initial_requests_used:7,dampening_factor:1,hourly_factors:"1 ".repeat(23)+"1"});
  assert.equal(effects.writes,1);assert.equal(panel.solcastSecret,"");assert.equal(panel.solcastFlow.type,"create_entry");
  assert.doesNotMatch(JSON.stringify(panel.solcastFlow)+JSON.stringify(panel.payload)+panel.shadowRoot.innerHTML,/synthetic-user-key|private-server-result/);
  assert.doesNotMatch(source,/localStorage|sessionStorage|console\.(?:log|error|debug)/);
});

test("a blank Solcast password preserves the saved key by omitting only that field",async()=>{
  const {panel}=fixture(),{apiCalls}=nativeSolcast(panel);await openManual(panel);await panel.submitSolcast();
  const sent=apiCalls.at(-1).data;
  assert.equal(Object.hasOwn(sent,"api_key"),false);
  assert.deepEqual(Object.keys(sent).sort(),["resource_ids","poll_interval_minutes","max_requests_per_day",
    "initial_requests_used","dampening_factor","hourly_factors"].sort());
  assert.equal(sent.initial_requests_used,10);
});

test("Solcast validation errors retain nonsecret drafts and the transient key without echoing native error text",async()=>{
  const {panel}=fixture(),{apiCalls}=nativeSolcast(panel,{manual:()=>manualForm("native-flow",false,
    {base:"invalid_solcast",other:"<script>private-error-key</script>"})});
  await openManual(panel);solcastInput(panel,"api_key","synthetic-key-retained");solcastInput(panel,"resource_ids","roof-edited");
  await panel.submitSolcast();
  assert.equal(panel.solcastSecret,"synthetic-key-retained");assert.equal(panel.solcastDraft.resource_ids,"roof-edited");
  assert.equal(panel.solcastCommitting,false);assert.equal(panel.solcastFlow.type,"form");
  assert.match(panel.solcastHtml(),/Sprawdź klucz/);
  assert.doesNotMatch(panel.shadowRoot.innerHTML,/synthetic-key-retained|private-error-key|<script>/);
  await panel.cancelSolcast();assert.equal(panel.solcastSecret,"");
  assert.equal(apiCalls.at(-1).method,"DELETE");
});

test("Solcast transport and HTTP schema errors use a fixed safe message and retain editable input",async()=>{
  const {panel}=fixture();nativeSolcast(panel,{manual:()=>{throw {message:"private-provider-key",body:{errors:"private-provider-key"}};}});
  await openManual(panel);solcastInput(panel,"api_key","synthetic-local-key");await panel.submitSolcast();
  assert.match(panel.solcastHtml(),/Nie udało się wykonać kroku/);
  assert.doesNotMatch(panel.shadowRoot.innerHTML,/private-provider-key|synthetic-local-key/);
  assert.equal(panel.solcastSecret,"synthetic-local-key");assert.equal(panel.solcastFlow.type,"form");
});

test("Solcast import reuses one flow and displays select and explicit calibration consent",async()=>{
  const {panel}=fixture(),{apiCalls,effects}=nativeSolcast(panel);await panel.openSolcast();
  await panel.advanceSolcast({next_step_id:"solcast_import"});
  const select=solcastInput(panel,"source_entry","source-one");assert.equal(select.attrs.tag,"select");
  await panel.submitSolcast();
  assert.equal(effects.writes,0);assert.equal(panel.solcastFlow.flow_id,"native-flow");
  assert.equal(panel.solcastFlow.step_id,"solcast_manual");
  assert.equal(panel.solcastDraft.accept_manual_calibration,false);
  assert.match(panel.solcastHtml(),/bez dalszego samouczenia/);
  solcastInput(panel,"accept_manual_calibration",true);await panel.submitSolcast();
  assert.equal(apiCalls.at(-1).data.accept_manual_calibration,true);
  assert.equal(apiCalls.filter(call=>call.route==="config/config_entries/options/flow").length,1);
});

test("Solcast disable requires a separate explicit confirmation and cancel never enters that step",async()=>{
  const {panel}=fixture(),{apiCalls,effects}=nativeSolcast(panel);await panel.openSolcast();
  const button=panel.shadowRoot.querySelectorAll("[data-solcast-step]").find(node=>node.dataset.solcastStep==="solcast_disable");
  button.events.click();assert.equal(effects.writes,0);
  assert.match(panel.solcastHtml(),/Tak, wyłącz pobieranie/);
  panel.shadowRoot.getElementById("solcast-disable-back").events.click();assert.equal(effects.writes,0);
  button.events.click();await panel.shadowRoot.getElementById("solcast-disable-confirm").events.click();
  assert.equal(effects.writes,1);assert.equal(apiCalls.at(-1).data.next_step_id,"solcast_disable");
  assert.match(panel.solcastNotice,/wyłączone/);
});

test("Solcast final saves cannot be cancelled while an already dispatched commit is pending",async()=>{
  for(const disable of [false,true]){
    const {panel}=fixture();let finish;
    nativeSolcast(panel,{manual:()=>new Promise(resolve=>{finish=resolve;}),finish:()=>new Promise(resolve=>{finish=resolve;})});
    if(disable){await panel.openSolcast();panel.solcastConfirmDisable=true;}else await openManual(panel);
    const pending=disable?panel.advanceSolcast({next_step_id:"solcast_disable"}):panel.submitSolcast();
    assert.equal(panel.solcastCommitting,true);
    assert.equal(panel.shadowRoot.getElementById("solcast-cancel").disabled,true);
    const sequence=panel.solcastSequence;
    await panel.cancelSolcast();assert.equal(panel.solcastOpen,true);assert.equal(panel.solcastSequence,sequence);
    finish({type:"create_entry",flow_id:"native-flow"});await pending;
    assert.equal(panel.solcastCommitting,false);assert.equal(panel.solcastFlow.type,"create_entry");
  }
});

test("Solcast active mode requires an explicit observation action and blocks pending form submits",async()=>{
  const {panel,calls}=fixture(),{apiCalls}=nativeSolcast(panel);panel.payload.mode="active";
  await panel.openSolcast();assert.equal(apiCalls.length,0);assert.match(panel.solcastHtml(),/Przejdź do obserwacji/);
  panel._hass.callWS=async message=>{calls.push(message);panel.payload={...panel.payload,mode:message.mode||panel.payload.mode};return panel.payload;};
  await panel.shadowRoot.getElementById("solcast-observe").events.click();
  assert.equal(calls[0].command,"mode");assert.equal(calls[0].mode,"shadow");
  assert.equal(panel.solcastFlow.step_id,"solcast");
  await panel.advanceSolcast({next_step_id:"solcast_manual"});
  const before=apiCalls.length;panel.payload.mode="active";await panel.submitSolcast();
  assert.equal(apiCalls.length,before);
});

test("Solcast cancel and disconnect clear the key and DELETE only the native options flow",async()=>{
  for(const disconnect of [false,true]){
    const {panel}=fixture(),{apiCalls}=nativeSolcast(panel);await openManual(panel);
    solcastInput(panel,"api_key","synthetic-cancel-key");
    if(disconnect){panel.disconnectedCallback();await flush();}else await panel.cancelSolcast();
    assert.equal(panel.solcastOpen,false);assert.equal(panel.solcastSecret,"");assert.equal(panel.solcastFlow,null);
    assert.equal(apiCalls.at(-1).method,"DELETE");
    assert.equal(apiCalls.at(-1).route,"config/config_entries/options/flow/native-flow");
    assert.equal(apiCalls.some(call=>call.method==="POST"&&call.data&&Object.keys(call.data).length===0),false);
  }
});

test("a cancelled late Solcast START is deleted and never advances or reopens the editor",async()=>{
  const {panel}=fixture(),apiCalls=[];let finish;
  panel._hass.callApi=(method,route,data)=>{apiCalls.push({method,route,data});return method==="POST"?new Promise(resolve=>{finish=resolve;}):Promise.resolve({message:"Flow aborted"});};
  const opening=panel.openSolcast();await flush();await panel.cancelSolcast();
  finish(nativeMenu("late-created","init"));await opening;await flush();
  assert.equal(panel.solcastOpen,false);assert.equal(panel.solcastFlow,null);
  assert.equal(apiCalls.filter(call=>call.method==="POST").length,1);
  assert.ok(apiCalls.some(call=>call.method==="DELETE"&&call.route.endsWith("/late-created")));
});

test("a late cancelled import cannot overwrite the current Solcast flow",async()=>{
  const {panel}=fixture();nativeSolcast(panel);await panel.openSolcast();
  const originalApi=panel._hass.callApi;let finish;
  panel._hass.callApi=(method,route,data)=>method==="POST"&&data?.next_step_id==="solcast_import"?
    new Promise(resolve=>{finish=resolve;}):originalApi(method,route,data);
  const importing=panel.advanceSolcast({next_step_id:"solcast_import"});
  await panel.cancelSolcast();nativeSolcast(panel,{id:"new-flow"});await panel.openSolcast();
  finish(manualForm("native-flow",true));await importing;await flush();
  assert.equal(panel.solcastFlow.flow_id,"new-flow");assert.equal(panel.solcastFlow.step_id,"solcast");
  assert.equal(panel.solcastSecret,"");
});

test("cancelling during previous-flow DELETE cannot resurrect a new Solcast START",async()=>{
  const {panel}=fixture();nativeSolcast(panel);await panel.openSolcast();
  let finish;const calls=[];
  panel._hass.callApi=(method,route,data)=>{calls.push({method,route,data});return new Promise(resolve=>{finish=resolve;});};
  const reopening=panel.openSolcast();await flush();await panel.cancelSolcast();
  finish({message:"Flow aborted"});await reopening;
  assert.equal(panel.solcastOpen,false);assert.equal(calls.filter(call=>call.method==="POST").length,0);
});

test("Solcast abort reasons and unsupported selectors cannot expose raw messages or submit empty defaults",async()=>{
  const {panel}=fixture();nativeSolcast(panel);await panel.openSolcast();
  panel.applySolcastResult({type:"abort",reason:"private-token-in-reason"},panel.solcastSequence);panel.render();
  assert.doesNotMatch(panel.solcastHtml(),/private-token-in-reason/);
  assert.doesNotMatch(JSON.stringify(panel.solcastFlow),/private-token-in-reason/);
  panel.applySolcastResult({type:"form",flow_id:"native-flow",step_id:"solcast_manual",
    data_schema:[{name:"api_key",selector:{object:{default:"secret"}}}]},panel.solcastSequence);panel.render();
  assert.equal(panel.solcastFlow.type,"abort");assert.equal(panel.shadowRoot.getElementById("solcast-form"),undefined);
  assert.doesNotMatch(panel.solcastHtml(),/secret/);
});

test("Solcast drafts and password input survive polling without inserting the password into HTML",async()=>{
  const {panel}=fixture();nativeSolcast(panel);await openManual(panel);
  const input=solcastInput(panel,"api_key","synthetic-focus-key");solcastInput(panel,"resource_ids","roof-draft");
  panel.shadowRoot.activeElement=input;const html=panel.shadowRoot.innerHTML;
  await panel.refresh();assert.equal(panel.shadowRoot.innerHTML,html);assert.equal(panel.solcastSecret,"synthetic-focus-key");
  assert.doesNotMatch(html,/synthetic-focus-key/);
  panel._hass.callWS=async()=>({...panel.payload,mode:"active"});await panel.refresh();
  assert.match(panel.solcastHtml(),/Przejdź do obserwacji/);assert.equal(panel.solcastDraft.resource_ids,"roof-draft");
});

test("a valid plan from before Solcast SAVE cannot enable resume, and a new plan requires an explicit click",async()=>{
  const {panel,calls}=fixture();panel.payload.data.plan.generated_at=new Date(NOW-1000).toISOString();
  nativeSolcast(panel);await openManual(panel);await panel.submitSolcast();await flush();
  assert.equal(panel.solcastPlanReady(),false);assert.equal(panel.shadowRoot.getElementById("solcast-resume").disabled,true);
  assert.equal(calls.some(call=>call.command==="mode"),false);
  panel.payload={...panel.payload,data:{...panel.payload.data,plan:{...panel.payload.data.plan,generated_at:new Date(NOW).toISOString()}}};
  await panel.refreshAfterSolcast(panel.solcastSequence);
  assert.equal(panel.solcastPlanReady(),true);assert.equal(panel.shadowRoot.getElementById("solcast-resume").disabled,false);
  assert.equal(calls.some(call=>call.command==="mode"),false);
  await panel.shadowRoot.getElementById("solcast-resume").events.click();
  assert.equal(calls.at(-1).command,"mode");assert.equal(calls.at(-1).mode,"active");
});

function appearanceThemes(panel){
  panel._hass.themes={theme:"default",darkMode:false,themes:{
    "synthetic-neutral":{
      "primary-color":"#2468ac","ha-card-background":"var(--card-background-color)",
      "lovelace-background":"var(--background-image)","background-image":"linear-gradient(#123456,#654321)",
      "ha-card-border-radius":"19px","ha-card-box-shadow":"none",
      "ha-color-primary-90":"#dae5ef","ha-color-primary-80":"#c4d5e5","ha-color-primary-40":"#28587d",
      "ha-color-primary-10":"#102a3c","ha-color-primary-20":"#1c3c52","ha-color-primary-60":"#8eb9d7",
      modes:{light:{"card-background-color":"#f7f9fb","primary-text-color":"#24303a"},
        dark:{"card-background-color":"#24303a","primary-text-color":"#f7f9fb"}}
    },
    "synthetic-plain":{"primary-color":"#135724","primary-background-color":"#f0f0f0"}
  }};
}

test("a saved HA theme applies base and current-mode CSS variables only on the panel host",()=>{
  const {panel}=fixture();appearanceThemes(panel);
  const original=JSON.stringify(panel._hass.themes);
  panel.payload.appearance={theme:"synthetic-neutral"};panel.render();
  assert.equal(panel.style.getPropertyValue("--primary-color"),"#2468ac");
  assert.equal(panel.style.getPropertyValue("--card-background-color"),"#f7f9fb");
  assert.equal(panel.style.getPropertyValue("--ha-card-background"),"var(--card-background-color)");
  assert.equal(panel.style.getPropertyValue("--lovelace-background"),"var(--background-image)");
  assert.equal(panel.style.getPropertyValue("--ha-card-border-radius"),"19px");
  assert.equal(panel.style.getPropertyValue("--rgb-primary-color"),"36,104,172");
  assert.equal(panel.style.getPropertyValue("color-scheme"),"light");
  assert.equal(JSON.stringify(panel._hass.themes),original);
  assert.doesNotMatch(panel.shadowRoot.innerHTML,/#2468ac|#123456|#654321/);
  assert.doesNotMatch(source,/frontend\/set_theme|document\.documentElement|document\.body|color-mix\(/);
});

test("HA mode changes reapply named-theme variables and local native button palette references",()=>{
  const {panel}=fixture();appearanceThemes(panel);
  panel.payload.appearance={theme:"synthetic-neutral"};panel.render();
  assert.equal(panel.style.getPropertyValue("--ems-button-background"),"var(--ha-color-primary-90)");
  const themes={...panel._hass.themes,darkMode:true};
  panel.hass={...panel._hass,themes,selectedTheme:{}};
  assert.equal(panel.style.getPropertyValue("--card-background-color"),"#24303a");
  assert.equal(panel.style.getPropertyValue("--primary-text-color"),"#f7f9fb");
  assert.equal(panel.style.getPropertyValue("--ems-button-background"),"var(--ha-color-primary-10)");
  assert.equal(panel.style.getPropertyValue("--ems-button-text"),"var(--ha-color-primary-60)");
  assert.equal(panel.style.getPropertyValue("color-scheme"),"dark");
  panel.hass={...panel._hass,selectedTheme:{dark:false}};
  assert.equal(panel.style.getPropertyValue("--card-background-color"),"#f7f9fb");
  assert.equal(panel.style.getPropertyValue("color-scheme"),"light");
});

test("a dark-only named theme preserves its base without guessing a mode from its colors or name",()=>{
  const {panel}=fixture();
  panel._hass.themes.themes["synthetic-dark-only"]={
    "card-background-color":"#191919","primary-text-color":"#eeeeee",modes:{dark:{}}
  };
  panel.payload.appearance={theme:"synthetic-dark-only"};panel.render();
  assert.equal(panel.style.getPropertyValue("--card-background-color"),"#191919");
  assert.equal(panel.style.getPropertyValue("--primary-text-color"),"#eeeeee");
  assert.equal(panel.style.getPropertyValue("color-scheme"),"light");
  panel.hass={...panel._hass,selectedTheme:{dark:true}};
  assert.equal(panel.style.getPropertyValue("--card-background-color"),"#191919");
  assert.equal(panel.style.getPropertyValue("color-scheme"),"dark");
});

test("changing or removing a theme resets stale CSSOM keys, RGB helpers and button aliases",()=>{
  const {panel}=fixture();appearanceThemes(panel);
  panel.payload.appearance={theme:"synthetic-neutral"};panel.render();
  panel.payload.appearance={theme:"synthetic-plain"};panel.render();
  assert.equal(panel.style.getPropertyValue("--primary-color"),"#135724");
  assert.equal(panel.style.getPropertyValue("--background-image"),"");
  assert.equal(panel.style.getPropertyValue("--ha-card-background"),"");
  assert.equal(panel.style.getPropertyValue("--ha-color-primary-90"),"");
  assert.equal(panel.style.getPropertyValue("--ems-button-text"),"var(--primary-color)");
  panel.payload.appearance={theme:""};panel.render();
  assert.equal(panel.style.values.size,0);
  assert.equal(panel.appearanceMissing,false);
});

test("missing saved themes warn and inherit the current HA profile without saving a replacement",()=>{
  const {panel,calls}=fixture();appearanceThemes(panel);
  panel.payload.appearance={theme:"synthetic-neutral"};panel.render();
  delete panel._hass.themes.themes["synthetic-neutral"];panel.render();
  assert.equal(panel.style.values.size,0);assert.equal(panel.appearanceMissing,true);
  assert.match(panel.appearanceHtml(),/motyw jest niedostępny/);
  assert.match(panel.appearanceHtml(),/Panel używa bieżącego motywu HA/);
  assert.equal(panel.shadowRoot.getElementById("panel-theme").value,"synthetic-neutral");
  assert.equal(calls.length,0);assert.equal(panel.payload.appearance.theme,"synthetic-neutral");
});

test("appearance selection is a draft until the explicit server-confirmed save, including active mode",async()=>{
  const {panel,calls}=fixture();appearanceThemes(panel);panel.payload.mode="active";panel.render();
  const before=JSON.stringify({mode:panel.payload.mode,options:panel.payload.options,sources:panel.payload.sources,plan:panel.payload.data.plan});
  const select=panel.shadowRoot.getElementById("panel-theme");
  select.value="synthetic-neutral";select.events.change();
  assert.equal(panel.style.values.size,0);assert.equal(calls.length,0);
  assert.equal(panel.shadowRoot.getElementById("appearance-save").disabled,false);
  panel._hass.callWS=async message=>{calls.push(message);return {...panel.payload,appearance:{theme:message.theme}};};
  await panel.saveAppearance();
  assert.deepEqual(JSON.parse(JSON.stringify(calls)),[
    {type:"deye_ems/command",command:"appearance",theme:"synthetic-neutral"}
  ]);
  assert.equal(panel.payload.appearance.theme,"synthetic-neutral");
  assert.equal(panel.appearanceDraft,null);
  assert.equal(panel.style.getPropertyValue("--primary-color"),"#2468ac");
  assert.equal(JSON.stringify({mode:panel.payload.mode,options:panel.payload.options,sources:panel.payload.sources,plan:panel.payload.data.plan}),before);
});

test("a failed appearance save preserves the draft and old theme and uses a safe error",async()=>{
  const {panel}=fixture();appearanceThemes(panel);
  panel.payload.appearance={theme:"synthetic-plain"};panel.appearanceDraft="synthetic-neutral";panel.render();
  panel._hass.callWS=async()=>{throw Error("untrusted-theme-data-from-server");};
  await panel.saveAppearance();
  assert.equal(panel.payload.appearance.theme,"synthetic-plain");
  assert.equal(panel.appearanceDraft,"synthetic-neutral");
  assert.equal(panel.style.getPropertyValue("--primary-color"),"#135724");
  assert.match(panel.appearanceHtml(),/Nie udało się zapisać motywu/);
  assert.doesNotMatch(panel.shadowRoot.innerHTML,/untrusted-theme-data-from-server/);
});

test("appearance drafts and select focus survive polling without changing saved styles",async()=>{
  const {panel}=fixture();appearanceThemes(panel);panel.render();
  let select=panel.shadowRoot.getElementById("panel-theme");select.value="synthetic-neutral";select.events.change();
  select=panel.shadowRoot.getElementById("panel-theme");panel.shadowRoot.activeElement=select;
  const html=panel.shadowRoot.innerHTML;
  await panel.refresh();
  assert.equal(panel.shadowRoot.innerHTML,html);assert.equal(panel.appearanceDraft,"synthetic-neutral");
  assert.equal(panel.style.values.size,0);
  panel.shadowRoot.activeElement=null;panel.render();
  assert.equal(panel.shadowRoot.getElementById("panel-theme").value,"synthetic-neutral");
});

test("theme values and RGB helpers update on theme reload without retaining stale mode variables",()=>{
  const {panel}=fixture();appearanceThemes(panel);panel.payload.appearance={theme:"synthetic-neutral"};panel.render();
  panel._hass.themes.themes["synthetic-neutral"]={"primary-color":"#abc","rgb-primary-color":"1,2,3"};
  panel.hass={...panel._hass};
  assert.equal(panel.style.getPropertyValue("--primary-color"),"#abc");
  assert.equal(panel.style.getPropertyValue("--rgb-primary-color"),"1,2,3");
  assert.equal(panel.style.getPropertyValue("--card-background-color"),"");
  assert.equal(panel.style.getPropertyValue("--background-image"),"");
});

test("theme names are escaped and theme definitions never enter the HTML or status payload",()=>{
  const {panel}=fixture();appearanceThemes(panel);
  const name='<img src=x onerror="unexpected()">';
  panel._hass.themes.themes[name]={"primary-color":"#56789a","bad key; color:red":"ignored",nested:{secret:"not-a-css-value"}};
  panel.payload.appearance={theme:name};panel.render();
  assert.match(panel.appearanceHtml(),/&lt;img/);assert.doesNotMatch(panel.shadowRoot.innerHTML,/<img/);
  assert.equal(panel.style.getPropertyValue("--primary-color"),"#56789a");
  assert.equal(panel.style.getPropertyValue("--bad key; color:red"),"");
  assert.equal(panel.style.getPropertyValue("--nested"),"");
  assert.doesNotMatch(panel.shadowRoot.innerHTML,/#56789a|not-a-css-value/);
  assert.equal(Object.hasOwn(panel.payload,"themes"),false);
});

test("the inherited appearance option never calls HA global theme APIs or applies a fabricated default theme",async()=>{
  const {panel,calls}=fixture();appearanceThemes(panel);panel.payload.appearance={theme:"synthetic-plain"};panel.render();
  panel.appearanceDraft="";
  panel._hass.callWS=async message=>{calls.push(message);return {...panel.payload,appearance:{theme:message.theme}};};
  await panel.saveAppearance();
  assert.equal(panel.style.values.size,0);assert.equal(calls.length,1);assert.equal(calls[0].theme,"");
  assert.equal(calls[0].command,"appearance");assert.equal(panel._hass.themes.theme,"default");
  assert.doesNotMatch(panel.appearanceHtml(),/value="default"/);
});

test("a removed draft theme cannot be sent and HA card and Lovelace shape variables remain in the stylesheet",async()=>{
  const {panel,calls}=fixture();appearanceThemes(panel);panel.appearanceDraft="synthetic-gone";
  await panel.saveAppearance();
  assert.equal(calls.length,0);assert.match(panel.appearanceHtml(),/nie jest już dostępny/);
  for(const variable of ["--lovelace-background","--ha-card-background","--ha-card-border-radius","--ha-card-border-width","--ha-card-box-shadow","--ha-card-backdrop-filter","--input-fill-color","--primary-color"]){
    assert.ok(source.includes(variable),variable);
  }
});
