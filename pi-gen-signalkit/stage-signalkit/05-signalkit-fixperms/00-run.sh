#!/bin/bash -e
# =============================================================================
# 05-signalkit-fixperms/00-run.sh
# =============================================================================
# Fixes file ownership and permissions across the rootfs.
#
# Why this is needed:
#   When pi-gen builds on an x86 host using QEMU user-static for ARM
#   cross-compilation, chown/chmod operations inside the emulated chroot
#   can silently fail or mismap UIDs. This results in system files being
#   owned by uid 1000 (the pi user) instead of root, which breaks:
#     - sudo (needs setuid root)
#     - su, passwd, newgrp, chfn, chsh (setuid binaries)
#     - hostapd, dnsmasq (need root-owned config files)
#     - systemd service isolation
#
# This script runs OUTSIDE the chroot (on the host, as root, no QEMU)
# so all filesystem operations work correctly regardless of emulation bugs.
# =============================================================================

echo "==> [05-signalkit-fixperms] Fixing file ownership and permissions"

# ---------------------------------------------------------------------------
# 1. Reset system directories to root:root ownership
# ---------------------------------------------------------------------------
# These directories and their contents must be owned by root for the system
# to function correctly. We exclude /home which has user-owned content.
for dir in bin boot etc lib opt root run sbin srv tmp usr var; do
    if [[ -d "${ROOTFS_DIR}/${dir}" ]]; then
        chown -R root:root "${ROOTFS_DIR}/${dir}"
    fi
done
echo "System directories reset to root:root"

# ---------------------------------------------------------------------------
# 2. Restore user home directory ownership
# ---------------------------------------------------------------------------
if [[ -d "${ROOTFS_DIR}/home/pi" ]]; then
    chown -R 1000:1000 "${ROOTFS_DIR}/home/pi"
    echo "Home directory /home/pi set to pi:pi (1000:1000)"
fi

# ---------------------------------------------------------------------------
# 3. Restore SignalKit application ownership (runs as pi user)
# ---------------------------------------------------------------------------
if [[ -d "${ROOTFS_DIR}/opt/signalkit" ]]; then
    chown -R 1000:1000 "${ROOTFS_DIR}/opt/signalkit"
    echo "SignalKit app /opt/signalkit set to pi:pi (1000:1000)"
fi

# ---------------------------------------------------------------------------
# 4. Restore setuid/setgid bits on critical binaries
# ---------------------------------------------------------------------------
# These binaries need the setuid bit to function (e.g., sudo needs to
# escalate privileges). QEMU emulation can strip these bits.
SETUID_BINS=(
    usr/bin/sudo
    usr/bin/passwd
    usr/bin/newgrp
    usr/bin/chfn
    usr/bin/chsh
    usr/bin/su
    usr/bin/gpasswd
    usr/bin/crontab
    usr/lib/openssh/ssh-keysign
    usr/lib/dbus-1.0/dbus-daemon-launch-helper
)

for bin in "${SETUID_BINS[@]}"; do
    if [[ -f "${ROOTFS_DIR}/${bin}" ]]; then
        chmod u+s "${ROOTFS_DIR}/${bin}"
    fi
done
echo "Setuid bits restored on critical binaries"

# ---------------------------------------------------------------------------
# 5. Restore setgid bits
# ---------------------------------------------------------------------------
SETGID_BINS=(
    usr/bin/wall
    usr/bin/write
    usr/bin/expiry
    usr/bin/chage
    usr/bin/ssh-agent
)

for bin in "${SETGID_BINS[@]}"; do
    if [[ -f "${ROOTFS_DIR}/${bin}" ]]; then
        chmod g+s "${ROOTFS_DIR}/${bin}"
    fi
done
echo "Setgid bits restored"

# ---------------------------------------------------------------------------
# 6. Fix specific directory/file permissions
# ---------------------------------------------------------------------------
# /tmp must be world-writable with sticky bit
chmod 1777 "${ROOTFS_DIR}/tmp" 2>/dev/null || true

# /var/tmp same
chmod 1777 "${ROOTFS_DIR}/var/tmp" 2>/dev/null || true

# /root home should be restricted
chmod 700 "${ROOTFS_DIR}/root" 2>/dev/null || true

# SSH directories
if [[ -d "${ROOTFS_DIR}/etc/ssh" ]]; then
    chmod 755 "${ROOTFS_DIR}/etc/ssh"
    chmod 644 "${ROOTFS_DIR}/etc/ssh/"*.pub 2>/dev/null || true
    chmod 600 "${ROOTFS_DIR}/etc/ssh/ssh_host_"*_key 2>/dev/null || true
fi

# /etc/shadow must be root-owned and restricted
chmod 640 "${ROOTFS_DIR}/etc/shadow" 2>/dev/null || true
chown root:shadow "${ROOTFS_DIR}/etc/shadow" 2>/dev/null || true
chmod 640 "${ROOTFS_DIR}/etc/gshadow" 2>/dev/null || true
chown root:shadow "${ROOTFS_DIR}/etc/gshadow" 2>/dev/null || true

# /var/log/signalkit owned by pi
if [[ -d "${ROOTFS_DIR}/var/log/signalkit" ]]; then
    chown 1000:1000 "${ROOTFS_DIR}/var/log/signalkit"
fi

echo "==> [05-signalkit-fixperms] Permissions fixed"
