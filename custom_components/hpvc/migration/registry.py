"""CAS registry migration, explicit provenance, fixture-only mutation in dev.7."""

from dataclasses import dataclass, replace
import hashlib
from ..codec import Record, SchemaError
from ..storage import VersionedStore
from .handoff import _FixturePermit, _TEST_KEY
from .model import Stage


@dataclass(frozen=True)
class RegistryIdentity(Record):
    entity_id: str
    unique_id: str
    platform: str
    config_entry_id: str | None


@dataclass(frozen=True)
class RegistryMove(Record):
    identity: RegistryIdentity
    destination: str


@dataclass(frozen=True)
class RegistryJournal(Record):
    transaction_id: str
    moves: tuple[RegistryMove, ...] = ()
    applied: int = 0
    rolled_back: bool = False
    in_progress: int | None = None


def plan_registry_migration(snapshot, legacy, native, desired, *, ownership_manifest):
    """Exact unique-ID/platform/entry tuples from captured HPVC provenance only.

    Renamed legacy IDs remain recorded. Unproven YAML helpers are never seized.
    Cross-domain replacement cannot reuse the legacy domain in HA's registry.
    """
    if legacy not in ownership_manifest or not legacy.unique_id or not legacy.platform:
        raise SchemaError("HPVC package/unique-ID provenance required")
    if native.platform != "hpvc" or not native.unique_id or not native.config_entry_id:
        raise SchemaError("Native config-entry provenance required")
    if native.entity_id.split(".")[0] != desired.split(".")[0]:
        raise SchemaError("HA registry migration cannot change entity domain")
    by_id = {r.entity_id: r for r in snapshot}
    if by_id.get(native.entity_id) != native or by_id.get(legacy.entity_id) != legacy:
        raise SchemaError("Registry snapshot identity changed")
    occupant = by_id.get(desired)
    moves = []
    if occupant and occupant != native:
        if occupant != legacy:
            raise SchemaError("Unrelated target collision; leave unchanged")
        retired = (
            desired.split(".")[0]
            + ".hpvc_legacy_retired_"
            + hashlib.sha256((legacy.unique_id + legacy.platform).encode()).hexdigest()[
                :12
            ]
        )
        if retired in by_id:
            raise SchemaError("Retirement target collision")
        moves.append(RegistryMove(legacy, retired))
    if native.entity_id != desired:
        moves.append(RegistryMove(native, desired))
    return tuple(moves)


class RegistryMigrator:
    def __init__(self, path, transaction_id, *, registry, permit):
        if type(permit) is not _FixturePermit or permit.key is not _TEST_KEY:
            raise SchemaError("Registry edits are fixture-only in dev.7")
        self.registry = registry
        self.store = VersionedStore(path, "migration_registry", RegistryJournal)
        self.current = RegistryJournal(transaction_id)

    async def load(self):
        old = await self.store.load()
        if old:
            if old.transaction_id != self.current.transaction_id:
                raise SchemaError("Different registry migration owner")
            self.current = old
        else:
            await self.store.commit(self.current, 0)

    async def _save(self, **changes):
        value = replace(self.current, **changes)
        await self.store.commit(value, self.store.revision)
        self.current = value

    def _identity(self, entity):
        r = self.registry.async_get(entity)
        return (
            RegistryIdentity(r.entity_id, r.unique_id, r.platform, r.config_entry_id)
            if r
            else None
        )

    async def apply(self, moves, handoff):
        if (
            not handoff.native_owner_ready
            or handoff.stage != Stage.READY
            or handoff.transaction_id != self.current.transaction_id
        ):
            raise SchemaError("Post-fence ownership-ready transaction required")
        if self.current.in_progress is not None and self.current.in_progress < 0:
            raise SchemaError("Interrupted rollback must be reconciled first")
        if self.current.rolled_back:
            raise SchemaError("Rolled-back registry transaction cannot replay")
        if self.current.moves and self.current.moves != tuple(moves):
            raise SchemaError("Registry plan changed")
        if not self.current.moves:
            await self._save(moves=tuple(moves))
        for i, m in enumerate(self.current.moves):
            if i < self.current.applied:
                continue
            expected = replace(m.identity, entity_id=m.destination)
            if (
                self.current.in_progress == i
                and self._identity(m.destination) == expected
                and self._identity(m.identity.entity_id) is None
            ):
                await self._save(applied=i + 1, in_progress=None)
                continue
            if (
                self._identity(m.identity.entity_id) != m.identity
                or self._identity(m.destination) is not None
            ):
                raise SchemaError(
                    "Registry CAS conflict; no unrelated entity overwritten"
                )
            await self._save(in_progress=i)
            self.registry.async_update_entity(
                m.identity.entity_id, new_entity_id=m.destination
            )
            await self._save(applied=i + 1, in_progress=None)

    async def rollback(self):
        # An interrupted apply is reconciled before rollback; never guess whether
        # an external registry operation completed.
        if self.current.in_progress is not None:
            raise SchemaError("Reconcile interrupted apply before rollback")
        while self.current.applied:
            i = self.current.applied - 1
            m = self.current.moves[i]
            expected = replace(m.identity, entity_id=m.destination)
            if (
                self._identity(m.destination) != expected
                or self._identity(m.identity.entity_id) is not None
            ):
                raise SchemaError("Rollback conflict; unrelated entity left untouched")
            # Write-ahead marker makes an interrupted rollback detectable.
            await self._save(in_progress=-(i + 1))
            self.registry.async_update_entity(
                m.destination, new_entity_id=m.identity.entity_id
            )
            await self._save(applied=i, in_progress=None)
        await self._save(rolled_back=True)

    async def reconcile_rollback(self):
        marker = self.current.in_progress
        if marker is None or marker >= 0:
            return
        i = -marker - 1
        m = self.current.moves[i]
        if (
            self._identity(m.identity.entity_id) == m.identity
            and self._identity(m.destination) is None
        ):
            await self._save(applied=i, in_progress=None)
        elif (
            self._identity(m.destination)
            == replace(m.identity, entity_id=m.destination)
            and self._identity(m.identity.entity_id) is None
        ):
            await self._save(in_progress=None)
        else:
            raise SchemaError("Ambiguous interrupted registry rollback")
