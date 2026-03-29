# Project Spotless — Complete System Overview

## 1. What is Project Spotless?

An automated pet grooming/bathing system. A customer purchases a session through a booking app, receives a QR code, scans it at a physical kiosk (Raspberry Pi), and the machine runs a fully automated bath sequence — controlling water, shampoo, conditioner, dryer, and disinfectant through a network of IoT relays.

---

## 2. Physical Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        WiFi Network (2.4 GHz)                   │
│                                                                 │
│  ┌─────────────────────┐     ┌──────────────┐                  │
│  │   Raspberry Pi 5    │     │  AWS RDS     │                  │
│  │   (Master Controller)│◄───►│  Aurora MySQL │  (via Internet) │
│  │                     │     │  petgully_db  │                  │
│  │  • Mosquitto MQTT   │     └──────────────┘                  │
│  │  • Flask Kiosk :5000│                                        │
│  │  • Admin UI   :8080 │                                        │
│  │  • GPIO: dry, geyser│                                        │
│  └────────┬────────────┘                                        │
│           │ MQTT (port 1883)                                    │
│  ┌────────┼────────────────────────────┐                        │
│  │        │                            │                        │
│  ▼        ▼                            ▼                        │
│ ESP32    ESP32                        ESP32                     │
│ Node 1   Node 2                       Node 3                   │
│ 7 relays 7 relays                    7 relays                  │
└─────────────────────────────────────────────────────────────────┘
```

**Total hardware controlled:** 21 ESP32 relays + 2 Pi GPIO relays = **23 relays**

---

## 3. Software Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| ESP32 Firmware | C++ / Arduino / PlatformIO | Relay + LED control, MQTT client |
| MQTT Broker | Mosquitto (on Pi) | Message bus between Pi ↔ ESP32s |
| Backend | Python 3 (Flask + Flask-SocketIO) | Session logic, hardware orchestration |
| Kiosk Frontend | HTML/CSS/JS + WebSocket | Customer-facing touchscreen UI |
| Admin Dashboard | Flask (port 8080) | Relay testing and node monitoring |
| Database | AWS RDS Aurora MySQL | Session configs, bookings, logs |
| Email | Gmail SMTP | Session completion notifications |

---

## 4. Complete Data Flow — End to End

### Step 1: Customer Books a Session
- Customer uses the **booking app** (`booking_app/`) to select a session type and book.
- A **booking record** is created in the DB with a unique `booking_code` (e.g., `PG-20260314-ABCD`).
- A **QR code** is generated containing this booking code.

### Step 2: QR Code is Scanned at the Kiosk
- The Raspberry Pi runs a **kiosk web UI** at `http://<pi-ip>:5000`.
- The customer scans the QR code using a barcode scanner connected to the Pi.
- The frontend (`kiosk/static/js/app.js`) captures the input and sends it to the backend via `POST /api/session/start`.

### Step 3: QR Code Validation (web_server.py → validate_qr_code)
Validation follows this priority:

```
QR Code Scanned
    │
    ├── Starts with "PG"?
    │   └── YES → Query bookings table in DB
    │       └── Found? → Get session_type, customer_name, params from booking
    │
    ├── DB available?
    │   └── YES → Query session_config table by mobile_number/QR
    │       └── Found? → Get session_type and custom params
    │
    ├── Matches a prefix? (SM, LG, DIY, TEST, DRY, WATER, FLUSH, etc.)
    │   └── YES → Map to session type (small, large, custdiy, quicktest, etc.)
    │
    ├── Matches a session type name directly? (e.g., "small", "demo")
    │   └── YES → Use that session type
    │
    └── None of the above → INVALID → Show error on kiosk
```

### Step 4: Session Parameters are Resolved
Once the session type is known, parameters are loaded:

| Parameter | Meaning | Example (small) |
|-----------|---------|-----------------|
| `sval` | Shampoo duration (seconds) | 120 |
| `cval` | Conditioner duration | 120 |
| `dval` | Disinfectant duration | 60 |
| `wval` | Water rinse duration | 60 |
| `dryval` | Dryer duration | 480 |
| `fval` | Flush duration | 60 |
| `wt` | Wait/pump prime time | 30 |
| `stval` | Stage wait value | 10 |
| `msgval` | Massage time | 10 |
| `tdry` | Towel dry time | 30 |
| `pr` | Process type (10 = include disinfectant, 20 = skip) | 20 |
| `ctype` | Conditioner type (100 = normal, 200 = medicated) | 100 |
| `stage` | Starting stage (1-6, allows mid-session resume) | 1 |

Sources for parameters (in priority order):
1. **Database booking record** (booking_code lookup)
2. **Database session_config** (mobile number lookup)
3. **Local config** (`~/.spotless/config.json`)
4. **Hardcoded defaults** (`config_manager.py → DEFAULT_SESSION_CONFIGS`)

### Step 5: Session Execution (spotless_functions.py → Spotless)
The main `Spotless()` function orchestrates the entire bath:

```
Spotless Function Flow:
    │
    ├── 1. Turn on roof lights (s9)
    ├── 2. Prime shampoo system (fill tank → drain to line)
    ├── 3. Onboarding audio announcement
    │
    ├── Stage 1: SHAMPOO
    │   ├── Activate pump p1 (async, primes shampoo line)
    │   ├── Play shampoo audio
    │   ├── Turn ON: s8, s1, s2, s4, d1, pump (for sval seconds)
    │   ├── Turn OFF all above
    │   └── Massage time (msgval seconds)
    │
    ├── Stage 2: WATER RINSE 1
    │   ├── Play water audio
    │   ├── Turn ON: s8, s5, s2, s4, pump (for wval seconds)
    │   ├── Turn OFF all above
    │   └── Prime for conditioner
    │
    ├── Stage 3: CONDITIONER (or MEDICATED BATH if ctype=200)
    │   ├── Activate pump p2 (async)
    │   ├── Turn ON: s8, s1, s2, s4, d1, pump (for cval seconds)
    │   ├── Turn OFF all above
    │   └── Massage time (msgval seconds)
    │
    ├── Stage 4: WATER RINSE 2
    │   ├── Turn ON: s8, s5, s2, s4, pump (for 2×wval seconds)
    │   └── Turn OFF all above
    │
    ├── Stage 5: TOWEL DRY
    │   ├── Play towel dry audio
    │   └── Wait tdry seconds
    │
    ├── Stage 6: DRYER
    │   ├── Play dryer audio
    │   ├── Dry cycle 1 (dryval × 0.5 seconds) — Pi GPIO "dry"
    │   ├── Break (15 seconds)
    │   └── Dry cycle 2 (dryval × 0.5 seconds) — Pi GPIO "dry"
    │
    ├── Offboarding audio
    │
    ├── DISINFECTANT (only if pr=10)
    │   ├── Spray disinfectant: s8, s3, s4, s2, d2, pump (dval seconds)
    │   └── Water rinse: s8, s5, s2, s4, pump (dval seconds)
    │
    ├── Empty tanks (async: d1+ro2, d2+ro4)
    ├── Thank you audio
    └── Lights off, roof lights auto-control
```

### Step 6: Frontend Progress Display
While the backend runs the session, the kiosk UI shows real-time progress:
- **WebSocket events** (`stage_start`, `stage_progress`, `stage_complete`) are emitted every second.
- The session page (`kiosk/templates/session.html`) displays: current stage name, progress bar, elapsed/remaining time.
- An emergency **STOP** button sends `POST /api/session/stop` which calls `all_off()`.

### Step 7: Session Completion
When the session finishes:
1. **Database update**: Session logged as "completed" with duration (`db_manager.log_session_complete`)
2. **Booking status update**: If it was a booking, status changes to "completed"
3. **Local log**: Session saved to `~/.spotless/sessions/{timestamp}_{type}.json`
4. **Email notification**: Sent via Gmail SMTP to management
5. **Kiosk UI**: Shows "Session Complete — Thank you!" and returns to scan screen

---

## 5. Relay-to-Device Mapping

### ESP32 Node 1 (spotless_node1)

| Relay | Label | GPIO | Device Name | Purpose |
|-------|-------|------|-------------|---------|
| 1 | S1_220V | 9 | pump | 220V Main Pump / Solenoid |
| 2 | P1_P2 | 10 | p3 | Pumps P1 & P2 |
| 3 | FP1 | 11 | d1 | Flow Pump 1 (Diaphragm) |
| 4 | RS1_DS2 | 12 | ro1 | RO Solenoid 1 & Dia Solenoid 2 |
| 5 | RS2_DS1 | 13 | ro2 | RO Solenoid 2 & Dia Solenoid 1 |
| 6 | BACK1 | 14 | p2 | Backflow 1 / Peristaltic Pump 2 |
| 7 | BACK2 | 21 | p1 | Backflow 2 / Peristaltic Pump 1 |

### ESP32 Node 2 (spotless_node2)

| Relay | Label | GPIO | Device Name | Purpose |
|-------|-------|------|-------------|---------|
| 1 | S1_220V | 9 | s9 | 220V Solenoid (was: roof) |
| 2 | P1_P2 | 10 | s7 | Pumps (was: bottom) |
| 3 | FP1 | 11 | d2 | Flow Pump 2 (Diaphragm) |
| 4 | RS1_DS2 | 12 | ro3 | RO Solenoid 3 |
| 5 | RS2_DS1 | 13 | ro4 | RO Solenoid 4 |
| 6 | BACK1 | 14 | p5 | Peristaltic Pump 5 |
| 7 | BACK2 | 21 | p4 | Peristaltic Pump 4 |

### ESP32 Node 3 (spotless_node3)

| Relay | Label | GPIO | Device Name | Purpose |
|-------|-------|------|-------------|---------|
| 1 | S1_220V | 9 | s8 | Solenoid 8 (was: flushmain) |
| 2 | P1_P2 | 10 | s6 | Solenoid 6 (was: top) |
| 3 | FP1 | 11 | s5 | Solenoid 5 |
| 4 | RS1_DS2 | 12 | s3 | Solenoid 3 |
| 5 | RS2_DS1 | 13 | s4 | Solenoid 4 |
| 6 | BACK1 | 14 | s2 | Solenoid 2 |
| 7 | BACK2 | 21 | s1 | Solenoid 1 |

### Raspberry Pi Direct GPIO

| Relay | GPIO Pin | Purpose |
|-------|----------|---------|
| dry | 14 | Dryer relay |
| geyser | 18 | Geyser/water heater relay |

---

## 6. MQTT Topic Structure

```
spotless/nodes/{node_id}/relays/{n}/command    ← Pi sends to ESP32
spotless/nodes/{node_id}/relays/{n}/state      ← ESP32 reports back
spotless/nodes/{node_id}/relays/all/command    ← Pi sends to all relays
spotless/nodes/{node_id}/status                ← ESP32 heartbeat (retained)
spotless/nodes/{node_id}/request               ← Pi requests status
```

**Command payload:** `{"state": "ON"}` or `{"state": "OFF"}`
**Status payload:** `{"online": true, "ip": "192.168.0.x", "rssi": -45, "node_id": "...", "relay_count": 7, "uptime": 1234}`

---

## 7. Session Types

### Full Bath Sessions (handler: `Spotless` or `fromDisinfectant`)

| Type | Description | Total Duration (approx) |
|------|-------------|------------------------|
| small | Small Pet Bath | ~15 min |
| large | Large Pet Bath | ~20 min |
| custdiy | Customer DIY (includes disinfectant) | ~18 min |
| medsmall | Medicated Bath - Small | ~14 min |
| medlarge | Medicated Bath - Large | ~18 min |
| onlydisinfectant | Disinfectant Only | ~5 min |

### Utility Sessions (single operations)

| Type | Handler | Duration | Purpose |
|------|---------|----------|---------|
| quicktest | test_relays | ~90s | Test each relay for 2s |
| demo | demo | ~200s | Sequential 5s relay activation |
| onlydrying | Dryer | 300s | Dryer only |
| onlywater | just_water | 90s | Water rinse only |
| onlyflush | Flush | 60s | Flush pipes |
| onlyshampoo | just_shampoo | 60s | Shampoo only |
| empty001 | Empty_tank | 180s | Drain tanks |

---

## 8. Database Schema (AWS RDS Aurora MySQL — petgully_db)

### Key Tables

**session_config** — Per-customer session parameters
```
mobile_number (PK), customer_name, session_type,
sval, cval, dval, wval, dryval, fval, wt, stval, msgval, tdry, pr, ctype,
is_active, created_at, updated_at
```

**bookings** — Booking records from the booking app
```
id, booking_code, customer_id, pet_id, session_type,
sval, cval, dval, wval, dryval, fval, wt, ctype,
status (pending/confirmed/completed), created_at
```

**session_logs** — Session execution logs
```
id, mobile_number, machine_id, session_type, qr_code, params,
activated_at, started_at, completed_at, duration, status,
stages (JSON), error_message
```

**customers** — Customer accounts
```
id, email, password_hash, name, phone, is_admin, created_at
```

---

## 9. File Structure — Raspberry Pi Code

```
raspberry_pi/
├── main.py                 ← Entry point. CLI args: --kiosk, --session, --test
├── config.py               ← MQTT, node, and relay configuration constants
├── config_manager.py       ← Machine ID, session config, offline storage
├── mqtt_client.py          ← Low-level MQTT pub/sub (paho-mqtt)
├── node_controller.py      ← High-level ESP32 node management
├── device_map.py           ← Friendly names (p1, ro1, pump) → node+relay
├── gpio_controller.py      ← Direct Pi GPIO (dry, geyser) via gpiod
├── spotless_functions.py   ← Core bath logic (Shampoo, Water, Dryer, etc.)
├── db_manager.py           ← AWS RDS Aurora MySQL queries
├── email_service.py        ← Gmail SMTP notifications
├── logging_config.py       ← Structured logging setup
├── requirements.txt        ← Python dependencies
├── .env.example            ← Environment variable template
│
├── kiosk/                  ← Customer-facing web UI
│   ├── web_server.py       ← Flask routes, QR validation, session runner
│   ├── templates/
│   │   ├── index.html      ← Scan/input page
│   │   └── session.html    ← Session progress page
│   └── static/
│       ├── css/style.css
│       ├── js/app.js       ← QR input handling, WebSocket
│       └── js/session.js   ← Progress bar, stage display
│
├── admin/                  ← Admin/testing dashboard
│   ├── admin_server.py     ← Flask + MQTT relay control (port 8080)
│   ├── templates/dashboard.html
│   └── static/{css,js}/
│
└── scripts/
    ├── setup_and_check.sh  ← First-time Pi setup (Mosquitto, venv, deps)
    ├── check_nodes.sh      ← Quick ESP32 connectivity check
    ├── setup_kiosk.sh      ← Kiosk auto-start config
    ├── start_kiosk.sh      ← Start script
    └── spotless.service    ← systemd service file
```

---

## 10. Testing Plan — Sections

### Section A: Infrastructure
1. **MQTT Broker** — Mosquitto running, publish/subscribe works
2. **ESP32 Connectivity** — All 3 nodes connect and report status
3. **Database Connection** — Can reach AWS RDS Aurora

### Section B: Individual Relay Testing
4. **Admin Dashboard** — Toggle each relay via web UI, confirm physical activation
5. **Pi GPIO** — Test dry and geyser relays directly

### Section C: QR Code Flow
6. **Prefix-based QR** — Scan "SM001", "TEST", "DRY", etc. and verify correct session type
7. **Database booking QR** — Scan a PG-prefixed booking code, verify DB lookup
8. **Invalid QR** — Scan garbage, verify error is shown

### Section D: Session Execution
9. **Quick Test** — Run `quicktest` to cycle all relays
10. **Demo Mode** — Run `demo` to see sequential activation
11. **Water Only** — Run `onlywater` to test basic pump operation
12. **Full Small Bath** — Run `small` session end-to-end (shortened durations for testing)

### Section E: Frontend + WebSocket
13. **Kiosk UI** — Load index page, scan input works, quick buttons work
14. **Session Progress** — Progress bar updates in real-time, stage transitions work
15. **Emergency Stop** — Stop button halts session and turns off all relays

### Section F: Database + Email
16. **Session Logging** — Verify session_logs table is updated
17. **Booking Status** — Verify bookings table status changes to "completed"
18. **Email Notification** — Verify email is sent on session completion

---

## 11. How to Run

```bash
# Kiosk mode (production)
cd ~/IOT_Spotless/raspberry_pi
source venv/bin/activate
python main.py --kiosk

# Admin dashboard (testing)
python admin/admin_server.py

# Quick relay test
python main.py --test

# Specific session via CLI
python main.py --session small --qr "TEST001"

# List all session types
python main.py --list
```
