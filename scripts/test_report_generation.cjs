const assert=require('assert/strict');
const fs=require('fs'),path=require('path'),os=require('os');
const {Runtime}=require('./control_test_runtime.cjs');
const r=new Runtime();
const now=r.now;
const work={
 version:'1.6.0',reportTimeZone:'Europe/Amsterdam',generatedAt:now,generated:'01-01-2027 00:00:00',
 batteryDiagnostics:{ts:now,usableCount:1,uncertainExcluded:0,unavailableExcluded:0,controlDisabledExcluded:0},
 chargePriorityDiagnostics:{ts:now,state:'active',displayReason:'fixture',reason:'fixture',increasePossible:true,eligibleBatteryCount:1,below90EligibleCount:1,taperEligibleCount:0,combinedBatteryHeadroom:1000,normalBatteryHeadroom:1000,taperBatteryAllowance:0,existingGridExport:0,netAbsorbableHeadroom:1000,remainingInverterCapacity:2000,stepCap:1000,calculatedIncrease:650,targetTotal:1650,deadband:25,prioritizedBattery:1,batteryOrder:[1],priorityCycleMode:'Configured order',stateMachineState:'active',confirmedChargeEnterThreshold:50,confirmedChargeRemainThreshold:25,batteryChargePower:500,batteryChargingConfirmed:true,responseWindowActive:false,responseWindowMs:15000,responseWindowRemainingMs:0,exitHoldActive:false,exitHoldMs:20000,exitHoldRemainingMs:0,persistentExportAgeMs:0,exportFallbackMs:30000,exportFallbackActive:false,exportLimitingSuppressed:false},
 enabled:true,externalReleaseRequested:false,externalReleaseActive:false,hbcControl:true,statusValue:'PV control active',reasonValue:'fixture',currentAction:'fixture',
 grid:0,pv:1500,market:0.01,allIn:0.10,
 settings:{targetExport:-25,deadband:25,exportStart:-150,importRestore:150,limitPrice:0,priceHysteresis:0.02,negativePriceHbcCharge:true,minimumPv:100,nightRestorePv:10,cooldownSeconds:60},
 configValid:true,hbcAvailable:true,
 decision:{exportTriggered:false,importTriggered:false,pvLimited:true,negativeMode:false,cooldown:false,deadbandInside:true,minimumPvBlock:false,gridError:25,pvTargetBaseline:'fixture',pvPostWriteSettling:false,pvPostWriteSettleAgeSeconds:0},
 inverters:[{name:'PV1',controlMethod:'Number entity',limitUnit:'Watts',current:1000,maximum:3000,minimum:0,calculatedTarget:1650,requestedTarget:1650,difference:650,atBoundary:false,writeRequired:true,verification:'Confirmed'}],
 inverterSummary:{configuredCount:1,availableCount:1,currentTotal:1000,minimumTotal:0,maximumTotal:3000,targetTotal:1650,requestedCount:1,verificationStatus:'Confirmed',lastWriteReason:'fixture',lastWriteTime:'fixture',lastVerificationTime:'fixture',diagnosticsTime:'fixture',diagnosticsAgeSeconds:0,dataSource:'fixture'},
 batteries:[{name:'M1',priorityEligible:true,soc:50,socMode:'Normal',headroomContribution:1000,normalHeadroom:1000,taperReleaseAllowance:0}],
 sensorHealth:[],insights:[],insightHistorySource:'fixture',activityRows:[],activitySummary:{},reportInsights:[],groupedInsights:[],insightSummary:{total:0,grouped:0,critical:0,warnings:0,information:0},
 targetAccuracy:95,factors:{tc:100,tbx:0,trms:10,tmae:5,toutp:2,tratio:1,tcoverp:100,tpolicyx:0,tgapx:0,tfs:'no_error',tctrlp:2,thloadp:1,tpvavailp:1,totherp:1},
 chargePriorityState:'active',chargePriorityActive:true,chargePriorityRequested:true,taperProbeActive:false,controlMode:'PV Limited',actionResult:'fixture',
 runtimeDiagnostics:{evaluationTime:'fixture',ageSeconds:0,warning:''},lastAdapterServiceError:null,disableRestoreState:{active:false},lastDisableRestore:null
};
const generation='1800000000000-abcd1234';
const runtime=require('./control_test_runtime.cjs');
const flowId=runtime.by['a67b7558a9d2250e'].z;
r.flows[flowId]=r.flows[flowId]||runtime.ctx();
r.flows[flowId].set('hpvcReportGenerationId',generation);
let msg={hpvcReportGenerationId:generation,hpvcReportWork:work,hpvcReportSnapshot:{'input_select.house_battery_strategy':{state:'Charge'},'input_select.house_battery_strategy_charge_goal':{state:'100'},'input_text.house_battery_strategy_active_sub_strategy':{state:'Charge'}},hpvcPerformanceDiagnostics:null,hpvcRateLimiterDiagnostics:{fullCycles:1,skippedCycles:0,lastFullAt:now,reason:'fixture'}};
for(const id of ['a83346bd7af628af','d49a821e53c3e774','156f69fef528bb92','91543a25f27ea40a','a67b7558a9d2250e']) msg=r.run(id,msg);
assert(msg.hpvcReport && msg.hpvcTxtReport && msg.hpvcHtmlReport);
assert(msg.hpvcTxtReport.includes('HPVC SUPPORT REPORT'));
assert(msg.hpvcTxtReport.includes('Version: 1.6.0'));
assert(msg.hpvcHtmlReport.includes('HPVC report'));
assert.equal(msg.hpvcReportParityOk,true);
// Exercise the same generation-scoped publication contract used by the shipped file+mv nodes.
msg.hpvcReportGenerationId=generation; msg.payload=msg.hpvcHtmlReport;
msg=r.run('342c62b69a81c38a',msg);
assert(msg && msg.filename.endsWith(`support-report.${generation}.tmp.html`));
// Write to a sandbox path, then verify generation immediately before atomic rename.
const dir=fs.mkdtempSync(path.join(os.tmpdir(),'hpvc-report-test-'));
const temp=path.join(dir,`support-report.${generation}.tmp.html`), final=path.join(dir,'support-report.html');
fs.writeFileSync(temp,msg.payload,'utf8');
msg.hpvcReportTempPath=`/tmp/hpvc-report-root/support-report.${generation}.tmp.html`;
let branches=r.run('dbc2293089791796',msg); assert(Array.isArray(branches) && branches[0]);
fs.renameSync(temp,final);
const published=fs.readFileSync(final,'utf8');
assert(published.includes('HPVC report'));
assert(published.includes('1.6.0'));
fs.rmSync(dir,{recursive:true,force:true});
console.log('PASS fixture report model -> TXT -> HTML -> parity -> generation-scoped atomic publication contract');
