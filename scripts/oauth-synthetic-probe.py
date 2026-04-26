#!/usr/bin/env python3
"""
OAuth synthetic probe — runs every 15 min via launchd.

Uses curl for HTTP (macOS system python has SSL cert issues with Google endpoints).
Tests gmail/drive/calendar/sheets. Alerts Telegram david@577469008 on
state transitions (OK→FAIL) or every 4 hours if still failing.
"""
import os, sys, json, subprocess, pathlib, datetime, shlex
from typing import Optional, Tuple, Dict

HOME = pathlib.Path.home()
TOKEN_PATH = HOME / ".hermes" / "google_token.json"
STATE_PATH = HOME / ".hermes" / "oauth_probe_state.json"
LOG_PATH = HOME / "nanoclaw" / "logs" / "oauth-probe.log"
DOTENV = HOME / "nanoclaw" / ".env"

TELEGRAM_CHAT = "577469008"
REALERT_HOURS = 4

# ---------- util ----------

def log(msg: str):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(f"[{ts}] {msg}\n")

def read_bot_token() -> Optional[str]:
    if not DOTENV.exists(): return None
    for line in DOTENV.read_text().splitlines():
        if line.startswith("TELEGRAM_BOT_TOKEN="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None

def curl_post(url: str, data: Dict, timeout: int = 15) -> Tuple[int, str]:
    """POST form-encoded. Returns (http_code, body)."""
    form_args = []
    for k, v in data.items():
        form_args += ["-d", f"{k}={v}"]
    cmd = ["curl", "-s", "-w", "\n__HTTP__:%{http_code}", "--max-time", str(timeout),
           "-X", "POST", url] + form_args
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        out = r.stdout
        code = 0
        if "\n__HTTP__:" in out:
            body, _, codepart = out.rpartition("\n__HTTP__:")
            out = body
            try: code = int(codepart.strip())
            except: pass
        return code, out
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"

def curl_get(url: str, access_token: str, timeout: int = 15) -> Tuple[int, str]:
    cmd = ["curl", "-s", "-w", "\n__HTTP__:%{http_code}", "--max-time", str(timeout),
           "-H", f"Authorization: Bearer {access_token}", url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        out = r.stdout
        code = 0
        if "\n__HTTP__:" in out:
            body, _, codepart = out.rpartition("\n__HTTP__:")
            out = body
            try: code = int(codepart.strip())
            except: pass
        return code, out
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"

def telegram_send(text: str):
    token = read_bot_token()
    if not token:
        log("no telegram token, skipping alert")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    code, body = curl_post(url, {"chat_id": TELEGRAM_CHAT, "text": text, "parse_mode": "Markdown"})
    if code == 200:
        log(f"telegram alert sent: {text[:80]}")
    else:
        log(f"telegram send failed: code={code} body={body[:200]}")

# ---------- token ----------

def load_token() -> Dict:
    return json.loads(TOKEN_PATH.read_text())

def save_token(tok: Dict):
    TOKEN_PATH.write_text(json.dumps(tok, indent=2))

def refresh_access_token(tok: Dict) -> Tuple[bool, str]:
    code, body = curl_post("https://oauth2.googleapis.com/token", {
        "client_id": tok["client_id"],
        "client_secret": tok["client_secret"],
        "refresh_token": tok["refresh_token"],
        "grant_type": "refresh_token",
    })
    if code != 200:
        return False, f"HTTP {code}: {body[:300]}"
    try:
        r = json.loads(body)
        tok["token"] = r["access_token"]
        save_token(tok)
        return True, "refreshed"
    except Exception as e:
        return False, f"parse: {e} body={body[:200]}"

# ---------- probes ----------

def probe_gmail(access_token: str) -> Tuple[bool, str]:
    code, body = curl_get("https://gmail.googleapis.com/gmail/v1/users/me/profile", access_token)
    if code == 200:
        try:
            d = json.loads(body)
            return True, f"{d.get('emailAddress')} msgs={d.get('messagesTotal')}"
        except: pass
    return False, f"status={code} body={body[:200]}"

def probe_drive(access_token: str) -> Tuple[bool, str]:
    code, body = curl_get("https://www.googleapis.com/drive/v3/about?fields=user,storageQuota", access_token)
    if code == 200:
        try:
            d = json.loads(body)
            return True, f"{d.get('user',{}).get('emailAddress')} usage={d.get('storageQuota',{}).get('usage','?')}"
        except: pass
    return False, f"status={code} body={body[:200]}"

def probe_calendar(access_token: str) -> Tuple[bool, str]:
    code, body = curl_get("https://www.googleapis.com/calendar/v3/users/me/calendarList?maxResults=1", access_token)
    if code == 200:
        try:
            d = json.loads(body)
            return True, f"calendars={len(d.get('items',[]))}"
        except: pass
    return False, f"status={code} body={body[:200]}"

def probe_sheets(access_token: str) -> Tuple[bool, str]:
    code, body = curl_get(
        "https://www.googleapis.com/drive/v3/files?q=mimeType%3D%27application%2Fvnd.google-apps.spreadsheet%27&pageSize=1&fields=files(id,name)",
        access_token,
    )
    if code == 200:
        return True, "sheets scope ok"
    return False, f"status={code} body={body[:200]}"

# ---------- state ----------

def load_state() -> Dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"last_status": "unknown", "last_alert_ts": None, "consecutive_fails": 0}

def save_state(state: Dict):
    STATE_PATH.write_text(json.dumps(state, indent=2))

def should_alert(state: Dict, currently_failing: bool) -> bool:
    if not currently_failing:
        return False
    last = state.get("last_alert_ts")
    if last is None:
        return True
    last_dt = datetime.datetime.fromisoformat(last)
    return (datetime.datetime.now() - last_dt).total_seconds() >= REALERT_HOURS * 3600

# ---------- main ----------

def main() -> int:
    try:
        tok = load_token()
    except Exception as e:
        log(f"CANNOT LOAD TOKEN: {e}")
        telegram_send(f"🚨 OAuth probe: cannot read token file. {e}")
        return 1

    ok, msg = refresh_access_token(tok)
    if not ok:
        log(f"REFRESH FAILED: {msg}")
        state = load_state()
        if should_alert(state, True):
            telegram_send(
                "🚨 *OAuth refresh failed* on Mac. Reauth required.\n"
                f"`{msg[:300]}`"
            )
            state["last_alert_ts"] = datetime.datetime.now().isoformat()
        state["last_status"] = "refresh_failed"
        state["consecutive_fails"] = state.get("consecutive_fails", 0) + 1
        save_state(state)
        print("OAUTH_PROBE: REFRESH_FAILED")
        return 1

    tok = load_token()
    access = tok["token"]
    probes = {"gmail": probe_gmail, "drive": probe_drive, "calendar": probe_calendar, "sheets": probe_sheets}
    results, failures = {}, []
    for name, fn in probes.items():
        ok, detail = fn(access)
        results[name] = {"ok": ok, "detail": detail}
        if not ok:
            failures.append(f"{name}: {detail}")

    state = load_state()
    currently_failing = bool(failures)
    was_failing = state.get("last_status", "ok") != "ok"

    if currently_failing and should_alert(state, True):
        lines = ["🚨 *OAuth synthetic probe failed*"]
        for f in failures: lines.append(f"• `{f[:200]}`")
        telegram_send("\n".join(lines))
        state["last_alert_ts"] = datetime.datetime.now().isoformat()

    if (not currently_failing) and was_failing:
        summary = " · ".join(f"{k}:ok" for k in results)
        telegram_send(f"✅ *OAuth probe recovered.*\n{summary}")

    state["last_status"] = "ok" if not currently_failing else "failing"
    state["consecutive_fails"] = 0 if not currently_failing else state.get("consecutive_fails", 0) + 1
    state["last_run"] = datetime.datetime.now().isoformat()
    save_state(state)

    summary = " · ".join(f"{k}:{'ok' if v['ok'] else 'FAIL'}" for k, v in results.items())
    log(f"probe result: {summary}")
    print("OAUTH_PROBE:", summary)
    return 0 if not currently_failing else 1

if __name__ == "__main__":
    sys.exit(main())
