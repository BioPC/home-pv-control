[← README](../README.md) · [Installation](01-installation.md) · [Settings](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md) · [Inverter compatibility](05-inverter-compatibility.md)

# Inverter compatibility

Home PV Control (HPVC) v1.5.2 controls inverter output through either a writable Home Assistant `number` entity or a configurable Home Assistant **Action/service** adapter. Limits can be expressed in **Watts** or **Percent**, while HPVC continues to calculate internally in Watts.

Compatibility depends on the **Home Assistant integration and the entities it exposes**, not only on the inverter brand or model. A writable grid-export limit is not automatically equivalent to an inverter active-power limit: HPVC expects to control the inverter production ceiling itself.


## v1.5.0 adapter impact

The matrix below describes integration fit, not a guarantee for every model/firmware. v1.5.0 adds generic **Action/service** adapters, so integrations previously marked **Action/service adapter** may now be configurable directly when Home Assistant exposes a stable action/service schema. Complex integrations can also use optional pre/post action sequences. Hardware field confirmation is still required before promoting a brand to **Confirmed direct**.

## Compatibility status

| Status | Meaning |
|---|---|
| **Confirmed direct** | Tested with HPVC on real hardware using one of the supported control methods and confirmed to work. |
| **Compatible by design** | The integration exposes the kind of writable inverter active-power-limit entity HPVC requires, but that integration/model has not yet been field-tested with HPVC. |
| **Action/service adapter** | The integration does not expose a directly usable writable limit `number`, but it exposes a stable Home Assistant action/service or register-write path that can be configured in HPVC v1.5.0. |
| **Not confirmed / not suitable** | No verified HPVC-compatible inverter active-power-limit entity was found, or the available control is for a different purpose such as site/grid export limiting. |

## Compatibility matrix

| Brand / integration | Status | Why |
|---|---|---|
| **Hoymiles + OpenDTU** | **Confirmed direct** | Writable absolute/relative inverter-limit entities are available and this setup is already used successfully with HPVC. |
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
| **Enphase Envoy** | **Not confirmed / not suitable for direct production-ceiling control** | The official Home Assistant integration does not expose a writable inverter active-power-limit `number`. Dynamic Power Export Limiting (PEL) available through some other APIs/custom integrations is export-control rather than a per-inverter production ceiling, so it should not be treated as equivalent to HPVC's normal inverter-limit backend. |
| **Qcells** | **Not confirmed / not suitable** | No verified generic HPVC-compatible inverter-output control was found. |
| **Delta** | **Not confirmed / not suitable** | Model-level Modbus control may exist, but no verified generic Home Assistant entity suitable for HPVC was found. |
| **KACO** | **Not confirmed / not suitable** | No verified directly usable HPVC inverter power-limit entity was found. |
| **Solplanet / AISWEI** | **Not confirmed / not suitable** | Monitoring support exists, but direct inverter-output control suitable for HPVC has not been verified. |
| **Sigenergy** | **Not confirmed / not suitable** | Advanced power controls exist, but a simple writable inverter active-power-limit `number` matching HPVC's current control model has not been verified. |

## What HPVC v1.5.0 requires

For **Number entity** control, the integration must expose a writable Home Assistant `number.*` representing the inverter active-power ceiling.

For **Action/service** control, the integration must expose a stable Home Assistant action/service schema that HPVC can call with a dynamic Watt or Percent value. Optional pre/post actions can enable control modes, select modes or trigger a command. Optional command refresh can provide a heartbeat.

A numeric readback entity is strongly recommended. Without one, HPVC tracks command-state only and does not claim physical inverter verification.

A site/grid **export limit** is not automatically equivalent to an inverter active-power limit. Use it only when the integration semantics match HPVC's intended production-ceiling control.

## Readback and verification

In **Number entity** mode HPVC verifies the configured writable limit entity. In **Action/service** mode HPVC verifies the optional readback entity when one is configured. Either value is independent physical inverter feedback only when the integration itself reports the applied inverter limit; a mirrored command-state value is not proof that the inverter applied the downstream command.

## Help improve the matrix

The matrix is intentionally conservative. If you successfully use an integration marked **Compatible by design** or **Action/service adapter** with HPVC, please open a GitHub issue or discussion with the inverter model, Home Assistant integration, control method, action/entity details and Limit unit so the status can be promoted to **Confirmed direct**.

## v1.5.2 release/disable behavior

Safe disable and the external PV-release handshake use the same configured Number-entity or Action/service write path as normal HPVC control. They do not create a separate inverter protocol. A real readback remains recommended: without independent readback, HPVC can confirm its command path but cannot prove the physical inverter response beyond the semantics exposed by the selected integration.

[← README](../README.md) · [Installation](01-installation.md) · [Settings](02-configuration.md) · [How it works](03-how-it-works.md) · [Troubleshooting](04-troubleshooting.md) · [Inverter compatibility](05-inverter-compatibility.md)
