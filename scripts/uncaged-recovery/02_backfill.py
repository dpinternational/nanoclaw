#!/usr/bin/env python3
"""
Backfill fetched Telegram history into nanoclaw's messages.db.

Handles JSONL rows from 01_fetch_history.py. Each row specifies its own chat_id,
so multi-chat pulls are supported. Idempotent: dedupes against existing rows by
(chat_jid, ts-to-second, content_hash) before inserting.

Usage:
    ssh root@89.167.109.12 "sudo -u david python3 /home/david/nanoclaw/scripts/uncaged-recovery/02_backfill.py /tmp/uncaged_messages.jsonl"
"""
import json, sys, sqlite3, shutil, hashlib, time
from datetime import datetime, timezone
from collections import defaultdict

if len(sys.argv) != 2:
    print("usage: 02_backfill.py <path-to-jsonl>", file=sys.stderr)
    sys.exit(1)

JSONL = sys.argv[1]
DB = "/home/david/nanoclaw/store/messages.db"

backup = f"{DB}.pre-backfill-{int(time.time())}"
shutil.copy2(DB, backup)
print(f"[ok] backup -> {backup}", file=sys.stderr)

con = sqlite3.connect(DB)
con.execute("PRAGMA busy_timeout=5000")
cur = con.cursor()

# Pre-index existing rows per-chat
print("[info] indexing existing messages...", file=sys.stderr)
existing = defaultdict(set)
cur.execute("SELECT chat_jid, timestamp, content_hash, content FROM messages")
for chat, ts, ch, content in cur.fetchall():
    if not chat or not ts: continue
    key = ts[:19]
    # Fall back to hash of content if content_hash is NULL (native ingest may leave it empty)
    h = ch if ch else hashlib.sha256((content or "").encode("utf-8")).hexdigest()[:16]
    existing[chat].add((key, h))
total_existing = sum(len(s) for s in existing.values())
print(f"[info] {total_existing} existing (ts,hash) keys across {len(existing)} chats", file=sys.stderr)

inserted = dup_skipped = 0
now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
per_chat_inserted = defaultdict(int)

with open(JSONL) as f:
    for line in f:
        r = json.loads(line)
        chat_jid = f"tg:{r['chat_id']}"
        ts = r["date_utc"]
        if not ts.endswith("Z"): ts = ts + "Z"
        ts_sec = ts[:19]
        content = r["text"] or ""
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
        if (ts_sec, content_hash) in existing[chat_jid]:
            dup_skipped += 1
            continue

        msg_id = f"recovered:{r['message_id']}"
        sender = r.get("sender_id") or ""
        sender_name = r.get("sender_name") or ""
        metadata = json.dumps({
            "source": "telethon_recovery",
            "recovered_at": now_iso,
            "tg_message_id": r["message_id"],
            "has_media": r.get("has_media", False),
            "reply_to": r.get("reply_to"),
            "chat_title": r.get("chat_title"),
        })
        try:
            cur.execute(
                """INSERT OR IGNORE INTO messages
                   (id, chat_jid, sender, sender_name, content, timestamp,
                    is_from_me, is_bot_message, processing_priority,
                    content_hash, content_truncated, metadata)
                   VALUES (?, ?, ?, ?, ?, ?, 0, 0, 5, ?, 0, ?)""",
                (msg_id, chat_jid, sender, sender_name, content, ts,
                 content_hash, metadata),
            )
            if cur.rowcount == 1:
                inserted += 1
                per_chat_inserted[chat_jid] += 1
                existing[chat_jid].add((ts_sec, content_hash))
            else:
                dup_skipped += 1
        except sqlite3.IntegrityError as e:
            print(f"[skip] {msg_id}: {e}", file=sys.stderr)

con.commit()
print(f"\n[result] inserted={inserted} dup_skipped={dup_skipped}", file=sys.stderr)
print("[per-chat inserts]:", file=sys.stderr)
for chat, n in sorted(per_chat_inserted.items(), key=lambda x: -x[1]):
    cur.execute("SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM messages WHERE chat_jid=?", (chat,))
    tot, mn, mx = cur.fetchone()
    print(f"  {chat}: +{n}  (total now {tot}, {mn} → {mx})", file=sys.stderr)
con.close()
