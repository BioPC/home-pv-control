# Installation

[← README](../README.md) · [Installation](01-installation.md) · [Settings](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md)

Home PV Control can run independently or alongside Home Battery Control. It does not modify HBC files.

## Requirements

- Home Assistant
- Node-RED with the Home Assistant nodes installed
- At least one writable PV inverter power-limit entity exposed as a Home Assistant `number` entity
- ApexCharts Card for the supplied dashboard graphs
- The standard Home Assistant `sun.sun` entity is recommended; HPVC falls back to the configured night-PV threshold when it is unavailable
- Home Battery Control only for HBC strategy control and HBC-assisted Hidden PV Reveal

## Upgrade from v1.2.0 or earlier

Version 1.3.0 renames active legacy helper entity IDs from `pv_ems_*` to `hpvc_*`. Upgrade the Home Assistant package, Node-RED flow, and dashboard together:

1. Replace [`home assistant/hpvc_config.yaml`](../home%20assistant/hpvc_config.yaml).
2. Import and replace the existing flow with [`node-red/hpvc_flow.json`](../node-red/hpvc_flow.json).
3. Replace or re-import [`home assistant/hpvc_dashboard.yaml`](../home%20assistant/hpvc_dashboard.yaml).
4. Reload packages or restart Home Assistant, then deploy Node-RED.
5. Copy or re-enter your sensor entities, inverter entities, limits, thresholds, and strategy selections in the new `hpvc_*` helpers.

Do not mix v1.3.0 files with older runtime files. Home Assistant may keep obsolete `pv_ems_*` helpers visible until their old package definitions are removed and Home Assistant is restarted.

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

## Step 3 — Add the dashboard

Install **ApexCharts Card** through HACS, then add [`home assistant/hpvc_dashboard.yaml`](../home%20assistant/hpvc_dashboard.yaml) as a separate YAML dashboard or view.

Do not paste it into your existing HBC dashboard unless you intentionally want to combine them.

## Step 4 — Configure entities

Open **Settings** in PV Master Control and configure:

- Grid power sensor
- Market/export price sensor
- All-in import price sensor
- Total PV power sensor
- One or more writable inverter-limit entities
- Optional HBC strategy entity

See [Settings](02-configuration.md) for sign conventions, thresholds, and inverter limits.

## Step 5 — Start with the shipped defaults

Review these starting values before enabling control:

| Setting | Shipped default |
|---|---:|
| PV limiting price | `0.00 €/kWh` |
| Export start | `-150 W` |
| Target export | `-25 W` |
| Import restore | `150 W` |
| Min PV for control | `100 W` |
| Cooldown | `60 s` |
| Deadband | `25 W` |

> **PV limiting price guidance:** Use €0.00/kWh with a net export-price sensor. For a raw market-price sensor, adjust for fees, compensation, and local rules.

## Step 6 — Verify installation

Confirm that:

- The dashboard loads without missing-card errors.
- Configuration status reports as valid.
- HPVC can be enabled.
- No **Configuration error** Insight appears.
- Each configured inverter-limit entity responds to a safe test.
- Generate report changes to View report after publication completes.

Continue with [Troubleshooting](04-troubleshooting.md) when any check fails.

## Next steps

- [Configure sensors and thresholds](02-configuration.md)
- [Understand the control sequence](03-how-it-works.md)
- [Diagnose problems](04-troubleshooting.md)


[← README](../README.md) · [Installation](01-installation.md) · [Settings](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md)
