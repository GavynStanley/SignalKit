#!/bin/bash -e
# =============================================================================
# 01-signalkit-system/00-run.sh
# =============================================================================
# Runs during image build (in chroot) to configure the system layer:
#   - Remove unnecessary packages (fast boot)
#   - Configure Bluetooth (auto-enable, pairing policy)
#   - Configure WiFi hotspot (hostapd + dnsmasq + static IP)
#   - Configure HDMI display output
#   - Disable login prompt (autologin to pi user, then systemd starts SignalKit)
#   - Tune boot parameters for speed
#
# pi-gen context: ${ROOTFS_DIR} is the target filesystem root.
#                 on_chroot runs commands inside that root.
# =============================================================================

# on_chroot is provided by pi-gen's common.sh (sourced by the build system)
# ROOTFS_DIR, STAGE_DIR are also provided by the build environment.

echo "==> [01-signalkit-system] Configuring SignalKit system layer"

# ---------------------------------------------------------------------------
# 0. Install packages that have interactive conffile prompts
# ---------------------------------------------------------------------------
# hostapd ships /etc/default/hostapd as a conffile. When apt installs it
# inside pi-gen's chroot (stdin = /dev/null), dpkg's conffile prompt causes
# "end of file on stdin" and aborts the build. We install these here with
# DEBIAN_FRONTEND=noninteractive and --force-confdef so dpkg never asks.
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
# NOTE: Most bloat (build-essential, media libs, spell checkers, unused
# firmware, extra kernels) is no longer installed — pi-gen/stage2 package
# lists have been trimmed at the source. Only a few stragglers remain.
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
# We configure autologin so that if SignalKit crashes, the user gets a shell.
# The signalkit.service starts independently of this.
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
# Add pi user to bluetooth group so rfcomm doesn't need sudo
usermod -aG bluetooth pi
# udev rule: allow /dev/rfcomm* without root
EOF

cat > "${ROOTFS_DIR}/etc/udev/rules.d/99-rfcomm.rules" << 'EOF'
KERNEL=="rfcomm*", MODE="0666"
EOF

# ---------------------------------------------------------------------------
# 6. WiFi Hotspot — static IP on wlan0
# ---------------------------------------------------------------------------
# Bookworm uses NetworkManager instead of dhcpcd.  We need to:
#   a) Tell NetworkManager to leave wlan0 alone (hostapd manages it)
#   b) Assign a static IP to wlan0 via systemd-networkd or a simple unit
#   c) Disable wpa_supplicant so it doesn't fight hostapd

# (a) Tell NetworkManager to ignore wlan0
install -d "${ROOTFS_DIR}/etc/NetworkManager/conf.d"
cat > "${ROOTFS_DIR}/etc/NetworkManager/conf.d/99-signalkit-unmanaged.conf" << 'EOF'
[keyfile]
unmanaged-devices=interface-name:wlan0
EOF

# (b) Static IP — assigned by signalkit-wifi.service before hostapd starts
# (using `ip addr add` in the service, no systemd-networkd needed)

# (b-fallback) Also write dhcpcd.conf in case this is a Bullseye-based build
if [[ -f "${ROOTFS_DIR}/etc/dhcpcd.conf" ]]; then
    cat >> "${ROOTFS_DIR}/etc/dhcpcd.conf" << 'EOF'

# SignalKit hotspot: static IP on wlan0, no DHCP client (we ARE the DHCP server)
interface wlan0
    static ip_address=192.168.4.1/24
    nohook wpa_supplicant
EOF
fi

# (c) Disable wpa_supplicant so it doesn't fight hostapd for wlan0
on_chroot << 'EOF'
systemctl disable wpa_supplicant 2>/dev/null || true
rfkill unblock wifi 2>/dev/null || true
EOF

# hostapd config
install -d "${ROOTFS_DIR}/etc/hostapd"
install -m 644 files/hostapd.conf "${ROOTFS_DIR}/etc/hostapd/hostapd.conf"

# Tell hostapd where its config is (Bullseye style)
if [[ -f "${ROOTFS_DIR}/etc/default/hostapd" ]]; then
    sed -i 's|#DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' \
        "${ROOTFS_DIR}/etc/default/hostapd"
fi

# dnsmasq config (DHCP for phone clients)
cp "${ROOTFS_DIR}/etc/dnsmasq.conf" "${ROOTFS_DIR}/etc/dnsmasq.conf.orig" 2>/dev/null || true
install -m 644 files/dnsmasq.conf "${ROOTFS_DIR}/etc/dnsmasq.conf"

on_chroot << 'EOF'
systemctl unmask hostapd 2>/dev/null || true
systemctl enable hostapd
systemctl enable dnsmasq
EOF

# Override hostapd to wait for signalkit-wifi (interface + IP must be ready)
install -d "${ROOTFS_DIR}/etc/systemd/system/hostapd.service.d"
cat > "${ROOTFS_DIR}/etc/systemd/system/hostapd.service.d/wait-for-wifi.conf" << 'EOF'
[Unit]
Requires=signalkit-wifi.service
After=signalkit-wifi.service
EOF

# ---------------------------------------------------------------------------
# 7. Boot configuration — HDMI display settings
# ---------------------------------------------------------------------------
# Detect which config.txt path this Pi OS version uses
BOOT_CONFIG="${ROOTFS_DIR}/boot/config.txt"
[[ -f "${ROOTFS_DIR}/boot/firmware/config.txt" ]] && \
    BOOT_CONFIG="${ROOTFS_DIR}/boot/firmware/config.txt"

# Append SignalKit display config to the boot config
cat >> "${BOOT_CONFIG}" << 'EOF'

# =============================================================================
# SignalKit Display Configuration
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

# GPU memory — Qt EGLFS uses GPU for rendering
gpu_mem=128

# Disable HDMI CEC — prevents external devices from sending
# power-off/standby commands that blank the display
hdmi_ignore_cec_init=1
hdmi_ignore_cec=1

# Never cut the HDMI signal — prevents "no signal" on the display.
# 0 = HDMI output stays active even when DPMS/screensaver triggers.
# Without this, the GPU firmware can power off the HDMI port entirely.
hdmi_blanking=0

# Disable the rainbow splash screen and text during boot for a cleaner startup
disable_splash=1

# =============================================================================
# USB Gadget Mode (SSH over USB for development)
# =============================================================================
# Enables the Pi Zero 2 W's USB port as an ethernet gadget so you can
# SSH in over a USB cable from a Mac/PC without WiFi or a keyboard.
dtoverlay=dwc2
EOF

# ---------------------------------------------------------------------------
# 8. Plymouth boot splash — SignalKit branded theme
# ---------------------------------------------------------------------------
# Install the custom SignalKit Plymouth theme
install -d "${ROOTFS_DIR}/usr/share/plymouth/themes/signalkit"
install -m 644 files/plymouth-signalkit/signalkit.plymouth \
    "${ROOTFS_DIR}/usr/share/plymouth/themes/signalkit/signalkit.plymouth"
install -m 644 files/plymouth-signalkit/signalkit.script \
    "${ROOTFS_DIR}/usr/share/plymouth/themes/signalkit/signalkit.script"
install -m 644 files/plymouth-signalkit/logo.png \
    "${ROOTFS_DIR}/usr/share/plymouth/themes/signalkit/logo.png"
install -m 644 files/plymouth-signalkit/dot.png \
    "${ROOTFS_DIR}/usr/share/plymouth/themes/signalkit/dot.png"

# Set SignalKit as the default Plymouth theme
# NOTE: We do NOT run update-initramfs here — export-image/05-finalise does it
# automatically. Running it twice doubles the build time under QEMU emulation.
on_chroot << 'EOF'
plymouth-set-default-theme signalkit
EOF

# ---------------------------------------------------------------------------
# 9. Kernel boot parameters — quiet and fast
# ---------------------------------------------------------------------------
# IMPORTANT: We do NOT replace cmdline.txt wholesale — pi-gen writes the
# correct root=PARTUUID=... into it during the export phase.
# We append our parameters to whatever pi-gen has already placed there.
CMDLINE="${ROOTFS_DIR}/boot/cmdline.txt"
[[ -f "${ROOTFS_DIR}/boot/firmware/cmdline.txt" ]] && \
    CMDLINE="${ROOTFS_DIR}/boot/firmware/cmdline.txt"

# cmdline.txt is a single line — read it, strip newline, append our params
EXISTING=$(cat "${CMDLINE}" | tr -d '\n')
for PARAM in "modules-load=dwc2,g_ether" "quiet" "splash" "loglevel=0" "logo.nologo" "vt.global_cursor_default=0" "systemd.show_status=false" "rd.systemd.show_status=false" "console=tty3" "consoleblank=0"; do
    if ! echo "${EXISTING}" | grep -q "${PARAM}"; then
        EXISTING="${EXISTING} ${PARAM}"
    fi
done
echo "${EXISTING}" > "${CMDLINE}"

# ---------------------------------------------------------------------------
# 10. Hostname
# ---------------------------------------------------------------------------
echo "signalkit" > "${ROOTFS_DIR}/etc/hostname"
# Update /etc/hosts to match
sed -i "s/raspberrypi/signalkit/g" "${ROOTFS_DIR}/etc/hosts" 2>/dev/null || true

# ---------------------------------------------------------------------------
# 11. USB gadget networking — static IP on usb0
# ---------------------------------------------------------------------------
# When the Pi is connected to a Mac/PC via USB, g_ether creates a usb0
# interface. This service gives it a static link-local IP so SSH works
# immediately without any config on the host side.
cat > "${ROOTFS_DIR}/etc/systemd/system/usb-gadget-ip.service" << 'EOF'
[Unit]
Description=Configure USB gadget ethernet (usb0) with static IP
After=network-pre.target sys-subsystem-net-devices-usb0.device
Wants=sys-subsystem-net-devices-usb0.device
ConditionPathExists=/sys/class/net/usb0

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/sbin/ip addr add 169.254.100.2/16 dev usb0
ExecStart=/sbin/ip link set usb0 up

[Install]
WantedBy=multi-user.target
EOF

on_chroot << 'EOF'
systemctl enable usb-gadget-ip.service
EOF

# ---------------------------------------------------------------------------
# 12. Display permissions (no X11)
# ---------------------------------------------------------------------------
on_chroot << 'EOF'
usermod -aG video,render,input,dialout,systemd-journal pi
EOF

# Allow pi user to access /dev/fb0 and /dev/dri/* without root
cat > "${ROOTFS_DIR}/etc/udev/rules.d/99-framebuffer.rules" << 'EOF'
KERNEL=="fb*", MODE="0660", GROUP="video"
EOF

cat > "${ROOTFS_DIR}/etc/udev/rules.d/99-gpu.rules" << 'EOF'
SUBSYSTEM=="drm", MODE="0660", GROUP="render"
EOF

# ---------------------------------------------------------------------------
# 13. Custom MOTD — replace default Debian banner with SignalKit info
# ---------------------------------------------------------------------------
# Remove all default MOTD sources
on_chroot << 'EOF'
rm -f /etc/motd
rm -f /etc/update-motd.d/*
EOF

# Empty /etc/motd so the default static banner is gone
echo -n > "${ROOTFS_DIR}/etc/motd"

# Install as /etc/profile.d/ script — this is sourced by bash on every
# interactive login (SSH, console, etc.) and works on all Raspberry Pi OS
# versions regardless of pam_motd configuration.
install -m 755 files/motd-signalkit \
    "${ROOTFS_DIR}/etc/profile.d/signalkit-motd.sh"

echo "==> [01-signalkit-system] System configuration complete"
