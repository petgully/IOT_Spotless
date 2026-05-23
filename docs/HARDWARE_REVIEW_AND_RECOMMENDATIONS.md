# Hardware Architecture Review & Recommendations

> **Date:** March 2026
>
> This document captures a detailed analysis of the Spotless hardware setup
> compared to commercial pet wash systems (iClean, Evolution Dog Wash), and
> provides actionable recommendations for future hardware revisions.

---

## 1. Current Spotless Hardware Setup

Spotless uses a **container-based chemical injection system**:

```
Bottle → Peristaltic Pump → Container → Diaphragm Pump → T-junction → Water Line
         (meters exact ml)   (mixing)    (pushes mix)      (injection)
```

**Per chemical line:** Peristaltic pump + Container + RO fill solenoid + RO drain
solenoid + Diaphragm pump + 2 line solenoids = **7 components**

**Total actuators:** 26 (24 GPIO + 2 I2C)

---

## 2. How Commercial Systems Do It

### iClean Dog Wash (Netherlands, 50+ years, 25+ countries)

iClean uses **peristaltic dosing pumps** — confirmed from their parts catalog:
- Peristaltic Dosing Pump: EUR 425
- Suction Lance (replacement): EUR 85
- Injection Valve (replacement): EUR 25

Their architecture:

```
Bottle → Peristaltic Pump → Injection Valve → directly into water line
         (meters exact ml)   (one-way check)    (water carries it out)
```

**No container. No diaphragm pump. No RO fill/drain. No priming.**

### Evolution Dog Wash

Uses **venturi injection** (ratio-based, not ml-precise). Products are infused
directly into the water stream using water pressure alone. Works like a
self-serve car wash — customer selects product, water+chemical mix flows
through the spray gun.

### Key Difference: Venturi vs Peristaltic

| Feature | Venturi Injector | Peristaltic Pump |
|---------|-----------------|------------------|
| Dosing method | Ratio-based (e.g., 1:128) | Exact ml volume |
| Moving parts | Zero | Rollers + tubing |
| Electricity needed | No | Yes |
| Precision | Concentration ratio | Exact volume (30ml, 50ml, etc.) |
| Cost | $10-30 | $50-425 |
| Use case | Self-serve (customer controls time) | Fully automated (machine controls dose) |

**Verdict:** Venturi is great for self-serve stations where the customer holds
the spray gun. For a fully automated system like Spotless (where the machine
must dispense exactly 30ml for small dogs, 50ml for large), **peristaltic
pumps are the correct choice** — and this is what iClean uses too.

---

## 3. What Spotless Gets Right

1. **Peristaltic pumps for precise ml dosing** — industry standard, same as iClean
2. **Separate containers for pet chemicals vs disinfectant** — prevents cross-contamination
3. **Anti-backflow valve logic** — opening S2/S4 to prevent reverse flow
4. **Backup pump (p5)** — good redundancy
5. **Separate autoflush water path** — bypasses geyser, high-pressure tub cleaning

---

## 4. What Could Be Improved

### Problem 1: Container system causes airlock

The container fills, empties, and refills. When it empties, air enters the
diaphragm pump line. Next session, d1/d2 compresses air instead of pushing
liquid. This requires a priming stage (16+ seconds per session).

**iClean's approach:** Peristaltic pump pushes directly into the water line
through an injection valve (one-way check valve). No container = no air entry
= no airlock = no priming needed.

### Problem 2: Diaphragm pumps are the #1 failure point

The rubber membrane flexes thousands of times and eventually cracks. When d1
or d2 fails, the entire process stops. These pumps cost $30-80 each and
require periodic replacement.

**iClean's approach:** No diaphragm pumps at all. The peristaltic pump pushes
directly into the pressurized water line. The water pressure carries the
chemical to the nozzle.

### Problem 3: RO solenoids add unnecessary complexity

ro1-ro4 exist only to fill and drain the containers for priming. Without
containers, these 4 solenoids and their wiring are eliminated.

### Problem 4: Anti-backflow hack with extra solenoids

Opening S2 and S4 as "anti-backflow" gates works but is fragile (relies on
correct software logic). Commercial systems use **passive check valves**
(one-way, mechanical, ~$5 each) that physically block reverse flow without
any electronic control.

---

## 5. Recommended Future Hardware Revision (V2)

### Replace container system with direct injection

```
CURRENT (V1):
  Bottle → Peristaltic → Container → Diaphragm → T-junction → Water line
  Components: 7 per chemical line

PROPOSED (V2):
  Bottle → Peristaltic → Injection Valve → Water line
  Components: 2 per chemical line
```

### Add passive check valves

Replace the S2/S4 anti-backflow software hack with $5 check valves on each
line. Each line gets a one-way valve that mechanically prevents reverse flow.

### Component reduction

| Component | V1 (Current) | V2 (Proposed) | Saved |
|-----------|-------------|---------------|-------|
| Containers | 2 | 0 | 2 |
| Diaphragm pumps (d1, d2) | 2 | 0 | 2 |
| RO solenoids (ro1-ro4) | 4 | 0 | 4 |
| Peristaltic pumps | 5 | 5 | 0 |
| Line solenoids | 7 | 5 + check valves | 2 |
| Check valves | 0 | 3-5 (~$5 each) | — |
| **Total electrical** | **26** | **~14** | **12** |

### Priming stage

Eliminated entirely. No container = no airlock = no priming.

### Estimated savings per booth

- 6 fewer electrical components (d1, d2, ro1-ro4): ~$200
- 2 fewer containers + plumbing: ~$50
- 5 check valves added: ~$25
- Eliminated priming stage: ~16 seconds per session saved
- **Net savings: ~$225 per booth + reduced maintenance + fewer failure points**

---

## 6. Decision

**For the current IoT code refactor:** Keep existing V1 hardware as-is. The
plumbing is built and working. The new code handles the existing 26 actuators
with the same valve logic.

**For future V2 hardware:** Apply the recommendations above when building the
next booth or during a major maintenance cycle. The code architecture (data-driven
stage configs) is designed to accommodate either hardware version — just change
the stage definitions.

---

*This review was conducted by analyzing the Spotless V7 codebase, physical
plumbing diagrams, and researching iClean Dog Wash, Evolution Dog Wash, and
commercial chemical dispensing systems (venturi injectors, metering pumps,
mixing stations from Lafferty, Alpha Tech Pet, and Dosatron).*
