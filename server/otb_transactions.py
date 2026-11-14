#!/usr/bin/env python3
"""OTB enrollment transaction writer — isolated development."""

import fcntl
import json
import os
import tempfile
from pathlib import Path

import otb_registry

BASE = (
    Path(__file__).resolve().parent
    / "pending-test/registration"
).resolve()

FILES = {
    "tokens": "tokens.json",
    "registry": "collector-status.json",
    "config": "chains.json",
}

JOURNAL = BASE / "transaction.json"
LOCK = BASE / "enroll.lock"


def save_json(path, data):
    """Atomically replace one JSON file, using private permissions."""
    fd, temporary = tempfile.mkstemp(
        prefix=".transaction-",
        dir=str(path.parent)
    )

    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

        os.chmod(temporary, 0o600)
        os.replace(temporary, path)

        directory_fd = os.open(
            str(path.parent), os.O_RDONLY
        )

        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)

    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate_transaction(data):
    if not isinstance(data, dict):
        raise ValueError("Invalid transaction")

    if set(data) != set(FILES):
        raise ValueError("Incomplete transaction")

    if not all(isinstance(value, dict)
               for value in data.values()):
        raise ValueError("Invalid transaction contents")

    if data["registry"].get("version") != 1:
        raise ValueError("Invalid registry version")

    # Validate using the existing registration library.
    # The temporary registry is restricted to our test folder.
    fd, temporary = tempfile.mkstemp(
        prefix=".validate-",
        dir=str(BASE)
    )

    try:
        with os.fdopen(fd, "w") as handle:
            json.dump(data["registry"], handle)

        otb_registry.load_registry(temporary)

    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def recover_locked():
    """Complete an interrupted transaction; caller holds LOCK."""
    if not JOURNAL.exists():
        return False

    transaction = json.loads(JOURNAL.read_text())
    validate_transaction(transaction)

    for key, filename in FILES.items():
        save_json(BASE / filename, transaction[key])

    JOURNAL.unlink()

    directory_fd = os.open(str(BASE), os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)

    return True


def recover():
    """Recover an interrupted transaction under the file lock."""
    with LOCK.open("r") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return recover_locked()


def commit_locked(staged):
    """Commit a transaction while the caller holds LOCK."""
    validate_transaction(staged)

    if JOURNAL.exists():
        raise RuntimeError(
            "Pending transaction requires recovery"
        )

    # Journal must be durable before registry writes begin.
    save_json(JOURNAL, staged)

    for key, filename in FILES.items():
        save_json(BASE / filename, staged[key])

    JOURNAL.unlink()

    directory_fd = os.open(str(BASE), os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)



def commit(staged):
    """Commit prepared data, retaining the existing public API."""
    with LOCK.open("r") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        commit_locked(staged)


def enroll_provisional(chain, collector, enode):
    """Validate and register a collector under one exclusive lock."""
    with LOCK.open("r") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)

        # Finish any interrupted transaction first.
        recover_locked()

        config = json.loads(
            (BASE / "chains.json").read_text()
        )
        tokens = json.loads(
            (BASE / "tokens.json").read_text()
        )
        registry = otb_registry.load_registry(
            BASE / "collector-status.json"
        )

        result = otb_registry.stage_provisional_registration(
            registry, tokens, config,
            chain, collector, enode
        )

        staged = {
            "tokens": result["tokens"],
            "registry": result["registry"],
            "config": result["config"]
        }

        commit_locked(staged)

        return {
            "chain": chain,
            "collector": collector,
            "token": result["token"],
            "status": "pending",
            "expires_at": result["registry"]["collectors"]
                [chain][collector]["expires_at"]
        }




def approve_collector(chain, collector):
    """Approve a pending collector under the enrollment lock."""
    from datetime import datetime, timezone

    with LOCK.open("r") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)

        recover_locked()

        config = json.loads(
            (BASE / "chains.json").read_text()
        )
        tokens = json.loads(
            (BASE / "tokens.json").read_text()
        )
        registry = otb_registry.load_registry(
            BASE / "collector-status.json"
        )

        if chain not in config["chains"]:
            raise ValueError("Unknown blockchain")

        settings = config["chains"][chain]

        if not settings.get("enabled"):
            raise ValueError("Blockchain disabled")

        record = registry["collectors"].get(
            chain, {}
        ).get(collector)

        if record is None:
            raise ValueError("Collector not registered")

        if record.get("status") != "pending":
            raise ValueError("Collector is not pending")

        expires = datetime.fromisoformat(
            record["expires_at"]
        )
        now = datetime.now(timezone.utc)

        if expires.tzinfo is None or now >= expires:
            raise ValueError("Provisional registration expired")

        if collector not in tokens.get(chain, {}):
            raise ValueError("Collector credential missing")

        if collector in settings["collectors"]:
            raise ValueError("Collector already approved")

        staged = {
            "tokens": tokens,
            "registry": registry,
            "config": config
        }

        record["status"] = "enabled"
        record["updated_at"] = now.isoformat()
        record["last_action"] = "admin_approved"

        settings["collectors"].append(collector)

        commit_locked(staged)

        return {
            "chain": chain,
            "collector": collector,
            "status": "enabled",
            "node_id": record["node_id"]
        }



if __name__ == "__main__":
    print("OTB transaction module — development")
    print("Test directory:", BASE)
    print("No transactions executed.")
