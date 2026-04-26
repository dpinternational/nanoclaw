# NanoClaw Operations

This document describes where things run and how the system is wired together.
See also: docs/plans/2026-04-26-git-state-cleanup-plan.md for the cleanup plan
that established the conventions below.

## Weekly LTV refresh

scripts/agent-ltv-model.py is the canonical Agent Lifetime Value runner.
It pulls Recruiting Report + Money Report from Google Sheets, joins
production from store/tpg-intel.db, and rebuilds the agent_ltv,
ltv_by_source, and ltv_by_manager tables.

Cron (user david, server):
    0 10 * * 1 cd /home/david/nanoclaw && TZ=UTC NODE_PATH=/home/david/nanoclaw/node_modules python3 scripts/agent-ltv-model.py >> /home/david/nanoclaw/logs/ltv-weekly.log 2>&1

Schedule rationale: Monday 10:00 UTC is one hour after gina-production-sync
(Mon 09 UTC), so the production db has the latest weekly numbers before LTV
recomputes. The other two ltv-*.py scripts (ltv-complete.py,
ltv-deep-analysis.py) are ad-hoc analyses against pre-dumped JSON and are
not part of the weekly schedule.

## Where things run

There are two production hosts:

1. Local Mac (development + some channels)
   - Path: /Users/davidprice/nanoclaw
   - Runs the Node.js orchestrator under launchd:
     ~/Library/LaunchAgents/com.nanoclaw.plist
   - Used for interactive development, edits, and as the source-of-truth git
     working tree.

2. Hetzner server (prod automation)
   - Host: root@89.167.109.12
   - Path: /home/david/nanoclaw
   - Runs the email/inbox-brief/Telegram-recovery scheduled jobs via crontab
     (user david) and a few systemd-user units.
   - Provides the Discord/Slack/Telegram bot listeners and email digest jobs.

## Crontab location

On the Hetzner box (as user david):

    ssh root@89.167.109.12
    sudo -u david crontab -l         # view
    sudo -u david crontab -e         # edit (rare; prefer git + rsync)

A snapshot of the prod crontab lives under backups/crontab-*.bak in this repo.

## Bot tokens (the four)

The system uses four bot identities. Tokens themselves live only in .env files
(NEVER committed). Identities:

1. Telegram - main NanoClaw bot (incoming user messages -> agent)
2. Discord  - email approval + scorecard channel bot
3. Slack    - status / celebration bot
4. Gmail OAuth (service account + user-delegated) - email channel + digests

Token storage:
   - Local Mac:    /Users/davidprice/nanoclaw/.env
   - Hetzner:      /home/david/nanoclaw/.env
Both are gitignored. Rotations: see docs/SERVER-MIGRATION.md.

## CRITICAL: edit-flow rule for scripts/

Anything under scripts/ that runs in prod is server-prod and is deployed by
manual rsync from this repo (Mac) -> Hetzner. The flow is:

    # 1. Edit on Mac inside this repo
    vim /Users/davidprice/nanoclaw/scripts/<file>.py
    # 2. Commit to git
    git add scripts/<file>.py && git commit -m "scripts: ..."
    # 3. Deploy to server
    rsync -av --exclude='__pycache__' --exclude='*.bak' \
        /Users/davidprice/nanoclaw/scripts/ \
        root@89.167.109.12:/home/david/nanoclaw/scripts/

NEVER edit files directly on the server. The server tree is downstream of the
Mac repo. Editing on the server creates drift that has bitten us before
(see Phase 1 inventory in docs/plans/2026-04-26-git-state-cleanup-plan.md
for the divergence that triggered this cleanup).

If you find yourself wanting to hot-patch the server, instead:
  - SSH in to read-only diagnose
  - scp the file DOWN to Mac, edit, commit, rsync UP
  - Or apply the change on Mac and rsync the single file up

## References

- docs/plans/2026-04-26-git-state-cleanup-plan.md - the cleanup plan
- docs/SERVER-MIGRATION.md - server bootstrap notes
- docs/REQUIREMENTS.md - architecture
- README.md - philosophy + setup

## Deploying to Hetzner

The Mac is the source of truth. The Hetzner server (root@89.167.109.12,
/home/david/nanoclaw/) is a deploy target that we treat as read-only from
the agent's perspective: nothing here writes to the server except a
deliberate rsync.

Use `scripts/deploy-to-server.sh` for every push to the server.

```
./scripts/deploy-to-server.sh scripts --dry-run    # always dry-run first
./scripts/deploy-to-server.sh scripts --execute    # then apply
./scripts/deploy-to-server.sh insurance-scraper --execute
```

The script:
- defaults to dry-run unless `--execute` is given
- excludes `__pycache__`, `*.pyc`, `.venv`, `*.bak`, `*.bak-*`, `.DS_Store`
- chowns to `david:david` on the remote post-rsync
- prints before/after file counts
- appends to `logs/deploy.log`

## Pre-edit checklist

Before changing anything that runs on the server:

1. `git status` is clean (no random unstaged WIP).
2. Make the edit on the Mac. Never SSH-edit on the server.
3. Test locally if at all possible (`npm run build`, unit tests, dry-runs).
4. Deploy with `./scripts/deploy-to-server.sh <subdir> --dry-run` then
   `--execute`.
5. `git add <specific paths> && git commit && git push origin <branch>`.

## What lives where

| Path                        | Source of truth | Runs on        | Notes                                  |
|-----------------------------|-----------------|----------------|----------------------------------------|
| `src/`                      | Mac (git)       | Mac (launchd)  | Core NanoClaw orchestrator             |
| `scripts/`                  | Mac (git)       | Mac + Hetzner  | Deployed via `deploy-to-server.sh`     |
| `insurance-scraper/`        | Mac (git)       | Hetzner        | Multi-worker scraper, deploy via rsync |
| `container/`                | Mac (git)       | Mac (Docker)   | Agent container image                  |
| `groups/`                   | Mac (local)     | Mac            | Per-group memory, gitignored data      |
| `logs/`                     | Mac (local)     | Mac            | Local logs incl. `deploy.log`          |
| `/home/david/nanoclaw/` (server) | rsync target | Hetzner    | Never edit directly                    |
