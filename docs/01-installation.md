# Installation

[← README](../README.md) · [Installation](01-installation.md) · [Settings](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md)

Home PV Control can run independently or alongside Home Battery Control. Use Steps 1–6 for a fresh installation. Existing installations should also read the upgrade section before replacing files.

## Requirements

- Home Assistant
- Node-RED with `node-red-contrib-home-assistant-websocket` version **0.80.3 or newer**
- At least one writable PV inverter power-limit entity exposed as a Home Assistant `number` entity
- ApexCharts Card for the supplied dashboard graphs

The supplied dashboard requires **ApexCharts Card**. It does not require card-mod, Button Card, or Config Template Card.
- The standard Home Assistant `sun.sun` entity is recommended as supporting Night Restore context. Valid PV power is authoritative; `sun.sun` is used only to corroborate a pending Night Restore transition if PV telemetry disappears after the low-PV timer has already started.
- Home Battery Control only for optional HBC execution tracking and multi-battery Charge Priority

## Step 1 — Install the Home Assistant package

Copy [`home assistant/hpvc_config.yaml`](../home%20assistant/hpvc_config.yaml) to:

```text
/config/packages/hpvc_config.yaml
```

Ensure packages are enabled in `configuration.yaml`:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

Reload supported YAML configuration where possible, or restart Home Assistant.

## Step 2 — Import the Node-RED flow

Import [`node-red/hpvc_flow.json`](../node-red/hpvc_flow.json), confirm that the Home Assistant server selected in the nodes is correct, and deploy the flow.

The flow imports as four tabs: **Inputs**, **Engine**, **Outputs**, and **Reports**. Import the complete flow rather than individual tabs so the control and report paths remain synchronized. See [How it works](03-how-it-works.md#node-red-flow-architecture) for the high-level layout.

## Step 3 — Add the dashboard

Install **ApexCharts Card** through HACS, then add [`home assistant/hpvc_dashboard.yaml`](../home%20assistant/hpvc_dashboard.yaml) as a separate YAML dashboard or view.

Do not paste it into your existing HBC dashboard unless you intentionally want to combine them.

## Step 4 — Configure entities

Open the **Settings** tab and configure:

- Grid power sensor
- Market/export price sensor
- All-in import price sensor
- Total PV power sensor
- One or more writable inverter-limit entities
- Optional HBC integration toggle; native HBC entities are detected automatically

See [Settings](02-configuration.md) for sign conventions, thresholds, and inverter limits.

## Step 5 — Start with the shipped defaults

Review these starting values during first-install setup. HPVC enables automatically once the required live inputs and control settings validate successfully:

| Setting | Shipped default |
|---|---:|
| HBC integration / Charge Priority | Off |
| Force charge at negative price | On by default; used only when HBC control is enabled |
| PV limiting price | `0.00 €/kWh` |
| Export start | `-150 W` |
| Target export | `0 W` |
| Import restore | `150 W` |
| Min PV for control | `100 W` |
| Cooldown | `30 s` |
| Deadband | `25 W` |

> **HBC permission:** **Enable HBC** is the master permission for HPVC to control charging in HBC. If it is turned off during an active negative-price override, only the confirmed restore sequence is allowed afterward. The negative-price charging switch is subordinate to it; with HBC disabled, negative prices still reduce PV to the configured inverter minimums but never change the HBC strategy.

> **PV limiting price guidance:** Use €0.00/kWh with a net export-price sensor. For a raw market-price sensor, adjust for fees, compensation, and local rules.

## Step 6 — Verify installation

Confirm that:

- The dashboard loads without missing-card errors.
- Configuration status reports as valid.
- HPVC can be enabled.
- No **Configuration error** Insight appears.
- Each configured inverter-limit entity responds to a safe verification.
- Generate report changes to View report after publication completes.

Continue with [Troubleshooting](04-troubleshooting.md) when any check fails.

## Upgrade from v1.2.0 or earlier

Version 1.3.0 renames active legacy helper entity IDs from `pv_ems_*` to `hpvc_*`. Upgrade the Home Assistant package, Node-RED flow, and dashboard together:

1. Replace [`home assistant/hpvc_config.yaml`](../home%20assistant/hpvc_config.yaml).
2. Import and replace the existing flow with [`node-red/hpvc_flow.json`](../node-red/hpvc_flow.json).
3. Replace or re-import [`home assistant/hpvc_dashboard.yaml`](../home%20assistant/hpvc_dashboard.yaml).
4. Review **Force charge at negative price**. HPVC seeds it **On** once on both fresh installations and upgrades. After that, a manual Off choice survives normal Home Assistant restarts and package/automation reloads. **Restore defaults** turns it On again.
5. Reload packages or restart Home Assistant, then deploy Node-RED.
6. Copy or re-enter your sensor entities, inverter entities, limits, thresholds, and HBC integration preference in the new `hpvc_*` helpers.

Do not mix v1.4.0 files with older runtime files. Home Assistant may keep obsolete `pv_ems_*` helpers visible until their old package definitions are removed and Home Assistant is restarted.

## Next steps

- [Configure sensors and thresholds](02-configuration.md)
- [Understand the control sequence](03-how-it-works.md)
- [Diagnose problems](04-troubleshooting.md)

[← README](../README.md) · [Installation](01-installation.md) · [Settings](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md)