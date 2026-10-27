"""A hard allowlist of HA read commands. No arbitrary request API."""

from custom_components.hpvc.codec import SchemaError
from custom_components.hpvc.site_audit.schema import ENTITY, MAX_ROWS

READ_COMMANDS = frozenset(
    (
        "get_states",
        "get_config",
        "config/entity_registry/list",
        "config/entity_registry/get_entries",
        "config/device_registry/list",
        "config_entries/get",
    )
)


class ReadOnlyHAClient:
    def __init__(self, websocket):
        self.websocket = websocket
        self.counter = 0

    async def read(self, kind, *, entity_ids=None):
        if kind not in READ_COMMANDS:
            raise SchemaError("Mutation/unknown HA command denied")
        msg = {"id": self.counter + 1, "type": kind}
        if kind == "config/entity_registry/get_entries":
            if (
                not isinstance(entity_ids, list)
                or len(entity_ids) > MAX_ROWS
                or any(
                    not isinstance(e, str) or not ENTITY.fullmatch(e)
                    for e in entity_ids
                )
            ):
                raise SchemaError("Explicit bounded entity identities required")
            msg["entity_ids"] = entity_ids
        elif entity_ids is not None:
            raise SchemaError("Unexpected read command parameters")
        self.counter += 1
        await self.websocket.send_json(msg)
        response = await self.websocket.receive_json()
        if (
            response.get("id") != self.counter
            or response.get("type") != "result"
            or response.get("success") is not True
        ):
            raise SchemaError("HA read failed; capture is incomplete")
        return response.get("result")


def validate_ws_origin(expected, response):
    from urllib.parse import urlsplit

    a = urlsplit(expected)
    b = urlsplit(str(response.url))
    scheme = {"http": "ws", "https": "wss"}.get(b.scheme, b.scheme)
    aport = a.port or (443 if a.scheme == "wss" else 80)
    bport = b.port or (443 if scheme == "wss" else 80)
    if response.history or (scheme, b.hostname, bport, b.path, b.query, b.fragment) != (
        a.scheme,
        a.hostname,
        aport,
        a.path,
        a.query,
        a.fragment,
    ):
        raise SchemaError("Redirected WebSocket origin denied before authentication")
