# Project Spotless — Developer Tools

One-command utilities for the Windows-side workflow (flashing ESP32 boards,
provisioning new booths). Designed so non-technical operators can use them
without learning PlatformIO or COM-port wrangling.

---

## `flash_node.ps1` — Flash ESP32-S3 nodes

### Prerequisites (one-time)

1. **Python 3** installed on Windows
2. **PlatformIO**: `pip install --user platformio`
3. **USB cable** (data-capable, not charge-only)
4. **Driver**: ESP32-S3 native USB works without drivers on Win 10+. For
   older boards using CP210x, install
   <https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers>

### Quick usage

| Command | Effect |
|---|---|
| `.\tools\flash_node.ps1 1` | Flash node 1 with whatever `config.h` currently has |
| `.\tools\flash_node.ps1 2` | Flash node 2 |
| `.\tools\flash_node.ps1 3` | Flash node 3 |
| `.\tools\flash_node.ps1 all` | Flash all 3 sequentially (prompts to swap USB cable between each) |
| `.\tools\flash_node.ps1 -Check` | Just verify PlatformIO + COM port detection |
| `.\tools\flash_node.ps1 1 -Monitor` | Flash node 1 and immediately open the serial monitor |
| `.\tools\flash_node.ps1 1 -Yes` | Skip the "proceed?" confirmation |

### Update WiFi / Pi IP and flash in one step

When deploying to a new booth, change the firmware's WiFi credentials and
MQTT broker IP without manually editing `config.h`:

```powershell
.\tools\flash_node.ps1 all `
    -WifiSsid "BoothWiFi-2G" `
    -WifiPassword "secret123" `
    -MqttBroker "192.168.0.20" `
    -Yes
```

This patches each node's `config.h` (same WIFI/MQTT for all 3 — only `NODE_ID`
remains different) and flashes them in sequence.

### Override auto-detection

```powershell
.\tools\flash_node.ps1 1 -Port COM5      # Force a specific COM port
```

The script pre-validates that `COM5` actually exists before launching
PlatformIO, so a typo gets caught early.

> **Note:** `-Port` is **ignored** in `all` mode — the COM port almost always
> changes between physically different boards, so `all` always re-detects.

### Interactive vs. unattended

If you forget to pass a node argument, the script prompts:

```
Which node? (1, 2, 3, or all)
```

For **fully unattended** runs (CI, scripted deployment), you must pass:
- A node argument (`1`, `2`, `3`, or `all`)
- `-Yes` to skip the "Proceed?" confirmation
- ⚠ Even with `-Yes`, `all` mode still pauses to ask you to swap the USB
  cable between boards. There is no way around this — only one board can be
  on USB at a time.

### What the script does, in order

1. **Locates `pio.exe`** — checks PATH, then standard install locations
   (`%USERPROFILE%\.platformio\penv\Scripts`, `%APPDATA%\Python\Python*\Scripts`,
   etc.). Adds it to PATH for the session if needed.
2. **Detects the ESP32 COM port** — prefers ports whose friendly name matches
   `CP210`, `CH340`, `USB Serial`, `JTAG`, `ESP32`, or `Silicon Labs`.
3. **Reads `config.h`** and shows you `NODE_ID`, `WIFI_SSID`, `MQTT_BROKER`
   (password is masked) so you confirm the right values are about to be
   flashed.
4. **(Optional)** Patches `config.h` with values from `-WifiSsid` / `-WifiPassword`
   / `-MqttBroker` flags.
5. **Asks "Proceed?"** unless `-Yes` is set.
6. **Runs `pio run --target upload --upload-port COMx`** in the right
   `esp32_node{N}/` directory.
7. **Reports success/failure** with the most common fixes when it fails.

### Common issues

| Problem | Fix |
|---|---|
| `pio not found` | Run `pip install --user platformio`. The script will find it on retry. |
| `Multiple COM ports found, none clearly an ESP32` | Plug in the ESP32 and re-run, or pass `-Port COMx` explicitly. Bluetooth virtual COM ports trip auto-detection. |
| `Upload fails with timeout` | Hold the **BOOT** button on the ESP32 while the upload starts; release after "Connecting..." appears. |
| `A fatal error occurred: Failed to connect to ESP32-S3` | Try a different USB cable. Some cables are charge-only and have no data lines. |
| First flash takes 10+ minutes | Normal — PlatformIO is downloading the ESP32-S3 toolchain (~150 MB). Subsequent flashes take ~30 seconds. |

### Per-node reference

| Node | NODE_ID | Firmware dir | Purpose |
|---|---|---|---|
| 1 | `spotless_node1` | `esp32_node1/` | Container 1: shampoo / conditioner pumps |
| 2 | `spotless_node2` | `esp32_node2/` | Container 2: disinfectant + flush |
| 3 | `spotless_node3` | `esp32_node3/` | Bath line solenoid valves |

All 3 use identical pin assignments and `platformio.ini`. Only `NODE_ID` and the
header comment differ between them — and the script never touches those.

---

## When to use this vs. PlatformIO directly

Use **`flash_node.ps1`** for:
- Routine flashing (single node, all three, with-or-without config update)
- Onboarding a new team member
- Field deployment to a new booth

Use **raw `pio` commands** (or PlatformIO IDE) for:
- Editing the firmware C++ code itself
- Debugging with breakpoints / OTA
- Anything outside the simple "flash all 3 with these settings" workflow
