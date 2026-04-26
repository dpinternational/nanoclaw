#!/usr/bin/env python3
"""
System Health Check + Alerting for NanoClaw.

Modes:
  --mode=checks     run all checks, alert to Daily Email Ops on failures (deduped)
  --mode=heartbeat  post morning status summary
  --mode=test       dry-run; print what would alert, do not post
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = "/home/david/nanoclaw"
DB_PATH = f"{ROOT}/store/messages.db"
ALERTS_DB = f"{ROOT}/store/health-alerts.db"
STATE_FILE = f"{ROOT}/store/health-last-state.json"
SESSIONS_DIR = f"{ROOT}/data/sessions"
CR_ARCHIVE = f"{ROOT}/data/cr-full-archive.json"
DIGEST_LOG = f"{ROOT}/logs/digest.log"
ENV_FILE = f"{ROOT}/.env"

DAILY_EMAIL_OPS_CHAT_ID = -5270945980
OBSERVATION_MODE_GROUPS = {"tg:-1002362081030"}  # TPG UnCaged — skip alerts

# ET offset: -4 (EDT, April). Use static for now.
ET = timezone(timedelta(hours=-4))
UTC = timezone.utc

DEDUPE_WINDOW_HOURS = 4


def load_bot_token():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if token:
        return token
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return None


def tg_send(text, chat_id=DAILY_EMAIL_OPS_CHAT_ID):
    token = load_bot_token()
    if not token:
        return None, "no token"
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode()
    try:
        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode())
            if body.get("ok"):
                return body["result"].get("message_id"), None
            return None, str(body)
    except Exception as e:
        return None, str(e)


def now_utc():
    return datetime.now(UTC)


def parse_ts(s):
    """Parse ISO timestamp; assume UTC if no tz."""
    if not s:
        return None
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except Exception:
        return None


# ============ DEDUPE ============
def ensure_alerts_db():
    con = sqlite3.connect(ALERTS_DB)
    con.execute("""CREATE TABLE IF NOT EXISTS alerts_fired(
        alert_key TEXT PRIMARY KEY,
        fired_at TEXT,
        severity TEXT
    )""")
    con.commit()
    con.close()


SEVERITY_RANK = {"info": 0, "minor": 1, "degraded": 2, "failure": 3, "critical": 4}


def should_fire(alert_key, severity):
    ensure_alerts_db()
    con = sqlite3.connect(ALERTS_DB)
    row = con.execute(
        "SELECT fired_at, severity FROM alerts_fired WHERE alert_key=?",
        (alert_key,),
    ).fetchone()
    if row is None:
        con.close()
        return True
    fired_at = parse_ts(row[0])
    prev_sev = row[1] or "failure"
    con.close()
    if fired_at is None:
        return True
    age_h = (now_utc() - fired_at).total_seconds() / 3600.0
    if age_h >= DEDUPE_WINDOW_HOURS:
        return True
    # severity escalation
    if SEVERITY_RANK.get(severity, 0) > SEVERITY_RANK.get(prev_sev, 0):
        return True
    return False


def record_fired(alert_key, severity):
    ensure_alerts_db()
    con = sqlite3.connect(ALERTS_DB)
    con.execute(
        "INSERT OR REPLACE INTO alerts_fired(alert_key, fired_at, severity) VALUES (?,?,?)",
        (alert_key, now_utc().isoformat(), severity),
    )
    con.commit()
    con.close()


def alert(alert_key, severity, issue, details, action, dry_run=False):
    text = (
        f"🚨 SYSTEM HEALTH ALERT\n\n"
        f"ISSUE: {issue}\n"
        f"DETAILS: {details}\n"
        f"ACTION: {action}"
    )
    if dry_run:
        print(f"[DRY-RUN would alert] key={alert_key} sev={severity}\n{text}\n---")
        return None
    if not should_fire(alert_key, severity):
        print(f"[deduped] {alert_key} ({severity})")
        return None
    msg_id, err = tg_send(text)
    if err:
        print(f"[alert-send-failed] {alert_key}: {err}")
        return None
    record_fired(alert_key, severity)
    print(f"[alerted] {alert_key} sev={severity} msg_id={msg_id}")
    return msg_id


# ============ CHECK A: NanoClaw Process ============
def check_a_nanoclaw():
    results = []
    r = subprocess.run(
        ["systemctl", "is-active", "nanoclaw.service"],
        capture_output=True, text=True,
    )
    active = r.stdout.strip() == "active"
    results.append(("nanoclaw.service active", active, r.stdout.strip()))

    pg = subprocess.run(
        ["pgrep", "-f", "node /home/david/nanoclaw/dist/index.js"],
        capture_output=True, text=True,
    )
    pids = [p for p in pg.stdout.strip().split("\n") if p]
    node_running = len(pids) > 0
    results.append(("node process running", node_running, ",".join(pids)))

    # Process start time (etime since)
    start_epoch = None
    if pids:
        ps = subprocess.run(
            ["ps", "-o", "lstart=", "-p", pids[0]],
            capture_output=True, text=True,
        )
        try:
            start_epoch = datetime.strptime(ps.stdout.strip(), "%a %b %d %H:%M:%S %Y")
            # ps lstart is local time; convert to UTC via timestamp roundtrip
            start_epoch = start_epoch.replace(tzinfo=UTC)  # approximation; server tz often UTC
        except Exception:
            start_epoch = None

    # Unexpected restart detection
    unexpected_restart = False
    last_known_start = None
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                state = json.load(f)
            last_known_start = parse_ts(state.get("nanoclaw_start"))
    except Exception:
        state = {}
    if start_epoch:
        age_h = (now_utc() - start_epoch).total_seconds() / 3600.0
        if last_known_start and start_epoch != last_known_start and age_h < 6:
            unexpected_restart = True
        # persist current
        try:
            with open(STATE_FILE, "w") as f:
                json.dump({"nanoclaw_start": start_epoch.isoformat()}, f)
        except Exception:
            pass
    results.append(("recent unexpected restart", not unexpected_restart,
                    f"start={start_epoch}, last_known={last_known_start}"))

    return {
        "active": active,
        "node_running": node_running,
        "start_time": start_epoch,
        "unexpected_restart": unexpected_restart,
        "results": results,
    }


# ============ CHECK B: Group Silence / Orphaned Triggers ============
def active_telegram_groups():
    con = sqlite3.connect(DB_PATH)
    rows = con.execute(
        "SELECT jid, name, folder FROM registered_groups WHERE jid LIKE 'tg:%'"
    ).fetchall()
    con.close()
    return rows


def check_b_orphaned_triggers():
    orphans = []
    con = sqlite3.connect(DB_PATH)
    groups = active_telegram_groups()
    cutoff_72h = now_utc() - timedelta(hours=72)
    for jid, name, folder in groups:
        if jid in OBSERVATION_MODE_GROUPS:
            continue
        rows = con.execute(
            """SELECT timestamp, sender, sender_name, content, is_from_me, is_bot_message
               FROM messages WHERE chat_jid=?
               ORDER BY timestamp DESC LIMIT 20""",
            (jid,),
        ).fetchall()
        if not rows:
            continue
        latest_ts = parse_ts(rows[0][0])
        if latest_ts and latest_ts < cutoff_72h:
            continue  # quiet group
        # Find latest human message and whether bot replied after it
        latest_human = None
        for ts, sender, sname, content, ifm, ibm in rows:
            tsd = parse_ts(ts)
            if tsd is None:
                continue
            is_bot = bool(ibm) or (sender and "8656467065" in str(sender))
            if is_bot:
                continue
            # david's own messages via is_from_me are still "human" triggers; but
            # we care about @Andy mentions. Whoever sent it, treat as human.
            content = content or ""
            # Strict: require literal '@Andy' (case-insensitive) as trigger.
            if "@andy" in content.lower():
                latest_human = (tsd, sender, sname, content, ifm)
                break
        if not latest_human:
            continue
        h_ts = latest_human[0]
        # any bot message after h_ts?
        replied = False
        for ts, sender, sname, content, ifm, ibm in rows:
            tsd = parse_ts(ts)
            if tsd is None:
                continue
            is_bot = bool(ibm) or (sender and "8656467065" in str(sender))
            if is_bot and tsd > h_ts:
                replied = True
                break
        age_min = (now_utc() - h_ts).total_seconds() / 60.0
        if not replied and age_min > 15:
            orphans.append({
                "jid": jid, "name": name, "folder": folder,
                "age_min": age_min, "content": latest_human[3][:120],
            })
    con.close()
    return orphans


# ============ CHECK C: Session Integrity ============
def check_c_session_integrity():
    con = sqlite3.connect(DB_PATH)
    groups = active_telegram_groups()
    sess_rows = dict(con.execute("SELECT group_folder, session_id FROM sessions").fetchall())

    silent_fail_risk = []  # recent human activity but no session row
    cutoff = now_utc() - timedelta(hours=24)
    for jid, name, folder in groups:
        if jid in OBSERVATION_MODE_GROUPS:
            continue
        if folder in sess_rows:
            continue
        # recent human messages?
        r = con.execute(
            """SELECT timestamp FROM messages
               WHERE chat_jid=? AND COALESCE(is_bot_message,0)=0
               ORDER BY timestamp DESC LIMIT 1""",
            (jid,),
        ).fetchone()
        if r:
            tsd = parse_ts(r[0])
            if tsd and tsd > cutoff:
                silent_fail_risk.append({
                    "jid": jid, "name": name, "folder": folder,
                    "last_human": tsd.isoformat(),
                })
    con.close()

    # orphaned sessions: row exists but no session directory at all
    orphaned = []
    for folder, sid in sess_rows.items():
        fdir = os.path.join(SESSIONS_DIR, folder)
        if not os.path.isdir(fdir):
            orphaned.append({"folder": folder, "session_id": sid, "reason": "no session dir"})

    return {"silent_fail_risk": silent_fail_risk, "orphaned_sessions": orphaned}


# ============ CHECK D: Dependent Services / Crons ============
def check_d_dependents():
    res = {}
    r = subprocess.run(
        ["systemctl", "is-active", "email-approval-bot.service"],
        capture_output=True, text=True,
    )
    res["email_approval_bot_active"] = r.stdout.strip() == "active"

    def age_hours(path):
        if not os.path.exists(path):
            return None
        return (time.time() - os.path.getmtime(path)) / 3600.0

    cr_age = age_hours(CR_ARCHIVE)
    res["cr_archive_age_h"] = cr_age
    res["cr_archive_ok"] = cr_age is not None and cr_age < 25

    dg_age = age_hours(DIGEST_LOG)
    res["digest_age_h"] = dg_age
    res["digest_ok"] = dg_age is not None and dg_age < 25
    return res


# ============ HEARTBEAT ============
def compose_heartbeat():
    now_et = datetime.now(ET)
    date_str = now_et.strftime("%b %-d")

    a = check_a_nanoclaw()
    d = check_d_dependents()
    orphans = check_b_orphaned_triggers()
    sess = check_c_session_integrity()

    # uptime
    uptime = "?"
    if a["start_time"]:
        hrs = (now_utc() - a["start_time"]).total_seconds() / 3600.0
        uptime = f"{hrs:.1f}h"

    nanoclaw_sym = "✓" if (a["active"] and a["node_running"]) else "✗"
    approval_sym = "✓" if d["email_approval_bot_active"] else "✗"
    cr_sym = "✓" if d["cr_archive_ok"] else "✗"
    cr_age_txt = f"{d['cr_archive_age_h']:.1f}h ago" if d["cr_archive_age_h"] is not None else "missing"
    digest_sym = "✓" if d["digest_ok"] else "✗"
    digest_age_txt = f"{d['digest_age_h']:.1f}h ago" if d["digest_age_h"] is not None else "missing"

    # groups responsive
    groups = [g for g in active_telegram_groups() if g[0] not in OBSERVATION_MODE_GROUPS]
    total = len(groups)
    responsive = total - len(orphans)

    lines = [
        f"📊 Morning System Health — {date_str}",
        f"NanoClaw: {nanoclaw_sym} (uptime {uptime})",
        f"Approval bot: {approval_sym}",
        f"CR archive: {cr_sym} ({cr_age_txt})",
        f"TPG digest: {digest_sym} ({digest_age_txt})",
        f"Groups responsive: {responsive}/{total}",
    ]
    if orphans:
        lines.append("⚠ Orphaned triggers: " + ", ".join(o["name"] for o in orphans))
    if sess["silent_fail_risk"]:
        lines.append("⚠ Silent-fail risk (no session): " + ", ".join(
            s["name"] for s in sess["silent_fail_risk"]))
    return "\n".join(lines)


# ============ MAIN ============
def run_checks(dry_run=False):
    fired = []

    # Check A
    a = check_a_nanoclaw()
    if not a["active"]:
        fired.append(alert(
            "nanoclaw_service_down", "critical",
            "nanoclaw.service is not active",
            "systemctl is-active returned non-active",
            "Run: sudo systemctl status nanoclaw.service && sudo systemctl restart nanoclaw.service",
            dry_run,
        ))
    if not a["node_running"]:
        fired.append(alert(
            "nanoclaw_process_missing", "critical",
            "NanoClaw node process not running",
            "pgrep found no matching node /home/david/nanoclaw/dist/index.js process",
            "Check systemd journal: journalctl -u nanoclaw.service -n 100",
            dry_run,
        ))
    if a["unexpected_restart"]:
        fired.append(alert(
            "nanoclaw_unexpected_restart", "degraded",
            "NanoClaw restarted within last 6h",
            f"Process start changed since last check: start={a['start_time']}",
            "Review journalctl -u nanoclaw.service --since '6 hours ago'",
            dry_run,
        ))

    # Check B
    for o in check_b_orphaned_triggers():
        key = f"orphan_trigger::{o['jid']}"
        fired.append(alert(
            key, "failure",
            f"Orphaned @Andy trigger in {o['name']}",
            f"Human message mentioning Andy is {o['age_min']:.0f}min old with no bot reply. Content: {o['content']!r}",
            f"Check nanoclaw logs for {o['folder']}; verify session routing. journalctl -u nanoclaw.service | grep -i {o['folder']}",
            dry_run,
        ))

    # Check C
    c = check_c_session_integrity()
    for s in c["silent_fail_risk"]:
        key = f"silent_fail_risk::{s['jid']}"
        fired.append(alert(
            key, "degraded",
            f"Silent-fail risk: {s['name']} has recent human activity but no session row",
            f"folder={s['folder']} last_human={s['last_human']}",
            f"Inspect sessions table and recent messages for {s['folder']}. This mirrors Apr 15 pattern.",
            dry_run,
        ))
    for o in c["orphaned_sessions"]:
        key = f"orphan_session::{o['folder']}"
        fired.append(alert(
            key, "minor",
            f"Orphaned session row for {o['folder']}",
            f"session_id={o['session_id']} reason={o['reason']}",
            f"Verify /home/david/nanoclaw/data/sessions/{o['folder']}/ or clean stale row.",
            dry_run,
        )) if False else None  # minor = log only
        print(f"[minor-log] orphan_session {o['folder']}: {o['reason']}")

    # Check D
    d = check_d_dependents()
    if not d["email_approval_bot_active"]:
        fired.append(alert(
            "email_approval_bot_down", "failure",
            "email-approval-bot.service is not active",
            "systemctl is-active returned non-active",
            "sudo systemctl status email-approval-bot.service && sudo systemctl restart email-approval-bot.service",
            dry_run,
        ))
    if not d["cr_archive_ok"]:
        age_txt = f"{d['cr_archive_age_h']:.1f}h" if d["cr_archive_age_h"] is not None else "missing"
        fired.append(alert(
            "cr_archive_stale", "degraded",
            "CR archive stale / missing",
            f"cr-full-archive.json age = {age_txt} (expected <25h)",
            "Check cron 'CR Archive Sync' logs: tail /home/david/nanoclaw/logs/cr-archive.log",
            dry_run,
        ))
    if not d["digest_ok"]:
        age_txt = f"{d['digest_age_h']:.1f}h" if d["digest_age_h"] is not None else "missing"
        fired.append(alert(
            "tpg_digest_stale", "degraded",
            "TPG daily digest log stale",
            f"digest.log age = {age_txt} (expected <25h)",
            "Check cron 'TPG Daily Digest' logs: tail /home/david/nanoclaw/logs/digest.log",
            dry_run,
        ))

    fired = [f for f in fired if f is not None]
    print(f"\nSUMMARY: {len(fired)} alerts fired (dry_run={dry_run})")
    return fired


def run_heartbeat(dry_run=False):
    text = compose_heartbeat()
    print(text)
    if dry_run:
        return None
    msg_id, err = tg_send(text)
    if err:
        print(f"[heartbeat-FAILED] {err}", file=sys.stderr)
        # fall back to log
        try:
            with open(f"{ROOT}/logs/health-check.log", "a") as f:
                f.write(f"\n[heartbeat-failed {now_utc().isoformat()}] {err}\n{text}\n")
        except Exception:
            pass
        sys.exit(1)
    print(f"heartbeat posted msg_id={msg_id}")
    return msg_id


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["checks", "heartbeat", "test"], required=True)
    args = ap.parse_args()

    print(f"=== system-health-check mode={args.mode} at {now_utc().isoformat()} ===")
    if args.mode == "test":
        run_checks(dry_run=True)
        print("\n--- heartbeat preview ---")
        print(compose_heartbeat())
    elif args.mode == "checks":
        run_checks(dry_run=False)
    elif args.mode == "heartbeat":
        run_heartbeat(dry_run=False)


if __name__ == "__main__":
    main()
