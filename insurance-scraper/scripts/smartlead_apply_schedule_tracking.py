#!/usr/bin/env python3
"""Apply slow-start schedule + enable tracking on Seq A and Seq B pilot campaigns.
Campaigns remain PAUSED — this only writes settings, does NOT launch.
"""
import json
import os
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
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


load_env('/Users/davidprice/nanoclaw/insurance-scraper/.env')
api_key = (os.getenv('SMARTLEAD_API_KEY') or '').strip()
if not api_key:
    raise SystemExit('SMARTLEAD_API_KEY missing')

BASE = 'https://server.smartlead.ai/api/v1'
CAMPAIGNS = [3232436, 3232437]

# Slow-start defaults
SCHEDULE = {
    'timezone': 'America/New_York',
    'days_of_the_week': [1, 2, 3, 4, 5],   # Mon-Fri
    'start_hour': '09:00',
    'end_hour': '17:00',
    'min_time_btw_emails': 12,              # minutes
    'max_new_leads_per_day': 5,             # slow ramp
}

# Tracking settings
TRACK_SETTINGS = ['DONT_TRACK_EMAIL_OPEN', 'DONT_TRACK_LINK_CLICK']
# Smartlead's track_settings is an EXCLUSION list. Empty list = all tracking ON.
# To enable open + click tracking, set track_settings = []
ENABLE_ALL_TRACKING = []


def get(path, **params):
    return requests.get(f'{BASE}{path}', params={'api_key': api_key, **params}, timeout=45)


def post(path, payload=None, **params):
    return requests.post(
        f'{BASE}{path}',
        params={'api_key': api_key, **params},
        json=payload or {},
        timeout=60,
    )


report = {'schedule': {}, 'tracking': {}, 'verify': {}}

# 1) Apply schedule
for cid in CAMPAIGNS:
    r = post(f'/campaigns/{cid}/schedule', payload=SCHEDULE)
    body = None
    try:
        body = r.json()
    except Exception:
        body = {'raw': r.text[:300]}
    report['schedule'][str(cid)] = {'status': r.status_code, 'body': body}

# 2) Enable open + click tracking
for cid in CAMPAIGNS:
    r = post(
        f'/campaigns/{cid}/settings',
        payload={'track_settings': ENABLE_ALL_TRACKING},
    )
    body = None
    try:
        body = r.json()
    except Exception:
        body = {'raw': r.text[:300]}
    report['tracking'][str(cid)] = {'status': r.status_code, 'body': body}

# 3) Verify
campaigns = get('/campaigns').json()
for c in campaigns:
    if c.get('id') in CAMPAIGNS:
        cid = c['id']
        details = get(f'/campaigns/{cid}').json()
        report['verify'][str(cid)] = {
            'name': c.get('name'),
            'status': c.get('status'),
            'track_settings': c.get('track_settings'),
            'schedule': {
                'timezone': details.get('timezone'),
                'days_of_the_week': details.get('days_of_the_week'),
                'start_hour': details.get('start_hour'),
                'end_hour': details.get('end_hour'),
                'min_time_btw_emails': details.get('min_time_btw_emails'),
                'max_new_leads_per_day': details.get('max_new_leads_per_day'),
            },
        }

print(json.dumps(report, indent=2, default=str))
