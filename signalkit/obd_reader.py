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

import os
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

    Uses the ELM327 interface directly to avoid python-OBD's OBDCommand
    parsing, which can crash on raw/AT commands.

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
        # Access the ELM327 interface directly for raw serial communication.
        # python-OBD's query() doesn't handle AT commands or raw mode well,
        # so we use the internal __send method via name mangling.
        elm = conn.interface
        if elm is None:
            return {"ok": False, "command": hex_cmd, "response": "", "error": "ELM327 interface not available"}

        # Use ELM327's internal __send which returns raw response lines
        # Name-mangled as _ELM327__send
        raw_lines = elm._ELM327__send(hex_cmd.encode("ascii"))

        if not raw_lines:
            return {"ok": True, "command": hex_cmd, "response": "NO DATA", "error": ""}

        # raw_lines is a list of bytes/strings — join them
        result_lines = []
        for line in raw_lines:
            s = line.decode("ascii", errors="replace") if isinstance(line, bytes) else str(line)
            s = s.strip()
            if s and s != ">":
                result_lines.append(s)

        response_text = "\n".join(result_lines) if result_lines else "NO DATA"
        return {"ok": True, "command": hex_cmd, "response": response_text, "error": ""}
    except OSError as e:
        # Bad file descriptor / serial port closed — connection dropped
        logger.error(f"Dev console command failed (connection lost): {e}")
        _set_connection(None)
        return {"ok": False, "command": hex_cmd, "response": "",
                "error": "Connection lost — OBD adapter disconnected"}
    except Exception as e:
        logger.error(f"Dev console command failed: {e}")
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
    Uses lock timeouts to prevent GUI freezes if the OBD thread is stuck.
    """
    acquired = _data_lock.acquire(timeout=0.5)
    if not acquired:
        logger.warning("get_data(): data lock timeout — returning stale snapshot")
        d = dict(_data)  # best-effort unsynchronized copy
    else:
        try:
            d = dict(_data)
        finally:
            _data_lock.release()
    d["trip"] = trip.get_trip()
    acquired = _diag_lock.acquire(timeout=0.5)
    if not acquired:
        d["vin"] = None
        d["vehicle"] = None
    else:
        try:
            d["vin"] = _diag.get("vin")
            d["vehicle"] = _diag.get("vehicle")
        finally:
            _diag_lock.release()
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


def _run_cmd(cmd, timeout=10) -> str:
    """Run a command and return combined output."""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
        )
        return (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return "TIMEOUT"
    except FileNotFoundError:
        return "NOT_FOUND"


def pair_bluetooth() -> bool:
    """
    Attempt to pair with the OBD2 adapter if not already paired.
    OBD adapters use classic Bluetooth (SPP), so we use bluetoothctl
    with individual commands. For PIN-based pairing, common OBD PINs
    (1234, 0000) are tried automatically.
    Returns True if pairing succeeds or device is already paired.
    """
    mac = config.OBD_MAC
    logger.info(f"Attempting Bluetooth pair with {mac}")

    # Step 1: Power on
    out = _run_cmd(["bluetoothctl", "power", "on"])
    logger.info(f"BT power on: {out}")
    if "NOT_FOUND" in out:
        logger.error("bluetoothctl not found")
        return False
    if "not available" in out.lower():
        logger.error("Bluetooth controller not available")
        return False

    # Step 2: Check if already paired
    info_out = _run_cmd(["bluetoothctl", "info", mac], timeout=5)
    logger.info(f"BT info {mac}: {info_out}")
    if "Paired: yes" in info_out:
        logger.info("Device already paired — trusting and skipping pair step")
        _run_cmd(["bluetoothctl", "trust", mac])
        return True

    # Step 3: Try to pair using bluetoothctl with PIN agent
    # First, try pairing with bluetoothctl (works if no PIN required)
    pair_out = _run_cmd(["bluetoothctl", "pair", mac], timeout=20)
    logger.info(f"BT pair: {pair_out}")

    lower = pair_out.lower()
    if "already paired" in lower or "pairing successful" in lower or "successful" in lower:
        logger.info("Bluetooth pairing successful")
        _run_cmd(["bluetoothctl", "trust", mac])
        return True

    # Step 4: If bluetoothctl pair failed, try with common OBD PINs
    # using a script that auto-answers the PIN prompt
    if "failed" in lower or "error" in lower:
        logger.info("Simple pair failed — trying with PIN 1234...")
        pin_script = f"""#!/usr/bin/expect -f
set timeout 15
spawn bluetoothctl
expect "#"
send "agent on\\r"
expect "#"
send "default-agent\\r"
expect "#"
send "pair {mac}\\r"
expect {{
    "PIN code" {{ send "1234\\r"; exp_continue }}
    "Passkey" {{ send "1234\\r"; exp_continue }}
    "Confirm passkey" {{ send "yes\\r"; exp_continue }}
    "successful" {{ }}
    "already paired" {{ }}
    "Failed" {{ }}
    timeout {{ }}
}}
sleep 1
send "trust {mac}\\r"
expect "#"
send "quit\\r"
expect eof
"""
        try:
            import tempfile
            with tempfile.NamedTemporaryFile(mode='w', suffix='.exp', delete=False) as f:
                f.write(pin_script)
                script_path = f.name
            os.chmod(script_path, 0o755)
            result = _run_cmd(["expect", script_path], timeout=25)
            logger.info(f"Expect pair result: {result}")
            os.unlink(script_path)

            if "successful" in result.lower() or "already paired" in result.lower():
                logger.info("Bluetooth pairing with PIN successful")
                return True
        except Exception as e:
            logger.warning(f"Expect-based pairing failed: {e}")

        # Fallback: try direct bluetoothctl trust (device might pair on rfcomm connect)
        logger.info("PIN pairing failed — trusting device for rfcomm fallback")
        _run_cmd(["bluetoothctl", "trust", mac])

    if "not available" in lower:
        logger.error("Bluetooth controller not available")
        return False
    if "not found" in lower:
        logger.error(f"Device {mac} not found — is it powered on and in range?")
        return False

    # Trust the device regardless — rfcomm bind may still work
    _run_cmd(["bluetoothctl", "trust", mac])
    logger.info("Bluetooth setup completed — attempting rfcomm bind")
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
        response = _query_with_timeout(connection, cmd, force=True)
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

_unsupported_pids: set = set()

# Watchdog: tracks when the last successful OBD query completed.
# If this falls too far behind, the polling loop is stuck.
_QUERY_TIMEOUT = 5  # seconds — max time to wait for a single OBD query
_last_successful_query = 0.0  # timestamp of last successful query


def _query_with_timeout(connection, cmd, force=False, timeout=_QUERY_TIMEOUT):
    """
    Wrapper around connection.query() that enforces a per-query timeout.
    Returns the OBDResponse, or a null response on timeout.
    """
    result = [None]
    exc = [None]

    def _do_query():
        try:
            result[0] = connection.query(cmd, force=force)
        except Exception as e:
            exc[0] = e

    t = threading.Thread(target=_do_query, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        # Query is hung — don't wait, return null
        logger.warning(f"OBD query timeout ({timeout}s) for {cmd.name}")
        return obd.OBDResponse()  # null response

    if exc[0] is not None:
        raise exc[0]

    global _last_successful_query
    _last_successful_query = time.time()
    return result[0]


def _query_safe(connection, cmd_name: str):
    """
    Query a standard OBD command by name, returning its value or None.
    Skips PIDs that the vehicle has reported as unsupported.
    Suppresses errors so one bad PID doesn't crash the polling loop.
    """
    if cmd_name in _unsupported_pids:
        return None
    try:
        cmd = obd.commands[cmd_name]
        if not connection.supports(cmd):
            _unsupported_pids.add(cmd_name)
            logger.info(f"PID {cmd_name} not supported by vehicle — skipping")
            return None
        response = _query_with_timeout(connection, cmd)
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
        dtc_response = _query_with_timeout(connection, obd.commands.GET_DTC)
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
# ---------------------------------------------------------------------------
# VIN Decoder
# ---------------------------------------------------------------------------

from vin_database import decode_vin  # noqa: E402 — 380+ WMI codes


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
    "vin": None,
    "vehicle": None,
}

# Full PID snapshot taken on connect — stores name, value, unit for every supported PID
_pid_snapshot_lock = threading.Lock()
_pid_snapshot = {"scanned_at": None, "pids": [], "by_service": {}, "total": 0}


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


def get_pid_snapshot() -> dict:
    """Return the last PID snapshot taken on connect."""
    with _pid_snapshot_lock:
        return dict(_pid_snapshot)


def _parse_response_value(val):
    """Extract a JSON-friendly value from an OBD response value."""
    if hasattr(val, 'magnitude'):
        return {
            "value": round(float(val.magnitude), 4),
            "unit": str(val.units),
            "raw": str(val),
        }
    # OBDResponse.Status objects (PID 01, PID 41) — extract structured fields
    elif hasattr(val, 'MIL') and hasattr(val, 'DTC_count'):
        status = {
            "MIL": val.MIL,
            "DTC_count": val.DTC_count,
            "ignition_type": str(val.ignition_type) if hasattr(val, 'ignition_type') else None,
        }
        # Extract readiness monitor flags if available
        for attr in ("misfire", "fuel_system", "component", "catalyst",
                     "heated_catalyst", "evaporative_system", "secondary_air_system",
                     "ac_refrigerant", "oxygen_sensor", "oxygen_sensor_heater",
                     "egr_system"):
            test = getattr(val, attr, None)
            if test is not None:
                status[attr] = {
                    "available": getattr(test, 'available', None),
                    "complete": getattr(test, 'complete', None),
                }
        return {
            "value": status,
            "unit": None,
            "raw": str(status),
        }
    # bytearray/bytes — decode to string (VIN, calibration IDs, etc.)
    elif isinstance(val, (bytearray, bytes)):
        decoded = val.decode("ascii", errors="replace").strip("\x00").strip()
        return {
            "value": decoded,
            "unit": None,
            "raw": decoded,
        }
    # Monitor objects (Service 06 on-board monitoring test results)
    elif hasattr(val, 'tests') or (hasattr(val, '__iter__') and hasattr(val, 'count')):
        # Check if it's a Monitor by looking for MonitorTest items
        tests = []
        raw_parts = []
        try:
            for test in val:
                t = {
                    "name": getattr(test, 'name', 'Unknown'),
                    "desc": getattr(test, 'desc', 'Unknown'),
                    "tid": getattr(test, 'tid', None),
                }
                test_val = getattr(test, 'value', None)
                if test_val is not None and hasattr(test_val, 'magnitude'):
                    t["value"] = round(float(test_val.magnitude), 6)
                    t["unit"] = str(test_val.units)
                    passed = True
                    mn = getattr(test, 'min', None)
                    mx = getattr(test, 'max', None)
                    if mn is not None and hasattr(mn, 'magnitude'):
                        t["min"] = round(float(mn.magnitude), 6)
                        if test_val.magnitude < mn.magnitude:
                            passed = False
                    if mx is not None and hasattr(mx, 'magnitude'):
                        t["max"] = round(float(mx.magnitude), 6)
                        if test_val.magnitude > mx.magnitude:
                            passed = False
                    t["passed"] = passed
                else:
                    t["value"] = str(test_val) if test_val is not None else None
                    t["unit"] = None
                    t["passed"] = None
                tests.append(t)
                desc = t.get("desc", "Unknown")
                val_str = f"{t['value']} {t.get('unit', '')}" if t.get('unit') else str(t['value'])
                status = "[PASSED]" if t.get("passed") else "[FAILED]" if t.get("passed") is False else ""
                raw_parts.append(f"{desc} : {val_str} {status}".strip())
        except TypeError:
            # Not iterable — fall through to generic handler
            return {
                "value": str(val),
                "unit": None,
                "raw": str(val),
            }
        return {
            "value": "\n".join(raw_parts),
            "unit": None,
            "raw": "\n".join(raw_parts),
        }
    elif isinstance(val, (list, tuple)):
        return {
            "value": [str(v) for v in val],
            "unit": None,
            "raw": str(val),
        }
    else:
        return {
            "value": str(val),
            "unit": None,
            "raw": str(val),
        }


def _make_pid_result(service, cmd, value=None, unit=None, raw="NO DATA", parsed=None):
    """Build a standardised PID scan result dict.

    Args:
        service: OBD service number string (e.g. "01", "06").
        cmd:     The python-OBD command object.
        value:   Parsed value (or None for no-data / error).
        unit:    Unit string (or None).
        raw:     Raw response string.
        parsed:  If provided, a dict from _parse_response_value() whose keys
                 override value/unit/raw.
    """
    entry = {
        "service": service,
        "pid": cmd.name if hasattr(cmd, 'name') else str(cmd),
        "desc": cmd.desc if hasattr(cmd, 'desc') else "",
        "value": value,
        "unit": unit,
        "raw": raw,
    }
    if parsed:
        entry.update(parsed)
    return entry


def _scan_standard_pids(connection):
    """Scan all supported standard PIDs (Services 01, 02, 03, 07, 09).

    Service 06 monitors are skipped here — their multi-frame ISO-TP responses
    can hang the ELM327 emulator.  They are scanned separately via
    _scan_mode06_monitors() with individual timeout protection.
    """
    results = []

    for cmd in sorted(connection.supported_commands, key=lambda c: str(c)):
        cmd_name = cmd.name if hasattr(cmd, 'name') else str(cmd)
        # Skip bitmask/housekeeping commands
        if any(skip in cmd_name for skip in ["PIDS_", "ELM_", "MIDS_"]):
            continue
        if "Supported" in (cmd.desc if hasattr(cmd, 'desc') else ""):
            continue

        # Determine service number from the command bytes
        service = "01"
        if hasattr(cmd, 'command') and cmd.command:
            raw = cmd.command
            if isinstance(raw, bytes):
                service = raw[:2].decode("ascii", errors="replace")
            else:
                service = str(raw)[:2]

        # Skip Service 06 monitors — handled separately
        if service == "06":
            continue

        try:
            response = _query_with_timeout(connection, cmd, force=True)
            if response.is_null():
                results.append(_make_pid_result(service, cmd))
            else:
                results.append(_make_pid_result(
                    service, cmd, parsed=_parse_response_value(response.value)))
        except Exception as e:
            results.append(_make_pid_result(service, cmd, raw=f"ERROR: {e}"))

    return results


def _scan_mode06_monitors(connection):
    """Scan Service 06 on-board monitoring test results.

    Each monitor query gets a short timeout to prevent hangs from
    multi-frame ISO-TP responses that the emulator may not handle properly.
    """
    results = []
    mode06_cmds = [
        cmd for cmd in connection.supported_commands
        if hasattr(cmd, 'command') and cmd.command
        and cmd.command[:2] == b'06'
        and not (cmd.name.startswith("MIDS_") or "Supported" in (cmd.desc or ""))
    ]

    if not mode06_cmds:
        return results

    logger.info(f"Scanning {len(mode06_cmds)} Service 06 monitors...")

    for cmd in sorted(mode06_cmds, key=lambda c: c.name):
        try:
            response = _query_with_timeout(connection, cmd, force=True, timeout=3)
            if response.is_null():
                results.append(_make_pid_result("06", cmd))
            else:
                results.append(_make_pid_result(
                    "06", cmd, parsed=_parse_response_value(response.value)))
        except Exception as e:
            logger.debug(f"Mode 06 monitor {cmd.name} failed: {e}")
            results.append(_make_pid_result("06", cmd, raw=f"ERROR: {e}"))

    logger.info(f"Service 06 scan complete: {len(results)} monitors")
    return results


# Known Kia/Hyundai Mode 22 extended PIDs to probe
_KIA_MODE22_PIDS = {
    "2101": "Engine Data Block 1",
    "2102": "Engine Data Block 2",
    "2103": "Engine Data Block 3",
    "2104": "Engine Data Block 4",
    "2105": "Engine Data Block 5",
    "2106": "Engine Data Block 6",
    "2107": "Engine Data Block 7",
    "2108": "Engine Data Block 8",
    "2110": "Transmission Data",
    "2111": "Transmission Data 2",
    "2112": "Braking System Data",
    "2150": "Battery Management",
    "2180": "Air Conditioning Data",
    "2191": "ECU Identification",
    "F190": "VIN (UDS)",
    "F191": "ECU Hardware Version",
    "F193": "ECU Software Version",
    "F195": "ECU Serial Number",
}

# CAN headers for Kia modules — only probe modules likely to support Mode 22.
# Body modules (BCM, SRS, Cluster, Steering, Climate) rarely support UDS 0x22
# and cause long timeouts when they don't respond, freezing the scan.
_KIA_MODULES = {
    "7E0": "Engine (ECM)",
    "7E2": "Transmission (TCM)",
}


def _decode_kia_mode22(pid_hex, raw_hex_str):
    """
    Decode Kia/Hyundai Mode 22 response bytes into human-readable fields.
    Returns a list of dicts: [{"name": ..., "value": ..., "unit": ...}, ...]
    or None if no decoder is available.
    """
    # Strip CAN headers and response prefix (62 XX XX)
    # Raw might look like "7E8 10 1C 62 21 01 A3 00" or multi-frame
    # Extract just the data bytes after the 62 XX XX service/pid echo
    hex_clean = raw_hex_str.replace(" ", "").upper()

    # Find the response marker: 62 + PID echo (e.g., 62 2101)
    marker = "62" + pid_hex.upper()
    idx = hex_clean.find(marker)
    if idx < 0:
        return None
    data_hex = hex_clean[idx + len(marker):]

    # Convert to byte array
    try:
        data = [int(data_hex[i:i+2], 16) for i in range(0, len(data_hex), 2)]
    except (ValueError, IndexError):
        return None

    if not data:
        return None

    fields = []

    # Engine ECM data blocks (header 7E0)
    if pid_hex == "2101" and len(data) >= 20:
        fields = [
            {"name": "Coolant Temp", "value": f"{data[0] - 40}", "unit": "°C"},
            {"name": "Intake Air Temp", "value": f"{data[1] - 40}", "unit": "°C"},
            {"name": "RPM", "value": f"{(data[2] * 256 + data[3]) / 4:.0f}", "unit": "rpm"},
            {"name": "Vehicle Speed", "value": f"{data[4]}", "unit": "km/h"},
            {"name": "Throttle Position", "value": f"{data[5] * 100 / 255:.1f}", "unit": "%"},
            {"name": "Engine Load", "value": f"{data[6] * 100 / 255:.1f}", "unit": "%"},
            {"name": "MAF Rate", "value": f"{(data[7] * 256 + data[8]) / 100:.2f}", "unit": "g/s"},
            {"name": "Battery Voltage", "value": f"{(data[9] * 256 + data[10]) / 1000:.1f}", "unit": "V"},
        ]
        if len(data) >= 24:
            fields.extend([
                {"name": "Fuel Pressure", "value": f"{data[11] * 3}", "unit": "kPa"},
                {"name": "Timing Advance", "value": f"{data[12] / 2 - 64:.1f}", "unit": "°"},
                {"name": "Injector Duty", "value": f"{data[13] * 100 / 255:.1f}", "unit": "%"},
            ])

    elif pid_hex == "2102" and len(data) >= 10:
        fields = [
            {"name": "Oil Temp", "value": f"{data[0] - 40}", "unit": "°C"},
            {"name": "Fuel Level", "value": f"{data[1] * 100 / 255:.1f}", "unit": "%"},
            {"name": "Ambient Temp", "value": f"{data[2] - 40}", "unit": "°C"},
            {"name": "Catalyst Temp", "value": f"{(data[3] * 256 + data[4]) / 10 - 40:.1f}", "unit": "°C"},
        ]
        if len(data) >= 12:
            fields.extend([
                {"name": "Short Fuel Trim", "value": f"{(data[5] - 128) * 100 / 128:.1f}", "unit": "%"},
                {"name": "Long Fuel Trim", "value": f"{(data[6] - 128) * 100 / 128:.1f}", "unit": "%"},
                {"name": "O2 Sensor Voltage", "value": f"{data[7] * 0.005:.3f}", "unit": "V"},
            ])

    elif pid_hex == "2103" and len(data) >= 8:
        fields = [
            {"name": "Ignition Timing Cyl 1", "value": f"{data[0] / 2 - 64:.1f}", "unit": "°"},
            {"name": "Ignition Timing Cyl 2", "value": f"{data[1] / 2 - 64:.1f}", "unit": "°"},
            {"name": "Ignition Timing Cyl 3", "value": f"{data[2] / 2 - 64:.1f}", "unit": "°"},
            {"name": "Ignition Timing Cyl 4", "value": f"{data[3] / 2 - 64:.1f}", "unit": "°"},
            {"name": "Knock Retard", "value": f"{data[4] * 0.5:.1f}", "unit": "°"},
        ]

    elif pid_hex == "2105" and len(data) >= 6:
        fields = [
            {"name": "Coolant Temp", "value": f"{data[0] - 40}", "unit": "°C"},
            {"name": "Intake Temp", "value": f"{data[1] - 40}", "unit": "°C"},
            {"name": "Fuel Pressure", "value": f"{data[2] * 3}", "unit": "kPa"},
            {"name": "Barometric Pressure", "value": f"{data[3]}", "unit": "kPa"},
        ]

    # Transmission data
    elif pid_hex == "2110" and len(data) >= 6:
        gear_map = {0: "P", 1: "R", 2: "N", 3: "D", 4: "1st", 5: "2nd",
                    6: "3rd", 7: "4th", 8: "5th", 9: "6th", 10: "7th"}
        fields = [
            {"name": "Current Gear", "value": gear_map.get(data[0], f"Unknown ({data[0]})"), "unit": ""},
            {"name": "Trans Fluid Temp", "value": f"{data[1] - 40}", "unit": "°C"},
            {"name": "Torque Converter Slip", "value": f"{(data[2] * 256 + data[3]) - 32768}", "unit": "rpm"},
            {"name": "Input Shaft Speed", "value": f"{data[4] * 256 + data[5]}", "unit": "rpm"},
        ]

    # ABS / ESC data
    elif pid_hex == "2112" and len(data) >= 8:
        fields = [
            {"name": "Wheel Speed FL", "value": f"{(data[0] * 256 + data[1]) / 100:.1f}", "unit": "km/h"},
            {"name": "Wheel Speed FR", "value": f"{(data[2] * 256 + data[3]) / 100:.1f}", "unit": "km/h"},
            {"name": "Wheel Speed RL", "value": f"{(data[4] * 256 + data[5]) / 100:.1f}", "unit": "km/h"},
            {"name": "Wheel Speed RR", "value": f"{(data[6] * 256 + data[7]) / 100:.1f}", "unit": "km/h"},
        ]

    # ECU identification strings (F1xx PIDs)
    elif pid_hex.startswith("F1") and data:
        try:
            text = bytes(data).decode("ascii", errors="replace").strip().rstrip("\x00")
            fields = [{"name": "Value", "value": text, "unit": ""}]
        except Exception:
            pass

    return fields if fields else None


def _elm_send_raw(elm, cmd_str, timeout=3):
    """Send a raw command via ELM327 and return joined response string.

    Uses a timeout thread to prevent indefinite hangs — some ECU modules
    don't respond at all, and elm.__send() blocks until the ELM327 prompt.
    """
    result = [None]

    def _do_send():
        try:
            result[0] = elm._ELM327__send(cmd_str.encode("ascii"))
        except Exception as e:
            logger.debug(f"ELM raw send '{cmd_str}' error: {e}")

    t = threading.Thread(target=_do_send, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        logger.debug(f"ELM raw send '{cmd_str}' timed out after {timeout}s")
        return ""

    if not result[0]:
        return ""
    return " ".join(
        l.decode("ascii", errors="replace") if isinstance(l, bytes) else str(l)
        for l in result[0]
    ).strip()


def _scan_mode22_pids(connection):
    """
    Probe Kia/Hyundai Mode 22 (UDS ReadDataByIdentifier) extended PIDs.

    The 2021+ Kia Forte requires:
      1. Set CAN header to target the specific ECU module
      2. Send '10 03' to enter extendedDiagnosticSession (UDS service 0x10)
      3. Send '22 XXXX' to read each DID (UDS service 0x22)

    Without the diagnostic session, the ECU returns 7F 22 11
    (serviceNotSupported) for all DIDs.
    """
    results = []
    elm = connection.interface
    if elm is None:
        logger.warning("Cannot scan Mode 22 — no ELM327 interface")
        return results

    try:
        # Set a short ELM327 timeout for probing — don't wait long for
        # non-responsive modules. AT ST 32 = 50 × 4ms = 200ms per command.
        _elm_send_raw(elm, "ATST 32", timeout=2)

        for header, module_name in _KIA_MODULES.items():
            # Set CAN header to target this module
            resp = _elm_send_raw(elm, f"ATSH {header}", timeout=2)
            if "ERROR" in resp or "?" in resp:
                logger.debug(f"Failed to set header {header}: {resp}")
                continue

            # Enter extended diagnostic session (UDS 10 03)
            # This unlocks manufacturer-specific DIDs on many Kia/Hyundai ECUs
            session_resp = _elm_send_raw(elm, "1003", timeout=3)
            if "7F" in session_resp:
                logger.debug(f"Module {header} ({module_name}): extended session rejected — {session_resp}")
                # Still try default session reads — some modules respond without it
            elif not session_resp or "NO DATA" in session_resp:
                logger.debug(f"Module {header} ({module_name}): no response to session request — skipping")
                continue
            else:
                logger.debug(f"Module {header} ({module_name}): extended session opened")

            module_found_pids = 0

            for did_hex, pid_desc in _KIA_MODE22_PIDS.items():
                try:
                    # Send as UDS Service 22 + DID (e.g., "22F190" not just "F190")
                    cmd = f"22{did_hex}"
                    resp = _elm_send_raw(elm, cmd, timeout=3)

                    if not resp:
                        continue

                    # Skip error/empty/negative responses
                    # 7F = UDS negative response (e.g. "7E8 03 7F 22 31" = requestOutOfRange)
                    if "NO DATA" in resp or "ERROR" in resp or "?" in resp or "7F" in resp:
                        continue

                    # Validate the response is actually a Service 22 positive response (62 XX XX)
                    # The emulator may echo back Mode 21 responses (61 XX) if it interprets
                    # "222103" as service 21 — filter those out
                    if "62" not in resp:
                        logger.debug(f"Mode 22 {header}/{did_hex}: no '62' positive response prefix — {resp}")
                        continue

                    # Try to decode the raw response
                    decoded_fields = _decode_kia_mode22(did_hex, resp)

                    results.append({
                        "service": "22",
                        "pid": did_hex,
                        "desc": f"{module_name} — {pid_desc}",
                        "module": module_name,
                        "header": header,
                        "value": decoded_fields if decoded_fields else resp,
                        "decoded": decoded_fields is not None,
                        "unit": None,
                        "raw": resp,
                    })
                    module_found_pids += 1

                except Exception as e:
                    logger.debug(f"Mode 22 probe {header}/{did_hex} failed: {e}")

            if module_found_pids > 0:
                logger.info(f"Module {header} ({module_name}): {module_found_pids} extended PIDs found")

            # Close diagnostic session — send '10 01' (return to default session)
            _elm_send_raw(elm, "1001", timeout=2)

    except Exception as e:
        logger.warning(f"Mode 22 scan error: {e}")
    finally:
        # Always restore ELM327 state so standard polling works after scan
        try:
            _elm_send_raw(elm, "1001", timeout=2)   # Close any open diagnostic session
            _elm_send_raw(elm, "ATSH 7E0", timeout=2)  # Restore engine ECU header
            _elm_send_raw(elm, "ATST FF", timeout=2)    # Restore default ELM timeout
            _elm_send_raw(elm, "ATZ", timeout=3)         # Full ELM reset as safety net
        except Exception:
            pass

    return results


def _scan_all_pids(connection):
    """
    Full PID scan across all services:
    - Services 01-09 via python-OBD (standard PIDs)
    - Service 22 via raw ELM327 (Kia/Hyundai extended PIDs)
    """
    logger.info("Starting full PID scan (all services)...")
    _update("status", "Scanning PIDs...")

    # Standard PIDs (Services 01, 02, 03, 07, 09)
    standard = _scan_standard_pids(connection)
    logger.info(f"Standard scan: {len(standard)} PIDs")

    # Service 06 monitors (separate to avoid multi-frame hangs)
    monitors = _scan_mode06_monitors(connection)
    logger.info(f"Service 06 scan: {len(monitors)} monitors")

    all_pids = standard + monitors

    # Group by service
    by_service = {}
    for pid in all_pids:
        svc = pid.get("service", "??")
        if svc not in by_service:
            by_service[svc] = []
        by_service[svc].append(pid)

    with _pid_snapshot_lock:
        _pid_snapshot["scanned_at"] = time.time()
        _pid_snapshot["pids"] = all_pids
        _pid_snapshot["by_service"] = by_service
        _pid_snapshot["total"] = len(all_pids)

    _update("status", "Connected")
    logger.info(f"Full PID scan complete: {len(all_pids)} total PIDs across {len(by_service)} services")


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

    _MAX_CONNECT_ATTEMPTS = 10  # Give up after this many failed connection attempts

    def run(self):
        """Main thread loop — connects and polls until stop() is called."""
        logger.info("OBDReader thread started")
        connect_failures = 0

        while not self._stop_event.is_set():
            try:
                connected = self._connect_and_poll(attempt=connect_failures + 1)
                if connected:
                    # Successfully connected and polled — reset failure counter
                    connect_failures = 0
                else:
                    connect_failures += 1
                    remaining = self._MAX_CONNECT_ATTEMPTS - connect_failures
                    logger.warning(f"Connection attempt {connect_failures}/{self._MAX_CONNECT_ATTEMPTS} failed"
                                   f" — {remaining} attempts remaining")
                    if connect_failures >= self._MAX_CONNECT_ATTEMPTS:
                        logger.error("Max connection attempts reached — giving up. "
                                     "Check OBD adapter pairing and power.")
                        _update_many({
                            "connected": False,
                            "status": "OBD adapter not found — check pairing and power, then restart SignalKit",
                        })
                        # Stop retrying — sit idle until SignalKit is restarted
                        self._stop_event.wait()
                        break
            except Exception as e:
                logger.error(f"OBDReader unexpected error: {e}")
                _update_many({"connected": False, "status": f"Error: {e}"})
                connect_failures += 1
                if connect_failures >= self._MAX_CONNECT_ATTEMPTS:
                    _update_many({
                        "connected": False,
                        "status": "OBD adapter not found — check pairing and power, then restart SignalKit",
                    })
                    self._stop_event.wait()
                    break
                self._stop_event.wait(config.OBD_RECONNECT_DELAY)

        logger.info("OBDReader thread stopped")

    def _connect_and_poll(self, attempt=1):
        """
        Attempt to connect to the OBD2 adapter and start polling.
        Runs the fast/slow poll loop until disconnected or stopped.
        Returns True if we successfully connected (even if later disconnected).
        Returns False if we failed to connect at all.
        """
        status_msg = f"Connecting to OBD2... ({attempt})"
        _update_many({"connected": False, "status": status_msg})

        # Skip Bluetooth setup on macOS or when using a non-rfcomm port
        # (e.g. ELM327-emulator on a virtual serial port)
        _is_rfcomm = config.OBD_PORT.startswith("/dev/rfcomm")
        _is_linux = platform.system() == "Linux"

        if _is_linux and _is_rfcomm:
            logger.info("Setting up Bluetooth connection...")
            pair_bluetooth()
            time.sleep(2)  # Give Bluetooth time to settle

            if not bind_rfcomm():
                logger.warning("rfcomm bind failed")
                self._stop_event.wait(config.OBD_RECONNECT_DELAY)
                return False
        else:
            logger.info("Skipping Bluetooth setup (port=%s, platform=%s)",
                        config.OBD_PORT, platform.system())

        # Connect via python-OBD
        logger.info(f"Connecting to OBD2 on {config.OBD_PORT}...")

        try:
            connection = obd.OBD(
                portstr=config.OBD_PORT,
                baudrate=config.OBD_BAUDRATE,
                timeout=10,
                fast=False,   # Don't skip supported PID checks
            )
        except Exception as e:
            logger.error(f"obd.OBD() connection failed: {e}")
            self._stop_event.wait(config.OBD_RECONNECT_DELAY)
            return False

        if not connection.is_connected():
            logger.warning("OBD connection returned but is not connected")
            connection.close()
            self._stop_event.wait(config.OBD_RECONNECT_DELAY)
            return False

        logger.info("OBD2 connected successfully")
        _unsupported_pids.clear()  # Re-check PID support on each new connection
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
                _diag["elm_version"] = str(_query_with_timeout(connection, obd.commands.ELM_VERSION).value or "Unknown")
            except Exception:
                _diag["elm_version"] = "Unknown"
            try:
                supported = [str(cmd) for cmd in connection.supported_commands]
                _diag["supported_pids"] = sorted(supported)
            except Exception:
                _diag["supported_pids"] = []

            # Read VIN and decode vehicle info
            try:
                vin_resp = _query_with_timeout(connection, obd.commands.VIN, force=True)
                if not vin_resp.is_null():
                    raw_val = vin_resp.value
                    # python-OBD returns VIN as bytearray or string
                    if isinstance(raw_val, (bytearray, bytes)):
                        vin_str = raw_val.decode("ascii", errors="replace").strip("\x00").strip()
                    else:
                        vin_str = str(raw_val).strip()
                    _diag["vin"] = vin_str
                    _diag["vehicle"] = decode_vin(vin_str)
                    logger.info(f"Vehicle identified: {_diag['vehicle'].get('display', 'Unknown')}")
                else:
                    _diag["vin"] = None
                    _diag["vehicle"] = None
            except Exception as e:
                logger.debug(f"VIN read failed: {e}")
                _diag["vin"] = None
                _diag["vehicle"] = None

        # Scan all supported PIDs once on connect (if enabled)
        if config.SCAN_PIDS_ON_BOOT:
            _scan_all_pids(connection)
        else:
            logger.info("PID scan on boot disabled — skipping")

        # Track whether optional PIDs are supported
        kia_oil_supported = True
        fuel_rate_supported = True

        # Initialize watchdog timestamp
        global _last_successful_query
        _last_successful_query = time.time()

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

            # Watchdog: if no successful query in 15s, the connection is hung
            if _last_successful_query > 0 and (loop_start - _last_successful_query) > 15:
                logger.error("Watchdog: no successful OBD query in 15s — forcing reconnect")
                _update_many({"connected": False, "status": "Connection stalled — reconnecting..."})
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

        return True  # We did connect successfully (even if we later disconnected)
