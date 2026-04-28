-- Run in Supabase SQL editor. Service-role REST DDL is blocked, so apply manually.
-- Stores parsed GlockApps inbox-placement results pulled by glockapps_sync.py.

CREATE TABLE IF NOT EXISTS glockapps_test_results (
  id BIGSERIAL PRIMARY KEY,
  glockapps_test_id TEXT NOT NULL UNIQUE,
  project_id TEXT NOT NULL,
  test_started_at TIMESTAMPTZ,
  test_completed_at TIMESTAMPTZ,
  subject TEXT,
  from_email TEXT,
  inbox_pct NUMERIC,
  spam_pct NUMERIC,
  missing_pct NUMERIC,
  promo_pct NUMERIC,
  spf_pass BOOLEAN,
  dkim_pass BOOLEAN,
  dmarc_pass BOOLEAN,
  blacklist_hits INT DEFAULT 0,
  full_payload JSONB,
  pulled_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_glockapps_completed
  ON glockapps_test_results (test_completed_at DESC);

ALTER TABLE glockapps_test_results ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname='public'
      AND tablename='glockapps_test_results'
      AND policyname='service_role_all_glockapps_test_results'
  ) THEN
    CREATE POLICY "service_role_all_glockapps_test_results"
      ON glockapps_test_results FOR ALL TO service_role
      USING (true) WITH CHECK (true);
  END IF;
END $$;
