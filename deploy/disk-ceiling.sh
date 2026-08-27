#!/usr/bin/env bash
#
# A disk ceiling for the enygma user, before the first upload.
#
# Runs on: spark-4d80, with sudo.   sudo bash deploy/disk-ceiling.sh [GB]
#
# The filesystem is shared. A runaway ingest on ENYGMA's side eats space PHNTM
# needs, and SQLite behaves badly on a full disk. Quotas are better than an alarm
# because they stop the write; an alarm only tells you afterwards. This tries the
# quota and falls back to the alarm.
#
set -euo pipefail

LIMIT_GB=${1:-200}
APP_USER=enygma
APP_HOME=/home/$APP_USER

say()  { printf '\n\033[36m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo."; exit 1; }
id "$APP_USER" >/dev/null 2>&1 || { echo "No $APP_USER user. Run install-on-spark.sh first."; exit 1; }

say "context"
note "$(df -h "$APP_HOME" | tail -1)"
note "enygma is using $(du -sh "$APP_HOME" 2>/dev/null | cut -f1) today"
note "audio costs about 75MB per hour of meeting, so ${LIMIT_GB}GB is roughly $((LIMIT_GB * 1000 / 75)) hours"

FS=$(df --output=source "$APP_HOME" | tail -1)
SOFT=$((LIMIT_GB * 1024 * 1024))
HARD=$(( (LIMIT_GB + 10) * 1024 * 1024 ))

if command -v setquota >/dev/null 2>&1 && quotaon -p "$(df --output=target "$APP_HOME" | tail -1)" 2>/dev/null | grep -q "is on"; then
  say "setting a quota on $FS"
  setquota -u "$APP_USER" "$SOFT" "$HARD" 0 0 "$(df --output=target "$APP_HOME" | tail -1)"
  quota -u "$APP_USER" | sed 's/^/    /'
  note "the write itself will fail past the hard limit, which is the point"
  exit 0
fi

say "quotas are not enabled on this filesystem, installing an hourly alarm instead"
note "an alarm reports; it does not stop the write. Enabling quotas is better if"
note "you are willing to remount with usrquota."

cat > /etc/cron.hourly/enygma-disk <<EOF
#!/bin/sh
# Written by ENYGMA deploy/disk-ceiling.sh
LIMIT_KB=$((LIMIT_GB * 1024 * 1024))
USED_KB=\$(du -sk $APP_HOME 2>/dev/null | cut -f1)
[ "\$USED_KB" -gt "\$LIMIT_KB" ] && \\
  logger -t enygma-disk "over ${LIMIT_GB}GB: \${USED_KB}k used in $APP_HOME"
FREE_KB=\$(df -k $APP_HOME | tail -1 | awk '{print \$4}')
[ "\$FREE_KB" -lt 52428800 ] && \\
  logger -t enygma-disk "less than 50GB free on the volume: \${FREE_KB}k"
exit 0
EOF
chmod +x /etc/cron.hourly/enygma-disk
sh /etc/cron.hourly/enygma-disk && note "installed and ran once cleanly"
note "watch it with:  journalctl -t enygma-disk -f"
