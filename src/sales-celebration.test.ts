import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Mock heavy deps that sales-celebration imports
vi.mock('better-sqlite3', () => {
  return {
    default: vi.fn(() => {
      throw new Error('No DB in test');
    }),
  };
});

vi.mock('./config.js', () => ({
  DATA_DIR: '/tmp/test-nanoclaw-data',
}));

vi.mock('./logger.js', () => {
  const noop = () => {};
  return {
    logger: { info: noop, warn: noop, error: noop, debug: noop },
  };
});

// We need to test the internal detectSales function. It's not exported, so
// we test via checkAndCelebrateSale which calls it. We'll verify behavior
// by checking whether sendMessage gets called (sale detected) or not.

import { checkAndCelebrateSale } from './sales-celebration.js';
import { Channel, NewMessage } from './types.js';

function makeMsg(overrides: Partial<NewMessage> = {}): NewMessage {
  return {
    id: `msg-${Math.random().toString(36).slice(2)}`,
    chat_jid: 'tg:-1002362081030',
    sender: 'user1',
    sender_name: 'John Smith',
    content: '',
    timestamp: new Date().toISOString(),
    is_from_me: false,
    is_bot_message: false,
    ...overrides,
  };
}

function makeTgChannel(): Channel & { sendMessage: ReturnType<typeof vi.fn> } {
  return {
    name: 'telegram',
    connect: vi.fn().mockResolvedValue(undefined),
    sendMessage: vi.fn().mockResolvedValue(undefined),
    isConnected: () => true,
    ownsJid: () => true,
    disconnect: vi.fn().mockResolvedValue(undefined),
  };
}

const TPG_JID = 'tg:-1002362081030';

describe('checkAndCelebrateSale', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('ignores messages from wrong chat', () => {
    const ch = makeTgChannel();
    const msg = makeMsg({ content: 'Trans $50.00 approved 🔥' });
    checkAndCelebrateSale(msg, 'wrong-jid', [ch]);
    vi.advanceTimersByTime(20000);
    expect(ch.sendMessage).not.toHaveBeenCalled();
  });

  it('ignores messages from the bot itself', () => {
    const ch = makeTgChannel();
    const msg = makeMsg({
      content: 'Trans $50.00 approved 🔥',
      is_from_me: true,
    });
    checkAndCelebrateSale(msg, TPG_JID, [ch]);
    vi.advanceTimersByTime(20000);
    expect(ch.sendMessage).not.toHaveBeenCalled();
  });

  it('ignores bot messages', () => {
    const ch = makeTgChannel();
    const msg = makeMsg({
      content: 'Trans $50.00 approved 🔥',
      is_bot_message: true,
    });
    checkAndCelebrateSale(msg, TPG_JID, [ch]);
    vi.advanceTimersByTime(20000);
    expect(ch.sendMessage).not.toHaveBeenCalled();
  });

  it('detects a sale with carrier + dollar amount', () => {
    const ch = makeTgChannel();
    const msg = makeMsg({ content: 'Trans $92.34/mo approved 🔥' });
    checkAndCelebrateSale(msg, TPG_JID, [ch]);
    vi.advanceTimersByTime(20000);
    expect(ch.sendMessage).toHaveBeenCalledTimes(1);
    const text = ch.sendMessage.mock.calls[0][1] as string;
    expect(text).toContain('John');
    expect(text).toContain('$92.34');
  });

  it('detects a sale with approval language and bare amount', () => {
    const ch = makeTgChannel();
    const msg = makeMsg({
      content: 'Approved! Americo 76.43 effective 4/15',
    });
    checkAndCelebrateSale(msg, TPG_JID, [ch]);
    vi.advanceTimersByTime(20000);
    expect(ch.sendMessage).toHaveBeenCalledTimes(1);
  });

  it('rejects lead store messages', () => {
    const ch = makeTgChannel();
    const msg = makeMsg({ content: 'Lead store has $50.00 packages' });
    checkAndCelebrateSale(msg, TPG_JID, [ch]);
    vi.advanceTimersByTime(20000);
    expect(ch.sendMessage).not.toHaveBeenCalled();
  });

  it('rejects daily recaps with multiple activity words', () => {
    const ch = makeTgChannel();
    const msg = makeMsg({
      content: '25 dials, 3 presentations, 1 closed app $150.00 Trans',
    });
    checkAndCelebrateSale(msg, TPG_JID, [ch]);
    vi.advanceTimersByTime(20000);
    expect(ch.sendMessage).not.toHaveBeenCalled();
  });

  it('rejects questions about sales', () => {
    const ch = makeTgChannel();
    const msg = makeMsg({
      content: 'Does anyone know if Trans pays $50.00?',
    });
    checkAndCelebrateSale(msg, TPG_JID, [ch]);
    vi.advanceTimersByTime(20000);
    expect(ch.sendMessage).not.toHaveBeenCalled();
  });

  it('does not celebrate the same message ID twice', () => {
    const ch = makeTgChannel();
    const msg = makeMsg({
      id: 'dupe-1',
      content: 'Trans $80.00 approved 🔥',
    });
    checkAndCelebrateSale(msg, TPG_JID, [ch]);
    checkAndCelebrateSale(msg, TPG_JID, [ch]);
    vi.advanceTimersByTime(20000);
    // Only one celebration even though called twice
    expect(ch.sendMessage).toHaveBeenCalledTimes(1);
  });

  it('detects multiple amounts in one message', () => {
    const ch = makeTgChannel();
    const msg = makeMsg({
      content: 'Closed husband and wife! Trans $55.00 and $42.00 approved 🔥',
    });
    checkAndCelebrateSale(msg, TPG_JID, [ch]);
    vi.advanceTimersByTime(20000);
    expect(ch.sendMessage).toHaveBeenCalledTimes(1);
    // Multi-sale celebration should mention count
    const text = ch.sendMessage.mock.calls[0][1] as string;
    expect(text).toContain('2');
  });

  it('warns when no telegram channel is available', () => {
    const msg = makeMsg({ content: 'Trans $80.00 approved 🔥' });
    // Should not throw, just silently warn
    expect(() => checkAndCelebrateSale(msg, TPG_JID, [])).not.toThrow();
  });

  it('requires a named sender (not "someone")', () => {
    const ch = makeTgChannel();
    const msg = makeMsg({
      content: 'Trans $80.00 approved 🔥',
      sender_name: '',
    });
    checkAndCelebrateSale(msg, TPG_JID, [ch]);
    vi.advanceTimersByTime(20000);
    expect(ch.sendMessage).not.toHaveBeenCalled();
  });

  it('requires carrier or sale language to detect a sale', () => {
    const ch = makeTgChannel();
    const msg = makeMsg({
      content: 'Just paid $80.00 for groceries 🔥',
    });
    checkAndCelebrateSale(msg, TPG_JID, [ch]);
    vi.advanceTimersByTime(20000);
    expect(ch.sendMessage).not.toHaveBeenCalled();
  });
});

describe('recentlyCelebrated bulk eviction', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('handles many messages without error (bulk eviction at 500)', () => {
    const ch = makeTgChannel();

    // Send 600 unique sale messages to trigger bulk eviction at 500
    for (let i = 0; i < 600; i++) {
      const msg = makeMsg({
        id: `evict-${i}`,
        content: `Trans $${(50 + i).toFixed(2)} approved 🔥`,
      });
      checkAndCelebrateSale(msg, TPG_JID, [ch]);
    }

    vi.advanceTimersByTime(20000);
    // Should have sent a celebration for each unique message
    expect(ch.sendMessage.mock.calls.length).toBe(600);
  });
});
