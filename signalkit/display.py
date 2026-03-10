# =============================================================================
# display.py - HDMI Dashboard Display (pywebview + Tailwind CSS)
# =============================================================================
# Renders a full-screen car dashboard on the HDMI output using pywebview.
# The HTML is rendered locally with no network dependencies — data flows
# through pywebview's JS-Python bridge (window.pywebview.api).
#
# Styling uses Tailwind CSS (play CDN) bundled locally in signalkit/static/
# for fully offline operation.
#
# Requires: pywebview (pip install pywebview)
# =============================================================================

import json
import logging
import os
import socket
import subprocess
import time

import webview

import config as app_config
import obd_reader

logger = logging.getLogger(__name__)

_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Load bundled Tailwind play CDN for inline embedding
# ---------------------------------------------------------------------------

def _load_asset(filename):
    path = os.path.join(_DIR, "static", filename)
    try:
        with open(path, "r") as f:
            return f.read()
    except FileNotFoundError:
        logger.warning(f"Asset not found: {path}")
        return ""


_TAILWIND_JS = _load_asset("tailwind.js")


# ---------------------------------------------------------------------------
# JS-Python Bridge — exposed to JavaScript as window.pywebview.api
# ---------------------------------------------------------------------------

class Api:
    """Methods callable from JavaScript via window.pywebview.api."""

    def get_data(self):
        """Return current OBD2 data as a JSON string."""
        return json.dumps(obd_reader.get_data())

    def get_config(self):
        """Return display-relevant config values."""
        theme = app_config.get_theme()
        return json.dumps({
            "redline": app_config.RPM_REDLINE,
            "overheat_c": app_config.COOLANT_OVERHEAT_C,
            "low_v": app_config.BATTERY_LOW_V,
            "critical_v": app_config.BATTERY_CRITICAL_V,
            "units_speed": app_config.UNITS_SPEED,
            "units_temp": app_config.UNITS_TEMP,
            "time_24hr": app_config.TIME_24HR,
            "accent": theme["accent"],
            "accent_glow": theme["glow"],
            "show_sparklines": app_config.SHOW_SPARKLINES,
        })

    def is_setup_complete(self):
        """Check if setup wizard has been completed."""
        return not _needs_setup()


# ---------------------------------------------------------------------------
# Build the complete HTML document
# ---------------------------------------------------------------------------

def _needs_setup():
    """Check if the first-run setup wizard hasn't been completed."""
    return (getattr(app_config, "SETUP_COMPLETE", 1) == 0
            and getattr(app_config, "OBD_MAC", "") == "AA:BB:CC:DD:EE:FF")


def _get_local_ip():
    """Get the machine's actual LAN/hotspot IP address."""
    try:
        # Connect to a dummy address to determine which interface is active
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return getattr(app_config, "HOTSPOT_IP", "192.168.4.1")


def _build_setup_html():
    """Build an HDMI screen guiding the user to complete setup via phone."""
    theme = app_config.get_theme()
    accent = theme["accent"]
    glow = theme["glow"]
    ssid = getattr(app_config, "HOTSPOT_SSID", "SignalKit")
    password = getattr(app_config, "HOTSPOT_PASSWORD", "signalkit1234")
    ip = _get_local_ip()
    port = getattr(app_config, "WEB_PORT", 8080)
    return f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
<meta charset="UTF-8">
<script>{_TAILWIND_JS}</script>
<script>
tailwind.config = {{
  darkMode: 'class',
  theme: {{ extend: {{ colors: {{ sk: {{ bg: '#0a0a0a' }} }} }} }}
}};
</script>
<style>
  :root {{ --accent: {accent}; --accent-glow: {glow}; }}
  * {{ box-sizing: border-box; }}
  body {{
    background: #0a0a0a; color: #ffffff;
    width: 800px; height: 480px; overflow: hidden; cursor: none;
    margin: 0; padding: 0;
    font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif;
    -webkit-font-smoothing: antialiased;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
  }}
  .accent {{ color: var(--accent); }}
  .glow {{ text-shadow: 0 0 20px var(--accent-glow); }}
  .step {{
    display: flex; align-items: flex-start; gap: 14px;
    padding: 10px 16px; margin: 6px 0;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 10px;
  }}
  .step-num {{
    width: 28px; height: 28px; border-radius: 50%;
    background: var(--accent); color: #0a0a0a;
    display: flex; align-items: center; justify-content: center;
    font-weight: 800; font-size: 0.85rem; flex-shrink: 0;
    margin-top: 2px;
  }}
  .pulse {{
    animation: pulse 2s ease-in-out infinite;
  }}
  @keyframes pulse {{
    0%, 100% {{ opacity: 1; }}
    50% {{ opacity: 0.5; }}
  }}
</style>
</head>
<body>

<div class="text-center mb-6">
  <div style="display:flex;justify-content:center;margin-bottom:8px;">
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="12 14 220 42" width="280" height="56">
      <rect x="16" y="44" width="6" height="8" rx="2" fill="{accent}" opacity="0.32"/>
      <rect x="25" y="38" width="6" height="14" rx="2" fill="{accent}" opacity="0.55"/>
      <rect x="34" y="30" width="6" height="22" rx="2" fill="{accent}" opacity="0.78"/>
      <rect x="43" y="20" width="6" height="32" rx="2" fill="{accent}"/>
      <text x="60" y="44" font-family="'Arial Black','Helvetica Neue',sans-serif" font-weight="800" font-size="32" letter-spacing="-0.5" fill="#ffffff">Signal</text>
      <text x="178" y="44" font-family="'Arial Black','Helvetica Neue',sans-serif" font-weight="800" font-size="32" letter-spacing="-0.5" fill="{accent}">Kit</text>
    </svg>
  </div>
  <div class="text-sm text-zinc-400">Setup Required</div>
</div>

<div style="width: 520px;">
  <div class="step">
    <div class="step-num">1</div>
    <div>
      <div class="text-sm font-semibold">Connect to WiFi</div>
      <div class="text-xs text-zinc-400 mt-0.5">
        On your phone, connect to <span class="accent font-bold">{ssid}</span>
        {"&nbsp;&middot;&nbsp; Password: <span class='font-mono accent'>" + password + "</span>" if password else "&nbsp;&middot;&nbsp; <span class='text-zinc-500'>No password</span>"}
      </div>
    </div>
  </div>

  <div class="step">
    <div class="step-num">2</div>
    <div>
      <div class="text-sm font-semibold">Open Browser</div>
      <div class="text-xs text-zinc-400 mt-0.5">
        A setup page should open automatically. If not, go to <span class="accent font-bold font-mono">{ip}:{port}</span>
      </div>
    </div>
  </div>

  <div class="step">
    <div class="step-num">3</div>
    <div>
      <div class="text-sm font-semibold">Complete Setup</div>
      <div class="text-xs text-zinc-400 mt-0.5">
        Follow the wizard to select your OBD2 adapter and configure WiFi.
      </div>
    </div>
  </div>
</div>

<div class="mt-6 text-xs text-zinc-600 pulse">Waiting for setup&hellip;</div>

<script>
  // Poll config to detect when setup completes, then reload to show dashboard
  async function checkSetup() {{
    try {{
      const raw = await window.pywebview.api.get_config();
      const cfg = JSON.parse(raw);
      // get_config doesn't return setup_complete, so we use a dedicated method
      const done = await window.pywebview.api.is_setup_complete();
      if (done === true || done === 'true') {{
        window.location.reload();
      }}
    }} catch (e) {{}}
  }}
  window.addEventListener('pywebviewready', function() {{
    setInterval(checkSetup, 3000);
  }});
</script>

</body>
</html>"""


def _build_html():
    theme = app_config.get_theme()
    accent = theme["accent"]
    glow = theme["glow"]
    try:
        git_hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(__file__), stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        git_hash = "?"
    return f"""<!DOCTYPE html>
<html lang="en" class="dark">
<head>
<meta charset="UTF-8">
<script>{_TAILWIND_JS}</script>
<script>
tailwind.config = {{
  darkMode: 'class',
  theme: {{
    extend: {{
      colors: {{
        sk: {{ bg: '#0a0a0a', good: '#22c55e', warn: '#f59e0b', danger: '#ef4444' }}
      }}
    }}
  }}
}};
</script>
<style type="text/tailwindcss">
  @layer base {{
    :root {{
      --accent: {accent};
      --accent-glow: {glow};
    }}
    * {{ box-sizing: border-box; }}
    body {{
      background: #0a0a0a;
      width: 800px; height: 480px;
      overflow: hidden; cursor: none;
      margin: 0; padding: 0;
      font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif;
      color: #ffffff;
      -webkit-font-smoothing: antialiased;
    }}
  }}
  @layer components {{
    .dcard {{
      @apply bg-zinc-900 rounded-lg text-center relative overflow-hidden;
      border: 1px solid color-mix(in srgb, var(--accent) 25%, #2d2d3e);
    }}
    .dcard-label {{
      color: color-mix(in srgb, var(--accent) 70%, #9ca3af);
    }}
    .clr-good {{ color: #22c55e !important; }}
    .clr-warn {{ color: #f59e0b !important; }}
    .clr-danger {{ color: #ef4444 !important; }}
  }}
</style>
<style>
  /* --- Splash --- */
  #splash {{
    position: fixed; inset: 0; z-index: 1000;
    background: #0a0a0a;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    transition: opacity 0.8s ease-out;
  }}
  #splash.fade-out {{ opacity: 0; pointer-events: none; }}

  /* Expanding ring */
  .splash-ring {{
    position: absolute;
    width: 80px; height: 80px;
    border: 2px solid var(--accent);
    border-radius: 50%;
    opacity: 0;
    animation: ring-expand 2s ease-out 0.2s forwards;
  }}
  @keyframes ring-expand {{
    0% {{ transform: scale(0.3); opacity: 0.8; }}
    70% {{ opacity: 0.2; }}
    100% {{ transform: scale(3.5); opacity: 0; }}
  }}

  /* Center dot */
  .splash-dot {{
    width: 10px; height: 10px;
    background: var(--accent);
    border-radius: 50%;
    box-shadow: 0 0 20px var(--accent), 0 0 40px var(--accent-glow);
    margin-bottom: 20px;
    opacity: 0;
    animation: dot-appear 0.5s ease-out 0.1s forwards, pulse 1.5s ease-in-out 0.6s infinite;
  }}
  @keyframes dot-appear {{
    0% {{ transform: scale(0); opacity: 0; }}
    100% {{ transform: scale(1); opacity: 1; }}
  }}
  @keyframes pulse {{
    0%, 100% {{ transform: scale(1); opacity: 1; }}
    50% {{ transform: scale(1.3); opacity: 0.7; }}
  }}

  /* Three loading dots */
  .splash-dots {{
    display: flex; gap: 6px;
    margin-top: 16px;
    opacity: 0;
    animation: fade-in 0.4s ease-out 0.8s forwards;
  }}
  .splash-dots span {{
    width: 5px; height: 5px;
    background: var(--accent);
    border-radius: 50%;
    opacity: 0.3;
    animation: dot-blink 1.2s ease-in-out infinite;
  }}
  .splash-dots span:nth-child(2) {{ animation-delay: 0.2s; }}
  .splash-dots span:nth-child(3) {{ animation-delay: 0.4s; }}
  @keyframes dot-blink {{
    0%, 100% {{ opacity: 0.3; transform: scale(1); }}
    50% {{ opacity: 1; transform: scale(1.3); }}
  }}

  /* Text reveal */
  .splash-title {{
    opacity: 0;
    transform: translateY(8px);
    animation: text-up 0.6s ease-out 0.3s forwards;
  }}
  .splash-sub {{
    opacity: 0;
    animation: fade-in 0.5s ease-out 0.6s forwards;
  }}
  @keyframes text-up {{
    to {{ opacity: 1; transform: translateY(0); }}
  }}
  @keyframes fade-in {{
    to {{ opacity: 1; }}
  }}

  /* --- RPM bar --- */
  .rpm-track {{
    height: 4px; border-radius: 3px; overflow: hidden;
    margin-top: 3px; background: rgba(255,255,255,0.06);
  }}
  .rpm-fill {{
    height: 100%; border-radius: 3px;
    background: linear-gradient(90deg, var(--accent), color-mix(in srgb, var(--accent) 60%, white));
    transition: width 0.4s cubic-bezier(.4,0,.2,1);
    width: 0%;
  }}

  /* --- DTC items --- */
  .dtc-item {{
    display: inline-flex; align-items: center; gap: 4px;
    padding: 1px 6px; margin-right: 6px;
    border-radius: 4px; font-size: 0.6rem;
    background: rgba(239,68,68,0.08);
    border: 1px solid rgba(239,68,68,0.15);
    white-space: nowrap;
  }}

  /* --- Sparklines --- */
  .sparkline {{
    position: absolute; bottom: 2px; left: 4px; right: 4px;
    height: 18px; opacity: 0.25; pointer-events: none;
  }}
  .sparkline polyline {{
    fill: none; stroke: var(--accent); stroke-width: 1.2;
    stroke-linecap: round; stroke-linejoin: round;
  }}
</style>
</head>
<body>

<!-- Splash -->
<div id="splash">
  <div class="splash-ring"></div>
  <div class="splash-dot"></div>
  <div class="splash-title text-2xl font-extrabold tracking-widest" style="color:var(--accent)">SIGNALKIT</div>
  <div class="splash-sub text-xs text-zinc-500 mt-1 tracking-wide">OBD2 Dashboard</div>
  <div class="splash-dots"><span></span><span></span><span></span></div>
</div>

<!-- Status bar -->
<div class="flex items-center gap-2 px-2.5 h-[26px] bg-zinc-900 border-b border-zinc-800">
  <span id="status-dot" class="w-[7px] h-[7px] rounded-full bg-red-500 shrink-0 transition-all duration-300"></span>
  <span id="status-text" class="text-xs text-zinc-500">Connecting...</span>
  <span id="trip-bar" class="ml-auto flex items-center gap-3 text-[0.6rem] tabular-nums text-zinc-500">
    <span id="trip-time">--:--</span>
    <span id="trip-dist">-- mi</span>
    <span id="trip-avg-mpg">-- mpg</span>
  </span>
  <span class="w-px h-3 bg-zinc-700"></span>
  <span id="version-badge" class="text-[0.58rem] font-mono text-zinc-600">{git_hash}</span>
  <span class="w-px h-3 bg-zinc-700"></span>
  <span id="clock" class="text-xs text-zinc-500 tabular-nums">--:--</span>
</div>

<!-- Dashboard: CSS grid fills 480-26=454px exactly -->
<div class="grid gap-1 p-1" style="height:calc(480px - 26px); grid-template-rows: 2fr 1.2fr 1.2fr 0.8fr">
  <!-- Hero row: RPM + Speed -->
  <div class="grid gap-1" style="grid-template-columns:55fr 45fr">
    <div class="dcard flex flex-col justify-center p-1.5">
      <div class="text-[0.45rem] font-semibold tracking-widest uppercase dcard-label mb-px">RPM</div>
      <div class="text-[2.3rem] font-extrabold leading-none tabular-nums" id="val-rpm">---</div>
      <div class="rpm-track mt-2"><div class="rpm-fill" id="rpm-bar"></div></div>
      <svg class="sparkline" id="spark-rpm" viewBox="0 0 120 18" preserveAspectRatio="none"><polyline points=""/></svg>
    </div>
    <div class="dcard flex flex-col justify-center p-1.5">
      <div class="text-[0.45rem] font-semibold tracking-widest uppercase dcard-label mb-px">Speed</div>
      <div class="text-[2.8rem] font-extrabold leading-none tabular-nums" id="val-speed">---</div>
      <div class="text-[0.65rem] text-zinc-500 mt-px font-medium" id="unit-speed">MPH</div>
      <svg class="sparkline" id="spark-speed" viewBox="0 0 120 18" preserveAspectRatio="none"><polyline points=""/></svg>
    </div>
  </div>

  <!-- Metrics row -->
  <div class="grid grid-cols-4 gap-1">
    <div class="dcard flex flex-col justify-center py-1 px-1.5">
      <div class="text-[0.45rem] font-semibold tracking-widest uppercase dcard-label mb-px">Coolant</div>
      <div class="text-[1.6rem] font-bold leading-none tabular-nums transition-colors" id="val-coolant">---</div>
      <div class="text-[0.65rem] text-zinc-500 mt-px font-medium" id="unit-coolant">&deg;C</div>
      <div id="warn-coolant"></div>
      <svg class="sparkline" id="spark-coolant" viewBox="0 0 120 18" preserveAspectRatio="none"><polyline points=""/></svg>
    </div>
    <div class="dcard flex flex-col justify-center py-1 px-1.5">
      <div class="text-[0.45rem] font-semibold tracking-widest uppercase dcard-label mb-px">Battery</div>
      <div class="text-[1.6rem] font-bold leading-none tabular-nums transition-colors" id="val-battery">---</div>
      <div class="text-[0.65rem] text-zinc-500 mt-px font-medium">Volts</div>
      <div id="warn-battery"></div>
      <svg class="sparkline" id="spark-battery" viewBox="0 0 120 18" preserveAspectRatio="none"><polyline points=""/></svg>
    </div>
    <div class="dcard flex flex-col justify-center py-1 px-1.5">
      <div class="text-[0.45rem] font-semibold tracking-widest uppercase dcard-label mb-px">Throttle</div>
      <div class="text-[1.6rem] font-bold leading-none tabular-nums" id="val-throttle">---</div>
      <div class="text-[0.65rem] text-zinc-500 mt-px font-medium">%</div>
      <svg class="sparkline" id="spark-throttle" viewBox="0 0 120 18" preserveAspectRatio="none"><polyline points=""/></svg>
    </div>
    <div class="dcard flex flex-col justify-center py-1 px-1.5">
      <div class="text-[0.45rem] font-semibold tracking-widest uppercase dcard-label mb-px">Engine Load</div>
      <div class="text-[1.6rem] font-bold leading-none tabular-nums" id="val-load">---</div>
      <div class="text-[0.65rem] text-zinc-500 mt-px font-medium">%</div>
      <svg class="sparkline" id="spark-load" viewBox="0 0 120 18" preserveAspectRatio="none"><polyline points=""/></svg>
    </div>
  </div>

  <!-- Secondary row -->
  <div class="grid grid-cols-4 gap-1">
    <div class="dcard flex flex-col justify-center py-1 px-1.5">
      <div class="text-[0.45rem] font-semibold tracking-widest uppercase dcard-label mb-px">Intake Air</div>
      <div class="text-[1.5rem] font-bold leading-none tabular-nums" id="val-iat">---</div>
      <div class="text-[0.65rem] text-zinc-500 mt-px font-medium" id="unit-iat">&deg;C</div>
      <svg class="sparkline" id="spark-iat" viewBox="0 0 120 18" preserveAspectRatio="none"><polyline points=""/></svg>
    </div>
    <div class="dcard flex flex-col justify-center py-1 px-1.5">
      <div class="text-[0.45rem] font-semibold tracking-widest uppercase dcard-label mb-px">Oil Temp</div>
      <div class="text-[1.5rem] font-bold leading-none tabular-nums" id="val-oil">N/A</div>
      <div class="text-[0.65rem] text-zinc-500 mt-px font-medium" id="unit-oil">&deg;C</div>
      <svg class="sparkline" id="spark-oil" viewBox="0 0 120 18" preserveAspectRatio="none"><polyline points=""/></svg>
    </div>
    <div class="dcard flex flex-col justify-center py-1 px-1.5">
      <div class="text-[0.45rem] font-semibold tracking-widest uppercase dcard-label mb-px">Fuel Trim B1</div>
      <div class="text-[1.5rem] font-bold leading-none tabular-nums" id="val-stft">---</div>
      <div class="text-[0.65rem] text-zinc-500 mt-px font-medium" id="val-ltft">---</div>
      <svg class="sparkline" id="spark-stft" viewBox="0 0 120 18" preserveAspectRatio="none"><polyline points=""/></svg>
    </div>
    <div class="dcard flex flex-col justify-center py-1 px-1.5">
      <div class="text-[0.45rem] font-semibold tracking-widest uppercase dcard-label mb-px">Fuel Economy</div>
      <div class="text-[1.5rem] font-bold leading-none tabular-nums" id="val-mpg">---</div>
      <div class="text-[0.65rem] text-zinc-500 mt-px font-medium">MPG</div>
      <svg class="sparkline" id="spark-mpg" viewBox="0 0 120 18" preserveAspectRatio="none"><polyline points=""/></svg>
    </div>
  </div>

  <!-- DTC section -->
  <div class="dcard flex items-center px-2.5 py-0.5 text-left overflow-hidden">
    <div class="text-[0.45rem] font-semibold tracking-widest uppercase dcard-label shrink-0 mr-2">Fault Codes</div>
    <div id="dtc-list" class="flex items-center overflow-x-auto gap-0" style="scrollbar-width:none"><span class="text-[0.6rem] text-emerald-500">No active fault codes</span></div>
  </div>
</div>

<script>
  let CFG = {{}};
  let pollTimer = null;

  function fmt(val, dec, fb) {{
    fb = fb || '---';
    return (val === null || val === undefined) ? fb : Number(val).toFixed(dec);
  }}
  function toF(c) {{ return c * 9/5 + 32; }}
  function toKmh(mph) {{ return mph * 1.60934; }}
  function convSpeed(v) {{ return CFG.units_speed === 'kmh' ? toKmh(v) : v; }}
  function convTemp(v) {{ return CFG.units_temp === 'F' ? toF(v) : v; }}
  function setColor(el, cls) {{
    el.className = el.className.replace(/clr-\\w+/g, '').trim();
    if (cls) el.classList.add(cls);
  }}

  // --- Sparkline history ---
  const SPARK_MAX = 120; // ~60s at 500ms poll
  const _hist = {{
    rpm: [], speed: [], coolant: [], battery: [],
    throttle: [], load: [], iat: [], oil: [], stft: [], mpg: []
  }};

  function sparkPush(key, val) {{
    if (val === null || val === undefined) return;
    const arr = _hist[key];
    arr.push(Number(val));
    if (arr.length > SPARK_MAX) arr.shift();
  }}

  function sparkDraw(svgId, arr) {{
    if (arr.length < 2) return;
    const svg = document.getElementById(svgId);
    if (!svg) return;
    const poly = svg.querySelector('polyline');
    const min = Math.min(...arr), max = Math.max(...arr);
    const range = max - min || 1;
    const w = 120, h = 18;
    const pts = arr.map((v, i) => {{
      const x = (i / (arr.length - 1)) * w;
      const y = h - ((v - min) / range) * (h - 1) - 0.5;
      return x.toFixed(1) + ',' + y.toFixed(1);
    }}).join(' ');
    poly.setAttribute('points', pts);
  }}

  function toggleSparklines(show) {{
    document.querySelectorAll('.sparkline').forEach(function(el) {{
      el.style.display = show ? '' : 'none';
    }});
  }}

  function updateSparklines() {{
    if (!CFG.show_sparklines) return;
    sparkDraw('spark-rpm', _hist.rpm);
    sparkDraw('spark-speed', _hist.speed);
    sparkDraw('spark-coolant', _hist.coolant);
    sparkDraw('spark-battery', _hist.battery);
    sparkDraw('spark-throttle', _hist.throttle);
    sparkDraw('spark-load', _hist.load);
    sparkDraw('spark-iat', _hist.iat);
    sparkDraw('spark-oil', _hist.oil);
    sparkDraw('spark-stft', _hist.stft);
    sparkDraw('spark-mpg', _hist.mpg);
  }}

  function updateClock() {{
    const now = new Date();
    let h = now.getHours(), m = now.getMinutes();
    let str;
    if (CFG.time_24hr) {{
      str = String(h).padStart(2,'0') + ':' + String(m).padStart(2,'0');
    }} else {{
      const ampm = h >= 12 ? 'PM' : 'AM';
      h = h % 12 || 12;
      str = h + ':' + String(m).padStart(2,'0') + ' ' + ampm;
    }}
    document.getElementById('clock').textContent = str;
  }}

  function applyData(d) {{
    const accentClr = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim();

    // Status
    const dot = document.getElementById('status-dot');
    dot.style.background = d.connected ? accentClr : '#ef4444';
    dot.style.boxShadow = d.connected ? '0 0 6px ' + accentClr : 'none';
    document.getElementById('status-text').textContent = d.status || '';

    // RPM
    const rpmEl = document.getElementById('val-rpm');
    rpmEl.textContent = d.rpm !== null && d.rpm !== undefined ? d.rpm.toLocaleString() : '---';
    const ratio = d.rpm ? Math.min(1, d.rpm / CFG.redline) : 0;
    const bar = document.getElementById('rpm-bar');
    bar.style.width = (ratio * 100) + '%';
    if (ratio >= 0.88) {{
      bar.style.background = 'linear-gradient(90deg, #f59e0b, #ef4444)';
      setColor(rpmEl, 'clr-danger');
    }} else if (ratio >= 0.7) {{
      bar.style.background = 'linear-gradient(90deg, ' + accentClr + ', #f59e0b)';
      setColor(rpmEl, '');
    }} else {{
      bar.style.background = '';
      setColor(rpmEl, '');
    }}

    // Speed
    document.getElementById('val-speed').textContent =
      d.speed !== null && d.speed !== undefined ? fmt(convSpeed(d.speed), 0) : '---';

    // Throttle / Load
    document.getElementById('val-throttle').textContent = fmt(d.throttle, 0);
    document.getElementById('val-load').textContent = fmt(d.engine_load, 0);

    // IAT
    document.getElementById('val-iat').textContent =
      d.intake_air_temp !== null && d.intake_air_temp !== undefined
        ? fmt(convTemp(d.intake_air_temp), 0) : '---';

    // Coolant
    const cEl = document.getElementById('val-coolant');
    const wc = document.getElementById('warn-coolant');
    cEl.textContent = d.coolant_temp !== null && d.coolant_temp !== undefined
      ? fmt(convTemp(d.coolant_temp), 0) : '---';
    if (d.coolant_temp !== null && d.coolant_temp >= CFG.overheat_c) {{
      setColor(cEl, 'clr-danger');
      wc.innerHTML = '<span class="inline-block bg-red-500/20 text-red-400 text-[0.5rem] font-bold px-1.5 py-0.5 rounded">OVERHEAT</span>';
    }} else if (d.coolant_temp !== null && d.coolant_temp >= 95) {{
      setColor(cEl, 'clr-warn');
      wc.innerHTML = '<span class="inline-block bg-amber-500/20 text-amber-400 text-[0.5rem] font-bold px-1.5 py-0.5 rounded">HIGH</span>';
    }} else {{
      setColor(cEl, 'clr-good'); wc.innerHTML = '';
    }}

    // Battery
    const bEl = document.getElementById('val-battery');
    const wb = document.getElementById('warn-battery');
    bEl.textContent = fmt(d.battery_voltage, 2);
    if (d.battery_voltage !== null && d.battery_voltage < CFG.critical_v) {{
      setColor(bEl, 'clr-danger');
      wb.innerHTML = '<span class="inline-block bg-red-500/20 text-red-400 text-[0.5rem] font-bold px-1.5 py-0.5 rounded">CRITICAL</span>';
    }} else if (d.battery_voltage !== null && d.battery_voltage < CFG.low_v) {{
      setColor(bEl, 'clr-warn');
      wb.innerHTML = '<span class="inline-block bg-amber-500/20 text-amber-400 text-[0.5rem] font-bold px-1.5 py-0.5 rounded">LOW</span>';
    }} else {{
      setColor(bEl, 'clr-good'); wb.innerHTML = '';
    }}

    // Oil
    const oEl = document.getElementById('val-oil');
    oEl.textContent = d.oil_temp !== null && d.oil_temp !== undefined
      ? fmt(convTemp(d.oil_temp), 0) : 'N/A';
    setColor(oEl, d.oil_temp !== null && d.oil_temp >= 130 ? 'clr-danger' :
                  d.oil_temp !== null && d.oil_temp >= 115 ? 'clr-warn' : '');

    // Fuel trim
    if (d.short_fuel_trim_1 !== null && d.short_fuel_trim_1 !== undefined) {{
      const s = d.short_fuel_trim_1, l = d.long_fuel_trim_1;
      const stEl = document.getElementById('val-stft');
      stEl.textContent = 'S: ' + (s >= 0 ? '+' : '') + s.toFixed(1) + '%';
      setColor(stEl, Math.abs(s) > 10 ? 'clr-warn' : '');
      if (l !== null && l !== undefined)
        document.getElementById('val-ltft').textContent =
          'L: ' + (l >= 0 ? '+' : '') + l.toFixed(1) + '%';
    }} else {{
      document.getElementById('val-stft').textContent = '---';
      document.getElementById('val-ltft').textContent = '---';
    }}

    // MPG
    const mpgEl = document.getElementById('val-mpg');
    if (d.mpg !== null && d.mpg !== undefined) {{
      mpgEl.textContent = Number(d.mpg).toFixed(1);
      setColor(mpgEl, d.mpg >= 25 ? 'clr-good' : d.mpg >= 15 ? '' : 'clr-warn');
    }} else {{
      mpgEl.textContent = '---';
      setColor(mpgEl, '');
    }}

    // DTCs
    const dtcList = document.getElementById('dtc-list');
    if (!d.dtcs || !d.dtcs.length) {{
      dtcList.innerHTML = '<span class="text-[0.6rem] text-emerald-500">No active fault codes</span>';
    }} else {{
      dtcList.innerHTML = d.dtcs.slice(0, 5).map(function(dtc) {{
        return '<span class="dtc-item" title="' + dtc.description + '">' +
          '<span class="font-bold font-mono text-red-400">' + dtc.code + '</span>' +
          '<span class="text-zinc-400">' + dtc.description + '</span>' +
          '</span>';
      }}).join('');
      if (d.dtcs.length > 5) {{
        dtcList.innerHTML += '<span class="text-[0.55rem] text-zinc-500 ml-1">+' +
          (d.dtcs.length - 5) + ' more</span>';
      }}
    }}

    // Push sparkline data
    sparkPush('rpm', d.rpm);
    sparkPush('speed', d.speed);
    sparkPush('coolant', d.coolant_temp);
    sparkPush('battery', d.battery_voltage);
    sparkPush('throttle', d.throttle);
    sparkPush('load', d.engine_load);
    sparkPush('iat', d.intake_air_temp);
    sparkPush('oil', d.oil_temp);
    sparkPush('stft', d.short_fuel_trim_1);
    sparkPush('mpg', d.mpg);
    updateSparklines();

    // Trip computer
    if (d.trip && d.trip.active) {{
      const s = d.trip.elapsed_s;
      const h = Math.floor(s / 3600);
      const m = Math.floor((s % 3600) / 60);
      document.getElementById('trip-time').textContent =
        h > 0 ? h + ':' + String(m).padStart(2, '0') : m + 'm';
      document.getElementById('trip-dist').textContent =
        d.trip.distance_mi.toFixed(1) + ' mi';
      document.getElementById('trip-avg-mpg').textContent =
        d.trip.avg_mpg > 0 ? d.trip.avg_mpg.toFixed(1) + ' mpg' : '-- mpg';
    }} else {{
      document.getElementById('trip-time').textContent = '--:--';
      document.getElementById('trip-dist').textContent = '-- mi';
      document.getElementById('trip-avg-mpg').textContent = '-- mpg';
    }}

    updateClock();
  }}

  // --- Poll data from Python via pywebview bridge ---
  let _cfgTick = 0;
  async function poll() {{
    try {{
      const raw = await window.pywebview.api.get_data();
      const d = JSON.parse(raw);
      applyData(d);
    }} catch (e) {{}}
    // Fallback: re-check config every ~5s in case evaluate_js push didn't fire
    _cfgTick++;
    if (_cfgTick >= 10) {{
      _cfgTick = 0;
      reloadConfig();
    }}
  }}

  // Called from Python via evaluate_js when a setting is changed
  async function reloadConfig() {{
    try {{
      const rawCfg = await window.pywebview.api.get_config();
      const newCfg = JSON.parse(rawCfg);
      if (newCfg.units_temp !== CFG.units_temp || newCfg.units_speed !== CFG.units_speed) {{
        const tempUnit = newCfg.units_temp === 'F' ? '\\u00b0F' : '\\u00b0C';
        document.getElementById('unit-speed').textContent = newCfg.units_speed === 'kmh' ? 'km/h' : 'MPH';
        document.getElementById('unit-coolant').innerHTML = tempUnit;
        document.getElementById('unit-iat').innerHTML = tempUnit;
        document.getElementById('unit-oil').innerHTML = tempUnit;
      }}
      // Update theme accent color
      if (newCfg.accent !== CFG.accent) {{
        document.documentElement.style.setProperty('--accent', newCfg.accent);
        document.documentElement.style.setProperty('--accent-glow', newCfg.accent_glow);
      }}
      // Toggle sparklines
      if (newCfg.show_sparklines !== CFG.show_sparklines) {{
        toggleSparklines(newCfg.show_sparklines);
      }}
      CFG = newCfg;
    }} catch (e) {{}}
  }}

  // --- Initialization ---
  async function init() {{
    try {{
      const rawCfg = await window.pywebview.api.get_config();
      CFG = JSON.parse(rawCfg);
    }} catch (e) {{
      CFG = {{ redline: 6500, overheat_c: 105, low_v: 12.0, critical_v: 11.5,
              units_speed: 'mph', units_temp: 'C', time_24hr: true }};
    }}

    const tempUnit = CFG.units_temp === 'F' ? '\\u00b0F' : '\\u00b0C';
    document.getElementById('unit-speed').textContent = CFG.units_speed === 'kmh' ? 'km/h' : 'MPH';
    document.getElementById('unit-coolant').innerHTML = tempUnit;
    document.getElementById('unit-iat').innerHTML = tempUnit;
    document.getElementById('unit-oil').innerHTML = tempUnit;
    toggleSparklines(CFG.show_sparklines);
    updateClock();

    setTimeout(function() {{
      document.getElementById('splash').classList.add('fade-out');
      setTimeout(function() {{ document.getElementById('splash').remove(); }}, 800);
    }}, 2500);

    pollTimer = setInterval(poll, 500);
  }}

  window.addEventListener('pywebviewready', init);
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

_window = None


def _build_error_html(error_msg, hint=""):
    """Build an error screen displayed on HDMI when something goes wrong."""
    theme = app_config.get_theme()
    accent = theme["accent"]
    # Escape HTML in the error message
    import html as html_mod
    safe_msg = html_mod.escape(str(error_msg))
    safe_hint = html_mod.escape(str(hint)) if hint else ""
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: #0a0a0a; color: #fff;
    width: 800px; height: 480px; overflow: hidden; cursor: none;
    font-family: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    padding: 40px;
  }}
  .icon {{ font-size: 48px; margin-bottom: 16px; }}
  .title {{ color: #ef4444; font-size: 20px; font-weight: 800; margin-bottom: 12px; }}
  .msg {{
    background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1);
    border-radius: 8px; padding: 16px 20px; max-width: 600px;
    font-family: monospace; font-size: 12px; color: #a1a1aa;
    word-break: break-word; white-space: pre-wrap; text-align: left;
    max-height: 200px; overflow-y: auto;
  }}
  .hint {{ color: #71717a; font-size: 12px; margin-top: 16px; text-align: center; }}
  .retry {{ color: {accent}; font-size: 13px; margin-top: 20px; animation: pulse 2s ease-in-out infinite; }}
  @keyframes pulse {{ 0%,100% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} }}
</style></head>
<body>
  <div class="icon">&#9888;</div>
  <div class="title">Something went wrong</div>
  <div class="msg">{safe_msg}</div>
  {"<div class='hint'>" + safe_hint + "</div>" if safe_hint else ""}
  <div class="retry">Restarting automatically&hellip;</div>
</body></html>"""


def run_display():
    """Entry point called from main.py. Blocks until the window is closed."""
    global _window
    api = Api()

    # Register callback so config changes push to the display instantly
    app_config._on_setting_changed = _on_setting_changed_handler

    try:
        if _needs_setup():
            html = _build_setup_html()
            logger.info("Showing setup guidance screen on HDMI")
        else:
            html = _build_html()
    except Exception as e:
        logger.error(f"Failed to build dashboard HTML: {e}", exc_info=True)
        html = _build_error_html(e, "The dashboard failed to render. Check journalctl -u signalkit for details.")

    # Show git hash in window title for desktop testing
    _title = "SignalKit Dashboard"
    try:
        _hash = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(__file__), stderr=subprocess.DEVNULL
        ).decode().strip()
        _title += f"  [{_hash}]"
    except Exception:
        pass

    _window = webview.create_window(
        _title,
        html=html,
        width=app_config.SCREEN_WIDTH,
        height=app_config.SCREEN_HEIGHT,
        fullscreen=app_config.FULLSCREEN,
        frameless=True,
        resizable=False,
        easy_drag=False,
        js_api=api,
        background_color='#0a0a0a',
    )

    webview.start(debug=False)


def _on_setting_changed_handler():
    """Handle config changes — reload dashboard or switch from setup to dashboard."""
    if _window:
        try:
            if not _needs_setup():
                # Setup just completed — load the full dashboard
                _window.load_html(_build_html())
                logger.info("Setup complete — switched HDMI to dashboard")
            else:
                _window.evaluate_js("(async()=>{await reloadConfig()})()")
                logger.debug("Pushed config reload to display")
        except Exception as e:
            logger.warning(f"Failed to update display: {e}")


def notify_config_changed():
    """Push a config reload to the pywebview display. Called from config.save_setting()."""
    _on_setting_changed_handler()


def show_shutdown_screen():
    """Replace the dashboard with a shutdown splash so the user never sees console logs."""
    if not _window:
        return
    theme = app_config.get_theme()
    accent = theme["accent"]
    glow = theme["glow"]
    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: #0a0a0a; color: #ffffff;
    width: 800px; height: 480px; overflow: hidden; cursor: none;
    font-family: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif;
    display: flex; flex-direction: column;
    align-items: center; justify-content: center;
    -webkit-font-smoothing: antialiased;
  }}
  .ring {{
    position: absolute;
    width: 60px; height: 60px;
    border: 2px solid {accent};
    border-radius: 50%;
    opacity: 0;
    animation: ring-expand 2s ease-out forwards;
  }}
  @keyframes ring-expand {{
    0% {{ transform: scale(0.5); opacity: 0.6; }}
    100% {{ transform: scale(4); opacity: 0; }}
  }}
  .dot {{
    width: 8px; height: 8px;
    background: {accent};
    border-radius: 50%;
    box-shadow: 0 0 15px {accent}, 0 0 30px {glow};
    margin-bottom: 20px;
    animation: dot-fade 1.5s ease-in-out infinite;
  }}
  @keyframes dot-fade {{
    0%, 100% {{ opacity: 1; transform: scale(1); }}
    50% {{ opacity: 0.4; transform: scale(0.8); }}
  }}
  .title {{
    font-size: 14px; font-weight: 600;
    letter-spacing: 3px; text-transform: uppercase;
    color: #71717a;
    margin-bottom: 6px;
  }}
  .sub {{
    font-size: 11px; color: #3f3f46;
    animation: fade-in 0.5s ease-out 0.3s both;
  }}
  @keyframes fade-in {{ to {{ opacity: 1; }} }}
  .fade-out {{
    animation: page-fade 1s ease-out 2s forwards;
  }}
  @keyframes page-fade {{
    to {{ opacity: 0; }}
  }}
</style></head>
<body class="fade-out">
  <div class="ring"></div>
  <div class="dot"></div>
  <div class="title">Shutting Down</div>
  <div class="sub" style="opacity:0">See you next drive</div>
</body></html>"""
    try:
        _window.load_html(html)
    except Exception:
        pass


def stop_display():
    """Stop the display from another thread."""
    global _window
    if _window:
        _window.destroy()
        _window = None
