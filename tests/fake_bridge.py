"""A small Stream Assistant Bridge for tests (docs/bridge-protocol.md).

Speaks enough of the protocol for the integration: status page, pairing,
hello, device inventory and hot-plug, key events, and it records what the
client sends.
"""

from __future__ import annotations

import json
import struct
from typing import Any

from aiohttp import WSMsgType, web

BRIDGE_ID = "f00dfeedf00dfeed"
BRIDGE_NAME = "Test bridge"


def deck(device_id: str = "sim-1", cols: int = 5, rows: int = 3, size: int = 72, **extra: Any) -> dict[str, Any]:
    """A device object as the bridge reports it."""
    data: dict[str, Any] = {
        "id": device_id,
        "vendor": "Stream Assistant",
        "model": f"Simulated deck {cols}×{rows}",
        "name": f"Deck {device_id}",
        "serial": device_id,
        "firmware": "0.8.0",
        "virtual": True,
        "capabilities": {
            "keys": {"cols": cols, "rows": rows, "image": {"width": size, "height": size, "formats": ["jpeg", "png"]}},
            "brightness": True,
        },
    }
    data.update(extra)
    return data


class FakeBridge:
    """Listens on 127.0.0.1 (random port)."""

    def __init__(self) -> None:
        self.code = "123456"
        self.tokens: set[str] = {"known-token"}
        self.devices: dict[str, dict[str, Any]] = {"sim-1": deck()}
        self.commands: list[dict[str, Any]] = []
        self.images: dict[tuple[str, int], bytes] = {}
        self.sockets: list[web.WebSocketResponse] = []
        self.hellos = 0
        self.port = 0
        self._runner: web.AppRunner | None = None
        # Answer the next hello with this error code instead of welcome
        self.refuse_with: str | None = None

    async def start(self) -> None:
        app = web.Application()
        app.router.add_get("/api/status", self._status)
        app.router.add_get("/ws", self._ws)
        self._runner = web.AppRunner(app)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]

    async def stop(self) -> None:
        await self.drop()
        if self._runner:
            await self._runner.cleanup()

    # Test controls

    async def send_all(self, message: dict[str, Any]) -> None:
        for ws in list(self.sockets):
            if not ws.closed:
                await ws.send_json(message)

    async def press(self, device: str, key: int, pressed: bool) -> None:
        await self.send_all({"type": "key", "device": device, "key": key, "pressed": pressed})

    async def plug(self, data: dict[str, Any]) -> None:
        self.devices[data["id"]] = data
        await self.send_all({"type": "device_added", "device": data})

    async def unplug(self, device_id: str) -> None:
        self.devices.pop(device_id, None)
        await self.send_all({"type": "device_removed", "device": device_id})

    async def drop(self) -> None:
        """Close every connection (bridge restart)."""
        for ws in list(self.sockets):
            await ws.close()
        self.sockets.clear()

    async def replace(self) -> None:
        """Another client took over."""
        await self.send_all({"type": "error", "code": "replaced", "message": "taken over"})
        await self.drop()

    # Handlers

    async def _status(self, request: web.Request) -> web.Response:
        return web.json_response(
            {
                "bridge": {"id": BRIDGE_ID, "name": BRIDGE_NAME, "version": "0.8.0", "platform": "test"},
                "pairing_code": self.code,
            }
        )

    async def _ws(self, request: web.Request) -> web.WebSocketResponse:
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        first = await ws.receive_json()
        welcome = {
            "type": "welcome",
            "protocol": 1,
            "bridge": {"id": BRIDGE_ID, "name": BRIDGE_NAME, "version": "0.8.0", "platform": "test"},
            "features": ["key_images", "brightness"],
        }
        if first.get("type") == "pair":
            if first.get("code") != self.code:
                await ws.send_json({"type": "error", "code": "invalid_code", "message": "wrong"})
                await ws.close()
                return ws
            token = f"token-{len(self.tokens)}"
            self.tokens.add(token)
            await ws.send_json({"type": "paired", "token": token})
        else:
            self.hellos += 1
            if self.refuse_with:
                code, self.refuse_with = self.refuse_with, None
                await ws.send_json({"type": "error", "code": code, "message": "refused"})
                await ws.close()
                return ws
            if first.get("token") not in self.tokens:
                await ws.send_json({"type": "error", "code": "unauthorized", "message": "pair first"})
                await ws.close()
                return ws
        await ws.send_json(welcome)
        await ws.send_json({"type": "devices", "devices": list(self.devices.values())})
        self.sockets.append(ws)
        async for message in ws:
            if message.type == WSMsgType.TEXT:
                self.commands.append(json.loads(message.data))
            elif message.type == WSMsgType.BINARY:
                (length,) = struct.unpack(">H", message.data[:2])
                header = json.loads(message.data[2 : 2 + length])
                self.images[(header["device"], header["key"])] = message.data[2 + length :]
        if ws in self.sockets:
            self.sockets.remove(ws)
        return ws
