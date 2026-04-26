/**
 * CR Monitor — Standalone (no Docker, no NanoClaw dependency)
 * Runs the monitor and sends report directly to Telegram.
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

  // Telegram 4096 char limit
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
  // Import and run the monitor
  const { runMonitor } = await import('../src/cr-monitor.js');
  const report = await runMonitor();

  // Send to Telegram
  const sent = await sendTelegram(report);
  console.log(sent ? 'Report sent to Telegram' : 'Failed to send to Telegram');
}

main().catch(err => {
  console.error('CR Monitor standalone failed:', err);
  // Try to alert via Telegram even on failure
  sendTelegram(`⚠️ CR Monitor failed: ${err.message}`).catch(() => {});
  process.exit(1);
});
