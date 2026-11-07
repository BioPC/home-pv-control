# Home PV Control v1.5.3

**Release date:** 2026-10-01

v1.5.3 adds safe maintenance workflows for both future Smart Updates and complete uninstall while retaining the v1.5.2 control model.

- Full Uninstall cleanup now includes the inverter-navigation range automation (`hpvc_keep_selected_inverter_in_range`), preventing a leftover HPVC registry entry after uninstall.
- Added Settings inverter navigation so only one configured PV card is shown at a time, with previous/next wraparound controls.
- Maintenance now shows the last GitHub check time in the Home Assistant local timezone, a release-notes shortcut for available updates, a compact configuration/input/Node-RED-flow health summary, and a clearly separated **Uninstall HPVC** section.
- Added **Manual upgrade** with a safe **Remove HPVC flows** action: it restores/validates PV first, removes only the four HPVC tabs, and preserves the Home Assistant package, entities, dashboard and saved data.
- Maintenance health now reports **Node-RED flows: Ready / Removed / Not detected / Needs attention** so normal, intentionally removed, manually absent and inconsistent flow states are distinguishable.
- Smart Update now validates the downloaded flow's `node-red-contrib-home-assistant-websocket` requirement against the current Node-RED global configuration and stops before replacement when a manual dependency update is required.
- Reduced the dashboard Insight helper cache from 20 to 10 entities while keeping the complete current-day Insight journal and HTML/TXT report history unchanged (up to 1,000 entries).

## Highlights

- The new **Maintenance → HPVC updates** section checks the latest GitHub release, shows update availability, installs newer HPVC releases while preserving entities/settings/data, and offers **Quick Reload Home Assistant** after installation.
- Update checking now distinguishes **Up to date**, **Update available**, and **Installed version is newer than latest release** without misreporting a successful process exit as `[object Object]`; when HPVC notifications are enabled, each newly detected update version creates one persistent notification.
- Smart Update downloads and validates the new files first, safely restores PV, then uses a detached updater process so replacing the old HPVC Node-RED tabs cannot terminate the update itself.
- Safe uninstall now restores PV limits when a usable configured inverter path exists before HPVC removes its own configuration.
- Installations with no inverter configured have nothing to restore. If a configured inverter is sleeping/offline/unavailable or otherwise cannot be verified at its full limit, the bounded watcher now stops cleanup and identifies the affected inverter(s) instead of silently treating shutdown as complete.
- A full uninstall resets HPVC helpers to fresh-install defaults and waits 15 seconds for RestoreEntity persistence so a later reinstall behaves like a clean first install.
- Normal upgrades preserve existing HPVC helper values.
- Node-RED tab cleanup discovers tabs by exact labels and supports direct Admin API, Supervisor-token and Supervisor-ingress access before falling back to a manual follow-up.

## Safe uninstall sequence

After confirmation, HPVC:

1. prevents a second uninstall run from starting;
2. disables only the HPVC master first, leaving inverter configuration available;
3. waits for active inverter write/verification work to finish;
4. restores configured PV limits to full when a usable inverter path is available;
5. releases any HPVC-owned HBC negative-price override;
6. treats no-inverter configurations as having nothing to restore, but requires every configured inverter to be readable and confirmed at its configured full limit; unavailable/unverifiable slots use the bounded failure path and are named in the failure message;
7. resets the complete HPVC helper set to fresh-install defaults;
8. waits 15 seconds for Home Assistant RestoreEntity persistence;
9. removes only exact HPVC registry entries through the supported Home Assistant WebSocket API;
10. removes HPVC Node-RED Engine/Outputs/Reports tabs by exact label;
11. removes HPVC-owned config/data/report paths and notifications; and
12. removes the HPVC Inputs tab last through a detached retry/verification finalizer.

Under normal conditions the full uninstall removes the HPVC-owned files/data and HPVC Node-RED tabs automatically. A Home Assistant restart is required after the uninstall reports completion.

HPVC never directly edits Home Assistant `.storage` files and does not use wildcard entity deletion. Inverter, battery, HBC, P1/grid-meter and shared Node-RED server configuration are deliberately left untouched.

If the dashboard was created by pasting YAML into Home Assistant, remove that dashboard/view manually. If a dashboard file was stored at a custom path instead of `/config/hpvc_dashboard.yaml`, remove that custom file manually.

## Reliability and hardening

- Preserved the previously live-tested entity-registry removal pattern.
- Rebuilt a clean WebSocket registry-list request immediately before cleanup to prevent stale `msg.payload` data from causing a missing-`type` WebSocket error.
- Added an uninstall re-entry guard.
- Blocked stale Action-node input overrides on the uninstall-state reset.
- Expanded uninstall error handling across the operational chain.
- Node-RED cleanup failures no longer block HPVC-owned file/data cleanup; unresolved tabs are reported as a manual follow-up.
- Secured temporary Node-RED ingress/session data with mode `0600` and cleanup on success/failure.
- Enabled **Global Context Store** on the bundled Home Assistant Node-RED server definition.
- Fixed embedded Node.js syntax in automatic Node-RED cleanup.
- Fixed the `currentPriceZone` scope error in **Detect Runtime Transitions and Log Insights**.
- HBC Charge Priority now starts its 15-second transition-settle window on the first observed loss of confirmed charging, overlapping the exit hold so a brief charging dip cannot immediately trigger an opposite PV correction.
- Added per-inverter warning after three consecutive unconfirmed write supersessions, closing a narrow lock-bypass case where a failing inverter write could otherwise remain silent.
- Extended inverter write-failure escalation now survives 120-second retry/supersession cycles, so an unresolved inverter can still reach the extended failure warning while HPVC continues retrying.
- Daily-history file-write errors now release the persistence serialization guard so the normal 10-second persistence cycle can retry instead of remaining stalled until restart.

## Negative-price mode

The negative-price mode sensor now requires HPVC to be enabled and configuration-valid, and it trims the configured all-in price entity ID before use. HBC permission remains independent because negative-price PV protection can operate without HBC control.

## Release hardening

- Made Full Uninstall, Smart Update, and Manual upgrade mutually exclusive so maintenance workflows cannot run concurrently.
- Smart Update now preserves a single existing shared `global-config` node even when configuration-node IDs differ between releases.
- Added a scoped Catch for update-path errors; pre-updater failures clear the in-progress state and explicitly leave HPVC disabled for inverter-limit verification.
- Added an availability guard to inverter navigation so a transiently unavailable inverter-count helper does not reset the selected PV during reload.
- Added automated release-version consistency validation for GitHub pushes and pull requests.

## Smart Update

From v1.5.3 onward, supported Home Assistant OS/Supervised Node-RED add-on installations can use **Settings → Maintenance → HPVC updates** for future releases. The updater checks the latest GitHub release, downloads and validates the tagged `hpvc_config.yaml`, `hpvc_flow.json` and `hpvc_dashboard.yaml`, runs the verified safe-shutdown path, then replaces the managed package and HPVC Node-RED tabs while preserving HPVC entities, settings, `hpvc-data`, history and reports.

The updater runs as a detached process before the old HPVC tabs are replaced. A managed `/config/hpvc_dashboard.yaml` is replaced only when it already existed; custom/pasted dashboards are left untouched and reported for manual upgrade. The standard `/config/packages/hpvc_config.yaml` path is required for Smart Update. After success, **Quick Reload Home Assistant** calls `homeassistant.reload_all` and restores HPVC to its pre-update enabled/disabled state.

Manual package/flow/dashboard replacement remains the fallback. Do **not** run the uninstaller just to upgrade: uninstall intentionally removes HPVC entities and saved data.
