#!/usr/bin/env node

/**
 * Re-authorize Google OAuth with Calendar scopes added
 * Keeps existing Gmail scopes and adds Calendar read/write
 */

const { google } = require('googleapis');
const fs = require('fs');
const path = require('path');
const http = require('http');
const url = require('url');

const CRED_DIR = path.join(require('os').homedir(), '.gmail-mcp');
const KEYS_PATH = path.join(CRED_DIR, 'gcp-oauth.keys.json');
const TOKEN_PATH = path.join(CRED_DIR, 'credentials.json');

const SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.settings.basic',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/calendar.events',
];

async function main() {
    if (!fs.existsSync(KEYS_PATH)) {
        console.log('❌ OAuth keys not found at', KEYS_PATH);
        process.exit(1);
    }

    const keys = JSON.parse(fs.readFileSync(KEYS_PATH, 'utf-8'));
    const config = keys.installed || keys.web || keys;
    const { client_id, client_secret, redirect_uris } = config;

    // Use localhost redirect for desktop OAuth (matches GCP config)
    const redirectUri = 'http://localhost:3847';
    const oauth2Client = new google.auth.OAuth2(client_id, client_secret, redirectUri);

    const authUrl = oauth2Client.generateAuthUrl({
        access_type: 'offline',
        scope: SCOPES,
        prompt: 'consent', // Force re-consent to get new refresh token with calendar scopes
    });

    console.log('\n📅 Adding Google Calendar access to NanoClaw\n');
    console.log('1. Open this URL in your browser:\n');
    console.log(authUrl);
    console.log('\n2. Sign in and grant Calendar access');
    console.log('3. You will be redirected back automatically\n');
    console.log('⏳ Waiting for authorization...\n');

    // Start local server to catch the callback
    const server = http.createServer(async (req, res) => {
        const query = url.parse(req.url, true).query;
        if (!query.code && !query.error) {
            res.writeHead(200);
            res.end('Waiting for authorization...');
            return;
        }
        if (query.code) {
            try {
                const { tokens } = await oauth2Client.getToken(query.code);

                // Back up existing credentials
                if (fs.existsSync(TOKEN_PATH)) {
                    fs.copyFileSync(TOKEN_PATH, TOKEN_PATH + '.backup');
                    console.log('📋 Backed up existing credentials to credentials.json.backup');
                }

                // Save new tokens
                fs.writeFileSync(TOKEN_PATH, JSON.stringify(tokens, null, 2));
                console.log('✅ Credentials updated with Calendar scopes!');
                console.log('📧 Gmail: ✅');
                console.log('📅 Calendar: ✅');
                console.log('\nScopes:', tokens.scope);

                res.writeHead(200, { 'Content-Type': 'text/html' });
                res.end('<html><body style="font-family:system-ui;text-align:center;padding:60px"><h1>✅ Calendar Access Granted!</h1><p>You can close this tab and return to Claude.</p></body></html>');

                setTimeout(() => {
                    server.close();
                    process.exit(0);
                }, 1000);
            } catch (err) {
                console.error('❌ Token exchange failed:', err.message);
                res.writeHead(500);
                res.end('Authorization failed: ' + err.message);
                server.close();
                process.exit(1);
            }
        } else if (query.error) {
            console.error('❌ Authorization denied:', query.error);
            res.writeHead(400);
            res.end('Authorization denied');
            server.close();
            process.exit(1);
        }
    });

    server.listen(3847, () => {
        console.log('🔗 Listening on http://localhost:3847 for OAuth callback...');
    });
}

main().catch(err => {
    console.error('❌ Error:', err.message);
    process.exit(1);
});
