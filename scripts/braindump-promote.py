#!/usr/bin/env python3
"""
Brain Dump -> Notion promotion bridge.

Triggered when David explicitly tells Brain Dump "send to notion" (or
equivalent). The Brain Dump agent writes a file here with frontmatter +
body, and this cron picks it up and pushes to Notion Email Drafts DB.

Two actions supported:
  1. create new Approved draft
  2. update existing draft with an FB variant (for repurposing)

Runs every 2 min via david's crontab:
  */2 * * * * cd /home/david/nanoclaw && python3 scripts/braindump-promote.py >> logs/braindump-promote.log 2>&1

File formats (YAML frontmatter + body). Brain Dump agent writes to
/workspace/group/pending-emails/<timestamp>-<slug>.md — the agent's
container path that maps to groups/telegram_braindump/pending-emails/ here.

=== ACTION 1: create email draft ===
  ---
  action: email
  subject: "the subject line"
  preview: "preview text (~100 chars)"
  send_date: 2026-04-21          # optional; defaults to next weekday
  theme: "Wednesday — Mindset"    # optional; auto-picked from send_date
  source_msg_id: "braindump:123"  # optional; for provenance
  ---
  <email body>

=== ACTION 2: add FB variant to existing Notion draft ===
  ---
  action: fb_variant
  notion_page_id: "abc123-def456"       # which email to attach FB to
  # OR match-by-subject if page id unknown:
  match_subject: "the subject line"
  ---
  <fb post body>

Successful files move to pending-emails/pushed/.
Failures move to pending-emails/errors/ with a stderr log line.
"""
import json, os, re, sys, time
import datetime as dt
from pathlib import Path
import requests

ROOT = Path("/home/david/nanoclaw")
PENDING = ROOT / "groups" / "telegram_braindump" / "pending-emails"
PUSHED = PENDING / "pushed"
ERRORS = PENDING / "errors"
NOTION_DB = "34261796-dd5b-81ac-9bef-d5794029302d"

# Pull Notion key from the same sources email-drafter-v2.py uses.
KEY = None
for p in [ROOT / ".env", Path("/home/david/.config/nanoclaw/env"),
          ROOT / "scripts" / "email-drafter-v2.py"]:
    try:
        for line in open(p):
            if line.startswith("NOTION_API_KEY="):
                KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
            m = re.search(r"ntn_[a-zA-Z0-9]+", line)
            if m and not KEY:
                KEY = m.group(0)
        if KEY:
            break
    except FileNotFoundError:
        continue

if not KEY:
    print("[fatal] cannot find NOTION_API_KEY", file=sys.stderr)
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {KEY}",
    "Notion-Version": "2022-06-28",
    "Content-Type": "application/json",
}

DAY_THEMES = {
    0: "Monday — Education",
    1: "Tuesday — Agent Proof",
    2: "Wednesday — Mindset",
    3: "Thursday — Behind Scenes",
    4: "Friday — Momentum",
    5: "Saturday — Community",
    6: "Sunday — Inspiration",
}


def parse_file(path: Path):
    """Return (frontmatter dict, body str)."""
    text = path.read_text(encoding="utf-8")
    fm = {}
    body = text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if m:
        raw_fm, body = m.group(1), m.group(2)
        for line in raw_fm.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, body.strip()


def next_weekday(d: dt.date) -> dt.date:
    """Next Mon–Fri; skips Sat/Sun."""
    add = 1
    while (d + dt.timedelta(days=add)).weekday() >= 5:
        add += 1
    return d + dt.timedelta(days=add)


def _rt(s, limit=1900):
    return [{"type": "text", "text": {"content": (s or "")[:limit]}}]


def notion_find_by_subject(subject: str):
    """Return first page whose Subject A or Subject title matches."""
    r = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DB}/query",
        headers=HEADERS,
        json={
            "page_size": 10,
            "filter": {
                "or": [
                    {"property": "Subject", "title": {"contains": subject[:50]}},
                    {"property": "Subject A", "rich_text": {"contains": subject[:50]}},
                ]
            },
            "sorts": [{"timestamp": "created_time", "direction": "descending"}],
        },
        timeout=30,
    )
    if r.status_code != 200:
        return None
    results = r.json().get("results", [])
    return results[0] if results else None


def action_email(fm, body):
    """Create a new Approved email draft in Notion."""
    if not body:
        return False, "empty body"

    today = dt.date.today()
    if fm.get("send_date"):
        try:
            send_date = dt.date.fromisoformat(fm["send_date"]).isoformat()
        except ValueError:
            send_date = next_weekday(today).isoformat()
    else:
        send_date = next_weekday(today).isoformat()

    theme = fm.get("theme")
    if not theme or theme not in DAY_THEMES.values():
        send_dt = dt.date.fromisoformat(send_date)
        theme = DAY_THEMES.get(send_dt.weekday(), DAY_THEMES[0])

    subject = fm.get("subject") or "(no subject)"
    preview = fm.get("preview") or body[:140]
    source = fm.get("source_msg_id", "braindump-interactive")
    wc = len(body.split())

    props = {
        "Subject": {"title": _rt(subject)},
        "Status": {"select": {"name": "Approved"}},
        "Day": {"select": {"name": theme}},
        "Subject A": {"rich_text": _rt(subject)},
        "Preview Text": {"rich_text": _rt(preview)},
        "Source": {"rich_text": _rt(f"BRAIN DUMP INTERACTIVE ({source}) — David-blessed in chat. Skip approval queue.")},
        "Word Count": {"number": wc},
        "Date Created": {"date": {"start": today.isoformat()}},
        "Send Date": {"date": {"start": send_date}},
        "Assigned To": {"select": {"name": "Mauzma"}},
        "Editor Score": {"number": 10},
        "Editor Notes": {"rich_text": _rt("Promoted from Brain Dump chat. David hand-blessed this draft.")},
        "Approved By": {"select": {"name": "David"}},
        "Approval Timestamp": {"date": {"start": dt.datetime.utcnow().isoformat() + "Z"}},
        "Auto-Skip Eligible": {"checkbox": False},
    }

    children = []
    for para in body.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        for chunk in [para[i:i + 1900] for i in range(0, len(para), 1900)]:
            children.append({
                "object": "block", "type": "paragraph",
                "paragraph": {"rich_text": _rt(chunk)},
            })

    r = requests.post(
        "https://api.notion.com/v1/pages",
        headers=HEADERS,
        json={"parent": {"database_id": NOTION_DB}, "properties": props, "children": children},
        timeout=30,
    )
    if r.status_code == 200:
        pid = r.json().get("id", "")
        return True, f"created {pid} send_date={send_date} theme={theme}"
    return False, f"notion create failed {r.status_code}: {r.text[:300]}"


def action_fb_variant(fm, body):
    """Attach an FB variant to an existing Notion draft."""
    if not body:
        return False, "empty fb body"

    page_id = fm.get("notion_page_id")
    if not page_id and fm.get("match_subject"):
        page = notion_find_by_subject(fm["match_subject"])
        if page:
            page_id = page["id"]
    if not page_id:
        return False, "no notion_page_id and match_subject did not resolve"

    r = requests.patch(
        f"https://api.notion.com/v1/pages/{page_id}",
        headers=HEADERS,
        json={"properties": {"FB Variant": {"rich_text": _rt(body)}}},
        timeout=30,
    )
    if r.status_code == 200:
        return True, f"updated FB variant on {page_id}"
    return False, f"notion update failed {r.status_code}: {r.text[:300]}"


def main():
    PUSHED.mkdir(parents=True, exist_ok=True)
    ERRORS.mkdir(parents=True, exist_ok=True)
    if not PENDING.exists():
        PENDING.mkdir(parents=True, exist_ok=True)
        return

    files = [f for f in sorted(PENDING.iterdir())
             if f.is_file() and f.suffix == ".md"]
    if not files:
        return

    for f in files:
        try:
            fm, body = parse_file(f)
            action = fm.get("action", "email").lower()
            if action == "email":
                ok, msg = action_email(fm, body)
            elif action in ("fb_variant", "fb", "facebook"):
                ok, msg = action_fb_variant(fm, body)
            else:
                ok, msg = False, f"unknown action: {action}"

            if ok:
                print(f"[ok] {f.name}: {msg}")
                f.rename(PUSHED / f.name)
            else:
                print(f"[fail] {f.name}: {msg}", file=sys.stderr)
                f.rename(ERRORS / f.name)
        except Exception as e:
            print(f"[exception] {f.name}: {e}", file=sys.stderr)
            try:
                f.rename(ERRORS / f.name)
            except Exception:
                pass


if __name__ == "__main__":
    main()
