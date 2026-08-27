"""Fail the build when CSS references a custom property nobody defines.

An undefined custom property does not warn. The whole declaration becomes invalid
and the browser drops it, so a layout quietly collapses and nothing in the console
says why. This cost PHNTM three separate bugs: an unreachable light mode, a
transparent nav rail, and a two column grid that folded to one.

Runs on: any machine.

    python3 tools/check_tokens.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "src/static/css"
SCANNED = list(CSS.glob("*.css")) + list((ROOT / "src/templates").glob("*.html"))

DEFINE = re.compile(r"(--[a-z0-9-]+)\s*:")
USE = re.compile(r"var\(\s*(--[a-z0-9-]+)")


def defined() -> set[str]:
    return set(DEFINE.findall((CSS / "tokens.css").read_text()))


def main() -> int:
    known = defined()
    problems: list[str] = []
    for path in SCANNED:
        text = path.read_text()
        # A file may define its own locals; count those as known within it.
        local = known | set(DEFINE.findall(text))
        for line_no, line in enumerate(text.splitlines(), 1):
            for name in USE.findall(line):
                if name not in local:
                    problems.append(f"{path.relative_to(ROOT)}:{line_no}  {name}")
    if problems:
        print(f"{len(problems)} reference(s) to undefined custom properties:\n")
        for p in problems:
            print("  " + p)
        print("\nDefine them in tools/gen_tokens.py, never in a stylesheet.")
        return 1
    print(f"ok: {len(known)} tokens defined, every var() reference resolves")
    return 0


if __name__ == "__main__":
    sys.exit(main())
