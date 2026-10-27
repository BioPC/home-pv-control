"""Run on a separate computer. HA reads only; writes a local redacted export."""

import argparse, asyncio, json, os, sys, time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from audit_tools.protocol import ReadOnlyHAClient, validate_ws_origin
from custom_components.hpvc.site_audit.capture import project_observations
from custom_components.hpvc.site_audit.schema import MAX_BYTES, redact
from custom_components.hpvc.codec import SchemaError
from custom_components.hpvc.inverter.base import (
    RegistryEntity,
    RegistryDevice,
    EntityRecord,
)
from custom_components.hpvc.inverter.detection import discover_controllers
from custom_components.hpvc.inverter.hoymiles import async_read_status, status_url


async def collect(base, token, *, read_opendtu=False):
    import aiohttp

    p = urlsplit(base)
    if (
        p.scheme not in ("http", "https")
        or not p.hostname
        or p.username
        or p.password
        or p.query
        or p.fragment
        or p.path not in ("", "/")
    ):
        raise SchemaError("HA base URL must contain only scheme and host/port")
    url = urlunsplit(
        ("wss" if p.scheme == "https" else "ws", p.netloc, "/api/websocket", "", "")
    )
    started = time.time()
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=30), trust_env=False
    ) as session:
        async with session.ws_connect(url, max_msg_size=MAX_BYTES, autoping=True) as ws:
            validate_ws_origin(url, ws._response)
            hello = await ws.receive_json()
            if hello.get("type") != "auth_required":
                raise SchemaError("Unexpected HA authentication protocol")
            await ws.send_json({"type": "auth", "access_token": token})
            if (await ws.receive_json()).get("type") != "auth_ok":
                raise SchemaError("HA read authentication failed")
            client = ReadOnlyHAClient(ws)
            states = await client.read("get_states")
            config = await client.read("get_config")
            entities = await client.read("config/entity_registry/list")
            devices = await client.read("config/device_registry/list")
            entries = await client.read("config_entries/get")
            # List payloads are partial. Read full records only for the scoped IDs
            # selected by the same projection, preserving original unique-ID metadata.
            project_observations(
                states=states,
                entities=entities,
                devices=devices,
                entries=entries,
                ha_version=config.get("version") or hello.get("ha_version"),
                now=time.time(),
            )
            ids = sorted(r["entity_id"] for r in entities)
            full = []
            for i in range(0, len(ids), 100):
                got = await client.read(
                    "config/entity_registry/get_entries", entity_ids=ids[i : i + 100]
                )
                if not isinstance(got, dict):
                    raise SchemaError("Unexpected entity registry response")
                full.extend(r for r in got.values() if r is not None)
            bundle = project_observations(
                states=states,
                entities=full,
                devices=devices,
                entries=entries,
                ha_version=config.get("version") or hello.get("ha_version"),
                now=time.time(),
                coverage={
                    "states": True,
                    "entity_registry": True,
                    "device_registry": True,
                    "config_entries": True,
                    "native_configuration": False,
                    "reference_files": [],
                },
            )
            bundle["ha"]["collection_started_at_utc"] = started
            bundle["ha"]["time_zone"] = config.get("time_zone")
    # A separate session carries NO HA token/header to the OpenDTU hosts.
    if read_opendtu:
        registry = tuple(
            RegistryEntity(
                r["entity_id"],
                r.get("registry_id") or "",
                r.get("device_id") or "",
                r.get("platform") or "",
                r.get("config_entry_id") or "",
                r.get("unique_id") or "",
                r.get("original_name") or "",
                r.get("translation_key") or "",
                r.get("original_entity_id") or "",
                bool(r.get("disabled_by")),
            )
            for r in bundle["entity_registry"]
        )
        devices = tuple(
            RegistryDevice(
                r["device_id"],
                r.get("manufacturer") or "",
                r.get("model") or "",
                r.get("model_id") or "",
                r.get("name") or "",
                r.get("configuration_url") or "",
                json.dumps(r.get("identifiers") or []),
            )
            for r in bundle["device_registry"]
        )
        records = tuple(
            EntityRecord(
                r["entity_id"],
                r.get("state"),
                None,
                json.dumps(r.get("attributes") or {}),
            )
            for r in bundle["states"]
        )
        candidates = discover_controllers(registry, devices, records)
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10), trust_env=False
        ) as status_session:
            for c in candidates:
                if c.kind != "hoymiles" or not c.metadata_verified:
                    continue
                start = time.time()
                try:
                    endpoint = status_url(c.configuration_url)
                    payload = await async_read_status(
                        status_session, c.configuration_url
                    )
                    if payload is None:
                        raise SchemaError("No status payload")
                    # Only fields used by the approved status parser leave this process.
                    payload = {
                        k: {
                            n: v
                            for n, v in row.items()
                            if n in ("max_power", "limit_relative", "limit_set_status")
                        }
                        for k, row in payload.items()
                        if isinstance(row, dict)
                    }
                    bundle["opendtu"].append(
                        dict(
                            device_id=c.device_id,
                            endpoint=endpoint,
                            poll_started_at_utc=start,
                            received_at_utc=time.time(),
                            payload=payload,
                        )
                    )
                except Exception as error:
                    bundle["collection_errors"].append(
                        {
                            "source": "OpenDTU",
                            "device_id": c.device_id,
                            "error_type": type(error).__name__,
                        }
                    )
    changes = []
    bundle = redact(bundle, changes=changes)
    bundle["redactions"] = sorted(set(bundle.get("redactions", []) + changes))
    return bundle


async def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--ha-url", required=True)
    p.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Local output file on this computer, outside production HA",
    )
    p.add_argument(
        "--read-opendtu",
        action="store_true",
        help="Opt in to the existing fixed /api/limit/status GET, no redirects",
    )
    a = p.parse_args()
    token = os.environ.get("HPVC_AUDIT_TOKEN")
    if not token:
        raise SchemaError("Set HPVC_AUDIT_TOKEN locally; never paste it into chat")
    bundle = await collect(a.ha_url, token, read_opendtu=a.read_opendtu)
    raw = json.dumps(bundle, indent=2, allow_nan=False)
    if len(raw.encode()) > MAX_BYTES:
        raise SchemaError("Export exceeds bound")
    a.output.write_text(raw + "\n", encoding="utf-8")
    print("Redacted read-only export saved locally:", a.output)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:
        print(
            "Collection stopped:",
            type(error).__name__,
            "; no error payload or credential is logged",
            file=sys.stderr,
        )
        raise SystemExit(1)
