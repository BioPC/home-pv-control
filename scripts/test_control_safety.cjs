// Behavioral regressions for the v1.6.0 audit fixes. No services or hardware run.
const assert = require('node:assert/strict');
const { Runtime, by } = require('./control_test_runtime.cjs');
let passed = 0;
function test(name, fn) {
    if (process.argv[2] && !new RegExp(process.argv[2]).test(name)) return;
    fn(); console.log('PASS ' + name); passed++;
}
function advance(r, seconds, pvAge = 0) { r.now += seconds * 1000; r.refresh(pvAge); }
function calls(h) { return (h.calls || []).filter(c => c.hpvcInverterWrite); }
function noWrites(h) { assert.equal(calls(h).length, 0); assert(!h.outputs?.[0]); }
function actionRuntime(percent = false) {
    const r = new Runtime(), s = r.states;
    s['input_select.hpvc_pv1_control_method'].state = 'Action/service';
    s['input_text.hpvc_pv1_action'].state = 'script.apply_limit';
    s['input_text.hpvc_pv1_pre_actions_json'].state = '[{"action":"script.prepare"}]';
    s['input_text.hpvc_pv1_post_actions_json'].state = '[{"action":"script.finish"}]';
    s['input_text.hpvc_pv1_readback_entity'].state = 'sensor.limit';
    s['sensor.limit'] = { state: percent ? '49.7' : '1500', attributes: {} };
    s['sensor.pv'].state = '1200';
    if (percent) s['input_select.hpvc_pv1_limit_unit'].state = 'Percent';
    r.refresh(); return r;
}
const START = '57dc0986bf249cd3', NEXT = '3f890e176d2b747b', FAIL = '548464084e431806';
function drain(r,batch){let msg=r.run(START,batch);for(let i=0;msg&&i<100;i++)msg=r.run(NEXT,msg);assert.equal(msg,null);}

test('stale zero PV above horizon cannot start or finish Night Restore', () => {
    const r = new Runtime(); r.states['number.inv1'].state = '500'; r.states['sensor.pv'].state = '0'; r.refresh(600000);
    for (let i = 0; i < 2; i++) {
        const h = r.cycle().hpvc;
        assert.equal(h.nightRestorePending, false); assert.equal(h.nightRestoreActive, false);
        assert.equal(h.halted, true); noWrites(h); advance(r, 120, 720000);
    }
});
test('fresh sustained low PV still restores after 120 seconds', () => {
    const r = new Runtime(); r.states['number.inv1'].state = '500'; r.states['sensor.pv'].state = '0'; r.refresh();
    assert.equal(r.cycle().hpvc.nightRestorePending, true); advance(r, 120);
    const h = r.cycle().hpvc; assert.equal(h.nightRestoreActive, true); assert.equal(calls(h)[0].payload.data.value, 3000);
});
test('PV disappearing after a fresh night start needs below-horizon corroboration', () => {
    for (const night of [false, true]) {
        const r = new Runtime(); r.states['number.inv1'].state = '500'; r.states['sensor.pv'].state = '0'; r.refresh();
        r.cycle(); r.states['sensor.pv'].state = 'unavailable'; r.states['sun.sun'].state = night ? 'below_horizon' : 'above_horizon';
        advance(r, 120); const h = r.cycle().hpvc;
        assert.equal(h.nightRestoreActive, night); if (!night) noWrites(h);
    }
});
test('invalid PV transport, missing/future timestamp and stale snapshot cannot prove low PV', () => {
    for (const mutate of [
        a => { a.freshness_transport = 'invalid'; }, a => { delete a.pv_last_reported_ms; },
        a => { a.pv_last_reported_ms += 61000; }, a => { a.snapshot_epoch_ms -= 91000; }
    ]) {
        const r = new Runtime(); r.states['sensor.pv'].state = '0'; r.refresh();
        mutate(r.states['sensor.hpvc_source_freshness'].attributes); const h = r.cycle().hpvc;
        assert.equal(h.pvPowerFresh, false); assert.equal(h.nightRestorePending, false); noWrites(h);
    }
});
test('stale numeric recovery cannot end an established Night Restore', () => {
    const r = new Runtime(); r.states['sensor.pv'].state = '0'; r.refresh(); r.cycle(); advance(r, 120); r.cycle();
    r.states['sensor.pv'].state = '1000'; advance(r, 31, 600000);
    assert.equal(r.cycle().hpvc.nightRestoreActive, true);
    advance(r, 1); r.cycle(); advance(r, 31); assert.equal(r.cycle().hpvc.nightRestoreActive, false);
});
test('import recovery increases from the current ceiling despite low measured PV', () => {
    const r = new Runtime(); r.states['number.inv1'].state = '1500'; r.states['sensor.pv'].state = '400'; r.states['sensor.grid'].state = '200'; r.refresh();
    const h = r.cycle().hpvc; assert.equal(h.importRecalcActive, true); assert(h.targetTotal > 1500);
    assert.equal(calls(h)[0].payload.data.value, 1700);
});
test('import recovery remains upward at low PV, under partial outage, and after settling timeout', () => {
    for (const variant of ['low', 'partial', 'timeout', 'full']) {
        const r = new Runtime(); r.states['number.inv1'].state = variant === 'full' ? '3000' : '1500';
        r.states['sensor.pv'].state = '20'; r.states['sensor.grid'].state = '200';
        if (variant === 'partial') { r.states['input_number.hpvc_inverter_count'].state = '2'; r.states['number.inv2'].state = 'unavailable'; }
        if (variant === 'timeout') r.global.set('homePvControlPvPostWriteSettle', {writeMs:r.now-1000000,requested:[{entity:'pv1',value:1500}],limitTotalBefore:1400,pvPowerBefore:400,pvUpdatedMsBefore:r.now-1000000});
        r.refresh(); const h = r.cycle().hpvc;
        assert(h.targetTotal >= Number(r.states['number.inv1'].state));
        for (const c of calls(h)) assert(c.hpvcInverterWrite.targetWatts >= 1500);
    }
});
test('coarse Watt and Percent command steps cannot reverse import recovery', () => {
    const r=new Runtime(); r.states['number.inv1'].state='1100'; r.states['number.inv1'].attributes.step=1000;
    r.states['sensor.pv'].state='400'; r.states['sensor.grid'].state='200'; r.refresh();
    assert(calls(r.cycle().hpvc)[0].payload.data.value>=1100);
    const p=actionRuntime(true); p.states['sensor.limit'].state='40.1'; p.states['input_number.hpvc_pv1_action_step'].state='20';
    p.states['sensor.pv'].state='400'; p.states['sensor.grid'].state='200'; p.refresh();
    assert(calls(p.cycle().hpvc)[0].payload.data.value>=40.1);
});
test('off-grid percentage rounding cannot write during cooldown', () => {
    const r = actionRuntime(true); r.cycle('bf031913c0a1facd'); r.global.set('homePvControlActionCommandState', {pv1:1491});
    r.global.set('homePvControlCooldownUntilMs', r.now+30000); advance(r, 1);
    const h = r.cycle().hpvc; assert.equal(h.canChangePv, false); assert.equal(h.pvAction, 'none'); noWrites(h);
});
test('coarse Watt readback also remains held during cooldown', () => {
    const r=new Runtime(); r.states['number.inv1'].state='1491'; r.states['number.inv1'].attributes.step=100;
    r.global.set('homePvControlCooldownUntilMs',r.now+30000); r.refresh(); noWrites(r.cycle().hpvc);
});
test('recovery rebalance remains authorized only outside cooldown', () => {
    for(const cooldown of [false,true]) {
        const r=new Runtime(); r.states['input_number.hpvc_inverter_count'].state='2';
        r.states['number.inv1'].state='2000'; r.states['number.inv2'].state='1000'; r.states['sensor.grid'].state='0';
        r.global.set('homePvControlInverterRebalancePending',{id:r.now,requestedAt:r.now,names:['PV2']});
        if(cooldown)r.global.set('homePvControlCooldownUntilMs',r.now+30000);
        r.refresh(); const h=r.cycle().hpvc;
        if(cooldown) noWrites(h); else {assert.equal(h.recoveryRebalanceAuthorized,true);assert.equal(calls(h).length,2);}
    }
});
test('heartbeat and initial synchronization cannot bypass cooldown', () => {
    for (const cached of [false, true]) {
        const r = actionRuntime(true); r.states['input_number.hpvc_pv1_refresh_seconds'].state = '1'; r.cycle('bf031913c0a1facd');
        if (cached) r.global.set('homePvControlActionCommandState', {pv1:1491});
        r.global.set('homePvControlCooldownUntilMs', r.now+30000); advance(r, 1); noWrites(r.cycle().hpvc);
    }
});
test('off-grid held percentage cannot write while a previous command is pending', () => {
    const r = actionRuntime(true); r.cycle('bf031913c0a1facd'); r.global.set('homePvControlActionCommandState', {pv1:1491});
    r.global.set('homePvControlPendingWriteVerification', {requested:[{entity:'pv1',value:1400}],requested_ts:r.now,checked:false,action:'adjust'});
    advance(r,1); const h=r.cycle().hpvc; assert.equal(h.pvWriteLockActive,true); noWrites(h);
});
test('authorized percentage adjustment still quantizes and stays within bounds', () => {
    const r=actionRuntime(true), h=r.cycle().hpvc; const c=calls(h)[0]; assert(c);
    assert.equal(c.payload.data.value, Math.round(c.payload.data.value)); assert(c.payload.data.value>=0 && c.payload.data.value<=100);
});
test('negative-price minimum retains its explicit cooldown override', () => {
    const r=actionRuntime(true); r.states['sensor.allin'].state='-0.1'; r.global.set('homePvControlCooldownUntilMs',r.now+30000);
    const h=r.cycle().hpvc; assert.equal(h.pvAction,'minimum'); assert.equal(calls(h)[0].payload.data.value,0);
});
test('manual-disable restoration remains unresolved through telemetry loss and completes on full readback', () => {
    const r=new Runtime(); r.states['number.inv1'].state='500'; r.states['input_boolean.hpvc_enabled'].state='off'; r.refresh();
    const first=r.cycle();assert.equal(calls(first.hpvc)[0].payload.data.value,3000);drain(r,first.hpvc.outputs[0]);
    r.states['number.inv1'].state='unavailable'; advance(r,10); const missing=r.cycle().hpvc;
    assert.equal(r.global.get('homePvControlLastDisableRestore'),undefined); assert.equal(r.global.get('homePvControlDisableRestoreState').active,true);
    assert(missing.status.includes('verification pending')); noWrites(missing);
    r.states['number.inv1'].state='3000'; advance(r,10); r.cycle();
    assert.equal(r.global.get('homePvControlLastDisableRestore').result,'Completed'); assert.equal(r.global.get('homePvControlLastDisableRestore').pvRestored,true);
});
test('one full reachable inverter cannot conceal another unresolved restore', () => {
    const r=new Runtime(); r.states['input_number.hpvc_inverter_count'].state='2'; r.states['number.inv1'].state='500'; r.states['number.inv2'].state='500';
    r.states['input_boolean.hpvc_enabled'].state='off'; r.refresh(); drain(r,r.cycle().hpvc.outputs[0]);
    r.states['number.inv1'].state='3000'; r.states['number.inv2'].state='unavailable'; advance(r,10); r.cycle();
    assert.equal(r.global.get('homePvControlLastDisableRestore'),undefined); assert(r.global.get('homePvControlDisableRestoreState').active);
    r.states['number.inv2'].state='3000'; advance(r,10); r.cycle(); assert.equal(r.global.get('homePvControlLastDisableRestore').result,'Completed');
});
test('removing an inverter during restoration preserves its unresolved obligation', () => {
    const r=new Runtime(); r.states['input_number.hpvc_inverter_count'].state='2'; r.states['number.inv1'].state='500'; r.states['number.inv2'].state='500';
    r.states['input_boolean.hpvc_enabled'].state='off'; r.refresh(); r.cycle();
    r.states['input_number.hpvc_inverter_count'].state='1'; r.states['number.inv1'].state='3000'; advance(r,10); const h=r.cycle().hpvc;
    assert.equal(r.global.get('homePvControlLastDisableRestore'),undefined); assert(r.global.get('homePvControlDisableRestoreState').active);
    assert(h.reason.includes('Waiting for independent'));
});
test('removing or reconfiguring a restore obligation does not fabricate completion', () => {
    const r=new Runtime(); r.states['number.inv1'].state='500'; r.states['input_boolean.hpvc_enabled'].state='off'; r.refresh(); r.cycle();
    r.states['input_number.hpvc_pv1_full_limit'].state='2500'; r.states['number.inv1'].state='2500'; advance(r,10); r.cycle();
    assert.equal(r.global.get('homePvControlLastDisableRestore'),undefined); assert(r.global.get('homePvControlDisableRestoreState').active);
});
test('open-loop command cache cannot prove manual-disable physical restoration', () => {
    const r=actionRuntime(); r.states['input_text.hpvc_pv1_readback_entity'].state=''; r.states['input_boolean.hpvc_enabled'].state='off'; r.refresh();
    r.cycle(); assert.equal(r.global.get('homePvControlLastDisableRestore'),undefined); assert(r.global.get('homePvControlDisableRestoreState').active);
});
test('new disable waits for old pre-action and suppresses its old main/post steps', () => {
    const r=actionRuntime(); const first=r.cycle(); const old=r.run(START,first.hpvc.outputs[0]); assert.equal(old.payload.action,'script.prepare');
    r.states['input_boolean.hpvc_enabled'].state='off'; advance(r,10); const restore=r.cycle();
    assert.equal(r.run(START,restore.hpvc.outputs[0]),null);
    const pre=r.run(NEXT,old); assert.equal(pre.payload.action,'script.prepare');
    const main=r.run(NEXT,pre); assert.equal(main.payload.data.value,3000);
    const post=r.run(NEXT,main); assert.equal(post.payload.action,'script.finish'); assert.equal(r.run(NEXT,post),null);
});
test('an already-sent old main drains before the new full-output command', () => {
    const r=actionRuntime(); const oldPre=r.run(START,r.cycle().hpvc.outputs[0]); const oldMain=r.run(NEXT,oldPre);
    assert.equal(oldMain.payload.data.value,915); r.states['input_boolean.hpvc_enabled'].state='off'; advance(r,10);
    assert.equal(r.run(START,r.cycle().hpvc.outputs[0]),null);
    const pre=r.run(NEXT,oldMain); assert.equal(pre.payload.action,'script.prepare');
    const main=r.run(NEXT,pre); assert.equal(main.payload.data.value,3000);
    assert.equal(r.run(NEXT,oldMain),null); // Duplicate callback cannot release the new main.
    assert.equal(r.global.get('homePvControlAdapterScheduler').busy.id,main.hpvcAdapterDispatchId);
});
test('full readback cannot complete disable while an old main is still in flight', () => {
    const r=actionRuntime(); const old=r.run(NEXT,r.run(START,r.cycle().hpvc.outputs[0]));
    r.states['input_boolean.hpvc_enabled'].state='off'; r.states['sensor.limit'].state='3000'; advance(r,10); r.cycle();
    assert.equal(r.global.get('homePvControlLastDisableRestore'),undefined); assert(r.global.get('homePvControlDisableRestoreState').active);
    assert.equal(r.run(NEXT,old),null);
});
test('old failure cannot erase a newer restore request before its queue starter runs', () => {
    const r=actionRuntime(); const old=r.run(START,r.cycle().hpvc.outputs[0]);
    r.states['input_boolean.hpvc_enabled'].state='off'; advance(r,10); const restore=r.cycle();
    const expected=JSON.stringify(r.global.get('homePvControlPendingWriteVerification'));
    old.error={message:'delayed old failure'}; const error=r.run(FAIL,old);
    assert.equal(error[0],null); assert.equal(JSON.stringify(r.global.get('homePvControlPendingWriteVerification')),expected);
    assert.equal(r.run(NEXT,error[1]),null);
    const pre=r.run(START,restore.hpvc.outputs[0]); assert.equal(r.run(NEXT,pre).payload.data.value,3000);
});
test('current pre-action failure stops that inverter while another inverter continues', () => {
    const r=actionRuntime(); r.states['input_number.hpvc_inverter_count'].state='2'; r.refresh();
    const pre=r.run(START,r.cycle().hpvc.outputs[0]); pre.error={message:'prepare failed'};
    const error=r.run(FAIL,pre); assert.equal(error[0].payload.action,'persistent_notification.create');
    const other=r.run(NEXT,error[1]); assert.equal(other.hpvcInverterWrite.controlKey,'pv2'); assert.equal(other.payload.action,'number.set_value');
    assert.equal(r.global.get('homePvControlActionCommandState').pv1,undefined);
    assert(r.global.get('homePvControlPendingWriteVerification').requested.every(x=>x.entity!=='pv1'));
});
test('live disable, adapter changes and maintenance cancel old continuations before another evaluation', () => {
    for(const mutate of [r=>{r.states['input_boolean.hpvc_enabled'].state='off';}, r=>{r.states['input_text.hpvc_pv1_action'].state='script.new_limit';}, r=>{r.global.set('homePvControlUninstallShutdownActive',true);}]) {
        const r=actionRuntime(); const old=r.run(START,r.cycle().hpvc.outputs[0]); mutate(r);
        assert.equal(r.run(NEXT,old),null); assert.equal(r.global.get('homePvControlAdapterResync').pv1,true);
    }
});
test('automatic input-fault pause suppresses an old preparatory continuation', () => {
    const r=actionRuntime(); const old=r.run(START,r.cycle().hpvc.outputs[0]);
    r.states['sensor.grid'].state='unavailable'; advance(r,10); assert(r.cycle().hpvc.halted); assert.equal(r.run(NEXT,old),null);
});
test('deployment drains the old pre-action and cancels its remaining steps', () => {
    const r=actionRuntime(); const batch=r.cycle().hpvc.outputs[0]; const old=r.run(START,batch);
    new Function('global',by[START].initialize)(r.global);
    assert.equal(r.run(NEXT,old),null); assert.equal(r.global.get('homePvControlAdapterResync').pv1,true);
    assert.equal(r.run(START,batch),null);
});
test('auto OpenDTU disable verification uses the same HA last_reported slot freshness proof as manual Number controllers', () => {
    const r = new Runtime();
    const e='number.hms_2000_4t_limit_nonpersistent_absolute';
    r.states['input_number.hpvc_inverter_count'].state='0';
    r.states['input_boolean.hpvc_enabled'].state='off';
    r.states[e]={state:'500',attributes:{min:0,max:2250,step:1,unit_of_measurement:'W'},last_updated:new Date(r.now-1000).toISOString(),last_changed:new Date(r.now-1000).toISOString()};
    r.global.set('homePvControlOpenDtuRegistry',{controllers:[{device_id:'od1',limit_entity:e}],registry_entities:[e],refreshed_at:r.now});
    r.global.set('homePvControlOpenDtuRatedPowerCache',{'device:od1':{max_power:2000,source:'OpenDTU API',updated_at:r.now}});
    r.refresh();
    const first=r.cycle(); assert.equal(calls(first.hpvc)[0]?.payload?.data?.value,2000); drain(r,first.hpvc.outputs[0]);
    advance(r,10);
    r.states[e].state='2000'; r.states[e].last_updated=new Date(r.now-600000).toISOString(); r.states[e].last_changed=new Date(r.now-600000).toISOString();
    // Node-RED's cached entity object may not expose HA-core last_reported for an unchanged value.
    // The HA template freshness sensor is authoritative and must let auto OpenDTU verify exactly
    // like a manual Number controller.
    r.states['sensor.hpvc_source_freshness']={state:'ok',attributes:{freshness_transport:'ha_template_last_reported_snapshot',snapshot_epoch_ms:r.now,pv1_last_reported_ms:r.now}};
    r.refresh(); r.cycle();
    assert.equal(r.global.get('homePvControlLastDisableRestore')?.result,'Completed');
});

test('auto Enphase disable verification uses the same HA last_reported slot freshness proof as manual Number controllers', () => {
    const r = new Runtime();
    const lim='number.envoy_dpel_limit', sw='switch.envoy_dpel_enabled', md='select.envoy_dpel_mode';
    r.states['input_number.hpvc_inverter_count'].state='0';
    r.states['input_boolean.hpvc_enabled'].state='off';
    r.states[lim]={state:'500',attributes:{min:0,max:3000,step:1,unit_of_measurement:'W'},last_updated:new Date(r.now-1000).toISOString(),last_changed:new Date(r.now-1000).toISOString()};
    r.states[sw]={state:'on',attributes:{},last_updated:new Date(r.now).toISOString()};
    r.states[md]={state:'Production',attributes:{options:['Production','Export']},last_updated:new Date(r.now).toISOString()};
    r.global.set('homePvControlEnphaseRegistry',{controllers:[{device_id:'ep1',limit_entity:lim,enable_entity:sw,mode_entity:md}],registry_entities:[lim,sw,md],refreshed_at:r.now});
    r.refresh();
    const first=r.cycle(); assert.equal(calls(first.hpvc)[0]?.payload?.data?.value,3000); drain(r,first.hpvc.outputs[0]);
    advance(r,10);
    r.states[lim].state='3000'; r.states[lim].last_updated=new Date(r.now-600000).toISOString(); r.states[lim].last_changed=new Date(r.now-600000).toISOString();
    r.states['sensor.hpvc_source_freshness']={state:'ok',attributes:{freshness_transport:'ha_template_last_reported_snapshot',snapshot_epoch_ms:r.now,pv1_last_reported_ms:r.now}};
    r.refresh(); r.cycle();
    assert.equal(r.global.get('homePvControlLastDisableRestore')?.result,'Completed');
});

assert(passed>0,'test filter must match at least one check');
console.log(passed+' control safety regression checks passed');
