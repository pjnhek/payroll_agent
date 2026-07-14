"""Regression tests for the repo layer's real SQL, column list, and delivery enrichment.

Each bug guarded here shipped because the mocked InMemoryRepo never exercised the
real SQL / real column list / real confirmation-subject enrichment.  These tests
close that blind spot by asserting against the real code paths.

Invariants locked here:

update_known_alias must use TEXT[] array operators, not JSONB ops.
    The schema declares employees.known_aliases as TEXT[], so JSONB functions
    (to_jsonb / jsonb_agg / jsonb_array_elements_text / @>) are rejected by
    PostgreSQL with a type error on every call.

RUN_COLS must include updated_at.
    Without it, load_run() never returns updated_at; the retrigger handler's
    stale-run guard always evaluates to False; stale-state recovery is dead.

RUN_COLS must include alias_candidates.
    Without it, the alias-learning WRITE side is a silent no-op against a real DB.

_deliver must enrich the run dict with business_name + pay_period_label.
    confirmation_subject() reads run["business_name"] / run["pay_period_label"].
    Neither is in the load_run() dict, so without the enrichment every
    confirmation subject reads "Payroll Confirmation — Payroll Run — ".

Retrigger must clear ALL reply-round context.
    Otherwise a stale provenance badge can outlive the data that produced it.
"""
from __future__ import annotations

# These fixtures cross dynamic JSONB and UUID repository boundaries.
import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient

import app.db.repo as repo_mod
from app.db.repo import RUN_COLS, load_business_name, update_known_alias
from app.models.status import RunStatus
from app.pipeline.compose_email import confirmation_subject
from app.queue import drain


@pytest.fixture
def client(fake_repo):
    """TestClient for the retrigger regression tests (mirrors
    tests/test_hitl.py's client fixture)."""
    from app.main import app

    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# update_known_alias SQL uses TEXT[] ops, NOT JSONB ops
# ---------------------------------------------------------------------------


def test_update_known_alias_sql_uses_text_array_ops(fake_conn):
    """update_known_alias must issue TEXT[]-compatible SQL.

    employees.known_aliases is declared TEXT[] in the schema.  JSONB functions
    (to_jsonb, jsonb_agg, jsonb_array_elements_text, @>) are rejected by
    PostgreSQL against a TEXT[] column.

    This test captures the executed SQL via FakeConnection and asserts:
    - The SQL contains TEXT[]-native operators (ANY or unnest).
    - The SQL does NOT contain any JSONB-specific functions/operators
      (to_jsonb, jsonb_agg, jsonb_array_elements_text, @>).
    """
    emp_id = uuid.uuid4()
    new_alias = "Dave Reyez"

    # FakeConnection returns None for fetchone → no RETURNING row → returns False.
    # We only care about the SQL shape, not the return value.
    _result = update_known_alias(emp_id, new_alias, conn=fake_conn)

    executed_sql = fake_conn.all_sql().upper()

    # Must use TEXT[]-native ANY / unnest
    assert "ANY" in executed_sql or "UNNEST" in executed_sql, (
        "update_known_alias must use TEXT[] array operators (ANY or unnest) — "
        f"got SQL:\n{fake_conn.all_sql()}"
    )

    # Must NOT use JSONB-specific functions/operators
    assert "TO_JSONB" not in executed_sql, (
        "update_known_alias must NOT use to_jsonb() — known_aliases is TEXT[], not JSONB"
    )
    assert "JSONB_AGG" not in executed_sql, (
        "update_known_alias must NOT use jsonb_agg() — known_aliases is TEXT[], not JSONB"
    )
    assert "JSONB_ARRAY_ELEMENTS_TEXT" not in executed_sql, (
        "update_known_alias must NOT use jsonb_array_elements_text() — "
        "known_aliases is TEXT[], not JSONB"
    )

    # The idempotency WHERE clause must NOT use the JSONB containment operator @>
    # against known_aliases (that is the specific PostgreSQL type error).
    # Note: @> could still appear in unrelated SQL elsewhere; we check
    # that the WHERE NOT clause uses ANY instead.
    assert "NOT (%S = ANY(" in executed_sql or "NOT (%s = ANY(" in fake_conn.all_sql(), (
        "update_known_alias idempotency guard must use NOT (%s = ANY(known_aliases)), "
        "not the JSONB containment operator @>"
    )


def test_update_known_alias_returns_false_when_alias_absent(fake_conn):
    """Returns False when no row is returned (alias absent or id missing).

    FakeConnection returns None from fetchone → the UPDATE RETURNING yields no row
    → update_known_alias returns False. This pins the return-value semantics that
    the TEXT[] implementation must preserve (True = appended, False = already present).
    """
    emp_id = uuid.uuid4()
    # No scripted fetchone → fetchone() returns None → returns False
    result = update_known_alias(emp_id, "New Alias", conn=fake_conn)
    assert result is False, (
        "update_known_alias must return False when RETURNING yields no row "
        "(alias already present or employee not found)"
    )


def test_update_known_alias_returns_true_when_row_returned(fake_conn):
    """Returns True when RETURNING yields a row (the alias was appended).

    Scripts FakeConnection to return a row from fetchone, simulating the UPDATE
    succeeding and RETURNING the employee id.
    """
    emp_id = uuid.uuid4()
    fake_conn.script_fetchone((str(emp_id),))  # simulate RETURNING id

    result = update_known_alias(emp_id, "New Alias", conn=fake_conn)

    assert result is True, (
        "update_known_alias must return True when RETURNING yields a row "
        "(alias was appended)"
    )


# ---------------------------------------------------------------------------
# RUN_COLS must include updated_at
# ---------------------------------------------------------------------------


def test_run_cols_contains_updated_at():
    """RUN_COLS must include 'updated_at'.

    Without this column, load_run() never returns updated_at, so the retrigger
    handler's stale-run guard always evaluates to False and stale-state recovery
    (RECEIVED/EXTRACTING/COMPUTED/SENT) is permanently disabled.

    This is an exhaustive regression guard: if someone removes updated_at from
    RUN_COLS in the future, this test catches it immediately.
    """
    assert "updated_at" in RUN_COLS, (
        "RUN_COLS must contain 'updated_at' so load_run() returns it as a "
        "tz-aware datetime and the retrigger stale-run guard can function. "
        "Without it, run.get('updated_at') is always None and stale is always "
        "False, permanently disabling stale-state recovery."
    )


def test_load_run_select_includes_updated_at(fake_conn):
    """load_run() SELECT must include updated_at in the column list.

    Scripts FakeConnection to return a stub row and asserts the executed SQL
    contains 'updated_at' — catching an omission at the SQL level, not just at
    the Python constant level.
    """
    run_id = uuid.uuid4()

    # Script enough columns to satisfy the SELECT … mapping (load_run maps by
    # column position; we only need the SQL assertion, not a valid mapping).
    fake_conn.script_fetchone(None)  # load_run returns None for missing run

    repo_mod.load_run(run_id, conn=fake_conn)

    executed_sql = fake_conn.all_sql()
    assert "updated_at" in executed_sql, (
        "load_run() SQL must include 'updated_at' in the SELECT column list — "
        "the retrigger stale-run guard depends on it"
    )


# ---------------------------------------------------------------------------
# RUN_COLS must include alias_candidates
# ---------------------------------------------------------------------------


def test_run_cols_contains_alias_candidates():
    """RUN_COLS must include 'alias_candidates'.

    Two orchestrator paths read alias_candidates from load_run():
    1. resume_pipeline's candidate diff, which binds a pending clarify-time token
       to the newly-resolved employee, and
    2. write_aliases_if_safe — the approval-gate write to employees.known_aliases.

    Without the column in RUN_COLS both paths get {} on a real dict_row, so the
    human-confirmation alias-learning WRITE side is a silent no-op against a live
    DB. Hermetic tests cannot catch this because InMemoryRepo.load_run returns the
    full in-memory run dict INCLUDING alias_candidates — the fixture-vs-reality
    gap this test exists to close.
    """
    assert "alias_candidates" in RUN_COLS, (
        "RUN_COLS must contain 'alias_candidates' so load_run() returns it and "
        "the alias-learning loop (resume binding + approval-gate write) works "
        "against a real database."
    )


def test_alias_candidates_roundtrips_through_real_load_run(fake_conn):
    """A scripted DB row with alias_candidates set flows through the REAL
    RUN_COLS-based load_run SQL and comes back on the run dict.

    Asserts on the actual SQL text AND the round-tripped value — NOT on an
    InMemoryRepo fake (a fake returning full dicts is exactly what masks this
    class of bug).
    """
    run_id = uuid.uuid4()
    scripted_row = {
        "id": run_id,
        "business_id": uuid.uuid4(),
        "source_email_id": uuid.uuid4(),
        "status": "awaiting_reply",
        "extracted_data": None,
        "decision": None,
        "reconciliation": None,
        "error_reason": None,
        "error_detail": None,
        "alias_candidates": {"Bobby": None},
        "pay_period_start": None,
        "pay_period_end": None,
        "updated_at": None,
    }
    fake_conn.script_fetchone(scripted_row)

    run = repo_mod.load_run(run_id, conn=fake_conn)
    assert run is not None, "scripted fetchone row must produce a run dict"

    # The actual SELECT column list (not just the Python constant) carries it.
    assert "alias_candidates" in fake_conn.all_sql(), (
        "load_run() SQL must include 'alias_candidates' in the SELECT column list"
    )
    # And the value the orchestrator reads (run_data.get('alias_candidates'))
    # is the persisted candidate map, not a silent {}.
    assert (run.get("alias_candidates") or {}) == {"Bobby": None}, (
        "load_run() must surface the persisted alias_candidates map to its "
        "callers (resume binding + write_aliases_if_safe)"
    )


# ---------------------------------------------------------------------------
# confirmation_subject uses the real business_name + pay_period
# ---------------------------------------------------------------------------


def test_confirmation_subject_with_real_business_name():
    """confirmation_subject must render the real business name.

    confirmation_subject(run) reads run.get("business_name", "Payroll Run"), so
    _deliver must enrich the run dict before calling it. This test exercises
    confirmation_subject directly with an enriched run dict and asserts the
    output contains the real business name, not the fallback.
    """
    run = {
        "business_name": "Coastal Cleaning Co.",
        "pay_period_label": "2026-06-01 to 2026-06-07",
    }
    subject = confirmation_subject(run)

    assert "Coastal Cleaning Co." in subject, (
        f"confirmation_subject must include the real business name; got: {subject!r}. "
        "_deliver must enrich the run dict with business_name before calling "
        "confirmation_subject."
    )
    assert "Payroll Run" not in subject, (
        f"confirmation_subject must NOT fall back to 'Payroll Run' when business_name "
        f"is present; got: {subject!r}"
    )


def test_confirmation_subject_with_pay_period():
    """confirmation_subject must include the pay period label."""
    run = {
        "business_name": "Metro Deli Group",
        "pay_period_label": "2026-06-01 to 2026-06-07",
    }
    subject = confirmation_subject(run)

    assert "2026-06-01 to 2026-06-07" in subject, (
        f"confirmation_subject must include the pay_period_label; got: {subject!r}. "
        "_deliver must format pay_period_start/end into pay_period_label."
    )


def test_confirmation_subject_fallback_when_empty_dict():
    """The fallback values must fire when keys are absent (not raise).

    Pins the degraded-but-safe behaviour (fallback "Payroll Run" / empty period)
    so the failure mode is explicit and the function provably does not raise on a
    partial dict.
    """
    subject = confirmation_subject({})
    assert subject == "Payroll Confirmation — Payroll Run — ", (
        f"confirmation_subject({{}}) must use fallbacks; got: {subject!r}"
    )


def test_deliver_enriches_run_dict_with_business_name(monkeypatch):
    """_deliver must enrich the run dict with business_name from the DB.

    Uses monkeypatching to stub repo.load_business_name and captures the subject
    line passed to gateway.send_outbound to verify it contains the real name.

    This is the end-to-end exercise of the enrichment path: the load_run() dict
    has only business_id → _deliver calls load_business_name → enriches the dict
    → the subject contains the real business name.
    """
    import app.db.repo as repo
    import app.email.gateway as gw
    from app.pipeline.delivery import deliver as _deliver

    run_id = uuid.uuid4()
    business_id = uuid.UUID("b0000001-0000-0000-0000-000000000001")

    # The run dict as returned by load_run() — NO business_name, NO pay_period_label.
    run_dict = {
        "id": str(run_id),
        "business_id": business_id,
        "status": "approved",
        "extracted_data": None,
        "decision": None,
        "reconciliation": None,
        "error_reason": None,
        "pay_period_start": date(2026, 6, 1),
        "pay_period_end": date(2026, 6, 7),
        "source_email_id": None,
        "updated_at": datetime.now(UTC),
        # Intentionally NO business_name or pay_period_label — these must be
        # computed by _deliver.
    }

    # Track the subject passed to send_outbound.
    captured_subjects: list[str] = []

    def _fake_load_business_name(bid, conn=None):
        return "Coastal Cleaning Co."

    def _fake_get_outbound_message_id(run_id, purpose=None, conn=None):
        return None  # no prior confirmation → proceed with send

    def _fake_load_line_items(run_id, conn=None):
        return []  # no paystubs — simplifies the test

    def _fake_load_roster_for_business(business_id, conn=None):
        from app.models.roster import Roster
        return Roster(business_id=business_id, employees=[])

    def _fake_load_inbound_email(run_id, conn=None):
        return None

    def _fake_send_outbound(*, run_id, to_addr, subject, body, attachments=None,
                             purpose=None, send_state=None):
        captured_subjects.append(subject)
        return f"<{uuid.uuid4()}@payroll-agent.local>"

    def _fake_set_status(run_id, status, conn=None):
        pass

    monkeypatch.setattr(repo, "load_business_name", _fake_load_business_name, raising=False)
    monkeypatch.setattr(repo, "get_outbound_message_id", _fake_get_outbound_message_id)
    monkeypatch.setattr(repo, "load_line_items", _fake_load_line_items)
    monkeypatch.setattr(repo, "load_roster_for_business", _fake_load_roster_for_business)
    monkeypatch.setattr(repo, "load_inbound_email", _fake_load_inbound_email)
    monkeypatch.setattr(repo, "set_status", _fake_set_status)
    monkeypatch.setattr(gw, "send_outbound", _fake_send_outbound)
    # _deliver checks the record_only flag; stub to False (live path)
    monkeypatch.setattr(repo, "get_record_only_flag", lambda *a, **kw: False, raising=False)

    # Also stub write_aliases_if_safe (called inside _deliver before SENT).
    from app.pipeline import alias_learning
    monkeypatch.setattr(
        alias_learning, "write_aliases_if_safe", lambda *a, **kw: None, raising=False
    )
    # _deliver's finalize sequence opens its own transaction.
    from tests.conftest import patch_get_connection
    patch_get_connection(monkeypatch, repo)

    _deliver(run_id, run_dict)

    assert len(captured_subjects) == 1, (
        "_deliver must call gateway.send_outbound exactly once for a normal approved run"
    )
    subject = captured_subjects[0]
    assert "Coastal Cleaning Co." in subject, (
        f"_deliver must enrich run with real business_name before composing confirmation; "
        f"got subject: {subject!r}. load_run() returns business_id only; _deliver must "
        f"call load_business_name to resolve the display name."
    )
    assert "Payroll Run" not in subject, (
        f"_deliver must NOT fall back to 'Payroll Run' when business_name is loaded; "
        f"got subject: {subject!r}"
    )
    assert "2026-06-01" in subject, (
        f"_deliver must format pay_period_start into pay_period_label; "
        f"got subject: {subject!r}"
    )


def test_load_business_name_sql_uses_businesses_table(fake_conn):
    """load_business_name must query the businesses table by id.

    Verifies the SQL shape (parameterized — business_id in params, not f-string)
    so the lookup is robust against SQL injection and matches the project's
    parameterized-SQL discipline.
    """
    biz_id = uuid.UUID("b0000001-0000-0000-0000-000000000001")
    fake_conn.script_fetchone(None)  # not found — we only care about SQL shape

    result = load_business_name(biz_id, conn=fake_conn)

    assert result is None  # FakeConnection returned None → no row

    executed_sql = fake_conn.all_sql().upper()
    assert "BUSINESSES" in executed_sql, (
        "load_business_name must query the businesses table"
    )
    # The business_id must be passed as a parameter, not embedded in the SQL.
    assert any(
        str(biz_id) in str(params) or str(biz_id).replace("-", "") in str(params or "")
        for _sql, params in fake_conn.executed
    ), (
        "load_business_name must pass business_id as a SQL parameter, not embed it "
        "in the SQL string (parameterized-SQL discipline)"
    )


# ---------------------------------------------------------------------------
# Retrigger clears ALL reply context after the winning claim, before the
# pipeline re-run is scheduled — so a stale provenance badge
# (is_round_2 = bool(clarified)) cannot outlive the data that produced it.
# ---------------------------------------------------------------------------


def _run_at_error_with_stale_reply_context(fake_repo) -> uuid.UUID:
    """Seed a claimable ERROR run carrying non-empty reply-round context —
    clarified_fields, a pre_clarify_extracted snapshot, clarification_round > 0,
    and alias_candidates set — the exact state retrigger must wipe."""
    business_id = fake_repo.contact_to_business["payroll@coastalcleaning.example"]
    run_id: uuid.UUID = fake_repo.create_run(business_id=business_id, source_email_id=None)
    fake_repo.set_status(run_id, RunStatus.ERROR)
    run = fake_repo.runs[str(run_id)]
    run["clarified_fields"] = {
        "e0000001-0000-0000-0000-000000000001": {"hours_overtime": "asked"}
    }
    run["pre_clarify_extracted"] = {"employees": [], "pay_period_start": "2026-06-15"}
    run["clarification_round"] = 2
    run["alias_candidates"] = {
        "Bobby": {"suggested": "e0000001-0000-0000-0000-000000000001", "bound": None}
    }
    return run_id


def test_retrigger_clears_all_reply_context(client, fake_repo, monkeypatch):
    """Retrigger clears clarified_fields, pre_clarify_extracted,
    clarification_round, AND alias_candidates after the winning claim — and
    still dispatches the re-run once the enqueued job is drained (QUEUE-02:
    retrigger no longer schedules a BackgroundTask, it enqueues a durable job)."""
    import app.routes.pipeline_glue as app_main

    dispatched: list[uuid.UUID] = []
    monkeypatch.setattr(app_main, "run_pipeline_now", lambda rid: dispatched.append(rid))

    run_id = _run_at_error_with_stale_reply_context(fake_repo)

    r = client.post(f"/runs/{run_id}/retrigger", follow_redirects=False)
    assert r.status_code == 303

    run = fake_repo.load_run(run_id)
    assert not run.get("clarified_fields"), (
        f"retrigger must clear clarified_fields; got {run.get('clarified_fields')!r}"
    )
    assert run.get("pre_clarify_extracted") is None, (
        f"retrigger must clear pre_clarify_extracted; got {run.get('pre_clarify_extracted')!r}"
    )
    assert run.get("clarification_round") == 0, (
        f"retrigger must reset clarification_round to 0; got {run.get('clarification_round')!r}"
    )
    assert run.get("alias_candidates") is None, (
        f"retrigger must clear alias_candidates; got {run.get('alias_candidates')!r}"
    )

    # New coverage: a durable jobs row exists BEFORE the drain, and the pipeline
    # has not yet run.
    matching = [j for j in fake_repo.jobs.values() if j["run_id"] == run_id]
    assert len(matching) == 1, (
        f"retrigger must enqueue exactly one run_pipeline job for {run_id}; "
        f"found {len(matching)}"
    )
    assert matching[0]["state"] == "pending" and matching[0]["kind"] == "run_pipeline"
    assert dispatched == [], (
        "the pipeline must not run before the enqueued job is drained"
    )

    assert drain.drain_once() is True, (
        "drain_once must claim and dispatch the job retrigger enqueued"
    )
    assert dispatched == [run_id], (
        "retrigger must still dispatch the pipeline re-run for the claimed run "
        f"after clearing reply context; got {dispatched}"
    )


def test_retrigger_clears_context_on_stale_inflight_claim(
    client, fake_repo, monkeypatch
):
    """The SAME clear must fire on the stale-in-flight CAS branch (not just the
    ERROR/APPROVED core CAS) — both winning branches converge on one
    clear_reply_context call before the pipeline re-run is scheduled."""
    from datetime import datetime, timedelta

    import app.routes.pipeline_glue as app_main

    dispatched: list[uuid.UUID] = []
    monkeypatch.setattr(app_main, "run_pipeline_now", lambda rid: dispatched.append(rid))

    business_id = fake_repo.contact_to_business["payroll@coastalcleaning.example"]
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=None)
    fake_repo.set_status(run_id, RunStatus.RECEIVED)
    run = fake_repo.runs[str(run_id)]
    run["clarified_fields"] = {"e0000001-0000-0000-0000-000000000001": {"hours_overtime": "asked"}}
    run["pre_clarify_extracted"] = {"employees": []}
    run["clarification_round"] = 1
    run["alias_candidates"] = {"Bobby": {"suggested": None, "bound": None}}
    # Stale in-flight requires updated_at older than STALE_THRESHOLD — the fake
    # repo does not track updated_at automatically, so set it directly.
    run["updated_at"] = datetime.now(UTC) - timedelta(minutes=30)

    r = client.post(f"/runs/{run_id}/retrigger", follow_redirects=False)
    assert r.status_code == 303

    run_after = fake_repo.load_run(run_id)
    assert not run_after.get("clarified_fields")
    assert run_after.get("pre_clarify_extracted") is None
    assert run_after.get("clarification_round") == 0
    assert run_after.get("alias_candidates") is None

    # New coverage: the stale in-flight branch also enqueues a durable job,
    # visible BEFORE any drain, and the pipeline has not yet run.
    matching = [j for j in fake_repo.jobs.values() if j["run_id"] == run_id]
    assert len(matching) == 1, (
        f"retrigger must enqueue exactly one run_pipeline job for {run_id}; "
        f"found {len(matching)}"
    )
    assert matching[0]["state"] == "pending" and matching[0]["kind"] == "run_pipeline"
    assert dispatched == [], (
        "the pipeline must not run before the enqueued job is drained"
    )

    assert drain.drain_once() is True, (
        "drain_once must claim and dispatch the job retrigger enqueued"
    )
    assert dispatched == [run_id], (
        "the stale in-flight retrigger branch must also dispatch the pipeline "
        f"re-run after clearing reply context; got {dispatched}"
    )


def test_stale_provenance_cannot_reproduce_after_retrigger(client, fake_repo, monkeypatch):
    """After retrigger wipes clarified_fields, `is_round_2 = bool(clarified)` for
    the re-run must see an EMPTY clarified_fields — the persisted/derived state a
    fresh run would see — not the pre-retrigger provenance. Asserted on the
    persisted column (not a rendered label)."""
    import app.routes.pipeline_glue as app_main

    monkeypatch.setattr(app_main, "run_pipeline_now", lambda rid: None)

    run_id = _run_at_error_with_stale_reply_context(fake_repo)
    # Sanity: before retrigger, clarified_fields is genuinely non-empty (the
    # exact provenance state that would make is_round_2 = bool(clarified) True).
    assert fake_repo.load_run(run_id)["clarified_fields"], (
        "sanity check: the seeded run must start with non-empty clarified_fields"
    )

    r = client.post(f"/runs/{run_id}/retrigger", follow_redirects=False)
    assert r.status_code == 303

    clarified_after = fake_repo.load_run(run_id).get("clarified_fields")
    assert bool(clarified_after) is False, (
        "after retrigger, clarified_fields must be empty/falsy so "
        "is_round_2 = bool(clarified) evaluates False for the re-run — a "
        f"stale provenance badge must not be able to reproduce; got {clarified_after!r}"
    )
