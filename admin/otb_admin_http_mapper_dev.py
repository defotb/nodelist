#!/usr/bin/env python3
"""HTTP mapping for coordinated administrator actions — development."""

from otb_admin_operations_dev import (
    OperationConflict,
    OperationIdConflict
)
from otb_admin_audit_dev import validate_name


def map_result(result):
    """Return (HTTP status, JSON-compatible response dictionary)."""

    if not isinstance(result, dict):
        return 503, {
            "error": "Administrator transaction response unavailable",
            "verification_required": True
        }

    decision = result.get("decision")
    state = result.get("state")

    if decision == "new" and state == "success":
        collector = result.get("result")

        valid = (
            set(result) == {"decision", "state", "result"}
            and isinstance(collector, dict)
        )

        if valid:
            valid = (
                {"chain", "collector", "status"} <= set(collector)
                and set(collector) <= {
                    "chain", "collector", "status",
                    "node_id", "action"
                }
                and validate_name(collector.get("chain"))
                and validate_name(collector.get("collector"))
                and collector.get("status")
                    in {"enabled", "suspended", "revoked"}
            )

        if valid and "node_id" in collector:
            node_id = collector["node_id"]
            valid = (
                node_id is None
                or (
                    isinstance(node_id, str)
                    and 1 <= len(node_id) <= 256
                )
            )

        if valid and "action" in collector:
            valid = collector["action"] in {
                "admin_denied", "admin_revoked"
            }

        if not valid:
            return 503, {
                "error": "Administrator transaction result unavailable",
                "verification_required": True
            }

        return 200, {
            "status": "success",
            "collector": dict(collector),
            "verification_required": False
        }

    if decision == "duplicate":
        if state == "success":
            return 409, {
                "error": "Operation already completed",
                "verification_required": False,
                "duplicate": True
            }

        return 409, {
            "error": "Operation requires verification",
            "verification_required": True,
            "duplicate": True
        }

    if decision == "indeterminate":
        return 503, {
            "error": "Operation reservation requires verification",
            "verification_required": True
        }

    if decision == "new" and state == "unresolved":
        return 503, {
            "error": "Transaction result requires verification",
            "verification_required": True
        }

    return 503, {
        "error": "Administrator transaction state unavailable",
        "verification_required": True
    }


def map_exception(exc):
    """Translate trusted exception types without exposing internals."""

    if isinstance(exc, OperationIdConflict):
        return 409, {
            "error": "Operation ID conflicts with another request",
            "verification_required": True
        }

    if isinstance(exc, OperationConflict):
        return 409, {
            "error": "Collector has an unresolved operation",
            "verification_required": True
        }

    return 503, {
        "error": "Administrator operation unavailable",
        "verification_required": True
    }
