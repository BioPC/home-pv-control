[← README](../README.md) · [Installation](01-installation.md) · [Configuration](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md) · [Inverter compatibility](05-inverter-compatibility.md)

# Configuration

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

### Inverter status and permission

Each PV controller window shows a derived status. No additional Home Assistant status entities or helpers are required. The existing `sensor.hpvc_effective_inverter_runtime` exposes `controller_ui_json` alongside its unchanged runtime map, using the same registry/device-based Enphase/OpenDTU discovery and effective slot assignment. Auto-detected OpenDTU/Hoymiles and Enphase slots identify the brand in the dashboard status as **Hoymiles detected** or **Enphase detected** while the internal runtime status remains `Detected`. When an entity/controller is present but its configuration is incomplete, the dashboard preserves that context as **Hoymiles detected but incomplete**, **Enphase detected but incomplete**, or **Detected but incomplete** for manual controllers; the internal runtime status remains `Incomplete`.

| Configuration | Display | HPVC Control |
| --- | --- | --- |
| Valid Number/OpenDTU or complete Enphase DPEL controller | Green **Detected** | Available |
| Valid Action/service configuration | Green **Configured** | Available |
| Detected/present controller with partial or invalid configuration | Amber **Detected but incomplete** (brand-prefixed for auto Hoymiles/Enphase) | Hidden |
| Valid controller with unavailable live states | **Unavailable** | Available; permission preserved |
| Counted but unfilled manual slot | Amber **Not configured** | Hidden |

Status checks include power ranges, units, entity existence, native number ranges, Action/service name syntax and JSON fields, and Enphase enable/mode pairing. Status is configuration and live-state feedback; the normal runtime freshness, validation and write-verification gates still decide whether a command is safe. Action/service readback remains optional: without it, Configured describes the existing command-cache mode and does not claim independent verification. Service execution errors remain subject to runtime safety handling.

This registry-clean package already uses `switch.hpvc_pvN_control`, backed by `input_boolean.hpvc_pvN_control_disabled` (N=1…10). Those names and persistent values are preserved; no `control_enabled` replacements are introduced. An invalid or empty slot makes the existing template switch unavailable, hiding its dashboard row without resetting its saved permission. A valid controller's communication outage does not make this permission switch unavailable.

With Insights enabled, an observed ON→OFF permission transition reports controller exclusion, or monitoring-only mode when every configured controller is excluded. OFF→ON reports the controller's return to control. Unchanged 10-second evaluations produce no repeated permission Insights. Initial observation and controller replacement establish a baseline; changes while Insights is disabled are not replayed when it is enabled. An outage is not a permission change. Switching control off preserves the last limit and does not bypass the existing verified full-output requirements for update, removal or uninstall.

Manual inverter slots require a **Control method** plus their common power limits. Native Enphase DPEL controllers and supported OpenDTU/Hoymiles absolute-Watt limiters are exceptions: HPVC can discover them automatically and assign them to the effective runtime slot map without requiring a placeholder entity.

For manually configured slots:

- **Control method** — `Number entity` for a writable Home Assistant `number.*`, or `Action/service` for an integration action/register-write path.
- **Limit unit** — `Watts` when the control value is power in W, or `Percent` when it uses a 0–100% active-power limit.
- **Full Limit / full power** — normal maximum inverter power in watts. For auto-detected OpenDTU/Hoymiles controllers, HPVC prefers confirmed OpenDTU `max_power`; if unavailable, enter the effective slot's Full Limit manually.
- **Minimum power** — lowest power HPVC may request, always configured in watts. It must be zero or positive and lower than Full power.
- **Limit entity** — required only for `Number entity` control. Action/service fields are described below.

See [Inverter compatibility](05-inverter-compatibility.md) before selecting an entity for an untested inverter brand/integration.

HPVC always calculates plant and inverter targets internally in watts. With **Limit unit = Percent**, only the Home Assistant I/O boundary is converted: `target % = target W / Full power W × 100`. The live percentage state is converted back to watts before allocation, deadband and write-verification logic. This allows percentage-controlled integrations to use the same HPVC control model without changing thresholds or proportional distribution.

The writable number entity is also used as the command-state readback for write verification. In **Number entity** mode, HPVC does not require a separate physical inverter-feedback sensor. If **Limit unit** is missing, unavailable, or not exactly `Watts` or `Percent`, configuration is treated as invalid and inverter writes are blocked rather than silently assuming Watts. For percentage entities, HPVC uses the Home Assistant `number` entity's `step` attribute when available, rounds commands to that supported percentage resolution, and verifies the effective Watt equivalent. If an integration does not expose a writable percentage `number` entity directly, use the v1.5.0 **Action/service** control method when the integration exposes a stable action/register-write path. A template/bridge number remains an alternative when preferred. A bridge that mirrors its requested value provides command-state confirmation only; it is not independent proof that the physical inverter accepted the underlying service/register write.

A slot-local invalid inverter configuration is excluded from allocation and reported while another valid inverter can continue degraded control. If every configured slot is invalid, control stops with a configuration error. Shared/ambiguous faults such as duplicate physical Number targets remain plant-wide blocking. A percentage entity reporting outside 0–100% is treated as a slot-local invalid configuration.

### Inverter total and manual slots

Above the **Inverters** +/− control, the settings show one line such as **Total inverters:** _2 auto-detected · 0 manual_. The breakdown comes from the effective runtime slot map, so values mirrored into the visible configuration fields do not reclassify an auto-detected controller as manual. Each controller uses one of the ten shared slots.

Automatic controllers reuse otherwise empty manual slots first, then occupy additional slots. The visible **Inverters** control has a dynamic minimum equal to the number of currently auto-detected controllers and a maximum of ten. With two auto-detected controllers it therefore cannot be reduced below 2; `+` can still increase capacity for additional manual controllers. If auto-detection later falls, the minimum falls with it without deleting existing manual configuration. Switching HPVC Control off changes control permission only and does not remove the controller from this floor or the effective total.

PV navigation and actual-limit rows use the effective runtime total, so the left/right selector cannot expose a slot beyond the real controller count.

### Duplicate controller assignments

Entering the same Number limit entity in another slot marks the later assignment **Incomplete — Limit entity already assigned to PVN** and hides that slot's control toggle. The original slot keeps its normal detection/availability display. Matching uses normalized entity IDs, not friendly names. Identical service names or shared readback entities alone do not prove that Action/service adapters target the same device.

The original assignment is selected using the limit fields' Home Assistant change timestamps. Equal or missing timestamps fall back to the lowest slot number; timestamps may reset after a Home Assistant restart. No persistent status helper is introduced. The existing runtime safety gate still blocks duplicate physical Number targets until the conflict is removed, even though only the later slot displays the duplicate alert. Clear or replace the duplicated entity to resolve it.

### Inverter navigation

The Settings dashboard shows one effective controller slot at a time. Manual Number/Action-service slots and supported auto-detected Enphase DPEL/OpenDTU-Hoymiles controllers share the same ten-slot runtime map. For auto-detected controllers HPVC mirrors the active control method, Limit entity and unit into the existing visible configuration fields while keeping the runtime source explicitly auto-detected. Enphase Max power and Min power remain user-owned manual settings. For auto-detected controllers, **Control method, Limit entity and Limit unit are read-only**. For **Enphase**, **Max power and Min power are always editable/manual** and must describe the actual installation range; HPVC never treats the DPEL Number entity min/max as rated power. For **OpenDTU/Hoymiles**, Max power is read-only when HPVC has a trusted API/cached maximum and otherwise remains editable/required; Min power remains editable. Manual Number controllers keep the normal editable fields. The dashboard navigation follows `sensor.hpvc_effective_inverter_runtime`, wraps at the first/last effective slot, and uses `input_select.hpvc_selected_inverter`; it does not change runtime allocation. If the effective count shrinks below the selected PV, `automation.hpvc_keep_selected_inverter_in_range` clamps the selection to the highest remaining slot.

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
| Enable Insights | Off |
| HBC integration / Charge Priority | Off |
| Force charge at negative price | On by default; effective only when HBC integration is enabled |
| Number of PV Inverters | 0 |
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

When no manual inverter capacity is configured and no Enphase/OpenDTU controller is auto-detected, **Inverters** is `0`. Settings hides the PV slot configuration and keeps the normal **Inverters** counter row visible at `0`; the minus button is unavailable at the current minimum and `+` creates a manual slot. The Main tab shows **No PV inverters available**. Zero is a supported setup state, but HPVC requires at least one usable inverter to operate, so the existing required-input safety automation keeps the master control OFF. Monitoring/dashboard diagnostics can still be viewed. Auto-detection raises the effective inverter count automatically; pressing `+` creates a manual slot.

Night Restore enters after 120 continuous seconds at or below the configured threshold. It exits only after valid PV remains above `max(25 W, threshold + 15 W)` for 30 seconds. See [How it works](03-how-it-works.md#restore-and-recovery) for restart and offline-telemetry behavior.

HPVC uses HBC's own strategy selector rather than separate HPVC strategy helpers. **Enable HBC** is the master permission. If it is turned off during an active negative-price override, HPVC performs only the confirmed restore sequence and then stops HBC writes. PV-minimum protection at negative prices remains independent, so HBC-disabled operation stays safe and PV-only.


### Enable Insights

`input_boolean.hpvc_insights_enabled` controls optional analytics and reporting work. It defaults to **Off**. When turned **Off**, HPVC hides the 10-Insights dashboard section and report controls and stops optional Insight/history/report background processing and non-essential diagnostic aggregation. Daily Control Accuracy and all core PV-control, HBC, safety, notification, update/recovery, and essential persistence paths continue to run.

## Restore defaults

The **Restore defaults** tile reapplies shipped configurable values after confirmation. It preserves:

- configured sensor entity IDs;
- active inverter count;
- all per-inverter control-path settings, including Control method, Limit entity, Limit unit, Maximum/Minimum power, Action/service, Value field, fixed/target JSON, Action Step, Refresh interval, pre/post actions, and readback entity;
- the current HBC Strategy Control on/off state.

It resets **Force charge at negative price** to its shipped default of **On**. The setting is also seeded **On** once on a fresh install or when first introduced by an upgrade. After that, a manual Off choice survives normal restarts and reloads. This does not grant HBC control by itself; **Enable HBC** remains the master permission and is preserved.

It does not populate installation-specific sensor or inverter entities. Verify all entities, maximum and minimum powers, inverter count, and optional HBC strategy entity afterward.

## HBC battery charge priority

When HBC is enabled and its active sub-strategy is `Charge` or `Charge PV`, that executing sub-strategy is the start signal for Charge Priority. If at least one usable battery has known useful headroom, HPVC suspends normal price-based PV limiting and releases PV in bounded steps; it does not wait for the battery-power sensor to show charging first. From 90% to 100%, HPVC uses controlled taper-aware increases and learns each battery's accepted power separately in five SOC bands (90–92, 92–94, 94–96, 96–98, and 98–100%).

### Exact battery entity names

These battery entities and `input_number.house_battery_count` are **not created or owned by HPVC**. They must already be provided by HBC and the configured battery integration, and they are required only when HBC control / Charge Priority is used. Standalone HPVC operation does not require them.

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

## Inverter control method

Each inverter has its own **Control method**.

### OpenDTU / Hoymiles auto-detection

When OpenDTU is connected to Home Assistant through MQTT with **Home Assistant MQTT Auto Discovery** enabled, HPVC can discover Hoymiles inverter devices automatically. The preferred control entity is the inverter's writable **non-persistent absolute limit** in watts. HPVC reads the Home Assistant entity registry and device registry on the independent 60-second discovery path, identifies the original `limit_nonpersistent_absolute` role on an MQTT/OpenDTU/Hoymiles device, and registers that inverter as one normal Number-entity controller.

Renaming the entity in Home Assistant does not break registry-based discovery because pairing uses the HA `device_id` plus original/immutable entity metadata. If registry metadata is unavailable, HPVC retains a conservative fallback for an entity whose ID ends in `_limit_nonpersistent_absolute`, whose native unit is watts, and whose native maximum is positive. Relative and persistent limit controls are not auto-selected.

Each detected OpenDTU inverter consumes one of the shared maximum ten effective controller slots. Empty Number slots are reused first; additional controllers are appended only while capacity remains. If the same limit number is already configured manually, HPVC deduplicates it and normalizes the runtime adapter to native Watt min/max/step semantics.

For the effective **Full/Max power**, HPVC prefers OpenDTU's read-only `/api/limit/status` `max_power` value when the DTU web API is reachable. The detected device `configuration_url` is used automatically and no API call is placed in the 10-second control loop. If OpenDTU requires authentication and guest read-only access is disabled, HPVC falls back to the last cached confirmed OpenDTU `max_power`, then the effective slot's manual **Full Limit**. The Home Assistant Number entity's native `max` is never treated as inverter rated power. If no trusted API/cache/manual value exists, the controller remains detected and visible as **Detected — Full Limit required** but is excluded from limiting until a valid Full Limit is entered. Smart Update, flow removal and full uninstall use this same rated-power precedence for their full-output verification; they do not substitute the HA Number `max`.

### Enphase DPEL auto-detection

When the **Enphase Envoy Installer** integration (recommended **0.10.2+**) exposes a complete DPEL set, HPVC detects it automatically. Do **not** create an `enphase` control method or type `enphase` into a slot. A valid set contains `number.envoy_*_dpel_limit`, `switch.envoy_*_dpel_enabled`, and `select.envoy_*_dpel_mode`, with both `Production` and `Export` present in the mode options.

The controller is represented internally as a Number-entity adapter in native Watts. Empty configured Number slots are reused before an Enphase controller is appended to the effective runtime list. If the same DPEL number is already configured manually, HPVC deduplicates it and normalizes control to native Watts/step/readback while preserving the slot's manually configured Max power and Min power. Each Envoy consumes one effective controller slot regardless of the number of microinverters behind it; the total manual + auto-detected controller count cannot exceed ten.

Before a DPEL limit write, HPVC requires the enable switch to report `on` and the mode to report `Production`. `unknown`/`unavailable` supporting states pause that controller without issuing corrective calls. `Export` mode is never used for HPVC's production-ceiling writes.

Each Envoy DPEL controller consumes one controller slot inside HPVC's existing maximum of ten. Manually configured `number.*`/OpenDTU slots continue to work normally. HPVC auto-detects the DPEL control entities but takes the operating **Max power** and **Min power** from the HPVC slot settings. It requires DPEL to be enabled and mode `Production` before it will send a Watt limit.

If `number.envoy_*_dpel_limit` was already entered manually in a slot, HPVC reuses that slot rather than creating a duplicate. Because the native DPEL Limit is always a Watt entity, HPVC normalizes that enriched slot to **Watts** at runtime and refreshes native step/readback capability metadata while preserving the manually configured HPVC Max/Min power. This also safely upgrades older/manual configurations that may still have `Percent` selected.

HPVC refreshes Home Assistant's supported WebSocket entity registry on startup and every 60 seconds, independently of the 10-second control timer. It pairs the DPEL Watt number, mode select and enable switch by their shared `device_id` (the HA device registry relationship), then uses integration `unique_id` role suffixes, `original_name`, `translation_key` or original entity role when available. Editable entity IDs are the last source of role evidence. The mode must advertise both `Production` and `Export`. A device with duplicate role candidates, disabled members or conflicting integration/config-entry identities is rejected; `production`, `pv_limit`, `pv_limit_enabled` and `pvlimit_pct` siblings cannot substitute for DPEL.

Renaming all three entity IDs is supported when original registry role metadata remains available. The official defaults `switch.envoy_*_dpel_enabled`, `number.envoy_*_dpel_limit` and `select.envoy_*_dpel_mode` remain supported. Legacy suffix pairing is used only when device registry information is unavailable for the triplet; it never overrides an authoritative registry rejection. Registry API failures retain the last successful mapping and retry on the next timer; a successful empty response clears removed controllers. Live state checks still gate every write.

The cached mapping is shared with HA templates by the `hpvc_enphase_registry_refreshed` event and `sensor.hpvc_enphase_registry`. Dashboard runtime slots, configuration validity, readiness and all three maintenance watchers use those same pairs. After installing the modified package and flow, reload the HA templates and deploy the flow; allow up to 60 seconds for renamed controllers to appear. Device IDs determine registry controller order, so entity renames do not reorder those controllers. Adding/removing devices or manual slots can change slot allocation; review the assigned slots and their control toggles after such changes.

Auto-detected controller values are mirrored into the existing PV slot fields while the runtime source remains auto-detected. Identity fields are read-only; Min power stays editable, and Max power is editable only when HPVC still needs a user-supplied trusted maximum.

### Per-controller HPVC Control

Each slot has an **HPVC Control** switch (`switch.hpvc_pv1_control` through `switch.hpvc_pv10_control`) in its dashboard settings. It defaults to On and persists across restarts using an inverse disabled helper. Off excludes that slot from HPVC allocation and stops new limit, DPEL preflight and automatic restore commands. It does not turn off solar production or change the DPEL enable switch, and it leaves the last physical limit in place. A service call already sent must finish; remaining queued steps are cancelled. Re-enable the slot to resume control. If every slot is off, no inverter commands are sent.

For restoration, leave HPVC Control on and disable the main HPVC switch first; wait for full-output confirmation before opting out. Maintenance still checks every configured/discovered controller, including opted-out slots, and blocks removal/update if full output cannot be verified. The ten-slot cap and manual/auto slot deduplication apply before opt-out, so switching off a slot does not move another controller into it.

### Number entity

Use this for integrations that expose a writable Home Assistant `number.*` active-power limit. This is the existing HPVC path and remains the default. Configure **Limit entity**, **Limit unit**, **Max power**, and **Min power**.

### Percentage step handling

For `Limit unit: Percent`, HPVC quantizes the requested Watt target to the writable `number.*` entity's advertised percentage `step` before deciding whether a write is required. The configured minimum remains a hard Watt floor: if nearest-step rounding would fall below it, HPVC uses the first supported percentage at or above the minimum.

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
- **Readback entity** — optional numeric entity used to verify and track the applied command during normal control. A valid numeric readback is required for automatic **Smart Update** and **Full uninstall** safe-limit verification in Action/service mode.
- **Limit unit** — still `Watts` or `Percent`; all HPVC control calculations remain in Watts.

Pre/post JSON is an array of objects with `action`, and optional `data` and `target`. Values can use the tokens `{{value}}`, `{{target_watts}}`, `{{desired_watts}}`, `{{percent}}`, `{{maximum_watts}}`, `{{minimum_watts}}`, and `{{slot}}`.

Example shape:

```json
[{"action":"switch.turn_on","target":{"entity_id":"switch.example_power_control"}}]
```


> **Maintenance safety:** Action/service adapters may run normal HPVC control without a readback, but automatic **Smart Update**, **Remove HPVC flows**, and **Full uninstall** require a valid numeric readback so HPVC can prove that the inverter has returned to its configured full limit before replacing or removing its configuration. The Maintenance dashboard now flags this before the action as **Maintenance verification unavailable**. If no usable readback is configured, those maintenance workflows stop safely and report the affected inverter instead of continuing destructively.

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

Every HPVC template entity now declares an explicit `default_entity_id`. This keeps fresh-install entity IDs deterministic, lets Smart Update identify newly introduced package entities without guessing from `unique_id`, and lets release validation prove exact uninstall ownership even if an existing registry entity has been renamed by the user.

## Update and uninstall persistence

Normal HPVC version updates preserve the current helper values when the same entity IDs are retained. Replacing the package, flow and dashboard is therefore different from uninstalling HPVC.

A **full uninstall** resets HPVC helpers to shipped/fresh-install values before their registry entries are removed, so a later reinstall does not restore stale configuration. **Restore defaults** remains the user-facing configuration reset and is separate from uninstall.

For the complete uninstall procedure and the files removed automatically, see [Installation → Full uninstall](01-installation.md#full-uninstall).

## Next steps

- [Understand the control sequence](03-how-it-works.md)
- [Troubleshoot unexpected behavior](04-troubleshooting.md)

[← README](../README.md) · [Installation](01-installation.md) · [Configuration](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md) · [Inverter compatibility](05-inverter-compatibility.md)
