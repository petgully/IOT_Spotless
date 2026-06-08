"""
=============================================================================
QR Code Validator - Project Spotless (Contract v1.1 §7)
=============================================================================
Implements the 7-gate QR validation flow specified in
docs/INTEGRATION_CONTRACT.md §7. Returns a structured `ValidationResult`
that tells the kiosk one of three actions: START, RESUME, or REFUSE.

Public entrypoints:

    validate_booking_qr(qr_code, machine_id, db, profile_overrides=None)
        -> ValidationResult  (action='start' | 'resume' | 'refuse')

    validate_test_prefix(qr_code)
        -> Optional[str]     -- service-mode test session name, or None

This module has NO dependency on Flask, SocketIO, or hardware controllers.
=============================================================================
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import db_bookings
from session_stages import build_session, is_known_session_type

logger = logging.getLogger(__name__)


# =============================================================================
# Configuration
# =============================================================================

# Booking codes from SpotlessBooking always start with this prefix.
BOOKING_PREFIX = "PG"

# Service-mode test prefix codes (machine-only, do NOT touch booking_sessions).
TEST_PREFIX_MAP: Dict[str, str] = {
    "TEST":  "quicktest",
    "DEMO":  "demo",
    "DRY":   "onlydrying",
    "WATER": "onlywater",
    "FLUSH": "onlyflush",
    "SHAMP": "onlyshampoo",
    "DIS":   "onlydisinfectant",
    "EMPTY": "empty001",
    "SMALL": "small",
    "LARGE": "large",
}

# Abandonment window in seconds (contract §9.3 — 7 days).
ABANDONMENT_WINDOW_SECONDS = 7 * 24 * 3600


# =============================================================================
# Result types
# =============================================================================

@dataclass
class ValidationResult:
    """The unified output of validate_booking_qr().

    action: one of 'start', 'resume', 'refuse'.

    On 'start' and 'resume':
        booking_code, machine_id, customer_name, pet_name, pet_size, package
        addons, machine_request, query_b (resume only)

    On 'refuse':
        refuse_code, refuse_message
    """
    action: str  # 'start' | 'resume' | 'refuse'

    # --- common (start + resume) ---
    booking_code: Optional[str] = None
    machine_id: Optional[str] = None
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    pet_name: Optional[str] = None
    pet_size: Optional[str] = None
    breed: Optional[str] = None
    package: Optional[str] = None
    addons: List[str] = field(default_factory=list)

    # Output of session_stages.build_session(); contains stages, profile, etc.
    machine_request: Optional[Dict[str, Any]] = None

    # On resume only: the Query B row that triggered the resume.
    query_b: Optional[Dict[str, Any]] = None

    # --- refuse only ---
    refuse_code: Optional[str] = None
    refuse_message: Optional[str] = None
    refuse_gate: Optional[int] = None  # which gate (1-7) failed

    @property
    def ok(self) -> bool:
        return self.action in ("start", "resume")

    def as_dict(self) -> Dict[str, Any]:
        d = {
            "action": self.action,
            "booking_code": self.booking_code,
            "machine_id": self.machine_id,
            "customer_name": self.customer_name,
            "customer_email": self.customer_email,
            "pet_name": self.pet_name,
            "pet_size": self.pet_size,
            "breed": self.breed,
            "package": self.package,
            "addons": self.addons,
            "refuse_code": self.refuse_code,
            "refuse_message": self.refuse_message,
            "refuse_gate": self.refuse_gate,
        }
        if self.machine_request:
            mr = self.machine_request
            d["machine_request"] = {
                "mode": mr.get("mode"),
                "profile": mr.get("profile"),
                "shampoo_pump": mr.get("shampoo_pump"),
                "dryer_extra_seconds": mr.get("dryer_extra_seconds"),
                "stage_count": len(mr.get("stages") or []),
            }
        if self.query_b:
            d["resume_from"] = self.query_b.get("last_stage")
            d["resume_count_cloud"] = self.query_b.get("resume_count")
        return d


# =============================================================================
# Helpers
# =============================================================================

def _refuse(code: str, message: str, gate: Optional[int] = None) -> ValidationResult:
    logger.info(f"qr_validator: REFUSE gate={gate} code={code} msg={message!r}")
    return ValidationResult(
        action="refuse",
        refuse_code=code,
        refuse_message=message,
        refuse_gate=gate,
    )


def _normalize_addons_csv(value) -> List[str]:
    """Accept None/''/'a,b'/list -> normalized lowercase list."""
    if not value:
        return []
    if isinstance(value, str):
        items = [a.strip().lower() for a in value.split(",") if a.strip()]
    else:
        items = [str(a).strip().lower() for a in value if str(a).strip()]
    seen, out = set(), []
    for a in items:
        if a not in seen:
            seen.add(a)
            out.append(a)
    return out


def _looks_like_booking_code(qr: str) -> bool:
    """Booking codes look like 'PG' followed by alphanumerics."""
    return bool(re.match(rf"^{BOOKING_PREFIX}[A-Z0-9_\-]+$", qr.upper()))


# =============================================================================
# Service-mode test prefix recognition
# =============================================================================

def validate_test_prefix(qr_code: str) -> Optional[str]:
    """Return a SESSION_STAGES key for service-mode codes, or None.

    These bypass the booking_sessions lifecycle entirely. Useful for operator
    smoke tests at the booth.
    """
    if not qr_code:
        return None
    qr = qr_code.strip().upper()

    # Longest-prefix match (so 'EMPTY' wins over a hypothetical 'EM').
    for prefix in sorted(TEST_PREFIX_MAP.keys(), key=len, reverse=True):
        if qr.startswith(prefix):
            session_type = TEST_PREFIX_MAP[prefix]
            logger.info(
                f"qr_validator: matched TEST prefix {prefix!r} -> {session_type}"
            )
            return session_type

    qr_lower = qr.lower()
    if is_known_session_type(qr_lower):
        logger.info(f"qr_validator: matched direct test session_type {qr_lower!r}")
        return qr_lower
    return None


# =============================================================================
# Main entrypoint - 7-gate booking validation
# =============================================================================

def validate_booking_qr(
    qr_code: str,
    machine_id: str,
    db,
    profile_overrides: Optional[Dict[str, Dict[str, int]]] = None,
    shampoo_plan_b: bool = False,
) -> ValidationResult:
    """Run the 7-gate validation flow on a PG-prefixed booking code.

    Args:
        qr_code:           raw scanned string.
        machine_id:        this kiosk's machine_id (e.g. "BS-HONER01").
        db:                DatabaseManager (must be connected).
        profile_overrides: optional {'A': {...}, 'B': {...}} for build_session;
                           typically obtained from ConfigManager.
        shampoo_plan_b:    TEMPORARY maintenance flag passed to build_session;
                           routes regular shampoo through the Plan B line.

    Returns:
        ValidationResult — see docstring above.
    """
    if not qr_code:
        return _refuse("empty_qr", "Empty QR code", gate=0)
    if not machine_id:
        return _refuse("no_machine_id", "Machine not configured", gate=0)
    if not db or not getattr(db, "is_connected", False):
        return _refuse(
            "db_offline",
            "Database unreachable — please ask staff for help.",
            gate=0,
        )

    booking_code = qr_code.strip()

    # ------------------------------------------------------------- Query A
    row_a = db_bookings.get_booking_query_a(db, booking_code)

    # ============ Gate 1: Row exists ============
    if row_a is None:
        return _refuse(
            "booking_not_found",
            "Booking not found. Please check your QR.",
            gate=1,
        )

    # ============ Gate 2: payment_status ============
    payment_status = row_a.get("payment_status")
    # v1.1 transitional: also accept NULL (per contract §7.3)
    if payment_status not in (None, "paid", "PAID"):
        return _refuse(
            "payment_not_confirmed",
            "Payment not confirmed for this booking.",
            gate=2,
        )

    # ============ Gate 3: bookings.status ============
    booking_status = (row_a.get("status") or "").lower()
    if booking_status not in ("confirmed", "pending"):
        if booking_status == "completed":
            msg = "This booking has already been completed."
        elif booking_status == "cancelled":
            msg = "This booking has been cancelled."
        else:
            msg = f"Booking is in an invalid state: {booking_status}"
        return _refuse("invalid_booking_status", msg, gate=3)

    # ============ Gate 4: booking_date in the past or today ============
    booking_date = row_a.get("booking_date")
    if booking_date is not None:
        # MySQL DATE -> Python date when DictCursor is used
        try:
            from datetime import date
            today = date.today()
            if hasattr(booking_date, "date"):
                bdate = booking_date.date()
            else:
                bdate = booking_date
            if bdate > today:
                return _refuse(
                    "future_booking",
                    f"Booking is scheduled for {bdate.isoformat()}. Please come back on that date.",
                    gate=4,
                )
        except Exception as e:
            logger.warning(f"qr_validator: booking_date check failed: {e}; allowing")

    # ------------------------------------------------------------- Query B
    row_b = db_bookings.get_booking_session_query_b(db, booking_code)

    # ============ Gate 5: status == 'completed' ============
    if row_b is not None:
        b_status = (row_b.get("status") or "").lower()
        if b_status == "completed":
            return _refuse(
                "already_used",
                "This QR has already been used. Please create a new booking.",
                gate=5,
            )

    # ============ Gate 6: in_progress -> machine + freshness ============
    is_resume = False
    if row_b is not None and (row_b.get("status") or "").lower() == "in_progress":
        other_machine = row_b.get("machine_id")
        age_sec = row_b.get("seconds_since_last_update") or 0

        if other_machine and other_machine != machine_id:
            return _refuse(
                "wrong_machine",
                "This booking is currently active on another machine.",
                gate=6,
            )
        if age_sec > ABANDONMENT_WINDOW_SECONDS:
            # Defensive: cron should have flipped it; do it now.
            logger.warning(
                f"qr_validator: scan-time abandonment for {booking_code} "
                f"(age={age_sec}s > {ABANDONMENT_WINDOW_SECONDS}s)"
            )
            db_bookings.update_booking_session_abort(
                db,
                booking_code=booking_code,
                machine_id=other_machine or machine_id,
                reason="abandonment-7d-scan-time",
            )
            return _refuse(
                "abandoned",
                "This booking was abandoned more than 7 days ago. "
                "Please contact support.",
                gate=6,
            )
        is_resume = True

    # ============ Gate 7: package resolution ============
    pet_size = row_a.get("pet_size")
    package  = row_a.get("package")
    addons_raw = row_a.get("addons", "")
    addons_list = _normalize_addons_csv(addons_raw)

    machine_request = build_session(
        size=pet_size,
        package=package,
        addons=addons_list,
        profile_overrides=profile_overrides,
        shampoo_plan_b=shampoo_plan_b,
    )
    if machine_request.get("refused"):
        return _refuse(
            machine_request.get("refuse_code") or "package_refused",
            machine_request.get("refuse_message") or "Package not supported on this machine.",
            gate=7,
        )

    # ------------------------------------------------------------- success
    action = "resume" if is_resume else "start"
    result = ValidationResult(
        action=action,
        booking_code=row_a.get("booking_code"),
        machine_id=machine_id,
        customer_name=row_a.get("customer_name"),
        customer_email=row_a.get("customer_email"),
        pet_name=row_a.get("pet_name"),
        pet_size=pet_size,
        breed=row_a.get("breed"),
        package=package,
        addons=addons_list,
        machine_request=machine_request,
        query_b=row_b if is_resume else None,
    )
    logger.info(
        f"qr_validator: OK {action.upper()} booking={booking_code} "
        f"profile={machine_request.get('profile')} mode={machine_request.get('mode')} "
        f"pump={machine_request.get('shampoo_pump')} "
        f"extra_dry={machine_request.get('dryer_extra_seconds')}s "
        f"pet={result.pet_name}"
    )
    return result


# =============================================================================
# Unified dispatch helper (kiosk's single entrypoint)
# =============================================================================

def validate_qr(qr_code: str, machine_id: str, db,
                profile_overrides: Optional[Dict[str, Dict[str, int]]] = None,
                shampoo_plan_b: bool = False,
                ) -> Dict[str, Any]:
    """Single entrypoint used by web_server / session_runner.

    Tries booking validation first (if looks like a booking code), then falls
    back to test-prefix matching. Returns a uniform dict so the kiosk UI can
    branch on `kind`:

        kind='booking', result=ValidationResult.as_dict()
        kind='test',    session_type=<str>
        kind='unknown', message='Invalid QR'
    """
    if not qr_code:
        return {"kind": "unknown", "message": "Empty QR code"}

    qr = qr_code.strip()

    if _looks_like_booking_code(qr):
        vr = validate_booking_qr(qr, machine_id, db, profile_overrides,
                                 shampoo_plan_b=shampoo_plan_b)
        # Stash the live ValidationResult in '_obj' so session_runner can
        # access machine_request without re-resolving.
        return {"kind": "booking", "result": vr.as_dict(), "_obj": vr}

    # Fallback: service-mode prefix codes
    test_type = validate_test_prefix(qr)
    if test_type:
        return {"kind": "test", "session_type": test_type}

    return {"kind": "unknown", "message": "Invalid QR code"}
