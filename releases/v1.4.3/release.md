# Home PV Control v1.4.3

Percent-mode targets are quantized before change detection using the Home Assistant number entity `step`; minimum-power rounding is constrained so the configured Watt minimum is never undercut.

Home PV Control v1.4.3 is a compatibility and runtime-efficiency maintenance release. It keeps the v1.4.2 control policy intact while reducing Home Assistant dashboard-helper traffic and adding native support for percentage-based inverter limit entities.

## Inverter limit units

Each inverter now has a **Limit unit** setting:

- **Watts** — existing behaviour; HPVC writes the calculated Watt target directly.
- **Percent** — HPVC converts the internal Watt target to 0–100% using that inverter's configured Full power.

Full power, Minimum power, plant targets, thresholds, deadband, allocation and diagnostics remain in watts. Live percentage states and write-verification states are converted back to watts internally. Existing installations default to **Watts**. Percentage commands are quantized to the writable Home Assistant `number` entity's `step` when available, and invalid/missing Limit unit values now fail configuration validation instead of falling back to Watts.

The existing `sensor.hpvc_pv1_actual_limit` through `sensor.hpvc_pv10_actual_limit` sensors also remain in watts; percentage entity states are converted using the configured Full power.

HPVC still uses a writable Home Assistant `number` entity as the inverter control/readback entity. Integrations that expose only a service or Modbus register can use a bridge/template number that translates the percentage value to the integration-specific command.

## Runtime publishing efficiency

- HPVC-owned output helpers no longer participate in the stable-input rate-limiter hash.
- Status and reason helpers are published only when their HPVC value changes, with a periodic five-minute resync.
- `hpvc_last_targets_json` changed values are published at most every 30 seconds.
- Accuracy diagnostics changed values are published at most every 60 seconds.
- Insight helpers are compared row-by-row, so one changed Insight no longer causes all 20 helpers to be rewritten.
- Support reports show rate-limiter full-evaluation and skipped-stable-cycle counters.

These changes reduce dashboard-only Home Assistant action calls. They do not change PV limiting thresholds, proportional target allocation, Night Restore, cooldown, negative-price protection, HBC Charge Priority or safety gating.

## Upgrade

Replace the Node-RED flow, Home Assistant package and dashboard from the same v1.4.3 package. Reload/restart Home Assistant so the new `input_select.hpvc_pv1_limit_unit` through `input_select.hpvc_pv10_limit_unit` helpers exist. Existing inverter slots should remain on **Watts** unless their writable limit entity is genuinely percentage-based.


### Verification semantics

HPVC verifies the state reported by the configured writable limit `number` entity. This is independent inverter feedback only when the integration itself exposes the applied inverter value. A template/bridge that mirrors the requested command provides command-state confirmation, not proof that the physical inverter accepted the downstream service or Modbus write.
