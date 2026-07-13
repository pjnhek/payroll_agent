"""Regression guard — multi-round context preservation.

WHY THIS LIVES IN ITS OWN MODULE (NOT tests/test_resume_pipeline.py):
tests/test_resume_pipeline.py carries a MODULE-LEVEL conditional-skip marker
gated on `os.environ.get("DATABASE_URL")` being unset. That marker silently skips
the ENTIRE module — including any new test added to it — whenever DATABASE_URL is
unset at collection time. This fixture must be genuinely hermetic (fake_repo +
mock_llm only, no live DB/LLM) and run unconditionally offline, so it lives in a
module with NO module-level conditional-skip marker of any kind. A guard that
silently skips is not a guard. Do not "helpfully" merge this file back into
test_resume_pipeline.py.

WHAT THIS FIXTURE PROVES:
A genuine client correction stated in an intermediate (Round-1) clarification
reply, and never restated in a later (Round-2) reply, must still be the value that
gets PAID. If this test starts failing with hours_regular reverting to 40 (the
stale ORIGINAL) instead of 30 (the client's Round-1 correction), the run is paying
a number the client explicitly corrected — a mispay.

Why the correction is at risk of being lost — the chain, traced against live source:
  1. `clean_body` strips quoted reply history at ingest (app/email/clean.py), so
     thread quoting cannot preserve intermediate replies once the next one arrives.
     This is why round-ordered accumulation (step 3) is the mechanism, rather than
     relying on the client's quoted history.
  2. `repo.load_source_email` (app/db/repo.py) returns ONLY the ingest-time
     ORIGINAL cleaned body — it is never updated by any reply.
  3. `_combined_context_email` (app/pipeline/orchestrator.py) therefore builds the
     resume extraction context as: ORIGINAL body + a code-owned "QUESTIONS WE
     ASKED" anchor + ALL consumed replies in round order + the current reply. An
     intermediate reply from an earlier round DOES accumulate into every later
     round's context. The consumed marker, written at the resume CAS claim, is what
     makes that accumulation observable at runtime.
  4. `detect_field_regression` (app/pipeline/validate.py) only fires on a
     paid->unpaid (dropped) transition — a paid->paid VALUE CHANGE (40->30) is
     invisible to it by design. That is fine, and it is exactly why accumulation
     (not detection) is the mechanism: the corrected value simply never disappears
     from the context in the first place.
  5. Round-2's classify step only reclassifies fields marked 'asked'; but because
     Round-1's reply text is present in the combined context (step 3), the Round-2
     combined extraction reads the CORRECTED value (30), not the stale ORIGINAL (40).

The alternative design — diffing against the last-persisted extraction — was
considered and rejected in favour of accumulating the reply bodies.
"""
from __future__ import annotations

# JSON-shaped fixtures and UUIDs cross dynamic repository seams in these tests.
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.models.contracts import Extracted, ExtractedEmployee, InboundEmail
from app.models.roster import NameMatchResult
from app.models.status import RunStatus
from app.pipeline.orchestrator import resume_pipeline

# ---------------------------------------------------------------------------
# Stable identifiers (mirrors tests/test_resume_pipeline.py's seed.py constants —
# Business 1 / Coastal Cleaning Co. / Maria Chen).
# ---------------------------------------------------------------------------
COASTAL_BIZ_ID = uuid.UUID("b0000001-0000-0000-0000-000000000001")
COASTAL_EMAIL = "payroll@coastalcleaning.example"
CHEN_ID = uuid.UUID("e0000001-0000-0000-0000-000000000001")
CHEN_ID_STR = str(CHEN_ID)


# ---------------------------------------------------------------------------
# Helpers — copied (not imported) from tests/test_resume_pipeline.py per this
# plan's read_first guidance: a plain function import is likely safe (the
# conditional-skip marker is evaluated at collection time for the defining
# module, not for importers) but copying is the simpler, guaranteed-safe
# option and keeps this module import-independent of the guarded one.
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


def _seed_run(fake_repo, *, body: str, from_addr: str = COASTAL_EMAIL) -> uuid.UUID:
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
    run_id: uuid.UUID = fake_repo.create_run(
        business_id=COASTAL_BIZ_ID,
        source_email_id=eid,
    )
    return run_id


def _inbound(body: str, from_addr: str = COASTAL_EMAIL) -> InboundEmail:
    """Build an InboundEmail for a reply (NOT persisted in fake_repo — safe for
    tests that don't exercise Task 1's mark_reply_consumed/accumulation seam)."""
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


def _inbound_persisted(
    fake_repo, run_id: uuid.UUID, body: str, from_addr: str = COASTAL_EMAIL
) -> InboundEmail:
    """Build a reply InboundEmail AND persist its row in fake_repo, linked to
    run_id — mirrors what the real webhook does (insert_inbound_email +
    link_email_to_run) BEFORE resume_pipeline is called.

    This is required, not incidental: resume_pipeline's own mark_reply_consumed
    call needs a REAL row to mark consumed, so that load_consumed_replies can
    genuinely return it for a later round's accumulation. Using the bare _inbound()
    helper above for a Round-1 reply would make this regression guard pass for the
    wrong reason — off a hardcoded mock response rather than real accumulation."""
    mid = f"<reply-{uuid.uuid4()}@test.example>"
    eid, _ = fake_repo.insert_inbound_email(
        message_id=mid,
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
        message_id=mid,
        in_reply_to=None,
        references_header=None,
        subject="Re: payroll hours",
        from_addr=from_addr,
        to_addr="agent@payroll-agent.local",
        body_text=body,
        created_at=datetime.now(UTC),
    )


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


# ---------------------------------------------------------------------------
# The known-edge fixture
# ---------------------------------------------------------------------------


def test_multi_round_context_preserves_round1_correction(fake_repo, mock_llm):
    """A correction stated in Round 1 and never restated must still be the value paid.

    This fixture lives in its own module (see the module docstring) because
    tests/test_resume_pipeline.py's module-level DATABASE_URL skip guard would
    silently skip it offline.

    Scenario (hermetic -- fake_repo + mock_llm, no live DB/LLM):
      Original email: Maria Chen worked 40 regular hours, 2 overtime.
      Round 1 reply: "Maria actually worked 30, not 40 -- no overtime this week."
        -> extraction persists hours_regular=30 (a paid->paid CORRECTION, invisible
           to detect_field_regression by design) and hours_overtime=None (a
           paid->unpaid DROP, which DOES trigger a field_regression clarification --
           on hours_overtime ONLY, not hours_regular).
      Round 2 reply: answers ONLY the overtime question ("no overtime, confirmed")
        -- it never restates the regular-hours correction.
      Round 2's combined extraction accumulates Round-1's reply text (via
      _combined_context_email's round-ordered accumulation) alongside the ORIGINAL
      body, so hours_regular reads the client's stated correction (30), not the
      stale ORIGINAL value (40). The consumed marker written by resume_pipeline's
      own claim is what makes Round-1's reply a REAL row that
      load_consumed_replies can return for Round 2.

    Assertion: the FINAL persisted/paid hours_regular is 30 -- the client's Round-1
    correction, carried into Round 2's accumulated context and paid -- NOT 40. A 40
    here means the pipeline silently reverted a correction the client explicitly
    made and paid 10 hours the employee did not work.
    """
    # ---- Original email + Round-1 correction -------------------------------
    run_id = _seed_run(
        fake_repo, body="Maria Chen worked 40 regular hours, 2 overtime"
    )

    # Pre-clarify snapshot: the original extraction (40 regular, 2 OT).
    snapshot = _mk_extracted(
        [{"submitted_name": "Maria Chen", "hours_regular": "40", "hours_overtime": "2"}],
        run_id=run_id,
    )
    fake_repo.set_pre_clarify_extracted(run_id, snapshot)
    prior_match = _mk_match("Maria Chen", CHEN_ID)
    fake_repo.persist_reconciliation(run_id, [prior_match])
    _set_run_awaiting_reply(fake_repo, run_id)

    # Round-1 reply: "Maria actually worked 30, not 40 -- no overtime this week."
    # Extraction persists hours_regular=30 (paid->paid correction, invisible to
    # detect_field_regression) and hours_overtime=None (paid->unpaid drop, DOES
    # trigger field_regression -- on hours_overtime only).
    mock_llm.script = [
        _extraction_json(
            [{"submitted_name": "Maria Chen", "hours_regular": "30"}]
        ),
        _suggestion_json({}),
        "Could you confirm Maria Chen's overtime hours?",
    ]

    reply_r1 = _inbound_persisted(
        fake_repo, run_id, "Maria actually worked 30, not 40 -- no overtime this week."
    )
    resume_pipeline(run_id, reply_r1)

    run_after_r1 = fake_repo.load_run(run_id)
    assert run_after_r1["status"] == RunStatus.AWAITING_REPLY.value, (
        f"Round 1 must clarify on the dropped hours_overtime field (paid->unpaid, "
        f"detectable); got {run_after_r1['status']!r}. The 40->30 hours_regular "
        "change alone is a paid->paid VALUE CHANGE and is invisible to "
        "detect_field_regression by design -- it is hours_overtime's drop that "
        "must trigger the Round-2 clarification here."
    )

    clarified_after_r1 = fake_repo.load_clarified_fields(run_id)
    assert clarified_after_r1.get(CHEN_ID_STR, {}).get("hours_overtime") == "asked", (
        f"Round 1 must ask specifically about hours_overtime (not hours_regular); "
        f"got {clarified_after_r1.get(CHEN_ID_STR, {})!r}"
    )

    # Confirm Round-1's genuine correction (30) was persisted going into Round 2.
    # persist_extracted overwrites run["extracted_data"] wholesale (InMemoryRepo
    # mirrors repo.persist_extracted). The pre-clarify snapshot is a SEPARATE,
    # never-overwritten baseline, so we read the persisted extraction from the run
    # row directly, not from load_pre_clarify_extracted.
    run_row_after_r1 = fake_repo.load_run(run_id)
    persisted_extracted_r1 = run_row_after_r1.get("extracted_data")
    assert persisted_extracted_r1 is not None, (
        "Round 1 must have persisted an extraction before deferring to clarify"
    )
    r1_regular = Decimal(str(persisted_extracted_r1["employees"][0]["hours_regular"]))
    assert r1_regular == Decimal("30"), (
        f"Round 1's persisted hours_regular must reflect the client's genuine "
        f"correction (30); got {r1_regular!r}. If this fails, the scenario setup "
        "itself is broken (not the regression under test)."
    )

    # ---- Round-2 reply: answers ONLY the overtime question ------------------
    # The Round-2 reply never restates "30" -- it only confirms no overtime.
    _r2_reply_only = _extraction_json(
        [{"submitted_name": "Maria Chen", "hours_regular": "40"}]
    )
    # Combined extraction (original + accumulated Round-1 reply + Round-2 reply):
    # _combined_context_email accumulates Round-1's consumed reply text ("Maria
    # actually worked 30, not 40...") alongside the ORIGINAL body, so a real
    # extraction model reading that accumulated context reads the CLIENT'S STATED
    # CORRECTION (30), not the stale original (40). Scripting the mock's response
    # as 30 matches what accumulation genuinely produces at runtime -- that the
    # Round-1 reply text really is present in the extraction input is proven
    # directly by test_combined_context.py::
    # test_consumed_marker_from_resume_drives_next_round_accumulation.
    _r2_combined = _extraction_json(
        [{"submitted_name": "Maria Chen", "hours_regular": "30"}]
    )
    mock_llm.script = [_r2_reply_only, _r2_combined]

    reply_r2 = _inbound("No overtime, confirmed.")
    resume_pipeline(run_id, reply_r2)

    run_after_r2 = fake_repo.load_run(run_id)
    assert run_after_r2["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"Round 2 answers the only outstanding asked field (hours_overtime) and "
        f"must reach AWAITING_APPROVAL; got {run_after_r2['status']!r}"
    )

    # The final persisted/paid hours_regular is the client's Round-1 correction
    # (30), NOT the stale ORIGINAL value (40). The correction survives into
    # Round 2's accumulated context and is paid.
    line_items = fake_repo.load_line_items(run_id)
    assert line_items, "paystub must be computed for a process run"
    chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
    assert chen_items, f"paystub item for Maria Chen ({CHEN_ID_STR}) must exist"
    final_regular = chen_items[0].hours_regular
    assert final_regular == Decimal("30"), (
        f"the final paystub hours_regular must be 30 -- the client's Round-1 "
        f"correction, carried into Round 2's accumulated context and paid; got "
        f"{final_regular!r}. If this fails with hours_regular reverting to 40, "
        "multi-round context accumulation has regressed and the pipeline is "
        "paying hours the client explicitly corrected away -- do not 'fix' it by "
        "changing this assertion back to 40."
    )


# ---------------------------------------------------------------------------
# A prior carried_forward terminal must survive later rounds
# ---------------------------------------------------------------------------


def test_prior_carried_forward_terminal_survives_later_round(fake_repo, mock_llm):
    """A prior-round `carried_forward` TERMINAL outcome must never be re-detected as
    the same paid->absent drop in a LATER round and flipped back to 'asked'.

    The trap: `carried_forward` is terminal but the field stays ABSENT from every
    subsequent extraction (that is what carrying forward means — the client never
    restates it). So round N+1 sees the same paid->absent shape as the original drop
    and re-detects it. If a prior carried_forward pair is in NEITHER suppression set,
    detect_field_regression re-emits the drop and
    `clarified.setdefault(emp_id, {})[field] = "asked"` overwrites the terminal —
    setdefault protects only the OUTER dict, not the inner field. The run then
    re-asks a question the client already answered, forever.

    The asymmetry that makes this correct: prior carried_forward pairs join
    suppress_detection ONLY, never backfill_skip. carried_forward MUST stay
    backfillable from the snapshot — skipping the backfill would pay 0 for a field
    the client told us to carry forward, an UNDERPAY. Suppress the re-question;
    keep the refill.

    Scenario (hermetic -- fake_repo + mock_llm, no live DB/LLM):
      Snapshot: Maria Chen 40 regular, 2 overtime, 8 vacation.
      Round 1: combined extraction drops hours_overtime -> field_regression ->
        hours_overtime 'asked', run parks AWAITING_REPLY.
      Round 2: reply is SILENT on overtime -> classified carried_forward
        (terminal). The combined extraction ALSO drops hours_vacation (paid 8 in
        the snapshot) -> NEW field_regression -> hours_vacation 'asked', run parks
        AWAITING_REPLY again.
      Round 3: reply answers ONLY the vacation question ("8 hours") and is again
        silent on overtime; the combined extraction again lacks overtime while the
        snapshot holds a positive value (2) — the re-detection bait.

    Assertions, both the money LABEL and the money VALUE:
      (a) the persisted hours_overtime outcome stays 'carried_forward' -- it is NOT
          flipped back to 'asked' by the round-3 re-detection;
      (b) the computed paystub line item still PAYS the carried-forward snapshot
          overtime (2), and the run reaches AWAITING_APPROVAL instead of re-asking
          a resolved question.
    A correct label with a wrong paid value is still a mispay, so (b) is not
    redundant with (a).
    """
    run_id = _seed_run(
        fake_repo,
        body="Maria Chen worked 40 regular hours, 2 overtime, 8 vacation",
    )

    # Pre-clarify snapshot: 40 regular, 2 OT, 8 vacation (all paid).
    snapshot = _mk_extracted(
        [
            {
                "submitted_name": "Maria Chen",
                "hours_regular": "40",
                "hours_overtime": "2",
                "hours_vacation": "8",
            }
        ],
        run_id=run_id,
    )
    fake_repo.set_pre_clarify_extracted(run_id, snapshot)
    fake_repo.persist_reconciliation(run_id, [_mk_match("Maria Chen", CHEN_ID)])
    _set_run_awaiting_reply(fake_repo, run_id)

    # ---- Round 1: combined extraction drops hours_overtime -> asked ---------
    mock_llm.script = [
        _extraction_json(
            [
                {
                    "submitted_name": "Maria Chen",
                    "hours_regular": "40",
                    "hours_vacation": "8",
                }
            ]
        ),
        _suggestion_json({}),
        "Could you confirm Maria Chen's overtime hours?",
    ]
    resume_pipeline(run_id, _inbound("Maria worked her usual 40, vacation was 8."))

    clarified_r1 = fake_repo.load_clarified_fields(run_id)
    assert clarified_r1.get(CHEN_ID_STR, {}).get("hours_overtime") == "asked", (
        f"scenario setup: Round 1 must ask about the dropped hours_overtime; "
        f"got {clarified_r1.get(CHEN_ID_STR, {})!r}"
    )
    assert fake_repo.load_run(run_id)["status"] == RunStatus.AWAITING_REPLY.value

    # ---- Round 2: silence on overtime -> carried_forward TERMINAL; ----------
    # ---- combined extraction ALSO drops vacation -> NEW asked field ---------
    mock_llm.script = [
        # Reply-only extraction (classify): Maria present, ALL hours silent ->
        # hours_overtime classifies as carried_forward (terminal).
        _extraction_json([{"submitted_name": "Maria Chen"}]),
        # Combined extraction (process/backfill): regular retained, overtime
        # still absent (suppressed this round via newly_classified), vacation
        # NOW ALSO absent (snapshot 8 -> None) -> NEW field_regression.
        _extraction_json(
            [{"submitted_name": "Maria Chen", "hours_regular": "40"}]
        ),
        # No further LLM calls: the round-2 clarification send is skipped by the
        # purpose-scoped idempotency guard (a separate, known limitation) -- the
        # run still parks at AWAITING_REPLY with hours_vacation 'asked'.
    ]
    resume_pipeline(run_id, _inbound("Sorry -- I'm not sure about her vacation."))

    clarified_r2 = fake_repo.load_clarified_fields(run_id)
    assert clarified_r2.get(CHEN_ID_STR, {}).get("hours_overtime") == "carried_forward", (
        f"scenario setup: Round 2 silence must classify hours_overtime as the "
        f"carried_forward terminal; got {clarified_r2.get(CHEN_ID_STR, {})!r}"
    )
    assert clarified_r2.get(CHEN_ID_STR, {}).get("hours_vacation") == "asked", (
        f"scenario setup: Round 2 must ask about the newly-dropped hours_vacation; "
        f"got {clarified_r2.get(CHEN_ID_STR, {})!r}"
    )
    assert fake_repo.load_run(run_id)["status"] == RunStatus.AWAITING_REPLY.value

    # ---- Round 3: answers ONLY vacation; still silent on overtime -----------
    mock_llm.script = [
        # Reply-only extraction (classify): vacation answered -> client_supplied.
        _extraction_json(
            [{"submitted_name": "Maria Chen", "hours_vacation": "8"}]
        ),
        # Combined extraction: AGAIN lacks the carried-forward overtime while
        # the snapshot holds a positive value (2) -- the re-detection bait.
        _extraction_json(
            [{"submitted_name": "Maria Chen", "hours_regular": "40"}]
        ),
    ]
    resume_pipeline(run_id, _inbound("Vacation was 8 hours, confirmed."))

    # (a) LABEL: the carried_forward terminal survives the round-3 re-detection.
    clarified_r3 = fake_repo.load_clarified_fields(run_id)
    assert clarified_r3.get(CHEN_ID_STR, {}).get("hours_overtime") == "carried_forward", (
        f"a prior carried_forward terminal must NOT be flipped back to 'asked' by "
        f"a later round's re-detection; got {clarified_r3.get(CHEN_ID_STR, {})!r}"
    )
    assert clarified_r3.get(CHEN_ID_STR, {}).get("hours_vacation") == "client_supplied", (
        f"Round 3's vacation answer must classify client_supplied; got "
        f"{clarified_r3.get(CHEN_ID_STR, {})!r}"
    )

    # The run processes (all fields resolved) instead of re-asking a resolved
    # question -- which the purpose-scoped send guard would silently never send,
    # parking the run at AWAITING_REPLY where no sweep can recover it.
    run_after_r3 = fake_repo.load_run(run_id)
    assert run_after_r3["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"Round 3 resolves the last asked field and must reach AWAITING_APPROVAL "
        f"(overtime suppressed as a prior terminal, backfilled from snapshot); "
        f"got {run_after_r3['status']!r}"
    )

    # (b) VALUE: the PAID overtime is the carried-forward snapshot value (2).
    # Assert the money value on the paystub line item, not just the label — fixing
    # the classify LABEL is not the same as fixing the PAID VALUE.
    line_items = fake_repo.load_line_items(run_id)
    assert line_items, "paystub must be computed for a process run"
    chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
    assert chen_items, f"paystub item for Maria Chen ({CHEN_ID_STR}) must exist"
    assert chen_items[0].hours_overtime == Decimal("2"), (
        f"the paid overtime must be the carried-forward snapshot value (2) -- "
        f"carried_forward stays OUT of backfill_skip so the backfill refills it; "
        f"adding it to backfill_skip would pay 0 (an underpay); got "
        f"{chen_items[0].hours_overtime!r}"
    )
    assert chen_items[0].hours_regular == Decimal("40")
    assert chen_items[0].hours_vacation == Decimal("8"), (
        f"Round 3's client-supplied vacation (8) must be the paid value; got "
        f"{chen_items[0].hours_vacation!r}"
    )
