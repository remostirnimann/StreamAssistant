"""Fill the add-on repository (remostirnimann/StreamAssistant-addon) for a release.

Copies `addon/` into the target folder, sets the add-on's version (the Supervisor builds
the image from the Dockerfile, which downloads the bridge of that release) and adds the
changelog the Supervisor shows with an update. The release workflow runs it; by hand:

    python scripts/addon_sync.py --version 0.10.0 --target ../StreamAssistant-addon

For a local test add-on on a Home Assistant host, add `--bridge <published bridge folder>`:
the bridge is then copied into the image instead of downloaded, and the version is
whatever `--version` says (e.g. `0.10.0-dev1`, it must change for every new build).
"""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "addon"
ADDON = "stream_assistant_bridge"


def sync(version: str, target: Path, bridge: Path | None = None) -> None:
    """Replace the add-on files in target (keeps .git and anything else at the top)."""
    target.mkdir(parents=True, exist_ok=True)
    for item in SOURCE.iterdir():
        dest = target / item.name
        if dest.is_dir():
            shutil.rmtree(dest)
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
    addon = target / ADDON
    config = addon / "config.yaml"
    text, count = re.subn(r'^version: ".*"$', f'version: "{version}"', config.read_text(encoding="utf-8"), flags=re.M)
    if count != 1:
        raise SystemExit("config.yaml has no version line")
    config.write_text(text, encoding="utf-8", newline="\n")
    shutil.copy2(ROOT / "CHANGELOG.md", addon / "CHANGELOG.md")
    if bridge is not None:
        shutil.copytree(bridge, addon / "rootfs" / "opt" / "bridge", dirs_exist_ok=True)


def main() -> None:
    """Command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--version", required=True, help="release version without v, e.g. 0.10.0")
    parser.add_argument("--target", required=True, type=Path, help="checkout of the add-on repository")
    parser.add_argument("--bridge", type=Path, help="published linux-musl bridge to build in (local tests)")
    args = parser.parse_args()
    sync(args.version.removeprefix("v"), args.target, args.bridge)
    print(f"{ADDON} {args.version} in {args.target}")


if __name__ == "__main__":
    main()
