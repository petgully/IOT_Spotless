# Frontend Current State — SpotlessBooking Repo

**Scope of this document**
This is the read-only Phase 0 snapshot of how the **Spotless module** in
`C:\Users\deepa\Documents\Github\Project_Alpha\Project_Spotless\SpotlessBooking`
works **today**. It is the baseline we will design the integration contract
against in Phase 1. Nothing here is a recommendation — recommendations live in
the upcoming `FRONTEND_CHANGE_REQUEST.md`.

> File line citations refer to commits as they exist on disk at the time of
> exploration (Phase 0).

---

## 1. Where the Spotless module lives

The frontend repo is a **multi-module Flask monolith** (Medical, Marketing,
Pawgress, Finance, Logistics, Driver Portal, Spotless, Mobile Grooming, Chat,
Handbook). Spotless code is **not** a separate Python package — it lives inline
in `app.py` plus a handful of templates.

| File | Role |
|------|------|
| `app.py` | All Spotless routes, Razorpay integration, QR generation, kiosk-facing API, DB pool, INSERT/SELECT statements. |
| `config.py` | RDS + Razorpay environment defaults. |
| `requirements.txt` | `razorpay`, `qrcode[pil]`, `pymysql`, `DBUtils`, etc. |
| `templates/about_spotless.html` | Marketing landing page (info only, not part of booking flow). |
| `templates/book_session.html` | The booking form — package picker, add-ons, hidden timing inputs, Razorpay Checkout JS. |
| `templates/booking_confirmation.html` | Post-booking page — shows booking code + QR PNG (data-URL). |
| `templates/admin/panel_spotless.html` | Admin Spotless bookings table + cancel UI. |
| `templates/email/booking_confirmation.html` | Email body template. |
| `init_waitlist_addons.py` | Migration script for `waitlist.addons` column. **Unrelated to Spotless `bookings`.** |

There is **no** `spotless_bookings`, `spotless_packages`, or any other
Spotless-specific table. Everything reuses the shared `bookings`, `pets`,
`customers`, `payments`, `service_packages`, `package_pricing`, `mg_addons`
tables on the central RDS.

---

## 2. Database

### 2.1 Engine and connection

- **Engine:** AWS RDS Aurora MySQL.
- **Default host:** `petgully-dbserver.cmzwm2y64qh8.us-east-1.rds.amazonaws.com`
- **Default DB:** `petgully_db`
- **Driver:** `pymysql` + connection pool `DBUtils.PooledDB`
  (`maxconnections=10`, `mincached=2`, `maxcached=5`, `ping=1`,
  `init_command="SET time_zone = '+05:30'"`).
- **Per-request connection** is bound to Flask `g` via `get_db()`.

> The IoT kiosk is **expected to read the same `petgully_db` database**.
> There is no separate kiosk-only schema in code.

### 2.2 Critical caveat — no DDL in repo

`init_booking_tables()` in `app.py` is intentionally hollow:

> *"All table schemas are managed via migrations / direct DB admin.
> CREATE TABLE / ALTER TABLE statements have been removed from boot."*

This means:

- The repo does **not** define `CREATE TABLE` for `bookings`, `pets`,
  `customers`, `payments`, `session_config`, `service_packages`, or
  `mg_addons`.
- The authoritative schema lives in production RDS.
- Before Phase 1 finalises the contract, we MUST run
  `SHOW CREATE TABLE bookings; SHOW CREATE TABLE pets;` (etc.) against the
  live database to capture exact column types, ENUM members, defaults,
  and any triggers/views.

### 2.3 Inferred `bookings` columns (from INSERT/SELECT in app.py)

| Column | Notes |
|--------|-------|
| `booking_code` | `VARCHAR` — unique, format `'PG' + 8 hex upper`. Acts as the QR payload. |
| `customer_id` | FK → `customers.id` |
| `pet_id` | FK → `pets.id` |
| `session_type` | `VARCHAR` — currently doubles as the **package** field. Values seen: `bath_pkg`, `complete_pkg`, `trim_pkg`, `diy_bath`, `addon_only`, `indie_special`. |
| `sval`, `cval`, `dval`, `wval`, `dryval`, `ctype` | Per-booking machine timing parameters. Today these come from hidden fields in `book_session.html` and from defaults. |
| `amount` | DECIMAL — final price. |
| `status` | `'pending' / 'confirmed' / 'completed' / 'cancelled'` (admin cancel sets `'cancelled'`). |
| `payment_status` | `'paid'` on Razorpay verify path; **omitted** by the credit-only INSERT, so falls back to whatever the DB default is (UI templates treat missing as `pending`). |
| `cancel_reason`, `cancelled_by` | Set by admin cancel. |
| `created_at`, `updated_at` | Standard timestamps. |

**Notably absent from `bookings`:**

- **`addons`** — selected add-ons are NOT written to `bookings`. They are
  preserved in `payments.notes` (JSON) for the Razorpay path only.
- A dedicated `package` field — `session_type` is overloaded as both
  "session category" and "package".

### 2.4 Inferred `pets` columns

| Column | Notes |
|--------|-------|
| `id`, `customer_id`, `name`, `breed`, `weight_kg`, `age_years`, `notes`, `photo_url`, `created_at` | Standard. |
| **`size`** | Allowed values (server-validated in `_validate_pet_size_for_breed`): **`small`, `medium_large`, `xl`, `indie`**. |
| `species` | Form collects it but **not written** by `INSERT INTO pets` — the column may not exist or is silently dropped. (Bug, see §10.) |

Pricing maps `medium_large` (and any legacy `large`) → `medium` when looking up
`package_pricing` (`book_session` ~3386–3387).

### 2.5 `session_config` table — legacy and confusing

Spotless inserts also do an `INSERT … ON DUPLICATE KEY UPDATE` against
`session_config` (`app.py` 3491–3503), where the column **`mobile_number`**
is being used to store the **booking code**. The schema is not in the repo.
This is a leftover from an older design and is misleading — anyone querying
`session_config.mobile_number` expecting a phone will get a `PG…` code instead.

### 2.6 `mg_addons` — the add-on catalogue

Shared with Mobile Grooming. Spotless filters with
`service_type IN ('both', 'spotless_only')` and reads:
`addon_code`, `addon_name`, `price`, `icon`, `description`, `applicable_packages`.

### 2.7 `customers` columns (inferred)

`id`, `email`, `password_hash`, `name`, `phone`, `is_admin`, `google_id`,
`profile_pic`, `last_login`, timestamps.

### 2.8 `payments` columns (inferred)

`id`, `customer_id`, `razorpay_order_id`, `amount`, `payment_type`
(values include `'booking'`), `reference_id` (= booking code for Spotless),
`description`, `notes` (JSON blob — contains pet/session/addons/credits
breakdown), `status` (`'created' / 'captured' / 'failed'`).

---

## 3. Spotless routes

### 3.1 Customer-facing

| Method | URL | Purpose |
|--------|-----|---------|
| `GET` | `/about-spotless` | Marketing page. |
| `GET` | `/book/<int:pet_id>` | Render booking form. |
| `POST` | `/book/<int:pet_id>` | Server handler — only for **zero-balance** (credits cover full amount) submissions. Paid path goes through Razorpay. |
| `GET` | `/booking/<code>` | Confirmation page — renders QR PNG inline. |
| `GET` | `/qr/<code>` | Public PNG QR for any code (no auth). |

### 3.2 Payment APIs

| Method | URL | Purpose |
|--------|-----|---------|
| `POST` | `/api/payment/create-order` | Server-side: recompute price, **allocate booking code**, create Razorpay order with `receipt=booking_code`, write `payments` row. |
| `POST` | `/api/payment/verify` | Verify HMAC signature, mark `payments.status='captured'`, INSERT `bookings` with `payment_status='paid'`, upsert `session_config`, debit credits, fire Pawgress activity, send confirmation email. |
| `POST` | `/api/razorpay/webhook` | `payment.captured` reconciliation backup — runs `_reconcile_payment_row`. |

### 3.3 Kiosk-facing API (already exists)

```text
GET /api/booking/<code>
```

Returns booking details for the kiosk to look up. **Today's response includes:**
`booking_code`, `customer_name`, `pet_name`, `session_type`,
`sval`, `cval`, `dval`, `wval`, `dryval`, `ctype` (and a few more).

**Today's response does NOT include:**
`pet.size`, `addons`, `payment_status`, `status`, `package` (as a separate
field), `breed`. We will need this enriched in Phase 3.

### 3.4 Admin Spotless routes

| Method | URL | Purpose |
|--------|-----|---------|
| `GET` | `/admin/panel/spotless` | Admin list of all Spotless bookings. |
| `POST` | `/api/admin/spotless-cancel` | Admin cancel a booking. |
| `POST` | `/api/admin/book-free` | Admin bypass (no payment). |
| `POST` | `/api/admin/payments/reconcile` | Admin manual reconciliation. |

There is **no machine-pairing logic, no remote control, no service-mode**
in the existing admin panel.

---

## 4. End-to-end customer journey

```
Customer logs in
  └─▶ /my-pets ──▶ pick a pet ──▶ /book/<pet_id>
        │
        │   GET renders book_session.html with:
        │     - service_packages (from DB)
        │     - package_pricing (size-based, from DB)
        │     - mg_addons filtered by service_type
        │     - hidden inputs: sval, cval, dval, wval, dryval, ctype
        │
        ▼
   Customer picks: package (radio) + add-ons (checkboxes) + date/time
        │
        ▼
   ┌────────────────────┴────────────────────┐
   │                                         │
 final_amount > 0                      final_amount <= 0
 (Razorpay path)                       (full credits / free)
   │                                         │
   ▼                                         ▼
POST /api/payment/create-order         POST /book/<pet_id> (form submit)
   │                                         │
   │ - allocates booking_code                │ - INSERT bookings
   │ - creates Razorpay order                │   (payment_status omitted!)
   │ - INSERT payments row                   │ - upsert session_config
   │                                         │ - send email
   ▼                                         │
Razorpay Checkout (browser)                  ▼
   │                                    /booking/<code>
   ▼                                         (renders QR PNG)
POST /api/payment/verify
   │
   │ - verify HMAC signature
   │ - mark payment captured
   │ - INSERT bookings (payment_status='paid')
   │ - upsert session_config
   │ - debit credits
   │ - send email
   │
   ▼
JSON returns redirect URL to /booking/<code>
   │
   ▼
/booking/<code>  →  renders QR PNG (booking_code as payload)
```

**Failover path:** if browser dies between Razorpay success and `/api/payment/verify`,
the **`payment.captured` webhook** at `/api/razorpay/webhook` runs
`_reconcile_payment_row` and creates the booking. ⚠ It uses **hardcoded
timings** `(120,120,60,60,480,100)` ignoring user form values (Section 10
gotcha #4).

---

## 5. Booking code (QR identifier)

| Property | Value |
|----------|-------|
| **Generator** | `'PG' + uuid.uuid4().hex[:8].upper()` |
| **Library** | `qrcode[pil]` |
| **QR payload** | The plain `booking_code` string. **No URL, no JSON.** |
| **When generated (paid path)** | At `/api/payment/create-order` — **before** payment completes. So a `bookings` row may not exist yet when the code is reserved in `payments`. |
| **When `bookings` row exists** | After `/api/payment/verify` (paid) or after `/book/<pet_id>` POST (zero-balance). |
| **When QR shown to user** | On `/booking/<code>` confirmation page (after the row exists). |
| **Email** | Confirmation email is sent on every successful path; HTML template at `templates/email/booking_confirmation.html`. SMS is not implemented. |

**Implication for kiosk validation:** the kiosk must guard on
`payment_status='paid'` AND `status IN ('confirmed','pending')` —
because a `PG…` code might appear in the cloud DB while payment is still
being captured.

---

## 6. Packages & add-ons (current state)

### 6.1 Package codes used as `session_type`

These are dynamic (loaded from `service_packages` table) but the codes
encountered in the code search are:

| Code (`session_type`) | UI label / meaning |
|---|---|
| `bath_pkg` | Standard assisted bath. |
| `complete_pkg` | Bath + manual trim. |
| `trim_pkg` | Trim only (manual — does this even need the machine? open question). |
| `diy_bath` | DIY bath — **currently blocked**: server flashes "DIY Bath is coming soon and cannot be booked yet." (`app.py` 3392–3394). |
| `addon_only` | Booking with only add-ons (no bath package). |
| `indie_special` | Special package shown only when `pet.size == 'indie'` or breed is Indian dog. |

### 6.2 Add-ons

- Catalogue: `mg_addons` table (`addon_code`, `addon_name`, `price`,
  `applicable_packages`, …).
- Filtered for Spotless via `service_type IN ('both', 'spotless_only')`.
- Indie pets have add-ons suppressed via `_sanitize_indie_addons`.
- **Persistence gap:** selected add-ons are written to `payments.notes` (JSON)
  only — **not to `bookings`**. So once the kiosk reads the booking, it
  cannot tell which add-ons the customer paid for.

### 6.3 Pet size values

`small`, `medium_large`, `xl`, `indie` (validated server-side).

The pricing layer collapses `medium_large` → `medium` for `package_pricing`
lookups.

---

## 7. Razorpay integration

| Item | Value |
|------|-------|
| Library | `razorpay` Python SDK. |
| Env vars | `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`. |
| Client init | `app.py` ~581–594 (lazy singleton `_razorpay_client`). |
| Checkout JS | `https://checkout.razorpay.com/v1/checkout.js` loaded in `book_session.html`. |
| Order receipt | Booking code (e.g. `PG12AB34CD`). |
| Webhook signature | HMAC verified via `RAZORPAY_WEBHOOK_SECRET` (`X-Razorpay-Signature` header). |
| Status transitions | `payments.status`: `created → captured` (verify), `created → failed` (bad signature). |

---

## 8. Existing kiosk-facing surface (already in place)

The frontend already exposes one endpoint clearly labelled "for kiosk lookup":

```text
GET /api/booking/<code>
```

But it is **incomplete** for our needs (see §3.3). Phase 3 change request will
ask for it to return: `pet.size`, `package` (= `session_type`), `addons`
(CSV or JSON), `payment_status`, `status`, `customer_name`, `pet_name`,
`breed` — plus a server-side guard that only returns "valid" bookings
(`payment_status='paid'` and `status` in {pending, confirmed} and date is
today or earlier).

---

## 9. Admin panel — what exists today

`/admin/panel/spotless` shows a table of all Spotless bookings with:

- Filter tabs by `bookings.status` (all / pending / confirmed / completed / cancelled).
- Columns: code, customer, pet (breed/size), package label (mapped from `session_type`),
  amount, payment status badge, timestamps.
- Cancel action with optional reason → `POST /api/admin/spotless-cancel`.

**Not present:** machine pairing, remote control, service-mode commands,
live config tuning. All of that is greenfield work in Phase 4.

---

## 10. Surprises & gotchas (read these carefully — they shape Phase 1)

1. **`bookings.addons` is not populated.** The UI lets the customer pick
   add-ons, the price reflects them, the Razorpay order's `notes` JSON
   includes them — but the `bookings` INSERT statement omits add-ons entirely.
   The kiosk currently has no way to know which add-ons a customer chose.
   → MUST be fixed in Phase 3 change request.

2. **Two confirmation paths with different fidelity.**
   - **Razorpay path** (`/api/payment/verify`) sets `payment_status='paid'`.
   - **Credit-only path** (`/book/<pet_id>` POST) **omits `payment_status`**,
     leaving it to DB default. We don't know that default without DDL.
   → Phase 1 contract must standardise on `payment_status='paid'` for
     all confirmed bookings.

3. **`session_config.mobile_number` holds a booking code.** Misnamed legacy
   column. Anyone reading it expecting a phone number will be confused.
   → Phase 1 should decide: keep, rename, or sunset `session_config`.

4. **Webhook fallback uses hardcoded timings** `(120,120,60,60,480,100)` and
   ignores any user-submitted form data (`app.py` ~6979–6992). If
   `/api/payment/verify` is skipped (browser dies), the booking row gets
   wrong timings.
   → After Phase 2 (kiosk derives timings from size profiles, not from booking),
     this gotcha becomes moot — the timings columns can be ignored.

5. **No DDL in repo.** Schema must be captured live with `SHOW CREATE TABLE`
   for Phase 1.

6. **Duplicate DB connection config.** Both `config.py` and
   `app.py:get_db_config()` carry defaults, including a hardcoded password
   fallback in `app.py` (~910). Risky if relied on.

7. **Email requires `MAIL_PASSWORD` at import-time** (`app.py` ~273).
   Startup will fail if SMTP env is missing.

8. **DIY (`diy_bath`) is hardwired blocked.** Server returns flash error if
   chosen. Customer-facing tile already shows "Coming soon".
   → Phase 3 change request must enable DIY.

9. **Per-booking timing fields (`sval`, `cval`, …)** are still being submitted
   from the form as hidden inputs. After Phase 2 they become irrelevant
   (kiosk derives from `(size, package)` profiles). Frontend can stop
   writing them OR keep writing for legacy compatibility — kiosk will
   ignore them either way.

10. **`pets.species` is collected but not stored.** Form has the field;
    INSERT statement omits it. Either column doesn't exist or it's silently
    dropped. Not blocking for Spotless — flagged for cleanliness.

11. **`trim_pkg` is a separate package.** Trim is purely manual — does the
    machine need to do anything for a `trim_pkg` booking? Open question for
    user (see §11).

12. **`indie_special` is its own package.** What sequence does the machine
    run for it? Same as `bath_pkg`? Open question (see §11).

13. **`addon_only` is a package.** Probably maps to our planned standalone
    `extra_dry` mode — but needs confirmation.

14. **Pawgress side effect.** `create_pawgress_activity_for_booking` fires on
    paid + admin paths. Coupling to another module — ensure it doesn't break
    if Spotless changes.

---

## 11. Open questions surfaced by Phase 0

These need user answers before Phase 1 can finalise the integration contract:

1. **`trim_pkg`** — does the machine need to run for a trim-only booking?
   (My assumption: **no** — trim is 100% manual, kiosk should refuse this
   QR or treat it as "no machine action".)

2. **`indie_special`** — what does the machine actually run for an Indie
   special booking? Same as `bath_pkg`? Or different timings/stages?

3. **`addon_only`** — is this the package we should map to "standalone
   extra_dry"? Or are there other addon-only flows?

4. **Mapping of `pets.size` to our SET A / SET B profiles:**
   | `pets.size` | Maps to |
   |---|---|
   | `small` | SET A |
   | `medium_large` | SET A |
   | `xl` | SET B |
   | `indie` | SET A (assumption — confirm) |

5. **`session_config` table** — keep, deprecate, or rename `mobile_number` →
   `booking_code`? Cleanest is to drop `session_config` writes entirely
   once the kiosk reads from `bookings`.

6. **Schema authority** — can you run `SHOW CREATE TABLE bookings; SHOW CREATE TABLE pets; SHOW CREATE TABLE mg_addons; SHOW CREATE TABLE session_config;`
   on the live RDS and paste the output? Without this we are designing
   the contract against inferred columns.

---

## 12. What this baseline gives us for Phase 1

With this snapshot we now know:

- **Cloud DB is shared** between frontend and kiosk → no API needed for
  kiosk lookups, direct SQL works (with `/api/booking/<code>` as a backup
  REST channel).
- **QR payload format is finalised**: just the `booking_code` string.
- **`session_type` column already plays the role of "package"** — we
  don't need a new column, we just need to formalise the allowed values.
- **`pets.size`** already supports `small / medium_large / xl / indie` —
  we don't need a schema migration, just a mapping rule.
- **The big gap is `addons`** — both the column and the persistence logic
  must be added in the frontend.
- **The kiosk-facing API already exists** — it just needs more fields in
  its response.

This means Phase 1's `INTEGRATION_CONTRACT.md` will be smaller than I
originally estimated — most of the data model is already there.
