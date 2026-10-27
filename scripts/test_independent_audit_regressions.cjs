const assert=require('node:assert/strict');
const {Runtime,by}=require('./control_test_runtime.cjs');
let passed=0;function test(name,fn){fn();passed++;console.log('PASS '+name);}
const WATCHERS=['eb9674e0d58dc6d1','b6d450b56fb931b3','6e1516a98c6391ee'];
function adapterPolicy(r){
 const keys=Object.keys(r.states).filter(key=>/^input_(?:text|number|select|boolean)\.hpvc_(?:pv\d+_|enabled$|auto_resume_pending$|external_release_request$|update_reload_required$|update_in_progress$|inverter_count$)/.test(key)).sort();
 return JSON.stringify([r.global.get('homePvControlUninstallShutdownActive')===true,...keys.map(key=>[key,String(r.states[key]?.state??'')])]);
}
function maintenanceReady(r){
 r.states['input_boolean.hpvc_enabled'].state='off';
 r.states['input_number.hpvc_inverter_count'].state='0';
 r.global.set('homePvControlUninstallShutdownStartedAt',r.now-1000);
 r.global.set('homePvControlUninstallShutdownLastEvaluationAt',r.now);
 r.global.set('homePvControlRuntimeEvaluationLock',null);
 r.global.set('homePvControlPendingWriteVerification',null);
 r.global.set('homePvControlAdapterScheduler',null);
 r.global.set('homePvControlAdapterRequests',{});
 r.global.set('homePvControlDisableRestoreState',null);
 r.global.set('homePvControlNegativePriceHbcOverride',null);
}
test('maintenance reads dedicated OpenDTU registry .controllers and refuses below-full auto controller',()=>{
 for(const id of WATCHERS){
  const r=new Runtime();r.refresh();maintenanceReady(r);
  const e='number.renamed_hoymiles_limit';
  r.states[e]={state:'500',attributes:{min:0,max:2250,step:1,unit_of_measurement:'W'},last_updated:new Date(r.now).toISOString()};
  r.global.set('homePvControlOpenDtuRegistry',{controllers:[{device_id:'od1',limit_entity:e}],registry_entities:[e],refreshed_at:r.now});
  r.global.set('homePvControlOpenDtuRatedPowerCache',{'device:od1':{max_power:2000,source:'OpenDTU API',updated_at:r.now}});
  const out=r.run(id,{});assert(!out?.[0],id+' incorrectly authorized maintenance');
 }
});
test('maintenance normalizes legacy manual Enphase Percent slot to native Watts',()=>{
 for(const id of WATCHERS){
  const r=new Runtime();r.refresh();maintenanceReady(r);
  r.states['input_number.hpvc_inverter_count'].state='1';
  const lim='number.envoy_old_dpel_limit', sw='switch.envoy_old_dpel_enabled', sel='select.envoy_old_dpel_mode';
  r.states['input_text.hpvc_pv1_limit_number'].state=lim;r.states['input_select.hpvc_pv1_limit_unit'].state='Percent';r.states['input_number.hpvc_pv1_full_limit'].state='100';
  r.states[lim]={state:'100',attributes:{min:0,max:3000,step:1,unit_of_measurement:'W'},last_updated:new Date(r.now).toISOString()};
  r.states[sw]={state:'on',attributes:{}};r.states[sel]={state:'Production',attributes:{options:['Production','Export']}};
  r.global.set('homePvControlEnphaseRegistry',{controllers:[{device_id:'ep1',limit_entity:lim,enable_entity:sw,mode_entity:sel}],registry_entities:[lim,sw,sel],refreshed_at:r.now});
  const out=r.run(id,{});assert(!out?.[0],id+' accepted 100 W as 100% full output');
 }
});
test('unresolved disable-restore obligation blocks maintenance even when rediscovery count is zero',()=>{
 for(const id of WATCHERS){
  const r=new Runtime();r.refresh();maintenanceReady(r);
  r.global.set('homePvControlDisableRestoreState',{active:true});
  const out=r.run(id,{});assert(!out?.[0],id+' ignored active disable-restore obligation');
 }
});
test('OpenDTU status request leaves HTTP method ownership to the configured Request node',()=>{
 const r=new Runtime();
 r.global.set('homePvControlOpenDtuRegistry',{controllers:[{device_id:'od1',configuration_url:'http://dtu'}]});
 const out=r.run('hpvcopendtustatusrequest157',{});
 assert(Array.isArray(out));assert.equal(out.length,1);assert(Array.isArray(out[0]));assert.equal(out[0].length,1);
 const request=out[0][0];assert.equal(request.url,'http://dtu/api/limit/status');
 assert.equal(Object.prototype.hasOwnProperty.call(request,'method'),false,'dynamic request must not override configured HTTP method');
});
test('OpenDTU API snapshot whose poll predates dispatch cannot confirm the later write',()=>{
 const r=new Runtime();r.refresh();
 const e='number.od_limit';r.states[e]={state:'3000',attributes:{min:0,max:3000,step:1,unit_of_measurement:'W'}};
 r.global.set('homePvControlPendingWriteVerification',{requested_ts:r.now-31000,checked:false,action:'limit',requested:[{entity:e,readback_entity:e,value:1500,before:3000,limit_unit:'Watts',adapter_kind:'opendtu_absolute',opendtu_device_id:'od1',dispatched_ts:r.now-30000}]});
 r.global.set('homePvControlOpenDtuLimitStatus',{'device:od1':{device_id:'od1',limit_entity:e,max_power:3000,limit_relative:50,limit_set_status:'Ok',poll_started_at:r.now-60000,received_at:r.now-1000}});
 const hpvc={now:r.now,cooldownSeconds:5,deadband:25,newInsights:[],outputs:Array(8).fill(null),cycleStates:r.states,pendingWriteRequest:null};
 r.run('1da749636a1dfe1b',{hpvc});
 const p=r.global.get('homePvControlPendingWriteVerification');assert.notEqual(p?.confirmed,true);assert.equal(p?.results?.[0]?.openDtuApiOk,false);
});
test('OpenDTU API poll started after dispatch may confirm matching command',()=>{
 const r=new Runtime();r.refresh();
 const e='number.od_limit';r.states[e]={state:'3000',attributes:{min:0,max:3000,step:1,unit_of_measurement:'W'}};
 r.global.set('homePvControlPendingWriteVerification',{requested_ts:r.now-31000,checked:false,action:'limit',requested:[{entity:e,readback_entity:e,value:1500,before:3000,limit_unit:'Watts',adapter_kind:'opendtu_absolute',opendtu_device_id:'od1',dispatched_ts:r.now-30000}]});
 r.global.set('homePvControlOpenDtuLimitStatus',{'device:od1':{device_id:'od1',limit_entity:e,max_power:3000,limit_relative:50,limit_set_status:'Ok',poll_started_at:r.now-20000,received_at:r.now-1000}});
 const hpvc={now:r.now,cooldownSeconds:5,deadband:25,newInsights:[],outputs:Array(8).fill(null),cycleStates:r.states,pendingWriteRequest:null};
 r.run('1da749636a1dfe1b',{hpvc});
 const p=r.global.get('homePvControlPendingWriteVerification');assert.equal(p?.confirmed,true);assert.equal(p?.results?.[0]?.openDtuApiOk,true);
});
test('OpenDTU discovery does not invalidate producer/dispatcher policy',()=>{
 const r=new Runtime();r.refresh();
 r.global.set('homePvControlOpenDtuEntities',['number.od_limit']);r.states['number.od_limit']={state:'1500',attributes:{min:0,max:2000,step:1}};
 r.global.set('homePvControlAdapterLatestGeneration',{pv1:1});
 const call={payload:{action:'number.set_value'},hpvcInverterWrite:{controlKey:'pv1',readbackEntity:'number.od_limit',entity:'number.od_limit',targetWatts:1000,adapterKind:'opendtu_absolute'},hpvcAdapterGeneration:1,hpvcAdapterPolicy:adapterPolicy(r)};
 const out=r.run('57dc0986bf249cd3',{payload:[call]});assert(out,'OpenDTU batch was rejected by dispatcher policy');assert.equal(out.hpvcAdapterCurrentControlKey,'pv1');
});
test('Enphase numeric readback update does not cancel another queued controller',()=>{
 const r=new Runtime();r.refresh();
 const lim1='number.ep1_dpel_limit',lim2='number.ep2_dpel_limit',sw1='switch.ep1_dpel_enabled',sw2='switch.ep2_dpel_enabled',md1='select.ep1_dpel_mode',md2='select.ep2_dpel_mode';
 for(const [id,state] of [[lim1,'3000'],[lim2,'3000'],[sw1,'on'],[sw2,'on'],[md1,'Production'],[md2,'Production']])r.states[id]={state,attributes:{}};
 r.global.set('homePvControlEnphaseDpelEntities',[lim1,sw1,md1,lim2,sw2,md2]);r.global.set('homePvControlAdapterLatestGeneration',{pv1:1,pv2:2});
 const policy=adapterPolicy(r);
 const mk=(key,lim,sw,md,target,generation)=>({payload:{action:'number.set_value'},hpvcInverterWrite:{controlKey:key,readbackEntity:lim,entity:lim,targetWatts:target,adapterKind:'enphase_dpel',dpelEnableEntity:sw,dpelModeEntity:md},hpvcAdapterGeneration:generation,hpvcAdapterPolicy:policy});
 const first=r.run('57dc0986bf249cd3',{payload:[mk('pv1',lim1,sw1,md1,2000,1),mk('pv2',lim2,sw2,md2,2200,2)]});assert(first);
 r.states[lim1].state='2000';
 const next=r.run('3f890e176d2b747b',first);assert(next,'normal Enphase readback update cancelled queued batch');assert.equal(next.hpvcAdapterCurrentControlKey,'pv2');
});
test('automatic Enphase slot honors configured minimum',()=>{
 const r=new Runtime();r.refresh();r.states['input_number.hpvc_inverter_count'].state='0';r.states['input_number.hpvc_pv1_low_limit'].state='500';
 const lim='number.ep_dpel_limit',sw='switch.ep_dpel_enabled',md='select.ep_dpel_mode';r.states[lim]={state:'2500',attributes:{min:0,max:4000,step:1}};r.states[sw]={state:'on',attributes:{}};r.states[md]={state:'Production',attributes:{options:['Production','Export']}};
 const hpvc={now:r.now,cycleStates:r.states,enphaseDpelControllers:[{limit_entity:lim,enable_entity:sw,mode_entity:md}],openDtuControllers:[]};
 const out=r.run('8b490d1484a538d7',{hpvc});assert.equal(out.hpvc.inverters.length,1);assert.equal(out.hpvc.inverters[0].minimum_power,500);
});
test('dispatchers attach actual dispatch timestamp to real logical pending record',()=>{
 const r=new Runtime();r.refresh();r.global.set('homePvControlAdapterLatestGeneration',{pv1:7});
 r.global.set('homePvControlPendingWriteVerification',{requested_ts:r.now-20000,checked:false,requested:[{entity:'pv1',readback_entity:'number.inv1',value:1500}]});
 const call={payload:{action:'number.set_value'},hpvcInverterWrite:{controlKey:'pv1',readbackEntity:'number.inv1',entity:'number.inv1',targetWatts:1500,adapterKind:'generic'},hpvcAdapterGeneration:7,hpvcAdapterPolicy:adapterPolicy(r)};
 const out=r.run('57dc0986bf249cd3',{payload:[call]});assert(out);const item=r.global.get('homePvControlPendingWriteVerification').requested[0];assert.equal(item.control_key,'pv1');assert.equal(item.dispatch_generation,7);assert.equal(item.dispatched_ts,r.now);
});
test('OpenDTU API rejects contradictory established serial',()=>{
 const r=new Runtime();const e='number.od_limit';r.global.set('homePvControlOpenDtuRegistry',{controllers:[{device_id:'od1',limit_entity:e,serial:'111111111111',configuration_url:'http://dtu'}]});
 const out=r.run('hpvcopendtustatuscache157',{statusCode:200,payload:{'222222222222':{max_power:8000,limit_relative:50,limit_set_status:'Ok'}},hpvcOpenDtuBaseUrl:'http://dtu',hpvcOpenDtuPollStartedAt:r.now-100});
 assert.equal(out,null);assert.equal(Object.keys(r.global.get('homePvControlOpenDtuRatedPowerCache')||{}).length,0);assert.equal(Object.keys(r.global.get('homePvControlOpenDtuLimitStatus')||{}).length,0);
});
test('flow removal accepts active restore lifecycle when auto OpenDTU is independently verified full',()=>{
 const r=new Runtime();r.refresh();maintenanceReady(r);
 const e='number.hms_2000_4t_limit_nonpersistent_absolute';
 r.states[e]={state:'2000',attributes:{min:0,max:2250,step:1,unit_of_measurement:'W'},last_updated:new Date(r.now).toISOString(),last_changed:new Date(r.now).toISOString()};
 r.global.set('homePvControlOpenDtuRegistry',{controllers:[{device_id:'od1',limit_entity:e}],registry_entities:[e],refreshed_at:r.now});
 r.global.set('homePvControlOpenDtuRatedPowerCache',{'device:od1':{max_power:2000,source:'OpenDTU API',updated_at:r.now}});
 r.global.set('homePvControlDisableRestoreState',{active:true,requestedAt:r.now-1000,obligations:[{key:'pv1',autoManaged:true}]});
 const out=r.run('b6d450b56fb931b3',{topic:'regression'});
 assert(out?.[0],'flow removal remained blocked by restore lifecycle despite independently verified full OpenDTU output');
});test('full uninstall accepts active restore lifecycle when auto OpenDTU is independently verified full',()=>{
 const r=new Runtime();r.refresh();maintenanceReady(r);
 const e='number.hms_2000_4t_limit_nonpersistent_absolute';
 r.states[e]={state:'2000',attributes:{min:0,max:2250,step:1,unit_of_measurement:'W'},last_updated:new Date(r.now).toISOString(),last_changed:new Date(r.now).toISOString()};
 r.global.set('homePvControlOpenDtuRegistry',{controllers:[{device_id:'od1',limit_entity:e}],registry_entities:[e],refreshed_at:r.now});
 r.global.set('homePvControlOpenDtuRatedPowerCache',{'device:od1':{max_power:2000,source:'OpenDTU API',updated_at:r.now}});
 r.global.set('homePvControlDisableRestoreState',{active:true,requestedAt:r.now-1000,obligations:[{key:'pv1',autoManaged:true}]});
 const out=r.run('6e1516a98c6391ee',{topic:'regression'});
 assert(out?.[0],'full uninstall remained blocked by restore lifecycle despite independently verified full OpenDTU output');
});
test('smart update accepts active restore lifecycle when auto OpenDTU is independently verified full',()=>{
 const r=new Runtime();r.refresh();maintenanceReady(r);
 const e='number.hms_2000_4t_limit_nonpersistent_absolute';
 r.states[e]={state:'2000',attributes:{min:0,max:2250,step:1,unit_of_measurement:'W'},last_updated:new Date(r.now).toISOString(),last_changed:new Date(r.now).toISOString()};
 r.global.set('homePvControlOpenDtuRegistry',{controllers:[{device_id:'od1',limit_entity:e}],registry_entities:[e],refreshed_at:r.now});
 r.global.set('homePvControlOpenDtuRatedPowerCache',{'device:od1':{max_power:2000,source:'OpenDTU API',updated_at:r.now}});
 r.global.set('homePvControlDisableRestoreState',{active:true,requestedAt:r.now-1000,obligations:[{key:'pv1',autoManaged:true}]});
 const out=r.run('eb9674e0d58dc6d1',{topic:'regression'});
 assert(out?.[0]?.hpvcUpdateAuthorized===true,'smart update remained blocked by restore lifecycle despite independently verified full OpenDTU output');
});


test('maintenance auto OpenDTU uses HA template last_reported proof like manual Number controllers after a completed restore write',()=>{
 for(const id of WATCHERS){
  const r=new Runtime();r.refresh();maintenanceReady(r);
  const e='number.hms_2000_4t_limit_nonpersistent_absolute';
  r.states[e]={state:'2000',attributes:{min:0,max:2250,step:1,unit_of_measurement:'W'},last_updated:new Date(r.now-600000).toISOString(),last_changed:new Date(r.now-600000).toISOString()};
  r.states['sensor.hpvc_source_freshness']={state:'ok',attributes:{freshness_transport:'ha_template_last_reported_snapshot',snapshot_epoch_ms:r.now,pv1_last_reported_ms:r.now}};
  r.global.set('homePvControlOpenDtuRegistry',{controllers:[{device_id:'od1',limit_entity:e}],registry_entities:[e],refreshed_at:r.now});
  r.global.set('homePvControlOpenDtuRatedPowerCache',{'device:od1':{max_power:2000,source:'OpenDTU API',updated_at:r.now}});
  r.global.set('homePvControlAdapterCompletedWrites',{pv1:{success:true,targetWatts:2000,startedAt:r.now-5000,completedAt:r.now-4000,preWriteFullConfirmed:false}});
  const out=r.run(id,{topic:'regression'});assert(out?.[0],id+' rejected fresh HA-template last_reported proof for auto OpenDTU');
 }
});
test('maintenance auto Enphase uses HA template last_reported proof like manual Number controllers after a completed restore write',()=>{
 for(const id of WATCHERS){
  const r=new Runtime();r.refresh();maintenanceReady(r);
  const lim='number.envoy_dpel_limit',sw='switch.envoy_dpel_enabled',md='select.envoy_dpel_mode';
  r.states[lim]={state:'3000',attributes:{min:0,max:3000,step:1,unit_of_measurement:'W'},last_updated:new Date(r.now-600000).toISOString(),last_changed:new Date(r.now-600000).toISOString()};
  r.states[sw]={state:'on',attributes:{}};r.states[md]={state:'Production',attributes:{options:['Production','Export']}};
  r.states['sensor.hpvc_source_freshness']={state:'ok',attributes:{freshness_transport:'ha_template_last_reported_snapshot',snapshot_epoch_ms:r.now,pv1_last_reported_ms:r.now}};
  r.global.set('homePvControlEnphaseRegistry',{controllers:[{device_id:'ep1',limit_entity:lim,enable_entity:sw,mode_entity:md}],registry_entities:[lim,sw,md],refreshed_at:r.now});
  r.global.set('homePvControlAdapterCompletedWrites',{pv1:{success:true,targetWatts:3000,startedAt:r.now-5000,completedAt:r.now-4000,preWriteFullConfirmed:false}});
  const out=r.run(id,{topic:'regression'});assert(out?.[0],id+' rejected fresh HA-template last_reported proof for auto Enphase');
 }
});

test('confirmed auto-controller write retires completed-write maintenance barrier',()=>{
 const r=new Runtime();r.refresh();
 const e='number.hms_2000_4t_limit_nonpersistent_absolute';
 r.states[e]={state:'2000',attributes:{min:0,max:2250,step:1,unit_of_measurement:'W'}};
 r.global.set('homePvControlAdapterCompletedWrites',{pv1:{success:true,targetWatts:2000,startedAt:r.now-6000,completedAt:r.now-5000,preWriteFullConfirmed:false}});
 r.global.set('homePvControlPendingWriteVerification',{requested_ts:r.now-6000,checked:false,action:'restore',requested:[{entity:'pv1',control_key:'pv1',readback_entity:e,value:2000,before:1500,limit_unit:'Watts',adapter_kind:'opendtu_absolute'}]});
 const hpvc={now:r.now,cooldownSeconds:60,deadband:25,newInsights:[],outputs:Array(8).fill(null),cycleStates:r.states,pendingWriteRequest:null};
 r.run('1da749636a1dfe1b',{hpvc});
 const pending=r.global.get('homePvControlPendingWriteVerification');assert.equal(pending?.confirmed,true,'restore write was not confirmed');
 assert.equal(Object.prototype.hasOwnProperty.call(r.global.get('homePvControlAdapterCompletedWrites')||{},'pv1'),false,'confirmed write left stale completed-write barrier');
});
test('historical completed auto write cannot re-block maintenance after pending verification is resolved',()=>{
 for(const id of WATCHERS){
  const r=new Runtime();r.refresh();maintenanceReady(r);
  const e='number.hms_2000_4t_limit_nonpersistent_absolute';
  r.states[e]={state:'2000',attributes:{min:0,max:2250,step:1,unit_of_measurement:'W'}};
  r.states['sensor.hpvc_source_freshness']={state:'ok',attributes:{freshness_transport:'ha_template_last_reported_snapshot',snapshot_epoch_ms:r.now,pv1_last_reported_ms:r.now-600000}};
  r.global.set('homePvControlOpenDtuRegistry',{controllers:[{device_id:'od1',limit_entity:e}],registry_entities:[e],refreshed_at:r.now});
  r.global.set('homePvControlOpenDtuRatedPowerCache',{'device:od1':{max_power:2000,source:'OpenDTU API',updated_at:r.now}});
  r.global.set('homePvControlAdapterCompletedWrites',{pv1:{success:true,targetWatts:2000,startedAt:r.now-5000,completedAt:r.now-4000,preWriteFullConfirmed:false}});
  r.global.set('homePvControlPendingWriteVerification',{requested_ts:r.now-5000,checked:true,confirmed:true,checked_ts:r.now-3000,requested:[{entity:'pv1',readback_entity:e,value:2000}]});
  const out=r.run(id,{topic:'regression'});assert(out?.[0],id+' re-blocked maintenance on historical completed write after verification was already resolved');
 }
});
console.log(`${passed} independent audit regression groups passed`);
