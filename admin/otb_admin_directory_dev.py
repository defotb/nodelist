#!/usr/bin/env python3
"""Secure directory opening for OTB development readers."""

import os
import stat
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def open_registration_directory(path):
    """Open an absolute directory path without following symlinks."""

    path = Path(path)

    if not path.is_absolute():
        raise ValueError("Registration path must be absolute")

    if ".." in path.parts:
        raise ValueError("Parent traversal is forbidden")

    flags = os.O_RDONLY | os.O_DIRECTORY

    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW

    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC

    fd = os.open("/", flags)

    try:
        for component in path.parts[1:]:
            if component in ("", "."):
                continue

            next_fd = os.open(
                component,
                flags,
                dir_fd=fd
            )

            os.close(fd)
            fd = next_fd

        info = os.fstat(fd)

        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("Unsafe registration directory type")

        if info.st_mode & 0o077:
            raise ValueError(
                "Unsafe registration directory permissions"
            )

        yield fd

    finally:
        os.close(fd)


@contextmanager
def open_private_member(directory_fd, name):
    """Open a private regular file relative to a verified directory."""

    allowed = {
        "enroll.lock",
        "enroll-transaction.json",
        "tokens.json",
        "chains.json",
        "collector-status.json"
    }

    if not isinstance(name, str) or name not in allowed:
        raise ValueError("Invalid registration filename")

    flags = (
        os.O_RDONLY |
        os.O_NONBLOCK |
        os.O_NOFOLLOW |
        os.O_CLOEXEC
    )

    fd = os.open(name, flags, dir_fd=directory_fd)

    try:
        info = os.fstat(fd)

        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Unsafe registration file type")

        if info.st_mode & 0o077:
            raise ValueError("Unsafe registration file permissions")

        yield fd

    finally:
        os.close(fd)


@contextmanager
def open_engine_directory(path):
    """Verify an engine root without following directory symlinks."""

    path = Path(path)

    if not path.is_absolute():
        raise ValueError("Engine root must be absolute")

    if ".." in path.parts:
        raise ValueError("Parent traversal is forbidden")

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC

    fd = os.open("/", flags)

    try:
        for component in path.parts[1:]:
            if component in ("", "."):
                continue

            next_fd = os.open(
                component,
                flags,
                dir_fd=fd
            )

            os.close(fd)
            fd = next_fd

        info = os.fstat(fd)

        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("Unsafe engine root type")

        # Engine source code and database paths must not be
        # replaceable by group members or other users.
        if info.st_mode & 0o022:
            raise ValueError("Writable engine root permissions")

        yield fd

    finally:
        os.close(fd)
