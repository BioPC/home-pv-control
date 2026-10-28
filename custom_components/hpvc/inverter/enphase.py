"""Enphase DPEL observations and preflight/main plans; no service execution."""

from dataclasses import replace
from ..codec import SchemaError
from ..control.models import AdapterKind, LimitUnit
from .base import OperatingRange, make_batch, finite
from .generic_number import GenericNumberAdapter


class EnphaseAdapter(GenericNumberAdapter):
    def normalize(self, config, entity, now, *, candidate, states, range_bound=True):
        config = replace(
            config,
            identity=replace(
                config.identity,
                uid=candidate.uid,
                adapter=AdapterKind.ENPHASE,
                device_id=candidate.device_id or None,
                entity_id=candidate.limit_entity,
            ),
            unit=LimitUnit.WATTS,
            limit_number=candidate.limit_entity,
        )
        operating = OperatingRange(
            config.full_limit_w if range_bound else 0,
            config.low_limit_w if range_bound else 0,
            "HPVC manual Full limit",
            False,
        )
        view = super().normalize(
            config, entity, now, operating=operating, candidate=candidate
        )
        state_map = {item.entity_id: item for item in states}
        enable = state_map.get(candidate.enable_entity)
        mode = state_map.get(candidate.mode_entity)

        def fresh(item):
            stamp = finite(item.reported_at_utc) if item else None
            return stamp is not None and stamp > 0 and -60 <= now - stamp <= 180

        enabled = (
            enable.state == "on"
            if fresh(enable) and enable.state in ("on", "off")
            else None
        )
        mode_known = (
            fresh(mode)
            and mode.state is not None
            and mode.state.lower() not in ("", "unknown", "unavailable", "none")
        )
        production = mode.state.lower() == "production" if mode_known else None
        options = mode.attributes.get("options", []) if mode else []
        valid = view.valid and "Production" in options and "Export" in options
        available = view.available and enabled is not None and mode_known
        ready = enabled is True and production is True
        reasons = view.reasons + (
            ()
            if "Production" in options and "Export" in options
            else ("DPEL production/export options required",)
        )
        observation = replace(
            view.observation,
            available=available,
            enabled=enabled,
            production_mode=production,
        )
        return replace(
            view,
            observation=observation,
            valid=valid,
            available=available,
            writable_capable=valid,
            independently_verifiable=available and ready,
            readiness_observed=ready,
            reasons=reasons,
        )

    def build_plan(
        self, view, target, *, batch_id, evaluation_id, requested_plant_target_w=None
    ):
        if not view.available:
            raise SchemaError("DPEL unavailable: no futile preflight plan")
        candidate = view.candidate
        if candidate is None:
            raise SchemaError("DPEL identity missing")
        steps = []
        if view.observation.enabled is not True:
            steps.append(
                (
                    "enphase-enable",
                    "switch.turn_on",
                    {},
                    {"entity_id": candidate.enable_entity},
                )
            )
        if view.observation.production_mode is not True:
            steps.append(
                (
                    "enphase-production",
                    "select.select_option",
                    {"option": "Production"},
                    {"entity_id": candidate.mode_entity},
                )
            )
        if steps:
            # The main Watt command must wait for a separate observed-ready snapshot.
            return replace(
                make_batch(
                    view,
                    target,
                    batch_id=batch_id,
                    evaluation_id=evaluation_id,
                    steps=steps,
                    requested_plant_target_w=requested_plant_target_w,
                ),
                requires_readiness=True,
            )
        return super().build_plan(
            view,
            target,
            batch_id=batch_id,
            evaluation_id=evaluation_id,
            requested_plant_target_w=requested_plant_target_w,
        )
