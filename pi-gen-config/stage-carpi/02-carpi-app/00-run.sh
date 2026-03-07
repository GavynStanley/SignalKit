#!/bin/bash -e
# =============================================================================
# 02-carpi-app/00-run.sh
# =============================================================================
# Installs the CarPi Python application into the image at /opt/carpi.
#
# Uses /opt/carpi (not /home/pi/carpi) because:
#   - /opt is the conventional location for third-party applications on Linux
#   - It's outside the user home directory, so read-only overlayfs doesn't
#     affect it (the app files are part of the immutable lower layer)
#   - The systemd service runs as user 'pi' but from /opt/carpi
# =============================================================================

echo "==> [02-carpi-app] Installing CarPi application"

CARPI_DEST="${ROOTFS_DIR}/opt/carpi"
CARPI_REPO="https://github.com/GavynStanley/CarPi.git"

# ---------------------------------------------------------------------------
# 1. Clone the CarPi repo into the image (enables OTA updates via git pull)
# ---------------------------------------------------------------------------
install -d "${CARPI_DEST}"

# Try cloning the repo so the Pi has a .git directory for OTA updates.
# Fall back to copying source files if git clone fails (offline build).
if git clone --depth=1 "${CARPI_REPO}" "${CARPI_DEST}.tmp" 2>/dev/null; then
    # Move only the carpi/ subdirectory contents into /opt/carpi,
    # but keep .git at the repo root level so git pull works
    rm -rf "${CARPI_DEST}"
    mv "${CARPI_DEST}.tmp" "${CARPI_DEST}"
    echo "Cloned CarPi repo from ${CARPI_REPO}"
else
    echo "Git clone failed (offline?) — falling back to file copy"
    # Replicate the repo layout: /opt/carpi/ is the repo root,
    # /opt/carpi/carpi/ holds the app code, /opt/carpi/VERSION, etc.
    REPO_ROOT="$(dirname "$(dirname "${STAGE_DIR}")")"
    APP_SRC="${REPO_ROOT}/carpi"

    if [[ -d "${APP_SRC}" ]]; then
        install -d "${CARPI_DEST}/carpi"
        cp -r "${APP_SRC}/." "${CARPI_DEST}/carpi/"
        # Copy repo-root files (VERSION, etc.) if they exist
        [[ -f "${REPO_ROOT}/VERSION" ]] && cp "${REPO_ROOT}/VERSION" "${CARPI_DEST}/"
        echo "Copied CarPi source from ${APP_SRC} -> ${CARPI_DEST}/carpi/"
    else
        install -d "${CARPI_DEST}/carpi"
        cp -r files/carpi/. "${CARPI_DEST}/carpi/"
        echo "Copied CarPi source from stage files/ -> ${CARPI_DEST}/carpi/"
    fi
    echo "WARNING: OTA updates will not work without a git repo"
fi

# Set ownership — app runs as pi user
on_chroot << 'EOF'
chown -R pi:pi /opt/carpi
chmod +x /opt/carpi/carpi/main.py 2>/dev/null || chmod +x /opt/carpi/main.py 2>/dev/null || true
EOF

echo "CarPi installed to /opt/carpi"

# ---------------------------------------------------------------------------
# 2. Install Python dependencies
# ---------------------------------------------------------------------------
# python-obd and flask are not in Debian apt, so we install via pip.
# We install system-wide (not per-user virtualenv) because the systemd
# service runs as user 'pi' but needs access to these packages.
on_chroot << 'EOF'
echo "Installing Python packages: obd flask pywebview"
python3 -m pip install --break-system-packages obd flask pywebview 2>/dev/null \
    || python3 -m pip install obd flask pywebview

echo "Python packages installed:"
python3 -m pip show obd flask pywebview | grep -E "^(Name|Version):"
EOF

# ---------------------------------------------------------------------------
# 3. Create a log directory that survives the read-only root
# ---------------------------------------------------------------------------
# /var/log is writable (it's tmpfs in our read-only setup), but we
# explicitly create the carpi log dir in case tmpfs isn't set up yet.
install -d -m 755 "${ROOTFS_DIR}/var/log/carpi"
on_chroot << 'EOF'
chown pi:pi /var/log/carpi
EOF

echo "==> [02-carpi-app] Application install complete"
