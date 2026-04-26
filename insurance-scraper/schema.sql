-- Insurance Pipeline Schema — Run in Supabase SQL Editor
-- Fresh install: creates all tables, indexes, and views

-- ─── Agents table ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agents (
  id SERIAL PRIMARY KEY,
  name TEXT,
  npn TEXT UNIQUE,
  email TEXT DEFAULT '',
  phone TEXT DEFAULT '',
  state TEXT,
  business_address TEXT DEFAULT '',
  loa TEXT DEFAULT 'Life',
  license_type TEXT DEFAULT 'Insurance Producer',
  license_status TEXT DEFAULT 'Active',
  license_expiration TEXT DEFAULT '',
  effective_date TEXT DEFAULT '',
  appointments JSONB DEFAULT '[]'::jsonb,
  appointments_list JSONB DEFAULT '[]'::jsonb,
  appointments_count INTEGER DEFAULT 0,
  is_new_licensee BOOLEAN DEFAULT false,
  pipeline_stage TEXT DEFAULT 'scraped',
  email_status TEXT DEFAULT 'pending',
  score INTEGER DEFAULT 0,
  opted_out BOOLEAN DEFAULT false,
  opted_out_at TIMESTAMPTZ,
  first_scraped_at TIMESTAMPTZ DEFAULT NOW(),
  scraped_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON COLUMN agents.pipeline_stage IS 'scraped | enriched | cold_sequence | engaged | warm | recruited | opted_out';
COMMENT ON COLUMN agents.email_status IS 'pending | verified | bounced | sent | opened | clicked | replied | opted_out';

-- ─── Appointments table ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS appointments (
  id SERIAL PRIMARY KEY,
  agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
  company_name TEXT,
  naic_cocode TEXT,
  license_type TEXT,
  line_of_authority TEXT,
  appointment_date TEXT,
  effective_date TEXT,
  expiration_date TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ─── State Queue ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS scrape_runs (
  id SERIAL PRIMARY KEY,
  state TEXT UNIQUE NOT NULL,
  status TEXT DEFAULT 'pending',
  last_prefix TEXT DEFAULT 'A',
  prefixes_completed INTEGER DEFAULT 0,
  total_prefixes INTEGER DEFAULT 18278,
  total_found INTEGER DEFAULT 0,
  qualified INTEGER DEFAULT 0,
  saved INTEGER DEFAULT 0,
  errors INTEGER DEFAULT 0,
  started_at TIMESTAMPTZ,
  completed_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- ─── Indexes ───────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_agents_state ON agents(state);
CREATE INDEX IF NOT EXISTS idx_agents_npn ON agents(npn);
CREATE INDEX IF NOT EXISTS idx_agents_new_licensee ON agents(is_new_licensee) WHERE is_new_licensee = true;
CREATE INDEX IF NOT EXISTS idx_agents_pipeline ON agents(pipeline_stage);
CREATE INDEX IF NOT EXISTS idx_agents_score ON agents(score DESC);
CREATE INDEX IF NOT EXISTS idx_agents_email_status ON agents(email_status);
CREATE INDEX IF NOT EXISTS idx_agents_first_scraped ON agents(first_scraped_at DESC);
CREATE INDEX IF NOT EXISTS idx_appointments_agent ON appointments(agent_id);

-- ─── Disable RLS (scraper uses anon key) ───────────────────────
ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
ALTER TABLE appointments ENABLE ROW LEVEL SECURITY;
ALTER TABLE scrape_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all for anon" ON agents FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for anon" ON appointments FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for anon" ON scrape_runs FOR ALL USING (true) WITH CHECK (true);

-- ─── Views ─────────────────────────────────────────────────────

CREATE OR REPLACE VIEW new_licensees AS
SELECT id, name, npn, email, phone, state, score, first_scraped_at, pipeline_stage
FROM agents
WHERE is_new_licensee = true AND opted_out = false AND pipeline_stage = 'scraped'
ORDER BY first_scraped_at DESC;

CREATE OR REPLACE VIEW hot_leads AS
SELECT id, name, npn, email, phone, state, score, appointments_count, pipeline_stage, first_scraped_at
FROM agents
WHERE score > 50 AND opted_out = false
ORDER BY score DESC;

CREATE OR REPLACE VIEW pipeline_funnel AS
SELECT
  pipeline_stage,
  COUNT(*) as count,
  COUNT(*) FILTER (WHERE email != '' AND email IS NOT NULL) as with_email,
  COUNT(*) FILTER (WHERE is_new_licensee = true) as new_licensees,
  ROUND(AVG(score), 1) as avg_score
FROM agents
WHERE opted_out = false
GROUP BY pipeline_stage
ORDER BY CASE pipeline_stage
  WHEN 'scraped' THEN 1 WHEN 'enriched' THEN 2 WHEN 'cold_sequence' THEN 3
  WHEN 'engaged' THEN 4 WHEN 'warm' THEN 5 WHEN 'recruited' THEN 6
END;

CREATE OR REPLACE VIEW state_summary AS
SELECT
  a.state,
  COUNT(*) as total_agents,
  COUNT(*) FILTER (WHERE a.is_new_licensee = true) as new_licensees,
  COUNT(*) FILTER (WHERE a.email != '' AND a.email IS NOT NULL) as with_email,
  COUNT(*) FILTER (WHERE a.phone != '' AND a.phone IS NOT NULL) as with_phone,
  ROUND(AVG(a.score), 1) as avg_score,
  sr.status as scrape_status,
  sr.prefixes_completed,
  sr.total_prefixes,
  ROUND((sr.prefixes_completed::numeric / NULLIF(sr.total_prefixes, 0)) * 100, 1) as pct_complete
FROM agents a
LEFT JOIN scrape_runs sr ON sr.state = a.state
GROUP BY a.state, sr.status, sr.prefixes_completed, sr.total_prefixes
ORDER BY a.state;
