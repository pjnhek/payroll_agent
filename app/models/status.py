"""RunStatus StrEnum — the single source of truth for all 10 pipeline status values.

Plan 02 mirrors these values verbatim in a CHECK constraint on payroll_runs.status.
A CI test asserts the SQL CHECK list equals this enum's members so drift fails fast.
"""
import enum


class RunStatus(str, enum.Enum):
    """Ten-state lifecycle for a payroll run.

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
