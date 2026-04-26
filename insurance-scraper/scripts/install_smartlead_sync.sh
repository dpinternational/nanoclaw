#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/scripts/smartlead_sync.py"
LOG_DIR="$ROOT/logs"
STATE_DIR="$ROOT/state"
LOCK_FILE="$STATE_DIR/smartlead_sync.lock"

mkdir -p "$LOG_DIR" "$STATE_DIR"

CRON_LINE="*/15 * * * * cd $ROOT && if command -v flock >/dev/null 2>&1; then flock -n $LOCK_FILE /usr/bin/python3 $SCRIPT; else /usr/bin/python3 $SCRIPT; fi >> $LOG_DIR/smartlead_sync.log 2>&1"

TMP_CRON="$(mktemp)"
crontab -l 2>/dev/null | grep -v 'smartlead_sync.py' > "$TMP_CRON" || true
echo "$CRON_LINE" >> "$TMP_CRON"
crontab "$TMP_CRON"
rm -f "$TMP_CRON"

echo "Installed Smartlead sync cron:"
echo "  $CRON_LINE"
echo
echo "Run one sync now:"
echo "  cd $ROOT && /usr/bin/python3 scripts/smartlead_sync.py"
