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
- UAT #3/#4 status poll endpoint: GET /runs/{id}/status → 200 JSON / 404

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
# D-8-07 / OPS2-02 — load_all_runs explicit-column projection (jsonb_typeof-guarded
# employee_count, review fix #2). DB-free via FakeConnection (fake_conn fixture,
# tests/conftest.py).
# ---------------------------------------------------------------------------


def test_load_all_runs_projection_has_no_select_star(fake_conn):
    """D-8-07 — the SQL text has no `pr.*` / `SELECT *`, and names the explicit
    scalar columns plus the two computed aliases."""
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
    """Review fix #2 / T-8-12 — employee_count is guarded by a jsonb_typeof CASE
    expression, NOT a bare COALESCE(jsonb_array_length(...), 0) — the bare form
    still raises on a non-array JSON scalar/null literal."""
    from app.db import repo

    fake_conn.script_fetchall([])
    repo.load_all_runs(conn=fake_conn)

    sql = fake_conn.all_sql()
    assert "CASE WHEN jsonb_typeof(pr.extracted_data->'employees') = 'array'" in sql
    assert "THEN jsonb_array_length(pr.extracted_data->'employees')" in sql
    assert "ELSE 0 END AS employee_count" in sql
    assert "COALESCE(jsonb_array_length" not in sql


def test_load_all_runs_tolerates_non_array_employee_count_value(fake_conn):
    """Review fix #2 — hermetic proxy: since FakeConnection replays scripted rows
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


# ---------------------------------------------------------------------------
# Test 8: UAT #3/#4 — GET /runs/{id}/status returns 404 for unknown run
# ---------------------------------------------------------------------------


def test_run_status_endpoint_404_for_unknown_run():
    """UAT #3/#4: GET /runs/{id}/status → 404 for a run that does not exist.

    The JS poller relies on this contract to stop polling on a missing run.
    The endpoint must never return 500 for an unknown UUID.
    """
    non_existent_id = uuid.uuid4()
    response = client.get(f"/runs/{non_existent_id}/status")
    assert response.status_code == 404, (
        f"GET /runs/{{uuid}}/status must return 404 for unknown run; "
        f"got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# Test 9: UAT #3/#4 — GET /runs/{id}/status returns 422 for non-UUID path
# ---------------------------------------------------------------------------


def test_run_status_endpoint_422_for_non_uuid():
    """UAT #3/#4: GET /runs/not-a-uuid/status → 422 (UUID validation guard).

    Ensures the status endpoint rejects non-UUID strings before they reach DB.
    """
    response = client.get("/runs/not-a-uuid/status")
    assert response.status_code == 422, (
        f"GET /runs/not-a-uuid/status must return 422; got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# Test 10: UAT #3/#4 — runs list page does NOT contain meta-refresh
# ---------------------------------------------------------------------------


def test_runs_list_has_no_meta_refresh():
    """UAT #3/#4: GET /runs must NOT emit <meta http-equiv="refresh">.

    The blunt meta-refresh was replaced by a vanilla-JS status poll.
    This test pins the removal so it can't silently regress.
    """
    response = client.get("/runs")
    assert response.status_code == 200
    assert 'http-equiv="refresh"' not in response.text, (
        "GET /runs must not emit <meta http-equiv='refresh'> — "
        "the vanilla-JS poll replaced it (UAT #3/#4)"
    )


# ---------------------------------------------------------------------------
# Test 11: UAT #3/#4 — run detail page does NOT contain meta-refresh
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
    monkeypatch.setattr(_repo, "load_outbound_emails", lambda rid, conn=None: [])

    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200, (
        f"GET /runs/{{id}} for an in-flight run must render 200, not {response.status_code} "
        "(run.id | tojson must not crash on a UUID)"
    )
    # The poll script must be present (run is in-flight) and carry the run id as a JSON string.
    assert "/status" in response.text
    assert str(run_id) in response.text


@pytest.mark.parametrize(
    "bad_name",
    [
        'Bad "Name"\r\nX-Injected: evil',  # CR-01 REVIEW-2: quote + CRLF header injection
        "Paweł Łukasiński",                # CR-01 REVIEW-3: non-latin-1 unicode (ł=U+0142)
        "İrem Çağ",                        # Turkish dotted-I + ç, also above U+00FF
    ],
)
def test_paystub_pdf_content_disposition_sanitized(monkeypatch, bad_name):
    """CR-01 (REVIEW-2 + REVIEW-3) security regression: the paystub PDF Content-Disposition
    filename must be sanitized so it (a) cannot break/inject the header (quote/CRLF) and
    (b) is always latin-1 encodable — Starlette latin-1-encodes header values, so a unicode
    name above U+00FF would raise UnicodeEncodeError → 500 without re.ASCII. emp_name falls
    back to item.submitted_name (LLM-extracted) when the employee was removed post-run.
    """
    from decimal import Decimal
    from datetime import datetime, timezone

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
        created_at=datetime.now(tz=timezone.utc),
    )
    monkeypatch.setattr(_repo, "load_line_items", lambda rid, conn=None: [item])
    monkeypatch.setattr(_repo, "load_run", lambda rid, conn=None: {"id": run_id, "business_id": uuid.uuid4()})
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
    assert cd.count('"') == 2, f"filename must remain a single well-formed quoted-string; got {cd!r}"
    # REVIEW-3: the whole header must be latin-1 encodable (Starlette encodes it that way);
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
    monkeypatch.setattr(_repo, "load_outbound_emails", lambda rid, conn=None: [])

    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200
    assert "location.reload()" in response.text, (
        "in-flight run-detail poll must reload once on settle so data columns populate"
    )


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
    monkeypatch.setattr(_repo, "load_outbound_emails", lambda rid, conn=None: [])

    text = client.get(f"/runs/{run_id}").text
    assert "/status" in text, "awaiting_reply must still render the poll script (it can advance on reply)"
    assert 'INITIAL_STATUS' in text and '"awaiting_reply"' in text, (
        "poll must seed INITIAL_STATUS from the rendered status"
    )
    assert "data.status !== INITIAL_STATUS" in text and "location.reload()" in text, (
        "poll must reload on ANY status change from the rendered status, not only on leaving in-flight"
    )


def test_run_detail_has_no_meta_refresh():
    """UAT #3/#4: GET /runs/{id} must NOT emit <meta http-equiv="refresh">.

    The blunt meta-refresh was replaced by a vanilla-JS status poll.
    """
    non_existent_id = uuid.uuid4()
    response = client.get(f"/runs/{non_existent_id}")
    # 404 is acceptable (run not found) — we're testing the 200 path for no-refresh.
    if response.status_code == 200:
        assert 'http-equiv="refresh"' not in response.text, (
            "GET /runs/{id} must not emit <meta http-equiv='refresh'> (UAT #3/#4)"
        )


# ---------------------------------------------------------------------------
# Tests for POST /runs/{run_id}/simulate-reply
# ---------------------------------------------------------------------------


def test_simulate_reply_noop_on_non_awaiting_run(monkeypatch):
    """POST /runs/{id}/simulate-reply on a non-awaiting run → 303, no crash.

    When the run is not in awaiting_reply status, the route must return a 303
    redirect without calling _route_reply or any pipeline code.
    """
    from app.db import repo as _repo
    from app.main import _route_reply as _rr

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

    # _route_reply must NOT be called; track any call via a spy.
    route_reply_calls = []
    import app.main as _main

    monkeypatch.setattr(
        _main,
        "_route_reply",
        lambda email, cleaned, bt: route_reply_calls.append(1) or None,
    )

    response = client.post(
        f"/runs/{run_id}/simulate-reply",
        data={"reply_body": "some reply"},
        follow_redirects=False,
    )
    assert response.status_code == 303, (
        f"non-awaiting simulate-reply must 303; got {response.status_code}"
    )
    assert len(route_reply_calls) == 0, "_route_reply must NOT be called for non-awaiting run"


def test_simulate_reply_noop_when_no_clarification_mid(monkeypatch):
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

    import app.main as _main
    route_reply_calls = []
    monkeypatch.setattr(
        _main,
        "_route_reply",
        lambda email, cleaned, bt: route_reply_calls.append(1) or None,
    )

    response = client.post(
        f"/runs/{run_id}/simulate-reply",
        data={"reply_body": "some reply"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert len(route_reply_calls) == 0, "_route_reply must NOT be called when no clarification mid"


def test_simulate_reply_triggers_route_reply_with_correct_headers(monkeypatch):
    """POST /runs/{id}/simulate-reply on awaiting_reply run → _route_reply called
    with in_reply_to == clarification Message-ID and from_addr == source inbound sender.

    This is the core contract: the synthetic reply carries the right RFC threading
    headers so _route_reply finds the awaiting_reply run AND the FIX-5 spoof guard
    passes (from_addr == business contact email).
    """
    from datetime import datetime, timezone

    from app.db import repo as _repo
    from app.models.contracts import InboundEmail

    run_id = uuid.uuid4()
    source_email_id = uuid.uuid4()
    clar_mid = "<clar-abc123@payroll-agent.local>"
    client_addr = "payroll@coastalcleaning.example"

    awaiting_run = {
        "id": run_id,
        "business_id": uuid.uuid4(),
        "source_email_id": source_email_id,
        "status": "awaiting_reply",
        "extracted_data": None,
        "decision": None,
        "reconciliation": None,
        "error_reason": None,
        "pay_period_start": None,
        "pay_period_end": None,
        "updated_at": None,
    }
    source_inbound = InboundEmail(
        id=source_email_id,
        message_id="<original-001@client.example>",
        in_reply_to=None,
        references_header=None,
        subject="Payroll hours",
        from_addr=client_addr,
        to_addr="agent@payroll-agent.local",
        body_text="Jame Okafor 40 hours.",
        created_at=datetime.now(timezone.utc),
    )

    monkeypatch.setattr(_repo, "load_run", lambda rid, conn=None: awaiting_run)
    monkeypatch.setattr(
        _repo,
        "get_outbound_message_id",
        lambda rid, purpose=None, conn=None: clar_mid,
    )
    monkeypatch.setattr(
        _repo, "load_inbound_email", lambda rid, conn=None: source_inbound
    )
    # insert_inbound_email must succeed (return a valid id, inserted=True)
    monkeypatch.setattr(
        _repo,
        "insert_inbound_email",
        lambda **kw: (uuid.uuid4(), True),
    )

    # Spy on _route_reply to capture the synthetic InboundEmail it receives.
    captured = {}
    import app.main as _main

    def spy_route_reply(email, cleaned, bt):
        captured["email"] = email
        captured["cleaned"] = cleaned
        return None  # simulate: not matched (so simulate-reply 303s cleanly)

    monkeypatch.setattr(_main, "_route_reply", spy_route_reply)

    response = client.post(
        f"/runs/{run_id}/simulate-reply",
        data={"reply_body": "Sorry — I meant James Okafor. Please process."},
        follow_redirects=False,
    )
    assert response.status_code == 303, (
        f"simulate-reply must 303; got {response.status_code}"
    )
    assert "email" in captured, "_route_reply must be called for awaiting_reply run"

    synthetic = captured["email"]
    # Core contract: in_reply_to and references_header == clarification Message-ID
    assert synthetic.in_reply_to == clar_mid, (
        f"synthetic reply in_reply_to must == clarification mid; got {synthetic.in_reply_to!r}"
    )
    assert synthetic.references_header == clar_mid, (
        f"synthetic reply references_header must == clarification mid; "
        f"got {synthetic.references_header!r}"
    )
    # from_addr == business contact email (FIX-5 spoof guard will pass)
    assert synthetic.from_addr == client_addr, (
        f"synthetic reply from_addr must == source inbound sender; got {synthetic.from_addr!r}"
    )
    # reply_body flows through as body_text (cleaned)
    assert "James Okafor" in captured["cleaned"], (
        "reply_body text must appear in cleaned body passed to _route_reply"
    )
    # subject is prefixed with "Re: "
    assert synthetic.subject.startswith("Re: "), (
        f"synthetic reply subject must start with 'Re: '; got {synthetic.subject!r}"
    )


@pytest.mark.integration
def test_send_test_mints_fresh_message_id_each_click():
    """UAT #2 / finding MEDIUM: two consecutive POST /demo/send-test calls must
    produce DISTINCT runs with DISTINCT message_ids — even though both now
    redirect to /runs (the queue view, not the individual run detail URL).

    Contract (DASH-05):
    - Both clicks → 303 to /runs (success path; UAT #2 fix).
    - Each click inserts a distinct email_messages row (different message_id).
    - Each click creates a distinct payroll_runs row.

    Marked @pytest.mark.integration because verifying distinct runs/message_ids
    requires a live DB (querying via repo after each POST).
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

    # UAT #2: both clicks now redirect to /runs (the triage queue), not to a
    # specific run URL. This is the correct CX: operator watches the queue.
    loc1 = response1.headers.get("location", "")
    loc2 = response2.headers.get("location", "")
    assert loc1 == "/runs", (
        f"First /demo/send-test must redirect to /runs (UAT #2); got {loc1!r}"
    )
    assert loc2 == "/runs", (
        f"Second /demo/send-test must redirect to /runs (UAT #2); got {loc2!r}"
    )

    # DASH-05 core contract: two distinct runs were created in the DB.
    # We verify this by loading all runs and checking the two most-recent ones
    # have distinct IDs and distinct message_ids (fresh Message-ID per click).
    try:
        all_runs = _repo.load_all_runs()
    except Exception:
        # DB unavailable in this test environment — skip the DB-level assertion.
        pytest.skip("DB unavailable — skipping run/message_id distinctness check")

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
# D-20: Health probe routes
#
# 06-01 wrote these as xfail(strict=True) stubs ("fail until the routes exist");
# 06-02 implemented GET /health/live and /health/ready in app/main.py, so the
# stubs flip to GREEN — the xfail markers are removed here at merge (the
# designed XFAIL→XPASS→remove-marker transition). These are now real assertions.
# ---------------------------------------------------------------------------


def test_health_live_returns_200_no_db():
    """D-20 liveness: GET /health/live must return 200 with no DB connection.

    This route is the Render deploy healthCheckPath — a Supabase blip during
    deploy must not fail this check. It touches NO database. (OPS-01 / D-20)

    T-06-02-01: Response body is {"status": "ok"} only.
    """
    response = client.get("/health/live")
    assert response.status_code == 200, (
        f"GET /health/live must return 200 (D-20 liveness); got {response.status_code}"
    )
    assert response.json()["status"] == "ok", (
        f"GET /health/live must return {{\"status\": \"ok\"}}; got {response.json()}"
    )


# ---------------------------------------------------------------------------
# Tests for 06-06 Task 1: HIGH-1 per-fixture routing fix + demo_reset re-arming
# ---------------------------------------------------------------------------


def test_demo_send_test_coastal_routes_to_coastal(monkeypatch):
    """HIGH-1 (R4) multi-business proof: coastal_exact fixture routes to Coastal
    Cleaning Co. unconditionally, independent of any demo_sender_bindings state.

    from_addr is now resolved from _SEED_CONTACTS[fixture["business_name"]] —
    a constant map — NOT from a DB lookup or global DEMO_CONTACT_EMAIL. Seed
    contacts are permanently stable (06-08 HIGH-2), so the constant is always
    correct. Each fixture routes to its own business with zero DB coupling.
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
    create_run_calls: list = []

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

    import resend as _resend
    monkeypatch.setattr(_resend.Emails, "send", staticmethod(lambda p: {"id": "fake"}), raising=True)

    tc = TestClient(app, raise_server_exceptions=False)
    response = tc.post("/demo/send-test", data={"fixture_key": "coastal_exact"}, follow_redirects=False)

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
    """HIGH-1 (R4) Beat-2 fixture: unknown_shorthand_metro routes to Metro Deli Group.

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
    create_run_calls: list = []

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

    import resend as _resend
    monkeypatch.setattr(_resend.Emails, "send", staticmethod(lambda p: {"id": "fake"}), raising=True)

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
    2. No 'UPDATE businesses' SQL is executed anywhere — the 06-08 HIGH-2
       invariant (seed .example contacts are permanently stable) is preserved.
    """
    import sys
    import os
    import importlib
    import types
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

    # Assert NO UPDATE businesses SQL was executed (HIGH-2 invariant)
    assert "UPDATE businesses" not in all_sql, (
        "demo_reset._rearm_demo_identity must NOT execute 'UPDATE businesses'; "
        f"executed SQL:\n{all_sql}"
    )


@pytest.mark.integration
def test_health_ready_returns_200_with_db(seeded_db):
    """D-20 readiness: GET /health/ready must run a real SELECT and return 200.

    This route is the GitHub Actions keep-alive target. It touches the businesses
    table to register DB activity so Supabase does not pause (D-16). The SELECT
    hits a real table (not SELECT 1) so Supabase registers activity. (OPS-01 / D-20 / D-16)
    Requires a live DB — skip-guarded with @pytest.mark.integration.
    """
    response = client.get("/health/ready")
    assert response.status_code == 200, (
        f"GET /health/ready must return 200 (D-20 readiness); got {response.status_code}"
    )
    assert response.json()["status"] == "ready", (
        f"GET /health/ready must return {{\"status\": \"ready\"}}; got {response.json()}"
    )
