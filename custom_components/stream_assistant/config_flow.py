"""Config flow for Stream Assistant.

Docks and bridges are identified by their serial number / bridge id, never by
their address. Bridges announce themselves via mDNS (_stream-assistant._tcp)
and are paired once with the code they show. The bridge add-on announces itself
through the Supervisor instead, with a token, so it needs no code.

Dock address changes are picked up from two sources:

- mDNS (_elg._tcp): the dock announces serial, MAC and current IP
- DHCP: for docks whose MAC is known, Home Assistant reports new leases
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
import secrets
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_MAC, CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import NumberSelector, NumberSelectorConfig, NumberSelectorMode
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.service_info.hassio import HassioServiceInfo
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
import voluptuous as vol

from .capabilities import MAX_COLS, MAX_ROWS
from .const import (
    CONF_AUTO_UPDATE,
    CONF_BRIDGE_ID,
    CONF_COLS,
    CONF_DECK_PRODUCT_ID,
    CONF_DECK_SERIAL,
    CONF_DEVICES,
    CONF_DOCK_SERIAL,
    CONF_KIND,
    CONF_PORT,
    CONF_ROWS,
    CONF_TOKEN,
    DOMAIN,
    KIND_BRIDGE,
    KIND_PLANNER,
    KIND_VIRTUAL,
    PLANNER_UNIQUE_ID,
    VERSION as CLIENT_VERSION,
)
from .protocol import NETWORK_DOCK_DEVICE_TYPE, ChildInfo, CoraError, DockInfo, find_model, probe
from .protocol.bridge import (
    DEFAULT_PORT as BRIDGE_PORT,
    SERVICE_TYPE as BRIDGE_SERVICE,
    BridgeError,
    BridgeInfo,
    fetch_info,
    pair,
)

_LOGGER = logging.getLogger(__name__)


def _entry_data(host: str, mac: str | None, dock: DockInfo, child: ChildInfo | None) -> dict[str, Any]:
    return {
        CONF_HOST: host,
        CONF_MAC: mac,
        CONF_DOCK_SERIAL: dock.serial,
        CONF_DECK_SERIAL: child.serial if child else None,
        CONF_DECK_PRODUCT_ID: child.product_id if child else None,
    }


def _grid_schema(cols: int, rows: int) -> dict[Any, Any]:
    def box(maximum: int) -> NumberSelector:
        return NumberSelector(NumberSelectorConfig(min=1, max=maximum, step=1, mode=NumberSelectorMode.BOX))

    return {
        vol.Required(CONF_COLS, default=cols): box(MAX_COLS),
        vol.Required(CONF_ROWS, default=rows): box(MAX_ROWS),
    }


class StreamAssistantConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up a Stream Deck Network Dock."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Options of bridge entries."""
        return BridgeOptionsFlow()

    @classmethod
    @callback
    def async_supports_options_flow(cls, config_entry: ConfigEntry) -> bool:
        """Only bridges have options (automatic updates)."""
        return config_entry.data.get(CONF_KIND) == KIND_BRIDGE

    def __init__(self) -> None:
        """Initialize the flow."""
        self._host: str | None = None
        self._mac: str | None = None
        self._dock: DockInfo | None = None
        self._child: ChildInfo | None = None
        self._port = BRIDGE_PORT
        self._bridge: BridgeInfo | None = None
        self._token: str | None = None

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

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Add a dock, a bridge or a virtual panel, or only enable planning (templates)."""
        return self.async_show_menu(step_id="user", menu_options=["dock", "bridge", "virtual", "planner"])

    # Bridge

    async def async_step_bridge(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manual bridge setup by address."""
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input[CONF_PORT])
            try:
                self._bridge = await fetch_info(async_get_clientsession(self.hass), host, port)
            except BridgeError:
                errors["base"] = "cannot_connect_bridge"
            else:
                await self.async_set_unique_id(self._bridge.id)
                self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port})
                self._host, self._port = host, port
                return await self.async_step_pair()
        return self.async_show_form(
            step_id="bridge",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_PORT, default=BRIDGE_PORT): vol.All(vol.Coerce(int), vol.Range(1, 65535)),
                }
            ),
            errors=errors,
        )

    async def _async_pair(self, code: str) -> tuple[BridgeInfo, str] | str:
        """Pair; returns info and token, or an error key."""
        assert self._host
        try:
            return await pair(async_get_clientsession(self.hass), self._host, self._port, code.strip(), CLIENT_VERSION)
        except BridgeError as err:
            return "invalid_code" if err.code == "invalid_code" else "cannot_connect_bridge"

    async def async_step_pair(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Enter the pairing code the bridge shows."""
        assert self._bridge
        errors: dict[str, str] = {}
        if user_input is not None:
            result = await self._async_pair(user_input["code"])
            if isinstance(result, str):
                errors["base"] = result
            else:
                info, token = result
                return self.async_create_entry(
                    title=info.name or self._bridge.name,
                    data={
                        CONF_KIND: KIND_BRIDGE,
                        CONF_HOST: self._host,
                        CONF_PORT: self._port,
                        CONF_BRIDGE_ID: info.id or self._bridge.id,
                        CONF_TOKEN: token,
                        CONF_DEVICES: {},
                    },
                )
        return self.async_show_form(
            step_id="pair",
            data_schema=vol.Schema({vol.Required("code"): str}),
            description_placeholders={
                "name": self._bridge.name,
                "host": f"{self._host}:{self._port}",
                "port": str(self._port),
            },
            errors=errors,
        )

    async def _async_step_bridge_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        properties = discovery_info.properties
        bridge_id = properties.get("id")
        if not bridge_id:
            return self.async_abort(reason="cannot_connect_bridge")
        host, port = discovery_info.host, discovery_info.port or BRIDGE_PORT
        await self.async_set_unique_id(bridge_id)
        # Known bridge: follow its address (reloads the entry if it changed)
        self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port})
        self._host, self._port = host, port
        self._bridge = BridgeInfo(bridge_id, properties.get("name") or host, properties.get("version") or "")
        self.context["title_placeholders"] = {"name": self._bridge.name}
        return await self.async_step_pair()

    async def async_step_hassio(self, discovery_info: HassioServiceInfo) -> ConfigFlowResult:
        """The bridge add-on announced itself through the Supervisor, with a token."""
        config = discovery_info.config
        bridge_id, host, token = config.get("bridge_id"), config.get("host"), config.get("token")
        if not (bridge_id and host and token):
            return self.async_abort(reason="cannot_connect_bridge")
        port = int(config.get("port") or BRIDGE_PORT)
        await self.async_set_unique_id(bridge_id)
        # Sent after every start of the add-on: keeps a known bridge's address and token
        self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: port, CONF_TOKEN: token})
        self._host, self._port, self._token = host, port, token
        try:
            self._bridge = await fetch_info(async_get_clientsession(self.hass), host, port)
        except BridgeError:
            self._bridge = BridgeInfo(bridge_id, discovery_info.name, "")
        self.context["title_placeholders"] = {"name": self._bridge.name}
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Confirm the add-on's bridge; it is already paired through the token."""
        assert self._bridge and self._token
        if user_input is not None:
            return self.async_create_entry(
                title=self._bridge.name,
                data={
                    CONF_KIND: KIND_BRIDGE,
                    CONF_HOST: self._host,
                    CONF_PORT: self._port,
                    CONF_BRIDGE_ID: self.unique_id,
                    CONF_TOKEN: self._token,
                    CONF_DEVICES: {},
                },
            )
        return self.async_show_form(step_id="hassio_confirm", description_placeholders={"name": self._bridge.name})

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """The bridge refused the token (e.g. it was reset): pair again."""
        self._host = entry_data[CONF_HOST]
        self._port = entry_data[CONF_PORT]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Enter a new pairing code."""
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            result = await self._async_pair(user_input["code"])
            if isinstance(result, str):
                errors["base"] = result
            elif result[0].id and result[0].id != entry.data[CONF_BRIDGE_ID]:
                errors["base"] = "wrong_bridge"
            else:
                return self.async_update_reload_and_abort(entry, data_updates={CONF_TOKEN: result[1]})
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required("code"): str}),
            description_placeholders={"name": entry.title, "host": f"{self._host}:{self._port}"},
            errors=errors,
        )

    async def async_step_virtual(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """A panel that only exists in Home Assistant, shown by a dashboard card."""
        if user_input is not None:
            # Stable id for the device and its entities, independent of the name
            serial = f"virtual-{secrets.token_hex(4)}"
            await self.async_set_unique_id(serial)
            return self.async_create_entry(
                title=user_input[CONF_NAME].strip() or "Virtual panel",
                data={
                    CONF_KIND: KIND_VIRTUAL,
                    CONF_DECK_SERIAL: serial,
                    CONF_COLS: int(user_input[CONF_COLS]),
                    CONF_ROWS: int(user_input[CONF_ROWS]),
                },
            )
        return self.async_show_form(
            step_id="virtual",
            data_schema=vol.Schema({vol.Required(CONF_NAME): str, **_grid_schema(5, 3)}),
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Change the grid of a virtual panel."""
        entry = self._get_reconfigure_entry()
        if entry.data.get(CONF_KIND) != KIND_VIRTUAL:
            return self.async_abort(reason="not_reconfigurable")
        if user_input is not None:
            return self.async_update_reload_and_abort(
                entry,
                data_updates={CONF_COLS: int(user_input[CONF_COLS]), CONF_ROWS: int(user_input[CONF_ROWS])},
            )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(_grid_schema(entry.data[CONF_COLS], entry.data[CONF_ROWS])),
        )

    async def async_step_planner(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Entry without hardware: loads the editor so templates can be planned."""
        await self.async_set_unique_id(PLANNER_UNIQUE_ID)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="Stream Assistant", data={CONF_KIND: KIND_PLANNER})
        return self.async_show_form(step_id="planner")

    async def async_step_dock(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
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

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        """A dock (_elg._tcp) or a bridge (_stream-assistant._tcp) announced itself via mDNS."""
        if discovery_info.type == BRIDGE_SERVICE:
            return await self._async_step_bridge_zeroconf(discovery_info)
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
            self._abort_if_unique_id_configured(updates=self._address_updates(host, self._mac))

        if await self._probe(host):
            return self.async_abort(reason="cannot_connect")
        assert self._dock
        await self.async_set_unique_id(self._dock.serial)
        self._abort_if_unique_id_configured(updates=self._address_updates(host, self._mac))

        self.context["title_placeholders"] = {"name": self._title()}
        return await self.async_step_zeroconf_confirm()

    async def async_step_zeroconf_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
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
            self.hass.config_entries.async_update_entry(entry, data={**entry.data, CONF_HOST: discovery_info.ip})
            self.hass.config_entries.async_schedule_reload(entry.entry_id)
        return self.async_abort(reason="already_configured")


class BridgeOptionsFlow(OptionsFlow):
    """Whether the bridge updates itself to the release that fits the integration."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the option."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = bool(self.config_entry.options.get(CONF_AUTO_UPDATE))
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({vol.Required(CONF_AUTO_UPDATE, default=current): bool}),
        )
