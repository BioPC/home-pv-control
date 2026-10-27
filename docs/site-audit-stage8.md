# Dev.8: read-only audit of your actual site

Production remains legacy HPVC v1.6 / Node-RED. Native dev.7 is not installed there. Do not install native HPVC or a migration bridge for this audit. Do not disable Node-RED, request safe disable, edit/deploy flows, rename entities, commit an import or issue a Number/HBC service call.

The tooling runs locally on a separate computer and consumes observations. Local report/export file creation is its only write. Nothing registers an audit service or UI control in HA. The real executor and all dev.1–7 tests/control modules remain unchanged. The supplied site report is UNKNOWN because no production observations have been provided; no actual first-test target is invented.

## What to provide

Provide these artifacts privately after local redaction. Never send a HA token, password, MQTT credentials, Node-RED credentials file or a full HA backup. Site captures must not be committed to the public development branch.

1. **HA observation export**, including HA version; relevant states with `last_reported`/`last_updated`; full entity-registry tuples (registry ID, entity ID, unique ID, platform, device ID, config-entry ID, original metadata and disabled state); relevant device metadata/identifiers and config-entry ownership; config-entry public metadata only. The collector below creates this without a native HPVC installation.
2. **Current complete Node-RED flow export**, saved locally as JSON using the existing editor's Export → all flows. Do not deploy anything. The local scanner emits only exact tab IDs, content/dependency fingerprint and candidate findings; it never exports raw code or credentials into the report. If only selected tabs can be exported, omit `--full-flow-export`; completeness stays unknown. Shared HA/global configuration dependencies are needed for the dev.7 fingerprint. A deployment-specific difference is a review item, not permission to accept a new fingerprint.
3. **Read-only legacy runtime/context evidence, only if already observable without deployment**. Save a copy of `audit_tools/legacy-context-template.json` and fill only observed values. Keep unknown keys absent/null; do not turn an empty queue assumption into evidence. Use the existing Node-RED context/sidebar/runtime-status facilities; do not add a debug/function node, deploy a bridge or stop the runtime. If full evidence cannot be obtained this way, leave it unavailable and the audit will remain UNKNOWN.
4. **Current OpenDTU status for both controllers**, collected by the optional existing read-only GET or saved separately. Each capture wrapper needs `device_id`, exact `endpoint`, `poll_started_at_utc`, `received_at_utc` and `payload`. Payload keys must contain the same inverter serial as registry/device metadata and the actual `max_power`, `limit_relative` and `limit_set_status`. The expected native status is `Ok`. Do not issue a limit command to obtain a status.
5. **Readable HPVC-owned/configured reference files**: the installed HPVC dashboard YAML/JSON, HPVC package YAML, current Node-RED flow and any explicitly selected scripts/automations/templates you want checked. These are local read copies. Reports list which files were scanned; unprovided user content is not claimed to be checked.
6. If native HPVC is absent, provide **no native configuration**. That absence is expected here. A native entity-ID reclamation plan cannot name a future native registry tuple until that tuple actually exists. Existing unrelated entries are never assumed reclaimable.

Expected controller entity IDs are:

- `number.hms_2000_4t_limit_nonpersistent_absolute`
- `number.hms_1000_2t_limit_nonpersistent_absolute`

These names are expectations only. The audit runs the existing native discovery/manager and importer. Stable registry/device/config-entry/serial binding, a matching API endpoint and independent readback are required. Rated power comes from a fresh matching-serial OpenDTU API record, never the HA Number maximum or model name.

## Option A: collector on a separate computer

Use Python 3.13+ and an existing HA access token kept locally. No token is requested in chat. The utility does not create credentials. If you have no existing token, use Option B in the already authenticated browser instead; no account/token change is required by that option.

Create a local virtual environment beside the extracted development bundle and install `audit_tools/requirements.txt` there. This is local tooling setup, not a production HA install. In PowerShell:

```powershell
py -3.13 -m venv .audit-venv
.\.audit-venv\Scripts\python.exe -m pip install -r audit_tools\requirements.txt
$hpvcAuditSecret = Read-Host 'Existing HA token (local only)' -AsSecureString
$env:HPVC_AUDIT_TOKEN = [System.Net.NetworkCredential]::new('', $hpvcAuditSecret).Password
.\.audit-venv\Scripts\python.exe audit_tools\collect_site.py --ha-url 'https://YOUR-HA-HOST:8123' --read-opendtu --output '..\ha-site-export.json'
Remove-Item Env:\HPVC_AUDIT_TOKEN
```

Substitute the real HA base URL locally. The output is a separate local file. Keep TLS verification enabled. `--read-opendtu` is optional and explicitly opts into the already-approved fixed `/api/limit/status` GET. It has a five-second bound and refuses redirects. A separate HTTP session carries no HA token/header to OpenDTU. No MQTT write or other HTTP command is supported.

HA WebSocket traffic is hard-allowlisted to `get_states`, `get_config`, `config/entity_registry/list`, `config/entity_registry/get_entries`, `config/device_registry/list` and `config_entries/get`. Authentication is performed only after checking the final WebSocket origin and rejecting redirects. There is no arbitrary command or service parameter. Collection failures stop with an error type and do not print raw authentication/error payloads. Insufficient read permission is missing evidence, not a reason to broaden the tool into a mutation client.

## Option B: existing authenticated HA browser

Open the existing HA browser tab and its developer console. Review/run `audit_tools/browser_read_export.js`. It calls only the same six read commands and copies a JSON read export to your computer's clipboard. Save it locally as `ha-raw-read.json`. No token is exported or created and no flow/service is invoked.

The raw read export may contain unrelated state attributes. Keep it local. Project and redact it before sharing:

```powershell
py -3.13 audit_tools\site_audit.py --raw-ha-export '..\ha-raw-read.json' --output-directory '..\site-audit-output'
```

This offline projection keeps relevant helper/controller/collision/HBC observations and strips config-entry data/options, unrelated personal sensors and credentials. Preserve registry IDs, unique IDs, device/config-entry IDs, inverter serials and timestamps: these are the physical identity evidence. Hardware identifiers and relevant device URLs are retained intentionally; URL user-info/query/fragment and credential-like payload fields are redacted. Review the resulting snapshot locally before sharing. Do not send the raw browser export.

## Generate the complete local audit

Node.js 22+ is needed only for the pinned pure flow scanner. It reads JSON without evaluating Function code or modifying flows.

```powershell
py -3.13 audit_tools\site_audit.py --input '..\ha-site-export.json' --flows '..\current-node-red-flows.json' --full-flow-export --legacy-context '..\legacy-context-readonly.json' --reference-file '..\installed-hpvc-dashboard.yaml' --reference-file '..\installed-hpvc-package.yaml' --output-directory '..\site-audit-output'
```

Omit any unavailable optional input. Use `--raw-ha-export` instead of `--input` for the browser alternative. Repeat `--reference-file` for explicitly selected additional files. A manually saved OpenDTU wrapper can be supplied with repeatable `--opendtu-capture`. Do not supply both a collector capture and a duplicate wrapper for the same device; ambiguous duplicate API evidence is rejected. The scanner reports partial flow inventory if `--full-flow-export` is omitted.

Outputs are `site-snapshot.json`, `site-readiness.json`, the 14-section `site-readiness-report.txt`, `import-preview.csv`, `registry-proposal.json` and `external-references.json`. The utility refuses to overwrite any input file. It never writes back to HA/Node-RED or changes any ownership record.

The no-data report can be reproduced with:

```powershell
py -3.13 audit_tools\site_audit.py --empty-site --output-directory '..\site-audit-output'
```

## Exact legacy evidence contract

The context wrapper has an explicit capture timestamp and runtime reachability/owner/update/recovery observations. `global_context` may contain only observed copies of the pinned dev.7 bridge keys:

- `homePvControlAdapterRequests`, `homePvControlAdapterScheduler`
- `homePvControlPendingWriteVerification`, `homePvControlDisableRestoreState`
- `homePvControlNegativePriceHbcOverride`
- `homePvControlAdapterSafetyBlocked`, `homePvControlAdapterResync`, `homePvControlRuntimeEvaluationLock`
- `homePvControlUninstallShutdownActive`, `homePvControlUninstallShutdownStartedAt`, `homePvControlUninstallShutdownLastEvaluationAt`, `homePvControlUninstallShutdownCompletedAt`
- `homePvControlAdapterRuntimeOwner`, `homePvControlAdapterConfigSignatures`, `homePvControlNightRestoreFullConfirmation`

`flow_context` may contain the existing `homePvControlNightRestoreActive` observation. `hbc_originals` must be an actually retained HPVC strategy/goal pair, not an invented value copied from current state. Scheduler/request/restore shapes and runtime owner are checked. An absent, cold or unreadable context remains incomplete. Do not deploy a new bridge to clear this unknown in dev.8. The report distinguishes user-reported legacy v1.6/native-not-installed facts from observed metadata.

## Freshness and review

An archive is useful inventory, not permanent live readiness. A readiness assessment requires a coherent export no older than 120 seconds, current controller states, matching API captures no older than 15 seconds with at most five seconds of poll latency, and current runtime/bridge observations. Old/future/missing timestamps are not replaced with the collection time. Manual asynchronous exports may remain UNKNOWN; that is the correct result when simultaneity cannot be established. Fresh execution-time observations are mandatory again in a later hardware stage.

The import is the actual legacy importer in preview only. All imported values, issues, domain changes, collisions, ownership and review requirements are reported. No store commit occurs. Registry proposals use the dev.7 pure planner only when exact old and native ownership tuples exist; no registry apply API is available to the audit. A same-name template entity is not assumed HPVC-owned. User-created content is never exhaustively claimed to be checked.

## First hardware candidate and disabled authorization design

A later first test is limited to one uniquely bound Hoymiles controller with fresh matching API/readback, certain API rating, available PV/grid telemetry and an original full starting limit. Changes are represented by the actual native Number representer, including its native step origin, and capped at the smaller of 25 W and 2% of rating; they must also exceed the native API verification tolerance. Controller isolation and reversibility are checked. If the observations are absent, there is no selection and no guessed numeric target. The tool does not choose from the HMS model names.

A proposed test has a 30-second maximum observation window, exact captured full/original restoration target and independent HA/API/PV/grid checks. A site-specific grid/PV variability abort bound still requires approval. Any stale telemetry, API mismatch, unavailable inverter, wrong readback, unexpected grid change, timeout, HA reload, Node-RED activity or controller replacement stops further tests and retains restoration/recovery obligations. A replaced or uncertain controller is never blindly commanded for restoration.

The authorization design requires site approval, committed native ownership, deployed legacy fencing, no unresolved physical work, current owner epoch, configuration fingerprint, controller binding and allowed lifecycle. Dev.8 keeps a separate permanent veto. A readiness verdict or `switch.hpvc_enabled` cannot authorize physical transport. If native HPVC is not installed, an absent physical-write sensor is reported as absent; the audit does not create it or falsely report an observed Off state.

## Primary API references

Read commands and authentication follow the [official HA WebSocket API](https://contributors.home-assistant.io/core/internals/websocket-api/). Full registry records use the pinned read APIs in [HA 2025.12.0](https://raw.githubusercontent.com/home-assistant/core/2025.12.0/homeassistant/components/config/entity_registry.py) and [HA 2026.10.4](https://raw.githubusercontent.com/home-assistant/core/2026.10.4/homeassistant/components/config/entity_registry.py). The collector explicitly reads extended records because list records are partial. All collected data and proposed plans are review evidence, not authorization.
