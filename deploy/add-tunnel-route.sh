#!/usr/bin/env bash
#
# Add enygma.arkhm.io to the cloudflared config that is already serving PHNTM.
#
# Runs on: spark-4d80, with sudo.   sudo bash deploy/add-tunnel-route.sh
#
# The whole point of this script is that it does not restart anything until the
# new config has been validated AND you have seen, in writing, that arkhm.io still
# routes where it did before. A mis-indented YAML line here is an outage on the
# other app.
#
set -euo pipefail

HOSTNAME_NEW=${1:-enygma.arkhm.io}
PORT=${ENYGMA_PORT:-4073}

say()  { printf '\n\033[36m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
die()  { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run with sudo."
command -v cloudflared >/dev/null || die "cloudflared is not on PATH."

CONFIG=""
for candidate in /etc/cloudflared/config.yml /etc/cloudflared/config.yaml \
                 /root/.cloudflared/config.yml /home/*/.cloudflared/config.yml; do
  [ -f "$candidate" ] && { CONFIG="$candidate"; break; }
done
[ -n "$CONFIG" ] || die "No cloudflared config found. Is the tunnel configured?"
say "config: $CONFIG"

# --- what is there now ----------------------------------------------------
say "current ingress"
sed -n '/^ingress:/,$p' "$CONFIG" | sed 's/^/    /'

if grep -q "$HOSTNAME_NEW" "$CONFIG"; then
  note ""
  note "$HOSTNAME_NEW is already in this config. Nothing to add."
  exit 0
fi

# --- back up --------------------------------------------------------------
BACKUP="$CONFIG.bak-$(date +%Y%m%d-%H%M%S)"
cp -a "$CONFIG" "$BACKUP"
say "backed up to $BACKUP"

# --- insert above the catch-all -------------------------------------------
# cloudflared requires a final rule with no hostname. The new rule has to go
# before it, or it is never reached. Done in python to keep the indentation the
# file already uses rather than guessing at it with sed.
python3 - "$CONFIG" "$HOSTNAME_NEW" "$PORT" <<'PY'
import re, sys
path, host, port = sys.argv[1], sys.argv[2], sys.argv[3]
lines = open(path).read().splitlines()

start = next((i for i, l in enumerate(lines) if re.match(r'^\s*ingress\s*:', l)), None)
if start is None:
    sys.exit("No ingress: block in the config.")

# The catch-all is the first rule after ingress: that has a service and no hostname.
catch = None
indent = "  "
i = start + 1
while i < len(lines):
    line = lines[i]
    if line.strip() and not line.startswith((" ", "\t")):
        break                                   # left the ingress block
    if re.match(r'^\s*-\s', line):
        m = re.match(r'^(\s*)-', line)
        indent = m.group(1)
        block = [line]
        j = i + 1
        while j < len(lines) and lines[j].startswith(indent + " ") and not re.match(r'^\s*-\s', lines[j]):
            block.append(lines[j]); j += 1
        if not any("hostname" in b for b in block):
            catch = i
            break
        i = j
        continue
    i += 1

if catch is None:
    sys.exit("No catch-all rule found. cloudflared will not start without one; "
             "add it by hand and re-run.")

new = [f"{indent}- hostname: {host}",
       f"{indent}  service: http://127.0.0.1:{port}"]
lines[catch:catch] = new
open(path, "w").write("\n".join(lines) + "\n")
print(f"    inserted above the catch-all at line {catch + 1}")
PY

say "diff"
diff -u "$BACKUP" "$CONFIG" | sed 's/^/    /' || true

# --- validate before touching the running service -------------------------
say "validating"
# --config is a global flag on `tunnel`, before the subcommand. Put it after and
# cloudflared prints "Incorrect Usage" and still exits 0, so the exit code alone
# is not evidence of anything. Check what it actually said.
VALIDATION=$(cloudflared tunnel --config "$CONFIG" ingress validate 2>&1) || true
printf '%s\n' "$VALIDATION" | sed 's/^/    /'
if printf '%s' "$VALIDATION" | grep -qiE "incorrect usage|flag provided but not defined"; then
  cp -a "$BACKUP" "$CONFIG"
  die "cloudflared rejected the command itself, so nothing was validated. Config restored."
fi
if ! printf '%s' "$VALIDATION" | grep -qiE "valid|OK"; then
  cp -a "$BACKUP" "$CONFIG"
  die "Validation did not report success. Config restored; nothing was restarted."
fi
note "validated for real this time"

say "routing check, before any restart"
route_for() {
  cloudflared tunnel --config "$CONFIG" ingress rule "https://$1" 2>&1 \
    | grep -iE "matched|service" | tail -1 | sed 's/^ *//'
}
ROUTES_OK=1
for host in "$HOSTNAME_NEW" $(grep -oP '(?<=hostname:\s)\S+' "$BACKUP" | sort -u); do
  ANSWER=$(route_for "$host")
  if [ -z "$ANSWER" ]; then
    printf '    %-28s -> \033[31mno answer, so this check proved nothing\033[0m\n' "$host"
    ROUTES_OK=0
  else
    printf '    %-28s -> %s\n' "$host" "$ANSWER"
  fi
done
if [ "$ROUTES_OK" -eq 0 ]; then
  cp -a "$BACKUP" "$CONFIG"
  die "The routing check returned nothing, so it verified nothing. Config restored."
fi

cat <<EOF

    Read those lines. Every hostname that worked before must still point at the
    same service. If anything moved, restore and stop:

        sudo cp -a $BACKUP $CONFIG

EOF
read -r -p "    Restart cloudflared now? [y/N] " answer
case "$answer" in
  [yY]*) ;;
  *) note "Left alone. The config is edited but not live until you restart."; exit 0 ;;
esac

# --- DNS ------------------------------------------------------------------
say "DNS"
TUNNEL=$(grep -oP '(?<=^tunnel:\s).*' "$CONFIG" | head -1 | tr -d '"' || true)
CREDS=$(grep -oP '(?<=^credentials-file:\s).*' "$CONFIG" | head -1 | tr -d '"' || true)
UUID=$(basename "${CREDS:-}" .json 2>/dev/null || true)
case "$TUNNEL" in
  [0-9a-f]*-[0-9a-f]*-*) UUID="$TUNNEL" ;;
esac

# `route dns` needs an origin certificate. A tunnel installed from a token has
# none, which is normal and not a fault.
HAVE_CERT=0
for c in ~/.cloudflared/cert.pem /etc/cloudflared/cert.pem /root/.cloudflared/cert.pem; do
  [ -f "$c" ] && HAVE_CERT=1
done

DNS_DONE=0
if [ "$HAVE_CERT" -eq 1 ] && [ -n "$TUNNEL" ]; then
  if cloudflared tunnel route dns "$TUNNEL" "$HOSTNAME_NEW" 2>&1 | sed 's/^/    /'; then
    DNS_DONE=1
  fi
else
  note "No origin certificate here, so this box cannot create the record itself."
fi

if [ "$DNS_DONE" -eq 0 ]; then
  cat <<EOF

    \033[33mCreate the DNS record yourself. Either works.\033[0m

    A) In the Cloudflare dashboard, arkhm.io > DNS > Add record:

           Type    CNAME
           Name    ${HOSTNAME_NEW%%.*}
           Target  ${UUID:-<tunnel-uuid>}.cfargotunnel.com
           Proxy   Proxied (orange cloud)  <-- required, a tunnel needs the proxy

    B) Or authorise this box once, then let cloudflared do it:

           cloudflared tunnel login          # prints a URL, open it anywhere
           cloudflared tunnel route dns ${TUNNEL:-<tunnel>} $HOSTNAME_NEW

EOF
fi

# --- restart and check both -----------------------------------------------
say "restarting cloudflared"
systemctl restart cloudflared
sleep 5

say "checks"
printf '    %-28s ' "$HOSTNAME_NEW"
curl -fsS --max-time 20 "https://$HOSTNAME_NEW/healthz" || \
  printf '\033[31mno answer yet (DNS can take a minute)\033[0m'
printf '\n'
for existing in $(grep -oP '(?<=hostname:\s)\S+' "$BACKUP" | sort -u); do
  printf '    %-28s %s\n' "$existing" "$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "https://$existing" || echo 'no answer')"
done

cat <<EOF

    If the other hostnames stopped answering, restore and restart:

        sudo cp -a $BACKUP $CONFIG && sudo systemctl restart cloudflared

    Otherwise open https://$HOSTNAME_NEW and create a passkey.
EOF
