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
from datetime import datetime

# ── Qt plugin path fix ──────────────────────────────────────────────
# Must happen at the C level before ANY Qt import touches the plugin loader.
import ctypes, ctypes.util
_libc = ctypes.CDLL(ctypes.util.find_library("c"))

import PySide6 as _pyside6
_qt_plugins = os.path.join(os.path.dirname(_pyside6.__file__), "Qt", "plugins")
_libc.setenv(b"QT_PLUGIN_PATH", _qt_plugins.encode(), ctypes.c_int(1))
os.environ["QT_PLUGIN_PATH"] = _qt_plugins
del _libc, _qt_plugins
# ────────────────────────────────────────────────────────────────────

from PySide6.QtCore import QObject, Property, Signal, QTimer, QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine


class Bridge(QObject):
    """Python↔QML bridge — exposes data as QML properties."""

    accentChanged = Signal()
    clockChanged = Signal()
    obdConnectedChanged = Signal()

    def __init__(self):
        super().__init__()
        self._accent = "#3b82f6"
        self._clock_text = ""
        self._obd_connected = False
        self._update_clock()

        # Clock timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._update_clock)
        self._timer.start(10_000)  # every 10s

    def _update_clock(self):
        now = datetime.now()
        h = now.hour % 12 or 12
        ampm = "PM" if now.hour >= 12 else "AM"
        self._clock_text = f"{h}:{now.minute:02d} {ampm}"
        self.clockChanged.emit()

    @Property(str, notify=accentChanged)
    def accent(self):
        return self._accent

    @Property(str, notify=clockChanged)
    def clockText(self):
        return self._clock_text

    @Property(bool, notify=obdConnectedChanged)
    def obdConnected(self):
        return self._obd_connected


def main():
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

    engine.load(QUrl.fromLocalFile(qml_path))

    if not engine.rootObjects():
        print("ERROR: Failed to load QML. Check the console for errors.")
        sys.exit(1)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
