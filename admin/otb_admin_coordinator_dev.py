#!/usr/bin/env python3
"""Isolated administrator transaction coordinator — development only."""

from otb_admin_audit_dev import append_event
from otb_admin_operations_dev import claim, finish


def execute(
    ledger_root,
    audit_path,
    operation_id,
    administrator,
    action,
    chain,
    collector,
    transaction,
    audit_writer=append_event
):
    """Execute a newly reserved operation at most once.

    An unresolved outcome must be investigated, never retried
    automatically.
    """

    # Claim first: duplicate IDs and collector conflicts cannot
    # reach the transaction function.
    try:
        decision, record = claim(
            ledger_root, operation_id, administrator,
            action, chain, collector
        )
    except OSError:
        # A failed directory sync may occur after the
        # reservation has already been atomically replaced.
        # No collector transaction has been started.
        return {
            "decision": "indeterminate",
            "state": "unknown",
            "reason": "reservation_requires_verification"
        }

    if decision == "duplicate":
        return {
            "decision": "duplicate",
            "state": record["state"]
        }

    # Once claimed, any failure leaves a durable reservation.
    try:
        audit_writer(
            audit_path, administrator, action,
            chain, collector, "attempt",
            operation_id=operation_id
        )
    except Exception:
        return {
            "decision": "new",
            "state": "unresolved",
            "reason": "audit_attempt_unavailable"
        }

    try:
        result = transaction()
    except Exception:
        # The transaction could have committed before failing.
        # Never classify this as a proven rollback.
        try:
            audit_writer(
                audit_path, administrator, action,
                chain, collector, "error",
                operation_id=operation_id
            )
        except Exception:
            pass

        return {
            "decision": "new",
            "state": "unresolved",
            "reason": "transaction_requires_verification"
        }

    # A completed transaction still needs a durable audit
    # outcome before finalizing its ledger record.
    try:
        audit_writer(
            audit_path, administrator, action,
            chain, collector, "success",
            operation_id=operation_id
        )
    except Exception:
        return {
            "decision": "new",
            "state": "unresolved",
            "reason": "audit_outcome_unavailable"
        }

    try:
        finish(ledger_root, operation_id, "success")
    except Exception:
        return {
            "decision": "new",
            "state": "unresolved",
            "reason": "ledger_finalization_unavailable"
        }

    return {
        "decision": "new",
        "state": "success",
        "result": result
    }
