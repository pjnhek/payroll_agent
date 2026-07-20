"""Live-Postgres behavioural proof of the D-13 unaccounted-error alarm predicate
(`app.db.repo.list_unaccounted_error_runs`).

The transaction-timestamp EQUALITY this predicate depends on is a real-Postgres
fact — `now()` is evaluated once, at transaction start, and held stable for
every statement inside that transaction. A mocked/hermetic test cannot observe
that; only a real database can. This module is therefore `integration` +
`queueproof` (mirrors `tests/test_queue_durability.py`'s own module-level
pytestmark), NOT `proof` — it is not one of the four durability proofs plan
21-09 inventories, and tagging it `proof` would break that exactly-once
inventory.

Eight tests, one per behaviour named in 21-02-PLAN.md's <behavior> block:
three legitimate settlement paths (must be SILENT) and five unaccounted
shapes (must FIRE) — including the two regression tests the cross-AI review
added: the late-no-op-job false negative (equality vs `>=`) and the
`settle_background_terminal()` classification. Every test asserts on the
returned run id specifically, never merely on row count, so a test cannot
pass by returning the wrong run.
"""
from __future__ import annotations

import time
import uuid

import pytest

from app.db import repo
from app.db.repo.job_settlement import SettlementOutcome
from app.models.job import JobKind
from app.models.status import RunStatus
from app.pipeline.result import (
    PipelineOutcome,
    PipelineReason,
    PipelineResult,
    PipelineStage,
)

# Mirrors tests/test_queue_durability.py's own module-level pytestmark: `integration`
# is what makes this module self-skip without a database (the two-factor guard
# `seeded_db` itself enforces via DATABASE_URL + ALLOW_DB_RESET=1); `queueproof` is
# the selector the narrow CI gate collects.
pytestmark = [pytest.mark.integration, pytest.mark.queueproof]

_COASTAL_BIZ_ID = uuid.UUID("b0000001-0000-0000-0000-000000000001")


def _delete_all_jobs() -> None:
    with repo.get_connection() as conn, conn.transaction():
        # outbound_provider_handoffs references jobs; clear it first (FK-safe).
        conn.execute("DELETE FROM outbound_provider_handoffs")
        conn.execute("DELETE FROM jobs")


@pytest.fixture(autouse=True)
def _isolated_jobs(seeded_db):
    """`claim_job()` claims the oldest eligible row GLOBALLY, with no per-test
    scoping of its own (see tests/test_queue_durability.py's own module
    docstring for the full argument). A job left pending by one test would
    otherwise be claimed by the NEXT test's `claim_job()` call instead of the
    row that test itself just enqueued. Empty `jobs` on both sides of every
    test in this module so each test's claim always resolves to its own row.
    """
    _delete_all_jobs()
    yield
    _delete_all_jobs()


def _new_run(*, status: RunStatus = RunStatus.RECEIVED) -> uuid.UUID:
    """Create a fresh run against the seeded Coastal Cleaning business, at the
    given starting status (default 'received', the row's natural default)."""
    run_id = repo.create_run(business_id=_COASTAL_BIZ_ID, source_email_id=None)
    if status is not RunStatus.RECEIVED:
        repo.set_status(run_id, status)
    return run_id


def _unaccounted_ids() -> set[uuid.UUID]:
    return {row["id"] for row in repo.list_unaccounted_error_runs()}


def _run_status(run_id: uuid.UUID) -> str:
    run = repo.load_run(run_id)
    assert run is not None, f"run {run_id} vanished"
    return str(run["status"])


def _row_updated_at(table: str, row_id: uuid.UUID):
    with repo.get_connection() as conn:
        row = conn.execute(
            f"SELECT updated_at FROM {table} WHERE id = %s", (str(row_id),)
        ).fetchone()
    assert row is not None, f"{table} row {row_id} not found"
    return row[0]


# ---------------------------------------------------------------------------
# 1-3: legitimate settlement paths must be SILENT.
# ---------------------------------------------------------------------------


def test_settle_pipeline_job_terminal_result_is_silent(seeded_db) -> None:
    """job done + run error, ONE transaction (settle_pipeline_job, terminal)."""
    run_id = _new_run(status=RunStatus.EXTRACTING)
    job_id = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"run_pipeline:{run_id}:0",
        run_id=run_id,
    )
    assert job_id is not None
    job = repo.claim_job()
    assert job is not None and job.run_id == run_id

    outcome = repo.settle_pipeline_job(
        job,
        PipelineResult(
            outcome=PipelineOutcome.TERMINAL,
            stage=PipelineStage.EXTRACT,
            reason=PipelineReason.SCHEMA_OR_PARSE_FAILURE,
        ),
        backoff_seconds=30.0,
    )
    assert outcome is SettlementOutcome.DONE

    # The test cannot pass because nothing errored: confirm the run genuinely
    # reached 'error' before asserting the predicate is silent about it.
    assert _run_status(run_id) == RunStatus.ERROR.value
    assert run_id not in _unaccounted_ids()


def test_settle_pipeline_job_retry_exhaustion_is_silent(seeded_db) -> None:
    """job dead + run error, ONE transaction (settle_pipeline_job, retry-exhausted)."""
    run_id = _new_run(status=RunStatus.EXTRACTING)
    job_id = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"run_pipeline:{run_id}:0",
        run_id=run_id,
        max_attempts=1,
    )
    assert job_id is not None
    job = repo.claim_job()
    assert job is not None and job.attempts == job.max_attempts == 1

    outcome = repo.settle_pipeline_job(
        job,
        PipelineResult(
            outcome=PipelineOutcome.RETRYABLE,
            stage=PipelineStage.EXTRACT,
            reason=PipelineReason.PROVIDER_TIMEOUT,
        ),
        backoff_seconds=30.0,
    )
    assert outcome is SettlementOutcome.DEAD

    assert _run_status(run_id) == RunStatus.ERROR.value
    assert run_id not in _unaccounted_ids()


def test_reap_expired_final_attempt_is_silent(seeded_db) -> None:
    """job dead + run error, ONE transaction (reap_expired_final_attempt)."""
    run_id = _new_run(status=RunStatus.EXTRACTING)
    job_id = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"run_pipeline:{run_id}:0",
        run_id=run_id,
        max_attempts=1,
    )
    assert job_id is not None
    job = repo.claim_job()
    assert job is not None and job.attempts == job.max_attempts == 1

    # Force the lease into the past directly — waiting out a real lease would
    # make this test slow and is not the behaviour under test.
    with repo.get_connection() as conn, conn.transaction():
        conn.execute(
            "UPDATE jobs SET leased_until = now() - interval '1 second' WHERE id = %s",
            (str(job.id),),
        )

    outcome = repo.reap_expired_final_attempt()
    assert outcome is SettlementOutcome.REAPED_FINAL_LEASE

    assert _run_status(run_id) == RunStatus.ERROR.value
    assert run_id not in _unaccounted_ids()


# ---------------------------------------------------------------------------
# 4-8: unaccounted shapes must FIRE.
# ---------------------------------------------------------------------------


def test_error_run_with_only_open_jobs_is_reported(seeded_db) -> None:
    """A run in error whose only job(s) are still pending/leased — no terminal
    settlement exists at all, so this must fire."""
    run_id = _new_run()
    repo.record_run_error(run_id, "SomeReason")
    assert _run_status(run_id) == RunStatus.ERROR.value

    job_id = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"run_pipeline:{run_id}:0",
        run_id=run_id,
    )
    assert job_id is not None  # stays 'pending' — never claimed or settled

    assert run_id in _unaccounted_ids()


def test_error_run_with_no_job_rows_at_all_is_reported(seeded_db) -> None:
    run_id = _new_run()
    repo.record_run_error(run_id, "SomeReason")
    assert _run_status(run_id) == RunStatus.ERROR.value

    assert run_id in _unaccounted_ids()


def test_error_run_whose_terminal_job_settled_before_the_error_is_reported(
    seeded_db,
) -> None:
    """A run's only done/dead job settled BEFORE the run's own error transition
    — a stale success must not vouch for a later, unrelated error."""
    run_id = _new_run(status=RunStatus.EXTRACTING)
    job_id = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"run_pipeline:{run_id}:0",
        run_id=run_id,
    )
    assert job_id is not None
    job = repo.claim_job()
    assert job is not None and job.run_id == run_id

    outcome = repo.settle_pipeline_job(
        job, PipelineResult(outcome=PipelineOutcome.OK), backoff_seconds=30.0
    )
    assert outcome is SettlementOutcome.DONE
    # OK settlement never touches the run — still 'extracting'.
    assert _run_status(run_id) == RunStatus.EXTRACTING.value

    time.sleep(0.02)  # force a genuinely later, distinct transaction below
    repo.record_run_error(run_id, "SomeReason")
    assert _run_status(run_id) == RunStatus.ERROR.value

    job_updated_at = _row_updated_at("jobs", job.id)
    run_updated_at = _row_updated_at("payroll_runs", run_id)
    assert job_updated_at < run_updated_at, (
        "the job's terminal settlement must be strictly BEFORE the run's error "
        "transition, or this test proves nothing about the ordering it claims"
    )

    assert run_id in _unaccounted_ids()


def test_late_no_op_job_after_an_independent_error_is_still_reported(
    seeded_db,
) -> None:
    """THE review's false-negative regression: record_run_error() errors a run
    on its own; a DIFFERENT job for that run is settled 'done' (OK) strictly
    LATER, in a separate transaction. A `>=` correlation would let that later,
    unrelated settlement silently vouch for the earlier unaccounted error —
    equality must not, and must still report the run.
    """
    run_id = _new_run(status=RunStatus.EXTRACTING)
    repo.record_run_error(run_id, "SomeReason")
    assert _run_status(run_id) == RunStatus.ERROR.value

    time.sleep(0.02)  # force the settlement below into a genuinely later transaction

    job_id = repo.enqueue_job(
        kind=JobKind.RUN_PIPELINE,
        dedup_key=f"run_pipeline:{run_id}:1",
        run_id=run_id,
    )
    assert job_id is not None
    job = repo.claim_job()
    assert job is not None and job.run_id == run_id

    outcome = repo.settle_pipeline_job(
        job, PipelineResult(outcome=PipelineOutcome.OK), backoff_seconds=30.0
    )
    assert outcome is SettlementOutcome.DONE

    run_updated_at = _row_updated_at("payroll_runs", run_id)
    job_updated_at = _row_updated_at("jobs", job.id)
    assert job_updated_at > run_updated_at, (
        "the two writes must land in distinct committed transactions with "
        "genuinely different now() values, or this test cannot exercise the "
        "ordering a >= correlation would have wrongly suppressed"
    )

    assert run_id in _unaccounted_ids()


def test_settle_background_terminal_classification_is_reported(seeded_db) -> None:
    """settle_background_terminal() errors a run with NO job at all — a
    currently-dormant path, classified here deliberately: no job took
    responsibility for the error, so it must be reported.
    """
    run_id = _new_run(status=RunStatus.EXTRACTING)

    outcome = repo.settle_background_terminal(
        run_id,
        PipelineResult(
            outcome=PipelineOutcome.TERMINAL,
            stage=PipelineStage.EXTRACT,
            reason=PipelineReason.SCHEMA_OR_PARSE_FAILURE,
        ),
    )
    assert outcome is SettlementOutcome.DONE
    assert _run_status(run_id) == RunStatus.ERROR.value

    assert run_id in _unaccounted_ids()
