# =============================================================================
# web_server.py - Flask Web Server for Phone Access
# =============================================================================
# Serves a mobile-friendly dashboard that phones can access by connecting to
# the SignalKit WiFi hotspot and navigating to http://192.168.4.1:5000
#
# Endpoints:
#   GET  /              - Live dashboard (real-time updates via SSE)
#   GET  /settings      - Settings page (edit config from phone browser)
#   GET  /update        - OTA update page (pull latest code from git)
#   GET  /api/data      - JSON snapshot of all current OBD2 data
#   GET  /api/stream    - SSE event stream for live dashboard updates
#   GET  /api/dtcs      - JSON list of active DTC codes
#   GET  /api/status    - Connection health check
#   GET  /api/settings  - JSON of all editable settings + current values
#   POST /api/settings  - Save one or more settings (JSON body)
#   POST /api/update    - Trigger a git pull OTA update
#
# Requires: flask (pip install flask)
# =============================================================================

import logging
import platform
import subprocess
import threading
import time
import os
import json

from flask import Flask, Response, jsonify, redirect, render_template_string, request

import config
import obd_reader

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.logger.setLevel(logging.WARNING)

# ---------------------------------------------------------------------------
# Shared HTML head (Tailwind + dark theme config)
# ---------------------------------------------------------------------------
SHARED_HEAD = """
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="theme-color" content="#0a0a0a">
  <link rel="manifest" href="/manifest.json">
  <link rel="icon" href="/icon.svg" type="image/svg+xml">
  <link rel="apple-touch-icon" href="/icon-180.svg">
  <script src="/static/tailwind.js"></script>
  <script>
  tailwind.config = {
    darkMode: 'class',
    theme: {
      extend: {
        colors: {
          sk: { bg: '#0a0a0a', good: '#22c55e', warn: '#f59e0b', danger: '#ef4444' },
          acc: '{{ accent_hex }}'
        }
      }
    }
  };
  </script>
  <style type="text/tailwindcss">
    @layer base {
      :root { --accent: {{ accent_hex }}; }
      body {
        background: #0a0a0a; color: #ffffff; min-height: 100vh;
        font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', Roboto, sans-serif;
        -webkit-font-smoothing: antialiased;
      }
    }
    @layer components {
      .clr-good { color: #22c55e !important; }
      .clr-warn { color: #f59e0b !important; }
      .clr-danger { color: #ef4444 !important; }
    }
  </style>
"""

# ---------------------------------------------------------------------------
# Dashboard HTML
# ---------------------------------------------------------------------------

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en" class="dark" style="background:#0a0a0a">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <meta name="theme-color" content="#0a0a0a">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <title>SignalKit</title>
  """ + SHARED_HEAD + """
</head>
<body>
  <!-- Safety Disclaimer (shown once per device) -->
  <div id="disclaimer" class="fixed inset-0 z-[100] bg-black/90 backdrop-blur-sm flex items-center justify-center p-6" style="display:none">
    <div class="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 max-w-sm w-full text-center">
      <div class="w-12 h-12 mx-auto mb-3 rounded-full bg-amber-500/15 flex items-center justify-center">
        <svg class="w-6 h-6 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"/></svg>
      </div>
      <h2 class="text-lg font-bold mb-2">Drive Safely</h2>
      <p class="text-sm text-zinc-400 leading-relaxed mb-5">SignalKit is for informational purposes only. Do not interact with this device while driving. The driver is responsible for safe vehicle operation at all times.</p>
      <button onclick="dismissDisclaimer()" class="w-full bg-acc text-white font-bold py-2.5 rounded-xl hover:opacity-90 transition-opacity text-sm">I Understand</button>
    </div>
  </div>
  <script>
    function dismissDisclaimer() {
      localStorage.setItem('signalkit_disclaimer', '1');
      document.getElementById('disclaimer').style.display = 'none';
    }
    if (!localStorage.getItem('signalkit_disclaimer')) {
      document.getElementById('disclaimer').style.display = 'flex';
    }
  </script>

  <!-- Header -->
  <div class="flex justify-between items-center px-4 py-2.5 bg-zinc-900 border-b border-zinc-800 sticky top-0 z-50">
    <h1 class="text-sm font-bold tracking-widest flex items-center gap-2">
      <span class="w-2 h-2 bg-acc rounded-full shadow-[0_0_8px_var(--accent)]"></span>SIGNALKIT
    </h1>
    <nav class="flex gap-0.5 bg-zinc-800 rounded-lg p-0.5">
      <a href="/" class="text-xs font-semibold px-3 py-1 rounded-md bg-acc text-white">Dashboard</a>
      <a href="/settings" class="text-xs font-semibold px-3 py-1 rounded-md text-zinc-400 hover:text-white">Settings</a>
      <a href="/diagnostics" class="text-xs font-semibold px-3 py-1 rounded-md text-zinc-400 hover:text-white">Diag</a>
      <a href="/dev" class="text-xs font-semibold px-3 py-1 rounded-md text-zinc-400 hover:text-white">Dev</a>
    </nav>
  </div>

  <!-- Status bar -->
  <div class="flex items-center gap-2 px-4 h-8 bg-zinc-900 border-b border-zinc-800">
    <span id="status-dot" class="w-[7px] h-[7px] rounded-full bg-red-500 shrink-0 transition-all"></span>
    <span id="status-text" class="text-xs text-zinc-500">Connecting...</span>
    <span id="sse-badge" class="ml-auto text-[0.58rem] font-bold px-2 py-0.5 rounded bg-red-500/10 text-red-400">POLLING</span>
  </div>

  <!-- Trip Computer -->
  <div class="flex items-center justify-between px-4 h-9 bg-zinc-900/50 border-b border-zinc-800 text-xs text-zinc-500">
    <span class="font-semibold tracking-wider uppercase text-[0.6rem]" style="color:var(--accent)">Trip</span>
    <div class="flex items-center gap-4 tabular-nums">
      <span id="trip-time">--:--</span>
      <span id="trip-dist">-- mi</span>
      <span id="trip-avg-speed">-- mph</span>
      <span id="trip-avg-mpg">-- mpg</span>
    </div>
  </div>

  <!-- Dashboard -->
  <div class="p-3 flex flex-col gap-2.5">
    <!-- Hero row -->
    <div class="grid grid-cols-2 gap-2.5">
      <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4 text-center">
        <div class="text-[0.65rem] font-semibold tracking-widest uppercase text-zinc-500 mb-2">RPM</div>
        <div class="text-[3.2rem] font-extrabold leading-none tabular-nums" id="val-rpm">---</div>
        <div class="h-1.5 bg-zinc-800 rounded-full overflow-hidden mt-2.5">
          <div class="h-full rounded-full bg-gradient-to-r from-acc to-acc/60 transition-all duration-500" id="rpm-bar" style="width:0%"></div>
        </div>
      </div>
      <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4 text-center">
        <div class="text-[0.65rem] font-semibold tracking-widest uppercase text-zinc-500 mb-2">Speed</div>
        <div class="text-[3.2rem] font-extrabold leading-none tabular-nums" id="val-speed">---</div>
        <div class="text-xs text-zinc-500 mt-1 font-medium" id="unit-speed">{{ 'km/h' if units_speed == 'kmh' else 'MPH' }}</div>
      </div>
    </div>

    <!-- Metrics row -->
    <div class="grid grid-cols-{{ layout_metrics|length }} gap-2.5 max-[440px]:grid-cols-2">
      {% for card in layout_metrics %}
      <div class="dcard bg-zinc-900 border border-zinc-800 rounded-xl p-3 text-center transition-opacity" data-card="{{ card }}">
        <div class="text-[0.65rem] font-semibold tracking-widest uppercase text-zinc-500 mb-2">{{ cards[card].label }}</div>
        <div class="text-2xl font-bold tabular-nums transition-colors" id="{{ cards[card].val_id }}">{{ cards[card].default }}</div>
        {% if cards[card].unit %}<div class="text-xs text-zinc-500 mt-1">{{ cards[card].unit }}</div>{% endif %}
        {% if cards[card].extra_id %}<div class="text-xs text-zinc-500 mt-1" id="{{ cards[card].extra_id }}">---</div>{% endif %}
        {% if cards[card].warn_id %}<div class="min-h-[14px] mt-1" id="{{ cards[card].warn_id }}"></div>{% endif %}
      </div>
      {% endfor %}
    </div>

    <!-- Secondary row -->
    <div class="grid grid-cols-{{ layout_slow|length }} gap-2.5 max-[440px]:grid-cols-2">
      {% for card in layout_slow %}
      <div class="dcard bg-zinc-900 border border-zinc-800 rounded-xl p-3 text-center transition-opacity" data-card="{{ card }}">
        <div class="text-[0.65rem] font-semibold tracking-widest uppercase text-zinc-500 mb-2">{{ cards[card].label }}</div>
        <div class="text-xl font-bold tabular-nums transition-colors" id="{{ cards[card].val_id }}">{{ cards[card].default }}</div>
        {% if cards[card].unit %}<div class="text-xs text-zinc-500 mt-1">{{ cards[card].unit }}</div>{% endif %}
        {% if cards[card].extra_id %}<div class="text-xs text-zinc-500 mt-1" id="{{ cards[card].extra_id }}">---</div>{% endif %}
        {% if cards[card].warn_id %}<div class="min-h-[14px] mt-1" id="{{ cards[card].warn_id }}"></div>{% endif %}
      </div>
      {% endfor %}
    </div>

    <!-- DTC section -->
    <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-3">
      <div class="text-[0.65rem] font-semibold tracking-widest uppercase text-zinc-500 mb-2">Fault Codes</div>
      <div id="dtc-list"><span class="text-sm text-emerald-500">No active fault codes</span></div>
    </div>
  </div>

  <!-- Footer -->
  <div class="text-center py-4 text-xs text-zinc-600 border-t border-zinc-800">
    SignalKit v{{ version }} &middot; <a href="/settings" class="text-zinc-400 hover:text-acc">Settings</a> &middot; {{ ip }}:{{ port }}
  </div>

  <script>
    const REDLINE = {{ redline }};
    const OVERHEAT_C = {{ overheat_c }};
    const LOW_V = {{ low_v }};
    const UNITS_SPEED = '{{ units_speed }}';
    const UNITS_TEMP = '{{ units_temp }}';
    let pollTimer = null;

    // PID support detection — fade unsupported cards after connection
    const _pidMap = {
      coolant: 'coolant_temp', battery: 'battery_voltage', throttle: 'throttle',
      load: 'engine_load', iat: 'intake_air_temp', oil: 'oil_temp',
      fuel_trim: 'short_fuel_trim_1', mpg: 'mpg'
    };
    const _pidSeen = {};
    let _connUpdates = 0;
    function checkPidSupport(d) {
      if (!d.connected) { _connUpdates = 0; return; }
      _connUpdates++;
      for (const [card, key] of Object.entries(_pidMap)) {
        if (d[key] !== null && d[key] !== undefined) _pidSeen[card] = true;
      }
      if (_connUpdates >= 8) {
        document.querySelectorAll('.dcard').forEach(el => {
          const id = el.dataset.card;
          if (id && !_pidSeen[id]) {
            el.style.opacity = '0.3';
            const valEl = el.querySelector('[id^="val-"]');
            if (valEl && valEl.textContent === '---') valEl.textContent = 'N/A';
          } else if (id) {
            el.style.opacity = '1';
          }
        });
      }
    }

    function fmt(val, dec=0, fb='---') {
      return (val === null || val === undefined) ? fb : Number(val).toFixed(dec);
    }
    function toF(c) { return c * 9/5 + 32; }
    function toKmh(mph) { return mph * 1.60934; }
    function convSpeed(v) { return UNITS_SPEED === 'kmh' ? toKmh(v) : v; }
    function convTemp(v) { return UNITS_TEMP === 'F' ? toF(v) : v; }
    function setColor(el, cls) {
      el.className = el.className.replace(/clr-\\w+/g, '').trim();
      if (cls) el.classList.add(cls);
    }

    function applyData(d) {
      checkPidSupport(d);

      const dot = document.getElementById('status-dot');
      dot.style.background = d.connected ? '#22c55e' : '#ef4444';
      dot.style.boxShadow = d.connected ? '0 0 6px #22c55e' : 'none';
      document.getElementById('status-text').textContent = d.status || '';

      // RPM
      const rpmEl = document.getElementById('val-rpm');
      rpmEl.textContent = d.rpm !== null ? d.rpm.toLocaleString() : '---';
      const ratio = d.rpm ? Math.min(1, d.rpm / REDLINE) : 0;
      const bar = document.getElementById('rpm-bar');
      bar.style.width = (ratio * 100) + '%';
      if (ratio >= 0.88) {
        bar.className = 'h-full rounded-full bg-gradient-to-r from-amber-500 to-red-500 transition-all duration-500';
        setColor(rpmEl, 'clr-danger');
      } else if (ratio >= 0.7) {
        bar.className = 'h-full rounded-full bg-gradient-to-r from-acc to-amber-500 transition-all duration-500';
        setColor(rpmEl, '');
      } else {
        bar.className = 'h-full rounded-full bg-gradient-to-r from-acc to-acc/60 transition-all duration-500';
        setColor(rpmEl, '');
      }

      document.getElementById('val-speed').textContent =
        d.speed !== null ? fmt(convSpeed(d.speed), 0) : '---';
      document.getElementById('val-throttle').textContent = fmt(d.throttle, 0);
      document.getElementById('val-load').textContent = fmt(d.engine_load, 0);
      document.getElementById('val-iat').textContent =
        d.intake_air_temp !== null ? fmt(convTemp(d.intake_air_temp), 0) : '---';

      // Coolant
      const cEl = document.getElementById('val-coolant');
      const wc = document.getElementById('warn-coolant');
      cEl.textContent = d.coolant_temp !== null ? fmt(convTemp(d.coolant_temp), 0) : '---';
      if (d.coolant_temp >= OVERHEAT_C) {
        setColor(cEl, 'clr-danger');
        wc.innerHTML = '<span class="inline-block bg-red-500/20 text-red-400 text-[0.6rem] font-bold px-2 py-0.5 rounded">OVERHEAT</span>';
      } else if (d.coolant_temp >= 95) {
        setColor(cEl, 'clr-warn');
        wc.innerHTML = '<span class="inline-block bg-amber-500/20 text-amber-400 text-[0.6rem] font-bold px-2 py-0.5 rounded">HIGH</span>';
      } else {
        setColor(cEl, 'clr-good'); wc.innerHTML = '';
      }

      // Battery
      const bEl = document.getElementById('val-battery');
      const wb = document.getElementById('warn-battery');
      bEl.textContent = fmt(d.battery_voltage, 2);
      if (d.battery_voltage !== null && d.battery_voltage < LOW_V - 0.5) {
        setColor(bEl, 'clr-danger');
        wb.innerHTML = '<span class="inline-block bg-red-500/20 text-red-400 text-[0.6rem] font-bold px-2 py-0.5 rounded">CRITICAL</span>';
      } else if (d.battery_voltage !== null && d.battery_voltage < LOW_V) {
        setColor(bEl, 'clr-warn');
        wb.innerHTML = '<span class="inline-block bg-amber-500/20 text-amber-400 text-[0.6rem] font-bold px-2 py-0.5 rounded">LOW</span>';
      } else {
        setColor(bEl, 'clr-good'); wb.innerHTML = '';
      }

      // Oil
      const oEl = document.getElementById('val-oil');
      oEl.textContent = d.oil_temp !== null ? fmt(convTemp(d.oil_temp), 0) : 'N/A';
      setColor(oEl, d.oil_temp >= 130 ? 'clr-danger' : d.oil_temp >= 115 ? 'clr-warn' : '');

      // Fuel trim
      if (d.short_fuel_trim_1 !== null) {
        const s = d.short_fuel_trim_1, l = d.long_fuel_trim_1;
        const stEl = document.getElementById('val-stft');
        stEl.textContent = 'S: ' + (s >= 0 ? '+' : '') + s.toFixed(1) + '%';
        setColor(stEl, Math.abs(s) > 10 ? 'clr-warn' : '');
        if (l !== null)
          document.getElementById('val-ltft').textContent =
            'L: ' + (l >= 0 ? '+' : '') + l.toFixed(1) + '%';
      } else {
        document.getElementById('val-stft').textContent = '---';
        document.getElementById('val-ltft').textContent = '---';
      }

      // MPG
      const mpgEl = document.getElementById('val-mpg');
      if (d.mpg !== null && d.mpg !== undefined) {
        mpgEl.textContent = Number(d.mpg).toFixed(1);
        setColor(mpgEl, d.mpg >= 25 ? 'clr-good' : d.mpg >= 15 ? '' : 'clr-warn');
      } else {
        mpgEl.textContent = '---'; setColor(mpgEl, '');
      }

      // Trip computer
      if (d.trip && d.trip.active) {
        const s = d.trip.elapsed_s;
        const h = Math.floor(s / 3600);
        const m = Math.floor((s % 3600) / 60);
        document.getElementById('trip-time').textContent =
          h > 0 ? h + ':' + String(m).padStart(2, '0') : m + 'm';
        document.getElementById('trip-dist').textContent =
          d.trip.distance_mi.toFixed(1) + ' mi';
        document.getElementById('trip-avg-speed').textContent =
          d.trip.avg_speed_mph.toFixed(0) + ' mph';
        document.getElementById('trip-avg-mpg').textContent =
          d.trip.avg_mpg > 0 ? d.trip.avg_mpg.toFixed(1) + ' mpg' : '-- mpg';
      }

      // DTCs
      const dtcList = document.getElementById('dtc-list');
      if (!d.dtcs || !d.dtcs.length) {
        dtcList.innerHTML = '<span class="text-sm text-emerald-500">No active fault codes</span>';
      } else {
        dtcList.innerHTML = d.dtcs.map(dtc =>
          `<div class="flex items-center gap-3 bg-red-500/10 border border-red-500/15 rounded-lg p-2 mb-1.5 last:mb-0">
            <span class="bg-red-500/20 text-red-400 text-xs font-bold font-mono px-2 py-0.5 rounded">${dtc.code}</span>
            <span class="text-sm text-zinc-400">${dtc.description}</span>
          </div>`).join('');
      }
    }

    // --- SSE with fallback to polling ---
    function startSSE() {
      const badge = document.getElementById('sse-badge');
      const es = new EventSource('/api/stream');
      es.onopen = function() {
        badge.textContent = 'LIVE';
        badge.className = 'ml-auto text-[0.58rem] font-bold px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400';
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
      };
      es.addEventListener('data', function(e) {
        try { applyData(JSON.parse(e.data)); } catch(err) {}
      });
      es.onerror = function() {
        badge.textContent = 'POLLING';
        badge.className = 'ml-auto text-[0.58rem] font-bold px-2 py-0.5 rounded bg-red-500/10 text-red-400';
        es.close();
        startPolling();
        setTimeout(startSSE, 10000);
      };
    }

    async function pollOnce() {
      try { applyData(await fetch('/api/data').then(r => r.json())); } catch(e) {}
    }
    function startPolling() { if (!pollTimer) pollTimer = setInterval(pollOnce, 1000); }

    pollOnce();
    startSSE();
  </script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# Settings HTML
# ---------------------------------------------------------------------------

SETTINGS_HTML = """<!DOCTYPE html>
<html lang="en" class="dark" style="background:#0a0a0a">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
  <meta name="theme-color" content="#0a0a0a">
  <title>SignalKit Settings</title>
  """ + SHARED_HEAD + """
</head>
<body>
  <!-- Header -->
  <div class="flex justify-between items-center px-4 py-2.5 bg-zinc-900 border-b border-zinc-800 sticky top-0 z-50">
    <h1 class="text-sm font-bold tracking-widest flex items-center gap-2">
      <span class="w-2 h-2 bg-acc rounded-full shadow-[0_0_8px_var(--accent)]"></span>SIGNALKIT
    </h1>
    <nav class="flex gap-0.5 bg-zinc-800 rounded-lg p-0.5">
      <a href="/" class="text-xs font-semibold px-3 py-1 rounded-md text-zinc-400 hover:text-white">Dashboard</a>
      <a href="/settings" class="text-xs font-semibold px-3 py-1 rounded-md bg-acc text-white">Settings</a>
      <a href="/diagnostics" class="text-xs font-semibold px-3 py-1 rounded-md text-zinc-400 hover:text-white">Diag</a>
      <a href="/dev" class="text-xs font-semibold px-3 py-1 rounded-md text-zinc-400 hover:text-white">Dev</a>
    </nav>
  </div>

  <div class="max-w-[600px] mx-auto p-4">

    <div id="restart-banner" class="hidden bg-amber-500/10 border border-amber-500/25 text-amber-400 p-3 text-sm font-medium mb-3 rounded-xl flex justify-between items-center gap-3">
      <span>Some changes require a restart to take effect.</span>
      <button type="button" onclick="restartApp()" id="restart-btn"
        class="bg-amber-500 text-black font-bold text-xs px-3 py-1.5 rounded-lg shrink-0 hover:opacity-85">Restart Now</button>
    </div>

    <!-- Tabs -->
    <div class="flex gap-0.5 bg-zinc-900 border border-zinc-800 rounded-xl p-1 mb-4" id="settings-tabs">
      {% for group in groups %}
      <button type="button" onclick="switchTab('{{ group }}')" data-tab="{{ group }}"
        class="flex-1 text-[0.65rem] font-semibold px-1.5 py-2 rounded-lg text-center leading-tight transition-all
          {% if loop.first %}bg-acc text-white shadow-md{% else %}text-zinc-400 hover:text-zinc-200{% endif %}">{{ tab_labels.get(group, group) }}</button>
      {% endfor %}
    </div>

    <!-- Tab panels -->
    {% for group in groups %}
    <div class="tab-panel {% if not loop.first %}hidden{% endif %}" data-panel="{{ group }}">
      {% for key, s in settings.items() %}
        {% if s.group == group %}

          {% if key in list_settings %}
          <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4 mb-2.5" id="field-{{ key }}">
            <div class="flex justify-between items-center mb-2.5">
              <label class="text-sm font-medium">{{ s.label }}</label>
              <button type="button" onclick="saveListSetting('{{ key }}')"
                class="bg-acc text-white font-bold text-xs px-4 py-2 rounded-lg hover:opacity-90">Save</button>
            </div>
            <input type="hidden" id="input-{{ key }}" value="{{ s.value }}"
              data-key="{{ key }}" data-restart="{{ 'true' if s.restart else 'false' }}">
            <div id="list-{{ key }}"></div>
            <div class="flex gap-2 mt-2 items-center">
              <select id="add-select-{{ key }}"
                class="flex-1 bg-black/30 border border-zinc-700 text-zinc-100 text-sm px-3 py-2 rounded-lg capitalize focus:outline-none focus:border-acc">
                {% for cid in all_card_ids %}
                <option value="{{ cid }}">{{ cid }}</option>
                {% endfor %}
              </select>
              <button type="button" onclick="addCardItem('{{ key }}')"
                class="bg-acc text-white font-bold text-sm px-3 py-2 rounded-lg hover:opacity-90">+ Add</button>
            </div>
            {% if s.description %}<div class="text-xs text-zinc-500 mt-2 leading-relaxed">{{ s.description }}</div>{% endif %}
            <div class="text-xs font-medium mt-1.5 min-h-[16px]" id="fb-{{ key }}"></div>
          </div>

          {% elif s.type == 'select' %}
          <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4 mb-2.5" id="field-{{ key }}">
            <div class="flex justify-between items-center gap-2.5 mb-3">
              <label class="text-sm font-medium flex-1">{{ s.label }}</label>
              {% if s.restart %}<span class="text-[0.58rem] font-bold text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded shrink-0">RESTART</span>{% endif %}
            </div>
            <input type="hidden" id="input-{{ key }}" value="{{ s.value }}"
              data-key="{{ key }}" data-restart="{{ 'true' if s.restart else 'false' }}">
            <div class="flex bg-zinc-800/60 rounded-lg p-0.5 border border-zinc-700/50" id="seg-{{ key }}">
              {% for opt_val, opt_label in s.options %}
              <button type="button"
                onclick="pickSegment('{{ key }}','{{ opt_val }}')"
                data-val="{{ opt_val }}"
                class="flex-1 text-sm font-semibold py-2 rounded-md transition-all
                  {% if s.value|string|lower == opt_val|string|lower or (s.value == true and opt_val == '1') or (s.value == false and opt_val == '0') %}
                    bg-acc text-white shadow-md
                  {% else %}
                    text-zinc-400 hover:text-zinc-200
                  {% endif %}">{{ opt_label }}</button>
              {% endfor %}
            </div>
            {% if s.description %}<div class="text-xs text-zinc-500 mt-2 leading-relaxed">{{ s.description }}</div>{% endif %}
            <div class="text-xs font-medium mt-1.5 min-h-[16px]" id="fb-{{ key }}"></div>
          </div>

          {% elif s.type == 'bt_mac' %}
          <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4 mb-2.5" id="field-{{ key }}">
            <input type="hidden" id="input-{{ key }}" value="{{ s.value }}"
              data-key="{{ key }}" data-restart="{{ 'true' if s.restart else 'false' }}">
            <div class="flex justify-between items-center gap-2.5 mb-3">
              <label class="text-sm font-medium flex-1">{{ s.label }}</label>
              {% if s.restart %}<span class="text-[0.58rem] font-bold text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded shrink-0">RESTART</span>{% endif %}
              <button type="button" onclick="btScan()" id="bt-scan-btn"
                class="bg-acc text-white font-bold text-xs px-4 py-2 rounded-lg hover:opacity-90 shrink-0 flex items-center gap-1.5">
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12.01 6.001C6.5 1 1 8 5.782 13.001L12.011 20l6.23-7C22.72 8-17.312 1 12.01 6.002z"/></svg>
                Scan
              </button>
            </div>
            <!-- Current device -->
            <div class="flex items-center gap-2 bg-black/30 border border-zinc-700 rounded-lg px-3 py-2.5 mb-2" id="bt-current">
              <svg class="w-4 h-4 text-acc shrink-0" fill="currentColor" viewBox="0 0 24 24"><path d="M17.71 7.71L12 2h-1v7.59L6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 11 14.41V22h1l5.71-5.71-4.3-4.29 4.3-4.29zM13 5.83l1.88 1.88L13 9.59V5.83zm1.88 10.46L13 18.17v-3.76l1.88 1.88z"/></svg>
              <span class="text-sm font-mono flex-1" id="bt-current-mac">{{ s.value }}</span>
              <span class="text-xs text-zinc-500" id="bt-current-label">{% if s.value and s.value != 'AA:BB:CC:DD:EE:FF' %}Selected{% else %}Not configured{% endif %}</span>
            </div>
            <!-- Scan results -->
            <div id="bt-devices" class="hidden">
              <div class="text-[0.65rem] text-zinc-500 uppercase tracking-wider font-semibold mb-1.5">Nearby Devices</div>
              <div id="bt-device-list" class="space-y-1"></div>
            </div>
            <!-- Scanning spinner -->
            <div id="bt-scanning" class="hidden flex items-center justify-center gap-2 py-4 text-sm text-zinc-400">
              <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/></svg>
              Scanning for Bluetooth devices…
            </div>
            {% if s.description %}<div class="text-xs text-zinc-500 mt-2 leading-relaxed">{{ s.description }}</div>{% endif %}
            <div class="text-xs font-medium mt-1.5 min-h-[16px]" id="fb-{{ key }}"></div>
          </div>

          {% else %}
          <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4 mb-2.5" id="field-{{ key }}">
            <div class="flex justify-between items-center gap-2.5">
              <label class="text-sm font-medium flex-1">{{ s.label }}</label>
              {% if s.restart %}<span class="text-[0.58rem] font-bold text-amber-400 bg-amber-500/10 px-2 py-0.5 rounded shrink-0">RESTART</span>{% endif %}
              {% if s.type == 'str' %}
                <input type="text" id="input-{{ key }}" value="{{ s.value }}"
                  data-key="{{ key }}" data-restart="{{ 'true' if s.restart else 'false' }}"
                  class="w-40 bg-black/30 border border-zinc-700 text-zinc-100 font-mono text-sm p-2 rounded-lg text-right focus:outline-none focus:border-acc focus:ring-2 focus:ring-acc/20">
              {% else %}
                <input type="number" id="input-{{ key }}" value="{{ s.value }}"
                  min="{{ s.min }}" max="{{ s.max }}" step="{{ '0.1' if s.type == 'float' else '1' }}"
                  data-key="{{ key }}" data-restart="{{ 'true' if s.restart else 'false' }}"
                  class="w-40 bg-black/30 border border-zinc-700 text-zinc-100 font-mono text-sm p-2 rounded-lg text-right focus:outline-none focus:border-acc focus:ring-2 focus:ring-acc/20">
              {% endif %}
              <button type="button" onclick="saveSetting('{{ key }}')"
                class="bg-acc text-white font-bold text-xs px-4 py-2 rounded-lg hover:opacity-90 shrink-0">Save</button>
            </div>
            {% if s.description %}<div class="text-xs text-zinc-500 mt-2 leading-relaxed">{{ s.description }}</div>{% endif %}
            <div class="text-xs font-medium mt-1.5 min-h-[16px]" id="fb-{{ key }}"></div>
          </div>
          {% endif %}

        {% endif %}
      {% endfor %}
    </div>
    {% endfor %}
  </div>

  <div class="text-center py-4 text-xs text-zinc-600 border-t border-zinc-800">
    SignalKit v{{ version }} &middot; <a href="/" class="text-zinc-400 hover:text-acc">Dashboard</a> &middot; {{ ip }}:{{ port }}
  </div>

  <script>
    let restartNeeded = false;

    function switchTab(group) {
      // Hide all panels, show selected
      document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
      const panel = document.querySelector('[data-panel="' + group + '"]');
      if (panel) panel.classList.remove('hidden');
      // Update tab button styles
      document.querySelectorAll('#settings-tabs button').forEach(b => {
        if (b.dataset.tab === group) {
          b.className = 'flex-1 text-[0.65rem] font-semibold px-1.5 py-2 rounded-lg text-center leading-tight transition-all bg-acc text-white shadow-md';
        } else {
          b.className = 'flex-1 text-[0.65rem] font-semibold px-1.5 py-2 rounded-lg text-center leading-tight transition-all text-zinc-400 hover:text-zinc-200';
        }
      });
    }

    async function saveSetting(key) {
      const input = document.getElementById('input-' + key);
      const fb = document.getElementById('fb-' + key);
      const requiresRestart = input.dataset.restart === 'true';

      fb.textContent = 'Saving...';
      fb.className = 'text-xs font-medium mt-1.5 min-h-[16px] text-amber-400';

      try {
        const resp = await fetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ [key]: input.value }),
        });
        const result = await resp.json();

        if (result.errors && result.errors[key]) {
          fb.textContent = result.errors[key];
          fb.className = 'text-xs font-medium mt-1.5 min-h-[16px] text-red-400';
        } else if (result.saved && result.saved.includes(key)) {
          fb.textContent = result.messages[key] || 'Saved';
          fb.className = 'text-xs font-medium mt-1.5 min-h-[16px] text-emerald-400';
          if (key === 'COLOR_THEME') setTimeout(() => window.location.reload(), 500);
          if (requiresRestart) showRestartBanner();
        } else {
          fb.textContent = 'Unknown response';
          fb.className = 'text-xs font-medium mt-1.5 min-h-[16px] text-red-400';
        }
      } catch (e) {
        fb.textContent = 'Network error';
        fb.className = 'text-xs font-medium mt-1.5 min-h-[16px] text-red-400';
      }
    }

    function pickSegment(key, val) {
      document.getElementById('input-' + key).value = val;
      const btns = document.querySelectorAll('#seg-' + key + ' button');
      btns.forEach(b => {
        if (b.dataset.val === val) {
          b.className = 'flex-1 text-sm font-semibold py-2 rounded-md transition-all bg-acc text-white shadow-md';
        } else {
          b.className = 'flex-1 text-sm font-semibold py-2 rounded-md transition-all text-zinc-400 hover:text-zinc-200';
        }
      });
      saveSetting(key);
    }

    function showRestartBanner() {
      restartNeeded = true;
      document.getElementById('restart-banner').classList.remove('hidden');
    }

    async function restartApp() {
      const btn = document.getElementById('restart-btn');
      btn.disabled = true;
      btn.textContent = 'Restarting...';
      try {
        await fetch('/api/restart', { method: 'POST' });
        btn.textContent = 'Reconnecting...';
        setTimeout(() => { window.location.href = '/'; }, 5000);
      } catch (e) {
        btn.textContent = 'Restart Now';
        btn.disabled = false;
      }
    }

    // --- Ordered list editor ---
    const LIST_KEYS = {{ list_settings_json|safe }};

    function getListItems(key) {
      const val = document.getElementById('input-' + key).value;
      return val ? val.split(',').map(s => s.trim()).filter(Boolean) : [];
    }

    function setListItems(key, items) {
      document.getElementById('input-' + key).value = items.join(', ');
      renderList(key);
    }

    function renderList(key) {
      const wrap = document.getElementById('list-' + key);
      const items = getListItems(key);
      wrap.innerHTML = items.map((id, i) => `
        <div class="flex items-center gap-2 bg-black/30 border border-zinc-700 rounded-lg px-3 py-2 mb-1.5 text-sm">
          <span class="w-[22px] h-[22px] min-w-[22px] flex items-center justify-center rounded-md bg-acc/15 text-acc text-xs font-bold">${i + 1}</span>
          <span class="flex-1 capitalize">${id}</span>
          <span class="cursor-pointer text-zinc-500 hover:text-zinc-200 select-none px-1" title="Move up" onclick="moveCard('${key}',${i},-1)" ${i===0?'style="opacity:0.3;pointer-events:none"':''}>&#9650;</span>
          <span class="cursor-pointer text-zinc-500 hover:text-zinc-200 select-none px-1" title="Move down" onclick="moveCard('${key}',${i},1)" ${i===items.length-1?'style="opacity:0.3;pointer-events:none"':''}>&#9660;</span>
          <span class="cursor-pointer text-zinc-500 hover:text-red-400 select-none px-1" title="Remove" onclick="removeCard('${key}',${i})">&#10005;</span>
        </div>
      `).join('');
    }

    function moveCard(key, idx, dir) {
      const items = getListItems(key);
      const target = idx + dir;
      if (target < 0 || target >= items.length) return;
      [items[idx], items[target]] = [items[target], items[idx]];
      setListItems(key, items);
    }

    function removeCard(key, idx) {
      const items = getListItems(key);
      items.splice(idx, 1);
      setListItems(key, items);
    }

    function addCardItem(key) {
      const sel = document.getElementById('add-select-' + key);
      const items = getListItems(key);
      if (!items.includes(sel.value)) {
        items.push(sel.value);
        setListItems(key, items);
      }
    }

    function saveListSetting(key) { saveSetting(key); }

    LIST_KEYS.forEach(renderList);

    // --- Bluetooth device scanner ---
    async function btScan() {
      const btn = document.getElementById('bt-scan-btn');
      const spinner = document.getElementById('bt-scanning');
      const devicesWrap = document.getElementById('bt-devices');
      const list = document.getElementById('bt-device-list');

      btn.disabled = true;
      btn.classList.add('opacity-50');
      spinner.classList.remove('hidden');
      devicesWrap.classList.add('hidden');
      list.innerHTML = '';

      try {
        const resp = await fetch('/api/bt-scan', { method: 'POST' });
        const data = await resp.json();

        spinner.classList.add('hidden');
        btn.disabled = false;
        btn.classList.remove('opacity-50');

        if (!data.ok) {
          list.innerHTML = `<div class="text-xs text-red-400 py-2">${data.error || 'Scan failed'}</div>`;
          devicesWrap.classList.remove('hidden');
          return;
        }

        if (data.devices.length === 0) {
          list.innerHTML = '<div class="text-xs text-zinc-500 py-2">No devices found. Make sure your OBD2 adapter is powered on.</div>';
          devicesWrap.classList.remove('hidden');
          return;
        }

        const currentMac = document.getElementById('input-OBD_MAC').value;
        list.innerHTML = data.devices.map(d => {
          const isSelected = d.mac.toUpperCase() === currentMac.toUpperCase();
          return `<button type="button" onclick="btSelect('${d.mac}','${d.name.replace(/'/g, "\\'")}')"
            class="w-full flex items-center gap-2.5 bg-black/30 border rounded-lg px-3 py-2.5 text-left transition-all
              ${isSelected ? 'border-acc bg-acc/10' : 'border-zinc-700 hover:border-zinc-500'}">
            <svg class="w-4 h-4 ${isSelected ? 'text-acc' : 'text-zinc-600'} shrink-0" fill="currentColor" viewBox="0 0 24 24"><path d="M17.71 7.71L12 2h-1v7.59L6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 11 14.41V22h1l5.71-5.71-4.3-4.29 4.3-4.29zM13 5.83l1.88 1.88L13 9.59V5.83zm1.88 10.46L13 18.17v-3.76l1.88 1.88z"/></svg>
            <div class="flex-1 min-w-0">
              <div class="text-sm font-medium truncate">${d.name}</div>
              <div class="text-xs font-mono text-zinc-500">${d.mac}</div>
            </div>
            ${isSelected ? '<span class="text-[0.6rem] font-bold text-acc bg-acc/15 px-2 py-0.5 rounded">SELECTED</span>' : ''}
          </button>`;
        }).join('');
        devicesWrap.classList.remove('hidden');
      } catch (e) {
        spinner.classList.add('hidden');
        btn.disabled = false;
        btn.classList.remove('opacity-50');
        list.innerHTML = '<div class="text-xs text-red-400 py-2">Network error during scan.</div>';
        devicesWrap.classList.remove('hidden');
      }
    }

    async function btSelect(mac, name) {
      document.getElementById('input-OBD_MAC').value = mac;
      document.getElementById('bt-current-mac').textContent = mac;
      document.getElementById('bt-current-label').textContent = name;
      // Re-render device list to update selected state
      document.querySelectorAll('#bt-device-list button').forEach(b => {
        const bMac = b.querySelector('.font-mono')?.textContent;
        if (bMac === mac) {
          b.className = b.className.replace('border-zinc-700 hover:border-zinc-500', 'border-acc bg-acc/10');
        } else {
          b.className = b.className.replace('border-acc bg-acc/10', 'border-zinc-700 hover:border-zinc-500');
        }
      });
      await saveSetting('OBD_MAC');
    }
  </script>
</body>
</html>
"""

# ---------------------------------------------------------------------------
# OTA Update HTML
# ---------------------------------------------------------------------------

UPDATE_HTML = """<!DOCTYPE html>
<html lang="en" class="dark" style="background:#0a0a0a">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
  <meta name="theme-color" content="#0a0a0a">
  <title>SignalKit Update</title>
  """ + SHARED_HEAD + """
</head>
<body>
  <!-- Header -->
  <div class="flex justify-between items-center px-4 py-2.5 bg-zinc-900 border-b border-zinc-800 sticky top-0 z-50">
    <h1 class="text-sm font-bold tracking-widest flex items-center gap-2">
      <span class="w-2 h-2 bg-acc rounded-full shadow-[0_0_8px_var(--accent)]"></span>SIGNALKIT
    </h1>
    <nav class="flex gap-0.5 bg-zinc-800 rounded-lg p-0.5">
      <a href="/" class="text-xs font-semibold px-3 py-1 rounded-md text-zinc-400 hover:text-white">Dashboard</a>
      <a href="/settings" class="text-xs font-semibold px-3 py-1 rounded-md text-zinc-400 hover:text-white">Settings</a>
      <a href="/diagnostics" class="text-xs font-semibold px-3 py-1 rounded-md text-zinc-400 hover:text-white">Diag</a>
    </nav>
  </div>

  <div class="max-w-[600px] mx-auto p-4">
    <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-5 mb-3.5">
      <h2 class="text-base font-bold mb-1">Software Update</h2>
      <p class="text-sm text-zinc-500 mb-4 leading-relaxed">Pull the latest code from the git repository and restart SignalKit.</p>

      <div class="flex justify-between items-center py-2.5 border-t border-zinc-800 first:border-t-0">
        <span class="text-xs font-semibold tracking-wide text-zinc-500 uppercase">Current Version</span>
        <span class="text-sm font-mono" id="current-hash">loading...</span>
      </div>
      <div class="flex justify-between items-center py-2.5 border-t border-zinc-800">
        <span class="text-xs font-semibold tracking-wide text-zinc-500 uppercase">Branch</span>
        <span class="text-sm font-mono" id="current-branch">loading...</span>
      </div>
      <div class="flex justify-between items-center py-2.5 border-t border-zinc-800">
        <span class="text-xs font-semibold tracking-wide text-zinc-500 uppercase">Last Updated</span>
        <span class="text-sm font-mono" id="last-commit-date">loading...</span>
      </div>

      <button type="button" onclick="runUpdate()" id="update-btn"
        class="w-full bg-acc text-white font-bold text-sm py-3.5 rounded-xl mt-2 hover:opacity-90 active:scale-[0.98] transition-all disabled:opacity-35 disabled:cursor-not-allowed">
        Check for Updates &amp; Install
      </button>

      <div id="update-log" class="hidden mt-3.5 bg-black/40 border border-zinc-800 rounded-xl p-3.5 font-mono text-xs text-zinc-400 leading-relaxed max-h-[300px] overflow-y-auto whitespace-pre-wrap break-all"></div>
      <div id="result-banner" class="hidden mt-3.5 p-3 rounded-xl text-sm font-semibold"></div>
    </div>
  </div>

  <div class="text-center py-4 text-xs text-zinc-600 border-t border-zinc-800">
    SignalKit v{{ version }} &middot; <a href="/" class="text-zinc-400 hover:text-acc">Dashboard</a> &middot; {{ ip }}:{{ port }}
  </div>

  <script>
    async function loadGitInfo() {
      try {
        const r = await fetch('/api/update');
        const d = await r.json();
        document.getElementById('current-hash').textContent = d.hash || 'unknown';
        document.getElementById('current-branch').textContent = d.branch || 'unknown';
        document.getElementById('last-commit-date').textContent = d.date || 'unknown';
      } catch(e) {
        document.getElementById('current-hash').textContent = 'error';
      }
    }
    loadGitInfo();

    async function runUpdate() {
      const btn = document.getElementById('update-btn');
      const log = document.getElementById('update-log');
      const banner = document.getElementById('result-banner');

      btn.disabled = true;
      btn.textContent = 'Updating...';
      log.classList.remove('hidden');
      log.innerHTML = '';
      banner.classList.add('hidden');

      function addLog(text, color) {
        const span = document.createElement('span');
        span.className = color || 'text-zinc-400';
        span.textContent = text + '\\n';
        log.appendChild(span);
        log.scrollTop = log.scrollHeight;
      }

      addLog('Fetching latest changes...', 'text-acc');

      try {
        const resp = await fetch('/api/update', { method: 'POST' });
        const result = await resp.json();

        if (result.steps) {
          result.steps.forEach(s => {
            addLog('$ ' + s.cmd, 'text-acc');
            if (s.output) addLog(s.output);
            if (s.error) addLog(s.error, 'text-red-400');
          });
        }

        banner.classList.remove('hidden');
        if (result.status === 'updated') {
          banner.className = 'mt-3.5 p-3 rounded-xl text-sm font-semibold bg-emerald-500/10 border border-emerald-500/20 text-emerald-400';
          banner.textContent = 'Update installed! Restarting SignalKit...';
          addLog('Restarting SignalKit service...', 'text-emerald-400');
          setTimeout(() => { window.location.reload(); }, 6000);
        } else if (result.status === 'reboot_required') {
          banner.className = 'mt-3.5 p-3 rounded-xl text-sm font-semibold bg-amber-500/10 border border-amber-500/20 text-amber-400';
          banner.textContent = 'Update staged — Pi is rebooting to apply it. This takes about 30 seconds.';
          addLog('Disabling read-only filesystem...', 'text-amber-400');
          addLog('Rebooting to apply update...', 'text-amber-400');
        } else if (result.status === 'up_to_date') {
          banner.className = 'mt-3.5 p-3 rounded-xl text-sm font-semibold bg-zinc-800 border border-zinc-700 text-zinc-400';
          banner.textContent = 'Already up to date.';
          addLog('No new changes.', 'text-emerald-400');
          btn.disabled = false;
          btn.textContent = 'Check for Updates & Install';
        } else {
          banner.className = 'mt-3.5 p-3 rounded-xl text-sm font-semibold bg-red-500/10 border border-red-500/20 text-red-400';
          banner.textContent = result.error || 'Update failed.';
          addLog('Update failed: ' + (result.error || 'Unknown error'), 'text-red-400');
          btn.disabled = false;
          btn.textContent = 'Retry Update';
        }
        loadGitInfo();
      } catch(e) {
        addLog('Network error: ' + e.message, 'text-red-400');
        banner.classList.remove('hidden');
        banner.className = 'mt-3.5 p-3 rounded-xl text-sm font-semibold bg-red-500/10 border border-red-500/20 text-red-400';
        banner.textContent = 'Network error during update.';
        btn.disabled = false;
        btn.textContent = 'Retry Update';
      }
    }
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Diagnostics HTML
# ---------------------------------------------------------------------------

DIAGNOSTICS_HTML = """<!DOCTYPE html>
<html lang="en" class="dark" style="background:#0a0a0a">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
  <meta name="theme-color" content="#0a0a0a">
  <title>SignalKit Diagnostics</title>
  """ + SHARED_HEAD + """
</head>
<body>
  <!-- Header -->
  <div class="flex justify-between items-center px-4 py-2.5 bg-zinc-900 border-b border-zinc-800 sticky top-0 z-50">
    <h1 class="text-sm font-bold tracking-widest flex items-center gap-2">
      <span class="w-2 h-2 bg-acc rounded-full shadow-[0_0_8px_var(--accent)]"></span>SIGNALKIT
    </h1>
    <nav class="flex gap-0.5 bg-zinc-800 rounded-lg p-0.5">
      <a href="/" class="text-xs font-semibold px-3 py-1 rounded-md text-zinc-400 hover:text-white">Dashboard</a>
      <a href="/settings" class="text-xs font-semibold px-3 py-1 rounded-md text-zinc-400 hover:text-white">Settings</a>
      <a href="/diagnostics" class="text-xs font-semibold px-3 py-1 rounded-md bg-acc text-white">Diag</a>
      <a href="/dev" class="text-xs font-semibold px-3 py-1 rounded-md text-zinc-400 hover:text-white">Dev</a>
    </nav>
  </div>

  <div class="max-w-[600px] mx-auto p-4">

    <!-- Connection Status -->
    <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-5 mb-3.5">
      <h2 class="text-base font-bold mb-3 flex items-center gap-2">
        <span class="w-2.5 h-2.5 rounded-full" id="diag-dot"></span>
        Connection Status
      </h2>
      <div id="diag-status" class="text-sm text-zinc-400 mb-4">Loading...</div>

      <div class="space-y-0">
        <div class="flex justify-between items-center py-2.5 border-t border-zinc-800">
          <span class="text-xs font-semibold tracking-wide text-zinc-500 uppercase">Bluetooth MAC</span>
          <span class="text-sm font-mono" id="diag-mac">--</span>
        </div>
        <div class="flex justify-between items-center py-2.5 border-t border-zinc-800">
          <span class="text-xs font-semibold tracking-wide text-zinc-500 uppercase">Serial Port</span>
          <span class="text-sm font-mono" id="diag-port">--</span>
        </div>
        <div class="flex justify-between items-center py-2.5 border-t border-zinc-800">
          <span class="text-xs font-semibold tracking-wide text-zinc-500 uppercase">RFCOMM Channel</span>
          <span class="text-sm font-mono" id="diag-channel">--</span>
        </div>
        <div class="flex justify-between items-center py-2.5 border-t border-zinc-800">
          <span class="text-xs font-semibold tracking-wide text-zinc-500 uppercase">OBD Protocol</span>
          <span class="text-sm font-mono" id="diag-protocol">--</span>
        </div>
        <div class="flex justify-between items-center py-2.5 border-t border-zinc-800">
          <span class="text-xs font-semibold tracking-wide text-zinc-500 uppercase">ELM327 Version</span>
          <span class="text-sm font-mono" id="diag-elm">--</span>
        </div>
        <div class="flex justify-between items-center py-2.5 border-t border-zinc-800">
          <span class="text-xs font-semibold tracking-wide text-zinc-500 uppercase">Connection Attempts</span>
          <span class="text-sm font-mono" id="diag-attempts">--</span>
        </div>
        <div class="flex justify-between items-center py-2.5 border-t border-zinc-800">
          <span class="text-xs font-semibold tracking-wide text-zinc-500 uppercase">Poll Errors</span>
          <span class="text-sm font-mono" id="diag-errors">--</span>
        </div>
      </div>
    </div>

    <!-- Supported PIDs -->
    <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-5 mb-3.5">
      <h2 class="text-base font-bold mb-1">Supported PIDs</h2>
      <p class="text-sm text-zinc-500 mb-3">Commands reported as supported by the vehicle's ECU.</p>
      <div id="diag-pids" class="text-sm text-zinc-400">Loading...</div>
    </div>

    <!-- System Info -->
    <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-5 mb-3.5">
      <h2 class="text-base font-bold mb-3">System Info</h2>
      <div class="space-y-0">
        <div class="flex justify-between items-center py-2.5 border-t border-zinc-800">
          <span class="text-xs font-semibold tracking-wide text-zinc-500 uppercase">CPU Temp</span>
          <span class="text-sm font-mono" id="sys-cpu-temp">--</span>
        </div>
        <div class="flex justify-between items-center py-2.5 border-t border-zinc-800">
          <span class="text-xs font-semibold tracking-wide text-zinc-500 uppercase">Memory Usage</span>
          <span class="text-sm font-mono" id="sys-memory">--</span>
        </div>
        <div class="flex justify-between items-center py-2.5 border-t border-zinc-800">
          <span class="text-xs font-semibold tracking-wide text-zinc-500 uppercase">Uptime</span>
          <span class="text-sm font-mono" id="sys-uptime">--</span>
        </div>
      </div>
    </div>
  </div>

  <div class="text-center py-4 text-xs text-zinc-600 border-t border-zinc-800">
    SignalKit v{{ version }} &middot; <a href="/" class="text-zinc-400 hover:text-acc">Dashboard</a> &middot; {{ ip }}:{{ port }}
  </div>

  <script>
    async function loadDiagnostics() {
      try {
        const r = await fetch('/api/diagnostics');
        const d = await r.json();

        // Connection status
        const dot = document.getElementById('diag-dot');
        const status = document.getElementById('diag-status');
        if (d.connected) {
          dot.style.background = '#22c55e';
          dot.style.boxShadow = '0 0 6px #22c55e';
          status.textContent = d.status;
          status.className = 'text-sm text-emerald-400 mb-4 font-semibold';
        } else {
          dot.style.background = '#ef4444';
          dot.style.boxShadow = '0 0 6px #ef4444';
          status.textContent = d.status || 'Disconnected';
          status.className = 'text-sm text-red-400 mb-4 font-semibold';
        }

        document.getElementById('diag-mac').textContent = d.bt_mac || '--';
        document.getElementById('diag-port').textContent = d.bt_port || '--';
        document.getElementById('diag-channel').textContent = d.bt_channel || '--';
        document.getElementById('diag-protocol').textContent = d.protocol || '--';
        document.getElementById('diag-elm').textContent = d.elm_version || '--';
        document.getElementById('diag-attempts').textContent = d.connection_attempts || '0';
        document.getElementById('diag-errors').textContent = d.poll_errors || '0';

        // PIDs
        const pidsDiv = document.getElementById('diag-pids');
        if (d.supported_pids && d.supported_pids.length > 0) {
          pidsDiv.innerHTML = '<div class="flex flex-wrap gap-1.5">' +
            d.supported_pids.map(pid =>
              `<span class="bg-zinc-800 border border-zinc-700 text-zinc-300 text-xs font-mono px-2 py-1 rounded-md">${pid}</span>`
            ).join('') + '</div>';
        } else {
          pidsDiv.innerHTML = '<span class="text-zinc-500">Not connected — PIDs will appear after connecting to the adapter.</span>';
        }

        // System info
        if (d.system) {
          document.getElementById('sys-cpu-temp').textContent = d.system.cpu_temp || '--';
          document.getElementById('sys-memory').textContent = d.system.memory || '--';
          document.getElementById('sys-uptime').textContent = d.system.uptime || '--';
        }
      } catch(e) {
        document.getElementById('diag-status').textContent = 'Failed to load diagnostics';
      }
    }

    loadDiagnostics();
    setInterval(loadDiagnostics, 5000);
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Setup Wizard HTML (first-run experience)
# ---------------------------------------------------------------------------

SETUP_HTML = """<!DOCTYPE html>
<html lang="en" class="dark" style="background:#0a0a0a">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>SignalKit Setup</title>
""" + SHARED_HEAD + """
  <style>
    .step { display: none; }
    .step.active { display: block; }
    .fade-in { animation: fadeIn 0.4s ease-out; }
    @keyframes fadeIn { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
    .pulse-dot { animation: pulse 2s ease-in-out infinite; }
    @keyframes pulse { 0%, 100% { opacity: 0.4; } 50% { opacity: 1; } }
  </style>
</head>
<body>
  <div class="max-w-md mx-auto px-5 py-8">

    <!-- Step 1: Welcome -->
    <div class="step active fade-in" data-step="1">
      <div class="text-center mb-8">
        <div class="mx-auto mb-5 flex justify-center">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="12 14 220 42" width="240" height="48">
            <rect x="16" y="44" width="6" height="8" rx="2" fill="#DC2626" opacity="0.32"/>
            <rect x="25" y="38" width="6" height="14" rx="2" fill="#DC2626" opacity="0.55"/>
            <rect x="34" y="30" width="6" height="22" rx="2" fill="#DC2626" opacity="0.78"/>
            <rect x="43" y="20" width="6" height="32" rx="2" fill="#DC2626"/>
            <text x="60" y="44" font-family="'Arial Black','Helvetica Neue',sans-serif" font-weight="800" font-size="32" letter-spacing="-0.5" fill="#ffffff">Signal</text>
            <text x="178" y="44" font-family="'Arial Black','Helvetica Neue',sans-serif" font-weight="800" font-size="32" letter-spacing="-0.5" fill="#DC2626">Kit</text>
          </svg>
        </div>
        <h1 class="text-2xl font-bold mb-2">Welcome to SignalKit</h1>
        <p class="text-sm text-zinc-400 leading-relaxed">Let's set up your OBD2 dashboard. This takes about a minute.</p>
      </div>
      <div class="space-y-3 mb-8">
        <div class="flex items-center gap-3 bg-zinc-900 border border-zinc-800 rounded-xl p-3.5">
          <div class="w-8 h-8 rounded-lg bg-acc/15 flex items-center justify-center shrink-0"><span class="text-sm font-bold text-acc">1</span></div>
          <div><div class="text-sm font-medium">Connect your OBD2 adapter</div><div class="text-xs text-zinc-500">Scan for nearby Bluetooth devices</div></div>
        </div>
        <div class="flex items-center gap-3 bg-zinc-900 border border-zinc-800 rounded-xl p-3.5">
          <div class="w-8 h-8 rounded-lg bg-zinc-800 flex items-center justify-center shrink-0"><span class="text-sm font-bold text-zinc-500">2</span></div>
          <div><div class="text-sm font-medium">Set WiFi password</div><div class="text-xs text-zinc-500">Secure your SignalKit network</div></div>
        </div>
        <div class="flex items-center gap-3 bg-zinc-900 border border-zinc-800 rounded-xl p-3.5">
          <div class="w-8 h-8 rounded-lg bg-zinc-800 flex items-center justify-center shrink-0"><span class="text-sm font-bold text-zinc-500">3</span></div>
          <div><div class="text-sm font-medium">You're ready</div><div class="text-xs text-zinc-500">Start driving with live data</div></div>
        </div>
      </div>
      <button onclick="goStep(2)" class="w-full bg-acc text-white font-bold py-3 rounded-xl hover:opacity-90 transition-opacity">Get Started</button>
    </div>

    <!-- Step 2: Bluetooth Scan -->
    <div class="step fade-in" data-step="2">
      <div class="mb-6">
        <div class="text-xs font-semibold text-acc uppercase tracking-wider mb-1">Step 1 of 2</div>
        <h2 class="text-xl font-bold mb-1">Find Your OBD2 Adapter</h2>
        <p class="text-sm text-zinc-400">Plug the adapter into your car's OBD2 port, then tap Scan.</p>
      </div>

      <button onclick="setupBtScan()" id="setup-scan-btn"
        class="w-full bg-zinc-900 border border-zinc-800 text-white font-semibold py-3 rounded-xl hover:border-zinc-700 transition-all flex items-center justify-center gap-2 mb-4">
        <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><path d="M17.71 7.71L12 2h-1v7.59L6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 11 14.41V22h1l5.71-5.71-4.3-4.29 4.3-4.29zM13 5.83l1.88 1.88L13 9.59V5.83zm1.88 10.46L13 18.17v-3.76l1.88 1.88z"/></svg>
        Scan for Devices
      </button>

      <div id="setup-scanning" class="hidden flex items-center justify-center gap-2 py-6 text-sm text-zinc-400">
        <svg class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"/></svg>
        Scanning for Bluetooth devices...
      </div>

      <div id="setup-devices" class="space-y-1.5 mb-4"></div>

      <div id="setup-bt-error" class="hidden text-xs text-zinc-500 text-center py-4"></div>

      <div class="flex gap-2 mt-4">
        <button onclick="goStep(1)" class="flex-1 bg-zinc-900 border border-zinc-800 text-zinc-400 font-semibold py-3 rounded-xl hover:text-white transition-colors">Back</button>
        <button onclick="goStep(3)" id="setup-next-2" disabled
          class="flex-1 bg-acc text-white font-bold py-3 rounded-xl transition-opacity disabled:opacity-30">Next</button>
      </div>
    </div>

    <!-- Step 3: WiFi Password -->
    <div class="step fade-in" data-step="3">
      <div class="mb-6">
        <div class="text-xs font-semibold text-acc uppercase tracking-wider mb-1">Step 2 of 2</div>
        <h2 class="text-xl font-bold mb-1">Secure Your WiFi</h2>
        <p class="text-sm text-zinc-400">Set a password for the SignalKit WiFi network, or leave blank to keep it open.</p>
      </div>

      <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4 mb-3">
        <label class="text-xs font-semibold text-zinc-500 uppercase tracking-wider">Network Name</label>
        <input type="text" id="setup-ssid" value="{{ ssid }}"
          class="w-full bg-black/30 border border-zinc-700 text-zinc-100 text-sm p-2.5 rounded-lg mt-1.5 focus:outline-none focus:border-acc">
      </div>

      <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4 mb-6">
        <label class="text-xs font-semibold text-zinc-500 uppercase tracking-wider">Password</label>
        <input type="text" id="setup-wifi-pass" placeholder="Leave blank for open network"
          class="w-full bg-black/30 border border-zinc-700 text-zinc-100 text-sm p-2.5 rounded-lg mt-1.5 focus:outline-none focus:border-acc">
        <div class="text-xs text-zinc-500 mt-1.5">Must be 8+ characters if set.</div>
      </div>

      <div class="flex gap-2">
        <button onclick="goStep(2)" class="flex-1 bg-zinc-900 border border-zinc-800 text-zinc-400 font-semibold py-3 rounded-xl hover:text-white transition-colors">Back</button>
        <button onclick="finishSetup()" id="setup-finish-btn"
          class="flex-1 bg-acc text-white font-bold py-3 rounded-xl hover:opacity-90 transition-opacity">Finish Setup</button>
      </div>
    </div>

    <!-- Step 4: Done -->
    <div class="step fade-in" data-step="4">
      <div class="text-center py-8">
        <div class="w-16 h-16 mx-auto mb-4 rounded-full bg-emerald-500/15 flex items-center justify-center">
          <svg class="w-8 h-8 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"/></svg>
        </div>
        <h2 class="text-2xl font-bold mb-2">You're All Set!</h2>
        <p class="text-sm text-zinc-400 leading-relaxed mb-6">SignalKit is configured and ready. Start your engine to see live data.</p>
        <div id="setup-summary" class="bg-zinc-900 border border-zinc-800 rounded-xl p-4 mb-6 text-left space-y-2">
          <div class="flex justify-between text-sm"><span class="text-zinc-500">Adapter</span><span class="font-mono" id="summary-mac">--</span></div>
          <div class="flex justify-between text-sm"><span class="text-zinc-500">WiFi</span><span id="summary-wifi">--</span></div>
        </div>
        <div class="text-xs text-amber-400 bg-amber-500/10 border border-amber-500/20 rounded-xl p-3 mb-6" id="setup-reboot-notice" class="hidden">
          SignalKit will restart to apply your settings. This takes about 15 seconds.
        </div>
        <a href="/" class="block w-full bg-acc text-white font-bold py-3 rounded-xl hover:opacity-90 transition-opacity text-center">Open Dashboard</a>
      </div>
    </div>

  </div>

  <script>
    let selectedMac = null;

    function goStep(n) {
      document.querySelectorAll('.step').forEach(s => s.classList.remove('active'));
      const step = document.querySelector('[data-step="' + n + '"]');
      if (step) step.classList.add('active');
    }

    async function setupBtScan() {
      const btn = document.getElementById('setup-scan-btn');
      const spinner = document.getElementById('setup-scanning');
      const list = document.getElementById('setup-devices');
      const errDiv = document.getElementById('setup-bt-error');

      btn.disabled = true;
      btn.classList.add('opacity-50');
      spinner.classList.remove('hidden');
      list.innerHTML = '';
      errDiv.classList.add('hidden');

      try {
        const resp = await fetch('/api/bt-scan', { method: 'POST' });
        const data = await resp.json();
        spinner.classList.add('hidden');
        btn.disabled = false;
        btn.classList.remove('opacity-50');

        if (!data.ok || data.devices.length === 0) {
          errDiv.textContent = data.error || 'No devices found. Make sure your OBD2 adapter is plugged in and powered on.';
          errDiv.classList.remove('hidden');
          return;
        }

        list.innerHTML = data.devices.map(d => `
          <button onclick="selectAdapter('${d.mac}','${d.name.replace(/'/g, "\\\\'")}')" data-mac="${d.mac}"
            class="w-full flex items-center gap-2.5 bg-black/30 border border-zinc-700 rounded-xl px-3.5 py-3 text-left transition-all hover:border-zinc-500">
            <svg class="w-5 h-5 text-zinc-600 shrink-0" fill="currentColor" viewBox="0 0 24 24"><path d="M17.71 7.71L12 2h-1v7.59L6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 11 14.41V22h1l5.71-5.71-4.3-4.29 4.3-4.29zM13 5.83l1.88 1.88L13 9.59V5.83zm1.88 10.46L13 18.17v-3.76l1.88 1.88z"/></svg>
            <div class="flex-1 min-w-0">
              <div class="text-sm font-medium truncate">${d.name}</div>
              <div class="text-xs font-mono text-zinc-500">${d.mac}</div>
            </div>
          </button>
        `).join('');
      } catch(e) {
        spinner.classList.add('hidden');
        btn.disabled = false;
        btn.classList.remove('opacity-50');
        errDiv.textContent = 'Network error during scan.';
        errDiv.classList.remove('hidden');
      }
    }

    function selectAdapter(mac, name) {
      selectedMac = mac;
      document.querySelectorAll('#setup-devices button').forEach(b => {
        if (b.dataset.mac === mac) {
          b.className = b.className.replace('border-zinc-700', 'border-acc bg-acc/10');
          b.querySelector('svg').className = 'w-5 h-5 text-acc shrink-0';
        } else {
          b.className = b.className.replace('border-acc bg-acc/10', 'border-zinc-700');
          b.querySelector('svg').className = 'w-5 h-5 text-zinc-600 shrink-0';
        }
      });
      document.getElementById('setup-next-2').disabled = false;
    }

    async function finishSetup() {
      const btn = document.getElementById('setup-finish-btn');
      btn.disabled = true;
      btn.textContent = 'Saving...';

      const ssid = document.getElementById('setup-ssid').value.trim();
      const pass = document.getElementById('setup-wifi-pass').value;

      // Validate WiFi password
      if (pass && pass.length < 8) {
        alert('WiFi password must be at least 8 characters.');
        btn.disabled = false;
        btn.textContent = 'Finish Setup';
        return;
      }

      // Save all settings
      const settings = {};
      if (selectedMac) settings['OBD_MAC'] = selectedMac;
      if (ssid) settings['HOTSPOT_SSID'] = ssid;
      settings['HOTSPOT_PASSWORD'] = pass;
      settings['SETUP_COMPLETE'] = '1';

      try {
        await fetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(settings),
        });

        // Show summary
        document.getElementById('summary-mac').textContent = selectedMac || 'Not set';
        document.getElementById('summary-wifi').textContent = pass ? ssid + ' (secured)' : ssid + ' (open)';
        goStep(4);

        // Trigger restart
        setTimeout(() => fetch('/api/restart', { method: 'POST' }), 2000);
      } catch(e) {
        btn.disabled = false;
        btn.textContent = 'Finish Setup';
        alert('Failed to save settings. Please try again.');
      }
    }
  </script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# About HTML
# ---------------------------------------------------------------------------

ABOUT_HTML = """<!DOCTYPE html>
<html lang="en" class="dark" style="background:#0a0a0a">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>About SignalKit</title>
""" + SHARED_HEAD + """
</head>
<body>
  <!-- Header -->
  <div class="flex justify-between items-center px-4 py-2.5 bg-zinc-900 border-b border-zinc-800 sticky top-0 z-50">
    <h1 class="text-sm font-bold tracking-widest flex items-center gap-2">
      <span class="w-2 h-2 bg-acc rounded-full shadow-[0_0_8px_var(--accent)]"></span>SIGNALKIT
    </h1>
    <nav class="flex gap-0.5 bg-zinc-800 rounded-lg p-0.5">
      <a href="/" class="text-xs font-semibold px-3 py-1 rounded-md text-zinc-400 hover:text-white">Dashboard</a>
      <a href="/settings" class="text-xs font-semibold px-3 py-1 rounded-md text-zinc-400 hover:text-white">Settings</a>
      <a href="/about" class="text-xs font-semibold px-3 py-1 rounded-md bg-acc text-white">About</a>
    </nav>
  </div>

  <div class="max-w-md mx-auto px-4 py-6 space-y-4">

    <!-- Logo + Version -->
    <div class="text-center py-4">
      <div class="w-20 h-20 mx-auto mb-4 rounded-2xl bg-acc/10 border border-acc/20 flex items-center justify-center">
        <svg class="w-10 h-10 text-acc" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
      </div>
      <h1 class="text-xl font-bold">SignalKit</h1>
      <p class="text-sm text-zinc-500 mt-1">Version {{ version }}</p>
    </div>

    <!-- Info -->
    <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4 space-y-3">
      <div class="flex justify-between text-sm">
        <span class="text-zinc-500">Version</span>
        <span class="font-mono">{{ version }}</span>
      </div>
      <div class="flex justify-between text-sm">
        <span class="text-zinc-500">WiFi Network</span>
        <span>{{ ssid }}</span>
      </div>
      <div class="flex justify-between text-sm">
        <span class="text-zinc-500">Dashboard</span>
        <span class="font-mono">{{ ip }}:{{ port }}</span>
      </div>
    </div>

    <!-- What is SignalKit -->
    <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
      <h2 class="text-sm font-bold mb-2">What is SignalKit?</h2>
      <p class="text-xs text-zinc-400 leading-relaxed">
        SignalKit is a real-time OBD2 vehicle dashboard built for Raspberry Pi. It connects to your car's
        diagnostic port via Bluetooth, displays live engine data on an HDMI screen, and serves a
        mobile-friendly dashboard to your phone over WiFi.
      </p>
    </div>

    <!-- Safety -->
    <div class="bg-amber-500/5 border border-amber-500/20 rounded-xl p-4">
      <h2 class="text-sm font-bold text-amber-400 mb-2">Safety Notice</h2>
      <p class="text-xs text-zinc-400 leading-relaxed">
        SignalKit is for informational purposes only. Do not interact with this device while driving.
        The driver is solely responsible for safe vehicle operation at all times. Data displayed may
        not be accurate — always rely on your vehicle's factory gauges for critical information.
      </p>
    </div>

    <!-- Legal -->
    <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
      <h2 class="text-sm font-bold mb-2">Legal</h2>
      <p class="text-xs text-zinc-400 leading-relaxed">
        THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND. IN NO EVENT SHALL THE
        AUTHORS BE LIABLE FOR ANY CLAIM, DAMAGES, OR OTHER LIABILITY ARISING FROM THE USE OF
        THIS SOFTWARE. Use at your own risk.
      </p>
    </div>

    <!-- Links -->
    <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4 space-y-2">
      <a href="/update" class="flex items-center justify-between py-1.5 text-sm text-zinc-300 hover:text-acc transition-colors">
        <span>Check for Updates</span>
        <svg class="w-4 h-4 text-zinc-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
      </a>
      <a href="/diagnostics" class="flex items-center justify-between py-1.5 text-sm text-zinc-300 hover:text-acc transition-colors border-t border-zinc-800">
        <span>Connection Diagnostics</span>
        <svg class="w-4 h-4 text-zinc-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
      </a>
      <a href="/setup" class="flex items-center justify-between py-1.5 text-sm text-zinc-300 hover:text-acc transition-colors border-t border-zinc-800">
        <span>Run Setup Wizard Again</span>
        <svg class="w-4 h-4 text-zinc-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 5l7 7-7 7"/></svg>
      </a>
    </div>

  </div>

  <div class="text-center py-4 text-xs text-zinc-600 border-t border-zinc-800">
    SignalKit v{{ version }} &middot; <a href="/" class="text-zinc-400 hover:text-acc">Dashboard</a> &middot; {{ ip }}:{{ port }}
  </div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Group settings for display in the settings page
# ---------------------------------------------------------------------------

_GROUPS = {
    "OBD_MAC": "OBD2 Connection",
    "OBD_BT_CHANNEL": "OBD2 Connection",
    "FAST_POLL_INTERVAL": "OBD2 Connection",
    "SLOW_POLL_INTERVAL": "OBD2 Connection",
    "COOLANT_OVERHEAT_C": "Warning Thresholds",
    "BATTERY_LOW_V": "Warning Thresholds",
    "BATTERY_CRITICAL_V": "Warning Thresholds",
    "RPM_REDLINE": "Warning Thresholds",
    "HOTSPOT_SSID": "WiFi Hotspot",
    "HOTSPOT_PASSWORD": "WiFi Hotspot",
    "TIME_24HR": "Display",
    "UNITS_SPEED": "Display",
    "UNITS_TEMP": "Display",
    "COLOR_THEME": "Display",
    "SHOW_SPARKLINES": "Display",
    "LAYOUT_METRICS": "Dashboard Layout",
    "LAYOUT_SLOW": "Dashboard Layout",
}


_GROUP_ORDER = ["OBD2 Connection", "Warning Thresholds", "Display", "Dashboard Layout", "WiFi Hotspot"]

_TAB_LABELS = {
    "OBD2 Connection": "OBD2",
    "Warning Thresholds": "Warnings",
    "Display": "Display",
    "Dashboard Layout": "Layout",
    "WiFi Hotspot": "WiFi",
}


def _build_settings_context():
    raw = config.get_current_settings()
    # Filter out hidden settings (e.g. SETUP_COMPLETE)
    raw = {k: v for k, v in raw.items() if not v.get("hidden")}
    for key in raw:
        raw[key]["group"] = _GROUPS.get(key, "General")
    ordered = dict(sorted(raw.items(), key=lambda kv: (_GROUPS.get(kv[0], ""), kv[0])))
    # Build ordered unique group list
    groups = []
    for g in _GROUP_ORDER:
        if any(s.get("group") == g for s in ordered.values()):
            groups.append(g)
    # Add any groups not in _GROUP_ORDER
    for s in ordered.values():
        if s["group"] not in groups:
            groups.append(s["group"])
    return ordered, groups


# ---------------------------------------------------------------------------
# SSE (Server-Sent Events) stream
# ---------------------------------------------------------------------------

def _sse_stream():
    while True:
        data = obd_reader.get_data()
        payload = json.dumps(data)
        yield f"event: data\ndata: {payload}\n\n"
        time.sleep(1.0)


# ---------------------------------------------------------------------------
# Git helper for OTA updates
# ---------------------------------------------------------------------------

_APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_system_info() -> dict:
    """Gather Raspberry Pi system stats."""
    info = {"cpu_temp": "--", "memory": "--", "uptime": "--"}
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            info["cpu_temp"] = f"{int(f.read().strip()) / 1000:.1f} °C"
    except Exception:
        pass
    try:
        r = subprocess.run(["free", "-m"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if line.startswith("Mem:"):
                parts = line.split()
                total, used = int(parts[1]), int(parts[2])
                info["memory"] = f"{used} / {total} MB ({100 * used // total}%)"
                break
    except Exception:
        pass
    try:
        with open("/proc/uptime") as f:
            secs = int(float(f.read().split()[0]))
            h, m = secs // 3600, (secs % 3600) // 60
            info["uptime"] = f"{h}h {m}m"
    except Exception:
        pass
    return info


def _git_info() -> dict:
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%h|%s|%ai|%D"],
            cwd=_APP_DIR, capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return {"hash": "not a git repo", "branch": "N/A", "date": "N/A"}
        parts = result.stdout.strip().split("|", 3)
        short_hash = parts[0] if len(parts) > 0 else "unknown"
        subject = parts[1] if len(parts) > 1 else ""
        date = parts[2].split(" ")[0] if len(parts) > 2 else ""
        refs = parts[3] if len(parts) > 3 else ""
        branch = "detached"
        for ref in refs.split(","):
            ref = ref.strip()
            if ref.startswith("HEAD -> "):
                branch = ref[8:]
                break
        return {"hash": short_hash, "subject": subject, "date": date, "branch": branch}
    except Exception as e:
        return {"hash": "error", "branch": str(e), "date": "N/A"}


def _is_overlayfs() -> bool:
    """Check if the root filesystem is an overlayfs (read-only SD card protection)."""
    try:
        r = subprocess.run(["mount"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.splitlines():
            if " / " in line and "overlay" in line:
                return True
    except Exception:
        pass
    return False


def _disable_overlayfs():
    """Temporarily disable overlayfs so git pull persists to SD card.
    Uses raspi-config noninteractive mode. Requires a reboot to take effect,
    so we do: disable overlay -> reboot -> pull -> enable overlay -> reboot."""
    try:
        r = subprocess.run(
            ["sudo", "raspi-config", "nonint", "disable_overlayfs"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            return True, "Overlayfs disabled — reboot required"
        return False, r.stderr.strip() or "raspi-config failed"
    except Exception as e:
        return False, str(e)


def _enable_overlayfs():
    """Re-enable overlayfs after a persistent update."""
    try:
        r = subprocess.run(
            ["sudo", "raspi-config", "nonint", "enable_overlayfs"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            return True, "Overlayfs re-enabled — reboot required"
        return False, r.stderr.strip() or "raspi-config failed"
    except Exception as e:
        return False, str(e)


def _git_pull() -> dict:
    steps = []
    overlay_active = _is_overlayfs()

    try:
        r = subprocess.run(["git", "fetch", "--all"], cwd=_APP_DIR, capture_output=True, text=True, timeout=30)
        steps.append({"cmd": "git fetch --all", "output": r.stdout.strip(), "error": r.stderr.strip()})
        if r.returncode != 0:
            return {"status": "error", "error": "git fetch failed", "steps": steps}
        r = subprocess.run(["git", "status", "-uno"], cwd=_APP_DIR, capture_output=True, text=True, timeout=10)
        steps.append({"cmd": "git status -uno", "output": r.stdout.strip(), "error": ""})
        if "Your branch is up to date" in r.stdout:
            return {"status": "up_to_date", "steps": steps}

        if overlay_active:
            # Overlayfs is on — disable it, schedule a reboot so the pull
            # happens on next boot against the real filesystem.
            ok, msg = _disable_overlayfs()
            steps.append({"cmd": "disable_overlayfs", "output": msg, "error": "" if ok else msg})
            if not ok:
                return {"status": "error", "error": f"Cannot persist update: {msg}", "steps": steps}
            # Write a flag file so main.py knows to pull + re-enable on next boot
            flag = os.path.join(_APP_DIR, ".ota-pending")
            try:
                with open(flag, "w") as f:
                    f.write("pull\n")
                steps.append({"cmd": "write .ota-pending", "output": "Flag written", "error": ""})
            except Exception:
                pass
            return {"status": "reboot_required", "steps": steps,
                    "message": "Update ready — the Pi will reboot to apply it."}

        # No overlay — pull directly
        r = subprocess.run(["git", "pull", "--ff-only"], cwd=_APP_DIR, capture_output=True, text=True, timeout=60)
        steps.append({"cmd": "git pull --ff-only", "output": r.stdout.strip(), "error": r.stderr.strip()})
        if r.returncode != 0:
            return {"status": "error", "error": "git pull failed (merge conflict?)", "steps": steps}
        return {"status": "updated", "steps": steps}
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Command timed out (no internet?)", "steps": steps}
    except Exception as e:
        return {"status": "error", "error": str(e), "steps": steps}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Captive portal detection — redirect phones to dashboard on WiFi connect
# ---------------------------------------------------------------------------

@app.route("/generate_204")
@app.route("/gen_204")
def captive_android():
    """Android captive portal check."""
    return redirect("/")


@app.route("/hotspot-detect.html")
@app.route("/library/test/success.html")
def captive_apple():
    """Apple captive portal check — must return non-success HTML to trigger popup."""
    return redirect("/")


@app.route("/connecttest.txt")
def captive_windows():
    """Windows captive portal check."""
    return redirect("/")


@app.route("/redirect")
@app.route("/ncsi.txt")
def captive_misc():
    """Misc captive portal checks."""
    return redirect("/")


@app.route("/manifest.json")
def pwa_manifest():
    accent = config.get_theme()["accent"]
    manifest = {
        "name": "SignalKit Dashboard",
        "short_name": "SignalKit",
        "description": "Real-time OBD2 vehicle dashboard",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#0a0a0a",
        "theme_color": accent,
        "icons": [
            {"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml"},
        ],
    }
    return jsonify(manifest)


@app.route("/icon.svg")
@app.route("/icon-180.svg")
def pwa_icon():
    accent = config.get_theme()["accent"]
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 180 180">
  <rect width="180" height="180" rx="40" fill="#0a0a0a"/>
  <circle cx="90" cy="90" r="50" fill="none" stroke="{accent}" stroke-width="6" opacity="0.3"/>
  <circle cx="90" cy="90" r="30" fill="none" stroke="{accent}" stroke-width="4" opacity="0.5"/>
  <circle cx="90" cy="90" r="8" fill="{accent}"/>
  <path d="M90 55 L90 40" stroke="{accent}" stroke-width="4" stroke-linecap="round"/>
  <path d="M90 140 L90 125" stroke="{accent}" stroke-width="3" stroke-linecap="round" opacity="0.5"/>
  <path d="M55 90 L40 90" stroke="{accent}" stroke-width="3" stroke-linecap="round" opacity="0.5"/>
  <path d="M140 90 L125 90" stroke="{accent}" stroke-width="3" stroke-linecap="round" opacity="0.5"/>
  <path d="M90 90 L110 65" stroke="{accent}" stroke-width="3" stroke-linecap="round"/>
</svg>'''
    return Response(svg, mimetype="image/svg+xml")


def _needs_setup() -> bool:
    """Check if the setup wizard should be shown."""
    return not config.SETUP_COMPLETE and config.OBD_MAC == "AA:BB:CC:DD:EE:FF"


@app.route("/setup")
def setup_page():
    return render_template_string(
        SETUP_HTML,
        ip=config.HOTSPOT_IP,
        port=config.WEB_PORT,
        ssid=config.HOTSPOT_SSID,
        accent_hex=config.get_theme()["accent"],
        version=config.APP_VERSION,
    )


@app.route("/")
def index():
    if _needs_setup():
        return redirect("/setup")
    return render_template_string(
        DASHBOARD_HTML,
        ip=config.HOTSPOT_IP,
        port=config.WEB_PORT,
        redline=config.RPM_REDLINE,
        overheat_c=config.COOLANT_OVERHEAT_C,
        low_v=config.BATTERY_LOW_V,
        units_speed=config.UNITS_SPEED,
        units_temp=config.UNITS_TEMP,
        layout_metrics=config.LAYOUT_METRICS,
        layout_slow=config.LAYOUT_SLOW,
        cards=_card_registry(config.UNITS_TEMP),
        accent_hex=config.get_theme()["accent"],
        version=config.APP_VERSION,
    )


_ALL_CARD_IDS = ["coolant", "battery", "throttle", "load", "iat", "oil", "fuel_trim", "mpg"]


def _card_registry(units_temp):
    """Card metadata keyed by card ID. Unit strings use the current temp unit."""
    deg = f"°{units_temp}"
    return {
        "coolant":    {"label": "Coolant",      "val_id": "val-coolant",  "default": "---", "unit": deg,    "warn_id": "warn-coolant", "extra_id": None},
        "battery":    {"label": "Battery",      "val_id": "val-battery",  "default": "---", "unit": "Volts","warn_id": "warn-battery", "extra_id": None},
        "throttle":   {"label": "Throttle",     "val_id": "val-throttle", "default": "---", "unit": "%",    "warn_id": None, "extra_id": None},
        "load":       {"label": "Engine Load",  "val_id": "val-load",     "default": "---", "unit": "%",    "warn_id": None, "extra_id": None},
        "iat":        {"label": "Intake Air",   "val_id": "val-iat",      "default": "---", "unit": deg,    "warn_id": None, "extra_id": None},
        "oil":        {"label": "Oil Temp",     "val_id": "val-oil",      "default": "N/A", "unit": deg,    "warn_id": None, "extra_id": None},
        "fuel_trim":  {"label": "Fuel Trim B1", "val_id": "val-stft",     "default": "---", "unit": None,   "warn_id": None, "extra_id": "val-ltft"},
        "mpg":        {"label": "Fuel Economy", "val_id": "val-mpg",      "default": "---", "unit": "MPG",  "warn_id": None, "extra_id": None},
    }


@app.route("/settings")
def settings_page():
    settings, groups = _build_settings_context()
    return render_template_string(
        SETTINGS_HTML,
        settings=settings,
        groups=groups,
        tab_labels=_TAB_LABELS,
        ip=config.HOTSPOT_IP,
        port=config.WEB_PORT,
        override_path=config._active_override_path or "(not yet determined)",
        list_settings=list(config._LIST_SETTINGS),
        all_card_ids=_ALL_CARD_IDS,
        list_settings_json=json.dumps(list(config._LIST_SETTINGS)),
        accent_hex=config.get_theme()["accent"],
        version=config.APP_VERSION,
    )


@app.route("/update")
def update_page():
    return render_template_string(
        UPDATE_HTML,
        ip=config.HOTSPOT_IP,
        port=config.WEB_PORT,
        accent_hex=config.get_theme()["accent"],
        version=config.APP_VERSION,
    )


@app.route("/diagnostics")
def diagnostics_page():
    return render_template_string(
        DIAGNOSTICS_HTML,
        ip=config.HOTSPOT_IP,
        port=config.WEB_PORT,
        accent_hex=config.get_theme()["accent"],
        version=config.APP_VERSION,
    )


@app.route("/about")
def about_page():
    return render_template_string(
        ABOUT_HTML,
        ip=config.HOTSPOT_IP,
        port=config.WEB_PORT,
        ssid=config.HOTSPOT_SSID,
        accent_hex=config.get_theme()["accent"],
        version=config.APP_VERSION,
    )


@app.route("/api/diagnostics")
def api_diagnostics():
    diag = obd_reader.get_diagnostics()
    diag["system"] = _get_system_info()
    return jsonify(diag)


@app.route("/api/data")
def api_data():
    return jsonify(obd_reader.get_data())


@app.route("/api/stream")
def api_stream():
    return Response(
        _sse_stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.route("/api/dtcs")
def api_dtcs():
    data = obd_reader.get_data()
    return jsonify({"count": data.get("dtc_count", 0), "mil_on": data.get("mil_on", False), "dtcs": data.get("dtcs", [])})


@app.route("/api/status")
def api_status():
    data = obd_reader.get_data()
    return jsonify({"connected": data.get("connected", False), "status": data.get("status", "Unknown"), "last_update": data.get("last_update")})


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    return jsonify(config.get_current_settings())


@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    body = request.get_json(silent=True)
    if not body or not isinstance(body, dict):
        return jsonify({"error": "Expected JSON object in request body"}), 400
    saved, errors, messages = [], {}, {}
    for key, raw_value in body.items():
        ok, msg = config.save_setting(key, str(raw_value))
        if ok:
            saved.append(key)
            messages[key] = msg
        else:
            errors[key] = msg
    return jsonify({"saved": saved, "errors": errors, "messages": messages})


@app.route("/api/bt-scan", methods=["POST"])
def api_bt_scan():
    """Scan for nearby Bluetooth devices. Supports Linux (bluetoothctl) and macOS (system_profiler)."""
    try:
        if platform.system() == "Darwin":
            return _bt_scan_macos()
        return _bt_scan_linux()
    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Bluetooth scan timed out"})
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "Bluetooth tools not found"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})


def _bt_scan_linux():
    """Scan using bluetoothctl (Raspberry Pi / Linux)."""
    subprocess.run(
        ["bluetoothctl"], input="power on\nscan on\n",
        capture_output=True, text=True, timeout=3,
    )
    time.sleep(6)
    proc = subprocess.run(
        ["bluetoothctl"], input="scan off\ndevices\n",
        capture_output=True, text=True, timeout=5,
    )
    output = proc.stdout + proc.stderr
    devices = []
    seen = set()
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("Device "):
            parts = line.split(" ", 2)
            mac = parts[1] if len(parts) >= 2 else None
            name = parts[2] if len(parts) >= 3 else mac
            if mac and mac not in seen:
                seen.add(mac)
                devices.append({"mac": mac, "name": name})
    return jsonify({"ok": True, "devices": devices})


def _bt_scan_macos():
    """Scan using blueutil --inquiry for discovery, fallback to system_profiler."""
    devices = []
    seen = set()

    # Try blueutil discovery scan (finds nearby devices)
    try:
        proc = subprocess.run(
            ["blueutil", "--inquiry", "5"],
            capture_output=True, text=True, timeout=15,
        )
        for line in proc.stdout.strip().splitlines():
            # Format: address: AA-BB-CC-DD-EE-FF, name: "DeviceName", ...
            parts = {}
            for segment in line.split(", "):
                if ": " in segment:
                    k, v = segment.split(": ", 1)
                    parts[k.strip()] = v.strip().strip('"')
            mac = parts.get("address", "").replace("-", ":")
            name = parts.get("name", mac) or mac
            if mac and mac not in seen:
                seen.add(mac)
                devices.append({"mac": mac, "name": name})
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Also include known/paired devices from system_profiler
    try:
        proc = subprocess.run(
            ["system_profiler", "SPBluetoothDataType", "-json"],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(proc.stdout)
        bt_data = data.get("SPBluetoothDataType", [{}])[0]
        for section_key in ("device_connected", "device_not_connected"):
            for device_group in bt_data.get(section_key, []):
                if isinstance(device_group, dict):
                    for name, info in device_group.items():
                        mac = info.get("device_address", "").replace("-", ":")
                        if mac and mac not in seen:
                            seen.add(mac)
                            devices.append({"mac": mac, "name": name})
    except (json.JSONDecodeError, KeyError, IndexError, subprocess.TimeoutExpired):
        pass

    return jsonify({"ok": True, "devices": devices})


@app.route("/api/restart", methods=["POST"])
def api_restart():
    def _do_restart():
        time.sleep(1.5)
        logger.info("Restarting SignalKit service via API request")
        os.system("sudo systemctl restart signalkit 2>/dev/null || sudo kill -SIGTERM 1")
    threading.Thread(target=_do_restart, daemon=True).start()
    return jsonify({"ok": True, "message": "Restarting in 1.5 seconds"})


@app.route("/api/update", methods=["GET"])
def api_update_get():
    return jsonify(_git_info())


@app.route("/api/update", methods=["POST"])
def api_update_post():
    result = _git_pull()
    if result["status"] == "updated":
        def _do_restart():
            time.sleep(2.0)
            logger.info("Restarting SignalKit after OTA update")
            os.system("sudo systemctl restart signalkit 2>/dev/null || sudo kill -SIGTERM 1")
        threading.Thread(target=_do_restart, daemon=True).start()
    elif result["status"] == "reboot_required":
        def _do_reboot():
            time.sleep(2.0)
            logger.info("Rebooting Pi to apply OTA update (overlayfs toggle)")
            os.system("sudo reboot")
        threading.Thread(target=_do_reboot, daemon=True).start()
    return jsonify(result)


# ---------------------------------------------------------------------------
# Dev Console (raw OBD command terminal)
# ---------------------------------------------------------------------------

DEV_HTML = """<!DOCTYPE html>
<html lang="en" class="dark" style="background:#0a0a0a">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
  <meta name="theme-color" content="#0a0a0a">
  <title>SignalKit Dev Console</title>
  """ + SHARED_HEAD + """
  <style>
    #terminal { font-family: 'SF Mono', 'Menlo', 'Monaco', 'Courier New', monospace; }
    #terminal .cmd { color: #3b82f6; }
    #terminal .resp { color: #22c55e; }
    #terminal .err { color: #ef4444; }
    #terminal .info { color: #71717a; }
    #cmd-input { font-family: 'SF Mono', 'Menlo', 'Monaco', 'Courier New', monospace; }
  </style>
</head>
<body>
  <!-- Header -->
  <div class="flex justify-between items-center px-4 py-2.5 bg-zinc-900 border-b border-zinc-800 sticky top-0 z-50">
    <h1 class="text-sm font-bold tracking-widest flex items-center gap-2">
      <span class="w-2 h-2 bg-acc rounded-full shadow-[0_0_8px_var(--accent)]"></span>SIGNALKIT
    </h1>
    <nav class="flex gap-0.5 bg-zinc-800 rounded-lg p-0.5">
      <a href="/" class="text-xs font-semibold px-3 py-1 rounded-md text-zinc-400 hover:text-white">Dashboard</a>
      <a href="/settings" class="text-xs font-semibold px-3 py-1 rounded-md text-zinc-400 hover:text-white">Settings</a>
      <a href="/diagnostics" class="text-xs font-semibold px-3 py-1 rounded-md text-zinc-400 hover:text-white">Diag</a>
      <a href="/dev" class="text-xs font-semibold px-3 py-1 rounded-md bg-acc text-white">Dev</a>
    </nav>
  </div>

  <div class="max-w-[700px] mx-auto p-4">

    <!-- Info -->
    <div class="bg-amber-500/10 border border-amber-500/20 rounded-xl p-4 mb-4">
      <div class="flex items-start gap-2.5">
        <svg class="w-5 h-5 text-amber-400 shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z"/></svg>
        <div>
          <div class="text-sm font-semibold text-amber-300">Development Mode</div>
          <div class="text-xs text-amber-200/70 mt-0.5 leading-relaxed">Send raw OBD-II / ELM327 commands directly to the adapter. Incorrect commands won't damage your car but may temporarily confuse the adapter.</div>
        </div>
      </div>
    </div>

    <!-- Connection status -->
    <div class="flex items-center gap-2 mb-4">
      <span class="w-2 h-2 rounded-full" id="dev-dot"></span>
      <span class="text-xs text-zinc-500" id="dev-status">Checking...</span>
    </div>

    <!-- Quick commands -->
    <div class="mb-4">
      <div class="text-xs font-semibold tracking-widest uppercase text-zinc-500 mb-2">Quick Commands</div>
      <div class="flex flex-wrap gap-1.5">
        <button onclick="sendQuick('ATZ')" class="text-xs bg-zinc-800 border border-zinc-700 text-zinc-300 px-2.5 py-1.5 rounded-lg hover:bg-zinc-700 transition-colors">ATZ (Reset)</button>
        <button onclick="sendQuick('ATI')" class="text-xs bg-zinc-800 border border-zinc-700 text-zinc-300 px-2.5 py-1.5 rounded-lg hover:bg-zinc-700 transition-colors">ATI (ID)</button>
        <button onclick="sendQuick('ATRV')" class="text-xs bg-zinc-800 border border-zinc-700 text-zinc-300 px-2.5 py-1.5 rounded-lg hover:bg-zinc-700 transition-colors">ATRV (Voltage)</button>
        <button onclick="sendQuick('ATDP')" class="text-xs bg-zinc-800 border border-zinc-700 text-zinc-300 px-2.5 py-1.5 rounded-lg hover:bg-zinc-700 transition-colors">ATDP (Protocol)</button>
        <button onclick="sendQuick('0100')" class="text-xs bg-zinc-800 border border-zinc-700 text-zinc-300 px-2.5 py-1.5 rounded-lg hover:bg-zinc-700 transition-colors">0100 (PIDs 01-20)</button>
        <button onclick="sendQuick('0120')" class="text-xs bg-zinc-800 border border-zinc-700 text-zinc-300 px-2.5 py-1.5 rounded-lg hover:bg-zinc-700 transition-colors">0120 (PIDs 21-40)</button>
        <button onclick="sendQuick('0140')" class="text-xs bg-zinc-800 border border-zinc-700 text-zinc-300 px-2.5 py-1.5 rounded-lg hover:bg-zinc-700 transition-colors">0140 (PIDs 41-60)</button>
        <button onclick="sendQuick('010C')" class="text-xs bg-zinc-800 border border-zinc-700 text-zinc-300 px-2.5 py-1.5 rounded-lg hover:bg-zinc-700 transition-colors">010C (RPM)</button>
        <button onclick="sendQuick('010D')" class="text-xs bg-zinc-800 border border-zinc-700 text-zinc-300 px-2.5 py-1.5 rounded-lg hover:bg-zinc-700 transition-colors">010D (Speed)</button>
        <button onclick="sendQuick('0105')" class="text-xs bg-zinc-800 border border-zinc-700 text-zinc-300 px-2.5 py-1.5 rounded-lg hover:bg-zinc-700 transition-colors">0105 (Coolant)</button>
        <button onclick="sendQuick('03')" class="text-xs bg-zinc-800 border border-zinc-700 text-zinc-300 px-2.5 py-1.5 rounded-lg hover:bg-zinc-700 transition-colors">03 (DTCs)</button>
      </div>
    </div>

    <!-- Terminal -->
    <div class="bg-zinc-900 border border-zinc-800 rounded-xl overflow-hidden">
      <div class="flex items-center justify-between px-4 py-2 border-b border-zinc-800">
        <span class="text-xs font-semibold tracking-widest uppercase text-zinc-500">Terminal</span>
        <button onclick="clearTerminal()" class="text-xs text-zinc-500 hover:text-zinc-300 transition-colors">Clear</button>
      </div>
      <div id="terminal" class="p-4 h-[400px] overflow-y-auto text-sm leading-relaxed"></div>
      <div class="flex border-t border-zinc-800">
        <span class="text-acc font-mono text-sm px-3 py-3 select-none">&gt;</span>
        <input type="text" id="cmd-input" class="flex-1 bg-transparent text-sm text-zinc-100 py-3 pr-3 outline-none placeholder-zinc-600" placeholder="Enter OBD command (e.g. 010C, ATZ, 2201...)" autocomplete="off" autocapitalize="characters" spellcheck="false">
        <button onclick="sendCommand()" id="send-btn" class="px-4 text-sm font-semibold text-acc hover:text-white transition-colors">Send</button>
      </div>
    </div>

    <!-- Reference -->
    <div class="bg-zinc-900 border border-zinc-800 rounded-xl p-4 mt-4">
      <div class="text-xs font-semibold tracking-widest uppercase text-zinc-500 mb-2">OBD-II Mode Reference</div>
      <div class="grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
        <div class="flex justify-between py-1 border-b border-zinc-800"><span class="text-zinc-400">01</span><span class="text-zinc-500">Current data</span></div>
        <div class="flex justify-between py-1 border-b border-zinc-800"><span class="text-zinc-400">02</span><span class="text-zinc-500">Freeze frame</span></div>
        <div class="flex justify-between py-1 border-b border-zinc-800"><span class="text-zinc-400">03</span><span class="text-zinc-500">Read DTCs</span></div>
        <div class="flex justify-between py-1 border-b border-zinc-800"><span class="text-zinc-400">04</span><span class="text-zinc-500">Clear DTCs</span></div>
        <div class="flex justify-between py-1 border-b border-zinc-800"><span class="text-zinc-400">09</span><span class="text-zinc-500">Vehicle info (VIN)</span></div>
        <div class="flex justify-between py-1 border-b border-zinc-800"><span class="text-zinc-400">22</span><span class="text-zinc-500">Extended PIDs</span></div>
        <div class="flex justify-between py-1 border-b border-zinc-800"><span class="text-zinc-400">AT</span><span class="text-zinc-500">ELM327 commands</span></div>
        <div class="flex justify-between py-1"><span class="text-zinc-400">ST</span><span class="text-zinc-500">STN commands</span></div>
      </div>
    </div>
  </div>

  <div class="text-center py-4 text-xs text-zinc-600 border-t border-zinc-800">
    SignalKit v{{ version }} &middot; <a href="/" class="text-zinc-400 hover:text-acc">Dashboard</a> &middot; {{ ip }}:{{ port }}
  </div>

  <script>
    const terminal = document.getElementById('terminal');
    const input = document.getElementById('cmd-input');
    const sendBtn = document.getElementById('send-btn');
    const history = [];
    let historyIndex = -1;

    function appendLine(text, cls) {
      const line = document.createElement('div');
      line.className = cls || '';
      line.textContent = text;
      terminal.appendChild(line);
      terminal.scrollTop = terminal.scrollHeight;
    }

    function clearTerminal() {
      terminal.innerHTML = '';
      appendLine('Terminal cleared.', 'info');
    }

    async function checkStatus() {
      try {
        const r = await fetch('/api/status');
        const d = await r.json();
        const dot = document.getElementById('dev-dot');
        const status = document.getElementById('dev-status');
        if (d.connected) {
          dot.style.background = '#22c55e';
          dot.style.boxShadow = '0 0 6px #22c55e';
          status.textContent = 'Connected to OBD adapter';
          status.className = 'text-xs text-emerald-400';
        } else {
          dot.style.background = '#ef4444';
          dot.style.boxShadow = '0 0 6px #ef4444';
          status.textContent = d.status || 'Disconnected';
          status.className = 'text-xs text-red-400';
        }
      } catch(e) {}
    }

    async function sendCommand() {
      const cmd = input.value.trim();
      if (!cmd) return;

      history.unshift(cmd);
      historyIndex = -1;
      input.value = '';

      appendLine('> ' + cmd, 'cmd');
      sendBtn.textContent = '...';
      input.disabled = true;

      try {
        const r = await fetch('/api/dev/command', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({command: cmd})
        });
        const d = await r.json();

        if (d.ok) {
          if (d.response) {
            d.response.split('\\n').forEach(line => {
              if (line.trim()) appendLine(line.trim(), 'resp');
            });
          } else {
            appendLine('(empty response)', 'info');
          }
        } else {
          appendLine('ERROR: ' + (d.error || 'Unknown error'), 'err');
        }
      } catch(e) {
        appendLine('ERROR: ' + e.message, 'err');
      }

      sendBtn.textContent = 'Send';
      input.disabled = false;
      input.focus();
    }

    function sendQuick(cmd) {
      input.value = cmd;
      sendCommand();
    }

    input.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        sendCommand();
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (historyIndex < history.length - 1) {
          historyIndex++;
          input.value = history[historyIndex];
        }
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (historyIndex > 0) {
          historyIndex--;
          input.value = history[historyIndex];
        } else {
          historyIndex = -1;
          input.value = '';
        }
      }
    });

    appendLine('SignalKit Dev Console ready.', 'info');
    appendLine('Type an OBD command (e.g. 010C) or ELM327 command (e.g. ATZ) and press Enter.', 'info');
    checkStatus();
    setInterval(checkStatus, 5000);
    input.focus();
  </script>
</body>
</html>
"""


@app.route("/dev")
def dev_page():
    return render_template_string(
        DEV_HTML,
        ip=config.HOTSPOT_IP,
        port=config.WEB_PORT,
        accent_hex=config.get_theme()["accent"],
        version=config.APP_VERSION,
    )


@app.route("/api/dev/command", methods=["POST"])
def api_dev_command():
    body = request.get_json(silent=True)
    if not body or "command" not in body:
        return jsonify({"ok": False, "error": "Missing 'command' in request body"}), 400
    result = obd_reader.send_raw_command(body["command"])
    return jsonify(result)


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def run_server():
    logger.info(f"Starting web server on {config.WEB_HOST}:{config.WEB_PORT}")
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False, use_reloader=False, threaded=True)
