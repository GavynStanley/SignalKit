#!/usr/bin/env bash
# =============================================================================
# build.sh — SignalKit OS Image Builder
# =============================================================================
# Builds a flashable .img file using a vendored copy of pi-gen (in ./pi-gen/).
# No internet clone step — pi-gen is part of this repo with trimmed packages.
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
# Output: deploy/SignalKit-YYYY-MM-DD.img.zip
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIGEN_DIR="${SCRIPT_DIR}/pi-gen"
CONFIG="${SCRIPT_DIR}/pi-gen-signalkit/config"
STAGE_DIR="${SCRIPT_DIR}/pi-gen-signalkit/stage-signalkit"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${GREEN}[build]${NC} $*"; }
warn() { echo -e "${YELLOW}[build]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*"; exit 1; }
step() { echo -e "\n${BLUE}==> $*${NC}"; }

USE_DOCKER=0
CLEAN=0
CLEAN_SIGNALKIT=0

# Parse arguments
for arg in "$@"; do
    case "$arg" in
        --docker)          USE_DOCKER=1 ;;
        --clean)           CLEAN=1 ;;
        --clean-signalkit) CLEAN_SIGNALKIT=1 ;;
        --help|-h)
            echo "Usage: $0 [--docker] [--clean] [--clean-signalkit]"
            echo "  --docker           Build inside Docker (required on macOS/Windows)"
            echo "  --clean            Remove ALL build artifacts (full rebuild)"
            echo "  --clean-signalkit  Re-run only stage-signalkit (keeps stages 0-2 cached)"
            exit 0
            ;;
        *) err "Unknown argument: $arg" ;;
    esac
done

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

step "Pre-flight checks"

# Check vendored pi-gen exists — clone if missing
if [[ ! -d "${PIGEN_DIR}" ]] || [[ ! -f "${PIGEN_DIR}/build.sh" ]]; then
    log "pi-gen not found — cloning from GitHub..."
    git clone --depth=1 https://github.com/RPi-Distro/pi-gen.git "${PIGEN_DIR}"
fi

# Check config file exists
[[ -f "${CONFIG}" ]] || err "Config not found: ${CONFIG}"

# Check SignalKit source exists
SIGNALKIT_SRC="${SCRIPT_DIR}/signalkit"
[[ -d "${SIGNALKIT_SRC}" ]] || err "SignalKit source not found: ${SIGNALKIT_SRC}"


# Check the build directory is not on a noexec filesystem
BUILD_MOUNT=$(df -P "${SCRIPT_DIR}" 2>/dev/null | tail -1 | awk '{print $6}')
if mount | grep -E " ${BUILD_MOUNT} " | grep -q noexec; then
    err "Build directory is on a noexec filesystem (mount: ${BUILD_MOUNT})." \
        "Copy the project to local storage and retry."
fi

if [[ ${USE_DOCKER} -eq 0 ]]; then
    [[ "$(uname -s)" == "Linux" ]] || err \
        "Native build requires Linux. Use --docker for macOS/Windows."
    command -v sudo &>/dev/null || err "sudo is required for native builds"
fi

log "All pre-flight checks passed"

# ---------------------------------------------------------------------------
# Link our custom stage into pi-gen
# ---------------------------------------------------------------------------

step "Linking custom stage"

PIGEN_STAGE_LINK="${PIGEN_DIR}/stage-signalkit"

if [[ ${USE_DOCKER} -eq 1 ]]; then
    # Docker build: copy files so Docker COPY picks them up
    sudo rm -rf "${PIGEN_STAGE_LINK}"
    sudo cp -r "${STAGE_DIR}" "${PIGEN_STAGE_LINK}"
    sudo cp "${CONFIG}" "${PIGEN_DIR}/config"
    log "Copied stage-signalkit and config into pi-gen (Docker build)"
else
    # Native build: symlink is fine
    if [[ -L "${PIGEN_STAGE_LINK}" ]]; then
        sudo rm "${PIGEN_STAGE_LINK}"
    elif [[ -d "${PIGEN_STAGE_LINK}" ]]; then
        sudo rm -rf "${PIGEN_STAGE_LINK}"
    fi
    sudo ln -sf "${STAGE_DIR}" "${PIGEN_STAGE_LINK}"
    # Also copy config into pi-gen dir so it's found as the default config
    # (belt-and-suspenders with the -c flag)
    sudo cp "${CONFIG}" "${PIGEN_DIR}/config"
    log "Linked: ${PIGEN_STAGE_LINK} -> ${STAGE_DIR}"
fi

# Ensure all stage run scripts are executable
sudo find "${STAGE_DIR}" -name "*.sh" -exec chmod +x {} \;
sudo find "${PIGEN_STAGE_LINK}" -name "*.sh" -exec chmod +x {} \;
log "Stage scripts marked executable"

# Skip intermediate images for stages 0-2 (saves time and disk)
for NO_IMG_STAGE in stage0 stage1 stage2; do
    SKIP_IMG="${PIGEN_DIR}/${NO_IMG_STAGE}/SKIP_IMAGES"
    if [[ -d "${PIGEN_DIR}/${NO_IMG_STAGE}" ]] && [[ ! -f "${SKIP_IMG}" ]]; then
        touch "${SKIP_IMG}"
    fi
done

# ---------------------------------------------------------------------------
# Clean previous build (optional)
# ---------------------------------------------------------------------------

if [[ ${CLEAN} -eq 1 ]]; then
    step "Cleaning ALL build artifacts (full rebuild)"
    sudo rm -rf "${PIGEN_DIR}/work" "${PIGEN_DIR}/deploy"
    log "Cleaned"
elif [[ ${CLEAN_SIGNALKIT} -eq 1 ]]; then
    step "Cleaning stage-signalkit only (stages 0-2 cached)"
    sudo rm -f "${PIGEN_DIR}/work/stage-signalkit/SKIP"
    sudo rm -f "${PIGEN_DIR}/work/export-image/SKIP"
    sudo rm -rf "${PIGEN_DIR}/deploy"
    log "Removed stage-signalkit + export-image SKIP markers — both will re-run"
fi

# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

step "Starting pi-gen build"
log "This will take 20-60 minutes depending on your machine."
log "Downloading Debian packages + building the full OS image."
echo ""

# ---------------------------------------------------------------------------
# Build output filter — suppress noisy package download/install logs.
# Shows: stage transitions, errors, our echo statements, and key milestones.
# Full log is always saved to build.log for troubleshooting.
# ---------------------------------------------------------------------------
BUILD_LOG="${SCRIPT_DIR}/build.log"
: > "${BUILD_LOG}"

# Filter function: only print lines that matter
_build_filter() {
    while IFS= read -r line; do
        echo "${line}" >> "${BUILD_LOG}"
        # Always show these patterns
        case "${line}" in
            *"==> ["*|*"[stage"*|*"Begin "*|*"End "*|*"SKIP"*|\
            *"error"*|*"Error"*|*"ERROR"*|*"FATAL"*|*"FAIL"*|\
            *"WARNING"*|*"warning:"*|\
            *"==> "*|*"[build]"*|\
            *"export-image"*|*"Compressing"*|*"compress"*|\
            *"Image"*|*".img"*|*".zip"*|\
            *"installed"*|*"done"*|*"Done"*|*"complete"*|*"Complete"*|\
            *"Removing"*|*"cleanup"*|*"Package cleanup"*|\
            *"systemctl"*|*"enable"*|*"disable"*|\
            *"rename"*|*"User rename"*|\
            *"overlayfs"*|*"overlay"*|\
            *"Running stage"*|*"Skipping stage"*|\
            *"mount"*|*"umount"*)
                log "${line}"
                ;;
        esac
    done
}

BUILD_START=$(date +%s)

if [[ ${USE_DOCKER} -eq 1 ]]; then
    log "Using Docker build"
    command -v docker &>/dev/null || err "Docker not found. Install Docker first."

    cd "${PIGEN_DIR}"
    sudo bash build-docker.sh 2>&1 | _build_filter
    BUILD_EXIT=${PIPESTATUS[0]}
else
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
    sudo bash build.sh -c "${CONFIG}" 2>&1 | _build_filter
    BUILD_EXIT=${PIPESTATUS[0]}
fi

[[ ${BUILD_EXIT} -ne 0 ]] && err "Build failed (exit code ${BUILD_EXIT}). Full log: ${BUILD_LOG}"

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
echo "       unzip -p deploy/SignalKit-*.img.zip | sudo dd of=/dev/sdX bs=4M status=progress"
echo ""
echo "  2. Insert SD card into Pi Zero 2 W and power on."
echo "     Dashboard appears in ~15 seconds."
echo ""
echo "  3. Connect to 'SignalKit' WiFi (password: signalkit1234) and open http://192.168.4.1:8080"
echo ""
