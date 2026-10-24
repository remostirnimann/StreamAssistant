"""Release metadata from manifest.json, const.py and CHANGELOG.md.

Used by the CI and release workflows, works locally too:

    python scripts/release_info.py          # key=value lines (for $GITHUB_OUTPUT)
    python scripts/release_info.py --notes  # the changelog section of this version

Fails (exit 1) when manifest.json and const.py disagree, or when CHANGELOG.md
has no dated section for the version. One version covers the integration and
the bridge.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "stream_assistant"


def fail(message: str) -> None:
    # In GitHub Actions the message shows up as an annotation on the run
    print(f"::error::{message}" if "GITHUB_ACTIONS" in os.environ else message, file=sys.stderr)
    sys.exit(1)


def version() -> str:
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))["version"]
    match = re.search(r'^VERSION = "([^"]+)"', (INTEGRATION / "const.py").read_text(encoding="utf-8"), re.M)
    if not match or match[1] != manifest:
        fail(f"manifest.json ({manifest}) and const.py ({match[1] if match else '?'}) have different versions")
    if not re.fullmatch(r"\d+\.\d+\.\d+((a|b|rc)\d+)?", manifest):
        fail(f"Version {manifest} must look like 1.2.3 or 1.2.3b1")
    return manifest


def notes(release: str) -> str:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(rf"^## \[{re.escape(release)}\] - \d{{4}}-\d{{2}}-\d{{2}}\n(.*?)(?=^## \[|\Z)", changelog, re.M | re.S)
    if not match:
        fail(f"CHANGELOG.md has no section '## [{release}] - YYYY-MM-DD'; move the [Unreleased] entries there")
    return match[1].strip() + "\n"


def main() -> None:
    release = version()
    body = notes(release)
    if "--notes" in sys.argv:
        print(body, end="")
        return
    print(f"version={release}")
    print(f"tag=v{release}")
    # .NET assembly versions are numeric only; the full version goes into the informational version
    print(f"numeric={re.match(r'[0-9.]+', release)[0]}")
    print(f"prerelease={'true' if re.search(r'(a|b|rc)\d+$', release) else 'false'}")


main()
