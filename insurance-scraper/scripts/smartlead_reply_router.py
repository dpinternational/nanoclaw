#!/usr/bin/env python3
"""Smartlead Reply Router — tails JSONL webhook events and pings David on Telegram.

Notifies on:
- EMAIL_REPLY (any reply)
- EMAIL_BOUNCE (per lead)
- LEAD_UNSUBSCRIBED (per lead)
- LEAD_CATEGORY_UPDATED (especially "Interested", "Meeting Request")

Tracks last-processed offset in state/reply_router_offset.json so it doesn't double-alert.
Runs as cron every minute, idempotent.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/home/david/insurance-scraper')
JSONL = ROOT / 'state' / 'smartlead_webhook_events.jsonl'
STATE = ROOT / 'state' / 'reply_router_offset.json'
LOG = ROOT / 'logs' / 'reply_router.log'
ENV_FILE = Path('/home/david/nanoclaw/.env')

CHAT_ID = '577469008'  # David's Telegram

ALERT_EVENTS = {
    'EMAIL_REPLY': '💬 Smartlead REPLY',
    'EMAIL_BOUNCE': '📛 Smartlead BOUNCE',
    'LEAD_UNSUBSCRIBED': '🚫 Smartlead UNSUB',
    'LEAD_CATEGORY_UPDATED': '🏷️ Smartlead CATEGORY',
}


def load_env():
    if not ENV_FILE.exists():
        return {}
    out = {}
    for line in ENV_FILE.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def log(msg):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat()
    with LOG.open('a') as f:
        f.write(f'{ts} {msg}\n')


def telegram_send(token, text):
    cmd = [
        'curl', '-sS', '-m', '15', '-X', 'POST',
        f'https://api.telegram.org/bot{token}/sendMessage',
        '-d', f'chat_id={CHAT_ID}',
        '-d', f'text={text}',
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    return r.returncode == 0 and '"ok":true' in (r.stdout or '')


def main():
    env = load_env()
    token = env.get('TELEGRAM_BOT_TOKEN')
    if not token:
        log('NO TELEGRAM_BOT_TOKEN; aborting')
        sys.exit(1)

    if not JSONL.exists():
        log(f'JSONL missing: {JSONL}')
        return 0

    # Load last offset
    last_offset = 0
    if STATE.exists():
        try:
            last_offset = int(json.loads(STATE.read_text()).get('offset', 0))
        except Exception:
            last_offset = 0

    file_size = JSONL.stat().st_size
    if file_size < last_offset:
        # Log was rotated; reset
        last_offset = 0

    if file_size == last_offset:
        return 0  # nothing new

    # Read new lines from offset
    new_events = []
    with JSONL.open('rb') as f:
        f.seek(last_offset)
        chunk = f.read()
        new_offset = file_size
    text = chunk.decode('utf-8', errors='replace')
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except Exception:
            continue
        new_events.append(evt)

    alerts_sent = 0
    for evt in new_events:
        etype = evt.get('event_type')
        if etype not in ALERT_EVENTS:
            continue
        payload = evt.get('payload') or {}
        campaign = payload.get('campaign_name') or f"campaign {payload.get('campaign_id')}"
        email = payload.get('lead_email') or evt.get('lead_email') or 'unknown'
        from_email = payload.get('from_email') or '-'

        prefix = ALERT_EVENTS[etype]

        # Build message
        if etype == 'EMAIL_REPLY':
            sent_msg = (payload.get('reply_message') or {}).get('text') or (payload.get('sent_message') or {}).get('text') or ''
            sent_msg = sent_msg[:300]
            text_msg = (
                f'{prefix}\n'
                f'Campaign: {campaign}\n'
                f'Lead: {email}\n'
                f'From mailbox: {from_email}\n\n'
                f'Reply preview:\n{sent_msg}'
            )
        elif etype == 'LEAD_CATEGORY_UPDATED':
            cat = payload.get('lead_category') or payload.get('new_category') or 'unknown'
            text_msg = (
                f'{prefix}\n'
                f'Campaign: {campaign}\n'
                f'Lead: {email}\n'
                f'Category: {cat}'
            )
        else:
            text_msg = (
                f'{prefix}\n'
                f'Campaign: {campaign}\n'
                f'Lead: {email}'
            )

        if telegram_send(token, text_msg):
            alerts_sent += 1
            log(f'sent: {etype} {email}')
        else:
            log(f'FAILED telegram send for {etype} {email}')

    # Save new offset
    STATE.write_text(json.dumps({'offset': new_offset, 'last_run': datetime.now(timezone.utc).isoformat()}))
    if new_events:
        log(f'processed {len(new_events)} events, sent {alerts_sent} alerts, offset {last_offset}->{new_offset}')

    return 0


if __name__ == '__main__':
    sys.exit(main() or 0)
