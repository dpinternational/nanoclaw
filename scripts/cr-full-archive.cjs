#!/usr/bin/env node
/**
 * Campaign Refinery Full Archive Builder
 * 
 * Pulls broadcast data + stats from CR API, then fetches actual
 * email content from Gmail. Builds a complete archive for AI training.
 * 
 * Run on server: cd /home/david/nanoclaw && node scripts/cr-full-archive.cjs
 */

const fs = require('fs');
const path = require('path');
const { google } = require('googleapis');

const API_KEY = fs.readFileSync('/home/david/nanoclaw/.env', 'utf-8')
  .match(/CAMPAIGN_REFINERY_API_KEY=(.+)/)[1].trim();
const BASE = 'https://app.campaignrefinery.com/rest';
const OUTPUT_PATH = '/home/david/nanoclaw/data/cr-full-archive.json';

// Gmail auth
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

async function crGet(endpoint) {
  const res = await fetch(`${BASE}${endpoint}?key=${API_KEY}`);
  return res.json();
}

async function crPost(endpoint, body = {}) {
  const res = await fetch(`${BASE}${endpoint}?key=${API_KEY}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json();
}

async function getEmailContent(subject) {
  try {
    const res = await gmail.users.messages.list({
      userId: 'me',
      q: `subject:"${subject}" from:david@tpglife.com OR from:davidprice@tpglife.com`,
      maxResults: 1,
    });
    if (!res.data.messages || res.data.messages.length === 0) return null;
    
    const msg = await gmail.users.messages.get({
      userId: 'me', id: res.data.messages[0].id, format: 'full',
    });
    
    let plainText = '';
    let html = '';
    const payload = msg.data.payload;
    
    function extractParts(parts) {
      for (const part of parts || []) {
        if (part.mimeType === 'text/plain' && part.body?.data) {
          plainText = Buffer.from(part.body.data, 'base64').toString('utf-8');
        }
        if (part.mimeType === 'text/html' && part.body?.data) {
          html = Buffer.from(part.body.data, 'base64').toString('utf-8');
        }
        if (part.parts) extractParts(part.parts);
      }
    }
    
    if (payload.body?.data) {
      plainText = Buffer.from(payload.body.data, 'base64').toString('utf-8');
    }
    if (payload.parts) extractParts(payload.parts);
    
    return {
      plain_text: plainText,
      html_length: html.length,
      word_count: plainText.split(/\s+/).filter(w => w).length,
    };
  } catch (e) {
    return { error: e.message };
  }
}

async function main() {
  console.log('=== Campaign Refinery Full Archive Builder ===\n');
  
  // Step 1: Get broadcasts
  console.log('1. Fetching broadcasts...');
  const bData = await crGet('/broadcasts/get-broadcasts');
  const broadcasts = bData.broadcasts || [];
  console.log(`   Found ${broadcasts.length} broadcasts\n`);
  
  // Step 2: Get stats + email content for each
  console.log('2. Fetching stats and email content...');
  const archive = [];
  
  for (const b of broadcasts) {
    // Stats
    let stats = {};
    try {
      const sData = await crPost('/broadcasts/get-broadcast-stats', { broadcast_id: b.id });
      stats = sData.broadcast_stats || {};
    } catch (e) { /* skip */ }
    
    const sent = parseInt(stats.sent || '0');
    const opened = parseInt(stats.opened || '0');
    const clicked = parseInt(stats.clicked || '0');
    const bounced = parseInt(stats.bounced || '0');
    const unsubscribed = parseInt(stats.unsubscribed || '0');
    
    // Email content from Gmail
    const content = await getEmailContent(b.subject);
    
    const record = {
      id: b.id,
      name: b.name,
      subject: b.subject,
      sent_at: b.completed_sending_at || b.started_sending_at,
      audience: b.audience_name,
      num_emails: b.num_emails,
      stats: {
        sent, opened, clicked, bounced, unsubscribed,
        open_rate: sent > 0 ? Math.round((opened / sent) * 1000) / 10 : 0,
        click_rate: sent > 0 ? Math.round((clicked / sent) * 1000) / 10 : 0,
        unsub_rate: sent > 0 ? Math.round((unsubscribed / sent) * 1000) / 10 : 0,
      },
      content: content ? {
        body: content.plain_text,
        word_count: content.word_count,
      } : null,
    };
    
    archive.push(record);
    const status = content?.plain_text ? '✓' : '✗';
    console.log(`   ${status} "${b.subject}" — ${record.stats.open_rate}% open, ${content?.word_count || 0} words`);
  }
  
  // Sort newest first
  archive.sort((a, b) => (b.sent_at || '').localeCompare(a.sent_at || ''));
  
  // Summary
  const withContent = archive.filter(b => b.content?.body);
  const output = {
    fetched_at: new Date().toISOString(),
    total_broadcasts: archive.length,
    broadcasts_with_content: withContent.length,
    summary: {
      total_sends: archive.reduce((s, b) => s + b.stats.sent, 0),
      avg_open_rate: Math.round(archive.reduce((s, b) => s + b.stats.open_rate, 0) / archive.length * 10) / 10,
      avg_word_count: withContent.length > 0
        ? Math.round(withContent.reduce((s, b) => s + b.content.word_count, 0) / withContent.length)
        : 0,
      best_subject: archive.reduce((best, b) => b.stats.open_rate > (best?.stats?.open_rate || 0) ? b : best, null)?.subject,
      best_open_rate: archive.reduce((best, b) => b.stats.open_rate > (best?.stats?.open_rate || 0) ? b : best, null)?.stats?.open_rate,
      subject_patterns: archive.map(b => ({
        subject: b.subject,
        open_rate: b.stats.open_rate,
        word_count: b.content?.word_count || 0,
        length: b.subject.length,
        has_question: b.subject.includes('?'),
        has_number: /\d/.test(b.subject),
        lowercase: b.subject === b.subject.toLowerCase(),
      })),
    },
    broadcasts: archive,
  };
  
  fs.writeFileSync(OUTPUT_PATH, JSON.stringify(output, null, 2));
  
  console.log(`\n=== Archive Complete ===`);
  console.log(`Saved to: ${OUTPUT_PATH}`);
  console.log(`Broadcasts: ${output.total_broadcasts} (${output.broadcasts_with_content} with content)`);
  console.log(`Avg open rate: ${output.summary.avg_open_rate}%`);
  console.log(`Avg word count: ${output.summary.avg_word_count}`);
  console.log(`Best subject: "${output.summary.best_subject}" (${output.summary.best_open_rate}%)`);
  
  console.log(`\nSubject line patterns:`);
  for (const p of output.summary.subject_patterns) {
    console.log(`  ${p.open_rate}% — "${p.subject}" (${p.word_count}w, ${p.lowercase ? 'lowercase' : 'mixed case'}${p.has_question ? ', question' : ''}${p.has_number ? ', has number' : ''})`);
  }
}

main().catch(e => {
  console.error('Fatal:', e.message);
  process.exit(1);
});
