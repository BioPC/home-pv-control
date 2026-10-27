# Home PV Control v1.6.0

**Release date:** 2026-10-25

- Display each inverter Limit entity as a native two-line Entities row: `Limit entity` on the first line and the full exact entity ID as secondary information on the second line, with no custom-card dependency.

- Fixed the per-inverter Min/Max warning card to use the same per-slot invalid-range sensor that hides/disables HPVC Control, eliminating separate warning-condition drift for manual, Hoymiles/OpenDTU and Enphase controllers.

- Clarify invalid inverter Min/Max recovery in the dashboard warning: HPVC Control is forced OFF while Min exceeds Max, and after correcting the value the user must enable HPVC Control again.
- Centralize inverter Min/Max validation in `sensor.hpvc_inverter_limit_validation`: equality is valid, only Min above Max is invalid, and per-slot warnings plus the automatic HPVC-Control-off guard consume the same result without rewriting the user's Min setting.
- Render the Min/Max warning from the same per-slot invalid-range sensor that gates HPVC Control, so `Min power must be ≤ Max power. Correct it, then re-enable HPVC Control.` appears consistently for manual, OpenDTU/Hoymiles, and Enphase controllers whenever Min exceeds Max.

v1.6.0 hardens inverter control, recovery and maintenance while adding registry-based automatic discovery for Enphase DPEL and Hoymiles/OpenDTU controllers. Manual Number-entity and Action/service configuration remains fully supported and has priority over automatic discovery.

## Release highlights

1. **Control correctness and safety** — fixes dispatch-policy mismatches, Min-power handling, dispatch-time verification, contradictory OpenDTU identity fallback, Night Restore freshness, import recovery and maintenance blocking.
2. **Sequencing and recovery** — hardens queued/in-flight inverter actions, callback identity, partial-deployment barriers and recovery-required states.
3. **Automatic controller support** — adds registry-based Hoymiles/OpenDTU discovery and strengthens Enphase DPEL discovery while preserving manual-controller priority and the shared ten-slot limit.
4. **Controller configuration and dashboard** — supports a true zero-inverter setup state, persistent per-controller HPVC Control, clearer status labels and stable locked/editable field behavior.
5. **Maintenance and validation** — retains Smart Update activation recovery protections and expands regression coverage for controller discovery, dispatch, safety, HBC and rendered Home Assistant templates.

## Control and safety

- Retire historical auto-controller completed-write barriers as soon as the authoritative pending-write verifier confirms the write. This restores v1.5.7 manual-Number maintenance semantics for auto-detected OpenDTU/Enphase: a resolved adapter write can no longer be re-verified indefinitely and reported as unavailable/unverifiable during Disable, Smart Update, Remove flows or Full Uninstall.

- Auto-detected native Number controllers (OpenDTU/Hoymiles and Enphase DPEL) now use the same Home Assistant template `last_reported` freshness contract as manual Number controllers during restore/maintenance verification. Auto-detected slots are mirrored into the normal `pvN` helpers, so `sensor.hpvc_source_freshness` resolves the real controller entity and reads HA-core `last_reported` directly. This fixes false `unavailable/unverifiable` results seen only with auto-detected controllers while preserving stale-readback protection.

- Prevent disable, Smart Update, flow removal and full uninstall from stalling when a Number-entity inverter was already independently confirmed at its trusted full output before a redundant restore-to-full write. HPVC carries that pre-write full-output proof through completion, so an unchanged OpenDTU value does not create a false verification barrier; genuinely stale full readback after a real limiting write remains blocked.
- Restore writes are now eligible for confirmation after 5 seconds when the live verified readback already matches the requested full limit; normal limiting writes retain the configured cooldown-based initial verification delay and slow OpenDTU writes keep their extended retry/failure windows.
- Align the **Smart Update**, **Remove HPVC flows** and **Full Uninstall** maintenance gates so a merely active disable-restore lifecycle does not override successful independent full-output verification. Maintenance still stops for pending/active inverter work, unavailable or below-full controllers, or unresolved restore state when no current controller exists to verify.
- Release HPVC-owned auto-managed Enphase DPEL and Hoymiles/OpenDTU slots when registry discovery no longer finds the controller, instead of leaving stale mirrored values as manual `Incomplete` slots. Genuine manual inverter slots remain persistent.
- Align destructive-maintenance verification with normal runtime controller resolution: dedicated OpenDTU registry records are included, legacy/manual Enphase DPEL entries are normalized to native Watts before proving full output, and an unresolved disable-restore obligation remains blocking even if no controller is rediscovered in that poll.
- Bind OpenDTU API write confirmation to the actual adapter dispatch. `/api/limit/status` polls now carry a poll-start timestamp and can confirm a command only when the matching controller evidence was requested after that command was dispatched; an older cached `Ok` snapshot cannot confirm a newer write.
- Keep adapter ownership signatures configuration-only and identical across producer, starter, continuation and failure recovery, so OpenDTU discovery cannot reject a batch and normal Enphase numeric readback changes cannot cancel unrelated queued controller writes. DPEL enabled/`Production` permission is checked explicitly at dispatch.
- Use each effective slot's configured **Max power and Min power** for auto-detected Enphase controllers; OpenDTU continues to use trusted rated power plus the configured slot minimum. Enphase DPEL native min/max metadata never overwrites the HPVC operating range.
- Preserve user-owned Enphase Max/Min across temporary controller disappearance/re-discovery by binding the saved range to the auto-detected DPEL controller identity. A returning Envoy keeps its configured range; a different Envoy is intentionally left `Incomplete` until its own Max/Min are entered.
- Correlate pending-write dispatch timestamps by stable HPVC control key plus physical readback identity, and require an actual dispatch timestamp for OpenDTU API confirmation.
- Reject contradictory OpenDTU API payloads when a controller already has a trusted serial; single-result fallback is used only when no trusted serial identity exists.
- Show a brand-neutral auto-detected/manual inverter total and use the effective runtime map for Settings navigation, Main badges and live actual-limit rows.
- Require fresh PV evidence before Night Restore entry/recovery and preserve bounded behavior after a confirmed nighttime transition.
- Strengthen import recovery, quantization/cooldown enforcement, manual-disable restore obligations and independent full-output verification.
- Block Smart Update, flow removal and uninstall while queued, in-flight or uncertain inverter work remains.
- Keep slot-local controller failures isolated where possible while retaining plant-wide blocking for ambiguous/duplicate physical targets.

## Inverter action sequencing

- Serialize inverter service calls and supersede only unsent stale work while allowing already-sent actions to complete safely.
- Protect continuations/failures with generation and dispatch identities so delayed callbacks cannot overwrite newer control state.
- Preserve call barriers across warm partial deployments and surface uncertain persisted/legacy leases as recovery-required rather than silently clearing them.
- Coalesce identical pending sequences without resetting verification clocks and retain unrelated-inverter failure isolation.

## Controller discovery, status and permission

- The centralized inverter Min/Max validator explicitly tracks all 20 Max/Min helpers, so Home Assistant refreshes warnings and invalid-range control gating immediately after a user edits any slot.
- Inverter Min/Max validation appears directly below the inverter-status banner for manual, Hoymiles/OpenDTU and auto-detected Enphase slots. Equality is valid; only Min above Max is invalid. HPVC preserves the entered Min, forces that slot control permission OFF, hides the control switch until the range is corrected, and never silently caps the helper.
- Live Inputs keeps switched-off inverter limits visible using the native label `PVx actual limit (Off)`; enabled rows retain `PVx actual limit`, while `unknown`/`unavailable` switch states stay hidden. This uses only existing entities and native Lovelace conditions.
- The Settings dashboard now uses one persistent native **Inverters** numeric-input row for both zero and non-zero counts; the separate zero-state add card was removed, while PV configuration remains hidden until at least one effective inverter exists.
- Keep auto-detected read-only fields visually muted with grey lock icons, and preserve trusted OpenDTU rated-power cache metadata across independent registry refreshes so Max power does not transiently revert to an editable manual input.
- Dashboard terminology now uses **Total inverters** and **Inverter status** for clearer user-facing labels; internal controller IDs and runtime semantics are unchanged.
- Dashboard inverter status now identifies auto-detected integrations as **Hoymiles detected** or **Enphase detected**, while internal status semantics remain unchanged.
- Dashboard incomplete status now preserves detection context: manual controllers show **Detected but incomplete**, auto OpenDTU/Hoymiles shows **Hoymiles detected but incomplete**, and auto Enphase shows **Enphase detected but incomplete**. Internal runtime status remains `Incomplete`.
- Fixed the false dashboard `Configuration error` caused by an empty duplicate entities card, and removed the redundant `Controller configuration` heading from PV controller cards.
- Keep the existing maximum of ten effective controller slots across manual and auto-detected controllers. Manual assignments win; automatic discovery reuses compatible empty slots first, deduplicates already represented controllers, then appends remaining controllers up to the cap.
- Support `0` as the real no-inverter setup state. When no manual slot and no auto-detected inverter exists, Settings shows only the **Inverters** add control and hides the empty PV configuration area; auto-detection raises the effective count automatically. Zero is accepted as configuration state but HPVC remains non-operational until at least one usable inverter exists.
- Show a dedicated Main warning in the zero-inverter setup state: **No PV inverters available** — “HPVC is monitoring only. Add an inverter or wait for them to be detected to enable PV limiting.” The required-input safety path keeps the HPVC master control OFF while no usable inverter exists; existing configuration and live-input warnings remain unchanged and take priority when another fault is present.
- Add persistent per-slot **HPVC Control** permission. OFF keeps the controller visible/monitored but excludes it from normal allocation and writes; transition-only Insights report exclusion, monitoring-only mode when all controllers are OFF, and return to control.
- Derive controller UI status from existing runtime/configuration data without extra status helpers: green **Detected/Configured**, amber **Incomplete/Not configured**, or **Unavailable** while preserving the saved control permission for valid controllers.
- Fix runtime-map consumers to support both JSON-string and native-list Home Assistant attributes.

## OpenDTU/Hoymiles auto-detection

- Automatically discover Hoymiles/OpenDTU inverter controllers when Home Assistant MQTT Auto Discovery exposes the non-persistent absolute Watt-limit Number entity.
- Prefer Home Assistant entity/device registry metadata and immutable/original role information so renamed entity IDs remain supported. A strict `_limit_nonpersistent_absolute` Watt-number pattern remains as fallback when registry metadata is unavailable.
- Reject persistent/relative limits, unrelated MQTT numbers and inverter power on/off controls for automatic limiting.
- Determine rated/full power from live OpenDTU `/api/limit/status` `max_power`, then a cached confirmed API value, then the effective slot's manual **Full Limit**. HPVC never treats the HA Number entity's `max` attribute as rated inverter power; without a trusted/API/manual value the controller remains detected but is excluded from limiting until Full Limit is supplied.
- Use OpenDTU `limit_set_status` as optional early verification evidence and enforce a 300-second minimum final verification window for potentially slow absolute-limit readback.
- Keep the OpenDTU limit-status HTTP Request node as the sole owner of the GET method; dynamic polling now supplies only `msg.url` and HPVC metadata, avoiding Node-RED override warnings on current runtimes.
- Support multiple OpenDTU devices, renamed entities, mixed Enphase/manual setups, manual deduplication, controller opt-out and the shared ten-slot ceiling.
- Use the same API/cache/manual Full Limit precedence during Smart Update, flow removal and full uninstall, preventing maintenance from treating the HA Number control-range `max` as rated inverter power.

## Enphase DPEL integration

- Automatically discover complete Enphase Envoy DPEL controllers exposed by Enphase Envoy Installer 0.10.2+ using registry roles and shared HA device IDs; fully renamed entity IDs remain supported.
- Keep suffix-based fallback when registry metadata is unavailable while rejecting production/PV-limit siblings, ambiguous pairings and incomplete DPEL triplets.
- Count each Envoy DPEL controller as one effective HPVC controller slot. A manually configured `number.*_dpel_limit` Number slot is enriched in place rather than duplicated.
- Normalize DPEL control to native Watts/step/readback while preserving manual HPVC Max/Min power, and require the mode select to expose both `Production` and `Export`.
- Require DPEL enabled + `Production` mode before any Watt limit write. `unknown`/`unavailable` support states pause the adapter without sending futile preflight or limit commands.
- Home Assistant validation/onboarding recognizes Enphase-only installations without requiring a placeholder manual inverter slot.

## Smart Update activation recovery

- Retain the v1.5.6 activation-recovery protections, finalized-transaction reconciliation, exclusive activation leases, stale-result protection and conservative orphan recovery.
- Update runtime/package/report markers and managed-version checks for v1.6.0 while preserving stable Node-RED node IDs and historical release documents.

## Regression coverage

- Add a dedicated HBC Charge Priority state-machine suite covering Waiting, Active, Exit hold/transition settle, high-SOC taper caps, persistent-export fallback, and negative-price separation.
- Add a fixture-driven support-report regression that renders the shared model to TXT and HTML, verifies renderer parity, validates generation guards, and exercises the atomic publication contract.
- Clean up controller auto-detection documentation placement so no implementation guidance remains after guide footer/navigation blocks.
- Run twelve baseline control simulations, 30 audited safety checks, fourteen independent maintenance/OpenDTU/dispatch audit regressions, twelve dispatcher lifecycle checks, activation/recovery, Insights and runtime-load regressions in CI.
- Add registry/device discovery tests for renamed/ambiguous Enphase and OpenDTU entities, multiple devices, manual priority/deduplication, max-slot handling and per-controller opt-out.
- Render the shipped Home Assistant Jinja templates with mocked HA states, including Enphase/OpenDTU-only readiness, mixed controllers, native-list/JSON runtime attributes, Number Watts/Percent, Action/service readback and Full Limit-required OpenDTU cases.
- Validate YAML/Node-RED structure, embedded JavaScript/shell syntax, version consistency, release-document synchronization, local documentation links and current CI entries.

## Upgrade

Smart Update remains the preferred upgrade path on the documented Home Assistant OS / Supervised Node-RED add-on setup once this version is published. Manual upgrade remains available for unsupported/custom installations; replace the Home Assistant package, Node-RED flow and managed dashboard together so runtime, templates and UI use the same implementation.

When upgrading from any earlier local unreleased candidate, replace it with the complete v1.6.0 package. Preserve update-recovery data. Existing per-controller HPVC Control helpers are seeded for compatibility and then retain their saved state across Home Assistant restarts.

For auto-detected OpenDTU/Hoymiles controllers, verify the displayed Full Limit source. If OpenDTU `max_power` is unavailable and no cached confirmed value exists, enter the inverter's rated power in that effective slot's **Full Limit** before enabling HPVC control for it.