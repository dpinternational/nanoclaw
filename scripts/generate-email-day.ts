/**
 * Generate an email for a specific day with optional Brain Dump content.
 * Usage: npx tsx scripts/generate-email-day.ts <Day> [braindump text]
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import Database from 'better-sqlite3';
import Anthropic from '@anthropic-ai/sdk';
import { buildPrompt, parseGeneratedEmail } from '../src/email-generator.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');

async function main() {
  const day = process.argv[2] || 'Monday';

  // Pull latest Brain Dump
  let brainDump = '';
  try {
    const db = new Database(path.join(PROJECT_ROOT, 'store', 'messages.db'), { readonly: true });
    const messages = db.prepare(`
      SELECT content, timestamp FROM messages
      WHERE chat_jid = 'tg:-5147163125' AND is_bot_message = 0
      ORDER BY timestamp DESC LIMIT 10
    `).all() as any[];
    db.close();

    if (messages.length > 0) {
      brainDump = "David's recent Brain Dump updates:\n\n";
      for (const m of messages.reverse()) {
        brainDump += `${m.content.slice(0, 1000)}\n\n`;
      }
    }
  } catch {}

  console.log(`Generating ${day} email...\n`);
  if (brainDump) console.log(`Using ${brainDump.split('\n').length} lines of Brain Dump data\n`);

  const prompt = buildPrompt(day, undefined, brainDump || undefined);
  const client = new Anthropic();
  const response = await client.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 1500,
    messages: [{ role: 'user', content: prompt }],
  });

  const output = response.content[0].type === 'text' ? response.content[0].text : '';
  const email = parseGeneratedEmail(output, day);

  console.log(`SUBJECT: ${email.subject}`);
  console.log(`ALT: ${email.subjectAlternatives.join(' | ')}`);
  console.log('');
  console.log(email.body);
  console.log(`\nWords: ${email.body.split(/\s+/).length}`);
}

main().catch(console.error);
