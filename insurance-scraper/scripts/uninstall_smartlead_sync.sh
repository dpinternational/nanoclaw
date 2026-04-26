#!/usr/bin/env bash
set -euo pipefail

TMP_CRON="$(mktemp)"
crontab -l 2>/dev/null | grep -v 'smartlead_sync.py' > "$TMP_CRON" || true
crontab "$TMP_CRON"
rm -f "$TMP_CRON"

echo "Removed smartlead_sync.py cron entries."
