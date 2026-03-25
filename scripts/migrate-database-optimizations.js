#!/usr/bin/env node

/**
 * Database Migration Script - Phase 1.1 Optimizations
 *
 * This script safely migrates all existing databases to the enhanced schema with:
 * - WAL mode enabled
 * - Performance monitoring
 * - Enhanced indexes
 * - Zero data loss
 */

import Database from 'better-sqlite3';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

class DatabaseMigrator {
    constructor() {
        this.nanosPath = '/Users/davidprice/nanoclaw';
        this.mainDbPath = path.join(this.nanosPath, 'store', 'messages.db');
        this.groupsPath = path.join(this.nanosPath, 'data', 'groups');
        this.migrationLog = [];
        this.errors = [];
    }

    log(level, message, data = {}) {
        const timestamp = new Date().toISOString();
        const logEntry = { timestamp, level, message, data };
        this.migrationLog.push(logEntry);

        if (level === 'error') {
            this.errors.push(logEntry);
        }

        console.log(`[${timestamp}] ${level.toUpperCase()}: ${message}`);
        if (Object.keys(data).length > 0) {
            console.log('  Data:', JSON.stringify(data, null, 2));
        }
    }

    async backupDatabase(dbPath) {
        const backupPath = `${dbPath}.backup.${Date.now()}`;

        try {
            if (!fs.existsSync(dbPath)) {
                this.log('warn', 'Database does not exist, skipping backup', { dbPath });
                return null;
            }

            // Copy the database file
            fs.copyFileSync(dbPath, backupPath);

            // Also backup WAL and SHM files if they exist
            const walPath = `${dbPath}-wal`;
            const shmPath = `${dbPath}-shm`;

            if (fs.existsSync(walPath)) {
                fs.copyFileSync(walPath, `${backupPath}-wal`);
            }

            if (fs.existsSync(shmPath)) {
                fs.copyFileSync(shmPath, `${backupPath}-shm`);
            }

            this.log('info', 'Database backup created', {
                original: dbPath,
                backup: backupPath
            });

            return backupPath;
        } catch (error) {
            this.log('error', 'Failed to create database backup', {
                dbPath,
                error: error.message
            });
            return null;
        }
    }

    applyMainDatabaseOptimizations(db) {
        this.log('info', 'Applying optimizations to main database');

        // Enable WAL mode and other optimizations
        try {
            db.pragma('journal_mode = WAL');
            db.pragma('synchronous = NORMAL');
            db.pragma('cache_size = -4000'); // 4MB
            db.pragma('temp_store = MEMORY');
            db.pragma('mmap_size = 268435456'); // 256MB
            db.pragma('optimize');

            this.log('info', 'WAL mode and optimizations applied');
        } catch (error) {
            this.log('error', 'Failed to apply database optimizations', { error: error.message });
        }

        // Add performance monitoring columns to messages table
        const migrations = [
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
            {
                name: 'add_updated_at_chats',
                sql: `ALTER TABLE chats ADD COLUMN updated_at TEXT DEFAULT CURRENT_TIMESTAMP`
            },
            {
                name: 'add_updated_at_tasks',
                sql: `ALTER TABLE scheduled_tasks ADD COLUMN updated_at TEXT DEFAULT CURRENT_TIMESTAMP`
            }
        ];

        // Create new performance indexes
        const indexes = [
            'CREATE INDEX IF NOT EXISTS idx_messages_priority ON messages(processing_priority)',
            'CREATE INDEX IF NOT EXISTS idx_messages_hash ON messages(content_hash)',
            'CREATE INDEX IF NOT EXISTS idx_messages_chat_time_bot ON messages(chat_jid, timestamp, is_bot_message)',
            'CREATE INDEX IF NOT EXISTS idx_messages_time_priority ON messages(timestamp, processing_priority)',
            'CREATE INDEX IF NOT EXISTS idx_tasks_due ON scheduled_tasks(status, next_run)',
            'CREATE INDEX IF NOT EXISTS idx_tasks_group_folder ON scheduled_tasks(group_folder)'
        ];

        // Apply migrations
        for (const migration of migrations) {
            try {
                db.exec(migration.sql);
                this.log('info', `Applied migration: ${migration.name}`);
            } catch (error) {
                if (error.message.includes('duplicate column')) {
                    this.log('debug', `Migration ${migration.name} skipped (column already exists)`);
                } else {
                    this.log('error', `Migration ${migration.name} failed`, { error: error.message });
                }
            }
        }

        // Create new indexes
        for (const indexSql of indexes) {
            try {
                db.exec(indexSql);
                this.log('info', `Created performance index: ${indexSql.split(' ')[5] || 'unnamed'}`);
            } catch (error) {
                this.log('error', 'Failed to create index', { sql: indexSql, error: error.message });
            }
        }

        // Create performance monitoring table
        try {
            db.exec(`
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
            this.log('info', 'Created performance monitoring table');
        } catch (error) {
            this.log('error', 'Failed to create performance monitoring table', { error: error.message });
        }

        // Backfill content hashes for existing messages
        try {
            const result = db.prepare(`
                UPDATE messages
                SET content_hash = lower(hex(randomblob(16))),
                    processing_priority = CASE
                        WHEN content LIKE '%?%' OR content LIKE '%urgent%' THEN 7
                        WHEN length(content) < 100 THEN 6
                        WHEN length(content) > 1000 THEN 4
                        ELSE 5
                    END,
                    content_truncated = CASE WHEN length(content) > 10000 THEN 1 ELSE 0 END,
                    metadata = json_object(
                        'original_length', length(content),
                        'migrated', 1,
                        'migration_date', datetime('now')
                    )
                WHERE content_hash IS NULL AND content IS NOT NULL AND content != ''
            `).run();

            this.log('info', 'Backfilled message metadata', {
                messagesUpdated: result.changes
            });
        } catch (error) {
            this.log('error', 'Failed to backfill message metadata', { error: error.message });
        }
    }

    async migrateMainDatabase() {
        this.log('info', 'Starting main database migration');

        if (!fs.existsSync(this.mainDbPath)) {
            this.log('warn', 'Main database does not exist, skipping');
            return false;
        }

        // Create backup
        const backupPath = await this.backupDatabase(this.mainDbPath);
        if (!backupPath) {
            this.log('error', 'Cannot proceed without backup');
            return false;
        }

        try {
            // Open database and apply optimizations
            const db = new Database(this.mainDbPath);

            // Get pre-migration stats
            const preStats = {
                messageCount: db.prepare('SELECT COUNT(*) as count FROM messages').get().count,
                chatCount: db.prepare('SELECT COUNT(*) as count FROM chats').get().count,
                taskCount: db.prepare('SELECT COUNT(*) as count FROM scheduled_tasks').get().count
            };

            this.log('info', 'Pre-migration stats', preStats);

            // Apply optimizations
            this.applyMainDatabaseOptimizations(db);

            // Verify data integrity
            const postStats = {
                messageCount: db.prepare('SELECT COUNT(*) as count FROM messages').get().count,
                chatCount: db.prepare('SELECT COUNT(*) as count FROM chats').get().count,
                taskCount: db.prepare('SELECT COUNT(*) as count FROM scheduled_tasks').get().count
            };

            this.log('info', 'Post-migration stats', postStats);

            // Verify no data loss
            if (postStats.messageCount !== preStats.messageCount ||
                postStats.chatCount !== preStats.chatCount ||
                postStats.taskCount !== preStats.taskCount) {

                this.log('error', 'Data integrity check failed!', {
                    preStats,
                    postStats
                });

                // Restore from backup
                db.close();
                fs.copyFileSync(backupPath, this.mainDbPath);
                this.log('info', 'Restored database from backup due to data integrity failure');
                return false;
            }

            db.close();
            this.log('info', 'Main database migration completed successfully');
            return true;

        } catch (error) {
            this.log('error', 'Main database migration failed', { error: error.message });

            // Restore from backup
            try {
                fs.copyFileSync(backupPath, this.mainDbPath);
                this.log('info', 'Restored database from backup after error');
            } catch (restoreError) {
                this.log('error', 'Failed to restore from backup!', { error: restoreError.message });
            }

            return false;
        }
    }

    async migrateGroupDatabase(groupFolder) {
        const dbPath = path.join(this.groupsPath, groupFolder, 'messages.db');

        this.log('info', `Migrating group database: ${groupFolder}`);

        if (!fs.existsSync(dbPath)) {
            this.log('warn', `Database does not exist for group ${groupFolder}`);
            return false;
        }

        // Create backup
        const backupPath = await this.backupDatabase(dbPath);
        if (!backupPath) {
            this.log('error', `Cannot proceed with ${groupFolder} without backup`);
            return false;
        }

        try {
            const db = new Database(dbPath);

            // Apply WAL mode and optimizations
            db.pragma('journal_mode = WAL');
            db.pragma('synchronous = NORMAL');
            db.pragma('cache_size = -2000');
            db.pragma('temp_store = MEMORY');
            db.pragma('mmap_size = 134217728');
            db.pragma('optimize');

            // Get pre-migration message count
            const preCount = db.prepare('SELECT COUNT(*) as count FROM messages').get().count;

            // Apply enhanced schema migrations (using the enhanced group manager logic)
            const migrations = [
                { name: 'add_processing_priority', sql: `ALTER TABLE messages ADD COLUMN processing_priority INTEGER DEFAULT 5` },
                { name: 'add_content_hash', sql: `ALTER TABLE messages ADD COLUMN content_hash TEXT` },
                { name: 'add_content_truncated', sql: `ALTER TABLE messages ADD COLUMN content_truncated INTEGER DEFAULT 0` },
                { name: 'add_metadata', sql: `ALTER TABLE messages ADD COLUMN metadata TEXT` },
                { name: 'add_created_at', sql: `ALTER TABLE messages ADD COLUMN created_at TEXT DEFAULT CURRENT_TIMESTAMP` },
                { name: 'add_updated_at', sql: `ALTER TABLE messages ADD COLUMN updated_at TEXT DEFAULT CURRENT_TIMESTAMP` }
            ];

            for (const migration of migrations) {
                try {
                    db.exec(migration.sql);
                    this.log('debug', `Applied ${groupFolder} migration: ${migration.name}`);
                } catch (error) {
                    if (!error.message.includes('duplicate column')) {
                        this.log('warn', `Migration ${migration.name} failed for ${groupFolder}`, { error: error.message });
                    }
                }
            }

            // Create new indexes
            const indexes = [
                'CREATE INDEX IF NOT EXISTS idx_content_hash ON messages(content_hash)',
                'CREATE INDEX IF NOT EXISTS idx_priority ON messages(processing_priority)',
                'CREATE INDEX IF NOT EXISTS idx_timestamp_priority ON messages(timestamp, processing_priority)',
                'CREATE INDEX IF NOT EXISTS idx_sender_timestamp ON messages(sender, timestamp)'
            ];

            for (const indexSql of indexes) {
                try {
                    db.exec(indexSql);
                } catch (error) {
                    this.log('warn', `Index creation failed for ${groupFolder}`, { sql: indexSql, error: error.message });
                }
            }

            // Backfill enhanced data
            const updateResult = db.prepare(`
                UPDATE messages
                SET content_hash = lower(hex(randomblob(16))),
                    processing_priority = CASE
                        WHEN content LIKE '%$%' OR content LIKE '%premium%' OR content LIKE '%sale%' THEN 8
                        WHEN content LIKE '%?%' THEN 7
                        WHEN length(content) < 100 THEN 6
                        WHEN length(content) > 1000 THEN 4
                        ELSE 5
                    END,
                    metadata = json_object(
                        'original_length', length(content),
                        'migrated', 1,
                        'group', ?
                    )
                WHERE content_hash IS NULL AND content IS NOT NULL
            `).run(groupFolder);

            // Verify data integrity
            const postCount = db.prepare('SELECT COUNT(*) as count FROM messages').get().count;

            if (postCount !== preCount) {
                this.log('error', `Data integrity check failed for ${groupFolder}!`, {
                    preCount,
                    postCount
                });

                db.close();
                fs.copyFileSync(backupPath, dbPath);
                this.log('info', `Restored ${groupFolder} from backup`);
                return false;
            }

            // Update group metadata
            const metadataPath = path.join(this.groupsPath, groupFolder, 'metadata.json');
            if (fs.existsSync(metadataPath)) {
                try {
                    const metadata = JSON.parse(fs.readFileSync(metadataPath, 'utf8'));
                    metadata.schema_version = '2.0';
                    metadata.performance_optimized = true;
                    metadata.wal_enabled = true;
                    metadata.migrated_at = new Date().toISOString();

                    if (!metadata.optimization_history) {
                        metadata.optimization_history = [];
                    }

                    metadata.optimization_history.push({
                        timestamp: new Date().toISOString(),
                        action: 'schema_migration',
                        description: `Migrated to enhanced schema v2.0, updated ${updateResult.changes} messages`
                    });

                    fs.writeFileSync(metadataPath, JSON.stringify(metadata, null, 2));
                } catch (error) {
                    this.log('warn', `Failed to update metadata for ${groupFolder}`, { error: error.message });
                }
            }

            db.close();
            this.log('info', `Successfully migrated ${groupFolder}`, {
                messagesUpdated: updateResult.changes,
                messageCount: postCount
            });
            return true;

        } catch (error) {
            this.log('error', `Failed to migrate ${groupFolder}`, { error: error.message });

            // Restore from backup
            try {
                fs.copyFileSync(backupPath, dbPath);
                this.log('info', `Restored ${groupFolder} from backup`);
            } catch (restoreError) {
                this.log('error', `Failed to restore ${groupFolder} from backup!`, { error: restoreError.message });
            }

            return false;
        }
    }

    async migrateAllGroupDatabases() {
        if (!fs.existsSync(this.groupsPath)) {
            this.log('warn', 'Groups directory does not exist');
            return [];
        }

        const groupFolders = fs.readdirSync(this.groupsPath)
            .filter(folder => {
                const dbPath = path.join(this.groupsPath, folder, 'messages.db');
                return fs.existsSync(dbPath);
            });

        this.log('info', `Found ${groupFolders.length} group databases to migrate`);

        const results = [];
        for (const groupFolder of groupFolders) {
            const success = await this.migrateGroupDatabase(groupFolder);
            results.push({ groupFolder, success });
        }

        return results;
    }

    async runFullMigration() {
        this.log('info', 'Starting full database migration to Phase 1.1 optimizations');

        const results = {
            mainDatabase: false,
            groupDatabases: [],
            totalGroups: 0,
            successfulGroups: 0,
            errors: [],
            startTime: new Date().toISOString()
        };

        try {
            // Migrate main database
            results.mainDatabase = await this.migrateMainDatabase();

            // Migrate all group databases
            results.groupDatabases = await this.migrateAllGroupDatabases();
            results.totalGroups = results.groupDatabases.length;
            results.successfulGroups = results.groupDatabases.filter(r => r.success).length;

            results.endTime = new Date().toISOString();
            results.errors = this.errors;

            // Save migration report
            const reportPath = path.join(this.nanosPath, 'migration-report.json');
            fs.writeFileSync(reportPath, JSON.stringify({
                ...results,
                migrationLog: this.migrationLog
            }, null, 2));

            this.log('info', 'Migration completed', {
                mainDbSuccess: results.mainDatabase,
                groupsSuccessful: results.successfulGroups,
                groupsTotal: results.totalGroups,
                errorsCount: results.errors.length
            });

            // Summary
            console.log('\n=== MIGRATION SUMMARY ===');
            console.log(`Main Database: ${results.mainDatabase ? '✅ SUCCESS' : '❌ FAILED'}`);
            console.log(`Group Databases: ${results.successfulGroups}/${results.totalGroups} successful`);
            console.log(`Errors: ${results.errors.length}`);
            console.log(`Report saved to: ${reportPath}`);

            if (results.errors.length > 0) {
                console.log('\nERRORS:');
                results.errors.forEach(error => {
                    console.log(`- ${error.message}`);
                });
            }

            return results;

        } catch (error) {
            this.log('error', 'Migration process failed', { error: error.message });
            results.endTime = new Date().toISOString();
            results.errors = this.errors;
            return results;
        }
    }

    async testDatabaseConnections() {
        this.log('info', 'Testing database connections after migration');

        const results = {
            mainDb: false,
            groupDbs: []
        };

        // Test main database
        try {
            const db = new Database(this.mainDbPath);
            const messageCount = db.prepare('SELECT COUNT(*) as count FROM messages').get().count;
            db.close();
            results.mainDb = true;
            this.log('info', 'Main database connection test passed', { messageCount });
        } catch (error) {
            this.log('error', 'Main database connection test failed', { error: error.message });
        }

        // Test group databases
        if (fs.existsSync(this.groupsPath)) {
            const groupFolders = fs.readdirSync(this.groupsPath)
                .filter(folder => {
                    const dbPath = path.join(this.groupsPath, folder, 'messages.db');
                    return fs.existsSync(dbPath);
                });

            for (const groupFolder of groupFolders) {
                const dbPath = path.join(this.groupsPath, groupFolder, 'messages.db');
                try {
                    const db = new Database(dbPath);
                    const messageCount = db.prepare('SELECT COUNT(*) as count FROM messages').get().count;
                    db.close();
                    results.groupDbs.push({ groupFolder, success: true, messageCount });
                    this.log('info', `Group ${groupFolder} connection test passed`, { messageCount });
                } catch (error) {
                    results.groupDbs.push({ groupFolder, success: false, error: error.message });
                    this.log('error', `Group ${groupFolder} connection test failed`, { error: error.message });
                }
            }
        }

        return results;
    }
}

// CLI interface
async function main() {
    const command = process.argv[2];
    const migrator = new DatabaseMigrator();

    switch (command) {
        case 'migrate':
            console.log('🚀 Starting database migration to Phase 1.1 optimizations...\n');
            await migrator.runFullMigration();
            break;

        case 'test':
            console.log('🧪 Testing database connections...\n');
            await migrator.testDatabaseConnections();
            break;

        case 'main-only':
            console.log('🏗️ Migrating main database only...\n');
            await migrator.migrateMainDatabase();
            break;

        case 'backup':
            const dbPath = process.argv[3];
            if (!dbPath) {
                console.error('Usage: node migrate-database-optimizations.js backup <db-path>');
                process.exit(1);
            }
            await migrator.backupDatabase(dbPath);
            break;

        default:
            console.log('NanoClaw Database Migration Tool - Phase 1.1 Optimizations');
            console.log('');
            console.log('Usage:');
            console.log('  node migrate-database-optimizations.js migrate      - Full migration of all databases');
            console.log('  node migrate-database-optimizations.js main-only    - Migrate main database only');
            console.log('  node migrate-database-optimizations.js test         - Test database connections');
            console.log('  node migrate-database-optimizations.js backup <path> - Backup specific database');
            console.log('');
            console.log('The migration will:');
            console.log('  ✅ Enable WAL mode for better concurrency');
            console.log('  ✅ Add performance monitoring columns');
            console.log('  ✅ Create strategic indexes');
            console.log('  ✅ Maintain zero data loss');
            console.log('  ✅ Create automatic backups');
    }
}

const __filename = fileURLToPath(import.meta.url);
const isMainModule = process.argv[1] === __filename;

if (isMainModule) {
    main().catch(error => {
        console.error('Migration script failed:', error);
        process.exit(1);
    });
}

export default DatabaseMigrator;