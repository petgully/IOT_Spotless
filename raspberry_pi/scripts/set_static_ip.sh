#!/usr/bin/env bash
# =============================================================================
# Project Spotless - Set Static IP (one-shot, re-runnable)
# =============================================================================
# Pins the Pi to a fixed IP so the ESP32 nodes (which target the broker IP)
# always find it. Works for the WIRED (default) or the WIFI connection, and
# automatically removes the same IP from the OTHER interface so you never end
# up with a duplicate-address conflict.
#
# Defaults match this booth: 192.168.1.20/24, gateway 192.168.1.254.
#
# Usage:
#   sudo bash set_static_ip.sh                 # WIRED (eth0)  -> 192.168.1.20
#   sudo bash set_static_ip.sh wifi            # WIFI  (wlan0) -> 192.168.1.20
#
#   # override any value via env vars:
#   sudo SPOTLESS_STATIC_IP=192.168.1.20 \
#        SPOTLESS_GATEWAY=192.168.1.254 \
#        SPOTLESS_DNS="192.168.1.254 8.8.8.8" \
#        bash set_static_ip.sh wired
#
# NOTE: re-activating the interface will briefly drop an SSH session that is
#       connected over that interface. Run it from the Pi console, or just
#       reconnect to the new IP afterwards.
# =============================================================================
set -euo pipefail

IP="${SPOTLESS_STATIC_IP:-192.168.1.20}"
PREFIX="${SPOTLESS_PREFIX:-24}"
GATEWAY="${SPOTLESS_GATEWAY:-192.168.1.254}"
DNS="${SPOTLESS_DNS:-192.168.1.254 8.8.8.8}"
TARGET="${1:-wired}"

if [[ "$(id -u)" -ne 0 ]]; then
    echo "Please run with sudo:  sudo bash $0 ${TARGET}"
    exit 1
fi

case "${TARGET,,}" in
    wired|eth|ethernet) DEVTYPE="ethernet"; LABEL="WIRED" ;;
    wifi|wlan|wireless) DEVTYPE="wifi";     LABEL="WIFI"  ;;
    *) echo "Usage: sudo bash $0 [wired|wifi]"; exit 1 ;;
esac

echo "=============================================="
echo "  Set static IP  ->  ${LABEL}"
echo "  IP:      ${IP}/${PREFIX}"
echo "  Gateway: ${GATEWAY}"
echo "  DNS:     ${DNS}"
echo "=============================================="

# 1) Find a device of the requested type.
DEV="$(nmcli -t -f DEVICE,TYPE device status | awk -F: -v t="$DEVTYPE" '$2==t{print $1; exit}')"
if [[ -z "${DEV}" ]]; then
    echo "ERROR: no ${DEVTYPE} device found."
    if [[ "${DEVTYPE}" == "ethernet" ]]; then
        echo "       Plug in the Ethernet cable and try again."
    else
        echo "       Enable WiFi (nmcli radio wifi on) and connect to your SSID first."
    fi
    exit 1
fi
echo "==> Device: ${DEV}"

# 2) Find the connection profile bound to that device (create one for wired
#    if none exists yet).
CON="$(nmcli -g GENERAL.CONNECTION device show "${DEV}" 2>/dev/null || true)"
if [[ -z "${CON}" || "${CON}" == "--" ]]; then
    if [[ "${DEVTYPE}" == "ethernet" ]]; then
        CON="Wired-Static"
        echo "==> No active profile on ${DEV}; creating '${CON}'"
        nmcli con add type ethernet ifname "${DEV}" con-name "${CON}" >/dev/null
    else
        echo "ERROR: no active WiFi profile on ${DEV}. Connect to your WiFi first, then re-run."
        exit 1
    fi
fi
echo "==> Connection: ${CON}"

# 3) Safety: if any OTHER connection currently holds this IP, drop it to DHCP
#    so we never have the same address on two interfaces.
while IFS=: read -r name dev; do
    [[ -z "${name}" || "${name}" == "${CON}" ]] && continue
    addrs="$(nmcli -g ipv4.addresses con show "${name}" 2>/dev/null || true)"
    if [[ "${addrs}" == *"${IP}/"* || "${addrs}" == *"${IP}"* ]]; then
        echo "==> Removing duplicate ${IP} from '${name}' (reverting it to DHCP)"
        nmcli con mod "${name}" ipv4.method auto ipv4.addresses "" ipv4.gateway "" || true
        nmcli con down "${name}" >/dev/null 2>&1 || true
        nmcli con up   "${name}" >/dev/null 2>&1 || true
    fi
done < <(nmcli -t -f NAME,DEVICE con show)

# 4) Apply the static configuration.
nmcli con mod "${CON}" \
    ipv4.method manual \
    ipv4.addresses "${IP}/${PREFIX}" \
    ipv4.gateway "${GATEWAY}" \
    ipv4.dns "${DNS}" \
    connection.autoconnect yes

echo "==> Re-activating '${CON}' (SSH on this interface may drop briefly)..."
nmcli con down "${CON}" >/dev/null 2>&1 || true
nmcli con up   "${CON}" >/dev/null

sleep 2
echo ""
echo "==> Done. Current addresses:"
hostname -I
echo "==> Default route:"
ip route | grep '^default' || true
echo ""
echo "Reconnect (if needed) via:  ssh spotless@${IP}"
