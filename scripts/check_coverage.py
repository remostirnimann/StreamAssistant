"""Merge Cobertura coverage reports and fail below a minimum line coverage.

Several test projects cover the same assemblies (e.g. the bridge core), so a
line counts as covered when any report covers it.

    python scripts/check_coverage.py --min 90 --exclude /tests/ report1.xml report2.xml ...

Prints the coverage per file (lowest first) and the total.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


def merge(reports: list[Path], exclude: list[str]) -> dict[str, dict[int, bool]]:
    """filename -> line -> covered."""
    files: dict[str, dict[int, bool]] = defaultdict(dict)
    for report in reports:
        for cls in ET.parse(report).getroot().iter("class"):
            name = cls.get("filename", "").replace("\\", "/")
            if not name or any(part in name for part in exclude):
                continue
            lines = files[name]
            for line in cls.iter("line"):
                number = int(line.get("number", "0"))
                lines[number] = lines.get(number, False) or int(line.get("hits", "0")) > 0
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--min", type=float, default=90.0, help="minimum total line coverage in percent")
    parser.add_argument("--exclude", action="append", default=[], help="skip files whose path contains this")
    args = parser.parse_args()

    files = merge(args.reports, args.exclude)
    covered = sum(sum(lines.values()) for lines in files.values())
    total = sum(len(lines) for lines in files.values())
    rows = sorted(
        ((sum(lines.values()) / len(lines) * 100, name, len(lines)) for name, lines in files.items() if lines)
    )
    for percent, name, count in rows:
        print(f"{percent:6.1f} %  {count:5d} lines  {name}")
    result = covered / total * 100 if total else 0.0
    print(f"\nTotal: {result:.1f} % of {total} lines (minimum {args.min:.0f} %)")
    if result < args.min:
        sys.exit(1)


main()
