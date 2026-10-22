"""Runtime object for one dock: connection, key state, key appearance."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store

from .const import (
    CONF_DECK_PRODUCT_ID,
    CONF_DECK_SERIAL,
    CONF_DOCK_SERIAL,
    DOMAIN,
    EVENT_LONG_PRESS,
    EVENT_PRESSED,
    EVENT_RELEASED,
    EVENT_SHORT_PRESS,
    LONG_PRESS_SECONDS,
    signal_key,
    signal_state,
)
from .protocol import CoraError, DeckInfo, DeckModel, DockClient, find_model
from .render import KeyAppearance, render_key

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
SAVE_DELAY = 2
DEFAULT_BRIGHTNESS = 70

type StreamAssistantConfigEntry = ConfigEntry[StreamAssistantDevice]


class StreamAssistantDevice:
    """One Network Dock with (optionally) one Stream Deck attached."""

    def __init__(self, hass: HomeAssistant, entry: StreamAssistantConfigEntry) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self.client = DockClient(entry.data[CONF_HOST])
        self.dock_serial: str = entry.data[CONF_DOCK_SERIAL]
        self.deck_serial: str | None = entry.data.get(CONF_DECK_SERIAL)
        product_id = entry.data.get(CONF_DECK_PRODUCT_ID)
        # The model is fixed per config entry so the key entities exist even while offline
        self.model: DeckModel | None = find_model(product_id) if product_id else None
        self.brightness = DEFAULT_BRIGHTNESS
        self.keys: dict[int, KeyAppearance] = {}

        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._long_press_timers: dict[int, CALLBACK_TYPE] = {}
        self._repaint_task: asyncio.Task[None] | None = None

    @property
    def deck_connected(self) -> bool:
        """Return True when the deck accepts commands."""
        return self.client.deck_connected

    @property
    def dock_device_info(self) -> DeviceInfo:
        """Device info of the dock."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.dock_serial)},
            manufacturer="Elgato",
            model="Stream Deck Network Dock",
            name="Stream Deck Network Dock",
            serial_number=self.dock_serial,
        )

    @property
    def deck_device_info(self) -> DeviceInfo:
        """Device info of the attached deck."""
        assert self.model and self.deck_serial
        return DeviceInfo(
            identifiers={(DOMAIN, self.deck_serial)},
            manufacturer="Elgato",
            model=self.model.name,
            name=self.model.name,
            serial_number=self.deck_serial,
            via_device=(DOMAIN, self.dock_serial),
        )

    async def async_start(self) -> None:
        """Load stored layout and start connecting."""
        if stored := await self._store.async_load():
            self.keys = {
                int(index): KeyAppearance.from_dict(data)
                for index, data in stored.get("keys", {}).items()
            }

        dev_reg = dr.async_get(self.hass)
        dev_reg.async_get_or_create(config_entry_id=self.entry.entry_id, **self.dock_device_info)

        self.client.on_dock_state = self._on_dock_state
        self.client.on_deck_connected = self._on_deck_connected
        self.client.on_deck_disconnected = self._on_deck_disconnected
        self.client.on_key = self._on_key
        self.client.start()

    async def async_stop(self) -> None:
        """Disconnect and flush storage."""
        for cancel in self._long_press_timers.values():
            cancel()
        self._long_press_timers.clear()
        if self._repaint_task:
            self._repaint_task.cancel()
        await self.client.stop()
        await self._store.async_save(self._data_to_store())

    def _data_to_store(self) -> dict[str, Any]:
        return {"keys": {str(i): a.as_dict() for i, a in self.keys.items()}}

    # Connection callbacks (event loop)

    @callback
    def _on_dock_state(self, connected: bool) -> None:
        dock = self.client.dock_info
        if connected and dock:
            dev_reg = dr.async_get(self.hass)
            if device := dev_reg.async_get_device(identifiers={(DOMAIN, self.dock_serial)}):
                dev_reg.async_update_device(device.id, sw_version=dock.firmware)
        async_dispatcher_send(self.hass, signal_state(self.entry.entry_id))

    @callback
    def _on_deck_connected(self, deck: DeckInfo) -> None:
        if deck.child.serial != self.deck_serial or deck.model is not self.model:
            # Another deck was plugged in: store it and rebuild the entities
            _LOGGER.info(
                "Dock %s: now has %s (%s) attached, reloading",
                self.dock_serial,
                deck.model.name,
                deck.child.serial,
            )
            self.hass.config_entries.async_update_entry(
                self.entry,
                title=f"{deck.model.name} ({self.dock_serial})",
                data={
                    **self.entry.data,
                    CONF_DECK_SERIAL: deck.child.serial,
                    CONF_DECK_PRODUCT_ID: deck.child.product_id,
                },
            )
            self.hass.config_entries.async_schedule_reload(self.entry.entry_id)
            return

        dev_reg = dr.async_get(self.hass)
        if device := dev_reg.async_get_device(identifiers={(DOMAIN, deck.child.serial)}):
            dev_reg.async_update_device(device.id, sw_version=deck.firmware or None)

        try:
            self.client.set_brightness(self.brightness)
        except CoraError as err:
            _LOGGER.debug("Setting brightness failed: %s", err)
        self._repaint_task = self.entry.async_create_background_task(
            self.hass, self._async_repaint_all(), "stream_assistant repaint"
        )
        async_dispatcher_send(self.hass, signal_state(self.entry.entry_id))

    @callback
    def _on_deck_disconnected(self) -> None:
        for cancel in self._long_press_timers.values():
            cancel()
        self._long_press_timers.clear()
        async_dispatcher_send(self.hass, signal_state(self.entry.entry_id))

    @callback
    def _on_key(self, key: int, pressed: bool) -> None:
        signal = signal_key(self.entry.entry_id, key)
        if pressed:
            async_dispatcher_send(self.hass, signal, EVENT_PRESSED)

            @callback
            def _long_press(_now: Any) -> None:
                self._long_press_timers.pop(key, None)
                async_dispatcher_send(self.hass, signal, EVENT_LONG_PRESS)

            if cancel := self._long_press_timers.pop(key, None):
                cancel()
            self._long_press_timers[key] = async_call_later(
                self.hass, LONG_PRESS_SECONDS, _long_press
            )
            return

        async_dispatcher_send(self.hass, signal, EVENT_RELEASED)
        if cancel := self._long_press_timers.pop(key, None):
            # Released before the long press fired
            cancel()
            async_dispatcher_send(self.hass, signal, EVENT_SHORT_PRESS)

    # Commands

    async def async_set_brightness(self, percent: int) -> None:
        """Set brightness, remembered across reconnects."""
        self.brightness = percent
        if self.deck_connected:
            self.client.set_brightness(percent)

    async def async_set_key(self, key: int, appearance: KeyAppearance) -> None:
        """Change what a key shows and persist it."""
        self.keys[key] = appearance
        self._store.async_delay_save(self._data_to_store, SAVE_DELAY)
        await self._async_paint(key)

    async def async_clear_key(self, key: int) -> None:
        """Blank a key and forget its appearance."""
        self.keys.pop(key, None)
        self._store.async_delay_save(self._data_to_store, SAVE_DELAY)
        await self._async_paint(key)

    async def _async_paint(self, key: int) -> None:
        if not self.deck_connected or not self.model:
            # Painted on the next connect
            return
        appearance = self.keys.get(key, KeyAppearance())
        jpeg = await self.hass.async_add_executor_job(render_key, self.model, appearance)
        try:
            self.client.set_key_image(key, jpeg)
        except CoraError as err:
            _LOGGER.debug("Painting key %s failed: %s", key, err)

    async def _async_repaint_all(self) -> None:
        if not self.model:
            return
        for key in range(self.model.key_count):
            await self._async_paint(key)
