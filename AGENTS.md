# AGENTS.md — Garden Irrigation System

Complete reference for AI agents operating this system.
Last updated: 01.07.2026

## Quick Access

| Resource | Value |
|----------|-------|
| Raspi IP | `192.168.178.55` |
| SSH user | `bennet` |
| SSH password | `<your-ssh-password>` |
| Sudo password | `<your-sudo-password>` |
| MQTT broker | `localhost:1883` (Mosquitto on Raspi) |
| ESP serial | `/dev/ttyACM*` (auto-detected by bridge) |
| ESP MAC | `e8:3d:c1:9e:1d:90` |
| Web dashboard | `http://192.168.178.55:8000` (local, no password needed) |
| Cloudflare Tunnel | `https://garten-bewaesserung.joancode.dev` (setup pending) |
| Cloudflare Access | SSO at edge (Google/GitHub/OTP) — auth handled before request reaches server |

SSH one-liner:
```
sshpass -p <password> ssh bennet@192.168.178.55 "command"
```
Or via paramiko in Python:
```python
import paramiko
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.178.55', username='bennet', password='<password>')
```

## Architecture

```
  ┌──────────────────────────────────────────────────────────────────┐
  │               MULTI-PLATFORM CONTROL LAYER                       │
  │                                                                  │
  │  Web Browser ─── HTTPS ──► Cloudflare Tunnel ──► FastAPI (:8000)│
  │  Discord App ─── ws ────► discord_bot.py                        │
  └──────────────────────────────┬───────────────────────────────────┘
                                 │ garden.py (MQTT client library)
                                 ▼
                    ┌─────────────────────────┐
                    │  Mosquitto MQTT (:1883)  │
                    └───────────┬─────────────┘
                                │
                    ┌───────────▼─────────────┐
                    │  usb_bridge.py           │  (auto-restart via cron every min)
                    │  auto-detects ACM*       │
                    └───────────┬─────────────┘
                                │ USB serial 115200 baud
                    ┌───────────▼─────────────┐
                    │  ESP32-C3-DevKitM-1      │
                    │  Firmware: v5 dynamic    │
                    │  RELAY_ACTIVE_LOW:false  │
                    └───────────┬─────────────┘
                                │
                    ┌───────────▼─────────────┐
                    │   5x Relay Module        │
                    │  GPIO 1,2,3,4,5         │
                    └─────────────────────────┘

  ┌──────────────────────────────────────────────────────────┐
  │  SCHEDULE ENGINE (APScheduler, in server process)         │
  │  - Loads schedules from SQLite DB                         │
  │  - Cron-triggered watering cycles                         │
  │  - Ad-hoc runs via API or Discord                         │
  └──────────────────────────────────────────────────────────┘
```

## MQTT Topics

| Topic | Direction | Payload | Retained |
|-------|-----------|---------|----------|
| `garden/relay/set` | → ESP | `{"pin":1,"state":1}` | no |
| `garden/relay/state` | ESP → | `{"type":"state","pin":1,"state":1}` | no |
| `garden/status` | ESP → | `{"type":"status","uptime":3600,"relays":{"1":1,...}}` | yes |

Quick access:
```bash
mosquitto_sub -t garden/status -C 1          # get latest status
mosquitto_sub -t garden/# -v                  # watch all topics
mosquitto_pub -t garden/relay/set -m '{"pin":1,"state":1}'  # raw MQTT command
```

## GPIO Pin Mapping (ESP32-C3, as of 02.07.2026)

| GPIO | Device | Notes |
|------|--------|-------|
| 0 | frei | has boot button on PCB — works but may glitch on reset |
| 1 | Gartenschlauch unten rechts | |
| 2 | Bewässerungsschlauch oben | strapping pin! Relay must not pull LOW at boot |
| 3 | Hauptwasserversorgung | main valve — must stay ON during entire watering |
| 4 | Sprinkler Beet oben | |
| 5 | (frei / nicht benannt) | |
| 6 | frei | |
| 7 | frei | |
| 10 | frei | |
| 20 | frei | also U0RXD |
| 21 | frei | also U0TXD |

**Blacklisted (firmware rejects):** 8, 9 (strapping), 18, 19 (USB/JTAG)
**Not on headers:** 11-17 (internal flash pins)

## ESP32 Firmware (src/main.ino)

- **Version:** v5 — dynamic GPIO
- **Board:** ESP32-C3-DevKitM-1 (platformio: `esp32-c3-devkitm-1`)
- **Framework:** Arduino
- **RELAY_ACTIVE_LOW:** `false` (HIGH = ON, LOW = OFF)
- **Baud rate:** 115200
- **Status interval:** 60 seconds
- **Behavior:** Accepts any GPIO 0-21 except blacklisted. Auto-configures `pinMode()` on first command. Status JSON dynamically lists only configured pins.

### Serial Protocol

ESP receives JSON lines (newline-terminated) over USB serial:
```
{"pin":1,"state":1}    → turns GPIO 1 ON
{"pin":2,"state":0}    → turns GPIO 2 OFF
```

ESP sends:
```
{"type":"state","pin":1,"state":1}                    ← per-command ack
{"type":"status","uptime":3600,"relays":{"1":1,...}}  ← every 60s
```

### Flashing the ESP

The ESP is connected via USB to the Raspberry Pi. Flash through the Pi:

```bash
# 1. Stop the bridge (frees serial port)
ssh bennet@192.168.178.55 "pkill -f usb_bridge.py; sleep 1"

# 2. Flash (use correct /dev/ttyACM* port)
ssh bennet@192.168.178.55 "esptool --chip esp32c3 --port /dev/ttyACM0 --baud 460800 write_flash \
    0x0 bootloader.bin 0x8000 partitions.bin 0x10000 firmware.bin"

# 3. Restart bridge (or cron will restart within 1 min)
ssh bennet@192.168.178.55 "nohup python3 -u /home/bennet/Gartenbewässerung/usb_bridge.py >> \
    /home/bennet/Gartenbewässerung/usb_bridge.log 2>&1 &"
```

**Compile on dev machine:**
```bash
cd esp32_relay_test
pio run
# Binaries: .pio/build/garden/{bootloader.bin, partitions.bin, firmware.bin}
```

**Transfer bins to Pi:**
```python
sftp.put('firmware.bin', '/home/bennet/garden_fw/firmware.bin')
```

If ESP is stuck in download mode (`wait usb download`), unplug/replug USB or press RST button. If GPIO 2 relay pulls LOW at boot, ESP won't start — disconnect GPIO 2 wire first.

## Scripts on Raspberry Pi

All in `/home/bennet/Gartenbewaesserung/`:

| File | Purpose | How to run |
|------|---------|------------|
| `usb_bridge.py` | USB↔MQTT bridge | `python3 usb_bridge.py` (cron auto-restarts) |
| `garden.py` | MQTT client library + CLI | `python3 garden.py on 1` / `off 2` / `status` / `watch` |
| `water_schedule.py` | Legacy timed watering cycle | `python3 water_schedule.py` (cron: 20:00 daily) — **DEPRECATED** |
| `manual_water.py` | Direct serial (no MQTT) | `python3 manual_water.py` |
| `server.py` | FastAPI web server + scheduler | systemd service `garden-server` |
| `discord_bot.py` | Discord bot with slash commands | systemd service `garden-discord` |
| `config.py` | Configuration loader | imported by all modules |
| `config.yaml` | Live configuration (secrets) | edit manually |
| `config.example.yaml` | Configuration template | — |
| `database.py` | SQLite layer (schedules, history) | auto-initialized |
| `scheduler.py` | APScheduler schedule engine | runs inside `server.py` |
| `auth.py` | JWT authentication | imported by `server.py` |
| `requirements.txt` | Python dependencies | `pip3 install -r requirements.txt` |
| `install.sh` | One-command Pi setup | `bash install.sh` |
| `deploy.sh` | Transfer files from dev machine | `bash deploy.sh` |
| `cloudflared-setup.sh` | Cloudflare Tunnel interactive setup | `bash cloudflared-setup.sh` |
| `static/` | Web frontend (SPA) | served by `server.py` |
| `systemd/` | Systemd unit files | `sudo cp systemd/*.service /etc/systemd/system/` |

### garden.py CLI
```bash
python3 garden.py on <pin>       # turn GPIO ON
python3 garden.py off <pin>      # turn GPIO OFF
python3 garden.py set <pin> <0|1>
python3 garden.py toggle <pin>
python3 garden.py status         # show ESP state (uptime, relays, rssi)
python3 garden.py watch          # live MQTT monitor
```

### server.py — Web Dashboard & API

**Auth:** Local network (192.168.x.x, 10.x.x.x, 127.0.0.0/8) auto-authenticates — no password needed. External requests are **blocked by default** (403). To gain access from an external IP, use the `/verify` command in Discord — this generates a one-time link (valid 1 hour) that adds your IP to the allowlist for 30 days. Cloudflare Tunnel requests arrive via 127.0.0.1 and auto-authenticate.

**Endpoints (auto-auth from local network or allowlisted IP, external IPs blocked otherwise):**

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/verify?token=xxx` | Consume Discord verify token → IP allowlisted for 30d |
| POST | `/api/auth/login` | Login → returns JWT token |
| GET | `/api/auth/check` | Check if IP is local or allowlisted |
| GET | `/api/relays` | All relay states with labels |
| POST | `/api/relays/{pin}/on` | Turn relay ON |
| POST | `/api/relays/{pin}/off` | Turn relay OFF |
| POST | `/api/relays/{pin}/toggle` | Toggle relay |
| GET | `/api/status` | ESP status (uptime, relays) |
| GET | `/api/schedules` | List all schedules |
| GET | `/api/schedules/{id}` | Get schedule detail |
| POST | `/api/schedules` | Create schedule |
| PUT | `/api/schedules/{id}` | Update schedule |
| DELETE | `/api/schedules/{id}` | Delete schedule |
| POST | `/api/schedules/{id}/run` | Trigger schedule immediately |
| GET | `/api/history?limit=100&offset=0` | Action history |
| WS | `/ws` | WebSocket — live relay state + status pushes |

**WebSocket events:**
```json
{"type":"state","pin":1,"state":1,"_topic":"garden/relay/state"}
{"type":"status","uptime":3600,"relays":{"1":1,...},"rssi":-42,"_topic":"garden/status"}
```

### discord_bot.py — Discord Bot

Slash commands:

**`/water <action> [pin] [schedule_name]`**

| Action | Description |
|--------|-------------|
| `Einschalten` | Turn relay ON (requires pin) |
| `Ausschalten` | Turn relay OFF (requires pin) |
| `Umschalten` | Toggle relay (requires pin) |
| `Status anzeigen` | Show ESP status and all relay states |
| `Zeitpläne auflisten` | List all configured schedules |
| `Zeitplan jetzt ausführen` | Trigger a schedule immediately |
| `Letzte Aktionen` | Show last 10 history entries |

**`/verify`** — Generate a one-time link (valid 1 hour). Clicking it adds your current IP to the allowlist for 30 days, granting access to the web dashboard.

### water_schedule.py — DEPRECATED

Replaced by the schedule engine in `scheduler.py`. Keep this file as a fallback/emergency script. No cron jobs needed.

### Scheduled Waterings (APScheduler, inside server.py)

| Name | Time | Cron |
|------|------|------|
| Morgenbewässerung | 08:00 daily | `0 8 * * *` |
| Abendbewässerung | 20:00 daily | `0 20 * * *` |

Each schedule: Hauptwasserversorgung (GPIO 3) ON → GPIO 1 20min → GPIO 2 20min → GPIO 4 20min → purge all 60s → Hauptventil OFF → wait 60s → safety all OFF.

### Cron Jobs
```
# Bridge keepalive: restart if dead (runs every minute)
* * * * * flock -n /tmp/garden_bridge.lock -c 'pgrep -f usb_bridge.py >/dev/null || \
    (cd /home/bennet/Gartenbewaesserung && nohup /usr/bin/python3 -u usb_bridge.py >> usb_bridge.log 2>&1 &)'
```

The watering schedule is fully managed by the APScheduler engine running inside `server.py`.

## Common Operations

### Turn a relay on/off
```bash
ssh bennet@192.168.178.55 "python3 /home/bennet/Gartenbewaesserung/garden.py on 1"
ssh bennet@192.168.178.55 "python3 /home/bennet/Gartenbewaesserung/garden.py off 1"
```

### Get ESP status
```bash
ssh bennet@192.168.178.55 "python3 /home/bennet/Gartenbewaesserung/garden.py status"
# Or directly:
mosquitto_sub -t garden/status -C 1 -W 2
```

### Watch live events
```bash
ssh bennet@192.168.178.55 "python3 /home/bennet/Gartenbewaesserung/garden.py watch"
```

### Web server management
```bash
# Check status
sudo systemctl status garden-server

# Restart
sudo systemctl restart garden-server

# View logs
tail -f /home/bennet/Gartenbewaesserung/server.log

# View API docs (local only)
curl http://localhost:8000/docs  # (if enabled)
```

### Discord bot management
```bash
sudo systemctl status garden-discord
sudo systemctl restart garden-discord
tail -f /home/bennet/Gartenbewaesserung/discord_bot.log
```

### Check bridge is running
```bash
ssh bennet@192.168.178.55 "pgrep -af usb_bridge && tail -5 /home/bennet/Gartenbewaesserung/usb_bridge.log"
```

### Restart bridge
```bash
ssh bennet@192.168.178.55 "pkill -f usb_bridge.py; sleep 1; \
    nohup python3 -u /home/bennet/Gartenbewaesserung/usb_bridge.py >> /home/bennet/Gartenbewaesserung/usb_bridge.log 2>&1 &"
```

### Kill the watering schedule
```bash
ssh bennet@192.168.178.55 "pkill -f water_schedule.py"
```

### Add a new GPIO pin
1. Wire the relay to any free GPIO (see pin table above)
2. Use `garden.py on <pin>` — no reflashing needed
3. Update `config.yaml` → `pins` section with the label
4. Restart the server: `sudo systemctl restart garden-server`
5. Update AGENTS.md pin mapping

### Check ESP serial output directly
```bash
ssh bennet@192.168.178.55 "timeout 5 cat /dev/ttyACM0 | head -20"
# Note: bridge must be stopped first to free the port
```

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| ESP stuck in `wait usb download` | Relay pulling strapping pin LOW at boot (GPIO 2) | Disconnect GPIO 2 wire, power cycle ESP |
| Bridge shows `device disconnected` | ESP crashed or cable loose | Check USB cable, power cycle ESP |
| Commands to garden.py have no effect | Bridge dead or ESP offline | Check `pgrep -af usb_bridge`, restart bridge |
| `/dev/ttyACM*` missing | ESP not connected | Check USB cable, power cycle |
| Port changed to ACM1/ACM2 | Normal after replug | Bridge auto-detects, wait 5s |
| Relay doesn't activate | RELAY_ACTIVE_LOW mismatch or 3.3V vs 5V | Check relay module logic level |
| `pip install` fails on Pi | Externally-managed Python | Use `apt install` or `--break-system-packages` |

## Cloudflare Tunnel Setup

The tunnel makes the dashboard accessible from the internet at `https://garten-bewaesserung.joancode.dev`.

**On the Pi (interactive — needs browser for OAuth):**
```bash
ssh bennet@192.168.178.55
cd /home/bennet/Gartenbewaesserung
bash cloudflared-setup.sh
```

This script will:
1. Open a Cloudflare login page (complete in your browser)
2. Create a tunnel named `garden`
3. Route DNS for `garten-bewaesserung.joancode.dev`
4. Install and start the systemd service

**After tunnel is running, set up Cloudflare Access (SSO edge auth):**
- Go to https://one.dash.cloudflare.com
- Access → Applications → Add Application → Self-hosted
- Subdomain: `garten-bewaesserung`, Domain: `joancode.dev`
- Add policy: choose identity provider (email OTP, Google, GitHub)

**Tunnel management:**
```bash
sudo systemctl status garden-tunnel
sudo systemctl restart garden-tunnel
cloudflared tunnel list
```

## Dev Machine

Project root: `C:\Users\benne\Documents\Projekte\Gartenbewässerung\`

```
esp32_relay_test/
  platformio.ini       — board config (esp32-c3-devkitm-1)
  src/main.ino         — ESP firmware v5 (dynamic GPIO)
  README.md            — ESP docs
raspi/
  garden.py            — MQTT CLI (local copy)
  water_schedule.py    — watering schedule (local copy)
  commands.sh          — raw mosquitto_pub commands
  config.example.yaml  — config template
  config.yaml          — live config (gitignored)
  config.py            — config loader
  server.py            — FastAPI server
  database.py          — SQLite layer
  scheduler.py         — schedule engine
  auth.py              — JWT auth
  discord_bot.py       — Discord bot
  requirements.txt     — Python deps
  deploy.sh            — transfer to Pi
  install.sh           — install on Pi
  static/              — web frontend
    index.html         — main dashboard
    login.html         — login page
    css/style.css      — styles
    js/app.js          — app logic
  systemd/             — service unit files
    garden-server.service
    garden-discord.service
```

## Configuration Reference (config.yaml)

```yaml
broker:
  host: localhost          # MQTT broker host
  port: 1883               # MQTT broker port

web:
  host: "0.0.0.0"          # Server bind address
  port: 8000               # Server port
  public_url: "https://garten-bewaesserung.joancode.dev"  # Used for /verify links

auth:
  jwt_secret: "..."        # JWT signing secret (change me!)
  admin_username: "admin"   # Web login username
  admin_password: "..."     # Web login password

discord:
  bot_token: "..."         # Discord bot token (from Discord Developer Portal)
  webhook_url: "..."       # Discord webhook for schedule notifications
  alert_user_id: "..."     # Discord user ID to @ping on errors

pins:
  1: "Gartenschlauch unten rechts"
  2: "Bewässerungsschlauch oben"
  3: "Hauptwasserversorgung"
  4: "Sprinkler Beet oben"
  5: "frei"
  6: "frei"
  7: "frei"

database:
  path: "garden.db"        # SQLite database file
```

## Safety Notes

- Do NOT connect 5V directly to ESP32 GPIO (3.3V only)
- GPIO 2 is a strapping pin — relay must not pull LOW during first 50ms of boot
- GPIO 0 has onboard boot button — may glitch ESP on rapid toggles
- Always turn off Hauptwasserversorgung (GPIO 3) last in any schedule
- The bridge log file grows indefinitely — rotate if needed
