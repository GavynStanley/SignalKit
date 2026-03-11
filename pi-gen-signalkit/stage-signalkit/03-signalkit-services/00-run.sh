#!/bin/bash -e
# =============================================================================
# 03-signalkit-services/00-run.sh — SignalKit Qt/QML Edition
# =============================================================================
# Installs and enables systemd services:
#   - signalkit.service        — OBD dashboard (Qt/QML via EGLFS, no X11)
#   - signalkit-rfcomm.service — Bluetooth rfcomm bind at boot
#   - signalkit-wifi.service   — WiFi hotspot config regeneration
#
# NOTE: No X11 service — Qt EGLFS renders directly to the framebuffer.
# =============================================================================

echo "==> [03-signalkit-services] Installing systemd services"

# ---------------------------------------------------------------------------
# SignalKit dashboard service (Qt/QML + EGLFS)
# ---------------------------------------------------------------------------
install -m 644 files/signalkit.service "${ROOTFS_DIR}/etc/systemd/system/signalkit.service"

on_chroot << 'EOF'
systemctl enable signalkit.service
echo "signalkit.service enabled"
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

echo "==> [03-signalkit-services] Services installed"
