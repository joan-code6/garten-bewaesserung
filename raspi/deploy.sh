#!/bin/bash
# deploy.sh — Deploy the garden control system to Raspberry Pi
# Run from dev machine (requires sshpass)
# Usage: bash deploy.sh

PI_IP="<your-raspi-ip>"
PI_USER="<your-ssh-user>"
PI_PASS="<your-ssh-password>"
PI_DIR="<your-garden-dir>"

SSH="sshpass -p $PI_PASS ssh -o StrictHostKeyChecking=no $PI_USER@$PI_IP"
SCP="sshpass -p $PI_PASS scp -o StrictHostKeyChecking=no"

echo "=== Deploying Garden Irrigation to $PI_IP ==="

# 1. Create directory structure on Pi
echo "[1/6] Creating directories..."
$SSH "mkdir -p $PI_DIR/static/css $PI_DIR/static/js $PI_DIR/systemd"

# 2. Transfer Python files
echo "[2/6] Transferring Python files..."
$SCP config.py database.py auth.py server.py scheduler.py discord_bot.py config.example.yaml requirements.txt \
    "$PI_USER@$PI_IP:$PI_DIR/"

# 3. Transfer static files
echo "[3/6] Transferring web frontend..."
$SCP static/login.html static/index.html static/css/style.css static/js/app.js \
    "$PI_USER@$PI_IP:$PI_DIR/static/"
$SCP -r static/css static/js "$PI_USER@$PI_IP:$PI_DIR/static/" 2>/dev/null || true

# 4. Transfer systemd files
echo "[4/6] Transferring systemd units..."
$SCP systemd/garden-server.service systemd/garden-discord.service \
    "$PI_USER@$PI_IP:$PI_DIR/systemd/"

# 5. Create config.yaml on Pi if it doesn't exist
echo "[5/6] Checking config.yaml..."
$SSH "if [ ! -f $PI_DIR/config.yaml ]; then cp $PI_DIR/config.example.yaml $PI_DIR/config.yaml && echo 'Created config.yaml — EDIT IT!'; else echo 'config.yaml already exists'; fi"

# 6. Install and enable systemd services
echo "[6/6] Installing systemd services..."
$SSH "
    sudo cp $PI_DIR/systemd/garden-server.service /etc/systemd/system/ &&
    sudo cp $PI_DIR/systemd/garden-discord.service /etc/systemd/system/ &&
    sudo systemctl daemon-reload &&
    sudo systemctl enable garden-server garden-discord &&
    sudo systemctl restart garden-server garden-discord &&
    echo 'Services installed and started'
"

echo ""
echo "=== Deploy complete! ==="
echo ""
echo "Check service status:"
echo "  ssh $PI_USER@$PI_IP 'sudo systemctl status garden-server garden-discord'"
