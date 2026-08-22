# Troubleshooting

[← README](../README.md) · [Installation](01-installation.md) · [Settings](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md)

Use the generated support report first. **Executive summary**, **Decision evaluation**, **Sensor health**, **Inverters**, and **Today’s Insights** usually identify the blocking condition quickly.

## Start here

1. Confirm **Configuration status** is valid.
2. Check **Sensor health** for unavailable or invalid required inputs.
3. Check **Decision evaluation** and **Status since**.
4. Check **Today’s Insights** for transitions, write warnings, or override faults.
5. Generate a fresh report before changing settings.

## Negative all-in-price override problems

At a valid all-in price `<= 0`, HPVC always applies PV-minimum protection. Forced HBC charging occurs only when **Enable HBC** and **Force charge at negative price** are both on and the native HBC strategy/charge-goal entities exist. Exit, or disabling either permission, restores the saved charge goal first and then the saved strategy.

If entry or restoration does not complete, check that both HBC entities are available, their required or saved options still exist, `/config/hpvc-data/` is writable, and `runtime-history.json` is valid. After five minutes in an unconfirmed phase, the fault helper and persistent notification identify the stuck phase.

For `recovery_unknown_previous`:

1. Select the intended HBC strategy and charge goal manually.
2. Confirm neither entity still shows the forced values.
3. Turn off `input_boolean.hpvc_negative_override_fault`.
4. Wait for the next HPVC evaluation.

Do not edit `runtime-history.json` manually unless this supported recovery path cannot run.

## HPVC turned itself off after a sensor outage

This is expected. If a required configuration or live control input becomes invalid while HPVC is running, the safety automation switches off the master toggle. HPVC resumes automatically only after all required inputs have been healthy for 5 continuous seconds and only when the shutdown was automatic. A manually disabled HPVC remains off.

### Identify which required sensor failed

**Today’s Insights** records the entity ID and validation reason. Identical faults are de-duplicated. During active Night Restore, expected nighttime loss of PV-power and inverter-limit telemetry is not treated as a daytime fault.

## One inverter is unavailable

During normal daytime control, HPVC pauses all inverter writes when any configured inverter limit is unavailable. It does not redistribute the plant target across only the remaining inverters because the missing inverter may still be producing.

During active Night Restore, expected nighttime loss of PV-power and inverter-limit telemetry is tolerated while grid and price safety inputs remain monitored.

## Installation and configuration

### Entities are unavailable after upgrading to v1.3.0

Replace the Home Assistant package, Node-RED flow, and dashboard together. Version 1.3.0 uses `hpvc_*` entity IDs; old `pv_ems_*` helpers are not migrated automatically.

### Restore defaults does not appear or cannot run

Confirm that `script.hpvc_restore_defaults` exists and that the current dashboard YAML is loaded. Reload packages or restart Home Assistant after replacing `hpvc_config.yaml`.

### Configuration error: invalid power thresholds

HPVC requires `Export Start < Target Export < Import Restore` and `Import Restore >= 0 W`. Writes remain blocked until corrected.

### Node-RED says entity not found

Check the exact entity IDs configured for grid power, prices, PV power, inverter limits, and optional HBC entities. Empty or invalid IDs are intentionally treated as configuration errors.

## PV limiting and restore

### PV does not limit

Check:

- HPVC is enabled;
- configuration status is valid;
- Market/export price is at or below the PV limiting price;
- grid export is more negative than Export Start;
- measured PV is above Min PV for control;
- cooldown is inactive;
- the requested change exceeds Deadband;
- inverter entities are writable and full/minimum powers are correct.

### Repeated export/import reversals

After an inverter write, HPVC waits for fresh or materially changed PV telemetry before making another ordinary closed-loop correction. A bounded timeout prevents control from remaining frozen if timestamps do not advance. If large reversals continue, check for fast house-load changes and verify grid/PV update cadence.

Near-simultaneous identical inverter write requests are suppressed for 2.5 seconds.

### PV restores to full at night

This is expected. Night Restore starts after valid measured PV remains at or below the configured threshold for 120 seconds. After activation, HPVC restores available inverter limits to full and suspends normal PV calculations. Expected nighttime loss of PV-power or inverter-limit telemetry is then tolerated.

If PV telemetry disappears while the timer is already running, **Night Restore pending** may complete only when `sun.sun` also reports `below_horizon`; otherwise strict validation returns. Recovery requires valid PV above `max(25 W, threshold + 15 W)` for 30 continuous seconds.

### Import happens while PV is limited

Import Restore can raise inverter limits even when measured PV is below Min PV for control. Low measured production may itself be caused by the active inverter limit.

### Inverter targets look wrong

Check inverter count, entity assignment, Full power, Minimum power, current limit, requested target, and Difference from target in the report. A total increase must never reduce an individual inverter, and a total decrease must never raise one.

## HBC and Charge Priority

### Battery should be charging but PV is limited

Check for every configured battery:

- AC power is valid and uses the expected sign while charging;
- SOC is numeric;
- maximum charge power is numeric and greater than 0;
- `input_number.house_battery_count` matches the installation;
- RS485 control is enabled;
- HBC is executing `Charge` or `Charge PV`;
- **Enable HBC** is on.

One healthy battery with usable headroom is enough to continue Charge Priority. Full, stale, unavailable, maximum-power, or taper-saturated batteries are excluded independently.

### Why is Charge Priority off outside the PV-limiting price zone?

This is expected. Outside the normal PV-limiting price zone, PV is already unrestricted, so HPVC does not need a Charge Priority intervention. HBC may still execute `Charge` or `Charge PV` normally.

Negative all-in-price mode is separate: PV is held at minimum, and forced HBC charging requires both HBC permissions.

### HBC strategy changes unexpectedly

During normal operation HPVC does not select HBC strategies. The exception is the optional negative-price override, which may temporarily force `Charge` when both HBC permissions are enabled and later restore the saved strategy. If **Enable HBC** is off, negative-price operation is PV-only.

If the strategy changed outside this case, check HBC itself, other automations, and the report timeline.

### Charge Priority says Off while HBC is executing Charge

This can be correct. Charge Priority is **Off** when HPVC intervention is not needed, such as outside the PV-limiting zone, during negative-price override, or when no battery has eligible headroom. Use the report's Charge Priority reason and per-battery eligibility table for the exact cause.

## Dashboard and graphs

### Insights card is empty

Confirm that `input_text.hpvc_insight_1` through `input_text.hpvc_insight_20` exist, deploy the supplied flow, and wait for the next evaluation. The current-day journal is restored from `hpvc-data/runtime-history.json` when the supported Home Assistant configuration mount is writable.

### Live Inputs does not show inverter 6–10

Rows appear only for slots included by `input_number.hpvc_inverter_count`.

### Price Zones in older or custom dashboards

The packaged dashboard includes the **HBC Price Intervals** graph with theme-aware grid and tooltip styling. It is shown only when onboarding is complete, HBC control is enabled, and `binary_sensor.hpvc_hbc_available` confirms HBC is available.

### Mobile report navigation buttons appear only after refresh

Use the current v1.4.0 report flow and generate a new report after deployment. Older already-published HTML files do not contain the updated mobile navigation script.

## Accuracy diagnostics

### One or more accuracy-loss factors remain 0.0%

This is not necessarily a problem. The four factors show contributions to the **headline loss**, so a factor stays 0.0% when no eligible harmful excursion was attributed to that cause. If Daily Control Accuracy is 100%, all four factors should be 0.0%.

For deeper analysis, use **Raw attributable shares**, **Attribution coverage**, and the exclusion diagnostics in the support report. These engineering metrics use different eligibility and do not have to match the compact dashboard percentages.

### All headline loss appears as Other

**Other** means HPVC saw a real harmful excursion but did not have enough safe evidence to assign it to House load, PV availability, or Control response. Short causal events can be carried across brief accuracy-ineligible gaps, but HPVC will not guess across weak telemetry continuity. If battery-power telemetry is uncertain, House-load inference is deliberately suppressed.

### A short appliance spike was not shown under House load

The evaluation that starts a normal PV-control cooldown is retained for accuracy, but later cooldown/settling samples are excluded. Very short events can still be missed when they occur entirely between source-sensor updates or inside an already-active cooldown.

### A visible grid spike is not appearing under House load changes

A grid spike is not classified from grid power alone. HPVC briefly reconciles it with PV, battery-power, and inverter-limit movement so cloud changes, battery movement, and controller response are not mistaken for house load. If source sensors never publish a changed value while a very short event exists, the detector cannot recover it later.

### Internal attribution diagnostics

For advanced troubleshooting, Node-RED global context stores the latest attribution audit record and a short rolling history with grid/PV/battery/limit deltas, causal weights, event age, and command verification state. These diagnostics do not alter dashboard behavior.

## Reports

### Generate report does not change to View report

Wait for generation to finish. **View report** appears only after publication succeeds. If report storage was temporarily unavailable during startup/redeploy, HPVC now retries storage initialization automatically every 30 seconds; a Generate report click also queues one request and asks the bounded retry path to re-initialize storage. If a previously-ready mount disappears later, a failed report file write or atomic publication invalidates the cached ready state so the same recovery path can re-probe it instead of remaining falsely marked ready. If publication still does not complete, check the persistent notification and Node-RED error log.

### The report time did not change

The report is an on-demand snapshot. Press **Generate report** again and wait for **View report** before reopening it.

### Generate or View report state appears stuck

Reload the dashboard and check Node-RED for a report-generation error. A successful generation publishes `/local/hpvc/support-report.html` and enables **View report**. Opening the report clears the Ready state through the bundled local webhook; the file itself remains until a newer report replaces it.

### Decision evaluation says Triggered while PV currently limited says No

This is valid. **Triggered** describes the current threshold condition; **PV currently limited** describes the actual control state. Cooldown, deadband, minimum PV, price mode, configuration errors, unavailable inputs, or another guard can prevent a write.

### Action result says No inverter change

The report shows the recorded action. It does not infer Reduce PV or Increase PV from a triggered condition alone.

### TXT export differs from HTML

Both formats use the same report model. HTML groups consecutive identical Insight runs, while TXT keeps every raw Insight event as a separate row. Other field values and diagnostics should match.

### Report tile remains on Generating after a deploy

Startup cleanup clears stale generation state and abandoned temporary files while leaving an already-published valid report intact.

## Node-RED and advanced diagnostics

### The flow imports as four tabs

This is expected. Import the complete `hpvc_flow.json`; Inputs, Engine, Outputs, and Reports are designed to work together.

### No Write warning Insight appears

A warning appears only when a requested inverter value remains unconfirmed after the verification timeout and has not been superseded by a newer target.

### Advanced diagnostic data is invalid or truncated

`input_text.hpvc_last_targets_json` is limited to 255 characters. When necessary, HPVC stores a smaller valid diagnostic object instead of truncating JSON mid-field.

### Report shows a runtime data notice

Live grid, PV, and price values are captured when the report is generated, while decision and taper diagnostics describe the latest completed HPVC evaluation. A notice means those runtime diagnostics are old, mismatched in time, or not yet available; it does not change control behavior.

### Repeated or truncated Battery telemetry Insights

The flow records a Battery telemetry warning when a battery becomes unusable and a recovery after 60 seconds of healthy telemetry. Truncated `input_text.hpvc_insight_*` values are startup fallback data only; older duplicate rows disappear at the next local-midnight reset.

For deeper telemetry, cutoff, persistence, attribution, and report semantics, see [How it works](03-how-it-works.md).

[← README](../README.md) · [Installation](01-installation.md) · [Settings](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md)
