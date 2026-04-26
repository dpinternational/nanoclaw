# Insurance Scraper — Operations

## Smartlead Auto-Pause Breaker

Script: `scripts/smartlead_breaker.py`
State: `state/smartlead_breaker_state.json`
Events: `state/smartlead_breaker_events.jsonl`
Log: `logs/smartlead_breaker.log`

### Thresholds (per campaign, only when sent_count >= 25)
- 🚨 PAUSE: bounce_pct > 3.0% OR unsub_pct > 1.0%
- ⚠️ WARN:  bounce_pct > 2.0% OR unsub_pct > 0.7% (Telegram alert, daily-deduped, no pause)

### Behavior on PAUSE
1. POST `/api/v1/campaigns/{id}/status` with `{"status":"PAUSED"}` (skipped if already PAUSED).
2. Telegram alert to David (chat 577469008) with reason and current numbers.
3. Trip event appended to `smartlead_breaker_state.json` and `smartlead_breaker_events.jsonl`.

### Modes
- `--dry-run` (default): print decisions, no actions.
- `--execute`: pause + alert + persist.
- `--reset-state`: delete state file (use after manually resuming a campaign).

### Cron (user `david`)
```
*/30 13-21 * * 1-5 cd /home/david/insurance-scraper && /usr/bin/flock -n /home/david/insurance-scraper/state/smartlead_breaker.lock /usr/bin/python3 /home/david/insurance-scraper/scripts/smartlead_breaker.py --execute >> /home/david/insurance-scraper/logs/smartlead_breaker.log 2>&1
```
Runs every 30 minutes 09:00–17:00 ET (13:00–21:00 UTC), Mon–Fri. Flock prevents overlapping runs.

### Manual reset procedure (after you resume a paused campaign)
```
sudo -u david /usr/bin/python3 /home/david/insurance-scraper/scripts/smartlead_breaker.py --reset-state
```
This clears the `trips` history and daily warn-dedupe table so subsequent warns fire normally.

### Pilot campaigns monitored
- 3232436 — Seq A - New Licensees PILOT
- 3232437 — Seq B - Single Carrier PILOT

### Relationship to phase1_guard.py
`phase1_guard.py` is a separate scraper-worker circuit breaker (docker compose services scraper_w1 / scraper_w2). It is **not** modified by this work and is kept as-is. The Smartlead breaker is an independent script with its own state file (`smartlead_breaker_state.json` vs `phase1_breaker_state.json`).

## Webhook Event Routing

Smartlead webhook events are written to `state/smartlead_webhook_events.jsonl`
by `smartlead_webhook_receiver.py`. Two independent "tail" scripts consume that
file and fan out events to operators. Each tracks its own byte-offset state file
and is safe to run in parallel.

| Script | Destination | Offset state file |
|---|---|---|
| `smartlead_reply_router.py` | Telegram DM (David, chat 577469008) | `state/reply_router_offset.json` |
| `smartlead_discord_bridge.py` | Discord #agent-scraper (channel 1488923847288684604) | `state/discord_router_offset.json` |

### smartlead_discord_bridge.py
- Posts to Discord via REST (`POST /api/v10/channels/{id}/messages`).
- Reads `DISCORD_BOT_TOKEN` from `/home/david/nanoclaw/.env`.
- First run initializes offset to current file size (skips historical events).
- Bridges: `EMAIL_REPLY`, `EMAIL_BOUNCE`, `LEAD_UNSUBSCRIBED`,
  `LEAD_CATEGORY_UPDATED`, `EMAIL_OPENED`, `EMAIL_CLICKED`.
- `EMAIL_OPENED` / `EMAIL_CLICKED` are throttled to 1 message / 10 minutes
  (high volume). Lead email is omitted from open/click messages.
- Cron-safe: always exits 0.
- Log: `logs/discord_bridge.log`.

Cron (user `david`):
```
* * * * * cd /home/david/insurance-scraper && /usr/bin/python3 scripts/smartlead_discord_bridge.py >> logs/discord_bridge.log 2>&1
```
