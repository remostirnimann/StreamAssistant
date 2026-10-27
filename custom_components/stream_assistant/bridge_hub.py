"""A Stream Assistant Bridge: one connection, any number of decks (docs/bridge-protocol.md).

Every deck becomes a StreamAssistantDevice with its own layout, entities and
behaviour, exactly like a deck behind a Network Dock. Decks seen once are
remembered in the config entry, so their entities exist while the bridge or
the deck is offline.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .capabilities import DeckCapabilities, grid_id
from .const import (
    BRIDGE_UPDATE_TIMEOUT,
    CONF_AUTO_UPDATE,
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
from .protocol.bridge import BridgeClient, BridgeDevice, BridgeError, TouchEvent
from .transport import AttachedDeck, DeckTransport

_LOGGER = logging.getLogger(__name__)

# Only releases are offered to bridges, not development versions of the integration
_RELEASE = re.compile(r"\d+\.\d+\.\d+((a|b|rc)\d+)?")


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

    def set_screen_image(self, image: bytes) -> None:
        """Send an image for the screen (JPEG, upright)."""
        self._client.send_screen_image(self.device_id, image)

    def set_button_color(self, index: int, color: str) -> None:
        """Light a button outside the grid."""
        self._client.send({"type": "set_button_color", "device": self.device_id, "button": index, "color": color})

    def set_dial_leds(self, index: int, color: str, level: float) -> None:
        """Light a dial's LED ring."""
        self._client.send(
            {"type": "set_dial_leds", "device": self.device_id, "dial": index, "color": color, "level": round(level, 3)}
        )

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

    @callback
    def button(self, index: int, pressed: bool) -> None:
        """A button outside the grid went down or up."""
        if self._present and self.on_button:
            self.on_button(index, pressed)

    @callback
    def nfc(self, tag_id: str) -> None:
        """An NFC tag was read."""
        if self._present and self.on_nfc:
            self.on_nfc(tag_id)


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
        # The bridge update in progress: resolved when the bridge is back with the version
        self._update: asyncio.Future[None] | None = None
        self._update_target: str | None = None
        # Versions an automatic update was tried for (once per start of Home Assistant)
        self._auto_tried: set[str] = set()

    @property
    def connected(self) -> bool:
        """The bridge is connected."""
        return self.client.connected

    # Updates of the bridge

    @property
    def bridge_version(self) -> str | None:
        """The version the bridge runs (last seen)."""
        return self.client.info.version if self.client.info else None

    @property
    def latest_version(self) -> str | None:
        """The bridge release that fits this integration; None for development versions."""
        return VERSION if _RELEASE.fullmatch(VERSION) else None

    @property
    def can_update(self) -> bool:
        """The bridge can install a release itself."""
        return bool(self.client.info and "update" in self.client.info.features)

    @property
    def needs_update(self) -> bool:
        """The bridge runs another version than the one that fits."""
        return bool(self.latest_version and self.bridge_version and self.bridge_version != self.latest_version)

    @property
    def auto_update(self) -> bool:
        """The entry option to update the bridge on its own."""
        return bool(self.entry.options.get(CONF_AUTO_UPDATE))

    @property
    def update_in_progress(self) -> bool:
        """An update was started and the bridge is not back with the new version yet."""
        return self._update is not None and not self._update.done()

    async def async_update_bridge(self, version: str) -> None:
        """Have the bridge install a release; returns when it is back with that version.

        Raises BridgeError when the bridge cannot update, reports a failure, or does not
        come back in time.
        """
        if not self.can_update:
            raise BridgeError("unsupported", "This bridge cannot update itself; install the new version by hand")
        if self.update_in_progress:
            raise BridgeError("busy", "An update is already running")
        self._update = self.hass.loop.create_future()
        self._update_target = version
        self.client.send({"type": "update", "version": version})
        _LOGGER.info("%s: updating the bridge to %s", self.entry.title, version)
        async_dispatcher_send(self.hass, signal_hub_state(self.entry.entry_id))
        try:
            async with asyncio.timeout(BRIDGE_UPDATE_TIMEOUT):
                await self._update
        except TimeoutError as err:
            raise BridgeError("timeout", f"The bridge did not come back with version {version}") from err
        finally:
            self._update = None
            self._update_target = None
            async_dispatcher_send(self.hass, signal_hub_state(self.entry.entry_id))

    @callback
    def async_check_auto_update(self) -> None:
        """Start an automatic update when wanted and possible (once per version)."""
        target = self.latest_version
        if (
            not self.auto_update
            or not target
            or not self.connected
            or not self.can_update
            or not self.needs_update
            or self.update_in_progress
            or target in self._auto_tried
        ):
            return
        self._auto_tried.add(target)
        _LOGGER.info(
            "%s: the bridge runs %s, updating it to %s on its own", self.entry.title, self.bridge_version, target
        )
        self.entry.async_create_background_task(
            self.hass, self._async_auto_update(target), "stream_assistant bridge update"
        )

    async def _async_auto_update(self, version: str) -> None:
        try:
            await self.async_update_bridge(version)
        except BridgeError as err:
            _LOGGER.warning("%s: automatic bridge update to %s failed: %s", self.entry.title, version, err)

    @callback
    def _on_update_status(self, status: dict[str, Any]) -> None:
        state = status.get("state")
        _LOGGER.debug("%s: bridge update %s %s", self.entry.title, state, status.get("message") or "")
        if state == "failed" and self._update and not self._update.done():
            self._update.set_exception(BridgeError("update_failed", str(status.get("message") or "Update failed")))

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
        self.client.on_update_status = self._on_update_status
        self.client.on_button = self._on_button
        self.client.on_nfc = self._on_nfc
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
            dial_ring=found.dial_ring,
            buttons=found.buttons if found.button_colors else 0,
            screen_width=found.screen_width,
            screen_height=found.screen_height,
            nfc=found.nfc,
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
                current.model.buttons,
                current.model.screen_width,
            )
            != (
                found.cols,
                found.rows,
                found.key_size,
                found.dials,
                found.touch_width,
                found.touch_height,
                found.buttons if found.button_colors else 0,
                found.screen_width,
            )
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
        if connected and self._update and not self._update.done() and self.bridge_version == self._update_target:
            _LOGGER.info("%s: the bridge is back with version %s", self.entry.title, self.bridge_version)
            self._update.set_result(None)
        async_dispatcher_send(self.hass, signal_hub_state(self.entry.entry_id))
        if connected:
            self.async_check_auto_update()

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
    def _on_button(self, device_id: str, index: int, pressed: bool) -> None:
        if transport := self._transports.get(device_id):
            transport.button(index, pressed)

    @callback
    def _on_nfc(self, device_id: str, tag_id: str) -> None:
        if transport := self._transports.get(device_id):
            transport.nfc(tag_id)

    @callback
    def _on_unauthorized(self) -> None:
        self.entry.async_start_reauth(self.hass)
        async_dispatcher_send(self.hass, signal_hub_state(self.entry.entry_id))
