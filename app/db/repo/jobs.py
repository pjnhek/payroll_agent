"""DB repo — the durable job queue's claim/lease/fencing protocol.

Seven functions, and this is the whole public surface: `enqueue_job`,
`claim_job`, `complete_job`, `fail_job`, `release_leases`, `get_job`,
`count_open_jobs`. Every one takes `conn: psycopg.Connection | None = None`
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

import uuid
from collections.abc import Sequence
from typing import Any

import psycopg
import psycopg.rows

from app.config import get_settings
from app.db.repo._shared import _conn_ctx, _nulltx
from app.db.repo.runs import _build_error_detail
from app.models.job import Job, JobKind, JobState

# Explicit column list for get_job's plain single-row read (no SELECT *),
# mirroring runs.py's RUN_COLS convention.
_JOB_COLS = (
    "id, kind, dedup_key, run_id, email_id, business_id, priority, state,"
    " attempts, max_attempts, available_at, lease_token, leased_until,"
    " last_error, created_at, updated_at"
)


def enqueue_job(
    *,
    kind: JobKind,
    dedup_key: str,
    run_id: uuid.UUID | None = None,
    email_id: uuid.UUID | None = None,
    business_id: uuid.UUID | None = None,
    max_attempts: int | None = None,
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

    `run_id`/`email_id`/`business_id` are all nullable at the column level —
    a future ingest kind will genuinely have no run yet — but a
    `run_pipeline` job with no run is unrepresentable, checked BEFORE any SQL
    is issued.
    """
    if kind is JobKind.RUN_PIPELINE and run_id is None:
        raise ValueError(
            f"enqueue_job: kind={kind.value!r} requires a run_id. A "
            "run_pipeline job with no run would be claimed, dispatched, "
            "no-op through the run-status CAS, and recorded done — a job "
            "that processed no payroll, marked a success."
        )
    max_attempts = (
        max_attempts if max_attempts is not None else get_settings().max_attempts
    )
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        row = c.execute(
            """
                INSERT INTO jobs (kind, dedup_key, run_id, email_id, business_id, max_attempts)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (dedup_key) DO NOTHING
                RETURNING id
                """,
            (
                kind.value,
                dedup_key,
                str(run_id) if run_id else None,
                str(email_id) if email_id else None,
                str(business_id) if business_id else None,
                max_attempts,
            ),
        ).fetchone()
    if row is None:
        return None
    return uuid.UUID(str(row[0]))


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

    `RETURNING` yields EXACTLY the six columns `Job` declares, in the same
    order — no `email_id`, no `event_id`. `tests/test_repo_jobs_sql.py`
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
                RETURNING j.id, j.kind, j.run_id, j.attempts, j.max_attempts, j.lease_token
                """,
            {"lease_seconds": lease_seconds},
        ).fetchone()
    if row is None:
        return None
    return Job(
        id=uuid.UUID(str(row[0])),
        kind=JobKind(row[1]),
        run_id=uuid.UUID(str(row[2])) if row[2] is not None else None,
        attempts=int(row[3]),
        max_attempts=int(row[4]),
        lease_token=uuid.UUID(str(row[5])),
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
