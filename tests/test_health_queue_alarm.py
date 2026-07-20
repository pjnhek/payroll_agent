"""Hermetic tests for GET /health/queue (app/routes/health.py).

No live Postgres anywhere in this file — every test drives the route through
`TestClient(app)` with `repo.list_unaccounted_error_runs` monkeypatched
directly, matching the `tests/test_pump_route.py` idiom (patch the facade
seam, not a fake-repo fixture, since this route calls the facade function
wholesale with no other repo dependency).

This route adds no correctness of its own: it surfaces the existing
`list_unaccounted_error_runs` predicate (the equality-correlated anti-join
over jobs vs. payroll_runs) unchanged. That predicate ships with the
corrected equality correlation (never `>=`) and a passing late-settling-job
false-negative regression test, proven live against real Postgres elsewhere
in this suite. Nothing in this file re-tests that predicate; it only tests
the HTTP surface built on top of it.
"""
from __future__ import annotations

import contextlib
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.db import repo
from app.db.schema_introspect import SchemaDiff
from app.main import app
from tests.conftest import FakeConnection

client = TestClient(app)


@contextlib.contextmanager
def _fake_conn_cm(conn):
    yield conn


# ── /health/queue: clear / firing / db-error ────────────────────────────────


def test_health_queue_no_unaccounted_errors_returns_200(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(repo, "list_unaccounted_error_runs", lambda: [])
    r = client.get("/health/queue")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_queue_unaccounted_errors_returns_503_with_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        {"id": "run-1", "error_reason": "delivery_failed", "updated_at": "t1"},
        {"id": "run-2", "error_reason": "unknown", "updated_at": "t2"},
        {"id": "run-3", "error_reason": "extraction_failed", "updated_at": "t3"},
    ]
    monkeypatch.setattr(repo, "list_unaccounted_error_runs", lambda: rows)
    r = client.get("/health/queue")
    assert r.status_code == 503
    assert r.json() == {"status": "unaccounted_errors", "count": 3}


def test_health_queue_db_error_returns_503_no_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _boom():
        raise RuntimeError("postgresql://user:secret@host/db unreachable")

    monkeypatch.setattr(repo, "list_unaccounted_error_runs", _boom)
    r = client.get("/health/queue")
    assert r.status_code == 503
    assert r.json() == {"detail": "queue check unavailable"}
    assert "secret" not in r.text and "postgresql://" not in r.text


# ── disclosure discipline: exact key set, no run id / error text ───────────


def test_health_queue_firing_body_keys_are_exactly_the_minimal_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An added field must red this test rather than silently widening
    disclosure."""
    rows = [{"id": "run-1", "error_reason": "delivery_failed", "updated_at": "t1"}]
    monkeypatch.setattr(repo, "list_unaccounted_error_runs", lambda: rows)
    r = client.get("/health/queue")
    assert r.status_code == 503
    assert set(r.json().keys()) == {"status", "count"}


def test_health_queue_firing_body_carries_no_run_id_or_error_detail_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disclosure is a contract, not a convention: the firing body must not
    leak any run identifier or error-reason text from the underlying rows."""
    rows = [
        {
            "id": "leak-me-run-id-should-never-appear",
            "error_reason": "leak-me-error-reason-should-never-appear",
            "updated_at": "2026-07-20T00:00:00Z",
        }
    ]
    monkeypatch.setattr(repo, "list_unaccounted_error_runs", lambda: rows)
    r = client.get("/health/queue")
    assert r.status_code == 503
    assert "leak-me-run-id-should-never-appear" not in r.text
    assert "leak-me-error-reason-should-never-appear" not in r.text


def test_health_queue_clear_case_returns_200_and_firing_case_returns_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(repo, "list_unaccounted_error_runs", lambda: [])
    assert client.get("/health/queue").status_code == 200

    monkeypatch.setattr(
        repo,
        "list_unaccounted_error_runs",
        lambda: [{"id": "x", "error_reason": None, "updated_at": "t"}],
    )
    assert client.get("/health/queue").status_code == 503


# ── regression: the three pre-existing health contracts are unchanged ──────


def test_health_live_still_returns_200_ok() -> None:
    r = client.get("/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_health_ready_still_returns_200_ready() -> None:
    with patch(
        "app.routes.health.get_connection", lambda: _fake_conn_cm(FakeConnection())
    ):
        r = client.get("/health/ready")
    assert r.status_code == 200
    assert r.json() == {"status": "ready"}


def test_health_ready_still_returns_503_no_leak_on_db_failure() -> None:
    def _boom():
        raise RuntimeError("postgresql://user:secret@host/db unreachable")

    with patch("app.routes.health.get_connection", _boom):
        r = client.get("/health/ready")
    assert r.status_code == 503
    assert r.json() == {"detail": "database not ready"}
    assert "secret" not in r.text and "postgresql://" not in r.text


def test_health_schema_still_returns_200_in_sync() -> None:
    diff = SchemaDiff({}, [], [], [])
    with patch(
        "app.routes.health.get_connection", lambda: _fake_conn_cm(FakeConnection())
    ), patch("app.routes.health.diff_against_live", return_value=diff):
        r = client.get("/health/schema")
    assert r.status_code == 200
    assert r.json() == {"status": "in_sync"}


def test_health_schema_still_returns_503_drift_with_missing() -> None:
    diff = SchemaDiff({"payroll_runs": ["clarification_round"]}, ["needs_operator"], [], [])
    with patch(
        "app.routes.health.get_connection", lambda: _fake_conn_cm(FakeConnection())
    ), patch("app.routes.health.diff_against_live", return_value=diff):
        r = client.get("/health/schema")
    assert r.status_code == 503
    body = r.json()
    assert body["status"] == "drift"
    assert body["missing"]["payroll_runs"] == ["clarification_round"]
    assert body["missing"]["status_values"] == ["needs_operator"]
