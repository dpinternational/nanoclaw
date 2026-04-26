/**
 * Pull Campaign Refinery broadcast emails from david@tpglife.com inbox
 * These are emails sent FROM davidprice@tpglife.com (the CR sending address)
 */

import fs from 'fs';
import os from 'os';
import path from 'path';
import { google } from 'googleapis';
import { OAuth2Client } from 'google-auth-library';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

async function main() {
  const credDir = path.join(os.homedir(), '.gmail-mcp');
  const creds = JSON.parse(fs.readFileSync(path.join(credDir, 'gcp-oauth.keys.json'), 'utf-8'));
  const tokens = JSON.parse(fs.readFileSync(path.join(credDir, 'credentials.json'), 'utf-8'));

  const installed = creds.installed || creds.web;
  const oauth2 = new OAuth2Client(installed.client_id, installed.client_secret, installed.redirect_uris?.[0]);
  oauth2.setCredentials(tokens);

  const gmail = google.gmail({ version: 'v1', auth: oauth2 });

  // Search for emails from davidprice@tpglife.com (CR broadcast sender)
  const res = await gmail.users.messages.list({
    userId: 'me',
    q: 'from:davidprice@tpglife.com',
    maxResults: 50,
  });

  console.log(`Found ${res.data.resultSizeEstimate} emails from davidprice@tpglife.com\n`);

  if (!res.data.messages) {
    console.log('No messages found.');
    return;
  }

  const emails: Array<{
    date: string;
    subject: string;
    snippet: string;
    body: string;
    labels: string[];
  }> = [];

  for (const m of res.data.messages) {
    const msg = await gmail.users.messages.get({
      userId: 'me',
      id: m.id!,
      format: 'full',
    });

    const headers = msg.data.payload?.headers || [];
    const subject = headers.find(h => h.name === 'Subject')?.value || '(no subject)';
    const date = headers.find(h => h.name === 'Date')?.value || '';
    const labels = msg.data.labelIds || [];

    // Extract body text
    let body = '';
    const payload = msg.data.payload;

    if (payload?.body?.data) {
      body = Buffer.from(payload.body.data, 'base64url').toString('utf-8');
    } else if (payload?.parts) {
      // Look for text/plain first, then text/html
      const textPart = payload.parts.find(p => p.mimeType === 'text/plain');
      const htmlPart = payload.parts.find(p => p.mimeType === 'text/html');

      if (textPart?.body?.data) {
        body = Buffer.from(textPart.body.data, 'base64url').toString('utf-8');
      } else if (htmlPart?.body?.data) {
        // Strip HTML tags for readable text
        body = Buffer.from(htmlPart.body.data, 'base64url').toString('utf-8')
          .replace(/<style[^>]*>[\s\S]*?<\/style>/gi, '')
          .replace(/<[^>]+>/g, ' ')
          .replace(/&nbsp;/g, ' ')
          .replace(/&amp;/g, '&')
          .replace(/&lt;/g, '<')
          .replace(/&gt;/g, '>')
          .replace(/&#\d+;/g, '')
          .replace(/\s+/g, ' ')
          .trim();
      }
    }

    emails.push({
      date,
      subject,
      snippet: msg.data.snippet || '',
      body,
      labels,
    });
  }

  // Print summary
  console.log('=== CHRIS\'S EMAILS (from CR broadcasts to david@tpglife.com) ===\n');

  for (const email of emails) {
    console.log(`DATE: ${email.date}`);
    console.log(`SUBJECT: ${email.subject}`);
    console.log(`LABELS: ${email.labels.join(', ')}`);
    console.log(`BODY:`);
    console.log(email.body.slice(0, 1500));
    console.log('\n' + '='.repeat(80) + '\n');
  }

  // Save full archive
  const outPath = path.resolve(__dirname, '..', 'store', 'cr-email-archive.json');
  fs.writeFileSync(outPath, JSON.stringify(emails, null, 2));
  console.log(`\nFull archive saved to ${outPath}`);
  console.log(`Total emails archived: ${emails.length}`);
}

main().catch(err => {
  console.error('Error:', err);
  process.exit(1);
});
