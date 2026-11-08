# Home PV Control v1.6.1

A maintenance update to v1.6.0, focused on Smart Update activation, trustworthy Node-RED health, safe cleanup and consistent dashboard feedback.

## Smart Update and activation
- Detect Home Assistant `homeassistant.reload_all` events to recheck activation after a Home Assistant-initiated Quick Reload, while keeping the HPVC Maintenance reload path.
- Require the expected `sensor.hpvc_installed_version` (`1.6.1`) and package entities before finalizing activation.
- Invalidate older-release Node-RED configuration snapshots; preserve persistent Night Restore and inverter restoration state.

## Runtime health and flow removal
- Track all five HPVC Node-RED tabs with independent 10-second heartbeats, 30-second expiry and 5-second health checks.
- Report `Ready`, `Incomplete`, `Stale`, `Missing`, `Updating`, and verified maintenance operation states. Manual tab deletion becomes `Stale` after expiry; confirmed Maintenance removal becomes `Removed`.
- Clear heartbeat helpers on successful Maintenance removal, and report `Removing` without relying on expiring heartbeat values.

## Safe uninstall and Maintenance controls
- Show `Preparing removal` / `Preparing uninstall` and inverter-restoration progress before cleanup. Only show `Removing` / `Uninstalling` after the safety watcher verifies inverter full-output limits.
- Abort removal/uninstall if verification fails or times out; report the failure and retain safety obligations.
- Hide unavailable Update, Remove and Uninstall actions when the Maintenance handler is offline, replacing overlapping warnings with one concise notice.
- Keep normal-height Maintenance controls and a compact mobile layout.

## Master Control and dashboard
- Grey out **Enable HPVC** when flows are unhealthy and guard the underlying enable boolean in Home Assistant.
- Make HPVC Status and Decision Details display consistent disabled/offline feedback after manual and automatic flow removal, without erasing previous internal control decisions.
- Improve the Reason field spacing and disabled-state message.

## Installation
Update all three files together: `home assistant/hpvc_config.yaml`, `home assistant/hpvc_dashboard.yaml` and `node-red/hpvc_flow.json`. Back up first and verify the updated Home Assistant entities and five Node-RED tabs after deployment.

## Verification and known limits
Structural parsing, Node-RED JavaScript syntax and included simulated regressions are not live Home Assistant acceptance tests. HA Quick Reload event detection, end-to-end Smart Update recovery, real inverter restoration and uninstall require field verification. Heartbeat health is not an independent flow inventory, and Full Uninstall still requires the Maintenance tab.
