#!/usr/bin/env node

/**
 * Parse Sandra's and Robert's recruitment spreadsheets
 * Extracts prospect data and daily metrics, stores in recruitment.db
 */

const { google } = require('googleapis');
const fs = require('fs');
const path = require('path');
const os = require('os');
const Database = require('better-sqlite3');

const CRED_DIR = path.join(os.homedir(), '.gmail-mcp');
const DB_PATH = path.join(process.cwd(), 'data', 'recruitment', 'recruitment.db');

const SANDRA_SHEET_ID = '1_LJLwIrxcR13fMnNXPcAvJtzKG4IL_jDsNEUMdJdWpY';
const CONTRACTING_SHEET_ID = '1UN7t-OXYxUgQjpkCWMrvlKtCVXNnByWIk3Szgon7Ku8';
const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];

// Status code mapping
const STATUS_MAP = {
  'Attpt': 'attempted', 'Attp': 'attempted',
  'PST': 'presentation', 'Sch': 'scheduled',
  'FU': 'follow_up', 'N/I': 'not_interested',
  'N/E': 'not_eligible', 'DND': 'do_not_hire',
  'add on': 'contacted', 'invalid': 'not_eligible',
  'VM': 'attempted', 'LM': 'attempted',
  'CB': 'follow_up', 'Int': 'interview',
};

async function getAuth() {
  const keys = JSON.parse(fs.readFileSync(path.join(CRED_DIR, 'gcp-oauth.keys.json'), 'utf-8'));
  const tokens = JSON.parse(fs.readFileSync(path.join(CRED_DIR, 'credentials.json'), 'utf-8'));
  const config = keys.installed || keys.web || keys;
  const auth = new google.auth.OAuth2(config.client_id, config.client_secret, config.redirect_uris?.[0]);
  auth.setCredentials(tokens);
  auth.on('tokens', (t) => {
    const c = JSON.parse(fs.readFileSync(path.join(CRED_DIR, 'credentials.json'), 'utf-8'));
    Object.assign(c, t);
    fs.writeFileSync(path.join(CRED_DIR, 'credentials.json'), JSON.stringify(c, null, 2));
  });
  return auth;
}

async function parseSheet(sheets, spreadsheetId, sheetName, recruiterName) {
  try {
    const res = await sheets.spreadsheets.values.get({
      spreadsheetId,
      range: `${sheetName}!A:H`,
    });
    const rows = res.data.values || [];

    // Find the date from row 1 (Name, Date)
    let reportDate = null;
    if (rows[1] && rows[1][1]) {
      const dateStr = rows[1][1]; // e.g., "3/23/26"
      const parts = dateStr.split('/');
      if (parts.length === 3) {
        const year = parts[2].length === 2 ? '20' + parts[2] : parts[2];
        reportDate = `${year}-${parts[0].padStart(2, '0')}-${parts[1].padStart(2, '0')}`;
      }
    }

    // Find data rows (start after header row which has "Name", "Phone", etc.)
    let dataStartRow = -1;
    for (let i = 0; i < rows.length; i++) {
      if (rows[i] && rows[i][0] === 'Name' && rows[i][1] === 'Phone') {
        dataStartRow = i + 1;
        break;
      }
    }

    if (dataStartRow === -1 || !reportDate) {
      return { prospects: [], metrics: null, date: reportDate };
    }

    const prospects = [];
    let totalCalls = 0;
    let contacts = 0;
    let presentations = 0;
    let scheduled = 0;
    let attempted = 0;

    for (let i = dataStartRow; i < rows.length; i++) {
      const row = rows[i];
      if (!row || !row[0] || !row[0].trim()) continue;

      const name = row[0].trim();
      // Skip summary rows
      if (name.startsWith('Calendar') || name.startsWith('Email Check') ||
          name.startsWith('Called') || name.startsWith('Updated') ||
          name.startsWith('Followed') || name.startsWith('Mtg')) {
        continue;
      }

      // Determine column layout based on recruiter
      // Sandra: Name, Phone, Email, Licensed, Type, Notes, Time
      // Robert: Name, Phone, Outbound/Inbound, Email, Licensed, Type, Notes
      let phone, email, licensed, statusCode, notes;
      if (recruiterName === 'Robert Ramsey') {
        // Robert: Name, Phone, Outbound/Inbound, Email, Licensed, Type, Notes
        phone = (row[1] || '').replace(/\.0$/, '');
        email = row[3] || '';
        licensed = row[4] || '';
        statusCode = row[5] || '';
        notes = row[6] || '';
      } else {
        // Sandra: Name, Phone, Email, Licensed, Type, Notes, Time
        phone = row[1] || '';
        email = row[2] || '';
        licensed = row[3] || '';
        statusCode = row[4] || '';
        notes = row[5] || '';
      }

      // Skip if statusCode looks like a time (e.g., "9:00", "10:30")
      if (/^\d{1,2}:\d{2}$/.test(statusCode)) {
        statusCode = '';
      }

      const trimmedCode = statusCode.trim();
      const status = STATUS_MAP[trimmedCode] || STATUS_MAP[trimmedCode.toLowerCase()] || (trimmedCode ? trimmedCode.toLowerCase() : 'contacted');

      totalCalls++;
      if (status === 'presentation') presentations++;
      else if (status === 'scheduled') scheduled++;
      else if (status === 'attempted') attempted++;
      if (status !== 'attempted' && status !== 'not_eligible') contacts++;

      prospects.push({
        name,
        phone: phone.replace(/[^\d]/g, ''),
        email,
        licensed,
        status,
        notes,
        recruiter: recruiterName,
        date: reportDate,
      });
    }

    return {
      prospects,
      metrics: {
        date: reportDate,
        recruiter: recruiterName,
        dials: totalCalls,
        contacts,
        presentations,
        scheduled,
        attempted,
      },
      date: reportDate,
    };
  } catch (e) {
    console.error(`Error reading ${sheetName}: ${e.message}`);
    return { prospects: [], metrics: null, date: null };
  }
}

function getWeekDatesFromFilename(filename) {
  // "Robert_WE_3_27_26.xlsx" → week ending 2026-03-27
  const match = filename.match(/WE_(\d+)_(\d+)_(\d+)/);
  if (!match) return null;
  const [, month, day, yr] = match;
  const year = yr.length === 2 ? '20' + yr : yr;
  const weekEnd = new Date(`${year}-${month.padStart(2, '0')}-${day.padStart(2, '0')}T12:00:00`);

  // Calculate Mon-Fri dates (week ending is typically Friday or Saturday)
  const dayOfWeek = weekEnd.getDay(); // 0=Sun, 5=Fri, 6=Sat
  const fridayOffset = dayOfWeek === 6 ? 1 : (dayOfWeek === 0 ? 2 : 5 - dayOfWeek);
  const friday = new Date(weekEnd);
  friday.setDate(friday.getDate() - fridayOffset);

  const dates = {};
  const dayNames = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];
  for (let i = 0; i < 5; i++) {
    const d = new Date(friday);
    d.setDate(friday.getDate() - (4 - i));
    dates[dayNames[i]] = d.toISOString().slice(0, 10);
  }
  return dates;
}

async function findRobertSpreadsheets(auth) {
  const drive = google.drive({ version: 'v3', auth });
  const res = await drive.files.list({
    q: "name contains 'Robert_WE' and mimeType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'",
    orderBy: 'modifiedTime desc',
    pageSize: 5,
    fields: 'files(id,name,modifiedTime)',
  });
  return res.data.files || [];
}

async function parseRobertXlsx(auth, fileId, fileName) {
  const drive = google.drive({ version: 'v3', auth });
  const { execSync } = require('child_process');

  // Download the xlsx file
  const tmpPath = `/tmp/robert_${fileId}.xlsx`;
  const res = await drive.files.get(
    { fileId, alt: 'media' },
    { responseType: 'arraybuffer' },
  );
  fs.writeFileSync(tmpPath, Buffer.from(res.data));

  // Parse with Python/openpyxl — outputs JSON
  const pyScriptPath = `/tmp/parse_xlsx_${fileId}.py`;
  fs.writeFileSync(pyScriptPath, `
import openpyxl, json
wb = openpyxl.load_workbook("${tmpPath}")
result = {}
for sheet_name in wb.sheetnames:
    ws = wb[sheet_name]
    rows = []
    for row in ws.iter_rows(values_only=True):
        rows.append([str(c) if c is not None else "" for c in row])
    result[sheet_name] = rows
print(json.dumps(result))
`);
  const output = execSync(`python3 ${pyScriptPath}`, { encoding: 'utf-8', maxBuffer: 10 * 1024 * 1024 });
  fs.unlinkSync(pyScriptPath);
  const data = JSON.parse(output);

  // Derive week dates from filename as fallback
  const weekDates = getWeekDatesFromFilename(fileName || '');

  const results = [];
  for (const day of DAYS) {
    if (!data[day]) continue;
    const rows = data[day];

    // Find date from row 1
    let reportDate = null;
    if (rows[1] && rows[1][1]) {
      const dateStr = rows[1][1];
      const parts = dateStr.split('/');
      if (parts.length === 3) {
        const year = parts[2].length === 2 ? '20' + parts[2] : parts[2];
        reportDate = `${year}-${parts[0].padStart(2, '0')}-${parts[1].padStart(2, '0')}`;
      }
    }

    // Fallback: derive date from filename (Robert often leaves row 1 blank)
    if (!reportDate && weekDates && weekDates[day]) {
      reportDate = weekDates[day];
    }

    // Find header row
    let dataStartRow = -1;
    for (let i = 0; i < rows.length; i++) {
      if (rows[i] && rows[i][0] === 'Name' && rows[i][1] === 'Phone') {
        dataStartRow = i + 1;
        break;
      }
    }

    if (dataStartRow === -1 || !reportDate) continue;

    const prospects = [];
    let totalCalls = 0, contacts = 0, presentations = 0, scheduled = 0;

    for (let i = dataStartRow; i < rows.length; i++) {
      const row = rows[i];
      if (!row || !row[0] || !row[0].trim()) continue;
      const name = row[0].trim();
      if (name.startsWith('Calendar') || name.startsWith('Email Check') ||
          name.startsWith('Called') || name.startsWith('Updated') || name.startsWith('Followed')) continue;

      const phone = (row[1] || '').replace(/\.0$/, '');
      const email = row[3] || '';
      const licensed = row[4] || '';
      let statusCode = row[5] || '';
      const notes = row[6] || '';

      if (/^\d{1,2}:\d{2}$/.test(statusCode)) statusCode = '';
      const trimmedCode = statusCode.trim();
      const status = STATUS_MAP[trimmedCode] || STATUS_MAP[trimmedCode.toLowerCase()] || (trimmedCode ? trimmedCode.toLowerCase() : 'contacted');

      totalCalls++;
      if (status === 'presentation') presentations++;
      else if (status === 'scheduled') scheduled++;
      if (status !== 'attempted' && status !== 'not_eligible') contacts++;

      prospects.push({ name, phone: phone.replace(/[^\d]/g, ''), email, licensed, status, notes, recruiter: 'Robert Ramsey', date: reportDate });
    }

    if (prospects.length > 0) {
      results.push({
        prospects,
        metrics: { date: reportDate, recruiter: 'Robert Ramsey', dials: totalCalls, contacts, presentations, scheduled },
        date: reportDate,
      });
    }
  }

  // Cleanup
  fs.unlinkSync(tmpPath);
  return results;
}

async function parseContractingPipeline(sheets) {
  const res = await sheets.spreadsheets.values.get({
    spreadsheetId: CONTRACTING_SHEET_ID,
    range: 'Summary!A:Z',
  });
  const rows = res.data.values || [];
  const results = [];

  // Header is at row 2: #, Date, Name, First, Last, Manager, Status, ...cols..., Source
  for (let i = 3; i < rows.length; i++) {
    const row = rows[i];
    if (!row || !row[2]) continue;

    const dateStr = row[1] || '';
    // Parse date like "3/23" — assume current year
    let sentDate = null;
    const dateParts = dateStr.split('/');
    if (dateParts.length >= 2) {
      sentDate = `2026-${dateParts[0].padStart(2, '0')}-${dateParts[1].padStart(2, '0')}`;
    }

    results.push({
      name: (row[2] || '').trim(),
      firstName: (row[3] || '').trim(),
      lastName: (row[4] || '').trim(),
      manager: (row[5] || '').trim(),
      status: (row[6] || '').trim(),
      source: (row[15] || '').trim(),
      sentDate,
    });
  }

  // Also read Master List for the full pipeline with lead sources
  const masterRes = await sheets.spreadsheets.values.get({
    spreadsheetId: CONTRACTING_SHEET_ID,
    range: 'Master List!A:Z',
  });
  const masterRows = masterRes.data.values || [];
  const masterMap = {};

  for (let i = 1; i < masterRows.length; i++) {
    const row = masterRows[i];
    if (!row || !row[1]) continue;
    const name = (row[1] || '').trim();
    const dateStr = row[4] || '';
    let sentDate = null;
    const dateParts = dateStr.split('/');
    if (dateParts.length >= 2) {
      const yr = dateParts[2] && dateParts[2].length === 2 ? '20' + dateParts[2] : (dateParts[2] || '2026');
      sentDate = `${yr}-${dateParts[0].padStart(2, '0')}-${dateParts[1].padStart(2, '0')}`;
    }
    masterMap[name] = {
      source: (row[5] || '').trim(),
      manager: (row[6] || '').trim(),
      sentDate,
    };
  }

  // Merge master data into summary results (master has source for all entries)
  for (const r of results) {
    if (!r.source && masterMap[r.name]) {
      r.source = masterMap[r.name].source;
    }
    if (!r.sentDate && masterMap[r.name]) {
      r.sentDate = masterMap[r.name].sentDate;
    }
  }

  return results;
}

async function main() {
  const auth = await getAuth();
  const sheets = google.sheets({ version: 'v4', auth });
  const db = new Database(DB_PATH);

  const insertProspect = db.prepare(`
    INSERT OR REPLACE INTO prospects (name, email, phone, source, recruiter, status, first_contact_date, last_contact_date, notes, updated_at)
    VALUES (?, ?, ?, 'recruitment_call', ?, ?, ?, ?, ?, datetime('now'))
  `);

  const insertMetrics = db.prepare(`
    INSERT OR REPLACE INTO daily_metrics (date, recruiter, dials, contacts, appointments, interviews, contact_rate, appointment_rate)
    VALUES (?, ?, ?, ?, ?, 0, CAST(? AS REAL) / NULLIF(?, 0), CAST(? AS REAL) / NULLIF(?, 0))
  `);

  let totalProspects = 0;
  let totalDays = 0;

  // Parse Sandra's sheets
  console.log('📊 Parsing Sandra\'s Call Log...');
  for (const day of DAYS) {
    const result = await parseSheet(sheets, SANDRA_SHEET_ID, day, 'Sandra Futch');
    if (result.prospects.length > 0) {
      console.log(`  ${day} (${result.date}): ${result.prospects.length} prospects, ${result.metrics.dials} calls`);

      for (const p of result.prospects) {
        insertProspect.run(p.name, p.email, p.phone, p.recruiter, p.status, p.date, p.date, p.notes);
      }

      if (result.metrics) {
        insertMetrics.run(
          result.metrics.date, result.metrics.recruiter,
          result.metrics.dials, result.metrics.contacts,
          result.metrics.presentations + result.metrics.scheduled, // appointments
          result.metrics.contacts, result.metrics.dials, // contact_rate
          result.metrics.presentations + result.metrics.scheduled, result.metrics.contacts, // appointment_rate
        );
      }

      totalProspects += result.prospects.length;
      totalDays++;
    }
  }

  // Parse Robert's sheets
  console.log('\n📊 Parsing Robert\'s spreadsheets...');
  const robertFiles = await findRobertSpreadsheets(auth);

  for (const file of robertFiles.slice(0, 2)) { // Last 2 reports
    console.log(`  Processing: ${file.name}`);
    try {
      const results = await parseRobertXlsx(auth, file.id, file.name);
      for (const result of results) {
        console.log(`  ${result.date}: ${result.prospects.length} prospects, ${result.metrics?.dials || 0} calls`);

        for (const p of result.prospects) {
          insertProspect.run(p.name, p.email, p.phone, p.recruiter, p.status, p.date, p.date, p.notes);
        }

        if (result.metrics) {
          insertMetrics.run(
            result.metrics.date, result.metrics.recruiter,
            result.metrics.dials, result.metrics.contacts,
            result.metrics.presentations + result.metrics.scheduled,
            result.metrics.contacts, result.metrics.dials,
            result.metrics.presentations + result.metrics.scheduled, result.metrics.contacts,
          );
        }

        totalProspects += result.prospects.length;
        totalDays++;
      }
    } catch (e) {
      console.error(`  Error processing ${file.name}: ${e.message}`);
    }
  }

  // Parse Contracting Pipeline
  console.log('\n📊 Parsing Contracting Pipeline...');
  db.exec(`
    CREATE TABLE IF NOT EXISTS contracting_pipeline (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      name TEXT NOT NULL,
      first_name TEXT,
      last_name TEXT,
      manager TEXT,
      status TEXT DEFAULT 'for_follow_up',
      lead_source TEXT,
      sent_to_contracting_date TEXT,
      created_at TEXT DEFAULT (datetime('now')),
      updated_at TEXT DEFAULT (datetime('now')),
      UNIQUE(name, sent_to_contracting_date)
    );
    CREATE INDEX IF NOT EXISTS idx_cp_status ON contracting_pipeline(status);
    CREATE INDEX IF NOT EXISTS idx_cp_manager ON contracting_pipeline(manager);
  `);

  try {
    const pipeline = await parseContractingPipeline(sheets);
    const insertPipeline = db.prepare(`
      INSERT OR REPLACE INTO contracting_pipeline (name, first_name, last_name, manager, status, lead_source, sent_to_contracting_date, updated_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
    `);

    const statusMap = {
      'For Follow-up': 'for_follow_up',
      'On Process': 'on_process',
      'Contracted': 'contracted',
      'Not Interested': 'not_interested',
    };

    for (const p of pipeline) {
      insertPipeline.run(
        p.name, p.firstName, p.lastName, p.manager,
        statusMap[p.status] || p.status.toLowerCase().replace(/\s+/g, '_'),
        p.source || null, p.sentDate,
      );
    }

    const pipelineStats = {
      total: pipeline.length,
      byStatus: {},
      byManager: {},
    };
    for (const p of pipeline) {
      pipelineStats.byStatus[p.status] = (pipelineStats.byStatus[p.status] || 0) + 1;
      pipelineStats.byManager[p.manager] = (pipelineStats.byManager[p.manager] || 0) + 1;
    }

    console.log(`  Total in pipeline: ${pipelineStats.total}`);
    console.log('  By status:', Object.entries(pipelineStats.byStatus).map(([s,c]) => `${s}: ${c}`).join(', '));
    console.log('  By manager:', Object.entries(pipelineStats.byManager).sort((a,b) => b[1]-a[1]).map(([m,c]) => `${m}: ${c}`).join(', '));

    const contracted = pipeline.filter(p => p.status === 'Contracted').length;
    const convRate = ((contracted / pipeline.length) * 100).toFixed(1);
    console.log(`  Conversion rate: ${contracted}/${pipeline.length} = ${convRate}%`);
  } catch (e) {
    console.error('  Error parsing contracting pipeline:', e.message);
  }

  // Print summary
  const stats = {
    totalProspects: db.prepare('SELECT COUNT(*) as cnt FROM prospects').get().cnt,
    totalMetricDays: db.prepare('SELECT COUNT(*) as cnt FROM daily_metrics').get().cnt,
    byRecruiter: db.prepare('SELECT recruiter, COUNT(*) as cnt FROM prospects GROUP BY recruiter').all(),
    byStatus: db.prepare('SELECT status, COUNT(*) as cnt FROM prospects GROUP BY status ORDER BY cnt DESC').all(),
  };

  console.log('\n✅ Recruitment data stored!');
  console.log(`  Prospects: ${stats.totalProspects}`);
  console.log(`  Metric days: ${stats.totalMetricDays}`);
  console.log('  By recruiter:', stats.byRecruiter.map(r => `${r.recruiter}: ${r.cnt}`).join(', '));
  console.log('  By status:', stats.byStatus.map(s => `${s.status}: ${s.cnt}`).join(', '));

  db.close();
}

main().catch(e => {
  console.error('Fatal error:', e.message);
  process.exit(1);
});
