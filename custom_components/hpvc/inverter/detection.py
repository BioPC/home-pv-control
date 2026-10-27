"""Metadata-first controller discovery. Ambiguity fails closed."""

import re
from .base import DiscoveryCandidate, finite, fingerprint


def normalize(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def enphase_role(entry):
    domain = entry.entity_id.split(".", 1)[0]
    for value in entry.metadata_values:
        key = normalize(value)
        if re.search(r"(?:^|_)(?:pv_?limit(?:_enabled|_pct)?|production)$", key):
            return None
        if re.search(r"(?:^|_)dpel_limit$", key):
            return "limit" if domain == "number" else None
        if re.search(r"(?:^|_)dpel_mode$", key):
            return "mode" if domain == "select" else None
        if re.search(r"(?:^|_)dpel(?:_enabled)?$", key):
            return "enable" if domain == "switch" else None
    return None


def opendtu_role(entry):
    return (
        entry.entity_id.startswith("number.")
        and entry.platform.lower() == "mqtt"
        and any(
            re.search(r"(?:^|_)limit_nonpersistent_absolute$", normalize(value))
            for value in entry.metadata_values
        )
    )


def looks_opendtu(device, entry):
    if device is None:
        return False
    text = normalize(
        " ".join(
            (
                device.manufacturer,
                device.model,
                device.model_id,
                device.name,
                device.configuration_url,
                device.identifiers_json,
                *entry.metadata_values,
            )
        )
    )
    return bool(re.search(r"(?:^|_)(?:opendtu|hoymiles|hms|hmt|hm)(?:_|$)", text))


def physical_number_uid(entity_id, registry):
    entry = next((item for item in registry if item.entity_id == entity_id), None)
    if entry:
        if entry.registry_id:
            return (
                "number-registry:"
                + fingerprint([entry.registry_id, entry.device_id])[:32]
            )
        if entry.unique_id:
            return (
                "number:"
                + fingerprint([entry.platform, entry.config_entry_id, entry.unique_id])[
                    :32
                ]
            )
    return "number-entity:" + entity_id


def discover_controllers(registry, devices, states):
    """Return all safe candidates; the fleet manager enforces the ten-slot limit."""
    device_map = {item.device_id: item for item in devices}
    state_map = {item.entity_id: item for item in states}
    metadata = {item.entity_id: item for item in registry}
    groups = {}
    od_groups = {}
    for entry in registry:
        if entry.disabled or not entry.device_id:
            continue
        role = enphase_role(entry)
        if role:
            groups.setdefault(entry.device_id, {"limit": [], "mode": [], "enable": []})[
                role
            ].append(entry)
        if opendtu_role(entry) and looks_opendtu(
            device_map.get(entry.device_id), entry
        ):
            od_groups.setdefault(entry.device_id, []).append(entry)
    found = []
    for device_id, roles in sorted(groups.items()):
        if any(len(rows) != 1 for rows in roles.values()):
            continue
        entries = [roles[key][0] for key in ("limit", "mode", "enable")]
        if (
            len({e.platform for e in entries if e.platform}) > 1
            or len({e.config_entry_id for e in entries if e.config_entry_id}) > 1
        ):
            continue
        limit, mode, enable = entries
        option_state = state_map.get(mode.entity_id)
        options = option_state.attributes.get("options", []) if option_state else []
        if "Production" not in options or "Export" not in options:
            continue
        if any(e.entity_id not in state_map for e in entries):
            continue
        limit_state = state_map[limit.entity_id]
        if str(limit_state.attributes.get("unit_of_measurement", "")).lower() not in (
            "w",
            "watt",
            "watts",
        ):
            continue
        found.append(
            DiscoveryCandidate(
                "enphase:" + device_id,
                "enphase",
                limit.entity_id,
                device_id,
                enable.entity_id,
                mode.entity_id,
                metadata_verified=True,
            )
        )
    for device_id, entries in sorted(od_groups.items()):
        if len(entries) != 1:
            continue
        entry = entries[0]
        device = device_map[device_id]
        state = state_map.get(entry.entity_id)
        if not state or str(
            state.attributes.get("unit_of_measurement", "")
        ).lower() not in ("w", "watt", "watts"):
            continue
        serial = ""
        for value in (device.identifiers_json, *entry.metadata_values):
            match = re.search(r"(?:^|[^0-9])([0-9]{10,16})(?:[^0-9]|$)", value)
            if match:
                serial = match[1]
                break
        found.append(
            DiscoveryCandidate(
                "hoymiles:" + device_id,
                "hoymiles",
                entry.entity_id,
                device_id,
                serial=serial,
                configuration_url=device.configuration_url,
                metadata_verified=True,
            )
        )
    detected = {item.limit_entity for item in found}
    for entity_id, state in sorted(state_map.items()):
        entry = metadata.get(entity_id)
        if entity_id in detected or (
            entry is not None and (entry.device_id or entry.disabled)
        ):
            continue
        if re.fullmatch(r"number\..+_dpel_limit", entity_id):
            stem = entity_id.removeprefix("number.").removesuffix("_dpel_limit")
            enable = "switch." + stem + "_dpel_enabled"
            mode = "select." + stem + "_dpel_mode"
            if any(
                e in metadata and (metadata[e].device_id or metadata[e].disabled)
                for e in (enable, mode)
            ):
                continue
            options = (
                state_map[mode].attributes.get("options", [])
                if mode in state_map
                else []
            )
            if (
                enable in state_map
                and "Production" in options
                and "Export" in options
                and str(state.attributes.get("unit_of_measurement", "")).lower()
                in ("w", "watt", "watts")
            ):
                found.append(
                    DiscoveryCandidate(
                        "enphase-fallback:" + stem,
                        "enphase",
                        entity_id,
                        enable_entity=enable,
                        mode_entity=mode,
                    )
                )
        elif re.fullmatch(r"number\..+_limit_nonpersistent_absolute", entity_id):
            attrs = state.attributes
            maximum = finite(attrs.get("max"))
            if (
                str(attrs.get("unit_of_measurement", "")).lower()
                in ("w", "watt", "watts")
                and maximum is not None
                and maximum > 0
            ):
                found.append(
                    DiscoveryCandidate(
                        "hoymiles-fallback:" + entity_id, "hoymiles", entity_id
                    )
                )
    return tuple(sorted(found, key=lambda item: (item.kind, item.uid)))
