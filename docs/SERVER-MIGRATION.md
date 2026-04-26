# Moving NanoClaw to a Hetzner Server

Step-by-step guide. No Linux experience needed.

---

## Step 1: Create the Server

1. Go to https://www.hetzner.com/cloud and sign up
2. Add a payment method
3. Click **Add Server**
4. Pick these settings:
   - **Location:** Ashburn (closest to US)
   - **Image:** Ubuntu 24.04
   - **Type:** CX32 (4 vCPU, 8GB RAM) — $8/month
   - **SSH Key:** Click "Add SSH Key" — paste your key (see below)
   - **Name:** `nanoclaw`
5. Click **Create & Buy Now**
6. Write down the IP address it gives you (e.g. `65.108.42.123`)

### How to get your SSH key

Open Terminal on your Mac and run:

```bash
# Check if you already have one
cat ~/.ssh/id_ed25519.pub
```

If that shows a long string starting with `ssh-ed25519`, copy it and paste it into Hetzner.

If it says "No such file", create one:

```bash
ssh-keygen -t ed25519
# Press Enter 3 times (accept defaults, no password)
cat ~/.ssh/id_ed25519.pub
# Copy this output and paste into Hetzner
```

---

## Step 2: Log In to Your Server

On your Mac, open Terminal:

```bash
ssh root@YOUR_SERVER_IP
```

Type `yes` when it asks about the fingerprint. You're now on your server.

---

## Step 3: Secure the Server

Run these commands one at a time on the server:

```bash
# Update everything
apt update && apt upgrade -y

# Create your user account
adduser david
# Type a password, press Enter through the rest

# Give yourself admin rights
usermod -aG sudo david

# Copy your SSH key to the new account
mkdir -p /home/david/.ssh
cp /root/.ssh/authorized_keys /home/david/.ssh/
chown -R david:david /home/david/.ssh

# Set up firewall
ufw allow OpenSSH
ufw enable
# Type 'y' when asked

# Set timezone
timedatectl set-timezone America/New_York
```

**TEST BEFORE CONTINUING:** Open a NEW terminal tab on your Mac and run:

```bash
ssh david@YOUR_SERVER_IP
```

If that works, you're good. If not, fix it using your still-open root session.

---

## Step 4: Install Node.js and Docker

Log in as david (`ssh david@YOUR_SERVER_IP`) and run:

```bash
# Install Node.js
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs

# Install Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker david

# Install build tools (needed for SQLite)
sudo apt install -y build-essential python3 git sqlite3

# Add swap space (prevents out-of-memory during Docker builds)
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# IMPORTANT: Log out and back in so Docker works without sudo
exit
```

Log back in:

```bash
ssh david@YOUR_SERVER_IP
```

Verify everything:

```bash
node -v      # Should show v22.x
docker -v    # Should show Docker version
```

---

## Step 5: Prepare Your Mac for Transfer

**On your Mac**, stop NanoClaw first so databases are clean:

```bash
launchctl unload ~/Library/LaunchAgents/com.nanoclaw.plist
```

Flush the databases (important — makes sure all data is saved):

```bash
for db in ~/nanoclaw/store/*.db ~/nanoclaw/data/groups/*/messages.db ~/nanoclaw/data/recruitment/*.db ~/nanoclaw/nanoclaw.db; do
  [ -f "$db" ] && sqlite3 "$db" "PRAGMA wal_checkpoint(TRUNCATE);" 2>/dev/null && echo "OK: $db"
done
```

---

## Step 6: Copy Everything to the Server

**On your Mac**, run these one at a time. Replace `YOUR_SERVER_IP` with your actual IP:

```bash
# Clone the repo on the server first
ssh david@YOUR_SERVER_IP "cd ~ && git clone https://github.com/dpinternational/nanoclaw.git"

# Copy your secrets file
scp ~/nanoclaw/.env david@YOUR_SERVER_IP:~/nanoclaw/.env

# Copy databases (this stores all your messages, sales, tasks)
scp -r ~/nanoclaw/store david@YOUR_SERVER_IP:~/nanoclaw/

# Copy application data (sales DBs, recruitment data)
scp -r ~/nanoclaw/data david@YOUR_SERVER_IP:~/nanoclaw/

# Copy group configs (this is the biggest one, ~360MB, may take a few minutes)
scp -r ~/nanoclaw/groups david@YOUR_SERVER_IP:~/nanoclaw/

# Copy root database if it has data
scp ~/nanoclaw/nanoclaw.db david@YOUR_SERVER_IP:~/nanoclaw/

# Copy config files
ssh david@YOUR_SERVER_IP "mkdir -p ~/.config/nanoclaw"
scp ~/.config/nanoclaw/*.json david@YOUR_SERVER_IP:~/.config/nanoclaw/ 2>/dev/null
```

If the repo is private, use a GitHub personal access token:
1. Go to https://github.com/settings/tokens → Generate new token (classic) → check "repo" → Create
2. Use: `ssh david@YOUR_SERVER_IP "cd ~ && git clone https://YOUR_TOKEN@github.com/dpinternational/nanoclaw.git"`

---

## Step 7: Build NanoClaw on the Server

**SSH into your server** and run:

```bash
ssh david@YOUR_SERVER_IP

cd ~/nanoclaw

# Install packages
npm install

# Compile TypeScript
npm run build

# Build the Docker container for agents (takes 5-10 minutes first time)
./container/build.sh
```

---

## Step 8: Set Up Auto-Start

This makes NanoClaw start automatically on boot and restart if it crashes.

```bash
sudo tee /etc/systemd/system/nanoclaw.service << 'EOF'
[Unit]
Description=NanoClaw Personal Claude Assistant
After=network-online.target docker.service
Wants=network-online.target
Requires=docker.service

[Service]
Type=simple
User=david
WorkingDirectory=/home/david/nanoclaw
ExecStart=/usr/bin/node /home/david/nanoclaw/dist/index.js
Restart=always
RestartSec=10
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.default.target
EOF

# Enable it (starts on boot)
sudo systemctl daemon-reload
sudo systemctl enable nanoclaw

# Start it now
sudo systemctl start nanoclaw
```

---

## Step 9: Check if It Works

```bash
# Is it running?
sudo systemctl status nanoclaw

# Watch the live logs
journalctl -u nanoclaw -f
```

You should see:
- "Telegram polling mode configured"
- "NanoClaw running (trigger: @Andy)"
- Channel connections (Discord, Gmail, etc.)

**Test it:** Send `@Andy hello` in your Telegram group. If Andy responds, you're done.

---

## Step 10: Turn Off the Mac Version

Once you confirm the server is working, **on your Mac**:

```bash
# It should already be stopped from Step 5, but make sure:
launchctl unload ~/Library/LaunchAgents/com.nanoclaw.plist
```

---

## Day-to-Day Cheat Sheet

```bash
# Log into your server
ssh david@YOUR_SERVER_IP

# Check if NanoClaw is running
sudo systemctl status nanoclaw

# Watch live logs
journalctl -u nanoclaw -f

# Restart NanoClaw
sudo systemctl restart nanoclaw

# Update code from GitHub
cd ~/nanoclaw && git pull && npm install && npm run build && sudo systemctl restart nanoclaw

# Rebuild agent container (after Dockerfile changes)
cd ~/nanoclaw && ./container/build.sh

# Check disk space
df -h

# Check memory
free -h

# See running Docker containers
docker ps
```

---

## If Something Goes Wrong

| Problem | Fix |
|---------|-----|
| "Permission denied" when SSH-ing | `ssh david@YOUR_SERVER_IP` (not root) |
| NanoClaw won't start | `journalctl -u nanoclaw -n 50 --no-pager` to see the error |
| "better-sqlite3" install fails | `sudo apt install build-essential python3` then `npm install` again |
| Docker says "permission denied" | `sudo usermod -aG docker david` then log out and back in |
| Out of memory | Add swap: `sudo fallocate -l 4G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile` |
| Gmail stops working | OAuth tokens may need re-authentication on the new server |
| Andy responds twice | Make sure the Mac version is stopped: `launchctl unload ~/Library/LaunchAgents/com.nanoclaw.plist` |

---

## Optional: Get Alerts if NanoClaw Goes Down

Create a script that texts you on Telegram when the service crashes:

```bash
sudo tee /usr/local/bin/nanoclaw-alert.sh << 'EOF'
#!/bin/bash
BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
CHAT_ID="577469008"
curl -s -X POST "https://api.telegram.org/bot${BOT_TOKEN}/sendMessage" \
  -d chat_id="${CHAT_ID}" \
  -d text="NanoClaw went down at $(date). Auto-restarting..." > /dev/null
EOF

sudo chmod +x /usr/local/bin/nanoclaw-alert.sh
```

Then add this line to the service file under `[Service]`:

```bash
sudo systemctl edit nanoclaw
```

Add:

```ini
[Service]
ExecStopPost=/usr/local/bin/nanoclaw-alert.sh
```

Then: `sudo systemctl daemon-reload && sudo systemctl restart nanoclaw`
