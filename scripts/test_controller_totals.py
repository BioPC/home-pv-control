"""Render shipped controller totals against real runtime slot templates."""
import json
from pathlib import Path
import yaml
from test_enphase_ha_templates import base_states, add_enphase, add_opendtu, render, template_entity

ROOT=Path(__file__).resolve().parents[1]
config=yaml.safe_load((ROOT/'home assistant/hpvc_config.yaml').read_text(encoding='utf-8'))
dash=yaml.safe_load((ROOT/'home assistant/hpvc_dashboard.yaml').read_text(encoding='utf-8'))
def walk(v):
 if isinstance(v,dict):
  yield v
  for c in v.values(): yield from walk(c)
 elif isinstance(v,list):
  for c in v: yield from walk(c)
objects=list(walk(dash))
summary=next(x['content'] for x in objects if x.get('type')=='markdown' and '**Total inverters:**' in x.get('content',''))
runtime=template_entity(config,'hpvc_effective_inverter_runtime')
checks=0
def check(value):
 global checks
 checks+=1
 assert value, f'check {checks}'
def verify(s,total,manual,auto):
 count=render(runtime['state'],s)
 slots=json.loads(render(runtime['attributes']['runtime_json'],s))
 check(int(count)==total)
 for data in (json.dumps(slots),slots):
  s.add('sensor.hpvc_effective_inverter_runtime',count,{'runtime_json':data})
  output=render(summary,s)
  check(output.strip() == f'**Total inverters:** _{auto} auto-detected · {manual} manual_')
  check(len([line for line in output.splitlines() if line.strip()]) == 1)
 return slots

def manual(s,i,limit=None):
 s.add(f'input_select.hpvc_pv{i}_control_method','Number entity')
 s.add(f'input_text.hpvc_pv{i}_limit_number',limit or f'number.manual{i}')
 s.add(f'input_text.hpvc_pv{i}_readback_entity','')
 s.add(f'input_text.hpvc_pv{i}_action','')
 s.add(f'input_select.hpvc_pv{i}_limit_unit','Watts')
 s.add(f'input_number.hpvc_pv{i}_full_limit','2000')
 s.add(f'input_number.hpvc_pv{i}_low_limit','0')

# Zero is a first-class state: no manual capacity + no discovery means no runtime controller.
s=base_states();s.add('input_number.hpvc_inverter_count','0')
count=render(runtime['state'],s); slots=json.loads(render(runtime['attributes']['runtime_json'],s))
check(int(count)==0 and slots==[])
inverter_number=template_entity(config,'hpvc_inverters')
s.add('sensor.hpvc_effective_inverter_runtime','0',{'runtime_json':[]})
check(int(float(render(inverter_number['state'],s)))==0)
check(int(float(render(inverter_number['min'],s)))==0)
# Auto discovery raises the floor from zero without requiring a manual slot.
add_opendtu(s,'number.hms_1000_2t_limit_nonpersistent_absolute',maximum=1000)
count=render(runtime['state'],s); slots=json.loads(render(runtime['attributes']['runtime_json'],s)); s.add('sensor.hpvc_effective_inverter_runtime',count,{'runtime_json':slots})
check(int(count)==1)
check(int(float(render(inverter_number['state'],s)))==1)
check(int(float(render(inverter_number['min'],s)))==1)

# A reserved empty slot counts once; discovery reuses it without raising the helper.
s=base_states();verify(s,1,1,0)
add_enphase(s);verify(s,1,0,1)
check(s('input_number.hpvc_inverter_count')=='1')
# Appended controllers show up even though the manual-count helper is only one.
s=base_states();manual(s,1);add_enphase(s);verify(s,2,1,1)
check(s('input_number.hpvc_inverter_count')=='1')
s.add('input_number.hpvc_inverter_count','2');manual(s,2)
verify(s,3,2,1)
add_enphase(s,'envoy_other');verify(s,4,2,2)
s.add('input_boolean.hpvc_pv3_control_disabled','on');verify(s,4,2,2)
# Auto-detected OpenDTU uses the same generic auto-controller accounting.
s=base_states();add_opendtu(s);verify(s,1,0,1)
s=base_states();manual(s,1);add_opendtu(s);verify(s,2,1,1)

# A discoverable Enphase entity remains auto-classified even after its detected values are mirrored into the visible fields.
s=base_states();add_enphase(s);manual(s,1,'number.envoy_122113020461_dpel_limit');verify(s,1,0,1)
# Action/service also counts as manual.
s=base_states();s.add('input_select.hpvc_pv1_control_method','Action/service');s.add('input_text.hpvc_pv1_action','inverter.set_limit')
add_enphase(s);verify(s,2,1,1)
# Ten-slot ceiling and mixed reserved/reused manual slots.
s=base_states();manual(s,1)
for i in range(11):add_enphase(s,f'envoy_{i:02}')
verify(s,10,1,9)
# Generic labeling depends on assignment, not a specific adapter/brand token.
s=base_states();s.add('sensor.hpvc_effective_inverter_runtime','2',{'runtime_json':['number.future|Watts|2000|0|future-adapter|Number entity|auto','number.future2|Watts|2000|0|other-adapter|Number entity|auto']})
check('**Total inverters:** _2 auto-detected · 0 manual_' in render(summary,s))
check('Enphase' not in summary)
# Absent/malformed runtime never fabricates an apparently complete breakdown.
for raw in (None,'{bad',{},[]):
 s.add('sensor.hpvc_effective_inverter_runtime','3',{'runtime_json':raw})
 check('Breakdown unavailable' in render(summary,s))
s.add('sensor.hpvc_effective_inverter_runtime','unavailable')
check('**Total inverters:** _Unavailable_' in render(summary,s))
# Navigation and all diagnostic rows follow the effective total.
nav=next(o for o in objects if o.get('type')=='grid' and any(c.get('entity')=='script.hpvc_previous_inverter' for c in o.get('cards',[])))
check(nav['visibility']==[dict(condition='numeric_state',entity='sensor.hpvc_effective_inverter_runtime',above=1)])
for i in range(2,11):
 row=next(o for o in objects if o.get('row',{}).get('entity')==f'sensor.hpvc_pv{i}_actual_limit')
 check(row['conditions'][0]==dict(condition='numeric_state',entity='sensor.hpvc_effective_inverter_runtime',above=i-1))
# One persistent native numeric-input tile is used at every count, including zero.
inverter_tiles=[o for o in objects if o.get('type')=='tile' and o.get('entity')=='number.hpvc_inverters' and o.get('name')=='Inverters']
check(len(inverter_tiles)==1)
inverter_tile=inverter_tiles[0]
check(inverter_tile['features']==[dict(type='numeric-input',style='buttons')] and inverter_tile['features_position']=='inline')
# No special zero-state or positive-state wrapper remains; the number entity's dynamic min controls the minus button.
check(not any(o.get('type')=='conditional' and any(c.get('entity')=='number.hpvc_inverters' for c in o.get('conditions',[])) for o in objects))
# The visible Inverters control has a dynamic floor equal to the number of auto-detected controllers.
inverter_number=template_entity(config,'hpvc_inverters')
s=base_states(); add_opendtu(s,'number.hms_1000_2t_limit_nonpersistent_absolute',maximum=1000); add_opendtu(s,'number.hms_2000_4t_limit_nonpersistent_absolute',maximum=2000)
count=render(runtime['state'],s); slots=json.loads(render(runtime['attributes']['runtime_json'],s)); s.add('sensor.hpvc_effective_inverter_runtime',count,{'runtime_json':slots})
check(int(count)==2)
check(int(float(render(inverter_number['state'],s)))==2)
check(int(float(render(inverter_number['min'],s)))==2)
check(inverter_number['max']==10)
check(render(summary,s).strip()=='**Total inverters:** _2 auto-detected · 0 manual_')
# Increasing manual capacity remains allowed above the auto-detected floor.
s.add('input_number.hpvc_inverter_count','3')
check(int(float(render(inverter_number['state'],s)))==3)
check(int(float(render(inverter_number['min'],s)))==2)
check(any(o.get('name')=='Total inverters' and o.get('entity')=='sensor.hpvc_effective_inverter_runtime' for o in objects))
print(f'PASS effective controller totals, generic breakdown and navigation ({checks} checks)')
