# Phase 1 Implementation Guide
## Enhanced Email Classification & Discord Routing

This guide provides step-by-step instructions for implementing David's inbox zero automation system using the existing NanoClaw infrastructure.

## Implementation Overview

The system integrates four main components:
1. **Email Classification Engine** - Categorizes emails using advanced pattern recognition
2. **Discord Email Router** - Routes emails to appropriate Discord channels with priority formatting
3. **Pattern Recognition Engine** - Learns from email patterns and user feedback
4. **Escalation System** - Manages priority-based alert workflows

## Step 1: Integration with Existing Gmail Channel

### Option A: Replace Existing Gmail Channel (Recommended)
```typescript
// In src/channels/registry.ts - comment out existing gmail registration
// registerChannel('gmail', (opts: ChannelOpts) => { ... });

// Register enhanced Gmail channel instead
import { EnhancedGmailChannel } from './enhanced-gmail.js';
```

### Option B: Run in Parallel
```typescript
// Keep existing gmail channel for backup
// Add enhanced-gmail as additional channel
// Both will process emails but enhanced version takes priority
```

## Step 2: Update Dependencies

Add required dependencies to `package.json`:
```bash
npm install --save natural sentiment # For basic sentiment analysis
```

## Step 3: Configure Discord Channels

### Create Required Channels in Discord Server

1. **Go to Discord Server Settings**
2. **Create New Channels:**
   ```
   📧 EMAIL MANAGEMENT
   ├── 🚨 business-critical      (ID: TBD)
   ├── 👥 client-communications  (ID: 1484840749924089996) [existing]
   ├── 🎯 recruitment-prospects  (ID: TBD)
   ├── 📅 calendar-scheduling   (ID: TBD)
   ├── 💰 financial-insurance   (ID: TBD)
   ├── 🏢 vendor-operational    (ID: TBD)
   ├── 📊 marketing-analytics   (ID: TBD)
   ├── 📝 personal-admin        (ID: TBD)
   └── 📦 email-archive         (ID: TBD)
   ```

3. **Update Channel IDs** in `src/discord-email-router.ts`:
   ```typescript
   private channels: Map<EmailCategory, DiscordChannelConfig> = new Map();

   // Replace TBD values with actual Discord channel IDs
   ```

## Step 4: Integration with Main NanoClaw Process

### Update Main Index File (`src/index.ts`)

```typescript
// Add imports
import { InboxZeroAutomation } from './inbox-zero-automation.js';
import { DiscordMessage } from './discord-email-router.js';

// Initialize automation system
const inboxZeroConfig = {
  classificationEnabled: true,
  confidenceThreshold: 0.7,
  discordRoutingEnabled: true,
  escalationEnabled: true,
  // ... other config options
};

const inboxZeroSystem = new InboxZeroAutomation(inboxZeroConfig);

// Add Discord message handler
const handleDiscordMessage = async (message: DiscordMessage) => {
  const discordChannel = channels.find(c => c.name === 'discord');
  if (discordChannel) {
    await discordChannel.sendMessage(`dc:${message.channelId}`, message.content);
  }
};

// Pass handler to enhanced Gmail channel
const enhancedGmailOpts = {
  ...standardGmailOpts,
  onDiscordMessage: handleDiscordMessage
};
```

### Update Channel Initialization

```typescript
// In the channel initialization section
if (enhancedGmailChannel) {
  channels.push(enhancedGmailChannel);

  // Link with inbox zero automation
  enhancedGmailChannel.setAutomationSystem(inboxZeroSystem);
}
```

## Step 5: Database Schema Updates (Optional)

Add tables for tracking email processing:

```sql
-- Email processing history
CREATE TABLE email_processing_log (
  id TEXT PRIMARY KEY,
  email_id TEXT NOT NULL,
  classification_category TEXT,
  priority TEXT,
  confidence REAL,
  discord_routed BOOLEAN DEFAULT FALSE,
  escalated BOOLEAN DEFAULT FALSE,
  processing_time_ms INTEGER,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Sender reputation tracking
CREATE TABLE sender_reputation (
  email_address TEXT PRIMARY KEY,
  domain TEXT,
  reputation_score INTEGER DEFAULT 50,
  category TEXT DEFAULT 'regular',
  interaction_count INTEGER DEFAULT 0,
  last_seen DATETIME,
  response_rate REAL,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Pattern learning feedback
CREATE TABLE pattern_feedback (
  id TEXT PRIMARY KEY,
  email_id TEXT NOT NULL,
  user_feedback TEXT NOT NULL,
  original_classification TEXT,
  correct_classification TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

## Step 6: Configuration Management

### Environment Variables

Add to `.env` file:
```bash
# Email Automation Settings
EMAIL_CLASSIFICATION_ENABLED=true
EMAIL_CONFIDENCE_THRESHOLD=0.7
EMAIL_LEARNING_ENABLED=true
EMAIL_AUTO_ARCHIVE_ENABLED=true
EMAIL_ESCALATION_ENABLED=true

# Discord Integration
EMAIL_DISCORD_ROUTING_ENABLED=true
EMAIL_ALERT_MENTIONS_ENABLED=true

# Timing Configuration
EMAIL_IMMEDIATE_ALERT_TIME=300000  # 5 minutes
EMAIL_FAST_TRACK_TIME=1800000     # 30 minutes
EMAIL_STANDARD_TIME=7200000       # 2 hours
```

### Load Configuration in Application

```typescript
// In src/config.ts
import { readEnvFile } from './env.js';

const envConfig = readEnvFile([
  'EMAIL_CLASSIFICATION_ENABLED',
  'EMAIL_CONFIDENCE_THRESHOLD',
  'EMAIL_LEARNING_ENABLED',
  // ... other email config variables
]);

export const EMAIL_CONFIG = {
  classificationEnabled: envConfig.EMAIL_CLASSIFICATION_ENABLED === 'true',
  confidenceThreshold: parseFloat(envConfig.EMAIL_CONFIDENCE_THRESHOLD || '0.7'),
  learningEnabled: envConfig.EMAIL_LEARNING_ENABLED === 'true',
  // ... map other variables
};
```

## Step 7: Testing and Validation

### Unit Testing

Create test files for each component:

```bash
# Create test directory
mkdir -p test/email-automation

# Test files to create:
test/email-automation/classifier.test.ts
test/email-automation/pattern-engine.test.ts
test/email-automation/discord-router.test.ts
test/email-automation/escalation-system.test.ts
test/email-automation/integration.test.ts
```

### Integration Testing

1. **Test with Sample Emails**
   ```typescript
   const testEmails = [
     {
       from: 'client@example.com',
       subject: 'Urgent: Policy Question',
       content: 'I need immediate help with my policy...',
       // ...
     }
   ];

   for (const email of testEmails) {
     const result = await inboxZeroSystem.processEmail(email);
     console.log('Classification:', result.classification);
   }
   ```

2. **Test Discord Routing**
   - Send test emails to verify correct channel routing
   - Check alert mention functionality
   - Verify escalation timers

3. **Test Pattern Learning**
   - Process emails with known patterns
   - Provide feedback to improve accuracy
   - Monitor confidence improvements

## Step 8: Deployment and Monitoring

### Deployment Steps

1. **Build the Application**
   ```bash
   npm run build
   ```

2. **Update Service Configuration**
   ```bash
   # Stop existing service
   launchctl unload ~/Library/LaunchAgents/com.nanoclaw.plist

   # Start with new configuration
   launchctl load ~/Library/LaunchAgents/com.nanoclaw.plist
   ```

3. **Monitor Logs**
   ```bash
   tail -f /tmp/nanoclaw.log
   ```

### Monitoring Checklist

- [ ] Email processing logs show classifications
- [ ] Discord channels receive routed emails
- [ ] Escalation alerts trigger correctly
- [ ] Auto-actions execute as expected
- [ ] Performance metrics within targets
- [ ] Error rates below 2%

## Step 9: User Training and Feedback

### Discord Commands (Future Enhancement)

Add commands for user interaction:
```
/email-stats                    # Show processing statistics
/email-classify <email-id>      # Manually classify email
/email-feedback <email-id> <correct|incorrect|spam>
/email-escalate <email-id>      # Manual escalation
/email-acknowledge <email-id>   # Stop escalations
```

### Feedback Collection

1. **React-Based Feedback**
   - Add reaction buttons to Discord messages
   - ✅ Correct classification
   - ❌ Incorrect classification
   - 🚫 Spam/unwanted
   - ⭐ Important/VIP

2. **Learning Integration**
   - Collect user feedback automatically
   - Update patterns based on corrections
   - Improve sender reputation scores
   - Adjust classification rules

## Step 10: Performance Optimization

### Monitoring Metrics

1. **Classification Accuracy**
   ```typescript
   const stats = inboxZeroSystem.getStats();
   console.log('Average Confidence:', stats.averageConfidence);
   console.log('Processing Time:', stats.processingTime);
   ```

2. **Discord Routing Success**
   - Track successful message deliveries
   - Monitor Discord API rate limits
   - Verify channel permissions

3. **Escalation Effectiveness**
   - Measure response times to alerts
   - Track acknowledgment rates
   - Monitor false positive escalations

### Optimization Strategies

1. **Confidence Threshold Tuning**
   - Start with 70% confidence threshold
   - Adjust based on accuracy feedback
   - Lower for better coverage, raise for precision

2. **Pattern Weight Adjustment**
   - Monitor pattern match effectiveness
   - Update weights based on user feedback
   - Remove ineffective patterns

3. **Performance Tuning**
   - Optimize email content parsing
   - Cache frequently used patterns
   - Batch process similar emails

## Rollback Plan

If issues occur, implement rollback:

1. **Disable Enhanced Gmail Channel**
   ```typescript
   // In src/channels/registry.ts
   // Comment out enhanced-gmail registration
   // Uncomment original gmail registration
   ```

2. **Revert to Original Configuration**
   - Restore original Gmail channel
   - Disable automation features
   - Fall back to existing email processing

3. **Preserve Learning Data**
   - Keep collected pattern data
   - Save user feedback
   - Maintain sender reputation scores

## Success Criteria

Phase 1 implementation is successful when:

- [ ] **95%+ emails** automatically classified correctly
- [ ] **90%+ emails** routed to correct Discord channels
- [ ] **Critical emails** escalated within 5 minutes
- [ ] **High priority emails** escalated within 30 minutes
- [ ] **Auto-archive accuracy** above 98%
- [ ] **Processing time** under 500ms per email
- [ ] **System uptime** above 99%
- [ ] **User satisfaction** with reduced manual email management

## Next Phase Planning

After successful Phase 1 deployment, plan Phase 2:

1. **Smart Reply Generation**
2. **Calendar Integration and Automation**
3. **Mobile Control Interface**
4. **CRM Integration**
5. **Advanced Analytics and Insights**

## Support and Troubleshooting

### Common Issues

1. **Classification Accuracy Too Low**
   - Check confidence threshold settings
   - Review pattern matching rules
   - Increase learning data collection

2. **Discord Routing Failures**
   - Verify Discord channel IDs
   - Check bot permissions
   - Monitor Discord API limits

3. **Escalation Not Triggering**
   - Verify escalation rule configuration
   - Check time threshold settings
   - Review trigger conditions

4. **Performance Issues**
   - Monitor processing time metrics
   - Check for Gmail API rate limits
   - Optimize pattern matching logic

### Debug Commands

```bash
# Check email processing logs
grep "Email classified" /tmp/nanoclaw.log

# Monitor Discord routing
grep "Discord message sent" /tmp/nanoclaw.log

# Check escalation events
grep "Escalation" /tmp/nanoclaw.log

# Performance monitoring
grep "processing completed" /tmp/nanoclaw.log | tail -20
```

This implementation provides a robust foundation for David's inbox zero automation while maintaining compatibility with existing NanoClaw infrastructure.