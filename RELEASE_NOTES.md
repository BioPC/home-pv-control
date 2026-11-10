# Home PV Control v1.6.2 — Release notes

Version 1.6.2 is a focused safety/recovery fix for v1.6.1. It retains the five-tab health monitoring and Smart Update protections while repairing unattended recovery after a temporary Node-RED health interruption.

## Fixed

### Follow-up fixes — manual stop and orphan activation gate
- A direct Home Assistant user OFF transition (`user_id` present, `parent_id` absent) cancels `hpvc_auto_resume_pending` **and** the healthy-session witness even if recovery was pending; safety automation OFF transitions preserve a valid reservation. If HPVC is already off or a script/integration has ambiguous context, press **Cancel automatic resume** explicitly.
- Correct the Node-RED **Reconcile orphaned activation gate** package-version check from `1.6.0` to `1.6.2`. It continues refusing reconciliation when a recovery transaction or uncertain updater lock exists, and leaves the reload safety gate set until in-progress is cleared.
- Both corrections retain the `1.6.2` release identifier. Source-level tests do not establish live Home Assistant timing or physical inverter behavior.

### Corrected v1.6.2 safety build
- Completing first-install setup marks onboarding complete but **leaves HPVC disabled** until a person enables it.
- Safety shutdown preserves any previously armed auto-resume reservation, including overlapping Node-RED/input failures; an invalid first-enable attempt cannot create one.
- For an already-disabled HPVC with automatic resume pending, the dashboard now shows **Cancel automatic resume**. Press it to prevent unattended re-enabling. Merely toggling an already-off boolean cannot produce an off-state event in Home Assistant.
- Manual switch-off during normal running invalidates the healthy-session witness. A safety-driven off-state transition does not clear an existing recovery reservation.
- Static checks cannot establish every asynchronous Home Assistant event-order or inverter behavior: conduct live testing before unattended deployment.
- The Node-RED runtime safety guard no longer always clears `hpvc_auto_resume_pending` when it disables an already-running HPVC instance. It remembers recovery intent **only** if that instance had previously run with healthy flows, valid configuration/inputs and completed onboarding.
- Recovery now listens for `sensor.hpvc_node_red_runtime_health` returning to `Ready`; otherwise the previous recovery automation could miss the return to normal even when a pending latch existed.
- Recovery waits for five seconds of continuously valid configuration, required inputs and Node-RED runtime health, and refuses automatic re-enable while Smart Update / activation reload flags remain active.
- A direct manual disable cancels recovery and clears the healthy-runtime witness. First-install setup continues to leave HPVC disabled; attempts to enable without a previously healthy runtime cannot arm unattended recovery.

---

# Home PV Control v1.6.1 — Release notes

Version 1.6.1 is a maintenance and reliability update to the v1.6.0 feature baseline. It strengthens Smart Update activation, flow liveness reporting, safe removal and Master Control feedback.

## Smart Update and configuration compatibility
- Recognizes Home Assistant `homeassistant.reload_all` calls as a possible trigger for the existing activation verifier, alongside HPVC Maintenance Quick Reload.
- Requires the expected installed version (`1.6.1`) and Home Assistant package entities before completing update activation; Node-RED deploy alone does not substitute for Home Assistant reload.
- Rebuilds Node-RED's cross-release configuration snapshot after Smart Update without erasing persistent Night Restore or inverter-restoration obligations.
- The Home Assistant UI reload event payload and end-to-end activation still require testing on the target installation.

## Five-tab runtime health
- Independently tracks the Inputs, Engine, Outputs, Reports and Maintenance tab heartbeats through Home Assistant helpers.
- Uses 10-second heartbeats, a 30-second liveness window and a 5-second health refresh. Manual deletion is reported as `Stale` after the last heartbeat expires, rather than falsely retaining `Ready` indefinitely.
- Reports confirmed Maintenance removal as `Removed`. Other possible states include `Ready`, `Incomplete`, `Missing`, `Updating`, maintenance progress and failure states.
- A heartbeat shows that a tab is reporting; it is not a complete flow-inventory or successful-control-operation test.

## Safe removal and uninstall
- On action acceptance, reports preparation and inverter-restoration progress; displays `Removing` or `Uninstalling` only after verified-safe inverter restoration permits deletion.
- Maintains the established safety checks and aborts cleanup on failed inverter verification, reporting `Restoration failed` or `Needs attention` as appropriate.
- Clears flow heartbeat helpers after a confirmed Maintenance removal. Manual deletion has no detached cleanup worker and is detected by heartbeat timeout.
- If the Maintenance tab is offline, update, remove and uninstall controls are unavailable. Re-import the HPVC flows to restore the Maintenance handler before uninstalling.

## Dashboard and Master Control
- Uses a single short Maintenance-offline warning, including inverter-limit guidance. Keeps mobile action rows compact, and avoids stretched action buttons on desktop.
- Greys out **Enable HPVC** when the five-tab runtime is not `Ready`; Home Assistant also turns off an attempted enable when flows are unhealthy.
- Displays a consistent disabled state in HPVC Status and Decision Details after manual or confirmed flow removal, preserving historical decision data internally.
- Improves Reason spacing and the disabled-state instruction for the ready-but-off condition.

## Installation and verification
1. Back up the Home Assistant package and Node-RED flows.
2. Install `home assistant/hpvc_config.yaml`, `home assistant/hpvc_dashboard.yaml` and `node-red/hpvc_flow.json` together, then reload Home Assistant and deploy the flows.
3. Confirm the five tab heartbeats and runtime-health sensor are reporting before enabling HPVC. Verify inverter restoration and maintenance flows on real hardware before relying on removal/uninstall.

**Limitations:** Package parsing, JavaScript checks and simulated regressions do not prove live Home Assistant reload event handling, inverter readback, Smart Update completion or full uninstall. The Maintenance flow is still required for uninstall; an independently running flow-inventory watchdog is not implemented.

---

## v1.6.0 feature baseline

HPVC v1.6.0 strengthened inverter safety, recovery and maintenance, and added automatic Enphase DPEL and Hoymiles/OpenDTU discovery. Manual Number and Action/service controllers remain supported.

## Safety and restoration (highest priority)

- **Safe writes and recovery:** PV Cooldown is configurable from **2–60 seconds** (default **10**); External Release verification runs independently. Night Restore blocks stale queued writes and keeps outstanding physical-call barriers. Fresh low-PV evidence retains its 120-second confirmation; when PV telemetry is stale/unavailable and `sun.sun` is `below_horizon`, the same safe Night Restore path starts without waiting for a PV report. Daytime freshness remains strict; sunrise recovery requires fresh PV telemetry.
- **Verified full output:** Disable, Smart Update, Remove flows and Full Uninstall require trustworthy full-output evidence and no pending, in-flight or uncertain commands. Existing full-output proof survives redundant restore writes; completed auto-controller writes no longer leave stale verification barriers.
- **Freshness and identity:** OpenDTU API confirmation must follow the actual dispatch; contradictory serials or stale readbacks are rejected. Freshness evidence is tied to the effective controller entity, including manually configured controllers migrated to automatic control.
- **Action sequencing:** Calls are serialized; unsent obsolete actions can be replaced, while already-sent actions complete under generation/identity protection. Interrupted work and uncertain leases require recovery rather than silent clearance.
- **Persistent obligations:** A removed inverter's original restoration obligation remains blocking until safely verified or explicitly reconciled as unrecoverable. Reconciliation does **not** claim that physical full-power restoration occurred.
- **Safety timing:** External Release uses independent lease checks with proactive refresh at 25 seconds and rejects heartbeat/verified evidence at 30 seconds or older. Night Restore retains its confirmation and recovery hysteresis rather than trusting stale zero-PV values.
- **Readback nuances:** Already-full Number entities can retain independently established full-output proof through a redundant restore call. Slow OpenDTU absolute-limit commands keep an extended retry/final-verification window; one stale API `Ok` cannot confirm a newer dispatch.
- **Failure isolation:** Per-inverter faults are isolated where safe. Unknown ownership, duplicate physical targets or unresolved restoration obligations block affected control or destructive maintenance rather than guessing.

## Automatic inverters and manual migration

- **Hoymiles/OpenDTU:** Discover supported MQTT `limit_nonpersistent_absolute` Watt entities through HA registry metadata, including renamed devices; reject relative/persistent or unrelated controls. Rated power follows **live `/api/limit/status` `max_power` → confirmed API cache → manual Full Limit**, never the HA Number `max` attribute. Slow readback retains its extended verification window.
- **Enphase DPEL:** Detect complete Envoy controllers (Enphase Envoy Installer 0.10.2+), one per Envoy, without a placeholder manual slot. Require supported `Production`/`Export` mode and enabled permission. Configure HPVC **Max power and Min power manually**; native DPEL Number range metadata is only a command capability.
- **Upgrade migration:** A manual inverter is matched to the native automatic controller only with reliable device identity. HPVC reuses the effective slot, preserves original manual helpers and holds ambiguous potential duplicates instead of activating two physical control paths. Conflicts are shown in Settings and diagnostics.
- **Identity changes:** Enphase range settings do not transfer to a different Envoy. All ten auto-managed identity helpers are included in live state; migrated Number-controller verification uses the new effective entity's freshness, not an old saved entity timestamp.
- Supports mixed manual/automatic installations, up to **10 effective slots**, and monitoring-only setup with zero usable inverters.
- **Controller disappearance:** HPVC can release vanished HPVC-owned automatic slots, while keeping genuine manual configuration. Unknown/offline identity does not authorize conversion or deletion.
- **Verification:** OpenDTU can use optional `limit_set_status` for early evidence. A confirmed physical controller is verified only once; freshness source IDs must match the effective Number readback.

## Maintenance and updates

- The five managed Node-RED tabs are **Inputs, Engine, Outputs, Reports and Maintenance**. Update/rollback, flow removal and uninstall manage the same tab set; v1.5.6 activation recovery and stable node IDs are retained.
- Maintenance watchers preserve the original full-output obligation even when a controller disappears or is replaced. OpenDTU maintenance continues using the documented API/cache/manual Full Limit order. Maintenance now checks the effective runtime-resolved inventory so migrated controllers are not counted twice; this reconciliation has passed isolated checks but is **not yet field-tested**.
- Smart Update and Recovery Probe validate the selected release version. Full uninstall preserves its protected cleanup order; Night Restore startup state and price-zone hysteresis share appropriate runtime context.
- For permanently removed, unrecoverable devices, the Settings reconciliation form requires explicit identity-scoped confirmation and records that physical restoration was not proven.
- **Maintenance layout:** Status and buttons retain their existing positions; reconciliation is shown below only when needed. Engine-to-HA status is diagnostic information, not restoration proof.
- **Persistence audit:** The protected uninstall finalizer removes Inputs and Maintenance last and records failure if cleanup cannot finish. Night Restore persists its active state through the journal; shared price-zone state prevents separate Engine/Inputs hysteresis histories.

## Dashboard, controls and HBC

- Per-inverter **HPVC Control** permissions support monitoring without commands. Min above Max produces a warning and requires re-enabling control after correction; Min equal to Max is valid.
- Native settings distinguish manual from auto-detected controllers, show clearer Enphase/Hoymiles status and appropriate read-only/editable fields, and handle the zero-inverter state.
- Controller configuration remains visible in one compact inverter row. Auto-detected limit entities are read-only; Enphase Max/Min are manually editable, and OpenDTU Full Limit is editable when trusted API/cache rated power is unavailable.
- Home Assistant runtime/UI status recognizes JSON strings and native-list attributes, with consistent effective controller counts and actual-limit sensors.
- Optional HBC integration remains independent: Charge Priority runs only for executing `Charge`/`Charge PV`; Eco Charge is separate. Reports and Insights remain available.

## Upgrade guidance

1. Back up Home Assistant and Node-RED. On supported Home Assistant OS/Supervised systems, use **Settings → Maintenance → HPVC updates** once v1.6.1 is available as a normal GitHub release; otherwise follow the documented manual upgrade.
2. Update `home assistant/hpvc_config.yaml`, `home assistant/hpvc_dashboard.yaml` and `node-red/hpvc_flow.json` together; keep the saved helper configuration and recovery data.
3. Check each effective inverter, per-controller permission, OpenDTU Full Limit source and Enphase manual Max/Min. Resolve any migration warning or dispatch recovery state before enabling control.

See [Installation](docs/01-installation.md), [Configuration](docs/02-configuration.md), [Troubleshooting](docs/04-troubleshooting.md) and the [Changelog](CHANGELOG.md) for procedures and detail.

## Testing and known limits

Source/mocked-runtime test suites cover control, dispatch and recovery, OpenDTU/Enphase registry discovery, HBC state transitions, rendered Home Assistant templates, maintenance safety and TXT/HTML reports. The clean installation ZIP does not contain development `scripts/` or `.github/` CI workflows.

These checks are not live hardware validation. Smart Update/rollback, flow removal, full uninstall, nighttime restart and migrated-controller maintenance identity reconciliation must be exercised in Home Assistant before declaring a stable release. The original test results should not be read as proof that every update path or maintenance scenario is safe on an installed system.
