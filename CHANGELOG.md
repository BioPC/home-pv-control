# Changelog

## v1.5.0

### Added / changed

- Watt-mode targets now honor Number-entity and Action/service command steps before change detection.
- Clarified readback-unit and pre/post action sequencing requirements.
- Added per-inverter **Control method: Number entity / Action/service**.
- Added optional per-inverter readback entities for physical write verification.
- Preserved existing Watt/Percent conversion, proportional allocation, cooldown and safety logic.
- Existing number-entity installations remain the default and require no adapter conversion.
- Added generic Action/service adapter fields with fixed JSON data, dynamic target injection, optional target JSON, Watt/Percent command-step quantization, refresh/heartbeat interval, and sequential stop-on-failure pre/post action sequences.
- Added adapter failure recovery so failed service calls invalidate cached command state and can retry safely.
- Adapter configuration changes invalidate cached command state and force a synchronization write.
- Added unit-aware Action Step validation: Percent steps above `100` and Watt steps above inverter Maximum power fail configuration validation. The helper range is `0–10000` so Watt-mode steps can cover the supported inverter-power range.

### Fixed

- Fixed Home Assistant configuration/readiness validation so **Action/service** inverter slots are validated by their adapter settings instead of being incorrectly rejected for not using a writable `number.*` entity.
- Fixed dashboard onboarding/unavailable diagnostics to use the selected inverter control method and optional Action/service readback instead of assuming every slot uses a Number entity.
- Fixed `HPVC PV Limited` and `HPVC At Minimum PV` compatibility indicators for Percent-mode adapters by normalizing limits back to watts; Action/service adapters without readback now use bounded runtime command diagnostics where physical state is unavailable.
- Expanded the fresh report-state snapshot with v1.5.0 adapter configuration/readback fields so reports remain correct before runtime inverter diagnostics have been populated.
- Repaired stale Node-RED group membership metadata for four v1.5.0 adapter/configuration nodes. This does not change runtime control behavior but keeps the imported flow structurally consistent in the editor.
- Fixed HTML/TXT report parity for v1.5.0 inverter rows so the checker expects the rendered Control method and Limit unit fields instead of reporting a false mismatch for every inverter.
- Action/service adapters with an empty command cache no longer force every 10-second timer wake; initial synchronization occurs on the next normal/full evaluation and remains bounded by the mandatory 30-second full evaluation.
- Fixed stable-input rate limiting after successful inverter writes: a completed `homePvControlPendingWriteVerification` record (`checked: true`) is retained for diagnostics but no longer counts as pending runtime work, so stable-cycle skipping can resume immediately after verification.
- Fixed Action/service startup rate limiting so an empty command cache no longer forces every 10-second wake; the next mandatory/full evaluation performs the initial synchronization and retries remain bounded by the 30-second full-evaluation interval.
- Adapter action failures are now included in HTML/TXT support reports with timestamp, slot, phase, action and error detail.
- Removed unused runtime bookkeeping keys and local variables that had no readers, reducing dead state without changing control behavior.
- Improved stable-input rate limiting so normal Marstek battery AC-power jitter no longer forces a full HPVC evaluation on every 10-second wake; battery power now uses the same cumulative 20 W + 2% significance test as grid/PV power.
- Battery SOC is normalized to whole-percentage changes for rate-limiter hashing, while control-relevant non-power states remain exact-match.
- Confirmed Night Restore is now treated as a stable state instead of automatically bypassing the rate limiter. Full evaluations resume immediately when valid PV rises above the Night Restore recovery threshold or a recovery timer is already active, and a complete evaluation is still forced at least every 30 seconds.
- Daily Control Accuracy command-application checks now resolve pending writes by per-inverter `pvN` control key and compare against Watt-normalized real readback, restoring correct Control attribution for Number-entity and Percent adapters.
- Fixed control-key write-settle confirmation so verified inverter writes can release the pending-write lock without an extra evaluation.
- Updated Daily Control Accuracy physical attribution for Action/service adapters with real readback; command-cache-only adapters remain excluded from physical attribution by design.
- Fixed support-report inverter entity validation so configured readback sensors cannot crash report generation.
- Fixed Settings conditional helper domains for inverter-slot visibility and threshold/range warnings.
- Fixed cross-tab runtime/diagnostic context scope for HBC timing/recovery and rate-limiter diagnostics.
- Fixed inverter diagnostic target lookup so calculated targets, clamping state and requested totals are retained correctly.

### Documentation and compatibility

- Improved the inverter Settings cards for mobile use: each inverter now has its own `PV1`…`PV10` card title, and repeated `PVx` prefixes plus long Action-step/refresh labels were shortened without card-mod or other UI mods.
- Kept Action Step in its logical position with the compact `Action step (0=auto)` label; unit-specific limits remain enforced by backend validation and documented in the configuration guide.
- Added the inverter-compatibility guide and updated its matrix for Number entity and Action/service control paths, including readback/verification semantics.
- Added the inverter compatibility guide to the navigation bar across docs 01–05.
- Completed the installation defaults table with price hysteresis and Night Restore threshold.
- Clarified that Restore defaults preserves all per-inverter adapter/control-path settings.
- Documented the Daily Control Accuracy attribution consequence of Action/service operation without real readback.
- Clarified release history: **v1.4.4 was never released**; development work that had been prepared under that version was folded into v1.5.0.

> **Release history note:** v1.4.4 was never published as a release. The changelog therefore correctly continues from v1.5.0 to v1.4.3.

## v1.4.3

- Finalized percentage-limit quantization before inverter change detection, preventing repeated writes when a percent entity can only represent coarse steps.
- Enforced configured inverter minimum power as a hard Watt floor when percent-step rounding is required.
- Added a per-inverter **Limit unit** (`Watts` / `Percent`) while keeping all HPVC control calculations, Full power and Minimum power in watts.
- Added percentage I/O conversion for live inverter limits, `number.set_value` commands and write verification.
- Updated the existing `sensor.hpvc_pv1_actual_limit` through `sensor.hpvc_pv10_actual_limit` compatibility sensors so they continue to report watts when a percentage limit entity is used.
- Kept existing installations backward-compatible by defaulting every inverter Limit unit to `Watts`.
- Removed HPVC-owned output helpers from the stable-input rate-limiter hash so dashboard publishing cannot retrigger full evaluations.
- Added HPVC-owned last-published caches to deduplicate status, reason, Insights, targets JSON and accuracy diagnostics.
- Throttled changed targets JSON to 30 seconds and changed accuracy diagnostics to 60 seconds, with a five-minute forced dashboard resync.
- Fixed Insight publishing so only changed rows are written instead of resending all 20 helpers after any Insight change.
- Added rate-limiter full/skip diagnostics to support reports.
- Updated installation, configuration, architecture and troubleshooting documentation for v1.4.3.
- Percentage limit writes now respect the writable `number` entity step/resolution and verify against the effective representable Watt target.
- Invalid, missing, unknown or unavailable per-inverter Limit unit values now fail safe as configuration errors instead of silently falling back to Watts.
- Corrected remaining v1.4.2 runtime/dashboard version labels and refreshed v1.4.3 documentation/reference metadata (screenshots intentionally unchanged).


## v1.4.2

### Runtime efficiency

- Added incremental Insights/dashboard rendering so unchanged Insight history is no longer rescanned and regrouped every 10 seconds.
- Kept Power Control history event-based while avoiding unchanged per-cycle history/meta writes.
- Changed activity pruning from every evaluation to a bounded periodic maintenance pass.
- Suppressed selected redundant scalar/context writes where the value has not changed.
- Avoided rewriting the bounded runtime-cadence array when its contents are unchanged.

### Diagnostics

- Added internal measured-stage and unaccounted-cycle timing to help isolate Node-RED scheduling, GC or untimed runtime overhead without expanding the visible support report.

### Compatibility

- No configuration migration is required from v1.4.1.
- Existing control, safety, HBC, inverter, accuracy and reporting behavior is retained.

### Issue #3 / #4 follow-up

- Added conservative HBC-style stable-input rate limiting with a mandatory full evaluation every 30 seconds.
- Fixed the rate-limiter baseline so grid/PV deltas accumulate from the last full HPVC evaluation rather than resetting after every 10-second check; the existing 20 W + 2% thresholds and 10-second trigger are retained.
- Fixed `settingsTrigger` declaration order in `Read HPVC Core Configuration` to prevent `ReferenceError: Cannot access 'settingsTrigger' before initialization`.
- Added high-load cooldown signalling for previous evaluations above 1 second without suppressing safety/control logic.
- Added bounded internal rate-limiter counters (full/skipped cycles) without storing a per-cycle history.
- Fixed a Settings-changed race: configuration changes received while the runtime lock is active are now marked dirty and applied by the next successful evaluation.
- Cached 68 helper/configuration states and rebuild them only on startup or a Settings changed event.
- Reduced the normal 10-second snapshot refresh to 30 live whitelist states plus dynamically resolved entities.
- Expanded Settings changed coverage to all cached configuration helpers.
- Reused the bounded serialized-cycle snapshot object and explicitly drops `msg.hpvc.cycleStates` after diagnostics.
- Added bounded internal retention counters for major HPVC histories to help isolate remaining heap growth.


## v1.4.1

### Performance and memory

- Fixed GitHub issue #2's confirmed allocation hotspot by removing the full Home Assistant state-table deep clone from the 10-second runtime evaluation.
- Removed the equivalent full-state deep clone from support-report generation.
- Replaced runtime `msg.hpvc.haStates` transport with a compact per-cycle `msg.hpvc.cycleStates` snapshot containing only required fixed and resolved dynamic entities.
- Added a legacy-state cleanup guard before output publication.
- Reduced Daily Control Accuracy allocation by replacing an unnecessary JSON deep clone of the last PV command with a small object copy.
- Reduced the activity-history ceiling from 9,000 to 3,000 rows.

### Diagnostics

- Added bounded per-stage evaluation timing and aggregate last/max/average cycle timing.
- Added optional heap telemetry sampled no more than once per minute when `process.memoryUsage()` is available in the Node-RED Function sandbox.
- Performance diagnostics are stored as a single bounded global object and do not create a per-cycle history.
- HTML and TXT support reports now render the v1.4.1 timing and heap diagnostics for issue #2 validation.

### Documentation

- Updated README, installation, architecture/how-it-works, troubleshooting, dashboard version label, release notes, and release archive documentation for v1.4.1.
- Added explicit testing guidance for issue #2.


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

