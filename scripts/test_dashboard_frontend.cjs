// Isolated DOM model: presentation and native selection only, never a live HA call.
const fs=require('fs'),path=require('path'),vm=require('vm'),assert=require('assert');
class Element { constructor(){this.attributes={};this.events={};this.textContent='';}setAttribute(k,v){this.attributes[k]=v;}addEventListener(k,v){this.events[k]=v;} }
class Shadow { constructor(){this.nodes={};}set innerHTML(v){this.markup=v;for(const k of ['ha-icon','.label','.value','button'])this.nodes[k]=new Element();}get innerHTML(){return this.markup;}querySelector(k){return this.nodes[k];} }
class HTMLElement {attachShadow(){this.shadowRoot=new Shadow();return this.shadowRoot;} }
const registry=new Map();const code=fs.readFileSync(path.resolve(__dirname,'../frontend/hpvc-dashboard.js'),'utf8');
vm.runInNewContext(code,{HTMLElement,customElements:{get:k=>registry.get(k),define:(k,v)=>registry.set(k,v)}});
let checks=0;function check(fn){fn();checks++;}
const Row=registry.get('hpvc-limit-entity-row');const Nav=registry.get('hpvc-inverter-navigation');
for(const id of ['number.hms_2000_4t_limit_nonpersistent_absolute','number.hms_1000_2t_limit_nonpersistent_absolute'])check(()=>{
 const row=new Row();row.setConfig({entity:'sensor.hpvc_inverter_limit_entity_display',attribute:'pv1_limit_entity'});row.hass={states:{'sensor.hpvc_inverter_limit_entity_display':{attributes:{pv1_limit_entity:id}}}};
 assert.equal(row.shadowRoot.querySelector('.label').textContent,'Limit entity:');assert.equal(row.shadowRoot.querySelector('.value').textContent,id);assert.equal(row.shadowRoot.querySelector('.value').title,id);assert.equal(row.shadowRoot.querySelector('ha-icon').attributes.icon,'mdi:lock-outline');assert.match(row.shadowRoot.innerHTML,/overflow-x:auto/);assert.match(row.shadowRoot.innerHTML,/white-space:nowrap/);assert.doesNotMatch(row.shadowRoot.innerHTML,/text-overflow:ellipsis|<input|<textarea/);
});
check(()=>{const row=new Row();row.setConfig({entity:'sensor.hpvc_inverter_limit_entity_display',attribute:'pv10_limit_entity'});row.hass={states:{}};assert.equal(row.shadowRoot.querySelector('.value').textContent,'Unavailable');});
check(()=>{const row=new Row();assert.throws(()=>row.setConfig({entity:'text.hpvc_target',attribute:'pv1_limit_entity'}));});
for(const direction of ['next','previous'])check(()=>{
 const nav=new Nav();const calls=[];nav.setConfig({entity:'select.hpvc_selected_inverter',runtime_entity:'sensor.hpvc_effective_inverter_runtime',direction,icon:'mdi:chevron-right'});
 nav.hass={states:{'sensor.hpvc_effective_inverter_runtime':{state:'2'},'select.hpvc_selected_inverter':{state:direction==='next'?'PV2':'PV1'}},callService:(...args)=>calls.push(args)};nav.navigate();assert.equal(calls.length,1);assert.equal(calls[0][0],'select');assert.equal(calls[0][1],'select_option');assert.equal(calls[0][2].entity_id,'select.hpvc_selected_inverter');assert.equal(calls[0][2].option,direction==='next'?'PV1':'PV2');
});
for(const value of ['0','1','unknown','unavailable'])check(()=>{
 const nav=new Nav();nav.setConfig({entity:'select.hpvc_selected_inverter',runtime_entity:'sensor.hpvc_effective_inverter_runtime',direction:'next'});let calls=0;nav.hass={states:{'sensor.hpvc_effective_inverter_runtime':{state:value},'select.hpvc_selected_inverter':{state:'PV1'}},callService:()=>calls++};nav.navigate();assert.equal(calls,0);assert.equal(nav.shadowRoot.querySelector('button').disabled,true);
});
check(()=>{assert.equal((code.match(/\.callService\(/g)||[]).length,1);assert.match(code,/callService\("select", "select_option"/);assert.doesNotMatch(code,/number\.set_value|switch\.turn_|callWS\(|sendMessage\(|fetch\(/);});
const dashboard=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../home assistant/hpvc_native_dashboard.json'),'utf8'));
function* walk(v){if(v&&typeof v==='object'){yield v;for(const x of Object.values(v))yield* walk(x);}}
for(const series of walk(dashboard))if(series.data_generator){
 const generate=new Function('entity','start','end','hass',series.data_generator);
 if(series.data_generator.includes('ui_dashboard_data?.history')){
  const history=[{at:100,mode:'Normal',priority:'Off',limited:false},{at:130,mode:'unknown',priority:'unknown'},{at:160,mode:'Limit',priority:'Waiting',limited:true},{at:400,mode:'Charge',priority:'Active',limited:true}];
  check(()=>{const points=generate({attributes:{ui_dashboard_data:{history}}});assert.deepEqual(points.map(p=>p[0]),[100000,130000,160000,250000,400000,490000]);assert.equal(points[3][1],null);assert.equal(points[5][1],null);});
  if(series.name.startsWith('Executed mode'))check(()=>assert.deepEqual(generate({attributes:{ui_dashboard_data:{history}}}).map(p=>p[1]),[0,null,2,null,1,null]));
  if(series.name==='PV limited')check(()=>assert.deepEqual(generate({attributes:{ui_dashboard_data:{history}}}).map(p=>p[1]),[0,null,1,null,1,null]));
 }
 if(series.data_generator.includes('const raw =')){
  const attribute=JSON.parse(series.data_generator.match(/const raw = entity.attributes\[("[^"]+")\]/)[1]);
  for(const value of [null,undefined,'unknown','unavailable','',NaN])check(()=>assert.equal(generate({attributes:{[attribute]:value}}).length,0));
  check(()=>{const points=generate({attributes:{[attribute]:0}});assert.equal(points.length,1);assert.equal(points[0][1],0);});
 }else check(()=>assert.equal(generate({attributes:{ui_source_attributes:{}}}).length,0));
}
console.log(`${checks} isolated dashboard DOM/selection/chart checks passed`);
