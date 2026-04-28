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

## Lead Loading Pipeline (Supabase -> Smartlead)

End-to-end automation for moving verified agents from Supabase into Smartlead campaigns. Closes the gap between ZeroBounce verification and Smartlead sending (no more manual CSV exports).

### Flow

    scraper.py
      -> Supabase agents (pipeline_stage='scraped')
    zerobounce_auto_verify.py (cron, every 30 min)
      -> sets agents.email_status = 'verified' | 'bounced'
    scripts/smartlead_lead_loader.py  <-- THIS
      -> POST /api/v1/campaigns/{cid}/leads in batches of 25
      -> writes idempotency row to public.agent_smartlead_loads
    Smartlead
      -> sends per campaign schedule (warmup-aware)

### Tables

`public.agent_smartlead_loads` (see `sql/agent_smartlead_loads_schema.sql`):
- UNIQUE(agent_id, smartlead_campaign_id) provides idempotency.
- `load_result` in {'uploaded','duplicate','invalid','failed'}.
- RLS enabled, service_role only (anon denied).

Apply once via Supabase SQL Editor:
```
psql/SQL Editor -> paste contents of sql/agent_smartlead_loads_schema.sql -> Run
```

### Default segments and campaigns

| Segment | Filter                                                    | Default campaign | Pool size |
|---------|-----------------------------------------------------------|------------------|-----------|
| seq_a   | email_status='verified' AND is_new_licensee=true          | 3232436          | 7,210     |
| seq_b   | email_status='verified' AND appointments_count=1          | 3232437          | 411       |
| custom  | email_status='verified' AND opted_out=false (any campaign)| --campaign-id    | 10,683    |

All segments also enforce `opted_out=false` and exclude agent_ids already in
`agent_smartlead_loads` for that specific campaign.

### Manual usage

Dry-run (always safe):
```
python3 scripts/smartlead_lead_loader.py --segment seq_a --limit 50 --dry-run
```

Execute:
```
python3 scripts/smartlead_lead_loader.py --segment seq_a --limit 50 --execute
```

Refill mode (top campaign up to N total tracked leads):
```
python3 scripts/smartlead_lead_loader.py --segment seq_a --refill-to 200 --execute
```

Custom campaign / arbitrary verified pool:
```
python3 scripts/smartlead_lead_loader.py --segment custom --campaign-id 9999999 --limit 100 --dry-run
```

Flags:
- `--limit N` (default 100, max 500 per run for API throttling)
- `--dry-run` (default) / `--execute` (mutually exclusive)
- `--refill-to N` overrides limit when current tracked count < N
- `--skip-policy-check` bypasses enforce_ready_senders.py (NOT recommended)
- `--skip-backlog-check` bypasses the 7-day-queue abort

### Pre-flight checks (executed in order)

1. `enforce_ready_senders.py` policy gate (subprocess; abort on non-zero).
2. Smartlead campaign lookup; abort unless status in {ACTIVE, PAUSED, DRAFT}.
3. Backlog cap: abort if tracked leads > `max_leads_per_day * 7`.

### Idempotency guarantees

- The loader excludes any `agent_id` already in `agent_smartlead_loads` for the
  target campaign before calling Smartlead.
- After every batch, tracking rows are upserted with
  `on_conflict=agent_id,smartlead_campaign_id, resolution=merge-duplicates`.
- Even if Smartlead returns "duplicate" / "invalid" / a network error, a tracking
  row is written so the loader will never retry that (agent, campaign) pair.

### Telegram alerts

On `--execute` with `uploaded > 0` and `TELEGRAM_BOT_TOKEN` available, sends to
chat 577469008:
```
Loaded N leads to {campaign_name} ({segment}). Pool remaining: {remaining}
```

### Logs

Server: `/home/david/insurance-scraper/logs/smartlead_lead_loader.log` (JSONL, one summary per run).
Mac fallback: `insurance-scraper/logs/smartlead_lead_loader.log`.

### Cron (auto-refill, NOT installed yet)

Start as DRY-RUN, review for a few days, then flip to `--execute`.

```
# Mon-Fri 08:00 ET (12:00 UTC) - 1 hour before sending starts
0 12 * * 1-5 cd /home/david/insurance-scraper && /usr/bin/python3 scripts/smartlead_lead_loader.py --segment seq_a --refill-to 200 --dry-run >> logs/smartlead_lead_loader.log 2>&1
5 12 * * 1-5 cd /home/david/insurance-scraper && /usr/bin/python3 scripts/smartlead_lead_loader.py --segment seq_b --refill-to 200 --dry-run >> logs/smartlead_lead_loader.log 2>&1
```

To enable execute mode after review, replace `--dry-run` with `--execute` on the lines above. The 5-minute offset prevents the two segments from competing for the Smartlead API.

### Scaling to additional segments / campaigns (8+ domains)

1. Create the new campaign in Smartlead UI; capture its numeric id.
2. Add a key/value to `DEFAULT_CAMPAIGNS` in `scripts/smartlead_lead_loader.py`
   (e.g. `"seq_c": 3300000`) and a branch in `fetch_candidates()` describing the
   Supabase filter for that segment. Add a label in `SEGMENT_LABELS`.
3. Add a cron line mirroring seq_a/seq_b with a unique minute offset.
4. Verify with `--dry-run` first; the UNIQUE constraint guarantees no
   double-loading even if cron fires concurrently.

### Pool stats (snapshot)

- 58,937 agents total
- 10,683 verified (`email_status='verified'`)
- 7,210 verified + is_new_licensee=true (Seq A pool)
- 411 verified + appointments_count=1 (Seq B pool)

## Email Quality Audit (pre-ZeroBounce dedup)

Script: `scripts/agents_email_quality_audit.py`
SQL: `sql/agent_email_quality_columns.sql`
Cron: `*/15 * * * *` on server (user `david`).
Log: `logs/email_quality_audit.log` (JSONL).

### Purpose
Mark agents whose email is shared by **3 or more** rows on the
`agents` table BEFORE ZeroBounce verification runs, so duplicate
emails never burn ZB credits and never reach the Smartlead loader.

Threshold rationale: 2-share emails are typically spouse/family
business and remain valid; 3+ are almost always corporate/shared
inboxes (worst-case observed: licensingusaa@usaa.com on 58 agents).

Corporate-pattern detection (info@, licensing@) and name-vs-email
match still live in `smartlead_lead_loader.py::passes_quality_filter`.
This audit only handles the dup-share dimension.

### Pipeline sequence
1. Scraper writes new agent rows (email_status=pending, email_quality_status=NULL).
2. Audit cron (every 15 min) marks NULL rows as `unique` or `duplicate_shared`.
3. ZB cron (every 30 min) skips `duplicate_shared` rows (only verifies
   `email_quality_status` IS NULL OR `unique`).
4. Smartlead loader skips `duplicate_shared` rows server-side via
   PostgREST filter; Python-side `passes_quality_filter` is the safety net.

### Manual commands
```
# Stats only (no writes)
python3 scripts/agents_email_quality_audit.py --report

# Initial backfill (run once after schema applied)
python3 scripts/agents_email_quality_audit.py --full-sweep --execute --i-mean-it

# Re-sweep everything after a policy change
python3 scripts/agents_email_quality_audit.py --full-sweep --dry-run
```

### Schema
Three columns on `agents`:
- `email_quality_status TEXT` — NULL | 'unique' | 'duplicate_shared'
- `email_quality_checked_at TIMESTAMPTZ`
- `email_share_count INT`

Apply `sql/agent_email_quality_columns.sql` in the Supabase SQL
Editor (DDL cannot be applied via PostgREST).

## Deliverability Monitoring (GlockApps)

Two-script automation that uses the GlockApps `autoTestEmail` magic seed
to produce inbox-placement reports for the live Smartlead pilot
sequences. Direct test-trigger endpoints (`/test/start`, `/createTest`,
`/seedList`) are blocked on the current GlockApps plan tier, so we
inject the seed as a Smartlead lead instead.

### Components
- `scripts/glockapps_seed_inject.py` — adds the project's
  `autoTestEmail` (e.g. `ipm7vvz_4df0@at.glockapps.com`) as a lead to
  both pilot campaigns once per week. Idempotent: skips a campaign if
  the seed is already present. Writes a sentinel row
  (`agent_id=-1`, `segment='glockapps_seed'`) to
  `agent_smartlead_loads`.
- `scripts/glockapps_sync.py` — every 30 min, lists tests under the
  configured project, detects new completed tests vs. the cursor in
  `state/glockapps_last_seen.json`, fetches detail, parses placement +
  auth + blacklist data, appends to `state/glockapps_results.jsonl`,
  and upserts to `glockapps_test_results` in Supabase.
- `sql/glockapps_test_results_schema.sql` — Supabase table + RLS
  policy (apply manually via Supabase SQL editor).

### Alerts
- `🚨 GlockApps placement: <inbox>% inbox, <spam>% spam — degraded
  deliverability` — triggered on any new test with inbox < 80% OR any
  failing SPF/DKIM/DMARC.
- `✅ GlockApps: <inbox>% inbox placement, all clean` — triggered on
  any new test with inbox >= 90% AND all auth passing.
- `🎯 GlockApps seed injected into Seq A + Seq B. ...` — emitted on
  successful weekly seed inject.

### Cadence
Each weekly seed runs through all 5 sequence steps over ~16 days, so
each injection produces up to 5 placement reports per campaign. With
both pilots active that is up to 10 reports/week.

### Cron (user `david`)
```
*/30 * * * * cd /home/david/insurance-scraper && /usr/bin/python3 scripts/glockapps_sync.py >> logs/glockapps_sync.log 2>&1
0 13 * * 1   cd /home/david/insurance-scraper && /usr/bin/python3 scripts/glockapps_seed_inject.py --execute >> logs/glockapps_seed_inject.log 2>&1
```
(`13:00 UTC` = `09:00 ET` Monday morning.)

### Manual usage
```
# Preview what would be injected (default)
python3 scripts/glockapps_seed_inject.py

# Inject into both pilots
python3 scripts/glockapps_seed_inject.py --execute

# Inject into a single campaign only
python3 scripts/glockapps_seed_inject.py --execute --campaign-id 3232436

# Force a sync poll
python3 scripts/glockapps_sync.py
```

### Speeding up the first report
After a manual injection, the seed lead enters the campaign queue at
position N where N = current `notStarted` count. With pilots throttled
to 25 leads/day per campaign, M-F 9-5 ET, that can be several business
days. To get same-day data, prioritize the seed lead inside the
Smartlead UI (campaign → leads → search the seed email → "Move to
top of queue").
