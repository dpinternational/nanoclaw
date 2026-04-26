#!/bin/bash
# NanoClaw Health Check
# Monitors if the main process is running and restarts it if not.
# Also checks Docker is running.
# Install as a separate launchd plist that runs every 5 minutes.

LOG="/Users/davidprice/nanoclaw/logs/health-check.log"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')

# Check if Docker is running
# launchd PATH is minimal — must use full path to docker and set context
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
export HOME="/Users/davidprice"
if ! docker info &>/dev/null; then
    echo "[$TIMESTAMP] ALERT: Docker is not running. Attempting to start..." >> "$LOG"
    open -a Docker
    sleep 15
    if ! docker info &>/dev/null; then
        echo "[$TIMESTAMP] CRITICAL: Docker failed to start. NanoClaw cannot run." >> "$LOG"
        # Send alert via curl to a simple webhook or write a flag file
        touch /Users/davidprice/nanoclaw/store/.docker-down-alert
        exit 1
    fi
    echo "[$TIMESTAMP] Docker started successfully." >> "$LOG"
fi

# Check if NanoClaw main process is running
if ! pgrep -f "dist/index.js" &>/dev/null; then
    echo "[$TIMESTAMP] ALERT: NanoClaw is not running. Restarting..." >> "$LOG"

    # Try to load/restart via launchd
    launchctl load ~/Library/LaunchAgents/com.nanoclaw.plist 2>/dev/null
    sleep 5

    if pgrep -f "dist/index.js" &>/dev/null; then
        echo "[$TIMESTAMP] NanoClaw restarted successfully via launchd." >> "$LOG"
    else
        # Direct start as fallback
        cd /Users/davidprice/nanoclaw
        /usr/local/bin/node dist/index.js >> logs/nanoclaw.log 2>> logs/nanoclaw.error.log &
        sleep 5
        if pgrep -f "dist/index.js" &>/dev/null; then
            echo "[$TIMESTAMP] NanoClaw restarted directly." >> "$LOG"
        else
            echo "[$TIMESTAMP] CRITICAL: NanoClaw failed to restart!" >> "$LOG"
            touch /Users/davidprice/nanoclaw/store/.nanoclaw-down-alert
            exit 1
        fi
    fi
else
    # Running — but check for DUPLICATE instances (causes Telegram 409 conflicts)
    INSTANCE_COUNT=$(pgrep -f "dist/index.js" | wc -l | tr -d ' ')
    if [ "$INSTANCE_COUNT" -gt 1 ]; then
        echo "[$TIMESTAMP] ALERT: $INSTANCE_COUNT NanoClaw instances running! Killing all and restarting clean..." >> "$LOG"
        pkill -f "dist/index.js"
        sleep 3
        launchctl unload ~/Library/LaunchAgents/com.nanoclaw.plist 2>/dev/null
        sleep 2
        launchctl load ~/Library/LaunchAgents/com.nanoclaw.plist 2>/dev/null
        sleep 5
        NEW_COUNT=$(pgrep -f "dist/index.js" | wc -l | tr -d ' ')
        echo "[$TIMESTAMP] Restarted. Now running $NEW_COUNT instance(s)." >> "$LOG"
    fi

    # Clean up any alert flags
    rm -f /Users/davidprice/nanoclaw/store/.docker-down-alert 2>/dev/null
    rm -f /Users/davidprice/nanoclaw/store/.nanoclaw-down-alert 2>/dev/null
fi

# Check last message timestamp — if no messages in 2 hours during business hours, flag it
HOUR=$(date '+%H')
if [ "$HOUR" -ge 8 ] && [ "$HOUR" -le 22 ]; then
    LAST_MSG=$(sqlite3 /Users/davidprice/nanoclaw/store/messages.db "SELECT MAX(timestamp) FROM messages;" 2>/dev/null)
    if [ -n "$LAST_MSG" ]; then
        LAST_EPOCH=$(date -j -f "%Y-%m-%dT%H:%M:%S" "${LAST_MSG%%.*}" '+%s' 2>/dev/null)
        NOW_EPOCH=$(date '+%s')
        if [ -n "$LAST_EPOCH" ]; then
            DIFF=$(( (NOW_EPOCH - LAST_EPOCH) ))
            if [ "$DIFF" -gt 7200 ]; then
                echo "[$TIMESTAMP] WARNING: No messages received in $(( DIFF / 3600 )) hours. Last: $LAST_MSG" >> "$LOG"
            fi
        fi
    fi
fi
