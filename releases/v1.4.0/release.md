# Home PV Control v1.4.0

Home PV Control v1.4.0 focuses on safer HBC coordination, predictable negative-price behavior, stronger runtime validation, more stable inverter control, and clearer diagnostics while keeping the core goal unchanged: control PV export without unnecessarily sacrificing useful solar production.

## Major changes

- **HBC Charge Priority** replaces Hidden PV Reveal and coordinates available PV with HBC `Charge` / `Charge PV` execution.
- **Force charge at negative price** is seeded **On** once on install/upgrade, while **Enable HBC** remains the master permission for every HPVC write to HBC. A later manual Off choice survives normal restarts/reloads; **Restore defaults** turns it On again.
- Negative all-in prices always protect against unwanted export by locking PV to configured inverter minimums; HBC grid charging remains optional.
- HBC 4.15.0 multi-battery support is aligned to **1–6 batteries** with RS485 eligibility, priority order, headroom and taper handling.
- Runtime evaluation is **10 seconds**, shipped cooldown **30 seconds**, and shipped Target Export **0 W**.
- Large/transient PV commands are now staged and reversal-damped without slowing ordinary small corrections.
- Asynchronous inverter writes share one command lock and retain causal identity through delayed confirmation.
- Daily Control Accuracy, Today’s Insights, Power Control history and support reports received major reliability and attribution improvements.
- The **Settings** tab is always visible; the obsolete Settings-enable helper has been removed.

### Onboarding and first run

- Recommended first-install defaults now initialize reliably before onboarding validation completes.
- Onboarding completion waits for all required live inputs and validates the full control-setting set, so setup progress cannot report completion from only partial validity.
- First-install progress requires configured core entities to exist, be available and contain valid live states.
- Inverter configuration is validated as part of onboarding.
- First-install graphs remain hidden until onboarding is complete.
- Resetting onboarding on an already-valid installation triggers a fresh validation and then completes automatically.
- Restore Defaults preserves configured entity selections and inverter count while restoring HPVC control settings.
- User-configurable helpers retain their edits across normal Home Assistant restarts/reloads.

## Safety and recovery

### Core input and inverter validation

- Required sensors, helper ranges, duplicate entities and threshold relationships are validated before writes.
- Export Start, Target Export and Import Restore must remain in a valid ordered relationship.
- If any configured inverter limit is invalid or unavailable, the complete configured inverter group is paused rather than controlling only part of the plant.
- Required live-input loss pauses Node-RED control **immediately**. The 90-second restoration grace only postpones escalation from **Waiting for inputs** to the harder **Inputs unavailable** status; it does not continue control on stale measurements.
- The supplied Home Assistant package separately turns the HPVC master control Off when required inputs become invalid and remembers that the disable was automatic. It re-enables HPVC only after the required inputs/configuration have remained healthy for **5 continuous seconds**.
- Manual user switch-off clears the automatic-resume latch, so a later sensor recovery cannot unexpectedly re-enable HPVC.

### Night Restore

Night Restore is designed around expected nighttime telemetry behavior:

- It restores inverter limits once and suspends normal PV calculations while production is effectively gone.
- Expected disappearance of PV power and inverter-limit telemetry after sunset does not create false control faults.
- Grid and price safety inputs remain required.
- `unknown` / `unavailable` PV can never be treated as a measured 0 W trigger.
- Normal control resumes only after valid PV has recovered above the required hysteresis for the configured recovery period.
- Night Restore is excluded from physical-attribution diagnostics so expected zero/stale nighttime PV does not inflate freshness-block counters.

### Battery telemetry

- Battery freshness uses SOC, AC-power telemetry and cutoff-aware idle behavior instead of one timestamp alone.
- Long-unchanged SOC can remain trusted when fresh AC-power telemetry confirms the battery is still reporting.
- Dual-stale telemetry suspends HBC-dependent Charge Priority while normal PV control can continue where safe.
- A battery at its configured charging cutoff can remain conservatively classified as full with 0 W headroom while its numeric entities remain valid.
- Live-but-invalid charge/discharge cutoff values are faults; HPVC does not hide them behind remembered defaults.
- Uncertain batteries are excluded from Charge Priority without unnecessarily stopping normal PV control.

### Runtime and report recovery

- Scoped Inputs/Engine/Outputs Function-error handlers now release only the runtime evaluation lock owned by the failed cycle, so a caught exception cannot unnecessarily suppress the next control evaluation or clear a newer cycle.
- Report storage now retries automatically after transient startup/filesystem failures. Recovery checks run every **30 seconds**, while a user Generate report request can request the same throttled retry immediately; retry attempts are bounded to prevent an exec storm.

## HBC Charge Priority

### Negative-price charging

At a valid all-in price `<= 0`, HPVC always locks every configured inverter to its user-defined minimum.

If both HBC permissions are enabled:

1. HPVC saves the current HBC strategy and charge goal.
2. It confirms the saved state is persisted.
3. It forces HBC to **Charge** and the required charge goal.
4. PV remains at configured minimums during the negative-price interval.
5. When the interval ends, HPVC restores the previous charge goal and strategy and confirms recovery before normal HBC control resumes.

If **Enable HBC** is Off, or **Force charge at negative price** is Off, the same negative-price PV protection remains active but HPVC does not start new HBC control. If permission is removed while an override is already active, only the confirmed restore sequence is allowed.

The override state is persisted and includes retry, timeout/fault handling and drift detection so restart/deploy does not silently lose the previous HBC state. Standalone installations without HBC use PV-only negative-price protection and never create an HBC restore lock.

### Charge Priority

Charge Priority no longer assumes that selecting a charging strategy means the batteries are actually charging. It combines HBC execution state, measured battery power and verified battery headroom.

- States are **Off, Requested, Waiting, Active**.
- `Charge` and `Charge PV` are both treated as charging requests.
- HBC 4.15.0 battery order and RS485 eligibility are respected for **1–6 batteries**.
- A battery contributes headroom only when its required telemetry and RS485 control state are valid.
- Multi-battery headroom is aggregated without allowing one tapering/full battery to unnecessarily reduce usable headroom from another battery.
- A short HBC response window allows HBC to absorb newly released PV before HPVC makes the opposite export correction.
- When confirmed charging drops into Waiting, HPVC uses a bounded **15-second transition-settle window** so a temporary battery-power transition is not immediately treated as a new steady-state grid error.
- Persistent unabsorbed export still falls back to normal PV limiting.

### Taper and high-SOC handling

- Added per-battery taper zones and learned charging ceilings.
- Bounded probes test whether additional PV can still be absorbed.
- Post-write confirmation separates real absorption failure from ambiguous telemetry.
- Repeated ambiguous probes use increasing backoff instead of corrupting learned ceilings.
- Cutoff/full-state recovery cancels obsolete taper probing and keeps zero-headroom batteries from being treated as available capacity.

## PV control and allocation

### Defaults and normal control

- Runtime evaluation: **10 s**.
- Cooldown: configurable **10–60 s**, shipped default **30 s**.
- Target Export: shipped default **0 W**.
- Export Start range: `-5000..0 W`.
- Target Export range: `-5000..+500 W`.
- HPVC requires `Export Start < Target Export < Import Restore`.
- Multi-inverter allocation preserves configured per-inverter minimums and maximums.
- Normal curtailed-PV corrections use the current commanded inverter-limit total plus grid error, reducing fast export/import reversals caused by lagging PV telemetry.
- Duplicate inverter writes and duplicate rapid activity snapshots are suppressed.

### Shared command lock and asynchronous write confirmation

- Normal PV correction, restore and HBC Charge Priority/taper release share one in-flight inverter-command lock.
- A second non-safety target is not issued while a previous write is still propagating.
- Live inverter limits must confirm the previous target and PV must respond credibly in the requested direction before normal control reverses the command.
- Large inverter-limit commands also require **two consecutive fresh, reasonably stable PV observations** after limit/direction confirmation before a meaningful reverse correction is allowed.
- Write verification is progress-aware and hardware-agnostic. Slow integrations are not marked failed merely because they miss an early fixed confirmation point; delayed progress remains locked and observed through a bounded extended verification horizon.
- Delayed or superseded HPVC commands keep their originating command identity, so observed inverter movement cannot later be misclassified as an external/manual limit change.

### Large-step and reversal damping

The controller remains fast for ordinary corrections. Extra damping applies only to large/transient changes:

- Large normal PV corrections are staged relative to the configured total plant range rather than jumping directly between extremes.
- Large Charge Priority releases use the same plant-relative shaping.
- The first large command in the opposite direction after a recent large HPVC command is capped more conservatively.
- The configured target and user Deadband are unchanged; small corrections continue on the normal evaluation cadence.
- Oscillation diagnostics monitor repeated **large HPVC command-direction reversals**, including reversals around HBC/battery transitions when they are part of the coupled loop. Explicit negative-price, Night Restore and price-zone full-restore transitions are excluded from that warning path.

## Reports and Today’s Insights

### Daily Control Accuracy

Daily Control Accuracy was reworked to show both the headline result and the main physical causes of lost tracking accuracy.

The dashboard keeps four user-facing loss factors:

- **Control response**
- **House load changes**
- **PV availability**
- **Other**

These values are estimated percentage contributions to the headline accuracy loss and reconcile to `100 − Daily Control Accuracy`.

Under the hood:

- Accuracy is continuity-aware and time-weighted rather than assuming every sensor updates synchronously.
- The physical-event detector runs with the normal HPVC evaluation and uses an adaptive **20–30 second reconciliation window** for delayed PV/battery/inverter-limit telemetry without delaying control itself.
- Battery causality is trigger-bounded: movement already visible at the grid trigger may explain that event; a later independent battery reaction belongs to the following physical interval instead of retroactively hiding the initiating house-load step.
- PV movement caused by an HPVC command issued after an older grid trigger is stripped from that older event before House/PV attribution.
- Delayed HPVC inverter-limit response keeps its command identity through verification/supersession and remains **Control response** rather than leaking into external/manual **Other**.
- Independent battery/HBC movement is classified as **Other**; HPVC-directed Charge Priority movement remains **Control response**.
- Uncommanded PV movement with coherent evidence is classified as **PV availability**.
- House-load inference uses physical power balance only when PV and battery evidence are coherent.
- Attribution degrades safely when telemetry is ambiguous instead of inventing house-load movement.
- A generic **High / Medium / Low** result-confidence indicator is derived from eligible sample count and continuity-gap burden.

Support reports expose attribution diagnostics including House inference accepted/blocked reasons, independent battery → Other, post-trigger HPVC PV stripping, delayed command response, uncommanded PV → PV availability and inferred House residuals.

### Support reports

- HTML and TXT are generated from one shared fresh model.
- Reports include HBC strategy/execution, Charge Priority, battery eligibility, taper state, negative-price override, inverter diagnostics, sensor health, result confidence and accuracy attribution diagnostics.
- Report-only battery fallback logic follows the same runtime validation and freshness rules as live control.
- Non-structural HTML/TXT parity warnings no longer prevent a successfully rendered report from reaching **View report**.
- Structural/shared-model parity failures remain blocking.
- Generation-scoped temporary files, generation IDs and atomic publication prevent an older timed-out report from overwriting a newer report.
- Report timestamps and current-day selection follow Home Assistant’s configured time zone.

### Today’s Insights and Power Control history

- HBC-only telemetry pauses are reported as HBC pauses instead of full HPVC faults when normal PV control can continue.
- Required-input/configuration blocks remain clearly classified as control faults.
- Recovery rows were cleaned up to avoid startup/redeploy false positives.
- Power Control separates genuine PV restore actions from ordinary upward adjustments.
- Charge Priority increases, PV reductions, restores and ordinary upward adjustments are counted from explicit HPVC command events rather than inferred later from asynchronous live-limit timing.
- Retention covers a full day at the 10-second cadence plus transition margin.
- Current-day rows and midnight rollover are persisted consistently.

## Dashboard

- The **Settings** tab is always visible; the Main-dashboard Settings button and obsolete `input_boolean.hpvc_config` visibility helper were removed.
- Added **Force charge at negative price** under **Optional HBC Setup**.
- HBC-only controls and badges remain hidden when HBC is unavailable.
- The **HBC Price Intervals** graph now also requires `binary_sensor.hpvc_hbc_available`, preventing the graph from referencing HBC-only data while HBC is unavailable.
- The **At minimum PV** helper uses the same fixed **1 W** minimum-state tolerance as runtime control. The user-configured PV adjustment Deadband remains unchanged and continues to be used by the control logic where intended.
- Removed the `card-mod` dependency.
- ApexCharts remains the only custom card required by the supplied dashboard graphs.
- The Daily Control Accuracy card remains compact; detailed engineering metrics stay in the support report.
- Report/mobile controls and visibility behavior were cleaned up.

## Bug fixes

- Fixed runtime evaluation-lock recovery after a scoped Function exception by carrying the cycle ID on the message immediately after lock acquisition and clearing the lock only when the failing cycle still owns it.
- Fixed report-storage recovery after a transient startup mount/writability failure; storage can now become usable later without requiring a Node-RED redeploy or restart.
- Removed an unused stale Main-dashboard screenshot that still showed the retired Settings button.
- Corrected first-install wording so the README and installation guide match the implemented automatic HPVC enable behavior after validation succeeds.

## Architecture and packaging

- Insights, Power Control, Daily Control Accuracy and negative-price override state share `hpvc-data/runtime-history.json`.
- Journal writes are serialized and guarded so stale write completions cannot overwrite or acknowledge newer state.
- Runtime waits for current-day journal restoration before dependent actions continue.
- Current-day restore, midnight rollover, clean-install initialization and legacy migration are handled in one persistence path.
- Node-RED is organized into four functional tabs with shared global context only where cross-tab state is required.
- Scoped runtime error handling surfaces Function-node failures without disabling normal self-recovery.
- Obsolete/declaration-only internal processing found during the final audit was removed without changing runtime behavior.
- Removed the write-only `homePvControlDirectionHistory` context reset after confirming no packaged runtime path reads it.

### Compatibility

- Home Assistant with package support.
- Node-RED with `node-red-contrib-home-assistant-websocket` **0.80.3 or newer**.
- One or more writable inverter `number.*` power-limit entities.
- ApexCharts Card for the supplied dashboard graphs.
- Optional Home Battery Control; HBC 4.15.0 is supported for **1–6 batteries**.


## Documentation

- Night Restore wording now matches runtime behavior: valid low PV drives entry; `sun.sun` only corroborates a pending transition when PV telemetry disappears after the timer has started.
- Stale pre-final dashboard/report screenshots were removed; the Node-RED architecture overview was regenerated from the final shipped v1.4.0 flow.

- Installation text now states that HPVC enables automatically after required live inputs and control settings validate successfully.
- Report documentation now describes bounded automatic report-storage recovery and the queued Generate report behavior.
- Release documentation is organized from major/safety changes through control, reporting, dashboard, bug fixes, architecture/packaging, documentation and upgrade instructions.
- Removed the unreferenced stale Main-dashboard screenshot asset rather than publishing an image that no longer matches v1.4.0.

## Upgrade instructions

1. Back up the existing Home Assistant package, dashboard, Node-RED flow and `hpvc-data` journal.
2. Replace `home assistant/hpvc_config.yaml`.
3. Replace the complete `node-red/hpvc_flow.json` flow.
4. Replace or merge `home assistant/hpvc_dashboard.yaml`.
5. Restart Home Assistant after package changes and deploy Node-RED.
6. Verify configured sensors and inverter limits.
7. Review **Force charge at negative price**. It is seeded **On** once on fresh installs and upgrades and only applies while **Enable HBC** is On. A later manual Off choice survives normal restarts/reloads; **Restore defaults** turns it On again.
8. Generate a support report to confirm the installation is healthy.
