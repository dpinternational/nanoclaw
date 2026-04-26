# PHASE 0 — STATE INVENTORY (David Price / NanoClaw)
Generated 2026-04-17 from live system

---

## A. GROUPS — 22 total (9 have no CLAUDE.md)

| # | Group | CLAUDE.md | Files | Scripts | Last | VERDICT |
|---|-------|-----------|-------|---------|------|---------|
| 1 | campaign_creation | NO | 1 | 0 | 2026-03-23 | **RETIRE** |
| 2 | discord_agent_scraper | YES | 73 | 0 | 04-17 | KEEP |
| 3 | discord_calendar_scheduling | NO | 0 | 0 | — | **RETIRE** (empty) |
| 4 | discord_command_center | NO | 1 | 0 | 03-23 | **RETIRE** |
| 5 | discord_email_campaigns | YES | 2965 | 1097 | 04-17 | KEEP (but reduce scope) |
| 6 | discord_email_triage | YES | 7 | 0 | 03-24 | **FREEZE** (inbox triage failed — mission aspirational) |
| 7 | discord_main | YES | 3 | 0 | 03-22 | **RETIRE** (Discord deprecated as ops surface) |
| 8 | discord_tpg_uncaged_chat | NO | 4 | 0 | 03-23 | **RETIRE** |
| 9 | global | YES | 1 | 0 | 03-20 | KEEP (fallback personality) |
| 10 | gmail_campaigns | NO | 0 | 0 | — | **RETIRE** (orphan registration) |
| 11 | gmail_main | NO | 0 | 0 | — | **RETIRE** (orphan registration) |
| 12 | main | YES | 2 | 0 | 04-11 | KEEP |
| 13 | telegram_7th_level_training | NO | 3 | 0 | 04-17 | FREEZE (just photos) |
| 14 | telegram_braindump | YES | 48 | 0 | 04-17 | **KEEP — high-value voice core** |
| 15 | telegram_content_ideas | YES | 3 | 0 | 04-16 | KEEP |
| 16 | telegram_fb_posting | NO | 1 | 0 | 04-01 | FREEZE |
| 17 | telegram_main | YES | 4942 | 1316 | 04-17 | **KEEP — primary ops surface** |
| 18 | telegram_the_council | YES | 12 | 0 | 04-16 | KEEP |
| 19 | telegram_tpg_uncaged | YES | 95 | 0 | 04-16 | KEEP |
| 20 | telegram_va_desk | YES | 85 | 0 | 04-16 | KEEP |
| 21 | tpg_monitoring | YES | 4 | 1 | 03-24 | **FREEZE** (stale, overlaps telegram_main) |
| 22 | tpg_uncaged_systems | NO | 62 | 36 | 03-31 | **INVESTIGATE** — 36 scripts, no personality. Likely infrastructure folder, not an agent group. Last updated 2026-03-31. |

Tally: 11 KEEP / 5 FREEZE / 6 RETIRE (9 net folders to delete/move)

---

## B. SCHEDULED TASKS — NanoClaw DB (`store/messages.db`)

### ACTIVE (13)

| Task | Group | Cron | Last | Status |
|------|-------|------|------|--------|
| morning-briefing-7am | telegram_main | 0 7 * * * | 04-17 | healthy |
| daily_fb_draft | telegram_braindump | 0 8 * * * | 04-17 | healthy |
| health-morning-check | telegram_main | 57 8 * * * | 04-17 | healthy |
| youtube_monitor | telegram_braindump | 0 10 * * * | 04-17 | healthy (local only per memory) |
| recruitment-scraper-health | discord_agent_scraper | 0 */6 * * * | 04-17 | healthy |
| recruitment-new-licensee-alert | discord_agent_scraper | 0 12 * * * | 04-17 | **BROKEN** — Container exit code 137, "Group not found: discord_agent_scraper" |
| task-1774132148036-jm4gai | discord_email_campaigns | 0 9 * * * | 04-17 | running but mystery id — no name |
| recruitment-daily-capture | telegram_main | 0 18 * * 1-5 | 04-17 | healthy |
| recruitment-pipeline-daily | discord_agent_scraper | 0 18 * * * | 04-17 | healthy |
| task-1775653326033-zpg5bx | discord_email_campaigns | 0 18 * * * | 04-17 | mystery id |
| cr-daily-monitor | telegram_main | 47 20 * * * | 04-17 | healthy |
| email-mock-daily | telegram_main | 3 21 * * * | 04-17 | **QUESTIONABLE** — "mock" sounds like test |
| recruitment-weekly-digest | telegram_main | 0 8 * * 1 | 04-13 | healthy |

### DISABLED (5) — still taking DB space

- daily-personal-summary-3am (2x fail/17 runs)
- task-1774039938082-hpbolm (**1,244 fail / 1,253 runs** — TPG goals pusher, killed Apr 1)
- tpg-morning-kickoff, tpg-midday-momentum, tpg-end-of-day (Andy silencing trio)

### ORPHAN in task_run_logs (not in scheduled_tasks)
- **daily-tpg-summary**: 1,554 errors / 1,559 runs. Last run 2026-03-25. No current schedule entry. Failure cause: "Group not found: telegram_tpg_uncaged". Dead task left its log scars.

---

## C. CRONS

### Local Mac (davidprice@) — 2 entries, **BOTH BROKEN**

```
*/5 * * * * node conservative-email-monitor.cjs >> conservative-email.log
```
- Points to `/Users/davidprice/conservative-email-monitor.cjs` — path doesn't exist.
- Actual file lives at `~/nanoclaw/groups/discord_email_campaigns/workspace/conservative-email-monitor.cjs`
- Last logged error: `Cannot find module '/Users/davidprice/conservative-email-monitor.cjs'`
- **Failing every 5 min silently for weeks.**

```
*/5 * * * * cd .../workspace && node proactive-email-system.cjs
```
- File exists. But log spam: `💥 Processing failed: Parse error: Unexpected end of JSON input`
- **Failing every 5 min silently for weeks.**

### Local launchd (3)
- com.nanoclaw.cr-monitor → runs cr-monitor-standalone.ts at 20:47 daily
- com.nanoclaw.email-mock → runs email-mock-standalone.ts at 21:03 daily
- com.nanoclaw.healthcheck → every 5 min

### Server (Hetzner david@89.167.109.12)
- 9 david crontab entries + 3 root entries (watchdog, health-check, email-performance-tracker)
- All python scripts healthy except **approval-bot.log has 2,792 errors** (needs look)
- health-check.log has 12 errors

---

## D. CHANNEL / GROUP DRIFT (what Codex caught)

### Orphaned registered_groups (folder registered, chat doesn't exist in DB)
- `gmail_main` → gmail:david@tpglife.com
- `gmail_campaigns` → gmail:davidprice@tpglife.com
- `discord_calendar_scheduling` → dc:1484839662278283334

### Orphaned chats (active chat, not registered)
- **"Daily Email Ops"** tg:-5270945980 — last msg 2026-04-17 10:20. Active group, not in any folder mapping.

---

## E. SCRIPTS — 34 local + 22 server

### Local Mac (~/nanoclaw/scripts/) — most recent
| Date | Script | Status |
|------|--------|--------|
| 04-14 | manager-scorecard-gina.py | active |
| 04-14 | manager-scorecard.py | active |
| 04-14 | target-carrier-alert.py | active (server) |
| 04-14 | tpg-daily-digest-server.py | active (server) |
| 04-13 | agent-ltv-model.py | recent |
| 04-13 | gina-production-sync.py | active (server Mon 5AM) |
| 04-13 | ltv-complete.py + ltv-deep-analysis.py | recent |
| 04-13 | parse-daily-production.py | recent |
| 04-13 | populate-ob-tracker.py | recent |
| 04-12 | cr-archive-builder.js, cr-full-archive.cjs | active |
| 04-12 | email-digest-server.py, email-reaction-handler.cjs | active |
| 04-12 | gmail-campaign-archive.cjs | active |
| 04-12 | youtube-monitor.py | active |
| 04-08 | cr-monitor-standalone.ts, email-mock-standalone.ts | active (launchd) |
| 04-06 | cr-email-pull, daily-email-mock, generate-email, generate-email-day | **overlapping email gen — consolidate** |
| 03-31 | whisper-transcribe, youtube-scraper | stale |
| 03-25/29/30 | benchmark/validate/migrate scripts | one-shot, RETIRE |

### Known overlapping email tooling (pick ONE):
- email-digest-server.py ← active (server 11AM daily)
- email-drafter-v2.py ← on server, David approved as "most mature"
- email-approval-bot.py ← active (server 10:30AM + 3PM M-F)
- email-mock-standalone.ts (launchd 21:03) + daily-email-mock.ts + email-mock-daily task ← TRIPLE mock, retire 2 of 3
- generate-email.ts + generate-email-day.ts ← redundant, collapse
- conservative-email-monitor.cjs ← **cron broken, script exists**
- proactive-email-system.cjs ← **cron spamming errors**
- email-reaction-handler.cjs ← status unknown
- email-performance-tracker.py ← server 3AM

**That's 10+ email-adjacent scripts.** Codex's core critique: email isn't one system, it's a landfill.

---

## F. KPIs TO LOCK IN (Phase 0 output)

| KPI | Current | Target (Week 1 end) |
|-----|---------|---------------------|
| Unread inbox | 12→0 today | ≤ 25 standing |
| Daily manual email touches | high | ≤ 10 |
| Task failure rate (active tasks) | ~20% (recruitment-new-licensee broken) | ≤ 2% |
| Broken crons (local+server) | 2+ confirmed silent failures | 0 |
| Groups with CLAUDE.md | 13/22 (59%) | 100% or folder gone |
| Scheduler drift entries | 4 (3 orphan folders + 1 orphan chat) | 0 |
| Fabricated content in sent outbound | unknown | 0 (enforced, not advisory) |
| Andy autonomy scope | broad (then silenced) | narrow (1 domain) |

---

## G. IMMEDIATE ACTIONS (Phase 0 → Phase 1 bridge)

Priority 1 — this session:
- [ ] Remove 2 broken local Mac cron entries
- [ ] Delete 5 disabled scheduled_tasks rows
- [ ] Delete or purge daily-tpg-summary log rows (1554 error entries)
- [ ] Register or archive "Daily Email Ops" orphan chat
- [ ] Unregister the 3 orphan folder mappings

Priority 2 — Monday:
- [ ] Retire 6 dead group folders (campaign_creation, discord_calendar_scheduling, discord_command_center, discord_tpg_uncaged_chat, gmail_campaigns, gmail_main, discord_main)
- [ ] Decide: Telegram = operator surface. Discord = off for ops.
- [ ] Fix recruitment-new-licensee-alert (broken since Apr 1)
- [ ] Investigate tpg_uncaged_systems/ (36 scripts, no CLAUDE.md)
- [ ] Rename the two mystery tasks: `task-1774132148036-jm4gai`, `task-1775653326033-zpg5bx` → human-readable IDs
- [ ] Audit approval-bot 2,792 errors on server

Priority 3 — Tuesday:
- [ ] Pick email system primary: email-drafter-v2.py. Retire or subordinate the other 9.
- [ ] Build synthetic 15-min Gmail+Drive+Calendar probe (Codex's suggestion)

---

## H. WHAT I'M NOT DOING YET
(Codex was right — these come later)
- Voice linter
- Citation killswitch beyond outbound email
- State-of-the-Business weekly auto-report
- Transcript→7-asset content pipeline
- Behind-the-scenes David Price brand content
