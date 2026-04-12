/**
 * DISCORD EMAIL ROUTING SYSTEM
 * Routes classified emails to appropriate Discord channels with priority-based formatting
 */

import { logger } from './logger.js';
import {
  EmailMetadata,
  ClassificationResult,
  EmailCategory,
  Priority,
  UrgencyLevel,
  EmailAction,
} from './email-classifier.js';

export interface DiscordChannelConfig {
  id: string;
  name: string;
  purpose: string;
  alertLevel: 'silent' | 'normal' | 'mention' | 'urgent';
  formatStyle: 'full' | 'summary' | 'minimal' | 'priority_unified';
}

export interface DiscordMessage {
  channelId: string;
  content: string;
  mentions?: string[];
  embeds?: DiscordEmbed[];
}

export interface DiscordEmbed {
  title?: string;
  description?: string;
  color?: number;
  fields?: { name: string; value: string; inline?: boolean }[];
  timestamp?: string;
  footer?: { text: string };
}

export class DiscordEmailRouter {
  private channels: Map<EmailCategory, DiscordChannelConfig> = new Map();
  private escalationHistory = new Map<string, Date>();

  constructor() {
    this.initializeChannels();
  }

  private initializeChannels(): void {
    // SIMPLIFIED SINGLE CHANNEL APPROACH
    // All emails route to #email-triage with smart priority formatting
    const emailTriageChannelId = '1484839736609607832'; // DOS #email-triage channel

    // Map all categories to the single email-triage channel with priority-based formatting
    Object.values(EmailCategory).forEach((category) => {
      this.channels.set(category, {
        id: emailTriageChannelId,
        name: 'email-triage',
        purpose: 'Unified inbox zero automation with smart priority formatting',
        alertLevel: this.getAlertLevelForCategory(category),
        formatStyle: 'priority_unified',
      });
    });
  }

  private getAlertLevelForCategory(
    category: EmailCategory,
  ): 'silent' | 'normal' | 'mention' | 'urgent' {
    switch (category) {
      case EmailCategory.BUSINESS_CRITICAL:
        return 'urgent';
      case EmailCategory.CLIENT_COMMUNICATIONS:
      case EmailCategory.FINANCIAL_INSURANCE:
        return 'mention';
      case EmailCategory.RECRUITMENT_PROSPECTS:
      case EmailCategory.CALENDAR_SCHEDULING:
      case EmailCategory.VENDOR_OPERATIONAL:
        return 'normal';
      case EmailCategory.MARKETING_ANALYTICS:
      case EmailCategory.PERSONAL_ADMIN:
      case EmailCategory.SPAM_NOISE:
      default:
        return 'silent';
    }
  }

  /**
   * Route classified email to appropriate Discord channel
   */
  public async routeEmail(
    email: EmailMetadata,
    classification: ClassificationResult,
  ): Promise<DiscordMessage> {
    const channelConfig = this.channels.get(classification.category);
    if (!channelConfig) {
      throw new Error(
        `No Discord channel configured for category: ${classification.category}`,
      );
    }

    const message = this.formatEmailMessage(
      email,
      classification,
      channelConfig,
    );

    // Mark message as needing numbered reactions for triage
    (message as any).needsTriageReactions = true;

    // Handle escalation if configured
    if (
      classification.escalation &&
      this.shouldEscalate(email.id, classification.escalation)
    ) {
      await this.handleEscalation(email, classification, message);
    }

    logger.info(
      {
        emailId: email.id,
        category: classification.category,
        priority: classification.priority,
        channelId: channelConfig.id,
      },
      'Email routed to Discord channel',
    );

    return message;
  }

  /**
   * Format email message based on priority and channel configuration
   */
  private formatEmailMessage(
    email: EmailMetadata,
    classification: ClassificationResult,
    channelConfig: DiscordChannelConfig,
  ): DiscordMessage {
    const message: DiscordMessage = {
      channelId: channelConfig.id,
      content: '',
      mentions: [],
      embeds: [],
    };

    // Determine mentions based on alert level and urgency
    message.mentions = this.determineMentions(classification, channelConfig);

    // Format based on style
    switch (channelConfig.formatStyle) {
      case 'priority_unified':
        return this.formatPriorityUnifiedMessage(
          email,
          classification,
          message,
        );
      case 'full':
        return this.formatFullMessage(email, classification, message);
      case 'summary':
        return this.formatSummaryMessage(email, classification, message);
      case 'minimal':
        return this.formatMinimalMessage(email, classification, message);
      default:
        return this.formatPriorityUnifiedMessage(
          email,
          classification,
          message,
        );
    }

    return message;
  }

  private formatFullMessage(
    email: EmailMetadata,
    classification: ClassificationResult,
    message: DiscordMessage,
  ): DiscordMessage {
    const urgencyEmoji = this.getUrgencyEmoji(classification.urgency);
    const priorityEmoji = this.getPriorityEmoji(classification.priority);

    // Create rich embed
    const embed: DiscordEmbed = {
      title: `${urgencyEmoji} ${priorityEmoji} ${classification.category.replace('_', ' ').toUpperCase()}`,
      description: email.subject,
      color: this.getPriorityColor(classification.priority),
      fields: [
        {
          name: '📧 From',
          value: `${email.fromName || email.from}\n\`${email.from}\``,
          inline: true,
        },
        {
          name: '⏰ Priority',
          value: `${classification.priority}\n${classification.urgency}`,
          inline: true,
        },
        {
          name: '🎯 Confidence',
          value: `${Math.round(classification.confidence * 100)}%`,
          inline: true,
        },
        {
          name: '📝 Reason',
          value: classification.reason,
          inline: false,
        },
      ],
      timestamp: email.timestamp,
      footer: { text: `Email ID: ${email.id}` },
    };

    // Add content preview if available
    if (email.content) {
      const preview = email.content.substring(0, 300);
      embed.fields!.push({
        name: '📖 Preview',
        value: `\`\`\`\n${preview}${email.content.length > 300 ? '...' : ''}\n\`\`\``,
        inline: false,
      });
    }

    message.embeds = [embed];

    // Add action buttons instruction
    const actionText = this.getActionText(classification.action);
    message.content =
      `${message.mentions?.join(' ') || ''}\n${actionText}`.trim();

    return message;
  }

  private formatSummaryMessage(
    email: EmailMetadata,
    classification: ClassificationResult,
    message: DiscordMessage,
  ): DiscordMessage {
    const urgencyEmoji = this.getUrgencyEmoji(classification.urgency);
    const priorityEmoji = this.getPriorityEmoji(classification.priority);

    message.content = [
      `${urgencyEmoji} ${priorityEmoji} **${classification.category.replace('_', ' ').toUpperCase()}**`,
      `**From:** ${email.fromName || email.from}`,
      `**Subject:** ${email.subject}`,
      `**Priority:** ${classification.priority} (${classification.urgency})`,
      `**Reason:** ${classification.reason}`,
      `**Email ID:** \`${email.id}\``,
      '',
      this.getActionText(classification.action),
    ].join('\n');

    if (message.mentions && message.mentions.length > 0) {
      message.content = `${message.mentions.join(' ')}\n\n${message.content}`;
    }

    return message;
  }

  private formatMinimalMessage(
    email: EmailMetadata,
    classification: ClassificationResult,
    message: DiscordMessage,
  ): DiscordMessage {
    const urgencyEmoji = this.getUrgencyEmoji(classification.urgency);

    message.content = [
      `${urgencyEmoji} **${classification.category.replace('_', ' ')}** from ${email.fromName || email.from}`,
      `📧 ${email.subject}`,
      `\`${email.id}\``,
    ].join('\n');

    return message;
  }

  /**
   * NEW: Priority Unified Format - Single channel with smart visual hierarchy
   */
  private formatPriorityUnifiedMessage(
    email: EmailMetadata,
    classification: ClassificationResult,
    message: DiscordMessage,
  ): DiscordMessage {
    const priorityConfig = this.getPriorityDisplayConfig(
      classification.priority,
      classification.urgency,
    );

    // Build main message content with visual hierarchy
    const mentionLine =
      message.mentions && message.mentions.length > 0
        ? `${message.mentions.join(' ')}\n\n`
        : '';

    const headerLine = `${priorityConfig.emoji} **${priorityConfig.label}** - ${this.getCategoryDisplayName(classification.category)}`;

    // Create clean, scannable format
    const emailInfo = [
      `📧 **From:** ${email.fromName || email.from}`,
      `📝 **Subject:** ${email.subject}`,
      `⏰ **Received:** ${this.formatTimestamp(email.timestamp)}`,
      `🎯 **Action:** ${this.getSimplifiedAction(classification.action, classification.urgency)}`,
    ];

    // Add content preview for higher priority items
    let contentPreview = '';
    if (
      classification.priority === Priority.CRITICAL ||
      classification.priority === Priority.HIGH
    ) {
      if (email.content) {
        const preview = email.content.substring(0, 200);
        contentPreview = `\n\n**Preview:** \`${preview}${email.content.length > 200 ? '...' : ''}\``;
      }
    }

    // Add reason and confidence for context
    const contextInfo = `\n\n**Why:** ${classification.reason} (${Math.round(classification.confidence * 100)}% confidence)`;

    // Quick action buttons with numbered reactions
    const actionButtons = `\n\n**Quick Actions:** React with numbers 1-9
1️⃣ Archive  2️⃣ Reply  3️⃣ Forward  4️⃣ Mark Important
5️⃣ Schedule Follow-up  6️⃣ Delete/Spam  7️⃣ Create Task
8️⃣ Ask Andy for Help  9️⃣ Move to Folder`;

    // Email ID for reference
    const emailRef = `\n\n\`Email ID: ${email.id}\``;

    message.content = [
      mentionLine,
      headerLine,
      ...emailInfo,
      contentPreview,
      contextInfo,
      actionButtons,
      emailRef,
    ]
      .filter(Boolean)
      .join('');

    return message;
  }

  private getPriorityDisplayConfig(
    priority: Priority,
    urgency: UrgencyLevel,
  ): {
    emoji: string;
    label: string;
    color: string;
  } {
    switch (priority) {
      case Priority.CRITICAL:
        return {
          emoji: '🚨 **RED**',
          label: 'CRITICAL',
          color: 'RED',
        };
      case Priority.HIGH:
        return {
          emoji: '🟡 **YELLOW**',
          label: 'IMPORTANT',
          color: 'YELLOW',
        };
      case Priority.MEDIUM:
        return {
          emoji: '🟢 **GREEN**',
          label: 'MEDIUM',
          color: 'GREEN',
        };
      case Priority.LOW:
        return {
          emoji: '🟢 **GREEN**',
          label: 'FYI',
          color: 'GREEN',
        };
      case Priority.ARCHIVE:
        return {
          emoji: '📦',
          label: 'ARCHIVED',
          color: 'GRAY',
        };
      default:
        return {
          emoji: '🟢 **GREEN**',
          label: 'STANDARD',
          color: 'GREEN',
        };
    }
  }

  private getCategoryDisplayName(category: EmailCategory): string {
    switch (category) {
      case EmailCategory.BUSINESS_CRITICAL:
        return 'Business Critical';
      case EmailCategory.CLIENT_COMMUNICATIONS:
        return 'Client Communication';
      case EmailCategory.RECRUITMENT_PROSPECTS:
        return 'Recruitment';
      case EmailCategory.CALENDAR_SCHEDULING:
        return 'Calendar/Scheduling';
      case EmailCategory.FINANCIAL_INSURANCE:
        return 'Financial/Insurance';
      case EmailCategory.VENDOR_OPERATIONAL:
        return 'Vendor/Operations';
      case EmailCategory.MARKETING_ANALYTICS:
        return 'Marketing/Analytics';
      case EmailCategory.PERSONAL_ADMIN:
        return 'Personal/Admin';
      case EmailCategory.SPAM_NOISE:
        return 'Spam/Noise';
      default:
        return 'Uncategorized';
    }
  }

  private formatTimestamp(timestamp: string): string {
    const date = new Date(timestamp);
    const now = new Date();
    const diffMinutes = Math.floor(
      (now.getTime() - date.getTime()) / (1000 * 60),
    );

    if (diffMinutes < 1) return 'Just now';
    if (diffMinutes < 60) return `${diffMinutes} minutes ago`;

    const diffHours = Math.floor(diffMinutes / 60);
    if (diffHours < 24) return `${diffHours} hours ago`;

    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  }

  private getSimplifiedAction(
    action: EmailAction,
    urgency: UrgencyLevel,
  ): string {
    switch (action) {
      case EmailAction.IMMEDIATE_ALERT:
        return 'IMMEDIATE RESPONSE NEEDED';
      case EmailAction.PRIORITY_ROUTE:
        return 'Priority handling required';
      case EmailAction.STANDARD_PROCESS:
        return 'Standard processing';
      case EmailAction.BATCH_PROCESS:
        return 'Can wait for batch processing';
      case EmailAction.AUTO_ARCHIVE:
        return 'Auto-archived (FYI only)';
      case EmailAction.SPAM_FILTER:
        return 'Marked as spam';
      case EmailAction.ESCALATE:
        return 'Escalated to management';
      default:
        return 'Review and classify';
    }
  }

  private determineMentions(
    classification: ClassificationResult,
    channelConfig: DiscordChannelConfig,
  ): string[] {
    const mentions: string[] = [];

    // SIMPLIFIED PRIORITY-BASED MENTIONS
    if (
      classification.priority === Priority.CRITICAL &&
      classification.urgency === UrgencyLevel.IMMEDIATE
    ) {
      // 🚨 RED = Critical (immediate action) - ping @here
      mentions.push('@here');
    } else if (
      classification.priority === Priority.HIGH ||
      classification.priority === Priority.CRITICAL
    ) {
      // 🟡 YELLOW = Important (today) - mention @David
      mentions.push('<@164006671699107841>'); // Replace with actual David's Discord ID
    }
    // 🟢 GREEN = FYI (when convenient) - silent post (no mentions)

    // Add escalation mentions if configured
    if (classification.escalation?.mentions) {
      mentions.push(...classification.escalation.mentions);
    }

    return mentions;
  }

  private getUrgencyEmoji(urgency: UrgencyLevel): string {
    switch (urgency) {
      case UrgencyLevel.IMMEDIATE:
        return '🚨';
      case UrgencyLevel.FAST_TRACK:
        return '⚡';
      case UrgencyLevel.STANDARD:
        return '📋';
      case UrgencyLevel.BATCH:
        return '📝';
      default:
        return '📬';
    }
  }

  private getPriorityEmoji(priority: Priority): string {
    switch (priority) {
      case Priority.CRITICAL:
        return '🔴';
      case Priority.HIGH:
        return '🟠';
      case Priority.MEDIUM:
        return '🟡';
      case Priority.LOW:
        return '🟢';
      case Priority.ARCHIVE:
        return '📦';
    }
  }

  private getPriorityColor(priority: Priority): number {
    switch (priority) {
      case Priority.CRITICAL:
        return 0xff0000; // Red
      case Priority.HIGH:
        return 0xff8000; // Orange
      case Priority.MEDIUM:
        return 0xffff00; // Yellow
      case Priority.LOW:
        return 0x00ff00; // Green
      case Priority.ARCHIVE:
        return 0x808080; // Gray
    }
  }

  private getActionText(action: EmailAction): string {
    const numberedActions = `\n\n**📱 MOBILE-FRIENDLY ACTIONS:** React with number emojis
1️⃣ Archive  2️⃣ Reply  3️⃣ Forward  4️⃣ Mark Important/Priority
5️⃣ Schedule Follow-up  6️⃣ Delete/Spam  7️⃣ Create Task
8️⃣ Ask Andy for Help  9️⃣ Move to Folder`;

    switch (action) {
      case EmailAction.IMMEDIATE_ALERT:
        return '🎯 **IMMEDIATE ACTION REQUIRED**' + numberedActions;
      case EmailAction.PRIORITY_ROUTE:
        return '⚡ **PRIORITY PROCESSING**' + numberedActions;
      case EmailAction.STANDARD_PROCESS:
        return '📋 **STANDARD PROCESSING**' + numberedActions;
      case EmailAction.BATCH_PROCESS:
        return '📝 **BATCH PROCESSING**' + numberedActions;
      case EmailAction.AUTO_ARCHIVE:
        return '📦 **AUTO-ARCHIVED**' + numberedActions;
      case EmailAction.SPAM_FILTER:
        return '🗑️ **SPAM FILTERED**' + numberedActions;
      case EmailAction.ESCALATE:
        return '🚨 **ESCALATED**' + numberedActions;
      default:
        return '📬 **EMAIL RECEIVED**' + numberedActions;
    }
  }

  private shouldEscalate(emailId: string, escalationConfig: any): boolean {
    const lastEscalation = this.escalationHistory.get(emailId);
    if (!lastEscalation) {
      this.escalationHistory.set(emailId, new Date());
      // Prevent unbounded growth — trim oldest entries when too large
      if (this.escalationHistory.size > 1000) {
        const entries = [...this.escalationHistory.entries()]
          .sort((a, b) => a[1].getTime() - b[1].getTime());
        this.escalationHistory = new Map(entries.slice(entries.length - 500));
      }
      return true;
    }

    const timeSinceEscalation = new Date().getTime() - lastEscalation.getTime();
    return (
      escalationConfig.delayMs &&
      timeSinceEscalation >= escalationConfig.delayMs
    );
  }

  private async handleEscalation(
    email: EmailMetadata,
    classification: ClassificationResult,
    originalMessage: DiscordMessage,
  ): Promise<void> {
    if (!classification.escalation?.channels) return;

    for (const channelId of classification.escalation.channels) {
      const escalationMessage: DiscordMessage = {
        channelId,
        content: `🚨 **ESCALATED EMAIL** - No response received\n\n${originalMessage.content}`,
        mentions: classification.escalation.mentions || ['@here'],
        embeds: originalMessage.embeds,
      };

      logger.info(
        {
          emailId: email.id,
          escalationChannel: channelId,
        },
        'Email escalated to additional channel',
      );
    }

    this.escalationHistory.set(email.id, new Date());
  }

  /**
   * Get channel configuration for a category
   */
  public getChannelConfig(
    category: EmailCategory,
  ): DiscordChannelConfig | undefined {
    return this.channels.get(category);
  }

  /**
   * Update channel configuration
   */
  public updateChannelConfig(
    category: EmailCategory,
    config: Partial<DiscordChannelConfig>,
  ): void {
    const existing = this.channels.get(category);
    if (existing) {
      this.channels.set(category, { ...existing, ...config });
    }
  }

  /**
   * Create summary of recent email activity
   */
  public createActivitySummary(
    classifications: ClassificationResult[],
    timeframe: string,
  ): DiscordMessage {
    const stats = {
      total: classifications.length,
      critical: classifications.filter((c) => c.priority === Priority.CRITICAL)
        .length,
      high: classifications.filter((c) => c.priority === Priority.HIGH).length,
      medium: classifications.filter((c) => c.priority === Priority.MEDIUM)
        .length,
      low: classifications.filter((c) => c.priority === Priority.LOW).length,
      archived: classifications.filter(
        (c) => c.action === EmailAction.AUTO_ARCHIVE,
      ).length,
    };

    const embed: DiscordEmbed = {
      title: `📊 Email Activity Summary - ${timeframe}`,
      color: 0x0099ff,
      fields: [
        {
          name: '📧 Total Emails',
          value: stats.total.toString(),
          inline: true,
        },
        {
          name: '🔴 Critical',
          value: stats.critical.toString(),
          inline: true,
        },
        {
          name: '🟠 High Priority',
          value: stats.high.toString(),
          inline: true,
        },
        {
          name: '🟡 Medium Priority',
          value: stats.medium.toString(),
          inline: true,
        },
        {
          name: '🟢 Low Priority',
          value: stats.low.toString(),
          inline: true,
        },
        {
          name: '📦 Auto-Archived',
          value: stats.archived.toString(),
          inline: true,
        },
      ],
      timestamp: new Date().toISOString(),
      footer: { text: 'Email Classification System' },
    };

    return {
      channelId:
        this.channels.get(EmailCategory.BUSINESS_CRITICAL)?.id ||
        '1484841234567890128', // email-triage channel
      content: '',
      embeds: [embed],
    };
  }
}
