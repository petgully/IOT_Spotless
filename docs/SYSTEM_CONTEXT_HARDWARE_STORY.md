# Spotless — System Context & Hardware Story

> This document describes the **physical hardware setup** of the Spotless pet bathing
> station as it exists in the real world, mapped against the old monolithic code
> (`Spotless_v7_FullTry_New.py`). It serves as the single source of truth for
> building the new IoT node-based architecture.

---

## 1. What is Spotless?

Spotless is an **automated pet bathing station**. A pet is placed inside a tub,
and the system runs through a multi-stage wash cycle — shampoo, rinse, condition,
dry — all controlled by relays and solenoids driven from a Raspberry Pi. After the
pet leaves, the tub is disinfected and auto-flushed for the next customer.

---

## 2. The 8-Stage Wash Cycle

| Stage | Name | What Happens | Pet in Tub? |
|-------|------|-------------|-------------|
| 0 | **Priming** | Fill containers with water, push air out of lines (airlock fix) | Yes (onboarding) |
| 1 | **Shampoo** | Inject shampoo mix into water stream, spray on pet, soak/massage | Yes |
| 2 | **Water Rinse 1** | Clean water rinse to wash off shampoo | Yes |
| 3 | **Conditioner** | Inject conditioner (or medicated shampoo) into stream, soak/massage | Yes |
| 4 | **Water Rinse 2** | Extended clean water rinse (2× duration) | Yes |
| 5 | **Dryer** | Hot air blower in two phases with a break | Yes |
| 6 | **Disinfectant** | Spray disinfectant solution, then water rinse (tub cleaning) | **No** (pet offboarded) |
| 7 | **Autoflush** | High-pressure flush of tub — bottom nozzles, then top nozzles | **No** |

---

## 3. Physical Plumbing — The Full Water Path

### 3.1 Water Inlet & Booster Pump

```
                        ┌─────────────────────────────────────┐
   Water Inlet (mains)  │                                     │
         │              │  pump (GPIO 23) — 220V Booster Pump │
         └──────────────┤                                     │
                        └──────────┬──────────────────────────┘
                                   │
                        ┌──────────┴──────────┐
                        │                     │
                   ┌────▼────┐          ┌─────▼──────┐
                   │ Geyser  │          │  AF Gate   │
                   │(heater) │          │ flushmain  │
                   └────┬────┘          │ (GPIO 18)  │
                        │               │  220V      │
                        │               └─────┬──────┘
                        │                     │
                   ┌────▼──────┐        ┌─────┴──────┐
                   │Main Gate  │        │  AUTOFLUSH │
                   │   s8      │        │  SYSTEM    │
                   │(GPIO 25)  │        │(see §3.5)  │
                   │  220V     │        └────────────┘
                   └────┬──────┘
                        │
              ┌─────────┼─────────┐
              │         │         │
         ┌────▼──┐ ┌────▼──┐ ┌───▼───┐
         │Line 1 │ │Line 2 │ │Line 3 │
         │Shampoo│ │Disinf.│ │ Water │
         └───────┘ └───────┘ └───────┘
              (see §3.2)
```

The booster pump (`pump`) is the heart — it provides pressure for everything.
It splits into **two independent paths**:

1. **Bath path** → through the geyser (hot water) → main gate (`s8`) → 3 bath lines
2. **Autoflush path** → through the autoflush gate (`flushmain`) → top/bottom nozzles

These two paths **never run simultaneously**. During bath stages 0–5, only the
bath path is active. During stages 6–7, the autoflush path is used.

### 3.2 The Three Bath Lines (after Main Gate s8)

After the main gate `s8` opens, water flows into three parallel lines that
converge at the **shower gun** (the output nozzle that sprays the pet/tub):

```
                           Main Gate s8 (GPIO 25) — 220V
                                    │
              ┌─────────────────────┼─────────────────────┐
              │                     │                     │
         ┌────▼────┐          ┌─────▼─────┐          ┌───▼───┐
         │   S1    │          │    S3     │          │  S5   │
         │(GPIO 26)│          │ (GPIO 20) │          │(GPIO 12)│
         │ 24V ½"  │          │  24V ½"   │          │ 24V ½" │
         └────┬────┘          └─────┬─────┘          └───┬───┘
              │                     │                    │
         ─ ─ ─┤ injection     ─ ─ ─┤ injection          │
         │    │ point          │    │ point              │
    Container 1            Container 2                   │
    via d1 ──┘             via d2 ──┘                    │
              │                     │                    │
         ┌────▼────┐          ┌─────▼─────┐             │
         │   S2    │          │    S4     │             │
         │(GPIO 21)│          │ (GPIO 16) │             │
         │ 24V ½"  │          │  24V ½"   │             │
         └────┬────┘          └─────┬─────┘             │
              │                     │                    │
              └─────────────────────┴────────────────────┘
                                    │
                              SHOWER GUN
                           (output nozzle)
```

**Line 1 — Shampoo/Conditioner/Med Shampoo:**
- Gates: S1 (entry) → injection point → S2 (exit)
- Between S1 and S2, a T-junction connects to **Container 1** via diaphragm pump `d1`
- When `d1` runs, it pushes the chemical mix from Container 1 into the water stream

**Line 2 — Disinfectant:**
- Gates: S3 (entry) → injection point → S4 (exit)
- Between S3 and S4, a T-junction connects to **Container 2** via diaphragm pump `d2`
- When `d2` runs, it pushes disinfectant from Container 2 into the water stream

**Line 3 — Clean Water:**
- Gate: S5 only (no injection, no exit gate needed)
- Pure water goes straight to the shower gun

### 3.3 The Reverse Flow Problem & Solution

**Problem:** When Line 1 is active (S1 + S2 open), water pressure can back-flow
through the closed S4 valve into the Line 2 T-junction, accidentally filling
Container 2 (disinfectant) with soapy water. This contaminates the disinfectant.

**Solution:** Open the "opposite" exit valve to block reverse flow:

| Active Line | Primary Gates | Anti-Backflow Gate(s) | Why |
|-------------|---------------|----------------------|-----|
| Line 1 (Shampoo) | S1 + S2 | **+ S4** | Blocks water from entering Line 2 via S4's backside |
| Line 2 (Disinfect) | S3 + S4 | **+ S2** | Blocks water from entering Line 1 via S2's backside |
| Line 3 (Water) | S5 | **+ S2 + S4** | Blocks backflow into both Line 1 and Line 2 |

This is why the code always activates seemingly "extra" valves:

```python
# Shampoo: Line 1 + anti-backflow S4
toggle_pins([s8, s1, s2, s4, d1, pump], True)

# Water: Line 3 + anti-backflow S2 + S4
toggle_pins([s8, s5, s2, s4, pump], True)

# Disinfectant: Line 2 + anti-backflow S2
toggle_pins([s8, s3, s4, s2, d2, pump], True)
```

### 3.4 Container System & Chemical Injection

There are **two mixing containers** — kept separate to avoid cross-contamination
between pet-safe chemicals and the disinfectant:

```
┌─────────────────────────────────────────────────────────────────┐
│                        CONTAINER 1                              │
│               (Shampoo / Conditioner / Med Shampoo)             │
│                                                                 │
│   Peristaltic pumps pull liquid from bottles INTO the container: │
│     p1 (GPIO 10) ← Shampoo bottle                              │
│     p2 (GPIO 17) ← Conditioner bottle                          │
│     p3 (GPIO 27) ← Medicated shampoo bottle                    │
│                                                                 │
│   RO water fill (6mm tubing):                                   │
│     ro1 (GPIO 9) ← fills container with water (for priming)    │
│                                                                 │
│   Diaphragm pump pushes mix OUT of container:                   │
│     d1 (GPIO 13) → into the injection T-junction between S1-S2 │
│                                                                 │
│   Drain line (6mm tubing):                                      │
│     ro2 (GPIO 11) ← drains container (used during priming)     │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                        CONTAINER 2                              │
│                     (Disinfectant Only)                          │
│                                                                 │
│   Peristaltic pump pulls liquid from bottle INTO the container:  │
│     p4 (GPIO 22) ← Disinfectant bottle                         │
│                                                                 │
│   RO water fill (6mm tubing):                                   │
│     ro3 (GPIO 5) ← fills container with water (for priming)    │
│                                                                 │
│   Diaphragm pump pushes mix OUT of container:                   │
│     d2 (GPIO 19) → into the injection T-junction between S3-S4 │
│                                                                 │
│   Drain line (6mm tubing):                                      │
│     ro4 (GPIO 6) ← drains container (used during priming)      │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│   p5 (GPIO 4) ← BACKUP peristaltic pump                        │
│   Can replace any failed p1–p4 by re-routing tubing             │
└─────────────────────────────────────────────────────────────────┘
```

**Why two containers?**
- Container 1 holds chemicals safe for pets (shampoo, conditioner, med shampoo)
- Container 2 holds disinfectant — **must never touch the pet**
- They share the same tub output but through different pipeline lines

### 3.5 Autoflush System

The autoflush system has its own **separate water path** from the booster pump,
bypassing the geyser entirely (cold water is fine for tub cleaning):

```
    Booster Pump (pump, GPIO 23)
            │
    ┌───────▼────────┐
    │   AF Gate      │
    │  flushmain     │
    │  (GPIO 18)     │
    │  220V          │
    └───────┬────────┘
            │
     ┌──────┴──────┐
     │             │
┌────▼─────┐ ┌────▼─────┐
│ Top Gate │ │Bottom    │
│  top     │ │Gate      │
│(GPIO 7)  │ │ bottom   │
│  24V     │ │(GPIO 8)  │
└────┬─────┘ │  24V     │
     │       └────┬─────┘
     │            │
  Top nozzles  Bottom nozzles
  (spray down  (spray up from
   from above)  tub floor)
```

**Flush sequence (from old code):**
1. Open `flushmain` + `top` + `pump` → spray from top nozzles for `val` seconds
2. Close `top` → open `bottom` → spray from bottom nozzles for `val` seconds
3. Close everything

> **Note:** The user's preferred order is bottom-first, then top. The old code
> does top-first. The new IoT code should follow the user's intended sequence:
> bottom first (clean tub floor), then top (rinse walls down).

---

## 4. The Priming Process (Airlock Fix)

### 4.1 Why Priming is Needed

The diaphragm pumps (`d1`, `d2`) can't push liquid through the injection line
if there's trapped air. Air compresses instead of pushing the liquid, so the
shampoo never reaches the shower gun. **Priming removes this airlock.**

### 4.2 How Priming Works (Container 1 — Shampoo Line)

```
Step 1: FILL container with water
   ─────────────────────────────
   Open: s8 (main gate) + s1 (shampoo gate) + ro1 (RO fill)
   Water flows: mains → pump → geyser → s8 → s1 → ro1 → Container 1
   Duration: ~10-12 seconds (fillval)
   Close: s8, s1, ro1

Step 2: PUSH water out (removes airlock)
   ──────────────────────────────────────
   Open: d1 (diaphragm pump) + ro2 (drain)
   Water flows: Container 1 → d1 pushes → ro2 → drain
   This clears air from the d1 → injection line path
   Duration: 6 seconds (empval)
   Close: d1, ro2

Step 3: FILL chemical (parallel, during voiceover/onboarding)
   ───────────────────────────────────────────────────────────
   Open: p1 (peristaltic pump) for wt seconds
   Shampoo flows: Bottle → p1 → Container 1
   The peristaltic pump meters a precise amount (in ml)

Step 4: INJECT during stage
   ─────────────────────────
   Open: s8, s1, s2, s4, d1, pump
   d1 pushes shampoo mix from Container 1 through the T-junction
   into the flowing water between S1 and S2 → out to shower gun
```

The same process applies to Container 2 (disinfectant line), using:
`s8 + s3 + ro3` for fill, `d2 + ro4` for push, `p4` for chemical, `d2` for inject.

### 4.3 Priming Code Mapping

| Code Function | Physical Action | Pins |
|---------------|----------------|------|
| `priming_sh(fillval)` | Prime Container 1 (shampoo line) | s8, s1, ro1 → d1, ro2 |
| `priming_dt(fillval)` | Prime Container 2 (disinfectant line) | s8, s3, ro3 → d2, ro4 |
| `emptytime(d1, ro2, 8)` | Drain remaining liquid from Container 1 | d1, ro2 |
| `emptytime(d2, ro4, 8)` | Drain remaining liquid from Container 2 | d2, ro4 |

---

## 5. Stage-by-Stage Pin Activation (What Actually Happens)

### Stage 0 — Priming (runs in parallel during onboarding)

```
priming_sh(10):
  Phase 1: s8 + s1 + ro1 → ON 10s → OFF     (fill Container 1)
  Phase 2: d1 + ro2 → ON 6s → OFF            (clear air)

priming_dt(10):                               (if disinfectant stage needed)
  Phase 1: s8 + s3 + ro3 → ON 10s → OFF      (fill Container 2)
  Phase 2: d2 + ro4 → ON 6s → OFF            (clear air)
```

### Stage 1 — Shampoo

```
Parallel: p1 → ON for wt seconds → OFF       (fill shampoo into Container 1)
Main:     s8 + s1 + s2 + s4 + d1 + pump → ON for sval seconds → OFF
          └─ main gate ─┘  └─ anti-backflow   └─ inject  └─ pressure
```

### Stage 2 — Water Rinse 1

```
Main: s8 + s5 + s2 + s4 + pump → ON for wval seconds → OFF
      └─ main gate  └─ water line   └─ anti-backflow  └─ pressure
```

### Stage 3 — Conditioner (ctype=100) or Medicated Bath (ctype=200)

```
Parallel: p2 → ON for wt seconds → OFF       (conditioner, if ctype=100)
   — OR —
Parallel: p4 → ON for wt seconds → OFF       (med shampoo, if ctype=200)

Main:     s8 + s1 + s2 + s4 + d1 + pump → ON for cval seconds → OFF
          (same pin pattern as Shampoo — uses Container 1 / Line 1)
```

### Stage 4 — Water Rinse 2

```
Main: s8 + s5 + s2 + s4 + pump → ON for 2×wval seconds → OFF
      (same as Water Rinse 1, but double duration)
```

### Stage 5 — Dryer

```
Phase 1: dry → ON for dryval×0.5 seconds → OFF
Break:   15 second pause (pet rests)
Phase 2: dry → ON for dryval×0.5 seconds → OFF
```

Only pin: `dry` (GPIO 14). All water valves stay OFF.

### Stage 6 — Disinfectant (pet has been offboarded)

```
Parallel: p4 → ON for wt×0.8 seconds → OFF   (fill disinfectant into Container 2)

Phase 1 (spray disinfectant):
  s8 + s3 + s4 + s2 + d2 + pump → ON for dval seconds → OFF

Phase 2 (water rinse):
  s8 + s5 + s2 + s4 + pump → ON for dval seconds → OFF
```

### Stage 7 — Autoflush

```
Phase 1: flushmain + top + pump → ON for fval seconds → top + pump OFF
Phase 2: bottom + pump → ON for fval seconds → bottom + pump + flushmain OFF
```

**Note:** `flushmain` stays ON across both phases. Uses a completely different
water path than stages 0–6 (bypasses geyser, goes through AF gate).

### Post-Session Cleanup

```
emptytime(d1, ro2, 8)    — drain Container 1
emptytime(d2, ro4, 8)    — drain Container 2
Allclose()               — all 24 relays OFF (safety)
```

---

## 6. Non-Plumbing Hardware

### 6.1 Dryer

| Variable | GPIO | Voltage | Purpose |
|----------|------|---------|---------|
| `dry` | 14 | 220V | Blower motor — hot air dryer |

Runs in two halves with a 15-second break. Only active during Stage 5.

### 6.2 Lighting & Indicators

| Variable | GPIO | Voltage | Purpose |
|----------|------|---------|---------|
| `rglight` | 24 | 220V | RGB ambient light strip — ON during session |
| `roof` | 15 | 220V | Roof lights — timed (5 PM – 5 AM) + ON during full session |
| `green` | I2C GPB1 | — | Green indicator light (via MCP23017, commented out) |

### 6.3 Geyser (Water Heater)

| Variable | GPIO | Voltage | Purpose |
|----------|------|---------|---------|
| `geyser` | I2C GPB2 | — | Water heater (via MCP23017 @ 0x22, Bus 3, commented out) |

The geyser sits between the booster pump and the main gate. It heats water
for the pet bath. In the old code, geyser control was via I2C extender board
but was commented out (likely controlled manually or always on).

---

## 7. Complete Hardware Inventory

### 7.1 All Actuators (26 total)

| # | Old Variable | Old GPIO | Voltage | Physical Component | Function Group |
|---|-------------|----------|---------|-------------------|----------------|
| 1 | `p1` | 10 | 12/24V | Peristaltic Pump 1 | Chemical: Shampoo |
| 2 | `p2` | 17 | 12/24V | Peristaltic Pump 2 | Chemical: Conditioner |
| 3 | `p3` | 27 | 12/24V | Peristaltic Pump 3 | Chemical: Med Shampoo |
| 4 | `p4` | 22 | 12/24V | Peristaltic Pump 4 | Chemical: Disinfectant |
| 5 | `p5` | 4 | 12/24V | Peristaltic Pump 5 | Backup (any failed pump) |
| 6 | `ro1` | 9 | 24V | RO Solenoid 1 (6mm) | Fill Container 1 |
| 7 | `ro2` | 11 | 24V | RO Solenoid 2 (6mm) | Drain Container 1 |
| 8 | `ro3` | 5 | 24V | RO Solenoid 3 (6mm) | Fill Container 2 |
| 9 | `ro4` | 6 | 24V | RO Solenoid 4 (6mm) | Drain Container 2 |
| 10 | `d1` | 13 | 24V | Diaphragm Pump 1 | Push from Container 1 |
| 11 | `d2` | 19 | 24V | Diaphragm Pump 2 | Push from Container 2 |
| 12 | `s1` | 26 | 24V | Solenoid ½" | Line 1 entry gate |
| 13 | `s2` | 21 | 24V | Solenoid ½" | Line 1 exit gate |
| 14 | `s3` | 20 | 24V | Solenoid ½" | Line 2 entry gate |
| 15 | `s4` | 16 | 24V | Solenoid ½" | Line 2 exit gate |
| 16 | `s5` | 12 | 24V | Solenoid ½" | Line 3 (water only) |
| 17 | `top` | 7 | 24V | Solenoid ½" | Autoflush top nozzle |
| 18 | `bottom` | 8 | 24V | Solenoid ½" | Autoflush bottom nozzle |
| 19 | `s8` | 25 | 220V | Solenoid (heavy duty) | Main gate (bath lines) |
| 20 | `flushmain` | 18 | 220V | Relay | Autoflush gate |
| 21 | `pump` | 23 | 220V | Booster pump | Water pressure for everything |
| 22 | `dry` | 14 | 220V | Blower motor | Pet dryer |
| 23 | `roof` | 15 | 220V | Relay | Roof lights |
| 24 | `rglight` | 24 | 220V | Relay | RGB ambient light |
| 25 | `green` | I2C GPB1 | — | MCP23017 | Green indicator |
| 26 | `geyser` | I2C GPB2 | — | MCP23017 | Water heater |

### 7.2 Sensors & Peripherals (no GPIO — interface based)

| Component | Interface | Purpose |
|-----------|-----------|---------|
| QR Scanner | USB HID (keyboard emulation) | Session activation |
| Display | HDMI (Tkinter GUI) | Kiosk interface |
| Audio (VLC) | 3.5mm / HDMI audio | Voiceover & music |
| Geyser control | I2C (MCP23017, Bus 3) | Hot water heater |
| Green light | I2C (MCP23017, Bus 3) | Status indicator |

---

## 8. Key Design Decisions & Gotchas for New Code

### 8.1 Things the Old Code Got Right
- Priming before session start (airlock prevention)
- Anti-backflow valve logic (S2/S4 always-open pattern)
- Parallel peristaltic pump fill while voiceover plays (no wasted time)
- Post-session container drain (`emptytime`)

### 8.2 Problems in the Old Code (to fix in new IoT version)
1. **Redundant functions** — `Shampoo()`, `Conditioner()`, `Mbath()` are nearly
   identical (same pin pattern, only the peristaltic pump differs). Should be
   one `inject_chemical(container, pump, duration)` function.
2. **No stage state machine** — uses `if stage <= N` cascading checks, fragile
   for resumption.
3. **Hardcoded timings** — durations baked into function calls, not configurable.
4. **`p3` and `p5` never used** — `p3` (med shampoo) is defined but `Mbath()`
   actually uses `p4` (which is also the disinfectant pump). This is a **bug** —
   medicated shampoo should use `p3` and go into Container 1, but the old code
   routes it through `p4` which feeds Container 2.
5. **Flush order** — code does top-first but physical logic suggests bottom-first
   (clean floor debris up, then rinse walls down).
6. **No error recovery** — if a relay fails mid-stage, everything hangs.
7. **Global variable soup** — `qr`, `bstatus`, `status`, `extradry`, `ustat`
   all globals, making the code hard to reason about.

### 8.3 What the New IoT Code Needs

The physical plumbing and valve logic stays the same. What changes is:
- **GPIO ownership** moves from one Raspberry Pi to multiple ESP32 nodes
- **Stage execution** becomes a clean state machine on the master (RPi)
- **Commands** are sent over ESP-NOW/WiFi from master to nodes
- **Each ESP32 node** owns a subset of relays (grouped by physical proximity)
- **Timing/configuration** comes from the database, not hardcoded values

---

## 9. Valve Combination Quick Reference (for new code)

This is the **truth table** for which valves must be open for each activity.
The new IoT code should use this as its core relay-activation map:

| Activity | s8 | s1 | s2 | s3 | s4 | s5 | d1 | d2 | pump | flushmain | top | bottom | dry |
|----------|----|----|----|----|----|----|----|----|------|-----------|-----|--------|-----|
| Shampoo spray | ON | ON | ON | — | ON | — | ON | — | ON | — | — | — | — |
| Conditioner spray | ON | ON | ON | — | ON | — | ON | — | ON | — | — | — | — |
| Med shampoo spray | ON | ON | ON | — | ON | — | ON | — | ON | — | — | — | — |
| Water rinse | ON | — | ON | — | ON | ON | — | — | ON | — | — | — | — |
| Disinfectant spray | ON | — | ON | ON | ON | — | — | ON | ON | — | — | — | — |
| Disinfectant rinse | ON | — | ON | — | ON | ON | — | — | ON | — | — | — | — |
| Autoflush top | — | — | — | — | — | — | — | — | ON | ON | ON | — | — |
| Autoflush bottom | — | — | — | — | — | — | — | — | ON | ON | — | ON | — |
| Dryer | — | — | — | — | — | — | — | — | — | — | — | — | ON |
| Prime fill C1 | ON | ON | — | — | — | — | — | — | — | — | — | — | — |
| Prime empty C1 | — | — | — | — | — | — | ON | — | — | — | — | — | — |
| Prime fill C2 | ON | — | — | ON | — | — | — | — | — | — | — | — | — |
| Prime empty C2 | — | — | — | — | — | — | — | ON | — | — | — | — | — |

*(ro1–ro4 and p1–p5 are omitted from this table for clarity — they run in
parallel as described in §4)*

### Peristaltic Pump Assignment

| Activity | Pump | Container |
|----------|------|-----------|
| Shampoo fill | `p1` | Container 1 |
| Conditioner fill | `p2` | Container 1 |
| Med shampoo fill | `p3` | Container 1 |
| Disinfectant fill | `p4` | Container 2 |
| Backup (any failure) | `p5` | Either |

### RO Solenoid Assignment

| Action | Solenoid | Container |
|--------|----------|-----------|
| Fill Container 1 (water) | `ro1` | Container 1 |
| Drain Container 1 | `ro2` | Container 1 |
| Fill Container 2 (water) | `ro3` | Container 2 |
| Drain Container 2 | `ro4` | Container 2 |

---

## 10. Ready for New Node Mapping

The physical system has **26 actuator outputs**. These need to be distributed
across the new ESP32 nodes based on:
- Physical proximity (wire length minimization)
- Voltage grouping (24V relays vs 220V relays)
- Functional grouping (which pins fire together)

**Awaiting:** New ESP32 node GPIO assignments from the user to map
`old variable → new node + new GPIO`.

---

*This document + `OLD_PROJECT_GPIO_HARDWARE_MAP.md` together form the complete
reference for building the new IoT Spotless system.*
