#!/usr/bin/env python3
"""Development-only coordinated administrator action dispatcher."""

from otb_admin_coordinator_dev import execute
from otb_admin_http_mapper_dev import map_result, map_exception
from otb_admin_operations_dev import validate_id
from otb_admin_audit_dev import ACTIONS, validate_name


def dispatch(
    ledger_root,
    audit_path,
    operation_id,
    administrator,
    action,
    chain,
    collector,
    transaction
):
    """Return (HTTP status, response body); never retry transactions."""

    try:
        validate_id(operation_id)
    except ValueError:
        return 400, {
            "error": "Invalid operation ID",
            "verification_required": False
        }

    if (
        not validate_name(administrator)
        or not validate_name(chain)
        or not validate_name(collector)
        or action not in ACTIONS
        or not callable(transaction)
    ):
        return 400, {
            "error": "Invalid administrator action",
            "verification_required": False
        }

    try:
        result = execute(
            ledger_root,
            audit_path,
            operation_id,
            administrator,
            action,
            chain,
            collector,
            transaction
        )
    except Exception as exc:
        return map_exception(exc)

    return map_result(result)
