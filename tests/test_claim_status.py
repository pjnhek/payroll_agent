"""claim_status CAS helper tests (FOUND-04).

These tests verify the correctness contract for `repo.claim_status`, the
atomic compare-and-swap that prevents duplicate operator approvals and late
reply races. All unit tests use FakeConnection (no live DB). The integration
test is skip-guarded.

Tests WILL FAIL RED until Wave 1 adds `claim_status` to app/db/repo.py.
That is the expected Wave 0 outcome — these are the spec, not the impl.
"""
from __future__ import annotations

import uuid
from typing import Any, cast

import pytest

from app.db import repo
from app.models.status import RunStatus

# Import FakeConnection from conftest (shared fixture — no duplication).
# FakeConnection is a pytest fixture but we also use the class directly here
# for inline construction with scripted fetchone returns.
from tests.conftest import FakeConnection

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _run_id() -> uuid.UUID:
    return uuid.uuid4()


# ---------------------------------------------------------------------------
# Unit tests — FakeConnection, no live DB
# ---------------------------------------------------------------------------


def test_claim_status_returns_true_when_row_returned():
    """claim_status returns True when the UPDATE's RETURNING clause yields a row
    (the run was in the expected status — the claim succeeded)."""
    conn = FakeConnection()
    # Simulate the UPDATE ... RETURNING id returning a row (claim succeeded).
    conn.script_fetchone(("some-uuid",))

    result = repo.claim_status(
        _run_id(),
        RunStatus.AWAITING_APPROVAL,
        RunStatus.APPROVED,
        conn=cast(Any, conn),
    )

    assert result is True, (
        "claim_status must return True when the conditional UPDATE returns a row "
        "(run was in expected status — CAS succeeded)"
    )


def test_claim_status_returns_false_when_no_row():
    """claim_status returns False when the UPDATE returns no row
    (the run was NOT in the expected status — a late/duplicate call)."""
    conn = FakeConnection()
    # fetchone_q is empty → _next_fetchone() returns None (claim lost).
    conn.script_fetchone(None)

    result = repo.claim_status(
        _run_id(),
        RunStatus.AWAITING_APPROVAL,
        RunStatus.APPROVED,
        conn=cast(Any, conn),
    )

    assert result is False, (
        "claim_status must return False when the conditional UPDATE returns no row "
        "(run was not in expected status — duplicate dropped)"
    )


def test_claim_status_sql_contains_where_status_and_returning():
    """The SQL executed by claim_status must contain the CAS predicate shape:
    'AND status = %s' (so ONLY the expected status is atomically swapped) and
    'RETURNING id' (so the Python side can distinguish success from no-op).

    This assertion pins the exact SQL contract so a refactor that drops the
    predicate or the RETURNING clause is caught immediately."""
    conn = FakeConnection()
    conn.script_fetchone(("some-uuid",))

    repo.claim_status(
        _run_id(),
        RunStatus.AWAITING_APPROVAL,
        RunStatus.APPROVED,
        conn=cast(Any, conn),
    )

    assert conn.executed, "claim_status must execute at least one SQL statement"
    sql_executed = conn.all_sql()
    assert "AND status = %s" in sql_executed, (
        "claim_status SQL must contain 'AND status = %s' — the CAS predicate "
        "that makes the operation atomic"
    )
    assert "RETURNING" in sql_executed.upper() and "id" in sql_executed.lower(), (
        "claim_status SQL must contain 'RETURNING id' — the mechanism that "
        "distinguishes a successful claim from a no-op"
    )


def test_claim_status_passes_expected_and_new_status_as_params():
    """The expected and new status values must be passed as SQL parameters
    (never f-string interpolated) — parameterized SQL is the project rule."""
    conn = FakeConnection()
    conn.script_fetchone(None)

    expected_status = RunStatus.AWAITING_APPROVAL
    new_status = RunStatus.APPROVED
    repo.claim_status(_run_id(), expected_status, new_status, conn=cast(Any, conn))

    # At least one executed statement must carry the enum values as params.
    found = False
    for _sql, params in conn.executed:
        if params and expected_status.value in params and new_status.value in params:
            found = True
            break
    assert found, (
        "claim_status must pass both expected and new status values as SQL params "
        "(never f-string interpolated — parameterized SQL rule)"
    )


def test_claim_status_invariant_doc_updated():
    """The 'two writers' invariant must stay documented where the writers live.

    The invariant: there are exactly TWO status writers — set_status (unguarded) and
    claim_status (the atomic guarded claim used at every contended gate). A third,
    unguarded writer added at a contended gate would silently reintroduce the
    double-claim races that claim_status exists to close, so the rule is documented
    in the module that owns both functions and pinned by this test.
    """
    import pathlib

    from app.db.repo import runs as repo_runs

    # set_status/claim_status — and the "two writers" invariant they share — live in
    # app/db/repo/runs.py, not the facade (which has no docstring body describing it).
    src = pathlib.Path(repo_runs.__file__).read_text()
    assert "two writers" in src, (
        "app/db/repo/runs.py must document the 'two writers' status-writer invariant "
        "in its docstring — it is the rule that keeps a third unguarded writer from "
        "being added at a contended gate"
    )


# ---------------------------------------------------------------------------
# Integration test — skip unless live DB available
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_claim_status_concurrent_calls_exactly_one_true():
    """Integration: two concurrent claim calls on the same run → exactly one True.

    This test requires a live Supabase/Postgres connection (DATABASE_URL env var).
    It verifies that the CAS is truly atomic — not just SQL-shape-correct.

    Skipped in the mocked suite (`uv run pytest -m 'not integration'`).
    """
    import os

    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set — skipping live-DB integration test")

    # Live DB round-trip: create a run, attempt two concurrent claims, assert one True.
    # Implementation note for Wave 1: use threading or asyncio to fire both claims
    # at near-simultaneously and assert exactly one returns True.
    # (Full implementation deferred to Wave 1 — this stub establishes the contract.)
    pytest.skip("Integration test stub — full impl in Wave 1 (claim_status not yet in repo)")
