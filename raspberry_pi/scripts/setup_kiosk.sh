#!/bin/bash
# =============================================================================
# Project Spotless — Kiosk Mode Setup Script
# =============================================================================
# Run this ONCE on the Raspberry Pi to set up auto-start:
#   1. Flask backend via systemd  (starts on boot)
#   2. Chromium browser in kiosk mode (fullscreen, no toolbar)
#
# Usage:  sudo bash setup_kiosk.sh
# =============================================================================

set -e

# --- Configuration ---
SPOTLESS_USER="${SUDO_USER:-spotless}"
SPOTLESS_HOME="/home/$SPOTLESS_USER"
PROJECT_DIR="$SPOTLESS_HOME/IOT_Spotless/raspberry_pi"
KIOSK_URL="http://localhost:5000"

echo "============================================="
echo "  Project Spotless — Kiosk Setup"
echo "============================================="
echo "  User:        $SPOTLESS_USER"
echo "  Project dir: $PROJECT_DIR"
echo "  Kiosk URL:   $KIOSK_URL"
echo ""

# --- Step 1: Install the systemd service ---
echo "[1/4] Installing spotless-kiosk systemd service..."
cp "$PROJECT_DIR/scripts/spotless-kiosk.service" /etc/systemd/system/spotless-kiosk.service

# Update paths if the user is different from 'spotless'
sed -i "s|User=spotless|User=$SPOTLESS_USER|g" /etc/systemd/system/spotless-kiosk.service
sed -i "s|Group=spotless|Group=$SPOTLESS_USER|g" /etc/systemd/system/spotless-kiosk.service
sed -i "s|/home/spotless|$SPOTLESS_HOME|g" /etc/systemd/system/spotless-kiosk.service

systemctl daemon-reload
systemctl enable spotless-kiosk.service
echo "  Done. Service enabled at boot."

# --- Step 2: Create Chromium kiosk autostart ---
echo ""
echo "[2/4] Setting up Chromium kiosk autostart..."

AUTOSTART_DIR="$SPOTLESS_HOME/.config/autostart"
mkdir -p "$AUTOSTART_DIR"

cat > "$AUTOSTART_DIR/spotless-browser.desktop" << DESKTOP_EOF
[Desktop Entry]
Type=Application
Name=Spotless Kiosk Browser
Comment=Open Spotless kiosk UI in fullscreen
Exec=bash -c 'sleep 8 && chromium-browser --kiosk --noerrdialogs --disable-infobars --disable-session-crashed-bubble --incognito $KIOSK_URL'
X-GNOME-Autostart-enabled=true
DESKTOP_EOF

chown "$SPOTLESS_USER:$SPOTLESS_USER" "$AUTOSTART_DIR/spotless-browser.desktop"
echo "  Done. Chromium will open fullscreen on login."

# --- Step 3: Disable screen blanking / screensaver ---
echo ""
echo "[3/4] Disabling screen blanking..."

LXSESSION_DIR="$SPOTLESS_HOME/.config/lxsession/LXDE-pi"
mkdir -p "$LXSESSION_DIR"

# Disable screensaver via xset in autostart
LXDE_AUTOSTART="$LXSESSION_DIR/autostart"
if [ ! -f "$LXDE_AUTOSTART" ]; then
    cat > "$LXDE_AUTOSTART" << LXDE_EOF
@lxpanel --profile LXDE-pi
@pcmanfm --desktop --profile LXDE-pi
@xset s off
@xset -dpms
@xset s noblank
LXDE_EOF
else
    # Append if not already present
    grep -q "xset s off" "$LXDE_AUTOSTART" || echo "@xset s off" >> "$LXDE_AUTOSTART"
    grep -q "xset -dpms" "$LXDE_AUTOSTART" || echo "@xset -dpms" >> "$LXDE_AUTOSTART"
    grep -q "xset s noblank" "$LXDE_AUTOSTART" || echo "@xset s noblank" >> "$LXDE_AUTOSTART"
fi

chown -R "$SPOTLESS_USER:$SPOTLESS_USER" "$LXSESSION_DIR"
echo "  Done. Screen will stay on permanently."

# --- Step 4: Enable auto-login (desktop) ---
echo ""
echo "[4/4] Enabling desktop auto-login..."

LIGHTDM_CONF="/etc/lightdm/lightdm.conf"
if [ -f "$LIGHTDM_CONF" ]; then
    sed -i "s/^#\?autologin-user=.*/autologin-user=$SPOTLESS_USER/" "$LIGHTDM_CONF"
    echo "  Done. Auto-login set for $SPOTLESS_USER."
else
    # Raspberry Pi OS Bookworm uses raspi-config for this
    raspi-config nonint do_boot_behaviour B4 2>/dev/null || true
    echo "  Done (via raspi-config)."
fi

echo ""
echo "============================================="
echo "  Kiosk setup complete!"
echo ""
echo "  On next reboot:"
echo "    1. spotless-kiosk.service starts Flask on :5000"
echo "    2. Chromium opens $KIOSK_URL fullscreen"
echo "    3. Screen never blanks"
echo ""
echo "  Manual controls:"
echo "    sudo systemctl start spotless-kiosk"
echo "    sudo systemctl stop spotless-kiosk"
echo "    sudo systemctl status spotless-kiosk"
echo "    journalctl -u spotless-kiosk -f    (live logs)"
echo ""
echo "  To EXIT kiosk browser: Alt+F4"
echo "  To DISABLE kiosk mode:"
echo "    sudo systemctl disable spotless-kiosk"
echo "    rm $AUTOSTART_DIR/spotless-browser.desktop"
echo "============================================="
