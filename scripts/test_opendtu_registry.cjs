const assert=require('node:assert/strict');
const {Runtime,by}=require('./control_test_runtime.cjs');
let passed=0;function test(name,fn){fn();passed++;console.log('PASS '+name);}
const MAP='hpvcenphaseregistrymap157',CACHE='hpvcopendtustatuscache157',CORE='6498f50f6fea77b9',READ='8b490d1484a538d7';
function odEntity(id='a',renamed=true,role='limit_nonpersistent_absolute'){
 return {device_id:'od_'+id,platform:'mqtt',config_entry_id:'mqtt_entry',
  entity_id:renamed?`number.garage_solar_controller_${id}`:`number.hms_2000_${role}`,
  unique_id:`11418200${id}_${role}`,original_name:role.split('_').map(x=>x[0].toUpperCase()+x.slice(1)).join(' ')};
}
function odDevice(id='a',over={}){return {id:'od_'+id,manufacturer:'Hoymiles',model:'HMS-2000-4T',name:'HMS '+id,identifiers:[['mqtt',`11418200000${String(id).replace(/\D/g,'').slice(-1)||'1'}`]],configuration_url:'http://192.0.2.10',...over};}
function stateFor(r,row,max=2000,value=1500){r.states[row.entity_id]={state:String(value),attributes:{min:10,max,step:10,unit_of_measurement:'W'},last_updated:new Date(r.now).toISOString(),last_changed:new Date(r.now).toISOString()};}
function setup(rows=[odEntity()],devices=[odDevice()]){
 const r=new Runtime();for(let i=1;i<=10;i++){r.states[`input_text.hpvc_pv${i}_limit_number`].state='';r.states[`input_number.hpvc_pv${i}_full_limit`].state='0';}
 rows.forEach(row=>stateFor(r,row));
 r.run(MAP,{hpvcEntityRegistryRows:rows,payload:devices});r.refresh();return r;
}
function discover(r){r.global.set('homePvControlRuntimeEvaluationLock',null);const m=r.run(CORE,{topic:'timer'});return m?.hpvc?.openDtuControllers||[];}
function read(r){r.global.set('homePvControlRuntimeEvaluationLock',null);return r.run(READ,r.run(CORE,{topic:'settings'})).hpvc;}

test('renamed OpenDTU Watt limiter is recognized by immutable role plus HA device metadata',()=>{
 const row=odEntity('a',true),r=setup([row],[odDevice('a')]);const c=discover(r);assert.equal(c.length,1);assert.equal(c[0].limit_entity,row.entity_id);
 r.global.set('homePvControlOpenDtuRatedPowerCache',{['entity:'+row.entity_id]:{max_power:2000,source:'OpenDTU API',updated_at:r.now}});r.refresh();
 const h=read(r);assert.equal(h.configuredInverters[0].adapter_kind,'opendtu_absolute');assert.equal(h.configuredInverters[0].limit_unit,'Watts');assert.equal(h.configuredInverters[0].full_power,2000);
});

test('non-OpenDTU MQTT device and persistent/relative entities are rejected',()=>{
 for(const [role,device] of [['limit_nonpersistent_absolute',odDevice('a',{manufacturer:'Other',model:'Generic MQTT',name:'Generic MQTT',identifiers:[['mqtt','generic_a']]})],['limit_persistent_absolute',odDevice('a')],['limit_nonpersistent_relative',odDevice('a')]]){
   const row=odEntity('a',true,role),r=setup([row],[device]);assert.equal(discover(r).length,0,role);
 }
});

test('official suffix fallback works only with Watt unit and positive native max when registry is unavailable',()=>{
 const row=odEntity('a',false),r=setup([],[]);stateFor(r,row);r.global.set('homePvControlOpenDtuRegistry',undefined);r.global.set('homePvControlEnphaseRegistry',undefined);r.refresh();assert.equal(discover(r).length,1);
 r.states[row.entity_id].attributes.unit_of_measurement='%';r.global.set('homePvControlRuntimeEvaluationLock',null);r.run(CORE,{topic:'settings'});r.now+=61000;r.refresh();assert.equal(discover(r).length,0);
});

test('manual OpenDTU number is deduplicated and old Percent configuration normalizes to native Watts',()=>{
 const row=odEntity(),r=setup([row],[odDevice()]);r.states['input_text.hpvc_pv1_limit_number'].state=row.entity_id;r.states['input_select.hpvc_pv1_limit_unit'].state='Percent';r.states['input_number.hpvc_pv1_full_limit'].state='2000';r.refresh();
 const h=read(r);assert.equal(h.configuredInverters.length,1);assert.equal(h.configuredInverters[0].adapter_kind,'opendtu_absolute');assert.equal(h.configuredInverters[0].limit_unit,'Watts');assert.equal(h.configuredInverters[0].current,1500);
});

test('several OpenDTU inverter devices occupy one slot each and remain bounded to ten',()=>{
 const rows=[],devices=[];for(let i=0;i<11;i++){const id=String(i).padStart(2,'0');rows.push(odEntity(id));devices.push(odDevice(id));}
 const r=setup(rows,devices);const cache={};rows.forEach(row=>cache['entity:'+row.entity_id]={max_power:2000,source:'OpenDTU API',updated_at:r.now});r.global.set('homePvControlOpenDtuRatedPowerCache',cache);r.refresh();const h=read(r);assert.equal(h.inverterCount,10);assert.equal(h.configuredInverters.length,10);assert.equal(h.openDtuOverflow.length,1);
});

test('mixed manual Number, Enphase and OpenDTU controllers keep independent slots',()=>{
 const od=odEntity('od'),epRows=['number','select','switch'].map((domain,i)=>({device_id:'ep',platform:'enphase_envoy',config_entry_id:'ep',entity_id:`${domain}.envoy_ep_${['dpel_limit','dpel_mode','dpel_enabled'][i]}`,unique_id:`ep_${['dpel_limit','dpel_mode','dpel_enabled'][i]}`,original_name:['DPEL Limit','DPEL Mode','DPEL'][i]}));
 const rows=[od,...epRows],devices=[odDevice('od'),{id:'ep',manufacturer:'Enphase',model:'Envoy'}],r=setup(rows,devices);r.global.set('homePvControlOpenDtuRatedPowerCache',{['entity:'+od.entity_id]:{max_power:2000,source:'OpenDTU API',updated_at:r.now}});
 r.states['number.manual_limit']={state:'500',attributes:{min:0,max:1000,step:10,unit_of_measurement:'W'}};r.states['input_text.hpvc_pv1_limit_number'].state='number.manual_limit';
 r.states[epRows[0].entity_id]={state:'1000',attributes:{min:0,max:3000,step:1,unit_of_measurement:'W'}};r.states[epRows[1].entity_id]={state:'Production',attributes:{options:['Production','Export']}};r.states[epRows[2].entity_id]={state:'on',attributes:{}};r.refresh();
 const h=read(r);assert.equal(h.configuredInverters.length,3);assert.equal(Array.from(h.configuredInverters,x=>x.adapter_kind).join(','),'generic,enphase_dpel,opendtu_absolute');
});

test('per-controller opt-out excludes auto OpenDTU from limiting but retains effective slot count',()=>{
 const r=setup();r.states['input_number.hpvc_pv1_full_limit'].state='2000';r.refresh();r.states['input_boolean.hpvc_pv1_control_disabled']={state:'on',attributes:{}};const h=read(r);assert.equal(h.inverterCount,1);assert.equal(h.configuredInverters.length,0);assert.equal(Array.from(h.disabledControllers).join(','),'pv1');
});

test('maintenance verification includes auto OpenDTU and blocks below-full or unavailable readback',()=>{
 for(const id of ['eb9674e0d58dc6d1','b6d450b56fb931b3','6e1516a98c6391ee']){
   const row=odEntity(),r=setup([row],[odDevice()]);r.states['input_number.hpvc_pv1_full_limit'].state='2000';r.refresh();r.states['input_boolean.hpvc_enabled'].state='off';r.states[row.entity_id].state='1000';assert(!r.run(id,{})?.[0],id+' authorized below-full');r.states[row.entity_id].state='unavailable';assert(!r.run(id,{})?.[0],id+' authorized unavailable');
 }
});


test('OpenDTU API max_power overrides an inflated HA Number max and is published into the shared registry',()=>{
 const row=odEntity('1',true),device=odDevice('1'),r=setup([row],[device]);
 r.states[row.entity_id].attributes.max=2250;
 const registry=r.global.get('homePvControlOpenDtuRegistry');
 assert.equal(registry.controllers[0].configuration_url,'http://192.0.2.10');
 r.run(CACHE,{statusCode:200,hpvcOpenDtuBaseUrl:'http://192.0.2.10',payload:{'114182000001':{limit_relative:75,max_power:2000,limit_set_status:'Ok'}}});
 r.refresh();
 const h=read(r),inv=h.configuredInverters[0];
 assert.equal(inv.full_power,2000);assert.equal(inv.full_power_source,'OpenDTU API');
 const shared=r.global.get('homePvControlEnphaseRegistry');assert.equal(shared.opendtu_controllers[0].max_power,2000);
});

test('cached OpenDTU rated power survives API loss, then manual Full limit beats native Number max',()=>{
 const row=odEntity('1',true),r=setup([row],[odDevice('1')]);r.states[row.entity_id].attributes.max=2250;
 r.global.set('homePvControlOpenDtuRatedPowerCache',{['entity:'+row.entity_id]:{max_power:2000,source:'OpenDTU API',updated_at:r.now}});r.refresh();
 let h=read(r);assert.equal(h.configuredInverters[0].full_power,2000);
 r.global.set('homePvControlOpenDtuRatedPowerCache',{});r.global.set('homePvControlOpenDtuLimitStatus',{});
 r.states['input_text.hpvc_pv1_limit_number'].state=row.entity_id;r.states['input_number.hpvc_pv1_full_limit'].state='1900';r.refresh();
 h=read(r);assert.equal(h.configuredInverters[0].full_power,1900);assert.equal(h.configuredInverters[0].full_power_source,'HPVC manual Full limit');
});

test('native HA Number max is never used as OpenDTU rated power; manual Full Limit activates control',()=>{
 const row=odEntity('1',true),r=setup([row],[odDevice('1')]);r.states[row.entity_id].attributes.max=2250;r.refresh();
 let h=read(r);assert.equal(h.configuredInverters.filter(x=>x.adapter_kind==='opendtu_absolute').length,0);assert.equal(h.openDtuFullLimitRequired.length,1);assert.equal(h.openDtuFullLimitRequired[0].reason,'Full Limit required');
 r.states['input_number.hpvc_pv1_full_limit'].state='2000';r.refresh();h=read(r);
 assert.equal(h.configuredInverters.length,1);assert.equal(h.configuredInverters[0].full_power,2000);assert.equal(h.configuredInverters[0].full_power_source,'HPVC manual Full limit');
});


test('maintenance uses OpenDTU API/cache/manual rated-power precedence and never native Number max',()=>{
 for(const id of ['eb9674e0d58dc6d1','b6d450b56fb931b3','6e1516a98c6391ee']){
   const func=by[id].func;
   assert(func.includes("homePvControlOpenDtuRatedPowerCache"),id+' missing rated cache');
   assert(func.includes("homePvControlOpenDtuLimitStatus"),id+' missing API status cache');
   assert(func.includes("Full Limit required"),id+' missing Full Limit required guard');
   assert(func.includes("numericState(liveEntity, slot, false, true, entry.fullPower)"),id+' does not verify against resolved full power');
   assert(!func.includes("entry.fullPower=max;"),id+' still trusts native Number max as rated power');
 }
});

test('OpenDTU verification code uses API Ok evidence and a 300 second failure floor',()=>{
 const verify=by[Object.keys(by).find(id=>by[id]?.name==='Verify Inverter Write Results')].func;
 assert(verify.includes("hasOpenDtuWrite?300000:120000"));
 assert(verify.includes("limit_set_status"));assert(verify.includes("openDtuApiOk"));
 const build=by[Object.keys(by).find(id=>by[id]?.name==='Build Inverter Limit Service Calls')].func;
 assert(build.includes("adapterKind:String(inv.adapter_kind||'generic')"));
});

test('registry refresh wiring remains outside the 10-second control path and fetches device registry',()=>{
 assert.equal(by.hpvcenphaseregistrytimer157.repeat,'60');assert.equal(by.hpvcpvregistrydeviceapi157?.type,'ha-api');
 const reachable=new Set();function walk(id){if(reachable.has(id))return;reachable.add(id);for(const wire of by[id]?.wires||[])wire.forEach(walk);}walk('49ecf8749ba7c0be');assert(!reachable.has('hpvcenphaseregistryapi157'));assert(!reachable.has('hpvcpvregistrydeviceapi157'));assert(!reachable.has('hpvcopendtustatusapi157'));assert.equal(by.hpvcopendtustatustimer157.repeat,'30');
});

test('registry refresh preserves trusted cached rated power for dashboard locking',()=>{
 const row=odEntity('1',true),device=odDevice('1'),r=setup([row],[device]);
 r.global.set('homePvControlOpenDtuRatedPowerCache',{['entity:'+row.entity_id]:{max_power:2000,source:'OpenDTU API',updated_at:r.now}});
 r.run(MAP,{hpvcEntityRegistryRows:[row],payload:[device]});
 const shared=r.global.get('homePvControlEnphaseRegistry');
 assert.equal(shared.opendtu_controllers[0].max_power,2000);
 assert.match(String(shared.opendtu_controllers[0].max_power_source),/OpenDTU API/);
});


test('already-full OpenDTU restore can prove maintenance without a newer unchanged HA timestamp',()=>{
 const BUILD='7b758196fe8a7359';
 const row=odEntity('1',true),r=setup([row],[odDevice('1')]);
 r.global.set('homePvControlOpenDtuRatedPowerCache',{['entity:'+row.entity_id]:{max_power:2000,source:'OpenDTU API',updated_at:r.now}});
 r.states[row.entity_id].state='2000'; r.states[row.entity_id].last_updated=new Date(r.now-1000).toISOString();
 r.states[row.entity_id].last_changed=new Date(r.now-1000).toISOString(); r.refresh();
 const hpvc={halted:false,now:r.now,deadband:25,canChangePv:true,pvWriteLockActive:false,pvCalculationsSuspended:false,pvAction:'restore',recoveryRebalanceAuthorized:false,
  cycleStates:r.states,inverters:[{slot:1,control_key:'pv1',name:'PV1',control_method:'Number entity',limit_entity:row.entity_id,readback_entity:row.entity_id,
   limit_unit:'Watts',full_power:2000,minimum_power:0,current:2000,current_source:'readback',adapter_kind:'opendtu_absolute',limit_step:1,refresh_seconds:0}],
  targets:[{entity:'pv1',target:2000,requested_target:2000,write_value_watts:2000,changed:true}]};
 const built=r.run(BUILD,{hpvc}); const write=built.hpvc.calls.find(x=>x.hpvcInverterWrite)?.hpvcInverterWrite;
 assert(write,'missing generated OpenDTU write'); assert.equal(write.preWriteFullConfirmed,true); assert.equal(write.preWriteObservedAtMs,r.now);
 // Model a successful redundant set_value(2000) where the native cached state timestamp
 // does not change; HA-template last_reported proof remains authoritative.
 r.global.set('homePvControlAdapterCompletedWrites',{pv1:{generation:1,startedAt:r.now+1000,completedAt:r.now+1500,targetWatts:2000,success:true,
  preWriteFullConfirmed:true,preWriteObservedAtMs:write.preWriteObservedAtMs}});
 r.states['input_boolean.hpvc_enabled'].state='off';
 r.global.set('homePvControlUninstallShutdownStartedAt',r.now-1000);
 r.global.set('homePvControlUninstallShutdownLastEvaluationAt',r.now);
 r.global.set('homePvControlDisableRestoreState',null); r.global.set('homePvControlPendingWriteVerification',null); r.global.set('homePvControlAdapterScheduler',null);
 for(const id of ['eb9674e0d58dc6d1','b6d450b56fb931b3','6e1516a98c6391ee']){
   r.global.set('homePvControlUninstallShutdownActive',true);
   const out=r.run(id,{topic:'regression'}); assert(out?.[0],id+' rejected independently confirmed already-full OpenDTU state');
 }
});

test('old full OpenDTU state still cannot prove a real restore without pre-write full confirmation',()=>{
 const row=odEntity('1',true),r=setup([row],[odDevice('1')]);
 r.global.set('homePvControlOpenDtuRatedPowerCache',{['entity:'+row.entity_id]:{max_power:2000,source:'OpenDTU API',updated_at:r.now}});
 r.states[row.entity_id].state='2000'; r.states[row.entity_id].last_updated=new Date(r.now-10000).toISOString();
 r.states[row.entity_id].last_changed=new Date(r.now-10000).toISOString(); r.states['input_boolean.hpvc_enabled'].state='off'; r.refresh();
 r.global.set('homePvControlAdapterCompletedWrites',{pv1:{generation:1,startedAt:r.now-1000,completedAt:r.now,targetWatts:2000,success:true,
  preWriteFullConfirmed:false,preWriteObservedAtMs:NaN}});
 for(const id of ['eb9674e0d58dc6d1','b6d450b56fb931b3','6e1516a98c6391ee']) assert(!r.run(id,{topic:'regression'})?.[0],id+' accepted stale full state without pre-write proof');
});

console.log(`${passed} OpenDTU registry regression groups passed`);
