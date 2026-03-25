import fetch from 'node-fetch';
import https from 'https';

import { logger } from './logger.js';

export interface TelegramWebhookInfo {
  url: string;
  has_custom_certificate: boolean;
  pending_update_count: number;
  ip_address?: string;
  last_error_date?: number;
  last_error_message?: string;
  last_synchronization_error_date?: number;
  max_connections?: number;
  allowed_updates?: string[];
}

export interface TelegramSetWebhookParams {
  url: string;
  certificate?: string;
  ip_address?: string;
  max_connections?: number;
  allowed_updates?: string[];
  drop_pending_updates?: boolean;
  secret_token?: string;
}

export class TelegramApi {
  private baseUrl: string;
  private agent: https.Agent;

  constructor(private botToken: string) {
    this.baseUrl = `https://api.telegram.org/bot${botToken}`;

    // Configure HTTPS agent for keep-alive and performance
    this.agent = new https.Agent({
      keepAlive: true,
      keepAliveMsecs: 30000,
      maxSockets: 10,
      maxFreeSockets: 5,
      timeout: 30000,
    });
  }

  private async makeRequest<T>(method: string, params?: Record<string, any>): Promise<T> {
    const url = `${this.baseUrl}/${method}`;

    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 30000);

      try {
        const response = await fetch(url, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: params ? JSON.stringify(params) : undefined,
          agent: this.agent,
          signal: controller.signal,
        });
        clearTimeout(timeoutId);

        if (!response.ok) {
          const errorText = await response.text();
          throw new Error(`Telegram API error (${response.status}): ${errorText}`);
        }

        const result = await response.json() as { ok: boolean; result: T; description?: string };

        if (!result.ok) {
          throw new Error(`Telegram API error: ${result.description || 'Unknown error'}`);
        }

        return result.result;

      } catch (err) {
        clearTimeout(timeoutId);
        throw err;
      }

    } catch (err) {
      logger.error({
        method,
        url,
        err: err instanceof Error ? err.message : String(err)
      }, 'Telegram API request failed');
      throw err;
    }
  }

  public async setWebhook(params: TelegramSetWebhookParams): Promise<boolean> {
    logger.info({
      url: params.url,
      maxConnections: params.max_connections,
      hasSecretToken: !!params.secret_token
    }, 'Setting Telegram webhook');

    try {
      const result = await this.makeRequest<boolean>('setWebhook', params);

      logger.info({ url: params.url }, 'Telegram webhook set successfully');
      return result;

    } catch (err) {
      logger.error({ err, params }, 'Failed to set Telegram webhook');
      throw err;
    }
  }

  public async deleteWebhook(dropPendingUpdates = false): Promise<boolean> {
    logger.info({ dropPendingUpdates }, 'Deleting Telegram webhook');

    try {
      const result = await this.makeRequest<boolean>('deleteWebhook', {
        drop_pending_updates: dropPendingUpdates,
      });

      logger.info('Telegram webhook deleted successfully');
      return result;

    } catch (err) {
      logger.error({ err }, 'Failed to delete Telegram webhook');
      throw err;
    }
  }

  public async getWebhookInfo(): Promise<TelegramWebhookInfo> {
    try {
      const result = await this.makeRequest<TelegramWebhookInfo>('getWebhookInfo');

      logger.debug({
        url: result.url,
        pendingCount: result.pending_update_count,
        lastError: result.last_error_message
      }, 'Webhook info retrieved');

      return result;

    } catch (err) {
      logger.error({ err }, 'Failed to get webhook info');
      throw err;
    }
  }

  public async getUpdates(offset?: number, limit = 100, timeout = 0): Promise<any[]> {
    try {
      const result = await this.makeRequest<any[]>('getUpdates', {
        offset,
        limit,
        timeout,
      });

      return result;

    } catch (err) {
      logger.error({ err, offset, limit, timeout }, 'Failed to get updates');
      throw err;
    }
  }

  public async getMe(): Promise<any> {
    try {
      return await this.makeRequest('getMe');
    } catch (err) {
      logger.error({ err }, 'Failed to get bot info');
      throw err;
    }
  }

  public destroy(): void {
    this.agent.destroy();
  }
}