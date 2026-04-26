# Recruitment Pipeline — Supabase Query Skill

You can query the insurance agent recruitment pipeline stored in Supabase. Use this when David asks about pipeline status, new licensees, scraper progress, or lead data.

## Supabase Connection

The Supabase credentials are in the environment:
- `SUPABASE_URL` = `https://snsoophwazxusonudtkv.supabase.co`
- `SUPABASE_KEY` = `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuc29vcGh3YXp4dXNvbnVkdGt2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE4NDgsImV4cCI6MjA5MDYyNzg0OH0.MZ3M9EL3JC-Y5ztMdfrGOd0H93v7Rk6qhSE2V0Dxhz8`
- Use the Supabase REST API directly with curl

## Quick Queries

### Scraper Status (which state is running)
```bash
curl -s "https://snsoophwazxusonudtkv.supabase.co/rest/v1/scrape_runs?status=eq.running&select=state,last_prefix,prefixes_completed,total_prefixes,saved,updated_at" \
  -H "apikey: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuc29vcGh3YXp4dXNvbnVkdGt2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE4NDgsImV4cCI6MjA5MDYyNzg0OH0.MZ3M9EL3JC-Y5ztMdfrGOd0H93v7Rk6qhSE2V0Dxhz8" -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuc29vcGh3YXp4dXNvbnVkdGt2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE4NDgsImV4cCI6MjA5MDYyNzg0OH0.MZ3M9EL3JC-Y5ztMdfrGOd0H93v7Rk6qhSE2V0Dxhz8" | jq .
```

### Pipeline Funnel
```bash
curl -s "https://snsoophwazxusonudtkv.supabase.co/rest/v1/pipeline_funnel?select=*" \
  -H "apikey: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuc29vcGh3YXp4dXNvbnVkdGt2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE4NDgsImV4cCI6MjA5MDYyNzg0OH0.MZ3M9EL3JC-Y5ztMdfrGOd0H93v7Rk6qhSE2V0Dxhz8" -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuc29vcGh3YXp4dXNvbnVkdGt2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE4NDgsImV4cCI6MjA5MDYyNzg0OH0.MZ3M9EL3JC-Y5ztMdfrGOd0H93v7Rk6qhSE2V0Dxhz8" | jq .
```

### New Licensees (0 appointments — hottest leads)
```bash
curl -s "https://snsoophwazxusonudtkv.supabase.co/rest/v1/agents?is_new_licensee=eq.true&opted_out=eq.false&select=name,email,phone,state,score,first_scraped_at&order=first_scraped_at.desc&limit=20" \
  -H "apikey: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuc29vcGh3YXp4dXNvbnVkdGt2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE4NDgsImV4cCI6MjA5MDYyNzg0OH0.MZ3M9EL3JC-Y5ztMdfrGOd0H93v7Rk6qhSE2V0Dxhz8" -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuc29vcGh3YXp4dXNvbnVkdGt2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE4NDgsImV4cCI6MjA5MDYyNzg0OH0.MZ3M9EL3JC-Y5ztMdfrGOd0H93v7Rk6qhSE2V0Dxhz8" | jq .
```

### Hot Leads (score > 50)
```bash
curl -s "https://snsoophwazxusonudtkv.supabase.co/rest/v1/agents?score=gt.50&opted_out=eq.false&select=name,email,phone,state,score,appointments_count,pipeline_stage&order=score.desc&limit=20" \
  -H "apikey: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuc29vcGh3YXp4dXNvbnVkdGt2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE4NDgsImV4cCI6MjA5MDYyNzg0OH0.MZ3M9EL3JC-Y5ztMdfrGOd0H93v7Rk6qhSE2V0Dxhz8" -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuc29vcGh3YXp4dXNvbnVkdGt2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE4NDgsImV4cCI6MjA5MDYyNzg0OH0.MZ3M9EL3JC-Y5ztMdfrGOd0H93v7Rk6qhSE2V0Dxhz8" | jq .
```

### State Summary
```bash
curl -s "https://snsoophwazxusonudtkv.supabase.co/rest/v1/state_summary?select=*" \
  -H "apikey: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuc29vcGh3YXp4dXNvbnVkdGt2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE4NDgsImV4cCI6MjA5MDYyNzg0OH0.MZ3M9EL3JC-Y5ztMdfrGOd0H93v7Rk6qhSE2V0Dxhz8" -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuc29vcGh3YXp4dXNvbnVkdGt2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE4NDgsImV4cCI6MjA5MDYyNzg0OH0.MZ3M9EL3JC-Y5ztMdfrGOd0H93v7Rk6qhSE2V0Dxhz8" | jq .
```

### Scrape Progress (all states)
```bash
curl -s "https://snsoophwazxusonudtkv.supabase.co/rest/v1/scrape_runs?select=state,status,prefixes_completed,total_prefixes,saved,qualified,errors&order=state" \
  -H "apikey: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuc29vcGh3YXp4dXNvbnVkdGt2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE4NDgsImV4cCI6MjA5MDYyNzg0OH0.MZ3M9EL3JC-Y5ztMdfrGOd0H93v7Rk6qhSE2V0Dxhz8" -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuc29vcGh3YXp4dXNvbnVkdGt2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE4NDgsImV4cCI6MjA5MDYyNzg0OH0.MZ3M9EL3JC-Y5ztMdfrGOd0H93v7Rk6qhSE2V0Dxhz8" | jq .
```

### Today's New Agents
```bash
TODAY=$(date -u +%Y-%m-%dT00:00:00)
curl -s "https://snsoophwazxusonudtkv.supabase.co/rest/v1/agents?first_scraped_at=gte.${TODAY}&select=name,state,email,is_new_licensee,score&order=score.desc" \
  -H "apikey: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuc29vcGh3YXp4dXNvbnVkdGt2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE4NDgsImV4cCI6MjA5MDYyNzg0OH0.MZ3M9EL3JC-Y5ztMdfrGOd0H93v7Rk6qhSE2V0Dxhz8" -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuc29vcGh3YXp4dXNvbnVkdGt2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE4NDgsImV4cCI6MjA5MDYyNzg0OH0.MZ3M9EL3JC-Y5ztMdfrGOd0H93v7Rk6qhSE2V0Dxhz8" | jq .
```

### Count by State
```bash
curl -s "https://snsoophwazxusonudtkv.supabase.co/rest/v1/rpc/count_agents_by_state" \
  -H "apikey: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuc29vcGh3YXp4dXNvbnVkdGt2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE4NDgsImV4cCI6MjA5MDYyNzg0OH0.MZ3M9EL3JC-Y5ztMdfrGOd0H93v7Rk6qhSE2V0Dxhz8" -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuc29vcGh3YXp4dXNvbnVkdGt2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE4NDgsImV4cCI6MjA5MDYyNzg0OH0.MZ3M9EL3JC-Y5ztMdfrGOd0H93v7Rk6qhSE2V0Dxhz8" \
  -H "Content-Type: application/json" -d '{}' | jq .
```

## Lead Scoring Reference

| Signal | Points |
|--------|--------|
| Has email | +10 |
| Has phone | +5 |
| New licensee (0 appointments) | +30 |
| Few carriers (1-2 appointments) | +15 |
| Email opened | +10 |
| Email clicked | +20 |
| Email replied | +50 |

Score > 80 = personal outreach by David.

## Pipeline Stages
`scraped` → `enriched` (email verified) → `cold_sequence` → `engaged` (opened/clicked/replied) → `warm` (Skool/list) → `recruited` → `opted_out`

## Response Formatting

When reporting pipeline data:
- Use tables for multi-row data
- Include counts and percentages
- Highlight new licensees (they're the hottest leads)
- For scraper status: show state name, progress %, ETA based on rate
- For daily reports: "Scraped X agents from Y. Z qualified. N new licensees. M with email."
