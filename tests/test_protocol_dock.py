"""Network Dock client (Cora over TCP) against the simulated dock."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

import pytest

from custom_components.stream_assistant.protocol import CoraError, DockClient, find_model_by_id, probe
from custom_components.stream_assistant.protocol.cora import CoraConnection
from custom_components.stream_assistant.protocol.dock import parse_child_info
from custom_components.stream_assistant.protocol.models import brightness_report, find_model

from .common import DECK_SERIAL, DOCK_PORT, DOCK_SERIAL, FakeDock


async def wait_for(predicate: Callable[[], bool], timeout: float = 5) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)


async def test_probe(fake_dock: FakeDock) -> None:
    dock, child = await probe("127.0.0.1", DOCK_PORT)
    assert dock.serial == DOCK_SERIAL
    assert dock.firmware == "1.01.013"
    assert child is not None and child.serial == DECK_SERIAL and child.tcp_port == fake_dock.child_port
    fake_dock.deck_attached = False
    _, child = await probe("127.0.0.1", DOCK_PORT)
    assert child is None


async def test_probe_fails_without_dock() -> None:
    with pytest.raises(CoraError, match="cannot connect"):
        await probe("127.0.0.1", 1)


async def test_client_session(fake_dock: FakeDock) -> None:
    client = DockClient("127.0.0.1", DOCK_PORT)
    states: list[bool] = []
    keys: list[tuple[int, bool]] = []
    disconnects: list[bool] = []
    client.on_dock_state = states.append
    client.on_key = lambda index, pressed: keys.append((index, pressed))
    client.on_deck_disconnected = lambda: disconnects.append(True)
    with pytest.raises(CoraError):
        client.set_brightness(10)
    client.start()
    await wait_for(lambda: client.deck_connected)
    assert client.dock_connected and states == [True]
    assert client.deck is not None and client.deck.firmware == "1.02.000"
    assert client.deck.model.model_id == "mk2"

    client.set_brightness(33)
    client.set_key_image(2, b"\xff\xd8" + bytes(1500) + b"\xff\xd9")
    with pytest.raises(ValueError, match="out of range"):
        client.set_key_image(15, b"x")
    await wait_for(lambda: fake_dock.brightness == 33 and 2 in fake_dock.images)
    assert len(fake_dock.images[2]) == 1504

    await fake_dock.press(4, 0.01)
    await wait_for(lambda: len(keys) == 2)
    assert keys == [(4, True), (4, False)]

    # Unplugging the deck ends the session; the client reconnects to the dock without it
    fake_dock.set_attached(False)
    await wait_for(lambda: disconnects == [True] and client.dock_connected)
    assert not client.deck_connected
    fake_dock.set_attached(True)
    await wait_for(lambda: client.deck_connected)

    await client.stop(reset=True)
    await wait_for(lambda: fake_dock.resets == 1)
    assert not client.dock_connected
    assert states[-1] is False


async def test_client_ignores_unsupported_deck(fake_dock: FakeDock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fake_dock.MK2_PID", 0x1234)
    client = DockClient("127.0.0.1", DOCK_PORT)
    client.start()
    await wait_for(lambda: client.dock_connected)
    await asyncio.sleep(0.1)
    assert not client.deck_connected
    await client.stop(reset=False)


async def test_connection_drops_without_keepalives(fake_dock: FakeDock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("custom_components.stream_assistant.protocol.cora.IDLE_TIMEOUT", 0.3)
    monkeypatch.setattr("fake_dock.KEEPALIVE_INTERVAL", 30)
    connection = CoraConnection("dock", "127.0.0.1", DOCK_PORT)
    closed: list[bool] = []
    connection.on_closed = lambda: closed.append(True)
    await connection.connect()
    await wait_for(lambda: closed == [True])
    assert not connection.connected
    await connection.close()


def test_models_and_reports() -> None:
    mk2 = find_model_by_id("mk2")
    assert mk2 is not None and find_model(0x0080) is mk2
    assert find_model(0x9999) is None
    reports = mk2.build_image_reports(1, bytes(2000))
    assert len(reports) == 2
    assert reports[0][3] == 0 and reports[1][3] == 1
    assert mk2.build_image_reports(0, b"")[0][3] == 1
    assert brightness_report(150)[2] == 100
    assert parse_child_info(b"\x00" * 10) is None
