#!/bin/bash
# =============================================================================
# Project Spotless - Quick ESP32 Node Check
# =============================================================================
# Quickly checks if ESP32 nodes are connected to the MQTT broker.
# No sudo needed. Run anytime to verify node status.
#
# Usage:
#   ./scripts/check_nodes.sh          # Default 10s timeout
#   ./scripts/check_nodes.sh 30       # Custom timeout (30s)
# =============================================================================

TIMEOUT=${1:-10}
EXPECTED_NODES=("spotless_node1" "spotless_node2" "spotless_node3")

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

PI_IP=$(hostname -I 2>/dev/null | awk '{print $1}')

echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BOLD}  Spotless - ESP32 Node Check${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "  Pi IP: ${BOLD}${PI_IP:-unknown}${NC}"
echo ""

# Check if Mosquitto is running
if ! systemctl is-active --quiet mosquitto 2>/dev/null; then
    echo -e "  ${RED}✗ Mosquitto is not running!${NC}"
    echo "    Start it with: sudo systemctl start mosquitto"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} Mosquitto is running"

# Check if mosquitto_sub is available
if ! command -v mosquitto_sub &> /dev/null; then
    echo -e "  ${RED}✗ mosquitto-clients not installed${NC}"
    echo "    Install with: sudo apt install mosquitto-clients"
    exit 1
fi

echo -e "  Scanning for nodes (${TIMEOUT}s timeout)...\n"

TEMP_FILE=$(mktemp)

# Subscribe and wait for messages
timeout "$TIMEOUT" mosquitto_sub -h localhost -t "spotless/nodes/+/status" -C "${#EXPECTED_NODES[@]}" > "$TEMP_FILE" 2>/dev/null &
SUB_PID=$!

# Countdown with live detection
FOUND=0
for i in $(seq "$TIMEOUT" -1 1); do
    if ! kill -0 $SUB_PID 2>/dev/null; then
        break
    fi
    
    # Count found so far
    CURRENT_FOUND=0
    for node in "${EXPECTED_NODES[@]}"; do
        grep -q "$node" "$TEMP_FILE" 2>/dev/null && ((CURRENT_FOUND++))
    done
    
    if [ $CURRENT_FOUND -gt $FOUND ]; then
        FOUND=$CURRENT_FOUND
    fi
    
    printf "\r  ⏳ Waiting... %2ds  |  Found: %d/%d " "$i" "$FOUND" "${#EXPECTED_NODES[@]}"
    sleep 1
done
printf "\r                                              \r"

kill $SUB_PID 2>/dev/null
wait $SUB_PID 2>/dev/null

# Parse and display results
echo -e "  ${BOLD}Results:${NC}\n"

NODES_ONLINE=0
for node in "${EXPECTED_NODES[@]}"; do
    if grep -q "$node" "$TEMP_FILE" 2>/dev/null; then
        NODE_DATA=$(grep "$node" "$TEMP_FILE" | head -1)
        NODE_IP=$(echo "$NODE_DATA" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('ip','?'))" 2>/dev/null || echo "?")
        NODE_RSSI=$(echo "$NODE_DATA" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); print(d.get('rssi','?'))" 2>/dev/null || echo "?")
        NODE_UP=$(echo "$NODE_DATA" | python3 -c "import sys,json; d=json.loads(sys.stdin.read()); s=d.get('uptime',0); print(f'{s//60}m {s%60}s')" 2>/dev/null || echo "?")
        
        echo -e "  ${GREEN}● ${BOLD}$node${NC}"
        echo -e "    IP: $NODE_IP  |  WiFi: ${NODE_RSSI}dBm  |  Uptime: $NODE_UP"
        ((NODES_ONLINE++))
    else
        echo -e "  ${RED}○ ${BOLD}$node${NC}  -  ${RED}OFFLINE${NC}"
    fi
done

rm -f "$TEMP_FILE"

echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
if [ $NODES_ONLINE -eq ${#EXPECTED_NODES[@]} ]; then
    echo -e "  ${GREEN}${BOLD}All ${#EXPECTED_NODES[@]} nodes ONLINE - Ready to go!${NC}"
elif [ $NODES_ONLINE -gt 0 ]; then
    echo -e "  ${YELLOW}${BOLD}$NODES_ONLINE/${#EXPECTED_NODES[@]} nodes online${NC}"
else
    echo -e "  ${RED}${BOLD}No nodes detected${NC}"
fi
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
