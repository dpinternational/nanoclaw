#!/usr/bin/env python3
"""
ZeroBounce Credit Watchdog

Polls https://api.zerobounce.net/v2/getcredits and alerts David on Telegram
when credits run low.

Thresholds:
  - credits <  500  : ALERT every run (until refilled)
  - credits < 1000  : WARN once per UTC day
  - credits >= 1000 : silent (still logs)

State file (so we don't spam) : /home/david/insurance-scraper/state/zb_credit_watchdog.json
Log file (always appends)     : /home/david/insurance-scraper/logs/zb_credit_watchdog.log

Env resolution (first hit wins):
  ZEROBOUNCE_API_KEY:
    1. /Users/davidprice/nanoclaw/.env       (Mac dev)
    2. /home/david/insurance-scraper/.env    (prod, source of truth)
    3. /home/david/nanoclaw/.env             (prod fallback)
    4. process env

  TELEGRAM_BOT_TOKEN:
    1. /Users/davidprice/nanoclaw/.env       (Mac dev)
    2. /home/david/nanoclaw/.env             (prod)
    3. process env

Always exits 0 — never break the cron run.

Cron (user david):
    0 9 * * * cd /home/david/nanoclaw && /usr/bin/python3 scripts/zerobounce-credit-watchdog.py >> logs/zb-watchdog.log 2>&1
"""

from __future__ import annotations

import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CHAT_ID = "577469008"

ALERT_THRESHOLD = 500
WARN_THRESHOLD = 1000

ZB_ENV_PATHS = [
    "/Users/davidprice/nanoclaw/.env",
    "/home/david/insurance-scraper/.env",
    "/home/david/nanoclaw/.env",
]
TG_ENV_PATHS = [
    "/Users/davidprice/nanoclaw/.env",
    "/home/david/nanoclaw/.env",
]

# Prefer the prod state/log dirs when they exist (server). Fall back to
# repo-local logs on Mac so local dry-runs don't fail.
def _resolve_dir(prod_path: str, local_fallback: str) -> Path:
    p = Path(prod_path)
    if p.parent.exists():
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except PermissionError:
            pass
    fb = Path(local_fallback)
    fb.mkdir(parents=True, exist_ok=True)
    return fb


STATE_FILE = _resolve_dir(
    "/home/david/insurance-scraper/state",
    str(Path(__file__).resolve().parent.parent / "logs"),
) / "zb_credit_watchdog.json"

LOG_FILE = _resolve_dir(
    "/home/david/insurance-scraper/logs",
    str(Path(__file__).resolve().parent.parent / "logs"),
) / "zb_credit_watchdog.log"


def read_env_value(paths: list[str], key: str) -> str | None:
    for p in paths:
        try:
            with open(p, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith(key + "="):
                        v = line[len(key) + 1:].strip()
                        if (v.startswith('"') and v.endswith('"')) or (
                            v.startswith("'") and v.endswith("'")
                        ):
                            v = v[1:-1]
                        if v:
                            return v
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return os.environ.get(key)


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as e:
        print(f"[{ts}] WARN: could not write log: {e}")


def load_state() -> dict:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}
    except Exception as e:
        log(f"WARN: state load failed: {e}")
        return {}


def save_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)
    except Exception as e:
        log(f"WARN: state save failed: {e}")


def fetch_credits(api_key: str) -> int | None:
    url = "https://api.zerobounce.net/v2/getcredits?api_key=" + urllib.parse.quote(api_key)
    req = urllib.request.Request(url, headers={"User-Agent": "zb-credit-watchdog/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        # API returns {"Credits":"5739"} (string). -1 / -2 indicate errors.
        raw = data.get("Credits", data.get("credits"))
        if raw is None:
            log(f"ERROR: unexpected response: {data}")
            return None
        n = int(raw)
        if n < 0:
            log(f"ERROR: ZeroBounce reported negative credits ({n}); auth/api issue")
            return None
        return n
    except Exception as e:
        log(f"ERROR: getcredits failed: {e}")
        return None


def send_telegram(token: str, text: str) -> bool:
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": "true",
    }).encode("utf-8")
    try:
        with urllib.request.urlopen(url, data=payload, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if not body.get("ok"):
                log(f"ERROR: telegram returned not-ok: {body}")
                return False
            return True
    except Exception as e:
        log(f"ERROR: telegram send failed: {e}")
        return False


def main() -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    api_key = read_env_value(ZB_ENV_PATHS, "ZEROBOUNCE_API_KEY")
    if not api_key:
        log("ERROR: no ZEROBOUNCE_API_KEY found in any env file; exiting 0")
        return 0

    credits = fetch_credits(api_key)
    if credits is None:
        log("ERROR: could not retrieve credit count; exiting 0")
        return 0

    log(f"credits={credits}")

    if credits >= WARN_THRESHOLD:
        # Silent path. Done.
        return 0

    severity = "alert" if credits < ALERT_THRESHOLD else "warn"
    emoji = "🚨" if severity == "alert" else "⚠️"

    state = load_state()
    last_alert = state.get("last_alert_date")
    last_warn = state.get("last_warn_date")

    should_send = False
    if severity == "alert":
        # ALERT — every run while below threshold (still capped to once per run).
        should_send = True
    else:  # warn
        if last_warn != today:
            should_send = True

    if not should_send:
        log(f"suppressed {severity} (already sent today: warn={last_warn} alert={last_alert})")
        return 0

    token = read_env_value(TG_ENV_PATHS, "TELEGRAM_BOT_TOKEN")
    if not token:
        log("ERROR: no TELEGRAM_BOT_TOKEN found; cannot send notification; exiting 0")
        return 0

    msg = (
        f"{emoji} ZeroBounce credits: {credits} — "
        f"refill at https://app.zerobounce.net/billing"
    )
    ok = send_telegram(token, msg)
    if ok:
        log(f"sent {severity} notification (credits={credits})")
        if severity == "alert":
            state["last_alert_date"] = today
        else:
            state["last_warn_date"] = today
        state["last_credits"] = credits
        state["last_check"] = datetime.now(timezone.utc).isoformat()
        save_state(state)
    else:
        log(f"send failed; will retry next run")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:
        # Final safety net: never crash cron.
        try:
            log(f"FATAL (caught): {e!r}")
        except Exception:
            pass
        sys.exit(0)
