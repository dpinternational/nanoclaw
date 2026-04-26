import fs from 'fs';
import os from 'os';
import path from 'path';

import { google, calendar_v3 } from 'googleapis';
import { OAuth2Client } from 'google-auth-library';

import { logger } from '../logger.js';
import { registerChannel, ChannelOpts } from './registry.js';
import {
  Channel,
  OnChatMetadata,
  OnInboundMessage,
  RegisteredGroup,
} from '../types.js';

export interface CalendarChannelOpts {
  onMessage: OnInboundMessage;
  onChatMetadata: OnChatMetadata;
  registeredGroups: () => Record<string, RegisteredGroup>;
}

export class GoogleCalendarChannel implements Channel {
  name = 'google-calendar';

  private oauth2Client: OAuth2Client | null = null;
  private calendar: calendar_v3.Calendar | null = null;
  private opts: CalendarChannelOpts;
  private pollIntervalMs: number;
  private pollTimer: ReturnType<typeof setTimeout> | null = null;
  private notifiedEvents = new Set<string>();
  private consecutiveErrors = 0;

  constructor(opts: CalendarChannelOpts, pollIntervalMs = 5 * 60 * 1000) {
    this.opts = opts;
    this.pollIntervalMs = pollIntervalMs;
  }

  async connect(): Promise<void> {
    const credDir = path.join(os.homedir(), '.gmail-mcp');
    const keysPath = path.join(credDir, 'gcp-oauth.keys.json');
    const tokensPath = path.join(credDir, 'credentials.json');

    if (!fs.existsSync(keysPath) || !fs.existsSync(tokensPath)) {
      logger.warn(
        'Google Calendar credentials not found in ~/.gmail-mcp/. Skipping.',
      );
      return;
    }

    const keys = JSON.parse(fs.readFileSync(keysPath, 'utf-8'));
    const tokens = JSON.parse(fs.readFileSync(tokensPath, 'utf-8'));

    // Check that calendar scopes are present
    const scopes = tokens.scope || '';
    if (!scopes.includes('calendar')) {
      logger.warn(
        'Google Calendar scopes not authorized. Run scripts/add-calendar-scope.cjs',
      );
      return;
    }

    const clientConfig = keys.installed || keys.web || keys;
    const { client_id, client_secret, redirect_uris } = clientConfig;
    this.oauth2Client = new google.auth.OAuth2(
      client_id,
      client_secret,
      redirect_uris?.[0],
    );
    this.oauth2Client.setCredentials(tokens);

    // Persist refreshed tokens
    this.oauth2Client.on('tokens', (newTokens) => {
      try {
        const current = JSON.parse(fs.readFileSync(tokensPath, 'utf-8'));
        Object.assign(current, newTokens);
        fs.writeFileSync(tokensPath, JSON.stringify(current, null, 2));
        logger.debug('Calendar OAuth tokens refreshed');
      } catch (err) {
        logger.warn({ err }, 'Failed to persist refreshed Calendar tokens');
      }
    });

    this.calendar = google.calendar({ version: 'v3', auth: this.oauth2Client });

    // Verify connection
    try {
      const calList = await this.calendar.calendarList.list({ maxResults: 1 });
      const primaryCal = calList.data.items?.find((c) => c.primary);
      logger.info(
        { calendar: primaryCal?.summary || 'primary' },
        'Google Calendar channel connected',
      );
    } catch (err) {
      logger.error({ err }, 'Failed to connect Google Calendar');
      this.calendar = null;
      return;
    }

    // Start polling for upcoming events
    const schedulePoll = () => {
      const backoffMs =
        this.consecutiveErrors > 0
          ? Math.min(
              this.pollIntervalMs * Math.pow(2, this.consecutiveErrors),
              30 * 60 * 1000,
            )
          : this.pollIntervalMs;
      this.pollTimer = setTimeout(() => {
        this.pollUpcomingEvents()
          .catch((err) => logger.error({ err }, 'Calendar poll error'))
          .finally(() => {
            if (this.calendar) schedulePoll();
          });
      }, backoffMs);
    };

    // Initial poll
    await this.pollUpcomingEvents();
    schedulePoll();
  }

  async sendMessage(jid: string, text: string): Promise<void> {
    if (!this.calendar) {
      logger.warn('Google Calendar not initialized');
      return;
    }

    // Parse calendar commands from agent responses
    const cmd = this.parseCalendarCommand(text);
    if (!cmd) {
      logger.debug({ jid }, 'Calendar: no actionable command in message');
      return;
    }

    try {
      if (cmd.action === 'create') {
        const event = await this.calendar.events.insert({
          calendarId: 'primary',
          requestBody: {
            summary: cmd.summary,
            description: cmd.description,
            start: {
              dateTime: cmd.startTime,
              timeZone: 'America/New_York',
            },
            end: {
              dateTime: cmd.endTime,
              timeZone: 'America/New_York',
            },
            ...(cmd.attendees?.length
              ? { attendees: cmd.attendees.map((e: string) => ({ email: e })) }
              : {}),
          },
        });
        logger.info(
          { eventId: event.data.id, summary: cmd.summary },
          'Calendar event created',
        );
      } else if (cmd.action === 'list') {
        // Agent requested event list — deliver as inbound message
        const events = await this.getUpcomingEvents(
          cmd.days || 1,
          cmd.maxResults || 10,
        );
        const summary = this.formatEventList(events, cmd.days || 1);
        const mainJid = this.getMainJid();
        if (mainJid) {
          this.opts.onMessage(mainJid, {
            id: `cal-list-${Date.now()}`,
            chat_jid: mainJid,
            sender: 'google-calendar',
            sender_name: 'Google Calendar',
            content: summary,
            timestamp: new Date().toISOString(),
            is_from_me: false,
          });
        }
      }
    } catch (err) {
      logger.error({ err, cmd }, 'Calendar command failed');
    }
  }

  isConnected(): boolean {
    return this.calendar !== null;
  }

  ownsJid(jid: string): boolean {
    return jid.startsWith('calendar:');
  }

  async disconnect(): Promise<void> {
    if (this.pollTimer) {
      clearTimeout(this.pollTimer);
      this.pollTimer = null;
    }
    this.calendar = null;
    this.oauth2Client = null;
    logger.info('Google Calendar channel stopped');
  }

  // --- Public API for direct use ---

  async listEvents(
    days = 1,
    maxResults = 10,
  ): Promise<calendar_v3.Schema$Event[]> {
    return this.getUpcomingEvents(days, maxResults);
  }

  async createEvent(opts: {
    summary: string;
    startTime: string;
    endTime: string;
    description?: string;
    attendees?: string[];
  }): Promise<calendar_v3.Schema$Event | null> {
    if (!this.calendar) return null;

    const event = await this.calendar.events.insert({
      calendarId: 'primary',
      requestBody: {
        summary: opts.summary,
        description: opts.description,
        start: { dateTime: opts.startTime, timeZone: 'America/New_York' },
        end: { dateTime: opts.endTime, timeZone: 'America/New_York' },
        ...(opts.attendees?.length
          ? { attendees: opts.attendees.map((e) => ({ email: e })) }
          : {}),
      },
    });
    return event.data;
  }

  // --- Private ---

  private async getUpcomingEvents(
    days: number,
    maxResults: number,
  ): Promise<calendar_v3.Schema$Event[]> {
    if (!this.calendar) return [];

    const now = new Date();
    const until = new Date(now.getTime() + days * 24 * 60 * 60 * 1000);

    const res = await this.calendar.events.list({
      calendarId: 'primary',
      timeMin: now.toISOString(),
      timeMax: until.toISOString(),
      maxResults,
      singleEvents: true,
      orderBy: 'startTime',
    });

    return res.data.items || [];
  }

  private async pollUpcomingEvents(): Promise<void> {
    if (!this.calendar) return;

    try {
      // Look 15 minutes ahead for event reminders
      const now = new Date();
      const soon = new Date(now.getTime() + 15 * 60 * 1000);

      const res = await this.calendar.events.list({
        calendarId: 'primary',
        timeMin: now.toISOString(),
        timeMax: soon.toISOString(),
        singleEvents: true,
        orderBy: 'startTime',
      });

      const events = res.data.items || [];

      for (const event of events) {
        if (!event.id || this.notifiedEvents.has(event.id)) continue;

        const startTime = event.start?.dateTime || event.start?.date;
        if (!startTime) continue;

        const startMs = new Date(startTime).getTime();
        const minsUntil = Math.round((startMs - now.getTime()) / 60000);

        // Only notify for events 5-15 minutes away
        if (minsUntil > 15 || minsUntil < 0) continue;

        this.notifiedEvents.add(event.id);

        const mainJid = this.getMainJid();
        if (!mainJid) continue;

        const timeStr = new Date(startTime).toLocaleTimeString('en-US', {
          timeZone: 'America/New_York',
          hour: 'numeric',
          minute: '2-digit',
        });

        let content = `[Calendar Reminder] "${event.summary}" starts in ${minsUntil} minutes (${timeStr} ET)`;
        if (event.hangoutLink) {
          content += `\nMeeting link: ${event.hangoutLink}`;
        }
        if (event.location) {
          content += `\nLocation: ${event.location}`;
        }
        if (event.attendees?.length) {
          const names = event.attendees
            .filter((a) => !a.self)
            .map((a) => a.displayName || a.email)
            .slice(0, 5);
          if (names.length > 0) {
            content += `\nWith: ${names.join(', ')}`;
          }
        }

        this.opts.onChatMetadata(
          `calendar:${event.id}`,
          new Date().toISOString(),
          event.summary || 'Calendar Event',
          'google-calendar',
          false,
        );

        this.opts.onMessage(mainJid, {
          id: `cal-${event.id}-${Date.now()}`,
          chat_jid: mainJid,
          sender: 'google-calendar',
          sender_name: 'Google Calendar',
          content,
          timestamp: new Date().toISOString(),
          is_from_me: false,
        });

        logger.info(
          { event: event.summary, minsUntil },
          'Calendar reminder sent',
        );
      }

      // Clean up old notified events (keep last 200)
      if (this.notifiedEvents.size > 200) {
        const ids = [...this.notifiedEvents];
        this.notifiedEvents = new Set(ids.slice(ids.length - 100));
      }

      this.consecutiveErrors = 0;
    } catch (err) {
      this.consecutiveErrors++;
      logger.error(
        { err, consecutiveErrors: this.consecutiveErrors },
        'Calendar poll failed',
      );
    }
  }

  private getMainJid(): string | null {
    const groups = this.opts.registeredGroups();
    const mainEntry = Object.entries(groups).find(([, g]) => g.isMain === true);
    return mainEntry ? mainEntry[0] : null;
  }

  private formatEventList(
    events: calendar_v3.Schema$Event[],
    days: number,
  ): string {
    if (events.length === 0) {
      return `[Calendar] No events in the next ${days} day${days > 1 ? 's' : ''}.`;
    }

    let result = `[Calendar] Upcoming events (next ${days} day${days > 1 ? 's' : ''}):\n\n`;

    let currentDate = '';
    for (const event of events) {
      const startTime = event.start?.dateTime || event.start?.date || '';
      const date = new Date(startTime);
      const dateStr = date.toLocaleDateString('en-US', {
        timeZone: 'America/New_York',
        weekday: 'short',
        month: 'short',
        day: 'numeric',
      });

      if (dateStr !== currentDate) {
        currentDate = dateStr;
        result += `${dateStr}:\n`;
      }

      if (event.start?.dateTime) {
        const time = date.toLocaleTimeString('en-US', {
          timeZone: 'America/New_York',
          hour: 'numeric',
          minute: '2-digit',
        });
        result += `  ${time} — ${event.summary || '(no title)'}`;
      } else {
        // All-day event
        result += `  All day — ${event.summary || '(no title)'}`;
      }

      if (event.location) result += ` (${event.location})`;
      result += '\n';
    }

    return result;
  }

  private parseCalendarCommand(text: string): {
    action: string;
    summary?: string;
    description?: string;
    startTime?: string;
    endTime?: string;
    attendees?: string[];
    days?: number;
    maxResults?: number;
  } | null {
    // Try to parse JSON calendar commands from agent output
    // Format: [CALENDAR:CREATE] { ... } or [CALENDAR:LIST] { ... }
    const createMatch = text.match(/\[CALENDAR:CREATE\]\s*(\{[\s\S]*?\})/i);
    if (createMatch) {
      try {
        const data = JSON.parse(createMatch[1]);
        return { action: 'create', ...data };
      } catch {
        return null;
      }
    }

    const listMatch = text.match(/\[CALENDAR:LIST\]\s*(\{[\s\S]*?\})?/i);
    if (listMatch) {
      try {
        const data = listMatch[1] ? JSON.parse(listMatch[1]) : {};
        return {
          action: 'list',
          days: data.days || 1,
          maxResults: data.maxResults || 10,
        };
      } catch {
        return { action: 'list', days: 1, maxResults: 10 };
      }
    }

    return null;
  }
}

registerChannel('google-calendar', (opts: ChannelOpts) => {
  const credDir = path.join(os.homedir(), '.gmail-mcp');
  if (
    !fs.existsSync(path.join(credDir, 'gcp-oauth.keys.json')) ||
    !fs.existsSync(path.join(credDir, 'credentials.json'))
  ) {
    logger.warn('Google Calendar: credentials not found in ~/.gmail-mcp/');
    return null;
  }

  // Check for calendar scopes before initializing
  try {
    const tokens = JSON.parse(
      fs.readFileSync(path.join(credDir, 'credentials.json'), 'utf-8'),
    );
    if (!tokens.scope?.includes('calendar')) {
      logger.info('Google Calendar: calendar scopes not authorized, skipping');
      return null;
    }
  } catch {
    return null;
  }

  return new GoogleCalendarChannel(opts);
});
