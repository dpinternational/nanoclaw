#!/usr/bin/env python3
import datetime as dt
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

# Change via env if needed
# Example: TEST_EMAIL='dpinternational@gmail.com' python3 smartlead_internal_test_send.py
TEST_EMAIL = (os.getenv('TEST_EMAIL') or 'davidprice@tpglife.com').strip()
FIRST_NAME = (os.getenv('TEST_FIRST_NAME') or 'David').strip()
LAST_NAME = (os.getenv('TEST_LAST_NAME') or 'Price').strip()
SEQUENCE_NUMBER = int(os.getenv('TEST_SEQUENCE_NUMBER') or '1')

CAMPAIGNS = [3232436, 3232437]
BASE = 'https://server.smartlead.ai/api/v1'


def get(path: str, **params):
    return requests.get(f'{BASE}{path}', params={'api_key': api_key, **params}, timeout=60)


def post(path: str, payload=None, **params):
    return requests.post(f'{BASE}{path}', params={'api_key': api_key, **params}, json=payload or {}, timeout=60)


def list_leads(campaign_id: int, limit: int = 100):
    # Smartlead API enforces limit <= 100
    r = get(f'/campaigns/{campaign_id}/leads', offset=0, limit=min(limit, 100))
    r.raise_for_status()
    body = r.json() if r.text else {}
    return (body or {}).get('data') or []


def find_lead_id(campaign_id: int, email: str):
    leads = list_leads(campaign_id)
    email_l = email.lower()
    for row in leads:
        lead = row.get('lead') or {}
        if (lead.get('email') or '').lower() == email_l:
            return int(lead['id'])
    return None


def ensure_lead(campaign_id: int, email: str):
    lead_id = find_lead_id(campaign_id, email)
    if lead_id:
        return {'action': 'existing', 'lead_id': lead_id}

    payload = {
        'lead_list': [
            {
                'email': email,
                'first_name': FIRST_NAME,
                'last_name': LAST_NAME,
            }
        ]
    }
    add = post(f'/campaigns/{campaign_id}/leads', payload=payload)
    add.raise_for_status()
    add_body = add.json() if add.text else {}

    lead_id = find_lead_id(campaign_id, email)
    return {
        'action': 'added',
        'lead_id': lead_id,
        'add_response': add_body,
    }


def send_test(campaign_id: int, lead_id: int, seq_number: int):
    payload = {'leadId': lead_id, 'sequenceNumber': seq_number}
    r = post(f'/campaigns/{campaign_id}/send-test-email', payload=payload)
    body = None
    try:
        body = r.json()
    except Exception:
        body = {'raw': r.text[:800]}
    return {'status_code': r.status_code, 'response': body}


def webhook_summary(campaign_id: int, hours_back: int = 2):
    now = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(hours=hours_back)
    params = {
        'fromTime': start.replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
        'toTime': now.replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
    }
    r = get(f'/campaigns/{campaign_id}/webhooks/summary', **params)
    body = None
    try:
        body = r.json()
    except Exception:
        body = {'raw': r.text[:800]}
    return {'status_code': r.status_code, 'query': params, 'response': body}


out = {
    'test_email': TEST_EMAIL,
    'sequence_number': SEQUENCE_NUMBER,
    'campaigns': {},
}

for cid in CAMPAIGNS:
    lead_info = ensure_lead(cid, TEST_EMAIL)
    lead_id = lead_info.get('lead_id')

    campaign_result = {
        'lead': lead_info,
        'send_test': None,
        'webhook_summary_after': None,
    }

    if lead_id:
        campaign_result['send_test'] = send_test(cid, lead_id, SEQUENCE_NUMBER)
    else:
        campaign_result['send_test'] = {'status_code': None, 'response': {'error': 'Could not resolve lead_id'}}

    campaign_result['webhook_summary_after'] = webhook_summary(cid, hours_back=2)
    out['campaigns'][str(cid)] = campaign_result

print(json.dumps(out, indent=2))
