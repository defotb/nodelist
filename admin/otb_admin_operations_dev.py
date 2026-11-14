#!/usr/bin/env python3
"""Durable administrator operation reservations — development only."""

import fcntl
import json
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from uuid import UUID

from otb_admin_audit_dev import ACTIONS, validate_name

# A generic error does not establish that a transaction rolled back.
# Only conclusively verified outcomes may be finalized.
FINAL = {"success", "rejected"}


class OperationConflict(ValueError):
    """Another unresolved operation protects this collector."""


class OperationIdConflict(ValueError):
    """An operation ID was reused with different parameters."""


def validate_id(value):
    if not isinstance(value, str):
        raise ValueError("Invalid operation ID")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ValueError("Invalid operation ID") from None
    if parsed.version != 4 or str(parsed) != value:
        raise ValueError("Invalid operation ID")


@contextmanager
def open_private_directory(root):
    """Anchor operations to a verified private directory inode."""
    flags = os.O_RDONLY | os.O_DIRECTORY

    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC

    fd = os.open(root, flags)

    try:
        info = os.fstat(fd)

        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("Operation root is not a directory")

        if info.st_mode & 0o077:
            raise ValueError("Operation directory must be private")

        if info.st_uid != os.geteuid():
            raise ValueError("Operation directory ownership mismatch")

        yield fd
    finally:
        os.close(fd)


@contextmanager
def lock_verified(directory_fd):
    """Lock a file and verify its identity within the open directory."""
    flags = os.O_RDWR | os.O_CREAT

    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC

    fd = os.open(
        "operations.lock",
        flags,
        0o600,
        dir_fd=directory_fd
    )

    try:
        info = os.fstat(fd)

        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Unsafe operation lock type")

        if info.st_mode & 0o077:
            raise ValueError("Unsafe operation lock permissions")

        if info.st_uid != os.geteuid() or info.st_nlink != 1:
            raise ValueError("Unsafe operation lock identity")

        fcntl.flock(fd, fcntl.LOCK_EX)

        try:
            current = os.stat(
                "operations.lock",
                dir_fd=directory_fd,
                follow_symlinks=False
            )

            if (
                current.st_dev != info.st_dev
                or current.st_ino != info.st_ino
                or not stat.S_ISREG(current.st_mode)
                or current.st_nlink != 1
            ):
                raise ValueError("Operation lock was replaced")

            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)

    finally:
        os.close(fd)


def check_root(root):
    root = Path(root)
    info = root.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("Operation directory must be private")
    return root


@contextmanager
def locked(root):
    """Hold the verified lock on an anchored private directory."""
    with open_private_directory(root) as directory_fd:
        with lock_verified(directory_fd):
            yield directory_fd

RECORD_FIELDS = {
    "administrator",
    "action",
    "chain",
    "collector",
    "state"
}

STATES = {"unresolved"} | FINAL


def validate_records(data):
    """Reject malformed persisted operations before using them."""

    if not isinstance(data, dict):
        raise ValueError("Invalid operation database")

    for operation_id, record in data.items():
        validate_id(operation_id)

        if not isinstance(record, dict):
            raise ValueError("Invalid operation record")

        if set(record) != RECORD_FIELDS:
            raise ValueError("Invalid operation record fields")

        if not all(validate_name(record[name]) for name in (
            "administrator", "chain", "collector"
        )):
            raise ValueError("Invalid stored operation identity")

        if record["action"] not in ACTIONS:
            raise ValueError("Invalid stored operation action")

        if record["state"] not in STATES:
            raise ValueError("Invalid stored operation state")

    return data


def load_at(directory_fd):
    """Load and validate the ledger through an anchored directory."""
    flags = os.O_RDONLY | os.O_NONBLOCK

    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC

    try:
        fd = os.open(
            "operations.json",
            flags,
            dir_fd=directory_fd
        )
    except FileNotFoundError:
        return {}

    try:
        info = os.fstat(fd)

        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Unsafe operation database type")

        if info.st_mode & 0o077:
            raise ValueError("Unsafe operation database permissions")

        if info.st_uid != os.geteuid() or info.st_nlink != 1:
            raise ValueError("Unsafe operation database identity")

        with os.fdopen(fd, "r", closefd=False) as handle:
            data = json.load(handle)

    finally:
        os.close(fd)

    return validate_records(data)


def save_at(directory_fd, data):
    """Atomically save a ledger using an anchored directory."""
    import uuid

    validate_records(data)

    temporary = ".operations-" + uuid.uuid4().hex

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL

    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC

    fd = os.open(
        temporary,
        flags,
        0o600,
        dir_fd=directory_fd
    )

    try:
        with os.fdopen(fd, "w", closefd=False) as handle:
            json.dump(data, handle, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.replace(
            temporary,
            "operations.json",
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd
        )

        os.fsync(directory_fd)

    finally:
        os.close(fd)

        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def load(root):
    path = root / "operations.json"
    if not path.exists() and not path.is_symlink():
        return {}

    flags = os.O_RDONLY | os.O_NONBLOCK

    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC

    fd = os.open(path, flags)

    try:
        info = os.fstat(fd)

        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Unsafe operation database type")

        if info.st_mode & 0o077:
            raise ValueError("Unsafe operation database permissions")

        with os.fdopen(fd, "r", closefd=False) as handle:
            data = json.load(handle)

    finally:
        os.close(fd)

    return validate_records(data)


def save(root, data):
    path = root / "operations.json"
    fd, temporary = tempfile.mkstemp(
        prefix=".operations-", dir=str(root)
    )
    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.chmod(temporary, 0o600)
        os.replace(temporary, path)

        directory_fd = os.open(root, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def claim(root, operation_id, administrator,
          action, chain, collector):
    """Durably reserve an ID before any external transaction."""
    validate_id(operation_id)

    if not all(validate_name(v) for v in (
        administrator, chain, collector
    )):
        raise ValueError("Invalid operation identity")
    if action not in ACTIONS:
        raise ValueError("Invalid operation action")

    identity = {
        "administrator": administrator,
        "action": action,
        "chain": chain,
        "collector": collector
    }

    with locked(root) as directory:
        records = load_at(directory)
        existing = records.get(operation_id)

        if existing is not None:
            if any(existing.get(k) != v for k, v in identity.items()):
                raise OperationIdConflict("Operation ID reused for another action")
            return "duplicate", dict(existing)

        # Do not reserve a second operation on a collector
        # while an earlier operation remains unresolved.
        for prior_id, prior in records.items():
            if (
                prior["chain"] == chain
                and prior["collector"] == collector
                and prior["state"] == "unresolved"
            ):
                raise OperationConflict(
                    "Collector has an unresolved operation"
                )

        record = dict(identity)
        record["state"] = "unresolved"
        records[operation_id] = record
        save_at(directory, records)
        return "claimed", dict(record)


def finish(root, operation_id, outcome):
    """Record a known outcome; never automatically re-execute."""
    validate_id(operation_id)
    if outcome not in FINAL:
        raise ValueError("Invalid operation outcome")

    with locked(root) as directory:
        records = load_at(directory)
        record = records.get(operation_id)
        if record is None:
            raise ValueError("Unknown operation ID")
        if record["state"] != "unresolved":
            raise ValueError("Operation already finalized")

        record["state"] = outcome
        save_at(directory, records)
        return dict(record)


def lookup(root, operation_id):
    validate_id(operation_id)
    with locked(root) as directory:
        record = load_at(directory).get(operation_id)
        return dict(record) if record is not None else None
