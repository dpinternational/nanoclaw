#!/usr/bin/env python3
"""
Fetch Telegram history for one or more chats via Telethon user account.

Usage:
    python3 01_fetch_history.py                  # default: TPG UnCaged, full week gap
    python3 01_fetch_history.py -5147163125      # one chat, 10-day lookback
    python3 01_fetch_history.py -5147163125 -5241666246   # multiple chats
    python3 01_fetch_history.py --days 14 -5147163125     # 14-day lookback
    python3 01_fetch_history.py --start 2026-04-10 --end 2026-04-18 -5147163125

Output: uncaged_messages.jsonl (one JSON object per message across all chats)
"""
import asyncio, os, json, sys, argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
from telethon import TelegramClient

DEFAULT_CHATS = [-1002362081030]  # TPG UnCaged
OUT = "uncaged_messages.jsonl"

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("chat_ids", nargs="*", type=int,
                   help="Telegram chat IDs (negative integers). Default: TPG UnCaged.")
    p.add_argument("--days", type=int, default=10,
                   help="How many days back from now to fetch (default 10).")
    p.add_argument("--start", type=str, help="UTC start date YYYY-MM-DD (overrides --days)")
    p.add_argument("--end", type=str, help="UTC end date YYYY-MM-DD (default: now)")
    p.add_argument("--out", type=str, default=OUT, help="Output JSONL path")
    return p.parse_args()

async def fetch_chat(client, chat_id, start, end, fh):
    entity = await client.get_entity(chat_id)
    title = getattr(entity, "title", None) or getattr(entity, "first_name", str(chat_id))
    print(f"[fetch] {chat_id} = {title}  window {start.isoformat()} → {end.isoformat()}", file=sys.stderr)
    n = 0
    async for msg in client.iter_messages(entity, offset_date=end, reverse=False):
        if msg.date < start: break
        if msg.date > end: continue
        sender = None
        sender_name = None
        if msg.sender:
            sender = str(getattr(msg.sender, "id", ""))
            sender_name = (
                getattr(msg.sender, "first_name", None)
                or getattr(msg.sender, "username", None)
                or ""
            )
            last = getattr(msg.sender, "last_name", None)
            if last:
                sender_name = f"{sender_name} {last}".strip()
        row = {
            "message_id": msg.id,
            "chat_id": chat_id,
            "chat_title": title,
            "date_utc": msg.date.isoformat().replace("+00:00", "Z"),
            "sender_id": sender,
            "sender_name": sender_name,
            "text": msg.message or "",
            "has_media": bool(msg.media),
            "reply_to": msg.reply_to_msg_id,
        }
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        n += 1
        if n % 100 == 0:
            print(f"[progress] {title}: {n} messages ({msg.date.isoformat()})", file=sys.stderr)
    print(f"[done] {title}: {n} messages", file=sys.stderr)
    return n

async def main():
    args = parse_args()
    # Harden: any files we create should be user-only (session file is credentials).
    os.umask(0o077)

    API_ID = int(os.environ["TG_API_ID"])
    API_HASH = os.environ["TG_API_HASH"]
    chats = args.chat_ids or DEFAULT_CHATS

    if args.start:
        start = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        start = datetime.now(timezone.utc) - timedelta(days=args.days)
    if args.end:
        end = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        end = datetime.now(timezone.utc)

    # Keep the session file OUT of the repo working tree. Telethon treats it as
    # credentials-equivalent (full user-account access).
    session_dir = Path.home() / ".config" / "nanoclaw-recovery"
    session_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    session_path = str(session_dir / "uncaged_recovery")

    client = TelegramClient(session_path, API_ID, API_HASH)
    await client.start()
    me = await client.get_me()
    print(f"[ok] logged in as {me.first_name} (id {me.id})", file=sys.stderr)

    total = 0
    with open(args.out, "w") as fh:
        for cid in chats:
            total += await fetch_chat(client, cid, start, end, fh)
    print(f"[all done] {total} messages from {len(chats)} chat(s) to {args.out}", file=sys.stderr)

if __name__ == "__main__":
    asyncio.run(main())
