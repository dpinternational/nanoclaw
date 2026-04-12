import fs from 'fs';

import { SENDER_ALLOWLIST_PATH } from './config.js';
import { logger } from './logger.js';

export interface ChatAllowlistEntry {
  allow: '*' | string[];
  mode: 'trigger' | 'drop';
}

export interface SenderAllowlistConfig {
  default: ChatAllowlistEntry;
  chats: Record<string, ChatAllowlistEntry>;
  logDenied: boolean;
}

const DEFAULT_CONFIG: SenderAllowlistConfig = {
  default: { allow: '*', mode: 'trigger' },
  chats: {},
  logDenied: true,
};

function isValidEntry(entry: unknown): entry is ChatAllowlistEntry {
  if (!entry || typeof entry !== 'object') return false;
  const e = entry as Record<string, unknown>;
  const validAllow =
    e.allow === '*' ||
    (Array.isArray(e.allow) && e.allow.every((v) => typeof v === 'string'));
  const validMode = e.mode === 'trigger' || e.mode === 'drop';
  return validAllow && validMode;
}

export function loadSenderAllowlist(
  pathOverride?: string,
): SenderAllowlistConfig {
  return loadSenderAllowlistCached(pathOverride);
}

// --- Cached loader: checks file mtime every 60s instead of reading disk per message ---
let _cachedConfig: SenderAllowlistConfig | null = null;
let _cachedMtimeMs = 0;
let _lastCheckMs = 0;
const CACHE_TTL_MS = 60_000; // Re-check file mtime every 60s

function loadSenderAllowlistCached(
  pathOverride?: string,
): SenderAllowlistConfig {
  const filePath = pathOverride ?? SENDER_ALLOWLIST_PATH;

  // Bypass cache when using a custom path (e.g. tests)
  if (pathOverride) {
    return loadSenderAllowlistFromDisk(filePath);
  }

  const now = Date.now();

  // Within TTL window and we have a cached value — return it
  if (_cachedConfig && now - _lastCheckMs < CACHE_TTL_MS) {
    return _cachedConfig;
  }

  _lastCheckMs = now;

  // Check if file has changed (stat is much cheaper than read+parse)
  try {
    const stat = fs.statSync(filePath);
    if (_cachedConfig && stat.mtimeMs === _cachedMtimeMs) {
      return _cachedConfig;
    }
    _cachedMtimeMs = stat.mtimeMs;
  } catch {
    // File doesn't exist or can't stat — fall through to full load
  }

  _cachedConfig = loadSenderAllowlistFromDisk(filePath);
  return _cachedConfig;
}

function loadSenderAllowlistFromDisk(
  filePath: string,
): SenderAllowlistConfig {

  let raw: string;
  try {
    raw = fs.readFileSync(filePath, 'utf-8');
  } catch (err: unknown) {
    if ((err as NodeJS.ErrnoException).code === 'ENOENT') return DEFAULT_CONFIG;
    logger.warn(
      { err, path: filePath },
      'sender-allowlist: cannot read config',
    );
    return DEFAULT_CONFIG;
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    logger.warn({ path: filePath }, 'sender-allowlist: invalid JSON');
    return DEFAULT_CONFIG;
  }

  const obj = parsed as Record<string, unknown>;

  if (!isValidEntry(obj.default)) {
    logger.warn(
      { path: filePath },
      'sender-allowlist: invalid or missing default entry',
    );
    return DEFAULT_CONFIG;
  }

  const chats: Record<string, ChatAllowlistEntry> = {};
  if (obj.chats && typeof obj.chats === 'object') {
    for (const [jid, entry] of Object.entries(
      obj.chats as Record<string, unknown>,
    )) {
      if (isValidEntry(entry)) {
        chats[jid] = entry;
      } else {
        logger.warn(
          { jid, path: filePath },
          'sender-allowlist: skipping invalid chat entry',
        );
      }
    }
  }

  return {
    default: obj.default as ChatAllowlistEntry,
    chats,
    logDenied: obj.logDenied !== false,
  };
}

function getEntry(
  chatJid: string,
  cfg: SenderAllowlistConfig,
): ChatAllowlistEntry {
  return cfg.chats[chatJid] ?? cfg.default;
}

export function isSenderAllowed(
  chatJid: string,
  sender: string,
  cfg: SenderAllowlistConfig,
): boolean {
  const entry = getEntry(chatJid, cfg);
  if (entry.allow === '*') return true;
  return entry.allow.includes(sender);
}

export function shouldDropMessage(
  chatJid: string,
  cfg: SenderAllowlistConfig,
): boolean {
  return getEntry(chatJid, cfg).mode === 'drop';
}

export function isTriggerAllowed(
  chatJid: string,
  sender: string,
  cfg: SenderAllowlistConfig,
): boolean {
  const allowed = isSenderAllowed(chatJid, sender, cfg);
  if (!allowed && cfg.logDenied) {
    logger.debug(
      { chatJid, sender },
      'sender-allowlist: trigger denied for sender',
    );
  }
  return allowed;
}
