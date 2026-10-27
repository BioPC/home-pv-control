#!/usr/bin/env node
const fs=require('fs');
const vm=require('vm');
const path=require('path');
const assert=require('assert');
const root=path.resolve(__dirname,'..');
const flow=JSON.parse(fs.readFileSync(path.join(root,'node-red','hpvc_flow.json'),'utf8'));
function fn(id){const n=flow.find(x=>x.id===id);if(!n)throw new Error('missing '+id);return n.func;}
function contextStore(seed={}){const m=new Map(Object.entries(seed));return {get:k=>m.get(k),set:(k,v)=>m.set(k,v),_m:m};}
function run(id,{msg={},globalSeed={},flowSeed={}}={}){
  const g=contextStore(globalSeed),f=contextStore(flowSeed);
  const sandbox={msg,global:g,flow:f,node:{status(){},warn(){},error(){}},Date,console,Buffer,setTimeout,clearTimeout};
  const script=new vm.Script(`(function(){${fn(id)}\n})()`);
  const result=script.runInNewContext(sandbox);
  return {result,msg,g,f};
}
function st(state,attributes={}){return {state:String(state),attributes};}

// Core discovery contract is represented literally in shipped function.
const core=fn('6498f50f6fea77b9');
assert(core.includes("/^number\\.(.+)_dpel_limit$/"));
assert(core.includes("_dpel_enabled"));
assert(core.includes("_dpel_mode"));
assert(core.includes("enphaseDpelControllers"));
assert(core.includes("!Array.isArray(options) || !options.includes('Production') || !options.includes('Export')"));
for (const id of ['eb9674e0d58dc6d1','b6d450b56fb931b3','6e1516a98c6391ee']) { const body=fn(id); assert(body.includes('_dpel_limit')); assert(body.includes('Enphase DPEL')); }

// Auto-detection must reuse an otherwise empty configured slot so an Enphase-only
// installation does not need a fake/manual inverter configuration.
const inverterStates={
  'input_number.hpvc_inverter_count':st('1'),
  'input_select.hpvc_pv1_control_method':st('Number entity'),
  'input_text.hpvc_pv1_limit_number':st(''),
  'input_text.hpvc_pv1_readback_entity':st(''),
  'input_text.hpvc_pv1_action':st(''),
  'input_select.hpvc_pv1_limit_unit':st('Watts'),
  'input_number.hpvc_pv1_full_limit':st('3680'),
  'input_number.hpvc_pv1_low_limit':st('0'),
  'input_number.hpvc_pv1_action_step':st('0'),
  'input_number.hpvc_pv1_refresh_seconds':st('0'),
  'number.envoy_123_dpel_limit':st('3000',{min:0,max:10000000000,step:1}),
  'switch.envoy_123_dpel_enabled':st('on'),
  'select.envoy_123_dpel_mode':st('Production',{options:['Production','Export']})
};
const read=run('8b490d1484a538d7',{msg:{hpvc:{now:100000,cycleStates:inverterStates,enphaseDpelControllers:[{stem:'envoy_123',limit_entity:'number.envoy_123_dpel_limit',enable_entity:'switch.envoy_123_dpel_enabled',mode_entity:'select.envoy_123_dpel_mode'}]}},globalSeed:{}}).msg.hpvc;
assert.strictEqual(read.configuredInverters.length,1);
assert.strictEqual(read.inverterCount,1);
assert.strictEqual(read.configuredInverters[0].slot,1);
assert.strictEqual(read.configuredInverters[0].adapter_kind,'enphase_dpel');
assert.strictEqual(read.configuredInverters[0].full_power,3680);
assert.strictEqual(read.configuredInverters[0].limit_entity,'number.envoy_123_dpel_limit');
assert.strictEqual(read.configuredInverters[0].minimum_power,0);
assert.strictEqual(read.configuredInverters[0].limit_max,10000000000,'native DPEL max stays a capability bound only');

// A manually configured DPEL number must be enriched as native Watts even if
// an older HPVC setup still says Percent. This is the upgrade regression that
// prevents a 2000 W target from being converted to 40 and written as 40 W.
// A currently discoverable DPEL entity remains auto-detected even when its mirrored helper fields are populated.
const manualPercentStates={
  'input_number.hpvc_inverter_count':st('1'),
  'input_select.hpvc_pv1_control_method':st('Number entity'),
  'input_text.hpvc_pv1_limit_number':st('number.envoy_123_dpel_limit'),
  'input_text.hpvc_pv1_readback_entity':st(''),
  'input_text.hpvc_pv1_action':st(''),
  'input_select.hpvc_pv1_limit_unit':st('Percent'),
  'input_number.hpvc_pv1_full_limit':st('5000'),
  'input_number.hpvc_pv1_low_limit':st('100'),
  'input_number.hpvc_pv1_action_step':st('0'),
  'input_number.hpvc_pv1_refresh_seconds':st('0'),
  'number.envoy_123_dpel_limit':st('3000',{min:0,max:5000,step:1}),
  'switch.envoy_123_dpel_enabled':st('on'),
  'select.envoy_123_dpel_mode':st('Production',{options:['Production','Export']})
};
const manual=run('8b490d1484a538d7',{msg:{hpvc:{now:100000,cycleStates:manualPercentStates,enphaseDpelControllers:[{stem:'envoy_123',limit_entity:'number.envoy_123_dpel_limit',enable_entity:'switch.envoy_123_dpel_enabled',mode_entity:'select.envoy_123_dpel_mode'}]}},globalSeed:{}}).msg.hpvc;
assert.strictEqual(manual.configuredInverters.length,1,'manual DPEL must be deduplicated');
assert.strictEqual(manual.configuredInverters[0].adapter_kind,'enphase_dpel');
assert.strictEqual(manual.configuredInverters[0].auto_detected,true,'a currently discoverable DPEL controller remains auto-detected after helper mirroring');
assert.strictEqual(manual.configuredInverters[0].limit_unit,'Watts');
assert.strictEqual(manual.configuredInverters[0].limit_unit_raw,'Watts');
assert.strictEqual(manual.configuredInverters[0].current_raw,3000);
assert.strictEqual(manual.configuredInverters[0].current,3000);
assert.strictEqual(manual.configuredInverters[0].limit_step,1);
assert.strictEqual(manual.configuredInverters[0].limit_min,0);
assert.strictEqual(manual.configuredInverters[0].limit_max,5000);
assert.strictEqual(manual.configuredInverters[0].full_power,5000);
assert.strictEqual(manual.configuredInverters[0].minimum_power,100);

// Mixed installations keep the existing normal number/OpenDTU controller and
// add Enphase as exactly one additional controller slot.
const mixedStates={
  'input_number.hpvc_inverter_count':st('1'),
  'input_select.hpvc_pv1_control_method':st('Number entity'),
  'input_text.hpvc_pv1_limit_number':st('number.hms_2000_4t_limit_nonpersistent_absolute'),
  'input_text.hpvc_pv1_readback_entity':st(''),
  'input_text.hpvc_pv1_action':st(''),
  'input_select.hpvc_pv1_limit_unit':st('Watts'),
  'input_number.hpvc_pv1_full_limit':st('2000'),
  'input_number.hpvc_pv1_low_limit':st('100'),
  'input_number.hpvc_pv1_action_step':st('0'),
  'input_number.hpvc_pv1_refresh_seconds':st('0'),
  'number.hms_2000_4t_limit_nonpersistent_absolute':st('1500',{min:100,max:2000,step:1}),
  'number.envoy_123_dpel_limit':st('3000',{min:0,max:5000,step:1}),
  'switch.envoy_123_dpel_enabled':st('on'),
  'select.envoy_123_dpel_mode':st('Production',{options:['Production','Export']})
};
const mixed=run('8b490d1484a538d7',{msg:{hpvc:{now:100000,cycleStates:mixedStates,enphaseDpelControllers:[{stem:'envoy_123',limit_entity:'number.envoy_123_dpel_limit',enable_entity:'switch.envoy_123_dpel_enabled',mode_entity:'select.envoy_123_dpel_mode'}]}},globalSeed:{}}).msg.hpvc;
assert.strictEqual(mixed.configuredInverters.length,2);
assert.strictEqual(mixed.configuredInverters[0].limit_entity,'number.hms_2000_4t_limit_nonpersistent_absolute');
assert.strictEqual(mixed.configuredInverters[0].adapter_kind,'generic');
assert.strictEqual(mixed.configuredInverters[1].limit_entity,'number.envoy_123_dpel_limit');
assert.strictEqual(mixed.configuredInverters[1].adapter_kind,'enphase_dpel');
assert.strictEqual(mixed.configuredInverters[1].slot,2);

// Build node must never issue a DPEL Watt write while mode is Export/off.
const buildMsg={hpvc:{halted:false,now:100000,canChangePv:true,pvWriteLockActive:false,pvCalculationsSuspended:false,pvAction:'adjust',reason:'test',cycleStates:{
  'number.envoy_123_dpel_limit':st('3000',{min:0,max:5000,step:1}),
  'switch.envoy_123_dpel_enabled':st('off'),
  'select.envoy_123_dpel_mode':st('Export',{options:['Production','Export']})
},inverters:[{slot:1,name:'PV1 Enphase',control_key:'pv1',control_method:'Number entity',limit_entity:'number.envoy_123_dpel_limit',limit_unit:'Watts',limit_step:1,limit_min:0,limit_max:5000,full_power:5000,minimum_power:0,current:3000,verification_available:true,adapter_kind:'enphase_dpel',dpel_enable_entity:'switch.envoy_123_dpel_enabled',dpel_mode_entity:'select.envoy_123_dpel_mode',pre_actions:[],post_actions:[]}],targets:[{entity:'pv1',target:2000,requested_target:2000,changed:true}]}};
const pre=run('7b758196fe8a7359',{msg:buildMsg,globalSeed:{homePvControlAdapterResync:{},homePvControlAdapterLastWriteAt:{},homePvControlActionCommandState:{}}}).msg.hpvc.calls;
assert.strictEqual(pre.filter(x=>x.hpvcInverterWrite).length,0,'unsafe DPEL Watt write escaped preflight');
assert(pre.some(x=>x.payload?.action==='switch.turn_on'));
assert(pre.some(x=>x.payload?.action==='select.select_option'&&x.payload?.data?.option==='Production'));

// Once Enabled + Production are observed, the normal Number entity path is used.
buildMsg.hpvc.cycleStates['switch.envoy_123_dpel_enabled']=st('on');
buildMsg.hpvc.cycleStates['select.envoy_123_dpel_mode']=st('Production',{options:['Production','Export']});
const ready=run('7b758196fe8a7359',{msg:buildMsg,globalSeed:{homePvControlAdapterResync:{pv1:true},homePvControlAdapterLastWriteAt:{},homePvControlActionCommandState:{}}}).msg.hpvc.calls;
const writes=ready.filter(x=>x.hpvcInverterWrite);
assert.strictEqual(writes.length,1);
assert.strictEqual(writes[0].payload.action,'number.set_value');
assert.strictEqual(writes[0].payload.target.entity_id,'number.envoy_123_dpel_limit');
assert.strictEqual(writes[0].payload.data.value,2000);
assert.strictEqual(writes[0].hpvcInverterWrite.adapterKind,'enphase_dpel');

// The enriched manual Percent configuration must now use the same direct Watt
// write path, not convert the target into a percent value.
const manualInv=manual.configuredInverters[0];
const manualWriteMsg={hpvc:{halted:false,now:100000,canChangePv:true,pvWriteLockActive:false,pvCalculationsSuspended:false,pvAction:'adjust',reason:'manual-upgrade-test',cycleStates:manualPercentStates,inverters:[manualInv],targets:[{entity:'pv1',target:2000,requested_target:2000,changed:true}]}};
const manualCalls=run('7b758196fe8a7359',{msg:manualWriteMsg,globalSeed:{homePvControlAdapterResync:{pv1:true},homePvControlAdapterLastWriteAt:{},homePvControlActionCommandState:{}}}).msg.hpvc.calls;
const manualWrites=manualCalls.filter(x=>x.hpvcInverterWrite);
assert.strictEqual(manualWrites.length,1);
assert.strictEqual(manualWrites[0].payload.data.value,2000,'manual DPEL Percent config must normalize to a 2000 W write');


// Runtime validation must keep the same strict DPEL contract as discovery:
// both Production and Export must remain advertised, and unavailable support
// entities must be treated as unavailable rather than as a writable adapter.
const validator=fn('5c38544d8b43e7a8');
assert(validator.includes("!Array.isArray(options) || !options.includes('Production') || !options.includes('Export')"));
assert(validator.includes("unavailableStates.has(enableState)"));
assert(validator.includes("unavailableStates.has(modeState)"));

// If the Envoy integration exists but its support entities are unavailable,
// HPVC must issue no switch/select preflight calls and no Watt write. It leaves
// the adapter on resync so normal recovery can retry after real states return.
const unavailableBuildMsg=JSON.parse(JSON.stringify(buildMsg));
unavailableBuildMsg.hpvc.cycleStates['switch.envoy_123_dpel_enabled']=st('unavailable');
unavailableBuildMsg.hpvc.cycleStates['select.envoy_123_dpel_mode']=st('unknown',{options:['Production','Export']});
const unavailableRun=run('7b758196fe8a7359',{msg:unavailableBuildMsg,globalSeed:{homePvControlAdapterResync:{},homePvControlAdapterLastWriteAt:{},homePvControlActionCommandState:{}}});
const unavailableCalls=unavailableRun.msg.hpvc.calls;
assert.strictEqual(unavailableCalls.length,0,'unavailable DPEL support entities must not generate futile service calls');
assert.strictEqual(unavailableRun.g.get('homePvControlAdapterResync').pv1,true,'unavailable DPEL adapter must remain marked for resync');

console.log('Enphase DPEL regression: PASS');
