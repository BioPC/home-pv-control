# Troubleshooting

[← README](../README.md) · [Installation](01-installation.md) · [Settings](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md)

Use the generated support report first. **Executive summary**, **Decision evaluation**, **Sensor health**, **Inverters**, and **Today’s Insights** usually identify the blocking condition quickly.

## Installation and configuration

### Entities are unavailable after upgrading to v1.3.0

Replace the Home Assistant package, Node-RED flow, and dashboard together. Version 1.3.0 uses `hpvc_*` entity IDs; old `pv_ems_*` helpers are not migrated automatically.

### Restore defaults does not appear or cannot run

Confirm that `script.hpvc_restore_defaults` exists and that the current dashboard YAML is loaded. Reload packages or restart Home Assistant after replacing `hpvc_config.yaml`.

### Configuration error: invalid power thresholds

HPVC requires `Export Start < Target Export <= 0 W` and `Import Restore >= 0 W`. Writes remain blocked until corrected.

### Node-RED says entity not found

Check the exact entity IDs configured for grid power, prices, PV power, inverter limits, and the optional HBC strategy entity. Empty or invalid IDs are intentionally treated as configuration errors.

## PV limiting and restore

### PV does not limit

Check:

- HPVC is enabled;
- configuration status is valid;
- the Market/export price is at or below the configured PV limiting price;
- grid export is more negative than Export Start;
- measured PV is above Min PV for control;
- cooldown is inactive;
- the requested change exceeds Deadband;
- inverter entities are writable and their full/minimum powers are correct.

### PV restores to full at night

This is expected. HPVC restores full limits after `sun.sun` remains `below_horizon` for the required period. If `sun.sun` is unavailable, it uses the configured night-PV fallback threshold.

### Import happens while PV is limited

Import Restore can raise the inverter limits even when measured PV is below Min PV for control. Low measured production may itself be caused by the active inverter limit.

### Inverter targets look wrong

Check inverter count, entity assignment, Full power, Minimum power, current limit, requested target, and Difference from target in the report. HPVC distributes the total target proportionally and clamps every inverter to its configured minimum and maximum.

## Hidden PV Reveal and batteries

### Multiple batteries still have charge headroom

HPVC evaluates configured batteries independently and combines the allowance of eligible batteries. Review each battery’s Status, Current reveal allowance, Telemetry, Reason, maximum charge power, SOC, and current charging power in the report.

Idle, unavailable, or non-charging batteries are normally excluded until they become eligible. A battery near full does not by itself block reveal when another eligible battery still has useful headroom.

### Current reveal allowance is much lower than raw charger headroom

Raw charger headroom is theoretical unused charging capacity. Current reveal allowance is the smaller amount HPVC is willing to test safely.

From 90% SOC onward, conservative probe ceilings apply:

| SOC | Maximum probe |
|---:|---:|
| 90–94% | 200 W |
| 95–96% | 100 W |
| 97–98% | 50 W |
| 99% | 25 W |
| 100% | 0 W |

Target Export margin, remaining hidden PV, the internal probe cap, cooldown, deadband, and response evaluation can reduce it further.

### Poor-response pause is active

HPVC paused further probes after an ineffective or unsafe response. **Response evaluation: Pending** means the previous reveal is still inside its settling/evaluation cycle.

### Excess export while HBC is in Charge

Verify every battery’s power, SOC, and maximum-charge-power entity. Unavailable or nonnumeric telemetry is excluded. Unchanged numeric values are not automatically treated as stale because Home Assistant timestamps represent value changes, not guaranteed connectivity loss.

## Dashboard and graphs

### Insights card is empty

Confirm that `input_text.hpvc_insight_1` through `input_text.hpvc_insight_20` exist, deploy the supplied flow, and wait for the next evaluation. Without file-backed Node-RED context, a Node-RED restart clears accumulated current-day Insight history.

### Live Inputs does not show inverter 6–10

Rows appear only for slots included by `input_number.hpvc_inverter_count`.

### Price Zones remains on Loading or is empty

Check that `sensor.hbc_energy_prices_data` contains valid timestamped forecast data through `marks`, `prices` plus `start`, `today`/`tomorrow`, or another supported forecast/rates attribute.

The graph:

- interprets HBC cent values as €/kWh;
- uses supplied timestamps and interval information;
- shows up to 48 hours when the sensor provides 192 quarter-hour points;
- can convert raw market forecasts to estimated all-in prices;
- displays **Price type uncertain** when current values cannot be classified reliably.

After HBC publishes tomorrow’s prices, the Home Assistant frontend may briefly retain the earlier 24-hour render. The card refreshes periodically; a manual browser refresh forces the latest 48-hour dataset immediately.

If values appear at the wrong scale, reload dashboard resources and clear the frontend cache.

## Reports

### Generate report does not change to View report

Wait for report publication to finish. Generation uses a lock to prevent overlapping requests and an atomic temporary-file publish step. Errors should clear the lock, reset the helper states, and create a persistent notification.

### The report time did not change

The report is an on-demand snapshot. Press **Generate report** again and wait for **View report** before reopening it.

### Generate or View report state appears stuck

Reload the dashboard and check Node-RED for a report-generation error. The View-report webhook retries after network and non-success HTTP responses. Restart Node-RED only after saving any diagnostic information you need.

### Decision evaluation says Triggered while PV currently limited says No

This is valid. **Triggered** means the threshold condition is currently true. **PV currently limited** shows the actual control state. Cooldown, deadband, minimum PV, price mode, configuration errors, unavailable inputs, or another guard may prevent a new write.

### Current action says No inverter change

The report now shows the actual recorded action. It does not infer Reduce PV or Increase PV solely from a triggered condition.

### TXT export differs from HTML

Both formats use the same report model. Generate a fresh report, then download TXT from that HTML snapshot. If an older file remains open, refresh only after generating a new report.

## Node-RED and diagnostics

### No Write warning Insight appears

Successful writes are confirmed internally and do not generate routine Insights. A warning is logged only when a requested value remains unconfirmed after the verification timeout and has not been superseded by a newer HPVC target.

### Advanced diagnostic data is invalid or truncated

`input_text.hpvc_last_targets_json` is limited to 255 characters. HPVC uses compact keys and stores a reduced but valid JSON object with `err: "diagnostic_payload_reduced"` rather than cutting JSON mid-field.

## HBC strategy changes unexpectedly

Turn off `input_boolean.hpvc_control_hbc_strategy`. HPVC will continue controlling PV limits while leaving HBC strategy selection untouched.


[← README](../README.md) · [Installation](01-installation.md) · [Settings](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md)
