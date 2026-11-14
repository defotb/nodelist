#!/usr/bin/env python3
"""OTB administrator account storage — development only."""

import json
import os
import re
import tempfile
from pathlib import Path

from otb_admin_auth_dev import hash_password, verify_password

USERNAME = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")


def load_account(path):
    """Load and validate a single administrator account."""
    path = Path(path)
    data = json.loads(path.read_text())

    if not isinstance(data, dict) or set(data) != {
        "version", "username", "password_hash"
    }:
        raise ValueError("Invalid administrator account")

    if data["version"] != 1:
        raise ValueError("Unsupported account version")

    if (
        not isinstance(data["username"], str)
        or not USERNAME.fullmatch(data["username"])
        or not isinstance(data["password_hash"], str)
        or not data["password_hash"].startswith("scrypt:")
    ):
        raise ValueError("Invalid administrator credentials")

    return data


def create_account(path, username, password):
    """Create one account without overwriting existing credentials."""
    path = Path(path)

    if not isinstance(username, str) or not USERNAME.fullmatch(username):
        raise ValueError("Invalid administrator username")

    if path.exists() or path.is_symlink():
        raise FileExistsError("Administrator account already exists")

    # Hash before opening any destination file.
    data = {
        "version": 1,
        "username": username,
        "password_hash": hash_password(password)
    }

    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    fd, temporary = tempfile.mkstemp(
        prefix=".admin-account-",
        dir=str(path.parent)
    )

    try:
        with os.fdopen(fd, "w") as handle:
            os.fchmod(handle.fileno(), 0o600)
            json.dump(data, handle)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        # Exclusive creation: never overwrite an existing account.
        os.link(temporary, path)

        directory_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)

    return username


def authenticate_account(path, username, password):
    """Authenticate without exposing stored password material."""
    account = load_account(path)

    if not isinstance(username, str):
        return False

    if username != account["username"]:
        return False

    return verify_password(password, account["password_hash"])
