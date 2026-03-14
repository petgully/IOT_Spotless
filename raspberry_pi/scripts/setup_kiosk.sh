#!/bin/bash
# =============================================================================
# Petgully Spotless - Kiosk Setup Script
# =============================================================================
# Run this script once to set up the Raspberry Pi for kiosk mode
#
# Usage:
#   sudo ./setup_kiosk.sh
# =============================================================================

set -e

echo "==========================================="
echo "  Petgully Spotless - Kiosk Setup"
echo "==========================================="

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo "Please run as root (sudo ./setup_kiosk.sh)"
    exit 1
fi

# Update system
echo "Updating system packages..."
apt-get update
apt-get upgrade -y

# Install required packages
echo "Installing required packages..."
apt-get install -y \
    python3-pip \
    python3-venv \
    chromium-browser \
    unclutter \
    xdotool \
    mosquitto \
    mosquitto-clients \
    git

# Install Python packages
echo "Installing Python dependencies..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"
pip3 install -r requirements.txt

# Create spotless user if doesn't exist
if ! id "spotless" &>/dev/null; then
    echo "Creating spotless user..."
    useradd -m -s /bin/bash spotless
    usermod -aG gpio,i2c,spi spotless
fi

# Create spotless directories
echo "Creating directories..."
mkdir -p /home/spotless/.spotless/logs
mkdir -p /home/spotless/.spotless/sessions
chown -R spotless:spotless /home/spotless/.spotless

# Set up auto-login (optional)
echo "Setting up auto-login..."
mkdir -p /etc/systemd/system/getty@tty1.service.d
cat > /etc/systemd/system/getty@tty1.service.d/autologin.conf << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin spotless --noclear %I \$TERM
EOF

# Set up autostart for desktop
echo "Setting up kiosk autostart..."
AUTOSTART_DIR="/home/spotless/.config/lxsession/LXDE-pi"
mkdir -p "$AUTOSTART_DIR"
cat > "$AUTOSTART_DIR/autostart" << EOF
@lxpanel --profile LXDE-pi
@pcmanfm --desktop --profile LXDE-pi
@xset s off
@xset -dpms
@xset s noblank
@bash $PROJECT_DIR/scripts/start_kiosk.sh
EOF
chown -R spotless:spotless /home/spotless/.config

# Disable screen blanking in lightdm
if [ -f /etc/lightdm/lightdm.conf ]; then
    echo "Configuring lightdm..."
    sed -i 's/#xserver-command=X/xserver-command=X -s 0 dpms/' /etc/lightdm/lightdm.conf
fi

# Set up systemd service
echo "Installing systemd service..."
cp "$PROJECT_DIR/scripts/spotless.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable spotless

# Configure Mosquitto (MQTT broker)
echo "Configuring Mosquitto MQTT broker..."
cat > /etc/mosquitto/conf.d/spotless.conf << EOF
listener 1883
allow_anonymous true
EOF
systemctl restart mosquitto
systemctl enable mosquitto

echo ""
echo "==========================================="
echo "  Setup Complete!"
echo "==========================================="
echo ""
echo "Please reboot the system to apply changes:"
echo "  sudo reboot"
echo ""
echo "The kiosk will start automatically after reboot."
echo ""
