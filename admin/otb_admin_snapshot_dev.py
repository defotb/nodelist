#!/usr/bin/env python3
"""Locked, read-only registration consistency snapshot."""

import fcntl
import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path

from otb_consistency_dev import validate
from otb_admin_reconcile_dev import load_private_registry


@contextmanager
def private_file(path):
    flags = os.O_RDONLY | os.O_NONBLOCK

    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC

    fd = os.open(path, flags)

    try:
        info = os.fstat(fd)

        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Unsafe snapshot file type")

        if info.st_mode & 0o077:
            raise ValueError("Unsafe snapshot file permissions")

        yield fd

    finally:
        os.close(fd)


def load_private_json(path):
    with private_file(path) as fd:
        with os.fdopen(os.dup(fd), "r") as handle:
            return json.load(handle)


def inspect_registration(registration_dir, chain=None, collector=None):
    """Read registration metadata under one anchored shared lock."""

    from otb_admin_directory_dev import (
        open_registration_directory,
        open_private_member
    )
    from otb_admin_reconcile_dev import validate_registry_data
    from otb_registry_dev import VALID_NAME

    if (chain is None) != (collector is None):
        raise ValueError("Incomplete collector identity")

    if chain is not None:
        for name in (chain, collector):
            if (
                not isinstance(name, str)
                or not VALID_NAME.fullmatch(name)
                or name in (".", "..")
            ):
                raise ValueError("Invalid collector identity")

    def read_json_member(directory_fd, name):
        with open_private_member(directory_fd, name) as fd:
            with os.fdopen(os.dup(fd), "r") as handle:
                return json.load(handle)

    with open_registration_directory(registration_dir) as directory_fd:
        with open_private_member(directory_fd, "enroll.lock") as lock_fd:
            fcntl.flock(lock_fd, fcntl.LOCK_SH)

            try:
                # Inspect journal relative to the verified directory.
                # Never follow a journal symlink.
                try:
                    journal_info = os.stat(
                        "enroll-transaction.json",
                        dir_fd=directory_fd,
                        follow_symlinks=False
                    )
                except FileNotFoundError:
                    journal_info = None

                if journal_info is not None:
                    with open_private_member(
                        directory_fd, "enroll-transaction.json"
                    ):
                        pass

                    result = {
                        "journal_present": True,
                        "registration_consistent": None,
                        "inspection_complete": False
                    }

                    if chain is not None:
                        result.update({
                            "collector_status": None,
                            "collector_last_action": None,
                            "collector_updated_at": None
                        })

                    return result

                tokens = read_json_member(directory_fd, "tokens.json")
                config = read_json_member(directory_fd, "chains.json")
                registry = validate_registry_data(
                    read_json_member(
                        directory_fd, "collector-status.json"
                    )
                )

                try:
                    consistent = validate(tokens, config, registry)
                except (ValueError, TypeError, KeyError):
                    consistent = False

                result = {
                    "journal_present": False,
                    "registration_consistent": consistent,
                    "inspection_complete": True
                }

                if chain is not None:
                    record = registry["collectors"].get(
                        chain, {}
                    ).get(collector)

                    result.update({
                        "collector_status": (
                            record.get("status") if record else None
                        ),
                        "collector_last_action": (
                            record.get("last_action") if record else None
                        ),
                        "collector_updated_at": (
                            record.get("updated_at") if record else None
                        )
                    })

                return result

            finally:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
