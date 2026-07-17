# Garden Irrigation System

This project waters my garden automatically. It uses an ESP32-C3, a Raspberry Pi, MQTT, and a web dashboard.

# Reviewer Instructions

Use the Discord invite link you received to join the server. Run the `/verify` command it will give you a URL. Click that URL it grants you access to my network so you can see the dashboard.

**These valves control real water in my garden. Dont fuck with them.** Look dont touch. Flipping a valve on will actually soak my plants or flood my yard. Just observe.

# How to Use

The dashboard is at [https://garten-bewaesserung.joancode.dev/](https://garten-bewaesserung.joancode.dev/). From there you can flip relays, set schedules, and see the history.

If you want CLI access, SSH into the Pi and use garden.py:

```bash
python3 garden.py on 1
python3 garden.py off 1
python3 garden.py status
python3 garden.py watch
```

To use the Discord bot, just run the slash commands in your server. `/water` to control relays, `/verify` to get web access from outside.

# Hardware

- ESP32-C3-DevKitM-1 with a 5 channel relay module
- Raspberry Pi (any model with USB)
- 5 magnetic valves, 24V AC

The ESP connects to the Pi over USB serial. The Pi runs Mosquitto as the MQTT broker and a Python bridge that forwards MQTT messages to the ESP.

# Scripts

## garden.py

```bash
from garden import GardenController
```

This is the MQTT client library. Import it in your own scripts to control relays, get status, or subscribe to events. Also works as a CLI.

## server.py

```python
from server import app
```

This is the FastAPI web server. It serves the dashboard, handles the schedule engine, and hosts the API endpoints for everything from relay control to Google Home.

## discord_bot.py

This is a Discord bot with slash commands. You can turn relays on and off, check status, list schedules, and run a schedule right now. The `/verify` command generates a one-time link that gives you 30 days of web access from your current IP.

## scheduler.py

```python
from scheduler import ScheduleEngine
```

This handles automated watering. It uses APScheduler and loads your schedules from the SQLite database. Before each run it checks the weather and skips if its raining or freezing.

## weather.py

```python
from weather import check_weather
```

Checks Open-Meteo before scheduled waterings. It will skip the watering if it rained recently, rain is forecast, or the temperature is below 2 degrees Celsius. After 3 skips in a row it forces the run anyway so nothing dries out.

## database.py

```python
from database import Database
```

SQLite wrapper for schedules and action history. Auto initializes on first import.

# Configuration

Copy `config.example.yaml` to `config.yaml`. The important sections are `broker` for MQTT, `web` for the server, `auth` for login, `discord` for the bot, `pins` for relay labels, and `weather` for skip rules.

# License

MIT
