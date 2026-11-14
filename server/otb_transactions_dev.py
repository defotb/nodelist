#!/usr/bin/env python3
"""OTB enrollment transaction writer — isolated development."""

import fcntl
import importlib.util
import json
import os
import tempfile
from pathlib import Path

import otb_registry_dev as otb_registry
import otb_consistency_dev

BASE = (
    Path(__file__).resolve().parent
    / "pending-test/registration"
).resolve()

FILES = {
    "tokens": "tokens.json",
    "registry": "collector-status.json",
    "config": "chains.json",
}

# Share the existing enrollment server's journal and recovery.
spec = importlib.util.spec_from_file_location(
    "otb_enrollment_shared_dev",
    Path(__file__).resolve().parent / "otb-enrollment-dev.py"
)
enrollment = importlib.util.module_from_spec(spec)
spec.loader.exec_module(enrollment)

JOURNAL = enrollment.JOURNAL
LOCK = enrollment.LOCK

assert enrollment.REGISTRATION == BASE
assert JOURNAL == BASE / "enroll-transaction.json"
assert LOCK == BASE / "enroll.lock"


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

        # Reject inconsistent registration data before
        # writing the shared transaction journal.
        otb_consistency_dev.validate(
            data["tokens"],
            data["config"],
            data["registry"]
        )

    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def recover_locked():
    """Recover the shared journal; caller holds the enrollment lock."""
    if not JOURNAL.exists():
        return False

    enrollment.recover_pending()
    return True


def recover():
    """Recover an interrupted transaction under the file lock."""
    with LOCK.open("r") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return recover_locked()


def commit_locked(staged, removal=None):
    """Commit through shared enrollment recovery.

    Caller must hold the exclusive enrollment lock.
    """
    validate_transaction(staged)

    if removal is not None:
        if not isinstance(removal, dict):
            raise ValueError("Invalid removal")

        if set(removal) != {"chain", "collector", "scope"}:
            raise ValueError("Incomplete removal")

        chain = removal["chain"]
        collector = removal["collector"]
        scope = removal["scope"]

        if (
            not isinstance(chain, str)
            or not isinstance(collector, str)
            or not otb_registry.VALID_NAME.fullmatch(chain)
            or not otb_registry.VALID_NAME.fullmatch(collector)
            or chain in (".", "..")
            or collector in (".", "..")
            or scope not in ("pending", "approved")
        ):
            raise ValueError("Invalid removal target")

        record = staged["registry"]["collectors"].get(
            chain, {}
        ).get(collector)

        if record is None or record["status"] != "revoked":
            raise ValueError("Removal requires revoked collector")

        if collector in staged["tokens"].get(chain, {}):
            raise ValueError("Revoked collector retains token")

        if collector in staged["config"]["chains"][chain]["collectors"]:
            raise ValueError("Revoked collector remains approved")

    if JOURNAL.exists():
        raise RuntimeError(
            "Pending transaction requires recovery"
        )

    # Preserve invitations from the current locked database.
    invitations = json.loads(
        enrollment.INVITES.read_text()
    )

    if not isinstance(invitations, dict):
        raise ValueError("Invalid invitations database")

    transaction = {
        "tokens": staged["tokens"],
        "config": staged["config"],
        "invitations": invitations,
        "registry": staged["registry"]
    }

    if removal is not None:
        transaction["removal"] = dict(removal)

    # Durable journal first; shared recovery performs all writes.
    save_json(JOURNAL, transaction)
    enrollment.recover_pending()


def commit(staged):
    """Reject externally prepared registration snapshots.

    Call an operation that loads current state under the
    enrollment lock instead.
    """
    raise RuntimeError(
        "Direct snapshot commits are disabled; "
        "use a lock-protected registration operation"
    )


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



def set_collector_enabled(chain, collector, enabled):
    """Suspend or re-enable an approved collector.

    Internal administrator operation; caller authorization
    must be enforced before exposing this through an API.
    """
    from datetime import datetime, timezone

    if not isinstance(enabled, bool):
        raise ValueError("Enabled must be a boolean")

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

        record = registry["collectors"].get(
            chain, {}
        ).get(collector)

        if record is None:
            raise ValueError("Collector not registered")

        current = record["status"]
        expected = "suspended" if enabled else "enabled"

        if current != expected:
            raise ValueError(
                "Invalid collector status transition"
            )

        if collector not in settings["collectors"]:
            raise ValueError("Collector not approved")

        if collector not in tokens.get(chain, {}):
            raise ValueError("Collector credential missing")

        new_status = "enabled" if enabled else "suspended"

        record["status"] = new_status
        record["updated_at"] = datetime.now(
            timezone.utc
        ).isoformat()
        record["last_action"] = (
            "admin_enabled" if enabled else "admin_suspended"
        )

        commit_locked({
            "tokens": tokens,
            "config": config,
            "registry": registry
        })

        return {
            "chain": chain,
            "collector": collector,
            "status": new_status,
            "node_id": record.get("node_id")
        }


def _admin_remove_collector(chain, collector, action):
    """Perform an internal, lock-protected administrator removal."""
    from datetime import datetime, timezone

    if action not in ("deny", "revoke"):
        raise ValueError("Invalid administrator removal action")

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
        record = registry["collectors"].get(
            chain, {}
        ).get(collector)

        if record is None:
            raise ValueError("Collector not registered")

        status = record["status"]
        approved = collector in settings["collectors"]

        if action == "deny":
            if status != "pending" or approved:
                raise ValueError(
                    "Denial requires a pending collector"
                )
            scope = "pending"
            last_action = "admin_denied"

        else:
            if status not in ("enabled", "suspended"):
                raise ValueError(
                    "Revocation requires an approved collector"
                )
            if not approved:
                raise ValueError("Approved membership missing")
            scope = "approved"
            last_action = "admin_revoked"

        if collector not in tokens.get(chain, {}):
            raise ValueError("Collector credential missing")

        node_id = record.get("node_id")

        # Preserve the identity reservation.
        record["status"] = "revoked"
        record["updated_at"] = datetime.now(
            timezone.utc
        ).isoformat()
        record["last_action"] = last_action

        # Remove credentials and approved membership as applicable.
        del tokens[chain][collector]

        if scope == "approved":
            settings["collectors"].remove(collector)

        commit_locked(
            {
                "tokens": tokens,
                "config": config,
                "registry": registry
            },
            removal={
                "chain": chain,
                "collector": collector,
                "scope": scope
            }
        )

        return {
            "chain": chain,
            "collector": collector,
            "status": "revoked",
            "node_id": node_id,
            "action": last_action
        }


def deny_collector(chain, collector):
    """Deny a pending collector registration."""
    return _admin_remove_collector(chain, collector, "deny")


def revoke_collector(chain, collector):
    """Revoke an enabled or suspended collector registration."""
    return _admin_remove_collector(chain, collector, "revoke")


if __name__ == "__main__":
    print("OTB transaction module — development")
    print("Test directory:", BASE)
    print("No transactions executed.")
