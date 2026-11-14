#!/usr/bin/env python3
"""Private OTB administrator audit log — development only."""

import fcntl
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID


SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")

ACTIONS = {
    "approve",
    "deny",
    "suspend",
    "enable",
    "revoke"
}

OUTCOMES = {
    "attempt",
    "success",
    "rejected",
    "error"
}


def validate_name(value):
    return (
        isinstance(value, str)
        and value not in (".", "..")
        and SAFE_NAME.fullmatch(value) is not None
    )


def append_event(path, administrator, action,
                 chain, collector, outcome, operation_id=None):
    """Append a restricted, structured audit event."""

    if not all(validate_name(value) for value in (
        administrator, chain, collector
    )):
        raise ValueError("Invalid audit identity")

    if action not in ACTIONS:
        raise ValueError("Invalid audit action")

    if outcome not in OUTCOMES:
        raise ValueError("Invalid audit outcome")

    if operation_id is not None:
        if not isinstance(operation_id, str):
            raise ValueError("Invalid audit operation ID")
        try:
            parsed_id = UUID(operation_id)
        except ValueError:
            raise ValueError("Invalid audit operation ID") from None

        if parsed_id.version != 4 or str(parsed_id) != operation_id:
            raise ValueError("Invalid audit operation ID")

    path = Path(path)

    if not path.parent.is_dir():
        raise ValueError("Audit directory unavailable")

    event = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "administrator": administrator,
        "action": action,
        "chain": chain,
        "collector": collector,
        "outcome": outcome
    }

    if operation_id is not None:
        event["operation_id"] = operation_id

    line = (
        json.dumps(event, separators=(",", ":")) + "\n"
    ).encode("utf-8")

    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT

    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC

    fd = os.open(str(path), flags, 0o600)

    try:
        info = os.fstat(fd)

        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Audit destination is not a file")

        if info.st_mode & 0o077:
            raise ValueError("Audit file permissions too open")

        with os.fdopen(fd, "ab", closefd=False) as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
            fcntl.flock(handle, fcntl.LOCK_UN)

    finally:
        os.close(fd)

    return event
