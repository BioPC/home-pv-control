# Changelog

## v1.4.0

### Major changes

- **HBC Charge Priority** replaces Hidden PV Reveal with bounded, measured battery-aware PV release.
- Negative all-in prices always lock PV to configured inverter minimums; optional HBC charging remains permission-gated.
- Runtime validation, command locking, persistence, reporting and Daily Control Accuracy were hardened for asynchronous Home Assistant/Node-RED telemetry.
- First-install onboarding now completes only after required live inputs and the complete control configuration are valid.

### Safety and recovery

- Report file-write or atomic-publication failures now invalidate cached storage readiness, allowing the same bounded recovery path to detect a Home Assistant configuration mount that disappears after startup and returns later.

- Runtime evaluation now runs every **10 seconds**.
- Shipped cooldown is **30 seconds**, configurable from **10–60 seconds** in 5-second steps.
- Shipped Target Export is now **0 W**.
- Export Start, Target Export and Import Restore are validated as an ordered set before control writes.
- Added stricter validation for required sensors, helper ranges, duplicate entities and inverter configuration.
- If any configured inverter limit becomes invalid or unavailable, HPVC pauses control for the complete inverter group.
- Night Restore now tolerates expected overnight PV/inverter-limit disappearance while keeping grid and price safety checks active.
- `unknown` or `unavailable` PV telemetry can no longer be mistaken for measured zero production.
- Night Restore restores limits once, suspends normal PV calculations, and resumes only after usable PV has recovered for the required hysteresis period.
- Battery freshness now combines SOC, AC-power telemetry and cutoff-aware idle behavior.
- Invalid live charging/discharging cutoff values are treated as configuration faults instead of being silently replaced.
- Stable full batteries can remain safely classified as full even when their SOC value itself has not changed for a long period, provided current telemetry still confirms the battery is reporting.
- HBC-dependent Charge Priority suspends on uncertain battery telemetry while standalone PV control continues where safe.
- Recovery messages and state transitions were cleaned up to avoid false startup/redeploy recovery events.
- Required live-input loss pauses Node-RED control immediately. A **90-second restoration grace** only delays hard `Inputs unavailable` escalation; the supplied Home Assistant package separately auto-disables HPVC immediately and re-enables it only after required inputs have remained healthy for 5 seconds.
- Scoped runtime Function-error handlers now release only the evaluation lock owned by the failed cycle, preventing a caught exception from suppressing a later valid cycle.
- Report-storage initialization now has bounded automatic recovery after transient startup/filesystem failures, with a 30-second recovery check and a throttled retry request from Generate report.

### HBC Charge Priority

- Replaced Hidden PV Reveal with bounded **HBC Charge Priority** for HBC `Charge` and `Charge PV` execution.
- Added **Force charge at negative price**, seeded **On** once for fresh installs and upgrades; later manual Off choices survive normal restarts/reloads, while **Restore defaults** turns it On again.
- Made **Enable HBC** the master permission for all HPVC writes to HBC.
- At a valid all-in price `<= 0`, HPVC always locks PV to the configured inverter minimums.
- HBC grid charging is forced only when both HBC permissions are enabled.
- Negative-price override state is persisted across restart/deploy and restores the previous HBC strategy and charge goal before normal control resumes.
- If HBC permission is removed during an active negative-price override, HPVC allows only the confirmed restore sequence and then returns to PV-only protection.
- Added retry, timeout, drift-detection and recovery handling for the negative-price override.
- Standalone installations without HBC now use PV-only negative-price protection without creating an HBC restore lock.
- HBC 4.15.0 support is aligned to **1–6 batteries** with RS485 eligibility and prioritized battery order.
- Charge Priority now uses **Off / Requested / Waiting / Active** states instead of assuming a selected HBC strategy means the batteries are charging.
- Added measured charging confirmation, multi-battery headroom, taper handling and persistent-export fallback.
- Improved high-SOC taper learning with bounded probes, learned ceilings, lockout/recovery handling and contamination backoff.
- Uncertain or ineligible batteries are excluded from Charge Priority without stopping normal PV control.
- Added a bounded **15-second HBC transition-settle window** when confirmed battery charging drops into Waiting, preventing HPVC from reacting to the full transient grid excursion while the independent battery controller is still changing state.
- Large Charge Priority releases are plant-relative and staged; small corrections stay fast, while the first large reversal after a recent opposite HPVC command is capped more conservatively.

### PV control and allocation

- Improved multi-inverter target distribution while preserving each inverter's configured minimum and maximum.
- Normal export limiting, import recovery, cooldown and deadband behavior remain separate from the negative-price minimum lock.
- Normal curtailed-PV corrections now use the current commanded inverter-limit total plus grid error, reducing fast export/import reversals caused by lagging PV telemetry.
- Suppressed identical inverter write retriggers and duplicate activity snapshots during rapid repeated evaluations.
- Improved restore behavior and handling of unavailable or malformed inverter limits so HPVC never controls only part of a configured plant.
- Normal PV correction, restore and HBC Charge Priority now share one in-flight inverter-command lock, preventing overlapping targets while a previous write is still propagating.
- Inverter write verification is progress-aware and hardware-agnostic: delayed confirmations retain command identity through a bounded extended verification horizon instead of being prematurely classified as external/manual movement.
- Large inverter-limit commands require live-limit confirmation, correct PV response direction and two fresh, reasonably stable PV observations before a meaningful reversal is permitted.
- Added plant-size-relative damping for large normal PV corrections and first-reversal damping after a recent large opposite command; ordinary small corrections retain the normal evaluation cadence.

### Reports and Today’s Insights

- Reworked **Daily Control Accuracy** with continuity-aware, direction-aware target tracking.
- Added the four user-facing loss factors: **Control response, House load changes, PV availability, Other**.
- Factor values now represent estimated percentage contributions to headline accuracy loss and reconcile to `100 − Daily Control Accuracy`.
- Added physical-event reconciliation so delayed PV, battery and inverter-limit telemetry can still be associated with the grid event that caused the loss without delaying control.
- Hardened attribution against stale events, manual inverter-limit changes, superseded commands, unrelated later actions, day rollover and restart/deploy boundaries.
- Added degraded attribution behavior for uncertain battery telemetry instead of inventing house-load movement.
- Added clearer support-report diagnostics for target baseline, continuity, settle state and raw attribution details.
- Fixed battery causal ordering in physical-event attribution: battery movement already visible at the grid trigger may explain that trigger, while a battery response that occurs during the later reconciliation window can no longer retroactively turn an appliance/load spike into **Other**.
- Fixed post-trigger PV command causality during physical-event reconciliation: PV movement caused by an HPVC command issued after a grid trigger is now removed from that older trigger before House-load/PV-availability attribution, while genuinely uncommanded delayed PV movement can still explain cloud/irradiance events.
- Physical-event reconciliation uses an adaptive **20–30 second** window for asynchronous telemetry while control itself continues at the normal cadence.
- Delayed/superseded HPVC inverter commands retain their causal identity so observed progress remains attributed to **Control response** rather than leaking into external/manual **Other**.
- Added data-quality confidence based on eligible sample count and continuity-gap burden, plus report diagnostics for House inference, independent battery → Other, uncommanded PV → PV availability and command-response causality.
- The **Settings** tab is now always visible; the Main-dashboard Settings toggle and obsolete `input_boolean.hpvc_config` helper were removed.
- Expanded HTML/TXT support reports with HBC Charge Priority, battery eligibility/taper, negative-price override, inverter, sensor-health and accuracy diagnostics.
- HTML and TXT reports are generated from one shared fresh snapshot.
- Hardened HTML/TXT parity checks so non-structural warnings no longer block **View report** after successful publication.
- Added generation-safe atomic report publication so an older timed-out render cannot overwrite a newer report.
- Report timestamps and current-day selection now follow Home Assistant's configured time zone.
- Today’s Insights now reports clearer control blocks, HBC-only pauses, negative-price override faults and recovery states.
- HBC-only battery telemetry pauses no longer appear as full HPVC faults when normal PV control continues.
- Power Control history now distinguishes PV restore actions from ordinary upward adjustments.
- Increased current-day Power Control retention to cover a full day at the 10-second evaluation cadence.
- Normalized activity rows so full-output states cannot remain incorrectly classified as Charge Priority + PV Limited.
- Improved midnight/day-boundary handling and persistence consistency.
- Power Control statistics are derived from explicit HPVC command events rather than delayed live-limit timing, including Charge Priority increases, reductions, restores and ordinary upward adjustments.
- Oscillation diagnostics monitor repeated large HPVC command-direction reversals and include HBC/battery transitions when they participate in the coupled loop.

### Dashboard

- Added **Force charge at negative price** under **Optional HBC Setup** with concise explanatory text.
- HBC-only dashboard content is hidden when HBC is unavailable.
- Removed the dashboard `card-mod` dependency; ApexCharts remains required for the supplied graphs.
- Kept the main Daily Control Accuracy card compact while moving detailed engineering metrics to the support report.
- Improved mobile report controls, report icons and dashboard visibility behavior.
- The **At minimum PV** helper now uses the same fixed **1 W** minimum-state tolerance as runtime control instead of the user PV-adjustment deadband.
- The **HBC Price Intervals** graph now also requires `binary_sensor.hpvc_hbc_available`, preventing the card from referencing HBC-only data when HBC is unavailable.

### Bug fixes

- Fixed first-install onboarding so recommended defaults initialize reliably, completion waits for all required live inputs, and setup progress reflects full control-setting validity.
- First-install progress now requires configured core entities to exist, be available and have valid live states before onboarding completes.
- Inverter setup validation is included in onboarding.
- Resetting onboarding on an already-valid installation triggers a fresh validation and then completes automatically.
- First-install graphs remain hidden until onboarding is complete.
- Restore Defaults preserves configured entity selections/inverter count while restoring HPVC control settings to shipped values.
- User-configurable helpers are no longer forced back to YAML `initial:` values on restart/reload.
- Fixed runtime-lock recovery after scoped Function exceptions with cycle-aware ownership checks.
- Fixed report-storage recovery so a transient unavailable/unwritable Home Assistant config mount no longer requires a redeploy/restart after the mount becomes healthy.

### Architecture and packaging

- Unified Insights, Power Control, Daily Control Accuracy and negative-price override state in `hpvc-data/runtime-history.json`.
- Added current-day restore, midnight rollover, clean-install initialization and legacy migration handling.
- Serialized journal writes and added write-ID guards so stale completions cannot acknowledge or overwrite newer state.
- Runtime waits for journal restoration before dependent actions continue, avoiding startup races.
- Reorganized Node-RED into four functional tabs and corrected cross-tab states that require shared global context.
- Added scoped runtime Function error handling and removed obsolete/dead internal processing.
- Reduced unnecessary report/runtime message payloads after the canonical report model is assembled.
- Removed remaining declaration-only Function-node helpers/locals found by the final release audit; this cleanup does not change control behavior.
- Removed the write-only `homePvControlDirectionHistory` flow-context reset after confirming no packaged runtime path reads that key.

### Documentation

- Corrected Night Restore wording so the dashboard and installation guide match the runtime: valid low PV is authoritative, while `sun.sun` only corroborates a pending transition if PV telemetry disappears mid-timer.
- Removed stale dashboard/report screenshots and regenerated the Node-RED architecture overview from the final v1.4.0 flow.

- Corrected README and installation wording to match automatic first-install HPVC enable behavior after validation succeeds.
- Documented bounded report-storage retry/recovery behavior.
- Removed the unused stale Main-dashboard screenshot that still showed the retired Settings button.
- Reorganized v1.4.0 release documentation from major/safety changes through control, reports, dashboard, bug fixes, architecture/packaging, documentation and upgrade notes.

### Upgrade instructions

- Replace the Home Assistant package, complete Node-RED flow and dashboard together.
- **Force charge at negative price** is seeded **On** once after install/upgrade. It remains user-configurable, survives normal restarts/reloads after a manual Off choice, is reset to On by **Restore defaults**, and only has effect while **Enable HBC** is On.
- Keep all HPVC files on the same release version.

## v1.3.0

### Control and reliability

- Renamed helpers to the `hpvc_*` namespace and improved migration/onboarding handling.
- Added stronger configuration validation, startup safety and sensor-health diagnostics.
- Improved cooldown, import recovery and multi-inverter behavior.

### HBC and batteries

- Expanded optional HBC integration and multi-battery awareness.
- Improved charge-headroom handling and battery telemetry diagnostics.
- Continued development of automatic Hidden PV Reveal before its replacement in v1.4.0.

### Dashboard and reports

- Added onboarding guidance, richer diagnostics, report improvements and dashboard cleanup.

## v1.2.0

- Added automatic Adaptive Hidden PV Reveal with bounded reveal behavior and PV-response verification.
- Improved first-run defaults, helper persistence, restore behavior and dashboard diagnostics.
- Improved multi-inverter reveal allocation and battery-aware reveal limits.

## v1.1.1

- Maintenance release with configuration-validation, persistence and dashboard fixes.
- Improved entity-picker handling and HBC strategy change detection.

## v1.1.0

- Added Hidden PV Reveal for grid-following batteries.
- Improved cooldown recovery, HBC strategy selection, battery charge awareness and dashboard diagnostics.
- Expanded Insights and HBC price-zone visualization.

## v1.0.6

- Improved default persistence, startup restore handling and internal cleanup.

## v1.0.5

- Fixed negative-price minimum-PV behavior, configuration validation and diagnostics.
- Completed the Home PV Control naming/dashboard cleanup.

## v1.0.4

- Fixed clean-install template and dashboard entity mismatches.

## v1.0.3

- Rebranded the project as **Home PV Control** and improved HBC/dashboard integration.

## v1.0.2

- UI, dashboard and stability improvements.

## v1.0.1

- Added configurable cooldown, faster evaluation and HBC battery-power support.

## v1.0.0

- Initial public release.
