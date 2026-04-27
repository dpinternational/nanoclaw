#!/usr/bin/env python3
import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "out"
STATE_DIR = ROOT / "state"
OUT_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)

LOG_PATH = OUT_DIR / "zerobounce_auto_log.jsonl"
STATE_PATH = STATE_DIR / "zerobounce_auto_state.json"

ZB_BATCH_URL = "https://bulkapi.zerobounce.net/v2/validatebatch"
ZB_CREDITS_URL = "https://api.zerobounce.net/v2/getcredits"
BATCH_SIZE = 100
SENDABLE = {"valid", "catch-all"}
UNSENDABLE = {
    "invalid",
    "spamtrap",
    "abuse",
    "do_not_mail",
    "unknown",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_cfg() -> dict:
    load_dotenv()
    return {
        "SUPABASE_URL": os.environ["SUPABASE_URL"],
        "SUPABASE_KEY": os.environ["SUPABASE_KEY"],
        "ZEROBOUNCE_API_KEY": os.environ["ZEROBOUNCE_API_KEY"],
        "MAX_PER_RUN": int(os.getenv("ZEROBOUNCE_MAX_PER_RUN", "500")),
        "SLEEP_BETWEEN_BATCHES": float(os.getenv("ZEROBOUNCE_BATCH_SLEEP_SEC", "0.2")),
    }


def sb_headers(cfg: dict) -> dict:
    return {
        "apikey": cfg["SUPABASE_KEY"],
        "Authorization": f"Bearer {cfg['SUPABASE_KEY']}",
        "Content-Type": "application/json",
    }


def get_credits(cfg: dict) -> int:
    r = requests.get(ZB_CREDITS_URL, params={"api_key": cfg["ZEROBOUNCE_API_KEY"]}, timeout=20)
    r.raise_for_status()
    return int(r.json().get("Credits", 0))


def fetch_pending_agents(cfg: dict, limit: int) -> list[dict]:
    url = f"{cfg['SUPABASE_URL']}/rest/v1/agents"
    params = {
        "select": "id,email,is_new_licensee,appointments_count,state,first_scraped_at,email_quality_status",
        "email": "not.is.null",
        "email_status": "eq.pending",
        # Skip emails the audit has flagged as shared by >=3 agents.
        # Accept rows that are unique OR not yet audited (NULL).
        "or": "(email_quality_status.is.null,email_quality_status.eq.unique)",
        "order": "first_scraped_at.asc",
        "limit": str(limit),
    }
    r = requests.get(url, headers=sb_headers(cfg), params=params, timeout=60)
    r.raise_for_status()
    rows = r.json()

    cleaned = []
    seen = set()
    for row in rows:
        email = (row.get("email") or "").strip().lower()
        if not email or email in seen:
            continue
        seen.add(email)
        row["email"] = email
        cleaned.append(row)
    return cleaned


def verify_batch(cfg: dict, emails: list[str]) -> list[dict]:
    payload = {
        "api_key": cfg["ZEROBOUNCE_API_KEY"],
        "email_batch": [{"email_address": e, "ip_address": ""} for e in emails],
    }
    r = requests.post(ZB_BATCH_URL, json=payload, timeout=120)
    r.raise_for_status()
    return r.json().get("email_batch", [])


def patch_agent_status(cfg: dict, agent_id: int, email_status: str) -> None:
    url = f"{cfg['SUPABASE_URL']}/rest/v1/agents"
    params = {"id": f"eq.{agent_id}"}
    body = {
        "email_status": email_status,
        "scraped_at": now_iso(),
    }
    r = requests.patch(url, headers=sb_headers(cfg), params=params, json=body, timeout=30)
    r.raise_for_status()


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"last_run_at": None, "total_verified": 0, "total_sendable": 0, "total_unsendable": 0}
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {"last_run_at": None, "total_verified": 0, "total_sendable": 0, "total_unsendable": 0}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2))


def append_log(record: dict) -> None:
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(record) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Auto-verify newly scraped leads via ZeroBounce")
    ap.add_argument("--max-agents", type=int, default=None, help="Override max leads per run")
    ap.add_argument("--dry-run", action="store_true", help="No API verification or updates")
    args = ap.parse_args()

    cfg = load_cfg()
    max_per_run = args.max_agents if args.max_agents is not None else cfg["MAX_PER_RUN"]

    credits = get_credits(cfg)
    if credits <= 0:
        rec = {"ts": now_iso(), "type": "no_credits", "credits": credits}
        append_log(rec)
        print(json.dumps(rec))
        return 0

    pending = fetch_pending_agents(cfg, min(max_per_run, credits))
    if not pending:
        rec = {"ts": now_iso(), "type": "noop", "reason": "no_pending_agents", "credits": credits}
        append_log(rec)
        print(json.dumps(rec))
        return 0

    if args.dry_run:
        rec = {
            "ts": now_iso(),
            "type": "dry_run",
            "pending_candidates": len(pending),
            "max_per_run": max_per_run,
            "credits": credits,
            "sample_emails": [r["email"] for r in pending[:10]],
        }
        append_log(rec)
        print(json.dumps(rec))
        return 0

    by_email: dict[str, list[dict]] = {}
    for a in pending:
        by_email.setdefault(a["email"], []).append(a)
    emails = list(by_email.keys())

    verified = 0
    sendable = 0
    unsendable = 0
    status_counts = {}

    for i in range(0, len(emails), BATCH_SIZE):
        batch = emails[i : i + BATCH_SIZE]
        results = verify_batch(cfg, batch)

        for r in results:
            email = (r.get("address") or "").strip().lower()
            status = (r.get("status") or "unknown").strip().lower()
            if not email:
                continue
            agents = by_email.get(email, [])
            if not agents:
                continue

            status_counts[status] = status_counts.get(status, 0) + len(agents)

            if status in SENDABLE:
                email_status = "verified"
                sendable += len(agents)
            elif status in UNSENDABLE:
                email_status = "bounced"
                unsendable += len(agents)
            else:
                email_status = "pending"

            for agent in agents:
                patch_agent_status(cfg, int(agent["id"]), email_status)

                append_log(
                    {
                        "ts": now_iso(),
                        "type": "agent_verified",
                        "agent_id": agent["id"],
                        "email": email,
                        "zb_status": status,
                        "email_status": email_status,
                        "state": agent.get("state"),
                    }
                )
                verified += 1

        time.sleep(cfg["SLEEP_BETWEEN_BATCHES"])

    state = load_state()
    state["last_run_at"] = now_iso()
    state["total_verified"] = int(state.get("total_verified", 0)) + verified
    state["total_sendable"] = int(state.get("total_sendable", 0)) + sendable
    state["total_unsendable"] = int(state.get("total_unsendable", 0)) + unsendable
    save_state(state)

    summary = {
        "ts": now_iso(),
        "type": "run_summary",
        "processed": verified,
        "sendable": sendable,
        "unsendable": unsendable,
        "status_counts": status_counts,
        "credits_before_run": credits,
    }
    append_log(summary)
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
