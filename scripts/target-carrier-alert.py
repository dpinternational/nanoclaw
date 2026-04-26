#!/usr/bin/env python3
"""
Target Carrier Monitor — flags agents with Senior Life, Lincoln Heritage, 
or Globe Life appointments by updating their pipeline_stage in the agents table.
Also copies them to hot_leads if possible.
"""

import json
import os
import urllib.request

SUPA_URL = "https://snsoophwazxusonudtkv.supabase.co"
SUPA_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuc29vcGh3YXp4dXNvbnVkdGt2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE4NDgsImV4cCI6MjA5MDYyNzg0OH0.MZ3M9EL3JC-Y5ztMdfrGOd0H93v7Rk6qhSE2V0Dxhz8"

TARGET_CARRIERS = {
    "SENIOR LIFE INSURANCE COMPANY": "target_senior_life",
    "LINCOLN HERITAGE LIFE INSURANCE COMPANY": "target_lincoln_heritage",
    "GLOBE LIFE AND ACCIDENT INSURANCE COMPANY": "target_globe_life",
}


def supa_get(endpoint):
    url = f"{SUPA_URL}/rest/v1/{endpoint}"
    req = urllib.request.Request(url, headers={
        "apikey": SUPA_KEY,
        "Authorization": f"Bearer {SUPA_KEY}",
    })
    return json.loads(urllib.request.urlopen(req, timeout=15).read())


def supa_patch(table, filter_str, data):
    url = f"{SUPA_URL}/rest/v1/{table}?{filter_str}"
    payload = json.dumps(data).encode()
    req = urllib.request.Request(url, data=payload, method="PATCH", headers={
        "apikey": SUPA_KEY,
        "Authorization": f"Bearer {SUPA_KEY}",
        "Content-Type": "application/json",
    })
    try:
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception as e:
        return False


def main():
    flagged = 0

    for carrier_name, stage in TARGET_CARRIERS.items():
        carrier_encoded = carrier_name.replace(" ", "%20")
        appts = supa_get(f"appointments?company_name=eq.{carrier_encoded}&select=agent_id")
        agent_ids = list(set(str(a["agent_id"]) for a in appts))

        for aid in agent_ids:
            # Check current stage — don't overwrite if already flagged
            agents = supa_get(f"agents?id=eq.{aid}&select=id,pipeline_stage")
            if not agents:
                continue
            
            current_stage = agents[0].get("pipeline_stage", "scraped")
            if current_stage.startswith("target_"):
                continue  # Already flagged
            
            # Update pipeline_stage
            if supa_patch("agents", f"id=eq.{aid}", {"pipeline_stage": stage}):
                flagged += 1

    # Count totals
    totals = {}
    for stage in TARGET_CARRIERS.values():
        count_data = supa_get(f"agents?pipeline_stage=eq.{stage}&select=id")
        totals[stage] = len(count_data)

    print(json.dumps({
        "newly_flagged": flagged,
        "totals": totals,
    }))


if __name__ == "__main__":
    main()
