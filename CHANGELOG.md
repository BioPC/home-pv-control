# Changelog

## v1.6.0 — 2026-10-25

### Limit entity layout

- Display each inverter Limit entity as a native two-line Entities row: `Limit entity` on the first line and the full exact entity ID as secondary information on the second line, with no custom-card dependency.

### Min/Max warning rendering

- Fixed the per-inverter Min/Max warning card to use the same per-slot invalid-range sensor that hides/disables HPVC Control, eliminating separate warning-condition drift for manual, Hoymiles/OpenDTU and Enphase controllers.

### Invalid Min/Max recovery guidance

- Expanded the per-inverter invalid-range warning to explain that HPVC Control was forced OFF and must be manually re-enabled after correcting Min to `<= Max`; no control behavior changed.

### Live Min/Max validation refresh

- Fixed Home Assistant dependency tracking for the centralized inverter Min/Max validator by explicitly subscribing it to all 20 per-slot Max/Min helpers. Editing a limit now immediately refreshes the invalid-range warning and the HPVC-Control force-off/hide guard; this prevents the runtime status from becoming incomplete while the dashboard warning remains stale.

### Inverter Min/Max guard and warning placement

- Show `Min power must be ≤ Max power. Correct it, then re-enable HPVC Control.` directly below the per-inverter status banner when Min exceeds Max for manual, Hoymiles/OpenDTU and auto-detected Enphase slots, including auto controllers whose manual entity helper is blank.
- Use explicit invalid-range gating for all ten inverter slots: **Min power equal to Max power is valid**; if Min exceeds Max, HPVC preserves the entered value, forces that inverter HPVC Control OFF, hides the unavailable control switch, and shows the range warning until the user corrects Min to `<= Max`.

### Dashboard Min/Max validation

- Render the Min/Max warning from the same per-slot invalid-range sensor that gates HPVC Control, so `Min power must be ≤ Max power. Correct it, then re-enable HPVC Control.` appears consistently for manual, OpenDTU/Hoymiles, and Enphase controllers whenever Min exceeds Max.

### Maintenance verification parity

- Retire auto-controller `homePvControlAdapterCompletedWrites` barriers immediately after the authoritative pending-write verifier confirms the physical write. Destructive maintenance now treats a resolved auto-detected Number write the same way the proven v1.5.7 manual Number path did, instead of re-checking a historical adapter-completion record and misclassifying healthy full-output Hoymiles/Enphase controllers as unavailable/unverifiable.


### Release priorities

This release prioritizes control correctness and safe recovery first, followed by inverter action sequencing, controller management, automatic integration support, maintenance recovery and validation.

### Control and safety
- Auto-detected native Number controllers (OpenDTU/Hoymiles and Enphase DPEL) now use the same Home Assistant template `last_reported` freshness contract as manual Number controllers during restore/maintenance verification. Auto-detected slots are mirrored into the normal `pvN` helpers, so `sensor.hpvc_source_freshness` resolves the real controller entity and reads HA-core `last_reported` directly. This fixes false `unavailable/unverifiable` results seen only with auto-detected controllers while preserving stale-readback protection.
- Prevent disable, Smart Update, flow removal and full uninstall from stalling when a Number-entity inverter was already independently confirmed at its trusted full output before a redundant restore-to-full write. HPVC now carries that pre-write full-output proof through the adapter completion record, so an unchanged OpenDTU value does not create a false verification barrier; genuinely stale full readback after a real limiting write remains blocked.
- Restore writes are now eligible for confirmation after 5 seconds when the live verified readback already matches the requested full limit; normal limiting writes retain the configured cooldown-based initial verification delay and slow OpenDTU writes keep their extended retry/failure windows.
- Align the **Smart Update**, **Remove HPVC flows** and **Full Uninstall** safe-shutdown gates: a merely active disable-restore lifecycle no longer blocks maintenance after every currently configured inverter is independently verified at full output and no inverter action/write remains pending. Unresolved obligations with unavailable, below-full or zero-current-controller evidence still block destructive maintenance.

- Release HPVC-owned auto-managed Enphase DPEL and Hoymiles/OpenDTU slots when registry discovery no longer finds the controller, instead of reclassifying stale mirrored values as manual `Incomplete` slots. Genuine manual inverter slots remain persistent.
- Fix independent maintenance-audit findings: Smart Update, flow removal and uninstall now consume the dedicated OpenDTU registry `.controllers` shape, normalize legacy/manual Enphase DPEL slots to native Watt metadata before full-output proof, and keep unresolved disable-restore obligations blocking even if rediscovery temporarily yields zero controllers.
- Correlate OpenDTU API write evidence to the physical adapter dispatch: limit-status polls are timestamped at request start, pending writes are stamped with their actual dispatch generation/time, and API `Ok` evidence is accepted only when that poll began after the relevant dispatch. Pre-command snapshots can no longer confirm later writes.
- Fix the final v1.6.0 release-audit controller boundary findings: use one configuration-only adapter policy across producer/dispatch/recovery, keep DPEL permission checks live at dispatch without signing mutable limit telemetry, honor configured per-slot power settings for newly auto-detected controllers, stamp real pending records by logical control key plus readback identity, and reject contradictory known OpenDTU serials.
- Require fresh PV evidence before Night Restore entry/recovery; retained stale zero values cannot authorize full output, while disappearance after a fresh night start keeps the existing bounded below-horizon policy.
- Use at least the current controllable output ceiling for import recovery so low measured PV cannot reduce the limit during an upward recalculation.
- Preserve write authorization through quantization; cooldown and pending-write holds also gate initial synchronization and heartbeat refreshes, while explicit minimum protection and authorized recovery rebalance remain available.
- Retain configured manual-disable restore obligations through unavailable telemetry and report verification pending until independent full-output confirmation; configuration changes and command-cache values cannot fabricate completion.
- Block Smart Update, flow removal and uninstall while registered, queued, in-flight or uncertain dispatcher work remains; neither Night Restore proof nor verification age exempts outstanding physical work. Reject full readback predating the relevant completed inverter call.

### Inverter action sequencing

- Serialize inverter service calls, replace superseded unsent steps, and drain an already-sent action before sending the newer target.
- Guard continuations and failures with generation/dispatch identities so delayed or duplicate callbacks cannot overwrite or erase newer work; preserve unrelated-inverter failure isolation.
- Cancel old continuations on live control-ownership/adapter changes and request fresh target reconciliation after cancellation or deployment. A service call that never returns remains held for investigation rather than permitting unsafe overlap.
- Coalesce identical pending sequences without restarting their generation or verification clock, preventing slow pre-actions from starving restores. Replay interrupted pre-dispatch delivery with the original identity.
- Preserve a live call barrier across warm partial Function deployment. Surface uncertain persisted/legacy leases as recovery-required and require explicit reconciliation rather than silently clearing them.

### Controller UI and per-controller permission

- Centralized all ten inverter Min/Max classifications (`valid`, `min_equal_max`, `min_above_max`) in `sensor.hpvc_inverter_limit_validation`. Equality is valid; only `min_above_max` is invalid. Dashboard warnings and the automatic HPVC-Control-off guard consume that shared result, and HPVC never rewrites the user's Min helper.
- Live Inputs now keeps switched-off inverter limits visible with the native label `PVx actual limit (Off)`; enabled rows retain `PVx actual limit`, while `unknown`/`unavailable` control-switch states remain hidden. No new entities or custom dashboard dependencies are required.
- The Settings dashboard now uses one persistent native **Inverters** numeric-input row for both zero and non-zero counts; the separate zero-state add card was removed, while PV configuration remains hidden until at least one effective inverter exists.
- Dashboard polish: auto-detected read-only inverter fields now use muted grey lock icons, and trusted OpenDTU Max power remains locked across independent registry refreshes instead of transiently reverting to a manual input.
- Dashboard terminology now uses **Total inverters** and **Inverter status** for clearer user-facing labels; internal controller IDs and runtime semantics are unchanged.
- Dashboard inverter status now identifies auto-detected integrations as **Hoymiles detected** or **Enphase detected**, while internal status semantics remain unchanged.
- Dashboard incomplete status now preserves detection context: manual controllers show **Detected but incomplete**, auto OpenDTU/Hoymiles shows **Hoymiles detected but incomplete**, and auto Enphase shows **Enphase detected but incomplete**. Internal runtime status remains `Incomplete`.
- Fixed a dashboard card regression that rendered a false `Configuration error` above valid auto-detected controllers; removed the redundant `Controller configuration` heading while keeping the existing HPVC Control and controller fields.
- Bound the visible **Inverters** control to a dynamic minimum equal to the current auto-detected controller count, so detected controllers cannot be hidden by decrementing below the live automatic floor.
- Allow a genuine zero-inverter setup state. With no manual capacity and no auto-detected controller, **Inverters** is `0`, the empty PV configuration area is hidden, and Settings shows only the add-inverter control. Zero is accepted by the runtime as a setup value but is not operational: HPVC requires at least one usable inverter and remains OFF. Existing legacy empty PV1 placeholders collapse to zero at Home Assistant startup.
- Add a dedicated Main-tab warning for the supported zero-inverter setup state: **No PV inverters available**. With no usable inverter, HPVC control is unavailable and the existing required-input safety path keeps the master control OFF; monitoring/dashboard diagnostics remain available until a manual inverter is added or Enphase/OpenDTU discovery supplies one. Existing configuration/live-input alerts retain priority for real faults.
- Auto-detected controller values are mirrored into the existing PV slot fields for a consistent configuration view. Control method, limit entity and unit are mirrored for all auto controllers; Hoymiles/OpenDTU may also mirror trusted Max power, while Enphase Max/Min remain user-owned manual values. The runtime source remains auto-detected so this mirroring does not create duplicate manual controllers.
- Auto-detected Enphase/OpenDTU Control method, Limit entity and Limit unit rows are read-only; Max power is locked only when a trusted detected maximum is available, while Min power stays editable and Max power remains editable when HPVC needs a manual rated value.
- Hide duplicate and incomplete controller readbacks from Live Inputs while retaining valid monitoring-only and unavailable-controller rows.
- Show duplicate Number-entity assignment feedback only on later-entered slots, identify the original slot and hide conflicting toggles; preserve the runtime duplicate-target safety gate.
- Evaluate manual power-range warnings directly from entered controller fields; keep empty/not-configured slots quiet and preserve native adapter limits.
- Show counted but unfilled manual slots as amber **Not configured**, derive Detected/Configured/Incomplete/Unavailable from existing runtime data, and add no extra status entities/helpers.
- Show a brand-neutral auto-detected/manual inverter total and include effective auto-detected slots in navigation, Main badges and actual-limit rows.
- Add transition-only Insights for controller exclusion, all-controller monitoring-only mode and return to control.

### OpenDTU/Hoymiles registry auto-detection

- Hardened OpenDTU/Hoymiles auto-control: prefer `/api/limit/status` `max_power`, cache confirmed rated power, require the slot's manual Full Limit when API/cache data is unavailable, never infer rated power from HA Number `max`, use `limit_set_status` as optional early verification evidence, and enforce a 300-second minimum final verification window for slow absolute-limit readback.
- Keep the OpenDTU limit-status HTTP Request node as the sole owner of the GET method; dynamic polling now supplies only `msg.url` and HPVC metadata, avoiding Node-RED override warnings on current runtimes.
- Added automatic Hoymiles/OpenDTU controller discovery through the existing independent registry refresh. HPVC now reads both Home Assistant entity and device registries, identifies MQTT `limit_nonpersistent_absolute` roles on OpenDTU/Hoymiles devices, and uses the writable Watt number as a normal verified Number-entity controller.
- Registry/device pairing supports renamed Home Assistant entities. When registry metadata is unavailable, a strict `_limit_nonpersistent_absolute` + Watt-unit + positive-native-max fallback remains available.
- Persistent/relative limits, unrelated MQTT numbers and inverter power controls are rejected for automatic control. Multiple OpenDTU devices, mixed Enphase/manual setups, deduplication, per-controller HPVC Control, maintenance verification and the shared ten-slot ceiling are covered by regression tests.
- Align Smart Update, flow removal and full-uninstall OpenDTU verification with runtime rated-power precedence (API `max_power` → cached confirmed value → manual Full Limit); maintenance no longer substitutes the HA Number `max`.

### Enphase DPEL integration

- DPEL discovery now prefers original entity registry roles and shared HA device IDs, supports fully renamed triplets, rejects production/PV-limit siblings and ambiguous pairings, and keeps suffix fallback without registry metadata.
- Registry reads run on a separate startup/60-second timer. Runtime, HA validation/dashboard templates and maintenance use the same cached mapping; multiple Envoys and the ten-slot maximum remain supported.
- Added persistent per-slot HPVC Control switches, enabled by default. Opt-out stops further commands without changing the last limit; maintenance still requires verified full output. See the configuration guide for restoration and slot assignment details.
- Added shipped-function registry, rename, ambiguity, cache, slot, opt-out and queued-action regressions, plus rendered HA template tests and CI coverage. Version remains v1.6.0.
- Added native Enphase Envoy DPEL auto-detection for Enphase Envoy Installer 0.10.2+ with one Envoy counted as one effective HPVC controller slot.
- Preserve user-owned Enphase Max/Min across temporary auto-detection loss by binding the saved range to the detected DPEL controller identity; the same Envoy regains its range after rediscovery, while a different Envoy cannot inherit the previous controller's values.
- Normalize manually configured DPEL Number-entity slots to native Watts/step/readback while preserving manual HPVC Max/Min power, and require an explicit `Production` + `Export` mode set.
- Make Home Assistant configuration/readiness/onboarding accept a complete auto-detected DPEL triplet without any manually populated inverter entity helper.
- Added an effective runtime inverter map so dashboard actual-limit sensors, slot visibility, inverter navigation, maintenance diagnostics, PV-limited and at-minimum indicators include auto-detected Enphase controllers.
- Capture the Node-RED adapter policy only after DPEL discovery to avoid a safe but unnecessary first-discovery resync cycle.
- Harden DPEL runtime validation: the mode select must continue to advertise both `Production` and `Export`, and `unknown`/`unavailable` enable or mode states now pause the Enphase adapter without issuing futile service calls until Home Assistant reports real states again.
- Fixed Home Assistant runtime-map consumers to accept both JSON strings and native list attributes, preventing `PVx actual limit` sensors from becoming `Unavailable` on installations where HA preserves the attribute as a native list.

### Smart Update activation recovery

- Retain the v1.5.6 activation recovery protections and update all current runtime/package/report markers and managed-version checks to v1.6.0.
- Preserve historical release documents, stable node IDs and existing Home Assistant helper inventory.

### Validation

- Add a dedicated HBC Charge Priority state-machine regression suite covering Waiting, Active, Exit hold/transition settle, taper-region step caps, persistent-export fallback, and negative-price separation.
- Add a fixture-driven report regression that builds the shared report model, renders TXT and HTML, verifies parity, exercises generation-token guards, and validates the generation-scoped atomic publication contract.
- Move auto-detected-controller documentation out of post-footer text and into the existing controller/adapter sections so the configuration and architecture guides remain structurally clean.
- Add behavioral control-safety regressions for all five audit findings, delayed actions, stale errors, multi-inverter outages, freshness boundaries and deployment.
- Add twelve dispatcher lifecycle regressions covering the three follow-up findings, maintenance completion, multi-inverter coalescing, replay and cold recovery.
- Add twelve baseline control simulations to GitHub Actions alongside the existing activation, Insights and runtime-load suites.
- Replace the Enphase Home Assistant string-presence check with rendered Jinja scenarios covering Enphase-only onboarding, strict DPEL option validation, native-list/JSON runtime attributes, manual Number Watts/Percent, Action/service readback, manual-DPEL deduplication/Watts normalization, mixed controllers and multiple Envoys.
- Pin Jinja2 in CI for rendered-template regression coverage, use explicit UTF-8 reads in Python scripts, and validate the new CI entries and current-version markers.
- Reorganize Enphase documentation into the existing Installation, Configuration, How it works, Troubleshooting and Compatibility sections; remove duplicated end-of-file callouts and update Live Inputs/navigation wording to the effective runtime slot model.

## v1.5.6 — 2026-10-14

### Smart Update activation recovery

- Fixed a v1.5.5 recovery deadlock where a completed transaction could remain stuck on **Update activation pending** when Home Assistant restored `hpvc_update_reload_required` or `hpvc_update_in_progress` stale, or Node-RED retained its local update latch.
- Finalized transactions now rerun the existing idempotent activation finalizer only when stale activation/update state still needs reconciliation; durable finalization is sufficient even when transient readiness metadata or the redundant activation-complete flag is missing.
- Durable transaction state is authoritative for recovery classification; a stale HA `hpvc_update_in_progress` helper no longer blocks a safe finalized-state repair.
- Successful activation finalization now explicitly clears and verifies both HA update booleans and clears the Node-RED-local update latch, timestamps, recovery-probe marker and phase.
- A reconciliation attempt that starts from an already-finalized transaction keeps new HA publication/verification failures retryable instead of misclassifying them as stale success.
- The `awaiting_quick_reload` user boundary and protection for genuine incomplete/live transactions remain unchanged.
- Added conservative orphan reconciliation for the remaining `transaction.json`-missing case: v1.5.6 clears stale update gates only when no local destructive/update phase is active, no updater/reclaim/fresh activation lock exists, and the managed package independently verifies as v1.5.6. The runtime gate is cleared last and HA state is re-verified.

### Validation

- Added regression coverage for stale reload-required, stale HA update-in-progress and stale Node-RED update-latch states after durable finalization.
- Added negative coverage proving unfinished transactions cannot be reconciled as finalized.
- Added regression coverage for missing-transaction orphan cleanup, including active-update-phase, transaction-present, updater-lock, wrong-package and Home Assistant service-failure refusal cases.
- Release validation now enforces finalized-state repair and Node-RED-local latch cleanup.

## v1.5.5 — 2026-10-11

### Smart Update readiness

- Terminal pre-install/no-change recovery no longer depends on Node-RED Admin API discovery: failed HA publication remains retryable, preserves the saved master state, and never arms activation when nothing was installed.
- Night Restore Maintenance proof now clears on any independently verified partial inverter even during degraded multi-inverter telemetry, and can be re-minted only after every configured inverter is confirmed full again.
- Night Restore proof signatures now cover the complete effective Action/service adapter configuration, including payload, target, value field, pre/post actions, steps and limits.
- Smart Update now treats `Update not started` as a terminal reconciled state, so fixing a preflight prerequisite allows the next click to start a fresh ordinary update instead of looping in recovery-only mode.
- Final GitHub-readiness cleanup fixes Troubleshooting section placement, removes stale template-domain wording, and adds repository/workflow/link validation.
- Tightened Night Restore Maintenance proof: Action/service inverters now require fresh numeric readback; command-cache and startup-full assumptions can no longer authorize Smart Update, flow removal, or uninstall.
- Night Restore now retains current-configuration full-output proof for Maintenance, so Smart Update, Remove HPVC flows, and Full Uninstall can proceed after an already-restored inverter goes to sleep; fresh partial limits, configuration changes, or Night Restore ending invalidate the proof.
- Pre-install prerequisite/API failures now use an explicit no-change recovery path: no activation gate is armed when nothing was installed, saved master intent is preserved, and launched/prepared no-change recovery does not depend on the Node-RED Admin API.
- Smart Update activation inventory now discovers HPVC template platforms generically through explicit `default_entity_id` values instead of hard-coding only sensor/binary-sensor domains.
- GitHub release checks now have bounded request/response/overall deadlines plus a matching Exec timeout.
- Activation completion is now durable, serialized, and retryable: restart recovery uses transaction metadata instead of status prose, an exclusive transaction-bound activation lease prevents overlapping Quick Reload/recovery attempts, abandoned `checking` attempts are recoverable after the lease becomes stale, readiness metadata survives until final helper reconciliation, and stale results cannot undo a newer completed activation.
- Activation lease acquisition is race-hardened: a lock directory is claimed atomically, a just-created/unreadable owner record is treated as busy until filesystem age proves staleness, stale-lock reclamation is quarantined, heartbeat renewal verifies ownership, and delayed failure output is side-effect free so an older attempt cannot re-arm a transaction finalized by a newer attempt.
- Pending update activation now acts as an explicit runtime control gate. The saved master enable state can be restored while the gate remains on, but normal PV/HBC control resumes only after preparation is acknowledged and final activation cleanup is reconciled.
- Smart Update now derives newly introduced activation entities automatically from the installed/staged `hpvc_config.yaml` inventories. All newly introduced HPVC package entities are checked for existence only; runtime `unknown`/`unavailable` states do not block activation. HPVC template entities use explicit `default_entity_id` values so discovery never guesses from `unique_id`. Quick Reload polls Home Assistant with one states API request per cycle for up to 20 seconds, verifies readiness metadata against the completed update transaction, and restores the persisted pre-update enabled/disabled intent only after readiness succeeds. If readiness is not confirmed, HPVC remains disabled and requests a full Home Assistant restart; the same transaction-bound check runs again after restart. The normal and recovery launchers now embed the same updater implementation, and verified rollback removes stale readiness metadata. No new HA helper is required.
- External Release heartbeat/lease writes are suppressed while update activation is pending or while their helper entities are unavailable, preventing the missing-entity error flood reported in issue #8.
- Added GitHub Actions release validation (`.github/workflows/validate-release.yml`) with `scripts/validate_release.py` and behavioral `scripts/test_activation_recovery.py` coverage for release/version consistency, strict YAML/Node-RED structure, deterministic template entity IDs, updater/recovery parity, activation interruption/concurrency, uninstall ownership, degraded-inverter policy, desktop Maintenance alignment, Function/embedded Node.js syntax, and Exec shell syntax.
- Hardened release validation so template ownership discovery is generic across every HPVC template domain and both shipped YAML files are parsed with duplicate-key rejection; future template platforms therefore cannot bypass uninstall parity merely by using a new domain.
- Fixed the desktop Maintenance layout so **Check for updates**, **Remove HPVC flows**, and **Uninstall HPVC** share one explicit three-column action row with single-row tiles, preventing the manual/uninstall buttons from stretching to double height when the Updates column has additional actions. The release validator now enforces this structure.

### Issue #9 — shared Node-RED runtime load

- Active price-zone limiting now always bypasses the stable-input limiter, preserving the full 10-second control cadence while idle/unrestricted operation can skip heavier evaluations.
- Kept the PV-control wake interval at **10 seconds**; active PV limiting is not slowed.
- Retained the HBC-inspired stable-input fast path so unchanged cycles exit before the heavier engine/output/diagnostic pipeline.
- Moved periodic runtime-history persistence off the control cadence: the journal now checks/publishes every **60 seconds**, while safety-critical negative-price override changes still trigger immediate persistence.
- Reduced periodic report-storage recovery polling from 30 to **60 seconds**; once storage is ready the path remains a bounded no-op.
- Existing inverter writes remain change-based (plus configured Action/service heartbeat refreshes), avoiding repeated identical commands.
- Together with the v1.5.5 **Enable Insights** switch, optional analytics/report workload can be removed without affecting core PV control or Daily Control Accuracy.

### Fixed

- Full uninstall now explicitly resets **Enable Insights** to its shipped Off default before helper removal, preventing Home Assistant RestoreEntity state from re-enabling optional analytics after a later fresh install.
- Support-report Accuracy now publishes and consumes the headline together with its factor/RMS/sample diagnostics as one coherent snapshot, preventing mixed-age headline/factor combinations.
- Maintenance now warns **Maintenance verification unavailable** before destructive actions when an Action/service inverter lacks a valid numeric readback; normal control can still operate without readback, but automatic maintenance will not claim full-output verification.
- Dashboard numeric `grid_options.columns` values are release-validated against the supported 1–12 range; remaining Maintenance cards now use full-section width 12.
- Full uninstall ownership now includes the maintenance inverter warning and both HPVC-owned automation unique IDs so registry cleanup does not leave those entries behind.
- Added a 60-second automatic fallback for the support-report Ready state. Local report viewing still resets **View report** immediately through the existing `local_only: true` webhook, while trusted remote access paths such as Tailscale now return to **Generate report** without exposing the reset webhook remotely.
- Added a conditional Maintenance warning when one or more configured PV inverters are unavailable or invalid. It explains that Smart Update, Remove HPVC flows, and Uninstall HPVC can wait up to 180 seconds and then cancel safely.
- Fixed degraded multi-inverter validation: slot-local inverter configuration defects no longer globally safety-pause HPVC when at least one inverter remains valid; invalid slots are excluded from allocation while shared/ambiguous plant faults remain blocking.
- Fixed automatic safety-resume status synchronization: `hpvc_enabled` and `hpvc_auto_resume_pending` are now read live every runtime cycle, preventing the dashboard from showing **Disabled** after HPVC has automatically re-enabled.
- Separated configured PV path existence from live PV telemetry readiness.
- A mistyped/non-existent Solar entity now fails readiness even during Night Restore.
- A configuration with no existing inverter control/readback path now fails readiness even during Night Restore.
- Night Restore still tolerates existing-but-unavailable/sleeping PV telemetry, and daytime degraded control still works when at least one inverter path remains usable.
- `unavailable_entities` now exposes non-existent Solar/inverter paths during Night Restore for clearer dashboard diagnostics.

## v1.5.4 — 2026-10-05

v1.5.4 strengthens PV restore verification, per-inverter fault isolation, External Release coordination, telemetry safety, and Smart Update recovery after real-world multi-inverter testing and extensive regression validation.

### Control and safety

- Changed normal full-output restore status from **PV restored** to **Restoring PV** until inverter limits are actually verified.
- Kept **Restoring PV** active across subsequent write-lock verification cycles until the pending restore is confirmed, preventing `PV full / price OK` or `Monitoring low price` from appearing while the plant is still below full.
- Added restore-specific delayed/failure Insights that identify inverter limits not confirmed at full output.
- Automatic safety pauses caused by invalid sensor/configuration state now hold the current inverter limits instead of forcing a full-output restore; healthy manual disable and verified maintenance paths retain their normal full-limit restore behavior.
- Corrected Watt target rounding for inverters whose configured minimum does not align exactly with the configured step size.
- Preserved validated core-price freshness through the inverter stage, so negative all-in-price minimum-PV protection and optional HBC negative-price charging remain active when the all-in sensor is healthy.
- Source freshness is now derived from a Home Assistant-side snapshot of HA-core `last_reported`, refreshed every 30 seconds. Node-RED verifies both snapshot age and source report age; missing, invalid, stale or implausibly future freshness fails safe without using `last_updated`/`last_changed` as communication heartbeats.
- External Release acknowledgement is protected by a 45-second HA-side verification lease; while release is requested HPVC forces full runtime evaluations so a stalled Node-RED engine cannot leave a historical acknowledgement active indefinitely.

### Inverter, External Release and HBC reliability

- Degraded inverter control now uses only the currently controllable inverter-limit total for grid-target correction when one or more configured inverters are unavailable.
- Recovery rebalance confirmation now accounts for inverter command step size, avoiding a stuck pending rebalance on coarse-step adapters.
- Inverter-health Insights distinguish partial availability from a plant-wide pause and no longer log normal `Unconfirmed → Healthy` confirmations as recoveries.

- Recovered inverters now trigger a one-time proportional rebalance of the available inverter limits, preventing temporary degraded-mode limit skew from persisting after communication returns.

- Added internal per-inverter health monitoring (`Healthy`, `Unconfirmed`, `Slow`, `Unavailable`, `Recovered`) without new Home Assistant helpers or dashboard cards.
- Isolated a temporarily unavailable inverter from the plant-wide live-input gate so healthy inverters can continue normal control.
- Added automatic inverter recovery reconciliation: when communication/readback returns, HPVC resumes control for that inverter and forces Action/service adapters to resynchronize their target on the next safe control cycle.
- Added transition Insights for inverter unavailable, slow confirmation, recovery, and recovered write/readback health.
- Configured inverter readback failures now remain unavailable instead of falling back to a cached command, so a failed readback cannot be mistaken for a verified live limit.
- Extended the slow-inverter isolation path to External Release so healthy inverters can restore to full while an older command remains unresolved on another inverter.
- External Release now classifies every configured inverter explicitly. Open-loop/unverified adapters cannot disappear from release eligibility, and reachable inverters with pending write or active settling work block acknowledgement.
- External Release remains strict for the first 90 seconds. After 90 continuous seconds, degraded acknowledgement may activate only when every independently reachable inverter is confirmed at full, remaining configured inverter(s) are genuinely unavailable, no reachable inverter has pending write/settling work, and no configured adapter is open-loop/unverified.
- Degraded External Release reports unavailable/unverified inverter(s) and total unconfirmed PV capacity in runtime reason/Insights.
- External Release now treats only an actually active post-write settling interval as blocking; an expired/timed-out retained settle record cannot strand a later full-output handoff.
- Improved External Release status/reason text for active restoration and blocked verification.
- Home Assistant readiness handling now allows per-inverter isolation so one unavailable inverter does not unnecessarily block healthy inverter control.

### Smart Update and recovery

- Smart Update and the recovery probe now verify the installed `node-red-contrib-home-assistant-websocket` version through Node-RED `GET /nodes` instead of inferring it from flow JSON.
- Smart Update now uses Node-RED API v2 revision checks, verified transactional recovery/rollback, response reconciliation, and preservation of unrelated concurrent Node-RED changes.
- Release tags are resolved to immutable Git commits before managed files are downloaded, removing the tag-movement/TOCTOU window while retaining the existing GitHub trust model.
- Package and dashboard YAML use a complete parser with duplicate-key rejection, real structure/version validation, post-write revalidation, and Home Assistant configuration validation before Node-RED deployment. Smart Update now falls back to Node-RED 5's bundled `js-yaml` when optional `yaml` 2.x is unavailable, and parser preflight runs before a new update transaction is created.
- Detached updater ownership is atomically published only after complete ownership metadata is prepared; established or uncertain owners are never reclaimed as empty locks.
- Stale-lock reclamation is serialized by a separate recovery-owner guard so concurrent retries cannot both reclaim the same dead updater lock.
- A detached updater process that cannot acquire ownership exits without changing HPVC helpers, status, resume intent, transaction metadata, or the shared updater result file.
- Ordinary safe-shutdown waiting and detached recovery are separate phases: repeated clicks during PV/HBC restoration cannot reach the installer, and recovery-only mode cannot begin a fresh installation without an interrupted transaction.
- Abrupt updater death can be recovered through a recovery-only retry while preserving the saved resume intention; a live owner still refuses the probe.
- Verified terminal `complete` and `rolled-back` transactions can be reconciled when final Home Assistant helper/status publication was lost. Mismatched terminal records fail safe without rollback or fresh installation.
- Terminal publication is outcome-safe: result-file or notification failures cannot roll back a verified installation or block rollback resume. Required helper/status publication is completed before durable acknowledgement, and acknowledged terminal history is not replayed.
- A fresh update persists its own launch marker before the first awaited resume-intent read, preventing older terminal history from restoring an obsolete enabled state after a later manual disable.
- Rollback recovery keeps the update marked in progress and preserves saved resume intent until restoring `hpvc_enabled` succeeds; a failure remains recovery-only on the next click rather than starting a fresh update.

### Diagnostics, performance and reports

- Added **Enable Insights** (default Off). Turning it Off hides the 10-Insights dashboard section and report controls and bypasses optional Insight generation/history, report-related activity history, periodic report-storage recovery work, and bounded performance aggregation. Core PV control, Daily Control Accuracy, HBC coordination, safety, notifications, update/recovery, and essential persistence remain active.
- Insights recovery candidates are cleared while Insights is disabled and no longer force full control evaluations, preventing optional diagnostics from defeating the issue #9 idle-load optimization.
- Enabling Insights records one informational Insight: **Insights enabled — diagnostic collection resumed.**
- Aligned Daily Control Accuracy journal preparation and restore on the shared schema/revision contract, including `headlineAttributionRevision`.
- Expanded bounded runtime profiling for cooldown gates, battery-capacity learning, HBC charge priority, final-target calculation, transition logging, inverter service-call preparation, and Insights/diagnostics without retaining per-cycle history.
- Increased the runtime evaluation stale-lock watchdog from 12 seconds to 30 seconds to reduce overlap risk during unusually slow Home Assistant/inverter operations.
- Aligned Smart Update and full-uninstall safe-shutdown runtime-lock checks with the same **30-second** evaluation watchdog, preventing maintenance from treating a still-valid 15–30 second evaluation as idle.
- Completed inverter service-call profiling on halted cycles so performance diagnostics remain accurate without changing control behavior.
- Support reports retain the standard **Generate report → Generating… → View report** dashboard flow. HTML is published at `/config/www/hpvc/support-report.html` and opened through `/local/hpvc/support-report.html`.
- The report-reset webhook is local-only; local viewing resets the tile to **Generate report**, while remote viewing does not reset it automatically.
- The `/local/` report view requires no extra component, but `/local/` content is not protected by Home Assistant authentication; use it only on trusted exposure paths.
- Replaced the historical report cache-busting label with the neutral `hpvc-report` query token.

### Maintenance, cleanup and validation

- Smart Update, flow removal, and full uninstall now reject stale/cached Action/service readback and require the same freshness snapshot contract used by runtime inverter control before destructive maintenance can proceed.
- Full-uninstall registry cleanup now includes the HPVC source-freshness sensor and the External Release heartbeat/lease helpers while retaining exact ownership matching.
- Release validation now derives the complete HPVC-owned entity/unique-ID inventory from `hpvc_config.yaml` and requires exact parity with the explicit full-uninstall allowlists, failing on both missing future ownership and stale/extra delete permissions. Runtime uninstall remains explicit and does not use wildcard deletion.
- Release validation covered control safety, External Release, updater transactions/recovery, YAML/templates, PV allocation, safe-shutdown boundaries, lock ownership, and terminal publication.
- Runtime documentation now follows the supported Node-RED/Node.js compatibility matrix; for the declared websocket baseline, Node-RED 4.x requires Node.js 18.2.0 or newer and Node-RED 5.x requires Node.js 22.9.0 or newer.

### Upgrade notes

- Supported Home Assistant OS/Supervised Node-RED add-on installations can use **Settings → Maintenance → HPVC updates**.
- Smart Update preserves HPVC entities, helper values, configuration and saved data; manual replacement of the Home Assistant package, Node-RED flow and dashboard remains supported.

## v1.5.3 — 2026-10-01

v1.5.3 adds safe maintenance workflows for both future Smart Updates and complete uninstall while retaining the v1.5.2 control model.

- Made Full Uninstall, Smart Update, and Manual upgrade mutually exclusive so maintenance workflows cannot overlap.
- Hardened Smart Update merge handling to preserve only one shared `global-config` node when IDs change between releases.
- Added scoped Smart Update error catching and clearer failure notices that keep HPVC disabled until inverter limits are verified after pre-updater failures.
- Added release-version consistency validation and documented the Smart Update GitHub trust model.
- Full Uninstall cleanup now includes the inverter-navigation range automation (`hpvc_keep_selected_inverter_in_range`), preventing a leftover HPVC registry entry after uninstall.
- Added Settings inverter navigation so only one configured PV card is shown at a time, with previous/next wraparound controls.
- Maintenance now shows the last GitHub check time in the Home Assistant local timezone, a release-notes shortcut for available updates, a compact configuration/input/Node-RED-flow health summary, and a clearly separated **Uninstall HPVC** section.
- Added **Manual upgrade** with a safe **Remove HPVC flows** action: it restores/validates PV first, removes only the four HPVC tabs, and preserves the Home Assistant package, entities, dashboard and saved data.
- Maintenance now shows **Node-RED flows: Ready / Removed / Not detected / Needs attention** so normal, intentionally removed, manually absent and inconsistent flow states are distinguishable.
- Safe uninstall/update shutdown now requires every configured inverter to be readable and confirmed at its full limit; unavailable/unverifiable inverter slots block destructive cleanup and are identified for manual verification.
- Reduced the dashboard Insight helper cache from 20 to 10 entities while keeping the complete current-day Insight journal and HTML/TXT report history unchanged (up to 1,000 entries).

### Added

- Added **Maintenance → HPVC updates** with installed/latest version display, periodic/manual GitHub release checks, an update-available indicator, **Update HPVC**, and post-install **Quick Reload Home Assistant**.
- Update checks now ignore the successful Exec return-code output, distinguish an installed version newer than GitHub's latest release, and send one persistent notification when each new update version is first detected (when HPVC notifications are enabled).
- Added a detached Smart Updater that safely restores PV first, downloads/validates the latest tagged HPVC files, atomically replaces only managed package/dashboard/Node-RED assets, preserves HPVC entities/settings/data, and survives replacement of the old HPVC flows.
- Smart Update now validates the downloaded flow's `node-red-contrib-home-assistant-websocket` requirement against the current Node-RED global configuration and stops before replacement when a manual dependency update is required.
- Added a confirmation-protected **Uninstall HPVC** control for manual installations.
- Added persistent uninstall progress, completion and failure notifications.
- Added dynamic Node-RED tab discovery by exact v1.5.3 tab labels instead of import-specific flow IDs.
- Added authenticated Node-RED cleanup fallbacks: direct Admin API, direct access with `SUPERVISOR_TOKEN`, Supervisor ingress, then explicit manual follow-up when automatic access is unavailable.

### Safe uninstall and reinstall

- Uninstall now starts with the live-tested **Safe Restore v3** lifecycle before destructive cleanup.
- The uninstall re-entry guard prevents overlapping cleanup runs.
- HPVC first disables only `input_boolean.hpvc_enabled`, preserving inverter configuration while shutdown is evaluated.
- If an inverter write/verification is already active, uninstall waits for that operation before issuing the normal full-limit restore.
- Configured and reachable inverter limits are restored to their configured full values through the existing HPVC verification/retry path.
- A fresh installation with no configured inverter is treated as having nothing to restore.
- Sleeping, offline or otherwise unusable inverter control paths do not cause an indefinite uninstall wait; the bounded safe-shutdown path fails safely if shutdown cannot complete.
- HPVC-owned HBC negative-price overrides are released before destructive cleanup.
- Only after safe shutdown completes, uninstall resets the complete HPVC helper set to fresh-install defaults and waits **15 seconds** for Home Assistant RestoreEntity persistence.
- The known-working entity-registry removal pattern is preserved: HPVC removes only exact packaged entity IDs and exact HPVC unique IDs through the supported Home Assistant WebSocket API.
- A clean `config/entity_registry/list` request is rebuilt immediately before registry cleanup so stale service-call payloads cannot remove the required WebSocket `type`.
- Node-RED Engine/Outputs/Reports tabs are removed by exact labels; the Inputs tab removes itself last with detached retry/verification.
- HPVC-owned config/data/report paths are removed without wildcard entity deletion or direct `.storage` editing.
- Normal version updates preserve existing HPVC helper values; the full fresh-install reset is uninstall-only.

### Hardening and safety

- Blocked Action-node input overrides on the fixed uninstall-state reset so stale `msg.payload.action` data cannot replace the intended service.
- Expanded uninstall error catching across the operational cleanup chain.
- Node-RED cleanup failure no longer blocks HPVC-owned file/data cleanup; remaining tabs are reported as a manual follow-up.
- Secured the temporary Node-RED ingress/access file with mode `0600` and cleanup on success/failure.
- Enabled **Global Context Store** on the bundled Home Assistant Node-RED server configuration because HPVC runtime Function nodes depend on it.
- Fixed embedded Node.js syntax in automatic Node-RED removal.
- Fixed a Node-RED runtime scope error in **Detect Runtime Transitions and Log Insights** where `currentPriceZone` could be referenced outside its declaration scope.
- Started the HBC Charge Priority 15-second transition-settle window at the first observed loss of confirmed charging, so it overlaps the exit hold and prevents a brief charging dip from causing an immediate opposite PV correction.
- Added per-inverter detection for repeated unconfirmed write supersessions; HPVC now warns after three consecutive supersessions instead of allowing a failing lock-bypass write path to remain silent.

### Negative-price mode

- `binary_sensor.hpvc_negative_price_mode` now requires HPVC to be enabled and configuration-valid before reporting active negative-price mode.
- The configured all-in price entity ID is trimmed before use.
- HBC permission remains independent: negative-price PV protection does not require HBC control to be enabled.

### Upgrade notes

- From v1.5.3 onward, use the dashboard Smart Updater for future releases when running the supported Home Assistant OS/Supervised Node-RED add-on environment.
- Smart Update preserves HPVC entities, helper values, configuration and saved data; it preserves the pre-update HPVC enabled/disabled state across Quick Reload, replaces a managed `/config/hpvc_dashboard.yaml` automatically, and reports custom/pasted dashboards for manual upgrade.
- **Quick Reload Home Assistant** uses `homeassistant.reload_all` after a successful Smart Update.
- Manual replacement of the Home Assistant package, Node-RED flow and dashboard remains the fallback.
- Do not uninstall to perform a normal upgrade. Existing helper/entity IDs are preserved so user configuration remains intact.
- Restart Home Assistant only when required by the installation/update instructions or after a completed full uninstall.

## v1.5.2

### Fixed

- Fixed issue #7 where one slow/unconfirmed inverter could hold the entire PV plant in the in-flight write lock while the house was importing from the grid.
- During an import-driven upward correction, HPVC now freezes only inverter(s) that have not confirmed the previous command and redistributes available increase across healthy inverters. Export/downward correction remains protected by the normal write lock.
- If the healthy inverters cannot reach the full requested increase, HPVC caps the temporary target at the reachable plant limit instead of raising a plant-wide allocation error.
- Fixed direction-safe allocation errors caused by small live-limit quantization outside a configured bound (for example 4.95 W with a 5 W minimum).
- Safe master-disable restore no longer waits for an older in-flight normal-control command; HPVC immediately issues full-limit targets to all configured inverters and uses the existing verification/retry path afterwards.
- Fixed price-zone Insight flapping at an exact threshold such as `0.0000 €/kWh`. Missing/partial evaluations no longer coerce the remembered state to false, and enter/leave transitions are logged only when the live price satisfies the corresponding hysteresis boundary.

### Reliability hardening

- Corrected Power Flow ApexCharts zero-line annotations to use `y: 0`.
- Reconciled published `controlAction` diagnostics with the allocator's final reachable target after slow-inverter target capping.
- Aligned current documentation and README release references with v1.5.2.
- Clarified the in-flight write-lock exceptions for import-driven upward recovery and safe master-disable restore.

## v1.5.1

- Added safe master-disable restoration: switching HPVC Off now restores configured inverter limits to full before normal control stops, where a usable control path is available.
- HPVC-owned negative-price HBC overrides are restored during the safe-disable sequence instead of being left active until HPVC is enabled again.
- Added the generic external PV-release handshake: `input_boolean.hpvc_external_release_request` and `binary_sensor.hpvc_external_release_active`.
- External release keeps HPVC enabled, respects higher-priority safety/minimum/restore states, restores PV to full through the normal inverter adapter path, and suspends ordinary curtailment until the request is removed.
- Support reports retain the most recent safe-disable restore result, including whether PV and HPVC-owned HBC restoration were required and confirmed.
- External release respects the normal PV cooldown/write-confirmation window; safe master-disable restoration bypasses the ordinary PV cooldown so a user-requested shutdown does not leave PV curtailed unnecessarily.
- Added an active-only External PV Release badge to the dashboard; the request helper remains an integration/API helper rather than a normal user control.
- Expanded HTML and TXT support reports with external-release request/active state and updated report version metadata.
- Updated installation, configuration, architecture, troubleshooting and inverter-compatibility documentation for the v1.5.1 handshake and safe-disable semantics.

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
- Inverter write failure escalation now survives 120-second retry/supersession cycles, so the extended unresolved-write warning remains reachable while retries continue.
- Daily-history file-write errors now release the persistence serialization guard so the normal persistence cycle can retry instead of remaining stalled until restart.
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
- Removed remaining declaration-only Function-node helpers/locals found by the final release review; this cleanup does not change control behavior.
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

