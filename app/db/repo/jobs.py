"""DB repo — the durable job queue's claim/lease/fencing protocol.

Twelve functions, and this is the whole public surface: `enqueue_job`,
`claim_job`, `complete_job`, `fail_job`, `release_leases`, `get_job`,
`count_open_jobs`, `get_run_queue_label`, `count_jobs_by_state`,
`oldest_due_pending_age_seconds`, `attempts_distribution`,
`list_dead_letter_jobs`. Every one takes
`conn: psycopg.Connection | None = None`
and opens with this package's `_conn_ctx(conn)` / `_nulltx()` convention, so a
caller that already owns a transaction (the retrigger route enqueuing a job
as part of a larger commit) can pass its own connection straight through with
zero new plumbing.

The `jobs` table carries transport identifiers only — no payload, no "next
payroll status" column. `payroll_runs.status` stays the sole business state
machine; nothing here may ever write to it. A worker that reads a claimed
`Job` calls back into `app.db.repo.claim_status` to advance the run — this
module has no opinion about what that call does.

Two independent guarantees this module provides, both proven by
`tests/test_repo_jobs_sql.py` (hermetic, SQL-shape) and
`tests/test_queue_durability.py` (live, behavioral):

1. **Exactly one claimant wins a contended job**, via a single UPDATE whose
   target row is selected by a `FOR UPDATE SKIP LOCKED` subquery — never a
   read-then-write pair, which would let two claimants both see the same
   unclaimed row.
2. **A worker whose lease has been reclaimed cannot silently corrupt the
   row.** Both `complete_job` and `fail_job` fence their write on
   `lease_token`; a worker that lost the race gets back `False`/`None` and
   must log and drop rather than retry or touch the run.
"""
from __future__ import annotations

import math
import uuid
from collections.abc import Sequence
from enum import StrEnum
from typing import Any

import psycopg
import psycopg.rows

from app.config import get_settings
from app.db.repo._shared import _conn_ctx, _nulltx
from app.db.repo.runs import _build_error_detail
from app.models.job import Job, JobKind, JobState
from app.pipeline.result import PipelineReason, PipelineStage

# Explicit column list for get_job's plain single-row read (no SELECT *),
# mirroring runs.py's RUN_COLS convention.
_JOB_COLS = (
    "id, kind, dedup_key, run_id, email_id, operator_resolution_id, event_id,"
    " business_id, priority, state,"
    " attempts, max_attempts, available_at, lease_token, leased_until,"
    " last_error, created_at, updated_at"
)

_SEND_OUTBOUND_MAX_ATTEMPTS = 8


class AdvanceSendJobOutcome(StrEnum):
    """The caller-visible result of advancing an existing delivery job."""

    ADVANCED = "advanced"
    MISSING = "missing"
    EXPIRED = "expired"
    NOT_PENDING = "not_pending"


def send_outbound_dedup_key(email_id: uuid.UUID) -> str:
    """Return the one durable identity for a frozen outbound email slot."""
    return f"send_outbound:{email_id}"


def enqueue_job(
    *,
    kind: JobKind,
    dedup_key: str,
    run_id: uuid.UUID | None = None,
    email_id: uuid.UUID | None = None,
    operator_resolution_id: uuid.UUID | None = None,
    event_id: uuid.UUID | None = None,
    business_id: uuid.UUID | None = None,
    max_attempts: int | None = None,
    available_in_seconds: float = 0.0,
    safe_last_error: str | None = None,
    conn: psycopg.Connection | None = None,
) -> uuid.UUID | None:
    """Insert a job row, idempotent on `dedup_key`. Returns the new id, or
    `None` when a row with this `dedup_key` already exists.

    A `None` return is NOT an error — `ON CONFLICT (dedup_key) DO NOTHING`
    means a caller who fires the same logical enqueue twice (a retry, a
    redelivered webhook) gets back "already enqueued" and moves on, exactly
    like `insert_inbound_email`'s duplicate-loser contract.

    `max_attempts` defaults to the configured queue knob when omitted, so the
    env-driven ceiling is actually live rather than shadowed by the column's
    own DEFAULT.

    Context identifiers are nullable at the column level because each kind
    owns a different exact subset. `ingest` owns only `event_id`; every other
    kind rejects it before SQL is issued.
    """
    kind_value = kind.value
    if kind_value not in {
        "ingest",
        "run_pipeline",
        "resume_reply",
        "operator_resume",
        "send_outbound",
    }:
        raise ValueError(f"enqueue_job: unsupported job kind {kind_value!r}")
    if kind_value == "ingest" and (
        event_id is None
        or dedup_key != f"ingest:{event_id}"
        or run_id is not None
        or email_id is not None
        or operator_resolution_id is not None
        or business_id is not None
    ):
        raise ValueError("enqueue_job: kind='ingest' requires event_id only")
    if kind_value == "run_pipeline" and (
        run_id is None
        or email_id is not None
        or operator_resolution_id is not None
        or event_id is not None
    ):
        raise ValueError(
            f"enqueue_job: kind={kind_value!r} requires run_id only. A "
            "run_pipeline job with no run would be claimed, dispatched, "
            "no-op through the run-status CAS, and recorded done — a job "
            "that processed no payroll, marked a success."
        )
    if kind_value == "resume_reply" and (
        run_id is None
        or email_id is None
        or operator_resolution_id is not None
        or event_id is not None
    ):
        raise ValueError(
            "enqueue_job: kind='resume_reply' requires run_id and email_id only"
        )
    if kind_value == "operator_resume" and (
        run_id is None
        or operator_resolution_id is None
        or email_id is not None
        or event_id is not None
    ):
        raise ValueError(
            "enqueue_job: kind='operator_resume' requires run_id and "
            "operator_resolution_id only"
        )
    if kind_value == "send_outbound" and (
        run_id is None
        or email_id is None
        or dedup_key != send_outbound_dedup_key(email_id)
        or operator_resolution_id is not None
        or event_id is not None
        or business_id is not None
    ):
        raise ValueError(
            "enqueue_job: kind='send_outbound' requires the run and frozen email only"
        )
    if (
        isinstance(available_in_seconds, bool)
        or not isinstance(available_in_seconds, (int, float))
        or not math.isfinite(available_in_seconds)
        or not 0 <= available_in_seconds <= 300
    ):
        raise ValueError("available_in_seconds must be a finite number from 0 to 300")
    if safe_last_error is not None:
        try:
            stage_value, reason_value = safe_last_error.split(":")
            PipelineStage(stage_value)
            PipelineReason(reason_value)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                "safe_last_error must be one bounded '<stage>:<reason>' diagnostic code"
            ) from exc
    if kind_value == "send_outbound":
        if max_attempts is not None and max_attempts != _SEND_OUTBOUND_MAX_ATTEMPTS:
            raise ValueError("send_outbound uses its fixed replay-attempt ladder")
        max_attempts = _SEND_OUTBOUND_MAX_ATTEMPTS
    else:
        max_attempts = (
            max_attempts if max_attempts is not None else get_settings().max_attempts
        )
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        row = c.execute(
            """
                INSERT INTO jobs (
                    kind, dedup_key, run_id, email_id, operator_resolution_id,
                    event_id, business_id, max_attempts, available_at, last_error
                )
                VALUES (
                    %(kind)s, %(dedup_key)s, %(run_id)s, %(email_id)s,
                    %(operator_resolution_id)s, %(event_id)s, %(business_id)s,
                    %(max_attempts)s,
                    now() + (%(available_in_seconds)s || ' seconds')::interval,
                    %(safe_last_error)s
                )
                ON CONFLICT (dedup_key) DO NOTHING
                RETURNING id
                """,
            {
                "kind": kind_value,
                "dedup_key": dedup_key,
                "run_id": str(run_id) if run_id else None,
                "email_id": str(email_id) if email_id else None,
                "operator_resolution_id": (
                    str(operator_resolution_id) if operator_resolution_id else None
                ),
                "event_id": str(event_id) if event_id else None,
                "business_id": str(business_id) if business_id else None,
                "max_attempts": max_attempts,
                "available_in_seconds": float(available_in_seconds),
                "safe_last_error": safe_last_error,
            },
        ).fetchone()
    if row is None:
        return None
    return uuid.UUID(str(row[0]))


def advance_existing_send_job_due_now(
    run_id: uuid.UUID,
    email_id: uuid.UUID,
    *,
    conn: psycopg.Connection | None = None,
) -> AdvanceSendJobOutcome:
    """Advance one eligible pending delivery job within the caller transaction.

    This operation only moves an existing job's due time.  The caller decides
    whether to wake a worker after committing when the returned outcome is
    ``ADVANCED``.
    """
    if conn is None:
        raise ValueError("advance_existing_send_job_due_now requires a caller-owned transaction")

    job = conn.execute(
        """
        SELECT id, state
          FROM jobs
         WHERE kind = 'send_outbound'
           AND run_id = %s
           AND email_id = %s
         FOR UPDATE
        """,
        (str(run_id), str(email_id)),
    ).fetchone()
    if job is None:
        return AdvanceSendJobOutcome.MISSING
    if job[1] != JobState.PENDING:
        return AdvanceSendJobOutcome.NOT_PENDING

    reservation = conn.execute(
        """
        SELECT snapshot.reserved_at + interval '20 hours' > now()
          FROM outbound_email_snapshots AS snapshot
          JOIN email_messages AS message ON message.id = snapshot.email_id
         WHERE message.id = %s
           AND message.run_id = %s
           AND message.direction = 'outbound'
           AND message.purpose = 'confirmation'
           AND message.send_state = 'reserved'
         FOR UPDATE OF snapshot, message
        """,
        (str(email_id), str(run_id)),
    ).fetchone()
    if reservation is None:
        return AdvanceSendJobOutcome.MISSING
    if not bool(reservation[0]):
        return AdvanceSendJobOutcome.EXPIRED

    review = conn.execute(
        """
        SELECT id
          FROM payroll_runs
         WHERE id = %s
           AND status = 'needs_operator'
           AND error_reason = 'DeliveryReview'
         FOR UPDATE
        """,
        (str(run_id),),
    ).fetchone()
    if review is None:
        return AdvanceSendJobOutcome.MISSING

    updated = conn.execute(
        """
        UPDATE jobs
           SET available_at = now(), updated_at = now()
         WHERE id = %s AND state = 'pending'
        RETURNING id
        """,
        (str(job[0]),),
    ).fetchone()
    return (
        AdvanceSendJobOutcome.ADVANCED
        if updated is not None
        else AdvanceSendJobOutcome.NOT_PENDING
    )


def advance_existing_clarification_delivery_review_job_due_now(
    run_id: uuid.UUID,
    email_id: uuid.UUID,
    *,
    conn: psycopg.Connection | None = None,
) -> AdvanceSendJobOutcome:
    """Reopen one existing clarification delivery job after operator review.

    The caller owns the transaction and wakes the queue only after commit.  The
    job and its immutable reservation are locked in that order so this explicit
    action cannot deadlock with delivery settlement or mint a replacement slot.
    """
    if conn is None:
        raise ValueError(
            "advance_existing_clarification_delivery_review_job_due_now "
            "requires a caller-owned transaction"
        )

    job = conn.execute(
        """
        SELECT id, state
          FROM jobs
         WHERE kind = 'send_outbound'
           AND run_id = %s
           AND email_id = %s
         FOR UPDATE
        """,
        (str(run_id), str(email_id)),
    ).fetchone()
    if job is None:
        return AdvanceSendJobOutcome.MISSING
    if job[1] != JobState.PENDING:
        return AdvanceSendJobOutcome.NOT_PENDING

    reservation = conn.execute(
        """
        SELECT snapshot.reserved_at + interval '20 hours' > now(),
               message.purpose, message.send_state
          FROM outbound_email_snapshots AS snapshot
          JOIN email_messages AS message ON message.id = snapshot.email_id
         WHERE message.id = %s
           AND message.run_id = %s
           AND message.direction = 'outbound'
         FOR UPDATE OF snapshot, message
        """,
        (str(email_id), str(run_id)),
    ).fetchone()
    if reservation is None:
        return AdvanceSendJobOutcome.MISSING
    if not bool(reservation[0]):
        return AdvanceSendJobOutcome.EXPIRED
    if reservation[1] not in {
        "clarification",
        "clarification_field_regression",
    } or reservation[2] != "reserved":
        return AdvanceSendJobOutcome.MISSING

    review = conn.execute(
        """
        SELECT status, error_reason
          FROM payroll_runs
         WHERE id = %s
         FOR UPDATE
        """,
        (str(run_id),),
    ).fetchone()
    if review is None or review[0] != "needs_operator" or review[1] != (
        "ClarificationDeliveryReview"
    ):
        return AdvanceSendJobOutcome.MISSING

    updated = conn.execute(
        """
        UPDATE jobs
           SET available_at = now(), updated_at = now()
         WHERE id = %s AND state = 'pending'
        RETURNING id
        """,
        (str(job[0]),),
    ).fetchone()
    return (
        AdvanceSendJobOutcome.ADVANCED
        if updated is not None
        else AdvanceSendJobOutcome.NOT_PENDING
    )


def claim_job(
    *,
    lease_seconds: int | None = None,
    conn: psycopg.Connection | None = None,
) -> Job | None:
    """The canonical claim: ONE statement, ONE implicit transaction, commits
    before any real work — no session state survives it, so it is safe under
    Supavisor transaction-mode pooling (no LISTEN/NOTIFY, no session advisory
    locks, both silently no-ops on that pooling mode).

    Three properties that must never be lost from this SQL:

    - `FOR UPDATE SKIP LOCKED` lives in the SUBQUERY, and the outer UPDATE
      re-targets by `id`. A bare `UPDATE ... LIMIT 1` is not valid Postgres,
      and `FOR UPDATE` on the outer statement gives no row-skipping at all —
      two concurrent claimants would both block on the same row instead of
      the second one moving on to a different one.
    - The WHERE includes `OR (c.state = 'leased' AND c.leased_until < now())`
      — reclaiming an expired lease. Without this clause a job whose worker
      died holding the lease stays leased forever, which is the exact
      failure this queue exists to eliminate.
    - `attempts = j.attempts + 1` increments AT CLAIM, not at failure. That
      is what bounds a crash loop: a worker SIGKILLed before it can report
      anything still burns an attempt, so a poison job eventually dead-
      letters instead of looping forever. The completion path must never
      also increment.

    `RETURNING` yields EXACTLY the nine columns `Job` declares, in the same
    order. `tests/test_repo_jobs_sql.py`
    machine-checks this bijection so it cannot silently drift.
    """
    lease_seconds = (
        lease_seconds if lease_seconds is not None else get_settings().lease_seconds
    )
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        row = c.execute(
            """
                UPDATE jobs j
                   SET state        = 'leased',
                       lease_token  = gen_random_uuid(),
                       leased_until = now() + (%(lease_seconds)s || ' seconds')::interval,
                       attempts     = j.attempts + 1,
                       updated_at   = now()
                 WHERE j.id = (
                       SELECT c.id
                         FROM jobs c
                        WHERE c.attempts < c.max_attempts
                          AND (
                                (c.state = 'pending' AND c.available_at <= now())
                             OR (c.state = 'leased'  AND c.leased_until <  now())
                              )
                        ORDER BY c.priority, c.available_at
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                 )
                RETURNING j.id, j.kind, j.run_id, j.email_id, j.operator_resolution_id,
                          j.event_id, j.attempts, j.max_attempts, j.lease_token
                """,
            {"lease_seconds": lease_seconds},
        ).fetchone()
    if row is None:
        return None
    return Job(
        id=uuid.UUID(str(row[0])),
        kind=JobKind(row[1]),
        run_id=uuid.UUID(str(row[2])) if row[2] is not None else None,
        email_id=uuid.UUID(str(row[3])) if row[3] is not None else None,
        operator_resolution_id=(
            uuid.UUID(str(row[4])) if row[4] is not None else None
        ),
        event_id=uuid.UUID(str(row[5])) if row[5] is not None else None,
        attempts=int(row[6]),
        max_attempts=int(row[7]),
        lease_token=uuid.UUID(str(row[8])),
    )


def complete_job(
    job_id: uuid.UUID,
    lease_token: uuid.UUID,
    conn: psycopg.Connection | None = None,
) -> bool:
    """Fenced completion. `False` means the lease was stolen — this worker
    is a zombie and must NOT retry, NOT error the run, NOT re-enqueue. It
    logs and drops, cleanly. Identical contract to `claim_status` returning
    `False`: the repo already has the "lost the race, drop cleanly" idiom in
    several places; this is the same idiom applied to the transport row.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        row = c.execute(
            "UPDATE jobs SET state = 'done', lease_token = NULL,"
            " leased_until = NULL, updated_at = now()"
            " WHERE id = %s AND state = 'leased' AND lease_token = %s"
            " RETURNING id",
            (str(job_id), str(lease_token)),
        ).fetchone()
    return row is not None


def fail_job(
    job_id: uuid.UUID,
    lease_token: uuid.UUID,
    *,
    error: BaseException | str,
    backoff_seconds: float,
    conn: psycopg.Connection | None = None,
) -> JobState | None:
    """Fenced failure/retry — the SAME `lease_token` predicate `complete_job`
    uses. This is the fence people forget (guard `complete`, leave `fail`
    open); a zombie worker's failure write must be rejected exactly like its
    completion write.

    `state` moves to `dead` once `attempts >= max_attempts`, else back to
    `pending` with `available_at` pushed out by `backoff_seconds` (computed
    by the caller — jitter and backoff curve are not this module's concern).
    Returns the row's new `JobState`, or `None` when fenced out.

    `last_error` is scrubbed INSIDE this function via this package's existing
    scrub helper — the same one `record_run_error` uses — so no caller ever
    has to remember to scrub a raw exception string before it reaches a
    column that could otherwise leak an employee name or prompt text.
    """
    exc: Exception = error if isinstance(error, Exception) else RuntimeError(str(error))
    detail = _build_error_detail("queue_job_failure", exc)
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        row = c.execute(
            """
                UPDATE jobs
                   SET state = CASE WHEN attempts >= max_attempts THEN 'dead' ELSE 'pending' END,
                       available_at = now() + (%(backoff_seconds)s || ' seconds')::interval,
                       last_error   = %(detail)s,
                       lease_token  = NULL, leased_until = NULL, updated_at = now()
                 WHERE id = %(id)s AND state = 'leased' AND lease_token = %(token)s
                RETURNING state
                """,
            {
                "backoff_seconds": backoff_seconds,
                "detail": detail,
                "id": str(job_id),
                "token": str(lease_token),
            },
        ).fetchone()
    if row is None:
        return None
    return JobState(row[0])


def release_leases(
    lease_tokens: Sequence[uuid.UUID],
    conn: psycopg.Connection | None = None,
) -> int:
    """The shutdown release: flip every row holding one of `lease_tokens`
    back to `pending`, immediately claimable again. An empty sequence is a
    no-op that issues no statement at all — an empty `ANY(%s)` is
    semantically fine in Postgres, but there is no reason to pay for a round
    trip that can only ever affect zero rows.
    """
    if not lease_tokens:
        return 0
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        rows = c.execute(
            "UPDATE jobs SET state = 'pending', available_at = now(),"
            " lease_token = NULL, leased_until = NULL, updated_at = now()"
            " WHERE lease_token = ANY(%s) AND state = 'leased'"
            " RETURNING id",
            ([str(t) for t in lease_tokens],),
        ).fetchall()
    return len(rows)


def get_job(
    job_id: uuid.UUID, conn: psycopg.Connection | None = None
) -> dict[str, Any] | None:
    """A plain single-row read of a job, used by the durability proofs and
    (later) an ops view. Explicit column list + dict_row, mirroring
    `load_run`'s shape — never `SELECT *`.
    """
    sql = "SELECT " + _JOB_COLS + " FROM jobs WHERE id = %s"
    with _conn_ctx(conn) as (c, _owns), c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, (str(job_id),))
        return cur.fetchone()


def count_open_jobs(conn: psycopg.Connection | None = None) -> int:
    """The point-in-time backlog count: rows in `state IN ('pending',
    'leased')`. Used by the pump route's `queue_depth` response field and,
    later, a queue-depth panel on the operator dashboard.

    Deliberately backlog-scoped (total outstanding), NOT "claimable right
    now" — it does not filter on `available_at <= now()` the way
    `claim_job`'s subquery does. The useful ops signal here is total
    outstanding depth, not the instantaneously-claimable subset.

    This is a plain read, no fencing, no mutation — a
    `SELECT count(*)` behind the same `_conn_ctx` convention every other
    function in this module uses.
    """
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            "SELECT count(*) FROM jobs WHERE state IN ('pending', 'leased')", ()
        ).fetchone()
    return int(row[0]) if row else 0


def get_run_queue_label(
    run_id: uuid.UUID, conn: psycopg.Connection | None = None
) -> str | None:
    """Return the fixed browser-safe label for a run's open queue work.

    The aggregate deliberately projects no job identifier, counter, timestamp,
    payload, or diagnostic.  A leased row wins over all pending rows; otherwise
    immediately due work wins over delayed work.  ``None`` means no pending or
    leased job remains.
    """
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            """
                SELECT CASE
                         WHEN bool_or(state = 'leased')
                           THEN 'Running'
                         WHEN bool_or(state = 'pending' AND available_at <= now())
                           THEN 'Queued'
                         WHEN bool_or(state = 'pending')
                           THEN 'Retry queued'
                       END AS queue_label
                  FROM jobs
                 WHERE run_id = %s
                   AND state IN ('pending', 'leased')
                """,
            (str(run_id),),
        ).fetchone()
    if row is None or row[0] not in {"Running", "Queued", "Retry queued"}:
        return None
    return str(row[0])


# ---------------------------------------------------------------------------
# Queue-metric reads — the four `/ops` panels. Every one of these is a plain
# SELECT with no mutation and no fencing, the same side-effect-free-read
# contract `count_open_jobs` and `get_run_queue_label` already carry.
# ---------------------------------------------------------------------------


def count_jobs_by_state(conn: psycopg.Connection | None = None) -> dict[str, int]:
    """Return the open backlog split by state: `{"pending": N, "leased": M}`.

    Side-effect-free read: a `GROUP BY state` count, no mutation. Both keys
    are ALWAYS present with an explicit `0` — never a missing key — so a
    caller never has to special-case "no leased jobs right now" as a
    KeyError. The depth is deliberately SPLIT rather than a single opaque
    total, because "5 pending" and "5 leased" are different operational
    signals (a stalled worker vs. a genuine backlog). `count_open_jobs` stays
    untouched: the pump route's `queue_depth` response field already depends
    on its single-int shape, and this function is additive, not a
    replacement.
    """
    with _conn_ctx(conn) as (c, _owns):
        rows = c.execute(
            "SELECT state, count(*) FROM jobs"
            " WHERE state IN ('pending', 'leased') GROUP BY state",
            (),
        ).fetchall()
    counts = {"pending": 0, "leased": 0}
    for state, n in rows:
        counts[str(state)] = int(n)
    return counts


def oldest_due_pending_age_seconds(
    conn: psycopg.Connection | None = None,
) -> float | None:
    """Return the age, in seconds, of the oldest currently-due pending job.

    Side-effect-free read. `None` when no pending job is due right now (an
    empty backlog, or every pending job is still backed off). Otherwise a
    non-negative `float` — psycopg maps Postgres `numeric` to `Decimal`, and
    this function converts explicitly with `float(...)` before returning so
    the annotated return type holds under strict mypy and the `/ops`
    template's formatting filter receives the type it was written for.

    Measured from `available_at`, NEVER `created_at`. A job deliberately
    backed off by the retry ladder (`fail_job`'s `available_at = now() +
    backoff`) is not late — it is exactly where the backoff curve put it.
    Measuring from `created_at` would report scheduled backoff as pump
    failure, which is the wrong signal for an operator asking "how long has
    something been ready and unclaimed", not "how old is the row".
    """
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            "SELECT extract(epoch FROM (now() - min(available_at)))"
            " FROM jobs WHERE state = 'pending' AND available_at <= now()",
            (),
        ).fetchone()
    if row is None or row[0] is None:
        return None
    return float(row[0])


def attempts_distribution(
    conn: psycopg.Connection | None = None,
) -> list[tuple[int, int]]:
    """Return `[(attempts, count), ...]` for open jobs, ordered ascending.

    Side-effect-free read. Scoped to `state IN ('pending', 'leased')` only —
    a dead job's attempts are already shown, per job, in the dead-letter list
    (`list_dead_letter_jobs`), and folding them into this distribution would
    double-count the same failure in two `/ops` panels. Rendered against
    `MAX_ATTEMPTS`, this lets an operator see at a glance how much of the
    open backlog is close to exhausting its retry ladder.
    """
    with _conn_ctx(conn) as (c, _owns):
        rows = c.execute(
            "SELECT attempts, count(*) FROM jobs"
            " WHERE state IN ('pending', 'leased')"
            " GROUP BY attempts ORDER BY attempts",
            (),
        ).fetchall()
    return [(int(attempts), int(n)) for attempts, n in rows]


def list_dead_letter_jobs(
    limit: int = 50, conn: psycopg.Connection | None = None
) -> list[dict[str, Any]]:
    """Return the newest `limit` dead-lettered jobs, bounded and PII-safe.

    Side-effect-free read, read through
    `c.cursor(row_factory=psycopg.rows.dict_row)` the way `get_job` is —
    never `SELECT *`. Ordered `updated_at DESC` (newest dead-letter first)
    and bounded by `limit` (default 50), so this can never hand an
    unauthenticated `/ops` caller an unbounded result set.

    Projects EXACTLY these seven columns: `id`, `kind`, `run_id`, `attempts`,
    `max_attempts`, `last_error`, `updated_at`. No payload, no lease token, no
    dedup key, no other diagnostic — `last_error` is the one diagnostic field
    allowed to cross the browser boundary, because it is already PII-scrubbed
    and length-bounded at both of its write sites (`fail_job` here routes it
    through `_build_error_detail`, the same scrub helper `record_run_error`
    uses; the settlement path in `job_settlement.py` writes a bounded
    diagnostic code, never raw exception text) — mirroring
    `get_run_queue_label`'s deliberate projection discipline.
    """
    sql = (
        "SELECT id, kind, run_id, attempts, max_attempts, last_error, updated_at"
        " FROM jobs WHERE state = 'dead' ORDER BY updated_at DESC LIMIT %s"
    )
    with _conn_ctx(conn) as (c, _owns), c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, (limit,))
        return cur.fetchall()
