# UnCaged one-shot history recovery — runbook

## When to run this
Only when the bot webhook silently stopped delivering UnCaged messages and you
need to backfill the gap. The bot API can't retrieve history; a user-account
MTProto client (Telethon) can.

## One-time setup

1. Go to https://my.telegram.org/apps (log in with your Telegram phone number).
2. Click "API development tools". If you don't have an app, create one —
   name: `nanoclaw-recovery`, platform: Other. Any description is fine.
3. Copy:
   - `api_id` (integer)
   - `api_hash` (32-char hex string)
   Keep these private. They're tied to your personal account.

4. Install Telethon locally (NOT on the server — keep the user-account login
   off the production box):
   ```
   pip3 install --user telethon
   ```

## Fetch the history (local, your Mac)

```
cd ~/nanoclaw/scripts/uncaged-recovery
export TG_API_ID=<your api_id>
export TG_API_HASH=<your api_hash>
python3 01_fetch_history.py
```

First run: Telethon prompts for your phone number, then for the SMS login code
Telegram sends. If you have 2FA, it asks for that too. A session file is
created at `~/.config/nanoclaw-recovery/uncaged_recovery.session` (mode 600,
outside the repo). Treat it like a password — it grants full access to your
Telegram account. Don't commit. Don't copy to the server.

Output: `uncaged_messages.jsonl` (one JSON object per message).

Edit the START_UTC / END_UTC in `01_fetch_history.py` if you want to adjust
the window. Defaults: Apr 16 05:00 EDT → Apr 17 11:00 EDT (the observed gap,
padded for overlap so we can dedupe).

## Backfill to messages.db (server)

```
scp uncaged_messages.jsonl root@89.167.109.12:/tmp/
ssh root@89.167.109.12 "sudo -u david python3 /home/david/nanoclaw/scripts/uncaged-recovery/02_backfill.py /tmp/uncaged_messages.jsonl"
```

Script is idempotent — uses `INSERT OR IGNORE` on `(id, chat_jid)`. IDs are
prefixed `recovered:<tg_message_id>` so they won't collide with the bot's
native ingest. Runs a backup of `messages.db` first.

## Also push the scripts to the server (one-time)

```
cd ~/nanoclaw
git add scripts/uncaged-recovery/
git commit -m "feat: one-shot UnCaged history recovery via Telethon"
git push
ssh root@89.167.109.12 "cd /home/david/nanoclaw && git pull"
```

## Verifying

The backfill script prints `[verify]` lines at the end showing new Apr 17 +
Apr 16 UnCaged row counts + min/max timestamps. Also rerun today's TPG morning
report — it should now see the recovered morning sales.

## Reconciling against David's count (46)

After backfill, count sales messages for Apr 17 UTC:
```
ssh root@89.167.109.12 "sqlite3 /home/david/nanoclaw/store/messages.db \
  \"SELECT COUNT(*) FROM messages WHERE chat_jid='tg:-1002362081030' \
   AND timestamp LIKE '2026-04-17%' \
   AND content GLOB '*\\$*';\""
```

Then parse with the TPG sales rules (>\$500 = AP, <\$500 = monthly×12, skip
rewrites, multi-sale posts count each).

## DO NOT

- Don't copy `uncaged_recovery.session` to the server. Keep the user-account
  identity on your workstation only.
- Don't run `01_fetch_history.py` on the server. Production box has no
  business holding your personal Telegram credentials.
- Don't commit `.session` files, `uncaged_messages.jsonl`, or the API hash.
