#!/usr/bin/env python3
"""
preview.py — Run the SignalKit dashboard with the ELM327 emulator.

No hardware required. Run from the repo root:
    pip install ELM327-emulator python-OBD
    python3 preview.py

The ELM327 emulator creates a virtual serial port that python-OBD
connects to, providing realistic OBD data without a car.

Press ESC or close the window to quit.
"""

import sys
import os
import time
import subprocess
import signal
import atexit
import tempfile

# Point imports at the signalkit/ source directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "signalkit"))

# ── Patch config before display imports it ──────────────────────────────────
import config
config.FULLSCREEN = False   # Windowed mode on desktop
config.SETUP_COMPLETE = 1   # Skip setup wizard

# Silence python-OBD "not supported" spam from the emulator
import logging
logging.getLogger("obd").setLevel(logging.ERROR)

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

# ── Start the OBD reader (real polling via emulator) ─────────────────────────
import obd_reader
_reader = obd_reader.OBDReader()
_reader.start()

def _shutdown(sig, frame):
    _reader.stop()
    _cleanup_emulator()
    sys.exit(0)

signal.signal(signal.SIGINT, _shutdown)
signal.signal(signal.SIGTERM, _shutdown)

# ── Run the dashboard ─────────────────────────────────────────────────────────
import display
display.run_display()
