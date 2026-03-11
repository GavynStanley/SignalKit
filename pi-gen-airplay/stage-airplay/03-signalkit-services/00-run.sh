#!/bin/bash -e
# =============================================================================
# 03-signalkit-services/00-run.sh — SignalKit AirPlay OS (Pi 5)
# =============================================================================
# Installs and enables systemd services:
#   - signalkit.service       — OBD dashboard (main app)
#   - signalkit-x11.service   — Minimal X11 server for pywebview + UxPlay
#   - signalkit-rfcomm.service — Bluetooth rfcomm bind at boot
#   - signalkit-wifi.service  — WiFi hotspot config regeneration
#   - signalkit-airplay.service — UxPlay AirPlay receiver
# =============================================================================

echo "==> [03-signalkit-services] Installing systemd services"

# ---------------------------------------------------------------------------
# SignalKit dashboard service
# ---------------------------------------------------------------------------
install -m 644 files/signalkit.service "${ROOTFS_DIR}/etc/systemd/system/signalkit.service"

on_chroot << 'EOF'
systemctl enable signalkit.service
echo "signalkit.service enabled"
EOF

# ---------------------------------------------------------------------------
# X11 display server service
# ---------------------------------------------------------------------------
# Both pywebview (dashboard) and UxPlay (AirPlay) need X11 for rendering.
install -m 644 files/signalkit-x11.service \
    "${ROOTFS_DIR}/etc/systemd/system/signalkit-x11.service"

on_chroot << 'EOF'
systemctl enable signalkit-x11.service
echo "signalkit-x11.service enabled"
EOF

# Allow pi user to start X without root
install -d "${ROOTFS_DIR}/etc/X11"
cat > "${ROOTFS_DIR}/etc/X11/Xwrapper.config" << 'EOF'
allowed_users=anybody
needs_root_rights=yes
EOF

# ---------------------------------------------------------------------------
# Bluetooth rfcomm bind helper service
# ---------------------------------------------------------------------------
install -m 644 files/signalkit-rfcomm.service \
    "${ROOTFS_DIR}/etc/systemd/system/signalkit-rfcomm.service"

on_chroot << 'EOF'
systemctl enable signalkit-rfcomm.service
echo "signalkit-rfcomm.service enabled"
EOF

# ---------------------------------------------------------------------------
# WiFi hotspot configuration service
# ---------------------------------------------------------------------------
install -m 644 files/signalkit-wifi.service \
    "${ROOTFS_DIR}/etc/systemd/system/signalkit-wifi.service"

install -d "${ROOTFS_DIR}/opt/signalkit/scripts"
install -m 755 files/signalkit-gen-hostapd.sh \
    "${ROOTFS_DIR}/opt/signalkit/scripts/signalkit-gen-hostapd.sh"

on_chroot << 'EOF'
systemctl enable signalkit-wifi.service
echo "signalkit-wifi.service enabled"
EOF

# ---------------------------------------------------------------------------
# AirPlay receiver service (UxPlay)
# ---------------------------------------------------------------------------
# UxPlay runs alongside SignalKit, rendering AirPlay mirrored content
# to the X11 display. When an iPhone connects via AirPlay, UxPlay takes
# over the screen. When they disconnect, UxPlay restarts and waits.
install -m 644 files/signalkit-airplay.service \
    "${ROOTFS_DIR}/etc/systemd/system/signalkit-airplay.service"

on_chroot << 'EOF'
systemctl enable signalkit-airplay.service
echo "signalkit-airplay.service enabled"
EOF

echo "==> [03-signalkit-services] Services installed"
