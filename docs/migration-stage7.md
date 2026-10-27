# Dev.7: dry-run legacy ownership and fencing

This build validates migration against contained fixtures. It does not contact or mutate a production Node-RED runtime, write PV/HBC actuators, transfer production ownership, merge or release. `DEVELOPMENT.json` identifies v2 development separately from the preserved v1.6 historical release records.

## Evidence and detection

`migration/model.py` defines strict immutable inventory, bridge, controller binding, physical proof and handoff records. The authoritative detector requires a fresh complete reachable inventory, the exact approved v1.6 HPVC-owned code fingerprint and multiple independent signals (managed tabs, helper family, runtime status, heartbeat). Pending updates/recovery, unrecognized fingerprints, missing context and unreachable Node-RED remain unknown. Off master intent, zero controllers and missing helpers never prove absence. The ordinary helper detector remains advisory; it cannot grant ownership.

The fingerprint covers the contents and exact IDs of nodes in the four known HPVC tabs and their two shared HA/runtime configuration dependencies. Shared configuration is fingerprinted but never deactivated. Unknown HPVC-like cloned flows outside these tabs make the inventory incomplete. Tab deactivation flags are verified separately so deactivation does not disguise code changes. The temporary CommonJS bridge reads only the pinned v1.6 context keys, exports scheduler/requests/verification/restore/HBC ownership and shutdown evaluation markers, and reports missing keys as incomplete. It does not reset queues or redesign the old control engine. The native decoder additionally requires independently captured controller bindings, durable original HBC values and fresh HBC state observations. A flow JSON showing disabled tabs cannot by itself prove deployment or runtime fencing.

The bridge is migration-only. It is not installed by the integration and is not a permanent native dependency. The controlled host supplies a transaction ID, fresh process challenge, runtime boot identity and a separately observed deployment receipt. Production host installation/authentication is intentionally unavailable in dev.7.

## Durable transaction

The states are UNASSESSED, LEGACY_PRESENCE_UNKNOWN, LEGACY_DETECTED, IMPORT_PREPARED, LEGACY_QUIESCING, LEGACY_RECONCILING, LEGACY_RESTORED, LEGACY_FENCING, POST_FENCE_VERIFY, NATIVE_OWNER_READY, READY_DISABLED, NATIVE_ACTIVE (model only) and BLOCKED_RECOVERY.

`HandoffEngine` commits every boundary through the existing versioned checksum/fsync/atomic-replace store. The transaction captures plant, import identity, exact legacy fingerprint and boot, native configuration fingerprint, controller identities, disable request, restoration boundary and fence generation. Native-owner-ready and production-transport-authorized are separate fields; deserialization rejects production authorization true. Handoff does not update the production execution ledger to active ownership.

A dedicated private fixture capability is required to install a mutation driver. Normal HA setup loads the journal with no driver. Thus there is no production path to a safe-disable request, a Node-RED edit or registry mutation in this build. This Python capability prevents accidental activation; it is not a sandbox against arbitrary Python code already executing inside HA.

## Safe disable and restoration

1. Native transport remains frozen by its independent permanent veto.
2. Capture exact legacy identity and bridge continuity.
3. Validate and durably commit the configuration import, forced disabled.
4. Commit the disable request boundary, then invoke the contained driver's idempotent request.
5. Require master Off and a v1.6 evaluation strictly after the disable request.
6. Reject active, queued, possibly issued, pending verification and unresolved restoration work.
7. Independently verify every captured controller at full output; opaque or command-cache assumptions are not proof.
8. Require available independently observed HBC originals restored and no override ownership.
9. Permit only a bound previously independently verified full-output Night Restore reference with current active-night evidence and no later possible issue or unresolved work.
10. Require quiescence, commit restoration, then commit fencing intent.
11. Deactivate the exact owned tabs in the contained fixture; observe deployed state and auto-resume prevention separately.
12. After fencing, repeat binding discovery, configuration identity, full-output/HBC proof and unresolved-work checks with observations after the fence observation boundary.
13. Commit native-owner-ready. Physical writes remain Off.

The original v1.6 Function-node runner characterizes the uninstall shutdown marker, post-disable evaluation and full restoration. No hard stop is treated as a substitute for draining issued work. HBC restoration order and controller execution semantics remain the unchanged v1.6 reference.

## Fencing and recovery

`migration/legacy-bridge-v1.6.cjs` exposes a pure fencing transform that deactivates only the exact four HPVC-owned tabs after fingerprint validation. Unrelated tabs, nodes and shared configuration are preserved. Native code has no HTTP/Admin API or service route for applying it. The contained fixture confirms effective command incapability and prevents automatic resume; a challenge/boot/transaction-bound receipt records the fence generation. User acknowledgement is not evidence.

Every restart invalidates the ready claim until a fresh challenge response and post-fence checks pass. Changed code/boot/fence generation, stale callback, legacy return, backup restoration or missing evidence blocks readiness. Interrupted disable/fence operations resume under the same durable transaction and idempotency key. A transient failure can be explicitly recovered only with fresh exact bridge evidence; acknowledgement alone cannot clear recovery. Ambiguous issued work remains a blocker.

## Configuration and history

The established importer retains sensor references, thresholds, all controller payload fields, permissions, selected controller, manual ranges and auto identity provenance. It forces native enabled intent false and stores the previous intent for review. Repeated import does not overwrite later native changes.

The migration manifest records old and actual mapped new entity IDs, typed imported value, validation, disposition and external-reference warning. Auto identity provenance is retained without pretending the provisional slot UID proves a physical binding. `ImportFinalizer` uses a write-ahead history import record and accepts only explicit v1.6 current-day history with the existing eligibility schema 11/attribution revision 22 validation. It does not import dispatcher leases, ownership, acceptance or execution claims. Existing native history, wrong day/plant/schema or an interrupted conflicting edit requires reconciliation.

## Registry migration and dashboard

The registry planner requires exact captured HPVC unique-ID/platform/config-entry provenance. Matching object names are insufficient. A proven legacy occupant may be renamed to a deterministic retired ID before the native suffix is moved to its intended ID. Renamed legacy entities remain captured; unrelated collisions block. Domain changes cannot be forced through HA's registry. Where unique-ID provenance is unavailable (including some YAML helpers), automatic reclamation is refused and the actual native ID must remain in the mapping.

A write-ahead CAS journal reconciles interrupted registry updates and rolls them back only when exact identities still match and original slots remain free. It never overwrites an unrelated entity. Registry application is fixture-only and requires the matching post-fence ready transaction. Both pinned real HA EntityRegistry APIs are exercised, including collision/reclamation and rollback.

`home assistant/hpvc_native_dashboard.json` is a generated Lovelace artifact using built-in cards. Regenerate with `scripts/build_native_dashboard.py --mapping actual-ids.json --configuration configuration.json --history history.json`. The output is reviewed/installed separately; no user dashboard or automation is modified. It preserves zero-controller warning, effective navigation, statuses, auto/manual presentation, a two-line Limit entity display with a full preformatted horizontally scrollable value, HBC state/permissions, Insights, Reports, Power Control and Price Interval views. Graphs use recorder history of mapped native and configured external sources. Insights/report cards show imported current-day snapshots where supplied; live history/report generation remains the existing later runtime scope rather than fabricated data.

## Inherited dashboard assertion and metadata

The v1.6 dashboard itself is unchanged. Its controller status card precedes its range warning. The old regression checked an obsolete literal newline between the words Inverter and status; it failed after YAML wrapping changed. The corrected test parses Markdown cards and verifies semantic order for all ten slots (521 checks pass). The native dashboard is not distorted to satisfy that assertion.

The isolated branch is synchronized to the supplied approved v1.6 legacy reference instead of retaining stale v1.5.6 current metadata. Historical release records are retained. Native development identity has its own validator; CI runs it alongside v1.6 release integrity and all legacy behavior suites. Nothing is published as a release.

## Validation boundaries

Foundation tests cover every durable state, unknown source signals, work/restoration blockers, exact fencing identity, stale proof, binding replacement, restart, backup return, commit failure, interrupted fence, registry CAS/rollback, history/import and dashboard contracts. Real HA acceptance uses controlled legacy fixtures plus actual HA lifecycle, states, templates and EntityRegistry; it rejects all service invocations in dev.7 tests. Source Function-node tests have no network. No test is evidence of real hardware response or a deployed production fence.

Before the first hardware stage: review/install an authenticated narrowly scoped production migration host, validate real Node-RED lifecycle and backup controls, reconcile existing obligations, approve exact site/controller/HBC scope and rollback, then separately approve the connection between verified ownership and transport. The dev.6 permanent production veto remains unchanged throughout dev.7.
