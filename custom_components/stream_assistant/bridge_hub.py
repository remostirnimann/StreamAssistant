"""A Stream Assistant Bridge: one connection, any number of decks (docs/bridge-protocol.md).

Every deck becomes a StreamAssistantDevice with its own layout, entities and
behaviour, exactly like a deck behind a Network Dock. Decks seen once are
remembered in the config entry, so their entities exist while the bridge or
the deck is offline.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .capabilities import DeckCapabilities, grid_id
from .const import (
    CONF_BRIDGE_ID,
    CONF_DEVICES,
    CONF_PORT,
    CONF_TOKEN,
    DOMAIN,
    VERSION,
    signal_hub_state,
    signal_new_device,
)
from .device import BridgeDeckSpec, StreamAssistantConfigEntry, StreamAssistantDevice
from .protocol.bridge import BridgeClient, BridgeDevice, TouchEvent
from .transport import AttachedDeck, DeckTransport

_LOGGER = logging.getLogger(__name__)


class BridgeDeckTransport(DeckTransport):
    """One deck of a bridge; the hub feeds it connection state and key presses."""

    def __init__(self, client: BridgeClient, device: BridgeDevice, capabilities: DeckCapabilities) -> None:
        """Initialize."""
        super().__init__()
        self._client = client
        self.device_id = device.id
        self._deck = AttachedDeck(device.serial or device.id, capabilities, device.firmware or "")
        self._present = False

    @property
    def hub_connected(self) -> bool:
        """The bridge is connected."""
        return self._client.connected

    @property
    def deck(self) -> AttachedDeck | None:
        """The deck while the bridge reports it."""
        return self._deck if self._present and self._client.connected else None

    def hub_info(self) -> dict[str, Any]:
        """Bridge facts for the info page."""
        info = self._client.info
        return {
            "serial": info.id if info else None,
            "name": info.name if info else None,
            "firmware": info.version if info else None,
            "host": f"{self._client.host}:{self._client.port}",
        }

    def start(self) -> None:
        """The hub connects; nothing to do per deck."""

    async def stop(self, *, reset: bool = True) -> None:
        """Show the idle screen when Home Assistant lets go of the deck."""
        if reset and self.deck_connected:
            self._client.send({"type": "reset", "device": self.device_id})
        self._present = False

    def set_brightness(self, percent: int) -> None:
        """Set the brightness."""
        self._client.send({"type": "set_brightness", "device": self.device_id, "percent": percent})

    def set_key_image(self, index: int, image: bytes) -> None:
        """Send a key image (JPEG, upright: the bridge rotates if needed)."""
        self._client.send_image(self.device_id, index, image)

    def set_touch_image(self, x: int, y: int, width: int, height: int, image: bytes) -> None:
        """Send an image for an area of the touch strip (JPEG, upright)."""
        self._client.send_touch_image(self.device_id, x, y, width, height, image)

    # Fed by the hub

    @callback
    def attached(self, device: BridgeDevice) -> None:
        """The bridge reports the deck (after connect or plug-in)."""
        self._deck = AttachedDeck(self._deck.serial, self._deck.capabilities, device.firmware or "")
        self._present = True
        if self.on_deck_connected:
            self.on_deck_connected(self._deck)

    @callback
    def detached(self) -> None:
        """The deck was unplugged or the bridge went away."""
        if not self._present:
            return
        self._present = False
        if self.on_deck_disconnected:
            self.on_deck_disconnected()

    @callback
    def hub_state(self, connected: bool) -> None:
        """Bridge connection changed."""
        if self.on_hub_state:
            self.on_hub_state(connected)

    @callback
    def key(self, index: int, pressed: bool) -> None:
        """A key went down or up."""
        if self._present and self.on_key:
            self.on_key(index, pressed)

    @callback
    def dial(self, index: int, delta: int) -> None:
        """A dial was turned."""
        if self._present and self.on_dial:
            self.on_dial(index, delta)

    @callback
    def dial_press(self, index: int, pressed: bool) -> None:
        """A dial was pushed or released."""
        if self._present and self.on_dial_press:
            self.on_dial_press(index, pressed)

    @callback
    def touch(self, event: TouchEvent) -> None:
        """The touch strip was tapped, held or swiped."""
        if self._present and self.on_touch:
            self.on_touch(event)


class BridgeHub:
    """Runtime data of a bridge config entry."""

    def __init__(self, hass: HomeAssistant, entry: StreamAssistantConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self.bridge_id: str = entry.data[CONF_BRIDGE_ID]
        self.client = BridgeClient(
            async_get_clientsession(hass),
            entry.data["host"],
            entry.data[CONF_PORT],
            entry.data[CONF_TOKEN],
            VERSION,
        )
        self.devices: dict[str, StreamAssistantDevice] = {}
        self._transports: dict[str, BridgeDeckTransport] = {}
        # Decks reported while their device object is still starting
        self._pending: dict[str, BridgeDevice] = {}
        self._present: set[str] = set()
        self.hub_device_id: str | None = None

    @property
    def connected(self) -> bool:
        """The bridge is connected."""
        return self.client.connected

    @property
    def device_info(self) -> DeviceInfo:
        """The bridge as a device (the decks hang below it)."""
        info = self.client.info
        return DeviceInfo(
            identifiers={(DOMAIN, f"bridge-{self.bridge_id}")},
            manufacturer="Stream Assistant",
            model="Stream Assistant Bridge",
            name=self.entry.title,
            sw_version=info.version if info else None,
        )

    async def async_start(self) -> None:
        """Create the known decks and connect."""
        device = dr.async_get(self.hass).async_get_or_create(config_entry_id=self.entry.entry_id, **self.device_info)
        self.hub_device_id = device.id
        for data in self.entry.data.get(CONF_DEVICES, {}).values():
            await self._async_add_device(BridgeDevice.from_json(data), announce=False)

        self.client.on_state = self._on_state
        self.client.on_devices = self._on_devices
        self.client.on_device_added = self._on_device_added
        self.client.on_device_removed = self._on_device_removed
        self.client.on_key = self._on_key
        self.client.on_dial = self._on_dial
        self.client.on_dial_press = self._on_dial_press
        self.client.on_touch = self._on_touch
        self.client.on_unauthorized = self._on_unauthorized
        self.client.start()

    async def async_stop(self) -> None:
        """Release all decks and disconnect."""
        for device in self.devices.values():
            await device.async_stop()
        await self.client.stop()

    # Devices

    async def _async_add_device(self, found: BridgeDevice, *, announce: bool) -> StreamAssistantDevice | None:
        image_keys = found.key_size > 0 and "jpeg" in found.formats
        # Keys without any display (pedals) only press
        input_only = found.key_size == 0 and not found.colors
        if found.cols < 1 or found.rows < 1 or not (image_keys or input_only):
            _LOGGER.warning(
                "%s: %s (%s) has keys this version cannot drive (colour-only keys), not supported yet",
                self.entry.title,
                found.name,
                found.id,
            )
            return None
        assert self.hub_device_id
        # Free grid as far as layouts and templates are concerned, at the deck's image and strip size
        caps = DeckCapabilities(
            grid_id(found.cols, found.rows, found.dials),
            found.model,
            found.cols,
            found.rows,
            found.key_size,
            dials=found.dials,
            touch_width=found.touch_width,
            touch_height=found.touch_height,
        )
        transport = BridgeDeckTransport(self.client, found, caps)
        device = StreamAssistantDevice(
            self.hass,
            self.entry,
            BridgeDeckSpec(found, caps, transport, self.hub_device_id, f"{self.bridge_id}-{found.id}"),
        )
        self.devices[found.id] = device
        self._transports[found.id] = transport
        await device.async_start()
        if announce:
            async_dispatcher_send(self.hass, signal_new_device(self.entry.entry_id), device)
        return device

    def _remember(self, found: BridgeDevice) -> None:
        """Store the deck in the entry; reload when its grid changed."""
        known: dict[str, Any] = dict(self.entry.data.get(CONF_DEVICES, {}))
        data = found.to_json()
        if known.get(found.id) == data:
            return
        old = known.get(found.id)
        known[found.id] = data
        self.hass.config_entries.async_update_entry(self.entry, data={**self.entry.data, CONF_DEVICES: known})
        current = self.devices.get(found.id)
        if (
            old
            and current
            and current.model
            and (
                current.model.cols,
                current.model.rows,
                current.model.key_size,
                current.model.dials,
                current.model.touch_width,
                current.model.touch_height,
            )
            != (found.cols, found.rows, found.key_size, found.dials, found.touch_width, found.touch_height)
        ):
            _LOGGER.info("%s: %s changed its controls, reloading", self.entry.title, found.name)
            self.hass.config_entries.async_schedule_reload(self.entry.entry_id)

    @callback
    def _attach(self, found: BridgeDevice) -> None:
        self._present.add(found.id)
        self._remember(found)
        if transport := self._transports.get(found.id):
            transport.attached(found)
            return
        if found.id in self._pending:
            self._pending[found.id] = found
            return
        self._pending[found.id] = found
        self.entry.async_create_background_task(
            self.hass, self._async_new_device(found.id), "stream_assistant bridge deck"
        )

    async def _async_new_device(self, device_id: str) -> None:
        found = self._pending[device_id]
        device = await self._async_add_device(found, announce=True)
        found = self._pending.pop(device_id)
        if device and device_id in self._present and self.client.connected:
            self._transports[device_id].attached(found)

    # Bridge callbacks

    @callback
    def _on_state(self, connected: bool) -> None:
        if not connected:
            self._present.clear()
            for transport in self._transports.values():
                transport.detached()
        for transport in self._transports.values():
            transport.hub_state(connected)
        if connected and self.client.info and self.hub_device_id:
            dr.async_get(self.hass).async_update_device(self.hub_device_id, sw_version=self.client.info.version)
        async_dispatcher_send(self.hass, signal_hub_state(self.entry.entry_id))

    @callback
    def _on_devices(self, devices: list[BridgeDevice]) -> None:
        reported = {d.id for d in devices}
        for device_id in list(self._present - reported):
            self._on_device_removed(device_id)
        for found in devices:
            self._attach(found)

    @callback
    def _on_device_added(self, found: BridgeDevice) -> None:
        self._attach(found)

    @callback
    def _on_device_removed(self, device_id: str) -> None:
        self._present.discard(device_id)
        if transport := self._transports.get(device_id):
            transport.detached()

    @callback
    def _on_key(self, device_id: str, index: int, pressed: bool) -> None:
        if transport := self._transports.get(device_id):
            transport.key(index, pressed)

    @callback
    def _on_dial(self, device_id: str, index: int, delta: int) -> None:
        if transport := self._transports.get(device_id):
            transport.dial(index, delta)

    @callback
    def _on_dial_press(self, device_id: str, index: int, pressed: bool) -> None:
        if transport := self._transports.get(device_id):
            transport.dial_press(index, pressed)

    @callback
    def _on_touch(self, device_id: str, event: TouchEvent) -> None:
        if transport := self._transports.get(device_id):
            transport.touch(event)

    @callback
    def _on_unauthorized(self) -> None:
        self.entry.async_start_reauth(self.hass)
        async_dispatcher_send(self.hass, signal_hub_state(self.entry.entry_id))
