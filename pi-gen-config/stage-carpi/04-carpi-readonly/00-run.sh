#!/bin/bash -e
# =============================================================================
# 04-carpi-readonly/00-run.sh
# =============================================================================
# Configures a read-only root filesystem using overlayfs.
#
# Why read-only?
#   A car dashboard loses power instantly when the engine turns off.
#   Without a read-only FS, an abrupt power cut mid-write corrupts the SD card.
#   With overlayfs:
#     - The SD card (lower layer) is mounted read-only — no write corruption
#     - A tmpfs RAM disk (upper layer) captures all writes during the session
#     - All writes are lost at power-off, but that's fine — we don't need
#       to persist anything between sessions
#
# Implementation:
#   Raspberry Pi OS uses a built-in overlayfs mechanism managed via the kernel
#   command line parameter: systemd.volatile=overlay
#   Combined with the Pi's initramfs, this is the cleanest approach.
#
#   We use raspi-config's noninteractive mode to enable it, which:
#     1. Adds the 'systemd.volatile=overlay' param to cmdline.txt
#     2. Sets up the boot-time overlayfs mount via init
# =============================================================================

echo "==> [04-carpi-readonly] Configuring read-only filesystem (overlayfs)"

# ---------------------------------------------------------------------------
# 1. Enable overlayfs via systemd.volatile kernel parameter
# ---------------------------------------------------------------------------
# We write directly to cmdline.txt instead of using raspi-config, which runs
# update-initramfs inside the chroot and leaves processes holding /sys busy —
# causing pi-gen's post-stage umount to fail and aborting image export.
#
# systemd.volatile=overlay is built into systemd — no extra package needed.
# At boot, systemd mounts a tmpfs overlay over the root filesystem so all
# writes go to RAM and are discarded on shutdown, protecting the SD card.

# Prefer /boot/firmware/ (bookworm+), fall back to /boot/ (legacy)
if [[ -f "${ROOTFS_DIR}/boot/firmware/cmdline.txt" ]]; then
    CMDLINE_FILE="${ROOTFS_DIR}/boot/firmware/cmdline.txt"
elif [[ -f "${ROOTFS_DIR}/boot/cmdline.txt" ]]; then
    CMDLINE_FILE="${ROOTFS_DIR}/boot/cmdline.txt"
fi

if [[ -f "${CMDLINE_FILE}" ]]; then
    CMDLINE=$(cat "${CMDLINE_FILE}" | tr -d '\n')
    if ! echo "${CMDLINE}" | grep -q "systemd.volatile"; then
        echo "${CMDLINE} systemd.volatile=overlay" > "${CMDLINE_FILE}"
    fi
    echo "overlayfs enabled via systemd.volatile=overlay in cmdline.txt"
else
    echo "WARNING: cmdline.txt not found — overlayfs not enabled"
    echo "Enable manually after first boot: sudo raspi-config -> Advanced -> Overlay FS"
fi

# ---------------------------------------------------------------------------
# 2. tmpfs mounts for directories that MUST be writable at runtime
# ---------------------------------------------------------------------------
# Even with the root overlayfs handling most writes, some services need
# specific writable paths. We mount tmpfs on these at boot via systemd.
#
# /tmp        — temporary files
# /var/log    — logs (lost on reboot, but journald keeps them in RAM anyway)
# /run        — runtime state (already tmpfs by default in systemd)
# /var/tmp    — persistent temp (we allow this to be RAM-backed too)

cat >> "${ROOTFS_DIR}/etc/fstab" << 'FSTAB'

# CarPi: tmpfs mounts for read-only root compatibility
# These directories need to be writable at runtime.
tmpfs   /tmp        tmpfs   defaults,noatime,nosuid,size=64m    0 0
tmpfs   /var/tmp    tmpfs   defaults,noatime,nosuid,size=32m    0 0
tmpfs   /var/log    tmpfs   defaults,noatime,nosuid,size=32m    0 0
FSTAB

# ---------------------------------------------------------------------------
# 3. Configure journald to use RAM (not disk) for logs
# ---------------------------------------------------------------------------
# With a read-only root, systemd-journald can't write to /var/log/journal
# on disk. Configure it to use volatile (RAM) storage instead.
install -d "${ROOTFS_DIR}/etc/systemd/journald.conf.d"
cat > "${ROOTFS_DIR}/etc/systemd/journald.conf.d/carpi-volatile.conf" << 'EOF'
[Journal]
# Store logs in RAM — lost on reboot, but that's acceptable for an embedded device.
# Increase RateLimitBurst to avoid dropping CarPi log messages.
Storage=volatile
RuntimeMaxUse=16M
RateLimitInterval=30s
RateLimitBurst=1000
EOF

# ---------------------------------------------------------------------------
# 4. Disable any services that write to disk unnecessarily
# ---------------------------------------------------------------------------
on_chroot << 'EOF'
# fake-hwclock writes the time to disk on shutdown to seed the clock at next boot.
# With read-only FS this write is lost anyway, so disable it.
systemctl disable fake-hwclock 2>/dev/null || true
systemctl mask fake-hwclock 2>/dev/null || true

# systemd-random-seed saves entropy to disk — not needed for our use case
systemctl disable systemd-random-seed 2>/dev/null || true
EOF

# ---------------------------------------------------------------------------
# 5. SSH host key persistence (optional)
# ---------------------------------------------------------------------------
# With a read-only root, SSH host keys regenerate on every boot (since
# /etc is in the RAM overlay). This causes "host key changed" warnings.
# For a production device with SSH disabled, this doesn't matter.
# If you enable SSH for development, uncomment the lines below to persist
# keys in a separate writable partition.

# install -m 644 files/ssh-keygen.service \
#     "${ROOTFS_DIR}/etc/systemd/system/ssh-keygen.service"
# on_chroot << 'EOF'
# systemctl enable ssh-keygen.service
# EOF

echo "==> [04-carpi-readonly] Read-only filesystem configured"
echo ""
echo "NOTE: The overlayfs is enabled. After flashing the image:"
echo "  - ALL changes made at runtime (file edits, etc.) are lost on reboot"
echo "  - To make permanent changes, disable overlayfs first:"
echo "      sudo raspi-config -> Advanced -> Overlay File System -> Disable"
echo "  - Then make changes and re-enable overlayfs"
