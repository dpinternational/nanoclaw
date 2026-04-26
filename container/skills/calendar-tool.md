# Google Calendar Tool

You have access to Google Calendar through the credentials at `~/.gmail-mcp/`. Use the following Node.js approach to interact with the calendar.

## Creating Events

```bash
node -e "
const { google } = require('googleapis');
const fs = require('fs');
const path = require('path');
const credDir = path.join(require('os').homedir(), '.gmail-mcp');
const keys = JSON.parse(fs.readFileSync(path.join(credDir, 'gcp-oauth.keys.json'), 'utf-8'));
const tokens = JSON.parse(fs.readFileSync(path.join(credDir, 'credentials.json'), 'utf-8'));
const config = keys.installed || keys.web || keys;
const auth = new google.auth.OAuth2(config.client_id, config.client_secret, config.redirect_uris?.[0]);
auth.setCredentials(tokens);
auth.on('tokens', (t) => { const c = JSON.parse(fs.readFileSync(path.join(credDir, 'credentials.json'), 'utf-8')); Object.assign(c, t); fs.writeFileSync(path.join(credDir, 'credentials.json'), JSON.stringify(c, null, 2)); });
const cal = google.calendar({ version: 'v3', auth });
cal.events.insert({ calendarId: 'primary', requestBody: {
  summary: 'EVENT TITLE HERE',
  description: 'DESCRIPTION HERE',
  start: { dateTime: '2026-04-01T10:00:00', timeZone: 'America/New_York' },
  end: { dateTime: '2026-04-01T10:30:00', timeZone: 'America/New_York' },
}}).then(r => console.log('✅ Event created:', r.data.htmlLink)).catch(e => console.error('❌', e.message));
"
```

## Listing Events

```bash
node -e "
const { google } = require('googleapis');
const fs = require('fs');
const path = require('path');
const credDir = path.join(require('os').homedir(), '.gmail-mcp');
const keys = JSON.parse(fs.readFileSync(path.join(credDir, 'gcp-oauth.keys.json'), 'utf-8'));
const tokens = JSON.parse(fs.readFileSync(path.join(credDir, 'credentials.json'), 'utf-8'));
const config = keys.installed || keys.web || keys;
const auth = new google.auth.OAuth2(config.client_id, config.client_secret, config.redirect_uris?.[0]);
auth.setCredentials(tokens);
auth.on('tokens', (t) => { const c = JSON.parse(fs.readFileSync(path.join(credDir, 'credentials.json'), 'utf-8')); Object.assign(c, t); fs.writeFileSync(path.join(credDir, 'credentials.json'), JSON.stringify(c, null, 2)); });
const cal = google.calendar({ version: 'v3', auth });
const now = new Date();
const until = new Date(now.getTime() + DAYS * 24 * 60 * 60 * 1000);
cal.events.list({ calendarId: 'primary', timeMin: now.toISOString(), timeMax: until.toISOString(), singleEvents: true, orderBy: 'startTime', maxResults: 20 })
.then(r => { (r.data.items || []).forEach(e => { const t = new Date(e.start.dateTime || e.start.date).toLocaleString('en-US', { timeZone: 'America/New_York', weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }); console.log(t + ' — ' + e.summary); }); })
.catch(e => console.error('❌', e.message));
"
```

Replace `DAYS` with the number of days to look ahead (e.g., 1, 7).

## Important Notes
- Always use `America/New_York` timezone
- Credentials are at `~/.gmail-mcp/` (shared with Gmail)
- Token refresh is handled automatically
- Use ISO datetime format for start/end times
