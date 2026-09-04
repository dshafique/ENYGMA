"""Write the release identity that the app reports and displays.

Three things: two build artifacts, and the changelog entry that describes them.

Two files, both build artifacts, both out of version control:

    VERSION   <commit>.<utc build stamp>   URL safe; busts asset caches and
                                           answers "which build is live"
    MARK      Mk II.<commit>               what a human reads, top right

The commit number comes from git, so "Mk II.7" means "built from the seventh
commit". Pass --count to stamp from outside a checkout, which is what the
release packaging does.

It also fills in the mark on the newest changelog entry, if that entry is still
marked UNRELEASED. Writing that number by hand looked fine and was wrong: the
number is the commit count, so committing the entry changed the number the entry
claimed, and the changelog quietly described a build that did not exist. An
entry that already carries a mark is never renumbered, because a device that has
been shown a release must not be shown it again under a new name.

Run it AFTER committing, never before. The number is the commit count, so a
stamp taken before the commit names the release one short and the changelog then
describes a build nobody will ever run. The stamp dirties src/changelog.py by
design; that change rides along in the next commit.

    git commit ...
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
    mark = f"Mk {SERIES}.{count}"
    (ROOT / "VERSION").write_text(f"{count}.{built}\n")
    (ROOT / "MARK").write_text(f"{mark}\n")
    named = name_the_release(mark)
    print(f"{mark}   build {count}.{built}"
          + (f"   changelog entry named {mark}" if named else ""))
    return 0


def name_the_release(mark: str) -> bool:
    """Give the newest changelog entry its number, once.

    Returns whether anything was written, so a re-stamp of an already-named
    release is silent rather than pretending to have done something.
    """
    source = ROOT / "src" / "changelog.py"
    if not source.exists():
        return False
    text = source.read_text()
    # Only the first, and only if it is a placeholder. Everything already
    # numbered stays as it is.
    placeholder = '"mark": UNRELEASED,'
    if placeholder not in text:
        return False
    source.write_text(text.replace(placeholder, f'"mark": "{mark}",', 1))
    return True


if __name__ == "__main__":
    raise SystemExit(main())
