#!/bin/bash -e
# =============================================================================
# 01-signalkit-system/00-run.sh — SignalKit AirPlay OS (Pi 5)
# =============================================================================
# Runs during image build (in chroot) to configure the system layer:
#   - Remove unnecessary packages (fast boot)
#   - Configure Bluetooth (auto-enable, pairing policy)
#   - Configure WiFi hotspot (hostapd + dnsmasq + static IP)
#   - Configure HDMI display output (Pi 5 — no dwc2 USB gadget)
#   - Disable login prompt (autologin to pi user, then systemd starts SignalKit)
#   - Tune boot parameters for speed
#   - Configure Avahi for AirPlay mDNS discovery
#
# pi-gen context: ${ROOTFS_DIR} is the target filesystem root.
#                 on_chroot runs commands inside that root.
# =============================================================================

echo "==> [01-signalkit-system] Configuring SignalKit AirPlay system layer"

# ---------------------------------------------------------------------------
# 0. Install packages that have interactive conffile prompts
# ---------------------------------------------------------------------------
on_chroot << 'EOF'
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y \
    -o Dpkg::Options::="--force-confdef" \
    -o Dpkg::Options::="--force-confold" \
    hostapd dnsmasq
echo "hostapd and dnsmasq installed"
EOF

# ---------------------------------------------------------------------------
# 1. Remove packages that waste space or slow boot
# ---------------------------------------------------------------------------
on_chroot << 'EOF'
echo "Removing unnecessary packages..."

# Services/daemons we don't need (may or may not be present)
apt-get remove -y --purge \
    triggerhappy rsyslog dphys-swapfile \
    logrotate cron \
    2>/dev/null || true

# Clean up
apt-get autoremove -y --purge
apt-get clean
rm -rf /var/lib/apt/lists/*

# Remove leftover docs and locale data
rm -rf /usr/share/doc/* /usr/share/man/* /usr/share/info/*
rm -rf /usr/share/locale/* 2>/dev/null || true
mkdir -p /usr/share/locale/en_US

echo "Package cleanup done"
EOF

# ---------------------------------------------------------------------------
# 2. Disable swap (embedded device, no swapfile needed, saves writes to SD)
# ---------------------------------------------------------------------------
on_chroot << 'EOF'
systemctl disable dphys-swapfile 2>/dev/null || true
swapoff -a 2>/dev/null || true
EOF

# ---------------------------------------------------------------------------
# 3. Disable services that don't belong on an embedded dashboard
# ---------------------------------------------------------------------------
on_chroot << 'EOF'
for svc in \
    triggerhappy \
    rsyslog \
    apt-daily \
    apt-daily-upgrade \
    man-db \
    ModemManager
do
    systemctl disable "$svc" 2>/dev/null || true
    systemctl mask "$svc" 2>/dev/null || true
done

# Disable getty (login prompt) on tty1 — we use autologin instead
systemctl disable getty@tty1 2>/dev/null || true
EOF

# ---------------------------------------------------------------------------
# 4. Autologin as 'pi' on tty1 (systemd then starts SignalKit)
# ---------------------------------------------------------------------------
install -d "${ROOTFS_DIR}/etc/systemd/system/getty@tty1.service.d"
cat > "${ROOTFS_DIR}/etc/systemd/system/getty@tty1.service.d/autologin.conf" << 'EOF'
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin pi --noclear %I $TERM
EOF

# ---------------------------------------------------------------------------
# 5. Bluetooth configuration — auto-enable adapter on boot
# ---------------------------------------------------------------------------
install -d "${ROOTFS_DIR}/etc/bluetooth"
install -m 644 files/bluetooth-main.conf "${ROOTFS_DIR}/etc/bluetooth/main.conf"

on_chroot << 'EOF'
systemctl enable bluetooth
usermod -aG bluetooth pi
EOF

cat > "${ROOTFS_DIR}/etc/udev/rules.d/99-rfcomm.rules" << 'EOF'
KERNEL=="rfcomm*", MODE="0666"
EOF

# ---------------------------------------------------------------------------
# 6. WiFi Hotspot — static IP on wlan0
# ---------------------------------------------------------------------------
install -d "${ROOTFS_DIR}/etc/NetworkManager/conf.d"
cat > "${ROOTFS_DIR}/etc/NetworkManager/conf.d/99-signalkit-unmanaged.conf" << 'EOF'
[keyfile]
unmanaged-devices=interface-name:wlan0
EOF

if [[ -f "${ROOTFS_DIR}/etc/dhcpcd.conf" ]]; then
    cat >> "${ROOTFS_DIR}/etc/dhcpcd.conf" << 'EOF'

# SignalKit hotspot: static IP on wlan0, no DHCP client (we ARE the DHCP server)
interface wlan0
    static ip_address=192.168.4.1/24
    nohook wpa_supplicant
EOF
fi

on_chroot << 'EOF'
systemctl disable wpa_supplicant 2>/dev/null || true
rfkill unblock wifi 2>/dev/null || true
EOF

install -d "${ROOTFS_DIR}/etc/hostapd"
install -m 644 files/hostapd.conf "${ROOTFS_DIR}/etc/hostapd/hostapd.conf"

if [[ -f "${ROOTFS_DIR}/etc/default/hostapd" ]]; then
    sed -i 's|#DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' \
        "${ROOTFS_DIR}/etc/default/hostapd"
fi

cp "${ROOTFS_DIR}/etc/dnsmasq.conf" "${ROOTFS_DIR}/etc/dnsmasq.conf.orig" 2>/dev/null || true
install -m 644 files/dnsmasq.conf "${ROOTFS_DIR}/etc/dnsmasq.conf"

on_chroot << 'EOF'
systemctl unmask hostapd 2>/dev/null || true
systemctl enable hostapd
systemctl enable dnsmasq
EOF

install -d "${ROOTFS_DIR}/etc/systemd/system/hostapd.service.d"
cat > "${ROOTFS_DIR}/etc/systemd/system/hostapd.service.d/wait-for-wifi.conf" << 'EOF'
[Unit]
Requires=signalkit-wifi.service
After=signalkit-wifi.service
EOF

# ---------------------------------------------------------------------------
# 7. Boot configuration — Pi 5 HDMI display settings
# ---------------------------------------------------------------------------
# Pi 5 uses /boot/firmware/config.txt (bookworm standard)
BOOT_CONFIG="${ROOTFS_DIR}/boot/firmware/config.txt"
[[ ! -f "${BOOT_CONFIG}" ]] && BOOT_CONFIG="${ROOTFS_DIR}/boot/config.txt"

cat >> "${BOOT_CONFIG}" << 'EOF'

# =============================================================================
# SignalKit AirPlay — Display Configuration (Pi 5)
# =============================================================================
# Force HDMI on even if no monitor is detected at boot
hdmi_force_hotplug=1

# Custom display mode for 800x480 LCD
hdmi_group=2
hdmi_mode=87
hdmi_cvt=800 480 60 6 0 0 0
hdmi_drive=2

# Disable overscan (black borders) — our display fills edge-to-edge
disable_overscan=1

# GPU memory — Pi 5 VideoCore VII needs more VRAM for
# WebKit/X11 rendering + GStreamer H.264 decode (AirPlay mirroring)
gpu_mem=256

# Disable HDMI CEC — prevents external devices from sending
# power-off/standby commands that blank the display
hdmi_ignore_cec_init=1
hdmi_ignore_cec=1

# Never cut the HDMI signal
hdmi_blanking=0

# Disable the rainbow splash screen and text during boot
disable_splash=1

# NOTE: No dtoverlay=dwc2 — Pi 5 has USB-A host ports, not OTG.
# SSH access is via WiFi hotspot or Ethernet, not USB gadget.
EOF

# ---------------------------------------------------------------------------
# 8. Plymouth boot splash — SignalKit branded theme
# ---------------------------------------------------------------------------
install -d "${ROOTFS_DIR}/usr/share/plymouth/themes/signalkit"
install -m 644 files/plymouth-signalkit/signalkit.plymouth \
    "${ROOTFS_DIR}/usr/share/plymouth/themes/signalkit/signalkit.plymouth"
install -m 644 files/plymouth-signalkit/signalkit.script \
    "${ROOTFS_DIR}/usr/share/plymouth/themes/signalkit/signalkit.script"
install -m 644 files/plymouth-signalkit/logo.png \
    "${ROOTFS_DIR}/usr/share/plymouth/themes/signalkit/logo.png"
install -m 644 files/plymouth-signalkit/dot.png \
    "${ROOTFS_DIR}/usr/share/plymouth/themes/signalkit/dot.png"

on_chroot << 'EOF'
plymouth-set-default-theme signalkit
EOF

# ---------------------------------------------------------------------------
# 9. Kernel boot parameters — quiet and fast (Pi 5, no USB gadget)
# ---------------------------------------------------------------------------
CMDLINE="${ROOTFS_DIR}/boot/firmware/cmdline.txt"
[[ ! -f "${CMDLINE}" ]] && CMDLINE="${ROOTFS_DIR}/boot/cmdline.txt"

EXISTING=$(cat "${CMDLINE}" | tr -d '\n')
# NOTE: No modules-load=dwc2,g_ether — Pi 5 has USB-A host ports, not OTG
for PARAM in "quiet" "splash" "loglevel=0" "logo.nologo" "vt.global_cursor_default=0" "systemd.show_status=false" "rd.systemd.show_status=false" "console=tty3" "consoleblank=0"; do
    if ! echo "${EXISTING}" | grep -q "${PARAM}"; then
        EXISTING="${EXISTING} ${PARAM}"
    fi
done
echo "${EXISTING}" > "${CMDLINE}"

# ---------------------------------------------------------------------------
# 10. Hostname
# ---------------------------------------------------------------------------
echo "signalkit-airplay" > "${ROOTFS_DIR}/etc/hostname"
sed -i "s/raspberrypi/signalkit-airplay/g" "${ROOTFS_DIR}/etc/hosts" 2>/dev/null || true

# ---------------------------------------------------------------------------
# 11. Avahi (mDNS) — required for AirPlay device discovery
# ---------------------------------------------------------------------------
# AirPlay clients find the receiver via Bonjour/mDNS. Avahi must be running
# for UxPlay to advertise the _airplay._tcp service on the local network.
on_chroot << 'EOF'
systemctl enable avahi-daemon
EOF

# ---------------------------------------------------------------------------
# 12. Display permissions
# ---------------------------------------------------------------------------
on_chroot << 'EOF'
# Include 'audio' group for AirPlay audio output
usermod -aG video,render,input,dialout,systemd-journal,audio pi
EOF

cat > "${ROOTFS_DIR}/etc/udev/rules.d/99-framebuffer.rules" << 'EOF'
KERNEL=="fb*", MODE="0660", GROUP="video"
EOF

cat > "${ROOTFS_DIR}/etc/udev/rules.d/99-gpu.rules" << 'EOF'
SUBSYSTEM=="drm", MODE="0660", GROUP="render"
EOF

# ---------------------------------------------------------------------------
# 13. Custom MOTD — replace default Debian banner with SignalKit info
# ---------------------------------------------------------------------------
on_chroot << 'EOF'
rm -f /etc/motd
rm -f /etc/update-motd.d/*
EOF

echo -n > "${ROOTFS_DIR}/etc/motd"

install -m 755 files/motd-signalkit \
    "${ROOTFS_DIR}/etc/profile.d/signalkit-motd.sh"

echo "==> [01-signalkit-system] System configuration complete"
