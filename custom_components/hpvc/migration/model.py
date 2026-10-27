"""Strict migration evidence, independent of production execution ownership."""

from dataclasses import dataclass
from enum import StrEnum
from ..codec import Record, SchemaError
from ..hbc.state import Clock


class Stage(StrEnum):
    UNASSESSED = "unassessed"
    UNKNOWN = "legacy_presence_unknown"
    DETECTED = "legacy_detected"
    IMPORT = "import_prepared"
    QUIESCING = "legacy_quiescing"
    RECONCILING = "legacy_reconciling"
    RESTORED = "legacy_restored"
    FENCING = "legacy_fencing"
    POST = "post_fence_verify"
    READY = "native_owner_ready"
    DISABLED = "ready_disabled"
    ACTIVE = "native_active"
    BLOCKED = "blocked_recovery"


@dataclass(frozen=True)
class Binding(Record):
    uid: str
    signature: str
    entity_id: str
    full_w: float
    source: str = "ha_readback"
    device_identity: str = ""


@dataclass(frozen=True)
class NightEvidence(Record):
    reference: str
    binding: Binding
    confirmed: Clock
    last_possible_issue_utc: float
    value_w: float
    current_night_observed: Clock
    night_active: bool = False
    independently_verified: bool = False


@dataclass(frozen=True)
class Proof(Record):
    binding: Binding
    value_w: float | None
    observed: Clock
    available: bool = True
    night_reference: str = ""
    device_identity: str = ""
    enabled: bool | None = None
    production_mode: bool | None = None
    command_status: str = ""


@dataclass(frozen=True)
class Bridge(Record):
    version: str
    runtime_boot: str
    fingerprint: str
    transaction_id: str
    challenge: str
    observed: Clock
    complete: bool = False
    master_off: bool = False
    disabled_at: float = 0.0
    evaluated_at: float = 0.0
    active: tuple[str, ...] = ()
    queued: tuple[str, ...] = ()
    potentially_issued: tuple[str, ...] = ()
    pending_verification: tuple[str, ...] = ()
    restore_obligations: tuple[str, ...] = ()
    hbc_owned: bool = False
    hbc_restored: bool = False
    hbc_available: bool = False
    hbc_original: tuple[str, str] = ("", "")
    hbc_current: tuple[str, str] = ("", "")
    hbc_observed: Clock | None = None
    quiescent: bool = False
    safety_unknown: bool = True
    fence_token: str = ""
    command_capability: bool = True
    auto_resume_blocked: bool = False
    night_evidence: tuple[NightEvidence, ...] = ()
    controller_bindings: tuple[Binding, ...] = ()


@dataclass(frozen=True)
class Inventory(Record):
    observed: Clock
    reachable: bool = False
    complete: bool = False
    fingerprint: str = ""
    known_nodes: tuple[str, ...] = ()
    helpers: tuple[str, ...] = ()
    runtime_status: str = "unknown"
    heartbeat_boot: str = ""
    managed_present: bool = False
    pending_update: bool = False
    recovery_pending: bool = False
    bridge: Bridge | None = None


@dataclass(frozen=True)
class Handoff(Record):
    plant_uid: str
    transaction_id: str = ""
    stage: Stage = Stage.UNASSESSED
    legacy_fingerprint: str = ""
    runtime_boot: str = ""
    configuration_fingerprint: str = ""
    bindings: tuple[Binding, ...] = ()
    import_id: str = ""
    disabled_requested: Clock | None = None
    restored_at: Clock | None = None
    fence_token: str = ""
    fence_observed: Clock | None = None
    native_owner_ready: bool = False
    production_transport_authorized: bool = False
    reason: str = ""
    resume_stage: Stage | None = None
    history: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.plant_uid or self.production_transport_authorized:
            raise SchemaError("Migration cannot authorize production transport")
        if self.native_owner_ready and self.stage not in (Stage.READY, Stage.DISABLED):
            raise SchemaError("Ready claim has inconsistent stage")
        if len(self.history) > 128 or len({b.uid for b in self.bindings}) != len(
            self.bindings
        ):
            raise SchemaError("Invalid migration retention/bindings")
        if self.native_owner_ready and not all(
            (
                self.transaction_id,
                self.fence_token,
                self.fence_observed,
                self.restored_at,
                self.import_id,
            )
        ):
            raise SchemaError("Incomplete ownership-ready provenance")
