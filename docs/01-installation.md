[← README](../README.md) · [Installation](01-installation.md) · [Configuration](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md) · [Inverter compatibility](05-inverter-compatibility.md)

# Installation

Home PV Control can run independently or alongside Home Battery Control. Use Steps 1–6 for a fresh installation. Existing installations should also read the upgrade section before replacing files.

## Requirements

Before installing HPVC, make sure you have:

- Home Assistant Core **2025.12 or newer** with package support. Earlier versions may work but are outside the documented support baseline.
- A currently supported Node-RED runtime. Node-RED 4.x requires Node.js 18.2.0 or newer for the declared Home Assistant websocket 0.80.3 baseline; Node-RED 5.x requires Node.js 22 or newer. Home Assistant add-on users should use the runtime bundled by the supported Node-RED add-on rather than pinning a separate JavaScript-runtime minimum.
- `node-red-contrib-home-assistant-websocket` **0.80.3 or newer**.
- Global Context Store enabled in the Node-RED Home Assistant server configuration.
- At least one PV inverter with either a writable Home Assistant `number` entity or a stable Home Assistant action/service that can apply an active-power limit.
- A valid grid-power sensor, market/export-price sensor, all-in-price sensor and PV-power sensor.
- **ApexCharts Card** installed through HACS for the supplied HPVC dashboard graphs.
- Home Battery Control only if you want optional HBC execution tracking and Charge Priority.

## Step 1 — Enable Home Assistant packages and install the HPVC package file

Open `configuration.yaml` in the Home Assistant configuration root and make sure package loading is enabled:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

If your `configuration.yaml` already contains a `homeassistant:` section, add the `packages:` line under that existing section instead of creating a second `homeassistant:` key.

Copy:

```text
home assistant/hpvc_config.yaml
```

from the HPVC release to:

```text
/config/packages/hpvc_config.yaml
```

Do **not** restart Home Assistant yet. Complete Step 2 first so all Home Assistant YAML/file changes can be applied with one restart.

## Step 2 — Install and register the HPVC dashboard

For the recommended managed dashboard, copy:

```text
home assistant/hpvc_dashboard.yaml
```

to the Home Assistant configuration root — the same folder that contains `configuration.yaml`:

```text
/config/hpvc_dashboard.yaml
```

Do **not** place `hpvc_dashboard.yaml` inside `packages/`, `hpvc-data/`, or `www/`.

Register the dashboard in `configuration.yaml`:

```yaml
lovelace:
  mode: storage
  dashboards:
    hpvc-dashboard:
      mode: yaml
      title: Home PV Control
      icon: mdi:solar-power
      show_in_sidebar: true
      filename: hpvc_dashboard.yaml
```

If your `configuration.yaml` already contains a `lovelace:` section, **do not add a second `lovelace:` key**. Merge only the `hpvc-dashboard:` entry under the existing `dashboards:` section.

This file-backed dashboard is recommended because Smart Update can keep `/config/hpvc_dashboard.yaml` current automatically.

If you intentionally prefer a custom/storage dashboard, you can instead create a dashboard or view in Home Assistant and paste the supplied YAML manually. Custom/pasted dashboards are not modified by Smart Update and must be updated manually after a release.

## Step 3 — Check configuration and restart Home Assistant

After the package file and dashboard registration are both in place:

1. Check the Home Assistant configuration.
2. Fix any reported YAML/configuration errors.
3. **Restart Home Assistant once.**

This is the single Home Assistant restart required for the normal first-install sequence.

After restart, the managed HPVC dashboard is loaded from:

```text
/config/hpvc_dashboard.yaml
```

Future Smart Updates can replace that file automatically. A later dashboard-file update normally does **not** require another full Home Assistant restart just because the dashboard YAML changed; reopen or refresh the dashboard to load the updated YAML.

## Step 4 — Import and deploy the Node-RED flow

Import:

```text
node-red/hpvc_flow.json
```

into Node-RED and deploy it.

Importing and deploying the flow **after** the Home Assistant restart is recommended because the HPVC package helpers/entities are already loaded when Node-RED starts evaluating the flow.

## Step 5 — Configure HPVC

Open the always-visible **Settings** tab and configure the required control paths:

- grid-power sensor;
- market/export-price sensor;
- all-in-price sensor;
- PV-power sensor;
- each configured inverter control path.

Review the shipped thresholds and optional HBC settings before enabling any behavior that depends on them.

### Shipped defaults

| Setting | Shipped default |
|---|---:|
| HBC integration / Charge Priority | Off |
| Force charge at negative price | On by default; used only when HBC control is enabled |
| PV limiting price | `0.00 €/kWh` |
| Price hysteresis | `0.02 €/kWh` |
| Export start | `-150 W` |
| Target export | `0 W` |
| Import restore | `150 W` |
| Min PV for control | `100 W` |
| Night Restore threshold | `10 W` |
| Cooldown | `30 s` |
| Deadband | `25 W` |

These are starting points, not universal recommendations. Review them for your inverter, sensors, electricity contract and local rules.

## Step 6 — Verify installation

Wait for first-install validation to complete.

Confirm that:

- the HPVC package entities/helpers are available;
- the **Home PV Control** dashboard opens;
- Node-RED is deployed without missing HPVC helper/entity errors;
- the configured live inputs are valid;
- each inverter control path is valid.

HPVC enables automatically once all required live inputs and control settings are valid.

For additional verification, generate an HPVC support report from the dashboard and review the live status, sensor health, inverter status and current control settings.

## Smart update from v1.5.3 onward

The preferred update path is **Settings → Maintenance → HPVC updates**. HPVC checks `BioPC/home-pv-control` through the GitHub Releases API and compares the latest release tag with `sensor.hpvc_installed_version`. Maintenance records the last completed GitHub check in `input_text.hpvc_last_update_check` as a standard ISO timestamp; the dashboard renders it using the Home Assistant local timezone. It also exposes the latest release notes while an update is available and shows a compact health summary for configuration, required inputs, and HPVC Node-RED flow state (`Ready`, `Removed`, `Not detected`, or `Needs attention`). The periodic check runs at Node-RED startup, every six hours, and whenever **Check for updates** is pressed. When a newer release is detected, HPVC shows **Update HPVC** and, when `input_boolean.hpvc_notifications` is enabled, sends one persistent notification for that newly detected release. The same release is not re-notified on each six-hour check. If the installed version is newer than GitHub's latest published release, Maintenance reports that explicitly instead of treating it as an error.

When **Update HPVC** is confirmed, HPVC:

1. disables normal HPVC control and runs the same verified safe-shutdown path used before uninstall, including a post-disable engine evaluation and PV full-limit restoration;
2. resolves the latest release tag to its immutable Git commit, downloads `hpvc_config.yaml`, `hpvc_flow.json`, and `hpvc_dashboard.yaml` from that commit, validates the expected HPVC package/dashboard/version-matched flow tabs, and confirms that the installed `node-red-contrib-home-assistant-websocket` version reported by Node-RED meets the downloaded flow's minimum version before replacing anything;
3. starts a detached updater process before the current HPVC Node-RED tabs are replaced, so deleting/replacing the old flows cannot terminate the updater itself;
4. keeps all existing HPVC entity-registry entries, helper values, inverter/HBC configuration, `hpvc-data`, report/history data and other saved runtime data;
5. atomically replaces `/config/packages/hpvc_config.yaml`; Smart Update requires this standard managed package path and falls back to manual upgrade when the package is stored elsewhere;
6. replaces `/config/hpvc_dashboard.yaml` only when that exact managed dashboard file existed before the update; a custom/pasted dashboard is never deleted or overwritten;
7. atomically replaces the four HPVC-managed Node-RED tabs while preserving unrelated user flows and the shared Home Assistant server/global configuration;
8. verifies that the four new version-matched HPVC tabs are present; and
9. reports completion and enables **Quick Reload Home Assistant**; after that reload, HPVC automatically resumes only when it was enabled before the update.

If the managed dashboard file was not present, HPVC reports that the custom/pasted dashboard must be updated manually. The downloaded dashboard file is not installed in that case.

**Quick Reload Home Assistant** calls `homeassistant.reload_all`. Home Assistant performs its own basic configuration check first and reloads the YAML domains that support reload without a full restart.

The Smart Updater is designed for the Home Assistant OS/Supervised Node-RED add-on environment, because it needs the Home Assistant config mount, `SUPERVISOR_TOKEN`, Supervisor API access, and Node-RED Admin API/ingress access. Other Node-RED/Home Assistant deployment types, and installations using a custom `hpvc_config.yaml` package path, should use the manual upgrade path.



### Smart Update recovery and rollback

Smart Update uses Node-RED API v2 revision checks and deploys modified flows. Concurrent deployments are refused rather than overwritten. Rollback restores only HPVC tabs against a fresh revision, preserving intervening unrelated changes. A lost response is reconciled by reading the active HPVC flows. File and flow rollback must be verified before automatic resume.

Private transaction metadata and original/intended files are kept in `/config/hpvc-data/update-recovery/`. If an update is interrupted or rollback cannot be verified, HPVC remains disabled and the backups remain available. Retrying Smart Update first attempts recovery of an unfinished transaction; after verified recovery, retry again to perform a fresh update. If the detached updater terminates after safe shutdown has authorized launch but before flow replacement, a later button press uses a recovery-only path. Repeated clicks while safe shutdown is still restoring/confirming PV or HBC state are ignored and cannot reach the installer. Recovery-only mode cannot start a fresh installation when no interrupted transaction exists. The launch guard reconciles terminal HA status with its local latch, and a filesystem process lock prevents a second updater writer from starting while another updater process is still active. If HPVC files/flows were changed outside the transaction, recovery refuses to overwrite them. Inspect the notification and backups before making a manual repair.



### Smart Update trust model

Smart Update retrieves the release tag from the GitHub Releases API, resolves that tag through the GitHub Git API to an immutable 40-character commit SHA, and downloads `hpvc_config.yaml`, `hpvc_flow.json`, and `hpvc_dashboard.yaml` over HTTPS from `raw.githubusercontent.com/BioPC/home-pv-control/<commit>/`. This removes the tag-movement/TOCTOU window between release discovery and the managed-file downloads. HPVC strictly parses both YAML files with duplicate-key rejection, validates required structure and actual package/dashboard version fields, validates the Node-RED JSON/tab labels and Home Assistant websocket dependency, then re-parses the exact staged files and calls Home Assistant's own configuration check before Node-RED deployment. A failed Home Assistant configuration check enters the same verified rollback path and the new Node-RED flow is not deployed. Smart Update requires the bundled Node-RED `yaml` 2.x parser and refuses to proceed if that complete parser cannot be resolved; it does not downgrade to marker-only or regex YAML checks. A private filesystem process lock also prevents overlapping detached updater writers. The updater still does **not** use an independently trusted cryptographic signature, so authenticity ultimately relies on the integrity of the `BioPC/home-pv-control` GitHub repository and GitHub HTTPS/API delivery. If that trust model is not acceptable for an installation, use the manual upgrade path and verify the downloaded release files independently before installing them.

Smart Update does **not** automatically change Node-RED palette dependencies. If the downloaded HPVC flow requires a newer `node-red-contrib-home-assistant-websocket` version than the installed Node-RED module reports, the update stops before file/flow replacement and tells you to update the Home Assistant Node-RED integration manually first.

For **Action/service** inverter control, automatic Smart Update also requires a valid numeric readback entity for every configured inverter. The readback is what lets HPVC confirm the live limit has returned to full before destructive replacement begins. Without it, the update stops safely and identifies the affected inverter; use the manual upgrade path after verifying/restoring the inverter limit yourself.

If download, validation, file replacement or flow deployment fails, HPVC leaves its entities and saved data intact, reports the failure, attempts to restore the previous managed files/flows when replacement had already started, and restores the pre-update HPVC enabled state when rollback succeeds. A safe-shutdown timeout or update-path exception stops the update **before** managed HPVC replacement when possible. When the safe-shutdown/update path fails before the detached updater takes over, HPVC remains disabled; verify inverter limits before enabling HPVC or retrying.

## Manual upgrade

Use **Settings → Maintenance → Manual upgrade → Remove HPVC flows** when Smart Update is unavailable or when you intentionally want to install a release manually. This is an upgrade workflow, not a full uninstall: HPVC configuration, entities/helpers, dashboard registration and saved `hpvc-data` are preserved while only the four HPVC Node-RED tabs are removed.

Before starting, back up the current `hpvc_config.yaml`, dashboard, Node-RED flow and `hpvc-data`. Then:

1. Press **Remove HPVC flows**. HPVC disables normal control, performs the same verified safe PV/HBC shutdown used by Smart Update/Full uninstall, removes only the four HPVC Node-RED tabs, and verifies that they are absent.
2. Install the new release [`home assistant/hpvc_config.yaml`](../home%20assistant/hpvc_config.yaml) at your HPVC package location.
3. Import the complete new [`node-red/hpvc_flow.json`](../node-red/hpvc_flow.json). Do not mix Node-RED tabs from different HPVC releases.
4. Update the dashboard from [`home assistant/hpvc_dashboard.yaml`](../home%20assistant/hpvc_dashboard.yaml), either by replacing the managed file or updating your custom/pasted dashboard.
5. Reload packages or restart Home Assistant as required by that release, deploy Node-RED, and confirm **Node-RED flows: Ready**.
6. Turn HPVC back on manually.

Maintenance shows **Node-RED flows: Removed** after the automatic flow-removal step succeeds. Re-importing the supplied flow changes the state to **Ready**. If the flows were removed manually or their state cannot be confirmed, Maintenance shows **Not detected**. A failed or inconsistent automatic removal shows **Needs attention**.

The flow-removal action blocks overlapping update/uninstall/removal runs, waits for a post-disable engine evaluation, active inverter write/verification work to finish, every configured inverter to be independently verified at full limit, and any HPVC-owned HBC override to be released. It then launches a detached remover so deleting the Inputs tab cannot terminate the operation. If safe shutdown cannot be verified within the bounded wait, no HPVC tab is removed. For **Action/service** inverter control, the same numeric readback requirement used by Smart Update/Full uninstall applies.

Do not run the full uninstaller for a normal upgrade: Full uninstall intentionally removes HPVC entities and saved data, while Manual upgrade preserves them.

## Upgrade from v1.2.0 or earlier

Version 1.3.0 renames active legacy helper entity IDs from `pv_ems_*` to `hpvc_*`. Upgrade the Home Assistant package, Node-RED flow, and dashboard together:

1. Replace [`home assistant/hpvc_config.yaml`](../home%20assistant/hpvc_config.yaml).
2. Import and replace the existing flow with [`node-red/hpvc_flow.json`](../node-red/hpvc_flow.json).
3. Replace or re-import [`home assistant/hpvc_dashboard.yaml`](../home%20assistant/hpvc_dashboard.yaml).
4. Review **Force charge at negative price**. HPVC seeds it **On** once on both fresh installations and upgrades. After that, a manual Off choice survives normal Home Assistant restarts and package/automation reloads. **Restore defaults** turns it On again.
5. Reload packages or restart Home Assistant, then deploy Node-RED.
6. Copy or re-enter your sensor entities, inverter entities, limits, thresholds, and HBC integration preference in the new `hpvc_*` helpers.

Do not mix files from different HPVC releases. Home Assistant may keep obsolete `pv_ems_*` helpers visible until their old package definitions are removed and Home Assistant is restarted.

## Full uninstall

Use **Settings → Uninstall HPVC** from the supplied dashboard. Do not manually delete the package first, because HPVC needs its inverter configuration during the safe-shutdown stage.

For **Action/service** inverter control, automatic Full uninstall requires a valid numeric readback entity for each configured inverter so HPVC can verify that the live limit is back at full. If readback is missing or unavailable, uninstall stops before destructive cleanup and identifies the affected inverter.

The uninstall sequence is:

1. prevent overlapping uninstall runs;
2. disable only `input_boolean.hpvc_enabled` first;
3. wait for any active inverter write/verification to finish;
4. restore configured inverter limits to full when a usable control path exists;
5. release any HPVC-owned HBC negative-price override;
6. continue without a PV restore when no inverter is configured; if any configured inverter is sleeping/offline/unavailable or otherwise cannot be verified at its full limit, wait only within the bounded safe-shutdown window and then abort cleanup while identifying the affected inverter(s);
7. reset the complete HPVC helper set to fresh-install defaults;
8. wait **15 seconds** for Home Assistant RestoreEntity persistence;
9. remove only exact HPVC-owned Home Assistant entity-registry entries through the supported WebSocket API, including the source-freshness sensor and external-release heartbeat/lease helpers;
10. remove the HPVC Engine/Outputs/Reports Node-RED tabs by exact label;
11. delete the exact HPVC-owned package/data/report paths and clear HPVC notifications; and
12. remove the HPVC Inputs tab last through the detached retry/verification finalizer.

After the uninstall reports completion, restart Home Assistant.

The automatic cleanup removes these HPVC-owned paths when present:

- `/config/packages/hpvc_config.yaml`
- `/config/hpvc_dashboard.yaml`
- `/config/hpvc-insight-history.json`
- `/config/hpvc-data/`
- `/config/www/hpvc/`

HPVC does **not** remove shared Node-RED server configuration or external inverter, battery, HBC, P1/grid-meter entities.

Node-RED tab cleanup tries local Admin API access, direct access with `SUPERVISOR_TOKEN`, and Supervisor ingress. Under normal conditions the HPVC Node-RED tabs are removed automatically. Only if all automatic paths fail does HPVC report a manual follow-up. A Node-RED access failure does not block HPVC-owned file/data cleanup.

Automatic Node-RED/file cleanup is designed for the Home Assistant OS/Supervised Node-RED add-on environment, where the Home Assistant configuration mounts, Supervisor access, and add-on API are available. Home Assistant Container/Core or other custom Node-RED deployments may require the documented manual cleanup fallback.

If you installed `hpvc_config.yaml` anywhere other than `/config/packages/hpvc_config.yaml`, remove that custom package file manually after uninstall. If you created the dashboard/view by pasting the supplied YAML into Home Assistant, remove that dashboard/view manually afterward. If you used a custom dashboard file path, remove that custom file manually. If a YAML dashboard registration was added separately to `configuration.yaml`, remove that external registration yourself after uninstall.

## Next steps

- [Configure sensors and thresholds](02-configuration.md)
- [Understand the control sequence](03-how-it-works.md)
- [Diagnose problems](04-troubleshooting.md)

[← README](../README.md) · [Installation](01-installation.md) · [Configuration](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md) · [Inverter compatibility](05-inverter-compatibility.md)
