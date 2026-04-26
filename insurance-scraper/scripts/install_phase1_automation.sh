#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$ROOT/logs"
STATE_DIR="$ROOT/state"
GUARD="$ROOT/scripts/phase1_guard.py"

mkdir -p "$LOG_DIR" "$STATE_DIR"

DOCKER_BIN="$(command -v docker || true)"
PATH_PREFIX="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/Applications/Docker.app/Contents/Resources/bin"
CRON_LINE="*/5 * * * * cd $ROOT && PATH=$PATH_PREFIX DOCKER_BIN=$DOCKER_BIN /usr/bin/python3 $GUARD >> $LOG_DIR/phase1_guard.log 2>&1"

TMP_CRON="$(mktemp)"
crontab -l 2>/dev/null | grep -v 'phase1_guard.py' > "$TMP_CRON" || true
echo "$CRON_LINE" >> "$TMP_CRON"
crontab "$TMP_CRON"
rm -f "$TMP_CRON"

echo "Installed Phase 1 automation cron:"
echo "  $CRON_LINE"
echo
echo "Run one immediate check now:"
echo "  cd $ROOT && /usr/bin/python3 scripts/phase1_guard.py"
echo
echo "View latest guard log:"
echo "  tail -n 80 $LOG_DIR/phase1_guard.log"
