#!/usr/bin/env python3
"""
SignalKit QML Display — Qt/QML-based UI for the HDMI touchscreen.

Run directly for development:
    python signalkit/qml_display.py

On Raspberry Pi (direct framebuffer, no X11):
    python signalkit/qml_display.py -platform eglfs
"""
import os
import sys
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Qt backend: PySide6 (macOS dev) or PyQt6 (Raspberry Pi) ──────
try:
    # PySide6 — macOS dev (pip-installed, needs plugin path fix)
    import ctypes, ctypes.util
    _libc = ctypes.CDLL(ctypes.util.find_library("c"))
    import PySide6 as _pyside6
    _qt_plugins = os.path.join(os.path.dirname(_pyside6.__file__), "Qt", "plugins")
    _libc.setenv(b"QT_PLUGIN_PATH", _qt_plugins.encode(), ctypes.c_int(1))
    os.environ["QT_PLUGIN_PATH"] = _qt_plugins
    del _libc, _qt_plugins, _pyside6

    from PySide6.QtCore import QObject, Property, Signal, QTimer, QUrl, Slot
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine
    _BACKEND = "PySide6"

except ImportError:
    # PyQt6 — Raspberry Pi (system packages via apt)
    from PyQt6.QtCore import QObject, QTimer, QUrl
    from PyQt6.QtCore import pyqtProperty as Property
    from PyQt6.QtCore import pyqtSignal as Signal
    from PyQt6.QtCore import pyqtSlot as Slot
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtQml import QQmlApplicationEngine
    _BACKEND = "PyQt6"
# ──────────────────────────────────────────────────────────────────

# ── OBD backend: optional import ──────────────────────────────────
_obd_available = False
try:
    # Add signalkit dir to path so obd_reader can find its siblings
    _sk_dir = os.path.dirname(os.path.abspath(__file__))
    if _sk_dir not in sys.path:
        sys.path.insert(0, _sk_dir)

    import obd_reader
    import config
    _obd_available = True
except ImportError as e:
    logger.info(f"OBD backend not available ({e}) — running in demo mode")
# ──────────────────────────────────────────────────────────────────


def _fmt_number(val, decimals=0):
    """Format a numeric value for display, or '---' if None."""
    if val is None:
        return "---"
    if decimals == 0:
        return f"{int(val):,}"
    return f"{val:.{decimals}f}"


class Bridge(QObject):
    """Python↔QML bridge — exposes live OBD data as QML properties."""

    # Change signals — one per property group
    accentChanged = Signal()
    clockChanged = Signal()
    obdChanged = Signal()

    def __init__(self):
        super().__init__()

        # Theme
        self._accent = "#3b82f6"
        if _obd_available:
            theme = config.get_theme()
            self._accent = theme.get("accent", self._accent)

        # Clock
        self._clock_text = ""
        self._update_clock()

        # OBD state
        self._obd_connected = False
        self._status_text = "Disconnected"
        self._rpm = "---"
        self._rpm_ratio = 0.0
        self._speed = "---"
        self._vehicle_moving = False
        self._coolant = "---"
        self._battery_voltage = "---"
        self._battery_color = "#e4e4e7"
        self._throttle = "---"
        self._engine_load = "---"
        self._dtc_count = 0
        self._dtc_text = "No active fault codes"
        self._dtc_color = "#22c55e"
        self._mpg = "---"
        self._oil_temp = "---"
        self._intake_air_temp = "---"
        self._speed_unit = "MPH"
        self._temp_unit = "°C"

        # Clock timer (every 10s)
        self._clock_timer = QTimer(self)
        self._clock_timer.timeout.connect(self._update_clock)
        self._clock_timer.start(10_000)

        # OBD poll timer (every 500ms)
        if _obd_available:
            self._obd_timer = QTimer(self)
            self._obd_timer.timeout.connect(self._poll_obd)
            self._obd_timer.start(500)

    # ── Clock ─────────────────────────────────────────────────────
    def _update_clock(self):
        now = datetime.now()
        if _obd_available and hasattr(config, "TIME_24HR") and config.TIME_24HR:
            self._clock_text = f"{now.hour:02d}:{now.minute:02d}"
        else:
            h = now.hour % 12 or 12
            ampm = "PM" if now.hour >= 12 else "AM"
            self._clock_text = f"{h}:{now.minute:02d} {ampm}"
        self.clockChanged.emit()

    # ── OBD polling ───────────────────────────────────────────────
    def _poll_obd(self):
        if not _obd_available:
            return
        data = obd_reader.get_data()

        changed = False

        # Connection state
        conn = data.get("connected", False)
        if conn != self._obd_connected:
            self._obd_connected = conn
            changed = True

        status = data.get("status", "Disconnected")
        if status != self._status_text:
            self._status_text = status
            changed = True

        # RPM
        rpm_val = data.get("rpm")
        rpm_str = _fmt_number(rpm_val)
        if rpm_str != self._rpm:
            self._rpm = rpm_str
            changed = True

        # RPM bar ratio (0.0 - 1.0 based on redline)
        redline = config.RPM_REDLINE if _obd_available else 6500
        ratio = min((rpm_val or 0) / redline, 1.0)
        if abs(ratio - self._rpm_ratio) > 0.005:
            self._rpm_ratio = ratio
            changed = True

        # Speed
        speed_val = data.get("speed")
        speed_str = _fmt_number(speed_val, 0)
        if speed_str != self._speed:
            self._speed = speed_str
            changed = True

        moving = (speed_val or 0) > 0
        if moving != self._vehicle_moving:
            self._vehicle_moving = moving
            changed = True

        # Speed unit
        unit = "MPH"
        if _obd_available and getattr(config, "UNITS_SPEED", "mph") == "kmh":
            unit = "km/h"
        if unit != self._speed_unit:
            self._speed_unit = unit
            changed = True

        # Coolant temp
        coolant_val = data.get("coolant_temp")
        coolant_str = _fmt_number(coolant_val, 0)
        if coolant_str != self._coolant:
            self._coolant = coolant_str
            changed = True

        # Temp unit
        tunit = "°C"
        if _obd_available and getattr(config, "UNITS_TEMP", "C") == "F":
            tunit = "°F"
        if tunit != self._temp_unit:
            self._temp_unit = tunit
            changed = True

        # Battery voltage
        batt_val = data.get("battery_voltage")
        batt_str = _fmt_number(batt_val, 1)
        if batt_str != self._battery_voltage:
            self._battery_voltage = batt_str
            changed = True

        # Battery color (green/yellow/red based on thresholds)
        batt_color = "#e4e4e7"
        if batt_val is not None:
            if batt_val >= 13.0:
                batt_color = "#22c55e"  # good
            elif batt_val >= config.BATTERY_LOW_V:
                batt_color = "#e4e4e7"  # normal
            elif batt_val >= config.BATTERY_CRITICAL_V:
                batt_color = "#fab005"  # warning
            else:
                batt_color = "#ef4444"  # critical
        if batt_color != self._battery_color:
            self._battery_color = batt_color
            changed = True

        # Throttle
        throttle_val = data.get("throttle")
        throttle_str = _fmt_number(throttle_val, 0)
        if throttle_str != self._throttle:
            self._throttle = throttle_str
            changed = True

        # Engine load
        load_val = data.get("engine_load")
        load_str = _fmt_number(load_val, 0)
        if load_str != self._engine_load:
            self._engine_load = load_str
            changed = True

        # DTCs
        dtc_count = data.get("dtc_count", 0)
        dtcs = data.get("dtcs", [])
        if dtc_count != self._dtc_count:
            self._dtc_count = dtc_count
            changed = True

        if dtc_count > 0:
            codes = [d.get("code", "?") for d in dtcs[:3]]
            txt = ", ".join(codes)
            if dtc_count > 3:
                txt += f" (+{dtc_count - 3} more)"
            color = "#ef4444"
        else:
            txt = "No active fault codes"
            color = "#22c55e"

        if txt != self._dtc_text:
            self._dtc_text = txt
            self._dtc_color = color
            changed = True

        # MPG
        mpg_val = data.get("mpg")
        mpg_str = _fmt_number(mpg_val, 1)
        if mpg_str != self._mpg:
            self._mpg = mpg_str
            changed = True

        # Oil temp
        oil_val = data.get("oil_temp")
        oil_str = _fmt_number(oil_val, 0)
        if oil_str != self._oil_temp:
            self._oil_temp = oil_str
            changed = True

        # Intake air temp
        iat_val = data.get("intake_air_temp")
        iat_str = _fmt_number(iat_val, 0)
        if iat_str != self._intake_air_temp:
            self._intake_air_temp = iat_str
            changed = True

        if changed:
            self.obdChanged.emit()

    # ── QML Properties ────────────────────────────────────────────
    @Property(str, notify=accentChanged)
    def accent(self):
        return self._accent

    @Property(str, notify=clockChanged)
    def clockText(self):
        return self._clock_text

    @Property(bool, notify=obdChanged)
    def obdConnected(self):
        return self._obd_connected

    @Property(str, notify=obdChanged)
    def statusText(self):
        return self._status_text

    @Property(str, notify=obdChanged)
    def rpm(self):
        return self._rpm

    @Property(float, notify=obdChanged)
    def rpmRatio(self):
        return self._rpm_ratio

    @Property(str, notify=obdChanged)
    def speed(self):
        return self._speed

    @Property(bool, notify=obdChanged)
    def vehicleMoving(self):
        return self._vehicle_moving

    @Property(str, notify=obdChanged)
    def speedUnit(self):
        return self._speed_unit

    @Property(str, notify=obdChanged)
    def coolant(self):
        return self._coolant

    @Property(str, notify=obdChanged)
    def tempUnit(self):
        return self._temp_unit

    @Property(str, notify=obdChanged)
    def batteryVoltage(self):
        return self._battery_voltage

    @Property(str, notify=obdChanged)
    def batteryColor(self):
        return self._battery_color

    @Property(str, notify=obdChanged)
    def throttle(self):
        return self._throttle

    @Property(str, notify=obdChanged)
    def engineLoad(self):
        return self._engine_load

    @Property(int, notify=obdChanged)
    def dtcCount(self):
        return self._dtc_count

    @Property(str, notify=obdChanged)
    def dtcText(self):
        return self._dtc_text

    @Property(str, notify=obdChanged)
    def dtcColor(self):
        return self._dtc_color

    @Property(str, notify=obdChanged)
    def mpg(self):
        return self._mpg

    @Property(str, notify=obdChanged)
    def oilTemp(self):
        return self._oil_temp

    @Property(str, notify=obdChanged)
    def intakeAirTemp(self):
        return self._intake_air_temp


def main():
    # Set up logging when run standalone
    if not logging.root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )

    app = QGuiApplication(sys.argv)
    app.setApplicationName("SignalKit")

    engine = QQmlApplicationEngine()

    # Expose bridge to QML
    bridge = Bridge()
    engine.rootContext().setContextProperty("bridge", bridge)

    # Load QML from file (not compiled resources — easier for dev)
    qml_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "qml")
    qml_path = os.path.join(qml_dir, "Main.qml")

    # Add the QML dir as import path so component files are found
    engine.addImportPath(qml_dir)

    # Expose icons directory as a context property so QML can use file:// paths
    icons_dir = QUrl.fromLocalFile(os.path.join(qml_dir, "icons") + "/")
    engine.rootContext().setContextProperty("iconsPath", icons_dir.toString())

    # Start OBD reader thread if available and not already running
    # (preview_qt.py or main.py may have already started one)
    obd_thread = None
    if _obd_available:
        import threading
        already_running = any(
            t.name == "OBDReader" and t.is_alive()
            for t in threading.enumerate()
        )
        if not already_running:
            logger.info("Starting OBD reader thread")
            obd_thread = obd_reader.OBDReader()
            obd_thread.start()
        else:
            logger.info("OBD reader already running — skipping")
    else:
        print("OBD backend not available — UI will show placeholder data")

    print(f"SignalKit starting (Qt backend: {_BACKEND}, OBD: {'live' if _obd_available else 'demo'})")
    engine.load(QUrl.fromLocalFile(qml_path))

    if not engine.rootObjects():
        print("ERROR: Failed to load QML. Check the console for errors.")
        sys.exit(1)

    exit_code = app.exec()

    # Clean shutdown
    if obd_thread is not None:
        logger.info("Stopping OBD reader")
        obd_thread.stop()
        obd_thread.join(timeout=5)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
