#!/usr/bin/env bash
#
# A nightly database backup, verified every time it is taken.
#
# Runs on: spark-4d80, with sudo.   sudo bash deploy/install-backups.sh
#
# What this protects against: corruption, a bad migration, an accidental delete,
# and anything that damages the database while the disk survives.
#
# What it does NOT protect against: losing the disk. The backups live on the same
# NVMe as the database, because there is nowhere else on this machine to put
# them. Off-machine copies are a separate decision and this script does not
# pretend to make it.
#
# The audio is not backed up. It is large and re-uploadable; the database is
# neither.
#
set -euo pipefail

APP_USER=enygma
APP_DIR=/home/$APP_USER/app
KEEP=${1:-14}

say()  { printf '\n\033[36m==> %s\033[0m\n' "$*"; }
note() { printf '    %s\n' "$*"; }
die()  { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Run with sudo: sudo bash deploy/install-backups.sh"
id "$APP_USER" >/dev/null 2>&1 || die "No $APP_USER user. Run install-on-spark.sh first."
[ -x "$APP_DIR/.venv/bin/python" ] || die "No virtualenv at $APP_DIR/.venv"

say "one now, so the first backup is not scheduled for tonight"
sudo -u "$APP_USER" bash -c "cd '$APP_DIR' && .venv/bin/python tools/backup.py --keep $KEEP" \
  || die "The first backup failed. Nothing was scheduled."

say "nightly job"
cat > /etc/cron.daily/enygma-backup <<EOF
#!/bin/sh
# Written by deploy/install-backups.sh. Keeps $KEEP nights.
OUT=\$(sudo -u $APP_USER sh -c "cd $APP_DIR && .venv/bin/python tools/backup.py --keep $KEEP" 2>&1)
STATUS=\$?
if [ \$STATUS -eq 0 ]; then
  echo "\$OUT" | logger -t enygma-backup
else
  echo "BACKUP FAILED (exit \$STATUS)" | logger -t enygma-backup -p user.err
  echo "\$OUT" | logger -t enygma-backup -p user.err
fi
EOF
chmod 755 /etc/cron.daily/enygma-backup
note "installed /etc/cron.daily/enygma-backup, keeping $KEEP nights"

say "proving the schedule itself runs, not just the command"
/etc/cron.daily/enygma-backup || die "The scheduled job failed when run directly."
note "ran cleanly"

say "where they are"
sudo -u "$APP_USER" ls -lh "/home/$APP_USER/app/backups" | tail -n +2 | sed 's/^/    /'

cat <<EOF

$(printf '\033[32mNightly backups are on.\033[0m')

  watch them          journalctl -t enygma-backup -f
  take one now        sudo -u $APP_USER sh -c "cd $APP_DIR && .venv/bin/python tools/backup.py"
  prove one restores  sudo -u $APP_USER sh -c "cd $APP_DIR && .venv/bin/python tools/backup.py --verify"

  Restoring, if it ever comes to that:

      sudo systemctl stop enygma
      sudo -u $APP_USER sh -c "cd $APP_DIR && gunzip -c backups/<file>.db.gz > data/enygma.db"
      sudo systemctl start enygma

  These sit on the same disk as the database. That covers corruption and
  mistakes, not a dead NVMe. If this data matters beyond that, copy
  $APP_DIR/backups somewhere else on a schedule.
EOF
