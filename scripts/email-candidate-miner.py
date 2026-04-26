#!/usr/bin/env python3
"""
Weekly Email Candidate Miner

Runs Fri 2pm ET. Pulls 30 days of signals from:
  - Brain Dump (David's own voice msgs/ideas)
  - TPG UnCaged (agent wins — standout only, not every sale)
  - Story Vault (66 reference stories for theme matching)
Dedupes against already-used subjects in Notion Email Drafts DB.
Produces:
  - Top 10 ranked raw signals (quotes, source, date)
  - 5 pre-chewed draft shells (subject ≤5 words lowercase, theme/day,
    angle, which agent/story, 1-paragraph seed body)
Saves to groups/telegram_braindump/candidates/<YYYY-Www>.md AND
sends the shortlist to David via Telegram for review.

Standout filter for UnCaged wins (not every sale qualifies):
  - First-ever sale, first carrier appointment, first rewrite
  - Multi-policy combo (his & hers, family)
  - AP >= $1000 single policy, or day-total >= $2000
  - Comeback story (slump -> sale)
  - Agent language itself is post-worthy (emoji/energy, vivid phrasing)
  - Recruitment win: someone went from stuck -> producing
Everyday $50-$300 single sales without context get FILTERED OUT.
"""
import json, os, re, sys, sqlite3, datetime as dt
from pathlib import Path
import requests

ROOT = Path("/home/david/nanoclaw")
DB = ROOT / "store" / "messages.db"
BRAINDUMP_JID = "tg:-5147163125"
UNCAGED_JID   = "tg:-1002362081030"
STORY_VAULT   = ROOT / "groups" / "telegram_braindump" / "story-vault.md"
CAND_DIR      = ROOT / "groups" / "telegram_braindump" / "candidates"
NOTION_DB_ID  = "34261796-dd5b-81ac-9bef-d5794029302d"
WINDOW_DAYS   = 30

# --- env ---
ENV = {}
for line in open(ROOT / ".env"):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.strip().split("=", 1)
        ENV[k] = v.strip().strip('"').strip("'")

ANTHROPIC_KEY = ENV.get("ANTHROPIC_API_KEY")
TG_TOKEN      = ENV.get("TELEGRAM_BOT_TOKEN")
DAVID_CHAT    = "577469008"  # DM with David

# Notion key: same multi-source lookup as promoter
NOTION_KEY = None
for p in [ROOT / ".env", ROOT / "scripts" / "email-drafter-v2.py"]:
    try:
        for line in open(p):
            m = re.search(r"ntn_[a-zA-Z0-9]+", line)
            if m:
                NOTION_KEY = m.group(0); break
        if NOTION_KEY: break
    except FileNotFoundError: pass


# ---------------- signal extraction ----------------
def braindump_signals(since_iso):
    """David's own words — typed + voice transcripts. Skip photo-only lines."""
    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT timestamp, content FROM messages "
        "WHERE chat_jid=? AND sender_name='David' "
        "AND timestamp >= ? AND content IS NOT NULL "
        "AND length(content) >= 80 "
        "ORDER BY timestamp DESC",
        (BRAINDUMP_JID, since_iso)
    ).fetchall()
    con.close()
    sigs = []
    for ts, content in rows:
        # strip photo markers but keep voice transcripts
        if content.strip().startswith("[Photo:"):
            continue
        text = re.sub(r"^\[Voice message\]\s*", "", content).strip().strip('"')
        if len(text) < 80:
            continue
        sigs.append({"source":"braindump","ts":ts,"text":text[:800]})
    return sigs


# Standout detectors
DOLLAR = re.compile(r"\$\s?(\d{1,4}(?:[.,]\d{2})?)")
FIRST_EVER = re.compile(r"\b(first\s+(?:ever\s+)?(?:sale|app|application|policy|rewrite|client|carrier|writing|appointment))\b", re.I)
COMBO = re.compile(r"\b(his\s*(?:&|and)\s*hers|husband\s*(?:&|and)\s*wife|family|couple|2\s*apps|two\s*apps|\d+\s*policies)\b", re.I)
COMEBACK = re.compile(r"\b(slump|dry\s*spell|back\s*in|first\s+(sale|app)\s+(in|back)|finally|breakthrough|comeback)\b", re.I)
VIVID = re.compile(r"[🔥⚔️⚡️💰🎯✝️♥️]{1,}|!{2,}|CAPS LOCK", re.I)
EXCLUDED_SENDERS = {"Gina", "Andy", "David Price"}  # VA, bot, David himself

def score_uncaged_msg(row):
    ts, sender, content = row
    if not content or len(content) < 30: return 0, []
    if sender in EXCLUDED_SENDERS: return 0, []
    if content.strip().startswith(("# TPG", "## ", "LEADERBOARD", "Daily recap")): return 0, []  # bot reports
    reasons = []
    # total AP detection
    dollars = [float(m.replace(",","")) for m in DOLLAR.findall(content)]
    total = sum(dollars) if dollars else 0
    biggest = max(dollars) if dollars else 0
    if biggest >= 1000:
        reasons.append(f"big_single_AP:${biggest:.0f}")
    if total >= 2000 and len(dollars) >= 2:
        reasons.append(f"big_day_total:${total:.0f}×{len(dollars)}")
    if FIRST_EVER.search(content):
        reasons.append("first_ever:" + FIRST_EVER.search(content).group(0))
    if COMBO.search(content) and dollars:
        reasons.append("combo_sale:" + COMBO.search(content).group(0))
    if COMEBACK.search(content):
        reasons.append("comeback:" + COMEBACK.search(content).group(0))
    if VIVID.search(content) and dollars:
        reasons.append("vivid_energy")
    # everyday single small sale without other hooks = 0
    if not reasons and dollars and biggest < 500 and len(dollars) == 1:
        return 0, []
    score = len(reasons) + (biggest / 1000 if biggest else 0)
    return score, reasons


def uncaged_signals(since_iso):
    con = sqlite3.connect(DB)
    rows = con.execute(
        "SELECT timestamp, sender_name, content FROM messages "
        "WHERE chat_jid=? AND timestamp >= ? AND is_bot_message=0 "
        "AND content IS NOT NULL AND length(content) >= 30 "
        "ORDER BY timestamp DESC",
        (UNCAGED_JID, since_iso)
    ).fetchall()
    con.close()
    sigs = []
    for ts, sender, content in rows:
        score, reasons = score_uncaged_msg((ts, sender, content))
        if score < 1.0:  # threshold — standout only
            continue
        sigs.append({
            "source":"uncaged","ts":ts,"agent":sender,
            "text":content[:500],"score":round(score,2),"reasons":reasons
        })
    sigs.sort(key=lambda s: -s["score"])
    return sigs


# ---------------- dedupe ----------------
def used_subjects():
    if not NOTION_KEY: return set()
    H = {"Authorization":f"Bearer {NOTION_KEY}","Notion-Version":"2022-06-28","Content-Type":"application/json"}
    used = set()
    cursor = None
    while True:
        body = {"page_size":100}
        if cursor: body["start_cursor"] = cursor
        r = requests.post(f"https://api.notion.com/v1/databases/{NOTION_DB_ID}/query",
                          headers=H, json=body, timeout=30)
        if r.status_code != 200: break
        j = r.json()
        for p in j.get("results",[]):
            t = p["properties"].get("Subject",{}).get("title",[])
            s = "".join(x.get("plain_text","") for x in t).lower().strip()
            if s: used.add(s)
        if not j.get("has_more"): break
        cursor = j.get("next_cursor")
    return used


# ---------------- Claude ranking + drafting ----------------
CLAUDE_MODELS = ["claude-opus-4-7", "claude-opus-4-5-20250929", "claude-sonnet-4-5"]

def call_claude(system, user, max_tokens=4000):
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    last_err = None
    for m in CLAUDE_MODELS:
        try:
            r = client.messages.create(
                model=m, max_tokens=max_tokens,
                system=system,
                messages=[{"role":"user","content":user}],
            )
            return r.content[0].text, m
        except Exception as e:
            last_err = e
    raise RuntimeError(f"Claude failed: {last_err}")


RANK_SYSTEM = """You are David Price's email editor. You're picking standout signals from this week's Brain Dump and TPG UnCaged chat that should become emails for his 5,690-agent list (100D Engage).

HARD RULES you enforce:

SUBJECT: 2-5 words, lowercase, no quotes/parens/punctuation, cliffhanger pattern-break. Not a headline, not a summary. Make them HAVE to open.
  Good: 'you work too much' / 'she borrowed 35' / 'dead lead came back'
  Bad:  'Katie just closed a dead lead from 6 months ago' / 'how to follow up'

OPENER: First word of body = the hook. NO greeting ever (no Hey, Hi, Hello, Hey [Name]). NO setup ('So here is...' / 'Let me tell you...'). Drop reader mid-scene.
  Good: 'Katie closed a lead from October.'
  Bad:  'Hey,

So here is what is wild.'

CLOSING: End with 'Never Settle' on its own line. Nothing after. No Talk soon / Best / David signoff.

FORMAT: When outputting seed bodies, output ONLY the text. No 'Here is the email:' / 'Formatted as...' preamble.

OTHER: No personalization tokens, no merge tags, no recipient first names. Agent first names (Taylor, Kari, Jamie) as subjects of the story are fine. Reply-CTA only, no links. $<500 single = monthly × 12 for AP; always cite AP. Never fabricate — every name/$/date must come from source signals. Dedupe against already-used subjects.
- Five daily themes: Monday Education, Tuesday Agent Proof, Wednesday Mindset, Thursday Behind Scenes, Friday Momentum.

Your output is TWO sections, plain text:

=== TOP 10 RAW SIGNALS (ranked) ===
1. [source|date|agent(if any)] one-sentence why-it's-email-worthy
   QUOTE: short verbatim snippet (≤120 chars)
... (10 total, ranked)

=== 5 PRE-CHEWED DRAFT SHELLS ===
For each of 5:
  DAY: Monday Education  (or Tue/Wed/Thu/Fri + theme)
  SUBJECT: xxx xxx xxx
  ANGLE: one sentence on the lesson/hook
  FEATURES: which agent(s), which $/AP, which story from Brain Dump
  SEED BODY: one opening paragraph in David's voice (short sentences, no dashes, no AI words, no emojis) — not the full email, just the opener so David can see if the angle lands.

End with "Never Settle" on its own line for each seed.
"""

def rank_and_draft(bd_sigs, uc_sigs, used):
    # trim to the best raw material
    bd = bd_sigs[:25]
    uc = uc_sigs[:40]
    blob = "ALREADY-USED SUBJECTS (skip these themes):\n" + "\n".join("- "+u for u in sorted(used)) + "\n\n"
    blob += "=== BRAIN DUMP (David's own voice, past 30d) ===\n"
    for s in bd:
        blob += f"[{s['ts'][:10]}] {s['text']}\n---\n"
    blob += "\n=== TPG UNCAGED STANDOUT WINS (past 30d) ===\n"
    for s in uc:
        blob += f"[{s['ts'][:10]}] {s['agent']} (score {s['score']}, {','.join(s['reasons'])}):\n{s['text']}\n---\n"
    return call_claude(RANK_SYSTEM, blob, max_tokens=4500)


# ---------------- telegram ----------------
def tg_send(text):
    if not TG_TOKEN: return
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    # split if >4000 chars
    for i in range(0, len(text), 3800):
        chunk = text[i:i+3800]
        requests.post(url, data={"chat_id":DAVID_CHAT,"text":chunk,"disable_web_page_preview":"true"}, timeout=30)


# ---------------- main ----------------
def main():
    since = (dt.datetime.utcnow() - dt.timedelta(days=WINDOW_DAYS)).isoformat() + "Z"
    bd = braindump_signals(since)
    uc = uncaged_signals(since)
    used = used_subjects()

    CAND_DIR.mkdir(parents=True, exist_ok=True)
    wk = dt.date.today().isocalendar()
    fname = CAND_DIR / f"{wk.year}-W{wk.week:02d}.md"

    stats = f"braindump:{len(bd)} uncaged_standouts:{len(uc)} used_subjects:{len(used)}"
    print(f"[miner] {stats}")

    if not bd and not uc:
        tg_send(f"Weekly miner: no standout signals past {WINDOW_DAYS}d. {stats}")
        return

    try:
        out, model = rank_and_draft(bd, uc, used)
    except Exception as e:
        tg_send(f"Weekly miner FAILED: {e}\n{stats}")
        raise

    header = f"# Weekly Email Candidates — {wk.year}-W{wk.week:02d}\n" \
             f"Generated: {dt.datetime.utcnow().isoformat()}Z  model={model}\n" \
             f"Signals: {stats}\n\n"
    fname.write_text(header + out)
    print(f"[miner] wrote {fname}")

    tg_send(f"📬 Weekly email candidates ready — {stats}\nFile: {fname.name}\n\n" + out[:3500])


if __name__ == "__main__":
    main()
