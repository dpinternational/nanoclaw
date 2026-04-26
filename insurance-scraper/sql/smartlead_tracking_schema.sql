-- Run in Supabase SQL editor before enabling Smartlead metric sync

CREATE TABLE IF NOT EXISTS smartlead_mailbox_health (
  id BIGSERIAL PRIMARY KEY,
  mailbox_id BIGINT UNIQUE NOT NULL,
  from_email TEXT NOT NULL,
  from_name TEXT,
  provider_type TEXT,
  smtp_ok BOOLEAN,
  imap_ok BOOLEAN,
  warmup_enabled BOOLEAN,
  message_per_day INTEGER,
  daily_sent_count INTEGER,
  campaign_count INTEGER,
  is_connected_to_campaign BOOLEAN,
  updated_at TIMESTAMPTZ,
  captured_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS smartlead_campaign_metrics (
  id BIGSERIAL PRIMARY KEY,
  campaign_id BIGINT UNIQUE NOT NULL,
  campaign_name TEXT,
  status TEXT,
  created_at_remote TIMESTAMPTZ,
  sent_count INTEGER,
  open_count INTEGER,
  click_count INTEGER,
  reply_count INTEGER,
  bounce_count INTEGER,
  unsubscribe_count INTEGER,
  raw_analytics JSONB,
  captured_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS smartlead_sync_runs (
  id BIGSERIAL PRIMARY KEY,
  run_type TEXT NOT NULL,
  ok BOOLEAN NOT NULL,
  details JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_smartlead_mailbox_health_email ON smartlead_mailbox_health(from_email);
CREATE INDEX IF NOT EXISTS idx_smartlead_campaign_metrics_captured ON smartlead_campaign_metrics(captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_smartlead_sync_runs_created ON smartlead_sync_runs(created_at DESC);

ALTER TABLE smartlead_mailbox_health ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlead_campaign_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE smartlead_sync_runs ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  -- Remove legacy permissive policy if present
  IF EXISTS (
    SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename='smartlead_mailbox_health' AND policyname='Allow all for anon'
  ) THEN
    DROP POLICY "Allow all for anon" ON smartlead_mailbox_health;
  END IF;

  IF EXISTS (
    SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename='smartlead_campaign_metrics' AND policyname='Allow all for anon'
  ) THEN
    DROP POLICY "Allow all for anon" ON smartlead_campaign_metrics;
  END IF;

  IF EXISTS (
    SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename='smartlead_sync_runs' AND policyname='Allow all for anon'
  ) THEN
    DROP POLICY "Allow all for anon" ON smartlead_sync_runs;
  END IF;

  -- Service role has full read/write access for automation jobs
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename='smartlead_mailbox_health' AND policyname='service_role_all_mailbox_health'
  ) THEN
    CREATE POLICY "service_role_all_mailbox_health" ON smartlead_mailbox_health FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename='smartlead_campaign_metrics' AND policyname='service_role_all_campaign_metrics'
  ) THEN
    CREATE POLICY "service_role_all_campaign_metrics" ON smartlead_campaign_metrics FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM pg_policies WHERE schemaname='public' AND tablename='smartlead_sync_runs' AND policyname='service_role_all_sync_runs'
  ) THEN
    CREATE POLICY "service_role_all_sync_runs" ON smartlead_sync_runs FOR ALL TO service_role USING (true) WITH CHECK (true);
  END IF;
END $$;
