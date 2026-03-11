#!/usr/bin/env python3
"""
preview_qt.py — Run the SignalKit Qt/QML dashboard with the ELM327 emulator.

No hardware required. Run from the repo root:
    pip install ELM327-emulator python-OBD PySide6
    python3 preview_qt.py

The ELM327 emulator creates a virtual serial port that python-OBD
connects to, providing realistic OBD data without a car.

Press the power button in the dock or Ctrl+C to quit.
"""

import sys
import os
import time
import subprocess
import signal
import atexit
import tempfile
import logging

# Point imports at the signalkit/ source directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "signalkit"))

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("preview_qt")

# Silence python-OBD "not supported" spam from the emulator
logging.getLogger("obd").setLevel(logging.ERROR)
logging.getLogger("obd.obd").setLevel(logging.ERROR)

# ── Patch config before anything imports it ──────────────────────────────────
import config
config.FULLSCREEN = False   # Windowed mode on desktop
config.SETUP_COMPLETE = 1   # Skip setup wizard

# ── Start the ELM327 emulator ───────────────────────────────────────────────
_batch_file = tempfile.NamedTemporaryFile(
    prefix="elm327_", suffix=".txt", delete=False, mode="w"
)
_batch_file.close()

print("Starting ELM327 emulator...")
_elm_proc = subprocess.Popen(
    [sys.executable, os.path.join(os.path.dirname(__file__), "emulator_patch.py"),
     "-b", _batch_file.name],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

# Wait for the emulator to write the PTY path to the batch file
_pty_path = None
for _ in range(50):  # up to 5 seconds
    time.sleep(0.1)
    try:
        with open(_batch_file.name, "r") as f:
            line = f.readline().strip()
            if line and os.path.exists(line):
                _pty_path = line
                break
    except Exception:
        pass

if not _pty_path:
    print("ERROR: ELM327 emulator failed to start. Is 'ELM327-emulator' installed?")
    print("  pip install ELM327-emulator")
    _elm_proc.kill()
    sys.exit(1)

print(f"ELM327 emulator running on {_pty_path}")

# Point SignalKit at the emulator's virtual serial port
config.OBD_PORT = _pty_path

# Clean up emulator on exit
def _cleanup_emulator():
    _elm_proc.terminate()
    try:
        _elm_proc.wait(timeout=3)
    except Exception:
        _elm_proc.kill()
    try:
        os.unlink(_batch_file.name)
    except Exception:
        pass

atexit.register(_cleanup_emulator)

# ── Start the web server in a background thread ──────────────────────────────
import threading
import web_server
threading.Thread(target=web_server.run_server, name="WebServer", daemon=True).start()

# ── Run the Qt/QML dashboard (starts OBD reader internally) ─────────────────
import qml_display
qml_display.main()
