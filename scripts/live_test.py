"""Exercise the integration's protocol layer and renderer against a real dock, without Home Assistant.

Usage: .venv\\Scripts\\python.exe scripts\\live_test.py <dock-ip> [seconds]

Each key shows "Taste N"; pressing a key toggles it to "AN" (green) and back.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import sys
import time
import types

# Import the integration modules as a plain package, without running its
# __init__.py (which needs Home Assistant)
_PKG_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "stream_assistant"
_pkg = types.ModuleType("sa")
_pkg.__path__ = [str(_PKG_DIR)]
sys.modules["sa"] = _pkg

from sa.protocol import DeckInfo, DockClient, probe  # noqa: E402
from sa.render import KeyAppearance, render_key  # noqa: E402

COLOURS = ["#1f3a93", "#8e44ad", "#c0392b", "#d35400", "#16a085"]


async def main(host: str, seconds: float) -> None:
    dock, child = await probe(host)
    print(f"probe: dock serial={dock.serial} fw={dock.firmware} child={child}")
    # Give the dock a moment to accept the next connection
    await asyncio.sleep(0.5)

    client = DockClient(host)
    toggled: dict[int, bool] = {}
    connected = asyncio.Event()

    def appearance(key: int) -> KeyAppearance:
        if toggled.get(key):
            return KeyAppearance(text="AN", background_color="#27ae60")
        return KeyAppearance(text=f"Taste\n{key + 1}", background_color=COLOURS[key % len(COLOURS)])

    async def paint(key: int) -> None:
        assert client.deck
        jpeg = await asyncio.to_thread(render_key, client.deck.model, appearance(key))
        client.set_key_image(key, jpeg)

    def on_deck_connected(deck: DeckInfo) -> None:
        print(f"deck connected: {deck.model.name} serial={deck.child.serial} fw={deck.firmware}")
        connected.set()

    def on_key(key: int, pressed: bool) -> None:
        print(f"key {key + 1:2d} {'DOWN' if pressed else 'UP'}")
        if pressed:
            toggled[key] = not toggled.get(key)
            asyncio.get_running_loop().create_task(paint(key))

    client.on_dock_state = lambda up: print(f"dock {'up' if up else 'down'}")
    client.on_deck_connected = on_deck_connected
    client.on_deck_disconnected = lambda: print("deck disconnected")
    client.on_key = on_key
    client.start()

    await asyncio.wait_for(connected.wait(), 15)
    client.set_brightness(60)
    start = time.perf_counter()
    for key in range(client.deck.model.key_count):  # type: ignore[union-attr]
        await paint(key)
    print(f"rendered and sent {client.deck.model.key_count} keys in {(time.perf_counter() - start) * 1000:.0f} ms")  # type: ignore[union-attr]

    print(f"Press keys. Running for {seconds:.0f}s ...")
    await asyncio.sleep(seconds)
    await client.stop(reset=True)
    print("done")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(
        main(sys.argv[1] if len(sys.argv) > 1 else "172.16.254.112", float(sys.argv[2]) if len(sys.argv) > 2 else 10)
    )
