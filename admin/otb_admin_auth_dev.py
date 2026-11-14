#!/usr/bin/env python3
"""OTB administrator authentication primitives — development only."""

import hashlib
import hmac
import secrets
import threading
import time

SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SALT_SIZE = 32
KEY_SIZE = 32

SESSION_SECONDS = 1800


def hash_password(password):
    """Hash a password with a random salt using scrypt."""
    if not isinstance(password, str) or len(password) < 6:
        raise ValueError("Administrator password too short")

    salt = secrets.token_bytes(SALT_SIZE)

    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=KEY_SIZE
    )

    return "scrypt:%d:%d:%d:%s:%s" % (
        SCRYPT_N,
        SCRYPT_R,
        SCRYPT_P,
        salt.hex(),
        derived.hex()
    )


def verify_password(password, stored):
    """Verify a supplied password against a stored scrypt hash."""
    if not isinstance(password, str):
        return False

    if not isinstance(stored, str):
        return False

    try:
        algorithm, n, r, p, salt, expected = stored.split(":")

        if algorithm != "scrypt":
            return False

        if (
            int(n) != SCRYPT_N
            or int(r) != SCRYPT_R
            or int(p) != SCRYPT_P
        ):
            return False

        salt = bytes.fromhex(salt)
        expected = bytes.fromhex(expected)

        if len(salt) != SALT_SIZE or len(expected) != KEY_SIZE:
            return False

        derived = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=SCRYPT_N,
            r=SCRYPT_R,
            p=SCRYPT_P,
            dklen=KEY_SIZE
        )

        return hmac.compare_digest(derived, expected)

    except (ValueError, TypeError, OverflowError):
        return False


class SessionStore:
    """Thread-safe, memory-only administrator sessions."""

    def __init__(self, lifetime=SESSION_SECONDS):
        if (
            isinstance(lifetime, bool)
            or not isinstance(lifetime, (int, float))
            or lifetime < 0
        ):
            raise ValueError("Invalid session lifetime")

        self.lifetime = lifetime
        self.sessions = {}
        self.mutex = threading.RLock()

    @staticmethod
    def fingerprint(token):
        return hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()

    def create(self, username):
        if not isinstance(username, str) or not username:
            raise ValueError("Invalid administrator username")

        token = secrets.token_urlsafe(48)
        fingerprint = self.fingerprint(token)

        with self.mutex:
            self.sessions[fingerprint] = {
                "username": username,
                "expires": time.monotonic() + self.lifetime
            }

        return token

    def authenticate(self, token):
        if not isinstance(token, str) or not token:
            return None

        fingerprint = self.fingerprint(token)

        with self.mutex:
            session = self.sessions.get(fingerprint)

            if session is None:
                return None

            if time.monotonic() >= session["expires"]:
                del self.sessions[fingerprint]
                return None

            return session["username"]

    def revoke(self, token):
        if not isinstance(token, str):
            return False

        fingerprint = self.fingerprint(token)

        with self.mutex:
            return self.sessions.pop(fingerprint, None) is not None

    def cleanup(self):
        with self.mutex:
            now = time.monotonic()

            for fingerprint, session in list(
                self.sessions.items()
            ):
                if now >= session["expires"]:
                    del self.sessions[fingerprint]
