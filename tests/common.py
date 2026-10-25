"""Helpers shared by the tests: config entries for the simulated hardware."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from pathlib import Path
import sys
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stream_assistant.const import (
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
    KIND_VIRTUAL,
)

from .fake_bridge import BRIDGE_ID, BRIDGE_NAME, FakeBridge

# The simulated dock lives in scripts/ so it can also run on its own
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from fake_dock import DECK_SERIAL, DOCK_SERIAL, MK2_PID, FakeDock

DOCK_PORT = 5343

__all__ = [
    "DECK_SERIAL",
    "DOCK_PORT",
    "DOCK_SERIAL",
    "FakeDock",
    "SetupEntry",
    "bridge_entry",
    "dock_entry",
    "entity_id",
    "virtual_entry",
    "wait_for",
]

type SetupEntry = Callable[[MockConfigEntry], Coroutine[Any, Any, MockConfigEntry]]


async def wait_for(predicate: Callable[[], bool], timeout: float = 5) -> None:
    """Let the event loop run until predicate holds (connections run outside hass' task tracking)."""
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)


def entity_id(hass: HomeAssistant, domain: str, unique_id: str) -> str:
    """Entity id by unique id (names depend on translations)."""
    found = er.async_get(hass).async_get_entity_id(domain, DOMAIN, unique_id)
    assert found, f"no {domain} entity {unique_id}"
    return found


def dock_entry() -> MockConfigEntry:
    """Entry for the simulated dock."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Stream Deck MK.2 ({DOCK_SERIAL})",
        unique_id=DOCK_SERIAL,
        data={
            "host": "127.0.0.1",
            "mac": None,
            CONF_DOCK_SERIAL: DOCK_SERIAL,
            CONF_DECK_SERIAL: DECK_SERIAL,
            CONF_DECK_PRODUCT_ID: MK2_PID,
        },
    )


def virtual_entry(cols: int = 4, rows: int = 2, title: str = "Wall panel") -> MockConfigEntry:
    """Entry for a virtual panel."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=title,
        unique_id="virtual-test",
        data={CONF_KIND: KIND_VIRTUAL, CONF_DECK_SERIAL: "virtual-test", CONF_COLS: cols, CONF_ROWS: rows},
    )


def bridge_entry(
    bridge: FakeBridge, token: str = "known-token", devices: dict[str, Any] | None = None
) -> MockConfigEntry:
    """Entry for the fake bridge."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=BRIDGE_NAME,
        unique_id=BRIDGE_ID,
        data={
            CONF_KIND: KIND_BRIDGE,
            "host": "127.0.0.1",
            CONF_PORT: bridge.port,
            CONF_BRIDGE_ID: BRIDGE_ID,
            CONF_TOKEN: token,
            CONF_DEVICES: devices or {},
        },
    )
