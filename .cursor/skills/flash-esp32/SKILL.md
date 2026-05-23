---
name: flash-esp32
description: >-
  Flash ESP32-S3 firmware for Project Spotless nodes. Use when the user wants to
  flash, upload, or program an ESP32 node, update node firmware, or mentions
  flashing node 1, node 2, or node 3.
---

# Flash ESP32-S3 Node — Project Spotless

## Overview

This skill flashes firmware onto ESP32-S3 DevKitC-1 boards for Project Spotless.
Always use the wrapper script `tools/flash_node.ps1` rather than calling
`pio` directly — it auto-detects PlatformIO regardless of where Python is
installed, auto-detects the COM port, and reports clear success/failure.

## Node Reference

| Node | ID | Firmware Directory | Config File |
|------|----|--------------------|-------------|
| Node 1 | spotless_node1 | `esp32_node1/` | `esp32_node1/include/config.h` |
| Node 2 | spotless_node2 | `esp32_node2/` | `esp32_node2/include/config.h` |
| Node 3 | spotless_node3 | `esp32_node3/` | `esp32_node3/include/config.h` |

All 3 nodes share identical `platformio.ini` (`board = esp32-s3-devkitc-1`)
and identical pin assignments. Only `NODE_ID` and the header comment differ.

## Workflow — when the user asks to flash a node

### Step 1: Identify the node(s)

Ask the user which node (1, 2, 3, or "all") if not specified.

### Step 2: Run the wrapper

The wrapper handles PlatformIO discovery, COM port detection, config.h
display, and the actual flash. Invoke it as:

```powershell
# Single node
.\tools\flash_node.ps1 1

# All three (prompts to swap USB cable between)
.\tools\flash_node.ps1 all

# Update WiFi + Pi IP at the same time as flashing
.\tools\flash_node.ps1 all -WifiSsid "..." -WifiPassword "..." -MqttBroker "192.168.0.20"

# Skip "Proceed?" prompt (for scripted runs)
.\tools\flash_node.ps1 1 -Yes

# Sanity-check the toolchain without flashing
.\tools\flash_node.ps1 -Check
```

### Step 3: Watch for success

The wrapper prints `[OK] Node N flashed successfully.` on success or
`[FAIL] Node N flash FAILED (exit X).` with the most common fixes on failure.
Trust the wrapper's exit code (0 = success, non-zero = failure) — the
PlatformIO `[SUCCESS]` line in the underlying output is incidental.

### Step 4: For "all" mode

The wrapper handles cable-swap prompts automatically:
1. Flashes node 1
2. Prompts: "Disconnect node 1 and connect node 2. Press Enter when ready"
3. Re-detects COM port (it usually changes)
4. Flashes node 2
5. Repeats for node 3
6. Prints a summary table

## Expected timings

- **First flash on a new machine:** ~10-15 minutes (PlatformIO downloads the
  ESP32-S3 toolchain and Arduino framework, ~150 MB)
- **Subsequent flashes:** ~25-30 seconds per board

## Troubleshooting

| Problem | Solution |
|---------|----------|
| `pio not found` | Run `pip install --user platformio`. Wrapper will find it on retry. |
| `Multiple COM ports found, none clearly an ESP32` | Plug in the ESP32 and re-run. Bluetooth virtual COM ports confuse auto-detect. Pass `-Port COMx` to override. |
| `Upload fails with timeout` | Hold the **BOOT** button on the ESP32 while the upload starts; release after "Connecting..." appears. |
| `Failed to connect to ESP32-S3` | Try a different USB cable (charge-only cables have no data lines). Try a different USB port. |
| Wrong node flashed | Each node's `config.h` has a unique `NODE_ID`. The wrapper shows it before flashing — the operator should confirm. |

## Manual fallback (only if the wrapper fails)

If `flash_node.ps1` itself won't run for some reason, here's the manual flow
it replaces:

```powershell
# 1. Make sure pio is on PATH. Common locations (do not hardcode):
#      %USERPROFILE%\.platformio\penv\Scripts\pio.exe
#      %APPDATA%\Python\Python<ver>\Scripts\pio.exe
#      %LOCALAPPDATA%\Programs\Python\Python<ver>\Scripts\pio.exe
#    Or use:  python -m platformio --version

# 2. Detect COM port
[System.IO.Ports.SerialPort]::GetPortNames()

# 3. Flash from the node directory
cd esp32_node1
pio run --target upload --upload-port COMx
```

But default to the wrapper. It exists specifically so non-technical operators
don't need to know any of the above.

## platformio.ini reference

Identical across all 3 nodes:

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

## Quick examples (intent → command)

| User says | Command |
|-----------|---------|
| "Flash node 1" | `.\tools\flash_node.ps1 1` |
| "Flash all nodes" | `.\tools\flash_node.ps1 all` |
| "Flash node 2 and watch the serial output" | `.\tools\flash_node.ps1 2 -Monitor` |
| "Update WiFi to MyNetwork and flash all" | `.\tools\flash_node.ps1 all -WifiSsid "MyNetwork" -WifiPassword "..."` |
| "Change MQTT broker to 192.168.1.100 and flash all" | `.\tools\flash_node.ps1 all -MqttBroker "192.168.1.100"` |
| "Just check if PlatformIO is installed" | `.\tools\flash_node.ps1 -Check` |
