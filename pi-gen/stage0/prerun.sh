#!/bin/bash -e

# CarPi uses bookworm (stable). Upstream pi-gen master targets trixie.

if [ ! -d "${ROOTFS_DIR}" ]; then
	bootstrap ${RELEASE} "${ROOTFS_DIR}" http://raspbian.raspberrypi.com/raspbian/
fi
