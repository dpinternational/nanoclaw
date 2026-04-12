#!/usr/bin/env node

/**
 * EMAIL REACTION HANDLER
 * Processes David's Discord reactions to email triage messages
 * Executes actions immediately when David reacts with A, B, C, D, E, F
 */

const { spawn } = require('child_process');
const fs = require('fs').promises;
const path = require('path');

// Configuration
const DISCORD_CHANNELS = {
    TRIAGE: '1484839736609607832',
    LOGS: '1484840749924089996'
};

const DISCORD_BOT_TOKEN = process.env.DISCORD_BOT_TOKEN || '';
const PENDING_DECISIONS = path.join(__dirname, 'pending-decisions.json');

// Reaction mappings
const REACTION_ACTIONS = {
    '🅰️': 'archive',
    '🅱️': 'business_reply',
    '📅': 'add_to_calendar',
    '🗑️': 'delete_email',
    '📧': 'draft_reply',
    '📝': 'note_and_archive'
};

/**
 * Gmail MCP Tool Integration
 */
async function callGmailTool(toolName, args) {
    return new Promise((resolve, reject) => {
        const mcpRequest = {
            jsonrpc: "2.0", method: "tools/call", id: 1,
            params: { name: toolName, arguments: args }
        };

        const gmailServer = spawn('/usr/local/bin/npx', ['-y', '@gongrzhe/server-gmail-autoauth-mcp'], {
            stdio: ['pipe', 'pipe', 'pipe']
        });

        let output = '';
        gmailServer.stdout.on('data', (data) => output += data.toString());
        gmailServer.stdin.write(JSON.stringify(mcpRequest) + '\n');
        gmailServer.stdin.end();

        gmailServer.on('close', () => {
            try {
                const lines = output.trim().split('\n');
                resolve(JSON.parse(lines[lines.length - 1]));
            } catch (parseError) {
                reject(new Error(`Parse error: ${parseError.message}`));
            }
        });

        setTimeout(() => { gmailServer.kill(); reject(new Error('Timeout')); }, 20000);
    });
}

/**
 * Discord Integration
 */
async function sendDiscordMessage(channelId, message) {
    const https = require('https');

    const postData = JSON.stringify({
        content: message.substring(0, 1900)
    });

    const options = {
        hostname: 'discord.com',
        path: `/api/v10/channels/${channelId}/messages`,
        method: 'POST',
        headers: {
            'Authorization': `Bot ${DISCORD_BOT_TOKEN}`,
            'Content-Type': 'application/json',
            'Content-Length': Buffer.byteLength(postData)
        }
    };

    return new Promise((resolve, reject) => {
        const req = https.request(options, (res) => {
            let data = '';
            res.on('data', (chunk) => data += chunk);
            res.on('end', () => {
                if (res.statusCode === 200 || res.statusCode === 201) {
                    resolve({ success: true });
                } else {
                    reject(new Error(`HTTP ${res.statusCode}: ${data}`));
                }
            });
        });

        req.on('error', reject);
        req.write(postData);
        req.end();
    });
}

/**
 * Pending Decision Management
 */
async function loadPendingDecisions() {
    try {
        const data = await fs.readFile(PENDING_DECISIONS, 'utf8');
        return JSON.parse(data);
    } catch (error) {
        return {};
    }
}

async function savePendingDecisions(decisions) {
    try {
        await fs.writeFile(PENDING_DECISIONS, JSON.stringify(decisions, null, 2));
    } catch (error) {
        console.error('Failed to save pending decisions:', error.message);
    }
}

async function markDecisionCompleted(letterCode, action, result) {
    const decisions = await loadPendingDecisions();
    if (decisions[letterCode]) {
        decisions[letterCode].status = 'completed';
        decisions[letterCode].completedAction = action;
        decisions[letterCode].completedAt = new Date().toISOString();
        decisions[letterCode].result = result;
        await savePendingDecisions(decisions);
    }
}

/**
 * Email Action Handlers
 */
async function archiveEmail(email) {
    console.log(`📁 Archiving email: ${email.from} - ${email.subject}`);

    const result = await callGmailTool('modify_email', {
        messageId: email.id,
        removeLabelIds: ['INBOX']
    });

    if (result.result) {
        return { success: true, message: 'Email archived successfully' };
    } else {
        throw new Error('Archive operation failed');
    }
}

async function deleteEmail(email) {
    console.log(`🗑️ Deleting email: ${email.from} - ${email.subject}`);

    const result = await callGmailTool('delete_email', {
        messageId: email.id
    });

    if (result.result) {
        return { success: true, message: 'Email deleted permanently' };
    } else {
        throw new Error('Delete operation failed');
    }
}

async function createBusinessReply(email) {
    console.log(`💼 Creating business reply for: ${email.from} - ${email.subject}`);

    // Generate appropriate business response based on email content
    let replyTemplate = '';

    const subject = email.subject.toLowerCase();
    const from = email.from.toLowerCase();

    if (subject.includes('insurance') || subject.includes('quote')) {
        replyTemplate = generateInsuranceReplyTemplate(email);
    } else if (subject.includes('meeting') || subject.includes('appointment')) {
        replyTemplate = generateMeetingReplyTemplate(email);
    } else if (from.includes('tpglife') || from.includes('premiersmi')) {
        replyTemplate = generateInternalReplyTemplate(email);
    } else {
        replyTemplate = generateGenericBusinessReplyTemplate(email);
    }

    // Create draft email
    const draftResult = await callGmailTool('draft_email', {
        to: email.from,
        subject: `Re: ${email.subject}`,
        body: replyTemplate
    });

    if (draftResult.result) {
        // Also archive original email
        await archiveEmail(email);
        return {
            success: true,
            message: 'Business reply drafted and original email archived',
            draftId: draftResult.result.id
        };
    } else {
        throw new Error('Failed to create business reply draft');
    }
}

async function addToCalendar(email) {
    console.log(`📅 Adding to calendar/tasks: ${email.from} - ${email.subject}`);

    // Create a task/reminder in the system
    const taskData = {
        title: `Follow up: ${email.subject}`,
        description: `Email from ${email.from}`,
        emailId: email.id,
        dueDate: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString(), // Tomorrow
        priority: 'medium',
        created: new Date().toISOString()
    };

    // Save to tasks file
    try {
        const tasksFile = path.join(__dirname, 'email-tasks.json');
        let tasks = [];
        try {
            const data = await fs.readFile(tasksFile, 'utf8');
            tasks = JSON.parse(data);
        } catch (error) {
            // File doesn't exist yet
        }

        tasks.push(taskData);
        await fs.writeFile(tasksFile, JSON.stringify(tasks, null, 2));

        // Archive original email
        await archiveEmail(email);

        return {
            success: true,
            message: 'Task created and email archived',
            taskId: taskData.created
        };
    } catch (error) {
        throw new Error(`Failed to create task: ${error.message}`);
    }
}

async function draftReply(email) {
    console.log(`📧 Drafting reply for: ${email.from} - ${email.subject}`);

    // Create a simple acknowledgment draft
    const replyBody = `Hi,

Thank you for your email. I'll review this and get back to you soon.

Best regards,
David Price
Insurance Industry Leader
davidprice@tpglife.com`;

    const draftResult = await callGmailTool('draft_email', {
        to: email.from,
        subject: `Re: ${email.subject}`,
        body: replyBody
    });

    if (draftResult.result) {
        return {
            success: true,
            message: 'Reply draft created (ready for editing)',
            draftId: draftResult.result.id
        };
    } else {
        throw new Error('Failed to create reply draft');
    }
}

async function noteAndArchive(email) {
    console.log(`📝 Adding note and archiving: ${email.from} - ${email.subject}`);

    // Create note entry
    const noteData = {
        timestamp: new Date().toISOString(),
        from: email.from,
        subject: email.subject,
        emailId: email.id,
        note: 'Reviewed and noted - no immediate action required'
    };

    try {
        const notesFile = path.join(__dirname, 'email-notes.json');
        let notes = [];
        try {
            const data = await fs.readFile(notesFile, 'utf8');
            notes = JSON.parse(data);
        } catch (error) {
            // File doesn't exist yet
        }

        notes.push(noteData);
        await fs.writeFile(notesFile, JSON.stringify(notes, null, 2));

        // Archive email
        await archiveEmail(email);

        return {
            success: true,
            message: 'Note added and email archived',
            noteId: noteData.timestamp
        };
    } catch (error) {
        throw new Error(`Failed to create note: ${error.message}`);
    }
}

/**
 * Email Template Generators
 */
function generateInsuranceReplyTemplate(email) {
    return `Hi there,

Thank you for reaching out about insurance. I'd be happy to help you explore your options.

To provide you with the most accurate information, I'd like to schedule a brief consultation where we can discuss:
- Your current insurance needs
- Available product options that fit your situation
- Pricing and coverage details

You can book a convenient time here: [calendar link]

Looking forward to helping you find the right coverage.

Best regards,
David Price
Insurance Industry Leader
davidprice@tpglife.com`;
}

function generateMeetingReplyTemplate(email) {
    return `Hi,

Thank you for the meeting invitation/request.

I'll review my calendar and confirm availability. If you need to reschedule or have any specific agenda items, please let me know.

Best regards,
David Price
davidprice@tpglife.com`;
}

function generateInternalReplyTemplate(email) {
    return `Thanks for the update.

I'll review this and follow up as needed.

Best,
David`;
}

function generateGenericBusinessReplyTemplate(email) {
    return `Hi,

Thank you for your message. I've received your email and will review it shortly.

If this is time-sensitive, please feel free to call me directly.

Best regards,
David Price
Insurance Industry Leader
davidprice@tpglife.com`;
}

/**
 * Main Reaction Handler
 */
async function handleEmailReaction(messageContent, reaction, userId) {
    try {
        // Extract letter code from message
        const letterMatch = messageContent.match(/EMAIL ([A-Z])/);
        if (!letterMatch) {
            console.log('No email letter code found in message');
            return;
        }

        const letterCode = letterMatch[1];
        console.log(`📧 Processing reaction ${reaction} for EMAIL ${letterCode}`);

        // Load pending decisions
        const decisions = await loadPendingDecisions();
        const decision = decisions[letterCode];

        if (!decision || decision.status !== 'pending') {
            console.log(`No pending decision found for EMAIL ${letterCode}`);
            return;
        }

        const email = decision.email;
        const action = REACTION_ACTIONS[reaction];

        if (!action) {
            console.log(`Unknown reaction: ${reaction}`);
            return;
        }

        // Execute the action
        let result;
        switch (action) {
            case 'archive':
                result = await archiveEmail(email);
                break;

            case 'business_reply':
                result = await createBusinessReply(email);
                break;

            case 'add_to_calendar':
                result = await addToCalendar(email);
                break;

            case 'delete_email':
                result = await deleteEmail(email);
                break;

            case 'draft_reply':
                result = await draftReply(email);
                break;

            case 'note_and_archive':
                result = await noteAndArchive(email);
                break;

            default:
                throw new Error(`Unknown action: ${action}`);
        }

        // Mark decision as completed
        await markDecisionCompleted(letterCode, action, result);

        // Send confirmation
        const confirmationMessage = `✅ **EMAIL ${letterCode} PROCESSED**

**Action:** ${action.replace('_', ' ').toUpperCase()}
**Email:** ${email.from} - ${email.subject.substring(0, 40)}...
**Result:** ${result.message}

🎯 Email removed from your inbox and handled automatically.`;

        await sendDiscordMessage(DISCORD_CHANNELS.TRIAGE, confirmationMessage);

        console.log(`✅ Successfully processed EMAIL ${letterCode} with action: ${action}`);

    } catch (error) {
        console.error(`❌ Failed to process reaction: ${error.message}`);

        await sendDiscordMessage(DISCORD_CHANNELS.LOGS,
            `❌ **Email Reaction Error**\nFailed to process reaction ${reaction}: ${error.message}`);
    }
}

/**
 * Monitor for message reactions (this would integrate with Discord bot)
 */
async function startReactionMonitoring() {
    console.log('👂 Email reaction handler ready');
    console.log('Waiting for Discord reactions to email triage messages...');

    // This function would be called by the Discord bot when reactions are detected
    // For now, it's exported for integration with the main Discord bot
}

/**
 * Export functions for integration
 */
module.exports = {
    handleEmailReaction,
    REACTION_ACTIONS,
    archiveEmail,
    createBusinessReply,
    addToCalendar,
    deleteEmail,
    draftReply,
    noteAndArchive
};

if (require.main === module) {
    startReactionMonitoring();
}
