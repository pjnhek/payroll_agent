"""Unit tests for repo.sweep_stranded_runs + repo.find_run_by_message_id (09-01).

All FakeConnection-based tests mirror test_claim_status.py's SQL-shape-pinning
style — no live DB needed. The full live sweep -> ERROR -> retrigger interplay
is stubbed here (integration-marked, skip-guarded) and gets its real
implementation in 09-04 once main.py's retrigger route wires the same
threshold constant.
"""
from __future__ import annotations

import os

import pytest

from app.db import repo
from tests.conftest import FakeConnection


# ---------------------------------------------------------------------------
# sweep_stranded_runs — SQL-shape + scope-pin unit tests
# ---------------------------------------------------------------------------


def test_sweep_stranded_runs_sql_shape():
    """The sweep's executed SQL must contain the CAS predicate shape (status =
    ANY(%s)), RETURNING, and the SQL-concatenation form of error_detail
    (|| status, not a Python '{status}' placeholder — Codex LOW, closed)."""
    conn = FakeConnection()
    conn.script_fetchall([])

    repo.sweep_stranded_runs(90, conn=conn)

    assert conn.executed, "sweep_stranded_runs must execute at least one SQL statement"
    sql_executed = conn.all_sql()
    assert "status = ANY(%s)" in sql_executed, (
        "sweep_stranded_runs SQL must contain 'status = ANY(%s)' — the CAS scope "
        "predicate (T-09-01)"
    )
    assert "RETURNING" in sql_executed.upper() and "id" in sql_executed.lower(), (
        "sweep_stranded_runs SQL must contain 'RETURNING id'"
    )
    assert "|| status" in sql_executed, (
        "sweep_stranded_runs SQL must build error_detail via SQL concatenation "
        "of the pre-update status column (%s || status) — NOT a literal "
        "'{status}' placeholder string (Codex LOW, closed)"
    )
    assert "{status}" not in sql_executed, (
        "sweep_stranded_runs SQL must NOT contain a literal unresolved "
        "'{status}' placeholder (Codex LOW regression guard)"
    )


def test_sweep_stranded_runs_scope_pin_d_9_12():
    """The scope param list passed to conn.execute must equal EXACTLY
    ['received', 'extracting', 'computed'] — never the parked statuses
    (awaiting_reply/awaiting_approval/approved). D-9-12 pin: sweeping a
    parked-by-design status would be a correctness bug (a run waiting on a
    human is not stranded)."""
    conn = FakeConnection()
    conn.script_fetchall([])

    repo.sweep_stranded_runs(90, conn=conn)

    scope_lists = [
        params[3]
        for _sql, params in conn.executed
        if params and isinstance(params[3], list)
    ]
    assert scope_lists, "expected a list-typed scope param in the executed SQL params"
    assert scope_lists[0] == ["received", "extracting", "computed"], (
        "sweep_stranded_runs scope must be exactly "
        "['received', 'extracting', 'computed'] (D-9-12)"
    )
    for parked in ("awaiting_reply", "awaiting_approval", "approved"):
        assert parked not in scope_lists[0], (
            f"sweep_stranded_runs scope must NEVER include parked status "
            f"'{parked}' — a run waiting on a human is not stranded (D-9-12)"
        )


def test_sweep_stranded_runs_returns_empty_list_when_no_rows():
    """Returns [] when the UPDATE ... RETURNING id yields no rows (no stranded
    runs past the threshold)."""
    conn = FakeConnection()
    conn.script_fetchall([])

    result = repo.sweep_stranded_runs(90, conn=conn)

    assert result == [], (
        "sweep_stranded_runs must return [] when fetchall() yields no rows"
    )


def test_sweep_stranded_runs_returns_swept_ids():
    """Returns the list of swept run ids, parsed as uuid.UUID, when the UPDATE
    RETURNING clause yields matching rows."""
    import uuid

    conn = FakeConnection()
    id1, id2 = uuid.uuid4(), uuid.uuid4()
    conn.script_fetchall([(str(id1),), (str(id2),)])

    result = repo.sweep_stranded_runs(90, conn=conn)

    assert result == [id1, id2], (
        "sweep_stranded_runs must return the RETURNING id rows as a list of "
        "uuid.UUID, in order"
    )


# ---------------------------------------------------------------------------
# find_run_by_message_id — join-shape unit test (checker BLOCKER 1 closure)
# ---------------------------------------------------------------------------


def test_find_run_by_message_id_sql_shape():
    """The executed SQL must JOIN email_messages and filter on
    email_messages.message_id = %s — the corrected join-based lookup keyed on
    message_id (never email_id, which the dedup-loser branch never has —
    checker BLOCKER 1, closed)."""
    conn = FakeConnection()
    conn.script_fetchone(None)

    repo.find_run_by_message_id("<client-001@acme.test>", conn=conn)

    assert conn.executed, "find_run_by_message_id must execute at least one SQL statement"
    sql_executed = conn.all_sql()
    assert "JOIN email_messages" in sql_executed, (
        "find_run_by_message_id SQL must contain 'JOIN email_messages'"
    )
    assert "email_messages.message_id = %s" in sql_executed, (
        "find_run_by_message_id SQL must contain "
        "'email_messages.message_id = %s'"
    )


def test_find_run_by_message_id_returns_none_when_not_found():
    """Returns None when no run's source email carries this message_id."""
    conn = FakeConnection()
    conn.script_fetchone(None)

    result = repo.find_run_by_message_id("<unknown@nowhere.test>", conn=conn)

    assert result is None


def test_find_run_by_message_id_returns_uuid_when_found():
    """Returns the run id (as uuid.UUID) when a matching row is found."""
    import uuid

    conn = FakeConnection()
    run_id = uuid.uuid4()
    conn.script_fetchone((str(run_id),))

    result = repo.find_run_by_message_id("<client-001@acme.test>", conn=conn)

    assert result == run_id


# ---------------------------------------------------------------------------
# runs_list() wiring — the sweep runs before load_all_runs (09-03, D-9-11)
# ---------------------------------------------------------------------------


def test_runs_list_calls_sweep_before_load_all_runs(monkeypatch):
    """GET /runs must call repo.sweep_stranded_runs BEFORE repo.load_all_runs
    (D-9-11 — freshly-swept ERROR rows must appear in the SAME page load) and
    must never 500 if the sweep itself raises (matches the existing
    try/except-swallow-on-DB-unavailable style already used for load_all_runs)."""
    from fastapi.testclient import TestClient

    import app.main as app_main
    from app.db import repo as repo_mod

    call_order: list[str] = []
    monkeypatch.setattr(
        repo_mod,
        "sweep_stranded_runs",
        lambda threshold_seconds: call_order.append("sweep"),
    )
    monkeypatch.setattr(
        repo_mod,
        "load_all_runs",
        lambda: call_order.append("load") or [],
    )

    client = TestClient(app_main.app)
    response = client.get("/runs")

    assert response.status_code == 200
    assert call_order == ["sweep", "load"], (
        f"sweep_stranded_runs must be called BEFORE load_all_runs on every "
        f"GET /runs (D-9-11); got order={call_order}"
    )


def test_runs_list_never_500s_when_sweep_raises(monkeypatch):
    """A sweep failure must never 500 the dashboard — log and continue to
    render (matches the existing route's DB-unavailable philosophy)."""
    from fastapi.testclient import TestClient

    import app.main as app_main
    from app.db import repo as repo_mod

    def _raise(threshold_seconds):
        raise RuntimeError("simulated sweep failure")

    monkeypatch.setattr(repo_mod, "sweep_stranded_runs", _raise)
    monkeypatch.setattr(repo_mod, "load_all_runs", lambda: [])

    client = TestClient(app_main.app)
    response = client.get("/runs")

    assert response.status_code == 200, (
        "a sweep_stranded_runs failure must not 500 the dashboard; the route "
        "must catch the exception and still render the (empty) runs list"
    )


# ---------------------------------------------------------------------------
# Integration test — skip unless live DB available (full impl in 09-04)
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_sweep_then_retrigger_interplay_live():
    """Integration: a run swept to ERROR by sweep_stranded_runs is then
    recoverable via the dashboard's retrigger route.

    This test requires a live Supabase/Postgres connection (DATABASE_URL env
    var). Stub only in this plan — the real implementation lands in 09-04 once
    main.py's retrigger route is wired to the same threshold constant.
    """
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set — skipping live-DB integration test")

    pytest.skip("Integration test stub — full impl in 09-04")
