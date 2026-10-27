"""Fixtures: Home Assistant with the integration, a simulated dock and a fake bridge."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.stream_assistant.protocol import bridge as bridge_protocol, dock as dock_protocol

from .common import DOCK_PORT, FakeDock, SetupEntry
from .fake_bridge import FakeBridge


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Load the integration from custom_components/."""


@pytest.fixture(autouse=True)
def allow_local_sockets(socket_enabled: None) -> None:
    """The simulated dock and the fake bridge are real servers on 127.0.0.1 (other hosts stay blocked)."""


@pytest.fixture(autouse=True)
def fast_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reconnect within milliseconds instead of seconds."""
    monkeypatch.setattr(dock_protocol, "RECONNECT_INTERVAL", 0.05)
    monkeypatch.setattr(bridge_protocol, "BACKOFF_MIN", 0.05)
    monkeypatch.setattr(bridge_protocol, "BACKOFF_MAX", 0.1)
    monkeypatch.setattr(bridge_protocol, "REPLACED_BACKOFF", 0.2)


@pytest.fixture
async def fake_dock() -> AsyncGenerator[FakeDock]:
    """A simulated Network Dock with an MK.2 on the dock's real port."""
    dock = FakeDock("127.0.0.1", DOCK_PORT, 0)
    await dock.start()
    yield dock
    await dock.stop()


@pytest.fixture
async def fake_bridge() -> AsyncGenerator[FakeBridge]:
    """A fake Stream Assistant Bridge with one 5x3 deck."""
    bridge = FakeBridge()
    await bridge.start()
    yield bridge
    await bridge.stop()


@pytest.fixture
async def setup_entry(hass: HomeAssistant) -> AsyncGenerator[SetupEntry]:
    """Add and set up entries; they are unloaded again after the test."""
    entries: list[MockConfigEntry] = []

    async def _setup(entry: MockConfigEntry) -> MockConfigEntry:
        entry.add_to_hass(hass)
        entries.append(entry)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        return entry

    yield _setup
    for entry in entries:
        if hass.config_entries.async_get_entry(entry.entry_id) and entry.state.recoverable:
            await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
