# Old Project (Spotless V7) — GPIO & Hardware Variable Map

> **Source file:** `Reference_documents/Spotless_v7_FullTry_New.py`
>
> This document maps every hardware-related GPIO pin, variable, and function
> from the original monolithic Raspberry Pi project so they can be reassigned
> to the new IoT node architecture (ESP32 nodes + Raspberry Pi master).

---

## 1. GPIO Overview

| GPIO | Variable | Group | Component | Voltage | Direction |
|------|----------|-------|-----------|---------|-----------|
| 4 | `p5` | Peristaltic Pumps | Peristaltic Pump 5 (unused in code) | 12V/24V | OUT |
| 5 | `ro3` | RO Solenoids | RO Solenoid 3 — fills disinfectant tank | 24V | OUT |
| 6 | `ro4` | RO Solenoids | RO Solenoid 4 — drains disinfectant tank | 24V | OUT |
| 7 | `top` | Solenoid Valves | Flush — top nozzle valve | 24V | OUT |
| 8 | `bottom` | Solenoid Valves | Flush — bottom nozzle valve | 24V | OUT |
| 9 | `ro1` | RO Solenoids | RO Solenoid 1 — fills shampoo tank | 24V | OUT |
| 10 | `p1` | Peristaltic Pumps | Peristaltic Pump 1 — **Shampoo** | 12V/24V | OUT |
| 11 | `ro2` | RO Solenoids | RO Solenoid 2 — drains shampoo tank | 24V | OUT |
| 12 | `s5` | Solenoid Valves | Solenoid Valve 5 — **Water line** gate | 24V | OUT |
| 13 | `d1` | Diaphragm Pumps | Diaphragm Pump 1 — shampoo/conditioner line | 24V | OUT |
| 14 | `dry` | High Voltage Relays | **Dryer** motor | 220V | OUT |
| 15 | `roof` | High Voltage Relays | **Roof lights** | 220V | OUT |
| 16 | `s4` | Solenoid Valves | Solenoid Valve 4 — common valve (always paired) | 24V | OUT |
| 17 | `p2` | Peristaltic Pumps | Peristaltic Pump 2 — **Conditioner** | 12V/24V | OUT |
| 18 | `flushmain` | High Voltage Relays | **Flush main** valve | 220V | OUT |
| 19 | `d2` | Diaphragm Pumps | Diaphragm Pump 2 — disinfectant line | 24V | OUT |
| 20 | `s3` | Solenoid Valves | Solenoid Valve 3 — **disinfectant** line gate | 24V | OUT |
| 21 | `s2` | Solenoid Valves | Solenoid Valve 2 — common spray output | 24V | OUT |
| 22 | `p4` | Peristaltic Pumps | Peristaltic Pump 4 — **Medicated Bath / Disinfectant** | 12V/24V | OUT |
| 23 | `pump` | High Voltage Relays | **Main water pump** | 220V | OUT |
| 24 | `rglight` | Lighting | **RGB ambient light** strip | 220V | OUT |
| 25 | `s8` | Lighting / Flow | **220V main solenoid** — master flow gate | 220V | OUT |
| 26 | `s1` | Solenoid Valves | Solenoid Valve 1 — **shampoo** line gate | 24V | OUT |
| 27 | `p3` | Peristaltic Pumps | Peristaltic Pump 3 (defined but unused) | 12V/24V | OUT |

### I2C Extender Board (MCP23017) — Commented out in code

| I2C Pin | Variable | Component | Notes |
|---------|----------|-----------|-------|
| GPB1 (1)| `green` | Green indicator light | Via MCP23017 @ address `0x22`, I2C bus 3 |
| GPB2 (2)| `geyser` | Water heater (geyser) | Via MCP23017 @ address `0x22`, I2C bus 3 |

---

## 2. Pin Groups (as defined in code)

### 2.1 Peristaltic Pumps — `ppumps`

```
ppumps = [10, 17, 27, 22, 4]
p1=GPIO10, p2=GPIO17, p3=GPIO27, p4=GPIO22, p5=GPIO4
```

| Var | GPIO | Purpose | Used in Functions |
|-----|------|---------|-------------------|
| `p1` | 10 | Shampoo dispensing | `Shampoo()` via `pumpready(p1, wt)` |
| `p2` | 17 | Conditioner dispensing | `Conditioner()` via `pumpready(p2, wt)` |
| `p3` | 27 | **Unused** — reserved spare pump | Not called anywhere |
| `p4` | 22 | Medicated bath / Disinfectant | `Mbath()` via `pumpready(p4, wt)`, `Disinfectant()` via `pumpready(p4, diwt)` |
| `p5` | 4 | **Unused** — reserved spare pump | Not called anywhere |

### 2.2 RO Solenoids (24V) — `rosol`

```
rosol = [9, 11, 5, 6]
ro1=GPIO9, ro2=GPIO11, ro3=GPIO5, ro4=GPIO6
```

| Var | GPIO | Purpose | Used in Functions |
|-----|------|---------|-------------------|
| `ro1` | 9 | Fill shampoo tank (RO water in) | `priming_sh()` → `priming(s8,s1,ro1,...)` |
| `ro2` | 11 | Drain shampoo tank (empty out) | `priming_sh()` → `priming(...,d1,ro2,...)`, `emptytime(d1,ro2,8)` |
| `ro3` | 5 | Fill disinfectant tank (RO water in) | `priming_dt()` → `priming(s8,s3,ro3,...)` |
| `ro4` | 6 | Drain disinfectant tank (empty out) | `priming_dt()` → `priming(...,d2,ro4,...)`, `emptytime(d2,ro4,8)` |

### 2.3 Diaphragm Pumps — `dia_pump`

```
dia_pump = [13, 19]
d1=GPIO13, d2=GPIO19
```

| Var | GPIO | Purpose | Used in Functions |
|-----|------|---------|-------------------|
| `d1` | 13 | Pump for shampoo/conditioner delivery line | `Shampoo()`, `Conditioner()`, `Mbath()`, `priming_sh()`, `emptytime()` |
| `d2` | 19 | Pump for disinfectant delivery line | `Disinfectant()`, `priming_dt()`, `emptytime()` |

### 2.4 Solenoid Valves (24V) — `sol_val`

```
sol_val = [26, 21, 20, 16, 12, 7, 8]
s1=GPIO26, s2=GPIO21, s3=GPIO20, s4=GPIO16, s5=GPIO12, top=GPIO7, bottom=GPIO8
```

| Var | GPIO | Purpose | Used in Functions |
|-----|------|---------|-------------------|
| `s1` | 26 | Shampoo line gate valve | `Shampoo()`, `Conditioner()`, `Mbath()`, `priming_sh()` |
| `s2` | 21 | Common spray output valve | `Shampoo()`, `Conditioner()`, `Mbath()`, `Water()`, `Disinfectant()` |
| `s3` | 20 | Disinfectant line gate valve | `Disinfectant()`, `priming_dt()` |
| `s4` | 16 | Common valve (always paired with s2) | `Shampoo()`, `Conditioner()`, `Mbath()`, `Water()`, `Disinfectant()` |
| `s5` | 12 | Water line valve (clean water) | `Water()`, `Disinfectant()` (rinse phase) |
| `top` | 7 | Flush — top nozzle | `Flush()` |
| `bottom` | 8 | Flush — bottom nozzle | `Flush()` |

### 2.5 220V Solenoid & Lighting — `lig_val`

```
lig_val = [25, 24]
s8=GPIO25, rglight=GPIO24
```

| Var | GPIO | Purpose | Used in Functions |
|-----|------|---------|-------------------|
| `s8` | 25 | 220V master flow solenoid (main water inlet) | `Shampoo()`, `Water()`, `Conditioner()`, `Mbath()`, `Disinfectant()`, `priming()` |
| `rglight` | 24 | RGB ambient light strip ON/OFF | `Lightson()`, `Lightsoff()` |

### 2.6 High Voltage Relays (220V) — `high_vol`

```
high_vol = [23, 18, 14, 15]
pump=GPIO23, flushmain=GPIO18, dry=GPIO14, roof=GPIO15
```

| Var | GPIO | Purpose | Used in Functions |
|-----|------|---------|-------------------|
| `pump` | 23 | Main water pump (220V) | `Shampoo()`, `Water()`, `Conditioner()`, `Mbath()`, `Disinfectant()`, `Flush()` |
| `flushmain` | 18 | Flush main valve (220V) | `Flush()` |
| `dry` | 14 | Dryer blower motor (220V) | `Dryer()` |
| `roof` | 15 | Roof lights (220V) | `Spotless()` start/end, `control_roof_lights()` |

---

## 3. Function-to-Pin Mapping (Which pins each function activates)

### 3.1 `Shampoo(qr_return, val, wt)`
```
Parallel: p1 ON for wt seconds (peristaltic pump primes shampoo)
Main:     s8, s1, s2, s4, d1, pump → ON for val seconds → OFF
```
**Pins used:** `p1`(10), `s8`(25), `s1`(26), `s2`(21), `s4`(16), `d1`(13), `pump`(23)

### 3.2 `Water(val)`
```
Main: s8, s5, s2, s4, pump → ON for val seconds → OFF
```
**Pins used:** `s8`(25), `s5`(12), `s2`(21), `s4`(16), `pump`(23)

### 3.3 `Conditioner(qr_return, val, wt)`
```
Parallel: p2 ON for wt seconds (peristaltic pump primes conditioner)
Main:     s8, s1, s2, s4, d1, pump → ON for val seconds → OFF
```
**Pins used:** `p2`(17), `s8`(25), `s1`(26), `s2`(21), `s4`(16), `d1`(13), `pump`(23)

### 3.4 `Mbath(qr_return, val, wt)` — Medicated Bath
```
Parallel: p4 ON for wt seconds (peristaltic pump primes medicated solution)
Main:     s8, s1, s2, s4, d1, pump → ON for val seconds → OFF
```
**Pins used:** `p4`(22), `s8`(25), `s1`(26), `s2`(21), `s4`(16), `d1`(13), `pump`(23)

### 3.5 `Dryer(qr_return, val)`
```
Phase 1: dry ON for val*0.5 seconds → OFF
Break:   15 second pause
Phase 2: dry ON for val*0.5 seconds → OFF
```
**Pins used:** `dry`(14)

### 3.6 `Disinfectant(val, wt)`
```
Parallel: p4 ON for wt*0.8 seconds
Phase 1:  s8, s3, s4, s2, d2, pump → ON for val seconds → OFF  (disinfectant spray)
Phase 2:  s8, s5, s2, s4, pump → ON for val seconds → OFF      (water rinse)
```
**Pins used:** `p4`(22), `s8`(25), `s3`(20), `s2`(21), `s4`(16), `d2`(19), `pump`(23), `s5`(12)

### 3.7 `Flush(val)`
```
Phase 1: top, pump, flushmain → ON for val seconds → OFF
Phase 2: bottom, pump → ON for val seconds → bottom, pump, flushmain → OFF
```
**Pins used:** `top`(7), `bottom`(8), `pump`(23), `flushmain`(18)

### 3.8 `priming_sh(fillval)` — Prime shampoo tank
```
Fill:  s8, s1, ro1 → ON for fillval seconds → OFF
Empty: d1, ro2 → ON for 6 seconds → OFF
```
**Pins used:** `s8`(25), `s1`(26), `ro1`(9), `d1`(13), `ro2`(11)

### 3.9 `priming_dt(fillval)` — Prime disinfectant tank
```
Fill:  s8, s3, ro3 → ON for fillval seconds → OFF
Empty: d2, ro4 → ON for 6 seconds → OFF
```
**Pins used:** `s8`(25), `s3`(20), `ro3`(5), `d2`(19), `ro4`(6)

### 3.10 `emptytime(dia, ro, drainval)` — Drain a tank
```
dia, ro → ON for drainval seconds → OFF
```
Called with: `(d1, ro2, 8)` for shampoo, `(d2, ro4, 8)` for disinfectant

### 3.11 `Lightson()` / `Lightsoff()`
```
rglight → ON / OFF
(green via MCP23017 — commented out)
```
**Pins used:** `rglight`(24)

### 3.12 `control_roof_lights(roof)`
```
roof → ON between 5 PM – 5 AM, OFF otherwise
```
**Pins used:** `roof`(15)

### 3.13 `Allclose()`
```
All 24 relay lines → OFF
```

### 3.14 `TestingRelays(qr_return)`
```
Each of 24 relay lines → ON for 3 seconds → OFF (sequentially)
```

---

## 4. Session Flow & Parameters

### 4.1 Main `Spotless()` function signature

```python
Spotless(qr_return, sval, cval, dval, wval, dryval, fval, wt, stval, msgval, tdry, pr, stage, ctype)
```

| Param | Meaning | Typical Values |
|-------|---------|----------------|
| `qr_return` | QR code / session identifier | string |
| `sval` | Shampoo duration (seconds) | 80–120 |
| `cval` | Conditioner duration (seconds) | 80–120 |
| `dval` | Disinfectant duration (seconds) | 60 |
| `wval` | Water rinse duration (seconds) | 60–70 |
| `dryval` | Dryer duration (seconds) | 480–600 |
| `fval` | Flush duration (seconds) | 60 |
| `wt` | Peristaltic pump run time (seconds) | 5–50 |
| `stval` | Stage wait / voiceover pause (seconds) | 10 |
| `msgval` | Massage/soak time (seconds) | 10 |
| `tdry` | Towel dry wait (seconds) | 30 |
| `pr` | Process flag (10 = include disinfectant at end) | 10 or 20 |
| `stage` | Starting stage (1–6, for resume) | 1 |
| `ctype` | 100 = conditioner, 200 = medicated bath | 100 / 200 |

### 4.2 Session Stages (sequential flow)

```
Stage 1: Shampoo → Massage/Soak
Stage 2: Water Rinse 1
Stage 3: Conditioner (or Medicated Bath if ctype=200) → Massage/Soak
Stage 4: Water Rinse 2 (double duration)
Stage 5: Towel Dry wait
Stage 6: Dryer (with break in middle)
---
Offboard voiceover
Disinfectant (if pr=10)
Empty tanks (d1/ro2 and d2/ro4)
Thank you → Lights off → Roof light check
```

### 4.3 Session Presets

| Session Type | `bstatus` | sval | cval | dval | wval | dryval | wt | ctype |
|--------------|-----------|------|------|------|------|--------|-----|-------|
| Small Pet Bath | `small` | 80 | 80 | 60 | 60 | 480 | 30 | 100 |
| Large Pet Bath | `large` | 100 | 100 | 60 | 60 | 600 | 50 | 100 |
| Customer DIY | `custdiy` | 100 | 100 | 60 | 60 | 600 | 12 | 100 |
| Med Bath Small | `medsmall` | 80 | 80 | 60 | 60 | 480 | 30 | 200 |
| Med Bath Large | `medlarge` | 100 | 100 | 60 | 60 | 600 | 50 | 200 |
| Disinfectant Only | `onlydisinfectant` | — | — | 60 | — | — | 15 | — |
| Test: Dryer | `onlydrying` | — | — | — | — | 300 | — | — |
| Test: Water | `onlywater` | — | — | — | 90 | — | — | — |
| Test: Flush | `onlyflush` | — | — | — | — | — | — | — |
| Test: Shampoo | `onlyshampoo` | — | — | — | — | — | — | — |
| Test: All Relays | `quicktest` | — | — | — | — | — | — | — |

---

## 5. Plumbing / Fluid Path Logic

Understanding which pins control which fluid path:

```
┌──────────────────────────────────────────────────────────────────────┐
│                        WATER INLET (mains)                          │
│                              │                                      │
│                         s8 (GPIO 25)  ← 220V master solenoid        │
│                              │                                      │
│              ┌───────────────┼───────────────┐                      │
│              │               │               │                      │
│         s1 (GPIO 26)    s3 (GPIO 20)    s5 (GPIO 12)                │
│         Shampoo gate    Disinfect gate  Water gate                  │
│              │               │               │                      │
│         ro1 (GPIO 9)    ro3 (GPIO 5)         │                      │
│         Fill shampoo    Fill disinfect        │                      │
│         tank            tank                  │                      │
│              │               │               │                      │
│         d1 (GPIO 13)    d2 (GPIO 19)         │                      │
│         Diaphragm       Diaphragm            │                      │
│         pump 1          pump 2               │                      │
│              │               │               │                      │
│         ro2 (GPIO 11)   ro4 (GPIO 6)         │                      │
│         Drain shampoo   Drain disinfect      │                      │
│         tank            tank                  │                      │
│              │               │               │                      │
│              └───────┬───────┘               │                      │
│                      │                       │                      │
│              s2 (GPIO 21) ← common spray     │                      │
│              s4 (GPIO 16) ← common valve     │                      │
│                      │                       │                      │
│                      └───────────────────────┘                      │
│                              │                                      │
│                    pump (GPIO 23) ← 220V main pump                  │
│                              │                                      │
│                         SPRAY NOZZLES                               │
│                                                                     │
│   ┌──────────────────────────────────────────────────────────────┐  │
│   │                    FLUSH SYSTEM                              │  │
│   │   flushmain (GPIO 18) ← 220V flush valve                    │  │
│   │   top (GPIO 7) ← top nozzle                                 │  │
│   │   bottom (GPIO 8) ← bottom nozzle                           │  │
│   └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│   ┌──────────────────────────────────────────────────────────────┐  │
│   │                 PERISTALTIC PUMPS                             │  │
│   │   p1 (GPIO 10) ← Shampoo bottle                             │  │
│   │   p2 (GPIO 17) ← Conditioner bottle                         │  │
│   │   p3 (GPIO 27) ← Spare (unused)                             │  │
│   │   p4 (GPIO 22) ← Medicated / Disinfectant bottle            │  │
│   │   p5 (GPIO 4)  ← Spare (unused)                             │  │
│   └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│   ┌──────────────────────────────────────────────────────────────┐  │
│   │                 HIGH VOLTAGE (220V)                           │  │
│   │   dry (GPIO 14)   ← Dryer blower motor                      │  │
│   │   roof (GPIO 15)  ← Roof lights (timed 5PM–5AM)             │  │
│   │   rglight (GPIO 24) ← RGB ambient light strip               │  │
│   └──────────────────────────────────────────────────────────────┘  │
│                                                                     │
│   ┌──────────────────────────────────────────────────────────────┐  │
│   │          I2C EXTENDER (MCP23017 @ 0x22, Bus 3)               │  │
│   │   GPB1 → green   ← Green indicator light                    │  │
│   │   GPB2 → geyser  ← Water heater                             │  │
│   └──────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 6. Utility / Helper Functions (hardware-related)

| Function | What it does | Hardware involved |
|----------|-------------|-------------------|
| `toggle_pins(pins, state)` | Sets a list of GPIO pins to HIGH or LOW | Any pins passed as args |
| `pumpready(pin, wt)` | Turns a single pin ON for `wt` seconds then OFF | Peristaltic pumps (p1–p5) |
| `emptytime(dia, ro, drainval)` | Runs diaphragm pump + RO drain for `drainval` seconds | d1/d2 + ro2/ro4 |
| `priming(mainflow, localgate, mainro, maindp, dpro, fillval, empval)` | Fill then drain a chemical tank to prime the lines | s8, s1/s3, ro1/ro3, d1/d2, ro2/ro4 |
| `priming_sh(fillval)` | Shortcut to prime shampoo line | Calls `priming(s8,s1,ro1,d1,ro2,fillval,6)` |
| `priming_dt(fillval)` | Shortcut to prime disinfectant line | Calls `priming(s8,s3,ro3,d2,ro4,fillval,6)` |
| `Allclose()` | Emergency/cleanup — all 24 relays OFF | All GPIO lines |
| `Lightson()` | Session start — ambient lights ON | `rglight`(24), (`green` via I2C) |
| `Lightsoff()` | Session end — ambient lights OFF | `rglight`(24), (`green` via I2C) |
| `control_roof_lights(roof)` | Time-based roof light (5PM–5AM) | `roof`(15) |
| `TestingRelays(qr_return)` | Sequential test of all 24 relays | All relay_lines |

---

## 7. Software Variables (non-GPIO, but important for mapping)

| Variable | Type | Purpose |
|----------|------|---------|
| `qr` | string | Raw QR code input from scanner |
| `qr_return` | string | Validated QR / session identifier |
| `bstatus` | string | Bath status type (`small`, `large`, `custdiy`, `medsmall`, `medlarge`, etc.) |
| `status` | string | Validation status (`Y` = registered, `N` = admin/offline, `X` = failed) |
| `extradry` | string | Extra drying flag (`Y`/`N`) |
| `ustat` | string | Update status sent to server (`S`=shampoo done, `C`=conditioner done, `E`=dryer done) |
| `start_time` | datetime | Session start timestamp |
| `relay_lines` | list | All 24 gpiod line objects |
| `ctr` | int | Main loop iteration counter |

---

## 8. Communication & Peripherals

| Component | Protocol | Details |
|-----------|----------|---------|
| GPIO chip | `gpiod` (libgpiod) | `gpiochip0` — all 24 GPIOs |
| MCP23017 I2C Expander | I2C (smbus) | Bus 3, Address `0x22`, Port B pins |
| QR Scanner | USB HID | Reads into tkinter Entry field as keyboard input |
| Server API | HTTP GET | `petgully.com` — QR validation & status updates |
| Email | SMTP/SSL | Gmail — session notifications with log attachment |
| Audio | VLC (cvlc) | Voiceover MP3 files via subprocess |
| Display | Tkinter | Kiosk GUI on attached screen |

---

## 9. Quick Reference — Pin Count by Node Function

For planning the new IoT node distribution:

| Function Category | Pin Count | Pins |
|-------------------|-----------|------|
| Peristaltic Pumps | 5 (3 active) | GPIO 10, 17, 27, 22, 4 |
| RO Solenoids (24V) | 4 | GPIO 9, 11, 5, 6 |
| Diaphragm Pumps | 2 | GPIO 13, 19 |
| Solenoid Valves (24V) | 7 | GPIO 26, 21, 20, 16, 12, 7, 8 |
| 220V Solenoid + Light | 2 | GPIO 25, 24 |
| 220V High Voltage Relays | 4 | GPIO 23, 18, 14, 15 |
| I2C Extender (MCP23017) | 2 | GPB1, GPB2 |
| **Total** | **26** | 24 direct GPIO + 2 I2C |

---

*Use this document to map each old variable to its new ESP32 node GPIO assignment.*
