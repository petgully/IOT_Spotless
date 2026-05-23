# Frontend Change Request — SpotlessBooking ↔ Kiosk Integration

> **Target repo:** `Project_Spotless/SpotlessBooking`
> **Source of truth:** `docs/INTEGRATION_CONTRACT.md` v1.1
> **Status:** Ready to hand off to the frontend team.
> **Scope:** Spotless module only. Do NOT touch Mobile Grooming, Medical,
> Marketing, Pawgress, Finance, Logistics, Driver Portal, Chat, or Handbook.

This document tells the SpotlessBooking team **exactly** what to add, change,
remove, and verify so that the kiosk integration works end-to-end. Each task
is self-contained — a developer should be able to execute it without reading
the contract first (though the contract is the authority if there's ever a
disagreement).

---

## How to read this doc

Each task has:

- **WHY** — the business / kiosk reason.
- **WHAT** — what to change.
- **WHERE** — exact file + function / line range when known.
- **HOW** — copy-pasteable SQL / Python.
- **TEST** — how to verify after.

Tasks are grouped by **type** (schema, code, ops). Within a group they are
ordered so that earlier tasks don't depend on later ones.

---

## Group A — Database schema

> **Heads-up:** the `booking_sessions` table needed by the kiosk is **already
> created** in RDS by the user via MySQL Workbench. The frontend does not
> need to create it. But it MAY want to query it for the admin panel (Task G3).

### A1. Add `bookings.addons` column

**WHY:** The kiosk currently has no way to know which add-ons a customer
booked. Add-ons exist in the UI, in pricing, in Razorpay `notes`, but never
land on `bookings`. The kiosk needs to read this column to decide whether
to (a) swap the medicated shampoo pump and (b) extend dryer time.

**WHAT:** Add a single column `addons VARCHAR(255) DEFAULT ''` to the
`bookings` table.

**WHERE:** RDS `petgully_db.bookings`.

**HOW:**
```sql
ALTER TABLE bookings
ADD COLUMN addons VARCHAR(255) NOT NULL DEFAULT ''
AFTER session_type;
```

**TEST:** `DESCRIBE bookings;` should show the new column right after
`session_type`.

---

### A2. Add `extra_dry` row to `mg_addons` catalog

**WHY:** Customer needs to be able to book "+5 min dryer" as an add-on
(or standalone with `addon_only` package). The kiosk maps `addon_code =
'extra_dry'` to either +300s on dryer (when paired with a bath package)
or to dryer-only mode (when paired with `addon_only`).

**WHAT:** Insert one row into `mg_addons`.

**WHERE:** RDS `petgully_db.mg_addons`.

**HOW:**
```sql
INSERT INTO mg_addons
    (addon_code, addon_name, price, icon, description, duration_minutes,
     applicable_packages, service_type, display_order, is_active)
VALUES
    ('extra_dry', 'Extra Dry (+5 min)', 50.00, '🌬', '5 extra minutes of dryer time',
     5, 'bath_pkg,complete_pkg,addon_only', 'spotless_only', 10, 1);
```

> **Note:** price ₹50 is a suggestion — the business owner can adjust.
> The standalone (dryer-only) pricing comes from the `addon_only` package
> in `service_packages` + `package_pricing`, not from this row.

**TEST:**
```sql
SELECT * FROM mg_addons WHERE addon_code = 'extra_dry';
```

---

### A3. (Optional) Standardise `pets.size` ENUM

**WHY:** Today the ENUM is `('small','medium','large','medium_large','xl')`.
The kiosk maps all of `small`, `medium`, `medium_large`, `large` → SET A,
and `xl` → SET B. The historical sprawl (`medium` + `medium_large` + `large`
all meaning roughly the same thing) is harmless but messy.

**WHAT:** Either leave as-is (kiosk handles all five values) OR collapse to
3 values `('small','medium','xl')` and add `indie`. **No urgency.**

**Recommendation:** leave as-is for now. Tackle in a future cleanup migration.

**TEST:** N/A.

---

## Group B — Code changes in `app.py`

### B1. Populate `addons` on every Spotless `INSERT INTO bookings`

**WHY:** This is the single most important code change. Without it,
Task A1 is useless — the column exists but is always empty.

**WHERE:** All call sites that `INSERT INTO bookings`. Verified count = **4
distinct sites** (admin payments reconcile reuses `_reconcile_payment_row`,
so it is the same INSERT as the webhook fallback):

| Location | Path | Approx. line |
|---|---|---|
| Credit-only `book_session` POST | `app.py` | ~3482 |
| Admin `/api/admin/book-free` | `app.py` | ~6383 |
| Razorpay verify success | `app.py` | ~6818 |
| Razorpay webhook fallback (also used by admin reconcile) | `app.py` | ~6979 (inside `_reconcile_payment_row` starting ~6911) |

**WHAT:** In each `INSERT INTO bookings (...)` statement:

1. Add `addons` to the column list.
2. Add the value (CSV string of selected addon_codes, empty string if none).

**HOW (example for the Razorpay verify path):**

```python
# BEFORE
cursor.execute("""
    INSERT INTO bookings
        (booking_code, customer_id, pet_id, session_type,
         sval, cval, dval, wval, dryval, ctype,
         amount, status, payment_status)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'confirmed', 'paid')
""", (booking_code, customer_id, pet_id, session_type,
      sval, cval, dval, wval, dryval, ctype, amount))

# AFTER
addons_csv = ','.join(addons) if addons else ''   # `addons` already exists locally
cursor.execute("""
    INSERT INTO bookings
        (booking_code, customer_id, pet_id, session_type, addons,
         sval, cval, dval, wval, dryval, ctype,
         amount, status, payment_status)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'confirmed', 'paid')
""", (booking_code, customer_id, pet_id, session_type, addons_csv,
      sval, cval, dval, wval, dryval, ctype, amount))
```

Repeat the same pattern for every other insert site.

**Critical rule:** if the call site has no `addons` variable in scope (e.g.
the webhook fallback today), recover it from `payments.notes` JSON:

```python
notes = json.loads(payment_row['notes'] or '{}')
addons_csv = notes.get('addons', '')
```

**TEST:**
```sql
-- Book a test session with med_bath + extra_dry add-ons in the UI.
-- Then:
SELECT booking_code, session_type, addons
FROM bookings
ORDER BY id DESC LIMIT 1;
-- Expect addons = 'med_bath,extra_dry' (or similar non-empty CSV).
```

---

### B2. Standardise `payment_status='paid'` on the credit-only path

**WHY:** Today the credit-only POST path omits `payment_status`, leaving it
at the DB default (`'pending'`). The kiosk requires `payment_status='paid'`
to start a session. Customers who paid fully with credits cannot use the
kiosk.

**WHERE:** `app.py` `book_session` POST handler, line ~3481.

**HOW:**

```python
# BEFORE
cursor.execute("""
    INSERT INTO bookings
        (booking_code, customer_id, pet_id, session_type, ...,
         amount, status)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'confirmed')
""", (...))

# AFTER  (add addons per Task B1, AND set payment_status)
cursor.execute("""
    INSERT INTO bookings
        (booking_code, customer_id, pet_id, session_type, addons, ...,
         amount, status, payment_status)
    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'confirmed', 'paid')
""", (...))
```

**TEST:** book a session that's fully covered by credits; then:
```sql
SELECT payment_status FROM bookings ORDER BY id DESC LIMIT 1;
-- Expect 'paid', not 'pending'.
```

---

### B3. Enable `diy_bath` package — FOUR guard sites + UI

**WHY:** Today `diy_bath` is hardwired-blocked with a flash error
("DIY Bath is coming soon and cannot be booked yet"). The kiosk fully
supports DIY (it runs the same hardware cycle as `bath_pkg`). The only
gate is on the frontend — but the gate exists in **four** places, not one.

**WHERE:** All four guards must be removed together. Removing only one
leaves users in a half-broken state (UI accepts DIY but API rejects it).

| # | Location | Path | Approx. line |
|---|---|---|---|
| 1 | `book_session` POST handler | `app.py` | ~3392–3394 |
| 2 | `/api/admin/book-free` admin bypass | `app.py` | ~6306–6307 |
| 3 | `/api/payment/create-order` (Razorpay path) | `app.py` | ~6569–6570 |
| 4 | `/api/payment/verify` (Razorpay verify) | `app.py` | ~6706–6707 |

**HOW:** In each of the four locations, delete the `if session_type ==
'diy_bath'` block (or the equivalent guard — wording may differ
slightly between sites). Pattern at all four sites:

```python
# BEFORE
if session_type == 'diy_bath':
    flash('DIY Bath is coming soon and cannot be booked yet.', 'error')
    return redirect(url_for('book_session', pet_id=pet_id))
# (or, in API handlers: return jsonify({'error': 'diy_unavailable'}), 400)

# AFTER
# (delete the entire if block)
```

Also UI side: edit `templates/book_session.html` around the `diy_bath`
radio input (~line 51–58). Remove the `disabled` attribute and the
`pkg-disabled` CSS class, and remove the "Coming soon" badge text.

**TEST:**

1. Open the booking form → DIY tile should be selectable.
2. Book a `diy_bath` session via Razorpay path → reaches confirmation page.
3. Book a `diy_bath` session via credit-only path → reaches confirmation page.
4. Book a `diy_bath` session via admin `/book-free` → succeeds.

> **IMPORTANT:** B3 must ship in the **same release** as E1 (UI changes).
> See sequencing note in Group I.

---

### B4. Enrich `GET /api/booking/<code>` response — BREAKING CHANGE

**WHY:** This is the kiosk's REST fallback when direct DB access fails.
Today it returns `session_type` + timings + a `success: true` wrapper —
but not the fields the kiosk needs to make a session decision, and the
shape doesn't match contract v1.1.

**WHERE:** `app.py` route `api_get_booking` (~line 6137–6171).

**⚠ BREAKING CHANGE NOTICE:** The new response is **not** a strict
superset of the current response. Specifically:
- Dropped: `success: true` wrapper, all timing fields (`sval`, `cval`,
  `dval`, `wval`, `dryval`, `ctype`), and the alias `code` (the new
  payload uses `booking.booking_code`).
- Added: `booking.pet_size`, `booking.addons`, `booking.payment_status`,
  `booking.status`, `booking.breed`, and a top-level `session_state`
  object.

**Backward compatibility:**
- The kiosk is the only known consumer of this endpoint. Confirm there
  are no other consumers before deploying.
- If other consumers exist, deploy the new shape at a new path
  (`/api/v2/booking/<code>`) and leave the v1 endpoint untouched, then
  migrate consumers individually.

**HOW:** Rewrite the route to implement all **7 validation gates** from
contract §7.3. The kiosk must pass its `machine_id` as a query parameter
(`?machine_id=KIOSK-01`) so gates 5–6 (which depend on `booking_sessions`
matching) can be evaluated server-side.

```python
from datetime import date

@app.route('/api/booking/<code>')
def api_get_booking(code):
    """
    Kiosk lookup endpoint — Contract v1.1 §7.

    Query params:
      machine_id (required) — the calling kiosk's machine ID. Used to
                              evaluate gates 5–6 against booking_sessions.
    Returns:
      200 {booking: {...}, session_state: {...|null}, gate_result: "ok"|"resume"}
      403 {error: "<gate_failure_code>"}
      404 {error: "booking_not_found"}
      400 {error: "machine_id_required"}
    """
    machine_id = request.args.get('machine_id', '').strip()
    if not machine_id:
        return jsonify({'error': 'machine_id_required'}), 400

    try:
        with get_db().cursor() as c:
            # --- Query A: booking + pet + customer (contract §7.1) ---
            c.execute("""
                SELECT
                    b.booking_code,
                    b.session_type AS package,
                    COALESCE(b.addons, '') AS addons,
                    b.status,
                    b.payment_status,
                    b.booking_date,
                    b.created_at,
                    p.size AS pet_size,
                    p.name AS pet_name,
                    p.breed,
                    c.name AS customer_name,
                    c.email AS customer_email
                FROM bookings b
                JOIN pets p ON b.pet_id = p.id
                JOIN customers c ON b.customer_id = c.id
                WHERE b.booking_code = %s
                LIMIT 1
            """, (code,))
            booking = c.fetchone()

            # --- Gate 1: booking exists ---
            if not booking:
                return jsonify({'error': 'booking_not_found'}), 404

            # --- Gate 2: paid (transitional NULL allowed) ---
            if booking['payment_status'] not in ('paid', None):
                return jsonify({'error': 'payment_not_confirmed'}), 403

            # --- Gate 3: booking status acceptable ---
            if booking['status'] not in ('confirmed', 'pending'):
                return jsonify({'error': f"booking_{booking['status']}"}), 403

            # --- Gate 4: not future-dated ---
            if booking['booking_date'] and booking['booking_date'] > date.today():
                return jsonify({'error': 'booking_in_future'}), 403

            # --- Query B: session-state (contract §7.2) ---
            c.execute("""
                SELECT machine_id, status, completed_stages, last_stage,
                       resume_count, started_at, completed_at, updated_at,
                       TIMESTAMPDIFF(SECOND, updated_at, NOW()) AS seconds_since_last_update
                FROM booking_sessions
                WHERE booking_code = %s
                ORDER BY id DESC
                LIMIT 1
            """, (code,))
            ss = c.fetchone()

            gate_result = 'ok'  # default: fresh session

            if ss:
                # --- Gate 5: already completed ---
                if ss['status'] == 'completed':
                    return jsonify({'error': 'booking_already_used'}), 403

                # --- Gate 6: machine binding + 7-day window ---
                if ss['status'] == 'in_progress':
                    if ss['machine_id'] != machine_id:
                        return jsonify({'error': 'booking_active_on_other_machine'}), 403
                    if ss['seconds_since_last_update'] > 7 * 24 * 3600:
                        return jsonify({'error': 'booking_abandoned'}), 403
                    gate_result = 'resume'

            # --- Gate 7: package resolution (Contract §5.1) ---
            pkg = booking['package']
            addons = [a for a in booking['addons'].split(',') if a]
            if pkg == 'trim_pkg':
                return jsonify({'error': 'machine_does_not_serve_trim'}), 403
            if pkg == 'addon_only' and 'extra_dry' not in addons:
                return jsonify({'error': 'no_machine_addons_selected'}), 403
            if pkg not in ('bath_pkg', 'complete_pkg', 'diy_bath',
                           'indie_special', 'addon_only'):
                return jsonify({'error': 'unknown_package'}), 403

            return jsonify({
                'booking': booking,
                'session_state': ss,         # may be None
                'gate_result': gate_result,  # 'ok' = fresh, 'resume' = continue existing
            })
    except Exception as e:
        logger.error(f"api_get_booking failed: {e}")
        return jsonify({'error': 'internal_error'}), 500
```

> **Do NOT** include timing fields (`sval`, `cval`, …) — kiosk-ignored.
> **Do NOT** add an admin / write endpoint here — read-only.

**Auth (deferred):** Phase 4 will add API key auth. For now, the endpoint
is public-readable on the assumption the booking_code itself is unguessable.

**TEST:**
```bash
# Fresh booking — expect 200 + gate_result=ok
curl "https://<host>/api/booking/PGD9F04A1C?machine_id=KIOSK-01" | jq

# Same code, second machine — expect 403 booking_active_on_other_machine
curl "https://<host>/api/booking/PGD9F04A1C?machine_id=KIOSK-02" | jq

# Trim-only booking — expect 403 machine_does_not_serve_trim
curl "https://<host>/api/booking/<trim_only_code>?machine_id=KIOSK-01" | jq

# Missing machine_id — expect 400
curl "https://<host>/api/booking/PGD9F04A1C" | jq
```

---

### B5. (Cleanup, optional) Stop writing `session_config`

**WHY:** The `session_config` table is now legacy. The kiosk no longer reads
from it. Continuing to write to it is harmless but wastes I/O and creates
confusion (`mobile_number` column holds booking codes).

**WHERE:** `app.py` `book_session` ~3491–3503 and Razorpay verify path.

**HOW:** Remove the `INSERT … ON DUPLICATE KEY UPDATE` block targeting
`session_config`.

**TEST:** book a session; verify `session_config` has no new row for the
new booking_code. If admin reports rely on `session_config`, defer this
task.

---

### B6. (Cleanup, optional) Drop unused `pets.species` form field

**WHY:** Form collects `species` but `INSERT INTO pets` omits it. Either
add the column + persist, or remove the field from the form. Not
kiosk-blocking, but a clean-up.

**WHERE:** `templates/add_pet.html` + `app.py` `add_pet` handler.

**TEST:** N/A.

---

## Group C — Webhook fallback fix

### C1. Fix webhook fallback hardcoded timings + missing addons

**WHY:** If the browser dies between Razorpay success and
`/api/payment/verify`, the `payment.captured` webhook creates a booking
with hardcoded timings `(120,120,60,60,480,100)` and **no addons**. After
the kiosk refactor, timings are ignored — but missing addons will silently
deprive the customer of medicated shampoo / extra dry that they paid for.

**WHERE:** `app.py` `_reconcile_payment_row` (~6970–6995).

**HOW:** Pull addons + session_type from `payments.notes` JSON, which
already contains them:

```python
notes = json.loads(payment_row['notes'] or '{}')
# Default to 'bath_pkg' (not 'bath') — must match service_packages.code values.
session_type_from_notes = (notes.get('session_type') or 'bath_pkg').strip()
addons_csv = notes.get('addons', '') or ''

cursor.execute("""
    INSERT INTO bookings
        (booking_code, customer_id, pet_id, session_type, addons,
         amount, status, payment_status)
    VALUES (%s, %s, %s, %s, %s, %s, 'confirmed', 'paid')
""", (booking_code, customer_id, pet_id, session_type_from_notes,
      addons_csv, amount))
```

(Drop the hardcoded timing columns entirely — kiosk doesn't read them.
Also: today's code at ~6968 defaults to `'bath'` which is NOT a valid
package code — that's a pre-existing latent bug fixed here.)

**TEST:** simulate a Razorpay webhook payload via curl or the Razorpay
test console; verify the resulting `bookings` row has the correct
`session_type` and `addons`.

---

## Group D — `service_packages` catalog gaps

### D1. Decide on `addon_only` package

**WHY:** Today `addon_only` is referenced in booking code but does not
exist in `service_packages`. If a customer ever tries to book it, the
join with `package_pricing` fails silently.

**WHAT:** Either:

- **(a)** Add a `service_packages` row + `package_pricing` rows for `addon_only`. This is needed for the standalone Extra Dry product.
- **(b)** Document a UI-only special branch (not recommended — fragile).

**HOW (option a):**

```sql
INSERT INTO service_packages
    (code, name, description, includes, icon, display_order, is_active)
VALUES
    ('addon_only', 'Add-ons Only', 'Service that runs only the selected add-ons (e.g. Extra Dry)',
     'Add-ons', '➕', 5, 1);

-- Then add pricing per size (example numbers — set by business)
INSERT INTO package_pricing
    (service_id, size, price, currency, is_active, effective_from)
VALUES
    ( (SELECT id FROM service_packages WHERE code='addon_only'), 'small',  299, 'INR', 1, CURDATE()),
    ( (SELECT id FROM service_packages WHERE code='addon_only'), 'medium', 299, 'INR', 1, CURDATE()),
    ( (SELECT id FROM service_packages WHERE code='addon_only'), 'large',  299, 'INR', 1, CURDATE()),
    ( (SELECT id FROM service_packages WHERE code='addon_only'), 'xl',     349, 'INR', 1, CURDATE());
```

**TEST:** book an `addon_only` + `extra_dry` combo in the UI; verify the
booking lands in `bookings` with `session_type='addon_only'` and
`addons='extra_dry'`.

---

### D2. Decide on `indie_special` package

**WHY:** Same problem as D1 — referenced in code, missing from catalog.

**WHAT:** Either add to `service_packages` (recommended), or remove the
references in code.

**HOW (option a, same pattern as D1):**

```sql
INSERT INTO service_packages
    (code, name, description, includes, icon, display_order, is_active)
VALUES
    ('indie_special', 'Indie Special', 'Special bath package for Indian dog breeds',
     'Bath,Ear Cleaning,Nail Clipping', '🐕', 6, 1);

INSERT INTO package_pricing
    (service_id, size, price, currency, is_active, effective_from)
VALUES
    ( (SELECT id FROM service_packages WHERE code='indie_special'), 'small',  599, 'INR', 1, CURDATE()),
    ( (SELECT id FROM service_packages WHERE code='indie_special'), 'medium', 599, 'INR', 1, CURDATE()),
    ( (SELECT id FROM service_packages WHERE code='indie_special'), 'large',  599, 'INR', 1, CURDATE()),
    ( (SELECT id FROM service_packages WHERE code='indie_special'), 'xl',     599, 'INR', 1, CURDATE());
```

(Pricing is at owner's discretion; kiosk forces SET A profile regardless of size.)

**TEST:** book an `indie_special` session for an Indian-dog-breed pet; verify
the `bookings` row.

---

## Group E — UI changes in templates

### E1. Update `book_session.html` to show DIY and Extra Dry properly

**WHY:** Enabling DIY (B3) requires removing the "Coming soon" badge on the
DIY tile. Extra Dry as an add-on needs to appear in the checkbox list.

**WHERE:** `templates/book_session.html`.

**HOW:**

1. Remove `disabled` attribute (and "Coming soon" badge) from the
   `diy_bath` radio.
2. The Extra Dry checkbox will appear automatically once Task A2 runs
   (it's loaded dynamically from `mg_addons`).

**TEST:** open the booking form; DIY tile should be selectable, Extra Dry
checkbox should appear in the add-ons section.

---

### E2. Booking confirmation: show add-ons to the customer

**WHY:** Today `booking_confirmation.html` shows the package name but not
which add-ons were selected. After A1+B1, the data is in the DB but the
route doesn't pass it to the template.

**WHERE:** **TWO** changes:

1. `app.py` — function `booking_confirmation` (~line 3640–3700). Must
   resolve add-on codes to display names and pass them in template context.
2. `templates/booking_confirmation.html` — render the new list.

**HOW (Python side):** mirror the pattern from F1 — fetch `addon_codes`
from `booking['addons']`, look them up in `mg_addons`, pass
`addon_display` into `render_template(...)`.

**HOW (template side):** add the same conditional block as F1's template
snippet under the package name.

**TEST:** book a session with two add-ons; the confirmation page should
list both.

---

## Group F — Email

### F1. Include add-ons in booking confirmation email

**WHY:** Same reason as E2 — the customer should see what they paid for.

**WHERE:** **TWO** changes (not just template):

1. `app.py` — function `send_booking_confirmation_email` (~line 360–415).
   Today this function does **not** pass `addons` into the template
   context. Must be updated.
2. `templates/email/booking_confirmation.html` — render the add-ons.

**HOW (Python side):**

```python
# In send_booking_confirmation_email(), after fetching booking details:
addons_csv = (booking.get('addons') or '').strip()
addon_codes = [a for a in addons_csv.split(',') if a]

# Look up display names from mg_addons:
addon_display = []
if addon_codes:
    with get_db().cursor() as c:
        placeholders = ','.join(['%s'] * len(addon_codes))
        c.execute(
            f"SELECT addon_code, addon_name FROM mg_addons "
            f"WHERE addon_code IN ({placeholders})",
            addon_codes,
        )
        name_map = {r['addon_code']: r['addon_name'] for r in c.fetchall()}
    addon_display = [name_map.get(code, code) for code in addon_codes]

# Pass into the template render call:
html_body = render_template(
    'email/booking_confirmation.html',
    booking=booking,
    customer=customer,
    addon_display=addon_display,   # NEW
    # ... existing context ...
)
```

**HOW (template side):** in `templates/email/booking_confirmation.html`,
add a conditional block where add-ons should appear:

```html
{% if addon_display %}
  <p><strong>Add-ons:</strong></p>
  <ul>
    {% for name in addon_display %}<li>{{ name }}</li>{% endfor %}
  </ul>
{% endif %}
```

**TEST:** book a session with two add-ons → check confirmation email for
the rendered add-on list.

---

## Group G — Admin panel changes

### G1. Surface `booking_sessions.status` on `/admin/panel/spotless`

**WHY:** Today the admin sees `bookings.status` (confirmed / cancelled /
completed). With the new model, the more relevant state is
`booking_sessions.status` (in_progress / completed / aborted / abandoned).

**WHERE:** `app.py` `admin_panel_spotless` (~line 4657) + template
`templates/admin/panel_spotless.html`.

**HOW:** Update the SELECT to LEFT JOIN `booking_sessions`:

```python
cursor.execute("""
    SELECT b.*, c.name as customer_name, c.email as customer_email,
           p.name as pet_name, p.breed as pet_breed, p.size as pet_size,
           bs.status AS session_status, bs.machine_id,
           bs.completed_stages, bs.last_stage, bs.resume_count,
           bs.started_at AS session_started_at,
           bs.completed_at AS session_completed_at,
           bs.abort_reason
    FROM bookings b
    JOIN customers c ON b.customer_id = c.id
    JOIN pets p ON b.pet_id = p.id
    LEFT JOIN (
        SELECT bs1.*
        FROM booking_sessions bs1
        INNER JOIN (
            SELECT booking_code, MAX(id) AS max_id
            FROM booking_sessions
            GROUP BY booking_code
        ) latest ON bs1.id = latest.max_id
    ) bs ON bs.booking_code = b.booking_code
    ORDER BY b.created_at DESC
""")
```

Then add the new columns to the template table.

**TEST:** load `/admin/panel/spotless`; expect new columns to render with
data from the last test booking that ran on the kiosk.

---

### G2. (Phase 4 — not now) Admin abort + refund-token actions

**WHY:** Per contract §13, the admin should be able to abort a stuck
`in_progress` session and issue a refund token. This is **not part of
this change request** — it belongs to the Phase 4 admin module spec.

This task is listed here only to flag that the admin panel should leave
space in its UI for these actions.

---

### G3. (Optional analytics) Add `booking_sessions` summary tile

**WHY:** Nice-to-have for admin dashboard. Surface counts of each
`booking_sessions.status` over a time window.

**WHERE:** `app.py` admin dashboard handler.

**HOW:**

```sql
SELECT status, COUNT(*) AS c
FROM booking_sessions
WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
GROUP BY status;
```

**TEST:** view admin dashboard; tile should render.

---

## Group H — Ops / cron jobs

### H1. Daily abandonment sweep

**WHY:** Per contract §13.3 — `in_progress` rows that haven't been touched
in 7 days should auto-transition to `abandoned`.

**WHERE:** existing cron mechanism in the SpotlessBooking deployment
(check `Procfile`, `render.yaml`, or whichever scheduler is in use).

**HOW:** New Python script `scripts/abandon_stale_sessions.py`:

```python
"""Run daily. Marks in_progress booking_sessions older than 7 days as abandoned."""
import pymysql
from config import get_config
cfg = get_config()
conn = pymysql.connect(host=cfg.DB_HOST, port=cfg.DB_PORT, user=cfg.DB_USER,
                       password=cfg.DB_PASSWORD, database=cfg.DB_NAME)
with conn.cursor() as c:
    c.execute("""
        UPDATE booking_sessions
        SET    status       = 'abandoned',
               abort_reason = 'auto_abandoned_7d'
        WHERE  status       = 'in_progress'
          AND  updated_at < DATE_SUB(NOW(), INTERVAL 7 DAY);
    """)
    n = c.rowcount
    conn.commit()
print(f"Marked {n} sessions as abandoned")
```

Schedule it daily at 03:00 IST (low-traffic).

**TEST:** insert a fake `in_progress` row with `updated_at = NOW() - INTERVAL 8 DAY`,
run the script, verify status flipped to `abandoned`.

---

## Group I — Verification checklist

Run these at the end, in order. Each must pass before declaring the change
request complete.

| # | Check | How |
|---|---|---|
| I1 | `bookings.addons` column exists | `DESCRIBE bookings` shows the column |
| I2 | `extra_dry` exists in `mg_addons` | `SELECT * FROM mg_addons WHERE addon_code='extra_dry';` returns 1 row |
| I3 | New booking writes `addons` correctly | Book in UI with 2 add-ons → `SELECT addons FROM bookings ORDER BY id DESC LIMIT 1;` shows CSV |
| I4 | Credit-only path writes `payment_status='paid'` | Book with full credits → `SELECT payment_status FROM bookings ORDER BY id DESC LIMIT 1;` shows `paid` |
| I5 | DIY booking succeeds | Book `diy_bath` in UI → reaches confirmation page without error |
| I6 | `/api/booking/<code>` returns full v1.1 payload | `curl /api/booking/<test_code> \| jq .booking.pet_size, .booking.addons, .session_state` |
| I7 | `/api/booking/<code>` rejects invalid bookings | Try a cancelled / unpaid / future-dated code → expect 403 / 404 |
| I8 | Webhook fallback writes correct `addons` | Simulate `payment.captured` webhook → verify booking row has addons |
| I9 | Admin panel shows session_status column | Load `/admin/panel/spotless` → new column visible |
| I10 | Abandonment cron works | Run `scripts/abandon_stale_sessions.py` against a stale test row → flips to `abandoned` |
| I11 | Kiosk end-to-end smoke | Book → pay → walk to kiosk → scan QR → full session runs → `booking_sessions.status` becomes `completed`, `bookings.status` becomes `completed` |
| I12 | Kiosk power-loss resume | Book → start session → kill kiosk power mid-dryer → restart → rescan → dryer resumes from saved checkpoint, not from 0 |
| I13 | Anti-fraud: cycle attack | Book → start dryer → wait until almost-done → cut power → restart → rescan → dryer runs only remaining seconds, refuses repeat |

---

## What this change request does NOT cover

The following are NOT in scope for this doc. They will be specified separately:

- **Admin module for machine pairing + service-mode controls** → future
  `ADMIN_MODULE_SPEC.md` (Phase 4).
- **Audit log table for admin overrides** → ships with Phase 4.
- **Sunset of `bookings.sval / cval / dval / wval / dryval / fval / wt /
  ctype` columns** → defer to a cleanup migration once kiosk is fully on
  the new model.
- **Per-stage telemetry / energy / water consumption** → future analytics
  work.

---

## Sequencing recommendation

If the frontend team wants to ship incrementally:

| Sprint | Tasks | Outcome |
|---|---|---|
| Sprint 1 | A1, A2, B1, B2, B4, C1 | Kiosk can read bookings end-to-end with real add-ons. (UI unchanged — DIY still blocked until Sprint 2.) |
| Sprint 2 | **B3 + E1 (must ship together)**, D1, D2, E2, F1 | All packages bookable + customer-facing UX consistent. |
| Sprint 3 | G1, G3, H1 | Admin observability + auto-cleanup. |
| Sprint 4 (deferred) | B5, B6, sunsets | Cleanup. |

**Critical sequencing rule:** B3 (server enable DIY at four guards) and
E1 (UI enable DIY tile) MUST ship in the **same release**. Shipping E1
alone makes the UI offer a tile that POST handlers reject — confusing
half-broken state. Shipping B3 alone is fine (UI hides the tile until
E1 ships).

Sprint 1 alone is enough to **unblock kiosk Phase 2 testing**: the
kiosk only needs `bookings.addons` populated and a valid
`/api/booking/<code>` response. DIY can stay disabled until Sprint 2.

---

## Rollback plan

For each task group, here is how to roll back if a problem appears in
production:

| Group | Forward action | Rollback action |
|---|---|---|
| A1 (column) | `ALTER TABLE bookings ADD COLUMN addons ...` | `ALTER TABLE bookings DROP COLUMN addons;` (no data loss — column is purely additive; ensure no reads outside the new code depend on it before dropping) |
| A2 (extra_dry row) | INSERT row | `DELETE FROM mg_addons WHERE addon_code='extra_dry';` |
| B1, B2, C1 (INSERT changes) | Deploy new code | Revert to prior commit; existing rows already written are valid (they just have empty `addons` and explicit `payment_status='paid'`) |
| B3 (DIY guards) | Remove 4 guards + UI changes | Revert commit; any DIY bookings created during the window remain valid (they ran the same hardware as `bath_pkg`) |
| B4 (API rewrite) | Deploy new endpoint | If kiosk fails, deploy a **shim**: keep the new `/api/booking/<code>` but also restore the old `/api/booking/<code>?legacy=1` returning the v1 shape. Then revert kiosk consumer separately. |
| D1, D2 (catalog rows) | INSERT rows | `DELETE FROM service_packages WHERE code IN ('addon_only','indie_special');` (and dependent `package_pricing` rows) |
| G1 (admin panel) | Add JOIN + columns | Revert commit |
| H1 (cron) | Add cron job | Disable cron job; existing `abandoned` rows are forensically correct anyway |

**Feature-flag option:** B4 is the highest-risk task. Consider
gating the new response shape behind an env var `API_V2_ENABLED=true`
so it can be toggled off without a deploy.

---

## Out of scope (explicit)

These items are referenced in `INTEGRATION_CONTRACT.md` v1.1 §11.10
("Frontend MUST" item 10) but are **deferred to Phase 4** (admin module
spec):

- Admin "abort stuck in_progress session" action button.
- Admin "issue refund token for aborted session" action.
- Audit table `booking_sessions_audit` for admin writes.

This deferral is acknowledged by the contract's §16 ("Open items
deferred to later phases"). Phase 2 kiosk work does NOT depend on these
— the manual SQL playbook in contract §13 covers operations until the
admin module ships.

---

**Questions on any task → reference `docs/INTEGRATION_CONTRACT.md` v1.1
for the authoritative semantics.**
