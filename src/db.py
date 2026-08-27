"""SQLite access and the migration runner.

The runner applies every .sql file in migrations/ in filename order, once, inside a
transaction, and records it. Applying twice is a no-op. It verifies the artifact
rather than trusting the report: after running it re-reads schema_migrations.
"""
import sqlite3
from contextlib import contextmanager

from .config import DB_PATH, DATA_DIR, MIGRATIONS_DIR


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def cursor():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def _strip_comments(sql: str) -> str:
    """Remove -- comments, respecting single quoted strings.

    Splitting on ";" without doing this first is a trap: a semicolon inside a
    comment ends a statement early and the rest of the comment becomes SQL. It
    fails as a syntax error pointing at an English word, which reads like
    nonsense until you find the semicolon in the prose.
    """
    out = []
    for line in sql.splitlines():
        in_string = False
        cut = None
        i = 0
        while i < len(line):
            ch = line[i]
            if ch == "'":
                in_string = not in_string
            elif ch == "-" and not in_string and line[i:i + 2] == "--":
                cut = i
                break
            i += 1
        out.append(line if cut is None else line[:cut])
    return "\n".join(out)


def _statements(sql: str) -> list[str]:
    """Split a migration into statements, dropping empty fragments."""
    return [chunk.strip() for chunk in _strip_comments(sql).split(";") if chunk.strip()]


def migrate(verbose: bool = False) -> list[str]:
    applied: list[str] = []
    with cursor() as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " version TEXT PRIMARY KEY,"
            " applied_at TEXT NOT NULL DEFAULT (datetime('now')))"
        )
        done = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            # Deliberately not executescript(). In Python's sqlite3, executescript
            # issues an implicit COMMIT before it runs, which silently ends the
            # transaction opened above and turns the rollback path into
            # "cannot rollback - no transaction is active". Statement by statement
            # keeps the migration atomic, which is the whole point of opening one.
            statements = _statements(path.read_text())
            conn.execute("BEGIN")
            try:
                for statement in statements:
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO schema_migrations (version) VALUES (?)", (path.name,)
                )
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                raise
            applied.append(path.name)
            if verbose:
                print(f"applied {path.name}")

        # Verify the artifact, not the report.
        recorded = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
        expected = {p.name for p in MIGRATIONS_DIR.glob("*.sql")}
        missing = expected - recorded
        if missing:
            raise RuntimeError(f"migrations did not record: {sorted(missing)}")

        conn.execute(
            "INSERT OR IGNORE INTO operator (id, handle) VALUES (1, 'yahya')"
        )
    return applied


if __name__ == "__main__":
    print(migrate(verbose=True) or "nothing to apply")
