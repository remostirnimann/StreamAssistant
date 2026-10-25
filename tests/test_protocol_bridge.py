"""Bridge protocol client against the fake bridge."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Callable
import struct

import aiohttp
import pytest

from custom_components.stream_assistant.protocol.bridge import (
    BridgeClient,
    BridgeDevice,
    BridgeError,
    envelope,
    fetch_info,
    pair,
)

from .fake_bridge import BRIDGE_ID, FakeBridge, deck


@pytest.fixture
async def session() -> AsyncGenerator[aiohttp.ClientSession]:
    async with aiohttp.ClientSession() as session:
        yield session


async def wait_for(predicate: Callable[[], bool], timeout: float = 5) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.02)


def test_envelope_and_device_round_trip() -> None:
    frame = envelope({"type": "set_key_image", "key": 1}, b"IMG")
    (length,) = struct.unpack(">H", frame[:2])
    assert frame[2 + length :] == b"IMG"
    device = BridgeDevice.from_json(deck("a", 4, 2, 96))
    assert (device.cols, device.rows, device.key_size, device.formats) == (4, 2, 96, ("jpeg", "png"))
    assert BridgeDevice.from_json(device.to_json()) == device
    bare = BridgeDevice.from_json({"id": "x"})
    assert (bare.name, bare.cols, bare.key_size, bare.brightness) == ("x", 0, 0, False)


async def test_fetch_info_and_pair(session: aiohttp.ClientSession, fake_bridge: FakeBridge) -> None:
    info = await fetch_info(session, "127.0.0.1", fake_bridge.port)
    assert info.id == BRIDGE_ID
    with pytest.raises(BridgeError) as err:
        await pair(session, "127.0.0.1", fake_bridge.port, "000000", "test")
    assert err.value.code == "invalid_code"
    info, token = await pair(session, "127.0.0.1", fake_bridge.port, "123456", "test")
    assert info.id == BRIDGE_ID and token in fake_bridge.tokens


async def test_unreachable(session: aiohttp.ClientSession) -> None:
    with pytest.raises(BridgeError) as err:
        await fetch_info(session, "127.0.0.1", 1)
    assert err.value.code == "cannot_connect"
    with pytest.raises(BridgeError):
        await pair(session, "127.0.0.1", 1, "123456", "test")


async def test_client_session(session: aiohttp.ClientSession, fake_bridge: FakeBridge) -> None:
    client = BridgeClient(session, "127.0.0.1", fake_bridge.port, "known-token", "test")
    states: list[bool] = []
    inventories: list[list[BridgeDevice]] = []
    added: list[str] = []
    removed: list[str] = []
    keys: list[tuple[str, int, bool]] = []
    client.on_state = states.append
    client.on_devices = inventories.append
    client.on_device_added = lambda d: added.append(d.id)
    client.on_device_removed = removed.append
    client.on_key = lambda device, key, pressed: keys.append((device, key, pressed))

    client.send({"type": "ignored while offline"})
    client.start()
    client.start()  # idempotent
    await wait_for(lambda: bool(inventories))
    assert client.connected and states == [True]
    assert client.info is not None and client.info.name == "Test bridge"
    assert [d.id for d in inventories[0]] == ["sim-1"]

    client.send({"type": "set_brightness", "device": "sim-1", "percent": 40})
    client.send_image("sim-1", 3, b"JPEG")
    await wait_for(lambda: ("sim-1", 3) in fake_bridge.images and fake_bridge.commands)
    assert fake_bridge.commands[0]["percent"] == 40

    await fake_bridge.press("sim-1", 3, True)
    await fake_bridge.plug(deck("sim-2"))
    await fake_bridge.unplug("sim-2")
    await fake_bridge.send_all({"type": "key", "device": "sim-1"})  # malformed: ignored
    await fake_bridge.send_all({"type": "error", "code": "unknown_device"})
    await wait_for(lambda: removed == ["sim-2"])
    assert keys == [("sim-1", 3, True)] and added == ["sim-2"]

    # Bridge restart: reconnect and a fresh device list
    await fake_bridge.drop()
    await wait_for(lambda: len(inventories) == 2)
    assert states == [True, False, True]

    # Another client takes over: back off, then come back
    await fake_bridge.replace()
    await wait_for(lambda: len(inventories) == 3)

    await client.stop()
    assert not client.connected


async def test_client_unauthorized(session: aiohttp.ClientSession, fake_bridge: FakeBridge) -> None:
    client = BridgeClient(session, "127.0.0.1", fake_bridge.port, "wrong", "test")
    refused: list[bool] = []
    client.on_unauthorized = lambda: refused.append(True)
    client.start()
    await wait_for(lambda: refused == [True])
    await client.stop()


async def test_client_retries_other_errors(session: aiohttp.ClientSession, fake_bridge: FakeBridge) -> None:
    fake_bridge.refuse_with = "busy"
    client = BridgeClient(session, "127.0.0.1", fake_bridge.port, "known-token", "test")
    client.start()
    await wait_for(lambda: client.connected)
    assert fake_bridge.hellos == 2
    await client.stop()
