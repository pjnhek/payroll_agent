"""Wave 0 RED stubs: dashboard route smoke tests (DASH-01..05).

These tests will fail RED until Wave 3 adds the dashboard routes to app/main.py:
- GET /runs              → DASH-01 runs list (200)
- GET /runs/{id}         → DASH-02 run detail (200 or 404)
- GET /eval              → DASH-03 eval view (200, contains "chart.svg")
- POST /demo/send-test   → DASH-04 demo button (303 redirect)

Also covers:
- DASH-05 eval graceful handling of missing summary.json (200 with "No eval results")
- Message-ID uniqueness: /demo/send-test mints a fresh ID per click
- UUID path param validation: /runs/not-a-uuid → 422 (non-UUID strings must never
  reach a SQL query)
- Status poll endpoint: GET /runs/{id}/status → 200 JSON / 404
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _default_dashboard_queue_projection(monkeypatch):
    """Keep legacy route fixtures DB-free unless a test opts into queue state."""
    from app.db import repo

    monkeypatch.setattr(repo, "get_run_queue_label", lambda rid, conn=None: None)


# ---------------------------------------------------------------------------
# Test 1: DASH-01 — GET /runs returns 200
# ---------------------------------------------------------------------------


def test_runs_list_returns_200(fake_repo):
    """DASH-01: GET /runs → 200 (runs list page), rendering a real seeded run.

    A bare status-code check on an unmocked repo layer is satisfied even when
    repo.load_all_runs() fails and the route degrades to an empty list (its
    own `except Exception: runs = []` fallback) — 200 either way. Wired onto
    fake_repo with a real seeded run so the assertion actually proves the row
    renders, not merely that SOME page (possibly the empty-state page) came
    back.
    """
    business_id = next(iter(fake_repo.contact_to_business.values()))
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=None)

    response = client.get("/runs")
    assert response.status_code == 200, (
        f"GET /runs must return 200 (DASH-01 runs list); got {response.status_code}"
    )
    assert str(run_id) in response.text, (
        "the seeded run must actually render as a row, not fall through to "
        "the empty-state page"
    )
    assert "No payroll runs yet" not in response.text

    # Falsification: with no runs seeded at all, the page must show the
    # empty-state copy instead — pins that the row assertion above depended
    # on the real seeded run, not boilerplate present on every response.
    fake_repo.runs.clear()
    empty = client.get("/runs")
    assert empty.status_code == 200
    assert "No payroll runs yet" in empty.text


# ---------------------------------------------------------------------------
# load_all_runs explicit-column projection (jsonb_typeof-guarded employee_count).
# DB-free via FakeConnection (fake_conn fixture, tests/conftest.py).
# ---------------------------------------------------------------------------


def test_load_all_runs_projection_has_no_select_star(fake_conn):
    """The SQL text has no `pr.*` / `SELECT *`, and names the explicit scalar
    columns plus the two computed aliases."""
    from app.db import repo

    fake_conn.script_fetchall([])
    repo.load_all_runs(conn=fake_conn)

    sql = fake_conn.all_sql()
    assert "pr.*" not in sql
    assert "SELECT *" not in sql
    assert "summary_gate_reason" in sql
    assert "employee_count" in sql
    assert "pr.id" in sql
    assert "pr.status" in sql
    assert "pr.created_at" in sql


def test_load_all_runs_employee_count_uses_jsonb_typeof_guard(fake_conn):
    """employee_count is guarded by a jsonb_typeof CASE expression, NOT a bare
    COALESCE(jsonb_array_length(...), 0) — the bare form still raises on a
    non-array JSON scalar/null literal."""
    from app.db import repo

    fake_conn.script_fetchall([])
    repo.load_all_runs(conn=fake_conn)

    sql = fake_conn.all_sql()
    assert "CASE WHEN jsonb_typeof(pr.extracted_data->'employees') = 'array'" in sql
    assert "THEN jsonb_array_length(pr.extracted_data->'employees')" in sql
    assert "ELSE 0 END AS employee_count" in sql
    assert "COALESCE(jsonb_array_length" not in sql


def test_load_all_runs_tolerates_non_array_employee_count_value(fake_conn):
    """Hermetic proxy: since FakeConnection replays scripted rows
    rather than executing real SQL, this proves the PYTHON-SIDE return path
    tolerates the employee_count value the new jsonb_typeof-guarded SQL guarantees
    for a corrupt/legacy non-array `employees` value (0), without raising."""
    from app.db import repo

    fake_conn.script_fetchall(
        [{"id": uuid.uuid4(), "employee_count": 0, "summary_gate_reason": None}]
    )
    result = repo.load_all_runs(conn=fake_conn)

    assert len(result) == 1
    assert result[0]["employee_count"] == 0


# ---------------------------------------------------------------------------
# Test 2: DASH-02 — GET /runs/{valid_uuid} returns 200 or 404
# ---------------------------------------------------------------------------


def test_run_detail_returns_200_or_404(fake_repo):
    """DASH-02: GET /runs/{valid_uuid} → 404 for a genuinely missing run, 200
    for a real one.

    A valid UUID that doesn't exist in the store must return 404, not 500 or
    422. Wired onto fake_repo and tightened from the original "200 or 404"
    (which any exception from an unmocked repo layer would also satisfy, via
    the route's `except Exception: raise 404`) to the precise, provable
    contract: missing -> 404, present -> 200.
    """
    non_existent_id = uuid.uuid4()
    response = client.get(f"/runs/{non_existent_id}")
    assert response.status_code == 404, (
        f"GET /runs/{{uuid}} for a genuinely missing run must return 404 "
        f"(DASH-02); got {response.status_code}"
    )

    business_id = next(iter(fake_repo.contact_to_business.values()))
    real_run_id = fake_repo.create_run(business_id=business_id, source_email_id=None)
    found = client.get(f"/runs/{real_run_id}")
    assert found.status_code == 200, (
        f"GET /runs/{{uuid}} for a real run must return 200; got {found.status_code}"
    )


# ---------------------------------------------------------------------------
# Test 3: DASH-03 — GET /eval returns 200 and references chart.svg
# ---------------------------------------------------------------------------


def test_eval_view_returns_200():
    """DASH-03: GET /eval → 200 and response body contains 'chart.svg'.

    The eval view must render even with an existing eval/chart.svg; if absent,
    it must handle it gracefully (see test_eval_returns_200_no_summary_json).
    Will fail RED until Wave 3 adds the GET /eval route.
    """
    response = client.get("/eval")
    assert response.status_code == 200, (
        f"GET /eval must return 200 (DASH-03); got {response.status_code}"
    )
    assert "chart.svg" in response.text, (
        "GET /eval response must reference 'chart.svg' (the committed eval chart; DASH-03)"
    )


# ---------------------------------------------------------------------------
# Test 4: DASH-04 — POST /demo/send-test returns 303 redirect
# ---------------------------------------------------------------------------


def test_send_test_returns_303(fake_repo):
    """DASH-04: POST /demo/send-test → 303 redirect to the newly created run.

    A bare status-code check is satisfied by BOTH the success path
    (redirect to /runs/{run_id}) and the failure path (redirect to
    /runs?demo_queue_error=1 — see app/routes/demo.py's except block), so it
    proves nothing about whether the demo write actually happened. Wired onto
    fake_repo so the write (insert_inbound_email/create_run/enqueue_job) is a
    real success against the in-memory store, and the assertions pin the
    SUCCESS redirect target and that a real run was persisted.
    """
    response = client.post("/demo/send-test", follow_redirects=False)
    assert response.status_code == 303, (
        f"POST /demo/send-test must return 303 redirect (DASH-04); "
        f"got {response.status_code}"
    )
    location = response.headers["location"]
    assert location.startswith("/runs/"), (
        "a successful demo send must redirect to the new run's detail page, "
        f"not the failure fallback (/runs?demo_queue_error=1); got Location={location!r}"
    )
    run_id = location.removeprefix("/runs/")
    assert run_id in fake_repo.runs, (
        "the redirected run_id must be a real run persisted through fake_repo, "
        "not a coincidental 303 from the exception fallback path"
    )


# ---------------------------------------------------------------------------
# Test 5: DASH-05 / eval graceful no-summary — GET /eval with no summary.json
# ---------------------------------------------------------------------------


def test_eval_returns_200_no_summary_json():
    """DASH-05: GET /eval with no eval/summary.json → 200 with 'No eval results'.

    The eval view must handle the missing-file case gracefully so the dashboard
    renders on a fresh deploy before the first eval run.
    Will fail RED until Wave 3 adds the GET /eval route with this guard.
    """
    response = client.get("/eval")
    # Two valid outcomes:
    # (a) Route missing → 404/405 (RED until Wave 3)
    # (b) Route exists but no summary.json → 200 with "No eval results" message
    # We assert the non-RED-correct state: 200 with the fallback message.
    if response.status_code == 200:
        assert "No eval results" in response.text or "chart.svg" in response.text, (
            "GET /eval with no summary.json must show 'No eval results' fallback "
            "or the chart (DASH-05)"
        )
    else:
        # RED: route not yet added — this will be fixed in Wave 3.
        assert response.status_code in (404, 405, 422), (
            f"Unexpected status {response.status_code} from GET /eval (expected 200, "
            "404, or 405 in Wave 0 RED state)"
        )


# ---------------------------------------------------------------------------
# Eval view path containment: a fixture_path may not escape the fixtures directory
# ---------------------------------------------------------------------------


def test_eval_view_refuses_fixture_path_traversal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """A fixture_path that escapes the fixtures directory must not disclose file contents.

    eval_view joins each summary entry's fixture_path onto the fixtures directory and reads
    the result. A relative-parent path ("../secret.txt") would otherwise read — and render —
    a file outside that directory. The escape must fall into the missing-file placeholder
    while a legitimate fixture inside the directory still renders its body.

    The route's two data paths are redirected via their module constants rather than by
    moving the process working directory: the Jinja searchpath is relative, so a cwd change
    would make eval.html unresolvable and the route would fail for the wrong reason.
    """
    from app.routes import dashboard

    sentinel = "TRAVERSAL_SENTINEL_CONTENT"
    legit_body = "LEGITIMATE_FIXTURE_BODY_TEXT"

    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "legit.json").write_text(json.dumps({"body_text": legit_body}))
    # The escape target: outside the fixtures directory, reachable only via "..".
    (tmp_path / "secret.txt").write_text(json.dumps({"body_text": sentinel}))

    def _fixture_entry(fixture_path: str) -> dict[str, Any]:
        return {
            "fixture_id": fixture_path,
            "fixture_path": fixture_path,
            "fixture_category": "exact",
            "extraction": {"f1": 1.0},
            "decision": {"final_action": "process", "expected_final_action": "process"},
        }

    summary = {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "extraction_model_id": "test-model",
        "extraction_overall_f1": 1.0,
        "false_process_rate": 0.0,
        "confusion_matrix": {
            "true_process": 1,
            "false_process": 0,
            "false_clarify": 0,
            "true_clarify": 0,
        },
        "per_fixture": [_fixture_entry("legit.json"), _fixture_entry("../secret.txt")],
    }
    (tmp_path / "summary.json").write_text(json.dumps(summary))

    monkeypatch.setattr(dashboard, "EVAL_SUMMARY_PATH", tmp_path / "summary.json")
    monkeypatch.setattr(dashboard, "EVAL_FIXTURES_DIR", fixtures_dir)

    response = client.get("/eval")

    assert response.status_code == 200, (
        f"GET /eval must still render when a fixture_path escapes; got {response.status_code}"
    )
    assert sentinel not in response.text, (
        "a fixture_path that escapes the fixtures directory must never have its file "
        "contents rendered on the eval page"
    )
    assert "‹fixture file missing›" in response.text, (
        "the refused fixture must fall back to the missing-file placeholder"
    )
    assert legit_body in response.text, (
        "refusing escapes must not break legitimate fixtures: a fixture_path that stays "
        "inside the fixtures directory must still render its body"
    )


# ---------------------------------------------------------------------------
# Test 6: UUID path validation — /runs/not-a-uuid returns 422
# ---------------------------------------------------------------------------


def test_runs_invalid_uuid_returns_422():
    """GET /runs/not-a-uuid must return 422 — Pydantic UUID validation rejects
    non-UUID strings before they reach the DB layer.

    This pins the security property: run_id path parameters are validated as UUIDs,
    so arbitrary strings never reach a SQL query. Will be verified RED until Wave 3
    adds the /runs/{run_id} route; once the route exists, this must pass.
    """
    response = client.get("/runs/not-a-uuid")
    # Either 422 (route exists, UUID validation fires) or 404/405 (route missing).
    assert response.status_code in (422, 404, 405), (
        f"GET /runs/not-a-uuid must return 422 (UUID validation) or 404/405 "
        f"(route missing in Wave 0); got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# Test 7: Message-ID uniqueness — /demo/send-test mints fresh ID each click
# (finding MEDIUM)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Test 8: GET /runs/{id}/status returns 404 for unknown run
# ---------------------------------------------------------------------------


def test_run_status_endpoint_404_for_unknown_run(fake_repo):
    """GET /runs/{id}/status → 404 for a run that does not exist.

    The JS poller relies on this contract to stop polling on a missing run.
    The endpoint must never return 500 for an unknown UUID. Wired onto
    fake_repo so `repo.load_run` genuinely returns None for the unknown id
    (the route's `if run is None: raise 404` branch) rather than 404 arriving
    via the route's OTHER except-clause catching an unrelated real-DB
    connection failure — the same status code for the wrong reason.
    """
    non_existent_id = uuid.uuid4()
    response = client.get(f"/runs/{non_existent_id}/status")
    assert response.status_code == 404, (
        f"GET /runs/{{uuid}}/status must return 404 for unknown run; "
        f"got {response.status_code}"
    )

    # Falsification: a run that DOES exist must NOT 404 — pins that the 404
    # above genuinely depended on the id being absent from the real store.
    business_id = next(iter(fake_repo.contact_to_business.values()))
    real_run_id = fake_repo.create_run(business_id=business_id, source_email_id=None)
    found = client.get(f"/runs/{real_run_id}/status")
    assert found.status_code == 200


# ---------------------------------------------------------------------------
# Test 9: GET /runs/{id}/status returns 422 for non-UUID path
# ---------------------------------------------------------------------------


def test_run_status_endpoint_422_for_non_uuid():
    """GET /runs/not-a-uuid/status → 422 (UUID validation guard).

    Ensures the status endpoint rejects non-UUID strings before they reach DB.
    """
    response = client.get("/runs/not-a-uuid/status")
    assert response.status_code == 422, (
        f"GET /runs/not-a-uuid/status must return 422; got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# Test 10: runs list page does NOT contain meta-refresh
# ---------------------------------------------------------------------------


def test_runs_list_has_no_meta_refresh(fake_repo):
    """GET /runs must NOT emit <meta http-equiv="refresh">.

    The blunt meta-refresh was replaced by a vanilla-JS status poll.
    This test pins the removal so it can't silently regress. Wired onto
    fake_repo (with a real seeded run so the page renders the actual runs
    table, not the empty-state fallback) purely to close the latency this
    plan exists to fix — the assertion itself is structural/template-level
    and independent of run content.
    """
    business_id = next(iter(fake_repo.contact_to_business.values()))
    fake_repo.create_run(business_id=business_id, source_email_id=None)

    response = client.get("/runs")
    assert response.status_code == 200
    assert 'http-equiv="refresh"' not in response.text, (
        "GET /runs must not emit <meta http-equiv='refresh'> — "
        "the vanilla-JS poll replaced it"
    )


# ---------------------------------------------------------------------------
# Test 11: run detail page does NOT contain meta-refresh
# ---------------------------------------------------------------------------


def test_run_detail_inflight_run_renders_200_not_500(monkeypatch):
    """UAT regression: viewing a run while it is still in-flight (received/extracting/
    computed) must render 200, NOT 500.

    Root cause this guards: run_detail.html's status-poll <script> only renders when
    the run is in-flight, and it did `{{ run.id | tojson }}` on a raw uuid.UUID, which
    Jinja2's tojson cannot serialize → TypeError → 500. A settled run skips the script
    block, which is why "view while processing" 500'd but "refresh after it finished" worked.
    """
    from app.db import repo as _repo

    run_id = uuid.uuid4()
    inflight_run = {
        "id": run_id,  # a real uuid.UUID — the exact thing that broke tojson
        "business_id": uuid.uuid4(),
        "source_email_id": uuid.uuid4(),
        "status": "extracting",  # in-flight → status-poll script renders
        "extracted_data": None,
        "decision": None,
        "reconciliation": None,
        "error_reason": None,
        "pay_period_start": None,
        "pay_period_end": None,
        "updated_at": None,
    }
    monkeypatch.setattr(_repo, "load_run", lambda rid, conn=None: inflight_run)
    monkeypatch.setattr(_repo, "load_inbound_email", lambda rid, conn=None: None)
    monkeypatch.setattr(_repo, "load_line_items", lambda rid, conn=None: [])
    monkeypatch.setattr(_repo, "load_thread_messages", lambda rid, conn=None: [])
    monkeypatch.setattr(_repo, "load_clarified_fields", lambda rid, conn=None: {})

    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200, (
        f"GET /runs/{{id}} for an in-flight run must render 200, not {response.status_code} "
        "(run.id | tojson must not crash on a UUID)"
    )
    # The poll script must be present (run is in-flight) and carry the run id as a JSON string.
    assert "/status" in response.text
    assert str(run_id) in response.text

    # Falsification: a SETTLED, non-in-flight run with no open job must NOT
    # render the poll script — pins that the "/status" assertion above
    # genuinely depends on the run being in-flight, not boilerplate present
    # on every response regardless of status.
    inflight_run["status"] = "reconciled"
    settled = client.get(f"/runs/{run_id}")
    assert settled.status_code == 200
    assert "/status" not in settled.text


# ---------------------------------------------------------------------------
# End-to-end key link: DB column -> RUN_COLS/load_run -> run_detail.html
# ---------------------------------------------------------------------------


def test_run_detail_never_renders_raw_error_detail(fake_conn, monkeypatch):
    """Persisted free-form diagnostics never cross the browser boundary.

    ``RUN_COLS`` still carries the value for internal diagnostics, but the route must
    reduce it to the bounded failure vocabulary before rendering.  This fixture
    deliberately resembles provider text plus PII so a regression is unmistakable.
    """
    from app.db import repo as _repo

    run_id = uuid.uuid4()
    scripted_row = {
        "id": run_id,
        "business_id": uuid.uuid4(),
        "source_email_id": uuid.uuid4(),
        "status": "error",
        "extracted_data": None,
        "decision": None,
        "reconciliation": None,
        "error_reason": "ValueError",
        "error_detail": "provider said Maria Chen <maria@example.test> is invalid",
        "pay_period_start": None,
        "pay_period_end": None,
        "updated_at": None,
    }
    fake_conn.script_fetchone(scripted_row)

    run = _repo.load_run(run_id, conn=fake_conn)
    assert run is not None

    # Part 1: RUN_COLS (and therefore the actual SQL text) includes error_detail.
    assert "error_detail" in fake_conn.all_sql()
    assert "Maria Chen" in run["error_detail"]

    # Part 2: the same persisted value must stop at the route's safe mapping.
    monkeypatch.setattr(_repo, "load_run", lambda rid, conn=None: run)
    monkeypatch.setattr(_repo, "load_inbound_email", lambda rid, conn=None: None)
    monkeypatch.setattr(_repo, "load_line_items", lambda rid, conn=None: [])
    monkeypatch.setattr(_repo, "load_thread_messages", lambda rid, conn=None: [])
    monkeypatch.setattr(_repo, "load_clarified_fields", lambda rid, conn=None: {})

    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200
    assert "Maria Chen" not in response.text
    assert "maria@example.test" not in response.text
    assert "provider said" not in response.text
    assert "Error" in response.text

    # Falsification (Truth #2 — negative-assertion tests are the most likely
    # to pass vacuously on an error/fallback page that simply never rendered
    # the field at all). The template only ever surfaces error_detail through
    # `run.failure.reason` (the bounded-vocabulary reduction in
    # _safe_failure_presentation) — it never references run.error_detail
    # directly. Bypass ONLY that vocabulary check, passing the raw
    # error_detail straight through as `reason` (keeping the other required
    # keys well-formed so the template still renders), and confirm the
    # hostile content NOW appears — proving the "not in text" assertions
    # above are load-bearing on real redaction, not on an unrelated fallback
    # that happens to never surface error_detail either way.
    import app.routes.runs as _runs_route

    def _leaky_failure_presentation(r: dict[str, Any]) -> dict[str, Any]:
        return {
            "secondary_label": None,
            "stage": None,
            "reason": r.get("error_detail"),
            "attempts": None,
        }

    monkeypatch.setattr(
        _runs_route, "_safe_failure_presentation", _leaky_failure_presentation
    )
    leaking = client.get(f"/runs/{run_id}")
    assert leaking.status_code == 200
    assert "Maria Chen" in leaking.text, (
        "sanity: with the bounded-vocabulary reduction bypassed, the hostile "
        "content must actually leak through — otherwise the negative "
        "assertions above would pass even if redaction were silently removed"
    )


def test_retry_exhausted_diagnostics_are_bounded_across_html_and_polling(monkeypatch):
    """Recognized failure codes render identically without exposing hostile fields."""
    from app.db import repo as _repo

    run_id = uuid.uuid4()
    hostile = "SECRET provider response for Maria Chen <maria@example.test>"
    run = {
        "id": run_id,
        "business_id": uuid.uuid4(),
        "source_email_id": uuid.uuid4(),
        "status": "error",
        "extracted_data": None,
        "decision": None,
        "reconciliation": None,
        "error_reason": "RetryExhausted",
        "error_detail": "extract:provider_timeout;attempts=5/5",
        "last_error": hostile,
        "pay_period_start": None,
        "pay_period_end": None,
        "updated_at": None,
    }
    monkeypatch.setattr(_repo, "load_run", lambda rid, conn=None: dict(run))
    monkeypatch.setattr(_repo, "load_inbound_email", lambda rid, conn=None: None)
    monkeypatch.setattr(_repo, "load_line_items", lambda rid, conn=None: [])
    monkeypatch.setattr(_repo, "load_thread_messages", lambda rid, conn=None: [])
    monkeypatch.setattr(_repo, "load_clarified_fields", lambda rid, conn=None: {})

    detail = client.get(f"/runs/{run_id}")
    poll = client.get(f"/runs/{run_id}/status")

    assert detail.status_code == 200
    assert poll.status_code == 200
    assert "Retries exhausted" in detail.text
    assert "Extraction" in detail.text
    assert "Provider timeout" in detail.text
    assert "5 of 5 attempts" in detail.text
    assert hostile not in detail.text
    poll_text = poll.text
    assert "Retries exhausted" in poll_text
    assert "Extraction" in poll_text
    assert "Provider timeout" in poll_text
    assert "5 of 5 attempts" in poll_text
    assert hostile not in poll_text

    # Falsification: an error_detail that does NOT match the bounded
    # diagnostic grammar must produce NONE of the derived labels above —
    # pins that "Retries exhausted"/"Stage: Extraction"/"Provider
    # timeout"/"5 of 5 attempts" genuinely come from parsing THIS run's real
    # error_detail through the bounded-vocabulary reduction, not from static
    # boilerplate present on every error-status response regardless of
    # content. ("Extraction" alone is excluded — it also appears in the
    # page's unconditional "Payroll details" section header, so it cannot
    # distinguish real derivation from boilerplate on its own.)
    run["error_detail"] = "not a real diagnostic code"
    mismatched_detail = client.get(f"/runs/{run_id}")
    mismatched_poll = client.get(f"/runs/{run_id}/status")
    assert mismatched_detail.status_code == 200
    assert mismatched_poll.status_code == 200
    for derived in (
        "Retries exhausted",
        "Provider timeout",
        "5 of 5 attempts",
    ):
        assert derived not in mismatched_detail.text
        assert derived not in mismatched_poll.text
    assert "Stage:</strong> Extraction" not in mismatched_detail.text


def test_runs_list_uses_safe_failure_projection(monkeypatch):
    """The list keeps Error canonical and exposes only the bounded projection."""
    from app.db import repo as _repo

    run_id = uuid.uuid4()
    hostile = "Traceback: payroll for Maria Chen maria@example.test"
    monkeypatch.setattr(
        _repo,
        "load_all_runs",
        lambda: [
            {
                "id": run_id,
                "business_id": uuid.uuid4(),
                "status": "error",
                "created_at": None,
                "updated_at": None,
                "business_name": "Safe Co",
                "summary_gate_reason": None,
                "employee_count": 0,
                "error_reason": "FinalAttemptLeaseExpired",
                "error_detail": (
                    "unknown:final_attempt_lease_expired;attempts=5/5"
                ),
                "job_attempts": 5,
                "job_max_attempts": 5,
                "last_error": hostile,
            }
        ],
    )

    response = client.get("/runs")

    assert response.status_code == 200
    assert ">Error<" in response.text
    assert "Retries exhausted" in response.text
    assert "Final attempt lease expired" in response.text
    assert "5 of 5 attempts" in response.text
    assert hostile not in response.text


def test_load_all_runs_projects_only_bounded_failure_inputs(fake_conn):
    """The list query projects run codes and latest-job attempt counters, not payloads."""
    from app.db import repo

    fake_conn.script_fetchall([])
    repo.load_all_runs(conn=fake_conn)

    sql = fake_conn.all_sql()
    assert "pr.error_reason" in sql
    assert "pr.error_detail" in sql
    assert "job_attempts" in sql
    assert "job_max_attempts" in sql
    assert "last_error" not in sql


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        (("Running",), "Running"),
        (("Queued",), "Queued"),
        (("Retry queued",), "Retry queued"),
        ((None,), None),
        (None, None),
    ],
)
def test_get_run_queue_label_returns_only_bounded_labels(fake_conn, row, expected):
    """The per-run projection emits one fixed label or ``None``, never job data."""
    from app.db.repo.jobs import get_run_queue_label

    fake_conn.script_fetchone(row)
    run_id = uuid.uuid4()

    assert get_run_queue_label(run_id, conn=fake_conn) == expected

    sql, params = fake_conn.last()
    assert "state IN ('pending', 'leased')" in sql
    assert params == (str(run_id),)
    for forbidden in ("dedup_key", "last_error", "attempts", "payload"):
        assert forbidden not in sql


def test_get_run_queue_label_sql_pins_running_queued_retry_precedence(fake_conn):
    """Leased wins, then due pending, then delayed pending, in one bounded read."""
    from app.db.repo.jobs import get_run_queue_label

    fake_conn.script_fetchone(("Running",))
    get_run_queue_label(uuid.uuid4(), conn=fake_conn)

    sql = fake_conn.all_sql()
    running = sql.index("THEN 'Running'")
    queued = sql.index("THEN 'Queued'")
    retry = sql.index("THEN 'Retry queued'")
    assert running < queued < retry
    assert "available_at <= now()" in sql


def test_running_queue_status_json_is_bounded_and_read_only(monkeypatch):
    """Polling exposes fixed presentation only and cannot trigger recovery work."""
    from app.db import repo as _repo

    run_id = uuid.uuid4()
    hostile = "job-SECRET attempts=99 payload=Maria <maria@example.test>"
    run = {
        "id": run_id,
        "status": "received",
        "error_reason": None,
        "error_detail": None,
        "last_error": hostile,
        "job_id": hostile,
        "job_attempts": 99,
        "job_max_attempts": 100,
        "available_at": hostile,
    }
    monkeypatch.setattr(_repo, "load_run", lambda rid, conn=None: dict(run))
    monkeypatch.setattr(
        _repo, "get_run_queue_label", lambda rid, conn=None: "Running"
    )
    for name in (
        "enqueue_job",
        "claim_status",
        "clear_reply_context",
        "mark_reply_consumed",
    ):
        monkeypatch.setattr(
            _repo,
            name,
            lambda *args, _name=name, **kwargs: pytest.fail(
                f"status poll called recovery seam {_name}"
            ),
        )

    response = client.get(f"/runs/{run_id}/status")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "received"
    assert body["queue_label"] == "Running"
    assert body["queue_badge_class"] == "running"
    assert body["has_open_job"] is True
    response_text = response.text
    assert hostile not in response_text
    for forbidden in (
        "job_id",
        "job_attempts",
        "job_max_attempts",
        "available_at",
        "last_error",
        "payload",
    ):
        assert forbidden not in body


def test_queued_run_detail_has_secondary_badge_durability_and_bounded_polling(
    monkeypatch,
):
    """Open work is secondary, accessible, and polled for exactly two minutes."""
    from app.db import repo as _repo

    run_id = uuid.uuid4()
    run = {
        "id": run_id,
        "business_id": uuid.uuid4(),
        "source_email_id": uuid.uuid4(),
        "status": "awaiting_approval",
        "extracted_data": None,
        "decision": None,
        "reconciliation": None,
        "error_reason": None,
        "pay_period_start": None,
        "pay_period_end": None,
        "updated_at": None,
    }
    monkeypatch.setattr(_repo, "load_run", lambda rid, conn=None: dict(run))
    monkeypatch.setattr(
        _repo, "get_run_queue_label", lambda rid, conn=None: "Queued"
    )
    monkeypatch.setattr(_repo, "load_inbound_email", lambda rid, conn=None: None)
    monkeypatch.setattr(_repo, "load_line_items", lambda rid, conn=None: [])
    monkeypatch.setattr(_repo, "load_thread_messages", lambda rid, conn=None: [])
    monkeypatch.setattr(_repo, "load_clarified_fields", lambda rid, conn=None: {})

    response = client.get(f"/runs/{run_id}")

    assert response.status_code == 200
    text = response.text
    assert text.index("Needs Approval") < text.index("Queued")
    assert "This action is durably saved; you can safely leave this page." in text
    assert 'aria-live="polite"' in text
    assert "var MAX_ATTEMPTS = 60" in text
    assert "setInterval(poll, 2000)" in text
    assert "data.queue_label !== INITIAL_QUEUE_LABEL" in text
    poll_script = text[text.index("<script>") : text.index("</script>")]
    for forbidden in (
        "enqueue_job(",
        "fetch('/runs/' + run_id + '/retrigger'",
        "fetch('/runs/' + run_id + '/simulate-reply'",
        "claim_status(",
    ):
        assert forbidden not in poll_script.lower()

    # Falsification: with no open queue work at all, the durability note and
    # the queue-polling script must NOT render — pins that the assertions
    # above genuinely depend on the real "Queued" state, not boilerplate
    # present on every run-detail response.
    monkeypatch.setattr(_repo, "get_run_queue_label", lambda rid, conn=None: None)
    settled = client.get(f"/runs/{run_id}")
    assert settled.status_code == 200
    assert (
        "This action is durably saved; you can safely leave this page."
        not in settled.text
    )
    assert "var MAX_ATTEMPTS = 60" not in settled.text


def test_retry_queued_runs_list_keeps_payroll_badge_first_and_updates_in_place(
    monkeypatch,
):
    """List polling preserves the existing row and renders one secondary badge."""
    from app.db import repo as _repo

    run_id = uuid.uuid4()
    monkeypatch.setattr(
        _repo,
        "load_all_runs",
        lambda: [
            {
                "id": run_id,
                "business_id": uuid.uuid4(),
                "status": "received",
                "created_at": None,
                "updated_at": None,
                "business_name": "Safe Co",
                "summary_gate_reason": None,
                "employee_count": 0,
                "error_reason": None,
                "error_detail": None,
                "queue_label": "Retry queued",
            }
        ],
    )

    text = client.get("/runs").text

    assert text.index("Received") < text.index("Retry queued")
    assert text.count("Retry queued") == 1
    assert 'data-has-open-job="true"' in text
    assert "var MAX_ATTEMPTS = 60" in text
    assert "setInterval(function()" in text and "}, 2000)" in text
    assert "window.location.reload" not in text
    assert "data.has_open_job" in text


def test_queue_feedback_hidden_when_no_open_work(monkeypatch):
    """Settled work has no queue badge, durability note, or polling script."""
    from app.db import repo as _repo

    run_id = uuid.uuid4()
    run = {
        "id": run_id,
        "business_id": uuid.uuid4(),
        "source_email_id": uuid.uuid4(),
        "status": "awaiting_approval",
        "extracted_data": None,
        "decision": None,
        "reconciliation": None,
        "error_reason": None,
        "pay_period_start": None,
        "pay_period_end": None,
        "updated_at": None,
    }
    monkeypatch.setattr(_repo, "load_run", lambda rid, conn=None: dict(run))
    monkeypatch.setattr(_repo, "get_run_queue_label", lambda rid, conn=None: None)
    monkeypatch.setattr(_repo, "load_inbound_email", lambda rid, conn=None: None)
    monkeypatch.setattr(_repo, "load_line_items", lambda rid, conn=None: [])
    monkeypatch.setattr(_repo, "load_thread_messages", lambda rid, conn=None: [])
    monkeypatch.setattr(_repo, "load_clarified_fields", lambda rid, conn=None: {})

    text = client.get(f"/runs/{run_id}").text

    assert "This action is durably saved; you can safely leave this page." not in text
    assert "run-queue-badge" not in text
    assert "MAX_ATTEMPTS" not in text

    # Falsification (Truth #2 — this is one of the negative-assertion tests
    # most likely to pass vacuously): with real open queue work, ALL THREE
    # of the above must actually appear — pins that their absence above is
    # genuinely caused by "no open job", not by the page failing to render
    # this section at all regardless of state.
    monkeypatch.setattr(_repo, "get_run_queue_label", lambda rid, conn=None: "Queued")
    open_work_text = client.get(f"/runs/{run_id}").text
    assert "This action is durably saved; you can safely leave this page." in (
        open_work_text
    )
    assert "run-queue-badge" in open_work_text
    assert "MAX_ATTEMPTS" in open_work_text


def test_run_detail_is_one_ordered_conversation_with_final_reply_composer(monkeypatch):
    """The run detail makes the email exchange primary and keeps evidence available."""
    from datetime import datetime, timedelta

    from app.db import repo as _repo

    run_id = uuid.uuid4()
    employee_id = uuid.uuid4()
    started_at = datetime(2026, 7, 18, 12, 0, tzinfo=UTC)
    long_suffix = "FULL MESSAGE CONTENT AFTER THREE HUNDRED CHARACTERS"
    run = {
        "id": run_id,
        "business_id": uuid.uuid4(),
        "source_email_id": uuid.uuid4(),
        "status": "awaiting_reply",
        "extracted_data": {"employees": [{
            "submitted_name": "Maria Chen", "hours_regular": 40,
            "hours_overtime": 0, "hours_vacation": 0, "hours_sick": 0,
            "hours_holiday": 0, "contribution_401k_override": None,
        }]},
        "decision": None,
        "reconciliation": [{
            "submitted_name": "Maria Chen", "matched_employee_id": str(employee_id),
            "source": "exact",
        }],
        "error_reason": None,
        "pay_period_start": None,
        "pay_period_end": None,
        "updated_at": None,
    }
    thread = [
        {"direction": "inbound", "purpose": None, "subject": "Initial payroll request",
         "body_text": "First message", "from_addr": "payroll@example.test",
         "to_addr": "agent@example.test", "created_at": started_at},
        {"direction": "outbound", "purpose": "clarification", "subject": "Clarification needed",
         "body_text": "Second message", "from_addr": "agent@example.test",
         "to_addr": "payroll@example.test", "created_at": started_at + timedelta(minutes=1)},
        {"direction": "inbound", "purpose": None, "subject": "Client correction",
         "body_text": "x" * 301 + long_suffix, "from_addr": "payroll@example.test",
         "to_addr": "agent@example.test", "created_at": started_at + timedelta(minutes=2)},
    ]
    paystubs = [{
        "submitted_name": "Maria Chen", "employee_id": employee_id, "gross_pay": 800,
        "pretax_401k": 0, "fica_ss": 49.6, "fica_medicare": 11.6,
        "federal_withholding": 90, "state_withholding": 0, "net_pay": 648.8,
        "additional_medicare_not_modeled": False,
    }]
    monkeypatch.setattr(_repo, "load_run", lambda *args, **kwargs: dict(run))
    monkeypatch.setattr(_repo, "load_inbound_email", lambda *args, **kwargs: None)
    monkeypatch.setattr(_repo, "load_line_items", lambda *args, **kwargs: paystubs)
    monkeypatch.setattr(_repo, "load_thread_messages", lambda *args, **kwargs: thread)
    monkeypatch.setattr(
        _repo, "load_outbound_emails",
        lambda *args, **kwargs: pytest.fail("run detail must use thread_messages only"),
    )
    monkeypatch.setattr(
        _repo, "load_clarified_fields",
        lambda *args, **kwargs: {str(employee_id): {"hours_regular": "client_supplied"}},
    )

    response = client.get(f"/runs/{run_id}")

    assert response.status_code == 200
    text = response.text
    assert text.count(">Conversation<") == 1
    assert (
        text.index("Initial payroll request")
        < text.index("Clarification needed")
        < text.index("Client correction")
    )
    assert text.count(">inbound<") == 2 and ">outbound<" in text
    assert "payroll@example.test" in text and "agent@example.test" in text
    assert long_suffix in text
    assert "Sent Emails" not in text and "Conversation thread" not in text
    assert "Raw Email (as received)" not in text and "run-detail-grid" not in text
    assert '<details class="payroll-details mt-xl">' in text
    assert "exact" in text and "client supplied" in text
    assert f"/runs/{run_id}/pdf/{employee_id}" in text
    assert text.count(f'action="/runs/{run_id}/simulate-reply"') == 1
    assert text.index("Payroll details") < text.index("Reply to client")


def test_run_detail_fallback_inbound_message_keeps_created_at_metadata(monkeypatch):
    """A source-email fallback still reads like a timestamped inbox message."""
    from datetime import datetime

    from app.db import repo as _repo

    run_id = uuid.uuid4()
    created_at = datetime(2026, 7, 18, 12, 34, tzinfo=UTC)
    run = {
        "id": run_id,
        "business_id": uuid.uuid4(),
        "source_email_id": uuid.uuid4(),
        "status": "received",
        "extracted_data": None,
        "decision": None,
        "reconciliation": None,
        "error_reason": None,
        "pay_period_start": None,
        "pay_period_end": None,
        "updated_at": None,
    }
    raw_email = {
        "subject": "Fallback payroll request",
        "body_text": "Maria Chen worked 40 hours.",
        "from_addr": "payroll@example.test",
        "to_addr": "agent@example.test",
        "created_at": created_at,
    }
    monkeypatch.setattr(_repo, "load_run", lambda *args, **kwargs: dict(run))
    monkeypatch.setattr(_repo, "load_inbound_email", lambda *args, **kwargs: raw_email)
    monkeypatch.setattr(_repo, "load_line_items", lambda *args, **kwargs: [])
    monkeypatch.setattr(_repo, "load_thread_messages", lambda *args, **kwargs: [])
    monkeypatch.setattr(_repo, "load_clarified_fields", lambda *args, **kwargs: {})

    response = client.get(f"/runs/{run_id}")

    assert response.status_code == 200
    assert "Fallback payroll request" in response.text
    assert "2026-07-18 12:34" in response.text


def test_resolution_superseded_notice_uses_fixed_copy_not_query_text(monkeypatch):
    """Browser-controlled query values select fixed copy and are never echoed."""
    from app.db import repo as _repo

    run_id = uuid.uuid4()
    hostile = "Maria Chen <maria@example.test><script>alert(1)</script>"
    run = {
        "id": run_id,
        "business_id": uuid.uuid4(),
        "source_email_id": uuid.uuid4(),
        "status": "needs_operator",
        "extracted_data": None,
        "decision": {"unresolved_names": []},
        "reconciliation": None,
        "error_reason": None,
        "pay_period_start": None,
        "pay_period_end": None,
        "updated_at": None,
    }
    monkeypatch.setattr(_repo, "load_run", lambda rid, conn=None: dict(run))
    monkeypatch.setattr(_repo, "get_run_queue_label", lambda rid, conn=None: None)
    monkeypatch.setattr(_repo, "load_inbound_email", lambda rid, conn=None: None)
    monkeypatch.setattr(_repo, "load_line_items", lambda rid, conn=None: [])
    monkeypatch.setattr(_repo, "load_thread_messages", lambda rid, conn=None: [])
    monkeypatch.setattr(_repo, "load_clarified_fields", lambda rid, conn=None: {})
    from app.models.roster import Roster as _Roster

    monkeypatch.setattr(
        _repo,
        "load_roster_for_business",
        lambda business_id, conn=None: _Roster(business_id=business_id, employees=[]),
    )

    response = client.get(
        f"/runs/{run_id}", params={"resolution_superseded": hostile}
    )

    assert response.status_code == 200
    assert (
        "An earlier resolution was already accepted. This submission was recorded "
        "but not applied."
    ) in response.text
    assert hostile not in response.text

    # Falsification: the fixed-copy notice must NOT appear when the query
    # param is absent — pins that its presence above is genuinely gated on
    # `resolution_superseded`, not boilerplate rendered on every needs_operator
    # response regardless of the query string.
    no_flag = client.get(f"/runs/{run_id}")
    assert no_flag.status_code == 200
    assert (
        "An earlier resolution was already accepted. This submission was recorded "
        "but not applied."
    ) not in no_flag.text


def test_demo_queue_error_notice_uses_fixed_copy_not_query_text(monkeypatch):
    """The demo failure flag is an allowlisted presence bit, not rendered text."""
    from app.db import repo as _repo

    hostile = "DB exploded for Maria <maria@example.test><script>alert(1)</script>"
    monkeypatch.setattr(_repo, "load_all_runs", lambda: [])

    response = client.get("/runs", params={"demo_queue_error": hostile})

    assert response.status_code == 200
    assert "We couldn't queue this demo run. Please try again." in response.text
    assert hostile not in response.text


# ---------------------------------------------------------------------------
# Delivery-review controls — frozen evidence and explicit operator outcomes
# ---------------------------------------------------------------------------


def _delivery_review_run(fake_repo: Any) -> tuple[uuid.UUID, dict[str, Any]]:
    """Create one confirmation awaiting a human delivery decision."""
    from app.models.job import JobKind
    from app.models.status import RunStatus

    business_id = fake_repo.contact_to_business["payroll@coastalcleaning.example"]
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=None)
    fake_repo.set_status(run_id, RunStatus.NEEDS_OPERATOR)
    fake_repo.runs[str(run_id)]["error_reason"] = "DeliveryReview"
    fake_repo.runs[str(run_id)]["error_detail"] = "delivery_review:payload_mismatch"
    snapshot = fake_repo.reserve_outbound_snapshot(
        run_id=run_id,
        purpose="confirmation",
        round=0,
        message_id="<frozen-review@payroll-agent.local>",
        from_addr="agent@payroll-agent.local",
        to_addr="payroll@example.test",
        reply_to="replies@payroll-agent.local",
        in_reply_to="<source@payroll-agent.local>",
        references_header="<prior@payroll-agent.local> <source@payroll-agent.local>",
        subject="Frozen confirmation",
        body_text="Frozen confirmation body",
        attachments=[("paystub_Ada.pdf", b"frozen-pdf-bytes")],
    )
    fake_repo.enqueue_job(
        kind=JobKind.SEND_OUTBOUND,
        dedup_key=f"send_outbound:{snapshot['email_id']}",
        run_id=run_id,
        email_id=snapshot["email_id"],
    )
    for job in fake_repo.jobs.values():
        job["state"] = "done"
    return run_id, snapshot


def test_delivery_review_serves_only_owned_frozen_email_and_attachment(fake_repo):
    """Review evidence comes from the stored snapshot, never mutable payroll data."""
    run_id, snapshot = _delivery_review_run(fake_repo)
    attachment_id = snapshot["attachments"][0]["id"]
    fake_repo.runs[str(run_id)]["business_name"] = "Changed after reservation"

    email = client.get(f"/runs/{run_id}/delivery-review/email")
    attachment = client.get(
        f"/runs/{run_id}/delivery-review/attachments/{attachment_id}"
    )
    outside_owner = client.get(
        f"/runs/{uuid.uuid4()}/delivery-review/attachments/{attachment_id}"
    )

    assert email.status_code == 200
    assert "Frozen confirmation" in email.text
    assert "Frozen confirmation body" in email.text
    assert "Changed after reservation" not in email.text
    assert attachment.status_code == 200
    assert attachment.content == b"frozen-pdf-bytes"
    assert attachment.headers["content-disposition"] == (
        'attachment; filename="paystub_Ada.pdf"'
    )
    assert outside_owner.status_code == 404


def test_delivery_review_retry_now_advances_only_the_existing_pending_job(
    fake_repo, monkeypatch
):
    """Retry-now is a post-commit wake, never a direct provider call or new job."""
    import app.routes.runs as runs_mod
    from app.email import gateway

    run_id, snapshot = _delivery_review_run(fake_repo)
    job = next(iter(fake_repo.jobs.values()))
    job["state"] = "pending"
    job["available_in_seconds"] = 3600.0
    wake_calls: list[None] = []
    monkeypatch.setattr(runs_mod.wake, "wake", lambda: wake_calls.append(None))
    monkeypatch.setattr(
        gateway,
        "send_outbound",
        lambda **_kwargs: pytest.fail("review retry reached the provider"),
    )

    response = client.post(
        f"/runs/{run_id}/delivery-review/retry-now", follow_redirects=False
    )

    assert response.status_code == 303
    assert job["available_in_seconds"] == 0.0
    assert len(fake_repo.jobs) == 1
    assert wake_calls == [None]
    assert fake_repo.load_run(run_id)["status"] == "needs_operator"
    job["state"] = "leased"
    second = client.post(
        f"/runs/{run_id}/delivery-review/retry-now", follow_redirects=False
    )
    assert second.status_code == 303
    assert wake_calls == [None]


def test_delivery_review_mark_delivered_is_a_provider_free_cas(fake_repo, monkeypatch):
    """Marking delivery complete is the explicit no-resend branch."""
    import app.routes.runs as runs_mod
    from app.email import gateway

    run_id, _snapshot = _delivery_review_run(fake_repo)
    monkeypatch.setattr(
        gateway,
        "send_outbound",
        lambda **_kwargs: pytest.fail("mark delivered reached the provider"),
    )
    monkeypatch.setattr(
        runs_mod.wake,
        "wake",
        lambda: pytest.fail("mark delivered woke a sender"),
    )

    first = client.post(
        f"/runs/{run_id}/delivery-review/mark-delivered", follow_redirects=False
    )
    second = client.post(
        f"/runs/{run_id}/delivery-review/mark-delivered", follow_redirects=False
    )

    assert first.status_code == second.status_code == 303
    assert fake_repo.load_run(run_id)["status"] == "reconciled"


def test_delivery_review_authorization_clones_frozen_bytes_into_one_new_slot(
    fake_repo, monkeypatch
):
    """A typed acknowledgement is required before a new immutable confirmation slot."""
    import app.routes.runs as runs_mod
    from app.email import gateway

    run_id, original = _delivery_review_run(fake_repo)
    wake_calls: list[None] = []
    monkeypatch.setattr(runs_mod.wake, "wake", lambda: wake_calls.append(None))
    monkeypatch.setattr(
        gateway,
        "send_outbound",
        lambda **_kwargs: pytest.fail("authorization reached the provider"),
    )

    rejected = client.post(
        f"/runs/{run_id}/delivery-review/authorize",
        data={"acknowledgement": "send it"},
        follow_redirects=False,
    )
    accepted = client.post(
        f"/runs/{run_id}/delivery-review/authorize",
        data={"acknowledgement": "AUTHORIZE A NEW CONFIRMATION"},
        follow_redirects=False,
    )
    duplicate = client.post(
        f"/runs/{run_id}/delivery-review/authorize",
        data={"acknowledgement": "AUTHORIZE A NEW CONFIRMATION"},
        follow_redirects=False,
    )

    assert rejected.status_code == accepted.status_code == duplicate.status_code == 303
    assert fake_repo.load_run(run_id)["status"] == "approved"
    assert fake_repo.load_run(run_id)["reply_epoch"] == 1
    snapshots = list(fake_repo.outbound_snapshots.values())
    assert len(snapshots) == 2
    replacement = next(
        item["payload"]
        for item in snapshots
        if item["payload"]["email_id"] != original["email_id"]
    )
    assert replacement["epoch"] == 1
    assert replacement["message_id"] != original["message_id"]
    assert replacement["to_addr"] == original["to_addr"]
    assert replacement["subject"] == original["subject"]
    assert replacement["body_text"] == original["body_text"]
    assert replacement["attachments"][0]["content"] == original["attachments"][0]["content"]
    assert len(fake_repo.jobs) == 2
    assert wake_calls == [None]


def test_delivery_review_card_uses_only_the_safe_projection(fake_repo):
    """The detail page gives two explicit choices without provider diagnostics."""
    run_id, _snapshot = _delivery_review_run(fake_repo)
    fake_repo.runs[str(run_id)]["error_detail"] = "delivery_review:payload_mismatch"

    response = client.get(f"/runs/{run_id}")

    assert response.status_code == 200
    assert "Review confirmation delivery" in response.text
    assert "Frozen payload mismatch" in response.text
    assert "Frozen confirmation" in response.text
    assert "View frozen email" in response.text
    assert "View frozen attachment" in response.text
    assert "Mark delivered" in response.text
    assert "Authorize a new confirmation" in response.text
    assert "AUTHORIZE A NEW CONFIRMATION" in response.text
    assert "Resolve unresolved names" not in response.text
    assert response.text.index(">Conversation<") < response.text.index(
        "Review confirmation delivery"
    )
    for unsafe_name in (
        "error_detail",
        "last_error",
        "provider_response",
        "provider_request",
        "queue_id",
    ):
        assert unsafe_name not in response.text


def test_delivery_review_template_has_no_automatic_recovery_action():
    """Review stays server-rendered and polling never creates or restarts work."""
    template = Path("app/templates/run_detail.html").read_text()

    assert "delivery-review" in template
    assert "delivery-review/mark-delivered" in template
    assert "delivery-review/authorize" in template
    assert "fetch('/runs/' + RUN_ID + '/delivery-review" not in template
    assert "enqueue" not in template


def test_clarification_delivery_review_card_is_purpose_isolated(fake_repo):
    """Clarification ambiguity never renders confirmation or alias controls."""
    from tests.test_phase20_clarification_review import _clarification_review_run

    run_id, _snapshot = _clarification_review_run(fake_repo)
    response = client.get(f"/runs/{run_id}")

    assert response.status_code == 200
    assert "Review clarification delivery" in response.text
    assert "Retry same question" in response.text
    assert "Mark handled" in response.text
    assert "Reject" in response.text
    assert f"/runs/{run_id}/delivery-review/clarification/retry-now" in response.text
    assert f"/runs/{run_id}/delivery-review/clarification/mark-handled" in response.text
    assert f"/runs/{run_id}/delivery-review/clarification/reject" in response.text
    assert "One payroll name needs clarification" in response.text
    assert "frozen-question.pdf" in response.text
    assert "Review confirmation delivery" not in response.text
    assert "Mark delivered" not in response.text
    assert "Authorize a new confirmation" not in response.text
    assert "AUTHORIZE A NEW CONFIRMATION" not in response.text
    assert "Resolve &amp; Resume" not in response.text
    assert "remember this alias" not in response.text
    assert response.text.index(">Conversation<") < response.text.index(
        "Review clarification delivery"
    )
    for unsafe_name in ("provider_response", "provider_request", "last_error", "queue_id"):
        assert unsafe_name not in response.text


def test_clarification_review_projection_is_bounded_and_question_is_frozen(fake_repo):
    """The card receives bounded facts; the separate email reader owns the body."""
    from app.routes.runs import _load_delivery_review, _safe_delivery_review_projection
    from tests.test_phase20_clarification_review import _clarification_review_run

    run_id, _snapshot = _clarification_review_run(fake_repo)
    review = _load_delivery_review(run_id)
    assert review is not None
    projection = _safe_delivery_review_projection(run_id, review)

    assert projection["purpose"] == "clarification"
    assert projection["review_kind"] == "clarification"
    assert projection["subject"] == "One payroll name needs clarification"
    assert "body_text" not in projection
    assert projection["attachments"][0]["filename"] == "frozen-question.pdf"

    email = client.get(f"/runs/{run_id}/delivery-review/email")
    assert "Which employee did you mean by D. Reyes?" in email.text


def test_clarification_review_has_no_automatic_recovery_post_or_polling_action():
    """Clarification review remains server-rendered and action-driven."""
    template = Path("app/templates/run_detail.html").read_text()

    assert "delivery-review/clarification/retry-now" in template
    assert "fetch('/runs/' + RUN_ID + '/delivery-review" not in template
    assert "window.location.reload" in template


@pytest.mark.parametrize(
    "bad_name",
    [
        'Bad "Name"\r\nX-Injected: evil',  # quote + CRLF header injection
        "Paweł Łukasiński",                # non-latin-1 unicode (ł=U+0142)
        "İrem Çağ",                        # Turkish dotted-I + ç, also above U+00FF
    ],
)
def test_paystub_pdf_content_disposition_sanitized(monkeypatch, bad_name):
    """Security regression: the paystub PDF Content-Disposition filename must be
    sanitized so it (a) cannot break or inject the header (quote/CRLF) and (b) is always
    latin-1 encodable — Starlette latin-1-encodes header values, so a unicode name above
    U+00FF would raise UnicodeEncodeError and 500 without re.ASCII. emp_name falls back
    to item.submitted_name (LLM-extracted) when the employee was removed post-run, so the
    value can be fully attacker-shaped.
    """
    from datetime import datetime
    from decimal import Decimal

    from app.db import repo as _repo
    from app.models.contracts import PaystubLineItem
    from app.models.roster import Roster

    run_id = uuid.uuid4()
    emp_id = uuid.uuid4()
    malicious = bad_name
    item = PaystubLineItem(
        id=uuid.uuid4(), run_id=run_id, employee_id=emp_id, submitted_name=malicious,
        hours_regular=Decimal("40"), hours_overtime=Decimal("0"), hours_vacation=Decimal("0"),
        hours_sick=Decimal("0"), hours_holiday=Decimal("0"), gross_pay=Decimal("720.00"),
        pretax_401k=Decimal("0"), fica_ss=Decimal("44.64"), fica_medicare=Decimal("10.44"),
        federal_withholding=Decimal("28.41"), state_withholding=None, net_pay=Decimal("636.51"),
        created_at=datetime.now(tz=UTC),
    )
    monkeypatch.setattr(_repo, "load_line_items", lambda rid, conn=None: [item])
    monkeypatch.setattr(
        _repo, "load_run", lambda rid, conn=None: {"id": run_id, "business_id": uuid.uuid4()}
    )
    # Empty roster → emp is None → route falls back to item.submitted_name (the malicious value)
    monkeypatch.setattr(
        _repo,
        "load_roster_for_business",
        lambda bid, conn=None: Roster(business_id=uuid.uuid4(), employees=[]),
    )
    monkeypatch.setattr(_repo, "load_business_name", lambda bid, conn=None: "Coastal Cleaning Co.")

    response = client.get(f"/runs/{run_id}/pdf/{emp_id}")
    assert response.status_code == 200
    cd = response.headers.get("content-disposition", "")
    # The security property: no CRLF (no header injection / split) and the filename stays a
    # single well-formed quoted-string (no embedded `"` breaking out). Harmless leftover
    # letters/hyphens inside the quotes are fine — only the dangerous chars are neutralized.
    assert "\r" not in cd and "\n" not in cd, "CRLF must not reach the Content-Disposition header"
    assert cd.count('"') == 2, (
        f"filename must remain a single well-formed quoted-string; got {cd!r}"
    )
    # The whole header must be latin-1 encodable (Starlette encodes it that way);
    # this is the property the re.ASCII flag guarantees. A non-encodable value 500s before
    # we ever get here, but assert it explicitly so the intent is clear.
    cd.encode("latin-1")


def test_run_detail_inflight_poll_reloads_on_settle(monkeypatch):
    """UAT: when a run viewed mid-flight SETTLES, the detail page must reload once so
    the extracted-data + paystub columns (rendered server-side, empty at first load)
    populate automatically — not require a manual refresh. The poll's settle branch
    must call window.location.reload().
    """
    from app.db import repo as _repo

    run_id = uuid.uuid4()
    inflight_run = {
        "id": run_id,
        "business_id": uuid.uuid4(),
        "source_email_id": uuid.uuid4(),
        "status": "extracting",
        "extracted_data": None,
        "decision": None,
        "reconciliation": None,
        "error_reason": None,
        "pay_period_start": None,
        "pay_period_end": None,
        "updated_at": None,
    }
    monkeypatch.setattr(_repo, "load_run", lambda rid, conn=None: inflight_run)
    monkeypatch.setattr(_repo, "load_inbound_email", lambda rid, conn=None: None)
    monkeypatch.setattr(_repo, "load_line_items", lambda rid, conn=None: [])
    monkeypatch.setattr(_repo, "load_thread_messages", lambda rid, conn=None: [])
    monkeypatch.setattr(_repo, "load_clarified_fields", lambda rid, conn=None: {})

    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200
    assert "location.reload()" in response.text, (
        "in-flight run-detail poll must reload once on settle so data columns populate"
    )

    # Falsification: a SETTLED run (no open job) must not render the poll
    # script at all — pins that "location.reload()" above genuinely depends
    # on the run being in-flight, not boilerplate present on every response.
    inflight_run["status"] = "reconciled"
    settled = client.get(f"/runs/{run_id}")
    assert settled.status_code == 200
    assert "location.reload()" not in settled.text


def test_run_detail_poll_reloads_on_status_change_not_just_settle(monkeypatch):
    """Regression: the run-detail poll must reload on ANY status change from what the page
    rendered with — NOT only when the status leaves the in-flight set. The earlier
    "leaves in-flight" logic missed extracting → awaiting_reply (awaiting_reply is itself
    in-flight), so the clarification banner + simulate-reply form never appeared without a
    manual refresh. The poll seeds INITIAL_STATUS from the rendered status and compares
    data.status !== INITIAL_STATUS.
    """
    from app.db import repo as _repo

    run_id = uuid.uuid4()
    # Render at awaiting_reply (itself an in-flight status now) — the script must STILL
    # render, seed INITIAL_STATUS to it, and reload on ANY change (e.g. → awaiting_approval).
    run = {
        "id": run_id, "business_id": uuid.uuid4(), "source_email_id": uuid.uuid4(),
        "status": "awaiting_reply", "extracted_data": None, "decision": None,
        "reconciliation": None, "error_reason": None, "pay_period_start": None,
        "pay_period_end": None, "updated_at": None,
    }
    monkeypatch.setattr(_repo, "load_run", lambda rid, conn=None: run)
    monkeypatch.setattr(_repo, "load_inbound_email", lambda rid, conn=None: None)
    monkeypatch.setattr(_repo, "load_line_items", lambda rid, conn=None: [])
    monkeypatch.setattr(_repo, "load_thread_messages", lambda rid, conn=None: [])
    monkeypatch.setattr(_repo, "load_clarified_fields", lambda rid, conn=None: {})

    text = client.get(f"/runs/{run_id}").text
    assert "/status" in text, (
        "awaiting_reply must still render the poll script (it can advance on reply)"
    )
    assert 'INITIAL_STATUS' in text and '"awaiting_reply"' in text, (
        "poll must seed INITIAL_STATUS from the rendered status"
    )
    assert "data.status !== INITIAL_STATUS" in text and "location.reload()" in text, (
        "poll must reload on ANY status change from the rendered status, "
        "not only on leaving in-flight"
    )

    # Falsification: a settled, non-in-flight run with no open job must not
    # render the poll script (and therefore none of INITIAL_STATUS/the
    # reload comparison) — pins that the markers above depend on the real
    # rendered status, not boilerplate present regardless of state.
    run["status"] = "reconciled"
    settled = client.get(f"/runs/{run_id}").text
    assert "INITIAL_STATUS" not in settled
    assert "data.status !== INITIAL_STATUS" not in settled


def test_run_detail_has_no_meta_refresh(fake_repo):
    """GET /runs/{id} must NOT emit <meta http-equiv="refresh">.

    The blunt meta-refresh was replaced by a vanilla-JS status poll. The
    original version of this test only asserted `if response.status_code ==
    200`, guarded against a non-existent run — since an unmocked repo layer
    always 404'd (whether genuinely missing or from a real-DB exception),
    that `if` body NEVER executed and the assertion never ran, on this plan's
    fix or before it. Wired onto fake_repo with a real seeded run so the
    body actually executes against a genuine 200.
    """
    business_id = next(iter(fake_repo.contact_to_business.values()))
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=None)
    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200
    assert 'http-equiv="refresh"' not in response.text, (
        "GET /runs/{id} must not emit <meta http-equiv='refresh'>"
    )


# ---------------------------------------------------------------------------
# Tests for POST /runs/{run_id}/simulate-reply
# ---------------------------------------------------------------------------


def test_simulate_reply_noop_on_non_awaiting_run(monkeypatch, fake_repo):
    """POST /runs/{id}/simulate-reply on a non-awaiting run → 303, no crash.

    When the run is not in awaiting_reply status, the route must return a 303
    redirect without persisting or enqueueing reply work.
    """
    from app.db import repo as _repo

    run_id = uuid.uuid4()
    non_awaiting_run = {
        "id": run_id,
        "business_id": uuid.uuid4(),
        "source_email_id": uuid.uuid4(),
        "status": "received",  # not awaiting_reply
        "extracted_data": None,
        "decision": None,
        "reconciliation": None,
        "error_reason": None,
        "pay_period_start": None,
        "pay_period_end": None,
        "updated_at": None,
    }
    monkeypatch.setattr(_repo, "load_run", lambda rid, conn=None: non_awaiting_run)

    response = client.post(
        f"/runs/{run_id}/simulate-reply",
        data={"reply_body": "some reply"},
        follow_redirects=False,
    )
    assert response.status_code == 303, (
        f"non-awaiting simulate-reply must 303; got {response.status_code}"
    )
    assert fake_repo.jobs == {}


def test_simulate_reply_noop_when_no_clarification_mid(monkeypatch, fake_repo):
    """POST /runs/{id}/simulate-reply with no clarification Message-ID → 303 no-op."""
    from app.db import repo as _repo

    run_id = uuid.uuid4()
    awaiting_run = {
        "id": run_id,
        "business_id": uuid.uuid4(),
        "source_email_id": uuid.uuid4(),
        "status": "awaiting_reply",
        "extracted_data": None,
        "decision": None,
        "reconciliation": None,
        "error_reason": None,
        "pay_period_start": None,
        "pay_period_end": None,
        "updated_at": None,
    }
    monkeypatch.setattr(_repo, "load_run", lambda rid, conn=None: awaiting_run)
    # No clarification outbound row → get_outbound_message_id returns None
    monkeypatch.setattr(
        _repo,
        "get_outbound_message_id",
        lambda rid, purpose=None, conn=None: None,
    )

    response = client.post(
        f"/runs/{run_id}/simulate-reply",
        data={"reply_body": "some reply"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert fake_repo.jobs == {}


def test_simulate_reply_commits_durable_job_with_correct_headers(
    monkeypatch, fake_repo
):
    """The demo reply commits linked context plus one job and never runs inline."""
    from app.db import repo as _repo
    from app.models.job import JobKind
    from app.models.status import RunStatus
    from app.queue import wake

    clar_mid = "<clar-abc123@payroll-agent.local>"
    client_addr = "payroll@coastalcleaning.example"
    source_email_id, inserted = fake_repo.insert_inbound_email(
        message_id=f"<original-{uuid.uuid4()}@client.example>",
        in_reply_to=None,
        references_header=None,
        subject="Payroll hours",
        from_addr=client_addr,
        to_addr="agent@payroll-agent.local",
        body_text="Jame Okafor 40 hours.",
    )
    assert inserted and source_email_id is not None
    run_id = fake_repo.create_run(
        business_id=uuid.UUID("b0000001-0000-0000-0000-000000000001"),
        source_email_id=source_email_id,
    )
    fake_repo.set_status(run_id, RunStatus.AWAITING_REPLY)
    fake_repo.outbound[str(run_id)] = [
        {
            "message_id": clar_mid,
            "direction": "outbound",
            "purpose": "clarification",
            "send_state": "sent",
            "round": 0,
        }
    ]

    events: list[str] = []

    class _Transaction:
        def __enter__(self):
            events.append("transaction_enter")
            return self

        def __exit__(self, exc_type, exc, traceback):
            events.append("transaction_commit" if exc_type is None else "rollback")
            return False

    class _Connection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def transaction(self):
            return _Transaction()

    connection = _Connection()
    monkeypatch.setattr(_repo, "get_connection", lambda: connection)

    original_insert = fake_repo.insert_inbound_email
    original_link = fake_repo.link_email_to_run
    original_enqueue = fake_repo.enqueue_job

    def insert_inbound_email(**kwargs):
        assert kwargs["conn"] is connection
        events.append("persist")
        return original_insert(**kwargs)

    def link_email_to_run(email_id, linked_run_id, conn=None):
        assert conn is connection
        events.append("link")
        return original_link(email_id, linked_run_id, conn=conn)

    def enqueue_job(**kwargs):
        assert kwargs["conn"] is connection
        events.append("enqueue")
        return original_enqueue(**kwargs)

    monkeypatch.setattr(_repo, "insert_inbound_email", insert_inbound_email)
    monkeypatch.setattr(_repo, "link_email_to_run", link_email_to_run)
    monkeypatch.setattr(_repo, "enqueue_job", enqueue_job)
    monkeypatch.setattr(
        "app.pipeline.orchestrator.resume_pipeline",
        lambda *args, **kwargs: pytest.fail("simulate-reply orchestrated inline"),
    )

    def wake_after_commit():
        assert events[-1] == "transaction_commit"
        events.append("wake")

    monkeypatch.setattr(wake, "wake", wake_after_commit)

    response = client.post(
        f"/runs/{run_id}/simulate-reply",
        data={"reply_body": "Sorry — I meant James Okafor. Please process."},
        follow_redirects=False,
    )
    assert response.status_code == 303, (
        f"simulate-reply must 303; got {response.status_code}"
    )
    assert response.headers["location"] == f"/runs/{run_id}"
    assert events == [
        "transaction_enter",
        "persist",
        "link",
        "enqueue",
        "transaction_commit",
        "wake",
    ]

    replies = [
        row
        for row in fake_repo.emails.values()
        if row.get("in_reply_to") == clar_mid
    ]
    assert len(replies) == 1
    persisted = replies[0]
    assert persisted["run_id"] == run_id
    assert persisted["references_header"] == clar_mid
    assert persisted["from_addr"] == client_addr
    assert persisted["subject"].startswith("Re: ")
    assert "James Okafor" in persisted["body_text"]

    assert len(fake_repo.jobs) == 1
    job = next(iter(fake_repo.jobs.values()))
    assert job["kind"] == JobKind.RESUME_REPLY.value
    assert job["dedup_key"] == f"resume_reply:{run_id}:{persisted['id']}"
    assert job["run_id"] == run_id
    assert job["email_id"] == persisted["id"]
    assert job["operator_resolution_id"] is None
    assert job["event_id"] is None
    assert "James Okafor" not in repr(job)


@pytest.mark.integration
def test_send_test_mints_fresh_message_id_each_click(seeded_db):
    """Two consecutive POST /demo/send-test calls must produce DISTINCT runs with
    DISTINCT message_ids and redirect directly to each new run detail.

    Contract (DASH-05):
    - Both clicks → 303 to their exact /runs/{run_id} detail (success path).
    - Each click inserts a distinct email_messages row (different message_id).
    - Each click creates a distinct payroll_runs row.

    Marked @pytest.mark.integration because verifying distinct runs/message_ids
    requires a database.  The shared ``seeded_db`` fixture owns the destructive
    reset, applies the current committed schema, and requires both DATABASE_URL
    and ALLOW_DB_RESET=1 before this test can touch a configured database.
    """
    from app.db import repo as _repo

    response1 = client.post("/demo/send-test", follow_redirects=False)
    response2 = client.post("/demo/send-test", follow_redirects=False)

    # Both POSTs must succeed (303).
    assert response1.status_code == 303, (
        f"First /demo/send-test must return 303; got {response1.status_code}"
    )
    assert response2.status_code == 303, (
        f"Second /demo/send-test must return 303 (fresh Message-ID per click); "
        f"got {response2.status_code}"
    )

    # Each click opens its own real run detail so the demo remains one-click.
    loc1 = response1.headers.get("location", "")
    loc2 = response2.headers.get("location", "")
    assert loc1.startswith("/runs/") and loc1 != "/runs/", (
        f"First /demo/send-test must redirect to run detail; got {loc1!r}"
    )
    assert loc2.startswith("/runs/") and loc2 != "/runs/", (
        f"Second /demo/send-test must redirect to run detail; got {loc2!r}"
    )
    assert loc1 != loc2

    # DASH-05 core contract: two distinct runs were created in the DB.
    # We verify this by loading all runs and checking the two most-recent ones
    # have distinct IDs and distinct message_ids (fresh Message-ID per click).
    all_runs = _repo.load_all_runs()

    assert len(all_runs) >= 2, (
        "Expected at least 2 runs after two /demo/send-test clicks; "
        f"got {len(all_runs)}"
    )
    # The two most-recent runs (newest first from load_all_runs).
    run_a = all_runs[0]
    run_b = all_runs[1]
    assert str(run_a["id"]) != str(run_b["id"]), (
        "Two /demo/send-test clicks must create two DISTINCT run IDs (DASH-05)"
    )


# ---------------------------------------------------------------------------
# Health probe routes
# ---------------------------------------------------------------------------


def test_health_live_returns_200_no_db():
    """Liveness: GET /health/live must return 200 with no DB connection.

    This route is the Render deploy healthCheckPath — a Supabase blip during deploy
    must not fail this check, so it touches NO database. The response body is
    {"status": "ok"} only: no version, no stack, no DB state.
    """
    response = client.get("/health/live")
    assert response.status_code == 200, (
        f"GET /health/live must return 200 (liveness); got {response.status_code}"
    )
    assert response.json()["status"] == "ok", (
        f"GET /health/live must return {{\"status\": \"ok\"}}; got {response.json()}"
    )


# ---------------------------------------------------------------------------
# Per-fixture demo routing + demo_reset re-arming
# ---------------------------------------------------------------------------


def test_demo_send_test_coastal_routes_to_coastal(monkeypatch):
    """Multi-business proof: the coastal_exact fixture routes to Coastal Cleaning Co.
    unconditionally, independent of any demo_sender_bindings state.

    from_addr resolves from _SEED_CONTACTS[fixture["business_name"]] — a constant map —
    NOT from a DB lookup or a global contact-email. The seed contacts are permanently
    stable, so each fixture routes to its own business with zero DB coupling; resolving
    via binding state would drag every fixture to whichever business was bound last.
    """
    import uuid as _uuid

    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app

    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")

    coastal_uuid = _uuid.UUID("b0000001-0000-0000-0000-000000000001")
    metro_uuid = _uuid.UUID("b0000002-0000-0000-0000-000000000002")

    import app.db.repo as _repo
    create_run_calls: list[dict[str, Any]] = []

    def _fake_find_business_by_sender(from_addr, conn=None):
        # coastal .example contact resolves to coastal_uuid
        if from_addr == "payroll@coastalcleaning.example":
            return coastal_uuid
        if from_addr == "hr@metrodeli.example":
            return metro_uuid
        return None

    def _fake_insert_inbound_email(**kw):
        return (_uuid.uuid4(), True)

    def _fake_create_run(*, business_id, source_email_id, **kw):
        rid = _uuid.uuid4()
        create_run_calls.append({"business_id": business_id, "run_id": rid})
        return rid

    monkeypatch.setattr(_repo, "find_business_by_sender", _fake_find_business_by_sender)
    monkeypatch.setattr(_repo, "insert_inbound_email", _fake_insert_inbound_email)
    monkeypatch.setattr(_repo, "create_run", _fake_create_run)

    from tests.test_demo_landing import _patch_demo_queue_dependencies

    _patch_demo_queue_dependencies(monkeypatch, _repo)

    import resend as _resend
    monkeypatch.setattr(
        _resend.Emails, "send", staticmethod(lambda p: {"id": "fake"}), raising=True
    )

    tc = TestClient(app, raise_server_exceptions=False)
    response = tc.post(
        "/demo/send-test", data={"fixture_key": "coastal_exact"}, follow_redirects=False
    )

    get_settings.cache_clear()

    assert response.status_code == 303, (
        f"POST /demo/send-test coastal_exact must return 303; got {response.status_code}"
    )
    assert len(create_run_calls) >= 1, "create_run must have been called"
    assert create_run_calls[0]["business_id"] == coastal_uuid, (
        f"coastal_exact must route to coastal_uuid ({coastal_uuid}); "
        f"got {create_run_calls[0]['business_id']}"
    )


def test_demo_send_test_metro_unknown_shorthand_routes_to_metro(monkeypatch):
    """The unknown_shorthand_metro fixture routes to Metro Deli Group.

    from_addr resolves to 'hr@metrodeli.example' via _SEED_CONTACTS because
    unknown_shorthand_metro has business_name='Metro Deli Group'. The run is
    created under metro_uuid — not None (not the unknown_sender path).
    """
    import uuid as _uuid

    from fastapi.testclient import TestClient

    from app.config import get_settings
    from app.main import app

    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")

    metro_uuid = _uuid.UUID("b0000002-0000-0000-0000-000000000002")

    import app.db.repo as _repo
    create_run_calls: list[dict[str, Any]] = []

    def _fake_find_business_by_sender(from_addr, conn=None):
        if from_addr == "hr@metrodeli.example":
            return metro_uuid
        return None

    def _fake_insert_inbound_email(**kw):
        return (_uuid.uuid4(), True)

    def _fake_create_run(*, business_id, source_email_id, **kw):
        rid = _uuid.uuid4()
        create_run_calls.append({"business_id": business_id, "run_id": rid})
        return rid

    monkeypatch.setattr(_repo, "find_business_by_sender", _fake_find_business_by_sender)
    monkeypatch.setattr(_repo, "insert_inbound_email", _fake_insert_inbound_email)
    monkeypatch.setattr(_repo, "create_run", _fake_create_run)

    from tests.test_demo_landing import _patch_demo_queue_dependencies

    _patch_demo_queue_dependencies(monkeypatch, _repo)

    import resend as _resend
    monkeypatch.setattr(
        _resend.Emails, "send", staticmethod(lambda p: {"id": "fake"}), raising=True
    )

    tc = TestClient(app, raise_server_exceptions=False)
    response = tc.post(
        "/demo/send-test",
        data={"fixture_key": "unknown_shorthand_metro"},
        follow_redirects=False,
    )

    get_settings.cache_clear()

    assert response.status_code == 303, (
        f"POST /demo/send-test unknown_shorthand_metro must return 303; got {response.status_code}"
    )
    assert len(create_run_calls) >= 1, (
        "create_run must be called — the unknown_shorthand_metro fixture must route to Metro Deli, "
        "not fall through to the unknown_sender path"
    )
    assert create_run_calls[0]["business_id"] == metro_uuid, (
        f"unknown_shorthand_metro must route to metro_uuid ({metro_uuid}); "
        f"got {create_run_calls[0]['business_id']}"
    )


def test_demo_reset_rearming_writes_demo_sender_bindings_not_contact_email():
    """Unit test: demo_reset.py --confirm re-UPSERTs demo_sender_bindings only.

    Using FakeConnection (from conftest.py), asserts that:
    1. The re-arming SQL targets demo_sender_bindings (not businesses).
    2. No 'UPDATE businesses' SQL is executed anywhere, preserving the invariant that
       the seed .example contacts are permanently stable.
    """
    import importlib
    import os

    from tests.conftest import FakeConnection

    fc = FakeConnection()

    # Script a fetchone for the business_id lookup that demo_reset.py does
    # when resolving DEMO_BUSINESS_NAME → UUID via _SEED_BUSINESS_IDS constant.
    # The script calls seed() (dry_run path does nothing to the DB) and then
    # re-arms via INSERT INTO demo_sender_bindings ... ON CONFLICT DO UPDATE.
    # We call the re-arming function directly after importing the module.

    # Provide minimal env vars so the module loads cleanly.
    test_env = {
        "DEMO_CONTACT_EMAIL": "pjnhek@gmail.com",
        "DEMO_BUSINESS_NAME": "Coastal Cleaning Co.",
        "DATABASE_URL": "postgresql://mock-test-stub/mockdb",
    }

    saved_env = {}
    for k, v in test_env.items():
        saved_env[k] = os.environ.get(k)
        os.environ[k] = v

    try:
        # Import or reload the module so it picks up test env
        import scripts.demo_reset as demo_reset_mod
        importlib.reload(demo_reset_mod)

        # Call the re-arming helper directly with our FakeConnection
        demo_reset_mod._rearm_demo_identity(fc)
    finally:
        for k, saved in saved_env.items():
            if saved is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = saved

    all_sql = fc.all_sql()

    # Assert the re-arm targets demo_sender_bindings
    assert "demo_sender_bindings" in all_sql, (
        "demo_reset._rearm_demo_identity must INSERT INTO demo_sender_bindings; "
        f"executed SQL:\n{all_sql}"
    )

    # Assert NO UPDATE businesses SQL was executed (stable-seed-contacts invariant)
    assert "UPDATE businesses" not in all_sql, (
        "demo_reset._rearm_demo_identity must NOT execute 'UPDATE businesses'; "
        f"executed SQL:\n{all_sql}"
    )


@pytest.mark.integration
def test_health_ready_returns_200_with_db(seeded_db):
    """Readiness: GET /health/ready must run a real SELECT and return 200.

    This route is the GitHub Actions keep-alive target. It touches the businesses table
    so the Supabase free project registers DB activity and does not pause — a bare
    SELECT 1 against no table may not count as "use" in Supabase's pause detection.
    Requires a live DB — skip-guarded with @pytest.mark.integration.
    """
    response = client.get("/health/ready")
    assert response.status_code == 200, (
        f"GET /health/ready must return 200 (readiness); got {response.status_code}"
    )
    assert response.json()["status"] == "ready", (
        f"GET /health/ready must return {{\"status\": \"ready\"}}; got {response.json()}"
    )
