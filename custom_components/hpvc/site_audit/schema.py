"""Bounded export contract and credential redaction; no persistence capability."""

import copy
import hashlib
import json
import math
import re
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from ..codec import SchemaError

EXPECTED = (
    "number.hms_2000_4t_limit_nonpersistent_absolute",
    "number.hms_1000_2t_limit_nonpersistent_absolute",
)
SCHEMA = "hpvc-site-audit/1"
MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 10000
ENTITY = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
SECRET = re.compile(
    r"password|passwd|token|secret|authorization|api[_-]?key|credential|private[_-]?key",
    re.I,
)
ATTRIBUTES = {
    "min",
    "max",
    "step",
    "unit_of_measurement",
    "options",
    "installed_version",
    "version",
    "hpvc_test_fixture",
    "hpvc_test_transport",
}
NATIVE_IDS = tuple(
    json.loads(
        Path(__file__).with_name("native_entities.json").read_text(encoding="utf-8")
    )
)


def clean_url(value):
    try:
        p = urlsplit(str(value))
        if p.scheme not in ("http", "https") or not p.hostname:
            return ""
        host = p.hostname
        if ":" in host:
            host = "[" + host + "]"
        if p.port:
            host += ":" + str(p.port)
        return urlunsplit((p.scheme, host, p.path, "", ""))
    except ValueError:
        return ""


def redact(value, *, path="", changes=None, depth=0):
    changes = changes if changes is not None else []
    if depth > 20:
        raise SchemaError("Audit nesting limit exceeded")
    if isinstance(value, dict):
        result = {}
        for k, v in value.items():
            if not isinstance(k, str) or len(k) > 512:
                raise SchemaError("Invalid audit key")
            target = path + "/" + k
            if (
                k == "state"
                and isinstance(value.get("entity_id"), str)
                and SECRET.search(value["entity_id"])
            ):
                result[k] = "[REDACTED]"
                changes.append(target)
                continue
            if k not in (
                "authorization_design",
                "production_transport_authorized",
                "physical_writes_authorized",
            ) and SECRET.search(k):
                result[k] = "[REDACTED]"
                changes.append(target)
            else:
                result[k] = redact(v, path=target, changes=changes, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        if len(value) > MAX_ROWS:
            raise SchemaError("Audit row bound exceeded")
        return [
            redact(v, path=path + "/" + str(i), changes=changes, depth=depth + 1)
            for i, v in enumerate(value)
        ]
    if isinstance(value, str):
        if len(value) > 262144:
            raise SchemaError("Audit text bound exceeded")
        stripped = value.strip()
        if stripped.startswith(("{", "[")):
            try:
                parsed = json.loads(value)
            except (ValueError, TypeError):
                pass
            else:
                return json.dumps(
                    redact(parsed, path=path, changes=changes, depth=depth + 1),
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
        if re.match(r"https?://", value):
            cleaned = clean_url(value)
            if cleaned != value:
                changes.append(path)
            return cleaned

        # Scrub credentials even when a URL is embedded in an error/helper string.
        def scrub_uri(match):
            raw = match.group(0)
            if raw.startswith(("http://", "https://")):
                return clean_url(raw)
            try:
                part = urlsplit(raw)
                return (
                    part.scheme + "://[REDACTED]@" + (part.hostname or "")
                    if part.username or part.password
                    else raw
                )
            except ValueError:
                return "[REDACTED_URL]"

        uri_cleaned = re.sub(
            r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s\"'<>()]+", scrub_uri, value
        )
        if uri_cleaned != value:
            changes.append(path)
        # Common embedded credentials in non-JSON free text never leave the audit.
        cleaned = re.sub(
            r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+", r"\1[REDACTED]", uri_cleaned
        )
        cleaned = re.sub(
            r"(?i)((?:password|token|secret|api_key)\s*[:=]\s*)[^\s,;]+",
            r"\1[REDACTED]",
            cleaned,
        )
        if cleaned != value:
            changes.append(path)
        return cleaned
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise SchemaError("Non-finite or unsupported audit value")


def validate_export(value):
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise SchemaError("Unsupported site export schema")
    try:
        encoded = json.dumps(value, allow_nan=False).encode()
    except (ValueError, TypeError) as e:
        raise SchemaError("Invalid finite JSON audit payload") from e
    if len(encoded) > MAX_BYTES:
        raise SchemaError("Audit export exceeds bound")
    allowed = {
        "schema",
        "source",
        "collected_at_utc",
        "ha",
        "states",
        "entity_registry",
        "device_registry",
        "config_entries",
        "native_configuration",
        "native_runtime",
        "legacy",
        "opendtu",
        "references",
        "coverage",
        "collection_errors",
        "redactions",
    }
    if set(value) - allowed:
        raise SchemaError("Unknown site export fields")
    if type(value.get("collected_at_utc")) not in (float, int) or not math.isfinite(
        value["collected_at_utc"]
    ):
        raise SchemaError("Capture timestamp required")
    for key in (
        "states",
        "entity_registry",
        "device_registry",
        "config_entries",
        "opendtu",
        "references",
    ):
        rows = value.get(key, [])
        if not isinstance(rows, list) or len(rows) > MAX_ROWS:
            raise SchemaError("Invalid " + key + " collection")
    states = value.get("states", [])
    if any(
        not isinstance(r, dict) or not ENTITY.fullmatch(str(r.get("entity_id", "")))
        for r in states
    ):
        raise SchemaError("Invalid state identity")
    if len({r["entity_id"] for r in states}) != len(states):
        raise SchemaError("Duplicate state identities")
    for key, id_key in (
        ("entity_registry", "entity_id"),
        ("device_registry", "device_id"),
        ("config_entries", "entry_id"),
    ):
        rows = value.get(key, [])
        if any(not isinstance(r, dict) or not r.get(id_key) for r in rows) or len(
            {r[id_key] for r in rows}
        ) != len(rows):
            raise SchemaError("Invalid/duplicate " + key + " identity")
    return copy.deepcopy(value)


def empty_export():
    return dict(
        schema=SCHEMA,
        source="no_production_observations",
        collected_at_utc=0.0,
        ha={},
        states=[],
        entity_registry=[],
        device_registry=[],
        config_entries=[],
        native_configuration=None,
        native_runtime={"user_reported_installed": False},
        legacy={"user_reported_version": "1.6.0", "user_reported_runtime": "Node-RED"},
        opendtu=[],
        references=[],
        coverage={},
        collection_errors=[],
        redactions=[],
    )


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
