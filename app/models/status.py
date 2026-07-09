"""RunStatus StrEnum — the single source of truth for all 11 pipeline status values.

Plan 02 mirrors these values verbatim in a CHECK constraint on payroll_runs.status.
A CI test asserts the SQL CHECK list equals this enum's members so drift fails fast.
"""
import enum


class RunStatus(enum.StrEnum):
    """Eleven-state lifecycle for a payroll run.

    D-02: modeled as TEXT + CHECK in Postgres (not a native ENUM) so adding a value
    is a one-line CHECK edit that can run inside a transaction.
    D-03: this Python class is the canonical source; the SQL mirrors it.
    """

    RECEIVED = "received"
    EXTRACTING = "extracting"
    AWAITING_REPLY = "awaiting_reply"
    COMPUTED = "computed"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    SENT = "sent"
    RECONCILED = "reconciled"
    REJECTED = "rejected"
    ERROR = "error"
    # Phase 11 (D-11-06): a run whose clarification round counter hit the cap
    # (MAX_CLARIFICATION_ROUNDS, D-11-07) with no resolvable reply. Terminal for
    # every automated path — NOT in sweep_stranded_runs' scope, NOT in the
    # retrigger stale_statuses list, and NOT polled by IN_FLIGHT_STATUSES (it is
    # a settled gate state like awaiting_approval, waiting on a HUMAN operator,
    # not a dead background task). Only an explicit operator resolve+resume
    # action (or reject) moves a run out of this state.
    NEEDS_OPERATOR = "needs_operator"
