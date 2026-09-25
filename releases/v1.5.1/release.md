# Home PV Control v1.5.1

v1.5.1 is a focused control-handover and shutdown-safety update built directly on v1.5.0.

## Safe disable

Switching `input_boolean.hpvc_enabled` Off now starts a controlled restore sequence when HPVC still owns a reduced PV limit or negative-price HBC override. Configured inverter limits are returned to full output and the owned HBC state is restored before HPVC settles at Disabled. The shutdown PV restore bypasses the ordinary PV cooldown so disabling HPVC does not intentionally preserve a stale curtailed limit.

## External PV release interface

Two HPVC-owned entities provide a generic request/acknowledgement contract for companion controllers:

- `input_boolean.hpvc_external_release_request`
- `binary_sensor.hpvc_external_release_active`

HPVC stays enabled during an external release. It keeps safety/minimum-price, Night Restore and owned HBC restore states at higher priority, respects the ordinary cooldown/write-confirmation path for the handover, restores configured inverters to full, then raises the active acknowledgement. Normal PV curtailment resumes when the request is removed.

The request switch is intentionally not exposed as a normal dashboard control. The active acknowledgement appears as a badge only while release is active.

## Reports and documentation

HTML and TXT support reports include the external-release request and active state. They also retain the most recent safe-disable restore result for post-event diagnostics. Installation, configuration, runtime, troubleshooting and inverter-compatibility documentation describe the public handshake and safe-disable semantics.

## Upgrade

Replace the Home Assistant package, Node-RED flow and dashboard from the same v1.5.1 package. Existing inverter settings and existing Number entity / Action-service adapter configuration remain compatible.
