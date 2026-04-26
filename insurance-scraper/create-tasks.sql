INSERT OR REPLACE INTO scheduled_tasks (id, group_folder, chat_jid, prompt, schedule_type, schedule_value, next_run, status, created_at, context_mode)
VALUES (
  'recruitment-pipeline-daily',
  'telegram_main',
  'tg:577469008',
  'Generate a daily recruitment pipeline report. Use curl to query the Supabase insurance pipeline:

SUPABASE_URL=https://snsoophwazxusonudtkv.supabase.co
KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuc29vcGh3YXp4dXNvbnVkdGt2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE4NDgsImV4cCI6MjA5MDYyNzg0OH0.MZ3M9EL3JC-Y5ztMdfrGOd0H93v7Rk6qhSE2V0Dxhz8

Run these queries:
1. Scraper status: curl -s "$SUPABASE_URL/rest/v1/scrape_runs?status=eq.running&select=state,last_prefix,prefixes_completed,total_prefixes,saved" -H "apikey: $KEY" -H "Authorization: Bearer $KEY"
2. Total agents: curl -si "$SUPABASE_URL/rest/v1/agents?select=id" -H "apikey: $KEY" -H "Authorization: Bearer $KEY" -H "Prefer: count=exact" -H "Range: 0-0" (check content-range header)
3. New licensees today: curl -s "$SUPABASE_URL/rest/v1/agents?is_new_licensee=eq.true&first_scraped_at=gte.$(date -u +%Y-%m-%dT00:00:00)&select=name,state,email,score&order=score.desc&limit=10" -H "apikey: $KEY" -H "Authorization: Bearer $KEY"
4. Agents with email: curl -s "$SUPABASE_URL/rest/v1/agents?email=neq.&select=name&limit=0" -H "apikey: $KEY" -H "Authorization: Bearer $KEY" -H "Prefer: count=exact" -H "Range: 0-0" (check content-range)

Format as a concise daily digest and send to David.',
  'cron',
  '0 18 * * *',
  '2026-04-01T22:00:00.000Z',
  'active',
  '2026-04-01T15:30:00.000Z',
  'isolated'
);

INSERT OR REPLACE INTO scheduled_tasks (id, group_folder, chat_jid, prompt, schedule_type, schedule_value, next_run, status, created_at, context_mode)
VALUES (
  'recruitment-new-licensee-alert',
  'telegram_main',
  'tg:577469008',
  'Check for new insurance agent licensees found in the last 24 hours. Use curl:

SUPABASE_URL=https://snsoophwazxusonudtkv.supabase.co
KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuc29vcGh3YXp4dXNvbnVkdGt2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE4NDgsImV4cCI6MjA5MDYyNzg0OH0.MZ3M9EL3JC-Y5ztMdfrGOd0H93v7Rk6qhSE2V0Dxhz8

Query: curl -s "$SUPABASE_URL/rest/v1/agents?is_new_licensee=eq.true&first_scraped_at=gte.$(date -u -d ''24 hours ago'' +%Y-%m-%dT%H:%M:%S 2>/dev/null || date -u -v-24H +%Y-%m-%dT%H:%M:%S)&select=name,state,email,phone,score&order=score.desc&limit=20" -H "apikey: $KEY" -H "Authorization: Bearer $KEY"

If new licensees found, send alert: list their names, states, and whether they have email/phone. These are brand-new agents with 0 carrier appointments - the hottest recruiting leads.
If none found, do NOT send any message.',
  'cron',
  '0 12 * * *',
  '2026-04-01T16:00:00.000Z',
  'active',
  '2026-04-01T15:30:00.000Z',
  'isolated'
);

INSERT OR REPLACE INTO scheduled_tasks (id, group_folder, chat_jid, prompt, schedule_type, schedule_value, next_run, status, created_at, context_mode)
VALUES (
  'recruitment-scraper-health',
  'telegram_main',
  'tg:577469008',
  'Check the insurance scraper health. Use curl:

SUPABASE_URL=https://snsoophwazxusonudtkv.supabase.co
KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNuc29vcGh3YXp4dXNvbnVkdGt2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzUwNTE4NDgsImV4cCI6MjA5MDYyNzg0OH0.MZ3M9EL3JC-Y5ztMdfrGOd0H93v7Rk6qhSE2V0Dxhz8

Query running state: curl -s "$SUPABASE_URL/rest/v1/scrape_runs?status=eq.running&select=state,last_prefix,prefixes_completed,total_prefixes,updated_at" -H "apikey: $KEY" -H "Authorization: Bearer $KEY"

Check pending count: curl -s "$SUPABASE_URL/rest/v1/scrape_runs?status=eq.pending&select=state" -H "apikey: $KEY" -H "Authorization: Bearer $KEY"

If a state is running but updated_at is more than 2 hours ago, alert David the scraper may be stuck.
If no state is running and there are still pending states, alert that the scraper has stopped.
If everything looks healthy, do NOT send any message. Only alert on problems.',
  'cron',
  '0 */6 * * *',
  '2026-04-01T18:00:00.000Z',
  'active',
  '2026-04-01T15:30:00.000Z',
  'isolated'
);
