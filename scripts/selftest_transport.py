"""Hardware-free self test: NetworkDockTransport against the simulated dock.

Usage: .venv\\Scripts\\python.exe scripts\\selftest_transport.py
Exit code 0 when everything passed.
"""

from __future__ import annotations

import asyncio
import io
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
_pkg = types.ModuleType("sa")
_pkg.__path__ = [str(ROOT / "custom_components" / "stream_assistant")]
sys.modules["sa"] = _pkg
sys.path.insert(0, str(ROOT / "scripts"))

from PIL import Image, ImageChops  # noqa: E402

from fake_dock import FakeDock  # noqa: E402
from sa.render import KeyVisual, render_key, render_preview  # noqa: E402
from sa.transport import AttachedDeck, NetworkDockTransport  # noqa: E402

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
    dock = FakeDock(port=0, child_port=0)
    await dock.start()

    transport = NetworkDockTransport("127.0.0.1")
    # The real dock always uses 5343; point the client at the fake's random port
    transport._client.port = dock.port  # noqa: SLF001
    hub_states: list[bool] = []
    decks: list[AttachedDeck] = []
    keys: list[tuple[int, bool]] = []
    transport.on_hub_state = hub_states.append
    transport.on_deck_connected = decks.append
    transport.on_key = lambda index, pressed: keys.append((index, pressed))
    transport.start()

    check(await wait_for(lambda: transport.deck_connected), "deck connects through the fake dock")
    check(hub_states[:1] == [True], "hub state reported as connected")
    deck = decks[0] if decks else None
    check(deck is not None and deck.serial == "FAKEDECK000001", "deck serial read from dock report 0x1c")
    check(deck is not None and deck.capabilities.model_id == "mk2", "MK.2 mapped to capability profile mk2")
    check(deck is not None and deck.firmware == "1.02.000", "deck firmware read")
    check(transport.hub_info().get("serial") == "FAKEDOCK000001", "dock serial in hub_info")

    transport.set_brightness(42)
    check(await wait_for(lambda: dock.brightness == 42), "brightness reaches the deck")

    caps = deck.capabilities
    visuals = [KeyVisual(f"Taste {i + 1}", "Test", "lightbulb", "#2f6fb0" if i % 2 else "#f2b134") for i in range(caps.key_count)]
    for index, visual in enumerate(visuals):
        transport.set_key_image(index, render_key(caps, visual))
    check(await wait_for(lambda: len(dock.images) == caps.key_count), f"all {caps.key_count} key images received")

    # What the deck got, turned back upright, must look like the editor preview
    with Image.open(io.BytesIO(dock.images[0])) as got, Image.open(io.BytesIO(render_preview(caps.key_size, visuals[0]))) as want:
        diff = ImageChops.difference(got.convert("RGB").rotate(180), want.convert("RGB"))
        worst = max(channel[1] for channel in diff.getextrema())
    check(worst < 60, f"image orientation matches the preview (max pixel diff {worst})")

    await dock.press(7)
    check(await wait_for(lambda: keys == [(7, True), (7, False)]), "key 8 press and release reported")

    await transport.stop(reset=True)
    check(await wait_for(lambda: dock.resets == 1), "stop resets the deck to the logo")
    await dock.stop()

    print("\nALL PASSED" if not failures else f"\n{len(failures)} FAILED")
    sys.exit(1 if failures else 0)


asyncio.run(main())
