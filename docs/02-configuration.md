[← README](../README.md) · [Installation](01-installation.md) · [Settings](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md) · [Inverter compatibility](05-inverter-compatibility.md)

# Settings

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

Each inverter requires a **Control method** plus its common power limits:

- **Control method** — `Number entity` for a writable Home Assistant `number.*`, or `Action/service` for an integration action/register-write path.
- **Limit unit** — `Watts` when the control value is power in W, or `Percent` when it uses a 0–100% active-power limit.
- **Full power** — normal maximum inverter power in watts.
- **Minimum power** — lowest power HPVC may request, always configured in watts. It must be zero or positive and lower than Full power.
- **Limit entity** — required only for `Number entity` control. Action/service fields are described below.

See [Inverter compatibility](05-inverter-compatibility.md) before selecting an entity for an untested inverter brand/integration.

HPVC always calculates plant and inverter targets internally in watts. With **Limit unit = Percent**, only the Home Assistant I/O boundary is converted: `target % = target W / Full power W × 100`. The live percentage state is converted back to watts before allocation, deadband and write-verification logic. This allows percentage-controlled integrations to use the same HPVC control model without changing thresholds or proportional distribution.

The writable number entity is also used as the command-state readback for write verification. In **Number entity** mode, HPVC v1.5.1 does not require a separate physical inverter-feedback sensor. If **Limit unit** is missing, unavailable, or not exactly `Watts` or `Percent`, configuration is treated as invalid and inverter writes are blocked rather than silently assuming Watts. For percentage entities, HPVC uses the Home Assistant `number` entity's `step` attribute when available, rounds commands to that supported percentage resolution, and verifies the effective Watt equivalent. If an integration does not expose a writable percentage `number` entity directly, use the v1.5.0 **Action/service** control method when the integration exposes a stable action/register-write path. A template/bridge number remains an alternative when preferred. A bridge that mirrors its requested value provides command-state confirmation only; it is not independent proof that the physical inverter accepted the underlying service/register write.

Invalid inverter limits or a percentage entity reporting outside 0–100% block writes and produce a configuration error.

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
| PV1–PV10 limit unit | `Watts` |
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
- active inverter count;
- all per-inverter control-path settings, including Control method, Limit entity, Limit unit, Maximum/Minimum power, Action/service, Value field, fixed/target JSON, Action Step, Refresh interval, pre/post actions, and readback entity;
- the current HBC Strategy Control on/off state.

It resets **Force charge at negative price** to its shipped default of **On**. The setting is also seeded **On** once on a fresh install or when first introduced by an upgrade. After that, a manual Off choice survives normal restarts and reloads. This does not grant HBC control by itself; **Enable HBC** remains the master permission and is preserved.

It does not populate installation-specific sensor or inverter entities. Verify all entities, maximum and minimum powers, inverter count, and optional HBC strategy entity afterward.

### Percentage step handling (v1.4.3)

For `Limit unit: Percent`, HPVC quantizes the requested Watt target to the writable `number.*` entity's advertised percentage `step` before deciding whether a write is required. The configured minimum remains a hard Watt floor: if nearest-step rounding would fall below it, HPVC uses the first supported percentage at or above the minimum.

## Inverter control method (v1.5.0)

Each inverter has its own **Control method**.

### Number entity

Use this for integrations that expose a writable Home Assistant `number.*` active-power limit. This is the existing HPVC path and remains the default. Configure **Limit entity**, **Limit unit**, **Max power**, and **Min power**.

### Action/service

Use this when the integration exposes a Home Assistant action/service or register-write action instead of a writable limit number. Configure:

- **Action/service** — `domain.service`, for example an integration-specific write action.
- **Value field** — the field inside the service data that receives HPVC's dynamic target (default `value`; dotted paths are supported).
- **Fixed data JSON** — constant service data such as hub, device, register or address.
- **Target JSON** — optional Home Assistant target object for the main action, such as an `entity_id`.
- **Action step** — command resolution in the selected Limit unit. Leave it at `0` unless the integration documents a required resolution; `0` uses HPVC's default step of `1` in the selected unit. In **Percent** mode, a positive Action step must be `≤ 100`. In **Watts** mode, it must be `≤ Maximum power` for that inverter. The dashboard keeps the compact `Action step (0=auto)` label for mobile; the unit-specific limits are documented here, and HPVC marks the configuration invalid instead of silently clamping an out-of-range value. Examples: `100` W, `0.1%`, or `1%`. HPVC quantizes the effective target before change detection so representable commands are not repeatedly resent.
- **Refresh seconds** — optional command heartbeat interval. Leave it at `0` unless the integration requires periodic re-sending; `0` disables periodic refresh. Valid helper range is `0–3600 s`. When due, the refresh bypasses the stable-input skip and is sent on the next HPVC timer cycle (normally within about 10 seconds of the configured interval).
- **Pre-actions JSON** — optional calls executed sequentially before the main write. The next step starts only after the previous Home Assistant action completes successfully.
- **Post-actions JSON** — optional calls executed sequentially after the main write. Any action failure stops the remaining sequence.
- **Readback entity** — optional numeric entity used to verify and track the applied command.
- **Limit unit** — still `Watts` or `Percent`; all HPVC control calculations remain in Watts.

Pre/post JSON is an array of objects with `action`, and optional `data` and `target`. Values can use the tokens `{{value}}`, `{{target_watts}}`, `{{desired_watts}}`, `{{percent}}`, `{{maximum_watts}}`, `{{minimum_watts}}`, and `{{slot}}`.

Example shape:

```json
[{"action":"switch.turn_on","target":{"entity_id":"switch.example_power_control"}}]
```

The optional readback entity must report the applied limit in the **same unit selected by Limit unit**. If an integration reports command output in a different unit, normalize it with a template sensor or leave readback empty; otherwise HPVC verification would compare incompatible units. Pre-actions, the main action and post-actions are executed sequentially and stop on the first failed Home Assistant action. HPVC does not insert an inter-step delay; if an integration requires a timed pause, wrap that device-specific sequence in a Home Assistant script and call the script from the adapter. Advanced JSON helpers are Home Assistant `input_text` states and therefore have a 255-character limit; use a script for larger payloads or sequences.

The adapter settings are normal Home Assistant helpers and persist across restarts. For Action/service adapters, a real numeric readback is also what allows the Daily Control Accuracy physical-event detector to attribute inverter-limit movement. Without readback, the headline accuracy and target-tracking metrics still run, but physical cause attribution is intentionally withheld rather than inferred from the command cache. If no readback entity is configured, HPVC uses the last commanded Watt value as runtime command state. After a fresh Node-RED context start (or after changing a slot from Number entity to Action/service), HPVC performs one initial synchronization write with the currently calculated target before relying on that command-state cache. If there is no readback, that synchronization write may replace a limit that was applied externally while HPVC was offline; if the current HPVC target is full power, it may intentionally restore full power. Configure a real readback where available, or keep HPVC disabled until the desired startup target is known. This is **not physical inverter verification**. Use a real readback entity whenever the integration provides one.

> **Upgrade note — sensor → binary_sensor migration:** v1.5.0 corrects several HPVC helper domains (`hpvc_show_inverter_slot_2`…`_10`, inverter limit-range warnings and the export-threshold warning) from `sensor.*` to `binary_sensor.*`. If an earlier installed package created the old `sensor.*` registry entries, Home Assistant may leave those old entities orphaned. They can be removed from the entity registry after confirming the new `binary_sensor.*` entities are present.


## Optional diagnostic compatibility sensors

The package intentionally retains these nine schema-11 diagnostic sensors even though the supplied dashboard and control flow read the compact diagnostics JSON directly:

- `sensor.hpvc_daily_band_excursions`
- `sensor.hpvc_daily_rms_control_error`
- `sensor.hpvc_daily_mae_control_error`
- `sensor.hpvc_daily_time_outside_target_deadband`
- `sensor.hpvc_deadband_exceedance_rms_mae_ratio`
- `sensor.hpvc_tracking_error_attribution_coverage`
- `sensor.hpvc_tracking_error_no_action_excluded`
- `sensor.hpvc_tracking_error_continuity_gap_excluded`
- `sensor.hpvc_tracking_error_factor_state`

They are retained for backward compatibility with v1.4.3 installations and for user automations, history cards, or external dashboards. Removing them from the package would leave existing installations with orphaned entity-registry entries. They are therefore **public diagnostic outputs**, not runtime dependencies.

`default_entity_id` is used only for `sensor.hpvc_diag_market_export_price` because that entity was renamed in v1.3.0 and the explicit default preserves the intended fresh-install entity ID. The remaining template sensors derive their default entity IDs from their names and `unique_id` values.

## Next steps

- [Understand the control sequence](03-how-it-works.md)
- [Troubleshoot unexpected behavior](04-troubleshooting.md)

[← README](../README.md) · [Installation](01-installation.md) · [Settings](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md) · [Inverter compatibility](05-inverter-compatibility.md)


## External PV release interface (v1.5.1)

HPVC exposes a small Home Assistant handshake for companion controllers such as EV/forecast automations. It is generic and is not tied to any charger, forecast provider or external project.

- `input_boolean.hpvc_external_release_request`: set this **On** to ask HPVC to release HPVC-controlled PV curtailment at the next safe opportunity. This helper is intended primarily for automations/integrations and is not shown as a normal dashboard control.
- `binary_sensor.hpvc_external_release_active`: turns **On** only after HPVC considers the configured inverter limits restored to full and the normal PV-curtailment path is suspended for the request. The dashboard shows this sensor as a status badge only while active.

A requester must wait for `binary_sensor.hpvc_external_release_active = on` before assuming that PV has been handed over. Do not use `input_boolean.hpvc_enabled` as a release acknowledgement. When the request is switched Off, HPVC immediately returns to its normal evaluation path.

Mandatory negative-price/minimum protection, HBC override restoration, Night Restore and safety/fault states keep priority over an external release request. The normal PV cooldown is respected before a release write; there is no fixed 30-second success promise.

### Safe master disable

Switching `input_boolean.hpvc_enabled` Off no longer means “freeze the last HPVC limit”. When a usable inverter control path remains available, HPVC first restores configured inverter limits to full and restores any HPVC-owned negative-price HBC override, then settles into `Disabled`. The support report records the resulting runtime status and external-release state.
