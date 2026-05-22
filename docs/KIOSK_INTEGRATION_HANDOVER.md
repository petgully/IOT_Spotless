# Spotless ↔ Kiosk Integration — Handover Document

> **Purpose:** This doc is the single reference for the SpotlessBooking ↔ Kiosk
> integration work delivered from the SpotlessBooking repo side. Hand this to
> the kiosk repo team so they know exactly what's done, what API contract
> they're integrating against, what they still need to do on their side,
> and what tests must be jointly green before declaring the integration
> complete.
>
> **Source of truth (input):** `FRONTEND_CHANGE_REQUEST.md` (this repo) ←
> derived from `docs/INTEGRATION_CONTRACT.md v1.1` (kiosk repo).
>
> **Status:** SpotlessBooking side is **code-complete + DB-migrated**.
> Pending: deploy, kiosk-side code changes, joint smoke tests, optional
> admin-panel observability (PR 5).

---

## 1. Quick scoreboard

| Area | Status | Notes |
|---|---|---|
| DB schema migration | ✅ Done | All ALTER + INSERT statements executed on RDS |
| Spotless backend (Python) | ✅ Done | All 4 INSERT INTO bookings sites + API rewrite + DIY enable + just_dry support |
| Spotless frontend (templates) | ✅ Done | Booking page, confirmation page, email template |
| Code deployed to live server | ❌ TODO | Merge this PR → deploy → restart Flask |
| `KIOSK_API_KEY` env var on server | ❌ TODO | Optional but recommended |
| Kiosk repo updates | ❌ TODO (kiosk team) | See §6 |
| Joint smoke tests | ❌ TODO | See §7 |
| Admin panel observability (PR 5) | ⏸ Deferred | Non-blocking |

---

## 2. What got delivered (this PR)

### 2.1 Database changes — already executed on RDS
You don't need to re-run any of this. Recording here for the audit trail:

```sql
-- A. Added the missing addons column to bookings
ALTER TABLE bookings
  ADD COLUMN addons VARCHAR(255) NOT NULL DEFAULT ''
  AFTER session_type;

-- B. Added the extra_dry add-on (Spotless-only, ₹50)
INSERT INTO mg_addons
    (addon_code, addon_name, price, icon, description, duration_minutes,
     applicable_packages, service_type, display_order, is_active)
VALUES
    ('extra_dry', 'Extra Dry (+5 min)', 50.00, '🌬',
     '5 extra minutes of dryer time for a thoroughly fluffy finish',
     5, 'bath_pkg,complete_pkg,diy_bath',
     'spotless_only', 10, 1);

-- C. Added the "Just Dry" main package
INSERT INTO service_packages
    (code, name, description, includes, icon, display_order, is_active)
VALUES
    ('just_dry', 'Just Dry',
     'Quick 5-minute dryer-only session — perfect after a swim, rain, or home bath',
     'Dryer cycle only', '🌬', 4, 1);

-- D. Pricing for Just Dry — ₹100 across all sizes
INSERT INTO package_pricing (service_id, size, price, currency, is_active, effective_from)
VALUES
    ((SELECT id FROM service_packages WHERE code='just_dry'), 'small',        100.00, 'INR', 1, CURDATE()),
    ((SELECT id FROM service_packages WHERE code='just_dry'), 'medium',       100.00, 'INR', 1, CURDATE()),
    ((SELECT id FROM service_packages WHERE code='just_dry'), 'medium_large', 100.00, 'INR', 1, CURDATE()),
    ((SELECT id FROM service_packages WHERE code='just_dry'), 'large',        100.00, 'INR', 1, CURDATE()),
    ((SELECT id FROM service_packages WHERE code='just_dry'), 'xl',           100.00, 'INR', 1, CURDATE());
```

> The `booking_sessions` table was pre-created on RDS via Workbench by the user
> earlier (per the change request §A heads-up). This repo does not own
> writes to that table; the kiosk does.

### 2.2 Backend code changes (`app.py`)

| Area | What changed |
|---|---|
| `book_session` POST (~L3482) | INSERT now includes `addons` + `payment_status='paid'` |
| `admin_book_free` (~L6384) | INSERT now includes `addons` |
| `/api/payment/verify` (~L6820) | INSERT now includes `addons` |
| `_reconcile_payment_row` (webhook fallback ~L6982) | INSERT now includes `addons` recovered from `payments.notes` JSON; default `session_type` fixed from `'bath'` → `'bath_pkg'` (latent bug) |
| `send_booking_confirmation_email` (~L350) | Now resolves `addon_display` from `mg_addons` and passes it to the email template. Branches on `booking_type` for MG vs Spotless. |
| `booking_confirmation` route (~L3651) | Fetches addon display names and passes `addon_display` to template |
| `_check_kiosk_api_key()` (new) | Helper for env-gated shared API key auth (timing-safe compare) |
| `_iso_or_none()` (new) | ISO 8601 serialization helper for kiosk JSON payload |
| **`api_get_booking(code)` — REWRITTEN** | See §3 for full contract |
| DIY guards removed (4 sites) | book_session POST (~L3392), admin_book_free (~L6306), create-order (~L6569), verify (~L6706) |
| Prime discount exclusions | Added `just_dry` to 4 Spotless pricing paths (book_session, admin-free, create-order, verify) |

### 2.3 Frontend / template changes

| File | What changed |
|---|---|
| `templates/book_session.html` | DIY tile no longer `disabled` / "Coming Soon" badged. Removed hardcoded "Just Add-ons" tile (replaced by DB-driven `just_dry` package). |
| `templates/booking_confirmation.html` | Added "Add-ons" row (gated by `{% if addon_display %}`). Added `just_dry` → "Just Dry" to package name map. |
| `templates/email/booking_confirmation.html` | Added "Add-ons" row. Replaced raw `{{ session_type }}` + CSS capitalize with proper `pkg_names` map (now displays "Just Dry", "Bath Package", etc., instead of "Just_dry", "Bath_pkg"). |

### 2.4 What was explicitly **NOT** done in this PR

| Item | Reason |
|---|---|
| B5 — Stop writing `session_config` table | Optional cleanup. Deferred. Still being written from all 3 user paths. Kiosk does not read it anymore so this is harmless I/O. |
| B6 — `pets.species` form field cleanup | Unrelated to kiosk. Deferred. |
| A3 — Standardise `pets.size` ENUM | No urgency. Kiosk handles all 5 values today. |
| G1, G3 — Admin panel observability | Deferred to PR 5. Non-blocking for kiosk Phase 2 testing. |
| G2 — Admin abort + refund-token actions | Belongs to Phase 4 admin module spec. |
| H1 — Daily abandonment cron sweep | Deferred to PR 5. |
| D2 — `indie_special` catalog row | Per business owner: indie pets are treated as `size='small'`. No separate package needed. |

---

## 3. Kiosk API contract — what the kiosk integrates against

### 3.1 Endpoint
```
GET /api/booking/<booking_code>
```

### 3.2 Request

**Query parameters (required):**
- `machine_id` — the calling kiosk's unique ID (e.g. `KIOSK-01`)

**Headers (required when `KIOSK_API_KEY` env var is set on the server):**
- `X-Kiosk-Key: <shared-secret>` — must match the server's `KIOSK_API_KEY` exactly

**If `KIOSK_API_KEY` is NOT set on server** → header is not checked (dev mode).

**Example:**
```bash
curl -H "X-Kiosk-Key: $KIOSK_API_KEY" \
     "https://<host>/api/booking/PGD9F04A1C?machine_id=KIOSK-01"
```

### 3.3 Response — success (200)

```json
{
  "booking": {
    "booking_code": "PGD9F04A1C",
    "package": "bath_pkg",
    "addons": ["extra_dry"],
    "status": "confirmed",
    "payment_status": "paid",
    "booking_date": "2026-05-22",
    "created_at": "2026-05-22T14:08:11",
    "pet_size": "medium",
    "pet_name": "Bruno",
    "breed": "Labrador",
    "customer_name": "Asha M.",
    "customer_email": "asha@example.com"
  },
  "session_state": null,
  "gate_result": "ok"
}
```

**Field semantics:**
- `booking.package` — one of: `bath_pkg`, `complete_pkg`, `diy_bath`, `indie_special`, `just_dry`. **Never** `trim_pkg` (server-side gate rejects it). **Never** `addon_only` (deprecated — removed from catalog).
- `booking.addons` — list of strings, parsed from CSV on the server. Empty list `[]` if no add-ons.
- `booking.pet_size` — one of: `small`, `medium`, `medium_large`, `large`, `xl`, `indie`. Kiosk must map all of `small/medium/medium_large/large` → SET A, `xl` → SET B (`indie` is treated as small per business decision).
- `session_state` — `null` for a brand-new booking. Populated object when there's an existing `booking_sessions` row (resume scenario).
- `gate_result` — `"ok"` (start fresh session) or `"resume"` (continue from saved checkpoint).

**`session_state` object (when present):**
```json
{
  "machine_id": "KIOSK-01",
  "status": "in_progress",
  "completed_stages": "shampoo,conditioner,rinse",
  "last_stage": "drying",
  "resume_count": 1,
  "started_at": "2026-05-22T14:10:33",
  "completed_at": null,
  "updated_at": "2026-05-22T14:18:02",
  "seconds_since_last_update": 47
}
```

### 3.4 Response — failure (4xx)

Always:
```json
{ "error": "<error_code>" }
```

**HTTP status + error codes:**

| Status | Error code | Meaning |
|---|---|---|
| 400 | `machine_id_required` | Query param missing |
| 401 | `api_key_required` | Header missing (when server has key configured) |
| 401 | `api_key_invalid` | Wrong key |
| 403 | `payment_not_confirmed` | Customer hasn't paid (or payment_status is something other than `paid`/`null`) |
| 403 | `booking_cancelled` / `booking_completed` / `booking_<status>` | Booking row's `status` is not `confirmed`/`pending` |
| 403 | `booking_in_future` | `booking_date` is later than today (IST) |
| 403 | `booking_already_used` | A `booking_sessions` row already shows `status='completed'` |
| 403 | `booking_active_on_other_machine` | Active `in_progress` session, but bound to a different `machine_id` |
| 403 | `booking_abandoned` | `in_progress` session not updated in 7+ days |
| 403 | `machine_does_not_serve_trim` | `package='trim_pkg'` (kiosk doesn't support trim) |
| 403 | `unknown_package` | Package code not in allowed list |
| 404 | `booking_not_found` | No booking with that code |
| 500 | `internal_error` | Server error (check Spotless logs) |
| 503 | `database_unavailable` | DB connection failed |

### 3.5 Package → hardware-cycle mapping (kiosk-side responsibility)

| `package` value | What the kiosk should run |
|---|---|
| `bath_pkg` | Shampoo → Conditioner → Rinse → Dryer (standard cycle) |
| `complete_pkg` | Same as bath_pkg (premium products, same machine sequence) |
| `diy_bath` | Same hardware cycle as `bath_pkg`. Customer-driven; same hardware. |
| `indie_special` | Hardware = SET A regardless of `pet_size`. |
| `just_dry` | **Dryer stage only.** ~5 min default. No shampoo, no conditioner, no rinse. |

**Add-on modifiers (on top of the base cycle):**

| `addon` code | Effect |
|---|---|
| `extra_dry` (when paired with `bath_pkg` / `complete_pkg` / `diy_bath`) | **+300 seconds on the dryer stage** of that cycle |
| `med_bath` (existing) | Swap the shampoo pump to the medicated reservoir for this session |

> Note: `extra_dry` will **never** appear in the `addons` list when `package='just_dry'` — the server already enforces that via `mg_addons.applicable_packages`. The kiosk does not need to handle that combo.

### 3.6 `machine_id` semantics
- It's a free-form string. No registry today.
- The server uses it for two checks:
  1. **Lock**: if any `booking_sessions` row exists for this booking with `status='in_progress'` and a DIFFERENT `machine_id`, the API returns `booking_active_on_other_machine` and the calling kiosk must refuse to start.
  2. **Resume**: if the in-progress row has the SAME `machine_id` as the caller, the API returns `gate_result='resume'` and the kiosk should pick up from `session_state.last_stage`.
- For now there's one machine. When you add more, just pick a unique string per machine. No code change needed on this side.

---

## 4. SQL data model — what the kiosk reads/writes

**Kiosk reads from:** `bookings`, `pets`, `customers`, `mg_addons`, `booking_sessions` (via this API, or directly with a DB connection — your call).

**Kiosk writes to:** `booking_sessions` only. Insert a new row when a session starts, update it as stages complete, mark `status='completed'` when done. Update `bookings.status='completed'` at the end if you want that visible in admin.

**Kiosk MUST NOT write to:** `bookings`, `payments`, `customers`, `pets`, `mg_addons`, `service_packages`, `package_pricing`.

---

## 5. Spotless-side deployment checklist (still pending — owner: SpotlessBooking team)

### 5.1 Deploy the code
- [ ] Merge this PR into the deploy branch (usually `main` or `feature/dashboard_updates_v1`)
- [ ] Deploy to live server (Render auto-deploys on push to main)
- [ ] Confirm Flask process restarted

### 5.2 (Recommended) Set `KIOSK_API_KEY`
- [ ] Generate: `python -c "import secrets; print(secrets.token_urlsafe(40))"`
- [ ] Set as env var on live server (Render dashboard → Environment)
- [ ] Restart Flask
- [ ] Share same value with kiosk team (secure channel — not Slack/email)

If skipped, endpoint is public-readable. Booking codes are unguessable, so it's not catastrophic — but defense-in-depth is better.

### 5.3 Quick smoke tests (no kiosk needed — runnable today)

```bash
# 1. Endpoint exists and rejects missing machine_id
curl "https://<host>/api/booking/<any_code>"
# Expect: {"error":"machine_id_required"} 400

# 2. Endpoint rejects non-existent booking
curl "https://<host>/api/booking/PGNOTREAL?machine_id=KIOSK-01"
# Expect: {"error":"booking_not_found"} 404

# 3. Endpoint returns full payload for a real booking
curl "https://<host>/api/booking/<real_test_code>?machine_id=KIOSK-01" | jq
# Expect: 200 with booking{} + session_state{|null} + gate_result
```

```sql
-- 4. New bookings persist addons
-- Book a session via the UI with `extra_dry` checked, then:
SELECT booking_code, session_type, addons, payment_status, status
FROM bookings ORDER BY id DESC LIMIT 1;
-- Expect: addons='extra_dry', payment_status='paid'

-- 5. Just Dry tile works
-- Book via "Just Dry" tile in UI, then:
SELECT booking_code, session_type, addons, amount
FROM bookings ORDER BY id DESC LIMIT 1;
-- Expect: session_type='just_dry', addons='', amount=100

-- 6. DIY is now bookable
-- Book via DIY tile, then:
SELECT booking_code, session_type, payment_status
FROM bookings ORDER BY id DESC LIMIT 1;
-- Expect: session_type='diy_bath', no errors
```

---

## 6. Kiosk-side TODO (owner: kiosk repo team)

> Share this section with the kiosk repo team. These are the changes they need
> in their own codebase to integrate with the now-updated SpotlessBooking API.

### 6.1 API client changes
- [ ] Update the kiosk's API client to call `GET /api/booking/<code>?machine_id=<MACHINE_ID>`.
- [ ] Send `X-Kiosk-Key: <secret>` header. Read from kiosk's local env (e.g. `BOOKING_API_KEY`).
- [ ] Parse the new response shape (see §3). **Drop** any code that relied on the old `success: true` wrapper or the old `sval/cval/dval/wval/dryval` fields.
- [ ] Handle every `error` code from §3.4 — show a sensible message to the user for each (e.g. "This booking is already in use on another machine", "Your booking has expired", etc.).

### 6.2 Package handling
- [ ] Add `just_dry` to the package → hardware mapping (dryer stage only).
- [ ] Remove any `addon_only` handling (no longer used).
- [ ] Verify `diy_bath` is wired up — it'll start hitting the kiosk now that the booking-side guard is removed and business has signed off.

### 6.3 Add-on handling
- [ ] When `addons` contains `extra_dry`, add +300 s to the dryer stage of the base cycle.
- [ ] `extra_dry` will only appear with `bath_pkg`, `complete_pkg`, or `diy_bath`. Never with `just_dry`.

### 6.4 booking_sessions writes
- [ ] On session start, INSERT a row with `(booking_code, machine_id, status='in_progress', started_at=NOW())`.
- [ ] On each stage complete, UPDATE `completed_stages`, `last_stage`, `updated_at=NOW()`.
- [ ] On clean completion: UPDATE `status='completed'`, `completed_at=NOW()`. Also UPDATE the parent `bookings.status='completed'`.
- [ ] On resume (`gate_result='resume'`), increment `resume_count`.

---

## 7. Joint smoke-test checklist (both teams together)

These are the must-pass tests **after both repos are deployed**. Map to the
verification checklist (§I) of `FRONTEND_CHANGE_REQUEST.md`.

| # | Check | Who runs |
|---|---|---|
| T1 | Book a `bath_pkg` + `extra_dry` in UI → `bookings.addons='extra_dry'` | Spotless |
| T2 | Book fully with credits → `bookings.payment_status='paid'` | Spotless |
| T3 | Book `diy_bath` → reaches confirmation page | Spotless |
| T4 | Book `just_dry` → reaches confirmation, no add-on section shown | Spotless |
| T5 | `/api/booking/<code>?machine_id=KIOSK-01` → 200 with new shape | Spotless (curl) |
| T6 | Same code on `KIOSK-02` while KIOSK-01 has it in_progress → 403 `booking_active_on_other_machine` | Both |
| T7 | Trim-only booking via API → 403 `machine_does_not_serve_trim` | Spotless (curl) |
| T8 | Webhook fallback path — simulate `payment.captured` → booking row has correct addons | Spotless |
| T9 | End-to-end: book → pay → walk to kiosk → scan QR → full cycle runs → `booking_sessions.status='completed'`, `bookings.status='completed'` | Both |
| T10 | Power-loss resume: start session → cut kiosk power mid-dryer → restart → rescan → dryer resumes from saved checkpoint, not from 0 | Both |
| T11 | Anti-fraud cycle attack: start dryer → wait near end → cut power → restart → rescan → only remaining seconds run, refuses repeat | Both |
| T12 | Just Dry on kiosk: scan a just_dry booking → only dryer stage runs (~5 min), no shampoo/rinse | Both |
| T13 | Extra Dry add-on: scan a bath_pkg+extra_dry booking → dryer runs +5 min longer than a plain bath_pkg | Both |

When all of T1–T13 pass, the integration is complete.

---

## 8. Rollback plans

If anything breaks in production, here's how to back out:

| What broke | Rollback |
|---|---|
| New bookings fail with "Unknown column 'addons'" | DB migration didn't run / didn't deploy. Run `ALTER TABLE bookings ADD COLUMN addons VARCHAR(255) NOT NULL DEFAULT '';` |
| Kiosk gets 401 on every call | `KIOSK_API_KEY` mismatch between server and kiosk. Re-sync the env vars, or unset on server to disable auth. |
| Kiosk gets wrong response shape | This repo's new code didn't deploy. Re-deploy. |
| All Spotless booking fails | Revert this PR. The DB schema additions are backward-compatible (defaults to `''`) — old code will not break on the new column. |
| `just_dry` priced wrong | `UPDATE package_pricing pp JOIN service_packages sp ON pp.service_id=sp.id SET pp.price = <new> WHERE sp.code='just_dry';` |

The new `addons` column is purely additive — dropping it would only break the
new code, not historical reads. Old bookings with empty `addons` continue to
work fine.

---

## 9. Open / deferred items (not blocking integration)

These are tracked here so they don't get forgotten:

1. **PR 5 — Admin panel observability** — show `booking_sessions.status` /
   `machine_id` / `resume_count` per booking on `/admin/panel/spotless`.
   Plus optional summary tile. Ship after smoke tests pass.
2. **Daily abandonment cron** — `scripts/abandon_stale_sessions.py` to
   transition stale `in_progress` rows to `abandoned` after 7 days. Part of
   PR 5.
3. **`session_config` table writes** — still being written from 3 paths.
   Kiosk doesn't read it anymore. Cleanup pass once the kiosk is fully on
   the new model and admin reports are confirmed not reading from it.
4. **`pets.species` form field** — collected but never persisted. Either add
   the column or remove the field. Not kiosk-blocking.
5. **`pets.size` ENUM cleanup** — consolidate `medium`/`medium_large`/`large`
   into a cleaner set. Tackle in a future cleanup migration.
6. **Admin abort + refund-token actions** — Phase 4 admin module.
7. **Per-machine API keys (instead of one shared)** — Phase 4 hardening.
   Today's shared-key model is fine while there's one machine.

---

## 10. Contacts / file pointers

- **SpotlessBooking repo:** this repo (`petgully/SpotlessBooking`).
- **Kiosk repo:** the Raspberry Pi machine repo (separate).
- **Input doc that drove this work:** `FRONTEND_CHANGE_REQUEST.md` (this repo, committed alongside the integration changes).
- **Authoritative contract:** `docs/INTEGRATION_CONTRACT.md` v1.1 (kiosk repo).
- **Main code reference for the API:** `app.py:api_get_booking` — read the docstring there for the canonical response/error contract.

---

*Document version: 1.0 — generated as part of the integration handover PR.*
