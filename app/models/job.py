"""JobKind / JobState — the transport vocabulary for the durable job queue.

The queue's vocabulary is transport state; `payroll_runs.status` (RunStatus, in
app/models/status.py) is the SOLE business state machine. INVARIANT J-1: a `jobs`
row may never encode "what payroll status comes next" — there is no payload
column, no status column, and (see `Job` below) no field for one. This module's
own drift test, `tests/test_job_kind_drift.py`, pins two things CI-side: (1)
`JobKind` values never collide with `RunStatus` values, and (2)
`set(JobKind) == set(dispatch.HANDLERS)` — set EQUALITY, not a superset check.

These Python classes are CANONICAL; `app/db/schema.sql`'s `jobs.kind` and
`jobs.state` CHECK constraints mirror them verbatim, the same "Python is
canonical, SQL CHECK mirrors it" convention `app/models/status.py` already
establishes for `RunStatus`. In Postgres both columns are TEXT + CHECK rather
than a native ENUM, so widening either is a one-line CHECK edit that runs
inside a transaction (`ALTER TYPE ... ADD VALUE` cannot).
"""
from __future__ import annotations

import dataclasses
import enum
import uuid


class JobKind(enum.StrEnum):
    """The kind of work a `jobs` row represents — a FUNCTION NAME, never a status.

    Exactly ONE member this phase: `RUN_PIPELINE`. The full design (see
    `.planning/research/ARCHITECTURE.md` §4) eventually names four kinds
    (`ingest`, `run_pipeline`, `resume_reply`, `operator_resume`), but Phase 16
    ships a real handler for only one of them. `app/queue/dispatch.py`'s CI
    guard asserts `set(JobKind) == set(HANDLERS)` — set EQUALITY. Pre-declaring
    the other three kinds now would make that guard permanently unsatisfiable
    (three kinds with no registered handler), and the only way to "fix" an
    unsatisfiable `==` guard is to weaken it to `⊇`, which would silently
    permit exactly the phantom-kind-with-no-handler the guard exists to catch.
    Widen this enum deliberately in a later phase, in the SAME commit that adds
    the new kind's handler — never ahead of it.
    """

    RUN_PIPELINE = "run_pipeline"


class JobState(enum.StrEnum):
    """The four states the canonical claim/complete/fail SQL moves a job between.

    Collision constraint (ROADMAP criterion #5): no `JobState` (or `JobKind`)
    value may ever equal a `RunStatus` value (app/models/status.py). The
    queue's vocabulary is transport state; the run's vocabulary is business
    state — a job row that could name a payroll status is INVARIANT J-1
    violated at the type level. Concretely: never introduce a member whose
    value is a string `RunStatus` already owns (e.g. `RunStatus.ERROR ==
    "error"` — no `JobState`/`JobKind` member may ever be `"error"`). These
    four values are collision-free against all 11 current `RunStatus` members;
    `tests/test_job_kind_drift.py` pins that fact so a future addition to
    either enum cannot silently reintroduce a collision.
    """

    PENDING = "pending"
    LEASED = "leased"
    DONE = "done"
    DEAD = "dead"


@dataclasses.dataclass(frozen=True)
class Job:
    """A transport record — mirrors EXACTLY what the claim SQL's `RETURNING` yields.

    SIX fields, in this order: `id`, `kind`, `run_id`, `attempts`,
    `max_attempts`, `lease_token`. Nothing else — no `email_id`, no payload, no
    next-state field. `jobs.email_id` still exists as a table COLUMN (reserved
    for Phase 19), but no field for it lives here: nothing in Phase 16 reads
    it, and a dataclass field with no consumer is a lie about the contract this
    docstring states — that `Job` mirrors `RETURNING`.

    This bijection is machine-enforced, not left to care: plan 16-04's
    `tests/test_repo_jobs_sql.py` parses `claim_job`'s `RETURNING` clause and
    asserts every returned column maps EXACTLY ONCE onto a `Job` field, and
    every `Job` field has EXACTLY ONE returned column — set equality, both
    directions.
    """

    id: uuid.UUID
    kind: JobKind
    run_id: uuid.UUID | None
    attempts: int
    max_attempts: int
    lease_token: uuid.UUID
