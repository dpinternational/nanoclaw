/**
 * Real-time sales celebration for TPG UnCaged.
 *
 * Detects sale posts via regex pattern matching and sends a short
 * congratulatory reply to the group. Runs inline in the main process
 * message loop — no container, no Haiku call, no scheduled task.
 */

import Database from 'better-sqlite3';
import fs from 'fs';
import path from 'path';

import { DATA_DIR } from './config.js';
import { logger } from './logger.js';
import { Channel, NewMessage } from './types.js';

const TPG_UNCAGED_JID = 'tg:-1002362081030';

/** Sales database for TPG UnCaged. */
let salesDb: Database.Database | null = null;

function getSalesDb(): Database.Database | null {
  if (salesDb) return salesDb;
  const dbPath = path.join(
    DATA_DIR,
    'groups',
    'telegram_tpg_uncaged',
    'messages.db',
  );
  if (!fs.existsSync(dbPath)) return null;
  try {
    salesDb = new Database(dbPath);
    salesDb.pragma('journal_mode = WAL');
    // Ensure sales table exists
    salesDb.exec(`
      CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id TEXT NOT NULL,
        sender TEXT NOT NULL,
        sender_name TEXT,
        amount REAL NOT NULL,
        product TEXT,
        sale_type TEXT,
        timestamp TEXT NOT NULL,
        annual_premium REAL,
        is_monthly INTEGER DEFAULT 0,
        detection_method TEXT DEFAULT 'celebration',
        confidence_score REAL DEFAULT 0.8,
        full_content TEXT,
        celebrated INTEGER DEFAULT 1
      )
    `);
    return salesDb;
  } catch (err) {
    logger.error({ err }, 'Failed to open sales database');
    return null;
  }
}

/** Clean up sender names: strip emojis, trailing IDs, keep first name only. */
function cleanSenderName(rawName: string | undefined): string {
  if (!rawName) return 'someone';
  // Strip emojis and special chars, keep letters and spaces
  const cleaned = rawName
    .replace(/[^\p{L}\s']/gu, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  // Take first word (first name)
  const firstName = cleaned.split(/\s+/)[0];
  return firstName || 'someone';
}

/** Determine if an amount is monthly or annual premium based on context. */
function detectMonthlyOrAnnual(
  content: string,
  amount: number,
): 'monthly' | 'annual' {
  const c = content.toLowerCase();
  // Explicit annual premium indicators
  if (/\bap\b|annual premium|per year|\/year|\/yr/i.test(content))
    return 'annual';
  // Explicit monthly indicators
  if (/a month|per month|\/month|\/mo|monthly/i.test(c)) return 'monthly';
  // Amounts over $500 are almost certainly annual premium
  if (amount > 500) return 'annual';
  // Default: assume monthly (most common posting format)
  return 'monthly';
}

function recordSale(msg: NewMessage, amount: number, amountStr: string): void {
  const db = getSalesDb();
  if (!db) return;
  try {
    const mode = detectMonthlyOrAnnual(msg.content, amount);
    const isMonthly = mode === 'monthly';
    const annualPremium = isMonthly ? amount * 12 : amount;
    const product = extractProduct(msg.content);
    const cleanName = cleanSenderName(msg.sender_name);
    db.prepare(
      `
      INSERT OR IGNORE INTO sales (message_id, sender, sender_name, amount, product, timestamp, annual_premium, is_monthly, full_content)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    `,
    ).run(
      msg.id,
      msg.sender,
      cleanName,
      amount,
      product,
      msg.timestamp,
      annualPremium,
      isMonthly ? 1 : 0,
      msg.content,
    );
    logger.info(
      { sender: cleanName, amount: amountStr, mode, ap: annualPremium },
      'Sale recorded',
    );
  } catch (err) {
    logger.warn({ err }, 'Failed to record sale');
  }
}

function extractProduct(content: string): string {
  const c = content.toLowerCase();
  if (c.includes('trans') || c.includes('transamerica')) return 'Transamerica';
  if (
    c.includes('amam') ||
    c.includes('american amicable') ||
    c.includes('am am')
  )
    return 'American Amicable';
  if (c.includes('americo')) return 'Americo';
  if (c.includes('mutual') || c.includes('moo')) return 'Mutual of Omaha';
  if (c.includes('aflac')) return 'Aflac';
  if (c.includes('aig')) return 'AIG';
  if (c.includes('cica')) return 'CICA';
  if (c.includes('prosperity')) return 'Prosperity';
  if (c.includes('assurity')) return 'Assurity';
  if (c.includes('sagicor')) return 'Sagicor';
  if (c.includes('foresters')) return 'Foresters';
  if (c.includes('royal neighbors')) return 'Royal Neighbors';
  return 'Unknown';
}

/** Known insurance carrier names / abbreviations. */
const CARRIERS = [
  'trans',
  'transamerica',
  'transexp',
  'trans express',
  'transsolutions',
  'trans solutions',
  'aflac',
  'americo',
  'moo',
  'mutual of omaha',
  'mutual',
  'aig',
  'cica',
  'ethos',
  'corebridge',
  'aetna',
  'amam',
  'am am',
  'american amicable',
  'igo',
  'asap',
  'royal neighbors',
  'cvs',
  'prosperity',
  'assurity',
  'sagicor',
  'foresters',
];

const CARRIER_RE = new RegExp(
  CARRIERS.map((c) => c.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'),
  'i',
);

/** Dollar amount pattern — $25+ with optional cents. Also matches bare amounts (no $). */
const AMOUNT_RE = /\$(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)/;
const BARE_AMOUNT_RE = /^(\d{2,3}\.\d{2})\b/;
/** Match standalone dollar-amount-looking numbers anywhere in a line (with or without $). */
const ANY_AMOUNT_RE = /(?:\$|(?<![.\d]))(\d{1,3}(?:,\d{3})*\.\d{2})(?!\d)/g;

/** Celebration emoji/words that signal a sale post. */
const CELEBRATION_RE =
  /🎉|🎊|🔥|💪|⚔️|❤️|🌺|💕|🌈|approved|graded|rewrite|wrote|closed|boom/i;

/** Date patterns like 4/3, 04/15 — effective dates, common in sale posts. */
const EFF_DATE_RE = /\d{1,2}\/\d{1,2}/;

/** Patterns that disqualify a message as a sale. */
const REJECT_RE =
  /lead (pack|store)|overflow|tcpa|earn \$|question|anyone know|does anyone|how do|can you|should i|when putting|zoom|training|happening now|scratch th(is|at)|(?<!\$\d{1,6}[\s\S]{0,100})cancel(led)?|fell through|didn'?t go through|won'?t go through|not going through|backed out|changed their mind|never\s?mind|disregard|(?<!\w)void(?!\w)/i;

/** Daily recap patterns — these are summaries, not individual sales. */
const RECAP_RE =
  /\b(dials?|pick\s?ups?|presentations?|contacts?|closed apps?|talk\s?time|hrs?\b|hours?\b)\b.*\b(dials?|pick\s?ups?|presentations?|contacts?|closed apps?|talk\s?time|hrs?\b|hours?\b)\b/is;
// Single activity word with a total/close reference = recap
const RECAP_WITH_TOTAL_RE =
  /\b\d+\s*(dials?|presentations?|pick\s?ups?|contacts?)\b[\s\S]*\b(close[ds]?|sales?)\b[\s\S]*\$/i;
const AP_TOTAL_RE = /\bAP\b/i;

/** Celebration templates grouped by STYLE so we never repeat the same vibe back to back. */
const CELEBRATION_STYLES: {
  style: string;
  templates: ((name: string, amount: string) => string)[];
}[] = [
  {
    style: 'hype',
    templates: [
      (name, amount) =>
        `🔥🔥🔥 ${name} JUST DROPPED ${amount}!!! Who's next?! ⚔️`,
      (name, amount) =>
        `BOOM 💥 ${name} with ${amount} ON THE BOARD! Let's GOOOOO! 🚀`,
      (name, amount) =>
        `LETS GOOOOO 🚀🚀🚀 ${name} just closed ${amount}!! DIAL, CLOSE, REPEAT! ⚔️🔥`,
    ],
  },
  {
    style: 'respect',
    templates: [
      (name, amount) =>
        `${name} just put ${amount} on the board. Quiet work, loud results. 💪`,
      (name, amount) =>
        `${amount} from ${name}. That's what consistency looks like. 🔥`,
      (name, amount) =>
        `Another one from ${name}. ${amount}. The scoreboard tells the story. 🏆`,
    ],
  },
  {
    style: 'competitive',
    templates: [
      (name, amount) =>
        `${name} with ${amount}!! Who's matching this energy today?! 🔥`,
      (name, amount) =>
        `${amount}!!! ${name} is putting the team on notice! Keep that same energy!! ⚔️`,
      (name, amount) => `${name} said WATCH THIS. ${amount} CLOSED! 🎯🔥`,
    ],
  },
  {
    style: 'team',
    templates: [
      (name, amount) =>
        `${name} just added ${amount} to the team total! Every sale matters, every dial counts! 💪🔥`,
      (name, amount) =>
        `${amount} from ${name}! That's what happens when you pick up the phone! 📞🔥`,
      (name, amount) =>
        `${name} with ${amount}! The phones are working today!! Who else is dialing?! ⚔️`,
    ],
  },
  {
    style: 'short',
    templates: [
      (name, amount) => `${name}. ${amount}. 🔥`,
      (name, amount) => `${amount}!! Nice work ${name}! 💪`,
      (name, amount) => `${name} stays dangerous. ${amount}. ⚔️`,
    ],
  },
];

const ALL_CELEBRATIONS = CELEBRATION_STYLES.flatMap((s) => s.templates);

/** Multi-sale celebrations. */
const MULTI_CELEBRATIONS = [
  (name: string, total: string, count: number) =>
    `🔥🔥🔥 ${name} JUST CLOSED ${count} POLICIES!!! ${total} TOTAL!! That's how you protect a family! ⚔️💪`,
  (name: string, total: string, count: number) =>
    `${name} with ${count} sales, ${total} on the board!! When BOTH of them say yes?! THAT'S the goal! 🔥🔥`,
  (name: string, total: string, count: number) =>
    `${name} said WHY STOP AT ONE?! ${count} policies, ${total} total!! Who else is doubling up?! 🔥⚔️`,
  (name: string, total: string, count: number) =>
    `${count} sales. ${total}. ${name} didn't leave the table early. 💪🔥`,
  (name: string, total: string, count: number) =>
    `${name} stacked ${count} for ${total}!! Protected the whole household!! 🏆🔥`,
  (name: string, total: string, count: number) =>
    `${total} from ${name}! ${count} policies in one shot! That's elite. ⚔️`,
];

let celebrationIndex = 0;
/** Track last style used to avoid same vibe back to back. */
let lastStyleUsed = '';
/** Track last 5 celebration texts to avoid any near-duplicates. */
const recentTexts: string[] = [];
/** Track recently celebrated message IDs to avoid double-celebrating. */
const recentlyCelebrated = new Set<string>();

/**
 * Determine if a message contains sale posts and return ALL of them.
 * A single message can contain multiple sales (e.g. two policies posted together).
 */
function detectSales(msg: NewMessage): { name: string; amount: string }[] {
  const content = msg.content;

  // Must not be from the bot itself
  if (msg.is_from_me || msg.is_bot_message) return [];

  // Reject obvious non-sales
  if (REJECT_RE.test(content)) return [];

  // Reject daily recaps (multiple activity words like "dials" AND "presentations")
  if (RECAP_RE.test(content)) return [];
  if (RECAP_WITH_TOTAL_RE.test(content)) return [];

  const name = cleanSenderName(msg.sender_name);
  if (!name || name === 'someone') return [];

  const sales: { name: string; amount: string }[] = [];
  const seenAmounts = new Set<number>();

  // Check if this is a carrier/sale post - must mention a carrier OR have approval language
  const hasCarrier = CARRIER_RE.test(content);
  const hasSaleLanguage =
    /approved|closed|wrote|got|sale|ASAP|effective|E-?check|DirExpress|existing client|rewrite|first policy|second policy|husband.*wife|mom|dad/i.test(
      content,
    );
  const hasEffDate = EFF_DATE_RE.test(content);
  if (!hasCarrier && !hasSaleLanguage && !hasEffDate) return [];

  // Find all dollar-looking amounts. Two patterns:
  // 1. With $ prefix: $1219.68, $27, $1,234.56
  // 2. Bare decimal amounts: 76.43, 225.72 (must have decimal)
  const patterns = [
    /\$(\d{1,5}(?:,\d{3})*(?:\.\d{2})?)(?!\d)/g, // $1219.68 or $27 or $1,234.56
    /(?<![\d.\$])(\d{2,4}\.\d{2})(?!\d)/g, // bare 76.43, 225.72 (not already matched by $)
  ];

  const rawAmounts: number[] = [];
  for (const regex of patterns) {
    let match;
    while ((match = regex.exec(content)) !== null) {
      const amount = parseFloat(match[1].replace(/,/g, ''));
      if (amount >= 25 && amount <= 10000 && !rawAmounts.includes(amount)) {
        rawAmounts.push(amount);
      }
    }
  }

  // Filter out amounts that are ~1/12 of another amount in the same post
  // (e.g. $92.34 is the monthly equivalent of $1108 annual - skip the monthly)
  const filteredAmounts = rawAmounts.filter((amt) => {
    for (const other of rawAmounts) {
      if (other !== amt && Math.abs(other / 12 - amt) < 1) {
        // amt is roughly other/12 - it's the monthly version of annual "other"
        return false;
      }
    }
    return true;
  });

  for (const amount of filteredAmounts) {
    const amountStr = `$${amount.toFixed(2)}`;
    sales.push({ name, amount: amountStr });
    recordSale(msg, amount, amountStr);
  }

  return sales;
}

/**
 * Hook into the message flow. Call this from onMessage for TPG UnCaged messages.
 */
export function checkAndCelebrateSale(
  msg: NewMessage,
  chatJid: string,
  channels: Channel[],
): void {
  if (chatJid !== TPG_UNCAGED_JID) return;

  const sales = detectSales(msg);
  if (sales.length === 0) return;

  // Deduplicate
  if (recentlyCelebrated.has(msg.id)) return;
  recentlyCelebrated.add(msg.id);

  // Keep the set from growing forever — bulk evict when hitting limit
  if (recentlyCelebrated.size > 500) {
    const ids = [...recentlyCelebrated];
    recentlyCelebrated.clear();
    for (const id of ids.slice(ids.length - 250)) recentlyCelebrated.add(id);
  }

  // Find the Telegram channel
  const tgChannel = channels.find((ch) => ch.name === 'telegram');
  if (!tgChannel) {
    logger.warn('Sales celebration: no Telegram channel found');
    return;
  }

  let text: string;
  const name = sales[0].name;

  if (sales.length >= 2) {
    const total = sales.reduce(
      (sum, s) => sum + parseFloat(s.amount.replace(/[$,]/g, '')),
      0,
    );
    const totalStr = `$${total.toFixed(2)}`;
    const template =
      MULTI_CELEBRATIONS[celebrationIndex % MULTI_CELEBRATIONS.length];
    celebrationIndex++;
    text = template(name, totalStr, sales.length);
  } else {
    // Pick a style that's DIFFERENT from the last one used
    const availableStyles = CELEBRATION_STYLES.filter(
      (s) => s.style !== lastStyleUsed,
    );
    const chosenStyle =
      availableStyles[Math.floor(Math.random() * availableStyles.length)] ||
      CELEBRATION_STYLES[0];
    const template =
      chosenStyle.templates[
        Math.floor(Math.random() * chosenStyle.templates.length)
      ];
    lastStyleUsed = chosenStyle.style;
    text = template(name, sales[0].amount);

    // Make sure we haven't used this exact text recently
    if (recentTexts.includes(text)) {
      const fallback = chosenStyle.templates.find(
        (t) => !recentTexts.includes(t(name, sales[0].amount)),
      );
      if (fallback) text = fallback(name, sales[0].amount);
    }

    // Track recent texts (keep last 10)
    recentTexts.push(text);
    if (recentTexts.length > 10) recentTexts.shift();
  }

  // Send after a brief delay so it doesn't feel instant/robotic
  setTimeout(
    () => {
      tgChannel.sendMessage(chatJid, text).catch((err) => {
        logger.error({ err }, 'Failed to send sales celebration');
      });
      logger.info(
        {
          sender: name,
          salesCount: sales.length,
          amounts: sales.map((s) => s.amount),
        },
        'Sales celebration sent',
      );
    },
    3000 + Math.random() * 5000,
  );
}
