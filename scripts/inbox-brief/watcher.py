#!/usr/bin/env python3
"""
Reply watcher — polls Telegram for commands and executes them.
"""
import json, re, datetime, pathlib, sys
from typing import List
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from db import get_db, kv_get, kv_set
from lib import (
    gmail_archive_many, gmail_unarchive_many, gmail_read, gmail_reply,
    telegram_send, telegram_get_updates, clean_from, trunc
)

CHAT_ID = "577469008"
UNDO_WINDOW_MIN = 15
PAGE_LIMITS = {"a": 12, "c": 8, "r": 8}
BUCKET_MAP = {"a": "AUTO_CANDIDATE", "c": "CARRIER", "r": "NEEDS_REVIEW"}
CHUNK_SIZE = 20
REVIEW_AUTO_ALLOW = re.compile(
    r"beehiiv|newsletter|daily|digest|no-reply@properties\.booking\.com|no-reply@canva\.com|"
    r"survey\.intuit\.com|zoom\.us|noreply@github\.com|forbes|facebook|instagram|skool|airtable|"
    r"notion|haro|mail\.airtable|mail\.notion|loox\.io|noreply@wetransfer\.com|pricelabs\.co|buzzsprout",
    re.I,
)
REVIEW_AUTO_BLOCK = re.compile(
    r"action required|security|phishing|payment of \$|debt|returned payment|past due|collections|"
    r"equitrust|premiersmi|tpglife|youradvgroup|gmail\.com|icon\.management|ismynest|le\s*parc|"
    r"contracting|assist|re:\s|urgent|verification code|password reset|suspension alert|"
    r"account verification|credit card is approved",
    re.I,
)


def latest_open_brief(conn):
    return conn.execute("SELECT * FROM briefs WHERE status='open' ORDER BY id DESC LIMIT 1").fetchone()


def brief_messages(conn, brief_id, bucket=None):
    sql = "SELECT * FROM classifications WHERE brief_id=? AND final_action='pending'"
    args = [brief_id]
    if bucket:
        sql += " AND bucket=?"
        args.append(bucket)
    sql += " ORDER BY id"
    return conn.execute(sql, args).fetchall()


def expand_refs(conn, brief_id, tokens):
    rows = []
    seen = set()
    for t in tokens:
        t = t.strip().lower()
        if t in ("a", "c", "r"):
            for r in brief_messages(conn, brief_id, bucket=BUCKET_MAP[t]):
                if r["id"] not in seen:
                    seen.add(r["id"])
                    rows.append(r)
        elif re.fullmatch(r"[acr]\d+", t):
            row = conn.execute(
                "SELECT * FROM classifications WHERE brief_id=? AND brief_ref=? AND final_action='pending'",
                (brief_id, t)
            ).fetchone()
            if row and row["id"] not in seen:
                seen.add(row["id"])
                rows.append(row)
    return rows


def _sender_key(email_from: str) -> str:
    s = (email_from or "").strip().lower()
    m = re.search(r'<([^>]+@[^>]+)>', s)
    if m:
        return m.group(1)
    m = re.search(r'([a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})', s)
    if m:
        return m.group(1)
    return s[:120]


def _load_learned_map(conn):
    raw = kv_get(conn, "learn_senders", "{}") or "{}"
    try:
        d = json.loads(raw)
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    return {}


def _save_learned_map(conn, d):
    # keep only top 300 senders by total interactions
    items = sorted(
        d.items(),
        key=lambda kv: -((int(kv[1].get("a", 0) or 0) + int(kv[1].get("k", 0) or 0))),
    )[:300]
    kv_set(conn, "learn_senders", json.dumps(dict(items), separators=(",", ":")))


def _learn_from_rows(conn, rows, action: str):
    if not rows:
        return
    learned = _load_learned_map(conn)
    for r in rows:
        key = _sender_key(r["email_from"])
        if not key:
            continue
        cur = learned.get(key, {"a": 0, "k": 0})
        a = int(cur.get("a", 0) or 0)
        k = int(cur.get("k", 0) or 0)
        if action == "archived":
            a += 1
        elif action == "kept":
            k += 1
        cur["a"] = a
        cur["k"] = k
        learned[key] = cur
    _save_learned_map(conn, learned)


def _review_safe_candidates(conn, brief_id: int) -> List:
    rows = conn.execute(
        "SELECT * FROM classifications WHERE brief_id=? AND final_action='pending' AND bucket='NEEDS_REVIEW' ORDER BY id",
        (brief_id,)
    ).fetchall()
    out = []
    for r in rows:
        frm = (r["email_from"] or "")
        subj = (r["email_subject"] or "")
        hay = f"{frm} {subj}"
        if REVIEW_AUTO_ALLOW.search(hay) and not REVIEW_AUTO_BLOCK.search(hay):
            out.append(r)
    return out


def _next_chunk(conn, brief_id: int):
    cands = _review_safe_candidates(conn, brief_id)
    if not cands:
        kv_set(conn, f"chunk:{brief_id}:last_refs", "[]")
        return []

    key = f"chunk:{brief_id}:offset"
    start = int(kv_get(conn, key, 0) or 0)
    if start >= len(cands):
        start = 0
    end = min(start + CHUNK_SIZE, len(cands))
    kv_set(conn, key, end)

    chosen = cands[start:end]
    refs = [r["brief_ref"] for r in chosen]
    kv_set(conn, f"chunk:{brief_id}:last_refs", json.dumps(refs))
    return chosen


def _normalize_tokens(action: str, raw_tokens, raw_text: str):
    toks = [t.lower() for t in raw_tokens]
    txt = raw_text.lower()

    if action == "archive":
        if ("everything" in txt) or re.search(r"\ball\b", txt):
            return ["a", "c", "r"]

    mapped = []
    stop = {"and", "the", "please", "bucket", "buckets", "all", "to", "of", "for", "me", "rest"}
    for t in toks:
        t = t.strip(",.")
        if t in stop:
            continue
        if t in {"auto", "autos", "auto-candidate", "auto-candidates", "autocandidate", "autocandidates"}:
            mapped.append("a")
        elif t in {"carrier", "carriers"}:
            mapped.append("c")
        elif t in {"review", "reviews"}:
            mapped.append("r")
        elif t in {"everything"}:
            mapped.extend(["a", "c", "r"])
        else:
            mapped.append(t)

    if action == "next" and not mapped:
        return ["a", "c", "r"]
    return mapped


def parse_command(text: str):
    original = text.strip()
    if not original:
        return None, [], original

    clean = original.lstrip("/").strip()
    low = clean.lower()

    if low in {"show me the rest", "show more", "more", "next", "next page"}:
        return "next", ["a", "c", "r"], original
    if low in {"chunk", "next chunk", "safe chunk", "bulk chunk"}:
        return "chunk", [], original
    if low in {"learn", "learning", "learn status", "model status"}:
        return "learn", [], original
    if low in {"undo", "undo last", "revert"}:
        return "undo", [], original

    parts = clean.split()
    action = parts[0].lower() if parts else ""
    synonyms = {
        "archive": "archive",
        "keep": "keep",
        "show": "show",
        "reply": "reply",
        "done": "done",
        "help": "help",
        "status": "status",
        "next": "next",
        "more": "next",
        "chunk": "chunk",
        "bulk": "chunk",
        "learn": "learn",
        "learning": "learn",
        "undo": "undo",
    }
    action = synonyms.get(action, action)
    tokens = parts[1:]
    tokens = _normalize_tokens(action, tokens, low)
    return action, tokens, original


def handle_archive(conn, brief, tokens):
    if any(t.lower() == "chunk" for t in tokens):
        try:
            refs = json.loads(kv_get(conn, f"chunk:{brief['id']}:last_refs", "[]") or "[]")
        except Exception:
            refs = []
        rows = expand_refs(conn, brief["id"], refs)
    else:
        rows = expand_refs(conn, brief["id"], tokens)
    if not rows:
        return "Nothing matched. Try: archive a   or   archive a1 c2   or   archive chunk"

    ids = [r["gmail_id"] for r in rows]
    try:
        gmail_archive_many(ids)
    except Exception as e:
        return f"❌ Gmail archive failed: {e}"

    now = datetime.datetime.now().isoformat()
    class_ids = []
    for r in rows:
        class_ids.append(r["id"])
        conn.execute(
            "UPDATE classifications SET final_action='archived', action_at=?, action_by='user' WHERE id=?",
            (now, r["id"])
        )
    _learn_from_rows(conn, rows, "archived")
    conn.commit()

    undo_payload = {
        "brief_id": brief["id"],
        "gmail_ids": ids,
        "class_ids": class_ids,
        "expires_at": (datetime.datetime.now() + datetime.timedelta(minutes=UNDO_WINDOW_MIN)).isoformat()
    }
    kv_set(conn, "undo_last", json.dumps(undo_payload))

    a = sum(1 for r in rows if r["bucket"] == "AUTO_CANDIDATE")
    c = sum(1 for r in rows if r["bucket"] == "CARRIER")
    rv = sum(1 for r in rows if r["bucket"] == "NEEDS_REVIEW")
    return f"✅ archived {len(rows)} (a:{a} c:{c} r:{rv}) · undo available {UNDO_WINDOW_MIN}m"


def handle_keep(conn, brief, tokens):
    rows = expand_refs(conn, brief["id"], tokens)
    if not rows:
        return "Nothing matched."
    now = datetime.datetime.now().isoformat()
    reset_streak = any(r["bucket"] == "AUTO_CANDIDATE" for r in rows)
    for r in rows:
        conn.execute(
            "UPDATE classifications SET final_action='kept', action_at=?, action_by='user' WHERE id=?",
            (now, r["id"])
        )
    _learn_from_rows(conn, rows, "kept")
    conn.commit()

    if reset_streak:
        kv_set(conn, "streak_day", 0)
        return f"📌 kept {len(rows)}. Streak reset to 0/7 (auto candidate overridden)."
    return f"📌 kept {len(rows)}."


def handle_show(conn, brief, tokens):
    if not tokens:
        return "Usage: show r1"
    t = tokens[0].strip().lower()
    row = conn.execute(
        "SELECT * FROM classifications WHERE brief_id=? AND brief_ref=?",
        (brief["id"], t)
    ).fetchone()
    if not row:
        return f"Ref {t} not found."
    body = gmail_read(row["gmail_id"])
    body = re.sub(r'<[^>]+>', ' ', body)
    body = re.sub(r'&\w+;', ' ', body)
    body = re.sub(r'https?://\S+', '[link]', body)
    body = re.sub(r'\s+', ' ', body).strip()[:2500]
    return f"{row['email_subject']}\nfrom: {row['email_from']}\n\n{body}"


def handle_reply(conn, brief, full_text):
    m = re.match(r'/?reply\s+([acr]\d+)\s+(.+)$', full_text, re.I | re.S)
    if not m:
        return 'Usage: reply r1 "your message"'
    ref = m.group(1).lower()
    body = m.group(2).strip().strip('"').strip("'")
    row = conn.execute(
        "SELECT * FROM classifications WHERE brief_id=? AND brief_ref=?",
        (brief["id"], ref)
    ).fetchone()
    if not row:
        return f"Ref {ref} not found."
    try:
        if 'never settle' not in body.lower():
            body = f"{body}\n\nNever Settle,\nDavid"
        gmail_reply(row["gmail_id"], body)
    except Exception as e:
        return f"❌ reply failed: {e}"

    try:
        gmail_archive_many([row["gmail_id"]])
    except Exception:
        pass

    now = datetime.datetime.now().isoformat()
    conn.execute(
        "UPDATE classifications SET final_action='replied', action_at=?, action_by='user' WHERE id=?",
        (now, row["id"])
    )
    conn.commit()
    return f"📨 replied to {ref} ({clean_from(row['email_from'], 22)}) and archived."


def handle_done(conn, brief):
    pending_auto = conn.execute(
        "SELECT count(*) FROM classifications WHERE brief_id=? AND bucket='AUTO_CANDIDATE' AND final_action='pending'",
        (brief["id"],)
    ).fetchone()[0]
    archived_auto = conn.execute(
        "SELECT count(*) FROM classifications WHERE brief_id=? AND bucket='AUTO_CANDIDATE' AND final_action='archived'",
        (brief["id"],)
    ).fetchone()[0]
    kept_auto = conn.execute(
        "SELECT count(*) FROM classifications WHERE brief_id=? AND bucket='AUTO_CANDIDATE' AND final_action='kept'",
        (brief["id"],)
    ).fetchone()[0]

    streak = int(kv_get(conn, "streak_day", 0) or 0)
    if kept_auto > 0:
        streak = 0
        kv_set(conn, "streak_day", streak)
        streak_msg = "Streak reset 0/7 (you kept auto candidates)."
    elif archived_auto > 0 and pending_auto == 0:
        streak += 1
        kv_set(conn, "streak_day", streak)
        streak_msg = f"Streak: {streak}/7 ✅"
    else:
        streak_msg = f"Streak unchanged: {streak}/7"

    conn.execute("UPDATE briefs SET status='closed' WHERE id=?", (brief["id"],))
    conn.commit()

    if streak >= 7:
        streak_msg += "\n🎉 Trust gate passed. Auto-archive mode is now safe to enable."
    return f"Brief #{brief['id']} closed.\n{streak_msg}"


def handle_status(conn, brief):
    rows = conn.execute(
        "SELECT bucket, final_action, count(*) AS c FROM classifications WHERE brief_id=? GROUP BY bucket, final_action ORDER BY bucket, final_action",
        (brief["id"],)
    ).fetchall()
    streak = int(kv_get(conn, "streak_day", 0) or 0)
    lines = [f"Brief #{brief['id']} status (streak {streak}/7):"]
    for r in rows:
        lines.append(f"  {r['bucket']}: {r['final_action']}={r['c']}")
    return "\n".join(lines)


def handle_learn(conn):
    learned = _load_learned_map(conn)
    if not learned:
        return "Learning: no sender history yet."

    items = sorted(
        learned.items(),
        key=lambda kv: -((int(kv[1].get('a', 0) or 0) + int(kv[1].get('k', 0) or 0)))
    )[:12]
    lines = ["Learning status (top senders):"]
    for sender, stats in items:
        a = int(stats.get("a", 0) or 0)
        k = int(stats.get("k", 0) or 0)
        pref = "keep" if k >= a + 1 and k >= 2 else ("archive" if a >= k + 2 and a >= 3 else "mixed")
        lines.append(f" {sender[:36]:36} a:{a} k:{k} -> {pref}")
    lines.append("Rules: keep>=2 => protect; archive>=3 (+2 over keep) => auto-candidate when safe.")
    msg = "\n".join(lines)
    if len(msg) > 3800:
        msg = msg[:3790] + "\n…"
    return msg


def _next_bucket(conn, brief_id, letter):
    bucket = BUCKET_MAP[letter]
    rows = brief_messages(conn, brief_id, bucket=bucket)
    if not rows:
        return [f"{letter.upper()}: no pending items."]

    lim = PAGE_LIMITS[letter]
    key = f"page:{brief_id}:{letter}"
    start = int(kv_get(conn, key, 0) or 0)
    if start >= len(rows):
        start = 0
    end = min(start + lim, len(rows))
    kv_set(conn, key, end)

    title = {"a": "🗑 AUTO", "c": "📋 CARRIER", "r": "⚠️ REVIEW"}[letter]
    lines = [f"{title} next {end-start}/{len(rows)}:"]
    for r in rows[start:end]:
        d = dict(r)
        lines.append(f" {d['brief_ref']}  {clean_from(d['email_from'],24)} · {trunc(d['email_subject'], 60)}")
        if letter in {"c", "r"}:
            sn = trunc(d.get("snippet", ""), 80)
            if sn:
                lines.append(f"      {sn}")
    rem = len(rows) - end
    if rem > 0:
        lines.append(f"      … +{rem} more (reply: next {letter})")
    return lines


def handle_next(conn, brief, tokens):
    letters = [t for t in tokens if t in {"a", "c", "r"}]
    if not letters:
        letters = ["a", "c", "r"]
    lines = []
    for i, letter in enumerate(letters):
        lines.extend(_next_bucket(conn, brief["id"], letter))
        if i < len(letters) - 1:
            lines.append("")
    msg = "\n".join(lines)
    if len(msg) > 3800:
        msg = msg[:3790] + "\n…"
    return msg


def handle_chunk(conn, brief):
    chosen = _next_chunk(conn, brief["id"])
    if not chosen:
        return "No safe review chunk found right now."

    lines = [f"Safe review chunk ({len(chosen)}):"]
    for r in chosen:
        lines.append(f" {r['brief_ref']}  {clean_from(r['email_from'],24)} · {trunc(r['email_subject'], 60)}")

    refs = " ".join([r["brief_ref"] for r in chosen])
    lines.append("")
    lines.append(f"Quick approve: archive chunk")
    lines.append(f"Explicit: archive {refs}")
    lines.append("Need exceptions? keep rN rM")
    msg = "\n".join(lines)
    if len(msg) > 3800:
        msg = msg[:3790] + "\n…"
    return msg


def handle_undo(conn):
    raw = kv_get(conn, "undo_last", "")
    if not raw:
        return "Nothing to undo."
    try:
        payload = json.loads(raw)
    except Exception:
        return "Undo state is invalid."

    exp = payload.get("expires_at")
    if not exp or datetime.datetime.now() > datetime.datetime.fromisoformat(exp):
        return "Undo expired."

    ids = payload.get("gmail_ids") or []
    class_ids = payload.get("class_ids") or []
    if not ids or not class_ids:
        return "Undo payload empty."

    try:
        gmail_unarchive_many(ids)
    except Exception as e:
        return f"❌ undo failed: {e}"

    q = ",".join(["?"] * len(class_ids))
    conn.execute(f"UPDATE classifications SET final_action='pending', action_at=NULL, action_by='pending' WHERE id IN ({q})", class_ids)
    conn.commit()
    kv_set(conn, "undo_last", "")
    return f"↩️ restored {len(class_ids)} emails to pending/inbox."


def process_update(conn, update):
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return None
    text = (msg.get("text") or "").strip()
    if not text:
        return None
    if str(msg.get("chat", {}).get("id")) != CHAT_ID:
        return None

    action, tokens, original = parse_command(text)
    if not action:
        return None

    known = {"archive", "keep", "show", "reply", "done", "help", "status", "learn", "next", "chunk", "undo"}
    if action not in known:
        return None

    brief = latest_open_brief(conn)
    if action not in {"undo", "learn"} and not brief:
        return "No open brief."

    now = datetime.datetime.now().isoformat()
    try:
        if action == "archive":
            reply = handle_archive(conn, brief, tokens)
        elif action == "keep":
            reply = handle_keep(conn, brief, tokens)
        elif action == "show":
            reply = handle_show(conn, brief, tokens)
        elif action == "reply":
            reply = handle_reply(conn, brief, original)
        elif action == "done":
            reply = handle_done(conn, brief)
        elif action == "status":
            reply = handle_status(conn, brief)
        elif action == "learn":
            reply = handle_learn(conn)
        elif action == "next":
            reply = handle_next(conn, brief, tokens)
        elif action == "chunk":
            reply = handle_chunk(conn, brief)
        elif action == "undo":
            reply = handle_undo(conn)
        elif action == "help":
            reply = (
                "Commands:\n"
                "archive a|c|r|a1 c2\n"
                "keep a3\n"
                "show r1\n"
                "next a|c|r (or just next)\n"
                "chunk (safe review batch)\n"
                "archive chunk\n"
                "reply r1 \"text\"\n"
                "undo (within 15m)\n"
                "done\n"
                "status\n"
                "learn"
            )
        else:
            reply = None
    except Exception as e:
        reply = f"❌ error: {e}"

    if brief is not None:
        conn.execute(
            "INSERT INTO user_actions(brief_id, received_at, command, parsed_action, targets, result) VALUES(?,?,?,?,?,?)",
            (brief["id"], now, original, action, json.dumps(tokens), (reply or "")[:500])
        )
        conn.commit()
    return reply


def main():
    conn = get_db()
    last_offset = int(kv_get(conn, "tg_offset", 0) or 0)
    now = datetime.datetime.now().isoformat(timespec="seconds")

    try:
        updates = telegram_get_updates(offset=last_offset + 1 if last_offset else None, timeout=20)
    except Exception as e:
        print(f"{now} watcher_error: {e}")
        return

    processed = 0
    sent = 0
    for u in updates:
        uid = u["update_id"]
        if uid > last_offset:
            last_offset = uid
        processed += 1
        reply = process_update(conn, u)
        if reply:
            telegram_send(CHAT_ID, reply, parse_mode="")
            sent += 1

    kv_set(conn, "tg_offset", last_offset)
    print(f"{now} watcher_ok updates={processed} replies={sent} offset={last_offset}")


if __name__ == "__main__":
    main()
