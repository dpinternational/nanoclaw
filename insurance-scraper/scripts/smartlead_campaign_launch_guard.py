#!/usr/bin/env python3
"""
Guarded Smartlead campaign launcher/pauser.

Policy:
- ALWAYS runs ready-sender guard before touching campaign status.
- Defaults to dry-run (no remote writes) unless --execute is provided.
- Requires explicit confirm phrase when executing launch.

Usage examples:
  python3 scripts/smartlead_campaign_launch_guard.py --campaign-id 123 --action launch
  python3 scripts/smartlead_campaign_launch_guard.py --campaign-id 123 --action launch --execute --confirm LAUNCH
  python3 scripts/smartlead_campaign_launch_guard.py --campaign-id 123 --campaign-id 456 --action pause --execute --confirm PAUSE
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
GUARD_SCRIPT = ROOT / "scripts" / "enforce_ready_senders.py"
BASE = "https://server.smartlead.ai/api/v1"


def load_cfg() -> dict:
    load_dotenv(ROOT / ".env")
    return {
        "SMARTLEAD_API_KEY": os.getenv("SMARTLEAD_API_KEY", "").strip(),
    }


def require_ready_senders() -> None:
    cmd = ["python3", str(GUARD_SCRIPT), "--strict-auth"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.returncode != 0:
        if proc.stderr:
            print(proc.stderr.rstrip(), file=sys.stderr)
        raise RuntimeError("BLOCKED: ready-sender guard failed; refusing campaign status change")


def sl_request(method: str, path: str, key: str, payload: dict | None = None) -> requests.Response:
    url = f"{BASE}{path}"
    params = {"api_key": key}
    if method == "get":
        return requests.get(url, params=params, timeout=30)
    if method == "post":
        return requests.post(url, params=params, json=payload or {}, timeout=30)
    if method == "put":
        return requests.put(url, params=params, json=payload or {}, timeout=30)
    if method == "patch":
        return requests.patch(url, params=params, json=payload or {}, timeout=30)
    raise ValueError(f"Unsupported method: {method}")


def get_campaign_map(key: str) -> dict[int, dict]:
    r = sl_request("get", "/campaigns", key)
    if r.status_code == 401:
        raise RuntimeError("Smartlead API unauthorized (401). Check SMARTLEAD_API_KEY in insurance-scraper/.env")
    if r.status_code >= 400:
        raise RuntimeError(f"Smartlead /campaigns failed: {r.status_code} {r.text[:200]}")
    data = r.json() if r.text else []
    out: dict[int, dict] = {}
    if isinstance(data, list):
        for c in data:
            try:
                cid = int(c.get("id"))
            except Exception:
                continue
            out[cid] = c
    return out


def attempt_status_update(campaign_id: int, target_status: str, key: str) -> tuple[bool, str]:
    # Multiple candidate API shapes for compatibility.
    paused = target_status != "START"
    candidates: list[tuple[str, str, dict]] = [
        ("post", f"/campaigns/{campaign_id}/status", {"status": target_status}),
        ("put", f"/campaigns/{campaign_id}/status", {"status": target_status}),
        ("patch", f"/campaigns/{campaign_id}", {"status": target_status}),
        ("post", f"/campaigns/{campaign_id}", {"status": target_status}),
        ("patch", f"/campaigns/{campaign_id}", {"campaign_status": target_status}),
        ("post", f"/campaigns/{campaign_id}/status", {"is_paused": paused}),
    ]

    errors: list[str] = []
    for method, path, payload in candidates:
        try:
            r = sl_request(method, path, key, payload)
            if 200 <= r.status_code < 300:
                return True, f"{method.upper()} {path} -> {r.status_code}"
            errors.append(f"{method.upper()} {path} -> {r.status_code} {r.text[:120]}")
        except Exception as e:
            errors.append(f"{method.upper()} {path} -> EXC {e}")
    return False, " | ".join(errors)


def normalize_status(raw: str | None) -> str:
    s = (raw or "").strip().upper()
    if not s:
        return "UNKNOWN"
    return s


def main() -> int:
    ap = argparse.ArgumentParser(description="Guarded Smartlead campaign launcher/pauser")
    ap.add_argument("--campaign-id", action="append", required=True, help="Campaign ID (repeatable)")
    ap.add_argument("--action", choices=["launch", "pause"], required=True)
    ap.add_argument("--execute", action="store_true", help="Perform remote status update (default is dry-run)")
    ap.add_argument("--confirm", default="", help="Required confirmation phrase when using --execute")
    args = ap.parse_args()

    cfg = load_cfg()
    key = cfg["SMARTLEAD_API_KEY"]
    if not key:
        print("Missing SMARTLEAD_API_KEY in .env", file=sys.stderr)
        return 2

    try:
        campaign_ids = [int(x) for x in args.campaign_id]
    except Exception:
        print("All --campaign-id values must be integers", file=sys.stderr)
        return 2

    target = "START" if args.action == "launch" else "PAUSED"
    expected_status = "ACTIVE" if args.action == "launch" else "PAUSED"
    required_confirm = "LAUNCH" if args.action == "launch" else "PAUSE"

    print(f"Policy preflight: enforcing ready-sender guard before {args.action} action")
    require_ready_senders()

    try:
        cmap = get_campaign_map(key)
    except Exception as e:
        print(str(e), file=sys.stderr)
        return 7
    missing = [cid for cid in campaign_ids if cid not in cmap]
    if missing:
        print(f"Campaign IDs not found: {missing}", file=sys.stderr)
        return 3

    print("Current campaign statuses:")
    for cid in campaign_ids:
        c = cmap[cid]
        print(json.dumps({
            "campaign_id": cid,
            "campaign_name": c.get("name") or c.get("campaign_name"),
            "status": c.get("status"),
        }))

    if not args.execute:
        print("DRY-RUN ONLY: no status changes sent. Re-run with --execute --confirm", required_confirm)
        return 0

    if (args.confirm or "").strip().upper() != required_confirm:
        print(f"Refusing execute: --confirm {required_confirm} required", file=sys.stderr)
        return 4

    print(f"Executing status change -> {target}")
    failures = 0
    for cid in campaign_ids:
        ok, msg = attempt_status_update(cid, target, key)
        print(json.dumps({"campaign_id": cid, "target": target, "ok": ok, "detail": msg}))
        if not ok:
            failures += 1

    if failures:
        print(f"Failed updates: {failures}", file=sys.stderr)
        return 5

    # Verify by re-reading campaigns
    try:
        cmap2 = get_campaign_map(key)
    except Exception as e:
        print(f"Post-update verification failed: {e}", file=sys.stderr)
        return 8
    verify_fail = 0
    for cid in campaign_ids:
        seen = normalize_status((cmap2.get(cid) or {}).get("status"))
        expected = normalize_status(expected_status)
        if seen != expected:
            verify_fail += 1
        print(json.dumps({"campaign_id": cid, "expected": expected, "seen": seen, "verified": seen == expected}))

    if verify_fail:
        print(f"Verification mismatch on {verify_fail} campaign(s)", file=sys.stderr)
        return 6

    print("SUCCESS: guarded campaign status update complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
