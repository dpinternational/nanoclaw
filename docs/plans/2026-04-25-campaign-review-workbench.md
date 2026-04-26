# Campaign Review Workbench (Seq A + Seq B)

Date: 2026-04-25
Source: `insurance-scraper/scripts/smartlead_wire_sequences.py`

## Current structure snapshot

Seq A (new licensees)
- 5 steps, delays: 0 / 2 / 5 / 7 / 10 days
- Word counts by step: 132, 139, 166, 73, 104

Seq B (single-carrier)
- 5 steps, delays: 0 / 3 / 7 / 10 / 14 days
- Word counts by step: 80, 103, 151, 60, 104

## What is good now
- Story-driven copy (not spammy templates)
- Natural plain-text format
- Sequence progression is logical (intro -> problem -> story -> invite -> close)
- CTA intent is conversational (good for replies)

## Main campaign problems to fix
1) Emails 1-3 are too long (especially A1/A2/A3 and B3)
2) Offer is broad ("guide/training/chat") vs one clear core offer
3) Proof claims are large but not tightly framed
4) CTA changes too much from step to step
5) No explicit positive-reply classification trigger (for faster triage)

## Recommended campaign objective
One clear outcome per sequence:
- Primary CTA keyword: `COMPARE`
- Secondary CTA keyword: `LATER`

This gives cleaner reply handling and better attribution.

## Immediate rewrite targets (highest impact)
Priority 1:
- Seq A step 1 -> reduce to ~85-100 words
- Seq B step 1 -> tighten and align to single core offer

Priority 2:
- Seq A step 3 and Seq B step 3 -> shorter case-study format (~90-110 words)

Priority 3:
- Steps 4-5 -> keep short, unify CTA language

## Suggested v2 framework

Seq A (new licensees)
1) Congrats + one mistake to avoid + COMPARE CTA
2) 5-point decision checklist + COMPARE CTA
3) short case study + risk reversal + COMPARE CTA
4) training invite as bonus, not main offer + COMPARE CTA
5) clean close + LATER option

Seq B (single-carrier)
1) benchmark question + COMPARE CTA
2) comp-gap math + conservative framing + COMPARE CTA
3) case study (less hype, more specifics) + COMPARE CTA
4) optional training bonus + COMPARE CTA
5) last note + LATER option

## Guardrail before campaign changes
Use only the guarded path:
- dry-run review path: `scripts/launch_seq_campaigns_guarded.sh launch`
- execute only with explicit confirm phrase and approval.

## Next working session options
A) Rewrite Seq A completely (5 emails)
B) Rewrite Seq B completely (5 emails)
C) Rewrite only top 4 high-impact emails first (A1, A3, B1, B3)
D) Build two A/B variants for first-touch emails only
