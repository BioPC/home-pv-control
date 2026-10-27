[← README](../README.md) · [Installation](01-installation.md) · [Configuration](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md) · [Inverter compatibility](05-inverter-compatibility.md)

# Inverter compatibility

Home PV Control (HPVC) v1.6.0 controls inverter output through either a writable Home Assistant `number` entity or a configurable Home Assistant **Action/service** adapter. Limits can be expressed in **Watts** or **Percent**, while HPVC continues to calculate internally in Watts.

Compatibility depends on the **Home Assistant integration and the entities it exposes**, not only on the inverter brand or model. A writable grid-export limit is not automatically equivalent to an inverter active-power limit: HPVC expects to control the inverter production ceiling itself.

## Adapter model

The matrix below describes integration fit, not a guarantee for every model/firmware. Generic **Action/service** adapters allow integrations marked **Action/service adapter** to be configured directly when Home Assistant exposes a stable action/service schema. Complex integrations can also use optional pre/post action sequences. Hardware field confirmation is still required before promoting a brand to **Confirmed direct**.

## Compatibility status

| Status | Meaning |
|---|---|
| **Confirmed direct** | Tested with HPVC on real hardware using one of the supported control methods and confirmed to work. |
| **Compatible by design** | The integration exposes the kind of writable inverter active-power-limit entity HPVC requires, but that integration/model has not yet been field-tested with HPVC. |
| **Action/service adapter** | The integration does not expose a directly usable writable limit `number`, but it exposes a stable Home Assistant action/service or register-write path that can be configured in HPVC. |
| **Not confirmed / not suitable** | No verified HPVC-compatible inverter active-power-limit entity was found, or the available control is for a different purpose such as site/grid export limiting. |

## Compatibility matrix

| Brand / integration | Status | Why |
|---|---|---|
| **Hoymiles + OpenDTU** | **Confirmed direct — auto-detected absolute-Watt adapter** | With OpenDTU MQTT Auto Discovery enabled, HPVC can discover each inverter device through Home Assistant registry metadata and use its non-persistent absolute Watt limit as one controller slot. Manual Number-entity configuration remains supported. |
| **SolarEdge + home-assistant-solaredge-modbus** | **Compatible by design** | Exposes a writable active-power-limit `number` in percent, which maps directly to HPVC Percent mode. |
| **Fronius native Home Assistant** | **Compatible by design** | Exposes an AC power-limit `number` in percent. The related limit-enable switch must remain enabled. |
| **Deye + deye-modbus-ha** | **Compatible by design** | Exposes writable Active Power Regulation in percent with defined steps. |
| **SAJ R5 / Zonneplan ONE + saj-r5-modbus** | **Compatible by design** | Exposes a writable Limit Power percentage entity suitable for HPVC Percent mode. Command/readback semantics may depend on the integration and inverter restart behavior. |
| **APsystems ECU-R Pro / ECU-C** | **Compatible by design** | Exposes writable maximum-power controls that match HPVC's writable-number control model. |
| **Solis / Ginlong via ESPHome Modbus bridge** | **Compatible by design** | The bridge exposes inverter output limiting as a writable percentage `number`, which fits HPVC Percent mode. |
| **Sunsynk** | **Compatible by design** | Current integrations can expose a writable PV maximum-power limit suitable for HPVC; exact availability is model/integration dependent. |
| **Sungrow** | **Compatible by design** | Selected integrations expose active-power-limit ratio controls, but exact entity availability depends on model and integration. |
| **Growatt WIT + Growatt_ModbusTCP** | **Compatible by design** | WIT models can expose Active Power Rate as a writable number. HPVC field confirmation is still needed. |
| **Victron + hass-victron** | **Compatible by design** | A PV-inverter power-limit number can be available, depending on the Victron topology and attached inverter devices. |
| **Growatt MIN / MIN TL-XH + Growatt_ModbusTCP** | **Action/service adapter** | Active Power Rate is available at register level but is not exposed as a directly writable control entity for these models. |
| **Huawei SUN2000** | **Action/service adapter** | Power control is available through integration services/registers rather than a simple HPVC-compatible writable inverter-limit number. |
| **SMA native Home Assistant** | **Not confirmed / not suitable** | The native integration exposes inverter power limit as read-only telemetry rather than a writable active-power control. |
| **SMA via Home Assistant Modbus / custom register action** | **Action/service adapter** | Model-specific Modbus write configurations can expose a callable register-write path; the correct register mapping must be supplied for the specific inverter. |
| **Sofar** | **Not confirmed / not suitable** | Underlying libraries support active-power control on some models, but a stable Home Assistant action/service path has not been verified broadly enough to classify it as directly configurable. |
| **SolaX** | **Action/service adapter** | Some power-control modes require additional mode selection, trigger actions or autorepeat behavior beyond setting one number entity. |
| **GoodWe native Home Assistant** | **Not confirmed / not suitable** | The readily available writable control is primarily a site/grid export limit, not clearly the inverter production ceiling HPVC controls. |
| **FoxESS** | **Not confirmed / not suitable** | Verified writable controls are mainly grid import/export limits rather than a simple inverter-generation ceiling. |
| **Kostal Plenticore** | **Not confirmed / not suitable** | No consistently verified writable inverter active-power-limit entity suitable for HPVC was found. |
| **ABB / FIMER** | **Not confirmed / not suitable** | SunSpec/export-control support exists, but a generic directly usable HPVC inverter-output entity has not been verified. |
| **Enphase Envoy + Enphase Envoy Installer 0.10.2+** | **Compatible by design — auto-detected DPEL adapter** | The custom integration exposes `switch.envoy_*_dpel_enabled`, `number.envoy_*_dpel_limit` (W) and `select.envoy_*_dpel_mode` (`Production` / `Export`). HPVC auto-detects each complete DPEL triplet as one controller slot, keeps DPEL enabled, requires `Production` mode before a Watt write, and controls the native DPEL Limit through the normal Number-entity path. Enphase microinverters behind one Envoy do not consume individual HPVC slots. |
| **Qcells** | **Not confirmed / not suitable** | No verified generic HPVC-compatible inverter-output control was found. |
| **Delta** | **Not confirmed / not suitable** | Model-level Modbus control may exist, but no verified generic Home Assistant entity suitable for HPVC was found. |
| **KACO** | **Not confirmed / not suitable** | No verified directly usable HPVC inverter power-limit entity was found. |
| **Solplanet / AISWEI** | **Not confirmed / not suitable** | Monitoring support exists, but direct inverter-output control suitable for HPVC has not been verified. |
| **Sigenergy** | **Not confirmed / not suitable** | Advanced power controls exist, but a simple writable inverter active-power-limit `number` matching HPVC's current control model has not been verified. |

## OpenDTU / Hoymiles auto-detection

HPVC v1.6.0 can automatically discover Hoymiles inverter devices published by OpenDTU through Home Assistant MQTT Auto Discovery. The preferred automatic control is the writable **non-persistent absolute** limit in watts, corresponding to OpenDTU's `limit_nonpersistent_absolute` command semantics. HPVC prefers Home Assistant entity/device registry metadata so user-renamed entity IDs remain usable, and it verifies that the entity belongs to an MQTT/OpenDTU/Hoymiles device before registering it.

The automatic adapter uses the native Number-entity min/step and Watt state, counts one OpenDTU inverter device as one HPVC controller slot, reuses empty Number slots first, deduplicates a manually entered copy of the same number, and respects the existing ten-controller maximum. Rated/full power is preferably taken from OpenDTU `/api/limit/status` `max_power`, then from a cached confirmed API value. If neither is available, HPVC requires the effective slot's manual **Full Limit**. The Number entity's `max` is never used as rated power because OpenDTU may expose a control range above nominal inverter output. HPVC does **not** auto-select persistent absolute limits, relative/percentage limits, or inverter power on/off entities. Smart Update, flow removal and full uninstall use the same OpenDTU rated-power source order as runtime control, so maintenance never treats the Number entity's control-range `max` as the inverter nameplate rating.

When registry metadata is unavailable, HPVC accepts only the conservative official-style fallback `number.*_limit_nonpersistent_absolute` when the live entity reports a Watt unit and a positive native maximum. This fallback is intentionally narrower than registry-based discovery.

## Enphase DPEL auto-detection

HPVC v1.6.0 can automatically discover the DPEL entities exposed by **Enphase Envoy Installer 0.10.2 or newer**. No HPVC slot needs the word `enphase`, and no custom action/service adapter is required. A complete controller consists of:

- `switch.envoy_*_dpel_enabled`
- `number.envoy_*_dpel_limit`
- `select.envoy_*_dpel_mode`

A complete Envoy DPEL controller counts as **one** of HPVC's maximum ten effective controller slots. Auto-detection first fills reusable empty Number slots and then appends additional Envoys after the configured manual slots. If the same `number.*_dpel_limit` is already configured manually as a Number-entity slot, HPVC enriches that slot instead of creating a duplicate and normalizes it to native **Watt** command/readback semantics while preserving manually configured HPVC Max/Min power. This prevents an older/manual `Percent` selection from scaling a DPEL Watt command incorrectly. If all ten effective slots are already occupied, automatic Enphase attachment is blocked and reported as a configuration problem.

For safety, HPVC treats DPEL **Production** mode as the only valid mode for its production-ceiling algorithm. When DPEL is disabled or its mode is `Export`, HPVC first requests `Enabled + Production` and deliberately defers the Watt-limit write until the next control evaluation confirms those states. This prevents a failed mode change from interpreting an HPVC production target as an export limit. Once ready, HPVC writes the native DPEL Limit with `number.set_value` and uses that same local entity for command-state readback/verification.

## Adapter requirements

For **Number entity** control, the integration must expose a writable Home Assistant `number.*` representing the inverter active-power ceiling.

For **Action/service** control, the integration must expose a stable Home Assistant action/service schema that HPVC can call with a dynamic Watt or Percent value. Optional pre/post actions can enable control modes, select modes or trigger a command. Optional command refresh can provide a heartbeat.

A numeric readback entity is strongly recommended for normal control. For **Action/service** adapters it is required for automatic **Smart Update**, **Remove HPVC flows**, and **Full uninstall**, because those maintenance workflows must verify the live inverter limit at full before replacing or removing HPVC configuration. Without usable numeric readback, normal control can still use command-state tracking, but the Maintenance dashboard warns **Maintenance verification unavailable** and automatic maintenance stops safely rather than assuming physical restoration.

A site/grid **export limit** is not automatically equivalent to an inverter active-power limit. Use it only when the integration semantics match HPVC's intended production-ceiling control.

## Readback and verification

In **Number entity** mode HPVC verifies the configured writable limit entity. In **Action/service** mode HPVC verifies the configured readback entity when one is present. That readback remains optional for normal control but is mandatory for automatic Smart Update and Full uninstall safe-limit verification. Either value is independent physical inverter feedback only when the integration itself reports the applied inverter limit; a mirrored command-state value is not proof that the inverter applied the downstream command.

## Help improve the matrix

The matrix is intentionally conservative. If you successfully use an integration marked **Compatible by design** or **Action/service adapter** with HPVC, please open a GitHub issue or discussion with the inverter model, Home Assistant integration, control method, action/entity details and Limit unit so the status can be promoted to **Confirmed direct**.

## Safe disable and uninstall behavior

Safe disable, external PV release and safe-uninstall restore use the same configured Number-entity or Action/service write path as normal HPVC control. They do not create a separate inverter protocol.

During full uninstall, HPVC keeps inverter configuration intact until safe shutdown is resolved so configured reachable inverters can be restored through the normal verification/retry path. For the complete uninstall sequence, see [Installation → Full uninstall](01-installation.md#full-uninstall).

Manual-disable completion also requires independent full-limit evidence in v1.6.0. An Action/service adapter without readback can send a restore but remains pending verification; cached commands cannot establish physical completion.

A real readback remains recommended. Without independent readback, HPVC can confirm its command path but cannot prove the physical inverter response beyond the semantics exposed by the selected integration.

[← README](../README.md) · [Installation](01-installation.md) · [Configuration](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md) · [Inverter compatibility](05-inverter-compatibility.md)
