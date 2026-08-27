# ENYGMA

Private meeting intelligence. Audio in, an attributed transcript and a checkable
summary out, running on one machine that its operator owns.

Built for one person. Not multi-tenant, and deliberately not built to become
multi-tenant later.

## What it does

Drop an audio file on **Meetings**. It is stored content-addressed, so the same
file twice is one meeting. A background worker transcribes it, attributes each
segment to a speaker, and writes a summary where every decision, open question
and action carries the timestamp it came from — a claim you cannot point at is a
claim the operator cannot check.

Five destinations:

| | |
|---|---|
| **Home** | What to look at now. Everything on it is a door into another tab. |
| **Meetings** | The list and the reader. Summary, transcript, actions, audio. |
| **Chat** | Ask ENYGMA. Threads can start from a term held down in a transcript. |
| **Actions** | Every action across every meeting, each linking back to where it was said. |
| **Directory** | Everyone who has spoken, and the meetings they appeared in. |

Hold a word anywhere in a transcript and a popover gives its definition;
*Learn more* opens a Chat thread with the question already asked.

## Design principles

**No password exists in this product.** Authentication is WebAuthn with
discoverable credentials. A PIN and recovery codes exist as a fallback, hashed
with Argon2id, behind one shared lockout counter.

**Isolation is filesystem permissions, not discipline.** It runs as its own unix
user with its own database, its own session secret and its own API key. No other
account on the machine can read the audio, the database or the secret.

**Migrations are forever-additive.** Never drop, never rename. To remove a
column, stop writing to it.

**Empty beats invented.** Where there is no real answer — no news feed connected,
nothing yet learned about the operator, no model reachable — the app says so
plainly rather than filling the space.

**.env is data, not code.** It is parsed, never sourced. A stray line in a file
humans paste into should not become a command that runs as the app.

## Running it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env          # then fill in ENYGMA_SESSION_SECRET
.venv/bin/python tools/stamp_release.py
./run.sh
```

`ENYGMA_PIPELINE=stub` is the default: the whole app runs with no API key and no
network, which is how the interface gets built before the bill starts. Set it to
`gemini` with a key for real transcripts.

Deployment to a single Linux host, including the unix user, the systemd unit with
a memory ceiling, and an isolation proof:

```bash
sudo bash deploy/install-on-spark.sh
```

## Checks

```bash
.venv/bin/python -m pytest tests -q         # the suite
.venv/bin/python tools/check_tokens.py      # no undefined CSS custom properties
.venv/bin/python tools/check_env.py         # .env sanity, secrets masked
.venv/bin/python tools/seed_demo.py         # a demo week; --clear removes it
```

`check_tokens.py` exists because an undefined custom property does not warn: the
whole declaration is dropped and a layout quietly collapses. It has caught that
class of bug more than once.

## Versioning

`tools/stamp_release.py` writes `VERSION` and `MARK` from the commit count, so
**Mk II.7** means "built from the seventh commit". Both are build artifacts and
are not in the repo. The mark is shown top right in the app and reported by
`/healthz`, which is what makes a stale deployment visible at a glance.
