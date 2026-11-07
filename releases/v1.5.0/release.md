# Home PV Control v1.5.0

> [!NOTE]
> **v1.4.4 was never released.** Development changes that had been prepared under that version were incorporated into v1.5.0, so the published release history moves directly from v1.4.3 to v1.5.0.

Home PV Control v1.5.0 is an inverter-compatibility and runtime-efficiency release. It adds a generic per-inverter adapter layer for integrations that expose writable Home Assistant actions/services instead of a writable limit `number` entity, while preserving the existing Watt-based HPVC control engine.

## Main changes

- Added per-inverter **Control method: Number entity / Action/service**.
- Added generic Action/service writes with dynamic Watt/Percent target injection.
- Added optional fixed service data, Home Assistant target data, readback entity, command step, heartbeat/refresh interval, and sequential pre/post actions.
- Existing writable-number integrations remain supported and remain the default.
- Improved mobile Settings layout: each inverter is shown in its own titled `PV1`…`PV10` card, while row labels are shortened and Action/service fields stay inline in the same card without card-mod.
- Action Step now has unit-aware validation without adding per-inverter warning entities: `0` keeps the default step, Percent values must be `≤ 100`, and Watt values must not exceed that inverter's Maximum power. The dashboard keeps the compact `Action step (0=auto)` label; unit-specific limits are documented here and enforced by backend validation.
- HPVC continues to calculate plant targets, thresholds, allocation and diagnostics internally in watts.

> [!IMPORTANT]
> Replace the Home Assistant package, Node-RED flow, and dashboard together when upgrading so helper domains, adapter settings, flow behavior, and displayed version information stay aligned.

## Generic inverter adapters

For **Number entity**, HPVC keeps the existing behavior: the finalized inverter target is written with `number.set_value`. Watt and Percent entities are both supported, and the writable entity step is applied before change detection and verification.

For **Action/service**, HPVC executes an optional pre-action sequence, the main configured Home Assistant action/service, and then an optional post-action sequence. Each step waits for the previous step to complete successfully. A failed action stops the remaining sequence for that inverter, invalidates its optimistic command cache, removes the failed pending-write entry, raises a persistent notification, and allows a later eligible cycle to retry.

The configured dynamic value field receives the finalized Watt or Percent command. Fixed data and target JSON are merged around that dynamic value. If a device requires timed waits between steps, use a Home Assistant script; HPVC does not insert arbitrary delays. Advanced JSON helpers are limited by Home Assistant `input_text` length, so larger payloads or sequences should also be wrapped in a script.

Changing an adapter's method, action, payload, unit, range, step, readback or sequence changes its configuration signature. HPVC then clears that inverter's cached command state and forces a fresh synchronization write. Action/service adapters may also send a periodic heartbeat/refresh command when configured.

For a new/default Action/service setup, leave **Action Step = 0** and **Refresh interval = 0 s** unless the inverter integration specifically requires another value. `0` for Action Step means HPVC uses a step of `1` in the selected unit; `0 s` for Refresh disables heartbeat writes. HPVC does not force these values back to zero on Home Assistant restart, so existing user settings remain persistent.

After a Node-RED context reset/restart, an Action/service adapter without cached command state performs one synchronization write on the next normal/full evaluation. That synchronization is not treated as a normal PV control change, so a genuinely new control decision on a following cycle may write again before the ordinary PV cooldown would have expired. This keeps startup synchronization from delaying a newly required safety/control response.

## Write verification and readback

A configured real readback entity allows HPVC to verify the physical/applied inverter limit. Readback values use the selected adapter unit and are normalized back to watts internally.

Action/service adapters without real readback can track the command HPVC requested, but that command cache is not treated as proof that the inverter physically accepted the value. Daily Control Accuracy therefore uses Action/service adapters for physical event attribution only when a real readback source is available. Without real readback, the headline accuracy calculation still runs, but controller-caused physical error cannot be proven as Control response; that portion can remain under Other/unclassified and attribution coverage can therefore be lower.

Pending-write confirmation, diagnostics and Daily Control Accuracy attribution now consistently resolve inverter writes through the per-slot `pvN` control key. Percent readback is converted to watts before comparison, avoiding mixed-unit attribution errors.

## Runtime efficiency

The stable-input rate limiter still wakes every 10 seconds and still forces a complete HPVC evaluation at least every 30 seconds.

A completed inverter-write verification record no longer keeps the limiter permanently bypassed. While a write is genuinely pending, verification still forces full evaluation; once the record is marked `checked: true`, it is retained for reporting/diagnostics but is no longer treated as pending runtime work, allowing normal stable-cycle skipping to resume.

Grid power, PV power and Marstek battery AC power now use the same cumulative **20 W + 2%** significance threshold measured from the **last full HPVC evaluation**. Small changes therefore accumulate instead of resetting the baseline every 10 seconds. Battery SOC is normalized to whole-percentage changes for the stable-input hash, while other control-relevant live states continue to use exact-state comparison.

A confirmed **Night Restore** state no longer forces every 10-second wake through the full downstream pipeline. Quiet nighttime cycles can be skipped. If valid PV rises above the Night Restore recovery threshold (`max(25 W, configured threshold + 15 W)`), or a recovery timer is already active, HPVC bypasses the limiter and evaluates recovery on the normal timer cadence. Safety, write-verification, recovery, settings changes, startup/config rebuilds and due adapter heartbeats continue to bypass stable-cycle skipping.

HPVC-owned dashboard/output helpers remain excluded from the rate-limiter hash. Status, reason, Insights, targets JSON and accuracy diagnostics continue to use the v1.4.3 deduplication/throttling behavior.

## Safety and diagnostics fixes

- Fixed Home Assistant configuration/readiness validation so **Action/service** inverter slots are validated by their adapter settings instead of being incorrectly rejected for not using a writable `number.*` entity.
- Fixed dashboard onboarding/unavailable diagnostics to use the selected inverter control method and optional Action/service readback instead of assuming every slot uses a Number entity.
- Fixed `HPVC PV Limited` and `HPVC At Minimum PV` compatibility indicators for Percent-mode adapters by normalizing limits back to watts; Action/service adapters without readback now use bounded runtime command diagnostics where physical state is unavailable.
- Expanded the fresh report-state snapshot with v1.5.0 adapter configuration/readback fields so reports remain correct before runtime inverter diagnostics have been populated.
- Repaired stale Node-RED group membership metadata for four v1.5.0 adapter/configuration nodes. This does not change runtime control behavior but keeps the imported flow structurally consistent in the editor.
- Fixed HTML/TXT report parity for inverter rows after v1.5.0 added Control method and Limit unit fields.
- Missing Action/service command cache state no longer forces every 10-second timer wake through the full pipeline. Initial synchronization occurs on the next normal/full evaluation, with the mandatory 30-second evaluation providing a bounded retry path.
- HTML and TXT support reports now expose the last adapter action failure (time, inverter slot, sequence phase, action and error detail).
- Removed unused runtime bookkeeping keys and dead local variables found during static analysis.
- Fixed the pending-write runtime-work gate so completed (`checked: true`) inverter verification records do not disable stable-cycle skipping after a successful write.
- Fixed support-report inverter entity validation so `sensor.*` readback entities cannot crash report generation.
- Fixed Settings conditional helper domains for inverter-slot visibility and threshold/range warnings.
- Fixed cross-tab runtime/diagnostic context scope for HBC timing, battery recovery and rate-limiter diagnostics.
- Fixed inverter diagnostic target lookup so calculated target, clamping state and requested totals are retained correctly.
- Fixed pending-write settle confirmation so a physically confirmed write can release its lock without waiting an extra evaluation.
- Fixed Daily Control Accuracy command-application attribution for `pvN` control keys and Watt-normalized readback.
- Action/service failures clear cached command state and last-write timing so failed commands can be retried rather than silently accepted.
- Adapter configuration changes invalidate stale command state and force resynchronization.
- Watt and Percent command steps are quantized before change detection and verification.

## Inverter compatibility documentation

v1.5.0 ships a dedicated inverter-compatibility guide for both Number entity and Action/service control paths:

- Compatibility remains classified by the actual Home Assistant integration/control path, not only by inverter brand.
- The guide continues to distinguish inverter active-power limiting from site/grid export limiting.
- The matrix now identifies integrations that can use the generic Action/service adapter and explains readback/verification limitations.

## Regression checks

The release package was statically validated before packaging for Node-RED references, Function-node JavaScript syntax, key v1.5.0 limiter/report invariants, dashboard structure, YAML integrity and documentation navigation. These release-validation checks are not shipped as part of the user package.

## Upgrade

Replace the Node-RED flow, Home Assistant package and dashboard from the same v1.5.0 package. The documented Home Assistant support baseline is **Core 2025.12 or newer**; earlier versions may work but are not part of the supported baseline.

Existing Number-entity configurations remain compatible and default to **Number entity**. Configure **Action/service** only when the integration exposes a suitable inverter power-limit action/service and no direct writable limit number is available.

v1.5.0 corrects several HPVC helper domains (`hpvc_show_inverter_slot_2`…`_10`, inverter limit-range warnings and the export-threshold warning) from `sensor.*` to `binary_sensor.*`. If an earlier installation created the old `sensor.*` registry entries, Home Assistant may leave them orphaned. After confirming the new `binary_sensor.*` entities are present, the old orphaned `sensor.*` entries can be removed from the entity registry.

After upgrade, the rate-limiter counters may show more skipped stable cycles than v1.4.3 on battery-equipped systems and during quiet Night Restore periods. This is expected: v1.5.0 no longer treats small battery-power jitter or the mere fact that Night Restore is active as reasons for a full evaluation. A full evaluation is still guaranteed at least every 30 seconds.

## Verification semantics

For Number-entity control, verification follows the state reported by the configured writable limit entity. This is independent physical feedback only when the integration itself reports the applied inverter value.

For Action/service control, use a real readback entity when available. Without one, HPVC can confirm only the command it sent, not the inverter's physical acceptance of that command.
