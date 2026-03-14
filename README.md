# Project Spotless

**Automated Pet Grooming System - IoT Architecture**

A distributed IoT system for automated pet bathing and grooming, featuring ESP32 microcontrollers as I/O nodes, Raspberry Pi 5 as the master controller, cloud database integration, and a modern web-based kiosk interface.

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Components](#components)
- [Process Flow](#process-flow)
- [Hardware Requirements](#hardware-requirements)
- [Software Stack](#software-stack)
- [Directory Structure](#directory-structure)
- [Setup Guide](#setup-guide)
- [Configuration](#configuration)
- [API Reference](#api-reference)
- [Database Schema](#database-schema)
- [Troubleshooting](#troubleshooting)

---

## Overview

Project Spotless is a modern rebuild of a legacy pet grooming automation system. The system controls water pumps, shampoo dispensers, dryers, and other equipment to provide automated pet bathing services.

### Key Features

- **Distributed IoT Architecture**: 3 ESP32 nodes + 1 Raspberry Pi master
- **Real-time Control**: MQTT-based communication for instant relay control
- **Cloud Integration**: AWS RDS Aurora MySQL for session configuration
- **Offline Mode**: Local configuration cache for operation without internet
- **Modern Kiosk UI**: Web-based interface with real-time progress tracking
- **Session Analytics**: Detailed logging of every stage for future optimization
- **Email Notifications**: Automated session completion notifications

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           CLOUD LAYER                                        │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│    ┌──────────────────────┐         ┌──────────────────────┐                │
│    │   AWS RDS Aurora     │         │   Email Service      │                │
│    │   (petgully_db)      │         │   (Gmail SMTP)       │                │
│    │                      │         │                      │                │
│    │  - session_config    │         │  - Session alerts    │                │
│    │  - session_logs      │         │  - Error reports     │                │
│    │  - session_stages    │         │  - Startup notices   │                │
│    │  - session_events    │         │                      │                │
│    └──────────┬───────────┘         └──────────┬───────────┘                │
│               │                                 │                            │
└───────────────┼─────────────────────────────────┼────────────────────────────┘
                │                                 │
                │ MySQL (Port 3306)               │ SMTP (Port 465)
                │                                 │
┌───────────────┼─────────────────────────────────┼────────────────────────────┐
│               │         MASTER LAYER            │                            │
├───────────────┴─────────────────────────────────┴────────────────────────────┤
│                                                                              │
│    ┌─────────────────────────────────────────────────────────────────────┐  │
│    │                     RASPBERRY PI 5                                   │  │
│    │                    (Master Controller)                               │  │
│    │                                                                      │  │
│    │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐ │  │
│    │  │ Kiosk UI    │  │ Spotless    │  │ Config      │  │ Email      │ │  │
│    │  │ (Flask)     │  │ Controller  │  │ Manager     │  │ Service    │ │  │
│    │  │ Port 5000   │  │             │  │             │  │            │ │  │
│    │  └─────────────┘  └─────────────┘  └─────────────┘  └────────────┘ │  │
│    │                                                                      │  │
│    │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐ │  │
│    │  │ MQTT Client │  │ Node        │  │ Device      │  │ GPIO       │ │  │
│    │  │ (Paho)      │  │ Controller  │  │ Controller  │  │ Controller │ │  │
│    │  │             │  │             │  │             │  │ (gpiod)    │ │  │
│    │  └──────┬──────┘  └─────────────┘  └─────────────┘  └─────┬──────┘ │  │
│    │         │                                                  │        │  │
│    │         │ MQTT (Port 1883)                        GPIO 14, 18      │  │
│    └─────────┼──────────────────────────────────────────────────┼────────┘  │
│              │                                                   │           │
└──────────────┼───────────────────────────────────────────────────┼───────────┘
               │                                                   │
               │                                          ┌────────┴────────┐
               │                                          │  Direct Relays  │
               │                                          │  - Dryer (14)   │
               │                                          │  - Geyser (18)  │
               │                                          └─────────────────┘
┌──────────────┴───────────────────────────────────────────────────────────────┐
│                              NODE LAYER                                       │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                               │
│  ┌─────────────────┐   ┌─────────────────┐   ┌─────────────────┐            │
│  │   ESP32 Node 1  │   │   ESP32 Node 2  │   │   ESP32 Node 3  │            │
│  │  (spotless_node1)│   │  (spotless_node2)│   │  (spotless_node3)│            │
│  │                 │   │                 │   │                 │            │
│  │  7 Relays:      │   │  7 Relays:      │   │  7 Relays:      │            │
│  │  - S1 (220V)    │   │  - S1 (220V)    │   │  - S1 (220V)    │            │
│  │  - P1&P2        │   │  - P1&P2        │   │  - P1&P2        │            │
│  │  - FP1          │   │  - FP1          │   │  - FP1          │            │
│  │  - RS1&DS2      │   │  - RS1&DS2      │   │  - RS1&DS2      │            │
│  │  - RS2&DS1      │   │  - RS2&DS1      │   │  - RS2&DS1      │            │
│  │  - BACK1        │   │  - BACK1        │   │  - BACK1        │            │
│  │  - BACK2        │   │  - BACK2        │   │  - BACK2        │            │
│  │                 │   │                 │   │                 │            │
│  │  5 LED Links    │   │  5 LED Links    │   │  5 LED Links    │            │
│  └─────────────────┘   └─────────────────┘   └─────────────────┘            │
│                                                                               │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

## Components

### 1. ESP32 Nodes (I/O Layer)

Each ESP32-S3 controls 7 relays and 5 LED indicators:

| Relay | GPIO | Purpose | Linked LED |
|-------|------|---------|------------|
| S1 (220V) | IO9 | Main power | - |
| P1&P2 | IO10 | Pump control | - |
| FP1 | IO11 | Fluid pump | LED_SHAMPOO (IO37) |
| RS1&DS2 | IO12 | Reset/Dispenser | LED_WATER (IO38) |
| RS2&DS1 | IO13 | Reset/Dispenser | LED_RESETCLEAN (IO39) |
| BACK1 | IO14 | Backup relay | PRE-MIX1 (IO40) |
| BACK2 | IO21 | Backup relay | PRE-MIX2 (IO42) |

### 2. Raspberry Pi 5 (Master Controller)

The brain of the system running Python:

| Module | Purpose |
|--------|---------|
| `main.py` | Application entry point |
| `mqtt_client.py` | MQTT communication with ESP32s |
| `node_controller.py` | High-level node management |
| `device_map.py` | Friendly device name mapping |
| `gpio_controller.py` | Direct Raspberry Pi GPIO control |
| `spotless_functions.py` | Bath session logic |
| `config_manager.py` | Configuration & offline mode |
| `db_manager.py` | AWS RDS database integration |
| `email_service.py` | Email notifications |
| `logging_config.py` | Structured logging |
| `kiosk/web_server.py` | Flask web UI |

### 3. Device Mapping

Friendly variable names mapped to physical relays:

**Node 1 (spotless_node1):**
| Variable | Relay | Description |
|----------|-------|-------------|
| `p1` | BACK2 | Pump 1 |
| `p2` | BACK1 | Pump 2 |
| `ro1` | RS1&DS2 | Rinse/Dispenser |
| `ro2` | RS2&DS1 | Rinse/Dispenser |
| `d1` | FP1 | Dispenser 1 |
| `p3` | P1&P2 | Pump 3 |
| `pump` | S1 | Main pump |

**Node 2 (spotless_node2):**
| Variable | Relay |
|----------|-------|
| `p4` | BACK2 |
| `p5` | BACK1 |
| `ro3` | RS1&DS2 |
| `ro4` | RS2&DS1 |
| `d2` | FP1 |
| `s7` | P1&P2 |
| `s9` | S1 |

**Node 3 (spotless_node3):**
| Variable | Relay |
|----------|-------|
| `s1` | BACK2 |
| `s2` | BACK1 |
| `s3` | RS1&DS2 |
| `s4` | RS2&DS1 |
| `s5` | FP1 |
| `s6` | P1&P2 |
| `s8` | S1 |

**Direct GPIO (Raspberry Pi):**
| Variable | GPIO | Description |
|----------|------|-------------|
| `dry` | 14 | Dryer relay |
| `geyser` | 18 | Water heater |

---

## Process Flow

### Session Lifecycle

```
┌─────────────────────────────────────────────────────────────────┐
│                      USER SCANS QR CODE                          │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. QR VALIDATION                                                │
│     ├── Check Database (petgully_db.session_config)             │
│     │   └── Found? Use customer's saved preferences             │
│     └── Not found? Use prefix mapping (SM→small, LG→large)      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. SESSION ACTIVATION                                           │
│     ├── Log to database: session_logs (status: 'activated')     │
│     ├── Load session parameters (sval, cval, dryval, etc.)      │
│     └── Initialize all relays to OFF state                      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. SESSION EXECUTION                                            │
│     │                                                            │
│     │  ┌──────────────────────────────────────────────────────┐ │
│     │  │ For each stage (Shampoo, Rinse, Conditioner, etc.): │ │
│     │  │   ├── Log stage_start to database                    │ │
│     │  │   ├── Emit WebSocket: stage_start                    │ │
│     │  │   ├── Control relays via MQTT                        │ │
│     │  │   ├── Update progress bar (WebSocket)                │ │
│     │  │   ├── Log stage_complete to database                 │ │
│     │  │   └── Emit WebSocket: stage_complete                 │ │
│     │  └──────────────────────────────────────────────────────┘ │
│     │                                                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. SESSION COMPLETION                                           │
│     ├── Turn off all relays                                     │
│     ├── Log to database: session_logs (status: 'completed')     │
│     ├── Calculate total duration                                │
│     ├── Send email notification                                 │
│     └── Redirect UI to home screen                              │
└─────────────────────────────────────────────────────────────────┘
```

### MQTT Communication

```
Raspberry Pi                          ESP32 Node
     │                                     │
     │  PUBLISH: spotless/node1/relay/1/set│
     │  Payload: {"state": "ON"}           │
     │ ───────────────────────────────────>│
     │                                     │
     │  SUBSCRIBE: spotless/node1/relay/+/state
     │<─────────────────────────────────── │
     │  Payload: {"relay": 1, "state": "ON",
     │            "led_gpio": 42}          │
     │                                     │
```

---

## Hardware Requirements

### Bill of Materials

| Component | Quantity | Purpose |
|-----------|----------|---------|
| Raspberry Pi 5 | 1 | Master controller |
| ESP32-S3 DevKit | 3 | I/O nodes |
| 8-Channel Relay Module | 3 | Relay control |
| 2-Channel Relay Module | 1 | Direct Pi GPIO |
| Power Supply 5V 10A | 1 | System power |
| Ethernet/WiFi Router | 1 | Network connectivity |
| Touch Screen (optional) | 1 | Kiosk display |
| Barcode Scanner | 1 | QR code input |

### Wiring Diagram

```
ESP32-S3 GPIO Pinout:
┌──────────────────────────────────────┐
│  GPIO 9  ──► Relay 1 (S1 220V)       │
│  GPIO 10 ──► Relay 2 (P1&P2)         │
│  GPIO 11 ──► Relay 3 (FP1)           │
│  GPIO 12 ──► Relay 4 (RS1&DS2)       │
│  GPIO 13 ──► Relay 5 (RS2&DS1)       │
│  GPIO 14 ──► Relay 6 (BACK1)         │
│  GPIO 21 ──► Relay 7 (BACK2)         │
│                                      │
│  GPIO 37 ──► LED_SHAMPOO             │
│  GPIO 38 ──► LED_WATER               │
│  GPIO 39 ──► LED_RESETCLEAN          │
│  GPIO 40 ──► PRE-MIX1                │
│  GPIO 42 ──► PRE-MIX2                │
└──────────────────────────────────────┘

Raspberry Pi 5 GPIO:
┌──────────────────────────────────────┐
│  GPIO 14 ──► Dryer Relay             │
│  GPIO 18 ──► Geyser Relay            │
└──────────────────────────────────────┘
```

---

## Software Stack

| Layer | Technology |
|-------|------------|
| ESP32 Firmware | PlatformIO + Arduino |
| Master Controller | Python 3.11+ |
| Web Framework | Flask + Flask-SocketIO |
| MQTT Broker | Mosquitto |
| Database | AWS RDS Aurora MySQL |
| Frontend | HTML5 + CSS3 + JavaScript |

### Python Dependencies

```
paho-mqtt>=1.6.0
gpiod>=2.0.0
flask>=2.3.0
flask-socketio>=5.3.0
pymysql>=1.1.0
requests>=2.28.0
```

---

## Directory Structure

```
Project_Spotless/
├── README.md                    # This file
│
├── esp32_node1/                 # ESP32 Node 1 firmware
│   ├── platformio.ini
│   ├── include/
│   │   └── config.h             # WiFi, MQTT, GPIO config
│   └── src/
│       └── main.cpp             # Main firmware code
│
├── esp32_node2/                 # ESP32 Node 2 firmware
│   └── (same structure)
│
├── esp32_node3/                 # ESP32 Node 3 firmware
│   └── (same structure)
│
└── raspberry_pi/                # Raspberry Pi code
    ├── main.py                  # Application entry point
    ├── config.py                # System configuration
    ├── requirements.txt         # Python dependencies
    │
    ├── mqtt_client.py           # MQTT communication
    ├── node_controller.py       # Node management
    ├── device_map.py            # Device name mapping
    ├── gpio_controller.py       # Direct GPIO control
    │
    ├── spotless_functions.py    # Bath session logic
    ├── config_manager.py        # Config & offline mode
    ├── db_manager.py            # Database integration
    ├── email_service.py         # Email notifications
    ├── logging_config.py        # Logging setup
    │
    ├── kiosk/                   # Web UI
    │   ├── __init__.py
    │   ├── web_server.py        # Flask server
    │   ├── templates/
    │   │   ├── index.html       # Main kiosk page
    │   │   └── session.html     # Progress page
    │   └── static/
    │       ├── css/style.css
    │       ├── js/app.js
    │       ├── js/session.js
    │       └── images/
    │
    ├── scripts/                 # Setup scripts
    │   ├── setup_kiosk.sh       # One-time setup
    │   ├── start_kiosk.sh       # Launch script
    │   └── spotless.service     # Systemd service
    │
    └── tests/                   # Test scripts
        ├── test_db_connection.py
        └── test_full_cycle.py
```

---

## Setup Guide

### 1. ESP32 Setup

```bash
# Install PlatformIO
pip install platformio

# For each ESP32 node:
cd esp32_node1
# Edit include/config.h with WiFi credentials
pio run --target upload
```

### 2. Raspberry Pi Setup

```bash
# Clone repository
cd ~/
git clone <repository> Project_Spotless
cd Project_Spotless/raspberry_pi

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure database (edit .env)
cp .env.example .env
nano .env
```

### 3. Database Setup

Run in MySQL Workbench:

```sql
USE petgully_db;

-- Session configuration table
CREATE TABLE session_config (
    id INT AUTO_INCREMENT PRIMARY KEY,
    mobile_number VARCHAR(15) NOT NULL UNIQUE,
    customer_name VARCHAR(100),
    session_type VARCHAR(50) DEFAULT 'small',
    sval INT DEFAULT 120,
    cval INT DEFAULT 120,
    dval INT DEFAULT 60,
    wval INT DEFAULT 60,
    dryval INT DEFAULT 480,
    -- ... (see db_manager.py for full schema)
);

-- Session logs, stages, events tables
-- (see test_db_connection.py for CREATE statements)
```

### 4. Run Kiosk

```bash
# Start with kiosk UI
python main.py --kiosk

# Or run in development mode
python -m kiosk.web_server
```

---

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SPOTLESS_DB_HOST` | Aurora endpoint | - |
| `SPOTLESS_DB_PORT` | Database port | 3306 |
| `SPOTLESS_DB_USER` | Database user | spotless001 |
| `SPOTLESS_DB_PASSWORD` | Database password | - |
| `SPOTLESS_DB_NAME` | Database name | petgully_db |
| `MQTT_BROKER` | MQTT broker IP | localhost |
| `MQTT_PORT` | MQTT port | 1883 |

### Session Types

| Type | Description | Duration |
|------|-------------|----------|
| `small` | Small pet bath | ~15 min |
| `large` | Large pet bath | ~19 min |
| `custdiy` | DIY with disinfectant | ~20 min |
| `medsmall` | Medicated small | ~14 min |
| `medlarge` | Medicated large | ~17 min |
| `quicktest` | Relay test | ~1.5 min |
| `onlydrying` | Drying only | ~5 min |
| `onlywater` | Water rinse only | ~1.5 min |

---

## API Reference

### REST Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | Kiosk home page |
| GET | `/session` | Session progress page |
| GET | `/api/status` | System status |
| POST | `/api/session/start` | Start session |
| POST | `/api/session/stop` | Emergency stop |
| GET | `/api/session_types` | List session types |

### WebSocket Events

| Event | Direction | Description |
|-------|-----------|-------------|
| `scan_success` | Server → Client | QR validation passed |
| `scan_failed` | Server → Client | QR validation failed |
| `stage_start` | Server → Client | New stage started |
| `stage_progress` | Server → Client | Progress update |
| `stage_complete` | Server → Client | Stage finished |
| `session_complete` | Server → Client | Session finished |
| `session_error` | Server → Client | Error occurred |

---

## Database Schema

### session_config
Customer session preferences and default presets.

### session_logs
Main session records with all parameters and timestamps.

### session_stages
Detailed tracking of each stage (shampoo, rinse, etc.).

### session_events
Granular event log for debugging and analytics.

---

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| ESP32 not connecting | Check WiFi credentials in config.h |
| MQTT timeout | Verify Mosquitto is running: `systemctl status mosquitto` |
| Database connection failed | Check security group allows your IP |
| Email not sending | Verify Gmail app password is correct |
| GPIO permission denied | Run with sudo or add user to gpio group |

### Logs

```bash
# Application logs
tail -f ~/.spotless/logs/spotless_*.log

# Kiosk logs
tail -f ~/.spotless/logs/kiosk.log

# MQTT broker logs
journalctl -u mosquitto -f
```

---

## License

Proprietary - Petgully Technologies

---

## Contact

For support, contact the development team at support@petgully.com
