# Settings

[← README](../README.md) · [Installation](01-installation.md) · [Settings](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md)

The Settings tab is always available and contains entity selection, inverter setup, control thresholds, optional HBC controls, and tuning options. Operational status, graphs, accuracy, and Insights remain on the Main tab.

The Main-tab **Daily Control Accuracy** score grades excursions outside **Export Start…Import Restore**. Its four loss factors—**Control response**, **House load changes**, **PV availability**, and **Other**—split the displayed headline loss (`100 − accuracy`). Use the support report for detailed RMS/MAE, raw attribution, coverage, and exclusion diagnostics. Legacy accuracy entity IDs are retained for compatibility.


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


### All-in import price sensor

Used for negative-price protection. At a valid all-in price `<= 0`, HPVC holds every configured inverter at its own minimum. If **Enable HBC** and **Force charge at negative price** are both on, HPVC may also force HBC to `Charge` with charge goal `batteries are full`. When the price becomes `> 0`, or either HBC permission is turned off, HPVC restores the saved charge goal and then the saved strategy. Without HBC permission, negative-price protection remains PV-only. No all-in-price hysteresis is used.

### Total PV power sensor

Current total PV production in watts.

### HBC integration

The dashboard exposes HBC's native strategy selector and reads `input_text.house_battery_strategy_active_sub_strategy` as the executing sub-strategy. **Enable HBC** is the master permission for HBC execution tracking, Charge Priority, and any HPVC HBC write. During normal operation HPVC does not select HBC strategies; the only automatic strategy write is the optional negative-price charging override.

## PV inverter setup

Each inverter requires:

- **Limit entity** — writable Home Assistant `number` entity used to set the inverter limit.
- **Full power** — normal maximum limit in watts.
- **Minimum power** — lowest value HPVC may request. It must be zero or positive and lower than Full power.

Invalid inverter limits block writes and produce a configuration error.

## Control relationships

HPVC requires:

- `Export Start < Target Export < Import Restore`
- `Export Start` range: `-5000 to 0 W`
- `Target Export` range: `-5000 to +500 W`
- `Import Restore >= 0 W`

Invalid combinations block inverter writes. Home Assistant and Node-RED also enforce the declared numeric helper ranges, so an out-of-range restored or injected helper state is treated as invalid even if it bypasses the normal dashboard control. A gap of roughly `75–100 W` between Export Start and Target Export is a practical starting point for smooth control.

### Min PV for control

Blocks new export-limiting actions when measured PV production is already low. It does not block Import Restore or HBC battery charge priority.

### Cooldown

Minimum time between inverter writes. The allowed range is 10–60 seconds in 5-second steps. The shipped and Restore Defaults value is 30 seconds. HPVC continues its 10-second evaluation cycle during cooldown but sends no new limit command.

### Deadband

Minimum requested combined plant-power change before HPVC writes a new target. Once the total change reaches the deadband, proportional per-inverter shares may be smaller than the deadband and are still retained.

## Shipped defaults

These values are safe starting points, not universal recommendations. Review them for your inverter, sensor definitions, electricity contract, and local rules.

| Setting | Shipped default |
|---|---:|
| Home PV Control Enabled | Off until setup is complete |
| Notifications | On |
| HBC integration / Charge Priority | Off |
| Force charge at negative price | On by default; effective only when HBC integration is enabled |
| Number of PV Inverters | 1 |
| PV limiting price | `0.00 €/kWh` |
| PV price exit hysteresis | `0.02 €/kWh` |
| Export start | `-150 W` |
| Target export | `0 W` |
| Import restore | `150 W` |
| Min PV for control | `100 W` |
| Night restore PV threshold | `10 W` |
| Cooldown | `30 s` |
| Deadband | `25 W` |
| PV1–PV10 full limit | `0 W` until configured |
| PV1–PV10 minimum limit | `0 W` until configured |

Night Restore enters after 120 continuous seconds at or below the configured threshold. It exits only after valid PV remains above `max(25 W, threshold + 15 W)` for 30 seconds. See [How it works](03-how-it-works.md#restore-and-recovery) for restart and offline-telemetry behavior.

HPVC uses HBC's own strategy selector rather than separate HPVC strategy helpers. **Enable HBC** is the master permission. If it is turned off during an active negative-price override, HPVC performs only the confirmed restore sequence and then stops HBC writes. PV-minimum protection at negative prices remains independent, so HBC-disabled operation stays safe and PV-only.


## HBC battery charge priority

When HBC is enabled and its active sub-strategy is `Charge` or `Charge PV`, that executing sub-strategy is the start signal for Charge Priority. If at least one usable battery has known useful headroom, HPVC suspends normal price-based PV limiting and releases PV in bounded steps; it does not wait for the battery-power sensor to show charging first. From 90% to 100%, HPVC uses controlled taper-aware increases and learns each battery's accepted power separately in five SOC bands (90–92, 92–94, 94–96, 96–98, and 98–100%).

### Exact battery entity names

For each configured battery `N`, HPVC expects:

- `sensor.marstek_mN_ac_power`
- `sensor.marstek_mN_battery_state_of_charge`
- `number.marstek_mN_max_charge_power`
- `select.marstek_mN_rs485_control_mode`

Set the battery count with `input_number.house_battery_count` (0–6, whole numbers only). Each battery is evaluated independently; invalid, full, maximum-power, or RS485-disabled batteries are excluded without blocking healthy batteries. When available, HPVC also validates HBC's prioritized-battery setting and follows that priority order. A last known positive maximum charge power may bridge a genuinely unavailable helper for up to 30 minutes, but malformed, zero, or negative live values are never replaced by memory.


### Charge Priority states and state entity

The report and Insights use these presentation states:

- **Off** — Charge Priority is not applicable, disabled, outside the normal PV-limiting price zone, or no eligible charging request is active. A battery can be excluded for being full, unavailable, RS485-disabled, or otherwise ineligible.
- **Requested** — HBC requests Charge/Charge PV, but usable-battery eligibility is unresolved because required battery telemetry is unavailable or uncertain.
- **Waiting** — HBC requests `Charge` or `Charge PV` and usable headroom exists, but measured charging is not yet confirmed or no usable PV increase can currently be applied.
- **Active** — HPVC is preserving or releasing PV for confirmed battery charging headroom.

Charge Priority can remain **Active** while charging is still confirmed even after usable battery headroom reaches zero. In that condition HPVC no longer suppresses normal export limiting, so ordinary PV control resumes while the batteries continue charging at their current ceiling.

`binary_sensor.hpvc_charge_priority_active` is on only while HPVC has confirmed the **Active** state. It can be used in dashboards and history graphs. During this state, new export-based PV reductions are blocked, although `binary_sensor.hpvc_pv_limited` may remain on temporarily while previously reduced limits are being raised.

### Negative all-in-price override

PV-minimum protection does **not** require HBC. At a valid all-in price `<= 0`, HPVC holds each inverter at its configured minimum and releases the PV-only lock when the price becomes valid and `> 0`.

When **Enable HBC** and **Force charge at negative price** are both on, and the native HBC strategy and charge-goal entities exist, HPVC additionally:

1. saves the current HBC strategy and charge goal;
2. confirms strategy `Charge`;
3. confirms charge goal `batteries are full`;
4. restores the saved charge goal and then the saved strategy on exit.

The restore sequence also starts if either HBC permission is turned off. The override is persisted in `/config/hpvc-data/runtime-history.json` so a restart cannot lose the original values. If an entry or restore phase remains unconfirmed for five minutes, `input_boolean.hpvc_negative_override_fault` and a persistent notification identify the stuck phase.

## Restore defaults

The **Restore defaults** tile reapplies shipped configurable values after confirmation. It preserves:

- configured sensor entity IDs;
- inverter limit entity selections;
- active inverter count;
- the current HBC Strategy Control on/off state.

It resets **Force charge at negative price** to its shipped default of **On**. The setting is also seeded **On** once on a fresh install or when first introduced by an upgrade. After that, a manual Off choice survives normal restarts and reloads. This does not grant HBC control by itself; **Enable HBC** remains the master permission and is preserved.

It does not populate installation-specific sensor or inverter entities. Verify all entities, maximum and minimum powers, inverter count, and optional HBC strategy entity afterward.

## Next steps

- [Understand the control sequence](03-how-it-works.md)
- [Troubleshoot unexpected behavior](04-troubleshooting.md)

[← README](../README.md) · [Installation](01-installation.md) · [Settings](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md)
