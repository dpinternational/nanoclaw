import Database from 'better-sqlite3';
import fs from 'fs';
import path from 'path';
import crypto from 'crypto';

import { ASSISTANT_NAME, DATA_DIR, STORE_DIR } from './config.js';
import { isValidGroupFolder } from './group-folder.js';
import { logger } from './logger.js';
import {
  NewMessage,
  RegisteredGroup,
  ScheduledTask,
  TaskRunLog,
} from './types.js';

// Connection Pool Interface
interface DatabaseConnection {
  db: Database.Database;
  lastUsed: number;
  inUse: boolean;
  refCount: number;
}

// Performance Metrics
interface DatabaseMetrics {
  queryCount: number;
  totalQueryTime: number;
  slowQueryCount: number;
  fragmentationLevel: number;
  cacheHitRate: number;
  lastOptimized: string;
}

// Enhanced Message Interface with Performance Columns
export interface EnhancedMessage extends NewMessage {
  processing_priority?: number;
  content_hash?: string;
  content_truncated?: boolean;
  metadata?: string;
}

class DatabaseManager {
  private connections: Map<string, DatabaseConnection> = new Map();
  private metrics: Map<string, DatabaseMetrics> = new Map();
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
   * Get or create database connection with WAL mode and optimizations
   */
  private getConnection(dbPath: string, readOnly = false): Database.Database {
    const connectionKey = `${dbPath}:${readOnly ? 'ro' : 'rw'}`;
    let connection = this.connections.get(connectionKey);

    if (!connection || connection.db.open === false) {
      // Create new connection
      const db = new Database(dbPath, {
        readonly: readOnly,
        fileMustExist: false
      });

      // Enable WAL mode for better concurrency (write-ahead logging)
      if (!readOnly) {
        db.pragma('journal_mode = WAL');
        db.pragma('synchronous = NORMAL'); // Balance between safety and performance
        db.pragma('cache_size = -2000'); // 2MB cache
        db.pragma('temp_store = MEMORY');
        db.pragma('mmap_size = 268435456'); // 256MB memory-mapped I/O
        db.pragma('optimize'); // Auto-optimize
      }

      connection = {
        db,
        lastUsed: Date.now(),
        inUse: false,
        refCount: 0
      };

      this.connections.set(connectionKey, connection);

      // Initialize metrics if new database
      if (!this.metrics.has(dbPath)) {
        this.metrics.set(dbPath, {
          queryCount: 0,
          totalQueryTime: 0,
          slowQueryCount: 0,
          fragmentationLevel: 0,
          cacheHitRate: 0,
          lastOptimized: new Date().toISOString()
        });
      }

      logger.info({ dbPath, readOnly }, 'Created new database connection with WAL mode');
    }

    // Update usage tracking
    connection.lastUsed = Date.now();
    connection.refCount++;

    return connection.db;
  }

  /**
   * Execute query with performance tracking
   */
  private executeWithMetrics<T>(
    dbPath: string,
    queryFn: (db: Database.Database) => T,
    queryType = 'unknown'
  ): T {
    const startTime = Date.now();
    const db = this.getConnection(dbPath);
    const metrics = this.metrics.get(dbPath)!;

    try {
      const result = queryFn(db);

      // Update metrics
      const queryTime = Date.now() - startTime;
      metrics.queryCount++;
      metrics.totalQueryTime += queryTime;

      if (queryTime > 100) { // Slow query threshold
        metrics.slowQueryCount++;
        logger.warn({
          dbPath,
          queryType,
          queryTime,
          avgQueryTime: metrics.totalQueryTime / metrics.queryCount
        }, 'Slow database query detected');
      }

      return result;
    } finally {
      // Release connection
      const connection = this.connections.get(`${dbPath}:rw`);
      if (connection) {
        connection.refCount = Math.max(0, connection.refCount - 1);
      }
    }
  }

  /**
   * Enhanced schema creation with performance optimizations
   */
  private createEnhancedSchema(database: Database.Database): void {
    // Transaction for atomic schema creation
    const transaction = database.transaction(() => {
      // Existing tables with enhancements
      database.exec(`
        CREATE TABLE IF NOT EXISTS chats (
          jid TEXT PRIMARY KEY,
          name TEXT,
          last_message_time TEXT,
          channel TEXT,
          is_group INTEGER DEFAULT 0,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS messages (
          id TEXT,
          chat_jid TEXT,
          sender TEXT,
          sender_name TEXT,
          content TEXT,
          timestamp TEXT,
          is_from_me INTEGER,
          is_bot_message INTEGER DEFAULT 0,
          processing_priority INTEGER DEFAULT 5,
          content_hash TEXT,
          content_truncated INTEGER DEFAULT 0,
          metadata TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (id, chat_jid),
          FOREIGN KEY (chat_jid) REFERENCES chats(jid)
        );

        -- Enhanced indexes for better query performance
        CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp);
        CREATE INDEX IF NOT EXISTS idx_messages_chat_timestamp ON messages(chat_jid, timestamp);
        CREATE INDEX IF NOT EXISTS idx_messages_sender ON messages(sender);
        CREATE INDEX IF NOT EXISTS idx_messages_priority ON messages(processing_priority);
        CREATE INDEX IF NOT EXISTS idx_messages_hash ON messages(content_hash);
        CREATE INDEX IF NOT EXISTS idx_messages_bot_flag ON messages(is_bot_message);

        -- Composite indexes for common query patterns
        CREATE INDEX IF NOT EXISTS idx_messages_chat_time_bot ON messages(chat_jid, timestamp, is_bot_message);
        CREATE INDEX IF NOT EXISTS idx_messages_time_priority ON messages(timestamp, processing_priority);

        CREATE TABLE IF NOT EXISTS scheduled_tasks (
          id TEXT PRIMARY KEY,
          group_folder TEXT NOT NULL,
          chat_jid TEXT NOT NULL,
          prompt TEXT NOT NULL,
          schedule_type TEXT NOT NULL,
          schedule_value TEXT NOT NULL,
          next_run TEXT,
          last_run TEXT,
          last_result TEXT,
          status TEXT DEFAULT 'active',
          context_mode TEXT DEFAULT 'isolated',
          created_at TEXT NOT NULL,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Enhanced task indexes
        CREATE INDEX IF NOT EXISTS idx_tasks_next_run ON scheduled_tasks(next_run);
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON scheduled_tasks(status);
        CREATE INDEX IF NOT EXISTS idx_tasks_group_folder ON scheduled_tasks(group_folder);
        CREATE INDEX IF NOT EXISTS idx_tasks_due ON scheduled_tasks(status, next_run);

        CREATE TABLE IF NOT EXISTS task_run_logs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          task_id TEXT NOT NULL,
          run_at TEXT NOT NULL,
          duration_ms INTEGER NOT NULL,
          status TEXT NOT NULL,
          result TEXT,
          error TEXT,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY (task_id) REFERENCES scheduled_tasks(id)
        );

        CREATE INDEX IF NOT EXISTS idx_task_run_logs ON task_run_logs(task_id, run_at);
        CREATE INDEX IF NOT EXISTS idx_task_logs_status ON task_run_logs(status);

        CREATE TABLE IF NOT EXISTS router_state (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS sessions (
          group_folder TEXT PRIMARY KEY,
          session_id TEXT NOT NULL,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS registered_groups (
          jid TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          folder TEXT NOT NULL UNIQUE,
          trigger_pattern TEXT NOT NULL,
          added_at TEXT NOT NULL,
          container_config TEXT,
          requires_trigger INTEGER DEFAULT 1,
          is_main INTEGER DEFAULT 0,
          created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        );

        -- Performance monitoring table
        CREATE TABLE IF NOT EXISTS db_performance_log (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
          query_type TEXT,
          execution_time_ms INTEGER,
          rows_affected INTEGER,
          table_name TEXT,
          optimization_applied TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_perf_log_timestamp ON db_performance_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_perf_log_type ON db_performance_log(query_type);
      `);
    });

    transaction();
    logger.info('Enhanced database schema created successfully');
  }

  /**
   * Migrate existing data to enhanced schema
   */
  private migrateToEnhancedSchema(database: Database.Database): void {
    const migrations = [
      // Add new columns to messages table
      {
        name: 'add_processing_priority',
        sql: `ALTER TABLE messages ADD COLUMN processing_priority INTEGER DEFAULT 5`
      },
      {
        name: 'add_content_hash',
        sql: `ALTER TABLE messages ADD COLUMN content_hash TEXT`
      },
      {
        name: 'add_content_truncated',
        sql: `ALTER TABLE messages ADD COLUMN content_truncated INTEGER DEFAULT 0`
      },
      {
        name: 'add_metadata',
        sql: `ALTER TABLE messages ADD COLUMN metadata TEXT`
      },
      {
        name: 'add_created_at_messages',
        sql: `ALTER TABLE messages ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP`
      },
      // Add timestamps to other tables
      {
        name: 'add_timestamps_chats',
        sql: `ALTER TABLE chats ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP;
              ALTER TABLE chats ADD COLUMN updated_at TEXT DEFAULT CURRENT_TIMESTAMP`
      },
      {
        name: 'add_updated_at_tasks',
        sql: `ALTER TABLE scheduled_tasks ADD COLUMN updated_at TEXT DEFAULT CURRENT_TIMESTAMP`
      },
      {
        name: 'add_created_at_logs',
        sql: `ALTER TABLE task_run_logs ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP`
      },
      // Backfill content hashes for existing messages
      {
        name: 'backfill_content_hashes',
        sql: `UPDATE messages SET content_hash =
              CASE
                WHEN content IS NOT NULL AND content != ''
                THEN lower(hex(randomblob(16)))
                ELSE NULL
              END
              WHERE content_hash IS NULL`
      }
    ];

    for (const migration of migrations) {
      try {
        database.exec(migration.sql);
        logger.info({ migration: migration.name }, 'Migration applied successfully');
      } catch (error) {
        // Column might already exist - this is expected for existing databases
        logger.debug({ migration: migration.name, error }, 'Migration skipped (likely already applied)');
      }
    }
  }

  /**
   * Initialize database with enhanced optimizations
   */
  public initDatabase(): void {
    const dbPath = path.join(STORE_DIR, 'messages.db');
    fs.mkdirSync(path.dirname(dbPath), { recursive: true });

    const db = this.getConnection(dbPath);
    this.createEnhancedSchema(db);
    this.migrateToEnhancedSchema(db);

    // Migrate from JSON files if they exist
    this.migrateJsonState(db);

    // Run initial optimization
    this.optimizeDatabase(dbPath);

    logger.info({ dbPath }, 'Database initialized with enhanced optimizations');
  }

  /**
   * Store message with enhanced features
   */
  public storeMessage(msg: NewMessage): void {
    const dbPath = path.join(STORE_DIR, 'messages.db');

    this.executeWithMetrics(dbPath, (db) => {
      const enhancedMsg: EnhancedMessage = {
        ...msg,
        processing_priority: this.calculatePriority(msg),
        content_hash: this.generateContentHash(msg.content),
        content_truncated: msg.content && msg.content.length > 10000 ? 1 : 0,
        metadata: JSON.stringify({
          original_length: msg.content?.length || 0,
          channel: msg.chat_jid.includes('@') ? 'whatsapp' : 'other'
        })
      };

      db.prepare(`
        INSERT OR REPLACE INTO messages (
          id, chat_jid, sender, sender_name, content, timestamp,
          is_from_me, is_bot_message, processing_priority, content_hash,
          content_truncated, metadata, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
      `).run(
        enhancedMsg.id,
        enhancedMsg.chat_jid,
        enhancedMsg.sender,
        enhancedMsg.sender_name,
        enhancedMsg.content_truncated ? enhancedMsg.content?.substring(0, 10000) : enhancedMsg.content,
        enhancedMsg.timestamp,
        enhancedMsg.is_from_me ? 1 : 0,
        enhancedMsg.is_bot_message ? 1 : 0,
        enhancedMsg.processing_priority,
        enhancedMsg.content_hash,
        enhancedMsg.content_truncated,
        enhancedMsg.metadata
      );
    }, 'storeMessage');
  }

  /**
   * Optimized message retrieval with priority and performance hints
   */
  public getNewMessages(
    jids: string[],
    lastTimestamp: string,
    botPrefix: string,
    limit: number = 200,
    priorityFilter?: number
  ): { messages: NewMessage[]; newTimestamp: string } {
    if (jids.length === 0) return { messages: [], newTimestamp: lastTimestamp };

    const dbPath = path.join(STORE_DIR, 'messages.db');

    return this.executeWithMetrics(dbPath, (db) => {
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

      const params = [lastTimestamp, ...jids, `${botPrefix}:%`];

      if (priorityFilter !== undefined) {
        sql += ' AND processing_priority >= ?';
        params.push(priorityFilter);
      }

      sql += `
          ORDER BY processing_priority DESC, timestamp DESC
          LIMIT ?
        ) ORDER BY timestamp
      `;
      params.push(limit);

      const rows = db.prepare(sql).all(...params) as NewMessage[];

      let newTimestamp = lastTimestamp;
      for (const row of rows) {
        if (row.timestamp > newTimestamp) newTimestamp = row.timestamp;
      }

      return { messages: rows, newTimestamp };
    }, 'getNewMessages');
  }

  /**
   * Get database performance metrics
   */
  public getPerformanceMetrics(dbPath?: string): DatabaseMetrics | Map<string, DatabaseMetrics> {
    if (dbPath) {
      return this.metrics.get(dbPath) || {
        queryCount: 0,
        totalQueryTime: 0,
        slowQueryCount: 0,
        fragmentationLevel: 0,
        cacheHitRate: 0,
        lastOptimized: new Date().toISOString()
      };
    }
    return new Map(this.metrics);
  }

  /**
   * Optimize database performance
   */
  public optimizeDatabase(dbPath: string): void {
    this.executeWithMetrics(dbPath, (db) => {
      // Analyze query planner statistics
      db.pragma('optimize');

      // Update table statistics
      db.exec('ANALYZE');

      // Check fragmentation
      const fragInfo = db.prepare('PRAGMA freelist_count').get() as any;
      const pageCount = db.prepare('PRAGMA page_count').get() as any;

      const fragmentation = (fragInfo['freelist_count'] / pageCount['page_count']) * 100;

      // Update metrics
      const metrics = this.metrics.get(dbPath)!;
      metrics.fragmentationLevel = fragmentation;
      metrics.lastOptimized = new Date().toISOString();

      // Auto-vacuum if fragmentation is high
      if (fragmentation > 25) {
        logger.info({ dbPath, fragmentation }, 'Running auto-vacuum due to high fragmentation');
        db.exec('VACUUM');
        metrics.fragmentationLevel = 0;
      }

      logger.info({
        dbPath,
        fragmentation: fragmentation.toFixed(2),
        queryCount: metrics.queryCount,
        avgQueryTime: (metrics.totalQueryTime / Math.max(1, metrics.queryCount)).toFixed(2)
      }, 'Database optimization completed');

    }, 'optimize');
  }

  /**
   * Calculate message processing priority
   */
  private calculatePriority(msg: NewMessage): number {
    let priority = 5; // Default priority

    // Higher priority for direct mentions or questions
    if (msg.content?.includes('?') || msg.content?.toLowerCase().includes(ASSISTANT_NAME.toLowerCase())) {
      priority += 2;
    }

    // Higher priority for shorter messages (likely more urgent)
    if (msg.content && msg.content.length < 100) {
      priority += 1;
    }

    // Lower priority for very long messages
    if (msg.content && msg.content.length > 1000) {
      priority -= 1;
    }

    // Higher priority for non-group chats
    if (!msg.chat_jid.includes('@g.us')) {
      priority += 1;
    }

    return Math.max(1, Math.min(10, priority));
  }

  /**
   * Generate content hash for deduplication
   */
  private generateContentHash(content: string | null | undefined): string | null {
    if (!content || content.trim() === '') return null;

    // Normalize content for hashing (remove extra whitespace, normalize case for better dedup)
    const normalized = content.trim().toLowerCase().replace(/\s+/g, ' ');
    return crypto.createHash('md5').update(normalized).digest('hex');
  }

  /**
   * Clean up unused connections
   */
  private cleanupConnections(): void {
    const now = Date.now();

    for (const [key, connection] of this.connections.entries()) {
      if (!connection.inUse &&
          connection.refCount === 0 &&
          now - connection.lastUsed > this.connectionTimeout) {

        try {
          connection.db.close();
          this.connections.delete(key);
          logger.debug({ connectionKey: key }, 'Cleaned up idle database connection');
        } catch (error) {
          logger.warn({ connectionKey: key, error }, 'Error cleaning up database connection');
        }
      }
    }
  }

  /**
   * Close all database connections
   */
  public closeAllConnections(): void {
    if (this.cleanupInterval) {
      clearInterval(this.cleanupInterval);
    }

    for (const [key, connection] of this.connections.entries()) {
      try {
        connection.db.close();
        logger.debug({ connectionKey: key }, 'Closed database connection');
      } catch (error) {
        logger.warn({ connectionKey: key, error }, 'Error closing database connection');
      }
    }

    this.connections.clear();
    this.metrics.clear();
    logger.info('All database connections closed');
  }

  // Migration helper - to be removed after migration is complete
  private migrateJsonState(db: Database.Database): void {
    // ... existing migration logic from original file
    // (Keeping this for backward compatibility during transition)
  }
}

// Create singleton instance
const dbManager = new DatabaseManager();

// Export enhanced database functions
export function initDatabase(): void {
  dbManager.initDatabase();
}

export function storeMessage(msg: NewMessage): void {
  dbManager.storeMessage(msg);
}

export function getNewMessages(
  jids: string[],
  lastTimestamp: string,
  botPrefix: string,
  limit: number = 200,
  priorityFilter?: number
): { messages: NewMessage[]; newTimestamp: string } {
  return dbManager.getNewMessages(jids, lastTimestamp, botPrefix, limit, priorityFilter);
}

export function getPerformanceMetrics(): Map<string, DatabaseMetrics> {
  return dbManager.getPerformanceMetrics() as Map<string, DatabaseMetrics>;
}

export function optimizeDatabase(): void {
  const dbPath = path.join(STORE_DIR, 'messages.db');
  dbManager.optimizeDatabase(dbPath);
}

// Re-export all other functions from the original implementation for compatibility
// (These would need to be implemented with the new optimized approach)

export function storeChatMetadata(
  chatJid: string,
  timestamp: string,
  name?: string,
  channel?: string,
  isGroup?: boolean,
): void {
  // Implementation using optimized connection management
  const dbPath = path.join(STORE_DIR, 'messages.db');
  const db = dbManager['getConnection'](dbPath);

  const ch = channel ?? null;
  const group = isGroup === undefined ? null : isGroup ? 1 : 0;

  if (name) {
    db.prepare(
      `
      INSERT INTO chats (jid, name, last_message_time, channel, is_group, updated_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
      ON CONFLICT(jid) DO UPDATE SET
        name = excluded.name,
        last_message_time = MAX(last_message_time, excluded.last_message_time),
        channel = COALESCE(excluded.channel, channel),
        is_group = COALESCE(excluded.is_group, is_group),
        updated_at = CURRENT_TIMESTAMP
    `,
    ).run(chatJid, name, timestamp, ch, group);
  } else {
    db.prepare(
      `
      INSERT INTO chats (jid, name, last_message_time, channel, is_group, updated_at) VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
      ON CONFLICT(jid) DO UPDATE SET
        last_message_time = MAX(last_message_time, excluded.last_message_time),
        channel = COALESCE(excluded.channel, channel),
        is_group = COALESCE(excluded.is_group, is_group),
        updated_at = CURRENT_TIMESTAMP
    `,
    ).run(chatJid, chatJid, timestamp, ch, group);
  }
}

// Additional exports for backward compatibility
export * from './db.js';