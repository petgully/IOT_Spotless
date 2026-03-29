"""
=============================================================================
QR Code Validator - Project Spotless
=============================================================================
Validates QR codes scanned at the kiosk and resolves them to a session type
with parameters.

Validation priority:
    1. Booking lookup (PG prefix — from booking app)
    2. Session config lookup (legacy mobile number key)
    3. Prefix mapping (SM, LG, TEST, DRY, etc.)
    4. Direct session type name (e.g. "small", "demo")
    5. Invalid — returns None

This module has NO dependency on Flask, SocketIO, or hardware controllers.
=============================================================================
"""

import logging
from typing import Optional, Dict

from session_stages import is_known_session_type

logger = logging.getLogger(__name__)

# Prefix → session type mapping for quick-start codes
PREFIX_MAP = {
    'SM': 'small',
    'LG': 'large',
    'DIY': 'custdiy',
    'MDS': 'medsmall',
    'MDL': 'medlarge',
    'DIS': 'onlydisinfectant',
    'TEST': 'quicktest',
    'DEMO': 'demo',
    'DRY': 'onlydrying',
    'WATER': 'onlywater',
    'FLUSH': 'onlyflush',
    'SHAMP': 'onlyshampoo',
    'EMPTY': 'empty001',
    'SMALL': 'small',
    'LARGE': 'large',
    'DEFAULT_SMALL': 'small',
    'DEFAULT_LARGE': 'large',
    'DEFAULT_DIY': 'custdiy',
}

SESSION_PARAM_KEYS = [
    'sval', 'cval', 'dval', 'wval', 'dryval',
    'fval', 'wt', 'stval', 'msgval', 'tdry', 'pr', 'ctype',
]


def _empty_result(qr_code: str) -> Dict:
    """Create a blank result template."""
    return {
        'session_type': None,
        'params': None,
        'customer_name': None,
        'pet_name': None,
        'mobile_number': qr_code,
        'booking_code': None,
        'from_database': False,
    }


def _extract_params(row: Dict, defaults: Dict = None) -> Dict:
    """Pull session param keys from a DB row, applying defaults for missing values."""
    base = defaults or {
        'sval': 120, 'cval': 120, 'dval': 60, 'wval': 60,
        'dryval': 480, 'fval': 60, 'wt': 30, 'stval': 10,
        'msgval': 10, 'tdry': 30, 'pr': 20, 'ctype': 100,
    }
    return {k: row.get(k, base.get(k)) for k in SESSION_PARAM_KEYS}


def _try_booking_lookup(db, qr_code: str, result: Dict) -> Optional[Dict]:
    """Attempt to find a booking by PG-prefixed code."""
    try:
        with db._connection.cursor() as cursor:
            cursor.execute("""
                SELECT b.*, p.name as pet_name, c.name as customer_name
                FROM bookings b
                JOIN pets p ON b.pet_id = p.id
                JOIN customers c ON b.customer_id = c.id
                WHERE b.booking_code = %s
            """, (qr_code,))
            booking = cursor.fetchone()

            if booking:
                result['session_type'] = booking.get('session_type', 'small')
                result['booking_code'] = booking.get('booking_code')
                result['customer_name'] = booking.get('customer_name')
                result['pet_name'] = booking.get('pet_name')
                result['params'] = _extract_params(booking)
                result['from_database'] = True

                cursor.execute(
                    "UPDATE bookings SET status = 'confirmed' WHERE booking_code = %s",
                    (qr_code,),
                )
                logger.info(f"Booking found: {qr_code} -> {result['session_type']} for {result['pet_name']}")
                return result
    except Exception as e:
        logger.warning(f"Booking lookup failed: {e}")
    return None


def _try_session_config_lookup(db, qr_code: str, result: Dict) -> Optional[Dict]:
    """Attempt to find a session_config row by the scanned value."""
    try:
        config = db.get_session_config(qr_code)
        if config:
            result['session_type'] = config.get('session_type', 'small')
            result['params'] = _extract_params(config)
            result['customer_name'] = config.get('customer_name')
            result['from_database'] = True
            logger.info(f"Session config found: {qr_code} -> {result['session_type']}")
            return result
    except Exception as e:
        logger.warning(f"Session config lookup failed: {e}")
    return None


def _try_prefix_match(db, qr_upper: str, result: Dict) -> Optional[Dict]:
    """Match QR code against known prefixes."""
    for prefix, session_type in PREFIX_MAP.items():
        if qr_upper.startswith(prefix):
            result['session_type'] = session_type
            if db and db.is_connected:
                try:
                    default_config = db.get_session_by_type(session_type)
                    if default_config:
                        result['params'] = {
                            k: v for k, v in default_config.items()
                            if k in SESSION_PARAM_KEYS
                        }
                except Exception:
                    pass
            return result
    return None


def validate_qr_code(qr_code: str, db=None) -> Optional[Dict]:
    """
    Validate a QR code and resolve it to session type + parameters.

    Args:
        qr_code: Raw string scanned from the barcode reader.
        db:      DatabaseManager instance (or None when offline).

    Returns:
        Dict with session_type, params, customer_name, etc. — or None if invalid.
    """
    qr_upper = qr_code.upper().strip()
    result = _empty_result(qr_code)

    # --- Priority 1 & 2: Database lookups ---
    if db and db.is_connected:
        if qr_upper.startswith('PG'):
            booking_result = _try_booking_lookup(db, qr_code, result)
            if booking_result:
                return booking_result

        config_result = _try_session_config_lookup(db, qr_code, result)
        if config_result:
            return config_result

    # --- Priority 3: Prefix mapping ---
    prefix_result = _try_prefix_match(db, qr_upper, result)
    if prefix_result:
        return prefix_result

    # --- Priority 4: Direct session type name ---
    qr_lower = qr_code.lower().strip()
    if is_known_session_type(qr_lower):
        result['session_type'] = qr_lower
        return result

    # --- Invalid ---
    logger.warning(f"Invalid QR code: {qr_code}")
    return None
