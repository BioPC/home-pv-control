"""Read-only OpenDTU ratings/status and absolute-Watt representation."""

from dataclasses import dataclass, replace
from urllib.parse import urlsplit
import asyncio
from ..codec import Record, SchemaError
from ..control.models import AdapterKind, LimitUnit
from ..storage import strict_json
from .base import OperatingRange, finite
from .generic_number import GenericNumberAdapter


@dataclass(frozen=True)
class OpenDtuStatus(Record):
    controller_uid: str
    device_id: str
    limit_entity: str
    serial: str
    poll_started_at_utc: float
    received_at_utc: float
    max_power: float | None = None
    limit_relative: float | None = None
    limit_set_status: str = ""


class OpenDtuCache:
    """Entry-owned cache, keyed by controller identity rather than UI slot."""

    def __init__(self):
        self.status = {}
        self.rated = {}

    def accept(self, record):
        previous = self.status.get(record.controller_uid)
        if previous and record.poll_started_at_utc < previous.poll_started_at_utc:
            return False
        self.status[record.controller_uid] = record
        if record.max_power is not None and record.max_power > 0:
            self.rated[record.controller_uid] = record.max_power
        return True

    def rated_power(self, uid, manual_full):
        status = self.status.get(uid)
        if status and status.max_power is not None and status.max_power > 0:
            return status.max_power, "OpenDTU API", True
        cached = self.rated.get(uid)
        if cached is not None and cached > 0:
            return cached, "OpenDTU API cache", True
        if manual_full > 0:
            return manual_full, "HPVC manual Full limit", False
        return 0.0, "Full Limit required", False


def status_url(configuration_url):
    raw = configuration_url.rstrip("/")
    parts = urlsplit(raw)
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
    ):
        raise SchemaError("Invalid read-only OpenDTU base URL")
    return raw + "/api/limit/status"


def parse_status(payload, candidates, *, poll_started_at_utc, received_at_utc):
    if not isinstance(payload, dict) or received_at_utc < poll_started_at_utc:
        return ()
    records = []
    for candidate in candidates:
        serial = candidate.serial
        if serial and serial not in payload:
            continue
        if not serial:
            serial = next((key for key in payload if key in candidate.limit_entity), "")
            if not serial and len(candidates) == 1 and len(payload) == 1:
                serial = next(iter(payload))
        row = payload.get(serial)
        if not isinstance(row, dict):
            continue
        maximum = finite(row.get("max_power"))
        records.append(
            OpenDtuStatus(
                candidate.uid,
                candidate.device_id,
                candidate.limit_entity,
                serial,
                poll_started_at_utc,
                received_at_utc,
                maximum if maximum is not None and maximum > 0 else None,
                finite(row.get("limit_relative")),
                str(row.get("limit_set_status", "")),
            )
        )
    return tuple(records)


async def async_read_status(session, configuration_url):
    """The only HTTP operation is GET of a fixed status endpoint; redirects forbidden."""
    url = status_url(configuration_url)
    async with asyncio.timeout(5):
        async with session.get(url, allow_redirects=False) as response:
            if response.status != 200:
                return None
            raw = await response.text()
            if len(raw) > 1024 * 1024:
                raise SchemaError("OpenDTU status payload too large")
            return strict_json(raw)


class HoymilesAdapter(GenericNumberAdapter):
    def normalize(self, config, entity, now, *, candidate, cache):
        full, source, locked = cache.rated_power(candidate.uid, config.full_limit_w)
        native_min = finite(entity.attributes.get("min")) if entity else None
        low = (
            min(full, max(native_min or 0, config.low_limit_w))
            if full > 0
            else config.low_limit_w
        )
        config = replace(
            config,
            identity=replace(
                config.identity,
                uid=candidate.uid,
                adapter=AdapterKind.HOYMILES,
                device_id=candidate.device_id or None,
                entity_id=candidate.limit_entity,
            ),
            unit=LimitUnit.WATTS,
            limit_number=candidate.limit_entity,
        )
        return super().normalize(
            config,
            entity,
            now,
            operating=OperatingRange(full, low, source, locked),
            candidate=candidate,
        )
