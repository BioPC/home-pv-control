# HPVC dev.5: authoritative dispatcher with a fake executor only

Physical-write authorization remains literal false. `Dispatcher` accepts exactly the concrete `FakeExecutor`; no HA-backed executor exists. Live read-only setup does not instantiate a fake dispatcher or invent simulated physical events. Tests explicitly bind the dispatcher and register its asynchronous cleanup with the entry owner.

## Architecture and persistence

`execution/dispatcher.py` owns executable sequencing for the simulation. A separate lock/lane exists for inverter and HBC work. Inverter service operations remain serial. Controller failure isolates the remaining unsent sequence while unrelated controllers may continue when transport is quiescent. Identical work coalesces; a new generation supersedes only an entirely unsent batch. An issued batch retains its remaining sequence.

`execution/executor.py` defines immutable requests, receipts, completions and quiescence receipts. `FakeExecutor` records requests, can delay receipt, throw, omit completion, and emit controlled duplicate/stale/old-epoch callbacks. It has no services, MQTT or HTTP handles. No wall-clock timer clears an unresolved operation.

The existing execution ledger remains authoritative for operations, evidence, obligations and maintenance. A checksummed `_dispatch.json` companion of kind `fake_dispatch` captures immutable accepted proposals, command batches, configuration references, bounded simulation audit history and settling. It is created only for an explicitly constructed fake dispatcher. Missing journal plus existing work fails closed. Journal/ledger commit ambiguity requires recovery; registered or armed work is never automatically replayed after reload.

The exact dev.4 execution record field sets migrate additively after original checksum validation. Arbitrary missing/extra fields, unknown schema/enums and corrupt payloads remain rejected. New native-state proof fields distinguish select/switch state from numeric inverter Watts. They cannot masquerade as numeric full-output restoration evidence.

## Lifecycle

Registration commits PREPARED without starting cooldown. Dispatch commits DISPATCH_ARMED with immutable owner/configuration/dispatch identity before calling the fake. Only a matching simulated issue receipt advances SERVICE_IN_FLIGHT and creates an accepted-command event. Pre-actions do not claim the main PV command has been issued. Completion advances SERVICE_COMPLETED then AWAITING_VERIFICATION or UNVERIFIABLE_OPEN_LOOP. Independent evidence alone can advance VERIFIED. Confirmed settling permits RETIRED for a PV main operation. Native select/switch steps retire after their independent state proof.

Stale or duplicate completions cannot advance newer work. The callback must match step payload, owner epoch, dispatch ID, controller and configuration. Fake transport failure, unknown outcome and verification failure remain explicit. Quiescence receipts resolve transport continuity only; physical proof/restoration obligations remain. Recovery may resume verification after proven completed transport, never by replaying the call.

## HBC lane

HBC may be in flight alongside one inverter operation. Strategy precedes goal on entry; goal precedes strategy on restoration. Durable capture is checked before forced action registration, issue acceptance and native payload matching. Executor success is not select confirmation. Fresh independent native-state observations must match the issued entity, expected value and timestamps. An outstanding HBC verification blocks the next HBC step. An explicit, completed transport failure can be retried from a fresh policy intent. Unresolved transport does not retry by age. Notification intents remain policy data; no real notification or helper service path was added.

## Accepted-command and settling contracts

Accepted facts are validated against the captured registered proposal, so an old in-flight sequence cannot be retroactively bound to a newer evaluation. Targets, before-values, configuration identity and cooldown duration remain execution-owned. Full-output restoration from a maintenance owner has a separate narrow registration path: it accepts only the captured archived full target after an accepted disabled evaluation. It cannot grant general control permission.

Settling consumes independent fresh PV observations after independently verified limits. Uninterrupted elapsed time follows the accepted monotonic clock. A completed settling result survives reload; partial sampling continuity resets. New issued work explicitly supersedes its controller's older settling interval without asserting that the old interval physically applied. A settling timeout is not restoration proof and cannot authorize maintenance.

## Obligations and maintenance

`execution/maintenance.py` captures saved enable intent, transaction identity, owner epoch, request clock and every applicable current/historical controller restoration identity. A fresh accepted post-disable evaluation is mandatory. Restore obligations survive removal, reconfiguration, zero-controller rediscovery, reload, restart and failures. Failed operations retain their audit states; only matched independent full-output proof can reconcile their restoration obligation after transport quiescence.

The already-full shortcut requires a matching available, independently verifiable live adapter view, exact archived identity/range, post-request fresh timestamps and no conflicting possible operation. Cache/startup assumptions, replacement signatures and stale full state cannot resolve an obligation. Unstructured Enphase/OpenDTU status is refused; their full structured evidence path is required. The approved durable Night Restore proof exception remains identity-bound and cannot cover later conflicting work.

Maintenance checks disabled intent, post-disable evaluation, drained/reconciled operations, every restore obligation, restored HBC phase and verified settling (or the bounded Night proof exception). At 180 monotonic seconds it becomes BLOCKED, never authorized. Authorization is a revision-, owner- and time-bound simulation decision. It performs no update, uninstall or removal action. Restart blocks the transaction and preserves obligations.

## Characterization and deliberate differences

`scripts/build_dispatch_characterization.cjs` executes the original supplied v1.6 Function nodes through the existing 12 dispatcher lifecycle scenarios with fake callbacks. The frozen scenario names and source digest are in `tests/fixtures/dispatch-v1.6-characterization.json`. Native tests exercise corresponding ordering, coalescing, generation, verification and maintenance invariants. This is state-machine characterization, not a claim of exact whole-runtime equivalence.

The retained dev.4 430 continuous policy/HBC oracle cycles remain unchanged. Dev.5 deliberately strengthens cold/warm restart and ambiguous receipt handling, independent preflight/select evidence, provenance on already-full proof, and maintenance ownership. Legacy queue-time cooldown is replaced by accepted main-issue cooldown. Opaque generic pre/post actions may complete transport but remain open-loop without independent evidence; they cannot silently authorize maintenance.

## Validation and limits

Run `python -B scripts/test_foundation.py`. The exact HA 2025.12.0 and HA 2026.10.4 matrix remains in `.github/workflows/validate-foundation.yml`, with real HA fake-dispatch lifecycle, ledger persistence, callback/reload/unload and actuator-call traps. Detailed results and the restart/fault matrix are in the completion report.

No real inverter/HBC calls, HTTP/MQTT writes, Node-RED fencing, native ownership commit or production cutover. Before a real executor: review service-specific pre/post proof and recovery contracts, complete production permission/readiness/fencing and handoff, bind fresh identity/evidence acquisition to the transport, then separately authorize and validate real actuation. No universal hardware-response or power-loss guarantee is claimed here.
