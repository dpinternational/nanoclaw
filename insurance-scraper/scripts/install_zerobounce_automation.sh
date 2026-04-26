#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT="$ROOT/scripts/zerobounce_auto_verify.py"
LOG_DIR="$ROOT/logs"
STATE_DIR="$ROOT/state"
LOCK_FILE="$STATE_DIR/zerobounce_auto.lock"

mkdir -p "$LOG_DIR" "$STATE_DIR"

CRON_LINE="*/30 * * * * cd $ROOT && if command -v flock >/dev/null 2>&1; then flock -n $LOCK_FILE /usr/bin/python3 $SCRIPT; else /usr/bin/python3 $SCRIPT; fi >> $LOG_DIR/zerobounce_auto.log 2>&1"

TMP_CRON="$(mktemp)"
crontab -l 2>/dev/null | grep -v 'zerobounce_auto_verify.py' > "$TMP_CRON" || true
echo "$CRON_LINE" >> "$TMP_CRON"
crontab "$TMP_CRON"
rm -f "$TMP_CRON"

echo "Installed ZeroBounce automation cron:"
echo "  $CRON_LINE"
echo
echo "Run one dry check now:"
echo "  cd $ROOT && /usr/bin/python3 scripts/zerobounce_auto_verify.py --dry-run"
echo
echo "View logs:"
echo "  tail -n 80 $LOG_DIR/zerobounce_auto.log"
