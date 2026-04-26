#!/usr/bin/env python3
"""
TPG UnCaged Morning Report — David's short-format daily summary.

Runs on the Hetzner server at 2:45 AM AST (6:45 UTC) via cron.
Uses the Andy bot (TPG_REPORT_BOT_TOKEN) to DM David directly.
Reuses the mature parser from tpg-daily-digest-hermes.py.

Format:
  📊 TPG UnCaged — {day_name}
  💰 ${total_ap} AP · {total_sales} sales · {unique_agents} agents

  🏆 TOP 5
    Agent         $X,XXX  carrier  (N sales)
    ...

  +{N more agents} · +${remaining_ap} in smaller wins

  🎯 Standouts: {short story if any}
  🔇 Quiet: {names of usually-active who went silent}
"""

import json
import os
import re
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

# reuse existing parser
sys.path.insert(0, '/home/david/nanoclaw/scripts')
import importlib.util
spec = importlib.util.spec_from_file_location(
    'digest', '/home/david/nanoclaw/scripts/tpg-daily-digest-hermes.py'
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

BOT_TOKEN = os.environ.get("TPG_REPORT_BOT_TOKEN", "")
CHAT_ID = "577469008"
DB = "/home/david/nanoclaw/store/messages.db"
ast = ZoneInfo("America/Puerto_Rico")   # AST year-round (no DST)

CLEAN_NAMES = {
    "⚔️❤️🙏Kari🙏❤️⚔️": "Kari",
    "🦋⚡️JESSICA⚡️🦋": "Jessica",
}


def clean_name(name):
    if name in CLEAN_NAMES:
        return CLEAN_NAMES[name]
    cleaned = re.sub(r'[^\w\s.\'-]', '', name).strip()
    return cleaned if cleaned else name


def format_report(data):
    date_str = data['date']
    try:
        day_name = datetime.strptime(date_str, "%Y-%m-%d").strftime("%A %b %-d")
    except Exception:
        day_name = date_str

    if data['message_count'] == 0:
        return f"📊 TPG UnCaged — {day_name}\n\nNo activity yesterday."

    sales = data['sales']
    total_ap = data['total_ap']
    total_sales = sum(s.get('num_sales', 1) for s in sales)
    unique_agents = len(set(s['agent'] for s in sales))

    # Consolidate per agent
    agent_totals = defaultdict(lambda: {'ap': 0, 'num_sales': 0, 'carriers': set(), 'content': []})
    for s in sales:
        a = s['agent']
        agent_totals[a]['ap'] += s['amount']
        agent_totals[a]['num_sales'] += s.get('num_sales', 1)
        if s['carrier'] not in ('Unknown', 'Multiple'):
            agent_totals[a]['carriers'].add(s['carrier'])
        agent_totals[a]['content'].append(s.get('content', ''))

    sorted_agents = sorted(agent_totals.items(), key=lambda x: -x[1]['ap'])

    lines = [f"📊 TPG UnCaged — {day_name}", ""]
    lines.append(f"💰 ${total_ap:,.0f} AP · {total_sales} sales · {unique_agents} agents")
    lines.append("")

    # Top 5
    lines.append("🏆 TOP 5")
    top5 = sorted_agents[:5]
    for agent, info in top5:
        name = clean_name(agent)
        carriers = ', '.join(sorted(info['carriers'])) if info['carriers'] else ''
        sales_str = f" · {info['num_sales']} sales" if info['num_sales'] > 1 else ''
        carrier_str = f" · {carriers}" if carriers else ''
        lines.append(f"  {name:18s}  ${info['ap']:>8,.0f}{carrier_str}{sales_str}")

    # Roll-up rest
    if len(sorted_agents) > 5:
        rest = sorted_agents[5:]
        rest_ap = sum(info['ap'] for _, info in rest)
        rest_sales = sum(info['num_sales'] for _, info in rest)
        lines.append("")
        lines.append(f"+ {len(rest)} more agents · ${rest_ap:,.0f} AP · {rest_sales} sales")

    # Standouts — short highlights
    standouts = []
    for msg in data.get('_messages', []) or []:
        content = msg.get('content', '')
        sender = clean_name(msg.get('sender_name', ''))
        if len(content) < 30 or len(content) > 220:
            continue
        lower = content.lower()
        if any(w in lower for w in [
            'best day', 'first sale', 'overcame', 'referr',
            'free lead', 'callback', 'wrote this lady', 'thank you',
        ]):
            standouts.append(f"{sender}: {content.strip()[:140]}")
    if standouts:
        lines.append("")
        lines.append("🎯 STANDOUTS")
        for s in standouts[:3]:
            lines.append(f"  • {s}")

    # Quiet — agents who posted last week but not yesterday
    quiet = data.get('quiet_agents', [])
    if quiet:
        lines.append("")
        names = ', '.join(
            f"{clean_name(q['agent'])} ({q['prior_week_msgs']})"
            for q in quiet[:5]
        )
        lines.append(f"🔇 Quiet: {names}")

    return '\n'.join(lines)


def send_telegram(text):
    if not BOT_TOKEN:
        print("[no TPG_REPORT_BOT_TOKEN env var — printing instead]")
        print(text)
        return True
    payload = json.dumps({
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data=payload, headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=15)
        return True
    except Exception as e:
        print(f"Telegram error: {e}", file=sys.stderr)
        print(text)
        return False


def main():
    # Optional CLI override: python tpg-uncaged-morning-report.py 2026-04-17
    if len(sys.argv) > 1:
        date_str = sys.argv[1]
    else:
        # Report yesterday (in AST)
        date_str = (datetime.now(ast) - timedelta(days=1)).strftime("%Y-%m-%d")

    data = mod.analyze(DB, date_str)
    messages, _ = mod.get_messages(DB, date_str)
    data['_messages'] = messages

    report = format_report(data)
    if send_telegram(report):
        total_sales = sum(s.get('num_sales', 1) for s in data['sales'])
        print(f"Sent morning report for {date_str}: {data['message_count']} msgs, {total_sales} sales, ${data['total_ap']:,.2f} AP")


if __name__ == "__main__":
    main()
