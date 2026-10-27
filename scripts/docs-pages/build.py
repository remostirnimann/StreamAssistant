"""Prepare the documentation test pages: the editor (index.html) and the card (card.html).

They run frontend/panel.js and frontend/card.js against a pretend Home Assistant
(fakehass.js), with key images drawn by the integration's renderer. Serve this folder and
capture it with a headless browser:

    .venv/Scripts/python.exe scripts/docs-pages/build.py
    .venv/Scripts/python.exe -m http.server 8765 --directory scripts/docs-pages
    msedge --headless=new --hide-scrollbars --window-size=1400,1000 --virtual-time-budget=6000 \
        --screenshot=editor-keys.png "http://localhost:8765/index.html?deck=mk2&select=0"

URL parameters: deck=mk2|plus|neo|studio|panel, select=<key>|d<dial>, view=info,
dialog=template|entity|icon, page=<page id>, lang=en|de.
"""

import base64
import importlib.util
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
COMPONENT = REPO / "custom_components" / "stream_assistant"

spec = importlib.util.spec_from_file_location("docs_demo", REPO / "scripts" / "docs_demo.py")
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)
render = demo.render


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def keys(count: int, size: int) -> list[str]:
    return [b64(render.render_preview(size, demo.KEYS[i % len(demo.KEYS)])) for i in range(count)]


images = {
    "mk2": {"keys": keys(15, 72), "dials": []},
    "plus": {"keys": keys(8, 120), "dials": [b64(render.render_segment(200, 100, v)) for v in demo.SEGMENTS]},
    "neo": {"keys": keys(8, 96), "dials": []},
    "studio": {"keys": keys(32, 112), "dials": []},
    "panel": {"keys": keys(12, 144), "dials": []},
}
(HERE / "images.js").write_text("window.SA_IMAGES = " + json.dumps(images) + ";\n", encoding="utf-8")
for name in ("panel.js", "card.js"):
    shutil.copy(COMPONENT / "frontend" / name, HERE / name)
for name in ("mdi.ttf", "mdi.json"):
    shutil.copy(COMPONENT / "assets" / name, HERE / name)
print("ok")
