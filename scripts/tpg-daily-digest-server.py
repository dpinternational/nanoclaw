#!/usr/bin/env python3
"""
TPG Daily Digest — Server-side version
Runs at 3 AM ET, reports YESTERDAY's full production.
Uses the Hermes parser for sales extraction.
Sends formatted report to David's Telegram.
"""

import json
import os
import re
import sys
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

# Use the Hermes parser (has the good sales extraction)
sys.path.insert(0, '/home/david/nanoclaw/scripts')
import importlib.util
spec = importlib.util.spec_from_file_location('digest', '/home/david/nanoclaw/scripts/tpg-daily-digest-hermes.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = "577469008"
DB = "/home/david/nanoclaw/store/messages.db"
et = ZoneInfo("America/New_York")

# Emoji name cleanup
CLEAN_NAMES = {
    "⚔️❤️🙏Kari🙏❤️⚔️": "Kari",
    "🦋⚡️JESSICA⚡️🦋": "Jessica",
}


def clean_name(name):
    if name in CLEAN_NAMES:
        return CLEAN_NAMES[name]
    # Strip common emoji patterns
    cleaned = re.sub(r'[^\w\s.\'-]', '', name).strip()
    return cleaned if cleaned else name


def get_prior_week_avg_ap(date_str):
    """Get average daily AP for the prior 7 days for comparison."""
    import sqlite3
    day = datetime.strptime(date_str, "%Y-%m-%d")
    total_ap = 0
    days_with_data = 0
    for i in range(1, 8):
        d = (day - timedelta(days=i)).strftime("%Y-%m-%d")
        data = mod.analyze(DB, d)
        if data['total_ap'] > 0:
            total_ap += data['total_ap']
            days_with_data += 1
    return total_ap / days_with_data if days_with_data > 0 else 0


def format_report(data):
    """Format the digest in the clean style David approved."""
    date_str = data['date']
    
    # Parse day of week
    try:
        day_name = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A %B %d")
    except:
        day_name = date_str
    
    if data['message_count'] == 0:
        return f"📊 TPG UnCaged — {day_name}\n\nNo activity today."
    
    sales = data['sales']
    total_ap = data['total_ap']
    total_sales = sum(s.get('num_sales', 1) for s in sales)
    unique_agents = len(set(s['agent'] for s in sales))
    
    # Consolidate: group by agent, sum their AP
    agent_totals = defaultdict(lambda: {'ap': 0, 'num_sales': 0, 'carriers': set(), 'content': []})
    for s in sales:
        agent = s['agent']
        agent_totals[agent]['ap'] += s['amount']
        agent_totals[agent]['num_sales'] += s.get('num_sales', 1)
        if s['carrier'] not in ('Unknown', 'Multiple'):
            agent_totals[agent]['carriers'].add(s['carrier'])
        agent_totals[agent]['content'].append(s.get('content', ''))
    
    # Sort by AP descending
    sorted_agents = sorted(agent_totals.items(), key=lambda x: -x[1]['ap'])
    
    lines = [f"📊 TPG UnCaged — {day_name}", ""]
    lines.append(f"💰 ${total_ap:,.0f} AP | {total_sales} sales | {unique_agents} agents on the board")
    lines.append("")
    
    # Top producers (consolidated by agent)
    lines.append("🏆 TOP PRODUCERS")
    for agent, info in sorted_agents[:12]:
        name = clean_name(agent)
        carriers = ', '.join(info['carriers']) if info['carriers'] else ''
        carrier_str = f"  {carriers}" if carriers else ''
        sales_str = f"  {info['num_sales']} sales" if info['num_sales'] > 1 else ''
        
        # Check for notable story in their messages
        story = ''
        for content in info['content']:
            lower = content.lower()
            if 'best day' in lower or 'first' in lower:
                story = ' 🔥 BEST DAY'
            elif 'referr' in lower or 'ref ' in lower:
                story = ' (referrals)'
            elif 'overcame' in lower or 'objection' in lower:
                story = ' (overcame objections)'
            elif 'free lead' in lower or 'callback' in lower:
                story = ' (free lead came back)'
        
        lines.append(f"  {name:20s} ${info['ap']:>10,.2f} AP{carrier_str}{sales_str}{story}")
    
    # Highlights — look for compelling stories
    lines.append("")
    highlights = []
    for msg in data.get('_messages', []):
        content = msg.get('content', '')
        sender = clean_name(msg.get('sender_name', ''))
        if len(content) > 80 and any(w in content.lower() for w in [
            'best day', 'overcame', 'referr', 'ref gave', 'chain',
            'free lead', 'callback', 'wrote this lady', 'first sale',
            'VCC', 'helped me', 'thank you',
        ]):
            # Extract the good part
            highlight = content[:200].replace('\n', ' ')
            highlights.append(f"  • {sender}: {highlight}")
    
    if highlights:
        lines.append("📖 HIGHLIGHTS")
        for h in highlights[:4]:
            lines.append(h)
    
    # Activity
    lines.append("")
    lines.append(f"📈 {data['message_count']} messages | {data['active_agents']} agents active")
    chatters = data.get('top_chatters', [])
    if chatters:
        top5 = ', '.join(f'{clean_name(n)} ({c})' for n, c in chatters[:5])
        lines.append(f"  Most active: {top5}")
    
    # Quiet agents
    quiet = data.get('quiet_agents', [])
    if quiet:
        lines.append("")
        lines.append("🔇 QUIET (active last week, silent today)")
        names = ', '.join(f'{clean_name(q["agent"])} ({q["prior_week_msgs"]})' for q in quiet[:5])
        lines.append(f"  {names}")
    
    # Comparison to last week
    try:
        avg_ap = get_prior_week_avg_ap(date_str)
        if avg_ap > 0:
            pct = ((total_ap - avg_ap) / avg_ap) * 100
            arrow = "📈" if pct > 0 else "📉"
            lines.append("")
            lines.append(f"vs last week avg: ${avg_ap:,.0f}/day — {'+' if pct > 0 else ''}{pct:.0f}% {arrow}")
    except Exception:
        pass
    
    return '\n'.join(lines)


def send_telegram(text):
    if not BOT_TOKEN:
        print(text)
        return True
    payload = json.dumps({"chat_id": CHAT_ID, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data=payload, headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except Exception as e:
        print(f"Telegram error: {e}", file=sys.stderr)
        print(text)
        return False


def main():
    # Report yesterday since this runs at 3 AM
    yesterday = (datetime.now(et) - timedelta(days=1)).strftime("%Y-%m-%d")
    
    # Get full analysis from the Hermes parser
    data = mod.analyze(DB, yesterday)
    
    # Also get raw messages for highlights
    messages, _ = mod.get_messages(DB, yesterday)
    data['_messages'] = messages
    
    report = format_report(data)
    
    if send_telegram(report):
        total_sales = sum(s.get('num_sales', 1) for s in data['sales'])
        print(f"Sent digest for {yesterday}: {data['message_count']} msgs, {total_sales} sales, ${data['total_ap']:,.2f} AP")
    

if __name__ == "__main__":
    main()
