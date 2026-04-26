#!/bin/bash
# Deploy insurance scraper to Hetzner server
# Usage: ./deploy.sh user@hetzner-ip

set -e

REMOTE="${1:?Usage: ./deploy.sh user@hetzner-ip}"
REMOTE_DIR="/opt/insurance-scraper"

echo "=== Deploying Insurance Scraper to $REMOTE ==="

# Create remote directory
ssh "$REMOTE" "mkdir -p $REMOTE_DIR"

# Copy files
scp scraper.py verify_emails.py requirements.txt Dockerfile docker-compose.yml docker-compose.multi.yml .env.example .env.worker.example check_proxy_ips.py MULTI_WORKER_RUNBOOK.md "$REMOTE:$REMOTE_DIR/"

# Check if .env exists on remote, if not copy example
ssh "$REMOTE" "[ -f $REMOTE_DIR/.env ] || cp $REMOTE_DIR/.env.example $REMOTE_DIR/.env"

echo ""
echo "Files deployed to $REMOTE:$REMOTE_DIR"
echo ""
echo "Next steps on the server:"
echo "  1. Edit .env with your Supabase credentials:"
echo "     ssh $REMOTE 'nano $REMOTE_DIR/.env'"
echo ""
echo "  2. Run the Supabase schema migration (schema.sql) in your Supabase SQL editor"
echo ""
echo "  3. Build and start the scraper:"
echo "     ssh $REMOTE 'cd $REMOTE_DIR && docker compose up -d --build'"
echo ""
echo "  4. View logs:"
echo "     ssh $REMOTE 'cd $REMOTE_DIR && docker compose logs -f'"
echo ""
echo "  5. Restart after changes:"
echo "     ssh $REMOTE 'cd $REMOTE_DIR && docker compose up -d --build'"
