# HPVC 2.0 HBC and runtime memory — dev.4

Physical inverter and HBC writes remain hard Off. There is no live dispatcher, service executor, HBC writer, Node-RED fencing or native ownership commit.

## Implemented

`hbc/state.py`, `observations.py`, `learning.py`, `override.py` and `evaluator.py` implement immutable raw observations, battery health and ordering, remembered maximums, taper profiles/probes, Charge Priority transitions and negative-price ordered action intent data. The source thresholds remain 50 W entry, 25 W remain, 15 s response, 15 s transition settle, 30 s persistent export and 20 s exit hold. Below 90% the initial release can precede measured charging and uses aggregate eligible headroom with source shaping. Taper caps remain 10%, 6% from 95% SOC and 3% from 98% SOC.

`policy_runtime.py` separates a proposal, accepted runtime memory, durable memory and simulated execution facts. The read-only coordinator invokes it from raw HA observations. Durable original capture is required before generating an eligible forced HBC action; generation itself cannot claim issuance, advance accepted retry time, create a probe or start cooldown. Strategy precedes goal on entry; goal precedes strategy on exit. Original values and uncertain phases survive restart.

`execution/facts.py` accepts simulated events only, validating represented targets, the latest accepted evaluation, configuration/controller/dispatch/owner identity, native HBC payload and durable capture token against an in-flight durable operation. There is no production caller that records issued events. `execution/snapshot.py` derives immutable restrictions from the ledger, not helper/cache state. Pending work, removed/replaced identities, obligations, maintenance, unknown ownership and failed/unknown outcomes remain restrictive. The physical authorization property is always false.

## Characterization

The exact original v1.6 Function-node source is bundled in `tests/fixtures/policy-v1.6-runtime.json.gz`; SHA-256 `b83d0ceaedc66cce7a6be870dc9a376f053b9b831717e4649d80bc8e8fe35ba7`. The original source ZIP SHA-256 is `fc5e877ea714e340c0688872cbcde8e061e7d5bbac0f8ff7977183deedd4401d`. The VM executes Function nodes with fake states/time/context and no service nodes or network.

- 103 frozen HBC sequences / 395 cycles compare state, headroom, shaping, health, override phase/originals/ordered select intents, every battery profile/counter/window, and pending-probe samples and shares.
- 10 frozen full-policy sequences / 35 cycles compare decisions, targets, native representation, price hysteresis and Night Restore proposed memory. They retain context across cycles and use fake acceptance plus frozen source execution observations. They do not claim that a legacy helper is authoritative native execution evidence.
- All dev.1/dev.2/dev.3 tests remain. The 439 previous policy/allocation cases and 528 quantization oracle cases remain intact.
- Fake lifecycle tests traverse actual durable operation transitions, matching simulated acceptance, cooldown, fake completion, independent verification, settling and the next evaluation. Service failure, verification failure, unknown outcome, superseded unsent work, obligations and maintenance are covered.
- Raw battery faults, stale evidence, failed/contaminated probes, repeated lockouts/recovery, independent band expiry, unavailable HBC states, corrupt/missing persistence, restart continuity and wall jumps are covered.

Regenerate the frozen additions with `node scripts/build_hbc_oracles.cjs` and `node scripts/build_policy_sequences.cjs`. Run `python -B scripts/test_foundation.py`; real HA acceptance uses the two pinned environments in `.github/workflows/validate-foundation.yml`.

## Explicit conservative migration differences

Uninterrupted windows use monotonic elapsed time. Restart clears partial response, exit-hold, transition, export, healthy-recovery and probe-stability observation windows; an interrupted probe requires independent recovery. Active Night Restore and durable override originals survive, but partial Night entry/recovery windows reset. This deliberately avoids claiming continuous observation across restart, unlike raw legacy wall-clock context.

A present malformed cutoff never falls back even if its companion is unavailable; the original paired-cache loophole is rejected as explicitly required. Post-write probe evidence must also be at/after the accepted write, not merely newer than the previous sample. Cooldown begins at an accepted/issued event, not at legacy plan construction. Across restart it honors the existing accepted UTC deadline and never creates a fresh interval. A backward clock that places acceptance in the future restricts recovery.

The 430 normal-continuity oracle cycles match; these conservative cases are separately tested, not described as exact legacy equivalence. Hardware response, live dispatch, legacy quiescence, power-loss guarantees and production readiness have not been validated.

## Persistence

Two schema-1 private companions are added to the existing three stores: `_policy.json` (`policy_memory`) and `_accepted_commands.json` (`accepted_commands`). Checksums, strict typed decoding, plant identity, serialized commits and generation/revision checks apply. Corruption or a missing companion fails closed. Policy persistence cannot acknowledge an unresolved physical operation. No new entity identities are introduced (282 retained).
