#!/usr/bin/env bash
# Runs on: spark-4d80, as the enygma user.
set -euo pipefail
cd "$(dirname "$0")"
# .env is data, not code.
#
# Sourcing it runs every line in the file with the app's privileges at each
# start, and .env is precisely the file a human pastes into. One stray line -- a
# shell command that ended up in the paste, a comment written without a "#" --
# becomes an executed command. Under systemd that runs on every restart.
# Parse it instead, and say out loud what was ignored.
load_env() {
    local file=$1 line key value ignored=0
    while IFS= read -r line || [ -n "$line" ]; do
        case "$line" in ''|'#'*) continue ;; esac
        key=${line%%=*}
        # An assignment, and the name is a shell identifier. Anything else is a
        # stray line, however much it looks like one.
        case "$line$key" in
            *=*) ;;
            *) key='' ;;
        esac
        case "$key" in
            ''|*[!A-Za-z0-9_]*|[0-9]*) key='' ;;
        esac
        if [ -z "$key" ]; then
            ignored=$((ignored + 1))
            printf 'run.sh: ignoring non-assignment line in .env: %.48s\n' "$line" >&2
            continue
        fi
        value=${line#*=}
        # systemd's EnvironmentFile strips matching surrounding quotes. Match it,
        # so the same file means the same thing under systemd and by hand.
        case "$value" in
            \"*\") value=${value#?}; value=${value%?} ;;
            \'*\') value=${value#?}; value=${value%?} ;;
        esac
        export "$key=$value"
    done < "$file"
    if [ "$ignored" -gt 0 ]; then
        printf 'run.sh: %d line(s) in .env are not KEY=VALUE and were ignored.\n' "$ignored" >&2
        printf 'run.sh: inspect it with  .venv/bin/python tools/check_env.py\n' >&2
    fi
}
if [ -f .env ]; then load_env .env; fi

# Prefer the virtual environment. systemd runs this directly, so a bare "python3"
# here would quietly use the system interpreter and fail on the first import.
PY=./.venv/bin/python
[ -x "$PY" ] || PY=python3

exec "$PY" -m uvicorn src.main:app \
    --host "${ENYGMA_HOST:-127.0.0.1}" --port "${ENYGMA_PORT:-4073}"
