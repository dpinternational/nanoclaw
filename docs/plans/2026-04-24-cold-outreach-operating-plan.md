# Cold Outreach Operating Plan (Insurance Database -> Cold Email)

Owner: David Price
Last updated: 2026-04-24
Scope: Cold outreach only (separate from CR broadcast list)

--------------------------------------------------
## 1) Mission
Build and run a repeatable cold outreach system that:
1) pulls/scrapes agent leads from insurance data,
2) verifies emails with ZeroBounce,
3) sends via Smartlead on warmed domains,
4) gates launch quality with GlockApps,
5) scales only when deliverability + reply metrics stay healthy.

--------------------------------------------------
## 2) Source of truth files
- Master launch plan:
  - /Users/davidprice/nanoclaw/docs/COLD_EMAIL_LAUNCH_PLAN.md
- Email verification + Smartlead-ready CSV export:
  - /Users/davidprice/nanoclaw/insurance-scraper/verify_emails.py
- Latest verification run log:
  - /Users/davidprice/nanoclaw/insurance-scraper/out/verify_run_20260424_135522.log
- Latest CSV outputs:
  - /Users/davidprice/nanoclaw/insurance-scraper/out/seq_a_new_licensees.csv
  - /Users/davidprice/nanoclaw/insurance-scraper/out/seq_b_single_carrier.csv
- Env keys (local):
  - /Users/davidprice/nanoclaw/insurance-scraper/.env

--------------------------------------------------
## 3) Current status snapshot (as of 2026-04-25)
DONE
[x] Cold outreach stack confirmed as separate from CR.
[x] TrulyInbox warmup tool present and bookmarked.
[x] Smartlead account/API key present.
[x] ZeroBounce account/API key present.
[x] ZeroBounce batch verification pipeline running.
[x] Fresh verification completed.
[x] Smartlead sync probe successful (24 mailboxes fetched/upserted).
[x] Smartlead webhook created and updated for reply + bounce + lead-category events (id 561927).
[x] GlockApps API auth + base URL verified (`/projects` and `/providers` return 200).

Verification output (latest run)
- Total verified: 12,147
- Sendable (valid + catch-all): 11,149 (91.8%)
- Status mix: valid 9,329 | catch-all 1,820 | invalid 580 | do_not_mail 149 | abuse 114 | unknown 154 | spamtrap 1
- Sequence CSV row counts:
  - Seq A (new licensees): 9,066 leads (+header)
  - Seq B (single carrier): 2,083 leads (+header)

NOT DONE / PENDING
[ ] Warmup complete across all 24 mailboxes (currently none ready).
[ ] GlockApps deliverability gate documented with pass/fail results for these exact sequences/domains.
[ ] Smartlead campaign import/execution checklist completed for current CSVs.
[ ] Pilot send completed and measured.

Warmup inventory (24 mailboxes across 8 domains)
Current state: WARMING (none ready yet)

- pricerecruits.com
  - david@pricerecruits.com
  - david.price@pricerecruits.com
  - davidprice@pricerecruits.com

- tpgagentteam.com
  - david@tpgagentteam.com
  - david.price@tpgagentteam.com
  - davidprice@tpgagentteam.com

- tpgopportunity.com
  - david@tpgopportunity.com
  - david.price@tpgopportunity.com
  - davidprice@tpgopportunity.com

- davidpricetpg.com
  - david@davidpricetpg.com
  - david.price@davidpricetpg.com
  - davidprice@davidpricetpg.com

- davidpriceinsurance.com
  - david@davidpriceinsurance.com
  - david.price@davidpriceinsurance.com
  - davidprice@davidpriceinsurance.com

- growtpg.com
  - david@growtpg.com
  - david.price@growtpg.com
  - davidprice@growtpg.com

- insurancecareerpath.com
  - david@insurancecareerpath.com
  - david.price@insurancecareerpath.com
  - davidprice@insurancecareerpath.com

- tpgagents.com
  - david@tpgagents.com
  - david.price@tpgagents.com
  - davidprice@tpgagents.com

--------------------------------------------------
## 4) Stage gates (must pass in order)
Gate 0 - Infrastructure readiness
- Domains warmed in TrulyInbox (or equivalent warmup status acceptable).
- DNS auth correct for sending domains (SPF/DKIM/DMARC).
- Smartlead mailboxes connected and healthy.
Exit criteria: all mailboxes green enough to pilot.

Gate 1 - List hygiene
- Run verify_emails.py against eligible scraped records.
- Include only valid + catch-all in export.
- Exclude invalid, do_not_mail, abuse, spamtrap.
Exit criteria: fresh CSVs generated and archived.

Gate 2 - Campaign setup in Smartlead
- Import Seq A and Seq B CSVs.
- Attach correct sequence copy and timing.
- Ensure unsubscribe + compliance fields configured.
Exit criteria: campaigns ready but not launched.

Gate 3 - Deliverability gate (GlockApps)
- Seed test representative emails from each sequence.
- Log inbox placement + spam placement by domain/mailbox.
Exit criteria (target):
- Inbox >= 90%
- Spam < 5%
- Promotions < 10%
- Any mailbox/domain failing is held back.

Gate 4 - Pilot launch
- Start with controlled sample (ex: 25 Seq A + 25 Seq B).
- Monitor 72 hours before scaling.
Exit criteria:
- Bounce < 2%
- Complaints = 0
- Positive reply trend

Gate 5 - Scale
- Increase gradually only if Gate 4 stays healthy.
- Keep continuous warmup + periodic GlockApps re-checks.

--------------------------------------------------
## 5) Next actions (priority order)
Immediate next action
1. Finish warmup to readiness across all 24 mailboxes (no sends yet).

Then
2. Run GlockApps tests for ready mailboxes/domains and record pass/fail in this plan.
3. Import fresh CSVs into Smartlead:
   - seq_a_new_licensees.csv
   - seq_b_single_carrier.csv
4. Build/verify the two campaign flows in Smartlead.
5. Launch 50-lead pilot only after GlockApps pass.
6. 72-hour review: bounce, complaint, open, reply, interested-lead count.
7. Decide scale step (hold / +25% / +50%) by data.

--------------------------------------------------
## 6) 72-hour pilot scorecard template
Date range: __________
Sending domains/mailboxes used: __________
Leads sent: __________

Performance
- Delivered: __________
- Bounce rate: __________
- Spam complaints: __________
- Open rate: __________
- Reply rate: __________
- Positive replies: __________
- Meetings booked: __________

Decision
[ ] Scale up
[ ] Hold steady
[ ] Pause/fix deliverability
Reason: ______________________________________

--------------------------------------------------
## 7) Operating rhythm
Daily
- Check Smartlead mailbox health + replies.
- Watch bounce/complaint anomalies.
- Ensure warmup remains active.

Weekly
- Refresh lead pull from scraper output.
- Re-run ZeroBounce validation for new leads.
- Remove/reduce underperforming mailboxes/domains.
- Review campaign-level metrics and adjust copy only with evidence.

Monthly
- GlockApps retest across active mailboxes/domains.
- Domain reputation review and pruning decisions.

--------------------------------------------------
## 8) Hard rules
1) Cold outreach never uses tpglife.com.
2) No launch without warmup + auth + deliverability gate.
3) No scaling when complaints > 0 or bounce drifts above threshold.
4) Keep CR broadcast ops and cold outreach ops fully separate.
5) Never send from a mailbox that is not "Ready for Outreach".
   - Enforced allowlist file: `/Users/davidprice/nanoclaw/insurance-scraper/config/ready_for_outreach_emails.txt`
   - Required preflight command before any launch/unpause:
     - `python3 /Users/davidprice/nanoclaw/insurance-scraper/scripts/enforce_ready_senders.py --strict-auth`
   - Canonical guarded launcher (Seq A/B campaigns):
     - Dry-run: `/Users/davidprice/nanoclaw/insurance-scraper/scripts/launch_seq_campaigns_guarded.sh launch`
     - Execute launch: `/Users/davidprice/nanoclaw/insurance-scraper/scripts/launch_seq_campaigns_guarded.sh launch --execute LAUNCH`
     - Execute pause: `/Users/davidprice/nanoclaw/insurance-scraper/scripts/launch_seq_campaigns_guarded.sh pause --execute PAUSE`
   - If guard fails or confirm phrase is wrong, launch is blocked.

--------------------------------------------------
## 9) Change log
2026-04-25
- Verified Smartlead sync probe works: 24 mailboxes fetched/upserted, no campaigns yet.
- Updated Smartlead webhook config to include `EMAIL_BOUNCED` in addition to reply and lead-category events.
- Replaced webhook 561829 with webhook 561927 (`tpg-recruiting-campaign-replied-bounced-v1`) at `https://webhook.site/b0d0489e-98b9-47c0-be32-863c032d5a1f`.
- Verified Smartlead API write access with non-send test actions (temporary campaign/lead/category update + cleanup).
- Verified GlockApps API auth/base URL works with `apiKey` query param at `/gateway/spamtest-v2/api` (`/projects` and `/providers` return 200).
- Added detailed scale plan: `/Users/davidprice/nanoclaw/docs/plans/2026-04-25-cold-outreach-scale-plan.md`.
- Updated snapshot date and done items to reflect current system state.
- Added hard send guard: only allowlisted Ready-for-Outreach mailboxes may send (`config/ready_for_outreach_emails.txt`), enforced by `scripts/enforce_ready_senders.py --strict-auth` preflight.
- Phase 1 hardening started: replaced permissive anon RLS policies in Smartlead tracking schemas with service-role-only policies; hardened webhook receiver with token auth, payload-size limits, and per-IP rate limits; repaired Smartlead/ZeroBounce cron entries to use flock fallback (`command -v flock`) instead of hardcoded `/usr/bin/flock`.
- Added guarded campaign control path: `scripts/smartlead_campaign_launch_guard.py` + `scripts/launch_seq_campaigns_guarded.sh` (mandatory ready-sender preflight + explicit execute confirm phrases).

2026-04-24
- Created persistent operating plan for cold outreach stack.
- Added current verified lead counts from latest ZeroBounce run.
- Added full warmup inventory: 24 mailboxes across 8 domains.
- Updated status: none of the warmup mailboxes are ready yet.
- Reordered next step sequence: warmup readiness -> GlockApps gate -> Smartlead import -> pilot.
