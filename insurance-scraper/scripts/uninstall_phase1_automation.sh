#!/usr/bin/env bash
set -euo pipefail

TMP_CRON="$(mktemp)"
crontab -l 2>/dev/null | grep -v 'phase1_guard.py' > "$TMP_CRON" || true
crontab "$TMP_CRON"
rm -f "$TMP_CRON"

echo "Removed phase1_guard.py cron entries."
