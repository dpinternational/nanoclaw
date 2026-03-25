/**
 * ENHANCED EMAIL CLASSIFICATION ENGINE
 * Phase 1 of David's Inbox Zero automation system
 */

import { logger } from './logger.js';

export interface EmailMetadata {
  from: string;
  fromName?: string;
  subject: string;
  content?: string;
  timestamp: string;
  id: string;
  threadId?: string;
  labels?: string[];
  inReplyTo?: string;
}

export interface ClassificationResult {
  category: EmailCategory;
  priority: Priority;
  urgency: UrgencyLevel;
  action: EmailAction;
  reason: string;
  discordChannel: string;
  escalation?: EscalationConfig;
  autoActions?: AutoAction[];
  routing?: RoutingConfig;
  sentiment?: number; // -1 to 1 scale
  confidence: number; // 0 to 1 scale
}

export enum EmailCategory {
  BUSINESS_CRITICAL = 'business_critical',
  CLIENT_COMMUNICATIONS = 'client_communications',
  RECRUITMENT_PROSPECTS = 'recruitment_prospects',
  CALENDAR_SCHEDULING = 'calendar_scheduling',
  FINANCIAL_INSURANCE = 'financial_insurance',
  VENDOR_OPERATIONAL = 'vendor_operational',
  MARKETING_ANALYTICS = 'marketing_analytics',
  PERSONAL_ADMIN = 'personal_admin',
  SPAM_NOISE = 'spam_noise'
}

export enum Priority {
  CRITICAL = 'CRITICAL',
  HIGH = 'HIGH',
  MEDIUM = 'MEDIUM',
  LOW = 'LOW',
  ARCHIVE = 'ARCHIVE'
}

export enum UrgencyLevel {
  IMMEDIATE = 'immediate',    // <5 min
  FAST_TRACK = 'fast_track',  // <30 min
  STANDARD = 'standard',      // <2 hrs
  BATCH = 'batch',           // Next scheduled run
  NONE = 'none'              // No urgency
}

export enum EmailAction {
  IMMEDIATE_ALERT = 'immediate_alert',
  PRIORITY_ROUTE = 'priority_route',
  STANDARD_PROCESS = 'standard_process',
  BATCH_PROCESS = 'batch_process',
  AUTO_ARCHIVE = 'auto_archive',
  SPAM_FILTER = 'spam_filter',
  ESCALATE = 'escalate'
}

export interface EscalationConfig {
  type: 'time_based' | 'keyword_based' | 'sender_based';
  delayMs?: number;
  channels?: string[];
  mentions?: string[];
}

export interface AutoAction {
  type: 'reply' | 'forward' | 'archive' | 'label' | 'calendar';
  config: Record<string, any>;
}

export interface RoutingConfig {
  primary: string;
  fallback?: string;
  ccChannels?: string[];
}

export interface SenderReputation {
  domain: string;
  score: number; // 0-100
  category: 'vip' | 'trusted' | 'regular' | 'suspicious' | 'blocked';
  interactionCount: number;
  lastSeen: string;
  responseRate?: number;
}

export class EmailClassificationEngine {
  private senderReputations = new Map<string, SenderReputation>();
  private keywordWeights = new Map<string, number>();
  private timeBasedPatterns = new Map<string, number>();

  // SIMPLIFIED SINGLE CHANNEL CONFIGURATION
  private discordChannels = {
    EMAIL_TRIAGE: '1484841234567890128',         // Single unified email triage channel
    // Keep fallback references for backwards compatibility
    BUSINESS_CRITICAL: '1484841234567890128',
    CLIENT_COMMUNICATIONS: '1484841234567890128',
    RECRUITMENT: '1484841234567890128',
    FINANCIAL: '1484841234567890128',
    CALENDAR: '1484841234567890128',
    VENDOR: '1484841234567890128',
    ANALYTICS: '1484841234567890128',
    GENERAL: '1484841234567890128',
    ARCHIVE: '1484841234567890128'
  };

  // VIP sender patterns (case-insensitive)
  private vipSenders = [
    '@callagylaw.com',
    'davidprice@tpglife.com',
    '@tpglife.com',
    '@premiersmi.com',
    '@mutualofomaha.com',
    '@transamerica.com',
    '@aglife.com',
    '@corebridge.com'
  ];

  // High priority keywords by category
  private criticalKeywords = [
    'urgent', 'immediate', 'asap', 'emergency', 'critical',
    'legal', 'lawsuit', 'court', 'deadline', 'compliance',
    'complaint', 'issue', 'problem', 'error', 'failure'
  ];

  private financialKeywords = [
    'commission', 'payment', 'invoice', 'statement', 'earnings',
    'compensation', '1099', 'tax', 'deposit', 'wire', 'ach',
    'overdue', 'balance', 'refund', 'chargeback'
  ];

  private clientKeywords = [
    'client', 'customer', 'policy', 'coverage', 'claim',
    'beneficiary', 'application', 'quote', 'premium',
    'cancellation', 'renewal', 'service'
  ];

  private recruitmentKeywords = [
    'agent', 'recruit', 'interview', 'hire', 'opportunity',
    'partnership', 'join', 'career', 'position', 'resume',
    'application', 'interested', 'team'
  ];

  private calendarKeywords = [
    'meeting', 'appointment', 'schedule', 'calendar', 'zoom',
    'call', 'conference', 'reschedule', 'cancel', 'confirm',
    'reminder', 'today', 'tomorrow', 'time'
  ];

  private spamIndicators = [
    'unsubscribe', 'newsletter', 'marketing', 'promotion',
    'deal', 'sale', 'discount', 'offer', 'limited time',
    'click here', 'act now', 'free', 'winner', 'congratulations'
  ];

  constructor() {
    this.initializeKeywordWeights();
    this.loadSenderReputations();
  }

  /**
   * Main classification method
   */
  public async classifyEmail(email: EmailMetadata): Promise<ClassificationResult> {
    logger.debug({ emailId: email.id }, 'Starting email classification');

    // Initial scoring
    let scores = this.initializeScores();

    // Apply classification rules
    this.analyzeSender(email, scores);
    this.analyzeSubject(email, scores);
    this.analyzeContent(email, scores);
    this.analyzeTimeContext(email, scores);
    this.applySenderReputation(email, scores);

    // Determine final classification
    const result = this.finalizeClassification(email, scores);

    // Update sender reputation
    this.updateSenderReputation(email);

    logger.info({
      emailId: email.id,
      category: result.category,
      priority: result.priority,
      confidence: result.confidence
    }, 'Email classified');

    return result;
  }

  private initializeScores(): Record<EmailCategory, number> {
    return Object.values(EmailCategory).reduce((acc, category) => {
      acc[category] = 0;
      return acc;
    }, {} as Record<EmailCategory, number>);
  }

  private analyzeSender(email: EmailMetadata, scores: Record<EmailCategory, number>): void {
    const fromLower = email.from.toLowerCase();
    const fromDomain = this.extractDomain(fromLower);

    // VIP sender check
    if (this.isVipSender(fromLower)) {
      scores[EmailCategory.BUSINESS_CRITICAL] += 50;
      return;
    }

    // Domain-based classification
    if (this.isFinancialDomain(fromDomain)) {
      scores[EmailCategory.FINANCIAL_INSURANCE] += 40;
    }

    if (this.isClientDomain(fromDomain)) {
      scores[EmailCategory.CLIENT_COMMUNICATIONS] += 30;
    }

    if (this.isMarketingDomain(fromDomain)) {
      scores[EmailCategory.MARKETING_ANALYTICS] += 20;
    }

    if (this.isSpamDomain(fromDomain)) {
      scores[EmailCategory.SPAM_NOISE] += 60;
    }

    // NoReply patterns
    if (fromLower.includes('noreply') || fromLower.includes('no-reply')) {
      scores[EmailCategory.MARKETING_ANALYTICS] += 15;
      scores[EmailCategory.SPAM_NOISE] += 10;
    }
  }

  private analyzeSubject(email: EmailMetadata, scores: Record<EmailCategory, number>): void {
    const subject = email.subject.toLowerCase();

    // Critical keywords
    this.criticalKeywords.forEach(keyword => {
      if (subject.includes(keyword)) {
        scores[EmailCategory.BUSINESS_CRITICAL] += 25;
      }
    });

    // Financial keywords
    this.financialKeywords.forEach(keyword => {
      if (subject.includes(keyword)) {
        scores[EmailCategory.FINANCIAL_INSURANCE] += 20;
      }
    });

    // Client keywords
    this.clientKeywords.forEach(keyword => {
      if (subject.includes(keyword)) {
        scores[EmailCategory.CLIENT_COMMUNICATIONS] += 20;
      }
    });

    // Recruitment keywords
    this.recruitmentKeywords.forEach(keyword => {
      if (subject.includes(keyword)) {
        scores[EmailCategory.RECRUITMENT_PROSPECTS] += 20;
      }
    });

    // Calendar keywords
    this.calendarKeywords.forEach(keyword => {
      if (subject.includes(keyword)) {
        scores[EmailCategory.CALENDAR_SCHEDULING] += 25;
      }
    });

    // Spam indicators
    this.spamIndicators.forEach(indicator => {
      if (subject.includes(indicator)) {
        scores[EmailCategory.SPAM_NOISE] += 15;
      }
    });

    // Time urgency indicators
    if (this.hasTimeUrgency(subject)) {
      scores[EmailCategory.BUSINESS_CRITICAL] += 30;
    }
  }

  private analyzeContent(email: EmailMetadata, scores: Record<EmailCategory, number>): void {
    if (!email.content) return;

    const content = email.content.toLowerCase();
    const contentLength = content.length;

    // Very short emails often spam/automated
    if (contentLength < 50) {
      scores[EmailCategory.SPAM_NOISE] += 10;
    }

    // Very long emails often detailed business communication
    if (contentLength > 2000) {
      scores[EmailCategory.BUSINESS_CRITICAL] += 15;
      scores[EmailCategory.CLIENT_COMMUNICATIONS] += 10;
    }

    // Sentiment analysis (basic)
    const sentiment = this.analyzeSentiment(content);
    if (sentiment < -0.3) { // Negative sentiment
      scores[EmailCategory.BUSINESS_CRITICAL] += 20;
      scores[EmailCategory.CLIENT_COMMUNICATIONS] += 15;
    }

    // Signature detection
    if (this.hasBusinessSignature(content)) {
      scores[EmailCategory.CLIENT_COMMUNICATIONS] += 10;
      scores[EmailCategory.BUSINESS_CRITICAL] += 10;
    }
  }

  private analyzeTimeContext(email: EmailMetadata, scores: Record<EmailCategory, number>): void {
    const emailTime = new Date(email.timestamp);
    const currentTime = new Date();
    const hoursSinceReceived = (currentTime.getTime() - emailTime.getTime()) / (1000 * 60 * 60);

    // Age-based scoring
    if (hoursSinceReceived > 24) {
      // Older emails less urgent unless critical
      scores[EmailCategory.BUSINESS_CRITICAL] -= 10;
    }

    // Time of day analysis
    const hour = emailTime.getHours();
    if ((hour >= 22 || hour <= 6) && this.isBusinessEmail(email)) {
      // Off-hours business emails are often urgent
      scores[EmailCategory.BUSINESS_CRITICAL] += 20;
    }

    // Weekend emails
    const dayOfWeek = emailTime.getDay();
    if ((dayOfWeek === 0 || dayOfWeek === 6) && this.isBusinessEmail(email)) {
      scores[EmailCategory.BUSINESS_CRITICAL] += 15;
    }
  }

  private applySenderReputation(email: EmailMetadata, scores: Record<EmailCategory, number>): void {
    const reputation = this.getSenderReputation(email.from);
    if (!reputation) return;

    const multiplier = reputation.score / 100;

    if (reputation.category === 'vip') {
      scores[EmailCategory.BUSINESS_CRITICAL] += 40 * multiplier;
    } else if (reputation.category === 'trusted') {
      scores[EmailCategory.CLIENT_COMMUNICATIONS] += 20 * multiplier;
    } else if (reputation.category === 'suspicious') {
      scores[EmailCategory.SPAM_NOISE] += 30;
    } else if (reputation.category === 'blocked') {
      scores[EmailCategory.SPAM_NOISE] += 80;
    }
  }

  private finalizeClassification(email: EmailMetadata, scores: Record<EmailCategory, number>): ClassificationResult {
    // Find highest scoring category
    const topCategory = Object.entries(scores).reduce((max, [category, score]) =>
      score > max.score ? { category: category as EmailCategory, score } : max,
      { category: EmailCategory.PERSONAL_ADMIN, score: 0 }
    );

    const category = topCategory.category;
    const confidence = Math.min(topCategory.score / 100, 1);

    // Determine priority and urgency
    const priority = this.calculatePriority(category, topCategory.score, email);
    const urgency = this.calculateUrgency(category, priority, email);

    // Determine action
    const action = this.determineAction(category, priority, urgency);

    // Set Discord routing
    const discordChannel = this.getDiscordChannel(category);

    // Generate reason
    const reason = this.generateReason(category, topCategory.score, email);

    // Configure escalation if needed
    const escalation = this.configureEscalation(category, priority, urgency);

    return {
      category,
      priority,
      urgency,
      action,
      reason,
      discordChannel,
      escalation,
      confidence,
      sentiment: email.content ? this.analyzeSentiment(email.content.toLowerCase()) : undefined,
      routing: {
        primary: discordChannel,
        fallback: this.discordChannels.EMAIL_TRIAGE
      }
    };
  }

  private calculatePriority(category: EmailCategory, score: number, email: EmailMetadata): Priority {
    if (category === EmailCategory.SPAM_NOISE && score > 40) {
      return Priority.ARCHIVE;
    }

    if (category === EmailCategory.BUSINESS_CRITICAL || score > 80) {
      return Priority.CRITICAL;
    }

    if (category === EmailCategory.FINANCIAL_INSURANCE ||
        category === EmailCategory.CLIENT_COMMUNICATIONS ||
        this.isVipSender(email.from.toLowerCase())) {
      return Priority.HIGH;
    }

    if (category === EmailCategory.RECRUITMENT_PROSPECTS ||
        category === EmailCategory.CALENDAR_SCHEDULING) {
      return Priority.MEDIUM;
    }

    return Priority.LOW;
  }

  private calculateUrgency(category: EmailCategory, priority: Priority, email: EmailMetadata): UrgencyLevel {
    const subject = email.subject.toLowerCase();

    // Immediate urgency triggers
    if (priority === Priority.CRITICAL ||
        this.hasTimeUrgency(subject) ||
        this.isCalendarConflict(email)) {
      return UrgencyLevel.IMMEDIATE;
    }

    // Fast track scenarios
    if (priority === Priority.HIGH ||
        category === EmailCategory.RECRUITMENT_PROSPECTS ||
        this.isMeetingRequest(subject)) {
      return UrgencyLevel.FAST_TRACK;
    }

    // Standard processing
    if (priority === Priority.MEDIUM) {
      return UrgencyLevel.STANDARD;
    }

    // Batch processing
    if (priority === Priority.LOW) {
      return UrgencyLevel.BATCH;
    }

    return UrgencyLevel.NONE;
  }

  private determineAction(category: EmailCategory, priority: Priority, urgency: UrgencyLevel): EmailAction {
    if (urgency === UrgencyLevel.IMMEDIATE) {
      return EmailAction.IMMEDIATE_ALERT;
    }

    if (urgency === UrgencyLevel.FAST_TRACK) {
      return EmailAction.PRIORITY_ROUTE;
    }

    if (priority === Priority.ARCHIVE) {
      return EmailAction.AUTO_ARCHIVE;
    }

    if (category === EmailCategory.SPAM_NOISE) {
      return EmailAction.SPAM_FILTER;
    }

    if (urgency === UrgencyLevel.STANDARD) {
      return EmailAction.STANDARD_PROCESS;
    }

    return EmailAction.BATCH_PROCESS;
  }

  private configureEscalation(category: EmailCategory, priority: Priority, urgency: UrgencyLevel): EscalationConfig | undefined {
    if (urgency === UrgencyLevel.IMMEDIATE) {
      return {
        type: 'time_based',
        delayMs: 5 * 60 * 1000, // 5 minutes
        channels: [this.discordChannels.BUSINESS_CRITICAL],
        mentions: ['@here']
      };
    }

    if (urgency === UrgencyLevel.FAST_TRACK) {
      return {
        type: 'time_based',
        delayMs: 30 * 60 * 1000, // 30 minutes
        channels: [this.discordChannels.BUSINESS_CRITICAL]
      };
    }

    return undefined;
  }

  private getDiscordChannel(category: EmailCategory): string {
    // SIMPLIFIED: All emails go to the single email-triage channel
    // Intelligence is in the formatting and priority indicators, not channel routing
    return this.discordChannels.EMAIL_TRIAGE;
  }

  private generateReason(category: EmailCategory, score: number, email: EmailMetadata): string {
    const reasons: string[] = [];

    if (this.isVipSender(email.from.toLowerCase())) {
      reasons.push('VIP sender');
    }

    if (this.hasTimeUrgency(email.subject.toLowerCase())) {
      reasons.push('time-sensitive');
    }

    if (score > 80) {
      reasons.push('high confidence match');
    }

    const categoryReasons: Record<EmailCategory, string> = {
      [EmailCategory.BUSINESS_CRITICAL]: 'Critical business issue requiring immediate attention',
      [EmailCategory.CLIENT_COMMUNICATIONS]: 'Client/customer communication',
      [EmailCategory.RECRUITMENT_PROSPECTS]: 'Potential agent recruitment opportunity',
      [EmailCategory.CALENDAR_SCHEDULING]: 'Meeting or scheduling request',
      [EmailCategory.FINANCIAL_INSURANCE]: 'Financial, commission, or insurance related',
      [EmailCategory.VENDOR_OPERATIONAL]: 'Vendor or operational communication',
      [EmailCategory.MARKETING_ANALYTICS]: 'Marketing or analytics report',
      [EmailCategory.PERSONAL_ADMIN]: 'Personal or administrative matter',
      [EmailCategory.SPAM_NOISE]: 'Low-value or promotional content'
    };

    const baseReason = categoryReasons[category];
    return reasons.length > 0 ? `${baseReason} (${reasons.join(', ')})` : baseReason;
  }

  // Helper methods
  private initializeKeywordWeights(): void {
    // Initialize keyword scoring weights
    this.criticalKeywords.forEach(keyword => this.keywordWeights.set(keyword, 25));
    this.financialKeywords.forEach(keyword => this.keywordWeights.set(keyword, 20));
    this.clientKeywords.forEach(keyword => this.keywordWeights.set(keyword, 20));
    this.recruitmentKeywords.forEach(keyword => this.keywordWeights.set(keyword, 20));
    this.calendarKeywords.forEach(keyword => this.keywordWeights.set(keyword, 25));
    this.spamIndicators.forEach(keyword => this.keywordWeights.set(keyword, -15));
  }

  private loadSenderReputations(): void {
    // Load saved reputation data (would normally come from database)
    // For now, initialize with basic VIP patterns
    this.vipSenders.forEach(sender => {
      this.senderReputations.set(sender, {
        domain: sender,
        score: 95,
        category: 'vip',
        interactionCount: 10,
        lastSeen: new Date().toISOString(),
        responseRate: 0.9
      });
    });
  }

  private extractDomain(email: string): string {
    const match = email.match(/@([^>]+)/);
    return match ? match[1].toLowerCase() : '';
  }

  private isVipSender(email: string): boolean {
    return this.vipSenders.some(vip => email.includes(vip.toLowerCase()));
  }

  private isFinancialDomain(domain: string): boolean {
    const financialDomains = [
      'mutualofomaha.com', 'transamerica.com', 'aglife.com',
      'corebridge.com', 'paypal.com', 'venmo.com', 'chase.com',
      'bankofamerica.com', 'wellsfargo.com'
    ];
    return financialDomains.some(fd => domain.includes(fd));
  }

  private isClientDomain(domain: string): boolean {
    // This would be populated with known client domains
    return domain.includes('client') || domain.includes('customer');
  }

  private isMarketingDomain(domain: string): boolean {
    const marketingDomains = [
      'mailchimp.com', 'constantcontact.com', 'salesforce.com',
      'hubspot.com', 'klaviyo.com', 'sendgrid.com'
    ];
    return marketingDomains.some(md => domain.includes(md));
  }

  private isSpamDomain(domain: string): boolean {
    const spamDomains = [
      'tempmail.com', '10minutemail.com', 'guerrillamail.com'
    ];
    return spamDomains.some(sd => domain.includes(sd));
  }

  private hasTimeUrgency(text: string): boolean {
    const urgencyPatterns = [
      'urgent', 'asap', 'immediately', 'emergency', 'deadline',
      'today', 'tomorrow', 'by end of day', 'eod', 'this morning',
      'time sensitive', 'quick turnaround'
    ];
    return urgencyPatterns.some(pattern => text.includes(pattern));
  }

  private isCalendarConflict(email: EmailMetadata): boolean {
    const subject = email.subject.toLowerCase();
    return subject.includes('conflict') ||
           subject.includes('reschedule') ||
           (subject.includes('meeting') && subject.includes('today'));
  }

  private isMeetingRequest(subject: string): boolean {
    return subject.includes('meeting') ||
           subject.includes('schedule') ||
           subject.includes('call') ||
           subject.includes('appointment');
  }

  private isBusinessEmail(email: EmailMetadata): boolean {
    const businessIndicators = [
      ...this.vipSenders,
      'business', 'company', 'corp', 'llc', 'inc'
    ];
    return businessIndicators.some(indicator =>
      email.from.toLowerCase().includes(indicator.toLowerCase())
    );
  }

  private analyzeSentiment(content: string): number {
    // Basic sentiment analysis
    const positiveWords = ['great', 'excellent', 'good', 'happy', 'pleased', 'satisfied'];
    const negativeWords = ['problem', 'issue', 'complaint', 'unhappy', 'disappointed', 'frustrated'];

    let score = 0;
    positiveWords.forEach(word => {
      if (content.includes(word)) score += 0.1;
    });
    negativeWords.forEach(word => {
      if (content.includes(word)) score -= 0.15;
    });

    return Math.max(-1, Math.min(1, score));
  }

  private hasBusinessSignature(content: string): boolean {
    return content.includes('best regards') ||
           content.includes('sincerely') ||
           content.includes('@') && content.includes('phone') ||
           content.includes('title:') ||
           content.includes('company:');
  }

  private getSenderReputation(email: string): SenderReputation | undefined {
    const domain = this.extractDomain(email);
    return this.senderReputations.get(email) || this.senderReputations.get(domain);
  }

  private updateSenderReputation(email: EmailMetadata): void {
    const existing = this.getSenderReputation(email.from);
    if (existing) {
      existing.interactionCount++;
      existing.lastSeen = new Date().toISOString();
    } else {
      // Create new reputation entry
      this.senderReputations.set(email.from, {
        domain: this.extractDomain(email.from),
        score: 50, // Neutral starting score
        category: 'regular',
        interactionCount: 1,
        lastSeen: new Date().toISOString()
      });
    }
  }

  /**
   * Public method to get sender reputation for external use
   */
  public getSenderReputationScore(email: string): number {
    const reputation = this.getSenderReputation(email);
    return reputation ? reputation.score : 50; // Default neutral score
  }

  /**
   * Update sender reputation externally (e.g., based on user feedback)
   */
  public updateSenderScore(email: string, delta: number, category?: 'vip' | 'trusted' | 'regular' | 'suspicious' | 'blocked'): void {
    let reputation = this.getSenderReputation(email);
    if (!reputation) {
      reputation = {
        domain: this.extractDomain(email),
        score: 50,
        category: 'regular',
        interactionCount: 1,
        lastSeen: new Date().toISOString()
      };
      this.senderReputations.set(email, reputation);
    }

    reputation.score = Math.max(0, Math.min(100, reputation.score + delta));
    if (category) {
      reputation.category = category;
    }
  }
}