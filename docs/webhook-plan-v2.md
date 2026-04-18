# NanoClaw Telegram Webhook — Revised Plan (v2)

Incorporates GPT's critique. Key corrections:
- Don't assume webhook drops = unrecoverable. Test the bot-API recovery path first.
- Domain+LE is hygiene, not RCA. Still need to find out WHY the webhook went empty.
- Reconciliation belongs in-process, not a cron.
- Alerts about Telegram problems must not go through Telegram.
- Add secret_token verification, per-bot state, idempotent update_id journaling, off-host backups.

## Findings from recovery-path test (just done)
- `getUpdates` on Andy bot after webhook was empty returned 0 results.
- DB's last message is Apr 17 18:48 UTC; Apr 18 is blank.
- Conclusion: the 24h window either expired or was drained elsewhere. Apr 17 morning UnCaged posts are lost.
- Lesson: the 24h buffer is real but thin. Detection must be fast (minutes, not hours) or the window closes.

## Phase 0 — RCA before building (half-day, blocking)
Do not ship architecture changes until we know why `url` became empty. Candidates:
1. setWebhook failed silently at last boot (self-signed rejected from Telegram side; current code is `logger.warn` only).
2. A script or manual call invoked `deleteWebhook` or re-registered to something else.
3. Bot token was used concurrently by a second process (last-writer-wins on webhook).
4. Telegram auto-removed webhook after repeated 5xx / TLS failures from our endpoint.

Actions:
- Grep all of `/home/david/nanoclaw` for `setWebhook` / `deleteWebhook` / `getUpdates` calls — confirm single owner per token.
- Review `logs/nanoclaw.log` for the last `setWebhook` attempt and its response.
- Curl the public webhook URL from an external host to confirm Telegram can actually reach it with the current cert. If it can't, document the specific error.
- Only after RCA is nailed, proceed.

## Phase 1 — TLS and URL hygiene (one evening)
- DNS: `hooks.davidprice.io` (or `tg.davidprice.io`) A-record → 89.167.109.12.
- Caddy on :443 as reverse proxy. LE auto-provisioned + auto-renewed. Node webhook server binds to `127.0.0.1:8443`.
- Per-bot secret paths with secret_token: `/tg/andy/<random>` and `/tg/brief/<random>`. Enforce the `X-Telegram-Bot-Api-Secret-Token` header match on every inbound; return 401 otherwise.
- Drop the `hasCert`/self-signed branch in `src/channels/telegram.ts`. Simplifies code.
- Env: `WEBHOOK_DOMAIN=hooks.davidprice.io` (no port).

## Phase 2 — Make registration correct & observable (1 day)
- Replace cron watcher with an **in-process per-bot reconcile loop**, 60s tick:
  - Call `getWebhookInfo` for the bot's token.
  - Decide state: OK / URL_MISMATCH / ERROR_STREAK / STALE_BACKLOG.
  - Only re-register on durable signals: URL mismatch, or 2–3 consecutive checks showing `last_error_date` within last 5 min, or `pending_update_count > 500` for 3+ consecutive checks.
  - Cooldown: exponential backoff, min 60s, max 10 min, reset after a good delivery.
- Boot behavior: don't exit on first setWebhook failure. Start in `readiness=false`, retry with backoff, flip `readiness=true` once a real update arrives. Alert only after sustained failure (e.g. 10 min).
- Log registration attempts at `info`, failures at `error`. Count them as a metric.

## Phase 3 — Ingestion durability (1 day)
- Add a raw-update journal: every inbound webhook body is appended to an append-only JSONL file (or a table) keyed on `(bot_id, update_id)`, before any parsing. Unique constraint on `(bot_id, update_id)` to absorb Telegram retries. This is the recoverable record of truth. Parsing into `messages.db` becomes a downstream transform.
- Idempotent upsert into `messages.db` on `(chat_jid, id)` (already PK — good).
- Nightly off-host backup of `store/*.db` and the raw-update journal (S3 / Backblaze / rclone to a second Hetzner box).
- Define an SLO: "During business hours, messages in the UnCaged chat appear in messages.db within 60 seconds, 99% of days."

## Phase 4 — Monitoring that doesn't depend on Telegram (half-day)
- `/livez` — process alive.
- `/readyz` — dependencies healthy (webhook registered for each bot, DB writable, journal writable).
- External checker: a tiny cron on David's Mac (or BetterStack/UptimeRobot free tier) hits `/readyz` every 2 min. If it flips non-200 for 6 min, email David + SMS. Crucially, this is **not** a Telegram alert.
- Add a "last message from UnCaged" freshness gauge to `/readyz`. If stale >15 min during business hours, fail readiness.

## Phase 5 — Only after 1–4 are shipped and proven
Revisit the question: is there still residual data-loss risk that justifies operating a second ingest stack (Telethon/MTProto user client)? Probably not, if Phases 1–4 are solid. Park this until it's proven necessary.

## Rollout order
0 → 1 → 2 → 3 → 4. Each phase is independently shippable and reversible. No single "big bang."

## What's explicitly OUT of scope (resisting scope creep)
- Migrating off sqlite.
- Multi-box HA.
- Telethon side-ingest (deferred indefinitely).
- Any changes to downstream reporting crons.

## Risk register (top 3)
1. Caddy/DNS change misconfigured → webhook dark for hours. Mitigation: stage with a test bot first; keep old self-signed path working until the new URL has received a confirmed real update.
2. Reconcile loop races with boot registration → double-register thrash. Mitigation: single owner of webhook state (the loop), boot just asks the loop to reconcile.
3. External monitor false-positives at 3 AM David-time. Mitigation: quiet-hours logic — degrade severity outside business hours, but still log.
