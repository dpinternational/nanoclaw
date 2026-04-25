# Cold Outreach Scale Plan (Data-Driven, Pivot-Ready)

Owner: David Price
Date: 2026-04-25
Scope: Insurance DB scraping -> verification -> Smartlead delivery -> reply handling -> hiring attribution
Constraint: No outbound sends without explicit David approval.

--------------------------------------------------
## 0) Current Ground Truth (verified today)

Infrastructure/data
- Verified sendable leads on disk: 11,149
  - Seq A CSV: 9,066 rows
  - Seq B CSV: 2,083 rows
  - Source files:
    - /Users/davidprice/nanoclaw/insurance-scraper/out/seq_a_new_licensees.csv
    - /Users/davidprice/nanoclaw/insurance-scraper/out/seq_b_single_carrier.csv
- Latest verification log:
  - /Users/davidprice/nanoclaw/insurance-scraper/out/verify_run_20260424_135522.log

Smartlead
- API reachable and writable.
- Mailboxes connected: 24/24
- SMTP healthy: 24/24
- IMAP healthy: 24/24
- Campaigns currently live: 0 (at snapshot time)
- Current account-level webhook (latest):
  - id: 561973
  - name: tpg-recruiting-campaign-replied-bounced-v1
  - url: https://89.167.109.12.sslip.io/smartlead/webhook
  - events: EMAIL_REPLY, EMAIL_BOUNCED, LEAD_CATEGORY_UPDATED

Execution status (2026-04-25 live build)
- Production webhook receiver deployed on Hetzner as systemd service:
  - service: smartlead-webhook-receiver
  - health: https://89.167.109.12.sslip.io/health
  - ingest path: /smartlead/webhook
  - raw event sink: /home/david/insurance-scraper/state/smartlead_webhook_events.jsonl
  - receiver log: /home/david/insurance-scraper/logs/smartlead_webhook_receiver.log
- Caddy reverse proxy + TLS enabled for 89.167.109.12.sslip.io.
- Pilot campaigns remain PAUSED and populated:
  - Seq A campaign_id: 3232436 (25 leads imported)
  - Seq B campaign_id: 3232437 (25 leads imported)
  - campaign-level webhooks:
    - 561971 (Seq A)
    - 561972 (Seq B)
- Sequence wiring completed (5 steps each):
  - Script: /home/david/insurance-scraper/scripts/smartlead_wire_sequences.py
  - Seq A: days 0/2/5/7/10
  - Seq B: days 0/3/7/10/14
- Daily scorecard SQL pack created:
  - /home/david/insurance-scraper/sql/smartlead_daily_scorecards.sql
- Live webhook receipt confirmed from Smartlead (LEAD_UNSUBSCRIBED test events) into receiver JSONL.
- Supabase webhook table applied and live:
  - table: public.smartlead_webhook_events
  - schema source: /home/david/insurance-scraper/sql/smartlead_webhook_events_schema.sql
  - ingestion verified: receiver writes test event(s) into Supabase successfully (supabase=true).

--------------------------------------------------
## 1) North-Star and Decision Framework

North-star outcomes (business)
1) Qualified agent conversations booked
2) Contracted agents sourced from cold outbound
3) Cost per contracted agent

Operational leading indicators (daily)
1) Deliverability health: bounce, complaint, inbox placement proxy
2) Engagement quality: reply rate, positive reply rate
3) Funnel velocity: reply -> meeting -> contract conversion and time-to-stage

Decision principle
- Scale only when deliverability is stable and conversion efficiency is not degrading.
- Hold/repair immediately on deliverability breach.
- Pivot messaging/targeting when engagement underperforms with healthy deliverability.

--------------------------------------------------
## 2) Measurement Architecture (single source of truth)

Build one canonical reporting layer (Supabase tables or existing analytics DB) with these entities:

A) leads_master
- lead_id (stable)
- email
- source_segment (new_licensee | single_carrier)
- state
- carrier
- verified_status (valid/catch-all/etc)
- verification_timestamp

B) outreach_events
- event_id
- timestamp_utc
- campaign_id
- mailbox_email
- lead_id/email
- event_type (sent, opened, clicked, replied, bounced, unsubscribed, category_updated)
- raw_payload_json

C) reply_outcomes
- lead_id
- first_reply_at
- reply_sentiment (positive/neutral/negative)
- intent_bucket (interested/meeting_request/info_request/not_interested/wrong_person/ooo/dnc)
- owner (David/Gina/VA)
- sla_minutes_to_first_human_response

D) pipeline_attribution
- lead_id
- meeting_booked_at
- application_started_at
- contracted_at
- first_year_commission_if_available
- attributed_campaign
- attributed_mailbox

E) experiment_registry
- experiment_id
- hypothesis
- variant_a / variant_b
- start_date / end_date
- primary_metric
- minimum_sample_size
- decision (ship/iterate/kill)

Required join keys
- Prefer Smartlead lead/campaign IDs + normalized email fallback.
- Keep raw payload immutable for audit/debug.

--------------------------------------------------
## 3) KPI Stack + Thresholds

Tier 1: Deliverability guardrails (hard gates)
- Bounce rate (7-day):
  - Green <= 2.0%
  - Yellow 2.0-3.0%
  - Red > 3.0% (pause affected mailbox/domain)
- Spam complaints:
  - Green = 0
  - Red >= 1 complaint on any mailbox/day (pause + investigate)
- Unsubscribe rate:
  - Green < 1.0%
  - Yellow 1.0-1.5%
  - Red > 1.5%

Tier 2: Engagement quality
- Reply rate by campaign cohort:
  - Green >= 2.0%
  - Yellow 1.2-1.99%
  - Red < 1.2%
- Positive reply rate (interested + meeting_request + info_request) / delivered:
  - Green >= 0.7%
  - Yellow 0.4-0.69%
  - Red < 0.4%

Tier 3: Business conversion
- Reply -> meeting conversion:
  - Green >= 20%
  - Yellow 12-19%
  - Red < 12%
- Meeting -> contract conversion (rolling 30-day):
  - target based on historical baseline once enough volume exists

--------------------------------------------------
## 4) Pivot Rules (exact triggers)

Deliverability pivot (immediate)
Trigger any of:
- Bounce > 3% on mailbox/domain (rolling 3-day)
- Any complaint event
- Sudden deliverability drop: reply rate down >40% week-over-week with stable lead quality
Actions:
1) Pause only affected mailbox/domain (not full system).
2) Remove catch-all leads from that segment temporarily.
3) Reduce per-mailbox cap by 30-50% for 3 days.
4) Run seed test (GlockApps/manual) and DNS/auth audit.
5) Resume only after 2 consecutive green days.

Offer/message pivot
Trigger:
- Reply rate <1.2% after minimum 1,000 delivered in a segment with green deliverability
Actions:
1) Keep same targeting, test new subject + first-line angle.
2) Keep body mostly stable; change one variable at a time.
3) Run A/B until minimum sample met; ship only if uplift >=15% relative.

Targeting pivot
Trigger:
- Positive reply rate <0.4% after 1,500 delivered in segment and 2 message iterations
Actions:
1) Re-slice segment (state, appointment profile, recency).
2) Start with highest-response micro-segment.
3) Suppress low-performing states/carriers for next cycle.

Scale pivot (up/down)
- Scale up +25% weekly if all are true for prior 7 days:
  - bounce <=2%, complaints=0, unsubscribe <1%, reply >=2%
- Hold if any yellow threshold
- Scale down -30% if any red threshold

--------------------------------------------------
## 5) Execution Plan (next 14 days)

Phase A: Instrumentation and readiness (Day 0-2)
1) Lock event capture
- Keep webhook 561927 active.
- Replace webhook.site with production receiver endpoint when ready.
- Persist raw webhook payloads to outreach_events.

2) Build scorecards
- Daily mailbox scorecard (health + bounce + reply + unsub + complaint)
- Daily campaign scorecard (delivered, reply, positive reply)
- Weekly segment scorecard (new_licensee vs single_carrier)

3) Attribution wiring
- Define contract attribution rule: last meaningful touch OR first reply touch.
- Enforce one lead_id/email identity map.

Phase B: Controlled pilot (Day 3-6)
1) Create two campaigns in Smartlead (Seq A, Seq B)
2) Import small pilot lists (25 + 25)
3) Set conservative per-mailbox caps
4) Monitor every 12 hours
5) No scale until 72h green

Phase C: First ramp (Day 7-10)
1) If pilot green, expand to 200-300 delivered/day total
2) Keep mailbox distribution balanced
3) Start first structured A/B test:
- variable: subject line only
- metric: reply rate
- holdout: 50/50

Phase D: Optimization cadence (Day 11-14)
1) Analyze by segment/state/carrier
2) Kill bottom quartile states or offers for next cycle
3) Double down on top quartile by +25% volume
4) Publish weekly decision memo: what changed, why, and result

--------------------------------------------------
## 6) Daily/Weekly Operating Rhythm

Daily (Mon-Fri)
1) Check red flags (bounce/complaint/unsub)
2) Review yesterday reply quality and SLA-to-human-response
3) Review mailbox-level outliers
4) Decide: scale / hold / reduce
5) Log decisions in experiment_registry or ops log

Weekly
1) Refresh newly scraped + verified leads
2) Run one experiment at a time per segment
3) Review segment-level economics (cost per positive reply, cost per meeting)
4) Reallocate volume toward best-performing segments

Monthly
1) Deliverability quality review per domain/mailbox
2) Sunset weak domains/mailboxes
3) Update thresholds from actual observed baselines

--------------------------------------------------
## 7) Dashboard Spec (minimum viable)

Dashboard 1: Executive (daily)
- Delivered, bounce, replies, positive replies, meetings, contracts
- Cost per positive reply, cost per meeting, cost per contract

Dashboard 2: Deliverability Ops
- Bounce/unsub/complaint by mailbox and domain
- 7-day trend and alerting

Dashboard 3: Funnel Conversion
- Sent -> delivered -> reply -> positive -> meeting -> contract
- By segment/state/carrier

Dashboard 4: Experiment Tracker
- Active tests, sample progress, confidence/de-risked recommendation

--------------------------------------------------
## 8) Alerts (must-have)

Immediate alerts to Telegram ops channel for:
- complaint >=1
- bounce >3% for any mailbox in last 24h
- webhook ingest failure for >15 minutes
- reply SLA breach (>60 minutes for positive intent)

Digest alerts (daily)
- top 5 positive replies
- bottom 5 mailbox/domain risk scores
- scale recommendation for next day

--------------------------------------------------
## 9) Specific next actions to execute now

1) Webhook validation
- Confirm webhook 561927 receives live Smartlead events after campaign activity begins.

2) Data plumbing
- Implement/verify webhook receiver -> outreach_events table.
- Ensure event dedupe by event_id or hash.

3) Campaign scaffolding
- Create Seq A + Seq B campaigns in Smartlead (draft state).
- Import pilot cohorts only (no send yet until explicit approval).

4) Scorecard build
- Stand up daily SQL/report templates for KPI stack and thresholds.

5) Go/no-go meeting
- Review pilot config + alerting + attribution before first send approval.

--------------------------------------------------
## 10) Non-negotiables

1) No sends without explicit David approval.
2) One-change-at-a-time in experiments.
3) If deliverability red, fix before growth.
4) Keep CR operations and cold outreach operations fully separate.
5) Every scale decision must reference measured data, not intuition.
