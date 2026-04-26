"""
SQLite schema for inbox-brief state.

Tables:
  classifications    — one row per email-classification decision
  user_actions       — one row per user action (archive/keep/reply)
  briefs             — one row per brief sent to Telegram
  streak             — simple key-value for the 7-day confidence gate
"""
import sqlite3, pathlib

DB_PATH = pathlib.Path("/home/david/nanoclaw/store") / "inbox-brief.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS classifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_id TEXT UNIQUE,              -- gmail message id (the internal one)
    brief_id INTEGER,                  -- FK to briefs.id
    brief_ref TEXT,                    -- human short ref: a1, c2, r3
    classified_at TEXT NOT NULL,
    email_from TEXT,
    email_subject TEXT,
    email_date TEXT,
    snippet TEXT,
    bucket TEXT NOT NULL,              -- AUTO_CANDIDATE | CARRIER | NEEDS_REVIEW
    confidence REAL,
    reason TEXT,
    final_action TEXT,                 -- archived | kept | replied | pending
    action_at TEXT,
    action_by TEXT                     -- user | auto | pending
);
CREATE INDEX IF NOT EXISTS idx_cls_gmail ON classifications(gmail_id);
CREATE INDEX IF NOT EXISTS idx_cls_brief ON classifications(brief_id);
CREATE INDEX IF NOT EXISTS idx_cls_action ON classifications(final_action);

CREATE TABLE IF NOT EXISTS briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sent_at TEXT NOT NULL,
    slot TEXT NOT NULL,                -- 'morning' | 'afternoon' | 'manual'
    telegram_message_id INTEGER,
    total_count INTEGER,
    auto_count INTEGER,
    carrier_count INTEGER,
    review_count INTEGER,
    status TEXT DEFAULT 'open'         -- open | closed
);

CREATE TABLE IF NOT EXISTS user_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    brief_id INTEGER,
    received_at TEXT NOT NULL,
    command TEXT NOT NULL,             -- raw text
    parsed_action TEXT,                -- archive | keep | show | reply
    targets TEXT,                      -- JSON list of refs
    result TEXT
);

CREATE TABLE IF NOT EXISTS kv (
    k TEXT PRIMARY KEY,
    v TEXT,
    updated_at TEXT
);
"""

def get_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn

def kv_get(conn, k, default=None):
    row = conn.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
    return row["v"] if row else default

def kv_set(conn, k, v):
    import datetime
    conn.execute(
        "INSERT INTO kv(k,v,updated_at) VALUES(?,?,?) "
        "ON CONFLICT(k) DO UPDATE SET v=excluded.v, updated_at=excluded.updated_at",
        (k, str(v), datetime.datetime.now().isoformat()),
    )
    conn.commit()
