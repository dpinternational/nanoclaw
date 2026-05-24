#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timedelta, timezone

from lib import (
    RUN_PATH,
    SELF_EMAIL,
    STATE_PATH,
    classify_license,
    detect_booked,
    gmail_read,
    gmail_reply,
    gmail_search,
    interest_score,
    is_negative_sender,
    load_json,
    make_final_bump_reply,
    make_followup_reply,
    make_initial_reply,
    parse_date,
    save_json,
    sender_email,
    truncate,
)

QUERY = f'in:anywhere newer_than:45d -from:{SELF_EMAIL}'
MAX_RESULTS = 200


def eligible_labels(msg: dict) -> bool:
    labels = set(msg.get('labels') or [])
    if 'SPAM' in labels:
        return False
    return 'INBOX' in labels or 'UNREAD' in labels


def latest_by_thread(messages):
    best = {}
    for msg in messages:
        tid = msg.get('threadId') or msg.get('id')
        dt = parse_date(msg.get('date', '')) or datetime(1970, 1, 1, tzinfo=timezone.utc)
        cur = best.get(tid)
        if not cur:
            best[tid] = (dt, msg)
        elif dt >= cur[0]:
            best[tid] = (dt, msg)
    return [v[1] for v in best.values()]


def stage_for_thread(state_row):
    if not state_row:
        return 'initial'
    status = state_row.get('status', 'initial')
    sent_at = parse_date(state_row.get('sent_at', ''))
    now = datetime.now(timezone.utc)
    if status in {'closed', 'booked'}:
        return None
    if status == 'sent1' and sent_at and now >= sent_at + timedelta(days=1):
        return 'followup1'
    if status == 'sent2' and sent_at and now >= sent_at + timedelta(days=2):
        return 'followup2'
    if status in {'sent1', 'sent2', 'sent3'}:
        return None
    return 'initial'


def build_reply(stage, license_status):
    if stage == 'initial':
        return make_initial_reply(license_status)
    if stage == 'followup1':
        return make_followup_reply()
    if stage == 'followup2':
        return make_final_bump_reply()
    return ''


def next_status(stage):
    return {'initial': 'sent1', 'followup1': 'sent2', 'followup2': 'sent3'}.get(stage, 'sent1')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--query', default=QUERY)
    ap.add_argument('--max', type=int, default=MAX_RESULTS)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    state = load_json(STATE_PATH, {})
    raw_messages = gmail_search(args.query, max_results=args.max)
    messages = latest_by_thread(raw_messages)
    actions = []
    now_iso = datetime.now(timezone.utc).isoformat()

    for msg in messages:
        thread_id = msg.get('threadId') or msg.get('id')
        from_header = msg.get('from', '')
        if is_negative_sender(from_header):
            continue
        if not eligible_labels(msg):
            continue
        body = gmail_read(msg['id'])
        score = interest_score(msg, body)
        if score < 3:
            continue
        if detect_booked(body):
            state[thread_id] = {
                'status': 'booked',
                'last_message_id': msg['id'],
                'last_seen_at': now_iso,
                'sent_at': state.get(thread_id, {}).get('sent_at', ''),
            }
            actions.append({
                'action': 'mark_booked',
                'thread_id': thread_id,
                'from': from_header,
                'subject': msg.get('subject', ''),
            })
            continue

        license_status = classify_license(body)
        stage = stage_for_thread(state.get(thread_id, {}))
        if not stage:
            continue
        reply = build_reply(stage, license_status)
        if not reply:
            continue

        result = {'dry_run': True} if args.dry_run else gmail_reply(msg['id'], reply)
        if not args.dry_run:
            state[thread_id] = {
                'status': next_status(stage),
                'sent_at': now_iso,
                'last_message_id': msg['id'],
                'last_seen_at': now_iso,
                'last_sent_reply': reply,
            }
        actions.append({
            'action': 'send_reply',
            'thread_id': thread_id,
            'message_id': msg['id'],
            'gmail_result': result,
            'from': from_header,
            'from_email': sender_email(from_header),
            'subject': msg.get('subject', ''),
            'license_status': license_status,
            'stage': stage,
            'score': score,
            'body_preview': truncate(body),
            'reply': reply,
        })

    save_json(STATE_PATH, state)
    payload = {
        'ran_at': now_iso,
        'query': args.query,
        'messages_considered': len(messages),
        'actions_count': len(actions),
        'dry_run': args.dry_run,
        'actions': actions,
    }
    save_json(RUN_PATH, payload)
    print(json.dumps(payload, indent=2))


if __name__ == '__main__':
    main()
