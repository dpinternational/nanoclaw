-- Run in Supabase SQL editor. Service-role REST DDL is blocked, so apply manually.
-- Tracks every agent->Smartlead campaign load attempt for idempotency + auditing.

CREATE TABLE IF NOT EXISTS agent_smartlead_loads (
  id BIGSERIAL PRIMARY KEY,
  agent_id BIGINT NOT NULL,
  smartlead_campaign_id BIGINT NOT NULL,
  smartlead_lead_id BIGINT,
  email TEXT NOT NULL,
  segment TEXT,
  loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  load_result TEXT,             -- 'uploaded' | 'duplicate' | 'invalid' | 'failed'
  load_response JSONB,
  CONSTRAINT agent_smartlead_loads_unique UNIQUE (agent_id, smartlead_campaign_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_smartlead_loads_campaign_loaded
  ON agent_smartlead_loads (smartlead_campaign_id, loaded_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_smartlead_loads_agent
  ON agent_smartlead_loads (agent_id);

CREATE INDEX IF NOT EXISTS idx_agent_smartlead_loads_email
  ON agent_smartlead_loads (email);

ALTER TABLE agent_smartlead_loads ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  -- Drop any legacy permissive anon policy
  IF EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname='public' AND tablename='agent_smartlead_loads'
      AND policyname='Allow all for anon'
  ) THEN
    DROP POLICY "Allow all for anon" ON agent_smartlead_loads;
  END IF;

  -- service_role full access (automation uses service-role key)
  IF NOT EXISTS (
    SELECT 1 FROM pg_policies
    WHERE schemaname='public' AND tablename='agent_smartlead_loads'
      AND policyname='service_role_all_agent_smartlead_loads'
  ) THEN
    CREATE POLICY "service_role_all_agent_smartlead_loads"
      ON agent_smartlead_loads
      FOR ALL TO service_role
      USING (true) WITH CHECK (true);
  END IF;

  -- Explicit deny for anon: no policies for anon role => RLS denies by default.
  -- (No CREATE POLICY for anon; RLS-enabled tables deny all when no policy matches.)
END $$;
