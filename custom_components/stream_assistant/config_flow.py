"""Config flow for Stream Assistant."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import CONF_DECK_PRODUCT_ID, CONF_DECK_SERIAL, CONF_DOCK_SERIAL, DOMAIN
from .protocol import NETWORK_DOCK_DEVICE_TYPE, ChildInfo, CoraError, DockInfo, find_model, probe

_LOGGER = logging.getLogger(__name__)


def _entry_data(host: str, dock: DockInfo, child: ChildInfo | None) -> dict[str, Any]:
    return {
        CONF_HOST: host,
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

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manual setup by IP address."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            if not (error := await self._probe(host)):
                assert self._dock
                await self.async_set_unique_id(self._dock.serial)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host})
                return self.async_create_entry(
                    title=self._title(), data=_entry_data(host, self._dock, self._child)
                )
            errors["base"] = error

        return self.async_show_form(
            step_id="user",
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
        if serial := properties.get("sn"):
            await self.async_set_unique_id(serial)
            self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        if await self._probe(host):
            return self.async_abort(reason="cannot_connect")
        assert self._dock
        await self.async_set_unique_id(self._dock.serial)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host})

        self.context["title_placeholders"] = {"name": self._title()}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to confirm a discovered dock."""
        assert self._host and self._dock
        if user_input is not None:
            return self.async_create_entry(
                title=self._title(),
                data=_entry_data(self._host, self._dock, self._child),
            )
        return self.async_show_form(
            step_id="zeroconf_confirm",
            description_placeholders=self._description_placeholders(),
        )
