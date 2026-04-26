#!/usr/bin/env bash
set -euo pipefail

TMP_CRON="$(mktemp)"
crontab -l 2>/dev/null | grep -v 'zerobounce_auto_verify.py' > "$TMP_CRON" || true
crontab "$TMP_CRON"
rm -f "$TMP_CRON"

echo "Removed zerobounce_auto_verify.py cron entries."
