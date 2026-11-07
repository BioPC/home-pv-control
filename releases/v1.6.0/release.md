# Home PV Control v1.6.0

HPVC v1.6.0 focuses on safer inverter restoration, reliable maintenance and automatic Enphase DPEL / Hoymiles OpenDTU discovery. Manual Number and Action/service controllers remain supported. This is a **release candidate** until live maintenance and inverter tests are completed.

## Key changes

- **Safer inverter control:** dispatch-aware verification, robust Night Restore, independent External Release protection and durable restoration obligations.
- **Automatic inverter discovery:** supported Hoymiles/OpenDTU absolute-Watt and Enphase DPEL controllers, with manual-controller priority and a shared limit of ten slots.
- **Safer updates and removal:** Smart Update, flow removal and full uninstall block while restoration or command verification remains unresolved.
- **Clearer configuration:** persistent per-inverter HPVC Control, explicit Min/Max warnings, zero-inverter onboarding and more informative dashboard statuses.
- **Migration safeguards:** preserve user-owned manual helpers, suppress ambiguous duplicate controllers and associate freshness evidence with the effective limiter entity.

## 1. Inverter safety and restoration

- **Control cadence:** PV Cooldown controls normal scheduled writes (2–60 seconds, default 10). The dashboard marks settings below five seconds as advanced. External Release runs independently with a 1-second safety scheduler; proactive refresh occurs at 25 seconds and stale/future heartbeat or verification evidence fails closed at 30 seconds.
- **Night Restore:** valid low-PV evidence retains its 120-second confirmation period. If PV telemetry is already stale or unavailable while `sun.sun` reports `below_horizon`, HPVC enters the same Night Restore safety path immediately instead of remaining stuck in **Waiting for inputs**. New DPEL/OpenDTU writes pause, stale queued actions are invalidated, and available inverter limits are restored to full before PV calculations suspend; already-started physical calls may finish. Daytime PV freshness remains strict. Sunrise recovery requires fresh numeric PV above the configured recovery threshold for 30 continuous seconds. Startup, journal and import recovery preserve the night state and restore obligations.
- **Dispatch and readback:** queued calls are serialized, only unsent stale actions can be superseded, and delayed continuations are checked by generation and dispatch identity. OpenDTU API `Ok` observations count only when requested after the corresponding dispatch; contradictory serial identity and stale or future telemetry are rejected.
- **Full-output proof:** Disable, Smart Update, Remove flows and Full Uninstall require reliable full-output confirmation, with no pending, in-flight or uncertain commands. Independently confirmed already-full controllers do not create false barriers after redundant restore writes. Auto-detected Number writes clear completed barriers when authoritatively verified.
- **Timing:** a matching live full-output readback may confirm restoration after five seconds where appropriate. Slow OpenDTU absolute-Watt readback retains its extended retry and final-verification window (at least 300 seconds). Standard limiting writes retain cooldown-based verification timing.
- **Persistence and failures:** restore obligations survive removal or slot replacement until independently proven; missing evidence blocks destructive cleanup. Recovery-required leases are not silently cleared. Failures remain isolated per inverter where safe, but duplicate physical targets and uncertain ownership block unsafe control.

## 2. Automatic detection and manual migration

### Hoymiles / OpenDTU

- Detect supported MQTT `limit_nonpersistent_absolute` Watt Number controllers using HA entity/device registry roles, including renamed entities; a strict suffix fallback is available when registry data is absent. Persistent/relative limit and on/off entities are excluded.
- Determine full/rated inverter power from **live `/api/limit/status` `max_power` → confirmed API cache → manually entered Full Limit**. The HA Number entity's `max` is only a command capability, never rated power. Missing trusted full power leaves the detected inverter incomplete until configured.
- Preserve confirmed API identity and cached rated power across registry refreshes. Use optional OpenDTU `limit_set_status` evidence; leave the HTTP Request node responsible for its GET method. Multiple OpenDTU devices and mixed installations share the ten-slot ceiling.

### Enphase DPEL

- Detect complete Envoy DPEL controllers from Enphase Envoy Installer 0.10.2+ through registry identity (including renamed entities). Reject ambiguous/incomplete groups and per-microinverter `Production` switches; **one Envoy uses one HPVC slot**, not one slot per microinverter.
- Use native Watt commands/readback. Require DPEL enabled and `Production` mode (with both `Production` and `Export` supported) before a write. Missing/unavailable permission pauses control. Normalize unlimited sentinel readbacks to the HPVC configured Max for display and decision-making.
- **Max power and Min power are configured in HPVC**, not inferred from DPEL Number `min`/`max` metadata. Preserve ranges for a returning controller with the same identity; a different Envoy must receive its own range rather than inheriting stale values. Enphase-only installation needs no placeholder manual slot.

### Existing manual controllers

- Reuse a manual slot only when the automatic controller can be confidently matched to the same physical device; otherwise preserve the manual slot. Uncertain potential duplicates are held rather than controlled twice, with a warning in Settings and diagnostic Reason information.
- Keep saved manual entity, unit and power settings intact for rollback. Automatic adapter identity is effective at runtime, not an instruction to overwrite the user's helpers. **OpenDTU power-source precedence remains API → cache → manual fallback.**
- Freshness checks associate each timestamp with its source entity and reject observations from an old manual entity when the effective controller has changed. Unknown device identity, offline controllers and Action/service adapters are handled conservatively.

## 3. Maintenance, updates and recovery

- The managed **HPVC Maintenance v1.6.0** Node-RED tab owns Smart Update, Recovery Probe, rollback, fingerprinting, manual flow removal and full uninstall. The five managed HPVC tabs are recognized consistently by maintenance and recovery.
- Smart Update retains v1.5.6 activation protections: exclusive leases, stale-result guards, transaction reconciliation, conservative orphan recovery and partial-deployment barriers.
- Destructive maintenance tracks each original inverter restore obligation even if a slot disappears. A reconciliation marked unrecoverable does **not** establish physical full-power restoration. Cleanup remains blocked without the required proof or explicit safe resolution.
- Full uninstall preserves Inputs and Maintenance until completion/final notification, then removes them last; finalizer failure is recorded at `/tmp/hpvc-uninstall-final.failed`.
- Night Restore state and timers share Node-RED global context across Inputs, journal and recovery, with the saved journal remaining the durable restart source. Price-zone cadence and hysteresis memory use shared global context rather than separate tab-local stores.
- Maintenance recognizes registry OpenDTU records and legacy/manual Enphase DPEL Watt normalization. Enphase restore uses HPVC's configured Min/Max, not DPEL command metadata. Recovery and update identification use the selected release version and matching Maintenance-tab identity.

**Maintenance inventory correction:** update, uninstall and flow-removal checks now use a fresh runtime-resolved controller snapshot for slot identity and rated Full Limit, while independently verifying live full-output readback and retaining original restore obligations. Isolated tests pass, but the behavior has **not yet been certified on a live Home Assistant installation**.

## 4. Dashboard, configuration and HBC

- The Settings page uses a persistent native **Inverters** row, supports **zero inverters** as a genuine setup state and hides unused PV configuration until a controller exists. Without a usable controller HPVC remains monitoring-only and the master control stays off.
- Persistent per-slot **HPVC Control** switches allow monitoring without dispatch. An invalid range (Min greater than Max) turns permission off until corrected and explicitly re-enabled; Min equal to Max is valid. The same `sensor.hpvc_inverter_limit_validation` source drives safety gating and dashboard warnings for all ten slots.
- Limit entity names are shown read-only with lock indicators. Main and Settings distinguish manual, Hoymiles and Enphase detected/incomplete/unavailable states. Live Inputs continues to show disabled inverter limit readbacks with `(Off)` labeling.
- Runtime-map UI consumers accept both JSON-string and native-list HA attributes. The empty duplicate card and redundant configuration header have been removed; only existing entities and native Lovelace conditions are required for status presentation.
- **HBC integration is unchanged:** HPVC does not force `Dynamic`. Only executing `Charge`/`Charge PV` activates Charge Priority; other valid HBC states remain visible. Eco Charge stays separate, and negative-price behavior is not conflated with Charge Priority.

## 5. Upgrade and installation

- On supported Home Assistant OS/Supervised installations with the Node-RED add-on, **Smart Update** is preferred *once v1.6.0 is published as a normal GitHub release*. Manual upgrades must replace the Home Assistant package, Node-RED flow and managed dashboard together.
- Upgrade from earlier unreleased candidates using the complete v1.6.0 set; preserve update-recovery data and existing helper values. Review detected inverter identity, Full Limit source, HPVC Control permissions and any migration warnings before enabling output limiting.
- An OpenDTU device with neither live nor cached `max_power` needs **Full Limit** entered manually in its effective slot. An auto-detected Enphase DPEL requires HPVC **Max power / Min power** configuration.

## 6. Validation and outstanding tests

- Pre-release source/mock validations covered controller discovery, action sequencing, Night Restore, HBC Charge Priority, maintenance recovery, support-report TXT/HTML parity, template rendering, version markers and documentation links. Testing tools are not included in the distribution ZIP.
- Regression checks also cover five managed tabs, 2–60-second cadence, Enphase/OpenDTU-only onboarding, action/Number adapters, Max/Min validation and ambiguous/manual controller cases. These are **not** a substitute for live integration tests; legacy assertions about permissive discovery may differ from the stricter identity policy.
- **Still to verify on real Home Assistant/Node-RED and physical inverters:** v1.5.6→v1.6.0 update, rollback, complete uninstall, manual flow removal, nighttime restart, Enphase/OpenDTU restoration and the corrected maintenance inventory reconciliation described above. Keep the release marked pre-release until this testing is complete.
