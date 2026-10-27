# Dev.6: guarded Home Assistant executor

The only ServiceRegistry call is in `custom_components/hpvc/execution/ha_executor.py`. Only a bound dispatcher task can issue a registered `CompiledServiceStep`. Compilation resolves JSON before registration and freezes nested values. The executor copies these values for HA and never reparses JSON or substitutes templates.

## Closed admission

Ordinary setup constructs a closed executor with no live dispatch provider or test capability. `production_transport_admitted()` is permanently false, independently of enabled intent. Physical authorization remains false. No production ownership commit, fencing or live dispatch loop was added.

Dedicated tests construct an opaque, non-serializable Python capability. Its aliases are restricted to `hpvc_transport_test`; it cannot route to actual actuator domains. Runtime configuration, YAML, storage imports, services, events and entity state cannot construct the capability. Python private symbols are an accidental-activation barrier, not a sandbox against arbitrary malicious Python code running inside HA.

## Services and immutable plans

- Generic Number: `number.set_value`, exact represented native value and entity.
- Generic Action: approved adapter domain/service, frozen target and fixed/nested/token-resolved data, ordered pre/main/post. Direct mqtt, rest_command, http, shell_command and python_script domains are rejected. Opaque success stays open-loop and supplies no physical proof.
- Enphase: `switch.turn_on`, `select.select_option` for Production, then `number.set_value` only after independently observed readiness and a current proposal. Preparation and main are separate.
- HBC: `input_select.select_option` for strategy then goal on entry and goal then strategy on exit. Only the four approved steps are executable. Diagnostic helper/fault/notification intents do not become transport calls. All HBC module files remain unchanged.

## Boundary and durability

The ledger commits ARMED and required original HBC capture before invocation. A separate per-owner transport journal commits an armed attempt before the last synchronous identity/admission check. There is no await between that check and ServiceRegistry entry. The actual boundary clock returns in the issue receipt; the dispatcher commits IN_FLIGHT before accepting a main-command event. A crash between these commits retains uncertainty; it cannot establish non-issue.

Every journal row identifies operation, dispatch, owner, controller, configuration, sequence, logical domain/service, exact target/data JSON, mapped call domain/service, armed/issued/completion clocks, result and exception details. HA handler return values are not requested; successful return means transport completion only. Journal retention is bounded at 128 attempts per owner; capacity/storage failure closes further admission conservatively. Owner journals are separate so late callbacks cannot overwrite another owner's journal. Long-term journal pruning is deferred.

Before issue: recheck plant/epoch, active dispatcher, healthy stores, operation state/dispatch, sequence and payload fingerprints, live configuration/adapter signature, opt-out, availability, enabled intent, maintenance ownership, HBC native entity binding/capture/permissions/current ordered intent, Enphase readiness, target existence/options and service registration.

## Results, timeouts and unload

Missing bindings/entities/services, unavailable targets and changed identities refuse before issue. Positive exact not-issued evidence permits ARMED to SUPERSEDED with a restricted reason. A stale refusal cannot clear a newer dispatch lease. Registry validation or handler exceptions after invocation are SERVICE_FAILED and retain restoration obligations. No error authorizes a retry automatically.

Timeout publishes outcome-unknown without cancelling the issued service. Late completion remains an audit result and cannot turn unknown into verified. Cancellation after invocation is unknown. Unload revokes admission first, cancels unissued work only, drains durable storage, and preserves issued handlers and uncertain obligations. Old-owner callbacks cannot advance a replacement owner. Completion arriving before IN_FLIGHT is buffered for later matched delivery.

Service success proceeds only to awaiting independent verification or open-loop status. HBC observations, Enphase readiness and main readback remain independent of callbacks. Maintenance cannot use transport success as restoration evidence.

## Scope left for later

Production binding provider and dispatcher scheduling, legacy detection/fencing, audited ownership handoff, externally proven quiescence where necessary, archive retention, hardware-specific service validation and a separately approved first controlled hardware test remain future work. This build is a development artifact, not a production cutover.
