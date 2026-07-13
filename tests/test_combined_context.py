"""Combined-context accumulation tests for the multi-round clarification path.

WHY THIS LIVES IN ITS OWN MODULE (NOT tests/test_resume_pipeline.py):
tests/test_resume_pipeline.py carries a MODULE-LEVEL conditional-skip marker
gated on `os.environ.get("DATABASE_URL")` being unset (see
tests/test_multiround_context_edge.py's docstring for the verified detail).
That marker silently skips the ENTIRE module offline. This module is genuinely
hermetic (pure-function assertions + fake_repo/mock_llm only, no live DB/LLM)
and must run unconditionally offline, so it has NO module-level conditional-
skip marker of any kind. Do not merge this file into test_resume_pipeline.py.

WHAT THIS MODULE PROVES:
  1. _combined_context_email's "QUESTIONS WE ASKED:" anchor is code-owned,
     positioned after ORIGINAL and before the replies, string-for-string
     testable.
  2. An empty asked_summary_lines emits NO anchor header at all.
  3. prior_replies accumulate in round order under distinct round-numbered
     delimiters, with the current reply labelled distinctly.
  4. The function is pure: no DB I/O, and the passed-in reply object's
     body_text is never mutated (model_copy, not mutation).
  5. _render_asked_summary derives its lines ONLY from persisted decision
     facts (unresolved_names + clarified_fields 'asked' entries) -- there is
     no LLM-draft parameter, so this is pinned by construction.
  6. The deterministic re-ask backstop: an asked field that stays absent
     after extraction re-gates to a NEW clarification round that actually
     SENDS -- never a silent park, never a guessed paystub.
  7. The consumed-marker-drives-accumulation assertion against REAL rows:
     resume_pipeline's own mark_reply_consumed call (Task 1) is what makes a
     SECOND resume's load_consumed_replies return the first reply -- this
     test does NOT pre-seed consumed_round by hand, so it fails if that seam
     is ever removed.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from typing import Any

from app.models.contracts import Decision, Extracted, ExtractedEmployee, InboundEmail
from app.models.roster import NameMatchResult
from app.models.status import RunStatus
from app.pipeline.clarification import (
    combined_context_email as _combined_context_email,
)
from app.pipeline.clarification import (
    render_asked_summary as _render_asked_summary,
)
from app.pipeline.orchestrator import resume_pipeline

# ---------------------------------------------------------------------------
# Stable identifiers (mirrors tests/test_resume_pipeline.py / test_multiround_
# context_edge.py's seed.py constants — Business 1 / Coastal Cleaning Co. /
# Maria Chen).
# ---------------------------------------------------------------------------
COASTAL_BIZ_ID = uuid.UUID("b0000001-0000-0000-0000-000000000001")
COASTAL_EMAIL = "payroll@coastalcleaning.example"
CHEN_ID = uuid.UUID("e0000001-0000-0000-0000-000000000001")
CHEN_ID_STR = str(CHEN_ID)


# ---------------------------------------------------------------------------
# 1-4: Pure-function tests for _combined_context_email (no DB, no fixtures).
# ---------------------------------------------------------------------------


def _mk_reply(body_text: str, message_id: str | None = None) -> InboundEmail:
    return InboundEmail(
        id=uuid.uuid4(),
        message_id=message_id or f"<reply-{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="Re: payroll hours",
        from_addr="payroll@example.com",
        to_addr="agent@payroll-agent.local",
        body_text=body_text,
        created_at=datetime.now(UTC),
    )


def test_anchor_present_after_original_before_replies():
    """A non-empty asked_summary_lines renders a "QUESTIONS WE ASKED:" section
    containing each line verbatim, positioned AFTER original and BEFORE the
    replies."""
    reply = _mk_reply("current reply body")
    result = _combined_context_email(
        reply,
        "ORIGINAL BODY TEXT",
        asked_summary_lines=["Amina Yusuf: hours are missing"],
        prior_replies=[],
    )
    body = result.body_text
    assert "QUESTIONS WE ASKED:" in body
    assert "Amina Yusuf: hours are missing" in body
    idx_original = body.index("ORIGINAL BODY TEXT")
    idx_anchor = body.index("QUESTIONS WE ASKED:")
    idx_current_reply = body.index("current reply body")
    assert idx_original < idx_anchor < idx_current_reply, (
        "the asked anchor must sit after the original body and before the "
        "reply sections"
    )


def test_no_anchor_when_asked_summary_lines_empty():
    """Empty asked_summary_lines emits NO "QUESTIONS WE ASKED:" header at all —
    an anchor with no content would be noise, not signal."""
    reply = _mk_reply("current reply body")
    result = _combined_context_email(
        reply, "ORIGINAL BODY TEXT", asked_summary_lines=[], prior_replies=[]
    )
    assert "QUESTIONS WE ASKED:" not in result.body_text


def test_accumulation_orders_prior_replies_before_current():
    """prior_replies=[r1, r2] + current r3 accumulate in order under distinct
    round-numbered delimiters, with the current reply labelled distinctly from
    the prior ones."""
    reply = _mk_reply("r3 body")
    result = _combined_context_email(
        reply,
        "ORIGINAL BODY TEXT",
        asked_summary_lines=[],
        prior_replies=["r1 body", "r2 body"],
    )
    body = result.body_text
    idx_r1 = body.index("r1 body")
    idx_r2 = body.index("r2 body")
    idx_r3 = body.index("r3 body")
    assert idx_r1 < idx_r2 < idx_r3, "replies must accumulate in round order"
    assert "CLARIFICATION REPLY 1 FROM CLIENT:" in body
    assert "CLARIFICATION REPLY 2 FROM CLIENT:" in body
    assert "CLARIFICATION REPLY 3 FROM CLIENT (CURRENT):" in body, (
        "the current reply must be labelled distinctly from the prior replies"
    )


def test_combined_context_email_is_pure_no_mutation():
    """_combined_context_email performs no DB I/O and returns
    reply.model_copy(update=...) — the original reply object's body_text is
    never mutated."""
    reply = _mk_reply("original current body")
    original_before = reply.body_text
    result = _combined_context_email(
        reply,
        "ORIGINAL BODY TEXT",
        asked_summary_lines=["some question"],
        prior_replies=["some prior reply"],
    )
    assert reply.body_text == original_before, "the input reply must not be mutated"
    assert result is not reply, "the function must return a NEW object (model_copy)"
    assert result.body_text != original_before, (
        "the RETURNED object must carry the combined body"
    )


# ---------------------------------------------------------------------------
# 5: _render_asked_summary sources ONLY persisted decision facts — no draft
# parameter exists, pinning the no-LLM rule by construction.
# ---------------------------------------------------------------------------


def test_render_asked_summary_sources_only_persisted_facts():
    """_render_asked_summary(decision, clarified_fields) has no LLM-draft
    parameter at all — its signature by construction cannot read a
    model-drafted body. Assert its lines derive exactly from
    decision.unresolved_names + clarified_fields entries currently 'asked',
    and that a terminal outcome (already resolved) does NOT appear."""
    decision = Decision(
        final_action="request_clarification",
        gate_reasons=["unresolved name"],
        unresolved_names=["Amina Yusuf"],
        missing_fields=[],
        resolutions=[],
    )
    clarified_fields = {
        CHEN_ID_STR: {
            "hours_overtime": "asked",
            "hours_regular": "client_supplied",  # terminal — must NOT appear
        }
    }
    lines = _render_asked_summary(decision, clarified_fields)
    assert any("Amina Yusuf" in line for line in lines), (
        "unresolved_names must be represented in the asked summary"
    )
    assert any(CHEN_ID_STR in line and "hours_overtime" in line for line in lines), (
        "a currently-'asked' clarified_fields entry must be represented"
    )
    assert not any("hours_regular" in line for line in lines), (
        "a TERMINAL outcome (client_supplied) must not appear as if still asked"
    )


def test_render_asked_summary_handles_none_decision():
    """A None decision (first-ever resume, no persisted Decision yet) must not
    raise — treated as 'no unresolved names'."""
    lines = _render_asked_summary(None, {})
    assert lines == []


# ---------------------------------------------------------------------------
# Helpers for the hermetic resume_pipeline-driving tests below (copied, not
# imported, from tests/test_multiround_context_edge.py per that module's own
# stated rationale: this module must stay import-independent of any module
# that could someday grow a skip guard).
# ---------------------------------------------------------------------------


def _mk_extracted(
    employees_data: list[dict[str, Any]],
    pay_period_start: str = "2026-06-15",
    run_id: uuid.UUID | None = None,
) -> Extracted:
    if run_id is None:
        run_id = uuid.uuid4()
    return Extracted(
        run_id=run_id,
        employees=[ExtractedEmployee(**e) for e in employees_data],
        pay_period_start=date.fromisoformat(pay_period_start),
        pay_period_end=None,
    )


def _mk_match(name: str, emp_id: uuid.UUID, resolved: bool = True) -> NameMatchResult:
    return NameMatchResult(
        submitted_name=name,
        matched_employee_id=emp_id if resolved else None,
        source="exact" if resolved else "none",
        resolved=resolved,
        reason="exact match" if resolved else "no roster match",
    )


def _seed_run(fake_repo, *, body: str, from_addr: str = COASTAL_EMAIL) -> uuid.UUID:
    eid, _ = fake_repo.insert_inbound_email(
        message_id=f"<{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="payroll hours",
        from_addr=from_addr,
        to_addr="agent@payroll-agent.local",
        body_text=body,
    )
    return uuid.UUID(str(fake_repo.create_run(business_id=COASTAL_BIZ_ID, source_email_id=eid)))


def _inbound(
    body: str, message_id: str | None = None, from_addr: str = COASTAL_EMAIL
) -> InboundEmail:
    return InboundEmail(
        id=uuid.uuid4(),
        message_id=message_id or f"<reply-{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="Re: payroll hours",
        from_addr=from_addr,
        to_addr="agent@payroll-agent.local",
        body_text=body,
        created_at=datetime.now(UTC),
    )


def _inbound_persisted(
    fake_repo, run_id: uuid.UUID, body: str, message_id: str, from_addr: str = COASTAL_EMAIL
) -> InboundEmail:
    """Build a reply InboundEmail AND persist its row in fake_repo, linked to
    run_id — mirrors what the real webhook does (insert_inbound_email +
    link_email_to_run) BEFORE resume_pipeline is ever called. Required for
    mark_reply_consumed/load_consumed_replies to have a real row to act on
    (InMemoryRepo.mark_reply_consumed looks up self.emails[message_id])."""
    eid, _ = fake_repo.insert_inbound_email(
        message_id=message_id,
        in_reply_to=None,
        references_header=None,
        subject="Re: payroll hours",
        from_addr=from_addr,
        to_addr="agent@payroll-agent.local",
        body_text=body,
    )
    fake_repo.link_email_to_run(eid, run_id)
    return InboundEmail(
        id=eid,
        message_id=message_id,
        in_reply_to=None,
        references_header=None,
        subject="Re: payroll hours",
        from_addr=from_addr,
        to_addr="agent@payroll-agent.local",
        body_text=body,
        created_at=datetime.now(UTC),
    )


def _extraction_json(employees: list[dict[str, Any]], pay_period_start: str = "2026-06-15") -> str:
    return json.dumps(
        {"employees": employees, "pay_period_start": pay_period_start, "pay_period_end": None}
    )


def _suggestion_json(suggestions: dict[str, str]) -> str:
    return json.dumps(
        {
            "suggestions": [
                {"submitted_name": k, "suggested_full_name": v}
                for k, v in suggestions.items()
            ]
        }
    )


def _set_run_awaiting_reply(fake_repo, run_id: uuid.UUID) -> None:
    fake_repo.runs[str(run_id)]["status"] = RunStatus.AWAITING_REPLY.value


# ---------------------------------------------------------------------------
# 6: The deterministic re-ask backstop — the real enforcement mechanism.
# An asked field that stays absent from the reply must re-gate to a NEW
# clarification that actually SENDS -- not a silent guess, not a silent park.
# ---------------------------------------------------------------------------


def test_reask_backstop_sends_new_clarification_when_asked_field_stays_absent(
    fake_repo, mock_llm
):
    """Drive resume where the reply is SILENT on the asked field (mock_llm
    returns the field absent). Assert the run re-gates to a NEW clarification
    that SENDS (gateway called, round advances) -- never a silent park and
    never a guessed paystub. This test asserts the
    deterministic SEND, never any LLM attribution behavior."""
    run_id = _seed_run(
        fake_repo, body="Maria Chen worked 40 regular hours, 2 overtime"
    )
    snapshot = _mk_extracted(
        [{"submitted_name": "Maria Chen", "hours_regular": "40", "hours_overtime": "2"}],
        run_id=run_id,
    )
    fake_repo.set_pre_clarify_extracted(run_id, snapshot)
    fake_repo.persist_reconciliation(run_id, [_mk_match("Maria Chen", CHEN_ID)])
    _set_run_awaiting_reply(fake_repo, run_id)

    # Round-1 reply drops hours_overtime (paid->unpaid, DOES trigger a
    # field_regression clarification asking specifically about hours_overtime).
    mock_llm.script = [
        _extraction_json([{"submitted_name": "Maria Chen", "hours_regular": "40"}]),
        _suggestion_json({}),
        "Could you confirm Maria Chen's overtime hours?",
    ]
    resume_pipeline(run_id, _inbound("Maria worked 40 hours this week."))

    run_after_r1 = fake_repo.load_run(run_id)
    assert run_after_r1["status"] == RunStatus.AWAITING_REPLY.value, (
        "Round 1 must ask about the dropped hours_overtime"
    )
    clarified_r1 = fake_repo.load_clarified_fields(run_id)
    assert clarified_r1.get(CHEN_ID_STR, {}).get("hours_overtime") == "asked"

    sent_before_r2 = len(fake_repo.outbound.get(str(run_id), []))

    # Round-2 reply is SILENT on the asked hours_overtime field AND silent on
    # hours_regular (a field that WAS present/paid, so its disappearance from
    # the combined extraction is a NEW field_regression — hours_regular has
    # never been asked about before, so this cannot be classified as an
    # already-terminal outcome). The deterministic backstop: hours_overtime's
    # silence classifies as carried_forward (backfilled from the snapshot,
    # never guessed), while the NEW hours_regular drop must re-gate to a
    # fresh, distinct clarification SEND — proving the run never silently
    # parks or pays a guessed value when an asked-adjacent field goes
    # unaddressed.
    mock_llm.script = [
        # classify (reply-only): Maria present, silent on everything.
        _extraction_json([{"submitted_name": "Maria Chen"}]),
        # combined (process/backfill): hours_regular now ALSO absent — a NEW
        # field_regression distinct from the already-asked hours_overtime.
        _extraction_json([{"submitted_name": "Maria Chen"}]),
    ]
    resume_pipeline(run_id, _inbound("Not sure, let me check and get back to you."))

    run_after_r2 = fake_repo.load_run(run_id)
    sent_after_r2 = len(fake_repo.outbound.get(str(run_id), []))
    clarified_r2 = fake_repo.load_clarified_fields(run_id)

    assert run_after_r2["status"] == RunStatus.AWAITING_REPLY.value, (
        "a still-unaddressed field_regression (hours_regular newly dropped, "
        "unanswered) must re-gate to AWAITING_REPLY, never silently process "
        "with a guessed value"
    )
    assert sent_after_r2 > sent_before_r2, (
        "the round-2 re-ask must actually SEND a new clarification email "
        "(gateway/outbound row count increases) -- this is the deterministic "
        "deterministic backstop, not any LLM attribution behavior"
    )
    assert clarified_r2.get(CHEN_ID_STR, {}).get("hours_overtime") == "carried_forward", (
        "silence on the asked field classifies as carried_forward (backfilled "
        "from the snapshot), never guessed onto a positive value"
    )


# ---------------------------------------------------------------------------
# 7: Consumed-marker-drives-accumulation — REAL rows, not seeded fakes.
# Do NOT pre-seed consumed_round by hand: let the real mark_reply_consumed call
# set it, so this test fails if that seam is ever removed. Seeding it by hand
# would make the test pass even with the marker logic deleted.
# ---------------------------------------------------------------------------


def test_consumed_marker_from_resume_drives_next_round_accumulation(fake_repo, mock_llm):
    """After a FIRST resume marks reply-1 consumed (via resume_pipeline's own
    mark_reply_consumed call, Task 1 — NOT hand-seeded here), a SECOND
    resume's load_consumed_replies must return reply-1, and the combined
    context handed to the second extraction call must include reply-1's
    text. This proves the marker write is the load-bearing seam: removing
    Task 1's mark_reply_consumed call makes this test fail."""
    run_id = _seed_run(
        fake_repo, body="Maria Chen worked 40 regular hours, 2 overtime"
    )
    snapshot = _mk_extracted(
        [{"submitted_name": "Maria Chen", "hours_regular": "40", "hours_overtime": "2"}],
        run_id=run_id,
    )
    fake_repo.set_pre_clarify_extracted(run_id, snapshot)
    fake_repo.persist_reconciliation(run_id, [_mk_match("Maria Chen", CHEN_ID)])
    _set_run_awaiting_reply(fake_repo, run_id)

    reply_1_body = "Maria actually worked 30, not 40 -- no overtime this week."
    reply_1 = _inbound_persisted(fake_repo, run_id, reply_1_body, message_id="<r1@test.example>")

    mock_llm.script = [
        _extraction_json([{"submitted_name": "Maria Chen", "hours_regular": "30"}]),
        _suggestion_json({}),
        "Could you confirm Maria Chen's overtime hours?",
    ]
    resume_pipeline(run_id, reply_1)

    # Assert the REAL consumed marker was set by resume_pipeline's own claim
    # (Task 1) -- this test does not touch consumed_round directly.
    consumed_after_r1 = fake_repo.load_consumed_replies(run_id)
    assert len(consumed_after_r1) == 1, (
        "resume_pipeline's own mark_reply_consumed call must have marked "
        "reply-1 consumed by now -- if this is 0, the Task 1 seam was removed"
    )
    assert consumed_after_r1[0]["message_id"] == "<r1@test.example>"

    # Capture the combined body handed to the SECOND resume's extraction call
    # via a spy on the module-level extract() the orchestrator imports. The
    # spy forwards llm UNCHANGED (never coerces None -> None as an explicit
    # kwarg override) so extract()'s own `llm=llm_client` default still
    # applies exactly as it does for the real (non-spied) call path.
    import app.pipeline.orchestrator as orch_mod

    captured_bodies: list[str] = []
    from app.pipeline.extract import extract as real_extract

    def _spy_extract(email, roster, *, run_id, llm=None):
        captured_bodies.append(email.body_text)
        kwargs = {"run_id": run_id}
        if llm is not None:
            kwargs["llm"] = llm
        return real_extract(email, roster, **kwargs)

    reply_2 = _inbound_persisted(
        fake_repo, run_id, "No overtime, confirmed.", message_id="<r2@test.example>"
    )
    mock_llm.script = [
        _extraction_json([{"submitted_name": "Maria Chen", "hours_regular": "40"}]),
        _extraction_json([{"submitted_name": "Maria Chen", "hours_regular": "40"}]),
    ]
    orch_mod.extract = _spy_extract  # type: ignore[attr-defined]  # deliberate module-attr spy swap over orchestrator's own `extract` binding, restored in finally
    try:
        resume_pipeline(run_id, reply_2)
    finally:
        orch_mod.extract = real_extract  # type: ignore[attr-defined]  # restore the original binding swapped above

    assert captured_bodies, "the second resume must call extract() at least once"
    assert any(reply_1_body in b for b in captured_bodies), (
        "reply-1's body must be present in the second resume's combined "
        "extraction context -- this is only true if load_consumed_replies "
        "returned a REAL row written by resume_pipeline's own "
        "mark_reply_consumed call (Task 1), not a hand-seeded fake"
    )
