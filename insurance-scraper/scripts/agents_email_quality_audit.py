#!/usr/bin/env python3
"""
agents_email_quality_audit.py

Mark agents whose email is shared by >=3 agents as 'duplicate_shared'
on the agents.email_quality_status column, BEFORE ZeroBounce verification
runs. Agents with unique or 2-share emails are marked 'unique'.

Modes:
  --full-sweep     scan all agents (initial backfill)
  --incremental    scan only rows where email_quality_status IS NULL (default)
  --report         print stats only, no writes
  --dry-run        show what would change, no writes
  --execute        perform updates
  --i-mean-it      required if full-sweep --execute would touch >50k rows

Threshold: emails shared by 3 OR MORE agents are flagged. 2-share permitted
(spouse/family business). Corporate-pattern detection (e.g. info@) lives in
the loader; this audit only handles the dup-share dimension.
"""
import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "email_quality_audit.log"

PAGE_SIZE = 1000
UPDATE_CHUNK = 100
DUP_THRESHOLD = 3


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_cfg() -> dict:
    load_dotenv()
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY")
    if not url or not key:
        print("missing SUPABASE_URL or SUPABASE_KEY/SERVICE_ROLE_KEY", file=sys.stderr)
        sys.exit(2)
    return {"SUPABASE_URL": url.rstrip("/"), "SUPABASE_KEY": key}


def headers(cfg: dict) -> dict:
    return {
        "apikey": cfg["SUPABASE_KEY"],
        "Authorization": f"Bearer {cfg['SUPABASE_KEY']}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal",
    }


def preflight_schema(cfg: dict) -> None:
    url = f"{cfg['SUPABASE_URL']}/rest/v1/agents"
    r = requests.get(
        url,
        headers=headers(cfg),
        params={"select": "id,email_quality_status", "limit": "1"},
        timeout=30,
    )
    if r.status_code >= 400:
        print("schema not applied: agents.email_quality_status missing", file=sys.stderr)
        print("Apply sql/agent_email_quality_columns.sql in Supabase SQL Editor.", file=sys.stderr)
        sys.exit(1)


def fetch_rows(cfg: dict, only_null: bool) -> list[dict]:
    """Paginate via Range header for stable ordering."""
    url = f"{cfg['SUPABASE_URL']}/rest/v1/agents"
    out: list[dict] = []
    offset = 0
    while True:
        params = {
            "select": "id,email,email_quality_status",
            "order": "id.asc",
            "email": "not.is.null",
            "limit": str(PAGE_SIZE),
            "offset": str(offset),
        }
        if only_null:
            params["email_quality_status"] = "is.null"
        r = requests.get(url, headers=headers(cfg), params=params, timeout=120)
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        out.extend(rows)
        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE
    return out


def patch_chunk(cfg: dict, ids: list[int], status: str, share_count: int) -> None:
    if not ids:
        return
    url = f"{cfg['SUPABASE_URL']}/rest/v1/agents"
    params = {"id": "in.(" + ",".join(str(i) for i in ids) + ")"}
    body = {
        "email_quality_status": status,
        "email_share_count": share_count,
        "email_quality_checked_at": now_iso(),
    }
    r = requests.patch(url, headers=headers(cfg), params=params, json=body, timeout=60)
    if r.status_code >= 400:
        raise RuntimeError(f"patch failed {r.status_code}: {r.text[:300]}")


def append_log(rec: dict) -> None:
    with LOG_PATH.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Pre-ZB duplicate-shared email audit")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--full-sweep", action="store_true")
    g.add_argument("--incremental", action="store_true")
    m = ap.add_mutually_exclusive_group()
    m.add_argument("--execute", action="store_true")
    m.add_argument("--dry-run", action="store_true")
    m.add_argument("--report", action="store_true")
    ap.add_argument("--i-mean-it", action="store_true",
                    help="required for full-sweep --execute touching >50k rows")
    ap.add_argument("--top", type=int, default=10, help="show top-N shared emails in report")
    args = ap.parse_args()

    full = args.full_sweep
    if not args.full_sweep and not args.incremental:
        # default mode = incremental
        pass

    cfg = load_cfg()
    preflight_schema(cfg)

    t0 = time.time()
    rows = fetch_rows(cfg, only_null=not full)
    fetched = len(rows)

    # If incremental, we still need full email-share counts to decide; pull
    # the full set's email shares from the database. To keep this fast and
    # within Postgrest limits, we fetch all (id,email) once for share-counting
    # when in incremental mode and there are NULL rows to process.
    if not full and rows:
        all_rows = fetch_rows(cfg, only_null=False)
    else:
        all_rows = rows

    by_email: dict[str, list[int]] = defaultdict(list)
    for r in all_rows:
        e = (r.get("email") or "").strip().lower()
        if not e:
            continue
        by_email[e].append(int(r["id"]))

    # Decide updates
    target_ids: set[int] = {int(r["id"]) for r in rows if (r.get("email") or "").strip()}
    dup_updates: dict[int, tuple[str, int]] = {}  # id -> (email, share_count)
    uniq_updates: dict[int, tuple[str, int]] = {}
    for email, ids in by_email.items():
        share = len(ids)
        is_dup = share >= DUP_THRESHOLD
        for aid in ids:
            if aid not in target_ids:
                continue
            if is_dup:
                dup_updates[aid] = (email, share)
            else:
                uniq_updates[aid] = (email, share)

    top_shared = sorted(
        ((e, len(ids)) for e, ids in by_email.items() if len(ids) >= 2),
        key=lambda x: -x[1],
    )[: args.top]

    summary = {
        "ts": now_iso(),
        "mode": "full-sweep" if full else "incremental",
        "fetched_rows": fetched,
        "total_rows_seen_for_share_counts": len(all_rows),
        "would_mark_duplicate": len(dup_updates),
        "would_mark_unique": len(uniq_updates),
        "unique_emails": len(by_email),
        "duplicate_emails_3plus": sum(1 for ids in by_email.values() if len(ids) >= DUP_THRESHOLD),
        "top_shared": top_shared,
        "elapsed_sec": round(time.time() - t0, 2),
    }

    if args.report or args.dry_run or not args.execute:
        summary["type"] = "report" if args.report else ("dry_run" if args.dry_run else "preview")
        append_log(summary)
        print(json.dumps(summary, indent=2))
        return 0

    # --execute path
    if full and (len(dup_updates) + len(uniq_updates)) > 50000 and not args.i_mean_it:
        print("full-sweep --execute would touch >50k rows; pass --i-mean-it to proceed", file=sys.stderr)
        return 3

    # Apply duplicate updates first (most important)
    def apply(updates: dict[int, tuple[str, int]], status: str) -> None:
        # Group by share_count so we can store accurate counts in batches
        by_share: dict[int, list[int]] = defaultdict(list)
        for aid, (_e, share) in updates.items():
            by_share[share].append(aid)
        for share, ids in by_share.items():
            for i in range(0, len(ids), UPDATE_CHUNK):
                patch_chunk(cfg, ids[i : i + UPDATE_CHUNK], status, share)

    apply(dup_updates, "duplicate_shared")
    apply(uniq_updates, "unique")

    summary["type"] = "executed"
    summary["elapsed_sec"] = round(time.time() - t0, 2)
    append_log(summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
