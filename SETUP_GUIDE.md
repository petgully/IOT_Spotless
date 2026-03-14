# Project Spotless - Hardware Setup Guide

**Simple step-by-step guide to set up your hardware system.**

---

## 📋 Prerequisites

- Raspberry Pi with Project Spotless code installed
- 3x ESP32 devices (Node 1, Node 2, Node 3)
- USB cable for ESP32 programming
- WiFi network credentials
- PlatformIO or Arduino IDE installed

---

## 🔧 STEP 1: Configure ESP32 Nodes

### 1.1 Find Raspberry Pi IP Address

**On Raspberry Pi, run:**
```bash
hostname -I
```

**Note down the IP address** (e.g., `192.168.0.16`)

---

### 1.2 Configure ESP32 Node 1

**Location:** `Project_Spotless/esp32_node1/include/config.h`

**Edit these lines:**
```cpp
#define WIFI_SSID     "YOUR_WIFI_SSID"           // Your WiFi name
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"       // Your WiFi password
#define MQTT_BROKER   "192.168.0.16"            // Raspberry Pi IP (from step 1.1)
#define NODE_ID       "spotless_node1"          // Already correct
```

**Save the file.**

**Upload to ESP32:**
- **PlatformIO:** Open folder in VS Code → Click "Upload" button
- **Arduino IDE:** Open `src/main.cpp` → Select ESP32 board → Upload

---

### 1.3 Configure ESP32 Node 2

**Location:** `Project_Spotless/esp32_node2/include/config.h`

**Edit these lines:**
```cpp
#define WIFI_SSID     "YOUR_WIFI_SSID"           // Same WiFi as Node 1
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"       // Same WiFi password
#define MQTT_BROKER   "192.168.0.16"            // Same Raspberry Pi IP
#define NODE_ID       "spotless_node2"          // Already correct
```

**Save and upload to ESP32 Node 2.**

---

### 1.4 Configure ESP32 Node 3

**Location:** `Project_Spotless/esp32_node3/include/config.h`

**Edit these lines:**
```cpp
#define WIFI_SSID     "YOUR_WIFI_SSID"           // Same WiFi as others
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"       // Same WiFi password
#define MQTT_BROKER   "192.168.0.16"            // Same Raspberry Pi IP
#define NODE_ID       "spotless_node3"          // Already correct
```

**Save and upload to ESP32 Node 3.**

---

### 1.5 Verify ESP32 Connection

**On Raspberry Pi, check MQTT logs:**
```bash
sudo mosquitto_sub -h localhost -t "spotless/nodes/+/status" -v
```

**Power on each ESP32 one by one.** You should see status messages like:
```
spotless/nodes/spotless_node1/status {"online":true}
spotless/nodes/spotless_node2/status {"online":true}
spotless/nodes/spotless_node3/status {"online":true}
```

**Press `Ctrl+C` to stop monitoring.**

---

## 🖥️ STEP 2: Setup Raspberry Pi Auto-Start Kiosk Mode

### 2.1 Navigate to Project Directory

```bash
cd ~/Project_Spotless/raspberry_pi
```

---

### 2.2 Run Setup Script

**This will install dependencies and configure auto-start:**
```bash
sudo ./scripts/setup_kiosk.sh
```

**This script will:**
- Install required packages (Python, Chromium, Mosquitto, etc.)
- Create `spotless` user
- Set up systemd service for auto-start
- Configure MQTT broker
- Set up kiosk mode

---

### 2.3 Enable Systemd Service (Alternative Method)

**If you prefer systemd service instead of desktop autostart:**

```bash
# Copy service file
sudo cp scripts/spotless.service /etc/systemd/system/

# Reload systemd
sudo systemctl daemon-reload

# Enable service (starts on boot)
sudo systemctl enable spotless

# Start service now
sudo systemctl start spotless

# Check status
sudo systemctl status spotless
```

---

### 2.4 Verify Kiosk Setup

**Check if service is running:**
```bash
sudo systemctl status spotless
```

**Check if web server is accessible:**
```bash
curl http://localhost:5000
```

**If you see HTML output, the server is running! ✅**

---

### 2.5 Reboot to Test Auto-Start

```bash
sudo reboot
```

**After reboot, the kiosk should:**
- Start automatically
- Open Chromium in full-screen mode
- Display the QR scan interface

**If kiosk doesn't start automatically, check logs:**
```bash
journalctl -u spotless -n 50
```

---

## 🧪 STEP 3: Run Demo Test

### 3.1 Start System (if not already running)

**If kiosk didn't auto-start, start manually:**
```bash
cd ~/Project_Spotless/raspberry_pi
python3 main.py --kiosk
```

**Or via systemd:**
```bash
sudo systemctl start spotless
```

---

### 3.2 Access Kiosk Interface

**Option 1: On Raspberry Pi display**
- Kiosk should be running in full-screen Chromium

**Option 2: From another device**
- Open browser on phone/laptop
- Go to: `http://RASPBERRY_PI_IP:5000`
- Example: `http://192.168.0.16:5000`

---

### 3.3 Run Demo Session

**In the QR code input field, type:**
```
demo
```

**Click "START SESSION"**

**What should happen:**
1. ✅ Validation passes (no error)
2. ✅ Session starts
3. ✅ Relays activate sequentially:
   - **Node 1:** p1 → p2 → ro2 → ro1 → d1 → p3 → pump (5 sec each)
   - **Node 2:** p4 → p5 → ro4 → ro3 → d2 → s7 → s9 (5 sec each)
   - **Node 3:** s1 → s2 → s4 → s3 → s5 → s6 → s8 (5 sec each)
   - **Raspberry Pi:** dry (GPIO 14) → geyser (GPIO 18) (5 sec each)
4. ✅ Session completes successfully

**Total demo duration:** ~200 seconds (~3.5 minutes)

---

### 3.4 Test Other Session Types

**Try these codes in the QR input:**

| Code | Description |
|------|-------------|
| `small` | Small Pet Bath Session |
| `large` | Large Pet Bath Session |
| `quicktest` | Quick Relay Test |
| `demo` | Demo Mode (sequential relays) |

**Invalid codes (should show error):**
- `xyz123` → Should show "Invalid QR code" error ✅
- `test123` → Should show "Invalid QR code" error ✅

---

## 🔍 Troubleshooting

### ESP32 Not Connecting

**Check WiFi credentials:**
- Verify SSID and password are correct
- Ensure WiFi is 2.4GHz (ESP32 doesn't support 5GHz)

**Check MQTT broker:**
- Verify Raspberry Pi IP is correct
- Test: `ping RASPBERRY_PI_IP`
- Check Mosquitto is running: `sudo systemctl status mosquitto`

**Check ESP32 serial output:**
- Connect ESP32 via USB
- Open Serial Monitor (115200 baud)
- Look for connection errors

---

### Kiosk Not Starting

**Check service status:**
```bash
sudo systemctl status spotless
```

**Check logs:**
```bash
journalctl -u spotless -n 100
```

**Check if port 5000 is in use:**
```bash
sudo netstat -tlnp | grep 5000
```

**Manual start for testing:**
```bash
cd ~/Project_Spotless/raspberry_pi
python3 main.py --kiosk
```

---

### Demo Not Working

**Check if all ESP32 nodes are online:**
```bash
python3 main.py --session quicktest
```

**Check MQTT connection:**
```bash
sudo mosquitto_sub -h localhost -t "spotless/nodes/+/status" -v
```

**Check Raspberry Pi logs:**
```bash
tail -f ~/.spotless/logs/spotless_*.log
```

---

## ✅ Verification Checklist

- [ ] All 3 ESP32 nodes configured with correct WiFi and MQTT broker IP
- [ ] All 3 ESP32 nodes uploaded and powered on
- [ ] All 3 ESP32 nodes showing online status in MQTT
- [ ] Raspberry Pi setup script completed successfully
- [ ] Systemd service enabled and running
- [ ] Kiosk accessible at `http://localhost:5000`
- [ ] Demo session runs successfully
- [ ] Invalid codes show error message
- [ ] Auto-start works after reboot

---

## 📝 Quick Reference

### Start Kiosk Manually
```bash
cd ~/Project_Spotless/raspberry_pi
python3 main.py --kiosk
```

### Stop Kiosk Service
```bash
sudo systemctl stop spotless
```

### Restart Kiosk Service
```bash
sudo systemctl restart spotless
```

### View Logs
```bash
journalctl -u spotless -f
```

### Test Relay Sequence
```bash
python3 main.py --session demo --qr DEMO_TEST
```

---

## 🎉 Setup Complete!

Your system is now ready to use. The kiosk will start automatically on boot, and you can run demo sessions or any other session type through the web interface.

**Next Steps:**
- Configure machine ID: `python3 main.py --setup`
- Test other session types
- Set up booking system integration (optional)

---

**Need Help?** Check the logs or review the configuration files.
