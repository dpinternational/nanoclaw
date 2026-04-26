#!/usr/bin/env python3
"""Populate Notion OB Tracker from Price Group OB.xlsx"""
import json, subprocess, openpyxl, time, os, sys

NK = os.environ.get("NOTION_API_KEY") or os.environ.get("NOTION_TOKEN")
if not NK:
    sys.exit("NOTION_API_KEY not set in environment")
DB = "34161796-dd5b-81ad-8fde-c59c5ad1b9e3"

wb = openpyxl.load_workbook('/home/david/nanoclaw/data/Price Group OB.xlsx', data_only=True)
ws = wb['Sheet1']

carrier_cols = {
    'Wellcare': 6, 'Zing': 7, 'Aetna': 8, 'Anthem': 9,
    'Humana': 10, 'UHC': 11, 'Molina': 12, 'Cigna': 13, 'Devoted': 14,
}

def normalize_status(val):
    if not val: return None
    v = str(val).strip()
    if v in ('X', 'x'): return 'X'
    if 'Pending' in v: return v
    if 'Needs Release' in v: return 'Needs Release'
    if v in ('NA', 'N/A', 'na'): return 'NA'
    if v == '': return None
    return v

count = 0
errors = 0
for row_idx in range(2, min(ws.max_row + 1, 970)):
    name = ws.cell(row_idx, 1).value
    if not name or not str(name).strip(): continue
    name = str(name).strip()
    
    npn = str(ws.cell(row_idx, 2).value or '').strip()
    phone = str(ws.cell(row_idx, 3).value or '').strip()
    email = str(ws.cell(row_idx, 4).value or '').strip()
    notes = str(ws.cell(row_idx, 5).value or '').strip()
    
    props = {
        "Agent Name": {"title": [{"text": {"content": name}}]},
    }
    if npn: props["NPN"] = {"rich_text": [{"text": {"content": npn}}]}
    if phone: props["Phone"] = {"phone_number": phone}
    if email and '@' in email: props["Email"] = {"email": email}
    if notes: props["Notes"] = {"rich_text": [{"text": {"content": notes[:200]}}]}
    
    for carrier, col in carrier_cols.items():
        status = normalize_status(ws.cell(row_idx, col).value)
        if status:
            props[carrier] = {"select": {"name": status}}
    
    data = {"parent": {"database_id": DB}, "properties": props}
    
    r = subprocess.run(
        ["curl", "-s", "-X", "POST", "https://api.notion.com/v1/pages",
         "-H", f"Authorization: Bearer {NK}",
         "-H", "Notion-Version: 2022-06-28",
         "-H", "Content-Type: application/json",
         "-d", json.dumps(data)],
        capture_output=True, text=True, timeout=10,
    )
    resp = json.loads(r.stdout)
    if resp.get("id"):
        count += 1
    else:
        errors += 1
        if errors <= 3:
            print(f"Error on {name}: {resp.get('message', str(resp)[:100])}")
    
    if count % 50 == 0 and count > 0:
        print(f"  {count} agents added...")
    
    # Rate limit
    if count % 3 == 0:
        time.sleep(0.4)

print(f"\nDone: {count} agents added, {errors} errors")
