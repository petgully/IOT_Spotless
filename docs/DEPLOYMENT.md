# Project Spotless — Deployment Runbook

> Single-page operator guide. If you are setting up a new booth, this is the
> only document you need.

---

## TL;DR — Setting up a new machine (~20 min, mostly hands-off)

You are at a fresh booth with one Raspberry Pi 5 + 3 ESP32 boards. You also
need a **Windows laptop** with USB to flash the ESP32s.

### Part A — Raspberry Pi (~15 min)

1. **Flash Raspberry Pi OS Bookworm (64-bit)** to an SD card. Use the official
   Raspberry Pi Imager. In Imager → "Edit settings", set:
   - Username: `spotless`
   - Password: pick something memorable (not the default!)
   - WiFi network + password (must be **2.4 GHz** — ESP32 doesn't do 5 GHz)
   - Locale, timezone, enable SSH if you want remote access

2. **Boot the Pi**, wait for it to connect to WiFi, open a Terminal window
   (or SSH in from your laptop).

3. **Run one command:**

   ```bash
   curl -fsSL https://raw.githubusercontent.com/petgully/IOT_Spotless/main/raspberry_pi/scripts/bootstrap.sh | sudo bash
   ```

4. **Answer ~5 prompts** (Machine ID, Static IP, DB host/user/password/name,
   admin password). Press Enter at any prompt to accept the suggested default
   or skip (DB → offline mode; admin password → uses the default
   `spotless-admin` which you should change later).
   Everything else runs unattended for ~10 minutes.

   > **Write down the static IP the script chose** (e.g. `192.168.0.20`) —
   > you'll need it in Part B.

5. **Reboot:**

   ```bash
   sudo reboot
   ```

6. After the reboot, the kiosk opens fullscreen and shows
   **"0 of 3 nodes online"** — that's expected, you haven't flashed the ESP32s
   yet. Move to Part B.

### Part B — ESP32 boards (~5 min, from your Windows laptop)

7. On your **Windows laptop** (not the Pi):

   ```powershell
   git clone https://github.com/petgully/IOT_Spotless.git
   cd IOT_Spotless
   ```

   First time only, allow PowerShell to run local scripts:
   ```powershell
   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
   ```

8. **Plug in node 1**, then flash all 3 boards (you'll be prompted to swap
   cables between them):

   ```powershell
   .\tools\flash_node.ps1 all `
       -WifiSsid "YourBoothWiFi" `
       -WifiPassword "YourBoothWiFiPassword" `
       -MqttBroker "192.168.0.20" `
       -Yes
   ```

   Replace `-MqttBroker` with the static IP you wrote down in step 4.
   See [`tools/README.md`](../tools/README.md) for full options, troubleshooting,
   and prerequisites (Python + PlatformIO).

9. Power on all 3 ESP32 boards in the booth. Within ~30 seconds the kiosk shows
   **"3 of 3 nodes online"**. Done.

---

## Suggested static IPs

| Machine | Static IP |
|---|---|
| Booth 1 (`BS01`) | `<gateway>.20` (e.g. `192.168.0.20`) |
| Booth 2 (`BS02`) | `<gateway>.21` |
| Booth 3 (`BS03`) | `<gateway>.22` |

The bootstrap script auto-detects your gateway and suggests the right IP.

---

## What the bootstrap installs

- Mosquitto MQTT broker (anonymous on `:1883`)
- Python virtual environment + all backend dependencies
- `spotless-kiosk.service` (systemd, **auto-starts on boot, auto-restarts on crash**)
- Chromium fullscreen autostart (waits for Flask to be ready before opening)
- Auto-login as `spotless`
- Screen blanking disabled
- Log rotation (7 days, 50 MB cap)
- Weekly preventive reboot, Sundays at 3 AM
- The `~/.spotless/machine_id.txt` and `.env` files are created from your inputs

The bootstrap is **idempotent** — re-running it on the same Pi just heals
configuration drift. Safe to run any time.

---

## ESP32 setup (3 boards per machine)

The flash wrapper handles WiFi credentials and the Pi's IP for you. From a
**Windows laptop** in the cloned repo root:

```powershell
.\tools\flash_node.ps1 all `
    -WifiSsid "YourBoothWiFi" `
    -WifiPassword "YourBoothWiFiPassword" `
    -MqttBroker "<Pi static IP>" `
    -Yes
```

The wrapper auto-detects the COM port, patches each node's `config.h` with the
values you pass, and flashes all 3 boards in sequence (prompting you to swap
cables between them).

`config.h` is **gitignored** — the per-booth credentials you flash are
intentionally never committed. Each node ships with `config.h.example`
(committed, placeholder values); the wrapper copies it to `config.h` on first
run.

Full options, prerequisites (Python + PlatformIO), and troubleshooting are in
[`tools/README.md`](../tools/README.md).

> **Phase 2b** (later, when you have ≥2 booths) will add a captive-portal so a
> fresh ESP32 broadcasts its own WiFi network you can join from your phone to
> enter credentials — no laptop or USB cable needed. Not required for Machine 1.

---

## Day-to-day operations

| Task | How |
|---|---|
| **Change shampoo / water / dryer time** | Edit `/home/spotless/.spotless/config.json` (changes take effect on the next session — no restart needed). Phase 3 will add a web UI for this so you don't have to edit JSON. |
| **See live logs** | `journalctl -u spotless-kiosk -f` |
| **Restart the kiosk** | `sudo systemctl restart spotless-kiosk` |
| **Stop the kiosk** | `sudo systemctl stop spotless-kiosk` |
| **Check ESP32 nodes are online** | `bash /home/spotless/IOT_Spotless/raspberry_pi/scripts/check_nodes.sh` |
| **Test all relays** | `cd /home/spotless/IOT_Spotless/raspberry_pi && source venv/bin/activate && python3 main.py --test` |
| **Update code from GitHub** | `cd /home/spotless/IOT_Spotless && git pull && sudo systemctl restart spotless-kiosk` |
| **Change DB / API key / admin password** | Edit `/home/spotless/IOT_Spotless/raspberry_pi/.env` then restart the service |

---

## Manless-mode behaviour (what happens when…)

| Event | What happens |
|---|---|
| Power loss mid-session | Pi reboots → service auto-starts → `recover_on_boot()` reads the saved checkpoint → kiosk shows "Resume?" prompt for the customer |
| Flask crashes | systemd restarts it within 5 seconds (max 10 fast restarts before giving up — that means a real bug) |
| Chromium freezes | Pi reboots Sunday 3 AM (weekly cron). For an immediate fix: power-cycle the Pi |
| WiFi drops temporarily | ESP32s auto-reconnect to MQTT once network returns; kiosk degrades to offline mode (sessions still log locally) |
| Database goes down | Kiosk continues running; sessions logged to `~/.spotless/sessions/*.json` and synced when DB is reachable again |
| SD card fills with logs | Logrotate caps log files at 7 days / 50 MB total |

---

## Troubleshooting

### Bootstrap fails partway through
Re-run it. It's idempotent. The error message will point at the failing step.

### Kiosk won't start after bootstrap
```bash
sudo systemctl status spotless-kiosk
journalctl -u spotless-kiosk -n 100
```
Most common cause: `.env` has a bad value (typo in DB password). Edit and
restart.

### Static IP didn't apply
A reboot finalises it cleanly:
```bash
sudo reboot
```

### ESP32 nodes don't show online
1. Are they powered?
2. WiFi credentials baked into the firmware correct (2.4 GHz only)?
3. The Pi's static IP correct in the firmware?
4. Plug one into your Windows laptop and watch its serial output:
   ```powershell
   .\tools\flash_node.ps1 1 -Monitor
   ```
   (Reflashes node 1 and immediately opens a serial monitor so you can see
   WiFi/MQTT connect logs.)
5. To re-flash with corrected values without unplugging anything else, just
   re-run `flash_node.ps1` with new `-WifiSsid` / `-WifiPassword` /
   `-MqttBroker` flags.

### "Database unavailable" errors in logs
Confirm `.env` has the right `SPOTLESS_DB_HOST` and credentials. Test
manually:
```bash
cd /home/spotless/IOT_Spotless/raspberry_pi
source venv/bin/activate
python3 test_db_connection.py
```

---

## What's coming next (so you know what to expect)

| Phase | Status | What it adds |
|---|---|---|
| **Phase 1** — bootstrap.sh | ✅ Done | One-command Pi setup |
| **Phase 2a** — `flash_node.ps1` wrapper | ✅ Done | One-command ESP32 flash from Windows laptop |
| **Phase 2b** — Captive-portal WiFi for ESP32 | Planned (when you have ≥2 booths) | No more `config.h` edits per site |
| **Phase 3** — `/admin` web UI | Planned | Edit shampoo/water times via a webpage instead of editing JSON |
| **Phase 4** — Watchdog + `/healthz` | Planned | systemd kills + restarts Flask if it hangs (today: only restarts on crash) |

---

## File locations cheat sheet

| What | Where |
|---|---|
| Code | `/home/spotless/IOT_Spotless/` |
| Backend Python | `/home/spotless/IOT_Spotless/raspberry_pi/` |
| Environment + secrets | `/home/spotless/IOT_Spotless/raspberry_pi/.env` |
| Machine ID | `/home/spotless/.spotless/machine_id.txt` |
| Timing config | `/home/spotless/.spotless/config.json` |
| Local session logs | `/home/spotless/.spotless/sessions/` |
| Application logs | `/home/spotless/.spotless/logs/` |
| systemd service file | `/etc/systemd/system/spotless-kiosk.service` |
| Mosquitto config | `/etc/mosquitto/conf.d/spotless.conf` |
| Logrotate rule | `/etc/logrotate.d/spotless` |
| Weekly reboot cron | `/etc/cron.d/spotless-weekly-reboot` |
