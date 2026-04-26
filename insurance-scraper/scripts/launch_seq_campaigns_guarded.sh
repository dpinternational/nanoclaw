#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CMD="$ROOT/scripts/smartlead_campaign_launch_guard.py"

ACTION="${1:-}"
EXECUTE_FLAG="${2:-}"
CONFIRM="${3:-}"

if [[ -z "$ACTION" ]]; then
  echo "Usage: $0 <launch|pause> [--execute] [LAUNCH|PAUSE]"
  echo "Examples:"
  echo "  $0 launch"
  echo "  $0 launch --execute LAUNCH"
  echo "  $0 pause --execute PAUSE"
  exit 1
fi

ARGS=(
  --campaign-id 3232436
  --campaign-id 3232437
  --action "$ACTION"
)

if [[ "$EXECUTE_FLAG" == "--execute" ]]; then
  ARGS+=(--execute)
fi

if [[ -n "$CONFIRM" ]]; then
  ARGS+=(--confirm "$CONFIRM")
fi

python3 "$CMD" "${ARGS[@]}"
