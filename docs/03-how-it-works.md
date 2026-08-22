# How it works

[← README](../README.md) · [Installation](01-installation.md) · [Settings](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md)

## Control overview

HPVC follows this execution order:

1. Capture one Home Assistant state snapshot.
2. Validate static configuration and runtime input readiness.
3. Evaluate usable HBC batteries and Charge Priority.
4. Determine price, import-recovery, cooldown, night, and negative-price modes.
5. Calculate and distribute inverter targets.
6. Make one authoritative minimum, restore, adjust, or hold decision.
7. Build inverter writes and publish status, Insights, diagnostics, and accuracy.
8. Generate reports only when the user presses Generate report.

Home PV Control calculates a target total PV limit and then distributes that target over all configured inverters.

The flow evaluates every 10 seconds and once at startup. Configuration-helper changes trigger an immediate evaluation; live grid, price, PV, battery, and inverter states are used on the next evaluation cycle.

## Input validation and startup safety

HPVC separates **configuration validity** from **live input readiness**.

- Invalid or missing configured entity IDs become **Configuration error** after the startup restore window.
- If a correctly configured required grid, price, PV, or inverter-limit entity becomes invalid while HPVC is running, Node-RED halts control immediately and the supplied Home Assistant safety automation switches off the master toggle; no inverter writes are sent.
- Node-RED keeps a 90-second **Waiting for inputs** restoration grace before escalating the status to **Inputs unavailable**. This grace changes fault/status escalation only; it never continues control on stale values.
- HPVC resumes automatically only when it was disabled by this safety path and all required inputs have been healthy for 5 continuous seconds.
- During normal control, unavailable measurements are never replaced with invented `0 W` or full-limit values.

Night Restore is the deliberate exception: after a valid low-PV transition has started, expected nighttime loss of PV-power or inverter-limit telemetry can be tolerated while grid and price safety inputs remain monitored. If any inverter limit is unavailable during normal daytime control, all inverter writes are paused rather than reallocating the plant target across only the remaining inverters.

## Negative-price and Charge Priority completion behavior

The all-in-price sensor controls a dedicated override independently of normal market/export-price hysteresis.

### Negative all-in-price state machine

A valid all-in price `<= 0` always holds each inverter at its configured minimum. If HBC is unavailable, **Enable HBC** is off, or **Force charge at negative price** is off, HPVC stays in **PV only** mode and does not create a new HBC override.

When both HBC permissions are enabled and the native HBC strategy/charge-goal entities exist, HPVC saves the original HBC values and proceeds through confirmed phases: **Entering strategy → Entering goal → Active → Restoring goal → Restoring strategy**. It forces strategy `Charge`, then charge goal `batteries are full`; Charge Priority is off during this override.

A valid all-in price `> 0`, or disabling either HBC permission, starts restoration. If no forced HBC write was ever issued, the temporary override can be cleared directly. Once a forced write may have occurred, the confirmed restore sequence remains mandatory. An unavailable all-in sensor holds the current durable state rather than guessing an exit. PV-minimum protection continues independently until the all-in price becomes positive.

## Dynamic limiting conditions

Normal export limiting is allowed when:

- market/export price is at or below the PV limiting price
- PV production is above Min PV for control
- grid power is more negative than Export Start
- cooldown has passed
- the combined total target differs from the current combined limit by at least the deadband

Import recovery and HBC battery charge priority may raise limits even when measured PV is below Min PV for control. This is intentional because an active inverter limit can itself suppress the measured PV value.

### Import recalculation

When PV is already limited and grid import rises above Import Restore, HPVC recalculates upward instead of blindly restoring every inverter to full. For this recovery calculation it uses at least the current combined inverter limit as the available-PV baseline, so low measured PV does not prevent recovery.

## PV target calculation

```text
target_total = pv_power + grid_power - target_grid_power
```

Example:

```text
PV power = 2500 W
Grid power = -600 W
Target export = 0 W

target_total = 2500 - 600 - 0 = 1900 W
```

## Inverter target distribution

The total target is distributed from the live inverter limits while preserving direction: an increase never lowers an inverter and a reduction never raises one. Allocation is proportional to configured inverter capacity and redistributes only when an inverter reaches its minimum or maximum.

The deadband applies to the **combined plant change**, not to each inverter share. HPVC therefore keeps small proportional per-inverter shares once the total requested change is meaningful. Targets are whole watts, while decimal live limits are still reconciled accurately inside the allocator.

Example:

```text
PV1 full = 2000 W
PV2 full = 1000 W
Total full = 3000 W
```

PV1 receives 2/3 of the target and PV2 receives 1/3. With two equal 1500 W inverters, each receives 50%.

### Per-inverter minimum power

Every inverter has its own `minimum_power`; HPVC never requests less than this value.

### Plant-level deadband and proportional shares

Once the combined plant change reaches the deadband, proportional shares are retained even when an individual share is smaller than the deadband. Diagnostics mark those shares rather than discarding them.

## Restore and recovery

PV is restored to full power when the market/export price rises above the limiting price plus exit hysteresis, or when measured PV remains at or below the Night Restore threshold for 120 continuous seconds.

Actual PV is authoritative for Night Restore; `sun.sun` is supporting context. After Night Restore is confirmed, HPVC restores available inverter limits to full and suspends normal PV calculations. Expected nighttime disappearance of PV-power or inverter-limit telemetry is then tolerated, while grid, price, configuration, HBC, diagnostics, and reports continue.

Night Restore can start only from a valid numeric low-PV measurement. If PV telemetry disappears after the timer has started, **Night Restore pending** preserves the bounded transition and may complete only when `sun.sun` also reports `below_horizon`; otherwise normal strict validation returns.

Night Restore ends only after valid PV stays above `max(25 W, threshold + 15 W)` for 30 continuous seconds. Any dip back below that recovery level resets the timer.

## HBC battery charge priority

When HBC executes `Charge` or `Charge PV` inside the normal PV-limiting price zone, HPVC can preserve or release PV for battery charging. It begins from the HBC request plus usable battery headroom; measured charging is required before the presentation state becomes **Active**, but not before below-90% headroom can be requested.

Below 90% SOC, usable headroom is the configured maximum charge power minus current charging power. From 90% upward, each battery contributes only a bounded taper allowance learned separately in five SOC bands. HPVC combines the usable headroom of healthy batteries, accounts for current grid export, and caps increases by inverter capacity and Charge Priority step limits.

Batteries are evaluated independently. A stale, unavailable, full, maximum-power, or otherwise ineligible battery is excluded without cancelling another healthy battery. Negative all-in-price mode has higher priority and keeps normal Charge Priority off.

### Battery eligibility

For HBC 4.15.0, a battery contributes Charge Priority headroom only when its required power, SOC, maximum-charge-power, and RS485-control entities are valid. `select.marstek_mN_rs485_control_mode` must be `enable`. A battery can be excluded individually without blocking other eligible batteries.

## Per-battery taper-only Charge Priority

HPVC evaluates high-SOC tapering per battery so one tapering battery cannot reduce the normal headroom of another battery below 90%.

Initial taper step caps are **15% of max charge power at 90–94%**, **10% at 94–98%**, and **5% at 98–100%**. After a taper increase, HPVC waits for a newer battery-power sample before allowing another increase for that battery.

Clean failed probes reduce that battery's unconfirmed taper allowance. Ambiguous or contaminated probes do not train the learned ceiling; they use increasing backoff instead. Probe and failure state is stored per battery and SOC band, and reaching the configured charging cutoff cancels any pending probe.

## Charge Priority degraded operation and diagnostics

- A battery with unavailable or stale power/SOC telemetry is excluded independently. Charge Priority continues with the remaining healthy batteries, or is suspended when none remain. A transition-only Insight is written when a battery is excluded and when it recovers.
- If any configured inverter limit entity is unavailable or non-numeric, HPVC pauses all inverter writes. A transition-only Insight identifies the affected inverter, and a recovery Insight is written after the complete inverter group is valid again.
- Charge Priority now exposes two separate states: whether Charge Priority is active and whether a PV increase is currently possible.
- The exact state/end reason is retained, including no headroom, export already consuming headroom, deadband, inverter maximum, full batteries, unsafe telemetry, or HBC no longer executing Charge/Charge PV.
- The support report includes a Charge Priority decision table and per-battery eligibility, SOC mode, headroom contribution, and exclusion reason.

The 90% SOC threshold changes headroom calculation from normal to taper-aware. It does not directly start or end Charge Priority.

### HBC battery charge order

For multi-battery HBC, HPVC reads HBC's prioritized-battery helper and priority-change interval when available. Values must be valid whole HBC values; malformed live values are reported rather than rounded or clamped.

HPVC follows the same rotated priority order HBC uses while still combining usable headroom across healthy batteries. A remembered positive maximum charge power may bridge a short genuinely unavailable helper state, but malformed, zero, or negative live values contribute no headroom.

## HBC Charge Priority coordination

HBC remains the fast grid-balancing controller during Charge Priority, while HPVC manages the available PV ceiling. After HPVC raises inverter limits for Charge Priority, it starts a **15-second response window**. During this window, normal HPVC export limiting is suppressed so HBC can adjust battery charging from live grid-power feedback without HPVC issuing an immediate opposite correction.

Outside the response window, export limiting remains suppressed while Charge Priority is engaged, confirmed battery charging headroom remains greater than the HPVC deadband, and the persistent-export fallback has not activated. If grid export stays beyond **Export Start** continuously for **30 seconds** while usable headroom still exists, the fallback activates and HPVC may reduce PV. The timer resets as soon as export returns above the Export Start threshold or Charge Priority/headroom is no longer applicable.

The support report exposes the response-window state, persistent-export age, fallback state, and export-limiting suppression state explicitly under **HBC & Battery Diagnostics**.

### Charge Priority state entity

`binary_sensor.hpvc_charge_priority_active` is on only while HPVC has confirmed HBC Charge Priority is active. It can be used in dashboards and history graphs. During this state, new export-based PV reductions are blocked, although `binary_sensor.hpvc_pv_limited` may remain on temporarily while previously reduced limits are being raised.

Presentation-state semantics distinguish charging state from control influence: **Off** means Charge Priority is not applicable or no eligible charging request is active; **Requested** is reserved for unresolved usable-battery telemetry; **Waiting** means HBC requests charging and usable headroom exists, but measured charging is not yet confirmed or no currently usable PV increase exists; **Active** requires confirmed charging operation. **Active may remain displayed after usable headroom reaches zero while charging continues.** In that case `HPVC export limiting suppressed` is `No`, normal PV limiting resumes, and the accuracy model may score eligible samples again.

### Tiered battery telemetry freshness

Battery power uses tighter freshness while actively charging/discharging and a wider idle allowance. SOC has a longer age allowance and may be corroborated by recent battery-power activity or a real device heartbeat. Unknown, unavailable, non-numeric, or implausible values remain invalid.

A stale battery is excluded independently. Recovery requires stable healthy telemetry before the battery is admitted again, preventing rapid state flapping.

### Marstek cutoff-aware battery telemetry

HPVC reads each battery's charging and discharging cutoff capacities. The pair is valid only when both are numeric and the discharging cutoff is lower than the charging cutoff.

At or above the charging cutoff, a battery contributes 0 W charging headroom and any taper probe is cancelled. An idle battery already at its charging cutoff can remain conservatively classified as full while its numeric SOC and power states stay available. The discharging cutoff does not receive this indefinite freshness exception.

## Battery charge-priority diagnostics and safeguards

Each battery needs valid AC power, SOC, charging/discharging cutoffs, and—when used for HBC 4.15.0 control—RS485 mode `enable`. Negative AC power means charging. Maximum charge power must be positive; a remembered positive value may bridge a genuinely unavailable helper for up to 30 minutes, but malformed, zero, or negative live values contribute no headroom. Invalid telemetry excludes only that battery. If none remain usable, Charge Priority pauses until at least one battery has been healthy for 60 seconds.

## Control boundaries and validation

HPVC requires `Export Start < Target Export < Import Restore`, `Import Restore >= 0 W`, and each inverter minimum to be lower than its full power. Invalid static configuration or a required live-input outage switches off the HPVC master toggle and blocks writes. When configuration validity and all required inputs remain healthy for 5 continuous seconds, HPVC resumes automatically only if it was running before the fault. Any unavailable configured inverter limit therefore stops all inverter writes.

## Cooldown and deadband

Every inverter write starts the configured cooldown; HPVC keeps evaluating but sends no new PV write until it expires. A newly started cooldown always takes precedence over an old cooldown that happened to expire at the beginning of the same runtime evaluation.

HPVC also keeps one authoritative inverter target in flight at a time. After a write, normal PV correction, restore, and HBC Charge Priority/taper releases wait until the live inverter-limit entities confirm the requested target and PV either moves materially in the commanded direction or a fresh PV observation shows that no measurable production response was physically required because the plant was already availability-limited. PV movement in the opposite direction does not release this lock. A bounded timeout prevents a permanently stale sensor from freezing control forever. Negative-price minimum protection remains the higher-priority safety action.

Deadband is evaluated at combined-plant level, so smaller proportional per-inverter shares are retained once the total change is meaningful. Daily Control Accuracy is separate: its 0–100 headline uses a side-aware, time-weighted normalized RMS excursion outside **Export Start…Import Restore**, normalized independently on the export and import sides. HBC Charge Priority has no sub-deadband full-restore exception.

## Persistence and safeguards

User-configurable Home Assistant helpers omit `initial:` values so Home Assistant restores user changes after restart. The transient helpers `input_boolean.hpvc_report_ready`, `input_boolean.hpvc_report_generating`, and `input_boolean.hpvc_negative_override_fault` use `initial: false` so stale transient state is not restored. The negative-override fault helper intentionally resets to `off` on Home Assistant restart; Node-RED re-derives and, when required, reasserts the effective fault state from the persisted negative-price override journal during startup recovery. First-run defaults are applied only while `input_boolean.hpvc_defaults_applied` is off.

The v1.3.0 diagnostic price sensor is `sensor.hpvc_diag_market_export_price`. Existing installations that previously used `sensor.hpvc_diag_market_price` must update dashboard or external references and may remove the old entity from the Home Assistant entity registry after confirming the new sensor is available.

A Home Assistant first-run automation applies the shipped defaults only when `input_boolean.hpvc_defaults_applied` is still off. A separate one-time marker seeds **Force charge at negative price** to **On** when the setting is first introduced, including upgrades. The seed check also runs after reload without resetting an already-seeded choice. After the marker is set, normal restarts and reloads preserve the user's choice; **Restore defaults** turns the option On again.

### Persistent current-day journal

HPVC stores current-day Insights, Power Control history, Daily Control Accuracy, and the durable negative-price override in `/config/hpvc-data/runtime-history.json`. Writes use a temporary file plus atomic rename so a partial journal is not promoted as valid state.

The negative-price override uses an additional persistence barrier: original HBC values must be durably published before the first forced HBC write is allowed. On restart, the journal is schema-validated and restored before runtime evaluation resumes.

Routine accuracy-counter changes are batched to reduce unnecessary storage writes; safety-critical override changes are persisted immediately.

### Daily history and accuracy restoration

- Today’s Insights and Power Control activity are scoped to the calendar day in Home Assistant's configured time zone.
- The journal survives Home Assistant restarts, Node-RED restarts/deploys, and re-importing or reinstalling the HPVC flow.
- Daily Control Accuracy schema-11 accumulators are restored from the same journal before normal calculations and journal writes resume. Time/causal continuity is deliberately **not** restored: the first eligible sample after restart starts a new interval using the learned scheduled runtime cadence and cannot be causally compared with the pre-restart sample.
- Yesterday’s entries and accuracy are never restored after midnight in the Home Assistant time zone, even if the Node-RED/container local time zone differs.
- Startup initialization creates the journal before the first read, preventing a clean-installation `ENOENT` message.

### Insight deduplication and grouping

Battery telemetry and HBC safety warnings are transition-based. A changing age value does not create a new warning. The same active fault remains represented by one Insight until telemetry has been continuously healthy for 60 seconds, at which point a single recovery Insight is recorded.

The dashboard and generated HTML report use the same consecutive grouping rule. Identical activities that occur directly after one another are shown once with an occurrence count such as `×5`; any different Insight closes the run. The downloadable TXT report intentionally keeps every raw Insight event as its own row, so it remains lossless even when HTML is compact. Both representations are derived from the same shared report model.


The original HBC strategy and charge goal are persisted before the first forced HBC write. If either entity was initially unavailable, the values captured after recovery receive a new persistence token and a second acknowledged journal write before forcing can continue.

## Runtime diagnostics

`input_text.hpvc_last_targets_json` stores the compact latest-calculation JSON used by diagnostics and support reports.

### Power Control timeline

Power Control records meaningful mode transitions and periodic stable-state heartbeats for the current local day. Modes describe actual control influence, including **Normal**, **PV Limited**, **PV Restore**, **Charge Priority**, **Charge Priority + PV Limited**, and **Paused/Fault**.

Activity rows retain the action that caused a real inverter write, so report summaries can distinguish reductions, upward adjustments, restores, and Charge Priority releases. HBC-only safety pauses keep the underlying PV mode and add **HBC Paused** because normal PV control continues.

Consecutive identical entries are grouped for display while the journal keeps canonical event history for reporting.

## Sensor Health thresholds

Grid power, PV power, market/export price, all-in price, `sun.sun`, inverter-limit entities, and HPVC output states use availability and value validation rather than timestamp-age staleness checks, because unchanged state age is not a reliable failure signal for those entities. Battery sensors use the tiered freshness model described under HBC Charge Priority.

### Operational Insights

Transition-only Insights cover night restore start/end, HBC executing substrategy changes, tiered battery freshness reasons, taper-probe start/result/timeout, and support-report success, failure, or watchdog timeout. Routine evaluations remain silent.

## Accuracy and factor attribution

Accuracy uses the schema-11 model described under **Daily Control Accuracy and target-tracking metrics** below. The headline is time-weighted and action-band-relative; RMS/MAE remain Target Export/deadband-referenced; and the four visible factors are percentage loss contributions to the headline action-band accuracy loss, allocated only from action-band excursions that actually reduce that score.

HBC 4.15.0 supports **1–6 configured batteries**. HPVC follows that native limit for HBC Charge Priority, report, and dashboard battery diagnostics. For battery eligibility, HPVC uses fresh live power telemetry as the authoritative signal. SOC is still required to be numerically available, but its timestamp may be older because SOC naturally changes slowly. HPVC remembers the last valid maximum charge-power setting for up to 30 minutes when that entity is temporarily unavailable; after that TTL the battery is excluded until a live maximum returns.

### Decision and response diagnostics

HPVC stores compact latest-calculation data, per-inverter calculated/requested targets, pending write verification, and current-day accuracy factors. Successful writes are confirmed internally; warnings are emitted only after an unsuperseded request exceeds the verification timeout.

### Unified HTML and TXT model

HPVC builds one internal report model and renders it as HTML and TXT. This prevents fields from appearing in only one format. Diagnostic values are read from existing helpers, configured entities, runtime debug state, inverter calculations, battery diagnostics, write-verification context, and Insights.

### Daily Control Accuracy and target-tracking metrics

The user-facing 0–100 headline and the physical engineering metrics answer different questions:

- **Daily Control Accuracy** asks whether HPVC kept grid power inside the configured control mandate. For every eligible sample, the normalized excursion `z` is zero while grid power is between **Export Start** and **Import Restore**. Below Export Start, `z = (Export Start − grid) / (4 × (Target Export − Export Start))`; above Import Restore, `z = (grid − Import Restore) / (4 × (Import Restore − Target Export))`. The daily score is `100 × max(0, 1 − sqrt(sum(z² × dt) / sum(dt)))`.
- **RMS control error** and **MAE control error** measure actual tracking around **Target Export** and do not depend on Export Start/Import Restore. Their per-sample physical error is `e = max(0, abs(grid − Target Export) − Deadband)`.
- **Time outside target deadband** is the time-weighted share of eligible time where `e > 0`.
- **Deadband-exceedance RMS/MAE** is computed only over intervals where `e > 0`, avoiding the zero-mass artefact of dividing a full-day RMS by a full-day MAE when most samples are exactly zero.
- **Band excursions** reports how many eligible samples were outside Export Start…Import Restore, alongside the total eligible sample count. A low excursion count makes a volatile daily headline self-evident without pretending that adjacent 10-second samples are statistically independent.

Eligibility remains intentionally narrow: required grid/PV inputs and threshold configuration must be valid, PV must actually be curtailed by a physically binding inverter limit, negative-price minimum and Night Restore are excluded, cooldown is excluded, and Charge Priority is excluded only while its response window/export suppression/PV-increase action is actually influencing PV control. Periods where released PV is limited by insufficient sunlight are not scored.

Time weighting uses the following continuity rules:

1. Any ineligible evaluation clears both the elapsed-time predecessor and the causal factor predecessor.
2. The first eligible sample after an eligibility gap or restart receives the **learned scheduled runtime interval** as its weight; if it has physical target error, that error is retained in RMS/MAE but marked internally as a continuity-gap exclusion for raw factor attribution.
3. Continuous eligible samples use actual elapsed time capped dynamically at roughly **two scheduled runtime intervals** (with a small safety margin), preventing a missed trigger from carrying a long gap’s weight. Only the repeating `timer` evaluation trains this cadence; startup/settings retriggers may run control and event detection but cannot distort nominal weighting.
4. Restart/deploy restores accumulated schema-11 sums only; it always starts a new causal/time interval.

### Accuracy-loss factors and raw attribution

The compact dashboard factors—**Control response**, **House load changes**, **PV availability**, and **Other**—split the actual headline loss (`100 − Daily Control Accuracy`). Only harmful action-band excursions contribute to this pool; helpful movement does not.

HPVC uses direction-aware physical evidence rather than a winner-takes-all classifier. It estimates house-load movement from PV, grid, and signed battery power; associates confirmed recent HPVC limit movement with Control response; treats uncommanded PV movement as PV availability; and routes independent battery movement, manual/external limit movement, or unresolved residual to Other. Mixed events may split across several factors.

The support report keeps the engineering view separately: raw attribution shares, attribution coverage, no-action and continuity-gap exclusions, RMS, MAE, and time outside deadband. These diagnostics are not the same values as the four dashboard loss contributions.

### Accuracy sampling at cooldown start

The measurement that triggers a normal PV correction is retained for accuracy before cooldown exclusion begins. Later settling/cooldown samples remain excluded.

For inverter-limit changes of at least **500 W**, the shared post-write lock also waits for the live limits to confirm the requested target, PV to move in the commanded direction, and two consecutive fresh PV observations to remain within the stability tolerance before an opposite correction may be issued. Smaller commands keep the faster settle path.

### Continuous physical-event detector for accuracy attribution

The attribution detector runs on every HPVC evaluation, even when the headline accuracy sample is temporarily ineligible. A significant grid step is held until a fresh post-trigger PV observation arrives, with an adaptive **20–30 second maximum reconciliation window** when OpenDTU is late, so later PV and inverter-limit updates can explain the same original event instead of being misclassified because sensors updated in a different order. Battery handling is deliberately causal rather than fully delayed: only battery movement already visible at trigger time may explain the original grid step. A battery change that appears after the trigger—such as a battery reducing discharge in response to a large import—is recorded as a later response and cannot retroactively replace the initiating House-load event with **Other**.

Matched events can be reused only while they remain recent, on the same action-band side, and physically consistent. Core grid/PV/inverter telemetry breaks clear pending causal state. If battery-power telemetry alone is uncertain, HPVC continues in degraded mode but suppresses House-load inference rather than treating missing battery power as 0 W. One conservative exception exists for a numeric 0 W battery independently confirmed at its configured charging cutoff/full boundary; that unchanged full-idle value may remain valid physical evidence for House-load accounting. The support report records whether House inference was accepted or blocked and why, whether post-trigger HPVC PV was stripped, and whether independent battery movement was classified as Other.

## Report generation and diagnostics

Reports are generated only when **Generate report** is pressed. One shared snapshot/model is rendered to HTML and TXT, written through a generation-scoped temporary file, and atomically published only if that generation still owns the report lock. A watchdog prevents late or stalled generations from replacing a newer report. Report-storage initialization is retried through a bounded recovery path after transient startup/filesystem failures; the periodic recovery check runs every 30 seconds and user report requests can trigger the same throttled retry path without creating a tight loop. If a later report file write or atomic publication shows that previously-ready storage has disappeared, HPVC invalidates the cached ready state and uses the same recovery path; a recent report request is retained briefly for replay after storage returns.

The HTML report includes executive status, live inputs, decision evaluation, accuracy, inverter diagnostics, HBC/battery diagnostics, settings, sensor health, Insights, and Power Control history. Mobile **Collapse** and **Top** controls are recalculated after page restore, scrolling, viewport/orientation changes, and tab visibility changes.

Generation or report viewing never changes HPVC settings, inverter limits, or HBC behavior. A failed build/publication produces a persistent error notification and leaves any previously published valid report intact.

### Insight retention and source

The dashboard helpers expose the latest 20 Insights, while generated HTML and TXT reports read the complete current calendar day from the date-scoped Node-RED journal, up to 1000 entries. Helper rows are used only as a recovery fallback when no canonical current-day journal exists.

### Report semantics and parity
- The Negative All-In Override block is presented consistently in both HTML and TXT output, including saved values, persistence state, fault state, retry state, and inverter drift.

The report carries battery freshness mode and heartbeat diagnostics, labels unconfirmed telemetry as `Uncertain`, validates numeric sensor states and `sun.sun` semantics, and identifies the Insight-history source. Unreliable PV-released and net-constrained energy estimates were removed, and deadband reporting is labelled as activity-sample based.

HTML and TXT are rendered from one shared model and expose the same applicable house-level and per-battery fields, including normal battery headroom, controlled taper allowance, taper confirmation state, and per-battery taper caps. HTML groups consecutive identical Insight runs for readability; TXT lists every underlying raw Insight event. Parity validation accounts for that intentional presentation difference.

### Report timestamps

Generated, inverter-write, and verification timestamps are formatted using Home Assistant’s configured time zone. The report's current-day boundary and filtering use that same Home Assistant time zone, so the report does not select the wrong day's history when Node-RED runs in a container with a different local time zone.

### Report presentation

- **Download report** saves the current diagnostic report as a UTF-8 `.txt` file with a timestamped filename.
- The HTML report and downloaded TXT report use the same shared data model; HTML groups consecutive identical Insights, while TXT preserves each raw Insight event.
- The report includes current status, inverter and battery tables, control settings, HBC/HBC battery charge priority information, and current-day Insights.
- Battery tables match the inverter table layout and hide entity IDs for cleaner presentation.
- HBC battery charge priority uses its own Insight type, while normal PV limiting and restore actions use `PV limit`.

## PV price hysteresis

PV limiting enters at or below the configured limiting price. Once active, it remains active until the market/export price rises above `limiting price + hysteresis`. If the market/export price becomes unavailable, HPVC follows the safe-pause policy and holds current inverter limits until the sensor recovers.

## Large-command transient damping

HPVC keeps small target corrections responsive. Larger corrections are bounded relative to the configured total inverter range and applied in stages, with fresh plant feedback between stages. If the immediately preceding HPVC command was a large move in the opposite direction, the first reverse step is capped more conservatively. During HBC Charge Priority, loss of confirmed battery charging also starts a short bounded transition-settle window so the independent battery controller can change state before HPVC reacts to the full transient grid error. These rules are plant-size-relative and do not depend on a particular inverter, battery model, or entity name.

Delayed inverter-limit motion remains associated with its originating HPVC command while that command is pending. If a newer HPVC command supersedes it, any progress already observed on the old command is retained for causal attribution so that the delayed HPVC response is not reclassified as a manual/external inverter change.

## HBC strategy integration

HBC remains the battery-strategy controller. The dashboard exposes HBC's own strategy selector, while HPVC reads `input_text.house_battery_strategy_active_sub_strategy` as the executing state.

**Enable HBC** is the master permission for HPVC to control charging in HBC. Normal Charge Priority uses HBC's executing `Charge`/`Charge PV` state only inside the normal PV-limiting price zone. Negative all-in-price mode is separate: PV minimum is always enforced, while forced HBC charging occurs only when **Enable HBC** and **Force charge at negative price** are both on and the native override entities exist.

Battery freshness, SOC cutoffs, RS485 state, and charge-power capacity determine whether each battery can contribute headroom. An ineligible battery is excluded independently so healthy batteries can continue.

## Node-RED flow architecture

The supplied flow is split into four tabs:

| Tab | Purpose |
|---|---|
| **HPVC Inputs v1.4.0** | Reads Home Assistant state, validates configuration and live inputs, and restores persisted runtime state. |
| **HPVC Engine v1.4.0** | Evaluates prices, cooldown, Night Restore, battery eligibility, Charge Priority, and the total PV target. |
| **HPVC Outputs v1.4.0** | Distributes inverter targets, performs writes, verifies results, and publishes status, Insights, and accuracy. |
| **HPVC Reports v1.4.0** | Builds and publishes the on-demand HTML/TXT support report. |

Import the complete `hpvc_flow.json`; the tabs are designed to operate together.

## Report data timing

The report captures a fresh Home Assistant snapshot when generated. Decision, inverter-target, battery-headroom, and taper details come from the latest completed HPVC evaluation and show their timestamp and age. A notice appears when those runtime diagnostics are old or not yet available.

HTML and TXT use the same report model. The report's timestamps and current-day selection follow the Home Assistant configured time zone. Generate a new report whenever you need an up-to-date snapshot.

[← README](../README.md) · [Installation](01-installation.md) · [Settings](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md)

