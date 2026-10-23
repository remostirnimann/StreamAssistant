"""Runtime object for one dock: connection, layout, live key images, key actions."""

from __future__ import annotations

from collections import OrderedDict
import copy
import logging
import secrets
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MAC
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store

from .actions import async_run_action
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
from .display import back_visual, key_visual
from .layout import (
    ACTION_BACK,
    ACTION_NONE,
    ACTION_PAGE,
    BACK_KEY,
    KEY_SCHEMA,
    ROOT_PAGE_ID,
    SECOND_LINE_NONE,
    empty_layout,
    migrate_v1,
)
from .protocol import CoraError, DeckInfo, DeckModel, DockClient, find_model
from .render import KeyVisual, render_key, render_preview

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 2
SAVE_DELAY = 2
DEFAULT_BRIGHTNESS = 70
RENDER_CACHE_SIZE = 256
BACK_ACTION = {"type": ACTION_BACK}
NO_ACTION = {"type": ACTION_NONE}

type StreamAssistantConfigEntry = ConfigEntry[StreamAssistantDevice]


class LayoutStore(Store[dict[str, Any]]):
    """Layout storage with migration from the set_key-only version 1."""

    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: dict[str, Any]
    ) -> dict[str, Any]:
        if old_major_version == 1:
            return migrate_v1(old_data)
        return old_data


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
        self.layout: dict[str, Any] = empty_layout()
        # Bumped on every change; the editor sends it back to detect stale saves.
        # The random prefix keeps revisions from before a restart from matching.
        self._revision_prefix = secrets.token_hex(4)
        self._revision_counter = 0
        self.current_page = ROOT_PAGE_ID

        self._store = LayoutStore(hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self._long_press_timers: dict[int, CALLBACK_TYPE] = {}
        self._short_done: set[int] = set()
        self._unsub_states: CALLBACK_TYPE | None = None
        # What each key should show; a finished render is only sent if it still matches
        self._wanted: dict[int, KeyVisual] = {}
        self._render_cache: OrderedDict[tuple[int, KeyVisual], bytes] = OrderedDict()
        self._dock_device_id: str | None = None

    @property
    def layout_revision(self) -> str:
        """Identifies the current layout version."""
        return f"{self._revision_prefix}-{self._revision_counter}"

    # Device info

    @property
    def dock_connected(self) -> bool:
        """Return True while the dock is reachable."""
        return self.client.dock_connected

    @property
    def deck_connected(self) -> bool:
        """Return True when the deck accepts commands."""
        return self.client.deck_connected

    @property
    def dock_device_info(self) -> DeviceInfo:
        """Device info of the dock.

        The MAC connection lets Home Assistant's DHCP watcher report new
        leases of this dock (see async_step_dhcp).
        """
        info = DeviceInfo(
            identifiers={(DOMAIN, self.dock_serial)},
            manufacturer="Elgato",
            model="Stream Deck Network Dock",
            name="Stream Deck Network Dock",
            serial_number=self.dock_serial,
        )
        if mac := self.entry.data.get(CONF_MAC):
            info["connections"] = {(dr.CONNECTION_NETWORK_MAC, mac)}
        return info

    @property
    def deck_device_info(self) -> DeviceInfo:
        """Device info of the attached deck."""
        assert self.model and self.deck_serial
        info = DeviceInfo(
            identifiers={(DOMAIN, self.deck_serial)},
            manufacturer="Elgato",
            model=self.model.name,
            name=self.model.name,
            serial_number=self.deck_serial,
        )
        if self._dock_device_id:
            info["via_device_id"] = self._dock_device_id
        return info

    # Lifecycle

    async def async_start(self) -> None:
        """Load the layout and start connecting."""
        if stored := await self._store.async_load():
            self.layout = stored

        dev_reg = dr.async_get(self.hass)
        dock = dev_reg.async_get_or_create(config_entry_id=self.entry.entry_id, **self.dock_device_info)
        self._dock_device_id = dock.id

        self.client.on_dock_state = self._on_dock_state
        self.client.on_deck_connected = self._on_deck_connected
        self.client.on_deck_disconnected = self._on_deck_disconnected
        self.client.on_key = self._on_key
        self._track_page_entities()
        self.client.start()

    async def async_stop(self) -> None:
        """Disconnect and flush storage."""
        self._cancel_timers()
        if self._unsub_states:
            self._unsub_states()
            self._unsub_states = None
        await self.client.stop()
        await self._store.async_save(self.layout)

    # Layout

    def page(self, page_id: str) -> dict[str, Any] | None:
        """Return a page of the layout."""
        return next((p for p in self.layout["pages"] if p["id"] == page_id), None)

    async def async_set_layout(self, layout: dict[str, Any]) -> None:
        """Replace the whole layout (already validated) and show it."""
        self.layout = layout
        self._revision_counter += 1
        self._store.async_delay_save(lambda: self.layout, SAVE_DELAY)
        if self.page(self.current_page) is None:
            self.current_page = ROOT_PAGE_ID
        self._track_page_entities()
        self._schedule_repaint()

    async def async_show_page(self, page_id: str) -> None:
        """Switch the deck to another page."""
        if self.page(page_id) is None:
            return
        self.current_page = page_id
        self._cancel_timers()
        self._track_page_entities()
        self._schedule_repaint()
        async_dispatcher_send(self.hass, signal_state(self.entry.entry_id))

    def _key_slot(self, page: dict[str, Any], index: int) -> tuple[dict[str, Any] | None, bool]:
        """Return (key config, is_back_key) for a key of a page."""
        if page.get("parent") and index == BACK_KEY:
            return None, True
        return page["keys"].get(str(index)), False

    def _visual(self, page: dict[str, Any], index: int) -> KeyVisual:
        key, is_back = self._key_slot(page, index)
        return back_visual(self.hass) if is_back else key_visual(self.hass, key)

    def _actions(self, index: int) -> tuple[dict[str, Any], dict[str, Any]]:
        page = self.page(self.current_page)
        if page is None:
            return NO_ACTION, NO_ACTION
        key, is_back = self._key_slot(page, index)
        if is_back:
            return BACK_ACTION, NO_ACTION
        if not key:
            return NO_ACTION, NO_ACTION
        return key["short"], key["long"]

    @callback
    def _track_page_entities(self) -> None:
        if self._unsub_states:
            self._unsub_states()
            self._unsub_states = None
        page = self.page(self.current_page)
        if page is None:
            return
        entities = {k["entity_id"] for k in page["keys"].values() if k.get("entity_id")}
        if entities:
            self._unsub_states = async_track_state_change_event(
                self.hass, sorted(entities), self._on_state_change
            )

    @callback
    def _on_state_change(self, event: Event[EventStateChangedData]) -> None:
        page = self.page(self.current_page)
        if page is None:
            return
        entity_id = event.data["entity_id"]
        keys = [int(i) for i, k in page["keys"].items() if k.get("entity_id") == entity_id]
        self._schedule_repaint(keys)

    # Painting

    @callback
    def _schedule_repaint(self, keys: list[int] | None = None) -> None:
        if not self.model or not self.deck_connected:
            # Painted on the next connect
            return
        indices = range(self.model.key_count) if keys is None else keys
        self.entry.async_create_background_task(
            self.hass, self._async_paint(list(indices)), "stream_assistant paint"
        )

    async def _async_render(self, size: int, visual: KeyVisual, *, upright: bool) -> bytes:
        assert self.model
        cache_key = (size if upright else -size, visual)
        if (jpeg := self._render_cache.get(cache_key)) is not None:
            self._render_cache.move_to_end(cache_key)
            return jpeg
        if upright:
            jpeg = await self.hass.async_add_executor_job(render_preview, size, visual)
        else:
            jpeg = await self.hass.async_add_executor_job(render_key, self.model, visual)
        self._render_cache[cache_key] = jpeg
        if len(self._render_cache) > RENDER_CACHE_SIZE:
            self._render_cache.popitem(last=False)
        return jpeg

    async def _async_paint(self, keys: list[int]) -> None:
        if not self.model:
            return
        page = self.page(self.current_page)
        if page is None:
            return
        for index in keys:
            if index >= self.model.key_count:
                continue
            visual = self._visual(page, index)
            self._wanted[index] = visual
            jpeg = await self._async_render(self.model.key_size, visual, upright=False)
            if self._wanted.get(index) != visual or not self.deck_connected:
                continue
            try:
                self.client.set_key_image(index, jpeg)
            except CoraError as err:
                _LOGGER.debug("Painting key %s failed: %s", index, err)
                return

    async def async_render_page_preview(self, page: dict[str, Any]) -> list[bytes]:
        """Upright JPEGs of every key of a (possibly unsaved) page, for the editor."""
        assert self.model
        return [
            await self._async_render(self.model.key_size, self._visual(page, index), upright=True)
            for index in range(self.model.key_count)
        ]

    # Connection callbacks (event loop)

    @callback
    def _on_dock_state(self, connected: bool) -> None:
        dock = self.client.dock_info
        if connected and dock and self._dock_device_id:
            dr.async_get(self.hass).async_update_device(self._dock_device_id, sw_version=dock.firmware)
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

        if deck.firmware:
            dr.async_get(self.hass).async_get_or_create(
                config_entry_id=self.entry.entry_id,
                identifiers={(DOMAIN, deck.child.serial)},
                sw_version=deck.firmware,
            )

        try:
            self.client.set_brightness(self.brightness)
        except CoraError as err:
            _LOGGER.debug("Setting brightness failed: %s", err)
        self._wanted.clear()
        self._schedule_repaint()
        async_dispatcher_send(self.hass, signal_state(self.entry.entry_id))

    @callback
    def _on_deck_disconnected(self) -> None:
        self._cancel_timers()
        async_dispatcher_send(self.hass, signal_state(self.entry.entry_id))

    def _cancel_timers(self) -> None:
        for cancel in self._long_press_timers.values():
            cancel()
        self._long_press_timers.clear()
        self._short_done.clear()

    # Keys

    @callback
    def _on_key(self, key: int, pressed: bool) -> None:
        signal = signal_key(self.entry.entry_id, key)
        short, long = self._actions(key)

        if pressed:
            async_dispatcher_send(self.hass, signal, EVENT_PRESSED)
            self._short_done.discard(key)
            if long["type"] == ACTION_NONE:
                # Nothing to wait for: react on press, feels instant
                self._short_done.add(key)
                self._run(short)

            @callback
            def _long_press(_now: Any) -> None:
                self._long_press_timers.pop(key, None)
                async_dispatcher_send(self.hass, signal, EVENT_LONG_PRESS)
                if key not in self._short_done:
                    self._short_done.add(key)
                    self._run(long)

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
            if key not in self._short_done:
                self._run(short)
        self._short_done.discard(key)

    async def async_simulate_press(
        self, index: int, long_press: bool, page: dict[str, Any] | None = None
    ) -> None:
        """Behave as if a key was pressed: key events plus its action.

        `page` is the editor's (possibly unsaved) page; default is the page shown.
        """
        page = page or self.page(self.current_page)
        if page is None:
            return
        key, is_back = self._key_slot(page, index)
        if is_back:
            short, long = BACK_ACTION, NO_ACTION
        elif key:
            short, long = key["short"], key["long"]
        else:
            short, long = NO_ACTION, NO_ACTION

        signal = signal_key(self.entry.entry_id, index)
        async_dispatcher_send(self.hass, signal, EVENT_PRESSED)
        if long_press:
            async_dispatcher_send(self.hass, signal, EVENT_LONG_PRESS)
            async_dispatcher_send(self.hass, signal, EVENT_RELEASED)
        else:
            async_dispatcher_send(self.hass, signal, EVENT_RELEASED)
            async_dispatcher_send(self.hass, signal, EVENT_SHORT_PRESS)
        self._run(long if long_press else short, page)

    @callback
    def _run(self, action: dict[str, Any], page: dict[str, Any] | None = None) -> None:
        kind = action["type"]
        if kind == ACTION_NONE:
            return
        if kind == ACTION_PAGE:
            self.hass.async_create_task(self.async_show_page(action["page"]))
            return
        if kind == ACTION_BACK:
            page = page or self.page(self.current_page)
            self.hass.async_create_task(
                self.async_show_page(page["parent"] if page and page.get("parent") else ROOT_PAGE_ID)
            )
            return
        self.entry.async_create_background_task(
            self.hass, async_run_action(self.hass, action), "stream_assistant action"
        )

    # Commands

    async def async_set_brightness(self, percent: int) -> None:
        """Set brightness, remembered across reconnects."""
        self.brightness = percent
        if self.deck_connected:
            self.client.set_brightness(percent)

    async def async_set_key(self, key: int, values: dict[str, Any]) -> None:
        """set_key action: change the look of a key on the page currently shown."""
        page = self.page(self.current_page)
        if page is None:
            return
        current = page["keys"].get(str(key)) or KEY_SCHEMA({"second_line": SECOND_LINE_NONE})
        updated = copy.deepcopy(current)
        if "text" in values:
            updated["title"] = values["text"]
        if "background_color" in values:
            updated["on_color"] = updated["off_color"] = values["background_color"]
        for field in ("text_color", "font_size", "image"):
            if field in values:
                updated[field] = values[field]
        page["keys"][str(key)] = KEY_SCHEMA(updated)
        await self.async_set_layout(self.layout)

    async def async_clear_key(self, key: int) -> None:
        """Remove a key from the page currently shown."""
        page = self.page(self.current_page)
        if page is None:
            return
        page["keys"].pop(str(key), None)
        await self.async_set_layout(self.layout)
