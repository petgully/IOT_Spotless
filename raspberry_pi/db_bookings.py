"""
=============================================================================
Database - Booking + booking_sessions Queries (Contract v1.1 §7, §8)
=============================================================================
All RDS reads/writes for the booking lifecycle. The kiosk MAY read from
`bookings`, `pets`, `customers`, `mg_addons`, `booking_sessions` and MAY
write to `bookings.status` and `booking_sessions.*`. Everything else is
read-only from the kiosk's perspective.

Public functions:

  Reads (called by qr_validator):
    get_booking_query_a(db, booking_code)        # §7.1
    get_booking_session_query_b(db, booking_code) # §7.2

  Writes (called by session_runner via cloud_sync):
    insert_booking_session_start(db, payload)    # §8.1
    update_bookings_status(db, booking_code, status)
    update_booking_session_resume(db, payload)   # §8.2
    update_booking_session_stage(db, payload)    # §8.3
    update_booking_session_complete(db, payload) # §8.4
    update_booking_session_abort(db, payload)    # §8.6

  Dispatch:
    apply_cloud_op(db, op_name, payload)         # used by cloud_sync executor
=============================================================================
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# =============================================================================
# Helper
# =============================================================================

def _ensure_connection(db) -> bool:
    """Best-effort ensure the DB connection is live. Returns True if ready."""
    if db is None:
        return False
    if hasattr(db, "_ensure_connection"):
        return bool(db._ensure_connection())
    return bool(getattr(db, "is_connected", False))


# =============================================================================
# READS - Query A (§7.1)
# =============================================================================

def get_booking_query_a(db, booking_code: str) -> Optional[Dict]:
    """Contract §7.1 — fetch booking + pet + customer in one row.

    Returns dict with the columns listed below, or None if no row.

    Columns:
        booking_code, package, addons, status, payment_status,
        booking_date, created_at, pet_size, pet_name, breed,
        customer_name, customer_email
    """
    if not _ensure_connection(db):
        logger.error("get_booking_query_a: db not connected")
        return None
    try:
        with db._connection.cursor() as cur:
            cur.execute(
                """
                SELECT
                    b.booking_code,
                    b.session_type            AS package,
                    COALESCE(b.addons, '')    AS addons,
                    b.status,
                    b.payment_status,
                    b.booking_date,
                    b.created_at,
                    p.size                    AS pet_size,
                    p.name                    AS pet_name,
                    p.breed,
                    c.name                    AS customer_name,
                    c.email                   AS customer_email
                FROM bookings b
                JOIN pets p      ON b.pet_id      = p.id
                JOIN customers c ON b.customer_id = c.id
                WHERE b.booking_code = %s
                LIMIT 1
                """,
                (booking_code,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"get_booking_query_a({booking_code!r}) error: {e}")
        return None


# =============================================================================
# READS - Query B (§7.2)
# =============================================================================

def get_booking_session_query_b(db, booking_code: str) -> Optional[Dict]:
    """Contract §7.2 — most recent booking_sessions row, or None if no row."""
    if not _ensure_connection(db):
        logger.error("get_booking_session_query_b: db not connected")
        return None
    try:
        with db._connection.cursor() as cur:
            cur.execute(
                """
                SELECT
                    id,
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
                LIMIT 1
                """,
                (booking_code,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"get_booking_session_query_b({booking_code!r}) error: {e}")
        return None


# =============================================================================
# WRITES - §8.1 fresh session start
# =============================================================================

def insert_booking_session_start(db, *, booking_code: str, machine_id: str,
                                  last_stage: str) -> bool:
    """Insert or reset the booking_sessions row for a fresh session start.

    Per contract §8.1, on duplicate `(booking_code, machine_id)` we RESET
    `completed_stages = ''` and `resume_count = 0` to wipe any stale
    state from a prior aborted/abandoned attempt.

    Also flips `bookings.status` to 'confirmed' (skipping cancelled rows).
    """
    if not _ensure_connection(db):
        return False
    try:
        with db._connection.cursor() as cur:
            cur.execute(
                """
                INSERT INTO booking_sessions
                    (booking_code, machine_id, started_at, status,
                     last_stage, completed_stages)
                VALUES (%s, %s, NOW(), 'in_progress', %s, '')
                ON DUPLICATE KEY UPDATE
                    started_at       = NOW(),
                    status           = 'in_progress',
                    last_stage       = VALUES(last_stage),
                    completed_stages = '',
                    resume_count     = 0,
                    completed_at     = NULL,
                    abort_reason     = NULL
                """,
                (booking_code, machine_id, last_stage),
            )
            cur.execute(
                """
                UPDATE bookings
                SET    status     = 'confirmed',
                       updated_at = NOW()
                WHERE  booking_code = %s
                   AND status     != 'cancelled'
                """,
                (booking_code,),
            )
        db._connection.commit()
        logger.info(
            f"booking_sessions: started booking={booking_code} machine={machine_id}"
        )
        return True
    except Exception as e:
        logger.error(
            f"insert_booking_session_start({booking_code!r}, {machine_id!r}) error: {e}"
        )
        try:
            db._connection.rollback()
        except Exception:
            pass
        return False


# =============================================================================
# WRITES - §8.2 resume
# =============================================================================

def update_booking_session_resume(db, *, booking_code: str, machine_id: str,
                                   last_stage: str) -> bool:
    """Bump resume_count and refresh updated_at on a matching in_progress row."""
    if not _ensure_connection(db):
        return False
    try:
        with db._connection.cursor() as cur:
            cur.execute(
                """
                UPDATE booking_sessions
                SET    resume_count = resume_count + 1,
                       last_stage   = %s,
                       updated_at   = NOW()
                WHERE  booking_code = %s
                   AND machine_id   = %s
                   AND status       = 'in_progress'
                """,
                (last_stage, booking_code, machine_id),
            )
            affected = cur.rowcount
        db._connection.commit()
        if affected == 0:
            logger.warning(
                f"booking_sessions: resume update affected 0 rows for "
                f"booking={booking_code} machine={machine_id}"
            )
        else:
            logger.info(
                f"booking_sessions: resumed booking={booking_code} stage={last_stage}"
            )
        return True
    except Exception as e:
        logger.error(
            f"update_booking_session_resume({booking_code!r}) error: {e}"
        )
        return False


# =============================================================================
# WRITES - §8.3 per-stage progress (deduplicating CSV append)
# =============================================================================

def update_booking_session_stage(db, *, booking_code: str, machine_id: str,
                                  stage_name: str) -> bool:
    """Append `stage_name` to completed_stages (idempotent via FIND_IN_SET)."""
    if not _ensure_connection(db):
        return False
    try:
        with db._connection.cursor() as cur:
            cur.execute(
                """
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
                """,
                (stage_name, stage_name, stage_name, stage_name,
                 booking_code, machine_id),
            )
        db._connection.commit()
        logger.debug(
            f"booking_sessions: appended stage={stage_name} "
            f"booking={booking_code}"
        )
        return True
    except Exception as e:
        logger.error(
            f"update_booking_session_stage({booking_code!r}, {stage_name!r}) error: {e}"
        )
        return False


# =============================================================================
# WRITES - §8.4 completion
# =============================================================================

def update_booking_session_complete(db, *, booking_code: str,
                                     machine_id: str) -> bool:
    """Mark the booking_sessions row as completed AND bookings.status='completed'."""
    if not _ensure_connection(db):
        return False
    try:
        with db._connection.cursor() as cur:
            cur.execute(
                """
                UPDATE booking_sessions
                SET    status       = 'completed',
                       completed_at = NOW(),
                       last_stage   = 'complete',
                       updated_at   = NOW()
                WHERE  booking_code = %s
                   AND machine_id   = %s
                """,
                (booking_code, machine_id),
            )
            cur.execute(
                """
                UPDATE bookings
                SET    status     = 'completed',
                       updated_at = NOW()
                WHERE  booking_code = %s
                """,
                (booking_code,),
            )
        db._connection.commit()
        logger.info(
            f"booking_sessions: completed booking={booking_code} machine={machine_id}"
        )
        return True
    except Exception as e:
        logger.error(
            f"update_booking_session_complete({booking_code!r}) error: {e}"
        )
        return False


# =============================================================================
# WRITES - §8.6 abort
# =============================================================================

def update_booking_session_abort(db, *, booking_code: str, machine_id: str,
                                  reason: str) -> bool:
    """Mark a session aborted. Does NOT touch bookings.status (contract §8.6)."""
    if not _ensure_connection(db):
        return False
    try:
        with db._connection.cursor() as cur:
            cur.execute(
                """
                UPDATE booking_sessions
                SET    status       = 'aborted',
                       abort_reason = %s,
                       completed_at = NOW(),
                       updated_at   = NOW()
                WHERE  booking_code = %s
                   AND machine_id   = %s
                """,
                (reason, booking_code, machine_id),
            )
        db._connection.commit()
        logger.info(
            f"booking_sessions: aborted booking={booking_code} reason={reason!r}"
        )
        return True
    except Exception as e:
        logger.error(
            f"update_booking_session_abort({booking_code!r}) error: {e}"
        )
        return False


# =============================================================================
# Legacy compatibility (old call sites)
# =============================================================================

def get_booking_by_code(db, booking_code: str) -> Optional[Dict]:
    """DEPRECATED — use get_booking_query_a(). Kept as thin alias."""
    return get_booking_query_a(db, booking_code)


def update_booking_status(db, booking_code: str, status: str) -> bool:
    """Generic bookings.status update. Most callers should use the session-aware
    helpers above (which also update booking_sessions).
    """
    if not _ensure_connection(db):
        return False
    try:
        with db._connection.cursor() as cur:
            cur.execute(
                "UPDATE bookings SET status = %s, updated_at = NOW() "
                "WHERE booking_code = %s",
                (status, booking_code),
            )
        db._connection.commit()
        logger.info(f"bookings.status: {booking_code} -> {status}")
        return True
    except Exception as e:
        logger.error(f"update_booking_status({booking_code!r}) error: {e}")
        return False


# =============================================================================
# CloudSync executor adapter
# =============================================================================
# This is the function registered with CloudSyncQueue(executor=...).
# It must RAISE on failure so the queue can retry.

class CloudWriteFailed(Exception):
    """Raised when a cloud_sync op did not succeed (queue should retry)."""


def apply_cloud_op(db, op_name: str, payload: Dict[str, Any]) -> None:
    """Dispatch a cloud_sync op to the right writer. Raises on failure."""
    ok = False
    if op_name == "session_start":
        ok = insert_booking_session_start(
            db,
            booking_code=payload["booking_code"],
            machine_id=payload["machine_id"],
            last_stage=payload.get("last_stage", ""),
        )
    elif op_name == "session_resume":
        ok = update_booking_session_resume(
            db,
            booking_code=payload["booking_code"],
            machine_id=payload["machine_id"],
            last_stage=payload.get("last_stage", ""),
        )
    elif op_name == "stage_complete":
        ok = update_booking_session_stage(
            db,
            booking_code=payload["booking_code"],
            machine_id=payload["machine_id"],
            stage_name=payload["stage_name"],
        )
    elif op_name == "session_complete":
        ok = update_booking_session_complete(
            db,
            booking_code=payload["booking_code"],
            machine_id=payload["machine_id"],
        )
    elif op_name == "session_abort":
        ok = update_booking_session_abort(
            db,
            booking_code=payload["booking_code"],
            machine_id=payload["machine_id"],
            reason=payload.get("reason", "unknown"),
        )
    else:
        raise CloudWriteFailed(f"unknown cloud op: {op_name!r}")

    if not ok:
        raise CloudWriteFailed(f"cloud op {op_name} returned False")
