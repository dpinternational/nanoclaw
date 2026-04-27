-- Add email-quality tracking columns to agents.
-- email_quality_status values:
--   NULL or 'unchecked' -> not yet audited
--   'unique'            -> email appears on this row only or on <=2 rows total (passes)
--   'duplicate_shared'  -> email is shared by >=3 agents (FAIL: skip ZB + exclude from loader)
ALTER TABLE agents
  ADD COLUMN IF NOT EXISTS email_quality_status TEXT,
  ADD COLUMN IF NOT EXISTS email_quality_checked_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS email_share_count INT;

CREATE INDEX IF NOT EXISTS idx_agents_email_quality_status
  ON agents (email_quality_status) WHERE email_quality_status IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_agents_email_lower
  ON agents (lower(email)) WHERE email IS NOT NULL;
