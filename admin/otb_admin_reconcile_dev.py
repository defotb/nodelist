#!/usr/bin/env python3
"""Read-only OTB administrator reconciliation inspector."""

import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path

from otb_admin_audit_dev import ACTIONS, OUTCOMES
from otb_admin_operations_dev import lookup, validate_id
from otb_registry_dev import load_registry


@contextmanager
def private_reader(path):
    """Read an existing private regular file without following links."""
    flags = os.O_RDONLY | os.O_NONBLOCK

    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC

    fd = os.open(path, flags)

    try:
        info = os.fstat(fd)

        if not stat.S_ISREG(info.st_mode):
            raise ValueError("Unsafe reconciliation file type")

        if info.st_mode & 0o077:
            raise ValueError("Unsafe reconciliation permissions")

        with os.fdopen(fd, "r", closefd=False) as handle:
            yield handle
    finally:
        os.close(fd)


def load_private_registry(path):
    """Read and validate an existing private registry file."""
    with private_reader(path) as handle:
        data = json.load(handle)

    return validate_registry_data(data)


def validate_registry_data(data):
    """Validate an already-loaded registry without filesystem access."""

    # Shared structural checks for both reader implementations.
    from otb_registry_dev import VALID_NAME, VALID_STATES, normalize_node_id

    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Invalid registry version")

    chains = data.get("collectors")
    if not isinstance(chains, dict):
        raise ValueError("Invalid collector registry")

    for chain, collectors in chains.items():
        if not isinstance(chain, str) or not VALID_NAME.fullmatch(chain):
            raise ValueError("Invalid blockchain name")

        if not isinstance(collectors, dict):
            raise ValueError("Invalid collector entries")

        identities = set()

        for name, record in collectors.items():
            if not isinstance(name, str) or not VALID_NAME.fullmatch(name):
                raise ValueError("Invalid collector name")

            if not isinstance(record, dict):
                raise ValueError("Invalid collector record")

            if record.get("status") not in VALID_STATES:
                raise ValueError("Invalid collector status")

            node_id = record.get("node_id")
            if node_id is not None:
                node_id = normalize_node_id(node_id)

                if node_id in identities:
                    raise ValueError("Duplicate node identity")

                identities.add(node_id)

    return data


def inspect_operation(
    ledger_root, audit_path, registration_dir, operation_id,
    *, include_assessment=False
):
    """Collect evidence without recovering or modifying registrations."""

    record = lookup(ledger_root, operation_id)

    if record is None:
        raise ValueError("Unknown operation ID")

    audit_path = Path(audit_path)

    chain = record["chain"]
    collector = record["collector"]

    # Local import avoids a circular dependency:
    # the snapshot module already imports the registry validator
    # from this module.
    from otb_admin_snapshot_dev import inspect_registration

    snapshot = inspect_registration(
        registration_dir, chain, collector
    )

    # Journal status and collector details come from the same
    # enrollment-locked snapshot.
    journal_present = snapshot["journal_present"]
    current_status = snapshot["collector_status"]
    last_action = snapshot["collector_last_action"]
    updated_at = snapshot["collector_updated_at"]

    # Missing audit evidence must be reported as missing,
    # not silently treated as proof of no transaction.
    events = []

    if audit_path.exists() or audit_path.is_symlink():
        with private_reader(audit_path) as handle:
            for line in handle:
                event = json.loads(line)

                if not isinstance(event, dict):
                    raise ValueError("Invalid audit event")

                if event.get("operation_id") != operation_id:
                    continue

                validate_id(event["operation_id"])

                if any(
                    event.get(key) != record[key]
                    for key in (
                        "administrator", "action",
                        "chain", "collector"
                    )
                ):
                    raise ValueError("Audit identity mismatch")

                if event.get("action") not in ACTIONS:
                    raise ValueError("Invalid audit action")

                if event.get("outcome") not in OUTCOMES:
                    raise ValueError("Invalid audit outcome")

                timestamp = event.get("timestamp")
                if not isinstance(timestamp, str) or not timestamp:
                    raise ValueError("Invalid audit timestamp")

                events.append({
                    "timestamp": timestamp,
                    "outcome": event["outcome"]
                })

    evidence = {
        "operation_id": operation_id,
        "administrator": record["administrator"],
        "action": record["action"],
        "chain": chain,
        "collector": collector,
        "ledger_state": record["state"],
        "audit_events": events,
        "journal_present": journal_present,
        "collector_status": current_status,
        "collector_last_action": last_action,
        "collector_updated_at": updated_at,
        "requires_manual_review": (
            record["state"] == "unresolved"
            or journal_present
        ),
        "automatic_resolution": False
    }

    if include_assessment:
        from otb_admin_assessment_dev import assess

        assessment = assess(
            evidence,
            snapshot["registration_consistent"]
        )

        # Preserve fail-closed behaviour when evidence is incomplete.
        if snapshot["inspection_complete"] is not (
            not snapshot["journal_present"]
        ):
            raise ValueError("Inconsistent snapshot completion state")

        evidence["assessment"] = assessment
        evidence["requires_manual_review"] = (
            assessment["requires_manual_review"]
        )

    return evidence
