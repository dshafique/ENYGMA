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

# Read out of src/config.py rather than written down here.
#
# This was a hand-kept list and it went stale the first time a setting was
# added: a real, working ENYGMA_ANTHROPIC_API_KEY was reported as "not a
# setting ENYGMA reads", in the middle of the output an operator is told to
# trust. A checker that is confidently wrong about a key is worse than no
# checker, because the next true warning it prints gets ignored too.
def known_settings() -> set[str]:
    source = ROOT / "src" / "config.py"
    if not source.exists():
        return set()
    return set(re.findall(r'"(ENYGMA_[A-Z0-9_]+)"', source.read_text()))


KNOWN = known_settings()


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

    import shutil as _sh
    if _sh.which("ffmpeg") and _sh.which("ffprobe"):
        print("\nffmpeg is present. Recordings longer than the diarization limit")
        print("will be transcribed in windows so speakers survive to the end.")
    else:
        problems += 1
        print("\nffmpeg is NOT installed. Speaker attribution silently collapses to")
        print("one voice after about 30 minutes and long recordings cannot be split.")
        print("Fix with:  sudo apt install ffmpeg")

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
