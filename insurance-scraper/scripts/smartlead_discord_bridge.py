#!/usr/bin/env python3
"""Smartlead → Discord bridge.

Tails Smartlead webhook JSONL events and posts them to the NanoClaw
"Agent Scraper" Discord channel for unified ops visibility. Sibling to
smartlead_reply_router.py (which DMs Telegram); this script is independent
and uses its own offset state file.

Events bridged:
  EMAIL_REPLY, EMAIL_BOUNCE, LEAD_UNSUBSCRIBED,
  LEAD_CATEGORY_UPDATED, EMAIL_OPENED, EMAIL_CLICKED

EMAIL_OPENED/EMAIL_CLICKED are throttled to at most 1 message / 10 min.
Cron-safe: always exits 0 on errors.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path('/home/david/insurance-scraper')
JSONL = ROOT / 'state' / 'smartlead_webhook_events.jsonl'
STATE = ROOT / 'state' / 'discord_router_offset.json'
LOG = ROOT / 'logs' / 'discord_bridge.log'
ENV_FILE = Path('/home/david/nanoclaw/.env')

CHANNEL_ID = '1488923847288684604'
THROTTLE_SECONDS = 600  # 10 min for OPEN/CLICK

ALERT_EVENTS = {
    'EMAIL_REPLY':           '💬 Smartlead REPLY',
    'EMAIL_BOUNCE':          '📛 Smartlead BOUNCE',
    'LEAD_UNSUBSCRIBED':     '🚫 Smartlead UNSUB',
    'LEAD_CATEGORY_UPDATED': '🏷️ Smartlead CATEGORY',
    'EMAIL_OPENED':          '👀 Smartlead OPEN',
    'EMAIL_CLICKED':         '🖱️ Smartlead CLICK',
}
THROTTLED = {'EMAIL_OPENED', 'EMAIL_CLICKED'}


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
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat()
        with LOG.open('a') as f:
            f.write(f'{ts} {msg}\n')
    except Exception:
        pass


def discord_send(token, content, dry_run=False):
    if dry_run:
        print(f'[DRY-RUN] would post to discord: {content[:120]}')
        return True
    body = json.dumps({'content': content[:1900]})
    cmd = [
        'curl', '-sS', '-m', '15', '-X', 'POST',
        f'https://discord.com/api/v10/channels/{CHANNEL_ID}/messages',
        '-H', f'Authorization: Bot {token}',
        '-H', 'Content-Type: application/json',
        '-d', body,
    ]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        ok = r.returncode == 0 and '"id"' in (r.stdout or '')
        if not ok:
            log(f'discord send failed rc={r.returncode} out={(r.stdout or "")[:200]} err={(r.stderr or "")[:200]}')
        return ok
    except Exception as e:
        log(f'discord send exception: {e}')
        return False


def format_message(etype, payload):
    prefix = ALERT_EVENTS[etype]
    campaign = payload.get('campaign_name') or f"campaign {payload.get('campaign_id')}"
    email = payload.get('lead_email') or 'unknown'

    if etype in ('EMAIL_OPENED', 'EMAIL_CLICKED'):
        # Don't include lead email in plaintext for privacy / volume.
        return f'{prefix}\nCampaign: {campaign}'
    if etype == 'EMAIL_REPLY':
        reply_text = (payload.get('reply_message') or {}).get('text') or \
                     (payload.get('sent_message') or {}).get('text') or ''
        reply_text = reply_text.strip()[:300]
        from_email = payload.get('from_email') or '-'
        return (
            f'{prefix}\n'
            f'Campaign: {campaign}\n'
            f'Lead: {email}\n'
            f'From mailbox: {from_email}\n\n'
            f'Reply preview:\n{reply_text}'
        )
    if etype == 'LEAD_CATEGORY_UPDATED':
        cat = payload.get('lead_category') or payload.get('new_category') or 'unknown'
        return f'{prefix}\nCampaign: {campaign}\nLead: {email}\nCategory: {cat}'
    return f'{prefix}\nCampaign: {campaign}\nLead: {email}'


def load_state():
    if not STATE.exists():
        return {}
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(state):
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state))
    except Exception as e:
        log(f'save_state failed: {e}')


def main():
    dry_run = '--dry-run' in sys.argv

    env = load_env()
    token = env.get('DISCORD_BOT_TOKEN')
    if not token and not dry_run:
        log('NO DISCORD_BOT_TOKEN; aborting (exit 0)')
        return 0

    if not JSONL.exists():
        msg = f'no JSONL found at {JSONL}'
        log(msg)
        if dry_run:
            print(msg)
        return 0

    state = load_state()
    file_size = JSONL.stat().st_size

    # First run: skip historical, set offset to current size.
    if 'offset' not in state:
        save_state({
            'offset': file_size,
            'last_run': datetime.now(timezone.utc).isoformat(),
            'last_throttled_send': 0,
        })
        log(f'initialized offset={file_size} (skipping historical)')
        return 0

    last_offset = int(state.get('offset', 0))
    last_throttled_send = float(state.get('last_throttled_send', 0))

    if file_size < last_offset:
        # rotation/truncation
        last_offset = 0

    if file_size == last_offset:
        return 0

    new_events = []
    with JSONL.open('rb') as f:
        f.seek(last_offset)
        chunk = f.read()
    new_offset = last_offset + len(chunk)
    for line in chunk.decode('utf-8', errors='replace').splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            new_events.append(json.loads(line))
        except Exception:
            continue

    alerts_sent = 0
    skipped_throttle = 0
    now = time.time()

    for evt in new_events:
        etype = evt.get('event_type')
        if etype not in ALERT_EVENTS:
            continue
        payload = evt.get('payload') or {}

        if etype in THROTTLED:
            if now - last_throttled_send < THROTTLE_SECONDS:
                skipped_throttle += 1
                continue

        content = format_message(etype, payload)
        if discord_send(token, content, dry_run=dry_run):
            alerts_sent += 1
            if etype in THROTTLED:
                last_throttled_send = now
                now = time.time()  # refresh
        else:
            log(f'failed send for {etype}')

    save_state({
        'offset': new_offset,
        'last_run': datetime.now(timezone.utc).isoformat(),
        'last_throttled_send': last_throttled_send,
    })

    if new_events:
        log(f'processed {len(new_events)} events, sent {alerts_sent}, '
            f'throttled {skipped_throttle}, offset {last_offset}->{new_offset}')

    return 0


if __name__ == '__main__':
    try:
        sys.exit(main() or 0)
    except Exception as e:
        log(f'fatal: {e}')
        sys.exit(0)
