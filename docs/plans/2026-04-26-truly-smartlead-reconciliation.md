# TrulyInbox / Smartlead Sender Reconciliation
Generated: 2026-04-26

## Summary
All 24 Smartlead mailboxes exist in TrulyInbox (no orphans). All 5 allowlist mailboxes are present and healthy in both systems. Both pilot campaigns (Seq A, Seq B) are wired to the same 4 senders, all of which are warming.

## Smartlead pilot campaign senders (8 attachments)
Each campaign uses these 4 mailboxes (TrulyInbox status in parens):
- david@growtpg.com (warming)
- david@davidpriceinsurance.com (warming)
- david@davidpricetpg.com (warming)
- david@tpgagents.com (warming)

## Allowlist (config/ready_for_outreach_emails.txt)
All 5 allowlist mailboxes pass enforce_ready_senders.py --strict-auth.
- david@davidpricetpg.com — SL ✓ TI ✓ (warming)
- david@davidpriceinsurance.com — SL ✓ TI ✓ (warming)
- david@growtpg.com — SL ✓ TI ✓ (warming)
- david@tpgagents.com — SL ✓ TI ✓ (warming)
- david@tpgopportunity.com — SL ✓ TI ✓ (warming)

⚠️ david@tpgopportunity.com is on the allowlist but NOT attached to either pilot campaign. This is fine if intentional (reserve for future), but worth noting.

## ⚠️ TrulyInbox-error Mailboxes Connected at Smartlead Account-Level
These 3 mailboxes are connected (smtp/imap healthy) at the Smartlead account level but show "error" in TrulyInbox warmup, meaning warmup is not running:

- david@tpgagentteam.com — TrulyInbox: error
- david@pricerecruits.com — TrulyInbox: error
- david@insurancecareerpath.com — TrulyInbox: error

**They are NOT attached to any current campaign — no sending risk now.**

Action recommendation:
- Investigate why TrulyInbox is "error" on these 3 (re-auth in TrulyInbox dashboard)
- OR remove them from Smartlead if not planned for future use
- OR leave them disconnected from campaigns (current state — no risk)

## Other healthy mailboxes connected at Smartlead but not in pilots
19 mailboxes in total are connected at Smartlead. The "extra" 19 (24 - 5 allowlist) are warmup-only or future-use and are NOT in any active campaign. enforce_ready_senders.py policy passes because policy is "never SEND from non-ready" — connected != sending.

## Per-Account Pattern
You have 8 domains × ~3 mailboxes per domain (david@, davidprice@, david.price@) = ~24 total. The pilot uses ONLY the david@ variant on the 4 chosen domains. This is a healthy reserve pattern — gives room to add senders later without re-warming.

## Verdict
✅ Pilot is correctly wired. All senders healthy.
✅ Allowlist policy enforced.
⚠️ 3 TrulyInbox-error mailboxes need re-auth or removal (not currently risky, but represents wasted Smartlead seat capacity).
ℹ️ david@tpgopportunity.com on allowlist is unused by any campaign (intentional reserve OK).

## Useful commands
```bash
# Re-run enforcement check
ssh root@89.167.109.12 'sudo -u david /usr/bin/python3 /home/david/insurance-scraper/scripts/enforce_ready_senders.py --strict-auth'

# View live Smartlead mailbox + TrulyInbox cross-reference
python3 - <<EOF
# (see prior reconciliation script)
EOF
```
