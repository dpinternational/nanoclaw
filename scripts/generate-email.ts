/**
 * Generate today's daily email using Claude + the email generator engine.
 * Usage: npx tsx scripts/generate-email.ts [DayOfWeek]
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import Anthropic from '@anthropic-ai/sdk';
import { buildPrompt, parseGeneratedEmail } from '../src/email-generator.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const PROJECT_ROOT = path.resolve(__dirname, '..');

async function main() {
  const dayArg = process.argv[2];
  const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  const day = dayArg || days[new Date().getDay()];

  console.log(`Generating ${day} email with Claude...\n`);

  const prompt = buildPrompt(day);
  const client = new Anthropic();

  const response = await client.messages.create({
    model: 'claude-sonnet-4-20250514',
    max_tokens: 1500,
    messages: [{ role: 'user', content: prompt }],
  });

  const output = response.content[0].type === 'text' ? response.content[0].text : '';
  const email = parseGeneratedEmail(output, day);

  console.log('=== GENERATED EMAIL ===\n');
  console.log(`SUBJECT: ${email.subject}`);
  console.log(`ALT 1: ${email.subjectAlternatives[0] || ''}`);
  console.log(`ALT 2: ${email.subjectAlternatives[1] || ''}`);
  console.log('');
  console.log(email.body);
  console.log('\n--- Stats ---');
  console.log(`Words: ${email.body.split(/\s+/).length}`);
  console.log(`Chars: ${email.body.length}`);

  // Save draft
  const outDir = path.join(PROJECT_ROOT, 'store', 'email-drafts');
  fs.mkdirSync(outDir, { recursive: true });
  const filename = path.join(outDir, `${new Date().toISOString().slice(0, 10)}-${day.toLowerCase()}.json`);
  fs.writeFileSync(filename, JSON.stringify(email, null, 2));
  console.log(`\nSaved to: ${filename}`);
}

main().catch(err => {
  console.error('Error:', err);
  process.exit(1);
});
