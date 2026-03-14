#!/bin/bash
# =============================================================================
# Project Spotless - Setup & Node Check Script
# =============================================================================
# Run this on the Raspberry Pi to:
#   1. Install & configure Mosquitto MQTT broker
#   2. Set up Python virtual environment + dependencies
#   3. Check if ESP32 nodes are connected and ready
#
# Usage:
#   chmod +x scripts/setup_and_check.sh
#   sudo ./scripts/setup_and_check.sh
#
# After setup completes, start kiosk with:
#   source venv/bin/activate
#   python3 main.py --kiosk
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
NODE_CHECK_TIMEOUT=15
EXPECTED_NODES=("spotless_node1" "spotless_node2" "spotless_node3")

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

print_header() {
    echo ""
    echo -e "${CYAN}==========================================${NC}"
    echo -e "${BOLD}  $1${NC}"
    echo -e "${CYAN}==========================================${NC}"
}

print_step() {
    echo -e "\n${BOLD}[$1/$TOTAL_STEPS]${NC} $2"
}

print_ok() {
    echo -e "  ${GREEN}✓${NC} $1"
}

print_warn() {
    echo -e "  ${YELLOW}⚠${NC} $1"
}

print_fail() {
    echo -e "  ${RED}✗${NC} $1"
}

print_info() {
    echo -e "  ${CYAN}→${NC} $1"
}

TOTAL_STEPS=5

# =============================================================================
print_header "Project Spotless - Setup & Check"
# =============================================================================

echo -e "  Raspberry Pi: $(hostname)"
echo -e "  IP Address:   $(hostname -I | awk '{print $1}')"
echo -e "  Date:         $(date)"
echo -e "  Project Dir:  $PROJECT_DIR"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
    echo ""
    echo -e "${RED}ERROR: Please run as root:${NC}"
    echo "  sudo ./scripts/setup_and_check.sh"
    exit 1
fi

# =============================================================================
# STEP 1: Install Mosquitto MQTT Broker
# =============================================================================
print_step 1 "Mosquitto MQTT Broker"

if command -v mosquitto &> /dev/null; then
    print_ok "Mosquitto is already installed"
else
    print_info "Installing Mosquitto..."
    apt-get update -qq
    apt-get install -y -qq mosquitto mosquitto-clients > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        print_ok "Mosquitto installed successfully"
    else
        print_fail "Failed to install Mosquitto"
        exit 1
    fi
fi

if ! dpkg -s mosquitto-clients &> /dev/null; then
    print_info "Installing Mosquitto clients..."
    apt-get install -y -qq mosquitto-clients > /dev/null 2>&1
fi

# Configure Mosquitto for anonymous access (ESP32 nodes need this)
MOSQUITTO_CONF="/etc/mosquitto/conf.d/spotless.conf"
if [ -f "$MOSQUITTO_CONF" ]; then
    print_ok "Mosquitto config already exists"
else
    print_info "Configuring Mosquitto for Spotless..."
    cat > "$MOSQUITTO_CONF" << 'EOF'
# Project Spotless MQTT Configuration
listener 1883
allow_anonymous true
EOF
    print_ok "Mosquitto configured (port 1883, anonymous access)"
fi

# Ensure Mosquitto is running and enabled
systemctl enable mosquitto > /dev/null 2>&1
systemctl restart mosquitto > /dev/null 2>&1
sleep 1

if systemctl is-active --quiet mosquitto; then
    print_ok "Mosquitto is running"
else
    print_fail "Mosquitto failed to start"
    echo "  Check logs: journalctl -u mosquitto -n 20"
    exit 1
fi

# Quick self-test
TEST_RESULT=$(mosquitto_pub -h localhost -t "spotless/test" -m "ping" 2>&1)
if [ $? -eq 0 ]; then
    print_ok "Mosquitto self-test passed (publish works)"
else
    print_fail "Mosquitto self-test failed: $TEST_RESULT"
fi

# =============================================================================
# STEP 2: Install System Dependencies
# =============================================================================
print_step 2 "System Dependencies"

PACKAGES_NEEDED=""
for pkg in python3-pip python3-venv python3-libgpiod; do
    if ! dpkg -s "$pkg" &> /dev/null 2>&1; then
        PACKAGES_NEEDED="$PACKAGES_NEEDED $pkg"
    fi
done

if [ -z "$PACKAGES_NEEDED" ]; then
    print_ok "All system packages already installed"
else
    print_info "Installing:$PACKAGES_NEEDED"
    apt-get install -y -qq $PACKAGES_NEEDED > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        print_ok "System packages installed"
    else
        print_warn "Some packages may have failed (non-critical)"
    fi
fi

# =============================================================================
# STEP 3: Python Virtual Environment & Dependencies
# =============================================================================
print_step 3 "Python Environment"

cd "$PROJECT_DIR"

if [ -d "venv" ]; then
    print_ok "Virtual environment already exists"
else
    print_info "Creating virtual environment..."
    python3 -m venv venv
    if [ $? -eq 0 ]; then
        print_ok "Virtual environment created"
    else
        print_fail "Failed to create virtual environment"
        exit 1
    fi
fi

# Activate and install dependencies
source venv/bin/activate

print_info "Installing Python dependencies..."
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt > /dev/null 2>&1
if [ $? -eq 0 ]; then
    print_ok "Python dependencies installed"
else
    print_warn "Some Python packages may have failed"
    print_info "Try manually: source venv/bin/activate && pip install -r requirements.txt"
fi

# Verify key imports
python3 -c "import paho.mqtt.client" 2>/dev/null && print_ok "paho-mqtt: OK" || print_fail "paho-mqtt: MISSING"
python3 -c "import flask" 2>/dev/null && print_ok "flask: OK" || print_fail "flask: MISSING"
python3 -c "import flask_socketio" 2>/dev/null && print_ok "flask-socketio: OK" || print_fail "flask-socketio: MISSING"
python3 -c "import pymysql" 2>/dev/null && print_ok "pymysql: OK" || print_warn "pymysql: MISSING (DB features disabled - OK for local testing)"

# gpiod is optional (only works on actual Pi hardware)
python3 -c "import gpiod" 2>/dev/null && print_ok "gpiod: OK" || print_warn "gpiod: MISSING (GPIO will be simulated)"

# =============================================================================
# STEP 4: Create Required Directories
# =============================================================================
print_step 4 "Directories & Permissions"

SPOTLESS_DIR="$HOME/.spotless"
mkdir -p "$SPOTLESS_DIR/logs"
mkdir -p "$SPOTLESS_DIR/sessions"
print_ok "Config directory: $SPOTLESS_DIR"
print_ok "Logs directory: $SPOTLESS_DIR/logs"
print_ok "Sessions directory: $SPOTLESS_DIR/sessions"

# =============================================================================
# STEP 5: Check ESP32 Node Connections
# =============================================================================
print_step 5 "ESP32 Node Connection Check"

PI_IP=$(hostname -I | awk '{print $1}')
print_info "Raspberry Pi IP: ${BOLD}$PI_IP${NC}"
print_info "ESP32 nodes should have MQTT_BROKER set to: ${BOLD}$PI_IP${NC}"
echo ""
print_info "Listening for ESP32 nodes for ${NODE_CHECK_TIMEOUT} seconds..."
print_info "(Make sure your ESP32s are powered on and on the same WiFi)"
echo ""

# Create a temp file for results
TEMP_FILE=$(mktemp)

# Subscribe to node status topics in the background
timeout "$NODE_CHECK_TIMEOUT" mosquitto_sub -h localhost -t "spotless/nodes/+/status" -C "${#EXPECTED_NODES[@]}" > "$TEMP_FILE" 2>/dev/null &
SUB_PID=$!

# Show a countdown
for i in $(seq "$NODE_CHECK_TIMEOUT" -1 1); do
    # Check if subscriber already got all messages
    if ! kill -0 $SUB_PID 2>/dev/null; then
        break
    fi
    printf "\r  Waiting... %2ds remaining " "$i"
    sleep 1
done
printf "\r                              \r"

# Kill subscriber if still running
kill $SUB_PID 2>/dev/null
wait $SUB_PID 2>/dev/null

# Parse results
NODES_FOUND=()
NODES_MISSING=()

for node in "${EXPECTED_NODES[@]}"; do
    if grep -q "$node" "$TEMP_FILE" 2>/dev/null; then
        NODE_IP=$(grep "$node" "$TEMP_FILE" | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        data = json.loads(line.strip())
        print(data.get('ip', 'unknown'))
        break
    except:
        pass
" 2>/dev/null)
        NODE_RSSI=$(grep "$node" "$TEMP_FILE" | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        data = json.loads(line.strip())
        print(data.get('rssi', 'N/A'))
        break
    except:
        pass
" 2>/dev/null)
        print_ok "$node: ${GREEN}ONLINE${NC}  (IP: $NODE_IP, WiFi: ${NODE_RSSI}dBm)"
        NODES_FOUND+=("$node")
    else
        print_fail "$node: ${RED}NOT FOUND${NC}"
        NODES_MISSING+=("$node")
    fi
done

rm -f "$TEMP_FILE"

# Also check if there's any retained status messages
echo ""
if [ ${#NODES_FOUND[@]} -eq ${#EXPECTED_NODES[@]} ]; then
    echo -e "  ${GREEN}${BOLD}All ${#EXPECTED_NODES[@]} nodes are ONLINE and ready!${NC}"
elif [ ${#NODES_FOUND[@]} -gt 0 ]; then
    echo -e "  ${YELLOW}${BOLD}${#NODES_FOUND[@]}/${#EXPECTED_NODES[@]} nodes found.${NC}"
    echo -e "  ${YELLOW}Missing nodes:${NC}"
    for node in "${NODES_MISSING[@]}"; do
        echo -e "    - $node"
    done
    echo ""
    echo -e "  ${CYAN}Troubleshooting tips for missing nodes:${NC}"
    echo "    1. Check ESP32 is powered on"
    echo "    2. Check WiFi credentials in config.h"
    echo "    3. Check MQTT_BROKER IP is set to: $PI_IP"
    echo "    4. Monitor ESP32 serial output (115200 baud)"
    echo "    5. Ensure WiFi is 2.4GHz (ESP32 doesn't support 5GHz)"
else
    echo -e "  ${RED}${BOLD}No nodes detected.${NC}"
    echo ""
    echo -e "  ${CYAN}This could mean:${NC}"
    echo "    - ESP32s are not powered on yet"
    echo "    - ESP32s haven't been flashed with the firmware"
    echo "    - WiFi credentials in config.h are incorrect"
    echo "    - MQTT_BROKER IP in config.h doesn't match: $PI_IP"
    echo ""
    echo -e "  ${CYAN}You can still start the kiosk without nodes connected.${NC}"
    echo "  Nodes can connect later and the system will detect them."
fi

# =============================================================================
# Summary
# =============================================================================
print_header "Setup Complete - Summary"

echo -e "  ${GREEN}✓${NC} Mosquitto MQTT:    Running on port 1883"
echo -e "  ${GREEN}✓${NC} Python venv:       $PROJECT_DIR/venv"
echo -e "  ${GREEN}✓${NC} Config dir:        ~/.spotless/"
echo -e "  ${GREEN}✓${NC} Raspberry Pi IP:   ${BOLD}$PI_IP${NC}"

if [ ${#NODES_FOUND[@]} -eq ${#EXPECTED_NODES[@]} ]; then
    echo -e "  ${GREEN}✓${NC} ESP32 Nodes:       All ${#EXPECTED_NODES[@]} ONLINE"
elif [ ${#NODES_FOUND[@]} -gt 0 ]; then
    echo -e "  ${YELLOW}⚠${NC} ESP32 Nodes:       ${#NODES_FOUND[@]}/${#EXPECTED_NODES[@]} online"
else
    echo -e "  ${YELLOW}⚠${NC} ESP32 Nodes:       None detected (can connect later)"
fi

echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  To start the kiosk, run:${NC}"
echo ""
echo -e "    cd $PROJECT_DIR"
echo -e "    source venv/bin/activate"
echo -e "    python3 main.py --kiosk"
echo ""
echo -e "  Then open: ${BOLD}http://$PI_IP:5000${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
