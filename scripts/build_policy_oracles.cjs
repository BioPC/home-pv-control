// Test-only oracle: execute ORIGINAL shipped Function nodes against fake HA/context.
// Stops before Record Requested Inverter Writes. No services, network or hardware.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const {Runtime,by,ctx}=require('../tests/policy_oracle_runtime.cjs');
const root=path.resolve(__dirname,'..');
const cases=[];
const controller=(kw={})=>Object.assign({full:3000,minimum:0,current:3000,unit:'Watts',step:1,available:true,participating:true},kw);
function add(name,kw={}){cases.push(Object.assign({name,grid:-600,pv:2500,market:-.01,all_in:.1,controllers:[controller()],settings:{},enabled:true},kw));}
add('zero',{controllers:[]});add('one');add('two',{controllers:[controller({full:2000,current:1500}),controller({full:1000,current:500})]});add('ten',{controllers:Array.from({length:10},()=>controller())});
add('mixed-percent',{controllers:[controller(),controller({unit:'Percent',step:3,current:1500,minimum:30})]});
for(const grid of [-151,-150,-149,-1,0,1,149,150,151,500,-5000]) add('grid-boundary-'+grid,{grid,controllers:[controller({current:2000})],pv:2000});
for(const delta of [24,25,26,-24,-25,-26])add('deadband-'+delta,{grid:-200,pv:2200+delta,controllers:[controller({current:2000})]});
for(const pv of [0,10,11,25,26,99,100,101]) add('pv-boundary-'+pv,{pv,controllers:[controller({current:1000})]});
for(const remaining of [-1,0,1,30]) add('cooldown-'+remaining,{cooldown_remaining:remaining});
for(const all_in of [-.1,0,.000001])add('all-in-'+all_in,{all_in,cooldown_remaining:30});
for(const market of [-.000001,0,.000001,.019999,.02,.020001])for(const price_mode of [true,false,null])add('price-'+market+'-'+price_mode,{market,price_mode,controllers:[controller({current:2000})]});
add('partial-outage',{controllers:[controller({full:2000,current:2000}),controller({full:1000,current:1000,available:false})],pv:2500,grid:-400});
add('opt-out',{controllers:[controller(),controller({participating:false})]});
add('all-opt-out',{controllers:[controller({participating:false})]});
add('import-current-ceiling',{grid:500,pv:100,controllers:[controller({current:1000})]});
add('import-degraded',{grid:600,pv:2500,controllers:[controller({current:1000}),controller({available:false})]});
add('recovery-rebalance',{rebalance:true,grid:0,pv:2000,controllers:[controller({full:2000,current:1900}),controller({full:1000,current:100})]});
add('saturation',{grid:-600,pv:1000,controllers:[controller({full:2000,current:110,minimum:100}),controller({full:1000,current:800,minimum:50})]});
add('quantization-shortfall',{grid:-450,pv:2000,controllers:[controller({unit:'Percent',step:7,current:2100})]});
add('decimal-allocation',{grid:-250,pv:1000,controllers:[controller({full:1000.25,current:700.25,minimum:5.5}),controller({full:500.5,current:400.5,minimum:4.5})]});
add('manual-disable',{enabled:false,controllers:[controller({current:1000})],cooldown_remaining:30});
add('manual-disabled-full',{enabled:false});
add('external-release',{external_release:true,controllers:[controller({current:1000})]});
add('external-full',{external_release:true});
add('external-cooldown',{external_release:true,cooldown_remaining:30,controllers:[controller({current:1000})]});
add('external-negative',{external_release:true,all_in:0});
add('external-degraded',{external_release:true,release_age:90,controllers:[controller(),controller({available:false})]});
for(const age of [0,119,120,121])add('night-entry-'+age,{pv:10,night_entry_age:age,controllers:[controller({current:1000})]});
add('night-active-full',{pv:0,night_active:true});
add('night-missing-without-candidate',{pv:null,sun_below:true});
add('night-missing-with-candidate',{pv:null,sun_below:true,night_entry_age:120});
add('night-stale-candidate',{pv:0,pv_age:181,night_entry_age:120,sun_below:true});
for(const pv of [25,26])for(const age of [29,30])add('night-recovery-'+pv+'-'+age,{pv,night_active:true,night_recovery_age:age});
add('pending-export',{pending:true});
add('pending-import',{pending:true,grid:500,pv:1000,controllers:[controller({current:1000}),controller({current:1000})]});
add('pending-import-saturated',{pending:true,grid:4000,pv:2000,controllers:[controller({current:1000}),controller({current:2900})]});
add('pending-disable',{enabled:false,pending:true,controllers:[controller({current:1000})]});
add('reversal-damping',{last_delta:1500,last_age:30,controllers:[controller()],grid:-3000,pv:3000});
add('reversal-expired',{last_delta:1500,last_age:181,controllers:[controller()],grid:-3000,pv:3000});
add('hbc-suppression',{hbc:{suppress:true,operational:true}});
add('hbc-fallback',{hbc:{suppress:false,operational:true,fallback:true}});
add('hbc-release',{grid:0,pv:1500,controllers:[controller({current:1500})],hbc:{increase:true,target:1800,operational:true}});
add('hbc-external-response',{external_release:true,hbc:{response:true},controllers:[controller({current:1500})]});
add('hbc-negative',{all_in:0,hbc:{suppress:true,operational:true}});
for(const gap of [24,25,26])add('disable-deadband-'+gap,{enabled:false,controllers:[controller({current:3000-gap})]});
add('external-aggregate-full-gap',{external_release:true,controllers:[controller({current:2980}),controller({current:2980})]});
add('external-individual-full-gap',{external_release:true,controllers:[controller({current:2980})]});
let seed=20261027;const rand=()=>{seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed/2**32;};
for(let i=0;i<120;i++){const n=1+Math.floor(rand()*4);const cs=Array.from({length:n},()=>{let full=[1000,2000,3000][Math.floor(rand()*3)];return controller({full,current:Math.floor(rand()*full),minimum:0});});add('seeded-'+i,{controllers:cs,grid:Math.floor(rand()*3000)-1800,pv:Math.floor(rand()*cs.reduce((x,c)=>x+c.full,0)),market:[-.01,0,.01,.03][Math.floor(rand()*4)],all_in:rand()<.1?0:.1,cooldown_remaining:rand()<.2?20:0});}
function run(s){
 const r=new Runtime();const put=(id,value,attrs)=>r.states[id]={state:String(value),attributes:attrs||{}};
 put('input_number.hpvc_inverter_count',s.controllers.length);put('input_boolean.hpvc_enabled',s.enabled?'on':'off');put('input_boolean.hpvc_external_release_request',s.external_release?'on':'off');
 for(const [key,value] of Object.entries(s.settings))put('input_number.hpvc_'+key,value);
 for(const [key,value] of Object.entries({grid:s.grid,pv:s.pv,market:s.market,allin:s.all_in}))put('sensor.'+key,value===null?'unavailable':value);
 put('sun.sun',s.sun_below?'below_horizon':'above_horizon');
 s.controllers.forEach((c,i)=>{const slot=i+1;put(`input_number.hpvc_pv${slot}_full_limit`,c.full);put(`input_number.hpvc_pv${slot}_low_limit`,c.minimum);put(`input_select.hpvc_pv${slot}_limit_unit`,c.unit);put(`input_boolean.hpvc_pv${slot}_control_disabled`,c.participating?'off':'on');put(`number.inv${slot}`,c.available?(c.unit==='Percent'?c.current/c.full*100:c.current):'unavailable',{min:0,max:c.unit==='Percent'?100:c.full,step:c.step});});
 r.refresh((s.pv_age||0)*1000);
 if(s.cooldown_remaining)r.global.set('homePvControlCooldownUntilMs',r.now+s.cooldown_remaining*1000);
 const flow=ctx();r.flows[by['ae1cca17db30eece'].z]=flow;const priceFlow=r.flows[by['a7df14169cc2e947'].z]??=ctx();
 if(s.price_mode!==undefined&&s.price_mode!==null)priceFlow.set('homePvControlPriceLimitingActive',s.price_mode);
 if(s.night_active)flow.set('homePvControlNightRestoreActive',true);
 if(s.night_entry_age!==undefined)flow.set('homePvControlNightRestoreSince',r.now-s.night_entry_age*1000);
 if(s.night_recovery_age!==undefined)flow.set('homePvControlNightRestoreRecoverySince',r.now-s.night_recovery_age*1000);
 if(s.release_age!==undefined)r.global.set('homePvControlExternalReleaseRequestState',{active:true,requestedAt:r.now-s.release_age*1000});
 if(s.rebalance)r.global.set('homePvControlInverterRebalancePending',{id:r.now-1000,names:['PV2']});
 if(s.last_delta)r.global.set('homePvControlLastPvCommand',{delta:s.last_delta,ts:r.now-s.last_age*1000,verification:'verified'});
 if(false)r.global.set('homePvControlPendingWriteVerification',{requested_ts:r.now-1000,requested:[{entity:'pv1',value:s.controllers[0].current-100}],checked:false});
 const original=r.run.bind(r);const stages={};
 r.run=(id,msg)=>{let result=original(id,msg);const m=Array.isArray(result)?result[0]:result;
  if(id==='8b490d1484a538d7'&&s.pending)r.global.set('homePvControlPendingWriteVerification',{requested_ts:r.now-1000,requested:[{entity:'pv1',value:s.controllers[0].current-100}],checked:false});
  if(id==='4e29c5113e825239'&&s.hbc&&m){const h=s.hbc;Object.assign(m.hpvc,{hbcExportLimitingSuppressed:!!h.suppress,hbcChargePriorityOperational:!!h.operational,hbcChargePriorityIncreaseRequired:!!h.increase,hbcChargePriorityTarget:h.target,hbcBelow90Priority:!!h.increase,hbcChargePriorityIncrease:Math.max(0,(h.target||0)-m.hpvc.currentLimitTotal),hbcResponseWindowActive:!!h.response,hbcTransitionSettleActive:false});}
  if(m&&['34beacbe564351d4','7ca764bbb9c3bedd','5d71ed0472f977a7'].includes(id))stages[id]=JSON.parse(JSON.stringify(m.hpvc));return result;};
 const h=r.cycle('5d71ed0472f977a7').hpvc;
 const final=stages['34beacbe564351d4']||h;const allocation=stages['7ca764bbb9c3bedd']||h;
 return {input:s,expected:{action:h.pvAction,status:h.status,reason:h.reason,halted:!!h.halted,requested:final.targetTotal,allocated:allocation.targetTotal,calculated:final.calculatedTargetTotal??null,targets:(allocation.targets||[]).map(t=>({uid:String(t.entity).replace(/^pv(\d+)$/,(_,n)=>'number.inv'+n),target:t.target,frozen:!!t.skippedInFlight})),represented:(h.targets||[]).map(t=>({uid:String(t.entity).replace(/^pv(\d+)$/,(_,n)=>'number.inv'+n),target:t.target,native:t.write_value_percent??t.write_value_watts})),price_mode:!!h.priceLimitingActive,remembered_price_mode:priceFlow.get('homePvControlPriceLimitingActive')??null,cooldown_active:!!h.cooldownActiveNow,cooldown_until:r.global.get('homePvControlCooldownUntilMs')||0,night_active:!!h.nightRestoreActive,night_pending:!!h.nightRestorePending,night_entry_since:flow.get('homePvControlNightRestoreSince')||0,night_recovery_since:flow.get('homePvControlNightRestoreRecoverySince')||0,rebalance_applied:!!h.inverterRebalanceApplied,rebalance_confirmed:!!h.inverterRebalanceConfirmed}};
}
const flow=require('zlib').gunzipSync(fs.readFileSync(path.join(root,'tests/fixtures/policy-v1.6-runtime.json.gz')));
const output={source_flow_sha256:crypto.createHash('sha256').update(flow).digest('hex'),source:'Original v1.6 Runtime.cycle through Detect Meaningful Inverter Target Changes, no dispatch. HBC scenarios inject resolved upstream HBC interface only.',scenarios:cases.map(run)};
const target=path.join(root,'tests/fixtures/policy-v1.6-oracles.json');fs.writeFileSync(target,JSON.stringify(output)+'\n');console.log(JSON.stringify({scenarios:cases.length,path:target,source_sha256:output.source_flow_sha256}));

// Independent allocation characterization executes the original allocator only.
const allocations=[];
for(let i=0;i<220;i++){
 const count=i%11;const cs=Array.from({length:count},(_,j)=>{const full=[1000,2000,3000][Math.floor(rand()*3)]+(i%3===0?.5:0);const minimum=i%4===0?25.5:0;return {uid:'allocation:'+j,full,minimum,current:minimum+Math.floor(rand()*(full-minimum)),available:true,participating:true,eligible:true};});
 const total=cs.reduce((sum,c)=>sum+c.full,0);const current=cs.reduce((sum,c)=>sum+c.current,0);
 const target=Math.round(rand()*(total+200))-100;const frozen=i%5===0&&target>current&&count>1?[cs[0].uid]:[];const rebalance=i%7===0&&!frozen.length;
 const r=new Runtime();let h={now:r.now,inverters:cs.map((c,j)=>({name:'PV'+(j+1),control_key:c.uid,current:c.current,full_power:c.full,minimum_power:c.minimum,action_step:1})),targetTotal:target,deadband:25,canChangePv:true,inverterRebalancePending:rebalance,inverterRebalanceRequest:rebalance?{id:r.now}:null,pvWriteLockActive:!!frozen.length,pvWriteLockBypassForImport:!!frozen.length,pvWriteBlockedIncreaseEntities:frozen};
 const result=r.run('7ca764bbb9c3bedd',{hpvc:h}).hpvc;
 allocations.push({input:{name:'allocation-'+i,controllers:cs,target,frozen,rebalance},expected:{targets:(result.targets||[]).map(t=>({uid:t.entity,target:t.target})),allocated:result.achievedTargetTotal??null,halted:!!result.halted,rebalance_applied:!!result.inverterRebalanceApplied,rebalance_confirmed:!!result.inverterRebalanceConfirmed}});
}
output.allocations=allocations;fs.writeFileSync(target,JSON.stringify(output)+'\n');console.log('Allocation oracle scenarios: '+allocations.length);
