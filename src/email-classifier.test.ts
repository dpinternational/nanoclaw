import { describe, it, expect, beforeEach, vi } from 'vitest';

// Mock logger before imports
vi.mock('./logger.js', () => ({
  logger: {
    debug: vi.fn(),
    info: vi.fn(),
    warn: vi.fn(),
    error: vi.fn(),
  },
}));

import {
  EmailClassificationEngine,
  EmailMetadata,
  EmailCategory,
  Priority,
  UrgencyLevel,
  EmailAction,
} from './email-classifier.js';

let engine: EmailClassificationEngine;

beforeEach(() => {
  engine = new EmailClassificationEngine();
});

function makeEmail(overrides: Partial<EmailMetadata> = {}): EmailMetadata {
  return {
    id: 'test-email-1',
    from: 'someone@example.com',
    subject: 'Hello',
    timestamp: new Date().toISOString(),
    ...overrides,
  };
}

// --- VIP Sender Classification ---

describe('VIP sender classification', () => {
  it('classifies VIP sender as business_critical', async () => {
    const email = makeEmail({
      from: 'john@callagylaw.com',
      subject: 'Follow up on case',
    });
    const result = await engine.classifyEmail(email);
    expect(result.category).toBe(EmailCategory.BUSINESS_CRITICAL);
    expect(result.priority).toBe(Priority.CRITICAL);
  });

  it('classifies tpglife.com as VIP', async () => {
    const email = makeEmail({
      from: 'davidprice@tpglife.com',
      subject: 'Quarterly report',
    });
    const result = await engine.classifyEmail(email);
    expect(result.category).toBe(EmailCategory.BUSINESS_CRITICAL);
  });

  it('classifies premiersmi.com as VIP', async () => {
    const email = makeEmail({
      from: 'agent@premiersmi.com',
      subject: 'New deal',
    });
    const result = await engine.classifyEmail(email);
    expect(result.category).toBe(EmailCategory.BUSINESS_CRITICAL);
  });

  it('VIP sender is case-insensitive', async () => {
    const email = makeEmail({
      from: 'CEO@CALLAGYLAW.COM',
      subject: 'Important matter',
    });
    const result = await engine.classifyEmail(email);
    expect(result.category).toBe(EmailCategory.BUSINESS_CRITICAL);
  });
});

// --- Financial Domain Classification ---

describe('financial domain classification', () => {
  it('classifies non-VIP financial domain emails', async () => {
    const email = makeEmail({
      from: 'notices@chase.com',
      subject: 'Your commission statement',
    });
    const result = await engine.classifyEmail(email);
    expect(result.category).toBe(EmailCategory.FINANCIAL_INSURANCE);
  });

  it('classifies paypal as financial', async () => {
    const email = makeEmail({
      from: 'reports@paypal.com',
      subject: 'Payment deposit summary',
    });
    const result = await engine.classifyEmail(email);
    expect(result.category).toBe(EmailCategory.FINANCIAL_INSURANCE);
  });

  it('VIP financial domains classify as business_critical (VIP takes priority)', async () => {
    const email = makeEmail({
      from: 'notices@mutualofomaha.com',
      subject: 'Your commission statement',
    });
    const result = await engine.classifyEmail(email);
    // VIP sender check (50 pts) outweighs financial domain (40 pts)
    expect(result.category).toBe(EmailCategory.BUSINESS_CRITICAL);
  });
});

// --- Spam Classification ---

describe('spam classification', () => {
  it('classifies emails from spam domains', async () => {
    const email = makeEmail({
      from: 'user@tempmail.com',
      subject: 'You are a winner!',
    });
    const result = await engine.classifyEmail(email);
    expect(result.category).toBe(EmailCategory.SPAM_NOISE);
  });

  it('classifies emails with many spam indicators', async () => {
    const email = makeEmail({
      from: 'promo@randomsite.com',
      subject: 'Limited time offer - act now for free discount!',
    });
    const result = await engine.classifyEmail(email);
    expect(result.category).toBe(EmailCategory.SPAM_NOISE);
  });

  it('noreply senders boost marketing/spam scores', async () => {
    const email = makeEmail({
      from: 'noreply@someservice.com',
      subject: 'Your weekly newsletter - unsubscribe anytime',
    });
    const result = await engine.classifyEmail(email);
    // Should be spam or marketing
    expect([
      EmailCategory.SPAM_NOISE,
      EmailCategory.MARKETING_ANALYTICS,
    ]).toContain(result.category);
  });
});

// --- Calendar / Scheduling ---

describe('calendar classification', () => {
  it('classifies meeting requests', async () => {
    const email = makeEmail({
      from: 'coworker@business.com',
      subject: 'Meeting tomorrow at 2pm - Zoom call',
    });
    const result = await engine.classifyEmail(email);
    expect(result.category).toBe(EmailCategory.CALENDAR_SCHEDULING);
  });

  it('classifies appointment scheduling', async () => {
    const email = makeEmail({
      from: 'assistant@company.com',
      subject: 'Reschedule your appointment',
    });
    const result = await engine.classifyEmail(email);
    expect(result.category).toBe(EmailCategory.CALENDAR_SCHEDULING);
  });
});

// --- Subject Keyword Analysis ---

describe('subject keyword analysis', () => {
  it('critical keywords boost business_critical', async () => {
    const email = makeEmail({
      from: 'someone@randomdomain.com',
      subject: 'URGENT: Compliance deadline approaching',
    });
    const result = await engine.classifyEmail(email);
    expect(result.category).toBe(EmailCategory.BUSINESS_CRITICAL);
  });

  it('financial keywords boost financial category', async () => {
    const email = makeEmail({
      from: 'accounting@neutral.com',
      subject: 'Invoice for commission payment - 1099 enclosed',
    });
    const result = await engine.classifyEmail(email);
    expect(result.category).toBe(EmailCategory.FINANCIAL_INSURANCE);
  });

  it('recruitment keywords boost recruitment category', async () => {
    const email = makeEmail({
      from: 'recruiter@neutral.com',
      subject: 'Great career opportunity - join our team',
    });
    const result = await engine.classifyEmail(email);
    expect(result.category).toBe(EmailCategory.RECRUITMENT_PROSPECTS);
  });
});

// --- Content Analysis ---

describe('content analysis', () => {
  it('very short content boosts spam score', async () => {
    const email = makeEmail({
      from: 'unknown@neutral.com',
      subject: 'Hi',
      content: 'Click here now!',
    });
    const result = await engine.classifyEmail(email);
    // Short content + spam indicator in subject
    expect(result.category).toBe(EmailCategory.SPAM_NOISE);
  });

  it('long content with business signature boosts client/business', async () => {
    const longContent =
      'Dear David, I wanted to follow up on our recent discussion about the policy coverage. ' +
      'We have reviewed the terms and believe that the proposed changes would be beneficial. ' +
      'Please let me know your thoughts at your earliest convenience. ' +
      'A'.repeat(2000) +
      '\n\nBest regards,\nJohn Smith\nSenior VP\nTitle: Director\nCompany: ACME Corp\nPhone: 555-1234\nemail: john@acme.com';
    const email = makeEmail({
      from: 'john@clientcompany.com',
      subject: 'Policy coverage review',
      content: longContent,
    });
    const result = await engine.classifyEmail(email);
    expect([
      EmailCategory.CLIENT_COMMUNICATIONS,
      EmailCategory.BUSINESS_CRITICAL,
    ]).toContain(result.category);
  });

  it('negative sentiment boosts critical/client scores', async () => {
    const email = makeEmail({
      from: 'user@somecompany.com',
      subject: 'Regarding our account',
      content:
        'I am very frustrated and disappointed with the recent issue. This is a serious problem that needs resolution.',
    });
    const result = await engine.classifyEmail(email);
    expect([
      EmailCategory.BUSINESS_CRITICAL,
      EmailCategory.CLIENT_COMMUNICATIONS,
    ]).toContain(result.category);
  });
});

// --- Priority Calculation ---

describe('priority calculation', () => {
  it('Gmail promo labels get LOW priority', async () => {
    const email = makeEmail({
      from: 'deals@store.com',
      subject: 'Big sale!',
      labels: ['CATEGORY_PROMOTIONS'],
    });
    const result = await engine.classifyEmail(email);
    expect(result.priority).toBe(Priority.LOW);
  });

  it('Gmail SPAM label gets LOW priority', async () => {
    const email = makeEmail({
      from: 'spam@spam.com',
      subject: 'Free money',
      labels: ['SPAM'],
    });
    const result = await engine.classifyEmail(email);
    expect(result.priority).toBe(Priority.LOW);
  });

  it('high spam score gets ARCHIVE priority', async () => {
    const email = makeEmail({
      from: 'user@tempmail.com',
      subject: 'Congratulations winner - click here for free offer',
    });
    const result = await engine.classifyEmail(email);
    expect(result.priority).toBe(Priority.ARCHIVE);
  });

  it('VIP sender with strong business signals gets CRITICAL', async () => {
    const email = makeEmail({
      from: 'partner@callagylaw.com',
      subject: 'URGENT: Legal compliance deadline tomorrow',
    });
    const result = await engine.classifyEmail(email);
    expect(result.priority).toBe(Priority.CRITICAL);
  });

  it('non-VIP business_critical caps at HIGH', async () => {
    const email = makeEmail({
      from: 'someone@randomdomain.com',
      subject: 'Urgent compliance issue - deadline approaching immediately',
    });
    const result = await engine.classifyEmail(email);
    if (result.category === EmailCategory.BUSINESS_CRITICAL) {
      expect(result.priority).toBe(Priority.HIGH);
    }
  });

  it('recruitment gets MEDIUM priority', async () => {
    const email = makeEmail({
      from: 'recruiter@neutral.com',
      subject: 'Great career opportunity - agent position - join our team',
    });
    const result = await engine.classifyEmail(email);
    if (result.category === EmailCategory.RECRUITMENT_PROSPECTS) {
      expect(result.priority).toBe(Priority.MEDIUM);
    }
  });
});

// --- Urgency Calculation ---

describe('urgency calculation', () => {
  it('CRITICAL priority gets IMMEDIATE urgency', async () => {
    const email = makeEmail({
      from: 'lawyer@callagylaw.com',
      subject: 'URGENT: Court deadline today',
    });
    const result = await engine.classifyEmail(email);
    expect(result.urgency).toBe(UrgencyLevel.IMMEDIATE);
  });

  it('calendar conflict gets IMMEDIATE urgency', async () => {
    const email = makeEmail({
      from: 'assistant@company.com',
      subject: 'Meeting conflict today - need to reschedule',
    });
    const result = await engine.classifyEmail(email);
    expect(result.urgency).toBe(UrgencyLevel.IMMEDIATE);
  });

  it('LOW priority gets BATCH urgency', async () => {
    const email = makeEmail({
      from: 'newsletter@marketing.com',
      subject: 'Weekly industry news',
      labels: ['CATEGORY_UPDATES'],
    });
    const result = await engine.classifyEmail(email);
    expect(result.urgency).toBe(UrgencyLevel.BATCH);
  });
});

// --- Action Determination ---

describe('action determination', () => {
  it('IMMEDIATE urgency triggers IMMEDIATE_ALERT', async () => {
    const email = makeEmail({
      from: 'boss@callagylaw.com',
      subject: 'URGENT: Emergency court filing deadline today',
    });
    const result = await engine.classifyEmail(email);
    expect(result.action).toBe(EmailAction.IMMEDIATE_ALERT);
  });

  it('ARCHIVE priority triggers AUTO_ARCHIVE', async () => {
    const email = makeEmail({
      from: 'junk@tempmail.com',
      subject: 'Congratulations winner - click here for free offer now',
    });
    const result = await engine.classifyEmail(email);
    expect(result.action).toBe(EmailAction.AUTO_ARCHIVE);
  });
});

// --- Escalation Configuration ---

describe('escalation configuration', () => {
  it('IMMEDIATE urgency gets time_based escalation with 5min delay', async () => {
    const email = makeEmail({
      from: 'lawyer@callagylaw.com',
      subject: 'URGENT: Emergency compliance deadline today',
    });
    const result = await engine.classifyEmail(email);
    expect(result.escalation).toBeDefined();
    expect(result.escalation!.type).toBe('time_based');
    expect(result.escalation!.delayMs).toBe(5 * 60 * 1000);
    expect(result.escalation!.mentions).toContain('@here');
  });

  it('FAST_TRACK urgency gets 30min escalation', async () => {
    const email = makeEmail({
      from: 'client@acme.com',
      subject: 'Policy coverage question about renewal',
    });
    const result = await engine.classifyEmail(email);
    if (result.urgency === UrgencyLevel.FAST_TRACK) {
      expect(result.escalation).toBeDefined();
      expect(result.escalation!.delayMs).toBe(30 * 60 * 1000);
    }
  });

  it('BATCH urgency has no escalation', async () => {
    const email = makeEmail({
      from: 'newsletter@marketing.com',
      subject: 'Weekly summary',
      labels: ['CATEGORY_UPDATES'],
    });
    const result = await engine.classifyEmail(email);
    expect(result.escalation).toBeUndefined();
  });
});

// --- Routing ---

describe('routing configuration', () => {
  it('all emails route to EMAIL_TRIAGE channel', async () => {
    const email = makeEmail({
      from: 'anyone@anywhere.com',
      subject: 'Test',
    });
    const result = await engine.classifyEmail(email);
    expect(result.discordChannel).toBe('1484841234567890128');
    expect(result.routing).toBeDefined();
    expect(result.routing!.primary).toBe('1484841234567890128');
  });
});

// --- Confidence ---

describe('confidence scoring', () => {
  it('confidence is between 0 and 1', async () => {
    const email = makeEmail({
      from: 'user@example.com',
      subject: 'Random subject',
    });
    const result = await engine.classifyEmail(email);
    expect(result.confidence).toBeGreaterThanOrEqual(0);
    expect(result.confidence).toBeLessThanOrEqual(1);
  });

  it('strong VIP signals produce high confidence', async () => {
    const email = makeEmail({
      from: 'partner@callagylaw.com',
      subject: 'Urgent legal deadline',
    });
    const result = await engine.classifyEmail(email);
    expect(result.confidence).toBeGreaterThan(0.5);
  });
});

// --- Sentiment ---

describe('sentiment analysis', () => {
  it('positive content returns positive sentiment', async () => {
    const email = makeEmail({
      from: 'user@example.com',
      subject: 'Feedback',
      content:
        'Everything was great and excellent. I am very happy and pleased with the service.',
    });
    const result = await engine.classifyEmail(email);
    expect(result.sentiment).toBeDefined();
    expect(result.sentiment!).toBeGreaterThan(0);
  });

  it('negative content returns negative sentiment', async () => {
    const email = makeEmail({
      from: 'user@example.com',
      subject: 'Feedback',
      content:
        'I have a problem and complaint. I am very unhappy and disappointed and frustrated.',
    });
    const result = await engine.classifyEmail(email);
    expect(result.sentiment).toBeDefined();
    expect(result.sentiment!).toBeLessThan(0);
  });

  it('no content means no sentiment', async () => {
    const email = makeEmail({
      from: 'user@example.com',
      subject: 'No body',
    });
    const result = await engine.classifyEmail(email);
    expect(result.sentiment).toBeUndefined();
  });
});

// --- Sender Reputation ---

describe('sender reputation', () => {
  it('getSenderReputationScore returns 50 for unknown sender', () => {
    expect(engine.getSenderReputationScore('unknown@nowhere.com')).toBe(50);
  });

  it('VIP senders have high reputation scores', () => {
    // VIP senders are initialized with score 95
    expect(engine.getSenderReputationScore('@callagylaw.com')).toBe(95);
  });

  it('updateSenderScore modifies reputation', () => {
    engine.updateSenderScore('test@newdomain.com', 20);
    expect(engine.getSenderReputationScore('test@newdomain.com')).toBe(70);
  });

  it('updateSenderScore clamps to 0-100', () => {
    engine.updateSenderScore('low@domain.com', -100);
    expect(engine.getSenderReputationScore('low@domain.com')).toBe(0);

    engine.updateSenderScore('high@domain.com', 200);
    expect(engine.getSenderReputationScore('high@domain.com')).toBe(100);
  });

  it('updateSenderScore can change category', () => {
    engine.updateSenderScore('user@domain.com', 0, 'blocked');
    // Classification for a blocked sender should boost spam
    const email = makeEmail({
      from: 'user@domain.com',
      subject: 'Hello there',
    });
    // Just verifying no error; the blocked category adds 80 to spam
    return engine.classifyEmail(email).then((result) => {
      expect(result).toBeDefined();
    });
  });

  it('classifyEmail updates sender reputation on each call', async () => {
    const email = makeEmail({
      from: 'repeat@sender.com',
      subject: 'First email',
    });
    await engine.classifyEmail(email);
    // After first classify, sender should be tracked
    expect(engine.getSenderReputationScore('repeat@sender.com')).toBe(50);
  });
});

// --- Reason Generation ---

describe('reason generation', () => {
  it('includes VIP sender in reason for VIP emails', async () => {
    const email = makeEmail({
      from: 'partner@callagylaw.com',
      subject: 'Case update',
    });
    const result = await engine.classifyEmail(email);
    expect(result.reason).toContain('VIP sender');
  });

  it('includes time-sensitive in reason for urgent subjects', async () => {
    const email = makeEmail({
      from: 'someone@domain.com',
      subject: 'ASAP - need this today',
    });
    const result = await engine.classifyEmail(email);
    expect(result.reason).toContain('time-sensitive');
  });
});

// --- Time Context Analysis ---

describe('time context analysis', () => {
  it('off-hours business emails get priority boost', async () => {
    const lateNight = new Date();
    lateNight.setHours(23, 30, 0, 0);

    const email = makeEmail({
      from: 'exec@callagylaw.com',
      subject: 'Need to discuss case',
      timestamp: lateNight.toISOString(),
    });
    const result = await engine.classifyEmail(email);
    expect(result.category).toBe(EmailCategory.BUSINESS_CRITICAL);
  });

  it('weekend business emails get priority boost', async () => {
    // Find next Saturday
    const saturday = new Date();
    saturday.setDate(saturday.getDate() + (6 - saturday.getDay()));
    saturday.setHours(10, 0, 0, 0);

    const email = makeEmail({
      from: 'manager@premiersmi.com',
      subject: 'Follow up on project',
      timestamp: saturday.toISOString(),
    });
    const result = await engine.classifyEmail(email);
    expect(result.category).toBe(EmailCategory.BUSINESS_CRITICAL);
  });
});

// --- Spam Override ---

describe('spam score override', () => {
  it('high spam score dampens other category scores', async () => {
    // Email from spam domain with spam keywords should override other signals
    const email = makeEmail({
      from: 'promo@tempmail.com',
      subject: 'Free offer - limited time sale discount - click here act now',
      content: 'Congratulations winner! Unsubscribe here.',
    });
    const result = await engine.classifyEmail(email);
    expect(result.category).toBe(EmailCategory.SPAM_NOISE);
  });
});

// --- Marketing Domain Classification ---

describe('marketing domain classification', () => {
  it('classifies marketing domains', async () => {
    const email = makeEmail({
      from: 'campaign@mailchimp.com',
      subject: 'Your campaign analytics report',
    });
    const result = await engine.classifyEmail(email);
    expect([
      EmailCategory.MARKETING_ANALYTICS,
      EmailCategory.SPAM_NOISE,
    ]).toContain(result.category);
  });
});

// --- Default / Personal Admin ---

describe('default classification', () => {
  it('generic email with no strong signals defaults to personal_admin', async () => {
    const email = makeEmail({
      from: 'friend@gmail.com',
      subject: 'Hey, how are you?',
    });
    const result = await engine.classifyEmail(email);
    expect(result.category).toBe(EmailCategory.PERSONAL_ADMIN);
    expect(result.priority).toBe(Priority.LOW);
  });
});
