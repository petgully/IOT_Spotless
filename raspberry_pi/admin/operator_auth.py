"""
=============================================================================
Operator Admin — HTTP Basic Auth
=============================================================================
Single-password gate for the per-booth admin UI mounted on the kiosk Flask
app at /admin/*.

Why HTTP Basic Auth?
- Zero JS dependencies, browser-native.
- Survives full-page reloads from form submissions without session plumbing.
- A booth manager who closes their laptop and reopens it is re-prompted —
  acceptable for a shared-machine operator console.
- Multi-machine: each booth uses its own SPOTLESS_ADMIN_PASSWORD env var
  loaded from /home/spotless/IOT_Spotless/raspberry_pi/.env. Operators can
  use the same password across all booths or pick per-booth ones; either
  works without code changes.

Username is fixed at "admin"; the password comes from SPOTLESS_ADMIN_PASSWORD
env var (default "spotless-admin", which the bootstrap warns operators to
change).
=============================================================================
"""

from __future__ import annotations

import hmac
import logging
import os
from functools import wraps
from typing import Callable

from flask import Response, request

logger = logging.getLogger(__name__)

ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "spotless-admin"
ENV_VAR = "SPOTLESS_ADMIN_PASSWORD"


def _get_expected_password() -> str:
    return os.environ.get(ENV_VAR) or DEFAULT_ADMIN_PASSWORD


def _is_default_password() -> bool:
    return _get_expected_password() == DEFAULT_ADMIN_PASSWORD


def _check_credentials(username: str, password: str) -> bool:
    """Constant-time comparison so timing can't leak the password."""
    if not username or not password:
        return False
    user_ok = hmac.compare_digest(username, ADMIN_USERNAME)
    pass_ok = hmac.compare_digest(password, _get_expected_password())
    return user_ok and pass_ok


def _challenge() -> Response:
    return Response(
        "Authentication required.\n",
        401,
        {"WWW-Authenticate": 'Basic realm="Spotless Admin"'},
    )


def require_admin(view: Callable) -> Callable:
    """Decorator: gate a Flask view behind the shared admin password."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        auth = request.authorization
        if auth is None or not _check_credentials(auth.username or "", auth.password or ""):
            client = request.headers.get("X-Forwarded-For", request.remote_addr or "?")
            logger.info(f"admin: auth challenge issued to {client} for {request.path}")
            return _challenge()
        return view(*args, **kwargs)

    return wrapper


def is_using_default_password() -> bool:
    """Public probe — used by the dashboard to nag operators about defaults."""
    return _is_default_password()
