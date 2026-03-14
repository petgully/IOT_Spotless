"""
=============================================================================
Configuration for Raspberry Pi Master Controller - Project Spotless
=============================================================================
Edit these values to match your network setup and hardware configuration.

This is the central configuration file for the Spotless IoT system.
The Raspberry Pi acts as the master controller, coordinating all ESP32 nodes.

Device Mapping (see device_map.py for details):
    NODE 1: p1, p2, ro1, ro2, d1, p3, pump
    NODE 2: p4, p5, ro3, ro4, d2, s7, s9
    NODE 3: s1, s2, s3, s4, s5, s6, s8

Relay Configuration (7 Relays per Node):
    Relay 1: S1 (220V)    - GPIO 9   - 220V Solenoid
    Relay 2: P1&P2        - GPIO 10  - Pumps
    Relay 3: FP1          - GPIO 11  - Flow Pump 1
    Relay 4: RS1&DS2      - GPIO 12  - RO Solenoid 1 & Diaphragm Solenoid 2
    Relay 5: RS2&DS1      - GPIO 13  - RO Solenoid 2 & Diaphragm Solenoid 1
    Relay 6: BACK1        - GPIO 14  - Backflow 1
    Relay 7: BACK2        - GPIO 21  - Backflow 2
=============================================================================
"""

# -----------------------------------------------------------------------------
# MQTT Broker Configuration
# -----------------------------------------------------------------------------
# The Raspberry Pi runs the MQTT broker (Mosquitto)
MQTT_BROKER_HOST = "localhost"
MQTT_BROKER_PORT = 1883

# Client ID for the master controller
MQTT_CLIENT_ID = "spotless_master"

# Quality of Service level
# 0 = At most once, 1 = At least once, 2 = Exactly once
MQTT_QOS = 1

# -----------------------------------------------------------------------------
# MQTT Topics Structure
# -----------------------------------------------------------------------------
# Topic format: spotless/nodes/{node_id}/relays/{num}/command
# 
# Examples:
#   spotless/nodes/spotless_node1/relays/1/command  - Command to relay 1 on node 1
#   spotless/nodes/spotless_node1/relays/1/state    - State update from relay 1
#   spotless/nodes/+/status                         - Status from all nodes

TOPIC_BASE = "spotless/nodes"
TOPIC_COMMAND_SUFFIX = "command"
TOPIC_STATE_SUFFIX = "state"
TOPIC_STATUS = "status"

# -----------------------------------------------------------------------------
# Node Configuration - Three ESP32 Devices
# -----------------------------------------------------------------------------
# Node IDs
NODE_1 = "spotless_node1"
NODE_2 = "spotless_node2"
NODE_3 = "spotless_node3"

# Node configuration
NODES = {
    NODE_1: {
        "name": "ESP32 Node 1",
        "relay_count": 7,
        "description": "Spotless Node 1 - p1, p2, ro1, ro2, d1, p3, pump"
    },
    NODE_2: {
        "name": "ESP32 Node 2",
        "relay_count": 7,
        "description": "Spotless Node 2 - p4, p5, ro3, ro4, d2, s7, s9"
    },
    NODE_3: {
        "name": "ESP32 Node 3",
        "relay_count": 7,
        "description": "Spotless Node 3 - s1, s2, s3, s4, s5, s6, s8"
    },
}

# -----------------------------------------------------------------------------
# Relay Configuration
# -----------------------------------------------------------------------------
# Relay number constants
class Relay:
    """Relay index constants for all nodes."""
    S1_220V = 1    # 220V Solenoid
    P1_P2 = 2      # Pumps P1 & P2
    FP1 = 3        # Flow Pump 1
    RS1_DS2 = 4    # RO Solenoid 1 & Diaphragm Solenoid 2
    RS2_DS1 = 5    # RO Solenoid 2 & Diaphragm Solenoid 1
    BACK1 = 6      # Backflow 1
    BACK2 = 7      # Backflow 2

# Relay configuration with GPIO and description
RELAY_CONFIG = {
    1: {"label": "S1_220V",   "gpio": 9,  "description": "220V Solenoid"},
    2: {"label": "P1_P2",     "gpio": 10, "description": "Pumps P1 & P2"},
    3: {"label": "FP1",       "gpio": 11, "description": "Flow Pump 1"},
    4: {"label": "RS1_DS2",   "gpio": 12, "description": "RO Solenoid 1 & Diaphragm Solenoid 2"},
    5: {"label": "RS2_DS1",   "gpio": 13, "description": "RO Solenoid 2 & Diaphragm Solenoid 1"},
    6: {"label": "BACK1",     "gpio": 14, "description": "Backflow 1"},
    7: {"label": "BACK2",     "gpio": 21, "description": "Backflow 2"},
}

# Relay labels per node (all identical)
RELAY_LABELS = {
    NODE_1: {
        1: "S1_220V",
        2: "P1_P2",
        3: "FP1",
        4: "RS1_DS2",
        5: "RS2_DS1",
        6: "BACK1",
        7: "BACK2",
    },
    NODE_2: {
        1: "S1_220V",
        2: "P1_P2",
        3: "FP1",
        4: "RS1_DS2",
        5: "RS2_DS1",
        6: "BACK1",
        7: "BACK2",
    },
    NODE_3: {
        1: "S1_220V",
        2: "P1_P2",
        3: "FP1",
        4: "RS1_DS2",
        5: "RS2_DS1",
        6: "BACK1",
        7: "BACK2",
    },
}

# -----------------------------------------------------------------------------
# Device Variable Mapping Reference
# -----------------------------------------------------------------------------
# NODE 1 Devices:
#   p1   → BACK2    (Relay 7) - Peristaltic Pump 1
#   p2   → BACK1    (Relay 6) - Peristaltic Pump 2
#   ro1  → RS1&DS2  (Relay 4) - RO Solenoid 1
#   ro2  → RS2&DS1  (Relay 5) - RO Solenoid 2
#   d1   → FP1      (Relay 3) - Diaphragm Pump 1
#   p3   → P1&P2    (Relay 2) - Pumps
#   pump → S1       (Relay 1) - Main Pump 220V
#
# NODE 2 Devices:
#   p4   → BACK2    (Relay 7) - Peristaltic Pump 4
#   p5   → BACK1    (Relay 6) - Peristaltic Pump 5
#   ro3  → RS1&DS2  (Relay 4) - RO Solenoid 3
#   ro4  → RS2&DS1  (Relay 5) - RO Solenoid 4
#   d2   → FP1      (Relay 3) - Diaphragm Pump 2
#   s7   → P1&P2    (Relay 2) - Solenoid 7
#   s9   → S1       (Relay 1) - Solenoid 9 220V
#
# NODE 3 Devices:
#   s1   → BACK2    (Relay 7) - Solenoid 1
#   s2   → BACK1    (Relay 6) - Solenoid 2
#   s3   → RS1&DS2  (Relay 4) - Solenoid 3
#   s4   → RS2&DS1  (Relay 5) - Solenoid 4
#   s5   → FP1      (Relay 3) - Solenoid 5
#   s6   → P1&P2    (Relay 2) - Solenoid 6
#   s8   → S1       (Relay 1) - Solenoid 8 220V

# -----------------------------------------------------------------------------
# Direct Raspberry Pi GPIO Relays
# -----------------------------------------------------------------------------
# These relays are connected directly to the Raspberry Pi GPIO pins,
# NOT through ESP32 nodes.

GPIO_CHIP = "gpiochip0"  # Raspberry Pi 5 GPIO chip

# Direct GPIO relay pins
GPIO_RELAYS = {
    "dry": {
        "pin": 14,
        "description": "Dryer Relay",
    },
    "geyser": {
        "pin": 18,
        "description": "Geyser/Heater Relay",
    },
}

# GPIO active state (True = Active HIGH, relay ON when GPIO is HIGH)
GPIO_ACTIVE_STATE = True

# -----------------------------------------------------------------------------
# System Configuration
# -----------------------------------------------------------------------------
# Logging configuration
LOG_FILE = "spotless_system.log"
LOG_LEVEL = "INFO"
LOG_ROTATION_DAYS = 7

# Status check interval (seconds)
STATUS_CHECK_INTERVAL = 30

# Connection timeout (seconds)
NODE_TIMEOUT = 60

# -----------------------------------------------------------------------------
# Session Configuration (Placeholder - to be configured)
# -----------------------------------------------------------------------------
# Bath session types and their configurations
# These will be defined based on the specific requirements

SESSION_TYPES = {
    # Example structure - to be configured
    # "small_bath": {
    #     "description": "Small Pet Bath Session",
    #     "duration_estimate": 600,  # seconds
    #     "stages": ["shampoo", "water", "conditioner", "water", "dry"]
    # },
}

# -----------------------------------------------------------------------------
# Email Configuration (Optional - for notifications)
# -----------------------------------------------------------------------------
EMAIL_ENABLED = False
EMAIL_SENDER = ""
EMAIL_PASSWORD = ""
EMAIL_RECEIVER = ""

# -----------------------------------------------------------------------------
# API Configuration (Optional - for remote control)
# -----------------------------------------------------------------------------
API_ENABLED = False
API_HOST = "0.0.0.0"
API_PORT = 5000
