# HPVC 2.0 HBC and runtime memory — 2.0.0-dev.4

This development build extends the accepted dev.1 foundation with read-only controller discovery, immutable command-plan representation, independent evidence interpretation, recovery classification and fleet diagnostics. Native inverter and HBC writes do not exist. The physical-write authorization sensor is always Off, including after enable, configuration edits, import, restart and reload.

## Installation and scope

For native development installation, copy only `custom_components/hpvc/` into the Home Assistant configuration's `custom_components/` directory, restart Home Assistant, then add **Home PV Control**. No Node-RED, Node.js or package YAML is required by the native foundation. HACS metadata is supplied, but this build has not been published to HACS or installed into a live HA instance here.

The original v1.6.0 YAML, dashboard, flow, scripts and documentation remain in this tree as the behavioral reference. Do not install those legacy assets as prerequisites for the native integration. An existing legacy installation is not disabled, edited or removed.

The config flow accepts zero controllers. Required-input readiness remains false because final control and verified ownership cutover remain absent. The effective fleet is now available for read-only diagnostics. `switch.hpvc_enabled` represents saved user intent; it cannot authorize a physical action.

## Entity identities alongside legacy

The new configuration domains preserve the approved object names. The integration does not seize or delete legacy-owned entity-registry entries. HA may allocate a suffix to a native entity whose intended ID remains owned by legacy (for example installed version or per-controller control switches). The CSV entity manifest lists intended IDs; actual registry IDs must be inspected during the later verified handoff. Never use the native permission switches as a replacement for legacy master disable in this stage.

## Storage contracts

Five private files are created under HA `.storage/`, prefixed `hpvc_<config-entry-id>`:

- `_configuration.json`: schema 1 envelope, `configuration` kind; PlantConfiguration and bounded ImportTransaction records. Import and initial configuration commit together.
- `_history.json`: schema 1 envelope, `history` kind; current-day history payload boundaries, accuracy eligibility schema 11 / attribution revision 22. Runtime history collection and legacy journal import are deferred.
- `_execution.json`: schema 1 envelope, `execution` kind; execution ledger schema 1, ownership, operations, restore obligations, maintenance, HBC override, active Night Restore and bounded evidence.

Each envelope contains kind, schema version, revision, payload and SHA-256 payload checksum. The checksum detects corruption; it is not an authentication mechanism. Loading rejects unsupported versions/kinds, malformed/duplicate JSON keys, non-finite values, extra/missing record fields, wrong plant identity, invalid references and evidence. A missing ledger beside existing configuration is not treated as an empty safe startup.

Commits serialize under an async lock, validate before writing, fsync a same-directory temporary file, atomically replace the destination and sync the parent directory on POSIX. Windows testing covers file fsync and replacement; it does not prove universal power-loss durability. A commit failure poisons the store until a validated reload. Cancellation drains outstanding filesystem work before returning.

Execution transitions are data representation only: there is no service executor. Armed/in-flight work becomes unknown after continuity loss; restore obligations survive removal from active configuration. Unknown execution blocks conflicting armed work. Referenced proof cannot be evicted to satisfy evidence retention. Evidence is capped at 128; terminal operation retention is bounded. Command-cache/startup assumptions cannot be verified evidence.

- `_policy.json`: `policy_memory` envelope; accepted policy/HBC memory, generation, boot clock and consumed probe-event identities.
- `_accepted_commands.json`: `accepted_commands` envelope; execution-owned simulated events only. Runtime policy evaluation never creates accepted commands. Missing companion files and corruption fail closed.

## Lifecycle and scheduling

One entry-owned scheduler worker uses bounded settings/timer flags, five-second startup delay, ten-second main wake and thirty-second forced full evaluation. Telemetry events mark dirty state without immediate evaluations. Power significance uses the source's strict >20 W AND >2% comparison against the last full snapshot. This phase evaluates and publishes observations only; HBC/final policy-specific rate-limiter bypasses belong to the later engine stage.

Listeners are rebound when configured sensor references change and are removed on unload. Owned workers/timers are cancelled and awaited; filesystem commits drain. Entry-owned registry refresh runs initially after two seconds and every 60 seconds; OpenDTU status refresh runs initially after eight seconds and every 30 seconds. The HTTP worker uses only GET of /api/limit/status with redirects forbidden. No report worker is installed. Setup-failure cleanup is tested. No task is allowed to grant write authorization.

## Legacy import framework

A read-only capture, strict validation and preview cover all 232 helper mappings. Valid configuration imports into native storage once; saved enable intent remains separate and native enable starts Off. Existing inactive-slot configuration is retained. Auto-managed slot provenance is preserved without creating extra controllers. Controller identities are reconciled through registry/device metadata. Imported auto identities remain provenance and cannot grant authorization.

Missing values are not numeric zero, malformed settings are not replaced by defaults, and invalid JSON/action sequences are rejected. Fingerprints ignore runtime diagnostic noise. Idempotent imports cannot overwrite later native settings. User-owned external references are explicitly uninspected and are not rewritten.

No journal import, physical reconciliation, Node-RED context bridge, legacy fencing, handoff completion or production cutover is implemented. Legacy helper absence is not proof that legacy execution has stopped.

## Validation

Run dependency-free behavioral/HA-contract-double tests with:

    python -B scripts/test_foundation.py

These test actual model/storage/scheduler/entity-wrapper code, but the HA contract harness is not a real HA runtime. A separate pinned real-HA suite is in `tests/ha/` and `.github/workflows/validate-foundation.yml`:

    python -m pip install -r requirements-test-ha.txt
    python -m pytest tests/ha -q

Real Linux acceptance runs on the isolated codex/hpvc-readonly-acceptance branch. The matrix pins HA 2025.12.0 / Python 3.13 and HA 2026.10.4 / Python 3.14. Phase A passed 14 real HA and 70 foundation tests per environment before adapter expansion. See docs/phase-a-accepted.md and docs/readonly-stage2.md for the staged scope and evidence.

The safety suite rejects actuator service access and HTTP/MQTT actuator transports anywhere in native integration source. A runtime service-call trap is exercised across setup, entity edits, import, evaluation, reload and unload. The concrete adapters have observation, representation and immutable plan-building interfaces only. The source has no dispatcher or HBC writer. The new pure engine is callable with immutable inputs and returns decisions/allocation/plan data; it is not connected to live scheduler dispatch. The only HTTP transport is a constrained OpenDTU status GET.

## Next stage

The dev.4 raw HBC evaluator, durable memory adapter, authoritative execution snapshot and fake lifecycle acceptance are documented in docs/hbc-stage4.md. Live dispatcher implementation remains a separately scoped later stage. Do not enable actuation, fence legacy, remove old assets or perform production cutover without a separately scoped stage.

## API references checked

- https://developers.home-assistant.io/docs/config_entries_index/
- https://contributors.home-assistant.io/core/integrations/config-entries/
- https://github.com/home-assistant/core/blob/dev/homeassistant/helpers/entity_platform.py
