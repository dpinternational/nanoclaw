# NanoClaw Operations

This document describes where things run and how the system is wired together.
See also: docs/plans/2026-04-26-git-state-cleanup-plan.md for the cleanup plan
that established the conventions below.

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
