"""Render the shipped status, switch availability and dashboard templates."""
import json
from pathlib import Path
import yaml
from test_enphase_ha_templates import base_states, add_enphase, render, template_entity, build_env

ROOT = Path(__file__).resolve().parents[1]
config = yaml.safe_load((ROOT / 'home assistant/hpvc_config.yaml').read_text(encoding='utf-8'))
dashboard = yaml.safe_load((ROOT / 'home assistant/hpvc_dashboard.yaml').read_text(encoding='utf-8'))
runtime = template_entity(config, 'hpvc_effective_inverter_runtime')
limit_validation = template_entity(config, 'hpvc_inverter_limit_validation')
checks = 0


def check(condition):
    global checks
    checks += 1
    assert condition, f'check {checks}'


def rows(s):
    value = json.loads(render(runtime['attributes']['controller_ui_json'], s))
    s.add('sensor.hpvc_effective_inverter_runtime', len(value), {'controller_ui_json': json.dumps(value)})
    return value


def status(s, expected, valid, slot=1):
    values = rows(s)
    check(values[slot-1].get('status') == expected and values[slot-1].get('valid') == valid)
    switch = template_entity(config, f'hpvc_pv{slot}_control')
    check(render(switch['availability'], s) == str(valid))
    # Permission is independent of detection/availability; no persistent flag is rewritten.
    s.add(f'input_boolean.hpvc_pv{slot}_control_disabled', 'on')
    check(render(switch['state'], s) == 'False')
    check(rows(s) == values)


s = base_states()
status(s, 'Not configured', False)
s.add('input_text.hpvc_pv1_limit_number', 'sensor.wrong_domain')
status(s, 'Incomplete', False)
s.add('input_text.hpvc_pv1_limit_number', 'number.missing')
status(s, 'Incomplete', False)
s.add('input_text.hpvc_pv1_limit_number', 'number.opendtu')
s.add('number.opendtu', '1500', {'min': 0, 'max': 2000})
status(s, 'Detected', True)
s.add('number.opendtu', 'unavailable', {'min': 0, 'max': 2000})
status(s, 'Unavailable', True)
s.add('number.opendtu', '1500', {'min': 0, 'max': 2000})
s.add('input_number.hpvc_pv1_low_limit', '2000')
status(s, 'Detected', True)
s.add('input_number.hpvc_pv1_low_limit', '2001')
status(s, 'Incomplete', False)

s = base_states()
s.add('input_select.hpvc_pv1_control_method', 'Action/service')
for name, value in {'action': 'inverter.set_limit', 'fixed_data_json': '{}', 'target_json': '{}',
                    'pre_actions_json': '[]', 'post_actions_json': '[]', 'readback_entity': 'sensor.limit'}.items():
    s.add('input_text.hpvc_pv1_' + name, value)
s.add('input_number.hpvc_pv1_action_step', '1')
s.add('input_number.hpvc_pv1_refresh_seconds', '0')
s.add('sensor.limit', '1000')
status(s, 'Configured', True)
s.add('sensor.limit', 'unavailable')
status(s, 'Unavailable', True)
for helper, value in [('fixed_data_json', '{bad'), ('target_json', '[]'), ('pre_actions_json', '[{}]'),
                      ('post_actions_json', '{}'), ('action', 'invalid'), ('readback_entity', 'sensor.missing')]:
    old = s('input_text.hpvc_pv1_' + helper)
    s.add('input_text.hpvc_pv1_' + helper, value)
    status(s, 'Incomplete', False)
    s.add('input_text.hpvc_pv1_' + helper, old)
s.add('input_text.hpvc_pv1_readback_entity', '')  # Existing command-cache mode remains supported.
status(s, 'Configured', True)

s = base_states()
add_enphase(s)
status(s, 'Detected', True)
s.add('switch.envoy_122113020461_dpel_enabled', 'unavailable')
status(s, 'Unavailable', True)
s.add('select.envoy_122113020461_dpel_mode', 'unavailable', {'options': ['Production', 'Export']})
status(s, 'Unavailable', True)
s.add('input_text.hpvc_pv1_limit_number', 'number.envoy_122113020461_dpel_limit')
s.add('select.envoy_122113020461_dpel_mode', 'Production', {'options': ['Production']})
status(s, 'Incomplete', False)

# Registry-based renamed triplets and all ten controller windows use the same contract.
s = base_states()
controllers = []
entities = []
for i in range(1, 11):
    s.add(f'input_number.hpvc_pv{i}_full_limit', '4000')
    s.add(f'input_number.hpvc_pv{i}_low_limit', '0')
    limit, enable, mode = f'number.site{i}_limit', f'switch.site{i}_enable', f'select.site{i}_mode'
    s.add(limit, '1000', {'min': 0, 'max': 4000})
    s.add(enable, 'on')
    s.add(mode, 'Production', {'options': ['Production', 'Export']})
    controllers.append(dict(limit_entity=limit, enable_entity=enable, mode_entity=mode))
    entities.extend([limit, enable, mode])
s.add('sensor.hpvc_enphase_registry', '10', {'controllers': controllers, 'registry_entities': entities})
for slot in range(1, 11):
    status(s, 'Detected', True, slot)


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


objects = list(walk(dashboard))
cards = [o for o in objects if o.get('type') == 'markdown' and 'Inverter status:' in o.get('content', '')]
check(len(cards) == 10)
for slot, card in enumerate(cards, 1):
    check('Inverter status:' in render(card['content'], s))
    conditionals = [o for o in objects if o.get('row', {}).get('entity') == f'switch.hpvc_pv{slot}_control']
    check(len(conditionals) == 1)
    check({c['state_not'] for c in conditionals[0]['conditions']} == {'unknown', 'unavailable'})
s = base_states()
rows(s)
check('Inverter status: Not configured' in render(cards[0]['content'], s))
check('alert-type="warning"' in render(cards[0]['content'], s))
s.add('input_text.hpvc_pv1_limit_number', 'bad')
rows(s)
check('alert-type="warning"' in render(cards[0]['content'], s))

# HA can preserve a template's JSON result as a native list. Its from_json filter
# need not accept lists; prove that consumers select the native branch directly.
def strict_from_json(value, default=None):
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default

for payload in ([dict(status='Detected', valid=True)], json.dumps([dict(status='Detected', valid=True)])):
    s.add('sensor.hpvc_effective_inverter_runtime', '1', {'controller_ui_json': payload})
    env = build_env(s)
    env.filters['from_json'] = strict_from_json
    check(env.from_string(template_entity(config, 'hpvc_pv1_control')['availability']).render().strip() == 'True')
    check('Detected' in env.from_string(cards[0]['content']).render())

# Auto-detected controllers keep the internal Detected state but render the
# integration brand in the user-facing dashboard status.
for kind, label in (('opendtu', 'Hoymiles detected'), ('enphase', 'Enphase detected')):
    payload = [dict(status='Detected', valid=True, source='auto', kind=kind)]
    s.add('sensor.hpvc_effective_inverter_runtime', '1', {'controller_ui_json': json.dumps(payload)})
    output = render(cards[0]['content'], s)
    check(f'Inverter status: {label}' in output)
    check('alert-type="success"' in output)

# Incomplete controllers keep their detection context in the user-facing label.
for kind, label in (('opendtu', 'Hoymiles detected but incomplete'), ('enphase', 'Enphase detected but incomplete')):
    payload = [dict(status='Incomplete', valid=False, source='auto', kind=kind)]
    s.add('sensor.hpvc_effective_inverter_runtime', '1', {'controller_ui_json': json.dumps(payload)})
    output = render(cards[0]['content'], s)
    check(f'Inverter status: {label}' in output)
    check('alert-type="warning"' in output)

# Manual Number controllers retain generic wording, with explicit detection context when incomplete.
payload = [dict(status='Detected', valid=True, source='manual', kind='manual-number')]
s.add('sensor.hpvc_effective_inverter_runtime', '1', {'controller_ui_json': json.dumps(payload)})
check('Inverter status: Detected' in render(cards[0]['content'], s))
payload = [dict(status='Incomplete', valid=False, source='manual', kind='manual-number')]
s.add('sensor.hpvc_effective_inverter_runtime', '1', {'controller_ui_json': json.dumps(payload)})
output = render(cards[0]['content'], s)
check('Inverter status: Detected but incomplete' in output)
check('alert-type="warning"' in output)
for payload in (None, '', '{broken', [], {}):
    s.add('sensor.hpvc_effective_inverter_runtime', '1', {'controller_ui_json': payload})
    check(render(template_entity(config, 'hpvc_pv1_control')['availability'], s) == 'False')
    check(render(cards[0]['content'], s) == '')
# Every counted but unfilled manual slot shows amber Not configured, including
# the screenshot case of two populated slots followed by an unfilled PV3.
s = base_states()
s.add('input_number.hpvc_inverter_count', '10')
for slot in range(1, 11):
    s.add(f'input_select.hpvc_pv{slot}_control_method', 'Number entity')
    s.add(f'input_select.hpvc_pv{slot}_limit_unit', 'Watts')
    s.add(f'input_number.hpvc_pv{slot}_full_limit', '0')
    s.add(f'input_number.hpvc_pv{slot}_low_limit', '0')
    for field in ('limit_number', 'readback_entity', 'action'):
        s.add(f'input_text.hpvc_pv{slot}_{field}', '')
for slot in range(1, 11):
    status(s, 'Not configured', False, slot)
    output = render(cards[slot-1]['content'], s)
    check('Inverter status: Not configured' in output and 'alert-type="warning"' in output)
s.add('input_number.hpvc_inverter_count', '3')
for slot in (1, 2):
    s.add(f'input_text.hpvc_pv{slot}_limit_number', f'number.manual{slot}')
    s.add(f'number.manual{slot}', '1000', {'min': 0, 'max': 2000})
    s.add(f'input_number.hpvc_pv{slot}_full_limit', '2000')
check([r['status'] for r in rows(s)] == ['Detected', 'Detected', 'Not configured'])
status(s, 'Not configured', False, 3)
check(render(cards[3]['content'], s) == '')  # Uncounted PV4 remains hidden/blank.

# Centralized Min/Max validation is the single HA source of truth for warnings
# and invalid-range gating. Per-slot binary sensors are compatibility projections only.
def refresh_limit_validation(s):
    validation_json = render(limit_validation['attributes']['validation_json'], s)
    rows_v = json.loads(validation_json)
    invalid = sum(1 for row in rows_v if row['status'] in ['unknown', 'min_above_max'])
    s.add('sensor.hpvc_inverter_limit_validation', str(invalid), {'validation_json': validation_json})
    for slot in range(1, 11):
        entity = template_entity(config, f'hpvc_pv{slot}_limit_range_invalid')
        state = 'on' if render(entity['state'], s) == 'True' else 'off'
        s.add(f'binary_sensor.hpvc_pv{slot}_limit_range_invalid', state)
    return rows_v

range_conditionals = [o for o in objects if o.get('type') == 'conditional' and isinstance(o.get('card'), dict) and o['card'].get('type') == 'markdown' and 'Min power must be ≤ Max power.' in o['card'].get('content', '')]
check(len(range_conditionals) == 10)
for i, cond in enumerate(range_conditionals, 1):
    check(cond.get('conditions') == [{'condition': 'state', 'entity': f'binary_sensor.hpvc_pv{i}_limit_range_invalid', 'state': 'on'}])
    card = cond['card']
    check(f'PV{i} Min power must be ≤ Max power.' in card['content'])
    check('Correct it, then re-enable HPVC Control.' in card['content'])
    s = base_states()
    s.add(f'input_number.hpvc_pv{i}_full_limit', '2000')
    s.add(f'input_number.hpvc_pv{i}_low_limit', '2000')
    rows_v = refresh_limit_validation(s)
    check(rows_v[i-1]['status'] == 'min_equal_max' and rows_v[i-1]['valid'] is True)
    check(s(f'binary_sensor.hpvc_pv{i}_limit_range_invalid') == 'off')
    s.add(f'input_number.hpvc_pv{i}_low_limit', '2100')
    rows_v = refresh_limit_validation(s)
    check(rows_v[i-1]['status'] == 'min_above_max')
    check(s(f'binary_sensor.hpvc_pv{i}_limit_range_invalid') == 'on')


# A duplicate Number target rejects the later assignment, leaving the original
# slot's presentation intact. Actual runtime duplicate-command safety is separate.
def duplicate_fixture():
    s = base_states()
    s.add('input_number.hpvc_inverter_count', '2')
    for i in (1, 2):
        s.add(f'input_select.hpvc_pv{i}_control_method', 'Number entity')
        s.add(f'input_select.hpvc_pv{i}_limit_unit', 'Watts')
        s.add(f'input_number.hpvc_pv{i}_full_limit', '2000')
        s.add(f'input_number.hpvc_pv{i}_low_limit', '0')
        for field in ('action', 'readback_entity'):
            s.add(f'input_text.hpvc_pv{i}_{field}', '')
        s.add(f'input_text.hpvc_pv{i}_limit_number', 'number.same')
    s.add('number.same', '1000', {'min': 0, 'max': 2000})
    return s

s = duplicate_fixture()
for original, newer in ((1, 2), (2, 1)):
    s.entities[f'input_text.hpvc_pv{original}_limit_number'].last_changed = '2026-10-24 10:00:00+00:00'
    s.entities[f'input_text.hpvc_pv{newer}_limit_number'].last_changed = '2026-10-24 11:00:00+00:00'
    values = rows(s)
    check(values[original-1].get('status') == 'Detected' and values[original-1].get('valid') is True)
    check(values[newer-1]['status'] == 'Incomplete' and not values[newer-1]['valid'])
    check(values[newer-1]['reason'] == f'Limit entity already assigned to PV{original}')
    check(render(template_entity(config, f'hpvc_pv{original}_control')['availability'], s) == 'True')
    check(render(template_entity(config, f'hpvc_pv{newer}_control')['availability'], s) == 'False')
    check(f'already assigned to PV{original}' in render(cards[newer-1]['content'], s))
    check('already assigned' not in render(cards[original-1]['content'], s))
# Equal/missing timestamps use stable slot order; normalized IDs are duplicates.
s = duplicate_fixture()
s.add('input_text.hpvc_pv2_limit_number', '  NUMBER.SAME  ')
check(rows(s)[1]['reason'] == 'Limit entity already assigned to PV1')
s.add('input_boolean.hpvc_pv1_control_disabled', 'on')
check(rows(s)[1]['status'] == 'Incomplete')
s.add('number.same', 'unavailable', {'min': 0, 'max': 2000})
check(rows(s)[0]['status'] == 'Unavailable' and rows(s)[1]['status'] == 'Incomplete')
s.add('input_text.hpvc_pv2_limit_number', 'number.different')
s.add('number.different', '1000', {'min': 0, 'max': 2000, 'friendly_name': 'Same display name'})
s.add('number.same', '1000', {'min': 0, 'max': 2000, 'friendly_name': 'Same display name'})
check([r['status'] for r in rows(s)] == ['Detected', 'Detected'])
check('reason' not in rows(s)[1])
# Sharing an action name/readback is not proof of duplicate physical targets.
s.add('input_select.hpvc_pv2_control_method', 'Action/service')
for field, value in {'action': 'inverter.set_limit', 'readback_entity': 'number.same', 'value_field': 'value', 'fixed_data_json': '{}', 'target_json': '{"entity_id":"inverter.two"}', 'pre_actions_json': '[]', 'post_actions_json': '[]'}.items():
    s.add(f'input_text.hpvc_pv2_{field}', value)
s.add('input_number.hpvc_pv2_action_step', '1')
s.add('input_number.hpvc_pv2_refresh_seconds', '0')
check(rows(s)[1]['status'] == 'Configured')

# Live Inputs uses the existing control switch state for a native, dependency-free
# label: ON keeps the normal label, OFF adds "(Off)", and unknown/unavailable
# match neither row and therefore stay hidden.
live_rows = {}
for i in range(1, 11):
    matches = [o for o in objects if o.get('row', {}).get('entity') == f'sensor.hpvc_pv{i}_actual_limit']
    check(len(matches) == 2)
    by_state = {}
    for card in matches:
        check(card['type'] == 'conditional')
        guards = [c for c in card['conditions'] if c.get('entity') == f'switch.hpvc_pv{i}_control']
        check(len(guards) == 1 and guards[0].get('condition') == 'state')
        by_state[guards[0].get('state')] = card
    check(set(by_state) == {'on', 'off'})
    check(by_state['on']['row'].get('name') == f'PV{i} actual limit')
    check(by_state['off']['row'].get('name') == f'PV{i} actual limit (Off)')
    if i >= 2:
        for card in matches:
            runtime = [c for c in card['conditions'] if c.get('entity') == 'sensor.hpvc_effective_inverter_runtime']
            check(len(runtime) == 1 and runtime[0].get('condition') == 'numeric_state' and runtime[0].get('above') == i - 1)
    live_rows[i] = by_state

def conditional_visible(s, card):
    for condition in card['conditions']:
        value = s(condition['entity'])
        if condition.get('condition') == 'numeric_state':
            try:
                if not float(value) > condition['above']:
                    return False
            except (TypeError, ValueError):
                return False
        elif condition.get('condition') == 'state':
            if value != condition.get('state'):
                return False
    return True

# Direct switch-state behavior: exactly one native row is visible for ON/OFF,
# while unknown/unavailable hide both.
for i in range(1, 11):
    s = base_states()
    s.add('sensor.hpvc_effective_inverter_runtime', '10')
    for state, expected in [('on', (True, False)), ('off', (False, True)), ('unknown', (False, False)), ('unavailable', (False, False))]:
        s.add(f'switch.hpvc_pv{i}_control', state)
        got = (conditional_visible(s, live_rows[i]['on']), conditional_visible(s, live_rows[i]['off']))
        check(got == expected)

# Range warning must occur after the status card in each selected-inverter view.
# YAML folds/wraps the label "Inverter status" differently across serializers.
# Compare parsed Markdown card content instead of an obsolete newline layout.
def markdown_cards(value):
    if isinstance(value, dict):
        if value.get('type') == 'markdown':
            yield str(value.get('content', ''))
        for child in value.values():
            yield from markdown_cards(child)
    elif isinstance(value, list):
        for child in value:
            yield from markdown_cards(child)

cards = list(markdown_cards(yaml.safe_load((ROOT / 'home assistant/hpvc_dashboard.yaml').read_text(encoding='utf-8'))))
for i in range(1, 11):
    warning = next(j for j, content in enumerate(cards) if f'PV{i} Min power must be ≤ Max power.' in content)
    check(warning > 0 and 'Inverter status:' in cards[warning - 1])

# Invalid Min/Max gating consumes the centralized validation sensor and forces
# HPVC Control OFF without rewriting the user's Min value.
guards = [a for a in config.get('automation', []) if a.get('id') == 'hpvc_disable_inverter_on_invalid_limit_range']
check(len(guards) == 1)
guard = guards[0]
check(guard.get('mode') == 'restart')
guard_text = yaml.safe_dump(guard, sort_keys=False)
check('sensor.hpvc_inverter_limit_validation' in guard_text)
check('min_above_max' in guard_text and 'row.status' in guard_text)
check("input_boolean.hpvc_pv{{ slot }}_control_disabled" in guard_text)
check('input_number.set_value' not in guard_text)
# The central validator itself is the only place that classifies above/equal/valid.
validator_text = yaml.safe_dump(limit_validation, sort_keys=False)
check("'min_above_max'" in validator_text and "'min_equal_max'" in validator_text and "'valid'" in validator_text)
for i in range(1, 11):
    projection = template_entity(config, f'hpvc_pv{i}_limit_range_invalid')
    projection_text = yaml.safe_dump(projection, sort_keys=False)
    check('sensor.hpvc_inverter_limit_validation' in projection_text)
    check('min_above_max' in projection_text and 'min_equal_max' not in projection_text)


# Central Min/Max validator must expose literal dependencies for all helper pairs so
# Home Assistant re-renders it immediately when a user edits any Max/Min helper.
config_text = (ROOT / 'home assistant/hpvc_config.yaml').read_text(encoding='utf-8')
for slot in range(1, 11):
    for suffix in ('full_limit', 'low_limit'):
        ref = f"states('input_number.hpvc_pv{slot}_{suffix}')"
        check(ref in config_text)

print(f'PASS controller status rendered templates and all ten windows ({checks} checks)')
