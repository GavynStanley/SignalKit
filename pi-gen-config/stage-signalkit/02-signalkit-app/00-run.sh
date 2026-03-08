#!/bin/bash -e
# =============================================================================
# 02-signalkit-app/00-run.sh
# =============================================================================
# Installs the SignalKit Python application into the image at /opt/signalkit.
#
# Uses /opt/signalkit (not /home/pi/signalkit) because:
#   - /opt is the conventional location for third-party applications on Linux
#   - It's outside the user home directory, so read-only overlayfs doesn't
#     affect it (the app files are part of the immutable lower layer)
#   - The systemd service runs as user 'pi' but from /opt/signalkit
# =============================================================================

echo "==> [02-signalkit-app] Installing SignalKit application"

SIGNALKIT_DEST="${ROOTFS_DIR}/opt/signalkit"
SIGNALKIT_REPO="https://github.com/GavynStanley/SignalKit.git"

# ---------------------------------------------------------------------------
# 1. Clone the SignalKit repo into the image (enables OTA updates via git pull)
# ---------------------------------------------------------------------------
install -d "${SIGNALKIT_DEST}"

# Try cloning the repo so the Pi has a .git directory for OTA updates.
# Fall back to copying source files if git clone fails (offline build).
if git clone --depth=1 "${SIGNALKIT_REPO}" "${SIGNALKIT_DEST}.tmp" 2>/dev/null; then
    # Move only the signalkit/ subdirectory contents into /opt/signalkit,
    # but keep .git at the repo root level so git pull works
    rm -rf "${SIGNALKIT_DEST}"
    mv "${SIGNALKIT_DEST}.tmp" "${SIGNALKIT_DEST}"
    echo "Cloned SignalKit repo from ${SIGNALKIT_REPO}"
else
    echo "Git clone failed (offline?) — falling back to file copy"
    # Replicate the repo layout: /opt/signalkit/ is the repo root,
    # /opt/signalkit/signalkit/ holds the app code, /opt/signalkit/VERSION, etc.
    REPO_ROOT="$(dirname "$(dirname "${STAGE_DIR}")")"
    APP_SRC="${REPO_ROOT}/signalkit"

    if [[ -d "${APP_SRC}" ]]; then
        install -d "${SIGNALKIT_DEST}/signalkit"
        cp -r "${APP_SRC}/." "${SIGNALKIT_DEST}/signalkit/"
        # Copy repo-root files (VERSION, etc.) if they exist
        [[ -f "${REPO_ROOT}/VERSION" ]] && cp "${REPO_ROOT}/VERSION" "${SIGNALKIT_DEST}/"
        echo "Copied SignalKit source from ${APP_SRC} -> ${SIGNALKIT_DEST}/signalkit/"
    else
        echo "ERROR: SignalKit source not found at ${APP_SRC} and git clone failed."
        echo "Cannot build image without application source."
        exit 1
    fi
    echo "WARNING: OTA updates will not work without a git repo"
fi

# Set ownership — app runs as pi user
on_chroot << 'EOF'
chown -R pi:pi /opt/signalkit
chmod +x /opt/signalkit/signalkit/main.py 2>/dev/null || chmod +x /opt/signalkit/main.py 2>/dev/null || true
EOF

echo "SignalKit installed to /opt/signalkit"

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
# explicitly create the signalkit log dir in case tmpfs isn't set up yet.
install -d -m 755 "${ROOTFS_DIR}/var/log/signalkit"
on_chroot << 'EOF'
chown pi:pi /var/log/signalkit
EOF

echo "==> [02-signalkit-app] Application install complete"
