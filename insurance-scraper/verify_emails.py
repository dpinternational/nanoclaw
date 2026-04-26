"""
Verify agent emails via ZeroBounce and export Smartlead-ready CSVs.

Usage:
    python verify_emails.py --limit 100                # Test run with 100 agents (free credits)
    python verify_emails.py --segment new_licensees    # Full run on new licensees
    python verify_emails.py --segment single_carrier   # Full run on single-carrier agents
    python verify_emails.py --segment all              # Everything

Outputs:
    out/seq_a_new_licensees.csv       — ready for Smartlead (valid + catch-all only)
    out/seq_b_single_carrier.csv      — ready for Smartlead (valid + catch-all only)
    out/verification_log.jsonl        — full raw ZeroBounce results (for audit / Supabase sync)
"""

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
ZEROBOUNCE_API_KEY = os.environ["ZEROBOUNCE_API_KEY"]

ZB_BATCH_URL = "https://bulkapi.zerobounce.net/v2/validatebatch"
ZB_CREDITS_URL = "https://api.zerobounce.net/v2/getcredits"
BATCH_SIZE = 100  # ZeroBounce max per batch call
SENDABLE_STATUSES = {"valid", "catch-all"}  # ship these to Smartlead

OUT_DIR = Path(__file__).parent / "out"
OUT_DIR.mkdir(exist_ok=True)
LOG_PATH = OUT_DIR / "verification_log.jsonl"


def sb_headers() -> dict:
    return {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
    }


def get_credits() -> int:
    r = requests.get(ZB_CREDITS_URL, params={"api_key": ZEROBOUNCE_API_KEY}, timeout=10)
    r.raise_for_status()
    return int(r.json().get("Credits", 0))


def fetch_agents(segment: str, limit: int | None) -> list[dict]:
    """Pull unverified agents from Supabase for a given segment."""
    select = "id,name,email,state,appointments_list,is_new_licensee,appointments_count"
    filters = ["email=not.is.null", "email=neq."]
    if segment == "new_licensees":
        filters.append("is_new_licensee=eq.true")
    elif segment == "single_carrier":
        filters.append("appointments_count=eq.1")
    elif segment == "ab":
        # A (new licensees) + B (single carrier) in one pass
        filters.append("or=(is_new_licensee.eq.true,appointments_count.eq.1)")
    elif segment != "all":
        raise ValueError(f"unknown segment: {segment}")

    url = f"{SUPABASE_URL}/rest/v1/agents?select={select}&{'&'.join(filters)}"
    if limit:
        url += f"&limit={limit}"

    # paginate in 1000-row pages (Supabase default cap)
    all_rows: list[dict] = []
    page_size = 1000
    offset = 0
    remaining = limit if limit else float("inf")
    while remaining > 0:
        page_url = url + f"&offset={offset}"
        r = requests.get(
            page_url,
            headers={**sb_headers(), "Range": f"{offset}-{offset + page_size - 1}"},
            timeout=30,
        )
        r.raise_for_status()
        rows = r.json()
        if not rows:
            break
        all_rows.extend(rows)
        offset += len(rows)
        remaining -= len(rows)
        if len(rows) < page_size:
            break
    return all_rows[:limit] if limit else all_rows


def verify_batch(emails: list[str]) -> list[dict]:
    """POST up to 100 emails to ZeroBounce /validatebatch."""
    payload = {
        "api_key": ZEROBOUNCE_API_KEY,
        "email_batch": [{"email_address": e, "ip_address": ""} for e in emails],
    }
    r = requests.post(ZB_BATCH_URL, json=payload, timeout=120)
    r.raise_for_status()
    data = r.json()
    return data.get("email_batch", [])


def extract_first_name(agent: dict) -> str:
    """Pick a clean first name for merge tag. NAIC format: 'LASTNAME, FIRSTNAME M'."""
    name = (agent.get("name") or "").strip()
    if "," in name:
        after = name.split(",", 1)[1].strip()
        if after:
            return after.split()[0].title()
    return ""


def extract_carrier(agent: dict) -> str:
    appts = agent.get("appointments_list") or []
    if appts and isinstance(appts, list):
        return (appts[0].get("company_name") or "").title()
    return ""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--segment",
        choices=["new_licensees", "single_carrier", "ab", "all"],
        default="new_licensees",
    )
    ap.add_argument("--limit", type=int, default=None, help="Max emails to verify (for test runs).")
    ap.add_argument("--dry-run", action="store_true", help="Fetch agents but don't hit ZeroBounce.")
    args = ap.parse_args()

    credits = get_credits()
    print(f"ZeroBounce credits available: {credits}")

    print(f"Fetching {args.segment} from Supabase...")
    agents = fetch_agents(args.segment, args.limit)
    print(f"  → {len(agents)} agents with email")

    if not agents:
        print("No agents to verify. Exiting.")
        return

    if len(agents) > credits and not args.dry_run:
        print(
            f"\n⚠️  Need {len(agents)} credits but only have {credits}. "
            f"Buy more at https://www.zerobounce.net/pricing or use --limit {credits}."
        )
        sys.exit(1)

    if args.dry_run:
        print("Dry run — no verification calls made.")
        print(f"Sample agents: {[a['email'] for a in agents[:3]]}")
        return

    agents_by_email = {a["email"].lower().strip(): a for a in agents if a.get("email")}
    emails = list(agents_by_email.keys())

    print(f"\nVerifying {len(emails)} emails in batches of {BATCH_SIZE}...")
    start = time.time()
    all_results: list[dict] = []
    sendable: list[dict] = []
    status_counts: dict[str, int] = {}

    with LOG_PATH.open("a") as logf:
        for i in range(0, len(emails), BATCH_SIZE):
            batch = emails[i : i + BATCH_SIZE]
            results = verify_batch(batch)
            for r in results:
                addr = (r.get("address") or "").lower()
                status = r.get("status", "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1
                agent = agents_by_email.get(addr, {})
                enriched = {
                    "agent_id": agent.get("id"),
                    "email": addr,
                    "status": status,
                    "sub_status": r.get("sub_status"),
                    "free_email": r.get("free_email"),
                    "did_you_mean": r.get("did_you_mean"),
                    "processed_at": r.get("processed_at"),
                    "state": agent.get("state"),
                }
                logf.write(json.dumps(enriched) + "\n")
                all_results.append({**enriched, "_agent": agent})
                if status in SENDABLE_STATUSES:
                    sendable.append({**enriched, "_agent": agent})
            done = min(i + BATCH_SIZE, len(emails))
            elapsed = time.time() - start
            rate = done / elapsed if elapsed > 0 else 0
            print(
                f"  {done}/{len(emails)} verified  ({rate:.1f}/sec)  "
                f"status so far: {dict(sorted(status_counts.items(), key=lambda x: -x[1]))}"
            )

    # write CSVs segmented by sequence assignment
    seq_a_path = OUT_DIR / "seq_a_new_licensees.csv"
    seq_b_path = OUT_DIR / "seq_b_single_carrier.csv"
    fieldnames = ["email", "firstName", "state", "carrier", "agent_id", "zb_status"]

    with seq_a_path.open("w", newline="") as fa, seq_b_path.open("w", newline="") as fb:
        wa = csv.DictWriter(fa, fieldnames=fieldnames)
        wb = csv.DictWriter(fb, fieldnames=fieldnames)
        wa.writeheader()
        wb.writeheader()
        for row in sendable:
            agent = row["_agent"]
            out = {
                "email": row["email"],
                "firstName": extract_first_name(agent),
                "state": agent.get("state", ""),
                "carrier": extract_carrier(agent),
                "agent_id": agent.get("id"),
                "zb_status": row["status"],
            }
            if agent.get("is_new_licensee"):
                wa.writerow(out)
            elif agent.get("appointments_count") == 1:
                wb.writerow(out)

    print("\n=== DONE ===")
    print(f"Total verified:     {len(all_results)}")
    print(f"Sendable (valid + catch-all): {len(sendable)}  ({len(sendable)/max(len(all_results),1)*100:.1f}%)")
    print(f"Status breakdown:   {status_counts}")
    print(f"CSV → Sequence A:   {seq_a_path}")
    print(f"CSV → Sequence B:   {seq_b_path}")
    print(f"Raw log:            {LOG_PATH}")
    print(f"Credits remaining:  {get_credits()}")


if __name__ == "__main__":
    main()
