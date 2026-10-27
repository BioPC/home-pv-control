#!/usr/bin/env python3
from pathlib import Path
import json
import yaml
ROOT=Path(__file__).resolve().parents[1]
config=(ROOT/'home assistant/hpvc_config.yaml').read_text(encoding="utf-8")
dash=(ROOT/'home assistant/hpvc_dashboard.yaml').read_text(encoding="utf-8")
flow=json.loads((ROOT/'node-red/hpvc_flow.json').read_text(encoding="utf-8"))
byid={n.get('id'):n for n in flow}
assert 'hpvc_insights_enabled:' in config
assert '- input_boolean.hpvc_insights_enabled' in config
assert 'entity: input_boolean.hpvc_insights_enabled\n            name: Enable Insights' in dash
assert dash.index('entity: input_boolean.hpvc_notifications') < dash.index('entity: input_boolean.hpvc_insights_enabled')
insights_pos=dash.index('title: 📋 Insights')
visibility_pos=dash.index('entity: input_boolean.hpvc_insights_enabled', insights_pos)
assert visibility_pos > insights_pos
assert dash.count("entity: input_boolean.hpvc_insights_enabled") >= 5  # tile + report states + Insights visibility
core=byid['6498f50f6fea77b9']['func']
assert "const insightsEnabled = stringState('input_boolean.hpvc_insights_enabled', 'off') === 'on';" in core
assert 'insightsEnabled,' in core
trans=byid['7d3a4ec873d023a2']['func']
assert 'skip\n// transition analysis, activity history and Insight generation when disabled' in trans
assert 'hpvc.insightsEnabled === false' in trans
journal=byid['a531bbe8d15a6096']['func']
assert "input_boolean.hpvc_insights_enabled" in journal
assert 'do not maintain optional Insight/report/activity history while disabled' in journal
report_gate=byid['hpvcinsightsreportgate155']['func']
assert "input_boolean.hpvc_insights_enabled" in report_gate
assert 'Insights disabled' in report_gate
retry=byid['0f68139b776691a2']['func']
assert "input_boolean.hpvc_insights_enabled" in retry
updates=byid['411af491012c6308']['func']
assert 'const insightsEnabled = msg.hpvc?.insightsEnabled !== false;' in updates
assert 'if (insightsEnabled) for (let i = 1; i <= 10; i++)' in updates
assert 'if (insightsEnabled && msg.hpvc && msg.hpvc.runtimeTiming)' in updates
assert "global.get('hpvcPreviousInsightsEnabled')" in updates
assert "previousInsightsEnabled === false" in updates
assert "Insights enabled — diagnostic collection resumed." in updates
assert "global.set('hpvcPreviousInsightsEnabled', false);" in updates
assert "global.set('hpvcPreviousInsightsEnabled', true);" in updates
accuracy=byid['bd67f0c058bb581a']['func']
assert 'Calculate Daily Control Accuracy' in accuracy and 'homePvControlDailyAccuracy' in accuracy
print('PASS optional Insights mode gating and core Accuracy preservation')

# Insights is a low-overhead opt-in feature: first install and Restore Defaults leave it off.
assert '- input_boolean.hpvc_insights_enabled' in config
restore_idx=config.index('alias: Home PV Control - Restore Defaults') if 'alias: Home PV Control - Restore Defaults' in config else config.index('hpvc_restore_defaults')
assert 'input_boolean.turn_off' in config[restore_idx:] and 'entity_id: input_boolean.hpvc_insights_enabled' in config[restore_idx:]
assert "global.set('hpvcBatteryTelemetryRecoveryCandidates', {});" in core
assert "global.set('hpvcBatteryCapacityRecoveryCandidateSince', 0);" in core
assert "if (insightsEnabled && hpvcObjectHasKeys(global.get('hpvcBatteryTelemetryRecoveryCandidates'))) return true;" in core
uninstall_defaults=byid['2cf211e5923758ad']['func']
assert '"input_boolean.hpvc_insights_enabled"' in uninstall_defaults
assert "add('input_boolean.turn_off'" in uninstall_defaults
print('PASS Insights mode optional-work gating/default-off behavior')
