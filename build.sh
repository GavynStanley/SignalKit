#!/usr/bin/env bash
# =============================================================================
# build.sh — CarPi OS Image Builder
# =============================================================================
# Builds a flashable .img file using pi-gen, the official Raspberry Pi OS
# build tool. The output is a complete OS image with CarPi pre-installed —
# just flash it to an SD card and put it in the Pi.
#
# Requirements:
#   - Linux host (Ubuntu/Debian recommended; Docker works too)
#   - ~8GB free disk space
#   - Internet access (downloads base Raspberry Pi OS packages)
#   - sudo / root access (pi-gen uses chroot)
#   - For Docker builds: Docker installed
#
# Usage:
#   ./build.sh              # Native Linux build
#   ./build.sh --docker     # Docker-based build (works on macOS too)
#   ./build.sh --clean      # Clean previous build artifacts first
#
# Output: deploy/CarPi-YYYY-MM-DD.img.zip
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIGEN_DIR="${SCRIPT_DIR}/pi-gen"
CONFIG="${SCRIPT_DIR}/pi-gen-config/config"
STAGE_DIR="${SCRIPT_DIR}/pi-gen-config/stage-carpi"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${GREEN}[build]${NC} $*"; }
warn() { echo -e "${YELLOW}[build]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
step() { echo -e "\n${BLUE}==> $*${NC}"; }

USE_DOCKER=0
CLEAN=0
CLEAN_CARPI=0

# Parse arguments
for arg in "$@"; do
    case "$arg" in
        --docker)      USE_DOCKER=1 ;;
        --clean)       CLEAN=1 ;;
        --clean-carpi) CLEAN_CARPI=1 ;;
        --help|-h)
            echo "Usage: $0 [--docker] [--clean] [--clean-carpi]"
            echo "  --docker       Build inside Docker (required on macOS/Windows)"
            echo "  --clean        Remove ALL build artifacts (full rebuild)"
            echo "  --clean-carpi  Re-run only stage-carpi (keeps stages 0-2 cached)"
            exit 0
            ;;
        *) err "Unknown argument: $arg" ;;
    esac
done

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

step "Pre-flight checks"

# Check config file exists
[[ -f "${CONFIG}" ]] || err "Config not found: ${CONFIG}"

# Check CarPi source exists
CARPI_SRC="${SCRIPT_DIR}/carpi"
[[ -d "${CARPI_SRC}" ]] || err "CarPi source not found: ${CARPI_SRC}"

# Check OBD_MAC is set (not the placeholder)
OBD_MAC=$(grep "^OBD_MAC" "${CARPI_SRC}/config.py" | cut -d'"' -f2)
if [[ "${OBD_MAC}" == "AA:BB:CC:DD:EE:FF" ]]; then
    warn "============================================================"
    warn "OBD_MAC in carpi/config.py is still the placeholder value!"
    warn "The image will build, but OBD2 connection won't work until"
    warn "you set the correct MAC address."
    warn "Either:"
    warn "  1. Edit carpi/config.py now, then rebuild"
    warn "  2. Or set it after flashing (requires disabling overlayfs)"
    warn "============================================================"
    sleep 3
fi

# Check the build directory is not on a noexec filesystem (e.g. a NAS mount).
# pi-gen runs chroot + execve inside the work directory — this fails silently
# on noexec mounts, producing confusing "Unable to execute target architecture"
# errors throughout the entire build log.
BUILD_MOUNT=$(df -P "${SCRIPT_DIR}" 2>/dev/null | tail -1 | awk '{print $6}')
if mount | grep -E " ${BUILD_MOUNT} " | grep -q noexec; then
    err "Build directory is on a noexec filesystem (mount: ${BUILD_MOUNT})."
    err "This is common with NAS/network mounts. pi-gen cannot build here."
    err ""
    err "Copy the project to local storage and retry:"
    err "  cp -r \"${SCRIPT_DIR}\" \"\${HOME}/car-pi\""
    err "  cd \"\${HOME}/car-pi\""
    err "  ./build.sh"
fi

if [[ ${USE_DOCKER} -eq 0 ]]; then
    # Native build requires Linux
    [[ "$(uname -s)" == "Linux" ]] || err \
        "Native build requires Linux. Use --docker for macOS/Windows."
    # Require sudo
    command -v sudo &>/dev/null || err "sudo is required for native builds"
fi

log "All pre-flight checks passed"

# ---------------------------------------------------------------------------
# Clone or update pi-gen
# ---------------------------------------------------------------------------

step "Setting up pi-gen"

PI_GEN_REPO="https://github.com/RPi-Distro/pi-gen.git"
# master branch builds armhf (32-bit) and runs natively on x86_64 Ubuntu/Debian.
# Pi Zero 2 W runs 32-bit Raspberry Pi OS Lite perfectly well.
PI_GEN_BRANCH="master"

if [[ -d "${PIGEN_DIR}" ]]; then
    log "pi-gen already cloned — pulling latest"
    sudo git -C "${PIGEN_DIR}" fetch origin
    sudo git -C "${PIGEN_DIR}" checkout "${PI_GEN_BRANCH}"
    sudo git -C "${PIGEN_DIR}" pull --ff-only || warn "git pull failed (offline?), using existing clone"
else
    log "Cloning pi-gen from ${PI_GEN_REPO} (branch: ${PI_GEN_BRANCH})"
    sudo git clone --depth=1 --branch "${PI_GEN_BRANCH}" "${PI_GEN_REPO}" "${PIGEN_DIR}"
fi

# ---------------------------------------------------------------------------
# Link our custom stage into pi-gen
# ---------------------------------------------------------------------------

step "Linking custom stage"

PIGEN_STAGE_LINK="${PIGEN_DIR}/stage-carpi"

if [[ ${USE_DOCKER} -eq 1 ]]; then
    # Docker build: copy files into pi-gen directory so Docker COPY picks them up.
    # Symlinks pointing outside the build context are silently ignored by Docker.
    sudo rm -rf "${PIGEN_STAGE_LINK}"
    sudo cp -r "${STAGE_DIR}" "${PIGEN_STAGE_LINK}"
    sudo cp "${CONFIG}" "${PIGEN_DIR}/config"
    log "Copied stage-carpi and config into pi-gen (Docker build)"
else
    # Native build: symlink is fine since chroot can follow it.
    if [[ -L "${PIGEN_STAGE_LINK}" ]]; then
        sudo rm "${PIGEN_STAGE_LINK}"
    fi
    sudo ln -sf "${STAGE_DIR}" "${PIGEN_STAGE_LINK}"
    log "Linked: ${PIGEN_STAGE_LINK} -> ${STAGE_DIR}"
fi

# Ensure all stage run scripts are executable.
# File permissions may not survive scp/zip transfers between machines.
sudo find "${STAGE_DIR}" -name "*.sh" -exec chmod +x {} \;
sudo find "${PIGEN_STAGE_LINK}" -name "*.sh" -exec chmod +x {} \;
log "Stage scripts marked executable"

# Mark stages we don't want as SKIP
# pi-gen builds all stages in STAGE_LIST; stages 3-5 add desktop, apps, etc.
for SKIP_STAGE in stage3 stage4 stage5; do
    SKIP_FILE="${PIGEN_DIR}/${SKIP_STAGE}/SKIP"
    if [[ -d "${PIGEN_DIR}/${SKIP_STAGE}" ]] && [[ ! -f "${SKIP_FILE}" ]]; then
        sudo touch "${SKIP_FILE}"
        log "Marked ${SKIP_STAGE} as SKIP (no desktop/apps needed)"
    fi
done

# Don't generate intermediate images for stages 0-2 (saves time and disk)
for NO_IMG_STAGE in stage0 stage1 stage2; do
    SKIP_IMG="${PIGEN_DIR}/${NO_IMG_STAGE}/SKIP_IMAGES"
    if [[ -d "${PIGEN_DIR}/${NO_IMG_STAGE}" ]] && [[ ! -f "${SKIP_IMG}" ]]; then
        sudo touch "${SKIP_IMG}"
    fi
done

# ---------------------------------------------------------------------------
# Clean previous build (optional)
# ---------------------------------------------------------------------------

if [[ ${CLEAN} -eq 1 ]]; then
    step "Cleaning ALL build artifacts (full rebuild)"
    sudo rm -rf "${PIGEN_DIR}/work" "${PIGEN_DIR}/deploy"
    log "Cleaned"
elif [[ ${CLEAN_CARPI} -eq 1 ]]; then
    step "Cleaning stage-carpi only (stages 0-2 cached)"
    sudo rm -f "${PIGEN_DIR}/work/stage-carpi/SKIP"
    sudo rm -f "${PIGEN_DIR}/work/export-image/SKIP"
    sudo rm -rf "${PIGEN_DIR}/deploy"
    log "Removed stage-carpi + export-image SKIP markers — both will re-run"
fi

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

step "Starting pi-gen build"
log "This will take 20-60 minutes depending on your machine."
log "Downloading Debian packages + building the full OS image."
echo ""

BUILD_START=$(date +%s)

if [[ ${USE_DOCKER} -eq 1 ]]; then
    # Docker build — works on macOS and Linux
    log "Using Docker build"
    command -v docker &>/dev/null || err "Docker not found. Install Docker first."

    cd "${PIGEN_DIR}"
    sudo bash build-docker.sh
else
    # Native build — faster, requires Linux + sudo
    log "Using native build (Linux)"

    # Install pi-gen dependencies if not present
    if ! dpkg -l coreutils quilt parted qemu-user-static qemu-user-binfmt \
        debootstrap zerofree zip dosfstools libarchive-tools libcap2-bin \
        grep rsync xz-utils pigz arch-test \
        &>/dev/null 2>&1; then
        log "Installing pi-gen build dependencies..."
        sudo apt-get update -qq
        sudo apt-get install -y \
            coreutils quilt parted \
            qemu-user-static qemu-user-binfmt \
            debootstrap zerofree \
            zip dosfstools libarchive-tools libcap2-bin \
            grep rsync xz-utils pigz arch-test \
            --no-install-recommends
    fi

    cd "${PIGEN_DIR}"
    sudo bash build.sh -c "${CONFIG}"
fi

BUILD_END=$(date +%s)
BUILD_MINS=$(( (BUILD_END - BUILD_START) / 60 ))

# ---------------------------------------------------------------------------
# Collect output
# ---------------------------------------------------------------------------

step "Build complete"

DEPLOY_DIR="${PIGEN_DIR}/deploy"
OUTPUT_DIR="${SCRIPT_DIR}/deploy"
sudo mkdir -p "${OUTPUT_DIR}"

# Find the generated image(s) and copy to our deploy/ directory
IMAGES=$(find "${DEPLOY_DIR}" -name "*.zip" -o -name "*.img" 2>/dev/null | sort)

if [[ -z "${IMAGES}" ]]; then
    err "No image found in ${DEPLOY_DIR} — build may have failed"
fi

for IMG in ${IMAGES}; do
    cp "${IMG}" "${OUTPUT_DIR}/"
    log "Output: ${OUTPUT_DIR}/$(basename "${IMG}")"
done

echo ""
log "============================================================"
log "BUILD SUCCESSFUL (${BUILD_MINS} minutes)"
log "============================================================"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo ""
echo "  1. Flash the image to a microSD card:"
echo "     Using Raspberry Pi Imager:"
echo "       Open Imager -> Choose OS -> Use Custom -> select the .img.zip"
echo "     Or using dd (Linux):"
echo "       unzip -p deploy/CarPi-*.img.zip | sudo dd of=/dev/sdX bs=4M status=progress"
echo ""
echo "  2. Insert SD card into Pi Zero 2 W and power on."
echo "     Dashboard appears in ~15 seconds."
echo ""
echo "  3. Connect to 'CarPi' WiFi (password: carpi1234) and open http://192.168.4.1:8080"
echo ""
if [[ "${OBD_MAC}" == "AA:BB:CC:DD:EE:FF" ]]; then
    echo -e "  ${YELLOW}4. Set your OBD2 MAC address:${NC}"
    echo "     The image was built with the placeholder MAC address."
    echo "     To fix without rebuilding:"
    echo "       a. SSH into Pi (enable SSH first via raspi-config)"
    echo "       b. sudo raspi-config -> Advanced -> Overlay FS -> Disable"
    echo "       c. nano /opt/carpi/config.py  (set OBD_MAC)"
    echo "       d. sudo raspi-config -> Advanced -> Overlay FS -> Enable"
    echo "       e. sudo reboot"
    echo ""
fi
