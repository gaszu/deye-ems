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
  constructor(attrs) {this.attrs=attrs;this.type=attrs.type;this.dataset={};this.events={};this.value=decode(attrs.value??"");this.open=attrs.tag==="details"&&attrs.open===true;this.checked=attrs.checked===true;this.disabled=attrs.disabled===true;this.required=attrs.required===true;for(const [key,value] of Object.entries(attrs))if(key.startsWith("data-"))this.dataset[key.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=value;}
  addEventListener(type,callback) {this.events[type]=callback;}
  reportValidity() {const n=Number(this.value);return this.value!==""&&Number.isFinite(n)&&n>=Number(this.attrs.min)&&n<=Number(this.attrs.max);}
  matches(selector) {return selector.split(",").some(s=>{const match=/^(input|select)\[data-([a-z-]+)\]$/.exec(s);return match&&this.attrs.tag===match[1]&&this.dataset[match[2].replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]!==undefined;});}
}

class FakeShadow {
  constructor() {this.activeElement=null;this.html="";this.nodes=[];}
  set innerHTML(html) {this.html=html;this.nodes=[];for(const match of html.matchAll(/<(input|select|button|details|form)\b([^>]*)>/g)){const attrs={tag:match[1]};for(const pair of match[2].matchAll(/([\w-]+)="([^"]*)"/g))attrs[pair[1]]=pair[2];for(const flag of ["open","checked","disabled","required"])attrs[flag]=new RegExp('(?:^|\\s)'+flag+'(?:\\s|$)').test(match[2]);this.nodes.push(new FakeNode(attrs));}for(const match of html.matchAll(/<select\b([^>]*)>([\s\S]*?)<\/select>/g)){const hardwareName=/data-hardware-field="([^"]+)"/.exec(match[1])?.[1];const name=/data-solcast-field="([^"]+)"/.exec(match[1])?.[1],sourceName=/data-source-field="([^"]+)"/.exec(match[1])?.[1],id=/\bid="([^"]+)"/.exec(match[1])?.[1],node=hardwareName?this.nodes.find(n=>n.dataset.hardwareField===hardwareName):name?this.nodes.find(n=>n.dataset.solcastField===name):sourceName?this.nodes.find(n=>n.dataset.sourceField===sourceName):this.nodes.find(n=>n.attrs.id===id);const selected=/<option\b([^>]*\bselected\b[^>]*)>/.exec(match[2]);if(node&&selected)node.value=decode(/value="([^"]*)"/.exec(selected[1])?.[1]??"");}}
  get innerHTML() {return this.html;}
  getElementById(id) {return this.nodes.find(n=>n.attrs.id===id);}
  querySelector(selector) {if(selector==="details")return this.nodes.find(n=>n.attrs.tag==="details");const hardware=/\[data-hardware-field="([^"]+)"\]/.exec(selector)?.[1];if(hardware)return this.nodes.find(n=>n.dataset.hardwareField===hardware);const source=/\[data-source-field="([^"]+)"\]/.exec(selector)?.[1];if(source)return this.nodes.find(n=>n.dataset.sourceField===source);const solcast=/\[data-solcast-field="([^"]+)"\]/.exec(selector)?.[1];if(solcast)return this.nodes.find(n=>n.dataset.solcastField===solcast);const field=/\[data-load-field="([^"]+)"\]/.exec(selector)?.[1];if(field)return this.nodes.find(n=>n.dataset.loadField===field);const key=/input\[data-key="([^"]+)"\]/.exec(selector)?.[1];return this.nodes.find(n=>n.attrs.tag==="input"&&n.dataset.key===key);}
  querySelectorAll(selector) {const data=/^\[data-([a-z-]+)\]$/.exec(selector)?.[1];if(data){const key=data.replace(/-([a-z])/g,(_,c)=>c.toUpperCase());return this.nodes.filter(n=>n.dataset[key]!==undefined);}return this.nodes.filter(n=>selector==="input[data-key]"&&n.attrs.tag==="input"&&n.dataset.key!==undefined);}
}

function fixture(previousElements = [], now = NOW) {
  const registry = new Map(previousElements);
  class HTMLElement {constructor(){this.style=new FakeStyle();}attachShadow(){this.shadowRoot=new FakeShadow();return this.shadowRoot;}}
  class ClockDate extends Date {static now(){return now;}}
  let reloads=0,timerId=0;const timers=[];
  const context = vm.createContext({HTMLElement,Date:ClockDate,console,location:{reload:()=>{reloads++;}},
    customElements:{get:name=>registry.get(name),define:(name,type)=>registry.set(name,type)},
    setInterval:()=>1,clearInterval:()=>{},setTimeout:(fn,ms)=>{const timer={id:++timerId,fn,ms,cleared:false};timers.push(timer);return timer.id;},clearTimeout:id=>{const timer=timers.find(t=>t.id===id);if(timer)timer.cleared=true;},fetch:()=>{throw Error("External requests are forbidden");}});
  vm.runInContext(source,context,{filename:"deye-ems-panel.js"});
  const Panel = registry.get("deye-ems-panel-2-0-3");
  const panel = new Panel();
  const calls=[];
  panel._hass={themes:{themes:{},darkMode:false,theme:"default"},selectedTheme:{dark:false},
    states:{"sensor.raw_stale":{state:"99",attributes:{friendly_name:"Raw stale reading"}}},
    callWS:async message=>{calls.push(message);return panel.payload;}};
  panel.payload={entry_id:"test-entry",backend_version:"2.0.3",appearance:{theme:""},mode:"shadow",effective_loads:[],loads_revision:"revision-1",options:{topology:"load_only",min_soc_lower_bound:15,min_soc_bound_valid:true,min_soc_percent:50,grid_import_limit_kw:12,grid_phase_limit_kw:5,extra_loads:[]},
    sources:{soc:"sensor.raw_stale"},data:{updated_at:new Date(NOW).toISOString(),
      inputs:{topology:"load_only",soc:62,soc_valid:true,telemetry_valid:true,grid_power:0,grid_port_power:0,load_power:2800,raw_load_power:2800,current_a:27,battery_power:-1400},
      control:{next_a:29,cap_a:45,read_setting_a:27,target_soc:75,target_deadline:"2026-11-11T07:00:00+01:00",target_source:"dated_cache",reason:"ramp_up"},
      plan:{status:"ok",quality:"valid",generated_at:new Date(NOW).toISOString(),targets:{night:{soc_percent:80,deadline:"2026-11-11T07:00:00+01:00"},peak:{soc_percent:65,deadline:"2026-11-11T16:00:00+01:00"}},rows:[]}}};
  panel.render();
  return {panel,calls,registry,reloads:()=>reloads,timers,advance:ms=>{now+=ms;}};
}

test("an existing browser session registers the updated panel alongside the old element",()=>{
  class LegacyPanel {}
  const {panel,registry}=fixture([["deye-ems-panel",LegacyPanel],["deye-ems-panel-1-0-1",LegacyPanel],["deye-ems-panel-1-0-5",LegacyPanel],["deye-ems-panel-1-0-10",LegacyPanel]]);
  assert.equal(registry.get("deye-ems-panel"),LegacyPanel);
  assert.equal(registry.get("deye-ems-panel-1-0-1"),LegacyPanel);
  assert.equal(registry.get("deye-ems-panel-1-0-5"),LegacyPanel);
  assert.equal(registry.get("deye-ems-panel-1-0-10"),LegacyPanel);
  assert.notEqual(registry.get("deye-ems-panel-2-0-3"),LegacyPanel);
  assert.match(panel.shadowRoot.innerHTML,/Wersja 2\.0\.3/);
});

function apiUsage(panel,changes={}){
  panel.payload.data.solcast={status:"ok",api_configured:true,api_enabled:true,
    quota:{limit:8,utc:{day:"2026-11-10",used:4}},...changes};
  return panel.solcastUsageHtml();
}

function updateInfo(panel,changes={}){
  panel.payload.updates={status:"not_checked",latest_version:null,checked_at:null,retry_at:null,stale:false,...changes};
  return panel.updatesHtml();
}

test("software version and manual update check are visible without opening advanced details or making requests",()=>{
  const {panel,calls,reloads}=fixture();
  const html=panel.shadowRoot.innerHTML.split("<details>")[0];
  assert.match(html,/<h2>Wersja i aktualizacje<\/h2>/);
  assert.match(html,/Uruchomiona w HA: <b>2\.0\.3<\/b>/);
  assert.match(html,/Interfejs tej karty: <b>2\.0\.3<\/b>/);
  assert.match(html,/Nie sprawdzono jeszcze dostępności/);
  assert.equal(panel.shadowRoot.getElementById("updates-check").disabled,false);
  assert.equal(calls.length,0);assert.equal(reloads(),0);
});

test("update states require validated versions and a completed check and use numeric version order",()=>{
  const {panel}=fixture();
  const checked_at=new Date(NOW).toISOString();
  let html=updateInfo(panel,{status:"current",latest_version:"2.0.3",checked_at});
  assert.match(html,/Ostatnie sprawdzenie: brak nowszego wydania/);
  html=updateInfo(panel,{status:"available",latest_version:"2.0.200",checked_at});
  assert.match(html,/Dostępna aktualizacja: 2\.0\.200/);
  html=updateInfo(panel,{status:"ahead",latest_version:"1.0.9",checked_at});
  assert.match(html,/nowsza niż ostatnie wydanie publiczne/);
  for(const changes of [{status:"current",latest_version:"2.0.4",checked_at},
    {status:"available",latest_version:"1.0.9",checked_at},
    {status:"current",latest_version:"2.0.3"},
    {status:"current",latest_version:"2.0.3",checked_at:"0"},
    {status:"current",latest_version:"2.0.3",checked_at:new Date(NOW+1).toISOString()},
    {status:"current",latest_version:"2.0.3",checked_at,stale:true}]){
    html=updateInfo(panel,changes);
    assert.doesNotMatch(html,/Ostatnie sprawdzenie: brak nowszego wydania|Dostępna aktualizacja:/);
  }
});

test("software version mismatch distinguishes an old tab from a backend awaiting restart without automatic reload",()=>{
  const {panel,reloads,calls}=fixture();
  panel.payload.backend_version="2.0.4";panel.render();
  assert.match(panel.updatesHtml(),/Otwarta karta ma starszy interfejs/);
  panel.payload.backend_version="1.0.16";panel.render();
  assert.match(panel.updatesHtml(),/Interfejs jest nowszy niż wersja uruchomiona w HA/);
  assert.match(panel.updatesHtml(),/wymagany jest restart HA/);
  for(const value of [undefined,null,17,"unknown","v2.0.3","2.0.3-beta","02.0.3"]){
    panel.payload.backend_version=value;panel.render();
    assert.match(panel.updatesHtml(),/Brak potwierdzonej wersji uruchomionej w HA/);
    assert.equal(panel.shadowRoot.getElementById("updates-check").disabled,true);
  }
  assert.equal(reloads(),0);assert.equal(calls.length,0);
});

test("update error keeps a stale last known release without claiming current or exposing provider text",()=>{
  const {panel}=fixture();
  const html=updateInfo(panel,{status:"error",reason:"rate_limited",latest_version:"2.0.4",
    checked_at:new Date(NOW).toISOString(),stale:true,error:"sensitive-provider-body",message:"unsafe-secret"});
  assert.match(html,/Osiągnięto limit sprawdzania wydań/);
  assert.match(html,/Ostatnio znane wydanie: 2\.0\.4/);
  assert.match(html,/Ta informacja może być nieaktualna/);
  assert.doesNotMatch(html,/Dostępna aktualizacja:|brak nowszego wydania|sensitive-provider-body|unsafe-secret/);
});

test("update navigation never accepts remote URLs or malformed release tags from the server",()=>{
  const {panel}=fixture();
  let html=updateInfo(panel,{status:"available",latest_version:"2.0.4",checked_at:new Date(NOW).toISOString(),
    release_url:"javascript:unexpected()",marketplace_url:"https://untrusted.example/install"});
  assert.match(html,/href="\/marketplace"/);
  assert.match(html,/href="https:\/\/github\.com\/gaszu\/deye-ems\/releases\/tag\/v2\.0\.4"/);
  assert.doesNotMatch(html,/javascript:|untrusted\.example|unexpected/);
  for(const latest_version of ['2.0.4\" onclick=\"unexpected()','<img src=x>','2.0.4/../../x',"v2.0.4",true,18,"2.0.4-beta","999999999.0.1"]){
    html=updateInfo(panel,{status:"available",latest_version,checked_at:new Date(NOW).toISOString()});
    assert.doesNotMatch(html,/github\.com|unexpected|<img|Dostępna aktualizacja:/);
  }
});

test("manual update check leaves stop control usable and merges only update data after concurrent mode changes",async()=>{
  const {panel,calls}=fixture();panel.payload.mode="active";panel.render();
  const old=structuredClone(panel.payload);let finish;
  panel._hass.callWS=message=>{calls.push(message);if(message.command==="check_updates")return new Promise(resolve=>{finish=resolve;});
    if(message.command==="mode")return Promise.resolve({...panel.payload,mode:message.mode,options:{...panel.payload.options,capacity_kwh:77}});
    throw Error("Unexpected request");};
  const checking=panel.checkUpdates();
  assert.equal(panel.busy,false);assert.equal(panel.updatesBusy,true);
  assert.equal(panel.shadowRoot.getElementById("mode").disabled,false);
  assert.match(panel.updatesHtml(),/Sprawdzanie dostępnych wydań/);
  assert.equal(await panel.checkUpdates(),false);
  await panel.shadowRoot.getElementById("mode").events.click();
  const afterStop=JSON.stringify({mode:panel.payload.mode,options:panel.payload.options,sources:panel.payload.sources,data:panel.payload.data});
  finish({...old,updates:{status:"available",latest_version:"2.0.4",checked_at:new Date(NOW).toISOString()}});
  assert.equal(await checking,true);
  assert.equal(panel.updatesBusy,false);assert.equal(panel.payload.updates.latest_version,"2.0.4");
  assert.equal(JSON.stringify({mode:panel.payload.mode,options:panel.payload.options,sources:panel.payload.sources,data:panel.payload.data}),afterStop);
  assert.equal(panel.payload.mode,"shadow");assert.equal(panel.payload.options.capacity_kwh,77);
  assert.deepEqual(JSON.parse(JSON.stringify(calls)),[{type:"deye_ems/command",command:"check_updates"},{type:"deye_ems/command",command:"mode",mode:"shadow"}]);
});

test("late update response cannot replace a newly observed backend version",async()=>{
  const {panel}=fixture();let finish;
  panel._hass.callWS=()=>new Promise(resolve=>{finish=resolve;});
  const checking=panel.checkUpdates();
  panel.payload={...panel.payload,backend_version:"2.0.4",updates:{status:"not_checked"}};
  finish({backend_version:"2.0.3",updates:{status:"current",latest_version:"2.0.3",checked_at:new Date(NOW).toISOString()}});
  assert.equal(await checking,false);assert.equal(panel.payload.backend_version,"2.0.4");
  assert.equal(panel.payload.updates.status,"not_checked");
  assert.match(panel.updatesHtml(),/Wersja HA mogła się zmienić/);
});

test("update cooldown and failed requests affect only the check button and use a safe error",async()=>{
  const {panel,calls}=fixture();
  updateInfo(panel,{retry_at:new Date(NOW+60000).toISOString()});panel.render();
  assert.equal(panel.shadowRoot.getElementById("updates-check").disabled,true);
  assert.equal(panel.shadowRoot.getElementById("mode").disabled,false);
  assert.match(panel.updatesHtml(),/Ponowne sprawdzenie za 60 s/);
  assert.equal(await panel.checkUpdates(),false);assert.equal(calls.length,0);
  updateInfo(panel);panel._hass.callWS=async()=>{throw Error("sensitive-network-details");};
  assert.equal(await panel.checkUpdates(),false);assert.equal(panel.busy,false);assert.equal(panel.updatesBusy,false);
  assert.match(panel.updatesHtml(),/Nie udało się sprawdzić aktualizacji/);
  assert.doesNotMatch(panel.shadowRoot.innerHTML,/sensitive-network-details/);
});

test("reload is explicit and respects unsaved forms while update polling preserves details and drafts",async()=>{
  const {panel,reloads,calls}=fixture();panel.render();
  const details=panel.shadowRoot.querySelector("details");details.open=true;
  panel.drafts.capacity_kwh="88";panel.render();
  assert.equal(panel.shadowRoot.getElementById("updates-reload").disabled,true);
  assert.equal(panel.reloadInterface(),false);assert.equal(reloads(),0);
  await panel.refresh();
  assert.equal(panel.drafts.capacity_kwh,"88");assert.equal(panel.shadowRoot.querySelector("details").open,true);
  delete panel.drafts.capacity_kwh;panel.render();
  assert.equal(reloads(),0);
  panel.shadowRoot.getElementById("updates-reload").events.click();
  assert.equal(reloads(),1);
  assert.deepEqual(JSON.parse(JSON.stringify(calls)),[{type:"deye_ems/status"}]);
});

test("an older polling response preserves a newer completed update check without losing new telemetry",async()=>{
  const {panel}=fixture();
  updateInfo(panel,{status:"available",latest_version:"2.0.4",checked_at:new Date(NOW).toISOString()});
  const old={...panel.payload,data:{...panel.payload.data,inputs:{...panel.payload.data.inputs,soc:63}},
    updates:{status:"not_checked",checked_at:null}};
  panel._hass.callWS=async()=>old;
  await panel.refresh();
  assert.equal(panel.payload.updates.latest_version,"2.0.4");assert.equal(panel.payload.data.inputs.soc,63);
  const newerError={...old,updates:{status:"error",latest_version:"2.0.4",stale:true,checked_at:new Date(NOW+1000).toISOString()}};
  panel._hass.callWS=async()=>newerError;await panel.refresh();
  assert.equal(panel.payload.updates.status,"error");
});

test("rendering or refreshing never automatically checks releases or reloads the page",async()=>{
  const {panel,calls,reloads}=fixture();
  panel.payload.backend_version="2.0.4";
  for(let i=0;i<3;i++){panel.render();await panel.refresh();}
  assert.equal(reloads(),0);assert.equal(calls.length,3);
  assert.ok(calls.every(call=>call.type==="deye_ems/status"));
  assert.doesNotMatch(panel.updatesHtml(),/<input|data-save=|Zainstaluj automatycznie/);
});

test("automatic Deye current ceiling is read-only and independent of the controlled setting",()=>{
  const {panel,calls}=fixture();
  Object.assign(panel.payload.data.inputs,{grid_charge_limit_valid:true,
    deye_max_charge_current_a:200,deye_grid_charge_limit_a:190,grid_port_power:4000});
  panel.payload.options.grid_current_max_a=108;
  panel.payload.options.inverter_max_power_kw=12;
  panel.render();
  const html=panel.shadowRoot.innerHTML;
  assert.match(html,/Automatyczny limit Deye −5%/);
  assert.match(html,/>190<small>A<\/small>/);
  assert.match(html,/ustawiony w Deye: 200 A/);
  assert.doesNotMatch(html,/data-key="grid_current_max_a"|data-save="grid_current_max_a"/);
  assert.match(html,/Moc portu GRID falownika: 4 kW/);
  assert.equal(calls.length,0);
});

const storeRow=(available_version="v2.0.3",changes={})=>({id:"1451991710",full_name:"gaszu/deye-ems",category:"integration",domain:"deye_ems",installed:true,available_version,...changes});
function storeFixture(){
  const result=fixture(),{panel}=result;
  panel.isConnected=true;panel._hass.user={is_admin:true};
  panel.payload.updates={status:"available",latest_version:"2.0.4",checked_at:new Date(NOW).toISOString(),stale:false};
  return result;
}
function successfulStore(panel,calls,{legacy=false,alreadyCurrent=false}={}){
  let refreshed=false;
  panel._hass.callWS=async message=>{calls.push(message);
    if(legacy&&message.type.startsWith("marketplace/"))throw {code:"unknown_command"};
    if(message.type.endsWith("/repositories/list"))return [storeRow(alreadyCurrent||refreshed?"v"+panel.payload.updates.latest_version:"v2.0.3")];
    if(message.type.endsWith("/repository/refresh")){refreshed=true;return {};}
    throw Error("Unexpected store request");};
}

test("open admin panel synchronizes only its older installed repository metadata once per confirmed release",async()=>{
  const {panel,calls,reloads}=storeFixture();successfulStore(panel,calls);
  assert.equal(await panel.syncStoreMetadata(),true);
  assert.deepEqual(JSON.parse(JSON.stringify(calls)),[
    {type:"marketplace/repositories/list",categories:["integration"]},
    {type:"marketplace/repository/refresh",repository:"1451991710"},
    {type:"marketplace/repositories/list",categories:["integration"]}]);
  for(let i=0;i<3;i++)assert.equal(await panel.syncStoreMetadata(),false);
  assert.equal(calls.length,3);assert.equal(reloads(),0);assert.equal(panel.busy,false);
  assert.match(panel.updatesHtml(),/Marketplace otrzymał aktualne metadane/);
  assert.ok(calls.every(message=>!JSON.stringify(message).match(/install|download|restart|version\"|mode/)));
  panel.payload.updates.latest_version="2.0.5";successfulStore(panel,calls);
  assert.equal(await panel.syncStoreMetadata(),true);assert.equal(calls.length,6);
});

test("store metadata work is single-flight and never occupies the EMS stop control",async()=>{
  const {panel,calls}=storeFixture();panel.payload.mode="active";panel.render();let finish;
  panel._hass.callWS=message=>{calls.push(message);return new Promise(resolve=>{finish=resolve;});};
  const first=panel.syncStoreMetadata(),second=panel.syncStoreMetadata();
  assert.equal(first,second);assert.equal(calls.length,1);assert.equal(panel.busy,false);
  assert.equal(panel.shadowRoot.getElementById("mode").disabled,false);
  finish([storeRow("v2.0.4")]);assert.equal(await first,true);assert.equal(calls.length,1);
});

test("already current marketplace metadata does not issue refresh and cannot downgrade a newer store release",async()=>{
  for(const version of ["2.0.4","v2.0.5"]){
    const {panel,calls}=storeFixture();panel._hass.callWS=async message=>{calls.push(message);return [storeRow(version)];};
    assert.equal(await panel.syncStoreMetadata(),true);assert.equal(calls.length,1);
  }
});

test("metadata sync requires an open admin panel and a fresh validated available release",async()=>{
  const bad=[{status:"error"},{status:"current"},{stale:true},{latest_version:"v2.0.4"},{latest_version:"2.0.3"},
    {latest_version:"<img src=x>"},{checked_at:new Date(NOW+1).toISOString()},
    {checked_at:new Date(NOW-7200001).toISOString()},{checked_at:null}];
  for(const changes of bad){const {panel,calls}=storeFixture();Object.assign(panel.payload.updates,changes);assert.equal(await panel.syncStoreMetadata(),false);assert.equal(calls.length,0);}
  for(const condition of ["closed","non_admin","unknown_user"]){
    const {panel,calls}=storeFixture();if(condition==="closed")panel.isConnected=false;else panel._hass.user=condition==="non_admin"?{is_admin:false}:undefined;
    assert.equal(await panel.syncStoreMetadata(),false);assert.equal(calls.length,0);
  }
});

test("wrong ambiguous uninstalled or malformed repository metadata never permits a refresh",async()=>{
  const rows=[[],{},[storeRow("2.0.3",{id:"different"})],[storeRow("2.0.3",{full_name:"other/repo"})],
    [storeRow("2.0.3",{domain:"other"})],[storeRow("2.0.3",{category:"plugin"})],
    [storeRow("2.0.3",{installed:false})],[storeRow("malformed")],[storeRow(),storeRow()]];
  for(const response of rows){const {panel,calls}=storeFixture();panel._hass.callWS=async message=>{calls.push(message);return response;};
    assert.equal(await panel.syncStoreMetadata(),false);assert.equal(calls.length,1);await panel.syncStoreMetadata();assert.equal(calls.length,1);}
});

test("legacy HACS fallback is allowed only for unknown_command and uses the same exact repository identity",async()=>{
  const {panel,calls}=storeFixture();successfulStore(panel,calls,{legacy:true});
  assert.equal(await panel.syncStoreMetadata(),true);
  assert.deepEqual(calls.map(message=>message.type),["marketplace/repositories/list","hacs/repositories/list","hacs/repository/refresh","hacs/repositories/list"]);
  assert.equal(calls[2].repository,"1451991710");
  for(const code of ["forbidden","unauthorized","not_loaded","repository_not_found","github_rate_limited"]){
    const {panel,calls}=storeFixture();panel._hass.callWS=async message=>{calls.push(message);throw {code,message:"unsafe-provider-secret"};};
    assert.equal(await panel.syncStoreMetadata(),false);assert.equal(calls.length,1);
    assert.doesNotMatch(panel.updatesHtml(),/unsafe-provider-secret/);assert.equal(panel.updatesError,"");
    if(["forbidden","unauthorized"].includes(code)){await panel.syncStoreMetadata();assert.equal(calls.length,1);}
  }
});

test("an unknown refresh endpoint rediscovers the same repository through legacy HACS before refreshing",async()=>{
  const {panel,calls}=storeFixture();let done=false;
  panel._hass.callWS=async message=>{calls.push(message);if(message.type==="marketplace/repository/refresh")throw {code:"unknown_command"};
    if(message.type.endsWith("/repositories/list"))return [storeRow(done?"v2.0.4":"v2.0.3")];done=true;return {};};
  assert.equal(await panel.syncStoreMetadata(),true);
  assert.deepEqual(calls.map(message=>message.type),["marketplace/repositories/list","marketplace/repository/refresh","hacs/repositories/list","hacs/repository/refresh","hacs/repositories/list"]);
});

test("transient metadata errors have bounded cooldowns while rate limits wait at least an hour",async()=>{
  const {panel,calls,advance,timers}=storeFixture();panel._hass.callWS=async message=>{calls.push(message);throw {code:"network",message:"secret"};};
  await panel.syncStoreMetadata();assert.equal(calls.length,1);assert.ok(timers.some(timer=>timer.ms===300000&&!timer.cleared));
  await panel.syncStoreMetadata();assert.equal(calls.length,1);advance(300000);await panel.syncStoreMetadata();assert.equal(calls.length,2);
  advance(900000);await panel.syncStoreMetadata();assert.equal(calls.length,3);advance(900000);await panel.syncStoreMetadata();assert.equal(calls.length,3);
  assert.doesNotMatch(panel.updatesHtml(),/secret/);
  const limited=storeFixture();limited.panel._hass.callWS=async message=>{limited.calls.push(message);throw {code:"github_rate_limited"};};
  await limited.panel.syncStoreMetadata();assert.ok(limited.timers.some(timer=>timer.ms===3600000&&!timer.cleared));
  limited.advance(3599999);await limited.panel.syncStoreMetadata();assert.equal(limited.calls.length,1);
});

test("metadata responses after unmount cancellation or release changes never trigger another request",async()=>{
  for(const reason of ["disconnect","changed_release","stale"]){
    const {panel,calls}=storeFixture();let finish;
    panel._hass.callWS=message=>{calls.push(message);return new Promise(resolve=>{finish=resolve;});};
    const pending=panel.syncStoreMetadata();
    if(reason==="disconnect"){panel.isConnected=false;panel.disconnectedCallback();}
    else if(reason==="changed_release")panel.payload.updates.latest_version="2.0.5";else panel.payload.updates.stale=true;
    finish([storeRow()]);assert.equal(await pending,false);assert.equal(calls.length,1);
  }
});

test("metadata request timeout is bounded and its cancellation leaves update and EMS controls available",async()=>{
  const {panel,calls,timers}=storeFixture();panel._hass.callWS=message=>{calls.push(message);return new Promise(()=>{});};
  const pending=panel.syncStoreMetadata(),timeout=timers.find(timer=>timer.ms===30000&&!timer.cleared);
  assert.ok(timeout);timeout.fn();assert.equal(await pending,false);assert.equal(calls.length,1);
  assert.equal(panel.busy,false);assert.equal(panel.updatesBusy,false);
});

test("successful metadata fetch does not claim the store offers an unconfirmed newer version",async()=>{
  const {panel,calls}=storeFixture();panel._hass.callWS=async message=>{calls.push(message);return message.type.endsWith("/repositories/list")?[storeRow()]:{};};
  assert.equal(await panel.syncStoreMetadata(),false);assert.equal(calls.length,3);
  assert.doesNotMatch(panel.updatesHtml(),/Marketplace otrzymał aktualne metadane/);
  assert.match(panel.updatesHtml(),/Sprawdź dostępne wersje i zgodność/);
});

test("normal status polling can trigger metadata synchronization without a separate release check command",async()=>{
  const {panel,calls}=storeFixture();let done=false;
  panel._hass.callWS=async message=>{calls.push(message);if(message.type==="deye_ems/status")return panel.payload;
    if(message.type.endsWith("/repositories/list"))return [storeRow(done?"v2.0.4":"v2.0.3")];done=true;return {};};
  await panel.refresh();await panel.storeSyncFlight;
  assert.equal(calls.filter(message=>message.type==="marketplace/repository/refresh").length,1);
  assert.ok(calls.every(message=>message.command!=="check_updates"));
});

test("automatic release schedule displays only validated manager fields",()=>{
  const {panel}=fixture();let html=updateInfo(panel,{automatic:true,interval_seconds:3600,next_check_at:new Date(NOW+3600000).toISOString()});
  assert.match(html,/Automatyczne sprawdzanie wydań co godzinę/);assert.match(html,/następne:/);
  html=updateInfo(panel,{automatic:true,interval_seconds:3600,next_check_at:"unsafe-provider-text"});assert.doesNotMatch(html,/unsafe-provider-text|następne:/);
  html=updateInfo(panel,{automatic:"true",interval_seconds:3600});assert.doesNotMatch(html,/Automatyczne sprawdzanie/);
});

test("battery authority labels distinguish raw Deye setting from grid minus-five-percent and real BMS limits",()=>{
  const {panel,calls}=fixture();Object.assign(panel.payload.data.inputs,{battery_limit_source:"deye_setting",bms_valid:true,bms_cap_a:200,
    grid_charge_limit_valid:true,deye_max_charge_current_a:200,deye_grid_charge_limit_a:190});panel.render();
  assert.match(panel.shadowRoot.innerHTML,/Limit z nastawy Deye/);assert.match(panel.shadowRoot.innerHTML,/>200<small>A/);
  assert.match(panel.shadowRoot.innerHTML,/Automatyczny limit Deye −5%/);assert.match(panel.shadowRoot.innerHTML,/>190<small>A/);
  assert.doesNotMatch(panel.shadowRoot.innerHTML,/<span class="label">Limit BMS/);
  assert.match(panel.shadowRoot.innerHTML,/Brak osobnej encji CCL BMS/);
  for(const [source,label] of [["deye_bms","Limit BMS z Deye"],["external_bms","Limit z zewnętrznego BMS"]]){
    panel.payload.data.inputs.battery_limit_source=source;panel.render();assert.ok(panel.shadowRoot.innerHTML.includes(label));
  }
  panel.payload.data.inputs.battery_limit_source="<img src=x>";panel.render();assert.match(panel.shadowRoot.innerHTML,/Limit baterii/);
  assert.doesNotMatch(panel.shadowRoot.innerHTML,/<img src=x>/);assert.equal(calls.length,0);
});

test("retired model charging power is not editable or rendered from persisted legacy options",()=>{
  const {panel,calls}=fixture();
  const inputKeys=()=>panel.shadowRoot.querySelectorAll("input[data-key]").map(input=>input.dataset.key);
  for(const value of [5.3,0.1,999,"malformed"]){
    panel.payload.options.charge_max_kw=value;panel.render();
    assert.equal(inputKeys().includes("charge_max_kw"),false);
    assert.equal(inputKeys().includes("discharge_max_kw"),true);
    assert.doesNotMatch(panel.shadowRoot.innerHTML,/Modelowy limit ładowania|data-key="charge_max_kw"/);
    assert.match(panel.shadowRoot.innerHTML,/Prognoza SoC wyznacza moc ładowania z aktualnych limitów Deye i BMS oraz napięcia baterii/);
    assert.match(panel.shadowRoot.innerHTML,/PV i sieci korzysta ze wspólnego budżetu baterii/);
  }
  assert.doesNotMatch(source,/\bcharge_max_kw\b/);
  assert.equal(calls.length,0);
});

test("PV priority diagnostics show validated battery-side powers without controls or extra requests",()=>{
  const {panel,calls}=fixture();
  Object.assign(panel.payload.data.control,{pv_surplus_credit_w:2300,net_grid_need_w:1700});
  panel.render();
  const html=panel.pvPriorityHtml();
  assert.match(html,/szacunek zachowawczy:<\/b> 2,3 kW/);
  assert.match(html,/potrzeba doładowania z sieci:<\/b> 1,7 kW/);
  assert.match(html,/mocy po stronie baterii/);
  assert.match(html,/nie jest osobnym pomiarem energii PV/);
  assert.match(html,/przed ograniczeniami sprzętowymi/);
  const visible=panel.shadowRoot.innerHTML.split("<details>")[0];
  assert.match(visible,/aria-label="Priorytet PV"/);
  assert.doesNotMatch(html,/<input|<button/);
  assert.equal(calls.length,0);
});

test("PV priority preserves genuine zero and never renders malformed diagnostics as measured zero",()=>{
  const {panel}=fixture();
  Object.assign(panel.payload.data.control,{pv_surplus_credit_w:0,net_grid_need_w:0});
  assert.equal((panel.pvPriorityHtml().match(/<\/b> 0 kW/g)||[]).length,2);
  for(const value of [undefined,null,true,false,"2300","",-1,NaN,Infinity]){
    Object.assign(panel.payload.data.control,{pv_surplus_credit_w:value,net_grid_need_w:value});
    const html=panel.pvPriorityHtml();
    assert.equal((html.match(/<\/b> — kW/g)||[]).length,2,String(value));
    assert.doesNotMatch(html,/<\/b> 0 kW/);
  }
});

test("PV priority hides stale future and telemetry-invalid powers",()=>{
  const {panel}=fixture();
  Object.assign(panel.payload.data.control,{pv_surplus_credit_w:2300,net_grid_need_w:1700});
  for(const updated of [new Date(NOW-30001).toISOString(),new Date(NOW+1).toISOString(),null,"malformed"]){
    panel.payload.data.updated_at=updated;
    assert.equal((panel.pvPriorityHtml().match(/<\/b> — kW/g)||[]).length,2);
  }
  panel.payload.data.updated_at=new Date(NOW).toISOString();
  panel.payload.data.inputs.telemetry_valid=false;
  assert.equal((panel.pvPriorityHtml().match(/<\/b> — kW/g)||[]).length,2);
  panel.payload.data.inputs.telemetry_valid=true;
  assert.match(panel.pvPriorityHtml(),/<\/b> 2,3 kW/);
});

test("PV priority uses runtime attribution without substituting CT raw PV or a register-derived power",()=>{
  const {panel}=fixture();
  Object.assign(panel.payload.data.control,{pv_surplus_credit_w:2300,net_grid_need_w:1700});
  const initial=panel.pvPriorityHtml();
  panel.payload.options.topology="load_with_external_ct";
  Object.assign(panel.payload.data.inputs,{grid_power:25000,grid_port_power:12000,battery_power:-9000,current_a:190,pv_power:20000});
  panel._hass.states["sensor.raw_pv"]={state:"20000",attributes:{unit_of_measurement:"W"}};
  assert.equal(panel.pvPriorityHtml(),initial);
  delete panel.payload.data.control.pv_surplus_credit_w;
  delete panel.payload.data.control.net_grid_need_w;
  assert.equal((panel.pvPriorityHtml().match(/<\/b> — kW/g)||[]).length,2);
});

test("PV-covered charge need is distinct from a reached SoC target",()=>{
  const {panel}=fixture();
  panel.payload.mode="active";
  panel.payload.data.control.reason="pv_covers_charge_need";panel.render();
  assert.match(panel.shadowRoot.innerHTML,/PV pokrywa potrzebę ładowania/);
  assert.doesNotMatch(panel.shadowRoot.innerHTML,/Cel SoC osiągnięty|Cel osiągnięty — wznowienie/);
});

function currentStatus(panel,changes={}){
  panel.payload.mode="active";
  Object.assign(panel.payload.data.control,{reason:"scheduled_hold",grid_charge_enabled:false,
    read_setting_a:0,current_hold_reason:"scheduled_regular",next_current_change_at:"2026-11-10T22:30:00+01:00",...changes});
  return panel.currentStatusText(panel.payload.data.control.reason);
}

test("zero current with a positive requested current says disabled and shows the server deadline",()=>{
  const {panel}=fixture();
  const text=currentStatus(panel,{next_a:20});
  assert.match(text,/Doładowanie baterii z sieci jest wyłączone/);
  assert.match(text,/Następna zmiana prądu najwcześniej o 22:30/);
  assert.doesNotMatch(text,/utrzymywana|:00 lub :30|włączone/);
  panel.render();assert.match(panel.shadowRoot.innerHTML,/Doładowanie baterii z sieci jest wyłączone/);
});

test("grid charge switch and register are distinct and never assert physical energy flow",()=>{
  const {panel}=fixture();
  let text=currentStatus(panel,{grid_charge_enabled:true,read_setting_a:27});
  assert.match(text,/jest włączone\. Limit 27 A/);
  text=currentStatus(panel,{grid_charge_enabled:false,read_setting_a:27});
  assert.match(text,/Limit 27 A zapisany, doładowanie baterii z sieci jest wyłączone/);
  for(const flag of [null,undefined,"true",1]){
    panel.payload.data.inputs.battery_power=-9000;panel.payload.data.inputs.grid_power=12000;
    text=currentStatus(panel,{grid_charge_enabled:flag,read_setting_a:27});
    assert.match(text,/Brak potwierdzenia włączenia/);
    assert.doesNotMatch(text,/jest włączone|jest wyłączone|pobiera|ładuje z mocą/);
  }
});

test("stale invalid or future telemetry suppresses charging and schedule claims",()=>{
  const {panel}=fixture();
  currentStatus(panel,{grid_charge_enabled:true,read_setting_a:27});
  for(const at of [NOW-30001,NOW+1]){
    panel.payload.data.updated_at=new Date(at).toISOString();
    const text=panel.currentStatusText("scheduled_hold");
    assert.match(text,/Brak aktualnego stanu sterowania/);
    assert.doesNotMatch(text,/włączone|27 A|22:30/);
  }
  panel.payload.data.updated_at=new Date(NOW).toISOString();panel.payload.data.inputs.telemetry_valid=false;
  assert.match(panel.currentStatusText("scheduled_hold"),/Brak poprawnych, świeżych pomiarów/);
  panel.payload.data.inputs.telemetry_valid=true;panel.payload.data.control.current_hold_reason="telemetry_invalid";
  assert.match(panel.currentStatusText("scheduled_hold"),/Brak poprawnych, świeżych pomiarów/);
});

test("recovery shows only a known remaining interval and does not advertise a regular slot",()=>{
  const {panel}=fixture();
  let text=currentStatus(panel,{current_hold_reason:"waiting_stable_measurements",recovery_remaining_s:43.2});
  assert.match(text,/stabilne pomiary — pozostało co najmniej 44 s/);
  assert.doesNotMatch(text,/22:30|Następna zmiana/);
  for(const value of [null,undefined,0,-1,121,"40",NaN]){
    text=currentStatus(panel,{current_hold_reason:"waiting_stable_measurements",recovery_remaining_s:value});
    assert.match(text,/Oczekiwanie na stabilne pomiary\./);assert.doesNotMatch(text,/pozostało|22:30/);
  }
});

test("missing malformed past and unreasonable deadlines never invent the next half hour",()=>{
  const {panel}=fixture();
  for(const at of [null,undefined,"22:30","garbage",new Date(NOW-1).toISOString(),new Date(NOW).toISOString(),new Date(NOW+49*3600000).toISOString()]){
    const text=currentStatus(panel,{next_current_change_at:at});
    assert.match(text,/Termin kolejnej zmiany prądu nie jest jeszcze potwierdzony/);
    assert.doesNotMatch(text,/najwcześniej|:00 lub :30|22:30/);
  }
});

test("server deadlines use Warsaw time and identify a different local day",()=>{
  const {panel}=fixture();
  assert.match(currentStatus(panel,{next_current_change_at:"2026-11-11T00:30:00+01:00"}),/dnia 11\.11\.2026 o 00:30/);
  const summer=Date.parse("2026-06-01T20:00:00Z"),{panel:summerPanel}=fixture([],summer);
  summerPanel.payload.data.updated_at=new Date(summer).toISOString();
  assert.match(currentStatus(summerPanel,{next_current_change_at:"2026-06-01T20:30:00Z"}),/najwcześniej o 22:30/);
});

test("observation does not describe active charging even with a positive setting and battery charge",()=>{
  const {panel}=fixture();currentStatus(panel,{grid_charge_enabled:true,read_setting_a:27});
  panel.payload.mode="shadow";
  const text=panel.currentStatusText("scheduled_hold");
  assert.match(text,/Tryb obserwacji — EMS nie steruje ładowaniem/);
  assert.doesNotMatch(text,/włączone|27 A|22:30/);
});

test("BMS hardware and ownership reasons keep priority over an ordinary scheduled wait",()=>{
  const {panel}=fixture();currentStatus(panel);
  panel.payload.data.inputs.telemetry_valid=false;
  for(const [reason,label] of [["bms_blocked","Blokada ładowania baterii"],["hardware_mode_mismatch","Tryby falownika wymagają sprawdzenia"],["ownership_conflict","Konflikt sterowników"]]){
    assert.equal(panel.currentStatusText("safety_"+reason),label);
    panel.payload.data.control.runtime_reason=reason;panel.render();
    assert.match(panel.shadowRoot.innerHTML,new RegExp(label));
  }
});

test("invalid telemetry labels accept controlled source reasons and never echo arbitrary provider data",()=>{
  const {panel}=fixture();currentStatus(panel);panel.payload.data.inputs.telemetry_valid=false;
  panel.payload.data.inputs.telemetry_issues=[{source:"battery_power",reason:"stale"},{source:"battery_power",reason:"stale"},{source:"charge_power",reason:"time_skew"},{source:"private_entity",reason:"stale"},{source:"grid_power",reason:"private_token"}];
  const text=panel.currentStatusText("scheduled_hold");
  assert.match(text,/moc baterii: za stary odczyt/);assert.match(text,/zgodność czasowa mocy: odczyty z różnych chwil/);
  assert.equal((text.match(/moc baterii/g)||[]).length,1);
  assert.doesNotMatch(text,/private_entity|private_token|22:30|włączone/);
});

test("first start is preparation and unknown diagnostic values are not rendered",()=>{
  const {panel}=fixture();
  let text=currentStatus(panel,{reason:"initial_charge_start",current_hold_reason:"initial_start",next_current_change_at:null});
  assert.match(text,/Przygotowanie pierwszego startu w tanim oknie/);assert.doesNotMatch(text,/jest włączone/);
  text=currentStatus(panel,{current_hold_reason:"private_internal_value",next_current_change_at:null});
  assert.doesNotMatch(text,/private_internal_value/);
});

function telemetryRow(changes={}){
  return {source:"voltage",entity_id:"sensor.site_battery_voltage",value:53.7,unit:"V",expected_unit:"V",
    last_reported:new Date(NOW-175000).toISOString(),age_seconds:175,max_age_seconds:120,
    valid:false,reason:"stale",platform:"esphome",...changes};
}
function telemetryData(panel,rows=[telemetryRow()],hints=[]){
  panel.payload.data.inputs.telemetry_details=rows;panel.payload.data.inputs.telemetry_hints=hints;
  panel.payload.data.inputs.telemetry_valid=rows.every(row=>row.valid===true);panel.render();return panel.telemetryDiagnosticsHtml();
}
test("measurement diagnostics identify the stale 175 second voltage and unchanged 120 second limit",()=>{
  const {panel,calls}=fixture();const html=telemetryData(panel);
  assert.match(html,/Diagnostyka pomiarów/);assert.match(html,/sensor\.site_battery_voltage/);assert.match(html,/Napięcie baterii/);
  assert.match(html,/53,7 V/);assert.match(html,/>175 s<\/td>/);assert.match(html,/>120 s<\/td>/);
  assert.match(html,/Odczyt starszy niż dopuszczalny limit/);assert.match(html,/Wiek dotyczy ostatniego sprawdzenia silnika/);
  assert.ok(panel.shadowRoot.innerHTML.indexOf("Diagnostyka pomiarów")<panel.shadowRoot.innerHTML.indexOf("Harmonogram taryfy"));
  assert.equal(calls.length,0);
});
test("wrong units and absent report time remain distinct without inventing zero age or a threshold",()=>{
  const {panel}=fixture();let html=telemetryData(panel,[telemetryRow({reason:"wrong_unit",unit:"mV",expected_unit:"V",value:53700})]);
  assert.match(html,/53[\s\u00a0]700 mV/);assert.match(html,/Błędna jednostka — oczekiwano V/);
  html=telemetryData(panel,[telemetryRow({last_reported:null,age_seconds:null,max_age_seconds:null,value:null,reason:"missing"})]);
  assert.match(html,/brak czasu odczytu/);assert.match(html,/bez stałego limitu/);assert.match(html,/Brak odczytu/);
  assert.doesNotMatch(html,/>0 s<\/td>/);assert.doesNotMatch(html,/>0 V<\/td>/);
});
test("group time coherence diagnostics show observed and allowed skew without changing guards",()=>{
  const {panel}=fixture();const html=telemetryData(panel,[telemetryRow({source:"charge_power",entity_id:null,value:null,unit:null,
    reason:"time_skew",last_reported:null,age_seconds:null,max_age_seconds:null,platform:null,
    observed_time_skew_seconds:17.5,max_time_skew_seconds:10})]);
  assert.match(html,/Odczyty pochodzą z różnych chwil — różnica 17,5 s, limit 10 s/);
  assert.match(html,/brak przypisanej encji/);
});
test("ESPHome read-only hints require an actual ESPHome source and never recommend modifying firmware",()=>{
  const {panel}=fixture(),hint={provider:"esphome",reason:"stale",sources:["voltage"],message:"private-provider-message"};
  let html=telemetryData(panel,[telemetryRow()],[hint]);assert.match(html,/Raporty ESPHome/);assert.match(html,/połączenie tylko do odczytu/);
  assert.match(html,/zmiana firmware nie jest wymagana/);assert.doesNotMatch(html,/force_update|update_interval/);
  assert.doesNotMatch(html,/private-provider-message/);
  html=telemetryData(panel,[telemetryRow({platform:"mqtt"})],[hint]);assert.doesNotMatch(html,/force_update|update_interval/);
  html=telemetryData(panel,[telemetryRow({platform:"mqtt"})],[{provider:"generic",reason:"stale",sources:["voltage"],message:"private-provider-message"}]);
  assert.match(html,/częstotliwość raportowania w integracji źródłowej/);assert.doesNotMatch(html,/force_update|ESPHome|private-provider-message/);
  html=telemetryData(panel,[telemetryRow({valid:true,reason:null,age_seconds:1}),telemetryRow({source:"grid_power",platform:"mqtt"})],[hint]);
  assert.doesNotMatch(html,/force_update|update_interval/);
});
test("stale future and missing whole snapshots never present cached telemetry ages values or repair hints as current",()=>{
  const {panel}=fixture();telemetryData(panel,[telemetryRow()],[{provider:"esphome",reason:"stale",sources:["voltage"]}]);
  for(const stamp of [new Date(NOW-30001).toISOString(),new Date(NOW+1).toISOString(),"unknown",null]){
    panel.payload.data.updated_at=stamp;const html=panel.telemetryDiagnosticsHtml();
    assert.match(html,/Brak bieżącej diagnostyki/);assert.doesNotMatch(html,/175 s|53,7|sensor\.site_battery_voltage|force_update/);
  }
});
test("diagnostic healthy rows expand locally and preserve expansion and focused drafts during polling",async()=>{
  const {panel,calls}=fixture();telemetryData(panel,[telemetryRow(),telemetryRow({source:"grid_power",entity_id:"sensor.site_grid_power",value:0,unit:"W",reason:null,valid:true,age_seconds:4,max_age_seconds:30})]);
  assert.doesNotMatch(panel.telemetryDiagnosticsHtml(),/sensor\.site_grid_power/);
  panel.shadowRoot.getElementById("telemetry-diagnostics-toggle").events.click();
  assert.equal(panel.telemetryExpanded,true);assert.match(panel.telemetryDiagnosticsHtml(),/sensor\.site_grid_power/);
  assert.match(panel.telemetryDiagnosticsHtml(),/>0 W<\/td>/);assert.equal(calls.length,0);
  const field=panel.shadowRoot.querySelector('input[data-key="capacity_kwh"]');field.value="88";field.events.input();panel.shadowRoot.activeElement=field;
  const html=panel.shadowRoot.innerHTML;await panel.refresh();assert.equal(panel.shadowRoot.innerHTML,html);assert.equal(panel.telemetryExpanded,true);assert.equal(panel.drafts.capacity_kwh,"88");
  panel.shadowRoot.activeElement=null;panel.render();assert.equal(panel.shadowRoot.querySelector('input[data-key="capacity_kwh"]').value,"88");
  panel.shadowRoot.getElementById("telemetry-diagnostics-toggle").events.click();assert.equal(panel.telemetryExpanded,false);
  assert.doesNotMatch(panel.telemetryDiagnosticsHtml(),/sensor\.site_grid_power/);assert.match(panel.telemetryDiagnosticsHtml(),/sensor\.site_battery_voltage/);
  assert.equal(panel.shadowRoot.nodes.filter(node=>node.attrs.tag==="details").length,1);
});
test("new failed diagnostics become visible despite a focused settings field and no automatic control requests",async()=>{
  const {panel,calls}=fixture();telemetryData(panel,[telemetryRow({valid:true,reason:null,age_seconds:4})]);
  panel.shadowRoot.activeElement=panel.shadowRoot.querySelector('input[data-key="capacity_kwh"]');
  panel._hass.callWS=async()=>({...panel.payload,data:{...panel.payload.data,inputs:{...panel.payload.data.inputs,telemetry_valid:false,telemetry_details:[telemetryRow()]}}});
  await panel.refresh();assert.match(panel.shadowRoot.innerHTML,/175 s/);assert.match(panel.shadowRoot.innerHTML,/Odczyt starszy niż dopuszczalny limit/);
  assert.equal(calls.length,0);
});
test("diagnostics escape identifiers units platforms and reason metadata but never print raw invalid sensor strings",()=>{
  const {panel}=fixture();const html=telemetryData(panel,[telemetryRow({source:'<img src=x>',entity_id:'sensor.bad" onclick="x',value:'<script>secret-value</script>',unit:'<svg onload=x>',
    platform:'<img src=x>',reason:"wrong_unit",expected_unit:'V<script>x</script>'})]);
  assert.match(html,/&lt;img/);assert.match(html,/sensor\.bad&quot;/);assert.match(html,/&lt;svg/);assert.match(html,/V&lt;script/);
  assert.doesNotMatch(html,/<img|<svg|<script|secret-value/);
});
test("healthy diagnostic lists stay collapsed by default and unknown detail formats do not trigger requests",()=>{
  const {panel,calls}=fixture();let html=telemetryData(panel,[telemetryRow({valid:true,reason:null,age_seconds:3})]);
  assert.match(html,/Wszystkie pokazane źródła/);assert.doesNotMatch(html,/sensor\.site_battery_voltage/);assert.equal(panel.telemetryExpanded,false);
  for(const details of [null,"unexpected",{},[null,1,"wrong",{}]]){
    panel.payload.data.inputs.telemetry_details=details;html=panel.telemetryDiagnosticsHtml();assert.match(html,/Brak szczegółów pomiarów/);
  }
  assert.equal(calls.length,0);
});
test("healthy individual rows cannot override an unconfirmed overall telemetry result",()=>{
  const {panel}=fixture();telemetryData(panel,[telemetryRow({valid:true,reason:null,age_seconds:1})]);panel.payload.data.inputs.telemetry_valid=false;
  const html=panel.telemetryDiagnosticsHtml();assert.match(html,/silnik nie potwierdza kompletu pomiarów/);assert.doesNotMatch(html,/Wszystkie pokazane źródła spełniają/);
});

function nativeTelemetryRow(changes={}){
  return telemetryRow({valid:true,reason:null,timestamp_source:"esphome_live",stream_samples:2,
    last_reported:new Date(NOW-5000).toISOString(),age_seconds:5,
    ha_last_reported:new Date(NOW-175000).toISOString(),ha_age_seconds:175,...changes});
}
function reportStreamData(panel,changes={}){
  panel.payload.data.inputs.report_stream={status:"ready",providers:1,connected_providers:1,bindings:3,verified_sources:1,...changes};
  panel.render();return panel.reportStreamHtml();
}
test("confirmed ESPHome reports distinguish EMS reception age from an older unchanged HA state",()=>{
  const {panel,calls}=fixture();panel.telemetryExpanded=true;const statesBefore=JSON.stringify(panel._hass.states);
  reportStreamData(panel);const html=telemetryData(panel,[nativeTelemetryRow()]);
  assert.match(html,/Raport odebrany przez EMS/);assert.match(html,/Wiek znacznika HA: 175 s/);
  assert.match(html,/>5 s<br>/);assert.match(html,/53,7 V/);assert.match(html,/Prawidłowy/);
  assert.match(html,/nie czas odczytu Modbus/);assert.match(html,/dodatkowego połączenia tylko do odczytu/);
  assert.match(html,/Nie wymaga zmian firmware ani nie zapisuje stanów encji/);
  assert.match(html,/Pierwszy stan po połączeniu może pochodzić z pamięci urządzenia/);
  assert.equal(calls.length,0);assert.equal(JSON.stringify(panel._hass.states),statesBefore);
});
test("one ESPHome packet cannot be presented as a verified native source even if the payload claims valid",()=>{
  const {panel}=fixture();reportStreamData(panel,{status:"warming_up",verified_sources:0});
  const html=telemetryData(panel,[nativeTelemetryRow({stream_samples:1})]);
  assert.match(html,/Oczekiwanie na kolejne zgodne raporty/);assert.match(html,/oczekiwanie na dwa zgodne raporty ESPHome/);
  assert.match(html,/Znacznik HA/);assert.match(html,/>175 s<\/td>/);
  assert.doesNotMatch(html,/Raport odebrany przez EMS|>5 s|Prawidłowy|Wszystkie pokazane źródła spełniają/);
});
test("malformed ESPHome proof fields and another source platform never acquire a native timestamp",()=>{
  const {panel}=fixture();reportStreamData(panel);
  for(const change of [{stream_samples:null},{stream_samples:"2"},{stream_samples:1.5},{last_reported:"unknown"},{last_reported:new Date(NOW+1).toISOString()},{age_seconds:NaN},{age_seconds:-1},{platform:"mqtt"}]){
    const html=telemetryData(panel,[nativeTelemetryRow(change)]);
    assert.doesNotMatch(html,/Raport odebrany przez EMS|Prawidłowy/);assert.match(html,/Znacznik HA/);
  }
});
test("an unknown timestamp origin cannot be labelled as a valid HA or ESPHome reception proof",()=>{
  const {panel}=fixture();const html=telemetryData(panel,[nativeTelemetryRow({timestamp_source:'<img src=x onerror="x">'})]);
  assert.match(html,/źródło znacznika czasu niepotwierdzone/);assert.match(html,/>175 s<\/td>/);
  assert.doesNotMatch(html,/Raport odebrany przez EMS|Prawidłowy|<img|onerror/);
});
test("original HA timestamps remain the fallback and no ESPHome proof is guessed for MQTT",()=>{
  const {panel}=fixture();reportStreamData(panel,{status:"not_applicable",providers:0,connected_providers:0,bindings:0,verified_sources:0});
  const html=telemetryData(panel,[telemetryRow({platform:"mqtt",timestamp_source:"home_assistant",stream_samples:0})],[{provider:"generic",reason:"stale",sources:["voltage"]}]);
  assert.match(html,/nie jest używany dodatkowy odbiór ESPHome; obowiązują znaczniki HA/);
  assert.match(html,/Odczyt starszy niż dopuszczalny limit/);assert.match(html,/Znacznik HA/);assert.match(html,/>175 s<\/td>/);
  assert.match(html,/częstotliwość raportowania w integracji źródłowej/);assert.doesNotMatch(html,/Raport odebrany przez EMS|force_update|Źródło ESPHome:/);
});
test("report connection states and zero counts are explicit without exposing provider connection data",()=>{
  const {panel,calls}=fixture();
  for(const [status,label] of [["connecting",/Łączenie ze źródłem ESPHome/],["warming_up",/Oczekiwanie na kolejne zgodne raporty/],["unavailable",/niedostępny; obowiązują pierwotne kontrole/],["ready",/Odbiór raportów działa/]]){
    const html=reportStreamData(panel,{status,host:"private-host.example",password:"do-not-print",noise_psk:"private-key",message:"private-provider-text"});
    assert.match(html,label);assert.doesNotMatch(html,/private-host|do-not-print|private-key|private-provider-text/);
    assert.match(html,/Odbiór raportów sam nie włącza sterowania/);
  }
  const zero=reportStreamData(panel,{status:"warming_up",providers:0,connected_providers:0,bindings:0,verified_sources:0});
  assert.match(zero,/Połączenia: 0 \/ 0/);assert.match(zero,/przypisane źródła: 0/);assert.equal(calls.length,0);
});
test("invalid report counters and statuses never appear as ready or leak raw provider text",()=>{
  const {panel}=fixture();
  for(const field of ["providers","connected_providers","bindings","verified_sources"]){
    for(const value of [-1,NaN,Infinity,1.5,"1",null,1000001]){
      const html=reportStreamData(panel,{[field]:value});assert.doesNotMatch(html,/Odbiór raportów działa/);assert.match(html,/—/);
    }
  }
  const html=reportStreamData(panel,{status:'<img src=x onerror="x">'});assert.match(html,/Brak potwierdzonego statusu/);assert.doesNotMatch(html,/<img|onerror/);
  assert.doesNotMatch(reportStreamData(panel,{connected_providers:2}),/Odbiór raportów działa/);
});
test("stale whole snapshots hide cached native report values ages proof and connection counts",()=>{
  const {panel}=fixture();panel.telemetryExpanded=true;reportStreamData(panel);telemetryData(panel,[nativeTelemetryRow()]);
  panel.payload.data.updated_at=new Date(NOW-30001).toISOString();
  const html=panel.telemetryDiagnosticsHtml();assert.match(html,/Brak bieżącej diagnostyki/);
  assert.doesNotMatch(html,/Raport odebrany przez EMS|5 s|175 s|Połączenia|Odbiór raportów działa/);
  assert.match(panel.reportStreamHtml(),/Brak bieżącego statusu/);assert.doesNotMatch(panel.reportStreamHtml(),/Połączenia:|potwierdzonym odbiorem: 1/);
});
test("native source expansion remains open while focused edits and readonly status polling are preserved",async()=>{
  const {panel,calls}=fixture();reportStreamData(panel);telemetryData(panel,[nativeTelemetryRow()]);
  panel.shadowRoot.getElementById("telemetry-diagnostics-toggle").events.click();assert.equal(panel.telemetryExpanded,true);
  const field=panel.shadowRoot.querySelector('input[data-key="capacity_kwh"]');field.value="77";field.events.input();panel.shadowRoot.activeElement=field;
  const html=panel.shadowRoot.innerHTML;await panel.refresh();assert.equal(panel.shadowRoot.innerHTML,html);assert.equal(panel.telemetryExpanded,true);
  panel.shadowRoot.activeElement=null;panel.render();assert.match(panel.telemetryDiagnosticsHtml(),/Raport odebrany przez EMS/);
  assert.equal(panel.shadowRoot.querySelector('input[data-key="capacity_kwh"]').value,"77");assert.ok(calls.every(message=>message.type==="deye_ems/status"));
  assert.equal(panel.shadowRoot.nodes.filter(node=>node.attrs.tag==="details").length,1);
});
test("HA secondary timestamp labels appear only when the HA marker is actually older than native reception",()=>{
  const {panel}=fixture();panel.telemetryExpanded=true;reportStreamData(panel);
  for(const ha_age_seconds of [5,2,null,NaN]){
    const html=telemetryData(panel,[nativeTelemetryRow({ha_age_seconds})]);assert.doesNotMatch(html,/Wiek znacznika HA:/);assert.match(html,/Raport odebrany przez EMS/);
  }
});

test("automatic Deye ceiling shows a missing value when invalid or stale",()=>{
  const {panel}=fixture();
  Object.assign(panel.payload.data.inputs,{grid_charge_limit_valid:false,
    deye_max_charge_current_a:200,deye_grid_charge_limit_a:190});
  panel.render();
  let section=panel.shadowRoot.innerHTML.split('<h2>Ładowanie akumulatora z sieci</h2>')[1].split('</section>')[0];
  assert.doesNotMatch(section,/>190<small>/);
  assert.match(section,/Brak poprawnego odczytu limitu Deye/);
  panel.payload.data.inputs.grid_charge_limit_valid=true;
  panel.payload.data.updated_at=new Date(NOW-31000).toISOString();
  panel.render();
  section=panel.shadowRoot.innerHTML.split('<h2>Ładowanie akumulatora z sieci</h2>')[1].split('</section>')[0];
  assert.doesNotMatch(section,/>190<small>/);
});

test("Solcast API usage is visible before advanced details and uses the local UTC budget",()=>{
  const {panel,calls}=fixture();apiUsage(panel);panel.render();
  const visible=panel.shadowRoot.innerHTML.split("<details>")[0];
  assert.match(visible,/aria-label="Zapytania API Solcast"/);
  assert.match(visible,/Wykorzystano dziś<\/span><strong>4<\/strong>/);
  assert.match(visible,/Limit na dobę UTC<\/span><strong>8<\/strong>/);
  assert.match(visible,/Pozostało<\/span><strong>4<\/strong>/);
  assert.match(visible,/Doba UTC: 2026-11-10/);
  assert.match(visible,/Odnowienie limitu: 11\.11,?\s+01:00 \(Europe\/Warsaw\)/);
  assert.match(visible,/Lokalny rejestr obejmuje próby zapytań/);
  assert.match(visible,/To nie licznik udanych pobrań/);
  assert.match(visible,/Zapytania innych klientów nie są tu automatycznie doliczane/);
  assert.equal(calls.length,0);
});

test("Solcast API usage preserves a real zero and clamps remaining after a raised initial counter",()=>{
  const {panel}=fixture();
  let html=apiUsage(panel,{quota:{limit:8,utc:{day:"2026-11-10",used:0}}});
  assert.match(html,/Wykorzystano dziś<\/span><strong>0<\/strong>/);
  assert.match(html,/Pozostało<\/span><strong>8<\/strong>/);
  assert.doesNotMatch(html,/Limit zapytań API EMS wyczerpany/);
  for(const used of [8,10]){
    html=apiUsage(panel,{reason:"daily_quota_exhausted",quota:{limit:8,utc:{day:"2026-11-10",used}}});
    assert.match(html,new RegExp('Wykorzystano dziś</span><strong>'+used+'</strong>'));
    assert.match(html,/Pozostało<\/span><strong>0<\/strong>/);
    assert.match(html,/Limit zapytań API EMS wyczerpany/);
    assert.doesNotMatch(html,/<strong>-\d/);
  }
});

test("Solcast API usage never turns missing malformed or other-day counters into zero",()=>{
  const {panel}=fixture();
  const invalid=[undefined,{},null,{limit:8},
    ...[null,true,"4",4.5,-1,Infinity,NaN].map(used=>({limit:8,utc:{day:"2026-11-10",used}})),
    ...[null,true,"8",0,-1,8.5,Infinity].map(limit=>({limit,utc:{day:"2026-11-10",used:4}})),
    ...[undefined,"2026-11-09","2026-11-11","2026-02-30","<img src=x onerror=alert(1)>"].map(day=>({limit:8,utc:{day,used:4}}))];
  for(const quota of invalid){
    const html=apiUsage(panel,{quota});
    assert.equal((html.match(/<strong>—<\/strong>/g)||[]).length,3);
    assert.doesNotMatch(html,/<strong>0<\/strong>|Odnowienie limitu:|<img/);
  }
});

test("Solcast API usage rejects stale snapshots and known corrupt request history",()=>{
  const {panel}=fixture();
  for(const reason of ["invalid_quota_state","clock_moved_backwards"]){
    const html=apiUsage(panel,{reason,quota:{limit:8,utc:{day:"2026-11-10",used:0}}});
    assert.equal((html.match(/<strong>—<\/strong>/g)||[]).length,3);
    assert.match(html,/Liczba dostępnych zapytań jest nieznana/);
  }
  panel.payload.data.updated_at=new Date(NOW-30001).toISOString();
  const html=apiUsage(panel,{reason:"daily_quota_exhausted",quota:{limit:8,utc:{day:"2026-11-10",used:8}}});
  assert.equal((html.match(/<strong>—<\/strong>/g)||[]).length,3);
  assert.match(html,/Brak aktualnego odczytu licznika/);
  assert.doesNotMatch(html,/Odnowienie limitu:|Limit zapytań API EMS wyczerpany/);
  panel.payload.data.updated_at=new Date(NOW).toISOString();
  const previousDay=apiUsage(panel,{reason:"daily_quota_exhausted",quota:{limit:8,utc:{day:"2026-11-09",used:8}}});
  assert.match(previousDay,/Licznik dotyczy innej doby UTC/);
  assert.doesNotMatch(previousDay,/Limit zapytań API EMS wyczerpany/);
});

test("Solcast API usage distinguishes HA forecasts disabled API and unconfigured API without guessing their counts",()=>{
  const {panel}=fixture();
  for(const [changes,message] of [
    [{status:"ha_entities",api_configured:false,api_enabled:false,quota:undefined},/Prognoza z encji HA\. EMS nie otrzymuje licznika zapytań tej integracji/],
    [{status:"ha_entities",api_configured:true,api_enabled:false,quota:undefined},/Pobieranie API EMS wyłączone\. Prognoza z encji HA/],
    [{status:"not_configured",api_configured:false,api_enabled:false,quota:undefined},/Klient API EMS nie jest skonfigurowany/]
  ]){
    const html=apiUsage(panel,changes);assert.match(html,message);
    assert.equal((html.match(/<strong>—<\/strong>/g)||[]).length,3);
    assert.doesNotMatch(html,/<strong>0<\/strong>/);
  }
  const html=apiUsage(panel,{status:"unavailable",reason:"authentication_failed"});
  assert.match(html,/Wykorzystano dziś<\/span><strong>4<\/strong>/);
});

test("Solcast UTC reset displays Polish summer time without moving the quota day",()=>{
  const now=Date.parse("2026-07-04T23:15:00Z"),{panel}=fixture([],now);
  panel.payload.data.updated_at=new Date(now).toISOString();
  const html=apiUsage(panel,{quota:{limit:10,utc:{day:"2026-07-04",used:3},warsaw:{day:"2026-07-05",used:1}}});
  assert.match(html,/Doba UTC: 2026-07-04/);
  assert.match(html,/Odnowienie limitu: 05\.07,?\s+02:00 \(Europe\/Warsaw\)/);
  assert.match(html,/Wykorzystano dziś<\/span><strong>3<\/strong>/);
  assert.match(html,/Pozostało<\/span><strong>7<\/strong>/);
});

test("Solcast API usage never echoes provider fields credentials or arbitrary reason text",()=>{
  const {panel}=fixture();
  const html=apiUsage(panel,{api_key:"private-key-never-render",status:"<img src=x>",reason:"private-key-never-render",
    source:"<script>private-key-never-render</script>",sites:[{resource_id:"private-site"}]});
  assert.doesNotMatch(html,/private-key|private-site|<script|<img/);
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
  panel.payload.options.topology="load_with_external_ct";
  Object.assign(panel.payload.data.inputs,{topology:"load_with_external_ct",grid_power:0,
    load_power:5000,raw_load_power:3000,outside_load_w:2000,outside_power_valid:true,grid_port_power:-2000});
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

function topologySection(panel){
  const basic=panel.shadowRoot.innerHTML.split("<details>")[0];
  return basic.split('<section aria-label="Układ instalacji">')[1]?.split("</section>")[0];
}

test("LOAD topology information stays visible in the main panel and does not invent external consumption",()=>{
  const {panel,calls}=fixture();
  Object.assign(panel.payload.options,{inverter_max_power_kw:12});
  Object.assign(panel.payload.data.inputs,{outside_load_w:0,outside_power_valid:true});
  panel.render();
  const section=topologySection(panel);
  assert.match(section,/<h2>Układ LOAD<\/h2>/);
  assert.match(section,/LOAD: 2,8 kW/);
  assert.match(section,/odbiory między GRID a CT: nieobliczane w układzie LOAD/);
  assert.doesNotMatch(section,/odbiory między GRID a CT: 0 kW|Sieć na CT:/);
  assert.match(section,/port GRID falownika: 0 kW/);
  assert.match(section,/Dom w modelu EMS: 2,8 kW · Sieć na porcie GRID: 0 kW/);
  assert.match(section,/Moc znamionowa falownika 12 kW jest wspólna dla wyjścia LOAD i oddawania przez port GRID/);
  assert.match(panel.shadowRoot.innerHTML,/dom: pomiar LOAD/);
  assert.doesNotMatch(panel.shadowRoot.innerHTML,/dom: wszystkie wybrane obwody/);
  assert.equal(calls.length,0);
});

test("CT topology shows native LOAD external branch total home and utility exchange before advanced details",()=>{
  const {panel,calls}=fixture();
  panel.payload.options.topology="load_with_external_ct";
  panel.payload.options.inverter_max_power_kw=12;
  Object.assign(panel.payload.data.inputs,{topology:"load_with_external_ct",raw_load_power:2000,
    outside_load_w:25000,outside_power_valid:true,grid_port_power:-12000,load_power:27000,grid_power:13000});
  panel.render();
  const section=topologySection(panel);
  assert.match(section,/<h2>Układ LOAD i CT<\/h2>/);
  assert.match(section,/LOAD: 2 kW · odbiory między GRID a CT: 25 kW · port GRID falownika: -12 kW/);
  assert.match(section,/Dom w modelu EMS: 27 kW · Sieć na CT: 13 kW/);
  assert.match(section,/O wymianie z siecią decyduje pomiar CT/);
  assert.match(section,/pozostałą moc bezpośrednio z sieci; ta część nie przechodzi przez falownik/);
  assert.equal(calls.length,0);
});

test("saved topology heading survives stale missing and invalid snapshots without showing old readings",()=>{
  for(const topology of ["load_only","load_with_external_ct"]){
    for(const corrupt of [
      p=>{p.data.updated_at=new Date(NOW-30001).toISOString();},
      p=>{p.data.updated_at=new Date(NOW+1).toISOString();},
      p=>{delete p.data.updated_at;},
      p=>{delete p.data.inputs;},
      p=>{p.data.inputs.telemetry_valid=false;},
      p=>{p.data.inputs.topology=topology==="load_only"?"load_with_external_ct":"load_only";}
    ]){
      const {panel}=fixture();
      panel.payload.options.topology=topology;
      Object.assign(panel.payload.data.inputs,{topology,raw_load_power:9000,grid_port_power:-4000,
        outside_load_w:4000,outside_power_valid:true,grid_power:5000,load_power:13000});
      corrupt(panel.payload);panel.render();
      const section=topologySection(panel);
      assert.match(section,new RegExp('<h2>'+(topology==="load_only"?'Układ LOAD':'Układ LOAD i CT')+'</h2>'));
      assert.match(section,/LOAD: — kW/);
      assert.match(section,/port GRID falownika: — kW/);
      assert.match(section,/Dom w modelu EMS: — kW/);
      assert.doesNotMatch(section,/LOAD: 9 kW|port GRID falownika: -4 kW|Dom w modelu EMS: 13 kW/);
      assert.match(section,/notice warning/);
    }
  }
});

test("an unsaved topology draft cannot relabel the saved installation or current measurements",()=>{
  for(const topology of ["load_only","load_with_external_ct"]){
    const {panel}=fixture();
    panel.payload.options.topology=topology;
    panel.payload.data.inputs.topology=topology;
    panel.drafts.topology=topology==="load_only"?"load_with_external_ct":"load_only";
    panel.render();
    const section=topologySection(panel);
    assert.match(section,new RegExp('<h2>'+(topology==="load_only"?'Układ LOAD':'Układ LOAD i CT')+'</h2>'));
    assert.match(section,/LOAD: 2,8 kW/);
    assert.equal(panel.shadowRoot.getElementById("topology").value,panel.drafts.topology);
    assert.match(panel.shadowRoot.innerHTML,/Niezapisana zmiana/);
  }
});

test("unknown saved topology remains unknown even when a snapshot or draft names LOAD or CT",()=>{
  for(const topology of [undefined,null,"unexpected"]){
    const {panel}=fixture();
    panel.payload.options.topology=topology;
    panel.drafts.topology="load_with_external_ct";
    panel.render();
    const section=topologySection(panel);
    assert.match(section,/<h2>Układ instalacji<\/h2>/);
    assert.doesNotMatch(section,/<h2>Układ LOAD/);
    assert.match(section,/Nie rozpoznano zapisanego układu instalacji/);
    assert.match(section,/LOAD: — kW/);
    assert.match(section,/Wymiana z siecią: — kW/);
  }
});

test("topology section distinguishes saved configuration from fresh actual inverter mode and flags disagreement",()=>{
  for(const [topology,expected,other] of [
    ["load_only","Zero Export To Load","Zero Export To CT"],
    ["load_with_external_ct","Zero Export To CT","Zero Export To Load"]
  ]){
    const {panel}=fixture();
    panel.payload.options.topology=topology;
    Object.assign(panel.payload.data.inputs,{topology,inverter_work_mode:expected});
    panel.render();
    let section=topologySection(panel);
    assert.ok(section.includes('Zapisany układ EMS: '+expected+' · odczyt trybu falownika: '+expected));
    assert.doesNotMatch(section,/Niezgodność trybu falownika/);
    for(const actual of [other,"Selling First"]){
      Object.assign(panel.payload.data.inputs,{inverter_work_mode:actual,telemetry_valid:false});
      panel.render();section=topologySection(panel);
      assert.ok(section.includes('odczyt trybu falownika: '+actual));
      assert.match(section,/Niezgodność trybu falownika z zapisanym układem EMS/);
      assert.ok(section.includes('Wymagany tryb: '+expected));
      assert.match(section,new RegExp('<h2>'+(topology==="load_only"?'Układ LOAD':'Układ LOAD i CT')+'</h2>'));
    }
  }
});

test("stale or missing actual modes remain unknown and fresh topology errors produce a safe warning",()=>{
  const {panel}=fixture();
  Object.assign(panel.payload.data.inputs,{inverter_work_mode:"Zero Export To CT",topology_error:"private_balance_detail"});
  panel.render();
  let section=topologySection(panel);
  assert.match(section,/Błąd pomiarów układu/);
  assert.doesNotMatch(section,/private_balance_detail/);
  panel.payload.data.updated_at=new Date(NOW-30001).toISOString();
  panel.render();section=topologySection(panel);
  assert.match(section,/odczyt trybu falownika: brak aktualnego odczytu/);
  assert.doesNotMatch(section,/odczyt trybu falownika: Zero Export To CT|Niezgodność trybu falownika|Błąd pomiarów układu/);
  panel.payload.data.updated_at=new Date(NOW).toISOString();
  panel.payload.data.inputs.topology_error=null;
  for(const actual of [undefined,null,""," ","unknown","unavailable"]){
    panel.payload.data.inputs.inverter_work_mode=actual;panel.render();section=topologySection(panel);
    assert.match(section,/odczyt trybu falownika: brak poprawnego odczytu/);
    assert.doesNotMatch(section,/Niezgodność trybu falownika/);
  }
  panel.payload.data.inputs.inverter_work_mode='<img src=x onerror="alert(1)">';
  panel.render();section=topologySection(panel);
  assert.match(section,/odczyt trybu falownika: &lt;img/);
  assert.doesNotMatch(section,/<img/);
});

test("topology readouts retain true zero and reject missing malformed or unvalidated readings",()=>{
  const {panel}=fixture();
  panel.payload.options.topology="load_with_external_ct";
  Object.assign(panel.payload.data.inputs,{topology:"load_with_external_ct",raw_load_power:0,
    grid_port_power:0,outside_load_w:0,outside_power_valid:true,load_power:0,grid_power:0});
  panel.render();
  let section=topologySection(panel);
  assert.match(section,/LOAD: 0 kW · odbiory między GRID a CT: 0 kW · port GRID falownika: 0 kW/);
  assert.match(section,/Dom w modelu EMS: 0 kW · Sieć na CT: 0 kW/);
  for(const value of [undefined,null,"unknown","",Infinity,NaN,true]){
    for(const key of ["raw_load_power","grid_port_power","outside_load_w","load_power","grid_power"])
      panel.payload.data.inputs[key]=value;
    panel.render();section=topologySection(panel);
    assert.match(section,/LOAD: — kW · odbiory między GRID a CT: — kW · port GRID falownika: — kW/);
    assert.match(section,/Dom w modelu EMS: — kW · Sieć na CT: — kW/);
  }
  Object.assign(panel.payload.data.inputs,{outside_load_w:0,outside_power_valid:false});
  panel.render();section=topologySection(panel);
  assert.match(section,/odbiory między GRID a CT: — kW/);
  assert.match(section,/Brak poprawnego bilansu CT i portu GRID/);
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
  panel.payload.mode="active";
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
  assert.doesNotMatch(source,/\bfetch\(|XMLHttpRequest|import\s*\(/);
  assert.deepEqual(source.match(/https?:\/\/[^'"\s]+/g),["https://github.com/gaszu/deye-ems/releases/tag/v"]);
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

function hardwareData(panel,phases=1){
  panel.payload.options.hardware_profile={model_id:"SUN-6K-SG04LP1-EU",label:"SUN-6K-SG04LP1-EU",phases,
    connection_phases:3,inverter_phase:"L2",battery_type:"LV",battery_min_v:40,battery_max_v:60,
    rated_power_kw:6,phase_max_power_kw:6,grid_passthrough_a:45,max_charge_current_a:135,
    control_supported:true,source_url:"https://www.deyeinverter.com/product/verified-model.html"};
  panel.payload.options.effective_hardware_limits={inverter_max_power_kw:5,inverter_phase_max_power_kw:4.5};
  panel.render();
}
const hardwareForm=(errors={})=>({type:"form",flow_id:"hardware-flow",step_id:"inverter",errors,
  data_schema:[
    {name:"inverter_model",required:true,default:"custom",selector:{select:{options:[{value:"custom",label:"Własny / dotychczasowe parametry"},{value:"SUN-6K-SG04LP1-EU",label:"Deye 6 kW — 1 faza"}]}}},
    {name:"inverter_phases",required:true,default:"3",selector:{select:{options:["1","3"]}}},
    {name:"connection_phases",required:true,default:"3",selector:{select:{options:["1","3"]}}},
    {name:"inverter_phase",required:true,default:"L1",selector:{select:{options:["L1","L2","L3"]}}}]});
const hardwareConfirmation=()=>({type:"form",flow_id:"hardware-flow",step_id:"inverter_confirm",errors:{},
  description_placeholders:{model_preview:"Model SUN-6K-SG04LP1-EU. Jedna faza; dotychczasowa rezerwa SoC i niższe limity zachowane."},
  data_schema:[{name:"confirm_model",required:true,default:false,selector:{boolean:{}}}]});
function nativeHardware(panel,{preview,finish}={}){
  const apiCalls=[],effects={writes:0};
  panel._hass.callApi=async(method,route,data)=>{
    apiCalls.push({method,route,data});
    if(method==="DELETE")return {};
    if(route==="config/config_entries/options/flow")return {type:"menu",flow_id:"hardware-flow",step_id:"init",menu_options:["inverter","parameters","sources"]};
    if(data.next_step_id==="inverter")return hardwareForm();
    if(Object.hasOwn(data,"inverter_model"))return preview?preview(data):hardwareConfirmation();
    assert.equal(data.confirm_model,true);effects.writes++;
    return finish?finish(data):{type:"create_entry",data:{private_server_result:"do-not-retain"}};
  };
  return {apiCalls,effects};
}
function hardwareInput(panel,name,value){
  const input=panel.shadowRoot.querySelector('[data-hardware-field="'+name+'"]');assert.ok(input,name);
  if(input.type==="checkbox")input.checked=value;else input.value=value;
  input.events.input();return input;
}

test("hardware summary is always visible with separate catalog effective and connection limits",()=>{
  const {panel,calls}=fixture();hardwareData(panel);
  const html=panel.shadowRoot.innerHTML.split("<details>")[0];
  assert.match(html,/Falownik i ograniczenia/);assert.match(html,/SUN-6K-SG04LP1-EU/);
  assert.match(html,/Jednofazowy · podłączenie L2 · przyłącze trójfazowe/);
  assert.match(html,/Moc katalogowa: 6 kW/);assert.match(html,/Skuteczny limit falownika: 5 kW/);
  assert.match(html,/na fazę: 4,5 kW/);assert.match(html,/Limit przyłącza: 12 kW/);
  assert.match(html,/Informacja sprzętowa; nie podwyższa zapisanego limitu/);
  assert.match(html,/Dokumentacja producenta/);assert.equal(calls.length,0);
});

test("single-phase hardware never describes three-phase balancing even when an old flag is set",()=>{
  const {panel}=fixture();hardwareData(panel);panel.payload.data.inputs.grid_charge_balanced=true;panel.render();
  assert.match(panel.shadowRoot.innerHTML,/Falownik jednofazowy — faza L2/);
  assert.doesNotMatch(panel.shadowRoot.innerHTML,/Bilansowanie poboru GRID potwierdzone/);
  hardwareData(panel,3);assert.match(panel.shadowRoot.innerHTML,/Trójfazowy/);
  assert.match(panel.shadowRoot.innerHTML,/Bilansowanie poboru GRID potwierdzone/);
});

test("single-phase LOAD readout displays only the actual connected port phase",()=>{
  const {panel}=fixture();hardwareData(panel);Object.assign(panel.payload.data.inputs,{grid_l1_power:0,grid_l2_power:1200,grid_l3_power:0});
  panel.render();const html=panel.gridPhaseReadoutHtml();
  assert.equal(html,"GRID L2 (port jednofazowy): 1,2 kW");assert.doesNotMatch(html,/L1|L3/);
  const regulation=panel.shadowRoot.innerHTML.split("<h2>Regulacja ładowania</h2>")[1].split("</section>")[0];
  assert.match(regulation,/GRID L2 \(port jednofazowy\): 1,2 kW/);assert.doesNotMatch(regulation,/L1 \/ L2 \/ L3/);
});

test("single-phase inverter still displays all real utility CT phases on a three-phase connection",()=>{
  const {panel}=fixture();hardwareData(panel);panel.payload.options.topology="load_with_external_ct";
  Object.assign(panel.payload.data.inputs,{topology:"load_with_external_ct",grid_l1_power:1100,grid_l2_power:1200,grid_l3_power:1300});
  assert.equal(panel.gridPhaseReadoutHtml(),"CT L1 / L2 / L3: 1,1 / 1,2 / 1,3 kW");
});

test("one-phase CT connection has one readout while stale or unknown phase readings remain missing",()=>{
  const {panel}=fixture();hardwareData(panel);Object.assign(panel.payload.options.hardware_profile,{connection_phases:1,inverter_phase:"L1"});
  panel.payload.options.topology="load_with_external_ct";Object.assign(panel.payload.data.inputs,{topology:"load_with_external_ct",grid_l1_power:1250,grid_l2_power:0,grid_l3_power:0});
  assert.equal(panel.gridPhaseReadoutHtml(),"CT L1 (przyłącze jednofazowe): 1,3 kW");
  panel.payload.data.updated_at=new Date(NOW-30001).toISOString();assert.equal(panel.gridPhaseReadoutHtml(),"CT L1 (przyłącze jednofazowe): — kW");
  panel.payload.options.hardware_profile.inverter_phase="unknown";assert.equal(panel.gridPhaseReadoutHtml(),"Faza podłączenia niepotwierdzona: — kW");
});

test("hardware names and URLs are escaped and unsupported control is explicit",()=>{
  const {panel}=fixture();hardwareData(panel);const h=panel.payload.options.hardware_profile;
  h.label='<img src=x onerror="unexpected()">';h.inverter_phase='<script>x</script>';h.control_supported=false;
  for(const source_url of ["javascript:unexpected()","https://untrusted.example/model","https://deye.com/\" onload=x","https://deye.com/\nattack"]){
    h.source_url=source_url;const html=panel.hardwareHtml();assert.doesNotMatch(html,/<img|<script|href=/);
    assert.match(html,/nie ma potwierdzonej obsługi sterowania/);assert.match(html,/&lt;img/);
  }
});

test("hardware opens native model selection without changing options source or mode",async()=>{
  const {panel,calls}=fixture(),before=JSON.stringify(panel.payload),{apiCalls,effects}=nativeHardware(panel);
  await panel.shadowRoot.getElementById("hardware-open").events.click();
  assert.equal(panel.hardwareFlow.step_id,"inverter");assert.equal(panel.hardwareDraft.inverter_model,"custom");
  assert.match(panel.hardwareEditorHtml(),/Pokaż parametry modelu/);
  assert.equal(JSON.stringify(panel.payload),before);assert.equal(effects.writes,0);assert.equal(calls.length,0);
  assert.deepEqual(JSON.parse(JSON.stringify(apiCalls)),[
    {method:"POST",route:"config/config_entries/options/flow",data:{handler:"test-entry"}},
    {method:"POST",route:"config/config_entries/options/flow/hardware-flow",data:{next_step_id:"inverter"}}]);
});

test("hardware selection previews single-phase model and only explicit consent saves",async()=>{
  const {panel,calls}=fixture(),{apiCalls,effects}=nativeHardware(panel),before=JSON.stringify(panel.payload);
  await panel.openHardware();hardwareInput(panel,"inverter_model","SUN-6K-SG04LP1-EU");hardwareInput(panel,"inverter_phase","L2");
  await panel.submitHardware();assert.equal(effects.writes,0);assert.equal(panel.hardwareFlow.step_id,"inverter_confirm");
  assert.deepEqual(JSON.parse(JSON.stringify(apiCalls.at(-1).data)),{inverter_model:"SUN-6K-SG04LP1-EU",inverter_phases:"3",connection_phases:"3",inverter_phase:"L2"});
  assert.equal(panel.hardwareDraft.confirm_model,false);assert.match(panel.hardwareEditorHtml(),/dotychczasowa rezerwa SoC i niższe limity zachowane/);
  const count=apiCalls.length;await panel.submitHardware();assert.equal(apiCalls.length,count);assert.match(panel.hardwareEditorHtml(),/zaznacz potwierdzenie/);
  hardwareInput(panel,"confirm_model",true);await panel.shadowRoot.getElementById("hardware-form").events.submit({preventDefault(){}});
  assert.equal(effects.writes,1);assert.equal(panel.hardwareFlow.type,"create_entry");assert.equal(panel.payload.mode,"shadow");
  assert.deepEqual(JSON.parse(JSON.stringify(apiCalls.at(-1).data)),{confirm_model:true});
  assert.equal(JSON.stringify(panel.payload),before);assert.ok(calls.every(message=>message.type==="deye_ems/status"));
  assert.doesNotMatch(JSON.stringify(panel.hardwareFlow)+panel.hardwareEditorHtml(),/do-not-retain|private_server_result/);
});

test("cancelling hardware selection or preview deletes only the draft",async()=>{
  for(const preview of [false,true]){
    const {panel}=fixture(),before=JSON.stringify(panel.payload),{apiCalls,effects}=nativeHardware(panel);
    await panel.openHardware();hardwareInput(panel,"inverter_model","SUN-6K-SG04LP1-EU");if(preview)await panel.submitHardware();
    await panel.shadowRoot.getElementById("hardware-cancel").events.click();
    assert.equal(effects.writes,0);assert.equal(panel.hardwareOpen,false);assert.equal(panel.hardwareFlow,null);
    assert.deepEqual(JSON.parse(JSON.stringify(panel.hardwareDraft)),{});assert.equal(JSON.stringify(panel.payload),before);
    assert.equal(apiCalls.at(-1).method,"DELETE");assert.match(apiCalls.at(-1).route,/hardware-flow$/);
  }
});

test("hardware form drafts and focus survive status polling",async()=>{
  const {panel}=fixture();nativeHardware(panel);await panel.openHardware();
  const input=hardwareInput(panel,"inverter_phase","L2");panel.shadowRoot.activeElement=input;
  const html=panel.shadowRoot.innerHTML;await panel.refresh();assert.equal(panel.shadowRoot.innerHTML,html);
  assert.equal(panel.hardwareDraft.inverter_phase,"L2");panel.shadowRoot.activeElement=null;panel.render();
  assert.equal(panel.shadowRoot.querySelector('[data-hardware-field="inverter_phase"]').value,"L2");
});

test("hardware validation errors preserve selection and never echo raw errors",async()=>{
  const {panel}=fixture();nativeHardware(panel,{preview:()=>hardwareForm({base:"private-provider-error"})});
  await panel.openHardware();hardwareInput(panel,"inverter_phase","L2");await panel.submitHardware();
  assert.equal(panel.hardwareDraft.inverter_phase,"L2");assert.match(panel.hardwareEditorHtml(),/Sprawdź wybór modelu/);
  assert.doesNotMatch(panel.hardwareEditorHtml(),/private-provider-error/);
});

test("hardware requires explicit observation and cannot save after an external mode change",async()=>{
  const {panel,calls}=fixture(),{apiCalls,effects}=nativeHardware(panel);panel.payload.mode="active";panel.render();
  await panel.openHardware();assert.equal(apiCalls.length,0);assert.match(panel.hardwareEditorHtml(),/Przejdź do obserwacji/);
  panel._hass.callWS=async message=>{calls.push(message);return {...panel.payload,mode:"shadow"};};
  await panel.shadowRoot.getElementById("hardware-observe").events.click();assert.equal(panel.hardwareFlow.step_id,"inverter");
  panel.payload.mode="active";const count=apiCalls.length;await panel.submitHardware();assert.equal(apiCalls.length,count);assert.equal(effects.writes,0);
});

test("hardware confirmation is never prechecked from a server default and unknown schemas cannot be submitted",async()=>{
  const {panel}=fixture();nativeHardware(panel,{preview:()=>{const result=hardwareConfirmation();result.data_schema[0].default=true;return result;}});
  await panel.openHardware();await panel.submitHardware();assert.equal(panel.hardwareDraft.confirm_model,false);
  await panel.cancelHardware();nativeHardware(panel,{preview:()=>({...hardwareConfirmation(),data_schema:[{name:"api_key",default:"do-not-copy",selector:{text:{}}}]})});
  await panel.openHardware();await panel.submitHardware();assert.match(panel.hardwareEditorHtml(),/Nie udało się/);
  assert.doesNotMatch(panel.hardwareEditorHtml()+JSON.stringify(panel.hardwareFlow),/do-not-copy|api_key/);
});

test("hardware committing save cannot be cancelled while a cancelled late opening cannot return",async()=>{
  const {panel}=fixture();let finish;nativeHardware(panel,{finish:()=>new Promise(resolve=>{finish=resolve;})});
  await panel.openHardware();await panel.submitHardware();hardwareInput(panel,"confirm_model",true);
  const saving=panel.submitHardware();assert.equal(panel.hardwareCommitting,true);assert.equal(panel.shadowRoot.getElementById("hardware-cancel").disabled,true);
  await panel.cancelHardware();assert.equal(panel.hardwareOpen,true);finish({type:"create_entry"});await saving;
  assert.equal(panel.hardwareFlow.type,"create_entry");await panel.cancelHardware();
  let opened;const apiCalls=[];panel._hass.callApi=async(method,route)=>{apiCalls.push({method,route});return method==="POST"?new Promise(resolve=>{opened=resolve;}):{};};
  const opening=panel.openHardware();await flush();await panel.cancelHardware();
  opened({type:"menu",flow_id:"late-hardware-flow",step_id:"init",menu_options:["inverter"]});await opening;await flush();
  assert.equal(panel.hardwareOpen,false);assert.equal(panel.hardwareFlow,null);assert.equal(apiCalls.at(-1).method,"DELETE");assert.match(apiCalls.at(-1).route,/late-hardware-flow$/);
});

test("hardware editor participates in unsaved-change protection and disconnect cleanup",async()=>{
  const {panel,reloads}=fixture(),{apiCalls}=nativeHardware(panel);await panel.openHardware();
  assert.equal(panel.hasUnsavedChanges(),true);assert.equal(panel.reloadInterface(),false);assert.equal(reloads(),0);
  panel.disconnectedCallback();await flush();assert.equal(panel.hardwareOpen,false);assert.equal(panel.hardwareFlow,null);
  assert.ok(apiCalls.some(call=>call.method==="DELETE"&&call.route.endsWith("hardware-flow")));
});

function calendarData(panel,changes={}){
  panel.payload.options.tariff_calendar={profile_id:"legacy_g13",label:"Dotychczasowy harmonogram EMS G13",version:"legacy-1",clock_basis:"local",runtime_allowed:true,preview_only:false,
    current_zone:"off_peak",next_change:"2026-11-11T04:00:00+01:00",
    today:[{start:"2026-11-10T07:00:00+01:00",end:"2026-11-10T13:00:00+01:00",zone:"morning_peak",grid_charge_allowed:false,reason:"winter",legacy_slot:3}],
    tomorrow:[{start:"2026-11-11T00:00:00+01:00",end:"2026-11-11T04:00:00+01:00",zone:"off_peak",grid_charge_allowed:true,reason:"winter",legacy_slot:1}],...changes};
  panel.render();return panel.tariffCalendarHtml();
}
test("retained calendar shows today tomorrow zone and clock basis without offering unsupported operators",()=>{
  const {panel,calls}=fixture();const html=calendarData(panel);
  assert.match(html,/Dotychczasowy harmonogram EMS G13/);assert.match(html,/Dziś/);assert.match(html,/Jutro/);
  assert.match(html,/Szczyt przedpołudniowy/);assert.match(html,/Zablokowane/);assert.match(html,/Dozwolone według zasad sezonu/);
  assert.match(html,/Czas lokalny Europe\/Warsaw/);assert.match(html,/Sezon zimowy · slot 3/);
  assert.match(html,/bez automatycznych wyjątków operatora/);assert.match(html,/Wybór operatora.*kolejnym etapie/);
  assert.match(panel.shadowRoot.innerHTML.split("<details>")[0],/Harmonogram taryfy/);assert.equal(calls.length,0);
});
test("preview calendar and fixed meter clock are distinct from a runtime schedule",()=>{
  const {panel}=fixture();const html=calendarData(panel,{profile_id:"tauron_g13_2026",label:"TAURON G13 — podgląd",preview_only:true,runtime_allowed:false,clock_basis:"fixed_cet"});
  assert.match(html,/Stały czas zimowy/);assert.match(html,/Podgląd kalendarza/);assert.doesNotMatch(html,/Zachowany profil G13 z wersji 1.x/);
});
test("calendar rejects malformed intervals and escapes labels without reading raw source URLs",()=>{
  const {panel}=fixture();const html=calendarData(panel,{label:'<img src=x>',version:'<script>x</script>',source_url:'javascript:unexpected()',
    today:[{start:"unknown",end:"unknown",zone:"off_peak",grid_charge_allowed:true},{start:"2026-11-10T13:00:00+01:00",end:"2026-11-10T07:00:00+01:00",zone:"off_peak",grid_charge_allowed:true}]});
  assert.match(html,/&lt;img/);assert.match(html,/Brak poprawnych przedziałów/);assert.doesNotMatch(html,/<img|<script|javascript:/);
});

const flush=()=>new Promise(resolve=>setImmediate(resolve));
const prefixForm=(errors={},profile="deye")=>({type:"form",flow_id:"source-flow",step_id:"entity_prefix",errors,
  data_schema:[{name:"entity_prefix",required:true,default:"existing_site_",selector:{text:{}}},
    {name:"battery_source_profile",required:true,default:profile,selector:{select:{options:[
      {value:"deye",label:"Deye — dane baterii z falownika"},{value:"yambms",label:"YamBMS — opcjonalne osobne źródło"},{value:"manual",label:"Ręczne przypisanie źródeł baterii"}]}}}]});
const sourceForm=()=>({type:"form",flow_id:"source-flow",step_id:"sources",errors:{},
  description_placeholders:{prefix_preview:"Prefiks: new_site_. Sprawdź propozycje. Istnienie encji nie potwierdza zgodności pomiarów."},
  data_schema:[{name:"soc",description:{suggested_value:"sensor.server_generated_soc"},selector:{entity:{domain:"sensor"}}},
    {name:"load_power",description:{suggested_value:"sensor.custom_load"},selector:{entity:{domain:"sensor"}}},
    {name:"ct_grid_power",description:{suggested_value:""},selector:{entity:{domain:"sensor"}}},
    {name:"pc_energy_total",description:{suggested_value:""},selector:{entity:{domain:"sensor"}}}]});
function nativeSources(panel,{preview,finish,profile="deye"}={}){
  const apiCalls=[],effects={writes:0};
  panel._hass.callApi=async(method,route,data)=>{
    apiCalls.push({method,route,data});
    if(method==="DELETE")return {};
    if(route==="config/config_entries/options/flow")return {type:"menu",flow_id:"source-flow",step_id:"init",menu_options:["solcast","entity_prefix","sources"]};
    if(data.next_step_id==="entity_prefix")return prefixForm({},profile);
    if(Object.hasOwn(data,"entity_prefix"))return preview?preview(data):sourceForm();
    // Native HA EntitySelector rejects an empty string; empty optional fields
    // must be absent from the complete form submission.
    assert.ok(Object.values(data).every(value=>value!==""));
    effects.writes++;return finish?finish(data):{type:"create_entry",data:{private_server_result:"must-not-be-kept"}};
  };
  return {apiCalls,effects};
}
function sourceInput(panel,name,value){
  const input=panel.shadowRoot.querySelector('[data-source-field="'+name+'"]');
  assert.ok(input,name);input.value=value;input.events.input();return input;
}

test("source configuration is visible and opens the native current-prefix field without changes",async()=>{
  const {panel,calls}=fixture(),before=JSON.stringify(panel.payload),{apiCalls,effects}=nativeSources(panel);
  assert.match(panel.shadowRoot.innerHTML.split("<details>")[0],/Źródła danych/);
  await panel.shadowRoot.getElementById("sources-open").events.click();
  assert.equal(sourceInput(panel,"entity_prefix","existing_site_").value,"existing_site_");
  assert.match(panel.sourcesHtml(),/Prefiks encji Deye/);
  assert.match(panel.sourcesHtml(),/Pokaż przypisania dla prefiksu/);
  assert.equal(JSON.stringify(panel.payload),before);assert.equal(effects.writes,0);assert.equal(calls.length,0);
  assert.deepEqual(JSON.parse(JSON.stringify(apiCalls)),[
    {method:"POST",route:"config/config_entries/options/flow",data:{handler:"test-entry"}},
    {method:"POST",route:"config/config_entries/options/flow/source-flow",data:{next_step_id:"entity_prefix"}}]);
});

test("native battery profile defaults to Deye and YamBMS or manual selection only requests a preview",async()=>{
  for(const profile of ["deye","yambms","manual"]){
    const {panel,calls}=fixture(),{apiCalls,effects}=nativeSources(panel),before=JSON.stringify(panel.payload);
    await panel.openSources();const select=panel.shadowRoot.querySelector('[data-source-field="battery_source_profile"]');
    assert.equal(select.attrs.tag,"select");assert.equal(select.value,"deye");assert.equal(panel.sourceDraft.battery_source_profile,"deye");
    assert.match(panel.sourcesHtml(),/YamBMS jest opcjonalny/);assert.match(panel.sourcesHtml(),/Deye — dane baterii z falownika/);
    sourceInput(panel,"battery_source_profile",profile);await panel.submitSources();
    assert.deepEqual(JSON.parse(JSON.stringify(apiCalls.at(-1).data)),{entity_prefix:"existing_site_",battery_source_profile:profile});
    assert.equal(effects.writes,0);assert.equal(calls.length,0);assert.equal(JSON.stringify(panel.payload),before);
    assert.equal(panel.sourceDraft.load_power,"sensor.custom_load");assert.equal(panel.sourceDraft.ct_grid_power,"");
    await panel.cancelSources();assert.equal(effects.writes,0);assert.equal(JSON.stringify(panel.payload),before);
  }
});

test("an existing native manual battery profile is preserved and profile drafts survive focused polling",async()=>{
  const {panel}=fixture(),{apiCalls}=nativeSources(panel,{profile:"manual"});
  await panel.openSources();assert.equal(panel.sourceDraft.battery_source_profile,"manual");
  const select=sourceInput(panel,"battery_source_profile","yambms");panel.shadowRoot.activeElement=select;
  const html=panel.shadowRoot.innerHTML;await panel.refresh();assert.equal(panel.shadowRoot.innerHTML,html);assert.equal(panel.sourceDraft.battery_source_profile,"yambms");
  panel.shadowRoot.activeElement=null;panel.render();assert.equal(panel.shadowRoot.querySelector('[data-source-field="battery_source_profile"]').value,"yambms");
  const count=apiCalls.length;sourceInput(panel,"battery_source_profile","unexpected");await panel.submitSources();
  assert.equal(apiCalls.length,count);assert.match(panel.sourcesHtml(),/Wybierz źródło danych baterii z listy/);
});

test("new prefix is only a native preview until explicit source save and preserves custom and disabled suggestions",async()=>{
  const {panel,calls}=fixture(),{apiCalls,effects}=nativeSources(panel),before=JSON.stringify(panel.payload);
  await panel.openSources();sourceInput(panel,"entity_prefix","new_site_");await panel.submitSources();
  assert.deepEqual(JSON.parse(JSON.stringify(apiCalls.at(-1).data)),{entity_prefix:"new_site_",battery_source_profile:"deye"});assert.equal(effects.writes,0);
  assert.equal(JSON.stringify(panel.payload),before);assert.equal(calls.length,0);
  assert.equal(panel.sourceDraft.soc,"sensor.server_generated_soc");assert.equal(panel.sourceDraft.load_power,"sensor.custom_load");
  assert.equal(panel.sourceDraft.ct_grid_power,"");assert.equal(panel.sourceDraft.pc_energy_total,"");
  assert.match(panel.sourcesHtml(),/Prefiks: new_site_/);assert.match(panel.sourcesHtml(),/Zapisz prefiks i przypisania/);
  assert.match(panel.sourcesHtml(),/Puste pole wyłącza dane źródło/);
  sourceInput(panel,"soc","sensor.reviewed_soc");await panel.shadowRoot.getElementById("sources-form").events.submit({preventDefault(){}});
  assert.equal(effects.writes,1);assert.deepEqual(JSON.parse(JSON.stringify(apiCalls.at(-1).data)),{soc:"sensor.reviewed_soc",load_power:"sensor.custom_load"});
  assert.equal(panel.sourceFlow.type,"create_entry");assert.match(panel.sourcesHtml(),/EMS pozostaje w obserwacji/);
  assert.equal(panel.payload.mode,"shadow");assert.doesNotMatch(JSON.stringify(panel.sourceFlow)+panel.sourcesHtml(),/must-not-be-kept|private_server_result/);
  assert.equal(calls.some(call=>call.command==="mode"),false);
});

test("cancelling prefix or source preview only deletes the native draft and retains all settings",async()=>{
  for(const preview of [false,true]){
    const {panel,calls}=fixture(),before=JSON.stringify(panel.payload),{apiCalls,effects}=nativeSources(panel);
    await panel.openSources();sourceInput(panel,"entity_prefix","unsaved_");if(preview)await panel.submitSources();
    await panel.shadowRoot.getElementById("sources-cancel").events.click();
    assert.equal(effects.writes,0);assert.equal(calls.length,0);assert.equal(JSON.stringify(panel.payload),before);
    assert.deepEqual(apiCalls.at(-1),{method:"DELETE",route:"config/config_entries/options/flow/source-flow",data:undefined});
    assert.equal(panel.sourceOpen,false);assert.equal(panel.sourceFlow,null);assert.deepEqual(JSON.parse(JSON.stringify(panel.sourceDraft)),{});
  }
});

test("clearing every optional source sends an empty native form only after explicit save in observation",async()=>{
  const {panel,calls}=fixture(),{apiCalls,effects}=nativeSources(panel);
  await panel.openSources();await panel.submitSources();assert.equal(effects.writes,0);
  for(const field of panel.sourceFlow.fields)sourceInput(panel,field.name,"");
  panel.render();assert.match(panel.sourcesHtml(),/Puste pole wyłącza dane źródło/);assert.match(panel.sourcesHtml(),/Zapisz prefiks i przypisania/);
  assert.equal(effects.writes,0);assert.equal(panel.payload.mode,"shadow");
  await panel.shadowRoot.getElementById("sources-form").events.submit({preventDefault(){}});
  assert.equal(effects.writes,1);assert.deepEqual(JSON.parse(JSON.stringify(apiCalls.at(-1).data)),{});
  assert.equal(calls.some(call=>call.command==="mode"),false);
});

test("prefix errors retain the entered draft and polling preserves source input and focus",async()=>{
  const {panel}=fixture();nativeSources(panel,{preview:()=>prefixForm({base:"invalid_entity_prefix",unsafe:"private-provider-error"})});
  await panel.openSources();const input=sourceInput(panel,"entity_prefix","invalid.prefix");panel.shadowRoot.activeElement=input;
  const html=panel.shadowRoot.innerHTML;await panel.refresh();assert.equal(panel.shadowRoot.innerHTML,html);
  panel.shadowRoot.activeElement=null;await panel.submitSources();
  assert.equal(panel.sourceDraft.entity_prefix,"invalid.prefix");assert.match(panel.sourcesHtml(),/Wpisz prefiks bez domeny/);
  assert.doesNotMatch(panel.sourcesHtml(),/private-provider-error/);
});

test("source changes require explicit observation and active mode blocks form submission",async()=>{
  const {panel,calls}=fixture(),{apiCalls,effects}=nativeSources(panel);panel.payload.mode="active";panel.render();
  await panel.openSources();assert.equal(apiCalls.length,0);assert.match(panel.sourcesHtml(),/Przejdź do obserwacji/);
  panel._hass.callWS=async message=>{calls.push(message);return {...panel.payload,mode:message.mode||panel.payload.mode};};
  await panel.shadowRoot.getElementById("sources-observe").events.click();
  assert.equal(panel.payload.mode,"shadow");assert.deepEqual(JSON.parse(JSON.stringify(calls)),[{type:"deye_ems/command",command:"mode",mode:"shadow"}]);
  assert.equal(panel.sourceFlow.step_id,"entity_prefix");const count=apiCalls.length;
  panel.payload.mode="active";panel.render();await panel.submitSources();
  assert.equal(apiCalls.length,count);assert.equal(effects.writes,0);assert.match(panel.sourcesHtml(),/Zmiana źródeł wymaga obserwacji/);
});

test("a dispatched source save cannot be cancelled while a late cancelled opening cannot reopen the editor",async()=>{
  const {panel}=fixture();let finish;
  nativeSources(panel,{finish:()=>new Promise(resolve=>{finish=resolve;})});
  await panel.openSources();await panel.submitSources();const saving=panel.submitSources();
  assert.equal(panel.sourceCommitting,true);assert.equal(panel.shadowRoot.getElementById("sources-cancel").disabled,true);
  await panel.cancelSources();assert.equal(panel.sourceOpen,true);
  finish({type:"create_entry"});await saving;assert.equal(panel.sourceFlow.type,"create_entry");
  await panel.cancelSources();
  const apiCalls=[];let opened;
  panel._hass.callApi=(method,route,data)=>{apiCalls.push({method,route,data});return method==="POST"?new Promise(resolve=>{opened=resolve;}):Promise.resolve({});};
  const opening=panel.openSources();await flush();await panel.cancelSources();
  opened({type:"menu",flow_id:"late-source-flow",step_id:"init",menu_options:["entity_prefix"]});await opening;await flush();
  assert.equal(panel.sourceOpen,false);assert.equal(panel.sourceFlow,null);
  assert.equal(apiCalls.filter(call=>call.method==="POST").length,1);
  assert.equal(apiCalls.at(-1).method,"DELETE");assert.match(apiCalls.at(-1).route,/late-source-flow$/);
});

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
