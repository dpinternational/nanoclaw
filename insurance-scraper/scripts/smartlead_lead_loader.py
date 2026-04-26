#!/usr/bin/env python3
"""
smartlead_lead_loader.py

Production lead loader bridging Supabase (verified agents) -> Smartlead campaigns.

Pipeline position:
    scraper.py -> agents (Supabase)
    zerobounce_auto_verify.py -> sets email_status='verified'/'bounced'
    smartlead_lead_loader.py (THIS) -> pushes verified agents into Smartlead campaigns
    Smartlead -> sends per campaign schedule

Selection segments:
    seq_a -> verified + is_new_licensee=true  (default campaign 3232436)
    seq_b -> verified + appointments_count=1  (default campaign 3232437)
    custom -> requires --campaign-id; selects verified + opted_out=false only

Idempotency: enforced by Supabase UNIQUE(agent_id, smartlead_campaign_id) on
agent_smartlead_loads, plus pre-filter SELECTing already-loaded agent_ids.

Safe by default: --dry-run unless --execute is supplied.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
LOCAL_ENV = ROOT / ".env"
MAC_LOCAL_ENV = Path("/Users/davidprice/nanoclaw/insurance-scraper/.env")
NANOCLAW_ENV = Path("/home/david/nanoclaw/.env")
MAC_NANOCLAW_ENV = Path("/Users/davidprice/nanoclaw/.env")

# Default log dir matches server layout; on Mac fall back to repo logs/.
SERVER_LOG = Path("/home/david/insurance-scraper/logs/smartlead_lead_loader.log")
LOCAL_LOG = ROOT / "logs" / "smartlead_lead_loader.log"

SMARTLEAD_BASE = "https://server.smartlead.ai/api/v1"
TELEGRAM_CHAT_ID = "577469008"

DEFAULT_CAMPAIGNS = {
    "seq_a": 3232436,  # Seq A - New Licensees PILOT
    "seq_b": 3232437,  # Seq B - Single Carrier PILOT
}

SEGMENT_LABELS = {
    "seq_a": "seq_a_new_licensees",
    "seq_b": "seq_b_single_carrier",
    "custom": "custom",
}

BATCH_SIZE = 25
MAX_LIMIT = 500
HARD_FAIL_HTTP_BACKOFF_SEC = 2

# Roughly: don't add more leads if campaign already has > 7 days of capacity queued.
# Smartlead exposes max_leads_per_day on /campaigns/{id}; we read it at runtime.
QUEUE_BACKLOG_DAYS = 7


# ---------------------------------------------------------------------------
# Env / secrets
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
              "SUPABASE_SERVICE_ROLE_KEY", "TELEGRAM_BOT_TOKEN"):
        if os.environ.get(k):
            env[k] = os.environ[k]
    # Prefer service role for tracking writes; fall back to SUPABASE_KEY.
    if not env.get("SUPABASE_SERVICE_ROLE_KEY") and env.get("SUPABASE_KEY"):
        env["SUPABASE_SERVICE_ROLE_KEY"] = env["SUPABASE_KEY"]
    return env


# ---------------------------------------------------------------------------
# HTTP helpers (stdlib only to match other scripts)
# ---------------------------------------------------------------------------

UA = "smartlead-lead-loader/1.0 (+nanoclaw)"


def _req(method: str, url: str, headers: dict | None = None,
         body: dict | list | None = None, timeout: int = 60) -> tuple[int, dict | list | str]:
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
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        text = e.read().decode("utf-8", errors="replace")
        try:
            return e.code, json.loads(text) if text else {"error": str(e)}
        except json.JSONDecodeError:
            return e.code, {"error": text[:800]}


# ---------------------------------------------------------------------------
# Supabase REST
# ---------------------------------------------------------------------------

class Supabase:
    def __init__(self, url: str, key: str):
        self.url = url.rstrip("/")
        self.key = key
        self.h = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }

    def select(self, table: str, params: dict) -> list[dict]:
        qs = urllib.parse.urlencode(params, doseq=True, safe="*().,:")
        url = f"{self.url}/rest/v1/{table}?{qs}"
        status, body = _req("GET", url, headers=self.h)
        if status >= 300:
            raise RuntimeError(f"Supabase select {table} {status}: {body}")
        return body if isinstance(body, list) else []

    def insert(self, table: str, rows: list[dict], on_conflict: str | None = None,
               return_rep: bool = True) -> list[dict]:
        if not rows:
            return []
        params = {}
        if on_conflict:
            params["on_conflict"] = on_conflict
        qs = ("?" + urllib.parse.urlencode(params)) if params else ""
        url = f"{self.url}/rest/v1/{table}{qs}"
        h = dict(self.h)
        prefer = ["return=representation" if return_rep else "return=minimal"]
        if on_conflict:
            prefer.append("resolution=merge-duplicates")
        h["Prefer"] = ",".join(prefer)
        status, body = _req("POST", url, headers=h, body=rows)
        if status >= 300:
            raise RuntimeError(f"Supabase insert {table} {status}: {body}")
        return body if isinstance(body, list) else []


# ---------------------------------------------------------------------------
# Smartlead REST
# ---------------------------------------------------------------------------

class Smartlead:
    def __init__(self, api_key: str):
        self.api_key = api_key

    def _qs(self, extra: dict | None = None) -> str:
        params = {"api_key": self.api_key}
        if extra:
            params.update(extra)
        return urllib.parse.urlencode(params)

    def get_campaign(self, cid: int) -> tuple[int, dict]:
        url = f"{SMARTLEAD_BASE}/campaigns/{cid}?{self._qs()}"
        status, body = _req("GET", url)
        return status, body if isinstance(body, dict) else {"raw": body}

    def list_leads(self, cid: int, offset: int = 0, limit: int = 100) -> tuple[int, dict]:
        url = f"{SMARTLEAD_BASE}/campaigns/{cid}/leads?{self._qs({'offset': offset, 'limit': min(limit, 100)})}"
        status, body = _req("GET", url)
        return status, body if isinstance(body, dict) else {"raw": body}

    def add_leads(self, cid: int, lead_list: list[dict]) -> tuple[int, dict]:
        url = f"{SMARTLEAD_BASE}/campaigns/{cid}/leads?{self._qs()}"
        status, body = _req("POST", url, body={"lead_list": lead_list}, timeout=120)
        return status, body if isinstance(body, dict) else {"raw": body}


# ---------------------------------------------------------------------------
# Selection logic
# ---------------------------------------------------------------------------

def split_name(full: str | None) -> tuple[str, str]:
    """agents.name format is 'LAST, FIRST MIDDLE'. Returns (first, last)."""
    if not full:
        return "", ""
    s = full.strip()
    if "," in s:
        last, rest = s.split(",", 1)
        rest = rest.strip().split()
        first = rest[0] if rest else ""
        return first.title(), last.strip().title()
    parts = s.split()
    if len(parts) == 1:
        return parts[0].title(), ""
    return parts[0].title(), parts[-1].title()


def first_carrier(appointments: Any) -> str:
    if not appointments:
        return ""
    if isinstance(appointments, str):
        try:
            appointments = json.loads(appointments)
        except Exception:
            return ""
    if isinstance(appointments, list) and appointments:
        first = appointments[0]
        if isinstance(first, dict):
            return (first.get("company_name")
                    or first.get("companyName")
                    or first.get("carrier") or "") or ""
    return ""


def fetch_already_loaded_ids(sb: Supabase, campaign_id: int) -> set[int]:
    """Pull every agent_id already tracked for this campaign (paginated).

    Returns empty set if the tracking table doesn't exist yet (graceful bootstrap).
    """
    out: set[int] = set()
    page = 0
    page_size = 1000
    while True:
        try:
            rows = sb.select("agent_smartlead_loads", {
                "select": "agent_id",
                "smartlead_campaign_id": f"eq.{campaign_id}",
                "limit": page_size,
                "offset": page * page_size,
            })
        except RuntimeError as e:
            msg = str(e)
            if "404" in msg or "PGRST205" in msg or "does not exist" in msg.lower():
                print("WARN: agent_smartlead_loads not found yet; treating as empty. "
                      "Apply sql/agent_smartlead_loads_schema.sql in Supabase SQL editor.",
                      file=sys.stderr)
                return out
            raise
        if not rows:
            break
        out.update(int(r["agent_id"]) for r in rows if r.get("agent_id") is not None)
        if len(rows) < page_size:
            break
        page += 1
    return out


def fetch_candidates(sb: Supabase, segment: str, limit: int,
                     exclude_ids: set[int]) -> list[dict]:
    base_params: dict = {
        "select": "id,name,email,npn,state,appointments,appointments_count,is_new_licensee,opted_out,email_status,scraped_at",
        "email_status": "eq.verified",
        "opted_out": "eq.false",
        "order": "scraped_at.desc.nullslast",
    }
    if segment == "seq_a":
        base_params["is_new_licensee"] = "eq.true"
    elif segment == "seq_b":
        base_params["appointments_count"] = "eq.1"
    elif segment == "custom":
        pass
    else:
        raise ValueError(f"Unknown segment: {segment}")

    # Over-fetch so we can locally filter excludes and still hit `limit`.
    fetch_size = min(MAX_LIMIT * 4, max(limit * 5, 200))
    base_params["limit"] = fetch_size
    rows = sb.select("agents", base_params)
    out: list[dict] = []
    for r in rows:
        if r.get("id") in exclude_ids:
            continue
        if not r.get("email"):
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out


def pool_remaining(sb: Supabase, segment: str, exclude_ids: set[int]) -> int:
    """Best-effort remaining-pool count via head-style request (returns Content-Range)."""
    params: dict = {
        "select": "id",
        "email_status": "eq.verified",
        "opted_out": "eq.false",
        "limit": 1,
    }
    if segment == "seq_a":
        params["is_new_licensee"] = "eq.true"
    elif segment == "seq_b":
        params["appointments_count"] = "eq.1"
    qs = urllib.parse.urlencode(params)
    url = f"{sb.url}/rest/v1/agents?{qs}"
    h = dict(sb.h)
    h["Prefer"] = "count=exact"
    h["Range-Unit"] = "items"
    h["Range"] = "0-0"
    req = urllib.request.Request(url, headers=h, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            cr = r.headers.get("Content-Range") or ""
            total = int(cr.split("/")[-1]) if "/" in cr else 0
            return max(total - len(exclude_ids), 0)
    except Exception:
        return -1


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
# Pre-flight: enforce_ready_senders.py
# ---------------------------------------------------------------------------

def run_sender_policy_check() -> tuple[bool, str]:
    """Run enforce_ready_senders.py; return (ok, captured stdout/stderr)."""
    script = ROOT / "scripts" / "enforce_ready_senders.py"
    if not script.exists():
        return True, "enforce_ready_senders.py not present (skipped)"
    try:
        r = subprocess.run(
            [sys.executable, str(script)],
            capture_output=True, text=True, timeout=60,
        )
        ok = r.returncode == 0
        out = (r.stdout or "") + (r.stderr or "")
        return ok, out[-2000:]
    except Exception as e:
        return False, f"policy check exception: {e}"


# ---------------------------------------------------------------------------
# Loader core
# ---------------------------------------------------------------------------

def chunked(seq: list, n: int) -> Iterable[list]:
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def build_lead_payload(agent: dict) -> dict:
    first, last = split_name(agent.get("name"))
    cf = {
        "agent_id": str(agent.get("id") or ""),
        "npn": str(agent.get("npn") or ""),
        "state": str(agent.get("state") or ""),
        "carrier": first_carrier(agent.get("appointments")),
    }
    cf = {k: v for k, v in cf.items() if v}
    return {
        "email": (agent.get("email") or "").strip(),
        "first_name": first,
        "last_name": last,
        "custom_fields": cf,
    }


def classify_response(body: dict, email: str) -> tuple[str, int | None]:
    """Pull lead_id + status from Smartlead /leads response shape (best-effort)."""
    lead_id = None
    # Smartlead returns various shapes: { upload_count, already_added_to_campaign,
    # duplicate_count, invalid_email_count, leads: [{email, lead_id}] }
    leads_field = body.get("leads") or body.get("lead_id_per_email") or []
    if isinstance(leads_field, list):
        for row in leads_field:
            if isinstance(row, dict) and (row.get("email") or "").lower() == email.lower():
                v = row.get("lead_id") or row.get("id")
                if v is not None:
                    try:
                        lead_id = int(v)
                    except (TypeError, ValueError):
                        pass
                break
    elif isinstance(leads_field, dict):
        v = leads_field.get(email) or leads_field.get(email.lower())
        if v is not None:
            try:
                lead_id = int(v)
            except (TypeError, ValueError):
                pass

    invalid = int(body.get("invalid_email_count") or 0)
    duplicates = int(body.get("duplicate_count") or 0) + int(
        body.get("already_added_to_campaign") or 0)
    uploaded = int(body.get("upload_count") or 0)

    if lead_id and uploaded:
        return "uploaded", lead_id
    if uploaded and not invalid and not duplicates:
        return "uploaded", lead_id
    if duplicates and not uploaded:
        return "duplicate", lead_id
    if invalid:
        return "invalid", lead_id
    if uploaded:
        return "uploaded", lead_id
    return "failed", lead_id


def write_log(log_path: Path, record: dict) -> None:
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception:
        # Logging failure must not abort the run.
        pass


def resolve_log_path() -> Path:
    return SERVER_LOG if SERVER_LOG.parent.exists() else LOCAL_LOG


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--segment", required=True, choices=["seq_a", "seq_b", "custom"],
                    help="Pool selector. 'custom' requires --campaign-id and uses verified+opted_out=false only.")
    ap.add_argument("--campaign-id", type=int, default=None,
                    help="Smartlead campaign id. Defaults from --segment.")
    ap.add_argument("--limit", type=int, default=100,
                    help="Max leads to load this run (clamped to 500).")
    ap.add_argument("--refill-to", type=int, default=None,
                    help="Top campaign up to this many total tracked leads. Overrides --limit if larger.")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="Plan only (default).")
    mode.add_argument("--execute", action="store_true",
                      help="Actually call Smartlead and write tracking rows.")
    ap.add_argument("--skip-policy-check", action="store_true",
                    help="Skip enforce_ready_senders.py preflight (NOT recommended).")
    ap.add_argument("--skip-backlog-check", action="store_true",
                    help="Skip the queue-backlog abort check.")
    args = ap.parse_args()

    if args.execute:
        args.dry_run = False

    segment = args.segment
    campaign_id = args.campaign_id or DEFAULT_CAMPAIGNS.get(segment)
    if not campaign_id:
        print(f"ERROR: --campaign-id required for segment '{segment}'", file=sys.stderr)
        return 2

    limit = max(1, min(args.limit, MAX_LIMIT))

    secrets = load_secrets()
    sb_url = secrets.get("SUPABASE_URL")
    sb_key = secrets.get("SUPABASE_SERVICE_ROLE_KEY") or secrets.get("SUPABASE_KEY")
    sl_key = secrets.get("SMARTLEAD_API_KEY")
    tg_token = secrets.get("TELEGRAM_BOT_TOKEN", "")
    if not sb_url or not sb_key:
        print("ERROR: SUPABASE_URL / SUPABASE_KEY missing.", file=sys.stderr)
        return 2
    if not sl_key:
        print("ERROR: SMARTLEAD_API_KEY missing.", file=sys.stderr)
        return 2

    sb = Supabase(sb_url, sb_key)
    sl = Smartlead(sl_key)
    log_path = resolve_log_path()

    summary: dict[str, Any] = {
        "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
        "segment": segment,
        "campaign_id": campaign_id,
        "mode": "execute" if args.execute else "dry_run",
        "limit_requested": args.limit,
        "limit_effective": limit,
        "refill_to": args.refill_to,
    }

    print(f"== smartlead_lead_loader segment={segment} campaign={campaign_id} mode={'EXECUTE' if args.execute else 'DRY-RUN'} ==")

    # 1. Sender policy preflight
    if not args.skip_policy_check:
        ok, out = run_sender_policy_check()
        summary["policy_check_ok"] = ok
        if not ok:
            summary["policy_check_output"] = out[-500:]
            print("ABORT: enforce_ready_senders.py failed:")
            print(out[-1500:])
            write_log(log_path, summary)
            return 3
        print("policy_check: OK")
    else:
        summary["policy_check_ok"] = None
        print("policy_check: SKIPPED")

    # 2. Campaign existence + status
    status, camp = sl.get_campaign(campaign_id)
    if status >= 300 or not isinstance(camp, dict) or not camp:
        summary["campaign_lookup"] = {"status": status, "body": camp}
        print(f"ABORT: campaign {campaign_id} lookup failed ({status}): {camp}")
        write_log(log_path, summary)
        return 4
    camp_status = (camp.get("status") or "").upper()
    camp_name = camp.get("name") or f"campaign-{campaign_id}"
    max_per_day = int(camp.get("max_leads_per_day") or 0)
    summary["campaign_status"] = camp_status
    summary["campaign_name"] = camp_name
    summary["max_leads_per_day"] = max_per_day
    print(f"campaign: {camp_name} status={camp_status} max_leads_per_day={max_per_day}")
    if camp_status not in ("ACTIVE", "PAUSED", "DRAFTED", "DRAFT"):
        print(f"ABORT: campaign status {camp_status!r} not loadable.")
        write_log(log_path, summary)
        return 5

    # 3. Already-loaded set + remaining pool
    already_loaded = fetch_already_loaded_ids(sb, campaign_id)
    summary["already_loaded_count"] = len(already_loaded)
    print(f"already_loaded: {len(already_loaded)}")

    # 4. Backlog check (best-effort): count queued leads in Smartlead
    if not args.skip_backlog_check and max_per_day > 0:
        queued = len(already_loaded)  # cheap proxy: total tracked rows
        cap = max_per_day * QUEUE_BACKLOG_DAYS
        summary["backlog_check"] = {"queued_proxy": queued, "cap": cap}
        if queued > cap:
            print(f"ABORT: queued {queued} > {cap} ({QUEUE_BACKLOG_DAYS}d backlog cap).")
            write_log(log_path, summary)
            return 6

    # 5. Determine effective limit (refill-to logic)
    if args.refill_to is not None:
        deficit = max(args.refill_to - len(already_loaded), 0)
        effective_limit = min(deficit, MAX_LIMIT)
        if effective_limit == 0:
            print(f"NO-OP: campaign already at/above refill target ({len(already_loaded)} >= {args.refill_to}).")
            summary["effective_limit"] = 0
            summary["loaded"] = 0
            write_log(log_path, summary)
            return 0
        limit = effective_limit
        summary["limit_effective"] = limit
        print(f"refill: deficit={deficit} -> loading up to {limit}")

    # 6. Pull candidates
    candidates = fetch_candidates(sb, segment, limit, already_loaded)
    remaining = pool_remaining(sb, segment, already_loaded)
    summary["candidates_planned"] = len(candidates)
    summary["pool_remaining"] = remaining
    print(f"candidates: {len(candidates)}  pool_remaining(approx): {remaining}")

    if not candidates:
        print("NO-OP: no candidates to load.")
        write_log(log_path, summary)
        return 0

    # Show first few
    preview_n = min(5, len(candidates))
    print(f"preview ({preview_n}):")
    for a in candidates[:preview_n]:
        first, last = split_name(a.get("name"))
        print(f"  - id={a.get('id')} {first} {last} <{a.get('email')}> "
              f"state={a.get('state')} carrier={first_carrier(a.get('appointments'))!r}")

    if args.dry_run:
        print(f"DRY-RUN: would load {len(candidates)} leads to campaign {campaign_id} ({camp_name}).")
        summary["loaded"] = 0
        write_log(log_path, summary)
        return 0

    # 7. EXECUTE: batch upload + tracking
    uploaded = duplicates = invalid = failed = 0
    tracking_rows: list[dict] = []

    for batch in chunked(candidates, BATCH_SIZE):
        payload = [build_lead_payload(a) for a in batch]
        status, body = sl.add_leads(campaign_id, payload)
        body_dict = body if isinstance(body, dict) else {"raw": body}
        ok = status < 300
        if not ok:
            time.sleep(HARD_FAIL_HTTP_BACKOFF_SEC)
        for agent, p in zip(batch, payload):
            email = p["email"]
            if not ok:
                result = "failed"
                lead_id = None
            else:
                result, lead_id = classify_response(body_dict, email)
            counters = {"uploaded": 0, "duplicate": 0, "invalid": 0, "failed": 0}
            counters[result] = 1
            uploaded += counters["uploaded"]
            duplicates += counters["duplicate"]
            invalid += counters["invalid"]
            failed += counters["failed"]
            tracking_rows.append({
                "agent_id": int(agent["id"]),
                "smartlead_campaign_id": int(campaign_id),
                "smartlead_lead_id": lead_id,
                "email": email,
                "segment": SEGMENT_LABELS.get(segment, segment),
                "load_result": result,
                "load_response": {
                    "http_status": status,
                    "campaign_response": body_dict if ok else {"error_status": status, "body": body_dict},
                },
            })
        # gentle pacing between batches
        time.sleep(0.4)

    # 8. Write tracking rows in chunks (idempotent upsert on the unique key)
    inserted = 0
    for chunk in chunked(tracking_rows, 200):
        try:
            res = sb.insert(
                "agent_smartlead_loads",
                chunk,
                on_conflict="agent_id,smartlead_campaign_id",
                return_rep=False,
            )
            inserted += len(chunk)
        except Exception as e:
            print(f"WARN: tracking insert failed: {e}", file=sys.stderr)

    summary.update({
        "loaded": uploaded,
        "duplicates": duplicates,
        "invalid": invalid,
        "failed": failed,
        "tracking_rows_written": inserted,
    })
    print(f"RESULT: uploaded={uploaded} duplicates={duplicates} invalid={invalid} failed={failed} tracked={inserted}")

    # 9. Telegram
    if uploaded > 0 and tg_token:
        msg = (f"Loaded {uploaded} leads to {camp_name} ({segment}). "
               f"Pool remaining: {remaining if remaining >= 0 else 'unknown'}.")
        telegram_send(tg_token, msg)

    write_log(log_path, summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
