"""Compile adapter-produced service DATA outside the executor; never rebuild it."""

from dataclasses import dataclass
from ..codec import SchemaError
from ..storage import strict_json
from ..inverter.base import ACTION_PATTERN, ENTITY_PATTERN, fingerprint
from .models import Lane

# No direct MQTT/HTTP/shell transport is introduced by Generic Action support.
DENIED_DOMAINS = frozenset(
    ("mqtt", "rest_command", "http", "shell_command", "python_script")
)


def freeze(value):
    if isinstance(value, dict):
        return ("object", tuple((key, freeze(v)) for key, v in value.items()))
    if isinstance(value, list):
        return ("array", tuple(freeze(v) for v in value))
    if value is None or type(value) in (str, int, float, bool):
        return value
    raise SchemaError("Unsupported frozen service value")


def thaw(value):
    if isinstance(value, tuple):
        kind, items = value
        return (
            {k: thaw(v) for k, v in items}
            if kind == "object"
            else [thaw(v) for v in items]
        )
    return value


@dataclass(frozen=True)
class CompiledServiceStep:
    operation_id: str
    batch_id: str
    step_id: str
    sequence_fingerprint: str
    step_fingerprint: str
    domain: str
    service: str
    frozen_target: tuple
    frozen_data: tuple
    target_json: str
    data_json: str
    entity_ids: tuple[str, ...]
    adapter_signature: str
    maintenance_fingerprint: str
    hbc_binding_identity: str = ""


@dataclass(frozen=True)
class NativeBinding:
    entity_id: str
    identity: str
    available: bool = True


@dataclass(frozen=True)
class InvocationBindings:
    plant_uid: str
    owner_epoch: str
    observed: object
    views: tuple = ()
    native_bindings: tuple[NativeBinding, ...] = ()
    hbc_permission: bool = False
    negative_charge_permission: bool = True
    enabled_intent: bool = True


def maintenance_fingerprint(record):
    return fingerprint(
        [
            record.state.value,
            record.owner_token,
            record.owner_epoch,
            record.post_disable_evaluation_id,
        ]
    )


def compile_service_step(reg, op, maintenance, bindings=None):
    step = reg.batch.steps[op.step_index]
    if (
        step.step_id != op.step_id
        or reg.batch.sequence_fingerprint != op.sequence_fingerprint
    ):
        raise SchemaError(
            "Service step does not match the immutable registered sequence"
        )
    if not ACTION_PATTERN.fullmatch(step.action):
        raise SchemaError("Invalid frozen service name")
    domain, service = step.action.split(".")
    if domain in DENIED_DOMAINS:
        raise SchemaError("Direct MQTT/HTTP/shell write services are not admitted")
    target = strict_json(step.target_json)
    data = strict_json(step.data_json)
    if not isinstance(target, dict) or not isinstance(data, dict):
        raise SchemaError("Service objects must already be resolved")
    entities = target.get("entity_id", data.get("entity_id", ()))
    entities = (
        (entities,)
        if isinstance(entities, str)
        else tuple(entities)
        if isinstance(entities, list)
        else ()
    )
    if any(
        not isinstance(e, str) or not ENTITY_PATTERN.fullmatch(e) or e.endswith(".all")
        for e in entities
    ):
        raise SchemaError("An explicit target identity is required")
    binding = reg.adapter_binding
    native_identity = ""
    if reg.lane == Lane.HBC:
        expected = (
            "input_select.house_battery_strategy"
            if reg.hbc_step in ("enter_strategy", "restore_strategy")
            else "input_select.house_battery_strategy_charge_goal"
            if reg.hbc_step in ("enter_goal", "restore_goal")
            else None
        )
        if (
            step.action != "input_select.select_option"
            or expected is None
            or entities != (expected,)
            or data != {"option": op.expected_native_value}
        ):
            raise SchemaError(
                "Only approved ordered HBC select plans have HA transport"
            )
        if bindings is None:
            raise SchemaError(
                "HBC transport registration requires an independent entity binding"
            )
        native = next(
            (b for b in bindings.native_bindings if b.entity_id == expected), None
        )
        if native is None or not native.available or not native.identity:
            raise SchemaError("HBC entity identity is unavailable")
        native_identity = native.identity
    else:
        if (
            binding is None
            or binding.configuration_signature != reg.batch.configuration_signature
            or binding.configuration.identity.uid != op.controller_uid
        ):
            raise SchemaError("Adapter binding must be frozen before service admission")
        method = binding.configuration.method.value
        if reg.adapter_kind in ("enphase", "enphase_dpel"):
            c = binding.candidate
            expected = (
                (
                    ("switch.turn_on", c.enable_entity)
                    if step.phase == "enphase-enable"
                    else ("select.select_option", c.mode_entity)
                    if step.phase == "enphase-production"
                    else ("number.set_value", binding.configuration.limit_number)
                )
                if c
                else None
            )
            if expected is None or (step.action, entities) != (
                expected[0],
                (expected[1],),
            ):
                raise SchemaError("Enphase step escapes its approved adapter binding")
        elif method != "Action/service" and (
            step.action != "number.set_value"
            or entities != (binding.configuration.limit_number,)
        ):
            raise SchemaError("Number service escapes its approved entity")
        if (
            step.phase == "main"
            and step.action == "number.set_value"
            and method != "Action/service"
            and (data.get("value") != op.native_command_value or set(data) != {"value"})
        ):
            raise SchemaError("Represented Number value changed after planning")
    return CompiledServiceStep(
        op.operation_id,
        op.batch_id,
        op.step_id,
        op.sequence_fingerprint,
        fingerprint(step.to_dict()),
        domain,
        service,
        freeze(target),
        freeze(data),
        step.target_json,
        step.data_json,
        entities,
        op.configuration_signature,
        maintenance_fingerprint(maintenance),
        native_identity,
    )
