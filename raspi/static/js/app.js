/* ═══════════════════════════════════════════════════════════════
   Garden Irrigation Dashboard — Application Logic
   ═══════════════════════════════════════════════════════════════ */

// ── Auth ────────────────────────────────────────────────────
const TOKEN_KEY = 'garden_token';
let isLocal = false;

function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

function authHeaders() {
  const token = getToken();
  const h = { 'Content-Type': 'application/json' };
  if (token) h['Authorization'] = 'Bearer ' + token;
  return h;
}

async function api(method, path, body) {
  const opts = { method, headers: authHeaders() };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  if (r.status === 401 || r.status === 403) {
    if (!isLocal) { logout(); return null; }
  }
  if (!r.ok) {
    const txt = await r.text();
    throw new Error(txt || r.statusText);
  }
  const ct = r.headers.get('content-type') || '';
  return ct.includes('application/json') ? r.json() : r.text();
}

function logout() {
  localStorage.removeItem(TOKEN_KEY);
  window.location.href = '/login';
}

// ── Init ────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  // Capture JWT from verify redirect (?token=...)
  const params = new URLSearchParams(window.location.search);
  const urlToken = params.get('token');
  if (urlToken) {
    localStorage.setItem(TOKEN_KEY, urlToken);
    window.history.replaceState({}, '', '/app');
  }

  // Check if we're on local network (skip login)
  try {
    const r = await fetch('/api/auth/check');
    const data = await r.json();
    isLocal = data.local || data.allowlisted || data.has_token;
  } catch (e) {}

  if (!isLocal && !getToken()) {
    window.location.href = '/login';
    return;
  }

  document.getElementById('app').classList.add('visible');
  initNav();
  initWS();
  refreshRelays();
  refreshTimers();
  setInterval(updateTimerDisplay, 1000);
});

// ── Navigation ──────────────────────────────────────────────
function initNav() {
  document.querySelectorAll('#nav button').forEach(btn => {
    btn.addEventListener('click', () => {
      const page = btn.dataset.page;
      document.querySelectorAll('#nav button').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
      document.getElementById('page-' + page).classList.add('active');
      if (page === 'schedules') loadSchedules();
      if (page === 'history') loadHistory();
    });
  });
}

// ── Toast ───────────────────────────────────────────────────
function toast(msg, type) {
  const el = document.createElement('div');
  el.className = 'toast ' + (type || 'success');
  el.textContent = msg;
  document.getElementById('toasts').appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ── Relay Cards ─────────────────────────────────────────────
let relayData = { uptime: 0, relays: {} };

const TIMER_PILLS = [
  {dur: 300, label: '5m'},
  {dur: 600, label: '10m'},
  {dur: 900, label: '15m'},
  {dur: 1200, label: '20m'},
  {dur: 1800, label: '30m'},
  {dur: 3600, label: '60m'},
  {dur: 0, label: '─'},
];

let selectedDurations = {};
let timers = {};

async function refreshRelays() {
  try {
    const fresh = await api('GET', '/api/relays');
    if (!fresh) return;
    // Merge fresh data into existing relayData, preserving labels
    relayData.uptime = fresh.uptime || 0;
    Object.entries(fresh.relays || {}).forEach(([pin, info]) => {
      if (!relayData.relays[pin]) relayData.relays[pin] = {};
      relayData.relays[pin].state = info.state;
      relayData.relays[pin].label = info.label || relayData.relays[pin].label || `GPIO ${pin}`;
    });
    renderRelays();
    updateUptime();
    updateStatusDot(true);
  } catch (e) {
    updateStatusDot(false);
  }
}

function renderRelays() {
  const grid = document.getElementById('relay-grid');
  if (!relayData || !relayData.relays) {
    grid.innerHTML = '<div class="empty"><p>Keine Relais-Daten — ist der ESP32 online?</p></div>';
    return;
  }

  const relays = relayData.relays;
  grid.innerHTML = Object.entries(relays).map(([pin, info]) => {
    const on = info.state;
    const sel = selectedDurations[pin];
    const hasTimer = timers[pin] && timers[pin].remaining > 0;
    const timerActive = hasTimer && on;
    return `
      <div class="relay-card ${on ? 'on' : ''}" onclick="toggleRelay(${pin})" data-pin="${pin}">
        <div class="relay-card-header">
          <span class="relay-pin">GPIO ${pin}</span>
          <span class="relay-state ${on ? 'on' : ''}"></span>
        </div>
        <div class="relay-label">${info.label || 'GPIO ' + pin}</div>
        ${timerActive ? `
          <div class="relay-timer" data-timer="${pin}">⏱ ${fmtTime(timers[pin].remaining)}</div>
        ` : on ? `
          <div class="relay-status-text">Aktiv</div>
        ` : `
          <div class="relay-status-text">Inaktiv</div>
          <div class="relay-timer-pills">
            ${TIMER_PILLS.map(t => `
              <span class="timer-pill${sel === t.dur ? ' active' : ''}"
                    onclick="event.stopPropagation();selectTimer(${pin},${t.dur})">${t.label}</span>
            `).join('')}
          </div>
        `}
      </div>`;
  }).join('');
}

function fmtTime(secs) {
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

function selectTimer(pin, dur) {
  if (selectedDurations[pin] === dur) {
    delete selectedDurations[pin];
  } else {
    selectedDurations[pin] = dur;
  }
  renderRelays();
}

async function toggleRelay(pin) {
  const info = relayData.relays[String(pin)];
  if (!info) return;
  const newState = !info.state;
  const action = newState ? 'on' : 'off';

  const dur = newState ? (selectedDurations[pin] || 0) : 0;
  delete selectedDurations[pin];

  info.state = newState;
  if (!newState) delete timers[pin];
  renderRelays();

  toast(`GPIO ${pin} → ${newState ? 'EIN' : 'AUS'}${dur > 0 ? ` (${Math.round(dur/60)} min)` : ''}`, 'success');

  try {
    const body = dur > 0 ? {duration: dur} : {};
    const result = await api('POST', `/api/relays/${pin}/${action}`, body);
    if (result && result.timer) {
      timers[pin] = {
        remaining: result.timer.remaining,
        total: result.timer.total,
        expiresAt: Date.now() + result.timer.remaining * 1000
      };
    }
  } catch (e) {
    info.state = !newState;
    delete timers[pin];
    renderRelays();
    toast(`Fehler: ${e.message}`, 'error');
  }
}

function updateTimerDisplay() {
  const now = Date.now();
  for (const pin in timers) {
    const t = timers[pin];
    const remaining = Math.max(0, Math.floor((t.expiresAt - now) / 1000));
    t.remaining = remaining;
    const el = document.querySelector(`.relay-timer[data-timer="${pin}"]`);
    if (el) {
      el.textContent = `⏱ ${fmtTime(remaining)}`;
    }
    if (remaining <= 0) {
      delete timers[pin];
    }
  }
}

async function refreshTimers() {
  try {
    const data = await api('GET', '/api/timers');
    if (data && data.timers) {
      const now = Date.now();
      let changed = false;
      for (const [pin, t] of Object.entries(data.timers)) {
        if (t.remaining > 0) {
          timers[pin] = {
            remaining: t.remaining,
            total: t.total,
            expiresAt: now + t.remaining * 1000
          };
          changed = true;
        } else {
          delete timers[pin];
        }
      }
      if (changed) renderRelays();
    }
  } catch (e) {}
}

function updateUptime() {
  const el = document.getElementById('uptime');
  if (!relayData || relayData.uptime == null) { el.textContent = '--'; return; }
  const h = Math.floor(relayData.uptime / 3600);
  const m = Math.floor((relayData.uptime % 3600) / 60);
  el.textContent = `${h}h ${m}m`;
}

function updateStatusDot(online) {
  const dot = document.getElementById('status-dot');
  dot.className = 'dot' + (online ? '' : ' offline');
}

// ── WebSocket ───────────────────────────────────────────────
let ws = null;

function initWS() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const url = `${proto}//${location.host}/ws`;
  ws = new WebSocket(url);

  ws.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data);
      const topic = data._topic;
      delete data._topic;

      if (topic === 'garden/status') {
        relayData.uptime = data.uptime || 0;
        Object.entries(data.relays || {}).forEach(([pin, state]) => {
          if (!relayData.relays[pin]) relayData.relays[pin] = {};
          relayData.relays[pin].state = Boolean(state);
          if (!relayData.relays[pin].label) relayData.relays[pin].label = `GPIO ${pin}`;
          if (!Boolean(state)) delete timers[pin];
        });
        renderRelays();
        updateUptime();
        updateStatusDot(true);
      } else if (topic === 'garden/relay/state') {
        const pin = String(data.pin);
        const state = Boolean(data.state);
        if (relayData.relays && relayData.relays[pin]) {
          relayData.relays[pin].state = state;
        }
        if (!state) delete timers[pin];
        renderRelays();
      }
    } catch (ex) {}
  };

  ws.onopen = () => {
    refreshTimers();
  };

  ws.onclose = () => {
    updateStatusDot(false);
    setTimeout(initWS, 3000);
  };

  ws.onerror = () => updateStatusDot(false);
}

// ── Schedules ───────────────────────────────────────────────
async function loadSchedules() {
  const list = document.getElementById('schedule-list');
  try {
    const schedules = await api('GET', '/api/schedules');
    if (!schedules || schedules.length === 0) {
      list.innerHTML = '<div class="empty"><p>Keine Zeitpläne.</p><button class="btn btn-primary btn-sm" onclick="openScheduleModal()">Ersten Zeitplan erstellen</button></div>';
      return;
    }
    list.innerHTML = schedules.map(s => `
      <div class="schedule-card ${s.enabled ? '' : 'disabled'}">
        <div class="schedule-card-top">
          <span class="schedule-name">${esc(s.name)}</span>
          <span class="schedule-cron" title="${esc(s.cron_expr)}">${esc(s.humanized || s.cron_expr)}</span>
        </div>
        ${s.description ? `<div class="schedule-desc">${esc(s.description)}</div>` : ''}
        <div class="schedule-steps">${formatSteps(s.steps || [])}</div>
        <div class="schedule-actions">
          <button class="btn btn-sm btn-primary" onclick="runSchedule(${s.id})">▶ Jetzt starten</button>
          <button class="btn btn-sm" onclick="editSchedule(${s.id})">Bearbeiten</button>
          <button class="btn btn-sm btn-danger" onclick="deleteSchedule(${s.id})">Löschen</button>
        </div>
      </div>
    `).join('');
  } catch (e) {
    list.innerHTML = `<div class="empty"><p>Fehler: ${esc(e.message)}</p></div>`;
  }
}

function formatSteps(steps) {
  if (!steps.length) return 'Keine Schritte';
  return steps.map(s => {
    const mins = Math.round(s.duration / 60);
    const type = s.type === 'purge' ? '💨' : '💧';
    const label = s.label || (`GPIO ${s.pin || '?'}`);
    return `${type} ${label} (${mins} min)`;
  }).join(' → ');
}

// ── Schedule Modal ──────────────────────────────────────────
let editingScheduleId = null;
let modalSteps = [];

function openScheduleModal(schedule) {
  editingScheduleId = schedule ? schedule.id : null;
  document.getElementById('modal-title').textContent = schedule ? 'Zeitplan bearbeiten' : 'Neuer Zeitplan';
  document.getElementById('sched-name').value = schedule ? schedule.name : '';
  document.getElementById('sched-desc').value = schedule ? (schedule.description || '') : '';
  document.getElementById('sched-cron').value = schedule ? schedule.cron_expr : '0 20 * * *';
  document.getElementById('sched-enabled').checked = schedule ? schedule.enabled : true;

  modalSteps = schedule ? JSON.parse(JSON.stringify(schedule.steps || [])) : [];
  document.getElementById('modal-delete-btn').style.display = schedule ? '' : 'none';

  renderStepList();
  document.getElementById('modal-overlay').classList.add('open');
  previewCron();
}

function closeModal() {
  document.getElementById('modal-overlay').classList.remove('open');
  editingScheduleId = null;
  modalSteps = [];
}

function addStep(type) {
  if (type === 'purge') {
    modalSteps.push({ type: 'purge', pins: [], duration: 60, label: 'Spülung' });
  } else {
    modalSteps.push({ type: 'single', pin: 1, duration: 1200, label: '' });
  }
  renderStepList();
}

function removeStep(idx) {
  modalSteps.splice(idx, 1);
  renderStepList();
}

function renderStepList() {
  const container = document.getElementById('step-list');
  if (!modalSteps.length) {
    container.innerHTML = '<div style="color:var(--text-dim);font-size:.82rem;padding:.5rem 0">Keine Schritte — füge welche hinzu</div>';
    return;
  }
  container.innerHTML = modalSteps.map((s, i) => `
    <div class="step-row">
      <select class="step-type" onchange="stepTypeChange(${i}, this.value)">
        <option value="single" ${s.type !== 'purge' ? 'selected' : ''}>Einzelventil</option>
        <option value="purge" ${s.type === 'purge' ? 'selected' : ''}>Spülung (mehrere)</option>
      </select>
      ${s.type === 'purge' ? `
        <input type="text" class="step-label" value="${esc(s.pins?.join(',') || '')}" placeholder="Pins (1,2,3)" onchange="stepPinsChange(${i}, this.value)">
      ` : `
        <select onchange="stepPinChange(${i}, this.value)">
          ${[1,2,3,4,5,6,7].map(p => `<option value="${p}" ${s.pin === p ? 'selected' : ''}>GPIO ${p}</option>`).join('')}
        </select>
      `}
      <input type="number" class="step-duration" value="${s.duration}" min="1" onchange="stepDurChange(${i}, this.value)" title="Sekunden">
      <input type="text" class="step-label" value="${esc(s.label || '')}" placeholder="Bezeichnung" onchange="stepLabelChange(${i}, this.value)">
      <button class="step-remove" onclick="removeStep(${i})" title="Entfernen">×</button>
    </div>
  `).join('');
}

function stepPinChange(i, val) { modalSteps[i].pin = parseInt(val); }
function stepPinsChange(i, val) { modalSteps[i].pins = val.split(',').map(v => parseInt(v.trim())).filter(v => !isNaN(v)); }
function stepDurChange(i, val) { modalSteps[i].duration = parseInt(val) || 60; }
function stepLabelChange(i, val) { modalSteps[i].label = val; }
function stepTypeChange(i, val) {
  modalSteps[i].type = val;
  if (val === 'purge') { modalSteps[i].pins = [1, 2, 3]; delete modalSteps[i].pin; }
  else { modalSteps[i].pin = 1; delete modalSteps[i].pins; }
  renderStepList();
}

async function saveSchedule() {
  const name = document.getElementById('sched-name').value.trim();
  if (!name) { toast('Name erforderlich', 'error'); return; }
  if (!modalSteps.length) { toast('Mindestens ein Schritt erforderlich', 'error'); return; }

  const body = {
    name,
    description: document.getElementById('sched-desc').value.trim(),
    cron_expr: document.getElementById('sched-cron').value.trim() || '0 20 * * *',
    enabled: document.getElementById('sched-enabled').checked,
    steps: modalSteps.map(s => {
      const clean = { ...s };
      if (clean.type === 'purge') { delete clean.pin; } else { delete clean.pins; }
      return clean;
    })
  };

  try {
    if (editingScheduleId) {
      await api('PUT', `/api/schedules/${editingScheduleId}`, body);
      toast('Zeitplan aktualisiert');
    } else {
      await api('POST', '/api/schedules', body);
      toast('Zeitplan erstellt');
    }
    closeModal();
    loadSchedules();
  } catch (e) {
    toast(`Fehler: ${e.message}`, 'error');
  }
}

async function editSchedule(id) {
  try {
    const s = await api('GET', `/api/schedules/${id}`);
    openScheduleModal(s);
  } catch (e) {
    toast(`Fehler: ${e.message}`, 'error');
  }
}

async function deleteScheduleFromModal() {
  if (!editingScheduleId || !confirm('Zeitplan wirklich löschen?')) return;
  await deleteSchedule(editingScheduleId);
  closeModal();
}

async function deleteSchedule(id) {
  if (!confirm('Zeitplan wirklich löschen?')) return;
  try {
    await api('DELETE', `/api/schedules/${id}`);
    toast('Zeitplan gelöscht');
    loadSchedules();
  } catch (e) {
    toast(`Fehler: ${e.message}`, 'error');
  }
}

async function runSchedule(id) {
  if (!confirm('Zeitplan jetzt ausführen?')) return;
  try {
    await api('POST', `/api/schedules/${id}/run`);
    toast('Zeitplan gestartet!');
  } catch (e) {
    toast(`Fehler: ${e.message}`, 'error');
  }
}

// ── History ─────────────────────────────────────────────────
async function loadHistory() {
  const list = document.getElementById('history-list');
  try {
    const data = await api('GET', '/api/history?limit=100');
    if (!data || !data.items || data.items.length === 0) {
      list.innerHTML = '<div class="empty"><p>Kein Verlauf</p></div>';
      return;
    }
    list.innerHTML = data.items.map(h => `
      <div class="history-item">
        <span class="history-ts">${(h.timestamp || '').substring(0, 16)}</span>
        <span class="history-action">${formatAction(h.action)}</span>
        ${h.pin != null ? `<span class="history-pin">GPIO ${h.pin}</span>` : ''}
        <span class="history-detail">${esc(h.detail || h.source || '')}</span>
      </div>
    `).join('');
  } catch (e) {
    list.innerHTML = `<div class="empty"><p>Fehler: ${esc(e.message)}</p></div>`;
  }
}

function formatAction(a) {
  const map = {
    relay_on: 'EIN', relay_off: 'AUS', relay_toggle: 'UMSCHALTEN',
    schedule_created: 'Zeitplan erstellt', schedule_updated: 'Zeitplan aktualisiert',
    schedule_deleted: 'Zeitplan gelöscht', schedule_triggered: 'Zeitplan gestartet'
  };
  return map[a] || a;
}

// ── Modal backdrop click ────────────────────────────────────
document.getElementById('modal-overlay').addEventListener('click', function(e) {
  if (e.target === this) closeModal();
});

// ── Helpers ─────────────────────────────────────────────────
function esc(s) {
  if (!s) return '';
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

async function previewCron() {
  const expr = document.getElementById('sched-cron').value.trim();
  const preview = document.getElementById('cron-preview');
  if (!expr) { preview.textContent = ''; return; }
  try {
    const r = await fetch(`/api/cron/humanize?expr=${encodeURIComponent(expr)}`);
    const data = await r.json();
    preview.textContent = data.humanized || expr;
  } catch (e) {
    preview.textContent = expr;
  }
}
