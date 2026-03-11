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
    """Read a static asset file from the signalkit/static/ directory."""
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
            "obd_mac": getattr(app_config, "OBD_MAC", ""),
            "obd_bt_channel": getattr(app_config, "OBD_BT_CHANNEL", 1),
            "phone_bt_mac": getattr(app_config, "PHONE_BT_MAC", ""),
            "phone_bt_auto": getattr(app_config, "PHONE_BT_AUTO", 0),
            "fast_poll": getattr(app_config, "FAST_POLL_INTERVAL", 1.0),
            "slow_poll": getattr(app_config, "SLOW_POLL_INTERVAL", 10),
            "scan_pids": getattr(app_config, "SCAN_PIDS_ON_BOOT", 1),
            "color_theme": app_config.COLOR_THEME,
        })

    def is_setup_complete(self):
        """Check if setup wizard has been completed."""
        return not _needs_setup()

    def save_setting(self, key, value):
        """Save a config setting from the display settings view."""
        ok, msg = app_config.save_setting(key, value)
        return json.dumps({"ok": ok, "message": msg})

    def send_obd_command(self, cmd):
        """Send a raw OBD/ELM327 command and return the response."""
        result = obd_reader.send_raw_command(cmd)
        return json.dumps(result)

    def bt_scan(self):
        """Scan for nearby Bluetooth devices via the local Flask API."""
        try:
            import urllib.request
            port = getattr(app_config, "WEB_PORT", 8080)
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/bt-scan",
                method="POST",
                headers={"Content-Type": "application/json"},
                data=b"{}",
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                return resp.read().decode()
        except Exception as e:
            return json.dumps({"ok": False, "devices": [], "error": str(e)})

    def get_system_info(self):
        """Return system info for the about page."""
        info = {
            "version": app_config.APP_VERSION,
            "theme": app_config.COLOR_THEME,
            "obd_mac": getattr(app_config, "OBD_MAC", "Not set"),
            "ip": _get_local_ip(),
            "port": getattr(app_config, "WEB_PORT", 8080),
        }
        try:
            info["git_hash"] = subprocess.check_output(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=os.path.dirname(__file__), stderr=subprocess.DEVNULL
            ).decode().strip()
        except Exception:
            info["git_hash"] = "?"
        return json.dumps(info)


# ---------------------------------------------------------------------------
# Build the complete HTML document
# ---------------------------------------------------------------------------

def _needs_setup():
    """Check if the first-run setup wizard hasn't been completed."""
    return app_config.needs_setup()


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
    """Build the complete HDMI HTML with launcher home + dashboard views."""
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

  /* --- Persistent sidebar dock (CarPlay-style) --- */
  #dock {{
    position: absolute; top: 0; left: 0; width: 56px; height: 480px;
    background: #111113;
    border-right: 1px solid #27272a;
    display: flex; flex-direction: column;
    align-items: center; padding: 10px 0 8px;
    z-index: 80;
  }}
  .dock-btn {{
    width: 40px; height: 40px; border-radius: 12px;
    display: flex; align-items: center; justify-content: center;
    cursor: pointer; -webkit-tap-highlight-color: transparent;
    transition: background 0.15s, transform 0.1s;
    position: relative;
  }}
  .dock-btn:active {{ transform: scale(0.88); }}
  .dock-btn:hover {{ background: rgba(255,255,255,0.06); }}
  .dock-btn.active {{
    background: color-mix(in srgb, var(--accent) 20%, transparent);
  }}
  .dock-btn.active::before {{
    content: ''; position: absolute; left: -8px;
    width: 3px; height: 20px; border-radius: 0 3px 3px 0;
    background: var(--accent);
  }}
  .dock-spacer {{ flex: 1; }}
  .dock-label {{
    font-size: 0.4rem; color: #52525b; text-align: center;
    margin-top: 2px; letter-spacing: 0.3px; font-weight: 600;
  }}

  /* --- Main content area (right of dock) --- */
  #main-content {{
    position: absolute; top: 0; left: 56px; right: 0; bottom: 0;
    overflow: hidden;
  }}
  .view {{ display: none; width: 100%; height: 100%; position: absolute; inset: 0; }}
  .view.active {{ display: flex; flex-direction: column; }}
  .view-enter {{ animation: viewFadeIn 0.2s ease-out; }}
  @keyframes viewFadeIn {{
    from {{ opacity: 0; }}
    to {{ opacity: 1; }}
  }}

  /* --- Home view (inside main content) --- */
  #view-home {{
    align-items: center; justify-content: center;
    background: #0a0a0a;
  }}
  .app-grid {{
    display: grid; grid-template-columns: repeat(4, 76px);
    gap: 24px 32px; justify-content: center;
  }}
  .app-icon {{
    display: flex; flex-direction: column; align-items: center;
    gap: 8px; cursor: pointer; -webkit-tap-highlight-color: transparent;
    transition: transform 0.15s ease;
  }}
  .app-icon:active {{ transform: scale(0.9); }}
  .app-tile {{
    width: 60px; height: 60px; border-radius: 14px;
    display: flex; align-items: center; justify-content: center;
    transition: transform 0.2s ease;
  }}
  .app-icon:hover .app-tile {{ transform: scale(1.08); }}
  .app-label {{
    font-size: 0.6rem; font-weight: 600; color: #a1a1aa;
    text-align: center; white-space: nowrap;
  }}

  /* --- Settings view (Apple split-panel) --- */
  .settings-split {{
    display: flex; flex: 1; overflow: hidden;
  }}
  .settings-sidebar {{
    width: 140px; min-width: 140px;
    background: #111113; border-right: 1px solid #27272a;
    padding: 8px 0; overflow-y: auto; scrollbar-width: none;
    display: flex; flex-direction: column;
  }}
  .settings-tab {{
    display: flex; align-items: center; gap: 8px;
    padding: 9px 14px; cursor: pointer;
    font-size: 0.65rem; font-weight: 600; color: #71717a;
    border-radius: 0; border-left: 2px solid transparent;
    transition: background 0.15s, color 0.15s;
    -webkit-tap-highlight-color: transparent;
  }}
  .settings-tab:active {{ background: #1c1c1e; }}
  .settings-tab.active {{
    background: color-mix(in srgb, var(--accent) 10%, transparent);
    color: #e4e4e7; border-left-color: var(--accent);
  }}
  .settings-tab svg {{ width: 16px; height: 16px; flex-shrink: 0; }}
  .settings-panel {{
    flex: 1; overflow-y: auto; padding: 14px 18px;
    scrollbar-width: none; display: none;
  }}
  .settings-panel.active {{ display: block; }}
  .settings-section-label {{
    font-size: 0.55rem; font-weight: 600; letter-spacing: 0.08em;
    text-transform: uppercase; color: #52525b; margin-bottom: 8px;
  }}
  .settings-row {{
    display: flex; align-items: center; justify-content: space-between;
    padding: 10px 0; border-bottom: 1px solid #1c1c1e;
  }}
  .settings-row:last-child {{ border-bottom: none; }}
  .settings-row-label {{
    font-size: 0.65rem; font-weight: 500; color: #a1a1aa;
  }}
  .settings-row-value {{
    display: flex; gap: 4px; align-items: center;
  }}
  .swatch {{
    width: 28px; height: 28px; border-radius: 8px;
    cursor: pointer; border: 2px solid transparent;
    transition: transform 0.1s, border-color 0.2s;
    -webkit-tap-highlight-color: transparent;
  }}
  .swatch:active {{ transform: scale(0.9); }}
  .swatch.active {{ border-color: #fff; }}
  .setting-btn {{
    font-size: 0.6rem; font-weight: 600;
    padding: 6px 14px; border-radius: 8px;
    background: #18181b; border: 1px solid #27272a;
    color: #a1a1aa; cursor: pointer;
    transition: all 0.15s;
    -webkit-tap-highlight-color: transparent;
  }}
  .setting-btn.small {{ padding: 5px 10px; font-size: 0.55rem; }}
  .setting-btn:active {{ transform: scale(0.92); }}
  .setting-btn.active {{
    background: color-mix(in srgb, var(--accent) 20%, transparent);
    border-color: var(--accent);
    color: #fff;
  }}

  /* --- Dev console --- */
  .dev-qbtn {{
    font-size: 0.6rem; font-weight: 600; font-family: monospace;
    padding: 5px 10px; border-radius: 8px;
    background: #18181b; border: 1px solid #27272a;
    color: #a1a1aa; cursor: pointer;
    transition: all 0.15s;
    -webkit-tap-highlight-color: transparent;
  }}
  .dev-qbtn:active {{ transform: scale(0.92); }}
  .kb-key {{
    min-width: 34px; height: 32px;
    font-size: 0.65rem; font-weight: 700; font-family: monospace;
    background: #1c1c1e; border: 1px solid #2a2a2e;
    border-radius: 6px; color: #d4d4d8;
    display: flex; align-items: center; justify-content: center;
    cursor: pointer; -webkit-tap-highlight-color: transparent;
    transition: background 0.1s, transform 0.08s;
  }}
  .kb-key:active {{ background: #3f3f46; transform: scale(0.92); }}
  .kb-key.wide {{ min-width: 44px; }}
  .dev-line {{ margin-bottom: 2px; word-break: break-all; }}
  .dev-cmd {{ color: #3b82f6; }}
  .dev-resp {{ color: #22c55e; }}
  .dev-err {{ color: #ef4444; }}
  .dev-info {{ color: #71717a; }}

  /* Toast */
  #toast {{
    position: fixed; bottom: 40px; left: 56px; right: 0;
    display: flex; justify-content: center;
    pointer-events: none; z-index: 90;
  }}
  #toast-inner {{
    background: rgba(39,39,42,0.95); border: 1px solid #52525b;
    border-radius: 10px; padding: 8px 20px;
    font-size: 0.75rem; color: #d4d4d8;
    opacity: 0; transition: opacity 0.3s;
    backdrop-filter: blur(8px); -webkit-backdrop-filter: blur(8px);
  }}
</style>
</head>
<body style="position:relative;overflow:hidden;width:800px;height:480px;margin:0;padding:0;background:#0a0a0a">

<!-- ===== PERSISTENT SIDEBAR DOCK ===== -->
<div id="dock">
  <!-- Home -->
  <div class="dock-btn active" data-view="home" onclick="switchView('home')" title="Home">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#a1a1aa" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      <path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>
    </svg>
  </div>
  <div class="dock-label">Home</div>

  <!-- Dashboard -->
  <div style="margin-top:10px"></div>
  <div class="dock-btn" data-view="dashboard" onclick="switchView('dashboard')" title="Dashboard">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="{accent}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      <path d="M13 10V3L4 14h7v7l9-11h-7z"/>
    </svg>
  </div>
  <div class="dock-label">OBD</div>

  <!-- Settings -->
  <div style="margin-top:10px"></div>
  <div class="dock-btn" data-view="settings" onclick="switchView('settings')" title="Settings">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#a1a1aa" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      <path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.573-1.066z"/>
      <circle cx="12" cy="12" r="3"/>
    </svg>
  </div>
  <div class="dock-label">Settings</div>

  <!-- Dev Console -->
  <div style="margin-top:10px"></div>
  <div class="dock-btn" data-view="dev" onclick="switchView('dev')" title="Dev Console">
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
      <path d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/>
    </svg>
  </div>
  <div class="dock-label">Dev</div>

  <div class="dock-spacer"></div>

  <!-- OBD status indicator -->
  <div style="display:flex;flex-direction:column;align-items:center;gap:3px;margin-bottom:4px">
    <span id="dock-obd-dot" style="width:7px;height:7px;border-radius:50%;background:#ef4444;transition:all 0.3s"></span>
    <span id="dock-clock" style="font-size:0.5rem;color:#52525b;font-variant-numeric:tabular-nums">--:--</span>
  </div>
</div>

<!-- ===== MAIN CONTENT AREA ===== -->
<div id="main-content">

<!-- Toast overlay -->
<div id="toast"><div id="toast-inner"></div></div>

<!-- ===== HOME VIEW ===== -->
<div id="view-home" class="view active" style="align-items:center;justify-content:center;background:#0a0a0a">

  <!-- App Grid -->
  <div class="app-grid">

    <!-- Dashboard -->
    <div class="app-icon" onclick="switchView('dashboard')">
      <div class="app-tile" style="background:linear-gradient(135deg, #064e3b, #065f46); border:1px solid #059669;">
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="#34d399" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
      </div>
      <span class="app-label">Dashboard</span>
    </div>

    <!-- Settings -->
    <div class="app-icon" onclick="switchView('settings')">
      <div class="app-tile" style="background:linear-gradient(135deg, #1c1c1e, #2a2a2e); border:1px solid #3f3f46;">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#a1a1aa" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.573-1.066z"/>
          <circle cx="12" cy="12" r="3"/>
        </svg>
      </div>
      <span class="app-label">Settings</span>
    </div>

    <!-- Dev Console -->
    <div class="app-icon" onclick="switchView('dev')">
      <div class="app-tile" style="background:linear-gradient(135deg, #1c1c1e, #2a2a2e); border:1px solid #3f3f46;">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#f59e0b" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>
      </div>
      <span class="app-label">Dev Console</span>
    </div>

    <!-- AirPlay -->
    <div class="app-icon" onclick="showToast('AirPlay — coming soon')" style="opacity:0.4">
      <div class="app-tile" style="background:linear-gradient(135deg, #1e1b4b, #272462); border:1px solid #4338ca;">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#818cf8" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
          <path d="M5 17H4a2 2 0 01-2-2V5a2 2 0 012-2h16a2 2 0 012 2v10a2 2 0 01-2 2h-1"/>
          <polygon points="12 15 17 21 7 21 12 15"/>
        </svg>
      </div>
      <span class="app-label">AirPlay</span>
    </div>

  </div>

  <!-- Bottom status -->
  <div style="position:absolute;bottom:0;left:0;right:0;height:32px;display:flex;align-items:center;justify-content:center;gap:8px;border-top:1px solid #1a1a1e">
    <span id="home-obd-dot" style="width:6px;height:6px;border-radius:50%;background:#ef4444;transition:all 0.3s"></span>
    <span id="home-obd-status" style="font-size:0.6rem;color:#52525b">Disconnected</span>
    <span style="color:#27272a;margin:0 4px">|</span>
    <span id="home-clock" style="font-size:0.6rem;color:#52525b;font-variant-numeric:tabular-nums">--:--</span>
  </div>
</div>

<!-- ===== DASHBOARD VIEW ===== -->
<div id="view-dashboard" class="view">

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

<!-- Dashboard grid -->
<div class="grid gap-1 p-1" style="flex:1; grid-template-rows: 2fr 1.2fr 1.2fr 0.8fr">
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

</div><!-- /view-dashboard -->

<!-- ===== SETTINGS VIEW ===== -->
<div id="view-settings" class="view" style="background:#0a0a0a">
  <div class="flex items-center px-4 h-[36px] border-b border-zinc-800 shrink-0">
    <span class="text-xs font-bold tracking-widest uppercase text-zinc-400">Settings</span>
    <div id="settings-status" style="font-size:0.55rem;color:#22c55e;opacity:0;transition:opacity 0.3s;margin-left:auto;padding-right:4px"></div>
  </div>
  <div class="settings-split">
    <!-- Sidebar tabs -->
    <div class="settings-sidebar">
      <div class="settings-tab active" data-stab="display" onclick="switchSettingsTab('display')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><path d="M12 1v2m0 18v2M4.22 4.22l1.42 1.42m12.72 12.72l1.42 1.42M1 12h2m18 0h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/></svg>
        Display
      </div>
      <div class="settings-tab" data-stab="bluetooth" onclick="switchSettingsTab('bluetooth')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6.5 6.5l11 11L12 23V1l5.5 5.5-11 11"/></svg>
        Bluetooth
      </div>
      <div class="settings-tab" data-stab="warnings" onclick="switchSettingsTab('warnings')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
        Warnings
      </div>
      <div class="settings-tab" data-stab="network" onclick="switchSettingsTab('network')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.55a11 11 0 0114.08 0"/><path d="M1.42 9a16 16 0 0121.16 0"/><path d="M8.53 16.11a6 6 0 016.95 0"/><circle cx="12" cy="20" r="1"/></svg>
        Network
      </div>
      <div class="settings-tab" data-stab="advanced" onclick="switchSettingsTab('advanced')">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
        Advanced
      </div>
      <div style="flex:1"></div>
      <div class="settings-tab" data-stab="about" onclick="switchSettingsTab('about')" style="border-top:1px solid #1c1c1e;margin-top:4px;padding-top:10px">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4m0-4h.01"/></svg>
        About
      </div>
    </div>

    <!-- Content panels -->
    <div style="flex:1;display:flex;flex-direction:column;overflow:hidden">
      <!-- Display panel -->
      <div class="settings-panel active" data-panel="display">
        <div class="settings-section-label">Theme Color</div>
        <div id="theme-colors" style="display:flex;gap:6px;margin-bottom:18px;flex-wrap:wrap">
          <div class="swatch" data-theme="red" style="background:#DC2626" onclick="setSetting('COLOR_THEME','red')"></div>
          <div class="swatch" data-theme="blue" style="background:#3b82f6" onclick="setSetting('COLOR_THEME','blue')"></div>
          <div class="swatch" data-theme="green" style="background:#22c55e" onclick="setSetting('COLOR_THEME','green')"></div>
          <div class="swatch" data-theme="purple" style="background:#a855f7" onclick="setSetting('COLOR_THEME','purple')"></div>
          <div class="swatch" data-theme="orange" style="background:#f97316" onclick="setSetting('COLOR_THEME','orange')"></div>
          <div class="swatch" data-theme="cyan" style="background:#06b6d4" onclick="setSetting('COLOR_THEME','cyan')"></div>
          <div class="swatch" data-theme="pink" style="background:#ec4899" onclick="setSetting('COLOR_THEME','pink')"></div>
        </div>

        <div class="settings-row">
          <span class="settings-row-label">Speed</span>
          <div class="settings-row-value">
            <button class="setting-btn" data-key="UNITS_SPEED" data-val="mph" onclick="setSetting('UNITS_SPEED','mph')">MPH</button>
            <button class="setting-btn" data-key="UNITS_SPEED" data-val="kmh" onclick="setSetting('UNITS_SPEED','kmh')">km/h</button>
          </div>
        </div>
        <div class="settings-row">
          <span class="settings-row-label">Temperature</span>
          <div class="settings-row-value">
            <button class="setting-btn" data-key="UNITS_TEMP" data-val="C" onclick="setSetting('UNITS_TEMP','C')">&deg;C</button>
            <button class="setting-btn" data-key="UNITS_TEMP" data-val="F" onclick="setSetting('UNITS_TEMP','F')">&deg;F</button>
          </div>
        </div>
        <div class="settings-row">
          <span class="settings-row-label">Clock</span>
          <div class="settings-row-value">
            <button class="setting-btn" data-key="TIME_24HR" data-val="1" onclick="setSetting('TIME_24HR','1')">24hr</button>
            <button class="setting-btn" data-key="TIME_24HR" data-val="0" onclick="setSetting('TIME_24HR','0')">12hr</button>
          </div>
        </div>
        <div class="settings-row">
          <span class="settings-row-label">Sparklines</span>
          <div class="settings-row-value">
            <button class="setting-btn" data-key="SHOW_SPARKLINES" data-val="1" onclick="setSetting('SHOW_SPARKLINES','1')">On</button>
            <button class="setting-btn" data-key="SHOW_SPARKLINES" data-val="0" onclick="setSetting('SHOW_SPARKLINES','0')">Off</button>
          </div>
        </div>
      </div>

      <!-- Bluetooth panel -->
      <div class="settings-panel" data-panel="bluetooth">
        <div class="settings-section-label">OBD Adapter</div>
        <div class="settings-row">
          <span class="settings-row-label">MAC Address</span>
          <div class="settings-row-value">
            <span id="bt-obd-mac" style="font-size:0.6rem;color:#71717a;font-family:monospace">--</span>
          </div>
        </div>
        <div style="margin-bottom:12px">
          <button class="setting-btn" onclick="btScan()" id="bt-scan-btn">Scan for Devices</button>
        </div>
        <div id="bt-scan-results" style="font-size:0.6rem;color:#a1a1aa;margin-bottom:16px"></div>

        <div class="settings-row">
          <span class="settings-row-label">RFCOMM Channel</span>
          <div class="settings-row-value">
            <button class="setting-btn small" data-key="OBD_BT_CHANNEL" data-val="1" onclick="setSetting('OBD_BT_CHANNEL','1')">1</button>
            <button class="setting-btn small" data-key="OBD_BT_CHANNEL" data-val="2" onclick="setSetting('OBD_BT_CHANNEL','2')">2</button>
            <button class="setting-btn small" data-key="OBD_BT_CHANNEL" data-val="3" onclick="setSetting('OBD_BT_CHANNEL','3')">3</button>
          </div>
        </div>

        <div class="settings-section-label" style="margin-top:14px">Phone</div>
        <div class="settings-row">
          <span class="settings-row-label">Phone Bluetooth</span>
          <div class="settings-row-value">
            <span id="bt-phone-mac" style="font-size:0.6rem;color:#71717a;font-family:monospace">--</span>
          </div>
        </div>
        <div class="settings-row">
          <span class="settings-row-label">Auto-Connect</span>
          <div class="settings-row-value">
            <button class="setting-btn" data-key="PHONE_BT_AUTO" data-val="1" onclick="setSetting('PHONE_BT_AUTO','1')">On</button>
            <button class="setting-btn" data-key="PHONE_BT_AUTO" data-val="0" onclick="setSetting('PHONE_BT_AUTO','0')">Off</button>
          </div>
        </div>
      </div>

      <!-- Warnings panel -->
      <div class="settings-panel" data-panel="warnings">
        <div class="settings-row">
          <span class="settings-row-label">RPM Redline</span>
          <div class="settings-row-value">
            <button class="setting-btn small" data-key="RPM_REDLINE" data-val="5500" onclick="setSetting('RPM_REDLINE','5500')">5500</button>
            <button class="setting-btn small" data-key="RPM_REDLINE" data-val="6000" onclick="setSetting('RPM_REDLINE','6000')">6000</button>
            <button class="setting-btn small" data-key="RPM_REDLINE" data-val="6500" onclick="setSetting('RPM_REDLINE','6500')">6500</button>
            <button class="setting-btn small" data-key="RPM_REDLINE" data-val="7000" onclick="setSetting('RPM_REDLINE','7000')">7000</button>
            <button class="setting-btn small" data-key="RPM_REDLINE" data-val="8000" onclick="setSetting('RPM_REDLINE','8000')">8000</button>
          </div>
        </div>
        <div class="settings-row">
          <span class="settings-row-label">Overheat &deg;C</span>
          <div class="settings-row-value">
            <button class="setting-btn small" data-key="COOLANT_OVERHEAT_C" data-val="100" onclick="setSetting('COOLANT_OVERHEAT_C','100')">100</button>
            <button class="setting-btn small" data-key="COOLANT_OVERHEAT_C" data-val="105" onclick="setSetting('COOLANT_OVERHEAT_C','105')">105</button>
            <button class="setting-btn small" data-key="COOLANT_OVERHEAT_C" data-val="110" onclick="setSetting('COOLANT_OVERHEAT_C','110')">110</button>
          </div>
        </div>
        <div class="settings-row">
          <span class="settings-row-label">Low Battery V</span>
          <div class="settings-row-value">
            <button class="setting-btn small" data-key="BATTERY_LOW_V" data-val="11.5" onclick="setSetting('BATTERY_LOW_V','11.5')">11.5</button>
            <button class="setting-btn small" data-key="BATTERY_LOW_V" data-val="12.0" onclick="setSetting('BATTERY_LOW_V','12.0')">12.0</button>
            <button class="setting-btn small" data-key="BATTERY_LOW_V" data-val="12.5" onclick="setSetting('BATTERY_LOW_V','12.5')">12.5</button>
          </div>
        </div>
        <div class="settings-row">
          <span class="settings-row-label">Critical Battery V</span>
          <div class="settings-row-value">
            <button class="setting-btn small" data-key="BATTERY_CRITICAL_V" data-val="10.5" onclick="setSetting('BATTERY_CRITICAL_V','10.5')">10.5</button>
            <button class="setting-btn small" data-key="BATTERY_CRITICAL_V" data-val="11.0" onclick="setSetting('BATTERY_CRITICAL_V','11.0')">11.0</button>
            <button class="setting-btn small" data-key="BATTERY_CRITICAL_V" data-val="11.5" onclick="setSetting('BATTERY_CRITICAL_V','11.5')">11.5</button>
          </div>
        </div>
      </div>

      <!-- Network panel -->
      <div class="settings-panel" data-panel="network">
        <div class="settings-section-label">WiFi Hotspot</div>
        <div class="settings-row">
          <span class="settings-row-label">SSID</span>
          <div class="settings-row-value">
            <span id="net-ssid" style="font-size:0.6rem;color:#71717a;font-family:monospace">{app_config.HOTSPOT_SSID}</span>
          </div>
        </div>
        <div class="settings-row">
          <span class="settings-row-label">Password</span>
          <div class="settings-row-value">
            <span style="font-size:0.6rem;color:#52525b">Change via phone</span>
          </div>
        </div>
      </div>

      <!-- Advanced panel -->
      <div class="settings-panel" data-panel="advanced">
        <div class="settings-row">
          <span class="settings-row-label">Fast Poll (sec)</span>
          <div class="settings-row-value">
            <button class="setting-btn small" data-key="FAST_POLL_INTERVAL" data-val="0.5" onclick="setSetting('FAST_POLL_INTERVAL','0.5')">0.5</button>
            <button class="setting-btn small" data-key="FAST_POLL_INTERVAL" data-val="1.0" onclick="setSetting('FAST_POLL_INTERVAL','1.0')">1.0</button>
            <button class="setting-btn small" data-key="FAST_POLL_INTERVAL" data-val="2.0" onclick="setSetting('FAST_POLL_INTERVAL','2.0')">2.0</button>
          </div>
        </div>
        <div class="settings-row">
          <span class="settings-row-label">Slow Poll (sec)</span>
          <div class="settings-row-value">
            <button class="setting-btn small" data-key="SLOW_POLL_INTERVAL" data-val="5" onclick="setSetting('SLOW_POLL_INTERVAL','5')">5</button>
            <button class="setting-btn small" data-key="SLOW_POLL_INTERVAL" data-val="10" onclick="setSetting('SLOW_POLL_INTERVAL','10')">10</button>
            <button class="setting-btn small" data-key="SLOW_POLL_INTERVAL" data-val="30" onclick="setSetting('SLOW_POLL_INTERVAL','30')">30</button>
          </div>
        </div>
        <div class="settings-row">
          <span class="settings-row-label">Scan PIDs on Boot</span>
          <div class="settings-row-value">
            <button class="setting-btn" data-key="SCAN_PIDS_ON_BOOT" data-val="1" onclick="setSetting('SCAN_PIDS_ON_BOOT','1')">On</button>
            <button class="setting-btn" data-key="SCAN_PIDS_ON_BOOT" data-val="0" onclick="setSetting('SCAN_PIDS_ON_BOOT','0')">Off</button>
          </div>
        </div>
      </div>

      <!-- About panel -->
      <div class="settings-panel" data-panel="about">
        <div style="text-align:center;padding-top:10px">
          <div style="width:52px;height:52px;border-radius:14px;background:linear-gradient(135deg, {accent}18, {accent}35);border:1px solid {accent}44;display:flex;align-items:center;justify-content:center;margin:0 auto 10px">
            <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="{accent}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>
          </div>
          <div style="font-size:1rem;font-weight:800;letter-spacing:0.5px">SignalKit</div>
          <div style="font-size:0.6rem;color:#52525b;margin-top:2px" id="about-version">v{git_hash}</div>
        </div>
        <div style="margin-top:16px;display:grid;gap:6px">
          <div class="settings-row">
            <span class="settings-row-label">IP Address</span>
            <span style="font-size:0.6rem;color:#a1a1aa;font-family:monospace" id="about-ip">--</span>
          </div>
          <div class="settings-row">
            <span class="settings-row-label">Web Port</span>
            <span style="font-size:0.6rem;color:#a1a1aa;font-family:monospace" id="about-port">--</span>
          </div>
          <div class="settings-row">
            <span class="settings-row-label">OBD Adapter</span>
            <span style="font-size:0.6rem;color:#a1a1aa;font-family:monospace" id="about-obd">--</span>
          </div>
          <div class="settings-row">
            <span class="settings-row-label">Theme</span>
            <span style="font-size:0.6rem;color:#a1a1aa" id="about-theme">--</span>
          </div>
        </div>
        <div style="margin-top:16px;font-size:0.5rem;color:#3f3f46;line-height:1.6;text-align:center">
          Open-source OBD2 dashboard for Raspberry Pi.<br>
          Not affiliated with any vehicle manufacturer.
        </div>
      </div>
    </div>
  </div>
</div>

<!-- ===== DEV CONSOLE VIEW ===== -->
<div id="view-dev" class="view" style="background:#0a0a0a">
  <div class="flex items-center justify-between px-4 h-[36px] border-b border-zinc-800 shrink-0">
    <span class="text-xs font-bold tracking-widest uppercase text-zinc-400">Dev Console</span>
    <button onclick="clearDevTerminal()" class="text-[0.6rem] text-zinc-500 hover:text-zinc-300" style="cursor:pointer;background:none;border:none;color:#71717a">Clear</button>
  </div>

  <!-- Quick commands -->
  <div style="padding:8px 12px;display:flex;flex-wrap:wrap;gap:5px;border-bottom:1px solid #27272a">
    <button class="dev-qbtn" onclick="devSend('ATZ')">ATZ</button>
    <button class="dev-qbtn" onclick="devSend('ATI')">ATI</button>
    <button class="dev-qbtn" onclick="devSend('ATRV')">ATRV</button>
    <button class="dev-qbtn" onclick="devSend('ATDP')">ATDP</button>
    <button class="dev-qbtn" onclick="devSend('0100')">0100</button>
    <button class="dev-qbtn" onclick="devSend('010C')">RPM</button>
    <button class="dev-qbtn" onclick="devSend('010D')">Speed</button>
    <button class="dev-qbtn" onclick="devSend('0105')">Coolant</button>
    <button class="dev-qbtn" onclick="devSend('03')">DTCs</button>
  </div>

  <!-- Terminal output -->
  <div id="dev-terminal" style="flex:1;overflow-y:auto;padding:8px 12px;font-family:'SF Mono','Menlo','Monaco','Courier New',monospace;font-size:0.65rem;line-height:1.6;scrollbar-width:none"></div>

  <!-- Input bar -->
  <div style="display:flex;border-top:1px solid #27272a;align-items:center;shrink:0">
    <span style="color:var(--accent);font-family:monospace;font-size:0.75rem;padding:0 8px 0 12px;user-select:none">&gt;</span>
    <div id="dev-input" style="flex:1;font-family:'SF Mono','Menlo',monospace;font-size:0.7rem;color:#e4e4e7;padding:10px 4px;min-height:18px;letter-spacing:0.5px;cursor:text" onclick="toggleDevKb(true)"></div>
    <button onclick="devSendInput()" style="padding:8px 14px;background:none;border:none;color:var(--accent);font-size:0.7rem;font-weight:700;cursor:pointer">Send</button>
  </div>

  <!-- On-screen keyboard -->
  <div id="dev-kb" style="display:none;border-top:1px solid #27272a;padding:6px 8px;background:#111113;shrink:0">
    <div style="display:flex;gap:4px;margin-bottom:4px;justify-content:center">
      <button class="kb-key" onclick="kbType('0')">0</button>
      <button class="kb-key" onclick="kbType('1')">1</button>
      <button class="kb-key" onclick="kbType('2')">2</button>
      <button class="kb-key" onclick="kbType('3')">3</button>
      <button class="kb-key" onclick="kbType('4')">4</button>
      <button class="kb-key" onclick="kbType('5')">5</button>
      <button class="kb-key" onclick="kbType('6')">6</button>
      <button class="kb-key" onclick="kbType('7')">7</button>
      <button class="kb-key" onclick="kbType('8')">8</button>
      <button class="kb-key" onclick="kbType('9')">9</button>
    </div>
    <div style="display:flex;gap:4px;margin-bottom:4px;justify-content:center">
      <button class="kb-key" onclick="kbType('A')">A</button>
      <button class="kb-key" onclick="kbType('B')">B</button>
      <button class="kb-key" onclick="kbType('C')">C</button>
      <button class="kb-key" onclick="kbType('D')">D</button>
      <button class="kb-key" onclick="kbType('E')">E</button>
      <button class="kb-key" onclick="kbType('F')">F</button>
      <button class="kb-key wide" onclick="kbType(' ')" style="min-width:60px">Space</button>
      <button class="kb-key" onclick="kbBackspace()" style="font-size:0.7rem">&#9003;</button>
    </div>
    <div style="display:flex;gap:4px;justify-content:center">
      <button class="kb-key wide" onclick="kbType('AT')">AT</button>
      <button class="kb-key" onclick="kbType('G')">G</button>
      <button class="kb-key" onclick="kbType('H')">H</button>
      <button class="kb-key" onclick="kbType('I')">I</button>
      <button class="kb-key" onclick="kbType('L')">L</button>
      <button class="kb-key" onclick="kbType('M')">M</button>
      <button class="kb-key" onclick="kbType('P')">P</button>
      <button class="kb-key" onclick="kbType('R')">R</button>
      <button class="kb-key" onclick="kbType('S')">S</button>
      <button class="kb-key" onclick="kbType('T')">T</button>
      <button class="kb-key" onclick="kbType('V')">V</button>
      <button class="kb-key" onclick="kbType('Z')">Z</button>
      <button class="kb-key" onclick="toggleDevKb(false)" style="font-size:0.6rem;color:#71717a">&#9660;</button>
    </div>
  </div>
</div>


</div><!-- /main-content -->

<script>
  // ===== View switching =====
  let currentView = 'home';
  let dashboardInitialized = false;

  function switchView(name) {{
    document.querySelectorAll('.view').forEach(function(v) {{ v.classList.remove('active', 'view-enter'); }});
    const target = document.getElementById('view-' + name);
    if (target) {{
      target.classList.add('active', 'view-enter');
      currentView = name;
    }}
    // Update dock active state
    document.querySelectorAll('.dock-btn[data-view]').forEach(function(b) {{
      b.classList.toggle('active', b.dataset.view === name);
    }});
    if (name === 'dashboard' && !dashboardInitialized) {{
      dashboardInitialized = true;
      initDashboard();
    }}
    if (name === 'settings') {{ initSettings(); }}
  }}

  function showToast(msg) {{
    const t = document.getElementById('toast-inner');
    t.textContent = msg;
    t.style.opacity = '1';
    setTimeout(function() {{ t.style.opacity = '0'; }}, 2000);
  }}

  // Clock (shared by dock + home)
  function updateAllClocks() {{
    const now = new Date();
    let h = now.getHours(), m = now.getMinutes();
    const ampm = h >= 12 ? 'PM' : 'AM';
    h = h % 12 || 12;
    const str = h + ':' + String(m).padStart(2, '0') + ' ' + ampm;
    const dc = document.getElementById('dock-clock');
    const hc = document.getElementById('home-clock');
    if (dc) dc.textContent = str;
    if (hc) hc.textContent = str;
  }}
  setInterval(updateAllClocks, 10000);
  updateAllClocks();

  // OBD status (dock + home)
  async function pollGlobalStatus() {{
    try {{
      const raw = await window.pywebview.api.get_data();
      const d = JSON.parse(raw);
      const connected = d.connected;
      // Dock dot
      const dd = document.getElementById('dock-obd-dot');
      dd.style.background = connected ? '{accent}' : '#ef4444';
      dd.style.boxShadow = connected ? '0 0 6px {accent}' : 'none';
      // Home view status
      const hd = document.getElementById('home-obd-dot');
      const hl = document.getElementById('home-obd-status');
      if (hd) {{
        hd.style.background = connected ? '#22c55e' : '#ef4444';
        hd.style.boxShadow = connected ? '0 0 6px #22c55e' : 'none';
      }}
      if (hl) {{
        hl.textContent = connected ? 'Connected' : (d.status || 'Disconnected');
        hl.style.color = connected ? '#22c55e' : '#52525b';
      }}
    }} catch(e) {{}}
  }}
  setInterval(pollGlobalStatus, 3000);

  // ===== Dashboard =====
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

  // --- Dashboard Initialization (called when switching to dashboard view) ---
  async function initDashboard() {{
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

    pollTimer = setInterval(poll, 500);
  }}

  // ===== Settings View =====
  function switchSettingsTab(name) {{
    document.querySelectorAll('.settings-tab').forEach(function(t) {{
      t.classList.toggle('active', t.dataset.stab === name);
    }});
    document.querySelectorAll('.settings-panel').forEach(function(p) {{
      p.classList.toggle('active', p.dataset.panel === name);
    }});
    if (name === 'about') {{ loadAboutInfo(); }}
  }}

  async function initSettings() {{
    try {{
      const rawCfg = await window.pywebview.api.get_config();
      const cfg = JSON.parse(rawCfg);
      // Highlight active swatch
      document.querySelectorAll('.swatch').forEach(function(s) {{
        s.classList.toggle('active', s.dataset.theme === cfg.color_theme);
      }});
      // Highlight active setting buttons
      const map = {{
        'UNITS_SPEED': cfg.units_speed,
        'UNITS_TEMP': cfg.units_temp,
        'TIME_24HR': cfg.time_24hr ? '1' : '0',
        'SHOW_SPARKLINES': cfg.show_sparklines ? '1' : '0',
        'RPM_REDLINE': String(cfg.redline),
        'COOLANT_OVERHEAT_C': String(cfg.overheat_c),
        'BATTERY_LOW_V': String(cfg.low_v),
        'BATTERY_CRITICAL_V': String(cfg.critical_v),
        'OBD_BT_CHANNEL': String(cfg.obd_bt_channel),
        'PHONE_BT_AUTO': cfg.phone_bt_auto ? '1' : '0',
        'FAST_POLL_INTERVAL': String(cfg.fast_poll),
        'SLOW_POLL_INTERVAL': String(cfg.slow_poll),
        'SCAN_PIDS_ON_BOOT': cfg.scan_pids ? '1' : '0',
      }};
      document.querySelectorAll('.setting-btn').forEach(function(b) {{
        const k = b.dataset.key, v = b.dataset.val;
        b.classList.toggle('active', map[k] === v);
      }});
      // Populate BT info
      const obdMac = document.getElementById('bt-obd-mac');
      if (obdMac) obdMac.textContent = cfg.obd_mac || 'Not set';
      const phoneMac = document.getElementById('bt-phone-mac');
      if (phoneMac) phoneMac.textContent = cfg.phone_bt_mac || 'Not set';
    }} catch(e) {{}}
  }}

  async function btScan() {{
    const btn = document.getElementById('bt-scan-btn');
    const results = document.getElementById('bt-scan-results');
    btn.textContent = 'Scanning...';
    btn.disabled = true;
    results.innerHTML = '<span style="color:#52525b">Searching for Bluetooth devices...</span>';
    try {{
      const raw = await window.pywebview.api.bt_scan();
      const data = JSON.parse(raw);
      if (!data.devices || !data.devices.length) {{
        results.innerHTML = '<span style="color:#71717a">No devices found</span>';
      }} else {{
        results.innerHTML = data.devices.map(function(d) {{
          return '<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid #1c1c1e">' +
            '<span style="font-size:0.6rem;color:#d4d4d8">' + d.name + ' <span style="color:#52525b;font-family:monospace;font-size:0.55rem">' + d.address + '</span></span>' +
            '<button class="setting-btn small" onclick="selectObdDevice(\\'' + d.address + '\\')" style="font-size:0.55rem">Select</button>' +
            '</div>';
        }}).join('');
      }}
    }} catch(e) {{
      results.innerHTML = '<span style="color:#ef4444">Scan failed: ' + e.message + '</span>';
    }}
    btn.textContent = 'Scan for Devices';
    btn.disabled = false;
  }}

  async function selectObdDevice(mac) {{
    await setSetting('OBD_MAC', mac);
    const obdMac = document.getElementById('bt-obd-mac');
    if (obdMac) obdMac.textContent = mac;
  }}

  async function setSetting(key, value) {{
    try {{
      const raw = await window.pywebview.api.save_setting(key, value);
      const result = JSON.parse(raw);
      const el = document.getElementById('settings-status');
      el.textContent = result.ok ? 'Saved' : result.message;
      el.style.color = result.ok ? '#22c55e' : '#ef4444';
      el.style.opacity = '1';
      setTimeout(function() {{ el.style.opacity = '0'; }}, 1500);
      // Update button active states
      if (result.ok) {{
        // For swatches
        if (key === 'COLOR_THEME') {{
          document.querySelectorAll('.swatch').forEach(function(s) {{
            s.classList.toggle('active', s.dataset.theme === value);
          }});
        }}
        // For toggle buttons
        document.querySelectorAll('.setting-btn[data-key="' + key + '"]').forEach(function(b) {{
          b.classList.toggle('active', b.dataset.val === value);
        }});
      }}
    }} catch(e) {{
      const el = document.getElementById('settings-status');
      el.textContent = 'Error: ' + e.message;
      el.style.color = '#ef4444';
      el.style.opacity = '1';
    }}
  }}

  // ===== Dev Console View =====
  let devInputText = '';

  function devUpdateInput() {{
    const el = document.getElementById('dev-input');
    el.textContent = devInputText + '\u2588';  // block cursor
  }}

  function kbType(ch) {{
    devInputText += ch;
    devUpdateInput();
  }}

  function kbBackspace() {{
    devInputText = devInputText.slice(0, -1);
    devUpdateInput();
  }}

  function toggleDevKb(show) {{
    document.getElementById('dev-kb').style.display = show ? '' : 'none';
    if (show) devUpdateInput();
  }}

  function devSendInput() {{
    const cmd = devInputText.trim();
    if (!cmd) return;
    devInputText = '';
    devUpdateInput();
    devSend(cmd);
  }}

  function devAppend(text, cls) {{
    const term = document.getElementById('dev-terminal');
    const line = document.createElement('div');
    line.className = 'dev-line ' + (cls || '');
    line.textContent = text;
    term.appendChild(line);
    term.scrollTop = term.scrollHeight;
  }}

  function clearDevTerminal() {{
    document.getElementById('dev-terminal').innerHTML = '';
    devAppend('Terminal cleared.', 'dev-info');
  }}

  async function devSend(cmd) {{
    devAppend('> ' + cmd, 'dev-cmd');
    try {{
      const raw = await window.pywebview.api.send_obd_command(cmd);
      const d = JSON.parse(raw);
      if (d.ok) {{
        if (d.response) {{
          d.response.split('\\n').forEach(function(line) {{
            if (line.trim()) devAppend(line.trim(), 'dev-resp');
          }});
        }} else {{
          devAppend('(empty response)', 'dev-info');
        }}
      }} else {{
        devAppend('ERROR: ' + (d.error || 'Unknown error'), 'dev-err');
      }}
    }} catch(e) {{
      devAppend('ERROR: ' + e.message, 'dev-err');
    }}
  }}

  // ===== About View =====
  async function loadAboutInfo() {{
    try {{
      const raw = await window.pywebview.api.get_system_info();
      const info = JSON.parse(raw);
      document.getElementById('about-version').textContent = 'v' + info.version + ' (' + info.git_hash + ')';
      document.getElementById('about-ip').textContent = info.ip;
      document.getElementById('about-port').textContent = String(info.port);
      document.getElementById('about-obd').textContent = info.obd_mac || 'Not set';
      document.getElementById('about-theme').textContent = info.theme.charAt(0).toUpperCase() + info.theme.slice(1);
    }} catch(e) {{}}
  }}

  // --- Startup ---
  window.addEventListener('pywebviewready', function() {{
    updateAllClocks();
    pollGlobalStatus();
  }});
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
    global _was_in_setup
    _was_in_setup = _needs_setup()
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


_was_in_setup = True  # Track setup state to detect transition

def _on_setting_changed_handler():
    """Handle config changes — reload dashboard or switch from setup to dashboard."""
    global _was_in_setup
    if _window:
        try:
            if _was_in_setup and not _needs_setup():
                # Setup just completed — load the full dashboard
                _was_in_setup = False
                _window.load_html(_build_html())
                logger.info("Setup complete — switched HDMI to dashboard")
            else:
                _was_in_setup = _needs_setup()
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
