// Execute shipped Function bodies with captured, manually completed HA calls.
const assert=require('node:assert/strict');
const {Runtime,by}=require('./control_test_runtime.cjs');
const START='57dc0986bf249cd3',NEXT='3f890e176d2b747b';
const WATCHERS=['eb9674e0d58dc6d1','6e1516a98c6391ee','b6d450b56fb931b3'];
let passed=0;
function test(name,fn){if(process.argv[2]&&!new RegExp(process.argv[2]).test(name))return;fn();passed++;console.log('PASS '+name);}
function setup({off=false,current=500,pre=true}={}){
 const r=new Runtime(),s=r.states;
 s['input_boolean.hpvc_enabled'].state=off?'off':'on';
 s['input_select.hpvc_pv1_control_method'].state='Action/service';
 s['input_text.hpvc_pv1_action'].state='script.apply_limit';
 s['input_text.hpvc_pv1_pre_actions_json'].state=pre?'[{"action":"script.prepare"}]':'[]';
 s['input_text.hpvc_pv1_readback_entity'].state='sensor.limit';
 s['sensor.limit']={state:String(current),attributes:{}};
 s['sensor.pv'].state='1200';r.refresh();return r;
}
function tick(r,seconds){r.now+=seconds*1000;r.refresh();return r.cycle(undefined,'timer');}
function start(r,m){return m?.hpvc?.outputs?.[0]?r.run(START,m.hpvc.outputs[0]):null;}
function initialize(r){const statuses=[];new Function('global','node',by[START].initialize)(r.global,{status:s=>statuses.push(s),warn:()=>{}});return statuses;}
function allBlocked(r){for(const id of WATCHERS){r.global.set('homePvControlUninstallShutdownActive',true);const out=r.run(id,{topic:'regression'});assert(!out?.[0],id+' authorized cleanup');assert(out?.[1]||out?.[2],id+' neither refused nor polled');}}
function finish(r,msg){const emitted=[];for(let i=0;msg&&i<50;i++){emitted.push(msg);if(msg.hpvcInverterWrite)r.states['sensor.limit'].state=String(msg.payload.data.value);msg=r.run(NEXT,msg);}assert.equal(msg,null);return emitted;}

test('slow identical restore completes without timer starvation',()=>{
 const r=setup({off:true});let active=start(r,r.cycle());assert.equal(active.payload.action,'script.prepare');
 const gen=active.hpvcAdapterGeneration,requested=r.global.get('homePvControlPendingWriteVerification').requested_ts;
 for(let i=0;i<3;i++){start(r,tick(r,10));assert.equal(r.global.get('homePvControlAdapterLatestGeneration').pv1,gen);assert.equal(r.global.get('homePvControlPendingWriteVerification').requested_ts,requested);}
 active=r.run(NEXT,active);assert.equal(active.payload.action,'script.apply_limit');assert.equal(active.payload.data.value,3000);
 start(r,tick(r,10));assert.equal(r.global.get('homePvControlAdapterLatestGeneration').pv1,gen);
 r.states['sensor.limit'].state='3000';r.run(NEXT,active);tick(r,1);
 assert.notEqual(r.global.get('homePvControlDisableRestoreState')?.active,true);
 assert.equal(r.global.get('homePvControlAdapterScheduler').busy,null);
});

test('lost pre-dispatch output replays original identity and duplicate batches do not duplicate calls',()=>{
 const r=setup({off:true});const original=r.cycle(),gen=original.hpvc.outputs[0].payload[0].hpvcAdapterGeneration;
 const requested=r.global.get('homePvControlPendingWriteVerification').requested_ts;
 const replay=tick(r,10);assert(replay.hpvc.outputs[0]);assert.equal(replay.hpvc.outputs[0].payload[0].hpvcAdapterGeneration,gen);
 assert.equal(r.global.get('homePvControlPendingWriteVerification').requested_ts,requested);
 let active=start(r,replay);assert(active);assert.equal(start(r,original),null);
 const emitted=finish(r,active);assert.deepEqual(emitted.map(m=>m.payload.action),['script.prepare','script.apply_limit']);
 assert.equal(Object.keys(r.global.get('homePvControlAdapterRequests')).length,0);
});

test('two inverter slow restore coalesces independently and drains both groups',()=>{
 const r=setup({off:true});r.states['input_number.hpvc_inverter_count'].state='2';r.states['number.inv2'].state='500';r.refresh();
 let active=start(r,r.cycle());const gens={...r.global.get('homePvControlAdapterLatestGeneration')};
 for(let i=0;i<4;i++){start(r,tick(r,10));assert.deepEqual({...r.global.get('homePvControlAdapterLatestGeneration')},gens);}
 const emitted=finish(r,active),main=emitted.filter(m=>m.hpvcInverterWrite);
 assert.equal(main.length,2);assert.deepEqual(main.map(m=>m.hpvcInverterWrite.controlKey),['pv1','pv2']);
 assert(main.every(m=>m.payload.data.value===3000));
});

test('maintenance waits beyond verification age while a limiting call remains live',()=>{
 const r=setup({current:3000,pre:false});r.states['sensor.pv'].state='2500';r.refresh();
 const old=start(r,r.cycle());assert(old.hpvcInverterWrite);assert(old.payload.data.value<3000);
 r.states['sensor.pv'].state='0';tick(r,10);tick(r,120);
 assert(!r.global.get('homePvControlNightRestoreFullConfirmation')?.confirmed);
 r.run('a622e5af64d3601e',{});r.states['input_boolean.hpvc_enabled'].state='off';tick(r,1);
 assert(r.global.get('homePvControlAdapterScheduler').busy);allBlocked(r);
 tick(r,200);allBlocked(r);assert(r.global.get('homePvControlAdapterScheduler').busy);
});

test('registered unsent requests block maintenance and nighttime proof',()=>{
 const r=setup({current:3000,pre:false});r.states['sensor.pv'].state='2500';r.refresh();r.cycle();
 r.states['sensor.pv'].state='0';tick(r,10);tick(r,120);
 assert(!r.global.get('homePvControlNightRestoreFullConfirmation')?.confirmed);
 r.run('a622e5af64d3601e',{});r.states['input_boolean.hpvc_enabled'].state='off';tick(r,1);allBlocked(r);
});

test('maintenance resumes after old limiting call drains and fresh full restoration completes',()=>{
 const r=setup({current:3000,pre:false});r.states['sensor.pv'].state='2500';r.refresh();
 const old=start(r,r.cycle());r.states['sensor.pv'].state='0';tick(r,10);tick(r,120);
 r.run('a622e5af64d3601e',{});r.states['input_boolean.hpvc_enabled'].state='off';const request=tick(r,1);start(r,request);allBlocked(r);
 r.states['sensor.limit'].state=String(old.payload.data.value);let next=r.run(NEXT,old);
 if(!next)next=start(r,tick(r,1));assert(next?.hpvcInverterWrite);assert.equal(next.payload.data.value,3000);
 r.now+=1000;r.states['sensor.limit'].state='3000';r.refresh();r.run(NEXT,next);tick(r,31);
 assert.notEqual(r.global.get('homePvControlDisableRestoreState')?.active,true);
 assert(r.global.get('homePvControlNightRestoreFullConfirmation')?.confirmed);
 for(const id of WATCHERS){r.global.set('homePvControlUninstallShutdownActive',true);const out=r.run(id,{topic:'regression'});assert(out?.[0],id+' did not authorize after drain');}
});

test('a full readback predating a completed limiting call cannot authorize maintenance',()=>{
 const r=setup({current:3000,pre:false});r.states['sensor.pv'].state='2500';r.refresh();const observed=r.now;
 const old=start(r,r.cycle());r.now+=30000;r.refresh();r.run(NEXT,old);
 r.states['sensor.pv'].state='0';
 for(const seconds of [10,120]){r.now+=seconds*1000;r.refresh();r.states['sensor.hpvc_source_freshness'].attributes.pv1_last_reported_ms=observed;r.cycle(undefined,'timer');}
 r.cycle(undefined,'settings');assert(!r.global.get('homePvControlNightRestoreFullConfirmation')?.confirmed);
 r.states['input_boolean.hpvc_enabled'].state='off';r.cycle(undefined,'settings');allBlocked(r);
});

test('warm partial redeploy preserves in-flight main barrier before newer full target',()=>{
 const r=setup({current:1500});const old=r.run(NEXT,start(r,r.cycle()));assert.equal(old.payload.data.value,915);
 const oldLease=old.hpvcAdapterDispatchId;initialize(r);
 assert.equal(r.global.get('homePvControlAdapterScheduler').busy.id,oldLease);
 r.states['input_boolean.hpvc_enabled'].state='off';assert.equal(start(r,tick(r,10)),null);
 let next=r.run(NEXT,old);assert.equal(next.payload.action,'script.prepare');
 assert.equal(r.run(NEXT,old),null);assert.equal(r.global.get('homePvControlAdapterScheduler').busy.id,next.hpvcAdapterDispatchId);
 next=r.run(NEXT,next);assert.equal(next.payload.data.value,3000);finish(r,next);
 assert.equal(r.states['sensor.limit'].state,'3000');assert.equal(r.global.get('homePvControlAdapterScheduler').busy,null);
});

test('warm pre-action redeploy cancels unsent old main and dispatches current restore',()=>{
 const r=setup({current:1500});const old=start(r,r.cycle());initialize(r);
 r.states['input_boolean.hpvc_enabled'].state='off';assert.equal(start(r,tick(r,10)),null);
 const emitted=finish(r,r.run(NEXT,old));const main=emitted.filter(m=>m.hpvcInverterWrite);
 assert.equal(main.length,1);assert.equal(main[0].payload.data.value,3000);
});

test('cold persisted lease is visibly held and neither late callback nor time clears it',()=>{
 const r=setup({current:1500});const old=r.run(NEXT,start(r,r.cycle()));
 const saved=JSON.parse(JSON.stringify(Object.fromEntries(r.global.m)));
 for(const [k,v] of Object.entries(saved))r.global.set(k,v);
 r.global.set('homeassistant.homeAssistant.states',r.states);initialize(r);
 assert.equal(r.global.get('homePvControlAdapterScheduler').recoveryRequired,true);
 r.states['input_boolean.hpvc_enabled'].state='off';const m=tick(r,200);
 assert.equal(m.hpvc.halted,true);assert.equal(m.hpvc.status,'Inverter dispatch recovery required');
 assert.equal(start(r,m),null);assert.equal(r.run(NEXT,old),null);allBlocked(r);
 tick(r,1000);assert.equal(r.global.get('homePvControlAdapterScheduler').busy.id,old.hpvcAdapterDispatchId);
});

test('reconciled cold lease retains counters and rejects pre-recovery callbacks',()=>{
 const r=setup({current:1500});const old=r.run(NEXT,start(r,r.cycle()));
 const saved=JSON.parse(JSON.stringify(Object.fromEntries(r.global.m)));for(const [k,v] of Object.entries(saved))r.global.set(k,v);
 r.global.set('homeassistant.homeAssistant.states',r.states);initialize(r);
 // Model explicit operator reconciliation AFTER stopping HA actions and inspecting applied limits.
 r.global.set('homePvControlAdapterScheduler',null);initialize(r);r.states['input_boolean.hpvc_enabled'].state='off';
 const pre=start(r,tick(r,1));assert(pre);assert(pre.hpvcAdapterDispatchId>old.hpvcAdapterDispatchId);
 assert.equal(r.run(NEXT,old),null);finish(r,pre);assert.equal(r.states['sensor.limit'].state,'3000');
});

test('fresh startup without retained lease still dispatches normally',()=>{
 const r=setup({off:true});initialize(r);assert.equal(finish(r,start(r,r.cycle())).filter(m=>m.hpvcInverterWrite).length,1);
});
assert(passed>0,'test filter must match at least one check');
console.log(`${passed} dispatcher lifecycle checks passed`);
