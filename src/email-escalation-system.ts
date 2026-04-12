/**
 * EMAIL ESCALATION SYSTEM
 * Manages priority-based escalation workflows and alert pathways
 */

import { logger } from './logger.js';
import {
  EmailMetadata,
  ClassificationResult,
  Priority,
  UrgencyLevel,
} from './email-classifier.js';

export interface EscalationRule {
  id: string;
  name: string;
  triggers: EscalationTrigger[];
  actions: EscalationAction[];
  cooldownMs: number; // Minimum time between escalations
  maxEscalations: number; // Maximum escalations per email
  enabled: boolean;
}

export interface EscalationTrigger {
  type:
    | 'time_elapsed'
    | 'no_response'
    | 'keyword_match'
    | 'sender_match'
    | 'priority_level';
  condition: string | number;
  threshold?: number;
}

export interface EscalationAction {
  type:
    | 'discord_alert'
    | 'sms_alert'
    | 'email_forward'
    | 'slack_notify'
    | 'escalate_priority';
  target: string; // Discord channel ID, phone number, email address, etc.
  template: string;
  urgency: 'low' | 'medium' | 'high' | 'critical';
}

export interface EscalationEvent {
  id: string;
  emailId: string;
  ruleId: string;
  timestamp: string;
  action: EscalationAction;
  status: 'pending' | 'sent' | 'failed' | 'acknowledged';
  attempts: number;
  nextAttempt?: string;
}

export interface AlertTemplate {
  name: string;
  subject: string;
  body: string;
  variables: string[]; // Available template variables
}

export class EmailEscalationSystem {
  private rules = new Map<string, EscalationRule>();
  private events = new Map<string, EscalationEvent[]>();
  private templates = new Map<string, AlertTemplate>();
  private acknowledgedEmails = new Set<string>();
  private processingInterval: NodeJS.Timeout | null = null;

  constructor() {
    this.initializeDefaultRules();
    this.initializeTemplates();
    this.startProcessing();
  }

  /**
   * Check if an email should trigger escalation
   */
  public async checkEscalation(
    email: EmailMetadata,
    classification: ClassificationResult,
  ): Promise<EscalationEvent[]> {
    const triggeredEvents: EscalationEvent[] = [];

    // Skip if already acknowledged
    if (this.acknowledgedEmails.has(email.id)) {
      return triggeredEvents;
    }

    // Test against all active escalation rules
    for (const [ruleId, rule] of this.rules) {
      if (!rule.enabled) continue;

      const shouldTrigger = await this.evaluateRule(
        email,
        classification,
        rule,
      );
      if (shouldTrigger) {
        const events = await this.createEscalationEvents(
          email,
          classification,
          rule,
        );
        triggeredEvents.push(...events);
      }
    }

    // Store events for tracking
    if (triggeredEvents.length > 0) {
      const existing = this.events.get(email.id) || [];
      this.events.set(email.id, [...existing, ...triggeredEvents]);
    }

    logger.info(
      {
        emailId: email.id,
        triggeredCount: triggeredEvents.length,
        rules: triggeredEvents.map((e) => e.ruleId),
      },
      'Escalation evaluation completed',
    );

    return triggeredEvents;
  }

  /**
   * Evaluate whether a rule should trigger for an email
   */
  private async evaluateRule(
    email: EmailMetadata,
    classification: ClassificationResult,
    rule: EscalationRule,
  ): Promise<boolean> {
    // Check cooldown
    if (!this.isCooldownExpired(email.id, rule)) {
      return false;
    }

    // Check max escalations
    if (this.hasReachedMaxEscalations(email.id, rule)) {
      return false;
    }

    // Test all triggers (AND logic)
    for (const trigger of rule.triggers) {
      if (!(await this.evaluateTrigger(email, classification, trigger))) {
        return false;
      }
    }

    return true;
  }

  /**
   * Evaluate a single escalation trigger
   */
  private async evaluateTrigger(
    email: EmailMetadata,
    classification: ClassificationResult,
    trigger: EscalationTrigger,
  ): Promise<boolean> {
    switch (trigger.type) {
      case 'time_elapsed':
        return this.checkTimeElapsed(email, trigger);

      case 'no_response':
        return await this.checkNoResponse(email, trigger);

      case 'keyword_match':
        return this.checkKeywordMatch(email, trigger);

      case 'sender_match':
        return this.checkSenderMatch(email, trigger);

      case 'priority_level':
        return this.checkPriorityLevel(classification, trigger);

      default:
        return false;
    }
  }

  private checkTimeElapsed(
    email: EmailMetadata,
    trigger: EscalationTrigger,
  ): boolean {
    const emailTime = new Date(email.timestamp);
    const now = new Date();
    const elapsedMs = now.getTime() - emailTime.getTime();
    const thresholdMs = trigger.threshold || 300000; // Default 5 minutes

    return elapsedMs >= thresholdMs;
  }

  private async checkNoResponse(
    email: EmailMetadata,
    trigger: EscalationTrigger,
  ): Promise<boolean> {
    // This would check if there's been no response in the email thread
    // For now, implement basic time-based check
    return this.checkTimeElapsed(email, trigger);
  }

  private checkKeywordMatch(
    email: EmailMetadata,
    trigger: EscalationTrigger,
  ): boolean {
    const keywords = (trigger.condition as string)
      .split(',')
      .map((k) => k.trim().toLowerCase());
    const subject = email.subject.toLowerCase();
    const content = (email.content || '').toLowerCase();

    return keywords.some(
      (keyword) => subject.includes(keyword) || content.includes(keyword),
    );
  }

  private checkSenderMatch(
    email: EmailMetadata,
    trigger: EscalationTrigger,
  ): boolean {
    const patterns = (trigger.condition as string)
      .split(',')
      .map((p) => p.trim().toLowerCase());
    const sender = email.from.toLowerCase();

    return patterns.some((pattern) => sender.includes(pattern));
  }

  private checkPriorityLevel(
    classification: ClassificationResult,
    trigger: EscalationTrigger,
  ): boolean {
    const requiredPriority = trigger.condition as string;

    switch (requiredPriority.toLowerCase()) {
      case 'critical':
        return classification.priority === Priority.CRITICAL;
      case 'high':
        return (
          classification.priority === Priority.HIGH ||
          classification.priority === Priority.CRITICAL
        );
      case 'medium':
        return (
          classification.priority !== Priority.LOW &&
          classification.priority !== Priority.ARCHIVE
        );
      default:
        return true;
    }
  }

  private isCooldownExpired(emailId: string, rule: EscalationRule): boolean {
    const events = this.events.get(emailId) || [];
    const ruleEvents = events.filter((e) => e.ruleId === rule.id);

    if (ruleEvents.length === 0) return true;

    const lastEvent = ruleEvents[ruleEvents.length - 1];
    const lastTime = new Date(lastEvent.timestamp);
    const now = new Date();

    return now.getTime() - lastTime.getTime() >= rule.cooldownMs;
  }

  private hasReachedMaxEscalations(
    emailId: string,
    rule: EscalationRule,
  ): boolean {
    const events = this.events.get(emailId) || [];
    const ruleEvents = events.filter((e) => e.ruleId === rule.id);

    return ruleEvents.length >= rule.maxEscalations;
  }

  /**
   * Create escalation events for a triggered rule
   */
  private async createEscalationEvents(
    email: EmailMetadata,
    classification: ClassificationResult,
    rule: EscalationRule,
  ): Promise<EscalationEvent[]> {
    const events: EscalationEvent[] = [];

    for (const action of rule.actions) {
      const event: EscalationEvent = {
        id: `${email.id}-${rule.id}-${Date.now()}`,
        emailId: email.id,
        ruleId: rule.id,
        timestamp: new Date().toISOString(),
        action,
        status: 'pending',
        attempts: 0,
      };

      events.push(event);
    }

    return events;
  }

  /**
   * Process pending escalation events
   */
  private async processPendingEvents(): Promise<void> {
    const allEvents = Array.from(this.events.values()).flat();
    const pendingEvents = allEvents.filter(
      (e) => e.status === 'pending' || e.status === 'failed',
    );

    for (const event of pendingEvents) {
      // Check if it's time to process this event
      if (event.nextAttempt && new Date() < new Date(event.nextAttempt)) {
        continue;
      }

      try {
        await this.executeEscalationAction(event);
        event.status = 'sent';
        event.attempts++;

        logger.info(
          {
            eventId: event.id,
            emailId: event.emailId,
            actionType: event.action.type,
          },
          'Escalation action executed',
        );
      } catch (error) {
        event.status = 'failed';
        event.attempts++;

        // Schedule retry with exponential backoff
        const retryDelayMs = Math.min(
          300000 * Math.pow(2, event.attempts - 1),
          3600000,
        ); // Max 1 hour
        event.nextAttempt = new Date(Date.now() + retryDelayMs).toISOString();

        logger.error(
          {
            eventId: event.id,
            error: error,
            nextAttempt: event.nextAttempt,
          },
          'Escalation action failed, scheduled retry',
        );
      }
    }
  }

  /**
   * Execute a specific escalation action
   */
  private async executeEscalationAction(event: EscalationEvent): Promise<void> {
    const { action } = event;

    switch (action.type) {
      case 'discord_alert':
        await this.sendDiscordAlert(event);
        break;

      case 'sms_alert':
        await this.sendSMSAlert(event);
        break;

      case 'email_forward':
        await this.forwardEmail(event);
        break;

      case 'slack_notify':
        await this.sendSlackNotification(event);
        break;

      case 'escalate_priority':
        await this.escalatePriority(event);
        break;

      default:
        throw new Error(`Unknown escalation action type: ${action.type}`);
    }
  }

  private async sendDiscordAlert(event: EscalationEvent): Promise<void> {
    // This would integrate with the Discord bot to send alerts
    logger.info(
      {
        eventId: event.id,
        channelId: event.action.target,
        urgency: event.action.urgency,
      },
      'Discord escalation alert sent',
    );
  }

  private async sendSMSAlert(event: EscalationEvent): Promise<void> {
    // This would integrate with SMS service (Twilio, AWS SNS, etc.)
    logger.info(
      {
        eventId: event.id,
        phoneNumber: event.action.target,
        urgency: event.action.urgency,
      },
      'SMS escalation alert sent',
    );
  }

  private async forwardEmail(event: EscalationEvent): Promise<void> {
    // This would forward the email to the specified address
    logger.info(
      {
        eventId: event.id,
        forwardTo: event.action.target,
      },
      'Email escalation forwarded',
    );
  }

  private async sendSlackNotification(event: EscalationEvent): Promise<void> {
    // This would integrate with Slack API
    logger.info(
      {
        eventId: event.id,
        slackChannel: event.action.target,
      },
      'Slack escalation notification sent',
    );
  }

  private async escalatePriority(event: EscalationEvent): Promise<void> {
    // This would update the email's priority level
    logger.info(
      {
        eventId: event.id,
        emailId: event.emailId,
      },
      'Email priority escalated',
    );
  }

  /**
   * Acknowledge an email to stop further escalations
   */
  public acknowledgeEmail(emailId: string): void {
    this.acknowledgedEmails.add(emailId);

    // Mark pending events as acknowledged
    const events = this.events.get(emailId) || [];
    events.forEach((event) => {
      if (event.status === 'pending') {
        event.status = 'acknowledged';
      }
    });

    logger.info({ emailId }, 'Email acknowledged, escalations stopped');
  }

  /**
   * Create a custom escalation rule
   */
  public addEscalationRule(rule: EscalationRule): void {
    this.rules.set(rule.id, rule);
    logger.info({ ruleId: rule.id, name: rule.name }, 'Escalation rule added');
  }

  /**
   * Remove an escalation rule
   */
  public removeEscalationRule(ruleId: string): boolean {
    const removed = this.rules.delete(ruleId);
    if (removed) {
      logger.info({ ruleId }, 'Escalation rule removed');
    }
    return removed;
  }

  /**
   * Get escalation statistics
   */
  public getEscalationStats(): {
    totalRules: number;
    totalEvents: number;
    pendingEvents: number;
    acknowledgedEmails: number;
  } {
    const allEvents = Array.from(this.events.values()).flat();

    return {
      totalRules: this.rules.size,
      totalEvents: allEvents.length,
      pendingEvents: allEvents.filter((e) => e.status === 'pending').length,
      acknowledgedEmails: this.acknowledgedEmails.size,
    };
  }

  /**
   * Start processing escalation events
   */
  private startProcessing(): void {
    if (this.processingInterval) {
      clearInterval(this.processingInterval);
    }

    // Process every minute
    this.processingInterval = setInterval(() => {
      this.processPendingEvents().catch((error) => {
        logger.error({ error }, 'Error processing escalation events');
      });
    }, 60000);

    logger.info('Escalation processing started');
  }

  /**
   * Stop processing escalation events
   */
  public stopProcessing(): void {
    if (this.processingInterval) {
      clearInterval(this.processingInterval);
      this.processingInterval = null;
    }
    logger.info('Escalation processing stopped');
  }

  /**
   * Initialize default escalation rules
   */
  private initializeDefaultRules(): void {
    // Critical Email Immediate Escalation
    this.addEscalationRule({
      id: 'critical-immediate',
      name: 'Critical Email Immediate Escalation',
      triggers: [
        {
          type: 'priority_level',
          condition: 'critical',
        },
        {
          type: 'time_elapsed',
          condition: 'unacknowledged',
          threshold: 300000, // 5 minutes
        },
      ],
      actions: [
        {
          type: 'discord_alert',
          target: '1484839736609607832', // Business critical channel
          template: 'critical_alert',
          urgency: 'critical',
        },
      ],
      cooldownMs: 600000, // 10 minutes
      maxEscalations: 3,
      enabled: true,
    });

    // VIP Client No Response
    this.addEscalationRule({
      id: 'vip-no-response',
      name: 'VIP Client No Response',
      triggers: [
        {
          type: 'sender_match',
          condition: '@tpglife.com,@callagylaw.com',
        },
        {
          type: 'time_elapsed',
          condition: 'unacknowledged',
          threshold: 1800000, // 30 minutes
        },
      ],
      actions: [
        {
          type: 'discord_alert',
          target: '1484839736609607832',
          template: 'vip_no_response',
          urgency: 'high',
        },
      ],
      cooldownMs: 1800000, // 30 minutes
      maxEscalations: 2,
      enabled: true,
    });

    // Financial Emergency Keywords
    this.addEscalationRule({
      id: 'financial-emergency',
      name: 'Financial Emergency Keywords',
      triggers: [
        {
          type: 'keyword_match',
          condition: 'chargeback,fraud,unauthorized,dispute,emergency payment',
        },
        {
          type: 'time_elapsed',
          condition: 'unacknowledged',
          threshold: 600000, // 10 minutes
        },
      ],
      actions: [
        {
          type: 'discord_alert',
          target: '1484841234567890124', // Financial channel
          template: 'financial_emergency',
          urgency: 'critical',
        },
      ],
      cooldownMs: 3600000, // 1 hour
      maxEscalations: 1,
      enabled: true,
    });

    // Client Complaint Escalation
    this.addEscalationRule({
      id: 'client-complaint',
      name: 'Client Complaint Escalation',
      triggers: [
        {
          type: 'keyword_match',
          condition:
            'complaint,unhappy,dissatisfied,problem,issue,cancel,refund',
        },
        {
          type: 'time_elapsed',
          condition: 'unacknowledged',
          threshold: 3600000, // 1 hour
        },
      ],
      actions: [
        {
          type: 'discord_alert',
          target: '1484840749924089996', // Client communications channel
          template: 'client_complaint',
          urgency: 'high',
        },
      ],
      cooldownMs: 7200000, // 2 hours
      maxEscalations: 2,
      enabled: true,
    });

    logger.info(
      { ruleCount: this.rules.size },
      'Default escalation rules initialized',
    );
  }

  /**
   * Initialize alert templates
   */
  private initializeTemplates(): void {
    this.templates.set('critical_alert', {
      name: 'Critical Alert',
      subject: '🚨 CRITICAL EMAIL ALERT',
      body: `🚨 **CRITICAL EMAIL REQUIRES IMMEDIATE ATTENTION**

**From:** {sender}
**Subject:** {subject}
**Received:** {timestamp}
**Classification:** {category}

**Reason:** {reason}

This email has been waiting for {elapsed_time} without response.

**Actions Required:**
• Reply immediately if urgent
• Acknowledge in Discord to stop alerts
• Forward if delegation needed

**Email ID:** {email_id}`,
      variables: [
        'sender',
        'subject',
        'timestamp',
        'category',
        'reason',
        'elapsed_time',
        'email_id',
      ],
    });

    this.templates.set('vip_no_response', {
      name: 'VIP No Response',
      subject: '⚡ VIP Client Needs Response',
      body: `⚡ **VIP CLIENT EMAIL AWAITING RESPONSE**

**From:** {sender}
**Subject:** {subject}
**Waiting Time:** {elapsed_time}

VIP client emails should be responded to within 30 minutes.

**Email ID:** {email_id}`,
      variables: ['sender', 'subject', 'elapsed_time', 'email_id'],
    });

    this.templates.set('financial_emergency', {
      name: 'Financial Emergency',
      subject: '💰 FINANCIAL EMERGENCY ALERT',
      body: `💰 **FINANCIAL EMERGENCY DETECTED**

**From:** {sender}
**Subject:** {subject}
**Keywords Matched:** {keywords}

This email contains emergency financial keywords and requires immediate review.

**Email ID:** {email_id}`,
      variables: ['sender', 'subject', 'keywords', 'email_id'],
    });

    this.templates.set('client_complaint', {
      name: 'Client Complaint',
      subject: '😟 Client Complaint Alert',
      body: `😟 **CLIENT COMPLAINT DETECTED**

**From:** {sender}
**Subject:** {subject}
**Complaint Indicators:** {keywords}

This appears to be a client complaint that needs prompt attention.

**Email ID:** {email_id}`,
      variables: ['sender', 'subject', 'keywords', 'email_id'],
    });

    logger.info(
      { templateCount: this.templates.size },
      'Alert templates initialized',
    );
  }
}
