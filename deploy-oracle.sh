#!/bin/bash
# deploy-oracle.sh - One-command deploy to your Oracle Cloud instance
# Run from your LOCAL machine (Windows Git Bash / WSL / Linux)
# Requires: SSH access to your Oracle instance

set -e

ORACLE_HOST="${ORACLE_HOST:-your-oracle-ip}"
ORACLE_USER="${ORACLE_USER:-ubuntu}"
REPO_URL="https://github.com/Kusdev00/discord-bot"
DEPLOY_DIR="/home/${ORACLE_USER}/discord-bot"

echo "🚀 Deploying Discord Bot to Oracle Cloud (${ORACLE_HOST})..."

# SSH and deploy
ssh "${ORACLE_USER}@${ORACLE_HOST}" << EOF
set -e
cd ${DEPLOY_DIR} 2>/dev/null || {
    echo "📥 Cloning repository..."
    git clone ${REPO_URL} ${DEPLOY_DIR}
    cd ${DEPLOY_DIR}
}

echo "🔄 Pulling latest changes..."
git pull origin main

echo "📦 Installing dependencies..."
source venv/bin/activate 2>/dev/null || python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

echo "⚙️  Checking .env..."
[ -f .env ] || cp .env.example .env
echo "   Please ensure .env has your DISCORD_TOKEN!"
grep -q "DISCORD_TOKEN=" .env || echo "   ⚠️  WARNING: DISCORD_TOKEN not found in .env"

echo "🔧 Installing systemd service..."
sudo tee /etc/systemd/system/discord-bot.service > /dev/null <<'SVC'
[Unit]
Description=Discord Bot
After=network.target

[Service]
Type=simple
User=${ORACLE_USER}
WorkingDirectory=${DEPLOY_DIR}
ExecStart=${DEPLOY_DIR}/venv/bin/python main.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SVC

echo "🔄 Reloading systemd & restarting bot..."
sudo systemctl daemon-reload
sudo systemctl enable discord-bot
sudo systemctl restart discord-bot

echo "✅ Deploy complete! Checking status..."
sudo systemctl status discord-bot --no-pager
EOF

echo ""
echo "✅ Deployment finished!"
echo "📋 Check logs: ssh ${ORACLE_USER}@${ORACLE_HOST} 'journalctl -u discord-bot -f'"