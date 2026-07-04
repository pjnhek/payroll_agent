"""Known-edge regression fixture — multi-round context loss (09-REVIEWS.md).

WHY THIS LIVES IN ITS OWN MODULE (NOT tests/test_resume_pipeline.py):
tests/test_resume_pipeline.py carries a MODULE-LEVEL conditional-skip marker
gated on `os.environ.get("DATABASE_URL")` being unset (verified this session,
tests/test_resume_pipeline.py:41-48). That marker silently skips the ENTIRE
module — including any new test added to it — whenever DATABASE_URL is unset at
collection time. This fixture must be genuinely hermetic (fake_repo + mock_llm
only, no live DB/LLM) and run unconditionally offline, so it lives in a fresh
module with NO module-level conditional-skip marker of any kind (09-REVIEWS.md
Codex Round-2 NEW MEDIUM — "fixture would be skipped offline"). Do not
"helpfully" merge this file back into test_resume_pipeline.py.

WHAT THIS FIXTURE PROVES:
This is a KNOWN EDGE / RED-FLAG fixture. It asserts CURRENT — NOT DESIRED —
behavior: a genuine client correction stated in an intermediate (Round-1)
clarification reply, and never restated in a later (Round-2) reply, is silently
discarded by the combined-extraction resume path. The test PASSING today is not
evidence the behavior is acceptable; it exists so a future MONEY-class fix phase
has a concrete regression target. The day a fix lands (disposition (a) or (b) in
09-CONTEXT.md's Deferred Ideas), this assertion is EXPECTED to flip and FAIL —
that failure is the signal the gap has been closed, not a regression.

Verified chain (09-REVIEWS.md Claude in-session HIGH finding; traced against live
source this session):
  1. `clean_body` strips quoted reply history at ingest (app/email/clean.py:35-60)
     — thread quoting cannot preserve intermediate replies once the next arrives.
  2. `repo.load_source_email` (app/db/repo.py:279-296) returns ONLY the ingest-time
     ORIGINAL cleaned body — never updated by any reply.
  3. `_combined_context_email` (app/pipeline/orchestrator.py:772-785) builds the
     resume extraction context as ORIGINAL body + the CURRENT/LATEST reply only —
     an intermediate reply from an earlier round never accumulates into a later
     round's context.
  4. `detect_field_regression` (app/pipeline/validate.py) only fires on a
     paid->unpaid (dropped) transition — a paid->paid VALUE CHANGE (e.g. 40->30)
     is invisible to it by design.
  5. Round-2's classify-first logic (resume_pipeline, orchestrator.py) only
     reclassifies fields marked 'asked'; a field corrected in Round-1 but never
     the SUBJECT of a Round-2 clarification question is not re-examined.

Disposition: (c) per 09-REVIEWS.md — this fixture, plus an explicit deferred
entry in 09-CONTEXT.md's Deferred Ideas. See that file for the three candidate
fix dispositions ((a) accumulate reply bodies, (b) diff against last-persisted
extraction, (c) this fixture) reserved for a future MONEY-class phase (same
family as Phase 7.5's field-regression work). This plan changes NO production
code.
"""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from app.models.contracts import Extracted, ExtractedEmployee, InboundEmail
from app.models.roster import NameMatchResult
from app.models.status import RunStatus
from app.pipeline.orchestrator import resume_pipeline

# ---------------------------------------------------------------------------
# Stable identifiers (mirrors tests/test_resume_pipeline.py's seed.py constants —
# Business 1 / Coastal Cleaning Co. / Maria Chen, D-11).
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
    employees_data: list[dict],
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
    return fake_repo.create_run(
        business_id=COASTAL_BIZ_ID,
        source_email_id=eid,
    )


def _inbound(body: str, from_addr: str = COASTAL_EMAIL) -> InboundEmail:
    """Build an InboundEmail for a reply."""
    return InboundEmail(
        id=uuid.uuid4(),
        message_id=f"<reply-{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="Re: payroll hours",
        from_addr=from_addr,
        to_addr="agent@payroll-agent.local",
        body_text=body,
        created_at=datetime.now(timezone.utc),
    )


def _extraction_json(
    employees: list[dict],
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


def test_multi_round_context_loss_known_edge(fake_repo, mock_llm):
    """KNOWN EDGE (09-REVIEWS.md Claude in-session HIGH, deferred per disposition
    (c)): this test asserts CURRENT -- NOT DESIRED -- behavior. It exists so a
    future fix phase has a concrete regression target; it is not evidence the
    behavior is acceptable, only that it is understood and tracked. This fixture
    lives in its own module (see module docstring) because
    tests/test_resume_pipeline.py's module-level DATABASE_URL skip guard would
    silently skip it offline.

    Scenario (hermetic -- fake_repo + mock_llm, no live DB/LLM):
      Original email: Maria Chen worked 40 regular hours, 2 overtime.
      Round 1 reply: "Maria actually worked 30, not 40 -- no overtime this week."
        -> extraction persists hours_regular=30 (a genuine paid->paid CORRECTION,
           invisible to detect_field_regression by design) and hours_overtime=None
           (a paid->unpaid DROP, which DOES trigger a field_regression
           clarification -- on hours_overtime ONLY, not hours_regular).
      Round 2 reply: answers ONLY the overtime question ("no overtime, confirmed")
        -- never restates the regular-hours correction.
      Round 2's combined extraction re-reads the ORIGINAL body (via
      _combined_context_email) for anything the reply doesn't restate, so
      hours_regular reverts to 40 (the ORIGINAL value) -- silently discarding the
      client's genuine, stated Round-1 correction to 30. No gate, no
      clarification, no operator visibility fires for this paid->paid change.

    Assertion: the FINAL persisted/paid hours_regular is 40 (the ORIGINAL value),
    NOT 30 (the client's Round-1 correction). If this assertion ever fails, the
    combined-context accumulation gap has been fixed -- update/retire this test,
    do not "fix" it back to failing.
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

    reply_r1 = _inbound(
        "Maria actually worked 30, not 40 -- no overtime this week."
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
    # mirrors repo.persist_extracted). The pre-clarify snapshot (D-19/D-28) is a
    # SEPARATE, never-overwritten baseline, so we read the persisted extraction
    # from the run row directly, not from load_pre_clarify_extracted.
    run_row_after_r1 = fake_repo.load_run(run_id)
    persisted_extracted_r1 = run_row_after_r1.get("extracted_data")
    assert persisted_extracted_r1 is not None, (
        "Round 1 must have persisted an extraction before deferring to clarify"
    )
    r1_regular = Decimal(str(persisted_extracted_r1["employees"][0]["hours_regular"]))
    assert r1_regular == Decimal("30"), (
        f"Round 1's persisted hours_regular must reflect the client's genuine "
        f"correction (30); got {r1_regular!r}. If this fails, the scenario setup "
        "itself is broken (not the known edge under test)."
    )

    # ---- Round-2 reply: answers ONLY the overtime question ------------------
    # The Round-2 reply never restates "30" -- it only confirms no overtime.
    _r2_reply_only = _extraction_json(
        [{"submitted_name": "Maria Chen", "hours_regular": "40"}]
    )
    # Combined extraction (original + Round-2 reply): _combined_context_email
    # re-reads the ORIGINAL body (40 regular, 2 OT) since Round-1's reply text
    # was never accumulated into this context -- the ORIGINAL 40 resurfaces.
    _r2_combined = _extraction_json(
        [{"submitted_name": "Maria Chen", "hours_regular": "40"}]
    )
    mock_llm.script = [_r2_reply_only, _r2_combined]

    reply_r2 = _inbound("No overtime, confirmed.")
    resume_pipeline(run_id, reply_r2)

    run_after_r2 = fake_repo.load_run(run_id)
    assert run_after_r2["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"Round 2 answers the only outstanding asked field (hours_overtime) and "
        f"must reach AWAITING_APPROVAL; got {run_after_r2['status']!r}"
    )

    # THE KNOWN EDGE: the final persisted/paid hours_regular is the ORIGINAL
    # value (40), NOT the client's genuine Round-1 correction (30). This is the
    # silent-discard bug -- current, documented, deferred behavior.
    line_items = fake_repo.load_line_items(run_id)
    assert line_items, "paystub must be computed for a process run"
    chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
    assert chen_items, f"paystub item for Maria Chen ({CHEN_ID_STR}) must exist"
    final_regular = chen_items[0].hours_regular
    assert final_regular == Decimal("40"), (
        f"KNOWN EDGE (09-REVIEWS.md Claude in-session HIGH): the final paystub "
        f"hours_regular is expected to be 40 (the ORIGINAL value, silently "
        f"reverting Round-1's genuine 30 correction) under CURRENT behavior; got "
        f"{final_regular!r}. This assertion documents a real, deferred gap -- it "
        "is NOT a desired invariant. If this test starts failing because "
        "hours_regular now correctly resolves to 30, the combined-context "
        "accumulation gap (09-CONTEXT.md Deferred Ideas, dispositions (a)/(b)) "
        "has been fixed -- update or retire this test, do not chase it back to "
        "failing."
    )
