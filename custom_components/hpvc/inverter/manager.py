"""One authoritative read-only fleet. Capability is never write authorization."""

from dataclasses import dataclass, replace
from ..codec import Record
from ..control.models import (
    ControllerConfiguration,
    ControllerIdentity,
    ControlMethod,
    AdapterKind,
)
from .base import AdapterView, fingerprint
from .detection import discover_controllers, physical_number_uid
from .generic_number import GenericNumberAdapter
from .generic_action import GenericActionAdapter
from .hoymiles import HoymilesAdapter, OpenDtuCache
from .enphase import EnphaseAdapter


@dataclass(frozen=True)
class FleetController(Record):
    view: AdapterView
    origin: str = "manual"

    @property
    def uid(self):
        return self.view.configuration.identity.uid

    @property
    def slot(self):
        return self.view.configuration.identity.slot

    @property
    def participating(self):
        return self.view.configuration.control_enabled

    @property
    def status(self):
        if not self.view.valid:
            return "Incomplete"
        if not self.view.available:
            return "Unavailable"
        return (
            "Configured"
            if self.view.configuration.method == ControlMethod.ACTION
            else "Detected"
        )


@dataclass(frozen=True)
class FleetSnapshot(Record):
    configured: tuple[ControllerConfiguration, ...] = ()
    effective: tuple[FleetController, ...] = ()
    overflow_uids: tuple[str, ...] = ()
    removed_uids: tuple[str, ...] = ()
    recovered_uids: tuple[str, ...] = ()
    replacement_pairs: tuple[tuple[str, str, int], ...] = ()
    rebalance_uids: tuple[str, ...] = ()
    faults: tuple[str, ...] = ()

    @property
    def participating(self):
        return tuple(row for row in self.effective if row.participating)

    @property
    def available(self):
        return tuple(row for row in self.effective if row.view.available)

    @property
    def writable_capable(self):
        return tuple(row for row in self.effective if row.view.writable_capable)

    @property
    def independently_verifiable(self):
        return tuple(row for row in self.effective if row.view.independently_verifiable)

    @property
    def available_capacity_w(self):
        return sum(
            row.view.operating_range.full_w
            for row in self.participating
            if row.view.valid and row.view.available
        )

    @property
    def physical_writes_authorized(self):
        return False

    def by_slot(self, slot):
        return next((row for row in self.effective if row.slot == slot), None)


class InverterManager:
    def __init__(self):
        self.current = FleetSnapshot()
        self.status_cache = OpenDtuCache()
        self.candidates = ()
        self.registry = ()
        self.devices = ()
        self._seen = set()
        self._slot_bindings = {}
        self._entity_aliases = {}
        self._rebalance = set()

    def _resolve_entity(self, entity_id, registry):
        if any(row.entity_id == entity_id for row in registry):
            return entity_id
        key = self._entity_aliases.get(entity_id)
        if key:
            matched = next((row for row in registry if row.registry_id == key), None)
            if matched:
                return matched.entity_id
        return entity_id

    def refresh(
        self,
        configuration,
        states,
        registry=None,
        devices=None,
        *,
        now,
        command_cache=None,
    ):
        if registry is not None:
            self.registry = tuple(registry)
        if devices is not None:
            self.devices = tuple(devices)
        registry = self.registry
        devices = self.devices
        state_map = {row.entity_id: row for row in states}
        self.candidates = discover_controllers(registry, devices, states)
        for row in registry:
            if row.registry_id:
                self._entity_aliases[row.entity_id] = row.registry_id
        by_entity = {row.limit_entity: row for row in self.candidates}
        configs = {row.identity.slot: row for row in configuration.controllers}
        configured = tuple(
            configs.get(slot)
            or ControllerConfiguration(
                ControllerIdentity(f"{configuration.plant_uid}:slot:{slot}", slot),
                signature="unconfigured",
            )
            for slot in range(1, configuration.inverter_count + 1)
        )
        selected = []
        used_entities = set()
        used_uids = set()
        faults = []
        for config in configured:
            entity_id = self._resolve_entity(config.limit_number, registry)
            candidate = by_entity.get(entity_id)
            if config.auto_managed:
                # Disappeared auto controls must not turn into optimistic generic controls.
                if candidate is None:
                    continue
            if config.method == ControlMethod.NUMBER and not entity_id:
                continue
            if (
                config.method == ControlMethod.ACTION
                and not config.action
                and not config.readback_entity
            ):
                continue
            if config.method == ControlMethod.NUMBER and entity_id in used_entities:
                faults.append(f"duplicate_number_target:{entity_id}")
                continue
            if config.method == ControlMethod.NUMBER:
                used_entities.add(entity_id)
            selected.append(
                (
                    config,
                    candidate,
                    "auto" if config.auto_managed else "manual",
                    entity_id,
                )
            )
            if candidate:
                used_uids.add(candidate.uid)
        occupied = {config.identity.slot for config, _, _, _ in selected}
        previous_slots = {row.uid: row.slot for row in self.current.effective}
        overflow = []
        for candidate in self.candidates:
            if candidate.uid in used_uids or candidate.limit_entity in used_entities:
                continue
            previous = previous_slots.get(candidate.uid)
            slot = (
                previous
                if previous is not None and previous not in occupied
                else next((i for i in range(1, 11) if i not in occupied), None)
            )
            if slot is None:
                overflow.append(candidate.uid)
                continue
            config = configs.get(slot) or ControllerConfiguration(
                ControllerIdentity(f"{configuration.plant_uid}:slot:{slot}", slot),
                signature="unconfigured",
            )
            # Auto identity does not inherit a different controller's editable range.
            selected.append((config, candidate, "auto", candidate.limit_entity))
            occupied.add(slot)
            used_uids.add(candidate.uid)
            used_entities.add(candidate.limit_entity)
        rows = []
        for config, candidate, origin, entity_id in selected:
            if candidate:
                config = replace(
                    config,
                    identity=replace(
                        config.identity,
                        uid=candidate.uid,
                        entity_id=candidate.limit_entity,
                        device_id=candidate.device_id or None,
                    ),
                    method=ControlMethod.NUMBER,
                )
            elif config.method == ControlMethod.NUMBER:
                uid = physical_number_uid(entity_id, registry)
                config = replace(
                    config,
                    identity=replace(
                        config.identity,
                        uid=uid,
                        entity_id=entity_id,
                        adapter=AdapterKind.NUMBER,
                    ),
                    limit_number=entity_id,
                )
            else:
                readback = self._resolve_entity(config.readback_entity, registry)
                uid = (
                    "action:"
                    + fingerprint(
                        [
                            config.action,
                            config.value_field,
                            config.fixed_data_json,
                            config.target_json,
                            physical_number_uid(readback, registry)
                            if readback
                            else None,
                        ]
                    )[:32]
                )
                config = replace(
                    config,
                    identity=replace(
                        config.identity, uid=uid, adapter=AdapterKind.ACTION
                    ),
                    readback_entity=readback,
                )
            if candidate and candidate.kind == "hoymiles":
                view = HoymilesAdapter().normalize(
                    config,
                    state_map.get(entity_id),
                    now,
                    candidate=candidate,
                    cache=self.status_cache,
                )
            elif candidate and candidate.kind == "enphase":
                previous_bound = self._slot_bindings.get(config.identity.slot)
                legacy_key = "enphase|" + candidate.limit_entity
                bound = (
                    origin == "manual"
                    or config.auto_identity in (candidate.uid, legacy_key)
                    or (
                        not config.auto_identity
                        and previous_bound in (None, candidate.uid)
                    )
                )
                view = EnphaseAdapter().normalize(
                    config,
                    state_map.get(entity_id),
                    now,
                    candidate=candidate,
                    states=states,
                    range_bound=bound,
                )
                self._slot_bindings[config.identity.slot] = candidate.uid
            elif config.method == ControlMethod.ACTION:
                cache = (command_cache or {}).get(config.identity.uid)
                view = GenericActionAdapter().normalize(
                    config,
                    state_map.get(config.readback_entity),
                    now,
                    command_cache_w=cache,
                )
            else:
                view = GenericNumberAdapter().normalize(
                    config, state_map.get(entity_id), now
                )
                if entity_id.endswith("_dpel_limit"):
                    view = replace(
                        view,
                        valid=False,
                        writable_capable=False,
                        reasons=view.reasons + ("incomplete_DPEL_controller",),
                    )
            if any(row.uid == view.configuration.identity.uid for row in rows):
                faults.append(
                    "duplicate_physical_controller:" + view.configuration.identity.uid
                )
                continue
            rows.append(FleetController(view, origin))
        if faults:
            rows = [
                replace(
                    row,
                    view=replace(
                        row.view,
                        writable_capable=False,
                        reasons=row.view.reasons + ("fleet_identity_conflict",),
                    ),
                )
                for row in rows
            ]
        rows = tuple(sorted(rows, key=lambda row: row.slot))
        old = {row.uid: row for row in self.current.effective}
        new = {row.uid: row for row in rows}
        removed = tuple(sorted(set(old) - set(new)))
        recovered = tuple(
            sorted(
                uid
                for uid, row in new.items()
                if row.view.available
                and uid in self._seen
                and (uid not in old or not old[uid].view.available)
            )
        )
        replacements = tuple(
            (old_row.uid, new_row.uid, new_row.slot)
            for new_row in rows
            for old_row in self.current.effective
            if old_row.slot == new_row.slot and old_row.uid != new_row.uid
        )
        self._rebalance.update(uid for uid in recovered if new[uid].participating)
        self._seen.update(new)
        self.current = FleetSnapshot(
            configured,
            rows,
            tuple(overflow),
            removed,
            recovered,
            replacements,
            tuple(sorted(self._rebalance)),
            tuple(faults),
        )
        return self.current

    def watched_entities(self):
        entities = set()
        for row in self.current.effective:
            config = row.view.configuration
            entities.update(
                filter(
                    None,
                    (
                        config.identity.entity_id,
                        config.limit_number,
                        config.readback_entity,
                    ),
                )
            )
            if row.view.candidate:
                entities.update(
                    filter(
                        None,
                        (
                            row.view.candidate.enable_entity,
                            row.view.candidate.mode_entity,
                        ),
                    )
                )
        return tuple(sorted(entities))
