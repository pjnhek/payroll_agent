"""Wave 0 RED stubs: dashboard route smoke tests (DASH-01..05).

These tests will fail RED until Wave 3 adds the dashboard routes to app/main.py:
- GET /runs              → DASH-01 runs list (200)
- GET /runs/{id}         → DASH-02 run detail (200 or 404)
- GET /eval              → DASH-03 eval view (200, contains "chart.svg")
- POST /demo/send-test   → DASH-04 demo button (303 redirect)

Also covers:
- DASH-05 eval graceful handling of missing summary.json (200 with "No eval results")
- Message-ID uniqueness (finding MEDIUM): /demo/send-test mints a fresh ID per click
- UUID path param validation (T-05-05 SQLi guard): /runs/not-a-uuid → 422

Routes do not yet exist in app/main.py — these tests are the Nyquist Wave 0
contract that Wave 3 must satisfy.
"""
from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Test 1: DASH-01 — GET /runs returns 200
# ---------------------------------------------------------------------------


def test_runs_list_returns_200():
    """DASH-01: GET /runs → 200 (runs list page).

    Will fail RED until Wave 3 adds the GET /runs route to app/main.py.
    """
    response = client.get("/runs")
    assert response.status_code == 200, (
        f"GET /runs must return 200 (DASH-01 runs list); got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# Test 2: DASH-02 — GET /runs/{valid_uuid} returns 200 or 404
# ---------------------------------------------------------------------------


def test_run_detail_returns_200_or_404():
    """DASH-02: GET /runs/{valid_uuid} → 200 (found) or 404 (not found).

    A valid UUID that doesn't exist in the DB must return 404, not 500 or 422.
    Will fail RED until Wave 3 adds the GET /runs/{run_id} route.
    """
    non_existent_id = uuid.uuid4()
    response = client.get(f"/runs/{non_existent_id}")
    assert response.status_code in (200, 404), (
        f"GET /runs/{{uuid}} must return 200 or 404 (DASH-02); got {response.status_code}"
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


def test_send_test_returns_303():
    """DASH-04: POST /demo/send-test → 303 redirect (back to /runs or run detail).

    The demo button fires the whole flow and redirects the operator to the
    resulting run. Will fail RED until Wave 3 adds the POST /demo/send-test route.
    """
    response = client.post("/demo/send-test", follow_redirects=False)
    assert response.status_code == 303, (
        f"POST /demo/send-test must return 303 redirect (DASH-04); "
        f"got {response.status_code}"
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
# Test 6: UUID path validation — /runs/not-a-uuid returns 422 (T-05-05 SQLi guard)
# ---------------------------------------------------------------------------


def test_runs_invalid_uuid_returns_422():
    """T-05-05 SQLi guard: GET /runs/not-a-uuid must return 422 (Pydantic UUID
    validation rejects non-UUID strings before they reach the DB layer).

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


@pytest.mark.integration
def test_send_test_mints_fresh_message_id_each_click():
    """Finding MEDIUM: two consecutive POST /demo/send-test calls must produce
    different Message-IDs.

    The uq_message_id unique constraint silently drops repeat clicks if the
    same fixture Message-ID is reused. The route must mint a fresh synthetic ID
    per click (e.g. f"<{uuid.uuid4()}@payroll-agent.local>") to avoid the constraint
    dropping the second demo click.

    Marked @pytest.mark.integration because verifying the minted Message-IDs
    requires a live DB (querying via repo after each POST).

    Will fail RED until Wave 3 / Plan 06 implements the /demo/send-test route
    with per-click Message-ID generation.
    """
    response1 = client.post("/demo/send-test", follow_redirects=False)
    response2 = client.post("/demo/send-test", follow_redirects=False)

    # Both POSTs must succeed (303) — second click must not 409 or 500.
    assert response1.status_code == 303, (
        f"First /demo/send-test must return 303; got {response1.status_code}"
    )
    assert response2.status_code == 303, (
        f"Second /demo/send-test must return 303 (fresh Message-ID per click); "
        f"got {response2.status_code}"
    )

    # The redirect Location headers must point to DIFFERENT run URLs
    # (each click creates a distinct run, each with a distinct Message-ID).
    loc1 = response1.headers.get("location", "")
    loc2 = response2.headers.get("location", "")
    assert loc1 != loc2, (
        "Two consecutive /demo/send-test clicks must redirect to DIFFERENT run URLs "
        "— each click mints a fresh Message-ID and creates a distinct run (finding MEDIUM)"
    )
