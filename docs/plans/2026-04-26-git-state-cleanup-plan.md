# Git State Cleanup Plan — 2026-04-26

Read-only inventory of NanoClaw repo state across local Mac and production server.
**No commits, pushes, deletes, or rebuilds were performed.**

---

## 1. Branch + Commit Divergence Summary

| Side   | Path                          | Branch                                     | HEAD     |
|--------|-------------------------------|--------------------------------------------|----------|
| LOCAL  | /Users/davidprice/nanoclaw    | chore/cold-outreach-webhook-scorecards     | 3f7e010  |
| SERVER | /home/david/nanoclaw          | main                                       | 91f17a1  |
| origin/main (GitHub dpinternational/nanoclaw) |                          | b2a81aa  |

Local is 1 commit ahead of origin/main:
  3f7e010  chore: add cold outreach webhook + scorecard ops artifacts

Server is 0 commits ahead of origin/main (HEAD == origin/main on server).

Local is 30+ commits ahead of server because the server has NOT been fast-forwarded
to current origin/main. Server's HEAD (91f17a1 / b2a81aa per origin) sits well behind
local's branch lineage. Recent commits between server HEAD and local HEAD include:

  3f7e010  chore: add cold outreach webhook + scorecard ops artifacts (LOCAL ONLY)
  b2a81aa  feat(email): Brain Dump -> Notion email promotion bridge   (=server HEAD =origin/main)
  e6752e0  fix(telegram): polling-only mode + liveness heartbeat
  44cca90  test: add 120 tests for 5 previously untested modules
  f1520a6  perf: convert hot-path sync filesystem ops to async
  f4bc0ac  fix: memory leaks, cursor race condition, collection bounds
  5006161  security: isolate credential mounts
  4ef336b  chore: remove dead code
  9559b78  refactor: code quality improvements
  38a80a0  security: fix container escape
  ae9df4a  feat: Digital Clone, Content Machine
  88e46cd  feat: Phase 1.1 Database Optimization
  ...

NOTE: Local origin/main and server origin/main both = b2a81aa. So divergence is:
  - Local branch  = origin/main + 1 (3f7e010)
  - Server main   = origin/main + 0 (clean wrt commits)
  - Server has a LARGE pile of uncommitted working-tree changes (see §3a/§3b/§5).

## 2. Common Ancestor

  git merge-base 3f7e010 91f17a1  =>  91f17a11b265b94c9fefe83209887a5915c24536

i.e. server HEAD IS an ancestor of local HEAD. The single divergent commit is 3f7e010.
Server's working tree has drifted but its committed history is a clean prefix of local.

---

## 3. Dirty-Path Categorization

Untouchable (never touch on either side, regardless of bucket):
  .env, .env.*, store/messages.db, nanoclaw.db, groups/**/messages.db, certs/

### 3a. PROD-CRITICAL (server-only, cron-driven; must preserve)

Confirmed via `crontab -u david -l` on 89.167.109.12. These run from server working tree
and are NOT yet committed to origin/main. Any "cleanup" that discards them breaks prod.

  scripts/braindump-promote.py             cron */2 * * * *  (Brain Dump -> Notion bridge)
  scripts/email-approval-bot.py            cron 30 10, 0 15 Mon-Fri (morning + safety)
  scripts/email-candidate-miner.py         cron 0 14 * * 5 (Friday miner)
  scripts/system-health-check.py           cron */30 + 0 12 (checks + heartbeat)
  scripts/tpg-uncaged-morning-report.py    cron 45 2 * * *
  scripts/inbox-brief/  (brief.py, watcher.py)  cron 0 3, 0 13, * * * * *
  scripts/cr-full-archive.cjs              cron 0 10 * * *
  scripts/gina-production-sync.py          cron 0 9 * * 1
  scripts/target-carrier-alert.py          cron 0 1,7,13,19 * * *
  scripts/email-digest-server.py           cron 0 11 * * *
  scripts/tpg-daily-digest-server.py       cron 0 7 * * *

Local-copy presence check (does local already have these?):
  braindump-promote.py        LOCAL HAS
  cr-full-archive.cjs         LOCAL HAS
  gina-production-sync.py     LOCAL HAS  (untracked locally too)
  target-carrier-alert.py     LOCAL HAS  (untracked locally too)
  email-digest-server.py      LOCAL HAS  (untracked locally too)
  tpg-daily-digest-server.py  LOCAL HAS  (untracked locally too)
  inbox-brief/                LOCAL HAS  (untracked locally)
  email-approval-bot.py       LOCAL MISSING <- SERVER-ONLY, PROD CRITICAL
  email-candidate-miner.py    LOCAL MISSING <- SERVER-ONLY, PROD CRITICAL
  system-health-check.py      LOCAL MISSING <- SERVER-ONLY, PROD CRITICAL
  tpg-uncaged-morning-report.py LOCAL MISSING <- SERVER-ONLY, PROD CRITICAL

Also referenced in cron from /home/david/insurance-scraper (separate repo dir, not
nanoclaw working tree — not in this inventory):
  scripts/zerobounce_auto_verify.py, smartlead_sync.py, glockapps_sync.py,
  smartlead_reply_router.py

Server-side additionally untracked (likely prod-supporting, not in cron but adjacent):
  scripts/email-drafter-v2.py            (paired .bak files exist)
  scripts/email-performance-tracker.py
  scripts/email_validator.py
  scripts/build_carousel_packet.py
  scripts/check-email.py
  scripts/whisper-transcribe.py          (LOCAL HAS — likely safe)
  scripts/uncaged-recovery/              (LOCAL HAS)
  scripts/youtube-scraper.py
  scripts/tpg-daily-digest-hermes.py

Total PROD-CRITICAL files identified: 11 cron-referenced + ~9 adjacent helpers = ~20.

### 3b. SOURCE-CHANGES (real edits worth committing)

LOCAL modified (tracked):
  M  groups/telegram_braindump/CLAUDE.md     (memory; usually committed)
  M  insurance-scraper/scraper.py            (~196 line diff; large)
  M  insurance-scraper/scripts/smartlead_wire_sequences.py
  M  insurance-scraper/sql/smartlead_webhook_events_schema.sql
  M  scripts/youtube-monitor.py              (~158 line diff)
  M  src/channels/telegram.ts                (~5 line diff, small)
  M  src/group-queue.test.ts                 (~3 line diff)
  M  src/index.ts                            (~10 line diff — CONFLICT, see §6)
  M  src/ipc.ts                              (~16 line diff — CONFLICT, see §6)
  M  src/routing.test.ts                     (~40 line diff — possibly same as server)
  M  src/sales-celebration.test.ts           (~42 line diff)
  M  src/sales-celebration.ts                (~17 line diff)

LOCAL untracked source-y (real new artifacts):
  ENTERPRISE_SECURITY_README.md
  INTEGRATION_DEPLOYMENT_PLAN.md
  docs/COLD_EMAIL_LAUNCH_PLAN.md
  docs/PHASE_0_INVENTORY.md
  docs/SERVER-MIGRATION.md
  docs/plans/2026-04-24-cold-outreach-operating-plan.md
  docs/plans/2026-04-25-campaign-review-workbench.md
  docs/plans/2026-04-25-deep-dive-audit-and-hormozi-plan.md
  container/scripts/                        (new agent scripts)
  container/skills/calendar-tool.md
  container/skills/recruitment-pipeline.md
  src/channels/google-calendar.ts
  src/cr-monitor.ts
  src/email-generator.ts
  src/recruitment-db.ts
  scripts/cr-email-pull.ts
  scripts/cr-monitor-standalone.ts
  scripts/daily-email-mock.ts
  scripts/email-mock-standalone.ts
  scripts/generate-email.ts
  scripts/generate-email-day.ts
  scripts/manager-scorecard.py
  scripts/manager-scorecard-gina.py
  scripts/agent-ltv-model.py
  scripts/ltv-complete.py
  scripts/ltv-deep-analysis.py
  scripts/lookup-agents.py
  scripts/parse-daily-production.py
  scripts/parse-recruitment-sheets.cjs
  scripts/populate-ob-tracker.py
  scripts/oauth-synthetic-probe.py
  scripts/health-check.sh
  scripts/add-calendar-scope.cjs
  scripts/add-sheets-scope.cjs
  scripts/gmail-campaign-archive.cjs
  scripts/cr-archive-builder.js
  insurance-scraper/* (tracked dir, many new files; see §3d)

SERVER modified (tracked) — committed-worthy if delta is meaningful:
  M  groups/global/CLAUDE.md              (memory)
  M  groups/main/CLAUDE.md                (memory)
  M  package.json                          REVIEW (deps drift?)
  M  package-lock.json                     REVIEW
  M  src/channels/index.ts                 (~8 line diff)
  M  src/config.ts                         (~27 line diff)
  M  src/container-runner.ts               (~67 line diff)
  M  src/group-queue.ts                    (~15 line diff)
  M  src/index.ts                          (~87 line diff — CONFLICT)
  M  src/ipc.ts                            (~55 line diff — CONFLICT)
  M  src/routing.test.ts                   (~40 line diff — possibly same as local)
  M  src/task-scheduler.ts                 (~48 line diff)

SERVER untracked source-y new files (not on local):
  src/audit-compliance.cjs
  src/backup-recovery.cjs
  src/channels/discord.ts        + discord.test.ts
  src/channels/enhanced-gmail.ts
  src/channels/gmail.ts          + gmail.test.ts
  src/channels/telegram.ts (untracked dup? — conflict if different)
  src/channels/telegram.test.ts
  src/channels/google-calendar.ts (also new on local!)
  src/db-integration-update.ts
  src/db-optimized.ts
  src/discord-email-router.ts
  src/email-classifier.ts
  src/email-escalation-system.ts
  src/email-pattern-engine.ts
  src/enhanced-sales-detection.cjs (+ .js)
  src/enterprise-security-suite.cjs
  src/group-database-manager.cjs (+ .js)
  src/inbox-zero-automation.ts
  src/intrusion-detection.cjs
  src/monitoring/
  src/recruitment-db.ts          (also new on local — likely SAME)
  src/sales-celebration.ts       (also tracked-modified on local)
  src/sales-celebration.test.ts  (also tracked-modified on local)
  src/security-system.cjs
  src/security-test-demo.cjs
  src/telegram-api.ts
  src/webhook-server.ts
  scripts/migrate-database-optimizations.js
  scripts/test-database-performance.js
  scripts/setup-webhook.sh, validate-webhook.cjs, benchmark-webhook.cjs
  backfill-sales.cjs

### 3c. JUNK (safe to discard)

Pattern-based count rather than enumeration:

LOCAL junk (untracked):
  .claude/scheduled_tasks.lock
  .hermes/
  tmp/
  download.html
  tpg-logo.png
  content-ideas.xlsx
  nanoclaw.db                     <- UNTOUCHABLE, listed as junk pattern but DO NOT DELETE
  backups/*.plist (3), backups/crontab-*.bak, backups/groups-archive-*/
  insurance-scraper/out/, insurance-scraper/snapshots/, insurance-scraper/state/
  insurance-scraper/.env.example, .env.worker.example, .env.worker1, .env.worker2

SERVER junk (untracked) — substantial:
  .env.preserved-1776544012             UNTOUCHABLE-style
  .venv/                                pattern junk (large)
  certs/                                UNTOUCHABLE
  scripts/__pycache__/                  pattern junk
  scripts/*.bak, *.bak-1776530777, *.bak-1776544389  (4 files)
  src/group-queue.ts.bak-1776544389
  src/index.ts.bak-1776544389

Server junk pattern count: ~10 paths (.bak, __pycache__, .venv) — under 50, listed above.
Local junk pattern count: ~12 paths — under 50, listed above.

### 3d. NEEDS-REVIEW

  insurance-scraper/ subtree on local — entire directory is mostly untracked and large:
    Dockerfile, docker-compose.yml, docker-compose.multi.yml, deploy.sh,
    requirements.txt, schema.sql, create-tasks.sql,
    config/, scripts/* (~16 new files — smartlead_*, glockapps_sync, zerobounce_auto_verify,
      enforce_ready_senders, phase1_guard, install_*, uninstall_*, etc.),
    sql/smartlead_tracking_schema.sql, MULTI_WORKER_RUNBOOK.md, email-sequences.md,
    setup-nanoclaw-tasks.sh, verify_emails.py, check_proxy_ips.py
    => Several of these are referenced by SERVER cron (zerobounce_auto_verify,
       smartlead_sync, glockapps_sync, smartlead_reply_router) but server cron points at
       /home/david/insurance-scraper (separate repo), NOT /home/david/nanoclaw/insurance-scraper.
       Need to confirm whether nanoclaw should own this subtree at all, or if it should
       be a sibling repo. HIGH priority review.

  src/channels/google-calendar.ts (new on BOTH sides)   — diff to confirm equivalence
  src/recruitment-db.ts          (new on BOTH sides)
  src/sales-celebration.ts       (M local; untracked server) — divergent histories
  src/sales-celebration.test.ts  (M local; untracked server)
  scripts/youtube-monitor.py     (M local only — large rewrite ~158 lines)
  scripts/manager-scorecard*.py  (untracked both sides) — confirm same content
  scripts/agent-ltv-model.py / ltv-*.py (untracked local; absent server)
  package.json + package-lock.json (server-only mods)   — likely deps for new src files
  groups/telegram_braindump/CLAUDE.md (local M) vs groups/global,main/CLAUDE.md (server M)
    => different group memories on each host; both legitimate.

---

## 4. Files Only on Local (not seen on server)

(Untracked only-on-local; tracked files always exist on both since merge-base.)

  ENTERPRISE_SECURITY_README.md
  INTEGRATION_DEPLOYMENT_PLAN.md
  docs/COLD_EMAIL_LAUNCH_PLAN.md
  docs/PHASE_0_INVENTORY.md
  docs/SERVER-MIGRATION.md
  docs/plans/2026-04-24-cold-outreach-operating-plan.md
  docs/plans/2026-04-25-campaign-review-workbench.md
  docs/plans/2026-04-25-deep-dive-audit-and-hormozi-plan.md
  container/scripts/, container/skills/calendar-tool.md, recruitment-pipeline.md
  src/cr-monitor.ts
  src/email-generator.ts
  scripts/cr-email-pull.ts, cr-monitor-standalone.ts
  scripts/daily-email-mock.ts, email-mock-standalone.ts
  scripts/generate-email.ts, generate-email-day.ts
  scripts/agent-ltv-model.py, ltv-complete.py, ltv-deep-analysis.py
  scripts/lookup-agents.py, manager-scorecard.py, manager-scorecard-gina.py
  scripts/oauth-synthetic-probe.py, parse-daily-production.py
  scripts/parse-recruitment-sheets.cjs, populate-ob-tracker.py
  scripts/health-check.sh, add-calendar-scope.cjs, add-sheets-scope.cjs
  scripts/gmail-campaign-archive.cjs, cr-archive-builder.js
  insurance-scraper/** (entire subtree, see §3d)
  download.html, tpg-logo.png, content-ideas.xlsx, tmp/

## 5. Files Only on Server (not on local)

PROD-CRITICAL (cron-driven), local-missing — must port back to local before any reset:
  scripts/email-approval-bot.py
  scripts/email-candidate-miner.py
  scripts/system-health-check.py
  scripts/tpg-uncaged-morning-report.py

Other server-only source/scripts:
  scripts/email-drafter-v2.py (+ .bak)
  scripts/email-performance-tracker.py
  scripts/email_validator.py
  scripts/build_carousel_packet.py
  scripts/check-email.py
  scripts/youtube-scraper.py
  scripts/tpg-daily-digest-hermes.py
  scripts/fetch-remaining-subs.py
  scripts/cr-archive-builder.cjs   (note: local has .js variant)
  scripts/setup-webhook.sh, validate-webhook.cjs, benchmark-webhook.cjs
  scripts/migrate-database-optimizations.js, test-database-performance.js
  src/audit-compliance.cjs, backup-recovery.cjs
  src/channels/discord.ts (+ test), enhanced-gmail.ts, gmail.ts (+ test),
    telegram.test.ts
  src/db-integration-update.ts, db-optimized.ts
  src/discord-email-router.ts
  src/email-classifier.ts, email-escalation-system.ts, email-pattern-engine.ts
  src/enhanced-sales-detection.cjs/.js
  src/enterprise-security-suite.cjs
  src/group-database-manager.cjs/.js
  src/inbox-zero-automation.ts
  src/intrusion-detection.cjs
  src/monitoring/
  src/security-system.cjs, security-test-demo.cjs
  src/telegram-api.ts, webhook-server.ts
  backfill-sales.cjs

## 6. Files Modified Differently on Each Side (true conflicts)

| File                  | Local diff lines | Server diff lines | Risk |
|-----------------------|------------------|-------------------|------|
| src/index.ts          | 28 (~10 +/-)     | 195 (~87 +/-)     | HIGH — server has substantially more change |
| src/ipc.ts            | 43 (~16 +/-)     | 73  (~55 +/-)     | HIGH |
| src/routing.test.ts   | 58 (~40 +/-)     | 58  (~40 +/-)     | LIKELY-SAME (identical line counts) — verify with diff hash |

Modified on local only:
  groups/telegram_braindump/CLAUDE.md, insurance-scraper/scraper.py,
  insurance-scraper/scripts/smartlead_wire_sequences.py,
  insurance-scraper/sql/smartlead_webhook_events_schema.sql,
  scripts/youtube-monitor.py, src/channels/telegram.ts,
  src/group-queue.test.ts, src/sales-celebration.ts, src/sales-celebration.test.ts

Modified on server only:
  groups/global/CLAUDE.md, groups/main/CLAUDE.md,
  package.json, package-lock.json,
  src/channels/index.ts, src/config.ts, src/container-runner.ts,
  src/group-queue.ts, src/task-scheduler.ts

---

## 7. Top 10 Largest Dirty Files (local)

  63729  tpg-logo.png
  51483  insurance-scraper/scraper.py
  29774  ENTERPRISE_SECURITY_README.md
  29215  src/channels/telegram.ts
  28563  content-ideas.xlsx
  23374  src/index.ts
  20928  scripts/agent-ltv-model.py
  20491  src/cr-monitor.ts
  18919  scripts/parse-recruitment-sheets.cjs
  17665  INTEGRATION_DEPLOYMENT_PLAN.md

---

## 8. Recommended Phase 2 Commit Strategy

Goal: get a clean, push-safe local branch without losing prod-critical server scripts.

Order of operations (LOCAL only — server stays read-only until final sync):

Step 1 — RESCUE prod-critical server-only scripts to local FIRST.
  scp from server to local (read-only on server side):
    scripts/email-approval-bot.py
    scripts/email-candidate-miner.py
    scripts/system-health-check.py
    scripts/tpg-uncaged-morning-report.py
  Place in /Users/davidprice/nanoclaw/scripts/. Do NOT commit yet — review for secrets.
  Commit: "feat(ops): port server-only cron scripts to repo (approval-bot, candidate-miner,
           health-check, uncaged-morning-report)"

Step 2 — Commit safe documentation + planning artifacts (low blast radius):
  git add docs/plans/*.md docs/COLD_EMAIL_LAUNCH_PLAN.md docs/PHASE_0_INVENTORY.md \
          docs/SERVER-MIGRATION.md ENTERPRISE_SECURITY_README.md \
          INTEGRATION_DEPLOYMENT_PLAN.md
  Commit: "docs: cold outreach + server migration planning artifacts"

Step 3 — Commit container skills additions:
  git add container/skills/calendar-tool.md container/skills/recruitment-pipeline.md \
          container/scripts/
  Commit: "feat(container): calendar-tool + recruitment-pipeline skills"

Step 4 — Commit new src/ TypeScript modules (review for compile first):
  git add src/cr-monitor.ts src/email-generator.ts src/recruitment-db.ts \
          src/channels/google-calendar.ts
  Commit: "feat: cr-monitor, email-generator, recruitment-db, google-calendar channel"

Step 5 — Commit modified source (existing tracked files):
  git add src/channels/telegram.ts src/group-queue.test.ts src/sales-celebration.ts \
          src/sales-celebration.test.ts src/routing.test.ts
  Commit: "fix(channels+sales): telegram tweaks + sales-celebration improvements + tests"

Step 6 — Commit scripts (TS + Py + cjs):
  git add scripts/cr-*.ts scripts/cr-*.cjs scripts/cr-*.js \
          scripts/daily-email-mock.ts scripts/email-mock-standalone.ts \
          scripts/generate-email*.ts scripts/parse-*.cjs scripts/parse-*.py \
          scripts/manager-scorecard*.py scripts/agent-ltv-model.py scripts/ltv-*.py \
          scripts/lookup-agents.py scripts/oauth-synthetic-probe.py \
          scripts/populate-ob-tracker.py scripts/health-check.sh \
          scripts/add-*-scope.cjs scripts/gmail-campaign-archive.cjs
  Commit: "feat(scripts): CR archive, email generation, LTV/scorecard tooling"

Step 7 — REVIEW + decide on insurance-scraper subtree (separate commit OR exclude):
  Decision required (NEEDS-REVIEW): does nanoclaw repo own insurance-scraper, or is it
  a sibling repo? Server cron uses /home/david/insurance-scraper (sibling). Recommend
  EXCLUDING from nanoclaw commits and either (a) move to sibling repo, or (b) add to
  .gitignore. Until decision: keep dirty, do not commit.

Step 8 — Modified groups/telegram_braindump/CLAUDE.md:
  Per-group memory. Decide policy: usually committed only if intentional structural
  changes. Diff first, commit if meaningful, otherwise leave dirty.

Step 9 — Push branch + open PR:
  git push origin chore/cold-outreach-webhook-scorecards
  Open PR -> origin/main. After merge, server can be brought up to date.

Step 10 — Server reconciliation (a SEPARATE phase, not part of this plan):
  Server has its own large set of uncommitted changes (database optimization, security
  suite, gmail/discord channel implementations). These appear to be a parallel feature
  branch's worth of work that was never committed. They are NOT addressed here. Plan
  Phase 3 to: snapshot server working tree → diff vs local equivalents (where they
  exist locally) → decide which to bring back to repo, which are obsolete drafts.

---

## 9. Risks + Rollback Plan

Risks:
  R1. Discarding server-only scripts breaks 6+ cron jobs (silent prod outage).
      Mitigation: Step 1 above runs FIRST and is read-only-on-server (scp pull only).
  R2. Server src/index.ts and src/ipc.ts have large uncommitted edits (87, 55 lines).
      If we ever `git checkout` or `git reset --hard` on server, that work vanishes.
      Mitigation: NEVER run destructive git on server until snapshot tarball is taken.
  R3. insurance-scraper subtree may pull secrets (.env.worker1/2 files visible locally).
      Mitigation: do NOT git add insurance-scraper/.env.* at any step.
  R4. Server has untracked .bak files for src/index.ts and src/group-queue.ts —
      indicates someone has been hand-editing prod source. Treat server as authoritative
      for any logic in those .bak'd files.
  R5. package.json/package-lock.json drift on server suggests deps were installed only
      on server. Pulling those into local without `npm install` could break local build.

Rollback plan (if any Phase 2 step misbehaves):
  - All Phase 2 commits are local-only until Step 9 push. Use `git reset --soft HEAD~N`
    to unwind, or `git branch backup-$(date +%s)` before starting.
  - Server is touched ONLY in Step 1 (read-only scp). No rollback needed there.
  - Before final push, tag local: `git tag pre-phase2-$(date +%Y%m%d-%H%M)`.
  - Keep a tarball: `tar czf ~/nanoclaw-prephase2.tgz -C /Users/davidprice nanoclaw`
    (excluding node_modules / .venv / *.db).

---

## 10. Bucket Counts

  PROD-CRITICAL (cron-referenced or adjacent helpers):  ~20 files
    of which server-only-and-local-missing:              4 files (Step 1 rescue)
  SOURCE-CHANGES (worth committing on local):           ~50 files
    of which tracked-modified:                           12 files
    of which untracked new:                             ~38 files
  JUNK:                                                 ~22 files (local 12 + server 10)
  NEEDS-REVIEW:                                         insurance-scraper subtree
                                                        (~30 files) + 3 conflict files
                                                        + package.json/lock pair + group
                                                        memory files = ~38 paths

  TOTAL local dirty paths:    ~110
  TOTAL server dirty paths:    ~95
  TRUE conflict files (mod-on-both): 3 (src/index.ts, src/ipc.ts, src/routing.test.ts)

---

## Approval Question for Phase 2

Proceed with Phase 2 in the order above (rescue server-only scripts → docs commit →
container skills → new src modules → modified src → scripts) WITHOUT touching the
insurance-scraper subtree, server working tree, or any *.db / .env / certs files?
