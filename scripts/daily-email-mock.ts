/**
 * Daily Email Mock — Shadow Mode
 *
 * Generates tomorrow's email draft and posts it to David's Telegram
 * alongside whatever Chris sent today. No emails are actually sent.
 *
 * Flow:
 * 1. Pull David's latest Brain Dump messages for fresh material
 * 2. Pull today's Chris broadcast (if any) from CR API
 * 3. Generate tomorrow's themed email using Claude
 * 4. Post both to Telegram for side-by-side comparison
 *
 * Usage: npx tsx scripts/daily-email-mock.ts
 * Scheduled: runs daily at 9 PM EST via NanoClaw task scheduler
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import Database from 'better-sqlite3';
import Anthropic from '@anthropic-ai/sdk';
import { buildPrompt, parseGeneratedEmail, getDayTheme } from '../src/email-generator.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');
const STORE_DIR = path.join(PROJECT_ROOT, 'store');

// --- Helpers ---

function readEnvVar(name: string): string {
  const envPath = path.join(PROJECT_ROOT, '.env');
  const content = fs.readFileSync(envPath, 'utf-8');
  const match = content.match(new RegExp(`${name}=(.+)`));
  return match?.[1]?.trim() || '';
}

// --- Pull Brain Dump messages (last 48 hours) ---

function getBrainDumpUpdates(): string {
  try {
    const dbPath = path.join(STORE_DIR, 'messages.db');
    const db = new Database(dbPath, { readonly: true });

    const cutoff = new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString();
    const messages = db.prepare(`
      SELECT content, timestamp, sender_name
      FROM messages
      WHERE chat_jid = 'tg:-5147163125'
        AND timestamp > ?
        AND is_bot_message = 0
      ORDER BY timestamp DESC
      LIMIT 20
    `).all(cutoff) as any[];

    db.close();

    if (messages.length === 0) return '';

    let output = 'David\'s recent Brain Dump updates (last 48 hours):\n\n';
    for (const m of messages.reverse()) {
      const time = new Date(m.timestamp).toLocaleString('en-US', { timeZone: 'America/New_York' });
      output += `[${time}] ${m.content.slice(0, 500)}\n\n`;
    }
    return output;
  } catch (err) {
    console.error('Could not read Brain Dump:', err);
    return '';
  }
}

// --- Pull TPG wins from Telegram (last 48 hours) ---

function getTPGWins(): string {
  try {
    const dbPath = path.join(STORE_DIR, 'messages.db');
    const db = new Database(dbPath, { readonly: true });

    const cutoff = new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString();
    const messages = db.prepare(`
      SELECT content, timestamp, sender_name
      FROM messages
      WHERE chat_jid = 'tg:-1002362081030'
        AND timestamp > ?
        AND (content LIKE '%$%' OR content LIKE '%wrote%' OR content LIKE '%issued%' OR content LIKE '%AP%')
      ORDER BY timestamp DESC
      LIMIT 10
    `).all(cutoff) as any[];

    db.close();

    if (messages.length === 0) return '';

    let output = 'Recent TPG agent wins:\n\n';
    for (const m of messages.reverse()) {
      output += `- ${m.sender_name}: ${m.content.slice(0, 300)}\n`;
    }
    return output;
  } catch (err) {
    return '';
  }
}

// --- Pull Chris's broadcast from today ---

async function getTodaysBroadcast(): Promise<{ subject: string; body: string } | null> {
  try {
    const archivePath = path.join(STORE_DIR, 'cr-email-archive.json');
    if (!fs.existsSync(archivePath)) return null;

    const archive = JSON.parse(fs.readFileSync(archivePath, 'utf-8'));
    const today = new Date().toISOString().slice(0, 10);

    // Find today's email
    const todayEmail = archive.find((e: any) => {
      const emailDate = new Date(e.date).toISOString().slice(0, 10);
      return emailDate === today;
    });

    if (todayEmail) {
      return { subject: todayEmail.subject, body: todayEmail.body };
    }

    // If not in archive, check CR API for today's broadcast subject
    const apiKey = readEnvVar('CAMPAIGN_REFINERY_API_KEY');
    if (!apiKey) return null;

    const res = await fetch(`https://app.campaignrefinery.com/rest/broadcasts/get-broadcasts?key=${apiKey}`);
    const data = await res.json() as any;
    const todayBroadcast = data.broadcasts?.find((b: any) => b.created_at?.startsWith(today));

    if (todayBroadcast) {
      return { subject: todayBroadcast.subject, body: '(body not available via API — check Gmail archive)' };
    }

    return null;
  } catch {
    return null;
  }
}

// --- Generate email ---

async function generateEmail(day: string, brainDump: string, tpgWins: string): Promise<ReturnType<typeof parseGeneratedEmail>> {
  const additionalContext = brainDump
    ? `## DAVID'S RECENT BRAIN DUMPS (use these for fresh, authentic material)\n${brainDump}`
    : undefined;

  const prompt = buildPrompt(day, tpgWins || undefined, additionalContext);

  const client = new Anthropic();
  const response = await client.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 1500,
    messages: [{ role: 'user', content: prompt }],
  });

  const output = response.content[0].type === 'text' ? response.content[0].text : '';
  return parseGeneratedEmail(output, day);
}

// --- Build comparison report ---

function buildReport(
  email: ReturnType<typeof parseGeneratedEmail>,
  chrisBroadcast: { subject: string; body: string } | null,
  brainDumpUsed: boolean,
  tpgWinsUsed: boolean,
): string {
  const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const tomorrow = days[(new Date().getDay() + 1) % 7];
  const today = days[new Date().getDay()];

  let report = `📧 *Content Machine — Daily Email Mock*\n`;
  report += `${new Date().toISOString().slice(0, 10)}\n\n`;

  // What Chris sent today
  report += `━━━ CHRIS TODAY (${today}) ━━━\n`;
  if (chrisBroadcast) {
    report += `Subject: "${chrisBroadcast.subject}"\n`;
    report += `${chrisBroadcast.body.slice(0, 400)}...\n\n`;
  } else {
    report += `No broadcast detected today.\n\n`;
  }

  // What Claude generated for tomorrow
  const theme = getDayTheme(tomorrow);
  report += `━━━ CLAUDE DRAFT FOR ${tomorrow.toUpperCase()} ━━━\n`;
  report += `Theme: ${theme.theme}\n`;
  report += `Subject: "${email.subject}"\n`;
  report += `Alt subjects: ${email.subjectAlternatives.join(' | ')}\n\n`;
  report += `${email.body}\n\n`;

  // Stats
  report += `━━━ STATS ━━━\n`;
  report += `Words: ${email.body.split(/\s+/).length}\n`;
  report += `Brain Dump data: ${brainDumpUsed ? 'Yes (fresh material used)' : 'No (no recent updates)'}\n`;
  report += `TPG Wins data: ${tpgWinsUsed ? 'Yes' : 'No'}\n`;
  report += `\n💡 This is a MOCK — nothing was sent to Campaign Refinery.\n`;
  report += `Reply with feedback to improve the voice/content.`;

  return report;
}

// --- Main ---

async function main() {
  const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const tomorrow = days[(new Date().getDay() + 1) % 7];

  console.log(`[Email Mock] Generating ${tomorrow}'s email draft...\n`);

  // 1. Pull Brain Dump updates
  console.log('[Email Mock] Pulling Brain Dump updates...');
  const brainDump = getBrainDumpUpdates();
  console.log(brainDump ? `  Found ${brainDump.split('\n').length} lines of brain dump data` : '  No recent brain dump updates');

  // 2. Pull TPG wins
  console.log('[Email Mock] Pulling TPG wins...');
  const tpgWins = getTPGWins();
  console.log(tpgWins ? `  Found TPG wins data` : '  No recent wins data');

  // 3. Check what Chris sent today
  console.log('[Email Mock] Checking Chris\'s broadcast today...');
  const chrisBroadcast = await getTodaysBroadcast();
  console.log(chrisBroadcast ? `  Chris sent: "${chrisBroadcast.subject}"` : '  No broadcast from Chris today');

  // 4. Generate tomorrow's email
  console.log(`[Email Mock] Generating ${tomorrow} email with Claude...`);
  const email = await generateEmail(tomorrow, brainDump, tpgWins);
  console.log(`  Generated: "${email.subject}" (${email.body.split(/\s+/).length} words)`);

  // 5. Build comparison report
  const report = buildReport(email, chrisBroadcast, brainDump.length > 0, tpgWins.length > 0);

  // 6. Save draft
  const draftDir = path.join(STORE_DIR, 'email-drafts');
  fs.mkdirSync(draftDir, { recursive: true });
  const draftFile = path.join(draftDir, `${new Date().toISOString().slice(0, 10)}-mock-${tomorrow.toLowerCase()}.json`);
  fs.writeFileSync(draftFile, JSON.stringify({ email, chrisBroadcast, report, brainDump: brainDump.slice(0, 500) }, null, 2));

  // 7. Save report for Telegram delivery
  const reportFile = path.join(STORE_DIR, 'email-mock-report.txt');
  fs.writeFileSync(reportFile, report);

  console.log(`\n[Email Mock] Done.`);
  console.log(`Draft saved: ${draftFile}`);
  console.log(`Report saved: ${reportFile}`);
  console.log(`\n${report}`);
}

main().catch(err => {
  console.error('Error:', err);
  process.exit(1);
});
