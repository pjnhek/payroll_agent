"""Integration tests for resume_pipeline — the field-regression state machine.

These tests lock the money-safety invariants of the clarification reply loop:
a dropped field is detected on the RAW reply, clarified exactly once, and then
either carried forward from the snapshot (silence), honoured as a removal
(explicit zero), or taken from the client's restated value — with no path that
silently overpays or underpays.

Hermetic discipline:
Every test uses the fake_repo (in-memory) + mock_llm fixtures from conftest.py,
patching ALL repo calls onto an InMemoryRepo so no live DB writes occur during
the test run. The module therefore runs unconditionally whether DATABASE_URL is
absent or contains a harmless stub value.

Hermetic cleanup: fake_repo is function-scoped (default conftest fixture) and
resets its in-memory state on each test — no cross-test contamination. No live DB
cleanup is needed since no real DB writes are made. The mock_llm fixture also
clears its script/calls lists before each test.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import httpx
import pytest
from openai import APIConnectionError

from app.models.contracts import Extracted, ExtractedEmployee, InboundEmail
from app.models.job import Job, JobKind
from app.models.roster import NameMatchResult
from app.models.status import RunStatus
from app.pipeline.orchestrator import resume_pipeline
from app.pipeline.result import PipelineOutcome, PipelineResult
from tests.conftest import InMemoryRepo

# ---------------------------------------------------------------------------
# Stable employee / business identifiers from seed.py
# ---------------------------------------------------------------------------
# Business 1 — Coastal Cleaning Co. (payroll@coastalcleaning.example)
COASTAL_BIZ_ID = uuid.UUID("b0000001-0000-0000-0000-000000000001")
COASTAL_EMAIL = "payroll@coastalcleaning.example"
SECOND_BIZ_ID = uuid.UUID("b0000002-0000-0000-0000-000000000002")

# Employee 1 — Maria Chen (Business 1, hourly, $18.50/hr, aliases: ["Maria", "M. Chen"])
CHEN_ID = uuid.UUID("e0000001-0000-0000-0000-000000000001")
CHEN_ID_STR = str(CHEN_ID)

# Employee 2 — James Okafor (Business 1, salary, married_jointly, 401k)
OKAFOR_ID = uuid.UUID("e0000002-0000-0000-0000-000000000002")
OKAFOR_ID_STR = str(OKAFOR_ID)


# ---------------------------------------------------------------------------
# Helper: build Extracted objects for scripted LLM responses
# ---------------------------------------------------------------------------

def _mk_extracted(
    employees_data: list[dict[str, Any]],
    pay_period_start: str = "2026-06-15",
    pay_period_end: str | None = None,
    run_id: uuid.UUID | None = None,
) -> Extracted:
    """Build an Extracted from a list of employee dicts."""
    if run_id is None:
        run_id = uuid.uuid4()
    return Extracted(
        run_id=run_id,
        employees=[ExtractedEmployee(**e) for e in employees_data],
        pay_period_start=date.fromisoformat(pay_period_start),
        pay_period_end=date.fromisoformat(pay_period_end) if pay_period_end else None,
    )


def _mk_match(
    name: str,
    emp_id: uuid.UUID,
    source: str = "exact",
    resolved: bool = True,
) -> NameMatchResult:
    """Build a NameMatchResult."""
    return NameMatchResult(
        submitted_name=name,
        matched_employee_id=emp_id if resolved else None,
        source=source,
        resolved=resolved,
        reason="exact match" if source == "exact" else source,
    )


def _seed_run(
    fake_repo: InMemoryRepo, *, body: str, from_addr: str = COASTAL_EMAIL
) -> uuid.UUID:
    """Seed an inbound email + run in the fake_repo."""
    eid, _ = fake_repo.insert_inbound_email(
        message_id=f"<{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="payroll hours",
        from_addr=from_addr,
        to_addr="agent@payroll-agent.local",
        body_text=body,
    )
    return fake_repo.create_run(
        business_id=COASTAL_BIZ_ID,
        source_email_id=eid,
    )


def _inbound(body: str, from_addr: str = COASTAL_EMAIL) -> InboundEmail:
    """Build an InboundEmail for the reply."""
    return InboundEmail(
        id=uuid.uuid4(),
        message_id=f"<reply-{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="Re: payroll hours",
        from_addr=from_addr,
        to_addr="agent@payroll-agent.local",
        body_text=body,
        created_at=datetime.now(UTC),
    )


def _resume_reply_job(
    *,
    run_id: uuid.UUID | None,
    email_id: uuid.UUID | None,
    attempts: int = 1,
) -> Job:
    return Job(
        id=uuid.uuid4(),
        kind=JobKind.RESUME_REPLY,
        run_id=run_id,
        email_id=email_id,
        attempts=attempts,
        max_attempts=5,
        lease_token=uuid.uuid4(),
    )


def test_resume_reply_handler_reloads_exact_persisted_body_from_received(
    fake_repo, monkeypatch
) -> None:
    from app.pipeline import orchestrator
    from app.queue.handlers import resume_reply

    run_id = _seed_run(fake_repo, body="original inbound")
    email_id, inserted = fake_repo.insert_inbound_email(
        message_id=f"<reply-{uuid.uuid4()}@test.example>",
        in_reply_to="<clarification@test.example>",
        references_header="<clarification@test.example>",
        subject="Re: payroll hours",
        from_addr=COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="persisted cleaned reply",
    )
    assert inserted and email_id is not None
    fake_repo.link_email_to_run(email_id, run_id)

    calls: list[tuple[uuid.UUID, InboundEmail, RunStatus]] = []
    explicit = PipelineResult(outcome=PipelineOutcome.OK)

    def _resume(rid, inbound, *, from_status, **kwargs):
        calls.append((rid, inbound, from_status))
        return explicit

    monkeypatch.setattr(orchestrator, "resume_pipeline", _resume)

    result = resume_reply.handle_resume_reply(
        _resume_reply_job(run_id=run_id, email_id=email_id)
    )

    assert result is explicit
    assert len(calls) == 1
    called_run_id, called_inbound, called_status = calls[0]
    assert called_run_id == run_id
    assert called_inbound.id == email_id
    assert called_inbound.body_text == "persisted cleaned reply"
    assert called_status is RunStatus.RECEIVED


def test_resume_reply_handler_reclaims_without_advancing_epoch(
    fake_repo, monkeypatch
) -> None:
    from app.pipeline import orchestrator
    from app.queue.handlers import resume_reply

    run_id = _seed_run(fake_repo, body="original inbound")
    email_id, _ = fake_repo.insert_inbound_email(
        message_id=f"<reply-{uuid.uuid4()}@test.example>",
        in_reply_to="<clarification@test.example>",
        references_header=None,
        subject="Re: payroll hours",
        from_addr=COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="same persisted reply",
    )
    assert email_id is not None
    fake_repo.link_email_to_run(email_id, run_id)
    run = fake_repo.runs[str(run_id)]
    run["status"] = RunStatus.EXTRACTING.value
    run["reply_epoch"] = 7

    calls: list[InboundEmail] = []

    def _resume(_rid, inbound, **_kwargs) -> PipelineResult:
        calls.append(inbound)
        return PipelineResult(outcome=PipelineOutcome.OK)

    monkeypatch.setattr(
        orchestrator,
        "resume_pipeline",
        _resume,
    )

    result = resume_reply.handle_resume_reply(
        _resume_reply_job(run_id=run_id, email_id=email_id, attempts=2)
    )
    assert result.outcome is PipelineOutcome.OK
    assert [inbound.id for inbound in calls] == [email_id]
    assert run["reply_epoch"] == 7


@pytest.mark.parametrize(
    ("row_run_id", "other_business"),
    [
        (None, False),
        ("not-a-uuid", False),
        ("wrong-run", False),
        ("wrong-run", True),
    ],
    ids=("null-run", "malformed-run", "same-business-wrong-run", "cross-business"),
)
def test_resume_reply_handler_rejects_unowned_persisted_context_before_conversion(
    fake_repo,
    monkeypatch,
    caplog,
    row_run_id: str | None,
    other_business: bool,
) -> None:
    from app.pipeline import orchestrator
    from app.queue.handlers import resume_reply

    job_run_id = _seed_run(fake_repo, body="original inbound")
    linked_run_id = fake_repo.create_run(
        business_id=SECOND_BIZ_ID if other_business else COASTAL_BIZ_ID,
        source_email_id=None,
    )
    email_id, inserted = fake_repo.insert_inbound_email(
        message_id=f"<hostile-{uuid.uuid4()}@test.example>",
        in_reply_to="<clarification@test.example>",
        references_header="<clarification@test.example>",
        subject="SECRET SUBJECT Acme Payroll",
        from_addr="secret-sender@example.test",
        to_addr="secret-recipient@example.test",
        body_text="SECRET BODY Maria Chen employee payroll",
    )
    assert inserted and email_id is not None
    if row_run_id == "wrong-run":
        fake_repo.link_email_to_run(email_id, linked_run_id)
    else:
        fake_repo.email_by_id[str(email_id)]["run_id"] = row_run_id

    def _fail_row_to_inbound(_row):
        raise AssertionError("row_to_inbound must not run for unowned context")

    def _fail_resume(*_args, **_kwargs):
        raise AssertionError("resume_pipeline must not run for unowned context")

    monkeypatch.setattr(resume_reply, "row_to_inbound", _fail_row_to_inbound)
    monkeypatch.setattr(orchestrator, "resume_pipeline", _fail_resume)
    job = _resume_reply_job(run_id=job_run_id, email_id=email_id)

    terminal = resume_reply.handle_resume_reply(job)

    assert terminal.outcome is PipelineOutcome.TERMINAL
    assert terminal.diagnostic_code == "load:invalid_operator_override_context"
    assert caplog.text.count("invalid_operator_override_context") == 1
    forbidden = (
        str(job.id),
        str(job_run_id),
        str(linked_run_id),
        str(email_id),
        str(COASTAL_BIZ_ID),
        str(SECOND_BIZ_ID),
        "SECRET",
        "Acme Payroll",
        "Maria Chen",
        "employee payroll",
        "secret-sender",
        "secret-recipient",
    )
    assert all(token not in caplog.text for token in forbidden)


def test_resume_reply_handler_rejects_missing_or_non_inbound_context(
    fake_repo, caplog
) -> None:
    from app.queue.handlers import resume_reply

    run_id = _seed_run(fake_repo, body="original inbound")

    with pytest.raises(ValueError, match="run_id"):
        resume_reply.handle_resume_reply(
            _resume_reply_job(run_id=None, email_id=uuid.uuid4())
        )
    with pytest.raises(ValueError, match="email_id"):
        resume_reply.handle_resume_reply(
            _resume_reply_job(run_id=run_id, email_id=None)
        )

    hostile_email_id, _ = fake_repo.insert_inbound_email(
        message_id=f"<hostile-{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="SECRET SUBJECT",
        from_addr=COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="SECRET TOKEN Maria Chen",
    )
    assert hostile_email_id is not None
    fake_repo.email_by_id[str(hostile_email_id)]["direction"] = "outbound"

    terminal = resume_reply.handle_resume_reply(
        _resume_reply_job(run_id=run_id, email_id=hostile_email_id)
    )
    assert terminal.outcome is PipelineOutcome.TERMINAL
    assert terminal.diagnostic_code == "load:invalid_operator_override_context"
    assert "SECRET" not in caplog.text
    assert "Maria Chen" not in caplog.text


def test_resume_reply_dispatch_forwards_handler_result(monkeypatch) -> None:
    from app.queue import dispatch
    from app.queue.handlers import resume_reply

    explicit = PipelineResult(outcome=PipelineOutcome.OK)
    monkeypatch.setattr(resume_reply, "handle_resume_reply", lambda _job: explicit)

    assert (
        dispatch.handle(
            _resume_reply_job(run_id=uuid.uuid4(), email_id=uuid.uuid4())
        )
        is explicit
    )


def test_resume_reply_dispatch_rejects_none_from_unsound_handler(monkeypatch) -> None:
    from app.queue import dispatch
    from app.queue.handlers import resume_reply

    monkeypatch.setattr(resume_reply, "handle_resume_reply", lambda _job: None)

    with pytest.raises(TypeError, match="expected PipelineResult, got NoneType"):
        dispatch.handle(
            _resume_reply_job(run_id=uuid.uuid4(), email_id=uuid.uuid4())
        )


def test_fake_resume_reply_context_is_strict_and_email_reads_are_copies(fake_repo) -> None:
    with pytest.raises(ValueError, match="resume_reply"):
        fake_repo.enqueue_job(
            kind=JobKind.RESUME_REPLY,
            dedup_key=f"resume_reply:{uuid.uuid4()}",
            run_id=uuid.uuid4(),
        )
    with pytest.raises(ValueError, match="resume_reply"):
        fake_repo.enqueue_job(
            kind=JobKind.RESUME_REPLY,
            dedup_key=f"resume_reply:{uuid.uuid4()}",
            run_id=uuid.uuid4(),
            email_id=uuid.uuid4(),
            operator_resolution_id=uuid.uuid4(),
        )

    email_id, _ = fake_repo.insert_inbound_email(
        message_id=f"<copy-{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="copy proof",
        from_addr=COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="persisted body",
    )
    assert email_id is not None
    first = fake_repo.get_inbound_email_by_id(email_id)
    assert first is not None
    first["body_text"] = "mutated caller copy"
    second = fake_repo.get_inbound_email_by_id(email_id)

    assert second is not None and second["body_text"] == "persisted body"
    assert fake_repo.context_calls[-2:] == [
        ("get_inbound_email_by_id", str(email_id)),
        ("get_inbound_email_by_id", str(email_id)),
    ]


def _extraction_json(
    employees: list[dict[str, Any]],
    pay_period_start: str = "2026-06-15",
) -> str:
    """Serialize extraction as the mock LLM response JSON string."""
    return json.dumps(
        {
            "employees": employees,
            "pay_period_start": pay_period_start,
            "pay_period_end": None,
        }
    )


def _suggestion_json(suggestions: dict[str, str]) -> str:
    """Serialize suggestions as the mock LLM response JSON string."""
    return json.dumps(
        {
            "suggestions": [
                {"submitted_name": k, "suggested_full_name": v}
                for k, v in suggestions.items()
            ]
        }
    )


def _set_run_awaiting_reply(fake_repo, run_id: uuid.UUID) -> None:
    """Force a run to AWAITING_REPLY state, bypassing the normal pipeline."""
    fake_repo.runs[str(run_id)]["status"] = RunStatus.AWAITING_REPLY.value


def _snapshot_extracted(
    submitted_name: str,
    hours_regular: str = "40",
    hours_overtime: str | None = "2",
    run_id: uuid.UUID | None = None,
) -> Extracted:
    """Build a pre-clarify snapshot Extracted."""
    emp: dict[str, Any] = {
        "submitted_name": submitted_name,
        "hours_regular": hours_regular,
    }
    if hours_overtime is not None:
        emp["hours_overtime"] = hours_overtime
    return _mk_extracted([emp], run_id=run_id)


# ---------------------------------------------------------------------------
# Helpers for Round-2 setup
# ---------------------------------------------------------------------------

def _setup_round2(
    fake_repo,
    run_id: uuid.UUID,
    submitted_name: str,
    emp_id: uuid.UUID,
    emp_id_str: str,
    match_source: str = "exact",
) -> None:
    """Put a run into Round-2 state: snapshot + clarified 'asked' for hours_overtime."""
    # Set snapshot
    snapshot = _snapshot_extracted(submitted_name, hours_regular="40", hours_overtime="2")
    fake_repo.set_pre_clarify_extracted(run_id, snapshot)
    # Write prior_matches into reconciliation (Step E0 in orchestrator)
    prior_match = _mk_match(submitted_name, emp_id, source=match_source)
    fake_repo.persist_reconciliation(run_id, [prior_match])
    # Write 'asked' in clarified_fields
    clarified = {emp_id_str: {"hours_overtime": "asked"}}
    fake_repo.set_clarified_fields(run_id, clarified)
    # Force AWAITING_REPLY
    _set_run_awaiting_reply(fake_repo, run_id)


def test_snapshot_once_not_overwritten(fake_repo, mock_llm):
    """set_pre_clarify_extracted's IS NULL guard — a second write is a no-op.

    A second set_pre_clarify_extracted call must NOT overwrite the first snapshot.
    The snapshot is the write-once record of what the client originally sent; if a
    later round could overwrite it, the carry-forward backfill would restore the
    reply's values instead of the original ones. The IS NULL CAS guard makes the
    write idempotent.
    """
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular hours")

    # First write
    first_snapshot = _snapshot_extracted("Maria Chen", hours_overtime="2")
    wrote_first = fake_repo.set_pre_clarify_extracted(run_id, first_snapshot)
    assert wrote_first is True, "First snapshot write must succeed"

    # Second write with different data
    second_snapshot = _snapshot_extracted("Maria Chen", hours_overtime="5")
    wrote_second = fake_repo.set_pre_clarify_extracted(run_id, second_snapshot)
    assert wrote_second is False, "IS NULL guard: second write must be rejected"

    # First value is preserved
    loaded = fake_repo.load_pre_clarify_extracted(run_id)
    assert loaded is not None
    ot = loaded.employees[0].hours_overtime
    assert ot == Decimal("2"), (
        f"the first snapshot (OT=2) must be preserved; got {ot!r}"
    )


def test_resume_calls_run_stages_exactly_once(fake_repo, mock_llm, monkeypatch):
    """resume_pipeline calls _run_stages exactly once per invocation.

    The Round-1 and Round-2 _run_stages calls are in mutually-exclusive
    if/else branches; exactly one fires per resume_pipeline call. A second call
    would re-extract and re-persist, double-charging the LLM and racing the first
    call's writes.
    """
    import app.pipeline.orchestrator as orch_mod

    call_count = [0]
    original_run_stages = orch_mod._run_stages

    def _counting_run_stages(*args, **kwargs):
        call_count[0] += 1
        return original_run_stages(*args, **kwargs)

    monkeypatch.setattr(orch_mod, "_run_stages", _counting_run_stages)

    # Set up a Round-1 (no clarified_fields yet)
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")
    _set_run_awaiting_reply(fake_repo, run_id)

    # Script: extraction (no field regression → process)
    mock_llm.script = [
        _extraction_json(
            [{"submitted_name": "Maria Chen", "hours_regular": "40", "hours_overtime": "2"}]
        ),
        _suggestion_json({}),
        "Thank you for your reply.",  # draft body (fallback)
    ]

    reply = _inbound("Maria Chen 40 regular 2 overtime. (Same as before.)")
    result = resume_pipeline(run_id, reply)

    assert call_count[0] == 1, (
        f"_run_stages must be called exactly once per resume_pipeline invocation; "
        f"called {call_count[0]} times"
    )
    assert result == PipelineResult(outcome=PipelineOutcome.OK)


def test_resume_result_classification_is_retryable_without_persisting_error(
    fake_repo, monkeypatch
):
    import app.pipeline.orchestrator as orch_mod
    from app.db import repo as repo_module

    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular")
    _set_run_awaiting_reply(fake_repo, run_id)
    persisted_errors: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        orch_mod,
        "extract",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            APIConnectionError(
                message="employee SECRET-NAME in provider payload",
                request=httpx.Request("POST", "https://provider.invalid"),
            )
        ),
    )
    monkeypatch.setattr(
        repo_module,
        "record_run_error",
        lambda *args, **_kwargs: persisted_errors.append(args),
    )

    result = resume_pipeline(run_id, _inbound("Maria Chen 40 regular"))

    assert result.outcome is PipelineOutcome.RETRYABLE
    assert result.diagnostic_code == "extract:provider_connection_failure"
    assert fake_repo.load_run(run_id)["error_reason"] is None
    assert persisted_errors == []
    assert "SECRET-NAME" not in repr(result)


def test_asked_written_before_clarification_send(fake_repo, mock_llm, monkeypatch):
    """clarified_fields records 'asked' BEFORE the clarification email is sent.

    The orchestrator must call set_clarified_fields (writing 'asked') before
    calling _clarify (which writes the outbound row). Never send before writing
    'asked': a crash between the two would leave a question sitting in the
    client's inbox that the system has no record of asking, so the reply would
    be treated as an unrelated inbound.
    """
    import app.db.repo as repo_mod
    from app.pipeline import clarification

    ordering: list[str] = []

    original_set_clarified = fake_repo.set_clarified_fields

    def _spy_set_clarified(run_id, clarified, conn=None):
        ordering.append("set_clarified_fields")
        return original_set_clarified(run_id, clarified, conn=conn)

    monkeypatch.setattr(repo_mod, "set_clarified_fields", _spy_set_clarified)

    original_clarify = clarification.clarify

    def _spy_clarify(run_id, email, decision, roster, extracted, *, llm, purpose="clarification"):
        ordering.append("_clarify")
        return original_clarify(
            run_id, email, decision, roster, extracted, llm=llm, purpose=purpose
        )

    monkeypatch.setattr(clarification, "clarify", _spy_clarify)

    # Set up Round-1 with OT=2 in snapshot, Round-1 reply drops OT → field regression
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")
    _set_run_awaiting_reply(fake_repo, run_id)

    # Script: Round-1 reply with OT=None (regression) — triggers field_regression clarification
    mock_llm.script = [
        _extraction_json([{"submitted_name": "Maria Chen", "hours_regular": "40"}]),
        _suggestion_json({}),
        "Could you confirm the overtime hours?",
    ]

    snapshot = _snapshot_extracted("Maria Chen", hours_regular="40", hours_overtime="2")
    fake_repo.set_pre_clarify_extracted(run_id, snapshot)
    prior_match = _mk_match("Maria Chen", CHEN_ID)
    fake_repo.persist_reconciliation(run_id, [prior_match])

    reply = _inbound("Maria Chen 40 regular hours")
    resume_pipeline(run_id, reply)

    # set_clarified_fields (writing 'asked') must precede _clarify (the send)
    assert "set_clarified_fields" in ordering, "set_clarified_fields must have been called"
    assert "_clarify" in ordering, "_clarify must have been called"
    asked_idx = ordering.index("set_clarified_fields")
    clarify_idx = ordering.index("_clarify")
    assert asked_idx < clarify_idx, (
        f"set_clarified_fields (idx={asked_idx}) must precede _clarify "
        f"(idx={clarify_idx}) — 'asked' must be written before the send"
    )

    # Also assert _clarify was called with purpose='clarification_field_regression'
    # (verifiable by checking outbound row purpose in fake_repo)
    outbound = fake_repo.outbound.get(str(run_id), [])
    assert any(r.get("purpose") == "clarification_field_regression" for r in outbound), (
        "_clarify must be called with purpose='clarification_field_regression'"
    )


def test_ordering_carried_forward_ot_in_paystub(fake_repo, mock_llm):
    """Carried-forward OT=2 lands in the FINAL PAYSTUB LINE ITEM.

    Round-2 path: OT asked, reply is SILENT (OT=None). backfill_extracted must
    run BEFORE _compute_line_items so the paystub sees OT=2.

    The value of this test is that it asserts the PAID value, not just the
    classification label: if backfill_extracted ran AFTER calc, OT would be
    absent from the extracted passed to calculate(), the label would still read
    'carried_forward', and the paystub would silently show OT=0 — an underpay
    with a correct-looking label.
    """
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")
    _setup_round2(fake_repo, run_id, "Maria Chen", CHEN_ID, CHEN_ID_STR)

    # Round-2 reply: OT=None (client silent — should carry forward OT=2).
    # Round-2 does TWO extractions — reply-only (classify) then combined
    # (process/backfill). Both return the same here: OT=None (silence).
    _r2_silent = _extraction_json([{"submitted_name": "Maria Chen", "hours_regular": "40"}])
    mock_llm.script = [_r2_silent, _r2_silent]

    reply = _inbound("Maria Chen 40 regular hours (same as usual)")
    resume_pipeline(run_id, reply)

    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"carried_forward path should reach AWAITING_APPROVAL; got {run['status']!r}"
    )

    # Paystub line item must have OT=2 (backfill fired before calc)
    line_items = fake_repo.load_line_items(run_id)
    assert line_items, "paystub must be computed for a process run"
    chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
    assert chen_items, f"paystub item for Maria Chen ({CHEN_ID_STR}) must exist"
    item = chen_items[0]
    assert item.hours_overtime == Decimal("2"), (
        f"carried-forward OT=2 must appear in the paystub; "
        f"got hours_overtime={item.hours_overtime!r}. "
        "If backfill ran AFTER calc, OT would be absent → paystub OT=0 (underpay)."
    )


def test_approved_bytes_equals_sent_bytes(fake_repo, mock_llm, monkeypatch):
    """The confirmation email's source data is the AWAITING_APPROVAL paystub.

    The paystub at AWAITING_APPROVAL (with carried-forward OT=2) must be the SAME
    data that flows into compose_confirmation when the operator approves the run.
    This pins the approved-equals-sent invariant: the paystub the operator
    approves IS the paystub in the confirmation email. Anything else means the
    human gate approved numbers the client never received.
    """
    import app.pipeline.delivery as delivery

    # Step 1: drive to AWAITING_APPROVAL via Round-2 carry-forward
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")
    _setup_round2(fake_repo, run_id, "Maria Chen", CHEN_ID, CHEN_ID_STR)

    # Round-2 does TWO extractions: reply-only (classify) then combined (process).
    _r2_silent = _extraction_json([{"submitted_name": "Maria Chen", "hours_regular": "40"}])
    mock_llm.script = [_r2_silent, _r2_silent]

    reply = _inbound("Maria Chen 40 regular (same OT applies)")
    resume_pipeline(run_id, reply)

    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_APPROVAL.value

    # Step 2: capture the line items at AWAITING_APPROVAL
    approval_items = fake_repo.load_line_items(run_id)
    assert approval_items, "line items must exist at AWAITING_APPROVAL"
    approval_ot = approval_items[0].hours_overtime
    assert approval_ot == Decimal("2"), (
        f"paystub at AWAITING_APPROVAL must have OT=2; got {approval_ot!r}"
    )

    # Step 3: capture what compose_confirmation receives — the same line items
    # from the repo (the confirmation must use repo.load_line_items, which reads
    # the persisted paystub, not a freshly recomputed one).
    confirmation_items_received: list[Any] = []
    from app.pipeline.compose_email import compose_confirmation as original_compose

    def _capture_compose(paystubs, run, *, timeout_s=3.0):
        confirmation_items_received.extend(paystubs)
        return original_compose(paystubs, run, timeout_s=timeout_s)

    monkeypatch.setattr(
        "app.pipeline.delivery.compose_confirmation", _capture_compose
    )

    # Invoke deliver (the confirmation path)
    run_dict = fake_repo.load_run(run_id)
    delivery.deliver(run_id, run_dict)

    # Assert the confirmation saw the same OT=2 paystub
    assert confirmation_items_received, (
        "compose_confirmation must have been called with paystub items"
    )
    conf_ot = confirmation_items_received[0].hours_overtime
    assert conf_ot == Decimal("2"), (
        f"the confirmation must use the paystub with OT=2; got {conf_ot!r}. "
        "Approved must equal sent — the operator approved OT=2, so the "
        "confirmation email must also carry OT=2."
    )


def test_tri_state_through_real_path(fake_repo, mock_llm):
    """None vs Decimal('0') survive the JSONB round-trip as distinct values.

    The tri-state (absent / explicit zero / positive) is the whole basis of the
    carry-forward decision: None means the client was silent (carry forward), and
    Decimal('0') means the client explicitly removed the hours (honour it). If the
    round-trip collapsed the two, silence would zero out real hours or an explicit
    removal would be re-backfilled — an underpay or an overpay respectively.

    set_pre_clarify_extracted serialises via model_dump(mode='json');
    load_pre_clarify_extracted deserialises via Extracted.model_validate. This
    exercises the SAME serialisation path the real code uses (not hand-typed JSON).
    """
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular")

    # Build snapshot with None OT (absent) and Decimal('0') vacation
    snap = Extracted(
        run_id=run_id,
        employees=[
            ExtractedEmployee(
                submitted_name="Maria Chen",
                hours_regular=Decimal("40"),
                hours_overtime=None,         # explicit None
                hours_vacation=Decimal("0"),  # explicit zero (not None)
            )
        ],
        pay_period_start=date(2026, 6, 15),
    )
    fake_repo.set_pre_clarify_extracted(run_id, snap)

    loaded = fake_repo.load_pre_clarify_extracted(run_id)
    assert loaded is not None
    emp = loaded.employees[0]

    # None survives as None (not 0, not absent)
    assert emp.hours_overtime is None, (
        f"a None OT must round-trip as None (silence), not 0; got {emp.hours_overtime!r}"
    )
    # Decimal('0') survives as Decimal('0') (not None)
    assert emp.hours_vacation == Decimal("0"), (
        f"a Decimal('0') vacation must round-trip as Decimal('0') (an explicit "
        f"removal), not None; got {emp.hours_vacation!r}"
    )


def test_loop_guard_fires_exactly_once(fake_repo, mock_llm):
    """Loop guard: a field-regression clarification fires exactly once.

    Round-1 sets 'asked'. Round-2 reply is silent on OT. The run must reach
    AWAITING_APPROVAL (not a second AWAITING_REPLY — no second clarification).
    """
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")
    _setup_round2(fake_repo, run_id, "Maria Chen", CHEN_ID, CHEN_ID_STR)

    # Round-2 reply: OT=None (silence → carry-forward → process → AWAITING_APPROVAL)
    # Round-2 does TWO extractions: reply-only (classify) then combined (process).
    _r2_silent = _extraction_json([{"submitted_name": "Maria Chen", "hours_regular": "40"}])
    mock_llm.script = [_r2_silent, _r2_silent]

    reply = _inbound("Maria Chen 40 regular hours")
    resume_pipeline(run_id, reply)

    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"Loop guard: Round-2 silence must reach AWAITING_APPROVAL, not AWAITING_REPLY; "
        f"got {run['status']!r}"
    )

    # No second outbound clarification row
    outbound = fake_repo.outbound.get(str(run_id), [])
    field_reg_outbound = [
        r for r in outbound if r.get("purpose") == "clarification_field_regression"
    ]
    assert len(field_reg_outbound) == 0, (
        f"Loop guard: no second field_regression clarification must be sent on Round-2 silence; "
        f"found {len(field_reg_outbound)} outbound rows with purpose=clarification_field_regression"
    )


def test_mixed_issue_records_asked_and_asks_field_regression(fake_repo, mock_llm):
    """Mixed-issue scenario — field_regression AND an unresolved name together.

    When a run has BOTH a field_regression issue (OT dropped) AND a normal
    unresolved-name issue, the clarification must defer under
    purpose='clarification_field_regression'. The 'asked' outcome is recorded in
    clarified_fields, and the outbound email carries that purpose — otherwise the
    dropped field is never marked asked, and the next round re-clarifies it
    forever.
    """
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime, Unknown Bob 38 regular")

    # Set snapshot with Maria Chen OT=2
    snapshot = _snapshot_extracted("Maria Chen", hours_regular="40", hours_overtime="2")
    fake_repo.set_pre_clarify_extracted(run_id, snapshot)
    # Prior reconciliation: Maria Chen resolved, Unknown Bob unresolved
    prior_matches = [
        _mk_match("Maria Chen", CHEN_ID, source="exact"),
        NameMatchResult(
            submitted_name="Unknown Bob",
            matched_employee_id=None,
            source="none",
            resolved=False,
            reason="no roster match",
        ),
    ]
    fake_repo.persist_reconciliation(run_id, prior_matches)
    _set_run_awaiting_reply(fake_repo, run_id)

    # Round-1 reply: Maria Chen OT=None (regression) + Unknown Bob still unresolved
    mock_llm.script = [
        _extraction_json([
            {"submitted_name": "Maria Chen", "hours_regular": "40"},
            {"submitted_name": "Unknown Bob", "hours_regular": "38"},
        ]),
        _suggestion_json({}),
        "We need to confirm the overtime for Maria Chen AND the identity of Unknown Bob.",
    ]

    reply = _inbound("Maria Chen 40 hours. Unknown Bob 38 hours.")
    resume_pipeline(run_id, reply)

    run = fake_repo.load_run(run_id)
    # Must be AWAITING_REPLY (not AWAITING_APPROVAL — mixed issue defers)
    assert run["status"] == RunStatus.AWAITING_REPLY.value, (
        f"a mixed-issue run must be AWAITING_REPLY; got {run['status']!r}"
    )

    # 'asked' must be in clarified_fields for Maria Chen
    clarified = fake_repo.load_clarified_fields(run_id)
    assert CHEN_ID_STR in clarified, "clarified_fields must have an entry for Maria Chen"
    assert clarified[CHEN_ID_STR].get("hours_overtime") == "asked", (
        f"hours_overtime must be 'asked' for Maria Chen; "
        f"got {clarified[CHEN_ID_STR]!r}"
    )

    # The outbound row must carry purpose='clarification_field_regression'
    outbound = fake_repo.outbound.get(str(run_id), [])
    assert any(r.get("purpose") == "clarification_field_regression" for r in outbound), (
        "a mixed-issue run must clarify under purpose='clarification_field_regression'"
    )


def test_restated_name_prior_matches_threading(fake_repo, mock_llm):
    """A restated name ('M. Chen' in snapshot, 'Maria Chen' in reply) must not
    break detection or carry-forward. Both halves are keyed on employee_id, never
    on the submitted name, because the client is free to write the name
    differently in every message.

    PART A (Round-1 — detection):
      'M. Chen' submitted in the original email (snapshot OT=2).
      Round-1 reply uses the full name 'Maria Chen' (same employee_id via alias).
      Reply OT=None → field_regression must be DETECTED and asked.
      Assert: run at AWAITING_REPLY, 'asked' written.
      FAILS if prior_matches is defaulted to None — detect_field_regression then
      returns [] and the run processes instead of clarifying (a silent drop).

    PART B (Round-2 — carry-forward):
      Round-2: 'Maria Chen' is still silent on OT.
      Assert: paystub OT=Decimal('2') (employee_id-keyed backfill carried the value).
      Assert: clarified_fields outcome 'carried_forward'.
      FAILS if backfill_extracted uses a submitted_name-keyed snapshot lookup
      ('Maria Chen' is absent from the prior alias key 'M. Chen' → no carry-forward
      → paystub OT=0, an UNDERPAY).
    """
    # ---- PART A: Round-1 field_regression detected with restated name ----

    run_id = _seed_run(fake_repo, body="M. Chen 40 regular 2 overtime")

    # Snapshot: "M. Chen" OT=2 (the alias name used in original email)
    snapshot = Extracted(
        run_id=run_id,
        employees=[ExtractedEmployee(
            submitted_name="M. Chen",
            hours_regular=Decimal("40"),
            hours_overtime=Decimal("2"),
        )],
        pay_period_start=date(2026, 6, 15),
    )
    fake_repo.set_pre_clarify_extracted(run_id, snapshot)

    # Prior reconciliation: "M. Chen" → CHEN_ID (alias match)
    prior_match_alias = _mk_match("M. Chen", CHEN_ID, source="alias")
    fake_repo.persist_reconciliation(run_id, [prior_match_alias])
    _set_run_awaiting_reply(fake_repo, run_id)

    # Round-1 reply: "Maria Chen" (full name restated) with OT=None.
    # prior_matches must be threaded into detect_field_regression so the
    # employee_id-keyed diff finds "M. Chen" (prior) == "Maria Chen" (current)
    # → same employee_id → OT 2→None is a regression drop → field_regression issue.
    mock_llm.script = [
        _extraction_json([{"submitted_name": "Maria Chen", "hours_regular": "40"}]),
        _suggestion_json({}),
        "Could you confirm Maria Chen's overtime hours?",
    ]

    reply_r1 = _inbound("Maria Chen 40 regular hours this week")
    resume_pipeline(run_id, reply_r1)

    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_REPLY.value, (
        f"the field_regression must be detected (AWAITING_REPLY); "
        f"got {run['status']!r}. "
        "FAILS if prior_matches is defaulted to None — detect_field_regression then "
        "returns [], no drop is detected, and the run processes instead of clarifying."
    )

    clarified = fake_repo.load_clarified_fields(run_id)
    assert CHEN_ID_STR in clarified, (
        "clarified_fields must have an entry for Maria Chen's employee_id"
    )
    assert clarified[CHEN_ID_STR].get("hours_overtime") == "asked", (
        f"hours_overtime must be 'asked'; got {clarified[CHEN_ID_STR]!r}"
    )

    # ---- PART B: Round-2 carry-forward via employee_id-keyed backfill ----
    # Force AWAITING_REPLY (Round-2)
    _set_run_awaiting_reply(fake_repo, run_id)

    # Round-2: "Maria Chen" still silent on OT
    # Round-2 does TWO extractions: reply-only (classify) then combined (process).
    _r2_silent = _extraction_json([{"submitted_name": "Maria Chen", "hours_regular": "40"}])
    mock_llm.script = [_r2_silent, _r2_silent]

    reply_r2 = _inbound("Maria Chen 40 regular hours (OT same as before)")
    resume_pipeline(run_id, reply_r2)

    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"Round-2 silence should reach AWAITING_APPROVAL; got {run['status']!r}"
    )

    # Paystub must have OT=2 (employee_id-keyed backfill_extracted carried it)
    line_items = fake_repo.load_line_items(run_id)
    assert line_items, "paystub must be computed for process run"
    chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
    assert chen_items, "paystub item for Maria Chen must exist"
    ot = chen_items[0].hours_overtime
    assert ot == Decimal("2"), (
        f"the carried-forward paystub must have OT=2; got {ot!r}. "
        "FAILS if backfill_extracted uses a submitted_name-keyed snapshot lookup: "
        "'Maria Chen' is absent from a snapshot keyed by 'M. Chen' → no "
        "carry-forward → UNDERPAY."
    )

    # clarified_fields outcome must be 'carried_forward'
    clarified_r2 = fake_repo.load_clarified_fields(run_id)
    assert clarified_r2.get(CHEN_ID_STR, {}).get("hours_overtime") == "carried_forward", (
        f"the clarified_fields outcome must be 'carried_forward'; "
        f"got {clarified_r2.get(CHEN_ID_STR, {})!r}"
    )


def test_confirmed_dropped_no_reloop_on_round2(fake_repo, mock_llm):
    """A confirmed_dropped field is terminal: it neither re-clarifies nor refills.

    Round-1: 'M. Chen' OT=2 snapshot; Round-1 reply OT=Decimal('0')
    → OT classified as 'confirmed_dropped' (injected here as the terminal state).

    Round-2: 'Maria Chen' OT=None (restated name, same employee_id, silent).
    Assert: OT NOT backfilled (confirmed_dropped is in backfill_skip → the guard
    fires, so the client's removal is honoured and there is no overpay).
    Assert: the run reaches AWAITING_APPROVAL (detection suppressed — no
    re-clarify, so the loop terminates).

    Every key in this path is (employee_id_str, field), never the submitted name,
    because the client may restate the name in any round. FAILS for any of three
    key-type regressions:
    1. the suppress_detection set keyed by submitted_name (not emp_id_str),
    2. a UUID-vs-str mismatch in the set lookup (str(current_emp_id) missing),
    3. the backfill_extracted guard keyed by name instead of (emp_id_str, field).
    """
    run_id = _seed_run(fake_repo, body="M. Chen 40 regular 2 overtime")

    # Snapshot: 'M. Chen' OT=2
    snapshot = Extracted(
        run_id=run_id,
        employees=[ExtractedEmployee(
            submitted_name="M. Chen",
            hours_regular=Decimal("40"),
            hours_overtime=Decimal("2"),
        )],
        pay_period_start=date(2026, 6, 15),
    )
    fake_repo.set_pre_clarify_extracted(run_id, snapshot)
    prior_match = _mk_match("M. Chen", CHEN_ID, source="alias")
    fake_repo.persist_reconciliation(run_id, [prior_match])

    # Simulate Round-1 terminal: OT confirmed_dropped already written
    # (inject the terminal outcome directly to simulate post-Round-1 state)
    clarified = {CHEN_ID_STR: {"hours_overtime": "confirmed_dropped"}}
    fake_repo.set_clarified_fields(run_id, clarified)
    _set_run_awaiting_reply(fake_repo, run_id)

    # Round-2: 'Maria Chen' OT=None (restated name, same employee_id).
    # suppress_detection must use (emp_id_str, field) keys, not names.
    # The current reconciliation resolves 'Maria Chen' → CHEN_ID.
    # Round-2 does TWO extractions: reply-only (classify) then combined (process).
    _r2_silent = _extraction_json([{"submitted_name": "Maria Chen", "hours_regular": "40"}])
    mock_llm.script = [_r2_silent, _r2_silent]

    reply = _inbound("Maria Chen 40 regular hours")
    resume_pipeline(run_id, reply)

    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"detection must be suppressed for a confirmed_dropped OT — no re-clarify; "
        f"got {run['status']!r}. "
        "FAILS if the suppress_detection set uses submitted_name keys instead of "
        "(emp_id_str, field)."
    )

    # OT must NOT be backfilled (confirmed_dropped in backfill_skip → no overpay)
    line_items = fake_repo.load_line_items(run_id)
    if line_items:
        chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
        if chen_items:
            ot = chen_items[0].hours_overtime
            assert ot != Decimal("2"), (
                f"a confirmed_dropped OT must NOT be re-backfilled (that is an "
                f"OVERPAY); got OT={ot!r} (expected 0 or None)"
            )


def test_detect_fired_on_raw(fake_repo, mock_llm, monkeypatch):
    """The three-phase ordering: detect < backfill < validate/calc.

    Detection MUST read the RAW reply, before any backfill. This is the whole
    reason the phases are ordered that way, and this test is the proof.

    PART A: Round-1 — detect_field_regression fires on the RAW (pre-backfill)
      extracted.
      Setup: 'Maria Chen' OT=2 in the snapshot. Round-1 reply has OT=None
      (the client went silent on overtime).
      Assert: (1) a field_regression issue is emitted (run at AWAITING_REPLY),
              (2) 'asked' is written in clarified_fields before _clarify,
              (3) an outbound with purpose='clarification_field_regression' is sent.

      If backfill ran BEFORE detect, the snapshot's OT=2 would fill in the reply's
      None → both sides read OT=2 → no drop → no issue → no clarification, and the
      dropped field would be silently paid from stale data. That regression fails
      assertion (1) (AWAITING_REPLY expected, AWAITING_APPROVAL actual).

    PART B: Round-2 carry-forward — the full round-trip.
      Round-2 reply is still silent on OT → carry-forward fires → paystub OT=2.
      Together with PART A this exercises the ordering end to end.
    """
    import app.pipeline.orchestrator as orch_mod
    from app.pipeline.validate import detect_field_regression

    detected_on_raw_drops = []
    original_detect = detect_field_regression

    def _spy_detect(prior, extracted, prior_matches, matches):
        drops = original_detect(prior, extracted, prior_matches, matches)
        detected_on_raw_drops.extend(drops)
        return drops

    monkeypatch.setattr(orch_mod, "detect_field_regression", _spy_detect)

    # ---- PART A: Round-1 detection on RAW ----
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")

    # Snapshot OT=2
    snapshot = _snapshot_extracted("Maria Chen", hours_regular="40", hours_overtime="2")
    fake_repo.set_pre_clarify_extracted(run_id, snapshot)
    prior_match = _mk_match("Maria Chen", CHEN_ID)
    fake_repo.persist_reconciliation(run_id, [prior_match])
    _set_run_awaiting_reply(fake_repo, run_id)

    # Round-1 reply: OT=None (regression drop)
    mock_llm.script = [
        _extraction_json([{"submitted_name": "Maria Chen", "hours_regular": "40"}]),
        _suggestion_json({}),
        "Please confirm the overtime hours for Maria Chen.",
    ]

    reply_r1 = _inbound("Maria Chen 40 regular hours")
    resume_pipeline(run_id, reply_r1)

    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_REPLY.value, (
        f"the field_regression must be detected (AWAITING_REPLY); "
        f"got {run['status']!r}. "
        "If backfill ran before detect, the OT 2→None drop would be masked → no "
        "issue → no clarification."
    )

    # Drops must have been detected on RAW (pre-backfill) data
    ot_drops = [d for d in detected_on_raw_drops if d.field == "hours_overtime"]
    assert ot_drops, (
        "detect_field_regression must emit an OT drop against the RAW extracted "
        "(pre-backfill). If detect ran post-backfill, the snapshot's OT=2 would "
        "mask the drop."
    )

    # 'asked' must be written
    clarified = fake_repo.load_clarified_fields(run_id)
    assert clarified.get(CHEN_ID_STR, {}).get("hours_overtime") == "asked", (
        "hours_overtime must be 'asked' after field_regression detection"
    )

    # Outbound with purpose='clarification_field_regression'
    outbound = fake_repo.outbound.get(str(run_id), [])
    assert any(r.get("purpose") == "clarification_field_regression" for r in outbound), (
        "a clarification_field_regression outbound must be sent"
    )

    # ---- PART B: Round-2 carry-forward (full round-trip proof) ----
    _set_run_awaiting_reply(fake_repo, run_id)

    # Round-2 does TWO extractions: reply-only (classify) then combined (process).
    _r2_silent = _extraction_json([{"submitted_name": "Maria Chen", "hours_regular": "40"}])
    mock_llm.script = [_r2_silent, _r2_silent]

    reply_r2 = _inbound("Maria Chen 40 regular (OT is the usual 2)")
    resume_pipeline(run_id, reply_r2)

    run_r2 = fake_repo.load_run(run_id)
    assert run_r2["status"] == RunStatus.AWAITING_APPROVAL.value, (
        "Round-2 silence should carry-forward and reach AWAITING_APPROVAL"
    )

    line_items = fake_repo.load_line_items(run_id)
    assert line_items, "paystub must exist"
    chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
    assert chen_items, "paystub item for Maria Chen must exist"
    ot = chen_items[0].hours_overtime
    assert ot == Decimal("2"), (
        f"the carried-forward paystub OT must be 2; got {ot!r}"
    )


def test_client_supplied_same_value_labeled_correctly(fake_repo, mock_llm):
    """The client supplies OT=2 (the SAME value as the snapshot) → 'client_supplied'.

    Classify reads the RAW reply BEFORE backfill. The raw reply has
    OT=Decimal('2') (present-positive) → classified as 'client_supplied'.

    A post-decide reclassifier would instead read the already-backfilled extracted
    (OT=2, restored from the snapshot) and mistake it for silence → 'carried_forward'
    — a label that claims the client never answered when in fact they did. The paid
    value happens to be identical here, so only the label is wrong; but the same
    ordering bug pays the wrong number whenever the client's value differs.

    Assert: the clarified_fields outcome for hours_overtime is 'client_supplied',
    NOT 'carried_forward', and the run reaches AWAITING_APPROVAL.
    """
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")
    _setup_round2(fake_repo, run_id, "Maria Chen", CHEN_ID, CHEN_ID_STR)

    # Round-2 reply: OT=Decimal('2') (same value as snapshot — client re-confirms)
    # Round-2 does TWO extractions: reply-only (classify) then combined (process).
    _r2_ot2 = _extraction_json(
        [{"submitted_name": "Maria Chen", "hours_regular": "40", "hours_overtime": "2"}]
    )
    mock_llm.script = [_r2_ot2, _r2_ot2]

    reply = _inbound("Maria Chen 40 regular 2 overtime (same as last week)")
    resume_pipeline(run_id, reply)

    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"a client_supplied run must reach AWAITING_APPROVAL; got {run['status']!r}"
    )

    clarified = fake_repo.load_clarified_fields(run_id)
    outcome = clarified.get(CHEN_ID_STR, {}).get("hours_overtime")
    assert outcome == "client_supplied", (
        f"OT=2 (the same value as the snapshot) present in the RAW reply must be "
        f"'client_supplied', NOT 'carried_forward'; got {outcome!r}. "
        "A post-decide classifier reads the already-backfilled data and mislabels "
        "it as carried_forward; classify must read the raw reply before backfill."
    )


def test_answered_silence_reaches_approval(fake_repo, mock_llm):
    """An answered-then-silent field reaches AWAITING_APPROVAL in ONE _run_stages call.

    Setup: Round-1 asked OT (snapshot OT=2, clarified={chen_id: {hours_overtime: 'asked'}}).
           Round-2 reply: Maria Chen OT=None (SILENCE — the client does not mention OT).
    Call resume_pipeline (the Round-2 path).

    Assertions:
      1. run status == AWAITING_APPROVAL (NOT AWAITING_REPLY — no second clarification).
      2. paystub hours_overtime == Decimal('2') (carry-forward fired; not dropped).
      3. the clarified_fields outcome for hours_overtime is 'carried_forward'.
      4. no second outbound row with purpose='clarification_field_regression'.

    Why classify must run BEFORE decide:
    classify labels the just-answered OT 'carried_forward' and adds it to
    suppress_detection, so the field-regression re-emission is suppressed, decide
    processes, and backfill restores OT=2 in the paystub.

    Run classify AFTER decide instead and the run strands: the suppression set is
    built from TERMINAL outcomes only, and 'asked' is not terminal, so the
    just-answered OT is absent from it. detect_field_regression then sees OT 2→None
    as a fresh drop, decide returns request_clarification, and the run re-clarifies
    the question the client already answered — forever. That regression fails
    assertion (1) (AWAITING_APPROVAL expected, AWAITING_REPLY actual).
    """
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")
    _setup_round2(fake_repo, run_id, "Maria Chen", CHEN_ID, CHEN_ID_STR)

    # Round-2 reply: OT=None (SILENCE — client does not mention overtime)
    # Round-2 does TWO extractions: reply-only (classify) then combined (process).
    # Both return the same here: OT=None (silence). The classify step sees None →
    # carried_forward. The combined step also sees None → backfill fills OT=2 from
    # snapshot → paystub OT=2.
    _r2_silent = _extraction_json([{"submitted_name": "Maria Chen", "hours_regular": "40"}])
    mock_llm.script = [_r2_silent, _r2_silent]

    reply = _inbound("Maria Chen 40 regular hours this week")
    resume_pipeline(run_id, reply)

    # Assertion 1: run reaches AWAITING_APPROVAL (NOT AWAITING_REPLY)
    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"an answered-then-silent field must reach AWAITING_APPROVAL; "
        f"got {run['status']!r}. "
        "A classify-after-decide ordering strands the run at AWAITING_REPLY, "
        "re-asking a question the client already answered."
    )

    # Assertion 2: paystub OT=2 (carry-forward fired, not dropped)
    line_items = fake_repo.load_line_items(run_id)
    assert line_items, "paystub must be computed"
    chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
    assert chen_items, "paystub item for Maria Chen must exist"
    ot = chen_items[0].hours_overtime
    assert ot == Decimal("2"), (
        f"carry-forward must set paystub OT=2; got {ot!r}. "
        "Silence means the client intended OT=2 to carry forward, not to drop."
    )

    # Assertion 3: clarified_fields outcome is 'carried_forward'
    clarified = fake_repo.load_clarified_fields(run_id)
    outcome = clarified.get(CHEN_ID_STR, {}).get("hours_overtime")
    assert outcome == "carried_forward", (
        f"the outcome must be 'carried_forward'; got {outcome!r}"
    )

    # Assertion 4: no second outbound field_regression clarification
    outbound = fake_repo.outbound.get(str(run_id), [])
    field_reg_rows = [r for r in outbound if r.get("purpose") == "clarification_field_regression"]
    assert len(field_reg_rows) == 0, (
        f"no second clarification_field_regression email must be sent; "
        f"found {len(field_reg_rows)} such rows"
    )


def test_answered_explicit_zero_not_rebackfilled(fake_repo, mock_llm):
    """THE OVERPAY GUARD: an explicit-zero answer is NOT re-backfilled.

    Setup: as in the answered-silence case (snapshot OT=2, 'asked' for OT), EXCEPT
           the Round-2 reply has OT=Decimal('0') — an EXPLICIT ZERO, the client
           removing the overtime.

    Assertions:
      1. run status == AWAITING_APPROVAL (no second clarification).
      2. paystub hours_overtime is None or Decimal('0') — NOT Decimal('2').
         The explicit zero is honoured; the snapshot's OT=2 is NOT restored.
      3. the clarified_fields outcome is 'confirmed_dropped'.

    Why this needs a dedicated guard: `_is_paid(Decimal('0'))` is False, so an
    explicit zero is indistinguishable from silence *by value alone* — it looks
    backfillable. Only the outcome label separates them. classify labels the field
    'confirmed_dropped', which puts (emp_id_str, 'hours_overtime') in backfill_skip,
    and backfill_extracted then skips it. The paystub pays 0, not 2.

    The two outcome sets are deliberately different:
      - confirmed_dropped → suppress_detection AND backfill_skip (never refill).
      - carried_forward   → suppress_detection ONLY, so backfill DOES refill (OT=2).

    Suppressing re-detection alone would not be enough: that only stops the field
    being re-asked, it does not stop backfill from restoring the snapshot value.
    The test FAILS if the paystub shows OT=2 (re-backfilled — an OVERPAY).
    """
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")
    _setup_round2(fake_repo, run_id, "Maria Chen", CHEN_ID, CHEN_ID_STR)

    # Round-2 reply: OT=Decimal('0') (EXPLICIT ZERO — client removes overtime)
    # Round-2 does TWO extractions: reply-only (classify) then combined (process).
    # Both return OT=0 here. The reply-only classify step sees Decimal('0') →
    # confirmed_dropped → backfill_skip. The combined step also sees OT=0 (no
    # restoration from snapshot). Paystub OT=0.
    _r2_zero = _extraction_json(
        [{"submitted_name": "Maria Chen", "hours_regular": "40", "hours_overtime": "0"}]
    )
    mock_llm.script = [_r2_zero, _r2_zero]

    reply = _inbound("Maria Chen 40 regular hours, 0 overtime this week")
    resume_pipeline(run_id, reply)

    # Assertion 1: run reaches AWAITING_APPROVAL (no second clarification)
    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"an explicit-zero answer must reach AWAITING_APPROVAL; "
        f"got {run['status']!r}"
    )

    # Assertion 2: paystub OT is 0 or None — NOT 2 (no re-backfill = no overpay)
    line_items = fake_repo.load_line_items(run_id)
    if line_items:
        chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
        if chen_items:
            ot = chen_items[0].hours_overtime
            assert ot != Decimal("2"), (
                f"an explicit-zero OT=0 must NOT be re-backfilled to 2; got {ot!r}. "
                "_is_paid(Decimal('0')) is False, so an explicit zero looks "
                "backfillable by value alone; the backfill_skip gate "
                "(confirmed_dropped) is the only protection."
            )

    # Assertion 3: clarified_fields outcome is 'confirmed_dropped'
    clarified = fake_repo.load_clarified_fields(run_id)
    outcome = clarified.get(CHEN_ID_STR, {}).get("hours_overtime")
    assert outcome == "confirmed_dropped", (
        f"OT=Decimal('0') must be 'confirmed_dropped'; got {outcome!r}"
    )


def test_answered_positive_uses_client_value(fake_repo, mock_llm):
    """A positive answered field pays the client's value, not the snapshot's.

    Setup: as in the answered-silence case (snapshot OT=2, 'asked' for OT), EXCEPT
           the Round-2 reply has OT=Decimal('5') — the client supplies a different
           amount.

    Assertions:
      1. run status == AWAITING_APPROVAL.
      2. paystub hours_overtime == Decimal('5') (the client's value, NOT snapshot OT=2).
      3. the clarified_fields outcome is 'client_supplied'.

    classify sees OT=Decimal('5') in the raw reply → present-positive →
    'client_supplied', which lands in backfill_skip, so backfill never overwrites it
    with the snapshot's 2. The raw extracted already carries OT=5, so
    _compute_line_items pays 5.
    """
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")
    _setup_round2(fake_repo, run_id, "Maria Chen", CHEN_ID, CHEN_ID_STR)

    # Round-2 reply: OT=Decimal('5') (POSITIVE VALUE — client supplies a different amount)
    # Round-2 does TWO extractions: reply-only (classify) then combined (process).
    # Both return OT=5 here. The reply-only classify step sees Decimal('5') > 0 →
    # client_supplied → backfill_skip. Paystub uses raw extracted OT=5.
    _r2_ot5 = _extraction_json(
        [{"submitted_name": "Maria Chen", "hours_regular": "40", "hours_overtime": "5"}]
    )
    mock_llm.script = [_r2_ot5, _r2_ot5]

    reply = _inbound("Maria Chen 40 regular 5 overtime hours this week")
    resume_pipeline(run_id, reply)

    # Assertion 1: run reaches AWAITING_APPROVAL
    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"a client_supplied run must reach AWAITING_APPROVAL; "
        f"got {run['status']!r}"
    )

    # Assertion 2: paystub OT=5 (client-supplied value, not snapshot OT=2)
    line_items = fake_repo.load_line_items(run_id)
    assert line_items, "paystub must be computed"
    chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
    assert chen_items, "paystub item for Maria Chen must exist"
    ot = chen_items[0].hours_overtime
    assert ot == Decimal("5"), (
        f"the paystub OT must be 5 (the client's value); got {ot!r} — NOT the "
        f"snapshot's OT=2. backfill_extracted skips client_supplied fields (they "
        f"are in backfill_skip); the raw extracted OT=5 flows straight to "
        f"_compute_line_items."
    )

    # Assertion 3: clarified_fields outcome is 'client_supplied'
    clarified = fake_repo.load_clarified_fields(run_id)
    outcome = clarified.get(CHEN_ID_STR, {}).get("hours_overtime")
    assert outcome == "client_supplied", (
        f"the outcome must be 'client_supplied'; got {outcome!r}"
    )


def test_round2_new_regression_reaches_awaiting_reply(fake_repo, mock_llm):
    """A Round-2 reply that introduces a NEW field regression sends a clarification
    and reaches AWAITING_REPLY — it must NOT stall at 'extracting'.

    Setup:
    - Snapshot: Maria Chen hours_overtime=2, hours_holiday=8.
    - Round-1 asked ONLY about hours_overtime (snapshot OT=2 dropped).
    - Round-2 reply: answers OT (present-positive, OT=2) but NOW drops hours_holiday
      (8 → absent in reply). suppress_detection covers only (CHEN_ID, hours_overtime)
      from Round-1. detect_field_regression emits a NEW drop for hours_holiday (NOT
      suppressed) → validate → decide → request_clarification → clarify_deferred=True.

    The failure mode this guards:
      if the Round-2 branch IGNORES stage.clarify_deferred it falls through to
      set_clarified_fields + the alias diff, and the run is left at 'extracting'
      with no email sent — a silent hang, with the client waiting on a question
      that was never asked. Nothing may ever silently hang.

    The correct behaviour (asserted here):
      defer_field_regression_clarification() runs → 'asked' is written for
      hours_holiday → a clarification_field_regression email is sent → the run
      reaches AWAITING_REPLY.

    Note: Round-2 does TWO extractions (reply-only for classify, combined for
    process). Both are scripted to return OT=2, holiday=None (dropped). The
    clarification path fires before the _run_stages process branch, so no paystub
    is computed.
    """
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime 8 holiday")

    # Snapshot: Maria Chen OT=2, holiday=8 (two positive fields).
    snapshot = Extracted(
        run_id=run_id,
        employees=[ExtractedEmployee(
            submitted_name="Maria Chen",
            hours_regular=Decimal("40"),
            hours_overtime=Decimal("2"),
            hours_holiday=Decimal("8"),
        )],
        pay_period_start=date(2026, 6, 15),
    )
    fake_repo.set_pre_clarify_extracted(run_id, snapshot)

    # Prior matches: Maria Chen → CHEN_ID (exact match)
    prior_match = _mk_match("Maria Chen", CHEN_ID, source="exact")
    fake_repo.persist_reconciliation(run_id, [prior_match])

    # Round-1 state: ONLY hours_overtime was asked (holiday was not yet dropped in R1).
    clarified = {CHEN_ID_STR: {"hours_overtime": "asked"}}
    fake_repo.set_clarified_fields(run_id, clarified)
    _set_run_awaiting_reply(fake_repo, run_id)

    # Round-2 reply: answers OT (OT=2, present-positive) but DROPS hours_holiday (absent).
    # suppress_detection covers (CHEN_ID, hours_overtime) only from Round-1 'asked'.
    # detect_field_regression on raw reply: holiday 8→None → NEW drop (not suppressed).
    # → validate → field_regression issue for holiday → decide → request_clarification.
    # → _run_stages returns clarify_deferred=True.
    #
    # Two extractions — reply-only (classify) then combined (process).
    # Both return OT=2 (answered) and holiday=None (newly dropped).
    _r2_holiday_dropped = _extraction_json([{
        "submitted_name": "Maria Chen",
        "hours_regular": "40",
        "hours_overtime": "2",
        # hours_holiday ABSENT → None → newly dropped → field_regression
    }])
    # The clarification path also needs suggestion + body responses.
    mock_llm.script = [
        _r2_holiday_dropped,   # Extraction 1: reply-only (classify)
        _r2_holiday_dropped,   # Extraction 2: combined (process/backfill in _run_stages)
        _suggestion_json({}),  # suggest_employees (no unresolved names)
        "Could you confirm Maria Chen's holiday hours?",  # compose_clarification
    ]

    reply = _inbound("Maria Chen 40 regular 2 overtime. (No holiday this week.)")
    resume_pipeline(run_id, reply)

    # Assertion 1: run must be AWAITING_REPLY (NOT stuck at 'extracting')
    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_REPLY.value, (
        f"a Round-2 reply introducing a NEW field regression must reach AWAITING_REPLY; "
        f"got {run['status']!r}. "
        "Ignoring stage.clarify_deferred leaves the run stuck at 'extracting' with "
        "no email sent; defer_field_regression_clarification() must send it."
    )

    # Assertion 2: a clarification_field_regression outbound row must exist
    outbound = fake_repo.outbound.get(str(run_id), [])
    field_reg_rows = [r for r in outbound if r.get("purpose") == "clarification_field_regression"]
    assert len(field_reg_rows) >= 1, (
        f"a clarification_field_regression outbound email must be sent; "
        f"found {len(field_reg_rows)} such rows. "
        "defer_field_regression_clarification() must call _clarify with "
        "purpose='clarification_field_regression'."
    )

    # Assertion 3: 'asked' must be written for the NEW drop (hours_holiday) BEFORE the send
    clarified_after = fake_repo.load_clarified_fields(run_id)
    hours_holiday_outcome = clarified_after.get(CHEN_ID_STR, {}).get("hours_holiday")
    assert hours_holiday_outcome == "asked", (
        f"hours_holiday must be 'asked' in clarified_fields, written before the send; "
        f"got {hours_holiday_outcome!r}. "
        "defer_field_regression_clarification must write 'asked' for the NEW "
        "field_regression drop."
    )

    # Assertion 4: hours_overtime outcome must be 'client_supplied' (answered in Round-2 classify)
    ot_outcome = clarified_after.get(CHEN_ID_STR, {}).get("hours_overtime")
    assert ot_outcome == "client_supplied", (
        f"hours_overtime (answered in Round-2 with OT=2) must be 'client_supplied'; "
        f"got {ot_outcome!r}."
    )


def test_explicit_zero_overpay_guard_with_prompt_inspecting_mock(
    fake_repo, mock_llm, monkeypatch
):
    """Classify must read the REPLY-ONLY extraction, never the combined body.

    Test approach: a PROMPT-INSPECTING MOCK (no live LLM). The mock's create()
    inspects the user message for "ORIGINAL PAYROLL EMAIL:" — the delimiter that
    _combined_context_email inserts:
    - Reply-only call (no delimiter): returns OT=0 (the client's explicit zero).
    - Combined call (delimiter present): returns OT=2 (adversarial — the original
      section's value wins over the reply's).

    The combined body contains BOTH the original email (OT=2) and the reply (OT=0),
    so an extraction over it can legitimately return either. Classify must therefore
    never be fed the combined body: if it were, the original section's positive value
    could eclipse the client's explicit zero, the field would be labelled
    'client_supplied' instead of 'confirmed_dropped', and OT=2 would flow through to
    the paystub — an OVERPAY of hours the client explicitly removed.

    Two assertions, deliberately separate:
      - the classify LABEL is 'confirmed_dropped' (it read the reply-only OT=0), and
      - the PAID value on the paystub is 0.
    Fixing the label alone is not enough; the raw extracted must also be reconciled
    to the reply-derived value, or the label is right and the money is still wrong.
    """
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")
    _setup_round2(fake_repo, run_id, "Maria Chen", CHEN_ID, CHEN_ID_STR)

    # Prompt-inspecting mock: inspects the user message for "ORIGINAL PAYROLL EMAIL:"
    # (the delimiter _combined_context_email inserts).
    #
    # Reply-only classify call (no delimiter in body):
    #   → mock returns OT=0 (the explicit zero from the reply)
    #   → must be classified as 'confirmed_dropped'
    #
    # Combined process/backfill call (delimiter present):
    #   → mock returns OT=2 (adversarial: the original section's value eclipses the
    #     reply's) — the exact failure mode a combined-body classify would hit.
    #
    # Key assertion: the classify outcome is 'confirmed_dropped' (not
    # 'client_supplied'), proving classify saw OT=0 from the reply-only extraction.
    from tests.conftest import _MockCompletions

    call_count = [0]

    def _prompt_inspecting_create(self, **kwargs):
        call_count[0] += 1
        mock_llm.calls.append(kwargs)
        messages = kwargs.get("messages", [])
        user_content = messages[1]["content"] if len(messages) > 1 else ""
        if "ORIGINAL PAYROLL EMAIL:" in user_content:
            # Combined body: adversarial — return OT=2 (original section wins)
            content = _extraction_json([{
                "submitted_name": "Maria Chen",
                "hours_regular": "40",
                "hours_overtime": "2",
            }])
        else:
            # Reply-only body: return OT=0 (client's explicit zero in the reply)
            content = _extraction_json([{
                "submitted_name": "Maria Chen",
                "hours_regular": "40",
                "hours_overtime": "0",
            }])
        return type("_R", (), {
            "choices": [type("_C", (), {
                "message": type("_M", (), {"content": content})()
            })()]
        })()

    monkeypatch.setattr(_MockCompletions, "create", _prompt_inspecting_create)

    reply = _inbound("Maria Chen 40 regular 0 overtime this week")
    resume_pipeline(run_id, reply)

    # Assertion 1: the classify outcome must be 'confirmed_dropped' (reply-only OT=0).
    # If classify used the combined extraction (adversarial mock returns OT=2), the
    # outcome would be 'client_supplied' — the original section's positive value
    # eclipsing the reply's explicit zero.
    clarified = fake_repo.load_clarified_fields(run_id)
    outcome = clarified.get(CHEN_ID_STR, {}).get("hours_overtime")
    assert outcome == "confirmed_dropped", (
        f"classify must use the REPLY-ONLY extraction → OT=0 → 'confirmed_dropped'; "
        f"got {outcome!r}. "
        "Classifying off the combined body lets the adversarial OT=2 win → "
        "'client_supplied' → the paystub pays OT=2 = OVERPAY."
    )

    # Assertion 2: at least 2 extraction LLM calls (reply-only classify + combined process)
    assert call_count[0] >= 2, (
        f"Round-2 must make at least 2 LLM extraction calls; got {call_count[0]}. "
        "The first is reply-only (classify); the second is combined (process/backfill)."
    )

    # Assertion 3: run reaches AWAITING_APPROVAL (OT asked and answered → process path)
    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"after answering OT=0, the run must reach AWAITING_APPROVAL; "
        f"got {run['status']!r}"
    )

    # Assertion 4 — the MONEY assertion, deliberately separate from the label:
    # the adversarial mock returns OT=2 from the combined extraction. If _run_stages
    # sees raw_extracted with OT=2, the paystub pays OT=2 even though classify
    # correctly labelled the field 'confirmed_dropped'. A correct label with a wrong
    # paid value is still an overpay — so assert the paid value, not just the label.
    line_items = fake_repo.load_line_items(run_id)
    assert line_items, (
        "line_items must be computed on a process run"
    )
    chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
    assert chen_items, "paystub item for Maria Chen must exist"
    ot_paid = chen_items[0].hours_overtime
    assert ot_paid == Decimal("0"), (
        f"the paystub OT must be 0 (reply-derived, confirmed_dropped); got {ot_paid!r}. "
        "Otherwise the combined extraction's adversarial OT=2 flows to _run_stages → "
        "paystub OT=2 = OVERPAY, even with a correct 'confirmed_dropped' label. "
        "raw_extracted's OT field must be overwritten with the reply-derived value (0) "
        "so the paid value matches the classify decision."
    )


def test_extraction_divergence_confirmed_dropped_paystub_value(fake_repo, mock_llm, monkeypatch):
    """Extraction divergence, confirmed_dropped case — the paystub must pay OT=0, not 2.

    Drives resume_pipeline with a prompt-inspecting mock where the TWO extractions
    DISAGREE on the asked field:
      - Reply-only (classify): OT=0 (the client's explicit zero → confirmed_dropped)
      - Combined (process):    OT=2 (adversarial: the original section's value
                                     eclipses the reply's)

    When the two disagree, the reply-only value is authoritative for an asked field:
    it is the client's answer to the question we asked. If _run_stages instead
    receives raw_extracted with OT=2 (the combined value), the paystub pays OT=2 —
    an OVERPAY — even though classify correctly labels the outcome
    'confirmed_dropped'.

    The reply-derived value must therefore be written back into raw_extracted
    (reply_value_overrides[(CHEN_ID_STR, 'hours_overtime')] = Decimal('0')) before
    _run_stages runs, so the PAID value matches the classify decision.
    """
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")
    _setup_round2(fake_repo, run_id, "Maria Chen", CHEN_ID, CHEN_ID_STR)

    from tests.conftest import _MockCompletions

    def _diverge_zero_vs_two(self, **kwargs):
        mock_llm.calls.append(kwargs)
        messages = kwargs.get("messages", [])
        user_content = messages[1]["content"] if len(messages) > 1 else ""
        if "ORIGINAL PAYROLL EMAIL:" in user_content:
            # Combined body call: adversarial — original section returns OT=2
            content = _extraction_json([{
                "submitted_name": "Maria Chen",
                "hours_regular": "40",
                "hours_overtime": "2",
            }])
        else:
            # Reply-only classify call: OT=0 (client's explicit zero)
            content = _extraction_json([{
                "submitted_name": "Maria Chen",
                "hours_regular": "40",
                "hours_overtime": "0",
            }])
        return type("_R", (), {
            "choices": [type("_C", (), {
                "message": type("_M", (), {"content": content})()
            })()]
        })()

    monkeypatch.setattr(_MockCompletions, "create", _diverge_zero_vs_two)

    reply = _inbound("Maria Chen 40 regular 0 overtime this week")
    resume_pipeline(run_id, reply)

    # Assertion 1: classify outcome must be 'confirmed_dropped'
    clarified = fake_repo.load_clarified_fields(run_id)
    outcome = clarified.get(CHEN_ID_STR, {}).get("hours_overtime")
    assert outcome == "confirmed_dropped", (
        f"classify must see the reply's OT=0 → 'confirmed_dropped'; got {outcome!r}"
    )

    # Assertion 2: run reaches AWAITING_APPROVAL
    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"the run must reach AWAITING_APPROVAL after answering OT=0; got {run['status']!r}"
    )

    # Assertion 3 — the MONEY assertion: the paystub OT must be 0, NOT the combined
    # extraction's 2. A correct 'confirmed_dropped' label with a paid OT=2 is still
    # an overpay, so the paid value is what gets asserted here.
    line_items = fake_repo.load_line_items(run_id)
    assert line_items, "the paystub must be computed on a process run"
    chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
    assert chen_items, "the paystub item for Maria Chen must exist"
    ot_paid = chen_items[0].hours_overtime
    assert ot_paid == Decimal("0"), (
        f"the paystub OT must be 0 (the reply said 0 = drop); got {ot_paid!r}. "
        "Reply-only extraction: OT=0. Combined extraction (adversarial): OT=2. "
        "If _run_stages sees OT=2 from the combined extraction, the paystub pays "
        "OT=2 = OVERPAY even though classify says 'confirmed_dropped'. raw_extracted's "
        "OT must be overwritten to 0 before _run_stages."
    )


def test_extraction_divergence_client_supplied_paystub_value(fake_repo, mock_llm, monkeypatch):
    """Extraction divergence, client_supplied case — the paystub must pay OT=5, not 2.

    Drives resume_pipeline with a prompt-inspecting mock where the TWO extractions
    DISAGREE on the asked field:
      - Reply-only (classify): OT=5 (the client supplied a new amount → client_supplied)
      - Combined (process):    OT=2 (adversarial: the original section's value
                                     eclipses the reply's)

    The mirror image of the confirmed_dropped case: if _run_stages receives
    raw_extracted with OT=2, the paystub pays OT=2 — an UNDERPAY, silently discarding
    the OT=5 the client actually supplied.

    The reply-derived value must be written back into raw_extracted
    (reply_value_overrides[(CHEN_ID_STR, 'hours_overtime')] = Decimal('5')) before
    _run_stages runs.
    """
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")
    _setup_round2(fake_repo, run_id, "Maria Chen", CHEN_ID, CHEN_ID_STR)

    from tests.conftest import _MockCompletions

    def _diverge_five_vs_two(self, **kwargs):
        mock_llm.calls.append(kwargs)
        messages = kwargs.get("messages", [])
        user_content = messages[1]["content"] if len(messages) > 1 else ""
        if "ORIGINAL PAYROLL EMAIL:" in user_content:
            # Combined body call: adversarial — original section returns OT=2
            content = _extraction_json([{
                "submitted_name": "Maria Chen",
                "hours_regular": "40",
                "hours_overtime": "2",
            }])
        else:
            # Reply-only classify call: OT=5 (client supplies a different amount)
            content = _extraction_json([{
                "submitted_name": "Maria Chen",
                "hours_regular": "40",
                "hours_overtime": "5",
            }])
        return type("_R", (), {
            "choices": [type("_C", (), {
                "message": type("_M", (), {"content": content})()
            })()]
        })()

    monkeypatch.setattr(_MockCompletions, "create", _diverge_five_vs_two)

    reply = _inbound("Maria Chen 40 regular 5 overtime hours this week")
    resume_pipeline(run_id, reply)

    # Assertion 1: classify outcome must be 'client_supplied'
    clarified = fake_repo.load_clarified_fields(run_id)
    outcome = clarified.get(CHEN_ID_STR, {}).get("hours_overtime")
    assert outcome == "client_supplied", (
        f"classify must see the reply's OT=5 → 'client_supplied'; got {outcome!r}"
    )

    # Assertion 2: run reaches AWAITING_APPROVAL
    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"the run must reach AWAITING_APPROVAL after answering OT=5; got {run['status']!r}"
    )

    # Assertion 3 — the MONEY assertion: the paystub OT must be 5, NOT the combined
    # extraction's 2 (which would silently discard the client's answer).
    line_items = fake_repo.load_line_items(run_id)
    assert line_items, "the paystub must be computed on a process run"
    chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
    assert chen_items, "the paystub item for Maria Chen must exist"
    ot_paid = chen_items[0].hours_overtime
    assert ot_paid == Decimal("5"), (
        f"the paystub OT must be 5 (the client's supplied value); got {ot_paid!r}. "
        "Reply-only extraction: OT=5. Combined extraction (adversarial): OT=2. "
        "If _run_stages sees OT=2 from the combined extraction, the paystub pays "
        "OT=2 = UNDERPAY and the client's OT=5 is silently discarded. raw_extracted's "
        "OT must be overwritten to 5 before _run_stages."
    )


def test_extraction_divergence_unresolvable_asked_money_safe(fake_repo, mock_llm, monkeypatch):
    """Extraction divergence, unresolvable-asked case — a combined OT=2 must NOT be paid.

    Drives resume_pipeline with a prompt-inspecting mock where:
      - Reply-only (classify): the employee is OMITTED (the reply never mentions
        Maria Chen) → (CHEN_ID, hours_overtime) is unresolvable → the field stays
        unanswered
      - Combined (process): Maria Chen OT=2 (adversarial: the original section
        carries the value forward)

    This is the subtlest of the three divergence cases. Marking the field
    unresolvable puts (CHEN_ID, OT) in backfill_skip, which prevents a snapshot
    RESTORE — but the combined extraction has already placed OT=2 directly into
    raw_extracted, and that flows straight to _compute_line_items. The run would
    reach AWAITING_APPROVAL paying OT=2 on a field still marked 'asked', with no
    re-clarification: money paid on a question the client never answered.

    Forcing raw_extracted's OT to None before _run_stages
    (reply_value_overrides[(CHEN_ID_STR, 'hours_overtime')] = None) makes the field
    genuinely absent, so validate/decide either request a clarification or refuse to
    advance. Either is money-safe. The invariant asserted here is narrow and
    absolute: OT=2 must NOT be paid while the field is still 'asked'.
    """
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")
    _setup_round2(fake_repo, run_id, "Maria Chen", CHEN_ID, CHEN_ID_STR)

    from tests.conftest import _MockCompletions

    def _diverge_absent_vs_two(self, **kwargs):
        mock_llm.calls.append(kwargs)
        messages = kwargs.get("messages", [])
        user_content = messages[1]["content"] if len(messages) > 1 else ""
        if "ORIGINAL PAYROLL EMAIL:" in user_content:
            # Combined body call: adversarial — original section carries Maria Chen OT=2
            content = _extraction_json([{
                "submitted_name": "Maria Chen",
                "hours_regular": "40",
                "hours_overtime": "2",
            }])
        else:
            # Reply-only classify call: Maria Chen is ABSENT from the reply entirely
            # → _unresolvable_asked (raw_emp is None for CHEN_ID)
            content = _extraction_json([])  # empty employees list
        return type("_R", (), {
            "choices": [type("_C", (), {
                "message": type("_M", (), {"content": content})()
            })()]
        })()

    monkeypatch.setattr(_MockCompletions, "create", _diverge_absent_vs_two)

    reply = _inbound("(No update for Maria Chen this week)")
    resume_pipeline(run_id, reply)

    # Assertion 1 (MONEY-SAFE): the run must NOT reach AWAITING_APPROVAL paying OT=2
    # on a field still 'asked'. Either:
    #   (a) run is at AWAITING_REPLY (re-clarification fired — the safest outcome), OR
    #   (b) run is at AWAITING_APPROVAL with paystub OT != 2 (genuinely under-filled).
    # What is NOT acceptable: AWAITING_APPROVAL with paystub OT=2 (paid on unanswered field).
    run = fake_repo.load_run(run_id)
    status = run["status"]

    line_items = fake_repo.load_line_items(run_id)
    chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
    ot_paid = chen_items[0].hours_overtime if chen_items else None

    # If the run reached AWAITING_APPROVAL, the paystub OT must NOT be 2 (the
    # combined extraction's adversarial value for an unanswered asked field).
    if status == RunStatus.AWAITING_APPROVAL.value:
        assert ot_paid != Decimal("2"), (
            f"the run reached AWAITING_APPROVAL but the paystub shows OT={ot_paid!r}. "
            "That is an overpay: the combined extraction carried OT=2 for a field still "
            "marked 'asked' (unanswered). The field must be genuinely absent (OT=0 or "
            "None), never paid at OT=2 because the combined extraction eclipsed the "
            "unanswered state. raw_extracted's OT must be forced to None so validate/decide "
            "can route it money-safely."
        )
    # If the run is at AWAITING_REPLY — the re-clarification fired — that is also
    # money-safe (the field was not paid). No further assertion needed for that path.
    # (Any other status — e.g. ERROR — indicates a pipeline failure, acceptable as
    #  money-safe but worth noting; we don't assert the exact status here, only that
    #  OT=2 is never paid on an unanswered field.)
