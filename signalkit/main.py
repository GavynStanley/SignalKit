#!/usr/bin/env python3
# =============================================================================
# main.py - SignalKit Entry Point
# =============================================================================
# Starts all subsystems in the correct order:
#   1. Logging setup
#   2. OBD2 reader (background thread)
#   3. Flask API server (background thread)
#   4. Qt/QML HDMI display (main thread — GUI frameworks must run on main thread)
#
# The Qt event loop blocks until the window is closed,
# then the script shuts down cleanly.
#
# Run: python3 main.py
# Auto-run on boot: see signalkit.service
# =============================================================================

import sys
import time
import signal
import logging
import threading

# ---------------------------------------------------------------------------
# Logging — set up before importing other modules so their loggers work
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("main")

# Silence python-OBD's per-poll "not supported" warnings — we handle
# unsupported PIDs gracefully in obd_reader.py already.
logging.getLogger("obd.obd").setLevel(logging.ERROR)

# ---------------------------------------------------------------------------
# Import project modules (after logging is configured)
# ---------------------------------------------------------------------------

import os
import subprocess

import config
import obd_reader
import web_server
import qml_display
import bt_pan


# ---------------------------------------------------------------------------
# Shutdown coordination
# ---------------------------------------------------------------------------

_shutdown_event = threading.Event()


def _handle_signal(signum, frame):
    """Gracefully handle SIGTERM/SIGINT (e.g., systemd stop, Ctrl+C)."""
    logger.info(f"Received signal {signum} — shutting down")
    _shutdown_event.set()


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def start_obd_reader() -> obd_reader.OBDReader:
    """Start the OBD2 polling thread."""
    logger.info("Starting OBD2 reader thread")
    reader = obd_reader.OBDReader()
    reader.start()
    return reader


def start_web_server() -> threading.Thread:
    """Start the Flask API server in a background daemon thread."""
    logger.info(f"Starting API server on port {config.WEB_PORT}")
    thread = threading.Thread(
        target=web_server.run_server,
        name="WebServer",
        daemon=True
    )
    thread.start()
    return thread


def _check_ota_pending():
    """If an OTA update was staged before reboot, apply it now.

    The flow is:
      1. User hits Update on web UI while overlayfs is active
      2. web_server disables overlayfs and writes .ota-pending flag
      3. Pi reboots (now running without overlayfs — writes persist)
      4. This function runs on boot, sees the flag, does git pull
      5. Re-enables overlayfs and reboots one final time
    """
    app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    flag = os.path.join(app_dir, ".ota-pending")
    if not os.path.exists(flag):
        return

    logger.info("=" * 60)
    logger.info("OTA UPDATE PENDING — applying now")
    logger.info("=" * 60)

    try:
        os.remove(flag)
    except OSError:
        pass

    # Pull latest code
    try:
        r = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=app_dir, capture_output=True, text=True, timeout=60,
        )
        if r.returncode == 0:
            logger.info(f"git pull succeeded: {r.stdout.strip()}")
        else:
            logger.error(f"git pull failed: {r.stderr.strip()}")
    except Exception as e:
        logger.error(f"git pull error: {e}")

    # Re-enable overlayfs
    try:
        subprocess.run(
            ["sudo", "raspi-config", "nonint", "enable_overlayfs"],
            capture_output=True, text=True, timeout=15,
        )
        logger.info("Overlayfs re-enabled")
    except Exception as e:
        logger.error(f"Failed to re-enable overlayfs: {e}")

    # Reboot to activate overlayfs with the updated code
    logger.info("Rebooting to finalize update...")
    time.sleep(2)
    os.system("sudo reboot")
    sys.exit(0)


def main():
    _check_ota_pending()

    logger.info("=" * 60)
    logger.info("SignalKit Dashboard Starting")
    logger.info(f"  Screen:     {config.SCREEN_WIDTH}x{config.SCREEN_HEIGHT}")
    logger.info(f"  OBD2 MAC:   {config.OBD_MAC}")
    logger.info(f"  API server: http://{config.HOTSPOT_IP}:{config.WEB_PORT}")
    logger.info("=" * 60)

    # Validate MAC address — alert user if it's still the placeholder
    if config.OBD_MAC == "AA:BB:CC:DD:EE:FF":
        logger.warning("=" * 60)
        logger.warning("OBD_MAC in config.py is still the placeholder value!")
        logger.warning("Update it with your Veepeak adapter's actual MAC address.")
        logger.warning("Find it by running:  hcitool scan")
        logger.warning("OBD2 connection will be attempted but will likely fail.")
        logger.warning("=" * 60)
        time.sleep(3)

    # Start background services
    obd_thread = start_obd_reader()
    web_thread = start_web_server()

    # Start Bluetooth PAN manager if a phone is configured
    pan_manager = None
    if config.PHONE_BT_MAC and config.PHONE_BT_AUTO:
        logger.info(f"Starting BT PAN manager for phone {config.PHONE_BT_MAC}")
        pan_manager = bt_pan.BtPanManager(config.PHONE_BT_MAC)
        pan_manager.start()

    # Brief startup pause — let OBD thread begin its connection attempt
    # and let the API server bind its port before the display renders
    time.sleep(1)

    # Run the Qt/QML display on the main thread
    # This blocks until the window is closed
    logger.info("Starting Qt/QML display (main thread)")
    try:
        qml_display.main()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt received")
    except Exception as e:
        logger.error(f"Display error: {e}", exc_info=True)

    # --- Shutdown ---
    logger.info("Display exited — shutting down")
    _shutdown_event.set()

    # Stop the BT PAN manager
    if pan_manager:
        pan_manager.stop()
        logger.info("BT PAN manager stopped")

    # Stop the OBD reader cleanly
    obd_thread.stop()
    obd_thread.join(timeout=5)
    logger.info("OBD reader stopped")

    # Web thread is a daemon — it exits automatically
    logger.info("SignalKit shutdown complete")
    sys.exit(0)


if __name__ == "__main__":
    main()
