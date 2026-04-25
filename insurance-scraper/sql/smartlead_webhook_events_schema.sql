-- Smartlead webhook receiver event sink

CREATE TABLE IF NOT EXISTS smartlead_webhook_events (
  id BIGSERIAL PRIMARY KEY,
  received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  event_hash TEXT UNIQUE NOT NULL,
  event_type TEXT,
  campaign_id BIGINT,
  lead_id BIGINT,
  lead_email TEXT,
  webhook_url_path TEXT,
  request_headers JSONB,
  payload JSONB,
  raw_payload TEXT
);

CREATE INDEX IF NOT EXISTS idx_smartlead_webhook_events_received_at ON smartlead_webhook_events(received_at DESC);
CREATE INDEX IF NOT EXISTS idx_smartlead_webhook_events_event_type ON smartlead_webhook_events(event_type);
CREATE INDEX IF NOT EXISTS idx_smartlead_webhook_events_campaign_id ON smartlead_webhook_events(campaign_id);
CREATE INDEX IF NOT EXISTS idx_smartlead_webhook_events_lead_email ON smartlead_webhook_events(lead_email);

ALTER TABLE smartlead_webhook_events ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
      AND tablename = 'smartlead_webhook_events'
      AND policyname = 'Allow all for anon'
  ) THEN
    CREATE POLICY "Allow all for anon"
      ON smartlead_webhook_events
      FOR ALL
      USING (true)
      WITH CHECK (true);
  END IF;
END $$;
