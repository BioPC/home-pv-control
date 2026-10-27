const assert=require('assert/strict');
const {Runtime}=require('./control_test_runtime.cjs');
const NODE='4e29c5113e825239';
let passed=0;
function test(name,fn){fn(); console.log('PASS '+name); passed++;}
function base(overrides={}){
  return {hpvc:Object.assign({
    halted:false, now:1800000000000, runtimeTiming:{stages:{},lastMarkMs:1800000000000},
    activeSubStrategyNormalized:'charge', hbcControlRequested:true, hbcExecutionStateAvailable:true,
    priceLimitingActive:true, rememberedPriceLimiting:true, selectedBatteryFull:false,
    hbcPriorityConfigurationValid:true, controlHbc:true, wantsMinimumPv:false,
    hbcBatterySummary:{usableCount:1,batteries:[{priorityEligible:true,soc:50}]},
    hbcUsableBatteryCount:1, selectedBatteryNormalAvailableChargePower:1000,
    selectedBatteryTaperAvailableChargePower:0, selectedBatteryPowerTotal:0,
    selectedBatteryIsCharging:false, inverters:[{current:1000}], currentLimitTotal:1000,
    totalFull:3000,totalMin:0,grid:0,exportStart:-150,deadband:25,cooldownMs:30000,
    pvPower:1500,minPvPower:100,hbcPrioritizedBattery:1,hbcBatteryOrder:[1],
    hbcPriorityCycleMode:'Configured order'
  },overrides)};
}
function run(r, overrides={}){return r.run(NODE,base(overrides)).hpvc;}

test('Charge request without confirmed charging enters Waiting and can release PV',()=>{
  const r=new Runtime(); const h=run(r);
  assert.equal(h.chargePriorityState,'waiting');
  assert.equal(h.hbcChargePriorityDisplayState,'waiting');
  assert.equal(h.hbcChargePriority,true);
  assert(h.hbcChargePriorityIncrease>0);
});

test('confirmed battery charging enters Active',()=>{
  const r=new Runtime(); const h=run(r,{selectedBatteryPowerTotal:-500,selectedBatteryIsCharging:true});
  assert.equal(h.chargePriorityState,'active');
  assert.equal(h.hbcChargePriorityDisplayState,'active');
  assert.equal(h.chargePriorityDiagnostics.batteryChargingConfirmed,true);
});

test('loss of confirmed charge enters bounded Exit hold and transition settle',()=>{
  const r=new Runtime();
  let h=run(r,{selectedBatteryPowerTotal:-500,selectedBatteryIsCharging:true});
  assert.equal(h.chargePriorityState,'active');
  r.now+=1000;
  h=run(r,{now:r.now,selectedBatteryPowerTotal:0,selectedBatteryIsCharging:false});
  assert.equal(h.chargePriorityState,'exit_hold');
  assert.equal(h.chargePriorityDiagnostics.exitHoldActive,true);
  assert.equal(h.chargePriorityDiagnostics.transitionSettleActive,true);
});

test('taper region uses a conservative capacity-scaled step cap',()=>{
  const r=new Runtime(); const h=run(r,{
    hbcBatterySummary:{usableCount:1,batteries:[{priorityEligible:true,soc:98}]},
    selectedBatteryNormalAvailableChargePower:0, selectedBatteryTaperAvailableChargePower:1000
  });
  assert.equal(h.hbcTaperPriority,true);
  assert.equal(h.chargePriorityDiagnostics.stepCap,90); // 3% of 3000 W at >=98% SOC
  assert(h.hbcChargePriorityIncrease<=90);
});

test('persistent export enables fallback after 30 seconds',()=>{
  const r=new Runtime();
  let h=run(r,{grid:-500,selectedBatteryPowerTotal:-500,selectedBatteryIsCharging:true});
  assert.equal(h.hbcExportFallbackActive,false);
  r.now+=31000;
  h=run(r,{now:r.now,grid:-500,selectedBatteryPowerTotal:-500,selectedBatteryIsCharging:true});
  assert.equal(h.hbcExportFallbackActive,true);
  assert.equal(h.hbcExportLimitingSuppressed,false);
});

test('negative-price minimum context keeps Charge Priority off',()=>{
  const r=new Runtime(); const h=run(r,{wantsMinimumPv:true,priceLimitingActive:true});
  // The surrounding engine owns the negative-price request; Charge Priority must not become operational.
  assert.equal(h.hbcChargePriorityOperational,false);
});

console.log(passed+' HBC Charge Priority regression checks passed');
