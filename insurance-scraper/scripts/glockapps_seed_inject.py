#!/usr/bin/env python3
"""
glockapps_seed_inject.py

Inject the GlockApps project autoTestEmail seed into Smartlead pilot campaigns
so the seed runs through the full sequence (5 steps over ~16 days) and produces
inbox-placement reports the GlockApps API can pull back via glockapps_sync.py.

Why: GlockApps blocks /test/start on this plan tier, so we cannot trigger tests
directly. Instead we use the project's "autoTestEmail" magic seed — any mail
sent to it auto-creates a placement test in the GlockApps dashboard.

Run cadence: weekly (Mon 09:00 ET cron). Idempotent: skips a campaign if the
seed is already present in its lead list.

Modes:
  --dry-run (default)  Print what would be injected.
  --execute            Actually call Smartlead + write tracking row.
  --campaign-id ID     Override default targets (Seq A + Seq B pilots).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENV = ROOT / ".env"
MAC_LOCAL_ENV = Path("/Users/davidprice/nanoclaw/insurance-scraper/.env")
NANOCLAW_ENV = Path("/home/david/nanoclaw/.env")
MAC_NANOCLAW_ENV = Path("/Users/davidprice/nanoclaw/.env")

SERVER_LOG = Path("/home/david/insurance-scraper/logs/glockapps_seed_inject.log")
LOCAL_LOG = ROOT / "logs" / "glockapps_seed_inject.log"

SMARTLEAD_BASE = "https://server.smartlead.ai/api/v1"
GLOCKAPPS_BASE_DEFAULT = "https://api.glockapps.com/gateway/spamtest-v2/api"
TELEGRAM_CHAT_ID = "577469008"

# Pilot campaigns (Seq A + Seq B). Match smartlead_lead_loader.py.
DEFAULT_CAMPAIGNS = [
    (3232436, "Seq A - New Licensees PILOT"),
    (3232437, "Seq B - Single Carrier PILOT"),
]

SENTINEL_AGENT_ID = -1   # Marker row in agent_smartlead_loads for seed injections
SEED_FIRST = "GlockApps"
SEED_LAST = "Test"
UA = "glockapps-seed-inject/1.0 (+nanoclaw)"


# ---------------------------------------------------------------------------
# Env loading
# ---------------------------------------------------------------------------

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


def load_secrets() -> dict[str, str]:
    env: dict[str, str] = {}
    for p in (LOCAL_ENV, MAC_LOCAL_ENV, NANOCLAW_ENV, MAC_NANOCLAW_ENV):
        for k, v in load_env_file(p).items():
            if k not in env or not env[k]:
                env[k] = v
    for k in ("SMARTLEAD_API_KEY", "SUPABASE_URL", "SUPABASE_KEY",
              "SUPABASE_SERVICE_ROLE_KEY", "TELEGRAM_BOT_TOKEN",
              "GLOCKAPPS_API_KEY", "GLOCKAPPS_PROJECT_ID",
              "GLOCKAPPS_API_BASE"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    if not env.get("SUPABASE_SERVICE_ROLE_KEY") and env.get("SUPABASE_KEY"):
        env["SUPABASE_SERVICE_ROLE_KEY"] = env["SUPABASE_KEY"]
    return env


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _req(method: str, url: str, headers: dict | None = None,
         body: dict | list | None = None,
         timeout: int = 60) -> tuple[int, dict | list | str]:
    data = None
    h = {"Accept": "application/json", "User-Agent": UA}
    if headers:
        h.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            text = r.read().decode("utf-8")
            try:
                return r.status, (json.loads(text) if text else {})
            except json.JSONDecodeError:
                return r.status, text
    except urllib.error.HTTPError as e:
        text = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, (json.loads(text) if text else {"error": str(e)})
        except json.JSONDecodeError:
            return e.code, {"error": text[:800]}


# ---------------------------------------------------------------------------
# GlockApps
# ---------------------------------------------------------------------------

def fetch_auto_test_email(api_key: str, project_id: str, base: str) -> str:
    base = (base or GLOCKAPPS_BASE_DEFAULT).rstrip("/")
    url = f"{base}/projects/{project_id}?{urllib.parse.urlencode({'apiKey': api_key})}"
    status, body = _req("GET", url, timeout=30)
    if status >= 300 or not isinstance(body, dict):
        raise RuntimeError(f"GlockApps /projects/{project_id} failed {status}: {body}")
    seed = body.get("autoTestEmail") or body.get("auto_test_email")
    if not seed and isinstance(body.get("data"), dict):
        d = body["data"]
        seed = d.get("autoTestEmail") or d.get("auto_test_email")
    if not seed:
        for v in body.values():
            if isinstance(v, dict) and v.get("autoTestEmail"):
                seed = v["autoTestEmail"]
                break
    if not seed:
        raise RuntimeError(f"autoTestEmail not present in project payload: {body}")
    return seed.strip()


# ---------------------------------------------------------------------------
# Smartlead helpers
# ---------------------------------------------------------------------------

def sl_qs(api_key: str, extra: dict | None = None) -> str:
    p = {"api_key": api_key}
    if extra:
        p.update(extra)
    return urllib.parse.urlencode(p)


def sl_get_campaign(api_key: str, cid: int) -> tuple[int, dict]:
    url = f"{SMARTLEAD_BASE}/campaigns/{cid}?{sl_qs(api_key)}"
    s, b = _req("GET", url)
    return s, (b if isinstance(b, dict) else {"raw": b})


def sl_count_leads(api_key: str, cid: int) -> int:
    """Best-effort: paginate /campaigns/{cid}/leads to total count."""
    total = 0
    offset = 0
    page = 100
    while True:
        url = (f"{SMARTLEAD_BASE}/campaigns/{cid}/leads?"
               f"{sl_qs(api_key, {'offset': offset, 'limit': page})}")
        s, b = _req("GET", url)
        if s >= 300 or not isinstance(b, dict):
            return total
        # Smartlead returns {"total_leads": N, "data": [...]} OR a list directly
        if "total_leads" in b:
            return int(b.get("total_leads") or 0)
        data = b.get("data") if isinstance(b, dict) else None
        if not data:
            break
        total += len(data)
        if len(data) < page:
            break
        offset += page
        if offset > 5000:
            break
    return total


def sl_search_lead_in_campaign(api_key: str, cid: int, email: str) -> bool:
    """Use global lead-search endpoint then filter by campaign_id."""
    url = (f"{SMARTLEAD_BASE}/leads/?"
           f"{sl_qs(api_key, {'email': email})}")
    s, b = _req("GET", url)
    if s >= 300:
        return False
    # Response may be a list or {data:[...]}
    rows = b if isinstance(b, list) else (b.get("data") if isinstance(b, dict) else None)
    if not rows:
        return False
    for row in rows:
        if not isinstance(row, dict):
            continue
        # Several shape possibilities
        camp_ids = []
        cf = row.get("campaign_lead_map") or row.get("campaigns") or []
        if isinstance(cf, list):
            for entry in cf:
                if isinstance(entry, dict):
                    v = entry.get("campaign_id") or entry.get("id")
                    if v is not None:
                        camp_ids.append(int(v))
        if row.get("campaign_id") is not None:
            try:
                camp_ids.append(int(row["campaign_id"]))
            except Exception:
                pass
        if int(cid) in camp_ids:
            return True
        # Fallback: if the email exact matches and no campaign info present,
        # do a per-campaign confirm via /campaigns/{cid}/leads?... Safer to
        # return False here; we'll rely on Smartlead duplicate-detect on POST.
    return False


def sl_add_lead(api_key: str, cid: int, lead: dict) -> tuple[int, dict]:
    url = f"{SMARTLEAD_BASE}/campaigns/{cid}/leads?{sl_qs(api_key)}"
    s, b = _req("POST", url, body={"lead_list": [lead]}, timeout=120)
    return s, (b if isinstance(b, dict) else {"raw": b})


# ---------------------------------------------------------------------------
# Supabase tracking
# ---------------------------------------------------------------------------

def supabase_track(sb_url: str, sb_key: str, row: dict) -> tuple[bool, str]:
    if not sb_url or not sb_key:
        return False, "supabase creds missing"
    url = (sb_url.rstrip("/")
           + "/rest/v1/agent_smartlead_loads"
           + "?on_conflict=agent_id,smartlead_campaign_id")
    h = {
        "apikey": sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal,resolution=merge-duplicates",
    }
    s, b = _req("POST", url, headers=h, body=[row])
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
# Logging
# ---------------------------------------------------------------------------

def resolve_log_path() -> Path:
    return SERVER_LOG if SERVER_LOG.parent.exists() else LOCAL_LOG


def write_log(path: Path, rec: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True)
    mode.add_argument("--execute", action="store_true",
                      help="Actually inject the seed.")
    ap.add_argument("--campaign-id", type=int, default=None,
                    help="Override target campaign(s). Default: both pilots.")
    ap.add_argument("--first-name", default=SEED_FIRST)
    ap.add_argument("--last-name", default=SEED_LAST)
    args = ap.parse_args()

    if args.execute:
        args.dry_run = False

    secrets = load_secrets()
    sl_key = secrets.get("SMARTLEAD_API_KEY")
    ga_key = secrets.get("GLOCKAPPS_API_KEY")
    ga_pid = secrets.get("GLOCKAPPS_PROJECT_ID")
    ga_base = secrets.get("GLOCKAPPS_API_BASE", GLOCKAPPS_BASE_DEFAULT)
    sb_url = secrets.get("SUPABASE_URL")
    sb_key = secrets.get("SUPABASE_SERVICE_ROLE_KEY") or secrets.get("SUPABASE_KEY")
    tg_token = secrets.get("TELEGRAM_BOT_TOKEN", "")

    missing = [k for k, v in {
        "SMARTLEAD_API_KEY": sl_key,
        "GLOCKAPPS_API_KEY": ga_key,
        "GLOCKAPPS_PROJECT_ID": ga_pid,
    }.items() if not v]
    if missing:
        print(f"ERROR: missing secrets: {missing}", file=sys.stderr)
        return 2

    log_path = resolve_log_path()
    summary: dict = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "mode": "execute" if args.execute else "dry_run",
    }

    print("== glockapps_seed_inject "
          f"mode={'EXECUTE' if args.execute else 'DRY-RUN'} ==")

    # 1. Fetch autoTestEmail fresh
    try:
        seed_email = fetch_auto_test_email(ga_key, ga_pid, ga_base)
    except Exception as e:
        print(f"ABORT: cannot fetch autoTestEmail: {e}", file=sys.stderr)
        summary["error"] = f"fetch_seed: {e}"
        write_log(log_path, summary)
        return 3
    summary["seed_email"] = seed_email
    summary["project_id"] = ga_pid
    print(f"autoTestEmail: {seed_email}  (project {ga_pid})")

    # 2. Determine targets
    if args.campaign_id:
        targets = [(args.campaign_id, f"campaign-{args.campaign_id}")]
    else:
        targets = list(DEFAULT_CAMPAIGNS)

    injected_count = 0
    skipped_count = 0
    failed_count = 0
    per_campaign: list[dict] = []
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()

    for cid, label in targets:
        print(f"\n-- campaign {cid} ({label}) --")
        rec: dict = {"campaign_id": cid, "label": label}

        # Confirm campaign exists / status
        s, camp = sl_get_campaign(sl_key, cid)
        if s >= 300 or not camp:
            print(f"  SKIP: campaign lookup failed status={s}: {camp}")
            rec["result"] = "lookup_failed"
            rec["http_status"] = s
            failed_count += 1
            per_campaign.append(rec)
            continue
        camp_status = (camp.get("status") or "").upper()
        camp_name = camp.get("name") or label
        rec["campaign_name"] = camp_name
        rec["campaign_status"] = camp_status
        print(f"  status={camp_status} name={camp_name!r}")

        before_total = sl_count_leads(sl_key, cid)
        rec["leads_before"] = before_total
        print(f"  leads_before: {before_total}")

        # Idempotency: is the seed already in this campaign?
        already = sl_search_lead_in_campaign(sl_key, cid, seed_email)
        rec["already_present"] = already
        if already:
            print(f"  SKIP: seed {seed_email} already present.")
            rec["result"] = "skipped_already_present"
            skipped_count += 1
            per_campaign.append(rec)
            continue

        lead_payload = {
            "email": seed_email,
            "first_name": args.first_name,
            "last_name": args.last_name,
            "custom_fields": {
                "state": "GLOCKAPPS_SEED",
                "carrier": "GLOCKAPPS_TEST",
                "agent_id": "glockapps_seed",
                "injected_at": now_iso,
            },
        }

        if args.dry_run:
            print(f"  DRY-RUN: would POST lead {lead_payload}")
            rec["result"] = "dry_run"
            per_campaign.append(rec)
            continue

        # Execute
        s, body = sl_add_lead(sl_key, cid, lead_payload)
        rec["http_status"] = s
        rec["response"] = body
        ok = s < 300 and isinstance(body, dict)
        uploaded = int((body or {}).get("upload_count") or 0) if isinstance(body, dict) else 0
        dup = (int((body or {}).get("duplicate_count") or 0)
               + int((body or {}).get("already_added_to_campaign") or 0)
               ) if isinstance(body, dict) else 0
        if not ok:
            print(f"  FAIL: status={s} body={body}")
            rec["result"] = "failed"
            failed_count += 1
            per_campaign.append(rec)
            continue

        after_total = sl_count_leads(sl_key, cid)
        rec["leads_after"] = after_total
        delta = after_total - before_total

        if uploaded and delta > 0:
            rec["result"] = "uploaded"
            injected_count += 1
            print(f"  OK: uploaded=1  ({before_total} -> {after_total})")
        elif dup or delta == 0:
            # Smartlead deduped server-side (seed already in campaign)
            rec["result"] = "skipped_smartlead_dedup"
            skipped_count += 1
            print(f"  SKIP: smartlead deduped (count unchanged {before_total}).")
        else:
            rec["result"] = "unknown"
            print(f"  WARN: ambiguous response: {body}")

        print(f"  leads_after: {after_total}")

        # Track in Supabase
        track_row = {
            "agent_id": SENTINEL_AGENT_ID,
            "smartlead_campaign_id": int(cid),
            "smartlead_lead_id": None,
            "email": seed_email,
            "segment": "glockapps_seed",
            "load_result": rec["result"],
            "load_response": {
                "http_status": s,
                "campaign_response": body,
                "injected_at": now_iso,
                "project_id": ga_pid,
            },
        }
        ok_t, msg = supabase_track(sb_url, sb_key, track_row)
        rec["tracking"] = msg
        if not ok_t:
            print(f"  WARN: tracking insert failed: {msg}")

        per_campaign.append(rec)

    summary["injected"] = injected_count
    summary["skipped"] = skipped_count
    summary["failed"] = failed_count
    summary["per_campaign"] = per_campaign
    write_log(log_path, summary)

    print("\n== summary ==")
    print(f"  injected: {injected_count}")
    print(f"  skipped:  {skipped_count}")
    print(f"  failed:   {failed_count}")

    # Telegram only when something actually happened in execute mode
    if args.execute and injected_count > 0 and tg_token:
        labels_done = ", ".join(
            r.get("campaign_name") or r["label"]
            for r in per_campaign if r.get("result") == "uploaded"
        )
        msg = (f"🎯 GlockApps seed injected into {labels_done}. "
               f"Inbox placement data will populate over next 16 days "
               f"as sequence steps send.")
        telegram_send(tg_token, msg)

    return 0 if failed_count == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
