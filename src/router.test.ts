import { describe, expect, it, vi } from 'vitest';

import {
  escapeXml,
  findChannel,
  formatMessages,
  formatOutbound,
  routeOutbound,
  stripInternalTags,
} from './router.js';
import { Channel, NewMessage } from './types.js';

describe('escapeXml', () => {
  it('returns empty string for falsy input', () => {
    expect(escapeXml('')).toBe('');
  });

  it('escapes ampersands', () => {
    expect(escapeXml('A & B')).toBe('A &amp; B');
  });

  it('escapes angle brackets', () => {
    expect(escapeXml('<tag>')).toBe('&lt;tag&gt;');
  });

  it('escapes double quotes', () => {
    expect(escapeXml('say "hello"')).toBe('say &quot;hello&quot;');
  });

  it('escapes all special chars in one string', () => {
    expect(escapeXml('<a href="x">&</a>')).toBe(
      '&lt;a href=&quot;x&quot;&gt;&amp;&lt;/a&gt;',
    );
  });

  it('passes through plain text unchanged', () => {
    expect(escapeXml('hello world')).toBe('hello world');
  });
});

describe('formatMessages', () => {
  it('wraps a single message in XML', () => {
    const msgs: NewMessage[] = [
      {
        id: '1',
        chat_jid: 'jid1',
        sender: 's1',
        sender_name: 'Alice',
        content: 'Hello',
        timestamp: '2025-01-15T12:00:00Z',
      },
    ];
    const result = formatMessages(msgs, 'America/New_York');
    expect(result).toContain('<context timezone="America/New_York"');
    expect(result).toContain('<messages>');
    expect(result).toContain('sender="Alice"');
    expect(result).toContain('>Hello</message>');
    expect(result).toContain('</messages>');
  });

  it('formats multiple messages', () => {
    const msgs: NewMessage[] = [
      {
        id: '1',
        chat_jid: 'j',
        sender: 's1',
        sender_name: 'Alice',
        content: 'Hi',
        timestamp: '2025-01-15T12:00:00Z',
      },
      {
        id: '2',
        chat_jid: 'j',
        sender: 's2',
        sender_name: 'Bob',
        content: 'Hey',
        timestamp: '2025-01-15T12:01:00Z',
      },
    ];
    const result = formatMessages(msgs, 'UTC');
    expect(result).toContain('sender="Alice"');
    expect(result).toContain('sender="Bob"');
  });

  it('escapes XML characters in message content', () => {
    const msgs: NewMessage[] = [
      {
        id: '1',
        chat_jid: 'j',
        sender: 's1',
        sender_name: 'A<B',
        content: 'x & y',
        timestamp: '2025-01-15T12:00:00Z',
      },
    ];
    const result = formatMessages(msgs, 'UTC');
    expect(result).toContain('sender="A&lt;B"');
    expect(result).toContain('>x &amp; y</message>');
  });
});

describe('stripInternalTags', () => {
  it('removes <internal>...</internal> tags', () => {
    expect(stripInternalTags('Hello <internal>secret</internal> world')).toBe(
      'Hello  world',
    );
  });

  it('removes multiline internal tags', () => {
    const input = 'before\n<internal>\nline1\nline2\n</internal>\nafter';
    expect(stripInternalTags(input)).toBe('before\n\nafter');
  });

  it('handles text with no internal tags', () => {
    expect(stripInternalTags('plain text')).toBe('plain text');
  });

  it('removes multiple internal tags', () => {
    const input = '<internal>a</internal> middle <internal>b</internal>';
    expect(stripInternalTags(input)).toBe('middle');
  });
});

describe('formatOutbound', () => {
  it('strips internal tags and returns text', () => {
    expect(formatOutbound('Hello <internal>ignore</internal> world')).toBe(
      'Hello  world',
    );
  });

  it('returns empty string when only internal content', () => {
    expect(formatOutbound('<internal>all internal</internal>')).toBe('');
  });

  it('returns text as-is when no internal tags', () => {
    expect(formatOutbound('plain message')).toBe('plain message');
  });
});

describe('routeOutbound', () => {
  function makeChannel(
    name: string,
    owns: boolean,
    connected: boolean,
  ): Channel {
    return {
      name,
      connect: vi.fn(),
      sendMessage: vi.fn().mockResolvedValue(undefined),
      isConnected: () => connected,
      ownsJid: () => owns,
      disconnect: vi.fn(),
    };
  }

  it('sends to the correct channel', async () => {
    const ch = makeChannel('telegram', true, true);
    await routeOutbound([ch], 'tg:123', 'hello');
    expect(ch.sendMessage).toHaveBeenCalledWith('tg:123', 'hello');
  });

  it('throws when no channel owns the JID', () => {
    const ch = makeChannel('telegram', false, true);
    expect(() => routeOutbound([ch], 'unknown:1', 'hi')).toThrow(
      'No channel for JID',
    );
  });

  it('throws when channel owns JID but is disconnected', () => {
    const ch = makeChannel('telegram', true, false);
    expect(() => routeOutbound([ch], 'tg:1', 'hi')).toThrow(
      'No channel for JID',
    );
  });

  it('picks the first matching channel', async () => {
    const ch1 = makeChannel('ch1', false, true);
    const ch2 = makeChannel('ch2', true, true);
    await routeOutbound([ch1, ch2], 'jid', 'msg');
    expect(ch1.sendMessage).not.toHaveBeenCalled();
    expect(ch2.sendMessage).toHaveBeenCalledWith('jid', 'msg');
  });
});

describe('findChannel', () => {
  function makeChannel(name: string, owns: boolean): Channel {
    return {
      name,
      connect: vi.fn(),
      sendMessage: vi.fn(),
      isConnected: () => true,
      ownsJid: () => owns,
      disconnect: vi.fn(),
    };
  }

  it('returns the channel that owns the JID', () => {
    const ch = makeChannel('tg', true);
    expect(findChannel([ch], 'tg:1')).toBe(ch);
  });

  it('returns undefined when no channel owns the JID', () => {
    const ch = makeChannel('tg', false);
    expect(findChannel([ch], 'unknown:1')).toBeUndefined();
  });
});
