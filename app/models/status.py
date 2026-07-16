"""RunStatus — the single source of truth for every pipeline status value.

The status column IS the state machine: it is what drives the pipeline, holds the
human-in-the-loop pause, and survives a restart. These values are mirrored verbatim in a
CHECK constraint on payroll_runs.status, and a CI test asserts the SQL CHECK list equals
this enum's members, so any drift between the two fails fast instead of admitting a status
the code has never heard of.
"""
import enum


class RunStatus(enum.StrEnum):
    """The lifecycle states a payroll run can occupy.

    This Python class is CANONICAL; the SQL mirrors it. In Postgres the column is modeled
    as TEXT + CHECK rather than a native ENUM, so adding a value is a one-line CHECK edit
    that runs inside a transaction (altering a native ENUM cannot).
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
    # A run whose clarification round counter hit MAX_CLARIFICATION_ROUNDS with no
    # resolvable reply: the system asked as many times as it is allowed to and still cannot
    # proceed without a human.
    #
    # Terminal for every automated path. It is deliberately excluded from the
    # retrigger stale_statuses list and IN_FLIGHT_STATUSES because it is a settled
    # gate state (like awaiting_approval) waiting on a human operator. Only an
    # explicit operator resolve+resume (or a reject) moves a run out of this state.
    NEEDS_OPERATOR = "needs_operator"
