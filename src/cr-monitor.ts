/**
 * Campaign Refinery Monitor
 *
 * Takes daily snapshots of CR account state, tracks changes,
 * detects bot signups, and monitors broadcast activity.
 *
 * Run manually: npx ts-node src/cr-monitor.ts
 * Or via scheduled task in NanoClaw.
 */

import Database from 'better-sqlite3';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const STORE_DIR = path.resolve(__dirname, '..', 'store');
const DB_PATH = path.join(STORE_DIR, 'cr-monitor.db');
const CR_BASE_URL = 'https://app.campaignrefinery.com/rest';

// Read API key from .env
function getApiKey(): string {
  const envPath = path.resolve(__dirname, '..', '.env');
  const envContent = fs.readFileSync(envPath, 'utf-8');
  const match = envContent.match(/CAMPAIGN_REFINERY_API_KEY=(.+)/);
  if (!match) throw new Error('CAMPAIGN_REFINERY_API_KEY not found in .env');
  return match[1].trim();
}

const API_KEY = getApiKey();

// --- CR API helpers ---

async function crGet(
  endpoint: string,
  params: Record<string, string> = {},
): Promise<any> {
  const url = new URL(`${CR_BASE_URL}${endpoint}`);
  url.searchParams.set('key', API_KEY);
  for (const [k, v] of Object.entries(params)) {
    url.searchParams.set(k, v);
  }
  const res = await fetch(url.toString(), {
    headers: { Accept: 'application/json' },
  });
  return res.json();
}

async function crPost(
  endpoint: string,
  body: Record<string, any> = {},
): Promise<any> {
  const url = new URL(`${CR_BASE_URL}${endpoint}`);
  url.searchParams.set('key', API_KEY);
  const res = await fetch(url.toString(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json();
}

// --- Database ---

function initDb(): Database.Database {
  fs.mkdirSync(path.dirname(DB_PATH), { recursive: true });
  const db = new Database(DB_PATH);
  db.pragma('journal_mode = WAL');
  db.pragma('synchronous = NORMAL');

  db.exec(`
    CREATE TABLE IF NOT EXISTS daily_snapshots (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      snapshot_date TEXT NOT NULL UNIQUE,
      total_contacts INTEGER,
      subscribed INTEGER,
      unsubscribed INTEGER,
      verified INTEGER,
      bot_contacts_total INTEGER,
      bot_contacts_new_today INTEGER,
      new_contacts_today INTEGER,
      engage_list_size INTEGER,
      created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS broadcast_log (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      broadcast_uuid TEXT NOT NULL UNIQUE,
      broadcast_date TEXT,
      subject TEXT,
      audience_name TEXT,
      num_emails INTEGER,
      sent INTEGER DEFAULT 0,
      delivered INTEGER DEFAULT 0,
      opened INTEGER DEFAULT 0,
      clicked INTEGER DEFAULT 0,
      bounced INTEGER DEFAULT 0,
      complained INTEGER DEFAULT 0,
      unsubscribed INTEGER DEFAULT 0,
      open_rate REAL DEFAULT 0,
      click_rate REAL DEFAULT 0,
      created_to_send_lag_min REAL,
      send_hour_utc INTEGER,
      first_seen_date TEXT DEFAULT (datetime('now')),
      last_updated TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS bot_signups (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      detected_date TEXT NOT NULL,
      contact_email TEXT,
      fake_name TEXT,
      real_name_guess TEXT,
      contact_add_dts TEXT,
      contact_domain TEXT,
      verification_status TEXT
    );

    CREATE TABLE IF NOT EXISTS tag_snapshots (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      snapshot_date TEXT NOT NULL,
      tag_uuid TEXT NOT NULL,
      tag_name TEXT,
      UNIQUE(snapshot_date, tag_uuid)
    );

    CREATE TABLE IF NOT EXISTS daily_alerts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      alert_date TEXT NOT NULL,
      alert_type TEXT NOT NULL,
      severity TEXT NOT NULL,
      message TEXT NOT NULL,
      created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_snapshots_date ON daily_snapshots(snapshot_date);
    CREATE INDEX IF NOT EXISTS idx_broadcast_date ON broadcast_log(broadcast_date);
    CREATE INDEX IF NOT EXISTS idx_bot_detected ON bot_signups(detected_date);
    CREATE INDEX IF NOT EXISTS idx_alerts_date ON daily_alerts(alert_date);
  `);

  return db;
}

// --- Data collection ---

interface ContactSample {
  total: number;
  subscribed: number;
  unsubscribed: number;
  verified: number;
  botCount: number;
  newToday: number;
  newBotToday: number;
  recentBots: Array<{
    email: string;
    fakeName: string;
    addedAt: string;
    domain: string;
    verification: string;
  }>;
}

async function sampleContacts(today: string): Promise<ContactSample> {
  // Get total count
  const countData = await crGet('/contacts/get-contacts', {
    offset: '0',
    limit: '1',
  });
  const total = parseInt(countData._metadata.total_count, 10);

  let subscribed = 0;
  let unsubscribed = 0;
  let verified = 0;
  let botCount = 0;
  let sampled = 0;

  // Sample across the list
  for (let offset = 0; offset < total; offset += 5000) {
    const data = await crGet('/contacts/get-contacts', {
      offset: String(offset),
      limit: '100',
      order_by: 'contact_email',
      sort: 'asc',
    });
    for (const c of data.contacts || []) {
      sampled++;
      if (c.contact_optout_status === 'subscribed') subscribed++;
      else unsubscribed++;
      if (c.contact_verification_status === 'verified') verified++;

      const name = (c.contact_first_name || '').trim();
      if (
        ['Robert', 'Sandra', ''].includes(name) &&
        c.contact_add_dts > '2025-04-28'
      ) {
        botCount++;
      }
    }
  }

  // Extrapolate to full list (guard against zero samples)
  const ratio = sampled > 0 ? total / sampled : 0;
  const estSubscribed = sampled > 0 ? Math.round(subscribed * ratio) : 0;
  const estUnsubscribed = sampled > 0 ? Math.round(unsubscribed * ratio) : 0;
  const estVerified = sampled > 0 ? Math.round(verified * ratio) : 0;
  const estBots = sampled > 0 ? Math.round(botCount * ratio) : 0;

  // Get today's new contacts
  const recentData = await crGet('/contacts/get-contacts', {
    offset: '0',
    limit: '200',
    order_by: 'contact_add_dts',
    sort: 'desc',
  });

  let newToday = 0;
  let newBotToday = 0;
  const recentBots: ContactSample['recentBots'] = [];

  for (const c of recentData.contacts || []) {
    if (!c.contact_add_dts.startsWith(today)) continue;
    newToday++;

    const name = (c.contact_first_name || '').trim();
    if (['Robert', 'Sandra', ''].includes(name)) {
      newBotToday++;
      recentBots.push({
        email: c.contact_email,
        fakeName:
          `${c.contact_first_name || ''} ${c.contact_last_name || ''}`.trim(),
        addedAt: c.contact_add_dts,
        domain: c.contact_email_domain || '',
        verification: c.contact_verification_status || '',
      });
    }
  }

  return {
    total,
    subscribed: estSubscribed,
    unsubscribed: estUnsubscribed,
    verified: estVerified,
    botCount: estBots,
    newToday,
    newBotToday,
    recentBots,
  };
}

interface BroadcastData {
  uuid: string;
  date: string;
  subject: string;
  audienceName: string;
  numEmails: number;
  sent: number;
  delivered: number;
  opened: number;
  clicked: number;
  bounced: number;
  complained: number;
  unsubscribed: number;
  openRate: number;
  clickRate: number;
  lagMinutes: number;
  sendHourUtc: number;
}

async function fetchBroadcasts(): Promise<BroadcastData[]> {
  const data = await crGet('/broadcasts/get-broadcasts');
  const broadcasts: BroadcastData[] = [];

  for (const b of data.broadcasts || []) {
    let stats = {
      sent: 0,
      delivered: 0,
      opened: 0,
      clicked: 0,
      bounced: 0,
      complained: 0,
      unsubscribed: 0,
    };
    try {
      const statsData = await crPost('/broadcasts/get-broadcast-stats', {
        broadcast_id: b.id,
      });
      const s = statsData.broadcast_stats || {};
      stats = {
        sent: parseInt(s.sent || '0', 10),
        delivered: parseInt(s.delivered || '0', 10),
        opened: parseInt(s.opened || '0', 10),
        clicked: parseInt(s.clicked || '0', 10),
        bounced: parseInt(s.bounced || '0', 10),
        complained: parseInt(s.complained || '0', 10),
        unsubscribed: parseInt(s.unsubscribed || '0', 10),
      };
    } catch {}

    const createdAt = new Date(b.created_at + 'Z');
    const sentAt = b.started_sending_at
      ? new Date(b.started_sending_at + 'Z')
      : createdAt;
    const lagMin = (sentAt.getTime() - createdAt.getTime()) / 60000;
    const sendHour = sentAt.getUTCHours();
    const openRate = stats.sent > 0 ? (stats.opened / stats.sent) * 100 : 0;
    const clickRate = stats.sent > 0 ? (stats.clicked / stats.sent) * 100 : 0;

    broadcasts.push({
      uuid: b.id,
      date: b.created_at.slice(0, 10),
      subject: b.subject,
      audienceName: b.audience_name || '',
      numEmails: b.num_emails || 0,
      ...stats,
      openRate,
      clickRate,
      lagMinutes: lagMin,
      sendHourUtc: sendHour,
    });
  }

  return broadcasts;
}

async function fetchTags(): Promise<Array<{ uuid: string; name: string }>> {
  const data = await crGet('/tags/get-tags');
  return (data.tags || []).map((t: any) => ({
    uuid: t.tag_uuid,
    name: t.tag_name,
  }));
}

// --- Storage ---

function storeSnapshot(
  db: Database.Database,
  today: string,
  contacts: ContactSample,
  engageListSize: number,
) {
  db.prepare(
    `
    INSERT OR REPLACE INTO daily_snapshots
    (snapshot_date, total_contacts, subscribed, unsubscribed, verified,
     bot_contacts_total, bot_contacts_new_today, new_contacts_today, engage_list_size)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
  `,
  ).run(
    today,
    contacts.total,
    contacts.subscribed,
    contacts.unsubscribed,
    contacts.verified,
    contacts.botCount,
    contacts.newBotToday,
    contacts.newToday,
    engageListSize,
  );
}

function storeBroadcasts(db: Database.Database, broadcasts: BroadcastData[]) {
  const stmt = db.prepare(`
    INSERT INTO broadcast_log
    (broadcast_uuid, broadcast_date, subject, audience_name, num_emails,
     sent, delivered, opened, clicked, bounced, complained, unsubscribed,
     open_rate, click_rate, created_to_send_lag_min, send_hour_utc, last_updated)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
    ON CONFLICT(broadcast_uuid) DO UPDATE SET
      sent=excluded.sent, delivered=excluded.delivered,
      opened=excluded.opened, clicked=excluded.clicked,
      bounced=excluded.bounced, complained=excluded.complained,
      unsubscribed=excluded.unsubscribed,
      open_rate=excluded.open_rate, click_rate=excluded.click_rate,
      last_updated=datetime('now')
  `);

  for (const b of broadcasts) {
    stmt.run(
      b.uuid,
      b.date,
      b.subject,
      b.audienceName,
      b.numEmails,
      b.sent,
      b.delivered,
      b.opened,
      b.clicked,
      b.bounced,
      b.complained,
      b.unsubscribed,
      b.openRate,
      b.clickRate,
      b.lagMinutes,
      b.sendHourUtc,
    );
  }
}

function storeBotSignups(
  db: Database.Database,
  today: string,
  bots: ContactSample['recentBots'],
) {
  const stmt = db.prepare(`
    INSERT OR IGNORE INTO bot_signups
    (detected_date, contact_email, fake_name, real_name_guess, contact_add_dts, contact_domain, verification_status)
    VALUES (?, ?, ?, ?, ?, ?, ?)
  `);

  for (const bot of bots) {
    // Guess real name from email (e.g., coreymitchelll@gmail.com → Corey Mitchell)
    const emailLocal = bot.email.split('@')[0];
    const guessedName = emailLocal
      .replace(/[0-9]+/g, '')
      .replace(/[._-]/g, ' ')
      .split(' ')
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
      .join(' ')
      .trim();

    stmt.run(
      today,
      bot.email,
      bot.fakeName,
      guessedName,
      bot.addedAt,
      bot.domain,
      bot.verification,
    );
  }
}

function storeTags(
  db: Database.Database,
  today: string,
  tags: Array<{ uuid: string; name: string }>,
) {
  const stmt = db.prepare(`
    INSERT OR IGNORE INTO tag_snapshots (snapshot_date, tag_uuid, tag_name)
    VALUES (?, ?, ?)
  `);
  for (const t of tags) {
    stmt.run(today, t.uuid, t.name);
  }
}

// --- Alerts ---

function generateAlerts(
  db: Database.Database,
  today: string,
  contacts: ContactSample,
  broadcasts: BroadcastData[],
  tags: Array<{ uuid: string; name: string }>,
): string[] {
  const alerts: string[] = [];
  const addAlert = (type: string, severity: string, message: string) => {
    alerts.push(`[${severity.toUpperCase()}] ${message}`);
    db.prepare(
      `INSERT INTO daily_alerts (alert_date, alert_type, severity, message) VALUES (?, ?, ?, ?)`,
    ).run(today, type, severity, message);
  };

  // Bot signup alert
  if (contacts.newBotToday > 0) {
    addAlert(
      'bot_signup',
      'warning',
      `${contacts.newBotToday} bot signups detected today (Robert/Sandra/blank names). Zapier integration still active.`,
    );
  }

  // List shrinkage — compare to yesterday
  const yesterday = db
    .prepare(
      `
    SELECT * FROM daily_snapshots WHERE snapshot_date < ? ORDER BY snapshot_date DESC LIMIT 1
  `,
    )
    .get(today) as any;

  if (yesterday) {
    const contactDiff = contacts.total - yesterday.total_contacts;
    if (contactDiff < -50) {
      addAlert(
        'list_shrink',
        'warning',
        `List shrank by ${Math.abs(contactDiff)} contacts since last snapshot (${yesterday.total_contacts} → ${contacts.total})`,
      );
    }

    const engageDiff =
      contacts.total -
      contacts.botCount -
      (yesterday.total_contacts - yesterday.bot_contacts_total);
    if (yesterday.engage_list_size && contacts.total) {
      // We'll track engage list size from broadcast send counts
    }
  }

  // Broadcast alerts
  const todayBroadcasts = broadcasts.filter((b) => b.date === today);
  if (todayBroadcasts.length === 0) {
    addAlert('no_broadcast', 'info', 'No broadcast sent today.');
  }

  for (const b of todayBroadcasts) {
    // Open rate check (only if enough time has passed)
    if (b.openRate > 0 && b.openRate < 25) {
      addAlert(
        'low_open_rate',
        'warning',
        `Broadcast "${b.subject}" has low open rate: ${b.openRate.toFixed(1)}%`,
      );
    }

    // High unsub rate
    const unsubRate = b.sent > 0 ? (b.unsubscribed / b.sent) * 100 : 0;
    if (unsubRate > 0.3) {
      addAlert(
        'high_unsubs',
        'warning',
        `Broadcast "${b.subject}" had high unsub rate: ${unsubRate.toFixed(2)}% (${b.unsubscribed} unsubs)`,
      );
    }

    // Complaint check
    if (b.complained > 2) {
      addAlert(
        'complaints',
        'critical',
        `Broadcast "${b.subject}" received ${b.complained} spam complaints!`,
      );
    }

    // Send time tracking
    const estHour = (b.sendHourUtc - 4 + 24) % 24;
    addAlert(
      'send_time',
      'info',
      `Broadcast "${b.subject}" sent at ${estHour > 12 ? estHour - 12 : estHour}:00 ${estHour >= 12 ? 'PM' : 'AM'} EST (${b.lagMinutes.toFixed(0)} min after creation)`,
    );
  }

  // Tag change detection
  const lastTagSnapshot = db
    .prepare(
      `
    SELECT tag_uuid, tag_name FROM tag_snapshots
    WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM tag_snapshots WHERE snapshot_date < ?)
  `,
    )
    .all(today) as any[];

  if (lastTagSnapshot.length > 0) {
    const prevTagIds = new Set(lastTagSnapshot.map((t: any) => t.tag_uuid));
    const currentTagIds = new Set(tags.map((t) => t.uuid));

    for (const t of tags) {
      if (!prevTagIds.has(t.uuid)) {
        addAlert('new_tag', 'info', `New tag created: "${t.name}"`);
      }
    }
    for (const t of lastTagSnapshot) {
      if (!currentTagIds.has(t.tag_uuid)) {
        addAlert('deleted_tag', 'warning', `Tag deleted: "${t.tag_name}"`);
      }
    }
  }

  return alerts;
}

// --- Report generation ---

function generateReport(
  db: Database.Database,
  today: string,
  contacts: ContactSample,
  broadcasts: BroadcastData[],
  alerts: string[],
): string {
  const todayBroadcasts = broadcasts.filter((b) => b.date === today);
  const yesterday = db
    .prepare(
      `
    SELECT * FROM daily_snapshots WHERE snapshot_date < ? ORDER BY snapshot_date DESC LIMIT 1
  `,
    )
    .get(today) as any;

  let report = `📊 *CR Daily Monitor — ${today}*\n\n`;

  // List health
  report += `*List Health*\n`;
  report += `Total: ${contacts.total.toLocaleString()}`;
  if (yesterday) {
    const diff = contacts.total - yesterday.total_contacts;
    report += ` (${diff >= 0 ? '+' : ''}${diff})`;
  }
  report += `\n`;
  report += `Subscribed: ~${contacts.subscribed.toLocaleString()} | Unsub: ~${contacts.unsubscribed.toLocaleString()}\n`;
  report += `New today: ${contacts.newToday}`;
  if (contacts.newBotToday > 0) {
    report += ` ⚠️ (${contacts.newBotToday} bot signups)`;
  }
  report += `\n`;
  report += `Est. bot contacts: ~${contacts.botCount.toLocaleString()} (${((contacts.botCount / contacts.total) * 100).toFixed(1)}% of list)\n\n`;

  // Today's broadcasts
  if (todayBroadcasts.length > 0) {
    report += `*Today's Broadcasts*\n`;
    for (const b of todayBroadcasts) {
      const estHour = (b.sendHourUtc - 4 + 24) % 24;
      const timeStr = `${estHour > 12 ? estHour - 12 : estHour}${estHour >= 12 ? 'PM' : 'AM'}`;
      report += `• "${b.subject}"\n`;
      report += `  Sent: ${b.sent.toLocaleString()} | Opens: ${b.opened.toLocaleString()} (${b.openRate.toFixed(1)}%) | Clicks: ${b.clicked}\n`;
      report += `  Unsubs: ${b.unsubscribed} | Complaints: ${b.complained} | Sent ${timeStr} EST\n`;
      report += `  Created-to-send: ${b.lagMinutes.toFixed(0)} min\n`;
    }
  } else {
    report += `*No broadcast sent today.*\n`;
  }
  report += `\n`;

  // Engage list trend (from broadcast send counts)
  const recentBroadcasts = db
    .prepare(
      `
    SELECT broadcast_date, num_emails, subject FROM broadcast_log
    ORDER BY broadcast_date DESC LIMIT 10
  `,
    )
    .all() as any[];

  if (recentBroadcasts.length >= 2) {
    const newest = recentBroadcasts[0];
    const oldest = recentBroadcasts[recentBroadcasts.length - 1];
    const listDiff = newest.num_emails - oldest.num_emails;
    report += `*Engage List Trend*\n`;
    report += `${oldest.num_emails.toLocaleString()} → ${newest.num_emails.toLocaleString()} (${listDiff >= 0 ? '+' : ''}${listDiff}) over last ${recentBroadcasts.length} sends\n\n`;
  }

  // Alerts
  if (alerts.length > 0) {
    report += `*Alerts*\n`;
    for (const a of alerts) {
      report += `${a}\n`;
    }
  }

  return report;
}

// --- Main ---

export async function runMonitor(): Promise<string> {
  const db = initDb();
  const today = new Date().toISOString().slice(0, 10);

  console.log(`[CR Monitor] Running snapshot for ${today}...`);

  // Collect data
  console.log('[CR Monitor] Sampling contacts...');
  const contacts = await sampleContacts(today);

  console.log('[CR Monitor] Fetching broadcasts...');
  const broadcasts = await fetchBroadcasts();

  console.log('[CR Monitor] Fetching tags...');
  const tags = await fetchTags();

  // Determine engage list size from most recent broadcast
  const engageListSize = broadcasts.length > 0 ? broadcasts[0].numEmails : 0;

  // Store everything
  console.log('[CR Monitor] Storing snapshot...');
  storeSnapshot(db, today, contacts, engageListSize);
  storeBroadcasts(db, broadcasts);
  storeBotSignups(db, today, contacts.recentBots);
  storeTags(db, today, tags);

  // Generate alerts
  const alerts = generateAlerts(db, today, contacts, broadcasts, tags);

  // Generate report
  const report = generateReport(db, today, contacts, broadcasts, alerts);

  console.log('[CR Monitor] Done.');
  console.log(report);

  db.close();
  return report;
}

// Run directly
const isMain =
  process.argv[1] && path.resolve(process.argv[1]) === path.resolve(__filename);
if (isMain) {
  runMonitor()
    .then((report) => {
      // Write report to file for easy access
      const reportPath = path.join(STORE_DIR, 'cr-daily-report.txt');
      fs.writeFileSync(reportPath, report);
      console.log(`\nReport saved to ${reportPath}`);
    })
    .catch((err) => {
      console.error('Monitor failed:', err);
      process.exit(1);
    });
}
