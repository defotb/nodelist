#!/usr/bin/env python3
"""Read-only administrator reconciliation assessment — development."""


def assess(evidence, registration_consistent):
    """Classify evidence without resolving an operation."""

    if not isinstance(evidence, dict):
        raise ValueError("Invalid reconciliation evidence")

    if (
        registration_consistent is not None
        and type(registration_consistent) is not bool
    ):
        raise ValueError("Invalid consistency result")

    state = evidence.get("ledger_state")
    journal = evidence.get("journal_present")
    events = evidence.get("audit_events")

    if state not in ("success", "rejected", "unresolved"):
        raise ValueError("Invalid ledger state")

    if type(journal) is not bool or not isinstance(events, list):
        raise ValueError("Invalid reconciliation evidence")

    if registration_consistent is None and not journal:
        raise ValueError("Missing consistency result without journal")

    outcomes = []

    for event in events:
        if (
            not isinstance(event, dict)
            or event.get("outcome")
                not in ("attempt", "success", "rejected", "error")
        ):
            raise ValueError("Invalid audit evidence")

        outcomes.append(event["outcome"])

    if journal:
        classification = "recovery_review_required"
        reason = "Unfinished transaction journal"

    elif not registration_consistent:
        classification = "consistency_review_required"
        reason = "Registration databases are inconsistent"

    elif state == "unresolved":
        classification = "manual_review_required"
        reason = "Operation ledger remains unresolved"

    elif state == "success":
        classification = "finalized_success_recorded"
        reason = "Ledger records successful finalization"

    else:
        classification = "finalized_rejection_recorded"
        reason = "Ledger records rejected finalization"

    return {
        "classification": classification,
        "reason": reason,
        "ledger_state": state,
        "registration_consistent": registration_consistent,
        "journal_present": journal,
        "audit_outcomes": outcomes,
        "requires_manual_review": (
            journal
            or registration_consistent is not True
            or state == "unresolved"
        ),
        "automatic_resolution": False,
        "collector_unlock_allowed": False
    }
