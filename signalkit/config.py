# =============================================================================
# config.py - SignalKit Configuration
# =============================================================================
# Edit this file to set hardware defaults before building the image.
# The most important setting is OBD_MAC — set it to your Veepeak adapter's
# Bluetooth MAC address (find it by running: hcitool scan)
#
# Runtime overrides:
#   Settings changed via the web UI (http://192.168.4.1:5000/settings) are
#   saved to /boot/signalkit-config.json — the FAT32 boot partition, which is
#   always writable on Raspberry Pi even with the read-only overlayfs root.
#   Those overrides are loaded here at startup and win over the defaults below.
# =============================================================================

import json
import logging
import os
import sys

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Version — read from VERSION file at repo root
# ---------------------------------------------------------------------------
_VERSION_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "VERSION")
try:
    with open(_VERSION_FILE) as _f:
        APP_VERSION = _f.read().strip()
except FileNotFoundError:
    APP_VERSION = "dev"

# Callback invoked after a setting is saved. Set by display.py at startup.
_on_setting_changed = None

# True when a restart-required setting has been changed but not yet restarted.
# Lives only in memory — cleared automatically on reboot/restart.
restart_pending = False

# Path to the user overrides file on the FAT32 boot partition.
# Tries the newer Pi OS path first (/boot/firmware), then legacy (/boot),
# then a local fallback for development on non-Pi machines.
_OVERRIDE_PATHS = [
    "/boot/firmware/signalkit-config.json",
    "/boot/signalkit-config.json",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "signalkit-config.json"),
]

# Resolved path actually in use — set by load_overrides()
_active_override_path = None  # type: str | None

# ---------------------------------------------------------------------------
# Defaults — all settings start here, then overrides are applied on top
# ---------------------------------------------------------------------------

# --- OBD2 Adapter ---
OBD_MAC = "AA:BB:CC:DD:EE:FF"   # Replace with your Veepeak adapter's MAC
OBD_PORT = "/dev/rfcomm0"        # Serial port after rfcomm bind
OBD_BAUDRATE = 38400             # ELM327 default baud rate
OBD_CONNECT_TIMEOUT = 30         # Seconds to wait for connection on boot
OBD_RECONNECT_DELAY = 5          # Seconds to wait before retrying after disconnect
OBD_BT_CHANNEL = 1               # RFCOMM channel (most ELM327 adapters use 1)

# --- Phone Bluetooth (internet tethering via PAN) ---
PHONE_BT_MAC = ""                # Paired phone's MAC for Bluetooth PAN internet
PHONE_BT_AUTO = 1                # 1 = auto-connect to phone PAN on boot

# --- WiFi Hotspot ---
HOTSPOT_SSID = "SignalKit"
HOTSPOT_PASSWORD = "signalkit1234"   # Default WiFi password (change in setup wizard or settings)
HOTSPOT_IP = "192.168.4.1"
HOTSPOT_INTERFACE = "wlan0"

# --- First-Run ---
SETUP_COMPLETE = 0               # Set to 1 after setup wizard completes

# --- Web Server ---
WEB_PORT = 8080
WEB_HOST = "0.0.0.0"

# --- Display ---
SCREEN_WIDTH = 800
SCREEN_HEIGHT = 480
TARGET_FPS = 30
FULLSCREEN = True                # Set False for windowed/debug mode
TIME_24HR = True                 # True = 24-hour clock, False = 12-hour with AM/PM
UNITS_SPEED = "mph"              # "mph" or "kmh"
UNITS_TEMP = "C"                 # "C" (Celsius) or "F" (Fahrenheit)
COLOR_THEME = "red"              # Accent color theme
SHOW_SPARKLINES = 1              # 1 = show sparkline graphs, 0 = hide
SCREEN_BRIGHTNESS = 1.0          # xrandr brightness (0.3=dim, 1.0=normal, 2.0=bright)

# --- Theme Presets ---
THEMES = {
    "blue":   {"accent": "#3b82f6", "glow": "#3b82f680"},
    "red":    {"accent": "#DC2626", "glow": "#DC262680"},
    "green":  {"accent": "#22c55e", "glow": "#22c55e80"},
    "purple": {"accent": "#a855f7", "glow": "#a855f780"},
    "orange": {"accent": "#f97316", "glow": "#f9731680"},
    "cyan":   {"accent": "#06b6d4", "glow": "#06b6d480"},
    "pink":   {"accent": "#ec4899", "glow": "#ec489980"},
}

def get_theme() -> dict:
    """Return the active theme dict. Falls back to red."""
    return THEMES.get(COLOR_THEME, THEMES["red"])

# --- Dashboard Layout ---
# Cards to show in the metrics row (up to 4) and slow row (up to 3).
# Valid card IDs: coolant, battery, throttle, load, iat, oil, fuel_trim, mpg
LAYOUT_METRICS = ["coolant", "battery", "throttle", "load"]
LAYOUT_SLOW = ["iat", "oil", "fuel_trim"]

# --- Polling Intervals (seconds) ---
FAST_POLL_INTERVAL = 1.0         # RPM, speed, throttle, engine load
SLOW_POLL_INTERVAL = 5.0         # Coolant temp, battery voltage, fuel trim, IAT
SCAN_PIDS_ON_BOOT = 1            # 1 = scan all PIDs on connect, 0 = skip

# --- Warning Thresholds ---
COOLANT_OVERHEAT_C = 105         # Coolant temperature overheat warning (°C)
BATTERY_LOW_V = 12.0             # Battery voltage low warning (V)
BATTERY_CRITICAL_V = 11.5        # Battery voltage critical warning (V)
RPM_REDLINE = 6500               # RPM redline for visual indicator

# --- Kia Extended PIDs ---
KIA_OIL_TEMP_PID = "2101"
KIA_OIL_TEMP_BYTE = 7
KIA_OIL_TEMP_SCALE = 0.75
KIA_OIL_TEMP_OFFSET = -48

# --- Colors (RGB tuples) ---
# Matches the web UI's modern dark theme
COLOR_BG = (10, 10, 10)             # --bg: #0a0a0a
COLOR_PANEL = (14, 14, 14)          # --surface: #0e0e0e
COLOR_CARD = (14, 14, 14)           # --surface: #0e0e0e
COLOR_BORDER = (40, 10, 10)         # --border: red-tinted
COLOR_TEXT_PRIMARY = (255, 255, 255) # --text: #ffffff
COLOR_TEXT_SECONDARY = (140, 140, 140) # --text-dim: rgba(255,255,255,0.55)
COLOR_TEXT_DIM = (77, 77, 77)        # --text-muted: rgba(255,255,255,0.30)
COLOR_ACCENT = (220, 38, 38)        # --accent: #DC2626 (Signal Red)
COLOR_GOOD = (34, 197, 94)           # --good: #22c55e
COLOR_WARNING = (250, 176, 5)        # --warn: #fab005
COLOR_DANGER = (239, 68, 68)         # --danger: #ef4444
COLOR_DTC = (248, 113, 113)          # lighter red for DTC text
COLOR_RPM_BAR = (220, 38, 38)        # matches accent red
COLOR_RPM_RED = (239, 68, 68)
COLOR_GAUGE_BG = (20, 20, 20)        # subtle arc background

# ---------------------------------------------------------------------------
# Editable settings registry
# ---------------------------------------------------------------------------
# Defines which settings can be changed at runtime via the web UI.
# Each key is a config variable name; the value is display/validation metadata.
#
# Fields:
#   label       — human-readable name shown in the settings form
#   type        — "str", "int", or "float" — used for casting and input type
#   min / max   — (numeric only) valid range; form enforces these limits
#   restart     — True if a SignalKit restart is needed for the change to take effect
#   description — hint text shown below the input field

EDITABLE_SETTINGS = {
    "OBD_MAC": {
        "label": "OBD2 Adapter",
        "type": "bt_mac",
        "restart": True,
        "description": "Select your OBD2 Bluetooth adapter from nearby devices.",
    },
    "OBD_BT_CHANNEL": {
        "label": "Bluetooth RFCOMM Channel",
        "type": "int", "min": 1, "max": 10,
        "restart": True,
        "description": "Almost always 1 for ELM327 adapters.",
    },
    "COOLANT_OVERHEAT_C": {
        "label": "Overheat Warning (°C)",
        "type": "int", "min": 80, "max": 130,
        "restart": False,
        "description": "Coolant temperature at which the overheat alert triggers.",
    },
    "BATTERY_LOW_V": {
        "label": "Low Battery Warning (V)",
        "type": "float", "min": 10.0, "max": 14.0,
        "restart": False,
        "description": "Battery voltage that triggers the amber low warning.",
    },
    "BATTERY_CRITICAL_V": {
        "label": "Critical Battery Warning (V)",
        "type": "float", "min": 9.0, "max": 13.0,
        "restart": False,
        "description": "Battery voltage that triggers the red critical warning.",
    },
    "RPM_REDLINE": {
        "label": "RPM Redline",
        "type": "int", "min": 3000, "max": 10000,
        "restart": False,
        "description": "RPM at which the bar turns red. Kia Forte 1.8L stock: 6500.",
    },
    "FAST_POLL_INTERVAL": {
        "label": "Fast Poll Interval (seconds)",
        "type": "float", "min": 0.5, "max": 5.0,
        "restart": True,
        "description": "How often to poll RPM, speed, throttle, and engine load.",
    },
    "SLOW_POLL_INTERVAL": {
        "label": "Slow Poll Interval (seconds)",
        "type": "float", "min": 2.0, "max": 60.0,
        "restart": True,
        "description": "How often to poll coolant temp, battery voltage, and fuel trim.",
    },
    "SCAN_PIDS_ON_BOOT": {
        "label": "Scan PIDs on Connect",
        "type": "select",
        "options": [("1", "On"), ("0", "Off")],
        "cast": "int",
        "restart": False,
        "description": "Scan all supported PIDs when connecting. Disable for faster startup.",
    },
    "HOTSPOT_SSID": {
        "label": "WiFi Hotspot Name (SSID)",
        "type": "str",
        "restart": True,
        "description": "The WiFi network name phones will see. Requires a full system reboot.",
    },
    "TIME_24HR": {
        "label": "Clock Format",
        "type": "select",
        "options": [("1", "24-hour (14:30)"), ("0", "12-hour (2:30 PM)")],
        "cast": "int",
        "restart": False,
        "description": "",
    },
    "UNITS_SPEED": {
        "label": "Speed Units",
        "type": "select",
        "options": [("mph", "MPH"), ("kmh", "km/h")],
        "restart": False,
        "description": "",
    },
    "UNITS_TEMP": {
        "label": "Temperature Units",
        "type": "select",
        "options": [("C", "Celsius (°C)"), ("F", "Fahrenheit (°F)")],
        "restart": False,
        "description": "",
    },
    "COLOR_THEME": {
        "label": "Color Theme",
        "type": "select",
        "options": [("blue", "Blue"), ("red", "Red"), ("green", "Green"), ("purple", "Purple"), ("orange", "Orange"), ("cyan", "Cyan"), ("pink", "Pink")],
        "restart": False,
        "description": "",
    },
    "SHOW_SPARKLINES": {
        "label": "Sparkline Graphs",
        "type": "select",
        "options": [("1", "On"), ("0", "Off")],
        "cast": "int",
        "restart": False,
        "description": "Tiny trend graphs on the HDMI dashboard cards.",
    },
    "SCREEN_BRIGHTNESS": {
        "label": "Screen Brightness",
        "type": "float", "min": 0.3, "max": 2.0,
        "restart": False,
        "description": "Display brightness via xrandr. 1.0 = normal, 2.0 = max for daylight.",
    },
    "LAYOUT_METRICS": {
        "label": "Metrics Row Cards",
        "type": "str",
        "restart": False,
        "description": "Comma-separated card IDs (up to 4): coolant, battery, throttle, load, iat, oil, fuel_trim, mpg",
    },
    "LAYOUT_SLOW": {
        "label": "Secondary Row Cards",
        "type": "str",
        "restart": False,
        "description": "Comma-separated card IDs (up to 3): coolant, battery, throttle, load, iat, oil, fuel_trim, mpg",
    },
    "HOTSPOT_PASSWORD": {
        "label": "WiFi Password",
        "type": "str",
        "restart": True,
        "description": "Leave blank for an open network. Must be 8+ characters if set.",
    },
    "PHONE_BT_MAC": {
        "label": "Phone Bluetooth",
        "type": "bt_phone",
        "restart": False,
        "description": "Pair your phone for internet access (Bluetooth tethering).",
    },
    "PHONE_BT_AUTO": {
        "label": "Auto-Connect Phone",
        "type": "select",
        "options": [("1", "On"), ("0", "Off")],
        "cast": "int",
        "restart": False,
        "description": "Automatically connect to phone's Bluetooth tethering on boot.",
    },
    "SETUP_COMPLETE": {
        "label": "Setup Complete",
        "type": "select",
        "options": [("1", "Yes"), ("0", "No")],
        "cast": "int",
        "restart": False,
        "description": "Reset to No to show the setup wizard again.",
        "hidden": True,
    },
}


# ---------------------------------------------------------------------------
# Override loading and saving
# ---------------------------------------------------------------------------

def _find_writable_path() -> str:
    """
    Find the best writable path for the override file.
    Prefers the FAT32 boot partition; falls back to a local file.
    """
    global _active_override_path
    if _active_override_path:
        return _active_override_path

    for path in _OVERRIDE_PATHS:
        directory = os.path.dirname(path)
        if os.path.isdir(directory) and os.access(directory, os.W_OK):
            _active_override_path = path
            return path

    # Absolute fallback
    fallback = _OVERRIDE_PATHS[-1]
    _active_override_path = fallback
    return fallback


def load_overrides():
    """
    Load saved overrides from the JSON file and apply them to this module's
    globals. Called automatically at the bottom of this file on import.
    """
    global _active_override_path

    for path in _OVERRIDE_PATHS:
        if os.path.exists(path):
            _active_override_path = path
            try:
                with open(path, "r") as f:
                    overrides = json.load(f)
                _apply(overrides)
                _logger.info(f"Loaded config overrides from {path}")
            except Exception as e:
                _logger.warning(f"Could not read overrides from {path}: {e}")
            return

    _logger.debug("No override file found — using compiled defaults")


_LIST_SETTINGS = {"LAYOUT_METRICS", "LAYOUT_SLOW"}


def _apply(overrides: dict):
    """Apply a {key: value} dict to this module's globals."""
    module = sys.modules[__name__]
    for key, value in overrides.items():
        if key in EDITABLE_SETTINGS and hasattr(module, key):
            # List settings are stored as comma-separated strings in JSON
            if key in _LIST_SETTINGS and isinstance(value, str):
                value = [v.strip() for v in value.split(",") if v.strip()]
            setattr(module, key, value)
            _logger.debug(f"Override: {key} = {value!r}")
        else:
            _logger.debug(f"Ignoring unrecognised override key: {key!r}")


def save_setting(key, raw_value):
    """
    Validate, persist, and immediately apply a single setting change.

    The value is written to the override JSON file on the boot partition so
    it survives a reboot. It is also applied in-memory right now so the
    dashboard reflects the change without restarting (for threshold settings).

    Args:
        key:       Name of a setting in EDITABLE_SETTINGS
        raw_value: Raw string from the web form (will be type-cast)

    Returns:
        (success, message) — message is shown to the user in the web UI
    """
    module = sys.modules[__name__]

    if key not in EDITABLE_SETTINGS:
        return False, f"Unknown setting: {key!r}"

    meta = EDITABLE_SETTINGS[key]

    # Type casting
    try:
        if meta["type"] == "int":
            value = int(raw_value)
        elif meta["type"] == "float":
            value = round(float(raw_value), 4)
        elif meta["type"] == "select":
            value = str(raw_value).strip()
            valid_values = [opt[0] for opt in meta.get("options", [])]
            if valid_values and value not in valid_values:
                return False, f"Invalid choice: {value!r}"
            # Some select settings store as int (e.g. TIME_24HR: 1/0)
            if meta.get("cast") == "int":
                value = int(value)
        else:
            value = str(raw_value).strip()
    except (ValueError, TypeError):
        return False, f"Invalid value — expected {meta['type']}"

    # List settings: parse comma-separated string, store as string in JSON
    if key in _LIST_SETTINGS:
        parsed = [v.strip() for v in value.split(",") if v.strip()]
        if not parsed:
            return False, "Must have at least one card"

    # Range validation
    if meta["type"] in ("int", "float"):
        if "min" in meta and value < meta["min"]:
            return False, f"Must be at least {meta['min']}"
        if "max" in meta and value > meta["max"]:
            return False, f"Must be at most {meta['max']}"

    # Persist to override file (always store as the raw string/number)
    override_path = _find_writable_path()
    try:
        existing: dict = {}
        if os.path.exists(override_path):
            with open(override_path, "r") as f:
                existing = json.load(f)
        existing[key] = value
        with open(override_path, "w") as f:
            json.dump(existing, f, indent=2)
    except Exception as e:
        _logger.error(f"Failed to write {override_path}: {e}")
        return False, f"Disk write failed: {e}"

    # Apply in-memory immediately (lists get the parsed version)
    if key in _LIST_SETTINGS:
        setattr(module, key, parsed)
    else:
        setattr(module, key, value)
    _logger.info(f"Setting updated: {key} = {value!r}")

    # Apply brightness immediately if changed
    if key == "SCREEN_BRIGHTNESS":
        apply_brightness(value)

    # Only notify the HDMI display for settings that affect the live dashboard
    # (theme, units, sparklines, layout, thresholds). Skip for restart-required
    # settings since those need a full restart anyway, and triggering a display
    # reload just causes a distracting splash screen flash.
    _LIVE_DISPLAY_KEYS = {
        "COLOR_THEME", "UNITS_SPEED", "UNITS_TEMP", "TIME_24HR",
        "SHOW_SPARKLINES", "LAYOUT_METRICS", "LAYOUT_SLOW",
        "COOLANT_OVERHEAT_C", "BATTERY_LOW_V", "BATTERY_CRITICAL_V",
        "RPM_REDLINE", "SCREEN_BRIGHTNESS",
    }
    if key in _LIVE_DISPLAY_KEYS and _on_setting_changed:
        try:
            _logger.info("Notifying display of config change: %s", key)
            _on_setting_changed()
        except Exception as e:
            _logger.warning(f"Failed to notify display: {e}")

    if meta.get("restart"):
        global restart_pending
        restart_pending = True
        return True, "Saved — restart SignalKit for this change to take effect"
    return True, "Saved"


def get_current_settings() -> dict:
    """
    Return all editable settings with their current live values and metadata.
    Used by the web UI to populate the settings form.
    """
    module = sys.modules[__name__]
    result = {}
    for key, meta in EDITABLE_SETTINGS.items():
        val = getattr(module, key, None)
        # Serialize lists to comma-separated strings for web UI
        if key in _LIST_SETTINGS and isinstance(val, list):
            val = ", ".join(val)
        result[key] = {"value": val, **meta}
    return result


# ---------------------------------------------------------------------------
# Screen brightness via xrandr
# ---------------------------------------------------------------------------

import subprocess as _subprocess
import shutil as _shutil

def apply_brightness(level=None):
    """Set screen brightness via xrandr. No-op if xrandr is not available."""
    if level is None:
        level = SCREEN_BRIGHTNESS
    level = max(0.3, min(2.0, float(level)))
    if not _shutil.which("xrandr"):
        return
    try:
        # Find the connected output name
        out = _subprocess.check_output(["xrandr", "--current"],
                                       stderr=_subprocess.DEVNULL).decode()
        for line in out.splitlines():
            if " connected" in line:
                output_name = line.split()[0]
                _subprocess.run(["xrandr", "--output", output_name,
                                 "--brightness", str(level)],
                                stderr=_subprocess.DEVNULL)
                _logger.info(f"Screen brightness set to {level} on {output_name}")
                return
    except Exception as e:
        _logger.warning(f"Failed to set brightness: {e}")


# ---------------------------------------------------------------------------
# Apply overrides immediately when this module is imported
# ---------------------------------------------------------------------------
load_overrides()
apply_brightness()
