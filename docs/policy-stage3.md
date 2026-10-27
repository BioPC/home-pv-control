# HPVC 2.0.0-dev.3: pure policy and allocation

This stage continues the approved dev.2 read-only architecture. Physical authorization remains literal False. No dispatcher or HBC writer exists. The installed integration continues its read-only workers; the new pipeline is separately callable for immutable simulation/acceptance, without starting live policy execution or persisting policy state automatically.

## Boundaries

control/decisions.py defines frozen PolicySnapshot, PolicyController, PolicyMemory, PolicyIntent and PolicyResult. control/engine.py evaluates a snapshot, returns the proposed next memory state, allocates desired Watts, and delegates representation to the unchanged dev.2 adapters. command_batches composes frozen CommandBatch DATA only. ExecutionSnapshot supplies cooldown, pending verification, settling, frozen identities, write eligibility, unresolved work, obligations and maintenance. No policy function changes those inputs, creates a task, calls Home Assistant or writes persistence.

The execution owner starts cooldown when a command is actually accepted/issued. Evaluating policy or constructing a simulated batch never starts cooldown. Caller-provided policy memory carries price hysteresis and Night Restore transitions. Night Restore active state uses the existing durable ledger contract; restart retains active mode while discarding partial entry/recovery windows. This stage tests that contract in real HA but does not install an automatic policy-to-ledger persistence loop.

## Ported semantics

Negative grid Watts denote export. Export Start uses strict <, Import Restore strict >. Minimum PV for ordinary export control uses strict >, while Night Restore entry uses <= its separate threshold. Price entry is <= limiting price; exit is > limit + hysteresis. Valid non-positive all-in price (<=0) requests per-controller minimum independent of optional HBC permission. Prices use the source two-hour freshness window; grid/PV use 180 seconds.

The source's large-step gain (0.65), span caps, recent opposite-command damping, current-ceiling import protection, degraded controllable-limit baseline, ordinary cooldown, negative/manual exceptions and recovery absolute rebalance are preserved. priorities.py resolves one action before allocation. External release remains a desired intent/candidate, never a lease or ownership authorization.

allocation.py ports source maximum-power weighted delta water filling, saturation redistribution, deterministic largest-remainder ordering and integer/milliwatt precision. Recovery uses absolute proportional allocation above hard minimums; already balanced state is characterized separately. Frozen lagging controllers stay at live limits during permitted import increases and achievable capacity can fall below the original request. Requested, allocated and represented plant targets are distinct immutable fields. Observed/verified state remains input evidence; plans never become observed values.

Night Restore requires a valid fresh low-PV candidate and 120 seconds. Missing/stale PV never starts a candidate. Sun corroboration can finish only an already-started candidate. Active mode requires 30 continuous seconds strictly above max(25 W, entry threshold +15 W) to recover. Proof invalidates on partial readback, unknown/replaced fleet binding or pending execution. Pending work and HBC restoration prevent a maintenance candidate; no proof/maintenance authority is granted by policy.

## HBC status

HbcPolicyInput is a typed, validated interface for HBC availability, Charge/Charge PV execution, battery eligibility/headroom, response/transition windows, persistent-export fallback, suppression, upward/taper release and override restoration. Downstream priority arbitration consumes resolved HBC intents. Full battery selection, response-window derivation, learned taper behavior, complete Charge Priority increase shaping and override sequencing are deliberately deferred to a required separate HBC substage before dispatcher work, as permitted by the request. HBC golden scenarios inject this resolved upstream interface and do not claim a full HBC evaluator port.

## Characterization

scripts/build_policy_oracles.cjs runs the original v1.6 Function-node runtime through Detect Meaningful Inverter Target Changes, stopping before Record Requested Inverter Writes. No HA service node is executed. It freezes 219 complete policy scenarios plus 220 independent allocation scenarios in tests/fixtures/policy-v1.6-oracles.json. Inputs are common scenario configuration/observations/runtime memory; expected values come only from the original JavaScript. The original flow digest is embedded and checked against a byte-exact gzip reference in tests/fixtures/policy-v1.6-runtime.json.gz. tests/policy_oracle_runtime.cjs is the original test harness with only its reference-input path changed; the existing legacy flow is not replaced. CI initially caught that the isolated branch inherited a different legacy flow, so the authoritative ZIP reference is bundled explicitly. Slot keys in legacy results are normalized to the same physical identities used by Python.

Tests compare action/status, limiting reason, requested/calculated totals, allocated/representable/native controller values, remembered/active price state, cooldown, Night Restore timestamps and rebalance outcome. The original ZIP's mojibake euro glyph is normalized for text comparison; native messages use a valid euro glyph. No control inequality or numeric output is normalized away. All existing 528 dev.2 quantization cases remain unchanged.

## Remaining before dispatch

Complete the HBC derivation substage, broaden multi-cycle/long-run and fault-injection characterization, design the policy-memory persistence adapter and execution snapshot builder, and test full simulated service completion/verification/settling/restore transactions. In particular policy full-output observations/degraded-release candidates cannot clear durable uncertainty, replace operation-bound proof or commit ownership. Unknown/recovery/maintenance and missing write eligibility intentionally block plan composition more conservatively than legacy permissive helper state. No Node-RED fencing, cutover, native ownership, release, merge or hardware deployment is included.
