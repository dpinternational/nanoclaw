import https from 'https';
import fs from 'fs';
import os from 'os';
import path from 'path';
import { Api, Bot } from 'grammy';
import crypto from 'crypto';

import {
  ASSISTANT_NAME,
  TRIGGER_PATTERN,
  WEBHOOK_ENABLED,
  WEBHOOK_SECRET_TOKEN,
  WEBHOOK_DOMAIN,
} from '../config.js';
import { readEnvFile } from '../env.js';
import { logger } from '../logger.js';
import { registerChannel, ChannelOpts } from './registry.js';
import {
  Channel,
  OnChatMetadata,
  OnInboundMessage,
  RegisteredGroup,
} from '../types.js';
import { TelegramApi } from '../telegram-api.js';
import { webhookServer, WebhookUpdate } from '../webhook-server.js';

export interface TelegramChannelOpts {
  onMessage: OnInboundMessage;
  onChatMetadata: OnChatMetadata;
  registeredGroups: () => Record<string, RegisteredGroup>;
}

/**
 * Send a message with Telegram Markdown parse mode, falling back to plain text.
 * Claude's output naturally matches Telegram's Markdown v1 format:
 *   *bold*, _italic_, `code`, ```code blocks```, [links](url)
 */
async function sendTelegramMessage(
  api: { sendMessage: Api['sendMessage'] },
  chatId: string | number,
  text: string,
  options: { message_thread_id?: number } = {},
): Promise<void> {
  try {
    await api.sendMessage(chatId, text, {
      ...options,
      parse_mode: 'Markdown',
    });
  } catch (err) {
    // Fallback: send as plain text if Markdown parsing fails
    logger.debug({ err }, 'Markdown send failed, falling back to plain text');
    await api.sendMessage(chatId, text, options);
  }
}

export class TelegramChannel implements Channel {
  name = 'telegram';

  private bot: Bot | null = null;
  private opts: TelegramChannelOpts;
  private botToken: string;
  private api: TelegramApi;
  private isUsingWebhook = false;
  private webhookSecretToken: string;
  private pollingFallbackTimer: NodeJS.Timeout | null = null;

  constructor(botToken: string, opts: TelegramChannelOpts) {
    this.botToken = botToken;
    this.opts = opts;
    this.api = new TelegramApi(botToken);
    this.webhookSecretToken =
      WEBHOOK_SECRET_TOKEN || this.generateSecretToken();
  }

  private generateSecretToken(): string {
    return crypto.randomBytes(32).toString('hex');
  }

  private async setupWebhookMode(): Promise<boolean> {
    if (!WEBHOOK_ENABLED || !WEBHOOK_DOMAIN) {
      logger.info(
        'Webhook mode disabled or domain not configured, using polling',
      );
      return false;
    }

    try {
      // Start webhook server if not already running
      if (!webhookServer.isRunning()) {
        await webhookServer.start();
      }

      // Register our handler
      webhookServer.registerHandler(
        'telegram-default',
        this.handleWebhookUpdate.bind(this),
      );

      // Configure webhook with Telegram
      const webhookUrl = webhookServer.getWebhookUrl();

      const certPath = path.join(process.cwd(), 'certs', 'webhook.pem');
      const hasCert = fs.existsSync(certPath);

      if (hasCert) {
        // Self-signed cert needs to be uploaded via multipart form - use a temporary grammY bot instance
        const { Bot, InputFile } = await import('grammy');
        const tempBot = new Bot(this.botToken);
        await tempBot.api.setWebhook(webhookUrl, {
          certificate: new InputFile(certPath),
          secret_token: this.webhookSecretToken,
          max_connections: 40,
          allowed_updates: [
            'message',
            'edited_message',
            'channel_post',
            'edited_channel_post',
          ],
          drop_pending_updates: false,
        });
      } else {
        await this.api.setWebhook({
          url: webhookUrl,
          secret_token: this.webhookSecretToken,
          max_connections: 40,
          allowed_updates: [
            'message',
            'edited_message',
            'channel_post',
            'edited_channel_post',
          ],
          drop_pending_updates: false,
        });
      }

      this.isUsingWebhook = true;
      logger.info({ webhookUrl }, 'Telegram webhook configured successfully');
      return true;
    } catch (err) {
      logger.warn(
        { err },
        'Failed to setup webhook mode, falling back to polling',
      );
      return false;
    }
  }

  private async handleWebhookUpdate(update: WebhookUpdate): Promise<void> {
    try {
      // Convert webhook update to Grammy context-like structure
      if (update.message || update.edited_message) {
        const message = update.message || update.edited_message;
        await this.processMessage(message);
      } else if (update.channel_post || update.edited_channel_post) {
        const message = update.channel_post || update.edited_channel_post;
        await this.processMessage(message);
      }
      // Other update types can be added as needed
    } catch (err) {
      logger.error(
        { err, updateId: update.update_id },
        'Error processing webhook update',
      );
    }
  }

  private async processMessage(message: any): Promise<void> {
    if (!message?.text) {
      // Handle non-text messages
      this.processNonTextMessage(message);
      return;
    }

    const chatJid = `tg:${message.chat.id}`;
    let content = message.text;
    const timestamp = new Date(message.date * 1000).toISOString();
    const senderName =
      message.from?.first_name ||
      message.from?.username ||
      message.from?.id?.toString() ||
      'Unknown';
    const sender = message.from?.id?.toString() || '';
    const msgId = message.message_id.toString();

    // Determine chat name
    const chatName =
      message.chat.type === 'private'
        ? senderName
        : message.chat.title || chatJid;

    // Get bot info for mention handling (cached from Grammy bot)
    if (this.bot?.botInfo?.username) {
      const botUsername = this.bot.botInfo.username.toLowerCase();
      if (message.entities) {
        const isBotMentioned = message.entities.some((entity: any) => {
          if (entity.type === 'mention') {
            const mentionText = content
              .substring(entity.offset, entity.offset + entity.length)
              .toLowerCase();
            return mentionText === `@${botUsername}`;
          }
          return false;
        });
        if (isBotMentioned && !TRIGGER_PATTERN.test(content)) {
          content = `@${ASSISTANT_NAME} ${content}`;
        }
      }
    }

    // Store chat metadata for discovery
    const isGroup =
      message.chat.type === 'group' || message.chat.type === 'supergroup';
    this.opts.onChatMetadata(chatJid, timestamp, chatName, 'telegram', isGroup);

    // Only deliver full message for registered groups
    const group = this.opts.registeredGroups()[chatJid];
    if (!group) {
      logger.debug(
        { chatJid, chatName },
        'Message from unregistered Telegram chat',
      );
      return;
    }

    // Deliver message
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
      'Telegram message processed',
    );
  }

  private async downloadPhoto(
    photoSizes: any[],
    chatJid: string,
  ): Promise<string> {
    if (!this.bot) return '[Photo]';
    try {
      // Get the largest photo size (last in array)
      const largest = photoSizes[photoSizes.length - 1];
      if (!largest || !largest.file_id) return '[Photo]';

      const file = await this.bot.api.getFile(largest.file_id);
      const filePath = file.file_path;
      if (!filePath) return '[Photo]';

      const token = this.botToken;
      const fileUrl = `https://api.telegram.org/file/bot${token}/${filePath}`;

      // Determine which group folder to save to
      const groups = this.opts.registeredGroups();
      const group = groups[chatJid];
      if (!group) return '[Photo]';

      const groupDir = path.join(process.cwd(), 'groups', group.folder);
      const imagesDir = path.join(groupDir, 'images');
      if (!fs.existsSync(imagesDir)) {
        fs.mkdirSync(imagesDir, { recursive: true });
      }

      const ext = filePath.endsWith('.png') ? '.png' : '.jpg';
      const filename = `photo_${Date.now()}${ext}`;
      const localPath = path.join(imagesDir, filename);

      // Download the image
      await new Promise<void>((resolve, reject) => {
        const fileStream = fs.createWriteStream(localPath);
        https
          .get(fileUrl, (response) => {
            response.pipe(fileStream);
            fileStream.on('finish', () => {
              fileStream.close();
              resolve();
            });
          })
          .on('error', reject);
      });

      logger.info({ filename, group: group.folder }, 'Photo downloaded');
      return `[Photo: /workspace/group/images/${filename}]`;
    } catch (err) {
      logger.error({ err }, 'Photo download failed');
      return '[Photo]';
    }
  }

  private async processVideo(fileId: string, chatJid: string): Promise<string> {
    if (!this.bot) return '[Video]';

    try {
      const file = await this.bot.api.getFile(fileId);
      const filePath = file.file_path;
      if (!filePath) return '[Video]';

      const token = this.botToken;
      const fileUrl = `https://api.telegram.org/file/bot${token}/${filePath}`;

      // Determine group folder for saving frames
      const groups = this.opts.registeredGroups();
      const group = groups[chatJid];
      if (!group) return '[Video]';

      const groupDir = path.join(process.cwd(), 'groups', group.folder);
      const imagesDir = path.join(groupDir, 'images');
      if (!fs.existsSync(imagesDir)) {
        fs.mkdirSync(imagesDir, { recursive: true });
      }

      const tmpVideo = path.join(os.tmpdir(), `video_${Date.now()}.mp4`);
      const tmpAudio = path.join(os.tmpdir(), `audio_${Date.now()}.ogg`);

      // Download video
      await new Promise<void>((resolve, reject) => {
        const fileStream = fs.createWriteStream(tmpVideo);
        https
          .get(fileUrl, (response) => {
            response.pipe(fileStream);
            fileStream.on('finish', () => {
              fileStream.close();
              resolve();
            });
          })
          .on('error', reject);
      });

      if (!fs.existsSync(tmpVideo) || fs.statSync(tmpVideo).size < 1000) {
        fs.unlink(tmpVideo, () => {});
        return '[Video - too small to process]';
      }

      const parts: string[] = [];

      // Extract key frames (start, 25%, 50%, 75%)
      const { execFileSync } = await import('child_process');
      try {
        // Get video duration
        const durationStr = execFileSync(
          'ffprobe',
          ['-v', 'quiet', '-show_entries', 'format=duration', '-of', 'csv=p=0', tmpVideo],
          { encoding: 'utf-8', timeout: 10000 },
        ).trim();
        const duration = parseFloat(durationStr) || 10;

        const frameTimestamps = [
          0,
          duration * 0.25,
          duration * 0.5,
          duration * 0.75,
        ];
        const framePaths: string[] = [];

        for (let i = 0; i < frameTimestamps.length; i++) {
          const framePath = path.join(
            imagesDir,
            `video_frame_${Date.now()}_${i}.jpg`,
          );
          try {
            execFileSync(
              'ffmpeg',
              ['-y', '-ss', String(frameTimestamps[i]), '-i', tmpVideo, '-vframes', '1', '-q:v', '3', framePath, '-loglevel', 'error'],
              { timeout: 10000 },
            );
            if (
              fs.existsSync(framePath) &&
              fs.statSync(framePath).size > 1000
            ) {
              framePaths.push(framePath);
            }
          } catch {
            // Skip this frame
          }
        }

        if (framePaths.length > 0) {
          const frameRefs = framePaths.map((fp, i) => {
            const filename = path.basename(fp);
            return `/workspace/group/images/${filename}`;
          });
          parts.push(`[Video frames extracted: ${frameRefs.join(', ')}]`);
          logger.info(
            { frames: framePaths.length, group: group.folder },
            'Video frames extracted',
          );
        }
      } catch (err) {
        logger.warn({ err }, 'Failed to extract video frames');
      }

      // Extract audio and transcribe
      try {
        execFileSync(
          'ffmpeg',
          ['-y', '-i', tmpVideo, '-vn', '-acodec', 'libopus', '-b:a', '48k', tmpAudio, '-loglevel', 'error'],
          { timeout: 30000 },
        );

        if (fs.existsSync(tmpAudio) && fs.statSync(tmpAudio).size > 1000) {
          const transcript = await this.transcribeVoice(tmpAudio, true);
          if (transcript && transcript !== '[Voice message]') {
            parts.push(
              transcript.replace('[Voice message] ', '[Video audio] '),
            );
          }
        }
      } catch (err) {
        logger.warn({ err }, 'Failed to extract video audio');
      }

      // Cleanup temp files
      fs.unlink(tmpVideo, () => {});
      fs.unlink(tmpAudio, () => {});

      if (parts.length > 0) {
        return `[Video] ${parts.join(' ')}`;
      }
      return '[Video - could not process. Please describe what the video shows.]';
    } catch (err) {
      logger.error({ err }, 'Video processing failed');
      return '[Video - processing failed. Please describe what the video shows.]';
    }
  }

  private async transcribeVoice(
    fileIdOrPath: string,
    isLocalFile = false,
  ): Promise<string> {
    const env = readEnvFile(['OPENAI_API_KEY']);
    const openaiKey = env.OPENAI_API_KEY;
    if (!openaiKey) {
      logger.warn('No OPENAI_API_KEY set, skipping voice transcription');
      return '[Voice message]';
    }

    try {
      let tmpFile: string;
      let shouldCleanup: boolean;

      if (isLocalFile) {
        // Audio file already on disk (from video processing)
        tmpFile = fileIdOrPath;
        shouldCleanup = false;
      } else {
        // Download from Telegram
        if (!this.bot) return '[Voice message]';
        const file = await this.bot.api.getFile(fileIdOrPath);
        const filePath = file.file_path;
        if (!filePath) return '[Voice message]';

        const token = this.botToken;
        const fileUrl = `https://api.telegram.org/file/bot${token}/${filePath}`;

        tmpFile = path.join(os.tmpdir(), `voice_${Date.now()}.ogg`);
        shouldCleanup = true;

        await new Promise<void>((resolve, reject) => {
          const fileStream = fs.createWriteStream(tmpFile);
          https
            .get(fileUrl, (response) => {
              response.pipe(fileStream);
              fileStream.on('finish', () => {
                fileStream.close();
                resolve();
              });
            })
            .on('error', reject);
        });
      }

      // Send to OpenAI Whisper API
      const FormData = (await import('form-data')).default;
      const form = new FormData();
      const ext = tmpFile.endsWith('.ogg') ? 'ogg' : 'mp4';
      form.append('file', fs.createReadStream(tmpFile), {
        filename: `audio.${ext}`,
      });
      form.append('model', 'whisper-1');
      form.append('language', 'en');

      const response = await new Promise<string>((resolve, reject) => {
        const req = https.request(
          {
            hostname: 'api.openai.com',
            path: '/v1/audio/transcriptions',
            method: 'POST',
            headers: {
              Authorization: `Bearer ${openaiKey}`,
              ...form.getHeaders(),
            },
          },
          (res) => {
            let data = '';
            res.on('data', (chunk: Buffer) => {
              data += chunk.toString();
            });
            res.on('end', () => resolve(data));
          },
        );
        req.on('error', reject);
        form.pipe(req);
      });

      if (shouldCleanup) fs.unlink(tmpFile, () => {});

      const result = JSON.parse(response);
      if (result.text) {
        logger.info(
          { words: result.text.split(' ').length },
          'Voice message transcribed',
        );
        return `[Voice message] "${result.text}"`;
      }
      return '[Voice message]';
    } catch (err) {
      logger.error({ err }, 'Voice transcription failed');
      return '[Voice message]';
    }
  }

  private async processNonTextMessage(message: any): Promise<void> {
    const chatJid = `tg:${message.chat.id}`;
    const group = this.opts.registeredGroups()[chatJid];
    if (!group) return;

    const timestamp = new Date(message.date * 1000).toISOString();
    const senderName =
      message.from?.first_name ||
      message.from?.username ||
      message.from?.id?.toString() ||
      'Unknown';
    const caption = message.caption ? ` ${message.caption}` : '';

    let placeholder = '[Unknown media]';
    if (message.photo) {
      placeholder = await this.downloadPhoto(message.photo, chatJid);
    } else if (message.video) {
      placeholder = await this.processVideo(message.video.file_id, chatJid);
    } else if (message.video_note) {
      placeholder = await this.processVideo(
        message.video_note.file_id,
        chatJid,
      );
    } else if (message.voice) {
      placeholder = await this.transcribeVoice(message.voice.file_id);
    } else if (message.audio) placeholder = '[Audio]';
    else if (message.document)
      placeholder = `[Document: ${message.document.file_name || 'file'}]`;
    else if (message.sticker)
      placeholder = `[Sticker ${message.sticker.emoji || ''}]`;
    else if (message.location) placeholder = '[Location]';
    else if (message.contact) placeholder = '[Contact]';

    const isGroup =
      message.chat.type === 'group' || message.chat.type === 'supergroup';
    this.opts.onChatMetadata(
      chatJid,
      timestamp,
      undefined,
      'telegram',
      isGroup,
    );

    this.opts.onMessage(chatJid, {
      id: message.message_id.toString(),
      chat_jid: chatJid,
      sender: message.from?.id?.toString() || '',
      sender_name: senderName,
      content: `${placeholder}${caption}`,
      timestamp,
      is_from_me: false,
    });
  }

  private async setupPollingMode(): Promise<void> {
    this.bot = new Bot(this.botToken, {
      client: {
        baseFetchConfig: { agent: https.globalAgent, compress: true },
      },
    });

    // Command to get chat ID (useful for registration)
    this.bot.command('chatid', (ctx) => {
      const chatId = ctx.chat.id;
      const chatType = ctx.chat.type;
      const chatName =
        chatType === 'private'
          ? ctx.from?.first_name || 'Private'
          : (ctx.chat as any).title || 'Unknown';

      ctx.reply(
        `Chat ID: \`tg:${chatId}\`\nName: ${chatName}\nType: ${chatType}`,
        { parse_mode: 'Markdown' },
      );
    });

    // Command to check bot status
    this.bot.command('ping', (ctx) => {
      ctx.reply(`${ASSISTANT_NAME} is online.`);
    });

    // Telegram bot commands handled above — skip them in the general handler
    const TELEGRAM_BOT_COMMANDS = new Set(['chatid', 'ping']);

    this.bot.on('message:text', async (ctx) => {
      if (ctx.message.text.startsWith('/')) {
        const cmd = ctx.message.text.slice(1).split(/[\s@]/)[0].toLowerCase();
        if (TELEGRAM_BOT_COMMANDS.has(cmd)) return;
      }

      await this.processMessage(ctx.message);
    });

    // Handle non-text messages
    this.bot.on('message:photo', (ctx) =>
      this.processNonTextMessage(ctx.message),
    );
    this.bot.on('message:video', (ctx) =>
      this.processNonTextMessage(ctx.message),
    );
    this.bot.on('message:voice', (ctx) =>
      this.processNonTextMessage(ctx.message),
    );
    this.bot.on('message:audio', (ctx) =>
      this.processNonTextMessage(ctx.message),
    );
    this.bot.on('message:document', (ctx) =>
      this.processNonTextMessage(ctx.message),
    );
    this.bot.on('message:sticker', (ctx) =>
      this.processNonTextMessage(ctx.message),
    );
    this.bot.on('message:location', (ctx) =>
      this.processNonTextMessage(ctx.message),
    );
    this.bot.on('message:contact', (ctx) =>
      this.processNonTextMessage(ctx.message),
    );

    // Handle errors gracefully
    this.bot.catch((err) => {
      logger.error({ err: err.message }, 'Telegram bot error');
    });

    logger.info('Telegram polling mode configured');
  }

  private startPollingFallback(): void {
    if (this.pollingFallbackTimer) return;

    // Monitor webhook health and fallback to polling if needed
    this.pollingFallbackTimer = setInterval(async () => {
      try {
        if (this.isUsingWebhook) {
          const webhookInfo = await this.api.getWebhookInfo();

          // Check for webhook errors
          if (webhookInfo.last_error_message) {
            const errorAge =
              Date.now() - (webhookInfo.last_error_date || 0) * 1000;
            if (errorAge < 300000) {
              // Recent error (< 5 minutes)
              logger.warn(
                {
                  error: webhookInfo.last_error_message,
                  errorAge: Math.round(errorAge / 1000),
                },
                'Webhook has recent errors, considering fallback to polling',
              );

              // If we have multiple recent errors, fallback
              if (webhookInfo.pending_update_count > 100) {
                await this.fallbackToPolling(
                  'High pending update count with errors',
                );
              }
            }
          }
        }
      } catch (err) {
        logger.error({ err }, 'Error checking webhook health');
      }
    }, 60000); // Check every minute
  }

  private async fallbackToPolling(reason: string): Promise<void> {
    if (!this.isUsingWebhook) return;

    logger.warn({ reason }, 'Falling back to polling mode');

    try {
      // Remove webhook
      await this.api.deleteWebhook(false);
      webhookServer.unregisterHandler('telegram-default');

      this.isUsingWebhook = false;

      // Start polling if not already set up
      if (!this.bot) {
        await this.setupPollingMode();
      }

      // Start polling
      await this.startPolling();

      logger.info('Successfully fell back to polling mode');
    } catch (err) {
      logger.error({ err }, 'Error during fallback to polling');
    }
  }

  private async startPolling(): Promise<void> {
    if (!this.bot) return;

    return new Promise<void>((resolve) => {
      this.bot!.start({
        onStart: (botInfo) => {
          logger.info(
            { username: botInfo.username, id: botInfo.id, mode: 'polling' },
            'Telegram bot connected',
          );
          console.log(`\n  Telegram bot: @${botInfo.username} (polling mode)`);
          console.log(
            `  Send /chatid to the bot to get a chat's registration ID\n`,
          );
          resolve();
        },
      });
    });
  }

  async connect(): Promise<void> {
    // Try webhook mode first, fallback to polling if it fails
    const webhookSuccess = await this.setupWebhookMode();

    if (webhookSuccess) {
      // Still need to create the bot instance for API operations and info
      this.bot = new Bot(this.botToken, {
        client: {
          baseFetchConfig: { agent: https.globalAgent, compress: true },
        },
      });

      // Get bot info for webhook processing
      try {
        const botInfo = await this.api.getMe();
        if (this.bot) {
          (this.bot as any).botInfo = botInfo; // Store for mention processing
        }

        logger.info(
          { username: botInfo.username, id: botInfo.id, mode: 'webhook' },
          'Telegram bot connected',
        );
        console.log(`\n  Telegram bot: @${botInfo.username} (webhook mode)`);
        console.log(`  Webhook URL: ${webhookServer.getWebhookUrl()}\n`);
      } catch (err) {
        logger.error({ err }, 'Failed to get bot info for webhook mode');
        throw err;
      }

      // Start health monitoring
      this.startPollingFallback();
    } else {
      // Fallback to polling mode
      await this.setupPollingMode();
      await this.startPolling();
    }
  }

  async sendMessage(jid: string, text: string): Promise<void> {
    if (!this.bot) {
      logger.warn('Telegram bot not initialized');
      return;
    }

    try {
      const numericId = jid.replace(/^tg:/, '');

      // Telegram has a 4096 character limit per message — split if needed
      const MAX_LENGTH = 4096;
      if (text.length <= MAX_LENGTH) {
        await sendTelegramMessage(this.bot.api, numericId, text);
      } else {
        for (let i = 0; i < text.length; i += MAX_LENGTH) {
          await sendTelegramMessage(
            this.bot.api,
            numericId,
            text.slice(i, i + MAX_LENGTH),
          );
        }
      }
      logger.info({ jid, length: text.length }, 'Telegram message sent');
    } catch (err) {
      logger.error({ jid, err }, 'Failed to send Telegram message');
    }
  }

  isConnected(): boolean {
    return this.bot !== null;
  }

  ownsJid(jid: string): boolean {
    return jid.startsWith('tg:');
  }

  async disconnect(): Promise<void> {
    // Clean up polling fallback timer
    if (this.pollingFallbackTimer) {
      clearInterval(this.pollingFallbackTimer);
      this.pollingFallbackTimer = null;
    }

    // Clean up webhook mode
    if (this.isUsingWebhook) {
      try {
        webhookServer.unregisterHandler('telegram-default');
        // Note: We don't delete the webhook here as it might be used by other instances
        // Webhook deletion should be done manually or during server shutdown
      } catch (err) {
        logger.warn({ err }, 'Error cleaning up webhook during disconnect');
      }
    }

    // Stop polling mode
    if (this.bot) {
      this.bot.stop();
      this.bot = null;
    }

    // Clean up API client
    this.api.destroy();

    logger.info(
      {
        mode: this.isUsingWebhook ? 'webhook' : 'polling',
      },
      'Telegram bot disconnected',
    );
  }

  async setTyping(jid: string, isTyping: boolean): Promise<void> {
    if (!this.bot || !isTyping) return;
    try {
      const numericId = jid.replace(/^tg:/, '');
      await this.bot.api.sendChatAction(numericId, 'typing');
    } catch (err) {
      logger.debug({ jid, err }, 'Failed to send Telegram typing indicator');
    }
  }
}

registerChannel('telegram', (opts: ChannelOpts) => {
  const envVars = readEnvFile(['TELEGRAM_BOT_TOKEN']);
  const token =
    process.env.TELEGRAM_BOT_TOKEN || envVars.TELEGRAM_BOT_TOKEN || '';
  if (!token) {
    logger.warn('Telegram: TELEGRAM_BOT_TOKEN not set');
    return null;
  }
  return new TelegramChannel(token, opts);
});
