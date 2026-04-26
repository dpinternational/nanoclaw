#!/usr/bin/env python3
"""Update Seq B sequence 4 subject line only. Preserve all other fields."""
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
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env('/Users/davidprice/nanoclaw/insurance-scraper/.env')
api_key = (os.getenv('SMARTLEAD_API_KEY') or '').strip()
if not api_key:
    raise SystemExit('SMARTLEAD_API_KEY missing')

BASE = 'https://server.smartlead.ai/api/v1'
CAMPAIGN_ID = 3232437  # Seq B
TARGET_SEQ = 4
NEW_SUBJECT = 'the link, $4,200/mo'

# Fetch current sequences
r = requests.get(f'{BASE}/campaigns/{CAMPAIGN_ID}/sequences', params={'api_key': api_key}, timeout=30)
r.raise_for_status()
seqs = sorted(r.json(), key=lambda x: x.get('seq_number', 0))

old_subject = None
out = []
for s in seqs:
    n = s.get('seq_number')
    delay_details = s.get('seq_delay_details') or {}
    delay = delay_details.get('delayInDays')
    if delay is None:
        delay = delay_details.get('delay_in_days', 0)

    subject = s.get('subject')
    if n == TARGET_SEQ:
        old_subject = subject
        subject = NEW_SUBJECT

    out.append({
        'seq_number': n,
        'subject': subject,
        'email_body': s.get('email_body') or '',
        'seq_delay_details': {'delay_in_days': int(delay or 0)},
    })

# Apply
w = requests.post(
    f'{BASE}/campaigns/{CAMPAIGN_ID}/sequences',
    params={'api_key': api_key},
    json={'sequences': out},
    timeout=60,
)
w.raise_for_status()

# Verify
v = requests.get(f'{BASE}/campaigns/{CAMPAIGN_ID}/sequences', params={'api_key': api_key}, timeout=30)
v.raise_for_status()
verify = sorted(v.json(), key=lambda x: x.get('seq_number', 0))

print(json.dumps({
    'campaign_id': CAMPAIGN_ID,
    'changed_seq': TARGET_SEQ,
    'old_subject': old_subject,
    'new_subject': NEW_SUBJECT,
    'verify': [{'seq': s.get('seq_number'), 'subject': s.get('subject')} for s in verify],
}, indent=2))
