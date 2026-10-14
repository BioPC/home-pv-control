# Home PV Control v1.5.6

**Release date:** 2026-10-14

v1.5.6 is a focused Smart Update recovery release. It fixes a case where an otherwise completed update could remain permanently gated as **Update activation pending** after Home Assistant restored stale update helpers or Node-RED retained a stale local update latch.

## Smart Update activation recovery

- Finalized Smart Update transactions can now reconcile stale activation/update latches instead of being ignored as already complete.
- The periodic recovery classifier now treats the durable update transaction as authoritative and no longer stops solely because `input_boolean.hpvc_update_in_progress` was restored stale by Home Assistant.
- If a finalized transaction still has any stale activation state (`hpvc_update_reload_required`, `hpvc_update_in_progress`, or the Node-RED local update latch), HPVC reruns the existing idempotent finalizer once and verifies cleanup. A durable `activationFinalized` record is sufficient for this cleanup even if the transient readiness file or redundant activation-complete flag is missing.
- Successful activation finalization explicitly clears and verifies both Home Assistant update booleans, restores the saved HPVC enabled/disabled intent, and clears the Node-RED-local update latch, timestamps, recovery-probe marker and phase.
- A reconciliation attempt that begins from an already-finalized transaction no longer hides a new Home Assistant publication/verification failure as an old stale success; the failure remains retryable.
- Genuine incomplete/live transactions remain protected by durable transaction state, and the user-authorized `awaiting_quick_reload` boundary is unchanged.
- If the activation/update helpers survive but `transaction.json` is missing, v1.5.6 can now reconcile that orphaned state conservatively. It proceeds only when no local destructive/update phase is active, no updater/reclaim/fresh activation lock is present, and `/config/packages/hpvc_config.yaml` independently verifies the managed v1.5.6 package. `hpvc_update_in_progress` is cleared first, the runtime safety gate is cleared last, and both states are verified.

## Regression coverage

- Added a regression for finalized transactions with stale `hpvc_update_reload_required`.
- Added coverage for stale Home Assistant `hpvc_update_in_progress` and stale Node-RED local update state.
- Added negative controls proving unfinished transactions are not treated as finalized recovery.
- Added missing-transaction orphan-state regression coverage with safety refusals for active phases, existing transactions, updater locks, wrong package markers and Home Assistant service failures.
- Release validation now requires the finalized-state reconciliation and local-latch cleanup invariants.

## Upgrade

Smart Update remains the preferred upgrade path on the documented Home Assistant OS / Supervised Node-RED add-on setup. Manual upgrade remains available for unsupported/custom installations.

If a v1.5.5 installation is already stuck on **Update activation pending**, v1.5.6 contains the permanent reconciliation fix. Keep the existing recovery data intact where possible so HPVC can reconcile the recorded transaction safely.
