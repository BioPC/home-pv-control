// Original v1.6 Function nodes; fake HA/context and explicit simulated acceptance only.
const fs=require('fs'),path=require('path'),crypto=require('crypto'),zlib=require('zlib');
const {Runtime,by}=require('../tests/policy_oracle_runtime.cjs');
const ROOT=path.resolve(__dirname,'..'),N=1800000000000;
const sequences=[];
const battery=(x={})=>Object.assign({soc:50,power:0,max:2000,charge_cutoff:100,discharge_cutoff:10,mode:'enable',power_age:0,soc_age:0},x);
function add(name,config,steps){sequences.push({name,config:Object.assign({permission:true,enabled:true,negative_charge:true,grid:0,pv:1500,market:-.01,all_in:.1,strategy:'Self Consumption',execution:'Charge',goal:'adaptive',count:1,priority:1,full:3000,current:1000,minimum:0,batteries:[battery()]},config),steps});}
add('request-response-active',{},[{at:0,accept_release:true},{at:5,batteries:[{power:-30}]},{at:15,batteries:[{power:-50}]},{at:20,batteries:[{power:-25}]},{at:25,batteries:[{power:-24}]},{at:39},{at:40},{at:41}]);
add('persistent-export',{},[{at:0,batteries:[{power:-100}],accept_release:true},{at:5,grid:-300},{at:20},{at:34},{at:35},{at:40}]);
add('delayed-response',{},[{at:0,accept_release:true},{at:14},{at:15},{at:16,batteries:[{power:-49}]},{at:17,batteries:[{power:-50}]}]);
add('health-disappearance-recovery',{},[{at:0,batteries:[{power:-100}]},{at:10,batteries:[{power:null,soc:null}]},{at:20,batteries:[{power:-100,soc:50}]},{at:79},{at:80}]);
add('taper-fresh-learning',{batteries:[battery({soc:91,power:-200})]},[{at:0},{at:59},{at:60,accept_release:true},{at:65,batteries:[{power:-250}]},{at:70,batteries:[{power:-320}]},{at:80}]);
add('taper-per-battery-delayed',{count:2,batteries:[battery({soc:93,power:-200}),battery({soc:95,power:-100})]},[{at:0},{at:60,accept_release:true},{at:70,batteries:[{power:-260},{hold_power:true}]},{at:80,batteries:[{power:-260},{power:-160}]},{at:100}]);
add('taper-contaminated',{batteries:[battery({soc:94,power:-100})]},[{at:0},{at:60,accept_release:true},{at:70,batteries:[{power:-1000}]},{at:130,accept_release:true},{at:140,batteries:[{power:-2000}]}]);
add('taper-export-failure',{batteries:[battery({soc:96,power:0})]},[{at:0,accept_release:true},{at:10,grid:-100,batteries:[{power:0}]},{at:11},{at:1810,grid:0,batteries:[{power:0}]},{at:1811}]);
add('taper-export-contaminated',{batteries:[battery({soc:91,power:0})]},[{at:0,accept_release:true},{at:10,grid:-1000,batteries:[{power:-1000}]},{at:20,grid:0},{at:80}]);
add('stale-post-write-timeout',{batteries:[battery({soc:92,power:0})]},[{at:0,accept_release:true},{at:10,batteries:[{hold_power:true}]},{at:180,batteries:[{hold_power:true}]},{at:181,batteries:[{hold_power:true}]}]);
add('maximum-memory-expiry',{},[{at:0},{at:1,batteries:[{max:null}]},{at:1800},{at:1801},{at:1810,batteries:[{max:1000}]}]);
add('malformed-live-max-no-fallback',{},[{at:0},{at:1,batteries:[{max:'bad'}]},{at:2,batteries:[{max:0}]},{at:3,batteries:[{max:-1}]},{at:4,batteries:[{max:null}]}]);
add('negative-override-entry-exit',{},[{at:0,all_in:0},{at:1,accept_override:true},{at:6,accept_override:true},{at:11},{at:20,all_in:.1,accept_override:true},{at:25,accept_override:true},{at:30}]);
add('negative-no-durable-capture',{},[{at:0,all_in:-.1,durable:false},{at:10,durable:false},{at:20,durable:false},{at:30,all_in:.1}]);
add('negative-permission-revoked',{},[{at:0,all_in:0},{at:5,accept_override:true},{at:10,accept_override:true},{at:15},{at:20,negative_charge:false,accept_override:true},{at:25,accept_override:true},{at:30}]);
add('negative-unknown-previous',{strategy:'Charge',goal:'batteries are full'},[{at:0,all_in:0},{at:10},{at:300}]);
add('negative-unavailable-price-freeze',{},[{at:0,all_in:0},{at:5,accept_override:true},{at:10,all_in:null},{at:20},{at:30,all_in:.1,accept_override:true}]);
add('negative-retry-fault',{},[{at:0,all_in:0},{at:5,accept_override:false},{at:6},{at:300},{at:305}]);
add('priority-rotation',{count:3,priority:2,batteries:[battery({soc:50}),battery({soc:92,power:0}),battery({soc:100})]},[{at:0},{at:10,priority:4},{at:20,priority:5}]);
for(const soc of [89,90,91,92,93,94,95,96,97,98,99,100])add('soc-band-'+soc,{batteries:[battery({soc,power:-200})]},[{at:0},{at:60},{at:61,accept_release:true},{at:75,batteries:[{power:-260}]}]);
for(const power of [-50,-49,-25,-24,0,24,25])add('charge-threshold-'+power,{batteries:[battery({power})]},[{at:0},{at:10,batteries:[{power:-24}]},{at:29},{at:30}]);
for(const count of [null,0,1,6,'bad',1.5,7,-1])add('count-'+count,{count,batteries:Array.from({length:6},()=>battery())},[{at:0},{at:10}]);
for(const mode of ['enable','disable','unknown'])add('control-'+mode,{batteries:[battery({mode})]},[{at:0},{at:60}]);
for(const ages of [[8000,8000],[8000,0],[0,8000],[301,8000],[121,8000]])add('freshness-'+ages.join('-'),{batteries:[battery({power:-100,power_age:ages[0],soc_age:ages[1]})]},[{at:0},{at:60}]);
add('full-cutoff-idle-old',{batteries:[battery({soc:100,power:0,power_age:100000,soc_age:100000})]},[{at:0},{at:10}]);
add('below-90-large-step',{full:10000,current:1000,batteries:[battery({max:5000})]},[{at:0},{at:10,grid:-100},{at:20,grid:-151}]);
add('below-90-reversal',{full:10000,current:1000,batteries:[battery({max:5000})],last_delta:-5000,last_age:10},[{at:0},{at:181}]);
add('taper-three-failures-recovery',{batteries:[battery({soc:92,power:-200})]},[{at:0},{at:60,accept_release:true},{at:70},{at:100,accept_release:true},{at:110},{at:170,accept_release:true},{at:180},{at:200,batteries:[{power:-260}]},{at:260}]);
add('band-independent-expiry',{batteries:[battery({soc:91,power:-200})]},[{at:0},{at:60,accept_release:true},{at:70,batteries:[{power:-300}]},{at:80,batteries:[{soc:95,power:-100}]},{at:172870},{at:172871}]);
for(const value of [null,'unavailable'])add('strategy-'+value,{strategy:value},[{at:0},{at:60}]);
for(const value of [null,'unknown'])add('execution-'+value,{execution:value},[{at:0},{at:60}]);
let seed=20261028;const random=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/2**32;};
for(let i=0;i<40;i++){const count=1+Math.floor(random()*6);add('seeded-batteries-'+i,{count,priority:1+Math.floor(random()*(count+1)),grid:Math.floor(random()*500)-200,batteries:Array.from({length:count},()=>battery({soc:Math.floor(random()*100),power:-Math.floor(random()*1500),max:2000}))},[{at:0},{at:60},{at:61,accept_release:true},{at:75}]);}
const STAGES=['58833ecba048acdd','0654673fc23c82a6','7fa0a525dfbdd47e','d66e2ee2bc26d3cc','234f3db1a3db2269','e011a45d7d27345e','9c50539b2e2d7fa4','a7df14169cc2e947','4e29c5113e825239'];
function sourceStep(r,c,at){
 const inv={name:'PV1',slot:1,control_key:'pv1',entity:'number.inv1',limit_entity:'number.inv1',current:c.current,full_power:c.full,minimum_power:c.minimum,control_method:'Number entity',limit_unit:'Watts',configuration_valid:true};
 let msg={hpvc:{now:r.now,cycleId:at+1,cycleStates:r.states,enabled:c.enabled,notify:false,hbcControlRequested:c.permission,negativePriceHbcCharge:c.negative_charge,hbcStrategyEntity:'input_select.house_battery_strategy',marketEntity:'sensor.market',allInEntity:'sensor.allin',market:c.market??0,marketValid:c.market!==null,allIn:c.all_in??0,allInValid:c.all_in!==null,grid:c.grid,pvPower:c.pv,pvPowerValid:c.pv!==null,pvPowerFresh:true,limitingPrice:0,hysteresis:.02,pvRestorePrice:.02,exportStart:-150,exportTarget:0,importRecalc:150,minPvPower:100,nightRestorePower:10,cooldownSeconds:30,deadband:25,thresholdConfigurationValid:true,halted:false,inverters:[inv],configuredInverters:[inv],unavailableInverters:[],totalFull:c.full,totalMin:c.minimum,newInsights:[],targets:[],calls:[],outputs:Array(8).fill(null),disableRestoreRequested:!c.enabled}};
 for(const id of STAGES){const out=r.run(id,msg);msg=Array.isArray(out)?out[0]:out;}
 return msg;
}
function profile(r,now){
 const max=r.global.get('homePvControlBatteryMaxChargePowers')?.batteries||{},taper=r.global.get('homePvControlBatteryTaperProfiles')?.batteries||{},cutoffs=r.global.get('homePvControlBatteryCutoffMemory')?.batteries||{};
 const indexes=new Set([...Object.keys(max),...Object.keys(taper),...Object.keys(cutoffs)]);const out={};
 for(const index of indexes){const bands={};for(const [key,b] of Object.entries(taper[index]?.bands||{})){bands[key]={ceiling:b.ceiling??null,samples:b.samples||0,result:b.lastProbeResult||'',failures:b.failureCount||0,contamination:b.contaminationCount||0,recovery:!!b.requiresRecovery,last_power:b.lastPower??null,stable_age:b.stableSince?Math.max(0,(now-b.stableSince)/1000):0,failure_remaining:Math.max(0,((b.probeBlockedUntil||0)-now)/1000),contamination_remaining:Math.max(0,((b.contaminationBlockedUntil||0)-now)/1000),idle_remaining:Math.max(0,((b.idleProbeBlockedUntil||0)-now)/1000),last_seen_age:b.lastSeenTs?(now-b.lastSeenTs)/1000:null,last_probe_age:b.lastProbeTs?(now-b.lastProbeTs)/1000:null,ratio:b.lastAbsorbedRatio??null,expected_share:b.lastExpectedStepShare||0,export_increase:b.lastExportIncrease||0,contaminated_delta:b.lastContaminatedDelta??null,contaminated_limit:b.lastContaminatedLimit??null};}out[index]={maximum:max[index]?.value??null,max_age:max[index]?Math.max(0,(now-max[index].updated)/1000):null,charging_cutoff:cutoffs[index]?.charging??null,discharging_cutoff:cutoffs[index]?.discharging??null,bands};}return out;
}
function run(sequence){
 const r=new Runtime(),c=JSON.parse(JSON.stringify(sequence.config)),records=[];const oldStamps={};
 for(let j=0;j<sequence.steps.length;j++){
  const step=sequence.steps[j],at=step.at;r.now=N+at*1000;
  for(const [k,v] of Object.entries(step))if(!['at','batteries','accept_release','accept_override','durable'].includes(k))c[k]=v;
  if(step.batteries)step.batteries.forEach((b,i)=>{c.batteries[i]=Object.assign(c.batteries[i]||battery(),b);});
  const entities=[];const put=(id,value,options=[],stamp=r.now,heartbeat=null)=>{if(value===null)return;const e={entity_id:id,state:String(value),updated_at_utc:stamp/1000,heartbeat_at_utc:heartbeat,options};entities.push(e);r.states[id]={state:e.state,attributes:{options},last_updated:new Date(stamp).toISOString()};};
  r.states={};r.global.set('homeassistant.homeAssistant.states',r.states);
  put('input_select.house_battery_strategy',c.strategy,['Self Consumption','Charge','Charge PV']);put('input_select.house_battery_strategy_charge_goal',c.goal,['adaptive','batteries are full']);put('input_text.house_battery_strategy_active_sub_strategy',c.execution);put('input_number.house_battery_count',c.count);put('input_number.house_battery_control_prioritize_battery',c.priority);put('sensor.market',c.market);put('sensor.allin',c.all_in);
  c.batteries.forEach((b,i)=>{const n=i+1,stamp=b.hold_power&&oldStamps[n]!==undefined?oldStamps[n]:r.now-(b.power_age||0)*1000;oldStamps[n]=stamp;put(`sensor.marstek_m${n}_ac_power`,b.power,[],stamp);put(`sensor.marstek_m${n}_battery_state_of_charge`,b.soc,[],r.now-(b.soc_age||0)*1000);put(`input_number.marstek_m${n}_charging_cutoff_capacity`,b.charge_cutoff);put(`input_number.marstek_m${n}_discharging_cutoff_capacity`,b.discharge_cutoff);put(`select.marstek_m${n}_rs485_control_mode`,b.mode);put(`number.marstek_m${n}_max_charge_power`,b.max);});
  if(c.last_delta)r.global.set('homePvControlLastPvCommand',{delta:c.last_delta,ts:N-(c.last_age||0)*1000,verification:'verified'});
  const msg=sourceStep(r,c,at),h=msg.hpvc,diagnostic=h.chargePriorityDiagnostics||{};
  const expected={valid:h.hbcPriorityConfigurationValid,control:h.controlHbc,order:h.hbcBatteryOrder,state:h.chargePriorityState,display:h.hbcChargePriorityDisplayState,normal:h.selectedBatteryNormalAvailableChargePower||0,taper:h.selectedBatteryTaperAvailableChargePower||0,total:h.selectedBatteryPowerTotal||0,enter:!!h.batteryChargingEnterConfirmed,remain:!!h.batteryChargingRemainConfirmed,engaged:!!h.hbcChargePriority,increase:h.hbcChargePriorityIncrease||0,unshaped:h.chargePriorityUnshapedIncrease||0,cap:diagnostic.stepCap||0,target:h.hbcChargePriorityTarget,response:(diagnostic.responseWindowRemainingMs||0)/1000,transition:(diagnostic.transitionSettleRemainingMs||0)/1000,exit:(diagnostic.exitHoldRemainingMs||0)/1000,export_age:(diagnostic.persistentExportAgeMs||0)/1000,suppressed:!!h.hbcExportLimitingSuppressed,fallback:!!h.hbcExportFallbackActive,large:!!h.chargePriorityLargeStepDamped,reversal:!!h.chargePriorityReversalDamped,override_phase:r.global.get('homePvControlNegativePriceHbcOverride')?.phase||'inactive',override_previous_strategy:r.global.get('homePvControlNegativePriceHbcOverride')?.previousStrategy||null,override_previous_goal:r.global.get('homePvControlNegativePriceHbcOverride')?.previousChargeGoal||null,override_actions:(h.hbcNegativeOverrideCalls||[]).filter(x=>['enter_strategy','enter_goal','restore_goal','restore_strategy'].includes(x.step)).map(x=>({step:x.step,entity:x.payload.target.entity_id,option:x.payload.data.option})),batteries:(h.hbcBatterySummary?.batteries||[]).map(b=>({i:b.index,status:b.status,maximum:b.maxChargePower,max_source:b.maxChargeSource,eligible:!!b.priorityEligible,headroom:b.rawHeadroom,normal:b.normalHeadroom,taper:b.taperReleaseAllowance,effective:b.effectiveChargeCeiling,learned:b.learnedTaperCeiling,band:b.taperBand,probe:!!b.taperProbeEligible,awaiting:!!b.taperAwaitingConfirmation,idle:!!b.idleStartupProbe,stable:b.taperStableSeconds,freshness:b.freshnessMode,usable:!!b.telemetryUsable,power_fresh:!!b.powerFresh,soc_fresh:!!b.socFresh})),memory:profile(r,r.now),paused:!!h.hbcSafetyPaused,recovering:!!h.hbcSafetyRecovering,
probe:(()=>{const p=r.global.get('homePvControlBatteryTaperProbe');return p?{step:p.step,export_before:p.exportBefore,age:(r.now-p.ts)/1000,batteries:p.batteries.map(b=>({i:b.index,band:b.band,charging:b.chargingPower,ceiling:b.effectiveCeiling,share:b.expectedStepShare,updated:b.powerUpdatedMs/1000,idle:!!b.idleStartupProbe}))}:null;})()};
  const input={at,entities,permission:c.permission,enabled:c.enabled,negative_charge:c.negative_charge,grid:c.grid,pv:c.pv,market:c.market,all_in:c.all_in,full:c.full,current:c.current,minimum:c.minimum,accept_release:!!step.accept_release,accept_override:!!step.accept_override,durable:step.durable!==false,last_delta:c.last_delta||null,last_age:c.last_age??null};
  records.push({input,expected});
  if(step.accept_release&&h.hbcChargePriorityIncreaseRequired){
   const target=h.hbcChargePriorityTarget;h.pvAction='charge_priority_increase';h.targetTotal=target;h.targets=[{entity:'pv1',target,current:c.current}];h.calls=[{payload:{action:'number.set_value',data:{value:target},target:{entity_id:'number.inv1'}},hpvcInverterWrite:{controlKey:'pv1',targetWatts:target,writeValue:target,limitUnit:'Watts',maximumWatts:c.full,desiredTargetWatts:target,controlMethod:'Number entity',verificationAvailable:true,readbackEntity:'number.inv1'}}];
   h.targets[0]=Object.assign(h.targets[0],{name:'PV1',changed:true,full_power:c.full,minimum_power:c.minimum,requested_target:target});
   r.run('7b758196fe8a7359',msg);
   r.run('0c09a82aaa67452b',msg);
   const requests=r.global.get('homePvControlAdapterRequests')||{};for(const value of Object.values(requests))value.status='complete';
  }
  if(step.accept_override)for(const call of h.hbcNegativeOverrideCalls||[]){if(call.payload.action==='input_select.select_option'){if(call.payload.target.entity_id==='input_select.house_battery_strategy')c.strategy=call.payload.data.option;else if(call.payload.target.entity_id==='input_select.house_battery_strategy_charge_goal')c.goal=call.payload.data.option;}}
  const override=r.global.get('homePvControlNegativePriceHbcOverride');if(step.durable!==false&&override?.entryToken)r.global.set('homePvControlNegativeOverridePersistedEntryToken',override.entryToken);
 }
 return {name:sequence.name,cycles:records};
}
const reference=zlib.gunzipSync(fs.readFileSync(path.join(ROOT,'tests/fixtures/policy-v1.6-runtime.json.gz')));
const output={source_flow_sha256:crypto.createHash('sha256').update(reference).digest('hex'),sequences:sequences.map(run)};
fs.writeFileSync(path.join(ROOT,'tests/fixtures/hbc-v1.6-sequences.json.gz'),zlib.gzipSync(JSON.stringify(output)+'\n'));
console.log(JSON.stringify({sequences:output.sequences.length,cycles:output.sequences.reduce((n,s)=>n+s.cycles.length,0)}));
