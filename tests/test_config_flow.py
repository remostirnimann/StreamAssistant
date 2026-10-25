"""Config flow: dock, bridge (pairing, discovery, reauth), virtual panel and planner."""

from __future__ import annotations

from ipaddress import ip_address
from unittest.mock import patch

from homeassistant.config_entries import SOURCE_DHCP, SOURCE_RECONFIGURE, SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.dhcp import DhcpServiceInfo
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stream_assistant.const import (
    CONF_BRIDGE_ID,
    CONF_COLS,
    CONF_DECK_SERIAL,
    CONF_KIND,
    CONF_PORT,
    CONF_ROWS,
    CONF_TOKEN,
    DOMAIN,
    KIND_BRIDGE,
    KIND_PLANNER,
    KIND_VIRTUAL,
)
from custom_components.stream_assistant.protocol import CoraError
from custom_components.stream_assistant.protocol.bridge import BridgeInfo

from .common import DECK_SERIAL, DOCK_PORT, DOCK_SERIAL, FakeDock, bridge_entry, virtual_entry
from .fake_bridge import BRIDGE_ID, FakeBridge

# The integration's setup is not part of these tests
SKIP_SETUP = patch("custom_components.stream_assistant.async_setup_entry", return_value=True)


async def _menu(hass: HomeAssistant, step: str) -> dict:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": step})


async def test_dock_manual(hass: HomeAssistant, fake_dock: FakeDock) -> None:
    result = await _menu(hass, "dock")
    with patch("custom_components.stream_assistant.config_flow.probe", side_effect=CoraError("unreachable")):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "10.0.0.1"})
    assert result["errors"] == {"base": "cannot_connect"}
    with SKIP_SETUP:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": " 127.0.0.1 "})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == f"Stream Deck MK.2 ({DOCK_SERIAL})"
    assert result["data"]["host"] == "127.0.0.1"
    assert result["data"][CONF_DECK_SERIAL] == DECK_SERIAL

    # The same dock again only updates the address
    result = await _menu(hass, "dock")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "127.0.0.1"})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "already_configured"


def _dock_zeroconf(**properties: str) -> ZeroconfServiceInfo:
    return ZeroconfServiceInfo(
        ip_address=ip_address("127.0.0.1"),
        ip_addresses=[ip_address("127.0.0.1")],
        hostname="dock.local.",
        name=f"Dock {DOCK_SERIAL}._elg._tcp.local.",
        port=DOCK_PORT,
        type="_elg._tcp.local.",
        properties={"dt": "215", "sn": DOCK_SERIAL, "id": "02:00:00:5A:00:01", **properties},
    )


async def test_dock_zeroconf(hass: HomeAssistant, fake_dock: FakeDock) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_dock_zeroconf(dt="20")
    )
    assert result["reason"] == "not_network_dock"

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_dock_zeroconf()
    )
    assert result["step_id"] == "zeroconf_confirm"
    assert "Stream Deck MK.2" in result["description_placeholders"]["deck"]
    with SKIP_SETUP:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"]["mac"] == "02:00:00:5a:00:01"

    # Known dock: a new announcement only refreshes its address
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_dock_zeroconf()
    )
    assert result["reason"] == "already_configured"


async def test_dock_zeroconf_unreachable(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_dock_zeroconf(sn="")
    )
    assert result["reason"] == "cannot_connect"


async def test_dock_follows_dhcp(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="SN1", data={"host": "10.0.0.1", "mac": "aa:bb:cc:dd:ee:ff"})
    entry.add_to_hass(hass)
    unknown = DhcpServiceInfo(ip="10.0.0.9", hostname="x", macaddress="112233445566")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=unknown)
    assert result["reason"] == "not_network_dock"

    moved = DhcpServiceInfo(ip="10.0.0.2", hostname="dock", macaddress="aabbccddeeff")
    with patch.object(hass.config_entries, "async_schedule_reload") as reload:
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_DHCP}, data=moved)
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == "10.0.0.2"
    reload.assert_called_once()


async def test_planner(hass: HomeAssistant) -> None:
    result = await _menu(hass, "planner")
    assert result["step_id"] == "planner"
    with SKIP_SETUP:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["data"] == {CONF_KIND: KIND_PLANNER}
    result = await _menu(hass, "planner")
    assert result["reason"] == "already_configured"


async def test_virtual_and_reconfigure(hass: HomeAssistant) -> None:
    result = await _menu(hass, "virtual")
    with SKIP_SETUP:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"name": "  ", CONF_COLS: 4.0, CONF_ROWS: 2.0}
        )
    assert result["title"] == "Virtual panel"
    assert result["data"][CONF_KIND] == KIND_VIRTUAL
    assert (result["data"][CONF_COLS], result["data"][CONF_ROWS]) == (4, 2)
    entry = hass.config_entries.async_get_entry(result["result"].entry_id)

    with SKIP_SETUP:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
        )
        assert result["step_id"] == "reconfigure"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_COLS: 3, CONF_ROWS: 3})
    assert result["reason"] == "reconfigure_successful"
    assert (entry.data[CONF_COLS], entry.data[CONF_ROWS]) == (3, 3)


async def test_reconfigure_only_for_virtual_panels(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data={"host": "10.0.0.1"})
    entry.add_to_hass(hass)
    result = await entry.start_reconfigure_flow(hass)
    assert result["reason"] == "not_reconfigurable"


async def test_bridge_manual_with_pairing(hass: HomeAssistant, fake_bridge: FakeBridge) -> None:
    result = await _menu(hass, "bridge")
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"host": "127.0.0.1", CONF_PORT: 1})
    assert result["errors"] == {"base": "cannot_connect_bridge"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "127.0.0.1", CONF_PORT: fake_bridge.port}
    )
    assert result["step_id"] == "pair"
    assert result["description_placeholders"]["name"] == "Test bridge"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "000000"})
    assert result["errors"] == {"base": "invalid_code"}
    with SKIP_SETUP:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": " 123456 "})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    data = result["data"]
    assert data[CONF_KIND] == KIND_BRIDGE and data[CONF_BRIDGE_ID] == BRIDGE_ID
    assert data[CONF_TOKEN] in fake_bridge.tokens

    result = await _menu(hass, "bridge")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "127.0.0.1", CONF_PORT: fake_bridge.port}
    )
    assert result["reason"] == "already_configured"


async def test_bridge_pairing_unreachable(hass: HomeAssistant, fake_bridge: FakeBridge) -> None:
    result = await _menu(hass, "bridge")
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"host": "127.0.0.1", CONF_PORT: fake_bridge.port}
    )
    await fake_bridge.stop()
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "123456"})
    assert result["errors"] == {"base": "cannot_connect_bridge"}


def _bridge_zeroconf(port: int, **properties: str) -> ZeroconfServiceInfo:
    return ZeroconfServiceInfo(
        ip_address=ip_address("127.0.0.1"),
        ip_addresses=[ip_address("127.0.0.1")],
        hostname="pc.local.",
        name="Test bridge._stream-assistant._tcp.local.",
        port=port,
        type="_stream-assistant._tcp.local.",
        properties={"id": BRIDGE_ID, "name": "Test bridge", "version": "0.8.0", **properties},
    )


async def test_bridge_zeroconf(hass: HomeAssistant, fake_bridge: FakeBridge) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_bridge_zeroconf(fake_bridge.port, id="")
    )
    assert result["reason"] == "cannot_connect_bridge"

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_bridge_zeroconf(fake_bridge.port)
    )
    assert result["step_id"] == "pair"
    with SKIP_SETUP:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "123456"})
    assert result["type"] is FlowResultType.CREATE_ENTRY

    # Known bridge at a new port: the entry follows it
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    with SKIP_SETUP:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_bridge_zeroconf(5999)
        )
        await hass.async_block_till_done()
    assert result["reason"] == "already_configured"
    assert entry.data[CONF_PORT] == 5999


async def test_bridge_reauth(hass: HomeAssistant, fake_bridge: FakeBridge) -> None:
    entry = bridge_entry(fake_bridge, token="revoked")
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "999999"})
    assert result["errors"] == {"base": "invalid_code"}
    with patch("custom_components.stream_assistant.config_flow.pair") as pair:
        pair.return_value = (BridgeInfo("someone-else", "Other", "0.8.0"), "t")
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "123456"})
    assert result["errors"] == {"base": "wrong_bridge"}
    with SKIP_SETUP:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"code": "123456"})
        # The entry reloads after reauth; let that finish while setup is still skipped
        await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_TOKEN] in fake_bridge.tokens


async def test_virtual_entries_do_not_clash(hass: HomeAssistant) -> None:
    virtual_entry().add_to_hass(hass)
    result = await _menu(hass, "virtual")
    with SKIP_SETUP:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"name": "Second", CONF_COLS: 2, CONF_ROWS: 2}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
