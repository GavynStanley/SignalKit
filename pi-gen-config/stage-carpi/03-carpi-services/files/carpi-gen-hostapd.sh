#!/bin/bash
# =============================================================================
# carpi-gen-hostapd.sh — Generate hostapd.conf from CarPi config.py
# =============================================================================
# Called by carpi-wifi.service on each boot to regenerate hostapd.conf
# from the SSID/password in config.py. This allows users to change WiFi
# settings by editing config.py without touching hostapd.conf directly.
# =============================================================================

CONF="/etc/hostapd/hostapd.conf"

# Read SSID and password from config.py
SSID=$(python3 -c "
import sys
sys.path.insert(0, '/opt/carpi/carpi')
import config
print(config.HOTSPOT_SSID)
" 2>/dev/null)

PASS=$(python3 -c "
import sys
sys.path.insert(0, '/opt/carpi/carpi')
import config
print(config.HOTSPOT_PASSWORD)
" 2>/dev/null)

# Fall back to defaults if config.py is missing or broken
SSID="${SSID:-CarPi}"
PASS="${PASS:-carpi1234}"

# Write hostapd.conf
cat > "$CONF" << EOF
interface=wlan0
driver=nl80211
ssid=${SSID}
hw_mode=g
channel=6
ignore_broadcast_ssid=0
wmm_enabled=0
macaddr_acl=0
EOF

if [ -n "$PASS" ] && [ ${#PASS} -ge 8 ]; then
    cat >> "$CONF" << EOF
auth_algs=1
wpa=2
wpa_passphrase=${PASS}
wpa_key_mgmt=WPA-PSK
wpa_pairwise=TKIP
rsn_pairwise=CCMP
EOF
    echo "WiFi secured with WPA2 (SSID: ${SSID})"
else
    echo "auth_algs=1" >> "$CONF"
    echo "WiFi open (SSID: ${SSID})"
fi
