"""Write the release identity that the app reports and displays.

Two files, both build artifacts, both out of version control:

    VERSION   <commit>.<utc build stamp>   URL safe; busts asset caches and
                                           answers "which build is live"
    MARK      Mk II.<commit>               what a human reads, top right

The commit number comes from git, so "Mk II.7" means "built from the seventh
commit". Pass --count to stamp from outside a checkout, which is what the
release packaging does.

    python3 tools/stamp_release.py
    python3 tools/stamp_release.py --count 7
"""
from __future__ import annotations

import argparse
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERIES = "II"


def commit_count() -> int | None:
    try:
        out = subprocess.run(
            ["git", "rev-list", "--count", "HEAD"],
            cwd=ROOT, capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    try:
        return int(out.stdout.strip())
    except ValueError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=None,
                    help="commit number to stamp, when git is not available")
    args = ap.parse_args()

    count = args.count if args.count is not None else commit_count()
    if count is None:
        # Not a checkout and nobody said. Keep whatever is already stamped rather
        # than lying about the number.
        existing = (ROOT / "MARK").read_text().strip() if (ROOT / "MARK").exists() else ""
        print(f"no git and no --count; left MARK as {existing or '(unset)'}")
        return 1

    built = datetime.now(timezone.utc).strftime("%Y.%m.%d.%H%M")
    (ROOT / "VERSION").write_text(f"{count}.{built}\n")
    (ROOT / "MARK").write_text(f"Mk {SERIES}.{count}\n")
    print(f"Mk {SERIES}.{count}   build {count}.{built}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
