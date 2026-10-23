"""How the integration talks to a deck, independent of the hardware path.

The device (layout, rendering, behaviour, entities) only uses DeckTransport.
Implementations:
- NetworkDockTransport: Elgato Stream Deck Network Dock (Cora over TCP)
- later: bridge (vendor-neutral protocol) and virtual decks
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .capabilities import DeckCapabilities, find_capabilities
from .protocol import CoraError, DeckInfo, DockClient


class TransportError(Exception):
    """A command could not be delivered to the deck."""


@dataclass(frozen=True, slots=True)
class AttachedDeck:
    """A deck that is connected and ready for commands."""

    serial: str
    capabilities: DeckCapabilities
    firmware: str
    # Transport specific id of the hardware model (USB product id for Elgato)
    hardware_id: int | None = None


class DeckTransport(ABC):
    """Connection to one deck (through a hub such as the Network Dock)."""

    def __init__(self) -> None:
        """Initialize callbacks; all are called from the event loop."""
        self.on_hub_state: Callable[[bool], None] | None = None
        self.on_deck_connected: Callable[[AttachedDeck], None] | None = None
        self.on_deck_disconnected: Callable[[], None] | None = None
        self.on_key: Callable[[int, bool], None] | None = None

    @property
    @abstractmethod
    def hub_connected(self) -> bool:
        """The hub (dock, bridge) is reachable."""

    @property
    @abstractmethod
    def deck(self) -> AttachedDeck | None:
        """The connected deck, if any."""

    @property
    def deck_connected(self) -> bool:
        """A deck is connected and accepts commands."""
        return self.deck is not None

    @abstractmethod
    def hub_info(self) -> dict[str, Any]:
        """Facts about the hub for the info page (serial, firmware, address, ...)."""

    @abstractmethod
    def start(self) -> None:
        """Start connecting (and keep reconnecting)."""

    @abstractmethod
    async def stop(self, *, reset: bool = True) -> None:
        """Disconnect; with reset, leave the deck showing its default screen."""

    @abstractmethod
    def set_brightness(self, percent: int) -> None:
        """Set the panel brightness (0-100)."""

    @abstractmethod
    def set_key_image(self, index: int, image: bytes) -> None:
        """Show an image (already encoded for the deck's capabilities) on a key."""


class NetworkDockTransport(DeckTransport):
    """Elgato Stream Deck Network Dock."""

    def __init__(self, host: str) -> None:
        """Initialize."""
        super().__init__()
        self.host = host
        self._client = DockClient(host)
        self._deck: AttachedDeck | None = None
        self._client.on_dock_state = self._on_dock_state
        self._client.on_deck_connected = self._on_deck_connected
        self._client.on_deck_disconnected = self._on_deck_disconnected
        self._client.on_key = self._on_key

    # Callbacks from the dock client

    def _on_dock_state(self, connected: bool) -> None:
        if self.on_hub_state:
            self.on_hub_state(connected)

    def _on_deck_connected(self, info: DeckInfo) -> None:
        caps = find_capabilities(info.model.model_id)
        if caps is None:
            # The dock client only connects models it knows; keep both lists in sync
            raise RuntimeError(f"No capability profile for {info.model.model_id}")
        self._deck = AttachedDeck(
            serial=info.child.serial,
            capabilities=caps,
            firmware=info.firmware,
            hardware_id=info.child.product_id,
        )
        if self.on_deck_connected:
            self.on_deck_connected(self._deck)

    def _on_deck_disconnected(self) -> None:
        self._deck = None
        if self.on_deck_disconnected:
            self.on_deck_disconnected()

    def _on_key(self, index: int, pressed: bool) -> None:
        if self.on_key:
            self.on_key(index, pressed)

    # DeckTransport

    @property
    def hub_connected(self) -> bool:
        """The dock is reachable."""
        return self._client.dock_connected

    @property
    def deck(self) -> AttachedDeck | None:
        """The attached deck while it is connected."""
        return self._deck if self._client.deck_connected else None

    def hub_info(self) -> dict[str, Any]:
        """Dock serial, firmware and address."""
        dock = self._client.dock_info
        return {
            "serial": dock.serial if dock else None,
            "firmware": dock.firmware if dock else None,
            "host": self.host,
        }

    def start(self) -> None:
        """Start the connect/reconnect loop."""
        self._client.start()

    async def stop(self, *, reset: bool = True) -> None:
        """Disconnect, optionally showing the Elgato logo first."""
        await self._client.stop(reset=reset)

    def set_brightness(self, percent: int) -> None:
        """Set the panel brightness."""
        try:
            self._client.set_brightness(percent)
        except CoraError as err:
            raise TransportError(str(err)) from err

    def set_key_image(self, index: int, image: bytes) -> None:
        """Show a JPEG on a key."""
        try:
            self._client.set_key_image(index, image)
        except CoraError as err:
            raise TransportError(str(err)) from err
