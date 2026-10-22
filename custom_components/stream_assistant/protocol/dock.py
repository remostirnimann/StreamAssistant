"""High level client for a Stream Deck Network Dock and the deck attached to it."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
import logging

from .cora import CoraConnection, CoraError
from .models import DeckModel, brightness_report, find_model, reset_report

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 5343
RECONNECT_INTERVAL = 5.0


@dataclass(frozen=True, slots=True)
class DockInfo:
    """Information about the dock itself."""

    serial: str
    firmware: str


@dataclass(frozen=True, slots=True)
class ChildInfo:
    """Information about the deck attached to the dock."""

    vendor_id: int
    product_id: int
    serial: str
    tcp_port: int


@dataclass(frozen=True, slots=True)
class DeckInfo:
    """A connected deck."""

    child: ChildInfo
    model: DeckModel
    firmware: str


def parse_child_info(payload: bytes) -> ChildInfo | None:
    """Parse the dock's 'device 2' report, None when nothing is attached."""
    if len(payload) < 128 or payload[4] != 0x02:
        return None
    serial = payload[94:125].split(b"\x00", 1)[0].decode("ascii", "replace")
    return ChildInfo(
        vendor_id=int.from_bytes(payload[26:28], "little"),
        product_id=int.from_bytes(payload[28:30], "little"),
        serial=serial,
        tcp_port=int.from_bytes(payload[126:128], "little"),
    )


async def _query_dock(dock: CoraConnection) -> tuple[DockInfo, ChildInfo | None]:
    fw = await dock.get_report(0x83, to_host=True)
    sn = await dock.get_report(0x84, to_host=True)
    info = DockInfo(
        serial=sn[4 : 4 + sn[3]].decode("ascii", "replace"),
        firmware=fw[8:16].decode("ascii", "replace").strip("\x00"),
    )
    child = parse_child_info(await dock.get_report(0x1C, to_host=True))
    return info, child


async def probe(host: str, port: int = DEFAULT_PORT) -> tuple[DockInfo, ChildInfo | None]:
    """Connect once, read dock and deck info, disconnect. Used by the config flow."""
    dock = CoraConnection("probe", host, port)
    await dock.connect()
    try:
        return await _query_dock(dock)
    finally:
        await dock.close()


class DockClient:
    """Keeps a connection to one dock (and its deck) alive and exposes simple commands.

    All callbacks are invoked from the event loop.
    """

    def __init__(self, host: str, port: int = DEFAULT_PORT) -> None:
        self.host = host
        self.port = port
        self.dock_info: DockInfo | None = None
        self.deck: DeckInfo | None = None

        self.on_dock_state: Callable[[bool], None] | None = None
        self.on_deck_connected: Callable[[DeckInfo], None] | None = None
        self.on_deck_disconnected: Callable[[], None] | None = None
        self.on_key: Callable[[int, bool], None] | None = None

        self._dock: CoraConnection | None = None
        self._deck: CoraConnection | None = None
        self._task: asyncio.Task[None] | None = None
        self._session_ended = asyncio.Event()
        self._key_state: list[bool] = []
        self._stopping = False

    @property
    def dock_connected(self) -> bool:
        """Return True while the dock itself is reachable."""
        return self._dock is not None and self._dock.connected

    @property
    def deck_connected(self) -> bool:
        """Return True when the deck can receive commands."""
        return self.deck is not None and self._deck is not None and self._deck.connected

    def start(self) -> None:
        """Start the background connect/reconnect loop."""
        if not self._task:
            self._task = asyncio.create_task(self._run(), name=f"dock-{self.host}")

    async def stop(self, *, reset: bool = True) -> None:
        """Stop the loop and disconnect. Optionally show the Elgato logo first."""
        self._stopping = True
        if reset and self.deck_connected:
            try:
                self.reset_to_logo()
                await self._deck.drain()  # type: ignore[union-attr]
            except CoraError:
                pass
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._close_session()

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await self._session()
            except CoraError as err:
                _LOGGER.debug("Dock %s: %s", self.host, err)
            except Exception:
                _LOGGER.exception("Dock %s: unexpected error", self.host)
            await self._close_session()
            if not self._stopping:
                await asyncio.sleep(RECONNECT_INTERVAL)

    async def _session(self) -> None:
        self._session_ended.clear()
        self._dock = CoraConnection("dock", self.host, self.port)
        self._dock.on_closed = self._session_ended.set
        self._dock.on_child_info = lambda _payload: self._session_ended.set()
        await self._dock.connect()

        self.dock_info, child = await _query_dock(self._dock)
        _LOGGER.debug("Dock %s: %s, child %s", self.host, self.dock_info, child)
        if self.on_dock_state:
            self.on_dock_state(True)

        if child is not None:
            model = find_model(child.product_id)
            if model is None:
                _LOGGER.warning(
                    "Dock %s: unsupported Stream Deck (product id %#06x)",
                    self.host,
                    child.product_id,
                )
            else:
                await self._connect_deck(child, model)

        # Runs until the dock or deck drops, or a deck is plugged/unplugged
        await self._session_ended.wait()

    async def _connect_deck(self, child: ChildInfo, model: DeckModel) -> None:
        self._deck = CoraConnection("deck", self.host, child.tcp_port)
        self._deck.on_closed = self._session_ended.set
        self._deck.on_input = self._handle_input
        await self._deck.connect()

        firmware = ""
        try:
            fw = await self._deck.get_report(0x05, to_host=False)
            firmware = fw[6 : fw[1] + 2].decode("ascii", "replace")
        except CoraError as err:
            _LOGGER.debug("Deck firmware query failed: %s", err)

        self._key_state = [False] * model.key_count
        self.deck = DeckInfo(child=child, model=model, firmware=firmware)
        if self.on_deck_connected:
            self.on_deck_connected(self.deck)

    async def _close_session(self) -> None:
        had_deck = self.deck is not None
        had_dock = self._dock is not None and self._dock.connected
        self.deck = None
        for conn in (self._deck, self._dock):
            if conn:
                conn.on_closed = None
                await conn.close()
        self._deck = None
        self._dock = None
        if had_deck and self.on_deck_disconnected:
            self.on_deck_disconnected()
        if had_dock and self.on_dock_state:
            self.on_dock_state(False)

    def _handle_input(self, data: bytes) -> None:
        if not self.deck or not data or data[0] != 0x00:
            # Only button reports exist on the button grid models supported so far
            return
        offset = self.deck.model.key_data_offset
        for index, previous in enumerate(self._key_state):
            pos = offset + index
            pressed = pos < len(data) and data[pos] != 0
            if pressed != previous:
                self._key_state[index] = pressed
                if self.on_key:
                    self.on_key(index, pressed)

    def _require_deck(self) -> tuple[CoraConnection, DeckInfo]:
        if not self.deck_connected:
            raise CoraError("Stream Deck not connected")
        return self._deck, self.deck  # type: ignore[return-value]

    def set_brightness(self, percent: int) -> None:
        """Set the panel brightness (0-100)."""
        conn, _ = self._require_deck()
        conn.send_feature_report(brightness_report(percent))

    def set_key_image(self, key: int, jpeg: bytes) -> None:
        """Show a JPEG (already sized and rotated for the model) on a key."""
        conn, deck = self._require_deck()
        if not 0 <= key < deck.model.key_count:
            raise ValueError(f"Key {key} out of range")
        conn.write_reports(deck.model.build_image_reports(key, jpeg))

    def reset_to_logo(self) -> None:
        """Show the Elgato logo."""
        conn, _ = self._require_deck()
        conn.send_feature_report(reset_report())
