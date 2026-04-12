/**
 * INBOX ZERO AUTOMATION SYSTEM
 * Phase 1 Implementation - Enhanced Email Classification & Discord Routing
 *
 * Integrates all components of the email automation system:
 * - Email Classification Engine
 * - Pattern Recognition Engine
 * - Discord Routing System
 * - Escalation Management
 */

import { logger } from './logger.js';
import {
  EmailClassificationEngine,
  EmailMetadata,
  ClassificationResult,
  EmailCategory,
  Priority,
  UrgencyLevel,
} from './email-classifier.js';
import { DiscordEmailRouter } from './discord-email-router.js';
import { EmailPatternEngine, PatternMatch } from './email-pattern-engine.js';
import { EmailEscalationSystem } from './email-escalation-system.js';

export interface InboxZeroConfig {
  // Classification settings
  classificationEnabled: boolean;
  confidenceThreshold: number;
  learningEnabled: boolean;

  // Discord routing settings
  discordRoutingEnabled: boolean;
  defaultChannel: string;
  alertMentions: boolean;

  // Escalation settings
  escalationEnabled: boolean;
  immediateAlertTime: number; // milliseconds
  fastTrackTime: number;
  standardTime: number;

  // Pattern recognition settings
  patternRecognitionEnabled: boolean;
  customPatternsEnabled: boolean;

  // Auto-action settings
  autoArchiveEnabled: boolean;
  autoMarkReadEnabled: boolean;
  autoLabelEnabled: boolean;

  // Reporting settings
  dailySummaryEnabled: boolean;
  weeklyReportEnabled: boolean;
  performanceMetrics: boolean;
}

export interface ProcessingStats {
  totalEmails: number;
  classificationResults: Map<EmailCategory, number>;
  priorityResults: Map<Priority, number>;
  urgencyResults: Map<UrgencyLevel, number>;
  autoActions: Map<string, number>;
  escalations: number;
  averageConfidence: number;
  processingTime: number;
  lastProcessed: string;
}

export interface EmailProcessingResult {
  emailId: string;
  classification: ClassificationResult;
  patternMatches: PatternMatch[];
  discordRouted: boolean;
  escalated: boolean;
  autoActions: string[];
  processingTimeMs: number;
}

export class InboxZeroAutomation {
  private classifier: EmailClassificationEngine;
  private patternEngine: EmailPatternEngine;
  private discordRouter: DiscordEmailRouter;
  private escalationSystem: EmailEscalationSystem;
  private config: InboxZeroConfig;
  private stats: ProcessingStats;

  constructor(config?: Partial<InboxZeroConfig>) {
    // Initialize default configuration
    this.config = {
      classificationEnabled: true,
      confidenceThreshold: 0.7,
      learningEnabled: true,
      discordRoutingEnabled: true,
      defaultChannel: '1484841234567890128', // Updated to use email-triage channel
      alertMentions: true,
      escalationEnabled: true,
      immediateAlertTime: 5 * 60 * 1000, // 5 minutes
      fastTrackTime: 30 * 60 * 1000, // 30 minutes
      standardTime: 2 * 60 * 60 * 1000, // 2 hours
      patternRecognitionEnabled: true,
      customPatternsEnabled: true,
      autoArchiveEnabled: true,
      autoMarkReadEnabled: true,
      autoLabelEnabled: true,
      dailySummaryEnabled: true,
      weeklyReportEnabled: true,
      performanceMetrics: true,
      ...config,
    };

    // Initialize processing statistics
    this.stats = {
      totalEmails: 0,
      classificationResults: new Map(),
      priorityResults: new Map(),
      urgencyResults: new Map(),
      autoActions: new Map(),
      escalations: 0,
      averageConfidence: 0,
      processingTime: 0,
      lastProcessed: new Date().toISOString(),
    };

    // Initialize components
    this.classifier = new EmailClassificationEngine();
    this.patternEngine = new EmailPatternEngine();
    this.discordRouter = new DiscordEmailRouter();
    this.escalationSystem = new EmailEscalationSystem();

    logger.info(
      { config: this.config, componentsLoaded: 4 },
      'Inbox Zero Automation System initialized',
    );
  }

  /**
   * Main processing method - analyze and process a single email
   */
  public async processEmail(
    email: EmailMetadata,
  ): Promise<EmailProcessingResult> {
    const startTime = Date.now();
    const result: EmailProcessingResult = {
      emailId: email.id,
      classification: {} as ClassificationResult,
      patternMatches: [],
      discordRouted: false,
      escalated: false,
      autoActions: [],
      processingTimeMs: 0,
    };

    try {
      logger.debug({ emailId: email.id }, 'Starting email processing pipeline');

      // Step 1: Pattern Recognition (if enabled)
      if (this.config.patternRecognitionEnabled) {
        result.patternMatches = await this.patternEngine.analyzePatterns(email);
        logger.debug(
          {
            emailId: email.id,
            patternMatchCount: result.patternMatches.length,
          },
          'Pattern analysis completed',
        );
      }

      // Step 2: Email Classification
      if (this.config.classificationEnabled) {
        result.classification = await this.classifier.classifyEmail(email);

        // Apply pattern recognition results to improve classification
        if (result.patternMatches.length > 0) {
          result.classification = this.enhanceClassificationWithPatterns(
            result.classification,
            result.patternMatches,
          );
        }

        logger.debug(
          {
            emailId: email.id,
            category: result.classification.category,
            priority: result.classification.priority,
            confidence: result.classification.confidence,
          },
          'Email classification completed',
        );
      }

      // Step 3: Discord Routing (if enabled and confident enough)
      if (
        this.config.discordRoutingEnabled &&
        result.classification.confidence >= this.config.confidenceThreshold
      ) {
        try {
          await this.discordRouter.routeEmail(email, result.classification);
          result.discordRouted = true;
          logger.debug({ emailId: email.id }, 'Email routed to Discord');
        } catch (error) {
          logger.error({ emailId: email.id, error }, 'Discord routing failed');
        }
      }

      // Step 4: Escalation Check (if enabled)
      if (this.config.escalationEnabled) {
        const escalationEvents = await this.escalationSystem.checkEscalation(
          email,
          result.classification,
        );
        if (escalationEvents.length > 0) {
          result.escalated = true;
          this.stats.escalations++;
          logger.debug(
            {
              emailId: email.id,
              escalationCount: escalationEvents.length,
            },
            'Email escalation triggered',
          );
        }
      }

      // Step 5: Auto-actions
      result.autoActions = await this.executeAutoActions(
        email,
        result.classification,
      );

      // Update statistics
      this.updateStats(email, result);

      result.processingTimeMs = Date.now() - startTime;

      logger.info(
        {
          emailId: email.id,
          category: result.classification.category,
          priority: result.classification.priority,
          discordRouted: result.discordRouted,
          escalated: result.escalated,
          autoActionCount: result.autoActions.length,
          processingTimeMs: result.processingTimeMs,
        },
        'Email processing completed',
      );

      return result;
    } catch (error) {
      logger.error(
        {
          emailId: email.id,
          error: error,
          processingTimeMs: Date.now() - startTime,
        },
        'Email processing failed',
      );

      // Return partial result with error info
      result.processingTimeMs = Date.now() - startTime;
      return result;
    }
  }

  /**
   * Enhance classification using pattern recognition results
   */
  private enhanceClassificationWithPatterns(
    classification: ClassificationResult,
    patternMatches: PatternMatch[],
  ): ClassificationResult {
    if (patternMatches.length === 0) return classification;

    // Find the highest scoring pattern match
    const topMatch = patternMatches[0];

    // If pattern confidence is higher than classification confidence, adjust
    if (topMatch.confidence > classification.confidence) {
      const patternBoost = Math.min(
        0.2,
        topMatch.confidence - classification.confidence,
      );
      classification.confidence = Math.min(
        1.0,
        classification.confidence + patternBoost,
      );

      // Add pattern context to reason
      classification.reason += ` (Pattern: ${topMatch.patternId})`;

      logger.debug(
        {
          originalConfidence: classification.confidence - patternBoost,
          patternBoost,
          finalConfidence: classification.confidence,
          patternId: topMatch.patternId,
        },
        'Classification enhanced with pattern recognition',
      );
    }

    return classification;
  }

  /**
   * Execute automatic actions based on classification
   */
  private async executeAutoActions(
    email: EmailMetadata,
    classification: ClassificationResult,
  ): Promise<string[]> {
    const actions: string[] = [];

    try {
      // Auto-archive low priority/spam emails
      if (
        this.config.autoArchiveEnabled &&
        (classification.priority === Priority.ARCHIVE ||
          classification.category === EmailCategory.SPAM_NOISE)
      ) {
        actions.push('auto_archive');
      }

      // Auto-mark as read for processed emails
      if (
        this.config.autoMarkReadEnabled &&
        classification.priority !== Priority.CRITICAL
      ) {
        actions.push('mark_read');
      }

      // Auto-label based on category
      if (this.config.autoLabelEnabled) {
        const label = this.getCategoryLabel(classification.category);
        if (label) {
          actions.push(`label:${label}`);
        }
      }

      // Record actions in stats
      actions.forEach((action) => {
        const current = this.stats.autoActions.get(action) || 0;
        this.stats.autoActions.set(action, current + 1);
      });
    } catch (error) {
      logger.error(
        { emailId: email.id, error },
        'Auto-action execution failed',
      );
    }

    return actions;
  }

  /**
   * Get Gmail label for email category
   */
  private getCategoryLabel(category: EmailCategory): string | null {
    const labelMap: Record<EmailCategory, string> = {
      [EmailCategory.BUSINESS_CRITICAL]: 'business-critical',
      [EmailCategory.CLIENT_COMMUNICATIONS]: 'clients',
      [EmailCategory.RECRUITMENT_PROSPECTS]: 'recruitment',
      [EmailCategory.CALENDAR_SCHEDULING]: 'calendar',
      [EmailCategory.FINANCIAL_INSURANCE]: 'financial',
      [EmailCategory.VENDOR_OPERATIONAL]: 'vendors',
      [EmailCategory.MARKETING_ANALYTICS]: 'analytics',
      [EmailCategory.PERSONAL_ADMIN]: 'personal',
      [EmailCategory.SPAM_NOISE]: 'spam',
    };

    return labelMap[category] || null;
  }

  /**
   * Update processing statistics
   */
  private updateStats(
    email: EmailMetadata,
    result: EmailProcessingResult,
  ): void {
    this.stats.totalEmails++;
    this.stats.lastProcessed = new Date().toISOString();

    // Update classification stats
    const category = result.classification.category;
    if (category) {
      const current = this.stats.classificationResults.get(category) || 0;
      this.stats.classificationResults.set(category, current + 1);
    }

    // Update priority stats
    const priority = result.classification.priority;
    if (priority) {
      const current = this.stats.priorityResults.get(priority) || 0;
      this.stats.priorityResults.set(priority, current + 1);
    }

    // Update urgency stats
    const urgency = result.classification.urgency;
    if (urgency) {
      const current = this.stats.urgencyResults.get(urgency) || 0;
      this.stats.urgencyResults.set(urgency, current + 1);
    }

    // Update average confidence
    if (result.classification.confidence) {
      this.stats.averageConfidence =
        (this.stats.averageConfidence * (this.stats.totalEmails - 1) +
          result.classification.confidence) /
        this.stats.totalEmails;
    }

    // Update processing time
    this.stats.processingTime =
      (this.stats.processingTime * (this.stats.totalEmails - 1) +
        result.processingTimeMs) /
      this.stats.totalEmails;
  }

  /**
   * Process multiple emails in batch
   */
  public async processBatch(
    emails: EmailMetadata[],
  ): Promise<EmailProcessingResult[]> {
    logger.info(
      { emailCount: emails.length },
      'Starting batch email processing',
    );

    const results: EmailProcessingResult[] = [];
    const batchStartTime = Date.now();

    for (const email of emails) {
      try {
        const result = await this.processEmail(email);
        results.push(result);

        // Small delay between emails to prevent overloading
        await new Promise((resolve) => setTimeout(resolve, 100));
      } catch (error) {
        logger.error({ emailId: email.id, error }, 'Batch processing error');
      }
    }

    const batchTime = Date.now() - batchStartTime;
    logger.info(
      {
        emailCount: emails.length,
        processedCount: results.length,
        batchTimeMs: batchTime,
        avgTimePerEmail: batchTime / results.length,
      },
      'Batch processing completed',
    );

    return results;
  }

  /**
   * Generate processing summary for Discord
   */
  public generateProcessingSummary(timeframe: string = '24h'): string {
    const summary = [
      `📊 **Inbox Zero Processing Summary - ${timeframe}**`,
      '',
      `📧 **Total Processed:** ${this.stats.totalEmails}`,
      `⚡ **Avg Confidence:** ${Math.round(this.stats.averageConfidence * 100)}%`,
      `⏱️ **Avg Processing Time:** ${Math.round(this.stats.processingTime)}ms`,
      '',
      '**📂 Categories:**',
    ];

    // Add category breakdown
    for (const [category, count] of this.stats.classificationResults) {
      const categoryName = category.replace('_', ' ').toUpperCase();
      summary.push(`• ${categoryName}: ${count}`);
    }

    summary.push('', '**🎯 Priorities:**');

    // Add priority breakdown
    for (const [priority, count] of this.stats.priorityResults) {
      summary.push(`• ${priority}: ${count}`);
    }

    if (this.stats.escalations > 0) {
      summary.push('', `🚨 **Escalations:** ${this.stats.escalations}`);
    }

    summary.push(
      '',
      `*Last updated: ${new Date(this.stats.lastProcessed).toLocaleString()}*`,
    );

    return summary.join('\n');
  }

  /**
   * Update configuration
   */
  public updateConfig(updates: Partial<InboxZeroConfig>): void {
    this.config = { ...this.config, ...updates };
    logger.info({ updates }, 'Configuration updated');
  }

  /**
   * Get current configuration
   */
  public getConfig(): InboxZeroConfig {
    return { ...this.config };
  }

  /**
   * Get current statistics
   */
  public getStats(): ProcessingStats {
    return {
      totalEmails: this.stats.totalEmails,
      classificationResults: new Map(this.stats.classificationResults),
      priorityResults: new Map(this.stats.priorityResults),
      urgencyResults: new Map(this.stats.urgencyResults),
      autoActions: new Map(this.stats.autoActions),
      escalations: this.stats.escalations,
      averageConfidence: this.stats.averageConfidence,
      processingTime: this.stats.processingTime,
      lastProcessed: this.stats.lastProcessed,
    };
  }

  /**
   * Reset statistics
   */
  public resetStats(): void {
    this.stats = {
      totalEmails: 0,
      classificationResults: new Map(),
      priorityResults: new Map(),
      urgencyResults: new Map(),
      autoActions: new Map(),
      escalations: 0,
      averageConfidence: 0,
      processingTime: 0,
      lastProcessed: new Date().toISOString(),
    };
    logger.info('Statistics reset');
  }

  /**
   * Add learning feedback
   */
  public addLearningFeedback(
    emailId: string,
    feedback: {
      userFeedback: 'correct' | 'incorrect' | 'spam' | 'important';
      originalClassification: EmailCategory;
      correctClassification?: EmailCategory;
    },
  ): void {
    if (!this.config.learningEnabled) return;

    this.patternEngine.addLearningData({
      emailId,
      userFeedback: feedback.userFeedback,
      originalClassification: feedback.originalClassification,
      correctClassification: feedback.correctClassification,
      timestamp: new Date().toISOString(),
    });

    // Update sender reputation based on feedback
    if (feedback.userFeedback === 'spam') {
      // Downgrade sender reputation
    } else if (feedback.userFeedback === 'important') {
      // Upgrade sender reputation
    }

    logger.info(
      {
        emailId,
        feedback: feedback.userFeedback,
        originalClassification: feedback.originalClassification,
      },
      'Learning feedback added',
    );
  }

  /**
   * Get component instances for external access
   */
  public getComponents() {
    return {
      classifier: this.classifier,
      patternEngine: this.patternEngine,
      discordRouter: this.discordRouter,
      escalationSystem: this.escalationSystem,
    };
  }

  /**
   * Shutdown the automation system
   */
  public shutdown(): void {
    this.escalationSystem.stopProcessing();
    logger.info('Inbox Zero Automation System shutdown');
  }
}

// Factory function for easy initialization
export function createInboxZeroAutomation(
  config?: Partial<InboxZeroConfig>,
): InboxZeroAutomation {
  return new InboxZeroAutomation(config);
}
