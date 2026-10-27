// Actual v1.6 Function bodies in a contained runner; no Node-RED/HA network.
'use strict';
const assert=require('node:assert/strict');
const {Runtime,by}=require('./control_test_runtime.cjs');
const bridge=require('../migration/legacy-bridge-v1.6.cjs');
const nodes=require('../node-red/hpvc_flow.json');
let passed=0;
function test(name,fn){fn();passed++;console.log('PASS '+name);}
function snapshot(r){return bridge.inspect({nodes,get:k=>r.global.get(k),completeInventory:true,runtimeBoot:'fixture-runtime',transactionId:'fixture-transaction',challenge:'fresh-host-nonce',now:r.now});}
function setup(){const r=new Runtime();r.states['input_boolean.hpvc_enabled'].state='off';r.states['number.inv1'].state='500';r.refresh();return r;}
function tick(r){r.now+=1000;r.refresh();return r.cycle(undefined,'timer');}
const START='57dc0986bf249cd3',NEXT='3f890e176d2b747b';
test('fingerprint pinned to supplied v1.6 owned tabs',()=>assert.equal(bridge.fingerprint(nodes),'23e70cb864ae386b2ffe202a86bd7683be49402679b6cf94cda12c6dc6af479d'));
test('fresh/cold missing context is unknown, never quiescent',()=>{const r=setup();assert.equal(snapshot(r).complete,false);assert.equal(snapshot(r).workMayExist,true);});
test('read-only export does not mutate control context',()=>{const r=setup();const before=[...r.global.m];snapshot(r);assert.deepEqual([...r.global.m],before);});
test('safe-disable source records request before evaluation',()=>{const r=setup();r.run('a622e5af64d3601e',{});assert.equal(r.global.get('homePvControlUninstallShutdownActive'),true);assert.equal(r.global.get('homePvControlUninstallShutdownLastEvaluationAt'),0);assert.equal(snapshot(r).shutdownEvaluatedAfterRequest,false);});
test('source off-cycle restores configured full limit',()=>{const r=setup();r.run('a622e5af64d3601e',{});const m=tick(r);let call=r.run(START,m.hpvc.outputs[0]);assert(call);assert.equal(call.payload.data.value,3000);assert(snapshot(r).workMayExist);r.states['number.inv1'].state='3000';r.run(NEXT,call);tick(r);assert.equal(r.global.get('homePvControlAdapterScheduler').busy,null);});
test('queued original source work is exported without reset',()=>{const r=setup();r.cycle();const before=JSON.stringify(r.global.get('homePvControlAdapterRequests'));const e=snapshot(r);assert(e.workMayExist);assert.equal(JSON.stringify(e.raw.homePvControlAdapterRequests),before);});
test('HBC object ownership blocks even without active boolean',()=>{const r=setup();r.global.set('homePvControlNegativePriceHbcOverride',{phase:'restoring_strategy',previousStrategy:'Self Consumption'});assert(snapshot(r).workMayExist);});
test('fence deactivates only exact owned tabs and preserves unrelated flows',()=>{const unrelated=[{id:'user-tab',type:'tab',label:'Unrelated'},{id:'user-node',z:'user-tab',type:'function',func:'return msg;'}];const all=[...nodes,...unrelated];const original=JSON.stringify(unrelated);const fenced=bridge.planFence(all,bridge.fingerprint(nodes));assert(bridge.TABS.every(id=>fenced.find(n=>n.id===id).disabled===true));assert.equal(JSON.stringify(fenced.filter(n=>n.id.startsWith('user-'))),original);assert.equal(bridge.fingerprint(fenced),bridge.fingerprint(nodes));});
test('fence refuses edited HPVC source',()=>{const changed=structuredClone(nodes);changed.find(n=>n.id===START).func+='\n// changed';assert.throws(()=>bridge.planFence(changed,bridge.fingerprint(nodes)));});
test('fence plan repeated is idempotent and does not fabricate runtime receipt',()=>{const once=bridge.planFence(nodes,bridge.fingerprint(nodes));assert.deepEqual(bridge.planFence(once,bridge.fingerprint(nodes)),once);const r=setup();const e=bridge.inspect({nodes:once,get:k=>r.global.get(k),completeInventory:true,runtimeBoot:'x',transactionId:'t',challenge:'n',now:r.now});assert.equal(e.commandTabsDisabled,true);assert.equal(e.complete,false);});
test('shared actuator dependency changes invalidate identity without editing shared config',()=>{const changed=structuredClone(nodes);changed.find(n=>n.id==='176d29a.6f648d6').name='changed server';assert.notEqual(bridge.fingerprint(changed),bridge.fingerprint(nodes));assert.throws(()=>bridge.planFence(changed,bridge.fingerprint(nodes)));});
test('unknown cloned HPVC source cannot hide outside known tabs',()=>{const extra=[...nodes,{id:'unknown-clone',z:'other-tab',type:'function',func:'global.get(\'homePvControlAdapterScheduler\')'}];const r=setup();const e=bridge.inspect({nodes:extra,get:k=>r.global.get(k),completeInventory:true,runtimeBoot:'b',transactionId:'t',challenge:'c',now:r.now});assert.deepEqual(e.foreignHpvcCandidates,['unknown-clone']);assert.equal(e.complete,false);});
console.log(`${passed} migration bridge/source fencing checks passed`);
