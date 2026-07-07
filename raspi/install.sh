#!/bin/bash
# install.sh — Run ON the Raspberry Pi after deploy.sh transfers files.
# Installs Python dependencies and systemd services.
# Usage: bash install.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== Garden Irrigation — Installation ==="
echo "Directory: $SCRIPT_DIR"

# ── Check Python ──
echo ""
echo "[1/6] Checking Python..."
python3 --version

# ── Install system dependencies ──
echo ""
echo "[2/6] Installing system packages..."
sudo apt update -qq
sudo apt install -y python3-pip python3-venv mosquitto mosquitto-clients curl

# ── Install Python dependencies ──
echo ""
echo "[3/6] Installing Python dependencies..."
pip3 install --break-system-packages -r requirements.txt 2>/dev/null || \
    pip3 install -r requirements.txt

# ── Install systemd services ──
echo ""
echo "[4/6] Installing systemd services..."
sudo cp systemd/garden-server.service /etc/systemd/system/
sudo cp systemd/garden-discord.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable garden-server.service

# ── Start services ──
echo ""
echo "[5/6] Starting services..."
sudo systemctl restart garden-server
echo "  garden-server: $(sudo systemctl is-active garden-server)"

# Optional: Only start Discord bot if token is configured
if grep -q "bot_token: \"PLACEHOLDER\"" config.yaml || grep -q "bot_token: \"your-discord" config.yaml; then
    echo "  garden-discord: SKIPPED (token not configured)"
else
    sudo systemctl enable garden-discord.service
    sudo systemctl restart garden-discord
    echo "  garden-discord: $(sudo systemctl is-active garden-discord)"
fi

# ── Verify ──
echo ""
echo "[6/6] Verification..."
sleep 2
if curl -s http://localhost:8000/login > /dev/null 2>&1; then
    echo "  Web server: OK (http://localhost:8000)"
else
    echo "  Web server: NOT RESPONDING — check log: tail -50 server.log"
fi

echo ""
echo "=== Installation complete! ==="
echo ""
echo "Web:       http://$(hostname -I | awk '{print $1}'):8000"
echo "Logs:      tail -f server.log"
echo "Status:    sudo systemctl status garden-server"
echo ""
echo "Next: Edit config.yaml to set your Discord bot token and passwords."
