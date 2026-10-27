// Test-only Function-node runner: actual shipped wiring; mocked states, time and calls.
const fs=require('fs'),vm=require('vm');
const path=require('path');
const packageRoot=process.env.HPVC_TEST_PACKAGE || path.resolve(__dirname,'..');
const nodes=JSON.parse(fs.readFileSync(path.join(packageRoot,'node-red/hpvc_flow.json'),'utf8'));
const by=Object.fromEntries(nodes.map(n=>[n.id,n]));
function ctx(initial={}){const m=new Map(Object.entries(initial));return {get:k=>m.get(k),set:(k,v)=>m.set(k,v),m};}
function fixture(){
 const s={}; const put=(id,value,attributes={})=>s[id]={state:String(value),attributes};
 for(const id of ['hpvc_enabled','hpvc_notifications'])put('input_boolean.'+id,'on');
 for(const id of ['hpvc_auto_resume_pending','hpvc_external_release_request','hpvc_control_hbc_strategy','hpvc_negative_price_hbc_charge','hpvc_insights_enabled','hpvc_update_reload_required'])put('input_boolean.'+id,'off');
 const settings={hpvc_inverter_count:1,hpvc_pv_limiting_price:0,hpvc_battery_price_hysteresis:0.02,hpvc_export_start_threshold:-150,hpvc_export_stop_threshold:0,hpvc_import_restore_threshold:150,hpvc_pv_min_power_for_control:100,hpvc_pv_night_restore_power:10,hpvc_cooldown_seconds:30,hpvc_pv_adjust_deadband:25};
 for(const [k,v] of Object.entries(settings))put('input_number.'+k,v);
 for(const [helper,id,v] of [['grid_power','grid',-600],['market_price','market',-0.01],['all_in_price','allin',0.1],['pv_power','pv',2500]]){put('input_text.hpvc_'+helper+'_sensor','sensor.'+id);put('sensor.'+id,v);}
 put('sun.sun','above_horizon');
 for(let i=1;i<=10;i++){
  put(`input_select.hpvc_pv${i}_control_method`,'Number entity');put(`input_select.hpvc_pv${i}_limit_unit`,'Watts');
  for(const [k,v] of Object.entries({limit_number:`number.inv${i}`,readback_entity:'',action:'',value_field:'value',fixed_data_json:'{}',target_json:'{}',pre_actions_json:'[]',post_actions_json:'[]'}))put(`input_text.hpvc_pv${i}_${k}`,v);
  for(const [k,v] of Object.entries({full_limit:3000,low_limit:0,action_step:1,refresh_seconds:0}))put(`input_number.hpvc_pv${i}_${k}`,v);
  put(`number.inv${i}`,3000,{min:0,max:3000,step:1});
 }
 return s;
}
class Runtime {
 constructor(s=fixture()){this.states=s;this.now=1800000000000;this.global=ctx({'homePvControlPersistentHistoryReady':true,'homeassistant.homeAssistant.states':s});this.flows={};this.nodeContexts={};this.trace=[];}
 refresh(pvAge=0){const attrs={freshness_transport:'ha_template_last_reported_snapshot',snapshot_epoch_ms:this.now,grid_last_reported_ms:this.now,market_last_reported_ms:this.now,all_in_last_reported_ms:this.now,pv_last_reported_ms:this.now-pvAge};for(let i=1;i<=10;i++)attrs[`pv${i}_last_reported_ms`]=this.now;this.states['sensor.hpvc_source_freshness']={state:String(this.now),attributes:attrs};}
 run(id,msg){const n=by[id];const flow=this.flows[n.z]??=ctx();let now=this.now;class Clock extends Date{constructor(...a){super(...(a.length?a:[now]));}static now(){return now;}}
  const c={msg,flow,global:this.global,context:this.nodeContexts[id]??=ctx(),Date:Clock,console,node:{status:()=>{},warn:()=>{},error:(e)=>{throw Error(String(e));}},Buffer};
  return vm.runInNewContext('(function(){'+n.func+'\n})()',c,{timeout:3000});}
 cycle(stop='0c09a82aaa67452b',topic='settings'){
  let msg={topic},id='6498f50f6fea77b9';this.trace=[];
  for(let i=0;i<70;i++){
   const n=by[id];if(!n)throw Error('Missing '+id);
   if(n.type==='function'){msg=this.run(id,msg);if(Array.isArray(msg))msg=msg[0];this.trace.push([n.name,msg?.hpvc?.status,msg?.hpvc?.pvAction]);if(!msg)return null;if(id===stop){if(stop==='0c09a82aaa67452b'){msg=this.run('bb19169eb0446c5c',msg);msg=this.run('1da749636a1dfe1b',msg);}this.global.set('homePvControlRuntimeEvaluationLock',null);return msg;}}
   if(n.type==='link out')id=n.links[0];else id=n.wires?.[0]?.[0];
   if(!id)throw Error('End '+n.name);
  }throw Error('Too many nodes');
 }
}
if(require.main===module){const r=new Runtime();r.refresh();const m=r.cycle();console.log(JSON.stringify({trace:r.trace,hpvc:{status:m.hpvc.status,action:m.hpvc.pvAction,target:m.hpvc.targetTotal,calls:m.hpvc.calls}},null,2));}
module.exports={Runtime,fixture,by,ctx};
