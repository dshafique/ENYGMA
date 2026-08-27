#!/usr/bin/env bash
#
# ENYGMA installer for spark-4d80.
#
# Runs on: spark-4d80, with sudo.   sudo bash deploy/install-on-spark.sh
#
# This is sections 1, 2, 3 and 5 of the runbook, executable and idempotent. Run it
# twice and nothing bad happens.
#
# It deliberately does NOT touch two things:
#   * the cloudflared config, because that file is serving PHNTM right now and a
#     blind edit takes arkhm.io down. It prints the block for you to paste.
#   * disk quotas, because the right command depends on the filesystem.
#
set -euo pipefail

APP_USER=enygma
APP_HOME=/home/$APP_USER
APP_DIR=$APP_HOME/app
PORT=${ENYGMA_PORT:-4073}
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say()  { printf '\n\033[36m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
die()  { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run this with sudo: sudo bash deploy/install-on-spark.sh"

# Which build is about to be installed, said out loud before anything happens.
# An install of a stale extraction looks identical to a correct one right up to
# the point where a file you expected is missing.
RELEASE=$(cat "$SRC/VERSION" 2>/dev/null || echo unknown)
say "release $RELEASE  (from $SRC)"
if [ -f /home/enygma/app/VERSION ]; then
  note "replacing build $(cat /home/enygma/app/VERSION)"
fi

# --- python ---------------------------------------------------------------
PY=$(command -v python3 || true)
[ -n "$PY" ] || die "python3 is not installed."
PYV=$($PY -c 'import sys; print("%d.%d" % sys.version_info[:2])')
case "$PYV" in
  3.1[0-9]|3.[2-9][0-9]) : ;;
  *) die "Python $PYV is too old. ENYGMA needs 3.10 or newer." ;;
esac
note "python3 $PYV"
$PY -c 'import venv' 2>/dev/null || die "python3-venv is missing. apt install python3-venv"

# --- port ------------------------------------------------------------------
# PHNTM holds 4063. If something already answers on our port, stop rather than
# fight it: two apps on one port is exactly the coupling this design avoids.
if command -v ss >/dev/null && ss -ltn "( sport = :$PORT )" | grep -q ":$PORT"; then
  if ! systemctl is-active --quiet enygma 2>/dev/null; then
    die "Something is already listening on $PORT and it is not enygma. Pick another port."
  fi
fi

# --- 1. the unix user ------------------------------------------------------
say "unix user"
if id "$APP_USER" >/dev/null 2>&1; then
  note "$APP_USER already exists"
else
  adduser --disabled-password --gecos "" "$APP_USER"
  note "created $APP_USER"
fi
mkdir -p "$APP_DIR"

# --- 2. the code -----------------------------------------------------------
say "code into $APP_DIR"
systemctl stop enygma 2>/dev/null || true
# Release-owned directories are replaced, not merged. tar over the top leaves
# deleted files behind, and a stale template or module that nothing imports will
# quietly shadow the new one. data/, uploads/, .env and .venv are the operator's
# and are never in this list.
for d in src tools tests deploy; do
  rm -rf "${APP_DIR:?}/$d"
done
# data/ and uploads/ and .env are the operator's, not the release's.
tar -C "$SRC" --exclude=.venv --exclude=data --exclude=uploads --exclude=.env \
    --exclude=__pycache__ --exclude='*.pyc' -cf - . | tar -C "$APP_DIR" -xf -
# systemd's ReadWritePaths names these two; if they do not exist the unit refuses
# to start with a namespace error that does not mention the directory.
mkdir -p "$APP_DIR/data" "$APP_DIR/uploads"
chown -R "$APP_USER:$APP_USER" "$APP_HOME"
chmod +x "$APP_DIR/run.sh"

# Isolation is enforced by filesystem permissions, not by remembering to keep two
# directories apart. adduser leaves the home world-readable on most distributions,
# which would let the arkhm user read Yahya's audio and his database.
chmod 750 "$APP_HOME"
chmod 700 "$APP_DIR/data" "$APP_DIR/uploads"
note "copied $(find "$APP_DIR" -type f | wc -l) files"

# --- 3. dependencies -------------------------------------------------------
say "virtual environment"
if [ ! -x "$APP_DIR/.venv/bin/python" ]; then
  sudo -u "$APP_USER" "$PY" -m venv "$APP_DIR/.venv"
fi
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q --upgrade pip
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"
note "installed"

# --- 4. configuration ------------------------------------------------------
say "configuration"
if [ -f "$APP_DIR/.env" ]; then
  note ".env already present, left alone"
else
  SECRET=$(sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" -c \
           'import secrets; print(secrets.token_urlsafe(48))')
  sudo -u "$APP_USER" tee "$APP_DIR/.env" >/dev/null <<EOF
ENYGMA_PORT=$PORT
ENYGMA_HOST=127.0.0.1
ENYGMA_RP_ID=enygma.arkhm.io
ENYGMA_ORIGIN=https://enygma.arkhm.io
ENYGMA_SESSION_SECRET=$SECRET
ENYGMA_INSECURE_COOKIES=0
ENYGMA_PIPELINE=stub
ENYGMA_HINOTES_ENABLED=0
ENYGMA_MAX_UPLOAD_MB=500
EOF
  # The secret was written by the shell above and is never echoed.
  chmod 600 "$APP_DIR/.env"
  chown "$APP_USER:$APP_USER" "$APP_DIR/.env"
  note "wrote .env with a fresh secret, mode 600"
fi

# --- 5. prove it before wiring it up ---------------------------------------
say "migrations and tests, as $APP_USER"
sudo -u "$APP_USER" bash -c "cd '$APP_DIR' && .venv/bin/python -m src.db"
sudo -u "$APP_USER" bash -c "cd '$APP_DIR' && .venv/bin/python tools/check_tokens.py"
# .env is hand-edited, so it is checked on every install rather than trusted.
sudo -u "$APP_USER" bash -c "cd '$APP_DIR' && .venv/bin/python tools/check_env.py" || \
  note "check_env reported problems above. The install continues; fix them and restart."
sudo -u "$APP_USER" bash -c "cd '$APP_DIR' && .venv/bin/python -m pytest tests -q"

# --- 6. the service --------------------------------------------------------
# A container or WSL has no systemd. Say so plainly instead of failing with a
# D-Bus error that sends the reader down the wrong path.
HAVE_SYSTEMD=1
command -v systemctl >/dev/null 2>&1 || HAVE_SYSTEMD=0
[ -d /run/systemd/system ] || HAVE_SYSTEMD=0

if [ "$HAVE_SYSTEMD" -eq 0 ]; then
  say "systemd is not running here, so the service step is skipped"
  note "Everything else is installed. To run it in the foreground:"
  note "  sudo -u $APP_USER bash -c 'cd $APP_DIR && ./run.sh'"
  exit 0
fi

say "systemd"
install -m 644 "$APP_DIR/deploy/enygma.service" /etc/systemd/system/enygma.service
systemctl daemon-reload
systemctl enable enygma >/dev/null 2>&1
systemctl restart enygma
sleep 3
systemctl is-active --quiet enygma || {
  journalctl -u enygma -n 30 --no-pager
  die "enygma did not start. The log above says why."
}
note "$(systemctl show enygma -p MemoryMax --value) memory ceiling in force"

# --- 7. verify the artifact, not the report --------------------------------
say "checks"
HEALTH=$(curl -fsS "http://127.0.0.1:$PORT/healthz" || true)
[ -n "$HEALTH" ] || die "healthz did not answer on $PORT."
note "healthz: $HEALTH"

# Prove the isolation rather than assuming it. Check the real neighbour if it
# exists, and an unrelated account either way.
ISOLATION_OK=1
for OTHER in arkhm nobody; do
  id "$OTHER" >/dev/null 2>&1 || continue
  if sudo -u "$OTHER" test -r "$APP_DIR/data" 2>/dev/null; then
    printf '\033[31m    WARNING: %s can read %s. Isolation is not real.\033[0m\n' "$OTHER" "$APP_DIR/data"
    ISOLATION_OK=0
  fi
  if sudo -u "$OTHER" test -r "$APP_DIR/.env" 2>/dev/null; then
    printf '\033[31m    WARNING: %s can read the .env. Rotate the secret.\033[0m\n' "$OTHER"
    ISOLATION_OK=0
  fi
done
[ "$ISOLATION_OK" -eq 1 ] && note "no other account can read the database, the audio or the secret"

cat <<EOF

$(printf '\033[32mENYGMA is running on 127.0.0.1:%s\033[0m' "$PORT")

Next, in order.

1) A demo week, if the app is still empty. Five meetings with real transcripts,
   speakers, summaries and actions, so every tab has something in it:

       sudo -u enygma bash -c "cd /home/enygma/app && .venv/bin/python tools/seed_demo.py"

   and to take it out again:

       sudo -u enygma bash -c "cd /home/enygma/app && .venv/bin/python tools/seed_demo.py --clear"

2) Open https://enygma.arkhm.io and create a passkey. The first device to enrol
   becomes the owner, so do this on the phone if the phone is the main device.

3) The transcript pipeline is still the stub: every transcript is placeholder
   text. Switch it in /home/enygma/app/.env when the key is ready:

       ENYGMA_PIPELINE=gemini
       ENYGMA_GEMINI_API_KEY=...

   then: sudo systemctl restart enygma

The ingress rule and the DNS record for enygma.arkhm.io already exist. If the
hostname ever stops resolving, deploy/dns-record.sh prints what it should be.

Useful afterwards:

    journalctl -u enygma -f
    sudo systemctl restart enygma
    curl -s https://enygma.arkhm.io/healthz     # says which build is live
EOF
