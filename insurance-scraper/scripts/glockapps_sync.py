#!/usr/bin/env python3
"""
glockapps_sync.py

Polls the GlockApps API every 30 minutes (cron) for the configured project,
detects new completed inbox-placement tests, parses placement + auth + blacklist
data, persists to JSONL + Supabase, and fires Telegram alerts on degraded
deliverability or all-clean results.

Tests are produced by sending mail to the project's autoTestEmail seed (see
glockapps_seed_inject.py). The /test/start API is blocked on this plan tier.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
EVENTS_PATH = STATE_DIR / "glockapps_sync_events.jsonl"
SNAPSHOT_PATH = STATE_DIR / "glockapps_sync_snapshot.json"
RESULTS_PATH = STATE_DIR / "glockapps_results.jsonl"
LAST_SEEN_PATH = STATE_DIR / "glockapps_last_seen.json"

LOCAL_ENV = ROOT / ".env"
MAC_LOCAL_ENV = Path("/Users/davidprice/nanoclaw/insurance-scraper/.env")
NANOCLAW_ENV = Path("/home/david/nanoclaw/.env")
MAC_NANOCLAW_ENV = Path("/Users/davidprice/nanoclaw/.env")

TELEGRAM_CHAT_ID = "577469008"
GLOCKAPPS_BASE_DEFAULT = "https://api.glockapps.com/gateway/spamtest-v2/api"
INBOX_DEGRADED_THRESHOLD = 80.0
INBOX_CLEAN_THRESHOLD = 90.0
UA = "glockapps-sync/2.0 (+nanoclaw)"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_event(rec: dict) -> None:
    rec = {"ts": now_iso(), **rec}
    with EVENTS_PATH.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec))


def load_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_cfg() -> dict:
    env: dict[str, str] = {}
    for p in (LOCAL_ENV, MAC_LOCAL_ENV, NANOCLAW_ENV, MAC_NANOCLAW_ENV):
        for k, v in load_env_file(p).items():
            if k not in env or not env[k]:
                env[k] = v
    for k in ("GLOCKAPPS_API_KEY", "GLOCKAPPS_API_BASE",
              "GLOCKAPPS_API_ENDPOINT", "GLOCKAPPS_PROJECT_ID",
              "SUPABASE_URL", "SUPABASE_KEY",
              "SUPABASE_SERVICE_ROLE_KEY", "TELEGRAM_BOT_TOKEN"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    if not env.get("SUPABASE_SERVICE_ROLE_KEY") and env.get("SUPABASE_KEY"):
        env["SUPABASE_SERVICE_ROLE_KEY"] = env["SUPABASE_KEY"]
    return {
        "api_key": env.get("GLOCKAPPS_API_KEY", ""),
        "base": env.get("GLOCKAPPS_API_BASE", GLOCKAPPS_BASE_DEFAULT),
        "endpoint": env.get("GLOCKAPPS_API_ENDPOINT", ""),
        "project_id": env.get("GLOCKAPPS_PROJECT_ID", ""),
        "sb_url": env.get("SUPABASE_URL", ""),
        "sb_key": env.get("SUPABASE_SERVICE_ROLE_KEY") or env.get("SUPABASE_KEY", ""),
        "tg_token": env.get("TELEGRAM_BOT_TOKEN", ""),
    }


def _http(method: str, url: str, headers: dict | None = None,
          body: dict | list | None = None,
          timeout: int = 30) -> tuple[int, dict | list | str, dict]:
    h = {"Accept": "application/json", "User-Agent": UA}
    if headers:
        h.update(headers)
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read().decode("utf-8")
            try:
                parsed = json.loads(text) if text else {}
            except json.JSONDecodeError:
                parsed = text
            return r.status, parsed, dict(r.headers)
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(text) if text else {"error": str(e)}
        except json.JSONDecodeError:
            parsed = {"error": text[:800]}
        return e.code, parsed, dict(e.headers or {})


def ga_get(base: str, path: str, api_key: str,
           extra: dict | None = None) -> tuple[int, dict | list | str]:
    base = base.rstrip("/")
    qs = {"apiKey": api_key}
    if extra:
        qs.update(extra)
    url = f"{base}/{path.lstrip('/')}?{urllib.parse.urlencode(qs)}"
    status, body, _ = _http("GET", url)
    return status, body


# ---------------------------------------------------------------------------
# Last-seen tracking
# ---------------------------------------------------------------------------

def load_last_seen() -> dict:
    if not LAST_SEEN_PATH.exists():
        return {"test_ids": []}
    try:
        return json.loads(LAST_SEEN_PATH.read_text())
    except Exception:
        return {"test_ids": []}


def save_last_seen(state: dict) -> None:
    # Keep only last 500 ids
    ids = state.get("test_ids", [])
    state["test_ids"] = ids[-500:]
    state["updated_at"] = now_iso()
    LAST_SEEN_PATH.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# Result parsing
# ---------------------------------------------------------------------------

def _f(v) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _b(v) -> bool | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    s = str(v).strip().lower()
    if s in ("pass", "passed", "true", "ok", "yes", "1"):
        return True
    if s in ("fail", "failed", "false", "no", "0"):
        return False
    return None


def parse_test(test_id: str, project_id: str, raw: dict) -> dict:
    """Best-effort parser that handles the common GlockApps response shapes."""
    d = raw if isinstance(raw, dict) else {}
    # Some endpoints return {data: {...}} envelopes
    if "data" in d and isinstance(d["data"], dict) and "inbox" not in d:
        d = {**d, **d["data"]}

    inbox_pct = _f(d.get("inbox") or d.get("inboxPct") or d.get("inbox_percent"))
    spam_pct = _f(d.get("spam") or d.get("spamPct") or d.get("spam_percent"))
    missing_pct = _f(d.get("missing") or d.get("missingPct") or d.get("missing_percent"))
    promo_pct = _f(d.get("promotions") or d.get("promo") or d.get("promoPct"))

    # Authentication
    auth = d.get("authentication") or d.get("auth") or {}
    if isinstance(auth, dict):
        spf = _b(auth.get("spf") or auth.get("SPF"))
        dkim = _b(auth.get("dkim") or auth.get("DKIM"))
        dmarc = _b(auth.get("dmarc") or auth.get("DMARC"))
    else:
        spf = dkim = dmarc = None
    if spf is None:
        spf = _b(d.get("spf"))
    if dkim is None:
        dkim = _b(d.get("dkim"))
    if dmarc is None:
        dmarc = _b(d.get("dmarc"))

    # Blacklists
    bl = d.get("blacklists") or d.get("blacklist") or d.get("blocklists") or []
    if isinstance(bl, dict):
        hits = sum(1 for v in bl.values() if v)
    elif isinstance(bl, list):
        hits = sum(1 for x in bl if x and (
            isinstance(x, str) or (isinstance(x, dict) and (
                x.get("listed") or x.get("hit") or x.get("status") in ("listed", "hit")
            ))
        ))
    else:
        hits = 0

    # Per-provider breakdown
    providers = d.get("providers") or d.get("isps") or d.get("isp") or []
    provider_breakdown: list[dict] = []
    if isinstance(providers, list):
        for p in providers:
            if not isinstance(p, dict):
                continue
            provider_breakdown.append({
                "name": p.get("name") or p.get("isp") or p.get("provider"),
                "inbox": _f(p.get("inbox") or p.get("inboxPct")),
                "spam": _f(p.get("spam") or p.get("spamPct")),
                "missing": _f(p.get("missing") or p.get("missingPct")),
            })
    elif isinstance(providers, dict):
        for k, v in providers.items():
            if isinstance(v, dict):
                provider_breakdown.append({
                    "name": k,
                    "inbox": _f(v.get("inbox") or v.get("inboxPct")),
                    "spam": _f(v.get("spam") or v.get("spamPct")),
                    "missing": _f(v.get("missing") or v.get("missingPct")),
                })

    return {
        "glockapps_test_id": str(test_id),
        "project_id": str(project_id),
        "test_started_at": d.get("startedAt") or d.get("started_at") or d.get("createdAt"),
        "test_completed_at": d.get("completedAt") or d.get("completed_at")
                             or d.get("finishedAt") or d.get("updatedAt"),
        "subject": d.get("subject"),
        "from_email": d.get("from") or d.get("fromEmail") or d.get("sender"),
        "inbox_pct": inbox_pct,
        "spam_pct": spam_pct,
        "missing_pct": missing_pct,
        "promo_pct": promo_pct,
        "spf_pass": spf,
        "dkim_pass": dkim,
        "dmarc_pass": dmarc,
        "blacklist_hits": int(hits or 0),
        "providers": provider_breakdown,
        "full_payload": raw,
    }


# ---------------------------------------------------------------------------
# Supabase upsert
# ---------------------------------------------------------------------------

def supabase_upsert_result(sb_url: str, sb_key: str, parsed: dict) -> tuple[bool, str]:
    if not sb_url or not sb_key:
        return False, "no supabase creds"
    row = {
        "glockapps_test_id": parsed["glockapps_test_id"],
        "project_id": parsed["project_id"],
        "test_started_at": parsed.get("test_started_at"),
        "test_completed_at": parsed.get("test_completed_at"),
        "subject": parsed.get("subject"),
        "from_email": parsed.get("from_email"),
        "inbox_pct": parsed.get("inbox_pct"),
        "spam_pct": parsed.get("spam_pct"),
        "missing_pct": parsed.get("missing_pct"),
        "promo_pct": parsed.get("promo_pct"),
        "spf_pass": parsed.get("spf_pass"),
        "dkim_pass": parsed.get("dkim_pass"),
        "dmarc_pass": parsed.get("dmarc_pass"),
        "blacklist_hits": parsed.get("blacklist_hits") or 0,
        "full_payload": parsed.get("full_payload"),
    }
    url = (sb_url.rstrip("/")
           + "/rest/v1/glockapps_test_results"
           + "?on_conflict=glockapps_test_id")
    h = {
        "apikey": sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal,resolution=merge-duplicates",
    }
    s, b, _ = _http("POST", url, headers=h, body=[row])
    if s >= 300:
        return False, f"http {s}: {b}"
    return True, "ok"


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def telegram_send(token: str, text: str) -> bool:
    if not token:
        return False
    try:
        cmd = [
            "curl", "-sS", "-m", "15", "-X", "POST",
            f"https://api.telegram.org/bot{token}/sendMessage",
            "-d", f"chat_id={TELEGRAM_CHAT_ID}",
            "-d", f"text={text}",
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return r.returncode == 0 and '"ok":true' in (r.stdout or "")
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Test discovery
# ---------------------------------------------------------------------------

def extract_test_list(body) -> list[dict]:
    """Normalize the various wrappers GlockApps uses."""
    if isinstance(body, list):
        return [r for r in body if isinstance(r, dict)]
    if isinstance(body, dict):
        for key in ("data", "items", "results", "tests", "list"):
            v = body.get(key)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
        # Sometimes a single object
        if "id" in body:
            return [body]
    return []


def extract_test_id(rec: dict) -> str | None:
    for k in ("id", "_id", "testId", "test_id", "uid", "uuid"):
        v = rec.get(k)
        if v:
            return str(v)
    return None


def fetch_test_detail(base: str, project_id: str, test_id: str,
                      api_key: str) -> tuple[int, dict | list | str]:
    """Try several detail endpoints in order."""
    candidates = [
        f"projects/{project_id}/tests/{test_id}",
        f"projects/{project_id}/tests/{test_id}/details",
        f"projects/{project_id}/shortTestResults",
    ]
    for path in candidates:
        extra = {"testId": test_id} if path.endswith("shortTestResults") else None
        s, body = ga_get(base, path, api_key, extra=extra)
        if s == 200 and body:
            # For shortTestResults we may need to filter
            if path.endswith("shortTestResults"):
                rows = extract_test_list(body)
                for r in rows:
                    if extract_test_id(r) == str(test_id):
                        return s, r
                if rows:
                    return s, rows[0]
                continue
            return s, body
    return 0, {"error": "no detail endpoint succeeded"}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    cfg = load_cfg()
    if not cfg["api_key"]:
        log_event({"type": "config_error", "error": "missing_GLOCKAPPS_API_KEY"})
        return 1

    base = cfg["base"].rstrip("/")
    pid = cfg["project_id"]

    # Probe + snapshot (preserve existing behavior so cron run still produces
    # debug snapshot for the dashboard).
    targets: list[str] = []
    if cfg["endpoint"]:
        targets.append(base + "/" + cfg["endpoint"].lstrip("/"))
    elif pid:
        targets.extend([
            f"{base}/projects/{pid}/shortTestResults",
            f"{base}/projects/{pid}/tests/list",
        ])
    else:
        targets.extend([
            f"{base}/projects",
            f"{base}/providers",
            f"{base}/blocklistServers",
        ])

    results: list[dict] = []
    for url in targets:
        try:
            s, body, headers = _http(
                "GET", f"{url}?{urllib.parse.urlencode({'apiKey': cfg['api_key']})}"
            )
            preview = body if isinstance(body, str) else json.dumps(body)[:500]
            results.append({
                "url": url,
                "status": s,
                "content_type": headers.get("Content-Type", ""),
                "body_preview": preview,
            })
        except Exception as e:
            results.append({"url": url, "error": str(e)})

    SNAPSHOT_PATH.write_text(json.dumps(
        {"captured_at": now_iso(), "results": results}, indent=2))

    # Result-detection only runs if we have a project_id (operational mode).
    new_results: list[dict] = []
    alerts: list[str] = []

    if pid:
        last_seen = load_last_seen()
        seen_ids = set(last_seen.get("test_ids", []))

        s, body = ga_get(base, f"projects/{pid}/tests/list", cfg["api_key"])
        tests = extract_test_list(body) if s == 200 else []
        for rec in tests:
            tid = extract_test_id(rec)
            if not tid or tid in seen_ids:
                continue
            # Only consider completed tests
            status_field = (rec.get("status") or rec.get("state") or "").lower()
            if status_field and status_field not in (
                "completed", "complete", "finished", "done"
            ):
                # Skip in-progress, but don't mark as seen
                continue

            ds, detail = fetch_test_detail(base, pid, tid, cfg["api_key"])
            payload = detail if isinstance(detail, dict) else {"raw": detail, "list_record": rec}
            # Merge list-level metadata when available
            merged = {**rec, **payload} if isinstance(payload, dict) else payload
            parsed = parse_test(tid, pid, merged)

            with RESULTS_PATH.open("a") as f:
                f.write(json.dumps({"pulled_at": now_iso(), **parsed}) + "\n")

            ok, msg = supabase_upsert_result(cfg["sb_url"], cfg["sb_key"], parsed)
            parsed["_supabase"] = msg

            new_results.append(parsed)
            seen_ids.add(tid)

            # Alerts
            inbox = parsed.get("inbox_pct")
            spam = parsed.get("spam_pct") or 0
            spf = parsed.get("spf_pass")
            dkim = parsed.get("dkim_pass")
            dmarc = parsed.get("dmarc_pass")
            auth_fail = any(x is False for x in (spf, dkim, dmarc))

            if inbox is not None and (inbox < INBOX_DEGRADED_THRESHOLD or auth_fail):
                alerts.append(
                    f"🚨 GlockApps placement: {inbox:.0f}% inbox, "
                    f"{spam:.0f}% spam — degraded deliverability"
                    + (f" (auth: SPF={spf} DKIM={dkim} DMARC={dmarc})"
                       if auth_fail else "")
                )
            elif inbox is not None and inbox >= INBOX_CLEAN_THRESHOLD and not auth_fail:
                alerts.append(
                    f"✅ GlockApps: {inbox:.0f}% inbox placement, all clean"
                )

        last_seen["test_ids"] = list(seen_ids)
        save_last_seen(last_seen)

    # Telegram
    if cfg["tg_token"]:
        for a in alerts:
            telegram_send(cfg["tg_token"], a)

    ok = any(r.get("status") == 200 and "error" not in r for r in results)
    log_event({
        "type": "glockapps_sync",
        "ok": ok,
        "endpoint_configured": bool(cfg["endpoint"]),
        "project_configured": bool(pid),
        "project_id": pid or None,
        "probe_results": results,
        "new_results_count": len(new_results),
        "new_test_ids": [r["glockapps_test_id"] for r in new_results],
        "alerts_sent": len(alerts),
        "next_step": (
            "Set GLOCKAPPS_PROJECT_ID (recommended) or GLOCKAPPS_API_ENDPOINT"
            if not cfg["endpoint"] and not pid else None
        ),
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
