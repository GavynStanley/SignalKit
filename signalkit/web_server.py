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
#   GET  /api/debug     - Aggregated debug snapshot (OBD, system, config, logs)
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
import tempfile

from flask import Flask, Response, jsonify, request

import bt_pan
import config
import obd_reader

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.logger.setLevel(logging.WARNING)

_GROUPS = {
    "OBD_MAC": "OBD2 Connection",
    "OBD_BT_CHANNEL": "OBD2 Connection",
    "FAST_POLL_INTERVAL": "OBD2 Connection",
    "SLOW_POLL_INTERVAL": "OBD2 Connection",
    "SCAN_PIDS_ON_BOOT": "OBD2 Connection",
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
    "SCREEN_BRIGHTNESS": "Display",
    "LAYOUT_METRICS": "Dashboard Layout",
    "LAYOUT_SLOW": "Dashboard Layout",
    "PHONE_BT_MAC": "Phone",
    "PHONE_BT_AUTO": "Phone",
}


_GROUP_ORDER = ["OBD2 Connection", "Warning Thresholds", "Display", "Dashboard Layout", "WiFi Hotspot", "Phone"]

def _schedule_restart(delay=2.0, reason="API request"):
    """Schedule a SignalKit service restart after a short delay.

    Args:
        delay:  Seconds to wait before restarting (gives the HTTP response time to flush).
        reason: Human-readable reason logged before the restart.
    """
    def _do():
        time.sleep(delay)
        logger.info("Restarting SignalKit: %s", reason)
        os.system("sudo systemctl restart signalkit 2>/dev/null || sudo kill -SIGTERM 1")
    threading.Thread(target=_do, daemon=True).start()


def _build_settings_context():
    """Build the settings dict and group list for the settings page template."""
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
    """Yield Server-Sent Events with live OBD2 data at 1 Hz."""
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
    info = {"cpu_temp": "--", "memory": "--", "uptime": "--",
            "voltage": "--", "power_status": "--", "clock_speed": "--"}
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

    # Core voltage (power draw indicator)
    try:
        r = subprocess.run(["vcgencmd", "measure_volts", "core"],
                           capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            # Output: "volt=1.2000V"
            info["voltage"] = r.stdout.strip().split("=")[1]
    except Exception:
        pass

    # Throttle / power status — detects undervoltage, throttling, etc.
    try:
        r = subprocess.run(["vcgencmd", "get_throttled"],
                           capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            # Output: "throttled=0x0" (0x0 = OK)
            hex_val = r.stdout.strip().split("=")[1]
            flags = int(hex_val, 16)
            if flags == 0:
                info["power_status"] = "OK"
            else:
                issues = []
                if flags & 0x1:
                    issues.append("Under-voltage detected")
                if flags & 0x2:
                    issues.append("ARM frequency capped")
                if flags & 0x4:
                    issues.append("Currently throttled")
                if flags & 0x8:
                    issues.append("Soft temp limit active")
                if flags & 0x10000:
                    issues.append("Under-voltage has occurred")
                if flags & 0x20000:
                    issues.append("ARM freq capping has occurred")
                if flags & 0x40000:
                    issues.append("Throttling has occurred")
                if flags & 0x80000:
                    issues.append("Soft temp limit has occurred")
                info["power_status"] = "; ".join(issues)
    except Exception:
        pass

    # CPU clock speed
    try:
        r = subprocess.run(["vcgencmd", "measure_clock", "arm"],
                           capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            # Output: "frequency(48)=1500000000"
            freq = int(r.stdout.strip().split("=")[1])
            info["clock_speed"] = f"{freq / 1_000_000:.0f} MHz"
    except Exception:
        pass

    return info


def _git_info() -> dict:
    """Return git branch, commit hash, and dirty status for the app repo."""
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
    """Execute a git pull OTA update, handling overlayfs if active."""
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
    """Android captive portal check — return 204 No Content."""
    return "", 204


@app.route("/hotspot-detect.html")
@app.route("/library/test/success.html")
def captive_apple():
    """Apple captive portal check."""
    return "<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>"


@app.route("/connecttest.txt")
def captive_windows():
    """Windows captive portal check."""
    return "Microsoft Connect Test"


@app.route("/redirect")
@app.route("/ncsi.txt")
def captive_misc():
    """Misc captive portal checks."""
    return "", 204


@app.route("/")
def index():
    """API root — return basic info."""
    return jsonify({
        "name": "SignalKit",
        "version": config.APP_VERSION,
        "status": "running",
    })


@app.route("/api/diagnostics")
def api_diagnostics():
    """Return diagnostics data including system info."""
    diag = obd_reader.get_diagnostics()
    diag["system"] = _get_system_info()
    return jsonify(diag)


@app.route("/api/data")
def api_data():
    """Return current OBD2 data as JSON."""
    data = obd_reader.get_data()
    data["restart_pending"] = config.restart_pending
    return jsonify(data)


@app.route("/api/pids")
def api_pids():
    """Return the full PID snapshot taken on connect."""
    return jsonify(obd_reader.get_pid_snapshot())


@app.route("/api/pids/scan", methods=["POST"])
def api_pids_scan():
    """Re-scan all supported PIDs and return the updated snapshot."""
    with obd_reader._conn_lock:
        conn = obd_reader._active_connection
    if conn is None or not conn.is_connected():
        return jsonify({"ok": False, "error": "Not connected to OBD adapter"}), 400
    obd_reader._scan_all_pids(conn)
    return jsonify({"ok": True, **obd_reader.get_pid_snapshot()})


@app.route("/api/bt-logs")
def api_bt_logs():
    """Return recent Bluetooth-related log lines from journald and SignalKit."""
    lines = []
    try:
        # Get SignalKit logs mentioning bluetooth/rfcomm/obd/connect
        r = subprocess.run(
            ["journalctl", "-u", "signalkit", "-u", "signalkit-rfcomm",
             "-u", "bluetooth", "--no-pager", "-n", "200"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            bt_keywords = ["bluetooth", "rfcomm", "obd", "bt_pan", "bluez",
                           "connect", "disconnect", "pair", "adapter", "hci",
                           "rfkill", "serial", "bound", "channel", "agent",
                           "power on", "trust", "scan", "failed", "error",
                           "bluetoothctl", "bluetoothd"]
            for line in r.stdout.splitlines():
                lower = line.lower()
                if any(kw in lower for kw in bt_keywords):
                    lines.append(line)
            # Keep last 100 relevant lines
            lines = lines[-100:]
    except Exception as e:
        lines = [f"Error reading logs: {e}"]
    return jsonify({"ok": True, "lines": lines})


@app.route("/api/stream")
def api_stream():
    """SSE endpoint for live dashboard updates."""
    return Response(
        _sse_stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


@app.route("/api/dtcs")
def api_dtcs():
    """Return active DTC codes and MIL status."""
    data = obd_reader.get_data()
    return jsonify({"count": data.get("dtc_count", 0), "mil_on": data.get("mil_on", False), "dtcs": data.get("dtcs", [])})


@app.route("/api/status")
def api_status():
    """Return OBD connection status."""
    data = obd_reader.get_data()
    return jsonify({"connected": data.get("connected", False), "status": data.get("status", "Unknown"), "last_update": data.get("last_update"), "restart_pending": config.restart_pending})


@app.route("/api/settings", methods=["GET"])
def api_settings_get():
    """Return all editable settings with current values."""
    settings, groups = _build_settings_context()
    return jsonify({"settings": settings, "groups": groups})


@app.route("/api/themes")
def api_themes():
    """Return available color themes."""
    return jsonify(config.THEMES)


@app.route("/api/settings", methods=["POST"])
def api_settings_post():
    """Save one or more settings from a JSON body."""
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


# Keywords that indicate a device is likely an OBD2 adapter
_OBD_KEYWORDS = [
    "obd", "obdii", "obd2", "elm327", "elm 327", "veepeak", "vepeak",
    "v-link", "vlink", "vgate", "konnwei", "kw", "carista", "fixd",
    "bluedriver", "bafx", "scan", "scanner", "autoenginuity", "torque",
    "icar", "xtool", "thinkcar", "launch", "autel",
]


def _is_likely_obd(name):
    """Check if a device name looks like an OBD2 adapter."""
    lower = name.lower()
    return any(kw in lower for kw in _OBD_KEYWORDS)


def _bt_scan_linux():
    """Scan using both hcitool (classic BT) and bluetoothctl (BLE).
    OBD adapters use classic Bluetooth SPP and only show up via hcitool."""
    # Ensure Bluetooth is unblocked and powered on
    subprocess.run(["rfkill", "unblock", "bluetooth"], capture_output=True, timeout=3)
    subprocess.run(["bluetoothctl", "power", "on"], capture_output=True, text=True, timeout=5)

    devices = []
    seen = set()

    # --- Classic Bluetooth scan via hcitool scan (finds OBD adapters) ---
    # Uses 'scan' instead of 'inq' — some OBD adapters don't respond to
    # raw inquiry but DO respond to a full scan with name resolution.
    try:
        logger.info("Starting classic BT scan (hcitool scan)...")
        proc = subprocess.run(
            ["hcitool", "scan", "--flush"],
            capture_output=True, text=True, timeout=30,
        )
        logger.info(f"hcitool scan output: {proc.stdout.strip()}")
        for line in proc.stdout.splitlines():
            line = line.strip()
            # Format: "00:1D:A5:09:BC:AA  DeviceName"
            if not line or line.startswith("Scanning"):
                continue
            parts = line.split(None, 1)
            mac = parts[0] if parts else None
            if mac and len(mac) == 17 and mac.count(":") == 5 and mac not in seen:
                seen.add(mac)
                name = parts[1].strip() if len(parts) > 1 else mac
                is_obd = _is_likely_obd(name)
                devices.append({"mac": mac, "name": name, "obd": is_obd})
    except subprocess.TimeoutExpired:
        logger.warning("hcitool scan timed out")
    except FileNotFoundError:
        logger.warning("hcitool not found — skipping classic BT scan")

    # --- BLE scan via bluetoothctl (finds newer devices) ---
    try:
        scan_proc = subprocess.Popen(
            ["bluetoothctl", "--timeout", "6", "scan", "on"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(6)
        try:
            scan_proc.terminate()
            scan_proc.wait(timeout=2)
        except Exception:
            scan_proc.kill()
        proc = subprocess.run(
            ["bluetoothctl", "devices"], capture_output=True, text=True, timeout=5,
        )
        for line in proc.stdout.splitlines():
            line = line.strip()
            if line.startswith("Device "):
                parts = line.split(" ", 2)
                mac = parts[1] if len(parts) >= 2 else None
                name = parts[2] if len(parts) >= 3 else mac
                if mac and mac not in seen:
                    seen.add(mac)
                    is_obd = _is_likely_obd(name) if name else False
                    devices.append({"mac": mac, "name": name, "obd": is_obd})
    except Exception as e:
        logger.warning(f"BLE scan failed: {e}")

    # Sort: OBD adapters first, then alphabetically by name
    devices.sort(key=lambda d: (not d.get("obd", False), (d.get("name") or "").lower()))
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


# ---------------------------------------------------------------------------
# OBD Adapter Pairing
# ---------------------------------------------------------------------------

@app.route("/api/bt-pair", methods=["POST"])
def api_bt_pair():
    """Pair with an OBD2 Bluetooth adapter by MAC address.

    Called when the user selects an adapter from the scan results.
    Many OBD2 adapters don't support standard bluetoothctl pairing —
    they just accept rfcomm connections directly. So we:
      1. Try bluetoothctl pair (works for some adapters)
      2. Always trust the device regardless
      3. Test rfcomm bind to verify the adapter is reachable
    Returns success if we can reach the device at all.
    """
    body = request.get_json(silent=True)
    mac = (body or {}).get("mac", "").strip()
    if not mac or mac.count(":") != 5:
        return jsonify({"ok": False, "error": "Invalid MAC address"})

    if platform.system() != "Linux":
        return jsonify({"ok": True, "message": "Pairing skipped (not on Linux)"})

    try:
        # Step 1: Try bluetoothctl pair (best-effort — many OBD adapters skip this)
        pair_out = subprocess.run(
            ["bluetoothctl", "pair", mac],
            capture_output=True, text=True, timeout=15,
        )
        pair_text = pair_out.stdout.lower() + pair_out.stderr.lower()
        if "successful" in pair_text or "already paired" in pair_text:
            logger.info(f"BT pair {mac}: bluetoothctl pairing successful")
        else:
            logger.info(f"BT pair {mac}: bluetoothctl pair didn't succeed ({pair_out.stdout.strip()}) — will try rfcomm directly")

        # Step 2: Always trust the device so rfcomm bind works
        subprocess.run(
            ["bluetoothctl", "trust", mac],
            capture_output=True, text=True, timeout=5,
        )

        # Step 3: Test rfcomm bind — release any existing binding first
        subprocess.run(["rfcomm", "release", "0"], capture_output=True, timeout=3)
        bind_result = subprocess.run(
            ["rfcomm", "bind", "0", mac, str(config.OBD_BT_CHANNEL)],
            capture_output=True, text=True, timeout=10,
        )
        bind_text = (bind_result.stdout + bind_result.stderr).lower()

        # Clean up the test binding
        subprocess.run(["rfcomm", "release", "0"], capture_output=True, timeout=3)

        if bind_result.returncode == 0 or "already" in bind_text:
            return jsonify({"ok": True, "message": f"Connected to {mac}"})
        else:
            # rfcomm bind failed — adapter may not be reachable
            logger.warning(f"BT pair {mac}: rfcomm bind failed — {bind_text.strip()}")
            return jsonify({"ok": False, "error": f"Could not reach {mac}. Is it plugged in and powered on?"})

    except subprocess.TimeoutExpired:
        return jsonify({"ok": False, "error": "Bluetooth pairing timed out"})
    except Exception as e:
        logger.warning(f"BT pair error: {e}")
        return jsonify({"ok": False, "error": str(e)})


# ---------------------------------------------------------------------------
# Bluetooth Phone Pairing & PAN (internet tethering)
# ---------------------------------------------------------------------------

@app.route("/api/phone/pair", methods=["POST"])
def api_phone_pair():
    """Pair with a phone for Bluetooth PAN internet tethering."""

    data = request.get_json(force=True)
    mac = data.get("mac", "").strip()
    if not mac:
        return jsonify({"ok": False, "error": "No MAC address provided"})

    ok, msg = bt_pan.bt_pair(mac)
    if ok:
        # Save the phone MAC to config
        config.save_setting("PHONE_BT_MAC", mac)
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/phone/unpair", methods=["POST"])
def api_phone_unpair():
    """Remove a paired phone."""

    mac = getattr(config, "PHONE_BT_MAC", "")
    if not mac:
        return jsonify({"ok": False, "error": "No phone paired"})

    bt_pan.bt_disconnect_pan(mac)
    ok, msg = bt_pan.bt_unpair(mac)
    if ok:
        config.save_setting("PHONE_BT_MAC", "")
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/phone/connect", methods=["POST"])
def api_phone_connect():
    """Connect to paired phone's Bluetooth PAN for internet."""

    mac = getattr(config, "PHONE_BT_MAC", "")
    if not mac:
        return jsonify({"ok": False, "error": "No phone paired — pair a phone first"})

    ok, msg = bt_pan.bt_connect_pan(mac)
    return jsonify({"ok": ok, "message": msg})


@app.route("/api/phone/disconnect", methods=["POST"])
def api_phone_disconnect():
    """Disconnect from phone's Bluetooth PAN."""

    mac = getattr(config, "PHONE_BT_MAC", "")
    if mac:
        bt_pan.bt_disconnect_pan(mac)
    return jsonify({"ok": True, "message": "Disconnected"})


@app.route("/api/phone/status", methods=["GET"])
def api_phone_status():
    """Get Bluetooth PAN connection status."""

    mac = getattr(config, "PHONE_BT_MAC", "")
    status = bt_pan.get_pan_status()
    status["phone_mac"] = mac
    status["auto_connect"] = bool(getattr(config, "PHONE_BT_AUTO", 0))
    return jsonify(status)


@app.route("/api/wifi-clients", methods=["GET"])
def api_wifi_clients():
    """Return list of devices connected to the Pi's WiFi hotspot."""
    clients = []
    try:
        # Read dnsmasq lease file for hostnames
        leases = {}
        lease_file = "/var/lib/misc/dnsmasq.leases"
        if os.path.exists(lease_file):
            with open(lease_file) as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 4:
                        # format: timestamp mac ip hostname client-id
                        leases[parts[1].lower()] = parts[3] if parts[3] != "*" else None

        # Get connected stations from hostapd via iw
        r = subprocess.run(
            ["iw", "dev", "wlan0", "station", "dump"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            current_mac = None
            for line in r.stdout.splitlines():
                line = line.strip()
                if line.startswith("Station"):
                    current_mac = line.split()[1].lower()
                    hostname = leases.get(current_mac)
                    clients.append({
                        "mac": current_mac,
                        "hostname": hostname,
                    })
    except Exception as e:
        logger.warning(f"Failed to get WiFi clients: {e}")
    return jsonify({"ok": True, "clients": clients})


@app.route("/api/restart", methods=["POST"])
def api_restart():
    """Restart the SignalKit service."""
    _schedule_restart(delay=1.5, reason="API request")
    return jsonify({"ok": True, "message": "Restarting in 1.5 seconds"})


@app.route("/api/update", methods=["GET"])
def api_update_get():
    """Return current git status for the OTA update page."""
    return jsonify(_git_info())


@app.route("/api/update", methods=["POST"])
def api_update_post():
    """Trigger an OTA update via git pull."""
    result = _git_pull()
    if result["status"] == "updated":
        _schedule_restart(reason="OTA update")
    elif result["status"] == "reboot_required":
        def _do_reboot():
            time.sleep(2.0)
            logger.info("Rebooting Pi to apply OTA update (overlayfs toggle)")
            os.system("sudo reboot")
        threading.Thread(target=_do_reboot, daemon=True).start()
    return jsonify(result)




# Standard OBD Mode 01 PID decoders: pid_byte -> (name, decode_func)
# decode_func takes data bytes (list of ints) and returns (value_str, unit)
_OBD_DECODERS = {
    0x04: ("Engine Load", lambda d: (f"{d[0] * 100 / 255:.1f}", "%")),
    0x05: ("Coolant Temp", lambda d: (f"{d[0] - 40}°C / {(d[0] - 40) * 9 / 5 + 32:.0f}°F", "")),
    0x06: ("Short Fuel Trim 1", lambda d: (f"{(d[0] - 128) * 100 / 128:.1f}", "%")),
    0x07: ("Long Fuel Trim 1", lambda d: (f"{(d[0] - 128) * 100 / 128:.1f}", "%")),
    0x08: ("Short Fuel Trim 2", lambda d: (f"{(d[0] - 128) * 100 / 128:.1f}", "%")),
    0x09: ("Long Fuel Trim 2", lambda d: (f"{(d[0] - 128) * 100 / 128:.1f}", "%")),
    0x0B: ("Intake Manifold Pressure", lambda d: (f"{d[0]}", "kPa")),
    0x0C: ("RPM", lambda d: (f"{(d[0] * 256 + d[1]) / 4:.0f}", "rpm")),
    0x0D: ("Speed", lambda d: (f"{d[0]} km/h / {d[0] * 0.621371:.0f} mph", "")),
    0x0E: ("Timing Advance", lambda d: (f"{d[0] / 2 - 64:.1f}", "°")),
    0x0F: ("Intake Air Temp", lambda d: (f"{d[0] - 40}°C / {(d[0] - 40) * 9 / 5 + 32:.0f}°F", "")),
    0x10: ("MAF Rate", lambda d: (f"{(d[0] * 256 + d[1]) / 100:.2f}", "g/s")),
    0x11: ("Throttle Position", lambda d: (f"{d[0] * 100 / 255:.1f}", "%")),
    0x1F: ("Run Time", lambda d: (f"{d[0] * 256 + d[1]}", "sec")),
    0x2F: ("Fuel Level", lambda d: (f"{d[0] * 100 / 255:.1f}", "%")),
    0x42: ("Control Module Voltage", lambda d: (f"{(d[0] * 256 + d[1]) / 1000:.2f}", "V")),
    0x46: ("Ambient Air Temp", lambda d: (f"{d[0] - 40}°C / {(d[0] - 40) * 9 / 5 + 32:.0f}°F", "")),
    0x5E: ("Fuel Rate", lambda d: (f"{(d[0] * 256 + d[1]) / 20:.2f}", "L/h")),
    0xA6: ("Odometer", lambda d: (f"{(d[0] * 16777216 + d[1] * 65536 + d[2] * 256 + d[3]) / 10:.1f} km / {(d[0] * 16777216 + d[1] * 65536 + d[2] * 256 + d[3]) / 10 * 0.621371:.0f} mi", "")),
}


def _decode_obd_response(raw_response, command):
    """Try to decode a raw OBD hex response into a human-readable string."""
    try:
        # Parse response lines — look for mode 41 responses (mode 01 + 0x40)
        for line in raw_response.split("\n"):
            line = line.strip()
            # Strip CAN header (e.g., "7E8 03") — find the 41 XX pattern
            hex_parts = line.replace(" ", "")
            # Look for "41" followed by the PID
            idx = hex_parts.find("41")
            if idx < 0:
                # Mode 03 (DTCs): look for "43" response
                idx = hex_parts.find("43")
                if idx >= 0:
                    dtc_data = hex_parts[idx + 2:]
                    if not dtc_data or dtc_data == "00" * 6:
                        return "No DTCs stored"
                    # Parse DTC pairs
                    dtcs = []
                    for i in range(0, len(dtc_data) - 3, 4):
                        b1, b2 = int(dtc_data[i:i+2], 16), int(dtc_data[i+2:i+4], 16)
                        if b1 == 0 and b2 == 0:
                            continue
                        prefix = ["P", "C", "B", "U"][(b1 >> 6) & 0x03]
                        code = f"{prefix}{(b1 & 0x3F):02X}{b2:02X}"
                        dtcs.append(code)
                    if dtcs:
                        return f"DTCs: {', '.join(dtcs)}"
                    return "No DTCs stored"
                continue

            payload = hex_parts[idx:]
            if len(payload) < 4:
                continue
            pid = int(payload[2:4], 16)
            data_hex = payload[4:]
            data_bytes = [int(data_hex[i:i+2], 16) for i in range(0, len(data_hex), 2)]

            if pid in _OBD_DECODERS and data_bytes:
                name, decoder = _OBD_DECODERS[pid]
                try:
                    val, unit = decoder(data_bytes)
                    return f"{name}: {val} {unit}"
                except (IndexError, ValueError):
                    pass

        # AT commands
        cmd_upper = command.strip().upper()
        if cmd_upper.startswith("AT"):
            return None  # AT responses are already readable

    except Exception:
        pass
    return None


@app.route("/api/dev/command", methods=["POST"])
def api_dev_command():
    """Execute a raw OBD/ELM327 command from the dev console."""
    body = request.get_json(silent=True)
    if not body or "command" not in body:
        return jsonify({"ok": False, "error": "Missing 'command' in request body"}), 400
    result = obd_reader.send_raw_command(body["command"])
    # Try to decode the response
    if result.get("ok") and result.get("response"):
        decoded = _decode_obd_response(result["response"], body["command"])
        if decoded:
            result["decoded"] = decoded
    return jsonify(result)


# ---------------------------------------------------------------------------
# Debug — single endpoint for phone-based troubleshooting
# ---------------------------------------------------------------------------

@app.route("/api/debug")
def api_debug():
    """
    Aggregated debug snapshot for development troubleshooting.
    Returns everything you'd normally SSH in to check.
    """
    import datetime

    # ── OBD connection state ──────────────────────────────────────────────
    data = obd_reader.get_data()
    diag = obd_reader.get_diagnostics()

    obd_info = {
        "connected": data.get("connected", False),
        "status": data.get("status"),
        "poll_errors": data.get("poll_errors", 0),
        "last_update": data.get("last_update"),
        "last_successful_query": obd_reader._last_successful_query,
        "seconds_since_last_query": (
            round(time.time() - obd_reader._last_successful_query, 1)
            if obd_reader._last_successful_query > 0 else None
        ),
        "connection_attempts": diag.get("connection_attempts", 0),
        "last_connect_time": diag.get("last_connect_time"),
        "protocol": diag.get("protocol"),
        "elm_version": diag.get("elm_version"),
        "bt_mac": diag.get("bt_mac"),
        "bt_port": diag.get("bt_port"),
        "bt_channel": diag.get("bt_channel"),
        "supported_pid_count": len(diag.get("supported_pids", [])),
        "vin": diag.get("vin"),
        "vehicle": diag.get("vehicle"),
    }

    # ── Current config snapshot ───────────────────────────────────────────
    cfg = {
        "OBD_MAC": config.OBD_MAC,
        "OBD_PORT": config.OBD_PORT,
        "OBD_BAUDRATE": config.OBD_BAUDRATE,
        "OBD_RECONNECT_DELAY": config.OBD_RECONNECT_DELAY,
        "OBD_BT_CHANNEL": config.OBD_BT_CHANNEL,
        "SCAN_PIDS_ON_BOOT": config.SCAN_PIDS_ON_BOOT,
        "FULLSCREEN": config.FULLSCREEN,
        "COLOR_THEME": config.COLOR_THEME,
        "SCREEN_BRIGHTNESS": config.SCREEN_BRIGHTNESS,
        "restart_pending": config.restart_pending,
    }

    # ── System info ───────────────────────────────────────────────────────
    sys_info = _get_system_info()
    sys_info["platform"] = platform.platform()
    sys_info["python"] = platform.python_version()
    sys_info["time"] = datetime.datetime.now().isoformat()
    sys_info["time_utc"] = datetime.datetime.utcnow().isoformat()

    # Disk usage
    try:
        r = subprocess.run(["df", "-h", "/"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            lines = r.stdout.strip().splitlines()
            if len(lines) >= 2:
                sys_info["disk"] = lines[1].split()[1:5]  # size, used, avail, use%
    except Exception:
        pass

    # ── Active threads ────────────────────────────────────────────────────
    threads = [
        {"name": t.name, "daemon": t.daemon, "alive": t.is_alive()}
        for t in threading.enumerate()
    ]

    # ── Recent SignalKit journal logs ─────────────────────────────────────
    logs = []
    try:
        r = subprocess.run(
            ["journalctl", "-u", "signalkit", "--no-pager", "-n", "50",
             "--output", "short-iso"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            logs = r.stdout.strip().splitlines()
    except Exception:
        logs = ["(journalctl not available)"]

    # ── Network interfaces ────────────────────────────────────────────────
    net = {}
    try:
        r = subprocess.run(
            ["ip", "-brief", "addr"], capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            for line in r.stdout.strip().splitlines():
                parts = line.split()
                if len(parts) >= 3:
                    net[parts[0]] = {"state": parts[1], "addrs": parts[2:]}
                elif len(parts) == 2:
                    net[parts[0]] = {"state": parts[1], "addrs": []}
    except Exception:
        pass

    # ── Bluetooth adapter state ───────────────────────────────────────────
    bt_state = None
    try:
        r = subprocess.run(
            ["bluetoothctl", "show"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            bt_state = r.stdout.strip()
    except Exception:
        pass

    # ── Git version ───────────────────────────────────────────────────────
    version = _git_info()

    # ── Full /api/data snapshot ─────────────────────────────────────────
    data["restart_pending"] = config.restart_pending

    return jsonify({
        "data": data,
        "obd": obd_info,
        "config": cfg,
        "system": sys_info,
        "threads": threads,
        "network": net,
        "bluetooth": bt_state,
        "version": version,
        "logs": logs,
    })


# ---------------------------------------------------------------------------
# Version & OTA Upload
# ---------------------------------------------------------------------------

@app.route("/api/version")
def api_version():
    """Return current app version, git hash, and branch."""
    info = _git_info()
    # Read full git hash for precise comparison
    full_hash = "unknown"
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=_APP_DIR, capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0:
            full_hash = r.stdout.strip()
    except Exception:
        pass

    # If an OTA update was applied, .ota_sha has the deployed commit
    ota_sha_path = os.path.join(_APP_DIR, ".ota_sha")
    ota_sha = None
    if os.path.isfile(ota_sha_path):
        try:
            with open(ota_sha_path) as f:
                ota_sha = f.read().strip()
        except Exception:
            pass

    return jsonify({
        "version": config.APP_VERSION,
        "hash": ota_sha or full_hash,
        "hash_short": (ota_sha or info.get("hash", "unknown"))[:7],
        "branch": info.get("branch", "unknown"),
        "date": info.get("date", ""),
        "subject": info.get("subject", ""),
        "ota_applied": ota_sha is not None,
    })


@app.route("/api/update/upload", methods=["POST"])
def api_update_upload():
    """
    Accept a tar.gz of the signalkit directory from the mobile app,
    extract it over the current install, and restart the service.

    Expected: multipart form with field 'update' containing a .tar.gz file.
    The archive should contain the repo files rooted at the repo root
    (e.g., signalkit/, VERSION, etc.).
    """
    import tarfile
    import shutil

    if "update" not in request.files:
        return jsonify({"ok": False, "error": "No 'update' file in request"}), 400

    upload = request.files["update"]
    if not upload.filename:
        return jsonify({"ok": False, "error": "Empty filename"}), 400

    # Save to a temp file
    tmp_path = os.path.join(tempfile.gettempdir(), "signalkit_update.tar.gz")
    try:
        upload.save(tmp_path)
        logger.info(f"OTA upload received: {upload.filename} ({os.path.getsize(tmp_path)} bytes)")

        # Validate it's a real tar.gz
        if not tarfile.is_tarfile(tmp_path):
            os.unlink(tmp_path)
            return jsonify({"ok": False, "error": "Not a valid tar.gz archive"}), 400

        # Extract to a staging directory first
        staging = os.path.join(tempfile.gettempdir(), "signalkit_staging")
        if os.path.exists(staging):
            shutil.rmtree(staging)
        os.makedirs(staging)

        with tarfile.open(tmp_path, "r:gz") as tar:
            # Security: reject paths that escape the staging dir
            for member in tar.getmembers():
                if member.name.startswith("/") or ".." in member.name:
                    os.unlink(tmp_path)
                    shutil.rmtree(staging)
                    return jsonify({"ok": False, "error": f"Unsafe path in archive: {member.name}"}), 400
            tar.extractall(path=staging)

        # Determine the actual root inside staging
        # (handles both flat extraction and single-directory wrapping)
        entries = os.listdir(staging)
        extract_root = staging
        if len(entries) == 1 and os.path.isdir(os.path.join(staging, entries[0])):
            extract_root = os.path.join(staging, entries[0])

        # Verify it looks like a SignalKit update (has signalkit/ dir or VERSION)
        has_signalkit = os.path.isdir(os.path.join(extract_root, "signalkit"))
        has_version = os.path.isfile(os.path.join(extract_root, "VERSION"))
        if not has_signalkit and not has_version:
            shutil.rmtree(staging)
            os.unlink(tmp_path)
            return jsonify({"ok": False, "error": "Archive doesn't look like a SignalKit update"}), 400

        # Read the new version before applying
        new_version = None
        if has_version:
            with open(os.path.join(extract_root, "VERSION")) as f:
                new_version = f.read().strip()

        # Only copy Pi-relevant directories/files (skip mobile/, .github/, etc.)
        _ALLOWED_PATHS = {"signalkit", "preview.py", "VERSION", "requirements.txt", "setup.py", "setup.cfg", "pyproject.toml"}
        updated_count = 0
        for entry in os.listdir(extract_root):
            # Check if this top-level entry is in the allowlist
            if entry not in _ALLOWED_PATHS:
                logger.info(f"OTA: skipping {entry}")
                continue
            src_path = os.path.join(extract_root, entry)
            dst_path = os.path.join(_APP_DIR, entry)
            if os.path.isdir(src_path):
                # Copy directory tree, overwriting existing files
                for dirpath, dirnames, filenames in os.walk(src_path):
                    rel_dir = os.path.relpath(dirpath, src_path)
                    dest_dir = os.path.join(dst_path, rel_dir)
                    os.makedirs(dest_dir, exist_ok=True)
                    for fname in filenames:
                        s = os.path.join(dirpath, fname)
                        d = os.path.join(dest_dir, fname)
                        shutil.copy2(s, d)
                        updated_count += 1
                        logger.info(f"OTA: updated {entry}/{os.path.relpath(d, dst_path)}")
            else:
                shutil.copy2(src_path, dst_path)
                updated_count += 1
                logger.info(f"OTA: updated {entry}")

        # Write deployed SHA so version endpoint can report it
        # (git HEAD won't change since we're copying over a repo)
        ota_sha_path = os.path.join(_APP_DIR, ".ota_sha")
        # Try to extract SHA from the wrapper directory name (GitHub format: User-Repo-SHA/)
        wrapper_name = os.path.basename(extract_root)
        parts = wrapper_name.rsplit("-", 1)
        if len(parts) == 2 and len(parts[1]) >= 7:
            with open(ota_sha_path, "w") as f:
                f.write(parts[1])
            logger.info(f"OTA: wrote .ota_sha = {parts[1]}")

        # Clean up
        shutil.rmtree(staging)
        os.unlink(tmp_path)

        logger.info(f"OTA update applied: {updated_count} files (version: {new_version})")

        _schedule_restart(reason="OTA upload")

        return jsonify({
            "ok": True,
            "message": f"Update applied — restarting",
            "version": new_version,
        })

    except Exception as e:
        logger.error(f"OTA upload failed: {e}")
        # Clean up on error
        for p in [tmp_path, os.path.join(tempfile.gettempdir(), "signalkit_staging")]:
            try:
                if os.path.isfile(p):
                    os.unlink(p)
                elif os.path.isdir(p):
                    shutil.rmtree(p)
            except Exception:
                pass
        return jsonify({"ok": False, "error": str(e)}), 500


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

def run_server():
    """Start the Flask web server (blocking)."""
    logger.info(f"Starting web server on {config.WEB_HOST}:{config.WEB_PORT}")
    app.run(host=config.WEB_HOST, port=config.WEB_PORT, debug=False, use_reloader=False, threaded=True)
