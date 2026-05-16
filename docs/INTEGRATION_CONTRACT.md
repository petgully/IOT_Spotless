# Integration Contract — SpotlessBooking ↔ IoT Kiosk

> **Status:** v1.1 — locked (resume + anti-fraud added).
> **Effective:** From Phase 2 implementation onwards.
> **Authority:** This document is the single source of truth for how the
> frontend booking app and the kiosk machine agree on data, semantics, and
> behaviour. Either side may evolve internals, but **must not break this
> contract** without bumping the version and updating this doc.
>
> **v1.1 changes vs v1.0:**
> - Removed 72-hour QR expiry. QRs no longer expire by time.
> - Added per-second stage accounting (§6.3) to prevent dryer-farming fraud.
> - Added cloud `booking_sessions` table (§4.4) — already created in RDS.
> - Added local SQLite `session_progress` schema (§8.0).
> - Added power-loss resume protocol (§9) with 7-day abandonment window.
> - Added boot recovery + admin override flow (§13).

---

## 1. Purpose

There are two repositories:

| Repo | Role |
|------|------|
| **SpotlessBooking** (`C:\…\Project_Spotless\SpotlessBooking`) | Customer booking UI, payment, QR generation, admin panel. Writes to cloud DB. |
| **IoT Spotless** (`C:\…\IOT_Spotless_Final`) | Raspberry Pi kiosk, ESP32 nodes, runs the physical bath cycle. Reads from cloud DB. |

They share one cloud database — **AWS RDS Aurora MySQL `petgully_db`**.
There is no service-mesh, no event bus, no message queue between them.
The integration is:

```
Frontend writes  →  bookings row + addons   →  Kiosk reads by booking_code
                                            ←  Kiosk writes status updates
```

This document specifies exactly what the row must contain, what the kiosk
will do with it, and what it will write back.

---

## 2. Communication channels

### 2.1 Primary: direct SQL on shared `petgully_db`

The kiosk connects to the same RDS instance as the frontend using a
read-mostly database user. All booking lookups and status writes are
direct SQL.

| Item | Value |
|------|-------|
| Host | `petgully-dbserver.cmzwm2y64qh8.us-east-1.rds.amazonaws.com` |
| Port | `3306` |
| Database | `petgully_db` |
| User (kiosk) | `spotless001` (or a dedicated kiosk user with `SELECT` + targeted `UPDATE` on `bookings`) |
| SSL | Required (`DB_SSL=true`) |

### 2.2 Secondary: REST fallback

When the kiosk has no direct DB access (network failure, RDS firewall),
it MAY fall back to:

```http
GET https://<frontend-host>/api/booking/<booking_code>
```

The endpoint already exists. Phase 3 will enrich its response to match
section 4.3.

---

## 3. The QR payload

| Property | Value |
|----------|-------|
| **Payload format** | Plain ASCII string. **No URL, no JSON, no encoding.** |
| **Pattern** | `^PG[A-F0-9]{8}$` (e.g. `PGD9F04A1C`) |
| **Length** | Exactly 10 chars |
| **Generator (frontend)** | `'PG' + uuid.uuid4().hex[:8].upper()` |
| **Renderer** | Library `qrcode` (Python) with `add_data(booking_code)` |
| **Where shown** | `/booking/<code>` confirmation page (PNG data-URL) + email |

The kiosk's barcode scanner reads the string and uses it as the lookup key.
**Nothing else is encoded in the QR** — all other data is fetched from the DB.

---

## 4. Data model (frozen)

### 4.1 `bookings` table — required columns

The kiosk depends on **exactly these columns**. Frontend may keep additional
columns, but these must always be present and populated as specified:

| Column | Type | Required value | Used by kiosk for |
|--------|------|----------------|-------------------|
| `booking_code` | `VARCHAR(20)` UNIQUE | `'PG' + 8 hex upper` | Lookup key |
| `customer_id` | `INT` | FK → `customers.id` | Logging, email recipient |
| `pet_id` | `INT` | FK → `pets.id` | Resolves `pets.size` |
| `session_type` | `VARCHAR(50)` | One of the package codes in §5.1 | Decides machine mode |
| **`addons`** | `VARCHAR(255)` **NEW** | CSV of `mg_addons.addon_code` values, e.g. `"med_bath,extra_dry"`. Empty string `""` if none. | Decides pump swap & dryer extension |
| `status` | ENUM(`pending`,`confirmed`,`completed`,`cancelled`) | Must be `'confirmed'` for kiosk to accept | Validity guard |
| `payment_status` | ENUM(`pending`,`paid`,`refunded`) | Must be `'paid'` for kiosk to accept | Validity guard |
| `booking_date` | `DATE` (nullable today) | If non-null, must be `<= today` | Validity guard |
| `created_at` | `TIMESTAMP` | Server-set | Logging only (no time-based expiry in v1.1; see §7.4) |

> **Critical addition:** `bookings.addons` does **not exist today**. Adding
> it is the single most important schema change in Phase 3. Frontend MUST
> populate it on every Spotless `INSERT INTO bookings` (paid path,
> credit-only path, webhook fallback, admin book-free).

### 4.2 `pets` table — required columns

| Column | Type | Used by kiosk for |
|--------|------|-------------------|
| `id` | `INT` | FK target |
| `name` | `VARCHAR(100)` | Kiosk display, email |
| `size` | `ENUM('small','medium','large','medium_large','xl')` | Profile selection (§5.2) |
| `breed` | `VARCHAR(100)` (nullable) | Display only |

No schema change required. The kiosk treats `indie` (if ever added to the
ENUM) as `small`. Indian-dog breed detection stays a **frontend pricing
concern** — the kiosk does not care about breed.

### 4.3 `mg_addons` table — values that affect the machine

The kiosk recognises **only two** add-on codes as machine-relevant. All
other rows are silently ignored (staff handles them off-machine).

| `addon_code` | Effect on machine | Notes |
|--------------|-------------------|-------|
| `med_bath` | Swap **shampoo** pump **p1 → p3** for the shampoo stage (medicated / tick shampoo lives in the p3 container, container 1). Conditioner pump unchanged. | Already in the catalog (`mg_addons` row exists). |
| `extra_dry` | If package is `addon_only` → run **DRYER_ONLY** mode (600 s total). Otherwise → add **+300 s** to dryer total. | **NOT in catalog today — frontend Task A2 adds the row.** |

All other addon_codes (`dental_eyecare`, `paw_moisturizing`, `deshedding`,
`dematting`, `hygiene_trim`, future ones) are **machine no-ops**. The
kiosk logs them as "non-machine add-ons" and moves on.

**Note for Phase 2 implementers:** the current `session_stages.py` uses
`ctype=200` to swap the **conditioner** stage's pump (p2 → p3). This is
**inconsistent with the contract**, which targets the **shampoo** stage.
Phase 2 must align the code with this contract (med_bath → shampoo pump
p3), not the other way around.

### 4.4 `booking_sessions` table — kiosk-owned session state (CREATED IN RDS)

This table is the **cloud source of truth for QR usage**. Kiosk writes here
on every major stage transition. Frontend reads it only for admin reporting.

```sql
CREATE TABLE `booking_sessions` (
  `id` int NOT NULL AUTO_INCREMENT,
  `booking_code` varchar(20) NOT NULL,
  `machine_id` varchar(50) NOT NULL,
  `started_at` datetime NOT NULL,
  `completed_at` datetime DEFAULT NULL,
  `completed_stages` varchar(500) DEFAULT '',     -- CSV of completed stage names
  `last_stage` varchar(50) DEFAULT NULL,           -- stage in progress at last write
  `resume_count` int DEFAULT '0',                  -- # of times session resumed after a restart
  `status` enum('in_progress','completed','aborted','abandoned') DEFAULT 'in_progress',
  `abort_reason` varchar(255) DEFAULT NULL,
  `created_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` timestamp NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uniq_code_machine` (`booking_code`,`machine_id`),
  KEY `idx_code` (`booking_code`),
  KEY `idx_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
```

Semantics:

- **`UNIQUE (booking_code, machine_id)`** — a QR binds to one machine on
  first scan. A second scan on a different machine is REFUSED (§7).
- **`completed_stages`** — CSV grown over the session lifetime; the kiosk
  appends a stage name when it finishes that stage to its full budget.
- **`status`** — lifecycle states:
  - `in_progress` — session is currently active or paused awaiting resume.
  - `completed` — all stages delivered to budget. QR is now permanently spent.
  - `aborted` — hardware fault or admin manual abort. Customer entitled to
    refund / re-booking by admin.
  - `abandoned` — no resume scan within 7 days. Forfeit.

This table was created manually in RDS by the user via MySQL Workbench.
Schema is verified to match this spec exactly (see `docs/booking_sessions_live.md`).

The kiosk recognises **only two** add-on codes as machine-relevant. All
other rows are silently ignored (staff handles them off-machine).

| `addon_code` | Effect on machine | Notes |
|--------------|-------------------|-------|
| `med_bath` | Swap shampoo pump **p1 → p3** for the shampoo stage (medicated/tick shampoo lives in the p3 container). Conditioner pump unchanged. | Already in the catalog. |
| `extra_dry` | Behaviour depends on package: see §5.3. | **NOT in catalog today — must be added in Phase 3.** Recommended row: `('extra_dry', 'Extra Dry (+5 min)', 50.00, 'bath_pkg,complete_pkg,addon_only', 'spotless_only', 1)` |

All other addon_codes (`dental_eyecare`, `paw_moisturizing`, `deshedding`,
`dematting`, `hygiene_trim`, future ones) are **machine no-ops**. The
kiosk logs them as "non-machine add-ons" and moves on.

---

## 5. Resolution rules (the heart of this contract)

Given a confirmed, paid booking, the kiosk resolves it to a **`MachineRequest`**
by applying these rules in order.

### 5.1 Step 1 — Package check

| `bookings.session_type` | Machine mode | If invalid → kiosk does |
|---|---|---|
| `bath_pkg` | `FULL_SESSION` | — |
| `complete_pkg` | `FULL_SESSION` (trim is manual) | — |
| `diy_bath` | `FULL_SESSION` (assistance level doesn't change machine ops) | — |
| `indie_special` | `FULL_SESSION` (always uses Profile A regardless of size) | — |
| `addon_only` | `DRYER_ONLY` **iff** `addons` contains `extra_dry`; otherwise **REFUSED** | Display: *"This booking has no machine service — please see staff."* |
| `trim_pkg` | **REFUSED** | Display: *"Trim is staff-only. Please proceed to the attendant."* |
| anything else | **REFUSED** | Display: *"Unknown package — please contact support."* |

### 5.2 Step 2 — Size profile selection

| `pets.size` | Selected profile |
|---|---|
| `small`, `medium`, `medium_large`, `large` | **SET A** |
| `xl` | **SET B** |
| `''` (empty) or any other | **SET A** + log warning |

**Special case:** if `session_type == 'indie_special'`, force **SET A**
regardless of `pets.size`.

### 5.3 Step 3 — Add-on application

Parse `bookings.addons` (CSV). For each recognised code:

| Code | If mode is `FULL_SESSION` | If mode is `DRYER_ONLY` |
|---|---|---|
| `med_bath` | Set `shampoo_pump = "p3"` for the shampoo stage. | Ignored (no shampoo stage). |
| `extra_dry` | Add **+300 s** to the dryer total. | Sets dryer total to **600 s** (10 min). |

Unrecognised codes are logged and ignored.

### 5.4 The resulting `MachineRequest` object

```python
{
  "booking_code": "PGD9F04A1C",
  "customer_name": "...",
  "pet_name": "...",
  "mode": "FULL_SESSION",                # or "DRYER_ONLY"
  "profile": "A",                         # or "B"
  "shampoo_pump": "p1",                   # or "p3" if med_bath
  "dryer_extra_seconds": 0,               # or 300 if extra_dry add-on
  "addons_raw": ["med_bath", "extra_dry"],
  "non_machine_addons": ["deshedding"]    # for logging only
}
```

This object is passed into the `StageExecutor` (Phase 2 work).

---

## 6. Profile values (SET A / SET B)

> **Target spec — Phase 2 implementation work.**
> This section describes the **target state** of `session_stages.py` after
> Phase 2 rewrites it. Today's `session_stages.py` has divergent values
> (e.g. `small.dryval=480`, `large.dryval=600`, `pr=20` excludes
> disinfectant, medicated path uses `ctype=200` on conditioner). Phase 2
> aligns the code to this contract — implementers should not try to
> reconcile the contract to the current code.

The actual timing values live in the kiosk's local config file —
**not** in the cloud DB. The frontend MUST NOT send timing values; the
columns `sval`, `cval`, `dval`, `wval`, `dryval`, `fval`, `wt`, `ctype` on
the `bookings` table are deprecated for the kiosk's purposes and are
ignored by the new lookup logic. (Frontend may continue writing them for
its own analytics until they are dropped in a future migration.)

**Config file location** (Phase 2): `~/.spotless/config.json` on the Pi
(the existing path used by `config_manager.py`). The file gains a new
top-level `size_profiles` section keyed `"A"` and `"B"`. The kiosk
ships a sane default if the section is missing.

### 6.1 Default values (kiosk side)

| Parameter | SET A (small / medium / medium_large / large) | SET B (xl) |
|---|---|---|
| `sval` shampoo spray | 80 s | 120 s |
| `cval` conditioner spray | 80 s | 120 s |
| `wval` water rinse | 60 s | 90 s |
| `dval` disinfectant spray | 60 s | 60 s |
| `dryval` dryer total (before `extra_dry` add-on) | 600 s | 800 s |
| `fval` autoflush per phase | 60 s | 60 s |
| `wt` peristaltic pump run | 30 s (~30 mL) | 60 s (~60 mL) |
| `msgval` massage wait | 30 s | 30 s |
| `tdry` towel wait | 30 s | 30 s |
| `prime_fill` | 30 s | 30 s |
| `prime_empty` | 6 s | 6 s |

### 6.2 Hardware sequence (identical for `FULL_SESSION` regardless of package)

Disinfectant is now **always** included as part of the standard cycle:

```
Prime (Container 1)
  ↓
Onboard (customer places pet in tub)
  ↓
Shampoo  (pump p1, or p3 if med_bath add-on)
  ↓
Massage 1
  ↓
Water Rinse 1
  ↓
Re-prime (Container 1)
  ↓
Conditioner (pump p2 always)
  ↓
Massage 2
  ↓
Final Rinse (double duration)
  ↓
Towel Dry
  ↓
Dryer Phase 1
  ↓
Break
  ↓
Dryer Phase 2     ← total dryer time = dryval + (extra_dry add-on ? 300 : 0)
  ↓
Offboard
  ↓
Prime Disinfect (Container 2)
  ↓
Disinfectant Spray (pump p4)
  ↓
Disinfect Rinse
  ↓
Drain Tanks
  ↓
Autoflush Bottom
  ↓
Autoflush Top
  ↓
Complete
```

### 6.3 `DRYER_ONLY` mode sequence

```
Onboard
  ↓
Dryer (600 s total — split into two phases with a break)
  ↓
Offboard
```

### 6.4 Stage budgets & per-second accounting (anti-fraud)

Each stage has a fixed **budget in seconds**, derived deterministically
from `(profile, add-ons)`. The kiosk tracks **delivered seconds** per
stage per booking. Hard rule:

> A stage is "delivered" only for the **wall-clock seconds during which
> its assigned device relays are confirmed ON**. Anything else (idle time,
> abort window, GPIO fault, prompt screen) does **not** count.

Accounting algorithm executed once per second by `StageExecutor`:

```python
if current_stage.relays_confirmed_on():
    delivered[current_stage.name] += 1
    if delivered[current_stage.name] >= current_stage.budget:
        mark_stage_complete(current_stage)
        advance_to_next_stage()
```

**Definition of `relays_confirmed_on()`** — precise to avoid ambiguity:

A stage's "relays confirmed ON" iff, for **every** device in
`stage.devices_on`, the kiosk has received an MQTT `…/state` retained
message confirming the device is `ON` within the last **2 seconds**
(soft timeout). For GPIO-direct devices (prefixed `gpio:`), the kiosk
reads back the GPIO pin level directly. If any device fails the check:

- The second is **NOT credited** to `delivered[stage]`.
- A counter `relay_fault_seconds` increments. If it reaches **10**
  consecutive seconds for the same stage, the session aborts with
  `abort_reason = 'relay_fault_<device>'`.

This prevents both **false credit** (commanded ON but no flow) and
**denial-of-service** by slow contacts.

On resume after a restart, the kiosk reads `delivered[stage]` from local
SQLite (§8.0) and computes:

```python
remaining = stage.budget - delivered[stage]
# Run the stage for `remaining` more seconds, then mark complete.
# If remaining <= 0, the stage is already paid in full → skip.
```

This guarantees that the total time the customer ever receives for a
given (booking, stage) cannot exceed the stage's budget, no matter how
many times the machine is power-cycled or the QR is rescanned. See §14
for the full anti-fraud guarantee matrix.

### 6.5 Stage budget defaults (derived)

For a `FULL_SESSION` booking, the per-stage budgets are derived as:

| Stage | SET A budget | SET B budget | Notes |
|---|---|---|---|
| `prime_fill` | 30 s | 30 s | Always |
| `prime_empty` | 6 s | 6 s | Always |
| `onboard` | 15 s | 15 s | Prompt; relays off — see §6.6 |
| `shampoo` | 80 s | 120 s | `sval` |
| `massage_1` | 30 s | 30 s | Prompt; relays off |
| `water_1` | 60 s | 90 s | `wval` |
| `prime_fill` (2nd) | 30 s | 30 s | Re-prime for conditioner |
| `prime_empty` (2nd) | 12 s | 12 s | |
| `conditioner` | 80 s | 120 s | `cval` |
| `massage_2` | 30 s | 30 s | Prompt |
| `water_2` | 120 s | 180 s | `wval * 2` (final rinse is doubled) |
| `towel_dry` | 30 s | 30 s | Prompt |
| `dryer_phase1` | 300 s | 400 s | `dryval / 2` |
| `dryer_break` | 15 s | 15 s | Prompt |
| `dryer_phase2` | 300 + extra | 400 + extra | `dryval / 2`. Add `+300` if `extra_dry` add-on present. |
| `offboard` | 20 s | 20 s | Prompt |
| `prime_dis_fill` | 12 s | 12 s | |
| `prime_dis_empty` | 6 s | 6 s | |
| `disinfectant` | 60 s | 60 s | `dval` |
| `disinfect_rinse` | 60 s | 60 s | `dval` |
| `drain_tanks` | 8 s | 8 s | |
| `flush_bottom` | 60 s | 60 s | `fval` |
| `flush_top` | 60 s | 60 s | `fval` |
| `complete` | 10 s | 10 s | Display only |

For `DRYER_ONLY` mode, the budgets are:

| Stage | Budget |
|---|---|
| `onboard` | 15 s |
| `dryer_phase1` | 300 s |
| `dryer_break` | 15 s |
| `dryer_phase2` | 285 s (so total dryer time = 600 s) |
| `offboard` | 20 s |

### 6.6 Prompt stages (relays-off stages)

Stages with no `devices_on` (e.g. `onboard`, `massage_1`, `towel_dry`,
`offboard`) are **prompt stages**. They have a budget too, but it
accumulates by **wall-clock time** instead of relay-ON time. The
customer cannot exploit them because there is no expensive resource to
extract — they only block the timeline.

If the kiosk is power-cycled during a prompt stage, the stage's
delivered seconds reset to 0 (i.e. the prompt re-runs in full) — this is
intentional UX (prompts are short, and the customer benefits from seeing
the instructions again on resume).

> **Implementation note (Phase 2):** the distinction between
> "relay-tracked" and "wall-clock-tracked" stages will live in
> `session_stages.py` as a new field `accounting: "relays" | "wallclock"`
> on each stage dict. Today's stage dicts do not have this field —
> Phase 2 adds it. A stage with `devices_on=[]` defaults to `"wallclock"`;
> all others default to `"relays"`.

---

## 7. QR validation gates (kiosk-side)

When a QR is scanned, the kiosk runs **two SQL queries** and applies **seven
validation gates** in order. Gates fail-fast — the first failing gate
displays an error and aborts.

### 7.1 Query A — booking lookup

```sql
SELECT
    b.booking_code,
    b.session_type    AS package,
    COALESCE(b.addons, '') AS addons,
    b.status,
    b.payment_status,
    b.booking_date,
    b.created_at,
    p.size            AS pet_size,
    p.name            AS pet_name,
    p.breed,
    c.name            AS customer_name,
    c.email           AS customer_email
FROM bookings b
JOIN pets p     ON b.pet_id      = p.id
JOIN customers c ON b.customer_id = c.id
WHERE b.booking_code = %s
LIMIT 1;
```

### 7.2 Query B — session-state lookup

```sql
SELECT
    machine_id,
    status,
    completed_stages,
    last_stage,
    resume_count,
    started_at,
    completed_at,
    updated_at,
    TIMESTAMPDIFF(SECOND, updated_at, NOW()) AS seconds_since_last_update
FROM booking_sessions
WHERE booking_code = %s
ORDER BY id DESC
LIMIT 1;
```

(May return zero rows on first-ever scan — that's normal.)

### 7.3 Validation gates (applied in order)

| # | Gate | Failure message |
|---|------|-----------------|
| 1 | Row from Query A exists | "Booking not found" |
| 2 | `payment_status = 'paid'` (transitional v1.1: also accept NULL) | "Payment not confirmed" |
| 3 | `status IN ('confirmed','pending')` | "Booking is cancelled / completed" |
| 4 | `booking_date IS NULL OR booking_date <= CURDATE()` | "Booking is for a future date" |
| 5 | If Query B returns a row with `status='completed'` → REFUSE | "This QR has already been used" |
| 6 | If Query B returns a row with `status='in_progress'`: must match THIS `machine_id` AND `seconds_since_last_update <= 7*24*3600` (7 days) | "Booking is active on another machine" OR "Booking has been abandoned — please contact support" |
| 7 | Package resolution (§5.1) succeeds (not `trim_pkg`, not `addon_only` without `extra_dry`) | (varies — see §5.1) |

If all 7 pass:
- **Fresh session** (Query B returned nothing or status=`aborted`/`abandoned`):
  proceed with §8.1 (start session).
- **Resume session** (Query B returned `in_progress` on this machine, within 7 days):
  proceed with §9 (resume protocol).

### 7.4 Why "no expiry by time" is safe

QRs no longer expire after 72h. A QR is valid until:

- It is used to completion (`booking_sessions.status='completed'`), or
- It was started but the customer never came back to resume within 7 days
  of the last update (`status` auto-transitioned to `abandoned`), or
- An admin explicitly cancels it (frontend `/api/admin/spotless-cancel`).

This is enforced by the gates above — there is no `created_at + 72h` check.

---

## 8. Kiosk write protocol

The kiosk writes to **two stores**: local SQLite (fast, per-second) and
cloud RDS (durable, per major event). All writes are idempotent. The
kiosk **never** modifies `payments`, `pets`, `customers`, `mg_addons`, or
`session_config`.

### 8.0 Local SQLite — `data/session_state.db` (kiosk-only)

This database lives on the Pi only. The kiosk creates it on first boot if
missing.

```sql
CREATE TABLE IF NOT EXISTS session_progress (
    booking_code        TEXT PRIMARY KEY,
    machine_id          TEXT NOT NULL,
    pet_name            TEXT,
    profile             TEXT NOT NULL,         -- 'A' or 'B'
    mode                TEXT NOT NULL,         -- 'FULL_SESSION' or 'DRYER_ONLY'
    shampoo_pump        TEXT NOT NULL,         -- 'p1' or 'p3'
    dryer_extra_seconds INTEGER DEFAULT 0,
    addons_raw          TEXT DEFAULT '',       -- CSV
    stage_budgets       TEXT NOT NULL,         -- JSON {"shampoo": 80, ...}
    stage_delivered     TEXT NOT NULL,         -- JSON {"shampoo": 80, "water_1": 42}
    completed_stages    TEXT NOT NULL DEFAULT '',  -- CSV
    current_stage_idx   INTEGER NOT NULL DEFAULT 0,
    current_stage_name  TEXT NOT NULL,
    started_at          INTEGER NOT NULL,      -- unix epoch
    last_checkpoint_at  INTEGER NOT NULL,
    resume_count        INTEGER DEFAULT 0,
    status              TEXT NOT NULL,         -- 'active'|'paused'|'completed'|'aborted'|'abandoned'
    abort_reason        TEXT
);
CREATE INDEX IF NOT EXISTS idx_status ON session_progress(status);
```

PRAGMA settings the kiosk applies on connection:
```
journal_mode = WAL          -- crash-safe, fast concurrent reads
synchronous  = NORMAL       -- safe + fast (FULL is overkill on SD)
busy_timeout = 5000
```

Write cadence:
- **Per second** (in-memory only): update `delivered[current_stage] += 1`
  if relays confirmed ON.
- **Every 5 seconds** (flush to SQLite): single `UPDATE` of `stage_delivered`,
  `last_checkpoint_at`.
- **On stage transition**: `UPDATE` of `completed_stages`, `current_stage_idx`,
  `current_stage_name`, `stage_delivered`.
- **On session end**: `UPDATE status='completed'/'aborted'/'abandoned'`.

### 8.1 Cloud: session start (on QR validation success, fresh)

```sql
INSERT INTO booking_sessions
    (booking_code, machine_id, started_at, status, last_stage, completed_stages)
VALUES (%s, %s, NOW(), 'in_progress', %s, '')
ON DUPLICATE KEY UPDATE
    started_at       = NOW(),
    status           = 'in_progress',
    last_stage       = VALUES(last_stage),
    completed_stages = '',           -- CRITICAL: reset stale state from prior aborted/abandoned attempt
    resume_count     = 0,
    completed_at     = NULL,
    abort_reason     = NULL;
```

**Why `completed_stages = ''` reset is critical:** if the same
`(booking_code, machine_id)` row was previously left in `aborted` or
`abandoned` status (e.g. hardware fault, then admin reset), the cloud row
still carries the old `completed_stages` CSV. A fresh session must start
from a clean slate or resume logic (§9.2) will incorrectly skip stages.
The local SQLite `session_progress` row is also re-initialised when a
fresh `INSERT INTO session_progress` happens for that booking.

```sql
UPDATE bookings
SET    status     = 'confirmed',
       updated_at = NOW()
WHERE  booking_code = %s
   AND status     != 'cancelled';
```

### 8.2 Cloud: session resume (on QR validation success, matching in_progress row)

```sql
UPDATE booking_sessions
SET    resume_count = resume_count + 1,
       last_stage   = %s,
       updated_at   = NOW()
WHERE  booking_code = %s
   AND machine_id   = %s
   AND status       = 'in_progress';
```

### 8.3 Cloud: per-stage progress (after each major stage completes its full budget)

> Only fired for "major" stages — see §8.5. Prime/drain/flush stages do
> not produce cloud writes (they're tracked locally only).

```sql
-- Deduplicating append: only add the stage if not already present.
UPDATE booking_sessions
SET    completed_stages = CASE
           WHEN FIND_IN_SET(%s, completed_stages) > 0 THEN completed_stages
           WHEN completed_stages = '' OR completed_stages IS NULL THEN %s
           ELSE CONCAT(completed_stages, ',', %s)
       END,
       last_stage   = %s,
       updated_at   = NOW()
WHERE  booking_code = %s
   AND machine_id   = %s
   AND status       = 'in_progress';
```

(Parameter order: `stage_name, stage_name, stage_name, stage_name,
booking_code, machine_id`. The `CASE` ensures idempotency — calling
this twice for the same stage produces the same `completed_stages` value.)

### 8.4 Cloud: session complete

```sql
UPDATE booking_sessions
SET    status       = 'completed',
       completed_at = NOW(),
       last_stage   = 'complete',
       updated_at   = NOW()
WHERE  booking_code = %s
   AND machine_id   = %s;
```

```sql
UPDATE bookings
SET    status     = 'completed',
       updated_at = NOW()
WHERE  booking_code = %s;
```

### 8.5 Major stages that trigger cloud writes (§8.3)

Only these stages produce a cloud `UPDATE` when complete. Everything
else is local-only to keep RDS write load low:

```
shampoo, water_1, conditioner, water_2, towel_dry,
dryer_phase2, disinfectant, disinfect_rinse, flush_top
```

Total cloud writes per `FULL_SESSION`: 1 start + 9 stage updates + 1 complete = **11**.
Total cloud writes per `DRYER_ONLY`: 1 start + 1 dryer + 1 complete = **3**.

### 8.6 Cloud: hardware abort / admin abort

```sql
UPDATE booking_sessions
SET    status       = 'aborted',
       abort_reason = %s,
       completed_at = NOW(),
       updated_at   = NOW()
WHERE  booking_code = %s
   AND machine_id   = %s;
```

`bookings.status` is **not** changed on abort — the booking remains
`confirmed` so the customer is entitled to admin-driven refund or
reissue (see §13).

### 8.7 Cloud network failure handling

If the cloud RDS write fails (network down, RDS unreachable):

- Local SQLite write succeeds and is the source of truth.
- A pending-write queue (in-memory plus persisted to
  `data/cloud_write_queue.json`) buffers the write.
- A background `cloud_sync` thread retries every 30s with exponential backoff.
- Kiosk **continues running the session** — cloud durability is best-effort,
  not blocking.
- If queue grows beyond 100 entries → kiosk shows non-blocking warning
  banner; admin notification email is sent.

---

## 9. Resume protocol

### 9.1 Boot recovery (kiosk just started)

On every kiosk boot, `main.py` runs a recovery check:

```python
def recover_on_boot():
    db = sqlite3.connect("data/session_state.db")
    rows = db.execute(
        "SELECT booking_code, pet_name, current_stage_name, last_checkpoint_at "
        "FROM session_progress WHERE status = 'active'"
    ).fetchall()
    if not rows:
        return  # nothing to do
    # Take the most recent one (there should be only one)
    row = max(rows, key=lambda r: r["last_checkpoint_at"])
    show_resume_prompt(row)  # kiosk UI: "Resume bath for Milo?"
```

The kiosk does NOT auto-execute. It waits for the customer/operator to
**re-scan the QR** to confirm identity. Only then does it resume.

If multiple `active` rows exist (shouldn't happen, but defensive), the
most recent wins; older rows are auto-marked `abandoned`.

### 9.2 Resume on re-scan

When a QR is rescanned and Query B (§7.2) returns `status='in_progress'`
on this machine:

1. Confirm local `session_progress` has a row for the same `booking_code`.
   - If yes → load `stage_delivered`, jump to `current_stage_name`.
   - If no (local DB lost) → cold-recover from cloud `completed_stages`:
     skip listed stages, restart current stage from 0. (Conservative
     fallback — customer may repeat the partial stage. Acceptable rare
     case.)
2. Compute `remaining = stage_budget - delivered` for the current stage.
3. If `remaining <= 0` → advance to next stage immediately.
4. Else → resume execution of the current stage for `remaining` more seconds.
5. Increment `resume_count` (local + cloud).
6. Continue normally from there.

### 9.3 Abandonment

A session transitions from `in_progress` → `abandoned` by **either** of
two mechanisms:

**(a) Server-side cron sweep** (authoritative). The frontend runs a daily
job (see CR Task H1) that flips any `in_progress` row whose `updated_at`
is older than **7 days** to `abandoned`. This is the primary lifecycle
transition.

**(b) Scan-time refusal** (defensive). If the cron has not run yet but
the customer scans a QR whose `booking_sessions` row is `in_progress` and
older than 7 days, the kiosk:

1. Updates that row to `abandoned` itself (immediate inline cleanup):
   ```sql
   UPDATE booking_sessions
   SET status='abandoned', abort_reason='inline_stale_7d', updated_at=NOW()
   WHERE booking_code=%s AND machine_id=%s AND status='in_progress';
   ```
2. Refuses the scan with the message *"Booking has been abandoned —
   please contact support."* (Gate 6, §7.3.)

The customer must contact admin for a refund or a fresh booking. The
kiosk does NOT offer a "start fresh" option at scan time — that would
allow customers to abandon and reuse the same QR repeatedly, which is
out of scope for this protocol.

A background sweep on the kiosk (runs hourly) marks stale **local
SQLite** rows as `abandoned` but does NOT delete them — they're kept
for 30 days for forensics.

### 9.4 Resume sanity caps

- `resume_count > 10` → session aborts with reason `"too_many_resumes"`.
  Prevents pathological loops if hardware is unstable.
- Total session lifetime (start to completion) > 30 days → session aborts
  with reason `"session_too_old"`.

---

## 10. Add-on handling — examples

### 10.1 Standard bath, no add-ons

```
session_type = 'bath_pkg'
addons       = ''
pet.size     = 'small'

→ MachineRequest{ mode=FULL_SESSION, profile=A, shampoo_pump=p1,
                  dryer_extra_seconds=0 }
```

### 10.2 Complete + medicated for XL pet

```
session_type = 'complete_pkg'
addons       = 'med_bath'
pet.size     = 'xl'

→ MachineRequest{ mode=FULL_SESSION, profile=B, shampoo_pump=p3,
                  dryer_extra_seconds=0 }
```

### 10.3 Standard bath + medicated + extra dry, medium-large pet

```
session_type = 'bath_pkg'
addons       = 'med_bath,extra_dry,paw_moisturizing'
pet.size     = 'medium_large'

→ MachineRequest{ mode=FULL_SESSION, profile=A, shampoo_pump=p3,
                  dryer_extra_seconds=300,
                  non_machine_addons=['paw_moisturizing'] }
```

### 10.4 Standalone extra dry

```
session_type = 'addon_only'
addons       = 'extra_dry'
pet.size     = 'small'

→ MachineRequest{ mode=DRYER_ONLY, profile=A, shampoo_pump=None,
                  dryer_extra_seconds=0,  # base is already 600s for DRYER_ONLY
                  dryer_total_seconds=600 }
```

### 10.5 Addon-only with no extra_dry — REFUSED

```
session_type = 'addon_only'
addons       = 'deshedding,hygiene_trim'

→ Kiosk display: "This booking has no machine service — please see staff."
   Booking is NOT marked completed; status stays as-is.
```

### 10.6 Trim package — REFUSED

```
session_type = 'trim_pkg'
addons       = ''

→ Kiosk display: "Trim is staff-only. Please proceed to the attendant."
   Booking is NOT marked completed.
```

### 10.7 Indie special, XL pet

```
session_type = 'indie_special'
pet.size     = 'xl'
addons       = ''

→ MachineRequest{ mode=FULL_SESSION, profile=A,   # forced A despite size=xl
                  shampoo_pump=p1, dryer_extra_seconds=0 }
```

---

## 11. Frontend MUST / MUST NOT (summary for Phase 3 handoff)

`docs/FRONTEND_CHANGE_REQUEST.md` is the full actionable spec for the
SpotlessBooking team. This section is the headline summary.

### Frontend MUST

1. Add column **`bookings.addons VARCHAR(255) DEFAULT ''`**.
2. Populate `addons` on **every** Spotless `INSERT INTO bookings` (paid
   path, credit-only path, webhook fallback, admin book-free, admin
   reconcile).
3. Standardise `bookings.payment_status = 'paid'` on every successful
   confirmation path (the credit-only path currently omits it).
4. Add a new row to `mg_addons` for `extra_dry`.
5. Either: (a) add `addon_only` to `service_packages` catalog, or
   (b) keep it as a UI-only special branch — but document which.
6. Either: (a) add `indie_special` to `service_packages` catalog, or
   (b) keep it as a breed-driven special branch — but document which.
7. Enable `diy_bath` (remove the "coming soon" block).
8. Enrich `GET /api/booking/<code>` to return all columns listed in §7.1.
9. Guard `GET /api/booking/<code>` with the same 7 validation gates as
   the kiosk (§7.3) — including the new `booking_sessions` check.
10. Admin Spotless panel: surface `booking_sessions.status` and
    `resume_count` for each booking (read-only). Add admin actions to
    abort stuck `in_progress` sessions and to issue refund tokens for
    `aborted` sessions.

### Frontend MUST NOT

1. **Send timing values** (`sval`, `cval`, `dval`, `wval`, `dryval`,
   `fval`, `wt`, `ctype`) with the expectation the kiosk will honour
   them. The kiosk ignores these columns entirely.
2. **Encode anything other than the booking code in the QR.**
3. **Modify `booking_sessions`** from any customer-facing route. Only
   admin override routes may touch it, and only with audit logging.
4. **Modify the kiosk's machine ID / hardware configuration** through
   any DB column (admin module in Phase 4 will use a dedicated table).

---

## 12. Backward compatibility

Until Phase 3 ships:

- The kiosk will tolerate missing `bookings.addons` column (treat as
  empty string). No add-ons → no medicated swap, no dryer extension.
- The kiosk will tolerate the credit-only path's missing `payment_status`
  by **also** accepting `payment_status IS NULL`. This relaxation is
  removed in contract v1.2 once frontend writes are standardised.
- Test-prefix QR codes (`SM`, `LG`, `TEST`, `DRY`, `WATER`, `FLUSH`,
  `SHAMP`, `DEMO`, `EMPTY`) continue to work outside the booking lookup
  path. These are for ops/debugging and have no DB dependency, and they
  do NOT write to `booking_sessions`.

---

## 13. Admin override flow (operations playbook)

The kiosk does not provide a UI for these — they are admin actions
performed via the SpotlessBooking admin panel (read-only today;
write actions to be added in Phase 4).

### 13.1 Customer complaint: "machine ate my booking"

Symptom: `booking_sessions.status = 'in_progress'` for hours, customer
no longer at machine.

Action:
```sql
UPDATE booking_sessions
SET status = 'aborted',
    abort_reason = 'admin_override:<ticket_id>',
    completed_at = NOW()
WHERE booking_code = %s;
```

Then either:
- Issue refund via Razorpay admin panel, or
- Reset `bookings.status` to `confirmed` and ask customer to rescan
  (this re-runs from scratch — `stage_delivered` was on the abandoned
  machine, so the customer is not penalised).

### 13.2 Customer changes machine (machine breakdown)

Action: same as 13.1 — abort the in_progress row. Customer rescans on
the new machine, which sees no `in_progress` row and starts fresh.

### 13.3 Stuck "in_progress" sweep (automated)

A frontend cron job runs daily:

```sql
-- Mark rows abandoned if no activity for 7 days
UPDATE booking_sessions
SET status = 'abandoned',
    abort_reason = 'auto_abandoned_7d'
WHERE status = 'in_progress'
  AND updated_at < DATE_SUB(NOW(), INTERVAL 7 DAY);
```

### 13.4 Audit log

Every admin-driven change to `booking_sessions` should be written to
a new `booking_sessions_audit` table (defined when Phase 4 admin
module ships).

---

## 14. Anti-fraud guarantees

Formal guarantees the contract makes about adversarial customer behaviour:

| Attack vector | Guarantee | Mechanism |
|---|---|---|
| Power-cycle to repeat a long stage (dryer) | Customer receives at most **stage budget** seconds of any given stage per booking. | Per-second `stage_delivered` accounting in local SQLite (§6.4). |
| Use same QR on two machines | Second machine refuses. | `UNIQUE (booking_code, machine_id)` constraint on `booking_sessions` + gate #6 (§7.3). |
| Use a QR twice (after completion) | Second scan refused. | Gate #5: `status='completed'` row exists. |
| Wipe local SQLite by yanking SD card | Customer loses delivered seconds for the **current partial stage only**; all fully-completed stages remain skipped on resume. | Cloud `completed_stages` is the floor; local SQLite is the precise ledger. |
| Pull power before "completed" write | Session remains `in_progress`; resume works as normal. After 7 days idle → abandoned. | Local-first writes + cloud retry queue (§8.7). |
| Replay the QR on the same machine after completion | Refused. | Gate #5. |
| Walk away mid-session, return next day | Resume works (within 7 days). | §9.2. |
| Walk away mid-session, return after 8 days | Forced restart from zero (with admin override option). | Gate #6 + abandonment rules (§9.3). |
| Crash kiosk during prompt stage (relays off) | Prompt re-runs in full. No financial cost; small UX delay. | §6.6. |
| Decompile firmware to forge a QR | Forgery has no DB row; gate #1 fails. | QR is just a lookup key; all authority lives in DB. |
| Sniff Wi-Fi to grab another customer's QR | Even if successful, gate #6 + machine binding makes it useless once original customer starts the session. | Machine binding on first scan. |

### Additional defended scenarios

| Attack vector | Guarantee | Mechanism |
|---|---|---|
| Rapid re-scanning of the same QR (spam) | Second scan within 2 s is silently ignored (debounce); valid resumes get a confirmation prompt before action. | Kiosk-side scan debounce + UI confirmation. |
| Race: two machines insert `in_progress` for the same QR simultaneously | First INSERT wins. Loser's `INSERT` fails the `UNIQUE (booking_code, machine_id)` constraint when retried with the winner's `machine_id`, OR creates a parallel row on a different `machine_id`. **Gate 6 then refuses any subsequent scan on the loser machine** because the most recent row by `id DESC` may be the winner's. **Operational rule:** kiosks SHOULD acquire a brief application-level advisory lock (`SELECT … FOR UPDATE` on the `bookings` row) for the duration of the `INSERT INTO booking_sessions`. Two-kiosk races are vanishingly rare in practice (same customer present at two machines at once). | DB unique constraint + advisory lock (Phase 2 implementation detail). |
| Mid-session refund (`bookings.payment_status` flipped to `refunded`) | Kiosk continues the current session (already started), but the **next** scan attempt fails Gate 2. In-session abort on refund is **not** automatic — admin must manually `UPDATE booking_sessions SET status='aborted'` to interrupt. | Gate 2 + admin override (§13). |
| REST `/api/booking/<code>` replay on the wire | HTTPS only; auth via static API key in `Authorization: Bearer <key>` header (Phase 3); response is read-only and idempotent so replay has no DB effect. | Transport-layer + endpoint design. |

### What this contract does NOT defend against

- A physical attacker swapping the SD card with a forged SQLite
  (mitigated only by physical machine security — outside scope).
- Backend DB tampering by an insider (mitigated by RDS IAM and audit logs).
- Razorpay refund fraud (handled by Razorpay's own rules).
- USB-injection attacks via the barcode scanner port
  (mitigated by kiosk OS hardening — outside scope).
- DST / Pi clock skew making `updated_at` math wrong by > 1 hour.
  Kiosk should NTP-sync on boot. Without it, the 7-day abandonment
  window has ±1 day jitter at worst.

---

## 15. Versioning & change process

| Field | Value |
|-------|-------|
| **Current version** | v1.1 |
| **Previous version** | v1.0 (without resume / anti-fraud) |
| **Bumps** | Major bump on any breaking change to §3, §4.1, §4.2, §4.4, §5, §7, §8, §9. Minor bump on additive changes. |
| **Process** | Any change to this contract requires (1) update this doc, (2) update Phase 2 kiosk code, (3) update Phase 3 frontend code, in that order. |
| **Owner** | Project Spotless lead. Both repo maintainers must approve before merging contract-affecting code. |

### v1.0 → v1.1 changelog

- §3: no change to QR payload format.
- §4.1: removed 72h `created_at` stale-detection note (no longer applies).
- §4.3: clarified `med_bath` swaps **shampoo** pump (not conditioner).
- §4.4: NEW — `booking_sessions` cloud table (already created in RDS).
- §6: added "target spec" banner; corrected config file path.
- §6.3: NEW — `DRYER_ONLY` mode formalised with explicit stages.
- §6.4: NEW — per-second stage-budget accounting + precise
  `relays_confirmed_on()` definition (2 s soft timeout, 10 s fault abort).
- §6.5, §6.6: NEW — stage budget tables + prompt-stage rules.
- §7: rewritten — 7 gates instead of 6; removed 72h expiry; added
  `booking_sessions` checks (gates 5 + 6).
- §8: rewritten — local SQLite + cloud write protocols; §8.1 resets
  `completed_stages` on re-INSERT; §8.3 uses deduplicating CASE.
- §9: NEW — resume protocol + reconciled abandonment with gate 6.
- §13: NEW — admin override flow.
- §14: NEW — anti-fraud guarantees + race / refund / replay defenses.

---

## 16. Open items deferred to later phases

Not part of this contract — handled in their own future docs:

- **Admin module** (machine pairing, service-mode commands, live config
  tuning) → Phase 4 spec.
- **MQTT remote control** → Phase 5 (depends on Phase 4 design).
- **`booking_sessions_audit` table** → Phase 4 (admin write actions need
  audit trail).
- **Sunset of `session_config` writes** from frontend — optional cleanup
  once kiosk no longer reads it; not blocking.
- **Sunset of `bookings.sval / cval / ...` columns** — drop in a future
  migration after both sides confirm they're unused.
- **Per-stage telemetry / metrics** (dryer kWh, water consumption, pump
  runtime histograms) → Phase 6+ analytics work; new tables TBD.
