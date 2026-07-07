#!/bin/bash
# cloudflared-setup.sh — Run on the Raspberry Pi to set up Cloudflare Tunnel
# Usage: bash cloudflared-setup.sh

set -e

DOMAIN="garten-bewaesserung.joancode.dev"
SERVICE="http://localhost:8000"

echo "================================="
echo " Cloudflare Tunnel Setup"
echo " $DOMAIN → $SERVICE"
echo "================================="
echo ""

# ── Step 1: Login to Cloudflare ──
echo "[1/4] Login to Cloudflare..."
echo ""
echo "  A browser URL will appear below. Open it on your PC/phone."
echo "  Log in with your Cloudflare account (the one that manages joancode.dev)."
echo "  Select the domain joancode.dev when prompted."
echo ""
read -p "  Press Enter to open the login page..."
cloudflared tunnel login

# ── Step 2: Create tunnel ──
echo ""
echo "[2/4] Creating tunnel..."
TUNNEL_ID=$(cloudflared tunnel create garden 2>&1 | grep -oP 'Created tunnel \K[a-f0-9-]+' || cloudflared tunnel list --output json | python3 -c "import sys,json; tunnels=json.load(sys.stdin); print([t['id'] for t in tunnels if t.get('name')=='garden'][0] if tunnels else '')")
echo "  Tunnel ID: $TUNNEL_ID"

# ── Step 3: Configure tunnel ──
echo ""
echo "[3/4] Configuring tunnel..."
mkdir -p ~/.cloudflared
cat > ~/.cloudflared/config.yml << CFEOF
tunnel: $TUNNEL_ID
credentials-file: /home/bennet/.cloudflared/$TUNNEL_ID.json

ingress:
  - hostname: $DOMAIN
    service: $SERVICE
  - service: http_status:404
CFEOF
echo "  Config written to ~/.cloudflared/config.yml"

# ── Step 4: Route DNS ──
echo ""
echo "[4/4] Routing DNS..."
cloudflared tunnel route dns garden $DOMAIN
echo "  DNS record created: $DOMAIN → tunnel"

# ── Install systemd service ──
echo ""
echo "Installing systemd service..."
sudo cp /home/bennet/Gartenbewaesserung/systemd/garden-tunnel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable garden-tunnel
sudo systemctl restart garden-tunnel
sleep 3

echo ""
echo "================================="
echo " Setup complete!"
echo "================================="
echo ""
echo "Check status:"
echo "  sudo systemctl status garden-tunnel"
echo "  tail -f ~/.cloudflared/cloudflared.log"
echo ""
echo "Your site should be live at:"
echo "  https://$DOMAIN"
echo ""
echo "=== NEXT: Cloudflare Access (email OTP login) ==="
echo "  Go to: https://one.dash.cloudflare.com"
echo "  → Access → Applications → Add Application → Self-hosted"
echo "  → Name: Garden, Domain: $DOMAIN"
echo "  → Policy: Include → Emails ending in @yourdomain.com"
echo "  → Or: Use 'One-time PIN' for email-based login"
