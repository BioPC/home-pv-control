// Continuous original v1.6 Function-node oracle. Simulated acceptance only.
const fs=require('fs'),path=require('path'),crypto=require('crypto');
const {Runtime,by,ctx}=require('../tests/policy_oracle_runtime.cjs');
const root=path.resolve(__dirname,'..');
const controller=(kw={})=>Object.assign({full:3000,minimum:0,current:3000,unit:'Watts',step:1,available:true,participating:true},kw);
function run(s,r){
 r.now=1800000000000+s.at*1000;const put=(id,value,attrs)=>r.states[id]={state:String(value),attributes:attrs||{}};
 put('input_number.hpvc_inverter_count',s.controllers.length);put('input_boolean.hpvc_enabled',s.enabled?'on':'off');put('input_boolean.hpvc_external_release_request',s.external_release?'on':'off');
 for(const [key,value] of Object.entries(s.settings))put('input_number.hpvc_'+key,value);
 for(const [key,value] of Object.entries({grid:s.grid,pv:s.pv,market:s.market,allin:s.all_in}))put('sensor.'+key,value===null?'unavailable':value);
 put('sun.sun',s.sun_below?'below_horizon':'above_horizon');
 s.controllers.forEach((c,i)=>{const slot=i+1;put(`input_number.hpvc_pv${slot}_full_limit`,c.full);put(`input_number.hpvc_pv${slot}_low_limit`,c.minimum);put(`input_select.hpvc_pv${slot}_limit_unit`,c.unit);put(`input_boolean.hpvc_pv${slot}_control_disabled`,c.participating?'off':'on');put(`number.inv${slot}`,c.available?(c.unit==='Percent'?c.current/c.full*100:c.current):'unavailable',{min:0,max:c.unit==='Percent'?100:c.full,step:c.step});});
 r.refresh((s.pv_age||0)*1000);
 if(s.cooldown_remaining)r.global.set('homePvControlCooldownUntilMs',r.now+s.cooldown_remaining*1000);
 const flow=r.flows[by['ae1cca17db30eece'].z]??=ctx();const priceFlow=r.flows[by['a7df14169cc2e947'].z]??=ctx();
 if(s.price_mode!==undefined&&s.price_mode!==null)priceFlow.set('homePvControlPriceLimitingActive',s.price_mode);
 if(s.night_active)flow.set('homePvControlNightRestoreActive',true);
 if(s.night_entry_age!==undefined)flow.set('homePvControlNightRestoreSince',r.now-s.night_entry_age*1000);
 if(s.night_recovery_age!==undefined)flow.set('homePvControlNightRestoreRecoverySince',r.now-s.night_recovery_age*1000);
 if(s.release_age!==undefined)r.global.set('homePvControlExternalReleaseRequestState',{active:true,requestedAt:r.now-s.release_age*1000});
 if(s.rebalance)r.global.set('homePvControlInverterRebalancePending',{id:r.now-1000,names:['PV2']});
 if(s.last_delta)r.global.set('homePvControlLastPvCommand',{delta:s.last_delta,ts:r.now-s.last_age*1000,verification:'verified'});
 if(false)r.global.set('homePvControlPendingWriteVerification',{requested_ts:r.now-1000,requested:[{entity:'pv1',value:s.controllers[0].current-100}],checked:false});
 const original=Runtime.prototype.run.bind(r);const stages={};
 const beforeCooldown=r.global.get("homePvControlCooldownUntilMs")||0;const beforeCommand=r.global.get("homePvControlLastPvCommand")||null;
 r.run=(id,msg)=>{let result=original(id,msg);const m=Array.isArray(result)?result[0]:result;
  if(id==='8b490d1484a538d7'&&s.pending)r.global.set('homePvControlPendingWriteVerification',{requested_ts:r.now-1000,requested:[{entity:'pv1',value:s.controllers[0].current-100}],checked:false});
  if(id==='4e29c5113e825239'&&s.hbc&&m){const h=s.hbc;Object.assign(m.hpvc,{hbcExportLimitingSuppressed:!!h.suppress,hbcChargePriorityOperational:!!h.operational,hbcChargePriorityIncreaseRequired:!!h.increase,hbcChargePriorityTarget:h.target,hbcBelow90Priority:!!h.increase,hbcChargePriorityIncrease:Math.max(0,(h.target||0)-m.hpvc.currentLimitTotal),hbcResponseWindowActive:!!h.response,hbcTransitionSettleActive:false});}
  if(m&&['34beacbe564351d4','7ca764bbb9c3bedd','5d71ed0472f977a7'].includes(id))stages[id]=JSON.parse(JSON.stringify(m.hpvc));return result;};
 const message=r.cycle('5d71ed0472f977a7');const h=JSON.parse(JSON.stringify(message.hpvc));
 if(s.accept){let accepted=original('7b758196fe8a7359',message);accepted=original('0c09a82aaa67452b',accepted);original('bb19169eb0446c5c',accepted);}
 s.execution={cooldown_until:beforeCooldown/1000,last:beforeCommand,pending:!!h.pvWriteLockActive&&!h.pvPostWriteSettling,settling:!!h.pvPostWriteSettling,lock_reason:h.pvWriteLockReason||"",blocked:h.pvWriteBlockedIncreaseEntities||[],pending_action:(r.global.get("homePvControlPendingWriteVerification")||{}).pvAction||null};
 const final=stages['34beacbe564351d4']||h;const allocation=stages['7ca764bbb9c3bedd']||h;
 return {input:s,expected:{action:h.pvAction,status:h.status,reason:h.reason,halted:!!h.halted,requested:final.targetTotal,allocated:allocation.targetTotal,calculated:final.calculatedTargetTotal??null,targets:(allocation.targets||[]).map(t=>({uid:String(t.entity).replace(/^pv(\d+)$/,(_,n)=>'number.inv'+n),target:t.target,frozen:!!t.skippedInFlight})),represented:(h.targets||[]).map(t=>({uid:String(t.entity).replace(/^pv(\d+)$/,(_,n)=>'number.inv'+n),target:t.target,native:t.write_value_percent??t.write_value_watts})),price_mode:!!h.priceLimitingActive,remembered_price_mode:priceFlow.get('homePvControlPriceLimitingActive')??null,cooldown_active:!!h.cooldownActiveNow,cooldown_until:beforeCooldown,night_active:!!h.nightRestoreActive,night_pending:!!h.nightRestorePending,night_entry_since:flow.get('homePvControlNightRestoreSince')||0,night_recovery_since:flow.get('homePvControlNightRestoreRecoverySince')||0,rebalance_applied:!!h.inverterRebalanceApplied,rebalance_confirmed:!!h.inverterRebalanceConfirmed}};
}
const definitions=[
 ['export-cooldown-further-export',[{at:0,accept:true},{at:5,controllers:[controller({current:2285})]},{at:31,controllers:[controller({current:2285})]}]],
 ['export-import-recovery',[{at:0,accept:true},{at:10,grid:600,pv:1800,controllers:[controller({current:2285})]},{at:31,grid:400,pv:1800,controllers:[controller({current:2285})]}]],
 ['large-reduction-reversal',[{at:0,grid:-2500,pv:3000,accept:true},{at:31,grid:2500,pv:1500,controllers:[controller({current:1950})]},{at:65,grid:-1200,pv:2500,controllers:[controller({current:2600})]}]],
 ['partial-outage-continuation',[{at:0,controllers:[controller({full:2000,current:2000}),controller({full:1000,current:1000})]},{at:1,controllers:[controller({full:2000,current:2000}),controller({full:1000,current:1000,available:false})]},{at:62,grid:500,controllers:[controller({full:2000,current:1000}),controller({full:1000,current:1000,available:false})]}]],
 ['controller-recovery-rebalance',[{at:0,controllers:[controller({full:2000,current:1900}),controller({full:1000,current:100,available:false})]},{at:61,rebalance:true,grid:0,pv:2000,controllers:[controller({full:2000,current:1900}),controller({full:1000,current:100})]},{at:62,grid:0,pv:2000,controllers:[controller({full:2000,current:1333}),controller({full:1000,current:667})]}]],
 ['night-entry-active-recovery',[{at:0,pv:10,controllers:[controller({current:1000})]},{at:119,pv:10,controllers:[controller({current:1000})]},{at:120,pv:10,controllers:[controller({current:1000})]},{at:121,pv:30},{at:150,pv:30},{at:151,pv:30}]],
 ['external-release-unresolved',[{at:0,external_release:true,controllers:[controller({current:1000})]},{at:1,external_release:true,pending:true,controllers:[controller({current:1000})]},{at:91,external_release:true,pending:true,controllers:[controller({current:1000})]}]],
 ['manual-disable-restoration',[{at:0,controllers:[controller({current:1000})]},{at:1,enabled:false,controllers:[controller({current:1000})]},{at:2,enabled:false}]],
 ['price-hysteresis-memory',[{at:0,market:-.01},{at:1,market:.01},{at:2,market:.03},{at:3,market:.01},{at:4,market:-.01}]],
 ['negative-price-entry-exit',[{at:0,all_in:0},{at:1,all_in:-.1},{at:10,all_in:.1}]],
];
const sequences=definitions.map(([name,steps])=>{const r=new Runtime();const cycles=steps.map(step=>run(Object.assign({name,grid:-600,pv:2500,market:-.01,all_in:.1,controllers:[controller()],settings:{},enabled:true},step),r));return {name,cycles};});
const raw=require('zlib').gunzipSync(fs.readFileSync(path.join(root,'tests/fixtures/policy-v1.6-runtime.json.gz')));
fs.writeFileSync(path.join(root,'tests/fixtures/policy-v1.6-sequences.json'),JSON.stringify({source_flow_sha256:crypto.createHash('sha256').update(raw).digest('hex'),sequences})+'\n');
console.log(JSON.stringify({sequences:sequences.length,cycles:sequences.reduce((n,s)=>n+s.cycles.length,0)}));
