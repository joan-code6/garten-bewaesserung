#!/usr/bin/env python3
"""Watering schedule: run at 20:00 via cron."""

import sys, time, json, subprocess, os

from garden import Garden

PIN_GARTENSCHLAUCH_UNTEN = 1
PIN_SPRINKLER = 2
PIN_GARTENSCHLAUCH = 3
PIN_WASSERZUFUHR = 4

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STEP_MINUTES = 20
PURGE_MINUTES = 1

WEBHOOK_URL = "https://discord.com/api/webhooks/..."
USER_ID = "YOUR_DISCORD_USER_ID"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def dc_notify(content):
    try:
        subprocess.run(
            [
                "curl",
                "-s",
                "-X",
                "POST",
                "-H",
                "Content-Type: application/json",
                "-d",
                json.dumps({"content": content}),
                WEBHOOK_URL,
            ],
            timeout=10,
            capture_output=True,
        )
    except Exception as e:
        log(f"Discord webhook fehlgeschlagen: {e}")


def dc_alert(content):
    dc_notify(f"<@{USER_ID}> {content}")


def ensure_bridge():
    try:
        result = subprocess.run(["pgrep", "-f", "usb_bridge.py"], capture_output=True)
        if result.returncode != 0:
            log("Bridge nicht aktiv, starte...")
            dc_alert("Bridge war tot, starte neu...")
            subprocess.Popen(
                ["/usr/bin/python3", "-u", os.path.join(BASE_DIR, "usb_bridge.py")],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            time.sleep(6)
            log("Bridge gestartet")
            dc_notify("Bridge gestartet")
        else:
            log("Bridge laeuft bereits")
    except Exception as e:
        log(f"Bridge check fehlgeschlagen: {e}")
        dc_alert(f"Bridge-Check fehlgeschlagen: {e}")


def run_schedule():
    errors = []

    def safe_op(label, fn, *args):
        try:
            fn(*args)
            log(label)
        except Exception as e:
            msg = f"{label} FEHLGESCHLAGEN: {e}"
            log(msg)
            errors.append(msg)
            dc_alert(msg)

    ensure_bridge()
    g = Garden()

    safe_op("Hauptwasserversorgung EIN", g.on, PIN_WASSERZUFUHR)

    safe_op("Gartenschlauch unten EIN", g.on, PIN_GARTENSCHLAUCH_UNTEN)
    log(f"Warte {STEP_MINUTES} Minuten (Gartenschlauch unten)...")
    time.sleep(STEP_MINUTES * 60)
    safe_op("Gartenschlauch unten AUS", g.off, PIN_GARTENSCHLAUCH_UNTEN)

    safe_op("Gartenschlauch oben EIN", g.on, PIN_GARTENSCHLAUCH)
    log(f"Warte {STEP_MINUTES} Minuten (Gartenschlauch oben)...")
    time.sleep(STEP_MINUTES * 60)
    safe_op("Gartenschlauch oben AUS", g.off, PIN_GARTENSCHLAUCH)

    safe_op("Sprinkler EIN", g.on, PIN_SPRINKLER)
    time.sleep(STEP_MINUTES * 60)
    safe_op("Sprinkler AUS", g.off, PIN_SPRINKLER)

    log(f"Spuelung: alle Ventile fuer {PURGE_MINUTES} Minute(n)")
    safe_op("Sprinkler EIN (Spuelung)", g.on, PIN_SPRINKLER)
    safe_op("Gartenschlauch oben EIN (Spuelung)", g.on, PIN_GARTENSCHLAUCH)
    safe_op("Gartenschlauch unten EIN (Spuelung)", g.on, PIN_GARTENSCHLAUCH_UNTEN)
    time.sleep(PURGE_MINUTES * 60)
    safe_op("Sprinkler AUS (Spuelung)", g.off, PIN_SPRINKLER)
    safe_op("Gartenschlauch oben AUS (Spuelung)", g.off, PIN_GARTENSCHLAUCH)
    safe_op("Gartenschlauch unten AUS (Spuelung)", g.off, PIN_GARTENSCHLAUCH_UNTEN)

    safe_op("Hauptwasserversorgung AUS", g.off, PIN_WASSERZUFUHR)

    if errors:
        msg = (
            "Bewaesserung abgeschlossen mit "
            + str(len(errors))
            + " Fehlern:\n"
            + "\n".join(errors)
        )
        dc_alert(msg)
    else:
        dc_notify("Bewaesserung erfolgreich abgeschlossen")
    log("Bewaesserung abgeschlossen")


if __name__ == "__main__":
    run_schedule()
