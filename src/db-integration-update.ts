/**
 * Database Integration Update - Phase 1.1
 *
 * This file contains the integration patches to apply the optimized database features
 * to the main db.ts file while maintaining backward compatibility.
 */

import Database from 'better-sqlite3';
import path from 'path';
import crypto from 'crypto';
import { STORE_DIR, ASSISTANT_NAME } from './config.js';
import { logger } from './logger.js';

// Database Connection Pool
interface DatabaseConnection {
  db: Database.Database;
  lastUsed: number;
  inUse: boolean;
  refCount: number;
}

class OptimizedDatabaseService {
  private connections: Map<string, DatabaseConnection> = new Map();
  private maxConnections = 10;
  private connectionTimeout = 30000; // 30 seconds
  private cleanupInterval: NodeJS.Timeout | null = null;

  constructor() {
    // Start connection cleanup interval
    this.cleanupInterval = setInterval(() => {
      this.cleanupConnections();
    }, 10000); // Every 10 seconds

    // Graceful shutdown
    process.on('SIGINT', () => this.closeAllConnections());
    process.on('SIGTERM', () => this.closeAllConnections());
  }

  /**
   * Get or create optimized database connection
   */
  getConnection(dbPath: string, readOnly = false): Database.Database {
    const connectionKey = `${dbPath}:${readOnly ? 'ro' : 'rw'}`;
    let connection = this.connections.get(connectionKey);

    if (!connection || connection.db.open === false) {
      // Create new connection with optimizations
      const db = new Database(dbPath, {
        readonly: readOnly,
        fileMustExist: false,
      });

      // Apply Phase 1.1 optimizations
      if (!readOnly) {
        this.applyOptimizations(db);
      }

      connection = {
        db,
        lastUsed: Date.now(),
        inUse: false,
        refCount: 0,
      };

      this.connections.set(connectionKey, connection);
      logger.info(
        { dbPath, readOnly },
        'Created optimized database connection',
      );
    }

    // Update usage tracking
    connection.lastUsed = Date.now();
    connection.refCount++;

    return connection.db;
  }

  /**
   * Apply Phase 1.1 database optimizations
   */
  private applyOptimizations(db: Database.Database): void {
    try {
      // Enable WAL mode for better concurrency
      db.pragma('journal_mode = WAL');

      // Performance optimizations
      db.pragma('synchronous = NORMAL'); // Balance safety and performance
      db.pragma('cache_size = -4000'); // 4MB cache
      db.pragma('temp_store = MEMORY');
      db.pragma('mmap_size = 268435456'); // 256MB memory-mapped I/O
      db.pragma('optimize'); // Auto-optimize query planner

      logger.debug('Applied database optimizations including WAL mode');
    } catch (error) {
      logger.warn({ error }, 'Failed to apply some database optimizations');
    }
  }

  /**
   * Calculate message processing priority based on content
   */
  calculateMessagePriority(
    content: string | null | undefined,
    chatJid: string,
  ): number {
    let priority = 5; // Default priority

    if (!content) return priority;

    // Higher priority for direct mentions or questions
    if (
      content.includes('?') ||
      content.toLowerCase().includes(ASSISTANT_NAME.toLowerCase())
    ) {
      priority += 2;
    }

    // Higher priority for urgent keywords
    if (/\b(urgent|asap|important|help|error|failed)\b/i.test(content)) {
      priority += 2;
    }

    // Higher priority for shorter messages (likely more urgent)
    if (content.length < 100) {
      priority += 1;
    }

    // Lower priority for very long messages
    if (content.length > 1000) {
      priority -= 1;
    }

    // Higher priority for non-group chats (direct messages)
    if (!chatJid.includes('@g.us') && !chatJid.includes('tg:')) {
      priority += 1;
    }

    // Higher priority for sales/business related content
    if (/\$[\d,]+|premium|commission|sale|closed|deal/i.test(content)) {
      priority += 1;
    }

    return Math.max(1, Math.min(10, priority));
  }

  /**
   * Generate content hash for deduplication
   */
  generateContentHash(content: string | null | undefined): string | null {
    if (!content || content.trim() === '') return null;

    // Normalize content for hashing (remove extra whitespace, normalize case)
    const normalized = content.trim().toLowerCase().replace(/\s+/g, ' ');
    return crypto.createHash('md5').update(normalized).digest('hex');
  }

  /**
   * Enhanced message storage with performance features
   */
  storeEnhancedMessage(
    db: Database.Database,
    id: string,
    chatJid: string,
    sender: string,
    senderName: string,
    content: string,
    timestamp: string,
    isFromMe: boolean,
    isBotMessage: boolean,
  ): void {
    const priority = this.calculateMessagePriority(content, chatJid);
    const contentHash = this.generateContentHash(content);
    const isContentTruncated = content && content.length > 10000;

    const metadata = JSON.stringify({
      original_length: content?.length || 0,
      channel: this.detectChannel(chatJid),
      has_urls: /https?:\/\//.test(content || ''),
      has_mentions: /@/.test(content || ''),
      processed_at: new Date().toISOString(),
    });

    try {
      db.prepare(
        `
        INSERT OR REPLACE INTO messages (
          id, chat_jid, sender, sender_name, content, timestamp,
          is_from_me, is_bot_message, processing_priority, content_hash,
          content_truncated, metadata
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `,
      ).run(
        id,
        chatJid,
        sender,
        senderName,
        isContentTruncated ? content.substring(0, 10000) : content,
        timestamp,
        isFromMe ? 1 : 0,
        isBotMessage ? 1 : 0,
        priority,
        contentHash,
        isContentTruncated ? 1 : 0,
        metadata,
      );

      logger.debug(
        { chatJid, priority, hasHash: !!contentHash },
        'Stored enhanced message',
      );
    } catch (error) {
      // Fallback to standard message storage for backward compatibility
      logger.warn(
        { error },
        'Enhanced message storage failed, using standard method',
      );

      db.prepare(
        `
        INSERT OR REPLACE INTO messages (
          id, chat_jid, sender, sender_name, content, timestamp, is_from_me, is_bot_message
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
      `,
      ).run(
        id,
        chatJid,
        sender,
        senderName,
        content,
        timestamp,
        isFromMe ? 1 : 0,
        isBotMessage ? 1 : 0,
      );
    }
  }

  /**
   * Enhanced message retrieval with priority filtering
   */
  getEnhancedMessages(
    db: Database.Database,
    jids: string[],
    lastTimestamp: string,
    botPrefix: string,
    limit: number = 200,
    minPriority?: number,
  ): {
    id: string;
    chat_jid: string;
    sender: string;
    sender_name: string;
    content: string;
    timestamp: string;
    is_from_me: boolean;
    processing_priority?: number;
  }[] {
    if (jids.length === 0) return [];

    const placeholders = jids.map(() => '?').join(',');
    let sql = `
      SELECT * FROM (
        SELECT id, chat_jid, sender, sender_name, content, timestamp, is_from_me,
               processing_priority, content_hash, metadata
        FROM messages
        WHERE timestamp > ? AND chat_jid IN (${placeholders})
          AND is_bot_message = 0 AND content NOT LIKE ?
          AND content != '' AND content IS NOT NULL
    `;

    const params: (string | number)[] = [lastTimestamp, ...jids, `${botPrefix}:%`];

    // Add priority filter if specified
    if (minPriority !== undefined) {
      sql += ' AND processing_priority >= ?';
      params.push(minPriority);
    }

    sql += `
        ORDER BY processing_priority DESC, timestamp DESC
        Limit ?
      ) ORDER BY timestamp
    `;
    params.push(limit);

    type EnhancedRow = {
      id: string;
      chat_jid: string;
      sender: string;
      sender_name: string;
      content: string;
      timestamp: string;
      is_from_me: boolean;
      processing_priority?: number;
    };

    try {
      return db.prepare(sql).all(...params) as EnhancedRow[];
    } catch (error) {
      // Fallback to standard query if enhanced columns don't exist
      logger.debug('Enhanced query failed, falling back to standard query');

      const fallbackSql = `
        SELECT * FROM (
          SELECT id, chat_jid, sender, sender_name, content, timestamp, is_from_me
          FROM messages
          WHERE timestamp > ? AND chat_jid IN (${placeholders})
            AND is_bot_message = 0 AND content NOT LIKE ?
            AND content != '' AND content IS NOT NULL
          ORDER BY timestamp DESC
          LIMIT ?
        ) ORDER BY timestamp
      `;

      return db
        .prepare(fallbackSql)
        .all(lastTimestamp, ...jids, `${botPrefix}:%`, limit) as EnhancedRow[];
    }
  }

  /**
   * Detect channel from JID pattern
   */
  private detectChannel(chatJid: string): string {
    if (chatJid.includes('@g.us') || chatJid.includes('@s.whatsapp.net')) {
      return 'whatsapp';
    }
    if (chatJid.includes('dc:')) {
      return 'discord';
    }
    if (chatJid.includes('tg:')) {
      return 'telegram';
    }
    if (chatJid.includes('@gmail.com') || chatJid.includes('@')) {
      return 'email';
    }
    return 'unknown';
  }

  /**
   * Clean up unused connections
   */
  private cleanupConnections(): void {
    const now = Date.now();

    for (const [key, connection] of this.connections.entries()) {
      if (
        !connection.inUse &&
        connection.refCount === 0 &&
        now - connection.lastUsed > this.connectionTimeout
      ) {
        try {
          connection.db.close();
          this.connections.delete(key);
          logger.debug(
            { connectionKey: key },
            'Cleaned up idle database connection',
          );
        } catch (error) {
          logger.warn(
            { connectionKey: key, error },
            'Error cleaning up database connection',
          );
        }
      }
    }
  }

  /**
   * Close all database connections
   */
  closeAllConnections(): void {
    if (this.cleanupInterval) {
      clearInterval(this.cleanupInterval);
    }

    for (const [key, connection] of this.connections.entries()) {
      try {
        connection.db.close();
        logger.debug({ connectionKey: key }, 'Closed database connection');
      } catch (error) {
        logger.warn(
          { connectionKey: key, error },
          'Error closing database connection',
        );
      }
    }

    this.connections.clear();
    logger.info('All database connections closed');
  }

  /**
   * Run database optimization
   */
  optimizeDatabase(dbPath?: string): void {
    const targetPath = dbPath || path.join(STORE_DIR, 'messages.db');
    const db = this.getConnection(targetPath);

    try {
      // Analyze query planner statistics
      db.pragma('optimize');

      // Update table statistics
      db.exec('ANALYZE');

      // Check fragmentation
      const fragInfo = db.prepare('PRAGMA freelist_count').get() as any;
      const pageCount = db.prepare('PRAGMA page_count').get() as any;

      if (fragInfo && pageCount) {
        const fragmentation =
          (fragInfo['freelist_count'] / pageCount['page_count']) * 100;

        // Auto-vacuum if fragmentation is high
        if (fragmentation > 25) {
          logger.info(
            { fragmentation },
            'Running auto-vacuum due to high fragmentation',
          );
          db.exec('VACUUM');
        }

        logger.info(
          { fragmentation: fragmentation.toFixed(2) },
          'Database optimization completed',
        );
      }
    } catch (error) {
      logger.warn({ error }, 'Database optimization failed');
    }
  }
}

// Export singleton instance
export const dbService = new OptimizedDatabaseService();

// Enhanced database functions that can be used as drop-in replacements
export function getOptimizedConnection(dbPath?: string): Database.Database {
  const targetPath = dbPath || path.join(STORE_DIR, 'messages.db');
  return dbService.getConnection(targetPath);
}

export function storeMessageWithOptimizations(
  id: string,
  chatJid: string,
  sender: string,
  senderName: string,
  content: string,
  timestamp: string,
  isFromMe: boolean,
  isBotMessage: boolean,
  dbPath?: string,
): void {
  const targetPath = dbPath || path.join(STORE_DIR, 'messages.db');
  const db = dbService.getConnection(targetPath);

  dbService.storeEnhancedMessage(
    db,
    id,
    chatJid,
    sender,
    senderName,
    content,
    timestamp,
    isFromMe,
    isBotMessage,
  );
}

export function getMessagesWithPriority(
  jids: string[],
  lastTimestamp: string,
  botPrefix: string,
  limit: number = 200,
  minPriority?: number,
  dbPath?: string,
): { messages: any[]; newTimestamp: string } {
  const targetPath = dbPath || path.join(STORE_DIR, 'messages.db');
  const db = dbService.getConnection(targetPath);

  const messages = dbService.getEnhancedMessages(
    db,
    jids,
    lastTimestamp,
    botPrefix,
    limit,
    minPriority,
  );

  let newTimestamp = lastTimestamp;
  for (const message of messages) {
    if (message.timestamp > newTimestamp) {
      newTimestamp = message.timestamp;
    }
  }

  return { messages, newTimestamp };
}

export function optimizeMainDatabase(): void {
  dbService.optimizeDatabase();
}

export function closeAllDatabaseConnections(): void {
  dbService.closeAllConnections();
}
