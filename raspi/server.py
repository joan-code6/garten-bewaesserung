#!/usr/bin/env python3
"""FastAPI server — REST API, WebSocket, static files, scheduler."""

import asyncio
import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger

import paho.mqtt.client as mqtt
from fastapi import (
    Body,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from auth import (
    authenticate,
    create_access_token,
    decode_token,
    get_current_user,
    get_optional_user,
    is_local_ip,
    get_client_ip,
)
from config import get
from database import (
    consume_verify_token,
    create_schedule,
    cron_to_human,
    delete_schedule,
    get_history,
    get_history_count,
    get_schedule,
    is_ip_allowed,
    list_schedules,
    log_action,
    set_last_run,
    update_schedule,
)
from garden import Garden
from scheduler import get_scheduler

log = logging.getLogger("garden-server")

STATIC_DIR = "static"

# ═══════════════════════════════════════════════════════════════
# Timer Manager — auto-off for manual relay control
# ═══════════════════════════════════════════════════════════════


class TimerManager:
    def __init__(self):
        self._scheduler = BackgroundScheduler()
        self._timers: dict[int, dict] = {}
        self._lock = threading.Lock()

    def start(self):
        self._scheduler.start()

    def stop(self):
        self._scheduler.shutdown(wait=False)

    def start_timer(self, pin: int, duration: int) -> dict:
        self.cancel_timer(pin)
        run_date = datetime.now(timezone.utc) + timedelta(seconds=duration)
        job = self._scheduler.add_job(
            self._timer_fired,
            trigger=DateTrigger(run_date=run_date),
            args=[pin],
            id=f"auto_off_{pin}",
            replace_existing=True,
        )
        expires_at = time.time() + duration
        with self._lock:
            self._timers[pin] = {"job_id": job.id, "expires_at": expires_at, "duration": duration}
        log.info("Timer started for GPIO %d: %ds", pin, duration)
        return {"remaining": duration, "total": duration}

    def cancel_timer(self, pin: int):
        with self._lock:
            info = self._timers.pop(pin, None)
            if info:
                try:
                    self._scheduler.remove_job(info["job_id"])
                except Exception:
                    pass
                log.info("Timer cancelled for GPIO %d", pin)

    def _timer_fired(self, pin: int):
        log.info("Timer fired for GPIO %d — turning OFF", pin)
        with self._lock:
            self._timers.pop(pin, None)
        try:
            Garden().off(pin)
            log_action("relay_off", pin=pin, state=0, source="timer")
        except Exception as e:
            log.error("Timer auto-off failed for GPIO %d: %s", pin, e)

    def get_active_timers(self) -> dict:
        now = time.time()
        result = {}
        with self._lock:
            for pin_key, info in self._timers.items():
                remaining = max(0, int(info["expires_at"] - now))
                result[str(pin_key)] = {"remaining": remaining, "total": info["duration"]}
        return result


timer_manager = TimerManager()

# ═══════════════════════════════════════════════════════════════
# WebSocket Manager
# ═══════════════════════════════════════════════════════════════


class WSManager:
    def __init__(self):
        self._clients: list[WebSocket] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop):
        self._loop = loop

    async def add(self, ws: WebSocket):
        await ws.accept()
        self._clients.append(ws)

    def remove(self, ws: WebSocket):
        if ws in self._clients:
            self._clients.remove(ws)

    def broadcast_sync(self, data: dict):
        if self._loop:
            asyncio.run_coroutine_threadsafe(self._broadcast(data), self._loop)

    async def _broadcast(self, data: dict):
        dead = []
        for ws in self._clients:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.remove(ws)


wsman = WSManager()

# ═══════════════════════════════════════════════════════════════
# MQTT Listener (background thread)
# ═══════════════════════════════════════════════════════════════

_mqtt_client: mqtt.Client | None = None


def _on_mqtt_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode())
        payload["_topic"] = msg.topic
        wsman.broadcast_sync(payload)
    except Exception:
        pass


def _start_mqtt_listener():
    global _mqtt_client
    _mqtt_client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
    _mqtt_client.on_message = _on_mqtt_message
    broker_host = get("broker", "host", default="localhost")
    broker_port = get("broker", "port", default=1883)
    _mqtt_client.connect(broker_host, broker_port)
    _mqtt_client.subscribe("garden/relay/state")
    _mqtt_client.subscribe("garden/status")
    _mqtt_client.loop_start()
    log.info("MQTT listener started on %s:%s", broker_host, broker_port)


def _stop_mqtt_listener():
    global _mqtt_client
    if _mqtt_client:
        _mqtt_client.loop_stop()
        _mqtt_client.disconnect()
        _mqtt_client = None


# ═══════════════════════════════════════════════════════════════
# App Lifespan
# ═══════════════════════════════════════════════════════════════


@asynccontextmanager
async def lifespan(app: FastAPI):
    wsman.set_loop(asyncio.get_running_loop())
    _start_mqtt_listener()
    sched = get_scheduler()
    sched.start()
    timer_manager.start()
    log.info("Garden server started")
    yield
    timer_manager.stop()
    sched.stop()
    _stop_mqtt_listener()
    log.info("Garden server stopped")


app = FastAPI(
    title="Garden Irrigation", lifespan=lifespan, docs_url=None, redoc_url=None
)

# ═══════════════════════════════════════════════════════════════
# Auth
# ═══════════════════════════════════════════════════════════════


@app.post("/api/auth/login")
def login(body: dict):
    token = authenticate(body.get("username", ""), body.get("password", ""))
    if not token:
        raise HTTPException(401, "Invalid credentials")
    return {"token": token, "token_type": "bearer"}


@app.get("/api/auth/check")
def auth_check(request: Request):
    """Check if the request can access the API without a login prompt."""
    ip = get_client_ip(request)
    cookie_token = request.cookies.get("garden_token")
    has_token = cookie_token is not None and decode_token(cookie_token) is not None
    return {
        "local": is_local_ip(ip),
        "allowlisted": is_ip_allowed(ip),
        "has_token": has_token,
        "ip": ip,
    }


@app.get("/api/auth/gateway-token")
def gateway_token(request: Request):
    """Issue a JWT to an IP that is either local or allowlisted.
    Used by the gateway page to get a portable auth token before
    redirecting to /app (avoids IP-rotation redirect loops)."""
    ip = get_client_ip(request)
    if not is_local_ip(ip) and not is_ip_allowed(ip):
        raise HTTPException(403, "IP not authorized")
    token = create_access_token({"sub": "gateway", "src": "ip_auth"})
    return {"token": token, "token_type": "bearer"}


# ═══════════════════════════════════════════════════════════════
# IP Verify (Discord → allowlist)
# ═══════════════════════════════════════════════════════════════

VERIFY_ERROR_HTML = """\
<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Gartenbewässerung — Fehler</title>
<link rel="stylesheet" href="/static/css/style.css">
</head>
<body class="login-page">
<div class="login-card" style="text-align:center">
  <h1>❌ Fehler</h1>
  <p>{message}</p>
  <a href="/" class="btn" style="display:block;text-align:center;margin-top:1rem;padding:.7rem;background:var(--border);color:var(--text);border-radius:var(--radius-sm);text-decoration:none">Zurück</a>
</div>
</body>
</html>"""


@app.get("/api/verify")
def api_verify(request: Request, token: str = ""):
    if not token:
        return HTMLResponse(VERIFY_ERROR_HTML.format(message="Kein Token angegeben."), status_code=400)

    client_ip = get_client_ip(request)
    log.info("Verify attempt — token=%.8s... ip=%s", token, client_ip)

    already_allowed = is_ip_allowed(client_ip)

    if not already_allowed:
        success, uid, uname, reason = consume_verify_token(token, client_ip)
        if not success:
            log.warning("Verify failed — token=%.8s... ip=%s reason=%s", token, client_ip, reason)
            msgs = {
                "expired": "Der Link ist abgelaufen (gültig für 1 Stunde).<br>Erstelle einen neuen mit /verify im Discord.",
                "not_found": "Ungültiger Link — wurde evtl. bereits verwendet.<br>Erstelle einen neuen mit /verify im Discord.",
            }
            return HTMLResponse(
                VERIFY_ERROR_HTML.format(message=msgs.get(reason, "Unbekannter Fehler.")),
                status_code=403,
            )

        log.info("Verify success — ip=%s user=%s (%s)", client_ip, uname, uid)
        log_action(
            "ip_verified",
            detail=f"IP {client_ip} verified via Discord by {uname} ({uid})",
            source="discord",
        )
        display_name = uname
    else:
        log.info("Verify already authorized — ip=%s", client_ip)
        display_name = ""

    jwt_token = create_access_token({"sub": display_name or "discord-user", "src": "discord_verify"})
    return RedirectResponse(f"/app?token={jwt_token}", status_code=302)


# ═══════════════════════════════════════════════════════════════
# Relays
# ═══════════════════════════════════════════════════════════════


def _relays_from_status():
    g = Garden()
    s = g.status()
    if not s:
        raise HTTPException(503, "ESP32 offline — check bridge and USB connection")
    pins = get("pins", default={})
    relays = {}
    for p_str, state in s.get("relays", {}).items():
        p = int(p_str)
        relays[str(p)] = {
            "state": bool(state),
            "label": pins.get(p, f"GPIO {p}"),
        }
    return {"uptime": s.get("uptime", 0), "relays": relays}


@app.get("/api/relays")
def api_relays(user=Depends(get_optional_user)):
    return _relays_from_status()


@app.post("/api/relays/{pin}/on")
def api_relay_on(pin: int, body: dict = Body(default={}), user=Depends(get_optional_user)):
    Garden().on(pin)
    log_action("relay_on", pin=pin, state=1, source="web")
    result = {"ok": True, "pin": pin, "state": 1}
    duration = body.get("duration")
    if duration and isinstance(duration, (int, float)) and duration > 0:
        timer_info = timer_manager.start_timer(pin, int(duration))
        result["timer"] = timer_info
    return result


@app.post("/api/relays/{pin}/off")
def api_relay_off(pin: int, user=Depends(get_optional_user)):
    timer_manager.cancel_timer(pin)
    Garden().off(pin)
    log_action("relay_off", pin=pin, state=0, source="web")
    return {"ok": True, "pin": pin, "state": 0}


@app.get("/api/timers")
def api_timers(user=Depends(get_optional_user)):
    return {"timers": timer_manager.get_active_timers()}


@app.post("/api/relays/{pin}/toggle")
def api_relay_toggle(pin: int, user=Depends(get_optional_user)):
    g = Garden()
    g.toggle(pin)
    log_action("relay_toggle", pin=pin, source="web")
    return {"ok": True, "pin": pin}


@app.get("/api/status")
def api_status(user=Depends(get_optional_user)):
    return _relays_from_status()


# ═══════════════════════════════════════════════════════════════
# Schedules
# ═══════════════════════════════════════════════════════════════


@app.get("/api/cron/humanize")
def api_cron_humanize(expr: str = "0 20 * * *"):
    return {"expr": expr, "humanized": cron_to_human(expr)}


@app.get("/api/schedules")
def api_list_schedules(user=Depends(get_optional_user)):
    return list_schedules()


@app.get("/api/schedules/{sid}")
def api_get_schedule(sid: int, user=Depends(get_optional_user)):
    s = get_schedule(sid)
    if not s:
        raise HTTPException(404, "Schedule not found")
    return s


@app.post("/api/schedules")
def api_create_schedule(body: dict, user=Depends(get_optional_user)):
    sid = create_schedule(
        name=body["name"],
        description=body.get("description", ""),
        cron_expr=body.get("cron_expr", "0 20 * * *"),
        steps=body.get("steps", []),
        enabled=body.get("enabled", True),
    )
    log_action(
        "schedule_created", schedule_id=sid, detail=body.get("name", ""), source="web"
    )
    sched = get_scheduler()
    sched.reload_jobs()
    return {"id": sid}


@app.put("/api/schedules/{sid}")
def api_update_schedule(sid: int, body: dict, user=Depends(get_optional_user)):
    update_schedule(sid, **body)
    log_action("schedule_updated", schedule_id=sid, source="web")
    sched = get_scheduler()
    sched.reload_jobs()
    return {"ok": True}


@app.delete("/api/schedules/{sid}")
def api_delete_schedule(sid: int, user=Depends(get_optional_user)):
    delete_schedule(sid)
    log_action("schedule_deleted", schedule_id=sid, source="web")
    sched = get_scheduler()
    sched.reload_jobs()
    return {"ok": True}


@app.post("/api/schedules/{sid}/run")
def api_run_schedule(sid: int, user=Depends(get_optional_user)):
    s = get_schedule(sid)
    if not s:
        raise HTTPException(404, "Schedule not found")
    sched = get_scheduler()
    sched.run_adhoc(s)
    set_last_run(sid)
    log_action(
        "schedule_triggered", schedule_id=sid, detail=s.get("name", ""), source="web"
    )
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════
# History
# ═══════════════════════════════════════════════════════════════


@app.get("/api/history")
def api_history(limit: int = 100, offset: int = 0, user=Depends(get_optional_user)):
    return {"total": get_history_count(), "items": get_history(limit, offset)}


# ═══════════════════════════════════════════════════════════════
# WebSocket
# ═══════════════════════════════════════════════════════════════


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await wsman.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        wsman.remove(ws)
    except Exception:
        wsman.remove(ws)


# ═══════════════════════════════════════════════════════════════
# Static / SPA
# ═══════════════════════════════════════════════════════════════

try:
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
except Exception:
    pass


@app.get("/login")
@app.get("/")
async def serve_login(request: Request):
    return FileResponse(f"{STATIC_DIR}/login.html")


@app.get("/app")
async def serve_app():
    return FileResponse(f"{STATIC_DIR}/index.html")


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
    host = get("web", "host", default="0.0.0.0")
    port = get("web", "port", default=8000)
    uvicorn.run(app, host=host, port=port)
