"""Runtime object for one deck (behind a dock or bridge, or virtual): connection, layout, live key images, key actions."""

from __future__ import annotations

from collections.abc import Hashable
import copy
from dataclasses import dataclass
from datetime import datetime
import logging
import secrets
import time
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_MAC
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .actions import adjust_call, async_run_action, async_run_adjust
from .behavior import BehaviorController
from .capabilities import DeckCapabilities, find_capabilities, grid_capabilities
from .const import (
    CONF_COLS,
    CONF_DECK_PRODUCT_ID,
    CONF_DECK_SERIAL,
    CONF_DOCK_SERIAL,
    CONF_KIND,
    CONF_ROWS,
    DIAL_BASE_SECONDS,
    DIAL_SETTLE_SECONDS,
    DOMAIN,
    EVENT_LONG_PRESS,
    EVENT_PRESSED,
    EVENT_RELEASED,
    EVENT_ROTATE_LEFT,
    EVENT_ROTATE_RIGHT,
    EVENT_SHORT_PRESS,
    EVENT_SWIPE_LEFT,
    EVENT_SWIPE_RIGHT,
    EVENT_TAP,
    KIND_BRIDGE,
    KIND_DOCK,
    KIND_VIRTUAL,
    LONG_PRESS_SECONDS,
    VERSION,
    signal_dial,
    signal_key,
    signal_state,
    signal_touch,
)
from .display import page_dial_visual, page_key_slot, page_key_visual
from .layout import (
    ACTION_BACK,
    ACTION_NONE,
    ACTION_PAGE,
    KEY_SCHEMA,
    ROOT_PAGE_ID,
    ROTATE_ACTIONS,
    ROTATE_ADJUST,
    SECOND_LINE_NONE,
    empty_layout,
    merge_into_template,
    migrate_v1,
    remap_layout,
    validate_layout,
)
from .preview import RenderCache
from .protocol import find_model
from .protocol.bridge import BridgeDevice, TouchEvent
from .render import KeyVisual
from .templates import DATA_TEMPLATES
from .transport import AttachedDeck, DeckTransport, NetworkDockTransport, TransportError, VirtualTransport

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 2
SAVE_DELAY = 2
DEFAULT_BRIGHTNESS = 70
BACK_ACTION = {"type": ACTION_BACK}
NO_ACTION = {"type": ACTION_NONE}
# Detents of one turn that run "actions" one by one; more are dropped
MAX_ROTATE_ACTIONS = 5

# runtime_data: the deck of a dock or virtual panel, or the hub of a bridge (see bridge_hub.py)
type StreamAssistantConfigEntry = ConfigEntry[Any]


@dataclass(frozen=True, slots=True)
class BridgeDeckSpec:
    """A deck behind a Stream Assistant Bridge; several share one config entry."""

    device: BridgeDevice
    capabilities: DeckCapabilities
    transport: DeckTransport
    # Device registry id of the bridge, the deck's via_device
    hub_device_id: str
    # Unique per bridge and deck; prefix of the entity unique ids
    unique_id: str


class LayoutStore(Store[dict[str, Any]]):
    """Layout storage with migration from the set_key-only version 1."""

    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: dict[str, Any]
    ) -> dict[str, Any]:
        if old_major_version == 1:
            return migrate_v1(old_data)
        return old_data


def _layout_store(hass: HomeAssistant, key: str) -> LayoutStore:
    return LayoutStore(hass, STORAGE_VERSION, f"{DOMAIN}.{key}")


def deck_key(entry_id: str, bridge_device_id: str | None = None) -> str:
    """Address of a deck: the entry id, plus the device id for bridge decks."""
    return f"{entry_id}.{bridge_device_id}" if bridge_device_id else entry_id


async def async_remove_layout(hass: HomeAssistant, key: str) -> None:
    """Delete the stored layout of a removed deck."""
    await _layout_store(hass, key).async_remove()


class StreamAssistantDevice:
    """One deck: behind a Network Dock (which may be empty), behind a bridge, or virtual."""

    def __init__(
        self, hass: HomeAssistant, entry: StreamAssistantConfigEntry, bridge: BridgeDeckSpec | None = None
    ) -> None:
        """Initialize."""
        self.hass = hass
        self.entry = entry
        self.bridge = bridge
        self.kind = KIND_BRIDGE if bridge else entry.data.get(CONF_KIND, KIND_DOCK)
        self.virtual = self.kind == KIND_VIRTUAL
        # Address in signals, storage and the editor's WebSocket API
        self.key = deck_key(entry.entry_id, bridge.device.id if bridge else None)
        self.transport: DeckTransport
        self.dock_serial: str | None
        self.deck_serial: str | None = entry.data.get(CONF_DECK_SERIAL)
        # The model is fixed per config entry so the key entities exist even while offline
        self.model: DeckCapabilities | None
        self._dock_device_id: str | None = None
        if bridge:
            found = bridge.device
            self.transport = bridge.transport
            self.dock_serial = None
            self.deck_serial = bridge.unique_id
            self.model = bridge.capabilities
            self._dock_device_id = bridge.hub_device_id
            self.brightness = 100 if found.virtual else DEFAULT_BRIGHTNESS
        elif self.virtual:
            assert self.deck_serial
            self.model = grid_capabilities(entry.data[CONF_COLS], entry.data[CONF_ROWS])
            self.transport = VirtualTransport(self.deck_serial, self.model, VERSION)
            self.dock_serial = None
            # A screen at 70 % looks broken; there is no LED wear to save
            self.brightness = 100
        else:
            self.transport = NetworkDockTransport(entry.data[CONF_HOST])
            self.dock_serial = entry.data[CONF_DOCK_SERIAL]
            product_id = entry.data.get(CONF_DECK_PRODUCT_ID)
            hardware = find_model(product_id) if product_id else None
            self.model = find_capabilities(hardware.model_id) if hardware else None
            self.brightness = DEFAULT_BRIGHTNESS
        self.templates = hass.data[DATA_TEMPLATES]
        # What the deck shows: the own layout, or the linked template's (fitted to this model)
        self.layout: dict[str, Any] = empty_layout()
        self._own_layout: dict[str, Any] = empty_layout()
        self.template_id: str | None = None
        # Keys of the template that do not fit this deck's grid
        self.template_dropped = 0
        self._unsub_template: CALLBACK_TYPE | None = None
        # Bumped on every change; the editor sends it back to detect stale saves.
        # The random prefix keeps revisions from before a restart from matching.
        self._revision_prefix = secrets.token_hex(4)
        self._revision_counter = 0
        self.current_page = ROOT_PAGE_ID

        self._store = _layout_store(hass, self.key)
        # Keys are ints, dials ("dial", index): both are pressed the same way
        self._long_press_timers: dict[Hashable, CALLBACK_TYPE] = {}
        self._short_done: set[Hashable] = set()
        self._unsub_states: CALLBACK_TYPE | None = None
        # What each key (int) and strip segment (("dial", index)) should show;
        # a finished render is only sent if it still matches
        self._wanted: dict[Hashable, KeyVisual] = {}
        # Dial detents waiting to become one adjustment, and the value the last one set
        self._dial_pending: dict[int, int] = {}
        self._dial_flush: dict[int, CALLBACK_TYPE] = {}
        self._dial_base: dict[int, tuple[float, float]] = {}
        self._renderer = RenderCache(hass)
        self.behavior = BehaviorController(hass, self._apply_brightness)
        self.deck_connected_since: datetime | None = None
        # Keys and dials whose press only woke the display: their release is ignored too
        self._swallowed: set[Hashable] = set()

    @property
    def title(self) -> str:
        """Name shown in the editor and logs."""
        return self.bridge.device.name if self.bridge else self.entry.title

    @property
    def layout_revision(self) -> str:
        """Identifies the current layout version."""
        return f"{self._revision_prefix}-{self._revision_counter}"

    # Device info

    @property
    def dock_connected(self) -> bool:
        """Return True while the dock is reachable."""
        return self.transport.hub_connected

    @property
    def deck_connected(self) -> bool:
        """Return True when the deck accepts commands."""
        return self.transport.deck_connected

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
        """Device info of the attached deck (or the virtual panel)."""
        assert self.model and self.deck_serial
        if self.virtual:
            return DeviceInfo(
                identifiers={(DOMAIN, self.deck_serial)},
                manufacturer="Stream Assistant",
                model=f"Virtual panel {self.model.name}",
                name=self.entry.title,
                sw_version=VERSION,
            )
        if self.bridge:
            found = self.bridge.device
            info = DeviceInfo(
                identifiers={(DOMAIN, self.deck_serial)},
                manufacturer=found.vendor or None,
                model=found.model or None,
                name=found.name,
                serial_number=found.serial,
                sw_version=found.firmware,
            )
        else:
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
        behavior = None
        if stored := await self._store.async_load():
            try:
                self._own_layout = validate_layout({"pages": stored["pages"]}, None)
            except (vol.Invalid, KeyError, TypeError) as err:
                # Damaged or from an incompatible version: start empty instead of failing later
                _LOGGER.warning("%s: stored layout is invalid (%s), starting with an empty one", self.title, err)
                self._own_layout = empty_layout()
            grid = stored.get("grid")
            if self.model and grid and grid != [self.model.cols, self.model.rows]:
                # The grid of a virtual panel was changed: keep keys at their row and column
                self._own_layout, dropped = remap_layout(self._own_layout, grid[0], self.model.cols, self.model.rows)
                _LOGGER.info("%s: grid changed to %s, %s keys did not fit", self.title, self.model.name, dropped)
                self._store.async_delay_save(self._data_to_store, SAVE_DELAY)
            if (template_id := stored.get("template_id")) and self.templates.get(template_id):
                self._link(template_id)
            behavior = stored.get("behavior")
        self._update_effective_layout()
        self.behavior.async_start(behavior)

        if self.kind == KIND_DOCK:
            dev_reg = dr.async_get(self.hass)
            dock = dev_reg.async_get_or_create(config_entry_id=self.entry.entry_id, **self.dock_device_info)
            self._dock_device_id = dock.id

        self.transport.on_hub_state = self._on_dock_state
        self.transport.on_deck_connected = self._on_deck_connected
        self.transport.on_deck_disconnected = self._on_deck_disconnected
        self.transport.on_key = self._on_key
        self.transport.on_dial = self._on_dial
        self.transport.on_dial_press = self._on_dial_press
        self.transport.on_touch = self._on_touch
        self._track_page_entities()
        self.transport.start()

    async def async_stop(self) -> None:
        """Disconnect and flush storage."""
        self._cancel_timers()
        if self._unsub_states:
            self._unsub_states()
            self._unsub_states = None
        if self._unsub_template:
            self._unsub_template()
            self._unsub_template = None
        self.behavior.async_stop()
        await self.transport.stop()
        await self._store.async_save(self._data_to_store())

    def _data_to_store(self) -> dict[str, Any]:
        return {
            **self._own_layout,
            "template_id": self.template_id,
            "behavior": self.behavior.settings,
            # Grid the own layout was made for, to follow later grid changes
            "grid": [self.model.cols, self.model.rows] if self.model else None,
        }

    # Behavior and info

    @callback
    def _apply_brightness(self) -> None:
        """Send the brightness the behavior asks for (normal, night or dimmed)."""
        if self.deck_connected and self.model and self.model.has_display:
            try:
                self.transport.set_brightness(self.behavior.target_brightness(self.brightness))
            except TransportError as err:
                _LOGGER.debug("Setting brightness failed: %s", err)
        async_dispatcher_send(self.hass, signal_state(self.key))

    async def async_set_behavior(self, settings: dict[str, Any]) -> None:
        """Store new automation settings and apply them right away."""
        self.behavior.async_start(settings)
        self._store.async_delay_save(self._data_to_store, SAVE_DELAY)

    def info(self) -> dict[str, Any]:
        """Facts for the editor's info page."""
        hub = self.transport.hub_info()
        deck = self.transport.deck
        pages = self.layout["pages"]
        deadline = self.behavior.idle_deadline
        return {
            "kind": self.kind,
            "virtual": self.virtual,
            "dock": {
                "name": hub.get("name"),
                "serial": self.dock_serial or hub.get("serial"),
                "firmware": hub.get("firmware"),
                "host": hub.get("host"),
                "mac": self.entry.data.get(CONF_MAC),
                "connected": self.dock_connected,
            },
            "deck": {
                "model": self.model.name if self.model else None,
                "serial": self.deck_serial,
                "firmware": deck.firmware if deck else None,
                "connected": self.deck_connected,
                "connected_since": self.deck_connected_since.isoformat() if self.deck_connected_since else None,
                "key_count": self.model.key_count if self.model else None,
                "dial_count": self.model.dials if self.model else None,
            },
            "brightness": {
                "base": self.brightness,
                "current": self.behavior.target_brightness(self.brightness),
                "night_active": self.behavior.night_active,
                "dimmed": self.behavior.dimmed,
                "dims_at": deadline.isoformat() if deadline else None,
            },
            "layout": {
                "template_id": self.template_id,
                "pages": len(pages),
                "folders": sum(1 for p in pages if p.get("parent")),
                "keys": sum(len(p["keys"]) for p in pages),
                "current_page": self.current_page,
            },
            "behavior": self.behavior.settings,
        }

    # Layout

    def page(self, page_id: str) -> dict[str, Any] | None:
        """Return a page of the layout."""
        return next((p for p in self.layout["pages"] if p["id"] == page_id), None)

    def _update_effective_layout(self) -> None:
        template = self.templates.get(self.template_id) if self.template_id else None
        template_model = self.templates.model(self.template_id) if template else None
        if template and template_model and self.model:
            self.layout, self.template_dropped = remap_layout(
                template["layout"], template_model.cols, self.model.cols, self.model.rows, self.model.dials
            )
        elif template:
            self.layout, self.template_dropped = copy.deepcopy(template["layout"]), 0
        else:
            self.layout, self.template_dropped = self._own_layout, 0

    @callback
    def _refresh(self) -> None:
        """Show the (changed) layout on the deck."""
        self._revision_counter += 1
        if self.page(self.current_page) is None:
            self.current_page = ROOT_PAGE_ID
        self._track_page_entities()
        self._schedule_repaint()
        async_dispatcher_send(self.hass, signal_state(self.key))

    async def async_set_layout(self, layout: dict[str, Any]) -> None:
        """Replace the whole layout (already validated for this deck) and show it.

        A linked deck writes into its template, which updates every linked deck.
        """
        if self.template_id and (template_model := self.templates.model(self.template_id)):
            if self.model and (template_model.cols, template_model.rows, template_model.dials) != (
                self.model.cols,
                self.model.rows,
                self.model.dials,
            ):
                layout = merge_into_template(
                    layout,
                    self.model.cols,
                    self.model.rows,
                    self.templates.get(self.template_id)["layout"],
                    template_model.cols,
                    template_model.rows,
                    self.model.dials,
                    template_model.dials,
                )
            await self.templates.async_set_layout(self.template_id, layout)
            return
        self._own_layout = layout
        self._store.async_delay_save(self._data_to_store, SAVE_DELAY)
        self._update_effective_layout()
        self._refresh()

    @callback
    def _link(self, template_id: str) -> None:
        if self._unsub_template:
            self._unsub_template()
        self.template_id = template_id
        self._unsub_template = self.templates.async_subscribe(template_id, self._on_template_change)

    @callback
    def _on_template_change(self, template: dict[str, Any]) -> None:
        if template.get("deleted"):
            # Keep showing the same keys, now as our own layout
            self._own_layout = copy.deepcopy(self.layout)
            self.template_id = None
            self._unsub_template = None
            self._store.async_delay_save(self._data_to_store, SAVE_DELAY)
        self._update_effective_layout()
        self._refresh()

    async def async_link_template(self, template_id: str) -> None:
        """Show (and edit) a template's layout on this deck."""
        self._link(template_id)
        self._store.async_delay_save(self._data_to_store, SAVE_DELAY)
        self._update_effective_layout()
        self._refresh()

    async def async_detach_template(self) -> None:
        """Stop following the template, keeping its current layout as a copy."""
        if not self.template_id:
            return
        self._own_layout = copy.deepcopy(self.layout)
        if self._unsub_template:
            self._unsub_template()
            self._unsub_template = None
        self.template_id = None
        self._store.async_delay_save(self._data_to_store, SAVE_DELAY)
        self._update_effective_layout()
        self._refresh()

    async def async_show_page(self, page_id: str) -> None:
        """Switch the deck to another page."""
        if self.page(page_id) is None:
            return
        self.current_page = page_id
        self._cancel_timers()
        self._track_page_entities()
        self._schedule_repaint()
        async_dispatcher_send(self.hass, signal_state(self.key))

    def _actions(self, index: int) -> tuple[dict[str, Any], dict[str, Any]]:
        page = self.page(self.current_page)
        if page is None:
            return NO_ACTION, NO_ACTION
        key, is_back = page_key_slot(page, index)
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
        controls = [*page["keys"].values(), *page.get("dials", {}).values()]
        entities = {c["entity_id"] for c in controls if c.get("entity_id")}
        if entities:
            self._unsub_states = async_track_state_change_event(self.hass, sorted(entities), self._on_state_change)

    @callback
    def _on_state_change(self, event: Event[EventStateChangedData]) -> None:
        page = self.page(self.current_page)
        if page is None:
            return
        entity_id = event.data["entity_id"]
        keys = [int(i) for i, k in page["keys"].items() if k.get("entity_id") == entity_id]
        dials = [int(i) for i, d in page.get("dials", {}).items() if d.get("entity_id") == entity_id]
        self._schedule_repaint(keys, dials)

    # Painting

    @callback
    def _schedule_repaint(self, keys: list[int] | None = None, dials: list[int] | None = None) -> None:
        """Paint some keys and strip segments; everything when neither is given."""
        if not self.model or not self.deck_connected or not self.model.has_display:
            # Painted on the next connect; nothing to paint on pedals
            return
        everything = keys is None and dials is None
        key_list = list(range(self.model.key_count)) if everything else keys or []
        dial_list = list(range(self.model.dials)) if everything else dials or []
        self.entry.async_create_background_task(
            self.hass, self._async_paint(key_list, dial_list), "stream_assistant paint"
        )

    async def _async_paint(self, keys: list[int], dials: list[int] | None = None) -> None:
        if not self.model:
            return
        page = self.page(self.current_page)
        if page is None:
            return
        if dials and self.model.segment_width:
            await self._async_paint_segments(page, dials)
        for index in keys:
            if index >= self.model.key_count:
                continue
            visual = page_key_visual(self.hass, page, index)
            self._wanted[index] = visual
            jpeg = await self._renderer.async_render(self.model, visual, upright=False)
            if self._wanted.get(index) != visual or not self.deck_connected:
                continue
            try:
                self.transport.set_key_image(index, jpeg)
            except TransportError as err:
                _LOGGER.debug("Painting key %s failed: %s", index, err)
                return

    async def _async_paint_segments(self, page: dict[str, Any], dials: list[int]) -> None:
        assert self.model
        width = self.model.segment_width
        for index in dials:
            if index >= self.model.dials:
                continue
            visual = page_dial_visual(self.hass, page, index)
            self._wanted[("dial", index)] = visual
            jpeg = await self._renderer.async_render_segment(self.model, visual)
            if self._wanted.get(("dial", index)) != visual or not self.deck_connected:
                continue
            try:
                self.transport.set_touch_image(index * width, 0, width, self.model.touch_height, jpeg)
            except TransportError as err:
                _LOGGER.debug("Painting the touch strip failed: %s", err)
                return

    async def async_render_page_preview(self, page: dict[str, Any]) -> list[bytes]:
        """Upright JPEGs of every key of a (possibly unsaved) page, for the editor."""
        assert self.model
        return await self._renderer.async_page_preview(self.model, page)

    # Connection callbacks (event loop)

    @callback
    def _on_dock_state(self, connected: bool) -> None:
        firmware = self.transport.hub_info().get("firmware")
        if connected and firmware and self._dock_device_id:
            dr.async_get(self.hass).async_update_device(self._dock_device_id, sw_version=firmware)
        async_dispatcher_send(self.hass, signal_state(self.key))

    @callback
    def _on_deck_connected(self, deck: AttachedDeck) -> None:
        caps = deck.capabilities
        if self.kind == KIND_DOCK and (
            deck.serial != self.deck_serial or self.model is None or caps.model_id != self.model.model_id
        ):
            # Another deck was plugged in: store it and rebuild the entities
            _LOGGER.info(
                "Dock %s: now has %s (%s) attached, reloading",
                self.dock_serial,
                caps.name,
                deck.serial,
            )
            self.hass.config_entries.async_update_entry(
                self.entry,
                title=f"{caps.name} ({self.dock_serial})",
                data={
                    **self.entry.data,
                    CONF_DECK_SERIAL: deck.serial,
                    CONF_DECK_PRODUCT_ID: deck.hardware_id,
                },
            )
            self.hass.config_entries.async_schedule_reload(self.entry.entry_id)
            return

        if deck.firmware and self.kind == KIND_DOCK:
            dr.async_get(self.hass).async_get_or_create(
                config_entry_id=self.entry.entry_id,
                identifiers={(DOMAIN, deck.serial)},
                sw_version=deck.firmware,
            )

        self.deck_connected_since = dt_util.utcnow()
        # The idle time ran on while the deck was away: start it fresh, deck lit
        self.behavior.async_wake()
        # Normal, night or dimmed brightness, whatever applies right now
        self._apply_brightness()
        self._wanted.clear()
        self._schedule_repaint()

    @callback
    def _on_deck_disconnected(self) -> None:
        self._cancel_timers()
        self._swallowed.clear()
        self.deck_connected_since = None
        async_dispatcher_send(self.hass, signal_state(self.key))

    def _cancel_timers(self) -> None:
        for cancel in [*self._long_press_timers.values(), *self._dial_flush.values()]:
            cancel()
        self._long_press_timers.clear()
        self._short_done.clear()
        self._dial_flush.clear()
        self._dial_pending.clear()

    # Keys and dials

    def _only_wakes(self) -> bool:
        """Count activity; True when it only woke the dimmed display (never on pedals: nothing to wake)."""
        woke = self.behavior.async_activity()
        return woke and bool(self.model and self.model.has_display)

    def _dial(self, index: int, page: dict[str, Any] | None = None) -> dict[str, Any] | None:
        page = page or self.page(self.current_page)
        return page.get("dials", {}).get(str(index)) if page else None

    @callback
    def _on_key(self, key: int, pressed: bool) -> None:
        short, long = self._actions(key)
        self._on_press(key, pressed, signal_key(self.key, key), short, long)

    @callback
    def _on_dial_press(self, index: int, pressed: bool) -> None:
        dial = self._dial(index)
        short, long = (dial["short"], dial["long"]) if dial else (NO_ACTION, NO_ACTION)
        self._on_press(("dial", index), pressed, signal_dial(self.key, index), short, long)

    @callback
    def _on_press(self, key: Hashable, pressed: bool, signal: str, short: dict[str, Any], long: dict[str, Any]) -> None:
        """A key or dial went down or up: events, short and long press."""
        if pressed and self._only_wakes():
            # This press only woke the display: no events, no action
            self._swallowed.add(key)
            return
        if not pressed and key in self._swallowed:
            self._swallowed.discard(key)
            return

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
            self._long_press_timers[key] = async_call_later(self.hass, LONG_PRESS_SECONDS, _long_press)
            return

        async_dispatcher_send(self.hass, signal, EVENT_RELEASED)
        if cancel := self._long_press_timers.pop(key, None):
            # Released before the long press fired
            cancel()
            async_dispatcher_send(self.hass, signal, EVENT_SHORT_PRESS)
            if key not in self._short_done:
                self._run(short)
        self._short_done.discard(key)

    @callback
    def _on_dial(self, index: int, delta: int) -> None:
        if not delta or self._only_wakes():
            # Turning a dimmed deck only wakes it
            return
        async_dispatcher_send(
            self.hass,
            signal_dial(self.key, index),
            EVENT_ROTATE_RIGHT if delta > 0 else EVENT_ROTATE_LEFT,
            {"steps": abs(delta)},
        )
        self._rotate(index, delta, self._dial(index))

    @callback
    def _rotate(self, index: int, delta: int, dial: dict[str, Any] | None, page: dict[str, Any] | None = None) -> None:
        if not dial:
            return
        if dial["rotate"] == ROTATE_ACTIONS:
            action = dial["right"] if delta > 0 else dial["left"]
            for _ in range(min(abs(delta), MAX_ROTATE_ACTIONS)):
                self._run(action, page)
        elif dial["rotate"] == ROTATE_ADJUST and dial.get("entity_id"):
            # Fast turning: collect the detents into one service call
            self._dial_pending[index] = self._dial_pending.get(index, 0) + delta
            if index not in self._dial_flush:

                @callback
                def _flush(_now: Any) -> None:
                    self._dial_flush.pop(index, None)
                    self._adjust(index, self._dial_pending.pop(index, 0), dial)

                self._dial_flush[index] = async_call_later(self.hass, DIAL_SETTLE_SECONDS, _flush)

    @callback
    def _adjust(self, index: int, steps: int, dial: dict[str, Any]) -> None:
        entity_id = dial["entity_id"]
        if not steps or (state := self.hass.states.get(entity_id)) is None:
            return
        base = None
        if (last := self._dial_base.get(index)) and time.monotonic() - last[1] < DIAL_BASE_SECONDS:
            # The entity may not have reported the last value yet
            base = last[0]
        if (call := adjust_call(state, steps, dial.get("step"), base)) is None:
            _LOGGER.debug("%s: %s cannot be adjusted with a dial", self.title, entity_id)
            return
        if call.value is not None:
            self._dial_base[index] = (call.value, time.monotonic())
        self.entry.async_create_background_task(
            self.hass, async_run_adjust(self.hass, entity_id, call), "stream_assistant dial"
        )

    @callback
    def _on_touch(self, event: TouchEvent) -> None:
        if self._only_wakes():
            # Touching a dimmed deck only wakes it
            return
        dial_index = self.model.segment(event.x) if self.model else None
        data: dict[str, Any] = {"x": event.x, "y": event.y, "dial": dial_index}
        if event.kind == "swipe":
            end = event.x2 if event.x2 is not None else event.x
            kind = EVENT_SWIPE_RIGHT if end >= event.x else EVENT_SWIPE_LEFT
            data.update(x2=end, y2=event.y2)
        else:
            kind = EVENT_LONG_PRESS if event.kind == "long" else EVENT_TAP
        async_dispatcher_send(self.hass, signal_touch(self.key), kind, data)
        if dial_index is not None and kind in (EVENT_TAP, EVENT_LONG_PRESS) and (dial := self._dial(dial_index)):
            self._run(dial["long"] if kind == EVENT_LONG_PRESS else dial["short"])

    async def async_simulate_dial(self, index: int, gesture: str, page: dict[str, Any] | None = None) -> None:
        """Behave as if a dial was used: "short" / "long" push, or "left" / "right" by one detent."""
        page = page or self.page(self.current_page)
        dial = self._dial(index, page)
        self.behavior.async_activity()
        signal = signal_dial(self.key, index)
        if gesture in ("left", "right"):
            delta = 1 if gesture == "right" else -1
            async_dispatcher_send(
                self.hass, signal, EVENT_ROTATE_RIGHT if delta > 0 else EVENT_ROTATE_LEFT, {"steps": 1}
            )
            self._rotate(index, delta, dial, page)
            return
        long_press = gesture == "long"
        async_dispatcher_send(self.hass, signal, EVENT_PRESSED)
        async_dispatcher_send(self.hass, signal, EVENT_LONG_PRESS if long_press else EVENT_RELEASED)
        async_dispatcher_send(self.hass, signal, EVENT_RELEASED if long_press else EVENT_SHORT_PRESS)
        if dial:
            self._run(dial["long" if long_press else "short"], page)

    async def async_simulate_press(self, index: int, long_press: bool, page: dict[str, Any] | None = None) -> None:
        """Behave as if a key was pressed: key events plus its action.

        `page` is the editor's (possibly unsaved) page; default is the page shown.
        """
        page = page or self.page(self.current_page)
        if page is None:
            return
        key, is_back = page_key_slot(page, index)
        if is_back:
            short, long = BACK_ACTION, NO_ACTION
        elif key:
            short, long = key["short"], key["long"]
        else:
            short, long = NO_ACTION, NO_ACTION

        # A test press counts as activity (wakes the display) but always runs
        self.behavior.async_activity()
        signal = signal_key(self.key, index)
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
        self._apply_brightness()

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
