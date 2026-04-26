#!/usr/bin/env bash
# deploy-to-server.sh — rsync deploy from Mac to Hetzner server.
#
# Usage:
#   ./scripts/deploy-to-server.sh                  # dry-run, default subdir=scripts
#   ./scripts/deploy-to-server.sh scripts          # dry-run scripts/
#   ./scripts/deploy-to-server.sh scripts --execute  # actually sync
#   ./scripts/deploy-to-server.sh insurance-scraper --execute
#
# Always dry-runs unless --execute is passed.
# Logs to logs/deploy.log.

set -euo pipefail

LOCAL_ROOT="/Users/davidprice/nanoclaw"
REMOTE_HOST="root@89.167.109.12"
REMOTE_ROOT_DEFAULT="/home/david/nanoclaw"
# insurance-scraper is deployed at the SIBLING path on the server, not under nanoclaw/
REMOTE_ROOT_INSURANCE="/home/david/insurance-scraper"
LOG_DIR="$LOCAL_ROOT/logs"
LOG_FILE="$LOG_DIR/deploy.log"

SUBDIR="${1:-scripts}"
MODE="dry-run"
shift || true
for arg in "$@"; do
  case "$arg" in
    --execute) MODE="execute" ;;
    --dry-run) MODE="dry-run" ;;
    *) ;;
  esac
done

mkdir -p "$LOG_DIR"

# Choose remote root + remap subdir if it starts with insurance-scraper
if [[ "$SUBDIR" == insurance-scraper* ]]; then
  REMOTE_ROOT="$REMOTE_ROOT_INSURANCE"
  REMOTE_SUBDIR="${SUBDIR#insurance-scraper}"
  REMOTE_SUBDIR="${REMOTE_SUBDIR#/}"
else
  REMOTE_ROOT="$REMOTE_ROOT_DEFAULT"
  REMOTE_SUBDIR="$SUBDIR"
fi

LOCAL_PATH="$LOCAL_ROOT/$SUBDIR/"
if [[ -n "$REMOTE_SUBDIR" ]]; then
  REMOTE_PATH="$REMOTE_ROOT/$REMOTE_SUBDIR/"
else
  REMOTE_PATH="$REMOTE_ROOT/"
fi

if [[ ! -d "$LOCAL_PATH" ]]; then
  echo "ERROR: local path does not exist: $LOCAL_PATH" >&2
  exit 1
fi

RSYNC_OPTS=(
  -av
  --exclude '__pycache__'
  --exclude '*.pyc'
  --exclude '.venv'
  --exclude '*.bak'
  --exclude '*.bak-*'
  --exclude '.DS_Store'
)

if [[ "$MODE" == "dry-run" ]]; then
  RSYNC_OPTS+=(--dry-run)
fi

ts() { date -u +"%Y-%m-%dT%H:%M:%SZ"; }
log() { echo "[$(ts)] $*" | tee -a "$LOG_FILE"; }

log "===== deploy start: subdir=$SUBDIR mode=$MODE ====="
log "local:  $LOCAL_PATH"
log "remote: $REMOTE_HOST:$REMOTE_PATH"

local_count=$(find "$LOCAL_PATH" -type f 2>/dev/null | wc -l | tr -d ' ')
log "local file count (pre):  $local_count"

remote_count_before=$(ssh -o StrictHostKeyChecking=accept-new "$REMOTE_HOST" \
  "find '$REMOTE_PATH' -type f 2>/dev/null | wc -l" | tr -d ' ' || echo "?")
log "remote file count (pre): $remote_count_before"

log "running rsync (${RSYNC_OPTS[*]})..."
rsync "${RSYNC_OPTS[@]}" "$LOCAL_PATH" "$REMOTE_HOST:$REMOTE_PATH" 2>&1 | tee -a "$LOG_FILE"

if [[ "$MODE" == "execute" ]]; then
  log "chown david:david on remote $REMOTE_PATH ..."
  ssh "$REMOTE_HOST" "chown -R david:david '$REMOTE_PATH' && chmod -R u+rw '$REMOTE_PATH'" \
    | tee -a "$LOG_FILE" || log "WARN: chown failed"

  remote_count_after=$(ssh "$REMOTE_HOST" \
    "find '$REMOTE_PATH' -type f 2>/dev/null | wc -l" | tr -d ' ' || echo "?")
  log "remote file count (post): $remote_count_after"
else
  log "DRY-RUN — no chown, no post-count. Re-run with --execute to apply."
fi

log "===== deploy end: subdir=$SUBDIR mode=$MODE ====="
