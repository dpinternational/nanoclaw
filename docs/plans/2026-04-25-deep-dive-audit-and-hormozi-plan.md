# Deep Dive Audit + Hormozi Upgrade Plan (Cold Outreach)

Date: 2026-04-25
Owner: David Price
Scope: insurance-scraper + cold email operating plan + sequence strategy

## Executive verdict
Infrastructure progress is real, but there are critical trust/safety gaps that can invalidate data and launch decisions.
Commercially, outbound is technically prepared to send, but not yet optimized to win.

Top priorities:
1) Lock security and data integrity
2) Make send gating non-bypassable
3) Tighten list quality for pilot
4) Upgrade offer/proof/CTA architecture (Hormozi style)

## What is working
- Ready-sender guard exists (`scripts/enforce_ready_senders.py`)
- Smartlead sync and telemetry schema exist
- Webhook ingestion has dedupe hash pattern
- Verification/export pipeline is operational
- Plan and stage-gate structure is largely sound

## Critical issues (fix before any send)
1) Supabase policy risk: schemas include permissive anon ALL policies
   - `sql/smartlead_tracking_schema.sql`
   - `sql/smartlead_webhook_events_schema.sql`
2) Webhook receiver accepts unauthenticated POSTs (spoofable event stream)
   - `scripts/smartlead_webhook_receiver.py`
3) Send guard is manual-only (documented preflight, not hard-enforced in launch path)
4) Warmup/readiness instrumentation is weak (manual/UI-driven; not canonical in pipeline)
5) Automation reliability issue observed: flock path mismatch in cron/log context

## High issues
- Smartlead API key appears in query-string request style (leak-prone in logs/proxies)
- Catch-all inclusion is too high for early-phase reputation control
- Plan/doc drift: conflicting status docs increase operator error
- Hardcoded IDs/paths reduce portability and increase misfire risk

## Marketing/growth diagnosis
Current engine is “safe-to-send” but not yet “high-conversion.”

Main gaps:
- Segmentation too broad (new licensees/single-carrier only)
- Offer is informational, not transformational
- Proof density too low vs claim intensity
- CTA too soft and ambiguous
- Variant testing architecture under-implemented

## Hormozi-style upgrade (what to ship)

## New core offer
"24-hour Agent Earnings Gap Audit"

Deliverables:
1) Personalized comp benchmark
2) Contract red-flag scan (vesting/portability/lock-in)
3) Lead-cost leakage calculator
4) 90-day production ramp blueprint
5) Training + mentor Q&A invite

## Risk reversal
"If your setup already benchmarks top-tier, we’ll tell you and show your best-fit path even if it’s not us."

## CTA
Primary: "Reply COMPARE"
Secondary: "Reply LATER"

## 14-day priority roadmap

### Days 1-3 (hardening)
- Remove permissive anon RLS policies; least privilege only
- Add webhook auth (HMAC/shared secret) + request size/rate limits
- Wire ready-sender preflight into all launch/unpause scripts (hard block)
- Fix cron lock binary path and verify heartbeat

### Days 4-7 (list quality + enforcement)
- Pilot on valid-only (exclude catch-all initially)
- Add suppression/compliance table enforcement pre-import
- Add canonical readiness registry with timestamp/source-of-truth
- Remove hardcoded campaign IDs and env-specific paths

### Days 8-14 (conversion lift)
- Rewrite first-touch emails to tighter 70-110 words
- Deploy upgraded value stack and proof blocks
- Run controlled A/B tests (subject + CTA + offer asset)
- Use delivered-based KPI tree only (opens diagnostic, not decision metric)

## KPI tree (decision metrics)
North Star: contracted agents from cold outreach

Primary funnel:
- Delivered
- Reply rate (delivered basis)
- Positive reply rate
- Meeting booked rate
- Contract conversion rate

Guardrails:
- Bounce rate
- Complaint rate
- Unsubscribe rate
- Mailbox/domain health

## Launch gate (must all be true)
- Security controls fixed (RLS + webhook auth)
- Ready-sender preflight integrated as hard dependency
- Pilot list = valid-only
- Suppression/compliance checks active
- Telemetry health verified for previous 24h

## Notes
This plan synthesizes independent technical audit + independent second-opinion review + strategic marketing review.
