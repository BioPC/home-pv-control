# Home PV Control v1.5.5

**Release date:** 2026-10-11

v1.5.5 improves Smart Update reliability, shared Node-RED runtime efficiency, optional Insights processing, degraded multi-inverter behavior, Maintenance safety, and the distinction between configuration mistakes and legitimate nighttime PV unavailability.

## Configuration and Night Restore

- The configured Solar power entity must now actually exist even while Night Restore is active.
- At least one configured inverter control/readback path must actually exist at all times.
- Mistyped or non-existent PV entity IDs therefore surface through the normal HPVC configuration/input warning instead of being hidden by the Night Restore telemetry exemption.
- Night Restore still tolerates an existing Solar/inverter entity that is temporarily unavailable or sleeping, so normal nighttime behavior is preserved.
- During daytime, HPVC still requires live numeric Solar telemetry and at least one live usable inverter path.
- Partial inverter operation is preserved: a slot-local inverter configuration defect or unavailable inverter is isolated when another inverter remains valid and usable; shared/ambiguous plant faults such as duplicate physical Number targets remain globally blocking.
- `binary_sensor.hpvc_required_inputs_ready` now reports non-existent Solar/inverter paths in its `unavailable_entities` diagnostics even during Night Restore.

## Runtime and performance

- Night Restore Maintenance proof now requires independently verifiable state: Action/service inverters need fresh numeric readback, while command-cache and startup-full assumptions are never accepted for destructive Maintenance authorization.
- Night Restore now retains a current-configuration full-output confirmation for destructive Maintenance. If all configured inverter limits were confirmed full before the inverter went to sleep, Smart Update, Remove HPVC flows, and Full Uninstall can continue without waiting for fresh nighttime readback; fresh partial limits, configuration changes, or Night Restore ending invalidate the proof.
- Issue #9 hardening keeps the PV-control wake interval at **10 seconds** and guarantees that active price-zone limiting bypasses the stable-input limiter, preserving the full control cadence while idle/unrestricted operation can skip heavier evaluations.
- Periodic runtime-history persistence now runs on a **60-second** cadence instead of every control wake, while safety-critical negative-price override changes still persist immediately.
- Existing inverter writes remain change-based, avoiding repeated identical commands except for configured Action/service heartbeat refreshes.
- Added **Enable Insights** as an optional performance mode. It defaults to Off and sits after **Notifications** in Settings. When Off, HPVC hides the 10-Insights dashboard section and report controls, stops Insight generation/history, Power Control activity history used only by Insights/reports, optional report-storage recovery work, and bounded performance-diagnostic aggregation, while core PV control, Daily Control Accuracy, HBC coordination, safety, notifications, update/recovery and essential persistence remain active.
- Insights recovery candidates are cleared while Insights is disabled and no longer force full control evaluations.
- GitHub release checks now use bounded request, response, overall, and Exec timeouts so a stalled network connection cannot leave an update check running indefinitely.
- Enabling Insights records one informational Insight: **Insights enabled — diagnostic collection resumed.**
- Fixed automatic safety-resume status synchronization: `hpvc_enabled` and `hpvc_auto_resume_pending` are now read live every runtime cycle, preventing the dashboard from showing **Disabled** after HPVC has automatically re-enabled.
- Fixed degraded multi-inverter validation: slot-local inverter configuration defects no longer globally safety-pause HPVC when at least one inverter remains valid; invalid slots are excluded from allocation while shared/ambiguous plant faults remain blocking.

## Maintenance and report behavior

- Smart Update, flow removal, and full uninstall now require fresh Action/service inverter readback using the same HA freshness snapshot contract as runtime control; cached numeric readback cannot authorize destructive maintenance.
- Added a conditional Maintenance warning when one or more configured PV inverters are unavailable or invalid. Action/service inverters without a valid numeric readback now surface **Maintenance verification unavailable** before the action, because automatic maintenance cannot prove full-output restoration. Smart Update, Remove HPVC flows, and Uninstall HPVC can wait up to **180 seconds** for full-output verification and then cancel safely if verification cannot complete.
- Support-report Accuracy now takes the headline and factor/RMS/sample diagnostics from one coherent publication snapshot instead of independently-aged helpers.
- Full uninstall explicitly resets **Enable Insights** to Off before helper removal so a later fresh install cannot inherit an old opt-in RestoreEntity state.
- Restored the proven desktop Maintenance widths so the Maintenance heading, status columns, and three-button action row keep their intended layout in Home Assistant.
- Added a **60-second** automatic fallback for the support-report Ready state. Local viewing still resets **View report** immediately through the existing local-only webhook; trusted remote access paths such as Tailscale return to **Generate report** automatically without exposing the reset webhook remotely.
- Fixed the desktop Maintenance action layout so **Check for updates**, **Remove HPVC flows**, and **Uninstall HPVC** remain aligned as direct single-row peers.
- Report actions and **Restore defaults** use full-width dashboard tiles for a consistent layout.

## Upgrade

### Smart Update

Supported Home Assistant OS/Supervised Node-RED add-on installations can use **Settings → Maintenance → HPVC updates**. Smart Update preserves HPVC entities, helper values, configuration and saved data.

After a successful Smart Update, use **Quick Reload Home Assistant** when prompted.

## Smart Update readiness hardening

- Verified pre-install/no-change terminal recovery now republishes the saved enabled/disabled intent before any Node-RED Admin API discovery. If HA publication fails, the unacknowledged terminal record remains retryable and `hpvc_update_reload_required` stays Off because no installation occurred.

- Night Restore Maintenance proof is now invalidated by any independently verified partial inverter even if another inverter is offline, and is re-created only after every configured inverter is independently confirmed full again.
- The Night Restore proof signature now covers the complete effective Action/service adapter configuration, including fixed/target payloads, value field, pre/post actions, step, refresh, full and minimum limits.
- Successful pre-install reconciliation now leaves Smart Update immediately retryable: `Update not started` is recognized as terminal and the next click begins a fresh ordinary update rather than recovery-only mode.

- Final GitHub-readiness cleanup fixes Troubleshooting document structure, removes stale sensor/binary-sensor-only wording, and extends validation to core repository files, the GitHub Actions workflow, and local Markdown links/images.

- Pre-install prerequisite/API failures are now a distinct no-change outcome: HPVC never arms the package-activation gate when nothing was installed, the saved pre-update master intent is preserved, and recovery can reconcile a launched/prepared no-change transaction without requiring the Node-RED Admin API.
- Activation inventory discovery is domain-generic for HPVC template entities with explicit `default_entity_id`, so future template switches/buttons/numbers/selects are included automatically instead of only sensor/binary-sensor platforms.
- Smart Update derives activation dependencies automatically from the installed/staged `hpvc_config.yaml` inventories; no manually maintained entity list or arbitrary Node-RED flow-reference scan is required.
- All newly introduced HPVC package entities are checked for existence only. Runtime states such as `unknown` or `unavailable` do not block package activation.
- Quick Reload polls readiness for up to 20 seconds using one Home Assistant states API request per cycle and checks newly introduced package entities by existence only. An exclusive transaction-bound activation lease serializes manual and automatic retries; a live checker cannot be duplicated, while an abandoned `checking` phase becomes recoverable after the lease is stale.
- Activation lease creation is hardened against create-before-metadata races: a freshly claimed/unreadable lock is treated as busy until its filesystem age proves staleness, stale locks are quarantined before reclamation, and heartbeat renewal verifies ownership. Failure helper/status publication happens while the attempt still owns the lease, while delayed process results are side-effect free at the downstream publication boundary so stale failures cannot undo newer finalization.
- Readiness metadata is bound to the completed Smart Update transaction by release tag, commit and transaction ID, and the persisted transaction carries the pre-update HPVC enabled/disabled intent used after readiness succeeds.
- If Quick Reload cannot activate the new package entities, HPVC keeps update activation gated and requests a full Home Assistant restart, then performs the same transaction-bound recheck automatically after Home Assistant returns. Activation preparation restores the saved master state while the gate remains on; only after preparation is acknowledged is the transaction marked complete and final helper cleanup reconciled. Interrupted finalization is idempotent, and stale/duplicate results are ignored so they cannot re-arm a completed transaction.
- Verified rollback removes pending readiness metadata. External Release heartbeat/lease service calls remain blocked while activation is pending or their helpers are unavailable, preventing issue #8-style error floods.
- The mechanism adds no new Home Assistant helper entities.
- Added GitHub Actions release validation (`.github/workflows/validate-release.yml`) backed by `scripts/validate_release.py` plus `scripts/test_activation_recovery.py`. Pushes and pull requests validate release/version consistency, strict YAML/Node-RED structure, template entity IDs, updater/recovery parity, durable activation invariants, uninstall ownership, degraded-inverter policy, desktop Maintenance alignment, Function/embedded Node.js syntax, Exec shell syntax, and behavioral activation interruption/concurrency regressions.
- Full-uninstall ownership is now release-gated against the package itself: validation derives all HPVC-owned helper/script/template entity IDs plus template/automation unique IDs from `hpvc_config.yaml` and requires the explicit uninstall allowlists to match exactly. Missing future ownership and stale/extra delete permissions both fail validation; runtime uninstall remains conservative and never uses a broad `hpvc_*` wildcard.
- Release validation now discovers HPVC template entities generically across all template domains (not only sensors/binary sensors), so future template switches, buttons, numbers, selects, and other template platforms are covered automatically. CI also rejects duplicate YAML mapping keys in both the package and dashboard instead of accepting the last duplicate silently.
- Smart Update no longer requires users to install the optional `yaml` npm package manually. It prefers `yaml` 2.x when present and otherwise uses Node-RED 5's bundled `js-yaml`; parser preflight now runs before a fresh transaction is created, so a parser prerequisite failure cannot disable HPVC or trigger rollback/recovery.
