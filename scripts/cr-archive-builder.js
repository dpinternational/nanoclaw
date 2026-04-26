#!/usr/bin/env node
/**
 * Campaign Refinery Archive Builder
 * 
 * Pulls all broadcast data + stats from Campaign Refinery API
 * and saves to a JSON archive for the intelligence system.
 * 
 * Run on the NanoClaw server: node scripts/cr-archive-builder.js
 */

const fs = require('fs');
const path = require('path');

const API_KEY = fs.readFileSync(path.join(process.env.HOME || '/home/david', '.env').replace('.env', 'nanoclaw/.env'), 'utf-8')
  .match(/CAMPAIGN_REFINERY_API_KEY=(.+)/)?.[1]?.trim() 
  || fs.readFileSync('/home/david/nanoclaw/.env', 'utf-8').match(/CAMPAIGN_REFINERY_API_KEY=(.+)/)[1].trim();

const BASE = 'https://app.campaignrefinery.com/rest';
const OUTPUT_PATH = '/home/david/nanoclaw/data/cr-broadcast-archive.json';

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

async function main() {
  console.log('Fetching broadcasts from Campaign Refinery...');
  
  // Get all broadcasts
  const bData = await crGet('/broadcasts/get-broadcasts');
  const broadcasts = bData.broadcasts || [];
  console.log(`Found ${broadcasts.length} broadcasts`);
  
  // Get stats for each broadcast
  const archive = [];
  for (const b of broadcasts) {
    let stats = {};
    try {
      const sData = await crPost('/broadcasts/get-broadcast-stats', {
        broadcast_id: b.id,
      });
      stats = sData.broadcast_stats || {};
    } catch (e) {
      console.error(`  Stats error for ${b.subject}: ${e.message}`);
    }
    
    const sent = parseInt(stats.sent || '0');
    const delivered = parseInt(stats.delivered || '0');
    const opened = parseInt(stats.opened || '0');
    const clicked = parseInt(stats.clicked || '0');
    const bounced = parseInt(stats.bounced || '0');
    const complained = parseInt(stats.complained || '0');
    const unsubscribed = parseInt(stats.unsubscribed || '0');
    
    const record = {
      id: b.id,
      name: b.name,
      subject: b.subject,
      status: b.status,
      audience: b.audience_name,
      domain: b.domain,
      scheduled_at: b.scheduled_at,
      sent_at: b.completed_sending_at || b.started_sending_at,
      num_emails: b.num_emails,
      stats: {
        sent,
        delivered,
        opened,
        clicked,
        bounced,
        complained,
        unsubscribed,
        open_rate: sent > 0 ? Math.round((opened / sent) * 1000) / 10 : 0,
        click_rate: sent > 0 ? Math.round((clicked / sent) * 1000) / 10 : 0,
        bounce_rate: sent > 0 ? Math.round((bounced / sent) * 1000) / 10 : 0,
        unsub_rate: sent > 0 ? Math.round((unsubscribed / sent) * 1000) / 10 : 0,
      },
    };
    
    archive.push(record);
    console.log(`  ${record.subject} — ${record.stats.open_rate}% open, ${record.stats.click_rate}% click`);
  }
  
  // Sort by date
  archive.sort((a, b) => (b.sent_at || '').localeCompare(a.sent_at || ''));
  
  // Get contact stats
  let contactStats = {};
  try {
    const cData = await crGet('/contacts/get-contacts');
    const contacts = cData.contacts || [];
    contactStats = {
      total: contacts.length,
      note: 'Limited to API page size — may not be total',
    };
  } catch (e) {
    contactStats = { error: e.message };
  }
  
  const output = {
    fetched_at: new Date().toISOString(),
    total_broadcasts: archive.length,
    broadcasts: archive,
    contact_stats: contactStats,
    summary: {
      total_sends: archive.reduce((s, b) => s + (b.stats.sent || 0), 0),
      avg_open_rate: archive.length > 0 
        ? Math.round(archive.reduce((s, b) => s + b.stats.open_rate, 0) / archive.length * 10) / 10 
        : 0,
      avg_click_rate: archive.length > 0
        ? Math.round(archive.reduce((s, b) => s + b.stats.click_rate, 0) / archive.length * 10) / 10
        : 0,
      best_open: archive.reduce((best, b) => b.stats.open_rate > (best?.stats?.open_rate || 0) ? b : best, null),
      worst_open: archive.reduce((worst, b) => b.stats.open_rate < (worst?.stats?.open_rate || 100) ? b : worst, null),
    },
  };
  
  fs.writeFileSync(OUTPUT_PATH, JSON.stringify(output, null, 2));
  console.log(`\nArchive saved to ${OUTPUT_PATH}`);
  console.log(`Total broadcasts: ${output.total_broadcasts}`);
  console.log(`Avg open rate: ${output.summary.avg_open_rate}%`);
  console.log(`Best: "${output.summary.best_open?.subject}" (${output.summary.best_open?.stats?.open_rate}%)`);
  console.log(`Worst: "${output.summary.worst_open?.subject}" (${output.summary.worst_open?.stats?.open_rate}%)`);
  
  // Also output as JSON for script consumption
  console.log('\n__JSON__');
  console.log(JSON.stringify(output.summary));
}

main().catch(e => {
  console.error('Fatal error:', e.message);
  process.exit(1);
});
