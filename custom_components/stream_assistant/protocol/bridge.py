"""Client for the Stream Assistant Bridge protocol (docs/bridge-protocol.md).

Home Assistant independent: needs an aiohttp ClientSession only.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
import contextlib
from dataclasses import dataclass
import json
import logging
import struct
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

PROTOCOL_VERSION = 1
DEFAULT_PORT = 5390
SERVICE_TYPE = "_stream-assistant._tcp.local."
CONNECT_TIMEOUT = 10
# WebSocket ping interval; aiohttp closes the connection when the pong is missing
HEARTBEAT = 10
BACKOFF_MIN = 1.0
BACKOFF_MAX = 30.0
# Another client took over the bridge: do not fight over it every second
REPLACED_BACKOFF = 60.0


class BridgeError(Exception):
    """The bridge refused or could not be reached."""

    def __init__(self, code: str, message: str = "") -> None:
        """Initialize with a protocol error code (or cannot_connect)."""
        super().__init__(f"{code}: {message}" if message else code)
        self.code = code


@dataclass(frozen=True, slots=True)
class BridgeInfo:
    """Facts about a bridge (welcome message or status page)."""

    id: str
    name: str
    version: str
    platform: str = ""


@dataclass(frozen=True, slots=True)
class TouchEvent:
    """A touch on a touch display (protocol section 9), pixels from the top left."""

    kind: str  # tap | long | swipe
    x: int
    y: int
    # End of a swipe
    x2: int | None = None
    y2: int | None = None


@dataclass(frozen=True, slots=True)
class BridgeDevice:
    """A device attached to a bridge, reduced to what the integration uses."""

    id: str
    vendor: str
    model: str
    name: str
    serial: str | None
    firmware: str | None
    virtual: bool
    cols: int
    rows: int
    # Edge length of key images; 0 for colour-only keys
    key_size: int
    formats: tuple[str, ...]
    brightness: bool
    # Colour-only keys (LED pads); keys without image and colours have no display (pedals)
    colors: bool = False
    dials: int = 0
    dial_press: bool = False
    touch_width: int = 0
    touch_height: int = 0

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> BridgeDevice:
        """Parse a device object (protocol section 4.2)."""
        caps = data.get("capabilities") or {}
        keys = caps.get("keys") or {}
        image = keys.get("image") or {}
        dials = caps.get("dials") or {}
        touch = caps.get("touch") or {}
        return cls(
            id=str(data["id"]),
            vendor=str(data.get("vendor") or ""),
            model=str(data.get("model") or ""),
            name=str(data.get("name") or data["id"]),
            serial=data.get("serial"),
            firmware=data.get("firmware"),
            virtual=bool(data.get("virtual")),
            cols=int(keys.get("cols") or 0),
            rows=int(keys.get("rows") or 0),
            key_size=int(min(image.get("width") or 0, image.get("height") or 0)),
            formats=tuple(image.get("formats") or ()),
            brightness=bool(caps.get("brightness")),
            colors=bool(keys.get("colors")),
            dials=int(dials.get("count") or 0),
            dial_press=bool(dials.get("press")),
            touch_width=int(touch.get("width") or 0),
            touch_height=int(touch.get("height") or 0),
        )

    def to_json(self) -> dict[str, Any]:
        """Serializable form, to remember devices across restarts."""
        data: dict[str, Any] = {
            "id": self.id,
            "vendor": self.vendor,
            "model": self.model,
            "name": self.name,
            "serial": self.serial,
            "firmware": self.firmware,
            "virtual": self.virtual,
            "capabilities": {
                "keys": {
                    "cols": self.cols,
                    "rows": self.rows,
                    "image": {"width": self.key_size, "height": self.key_size, "formats": list(self.formats)},
                },
                "brightness": self.brightness,
            },
        }
        keys = data["capabilities"]["keys"]
        if not self.key_size:
            del keys["image"]
        if self.colors:
            keys["colors"] = True
        if self.dials:
            data["capabilities"]["dials"] = {"count": self.dials, "press": self.dial_press}
        if self.touch_width and self.touch_height:
            data["capabilities"]["touch"] = {"width": self.touch_width, "height": self.touch_height}
        return data


def _url(host: str, port: int, path: str, scheme: str = "http") -> str:
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"  # IPv6
    return f"{scheme}://{host}:{port}{path}"


def envelope(header: dict[str, Any], payload: bytes) -> bytes:
    """Binary envelope (protocol section 6)."""
    encoded = json.dumps(header, separators=(",", ":")).encode()
    return struct.pack(">H", len(encoded)) + encoded + payload


async def fetch_info(session: aiohttp.ClientSession, host: str, port: int = DEFAULT_PORT) -> BridgeInfo:
    """Read id and name from the bridge's status page (no pairing needed)."""
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT):
            async with session.get(_url(host, port, "/api/status")) as response:
                response.raise_for_status()
                data = await response.json(content_type=None)
        bridge = data["bridge"]
        return BridgeInfo(
            str(bridge["id"]), str(bridge["name"]), str(bridge.get("version", "")), str(bridge.get("platform", ""))
        )
    except (aiohttp.ClientError, TimeoutError, KeyError, TypeError, ValueError) as err:
        raise BridgeError("cannot_connect", str(err)) from err


async def _handshake(
    session: aiohttp.ClientSession, host: str, port: int, first: dict[str, Any], *, heartbeat: float | None = None
) -> tuple[aiohttp.ClientWebSocketResponse, dict[str, Any], str | None]:
    """Open a connection and send hello or pair; returns welcome (and a new token).

    Only the lasting session needs a heartbeat; the pairing connection is closed right away.
    """
    try:
        async with asyncio.timeout(CONNECT_TIMEOUT):
            ws = await session.ws_connect(
                _url(host, port, "/ws", "ws"), heartbeat=heartbeat, max_msg_size=4 * 1024 * 1024
            )
    except (aiohttp.ClientError, TimeoutError) as err:
        raise BridgeError("cannot_connect", str(err)) from err
    token = None
    try:
        await ws.send_json(first)
        async with asyncio.timeout(CONNECT_TIMEOUT):
            message = await _receive_json(ws)
            if message.get("type") == "paired":
                token = str(message["token"])
                message = await _receive_json(ws)
        if message.get("type") == "error":
            raise BridgeError(str(message.get("code")), str(message.get("message", "")))
        if message.get("type") != "welcome":
            raise BridgeError("invalid_message", f"Expected welcome, got {message.get('type')}")
    except BaseException:
        await ws.close()
        raise
    return ws, message, token


async def _receive_json(ws: aiohttp.ClientWebSocketResponse) -> dict[str, Any]:
    message = await ws.receive()
    if message.type != aiohttp.WSMsgType.TEXT:
        raise BridgeError("cannot_connect", f"Connection closed ({message.type.name})")
    data = json.loads(message.data)
    if not isinstance(data, dict):
        raise BridgeError("invalid_message", "Expected a JSON object")
    return data


def _info(welcome: dict[str, Any]) -> BridgeInfo:
    bridge = welcome.get("bridge") or {}
    return BridgeInfo(
        str(bridge.get("id", "")),
        str(bridge.get("name", "")),
        str(bridge.get("version", "")),
        str(bridge.get("platform", "")),
    )


async def pair(
    session: aiohttp.ClientSession, host: str, port: int, code: str, client_version: str
) -> tuple[BridgeInfo, str]:
    """Pair with a bridge using the code it shows; returns its info and the token."""
    ws, welcome, token = await _handshake(
        session,
        host,
        port,
        {
            "type": "pair",
            "protocol": PROTOCOL_VERSION,
            "client": "Home Assistant",
            "client_version": client_version,
            "code": code,
        },
    )
    await ws.close()
    assert token
    return _info(welcome), token


class BridgeClient:
    """Keeps a connection to one bridge and reports its devices and their input.

    Callbacks run in the event loop. After every (re)connect the device list
    arrives through on_devices; the owner then sends brightness and all images.
    """

    def __init__(self, session: aiohttp.ClientSession, host: str, port: int, token: str, client_version: str) -> None:
        """Initialize."""
        self.host = host
        self.port = port
        self._session = session
        self._token = token
        self._client_version = client_version
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._task: asyncio.Task[None] | None = None
        self._outgoing: asyncio.Queue[str | bytes] = asyncio.Queue()
        self.info: BridgeInfo | None = None
        self.on_state: Callable[[bool], None] | None = None
        self.on_devices: Callable[[list[BridgeDevice]], None] | None = None
        self.on_device_added: Callable[[BridgeDevice], None] | None = None
        self.on_device_removed: Callable[[str], None] | None = None
        self.on_key: Callable[[str, int, bool], None] | None = None
        self.on_dial: Callable[[str, int, int], None] | None = None
        self.on_dial_press: Callable[[str, int, bool], None] | None = None
        self.on_touch: Callable[[str, TouchEvent], None] | None = None
        # The token was refused: the user has to pair again
        self.on_unauthorized: Callable[[], None] | None = None

    @property
    def connected(self) -> bool:
        """A session with the bridge is established."""
        return self._ws is not None and not self._ws.closed

    def start(self) -> None:
        """Connect and keep reconnecting until stopped."""
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(
                self._run(), name=f"stream_assistant bridge {self.host}"
            )

    async def stop(self) -> None:
        """Disconnect for good."""
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._ws:
            await self._ws.close()
            self._ws = None

    # Commands (fire and forget; dropped while disconnected, the resync covers them)

    def send(self, message: dict[str, Any]) -> None:
        """Queue a JSON command."""
        if self.connected:
            self._outgoing.put_nowait(json.dumps(message, separators=(",", ":")))

    def send_image(self, device: str, key: int, image: bytes, image_format: str = "jpeg") -> None:
        """Queue a key image."""
        if self.connected:
            self._outgoing.put_nowait(
                envelope({"type": "set_key_image", "device": device, "key": key, "format": image_format}, image)
            )

    def send_touch_image(
        self, device: str, x: int, y: int, width: int, height: int, image: bytes, image_format: str = "jpeg"
    ) -> None:
        """Queue an image for an area of a touch display."""
        if self.connected:
            header = {
                "type": "set_touch_image",
                "device": device,
                "x": x,
                "y": y,
                "width": width,
                "height": height,
                "format": image_format,
            }
            self._outgoing.put_nowait(envelope(header, image))

    # Connection loop

    async def _run(self) -> None:
        backoff = BACKOFF_MIN
        while True:
            try:
                self._ws, welcome, _ = await _handshake(
                    self._session,
                    self.host,
                    self.port,
                    {
                        "type": "hello",
                        "protocol": PROTOCOL_VERSION,
                        "client": "Home Assistant",
                        "client_version": self._client_version,
                        "token": self._token,
                    },
                    heartbeat=HEARTBEAT,
                )
                self.info = _info(welcome)
                backoff = BACKOFF_MIN
                _LOGGER.debug("Connected to bridge %s at %s", self.info.name, self.host)
                await self._session_loop()
                _LOGGER.info("Connection to bridge %s lost", self.host)
            except BridgeError as err:
                if err.code == "unauthorized":
                    _LOGGER.warning("Bridge %s refused the token, pair again", self.host)
                    if self.on_unauthorized:
                        self.on_unauthorized()
                    return
                if err.code == "replaced":
                    _LOGGER.warning("Another client took over bridge %s", self.host)
                    backoff = REPLACED_BACKOFF
                else:
                    _LOGGER.debug("Bridge %s: %s", self.host, err)
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                _LOGGER.debug("Bridge %s: %s", self.host, err)
            finally:
                await self._close()
            await asyncio.sleep(backoff)
            backoff = min(BACKOFF_MAX, backoff * 2) if backoff < REPLACED_BACKOFF else BACKOFF_MIN

    async def _close(self) -> None:
        was_connected = self._ws is not None
        if self._ws:
            await self._ws.close()
            self._ws = None
        # Commands for the old session are useless after a reconnect
        self._outgoing = asyncio.Queue()
        if was_connected and self.on_state:
            self.on_state(False)

    async def _session_loop(self) -> None:
        assert self._ws
        ws = self._ws
        writer = asyncio.get_running_loop().create_task(self._write_loop(ws, self._outgoing))
        if self.on_state:
            self.on_state(True)
        try:
            async for message in ws:
                if message.type == aiohttp.WSMsgType.TEXT:
                    self._handle(json.loads(message.data))
                elif message.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSE):
                    break
        finally:
            writer.cancel()

    @staticmethod
    async def _write_loop(ws: aiohttp.ClientWebSocketResponse, queue: asyncio.Queue[str | bytes]) -> None:
        while True:
            item = await queue.get()
            if isinstance(item, bytes):
                await ws.send_bytes(item)
            else:
                await ws.send_str(item)

    def _handle(self, message: dict[str, Any]) -> None:
        kind = message.get("type")
        try:
            if kind == "devices" and self.on_devices:
                self.on_devices([BridgeDevice.from_json(d) for d in message.get("devices", [])])
            elif kind == "device_added" and self.on_device_added:
                self.on_device_added(BridgeDevice.from_json(message["device"]))
            elif kind == "device_removed" and self.on_device_removed:
                self.on_device_removed(str(message["device"]))
            elif kind == "key" and self.on_key:
                self.on_key(str(message["device"]), int(message["key"]), bool(message["pressed"]))
            elif kind == "dial" and self.on_dial:
                self.on_dial(str(message["device"]), int(message["dial"]), int(message["delta"]))
            elif kind == "dial_press" and self.on_dial_press:
                self.on_dial_press(str(message["device"]), int(message["dial"]), bool(message["pressed"]))
            elif kind == "touch" and self.on_touch:
                swipe = message["kind"] == "swipe"
                self.on_touch(
                    str(message["device"]),
                    TouchEvent(
                        str(message["kind"]),
                        int(message["x"]),
                        int(message["y"]),
                        int(message["x2"]) if swipe else None,
                        int(message["y2"]) if swipe else None,
                    ),
                )
            elif kind == "error":
                if message.get("code") == "replaced":
                    raise BridgeError("replaced")
                _LOGGER.debug("Bridge %s reported %s: %s", self.host, message.get("code"), message.get("message"))
        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.debug("Bridge %s sent an unexpected %s message: %s", self.host, kind, err)
