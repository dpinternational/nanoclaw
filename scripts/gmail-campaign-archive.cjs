#!/usr/bin/env node
/**
 * Full Email Campaign Archive from Gmail
 * 
 * Pulls ALL emails sent from davidprice@tpglife.com (the CR sending address)
 * with subjects, bodies, dates, and word counts.
 * 
 * Run: cd /home/david/nanoclaw && node scripts/gmail-campaign-archive.cjs
 */

const fs = require('fs');
const path = require('path');
const { google } = require('googleapis');

const credDir = '/home/david/.gmail-mcp';
const keys = JSON.parse(fs.readFileSync(path.join(credDir, 'gcp-oauth.keys.json'), 'utf-8'));
const tokens = JSON.parse(fs.readFileSync(path.join(credDir, 'credentials.json'), 'utf-8'));
const config = keys.installed || keys.web || keys;
const auth = new google.auth.OAuth2(config.client_id, config.client_secret, config.redirect_uris?.[0]);
auth.setCredentials(tokens);
auth.on('tokens', t => {
  const c = JSON.parse(fs.readFileSync(path.join(credDir, 'credentials.json'), 'utf-8'));
  Object.assign(c, t);
  fs.writeFileSync(path.join(credDir, 'credentials.json'), JSON.stringify(c, null, 2));
});
const gmail = google.gmail({ version: 'v1', auth });

const OUTPUT = '/home/david/nanoclaw/data/campaign-email-archive.json';

async function getAllMessageIds(query) {
  const ids = [];
  let pageToken = null;
  while (true) {
    const params = { userId: 'me', q: query, maxResults: 100 };
    if (pageToken) params.pageToken = pageToken;
    const res = await gmail.users.messages.list(params);
    for (const m of res.data.messages || []) ids.push(m.id);
    pageToken = res.data.nextPageToken;
    if (!pageToken) break;
  }
  return ids;
}

async function getEmailContent(id) {
  const msg = await gmail.users.messages.get({ userId: 'me', id, format: 'full' });
  const headers = msg.data.payload.headers || [];
  const getHeader = (name) => headers.find(h => h.name.toLowerCase() === name.toLowerCase())?.value || '';
  
  let plainText = '';
  function extractParts(payload) {
    if (payload.body?.data) {
      if (!plainText && (payload.mimeType === 'text/plain' || !payload.mimeType)) {
        plainText = Buffer.from(payload.body.data, 'base64').toString('utf-8');
      }
    }
    for (const part of payload.parts || []) {
      if (part.mimeType === 'text/plain' && part.body?.data) {
        plainText = Buffer.from(part.body.data, 'base64').toString('utf-8');
      }
      if (part.parts) extractParts(part);
    }
  }
  extractParts(msg.data.payload);
  
  return {
    id,
    subject: getHeader('Subject'),
    from: getHeader('From'),
    date: getHeader('Date'),
    body: plainText,
    word_count: plainText.split(/\s+/).filter(w => w).length,
    snippet: msg.data.snippet,
  };
}

async function main() {
  console.log('=== Gmail Campaign Email Archive Builder ===\n');
  
  // Get all emails from the CR sending address
  console.log('1. Finding all campaign emails...');
  const ids = await getAllMessageIds('from:davidprice@tpglife.com');
  console.log(`   Found ${ids.length} emails\n`);
  
  console.log('2. Fetching content (this may take a minute)...');
  const emails = [];
  let fetched = 0;
  
  for (const id of ids) {
    try {
      const email = await getEmailContent(id);
      emails.push(email);
      fetched++;
      if (fetched % 25 === 0) console.log(`   ${fetched}/${ids.length} fetched...`);
    } catch (e) {
      console.error(`   Error fetching ${id}: ${e.message}`);
    }
  }
  
  // Sort by date (newest first)
  emails.sort((a, b) => new Date(b.date) - new Date(a.date));
  
  // Deduplicate by subject (CR sometimes sends test + live)
  const seen = new Set();
  const unique = [];
  for (const e of emails) {
    const key = e.subject?.toLowerCase().trim();
    if (!seen.has(key)) {
      seen.add(key);
      unique.push(e);
    }
  }
  
  // Analyze patterns
  const withBody = unique.filter(e => e.word_count > 20);
  const avgWords = withBody.length > 0
    ? Math.round(withBody.reduce((s, e) => s + e.word_count, 0) / withBody.length)
    : 0;
  
  const output = {
    fetched_at: new Date().toISOString(),
    total_fetched: emails.length,
    unique_subjects: unique.length,
    emails_with_content: withBody.length,
    avg_word_count: avgWords,
    date_range: {
      oldest: emails[emails.length - 1]?.date,
      newest: emails[0]?.date,
    },
    emails: unique,
  };
  
  fs.writeFileSync(OUTPUT, JSON.stringify(output, null, 2));
  
  console.log(`\n=== Archive Complete ===`);
  console.log(`Total fetched: ${emails.length}`);
  console.log(`Unique subjects: ${unique.length}`);
  console.log(`With content (>20 words): ${withBody.length}`);
  console.log(`Avg word count: ${avgWords}`);
  console.log(`Date range: ${output.date_range.oldest} to ${output.date_range.newest}`);
  console.log(`Saved to: ${OUTPUT}`);
  
  // Print recent subjects
  console.log('\nRecent subjects:');
  for (const e of unique.slice(0, 15)) {
    console.log(`  ${e.date?.substring(0, 16)} — "${e.subject}" (${e.word_count}w)`);
  }
}

main().catch(e => {
  console.error('Fatal:', e.message);
  process.exit(1);
});
