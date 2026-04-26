#!/usr/bin/env python3
"""
Fail-safe guard: block cold outreach sends from non-ready mailboxes.

What it enforces
- Only from_email values listed in config/ready_for_outreach_emails.txt are allowed.
- Any Smartlead mailbox with campaign_count > 0 that is not on allowlist is flagged.
- Optional strict mode also fails if allowlisted mailbox has SMTP/IMAP errors.

This script is read-only (no API writes). Use it as a preflight gate before any send/launch.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALLOWLIST = ROOT / "config" / "ready_for_outreach_emails.txt"
DEFAULT_SNAPSHOT = ROOT / "state" / "smartlead_sync_snapshot.json"


def parse_allowlist(path: Path) -> set[str]:
    if not path.exists():
        raise FileNotFoundError(f"Allowlist file not found: {path}")
    out: set[str] = set()
    for raw in path.read_text().splitlines():
        line = raw.strip().lower()
        if not line or line.startswith("#"):
            continue
        out.add(line)
    if not out:
        raise RuntimeError(f"Allowlist is empty: {path}")
    return out


def load_snapshot(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"Snapshot not found: {path}")
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON snapshot {path}: {e}") from e


def main() -> int:
    ap = argparse.ArgumentParser(description="Enforce send allowlist for ready sender mailboxes")
    ap.add_argument("--allowlist", default=str(DEFAULT_ALLOWLIST), help="Path to ready sender allowlist")
    ap.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT), help="Path to Smartlead snapshot JSON")
    ap.add_argument("--strict-auth", action="store_true", help="Also require SMTP+IMAP success for allowlisted rows")
    args = ap.parse_args()

    allowlist = parse_allowlist(Path(args.allowlist))
    snap = load_snapshot(Path(args.snapshot))
    mailboxes = snap.get("mailboxes") or []

    if not isinstance(mailboxes, list):
        raise RuntimeError("Snapshot field 'mailboxes' must be a list")

    violating_connected: list[dict] = []
    allowlist_auth_issues: list[dict] = []

    for m in mailboxes:
        from_email = (m.get("from_email") or "").strip().lower()
        if not from_email:
            continue

        campaign_count = int(m.get("campaign_count") or 0)
        smtp_ok = bool(m.get("is_smtp_success"))
        imap_ok = bool(m.get("is_imap_success"))

        if campaign_count > 0 and from_email not in allowlist:
            violating_connected.append(
                {
                    "from_email": from_email,
                    "campaign_count": campaign_count,
                    "smtp_ok": smtp_ok,
                    "imap_ok": imap_ok,
                }
            )

        if args.strict_auth and from_email in allowlist and (not smtp_ok or not imap_ok):
            allowlist_auth_issues.append(
                {
                    "from_email": from_email,
                    "smtp_ok": smtp_ok,
                    "imap_ok": imap_ok,
                }
            )

    summary = {
        "captured_at": snap.get("captured_at"),
        "allowlist_size": len(allowlist),
        "mailboxes_seen": len(mailboxes),
        "violating_connected_mailboxes": violating_connected,
        "allowlisted_auth_issues": allowlist_auth_issues,
        "policy": "never_send_from_non_ready_mailbox",
    }
    print(json.dumps(summary, indent=2))

    if violating_connected:
        print("\nBLOCK: Non-ready mailboxes are connected to campaigns.", file=sys.stderr)
        return 2

    if allowlist_auth_issues:
        print("\nBLOCK: Allowlisted mailbox auth health failed strict check.", file=sys.stderr)
        return 3

    print("\nPASS: Ready sender policy check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
