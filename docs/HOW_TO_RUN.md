# How to Run — Project Spotless (Full Setup Guide)

Step-by-step instructions to set up and run the entire Spotless IoT system
from scratch: ESP32 nodes, Raspberry Pi master, kiosk UI, and database.

> **Just want to deploy a new booth?** Use the one-command bootstrap instead
> of following this entire document. See `docs/DEPLOYMENT.md` — it replaces
> Sections 1, 4, and 6 below with a single `curl` command. The full guide
> here is kept for reference and troubleshooting.

---

## Prerequisites

| Item | Details |
|------|---------|
| Raspberry Pi 5 | Raspberry Pi OS Bookworm, connected to WiFi |
| 3x ESP32-S3 boards | Node 1, Node 2, Node 3 — with custom PCB relay boards |
| WiFi router | **2.4 GHz** (ESP32 does not support 5 GHz) |
| Laptop/PC | PlatformIO (VS Code extension) installed, USB-C cable |
| Monitor + keyboard | For Raspberry Pi initial setup (or SSH) |

---

## System Architecture

```
  Internet (optional — for DB & email only)
      |
  [WiFi Router]  (2.4 GHz)
      |
      +-- Raspberry Pi 5          <- Static IP: 192.168.0.16
      |     +-- Mosquitto MQTT Broker (port 1883)
      |     +-- Flask Kiosk Web UI (port 5000)
      |     +-- StageExecutor (relay control + UI timer)
      |     +-- GeyserController (smart pre-heating)
      |     +-- RoofLightController (session + evening schedule)
      |     +-- GPIO: dry (14), roof (15), geyser (18), rglight (24)
      |
      +-- ESP32 Node 1  (Container 1: shampoo/conditioner system)
      +-- ESP32 Node 2  (Container 2: disinfectant + autoflush)
      +-- ESP32 Node 3  (Bath line solenoid valves)
```

Only the Pi needs a static IP. ESP32s use dynamic IPs — they connect
**to** the Pi, not the other way around.

---

## Section 1: Raspberry Pi Setup

### 1.1 Install the OS and Clone the Code

Flash Raspberry Pi OS Bookworm to an SD card, boot, connect to WiFi, then:

```bash
sudo apt update && sudo apt install -y git python3-venv python3-pip
cd ~
git clone https://github.com/petgully/IOT_Spotless.git
cd IOT_Spotless
```

### 1.2 Set a Static IP Address

The Pi must always be at the same IP so ESP32 nodes know where to connect.

```bash
# Check your current network info
hostname -I                          # Current IP
ip route | grep default              # Gateway (usually 192.168.0.1)
nmcli connection show                # Connection name (e.g. "preconfigured")
```

Set the static IP (adjust values for your network):

```bash
sudo nmcli connection modify preconfigured \
  ipv4.addresses 192.168.0.16/24 \
  ipv4.gateway 192.168.0.1 \
  ipv4.dns "8.8.8.8,8.8.4.4" \
  ipv4.method manual

sudo nmcli connection up preconfigured
```

Verify:

```bash
hostname -I
# Should show: 192.168.0.16
```

### 1.3 Install Mosquitto MQTT Broker

```bash
sudo apt install -y mosquitto mosquitto-clients
```

Configure it for open access on the local network:

```bash
sudo tee /etc/mosquitto/conf.d/spotless.conf > /dev/null << 'EOF'
listener 1883
allow_anonymous true
EOF
```

Remove any conflicting config files:

```bash
ls /etc/mosquitto/conf.d/
# If you see local.conf or other files, remove them:
sudo rm /etc/mosquitto/conf.d/local.conf
```

Start and enable:

```bash
sudo systemctl enable mosquitto
sudo systemctl restart mosquitto
sudo systemctl status mosquitto
# Should show: active (running)
```

Quick test:

```bash
mosquitto_pub -h localhost -t "test" -m "hello"
# No error = working
```

### 1.4 Create Python Virtual Environment and Install Dependencies

```bash
cd ~/IOT_Spotless/raspberry_pi
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

> **Note:** `gpiod` will only work on the actual Raspberry Pi. On a dev
> machine it fails to import, and the system falls back to simulated GPIO
> (which is fine for testing).

### 1.5 Create the .env File (Database Credentials)

```bash
cp .env.example .env
nano .env
```

Fill in your database and email credentials:

```bash
# AWS RDS Aurora MySQL
SPOTLESS_DB_HOST=your-aurora-endpoint.cluster-xxxxx.us-east-1.rds.amazonaws.com
SPOTLESS_DB_PORT=3306
SPOTLESS_DB_USER=spotless001
SPOTLESS_DB_PASSWORD=your-password-here
SPOTLESS_DB_NAME=petgully_db
SPOTLESS_DB_SSL=true
```

Save with `Ctrl+O`, exit with `Ctrl+X`.

> If you don't have a database yet, skip this step. The system works fully
> offline — session logs are stored locally in `~/.spotless/sessions/` and
> can be synced to the DB later.

### 1.6 Configure Machine ID (First Run)

```bash
cd ~/IOT_Spotless/raspberry_pi
source venv/bin/activate
python3 main.py --setup
```

You'll be prompted to enter a Machine ID (e.g., `BS01`, `HONER01`).
This ID is saved in `~/.spotless/machine_id.txt` and used for logging
and identification.

### 1.7 Verify Configuration

```bash
python3 main.py --config
```

This prints the current machine configuration, all session types, geyser
settings, and roof light schedule.

```bash
python3 main.py --list
```

This lists all available session types (bath + utility).

---

## Section 2: ESP32 Node Setup

### 2.1 Understand the Node Layout

Each ESP32-S3 board has 7 relays with identical PCB wiring:

| Relay | PCB Label | GPIO |
|-------|-----------|------|
| 1 | S1 (220V) | 9 |
| 2 | P1&P2 | 10 |
| 3 | FP1 | 11 |
| 4 | RS1&DS2 | 12 |
| 5 | RS2&DS1 | 13 |
| 6 | BACK1 | 14 |
| 7 | BACK2 | 21 |

What each node controls:

| | Relay 7 (BACK2) | Relay 6 (BACK1) | Relay 5 (RS2&DS1) | Relay 4 (RS1&DS2) | Relay 3 (FP1) | Relay 2 (P1&P2) | Relay 1 (S1 220V) |
|---|---|---|---|---|---|---|---|
| **Node 1** | P1 (Shampoo pump) | P2 (Conditioner pump) | RO1 (Fill container 1) | RO2 (Drain container 1) | D1 (Diaphragm pump 1) | P3 (Med shampoo pump) | Booster Pump 220V |
| **Node 2** | P4 (Disinfectant pump) | P5 (Backup pump) | RO3 (Fill container 2) | RO4 (Drain container 2) | D2 (Diaphragm pump 2) | TOP (Flush top nozzle) | Flushmain 220V |
| **Node 3** | S1 (Shampoo gate) | S2 (Anti-backflow) | S3 (Disinfectant gate) | S4 (Anti-backflow) | S5 (Water line) | BOTTOM (Flush bottom) | S8 Main Gate 220V |

### 2.2 Update WiFi and MQTT Settings

On your PC, edit each node's config file. Only 3 lines need changing:

**Node 1:** `esp32_node1/include/config.h`

```cpp
#define WIFI_SSID     "YourWiFiName"         // 2.4 GHz only
#define WIFI_PASSWORD "YourWiFiPassword"
#define MQTT_BROKER   "192.168.0.16"         // Your Pi's static IP
```

**Node 2:** `esp32_node2/include/config.h` — same WiFi/MQTT values,
`NODE_ID` is already `"spotless_node2"`.

**Node 3:** `esp32_node3/include/config.h` — same WiFi/MQTT values,
`NODE_ID` is already `"spotless_node3"`.

> Everything else in `config.h` (relay pins, LED pins, timing) should be
> left as-is unless you changed the hardware wiring.

### 2.3 Flash Each ESP32

Using PlatformIO CLI:

```bash
# Node 1
cd esp32_node1
pio run --target upload

# Node 2
cd ../esp32_node2
pio run --target upload

# Node 3
cd ../esp32_node3
pio run --target upload
```

Or use the PlatformIO upload button in VS Code with each node folder open.

### 2.4 Verify ESP32 Connection

On the Raspberry Pi:

```bash
mosquitto_sub -h localhost -t "spotless/nodes/+/status" -v
```

Power on each ESP32. You should see:

```
spotless/nodes/spotless_node1/status {"online":true}
spotless/nodes/spotless_node2/status {"online":true}
spotless/nodes/spotless_node3/status {"online":true}
```

Press `Ctrl+C` to stop.

### 2.5 Optional: Monitor Serial Output

If an ESP32 isn't connecting, plug it into USB and check serial:

```bash
pio device monitor --baud 115200
```

You should see:

```
WiFi connected! IP: 192.168.0.xx
Connected to MQTT broker
```

---

## Section 3: Running the System

### 3.1 Start in Kiosk Mode (Production)

This is the normal way to run the system:

```bash
cd ~/IOT_Spotless/raspberry_pi
source venv/bin/activate
python3 main.py --kiosk
```

What happens:
1. Machine ID is loaded from `~/.spotless/machine_id.txt`
2. Configuration is loaded from `~/.spotless/config.json`
3. GPIO controller initializes (dry, roof, geyser, rglight)
4. MQTT controller connects and waits for ESP32 nodes (30s timeout)
5. StageExecutor is created (data-driven relay controller)
6. GeyserController starts (morning pre-heat schedule + safety cutoff)
7. RoofLightController starts (evening schedule thread)
8. Flask web server starts on port 5000
9. Kiosk UI is available at `http://<pi-ip>:5000`

### 3.2 Start from CLI (Testing)

Run specific sessions without the web UI:

```bash
# Small bath session
python3 main.py --session small --qr TEST123

# Relay test (cycles through every relay)
python3 main.py --test

# Demo mode (5 seconds per relay, sequential)
python3 main.py --session demo

# Dryer only
python3 main.py --session onlydrying

# Flush tub
python3 main.py --session onlyflush

# Water only
python3 main.py --session onlywater
```

### 3.3 Using the Kiosk Web UI

1. Open `http://<pi-ip>:5000` on the kiosk display or any device on the same network
2. Scan or type a QR code
3. The system validates the code (against the database or local patterns)
4. If valid: session starts, progress is shown on screen with countdown timers
5. If invalid: error message appears

**Test QR codes (no database required):**

| Code | Session Type |
|------|-------------|
| `small` | Small Pet Bath |
| `large` | Large Pet Bath |
| `demo` | Demo Mode (relay test) |
| `quicktest` | Quick Relay Test |

---

## Section 4: Auto-Start on Boot (Kiosk Mode)

### 4.1 Run the Setup Script

```bash
cd ~/IOT_Spotless/raspberry_pi
sudo bash scripts/setup_kiosk.sh
```

This script:
- Installs the `spotless-kiosk` systemd service
- Configures Chromium to open fullscreen on login
- Disables screen blanking
- Enables desktop auto-login

### 4.2 Reboot and Verify

```bash
sudo reboot
```

After reboot:
1. The Pi auto-logs in
2. `spotless-kiosk.service` starts the Flask backend
3. Chromium opens `http://localhost:5000` in fullscreen

### 4.3 Service Management Commands

```bash
# Check status
sudo systemctl status spotless-kiosk

# Start / stop / restart
sudo systemctl start spotless-kiosk
sudo systemctl stop spotless-kiosk
sudo systemctl restart spotless-kiosk

# View live logs
journalctl -u spotless-kiosk -f

# View last 50 log lines
journalctl -u spotless-kiosk -n 50

# Disable auto-start
sudo systemctl disable spotless-kiosk
```

---

## Section 5: Database Setup (Optional)

The system works fully offline. The database is only needed for:
- Pulling booking details from QR codes
- Logging sessions to a central server
- Remote configuration updates

### 5.1 Database Requirements

- AWS RDS Aurora MySQL (or any MySQL 5.7+ / MariaDB 10.3+)
- Database name: `petgully_db`
- Required tables: `session_logs`, `session_stages`, `session_events`,
  `bookings`, `machine_configs`

### 5.2 Configure Connection

Edit `~/.spotless/.env` (or `raspberry_pi/.env`):

```bash
SPOTLESS_DB_HOST=your-aurora-endpoint.cluster-xxxxx.us-east-1.rds.amazonaws.com
SPOTLESS_DB_PORT=3306
SPOTLESS_DB_USER=spotless001
SPOTLESS_DB_PASSWORD=your-password-here
SPOTLESS_DB_NAME=petgully_db
SPOTLESS_DB_SSL=true
```

### 5.3 Test Connection

```bash
cd ~/IOT_Spotless/raspberry_pi
source venv/bin/activate
python3 test_db_connection.py
```

### 5.4 Offline Mode

When the database is unavailable:
- QR codes are validated using local patterns (type the session type directly)
- Sessions are logged to `~/.spotless/sessions/*.json`
- Pending logs can be synced later when connectivity is restored

---

## Section 6: Configuration Tuning

All timing and schedule parameters live in `~/.spotless/config.json`.
This file is created automatically on first run.

### 6.1 Session Timings

Each bath session type has configurable parameters:

| Parameter | Description | Small Default | Large Default |
|-----------|-------------|---------------|---------------|
| `sval` | Shampoo spray duration (seconds) | 80 | 100 |
| `cval` | Conditioner spray duration (seconds) | 80 | 100 |
| `dval` | Disinfectant duration (seconds) | 60 | 60 |
| `wval` | Water rinse duration (seconds) | 60 | 60 |
| `dryval` | Total dryer time (split into 2 phases) | 480 | 600 |
| `fval` | Flush duration per phase (seconds) | 60 | 60 |
| `wt` | Peristaltic pump run time (seconds) | 30 | 50 |
| `msgval` | Massage/soak wait time (seconds) | 30 | 30 |
| `tdry` | Towel dry wait time (seconds) | 30 | 30 |
| `pr` | Include disinfectant (10=yes, 20=no) | 20 | 20 |
| `ctype` | Conditioner type (100=normal, 200=medicated) | 100 | 100 |

To change: edit `~/.spotless/config.json`, find the session type under
`"session_types"`, and update the values. Changes take effect on the
next session (no restart needed — config is re-read per session).

### 6.2 Geyser Settings

```json
"geyser": {
    "morning_preheat_time": "07:00",
    "heat_duration_sec": 480,
    "safety_cutoff_sec": 1800
}
```

| Parameter | Description | Default |
|-----------|-------------|---------|
| `morning_preheat_time` | Daily pre-heat time (HH:MM) | 07:00 |
| `heat_duration_sec` | How long to heat per cycle | 480 (8 min) |
| `safety_cutoff_sec` | Max continuous ON time before forced shutoff | 1800 (30 min) |

The geyser also re-heats automatically after every completed session.

### 6.3 Roof Light Settings

```json
"roof_light": {
    "evening_on_time": "19:00",
    "evening_off_time": "21:00"
}
```

The roof tubelight turns ON when **either**:
- A session is active (QR validated through session complete)
- Current time is within the evening window

OR-logic: if the evening window and a session overlap, the light stays
on through both periods.

---

## Section 7: Session Flow (What Happens When You Scan a QR)

```
QR Scan
  |
  v
Validate QR (DB lookup or local pattern match)
  |
  v
Load session config (e.g. "small") from ~/.spotless/config.json
  |
  v
Build stage list (20+ stages with relay patterns, durations, audio cues)
  |
  v
Roof light ON
  |
  v
For each stage:
  +-- Play audio voiceover (non-blocking)
  +-- Start parallel pump if needed (e.g. p1 for 30s)
  +-- Turn ON relay devices via MQTT + GPIO
  +-- Countdown loop (1 second ticks):
  |     +-- Emit progress to kiosk UI (SocketIO)
  |     +-- Log to database (if connected)
  +-- Turn OFF relay devices
  +-- Beep if stage boundary
  |
  v
Session complete
  +-- Log total duration to DB
  +-- Update booking status
  +-- Send completion email
  +-- Trigger geyser re-heat
  +-- Turn off roof light (unless evening schedule is active)
```

---

## Section 8: Troubleshooting

### ESP32 Won't Connect

| Check | Command / Action |
|-------|-----------------|
| WiFi is 2.4 GHz? | ESP32 does not support 5 GHz networks |
| WiFi credentials correct? | Re-check `config.h` SSID and password |
| Pi IP correct? | `hostname -I` on Pi, compare with `MQTT_BROKER` in `config.h` |
| Mosquitto running? | `sudo systemctl status mosquitto` |
| Can ESP32 reach Pi? | Plug ESP32 into USB, check serial at 115200 baud |
| Firewall blocking? | `sudo ufw allow 1883/tcp` (if UFW is enabled) |

### Kiosk Won't Start

```bash
# Check service status
sudo systemctl status spotless-kiosk

# Check logs
journalctl -u spotless-kiosk -n 100

# Is port 5000 already in use?
sudo ss -tlnp | grep 5000

# Manual start for debugging
cd ~/IOT_Spotless/raspberry_pi
source venv/bin/activate
python3 main.py --kiosk
```

### Relays Not Activating

```bash
# Run relay test
python3 main.py --test

# Watch MQTT messages in real time
mosquitto_sub -h localhost -t "spotless/#" -v

# Check which nodes are online
python3 main.py --session quicktest
```

### Database Connection Fails

```bash
# Test connection
python3 test_db_connection.py

# Check .env file exists and has correct values
cat .env

# System works offline — check local session logs
ls -la ~/.spotless/sessions/
```

### Geyser / Roof Light Not Working

```bash
# Check GPIO controller recognizes the pins
python3 -c "
import sys; sys.path.insert(0, '.')
from gpio_controller import GPIOController
gpio = GPIOController()
gpio.print_status()
print('Roof relay:', gpio.roof)
print('Geyser relay:', gpio.geyser)
"
```

---

## Section 9: File Reference

### Raspberry Pi Code (`raspberry_pi/`)

| File | Purpose |
|------|---------|
| `main.py` | Entry point — wires everything together, CLI args |
| `config.py` | Static config: MQTT topics, node IDs, GPIO pins |
| `config_manager.py` | Dynamic config: session timings, geyser/roof settings |
| `device_map.py` | Maps friendly names (p1, s8, top) to node+relay |
| `gpio_controller.py` | Direct RPi GPIO control (dry, roof, geyser, rglight) |
| `spotless_controller.py` | StageExecutor — data-driven relay + countdown engine |
| `session_runner.py` | Session lifecycle: DB logging, email, hooks |
| `session_stages.py` | Stage definitions — the single source of truth |
| `geyser_controller.py` | Smart geyser pre-heating with safety cutoff |
| `roof_light_controller.py` | Roof light: session + evening schedule OR-logic |
| `mqtt_client.py` | MQTT publish/subscribe wrapper |
| `node_controller.py` | ESP32 node management (online/offline tracking) |
| `qr_validator.py` | QR code validation (DB + local patterns) |
| `db_manager.py` | Database connection (AWS RDS Aurora MySQL) |
| `db_sessions.py` | Session/stage logging queries |
| `db_bookings.py` | Booking lookup/update queries |
| `email_service.py` | Session email notifications |
| `logging_config.py` | Structured logging setup |
| `kiosk/web_server.py` | Flask + SocketIO kiosk web server |

### ESP32 Firmware (`esp32_node1/`, `esp32_node2/`, `esp32_node3/`)

| File | Purpose |
|------|---------|
| `include/config.h` | WiFi, MQTT, relay pin configuration |
| `src/main.cpp` | Firmware: connects WiFi/MQTT, listens for relay commands |
| `platformio.ini` | PlatformIO build configuration |

### Configuration Files (created at runtime)

| File | Purpose |
|------|---------|
| `~/.spotless/config.json` | All session timings, geyser/roof settings |
| `~/.spotless/machine_id.txt` | Machine identifier (e.g. BS01) |
| `~/.spotless/sessions/*.json` | Offline session logs |
| `raspberry_pi/.env` | Database and email credentials |

---

## Quick Reference — Common Commands

```bash
# --- Start the system ---
cd ~/IOT_Spotless/raspberry_pi
source venv/bin/activate
python3 main.py --kiosk                     # Start with web UI
python3 main.py --session small             # Run small bath (CLI)
python3 main.py --test                      # Test all relays

# --- Service management ---
sudo systemctl start spotless-kiosk         # Start service
sudo systemctl stop spotless-kiosk          # Stop service
sudo systemctl restart spotless-kiosk       # Restart service
journalctl -u spotless-kiosk -f             # Live logs

# --- MQTT debugging ---
mosquitto_sub -h localhost -t "spotless/#" -v        # All messages
mosquitto_sub -h localhost -t "spotless/nodes/+/status" -v  # Node status only

# --- Configuration ---
python3 main.py --setup                     # Set/reset machine ID
python3 main.py --config                    # Print current config
python3 main.py --list                      # List session types
nano ~/.spotless/config.json                # Edit timings

# --- System info ---
hostname -I                                 # Pi's IP address
sudo systemctl status mosquitto             # MQTT broker status
```

---

## Verification Checklist

Use this after a fresh setup to confirm everything works:

- [ ] Raspberry Pi has a static IP
- [ ] Mosquitto is running (`sudo systemctl status mosquitto`)
- [ ] Python venv created and dependencies installed
- [ ] `.env` file created (or skipped for offline mode)
- [ ] Machine ID configured (`python3 main.py --setup`)
- [ ] All 3 ESP32 nodes flashed with correct WiFi/MQTT
- [ ] All 3 ESP32 nodes showing online in MQTT
- [ ] `python3 main.py --test` cycles through all relays
- [ ] `python3 main.py --kiosk` starts the web UI
- [ ] Kiosk accessible at `http://<pi-ip>:5000`
- [ ] Typing `demo` in QR input starts a demo session
- [ ] Invalid QR codes show error message
- [ ] Geyser heats at configured morning time
- [ ] Roof light turns on during evening window
- [ ] Auto-start works after `sudo reboot`
