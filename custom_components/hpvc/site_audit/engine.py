"""Pure production-observation audit. Produces proposals, never commands or commits."""

from datetime import datetime
import json
import math
import re
from ..codec import SchemaError
from ..legacy import build_preview
from ..migration.imports import migration_manifest
from ..migration.detector import APPROVED_FINGERPRINT
from ..migration.registry import RegistryIdentity, plan_registry_migration
from ..inverter.base import EntityRecord, RegistryEntity, RegistryDevice, finite
from ..inverter.manager import InverterManager
from ..inverter.hoymiles import parse_status, status_url
from ..inverter.generic_number import represent_target
from ..control.models import PlantConfiguration
from .schema import EXPECTED, NATIVE_IDS, validate_export, redact, digest


def stamp(value):
    if type(value) in (int, float):
        return float(value) if math.isfinite(value) else None
    if isinstance(value, str):
        try:
            d = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return d.timestamp() if d.tzinfo is not None else None
        except ValueError:
            return None
    return None


def age(value, now):
    t = stamp(value)
    return now - t if t is not None and 0 <= now - t <= 86400 * 365 else None


def authorization_design():
    names = (
        "site_readiness_approved",
        "native_ownership_committed",
        "legacy_execution_fenced",
        "no_unresolved_physical_work",
        "current_owner_epoch_valid",
        "configuration_fingerprint_valid",
        "controller_binding_valid",
        "lifecycle_allows_writes",
    )
    return dict(
        required_conditions=list(names),
        expression=" AND ".join(names),
        production_transport_authorized=False,
        dev8_permanent_veto=True,
        enabled_switch_is_intent_only=True,
    )


def registry_audit(bundle, preview, plant_uid):
    registry = bundle.get("entity_registry", [])
    by_id = {r["entity_id"]: r for r in registry}
    native_entries = {
        r["entry_id"]
        for r in bundle.get("config_entries", [])
        if r.get("domain") == "hpvc"
    }
    evidence = bundle.get("legacy", {}).get("registry_ownership", [])
    proven = {
        (
            r.get("entity_id"),
            r.get("unique_id"),
            r.get("platform"),
            r.get("config_entry_id"),
        )
        for r in evidence
        if isinstance(r, dict)
    }
    snap = tuple(
        RegistryIdentity(
            r["entity_id"],
            r.get("unique_id") or "",
            r.get("platform") or "",
            r.get("config_entry_id"),
        )
        for r in registry
    )
    mappings = []
    for intended in NATIVE_IDS:
        key = intended.split(".hpvc_", 1)[-1]
        native = next(
            (
                r
                for r in registry
                if r.get("platform") == "hpvc"
                and r.get("config_entry_id") in native_entries
                and r.get("unique_id") == plant_uid + ":" + key
            ),
            None,
        )
        occupant = by_id.get(intended)
        entry = dict(
            intended_entity_id=intended,
            actual_native_entity_id=native["entity_id"] if native else None,
            occupant=occupant,
            proposal=[],
            collision=False,
            ownership="unoccupied",
            suffix_risk=False,
            manual_review=False,
        )
        if occupant:
            entry["collision"] = (
                not native or occupant["entity_id"] != native["entity_id"]
            )
            if native and occupant["entity_id"] == native["entity_id"]:
                entry["ownership"] = "native_HPVC"
            elif (
                occupant["entity_id"],
                occupant.get("unique_id"),
                occupant.get("platform"),
                occupant.get("config_entry_id"),
            ) in proven:
                entry.update(
                    ownership="legacy_HPVC_proven_by_supplied_manifest",
                    manual_review=True,
                    suffix_risk=True,
                )
                if native:
                    try:
                        old = next(
                            r for r in snap if r.entity_id == occupant["entity_id"]
                        )
                        new = next(
                            r for r in snap if r.entity_id == native["entity_id"]
                        )
                        moves = plan_registry_migration(
                            snap, old, new, intended, ownership_manifest=(old,)
                        )
                        entry["proposal"] = [r.to_dict() for r in moves]
                    except SchemaError as e:
                        entry["review_reason"] = str(e)
                else:
                    entry["review_reason"] = (
                        "Native replacement not installed; capture its exact registry tuple after a later approved installation before planning CAS moves"
                    )
            else:
                entry.update(
                    ownership="unrelated_or_unproven_do_not_touch",
                    manual_review=True,
                    suffix_risk=True,
                    review_reason="Matching name is not HPVC ownership; no reclamation is authorized",
                )
        mappings.append(entry)
    by_dest = {r["intended_entity_id"]: r for r in mappings}
    rows = []
    for row in migration_manifest(preview):
        r = row.to_dict()
        collision = by_dest.get(r["new_entity_id"])
        r.update(
            collision=bool(collision and collision["collision"]),
            ownership=collision["ownership"]
            if collision
            else "domain_change_or_retired",
            manual_review=bool(collision and collision["manual_review"]),
        )
        if (
            r["new_entity_id"]
            and r["old_entity_id"].split(".")[0] != r["new_entity_id"].split(".")[0]
        ):
            r["domain_change"] = True
        rows.append(r)
    return mappings, rows


def audit_site(raw, *, now):
    bundle = validate_export(raw)
    if type(now) not in (int, float) or not math.isfinite(now):
        raise SchemaError("Audit clock required")
    problems = []

    def issue(level, code, reason, required, subject="site"):
        problems.append(
            dict(
                level=level,
                code=code,
                subject=subject,
                reason=reason,
                required_evidence=required,
            )
        )

    measured = bundle.get("source") == "production_export"
    if not measured:
        issue(
            "UNKNOWN",
            "no_production_snapshot",
            "No actual production snapshot was supplied",
            "Read-only HA export and current legacy/OpenDTU/HBC evidence",
        )
    capture_age = age(bundle["collected_at_utc"], now)
    if capture_age is None or capture_age > 120:
        issue(
            "UNKNOWN",
            "snapshot_not_current",
            "Snapshot is missing, future-dated or older than 120 seconds",
            "Recapture together immediately before readiness review; historical exports remain useful inventory only",
        )
    coverage = bundle.get("coverage", {})
    for key in ("states", "entity_registry", "device_registry", "config_entries"):
        if coverage.get(key) is not True:
            issue(
                "UNKNOWN",
                "coverage_" + key,
                "Incomplete " + key + " observations",
                "Complete read-only " + key + " collection with success status",
            )
    if not bundle.get("ha", {}).get("version"):
        issue(
            "UNKNOWN",
            "HA_version",
            "HA version is unobserved",
            "HA get_config or WebSocket handshake version",
        )
    states = {r["entity_id"]: r for r in bundle.get("states", [])}
    legacy_values = {name: str(r.get("state", "")) for name, r in states.items()}
    native_config = bundle.get("native_configuration")
    native_meta = [
        r for r in bundle.get("config_entries", []) if r.get("domain") == "hpvc"
    ]
    if native_meta and native_config is None:
        issue(
            "UNKNOWN",
            "native_configuration_missing",
            "A native entry exists but its configuration was not supplied",
            "Read-only native configuration export; do not install/reload native HPVC to obtain one",
        )
    plant_uid = (
        native_config.get("plant_uid", "site-audit-preview")
        if isinstance(native_config, dict)
        else "site-audit-preview"
    )
    preview = build_preview(legacy_values, plant_uid)
    if preview.issues:
        issue(
            "BLOCKED" if measured and coverage.get("states") else "UNKNOWN",
            "import_validation",
            "Legacy import preview has "
            + str(len(preview.issues))
            + " validation issue(s)",
            "Capture every required helper and resolve invalid values; do not commit an invalid import",
        )
    cfg = preview.candidate or PlantConfiguration(plant_uid)
    if native_config:
        try:
            cfg = PlantConfiguration.from_dict(native_config)
        except SchemaError:
            issue(
                "BLOCKED",
                "native_configuration_invalid",
                "Supplied native configuration fails schema validation",
                "Valid read-only native configuration export",
            )
    registry = []
    for r in bundle.get("entity_registry", []):
        registry.append(
            RegistryEntity(
                r["entity_id"],
                str(r.get("registry_id") or r.get("id") or ""),
                str(r.get("device_id") or ""),
                str(r.get("platform") or ""),
                str(r.get("config_entry_id") or ""),
                str(r.get("unique_id") or ""),
                str(r.get("original_name") or ""),
                str(r.get("translation_key") or ""),
                str(r.get("original_entity_id") or ""),
                bool(r.get("disabled_by")),
            )
        )
    devices = []
    device_meta = {r["device_id"]: r for r in bundle.get("device_registry", [])}
    for r in device_meta.values():
        devices.append(
            RegistryDevice(
                r["device_id"],
                str(r.get("manufacturer") or ""),
                str(r.get("model") or ""),
                str(r.get("model_id") or ""),
                str(r.get("name_by_user") or r.get("name") or ""),
                str(r.get("configuration_url") or ""),
                json.dumps(r.get("identifiers") or []),
            )
        )
    records = tuple(
        EntityRecord(
            r["entity_id"],
            r.get("state"),
            stamp(r.get("last_reported")),
            json.dumps(r.get("attributes") or {}),
        )
        for r in states.values()
    )
    manager = InverterManager()
    manager.refresh(cfg, records, registry, devices, now=now)
    candidates = manager.candidates
    api_identity = {}
    api_problems = {}
    for candidate in candidates:
        if candidate.kind != "hoymiles":
            continue
        captures = [
            r
            for r in bundle.get("opendtu", [])
            if r.get("device_id") == candidate.device_id
        ]
        if len(captures) != 1:
            api_problems[candidate.uid] = "Exactly one bound API capture is required"
            continue
        capture = captures[0]
        try:
            expected_endpoint = status_url(candidate.configuration_url)
        except SchemaError:
            api_problems[candidate.uid] = (
                "Missing/invalid registry OpenDTU configuration URL"
            )
            continue
        start = stamp(capture.get("poll_started_at_utc"))
        received = stamp(capture.get("received_at_utc"))
        if (
            not candidate.serial
            or capture.get("endpoint") != expected_endpoint
            or start is None
            or received is None
            or received < start
            or now - received < 0
            or now - received > 15
            or received - start > 5
            or candidate.serial not in (capture.get("payload") or {})
        ):
            api_problems[candidate.uid] = (
                "API serial, registry endpoint or freshness/latency does not match"
            )
            continue
        parsed = parse_status(
            capture["payload"],
            (candidate,),
            poll_started_at_utc=start,
            received_at_utc=received,
        )
        if len(parsed) != 1 or parsed[0].serial != candidate.serial:
            api_problems[candidate.uid] = "API identity is ambiguous"
            continue
        manager.status_cache.accept(parsed[0])
        api_identity[candidate.uid] = parsed[0]
    fleet = manager.refresh(cfg, records, registry, devices, now=now)
    reg_map = {r.entity_id: r for r in registry}
    entries = {r["entry_id"]: r for r in bundle.get("config_entries", [])}
    inventory = []
    for row in fleet.effective:
        v = row.view
        c = v.candidate
        er = reg_map.get(v.configuration.limit_number)
        dm = device_meta.get(c.device_id if c else er.device_id if er else "", {})
        api = api_identity.get(row.uid)
        ambiguity = []
        ownership = bool(
            er
            and er.registry_id
            and er.unique_id
            and er.device_id
            and er.config_entry_id
            and er.config_entry_id in entries
            and er.config_entry_id in (dm.get("config_entries") or [])
        )
        if c and c.kind == "hoymiles":
            if (
                not c.metadata_verified
                or not ownership
                or er is None
                or entries.get(er.config_entry_id, {}).get("domain") != "mqtt"
            ):
                ambiguity.append("Registry/device/config-entry ownership is incomplete")
            if er and (
                entries.get(er.config_entry_id, {}).get("disabled_by") is not None
                or entries.get(er.config_entry_id, {}).get("state") != "loaded"
            ):
                ambiguity.append(
                    "Owning config entry is not observed loaded and enabled"
                )
            serials = set(
                re.findall(
                    r"(?<![0-9])([0-9]{10,16})(?![0-9])",
                    json.dumps(dm.get("identifiers") or [])
                    + " "
                    + (er.unique_id if er else ""),
                )
            )
            if len(serials) != 1 or c.serial not in serials:
                ambiguity.append("Physical serial provenance is missing or ambiguous")
        if not ownership and not (c and c.kind == "hoymiles"):
            ambiguity.append(
                "Manual/controller registry and physical ownership provenance is incomplete"
            )
        if not v.independently_verifiable:
            ambiguity.append("Controller does not provide independent verification")
        if not v.valid or not v.available:
            ambiguity.append(
                "Controller is invalid, unavailable or stale under the native adapter"
            )
        if c and c.kind == "hoymiles":
            if not api:
                ambiguity.append(api_problems.get(row.uid, "API capture missing"))
            elif (
                api.max_power is None
                or api.limit_relative is None
                or not 0 <= api.limit_relative <= 100
                or str(api.limit_set_status).strip().lower() != "ok"
            ):
                ambiguity.append("API rating/limit/status is incomplete")
            elif v.observation.limit.value is None or abs(
                api.max_power * api.limit_relative / 100 - v.observation.limit.value
            ) > max(1, api.max_power * 0.01 + 0.5):
                ambiguity.append(
                    "Independent API limit disagrees with the HA Number readback"
                )
        if not row.participating:
            ambiguity.append("Controller is opted out")
        item = dict(
            controller_uid=row.uid,
            configuration_signature=v.configuration_signature,
            slot=row.slot,
            origin=row.origin,
            adapter_kind=v.configuration.identity.adapter.value,
            writable_entity=v.configuration.limit_number,
            device_id=c.device_id if c else v.configuration.identity.device_id,
            serial=c.serial if c else None,
            metadata_verified=bool(ownership and (c.metadata_verified if c else True)),
            readback_source=v.current_source.value,
            available=v.available,
            opted_out=not row.participating,
            minimum_w=v.operating_range.minimum_w,
            full_w=v.operating_range.full_w,
            rated_power_provenance=v.operating_range.source,
            actual_limit_w=v.observation.limit.value,
            number_max_is_not_rated_power=True,
            independently_verifiable=v.independently_verifiable,
            api=api.to_dict() if api else None,
            api_endpoint=status_url(c.configuration_url)
            if c
            and c.configuration_url
            and c.kind == "hoymiles"
            and c.uid in api_identity
            else None,
            native_step_w=v.capabilities.step,
            ambiguity=ambiguity,
        )
        inventory.append(item)
        for why in ambiguity:
            issue(
                "BLOCKED" if "disagrees" in why or "opted out" in why else "UNKNOWN",
                "controller_evidence",
                why,
                "Fresh exact registry, device/config-entry and independent OpenDTU capture",
                item["writable_entity"],
            )
    if fleet.faults or fleet.overflow_uids:
        issue(
            "BLOCKED",
            "fleet_ambiguity",
            "Native fleet faults/overflow: "
            + str(fleet.faults)
            + " "
            + str(fleet.overflow_uids),
            "Resolve every effective controller binding and native fleet fault",
        )
    if legacy_values.get("input_boolean.hpvc_enabled") not in ("on", "off"):
        issue(
            "UNKNOWN",
            "legacy_master_intent",
            "Current legacy master intent is unobserved",
            "Current input_boolean.hpvc_enabled state",
        )
    physical_serials = {r.get("serial") for r in inventory if r.get("serial")}
    for serial in physical_serials:
        same = [r for r in inventory if r.get("serial") == serial]
        if len(same) > 1:
            for row in same:
                row["ambiguity"].append(
                    "Multiple effective controllers share one physical serial"
                )
            issue(
                "BLOCKED",
                "duplicate_physical_identity",
                "Multiple registry/device entries resolve to the same physical inverter serial",
                "Resolve aliases/replacement identity; two entity IDs do not establish two inverters",
            )
    expected = []
    for entity in EXPECTED:
        matches = [
            r
            for r in inventory
            if r["writable_entity"] == entity and r["adapter_kind"] == "hoymiles"
        ]
        verified = (
            len(matches) == 1
            and matches[0]["metadata_verified"]
            and not matches[0]["ambiguity"]
        )
        expected.append(
            dict(
                entity_id=entity,
                verified=verified,
                controller_uid=matches[0]["controller_uid"]
                if len(matches) == 1
                else None,
            )
        )
        if not matches:
            issue(
                "BLOCKED"
                if measured
                and coverage.get("entity_registry")
                and coverage.get("device_registry")
                and coverage.get("states")
                else "UNKNOWN",
                "expected_controller_missing",
                "Expected entity is not uniquely discovered as Hoymiles/OpenDTU",
                "Full metadata and current state for this exact entity; an entity ID alone is insufficient",
                entity,
            )
    legacy = bundle.get("legacy", {})
    version = legacy.get("version")
    flow_ok = (
        legacy.get("fingerprint") == APPROVED_FINGERPRINT
        and legacy.get("flow_inventory_complete") is True
        and not legacy.get("foreign_hpvc_candidates")
    )
    if not flow_ok or version != "1.6.0":
        issue(
            "UNKNOWN",
            "legacy_identity",
            "Exact current v1.6 flow/dependency identity is not proven",
            "Complete current Node-RED flow export inspected by the pinned scanner",
        )
    helper_holds = {
        name: legacy_values.get(name)
        for name in (
            "input_boolean.hpvc_update_in_progress",
            "input_boolean.hpvc_update_reload_required",
            "input_boolean.hpvc_auto_resume_pending",
            "input_boolean.hpvc_negative_override_fault",
        )
    }
    for name, value in helper_holds.items():
        if value == "on":
            issue(
                "BLOCKED",
                "legacy_helper_hold",
                "Observed legacy hold/fault helper is On even if another source reports quiet",
                "Fresh reconciled helper and runtime/recovery evidence; do not clear the helper from audit mode",
                name,
            )
    runtime = legacy.get("runtime", {})
    if (
        runtime.get("reachable") is not True
        or age(runtime.get("observed_at_utc"), now) is None
        or age(runtime.get("observed_at_utc"), now) > 15
    ):
        issue(
            "UNKNOWN",
            "legacy_runtime",
            "Runtime reachability/continuity is not currently observed",
            "Timestamped read-only runtime status and heartbeat/owner observation",
        )
    bridge = legacy.get("bridge", {})
    bridge_fields = (
        "active",
        "queued",
        "potentially_issued",
        "pending_verification",
        "restore_obligations",
    )
    if (
        bridge.get("complete") is not True
        or bridge.get("schema") != "hpvc-migration/1.6.0/1"
        or not bridge.get("runtime_owner")
        or bridge.get("runtime_owner") != runtime.get("runtime_owner")
        or bridge.get("flow_fingerprint") != legacy.get("fingerprint")
        or not all(isinstance(bridge.get(k), list) for k in bridge_fields)
        or type(bridge.get("recovery_required")) is not bool
        or age(bridge.get("observed_at_utc"), now) is None
        or age(bridge.get("observed_at_utc"), now) > 15
    ):
        issue(
            "UNKNOWN",
            "legacy_bridge",
            "Required in-memory dispatcher/HBC evidence is unavailable or incomplete",
            "Existing complete version-bound read-only bridge export; absent evidence stays unknown, do not install/deploy a bridge in dev.8",
        )
    elif any(
        bridge.get(k)
        for k in (
            "active",
            "queued",
            "potentially_issued",
            "pending_verification",
            "restore_obligations",
            "recovery_required",
        )
    ):
        issue(
            "BLOCKED",
            "legacy_work",
            "Legacy execution or recovery work is outstanding",
            "Source-supported reconciliation and independent proof in a later approved handoff",
        )
    for k in ("pending_update", "recovery_pending"):
        if runtime.get(k) is True:
            issue(
                "BLOCKED",
                k,
                "Legacy " + k + " is active",
                "Reconciled source runtime and fresh recovery evidence",
            )
        elif runtime.get(k) is not False:
            issue(
                "UNKNOWN",
                k,
                "Legacy " + k + " is unobserved",
                "Explicit timestamped update/recovery indicators",
            )

    def observed(name):
        r = states.get(name)
        a = age(r.get("last_reported"), now) if r else None
        return dict(
            entity_id=name,
            value=r.get("state") if r else None,
            available=bool(
                r
                and str(r.get("state")).lower()
                not in ("unknown", "unavailable", "none", "")
            ),
            age_seconds=a,
            fresh=bool(a is not None and a <= 180),
        )

    telemetry = {
        key: observed(getattr(cfg, key))
        for key in (
            "pv_power_sensor",
            "grid_power_sensor",
            "market_price_sensor",
            "all_in_price_sensor",
        )
    }
    for key, row in telemetry.items():
        if (
            not row["entity_id"]
            or not row["available"]
            or not row["fresh"]
            or finite(row["value"]) is None
        ):
            issue(
                "UNKNOWN",
                "site_telemetry",
                "Configured " + key + " is missing, stale or invalid",
                "Current configured sensor reference, value and last_reported timestamp",
                row["entity_id"] or key,
            )
    hbc = {
        k: observed(name)
        for k, name in [
            ("strategy", "input_select.house_battery_strategy"),
            ("charge_goal", "input_select.house_battery_strategy_charge_goal"),
            (
                "active_sub_strategy",
                "input_text.house_battery_strategy_active_sub_strategy",
            ),
            ("battery_count", "input_number.house_battery_count"),
        ]
    }
    hbc["permission"] = legacy_values.get("input_boolean.hpvc_control_hbc_strategy")
    hbc["negative_price_permission"] = legacy_values.get(
        "input_boolean.hpvc_negative_price_hbc_charge"
    )
    if hbc["permission"] not in ("on", "off") or hbc[
        "negative_price_permission"
    ] not in ("on", "off"):
        issue(
            "UNKNOWN",
            "HBC_permissions",
            "Legacy HBC permission intent is not fully observed",
            "Both current HPVC HBC permission helpers",
        )
    hbc["override_ownership"] = (
        bridge.get("hbc_override_owned") if bridge.get("complete") is True else None
    )
    originals = bridge.get("hbc_originals")
    hbc["retained_originals"] = originals
    hbc["restoration_provable_now"] = bool(
        bridge.get("complete") is True
        and hbc["override_ownership"] is False
        and isinstance(originals, list)
        and len(originals) == 2
        and originals == [hbc["strategy"]["value"], hbc["charge_goal"]["value"]]
        and all(
            hbc[k]["available"] and hbc[k]["fresh"] for k in ("strategy", "charge_goal")
        )
    )
    count = finite(hbc["battery_count"]["value"])
    hbc["batteries"] = []
    if count is not None and count.is_integer() and 0 <= count <= 6:
        for i in range(1, int(count) + 1):
            hbc["batteries"].append(
                dict(
                    index=i,
                    power=observed(f"sensor.marstek_m{i}_ac_power"),
                    soc=observed(f"sensor.marstek_m{i}_battery_state_of_charge"),
                )
            )
    else:
        issue(
            "UNKNOWN",
            "battery_inventory",
            "Battery count is unavailable/invalid",
            "Current HBC battery count and relevant battery power/SOC",
        )
    if not hbc["restoration_provable_now"]:
        issue(
            "UNKNOWN" if hbc["override_ownership"] is None else "BLOCKED",
            "HBC_restoration",
            "HBC originals/restoration or availability cannot currently be proven",
            "Independent current strategy/goal plus retained HPVC original ownership evidence",
        )
    if any(
        not r[k]["available"] or not r[k]["fresh"]
        for r in hbc["batteries"]
        for k in ("power", "soc")
    ):
        issue(
            "UNKNOWN",
            "battery_telemetry",
            "Relevant battery telemetry is stale/unavailable",
            "Current battery power and state-of-charge observations",
        )
    collisions, manifest = registry_audit(bundle, preview, plant_uid)
    if any(
        r["collision"] and r["ownership"] == "unrelated_or_unproven_do_not_touch"
        for r in collisions
    ):
        issue(
            "BLOCKED",
            "unproven_collision",
            "Native intended IDs collide with unrelated/unproven entries",
            "Keep actual native suffixes or obtain exact HPVC ownership provenance; never seize by name",
        )
    if bundle.get("redactions"):
        issue(
            "UNKNOWN",
            "redacted_configuration",
            "Some exported fields were redacted; validate original values locally",
            "Review listed redaction paths; never provide credentials/tokens in chat",
        )
    verdict = (
        "BLOCKED"
        if any(r["level"] == "BLOCKED" for r in problems)
        else "UNKNOWN"
        if problems
        else "READY_FOR_CONTROLLED_HANDOFF"
    )
    plan = select_first_test(
        inventory,
        states,
        now,
        telemetry=telemetry,
        views={r.uid: r.view for r in fleet.effective},
    )
    auth_state = states.get("binary_sensor.hpvc_physical_writes_authorized", {}).get(
        "state"
    )
    if auth_state not in (None, "off"):
        issue(
            "BLOCKED",
            "unexpected_native_authorization",
            "Observed physical-write sensor is not Off",
            "Stop readiness approval and investigate; audit never changes the sensor",
        )
        verdict = "BLOCKED"
    report = dict(
        schema="hpvc-site-readiness-report/1",
        audit_at_utc=now,
        source=bundle.get("source"),
        production_observations_supplied=measured,
        overall_verdict=verdict,
        production_transport_authorized=False,
        ha=bundle.get("ha", {}),
        coverage=coverage,
        native=dict(
            user_reported_installed=bundle.get("native_runtime", {}).get(
                "user_reported_installed"
            ),
            config_entries=native_meta,
            installed=bool(native_meta) if coverage.get("config_entries") else None,
            configuration_supplied=bool(native_config),
            physical_write_sensor_observed=auth_state,
        ),
        legacy=dict(
            user_reported_version=legacy.get("user_reported_version"),
            user_reported_runtime=legacy.get("user_reported_runtime"),
            version=version,
            fingerprint=legacy.get("fingerprint"),
            identity_verified=flow_ok,
            managed_tabs=legacy.get("managed_tabs", []),
            runtime=runtime,
            bridge=bridge,
            master_enable=legacy_values.get("input_boolean.hpvc_enabled"),
            helper_presence=sorted(
                name
                for name in states
                if name.startswith(
                    (
                        "input_boolean.hpvc_",
                        "input_number.hpvc_",
                        "input_text.hpvc_",
                        "input_select.hpvc_",
                    )
                )
            ),
            helper_indicators=helper_holds,
        ),
        expected_controllers=expected,
        controllers=inventory,
        hbc=hbc,
        telemetry=telemetry,
        import_preview=dict(
            stage=preview.stage.value,
            committed=False,
            issues=[r.to_dict() for r in preview.issues],
            settings=manifest,
        ),
        registry_migration=collisions,
        references=bundle.get("references", []),
        external_reference_scope=dict(
            exhaustive=False,
            files_read=coverage.get("reference_files", []),
            unknown_content="Unprovided dashboards, scripts, automations and templates are not checked",
        ),
        blockers_unknowns=problems,
        handoff_projection=dict(
            production_state_advanced=False,
            observational_state="LEGACY_DETECTED"
            if flow_ok
            else "LEGACY_PRESENCE_UNKNOWN",
            import_preview_valid=preview.candidate is not None,
            post_disable_or_fence_proofs_claimed=False,
        ),
        first_hardware_test=plan,
        authorization_design=authorization_design(),
        snapshot_digest=digest(bundle),
    )
    return redact(report)


def select_first_test(inventory, states, now, *, telemetry=None, views=None):
    eligible = []
    for r in inventory:
        if (
            r["adapter_kind"] != "hoymiles"
            or r["ambiguity"]
            or not r["available"]
            or not r["metadata_verified"]
            or not r["api"]
            or not r["independently_verifiable"]
        ):
            continue
        original = r["actual_limit_w"]
        full = r["full_w"]
        step = finite(r["native_step_w"])
        if (
            original is None
            or full <= 0
            or step is None
            or step <= 0
            or abs(original - full) > max(1, full * 0.001)
        ):
            continue
        others = [x for x in inventory if x["controller_uid"] != r["controller_uid"]]
        if any(
            x["device_id"] == r["device_id"]
            or x.get("serial") == r.get("serial")
            or x["writable_entity"] == r["writable_entity"]
            for x in others
        ):
            continue
        desired = min(25.0, full * 0.02)
        delta = math.floor(desired / step) * step
        if delta <= 0:
            continue
        view = (views or {}).get(r["controller_uid"])
        if view is None:
            continue
        target = None
        # Use the actual native representer, including its native step origin.
        # A rounded result outside the small-change budget is not proposed.
        for allocated in (original - delta, original - max(0, delta - step)):
            try:
                represented = represent_target(
                    view.configuration,
                    allocated,
                    view.capabilities,
                    view.operating_range,
                )
            except SchemaError:
                continue
            possible = represented.native_value
            if r["minimum_w"] <= possible and 0 < original - possible <= desired:
                target = possible
                break
        if target is None:
            continue
        if original - target <= max(1, full * 0.01 + 0.5, step * 0.51):
            continue  # The test change must be distinguishable from unchanged/full API readback.
        if not telemetry or not all(
            telemetry.get(k, {}).get("fresh") and telemetry[k].get("available")
            for k in ("pv_power_sensor", "grid_power_sensor")
        ):
            continue
        pv = finite(telemetry["pv_power_sensor"].get("value"))
        grid = finite(telemetry["grid_power_sensor"].get("value"))
        if pv is None or pv < max(100, 2 * (original - target)) or grid is None:
            continue
        eligible.append((original - target, full, r, target))
    if not eligible:
        return dict(
            controller=None,
            status="UNDETERMINED_NO_COMMAND",
            reason="No uniquely bound controller has fresh independent API/rating/full starting limit and a small isolated reversible step",
            executable=False,
            sequence=hardware_sequence(),
        )
    _, _, r, target = min(eligible, key=lambda x: (x[0], x[1], x[2]["controller_uid"]))
    return dict(
        status="PROPOSED_FOR_LATER_EXPLICIT_APPROVAL",
        executable=False,
        controller=r["writable_entity"],
        controller_uid=r["controller_uid"],
        configuration_signature=r["configuration_signature"],
        serial=r["serial"],
        device_id=r["device_id"],
        initial_observed_limit_w=r["actual_limit_w"],
        proposed_test_limit_w=target,
        expected_watt_difference=r["actual_limit_w"] - target,
        restoration_target_w=r["actual_limit_w"],
        rated_full_w=r["full_w"],
        maximum_observation_seconds=30,
        required_readback="Fresh HA Number plus matching-serial OpenDTU limit_relative * max_power and Ok status; then independent PV/grid response",
        grid_abort_threshold_w=None,
        grid_abort_note="A site-specific grid/PV variability bound must be approved before execution",
        other_controller_must_remain_unchanged=True,
        starting_site_observations=telemetry,
        sequence=hardware_sequence(),
    )


def hardware_sequence():
    return [
        "Separately approve handoff and one-controller test; audit approval alone never authorizes commands",
        "Revalidate committed ownership, deployed legacy fence, owner epoch and lifecycle",
        "Require fresh full starting HA/API observations and no outstanding operations or HBC restoration",
        "Bind exact registry/device/config-entry/serial and configuration fingerprint",
        "Record starting limit, PV/grid, other-controller limit and approved abort bounds",
        "Issue exactly one bounded command through a later approved dispatcher; never from audit mode",
        "Verify matching-serial API and HA readback within 30 seconds; service return is not proof",
        "Observe independent PV response while checking grid and other-controller isolation",
        "Restore the captured original full limit through the approved recovery path",
        "Independently verify HA/API restoration and no unresolved obligation, then stop",
        "On stale telemetry, API mismatch, unavailability, wrong readback, grid deviation, timeout, HA reload, Node-RED activity or identity change: stop new tests; retain uncertainty; enter restoration/recovery",
        "Do not blindly replay on timeout/reload or command a replaced controller; if ownership/identity cannot be proven, hold recovery for operator reconciliation",
    ]
