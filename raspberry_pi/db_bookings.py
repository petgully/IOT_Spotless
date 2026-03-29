"""
=============================================================================
Database - Booking Queries - Project Spotless
=============================================================================
All booking-related database operations: lookup, status updates.

Depends on: db_manager.DatabaseManager for the connection.
=============================================================================
"""

import logging
from typing import Optional, Dict

logger = logging.getLogger(__name__)


def get_booking_by_code(db, booking_code: str) -> Optional[Dict]:
    """
    Look up a booking with pet and customer info.

    Args:
        db: DatabaseManager instance (must be connected).
        booking_code: The PG-prefixed booking code.

    Returns:
        Dict with booking row + pet_name + customer_name, or None.
    """
    if not db or not db.is_connected:
        return None

    try:
        with db._connection.cursor() as cursor:
            cursor.execute("""
                SELECT b.*, p.name as pet_name, c.name as customer_name
                FROM bookings b
                JOIN pets p ON b.pet_id = p.id
                JOIN customers c ON b.customer_id = c.id
                WHERE b.booking_code = %s
            """, (booking_code,))
            row = cursor.fetchone()
            return dict(row) if row else None
    except Exception as e:
        logger.error(f"Booking lookup error: {e}")
        return None


def update_booking_status(db, booking_code: str, status: str) -> bool:
    """
    Update the status of a booking (e.g. confirmed, completed).

    Args:
        db: DatabaseManager instance.
        booking_code: The PG-prefixed booking code.
        status: New status string.

    Returns:
        True if the update succeeded.
    """
    if not db or not db.is_connected:
        return False

    try:
        with db._connection.cursor() as cursor:
            cursor.execute(
                "UPDATE bookings SET status = %s WHERE booking_code = %s",
                (status, booking_code),
            )
            logger.info(f"Booking {booking_code} -> status={status}")
            return True
    except Exception as e:
        logger.error(f"Booking status update error: {e}")
        return False
