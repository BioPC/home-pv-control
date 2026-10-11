# Home PV Control v1.5.5

**Release date:** 2026-10-11

v1.5.5 improves the distinction between configuration mistakes and legitimate nighttime PV unavailability.

## Configuration and Night Restore

- The configured Solar power entity must now actually exist even while Night Restore is active.
- At least one configured inverter control/readback path must actually exist at all times.
- Mistyped or non-existent PV entity IDs therefore surface through the normal HPVC configuration/input warning instead of being hidden by the Night Restore telemetry exemption.
- Night Restore still tolerates an existing Solar/inverter entity that is temporarily unavailable or sleeping, so normal nighttime behavior is preserved.
- During daytime, HPVC still requires live numeric Solar telemetry and at least one live usable inverter path.
- Partial inverter operation is preserved: a slot-local inverter configuration defect or unavailable inverter is isolated when another inverter remains valid and usable; shared/ambiguous plant faults such as duplicate physical Number targets remain globally blocking.
- `binary_sensor.hpvc_required_inputs_ready` now reports non-existent Solar/inverter paths in its `unavailable_entities` diagnostics even during Night Restore.

## Upgrade

### Smart Update

Supported Home Assistant OS/Supervised Node-RED add-on installations can use **Settings → Maintenance → HPVC updates**. Smart Update preserves HPVC entities, helper values, configuration and saved data.

After a successful Smart Update, use **Quick Reload Home Assistant** when prompted.

### Runtime and maintenance fixes

- Fixed automatic safety-resume status synchronization: `hpvc_enabled` and `hpvc_auto_resume_pending` are now read live every runtime cycle, preventing the dashboard from showing **Disabled** after HPVC has automatically re-enabled.
- Fixed degraded multi-inverter validation: slot-local inverter configuration defects no longer globally safety-pause HPVC when at least one inverter remains valid; invalid slots are excluded from allocation while shared/ambiguous plant faults remain blocking.
- Added a conditional Maintenance warning when one or more configured PV inverters are unavailable or invalid. It explains that Smart Update, Remove HPVC flows, and Uninstall HPVC can wait up to 180 seconds and then cancel safely.
- Added a 60-second automatic fallback for the support-report Ready state. Local viewing still resets **View report** immediately through the existing local-only webhook; remote access such as Tailscale now returns to **Generate report** automatically without making the webhook remotely callable.

## Smart Update readiness hardening

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
- Fixed the desktop Maintenance layout so **Check for updates**, **Remove HPVC flows**, and **Uninstall HPVC** are direct peers in one three-column grid row with single-row tiles. The action row therefore stays horizontally aligned and the manual/uninstall buttons can no longer stretch to double height when extra update actions are visible. Release validation now guards this layout.
