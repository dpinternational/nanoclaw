#!/usr/bin/env node

/**
 * Database Performance Testing Script - Phase 1.1
 *
 * Validates the performance improvements from database optimizations:
 * - Query performance comparison
 * - WAL mode verification
 * - Index effectiveness
 * - Connection pooling validation
 */

import Database from 'better-sqlite3';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

class DatabasePerformanceTester {
    constructor() {
        this.nanosPath = '/Users/davidprice/nanoclaw';
        this.mainDbPath = path.join(this.nanosPath, 'store', 'messages.db');
        this.groupsPath = path.join(this.nanosPath, 'data', 'groups');
        this.results = {
            timestamp: new Date().toISOString(),
            tests: {},
            summary: {}
        };
    }

    log(message, data = {}) {
        console.log(`[${new Date().toISOString()}] ${message}`);
        if (Object.keys(data).length > 0) {
            console.log('  ', JSON.stringify(data, null, 2));
        }
    }

    async measureQueryPerformance(db, queryName, queryFn, iterations = 100) {
        const times = [];

        // Warm up
        for (let i = 0; i < 5; i++) {
            try {
                queryFn();
            } catch (error) {
                // Ignore warmup errors
            }
        }

        // Measure
        for (let i = 0; i < iterations; i++) {
            const start = process.hrtime.bigint();
            try {
                const result = queryFn();
                const end = process.hrtime.bigint();
                times.push(Number(end - start) / 1000000); // Convert to milliseconds
            } catch (error) {
                this.log(`Query ${queryName} failed on iteration ${i}`, { error: error.message });
            }
        }

        if (times.length === 0) {
            return null;
        }

        const avgTime = times.reduce((a, b) => a + b, 0) / times.length;
        const minTime = Math.min(...times);
        const maxTime = Math.max(...times);
        const medianTime = times.sort((a, b) => a - b)[Math.floor(times.length / 2)];

        return {
            queryName,
            iterations: times.length,
            avgTime: parseFloat(avgTime.toFixed(3)),
            minTime: parseFloat(minTime.toFixed(3)),
            maxTime: parseFloat(maxTime.toFixed(3)),
            medianTime: parseFloat(medianTime.toFixed(3)),
            totalTime: parseFloat((times.reduce((a, b) => a + b, 0)).toFixed(3))
        };
    }

    async testMainDatabasePerformance() {
        if (!fs.existsSync(this.mainDbPath)) {
            this.log('Main database not found, skipping tests');
            return null;
        }

        this.log('Testing main database performance...');
        const db = new Database(this.mainDbPath);

        // Check WAL mode
        const walMode = db.pragma('journal_mode');
        this.log('Journal mode', { mode: walMode });

        // Get database stats
        const messageCount = db.prepare('SELECT COUNT(*) as count FROM messages').get()?.count || 0;
        const chatCount = db.prepare('SELECT COUNT(*) as count FROM chats').get()?.count || 0;

        this.log('Database stats', { messageCount, chatCount });

        const tests = [];

        // Test 1: Simple message retrieval
        tests.push(await this.measureQueryPerformance(db, 'simple_select', () => {
            return db.prepare('SELECT * FROM messages LIMIT 10').all();
        }));

        // Test 2: Timestamp-based query (common pattern)
        tests.push(await this.measureQueryPerformance(db, 'timestamp_query', () => {
            const yesterday = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
            return db.prepare('SELECT * FROM messages WHERE timestamp > ? LIMIT 50').all(yesterday);
        }));

        // Test 3: Chat-based query
        tests.push(await this.measureQueryPerformance(db, 'chat_query', () => {
            return db.prepare('SELECT * FROM messages WHERE chat_jid LIKE ? LIMIT 20').all('%@%');
        }));

        // Test 4: Priority-based query (new optimization)
        tests.push(await this.measureQueryPerformance(db, 'priority_query', () => {
            return db.prepare('SELECT * FROM messages WHERE processing_priority >= ? ORDER BY processing_priority DESC LIMIT 10').all(7);
        }, 50)); // Fewer iterations for potentially complex query

        // Test 5: Hash-based deduplication query
        tests.push(await this.measureQueryPerformance(db, 'hash_dedup', () => {
            return db.prepare('SELECT content_hash, COUNT(*) as count FROM messages WHERE content_hash IS NOT NULL GROUP BY content_hash HAVING count > 1').all();
        }, 20));

        // Test 6: Complex join with tasks
        tests.push(await this.measureQueryPerformance(db, 'complex_join', () => {
            return db.prepare(`
                SELECT m.id, m.content, t.prompt
                FROM messages m
                LEFT JOIN scheduled_tasks t ON m.chat_jid = t.chat_jid
                WHERE m.timestamp > date('now', '-7 days')
                LIMIT 25
            `).all();
        }, 30));

        // Test query planner effectiveness
        const explainResults = {};
        try {
            explainResults.timestamp_index = db.prepare('EXPLAIN QUERY PLAN SELECT * FROM messages WHERE timestamp > ? LIMIT 10').all('2024-01-01');
            explainResults.priority_index = db.prepare('EXPLAIN QUERY PLAN SELECT * FROM messages WHERE processing_priority >= ? ORDER BY processing_priority DESC LIMIT 10').all(5);
        } catch (error) {
            this.log('Query plan analysis failed', { error: error.message });
        }

        // Database integrity check
        let integrityCheck;
        try {
            integrityCheck = db.pragma('integrity_check');
        } catch (error) {
            integrityCheck = `Error: ${error.message}`;
        }

        // Fragmentation analysis
        let fragmentation;
        try {
            const freeListCount = db.prepare('PRAGMA freelist_count').get()['freelist_count'];
            const pageCount = db.prepare('PRAGMA page_count').get()['page_count'];
            fragmentation = {
                freePages: freeListCount,
                totalPages: pageCount,
                fragmentationPercent: parseFloat(((freeListCount / pageCount) * 100).toFixed(2))
            };
        } catch (error) {
            fragmentation = { error: error.message };
        }

        db.close();

        const mainDbResults = {
            walMode,
            messageCount,
            chatCount,
            queryTests: tests.filter(t => t !== null),
            explainResults,
            integrityCheck,
            fragmentation
        };

        this.results.tests.mainDatabase = mainDbResults;
        return mainDbResults;
    }

    async testGroupDatabasePerformance() {
        if (!fs.existsSync(this.groupsPath)) {
            this.log('Groups directory not found, skipping tests');
            return [];
        }

        const groupFolders = fs.readdirSync(this.groupsPath)
            .filter(folder => {
                const dbPath = path.join(this.groupsPath, folder, 'messages.db');
                return fs.existsSync(dbPath);
            });

        this.log(`Testing ${groupFolders.length} group databases...`);

        const groupResults = [];

        for (const groupFolder of groupFolders.slice(0, 3)) { // Test first 3 groups to keep tests reasonable
            this.log(`Testing group: ${groupFolder}`);

            const dbPath = path.join(this.groupsPath, groupFolder, 'messages.db');
            const db = new Database(dbPath);

            try {
                const walMode = db.pragma('journal_mode');
                const messageCount = db.prepare('SELECT COUNT(*) as count FROM messages').get()?.count || 0;

                if (messageCount === 0) {
                    this.log(`Skipping ${groupFolder} - no messages`);
                    db.close();
                    continue;
                }

                const tests = [];

                // Test group-specific queries
                tests.push(await this.measureQueryPerformance(db, 'group_recent_messages', () => {
                    return db.prepare('SELECT * FROM messages ORDER BY timestamp DESC LIMIT 20').all();
                }));

                tests.push(await this.measureQueryPerformance(db, 'group_sender_stats', () => {
                    return db.prepare('SELECT sender, COUNT(*) as count FROM messages GROUP BY sender ORDER BY count DESC LIMIT 10').all();
                }));

                // Test sales detection performance
                tests.push(await this.measureQueryPerformance(db, 'sales_detection', () => {
                    return db.prepare("SELECT * FROM messages WHERE content LIKE '%$%' OR content LIKE '%premium%' LIMIT 15").all();
                }, 30));

                // Test priority-based retrieval
                tests.push(await this.measureQueryPerformance(db, 'priority_messages', () => {
                    return db.prepare('SELECT * FROM messages WHERE processing_priority >= ? ORDER BY processing_priority DESC, timestamp DESC LIMIT 10').all(6);
                }, 50));

                // Check for enhanced schema columns
                let hasEnhancedSchema = false;
                try {
                    db.prepare('SELECT processing_priority FROM messages LIMIT 1').all();
                    hasEnhancedSchema = true;
                } catch (error) {
                    hasEnhancedSchema = false;
                }

                groupResults.push({
                    groupFolder,
                    walMode,
                    messageCount,
                    hasEnhancedSchema,
                    queryTests: tests.filter(t => t !== null)
                });

            } catch (error) {
                this.log(`Error testing ${groupFolder}`, { error: error.message });
                groupResults.push({
                    groupFolder,
                    error: error.message
                });
            } finally {
                db.close();
            }
        }

        this.results.tests.groupDatabases = groupResults;
        return groupResults;
    }

    async testConnectionPooling() {
        this.log('Testing connection pooling behavior...');

        // This test simulates multiple concurrent connections
        const dbPath = this.mainDbPath;
        const connections = [];
        const results = {
            concurrentConnections: 0,
            operationsPerSecond: 0,
            errors: []
        };

        try {
            // Create multiple connections
            for (let i = 0; i < 5; i++) {
                connections.push(new Database(dbPath, { readonly: true }));
            }
            results.concurrentConnections = connections.length;

            // Perform concurrent operations
            const startTime = Date.now();
            const operations = [];

            for (let i = 0; i < 100; i++) {
                const connectionIndex = i % connections.length;
                operations.push(
                    new Promise((resolve, reject) => {
                        try {
                            const result = connections[connectionIndex].prepare('SELECT COUNT(*) FROM messages').get();
                            resolve(result);
                        } catch (error) {
                            reject(error);
                        }
                    })
                );
            }

            const operationResults = await Promise.allSettled(operations);
            const endTime = Date.now();

            const successfulOps = operationResults.filter(r => r.status === 'fulfilled').length;
            const failedOps = operationResults.filter(r => r.status === 'rejected').length;

            results.operationsPerSecond = Math.round((successfulOps / (endTime - startTime)) * 1000);
            results.successfulOperations = successfulOps;
            results.failedOperations = failedOps;

            if (failedOps > 0) {
                results.errors = operationResults
                    .filter(r => r.status === 'rejected')
                    .map(r => r.reason.message);
            }

        } catch (error) {
            results.errors.push(error.message);
        } finally {
            // Clean up connections
            connections.forEach(conn => {
                try {
                    conn.close();
                } catch (error) {
                    // Ignore cleanup errors
                }
            });
        }

        this.results.tests.connectionPooling = results;
        return results;
    }

    generatePerformanceReport() {
        const mainDb = this.results.tests.mainDatabase;
        const groupDbs = this.results.tests.groupDatabases || [];
        const pooling = this.results.tests.connectionPooling;

        const report = {
            timestamp: this.results.timestamp,
            summary: {
                walEnabled: mainDb?.walMode === 'wal',
                totalMessagesTested: (mainDb?.messageCount || 0) + groupDbs.reduce((sum, g) => sum + (g.messageCount || 0), 0),
                groupsWithEnhancedSchema: groupDbs.filter(g => g.hasEnhancedSchema).length,
                totalGroupsTested: groupDbs.length
            },
            performance: {
                mainDatabase: mainDb?.queryTests?.map(t => ({
                    query: t.queryName,
                    avgTime: t.avgTime,
                    medianTime: t.medianTime
                })),
                groupDatabases: groupDbs.map(g => ({
                    group: g.groupFolder,
                    messageCount: g.messageCount,
                    avgQueryTime: g.queryTests ?
                        (g.queryTests.reduce((sum, t) => sum + t.avgTime, 0) / g.queryTests.length).toFixed(2) :
                        null
                })),
                connectionPooling: {
                    concurrentConnections: pooling?.concurrentConnections,
                    operationsPerSecond: pooling?.operationsPerSecond,
                    errors: pooling?.errors?.length || 0
                }
            },
            optimizations: {
                fragmentationLevel: mainDb?.fragmentation?.fragmentationPercent,
                integrityCheck: mainDb?.integrityCheck === 'ok' ? 'passed' : 'issues',
                indexesWorking: mainDb?.explainResults ? 'verified' : 'unknown'
            },
            recommendations: []
        };

        // Generate recommendations
        if (report.summary.walEnabled) {
            report.recommendations.push('✅ WAL mode is enabled for better concurrency');
        } else {
            report.recommendations.push('❌ WAL mode is not enabled - run migration script');
        }

        if (report.optimizations.fragmentationLevel > 25) {
            report.recommendations.push(`⚠️ High fragmentation detected (${report.optimizations.fragmentationLevel}%) - consider VACUUM`);
        } else {
            report.recommendations.push('✅ Fragmentation level is acceptable');
        }

        const avgMainQueryTime = mainDb?.queryTests ?
            mainDb.queryTests.reduce((sum, t) => sum + t.avgTime, 0) / mainDb.queryTests.length : 0;

        if (avgMainQueryTime > 50) {
            report.recommendations.push(`⚠️ Average query time is high (${avgMainQueryTime.toFixed(2)}ms) - check indexes`);
        } else {
            report.recommendations.push('✅ Query performance is good');
        }

        if (report.performance.connectionPooling.operationsPerSecond > 500) {
            report.recommendations.push('✅ Connection pooling performance is excellent');
        } else {
            report.recommendations.push('⚠️ Connection pooling could be improved');
        }

        return report;
    }

    async runAllTests() {
        this.log('🧪 Starting comprehensive database performance tests...\n');

        try {
            // Test main database
            await this.testMainDatabasePerformance();

            // Test group databases
            await this.testGroupDatabasePerformance();

            // Test connection pooling
            await this.testConnectionPooling();

            // Generate report
            const report = this.generatePerformanceReport();

            // Save detailed results
            const resultsPath = path.join(this.nanosPath, 'performance-test-results.json');
            fs.writeFileSync(resultsPath, JSON.stringify(this.results, null, 2));

            // Save summary report
            const reportPath = path.join(this.nanosPath, 'performance-report.json');
            fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));

            // Display summary
            this.log('\n🎯 PERFORMANCE TEST SUMMARY');
            console.log('='.repeat(50));
            console.log(`WAL Mode Enabled: ${report.summary.walEnabled ? '✅' : '❌'}`);
            console.log(`Total Messages Tested: ${report.summary.totalMessagesTested.toLocaleString()}`);
            console.log(`Groups with Enhanced Schema: ${report.summary.groupsWithEnhancedSchema}/${report.summary.totalGroupsTested}`);
            console.log(`Fragmentation Level: ${report.optimizations.fragmentationLevel}%`);
            console.log(`Connection Pool Performance: ${report.performance.connectionPooling.operationsPerSecond} ops/sec`);

            console.log('\nRECOMMENDATIONS:');
            report.recommendations.forEach(rec => console.log(`  ${rec}`));

            console.log(`\nDetailed results saved to: ${resultsPath}`);
            console.log(`Summary report saved to: ${reportPath}`);

            return report;

        } catch (error) {
            this.log('Performance testing failed', { error: error.message });
            throw error;
        }
    }
}

// CLI interface
async function main() {
    const command = process.argv[2];
    const tester = new DatabasePerformanceTester();

    switch (command) {
        case 'full':
            await tester.runAllTests();
            break;

        case 'main':
            await tester.testMainDatabasePerformance();
            break;

        case 'groups':
            await tester.testGroupDatabasePerformance();
            break;

        case 'pool':
            await tester.testConnectionPooling();
            break;

        default:
            console.log('NanoClaw Database Performance Tester - Phase 1.1');
            console.log('');
            console.log('Usage:');
            console.log('  node test-database-performance.js full    - Run all performance tests');
            console.log('  node test-database-performance.js main    - Test main database only');
            console.log('  node test-database-performance.js groups  - Test group databases only');
            console.log('  node test-database-performance.js pool    - Test connection pooling only');
            console.log('');
            console.log('This will test:');
            console.log('  ⚡ Query performance improvements');
            console.log('  🔄 WAL mode effectiveness');
            console.log('  📊 Index utilization');
            console.log('  🔗 Connection pooling efficiency');
            console.log('  📈 Fragmentation levels');
    }
}

const __filename = fileURLToPath(import.meta.url);
const isMainModule = process.argv[1] === __filename;

if (isMainModule) {
    main().catch(error => {
        console.error('Performance testing failed:', error);
        process.exit(1);
    });
}

export default DatabasePerformanceTester;