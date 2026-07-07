#!/usr/bin/env python3
"""Discord bot with slash commands for garden irrigation control."""

import json
import logging
import os
from datetime import datetime, timezone

from apscheduler.triggers.cron import CronTrigger

import discord
from discord import app_commands

from config import get
from database import (
    generate_verify_token,
    get_history,
    get_schedule,
    list_schedules,
    set_last_run,
)
from garden import Garden
from scheduler import Scheduler, get_scheduler

log = logging.getLogger("garden-discord")

BOT_TOKEN = get("discord", "bot_token", default="")
if not BOT_TOKEN or BOT_TOKEN == "PLACEHOLDER" or BOT_TOKEN == "your-discord-bot-token":
    log.error("Discord bot token not configured in config.yaml → discord.bot_token")
    BOT_TOKEN = None

PINS_CFG = get("pins", default={})

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ═══════════════════════════════════════════════════════════════
# Autocomplete for pin numbers
# ═══════════════════════════════════════════════════════════════


async def pin_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[int]]:
    choices = []
    for p, label in PINS_CFG.items():
        p_int = int(p)
        name = f"GPIO {p} — {label}"
        if current.lower() in name.lower() or current in str(p):
            choices.append(app_commands.Choice(name=name, value=p_int))
    return choices[:25]


async def schedule_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    schedules = list_schedules()
    choices = []
    for s in schedules:
        name = s["name"]
        if current.lower() in name.lower():
            choices.append(app_commands.Choice(name=name, value=name))
    return choices[:25]


# ═══════════════════════════════════════════════════════════════
# Slash Commands
# ═══════════════════════════════════════════════════════════════


@tree.command(name="water", description="Gartenbewässerung steuern")
@app_commands.describe(
    action="Was möchtest du tun?",
    pin="GPIO-Pin (1-7)",
    schedule_name="Name des Zeitplans",
)
@app_commands.choices(
    action=[
        app_commands.Choice(name="Einschalten", value="on"),
        app_commands.Choice(name="Ausschalten", value="off"),
        app_commands.Choice(name="Umschalten", value="toggle"),
        app_commands.Choice(name="Status anzeigen", value="status"),
        app_commands.Choice(name="Zeitpläne auflisten", value="list"),
        app_commands.Choice(name="Zeitplan jetzt ausführen", value="run"),
        app_commands.Choice(name="Letzte Aktionen", value="history"),
    ]
)
async def water_command(
    interaction: discord.Interaction,
    action: str,
    pin: int | None = None,
    schedule_name: str | None = None,
):
    await interaction.response.defer()

    try:
        if action == "status":
            await _cmd_status(interaction)

        elif action in ("on", "off", "toggle"):
            if pin is None:
                await interaction.followup.send(
                    "Bitte gib einen GPIO-Pin an (1-7).", ephemeral=True
                )
                return
            await _cmd_relay(interaction, action, pin)

        elif action == "list":
            await _cmd_list(interaction)

        elif action == "run":
            if not schedule_name:
                await interaction.followup.send(
                    "Bitte gib einen Zeitplan-Namen an.", ephemeral=True
                )
                return
            await _cmd_run(interaction, schedule_name)

        elif action == "history":
            await _cmd_history(interaction)

        else:
            await interaction.followup.send(
                f"Unbekannte Aktion: {action}", ephemeral=True
            )

    except Exception as e:
        log.exception("Command error")
        await interaction.followup.send(f"❌ Fehler: {e}", ephemeral=True)


@tree.command(name="verify", description="Web-Dashboard Zugang für deine IP freischalten")
async def verify_command(interaction: discord.Interaction):
    """Generate a one-time verify link valid for 1 hour."""
    await interaction.response.defer(ephemeral=True)

    public_url = get("web", "public_url", default="http://192.168.178.55:8000")
    uid = str(interaction.user.id)
    uname = str(interaction.user)

    try:
        token = generate_verify_token(uid, uname)
    except Exception as e:
        log.exception("Verify token generation failed")
        await interaction.followup.send("❌ Fehler beim Erstellen des Verifizierungs-Links.", ephemeral=True)
        return

    link = f"{public_url.rstrip('/')}/api/verify?token={token}"
    await interaction.followup.send(
        f"🔗 **Zugang zum Garten-Dashboard freischalten:**\n\n"
        f"Klicke auf diesen Link (gültig für 1 Stunde):\n{link}\n\n"
        f"Deine IP wird danach für **30 Tage** freigeschaltet.",
        ephemeral=True,
    )


# ═══════════════════════════════════════════════════════════════
# Command handlers
# ═══════════════════════════════════════════════════════════════


async def _cmd_relay(interaction, action, pin):
    g = Garden()
    label = PINS_CFG.get(pin, f"GPIO {pin}")
    if action == "on":
        g.on(pin)
        await interaction.followup.send(f"✅ GPIO {pin} **{label}** → EINGESCHALTET")
    elif action == "off":
        g.off(pin)
        await interaction.followup.send(f"🔴 GPIO {pin} **{label}** → AUSGESCHALTET")
    elif action == "toggle":
        g.toggle(pin)
        await interaction.followup.send(f"🔄 GPIO {pin} **{label}** → UMGE SCHALTET")


async def _cmd_status(interaction):
    g = Garden()
    s = g.status()
    if not s:
        await interaction.followup.send(
            "⚠️ ESP32 antwortet nicht — ist die Bridge online?"
        )
        return

    uptime_h = s.get("uptime", 0) // 3600
    uptime_m = (s.get("uptime", 0) % 3600) // 60

    lines = [f"**🌿 Garten Status** (Uptime: {uptime_h}h {uptime_m}m)\n"]
    for p_str, state in s.get("relays", {}).items():
        p = int(p_str)
        label = PINS_CFG.get(p, f"GPIO {p}")
        icon = "🟢" if state else "⚫"
        lines.append(f"{icon} GPIO {p} — **{label}**")
    await interaction.followup.send("\n".join(lines))


async def _cmd_list(interaction):
    schedules = list_schedules()
    if not schedules:
        await interaction.followup.send("Keine Zeitpläne konfiguriert.")
        return

    lines = ["**📋 Zeitpläne:**\n"]
    for s in schedules:
        status_icon = "✅" if s["enabled"] else "⏸️"
        last = s.get("last_run", "Nie")
        if last and last != "Nie":
            last = last[:16]
        lines.append(
            f"{status_icon} **{s['name']}** — `{s['cron_expr']}` (zuletzt: {last})"
        )
    await interaction.followup.send("\n".join(lines))


async def _cmd_run(interaction, name):
    sched = None
    for s in list_schedules():
        if s["name"].lower() == name.lower():
            sched = s
            break
    if not sched:
        await interaction.followup.send(
            f"❌ Zeitplan '{name}' nicht gefunden.", ephemeral=True
        )
        return

    sch = get_scheduler()
    sch.run_adhoc(sched)
    set_last_run(sched["id"])

    from database import log_action

    log_action(
        "schedule_triggered",
        schedule_id=sched["id"],
        detail=sched["name"],
        source="discord",
    )

    await interaction.followup.send(
        f"🚀 Zeitplan **{sched['name']}** wurde gestartet!\n"
        f"Dauer: ca. {_total_duration(sched)} Minuten"
    )


async def _cmd_history(interaction):
    items = get_history(10)
    if not items:
        await interaction.followup.send("Keine Einträge im Verlauf.")
        return

    lines = ["**📜 Letzte Aktionen:**\n"]
    for h in items:
        ts = h["timestamp"][:16]
        action = h["action"]
        pin = h.get("pin", "")
        detail = h.get("detail", "")
        line = f"`{ts}` {action}"
        if pin:
            line += f" GPIO {pin}"
        if detail:
            line += f" — {detail}"
        lines.append(line)
    await interaction.followup.send("\n".join(lines))


def _total_duration(sched):
    total = 0
    for step in sched.get("steps", []):
        total += step.get("duration", 0)
    total += 10  # overhead for valve switching
    return round(total / 60)


# ═══════════════════════════════════════════════════════════════
# Dashboard (auto-updating every 60s)
# ═══════════════════════════════════════════════════════════════

import asyncio

_dashboard_messages: dict[int, int] = {}  # channel_id → message_id
_dashboard_lock = asyncio.Lock()
_dashboard_task: asyncio.Task | None = None

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_DASHBOARD_FILE = os.path.join(_SCRIPT_DIR, "dashboard_state.json")


def _load_dashboards():
    """Restore persisted dashboard message IDs from disk."""
    global _dashboard_messages
    try:
        if os.path.exists(_DASHBOARD_FILE):
            with open(_DASHBOARD_FILE, "r") as f:
                raw = json.load(f)
            _dashboard_messages = {int(k): int(v) for k, v in raw.items()}
            log.info("Loaded %d dashboard(s) from disk", len(_dashboard_messages))
    except Exception as e:
        log.warning("Failed to load dashboard state: %s", e)


def _save_dashboards():
    """Persist dashboard message IDs to disk."""
    try:
        serializable = {str(k): int(v) for k, v in _dashboard_messages.items()}
        with open(_DASHBOARD_FILE, "w") as f:
            json.dump(serializable, f)
    except Exception as e:
        log.warning("Failed to save dashboard state: %s", e)


def _make_embed() -> discord.Embed:
    now = datetime.now(timezone.utc)
    g = Garden()
    status = g.status()

    online = status is not None
    relays = status.get("relays", {}) if status else {}
    uptime_s = status.get("uptime", 0) if status else 0
    uptime_str = f"{uptime_s // 3600}h {(uptime_s % 3600) // 60}m"

    color = 0x2D7D46 if online else 0xED4245
    embed = discord.Embed(
        title="🌿 Gartenbewässerung",
        color=color,
        timestamp=now,
    )

    status_line = f"🟢 Online — {uptime_str}" if online else "🔴 Offline"
    embed.description = status_line

    if relays:
        lines = []
        for p_str, state in sorted(relays.items(), key=lambda x: int(x[0])):
            label = PINS_CFG.get(int(p_str), f"GPIO {p_str}")
            led = "🟢" if state else "⚫"
            lines.append(f"{led} {label}")
        embed.add_field(name="Relais", value="\n".join(lines), inline=False)
    else:
        embed.add_field(name="Relais", value="Keine Daten", inline=False)

    schedules = list_schedules()
    next_lines = []
    for s in schedules:
        if not s["enabled"]:
            continue
        try:
            trigger = CronTrigger.from_crontab(s["cron_expr"])
            nrt = trigger.get_next_fire_time(None, now)
            if nrt:
                local_tz = now.astimezone().tzinfo
                nrt_local = nrt.astimezone(local_tz)
                delta = nrt_local.replace(tzinfo=None) - now.astimezone(
                    local_tz
                ).replace(tzinfo=None)
                h, rem = divmod(int(delta.total_seconds()), 3600)
                m = rem // 60
                countdown = f"in {h}h {m}m" if h > 0 else f"in {m}m"
                next_lines.append(
                    f"**{s['name']}** → {nrt_local.strftime('%H:%M')} ({countdown})"
                )
        except Exception:
            pass

    if next_lines:
        embed.add_field(
            name="⏰ Nächste Bewässerung",
            value="\n".join(next_lines),
            inline=False,
        )
    elif schedules:
        embed.add_field(
            name="⏰ Nächste Bewässerung",
            value="Keine aktiven Zeitpläne",
            inline=False,
        )

    items = get_history(3)
    if items:
        h = items[0]
        ts = h["timestamp"][11:16]
        action = h["action"]
        detail = h.get("detail", "")
        pin = h.get("pin", "")
        desc = f"`{ts}` {action}"
        if pin:
            desc += f" GPIO {pin}"
        if detail:
            desc += f" — {detail}"
        embed.add_field(name="📋 Letzte Aktion", value=desc, inline=False)

    return embed


async def _refresh_dashboards():
    loop = asyncio.get_running_loop()
    embed = await loop.run_in_executor(None, _make_embed)
    async with _dashboard_lock:
        dead = []
        for cid, mid in list(_dashboard_messages.items()):
            try:
                channel = client.get_channel(cid)
                if channel:
                    msg = await channel.fetch_message(mid)
                    await msg.edit(embed=embed)
            except (discord.NotFound, discord.Forbidden):
                dead.append(cid)
            except Exception as e:
                log.debug("Dashboard update: %s", e)
        for cid in dead:
            del _dashboard_messages[cid]
        if dead:
            _save_dashboards()


async def _dashboard_loop():
    while True:
        await asyncio.sleep(60)
        try:
            await _refresh_dashboards()
        except Exception as e:
            log.warning("Dashboard loop: %s", e)


@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    content = message.content.strip()

    if content == "!install-garten-dashboard":
        loop = asyncio.get_running_loop()
        embed = await loop.run_in_executor(None, _make_embed)

        async with _dashboard_lock:
            existing_id = _dashboard_messages.get(message.channel.id)
            if existing_id:
                try:
                    existing_msg = await message.channel.fetch_message(existing_id)
                    await existing_msg.edit(embed=embed)
                    return
                except discord.NotFound:
                    pass

            msg = await message.channel.send(embed=embed)
            _dashboard_messages[message.channel.id] = msg.id
            _save_dashboards()
            log.info(
                "Dashboard installed in #%s by %s", message.channel, message.author
            )


# ═══════════════════════════════════════════════════════════════
# Events
# ═══════════════════════════════════════════════════════════════


@client.event
async def on_ready():
    await tree.sync()
    log.info("Discord bot ready as %s — %d guilds", client.user, len(client.guilds))
    global _dashboard_task
    _load_dashboards()
    if _dashboard_task is None:
        _dashboard_task = client.loop.create_task(_dashboard_loop())


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("ERROR: Discord bot token not set. Edit config.yaml → discord.bot_token")
        exit(1)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    client.run(BOT_TOKEN)
