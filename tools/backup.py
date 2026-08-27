"""Back up the database, and prove the backup can be read.

What is worth protecting is the derived work: transcripts, summaries, actions,
the people, the chat history, and the enrolled passkeys. All of it is in one
SQLite file that exists in exactly one place.

The audio is deliberately NOT backed up. It is large, it is re-uploadable from
wherever it came from, and copying 500 MB files nightly onto the same disk buys
very little. Losing audio costs a re-upload; losing the database costs everything
that was ever understood about it.

This copies with SQLite's own backup API rather than `cp`, because the database
runs in WAL mode and a file copy taken mid-write is a torn database that looks
fine until the day you need it.

    python3 tools/backup.py                 # take one, prune old ones
    python3 tools/backup.py --verify        # restore the newest and check it
    python3 tools/backup.py --keep 30
"""
from __future__ import annotations

import argparse
import gzip
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import DB_PATH, BASE_DIR  # noqa: E402

BACKUPS = BASE_DIR / "backups"

# Tables whose emptiness would mean the backup is not worth having.
EXPECTED = ("recordings", "transcript_segments", "summaries", "action_items",
            "speakers", "credentials", "chat_threads", "terms")


def take(keep: int) -> Path:
    BACKUPS.mkdir(mode=0o700, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    target = BACKUPS / f"enygma-{stamp}.db.gz"

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
        raw = Path(handle.name)
    try:
        source = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        destination = sqlite3.connect(raw)
        with destination:
            source.backup(destination)          # consistent even mid-write
        destination.close()
        source.close()
        with open(raw, "rb") as src, gzip.open(target, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst)
    finally:
        raw.unlink(missing_ok=True)

    target.chmod(0o600)
    print(f"wrote {target.name}  ({target.stat().st_size / 1024:.0f} KB)")

    existing = sorted(BACKUPS.glob("enygma-*.db.gz"))
    for old in existing[:-keep] if keep > 0 else []:
        old.unlink()
        print(f"pruned {old.name}")
    print(f"{len(sorted(BACKUPS.glob('enygma-*.db.gz')))} backup(s) kept in {BACKUPS}")
    return target


def verify(path: Path | None = None) -> int:
    """A backup nobody has restored is a hope, not a backup."""
    candidates = sorted(BACKUPS.glob("enygma-*.db.gz"))
    chosen = path or (candidates[-1] if candidates else None)
    if chosen is None:
        print("No backups to verify.")
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        restored = Path(tmp) / "restored.db"
        with gzip.open(chosen, "rb") as src, open(restored, "wb") as dst:
            shutil.copyfileobj(src, dst)

        conn = sqlite3.connect(restored)
        conn.row_factory = sqlite3.Row
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        print(f"restored {chosen.name}")
        print(f"  integrity_check: {integrity}")
        if integrity != "ok":
            conn.close()
            return 1

        present = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        missing = [t for t in EXPECTED if t not in present]
        if missing:
            print(f"  MISSING TABLES: {', '.join(missing)}")
            conn.close()
            return 1
        for table in EXPECTED:
            count = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            print(f"  {table:22} {count}")
        conn.close()
    print("  the backup opens, passes integrity check and has every table.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--verify", action="store_true",
                    help="restore the newest backup to a temp file and check it")
    ap.add_argument("--keep", type=int, default=14, help="how many to keep (default 14)")
    args = ap.parse_args()

    if args.verify:
        return verify()
    if not Path(DB_PATH).exists():
        print(f"No database at {DB_PATH}")
        return 1
    take(args.keep)
    return verify()          # every backup is verified the moment it is taken


if __name__ == "__main__":
    raise SystemExit(main())
