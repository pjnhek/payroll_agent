"""Unit tests for repo.sweep_stranded_runs + repo.find_run_by_message_id (09-01),
plus the SC3 end-to-end live-DB proof (09-04).

All FakeConnection-based tests mirror test_claim_status.py's SQL-shape-pinning
style — no live DB needed. The live sweep -> ERROR -> retrigger interplay
(`test_stranded_run_swept_and_retriggerable`) is the real implementation,
replacing the 09-01 stub, now that main.py's retrigger route is wired to the
same STALE_THRESHOLD_SECONDS constant used by the sweep (09-03/09-04).
"""
from __future__ import annotations

import os
import uuid
from typing import Any, cast

import pytest

from app.db import repo
from app.models.status import RunStatus
from tests.conftest import FakeConnection

_HAS_DB = bool(os.environ.get("DATABASE_URL"))
_HAS_RESET = os.environ.get("ALLOW_DB_RESET") == "1"

_SKIP_LIVE_DB = pytest.mark.skipif(
    not (_HAS_DB and _HAS_RESET),
    reason="Live-DB tests require DATABASE_URL and ALLOW_DB_RESET=1 (two-factor guard)",
)

# Shared seed identifiers (mirrors tests/test_atomic_persist.py).
COASTAL_BIZ_ID = uuid.UUID("b0000001-0000-0000-0000-000000000001")
COASTAL_EMAIL = "payroll@coastalcleaning.example"


# ---------------------------------------------------------------------------
# sweep_stranded_runs — SQL-shape + scope-pin unit tests
# ---------------------------------------------------------------------------


def test_sweep_stranded_runs_sql_shape():
    """The sweep's executed SQL must contain the CAS predicate shape (status =
    ANY(%s)), RETURNING, and the SQL-concatenation form of error_detail
    (|| status, not a Python '{status}' placeholder)."""
    conn = FakeConnection()
    conn.script_fetchall([])

    repo.sweep_stranded_runs(90, conn=cast(Any, conn))

    assert conn.executed, "sweep_stranded_runs must execute at least one SQL statement"
    sql_executed = conn.all_sql()
    assert "status = ANY(%s)" in sql_executed, (
        "sweep_stranded_runs SQL must contain 'status = ANY(%s)' — the CAS scope "
        "predicate"
    )
    assert "RETURNING" in sql_executed.upper() and "id" in sql_executed.lower(), (
        "sweep_stranded_runs SQL must contain 'RETURNING id'"
    )
    assert "|| status" in sql_executed, (
        "sweep_stranded_runs SQL must build error_detail via SQL concatenation "
        "of the pre-update status column (%s || status) — NOT a literal "
        "'{status}' placeholder string"
    )
    assert "{status}" not in sql_executed, (
        "sweep_stranded_runs SQL must NOT contain a literal unresolved "
        "'{status}' placeholder (regression guard)"
    )


def test_sweep_stranded_runs_scope_pin():
    """The scope param list passed to conn.execute must equal EXACTLY
    ['received', 'extracting', 'computed'] — never the parked statuses
    (awaiting_reply/awaiting_approval/approved). Sweeping a parked-by-design
    status would be a correctness bug: a run waiting on a human is not
    stranded, and sweeping it to ERROR discards the pending human decision."""
    conn = FakeConnection()
    conn.script_fetchall([])

    repo.sweep_stranded_runs(90, conn=cast(Any, conn))

    scope_lists = [
        params[3]
        for _sql, params in conn.executed
        if params and isinstance(params[3], list)
    ]
    assert scope_lists, "expected a list-typed scope param in the executed SQL params"
    assert scope_lists[0] == ["received", "extracting", "computed"], (
        "sweep_stranded_runs scope must be exactly "
        "['received', 'extracting', 'computed']"
    )
    for parked in ("awaiting_reply", "awaiting_approval", "approved"):
        assert parked not in scope_lists[0], (
            f"sweep_stranded_runs scope must NEVER include parked status "
            f"'{parked}' — a run waiting on a human is not stranded"
        )
    # needs_operator is a settled human-gate escalation state (like awaiting_approval),
    # NOT a stranded background-task failure — it must NEVER join the sweep scope.
    assert "needs_operator" not in scope_lists[0], (
        "sweep_stranded_runs scope must NEVER include 'needs_operator' — it is "
        "a settled human-gate escalation state, not a stranded run"
    )


def test_sweep_stranded_runs_returns_empty_list_when_no_rows():
    """Returns [] when the UPDATE ... RETURNING id yields no rows (no stranded
    runs past the threshold)."""
    conn = FakeConnection()
    conn.script_fetchall([])

    result = repo.sweep_stranded_runs(90, conn=cast(Any, conn))

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

    result = repo.sweep_stranded_runs(90, conn=cast(Any, conn))

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

    repo.find_run_by_message_id("<client-001@acme.test>", conn=cast(Any, conn))

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

    result = repo.find_run_by_message_id("<unknown@nowhere.test>", conn=cast(Any, conn))

    assert result is None


def test_find_run_by_message_id_returns_uuid_when_found():
    """Returns the run id (as uuid.UUID) when a matching row is found."""
    import uuid

    conn = FakeConnection()
    run_id = uuid.uuid4()
    conn.script_fetchone((str(run_id),))

    result = repo.find_run_by_message_id("<client-001@acme.test>", conn=cast(Any, conn))

    assert result == run_id


# ---------------------------------------------------------------------------
# runs_list() wiring — the sweep runs before load_all_runs
# ---------------------------------------------------------------------------


def test_runs_list_calls_sweep_before_load_all_runs(monkeypatch):
    """GET /runs must call repo.sweep_stranded_runs BEFORE repo.load_all_runs
    — freshly-swept ERROR rows must appear in the SAME page load — and must never
    500 if the sweep itself raises (matching the try/except-swallow-on-DB-unavailable
    style already used for load_all_runs)."""
    from fastapi.testclient import TestClient

    import app.main as app_main
    from app.db import repo as repo_mod

    call_order: list[str] = []
    def _record_call(label: str) -> None:
        call_order.append(label)

    def _load_runs() -> list[Any]:
        _record_call("load")
        return []

    monkeypatch.setattr(
        repo_mod,
        "sweep_stranded_runs",
        lambda threshold_seconds: _record_call("sweep"),
    )
    monkeypatch.setattr(
        repo_mod,
        "load_all_runs",
        _load_runs,
    )

    client = TestClient(app_main.app)
    response = client.get("/runs")

    assert response.status_code == 200
    assert call_order == ["sweep", "load"], (
        f"sweep_stranded_runs must be called BEFORE load_all_runs on every "
        f"GET /runs; got order={call_order}"
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
# SC3 end-to-end integration test — strand, sweep, retrigger via the ACTUAL
# POST /runs/{run_id}/retrigger route. Driving repo.claim_status(...) directly
# instead would only prove claimability, not the operator recovery path.
# ---------------------------------------------------------------------------


def _seed_live_run() -> uuid.UUID:
    """Insert a fresh inbound email + run against the REAL DB (mirrors
    test_atomic_persist.py's _seed_live_run)."""
    eid, _ = repo.insert_inbound_email(
        message_id=f"<{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="payroll hours",
        from_addr=COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="Maria Chen 40 regular",
    )
    return repo.create_run(business_id=COASTAL_BIZ_ID, source_email_id=eid)


def _backdate_updated_at(run_id: uuid.UUID, seconds_ago: int) -> None:
    """Directly backdate a run's updated_at via a raw UPDATE — no repo helper
    exposes a raw updated_at write, since every writer sets it to now()."""
    from app.db.supabase import get_connection

    with get_connection() as conn, conn.transaction():
        conn.execute(
            "UPDATE payroll_runs SET updated_at = now() - (%s || ' seconds')::interval"
            " WHERE id = %s",
            (str(seconds_ago), str(run_id)),
        )


@pytest.mark.integration
@_SKIP_LIVE_DB
def test_stranded_run_swept_and_retriggerable(seeded_db, monkeypatch):
    """SC3 end-to-end (DATA-03): a run stranded mid-flight is swept to ERROR
    with a distinguishing sentinel, then successfully retriggered to a
    progressing status via the ACTUAL operator-facing retrigger route, not the
    underlying claim primitive — so this proves the recovery path a human operator
    actually uses.
    """
    from app.routes.runs import STALE_THRESHOLD_SECONDS

    # --- Strand a run in EXTRACTING with a backdated updated_at ------------
    run_id = _seed_live_run()
    repo.set_status(run_id, RunStatus.EXTRACTING)
    _backdate_updated_at(run_id, STALE_THRESHOLD_SECONDS + 60)

    # --- Sweep: the stranded run must be swept to ERROR --------------------
    swept_ids = repo.sweep_stranded_runs(STALE_THRESHOLD_SECONDS)
    assert run_id in swept_ids, "the stranded run must appear in the swept list"

    run = cast(dict[str, Any], repo.load_run(run_id))
    assert run["status"] == "error"
    assert run["error_reason"] == "StrandedRunSwept"
    assert run["error_detail"] is not None
    assert "stranded" in run["error_detail"].lower(), (
        "error_detail must be distinguishable from a real exception-driven ERROR"
    )

    # --- Operator recovery: the ACTUAL POST /runs/{run_id}/retrigger route -
    # QUEUE-02: retrigger no longer schedules a BackgroundTask — it enqueues a
    # durable `jobs` row inside the same transaction as the winning claim, and a
    # worker (here, an explicit drain.drain_once()) is what actually dispatches the
    # pipeline. Monkeypatch the background-task target to a no-op so this proves the
    # CLAIM + ENQUEUE + DISPATCH behavior against the real DB without triggering a
    # real LLM/pipeline run.
    from fastapi.testclient import TestClient

    import app.main as app_main
    import app.routes.pipeline_glue as pipeline_glue_mod
    from app.db.supabase import get_connection
    from app.queue import drain

    dispatched: list[uuid.UUID] = []
    monkeypatch.setattr(
        pipeline_glue_mod, "run_pipeline_bg", lambda rid: dispatched.append(rid)
    )

    client = TestClient(app_main.app)
    response = client.post(f"/runs/{run_id}/retrigger")

    assert response.status_code in (200, 303), (
        f"retrigger route must return a success status; got {response.status_code}"
    )
    reloaded = cast(dict[str, Any], repo.load_run(run_id))
    assert reloaded["status"] == "received", (
        "the swept-to-ERROR run must be claimed to a progressing status "
        "(received) by the actual retrigger route"
    )

    # A durable jobs row must exist BEFORE the drain runs, proving the enqueue
    # (not just the drain below) is what the route is actually responsible for.
    with get_connection() as conn:
        job_row = conn.execute(
            "SELECT state, kind, dedup_key FROM jobs WHERE run_id = %s",
            (str(run_id),),
        ).fetchone()
    assert job_row is not None, (
        "retrigger must enqueue a durable jobs row for this run_id — none was found"
    )
    assert job_row[0] == "pending" and job_row[1] == "run_pipeline", (
        f"expected a pending run_pipeline job; got state={job_row[0]!r} "
        f"kind={job_row[1]!r}"
    )
    assert str(run_id) in job_row[2], (
        f"the enqueued job's dedup_key must carry this run_id; got {job_row[2]!r}"
    )

    assert drain.drain_once() is True, (
        "drain_once must claim and dispatch the job the retrigger route enqueued"
    )
    assert dispatched == [run_id], (
        "the retrigger route's enqueued job, once drained, must dispatch the "
        "background pipeline task for this run_id — proving it actually dispatched "
        "recovery work (not just flipped a status column)"
    )


@pytest.mark.integration
@_SKIP_LIVE_DB
def test_parked_statuses_never_swept_live(seeded_db):
    """Real-DB confirmation of the sweep scope, closing the loop with the
    FakeConnection-based test_sweep_stranded_runs_scope_pin unit test above: a run in
    awaiting_reply/awaiting_approval/approved with a backdated updated_at must NEVER
    be swept — it is waiting on a HUMAN, not stranded."""
    from app.routes.runs import STALE_THRESHOLD_SECONDS

    parked_statuses = [
        RunStatus.AWAITING_REPLY,
        RunStatus.AWAITING_APPROVAL,
        RunStatus.APPROVED,
    ]
    parked_run_ids: list[uuid.UUID] = []
    for status in parked_statuses:
        run_id = _seed_live_run()
        repo.set_status(run_id, status)
        _backdate_updated_at(run_id, STALE_THRESHOLD_SECONDS + 60)
        parked_run_ids.append(run_id)

    swept_ids = repo.sweep_stranded_runs(STALE_THRESHOLD_SECONDS)

    for run_id in parked_run_ids:
        assert run_id not in swept_ids, (
            f"a parked-by-design run ({run_id}) must never be swept — it is "
            "waiting on a human, not stranded"
        )
        # Confirm the status is untouched.
        run = cast(dict[str, Any], repo.load_run(run_id))
        assert run["status"] != "error"
