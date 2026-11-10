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
  constructor(attrs) {this.attrs=attrs;this.dataset={};this.events={};this.value=decode(attrs.value??"");for(const [key,value] of Object.entries(attrs))if(key.startsWith("data-"))this.dataset[key.slice(5)]=value;}
  addEventListener(type,callback) {this.events[type]=callback;}
  reportValidity() {const n=Number(this.value);return this.value!==""&&Number.isFinite(n)&&n>=Number(this.attrs.min)&&n<=Number(this.attrs.max);}
  matches(selector) {return selector==="input[data-key]"&&this.dataset.key!==undefined;}
}

class FakeShadow {
  constructor() {this.activeElement=null;this.html="";this.nodes=[];}
  set innerHTML(html) {this.html=html;this.nodes=[];for(const match of html.matchAll(/<(input|button)\b([^>]*)>/g)){const attrs={tag:match[1]};for(const pair of match[2].matchAll(/([\w-]+)="([^"]*)"/g))attrs[pair[1]]=pair[2];this.nodes.push(new FakeNode(attrs));}}
  get innerHTML() {return this.html;}
  getElementById(id) {return this.nodes.find(n=>n.attrs.id===id);}
  querySelector(selector) {const key=/input\[data-key="([^"]+)"\]/.exec(selector)?.[1];return this.nodes.find(n=>n.attrs.tag==="input"&&n.dataset.key===key);}
  querySelectorAll(selector) {return this.nodes.filter(n=>selector==="[data-save]"?n.dataset.save!==undefined:selector==="input[data-key]"?n.attrs.tag==="input"&&n.dataset.key!==undefined:false);}
}

function fixture(previousElements = []) {
  const registry = new Map(previousElements);
  class HTMLElement {attachShadow(){this.shadowRoot=new FakeShadow();return this.shadowRoot;}}
  class ClockDate extends Date {static now(){return NOW;}}
  const context = vm.createContext({HTMLElement,Date:ClockDate,console,
    customElements:{get:name=>registry.get(name),define:(name,type)=>registry.set(name,type)},
    setInterval:()=>1,clearInterval:()=>{},fetch:()=>{throw Error("External requests are forbidden");}});
  vm.runInContext(source,context,{filename:"deye-ems-panel.js"});
  const Panel = registry.get("deye-ems-panel-1-0-1");
  const panel = new Panel();
  const calls=[];
  panel._hass={states:{"sensor.raw_stale":{state:"99",attributes:{friendly_name:"Raw stale reading"}}},
    callWS:async message=>{calls.push(message);return panel.payload;}};
  panel.payload={mode:"shadow",options:{min_soc_percent:50,grid_import_limit_kw:12,grid_phase_limit_kw:5,extra_loads:[]},
    sources:{soc:"sensor.raw_stale"},data:{updated_at:new Date(NOW).toISOString(),
      inputs:{soc:62,soc_valid:true,telemetry_valid:true,grid_power:0,load_power:2800,current_a:27,battery_power:-1400},
      control:{next_a:29,cap_a:45,read_setting_a:27,target_soc:75,target_deadline:"2026-11-11T07:00:00+01:00",target_source:"dated_cache",reason:"ramp_up"},
      plan:{status:"ok",quality:"valid",generated_at:new Date(NOW).toISOString(),targets:{night:{soc_percent:80,deadline:"2026-11-11T07:00:00+01:00"},peak:{soc_percent:65,deadline:"2026-11-11T16:00:00+01:00"}},rows:[]}}};
  panel.render();
  return {panel,calls,registry};
}

test("an existing browser session registers the updated panel alongside the old element",()=>{
  class LegacyPanel {}
  const {panel,registry}=fixture([["deye-ems-panel",LegacyPanel]]);
  assert.equal(registry.get("deye-ems-panel"),LegacyPanel);
  assert.notEqual(registry.get("deye-ems-panel-1-0-1"),LegacyPanel);
  assert.match(panel.shadowRoot.innerHTML,/Wersja 1\.0\.1/);
});

test("renders four simple primary facts and leaves technical settings collapsed",()=>{
  const {panel}=fixture();
  const html=panel.shadowRoot.innerHTML;
  const stats=html.split('<div class="grid stats">')[1].split('</div>')[0];
  assert.equal((stats.match(/<article>/g)||[]).length,4);
  assert.match(stats,/Akumulator/);assert.match(stats,/Sieć \/ dom/);assert.match(stats,/Wybrany cel SoC/);assert.match(stats,/Tryb/);
  assert.match(html,/<details><summary>Ustawienia zaawansowane/);
  assert.doesNotMatch(html,/<details[^>]*\bopen\b/);
  const beforeAdvanced=html.split("<details>")[0];
  assert.equal((beforeAdvanced.match(/<input /g)||[]).length,3);
  assert.match(beforeAdvanced,/data-key="min_soc_percent"/);
  assert.match(beforeAdvanced,/data-key="capacity_kwh"/);
  assert.match(beforeAdvanced,/data-key="pv_peak_kwp"/);
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

test("shows external demand once in the whole-home card",()=>{
  const {panel}=fixture();
  panel.payload.data.inputs.outside_load_w=500;
  panel.payload.data.inputs.total_load_with_outside_w=3300;
  assert.equal(panel.kw("load_power"),3.3);
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
  panel.payload.options.extra_loads=[{name:attack,energy_entity:"sensor.test",included_in_load:true}];
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

test("additional-load management uses the local integration flow and no CDN",()=>{
  const {panel}=fixture();
  assert.match(panel.shadowRoot.innerHTML,/href="\/config\/integrations\/integration\/deye_ems"/);
  assert.doesNotMatch(source,/https?:\/\/|\bfetch\(|XMLHttpRequest|import\s*\(/);
});
