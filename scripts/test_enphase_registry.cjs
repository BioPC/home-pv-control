// Exercise the shipped Node-RED functions, including registry refresh and runtime.
const assert=require('node:assert/strict');
const {Runtime,by}=require('./control_test_runtime.cjs');
let passed=0;
function test(name,fn){fn();passed++;console.log('PASS '+name);}
const MAP='hpvcenphaseregistrymap157',CORE='6498f50f6fea77b9',READ='8b490d1484a538d7';
const clone=x=>JSON.parse(JSON.stringify(x));
function triplet(id='a',renamed=true){
 return ['number','select','switch'].map((domain,i)=>({device_id:id,platform:'enphase_envoy',config_entry_id:'entry_'+id,
  entity_id:renamed?`${domain}.${['ceiling','strategy','meterkast_envoy_serienummerenvoy_dpel'][i]}_${id}`:`${domain}.envoy_${id}_${['dpel_limit','dpel_mode','dpel_enabled'][i]}`,
  unique_id:`123_${['dpel_limit','dpel_mode','dpel_enabled'][i]}`,original_name:['Envoy DPEL Limit','Envoy DPEL Mode','Envoy DPEL'][i]}));
}
function setup(rows=triplet()){
 const r=new Runtime();
 for(let i=1;i<=10;i++)r.states[`input_text.hpvc_pv${i}_limit_number`].state='';
 for(const row of rows){const domain=row.entity_id.split('.')[0];r.states[row.entity_id]={state:domain==='number'?'5000':domain==='select'?'Production':'on',attributes:domain==='number'?{min:0,max:5000,step:1}:domain==='select'?{options:['Production','Export']}:{}};}
 r.run(MAP,{payload:rows});r.refresh();return r;
}
function discover(r){r.global.set('homePvControlRuntimeEvaluationLock',null);const m=r.run(CORE,{topic:'timer'});return m?.hpvc?.enphaseDpelControllers||[];}
function read(r){r.global.set('homePvControlRuntimeEvaluationLock',null);return r.run(READ,r.run(CORE,{topic:'settings'})).hpvc;}
test('fully renamed triplet uses immutable roles and one HA device',()=>{
 const rows=triplet(),r=setup(rows),controllers=discover(r);
 assert.equal(controllers.length,1);assert.equal(controllers[0].enable_entity,rows[2].entity_id);
 const hpvc=read(r);assert.equal(hpvc.configuredInverters[0].adapter_kind,'enphase_dpel');assert.equal(hpvc.configuredInverters[0].full_power,3000);assert.equal(hpvc.configuredInverters[0].minimum_power,0);
});
test('original name, translation key and original entity role work without unique ID',()=>{
 for(const source of ['original_name','translation_key','original_entity_id']){
  const rows=triplet();rows.forEach((r,i)=>{delete r.unique_id;delete r.original_name;r[source]=['DPEL Limit','DPEL Mode','DPEL'][i];});
  assert.equal(discover(setup(rows)).length,1);
 }
});
test('production and PV-limit siblings cannot masquerade as DPEL',()=>{
 const rows=triplet();for(const [entity_id,unique_id] of [['switch.envoy_a_dpel_enabled','123_production'],['number.envoy_a_dpel_limit','123_pvlimit_pct'],['switch.other','123_pv_limit_enabled']])rows.push({...rows[2],entity_id,unique_id,original_name:'Misleading DPEL'});
 const c=discover(setup(rows));assert.equal(c.length,1);assert.equal(c[0].enable_entity,rows[2].entity_id);assert.equal(c[0].limit_entity,rows[0].entity_id);
});
test('ambiguous, disabled and cross-device/config-entry/platform roles fail closed',()=>{
 for(const change of [rows=>rows.push({...rows[2],entity_id:'switch.duplicate'}),rows=>rows[2].disabled_by='user',rows=>rows[2].device_id='other',rows=>rows[2].config_entry_id='other',rows=>rows[2].platform='other']){
  const rows=triplet('a',false);change(rows);assert.equal(discover(setup(rows)).length,0);
 }
});
test('official suffix fallback remains when registry unavailable or device metadata absent',()=>{
 const rows=triplet('a',false),r=setup(rows);r.global.set('homePvControlEnphaseRegistry',undefined);assert.equal(discover(r).length,1);
 rows.forEach(row=>delete row.device_id);assert.equal(discover(setup(rows)).length,1);
});
test('wrong select semantics rejected, with no speculative sibling selection',()=>{
 const rows=triplet(),r=setup(rows);r.states[rows[1].entity_id].attributes.options=['Production'];assert.equal(discover(r).length,0);
 rows[1].unique_id='123_unrelated';rows[1].original_name='Another select';assert.equal(discover(setup(rows)).length,0);
});
test('several Envoys are ordered by device identity and bounded to ten slots',()=>{
 const rows=Array.from({length:11},(_,i)=>triplet(String(i).padStart(2,'0'))).flat(),r=setup(rows),h=read(r);
 assert.equal(h.configuredInverters.length,10);assert.equal(h.enphaseOverflow.length,1);
 assert.equal(h.configuredInverters[1].limit_entity,rows[3].entity_id);
});
test('manual renamed limit is deduplicated and normalized from Percent to Watts',()=>{
 const rows=triplet(),r=setup(rows);r.states['input_text.hpvc_pv1_limit_number'].state=rows[0].entity_id;r.states['input_select.hpvc_pv1_limit_unit'].state='Percent';
 const h=read(r);assert.equal(h.configuredInverters.length,1);assert.equal(h.configuredInverters[0].limit_unit,'Watts');
});
test('registry requests stay on separate 60s wiring and cache refresh handles rename/removal',()=>{
 const r=setup(),before=r.global.get('homePvControlEnphaseRegistry');discover(r);r.now+=10000;discover(r);assert.equal(r.global.get('homePvControlEnphaseRegistry'),before);
 assert.equal(by.hpvcenphaseregistrytimer157.repeat,'60');assert.equal(by.hpvcenphaseregistrytimer157.once,true);
 const reachable=new Set();function walk(id){if(reachable.has(id))return;reachable.add(id);for(const wire of by[id]?.wires||[])wire.forEach(walk);}walk('49ecf8749ba7c0be');assert(!reachable.has('hpvcenphaseregistryapi157'));
 const rows=triplet();rows[2].entity_id='switch.new_enable';r.states['switch.new_enable']={state:'on',attributes:{}};r.run(MAP,{payload:rows});assert.equal(discover(r)[0].enable_entity,'switch.new_enable');
 r.run(MAP,{payload:[]});assert.equal(discover(r).length,0);
 r.run(MAP,{payload:{error:'offline'}});assert.equal(r.global.get('homePvControlEnphaseRegistry').controllers.length,0);
});
test('maintenance watchers use renamed pairs and block unavailable or below-full readback',()=>{
 for(const id of ['eb9674e0d58dc6d1','b6d450b56fb931b3','6e1516a98c6391ee']){
  const rows=triplet(),r=setup(rows);r.states[rows[0].entity_id].state='1000';r.states['input_boolean.hpvc_enabled'].state='off';
  const out=r.run(id,{});assert(!out?.[0],id+' authorized below-full cleanup');
  r.states[rows[0].entity_id].state='unavailable';assert(!r.run(id,{})?.[0]);
 }
});
test('per-controller opt-out excludes one slot without renumbering another',()=>{
 const rows=[...triplet('a'),...triplet('b')],r=setup(rows);r.states['input_boolean.hpvc_pv1_control_disabled']={state:'on',attributes:{}};
 const h=read(r);assert.equal(h.inverterCount,2);assert.equal(h.configuredInverters.length,1);assert.equal(h.configuredInverters[0].slot,2);assert.equal(h.inverters[0].control_key,'pv2');
});
test('live opt-out suppresses an already-built DPEL write before the next cycle',()=>{
 const rows=triplet(),r=setup(rows),h=read(r);r.states['input_boolean.hpvc_pv1_control_disabled']={state:'on',attributes:{}};
 Object.assign(h,{halted:false,canChangePv:true,pvWriteLockActive:false,pvCalculationsSuspended:false,pvAction:'adjust',targets:[{entity:'pv1',target:2000,requested_target:2000,changed:true}]});
 r.run('7b758196fe8a7359',{hpvc:h});assert.equal(h.calls.length,0);
});
test('live opt-out cancels a queued main command after an in-flight pre-action',()=>{
 const r=new Runtime();r.states['input_select.hpvc_pv1_control_method'].state='Action/service';r.states['input_text.hpvc_pv1_action'].state='script.apply';r.states['input_text.hpvc_pv1_pre_actions_json'].state='[{"action":"script.prepare"}]';r.refresh();
 const m=r.cycle(),active=r.run('57dc0986bf249cd3',m.hpvc.outputs[0]);assert.equal(active.payload.action,'script.prepare');
 r.states['input_boolean.hpvc_pv1_control_disabled']={state:'on',attributes:{}};assert.equal(r.run('3f890e176d2b747b',active),null);
});
test('warm cached configuration reads controller opt-out on the next timer tick',()=>{
 const r=setup([...triplet('a'),...triplet('b')]);read(r);r.now+=10000;r.refresh();
 r.states['input_boolean.hpvc_pv1_control_disabled']={state:'on',attributes:{}};
 r.global.set('homePvControlRuntimeEvaluationLock',null);
 const h=r.run(READ,r.run(CORE,{topic:'timer'})).hpvc;
 assert.equal(h.configuredInverters.length,1);assert.equal(h.configuredInverters[0].slot,2);
});
test('all controllers opted out produce no inverter commands',()=>{
 const r=setup();r.states['input_boolean.hpvc_pv1_control_disabled']={state:'on',attributes:{}};
 const m=r.cycle();assert(m);assert.equal(m.hpvc.calls?.filter(c=>c.hpvcInverterWrite || /^(switch|select|number)\./.test(c.payload?.action||'')).length||0,0);
});
console.log(`${passed} Enphase registry/control-toggle regression groups passed`);
