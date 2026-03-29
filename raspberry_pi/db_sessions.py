"""
=============================================================================
Database - Session Logging Queries - Project Spotless
=============================================================================
All session log and stage log database operations.

Tracks the full lifecycle:
    activated -> started -> in_progress -> completed / error / stopped

Also tracks individual stages (shampoo, water, dryer, etc.) and
granular events for debugging.

Depends on: db_manager.DatabaseManager for the connection.
=============================================================================
"""

import json
import logging
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)


# =========================================================================
# Session Lifecycle
# =========================================================================

def log_session_activated(db, mobile_number: str, machine_id: str,
                          session_type: str, qr_code: str,
                          params: Dict = None) -> Optional[int]:
    """Log when a session QR is scanned. Returns the session_logs row ID."""
    if not db or not db._ensure_connection():
        return None

    try:
        params = params or {}
        with db._connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO session_logs
                    (mobile_number, machine_id, session_type, qr_code,
                     activated_at, status,
                     sval, cval, dval, wval, dryval, fval,
                     wt, stval, msgval, tdry, pr, ctype)
                VALUES
                    (%s, %s, %s, %s, NOW(), 'activated',
                     %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                mobile_number, machine_id, session_type, qr_code,
                params.get('sval'), params.get('cval'),
                params.get('dval'), params.get('wval'),
                params.get('dryval'), params.get('fval'),
                params.get('wt'), params.get('stval'),
                params.get('msgval'), params.get('tdry'),
                params.get('pr'), params.get('ctype'),
            ))
            session_id = cursor.lastrowid
            logger.info(f"Session activated - ID: {session_id}, Type: {session_type}")
            return session_id
    except Exception as e:
        logger.error(f"log_session_activated error: {e}")
        return None


def log_session_start(db, session_id: int) -> bool:
    """Mark session as started."""
    return _update_session(db, session_id,
                           "SET session_start = NOW(), status = 'started'")


def log_session_in_progress(db, session_id: int) -> bool:
    """Mark session as in_progress."""
    return _update_session(db, session_id, "SET status = 'in_progress'")


def log_session_complete(db, session_id: int, duration_seconds: int) -> bool:
    """Mark session as completed with total duration."""
    return _update_session(
        db, session_id,
        "SET session_end = NOW(), total_duration_seconds = %s, status = 'completed'",
        (duration_seconds,),
    )


def log_session_error(db, session_id: int, error_message: str = "") -> bool:
    """Mark session as errored."""
    return _update_session(
        db, session_id,
        "SET session_end = NOW(), status = 'error', error_message = %s",
        (error_message,),
    )


def log_session_stopped(db, session_id: int, duration_seconds: int = None) -> bool:
    """Mark session as manually stopped."""
    return _update_session(
        db, session_id,
        "SET session_end = NOW(), status = 'stopped', total_duration_seconds = %s",
        (duration_seconds,),
    )


def _update_session(db, session_id: int, set_clause: str, extra_params=()) -> bool:
    """Generic helper to UPDATE session_logs by ID."""
    if not db or not db._ensure_connection():
        return False
    try:
        with db._connection.cursor() as cursor:
            sql = f"UPDATE session_logs {set_clause} WHERE id = %s"
            cursor.execute(sql, (*extra_params, session_id))
            return True
    except Exception as e:
        logger.error(f"Session update error (id={session_id}): {e}")
        return False


# =========================================================================
# Stage Logging
# =========================================================================

def log_stage_start(db, session_id: int, stage_name: str,
                    stage_order: int, planned_duration: int) -> Optional[int]:
    """Log the start of a stage. Returns the session_stages row ID."""
    if not db or not db._ensure_connection():
        return None

    try:
        with db._connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO session_stages
                    (session_id, stage_name, stage_order,
                     planned_duration_seconds, start_time, status)
                VALUES (%s, %s, %s, %s, NOW(), 'started')
            """, (session_id, stage_name, stage_order, planned_duration))
            return cursor.lastrowid
    except Exception as e:
        logger.error(f"log_stage_start error: {e}")
        return None


def log_stage_complete(db, stage_id: int, actual_duration: int) -> bool:
    """Mark a stage as completed."""
    if not db or not db._ensure_connection():
        return False
    try:
        with db._connection.cursor() as cursor:
            cursor.execute("""
                UPDATE session_stages
                SET end_time = NOW(), actual_duration_seconds = %s, status = 'completed'
                WHERE id = %s
            """, (actual_duration, stage_id))
            return True
    except Exception as e:
        logger.error(f"log_stage_complete error: {e}")
        return False


def log_stage_error(db, stage_id: int, error_message: str) -> bool:
    """Mark a stage as errored."""
    if not db or not db._ensure_connection():
        return False
    try:
        with db._connection.cursor() as cursor:
            cursor.execute("""
                UPDATE session_stages
                SET end_time = NOW(), status = 'error', notes = %s
                WHERE id = %s
            """, (error_message, stage_id))
            return True
    except Exception as e:
        logger.error(f"log_stage_error error: {e}")
        return False


def log_stage_skipped(db, session_id: int, stage_name: str,
                      stage_order: int, reason: str = None) -> bool:
    """Record that a stage was skipped."""
    if not db or not db._ensure_connection():
        return False
    try:
        with db._connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO session_stages
                    (session_id, stage_name, stage_order, status, notes)
                VALUES (%s, %s, %s, 'skipped', %s)
            """, (session_id, stage_name, stage_order, reason))
            return True
    except Exception as e:
        logger.error(f"log_stage_skipped error: {e}")
        return False


# =========================================================================
# Event Logging
# =========================================================================

def log_event(db, session_id: int, event_type: str,
              event_data: Dict = None) -> bool:
    """Log a granular event (relay_on, relay_off, pump_start, etc.)."""
    if not db or not db._ensure_connection():
        return False
    try:
        with db._connection.cursor() as cursor:
            event_json = json.dumps(event_data) if event_data else None
            cursor.execute("""
                INSERT INTO session_events (session_id, event_type, event_data)
                VALUES (%s, %s, %s)
            """, (session_id, event_type, event_json))
            return True
    except Exception as e:
        logger.error(f"log_event error: {e}")
        return False


# =========================================================================
# Queries / Analytics
# =========================================================================

def get_session_history(db, mobile_number: str, limit: int = 10) -> List[Dict]:
    """Get recent session logs for a customer."""
    if not db or not db._ensure_connection():
        return []
    try:
        with db._connection.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM session_logs
                WHERE mobile_number = %s
                ORDER BY created_at DESC LIMIT %s
            """, (mobile_number, limit))
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        logger.error(f"get_session_history error: {e}")
        return []


def get_session_details(db, session_id: int) -> Optional[Dict]:
    """Get full session details including stages and events."""
    if not db or not db._ensure_connection():
        return None
    try:
        result = {}
        with db._connection.cursor() as cursor:
            cursor.execute("SELECT * FROM session_logs WHERE id = %s", (session_id,))
            result['session'] = cursor.fetchone()
            if not result['session']:
                return None

            cursor.execute("""
                SELECT * FROM session_stages
                WHERE session_id = %s ORDER BY stage_order
            """, (session_id,))
            result['stages'] = cursor.fetchall()

            cursor.execute("""
                SELECT * FROM session_events
                WHERE session_id = %s ORDER BY event_time
            """, (session_id,))
            result['events'] = cursor.fetchall()
        return result
    except Exception as e:
        logger.error(f"get_session_details error: {e}")
        return None


def get_machine_stats(db, machine_id: str, days: int = 30) -> Dict:
    """Get aggregate statistics for a machine."""
    if not db or not db._ensure_connection():
        return {}
    try:
        stats = {}
        with db._connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END) as completed,
                       SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as errors,
                       AVG(total_duration_seconds) as avg_duration
                FROM session_logs
                WHERE machine_id = %s
                  AND activated_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
            """, (machine_id, days))
            stats['sessions'] = cursor.fetchone()

            cursor.execute("""
                SELECT session_type, COUNT(*) as count
                FROM session_logs
                WHERE machine_id = %s
                  AND activated_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                GROUP BY session_type
            """, (machine_id, days))
            stats['by_type'] = cursor.fetchall()
        return stats
    except Exception as e:
        logger.error(f"get_machine_stats error: {e}")
        return {}
