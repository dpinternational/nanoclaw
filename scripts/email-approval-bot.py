#!/usr/bin/env python3
"""
Telegram approval bot for Daily Email Ops group.

Modes:
  --mode=morning-post       Post In-Review drafts dated today (ET) to TG with buttons.
  --mode=callback-handler   Long-poll getUpdates; handle Approve/Skip/Full-draft & feedback replies.
  --mode=safety-valve       Mark still-In-Review drafts Auto-Skipped.
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
import time
import traceback
from pathlib import Path

import requests
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(p):
        try:
            for line in Path(p).read_text().splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
        except Exception:
            pass

ROOT = Path("/home/david/nanoclaw")
load_dotenv(ROOT / ".env")

TG_TOKEN = os.environ.get("EMAIL_APPROVAL_BOT_TOKEN")
if not TG_TOKEN:
    # fallback: parse .env manually
    for line in (ROOT / ".env").read_text().splitlines():
        if line.startswith("EMAIL_APPROVAL_BOT_TOKEN="):
            TG_TOKEN = line.split("=", 1)[1].strip()
            break

CHAT_ID = -5270945980
NOTION_DB_ID = "34261796-dd5b-81ac-9bef-d5794029302d"
NOTION_KEY = os.environ.get("NOTION_API_KEY") or ""
if not NOTION_KEY:
    for _line in (ROOT / ".env").read_text().splitlines():
        if _line.startswith("NOTION_API_KEY="):
            NOTION_KEY = _line.split("=", 1)[1].strip()
            break
if not NOTION_KEY:
    raise SystemExit("NOTION_API_KEY missing from env / .env")
NOTION_VERSION = "2022-06-28"
NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_KEY}",
    "Notion-Version": NOTION_VERSION,
    "Content-Type": "application/json",
}

DB_PATH = ROOT / "store" / "approval-state.db"
OFFSET_PATH = ROOT / "store" / "approval-bot.offset"
MAUZMA_NAME = "Mauzma"   # no @username available, tag by name only

TG_API = f"https://api.telegram.org/bot{TG_TOKEN}"

# ------------ ET helpers ------------ #
def et_today_iso():
    # ET ~ UTC-5 in winter, UTC-4 in summer; use zoneinfo if available
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    except Exception:
        # approximation: UTC-5
        return (dt.datetime.utcnow() - dt.timedelta(hours=5)).date().isoformat()

def now_iso_utc():
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

# ------------ SQLite ------------ #
def db_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.execute("""CREATE TABLE IF NOT EXISTS approvals(
        notion_page_id TEXT PRIMARY KEY,
        telegram_chat_id INT,
        telegram_message_id INT,
        posted_at TEXT,
        approved_at TEXT,
        approved_subject CHAR(1),
        state TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS feedback(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        notion_page_id TEXT,
        telegram_user_id INT,
        telegram_username TEXT,
        feedback_text TEXT,
        received_at TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS mauzma_sends(
        notion_page_id TEXT PRIMARY KEY,
        mauzma_message_id INT,
        cr_done_at TEXT,
        fb_done_at TEXT,
        sent_date TEXT)""")
    c.commit()
    return c

# ------------ Notion ------------ #
def notion_query_in_review(date_iso, auto_skip_only=False):
    filt = {
        "and": [
            {"property": "Status", "select": {"equals": "In Review"}},
            {"property": "Date Created", "date": {"equals": date_iso}},
        ]
    }
    if auto_skip_only:
        filt["and"].append({"property": "Auto-Skip Eligible", "checkbox": {"equals": True}})
    r = requests.post(
        f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
        headers=NOTION_HEADERS, json={"filter": filt}, timeout=30)
    r.raise_for_status()
    return r.json().get("results", [])

def notion_get_page(page_id):
    r = requests.get(f"https://api.notion.com/v1/pages/{page_id}",
                     headers=NOTION_HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

def notion_update(page_id, properties):
    r = requests.patch(f"https://api.notion.com/v1/pages/{page_id}",
                       headers=NOTION_HEADERS, json={"properties": properties}, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Notion update failed {r.status_code}: {r.text}")
    return r.json()

def notion_blocks(page_id):
    out = []
    cursor = None
    while True:
        url = f"https://api.notion.com/v1/blocks/{page_id}/children?page_size=100"
        if cursor:
            url += f"&start_cursor={cursor}"
        r = requests.get(url, headers=NOTION_HEADERS, timeout=30)
        r.raise_for_status()
        j = r.json()
        out.extend(j.get("results", []))
        if not j.get("has_more"):
            break
        cursor = j.get("next_cursor")
    return out

def rt_plain(rts):
    return "".join(x.get("plain_text", "") for x in (rts or []))

def prop_text(props, name):
    p = props.get(name)
    if not p:
        return ""
    t = p.get("type")
    if t == "rich_text":
        return rt_plain(p["rich_text"])
    if t == "title":
        return rt_plain(p["title"])
    if t == "select":
        return (p.get("select") or {}).get("name", "")
    if t == "number":
        return p.get("number")
    if t == "checkbox":
        return p.get("checkbox")
    return ""

def extract_v2_clean(blocks):
    """Return (first_two_lines, full_body, source_map) from page content."""
    current = None
    buckets = {"v2": [], "sm": []}
    for b in blocks:
        t = b.get("type")
        if t == "heading_2":
            h = rt_plain(b["heading_2"]["rich_text"]).lower()
            if "v_2 clean" in h:
                current = "v2"
            elif "source map" in h:
                current = "sm"
            else:
                current = None
        elif t == "paragraph" and current:
            txt = rt_plain(b["paragraph"]["rich_text"])
            if txt.strip():
                buckets[current].append(txt)
    v2 = "\n\n".join(buckets["v2"])
    sm = "\n\n".join(buckets["sm"])
    first_lines = []
    for line in v2.split("\n"):
        if line.strip():
            first_lines.append(line.strip())
            if len(first_lines) >= 2:
                break
    return "\n".join(first_lines), v2, sm

# ------------ Telegram ------------ #
def tg(method, **payload):
    r = requests.post(f"{TG_API}/{method}", json=payload, timeout=30)
    try:
        j = r.json()
    except Exception:
        raise RuntimeError(f"TG {method} non-json: {r.status_code} {r.text}")
    if not j.get("ok"):
        # soft-fail non-critical calls so the handler doesn't crash
        if method in ("answerCallbackQuery", "editMessageReplyMarkup"):
            print(f"[tg soft-fail] {method}: {j}")
            return None
        raise RuntimeError(f"TG {method} failed: {j}")
    return j["result"]

def approval_keyboard():
    return {"inline_keyboard": [[
        {"text": "✓ Approve A", "callback_data": "approve:A"},
        {"text": "B", "callback_data": "approve:B"},
        {"text": "C", "callback_data": "approve:C"},
        {"text": "❌ Skip", "callback_data": "skip"},
        {"text": "📄 Full draft", "callback_data": "full"},
    ]]}

# ------------ Mode A: morning-post ------------ #
def mode_morning_post():
    today = et_today_iso()
    print(f"[morning-post] querying Notion for In Review on {today}")
    pages = notion_query_in_review(today)
    print(f"[morning-post] found {len(pages)} pages")
    conn = db_conn()
    posted = []
    for p in pages:
        pid = p["id"]
        props = p["properties"]
        # skip if already posted
        row = conn.execute("SELECT telegram_message_id FROM approvals WHERE notion_page_id=?",
                           (pid,)).fetchone()
        if row:
            print(f"[morning-post] already posted {pid} -> msg {row[0]}, skipping")
            continue
        day = prop_text(props, "Day") or "Today"
        subA = prop_text(props, "Subject A")
        subB = prop_text(props, "Subject B")
        subC = prop_text(props, "Subject C")
        preview = prop_text(props, "Preview Text")
        score = prop_text(props, "Editor Score")
        blocks = notion_blocks(pid)
        first2, _, _ = extract_v2_clean(blocks)

        header = day.upper().replace(" — ", " / ")
        text = (
            f"📧 {header}\n\n"
            f"A ▸ {subA}\n"
            f"B ▸ {subB}\n"
            f"C ▸ {subC}\n\n"
            f"Preview: {preview}\n\n"
            f"Body opens:\n{first2}\n\n"
            f"Editor score: {score}\n"
            f"Notion: https://www.notion.so/{pid.replace('-','')}"
        )
        msg = tg("sendMessage", chat_id=CHAT_ID, text=text,
                 reply_markup=approval_keyboard(), disable_web_page_preview=True)
        mid = msg["message_id"]
        conn.execute("""INSERT INTO approvals(notion_page_id, telegram_chat_id, telegram_message_id,
                        posted_at, state) VALUES(?,?,?,?,?)""",
                     (pid, CHAT_ID, mid, now_iso_utc(), "posted"))
        conn.commit()
        posted.append((pid, mid))
        print(f"[morning-post] posted page={pid} msg={mid}")
    print(f"[morning-post] done. posted={len(posted)}")
    return posted

# ------------ Mode C: safety-valve ------------ #
def mode_safety_valve():
    today = et_today_iso()
    pages = notion_query_in_review(today, auto_skip_only=True)
    print(f"[safety-valve] found {len(pages)} still-in-review auto-skip-eligible on {today}")
    conn = db_conn()
    for p in pages:
        pid = p["id"]
        notion_update(pid, {
            "Status": {"select": {"name": "Auto-Skipped"}},
            "Approved By": {"select": {"name": "Auto-skip"}},
            "Approval Timestamp": {"date": {"start": now_iso_utc()}},
        })
        conn.execute("UPDATE approvals SET state='auto-skipped', approved_at=? WHERE notion_page_id=?",
                     (now_iso_utc(), pid))
        conn.commit()
        # edit original message if we have it
        row = conn.execute("SELECT telegram_chat_id, telegram_message_id FROM approvals WHERE notion_page_id=?",
                           (pid,)).fetchone()
        if row:
            try:
                tg("editMessageReplyMarkup", chat_id=row[0], message_id=row[1],
                   reply_markup={"inline_keyboard": []})
            except Exception as e:
                print("edit markup failed:", e)
        print(f"[safety-valve] auto-skipped {pid}")
    tg("sendMessage", chat_id=CHAT_ID,
       text=f"⏰ Auto-skipped today's draft ({len(pages)} page(s)) — no approval received by 11 AM ET. No email will send.")

# ------------ Mauzma send workflow ------------ #
def post_mauzma_send_msg(conn, pid, subject):
    existing = conn.execute("SELECT mauzma_message_id FROM mauzma_sends WHERE notion_page_id=?",
                            (pid,)).fetchone()
    if existing:
        print(f"[mauzma] already pinged for {pid} -> msg {existing[0]}, skipping")
        return existing[0]
    url = f"https://www.notion.so/{pid.replace('-','')}"
    text = (
        "📧 SENDING TODAY\n\n"
        f"Subject: {subject}\n"
        "Send time: 12:30 PM ET today\n"
        "Audience: 100D Engage List (5,690 subs)\n\n"
        f"Draft: {url}\n\n"
        "Steps:\n"
        "1. Open draft link\n"
        "2. Copy body (v_2 section) + subject + preview\n"
        "3. Send test to yourself first in CR\n"
        "4. Schedule for 12:30 PM ET\n"
        "5. Post FB variant to David's personal FB\n"
        "6. Reply 'DONE' when CR is sent\n"
        "7. Reply 'FB DONE' when FB is posted\n\n"
        f"@{MAUZMA_NAME}"
    )
    msg = tg("sendMessage", chat_id=CHAT_ID, text=text, disable_web_page_preview=True)
    mmid = msg["message_id"]
    conn.execute("""INSERT INTO mauzma_sends(notion_page_id, mauzma_message_id, sent_date)
                    VALUES(?,?,?)""", (pid, mmid, et_today_iso()))
    conn.commit()
    print(f"[mauzma] posted send-ping for {pid} -> msg {mmid}")
    return mmid

def get_active_mauzma_send(conn):
    today = et_today_iso()
    return conn.execute("""SELECT notion_page_id, mauzma_message_id, cr_done_at, fb_done_at
                           FROM mauzma_sends WHERE sent_date=?
                           ORDER BY rowid DESC LIMIT 1""", (today,)).fetchone()

# ------------ Mode B: callback-handler ------------ #
def handle_callback(cb, conn):
    data = cb.get("data", "")
    user = cb.get("from", {})
    uname = user.get("username") or user.get("first_name") or "unknown"
    msg = cb.get("message", {})
    chat_id = msg.get("chat", {}).get("id")
    mid = msg.get("message_id")
    row = conn.execute("SELECT notion_page_id, state FROM approvals WHERE telegram_chat_id=? AND telegram_message_id=?",
                       (chat_id, mid)).fetchone()
    if not row:
        tg("answerCallbackQuery", callback_query_id=cb["id"], text="Unknown post (not in DB).")
        return
    pid, state = row

    # check Notion current status to prevent double-action
    page = notion_get_page(pid)
    cur_status = prop_text(page["properties"], "Status")
    if cur_status in ("Approved", "Sent", "Killed", "Auto-Skipped"):
        tg("answerCallbackQuery", callback_query_id=cb["id"],
           text=f"Already actioned: {cur_status}", show_alert=True)
        return

    if data.startswith("approve:"):
        letter = data.split(":", 1)[1]
        subject = prop_text(page["properties"], f"Subject {letter}")
        notion_update(pid, {
            "Status": {"select": {"name": "Approved"}},
            "Approved By": {"select": {"name": "David"}},
            "Approval Timestamp": {"date": {"start": now_iso_utc()}},
            "Approved Version": {"rich_text": [{"type": "text",
                "text": {"content": f"v_2 / Subject {letter}"}}]},
        })
        conn.execute("UPDATE approvals SET state='approved', approved_at=?, approved_subject=? WHERE notion_page_id=?",
                     (now_iso_utc(), letter, pid))
        conn.commit()
        new_text = (f"✅ APPROVED by David (Subject {letter}) — @{MAUZMA_NAME} you're up!\n\n"
                    f"Subject: {subject}\n"
                    f"Notion: https://www.notion.so/{pid.replace('-','')}")
        try:
            tg("editMessageText", chat_id=chat_id, message_id=mid, text=new_text,
               disable_web_page_preview=True)
        except Exception as e:
            print("editMessageText failed:", e)
        tg("answerCallbackQuery", callback_query_id=cb["id"], text=f"Approved {letter}")
        try:
            post_mauzma_send_msg(conn, pid, subject)
        except Exception as e:
            print("post_mauzma_send_msg failed:", e)
            traceback.print_exc()
        return

    if data == "skip":
        notion_update(pid, {
            "Status": {"select": {"name": "Killed"}},
            "Approved By": {"select": {"name": "David"}},
            "Approval Timestamp": {"date": {"start": now_iso_utc()}},
        })
        conn.execute("UPDATE approvals SET state='killed', approved_at=? WHERE notion_page_id=?",
                     (now_iso_utc(), pid))
        conn.commit()
        tg("editMessageText", chat_id=chat_id, message_id=mid, text="❌ SKIPPED by David")
        tg("answerCallbackQuery", callback_query_id=cb["id"], text="Skipped.")
        return

    if data == "full":
        blocks = notion_blocks(pid)
        _, body, sm = extract_v2_clean(blocks)
        body = body or "(no v_2 body found)"
        full = f"FULL DRAFT\n\n{body}\n\n--- SOURCE MAP ---\n{sm or '(none)'}"
        # chunk into 3500-char pieces
        chunks = [full[i:i+3500] for i in range(0, len(full), 3500)] or [full]
        for c in chunks:
            tg("sendMessage", chat_id=chat_id, text=c, reply_to_message_id=mid,
               disable_web_page_preview=True)
        tg("answerCallbackQuery", callback_query_id=cb["id"], text="Sent full draft.")
        return

def handle_mauzma_text(msg, conn):
    """Handle DONE/FB DONE/UNDO DONE keywords from Mauzma (or anyone) in the ops group."""
    if msg.get("chat", {}).get("id") != CHAT_ID:
        return False
    user = msg.get("from", {})
    if user.get("is_bot"):
        return False
    text = (msg.get("text") or "").strip()
    if not text:
        return False
    upper = text.upper()
    import re
    has_done = re.search(r"\bDONE\b", upper) is not None
    has_fb_done = re.search(r"\bFB\s+DONE\b", upper) is not None
    has_undo = re.search(r"\bUNDO\s+DONE\b", upper) is not None
    if not (has_done or has_fb_done or has_undo):
        return False
    # precedence: UNDO DONE > FB DONE > DONE
    active = get_active_mauzma_send(conn)
    if not active:
        tg("sendMessage", chat_id=CHAT_ID,
           text="No active send awaiting confirmation. Check Notion if you meant a different draft.",
           reply_to_message_id=msg["message_id"])
        return True
    pid, mmid, cr_done_at, fb_done_at = active

    if has_undo:
        try:
            notion_update(pid, {
                "CR Sent": {"checkbox": False},
                "Status": {"select": {"name": "Approved"}},
            })
        except Exception as e:
            print("undo notion_update failed:", e)
        conn.execute("UPDATE mauzma_sends SET cr_done_at=NULL WHERE notion_page_id=?", (pid,))
        conn.commit()
        tg("sendMessage", chat_id=CHAT_ID,
           text="↩️ Reverted CR Sent. Awaiting new 'DONE' confirmation.",
           reply_to_message_id=msg["message_id"])
        return True

    if has_fb_done:
        if fb_done_at:
            tg("sendMessage", chat_id=CHAT_ID,
               text=f"Already marked FB posted at {fb_done_at}. Nothing to do.",
               reply_to_message_id=msg["message_id"])
            return True
        ts = now_iso_utc()
        try:
            notion_update(pid, {"FB Posted": {"checkbox": True}})
        except Exception as e:
            print("FB Posted update failed:", e)
        conn.execute("UPDATE mauzma_sends SET fb_done_at=? WHERE notion_page_id=?", (ts, pid))
        conn.commit()
        tg("sendMessage", chat_id=CHAT_ID, text="✅ Full send complete for today!",
           reply_to_message_id=msg["message_id"])
        # refresh active
        active2 = get_active_mauzma_send(conn)
        if active2 and active2[2] and active2[3]:
            tg("sendMessage", chat_id=CHAT_ID,
               text="📤 Today's email delivered. Monitoring reply stats overnight.")
        return True

    # plain DONE -> CR Sent
    if cr_done_at:
        tg("sendMessage", chat_id=CHAT_ID,
           text=f"Already marked sent at {cr_done_at}. Nothing to do.",
           reply_to_message_id=msg["message_id"])
        return True
    ts = now_iso_utc()
    try:
        notion_update(pid, {
            "CR Sent": {"checkbox": True},
            "Status": {"select": {"name": "Sent"}},
        })
    except Exception as e:
        print("CR Sent update failed:", e)
    conn.execute("UPDATE mauzma_sends SET cr_done_at=? WHERE notion_page_id=?", (ts, pid))
    conn.commit()
    # react with a ✓ via setMessageReaction (best-effort)
    try:
        tg("setMessageReaction", chat_id=CHAT_ID, message_id=msg["message_id"],
           reaction=[{"type": "emoji", "emoji": "👌"}])
    except Exception as e:
        print("reaction failed:", e)
    tg("sendMessage", chat_id=CHAT_ID, text="✅ CR send confirmed — FB pending",
       reply_to_message_id=msg["message_id"])
    active2 = get_active_mauzma_send(conn)
    if active2 and active2[2] and active2[3]:
        tg("sendMessage", chat_id=CHAT_ID,
           text="📤 Today's email delivered. Monitoring reply stats overnight.")
    return True

def handle_reply(msg, conn):
    reply_to = msg.get("reply_to_message")
    if not reply_to:
        return
    chat_id = msg["chat"]["id"]
    mid = reply_to.get("message_id")
    row = conn.execute("SELECT notion_page_id FROM approvals WHERE telegram_chat_id=? AND telegram_message_id=?",
                       (chat_id, mid)).fetchone()
    if not row:
        return
    pid = row[0]
    user = msg.get("from", {})
    text = msg.get("text", "").strip()
    if not text:
        return
    # ignore bot's own messages
    if user.get("is_bot"):
        return
    conn.execute("""INSERT INTO feedback(notion_page_id, telegram_user_id, telegram_username,
                    feedback_text, received_at) VALUES(?,?,?,?,?)""",
                 (pid, user.get("id"), user.get("username") or user.get("first_name", ""),
                  text, now_iso_utc()))
    conn.commit()
    tg("sendMessage", chat_id=chat_id, text="📝 Rewrite queued (logged for regen).",
       reply_to_message_id=msg["message_id"])

def mode_callback_handler():
    conn = db_conn()
    offset = 0
    if OFFSET_PATH.exists():
        try:
            offset = int(OFFSET_PATH.read_text().strip())
        except Exception:
            offset = 0
    print(f"[callback-handler] starting, offset={offset}")
    while True:
        try:
            r = requests.get(f"{TG_API}/getUpdates",
                             params={"timeout": 50, "offset": offset,
                                     "allowed_updates": json.dumps(["message", "callback_query"])},
                             timeout=70)
            j = r.json()
            if not j.get("ok"):
                print("getUpdates not ok:", j)
                time.sleep(5)
                continue
            for upd in j.get("result", []):
                offset = upd["update_id"] + 1
                OFFSET_PATH.write_text(str(offset))
                try:
                    if "callback_query" in upd:
                        handle_callback(upd["callback_query"], conn)
                    elif "message" in upd:
                        if not handle_mauzma_text(upd["message"], conn):
                            handle_reply(upd["message"], conn)
                except Exception:
                    traceback.print_exc()
        except requests.exceptions.Timeout:
            continue
        except Exception:
            traceback.print_exc()
            time.sleep(5)

# ------------ main ------------ #
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", required=True,
                    choices=["morning-post", "callback-handler", "safety-valve"])
    args = ap.parse_args()
    if args.mode == "morning-post":
        mode_morning_post()
    elif args.mode == "callback-handler":
        mode_callback_handler()
    elif args.mode == "safety-valve":
        mode_safety_valve()

if __name__ == "__main__":
    main()
