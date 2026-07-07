#!/usr/bin/env python3
"""SQLite database layer for schedules, history, IP allowlist, and verify tokens."""

import json
import os
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import ipaddress

from config import get

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    get("database", "path", default="garden.db"),
)

_local = threading.local()


def _conn():
    """Get thread-local database connection."""
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA foreign_keys=ON")
    return _local.conn


def init_db():
    """Create tables if they don't exist."""
    db = _conn()
    db.executescript("""
        CREATE TABLE IF NOT EXISTS schedules (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            description TEXT DEFAULT '',
            enabled     INTEGER DEFAULT 1,
            cron_expr   TEXT NOT NULL DEFAULT '0 20 * * *',
            steps       TEXT NOT NULL DEFAULT '[]',
            last_run    TEXT,
            created_at  TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
            action      TEXT NOT NULL,
            pin         INTEGER,
            state       INTEGER,
            source      TEXT DEFAULT 'manual',
            schedule_id INTEGER,
            detail      TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS verify_tokens (
            token            TEXT PRIMARY KEY,
            discord_user_id  TEXT NOT NULL,
            discord_username TEXT DEFAULT '',
            created_at       TEXT NOT NULL DEFAULT (datetime('now')),
            expires_at       TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS ip_allowlist (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            ip               TEXT NOT NULL,
            discord_user_id  TEXT NOT NULL,
            discord_username TEXT DEFAULT '',
            created_at       TEXT NOT NULL DEFAULT (datetime('now')),
            expires_at       TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_history_ts ON history(timestamp DESC);
        CREATE INDEX IF NOT EXISTS idx_schedules_enabled ON schedules(enabled);
        CREATE INDEX IF NOT EXISTS idx_ip_allowlist_ip ON ip_allowlist(ip);
        CREATE INDEX IF NOT EXISTS idx_ip_allowlist_expires ON ip_allowlist(expires_at);
    """)
    db.commit()


def migrate_default_schedule():
    """Insert the default evening watering schedule if DB is empty."""
    db = _conn()
    row = db.execute("SELECT COUNT(*) FROM schedules").fetchone()
    if row[0] == 0:
        steps = [
            {"pin": 1, "duration": 1200, "label": "Gartenschlauch unten rechts"},
            {"pin": 2, "duration": 1200, "label": "Bewässerungsschlauch oben"},
            {"pin": 4, "duration": 1200, "label": "Sprinkler Beet oben"},
            {
                "type": "purge",
                "duration": 60,
                "pins": [1, 2, 4],
                "label": "Spülung alle Ventile",
            },
        ]
        db.execute(
            "INSERT INTO schedules (name, description, cron_expr, steps) VALUES (?, ?, ?, ?)",
            (
                "Abendbewässerung",
                "Tägliche Bewässerung um 20:00 Uhr",
                "0 20 * * *",
                json.dumps(steps),
            ),
        )
        # Morning watering at 08:00
        db.execute(
            "INSERT INTO schedules (name, description, cron_expr, steps) VALUES (?, ?, ?, ?)",
            (
                "Morgenbewässerung",
                "Tägliche Bewässerung um 08:00 Uhr",
                "0 8 * * *",
                json.dumps(steps),
            ),
        )
        db.commit()


# ── Schedules CRUD ────────────────────────────────────────────


def list_schedules():
    rows = (
        _conn().execute("SELECT * FROM schedules ORDER BY created_at DESC").fetchall()
    )
    return [_row_to_dict(r) for r in rows]


def get_schedule(schedule_id):
    row = (
        _conn()
        .execute("SELECT * FROM schedules WHERE id = ?", (schedule_id,))
        .fetchone()
    )
    return _row_to_dict(row) if row else None


def create_schedule(
    name, description="", cron_expr="0 20 * * *", steps=None, enabled=True
):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    db = _conn()
    cur = db.execute(
        "INSERT INTO schedules (name, description, enabled, cron_expr, steps, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, description, int(enabled), cron_expr, json.dumps(steps or []), now, now),
    )
    db.commit()
    return cur.lastrowid


def update_schedule(schedule_id, **kwargs):
    allowed = {"name", "description", "enabled", "cron_expr", "steps"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False
    if "enabled" in updates:
        updates["enabled"] = int(updates["enabled"])
    if "steps" in updates:
        updates["steps"] = json.dumps(updates["steps"])
    updates["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [schedule_id]
    db = _conn()
    db.execute(f"UPDATE schedules SET {set_clause} WHERE id = ?", values)
    db.commit()
    return True


def delete_schedule(schedule_id):
    db = _conn()
    db.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
    db.commit()


def set_last_run(schedule_id):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    db = _conn()
    db.execute(
        "UPDATE schedules SET last_run = ?, updated_at = ? WHERE id = ?",
        (now, now, schedule_id),
    )
    db.commit()


# ── History ───────────────────────────────────────────────────


def log_action(
    action, pin=None, state=None, source="manual", schedule_id=None, detail=""
):
    db = _conn()
    db.execute(
        "INSERT INTO history (action, pin, state, source, schedule_id, detail) VALUES (?, ?, ?, ?, ?, ?)",
        (action, pin, state, source, schedule_id, str(detail)),
    )
    db.commit()


def get_history(limit=100, offset=0):
    rows = (
        _conn()
        .execute(
            "SELECT * FROM history ORDER BY timestamp DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
        .fetchall()
    )
    return [_row_to_dict(r) for r in rows]


def get_history_count():
    return _conn().execute("SELECT COUNT(*) FROM history").fetchone()[0]


# ── Helpers ───────────────────────────────────────────────────


def cron_to_human(cron_expr: str) -> str:
    """Convert a 5-field cron expression to a German human-readable string."""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return cron_expr

    minute, hour, dom, month, dow = parts

    # Weekday names
    dow_names = {
        0: "Sonntag",
        1: "Montag",
        2: "Dienstag",
        3: "Mittwoch",
        4: "Donnerstag",
        5: "Freitag",
        6: "Samstag",
    }
    month_names = {
        1: "Januar",
        2: "Februar",
        3: "März",
        4: "April",
        5: "Mai",
        6: "Juni",
        7: "Juli",
        8: "August",
        9: "September",
        10: "Oktober",
        11: "November",
        12: "Dezember",
    }

    # Time part
    time_str = ""
    if hour == "*":
        if minute == "*":
            time_str = "jede Minute"
        elif minute.isdigit():
            time_str = f"jede Stunde um :{int(minute):02d}"
        else:
            time_str = f"um {minute} nach jeder Stunde"
    elif hour.isdigit():
        h = int(hour)
        if minute.isdigit():
            time_str = f"um {h:02d}:{int(minute):02d}"
        elif minute == "*":
            time_str = f"jede Minute von {h:02d}:00-{h:02d}:59"
        else:
            time_str = f"um {h:02d}:{minute}"
    else:
        time_str = f"um {minute} {hour}"

    # Day part
    day_str = ""

    # Day of week takes priority over day of month in cron
    if dow != "*":
        if "," in dow:
            days = [dow_names[int(d)] for d in dow.split(",") if d.isdigit()]
            if len(days) == 5 and set(days) == {
                "Montag",
                "Dienstag",
                "Mittwoch",
                "Donnerstag",
                "Freitag",
            }:
                day_str = "jeden Werktag"
            else:
                day_str = "jeden " + ", ".join(days)
        elif "-" in dow:
            parts_dow = dow.split("-")
            if parts_dow[0].isdigit() and parts_dow[1].isdigit():
                day_str = f"jeden Tag von {dow_names[int(parts_dow[0])]} bis {dow_names[int(parts_dow[1])]}"
            else:
                day_str = f"an Tagen {dow}"
        elif dow.isdigit():
            day_str = f"jeden {dow_names[int(dow)]}"
        else:
            day_str = f"an Tagen: {dow}"
    elif dom != "*":
        if dom.isdigit():
            day_str = f"jeden {int(dom)}."
        elif "," in dom:
            nums = [str(int(d)) for d in dom.split(",") if d.lstrip("0").isdigit()]
            day_str = f"jeden {', '.join(nums)}."
        else:
            day_str = f"am {dom}."
    else:
        # Both dom and dow are *
        day_str = "jeden Tag"

    # Month
    month_str = ""
    if month != "*":
        if month.isdigit():
            month_str = f" im {month_names[int(month)]}"
        elif "," in month:
            m_names = [month_names[int(m)] for m in month.split(",") if m.isdigit()]
            month_str = f" im {', '.join(m_names)}"
        else:
            month_str = f" in Monat {month}"

    result = f"{day_str} {time_str}{month_str}"
    return result.strip()


def _row_to_dict(row):
    d = dict(row)
    if "steps" in d and isinstance(d["steps"], str):
        try:
            d["steps"] = json.loads(d["steps"])
        except (json.JSONDecodeError, TypeError):
            pass
    d["enabled"] = bool(d.get("enabled", 1))
    if "cron_expr" in d and d["cron_expr"]:
        d["humanized"] = cron_to_human(d["cron_expr"])
    return d


# ── IP Allowlist & Verify Tokens ───────────────────────────────

VERIFY_TOKEN_HOURS = 1
IP_ALLOWLIST_DAYS = 30


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _utc_expires(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _normalize_ip(ip_str: str) -> str:
    if not ip_str:
        return ""
    try:
        return ipaddress.ip_address(ip_str).compressed
    except ValueError:
        return ip_str.strip()


def is_ip_allowed(ip: str) -> bool:
    ip = _normalize_ip(ip)
    now = _utc_now()
    row = (
        _conn()
        .execute(
            "SELECT COUNT(*) FROM ip_allowlist WHERE ip = ? AND expires_at > ?",
            (ip, now),
        )
        .fetchone()
    )
    return row[0] > 0


def generate_verify_token(discord_user_id: str, discord_username: str) -> str:
    _cleanup_expired()
    token = secrets.token_urlsafe(32)
    _conn().execute(
        "INSERT INTO verify_tokens (token, discord_user_id, discord_username, expires_at) VALUES (?, ?, ?, ?)",
        (token, str(discord_user_id), discord_username, _utc_expires(VERIFY_TOKEN_HOURS)),
    )
    _conn().commit()
    return token


def consume_verify_token(token: str, ip: str) -> tuple[bool, str, str, str]:
    """Returns (success, discord_user_id, discord_username, reason)."""
    ip = _normalize_ip(ip)
    _cleanup_expired()
    db = _conn()
    row = db.execute(
        "SELECT * FROM verify_tokens WHERE token = ? AND expires_at > ?",
        (token, _utc_now()),
    ).fetchone()
    if not row:
        existed = db.execute(
            "SELECT expires_at FROM verify_tokens WHERE token = ?", (token,)
        ).fetchone()
        if existed:
            return False, "", "", "expired"
        return False, "", "", "not_found"
    uid = row["discord_user_id"]
    uname = row["discord_username"]
    db.execute(
        "INSERT OR REPLACE INTO ip_allowlist (ip, discord_user_id, discord_username, expires_at) VALUES (?, ?, ?, ?)",
        (ip, uid, uname, _utc_expires(IP_ALLOWLIST_DAYS * 24)),
    )
    db.execute("DELETE FROM verify_tokens WHERE token = ?", (token,))
    db.commit()
    return True, uid, uname, "ok"


def _cleanup_expired():
    now = _utc_now()
    db = _conn()
    db.execute("DELETE FROM verify_tokens WHERE expires_at <= ?", (now,))
    db.execute("DELETE FROM ip_allowlist WHERE expires_at <= ?", (now,))
    db.commit()


# Auto-init on import
init_db()
migrate_default_schedule()
