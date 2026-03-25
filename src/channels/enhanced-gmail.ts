/**
 * ENHANCED GMAIL CHANNEL WITH EMAIL CLASSIFICATION
 * Integrates with the new email classification engine and Discord routing system
 */

import fs from 'fs';
import os from 'os';
import path from 'path';

import { google, gmail_v1 } from 'googleapis';
import { OAuth2Client } from 'google-auth-library';

import { logger } from '../logger.js';
import { registerChannel, ChannelOpts } from './registry.js';
import {
  Channel,
  OnChatMetadata,
  OnInboundMessage,
  RegisteredGroup,
} from '../types.js';
import {
  EmailClassificationEngine,
  EmailMetadata,
  ClassificationResult,
  EmailCategory,
  Priority,
  UrgencyLevel,
  EmailAction
} from '../email-classifier.js';
import { DiscordEmailRouter, DiscordMessage } from '../discord-email-router.js';

export interface EnhancedGmailChannelOpts {
  onMessage: OnInboundMessage;
  onChatMetadata: OnChatMetadata;
  registeredGroups: () => Record<string, RegisteredGroup>;
  onDiscordMessage?: (message: DiscordMessage) => Promise<void>;
}

interface ThreadMeta {
  sender: string;
  senderName: string;
  subject: string;
  messageId: string;
  classification?: ClassificationResult;
}

export class EnhancedGmailChannel implements Channel {
  name = 'enhanced-gmail';

  private oauth2Client: OAuth2Client | null = null;
  private gmail: gmail_v1.Gmail | null = null;
  private opts: EnhancedGmailChannelOpts;
  private pollIntervalMs: number;
  private pollTimer: ReturnType<typeof setTimeout> | null = null;
  private processedIds = new Set<string>();
  private threadMeta = new Map<string, ThreadMeta>();
  private consecutiveErrors = 0;
  private userEmail = '';

  // Enhanced features
  private classifier: EmailClassificationEngine;
  private discordRouter: DiscordEmailRouter;
  private processingStats = {
    totalProcessed: 0,
    autoArchived: 0,
    escalated: 0,
    discordRouted: 0,
    lastReset: new Date()
  };

  constructor(opts: EnhancedGmailChannelOpts, pollIntervalMs = 60000) {
    this.opts = opts;
    this.pollIntervalMs = pollIntervalMs;
    this.classifier = new EmailClassificationEngine();
    this.discordRouter = new DiscordEmailRouter();
  }

  async connect(): Promise<void> {
    const credDir = path.join(os.homedir(), '.gmail-mcp');
    const keysPath = path.join(credDir, 'gcp-oauth.keys.json');
    const tokensPath = path.join(credDir, 'credentials.json');

    if (!fs.existsSync(keysPath) || !fs.existsSync(tokensPath)) {
      logger.warn(
        'Gmail credentials not found in ~/.gmail-mcp/. Skipping Enhanced Gmail channel. Run /add-gmail to set up.',
      );
      return;
    }

    const keys = JSON.parse(fs.readFileSync(keysPath, 'utf-8'));
    const tokens = JSON.parse(fs.readFileSync(tokensPath, 'utf-8'));

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
        logger.debug('Enhanced Gmail OAuth tokens refreshed');
      } catch (err) {
        logger.warn({ err }, 'Failed to persist refreshed Enhanced Gmail tokens');
      }
    });

    this.gmail = google.gmail({ version: 'v1', auth: this.oauth2Client });

    // Verify connection
    const profile = await this.gmail.users.getProfile({ userId: 'me' });
    this.userEmail = profile.data.emailAddress || '';
    logger.info({ email: this.userEmail }, 'Enhanced Gmail channel connected');

    // Start enhanced polling with classification
    const schedulePoll = () => {
      const backoffMs =
        this.consecutiveErrors > 0
          ? Math.min(
              this.pollIntervalMs * Math.pow(2, this.consecutiveErrors),
              30 * 60 * 1000,
            )
          : this.pollIntervalMs;
      this.pollTimer = setTimeout(() => {
        this.enhancedPollForMessages()
          .catch((err) => logger.error({ err }, 'Enhanced Gmail poll error'))
          .finally(() => {
            if (this.gmail) schedulePoll();
          });
      }, backoffMs);
    };

    // Initial poll
    await this.enhancedPollForMessages();
    schedulePoll();
  }

  /**
   * Enhanced polling with email classification and routing
   */
  private async enhancedPollForMessages(): Promise<void> {
    if (!this.gmail) return;

    try {
      const query = this.buildQuery();
      const res = await this.gmail.users.messages.list({
        userId: 'me',
        q: query,
        maxResults: 25, // Increased for better processing
      });

      const messages = res.data.messages || [];
      logger.debug({ messageCount: messages.length }, 'Enhanced Gmail polling results');

      for (const stub of messages) {
        if (!stub.id || this.processedIds.has(stub.id)) continue;
        this.processedIds.add(stub.id);

        await this.processEnhancedMessage(stub.id);
      }

      // Cap processed ID set to prevent unbounded growth
      if (this.processedIds.size > 5000) {
        const ids = [...this.processedIds];
        this.processedIds = new Set(ids.slice(ids.length - 2500));
      }

      this.consecutiveErrors = 0;

      // Send periodic stats update
      await this.sendStatsUpdateIfNeeded();

    } catch (err) {
      this.consecutiveErrors++;
      const backoffMs = Math.min(
        this.pollIntervalMs * Math.pow(2, this.consecutiveErrors),
        30 * 60 * 1000,
      );
      logger.error(
        {
          err,
          consecutiveErrors: this.consecutiveErrors,
          nextPollMs: backoffMs,
        },
        'Enhanced Gmail poll failed',
      );
    }
  }

  /**
   * Process individual message with full classification and routing
   */
  private async processEnhancedMessage(messageId: string): Promise<void> {
    if (!this.gmail) return;

    try {
      const msg = await this.gmail.users.messages.get({
        userId: 'me',
        id: messageId,
        format: 'full',
      });

      const headers = msg.data.payload?.headers || [];
      const getHeader = (name: string) =>
        headers.find((h) => h.name?.toLowerCase() === name.toLowerCase())
          ?.value || '';

      const from = getHeader('From');
      const subject = getHeader('Subject');
      const rfc2822MessageId = getHeader('Message-ID');
      const threadId = msg.data.threadId || messageId;
      const timestamp = new Date(
        parseInt(msg.data.internalDate || '0', 10),
      ).toISOString();

      // Extract sender name and email
      const senderMatch = from.match(/^(.+?)\s*<(.+?)>$/);
      const senderName = senderMatch ? senderMatch[1].replace(/"/g, '') : from;
      const senderEmail = senderMatch ? senderMatch[2] : from;

      // Skip emails from self
      if (senderEmail === this.userEmail) return;

      // Extract body text
      const body = this.extractTextBody(msg.data.payload);

      if (!body && !subject) {
        logger.debug({ messageId, subject }, 'Skipping email with no content');
        return;
      }

      // Create email metadata for classification
      const emailMetadata: EmailMetadata = {
        from: senderEmail,
        fromName: senderName,
        subject,
        content: body,
        timestamp,
        id: messageId,
        threadId,
        labels: msg.data.labelIds || []
      };

      // Classify the email
      const classification = await this.classifier.classifyEmail(emailMetadata);

      // Handle the classified email
      await this.handleClassifiedEmail(emailMetadata, classification);

      this.processingStats.totalProcessed++;

      logger.info(
        {
          messageId,
          from: senderName,
          subject,
          category: classification.category,
          priority: classification.priority,
          action: classification.action
        },
        'Enhanced Gmail email processed and classified',
      );

    } catch (error) {
      logger.error({ messageId, error }, 'Failed to process enhanced email');
    }
  }

  /**
   * Handle classified email based on determined action
   */
  private async handleClassifiedEmail(email: EmailMetadata, classification: ClassificationResult): Promise<void> {
    // Cache thread metadata
    if (email.threadId) {
      this.threadMeta.set(email.threadId, {
        sender: email.from,
        senderName: email.fromName || email.from,
        subject: email.subject,
        messageId: email.id,
        classification
      });
    }

    // Route to Discord if not auto-archived/spam
    if (classification.action !== EmailAction.AUTO_ARCHIVE &&
        classification.action !== EmailAction.SPAM_FILTER) {
      await this.routeToDiscord(email, classification);
    }

    // Handle auto-actions
    await this.executeAutoActions(email, classification);

    // Send to main group if needed for traditional processing
    if (this.shouldSendToMainGroup(classification)) {
      await this.sendToMainGroup(email, classification);
    }

    // Store chat metadata for discovery
    const chatJid = `gmail:${email.threadId || email.id}`;
    this.opts.onChatMetadata(chatJid, email.timestamp, email.subject, 'enhanced-gmail', false);
  }

  /**
   * Route email to Discord based on classification
   */
  private async routeToDiscord(email: EmailMetadata, classification: ClassificationResult): Promise<void> {
    try {
      const discordMessage = await this.discordRouter.routeEmail(email, classification);

      // Send to Discord via callback if provided
      if (this.opts.onDiscordMessage) {
        await this.opts.onDiscordMessage(discordMessage);
      }

      this.processingStats.discordRouted++;

      logger.info({
        emailId: email.id,
        discordChannel: discordMessage.channelId,
        category: classification.category
      }, 'Email routed to Discord');

    } catch (error) {
      logger.error({ emailId: email.id, error }, 'Failed to route email to Discord');
    }
  }

  /**
   * Execute automatic actions based on classification
   */
  private async executeAutoActions(email: EmailMetadata, classification: ClassificationResult): Promise<void> {
    if (!this.gmail) return;

    try {
      switch (classification.action) {
        case EmailAction.AUTO_ARCHIVE:
          await this.gmail.users.messages.modify({
            userId: 'me',
            id: email.id,
            requestBody: {
              removeLabelIds: ['UNREAD', 'INBOX']
            },
          });
          this.processingStats.autoArchived++;
          logger.debug({ emailId: email.id }, 'Email auto-archived');
          break;

        case EmailAction.SPAM_FILTER:
          await this.gmail.users.messages.modify({
            userId: 'me',
            id: email.id,
            requestBody: {
              addLabelIds: ['SPAM'],
              removeLabelIds: ['UNREAD', 'INBOX']
            },
          });
          logger.debug({ emailId: email.id }, 'Email marked as spam');
          break;

        case EmailAction.IMMEDIATE_ALERT:
        case EmailAction.ESCALATE:
          // Mark as important
          await this.gmail.users.messages.modify({
            userId: 'me',
            id: email.id,
            requestBody: {
              addLabelIds: ['IMPORTANT']
            },
          });
          this.processingStats.escalated++;
          break;

        default:
          // Mark as read for processed emails
          await this.gmail.users.messages.modify({
            userId: 'me',
            id: email.id,
            requestBody: { removeLabelIds: ['UNREAD'] },
          });
          break;
      }

      // Execute any custom auto-actions
      if (classification.autoActions) {
        for (const action of classification.autoActions) {
          await this.executeCustomAction(email, action);
        }
      }

    } catch (error) {
      logger.error({ emailId: email.id, error }, 'Failed to execute auto-actions');
    }
  }

  /**
   * Execute custom actions (placeholder for future extensions)
   */
  private async executeCustomAction(email: EmailMetadata, action: any): Promise<void> {
    logger.debug({ emailId: email.id, actionType: action.type }, 'Custom action execution not implemented');
    // Future: Implement custom actions like auto-reply, forward, etc.
  }

  /**
   * Determine if email should still be sent to main group for traditional processing
   */
  private shouldSendToMainGroup(classification: ClassificationResult): boolean {
    // Send critical and high priority emails to main group for Andy to handle
    return classification.priority === Priority.CRITICAL ||
           classification.priority === Priority.HIGH ||
           classification.action === EmailAction.IMMEDIATE_ALERT ||
           classification.action === EmailAction.ESCALATE;
  }

  /**
   * Send email to main group for traditional NanoClaw processing
   */
  private async sendToMainGroup(email: EmailMetadata, classification: ClassificationResult): Promise<void> {
    const groups = this.opts.registeredGroups();
    const mainEntry = Object.entries(groups).find(([, g]) => g.isMain === true);

    if (!mainEntry) {
      logger.debug(
        { emailId: email.id },
        'No main group registered, skipping traditional delivery',
      );
      return;
    }

    const mainJid = mainEntry[0];
    const content = this.formatEmailForMainGroup(email, classification);

    this.opts.onMessage(mainJid, {
      id: email.id,
      chat_jid: mainJid,
      sender: email.from,
      sender_name: email.fromName || email.from,
      content,
      timestamp: email.timestamp,
      is_from_me: false,
    });

    logger.debug(
      { mainJid, emailId: email.id, category: classification.category },
      'Email sent to main group for traditional processing',
    );
  }

  /**
   * Format email content for main group delivery
   */
  private formatEmailForMainGroup(email: EmailMetadata, classification: ClassificationResult): string {
    const priority = classification.priority === Priority.CRITICAL ? '🚨 CRITICAL' :
                    classification.priority === Priority.HIGH ? '⚡ HIGH PRIORITY' : '';

    const categoryLabel = classification.category.replace('_', ' ').toUpperCase();

    return [
      `${priority ? `${priority} - ` : ''}[${categoryLabel} EMAIL]`,
      `From: ${email.fromName || email.from} <${email.from}>`,
      `Subject: ${email.subject}`,
      `Classification: ${classification.reason}`,
      `Confidence: ${Math.round(classification.confidence * 100)}%`,
      '',
      email.content || '(No content preview available)'
    ].join('\n');
  }

  /**
   * Send periodic statistics update to Discord
   */
  private async sendStatsUpdateIfNeeded(): Promise<void> {
    const now = new Date();
    const hoursSinceReset = (now.getTime() - this.processingStats.lastReset.getTime()) / (1000 * 60 * 60);

    // Send summary every 4 hours if there's been activity
    if (hoursSinceReset >= 4 && this.processingStats.totalProcessed > 0) {
      try {
        const summaryMessage = this.discordRouter.createActivitySummary([], '4 hours');
        summaryMessage.content = this.generateStatsContent();

        if (this.opts.onDiscordMessage) {
          await this.opts.onDiscordMessage(summaryMessage);
        }

        // Reset stats
        this.processingStats = {
          totalProcessed: 0,
          autoArchived: 0,
          escalated: 0,
          discordRouted: 0,
          lastReset: now
        };

        logger.info('Email processing stats summary sent to Discord');
      } catch (error) {
        logger.error({ error }, 'Failed to send stats summary');
      }
    }
  }

  /**
   * Generate statistics content for Discord
   */
  private generateStatsContent(): string {
    return [
      '📊 **Enhanced Gmail Processing Summary**',
      '',
      `📧 Total Processed: ${this.processingStats.totalProcessed}`,
      `📦 Auto-Archived: ${this.processingStats.autoArchived}`,
      `🚨 Escalated: ${this.processingStats.escalated}`,
      `💬 Routed to Discord: ${this.processingStats.discordRouted}`,
      '',
      'All emails classified and routed automatically. Check individual channels for details.'
    ].join('\n');
  }

  // Standard Gmail channel methods (updated for enhanced functionality)

  async sendMessage(jid: string, text: string): Promise<void> {
    if (!this.gmail) {
      logger.warn('Enhanced Gmail not initialized');
      return;
    }

    const threadId = jid.replace(/^gmail:/, '');
    const meta = this.threadMeta.get(threadId);

    if (!meta) {
      logger.warn({ jid }, 'No thread metadata for enhanced reply, cannot send');
      return;
    }

    // Enhanced reply formatting based on classification
    const enhancedText = this.enhanceReplyText(text, meta.classification);

    const subject = meta.subject.startsWith('Re:')
      ? meta.subject
      : `Re: ${meta.subject}`;

    const headers = [
      `To: ${meta.sender}`,
      `From: ${this.userEmail}`,
      `Subject: ${subject}`,
      `In-Reply-To: ${meta.messageId}`,
      `References: ${meta.messageId}`,
      'Content-Type: text/plain; charset=utf-8',
      '',
      enhancedText,
    ].join('\r\n');

    const encodedMessage = Buffer.from(headers)
      .toString('base64')
      .replace(/\+/g, '-')
      .replace(/\//g, '_')
      .replace(/=+$/, '');

    try {
      await this.gmail.users.messages.send({
        userId: 'me',
        requestBody: {
          raw: encodedMessage,
          threadId,
        },
      });
      logger.info({ to: meta.sender, threadId }, 'Enhanced Gmail reply sent');
    } catch (err) {
      logger.error({ jid, err }, 'Failed to send enhanced Gmail reply');
    }
  }

  /**
   * Enhance reply text based on original classification
   */
  private enhanceReplyText(text: string, classification?: ClassificationResult): string {
    if (!classification) return text;

    // Add context based on classification
    if (classification.priority === Priority.CRITICAL) {
      return `${text}\n\n[This message was prioritized due to its critical nature]`;
    }

    return text;
  }

  isConnected(): boolean {
    return this.gmail !== null;
  }

  ownsJid(jid: string): boolean {
    return jid.startsWith('gmail:');
  }

  async disconnect(): Promise<void> {
    if (this.pollTimer) {
      clearTimeout(this.pollTimer);
      this.pollTimer = null;
    }
    this.gmail = null;
    this.oauth2Client = null;
    logger.info('Enhanced Gmail channel stopped');
  }

  private buildQuery(): string {
    return 'is:unread in:inbox';
  }

  private extractTextBody(
    payload: gmail_v1.Schema$MessagePart | undefined,
  ): string {
    if (!payload) return '';

    // Direct text/plain body
    if (payload.mimeType === 'text/plain' && payload.body?.data) {
      return Buffer.from(payload.body.data, 'base64').toString('utf-8');
    }

    // Multipart: search parts recursively
    if (payload.parts) {
      // Prefer text/plain
      for (const part of payload.parts) {
        if (part.mimeType === 'text/plain' && part.body?.data) {
          return Buffer.from(part.body.data, 'base64').toString('utf-8');
        }
      }
      // Recurse into nested multipart
      for (const part of payload.parts) {
        const text = this.extractTextBody(part);
        if (text) return text;
      }
    }

    return '';
  }

  /**
   * Get classification engine for external access
   */
  public getClassifier(): EmailClassificationEngine {
    return this.classifier;
  }

  /**
   * Get Discord router for external access
   */
  public getDiscordRouter(): DiscordEmailRouter {
    return this.discordRouter;
  }

  /**
   * Get processing statistics
   */
  public getProcessingStats() {
    return { ...this.processingStats };
  }
}

// Register the enhanced Gmail channel
registerChannel('enhanced-gmail', (opts: ChannelOpts) => {
  const credDir = path.join(os.homedir(), '.gmail-mcp');
  if (
    !fs.existsSync(path.join(credDir, 'gcp-oauth.keys.json')) ||
    !fs.existsSync(path.join(credDir, 'credentials.json'))
  ) {
    logger.warn('Enhanced Gmail: credentials not found in ~/.gmail-mcp/');
    return null;
  }
  return new EnhancedGmailChannel(opts);
});