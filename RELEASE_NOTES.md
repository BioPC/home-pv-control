# Home PV Control v1.5.0

> **Release history:** v1.4.4 was never released. Development changes prepared under that version were folded into v1.5.0, so the published release sequence is v1.4.3 → v1.5.0.

v1.5.0 expands inverter compatibility with a generic per-inverter adapter layer.

## Highlights

- Fixed a rate-limiter regression where a successfully checked inverter-write verification record could keep every later timer wake on the full-evaluation path; completed verification records are now ignored by the pending-work gate while remaining available for diagnostics.
- Improved the stable-input rate limiter for battery-equipped systems: Marstek battery AC-power changes now use the cumulative 20 W + 2% significance threshold instead of exact-state hashing, and battery SOC changes are normalized to whole percentages.
- Confirmed Night Restore can now skip stable 10-second cycles. Recovery remains responsive because valid PV above `max(25 W, Night Restore threshold + 15 W)` and any active recovery timer bypass the limiter; a complete evaluation is still forced at least every 30 seconds.
- Fixed support-report inverter health validation for both `number.*` and sensor/readback entities.
- Fixed Settings conditional helpers so inverter-slot and range-warning cards use the expected `binary_sensor.*` domains.
- Fixed cross-stage runtime/diagnostic context handling and inverter target diagnostics.
- New **Control method: Number entity / Action/service** per inverter.
- Generic action/service writes with dynamic Watt/Percent target injection.
- Optional fixed data, Home Assistant target data, sequential stop-on-failure pre/post actions, command step and refresh/heartbeat interval.
- Adapter configuration changes force a safe resynchronization, and command-step quantization now applies in both Watts and Percent modes.
- Failed Action/service calls invalidate the optimistic command cache and are retried on a later eligible cycle instead of being silently treated as applied.
- Optional numeric readback entity for write verification.
- Initial Action/service synchronization after a fresh command cache, plus optional heartbeat refresh that bypasses stable-cycle skipping when due.
- Existing writable-number integrations remain fully supported and are still the default.
- Improved Settings on small screens: each inverter uses a titled `PV1`…`PV10` card and shorter inline labels, with no card-mod dependency.
- Added unit-aware Action Step validation with no new warning entities: `0` is the recommended default, Percent steps must be `≤ 100`, and Watt steps must be `≤ Maximum power`; the dashboard keeps the compact `Action step (0=auto)` label while the unit-specific limits are documented and enforced by backend validation. Refresh interval remains `0–3600 s`, with `0` recommended unless heartbeat refresh is required.
- HPVC continues to calculate and distribute all control targets internally in Watts.
- The report parity checker now matches the v1.5.0 inverter TXT format, including Control method and Limit unit, so valid reports no longer produce a false yellow inverter mismatch.
- Documentation navigation now includes the inverter-compatibility guide across docs 01–05, the install defaults table includes hysteresis and Night Restore threshold, and Restore defaults explicitly documents preserved adapter settings.
- Daily Control Accuracy documentation now states that Action/service adapters without real readback can leave controller-caused error under Other/unclassified while the headline score still remains available.

v1.5.0 ships the inverter-compatibility guide with Number entity and Action/service classifications, plus readback and export-limit guidance.

See `docs/02-configuration.md` and `docs/05-inverter-compatibility.md`.


### Reliability and diagnostics

- Missing Action/service command cache state no longer bypasses the stable-input limiter every 10 seconds; initial synchronization is handled by normal/mandatory full evaluations.
- Support reports now include the last Action/service adapter failure instead of leaving that diagnostic only in a persistent notification.
- Removed unused runtime bookkeeping state and dead local variables identified during static cleanup.
- Fixed control-key write-settle confirmation for Number entity and Action/service adapters.
- Physical Daily Control Accuracy attribution now supports Action/service adapters when a real readback entity is available; adapters without readback remain excluded from physical attribution while headline accuracy continues normally.
- Daily Control Accuracy command attribution now resolves pending inverter writes by `pvN` control key and compares them against Watt-normalized real readback, fixing missed Control attribution after confirmed writes.

> **Upgrade note — sensor → binary_sensor migration:** v1.5.0 corrects several HPVC helper domains (`hpvc_show_inverter_slot_2`…`_10`, inverter limit-range warnings and the export-threshold warning) from `sensor.*` to `binary_sensor.*`. If an earlier installed package created the old `sensor.*` registry entries, Home Assistant may leave those old entities orphaned. They can be removed from the entity registry after confirming the new `binary_sensor.*` entities are present.


## Final audit fixes

- Fixed Home Assistant configuration/readiness validation so **Action/service** inverter slots are validated by their adapter settings instead of being incorrectly rejected for not using a writable `number.*` entity.
- Fixed dashboard onboarding/unavailable diagnostics to use the selected inverter control method and optional Action/service readback instead of assuming every slot uses a Number entity.
- Fixed `HPVC PV Limited` and `HPVC At Minimum PV` compatibility indicators for Percent-mode adapters by normalizing limits back to watts; Action/service adapters without readback now use bounded runtime command diagnostics where physical state is unavailable.
- Expanded the fresh report-state snapshot with v1.5.0 adapter configuration/readback fields so reports remain correct before runtime inverter diagnostics have been populated.
- Repaired stale Node-RED group membership metadata for four v1.5.0 adapter/configuration nodes. This does not change runtime control behavior but keeps the imported flow structurally consistent in the editor.
