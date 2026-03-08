# SignalKit — Raspberry Pi OBD2 Car Dashboard

A custom Raspberry Pi OS image that boots directly into a real-time car dashboard. No desktop, no login, no setup required beyond flashing the SD card. Built with **pi-gen**, the official Raspberry Pi OS build tool.

Connects to your car's OBD2 port via a Bluetooth ELM327 adapter and displays live engine data on an HDMI screen, with a mobile web dashboard accessible over WiFi.

**Target hardware:** Raspberry Pi Zero 2 W + 800x480 HDMI display + Veepeak Bluetooth OBD2 adapter

---

## Features

- **HDMI dashboard** (pywebview + Tailwind CSS) — RPM, speed, coolant temp, battery voltage, throttle, engine load, intake air temp, oil temp, fuel trim, MPG, active DTCs
- **Sparkline graphs** — rolling trend lines on each metric card
- **Trip computer** — elapsed time, distance, average MPG
- **Mobile web dashboard** — connect your phone to the Pi's WiFi hotspot, open a browser
- **Setup wizard** — first-boot guided setup on both HDMI and web (Bluetooth scan, WiFi config)
- **Captive portal** — phones auto-open the dashboard when connecting to the hotspot
- **Progressive Web App** — add to home screen on iOS/Android for an app-like experience
- **OTA updates** — update the app from GitHub without reflashing the SD card
- **PID auto-detection** — automatically fades out metrics your car doesn't support
- **Runtime settings** — change theme colors, units, warning thresholds, polling intervals, and more from the web UI
- **Safety disclaimer** — one-time acknowledgment overlay on first web visit
- **Read-only filesystem** (overlayfs) — survives hard power cuts with no SD card corruption
- **Color themes** — red, blue, green, purple, orange, cyan, pink
- **Warning alerts** — color-coded overheat, low battery, and redline indicators
- **Kia extended PIDs** — oil temperature via manufacturer-specific PID 2101
- **Dev console** — send raw OBD/ELM327 commands for debugging

---

## Hardware

| Component | Part |
|-----------|------|
| SBC | Raspberry Pi Zero 2 W |
| Display | 800x480 HDMI LCD |
| OBD2 Adapter | Veepeak BT/BLE ELM327 (or any Bluetooth ELM327) |
| Power | Car 12V to USB-C (5V 3A minimum) |

---

## Quick Start

### 1. Build the OS image

```bash
git clone https://github.com/GavynStanley/SignalKit.git
cd SignalKit
chmod +x build.sh
./build.sh              # Linux (native)
./build.sh --docker     # macOS/Windows (via Docker)
```

Build takes 20-60 minutes. Output: `deploy/SignalKit-YYYY-MM-DD.img.zip`

### 2. Flash to SD card

Use **Raspberry Pi Imager**: Choose OS > Use Custom > select the `.img.zip`

Or with `dd`:
```bash
unzip -p deploy/SignalKit-*.img.zip | sudo dd of=/dev/sdX bs=4M status=progress
```

### 3. Boot and set up

1. Insert SD card into the Pi and power on
2. The HDMI display shows a setup screen with WiFi credentials
3. Connect your phone to the **SignalKit** WiFi (default password: `signalkit1234`)
4. A setup wizard opens automatically — select your OBD2 Bluetooth adapter and configure WiFi
5. The dashboard starts automatically after setup

---

## Project Structure

```
build.sh                         # Build script — produces the flashable .img
VERSION                          # App version (read by config.py)
signalkit/                       # The dashboard application
|-- main.py                      # Entry point — starts all subsystems
|-- config.py                    # Settings, defaults, runtime overrides
|-- obd_reader.py                # OBD2 polling thread
|-- display.py                   # HDMI dashboard (pywebview + Tailwind CSS)
|-- web_server.py                # Mobile web UI, settings API, setup wizard
|-- trip.py                      # Trip computer (distance, time, avg MPG)
|-- dtc_descriptions.py          # DTC code descriptions
|-- static/
|   +-- tailwind.js              # Bundled Tailwind CSS (offline use)
+-- setup/                       # Alternative: manual install on existing Pi OS
    |-- install.sh
    |-- autostart.service
    +-- hotspot.sh

pi-gen-config/
|-- config                       # pi-gen build settings
+-- stage-signalkit/             # Custom OS stage
    |-- 00-signalkit-packages/
    |   +-- 00-packages          # apt packages
    |-- 01-signalkit-system/
    |   |-- 00-run.sh            # Bluetooth, WiFi hotspot, display, boot config
    |   +-- files/               # hostapd.conf, dnsmasq.conf, plymouth theme, etc.
    |-- 02-signalkit-app/
    |   +-- 00-run.sh            # Clones repo to /opt/signalkit, installs pip deps
    |-- 03-signalkit-services/
    |   |-- 00-run.sh            # Enables systemd services
    |   +-- files/
    |       |-- signalkit.service         # Main app service
    |       |-- signalkit-rfcomm.service  # Bluetooth serial bind
    |       |-- signalkit-wifi.service    # WiFi hotspot config + static IP
    |       +-- signalkit-x11.service     # X11 display server
    |-- 04-signalkit-readonly/
    |   +-- 00-run.sh            # Enables overlayfs read-only root
    +-- 05-signalkit-fixperms/
        +-- 00-run.sh            # Fixes file ownership (QEMU build artifact)
```

---

## Building the OS Image

### Requirements

| Requirement | Notes |
|-------------|-------|
| Linux host | Ubuntu 22.04+ recommended. macOS/Windows need `--docker`. |
| ~8 GB free disk | For build artifacts |
| Internet access | Downloads Debian packages during build |
| Docker (optional) | Required for macOS/Windows builds |

### Build options

```bash
./build.sh                    # Native Linux build
./build.sh --docker           # Docker build (macOS/Windows)
./build.sh --clean            # Full clean rebuild
./build.sh --clean-signalkit  # Re-run only SignalKit stage (keeps base OS cached)
```

The build script automatically:
- Links the custom stage into pi-gen
- Installs build dependencies (on Linux)
- Skips desktop/app stages (3-5)
- Produces a compressed `.img.zip`

### OBD2 MAC address

You do **not** need to set the MAC address before building. The first-boot setup wizard will scan for Bluetooth devices and let you select your adapter. If you prefer to bake it in:

```python
# signalkit/config.py
OBD_MAC = "AA:BB:CC:DD:EE:FF"   # Replace with your adapter's MAC
```

---

## Using SignalKit

### HDMI Display

The dashboard auto-starts on boot. Layout (800x480):

| Section | Data |
|---------|------|
| Top row | RPM (with bar + redline) and Speed |
| Metrics row | Coolant temp, Battery voltage, Throttle %, Engine load |
| Secondary row | Intake air temp, Oil temp, Fuel trim B1, Fuel economy (MPG) |
| Bottom | Active DTC fault codes with descriptions |
| Status bar | Connection status, trip computer, clock |

Warning colors: green = normal, amber = caution, red = action needed.

### Mobile Web Dashboard

1. Connect to the **SignalKit** WiFi network (default password: `signalkit1234`)
2. A captive portal page should open automatically
3. If not, open `http://192.168.4.1:8080` in your browser

The web UI includes:
- **Dashboard** — live-updating metrics via Server-Sent Events
- **Settings** — change units, themes, thresholds, polling intervals, WiFi password
- **Update** — OTA update from GitHub (handles overlayfs automatically)
- **Diagnostics** — view active DTCs
- **Dev** — raw OBD/ELM327 command console
- **About** — version info, legal notices

### Settings

All settings are changeable at runtime via the web UI at `/settings`. Changes are saved to `/boot/firmware/signalkit-config.json` (the FAT32 boot partition, always writable even with overlayfs). Available settings:

- OBD2 adapter (Bluetooth scanner)
- Warning thresholds (overheat temp, low battery voltage, RPM redline)
- Polling intervals (fast/slow)
- Display units (MPH/km/h, Celsius/Fahrenheit)
- Clock format (12/24 hour)
- Color theme
- Sparkline graphs (on/off)
- Dashboard card layout
- WiFi hotspot name and password

---

## OTA Updates

SignalKit can update itself from GitHub without reflashing the SD card.

From the web UI, go to the **Update** page. If the root filesystem uses overlayfs (default), the update flow is:

1. Disable overlayfs and reboot (automatic)
2. `git pull` the latest code
3. Re-enable overlayfs and reboot

This takes two reboots and is fully automated once you hit the update button.

---

## Architecture

### How it works

```
Power on
  -> Plymouth boot splash
  -> systemd starts signalkit-x11.service (X11 display server)
  -> systemd starts signalkit-rfcomm.service (binds Bluetooth serial)
  -> systemd starts signalkit-wifi.service (configures WiFi AP + static IP)
  -> systemd starts hostapd + dnsmasq (WiFi hotspot + DHCP)
  -> systemd starts signalkit.service
     -> main.py
        -> OBD2 reader thread (polls ELM327 adapter)
        -> Flask web server thread (port 8080)
        -> pywebview HDMI display (main thread)
```

### OBD2 Polling

- `OBDReader` runs in a background thread
- Fast data (RPM, speed, throttle, load): polled every ~1 second
- Slow data (temps, voltage, DTCs): polled every ~5 seconds
- All data in a shared dict protected by `threading.Lock`
- `obd_reader.get_data()` returns a thread-safe snapshot

### Bluetooth

The Veepeak adapter uses classic Bluetooth SPP (Serial Port Profile). The `signalkit-rfcomm.service` runs `rfcomm bind` on boot to create `/dev/rfcomm0`, which python-OBD uses as a serial port.

### WiFi Hotspot

- `NetworkManager` is configured to ignore `wlan0`
- `signalkit-wifi.service` assigns a static IP (`192.168.4.1`) and writes `hostapd.conf` from config.py
- `hostapd` runs the access point; `dnsmasq` provides DHCP
- DNS wildcard (`address=/#/192.168.4.1`) enables the captive portal

### Read-Only Filesystem

The root filesystem is protected by overlayfs (configured in stage 04). All writes go to a tmpfs overlay and are discarded on reboot. This prevents SD card corruption from power cuts. Settings persist because they're written to the FAT32 boot partition, which is always writable.

### Kia Extended PIDs

Kia/Hyundai vehicles use OBD2 service `0x22` for manufacturer-specific data. Oil temperature uses PID `2101`, byte index 7, formula: `temp_c = (raw * 0.75) - 48`. Configurable in `config.py`.

---

## Troubleshooting

### WiFi hotspot not appearing

```bash
sudo systemctl status hostapd
sudo systemctl status signalkit-wifi
sudo journalctl -u hostapd -n 30
sudo journalctl -u signalkit-wifi -n 30
```

### Dashboard doesn't start

```bash
sudo journalctl -u signalkit -f        # Follow live logs
sudo systemctl status signalkit        # Check service status
cd /opt/signalkit/signalkit && python3 main.py  # Run manually
```

### Bluetooth won't connect

```bash
# Check if adapter is visible
hcitool scan

# Pair manually
bluetoothctl
> power on
> scan on
> pair AA:BB:CC:DD:EE:FF
> trust AA:BB:CC:DD:EE:FF
> quit

# Bind rfcomm manually
sudo rfcomm bind /dev/rfcomm0 AA:BB:CC:DD:EE:FF 1
```

### Oil temp shows "N/A"

Expected on many vehicles. The oil temperature PID (`2101`) is Kia/Hyundai-specific and may not be supported on all trims. The dashboard auto-detects and fades unsupported metrics.

---

## Dependencies

| Package | Purpose |
|---------|---------|
| `python-obd` | OBD2 communication over rfcomm |
| `pywebview` | HDMI display rendering (GTK + WebKit2) |
| `flask` | Web server for mobile UI and API |
| `bluez` / `rfcomm` | Bluetooth stack and serial binding |
| `hostapd` | WiFi access point |
| `dnsmasq` | DHCP + DNS for hotspot clients |
| `xserver-xorg-core` | X11 display server for pywebview |

All dependencies are installed automatically during the image build.

---

## License

MIT
