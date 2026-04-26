# Cold Email Launch Plan — Insurance Agent Recruitment

**Owner:** David Price (The Price Group / TPG Life)
**Today's date:** 2026-04-24
**Status:** Pipeline built. Copy written. Zero tooling accounts exist yet. Nothing is sending.
**Goal:** Launch a compliant, high-deliverability cold email pipeline to recruit US life insurance agents, using NAIC-scraped data.

---

## 1. Business Context

David runs The Price Group (TPG Life), an insurance agency recruiting licensed life insurance agents across all 50 US states. He pays independent agents higher commissions (80-140% first year) than captive carriers, provides leads, mentorship, and portable books of business.

The cold email pipeline is a scale lever: instead of manually sourcing agents, identify freshly-licensed agents from state insurance department data, email them with a value-first sequence before competitors lock them into captive contracts.

**Two audiences:**
- **Sequence A — New Licensees:** agents with `is_new_licensee = true` and `appointments_count = 0` (no carrier yet)
- **Sequence B — Single-Carrier Agents:** agents with `appointments_count = 1` (committed to one carrier — show what they're missing)

---

## 2. What's Already Built

### Data pipeline
- **NAIC SOLAR scraper** (Python/Selenium) — 36 US states, auto-advance, prefix-level resume, Chrome crash recovery. Scrapes ALL active Insurance Producers (Life, Health, Property, Casualty — no LOA filter).
- **Supabase** (`snsoophwazxusonudtkv.supabase.co`, project "insurance-agent-pipeline")
  - `agents` table with pipeline columns
  - `appointments` table
  - `scrape_runs` state queue
- **IPRoyal residential proxies** (geo.iproyal.com:12321, IP whitelist auth)
- **Hetzner server** (89.167.109.12, SSH user: david) with Docker Compose `restart: always`
- **New licensee detection** — agents with 0 appointments get `is_new_licensee=true` and +30 score points

### Copy
- **10 emails total** written and ready to paste into any sending tool
- Sequence A: 5 emails over 10 days (Day 0/2/5/7/10)
- Sequence B: 5 emails over 14 days (Day 0/3/7/10/14)
- Each email has 2 subject-line A/B variants
- Variables used: `{firstName}`, `{state}`, `{carrier}`
- Tone: value-first, no hard selling, signed "David Price, Insurance Industry Leader"
- Full copy lives at `insurance-scraper/email-sequences.md` in the repo

### Monitoring (existing in "NanoClaw" personal-assistant system)
- `recruitment-pipeline-daily` cron — daily pipeline report to Discord #agent-scraper at 6PM
- `recruitment-new-licensee-alert` cron — noon alert (currently broken, exit 137)
- `recruitment-scraper-health` cron — every 6 hours
- `recruitment-daily-capture` cron — weekdays 6PM
- `recruitment-weekly-digest` cron — Monday 8AM

---

## 3. What's Missing (Everything Tooling-Related)

**Zero accounts exist for any of the following. All must be created.**

| Tool | Purpose | Est. cost |
|------|---------|-----------|
| Smartlead.ai | Sending platform (campaigns, warmup, inbox rotation, unsubscribe, reply detection) | $39-94/mo |
| ZeroBounce | Email verification before send (filter bounces/traps) | ~$16 per 10k verifications |
| GlockApps | Seed-based deliverability testing (inbox placement, spam score) | $59-99/mo |
| Cold sending domains | Reputation-isolated sender domains (NEVER send cold from tpglife.com) | ~$12/yr per domain |
| Google Workspace mailboxes | One per cold domain, 2-3 mailboxes per domain | $6/user/mo |

**Domain strategy:** purchase 3-5 lookalike domains (e.g. `tpgleaders.com`, `agentsfuture.com`, `pricegroupcareers.com`) — NOT tpglife.com, to protect the primary domain's reputation. Each domain gets 2-3 mailboxes, each mailbox sends 30-50 emails/day once warmed.

---

## 4. The Full Launch Plan

### Phase 0 — Procurement & Setup (Days 1-2)

1. **Buy 3-5 cold domains** at Namecheap/Cloudflare (~$60/year total)
   - Brandable, NOT a lookalike typosquat of tpglife.com
   - Suggested: `tpgleaders.com`, `agentcareers.io`, `pricegroupagents.com`
2. **Create Google Workspace accounts** on each cold domain ($18-30/domain/mo)
   - 2-3 mailboxes per domain: `david@`, `outreach@`, `david.price@`
3. **DNS configuration for each domain:**
   - MX records (Google)
   - SPF: `v=spf1 include:_spf.google.com ~all`
   - DKIM: generate via Google Admin, add TXT record
   - DMARC: `v=DMARC1; p=none; rua=mailto:dmarc@domain.com` (start `p=none`, tighten later)
4. **Sign up for Smartlead**, connect all mailboxes, enable warmup for each
5. **Sign up for ZeroBounce** — get API key
6. **Sign up for GlockApps** — no API needed initially, use their seed list

### Phase 1 — Warmup (Days 2-16, 14 days)

**Critical. No real sends until this completes.**

- Smartlead's built-in warmup sends 20-40 auto-replies per day between your mailboxes and Smartlead's network
- Ramps sender reputation, gets into Gmail/Outlook inbox (not spam)
- **Do nothing but wait 14 days**
- Monitor: Smartlead dashboard should show green "warmed" status on each mailbox before flipping to campaign mode

### Phase 2 — List Hygiene (During warmup, Days 2-7)

Runs in parallel with warmup. No blocker.

1. Export target agents from Supabase `agents` table:
   ```sql
   SELECT first_name, last_name, email, state, carrier, is_new_licensee, appointments_count
   FROM agents
   WHERE email IS NOT NULL
     AND email_status IS NULL
     AND (is_new_licensee = true OR appointments_count = 1);
   ```
2. Run through ZeroBounce API (bulk validation endpoint)
3. Keep only `valid` + `catch-all`; drop `invalid`, `spamtrap`, `abuse`, `do_not_mail`
4. Write back to Supabase:
   ```sql
   ALTER TABLE agents ADD COLUMN email_status TEXT;
   ALTER TABLE agents ADD COLUMN email_verified_at TIMESTAMPTZ;
   ```
5. **Target bounce rate on actual sends: <2%**

### Phase 3 — Campaign Build in Smartlead (Day 14)

1. Create two campaigns:
   - `Seq A — New Licensees (5 emails, 10 days)`
   - `Seq B — Single Carrier (5 emails, 14 days)`
2. Paste email bodies from `insurance-scraper/email-sequences.md`
3. Wire merge tags: `{{firstName}}`, `{{state}}`, `{{carrier}}`
4. Configure A/B subject-line test per email (each has 2 variants)
5. Attach all warmed mailboxes with 30-50 sends/day cap each
6. Enable: unsubscribe link (required), physical address in footer (CAN-SPAM)
7. Disable: link tracking pixels, HTML wrapping on cold touches (plain-text style inboxes better)
8. Set reply detection → forward replies to David's inbox

### Phase 4 — Deliverability Gate (Day 14-15)

**Do not launch unless this passes.**

1. Run GlockApps seed test on both sequences (all 10 emails)
2. **Gate criteria:**
   - Inbox placement ≥ 90%
   - Spam folder < 5%
   - Promotions tab < 10%
   - Spam score < 3 (lower is better)
3. If any email fails:
   - Check for spam-trigger words ("guaranteed income", "6-figures", excessive caps)
   - Verify SPF/DKIM/DMARC alignment
   - Check sending domain isn't on blocklists (MXToolbox scan)
   - Rewrite + retest
4. Confirm: every sending mailbox passes auth (SPF pass, DKIM aligned, DMARC aligned)

### Phase 5 — Soft Launch (Days 15-18, 50-agent pilot)

1. Pull 50 verified agents from Supabase: 25 Sequence A + 25 Sequence B
2. Stagger sends across 3 days (no single blast)
3. Monitor daily:
   - Bounce rate (target <2%)
   - Open rate (target >40%)
   - Reply rate (target >2%)
   - Spam complaints (target 0 — any complaint = pause + investigate)
   - Unsubscribe rate (target <1%)
4. Capture replies in Supabase `agent_replies` table for analysis

### Phase 6 — Scale (Day 18 onward)

1. Ramp to 200-300 sends/day total across all warmed mailboxes
2. Weekly list refresh: pull new `is_new_licensee=true` agents from scraper
3. Weekly: verify new emails through ZeroBounce, cull bounces
4. Monthly: GlockApps re-test to catch reputation drift
5. Weekly review in Discord `#agent-scraper`:
   - Campaigns sent/delivered/opened/replied
   - New pipeline adds (interested leads)
   - Deliverability trend

### Phase 7 — Operational Integration (Day 21+)

- Replies → route to David's Telegram `telegram_main` for review
- Interested leads → create Supabase `pipeline_leads` row + alert in Discord `#agent-scraper`
- Gina (David's VA, gina@tpglife.com) handles reply triage on positives
- Existing `recruitment-pipeline-daily` cron (6PM) extended to include cold email funnel metrics

---

## 5. Budget Summary (Month 1)

| Line item | Cost |
|-----------|------|
| 3 cold domains (annual) | $36 |
| Google Workspace (3 domains × 2 mailboxes × $6) | $36/mo |
| Smartlead Basic | $39/mo |
| ZeroBounce credits (~25k verifications) | $50 one-time |
| GlockApps Starter | $59/mo |
| **Month 1 total** | **~$220** |
| **Ongoing monthly** | **~$134/mo** |

---

## 6. Critical Rules

1. **NEVER send cold email from tpglife.com.** Domain reputation damage would cripple legitimate TPG email.
2. **Never skip warmup.** 14 days minimum. Cold IPs to inbox placement without warmup = spam folder permanent.
3. **Always verify before send.** ZeroBounce first, every time. A 10% bounce rate burns domain reputation in days.
4. **Signature must match reality.** "David Price, Insurance Industry Leader" — real person, real business, physical address in footer.
5. **CAN-SPAM compliance:** unsubscribe link + physical address + honest subject lines in every email.
6. **Reply within 24 hours** to any interested reply. Cold outreach only works if follow-through is fast.

---

## 7. Open Decisions Needed from David

1. **Domain names** — purchase 3 of: `tpgleaders.com`, `agentcareers.io`, `pricegroupcareers.com`, or own suggestions?
2. **Physical address for footer** — home, TPG Life office, or PO Box?
3. **Reply handler** — David reviews all replies, or Gina triages first with David on "hot" only?
4. **Starting volume** — aggressive ramp (300/day by week 4) or conservative (100/day, scale over 2 months)?
5. **Sequence priority** — launch both A and B simultaneously, or A first (new licensees = higher intent) then B?

---

## 8. Success Metrics (90 days out)

| Metric | Target |
|--------|--------|
| Emails sent | 15,000+ |
| Delivery rate | >98% |
| Open rate (avg) | >40% |
| Reply rate | >2% (300+ replies) |
| Qualified leads (scheduled calls) | 50+ |
| Agents contracted from cold pipeline | 5-10 |
| Cost per contracted agent | <$500 |
| Domain reputation | all green on GlockApps monthly |

---

## 9. Risk Register

| Risk | Mitigation |
|------|------------|
| Domain reputation burn from bad list | ZeroBounce every email before send |
| Spam complaints tank deliverability | GlockApps gate before launch; pause on any complaint |
| Gmail/Outlook policy change mid-campaign | Monthly re-test; keep warmup running always |
| Replies missed → lose hot leads | Smartlead reply forwarding → Telegram; 24h SLA |
| Legal (CAN-SPAM violation) | Physical address + unsubscribe in every email; honor opt-outs within 10 days |
| NAIC data freshness | Scraper already runs daily; new licensees flow in automatically |

---

## 10. Where to Find Things

| Artifact | Location |
|----------|----------|
| Email sequences (full copy) | `insurance-scraper/email-sequences.md` |
| NAIC scraper | `insurance-scraper/scraper.py` |
| Supabase schema | `insurance-scraper/schema.sql` |
| Docker deploy | `insurance-scraper/Dockerfile` + `docker-compose.yml` |
| Server | Hetzner 89.167.109.12, SSH user david |
| Supabase project | snsoophwazxusonudtkv.supabase.co ("insurance-agent-pipeline") |
| NanoClaw monitoring | `groups/discord_agent_scraper/CLAUDE.md` |

---

**Next concrete action:** David decides on 3 cold domain names + answers Q3/Q4/Q5 above, then Phase 0 procurement can begin.
