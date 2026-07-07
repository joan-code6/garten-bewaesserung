# Garden Irrigation System

Automated garden irrigation controlled by an ESP32-C3, Raspberry Pi, MQTT, and a web dashboard.

## Overview

- **ESP32-C3-DevKitM-1** with 5-channel relay module controlling garden valves
- **Raspberry Pi** running Mosquitto MQTT broker, FastAPI web server, and USB-MQTT bridge
- **Web Dashboard** with real-time relay control, scheduling, and history
- **Discord Bot** for remote control and monitoring via slash commands
- **APScheduler** for cron-triggered watering schedules
- **Cloudflare Tunnel** for secure external access

## Structure

```
├── esp32_relay_test/     # PlatformIO project — ESP32 firmware v5
│   ├── src/main.ino      # Active firmware (dynamic GPIO, USB serial)
│   ├── src/bridge/       # ESP-NOW to MQTT bridge (legacy)
│   ├── src/garden/       # ESP-NOW garden node (legacy)
│   └── platformio.ini
├── raspi/                # Raspberry Pi server code
│   ├── garden.py         # MQTT client library + CLI
│   ├── server.py         # FastAPI web server + scheduler
│   ├── discord_bot.py    # Discord bot with slash commands
│   ├── scheduler.py      # APScheduler watering engine
│   ├── database.py       # SQLite layer
│   ├── auth.py           # JWT + IP authentication
│   ├── config.py         # Configuration loader
│   ├── config.example.yaml  # Configuration template
│   ├── requirements.txt  # Python dependencies
│   ├── static/           # Web frontend (SPA)
│   ├── systemd/          # Systemd service units
│   └── deploy.sh         # Deploy from dev machine to Pi
└── AGENTS.md             # Full system reference
```

## Hardware

- **ESP32-C3-DevKitM-1** (RISC-V microcontroller)
- **5-channel Relay Module** (active high, GPIO 1-5)
- **Raspberry Pi** (any model with USB)
- 5 magnetic valves (24V AC)

## Quick Start

### ESP32 Firmware

```bash
cd esp32_relay_test
pio run
# Flash via the Pi's USB port (see AGENTS.md for detailed instructions)
```

### Raspberry Pi Setup

Copy `config.example.yaml` to `config.yaml`, fill in your secrets, then:

```bash
cd raspi
pip3 install -r requirements.txt
python3 server.py
```

Or for a full install with systemd:

```bash
bash install.sh
```

### Configuration

See `raspi/config.example.yaml` for all options. Key sections:

- `broker` — MQTT settings
- `web` — server host/port and public URL
- `auth` — JWT secret, admin credentials
- `discord` — bot token, webhook URL, alert user ID
- `pins` — GPIO to descriptive name mapping
- `database` — SQLite path

## License

MIT
