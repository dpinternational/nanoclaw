#!/usr/bin/env python3
"""
Clean up duplicate rows in messages.db created by Telethon backfills.

Matches duplicates on (chat_jid, ts-to-second, content) — handles NULL
content_hash from the native ingest path. When dupes exist, prefers the
non-`recovered:*` row (native-ingest) and deletes the others.

Usage:
    # All Telegram chats that had recovered:* inserts:
    python3 03_dedupe.py

    # Just specific chats:
    python3 03_dedupe.py tg:-1002362081030 tg:-5241666246

    # Only chats touched in the last N days:
    python3 03_dedupe.py --since-days 30
"""
import sqlite3, shutil, time, sys, argparse
from collections import defaultdict

DB = "/home/david/nanoclaw/store/messages.db"

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("chats", nargs="*",
                   help="Specific chat_jids to dedupe. Default: all chats that have any recovered:* rows.")
    p.add_argument("--since-days", type=int, default=0,
                   help="Only consider messages within N days (0 = all time)")
    p.add_argument("--db", default=DB, help="path to messages.db")
    p.add_argument("--dry-run", action="store_true", help="report only, don't delete")
    return p.parse_args()

def main():
    args = parse_args()
    backup = f"{args.db}.pre-dedupe-{int(time.time())}"
    if not args.dry_run:
        shutil.copy2(args.db, backup)
        print(f"[ok] backup -> {backup}", file=sys.stderr)
    else:
        print("[dry-run] no backup, no deletes", file=sys.stderr)

    con = sqlite3.connect(args.db)
    con.execute("PRAGMA busy_timeout=5000")
    cur = con.cursor()

    # Decide target chats
    if args.chats:
        target_chats = args.chats
    else:
        cur.execute("SELECT DISTINCT chat_jid FROM messages WHERE id LIKE 'recovered:%'")
        target_chats = [r[0] for r in cur.fetchall()]
    print(f"[info] dedup target chats: {len(target_chats)}", file=sys.stderr)
    for c in target_chats:
        print(f"        {c}", file=sys.stderr)
    if not target_chats:
        print("[nothing to do]", file=sys.stderr)
        return

    time_filter = ""
    params = []
    if args.since_days > 0:
        time_filter = " AND timestamp >= datetime('now', ?)"
        params.append(f"-{args.since_days} days")

    summary_deleted = defaultdict(int)
    for chat_jid in target_chats:
        q_params = [chat_jid] + params
        cur.execute(
            f"SELECT rowid, id, timestamp, content FROM messages WHERE chat_jid=?{time_filter}",
            q_params,
        )
        rows = cur.fetchall()

        groups = defaultdict(list)
        for rowid, msg_id, ts, content in rows:
            ts_sec = (ts or "")[:19]
            key = (ts_sec, content or "")
            groups[key].append((rowid, msg_id))

        to_delete = []
        dupe_groups = 0
        for items in groups.values():
            if len(items) < 2: continue
            dupe_groups += 1
            non_recovered = [x for x in items if not x[1].startswith('recovered:')]
            if non_recovered:
                keep = non_recovered[0]
            else:
                keep = sorted(items)[0]
            for x in items:
                if x[0] != keep[0]:
                    to_delete.append(x[0])

        print(f"[{chat_jid}] scanned={len(rows)} dupe_groups={dupe_groups} to_delete={len(to_delete)}", file=sys.stderr)

        if to_delete and not args.dry_run:
            cur.executemany("DELETE FROM messages WHERE rowid=?", [(r,) for r in to_delete])
            con.commit()
            summary_deleted[chat_jid] = len(to_delete)

    if not args.dry_run:
        print(f"\n[result] total deletions: {sum(summary_deleted.values())}", file=sys.stderr)
    else:
        print("\n[dry-run] no changes made", file=sys.stderr)

    # Verify
    for chat_jid in target_chats:
        cur.execute("SELECT COUNT(*) FROM messages WHERE chat_jid=?", (chat_jid,))
        total = cur.fetchone()[0]
        print(f"[verify] {chat_jid}: {total} rows", file=sys.stderr)
    con.close()

if __name__ == "__main__":
    main()
