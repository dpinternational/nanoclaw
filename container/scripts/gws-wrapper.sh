#!/bin/bash
# Wrapper around gws CLI that gates outbound email operations.
# Intercepts send/reply/forward and queues them for David's approval.

REAL_GWS="/usr/local/bin/gws-real"
IPC_DRAFTS="/workspace/ipc/email_drafts"

# Check if this is a gmail operation that needs gating
if [[ "$1" == "gmail" ]]; then
  case "$2" in
    +send|+reply|+reply-all|+forward)
      # Gate this operation — write draft to IPC for approval
      mkdir -p "$IPC_DRAFTS"

      DRAFT_ID="draft-$(date +%s)-$RANDOM"
      DRAFT_FILE="$IPC_DRAFTS/${DRAFT_ID}.json"

      # Capture all arguments
      cat > "$DRAFT_FILE" <<EOF
{
  "type": "email_draft",
  "draft_id": "$DRAFT_ID",
  "command": "gws $*",
  "full_args": $(printf '%s\n' "$@" | jq -R . | jq -s .),
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

      echo "⚠️ Email draft queued for David's approval (ID: $DRAFT_ID)."
      echo "The email will NOT be sent until David approves it."
      echo "Do not attempt to send this email directly or through other means."
      exit 0
      ;;
  esac

  # Block trash and delete operations entirely
  ALL_ARGS="$*"
  if echo "$ALL_ARGS" | grep -qiE "trash|delete|batchDelete"; then
    echo "🚫 BLOCKED: Deleting or trashing emails is not allowed."
    echo "You may only archive emails (remove from inbox). Use messages modify with removeLabelIds: [\"INBOX\"] instead."
    exit 1
  fi
fi

# All other gws commands pass through normally
exec "$REAL_GWS" "$@"
