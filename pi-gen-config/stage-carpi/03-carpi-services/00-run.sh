#!/bin/bash -e
# =============================================================================
# 03-carpi-services/00-run.sh
# =============================================================================
# Installs and enables the carpi.service systemd unit.
# This is what makes CarPi auto-start on every boot with no user interaction.
# =============================================================================

echo "==> [03-carpi-services] Installing systemd service"

# Install the service unit file
install -m 644 files/carpi.service "${ROOTFS_DIR}/etc/systemd/system/carpi.service"

# Enable it so it starts on boot (equivalent to 'systemctl enable carpi')
# In pi-gen chroot, systemctl enable works via symlinks in /etc/systemd/system/
on_chroot << 'EOF'
systemctl enable carpi.service
echo "carpi.service enabled"
EOF

# ---------------------------------------------------------------------------
# X11 display server service
# ---------------------------------------------------------------------------
# pywebview uses GTK + WebKit which requires X11. This minimal Xorg service
# starts a framebuffer-only X server with no window manager — CarPi renders
# fullscreen via pywebview on top of it.
install -m 644 files/carpi-x11.service \
    "${ROOTFS_DIR}/etc/systemd/system/carpi-x11.service"

on_chroot << 'EOF'
systemctl enable carpi-x11.service
echo "carpi-x11.service enabled"
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
# rfcomm bind must be run each boot before the carpi app starts.
# We create a oneshot service that does this, ordered before carpi.service.
install -m 644 files/carpi-rfcomm.service \
    "${ROOTFS_DIR}/etc/systemd/system/carpi-rfcomm.service"

on_chroot << 'EOF'
systemctl enable carpi-rfcomm.service
echo "carpi-rfcomm.service enabled"
EOF

# ---------------------------------------------------------------------------
# WiFi hotspot configuration service
# ---------------------------------------------------------------------------
# Regenerates hostapd.conf from config.py on each boot so WiFi SSID/password
# changes made via the web UI take effect.
install -m 644 files/carpi-wifi.service \
    "${ROOTFS_DIR}/etc/systemd/system/carpi-wifi.service"

# Helper script that generates hostapd.conf from config.py
install -d "${ROOTFS_DIR}/opt/carpi/scripts"
install -m 755 files/carpi-gen-hostapd.sh \
    "${ROOTFS_DIR}/opt/carpi/scripts/carpi-gen-hostapd.sh"

on_chroot << 'EOF'
systemctl enable carpi-wifi.service
echo "carpi-wifi.service enabled"
EOF

echo "==> [03-carpi-services] Services installed"
