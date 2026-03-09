# =============================================================================
# obd_reader.py - OBD2 Connection and Data Polling
# =============================================================================
# Manages the Bluetooth connection to the Veepeak ELM327 adapter and
# continuously polls vehicle data in a background thread.
#
# Architecture:
#   - OBDReader runs in a background thread started by main.py
#   - All data is stored in a shared `data` dict protected by a Lock
#   - Other modules read from `data` safely via get_data()
#
# Bluetooth setup (done before this runs, by main.py or systemd):
#   sudo rfcomm bind /dev/rfcomm0 <MAC_ADDRESS> 1
#
# OBD2 library: python-OBD (pip install obd)
#   https://python-obd.readthedocs.io/
# =============================================================================

import threading
import time
import logging
import platform
import subprocess

import obd

import config
import trip
from dtc_descriptions import format_dtc_list

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Active OBD connection reference (set by OBDReader, used by dev commands)
# ---------------------------------------------------------------------------
_conn_lock = threading.Lock()
_active_connection = None  # type: obd.OBD | None


def _set_connection(conn):
    """Store the active OBD connection for use by dev commands."""
    global _active_connection
    with _conn_lock:
        _active_connection = conn


def send_raw_command(hex_cmd: str) -> dict:
    """
    Send a raw OBD command (hex string like '010C' or 'ATZ') and return
    the response. Used by the dev console.

    Returns dict with keys: ok, command, response, error
    """
    hex_cmd = hex_cmd.strip().upper()
    if not hex_cmd:
        return {"ok": False, "command": hex_cmd, "response": "", "error": "Empty command"}

    with _conn_lock:
        conn = _active_connection

    if conn is None or not conn.is_connected():
        return {"ok": False, "command": hex_cmd, "response": "", "error": "Not connected to OBD adapter"}

    try:
        cmd = obd.OBDCommand(
            "DEV_RAW",
            "Dev Console Raw",
            hex_cmd.replace(" ", "").encode(),
            0,
            lambda msgs, unit: msgs,
            obd.ECU.ALL,
            True,
        )
        response = conn.query(cmd, force=True)
        if response.is_null():
            return {"ok": True, "command": hex_cmd, "response": "NO DATA", "error": ""}
        raw = str(response.value)
        return {"ok": True, "command": hex_cmd, "response": raw, "error": ""}
    except Exception as e:
        return {"ok": False, "command": hex_cmd, "response": "", "error": str(e)}


# ---------------------------------------------------------------------------
# Shared data store — all vehicle readings are stored here.
# Access via get_data() for thread-safe reads.
# ---------------------------------------------------------------------------
_data_lock = threading.Lock()
_data = {
    # Connection state
    "connected": False,
    "status": "Disconnected",      # Human-readable status string

    # Fast-polled values (~1s interval)
    "rpm": None,                   # Engine RPM (int)
    "speed": None,                 # Vehicle speed in MPH (float)
    "throttle": None,              # Throttle position % (float)
    "engine_load": None,           # Engine load % (float)

    # Slow-polled values (~5s interval)
    "coolant_temp": None,          # Coolant temperature °C (float)
    "battery_voltage": None,       # Battery voltage V (float)
    "intake_air_temp": None,       # Intake air temperature °C (float)
    "short_fuel_trim_1": None,     # Short-term fuel trim Bank 1 % (float)
    "long_fuel_trim_1": None,      # Long-term fuel trim Bank 1 % (float)
    "short_fuel_trim_2": None,     # Short-term fuel trim Bank 2 % (float)
    "long_fuel_trim_2": None,      # Long-term fuel trim Bank 2 % (float)
    "oil_temp": None,              # Oil temperature °C (float, Kia extended PID)

    # Fuel economy
    "maf": None,                   # Mass Air Flow g/s (float)
    "fuel_rate": None,             # Engine fuel rate L/h (float, PID 0x5E if supported)
    "mpg": None,                   # Estimated miles per gallon (float)

    # Diagnostic trouble codes
    "dtcs": [],                    # List of active DTC dicts: [{code, description}]
    "dtc_count": 0,                # Number of active DTCs
    "mil_on": False,               # Malfunction Indicator Lamp (check engine light)

    # Metadata
    "last_update": None,           # Timestamp of last successful update
    "poll_errors": 0,              # Consecutive polling errors (resets on success)
}


def get_data() -> dict:
    """
    Thread-safe snapshot of all current vehicle data.
    Returns a copy so callers can read without holding the lock.
    """
    with _data_lock:
        d = dict(_data)
    d["trip"] = trip.get_trip()
    return d


def _update(key: str, value):
    """Update a single value in the shared data store."""
    with _data_lock:
        _data[key] = value


def _update_many(updates: dict):
    """Update multiple values atomically."""
    with _data_lock:
        _data.update(updates)


# ---------------------------------------------------------------------------
# Bluetooth / RFCOMM Setup
# ---------------------------------------------------------------------------

def bind_rfcomm() -> bool:
    """
    Bind the OBD2 adapter's Bluetooth MAC to /dev/rfcomm0.
    This must be done before obd.OBD() can connect.

    Returns True if successful (or already bound), False on failure.
    """
    mac = config.OBD_MAC
    port = config.OBD_PORT
    channel = config.OBD_BT_CHANNEL

    # Check if already bound
    try:
        result = subprocess.run(
            ["rfcomm", "show", port],
            capture_output=True, text=True, timeout=5
        )
        if mac.upper() in result.stdout.upper():
            logger.info(f"rfcomm already bound: {port} -> {mac}")
            return True
    except Exception:
        pass

    # Attempt to bind
    try:
        logger.info(f"Binding rfcomm: {port} -> {mac} channel {channel}")
        subprocess.run(
            ["rfcomm", "bind", port, mac, str(channel)],
            check=True, timeout=10
        )
        logger.info("rfcomm bind successful")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"rfcomm bind failed: {e}")
        return False
    except FileNotFoundError:
        logger.error("rfcomm not found — is bluez installed? (sudo apt install bluez)")
        return False


def _btctl(*args, timeout=10) -> str:
    """Run a single bluetoothctl command and return combined output."""
    try:
        r = subprocess.run(
            ["bluetoothctl", *args],
            capture_output=True, text=True, timeout=timeout,
        )
        return (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    except FileNotFoundError:
        return "NOT_FOUND"


def pair_bluetooth() -> bool:
    """
    Attempt to pair with the OBD2 adapter if not already paired.
    Uses individual bluetoothctl commands instead of piping stdin
    (which fails to register the agent properly).
    Returns True if pairing succeeds or device is already paired.
    """
    mac = config.OBD_MAC
    logger.info(f"Attempting Bluetooth pair with {mac}")

    # Step 1: Power on
    out = _btctl("power", "on")
    logger.info(f"BT power on: {out}")
    if "NOT_FOUND" in out:
        logger.error("bluetoothctl not found")
        return False
    if "not available" in out.lower():
        logger.error("Bluetooth controller not available")
        return False

    # Step 2: Check if already paired
    info_out = _btctl("info", mac, timeout=5)
    logger.info(f"BT info {mac}: {info_out}")
    if "Paired: yes" in info_out:
        logger.info("Device already paired — trusting and skipping pair step")
        _btctl("trust", mac)
        return True

    # Step 3: Try to pair (use 'yes' to auto-confirm, common OBD PINs are
    # handled by the default NoInputNoOutput agent capability)
    pair_out = _btctl("pair", mac, timeout=20)
    logger.info(f"BT pair: {pair_out}")

    lower = pair_out.lower()
    if "already paired" in lower or "pairing successful" in lower or "successful" in lower:
        logger.info("Bluetooth pairing successful")
        _btctl("trust", mac)
        return True

    if "not available" in lower:
        logger.error("Bluetooth controller not available")
        return False
    if "not found" in lower:
        logger.error(f"Device {mac} not found — is it powered on and in range?")
        return False
    if "failed" in lower or "error" in lower:
        logger.error(f"Bluetooth pairing failed: {pair_out}")
        return False

    # Step 4: Trust the device so it reconnects automatically
    trust_out = _btctl("trust", mac)
    logger.info(f"BT trust: {trust_out}")

    logger.info("Bluetooth pairing completed — device should be ready")
    return True


# ---------------------------------------------------------------------------
# Kia Extended PID (Oil Temperature)
# ---------------------------------------------------------------------------

def _read_kia_oil_temp(connection):
    """
    Attempt to read Kia/Hyundai oil temperature via mode 22 extended PID.

    The Kia Forte stores oil temperature in a proprietary OBD2 service.
    This sends a raw command and parses the response bytes manually.

    Returns temperature in °C, or None if unsupported.
    """
    try:
        # Send raw mode 22 request for the Kia oil temp PID
        cmd = obd.OBDCommand(
            "KIA_OIL_TEMP",
            "Kia Oil Temperature",
            b"2201" + config.KIA_OIL_TEMP_PID.encode(),
            6,
            lambda msgs, unit: msgs,  # raw response — we parse manually
            obd.ECU.ENGINE,
            True
        )
        response = connection.query(cmd, force=True)
        if response.is_null():
            return None

        # Parse raw response bytes
        # Typical response: "62 21 01 XX XX XX XX ..."
        raw = str(response.value)
        parts = raw.strip().split()

        if len(parts) > config.KIA_OIL_TEMP_BYTE:
            byte_val = int(parts[config.KIA_OIL_TEMP_BYTE], 16)
            temp_c = (byte_val * config.KIA_OIL_TEMP_SCALE) + config.KIA_OIL_TEMP_OFFSET
            if -40 <= temp_c <= 200:  # Sanity check
                return round(temp_c, 1)
    except Exception as e:
        logger.debug(f"Kia oil temp read failed (non-critical): {e}")

    return None


# ---------------------------------------------------------------------------
# OBD2 Polling
# ---------------------------------------------------------------------------

def _query_safe(connection, cmd_name: str):
    """
    Query a standard OBD command by name, returning its value or None.
    Suppresses errors so one bad PID doesn't crash the polling loop.
    """
    try:
        cmd = obd.commands[cmd_name]
        response = connection.query(cmd)
        if response.is_null():
            return None
        return response.value
    except Exception as e:
        logger.debug(f"Query failed for {cmd_name}: {e}")
        return None


def _poll_fast(connection, fuel_rate_supported: bool) -> bool:
    """
    Poll fast-changing data: RPM, speed, throttle, engine load, MAF, fuel economy.
    Called every FAST_POLL_INTERVAL seconds.
    Returns whether PID 0x5E (fuel rate) is supported.
    """
    updates = {}

    # RPM (returns pint Quantity in rpm)
    rpm = _query_safe(connection, "RPM")
    updates["rpm"] = int(rpm.magnitude) if rpm is not None else None

    # Speed — python-OBD returns km/h; store both for unit conversion
    speed = _query_safe(connection, "SPEED")
    speed_mph = None
    if speed is not None:
        speed_mph = round(speed.to("mph").magnitude, 1)
    updates["speed"] = speed_mph

    # Throttle position %
    throttle = _query_safe(connection, "THROTTLE_POS")
    updates["throttle"] = round(float(throttle.magnitude), 1) if throttle is not None else None

    # Engine load %
    load = _query_safe(connection, "ENGINE_LOAD")
    updates["engine_load"] = round(float(load.magnitude), 1) if load is not None else None

    # MAF — Mass Air Flow (g/s), needed for MPG calculation
    maf = _query_safe(connection, "MAF")
    maf_gs = None
    if maf is not None:
        maf_gs = round(float(maf.magnitude), 2)
    updates["maf"] = maf_gs

    # Fuel rate (PID 0x5E) — not all cars support this
    fuel_rate_lh = None
    if fuel_rate_supported:
        fr = _query_safe(connection, "FUEL_RATE")
        if fr is not None:
            fuel_rate_lh = round(float(fr.magnitude), 2)
        else:
            fuel_rate_supported = False  # Stop trying if unsupported
        updates["fuel_rate"] = fuel_rate_lh

    # Calculate MPG
    # Method 1: From fuel rate (L/h) + speed if available
    # Method 2: From MAF (g/s) + speed — MPG = (speed_mph * 7.718) / MAF_gs
    # (7.718 = 3600 / (454 * 14.7 * 6.17 / 3785.41) — stoichiometric for gasoline)
    mpg = None
    if speed_mph and speed_mph > 1:
        if fuel_rate_lh and fuel_rate_lh > 0:
            # L/h to MPG: MPG = speed_mph / (fuel_rate_lh * 0.264172)
            gal_per_hour = fuel_rate_lh * 0.264172
            mpg = round(speed_mph / gal_per_hour, 1)
        elif maf_gs and maf_gs > 0:
            mpg = round((speed_mph * 7.718) / maf_gs, 1)
        if mpg is not None:
            mpg = min(mpg, 99.9)  # Cap at 99.9 for display sanity
    updates["mpg"] = mpg

    updates["last_update"] = time.time()
    _update_many(updates)

    # Feed trip computer
    trip.update(speed_mph, mpg, updates.get("rpm"))

    return fuel_rate_supported


def _poll_slow(connection, kia_oil_supported: bool) -> bool:
    """
    Poll slow-changing data: temps, voltage, fuel trim, DTCs.
    Returns whether Kia oil temp is supported (for caching the result).
    Called every SLOW_POLL_INTERVAL seconds.
    """
    updates = {}

    # Coolant temperature (°C)
    coolant = _query_safe(connection, "COOLANT_TEMP")
    if coolant is not None:
        updates["coolant_temp"] = round(float(coolant.magnitude), 1)

    # Battery/control module voltage
    voltage = _query_safe(connection, "CONTROL_MODULE_VOLTAGE")
    if voltage is not None:
        updates["battery_voltage"] = round(float(voltage.magnitude), 2)

    # Intake air temperature (°C)
    iat = _query_safe(connection, "INTAKE_TEMP")
    if iat is not None:
        updates["intake_air_temp"] = round(float(iat.magnitude), 1)

    # Short-term fuel trim Bank 1 (%)
    stft1 = _query_safe(connection, "SHORT_FUEL_TRIM_1")
    if stft1 is not None:
        updates["short_fuel_trim_1"] = round(float(stft1.magnitude), 1)

    # Long-term fuel trim Bank 1 (%)
    ltft1 = _query_safe(connection, "LONG_FUEL_TRIM_1")
    if ltft1 is not None:
        updates["long_fuel_trim_1"] = round(float(ltft1.magnitude), 1)

    # Short-term fuel trim Bank 2 (may not exist on 4-cyl single-bank engines)
    stft2 = _query_safe(connection, "SHORT_FUEL_TRIM_2")
    if stft2 is not None:
        updates["short_fuel_trim_2"] = round(float(stft2.magnitude), 1)

    ltft2 = _query_safe(connection, "LONG_FUEL_TRIM_2")
    if ltft2 is not None:
        updates["long_fuel_trim_2"] = round(float(ltft2.magnitude), 1)

    # Kia extended oil temperature (only try if it worked before or not yet tested)
    if kia_oil_supported:
        oil_temp = _read_kia_oil_temp(connection)
        updates["oil_temp"] = oil_temp
        kia_oil_supported = oil_temp is not None  # Stop trying if it fails

    # Active DTCs — python-OBD returns a list of OBD objects
    try:
        dtc_response = connection.query(obd.commands.GET_DTC)
        if not dtc_response.is_null():
            raw_dtcs = dtc_response.value  # List of (code, description) tuples
            codes = [entry[0] for entry in raw_dtcs if entry and entry[0]]
            if codes:
                logger.info("DTCs found: %s", codes)
            updates["dtcs"] = format_dtc_list(codes)
            updates["dtc_count"] = len(codes)
            updates["mil_on"] = len(codes) > 0
        else:
            updates["dtcs"] = []
            updates["dtc_count"] = 0
            updates["mil_on"] = False
    except Exception as e:
        logger.warning(f"DTC query failed: {e}")

    _update_many(updates)
    return kia_oil_supported


# ---------------------------------------------------------------------------
# Main OBD Reader Thread
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Diagnostics info — populated during connection
# ---------------------------------------------------------------------------
_diag_lock = threading.Lock()
_diag = {
    "adapter_name": None,
    "protocol": None,
    "supported_pids": [],
    "elm_version": None,
    "bt_mac": None,
    "bt_port": None,
    "connection_attempts": 0,
    "last_connect_time": None,
    "fuel_rate_supported": False,
    "kia_oil_supported": False,
}


def get_diagnostics() -> dict:
    """Return connection diagnostic info."""
    with _diag_lock:
        d = dict(_diag)
    d["bt_mac"] = config.OBD_MAC
    d["bt_port"] = config.OBD_PORT
    d["bt_channel"] = config.OBD_BT_CHANNEL
    with _data_lock:
        d["connected"] = _data["connected"]
        d["status"] = _data["status"]
        d["poll_errors"] = _data["poll_errors"]
    return d


class OBDReader(threading.Thread):
    """
    Background thread that manages the OBD2 connection and polls data.

    The thread automatically reconnects if the connection drops (e.g., when
    the car is turned off and back on). Call stop() to shut it down cleanly.
    """

    def __init__(self):
        super().__init__(name="OBDReader", daemon=True)
        self._stop_event = threading.Event()

    def stop(self):
        """Signal the thread to stop on its next iteration."""
        self._stop_event.set()
        logger.info("OBDReader stop requested")

    def run(self):
        """Main thread loop — connects and polls until stop() is called."""
        logger.info("OBDReader thread started")

        while not self._stop_event.is_set():
            try:
                self._connect_and_poll()
            except Exception as e:
                logger.error(f"OBDReader unexpected error: {e}")
                _update_many({"connected": False, "status": f"Error: {e}"})
                # Wait before retrying
                self._stop_event.wait(config.OBD_RECONNECT_DELAY)

        logger.info("OBDReader thread stopped")

    def _connect_and_poll(self):
        """
        Attempt to connect to the OBD2 adapter and start polling.
        Runs the fast/slow poll loop until disconnected or stopped.
        """
        _update_many({"connected": False, "status": "Connecting to OBD2..."})

        # Skip Bluetooth setup on macOS or when using a non-rfcomm port
        # (e.g. ELM327-emulator on a virtual serial port)
        _is_rfcomm = config.OBD_PORT.startswith("/dev/rfcomm")
        _is_linux = platform.system() == "Linux"

        if _is_linux and _is_rfcomm:
            logger.info("Setting up Bluetooth connection...")
            pair_bluetooth()
            time.sleep(2)  # Give Bluetooth time to settle

            if not bind_rfcomm():
                _update("status", "rfcomm bind failed — retrying...")
                self._stop_event.wait(config.OBD_RECONNECT_DELAY)
                return
        else:
            logger.info("Skipping Bluetooth setup (port=%s, platform=%s)",
                        config.OBD_PORT, platform.system())

        # Connect via python-OBD
        logger.info(f"Connecting to OBD2 on {config.OBD_PORT}...")
        _update("status", f"Opening {config.OBD_PORT}...")

        try:
            connection = obd.OBD(
                portstr=config.OBD_PORT,
                baudrate=config.OBD_BAUDRATE,
                timeout=10,
                fast=False,   # Don't skip supported PID checks
            )
        except Exception as e:
            logger.error(f"obd.OBD() connection failed: {e}")
            _update("status", f"Connection failed: {e}")
            self._stop_event.wait(config.OBD_RECONNECT_DELAY)
            return

        if not connection.is_connected():
            logger.warning("OBD connection returned but is not connected")
            _update("status", "OBD not connected — check adapter power")
            connection.close()
            self._stop_event.wait(config.OBD_RECONNECT_DELAY)
            return

        logger.info("OBD2 connected successfully")
        _set_connection(connection)
        _update_many({"connected": True, "status": "Connected", "poll_errors": 0})

        # Populate diagnostics
        with _diag_lock:
            _diag["connection_attempts"] += 1
            _diag["last_connect_time"] = time.time()
            try:
                _diag["protocol"] = str(connection.protocol_name())
            except Exception:
                _diag["protocol"] = "Unknown"
            try:
                _diag["elm_version"] = str(connection.query(obd.commands.ELM_VERSION).value or "Unknown")
            except Exception:
                _diag["elm_version"] = "Unknown"
            try:
                supported = [str(cmd) for cmd in connection.supported_commands]
                _diag["supported_pids"] = sorted(supported)
            except Exception:
                _diag["supported_pids"] = []

        # Track whether optional PIDs are supported
        kia_oil_supported = True
        fuel_rate_supported = True

        # Timing trackers
        last_slow_poll = 0.0
        fast_interval = config.FAST_POLL_INTERVAL
        slow_interval = config.SLOW_POLL_INTERVAL

        # Main polling loop
        while not self._stop_event.is_set():
            loop_start = time.time()

            # Check if the connection is still alive
            if not connection.is_connected():
                logger.warning("OBD connection lost — reconnecting...")
                _update_many({"connected": False, "status": "Connection lost — reconnecting..."})
                break

            try:
                # Always poll fast data
                fuel_rate_supported = _poll_fast(connection, fuel_rate_supported)

                # Poll slow data on its own schedule
                if loop_start - last_slow_poll >= slow_interval:
                    kia_oil_supported = _poll_slow(connection, kia_oil_supported)
                    last_slow_poll = time.time()

                # Reset error counter on success
                with _data_lock:
                    _data["poll_errors"] = 0

            except Exception as e:
                with _data_lock:
                    _data["poll_errors"] += 1
                    errors = _data["poll_errors"]

                logger.warning(f"Poll error #{errors}: {e}")

                if errors >= 5:
                    logger.error("Too many consecutive poll errors — reconnecting")
                    _update_many({"connected": False, "status": "Connection lost — reconnecting..."})
                    break

            # Sleep for the remainder of the fast poll interval
            elapsed = time.time() - loop_start
            sleep_time = max(0, fast_interval - elapsed)
            self._stop_event.wait(sleep_time)

        # Clean up
        _set_connection(None)
        try:
            connection.close()
        except Exception:
            pass

        if not self._stop_event.is_set():
            _update_many({"connected": False, "status": "Reconnecting..."})
            logger.info("Disconnected — will reconnect")
            self._stop_event.wait(config.OBD_RECONNECT_DELAY)
