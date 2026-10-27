"""Hardware-free self test: the integration's bridge client against the real .NET bridge.

Starts the bridge (built with `dotnet build bridge`) with a simulated 5x3 deck
on port 5391, pairs, sends images and brightness, and presses, unplugs and
replugs the deck through the simulator page's WebSocket.

Usage: .venv\\Scripts\\python.exe scripts\\selftest_bridge.py
Exit code 0 when everything passed.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import types

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
_pkg = types.ModuleType("sa")
_pkg.__path__ = [str(ROOT / "custom_components" / "stream_assistant")]
sys.modules["sa"] = _pkg

from sa.protocol.bridge import BridgeClient, BridgeDevice, BridgeError, fetch_info, pair  # noqa: E402

PORT = 5391
BRIDGE_DLL = ROOT / "bridge/src/StreamAssistant.Bridge/bin/Debug/net10.0/stream-assistant-bridge.dll"
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/"
    "wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q=="
)

failures: list[str] = []


def check(condition: bool, message: str) -> None:
    print(("PASS " if condition else "FAIL ") + message)
    if not condition:
        failures.append(message)


async def wait_for(predicate, timeout: float = 5.0) -> bool:
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return predicate()


async def main() -> None:
    if not BRIDGE_DLL.exists():
        sys.exit(f"Build the bridge first: dotnet build bridge ({BRIDGE_DLL} missing)")
    config = tempfile.mkdtemp(prefix="sab-selftest-")
    process = subprocess.Popen(
        [
            "dotnet",
            str(BRIDGE_DLL),
            "--port",
            str(PORT),
            "--simulate",
            "5x3",
            "--mdns",
            "false",
            "--config-dir",
            config,
            "--name",
            "Selftest",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        async with aiohttp.ClientSession() as session:
            await run(session)
    finally:
        process.terminate()
        process.wait(10)
    print("\nALL PASSED" if not failures else f"\n{len(failures)} FAILED")
    sys.exit(1 if failures else 0)


async def run(session: aiohttp.ClientSession) -> None:
    info = None
    for _ in range(100):
        try:
            info = await fetch_info(session, "127.0.0.1", PORT)
            break
        except BridgeError:
            await asyncio.sleep(0.2)
    check(info is not None and info.name == "Selftest", "status page gives bridge id and name")
    assert info

    async with session.get(f"http://127.0.0.1:{PORT}/api/status") as response:
        code = (await response.json())["pairing_code"]
    try:
        await pair(session, "127.0.0.1", PORT, "111111" if code == "000000" else "000000", "test")
        wrong = False
    except BridgeError as err:
        wrong = err.code == "invalid_code"
    check(wrong, "wrong pairing code is refused")

    paired, token = await pair(session, "127.0.0.1", PORT, code, "test")
    check(paired.id == info.id and len(token) > 30, "pairing with the shown code gives a token")

    client = BridgeClient(session, "127.0.0.1", PORT, token, "test")
    states: list[bool] = []
    devices: list[list[BridgeDevice]] = []
    keys: list[tuple[str, int, bool]] = []
    removed: list[str] = []
    added: list[BridgeDevice] = []
    client.on_state = states.append
    client.on_devices = devices.append
    client.on_key = lambda device, key, pressed: keys.append((device, key, pressed))
    client.on_device_removed = removed.append
    client.on_device_added = added.append
    client.start()

    check(await wait_for(lambda: bool(devices)), "connects and receives the device list")
    deck = devices[0][0] if devices and devices[0] else None
    check(
        deck is not None and (deck.id, deck.cols, deck.rows, deck.key_size) == ("sim-1", 5, 3, 72),
        "simulated 5x3 deck with 72 px keys",
    )
    check(
        deck is not None and "jpeg" in deck.formats and deck.brightness and deck.virtual,
        "capabilities: jpeg, brightness, virtual",
    )
    check(states[:1] == [True], "connection state reported")

    async with session.ws_connect(f"ws://127.0.0.1:{PORT}/sim/ws") as sim:
        state = json.loads((await sim.receive()).data)
        check(state["type"] == "state", "simulator page connects")

        client.send({"type": "set_brightness", "device": "sim-1", "percent": 33})
        client.send_image("sim-1", 4, JPEG)
        seen: dict[str, object] = {}

        async def watch() -> None:
            async for message in sim:
                data = json.loads(message.data)
                if data["type"] == "device":
                    seen["brightness"] = data["brightness"]
                elif data["type"] == "key":
                    seen[f"key{data['key']}"] = data["content"]

        watcher = asyncio.create_task(watch())
        check(await wait_for(lambda: seen.get("brightness") == 33), "brightness reaches the simulated deck")
        image = seen.get("key4")
        check(
            isinstance(image, dict) and image["image"] == "data:image/jpeg;base64," + base64.b64encode(JPEG).decode(),
            "key image reaches the simulated deck unchanged",
        )

        await sim.send_json({"type": "press", "device": "sim-1", "key": 9, "pressed": True})
        await sim.send_json({"type": "press", "device": "sim-1", "key": 9, "pressed": False})
        check(
            await wait_for(lambda: keys == [("sim-1", 9, True), ("sim-1", 9, False)]), "key press and release reported"
        )

        await sim.send_json({"type": "plug", "device": "sim-1", "plugged": False})
        check(await wait_for(lambda: removed == ["sim-1"]), "unplug reported as device_removed")
        await sim.send_json({"type": "plug", "device": "sim-1", "plugged": True})
        check(
            await wait_for(lambda: [d.id for d in added] == ["sim-1"]),
            "replug reported as device_added with the same id",
        )
        watcher.cancel()

    # A second client with the same token takes over; the first one backs off
    second = BridgeClient(session, "127.0.0.1", PORT, token, "test")
    second_devices: list[list[BridgeDevice]] = []
    second.on_devices = second_devices.append
    second.start()
    check(await wait_for(lambda: bool(second_devices)), "second client connects")
    check(await wait_for(lambda: not client.connected), "first client is replaced")
    await second.stop()
    await client.stop()

    refused: list[bool] = []
    stranger = BridgeClient(session, "127.0.0.1", PORT, "not-a-token", "test")
    stranger.on_unauthorized = lambda: refused.append(True)
    stranger.start()
    check(await wait_for(lambda: refused == [True]), "unknown token triggers re-pairing")
    await stranger.stop()


asyncio.run(main())
