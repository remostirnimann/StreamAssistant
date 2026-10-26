"""Paint a demo layout on every deck of a running bridge, for documentation screenshots.

Pairs with the bridge (the code comes from its local status page), then draws keys, touch
strip segments, the Neo's screen and page buttons and the Studio's LED rings with the
integration's own renderer, as Home Assistant would. Needs Pillow and aiohttp (the
Windows venv has both).

    .venv/Scripts/python.exe scripts/docs_demo.py [--port 5390]

Start the bridge first, for example with simulated decks of every kind:

    dotnet run --project bridge/src/StreamAssistant.Bridge -- --simulate mk2,plus,neo,studio,pedal --usb false
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
from pathlib import Path
import sys
import types

import aiohttp

COMPONENT = Path(__file__).resolve().parent.parent / "custom_components" / "stream_assistant"


def _load(name: str, path: Path) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(f"sa.{name}", path)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"sa.{name}"] = module
    spec.loader.exec_module(module)
    return module


# The integration's modules without Home Assistant: a stand-in package for the relative imports
_package = types.ModuleType("sa")
_package.__path__ = [str(COMPONENT)]
sys.modules["sa"] = _package
_load("capabilities", COMPONENT / "capabilities.py")
render = _load("render", COMPONENT / "render.py")
bridge = _load("protocol_bridge", COMPONENT / "protocol" / "bridge.py")
V = render.KeyVisual

YELLOW, BLUE, GREEN, RED, GREY, DARK, PURPLE = (
    "#f2b134",
    "#2f6fb0",
    "#1e6b4a",
    "#a8432f",
    "#3a3a3a",
    "#2b2b2b",
    "#6b4aa8",
)

# What a typical home deck shows; repeated to fill bigger grids
KEYS = [
    V(title="Living room", subtitle="On · 65 %", icon="lightbulb-on", background=YELLOW),
    V(title="Kitchen", subtitle="Off", icon="lightbulb-outline", background=DARK),
    V(title="Blinds", subtitle="Open · 40 %", icon="window-shutter-open", background=BLUE),
    V(title="Movie", icon="movie-open", background=PURPLE),
    V(title="Music", subtitle="Playing", icon="play", background=GREEN),
    V(title="Heating", subtitle="21.5 °C", icon="thermostat", background=RED),
    V(title="Front door", subtitle="Locked", icon="lock", background=DARK),
    V(title="Garage", subtitle="Closed", icon="garage", background=DARK),
    V(title="Fan", subtitle="On · 50 %", icon="fan", background=BLUE),
    V(title="Lights", icon="folder-outline", background=GREY),
    V(title="Coffee", subtitle="Off", icon="coffee", background=DARK),
    V(title="Washer", subtitle="Done", icon="washing-machine", background=GREEN),
    V(title="Outside", subtitle="14.2 °C", icon="thermometer", background=GREY),
    V(title="Good night", icon="weather-night", background=PURPLE),
    V(title="Alarm", subtitle="Armed", icon="shield-home", background=RED),
]
SEGMENTS = [
    V(title="Living room", subtitle="On · 65 %", icon="lightbulb-on", background=YELLOW, level=0.65),
    V(title="Radio", subtitle="Playing", icon="speaker", background=BLUE, level=0.3),
    V(title="Blinds", subtitle="Open · 40 %", icon="window-shutter-open", background=DARK, level=0.4),
    V(title="Heating", subtitle="21.5 °C", icon="thermostat", background=RED, level=0.55),
]
# Studio rings: colour and level per dial
RINGS = [("#f2b134", 0.65), ("#2f6fb0", 0.3)]


async def paint(client: bridge.BridgeClient, device: bridge.BridgeDevice) -> None:
    name = device.id
    if device.key_size:
        for index in range(device.cols * device.rows):
            visual = KEYS[index % len(KEYS)]
            client.send_image(name, index, render.render_preview(device.key_size, visual))
    if device.dials and device.touch_width:
        width = device.touch_width // device.dials
        for index in range(device.dials):
            image = render.render_segment(width, device.touch_height, SEGMENTS[index % len(SEGMENTS)])
            client.send_touch_image(name, index * width, 0, width, device.touch_height, image)
    if device.dial_ring:
        for index in range(device.dials):
            color, level = RINGS[index % len(RINGS)]
            client.send({"type": "set_dial_leds", "device": name, "dial": index, "color": color, "level": level})
    if device.screen_width:
        screen = V(title="Home", subtitle="1 / 3", background="#000000", foreground="#ffffff")
        client.send_screen_image(name, render.render_segment(device.screen_width, device.screen_height, screen))
    for index in range(device.buttons):
        # On the first of three pages: only "next" leads somewhere
        client.send(
            {"type": "set_button_color", "device": name, "button": index, "color": "#ffffff" if index else "#000000"}
        )
    if device.brightness:
        client.send({"type": "set_brightness", "device": name, "percent": 100})


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5390)
    args = parser.parse_args()
    async with aiohttp.ClientSession() as session:
        async with session.get(f"http://{args.host}:{args.port}/api/status") as response:
            code = (await response.json(content_type=None))["pairing_code"]
        _, token = await bridge.pair(session, args.host, args.port, code, "docs-demo")
        client = bridge.BridgeClient(session, args.host, args.port, token, "docs-demo")
        devices: asyncio.Future[list[bridge.BridgeDevice]] = asyncio.get_running_loop().create_future()
        client.on_devices = lambda found: devices.done() or devices.set_result(found)
        client.start()
        for device in await asyncio.wait_for(devices, 10):
            await paint(client, device)
            print(f"painted {device.id} ({device.model})")
        # Let the queue drain; staying connected keeps the bridge from resetting the decks
        await asyncio.sleep(2)
        print("Done. Keep this running while taking screenshots; Ctrl+C ends it.")
        await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
