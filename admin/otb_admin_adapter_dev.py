#!/usr/bin/env python3
"""Isolated OTB administrator transaction adapter — development."""

import importlib.util
from pathlib import Path
from uuid import uuid4


PROJECT = Path(__file__).resolve().parent

PROTECTED = (
    PROJECT / "pending-test/registration",
    PROJECT / "private",
)


def load_engine(root):
    """Load a transaction engine from an explicit isolated root."""

    root = Path(root).resolve(strict=True)
    db = root / "pending-test/registration"

    if not root.is_dir() or not db.is_dir():
        raise ValueError("Invalid isolated database directory")

    db = db.resolve(strict=True)

    for protected in PROTECTED:
        protected = protected.resolve()

        if (
            root == protected
            or protected in root.parents
            or db == protected
            or protected in db.parents
        ):
            raise ValueError("Protected database location")

    # The selected registration directory must really
    # reside directly inside the selected isolated root.
    if db != root / "pending-test/registration":
        raise ValueError("Registration path escapes isolated root")

    required = (
        "tokens.json",
        "chains.json",
        "collector-status.json",
        "invitations.json",
        "enroll.lock",
    )

    for name in required:
        path = db / name

        if not path.is_file() or path.is_symlink():
            raise ValueError("Missing or unsafe registration file")

    # Refuse an unfinished transaction rather than
    # silently recovering it while loading the adapter.
    if (db / "enroll-transaction.json").exists():
        raise ValueError("Outstanding registration transaction")

    module = root / "otb_transactions_dev.py"
    enrollment = root / "otb-enrollment-dev.py"

    for path in (module, enrollment):
        if not path.is_file() or path.is_symlink():
            raise ValueError("Isolated transaction modules missing")

    spec = importlib.util.spec_from_file_location(
        "otb_admin_isolated_" + uuid4().hex,
        module
    )

    if spec is None or spec.loader is None:
        raise ValueError("Cannot load isolated transaction engine")

    tx = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tx)

    en = tx.enrollment

    if not (
        tx.BASE == db
        and en.REGISTRATION == db
        and tx.LOCK == db / "enroll.lock"
        and tx.JOURNAL == db / "enroll-transaction.json"
        and en.LOCK == tx.LOCK
        and en.JOURNAL == tx.JOURNAL
        and en.TOKENS == db / "tokens.json"
        and en.CONFIG == db / "chains.json"
        and en.STATUS == db / "collector-status.json"
        and en.INVITES == db / "invitations.json"
        and en.WEB == root / "pending-test/approved-feeds"
    ):
        raise ValueError("Isolated transaction path mismatch")

    return tx
