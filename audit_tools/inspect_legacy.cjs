// Pure inspection of local exports. Never evaluates flow code or edits any flow.
'use strict';
const fs=require('node:fs');const b=require('../migration/legacy-bridge-v1.6.cjs');
function inspect(nodes,context={},complete=false){
 const known=b.fingerprint(nodes)==='23e70cb864ae386b2ffe202a86bd7683be49402679b6cf94cda12c6dc6af479d';
 const g=context.global_context||{},f=context.flow_context||{},runtime=context.runtime||{};
 const e=b.inspect({nodes,get:k=>g[k],getFlow:k=>f[k],completeInventory:complete,runtimeBoot:runtime.runtime_owner,transactionId:'audit-observation-only',challenge:'audit-no-handoff',now:context.observed_at_utc});
 const scheduler=g.homePvControlAdapterScheduler||{};
 const shapeComplete=!!g.homePvControlAdapterScheduler&&typeof g.homePvControlAdapterScheduler==='object'&&Array.isArray(scheduler.queue)&&Object.hasOwn(scheduler,'busy')&&!!g.homePvControlAdapterRequests&&typeof g.homePvControlAdapterRequests==='object'&&!Array.isArray(g.homePvControlAdapterRequests)&&!!g.homePvControlDisableRestoreState&&typeof g.homePvControlDisableRestoreState.active==='boolean';
 const active=scheduler.busy?['legacy-busy']:[];
 const queued=[...Object.keys(g.homePvControlAdapterRequests||{}),...(scheduler.queue||[]).map((_,i)=>'queue:'+i)];
 return {version:known?'1.6.0':null,version_claim:nodes.filter(n=>b.TABS.includes(n.id)).map(n=>n.label),fingerprint:e.fingerprint,
  flow_inventory_complete:complete,foreign_hpvc_candidates:e.foreignHpvcCandidates,
  managed_tabs:nodes.filter(n=>b.TABS.includes(n.id)).map(n=>({id:n.id,label:n.label,disabled:n.disabled===true})),
  runtime:{reachable:runtime.reachable??null,observed_at_utc:runtime.observed_at_utc??context.observed_at_utc??null,runtime_owner:runtime.runtime_owner??null,pending_update:runtime.pending_update??null,recovery_pending:runtime.recovery_pending??null},
  bridge:{schema:e.schema,complete:e.complete&&shapeComplete&&g.homePvControlAdapterRuntimeOwner===runtime.runtime_owner,
   runtime_owner:g.homePvControlAdapterRuntimeOwner??null,flow_fingerprint:e.fingerprint,observed_at_utc:context.observed_at_utc??null,
   active,queued,potentially_issued:active,pending_verification:g.homePvControlPendingWriteVerification?['legacy-pending']:[],
   restore_obligations:g.homePvControlDisableRestoreState?.active?['legacy-restore']:[],
   recovery_required:!!g.homePvControlAdapterSafetyBlocked||Object.keys(g.homePvControlAdapterResync||{}).length>0||!!g.homePvControlRuntimeEvaluationLock,
   hbc_override_owned:g.homePvControlNegativePriceHbcOverride!==undefined?g.homePvControlNegativePriceHbcOverride!==null:null,
   hbc_originals:Array.isArray(context.hbc_originals)?context.hbc_originals:null}};
}
if(require.main===module){
 const args=process.argv.slice(2);if(!args[0])throw Error('Local flow export path required');
 const raw=fs.readFileSync(args[0]);if(raw.length>8*1024*1024)throw Error('Flow export bound exceeded');
 const parsed=JSON.parse(raw);const nodes=Array.isArray(parsed)?parsed:parsed.flows;
 if(!Array.isArray(nodes)||nodes.length>10000)throw Error('Flow inventory required');
 const context=args[1]&&args[1]!=='-'?JSON.parse(fs.readFileSync(args[1],'utf8')):{};
 console.log(JSON.stringify(inspect(nodes,context,args[2]==='complete')));
}
module.exports={inspect};
