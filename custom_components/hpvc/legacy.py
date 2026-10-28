"""Read-only legacy detection and import previews; never fences or changes legacy."""

from __future__ import annotations
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
from .codec import SchemaError
from .control.models import (
    PlantConfiguration,
    ControlSettings,
    ControllerIdentity,
    ControllerConfiguration,
    ControlMethod,
    LimitUnit,
    ImportTransaction,
    ImportStage,
    LegacyValue,
    ImportIssue,
    EntityMapping,
)
from .storage import ConfigurationState, canonical, strict_json

SENSOR_KEYS = (
    "market_price_sensor",
    "all_in_price_sensor",
    "grid_power_sensor",
    "pv_power_sensor",
)
BOOL_KEYS = (
    "enabled",
    "external_release_request",
    "insights_enabled",
    "notifications",
    "control_hbc_strategy",
    "negative_price_hbc_charge",
)
CONTROLLER_TEXT = (
    "limit_number",
    "action",
    "value_field",
    "fixed_data_json",
    "target_json",
    "pre_actions_json",
    "post_actions_json",
    "readback_entity",
)


def mapping_manifest():
    raw = json.loads(
        Path(__file__).with_name("legacy_mapping.json").read_text(encoding="utf-8")
    )
    return tuple(EntityMapping.from_dict(row) for row in raw["mappings"])


# Static descriptors are loaded once; config-flow callbacks do no filesystem I/O.
MAPPINGS = mapping_manifest()


def detect_legacy(values):
    present = {
        key
        for key in values
        if key.startswith(
            (
                "input_boolean.hpvc_",
                "input_number.hpvc_",
                "input_text.hpvc_",
                "input_select.hpvc_",
                "input_button.hpvc_",
            )
        )
    }
    if "input_number.hpvc_inverter_count" in present:
        return "legacy_detected"
    if present:
        return "legacy_presence_unknown"
    return "unassessed"  # helper absence is not proof that Node-RED is stopped


def build_preview(values: dict[str, str | None], plant_uid: str) -> ImportTransaction:
    captured = tuple(
        LegacyValue(row.source, values.get(row.source)) for row in MAPPINGS
    )
    issues = []

    def issue(key, reason):
        issues.append(ImportIssue(key, reason))

    def number(key, default=None, integer=False):
        raw = values.get(key)
        if raw is None or raw.strip().lower() in ("unknown", "unavailable", "none", ""):
            if default is None:
                issue(key, "missing_or_unavailable")
            return default
        try:
            value = float(raw)
            if (
                value != value
                or abs(value) == float("inf")
                or (integer and not value.is_integer())
            ):
                raise ValueError()
            return int(value) if integer else value
        except (ValueError, TypeError):
            issue(key, "invalid_numeric_value")
            return default

    def boolean(key, default=False):
        raw = values.get(key)
        if raw is None:
            return default
        if raw not in ("on", "off"):
            issue(key, "invalid_boolean_state")
            return default
        return raw == "on"

    def text(key, default=""):
        raw = values.get(key)
        if raw is None:
            return default
        if raw.strip().lower() in ("unknown", "unavailable", "none"):
            issue(key, "unavailable_text")
            return default
        if len(raw) > 255:
            issue(key, "legacy_text_limit_exceeded")
        return raw

    count = number("input_number.hpvc_inverter_count", integer=True)
    settings_values = {
        key: number("input_number.hpvc_" + key)
        for key in ControlSettings.__dataclass_fields__
    }
    switches = {
        key: boolean(
            "input_boolean.hpvc_" + key,
            getattr(
                PlantConfiguration(plant_uid),
                key + "_intent" if key == "enabled" else key,
            ),
        )
        for key in BOOL_KEYS
    }
    sensors = {key: text("input_text.hpvc_" + key) for key in SENSOR_KEYS}
    selected = text("input_select.hpvc_selected_inverter", "PV1")
    controllers = []
    if count is not None and 0 <= count <= 10:
        for slot in range(1, 11):
            prefix = f"hpvc_pv{slot}_"
            active = slot <= count
            if not active and not any(
                key.startswith(
                    (
                        "input_text." + prefix,
                        "input_number." + prefix,
                        "input_select." + prefix,
                        "input_boolean." + prefix,
                    )
                )
                for key in values
            ):
                continue
            kw = {
                key: text(
                    "input_text." + prefix + key,
                    "{}"
                    if key in ("fixed_data_json", "target_json")
                    else "[]"
                    if key in ("pre_actions_json", "post_actions_json")
                    else "value"
                    if key == "value_field"
                    else "",
                )
                for key in CONTROLLER_TEXT
            }
            method = text("input_select." + prefix + "control_method", "Number entity")
            unit = text("input_select." + prefix + "limit_unit", "Watts")
            full = number(
                "input_number." + prefix + "full_limit", None if active else 0.0
            )
            low = number(
                "input_number." + prefix + "low_limit", None if active else 0.0
            )
            step = number("input_number." + prefix + "action_step", 0.0)
            refresh = number("input_number." + prefix + "refresh_seconds", 0.0)
            for key, typ in (
                ("fixed_data_json", dict),
                ("target_json", dict),
                ("pre_actions_json", list),
                ("post_actions_json", list),
            ):
                try:
                    parsed = strict_json(kw[key])
                    if not isinstance(parsed, typ):
                        raise SchemaError("wrong JSON shape")
                    if typ is list:
                        for action in parsed:
                            if not isinstance(action, dict) or not re.fullmatch(
                                r"[a-z0-9_]+\.[a-z0-9_]+", str(action.get("action", ""))
                            ):
                                raise SchemaError("invalid sequence action")
                            if not isinstance(
                                action.get("data", {}), dict
                            ) or not isinstance(action.get("target", {}), dict):
                                raise SchemaError("invalid sequence payload")
                except SchemaError:
                    issue("input_text." + prefix + key, "invalid_json_payload")
            if (
                active
                and method == "Number entity"
                and not re.fullmatch(r"number\.[a-z0-9_]+", kw["limit_number"])
            ):
                issue("input_text." + prefix + "limit_number", "number_entity_required")
            if (
                active
                and method == "Action/service"
                and not re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", kw["action"])
            ):
                issue("input_text." + prefix + "action", "invalid_action")
            if active and method == "Action/service" and not kw["value_field"].strip():
                issue("input_text." + prefix + "value_field", "value_path_required")
            auto = boolean("input_boolean." + prefix + "auto_managed")
            auto_identity = text("input_text." + prefix + "auto_identity")
            disabled = boolean("input_boolean." + prefix + "control_disabled")
            if full is not None and low is not None:
                try:
                    signature = hashlib.sha256(
                        canonical([kw, method, unit, full, low, step, refresh]).encode()
                    ).hexdigest()
                    uid = f"legacy-slot:{plant_uid}:{slot}"  # provisional; registry discovery establishes physical identity later
                    controllers.append(
                        ControllerConfiguration(
                            identity=ControllerIdentity(
                                uid, slot, entity_id=kw["limit_number"] or None
                            ),
                            signature=signature,
                            method=ControlMethod(method),
                            unit=LimitUnit(unit),
                            full_limit_w=full,
                            low_limit_w=low,
                            action_step=step,
                            refresh_seconds=refresh,
                            control_enabled=not disabled,
                            auto_managed=auto,
                            auto_identity=auto_identity,
                            **kw,
                        )
                    )
                except (SchemaError, ValueError) as err:
                    issue("input_select." + prefix + "control_method", str(err))
    elif count is not None:
        issue("input_number.hpvc_inverter_count", "outside_zero_to_ten")
    active_numbers = (
        [
            item.limit_number
            for item in controllers
            if item.identity.slot <= count and item.method == ControlMethod.NUMBER
        ]
        if count is not None
        else []
    )
    if len(set(active_numbers)) != len(active_numbers):
        issue("configuration", "duplicate_active_number_targets")
    candidate = None
    if not issues:
        try:
            candidate = PlantConfiguration(
                plant_uid,
                inverter_count=count,
                settings=ControlSettings(**settings_values),
                controllers=tuple(controllers),
                selected_inverter=selected,
                enabled_intent=False,
                **sensors,
                **{key: value for key, value in switches.items() if key != "enabled"},
            )
        except (SchemaError, TypeError) as err:
            issue("configuration", str(err))
    config_sources = {
        row.source
        for row in MAPPINGS
        if row.disposition in ("configuration", "intent", "inverted")
    }
    config_sources.update(
        f"input_boolean.hpvc_pv{i}_auto_managed" for i in range(1, 11)
    )
    config_sources.update(f"input_text.hpvc_pv{i}_auto_identity" for i in range(1, 11))
    fingerprint = hashlib.sha256(
        canonical([(key, values.get(key)) for key in sorted(config_sources)]).encode()
    ).hexdigest()
    transaction_id = hashlib.sha256(
        (plant_uid + ":" + fingerprint).encode()
    ).hexdigest()
    return ImportTransaction(
        transaction_id,
        fingerprint,
        ImportStage.INVALID if issues else ImportStage.PREVIEW,
        candidate,
        captured,
        tuple(issues),
        MAPPINGS,
        switches["enabled"],
        False,
    )


async def persist_preview(
    store, state: ConfigurationState, transaction: ImportTransaction, *, commit=False
):
    existing = next(
        (
            item
            for item in state.imports
            if item.transaction_id == transaction.transaction_id
        ),
        None,
    )
    if existing and (existing.stage == ImportStage.COMMITTED or not commit):
        return state, existing
    if commit and (
        transaction.stage != ImportStage.PREVIEW
        or transaction.candidate is None
        or transaction.issues
    ):
        raise SchemaError("Cannot commit invalid legacy preview")
    if commit and any(item.stage == ImportStage.COMMITTED for item in state.imports):
        raise SchemaError(
            "Legacy import already committed; cannot overwrite native configuration"
        )
    item = replace(transaction, stage=ImportStage.COMMITTED) if commit else transaction
    imports = tuple(
        row for row in state.imports if row.transaction_id != item.transaction_id
    )
    if len(imports) >= 16:
        raise SchemaError("Import history bound reached; explicit review required")
    new = replace(
        state,
        configuration=transaction.candidate if commit else state.configuration,
        imports=(*imports, item),
    )
    await store.commit(new, store.revision)
    return new, item
