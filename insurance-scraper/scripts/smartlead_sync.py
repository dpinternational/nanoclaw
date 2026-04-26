#!/usr/bin/env python3
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
LOG_DIR = ROOT / "logs"
STATE_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)

SNAPSHOT_PATH = STATE_DIR / "smartlead_sync_snapshot.json"
EVENTS_PATH = STATE_DIR / "smartlead_sync_events.jsonl"

BASE = "https://server.smartlead.ai/api/v1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def event(rec: dict) -> None:
    rec = {"ts": now_iso(), **rec}
    with EVENTS_PATH.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    print(json.dumps(rec))


def load_cfg() -> dict:
    load_dotenv()
    return {
        "SUPABASE_URL": os.environ["SUPABASE_URL"],
        "SUPABASE_KEY": os.environ["SUPABASE_KEY"],
        "SMARTLEAD_API_KEY": os.environ["SMARTLEAD_API_KEY"],
    }


def sb_headers(cfg: dict) -> dict:
    return {
        "apikey": cfg["SUPABASE_KEY"],
        "Authorization": f"Bearer {cfg['SUPABASE_KEY']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def sl_get(path: str, cfg: dict, params: dict | None = None):
    p = dict(params or {})
    p["api_key"] = cfg["SMARTLEAD_API_KEY"]
    r = requests.get(f"{BASE}{path}", params=p, timeout=30)
    r.raise_for_status()
    return r.json() if r.text else None


def upsert_supabase(cfg: dict, table: str, row: dict, conflict_col: str) -> tuple[bool, str]:
    url = f"{cfg['SUPABASE_URL']}/rest/v1/{table}"
    headers = {**sb_headers(cfg), "Prefer": f"resolution=merge-duplicates,return=minimal"}
    params = {"on_conflict": conflict_col}
    r = requests.post(url, headers=headers, params=params, json=[row], timeout=30)
    if r.status_code in (200, 201, 204):
        return True, "ok"
    if r.status_code == 404 and "PGRST205" in r.text:
        return False, "table_missing"
    return False, f"http_{r.status_code}:{r.text[:160]}"


def safe_int(v):
    try:
        return int(v)
    except Exception:
        return None


def main() -> int:
    cfg = load_cfg()

    mailboxes = sl_get("/email-accounts", cfg) or []
    campaigns = sl_get("/campaigns", cfg) or []

    campaign_analytics = []
    for c in campaigns:
        cid = c.get("id")
        if cid is None:
            continue
        try:
            analytics = sl_get(f"/campaigns/{cid}/analytics", cfg) or {}
        except Exception as e:
            analytics = {"_error": str(e)}
        campaign_analytics.append({"campaign": c, "analytics": analytics})

    snapshot = {
        "captured_at": now_iso(),
        "mailboxes": mailboxes,
        "campaigns": campaigns,
        "campaign_analytics": campaign_analytics,
    }
    SNAPSHOT_PATH.write_text(json.dumps(snapshot, indent=2))

    # Push mailbox health to Supabase (if table exists)
    table_missing = False
    mailbox_ok = 0
    for m in mailboxes:
        row = {
            "mailbox_id": m.get("id"),
            "from_email": m.get("from_email"),
            "from_name": m.get("from_name"),
            "provider_type": m.get("type"),
            "smtp_ok": m.get("is_smtp_success"),
            "imap_ok": m.get("is_imap_success"),
            "warmup_enabled": bool(m.get("warmup_details")) if m.get("warmup_details") is not None else False,
            "message_per_day": safe_int(m.get("message_per_day")),
            "daily_sent_count": safe_int(m.get("daily_sent_count")),
            "campaign_count": safe_int(m.get("campaign_count")),
            "is_connected_to_campaign": m.get("is_connected_to_campaign"),
            "updated_at": m.get("updated_at"),
            "captured_at": now_iso(),
        }
        ok, msg = upsert_supabase(cfg, "smartlead_mailbox_health", row, "mailbox_id")
        if ok:
            mailbox_ok += 1
        elif msg == "table_missing":
            table_missing = True
            break
        else:
            event({"type": "supabase_error", "table": "smartlead_mailbox_health", "error": msg})

    campaign_ok = 0
    if not table_missing:
        for ca in campaign_analytics:
            c = ca["campaign"]
            a = ca["analytics"] if isinstance(ca["analytics"], dict) else {}
            row = {
                "campaign_id": c.get("id"),
                "campaign_name": c.get("name") or c.get("campaign_name"),
                "status": c.get("status"),
                "created_at_remote": c.get("created_at"),
                "sent_count": safe_int(a.get("sent_count") or a.get("sent") or a.get("total_sent")),
                "open_count": safe_int(a.get("open_count") or a.get("opens")),
                "click_count": safe_int(a.get("click_count") or a.get("clicks")),
                "reply_count": safe_int(a.get("reply_count") or a.get("replies")),
                "bounce_count": safe_int(a.get("bounce_count") or a.get("bounces")),
                "unsubscribe_count": safe_int(a.get("unsubscribe_count") or a.get("unsubscribes")),
                "raw_analytics": a,
                "captured_at": now_iso(),
            }
            ok, msg = upsert_supabase(cfg, "smartlead_campaign_metrics", row, "campaign_id")
            if ok:
                campaign_ok += 1
            elif msg == "table_missing":
                table_missing = True
                break
            else:
                event({"type": "supabase_error", "table": "smartlead_campaign_metrics", "campaign_id": c.get("id"), "error": msg})

    run_row = {
        "run_type": "smartlead_sync",
        "ok": True,
        "details": {
            "mailboxes_fetched": len(mailboxes),
            "campaigns_fetched": len(campaigns),
            "mailboxes_upserted": mailbox_ok,
            "campaigns_upserted": campaign_ok,
            "table_missing": table_missing,
        },
    }
    ok, msg = upsert_supabase(cfg, "smartlead_sync_runs", run_row, "id")
    if not ok and msg != "table_missing":
        event({"type": "supabase_error", "table": "smartlead_sync_runs", "error": msg})

    event(
        {
            "type": "smartlead_sync_summary",
            "mailboxes_fetched": len(mailboxes),
            "campaigns_fetched": len(campaigns),
            "mailboxes_upserted": mailbox_ok,
            "campaigns_upserted": campaign_ok,
            "table_missing": table_missing,
            "schema_sql": str((ROOT / "sql" / "smartlead_tracking_schema.sql").resolve()) if table_missing else None,
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
