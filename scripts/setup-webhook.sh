#!/bin/bash

set -e

echo "🚀 Setting up NanoClaw Telegram Webhook Infrastructure"
echo "=================================================="

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if .env file exists
if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠️  .env file not found. Creating from template...${NC}"
    if [ -f .env.webhook-example ]; then
        cp .env.webhook-example .env
        echo -e "${GREEN}✓ Created .env from webhook example${NC}"
    else
        echo -e "${RED}❌ .env.webhook-example not found. Please create .env manually.${NC}"
        exit 1
    fi
fi

echo
echo -e "${BLUE}🔧 Current Webhook Configuration:${NC}"

# Read current configuration
WEBHOOK_ENABLED=$(grep -E "^WEBHOOK_ENABLED=" .env | cut -d'=' -f2 || echo "false")
WEBHOOK_DOMAIN=$(grep -E "^WEBHOOK_DOMAIN=" .env | cut -d'=' -f2 || echo "")
WEBHOOK_PORT=$(grep -E "^WEBHOOK_PORT=" .env | cut -d'=' -f2 || echo "3002")
TELEGRAM_BOT_TOKEN=$(grep -E "^TELEGRAM_BOT_TOKEN=" .env | cut -d'=' -f2 || echo "")

echo "   Webhook Enabled: ${WEBHOOK_ENABLED}"
echo "   Domain: ${WEBHOOK_DOMAIN:-"(not set)"}"
echo "   Port: ${WEBHOOK_PORT}"
echo "   Bot Token: ${TELEGRAM_BOT_TOKEN:+***configured***}"

echo

# Function to update or add environment variable
update_env_var() {
    local key=$1
    local value=$2
    local file=".env"

    if grep -q "^${key}=" "$file"; then
        # Update existing
        sed -i.bak "s|^${key}=.*|${key}=${value}|" "$file"
    else
        # Add new
        echo "${key}=${value}" >> "$file"
    fi
}

# Interactive configuration
read -p "🌐 Enter your webhook domain (e.g., your-server.com): " NEW_DOMAIN
if [ ! -z "$NEW_DOMAIN" ]; then
    update_env_var "WEBHOOK_DOMAIN" "$NEW_DOMAIN"
    echo -e "${GREEN}✓ Updated webhook domain${NC}"
fi

read -p "🔐 Generate new webhook secret token? (y/N): " GENERATE_SECRET
if [[ $GENERATE_SECRET =~ ^[Yy]$ ]]; then
    SECRET_TOKEN=$(openssl rand -hex 32)
    update_env_var "WEBHOOK_SECRET_TOKEN" "$SECRET_TOKEN"
    echo -e "${GREEN}✓ Generated new webhook secret token${NC}"
fi

read -p "🚦 Enable webhook mode? (Y/n): " ENABLE_WEBHOOK
if [[ ! $ENABLE_WEBHOOK =~ ^[Nn]$ ]]; then
    update_env_var "WEBHOOK_ENABLED" "true"
    echo -e "${GREEN}✓ Enabled webhook mode${NC}"
else
    update_env_var "WEBHOOK_ENABLED" "false"
    echo -e "${YELLOW}⚠️  Webhook mode disabled - will use polling${NC}"
fi

echo
echo -e "${BLUE}📋 Webhook Setup Checklist:${NC}"

# Validation checks
CHECKS_PASSED=0
TOTAL_CHECKS=4

# Check 1: Domain configured
if [ ! -z "$(grep -E "^WEBHOOK_DOMAIN=" .env | cut -d'=' -f2)" ]; then
    echo -e "${GREEN}✓ Webhook domain configured${NC}"
    ((CHECKS_PASSED++))
else
    echo -e "${RED}❌ Webhook domain not configured${NC}"
fi

# Check 2: Bot token configured
if [ ! -z "$(grep -E "^TELEGRAM_BOT_TOKEN=" .env | cut -d'=' -f2)" ]; then
    echo -e "${GREEN}✓ Telegram bot token configured${NC}"
    ((CHECKS_PASSED++))
else
    echo -e "${RED}❌ Telegram bot token not configured${NC}"
    echo "   Please add TELEGRAM_BOT_TOKEN=your_token_here to .env"
fi

# Check 3: Dependencies installed
if npm list express >/dev/null 2>&1 && npm list helmet >/dev/null 2>&1; then
    echo -e "${GREEN}✓ Webhook dependencies installed${NC}"
    ((CHECKS_PASSED++))
else
    echo -e "${YELLOW}⚠️  Installing webhook dependencies...${NC}"
    npm install
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ Dependencies installed successfully${NC}"
        ((CHECKS_PASSED++))
    else
        echo -e "${RED}❌ Failed to install dependencies${NC}"
    fi
fi

# Check 4: Port available
if ! lsof -i :${WEBHOOK_PORT} >/dev/null 2>&1; then
    echo -e "${GREEN}✓ Webhook port ${WEBHOOK_PORT} is available${NC}"
    ((CHECKS_PASSED++))
else
    echo -e "${YELLOW}⚠️  Port ${WEBHOOK_PORT} is in use. Consider changing WEBHOOK_PORT${NC}"
fi

echo
echo -e "${BLUE}🎯 Setup Results: ${CHECKS_PASSED}/${TOTAL_CHECKS} checks passed${NC}"

if [ $CHECKS_PASSED -eq $TOTAL_CHECKS ]; then
    echo -e "${GREEN}🎉 Webhook setup completed successfully!${NC}"
    echo
    echo -e "${BLUE}Next steps:${NC}"
    echo "1. Build the project: npm run build"
    echo "2. Start NanoClaw: npm start"
    echo "3. Monitor logs: tail -f logs/nanoclaw.log"
    echo
    echo -e "${BLUE}Webhook URL will be:${NC}"
    FINAL_DOMAIN=$(grep -E "^WEBHOOK_DOMAIN=" .env | cut -d'=' -f2)
    FINAL_PORT=$(grep -E "^WEBHOOK_PORT=" .env | cut -d'=' -f2 || echo "3002")
    echo "https://${FINAL_DOMAIN}:${FINAL_PORT}/webhook"
else
    echo -e "${YELLOW}⚠️  Setup completed with warnings. Please review the failed checks above.${NC}"
fi

echo
echo -e "${BLUE}📖 For detailed documentation, see:${NC}"
echo "   docs/webhook-architecture.md"

echo
echo "🏁 Webhook setup script completed!"