#!/usr/bin/env python3
"""Smartlead Auto-Pause Breaker.

Polls campaign analytics for pilot campaigns and auto-pauses any campaign
exceeding bounce or unsubscribe thresholds. Notifies David on Telegram.

Thresholds:
  PAUSE: bounce_pct > 3.0 OR unsub_pct > 4.0
  WARN:  bounce_pct > 2.0 OR unsub_pct > 0.7
Sample floor: sent_count >= 50 (otherwise reported as below-sample, no action).

Modes:
  --dry-run    (default) Compute and print, take NO actions.
  --execute    Actually pause + alert + persist trip events.
  --reset-state  Clear breaker state file (use after manual resume).

State file: state/smartlead_breaker_state.json
  {
    "trips":   [ {ts, campaign_id, reason, metrics} ],
    "warns":   { "<campaign_id>": "YYYY-MM-DD" }   # last warn date for daily dedupe
  }

Independent of phase1_guard.py (which manages scraper docker workers).
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
LOG_DIR = ROOT / "logs"
STATE_FILE = STATE_DIR / "smartlead_breaker_state.json"
EVENTS_FILE = STATE_DIR / "smartlead_breaker_events.jsonl"

LOCAL_ENV = ROOT / ".env"
NANOCLAW_ENV = Path("/home/david/nanoclaw/.env")
# Mac fallbacks for local dry-run
MAC_LOCAL_ENV = Path("/Users/davidprice/nanoclaw/insurance-scraper/.env")
MAC_NANOCLAW_ENV = Path("/Users/davidprice/nanoclaw/.env")

BASE = "https://server.smartlead.ai/api/v1"
CHAT_ID = "577469008"

# Pilot campaigns
CAMPAIGNS = [
    (3232436, "Seq A - New Licensees PILOT"),
    (3232437, "Seq B - New Licensees PILOT"),
]

PAUSE_BOUNCE = 3.0
PAUSE_UNSUB = 4.0
WARN_BOUNCE = 2.0
WARN_UNSUB = 0.7
SAMPLE_FLOOR = 50


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def load_env_file(path: Path) -> dict:
    if not path.exists():
        return {}
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_secrets() -> dict:
    env = {}
    for p in (LOCAL_ENV, MAC_LOCAL_ENV, NANOCLAW_ENV, MAC_NANOCLAW_ENV):
        env.update({k: v for k, v in load_env_file(p).items() if k not in env or not env[k]})
    # OS env wins
    for k in ("SMARTLEAD_API_KEY", "TELEGRAM_BOT_TOKEN"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


UA = "smartlead-breaker/1.0 (+nanoclaw)"


def http_get_json(url: str, timeout: int = 30):
    req = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": UA}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def http_post_json(url: str, body: dict, timeout: int = 30):
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        text = r.read().decode("utf-8")
        try:
            return r.status, json.loads(text) if text else {}
        except Exception:
            return r.status, {"raw": text}


def fetch_analytics(campaign_id: int, api_key: str) -> dict:
    qs = urllib.parse.urlencode({"api_key": api_key})
    return http_get_json(f"{BASE}/campaigns/{campaign_id}/analytics?{qs}")


def pause_campaign(campaign_id: int, api_key: str) -> tuple[int, dict]:
    qs = urllib.parse.urlencode({"api_key": api_key})
    return http_post_json(
        f"{BASE}/campaigns/{campaign_id}/status?{qs}",
        {"status": "PAUSED"},
    )


def telegram_send(token: str, text: str) -> tuple[bool, str]:
    """Send Telegram message; returns (ok, message_id)."""
    cmd = [
        "curl", "-sS", "-m", "15", "-X", "POST",
        f"https://api.telegram.org/bot{token}/sendMessage",
        "-d", f"chat_id={CHAT_ID}",
        "-d", f"text={text}",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    out = r.stdout or ""
    if r.returncode != 0 or '"ok":true' not in out:
        return False, ""
    msg_id = ""
    try:
        j = json.loads(out)
        msg_id = str(j.get("result", {}).get("message_id", ""))
    except Exception:
        pass
    return True, msg_id


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {"trips": [], "warns": {}}
    try:
        s = json.loads(STATE_FILE.read_text())
        s.setdefault("trips", [])
        s.setdefault("warns", {})
        return s
    except Exception:
        return {"trips": [], "warns": {}}


def save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def append_event(rec: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    rec = {"ts": now_iso(), **rec}
    with EVENTS_FILE.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def safe_int(v) -> int:
    try:
        return int(v)
    except Exception:
        return 0


def evaluate(a: dict) -> dict:
    sent = safe_int(a.get("sent_count"))
    bounces = safe_int(a.get("bounce_count"))
    unsubs = safe_int(a.get("unsubscribed_count"))
    if sent <= 0:
        bounce_pct = 0.0
        unsub_pct = 0.0
    else:
        bounce_pct = bounces / sent * 100
        unsub_pct = unsubs / sent * 100
    below_sample = sent < SAMPLE_FLOOR
    decision = "ok"
    reasons = []
    if not below_sample:
        if bounce_pct > PAUSE_BOUNCE:
            decision = "pause"
            reasons.append(f"bounce_pct={bounce_pct:.2f}>{PAUSE_BOUNCE}")
        if unsub_pct > PAUSE_UNSUB:
            decision = "pause"
            reasons.append(f"unsub_pct={unsub_pct:.2f}>{PAUSE_UNSUB}")
        if decision != "pause":
            if bounce_pct > WARN_BOUNCE:
                decision = "warn"
                reasons.append(f"bounce_pct={bounce_pct:.2f}>{WARN_BOUNCE}")
            if unsub_pct > WARN_UNSUB:
                decision = "warn"
                reasons.append(f"unsub_pct={unsub_pct:.2f}>{WARN_UNSUB}")
    else:
        decision = "below_sample"
    return {
        "sent": sent,
        "bounces": bounces,
        "unsubs": unsubs,
        "bounce_pct": round(bounce_pct, 2),
        "unsub_pct": round(unsub_pct, 2),
        "below_sample": below_sample,
        "decision": decision,
        "reasons": reasons,
        "status": a.get("status"),
        "name": a.get("name"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true", help="Print only, take no action (default).")
    g.add_argument("--execute", action="store_true", help="Pause + alert + persist.")
    g.add_argument("--reset-state", action="store_true", help="Clear breaker state file.")
    args = ap.parse_args()

    if args.reset_state:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
        print(f"reset: {STATE_FILE} cleared")
        return 0

    execute = bool(args.execute)
    secrets = load_secrets()
    api_key = secrets.get("SMARTLEAD_API_KEY")
    tg_token = secrets.get("TELEGRAM_BOT_TOKEN")
    if not api_key:
        print("ERROR: SMARTLEAD_API_KEY missing", file=sys.stderr)
        return 2

    state = load_state()
    today = today_utc()
    print(f"[smartlead_breaker] mode={'execute' if execute else 'dry-run'} ts={now_iso()}")

    any_action = False
    for cid, label in CAMPAIGNS:
        try:
            a = fetch_analytics(cid, api_key)
        except Exception as e:
            print(f"  {cid} {label}: ERROR fetching analytics: {e}")
            append_event({"event": "fetch_error", "campaign_id": cid, "error": str(e)})
            continue
        m = evaluate(a)
        print(
            f"  {cid} {m['name'] or label} status={m['status']} sent={m['sent']} "
            f"bounce={m['bounces']} ({m['bounce_pct']}%) unsub={m['unsubs']} ({m['unsub_pct']}%) "
            f"-> {m['decision']} {m['reasons']}"
        )

        if m["decision"] == "pause":
            reason_str = "; ".join(m["reasons"])
            text = (
                f"🚨 Smartlead AUTO-PAUSE\n"
                f"Campaign: {m['name'] or label} ({cid})\n"
                f"Tripped: {reason_str}\n"
                f"Sent={m['sent']} Bounces={m['bounces']} ({m['bounce_pct']}%) "
                f"Unsubs={m['unsubs']} ({m['unsub_pct']}%)\n"
                f"Action: {'PAUSED' if execute else 'DRY-RUN (no action)'}"
            )
            if execute:
                if m["status"] == "PAUSED":
                    print(f"    already PAUSED; sending alert only")
                else:
                    try:
                        sc, resp = pause_campaign(cid, api_key)
                        print(f"    pause http={sc} resp={resp}")
                    except Exception as e:
                        print(f"    pause ERROR: {e}")
                        append_event({"event": "pause_error", "campaign_id": cid, "error": str(e)})
                if tg_token:
                    ok, mid = telegram_send(tg_token, text)
                    print(f"    telegram ok={ok} mid={mid}")
                state["trips"].append({
                    "ts": now_iso(),
                    "campaign_id": cid,
                    "reason": reason_str,
                    "metrics": m,
                })
                append_event({"event": "trip", "campaign_id": cid, "reason": reason_str, "metrics": m})
                save_state(state)
                any_action = True
            else:
                print(f"    [dry-run] would alert + pause: {text}")

        elif m["decision"] == "warn":
            reason_str = "; ".join(m["reasons"])
            last_warn = state["warns"].get(str(cid))
            if last_warn == today:
                print(f"    warn already sent today; skipping")
                continue
            text = (
                f"⚠️ Smartlead WARN (approaching breaker)\n"
                f"Campaign: {m['name'] or label} ({cid})\n"
                f"Watch: {reason_str}\n"
                f"Sent={m['sent']} Bounces={m['bounces']} ({m['bounce_pct']}%) "
                f"Unsubs={m['unsubs']} ({m['unsub_pct']}%)"
            )
            if execute:
                if tg_token:
                    ok, mid = telegram_send(tg_token, text)
                    print(f"    telegram ok={ok} mid={mid}")
                state["warns"][str(cid)] = today
                append_event({"event": "warn", "campaign_id": cid, "reason": reason_str, "metrics": m})
                save_state(state)
                any_action = True
            else:
                print(f"    [dry-run] would warn: {text}")

    if not any_action:
        append_event({"event": "tick", "mode": "execute" if execute else "dry-run"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
