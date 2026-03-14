---
name: flash-esp32
description: >-
  Flash ESP32-S3 firmware for Project Spotless nodes. Use when the user wants to
  flash, upload, or program an ESP32 node, update node firmware, or mentions
  flashing node 1, node 2, or node 3.
---

# Flash ESP32-S3 Node — Project Spotless

## Overview

This skill flashes firmware onto ESP32-S3 DevKitC boards for Project Spotless.
There are 3 nodes, each with its own firmware in the project repo.

## Node Reference

| Node | ID | Firmware Directory | Config File |
|------|----|--------------------|-------------|
| Node 1 | spotless_node1 | `esp32_node1/` | `esp32_node1/include/config.h` |
| Node 2 | spotless_node2 | `esp32_node2/` | `esp32_node2/include/config.h` |
| Node 3 | spotless_node3 | `esp32_node3/` | `esp32_node3/include/config.h` |

## Prerequisites

PlatformIO CLI must be available. If `pio --version` fails:

```powershell
pip install platformio
$env:Path += ";C:\Users\deepa\AppData\Roaming\Python\Python313\Scripts"
```

## Flash Workflow

Follow these steps exactly when the user asks to flash a node:

### Step 1: Identify which node(s) to flash

Ask the user which node (1, 2, or 3) if not specified. They may say "all" for all three.

### Step 2: Confirm config.h settings

Read the node's `config.h` and confirm with the user:

```cpp
#define WIFI_SSID     "..."           // Must match their WiFi (2.4 GHz only)
#define WIFI_PASSWORD "..."           // Must be correct
#define MQTT_BROKER   "192.168.0.16"  // Must match Raspberry Pi static IP
```

If the user wants to change WiFi or MQTT broker IP, update `config.h` before flashing.

### Step 3: Ensure PlatformIO PATH is set

Run in the shell before any `pio` command:

```powershell
$env:Path += ";C:\Users\deepa\AppData\Roaming\Python\Python313\Scripts"
```

### Step 4: Detect the COM port

The user should have the ESP32 plugged in via USB. Detect the port:

```powershell
mode 2>&1 | Select-String "COM"
```

This returns something like `Status for device COM12:`. Extract the COM port number.

If no COM port is found:
- Ask the user to check the USB cable connection
- They may need to install the CP210x or CH340 driver
- ESP32-S3 native USB should work without extra drivers on Windows 10+

### Step 5: Build and flash

Run from the node's directory:

```powershell
pio run --target upload --upload-port COM{N} 2>&1
```

Where `{N}` is the detected COM port number.

**Working directories:**
- Node 1: `esp32_node1/`
- Node 2: `esp32_node2/`
- Node 3: `esp32_node3/`

**Expected timings:**
- First flash ever: ~10-15 minutes (downloads ESP32-S3 toolchain + framework)
- Subsequent flashes: ~25-30 seconds

### Step 6: Verify success

Look for `[SUCCESS]` in the output. Report to the user:
- Flash status (success/fail)
- If flashing multiple nodes, ask them to swap the USB cable to the next ESP32

### Step 7: For multiple nodes

When flashing all 3 nodes:
1. Flash Node 1 → ask user to unplug and connect Node 2
2. Re-detect COM port (it may change between boards)
3. Flash Node 2 → ask user to unplug and connect Node 3
4. Re-detect COM port
5. Flash Node 3

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `pio` not recognized | Run: `$env:Path += ";C:\Users\deepa\AppData\Roaming\Python\Python313\Scripts"` |
| No COM port detected | Check USB cable. Try a different port. Install CP210x/CH340 driver. |
| Upload fails with timeout | Hold the **BOOT** button on ESP32 while upload starts, release after "Connecting..." |
| `board not found` error | Verify `platformio.ini` has `board = esp32-s3-devkitc-1` |
| Wrong node flashed | Each node's `config.h` has a unique `NODE_ID`. Verify before flashing. |

## platformio.ini Reference

All 3 nodes use identical build settings (only `config.h` differs):

```ini
[env:esp32s3]
platform = espressif32
board = esp32-s3-devkitc-1
framework = arduino
monitor_speed = 115200
lib_deps = 
    knolleary/PubSubClient@^2.8
    bblanchon/ArduinoJson@^7.0.0
build_flags = 
    -DCORE_DEBUG_LEVEL=3
    -DARDUINO_USB_CDC_ON_BOOT=1
```

## Quick Examples

**User says:** "Flash node 1"
→ Read config.h, detect COM port, run `pio run --target upload --upload-port COM{N}` in `esp32_node1/`

**User says:** "Flash all nodes"
→ Flash node 1, ask to swap, flash node 2, ask to swap, flash node 3

**User says:** "Update WiFi to MyNetwork and flash node 2"
→ Update `WIFI_SSID` and `WIFI_PASSWORD` in `esp32_node2/include/config.h`, then flash

**User says:** "Change MQTT broker to 192.168.1.100 and flash all"
→ Update `MQTT_BROKER` in all 3 `config.h` files, then flash each sequentially
