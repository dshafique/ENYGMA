#!/usr/bin/env bash
# Print exactly the DNS record enygma.arkhm.io needs. Reads only; changes nothing.
# Runs on: spark-4d80.   bash deploy/dns-record.sh
set -euo pipefail
HOST=${1:-enygma.arkhm.io}
CONFIG=""
for c in /etc/cloudflared/config.yml /etc/cloudflared/config.yaml \
         /root/.cloudflared/config.yml /home/*/.cloudflared/config.yml; do
  [ -r "$c" ] && { CONFIG="$c"; break; }
done
[ -n "$CONFIG" ] || { echo "No readable cloudflared config. Try with sudo."; exit 1; }

TUNNEL=$(grep -oP '(?<=^tunnel:\s).*' "$CONFIG" | head -1 | tr -d '"' || true)
CREDS=$(grep -oP '(?<=^credentials-file:\s).*' "$CONFIG" | head -1 | tr -d '"' || true)
UUID=$(basename "${CREDS:-}" .json 2>/dev/null || true)
case "$TUNNEL" in [0-9a-f]*-[0-9a-f]*-*) UUID="$TUNNEL" ;; esac

echo
echo "  config      $CONFIG"
echo "  tunnel      ${TUNNEL:-unknown}"
echo "  uuid        ${UUID:-unknown}"
echo
if [ -z "$UUID" ] || [ "$UUID" = "." ]; then
  echo "  Could not work out the UUID. Show me these two lines:"
  grep -E '^(tunnel|credentials-file):' "$CONFIG" || true
  exit 1
fi
cat <<EOF
  Add this in the Cloudflare dashboard, under arkhm.io > DNS > Records:

      Type    CNAME
      Name    ${HOST%%.*}
      Target  ${UUID}.cfargotunnel.com
      Proxy   Proxied (orange cloud)

  The orange cloud is not optional: an unproxied CNAME to cfargotunnel.com
  does not resolve. Then, from anywhere:

      curl -s https://${HOST}/healthz
EOF
