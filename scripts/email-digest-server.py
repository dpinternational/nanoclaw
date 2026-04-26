#!/usr/bin/env python3
"""
Morning Email Digest — Server-side version
Reads Gmail via googleapis (already installed on server),
classifies emails, sends summary to David's Telegram.
"""

import json
import os
import re
import subprocess
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
DAVID_CHAT_ID = "577469008"
NANOCLAW = "/home/david/nanoclaw"

VIP_SENDERS = {
    "tpglife.com": "TPG Life",
    "callagylaw.com": "Callagy Law",
    "premiersmi.com": "Premier SMI",
    "mutualofomaha.com": "Mutual of Omaha",
    "transamerica.com": "Transamerica",
    "corebridge.com": "Corebridge",
    "campaignrefinery.com": "Campaign Refinery",
}

TPG_PEOPLE = {
    "sandra": "Sandra Futch (Recruiter)",
    "gina": "Gina Soriano (Ops)",
    "contracting": "Contracting Dept",
    "kendra": "Kendra Wilson",
    "hiring": "Hiring Dept",
}

JUNK_RE = [
    r"noreply@", r"no-reply@", r"notifications@",
    r"@linkedin\.com", r"@facebookmail\.com", r"@x\.com",
    r"newsletter@", r"marketing@", r"promotions@", r"@zapier\.com",
]

URGENT_RE = [
    r"contracting@tpglife\.com", r"hiring@tpglife\.com",
    r"urgent", r"asap", r"immediately", r"deadline", r"expir", r"cancel",
]


def fetch_emails():
    """Fetch unread emails using Node.js + googleapis on the server."""
    node_script = r"""
const {google} = require('googleapis');
const fs = require('fs'), path = require('path');
const credDir = '/home/david/.gmail-mcp';
const keys = JSON.parse(fs.readFileSync(path.join(credDir, 'gcp-oauth.keys.json'), 'utf-8'));
const tokens = JSON.parse(fs.readFileSync(path.join(credDir, 'credentials.json'), 'utf-8'));
const config = keys.installed || keys.web || keys;
const auth = new google.auth.OAuth2(config.client_id, config.client_secret, config.redirect_uris?.[0]);
auth.setCredentials(tokens);
auth.on('tokens', t => {
  const c = JSON.parse(fs.readFileSync(path.join(credDir, 'credentials.json'), 'utf-8'));
  Object.assign(c, t);
  fs.writeFileSync(path.join(credDir, 'credentials.json'), JSON.stringify(c, null, 2));
});
const gmail = google.gmail({version:'v1',auth});
async function main() {
  const res = await gmail.users.messages.list({
    userId:'me', q:'is:unread -category:promotions -category:social newer_than:2d', maxResults:50
  });
  const msgs = res.data.messages || [];
  const results = [];
  for (const m of msgs) {
    try {
      const d = await gmail.users.messages.get({userId:'me',id:m.id,format:'metadata',
        metadataHeaders:['From','Subject','Date']});
      const h = d.data.payload.headers;
      results.push({
        id: m.id,
        from: h.find(x=>x.name==='From')?.value||'',
        subject: h.find(x=>x.name==='Subject')?.value||'',
        date: h.find(x=>x.name==='Date')?.value||'',
        snippet: d.data.snippet||'',
      });
    } catch(e) {}
  }
  console.log(JSON.stringify({emails:results}));
}
main().catch(e=>console.error(JSON.stringify({error:e.message})));
"""
    script_path = f"/tmp/_email_fetch_{os.getpid()}.js"
    with open(script_path, "w") as f:
        f.write(node_script)

    result = subprocess.run(
        ["node", script_path],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, "HOME": "/home/david",
             "NODE_PATH": f"{NANOCLAW}/node_modules"},
        cwd=NANOCLAW,
    )
    try:
        for i, ch in enumerate(result.stdout):
            if ch == '{':
                return json.loads(result.stdout[i:])
        return {"emails": [], "error": "No JSON"}
    except Exception as e:
        return {"emails": [], "error": str(e)}


def classify(email):
    from_addr = email.get("from", "").lower()
    subject = email.get("subject", "").lower()
    snippet = email.get("snippet", "").lower()
    combined = f"{from_addr} {subject} {snippet}"

    domain_match = re.search(r"@([\w.-]+)", from_addr)
    domain = domain_match.group(1) if domain_match else ""
    name_match = re.search(r"^([^<]+)", email.get("from", ""))
    sender_name = name_match.group(1).strip().strip('"') if name_match else from_addr

    is_vip = any(d in domain for d in VIP_SENDERS)
    tpg_person = next((p for k, p in TPG_PEOPLE.items() if k in from_addr or k in sender_name.lower()), "")
    is_junk = any(re.search(p, from_addr) for p in JUNK_RE)
    is_urgent = any(re.search(p, combined) for p in URGENT_RE)

    if is_urgent and is_vip: priority = "CRITICAL"
    elif is_urgent or tpg_person: priority = "HIGH"
    elif is_vip: priority = "MEDIUM"
    elif is_junk: priority = "JUNK"
    else: priority = "NORMAL"

    return {
        "from": sender_name, "subject": email.get("subject", "(no subject)"),
        "snippet": email.get("snippet", "")[:120],
        "priority": priority, "is_junk": is_junk,
    }


def format_digest(emails):
    et_now = datetime.now(ZoneInfo("America/New_York"))
    date_str = et_now.strftime("%A %B %d")

    classified = [classify(e) for e in emails]
    priority_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "NORMAL": 3, "JUNK": 4}
    classified.sort(key=lambda e: priority_order.get(e["priority"], 5))

    critical = [e for e in classified if e["priority"] == "CRITICAL"]
    high = [e for e in classified if e["priority"] == "HIGH"]
    medium = [e for e in classified if e["priority"] == "MEDIUM"]
    normal = [e for e in classified if e["priority"] == "NORMAL"]
    junk = [e for e in classified if e["is_junk"]]

    lines = [f"📧 Morning Inbox — {date_str}", ""]

    if not classified:
        lines.append("Inbox clear ✓")
        return "\n".join(lines)

    if critical:
        lines.append(f"🔴 NEEDS ATTENTION ({len(critical)})")
        for e in critical:
            lines.append(f"  • {e['from'][:25]}: {e['subject'][:50]}")
            if e['snippet']:
                lines.append(f"    {e['snippet'][:80]}")
        lines.append("")

    if high:
        lines.append(f"🟠 HIGH ({len(high)})")
        for e in high:
            lines.append(f"  • {e['from'][:25]}: {e['subject'][:50]}")
        lines.append("")

    if medium:
        lines.append(f"🟡 VIP ({len(medium)})")
        for e in medium[:5]:
            lines.append(f"  • {e['from'][:25]}: {e['subject'][:50]}")
        if len(medium) > 5:
            lines.append(f"  + {len(medium) - 5} more")
        lines.append("")

    if normal:
        lines.append(f"📬 ROUTINE ({len(normal)})")
        for e in normal[:3]:
            lines.append(f"  • {e['from'][:25]}: {e['subject'][:50]}")
        if len(normal) > 3:
            lines.append(f"  + {len(normal) - 3} more")
        lines.append("")

    if junk:
        lines.append(f"🗑 JUNK ({len(junk)}) — safe to ignore")

    return "\n".join(lines)


def send_telegram(text):
    if not BOT_TOKEN:
        print(text)
        return
    data = json.dumps({"chat_id": DAVID_CHAT_ID, "text": text}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data=data, headers={"Content-Type": "application/json"},
    )
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}", file=__import__('sys').stderr)


def main():
    data = fetch_emails()
    if data.get("error") and not data.get("emails"):
        send_telegram(f"📧 Morning Inbox — Error fetching emails: {data['error'][:100]}")
        return

    emails = data.get("emails", [])
    report = format_digest(emails)
    send_telegram(report)
    print(f"Sent email digest: {len(emails)} emails")


if __name__ == "__main__":
    main()
