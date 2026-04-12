import crypto from 'crypto';
import express from 'express';
import fs from 'fs';
import helmet from 'helmet';
import http from 'http';
import https from 'https';
import path from 'path';

import {
  HTTP3_ENABLED,
  WEBHOOK_DOMAIN,
  WEBHOOK_MAX_CONNECTIONS,
  WEBHOOK_PATH,
  WEBHOOK_PORT,
  WEBHOOK_RATE_LIMIT,
  WEBHOOK_SECRET_TOKEN,
} from './config.js';
import { logger } from './logger.js';

export interface WebhookUpdate {
  update_id: number;
  message?: any;
  edited_message?: any;
  channel_post?: any;
  edited_channel_post?: any;
  inline_query?: any;
  chosen_inline_result?: any;
  callback_query?: any;
  shipping_query?: any;
  pre_checkout_query?: any;
  poll?: any;
  poll_answer?: any;
  my_chat_member?: any;
  chat_member?: any;
  chat_join_request?: any;
}

export type WebhookHandler = (update: WebhookUpdate) => Promise<void>;

interface RateLimitEntry {
  count: number;
  resetTime: number;
}

export class WebhookServer {
  private app: express.Application;
  private server: http.Server | https.Server | null = null;
  private handlers: Map<string, WebhookHandler> = new Map();
  private rateLimiter: Map<string, RateLimitEntry> = new Map();
  private secretToken: string;
  private isShuttingDown = false;

  constructor(secretToken: string = WEBHOOK_SECRET_TOKEN) {
    this.app = express();
    this.secretToken = secretToken;
    this.setupMiddleware();
    this.setupRoutes();
    this.startRateLimitCleanup();
  }

  private setupMiddleware(): void {
    // Security middleware
    this.app.use(
      helmet({
        contentSecurityPolicy: false, // Webhook doesn't need CSP
      }),
    );

    // Rate limiting middleware
    this.app.use((req, res, next) => {
      const clientIp = req.ip || req.socket.remoteAddress || 'unknown';

      if (!this.isRateLimited(clientIp)) {
        next();
      } else {
        logger.warn({ clientIp }, 'Webhook rate limit exceeded');
        res.status(429).json({ error: 'Rate limit exceeded' });
      }
    });

    // Body parsing with size limit
    this.app.use(express.json({ limit: '10mb' }));
    this.app.use(express.raw({ limit: '10mb', type: 'application/json' }));
  }

  private setupRoutes(): void {
    // Health check endpoint
    this.app.get('/health', (req, res) => {
      res.json({
        status: 'ok',
        timestamp: new Date().toISOString(),
        uptime: process.uptime(),
      });
    });

    // Main webhook endpoint
    this.app.post(WEBHOOK_PATH, (req, res) => {
      this.handleWebhook(req, res).catch((err) => {
        logger.error({ err }, 'Webhook handler error');
        if (!res.headersSent) {
          res.status(500).json({ error: 'Internal server error' });
        }
      });
    });

    // Catch-all for invalid routes
    this.app.use('*', (req, res) => {
      res.status(404).json({ error: 'Not found' });
    });
  }

  private async handleWebhook(
    req: express.Request,
    res: express.Response,
  ): Promise<void> {
    try {
      // Verify secret token if configured
      if (this.secretToken) {
        const providedToken = req.header('X-Telegram-Bot-Api-Secret-Token');
        if (!providedToken || providedToken !== this.secretToken) {
          logger.warn({ providedToken }, 'Invalid webhook secret token');
          res.status(401).json({ error: 'Unauthorized' });
          return;
        }
      }

      // Parse update
      const update: WebhookUpdate = req.body;
      if (!update || typeof update.update_id !== 'number') {
        logger.warn({ body: req.body }, 'Invalid webhook update format');
        res.status(400).json({ error: 'Invalid update format' });
        return;
      }

      // Determine handler key (can be extended for multi-bot support)
      const handlerKey = 'telegram-default';
      const handler = this.handlers.get(handlerKey);

      if (!handler) {
        logger.warn({ handlerKey }, 'No handler registered for webhook');
        res.status(200).json({ ok: true }); // Return 200 to avoid Telegram retries
        return;
      }

      // Process update asynchronously
      setImmediate(() => {
        handler(update).catch((err) => {
          logger.error(
            { err, updateId: update.update_id },
            'Handler processing error',
          );
        });
      });

      // Respond immediately to Telegram
      res.status(200).json({ ok: true });
    } catch (err) {
      logger.error({ err }, 'Webhook processing error');
      res.status(500).json({ error: 'Internal server error' });
    }
  }

  private isRateLimited(clientIp: string): boolean {
    const now = Date.now();
    const windowMs = 60 * 1000; // 1 minute

    const entry = this.rateLimiter.get(clientIp);
    if (!entry) {
      this.rateLimiter.set(clientIp, { count: 1, resetTime: now + windowMs });
      return false;
    }

    if (now > entry.resetTime) {
      // Reset window
      this.rateLimiter.set(clientIp, { count: 1, resetTime: now + windowMs });
      return false;
    }

    entry.count++;
    return entry.count > WEBHOOK_RATE_LIMIT;
  }

  private startRateLimitCleanup(): void {
    // Clean up expired rate limit entries every 5 minutes
    setInterval(
      () => {
        const now = Date.now();
        const entries = Array.from(this.rateLimiter.entries());
        for (const [ip, entry] of entries) {
          if (now > entry.resetTime) {
            this.rateLimiter.delete(ip);
          }
        }
      },
      5 * 60 * 1000,
    );
  }

  public registerHandler(key: string, handler: WebhookHandler): void {
    this.handlers.set(key, handler);
    logger.info({ key }, 'Webhook handler registered');
  }

  public unregisterHandler(key: string): void {
    this.handlers.delete(key);
    logger.info({ key }, 'Webhook handler unregistered');
  }

  public async start(): Promise<void> {
    if (this.server) {
      logger.warn('Webhook server already running');
      return;
    }

    return new Promise((resolve, reject) => {
      try {
        // Create server with appropriate protocol
        if (HTTP3_ENABLED) {
          // HTTP/3 support would require additional dependencies and certificates
          // For now, fall back to HTTP/2 with HTTP/1.1 compatibility
          logger.info('HTTP/3 requested but falling back to HTTP/2');
        }

        // Check for SSL certificates — if present, use HTTPS (required for Telegram webhooks)
        const certDir = path.join(process.cwd(), 'certs');
        const certPath = path.join(certDir, 'webhook.pem');
        const keyPath = path.join(certDir, 'webhook.key');
        if (fs.existsSync(certPath) && fs.existsSync(keyPath)) {
          logger.info({ certPath }, 'Starting webhook server with HTTPS');
          this.server = https.createServer(
            {
              cert: fs.readFileSync(certPath),
              key: fs.readFileSync(keyPath),
            },
            this.app,
          );
        } else {
          this.server = http.createServer(this.app);
        }

        // Configure server settings for performance
        this.server.maxConnections = WEBHOOK_MAX_CONNECTIONS;
        this.server.keepAliveTimeout = 65000; // Slightly higher than typical load balancer timeout
        this.server.headersTimeout = 66000; // Higher than keepAliveTimeout

        this.server.listen(WEBHOOK_PORT, () => {
          logger.info(
            {
              port: WEBHOOK_PORT,
              path: WEBHOOK_PATH,
              maxConnections: WEBHOOK_MAX_CONNECTIONS,
              rateLimit: WEBHOOK_RATE_LIMIT,
            },
            'Webhook server started',
          );
          resolve();
        });

        this.server.on('error', (err) => {
          logger.error({ err }, 'Webhook server error');
          reject(err);
        });

        // Graceful shutdown handling
        this.server.on('close', () => {
          logger.info('Webhook server closed');
        });
      } catch (err) {
        reject(err);
      }
    });
  }

  public async stop(): Promise<void> {
    if (!this.server) {
      return;
    }

    this.isShuttingDown = true;

    return new Promise((resolve) => {
      this.server!.close(() => {
        this.server = null;
        this.isShuttingDown = false;
        resolve();
      });
    });
  }

  public isRunning(): boolean {
    return this.server !== null && !this.isShuttingDown;
  }

  public getWebhookUrl(): string {
    if (!WEBHOOK_DOMAIN) {
      throw new Error('WEBHOOK_DOMAIN not configured');
    }
    // If certs exist, use HTTPS. Telegram webhooks require HTTPS.
    const certDir = path.join(process.cwd(), 'certs');
    const hasCerts = fs.existsSync(path.join(certDir, 'webhook.pem'));
    const protocol = hasCerts ? 'https' : 'http';
    // WEBHOOK_DOMAIN may or may not include port. Use it as-is.
    return `${protocol}://${WEBHOOK_DOMAIN}${WEBHOOK_PATH}`;
  }
}

export const webhookServer = new WebhookServer();
