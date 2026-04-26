# Telegram Webhook Re-Enable — Deferred Decision
Generated: 2026-04-26

## TL;DR
**DO NOT re-enable Telegram webhook without first fixing the underlying cause of the April 18 outage.** Polling mode is the safer default and is currently working fine.

## Context
- Original audit recommendation: re-enable Telegram webhook to reduce polling latency + CPU
- Source: src/channels/telegram.ts line 80 has WEBHOOK MODE DISABLED with hardcoded early return
- Reason in code comment: "polling-only since Apr 18 2026 RCA. Self-signed + raw-IP webhooks silently decayed on Telegram's side causing 28.5h of blind ingest. See docs/webhook-plan-v2.md"

## Why "just flip the flag" is WRONG
The audit's framing was: "code already exists, just flip a flag." That's misleading. The flag was disabled BECAUSE the underlying setup was broken. Re-enabling without fixing the root cause re-creates a 28.5-hour blind-ingest incident.

Specific blockers:
1. **Self-signed cert** — Telegram silently stopped honoring it. Need real TLS (Let's Encrypt or paid cert).
2. **Raw IP domain** — WEBHOOK_DOMAIN=89.167.109.12:8443. Telegram prefers FQDN with valid cert.
3. **Port 8443** — open + exposed but undocumented. Possibly behind firewall.
4. **No webhook health probe** — no synthetic "did Telegram actually deliver an update in the last 10 min?" check.

## What's needed BEFORE re-enable
- [ ] Acquire FQDN pointing at server (e.g. tg-webhook.thepricegroupimo.com or sslip subdomain)
- [ ] Issue Let's Encrypt cert via Caddy/certbot
- [ ] Update WEBHOOK_DOMAIN to FQDN
- [ ] Remove early-return at telegram.ts:80
- [ ] Add webhook-liveness synthetic probe (analogous to oauth-synthetic-probe.py)
- [ ] Stage in maintenance window with rollback plan
- [ ] Run for 24 hours in dual-mode (webhook + polling fallback enabled) before declaring healthy
- [ ] If incident recurs, hardcoded disable is the proven recovery

## Polling-mode performance reality check
Current polling mode is fine:
- ~230 MB RSS, 28 min CPU over 1 week
- Telegram message latency: ~1-3 seconds (acceptable)
- No outages since Apr 18

The audit's "kills polling latency + cuts CPU" claim was theoretical, not measured.

## Recommendation
LEAVE THIS AS-IS until either:
- A real performance problem appears (latency >10s, CPU >50%)
- Or the FQDN+cert prerequisites are independently set up for other reasons (e.g. inbound webhook for some other integration)

If prerequisites get done, then re-enable becomes a 30-min task. Until then, it's a multi-day project with real outage risk.

## Verdict
DEFERRED — moved off the urgent-improvement list. Ticket closed as "won't do without prerequisite work."
