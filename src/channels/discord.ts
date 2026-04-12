import {
  Client,
  Events,
  GatewayIntentBits,
  Message,
  MessageReaction,
  PartialMessageReaction,
  PartialUser,
  TextChannel,
  User,
} from 'discord.js';

import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { ASSISTANT_NAME, TRIGGER_PATTERN } from '../config.js';
import { readEnvFile } from '../env.js';
import { logger } from '../logger.js';
import { registerChannel, ChannelOpts } from './registry.js';
import {
  Channel,
  OnChatMetadata,
  OnInboundMessage,
  RegisteredGroup,
} from '../types.js';

export interface DiscordChannelOpts {
  onMessage: OnInboundMessage;
  onChatMetadata: OnChatMetadata;
  registeredGroups: () => Record<string, RegisteredGroup>;
}

export class DiscordChannel implements Channel {
  name = 'discord';

  private client: Client | null = null;
  private opts: DiscordChannelOpts;
  private botToken: string;

  constructor(botToken: string, opts: DiscordChannelOpts) {
    this.botToken = botToken;
    this.opts = opts;
  }

  async connect(): Promise<void> {
    this.client = new Client({
      intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent,
        GatewayIntentBits.DirectMessages,
        GatewayIntentBits.GuildMessageReactions,
      ],
    });

    this.client.on(Events.MessageCreate, async (message: Message) => {
      // Ignore bot messages (including own)
      if (message.author.bot) return;

      const channelId = message.channelId;
      const chatJid = `dc:${channelId}`;
      let content = message.content;
      const timestamp = message.createdAt.toISOString();
      const senderName =
        message.member?.displayName ||
        message.author.displayName ||
        message.author.username;
      const sender = message.author.id;
      const msgId = message.id;

      // Determine chat name
      let chatName: string;
      if (message.guild) {
        const textChannel = message.channel as TextChannel;
        chatName = `${message.guild.name} #${textChannel.name}`;
      } else {
        chatName = senderName;
      }

      // Translate Discord @bot mentions into TRIGGER_PATTERN format.
      // Discord mentions look like <@botUserId> — these won't match
      // TRIGGER_PATTERN (e.g., ^@Andy\b), so we prepend the trigger
      // when the bot is @mentioned.
      if (this.client?.user) {
        const botId = this.client.user.id;
        const isBotMentioned =
          message.mentions.users.has(botId) ||
          content.includes(`<@${botId}>`) ||
          content.includes(`<@!${botId}>`);

        if (isBotMentioned) {
          // Strip the <@botId> mention to avoid visual clutter
          content = content
            .replace(new RegExp(`<@!?${botId}>`, 'g'), '')
            .trim();
          // Prepend trigger if not already present
          if (!TRIGGER_PATTERN.test(content)) {
            content = `@${ASSISTANT_NAME} ${content}`;
          }
        }
      }

      // Handle attachments — store placeholders so the agent knows something was sent
      if (message.attachments.size > 0) {
        const attachmentDescriptions = [...message.attachments.values()].map(
          (att) => {
            const contentType = att.contentType || '';
            if (contentType.startsWith('image/')) {
              return `[Image: ${att.name || 'image'}]`;
            } else if (contentType.startsWith('video/')) {
              return `[Video: ${att.name || 'video'}]`;
            } else if (contentType.startsWith('audio/')) {
              return `[Audio: ${att.name || 'audio'}]`;
            } else {
              return `[File: ${att.name || 'file'}]`;
            }
          },
        );
        if (content) {
          content = `${content}\n${attachmentDescriptions.join('\n')}`;
        } else {
          content = attachmentDescriptions.join('\n');
        }
      }

      // Handle reply context — include who the user is replying to
      if (message.reference?.messageId) {
        try {
          const repliedTo = await message.channel.messages.fetch(
            message.reference.messageId,
          );
          const replyAuthor =
            repliedTo.member?.displayName ||
            repliedTo.author.displayName ||
            repliedTo.author.username;
          content = `[Reply to ${replyAuthor}] ${content}`;
        } catch {
          // Referenced message may have been deleted
        }
      }

      // Store chat metadata for discovery
      const isGroup = message.guild !== null;
      this.opts.onChatMetadata(
        chatJid,
        timestamp,
        chatName,
        'discord',
        isGroup,
      );

      // Only deliver full message for registered groups
      const group = this.opts.registeredGroups()[chatJid];
      if (!group) {
        logger.debug(
          { chatJid, chatName },
          'Message from unregistered Discord channel',
        );
        return;
      }

      // Deliver message — startMessageLoop() will pick it up
      this.opts.onMessage(chatJid, {
        id: msgId,
        chat_jid: chatJid,
        sender,
        sender_name: senderName,
        content,
        timestamp,
        is_from_me: false,
      });

      logger.info(
        { chatJid, chatName, sender: senderName },
        'Discord message stored',
      );
    });

    // Handle message reactions for email triage
    this.client.on(
      Events.MessageReactionAdd,
      async (
        reaction: MessageReaction | PartialMessageReaction,
        user: User | PartialUser,
      ) => {
        await this.handleEmailTriageReaction(reaction, user, 'add');
      },
    );

    this.client.on(
      Events.MessageReactionRemove,
      async (
        reaction: MessageReaction | PartialMessageReaction,
        user: User | PartialUser,
      ) => {
        await this.handleEmailTriageReaction(reaction, user, 'remove');
      },
    );

    // Handle errors gracefully
    this.client.on(Events.Error, (err) => {
      logger.error({ err: err.message }, 'Discord client error');
    });

    return new Promise<void>((resolve) => {
      this.client!.once(Events.ClientReady, (readyClient) => {
        logger.info(
          { username: readyClient.user.tag, id: readyClient.user.id },
          'Discord bot connected',
        );
        console.log(`\n  Discord bot: ${readyClient.user.tag}`);
        console.log(
          `  Use /chatid command or check channel IDs in Discord settings\n`,
        );
        resolve();
      });

      this.client!.login(this.botToken);
    });
  }

  async sendMessage(jid: string, text: string): Promise<void> {
    if (!this.client) {
      logger.warn('Discord client not initialized');
      return;
    }

    try {
      const channelId = jid.replace(/^dc:/, '');
      const channel = await this.client.channels.fetch(channelId);

      if (!channel || !('send' in channel)) {
        logger.warn({ jid }, 'Discord channel not found or not text-based');
        return;
      }

      const textChannel = channel as TextChannel;

      // Check if this is an email triage message (new proactive system)
      const isEmailTriageMessage =
        text.includes('EMAIL ') && text.includes('Quick Actions');

      // Discord has a 2000 character limit per message — split if needed
      const MAX_LENGTH = 2000;
      let lastMessage: Message | null = null;

      if (text.length <= MAX_LENGTH) {
        lastMessage = await textChannel.send(text);
      } else {
        const chunks = [];
        for (let i = 0; i < text.length; i += MAX_LENGTH) {
          chunks.push(text.slice(i, i + MAX_LENGTH));
        }

        for (let i = 0; i < chunks.length; i++) {
          lastMessage = await textChannel.send(chunks[i]);
        }
      }

      // Add letter reactions to email triage messages
      if (isEmailTriageMessage && lastMessage) {
        await this.addProactiveEmailReactions(lastMessage);
      }

      logger.info(
        { jid, length: text.length, isEmailTriage: isEmailTriageMessage },
        'Discord message sent',
      );
    } catch (err) {
      logger.error({ jid, err }, 'Failed to send Discord message');
    }
  }

  /**
   * Add letter reactions to proactive email triage messages
   */
  private async addProactiveEmailReactions(message: Message): Promise<void> {
    const reactions = ['🅰️', '🅱️', '📅', '🗑️', '📧', '📝'];

    try {
      for (const reaction of reactions) {
        await message.react(reaction);
        // Small delay to avoid rate limiting
        await new Promise((resolve) => setTimeout(resolve, 300));
      }
      logger.info({ messageId: message.id }, 'Proactive email reactions added');
    } catch (error) {
      logger.error(
        { messageId: message.id, error },
        'Failed to add proactive email reactions',
      );
    }
  }

  /**
   * Add numbered reactions to email triage messages (legacy system)
   */
  private async addTriageReactions(message: Message): Promise<void> {
    const reactions = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣'];

    try {
      for (const reaction of reactions) {
        await message.react(reaction);
        // Small delay to avoid rate limiting
        await new Promise((resolve) => setTimeout(resolve, 250));
      }
      logger.info({ messageId: message.id }, 'Email triage reactions added');
    } catch (error) {
      logger.error(
        { messageId: message.id, error },
        'Failed to add email triage reactions',
      );
    }
  }

  isConnected(): boolean {
    return this.client !== null && this.client.isReady();
  }

  ownsJid(jid: string): boolean {
    return jid.startsWith('dc:');
  }

  async disconnect(): Promise<void> {
    if (this.client) {
      this.client.destroy();
      this.client = null;
      logger.info('Discord bot stopped');
    }
  }

  /**
   * Handle numbered reactions for email triage system
   */
  private async handleEmailTriageReaction(
    reaction: MessageReaction | PartialMessageReaction,
    user: User | PartialUser,
    action: 'add' | 'remove',
  ): Promise<void> {
    try {
      // Ignore bot reactions
      if (user.bot) return;

      // Fetch partial data if needed
      if (reaction.partial) {
        reaction = await reaction.fetch();
      }
      if (user.partial) {
        user = await user.fetch();
      }

      let message = reaction.message;
      if (message.partial) {
        message = await message.fetch();
      }
      const reactionEmoji = reaction.emoji.name;

      // Handle both legacy numbered reactions and new letter reactions
      const numberReactions = [
        '1️⃣',
        '2️⃣',
        '3️⃣',
        '4️⃣',
        '5️⃣',
        '6️⃣',
        '7️⃣',
        '8️⃣',
        '9️⃣',
      ];
      const letterReactions = ['🅰️', '🅱️', '📅', '🗑️', '📧', '📝'];

      const isNumberReaction = numberReactions.includes(reactionEmoji || '');
      const isLetterReaction = letterReactions.includes(reactionEmoji || '');

      if (!isNumberReaction && !isLetterReaction) {
        return;
      }

      // Check if this is a proactive email triage message (new system)
      if (isLetterReaction && message.content?.includes('EMAIL ')) {
        if (action === 'add') {
          await this.handleProactiveEmailReaction(
            reactionEmoji!,
            message,
            user,
          );
        }
        return;
      }

      // Legacy system - Check if this is an email triage message by looking for Email ID
      if (!message.content?.includes('Email ID:')) {
        return;
      }

      // Extract email ID from message
      const emailIdMatch = message.content.match(/Email ID:\s*([^\s`]+)/);
      if (!emailIdMatch) {
        logger.warn(
          { messageId: message.id },
          'Could not extract email ID from reaction message',
        );
        return;
      }

      const emailId = emailIdMatch[1];
      const userId = user.id;
      const userName = user.username || user.displayName || 'Unknown';

      if (action === 'add') {
        await this.processEmailTriageAction(
          emailId,
          reactionEmoji!,
          userId,
          userName,
          message,
        );
      }

      logger.info(
        {
          emailId,
          action: reactionEmoji,
          userId,
          userName,
          messageId: message.id,
        },
        `Email triage reaction ${action === 'add' ? 'processed' : 'removed'}`,
      );
    } catch (error) {
      logger.error({ error }, 'Failed to handle email triage reaction');
    }
  }

  /**
   * Handle proactive email system reactions (A, B, C, D, E, F)
   */
  private async handleProactiveEmailReaction(
    reactionEmoji: string,
    message: Message,
    user: User | PartialUser,
  ): Promise<void> {
    try {
      // Extract EMAIL letter from message
      const emailMatch = message.content?.match(/EMAIL ([A-Z])/);
      if (!emailMatch) {
        logger.warn(
          { messageId: message.id },
          'Could not extract email letter from proactive message',
        );
        return;
      }

      const emailLetter = emailMatch[1];
      const userName = user.username || user.displayName || 'Unknown';

      // Call our proactive email reaction handler
      // SECURITY: Load from project scripts/, NOT from container-writable workspace
      const __filename = fileURLToPath(import.meta.url);
      const __dirname = path.dirname(__filename);
      const handlerPath = path.join(__dirname, '..', '..', 'scripts', 'email-reaction-handler.cjs');
      const {
        handleEmailReaction,
      } = require(handlerPath);

      await handleEmailReaction(message.content || '', reactionEmoji, user.id);

      // Update message to show action taken
      const actionTaken = this.getActionFromReaction(reactionEmoji);
      const updatedContent = this.addProactiveActionStatus(
        message.content || '',
        actionTaken,
        userName,
      );

      if (message.editable) {
        await message.edit(updatedContent);
      } else {
        await message.reply(
          `✅ **${actionTaken}** processed for EMAIL ${emailLetter} by ${userName}`,
        );
      }

      logger.info(
        {
          emailLetter,
          action: reactionEmoji,
          actionName: actionTaken,
          userId: user.id,
          userName,
          messageId: message.id,
        },
        'Proactive email reaction processed',
      );
    } catch (error) {
      logger.error(
        { error, messageId: message.id },
        'Failed to handle proactive email reaction',
      );
      await message.reply(
        `❌ Failed to process email action. Please try again or handle manually.`,
      );
    }
  }

  /**
   * Get action name from reaction emoji
   */
  private getActionFromReaction(reactionEmoji: string): string {
    const actionMap: Record<string, string> = {
      '🅰️': 'Archive',
      '🅱️': 'Business Reply',
      '📅': 'Add to Calendar',
      '🗑️': 'Delete',
      '📧': 'Draft Reply',
      '📝': 'Note and Archive',
    };
    return actionMap[reactionEmoji] || 'Unknown Action';
  }

  /**
   * Add action status to proactive email message
   */
  private addProactiveActionStatus(
    originalContent: string,
    actionName: string,
    userName: string,
  ): string {
    const statusLine = `\n\n✅ **PROCESSED:** ${actionName} by ${userName} at ${new Date().toLocaleTimeString()}`;

    // If there's already an action status, replace it
    if (originalContent.includes('✅ **PROCESSED:**')) {
      return originalContent.replace(
        /\n\n✅ \*\*PROCESSED:\*\*.*$/s,
        statusLine,
      );
    }

    return originalContent + statusLine;
  }

  /**
   * Process the specific email triage action based on number reaction
   */
  private async processEmailTriageAction(
    emailId: string,
    reactionEmoji: string,
    userId: string,
    userName: string,
    message: Message,
  ): Promise<void> {
    const actionMap: Record<string, string> = {
      '1️⃣': 'Archive',
      '2️⃣': 'Reply',
      '3️⃣': 'Forward',
      '4️⃣': 'Mark Important/Priority',
      '5️⃣': 'Schedule Follow-up',
      '6️⃣': 'Delete/Spam',
      '7️⃣': 'Create Task',
      '8️⃣': 'Ask Andy for Help',
      '9️⃣': 'Move to Folder',
    };

    const actionName = actionMap[reactionEmoji];
    if (!actionName) return;

    try {
      // Send a request to Andy (the assistant) to handle the email action
      const andyMessage = this.buildAndyRequestMessage(
        emailId,
        actionName,
        userName,
      );

      // Send the request in the same channel or a designated Andy channel
      const chatJid = `dc:${message.channelId}`;

      // Create message for Andy to process
      this.opts.onMessage(chatJid, {
        id: `${message.id}-reaction-${Date.now()}`,
        chat_jid: chatJid,
        sender: userId,
        sender_name: userName,
        content: andyMessage,
        timestamp: new Date().toISOString(),
        is_from_me: false,
      });

      // Update the original message to show action taken
      if (message.editable) {
        const updatedContent = this.addActionStatusToMessage(
          message.content || '',
          actionName,
          userName,
        );
        await message.edit(updatedContent);
      } else {
        // If can't edit, reply with status
        await message.reply(
          `✅ **${actionName}** requested by ${userName} for email \`${emailId}\``,
        );
      }
    } catch (error) {
      logger.error(
        { emailId, actionName, error },
        'Failed to process email triage action',
      );
      await message.reply(
        `❌ Failed to process **${actionName}** for email \`${emailId}\`. Please try again or handle manually.`,
      );
    }
  }

  /**
   * Build a message for Andy to handle the email action
   */
  private buildAndyRequestMessage(
    emailId: string,
    actionName: string,
    userName: string,
  ): string {
    const baseMessage = `@${ASSISTANT_NAME} Please handle email triage action:

**Action:** ${actionName}
**Email ID:** ${emailId}
**Requested by:** ${userName}
**Timestamp:** ${new Date().toISOString()}

`;

    switch (actionName) {
      case 'Archive':
        return (
          baseMessage +
          'Please archive this email in Gmail and mark it as processed.'
        );

      case 'Reply':
        return (
          baseMessage +
          'Please compose and send an appropriate reply to this email. Use your best judgment for the response content based on the email context.'
        );

      case 'Forward':
        return (
          baseMessage +
          'Please forward this email to the appropriate person/team. Determine the best recipient based on the email content and context.'
        );

      case 'Mark Important/Priority':
        return (
          baseMessage +
          'Please mark this email as important/priority in Gmail and ensure it gets expedited handling.'
        );

      case 'Schedule Follow-up':
        return (
          baseMessage +
          'Please schedule a follow-up reminder for this email. Set an appropriate follow-up time based on the email content and urgency.'
        );

      case 'Delete/Spam':
        return (
          baseMessage +
          "Please delete this email or mark it as spam if appropriate. Use caution and only do this if you're confident it's spam or truly unnecessary."
        );

      case 'Create Task':
        return (
          baseMessage +
          'Please create a task or calendar item based on this email content. Extract any actionable items and schedule them appropriately.'
        );

      case 'Ask Andy for Help':
        return (
          baseMessage +
          'Please provide guidance on how to handle this email. Analyze the content and suggest the best course of action.'
        );

      case 'Move to Folder':
        return (
          baseMessage +
          'Please move this email to the appropriate folder/label in Gmail based on its content and category.'
        );

      default:
        return baseMessage + 'Please handle this email appropriately.';
    }
  }

  /**
   * Add action status to the original email message
   */
  private addActionStatusToMessage(
    originalContent: string,
    actionName: string,
    userName: string,
  ): string {
    const statusLine = `\n\n✅ **Action Taken:** ${actionName} (requested by ${userName} at ${new Date().toLocaleTimeString()})`;

    // If there's already an action status, replace it
    if (originalContent.includes('✅ **Action Taken:**')) {
      return originalContent.replace(
        /\n\n✅ \*\*Action Taken:\*\*.*$/s,
        statusLine,
      );
    }

    return originalContent + statusLine;
  }

  async setTyping(jid: string, isTyping: boolean): Promise<void> {
    if (!this.client || !isTyping) return;
    try {
      const channelId = jid.replace(/^dc:/, '');
      const channel = await this.client.channels.fetch(channelId);
      if (channel && 'sendTyping' in channel) {
        await (channel as TextChannel).sendTyping();
      }
    } catch (err) {
      logger.debug({ jid, err }, 'Failed to send Discord typing indicator');
    }
  }
}

registerChannel('discord', (opts: ChannelOpts) => {
  const envVars = readEnvFile(['DISCORD_BOT_TOKEN']);
  const token =
    process.env.DISCORD_BOT_TOKEN || envVars.DISCORD_BOT_TOKEN || '';
  if (!token) {
    logger.warn('Discord: DISCORD_BOT_TOKEN not set');
    return null;
  }
  return new DiscordChannel(token, opts);
});
