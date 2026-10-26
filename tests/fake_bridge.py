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


def plus(device_id: str = "plus-1", dials: int = 4) -> dict[str, Any]:
    """A deck with dials and a touch strip, like a Stream Deck +."""
    data = deck(device_id, 4, 2, 120)
    data["capabilities"]["dials"] = {"count": dials, "press": True}
    data["capabilities"]["touch"] = {"width": dials * 200, "height": 100}
    return data


def neo(device_id: str = "neo-1") -> dict[str, Any]:
    """Like a Stream Deck Neo: 4x2 keys, two lit page buttons, a small screen."""
    data = deck(device_id, 4, 2, 96)
    data["capabilities"]["buttons"] = {"count": 2, "colors": True}
    data["capabilities"]["screen"] = {"width": 248, "height": 58, "formats": ["jpeg", "png"]}
    return data


def studio(device_id: str = "studio-1") -> dict[str, Any]:
    """Like a Stream Deck Studio: 16x2 wide keys, two dials with LED rings, NFC."""
    data = deck(device_id, 16, 2)
    data["capabilities"]["keys"]["image"] = {"width": 144, "height": 112, "formats": ["jpeg", "png"]}
    data["capabilities"]["dials"] = {"count": 2, "press": True, "ring": 24}
    data["capabilities"]["nfc"] = True
    return data


def pedal(device_id: str = "pedal-1") -> dict[str, Any]:
    """Three keys without display, like a Stream Deck Pedal."""
    data = deck(device_id, 3, 1)
    data["capabilities"] = {"keys": {"cols": 3, "rows": 1}}
    return data


class FakeBridge:
    """Listens on 127.0.0.1 (random port)."""

    def __init__(self) -> None:
        self.code = "123456"
        self.tokens: set[str] = {"known-token"}
        self.devices: dict[str, dict[str, Any]] = {"sim-1": deck()}
        self.commands: list[dict[str, Any]] = []
        self.images: dict[tuple[str, int], bytes] = {}
        # Touch strip images by (device, x, y, width, height)
        self.touch_images: dict[tuple[str, int, int, int, int], bytes] = {}
        self.screen_images: dict[str, bytes] = {}
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

    async def turn(self, device: str, dial: int, delta: int) -> None:
        await self.send_all({"type": "dial", "device": device, "dial": dial, "delta": delta})

    async def push_dial(self, device: str, dial: int, pressed: bool) -> None:
        await self.send_all({"type": "dial_press", "device": device, "dial": dial, "pressed": pressed})

    async def button(self, device: str, button: int, pressed: bool) -> None:
        await self.send_all({"type": "button", "device": device, "button": button, "pressed": pressed})

    async def tag(self, device: str, tag_id: str) -> None:
        await self.send_all({"type": "nfc", "device": device, "id": tag_id})

    async def touch(self, device: str, kind: str, x: int, y: int = 50, **end: int) -> None:
        await self.send_all({"type": "touch", "device": device, "kind": kind, "x": x, "y": y, **end})

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
                payload = message.data[2 + length :]
                if header["type"] == "set_screen_image":
                    self.screen_images[header["device"]] = payload
                elif header["type"] == "set_touch_image":
                    area = (header["device"], header["x"], header["y"], header["width"], header["height"])
                    self.touch_images[area] = payload
                else:
                    self.images[(header["device"], header["key"])] = payload
        if ws in self.sockets:
            self.sockets.remove(ws)
        return ws
