// Execute shipped configuration and transition functions with persistent context.
const assert=require('assert');
const {Runtime,fixture}=require('./control_test_runtime.cjs');
const READ='8b490d1484a538d7',TRANS='7d3a4ec873d023a2';
const r=new Runtime(fixture());
r.states['input_number.hpvc_inverter_count'].state='2';
function toggle(slot,disabled){r.states[`input_boolean.hpvc_pv${slot}_control_disabled`]={state:disabled?'on':'off',attributes:{}};}
toggle(1,false);toggle(2,false);
function cycle(enabled=true){
 r.now+=10000;r.refresh();
 const m={hpvc:{cycleStates:r.states,now:r.now,insightsEnabled:enabled}};
 r.run(READ,m);
 r.run(TRANS,m);
 return (m.hpvc.newInsights||[]).filter(x=>x.key.includes('| PV control permission |'));
}
assert.equal(cycle().length,0,'initial observation only seeds state');
toggle(2,true);
assert.match(cycle()[0].line,/1 of 2.*PV2/);
for(let n=0;n<20;n++)assert.equal(cycle().length,0,'no repeated 10-second Insight');
toggle(1,true);
assert.match(cycle()[0].line,/all PV controllers.*monitoring only/);
assert.equal(cycle().length,0);
toggle(2,false);
assert.match(cycle()[0].line,/PV2 returned to HPVC control/);
r.states['number.inv2'].state='unavailable';
assert.equal(cycle().length,0,'outage is not a permission change');
toggle(2,true);
assert.match(cycle()[0].line,/all PV controllers/,'unavailable valid controller still participates in permission accounting');
toggle(1,false);toggle(2,false);
assert.match(cycle()[0].line,/PV1, PV2 returned/);
toggle(1,true);toggle(2,true);
assert.equal(cycle(false).length,0,'Insights disabled');
assert.equal(cycle(true).length,0,'no replay on enable');
toggle(1,false);
assert.match(cycle()[0].line,/PV1 returned/);
// Replacement and empty slots never invent a returned/excluded edge.
r.states['input_text.hpvc_pv1_limit_number'].state='number.replacement';
toggle(1,true);
assert.equal(cycle().length,0,'new controller baseline');
r.states['input_text.hpvc_pv1_limit_number'].state='';
assert.equal(cycle().length,0,'empty slot ignored');
toggle(2,false);
assert.match(cycle()[0].line,/PV2 returned/);
console.log('PASS controller permission transitions, deduplication, outages, replacement and Insights gating');
