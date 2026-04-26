# NanoClaw Container OOM-137 — Fix Staged
Generated: 2026-04-26

## Diagnosis
Symptom: Containers exit with code 137 (SIGKILL) AFTER emitting `type=result` successfully. Multiple times per day. Logs noisy. Sessions appear successful (work completes) but watchdog/cursor state can still drift.

Root cause:
- `src/config.ts` line 80: `IDLE_TIMEOUT = parseInt(process.env.IDLE_TIMEOUT || '1800000', 10)` — defaults to 30 min
- After agent emits `type=result`, container stays alive 30 min waiting for follow-up streams
- Hard timeout fires → docker stop SIGTERM (15s grace) → docker SIGKILL → exit 137
- Code does correctly handle this case (resolves with `status: 'success'`, preserves session) — only cosmetic noise + slow shutdown

## Fix Applied (env-only, no code change)
Server `/home/david/nanoclaw/.env` now has:
```
IDLE_TIMEOUT=60000
```

This makes containers shut down 60 seconds after success instead of 30 minutes. Zero code change. Reverts to 30 min if env var removed.

## Activation
**The new value will NOT take effect until nanoclaw service restarts.** Per project rule "don't restart nanoclaw without David's OK," the change is staged. When the service eventually restarts (planned maintenance, server reboot, deploy of unrelated change, etc.), the fix activates automatically.

To activate immediately when ready:
```bash
ssh root@89.167.109.12 'systemctl restart nanoclaw'
```

To verify after restart:
```bash
ssh root@89.167.109.12 'journalctl -u nanoclaw --since "1 hour ago" | grep -c "code: 137"'
# Expect: dramatic reduction (was multiple per hour, should be 0 or near-0)
```

## Rollback
```bash
ssh root@89.167.109.12 'sed -i "/^IDLE_TIMEOUT=/d" /home/david/nanoclaw/.env'
ssh root@89.167.109.12 'systemctl restart nanoclaw'
```

## Why Not Code-Path Fix
Original audit suggested editing src/container-runner.ts to detect `type=result` and shrink the timeout dynamically. That requires:
- TS code edit
- npm run build
- Push compiled dist/ to server
- Restart nanoclaw

Repo state was dirty during the audit; touching core files = unacceptable risk. Env-var approach achieves the same effect with zero code risk.

## Verdict
✅ STAGED — fix is in place, awaits next service restart to activate. No urgency given the issue is cosmetic (work succeeds, sessions persist).

When you next restart nanoclaw for any reason, expect the 137 spam to drop to near-zero immediately.
