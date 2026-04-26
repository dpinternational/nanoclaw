#!/usr/bin/env python3
import json
import os
import re
from pathlib import Path

import requests


def load_env(path: str):
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


load_env("/Users/davidprice/nanoclaw/insurance-scraper/.env")
api_key = (os.getenv("SMARTLEAD_API_KEY") or "").strip()
if not api_key:
    raise SystemExit("SMARTLEAD_API_KEY not found in env")

base = "https://server.smartlead.ai/api/v1"

campaign_tags = {
    3232436: "seq_a_pilot",
    3232437: "seq_b_pilot",
}

# Existing webhooks to clone/update (NO DELETE)
source_webhooks = {
    3232436: 561971,
    3232437: 561972,
}

summary = {
    "created_webhooks": {},
    "sequence_rewrites": {},
    "verification": {},
}


def api_get(path, **params):
    r = requests.get(f"{base}{path}", params={"api_key": api_key, **params}, timeout=45)
    return r


def api_post(path, payload=None, **params):
    r = requests.post(
        f"{base}{path}",
        params={"api_key": api_key, **params},
        json=payload or {},
        timeout=60,
    )
    return r


# 1) Create replacement webhooks with EMAIL_OPENED + EMAIL_CLICKED enabled (NO DELETE)
for campaign_id, webhook_id in source_webhooks.items():
    src = api_get(f"/webhook/{webhook_id}")
    src.raise_for_status()
    src_data = (src.json() or {}).get("data") or {}

    event_map = dict(src_data.get("event_type_map") or {})
    event_map["EMAIL_OPENED"] = True
    event_map["EMAIL_CLICKED"] = True

    create_payload = {
        "name": f"{src_data.get('name', f'campaign {campaign_id} webhook')} (click-open)",
        "webhook_url": src_data.get("webhook_url") or "https://89.167.109.12.sslip.io/smartlead/webhook",
        "email_campaign_id": campaign_id,
        "event_type_map": event_map,
        "association_type": 3,
    }

    created = api_post("/webhook/create", payload=create_payload)
    created.raise_for_status()
    created_json = created.json() if created.text else {}
    created_data = (created_json or {}).get("data") or {}
    new_id = created_data.get("id")
    if isinstance(new_id, dict):
        new_id = new_id.get("id")

    summary["created_webhooks"][str(campaign_id)] = {
        "source_webhook_id": webhook_id,
        "new_webhook_id": new_id,
        "name": create_payload["name"],
        "webhook_url": create_payload["webhook_url"],
        "event_type_map": event_map,
    }


# 2) Rewrite sequences with UTM-tagged Skool links
base_skool = "https://www.skool.com/insurance/about"
for campaign_id, tag in campaign_tags.items():
    seq_resp = api_get(f"/campaigns/{campaign_id}/sequences")
    seq_resp.raise_for_status()
    seqs = sorted(seq_resp.json(), key=lambda x: x.get("seq_number", 0))

    rewritten = []
    changed = 0
    for row in seqs:
        seq_number = row.get("seq_number")
        delay_details = row.get("seq_delay_details") or {}
        delay = delay_details.get("delayInDays")
        if delay is None:
            delay = delay_details.get("delay_in_days", 0)

        body = row.get("email_body") or ""
        original = body

        # Normalize existing skool variants to base first
        body = re.sub(r"https://www\.skool\.com/insurance/about[^\s\)\]\"<]*", base_skool, body)

        utm = (
            f"{base_skool}?utm_source=smartlead"
            f"&utm_medium=cold_email"
            f"&utm_campaign={tag}"
            f"&utm_content=seq{seq_number}"
        )
        body = body.replace(base_skool, utm)

        if body != original:
            changed += 1

        rewritten.append(
            {
                "seq_number": seq_number,
                "subject": row.get("subject"),
                "email_body": body,
                "seq_delay_details": {"delay_in_days": int(delay or 0)},
            }
        )

    save = api_post(f"/campaigns/{campaign_id}/sequences", payload={"sequences": rewritten})
    save.raise_for_status()

    summary["sequence_rewrites"][str(campaign_id)] = {
        "sequences_total": len(rewritten),
        "sequences_changed": changed,
        "campaign_tag": tag,
    }


# 3) Verify webhooks + URLs
for campaign_id, tag in campaign_tags.items():
    # verify new webhook
    new_id = summary["created_webhooks"].get(str(campaign_id), {}).get("new_webhook_id")
    if new_id:
        v = api_get(f"/webhook/{new_id}")
        if v.status_code == 200:
            d = (v.json() or {}).get("data") or {}
            em = d.get("event_type_map") or {}
            summary["verification"][f"webhook_{campaign_id}"] = {
                "webhook_id": new_id,
                "email_opened": em.get("EMAIL_OPENED"),
                "email_clicked": em.get("EMAIL_CLICKED"),
                "ok": bool(em.get("EMAIL_OPENED") and em.get("EMAIL_CLICKED")),
            }

    # verify sequence URLs
    s = api_get(f"/campaigns/{campaign_id}/sequences")
    s.raise_for_status()
    urls = []
    all_ok = True
    for row in s.json():
        seq_number = row.get("seq_number")
        found = re.findall(r"https://www\.skool\.com/insurance/about[^\s\)\]\"<]*", row.get("email_body") or "")
        for u in found:
            ok = (
                "utm_source=smartlead" in u
                and "utm_medium=cold_email" in u
                and f"utm_campaign={tag}" in u
                and f"utm_content=seq{seq_number}" in u
            )
            urls.append({"seq": seq_number, "url": u, "utm_ok": ok})
            if not ok:
                all_ok = False

    summary["verification"][f"sequence_{campaign_id}"] = {
        "urls_found": len(urls),
        "all_urls_utm_ok": all_ok,
        "sample": urls[:10],
    }

print(json.dumps(summary, indent=2))
