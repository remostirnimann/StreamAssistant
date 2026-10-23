"""Config flow for Stream Assistant.

The dock is identified by its serial number, never by its address. Address
changes are picked up from two sources:

- mDNS (_elg._tcp): the dock announces serial, MAC and current IP
- DHCP: for docks whose MAC is known, Home Assistant reports new leases
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_MAC
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import (
    CONF_DECK_PRODUCT_ID,
    CONF_DECK_SERIAL,
    CONF_DOCK_SERIAL,
    CONF_KIND,
    DOMAIN,
    KIND_PLANNER,
    PLANNER_UNIQUE_ID,
)
from .protocol import NETWORK_DOCK_DEVICE_TYPE, ChildInfo, CoraError, DockInfo, find_model, probe

_LOGGER = logging.getLogger(__name__)


def _entry_data(
    host: str, mac: str | None, dock: DockInfo, child: ChildInfo | None
) -> dict[str, Any]:
    return {
        CONF_HOST: host,
        CONF_MAC: mac,
        CONF_DOCK_SERIAL: dock.serial,
        CONF_DECK_SERIAL: child.serial if child else None,
        CONF_DECK_PRODUCT_ID: child.product_id if child else None,
    }


class StreamAssistantConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a Stream Deck Network Dock."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the flow."""
        self._host: str | None = None
        self._mac: str | None = None
        self._dock: DockInfo | None = None
        self._child: ChildInfo | None = None

    async def _probe(self, host: str) -> str | None:
        """Read dock info, return an error key on failure."""
        try:
            self._dock, self._child = await probe(host)
        except CoraError as err:
            _LOGGER.debug("Probe of %s failed: %s", host, err)
            return "cannot_connect"
        self._host = host
        return None

    def _title(self) -> str:
        assert self._dock
        if self._child and (model := find_model(self._child.product_id)):
            return f"{model.name} ({self._dock.serial})"
        return f"Stream Deck Network Dock ({self._dock.serial})"

    def _description_placeholders(self) -> dict[str, str]:
        if self._child is None:
            deck = "-"
        elif model := find_model(self._child.product_id):
            deck = f"{model.name} ({self._child.serial})"
        else:
            deck = f"unsupported (product id {self._child.product_id:#06x})"
        return {"host": self._host or "", "deck": deck}

    def _create_entry(self) -> ConfigFlowResult:
        assert self._host and self._dock
        return self.async_create_entry(
            title=self._title(),
            data=_entry_data(self._host, self._mac, self._dock, self._child),
        )

    def _address_updates(self, host: str, mac: str | None) -> dict[str, Any]:
        """Data to update on an existing entry. A known MAC is never cleared."""
        updates: dict[str, Any] = {CONF_HOST: host}
        if mac:
            updates[CONF_MAC] = mac
        return updates

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add a dock, or only enable planning (templates) without hardware."""
        return self.async_show_menu(step_id="user", menu_options=["dock", "planner"])

    async def async_step_planner(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Entry without hardware: loads the editor so templates can be planned."""
        await self.async_set_unique_id(PLANNER_UNIQUE_ID)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="Stream Assistant", data={CONF_KIND: KIND_PLANNER})
        return self.async_show_form(step_id="planner")

    async def async_step_dock(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual setup by IP address or hostname."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            if not (error := await self._probe(host)):
                assert self._dock
                await self.async_set_unique_id(self._dock.serial)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                # The MAC is filled in by the next mDNS announcement
                return self._create_entry()
            errors["base"] = error

        return self.async_show_form(
            step_id="dock",
            data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
            errors=errors,
        )

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> ConfigFlowResult:
        """A dock announced itself via mDNS (_elg._tcp)."""
        properties = discovery_info.properties
        if str(properties.get("dt")) != str(NETWORK_DOCK_DEVICE_TYPE):
            # Decks behind a dock announce themselves too, they are handled via the dock
            return self.async_abort(reason="not_network_dock")

        host = discovery_info.host
        raw_mac = properties.get("id")
        self._mac = format_mac(raw_mac) if raw_mac else None

        if serial := properties.get("sn"):
            await self.async_set_unique_id(serial)
            # Known dock: only refresh its address (reloads the entry if it changed)
            self._abort_if_unique_id_configured(
                updates=self._address_updates(host, self._mac)
            )

        if await self._probe(host):
            return self.async_abort(reason="cannot_connect")
        assert self._dock
        await self.async_set_unique_id(self._dock.serial)
        self._abort_if_unique_id_configured(
            updates=self._address_updates(host, self._mac)
        )

        self.context["title_placeholders"] = {"name": self._title()}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to confirm a discovered dock."""
        if user_input is not None:
            return self._create_entry()
        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders=self._description_placeholders(),
        )

    async def async_step_dhcp(self, discovery_info: DhcpServiceInfo) -> ConfigFlowResult:
        """A configured dock got a (new) DHCP lease.

        Only registered devices are matched (see manifest), so this never
        sets up new docks; it just keeps the address of known ones current.
        """
        mac = format_mac(discovery_info.macaddress)
        entry: ConfigEntry | None = next(
            (e for e in self._async_current_entries() if e.data.get(CONF_MAC) == mac),
            None,
        )
        if entry is None:
            return self.async_abort(reason="not_network_dock")

        if entry.data.get(CONF_HOST) != discovery_info.ip:
            _LOGGER.info(
                "Dock %s moved from %s to %s (DHCP)",
                entry.unique_id,
                entry.data.get(CONF_HOST),
                discovery_info.ip,
            )
            self.hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_HOST: discovery_info.ip}
            )
            self.hass.config_entries.async_schedule_reload(entry.entry_id)
        return self.async_abort(reason="already_configured")
