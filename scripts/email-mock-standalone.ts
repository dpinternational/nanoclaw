/**
 * Email Mock — Standalone (no Docker, no NanoClaw dependency)
 * Generates tomorrow's email draft and sends comparison to Telegram.
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');

function readEnvVar(name: string): string {
  const envPath = path.join(PROJECT_ROOT, '.env');
  const content = fs.readFileSync(envPath, 'utf-8');
  const match = content.match(new RegExp(`^${name}=(.+)`, 'm'));
  return match?.[1]?.trim() || '';
}

async function sendTelegram(text: string): Promise<boolean> {
  const token = readEnvVar('TELEGRAM_BOT_TOKEN');
  if (!token) { console.error('No TELEGRAM_BOT_TOKEN'); return false; }

  const chunks = [];
  for (let i = 0; i < text.length; i += 4000) {
    chunks.push(text.slice(i, i + 4000));
  }

  for (const chunk of chunks) {
    const res = await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: 577469008, text: chunk }),
    });
    const data = await res.json() as any;
    if (!data.ok) { console.error('Telegram error:', data); return false; }
  }
  return true;
}

async function main() {
  // Set env vars for the Anthropic SDK
  process.env.ANTHROPIC_API_KEY = readEnvVar('ANTHROPIC_API_KEY');

  // Run the mock generator (it reads from DB and APIs directly)
  const mockScript = path.join(PROJECT_ROOT, 'scripts', 'daily-email-mock.ts');

  // Dynamic import of the generator components
  const { buildPrompt, parseGeneratedEmail, getDayTheme } = await import('../src/email-generator.js');
  const Database = (await import('better-sqlite3')).default;
  const Anthropic = (await import('@anthropic-ai/sdk')).default;

  const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const tomorrow = days[(new Date().getDay() + 1) % 7];
  const today = days[new Date().getDay()];

  console.log(`[Email Mock Standalone] Generating ${tomorrow} email...`);

  // Pull Brain Dump
  let brainDump = '';
  try {
    const db = new Database(path.join(PROJECT_ROOT, 'store', 'messages.db'), { readonly: true });
    const cutoff = new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString();
    const messages = db.prepare(`
      SELECT content, timestamp FROM messages
      WHERE chat_jid = 'tg:-5147163125' AND timestamp > ? AND is_bot_message = 0
      ORDER BY timestamp DESC LIMIT 20
    `).all(cutoff) as any[];
    db.close();
    if (messages.length > 0) {
      brainDump = "David's recent Brain Dump:\n\n";
      for (const m of messages.reverse()) {
        brainDump += `${m.content.slice(0, 500)}\n\n`;
      }
    }
  } catch {}

  // Pull TPG wins
  let tpgWins = '';
  try {
    const db = new Database(path.join(PROJECT_ROOT, 'store', 'messages.db'), { readonly: true });
    const cutoff = new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString();
    const messages = db.prepare(`
      SELECT content, sender_name FROM messages
      WHERE chat_jid = 'tg:-1002362081030' AND timestamp > ?
        AND (content LIKE '%$%' OR content LIKE '%wrote%' OR content LIKE '%issued%')
      ORDER BY timestamp DESC LIMIT 10
    `).all(cutoff) as any[];
    db.close();
    if (messages.length > 0) {
      tpgWins = "Recent TPG wins:\n";
      for (const m of messages) tpgWins += `- ${m.sender_name}: ${m.content.slice(0, 300)}\n`;
    }
  } catch {}

  // Check Chris's broadcast today
  let chrisSubject = '';
  try {
    const archivePath = path.join(PROJECT_ROOT, 'store', 'cr-email-archive.json');
    if (fs.existsSync(archivePath)) {
      const archive = JSON.parse(fs.readFileSync(archivePath, 'utf-8'));
      const todayStr = new Date().toISOString().slice(0, 10);
      const todayEmail = archive.find((e: any) => new Date(e.date).toISOString().slice(0, 10) === todayStr);
      if (todayEmail) chrisSubject = todayEmail.subject;
    }
    if (!chrisSubject) {
      const apiKey = readEnvVar('CAMPAIGN_REFINERY_API_KEY');
      const res = await fetch(`https://app.campaignrefinery.com/rest/broadcasts/get-broadcasts?key=${apiKey}`);
      const data = await res.json() as any;
      const todayStr = new Date().toISOString().slice(0, 10);
      const b = data.broadcasts?.find((b: any) => b.created_at?.startsWith(todayStr));
      if (b) chrisSubject = b.subject;
    }
  } catch {}

  // Generate email
  const prompt = buildPrompt(tomorrow, tpgWins || undefined, brainDump || undefined);
  const client = new Anthropic();
  const response = await client.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 1500,
    messages: [{ role: 'user', content: prompt }],
  });

  const output = response.content[0].type === 'text' ? response.content[0].text : '';
  const email = parseGeneratedEmail(output, tomorrow);
  const theme = getDayTheme(tomorrow);

  // Build report
  let report = `📧 Content Machine — Daily Email Mock\n${new Date().toISOString().slice(0, 10)}\n\n`;
  report += `━━━ CHRIS TODAY (${today}) ━━━\n`;
  report += chrisSubject ? `Subject: "${chrisSubject}"\n\n` : `No broadcast sent today.\n\n`;
  report += `━━━ CLAUDE DRAFT FOR ${tomorrow.toUpperCase()} ━━━\n`;
  report += `Theme: ${theme.theme}\n`;
  report += `Subject: "${email.subject}"\n`;
  report += `Alt: ${email.subjectAlternatives.join(' | ')}\n\n`;
  report += `${email.body}\n\n`;
  report += `━━━ STATS ━━━\n`;
  report += `Words: ${email.body.split(/\s+/).length}\n`;
  report += `Brain Dump: ${brainDump ? 'Yes' : 'No'}\n`;
  report += `TPG Wins: ${tpgWins ? 'Yes' : 'No'}\n`;
  report += `\nThis is a MOCK — nothing sent to Campaign Refinery.`;

  // Save draft
  const draftDir = path.join(PROJECT_ROOT, 'store', 'email-drafts');
  fs.mkdirSync(draftDir, { recursive: true });
  fs.writeFileSync(path.join(draftDir, `${new Date().toISOString().slice(0, 10)}-mock-${tomorrow.toLowerCase()}.json`), JSON.stringify(email, null, 2));
  fs.writeFileSync(path.join(PROJECT_ROOT, 'store', 'email-mock-report.txt'), report);

  // Send to Telegram
  const sent = await sendTelegram(report);
  console.log(sent ? 'Report sent to Telegram' : 'Failed to send');
}

main().catch(err => {
  console.error('Email Mock standalone failed:', err);
  sendTelegram(`⚠️ Email Mock failed: ${err.message}`).catch(() => {});
  process.exit(1);
});
