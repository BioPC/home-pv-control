# Settings

[← README](../README.md) · [Installation](01-installation.md) · [Settings](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md)

The Settings tab contains entity selection, inverter setup, control thresholds, optional HBC controls, and tuning options. Operational status, graphs, accuracy, and Insights remain on the Main tab.

## Entity configuration

Entity helpers are plain `input_text` fields. Paste the complete Home Assistant entity ID; HPVC reports an invalid or empty field as a configuration error instead of guessing.

### Grid power sensor

Expected sign convention:

```text
negative = export
positive = import
```

Example: `sensor.p1_meter_power`

### Market/export price sensor

This sensor is used for PV limiting decisions. It may contain either a raw market price or the true net value of exported electricity.

> **PV limiting price guidance:** Use €0.00/kWh with a net export-price sensor. For a raw market-price sensor, adjust for fees, compensation, and local rules.

For HBC Price Zones, a raw market-price sensor gives the clearest Market → estimated all-in conversion. A net export-price sensor remains valid for PV limiting, but the graph may report the forecast type as uncertain when it cannot distinguish market and all-in values reliably.

### All-in import price sensor

Used only for optional HBC strategy switching and HBC price-zone conversion.

### Total PV power sensor

Current total PV production in watts.

### HBC strategy entity

Used only when **HBC Strategy Control** is enabled. Disable it when HPVC should control only PV inverter output.

## PV inverter setup

Each inverter requires:

- **Limit entity** — writable Home Assistant `number` entity used to set the inverter limit.
- **Full power** — normal maximum limit in watts.
- **Minimum power** — lowest value HPVC may request. It must be zero or positive and lower than Full power.

Invalid inverter limits block writes and produce a configuration error.

## Shipped defaults

These values are safe starting points, not universal recommendations. Review them for your inverter, sensor definitions, electricity contract, and local rules.

| Setting | Shipped default |
|---|---:|
| Home PV Control Enabled | On |
| Notifications | On |
| HBC Strategy Control | Off |
| Settings visibility | Off |
| Number of PV Inverters | 1 |
| PV limiting price | `0.00 €/kWh` |
| Battery charge all-in price | `0.10 €/kWh` |
| Expensive all-in price | `0.35 €/kWh` |
| Battery price hysteresis | `0.02 €/kWh` |
| Export start | `-150 W` |
| Target export | `-25 W` |
| Import restore | `150 W` |
| Min PV for control | `100 W` |
| Night restore PV fallback | `10 W` |
| Cooldown | `60 s` |
| Deadband | `25 W` |
| PV1–PV10 full limit | `0 W` until configured |
| PV1–PV10 minimum limit | `0 W` until configured |
| Charge strategy | Charge |
| Balanced strategy | Dynamic |
| Expensive strategy | Dynamic |

| Battery strategy entity | `input_select.house_battery_strategy` |

The Charge strategy is automatically managed and shown read-only in Settings. HPVC always uses `Charge` when that exact live HBC option exists. Balanced and Expensive remain user-selectable and mirror the live options from the configured HBC strategy entity; `Dynamic` is their preferred default when available. When HBC temporarily exposes no valid options—or the strategy entity is unavailable—HPVC preserves the selectors and the **Enable HBC** preference, pauses only HBC strategy control and battery-assisted reveal, and continues normal PV control. When HBC is not detected and **Enable HBC** is off, the periodic check skips option updates. Automatic detection still resumes within one minute when a valid option list appears.



## Control relationships

HPVC requires:

- `Export Start < Target Export <= 0 W`
- `Import Restore >= 0 W`

Invalid combinations block inverter writes. A gap of roughly `75–100 W` between Export Start and Target Export is a practical starting point for smooth control.

### Min PV for control

Blocks new export-limiting actions when measured PV production is already low. It does not block Import Restore or Hidden PV Reveal.

### Cooldown

Minimum time between inverter writes. HPVC continues evaluating during cooldown but sends no new limit command.

### Deadband

Minimum requested power change before HPVC writes a new target. Normal control applies it per inverter; Hidden PV Reveal applies it once to the total reveal request before preserving the proportional split.

## Hidden PV Reveal

Hidden PV Reveal uses Export Start, Target Export, Deadband, Cooldown, Min PV for control, battery charge power, SOC, and available charging headroom. No separate reveal threshold is required.

Reveal is allowed only after export has recovered to at least Export Start. This prevents HPVC from revealing more PV while export is still excessive.

## Runtime updates

The Node-RED flow evaluates every 15 seconds and once at startup. Changes to HPVC configuration helpers trigger an immediate reevaluation. Live grid, market, and PV sensor changes are picked up on the next cycle.

## Restore defaults

The **Restore defaults** tile reapplies shipped configurable values after confirmation. It preserves:

- configured sensor entity IDs;
- inverter limit entity selections;
- active inverter count;
- the current HBC Strategy Control on/off state.

It does not populate installation-specific sensor or inverter entities. Verify all entities, maximum and minimum powers, inverter count, and optional HBC strategy entity afterward.

## Restart persistence

User-configurable helpers intentionally omit `initial:` values so Home Assistant restores user changes after a restart. The transient report-ready and report-generating helpers use `initial: false` to prevent stale report states.

First-run defaults are applied only while `input_boolean.hpvc_defaults_applied` is off. Afterward, user changes are retained.

## Entity-name change in v1.3.0

All active helpers, template entities, dashboard references, and Node-RED references use the `hpvc_*` prefix. This is an entity-ID rename, not only a display-name change.

Examples:

- `input_boolean.pv_ems_enabled` → `input_boolean.hpvc_enabled`
- `input_text.pv_ems_grid_power_sensor` → `input_text.hpvc_grid_power_sensor`
- `input_number.pv_ems_export_start_threshold` → `input_number.hpvc_export_start_threshold`

Replace the package, flow, and dashboard together. Existing values in old helpers are not migrated automatically. See [Upgrade from v1.2.0 or earlier](01-installation.md#upgrade-from-v120-or-earlier).


[← README](../README.md) · [Installation](01-installation.md) · [Settings](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md)
