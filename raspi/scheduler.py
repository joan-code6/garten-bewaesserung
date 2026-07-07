#!/usr/bin/env python3
"""Schedule engine — cron-based watering cycles via APScheduler."""

import json
import logging
import subprocess
import threading
import time
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import get
from database import get_schedule, list_schedules, log_action, set_last_run
from garden import Garden

log = logging.getLogger("garden-scheduler")

PIN_WASSERZUFUHR = 3  # main water supply — must be ON during entire cycle
PIN_MAIN = PIN_WASSERZUFUHR

_scheduler: "Scheduler | None" = None


def dc_notify(content: str):
    """Send a Discord webhook message."""
    url = get("discord", "webhook_url", default="")
    if not url:
        return
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
                url,
            ],
            timeout=10,
            capture_output=True,
        )
    except Exception as e:
        log.warning("Discord webhook failed: %s", e)


def dc_alert(content: str):
    """Send a Discord message with user ping."""
    uid = get("discord", "alert_user_id", default="")
    prefix = f"<@{uid}> " if uid else ""
    dc_notify(f"{prefix}{content}")


class Scheduler:
    def __init__(self):
        self._aps = BackgroundScheduler()
        self._jobs = {}

    def start(self):
        self._aps.start()
        self.reload_jobs()
        log.info("Scheduler started with %d jobs", len(self._jobs))

    def stop(self):
        self._aps.shutdown(wait=False)
        log.info("Scheduler stopped")

    def reload_jobs(self):
        """Reload all enabled schedules from DB."""
        for job_id in list(self._jobs.keys()):
            self._aps.remove_job(job_id)
        self._jobs.clear()

        for sched in list_schedules():
            if not sched["enabled"]:
                continue
            job_id = f"schedule_{sched['id']}"
            try:
                trigger = CronTrigger.from_crontab(sched["cron_expr"])
            except Exception as e:
                log.warning(
                    "Invalid cron '%s' for schedule %s: %s",
                    sched["cron_expr"],
                    sched["name"],
                    e,
                )
                continue
            job = self._aps.add_job(
                self._execute,
                trigger=trigger,
                args=[sched],
                id=job_id,
                name=sched["name"],
                replace_existing=True,
            )
            self._jobs[job_id] = job
            log.info("Scheduled '%s': %s", sched["name"], sched["cron_expr"])

    def _execute(self, sched: dict):
        """Entry point for APScheduler — runs in its thread pool."""
        name = sched.get("name", "Unbenannt")
        steps = sched.get("steps", [])
        sid = sched.get("id")
        log.info("Running schedule '%s' (id=%s)", name, sid)
        dc_notify(f"🕐 **{name}** gestartet")

        errors = []
        g = Garden()

        def safe_op(label, fn, *args):
            try:
                fn(*args)
                log.info("  %s", label)
            except Exception as e:
                msg = f"  {label} FEHLGESCHLAGEN: {e}"
                log.error(msg)
                errors.append(msg)

        # Turn on main water supply
        safe_op("Hauptwasserversorgung EIN", g.on, PIN_MAIN)
        log_action(
            "relay_on",
            pin=PIN_MAIN,
            state=1,
            source="schedule",
            schedule_id=sid,
            detail=name,
        )

        for step in steps:
            step_type = step.get("type", "single")

            if step_type == "purge":
                pins = step.get("pins", [])
                duration = step.get("duration", 60)
                label = step.get("label", f"Spülung {pins}")

                for p in pins:
                    safe_op(f"{label} — GPIO {p} EIN", g.on, p)
                    log_action(
                        "relay_on",
                        pin=p,
                        state=1,
                        source="schedule",
                        schedule_id=sid,
                        detail=name,
                    )

                log.info("  %s — warte %ds", label, duration)
                time.sleep(duration)

                for p in pins:
                    safe_op(f"{label} — GPIO {p} AUS", g.off, p)
                    log_action(
                        "relay_off",
                        pin=p,
                        state=0,
                        source="schedule",
                        schedule_id=sid,
                        detail=name,
                    )
            else:
                pin = step.get("pin")
                duration = step.get("duration", 1200)
                label = step.get("label", f"GPIO {pin}")

                safe_op(f"{label} EIN", g.on, pin)
                log_action(
                    "relay_on",
                    pin=pin,
                    state=1,
                    source="schedule",
                    schedule_id=sid,
                    detail=name,
                )

                log.info("  %s — warte %ds", label, duration)
                time.sleep(duration)

                safe_op(f"{label} AUS", g.off, pin)
                log_action(
                    "relay_off",
                    pin=pin,
                    state=0,
                    source="schedule",
                    schedule_id=sid,
                    detail=name,
                )

        # Turn off main water supply last
        safe_op("Hauptwasserversorgung AUS", g.off, PIN_MAIN)
        log_action(
            "relay_off",
            pin=PIN_MAIN,
            state=0,
            source="schedule",
            schedule_id=sid,
            detail=name,
        )

        # Wait 1 minute for water to drain, then ensure all valves are off
        log.info("  Warte 60s — Restwasser ablassen")
        time.sleep(60)
        all_pins = set()
        for step in steps:
            if step.get("type", "single") == "purge":
                all_pins.update(step.get("pins", []))
            else:
                pin = step.get("pin")
                if pin is not None:
                    all_pins.add(pin)
        for p in sorted(all_pins):
            safe_op(f"Sicherheit AUS GPIO {p}", g.off, p)
        safe_op("Hauptwasserversorgung AUS (Sicherheit)", g.off, PIN_MAIN)

        set_last_run(sid)

        if errors:
            dc_alert(
                f"⚠️ **{name}** abgeschlossen mit {len(errors)} Fehlern:\n"
                + "\n".join(errors)
            )
        else:
            dc_notify(f"✅ **{name}** erfolgreich abgeschlossen")
        log.info("Schedule '%s' completed", name)

    def run_adhoc(self, sched: dict):
        """Run a schedule immediately (ad-hoc), in a background thread."""
        t = threading.Thread(target=self._execute, args=[sched], daemon=True)
        t.start()


_scheduler_instance: Scheduler | None = None


def get_scheduler() -> Scheduler:
    global _scheduler_instance
    if _scheduler_instance is None:
        _scheduler_instance = Scheduler()
    return _scheduler_instance
