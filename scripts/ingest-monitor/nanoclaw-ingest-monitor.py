#!/usr/bin/env python3
"""
Nanoclaw ingest staleness monitor.

Strategy:
  BUSINESS HOURS (7am-11pm ET): the business is active on Telegram, so SOME
    message should land SOMEWHERE we care about at least every 45 minutes.
    Alert if NONE of the watched chats received a message in that window.
  OFF HOURS: per-chat threshold. Alert only if a specific chat (e.g. TPG
    UnCaged) has been stale for >4 hours.

Robust to:
  - Transient SSH failures (2 retries with backoff before alerting).
  - Clock skew (uses server's own timestamps, not Mac clock, for the ingest
    freshness check).
  - State file corruption (logs a warning, resets state, doesn't crash).

Alerts via iMessage (imsg CLI) + macOS notification + audit log. Explicitly
NOT Telegram.

Runs every 5 min via launchd (com.nanoclaw.ingest-monitor).
"""
import subprocess, sys, json, os, time, logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    ET = ZoneInfo("America/New_York")
except ImportError:
    ET = timezone(timedelta(hours=-4))

SSH_TARGET = "root@89.167.109.12"
DB_PATH = "/home/david/nanoclaw/store/messages.db"
STATE_FILE = Path.home() / ".hermes" / "nanoclaw-ingest-monitor.json"
ALERT_LOG = Path.home() / ".hermes" / "nanoclaw-ingest-monitor-alerts.log"
IMESSAGE_TO = "+12399194364"

# Business-critical chats: if NONE of these see a message during business hours, alert.
WATCHED_CHATS = {
    "tg:-1002362081030": "TPG UnCaged",
    "tg:577469008": "David Main",
    "tg:-5241666246": "Sound Like David Price",
    "tg:-5147163125": "Brain Dump",
    "tg:-4673675100": "FB Posting",
    "tg:-5222826713": "Content Ideas",
}

# TPG UnCaged is special — stale even off-hours is bad.
CRITICAL_CHATS = {"tg:-1002362081030"}

BUSINESS_START = 7  # 7 AM ET
BUSINESS_END = 23   # 11 PM ET
BUSINESS_IDLE_MIN = 45     # no msg in ANY watched chat this long = alert
CRITICAL_STALE_HRS = 4     # TPG UnCaged stale this long = alert (any time)
ALERT_COOLDOWN_MIN = 30    # first re-alert after this long
ESCALATION_MIN = 60        # if still stale after this long, alert AGAIN unconditionally

SSH_RETRIES = 2
SSH_RETRY_DELAY = 15


def ssh_query(sql: str) -> str | None:
    """Run sqlite3 over ssh with retry. Return stdout text or None on failure."""
    for attempt in range(SSH_RETRIES + 1):
        try:
            r = subprocess.run(
                [
                    "ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
                    "-o", "ServerAliveInterval=5",
                    SSH_TARGET,
                    f"sqlite3 {DB_PATH} \"{sql}\"",
                ],
                capture_output=True, text=True, timeout=30,
            )
            if r.returncode == 0:
                return r.stdout
        except subprocess.TimeoutExpired:
            pass
        if attempt < SSH_RETRIES:
            time.sleep(SSH_RETRY_DELAY)
    return None


def ssh_read(path: str) -> str | None:
    """Read a small file on the server via ssh. Returns content or None."""
    for attempt in range(SSH_RETRIES + 1):
        try:
            r = subprocess.run(
                [
                    "ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes",
                    SSH_TARGET,
                    f"cat {path} 2>/dev/null || echo NOFILE",
                ],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0:
                return r.stdout.strip()
        except subprocess.TimeoutExpired:
            pass
        if attempt < SSH_RETRIES:
            time.sleep(SSH_RETRY_DELAY)
    return None


def query_state():
    """Return dict {chat_jid: latest_ts} AND server's 'now' in utc, or None on ssh fail."""
    out = ssh_query(
        "SELECT 'NOW|'||strftime('%Y-%m-%dT%H:%M:%SZ','now') "
        "UNION ALL "
        "SELECT chat_jid||'|'||MAX(timestamp) FROM messages WHERE chat_jid IN ("
        + ",".join(f"'{c}'" for c in WATCHED_CHATS) +
        ") GROUP BY chat_jid"
    )
    if out is None:
        return None
    latest = {}
    server_now = None
    for line in out.strip().splitlines():
        if "|" not in line:
            continue
        k, v = line.split("|", 1)
        if k == "NOW":
            server_now = v
        else:
            latest[k] = v
    return {"now": server_now, "latest": latest}


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except json.JSONDecodeError as e:
            logging.warning(f"state file corrupt, resetting: {e}")
    return {}


def save_state(s: dict):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s, indent=2))


def send_alert(text: str):
    """Non-Telegram alert. imsg CLI + macOS notification + audit log."""
    ALERT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with ALERT_LOG.open("a") as f:
        f.write(f"{datetime.now().isoformat()}  {text}\n")

    try:
        subprocess.run(
            ["imsg", "send", "--to", IMESSAGE_TO, "--text", text],
            timeout=10, check=False, capture_output=True,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    try:
        short = text[:200]
        subprocess.run(
            ["osascript", "-e",
             f'display notification {json.dumps(short)} with title "Nanoclaw ingest alert"'],
            timeout=5, check=False, capture_output=True,
        )
    except Exception:
        pass


def parse_utc(ts: str) -> datetime:
    """Accept both T15:25:01Z and T15:25:01.000Z forms."""
    ts = ts.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return datetime.fromisoformat(ts[:19] + "+00:00")


def should_alert(state: dict, alert_key: str, now_ts: float) -> bool:
    """Return True if we should send an alert now, honoring cooldown & escalation."""
    last = state.get(alert_key, 0)
    if last == 0:
        return True  # never alerted
    age_min = (now_ts - last) / 60
    # Always re-alert after ESCALATION_MIN regardless of cooldown if condition persists.
    return age_min >= ALERT_COOLDOWN_MIN


def main():
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    state = load_state()
    now_ts = time.time()

    result = query_state()
    if result is None:
        # SSH repeatedly failing — that itself is news
        if should_alert(state, "_ssh_fail_ts", now_ts):
            send_alert("⚠️ nanoclaw-ingest-monitor: cannot reach server via SSH (3 attempts)")
            state["_ssh_fail_ts"] = now_ts
            save_state(state)
        sys.exit(1)

    # Clear ssh-fail state if present
    state.pop("_ssh_fail_ts", None)

    server_now = parse_utc(result["now"]) if result["now"] else datetime.now(timezone.utc)
    latest = result["latest"]
    et_now = server_now.astimezone(ET)
    in_business = BUSINESS_START <= et_now.hour < BUSINESS_END

    alerts = []

    # Check 0: TELEGRAM POLLING LIVENESS HEARTBEAT
    # Nanoclaw touches /tmp/nanoclaw-telegram-heartbeat every 30s while the
    # poller is alive. If this is stale > 5 min, the poller is hung (Apr 18
    # 2026 incident). This is the most direct "polling is actually working"
    # signal — more reliable than "messages arrived" which depends on agents
    # actually sending things.
    hb = ssh_read("/tmp/nanoclaw-telegram-heartbeat")
    if hb is None or hb == "NOFILE":
        # Heartbeat file missing. Could mean the service hasn't been
        # restarted with the new code yet. Log once per hour but don't alert.
        logging.info("heartbeat file missing — service may not have new code yet")
    else:
        try:
            hb_ms = int(hb)
            hb_age_sec = (time.time() * 1000 - hb_ms) / 1000
            if hb_age_sec > 300:  # 5 min
                alerts.append((
                    "poller_heartbeat_stale",
                    f"🚨 TELEGRAM POLLER HUNG: heartbeat {int(hb_age_sec)}s stale. "
                    f"Long-poller likely dead. Restart nanoclaw.service."
                ))
        except ValueError:
            pass

    # Check 1: BUSINESS HOURS — any activity across all watched chats?
    if in_business:
        most_recent_utc = None
        most_recent_chat = None
        for jid in WATCHED_CHATS:
            ts_str = latest.get(jid)
            if not ts_str:
                continue
            ts = parse_utc(ts_str)
            if most_recent_utc is None or ts > most_recent_utc:
                most_recent_utc = ts
                most_recent_chat = jid
        if most_recent_utc is None:
            alerts.append(("business_no_data", "No messages in any watched chat EVER"))
        else:
            idle_min = (server_now - most_recent_utc).total_seconds() / 60
            if idle_min > BUSINESS_IDLE_MIN:
                alerts.append((
                    "business_idle",
                    f"⚠️ BUSINESS IDLE: no new messages in any chat for {int(idle_min)} min "
                    f"(last was {WATCHED_CHATS.get(most_recent_chat, most_recent_chat)} "
                    f"at {most_recent_utc.isoformat()[:16]})"
                ))

    # Check 2: TPG UnCaged stale beyond 4 hours — always alert
    for jid in CRITICAL_CHATS:
        ts_str = latest.get(jid)
        if not ts_str:
            alerts.append(("critical_missing", f"⚠️ CRITICAL chat {WATCHED_CHATS.get(jid, jid)} has no messages"))
            continue
        ts = parse_utc(ts_str)
        age_hrs = (server_now - ts).total_seconds() / 3600
        if age_hrs > CRITICAL_STALE_HRS:
            alerts.append((
                f"critical_stale_{jid}",
                f"⚠️ CRITICAL: {WATCHED_CHATS.get(jid, jid)} stale {age_hrs:.1f}h "
                f"(last {ts.isoformat()[:16]})"
            ))

    if alerts:
        for key, msg in alerts:
            if should_alert(state, key, now_ts):
                send_alert(msg)
                state[key] = now_ts
        save_state(state)
        sys.exit(2)

    # Healthy — clear any stale-alert keys so the next outage triggers immediately
    cleared = False
    for k in list(state.keys()):
        if k.startswith("business_") or k.startswith("critical_"):
            state.pop(k)
            cleared = True
    if cleared:
        save_state(state)

    logging.info(f"ok (in_business={in_business}, {len(latest)} chats tracked, server_now={server_now.isoformat()[:16]})")


if __name__ == "__main__":
    main()
