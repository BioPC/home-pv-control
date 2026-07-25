# How it works

[← README](../README.md) · [Installation](01-installation.md) · [Settings](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md)

## Control overview

HPVC follows this execution order:

1. Startup and input validation
2. Control cycle
3. Target calculation
4. Inverter split
5. Decision logic (limit, restore or monitor)
6. Hidden PV Reveal
7. Response evaluation
8. Accuracy calculation
9. Safety checks

Home PV Control calculates a target total PV limit and then distributes that target over all configured inverters.


## Input validation and startup safety

HPVC separates **configuration validity** from **live input readiness**.

- A missing or malformed entity ID in an HPVC helper is a configuration problem. HPVC allows up to 90 seconds after a Home Assistant restart for helpers to restore; if the problem remains, the status becomes **Configuration error**.
- A correctly configured grid, market/export-price, all-in-price, PV-power, or active inverter-limit entity that reports `unknown`, `unavailable`, an empty state, or a non-numeric value is a live-input outage. HPVC sends no inverter writes while any required live input is unavailable.
- During the first 90 seconds of a live-input outage, the status is **Waiting for inputs**. If the outage lasts longer, the status becomes **Inputs unavailable** and control remains paused until every required value is numeric again.
- When the live inputs recover, HPVC resumes normal evaluation and records an input-restored Insight.

HPVC never substitutes `0 W` for unavailable grid/PV measurements and never substitutes the configured full limit for an unavailable inverter-limit state. This prevents restart-time or integration-outage decisions from being made with invented values.


## PV target calculation

```text
target_total = pv_power + grid_power - target_grid_power
```

Example:

```text
PV power = 2500 W
Grid power = -600 W
Target export = -25 W

target_total = 2500 - 600 + 25 = 1925 W
```

## Inverter target distribution

The target is split proportionally by `full_power`.

Example:

```text
PV1 full = 2000 W
PV2 full = 1000 W
Total full = 3000 W
```

PV1 gets 2/3 of the target, PV2 gets 1/3.

If another user has:

```text
PV1 = 1500 W
PV2 = 1500 W
```

both get 50%.

### Per-inverter minimum power

Every inverter has its own `minimum_power`.

The EMS never sets an inverter below this value.

## Restore and recovery

PV is restored to full power when:

- market/export price is unavailable
- market/export price rises above the PV limiting price plus the configured exit hysteresis
- when `sun.sun` is available, it remains `below_horizon` for 120 continuous seconds; or
- when `sun.sun` is unavailable, PV production remains below the night restore fallback threshold for 120 continuous seconds

The active 120-second timer resets immediately when its condition stops being true. The PV threshold is ignored whenever `sun.sun` is available, and its dashboard input is hidden. This gives normal installations a predictable sunset restore while preserving an automatic fallback for installations without the Sun entity.

## Dynamic limiting conditions

Normal export limiting is allowed when:

- market/export price is at or below the PV limiting price
- PV production is above Min PV for control
- grid power is more negative than Export Start
- cooldown has passed
- at least one inverter target differs by more than the deadband

Import recovery and Hidden PV Reveal may raise limits even when measured PV is below Min PV for control. This is intentional because an active inverter limit can itself suppress the measured PV value.

### Import recalculation

When PV is already limited and grid import rises above Import Restore, HPVC recalculates upward instead of blindly restoring every inverter to full. For this recovery calculation it uses at least the current combined inverter limit as the available-PV baseline, so low measured PV does not prevent recovery.

## Hidden PV Reveal


Active HBC batteries are displayed in a table matching the inverter table, with columns for Battery, Status, SOC, Actual power, Max charge power, Raw charger headroom, Current reveal allowance, Telemetry, and Reason.

The grid must be inside the reveal recovery region:

- grid power is at or above Export Start, so export is no longer excessive; and
- grid power remains below Target Export plus dynamic tolerance, so useful room for additional PV still exists.

The reveal amount is:

`min(800 W cap, effective active-battery headroom, Target Export margin + dynamic tolerance, hidden PV remaining)`

The dynamic tolerance is:

`min(max(deadband × 2, effective active-battery headroom × 0.25), 150 W)`

The PV Adjustment Deadband is applied to the total reveal request. Once that total exceeds the deadband, HPVC preserves the proportional split across the limited inverters instead of discarding smaller inverter shares.


### Multiple charging batteries

HBC can distribute charging power across multiple batteries in one cycle. HPVC sums usable headroom per eligible battery. Actively charging batteries contribute their known remaining charge headroom, while eligible idle batteries may contribute an SOC-capped initial probe. Discharging, full, unavailable, or nonnumeric batteries contribute zero.

For multi-battery control, HPVC evaluates and tracks each battery independently. Each battery contributes only its own usable probe headroom. Eligible idle batteries may bootstrap the first probe; discharging, full, unavailable, and nonnumeric batteries contribute zero without blocking other valid batteries. Below 90% SOC, Current reveal allowance uses raw charger headroom subject to the global adaptive cap. From 90% onward, it uses an SOC-based probe ceiling: 200 W at 90–94%, 100 W at 95–96%, 50 W at 97–98%, 25 W at 99%, and 0 W at 100%. The current charging power is feedback, not a hard ceiling. After each reveal, the response guard measures battery-charge increase and grid export. A battery-charge increase is counted only when its power entity has received a new sample after the reveal; an unchanged old numeric value remains eligible telemetry but is not response evidence. A safe response permits another probe; weak absorption with export leakage is treated as actual tapering and pauses further probes. A battery with unknown maximum charge power contributes no Reveal headroom. Full-PV Charge Priority is allowed only for meaningful headroom from a battery below the high-SOC band, backed by a valid maximum-charge-power value, or during that same battery's startup/telemetry grace. Small margins and unknown maximum-power data use normal export limiting with bounded Reveal. High-SOC mode enters at 90% and leaves below 89%; the 95% band leaves below 94%. A high-SOC battery or an active taper pause can never cancel the startup grace or useful headroom of a separate lower-SOC battery.

### High-SOC repeated reveal probes

The configured maximum charge power is only an upper limit; near a high state of charge, the battery BMS may intentionally accept less power. After each reveal, HPVC compares the increase in battery charging with any increase in grid export. From 90% SOC, reveal steps use progressively smaller ceilings: 200 W at 90–94%, 100 W at 95–96%, 50 W at 97–98%, 25 W at 99%, and 0 W at 100%. If a high-SOC reveal mostly becomes extra export instead of battery charging, HPVC pauses reveal immediately. It resumes when SOC falls below 90% or charging power clearly recovers.

**Example:** A battery is at 92% SOC and charging at 500 W. HPVC reveals 200 W, but charging rises by only 20 W while export rises by 180 W. HPVC detects the weak charging response and pauses further reveal instead of repeating a limit → reveal → limit cycle.

## Reveal accuracy guard and stability score

Daily Reveal Accuracy uses watt weighting: the requested reveal power is the sample weight, so larger probes affect the daily score more than tiny probes near the deadband. Factor losses use the same weight and therefore still add up to the displayed daily loss.

The expected response is capped by an independent estimate captured before the probe, using measured PV output relative to the active inverter limit. The observed response is never used to reduce its own scoring denominator. When available solar falls significantly during the response window and the requested limit can no longer be reached, the probe is excluded instead of being scored as a Reveal failure.

Scoring begins only after fresh grid and PV samples arrive and every requested inverter-limit value is visible within the write tolerance. Stale telemetry and unsettled writes time out as skipped evaluations. They do not lower Daily Reveal Accuracy or the Reveal stability score.

Each reveal request is evaluated once after at least 25 seconds, allowing inverter, PV, battery, and grid readings to settle. The stability score ranges from 0–100%: good response raises it and weak or poor response lowers it. Low-stability pause requires two consecutive poor evaluated responses below 40%. It can recover when actual PV production rises again or grid export becomes strong enough to indicate that more solar is available.

## Control boundaries and validation

Export Start begins normal limiting. Target Export is the calculated grid target and the upper edge of the reveal recovery window. HPVC requires `Export Start < Target Export <= 0 W` and `Import Restore >= 0 W`. Invalid values produce a configuration error and block inverter writes. A 75–100 W gap between Export Start and Target Export is recommended for smooth control.

## Cooldown and deadband

Every actual inverter-limit write starts the configured cooldown. During that window HPVC sends no further PV-limit write; the first evaluation after expiry may act immediately. Normal target changes use the deadband per inverter. Hidden PV Reveal applies it to the total reveal request, then preserves proportional inverter shares.

## Negative price and final restore behavior

When the all-in import price is zero or negative, HPVC forces PV to minimum output.

When Hidden PV Reveal reaches the full region, HPVC verifies every inverter. If any inverter remains slightly below its exact full limit, it sends one final per-inverter restore command.

## Runtime diagnostics

`input_text.hpvc_last_targets_json` stores the compact latest-calculation JSON used by diagnostics and support reports.


## Persistence and safeguards

The v1.3.0 diagnostic price sensor is `sensor.hpvc_diag_market_export_price`. Existing installations that previously used `sensor.hpvc_diag_market_price` must update dashboard or external references and may remove the old entity from the Home Assistant entity registry after confirming the new sensor is available.

User-configurable Home PV Control helpers do not use `initial:` values in the shipped YAML, allowing Home Assistant to restore user-edited settings after a restart. The transient `hpvc_report_ready` and `hpvc_report_generating` helpers intentionally use `initial: false` so stale report states are not restored.

A Home Assistant first-run automation applies the shipped defaults only when `input_boolean.hpvc_defaults_applied` is still off. After the defaults are applied, that flag is turned on and restored by Home Assistant on later restarts, so user changes are not overwritten.

### Reveal deadband handling

Hidden PV Reveal applies the PV Adjustment Deadband to the **total reveal request**, not to each inverter's proportional share.

If the total reveal is meaningful, HPVC keeps the proportional split across inverters. Every proportional inverter change is applied once the total reveal exceeds the deadband. This prevents smaller inverters from lagging behind during small reveal steps.


Every new Insight is appended to a date-scoped Node-RED flow-context log. Consecutive identical Insights generated within 60 seconds are suppressed. The log is capped at 1000 entries and resets when the local date changes.

The latest 20 entries are written to the existing numbered Insight helpers, which the Main dashboard reads directly. The full current-day log remains available to the report generator and is cleared when the local date changes.


In the HTML report, Master control and HBC control enabled Insights use the on style, disabled Insights use the muted off style, and only `Control warning` and `Write warning` use the warning style.

## User actions

### Restore defaults

The **Restore defaults** button resets only the recommended HPVC control settings. It preserves the user's current HBC Strategy Control on/off state.

```text
Dashboard button
        │
        ▼
script.hpvc_restore_defaults
        │
        ▼
Home Assistant automation/script
        │
        ▼
Recommended HPVC settings restored
        │
        ▼
Node-RED detects the changes
        │
        ▼
HPVC immediately performs a new evaluation
```

**Restored**

- Price Strategy settings
- Power Flow Control settings
- Control Tuning settings

**Not changed**

- Configured entity selections
- Inverter limit entities
- Active inverter count
- HBC configuration
- Node-RED flow configuration
- Home Assistant or Node-RED runtime

## Report generation and diagnostics

```text
Generate report pressed
        │
        ▼
Ready OFF → Generating ON
        │
        ▼
Capture current values → build HTML → write file
        │
        ▼
Generating OFF → Ready ON → View report
        │
        ▼
Open report → reset webhook → Ready OFF
```

The only generation trigger is `input_button.hpvc_export_report`. The report is not built by the 15-second evaluation, startup, settings changes, telemetry changes, or Insights. Loading the report performs one cache-bypassing fetch of the same saved file to prevent stale mobile-browser content; the page does not auto-refresh afterward.

A write/build error is caught by Node-RED. Both report-state helpers are turned off and Home Assistant receives a persistent error notification. Generating or viewing the report never changes HPVC settings, inverter limits, or HBC behaviour.

The report includes executive status, live inputs, decision evaluation, daily accuracy, inverter diagnostics, HBC/battery diagnostics, settings, sensor health, and all current-day Insights. The **Download report** button creates the matching TXT snapshot in the browser.

### Report presentation

- **Download report** saves the current diagnostic report as a UTF-8 `.txt` file with a timestamped filename.
- The HTML report uses the same data as the downloaded TXT report.
- The report includes current status, inverter and battery tables, control settings, HBC/Hidden PV Reveal information, and current-day Insights.
- Battery tables match the inverter table layout and hide entity IDs for cleaner presentation.
- Hidden PV Reveal uses its own Insight type, while normal PV limiting and restore actions use `PV limit`.

## Accuracy and factor attribution

- Target accuracy is sampled every 15-second evaluation only while HPVC is enabled, inputs are valid, PV is actively limited for normal target tracking, cooldown is inactive, and neither negative-price minimum mode nor night restore is active.
- Reveal accuracy measures improvement in grid error relative to Target Export. Overshoot is recorded only when grid power passes beyond Target Export by more than the configured deadband. PV absorption is retained as a separate diagnostic, and cycles without an evaluated reveal response remain unavailable rather than counting as 0%.
- Daily averages weight each eligible sample equally.
- Diagnostic percentages are estimated contributing factors inferred from structured controller events and Insights. They are not direct physical measurements. The complete loss is distributed across the four published factors for that accuracy metric; no additional residual factor is created.
- Runtime, report, and dashboard battery totals support up to 10 configured HBC batteries.

For battery eligibility, HPVC uses fresh live power telemetry as the authoritative signal. SOC is still required to be numerically available, but its timestamp may be older because SOC naturally changes slowly. HPVC also remembers the last valid maximum charge-power setting when that entity is temporarily unavailable.


### Decision and response diagnostics
The report separates **Poor-response pause** (a guard pause caused by ineffective reveal response) from **Response evaluation** (a reveal awaiting its settling/evaluation window). The inverter diagnostics card uses the existing inverter configuration, live limits, calculated targets, and write-verification context only.

### Unified HTML and TXT model

HPVC builds one internal report model and renders it as HTML and TXT. This prevents fields from appearing in only one format. Diagnostic values are read from existing helpers, configured entities, runtime debug state, inverter calculations, battery diagnostics, write-verification context, and Insights.

### Target Accuracy factors

Target Accuracy continues to use four factors:

- **Control response**: recent inverter writes, inverter minimum/maximum boundaries, threshold or deadband holding, and stable off-target operation while a limit is physically binding.
- **House load changes**: a meaningful change in estimated house load (`PV power + grid power`) that dominates the simultaneous PV movement.
- **PV availability**: meaningful PV movement while inverter limits and estimated house load remain comparatively stable.
- **Other**: only samples that cannot be explained by the three categories above.

This changes factor attribution only. It does not change the Target Accuracy score, PV control decisions, thresholds, cooldown, inverter writes, HBC, or Hidden PV Reveal.


## PV price hysteresis

PV limiting enters immediately when the configured market/export price is at or below the PV limiting price. Once active, it remains active through the hysteresis band and exits only when that price rises above `PV limiting price + price hysteresis`. Negative all-in-price mode remains the highest priority. During HBC **Charge**, full PV is restored only for meaningful, known maximum-power headroom below the high-SOC band. Small margins, unknown maximum-power data, and high-SOC batteries stay under normal export limiting with bounded adaptive Reveal. Charge startup and telemetry state are tracked per battery for 60 and 30 seconds; unknown SOC receives only a 15-second startup fallback. Internal 90/89% and 95/94% SOC hysteresis prevents boundary oscillation. These safeguards require no extra user input.

## HBC charge and expensive price hysteresis

When HBC strategy control is enabled, the same configured price hysteresis stabilizes the all-in-price strategy transitions, but only on exit:

- **Charge:** enter when all-in price is at or below `Charge price`; remain in Charge until all-in price rises above `Charge price + price hysteresis`.
- **Expensive:** enter when all-in price is at or above `Expensive price`; remain in the expensive strategy until all-in price falls below `Expensive price - price hysteresis`.
- **Balanced:** selected only when neither Charge nor Expensive is being entered or held.
- **Negative all-in price:** remains independent and uses no hysteresis; it enters at `all-in <= 0` and exits immediately when all-in becomes positive.

For example, with Charge `0.10`, Expensive `0.35`, and hysteresis `0.02` €/kWh, Charge is held through `0.12`, while Expensive is held down through `0.33`.



## Live HBC strategy options

HPVC mirrors the configured HBC strategy entity's live option list into its strategy helpers. The Charge strategy is automatically managed and shown read-only: HPVC always uses `Charge` when that exact option exists. Balanced and Expensive remain user-selectable and prefer `Dynamic` when available. If a preferred option does not exist, HPVC preserves a valid fallback, uses HBC's current valid strategy, or selects the first available option.

If the configured HBC entity or its option list is unavailable, HPVC leaves the selectors and **Enable HBC** preference unchanged. HBC strategy writes and battery-assisted reveal pause, while normal PV limiting and restore continue. HPVC checks at startup, after the configured entity changes, and once per minute. When HBC is not detected and **Enable HBC** is off, it skips the option-update script; valid options discovered later are still adopted automatically.

## HBC Price Zones graph

The graph displays HBC prices over 48 hours using the configured Charge and Expensive thresholds.

When HBC provides market prices, HPVC estimates the equivalent all-in prices using the configured Market and All-in sensors. It learns the relationship over time and temporarily uses the current `All-in − Market` difference until enough valid samples are available.

Prices are left unchanged when HBC already provides all-in prices or when the price type cannot be determined reliably.

The current interval is highlighted in blue, future prices are shown with reduced opacity, and the support report records the detected price type and conversion method. If HBC does not publish forecast data to `sensor.hbc_energy_prices_data`, the graph may remain empty or show **Loading**.


[← README](../README.md) · [Installation](01-installation.md) · [Settings](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md)
