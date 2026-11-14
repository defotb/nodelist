#!/usr/bin/env python3
"""OTB administrator CSRF protection — development only."""

import hashlib
import hmac
import secrets

CSRF_SECRET = secrets.token_bytes(32)
CONTEXT = b"OTB-admin-CSRF-v1:"


def create_csrf_token(session_token):
    """Create a token cryptographically bound to one session."""
    if not isinstance(session_token, str) or not session_token:
        raise ValueError("Invalid administrator session")

    return hmac.new(
        CSRF_SECRET,
        CONTEXT + session_token.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


def verify_csrf_token(session_token, supplied):
    """Verify a CSRF token using constant-time comparison."""
    if (
        not isinstance(session_token, str)
        or not session_token
        or not isinstance(supplied, str)
        or len(supplied) != 64
    ):
        return False

    expected = create_csrf_token(session_token)

    return hmac.compare_digest(expected, supplied)
