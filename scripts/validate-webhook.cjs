#!/usr/bin/env node

/**
 * NanoClaw Webhook System Validation
 *
 * Comprehensive validation of webhook infrastructure components
 */

const fs = require('fs');
const path = require('path');
const http = require('http');

// Validation Results
let validationResults = {
    total: 0,
    passed: 0,
    failed: 0,
    warnings: 0,
    results: []
};

// Colors for output
const colors = {
    reset: '\x1b[0m',
    bright: '\x1b[1m',
    red: '\x1b[31m',
    green: '\x1b[32m',
    yellow: '\x1b[33m',
    blue: '\x1b[34m',
    cyan: '\x1b[36m'
};

function log(message, color = colors.reset) {
    console.log(`${color}${message}${colors.reset}`);
}

function addResult(test, status, message, details = '') {
    validationResults.total++;
    validationResults[status]++;
    validationResults.results.push({ test, status, message, details });

    const icon = status === 'passed' ? '✅' : status === 'failed' ? '❌' : '⚠️';
    const color = status === 'passed' ? colors.green : status === 'failed' ? colors.red : colors.yellow;

    log(`${icon} ${test}: ${message}`, color);
    if (details) {
        log(`   ${details}`, colors.cyan);
    }
}

async function validateFileStructure() {
    log('\n📁 Validating File Structure...', colors.blue);

    const requiredFiles = [
        'src/webhook-server.ts',
        'src/telegram-api.ts',
        'src/channels/telegram.ts',
        'package.json',
        '.env.webhook-example'
    ];

    const optionalFiles = [
        'docs/webhook-architecture.md',
        'scripts/setup-webhook.sh',
        'scripts/benchmark-webhook.js'
    ];

    for (const file of requiredFiles) {
        if (fs.existsSync(file)) {
            addResult('File Structure', 'passed', `${file} exists`);
        } else {
            addResult('File Structure', 'failed', `${file} missing`);
        }
    }

    for (const file of optionalFiles) {
        if (fs.existsSync(file)) {
            addResult('Documentation', 'passed', `${file} exists`);
        } else {
            addResult('Documentation', 'warnings', `${file} missing (optional)`);
        }
    }
}

async function validateDependencies() {
    log('\n📦 Validating Dependencies...', colors.blue);

    try {
        const packageJson = JSON.parse(fs.readFileSync('package.json', 'utf8'));
        const requiredDeps = ['express', 'helmet', 'node-fetch'];
        const requiredDevDeps = ['@types/express'];

        for (const dep of requiredDeps) {
            if (packageJson.dependencies && packageJson.dependencies[dep]) {
                addResult('Dependencies', 'passed', `${dep} dependency found`);
            } else {
                addResult('Dependencies', 'failed', `${dep} dependency missing`);
            }
        }

        for (const dep of requiredDevDeps) {
            if (packageJson.devDependencies && packageJson.devDependencies[dep]) {
                addResult('Dev Dependencies', 'passed', `${dep} dev dependency found`);
            } else {
                addResult('Dev Dependencies', 'warnings', `${dep} dev dependency missing`);
            }
        }

    } catch (err) {
        addResult('Dependencies', 'failed', 'Cannot read package.json', err.message);
    }
}

async function validateConfiguration() {
    log('\n⚙️ Validating Configuration...', colors.blue);

    // Check for .env file
    if (fs.existsSync('.env')) {
        addResult('Configuration', 'passed', '.env file exists');

        try {
            const envContent = fs.readFileSync('.env', 'utf8');
            const configs = [
                'WEBHOOK_ENABLED',
                'WEBHOOK_DOMAIN',
                'WEBHOOK_PORT',
                'TELEGRAM_BOT_TOKEN'
            ];

            for (const config of configs) {
                if (envContent.includes(`${config}=`)) {
                    const value = envContent.match(new RegExp(`${config}=(.+)`))?.[1] || '';
                    if (value && value !== 'your_value_here' && value !== 'your-domain.com') {
                        addResult('Configuration', 'passed', `${config} configured`);
                    } else {
                        addResult('Configuration', 'warnings', `${config} needs configuration`);
                    }
                } else {
                    addResult('Configuration', 'warnings', `${config} not found in .env`);
                }
            }
        } catch (err) {
            addResult('Configuration', 'failed', 'Cannot read .env file', err.message);
        }
    } else {
        addResult('Configuration', 'warnings', '.env file not found');
    }

    // Check example configuration
    if (fs.existsSync('.env.webhook-example')) {
        addResult('Configuration', 'passed', '.env.webhook-example template exists');
    } else {
        addResult('Configuration', 'failed', '.env.webhook-example template missing');
    }
}

async function validateCodeIntegration() {
    log('\n🔧 Validating Code Integration...', colors.blue);

    // Check telegram.ts modifications
    try {
        const telegramTs = fs.readFileSync('src/channels/telegram.ts', 'utf8');

        const requiredImports = [
            'webhook-server',
            'telegram-api',
            'WEBHOOK_ENABLED'
        ];

        for (const importName of requiredImports) {
            if (telegramTs.includes(importName)) {
                addResult('Code Integration', 'passed', `${importName} import found`);
            } else {
                addResult('Code Integration', 'failed', `${importName} import missing`);
            }
        }

        const requiredMethods = [
            'setupWebhookMode',
            'handleWebhookUpdate',
            'fallbackToPolling'
        ];

        for (const method of requiredMethods) {
            if (telegramTs.includes(method)) {
                addResult('Code Integration', 'passed', `${method} method implemented`);
            } else {
                addResult('Code Integration', 'failed', `${method} method missing`);
            }
        }

    } catch (err) {
        addResult('Code Integration', 'failed', 'Cannot read telegram.ts', err.message);
    }

    // Check config.ts modifications
    try {
        const configTs = fs.readFileSync('src/config.ts', 'utf8');

        const requiredConfigs = [
            'WEBHOOK_ENABLED',
            'WEBHOOK_PORT',
            'WEBHOOK_DOMAIN'
        ];

        for (const config of requiredConfigs) {
            if (configTs.includes(config)) {
                addResult('Config Integration', 'passed', `${config} constant defined`);
            } else {
                addResult('Config Integration', 'failed', `${config} constant missing`);
            }
        }

    } catch (err) {
        addResult('Config Integration', 'failed', 'Cannot read config.ts', err.message);
    }

    // Check index.ts modifications
    try {
        const indexTs = fs.readFileSync('src/index.ts', 'utf8');

        if (indexTs.includes('webhookServer')) {
            addResult('Main Integration', 'passed', 'webhookServer integrated in main');
        } else {
            addResult('Main Integration', 'warnings', 'webhookServer not found in main (may be optional)');
        }

    } catch (err) {
        addResult('Main Integration', 'failed', 'Cannot read index.ts', err.message);
    }
}

async function validateWebhookServer() {
    log('\n🌐 Validating Webhook Server...', colors.blue);

    // Check if webhook server is running
    const testPort = process.env.WEBHOOK_PORT || '3002';

    return new Promise((resolve) => {
        const options = {
            hostname: 'localhost',
            port: parseInt(testPort),
            path: '/health',
            method: 'GET',
            timeout: 3000
        };

        const req = http.request(options, (res) => {
            if (res.statusCode === 200) {
                addResult('Webhook Server', 'passed', `Webhook server running on port ${testPort}`);

                let data = '';
                res.on('data', chunk => data += chunk);
                res.on('end', () => {
                    try {
                        const health = JSON.parse(data);
                        if (health.status === 'ok') {
                            addResult('Health Check', 'passed', 'Webhook health endpoint working');
                        } else {
                            addResult('Health Check', 'warnings', 'Webhook health endpoint returned non-ok status');
                        }
                    } catch (err) {
                        addResult('Health Check', 'warnings', 'Health endpoint response not JSON');
                    }
                });
            } else {
                addResult('Webhook Server', 'warnings', `Webhook server responding with status ${res.statusCode}`);
            }
            resolve();
        });

        req.on('error', () => {
            addResult('Webhook Server', 'warnings', `Webhook server not running on port ${testPort}`, 'Start NanoClaw to test webhook server');
            resolve();
        });

        req.on('timeout', () => {
            req.destroy();
            addResult('Webhook Server', 'warnings', 'Webhook server health check timeout');
            resolve();
        });

        req.end();
    });
}

function generateReport() {
    log('\n📊 VALIDATION REPORT', colors.bright);
    log('===================', colors.bright);

    const successRate = ((validationResults.passed / validationResults.total) * 100).toFixed(1);

    log(`\nTotal Tests: ${validationResults.total}`);
    log(`✅ Passed: ${validationResults.passed}`, colors.green);
    log(`❌ Failed: ${validationResults.failed}`, colors.red);
    log(`⚠️  Warnings: ${validationResults.warnings}`, colors.yellow);
    log(`Success Rate: ${successRate}%`, successRate >= 80 ? colors.green : colors.yellow);

    if (validationResults.failed > 0) {
        log('\n🚨 CRITICAL ISSUES:', colors.red);
        validationResults.results
            .filter(r => r.status === 'failed')
            .forEach(r => log(`   • ${r.test}: ${r.message}`, colors.red));
    }

    if (validationResults.warnings > 0) {
        log('\n⚠️  WARNINGS:', colors.yellow);
        validationResults.results
            .filter(r => r.status === 'warnings')
            .forEach(r => log(`   • ${r.test}: ${r.message}`, colors.yellow));
    }

    log('\n📋 NEXT STEPS:', colors.blue);

    if (validationResults.failed === 0) {
        log('✨ Webhook system is ready for testing!');
        log('\n🚀 To test the webhook system:');
        log('   1. Configure .env with your settings');
        log('   2. Run: npm run build');
        log('   3. Run: npm start');
        log('   4. Monitor: tail -f logs/nanoclaw.log | grep webhook');
        log('   5. Benchmark: node scripts/benchmark-webhook.js');
    } else {
        log('🔧 Fix the critical issues above before proceeding');
        log('   1. Review failed tests');
        log('   2. Check file structure and dependencies');
        log('   3. Re-run validation: node scripts/validate-webhook.js');
    }

    if (validationResults.warnings > 0) {
        log('\n💡 Address warnings for optimal performance:');
        log('   • Complete configuration in .env');
        log('   • Test webhook server connectivity');
        log('   • Review documentation files');
    }
}

async function main() {
    log('🚀 NanoClaw Webhook System Validation', colors.bright);
    log('=====================================', colors.bright);

    await validateFileStructure();
    await validateDependencies();
    await validateConfiguration();
    await validateCodeIntegration();
    await validateWebhookServer();

    generateReport();

    // Exit with appropriate code
    process.exit(validationResults.failed > 0 ? 1 : 0);
}

if (require.main === module) {
    main().catch(err => {
        log(`❌ Validation script failed: ${err.message}`, colors.red);
        process.exit(1);
    });
}

module.exports = { main, validationResults };