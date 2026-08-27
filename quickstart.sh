#!/usr/bin/env bash
# Runs on: your machine. Gets ENYGMA up on http://localhost:4073 from a cold start.
#
#   ./quickstart.sh              local only
#   ./quickstart.sh --tunnel     local plus a public https URL via Cloudflare
#
set -euo pipefail
cd "$(dirname "$0")"

PORT="${ENYGMA_PORT:-4073}"
TUNNEL=0
[ "${1:-}" = "--tunnel" ] && TUNNEL=1

command -v python3 >/dev/null || { echo "python3 is required"; exit 1; }

if [ ! -d .venv ]; then
  echo "→ creating .venv"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
echo "→ installing dependencies"
pip install -q --upgrade pip
pip install -q -r requirements.txt

if [ ! -f .env ]; then
  echo "→ writing .env for local use"
  SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(48))")
  cat > .env <<EOF
ENYGMA_PORT=$PORT
ENYGMA_HOST=127.0.0.1
ENYGMA_RP_ID=localhost
ENYGMA_ORIGIN=http://localhost:$PORT
ENYGMA_SESSION_SECRET=$SECRET
ENYGMA_INSECURE_COOKIES=1
ENYGMA_PIPELINE=stub
ENYGMA_HINOTES_ENABLED=0
EOF
  chmod 600 .env
fi

python3 tools/check_tokens.py
python3 -m pytest tests -q

if [ "$TUNNEL" = "1" ]; then
  command -v cloudflared >/dev/null || {
    echo "cloudflared is not installed. brew install cloudflared, or see"
    echo "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
    exit 1; }
  echo
  echo "→ opening a public tunnel. Watch for the trycloudflare.com URL below."
  echo "  Passkeys are bound to an origin: set ENYGMA_RP_ID and ENYGMA_ORIGIN to"
  echo "  that hostname in .env and restart, or the unlock will refuse."
  echo
  cloudflared tunnel --url "http://localhost:$PORT" &
fi

echo
echo "→ ENYGMA on http://localhost:$PORT"
echo "  Open /lock and create a passkey. Then drop an audio file on /meetings."
echo
exec ./run.sh
