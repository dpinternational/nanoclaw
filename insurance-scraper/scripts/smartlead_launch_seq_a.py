#!/usr/bin/env python3
"""Launch Seq A pilot campaign (3232436). Requires --confirm LAUNCH."""
import json
import os
import sys
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
CAMPAIGN_ID = 3232436
CAMPAIGN_NAME = 'Seq A - New Licensees PILOT (25)'

confirm = '--confirm' in sys.argv and 'LAUNCH' in sys.argv

# Pre-flight checks
report = {'campaign_id': CAMPAIGN_ID, 'name': CAMPAIGN_NAME, 'preflight': {}}

# 1) Status check
campaigns = requests.get(f'{BASE}/campaigns', params={'api_key': api_key}, timeout=30).json()
c = next((x for x in campaigns if x.get('id') == CAMPAIGN_ID), None)
if not c:
    raise SystemExit(f'Campaign {CAMPAIGN_ID} not found')
report['preflight']['current_status'] = c.get('status')
report['preflight']['max_leads_per_day'] = c.get('max_leads_per_day')
report['preflight']['min_time_btwn_emails'] = c.get('min_time_btwn_emails')
report['preflight']['scheduler_cron_value'] = c.get('scheduler_cron_value')
report['preflight']['track_settings'] = c.get('track_settings')
report['preflight']['unsubscribe_text_present'] = bool(c.get('unsubscribe_text'))

# 2) Lead count
l = requests.get(f'{BASE}/campaigns/{CAMPAIGN_ID}/leads', params={'api_key': api_key, 'offset': 0, 'limit': 1}, timeout=30).json()
report['preflight']['total_leads'] = l.get('total_leads')

# 3) Email accounts
ea = requests.get(f'{BASE}/campaigns/{CAMPAIGN_ID}/email-accounts', params={'api_key': api_key}, timeout=30).json()
report['preflight']['email_accounts_count'] = len(ea) if isinstance(ea, list) else 0

# 4) Sequences
sq = requests.get(f'{BASE}/campaigns/{CAMPAIGN_ID}/sequences', params={'api_key': api_key}, timeout=30).json()
report['preflight']['sequence_count'] = len(sq)

# Validation
errors = []
if report['preflight']['current_status'] != 'PAUSED':
    errors.append(f"Expected PAUSED, got {report['preflight']['current_status']}")
if not report['preflight']['scheduler_cron_value']:
    errors.append('No schedule set')
if int(report['preflight']['total_leads'] or 0) < 1:
    errors.append('No leads')
if report['preflight']['email_accounts_count'] < 1:
    errors.append('No email accounts')
if report['preflight']['sequence_count'] < 1:
    errors.append('No sequences')

report['preflight']['errors'] = errors

if errors:
    print(json.dumps(report, indent=2, default=str))
    raise SystemExit(f'Preflight FAILED: {errors}')

if not confirm:
    report['action'] = 'DRY RUN — not launched. Re-run with: --confirm LAUNCH'
    print(json.dumps(report, indent=2, default=str))
    sys.exit(0)

# LAUNCH
launch = requests.post(
    f'{BASE}/campaigns/{CAMPAIGN_ID}/status',
    params={'api_key': api_key},
    json={'status': 'START'},
    timeout=30,
)
report['launch'] = {'status': launch.status_code}
try:
    report['launch']['body'] = launch.json()
except Exception:
    report['launch']['body'] = launch.text[:300]

# Verify post-launch status
post = requests.get(f'{BASE}/campaigns', params={'api_key': api_key}, timeout=30).json()
pc = next((x for x in post if x.get('id') == CAMPAIGN_ID), None)
report['post_launch_status'] = (pc or {}).get('status')

print(json.dumps(report, indent=2, default=str))
