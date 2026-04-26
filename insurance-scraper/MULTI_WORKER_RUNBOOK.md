# Multi-Worker Scraper Runbook

Goal: run 2+ scraper workers safely from one codebase.

## Files added
- `docker-compose.multi.yml`
- `.env.worker.example`
- `.env.worker1`
- `.env.worker2`
- `check_proxy_ips.py`

## 1) Configure worker env files
Edit:
- `.env.worker1`
- `.env.worker2`

Required:
- `SUPABASE_KEY`
- `PROXY_URL`

Important:
- Use a distinct proxy session/IP path per worker.
- Keep `ENABLE_MONTHLY_RESET=false` for multi-worker mode.

## 2) Verify each worker exits from a different IP
Run:

```bash
python3 check_proxy_ips.py .env.worker1 .env.worker2
```

If the script warns both workers share same IP, fix proxy session config first.

## 3) Start workers
Run:

```bash
docker compose -f docker-compose.multi.yml up -d --build
```

Check:

```bash
docker compose -f docker-compose.multi.yml ps
docker compose -f docker-compose.multi.yml logs -f --tail=100
```

## 4) Stop workers

```bash
docker compose -f docker-compose.multi.yml down
```

## 5) How state claiming works now
Each worker uses conditional update (`status=pending` -> `running`) to claim exactly one state.
Workers that lose the claim race retry automatically.
Stale `running` states (no updates for `RUNNING_STALE_MINUTES`) are recycled back to `pending`.

## 6) Safe rollout
1. Start only worker 1, observe 1-2 hours.
2. Start worker 2, observe 24-48 hours.
3. Track errors (403/429/CAPTCHA) and new-agent throughput.
4. Only then add worker 3+.

## 7) Phase 1 automation (safe mode)

Phase 1 guard does three things every 5 minutes:
- Keeps worker1 up (auto-start if down)
- Watches worker2 logs for failure bursts
- Trips a circuit breaker and stops worker2 when risk thresholds are hit

Thresholds (default):
- search failures in 10m >= 3
- restart loops in 10m >= 3
- any 403/429/CAPTCHA hit

When tripped:
- worker2 is stopped
- cooldown starts (default 60 minutes)
- event is written to `state/phase1_events.jsonl`

Install automation:

```bash
cd /Users/davidprice/nanoclaw/insurance-scraper
./scripts/install_phase1_automation.sh
```

Run one immediate check manually:

```bash
python3 scripts/phase1_guard.py
```

Inspect guard outputs:

```bash
tail -n 120 logs/phase1_guard.log
tail -n 50 state/phase1_events.jsonl
cat state/phase1_breaker_state.json
```

Remove automation:

```bash
./scripts/uninstall_phase1_automation.sh
```

## 8) Notes
- Multi-worker is for faster discovery, not higher send volume by itself.
- Keep cold-email warmup/deliverability gates separate from scraper speed decisions.
- Phase 1 defaults are conservative. Tune only after 24-48h clean data.
