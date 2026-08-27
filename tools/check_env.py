"""Read .env and say what is wrong with it, without printing any secret.

Written after a pasted command block ended up inside .env instead of in the
shell. The file looked fine at a glance, the service still started, and the
mistake would only have surfaced as a confusing failure much later.

Runs on: any machine.

    .venv/bin/python tools/check_env.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Names whose values must never be printed, even partially, beyond a tail.
SECRET = ("SECRET", "KEY", "TOKEN", "PASSWORD", "PIN")

KNOWN = {
    "ENYGMA_PORT", "ENYGMA_HOST", "ENYGMA_RP_ID", "ENYGMA_RP_NAME", "ENYGMA_ORIGIN",
    "ENYGMA_SESSION_SECRET", "ENYGMA_INSECURE_COOKIES", "ENYGMA_REAUTH_MINUTES",
    "ENYGMA_PIPELINE", "ENYGMA_GEMINI_API_KEY", "ENYGMA_GEMINI_MODEL",
    "ENYGMA_MAX_UPLOAD_MB", "ENYGMA_WORKER_POLL_SECONDS",
    "ENYGMA_HINOTES_ENABLED", "ENYGMA_HINOTES_BASE", "ENYGMA_HINOTES_TOKEN",
    "ENYGMA_HINOTES_PAGE_SIZE", "ENYGMA_HINOTES_TIMEOUT",
}


def mask(name: str, value: str) -> str:
    if any(word in name.upper() for word in SECRET):
        if not value:
            return "(empty)"
        return f"set, {len(value)} chars, ends {value[-4:]}"
    return value or "(empty)"


def main() -> int:
    if not ENV.exists():
        print(f"No .env at {ENV}")
        return 1

    mode = oct(ENV.stat().st_mode)[-3:]
    print(f"{ENV}  mode {mode}\n")

    good: list[tuple[str, str]] = []
    stray: list[tuple[int, str]] = []
    dupes: list[str] = []
    seen: set[str] = set()

    for number, raw in enumerate(ENV.read_text().splitlines(), 1):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, sep, value = line.partition("=")
        if not sep or not IDENT.match(name.strip()):
            stray.append((number, line))
            continue
        name = name.strip()
        if value[:1] == value[-1:] and value[:1] in ("'", '"') and len(value) > 1:
            value = value[1:-1]
        if name in seen:
            dupes.append(name)
        seen.add(name)
        good.append((name, value))

    for name, value in good:
        flag = "" if name in KNOWN else "   <- not a setting ENYGMA reads"
        print(f"  {name:28} {mask(name, value)}{flag}")

    problems = 0

    if stray:
        problems += len(stray)
        print(f"\n{len(stray)} line(s) that are not KEY=VALUE. These are ignored at")
        print("startup, and if any of them is a command you meant to run, it never ran:")
        for number, line in stray:
            print(f"  line {number}: {line[:70]}")

    if dupes:
        problems += len(dupes)
        print(f"\nDefined more than once (the last one wins): {', '.join(sorted(set(dupes)))}")

    values = dict(good)
    if not values.get("ENYGMA_SESSION_SECRET"):
        problems += 1
        print("\nENYGMA_SESSION_SECRET is empty. Every session cookie fails without it.")

    pipeline = values.get("ENYGMA_PIPELINE", "stub")
    if pipeline == "gemini" and not values.get("ENYGMA_GEMINI_API_KEY"):
        problems += 1
        print("\nENYGMA_PIPELINE=gemini but ENYGMA_GEMINI_API_KEY is empty.")
        print("Every transcription will fail. Set the key or go back to stub.")
    elif pipeline != "gemini":
        print(f"\nPipeline is '{pipeline}'. Transcripts are placeholder text, not real ones.")

    if mode != "600":
        problems += 1
        print(f"\n.env is mode {mode}. It holds the session secret and the API key.")
        print("Fix with:  chmod 600 .env")

    print()
    if problems:
        print(f"{problems} problem(s) found.")
        return 1
    print("No problems found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
