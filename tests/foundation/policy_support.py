"""Shared conversion from independent frozen scenario inputs to typed policy inputs."""

from custom_components.hpvc.control.decisions import (
    PolicySnapshot,
    PolicyController,
    PolicyMemory,
)
from custom_components.hpvc.control.models import (
    Observation,
    Quality,
    ControlSettings,
    NightRestoreState,
    ControllerConfiguration,
    ControllerIdentity,
    LimitUnit,
)
from custom_components.hpvc.execution.models import ExecutionSnapshot
from custom_components.hpvc.hbc.models import HbcPolicyInput
from custom_components.hpvc.inverter.base import EntityRecord
from custom_components.hpvc.inverter.generic_number import GenericNumberAdapter
import json

NOW = 1800000000.0


def make_snapshot(s):
    settings = ControlSettings(**s.get("settings", {}))

    def obs(key):
        value = s.get(key)
        stamp = NOW - s.get("pv_age", 0) if key == "pv" else NOW
        return Observation(
            key,
            value,
            Quality.VALID if value is not None else Quality.UNAVAILABLE,
            stamp,
            NOW,
        )

    controllers = tuple(
        PolicyController(
            "number.inv" + str(i + 1),
            c["current"] if c["available"] else None,
            c["full"],
            c["minimum"],
            c["available"],
            c["participating"],
            True,
            True,
            c["step"] / 100 * c["full"] if c["unit"] == "Percent" else c["step"],
            "signature:" + str(i),
        )
        for i, c in enumerate(s["controllers"])
    )
    memory = PolicyMemory(
        s.get("price_mode"),
        night=NightRestoreState(
            active=s.get("night_active", False),
            entry_candidate_since_utc=NOW - s["night_entry_age"]
            if "night_entry_age" in s
            else None,
            recovery_candidate_since_utc=NOW - s["night_recovery_age"]
            if "night_recovery_age" in s
            else None,
        ),
        release_requested_since_utc=NOW - s["release_age"]
        if "release_age" in s
        else None,
    )
    execution = ExecutionSnapshot(
        pending_verification=s.get("pending", False),
        pending_since_utc=NOW - 1 if s.get("pending") else None,
        frozen_controller_uids=("number.inv1",) if s.get("pending") else (),
        cooldown_until_utc=NOW + s.get("cooldown_remaining", 0)
        if s.get("cooldown_remaining")
        else 0,
        last_command_delta_w=s.get("last_delta"),
        last_command_at_utc=NOW - s["last_age"] if "last_age" in s else None,
    )
    h = s.get("hbc", {})
    hbc = HbcPolicyInput(
        available=bool(h),
        control_enabled=bool(h),
        execution_strategy="Charge" if h else None,
        usable_batteries=1 if h else 0,
        eligible_headroom_w=1000 if h else 0,
        suppress_export_limiting=h.get("suppress", False),
        priority_operational=h.get("operational", False),
        increase_required=h.get("increase", False),
        increase_target_w=h.get("target"),
        response_window_active=h.get("response", False),
        persistent_export_fallback=h.get("fallback", False),
    )
    return PolicySnapshot(
        s["name"],
        NOW,
        obs("grid"),
        obs("pv"),
        obs("market"),
        obs("all_in"),
        controllers,
        settings,
        execution,
        hbc,
        memory,
        s.get("enabled", True),
        s.get("external_release", False),
        s.get("sun_below", False),
        s.get("rebalance", False),
    )


def make_views(s):
    views = []
    for i, c in enumerate(s["controllers"]):
        if not c["participating"] or not c["available"]:
            continue
        uid = "number.inv" + str(i + 1)
        cfg = ControllerConfiguration(
            ControllerIdentity(uid, i + 1, entity_id=uid),
            "signature:" + str(i),
            unit=LimitUnit(c["unit"]),
            full_limit_w=c["full"],
            low_limit_w=c["minimum"],
            limit_number=uid,
        )
        raw = c["current"] / c["full"] * 100 if c["unit"] == "Percent" else c["current"]
        entity = EntityRecord(
            uid,
            str(raw),
            NOW,
            json.dumps(
                dict(
                    min=0,
                    max=100 if c["unit"] == "Percent" else c["full"],
                    step=c["step"],
                    unit_of_measurement="%" if c["unit"] == "Percent" else "W",
                )
            ),
        )
        views.append(GenericNumberAdapter().normalize(cfg, entity, NOW))
    return tuple(views)
