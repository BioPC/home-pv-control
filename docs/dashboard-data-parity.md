# Native dashboard data stage — local validation

This stage continues `hpvc-2.0-dashboard-parity-local.zip`. The previous completion
report remains historical evidence. No production installation, handoff or GitHub
publication is authorized by this package. Production transport authorization is
still **false**. The final report distinguishes implemented data from pending
runtime/frontend acceptance; it does not grant visual approval.

## Entry-owned data and lifetime

`DashboardObserver` is attached in config-entry setup. It uses the existing
`LifecycleOwner` for its 30-second worker, which is cancelled and awaited on
unload. No control scheduler, decision evaluator, dispatcher or service is called.
The observer reads the accepted HBC memory, current policy proposal, authoritative
fleet and immutable execution ledger. It never modifies any of them.

The independent versioned/checksummed file is
`.storage/hpvc_<entry_id>_dashboard.json`. Existing configuration, execution,
policy and legacy history schemas/files remain unchanged. The new file stores:

| State | Retention/restart rule |
|---|---|
| Executed observation points | Last 2,880 samples (about 24h at 30s), across midnight |
| Insights | Newest first, at most 20, current local date only |
| Accuracy | Current-day counters/sums, no unbounded raw sample list |
| Last measured grid timestamp | Persisted to avoid counting a repeated measurement twice |
| Report/maintenance snapshot | Recomputed from current state; not restored as live truth |

Every successful collection is atomically committed before publication. A restart
adds an explicit unknown point, never promotes retained state to current state.
Stale current presentation becomes unknown after 90 seconds. Timeline generators
insert null after the same 90-second validity window, including downtime gaps.
The aggregate payloads are excluded from HA Recorder using the entity API
available in both HA versions; the dedicated store owns their bounded history.
Numeric Power Flow attributes remain recordable.

The store retains all source evidence references needed for its mode label: up to
ten controller proofs plus one HBC proof, each ID bounded to 64 characters.
Messages and reasons are bounded too, keeping the maximum payload below the
existing 4 MiB storage limit. Storage faults, wrong plant identity and backwards
clock/date changes stop the observer with an explicit dashboard fault. They do
not change control state or overwrite a corrupt store. A presentation fault is
not treated as confirmed operation or as permission to execute anything.

Local midnight uses Home Assistant's configured timezone captured at entry setup.
Historical points remain, while Insights and accuracy roll to the new local date.
The getter also hides yesterday's daily values immediately after midnight even
before the worker next runs. Timezone changes take effect after entry reload.

## Executed mode and Charge Priority

Normal means independently verified native operations plus fresh full-output
readback for the whole effective fleet. Limit means the same proof with an
observed reduced limit. Charge additionally requires the latest native HBC
operation to have independent native-state proof matching the live strategy and
the authoritative HBC runtime to say Active. PV-limited is stored separately,
because Charge and a reduced PV limit can coexist.

All controllers must match operation UID/configuration signature and native owner
epoch, completed transport, dispatch identity and verified/retired state. Allowed
proof kinds are HA readback, OpenDTU API, Enphase readback, and independent native
state for HBC. Proof and current readback must be fresh within 90 seconds. Missing
fleet members, stale evidence, recovery, helper proofs, startup assumptions,
simulated epochs or merely proposed plans produce unknown gaps. This is
deliberately conservative; an old command receipt alone does not renew history.

Charge Priority is a presentation of `PolicyRuntimeAdapter.accepted.hbc.priority_state`.
Off/Waiting/Active map directly; `exit_hold` is Waiting with that mapping documented.
The accepted clock must be fresh and the external strategy available. A stable
strategy helper does not need to change its value to remain available. This value is
the existing HBC runtime state, **not proof of a physical HPVC write**. No second
Charge Priority state machine has been introduced.

**Remaining data limitation:** the existing accepted-command fact recorder is
simulation-only. No authoritative physical cooldown feed or coordinator-owned
settling result exists to observe in this stage. Both fields remain unknown.
Completed physical service awaiting verification is separately labelled
`verification_pending`; it is not inferred to be settling. Implementing a new
cooldown/settling algorithm here would violate the control boundary. The store
and graph preserve nullable fields rather than fabricating Off/zero.

## Insights

Entries record observed mode/reason transitions, authoritative HBC state changes
and fresh read-only policy evaluations. Evaluations explicitly say “proposal,
not executed.” No action-success message is created from intent. Collection
respects native `insights_enabled`. Times are displayed in local HH:MM:SS, with
UTC timestamps retained for ordering and audit. Sampling does not claim to have
captured every event between observations.

## Accuracy: exact native formula and difference from v1.6

This is **observed grid target-band accuracy**, not v1.6's counterfactual loss
attribution or proof of control causality. The original card title stays familiar;
the explanatory text states this difference.

A sample is eligible only with a known verified executed mode and a finite grid
measurement reported no more than 180 seconds earlier. Its grid timestamp must
differ from the last measured sample. For each eligible sample:

```
error_W = measured_grid_W - configured_Target_Export_W
within = abs(error_W) <= configured_PV_Adjust_Deadband_W
accuracy_percent = 100 * within_count / measured_count
MAE_W = sum(abs(error_W)) / measured_count
RMSE_W = sqrt(sum(error_W ** 2) / measured_count)
sampled_coverage_percent = 100 * measured_count /
    (measured_count + unavailable_count + duplicate_count)
```

No eligible samples means unavailable metrics, never 0% accuracy. Unknown mode,
stale/unavailable/nonfinite measurements or accumulator overflow increase the
unavailable count. Repeated timestamps increase duplicate count. Coverage is
sample-attempt coverage, not whole-day duration or an estimate across downtime.
Each sample uses the configured target/deadband at that observation; settings
changes do not rewrite earlier measurements. Estimated v1.6 Control/Load/PV/Other
loss attribution remains unavailable because native evidence cannot establish it.

## Reports and maintenance

All ten existing collapsible sections bind to `ui_report_sections` on the existing
native status sensor. Executive Summary stays open, the other nine collapsed.
They contain native current mode/provenance, enable intent, fresh proposed
evaluation status/reason/action, current-day Insights and accuracy, observed
grid/PV and HBC/battery data, current fleet rows, health and configuration.
Unavailable fields stay unavailable. A stale policy proposal is not presented as
current. Rendering a report is read-only and triggers no collection or action.
The Generate/View report publication flow remains disabled; export is outside
this stage's required scope.

Maintenance exposes installed version, read-only runtime/recovery status,
dashboard storage health, migration state and unresolved restore obligations.
Production authorization is false and the permanent veto is explicit. Pending
restart/reload is unknown without an authoritative update source. Legacy
update/reload/remove/uninstall actions stay disabled.

## Dashboard and compatibility

View, section and card order, inverter layout, two-line Limit entity, 12h Power
Flow and 48h HBC graph remain intact. Existing history frames consume the new
bounded native points. An executed-mode series distinguishes Normal/Charge/Limit.
No new custom conditional resource is introduced.

All attribute-based conditions are replaced with ordinary `state`/`numeric_state`
conditions backed by 19 read-only native sensor mirrors. Their IDs are
`sensor.hpvc_dashboard_<attribute>` and their unique IDs are entry/plant-owned.
`condition-keys.json` is the complete key list; generated mapping is included in
`review/condition-entity-mapping.json`. The original 282 native entities plus
these 19 give 301 on a clean installation. Only the HA acceptance entity-count
assertion changes for this addition; control test behavior is not weakened.

This removes the known HA 2025.12 attribute-condition incompatibility at the
configuration level. **It does not prove frontend loading.** Both real-HA
Python-version matrices and actual resource/card loading on both frontend
versions remain pending under the user's local-only instruction. The existing
Limit row/navigation module is unchanged. Isolated DOM/chart execution and
template rendering are not substituted for real HA frontend acceptance.

Primary API references:

- [HA 2025.12 entity Recorder exclusions](https://github.com/home-assistant/core/blob/2025.12.0/homeassistant/helpers/entity.py)
- [HA 2026.10.4 entity Recorder exclusions](https://github.com/home-assistant/core/blob/2026.10.4/homeassistant/helpers/entity.py)
- [HA 2025.12 frontend conditions](https://github.com/home-assistant/frontend/blob/20251203.3/src/panels/lovelace/common/validate-condition.ts)
- [HA 2026.10.4 frontend conditions](https://github.com/home-assistant/frontend/blob/20260930.5/src/panels/lovelace/common/validate-condition.ts)

## Pending acceptance in an isolated test system

Run the unchanged exact HA/Python requirements matrix with the new HA tests (98
tests expected, actual count/result must be recorded). On each version, register
the existing resource as a module, open both views and verify resource loading,
visibility state changes, zero/mixed/stale/HBC-unavailable cases, keyboard/scroll
behavior for the full Limit ID, 12h/48h charts, unknown timeline gaps, all report
sections and disabled maintenance actions. Capture browser errors and screenshots
for the later side-by-side visual review. No production installation or hardware
action is part of these instructions.
