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
