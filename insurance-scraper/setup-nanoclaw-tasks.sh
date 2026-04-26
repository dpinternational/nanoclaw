#!/bin/bash
# Register recruitment pipeline scheduled tasks in NanoClaw
# Run this once after deploying the scraper

NANOCLAW_DIR="${1:-/Users/davidprice/nanoclaw}"
IPC_DIR="$NANOCLAW_DIR/data/ipc/main/tasks"

mkdir -p "$IPC_DIR"

echo "Setting up recruitment pipeline scheduled tasks..."

# 1. Pipeline Daily Report — 6 PM daily
cat > "$IPC_DIR/pipeline_report_$(date +%s).json" << 'TASK'
{
  "type": "schedule_task",
  "name": "recruitment_pipeline_report",
  "schedule_type": "cron",
  "schedule_value": "0 18 * * *",
  "prompt": "Generate a daily recruitment pipeline report. Query Supabase for: 1) How many agents were scraped today (first_scraped_at >= today), 2) How many are new licensees, 3) How many have email, 4) Which state the scraper is currently running on and its progress %, 5) Pipeline funnel counts. Format as a concise daily digest and send to Discord #recruitment-pipeline channel.",
  "target_jid": "dc:recruitment-pipeline"
}
TASK

# 2. New Licensee Alert — noon daily
cat > "$IPC_DIR/new_licensee_alert_$(date +%s).json" << 'TASK'
{
  "type": "schedule_task",
  "name": "new_licensee_alert",
  "schedule_type": "cron",
  "schedule_value": "0 12 * * *",
  "prompt": "Check Supabase for new licensees (is_new_licensee=true) found in the last 24 hours. If any found, send an alert to David listing their names, states, and whether they have email/phone. These are the hottest leads — brand new agents with 0 carrier appointments.",
  "target_jid": "tg:main"
}
TASK

# 3. Scraper Health Check — every 30 minutes
cat > "$IPC_DIR/scraper_health_$(date +%s).json" << 'TASK'
{
  "type": "schedule_task",
  "name": "scraper_health_check",
  "schedule_type": "cron",
  "schedule_value": "*/30 * * * *",
  "prompt": "Check the scraper health: query Supabase scrape_runs for the running state. If updated_at is more than 1 hour ago, the scraper may be stuck — alert David on Telegram. If no state is running and there are still pending states, alert that the scraper has stopped. Only send messages if there's a problem.",
  "target_jid": "tg:main"
}
TASK

echo "✅ Task files created in $IPC_DIR"
echo "NanoClaw will pick these up on next IPC poll cycle."
echo ""
echo "Note: You may need to create the Discord channel #recruitment-pipeline first,"
echo "then register it as a NanoClaw group."
