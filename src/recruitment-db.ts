/**
 * Recruitment Intelligence Database
 * Captures and stores @tpglife.com emails for trend analysis and AI-driven insights.
 */

import Database from 'better-sqlite3';
import path from 'path';
import { logger } from './logger.js';

const DB_PATH = path.join(
  process.cwd(),
  'data',
  'recruitment',
  'recruitment.db',
);

let db: Database.Database | null = null;

function getDb(): Database.Database {
  if (!db) {
    db = new Database(DB_PATH);
    db.pragma('journal_mode = WAL');
    db.pragma('busy_timeout = 5000');
    initSchema();
  }
  return db;
}

function initSchema(): void {
  const d = db!;

  d.exec(`
    CREATE TABLE IF NOT EXISTS emails (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      gmail_message_id TEXT UNIQUE,
      gmail_thread_id TEXT,
      sender_email TEXT NOT NULL,
      sender_name TEXT,
      recipient TEXT,
      subject TEXT,
      body TEXT,
      timestamp TEXT NOT NULL,
      category TEXT,
      processed INTEGER DEFAULT 0,
      created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS recruiter_reports (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      recruiter_name TEXT NOT NULL,
      recruiter_email TEXT NOT NULL,
      report_date TEXT NOT NULL,
      report_type TEXT NOT NULL,
      total_dials INTEGER,
      contacts_reached INTEGER,
      voicemails_left INTEGER,
      appointments_set INTEGER,
      interviews_completed INTEGER,
      follow_ups_scheduled INTEGER,
      applications_submitted INTEGER,
      agents_contracted INTEGER,
      agents_onboarded INTEGER,
      lead_source TEXT,
      leads_worked INTEGER,
      leads_remaining INTEGER,
      notes TEXT,
      challenges TEXT,
      wins TEXT,
      source_email_id INTEGER REFERENCES emails(id),
      source_spreadsheet_url TEXT,
      raw_data TEXT,
      created_at TEXT DEFAULT (datetime('now')),
      UNIQUE(recruiter_name, report_date, report_type)
    );

    CREATE TABLE IF NOT EXISTS prospects (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      email TEXT,
      phone TEXT,
      source TEXT,
      recruiter TEXT,
      status TEXT DEFAULT 'new',
      first_contact_date TEXT,
      last_contact_date TEXT,
      next_follow_up TEXT,
      notes TEXT,
      created_at TEXT DEFAULT (datetime('now')),
      updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS contracting_requests (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      agent_name TEXT NOT NULL,
      submitted_by TEXT,
      carriers TEXT,
      status TEXT DEFAULT 'pending',
      submit_date TEXT,
      completion_date TEXT,
      notes TEXT,
      source_email_id INTEGER REFERENCES emails(id),
      created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS daily_metrics (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      date TEXT NOT NULL,
      recruiter TEXT NOT NULL,
      dials INTEGER DEFAULT 0,
      contacts INTEGER DEFAULT 0,
      appointments INTEGER DEFAULT 0,
      interviews INTEGER DEFAULT 0,
      applications INTEGER DEFAULT 0,
      contracted INTEGER DEFAULT 0,
      contact_rate REAL,
      appointment_rate REAL,
      close_rate REAL,
      created_at TEXT DEFAULT (datetime('now')),
      UNIQUE(date, recruiter)
    );

    CREATE TABLE IF NOT EXISTS weekly_snapshots (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      week_ending TEXT NOT NULL,
      recruiter TEXT NOT NULL,
      total_dials INTEGER DEFAULT 0,
      total_contacts INTEGER DEFAULT 0,
      total_appointments INTEGER DEFAULT 0,
      total_interviews INTEGER DEFAULT 0,
      total_applications INTEGER DEFAULT 0,
      total_contracted INTEGER DEFAULT 0,
      avg_contact_rate REAL,
      avg_close_rate REAL,
      dials_change_pct REAL,
      contacts_change_pct REAL,
      contracted_change_pct REAL,
      ai_insights TEXT,
      created_at TEXT DEFAULT (datetime('now')),
      UNIQUE(week_ending, recruiter)
    );

    CREATE INDEX IF NOT EXISTS idx_emails_sender ON emails(sender_email);
    CREATE INDEX IF NOT EXISTS idx_emails_timestamp ON emails(timestamp);
    CREATE INDEX IF NOT EXISTS idx_emails_category ON emails(category);
    CREATE INDEX IF NOT EXISTS idx_reports_recruiter ON recruiter_reports(recruiter_name, report_date);
    CREATE INDEX IF NOT EXISTS idx_prospects_status ON prospects(status);
    CREATE INDEX IF NOT EXISTS idx_daily_metrics_date ON daily_metrics(date, recruiter);
    CREATE INDEX IF NOT EXISTS idx_contracting_agent ON contracting_requests(agent_name);
  `);
}

/** Known tpglife.com senders and their roles */
const TPG_SENDERS: Record<string, { role: string; name: string }> = {
  'sandra@tpglife.com': { role: 'recruiter', name: 'Sandra Futch' },
  'gina@tpglife.com': { role: 'operations', name: 'Gina Soriano' },
  'contracting@tpglife.com': {
    role: 'contracting',
    name: 'Contracting Department',
  },
  'kendra@tpglife.com': { role: 'staff', name: 'Kendra Wilson' },
  'kwilson@tpglife.com': { role: 'staff', name: 'K. Wilson' },
  'hiring@tpglife.com': { role: 'recruiting', name: 'Hiring' },
  'info@tpglife.com': { role: 'general', name: 'TPG Info' },
};

/** Check if an email is from a tpglife.com domain */
export function isTPGEmail(senderEmail: string): boolean {
  return senderEmail.toLowerCase().endsWith('@tpglife.com');
}

/** Categorize a tpglife.com email based on sender and content */
function categorizeEmail(
  senderEmail: string,
  subject: string,
  body: string,
): string {
  const s = subject.toLowerCase();
  const b = body.toLowerCase();
  const email = senderEmail.toLowerCase();

  if (email === 'contracting@tpglife.com' || s.includes('contracting')) {
    return 'contracting';
  }
  if (
    s.includes('production') ||
    s.includes('premium') ||
    s.includes('commission')
  ) {
    return 'production';
  }
  if (
    s.includes('lead') ||
    s.includes('call log') ||
    s.includes('spreadsheet') ||
    s.includes('eod') ||
    b.includes('dials') ||
    b.includes('appointments')
  ) {
    return 'recruiter_report';
  }
  if (
    s.includes('recruit') ||
    s.includes('hire') ||
    s.includes('interview') ||
    s.includes('onboard')
  ) {
    return 'recruiting';
  }
  if (email === 'hiring@tpglife.com') {
    return 'recruiting';
  }

  const sender = TPG_SENDERS[email];
  if (sender?.role === 'recruiter') return 'recruiter_report';

  return 'general';
}

/**
 * Capture a tpglife.com email into the recruitment database.
 * Called from the enhanced Gmail channel when a @tpglife.com email is detected.
 */
export function captureTPGEmail(params: {
  gmailMessageId: string;
  gmailThreadId?: string;
  senderEmail: string;
  senderName: string;
  recipient?: string;
  subject: string;
  body: string;
  timestamp: string;
}): void {
  try {
    const d = getDb();
    const category = categorizeEmail(
      params.senderEmail,
      params.subject,
      params.body,
    );

    d.prepare(
      `
      INSERT OR IGNORE INTO emails (
        gmail_message_id, gmail_thread_id, sender_email, sender_name,
        recipient, subject, body, timestamp, category
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `,
    ).run(
      params.gmailMessageId,
      params.gmailThreadId || null,
      params.senderEmail.toLowerCase(),
      params.senderName,
      params.recipient || null,
      params.subject,
      params.body,
      params.timestamp,
      category,
    );

    logger.info(
      {
        sender: params.senderEmail,
        subject: params.subject,
        category,
      },
      'TPG email captured to recruitment database',
    );

    // Auto-extract contracting requests
    if (category === 'contracting') {
      extractContractingRequest(params);
    }
  } catch (error) {
    logger.error(
      { error, messageId: params.gmailMessageId },
      'Failed to capture TPG email',
    );
  }
}

/** Extract contracting details from contracting@tpglife.com emails */
function extractContractingRequest(params: {
  gmailMessageId: string;
  senderName: string;
  subject: string;
  body: string;
  timestamp: string;
}): void {
  const d = getDb();

  // Extract agent name from subject like "Follow-up Request – Agents for Contracting - Evan"
  const nameMatch = params.subject.match(/[-–]\s*(\w+)\s*$/);
  if (!nameMatch) return;

  const agentName = nameMatch[1];
  const emailRow = d
    .prepare('SELECT id FROM emails WHERE gmail_message_id = ?')
    .get(params.gmailMessageId) as { id: number } | undefined;

  d.prepare(
    `
    INSERT OR IGNORE INTO contracting_requests (
      agent_name, submitted_by, status, submit_date, notes, source_email_id
    ) VALUES (?, ?, 'pending', ?, ?, ?)
  `,
  ).run(
    agentName,
    params.senderName,
    params.timestamp.slice(0, 10),
    params.subject,
    emailRow?.id || null,
  );

  logger.info({ agentName }, 'Contracting request extracted');
}

/** Get recruitment database stats for reporting */
export function getRecruitmentStats(): {
  totalEmails: number;
  byCategory: Record<string, number>;
  bySender: Record<string, number>;
  contractingPending: number;
  recentEmails: Array<{
    sender: string;
    subject: string;
    timestamp: string;
    category: string;
  }>;
} {
  const d = getDb();

  const totalEmails = (
    d.prepare('SELECT COUNT(*) as cnt FROM emails').get() as { cnt: number }
  ).cnt;

  const categories = d
    .prepare('SELECT category, COUNT(*) as cnt FROM emails GROUP BY category')
    .all() as Array<{ category: string; cnt: number }>;
  const byCategory: Record<string, number> = {};
  for (const c of categories) byCategory[c.category] = c.cnt;

  const senders = d
    .prepare(
      'SELECT sender_email, COUNT(*) as cnt FROM emails GROUP BY sender_email ORDER BY cnt DESC',
    )
    .all() as Array<{ sender_email: string; cnt: number }>;
  const bySender: Record<string, number> = {};
  for (const s of senders) bySender[s.sender_email] = s.cnt;

  const contractingPending = (
    d
      .prepare(
        "SELECT COUNT(*) as cnt FROM contracting_requests WHERE status = 'pending'",
      )
      .get() as { cnt: number }
  ).cnt;

  const recentEmails = d
    .prepare(
      'SELECT sender_name as sender, subject, timestamp, category FROM emails ORDER BY timestamp DESC LIMIT 10',
    )
    .all() as Array<{
    sender: string;
    subject: string;
    timestamp: string;
    category: string;
  }>;

  return {
    totalEmails,
    byCategory,
    bySender,
    contractingPending,
    recentEmails,
  };
}
