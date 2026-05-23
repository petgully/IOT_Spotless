"""
=============================================================================
Operator Admin — Form / Payload Validators
=============================================================================
All operator-supplied values pass through here before reaching ConfigManager.

Bad input (a typo, an out-of-range value, an HH:MM string with a 25th hour)
must NOT silently corrupt config.json — the running kiosk would then build
sessions with garbage timings (zero-second shampoo, 9999-second dryer).

Each validator returns (cleaned_value, error_message_or_None). On the first
error the caller bails out and shows the operator a friendly message.
=============================================================================
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# (field, label, min_seconds, max_seconds)
SIZE_PROFILE_FIELDS: List[Tuple[str, str, int, int]] = [
    ("sval",          "Shampoo spray (s)",                   1, 600),
    ("cval",          "Conditioner spray (s)",               1, 600),
    ("wval",          "Water rinse — each pass (s)",         1, 600),
    ("dval",          "Disinfectant spray (s)",              1, 600),
    ("dryval",        "Dryer total (s)",                     1, 1800),
    ("fval",          "Auto-flush per phase (s)",            1, 600),
    ("wt",            "Peristaltic pump dose (s)",           1, 600),
    ("msgval",        "Massage / soak wait (s)",             0, 600),
    ("tdry",          "Towel dry wait (s)",                  0, 600),
    ("prime_fill",    "Prime: fill (s)",                     1, 300),
    ("prime_empty",   "Prime: first empty (s)",              1, 300),
    ("prime_empty_2", "Prime: second empty (s)",             1, 300),
]

GEYSER_NUMERIC_FIELDS = [
    ("heat_duration_sec", "Heat duration (s)",  60, 3600),
    ("safety_cutoff_sec", "Safety cutoff (s)",  60, 7200),
]

ROOF_LIGHT_TIME_FIELDS = ["evening_on_time", "evening_off_time"]


# =============================================================================
# Primitives
# =============================================================================

def _to_int(raw: Any) -> Optional[int]:
    if raw is None:
        return None
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return None
        try:
            return int(s)
        except ValueError:
            return None
    return None


def _validate_int_in_range(
    raw: Any, label: str, lo: int, hi: int,
) -> Tuple[Optional[int], Optional[str]]:
    n = _to_int(raw)
    if n is None:
        return None, f"{label}: must be a whole number (got {raw!r})."
    if n < lo or n > hi:
        return None, f"{label}: must be between {lo} and {hi} (got {n})."
    return n, None


def _validate_hhmm(raw: Any, label: str) -> Tuple[Optional[str], Optional[str]]:
    if not isinstance(raw, str):
        return None, f"{label}: must be HH:MM (got {raw!r})."
    s = raw.strip()
    if len(s) != 5 or s[2] != ":":
        return None, f"{label}: must be HH:MM (got {raw!r})."
    try:
        h, m = int(s[:2]), int(s[3:])
    except ValueError:
        return None, f"{label}: must be HH:MM with numeric hour and minute (got {raw!r})."
    if not (0 <= h <= 23) or not (0 <= m <= 59):
        return None, f"{label}: hour 00-23 and minute 00-59 (got {raw!r})."
    return f"{h:02d}:{m:02d}", None


def _validate_short_text(
    raw: Any, label: str, *, max_len: int = 64, allow_empty: bool = False,
) -> Tuple[Optional[str], Optional[str]]:
    if raw is None:
        if allow_empty:
            return "", None
        return None, f"{label}: required."
    s = str(raw).strip()
    if not s and not allow_empty:
        return None, f"{label}: required."
    if len(s) > max_len:
        return None, f"{label}: too long (max {max_len} chars)."
    if "\n" in s or "\r" in s:
        return None, f"{label}: cannot contain newlines."
    return s, None


# =============================================================================
# Section validators (form payload -> cleaned dict OR error message)
# =============================================================================

def validate_size_profile(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, int]], Optional[str]]:
    """Validate a SET A or SET B timing payload.

    The payload may contain a subset of the fields — we only validate what
    was supplied so that adding a new field later doesn't force us to re-emit
    every old field.
    """
    cleaned: Dict[str, int] = {}
    for field, label, lo, hi in SIZE_PROFILE_FIELDS:
        if field not in payload:
            continue
        n, err = _validate_int_in_range(payload[field], label, lo, hi)
        if err:
            return None, err
        cleaned[field] = n  # type: ignore[assignment]
    if not cleaned:
        return None, "No timing fields supplied."
    return cleaned, None


def validate_geyser(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    cleaned: Dict[str, Any] = {}
    if "morning_preheat_time" in payload:
        v, err = _validate_hhmm(payload["morning_preheat_time"], "Morning pre-heat time")
        if err:
            return None, err
        cleaned["morning_preheat_time"] = v
    for field, label, lo, hi in GEYSER_NUMERIC_FIELDS:
        if field not in payload:
            continue
        n, err = _validate_int_in_range(payload[field], label, lo, hi)
        if err:
            return None, err
        cleaned[field] = n
    if not cleaned:
        return None, "No geyser fields supplied."
    return cleaned, None


def validate_roof_light(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    cleaned: Dict[str, Any] = {}
    for field in ROOF_LIGHT_TIME_FIELDS:
        if field not in payload:
            continue
        label = "Evening ON" if field == "evening_on_time" else "Evening OFF"
        v, err = _validate_hhmm(payload[field], label)
        if err:
            return None, err
        cleaned[field] = v
    if not cleaned:
        return None, "No roof light fields supplied."
    # Note: a window where on == off is treated as "always off" by the
    # controller's _is_evening_window. We allow it but warn the operator
    # via the UI; backend doesn't reject it.
    return cleaned, None


def validate_machine_info(payload: Dict[str, Any]) -> Tuple[Optional[Dict[str, str]], Optional[str]]:
    cleaned: Dict[str, str] = {}
    if "machine_name" in payload:
        v, err = _validate_short_text(payload["machine_name"], "Machine name", max_len=64)
        if err:
            return None, err
        cleaned["machine_name"] = v  # type: ignore[assignment]
    if "location" in payload:
        v, err = _validate_short_text(payload["location"], "Location", max_len=128, allow_empty=True)
        if err:
            return None, err
        cleaned["location"] = v  # type: ignore[assignment]
    if not cleaned:
        return None, "No machine info fields supplied."
    return cleaned, None
