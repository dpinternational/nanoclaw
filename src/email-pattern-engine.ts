/**
 * EMAIL PATTERN RECOGNITION ENGINE
 * Advanced pattern recognition for email classification and prioritization
 */

import { logger } from './logger.js';
import { EmailMetadata, EmailCategory } from './email-classifier.js';

export interface Pattern {
  id: string;
  name: string;
  category: EmailCategory;
  weight: number;
  confidence: number;
  rules: PatternRule[];
  timeDecay?: boolean; // Whether pattern effectiveness decays over time
  learningEnabled?: boolean; // Whether pattern can be updated based on feedback
}

export interface PatternRule {
  type: 'sender' | 'subject' | 'content' | 'time' | 'frequency' | 'chain';
  field?: string;
  operator:
    | 'contains'
    | 'matches'
    | 'starts_with'
    | 'ends_with'
    | 'regex'
    | 'exists'
    | 'count'
    | 'time_range';
  value: string | number | RegExp;
  weight: number;
  caseSensitive?: boolean;
}

export interface PatternMatch {
  patternId: string;
  score: number;
  confidence: number;
  matchedRules: string[];
  context?: Record<string, any>;
}

export interface LearningData {
  emailId: string;
  userFeedback: 'correct' | 'incorrect' | 'spam' | 'important';
  originalClassification: EmailCategory;
  correctClassification?: EmailCategory;
  timestamp: string;
}

export class EmailPatternEngine {
  private patterns = new Map<string, Pattern>();
  private learningHistory = new Map<string, LearningData[]>();
  private senderFrequency = new Map<
    string,
    { count: number; lastSeen: Date; categories: EmailCategory[] }
  >();
  private timePatterns = new Map<
    string,
    { hourCounts: number[]; dayCounts: number[] }
  >();

  constructor() {
    this.initializeDefaultPatterns();
  }

  /**
   * Analyze email against all patterns and return matches
   */
  public async analyzePatterns(email: EmailMetadata): Promise<PatternMatch[]> {
    const matches: PatternMatch[] = [];

    // Update frequency tracking
    this.updateSenderFrequency(email);
    this.updateTimePatterns(email);

    // Test against all patterns
    for (const [patternId, pattern] of this.patterns) {
      const match = await this.testPattern(email, pattern);
      if (match.score > 0) {
        matches.push({
          patternId,
          score: match.score,
          confidence: match.confidence,
          matchedRules: match.matchedRules,
          context: match.context,
        });
      }
    }

    // Sort by score descending
    matches.sort((a, b) => b.score - a.score);

    logger.debug(
      {
        emailId: email.id,
        matchCount: matches.length,
        topMatch: matches[0]?.patternId,
      },
      'Pattern analysis completed',
    );

    return matches;
  }

  /**
   * Test a single pattern against an email
   */
  private async testPattern(
    email: EmailMetadata,
    pattern: Pattern,
  ): Promise<{
    score: number;
    confidence: number;
    matchedRules: string[];
    context: Record<string, any>;
  }> {
    const result = {
      score: 0,
      confidence: 0,
      matchedRules: [] as string[],
      context: {} as Record<string, any>,
    };

    let totalWeight = 0;
    let matchedWeight = 0;

    for (const rule of pattern.rules) {
      totalWeight += rule.weight;
      const ruleResult = await this.testRule(email, rule);

      if (ruleResult.matched) {
        matchedWeight += rule.weight;
        result.matchedRules.push(`${rule.type}:${rule.operator}`);
        if (ruleResult.context) {
          Object.assign(result.context, ruleResult.context);
        }
      }
    }

    if (matchedWeight > 0) {
      result.score = (matchedWeight / totalWeight) * pattern.weight;
      result.confidence = pattern.confidence * (matchedWeight / totalWeight);

      // Apply time decay if enabled
      if (pattern.timeDecay) {
        const decayFactor = this.calculateTimeDecay(email.timestamp);
        result.score *= decayFactor;
        result.confidence *= decayFactor;
      }
    }

    return result;
  }

  /**
   * Test a single rule against an email
   */
  private async testRule(
    email: EmailMetadata,
    rule: PatternRule,
  ): Promise<{
    matched: boolean;
    context?: Record<string, any>;
  }> {
    const caseSensitive = rule.caseSensitive ?? false;

    switch (rule.type) {
      case 'sender':
        return this.testSenderRule(email, rule, caseSensitive);
      case 'subject':
        return this.testSubjectRule(email, rule, caseSensitive);
      case 'content':
        return this.testContentRule(email, rule, caseSensitive);
      case 'time':
        return this.testTimeRule(email, rule);
      case 'frequency':
        return this.testFrequencyRule(email, rule);
      case 'chain':
        return this.testChainRule(email, rule);
      default:
        return { matched: false };
    }
  }

  private testSenderRule(
    email: EmailMetadata,
    rule: PatternRule,
    caseSensitive: boolean,
  ): {
    matched: boolean;
    context?: Record<string, any>;
  } {
    const sender = caseSensitive ? email.from : email.from.toLowerCase();
    const value = caseSensitive
      ? (rule.value as string)
      : (rule.value as string).toLowerCase();

    let matched = false;

    switch (rule.operator) {
      case 'contains':
        matched = sender.includes(value);
        break;
      case 'matches':
        matched = sender === value;
        break;
      case 'starts_with':
        matched = sender.startsWith(value);
        break;
      case 'ends_with':
        matched = sender.endsWith(value);
        break;
      case 'regex':
        matched = new RegExp(value).test(sender);
        break;
      case 'exists':
        matched = sender.length > 0;
        break;
    }

    return {
      matched,
      context: matched ? { matchedSender: email.from } : undefined,
    };
  }

  private testSubjectRule(
    email: EmailMetadata,
    rule: PatternRule,
    caseSensitive: boolean,
  ): {
    matched: boolean;
    context?: Record<string, any>;
  } {
    const subject = caseSensitive ? email.subject : email.subject.toLowerCase();
    const value = caseSensitive
      ? (rule.value as string)
      : (rule.value as string).toLowerCase();

    let matched = false;

    switch (rule.operator) {
      case 'contains':
        matched = subject.includes(value);
        break;
      case 'matches':
        matched = subject === value;
        break;
      case 'starts_with':
        matched = subject.startsWith(value);
        break;
      case 'ends_with':
        matched = subject.endsWith(value);
        break;
      case 'regex':
        matched = new RegExp(value).test(subject);
        break;
      case 'exists':
        matched = subject.length > 0;
        break;
    }

    return {
      matched,
      context: matched ? { matchedSubject: email.subject } : undefined,
    };
  }

  private testContentRule(
    email: EmailMetadata,
    rule: PatternRule,
    caseSensitive: boolean,
  ): {
    matched: boolean;
    context?: Record<string, any>;
  } {
    if (!email.content) return { matched: false };

    const content = caseSensitive ? email.content : email.content.toLowerCase();
    const value = caseSensitive
      ? (rule.value as string)
      : (rule.value as string).toLowerCase();

    let matched = false;

    switch (rule.operator) {
      case 'contains':
        matched = content.includes(value);
        break;
      case 'regex':
        matched = new RegExp(value).test(content);
        break;
      case 'count':
        const count = (content.match(new RegExp(value, 'g')) || []).length;
        matched = count >= (rule.value as number);
        break;
    }

    return {
      matched,
      context: matched ? { contentLength: email.content.length } : undefined,
    };
  }

  private testTimeRule(
    email: EmailMetadata,
    rule: PatternRule,
  ): {
    matched: boolean;
    context?: Record<string, any>;
  } {
    const emailDate = new Date(email.timestamp);
    const hour = emailDate.getHours();
    const dayOfWeek = emailDate.getDay();

    let matched = false;
    let context: Record<string, any> = {};

    switch (rule.operator) {
      case 'time_range':
        if (typeof rule.value === 'string' && rule.value.includes('-')) {
          const [start, end] = rule.value.split('-').map(Number);
          matched = hour >= start && hour <= end;
          context = { hour, timeRange: rule.value };
        }
        break;
      case 'contains':
        if (rule.field === 'weekend') {
          matched = dayOfWeek === 0 || dayOfWeek === 6;
          context = { dayOfWeek, isWeekend: matched };
        }
        break;
    }

    return { matched, context };
  }

  private testFrequencyRule(
    email: EmailMetadata,
    rule: PatternRule,
  ): {
    matched: boolean;
    context?: Record<string, any>;
  } {
    const senderData = this.senderFrequency.get(email.from);
    if (!senderData) return { matched: false };

    let matched = false;
    const context = {
      senderFrequency: senderData.count,
      lastSeen: senderData.lastSeen,
    };

    switch (rule.operator) {
      case 'count':
        matched = senderData.count >= (rule.value as number);
        break;
      case 'exists':
        matched = senderData.count > 0;
        break;
    }

    return { matched, context };
  }

  private testChainRule(
    email: EmailMetadata,
    rule: PatternRule,
  ): {
    matched: boolean;
    context?: Record<string, any>;
  } {
    // Test for email chains (Re:, Fwd:, etc.)
    const subject = email.subject.toLowerCase();

    let matched = false;
    const context: Record<string, any> = {};

    switch (rule.operator) {
      case 'contains':
        if (rule.value === 'reply') {
          matched = subject.startsWith('re:') || subject.includes('[reply]');
          context.isReply = matched;
        } else if (rule.value === 'forward') {
          matched = subject.startsWith('fwd:') || subject.startsWith('fw:');
          context.isForward = matched;
        }
        break;
    }

    return { matched, context };
  }

  private updateSenderFrequency(email: EmailMetadata): void {
    const existing = this.senderFrequency.get(email.from);
    if (existing) {
      existing.count++;
      existing.lastSeen = new Date();
    } else {
      this.senderFrequency.set(email.from, {
        count: 1,
        lastSeen: new Date(),
        categories: [],
      });
    }
  }

  private updateTimePatterns(email: EmailMetadata): void {
    const emailDate = new Date(email.timestamp);
    const hour = emailDate.getHours();
    const day = emailDate.getDay();

    const existing = this.timePatterns.get(email.from);
    if (existing) {
      existing.hourCounts[hour]++;
      existing.dayCounts[day]++;
    } else {
      const hourCounts = new Array(24).fill(0);
      const dayCounts = new Array(7).fill(0);
      hourCounts[hour] = 1;
      dayCounts[day] = 1;
      this.timePatterns.set(email.from, { hourCounts, dayCounts });
    }
  }

  private calculateTimeDecay(timestamp: string): number {
    const emailDate = new Date(timestamp);
    const now = new Date();
    const hoursOld = (now.getTime() - emailDate.getTime()) / (1000 * 60 * 60);

    // Decay factor: 1.0 for new emails, 0.5 after 24 hours, 0.1 after 7 days
    if (hoursOld <= 1) return 1.0;
    if (hoursOld <= 24) return 0.8;
    if (hoursOld <= 168) return 0.5; // 7 days
    return 0.1;
  }

  /**
   * Add learning feedback to improve pattern matching
   */
  public addLearningData(data: LearningData): void {
    const existing = this.learningHistory.get(data.emailId);
    if (existing) {
      existing.push(data);
    } else {
      this.learningHistory.set(data.emailId, [data]);
    }

    // Update patterns based on feedback
    this.updatePatternsFromFeedback(data);

    logger.info(
      {
        emailId: data.emailId,
        feedback: data.userFeedback,
        originalClassification: data.originalClassification,
      },
      'Learning data added for pattern improvement',
    );
  }

  private updatePatternsFromFeedback(data: LearningData): void {
    // Find patterns that matched this email
    const relevantPatterns = Array.from(this.patterns.values()).filter(
      (p) => p.category === data.originalClassification && p.learningEnabled,
    );

    for (const pattern of relevantPatterns) {
      if (data.userFeedback === 'incorrect') {
        // Reduce pattern weight slightly
        pattern.weight *= 0.95;
        pattern.confidence *= 0.98;
      } else if (data.userFeedback === 'correct') {
        // Increase pattern weight slightly
        pattern.weight *= 1.02;
        pattern.confidence *= 1.01;
      }

      // Clamp values
      pattern.weight = Math.max(0.1, Math.min(2.0, pattern.weight));
      pattern.confidence = Math.max(0.1, Math.min(1.0, pattern.confidence));
    }
  }

  /**
   * Get sender frequency data
   */
  public getSenderFrequency(
    sender: string,
  ):
    | { count: number; lastSeen: Date; categories: EmailCategory[] }
    | undefined {
    return this.senderFrequency.get(sender);
  }

  /**
   * Get time patterns for a sender
   */
  public getTimePatterns(
    sender: string,
  ): { hourCounts: number[]; dayCounts: number[] } | undefined {
    return this.timePatterns.get(sender);
  }

  /**
   * Add a custom pattern
   */
  public addPattern(pattern: Pattern): void {
    this.patterns.set(pattern.id, pattern);
    logger.info(
      { patternId: pattern.id, name: pattern.name },
      'Custom pattern added',
    );
  }

  /**
   * Remove a pattern
   */
  public removePattern(patternId: string): boolean {
    const removed = this.patterns.delete(patternId);
    if (removed) {
      logger.info({ patternId }, 'Pattern removed');
    }
    return removed;
  }

  /**
   * Get all patterns
   */
  public getPatterns(): Map<string, Pattern> {
    return new Map(this.patterns);
  }

  /**
   * Initialize default patterns for common email types
   */
  private initializeDefaultPatterns(): void {
    // VIP Business Communication Pattern
    this.addPattern({
      id: 'vip-business',
      name: 'VIP Business Communication',
      category: EmailCategory.BUSINESS_CRITICAL,
      weight: 1.5,
      confidence: 0.9,
      learningEnabled: true,
      rules: [
        {
          type: 'sender',
          operator: 'contains',
          value: '@tpglife.com',
          weight: 40,
        },
        {
          type: 'sender',
          operator: 'contains',
          value: '@callagylaw.com',
          weight: 45,
        },
        {
          type: 'subject',
          operator: 'contains',
          value: 'urgent',
          weight: 30,
        },
        {
          type: 'time',
          operator: 'contains',
          field: 'weekend',
          value: 'true',
          weight: 20,
        },
      ],
    });

    // Financial/Commission Pattern
    this.addPattern({
      id: 'financial-commission',
      name: 'Financial and Commission Emails',
      category: EmailCategory.FINANCIAL_INSURANCE,
      weight: 1.3,
      confidence: 0.85,
      learningEnabled: true,
      rules: [
        {
          type: 'subject',
          operator: 'regex',
          value: '(commission|payment|invoice|statement)',
          weight: 35,
        },
        {
          type: 'sender',
          operator: 'regex',
          value: '(bank|payment|finance|mutual|transamerica)',
          weight: 30,
        },
        {
          type: 'content',
          operator: 'contains',
          value: '$',
          weight: 15,
        },
      ],
    });

    // Client Communication Pattern
    this.addPattern({
      id: 'client-communication',
      name: 'Client Communications',
      category: EmailCategory.CLIENT_COMMUNICATIONS,
      weight: 1.2,
      confidence: 0.8,
      learningEnabled: true,
      rules: [
        {
          type: 'subject',
          operator: 'regex',
          value: '(policy|coverage|claim|premium)',
          weight: 30,
        },
        {
          type: 'content',
          operator: 'regex',
          value: '(question|help|inquiry)',
          weight: 25,
        },
        {
          type: 'chain',
          operator: 'contains',
          value: 'reply',
          weight: 20,
        },
      ],
    });

    // Recruitment Prospect Pattern
    this.addPattern({
      id: 'recruitment-prospect',
      name: 'Recruitment Prospects',
      category: EmailCategory.RECRUITMENT_PROSPECTS,
      weight: 1.4,
      confidence: 0.75,
      learningEnabled: true,
      rules: [
        {
          type: 'subject',
          operator: 'regex',
          value: '(agent|recruit|opportunity|career|position)',
          weight: 35,
        },
        {
          type: 'content',
          operator: 'regex',
          value: '(resume|cv|interested|join|team)',
          weight: 25,
        },
        {
          type: 'frequency',
          operator: 'count',
          value: 1,
          weight: 15, // First-time senders often prospects
        },
      ],
    });

    // Calendar/Meeting Pattern
    this.addPattern({
      id: 'calendar-meeting',
      name: 'Calendar and Meeting Requests',
      category: EmailCategory.CALENDAR_SCHEDULING,
      weight: 1.3,
      confidence: 0.85,
      learningEnabled: true,
      rules: [
        {
          type: 'subject',
          operator: 'regex',
          value: '(meeting|appointment|schedule|calendar|zoom)',
          weight: 40,
        },
        {
          type: 'content',
          operator: 'regex',
          value: '(when|time|available|calendar|schedule)',
          weight: 25,
        },
        {
          type: 'time',
          operator: 'time_range',
          value: '9-17', // Business hours
          weight: 15,
        },
      ],
    });

    // Spam/Marketing Pattern
    this.addPattern({
      id: 'spam-marketing',
      name: 'Spam and Marketing',
      category: EmailCategory.SPAM_NOISE,
      weight: 1.1,
      confidence: 0.9,
      timeDecay: false,
      learningEnabled: true,
      rules: [
        {
          type: 'sender',
          operator: 'regex',
          value: '(noreply|no-reply|marketing|promo)',
          weight: 30,
        },
        {
          type: 'subject',
          operator: 'regex',
          value: '(unsubscribe|newsletter|deal|sale|limited time)',
          weight: 35,
        },
        {
          type: 'content',
          operator: 'regex',
          value: '(click here|act now|free|winner)',
          weight: 25,
        },
      ],
    });

    // Off-hours Critical Pattern
    this.addPattern({
      id: 'off-hours-critical',
      name: 'Off-Hours Critical Emails',
      category: EmailCategory.BUSINESS_CRITICAL,
      weight: 1.6,
      confidence: 0.8,
      learningEnabled: true,
      rules: [
        {
          type: 'time',
          operator: 'time_range',
          value: '22-6', // Late night/early morning
          weight: 40,
        },
        {
          type: 'frequency',
          operator: 'count',
          value: 5, // Known sender
          weight: 20,
        },
        {
          type: 'subject',
          operator: 'regex',
          value: '(urgent|emergency|asap|immediate)',
          weight: 30,
        },
      ],
    });

    logger.info(
      { patternCount: this.patterns.size },
      'Default email patterns initialized',
    );
  }
}
