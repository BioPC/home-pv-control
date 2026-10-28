"""Validated migration manifests and restartable current-day history import."""

from dataclasses import dataclass, replace
import hashlib
import re
from enum import Enum
from ..codec import Record, SchemaError
from ..legacy import MAPPINGS, persist_preview
from ..storage import HistoryState, VersionedStore, canonical
from ..control.models import ImportStage


@dataclass(frozen=True)
class ManifestRow(Record):
    old_entity_id: str
    new_entity_id: str
    imported_value_json: str
    validation_result: str
    disposition: str
    external_reference_warning: str = (
        "External automations, scripts and dashboards are not rewritten"
    )


def migration_manifest(transaction, actual_entity_ids=None):
    actual_entity_ids = actual_entity_ids or {}
    values = {v.entity_id: v.raw for v in transaction.captured_values}
    issues = {i.entity_id: i.reason for i in transaction.issues}
    rows = []
    cfg = transaction.candidate
    for m in MAPPINGS:
        value = values.get(m.source)
        disposition = m.disposition
        if (
            cfg
            and m.destination
            and disposition in ("configuration", "intent", "inverted")
        ):
            key = m.destination.split(".hpvc_", 1)[-1]
            match = re.fullmatch(r"pv([0-9]+)_(.+)", key)
            if match:
                controller = next(
                    (c for c in cfg.controllers if c.identity.slot == int(match[1])),
                    None,
                )
                field = {
                    "full_limit": "full_limit_w",
                    "low_limit": "low_limit_w",
                    "control": "control_enabled",
                    "control_method": "method",
                    "limit_unit": "unit",
                }.get(match[2], match[2])
                if controller and hasattr(controller, field):
                    value = getattr(controller, field)
            elif key == "enabled":
                value = cfg.enabled_intent
                disposition = "intent_forced_disabled"
            elif hasattr(cfg, key):
                value = getattr(cfg, key)
            elif hasattr(cfg.settings, key):
                value = getattr(cfg.settings, key)
        if isinstance(value, Enum):
            value = value.value
        rows.append(
            ManifestRow(
                m.source,
                actual_entity_ids.get(m.destination, m.destination) or "",
                canonical(value),
                issues.get(m.source, "valid" if cfg is not None else "import_invalid"),
                disposition,
            )
        )
    # Auto identity provenance is retained explicitly even where an older mapping
    # catalog classified it as runtime diagnostics rather than configuration.
    if transaction.candidate:
        for c in transaction.candidate.controllers:
            for key, value in (
                ("auto_identity", c.auto_identity),
                ("auto_managed", c.auto_managed),
            ):
                old = (
                    "input_text" if key == "auto_identity" else "input_boolean"
                ) + f".hpvc_pv{c.identity.slot}_{key}"
                if not any(r.old_entity_id == old for r in rows):
                    rows.append(
                        ManifestRow(
                            old, "", canonical(value), "valid", "identity_provenance"
                        )
                    )
    return tuple(rows)


@dataclass(frozen=True)
class HistoryImport(Record):
    plant_uid: str
    source_digest: str = ""
    expected_revision: int = 0
    completed: bool = False


class ImportFinalizer:
    def __init__(self, path, plant_uid):
        self.store = VersionedStore(path, "migration_history", HistoryImport)
        self.current = HistoryImport(plant_uid)

    async def load(self):
        old = await self.store.load()
        if old:
            if old.plant_uid != self.current.plant_uid:
                raise SchemaError("Wrong history import plant")
            self.current = old
        else:
            await self.store.commit(self.current, 0)

    async def commit(
        self,
        configuration_store,
        state,
        transaction,
        history_store,
        history,
        *,
        today,
        export=None,
    ):
        # Configuration + import identity commit atomically using the established
        # importer. Repeated import cannot overwrite later native edits.
        state, item = await persist_preview(
            configuration_store, state, transaction, commit=True
        )
        if item.stage != ImportStage.COMMITTED:
            raise SchemaError("Configuration import did not commit")
        if export is None:
            return state, item, history
        if (
            set(export) != {"source_version", "history"}
            or export["source_version"] != "1.6.0"
        ):
            raise SchemaError("Unsupported migration history export")
        candidate = HistoryState.from_dict(export["history"])
        if (
            candidate.plant_uid != state.configuration.plant_uid
            or candidate.local_date != today
        ):
            raise SchemaError("Only compatible current-day history may migrate")
        if len(canonical(candidate.to_dict())) > 512000:
            raise SchemaError("History migration bound exceeded")
        digest = hashlib.sha256(canonical(candidate.to_dict()).encode()).hexdigest()
        old = self.current
        if old.source_digest and old.source_digest != digest:
            raise SchemaError("Different history already prepared")
        if old.completed:
            return state, item, history
        if not old.source_digest:
            if history.local_date is not None:
                raise SchemaError(
                    "Existing native history requires explicit reconciliation"
                )
            old = replace(
                old, source_digest=digest, expected_revision=history_store.revision
            )
            await self.store.commit(old, self.store.revision)
            self.current = old
        if history != candidate:
            if history_store.revision != old.expected_revision:
                raise SchemaError("History changed during interrupted import")
            await history_store.commit(candidate, history_store.revision)
        value = replace(old, completed=True)
        await self.store.commit(value, self.store.revision)
        self.current = value
        return state, item, candidate
