// Run only in your existing authenticated HA browser tab's developer console.
// Reads only. No service, event, registry update, import, deploy or template call.
(async () => {
  const hass=document.querySelector('home-assistant')?.hass;
  if(!hass)throw Error('Open your existing Home Assistant tab first');
  const collection_started_at_utc=Date.now()/1000;
  const states=await hass.callWS({type:'get_states'});
  const ha=await hass.callWS({type:'get_config'});
  const partial=await hass.callWS({type:'config/entity_registry/list'});
  const devices=await hass.callWS({type:'config/device_registry/list'});
  const entries=await hass.callWS({type:'config_entries/get'});
  const entities=[];
  for(let i=0;i<partial.length;i+=100){
    const result=await hass.callWS({type:'config/entity_registry/get_entries',entity_ids:partial.slice(i,i+100).map(r=>r.entity_id)});
    entities.push(...Object.values(result).filter(Boolean));
  }
  const result={schema:'hpvc-ha-read-export/1',collected_at_utc:Date.now()/1000,ha:{version:ha.version,time_zone:ha.time_zone,collection_started_at_utc},states,entity_registry:entities,device_registry:devices,config_entries:entries};
  const text=JSON.stringify(result,null,2);
  if(new TextEncoder().encode(text).length>8*1024*1024)throw Error('Export too large; use scoped collector');
  // Chrome/Edge Developer Tools copy() copies to this computer's clipboard only.
  copy(text);
  console.info('Read export copied locally. Save as ha-raw-read.json; redact locally with site_audit.py before sharing. No token was exported.');
})();
