# Home PV Control v1.6.0 — Release notes

HPVC v1.6.0 strengthens inverter safety, recovery and maintenance, and adds automatic Enphase DPEL and Hoymiles/OpenDTU discovery. Manual Number and Action/service controllers remain supported.

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

1. Back up Home Assistant and Node-RED. On supported Home Assistant OS/Supervised systems, use **Settings → Maintenance → HPVC updates** once v1.6.0 is available as a normal GitHub release; otherwise follow the documented manual upgrade.
2. Update `home assistant/hpvc_config.yaml`, `home assistant/hpvc_dashboard.yaml` and `node-red/hpvc_flow.json` together; keep the saved helper configuration and recovery data.
3. Check each effective inverter, per-controller permission, OpenDTU Full Limit source and Enphase manual Max/Min. Resolve any migration warning or dispatch recovery state before enabling control.

See [Installation](docs/01-installation.md), [Configuration](docs/02-configuration.md), [Troubleshooting](docs/04-troubleshooting.md) and the [Changelog](CHANGELOG.md) for procedures and detail.

## Testing and known limits

Source/mocked-runtime test suites cover control, dispatch and recovery, OpenDTU/Enphase registry discovery, HBC state transitions, rendered Home Assistant templates, maintenance safety and TXT/HTML reports. The clean installation ZIP does not contain development `scripts/` or `.github/` CI workflows.

These checks are not live hardware validation. Smart Update/rollback, flow removal, full uninstall, nighttime restart and migrated-controller maintenance identity reconciliation must be exercised in Home Assistant before declaring a stable release. The original test results should not be read as proof that every update path or maintenance scenario is safe on an installed system.
