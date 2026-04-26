#!/usr/bin/env node

/**
 * Re-authorize Google OAuth with Sheets scope added
 * Keeps existing Gmail + Calendar scopes and adds Sheets read-only
 */

const { google } = require('googleapis');
const fs = require('fs');
const path = require('path');
const http = require('http');

const CRED_DIR = path.join(require('os').homedir(), '.gmail-mcp');
const KEYS_PATH = path.join(CRED_DIR, 'gcp-oauth.keys.json');
const TOKEN_PATH = path.join(CRED_DIR, 'credentials.json');

const SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.settings.basic',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/calendar.events',
    'https://www.googleapis.com/auth/spreadsheets.readonly',
    'https://www.googleapis.com/auth/drive.readonly',
];

async function main() {
    if (!fs.existsSync(KEYS_PATH)) {
        console.log('❌ OAuth keys not found at', KEYS_PATH);
        process.exit(1);
    }

    const keys = JSON.parse(fs.readFileSync(KEYS_PATH, 'utf-8'));
    const config = keys.installed || keys.web || keys;
    const { client_id, client_secret } = config;

    const redirectUri = 'http://localhost:3847';
    const oauth2Client = new google.auth.OAuth2(client_id, client_secret, redirectUri);

    const authUrl = oauth2Client.generateAuthUrl({
        access_type: 'offline',
        scope: SCOPES,
        prompt: 'consent',
    });

    console.log('\n📊 Adding Google Sheets access to NanoClaw\n');
    console.log('1. Open this URL in your browser:\n');
    console.log(authUrl);
    console.log('\n2. Sign in and grant access');
    console.log('3. You will be redirected back automatically\n');
    console.log('⏳ Waiting for authorization...\n');

    const server = http.createServer(async (req, res) => {
        const parsed = new URL(req.url, `http://localhost:3847`);
        const code = parsed.searchParams.get('code');
        if (!code) {
            res.writeHead(400);
            res.end('No code received');
            return;
        }

        try {
            const { tokens } = await oauth2Client.getToken(code);

            // Backup existing credentials
            if (fs.existsSync(TOKEN_PATH)) {
                fs.copyFileSync(TOKEN_PATH, TOKEN_PATH + '.backup');
            }

            fs.writeFileSync(TOKEN_PATH, JSON.stringify(tokens, null, 2));

            // Also update gws credentials if they exist
            const gwsCredDir = path.join(require('os').homedir(), '.config', 'gws');
            const gwsTokenPath = path.join(gwsCredDir, 'credentials.json');
            if (fs.existsSync(gwsTokenPath)) {
                const gwsCreds = JSON.parse(fs.readFileSync(gwsTokenPath, 'utf-8'));
                gwsCreds.refresh_token = tokens.refresh_token || gwsCreds.refresh_token;
                fs.writeFileSync(gwsTokenPath, JSON.stringify(gwsCreds, null, 2));
                console.log('✅ Also updated gws credentials');
            }

            res.writeHead(200, { 'Content-Type': 'text/html' });
            res.end('<h1>✅ Authorization successful!</h1><p>Google Sheets access granted. You can close this tab.</p>');

            console.log('✅ Credentials saved with Sheets + Drive scopes!');
            console.log('Scopes:', SCOPES.join(', '));

            server.close();
            process.exit(0);
        } catch (err) {
            res.writeHead(500);
            res.end('Error: ' + err.message);
            console.error('❌ Error:', err.message);
        }
    });

    server.listen(3847, () => {
        console.log('Listening on http://localhost:3847 for OAuth callback...');
    });
}

main().catch(console.error);
