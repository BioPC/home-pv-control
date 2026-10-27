// Temporary, migration-only v1.6 bridge. Not deployed or wired by native HPVC.
// Host supplies a complete flow inventory and the in-process v1.6 global context.
'use strict';
const crypto=require('node:crypto');
const TABS=['d67da0bc5cc8b033','2eca035706d6f2b3','868aa5d1f8da9181','2546832d38d000c2'];
const DEPENDENCIES=['176d29a.6f648d6','9a452ab456ded4e2'];
const KEYS=['homePvControlAdapterRequests','homePvControlAdapterScheduler',
 'homePvControlPendingWriteVerification','homePvControlDisableRestoreState',
 'homePvControlNegativePriceHbcOverride','homePvControlAdapterSafetyBlocked',
 'homePvControlAdapterResync','homePvControlRuntimeEvaluationLock',
 'homePvControlUninstallShutdownActive','homePvControlUninstallShutdownStartedAt',
 'homePvControlUninstallShutdownLastEvaluationAt','homePvControlUninstallShutdownCompletedAt',
 'homePvControlAdapterRuntimeOwner','homePvControlAdapterConfigSignatures',
 'homePvControlNightRestoreFullConfirmation'];
function canonical(x){return JSON.stringify(x, function(k,v){if(v&&typeof v==='object'&&!Array.isArray(v))return Object.fromEntries(Object.keys(v).sort().map(n=>[n,v[n]]));return v;});}
function owned(nodes){return nodes.filter(n=>TABS.includes(n.id)||TABS.includes(n.z)||DEPENDENCIES.includes(n.id));}
function foreignHpvc(nodes){return nodes.filter(n=>!TABS.includes(n.id)&&!TABS.includes(n.z)&&!DEPENDENCIES.includes(n.id)&&(/homePvControl/.test(n.func||'')||/hpvc/i.test((n.name||'')+' '+(n.label||'')))).map(n=>n.id);}
function fingerprint(nodes){return crypto.createHash('sha256').update(canonical(owned(nodes).map(n=>{const v={...n};if(v.type==='tab')delete v.disabled;return v;}).sort((a,b)=>a.id.localeCompare(b.id)))).digest('hex');}
function inspect({nodes,get,completeInventory=false,runtimeBoot,transactionId,challenge,now,getFlow}){
 const raw=Object.fromEntries(KEYS.map(k=>[k,get(k)]));
 // Undefined context can mean a cold restart that lost outstanding obligations.
 // Never replace it with an empty scheduler or an assumed-restored HBC state.
 const foreign=foreignHpvc(nodes);
 const complete=completeInventory&&foreign.length===0&&KEYS.every(k=>raw[k]!==undefined)&&!!runtimeBoot&&!!transactionId&&!!challenge;
 const scheduler=raw.homePvControlAdapterScheduler;
 const requests=raw.homePvControlAdapterRequests;
 const hbc=raw.homePvControlNegativePriceHbcOverride;
 const pending=raw.homePvControlPendingWriteVerification;
 const restore=raw.homePvControlDisableRestoreState;
 return {schema:'hpvc-migration/1.6.0/1',fingerprint:fingerprint(nodes),runtimeBoot,transactionId,challenge,now,complete,
  raw,night:{active:typeof getFlow==='function'&&getFlow('homePvControlNightRestoreActive')===true,confirmation:raw.homePvControlNightRestoreFullConfirmation},foreignHpvcCandidates:foreign,commandTabsDisabled:TABS.every(id=>nodes.find(n=>n.id===id)?.disabled===true),
  workMayExist:!complete||!!scheduler?.busy||!!scheduler?.queue?.length||!!requests&&Object.keys(requests).length>0||!!pending||restore?.active===true||!!hbc||!!raw.homePvControlAdapterSafetyBlocked||!!raw.homePvControlAdapterResync||!!raw.homePvControlRuntimeEvaluationLock,
  shutdownEvaluatedAfterRequest:Number(raw.homePvControlUninstallShutdownLastEvaluationAt)>Number(raw.homePvControlUninstallShutdownStartedAt)&&raw.homePvControlUninstallShutdownActive===true};
}
function planFence(nodes,expectedFingerprint){
 if(fingerprint(nodes)!==expectedFingerprint)throw Error('HPVC fingerprint changed');
 if(!TABS.every(id=>nodes.find(n=>n.id===id)?.type==='tab'))throw Error('Incomplete HPVC ownership');
 // Only exact owned tabs are deactivated; unrelated nodes/configuration are untouched.
 return nodes.map(n=>TABS.includes(n.id)?{...n,disabled:true}:n);
}
module.exports={TABS,KEYS,DEPENDENCIES,foreignHpvc,canonical,fingerprint,inspect,planFence};
