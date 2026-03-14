# Project Spotless - Quick Setup Guide

Simple step-by-step instructions to set up the entire system from scratch.

---

## What You Need

- 1x Raspberry Pi 5 (with Raspberry Pi OS Bookworm)
- 3x ESP32-S3 boards (flashed with node firmware)
- A WiFi router (2.4 GHz - ESP32 does not support 5 GHz)
- A laptop/PC with PlatformIO installed (for flashing ESP32s)
- USB-C cable for ESP32 programming

---

## Part 1: Raspberry Pi Setup

### 1.1 Install Git and Clone the Code

```bash
sudo apt update
sudo apt install -y git
cd ~
git clone https://github.com/petgully/IOT_Spotless.git
cd IOT_Spotless
```

### 1.2 Set a Static IP (So ESP32s Always Find the Pi)

Your Pi needs a fixed IP address. Without this, the IP changes every reboot and ESP32s won't know where to connect.

**Find your current network info:**

```bash
# Your current IP
hostname -I

# Your router/gateway IP (usually 192.168.0.1 or 192.168.1.1)
ip route | grep default

# Your connection name
nmcli connection show
```

**Set the static IP:**

Replace `preconfigured` with your actual connection name from above.
Replace `192.168.0.16` with your desired IP.
Replace `192.168.0.1` with your actual gateway.

```bash
sudo nmcli connection modify preconfigured \
  ipv4.addresses 192.168.0.16/24 \
  ipv4.gateway 192.168.0.1 \
  ipv4.dns "8.8.8.8,8.8.4.4" \
  ipv4.method manual

sudo nmcli connection up preconfigured
```

**Verify:**

```bash
hostname -I
# Should show: 192.168.0.16
```

**To undo (go back to dynamic IP):**

```bash
sudo nmcli connection modify preconfigured \
  ipv4.method auto \
  ipv4.addresses "" \
  ipv4.gateway "" \
  ipv4.dns ""

sudo nmcli connection up preconfigured
```

### 1.3 Install Mosquitto MQTT Broker

```bash
sudo apt install -y mosquitto mosquitto-clients
```

**Configure it to allow ESP32 connections:**

```bash
sudo tee /etc/mosquitto/conf.d/spotless.conf > /dev/null << 'EOF'
listener 1883
allow_anonymous true
EOF
```

**Important:** If `/etc/mosquitto/conf.d/` has other config files (like `local.conf`), remove them to avoid conflicts:

```bash
# Check for other config files
ls /etc/mosquitto/conf.d/

# Remove any conflicting ones (keep only spotless.conf)
sudo rm /etc/mosquitto/conf.d/local.conf    # if it exists
```

**Start Mosquitto:**

```bash
sudo systemctl enable mosquitto
sudo systemctl restart mosquitto
sudo systemctl status mosquitto
```

You should see `active (running)` in green.

**Test it works:**

```bash
mosquitto_pub -h localhost -t "test" -m "hello"
# No error = working
```

### 1.4 Run the Full Setup Script

This installs Python dependencies, creates the virtual environment, and checks for ESP32 connections:

```bash
cd ~/IOT_Spotless/raspberry_pi
chmod +x scripts/setup_and_check.sh scripts/check_nodes.sh
sudo ./scripts/setup_and_check.sh
```

### 1.5 Create Your .env File

```bash
cp .env.example .env
nano .env
```

Fill in your actual database and email credentials. Save with `Ctrl+O`, exit with `Ctrl+X`.

### 1.6 Start the Kiosk

```bash
cd ~/IOT_Spotless/raspberry_pi
source venv/bin/activate
python3 main.py --kiosk
```

The kiosk web UI will be available at `http://<your-pi-ip>:5000`

---

## Part 2: ESP32 Setup

### 2.1 Update WiFi and MQTT Settings

On your PC, edit each node's config file:

| Node | File |
|------|------|
| Node 1 | `esp32_node1/include/config.h` |
| Node 2 | `esp32_node2/include/config.h` |
| Node 3 | `esp32_node3/include/config.h` |

In each `config.h`, update these 3 lines:

```cpp
#define WIFI_SSID     "YourWiFiName"        // Your 2.4GHz WiFi name
#define WIFI_PASSWORD "YourWiFiPassword"    // Your WiFi password
#define MQTT_BROKER   "192.168.0.16"        // Your Raspberry Pi's static IP
```

Everything else in `config.h` (relay pins, LED pins, etc.) should be left as-is unless you changed the hardware wiring.

### 2.2 Flash Each ESP32

Using PlatformIO (VS Code extension):

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

### 2.3 Monitor ESP32 Serial Output (Optional)

To debug, open serial monitor at 115200 baud:

```bash
pio device monitor --baud 115200
```

You should see:
```
WiFi connected! IP: 192.168.0.xx
Connected to MQTT broker
```

---

## Part 3: Verify Everything Works

### On the Raspberry Pi:

```bash
cd ~/IOT_Spotless/raspberry_pi
./scripts/check_nodes.sh
```

This will show you which ESP32 nodes are online, their IPs, WiFi signal strength, and uptime.

### Quick MQTT test:

```bash
# In one terminal - listen for messages:
mosquitto_sub -h localhost -t "spotless/#" -v

# You should see status messages from connected ESP32 nodes
```

---

## Updating the Code

When changes are pushed from your PC:

**On PC (Windows):**
```bash
git add -A
git commit -m "your message"
git push
```

**On Raspberry Pi:**
```bash
cd ~/IOT_Spotless
git pull
```

For ESP32 changes, you need to re-flash each board from the PC using PlatformIO.

---

## Network Diagram

```
  Internet (optional - for DB & email only)
      |
  [WiFi Router]  (2.4 GHz)
      |
      ├── Raspberry Pi 5     ← Static IP: 192.168.0.16
      |     ├── Mosquitto MQTT Broker (port 1883)
      |     ├── Flask Kiosk Web UI (port 5000)
      |     └── Python control logic
      |
      ├── ESP32 Node 1       ← Dynamic IP (doesn't matter)
      ├── ESP32 Node 2       ← Dynamic IP (doesn't matter)
      └── ESP32 Node 3       ← Dynamic IP (doesn't matter)
```

Only the Pi needs a static IP. ESP32s can have dynamic IPs because they connect TO the Pi (not the other way around).

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Mosquitto won't start | Check `sudo journalctl -u mosquitto -n 20`. Remove conflicting configs in `/etc/mosquitto/conf.d/` |
| ESP32 can't connect to WiFi | Verify SSID/password in `config.h`. Make sure WiFi is 2.4 GHz. |
| ESP32 can't reach MQTT | Check Pi's IP matches `MQTT_BROKER` in `config.h`. Run `ping 192.168.0.16` from another device. |
| Pi IP changed | Set a static IP (see section 1.2 above) |
| `check_nodes.sh` shows nodes offline | Power cycle the ESP32s. Check serial output at 115200 baud. |
| Kiosk won't start | Make sure venv is active: `source venv/bin/activate`. Check `python3 main.py --kiosk` for errors. |
| `git pull` asks for password | Install `gh` on Pi: `sudo apt install gh`, then `gh auth login` |

---

## Useful Commands (Cheat Sheet)

```bash
# Start kiosk
cd ~/IOT_Spotless/raspberry_pi
source venv/bin/activate
python3 main.py --kiosk

# Check node status
./scripts/check_nodes.sh

# Mosquitto status
sudo systemctl status mosquitto

# Watch live MQTT messages
mosquitto_sub -h localhost -t "spotless/#" -v

# Pi IP address
hostname -I

# Restart Mosquitto
sudo systemctl restart mosquitto

# Update code from GitHub
cd ~/IOT_Spotless && git pull
```
