#!/usr/bin/env python3
"""
Generate + send the inbox brief to Telegram.

Usage:
  python3 brief.py [--slot morning|afternoon|manual] [--dry-run]
"""
import sys, json, argparse, datetime, pathlib, re
sys.path.insert(0, str(pathlib.Path(__file__).parent))

from classifier import classify, extract_money_hint, extract_agent_name
from db import get_db, kv_get, kv_set
from lib import gmail_search, gmail_read, telegram_send, clean_from, trunc

CHAT_ID = "577469008"
AUTO_PAGE = 12
CARRIER_PAGE = 8
REVIEW_PAGE = 8

LEARN_ARCHIVE_THRESHOLD = 3
LEARN_KEEP_THRESHOLD = 2
LEARN_RISK_BLOCK = re.compile(
    r"action required|security|phishing|payment of \\$|debt|returned payment|past due|collections|equitrust|premiersmi|tpglife|youradvgroup|gmail\\.com|icon\\.management|ismynest|le\\s*parc|contracting|assist|urgent",
    re.I,
)


def _sender_key(email_from: str) -> str:
    s = (email_from or "").strip().lower()
    m = re.search(r'<([^>]+@[^>]+)>', s)
    if m:
        return m.group(1)
    m = re.search(r'([a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,})', s)
    if m:
        return m.group(1)
    return s[:120]


def _load_learned_map(conn):
    raw = kv_get(conn, "learn_senders", "{}") or "{}"
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {}


def _learned_override(learned: dict, msg: dict, bucket: str):
    sender = _sender_key(msg.get("from", ""))
    stats = learned.get(sender, {}) if isinstance(learned, dict) else {}
    a = int(stats.get("a", 0) or 0)
    k = int(stats.get("k", 0) or 0)

    hay = f"{msg.get('from','')} {msg.get('subject','')} {msg.get('snippet','')}"
    risky = bool(LEARN_RISK_BLOCK.search(hay))

    if k >= LEARN_KEEP_THRESHOLD and k >= a + 1:
        return "NEEDS_REVIEW", f"learned-keep:{sender}:{a}/{k}"

    if (
        bucket == "NEEDS_REVIEW"
        and not risky
        and a >= LEARN_ARCHIVE_THRESHOLD
        and a >= k + 2
    ):
        return "AUTO_CANDIDATE", f"learned-archive:{sender}:{a}/{k}"

    return bucket, ""


def fetch_new_inbox(conn, max_results=250):
    msgs = gmail_search("in:inbox", max_results=max_results)
    already = {row["gmail_id"] for row in conn.execute("SELECT gmail_id FROM classifications").fetchall()}
    new = [m for m in msgs if m["id"] not in already]
    return new, len(msgs)


def enrich_with_body(msg: dict, max_chars: int = 1800) -> dict:
    try:
        body = gmail_read(msg["id"])
    except Exception:
        return msg
    body = re.sub(r'<[^>]+>', ' ', body)
    body = re.sub(r'&\w+;', ' ', body)
    body = re.sub(r'\s+', ' ', body).strip()
    out = dict(msg)
    if not out.get("snippet"):
        out["snippet"] = body[:max_chars]
    else:
        out["snippet"] = (out["snippet"] + " " + body[:max_chars]).strip()
    return out


def _amount_to_float(amount: str) -> float:
    if not amount:
        return 0.0
    m = re.search(r'-?\$([\d,]+(?:\.\d{2})?)', amount)
    if not m:
        return 0.0
    try:
        return float(m.group(1).replace(',', ''))
    except Exception:
        return 0.0


def line_for(m: dict, show_amount: bool = False, include_snip: bool = False) -> list[str]:
    ref = m["brief_ref"]
    frm = clean_from(m["email_from"], 24)
    subj = trunc(m["email_subject"], 60)
    lines = [f" {ref}  {frm} · {subj}"]
    extras = []
    if show_amount and m.get("agent_name"):
        extras.append(f"👤 {m['agent_name']}")
    if show_amount and m.get("money_hint"):
        extras.append(f"💵 {m['money_hint']}")
    if extras:
        lines.append(f"      {'  '.join(extras)}")
    if include_snip:
        sn = trunc(m.get("snippet", ""), 90)
        if sn:
            lines.append(f"      {sn}")
    return lines


def _bucket_rows(conn, brief_id: int, bucket: str):
    return conn.execute(
        "SELECT * FROM classifications WHERE brief_id=? AND bucket=? AND final_action='pending' ORDER BY id",
        (brief_id, bucket)
    ).fetchall()


def render_brief(conn, brief_id: int, streak_day: int) -> tuple[str, dict]:
    now = datetime.datetime.now().strftime("%-I:%M %p").lstrip("0")
    auto = _bucket_rows(conn, brief_id, "AUTO_CANDIDATE")
    carrier = _bucket_rows(conn, brief_id, "CARRIER")
    review = _bucket_rows(conn, brief_id, "NEEDS_REVIEW")
    total = len(auto) + len(carrier) + len(review)

    lines = [f"📬 {now} · {total} new · streak {streak_day}/7", ""]

    def add_bucket(title, rows, limit, key, show_amount=False, include_snip=False):
        if not rows:
            return 0
        lines.append(title)
        lines.append("")
        shown = rows[:limit]
        for r in shown:
            lines.extend(line_for(dict(r), show_amount=show_amount, include_snip=include_snip))
        remaining = len(rows) - len(shown)
        if remaining > 0:
            lines.append(f"      … +{remaining} more (reply: next {key})")
        lines.append("")
        return len(shown)

    shown_auto = add_bucket(f"🗑 AUTO ({len(auto)}) — reply: archive a", auto, AUTO_PAGE, "a")
    shown_carrier = add_bucket(f"📋 CARRIER ({len(carrier)}) — reply: archive c", carrier, CARRIER_PAGE, "c", show_amount=True)
    shown_review = add_bucket(f"⚠️ REVIEW ({len(review)})", review, REVIEW_PAGE, "r", show_amount=True, include_snip=True)

    lines.append(f"Brief #{brief_id}")
    lines.append("Commands: archive / keep / show / next / reply / undo / done")
    lines.append("Shortcuts: a c r   or   a1 c2 r1")

    text = "\n".join(lines)
    if len(text) > 3800:
        text = text[:3790] + "\n… (truncated, use `next` for more)"

    cursors = {"a": shown_auto, "c": shown_carrier, "r": shown_review}
    return text, cursors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot", default="manual", choices=["morning", "afternoon", "manual"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = get_db()
    now = datetime.datetime.now().isoformat()
    streak_day = int(kv_get(conn, "streak_day", 0) or 0)

    new_msgs, total_in_inbox = fetch_new_inbox(conn)
    if not new_msgs:
        msg = f"📭 Inbox clean — {total_in_inbox} in inbox, nothing new."
        if args.dry_run:
            print(msg)
        else:
            telegram_send(CHAT_ID, msg, parse_mode="")
        return 0

    conn.execute("UPDATE briefs SET status='closed' WHERE status='open'")

    buckets = {"AUTO_CANDIDATE": [], "CARRIER": [], "NEEDS_REVIEW": []}
    learned = _load_learned_map(conn)
    for m in new_msgs:
        bucket, conf, reason = classify(m)

        bucket2, learn_reason = _learned_override(learned, m, bucket)
        if bucket2 != bucket:
            bucket = bucket2
            reason = f"{reason}|{learn_reason}" if reason else learn_reason
        enriched = m
        if bucket in ("CARRIER", "NEEDS_REVIEW"):
            enriched = enrich_with_body(m)

        money = extract_money_hint(enriched)
        agent_name = extract_agent_name(enriched) if bucket == "CARRIER" else ""

        # stronger high-signal routing: carrier debt/large-$ gets promoted to review
        hay = f"{enriched.get('subject','')} {enriched.get('snippet','')}"
        if bucket == "CARRIER":
            amt = _amount_to_float(money)
            if amt >= 500 or re.search(r'debt|debit balance|returned payment|past due|collections?', hay, re.I):
                bucket = "NEEDS_REVIEW"
                reason = f"promoted-high-signal:{reason}"

        rec = {
            "id": m["id"],
            "email_from": m.get("from", ""),
            "email_subject": m.get("subject", ""),
            "email_date": m.get("date", ""),
            "snippet": enriched.get("snippet", ""),
            "bucket": bucket,
            "confidence": conf,
            "reason": reason,
            "money_hint": money,
            "agent_name": agent_name,
        }
        buckets[bucket].append(rec)

    auto = buckets["AUTO_CANDIDATE"]
    carrier = buckets["CARRIER"]
    review = buckets["NEEDS_REVIEW"]

    cur = conn.execute(
        "INSERT INTO briefs(sent_at, slot, total_count, auto_count, carrier_count, review_count) VALUES(?, ?, ?, ?, ?, ?)",
        (now, args.slot, len(auto) + len(carrier) + len(review), len(auto), len(carrier), len(review))
    )
    brief_id = cur.lastrowid

    for i, m in enumerate(auto, 1):
        m["brief_ref"] = f"a{i}"
    for i, m in enumerate(carrier, 1):
        m["brief_ref"] = f"c{i}"
    for i, m in enumerate(review, 1):
        m["brief_ref"] = f"r{i}"

    for m in auto + carrier + review:
        conn.execute(
            "INSERT OR REPLACE INTO classifications (gmail_id, brief_id, brief_ref, classified_at, email_from, email_subject, email_date, snippet, bucket, confidence, reason, final_action) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (m["id"], brief_id, m["brief_ref"], now, m["email_from"], m["email_subject"], m["email_date"], m["snippet"], m["bucket"], m["confidence"], m["reason"], "pending")
        )
    conn.commit()

    text, cursors = render_brief(conn, brief_id, streak_day)

    if args.dry_run:
        print(text)
        return 0

    result = telegram_send(CHAT_ID, text, parse_mode="")
    tg_msg_id = result.get("message_id")
    conn.execute("UPDATE briefs SET telegram_message_id=? WHERE id=?", (tg_msg_id, brief_id))
    kv_set(conn, f"page:{brief_id}:a", cursors["a"])
    kv_set(conn, f"page:{brief_id}:c", cursors["c"])
    kv_set(conn, f"page:{brief_id}:r", cursors["r"])
    conn.commit()

    print(f"sent brief #{brief_id} tg_msg={tg_msg_id} a={len(auto)} c={len(carrier)} r={len(review)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
