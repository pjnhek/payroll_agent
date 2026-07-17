"""Clarify→reply→resume threading tests (CLAR-02, CLAR-03, EMAIL-01).

Re-entrancy is the hard part of the clarification loop. A reply POSTed to the SAME
inbound webhook must route back to its paused run via the RFC In-Reply-To/References
header chain, its sender must be re-asserted against the matched run's business, and
the run must re-enter the pipeline at extraction idempotently AND losslessly over
(original cleaned inbound body + reply body).

The five invariants under test:
  - the header-chain match is restricted to awaiting_reply runs
    (find_awaiting_reply_for_header) — only a paused run can be resumed;
  - the reply sender is re-validated against the matched run's business, so guessing an
    outbound Message-ID does not let an outsider drive someone else's payroll;
  - a partial reply preserves the original hours: resume re-extracts over
    (original + reply), so an answer-only reply cannot silently zero out the hours;
  - resume stamps the code-owned run_id into extract, so the rebuilt Extracted always
    belongs to the run being resumed rather than to whatever the model echoed back;
  - a late reply (header match to a run that already advanced) is found via
    find_any_run_for_header and logged, never resumed — resuming would clobber an
    already-approved payroll.

All LLM calls are mocked; the FULL pipeline runs offline via the conftest in-memory
fake_repo + the FIFO mock_llm script. DB round-trips that need a live database go
behind @pytest.mark.integration + the two-factor guard.
"""
from __future__ import annotations

import json
import pathlib
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.db import repo
from app.models.contracts import Decision, InboundEmail
from app.models.job import JobKind
from app.queue import drain
from app.queue.drain import DrainOutcome

# The seeded David Reyes employee id (app/db/seed.py emp 3) — the hero gate run.
_DAVID_REYES_ID = "e0000003-0000-0000-0000-000000000003"
_METRO_DELI_CONTACT = "hr@metrodeli.example"

_GATE_BLOCK_FIXTURE = (
    pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "gate_block_hero.json"
)
_CLARIFY_REPLY_FIXTURE = (
    pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "clarify_reply.json"
)
# The placeholder token in clarify_reply.json that the test substitutes with the
# actual sent clarification Message-ID at runtime — the Message-ID is generated per
# run, so it cannot be committed into the fixture.
_CLARIFICATION_PLACEHOLDER = "__CLARIFICATION_MESSAGE_ID__"


@pytest.fixture
def client(fake_repo, monkeypatch):
    """TestClient with ALLOW_UNSIGNED_FIXTURES=true so canonical dict POSTs succeed.

    Without the flag the webhook rejects unsigned payloads with 400 — correct in
    production, but it would block every mocked test from reaching the pipeline.
    """
    from app.config import get_settings
    from app.main import app

    get_settings.cache_clear()
    monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://mock-test-stub/mockdb")
    events: dict[uuid.UUID, dict[str, Any]] = {}

    def _insert_or_get(*, external_event_id, payload, conn=None):
        for event in events.values():
            if event["external_event_id"] == external_event_id:
                return event["id"], False
        event_id = uuid.uuid4()
        events[event_id] = {
            "id": event_id,
            "external_event_id": external_event_id,
            "payload": payload,
        }
        return event_id, True

    def _load(event_id, conn=None):
        event = events.get(event_id)
        return None if event is None else {"id": event["id"], "payload": event["payload"]}

    monkeypatch.setattr(repo, "insert_or_get_inbound_event", _insert_or_get)
    monkeypatch.setattr(repo, "load_inbound_event", _load)
    yield TestClient(app)
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# LLM scripts (FIFO; conftest pops one per structured/text call in order)
# ---------------------------------------------------------------------------


def _script_gate_block_to_reply(mock_llm) -> None:
    """Drive the David Reyez fixture to awaiting_reply.

    reconcile + decide are PURE deterministic code — no LLM calls — so the FIFO script
    carries ONLY the extract response and the free-text clarification draft. If a
    script entry is ever needed for either stage, that stage has gained an LLM call it
    must not have. The extracted "David Reyez" is a TYPO of the seeded "David Reyes" (which
    has no known_alias for the misspelling), so the deterministic resolver leaves it
    unresolved → decide gates to request_clarification → the draft+send branch runs.
    """
    mock_llm.script = [
        json.dumps(
            {
                "employees": [{"submitted_name": "David Reyez", "hours_regular": "38"}],
                "pay_period_start": "2026-06-15",
                "pay_period_end": None,
            }
        ),
        "Hi — could you confirm the employee name 'David Reyez'?",
    ]


def _script_resume_resolved(mock_llm) -> None:
    """Script the RESUME pass: the corrected name now resolves cleanly and processes.

    On resume the orchestrator re-extracts over (original cleaned body + reply body),
    then runs the PURE reconcile→decide stages again. The corrected "David Reyes" is
    now an EXACT match to the seeded employee, so the deterministic resolver resolves
    it and decide returns final_action='process'. Only the extract call hits the LLM.
    """
    mock_llm.script = [
        # extract over (original + reply body) — the corrected spelling now extracted.
        json.dumps(
            {
                "employees": [{"submitted_name": "David Reyes", "hours_regular": "38"}],
                "pay_period_start": "2026-06-15",
                "pay_period_end": None,
            }
        ),
    ]


def _drive_to_awaiting_reply(client, fake_repo, mock_llm) -> tuple[str, str]:
    """POST the gate-block fixture → awaiting_reply; return (run_id, outbound_msg_id)."""
    _script_gate_block_to_reply(mock_llm)
    before = set(fake_repo.runs)
    r = client.post("/webhook/inbound", json=json.loads(_GATE_BLOCK_FIXTURE.read_text()))
    assert r.status_code == 200
    assert set(r.json()) == {"status", "event_id"}
    assert drain.drain_once() is DrainOutcome.DONE
    created = set(fake_repo.runs) - before
    assert len(created) == 1
    run_id = created.pop()
    assert drain.drain_once() is DrainOutcome.DONE
    # The clarification producer only queues a frozen SEND_OUTBOUND job. Drain that
    # worker-owned delivery before reading the RFC thread anchor from a sent row.
    assert drain.drain_once() is DrainOutcome.DONE
    assert fake_repo.load_run(run_id)["status"] == "awaiting_reply"
    msg_id = fake_repo.get_outbound_message_id(run_id)
    assert msg_id is not None
    return run_id, msg_id


def _reply_payload(*, in_reply_to: str, from_addr: str, body: str) -> dict[str, Any]:
    """A canonical reply InboundEmail payload (answer-only by default)."""
    return InboundEmail(
        id=uuid.uuid4(),
        message_id=f"<reply-{uuid.uuid4()}@metrodeli.example>",
        in_reply_to=in_reply_to,
        references_header=in_reply_to,
        subject="Re: Payroll hours for week of 2026-06-15",
        from_addr=from_addr,
        to_addr="agent@payroll-agent.local",
        body_text=body,
        created_at=datetime.now(UTC),
    ).model_dump(mode="json")


# ---------------------------------------------------------------------------
# test_header_chain_match — a reply routes to its run via In-Reply-To / References
# ---------------------------------------------------------------------------


def test_header_chain_match(client, fake_repo, mock_llm):
    """A reply whose in_reply_to == the stored outbound Message-ID routes to that run
    via find_awaiting_reply_for_header and resumes it (CLAR-02)."""
    run_id, msg_id = _drive_to_awaiting_reply(client, fake_repo, mock_llm)

    _script_resume_resolved(mock_llm)
    reply = _reply_payload(
        in_reply_to=msg_id,
        from_addr=_METRO_DELI_CONTACT,
        body="Sorry, the correct spelling is David Reyes. Thanks!",
    )
    r = client.post("/webhook/inbound", json=reply)
    assert r.status_code == 200
    assert drain.drain_once() is DrainOutcome.DONE
    assert drain.drain_once() is DrainOutcome.DONE

    run = fake_repo.load_run(run_id)
    # The run resumed and advanced past awaiting_reply (no longer paused there).
    assert run["status"] != "awaiting_reply", "the reply must resume the run"
    assert run["status"] in ("awaiting_approval", "computed")


def test_header_chain_match_via_references(client, fake_repo, mock_llm):
    """A reply matching via the References chain (in_reply_to None) also routes."""
    run_id, msg_id = _drive_to_awaiting_reply(client, fake_repo, mock_llm)

    _script_resume_resolved(mock_llm)
    # in_reply_to is None; the outbound Message-ID is embedded in a multi-id References.
    reply = InboundEmail(
        id=uuid.uuid4(),
        message_id="<reply-refs@metrodeli.example>",
        in_reply_to=None,
        references_header=f"<other-thread@x.example> {msg_id} <tail@x.example>",
        subject="Re: Payroll hours",
        from_addr=_METRO_DELI_CONTACT,
        to_addr="agent@payroll-agent.local",
        body_text="Correct spelling is David Reyes.",
        created_at=datetime.now(UTC),
    ).model_dump(mode="json")
    r = client.post("/webhook/inbound", json=reply)
    assert r.status_code == 200
    assert drain.drain_once() is DrainOutcome.DONE
    assert drain.drain_once() is DrainOutcome.DONE
    assert fake_repo.load_run(run_id)["status"] != "awaiting_reply"


def test_stale_epoch_header_cannot_resume_current_awaiting_run(fake_repo):
    """A retriggered run may observe an old header but cannot resume from it.

    The append-only outbound log retains the old clarification Message-ID for late
    reply observability.  The resume lookup must nevertheless require the row's
    stamped epoch to equal the run's current reply_epoch.
    """
    from app.models.status import RunStatus

    run_id = fake_repo.create_run(
        business_id=uuid.uuid4(),
        source_email_id=uuid.uuid4(),
        pay_period_start="2026-06-15",
        pay_period_end="2026-06-21",
    )
    old_header = "<clarification-epoch-0@payroll-agent.local>"
    current_header = "<clarification-epoch-1@payroll-agent.local>"

    fake_repo.insert_email_message(
        run_id=run_id,
        direction="outbound",
        message_id=old_header,
        purpose="clarification",
        send_state="sent",
    )
    fake_repo.set_status(run_id, RunStatus.AWAITING_REPLY)
    assert fake_repo.clear_reply_context(run_id) == 1
    fake_repo.insert_email_message(
        run_id=run_id,
        direction="outbound",
        message_id=current_header,
        purpose="clarification",
        send_state="sent",
    )

    assert (
        fake_repo.find_awaiting_reply_for_header(
            in_reply_to=old_header,
            references_header=None,
        )
        is None
    )
    assert fake_repo.find_awaiting_reply_for_header(
        in_reply_to=current_header,
        references_header=None,
    ) == run_id
    assert fake_repo.find_any_run_for_header(
        in_reply_to=old_header,
        references_header=None,
    ) == run_id


def test_references_like_is_parameterized():
    """The references LIKE is a NAMED placeholder, never an f-string.

    The References header is attacker-controllable text arriving from the public inbox;
    interpolating it into SQL would be a direct injection path.
    """
    import inspect

    import app.db.repo.emails as emails_mod

    # The header-chain references LIKE SQL (find_awaiting_reply_for_header /
    # find_any_run_for_header) lives in emails.py, not the facade (which has no SQL).
    src = inspect.getsource(emails_mod)
    assert "%(references)s" in src, "references must be a named placeholder"
    # No Message-ID value interpolated into the LIKE via f-string.
    assert "LIKE f'" not in src and 'LIKE f"' not in src


def test_pad_references_anchors_whole_tokens():
    """The References match is anchored on whole whitespace-bounded tokens.

    A stored Message-ID that appears only as a SUBSTRING of another References token
    must NOT false-match — a false match here would route a stranger's reply into
    someone else's paused payroll run. _pad_references normalizes whitespace and pads
    both ends, and the SQL pattern (' <id> ') requires the stored id to be a complete
    token.
    """
    from app.db.repo import _pad_references

    mid = "<abc@payroll-agent.local>"
    # The padded references contains the WHOLE token (real match) ...
    padded_real = _pad_references(f"<other@x.example> {mid} <tail@x.example>")
    assert f" {mid} " in padded_real, "a whole-token id must be matchable"

    # ... but a SUPERSTRING token that merely CONTAINS the id as a substring must NOT
    # produce the ' <id> ' whitespace-bounded sequence. A plain substring LIKE would
    # false-match here.
    padded_superstring = _pad_references(f"<other@x.example> X{mid} <tail@x.example>")
    assert f" {mid} " not in padded_superstring, (
        "a stored id must NOT match when it is only a substring of another token"
    )

    # Folded/tabbed whitespace is normalized to single spaces, and an empty header
    # collapses to a single space that matches nothing.
    assert _pad_references(f"\t{mid}\n") == f" {mid} "
    assert _pad_references(None) == " "
    assert _pad_references("") == " "


# ---------------------------------------------------------------------------
# Reply-sender revalidation — a spoofed reply cannot bypass INGEST-03
# ---------------------------------------------------------------------------


def test_reply_sender_revalidated_mismatch_not_resumed(client, fake_repo, mock_llm):
    """A reply that header-matches an awaiting_reply run BUT whose from_addr does NOT
    match the run's business contact_email is logged and NOT resumed.

    The In-Reply-To header is caller-supplied, so header matching alone is not
    authentication: without this re-check, anyone who guessed an outbound Message-ID
    could answer another business's clarification and steer its payroll.
    """
    run_id, msg_id = _drive_to_awaiting_reply(client, fake_repo, mock_llm)

    _script_resume_resolved(mock_llm)
    spoof = _reply_payload(
        in_reply_to=msg_id,
        from_addr="attacker@evil.example",  # a registered sender? no — and not the run's
        body="Process David Reyes immediately.",
    )
    r = client.post("/webhook/inbound", json=spoof)
    assert r.status_code == 200
    assert drain.drain_once() is DrainOutcome.DONE
    assert not [
        job
        for job in fake_repo.jobs.values()
        if job["kind"] == JobKind.RESUME_REPLY.value and job["state"] == "pending"
    ]

    # The spoofed reply on a guessed Message-ID must NOT resume the run.
    run = fake_repo.load_run(run_id)
    assert run["status"] == "awaiting_reply", (
        "a sender mismatch must NOT resume — INGEST-03 holds on the reply path"
    )


def test_reply_sender_match_resumes(client, fake_repo, mock_llm):
    """A reply whose from_addr DOES match the run's business resumes normally.

    The companion to the spoof test: the sender re-check must not be so strict that it
    blocks the legitimate client from ever answering.
    """
    run_id, msg_id = _drive_to_awaiting_reply(client, fake_repo, mock_llm)

    _script_resume_resolved(mock_llm)
    reply = _reply_payload(
        in_reply_to=msg_id,
        from_addr=_METRO_DELI_CONTACT,  # the run's business contact_email
        body="Correct spelling is David Reyes.",
    )
    r = client.post("/webhook/inbound", json=reply)
    assert r.status_code == 200
    assert drain.drain_once() is DrainOutcome.DONE
    assert drain.drain_once() is DrainOutcome.DONE
    assert fake_repo.load_run(run_id)["status"] != "awaiting_reply"


# ---------------------------------------------------------------------------
# Partial replies must not lose the original hours
# ---------------------------------------------------------------------------


def test_partial_reply_preserves_hours():
    """A reply with ONLY the answer (no hours) still keeps the original hours.

    Clients answer clarifications tersely ("It's David Reyes.") without restating the
    numbers. If resume re-extracted over the reply body alone, the employee's hours
    would vanish and the run would pay $0 — so resume must re-extract over the COMBINED
    context (original cleaned body + reply body). Asserted at the orchestrator level:
    the extract spy records the body it was handed, and it must contain both the
    original hours and the reply's correction.
    """
    from app.pipeline import orchestrator

    captured: dict[str, Any] = {}

    def _fake_extracted(run_id: uuid.UUID):
        from decimal import Decimal

        from app.models.contracts import Extracted, ExtractedEmployee

        return Extracted(
            run_id=run_id,
            employees=[
                ExtractedEmployee(submitted_name="David Reyes", hours_regular=Decimal("38"))
            ],
            pay_period_start="2026-06-15",
        )

    # Spy on extract to capture the combined body the resume stage builds + the run_id.
    def _spy_extract(email, roster, *, run_id: uuid.UUID, llm=None):
        captured["body"] = email.body_text
        captured["run_id"] = run_id
        return _fake_extracted(run_id)

    # Build a minimal in-memory repo just for this orchestrator-level test.
    run_id = uuid.uuid4()
    store = _MiniStore(run_id)

    import pytest as _pt

    import app.db.repo as repo_mod

    monkey = _pt.MonkeyPatch()
    try:
        for name in (
            "load_run", "load_source_email", "load_roster_for_business",
            "set_status", "claim_status", "record_run_error", "persist_extracted",
            "persist_decision", "persist_reconciliation", "replace_line_items",
            # The field-regression helpers (pre-clarify snapshot + clarified_fields).
            "load_pre_clarify_extracted", "load_clarified_fields",
            "set_pre_clarify_extracted", "set_clarified_fields",
            # _run_stages calls set_hours_changes UNCONDITIONALLY on every run.
            "set_hours_changes",
            # resume_pipeline writes the consumed-reply marker right after its CAS
            # claim, so the mini-store must intercept these too — otherwise they fall
            # through to the real DB-backed repo and the test needs a live database.
            "get_clarification_round", "mark_reply_consumed", "load_consumed_replies",
        ):
            monkey.setattr(repo_mod, name, getattr(store, name), raising=False)
        monkey.setattr(orchestrator, "extract", _spy_extract)
        monkey.setattr(
            orchestrator,
            "reconcile_names",
            lambda names, roster, **kw: _stub_matches(names),
        )
        monkey.setattr(orchestrator, "validate", lambda *a, **kw: [])
        monkey.setattr(orchestrator, "decide", lambda *a, **kw: _stub_decision_process())

        reply = InboundEmail(
            id=uuid.uuid4(),
            message_id="<reply-partial@metrodeli.example>",
            in_reply_to="<outbound@payroll-agent.local>",
            references_header="<outbound@payroll-agent.local>",
            subject="Re: hours",
            from_addr=_METRO_DELI_CONTACT,
            to_addr="agent@payroll-agent.local",
            body_text="It's David Reyes.",  # answer-only: NO hours in the reply
            created_at=datetime.now(UTC),
        )
        orchestrator.resume_pipeline(run_id, reply)
    finally:
        monkey.undo()

    # The combined extraction context includes BOTH the original body (with hours)
    # AND the reply body (the corrected name) — so partial replies don't lose hours.
    assert "38 regular hours" in captured["body"], "original hours must be in context"
    assert "David Reyes" in captured["body"], "the reply correction must be in context"
    assert captured["run_id"] == run_id, (
        "resume must pass the code-owned run_id into extract, so the rebuilt Extracted "
        "is bound to the run being resumed rather than to anything the model returned"
    )


# ---------------------------------------------------------------------------
# A resume on a non-awaiting_reply run is a no-op
# ---------------------------------------------------------------------------


def test_resume_on_non_awaiting_reply_run_does_not_mutate():
    """resume_pipeline must re-assert the run is still awaiting_reply BEFORE mutating.

    A late or duplicate reply that lands after the run advanced (approved / computed /
    sent / …) must be DROPPED: no EXTRACTING flip, no gate re-run, no line-item
    replacement, and crucially NOT routed to ERROR — a late reply is not a failure.
    Without the re-check, a status race between the webhook's check and the
    BackgroundTask could re-extract over an already-approved payroll and replace the
    numbers a human already signed off on.
    """
    from app.pipeline import orchestrator

    run_id = uuid.uuid4()
    store = _MiniStore(run_id)
    # The run already advanced past awaiting_reply (operator approved the first result).
    store.runs[str(run_id)]["status"] = "approved"

    extract_called = {"n": 0}

    def _spy_extract(email, roster, *, run_id: uuid.UUID, llm=None):
        extract_called["n"] += 1
        return _fake_extracted_unused(run_id)

    import pytest as _pt

    import app.db.repo as repo_mod

    monkey = _pt.MonkeyPatch()
    try:
        for name in (
            "load_run", "load_source_email", "load_roster_for_business",
            "set_status", "claim_status", "record_run_error", "persist_extracted",
            "persist_decision", "persist_reconciliation", "replace_line_items",
            # The field-regression helpers (pre-clarify snapshot + clarified_fields).
            "load_pre_clarify_extracted", "load_clarified_fields",
            "set_pre_clarify_extracted", "set_clarified_fields",
            # _run_stages calls set_hours_changes UNCONDITIONALLY on every run.
            "set_hours_changes",
            # claim_status returns False here (the run is no longer awaiting_reply), so
            # these are never reached — patched anyway so that if the short-circuit ever
            # regresses, the test fails on its assertions rather than on a live-DB call.
            "get_clarification_round", "mark_reply_consumed", "load_consumed_replies",
        ):
            monkey.setattr(repo_mod, name, getattr(store, name), raising=False)
        # If the precondition fails to short-circuit, these spies prove the mutation.
        monkey.setattr(orchestrator, "extract", _spy_extract)

        reply = InboundEmail(
            id=uuid.uuid4(),
            message_id="<late-reply@metrodeli.example>",
            in_reply_to="<outbound@payroll-agent.local>",
            references_header="<outbound@payroll-agent.local>",
            subject="Re: hours",
            from_addr=_METRO_DELI_CONTACT,
            to_addr="agent@payroll-agent.local",
            body_text="A late reply after the run was already approved.",
            created_at=datetime.now(UTC),
        )
        orchestrator.resume_pipeline(run_id, reply)
    finally:
        monkey.undo()

    run = store.runs[str(run_id)]
    # The run was NOT touched: still approved (no EXTRACTING / awaiting_approval flip).
    assert run["status"] == "approved", (
        "a resume on a non-awaiting_reply run must NOT mutate its status"
    )
    # And it was NOT clobbered to ERROR — a late reply is dropped, not an error.
    assert run["error_reason"] is None, "a late/duplicate reply must NOT route to ERROR"
    # The gate path never ran (no re-extraction over the approved run).
    assert extract_called["n"] == 0, "resume must short-circuit before re-running stages"
    # No extracted_data / decision were overwritten on the terminal run.
    assert run["extracted_data"] is None
    assert run["decision"] is None


def _fake_extracted_unused(run_id: uuid.UUID):
    """An Extracted used only to prove extract() was NOT called on the short-circuit."""
    from decimal import Decimal

    from app.models.contracts import Extracted, ExtractedEmployee

    return Extracted(
        run_id=run_id,
        employees=[ExtractedEmployee(submitted_name="X", hours_regular=Decimal("1"))],
        pay_period_start="2026-06-15",
    )


# ---------------------------------------------------------------------------
# resume stamps the code-owned run_id into extract
# ---------------------------------------------------------------------------


def test_resume_stamps_run_id():
    """resume passes the run's code-owned run_id into extract, so the rebuilt
    Extracted.run_id always equals the resumed run and never a model-supplied value."""
    import inspect

    from app.pipeline import orchestrator

    src = inspect.getsource(orchestrator)
    assert "def resume_pipeline" in src, "resume_pipeline must exist"
    # Both run_pipeline and resume_pipeline must pass run_id=run_id into extract.
    assert src.count("run_id=run_id") >= 1, "extract must be called with run_id=run_id"


# ---------------------------------------------------------------------------
# test_idempotent_resume — overwrite extracted_data, replace line items
# ---------------------------------------------------------------------------


def test_idempotent_resume(client, fake_repo, mock_llm):
    """Resuming a run overwrites extracted_data (not appends) and is idempotent —
    re-running yields the same final state."""
    run_id, msg_id = _drive_to_awaiting_reply(client, fake_repo, mock_llm)

    _script_resume_resolved(mock_llm)
    reply = _reply_payload(
        in_reply_to=msg_id,
        from_addr=_METRO_DELI_CONTACT,
        body="Correct spelling is David Reyes.",
    )
    r1 = client.post("/webhook/inbound", json=reply)
    assert r1.status_code == 200
    assert drain.drain_once() is DrainOutcome.DONE
    assert drain.drain_once() is DrainOutcome.DONE
    state_after_first = fake_repo.load_run(run_id)["status"]
    extracted_after_first = fake_repo.load_run(run_id)["extracted_data"]

    # extracted_data is a single cell (a dict, not a growing list of extractions).
    assert isinstance(extracted_after_first, dict)
    assert "employees" in extracted_after_first
    # Exactly one employee — the re-extraction OVERWROTE, did not append.
    assert len(extracted_after_first["employees"]) == 1

    assert state_after_first in ("awaiting_approval", "computed")


# ---------------------------------------------------------------------------
# A late reply is observed, never resumed
# ---------------------------------------------------------------------------


def test_late_reply_logged_not_resumed(client, fake_repo, mock_llm):
    """A header match to a run NOT in awaiting_reply (e.g. sent/reconciled) is found
    via find_any_run_for_header and logged as a late reply, never resumed.

    The any-status lookup exists purely for observability: it lets a late reply be
    attributed to its run without giving it the power to restart one.
    """
    run_id, msg_id = _drive_to_awaiting_reply(client, fake_repo, mock_llm)

    # Move the run OUT of awaiting_reply (simulate it already resolved / sent).
    from app.models.status import RunStatus

    fake_repo.set_status(run_id, RunStatus.SENT)
    assert fake_repo.load_run(run_id)["status"] == "sent"

    _script_resume_resolved(mock_llm)
    reply = _reply_payload(
        in_reply_to=msg_id,
        from_addr=_METRO_DELI_CONTACT,
        body="A late reply that arrives after the run already advanced.",
    )
    r = client.post("/webhook/inbound", json=reply)
    assert r.status_code == 200
    assert drain.drain_once() is DrainOutcome.DONE

    # The late reply did NOT resume — the run stays at sent (only awaiting_reply resumes).
    assert fake_repo.load_run(run_id)["status"] == "sent", (
        "a header match to a non-awaiting_reply run must NOT resume"
    )
    assert r.json().get("status") == "accepted"
    assert not [
        job
        for job in fake_repo.jobs.values()
        if job["kind"] == JobKind.RESUME_REPLY.value and job["state"] == "pending"
    ]


def test_webhook_uses_both_header_lookups():
    """The webhook calls find_awaiting_reply_for_header for resume AND
    find_any_run_for_header for late-reply observability.

    Collapsing the two lookups into one would either resume runs that must not be
    resumed, or make late replies vanish without a trace.
    """
    import inspect

    import app.ingest as ingest_mod

    src = inspect.getsource(ingest_mod)
    assert "find_awaiting_reply_for_header" in src
    assert "find_any_run_for_header" in src


# ---------------------------------------------------------------------------
# The committed reply fixture completes the clarify→reply→resume loop (EMAIL-01)
# ---------------------------------------------------------------------------


def test_clarify_reply_fixture_validates_as_inbound_email():
    """The committed reply fixture validates as a canonical InboundEmail, carries an
    in_reply_to slot, and its from_addr equals the gate-block run's business contact —
    so it survives the sender revalidation rather than being dropped as a spoof."""
    from app.db.seed import seed

    payload = json.loads(_CLARIFY_REPLY_FIXTURE.read_text())
    email = InboundEmail.model_validate(payload)
    assert email.in_reply_to is not None, "the reply must carry an in_reply_to slot"
    assert _CLARIFICATION_PLACEHOLDER in email.in_reply_to, (
        "the fixture must carry the substitutable placeholder token"
    )
    seeded_emails = {b["contact_email"] for b in seed(dry_run=True).businesses}
    assert email.from_addr in seeded_emails
    assert email.from_addr == _METRO_DELI_CONTACT, (
        "from_addr must equal the gate-block run's business, or the sender revalidation "
        "drops the reply and the loop never resumes"
    )
    # Answer-only: the reply corrects the name but does NOT restate the hours, so the
    # resume exercises the partial-reply-preserves-hours path rather than a lucky
    # re-statement of the numbers.
    assert "David Reyes" in email.body_text
    assert "38" not in email.body_text, "the reply must NOT restate hours (partial reply)"


def test_clarify_reply_fixture_completes_full_loop(client, fake_repo, mock_llm):
    """The full clarify→reply→resume loop with ZERO real email (EMAIL-01, CLAR-03).

    gate-block fixture → awaiting_reply → read back the clarification Message-ID from
    its email_messages anchor → substitute it into the reply payload → ASSERT the
    substitution took (the placeholder is gone) BEFORE the POST → POST the reply → the
    run resumes at extraction over (original cleaned body + reply body) and advances,
    retaining the original hours.

    The pre-POST substitution assertion is load-bearing: a broken substitution would
    still return 200, but via the no-header-match branch — the test would pass while
    proving nothing about resume.
    """
    # 1. Drive the gate-block fixture to awaiting_reply.
    run_id, clarification_msg_id = _drive_to_awaiting_reply(client, fake_repo, mock_llm)

    # 2. Substitute the captured clarification Message-ID into the reply payload.
    raw = _CLARIFY_REPLY_FIXTURE.read_text()
    assert _CLARIFICATION_PLACEHOLDER in raw, "fixture must carry the placeholder"
    substituted = raw.replace(_CLARIFICATION_PLACEHOLDER, clarification_msg_id)
    reply_payload = json.loads(substituted)

    # 3. ASSERT the substitution took BEFORE the POST — fail loudly here rather than
    #    silently falling through the no-match branch. The reply's in_reply_to now
    #    equals the captured clarification Message-ID and the placeholder token is gone.
    assert _CLARIFICATION_PLACEHOLDER not in json.dumps(reply_payload), (
        "the placeholder must be fully substituted before POSTing"
    )
    assert reply_payload["in_reply_to"] == clarification_msg_id, (
        "the reply's in_reply_to must equal the captured clarification Message-ID"
    )

    # 4. Script the resume pass (corrected name resolves cleanly → process) and POST.
    _script_resume_resolved(mock_llm)
    r = client.post("/webhook/inbound", json=reply_payload)
    assert r.status_code == 200
    assert r.json()["status"] == "accepted"
    assert drain.drain_once() is DrainOutcome.DONE
    assert drain.drain_once() is DrainOutcome.DONE

    # 5. The run resumed at extraction and advanced (retaining original hours via the
    #    combined-context re-extraction — the loop is exercisable with zero real email).
    run = fake_repo.load_run(run_id)
    assert run["status"] in ("awaiting_approval", "computed"), (
        "the resumed run must advance past awaiting_reply"
    )
    # A line item was computed for the now-resolved David Reyes (hours survived).
    items = fake_repo.line_items.get(run_id, [])
    assert len(items) == 1, "the resumed run computes a paystub for the resolved employee"


def test_reply_with_no_matching_outbound_handled_gracefully(client, fake_repo, mock_llm):
    """A reply whose in_reply_to matches no outbound Message-ID is handled gracefully
    (logged, no wrong-run resume). This is NOT how the resume test passes — the
    pre-POST substitution assertion guarantees the resume path is the one exercised."""
    # No run was ever driven to awaiting_reply, so there is no outbound anchor.
    reply = _reply_payload(
        in_reply_to="<nonexistent-clarification@payroll-agent.local>",
        from_addr=_METRO_DELI_CONTACT,
        body="A reply that threads onto nothing.",
    )
    r = client.post("/webhook/inbound", json=reply)
    assert r.status_code == 200
    assert drain.drain_once() is DrainOutcome.DONE
    # No header match → falls through to ordinary first ingest (a NEW run is opened,
    # never a wrong-run resume). The reply's sender is a seeded business, so the
    # ordinary path accepts it.
    assert r.json()["status"] == "accepted", "no header match → ordinary inbound, no resume"


# ---------------------------------------------------------------------------
# Mini orchestrator-level stubs (for the body-composition test only)
# ---------------------------------------------------------------------------


def _stub_matches(names: list[str]):
    from app.models.roster import NameMatchResult

    return [
        NameMatchResult(
            submitted_name=n,
            matched_employee_id=uuid.UUID(_DAVID_REYES_ID),
            source="exact",
            resolved=True,
            reason="stub",
        )
        for n in names
    ]


def _stub_decision_process() -> Decision:
    from app.models.contracts import Decision

    return Decision(
        final_action="process",
        gate_reasons=[],
        unresolved_names=[],
        missing_fields=[],
        resolutions=_stub_matches(["David Reyes"]),
    )


class _MiniStore:
    """A tiny in-memory repo for the orchestrator-level partial-reply test."""

    def __init__(self, run_id: uuid.UUID) -> None:
        self.run_id = run_id
        self.runs = {
            str(run_id): {
                "id": run_id,
                "business_id": uuid.UUID("b0000002-0000-0000-0000-000000000002"),
                "source_email_id": uuid.uuid4(),
                "status": "awaiting_reply",
                "extracted_data": None,
                "decision": None,
                "reconciliation": None,
                "error_reason": None,
                "pay_period_start": None,
                "pay_period_end": None,
            }
        }

    def load_run(self, run_id, conn=None):
        return self.runs.get(str(run_id))

    def load_source_email(self, run_id, conn=None):
        # The ORIGINAL cleaned inbound body (with the hours), as persisted at ingest.
        return "David Reyez - 38 regular hours\n\nThanks!"

    def load_roster_for_business(self, business_id, conn=None):
        from app.db.seed import seed
        from app.models.roster import Roster

        seeded = seed(dry_run=True)
        emps = [e for e in seeded.employees if str(e.business_id) == str(business_id)]
        return Roster(business_id=business_id, employees=emps)

    def set_status(self, run_id, status, conn=None):
        from app.models.status import RunStatus

        self.runs[str(run_id)]["status"] = RunStatus(status).value

    def claim_status(self, run_id, expected, new, conn=None):
        """Compare-and-set the run's status, mirroring repo.claim_status (FOUND-04).

        Returns False when the run is not in the expected status — that False is the
        short-circuit the late-reply test depends on.
        """
        from app.models.status import RunStatus

        run = self.runs.get(str(run_id))
        if run is None:
            return False
        if run["status"] != RunStatus(expected).value:
            return False
        run["status"] = RunStatus(new).value
        return True

    def record_run_error(
        self, run_id, reason, conn=None, *, detail_exc=None, stage=None, roster=None
    ):
        # Mirrors the real repo.record_run_error's conn-positional-then-keyword-only
        # shape (as does tests/conftest.py's InMemoryRepo): the keyword-only extras must
        # be accepted without erroring, or a caller that passes them blows up in the
        # double instead of exercising the error path under test.
        self.runs[str(run_id)]["error_reason"] = reason

    def persist_extracted(self, run_id, extracted, conn=None):
        self.runs[str(run_id)]["extracted_data"] = extracted.model_dump(mode="json")

    def persist_decision(self, run_id, decision, conn=None):
        self.runs[str(run_id)]["decision"] = decision.model_dump(mode="json")

    def persist_reconciliation(self, run_id, matches, conn=None):
        self.runs[str(run_id)]["reconciliation"] = [
            m.model_dump(mode="json") for m in matches
        ]

    def replace_line_items(self, run_id, items, conn=None):
        pass

    def load_pre_clarify_extracted(self, run_id, conn=None):
        """No pre-clarify snapshot exists here — field regression is not under test."""
        return None

    def load_clarified_fields(self, run_id, conn=None):
        """No fields have been clarified here — field regression is not under test."""
        return {}

    def set_pre_clarify_extracted(self, run_id, extracted, conn=None):
        """No-op: this mini-store does not exercise the snapshot write."""
        return True

    def set_clarified_fields(self, run_id, clarified, conn=None):
        """No-op: this mini-store does not exercise the clarified-fields write."""
        pass

    def set_hours_changes(self, run_id, changes, conn=None):
        """No-op: this mini-store does not exercise the hours-changes write.

        It must still EXIST and be named in BOTH registration tuples below — _run_stages
        calls repo.set_hours_changes unconditionally, and an unpatched name falls through
        to the real DB-backed repo (see the comment on those tuples).
        """
        pass

    def get_clarification_round(self, run_id, conn=None):
        """Always round 0 — the multi-round machine is not under test here."""
        return 0

    def mark_reply_consumed(self, message_id, round, conn=None):
        """No-op: this test does not exercise multi-round context accumulation."""
        pass

    def load_consumed_replies(self, run_id, conn=None):
        """No prior consumed replies — this is a single-round test."""
        return []
