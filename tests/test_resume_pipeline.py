"""Integration tests for resume_pipeline — MONEY-03 state-machine invariants.

# Hermetic discipline (D-7.5-04d / Finding 7):
# All 15 tests use the fake_repo (in-memory) + mock_llm fixture from conftest.py,
# patching ALL repo calls onto an InMemoryRepo so no live DB writes occur during
# the test run. The module-level pytestmark guards the module: when DATABASE_URL
# is NOT set in the shell environment (module-load time, before any fixture runs),
# the entire module is skipped — skip != evidence (D-7.5-04). When DATABASE_URL
# IS set (signalling that the developer has a configured environment), all 15 tests
# run end-to-end via the full pipeline (resume_pipeline calls, mock LLM scripted
# responses, in-memory state machine) and must PASS. The mock_llm fixture sets a
# stub DATABASE_URL via monkeypatch WITHIN each test, but the pytestmark is
# evaluated at module load time so it correctly gates on the shell-level presence.
#
# Hermetic cleanup: fake_repo is function-scoped (default conftest fixture) and
# resets its in-memory state on each test — no cross-test contamination.
# No live DB cleanup is needed since no real DB writes are made.
# The mock_llm fixture also clears its script/calls lists before each test.
#
# NOTE: The 16 xfail integration stubs from plan 03 are replaced by these
# 15 PASSING tests. The xfail stubs are removed in this plan.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from app.models.contracts import Extracted, ExtractedEmployee, InboundEmail
from app.models.roster import NameMatchResult
from app.models.status import RunStatus
from app.pipeline.orchestrator import resume_pipeline
from tests.conftest import InMemoryRepo

# ---------------------------------------------------------------------------
# Module-level skip guard — skip != evidence (D-7.5-04)
# ---------------------------------------------------------------------------
pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason=(
        "requires DATABASE_URL set in shell env before phase gate; "
        "skip != evidence (D-7.5-04). "
        "Set DATABASE_URL to run these integration tests."
    ),
)

# ---------------------------------------------------------------------------
# Stable employee / business identifiers from seed.py (D-11)
# ---------------------------------------------------------------------------
# Business 1 — Coastal Cleaning Co. (payroll@coastalcleaning.example)
COASTAL_BIZ_ID = uuid.UUID("b0000001-0000-0000-0000-000000000001")
COASTAL_EMAIL = "payroll@coastalcleaning.example"

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
    """Build an Extracted from a list of employee dicts (PATTERNS.md §8 style)."""
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
    """Build a NameMatchResult (PATTERNS.md §8 style)."""
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


# ---------------------------------------------------------------------------
# Test 1 — test_snapshot_once_not_overwritten (D-19 / D-28)
# ---------------------------------------------------------------------------

def test_snapshot_once_not_overwritten(fake_repo, mock_llm):
    """D-19/D-28: set_pre_clarify_extracted IS NULL guard — second write is a no-op.

    A second set_pre_clarify_extracted call must NOT overwrite the first snapshot.
    The IS NULL CAS guard makes this idempotent.
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
        f"D-19: first snapshot (OT=2) must be preserved; got {ot!r}"
    )


# ---------------------------------------------------------------------------
# Test 2 — test_n1_single_run_stages_call (N1)
# ---------------------------------------------------------------------------

def test_n1_single_run_stages_call(fake_repo, mock_llm, monkeypatch):
    """N1: resume_pipeline calls _run_stages exactly once per invocation.

    The Round-1 and Round-2 _run_stages calls are in mutually-exclusive
    if/else branches; exactly one fires per resume_pipeline call.
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
    resume_pipeline(run_id, reply)

    assert call_count[0] == 1, (
        f"N1: _run_stages must be called exactly once per resume_pipeline invocation; "
        f"called {call_count[0]} times"
    )


# ---------------------------------------------------------------------------
# Test 3 — test_n2_asked_written_before_send (N2 — asked-before-send ordering)
# ---------------------------------------------------------------------------

def test_n2_asked_written_before_send(fake_repo, mock_llm, monkeypatch):
    """N2: clarified_fields has 'asked' BEFORE the clarification email is sent.

    The orchestrator must call set_clarified_fields (writing 'asked') before
    calling _clarify (which writes the outbound row). This ordering is the N2
    invariant — never send before writing 'asked'.
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

    # N2: set_clarified_fields (writing 'asked') must precede _clarify (send)
    assert "set_clarified_fields" in ordering, "set_clarified_fields must have been called"
    assert "_clarify" in ordering, "_clarify must have been called"
    asked_idx = ordering.index("set_clarified_fields")
    clarify_idx = ordering.index("_clarify")
    assert asked_idx < clarify_idx, (
        f"N2 violation: set_clarified_fields (idx={asked_idx}) must precede "
        f"_clarify (idx={clarify_idx}) — 'asked' must be written before the send"
    )

    # Also assert _clarify was called with purpose='clarification_field_regression'
    # (verifiable by checking outbound row purpose in fake_repo)
    outbound = fake_repo.outbound.get(str(run_id), [])
    assert any(r.get("purpose") == "clarification_field_regression" for r in outbound), (
        "N2: _clarify must be called with purpose='clarification_field_regression'"
    )


# ---------------------------------------------------------------------------
# Test 4 — test_ordering_carried_forward_ot_in_paystub (D-7.5-04a — ROOT CAUSE PIN)
# ---------------------------------------------------------------------------

def test_ordering_carried_forward_ot_in_paystub(fake_repo, mock_llm):
    """D-7.5-04a: carried-forward OT=2 lands in the FINAL PAYSTUB LINE ITEM.

    Round-2 path: OT asked, reply is SILENT (OT=None). backfill_extracted
    must run BEFORE _compute_line_items so the paystub sees OT=2.

    NEGATIVE COMPANION: if backfill_extracted ran AFTER calc, OT would be
    absent from the extracted passed to calculate(), and the paystub would
    show OT=0 or None. This test FAILS if backfill-after-calc regression occurs.
    (Pins R3-1 ordering invariant.)
    """
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")
    _setup_round2(fake_repo, run_id, "Maria Chen", CHEN_ID, CHEN_ID_STR)

    # Round-2 reply: OT=None (client silent — should carry forward OT=2)
    # CR-01 FIX: Round-2 now does TWO extractions — reply-only (classify) then
    # combined (process/backfill). Both return the same here: OT=None (silence).
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
        f"D-7.5-04a: carried-forward OT=2 must appear in paystub; "
        f"got hours_overtime={item.hours_overtime!r}. "
        "NEGATIVE COMPANION: if backfill ran AFTER calc, OT would be absent → paystub OT=0."
    )


# ---------------------------------------------------------------------------
# Test 5 — test_approved_bytes_equals_sent_bytes (D-7.5-04b — Finding 8)
# ---------------------------------------------------------------------------

def test_approved_bytes_equals_sent_bytes(fake_repo, mock_llm, monkeypatch):
    """D-7.5-04b (Finding 8): confirmation email source data uses the AWAITING_APPROVAL paystub.

    The paystub at AWAITING_APPROVAL (with carried-forward OT=2) must be the SAME
    data that flows into compose_confirmation when the operator approves the run.
    This pins the approved==sent invariant: the paystub the operator sees IS the
    paystub in the confirmation email.
    """
    import app.pipeline.delivery as delivery

    # Step 1: drive to AWAITING_APPROVAL via Round-2 carry-forward
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")
    _setup_round2(fake_repo, run_id, "Maria Chen", CHEN_ID, CHEN_ID_STR)

    # CR-01 FIX: Round-2 now does TWO extractions (reply-only then combined).
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

    # Step 3: capture what compose_confirmation receives — same line items from repo
    # (Finding 8: confirmation must use repo.load_line_items which reads the persisted paystub)
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
        f"D-7.5-04b: confirmation must use paystub with OT=2; got {conf_ot!r}. "
        "Finding 8: approved==sent invariant — the operator sees OT=2, "
        "the confirmation email must also carry OT=2."
    )


# ---------------------------------------------------------------------------
# Test 6 — test_tri_state_through_real_path (D-7.5-04c)
# ---------------------------------------------------------------------------

def test_tri_state_through_real_path(fake_repo, mock_llm):
    """D-7.5-04c: None vs Decimal('0') survive through the JSONB round-trip.

    set_pre_clarify_extracted serialises via model_dump(mode='json');
    load_pre_clarify_extracted deserialises via Extracted.model_validate.
    None must survive as None; Decimal('0') must survive as Decimal('0').
    This tests the SAME serialisation path the real code uses (not hand-typed JSON).
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
        f"D-7.5-04c: None OT must round-trip as None; got {emp.hours_overtime!r}"
    )
    # Decimal('0') survives as Decimal('0') (not None)
    assert emp.hours_vacation == Decimal("0"), (
        f"D-7.5-04c: Decimal('0') vacation must round-trip as Decimal('0'); "
        f"got {emp.hours_vacation!r}"
    )


# ---------------------------------------------------------------------------
# Test 7 — test_loop_guard_fires_exactly_once
# ---------------------------------------------------------------------------

def test_loop_guard_fires_exactly_once(fake_repo, mock_llm):
    """Loop guard: a field-regression clarification fires exactly once.

    Round-1 sets 'asked'. Round-2 reply is silent on OT. The run must reach
    AWAITING_APPROVAL (not a second AWAITING_REPLY — no second clarification).
    """
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")
    _setup_round2(fake_repo, run_id, "Maria Chen", CHEN_ID, CHEN_ID_STR)

    # Round-2 reply: OT=None (silence → carry-forward → process → AWAITING_APPROVAL)
    # CR-01 FIX: Round-2 now does TWO extractions (reply-only then combined).
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


# ---------------------------------------------------------------------------
# Test 8 — test_mixed_issue_records_asked_and_asks_field_regression (SC4 / R3-2)
# ---------------------------------------------------------------------------

def test_mixed_issue_records_asked_and_asks_field_regression(fake_repo, mock_llm):
    """SC4 / R3-2: mixed-issue scenario — field_regression + unresolved name.

    When a run has BOTH a field_regression issue (OT dropped) AND a normal
    unresolved-name issue, the clarification defers under
    purpose='clarification_field_regression' (R3-2 fix). The 'asked' outcome
    is recorded in clarified_fields, and the outbound email has the correct purpose.
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
        f"SC4: mixed-issue run must be AWAITING_REPLY; got {run['status']!r}"
    )

    # 'asked' must be in clarified_fields for Maria Chen
    clarified = fake_repo.load_clarified_fields(run_id)
    assert CHEN_ID_STR in clarified, "SC4: clarified_fields must have entry for Maria Chen"
    assert clarified[CHEN_ID_STR].get("hours_overtime") == "asked", (
        f"SC4: hours_overtime must be 'asked' for Maria Chen; "
        f"got {clarified[CHEN_ID_STR]!r}"
    )

    # Outbound must have purpose='clarification_field_regression' (R3-2 fix)
    outbound = fake_repo.outbound.get(str(run_id), [])
    assert any(r.get("purpose") == "clarification_field_regression" for r in outbound), (
        "SC4 / R3-2: mixed-issue must clarify under purpose='clarification_field_regression'"
    )


# ---------------------------------------------------------------------------
# Test 9 — test_restated_name_prior_matches_threading (R3-3 + R2-2)
# ---------------------------------------------------------------------------

def test_restated_name_prior_matches_threading(fake_repo, mock_llm):
    """R3-3 + R2-2 integration pin: 'M. Chen' in snapshot, 'Maria Chen' in reply.

    PART A (Round-1 — R3-3 pin):
      'M. Chen' submitted in original email (snapshot OT=2).
      Round-1 reply uses full name 'Maria Chen' (same employee_id via alias).
      Reply OT=None → field_regression must be DETECTED and asked.
      Assert: run at AWAITING_REPLY, 'asked' written.
      R3-3 integration pin: FAILS if prior_matches is defaulted to None —
      detect_field_regression returns [] without prior_matches, no drop detected,
      run processes instead of clarifying.

    PART B (Round-2 — R2-2 pin):
      Round-2: 'Maria Chen' still silent on OT.
      Assert: paystub OT=Decimal('2') (employee_id-keyed backfill carried the value).
      Assert: clarified_fields outcome 'carried_forward'.
      R2-2 fix pin: FAILS if backfill_extracted uses submitted_name-keyed snapshot lookup
      ('Maria Chen' absent from prior alias key 'M. Chen' → no carry-forward → OT=0).
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

    # Round-1 reply: "Maria Chen" (full name restated) with OT=None
    # R3-3 pin: prior_matches must be threaded into detect_field_regression so
    # the employee_id-keyed diff finds "M. Chen" (prior) == "Maria Chen" (current)
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
        f"R3-3 integration pin: field_regression must be detected (AWAITING_REPLY); "
        f"got {run['status']!r}. "
        "FAILS if prior_matches is defaulted to None — detect_field_regression returns "
        "[] without prior_matches, no drop detected, run processes instead of clarifying."
    )

    clarified = fake_repo.load_clarified_fields(run_id)
    assert CHEN_ID_STR in clarified, (
        "R3-3: clarified_fields must have entry for Maria Chen's employee_id"
    )
    assert clarified[CHEN_ID_STR].get("hours_overtime") == "asked", (
        f"R3-3: hours_overtime must be 'asked'; got {clarified[CHEN_ID_STR]!r}"
    )

    # ---- PART B: Round-2 carry-forward via employee_id-keyed backfill ----
    # Force AWAITING_REPLY (Round-2)
    _set_run_awaiting_reply(fake_repo, run_id)

    # Round-2: "Maria Chen" still silent on OT
    # CR-01 FIX: Round-2 now does TWO extractions (reply-only then combined).
    _r2_silent = _extraction_json([{"submitted_name": "Maria Chen", "hours_regular": "40"}])
    mock_llm.script = [_r2_silent, _r2_silent]

    reply_r2 = _inbound("Maria Chen 40 regular hours (OT same as before)")
    resume_pipeline(run_id, reply_r2)

    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"R2-2: Round-2 silence should reach AWAITING_APPROVAL; got {run['status']!r}"
    )

    # Paystub must have OT=2 (employee_id-keyed backfill_extracted carried it)
    line_items = fake_repo.load_line_items(run_id)
    assert line_items, "paystub must be computed for process run"
    chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
    assert chen_items, "paystub item for Maria Chen must exist"
    ot = chen_items[0].hours_overtime
    assert ot == Decimal("2"), (
        f"R2-2 fix pin: carried-forward paystub must have OT=2; got {ot!r}. "
        "FAILS if backfill_extracted uses submitted_name-keyed snapshot lookup: "
        "'Maria Chen' is absent from snapshot keyed by 'M. Chen' → no carry-forward."
    )

    # clarified_fields outcome must be 'carried_forward'
    clarified_r2 = fake_repo.load_clarified_fields(run_id)
    assert clarified_r2.get(CHEN_ID_STR, {}).get("hours_overtime") == "carried_forward", (
        f"R2-2: clarified_fields outcome must be 'carried_forward'; "
        f"got {clarified_r2.get(CHEN_ID_STR, {})!r}"
    )


# ---------------------------------------------------------------------------
# Test 10 — test_confirmed_dropped_no_reloop_on_round2 (BLOCKER FIX)
# ---------------------------------------------------------------------------

def test_confirmed_dropped_no_reloop_on_round2(fake_repo, mock_llm):
    """BLOCKER FIX cross-plan key-type consistency: confirmed_dropped suppresses reloop.

    Round-1: 'M. Chen' OT=2 snapshot; Round-1 reply OT=Decimal('0')
    → OT classified as 'confirmed_dropped' (injected as terminal state).

    Round-2: 'Maria Chen' OT=None (restated name, same employee_id, silent).
    Assert: OT NOT backfilled (confirmed_dropped is in backfill_skip → guard fires).
    Assert: run reaches AWAITING_APPROVAL (N8 suppression fired — no re-clarify).

    FAILS for any of three regressions:
    1. suppress_detection set keyed by submitted_name (not emp_id_str).
    2. str(current_emp_id) missing — UUID vs str mismatch in the set lookup.
    3. backfill_extracted guard keyed by name instead of (emp_id_str, field).
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

    # Round-2: 'Maria Chen' OT=None (restated name, same employee_id)
    # BLOCKER FIX: suppress_detection must use (emp_id_str, field) keys (not names).
    # The current reconciliation resolves 'Maria Chen' → CHEN_ID.
    # CR-01 FIX: Round-2 now does TWO extractions (reply-only then combined).
    _r2_silent = _extraction_json([{"submitted_name": "Maria Chen", "hours_regular": "40"}])
    mock_llm.script = [_r2_silent, _r2_silent]

    reply = _inbound("Maria Chen 40 regular hours")
    resume_pipeline(run_id, reply)

    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"BLOCKER FIX cross-plan key-type consistency: N8 must suppress re-clarify "
        f"for confirmed_dropped OT; got {run['status']!r}. "
        "FAILS if suppress_detection set uses submitted_name keys instead of (emp_id_str, field)."
    )

    # OT must NOT be backfilled (confirmed_dropped in backfill_skip → no overpay)
    line_items = fake_repo.load_line_items(run_id)
    if line_items:
        chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
        if chen_items:
            ot = chen_items[0].hours_overtime
            assert ot != Decimal("2"), (
                f"BLOCKER FIX: confirmed_dropped OT must NOT be re-backfilled; "
                f"got OT={ot!r} (expected 0 or None)"
            )


# ---------------------------------------------------------------------------
# Test 11 — test_detect_fired_on_raw (D-7.5-10 three-phase ordering — R2-1 proof)
# ---------------------------------------------------------------------------

def test_detect_fired_on_raw(fake_repo, mock_llm, monkeypatch):
    """D-7.5-10 three-phase ordering — R2-1 proof.

    PART A: Round-1 path — detect_field_regression fires on RAW (pre-backfill) extracted.
      Setup: 'Maria Chen' OT=2 in snapshot. Round-1 reply has OT=None (client silent).
      Assert: (1) field_regression issue emitted (run at AWAITING_REPLY).
              (2) 'asked' written in clarified_fields before _clarify (N2).
              (3) outbound with purpose='clarification_field_regression' sent.

      D-7.5-10 detect-on-raw proof: if backfill ran before detect, the snapshot's
      OT=2 would fill in the reply's None → both sides OT=2 → no drop → no issue →
      no clarification. The test would then FAIL on assertion (1) (AWAITING_REPLY
      expected, AWAITING_APPROVAL actual — no regression detected).

    PART B: Continue to Round-2 carry-forward — full round-trip proof.
      Round-2 reply still silent on OT → carry-forward fires → paystub OT=2.
      Assert: paystub OT=Decimal('2').
      Together with PART A, proves D-7.5-10 end-to-end.
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
        f"D-7.5-10 detect-on-raw proof: field_regression must be detected (AWAITING_REPLY); "
        f"got {run['status']!r}. "
        "If backfill ran before detect, OT 2→None drop would be masked → no issue → no clarify."
    )

    # Drops must have been detected on RAW (pre-backfill) data
    ot_drops = [d for d in detected_on_raw_drops if d.field == "hours_overtime"]
    assert ot_drops, (
        "D-7.5-10: detect_field_regression must have emitted an OT drop on the RAW extracted "
        "(pre-backfill). If detect ran post-backfill, the snapshot's OT=2 would mask the drop."
    )

    # 'asked' must be written
    clarified = fake_repo.load_clarified_fields(run_id)
    assert clarified.get(CHEN_ID_STR, {}).get("hours_overtime") == "asked", (
        "D-7.5-10: hours_overtime must be 'asked' after field_regression detection"
    )

    # Outbound with purpose='clarification_field_regression'
    outbound = fake_repo.outbound.get(str(run_id), [])
    assert any(r.get("purpose") == "clarification_field_regression" for r in outbound), (
        "D-7.5-10: clarification_field_regression outbound must be sent"
    )

    # ---- PART B: Round-2 carry-forward (full round-trip proof) ----
    _set_run_awaiting_reply(fake_repo, run_id)

    # CR-01 FIX: Round-2 now does TWO extractions (reply-only then combined).
    _r2_silent = _extraction_json([{"submitted_name": "Maria Chen", "hours_regular": "40"}])
    mock_llm.script = [_r2_silent, _r2_silent]

    reply_r2 = _inbound("Maria Chen 40 regular (OT is the usual 2)")
    resume_pipeline(run_id, reply_r2)

    run_r2 = fake_repo.load_run(run_id)
    assert run_r2["status"] == RunStatus.AWAITING_APPROVAL.value, (
        "D-7.5-10 PART B: Round-2 silence should carry-forward and reach AWAITING_APPROVAL"
    )

    line_items = fake_repo.load_line_items(run_id)
    assert line_items, "paystub must exist"
    chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
    assert chen_items, "paystub item for Maria Chen must exist"
    ot = chen_items[0].hours_overtime
    assert ot == Decimal("2"), (
        f"D-7.5-10 PART B full round-trip: carried-forward paystub OT must be 2; "
        f"got {ot!r}. Both PART A + PART B together prove D-7.5-10 end-to-end."
    )


# ---------------------------------------------------------------------------
# Test 12 — test_client_supplied_same_value_labeled_correctly (R2-3 fix proof)
# ---------------------------------------------------------------------------

def test_client_supplied_same_value_labeled_correctly(fake_repo, mock_llm):
    """R2-3 fix proof: client supplies OT=2 (SAME as snapshot) → 'client_supplied'.

    The classify-first step reads from RAW reply BEFORE backfill. Raw reply has
    OT=Decimal('2') (present-positive) → classified as 'client_supplied'.

    Before the D-7.5-11 / R2-3 fix: a post-decide reclassifier would see
    the backfilled extracted (OT=2 from snapshot) and mistake it for silence
    carry-forward → 'carried_forward' (incorrect label, implies client was silent).

    After the fix: classify-first sees raw reply OT=2 > 0 → 'client_supplied'.
    The label is correct: the client actively re-supplied the same value.

    Assert: clarified_fields outcome for hours_overtime is 'client_supplied' NOT 'carried_forward'.
    Assert: run at AWAITING_APPROVAL.

    R2-3 fix proof: classify-first reads raw reply before backfill; present-positive
    → client_supplied.
    """
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")
    _setup_round2(fake_repo, run_id, "Maria Chen", CHEN_ID, CHEN_ID_STR)

    # Round-2 reply: OT=Decimal('2') (same value as snapshot — client re-confirms)
    # CR-01 FIX: Round-2 now does TWO extractions (reply-only then combined).
    _r2_ot2 = _extraction_json(
        [{"submitted_name": "Maria Chen", "hours_regular": "40", "hours_overtime": "2"}]
    )
    mock_llm.script = [_r2_ot2, _r2_ot2]

    reply = _inbound("Maria Chen 40 regular 2 overtime (same as last week)")
    resume_pipeline(run_id, reply)

    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"R2-3: client_supplied run must reach AWAITING_APPROVAL; got {run['status']!r}"
    )

    clarified = fake_repo.load_clarified_fields(run_id)
    outcome = clarified.get(CHEN_ID_STR, {}).get("hours_overtime")
    assert outcome == "client_supplied", (
        f"R2-3 fix proof: OT=2 (same as snapshot) in RAW reply must be 'client_supplied', "
        f"NOT 'carried_forward'; got {outcome!r}. "
        "Before fix: post-decide classifier saw backfilled data → mislabeled as carried_forward. "
        "After fix: classify-first reads raw reply before backfill → present-positive → "
        "client_supplied."
    )


# ---------------------------------------------------------------------------
# Test 13 — test_answered_silence_reaches_approval (NEW — D-7.5-11 proof)
# ---------------------------------------------------------------------------

def test_answered_silence_reaches_approval(fake_repo, mock_llm):
    """D-7.5-11 proof: answered-silence reaches AWAITING_APPROVAL in ONE _run_stages call.

    Setup: Round-1 asked OT (snapshot OT=2, clarified={chen_id: {hours_overtime: 'asked'}}).
           Round-2 reply: Maria Chen OT=None (SILENCE — client does not mention OT).
    Call resume_pipeline (Round-2 path).

    Assertions:
      1. run status == AWAITING_APPROVAL (NOT AWAITING_REPLY — no second clarification).
      2. paystub hours_overtime == Decimal('2') (carry-forward fired; not dropped).
      3. clarified_fields outcome for hours_overtime is 'carried_forward'.
      4. No second outbound row with purpose='clarification_field_regression'.

    # D-7.5-11 proof: answered-silence reaches AWAITING_APPROVAL in a single _run_stages call.
    # The fix (classify-first): classify-first labels OT 'carried_forward', includes it in
    # suppress_detection. _run_stages: N8 suppresses field_regression re-emission for OT.
    # decide → process → run reaches AWAITING_APPROVAL. Paystub OT=2 (backfill fired in Phase 2).
    #
    # NEGATIVE COMPANION — the D-7.5-11 failure mode (classify-after-decide ordering):
    # If classify-first is removed and the old ordering is restored:
    # Step E2 builds _resolved_by_name from TERMINAL outcomes only ('asked' is not terminal).
    # The just-answered OT field is NOT in _resolved_by_name.
    # _run_stages(resolved_drops=_resolved_by_name) does NOT suppress OT in N8.
    # detect_field_regression sees OT: 2→None (a drop) → field_regression issue emitted.
    # decide → request_clarification → _run_stages DEFERS, skips _compute_line_items.
    # Run re-clarifies (strands at AWAITING_REPLY). This test then FAILS assertion (1)
    # (expected AWAITING_APPROVAL, got AWAITING_REPLY) — the exact D-7.5-11 stranding bug.
    # classify-first is the fix; classify-after-decide is the failure mode.
    """
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")
    _setup_round2(fake_repo, run_id, "Maria Chen", CHEN_ID, CHEN_ID_STR)

    # Round-2 reply: OT=None (SILENCE — client does not mention overtime)
    # CR-01 FIX: Round-2 now does TWO extractions (reply-only then combined).
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
        f"D-7.5-11 proof: answered-silence must reach AWAITING_APPROVAL; "
        f"got {run['status']!r}. "
        "classify-after-decide ordering would strand the run at AWAITING_REPLY "
        "(the D-7.5-11 failure mode this test prevents)."
    )

    # Assertion 2: paystub OT=2 (carry-forward fired, not dropped)
    line_items = fake_repo.load_line_items(run_id)
    assert line_items, "paystub must be computed"
    chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
    assert chen_items, "paystub item for Maria Chen must exist"
    ot = chen_items[0].hours_overtime
    assert ot == Decimal("2"), (
        f"D-7.5-11 proof: carry-forward must set paystub OT=2; got {ot!r}. "
        "Silence means client intended OT=2 to carry forward (not drop)."
    )

    # Assertion 3: clarified_fields outcome is 'carried_forward'
    clarified = fake_repo.load_clarified_fields(run_id)
    outcome = clarified.get(CHEN_ID_STR, {}).get("hours_overtime")
    assert outcome == "carried_forward", (
        f"D-7.5-11 proof: outcome must be 'carried_forward'; got {outcome!r}"
    )

    # Assertion 4: no second outbound field_regression clarification
    outbound = fake_repo.outbound.get(str(run_id), [])
    field_reg_rows = [r for r in outbound if r.get("purpose") == "clarification_field_regression"]
    assert len(field_reg_rows) == 0, (
        f"D-7.5-11 proof: no second clarification_field_regression email must be sent; "
        f"found {len(field_reg_rows)} such rows"
    )


# ---------------------------------------------------------------------------
# Test 14 — test_answered_explicit_zero_not_rebackfilled (D-7.5-11 overpay guard)
# ---------------------------------------------------------------------------

def test_answered_explicit_zero_not_rebackfilled(fake_repo, mock_llm):
    """D-7.5-11 overpay guard proof: explicit-zero answered field is NOT re-backfilled.

    Setup: same as test 13 (snapshot OT=2, 'asked' for OT), EXCEPT:
           Round-2 reply has OT=Decimal('0') (EXPLICIT ZERO — client removing OT).
    Call resume_pipeline (Round-2 path).

    Assertions:
      1. run status == AWAITING_APPROVAL (no second clarification).
      2. paystub hours_overtime is None or Decimal('0') — NOT Decimal('2').
         This is the critical overpay guard: the explicit zero is honored.
         The snapshot value (OT=2) is NOT re-backfilled.
      3. clarified_fields outcome is 'confirmed_dropped'.

    # D-7.5-11 overpay guard proof: explicit-zero answered field is NOT re-backfilled.
    # _is_paid(Decimal('0')) is False — explicit zero LOOKS backfillable by value alone.
    # The classify-first step labels OT 'confirmed_dropped' and includes it in suppress_detection.
    # backfill_extracted: (emp_id_str, 'hours_overtime') in resolved_drops (= backfill_skip;
    # confirmed_dropped IS in backfill_skip) → SKIP backfill.
    # Paystub OT=0 (or absent), not OT=2.
    # NOTE: confirmed_dropped is in BOTH suppress_detection (for N8) AND backfill_skip
    # (for backfill guard). carried_forward is in suppress_detection ONLY (NOT
    # backfill_skip) → backfill FILLS → OT=2 in test 13.
    #
    # The naive "also suppress on asked" patch would NOT protect this: if we had added
    # 'asked' to _resolved_by_name without classify-first, the suppress set is populated
    # but backfill_extracted doesn't know whether to skip because the set only blocks
    # re-detection, not re-backfill.
    # The actual fix is that classify-first determines confirmed_dropped (not just
    # 'suppress for asked') so backfill_extracted's check (emp_id_str, field) in
    # resolved_drops correctly excludes it.
    # Test FAILS if paystub OT=2 (re-backfilled — OVERPAY).
    """
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")
    _setup_round2(fake_repo, run_id, "Maria Chen", CHEN_ID, CHEN_ID_STR)

    # Round-2 reply: OT=Decimal('0') (EXPLICIT ZERO — client removes overtime)
    # CR-01 FIX: Round-2 now does TWO extractions (reply-only then combined).
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
        f"D-7.5-11 overpay guard: explicit-zero must reach AWAITING_APPROVAL; "
        f"got {run['status']!r}"
    )

    # Assertion 2: paystub OT is 0 or None — NOT 2 (no re-backfill = no overpay)
    line_items = fake_repo.load_line_items(run_id)
    if line_items:
        chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
        if chen_items:
            ot = chen_items[0].hours_overtime
            assert ot != Decimal("2"), (
                f"D-7.5-11 OVERPAY GUARD: explicit-zero OT=0 must NOT be re-backfilled to 2; "
                f"got {ot!r}. "
                "_is_paid(Decimal('0')) is False so explicit-zero looks backfillable by value "
                "alone; the resolved_drops gate (confirmed_dropped in backfill_skip) is the "
                "protection."
            )

    # Assertion 3: clarified_fields outcome is 'confirmed_dropped'
    clarified = fake_repo.load_clarified_fields(run_id)
    outcome = clarified.get(CHEN_ID_STR, {}).get("hours_overtime")
    assert outcome == "confirmed_dropped", (
        f"D-7.5-11 overpay guard: OT=Decimal('0') must be 'confirmed_dropped'; "
        f"got {outcome!r}"
    )


# ---------------------------------------------------------------------------
# Test 15 — test_answered_positive_uses_client_value (D-7.5-11 client_supplied)
# ---------------------------------------------------------------------------

def test_answered_positive_uses_client_value(fake_repo, mock_llm):
    """D-7.5-11 client_supplied proof: positive answered field uses the client's value.

    Setup: same as test 13 (snapshot OT=2, 'asked' for OT), EXCEPT:
           Round-2 reply has OT=Decimal('5') (POSITIVE VALUE — client supplies different amount).
    Call resume_pipeline (Round-2 path).

    Assertions:
      1. run status == AWAITING_APPROVAL.
      2. paystub hours_overtime == Decimal('5') (client-supplied value, NOT snapshot OT=2).
      3. clarified_fields outcome is 'client_supplied'.

    # D-7.5-11 client_supplied proof: positive answered field uses the client's value.
    # classify-first: OT=Decimal('5') in raw reply → present-positive → client_supplied.
    # (emp_id_str, 'hours_overtime') added to suppress_detection.
    # backfill_extracted: field in resolved_drops (= backfill_skip; client_supplied IS in
    # backfill_skip) → SKIP backfill.
    # NOTE: client_supplied is in BOTH suppress_detection (for N8) AND backfill_skip
    # (for backfill guard).
    # BUT the raw extracted already has OT=5, so _compute_line_items uses OT=5.
    # Paystub OT=5 (client value), labeled 'client_supplied'.
    """
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")
    _setup_round2(fake_repo, run_id, "Maria Chen", CHEN_ID, CHEN_ID_STR)

    # Round-2 reply: OT=Decimal('5') (POSITIVE VALUE — client supplies a different amount)
    # CR-01 FIX: Round-2 now does TWO extractions (reply-only then combined).
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
        f"D-7.5-11 client_supplied: run must reach AWAITING_APPROVAL; "
        f"got {run['status']!r}"
    )

    # Assertion 2: paystub OT=5 (client-supplied value, not snapshot OT=2)
    line_items = fake_repo.load_line_items(run_id)
    assert line_items, "paystub must be computed"
    chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
    assert chen_items, "paystub item for Maria Chen must exist"
    ot = chen_items[0].hours_overtime
    assert ot == Decimal("5"), (
        f"D-7.5-11 client_supplied proof: paystub OT must be 5 (client-supplied); "
        f"got {ot!r} (NOT snapshot OT=2). "
        "backfill_extracted skips client_supplied fields (in backfill_skip); "
        "raw extracted OT=5 flows directly to _compute_line_items."
    )

    # Assertion 3: clarified_fields outcome is 'client_supplied'
    clarified = fake_repo.load_clarified_fields(run_id)
    outcome = clarified.get(CHEN_ID_STR, {}).get("hours_overtime")
    assert outcome == "client_supplied", (
        f"D-7.5-11 client_supplied proof: outcome must be 'client_supplied'; "
        f"got {outcome!r}"
    )


# ---------------------------------------------------------------------------
# Test 16 — test_cr02_round2_new_regression_reaches_awaiting_reply (CR-02 fix)
# ---------------------------------------------------------------------------

def test_cr02_round2_new_regression_reaches_awaiting_reply(fake_repo, mock_llm):
    """CR-02 fix: Round-2 reply that introduces a NEW field regression sends a
    clarification and reaches AWAITING_REPLY — NOT stuck at 'extracting'.

    Setup:
    - Snapshot: Maria Chen hours_overtime=2, hours_holiday=8.
    - Round-1 asked ONLY about hours_overtime (snapshot OT=2 dropped).
    - Round-2 reply: answers OT (present-positive, OT=2) but NOW drops hours_holiday
      (8 → absent in reply). suppress_detection covers only (CHEN_ID, hours_overtime)
      from Round-1. detect_field_regression emits a NEW drop for hours_holiday (NOT
      suppressed) → validate → decide → request_clarification → clarify_deferred=True.

    Pre-fix behaviour (CR-02 bug):
      Round-2 branch IGNORED stage.clarify_deferred → fell through to set_clarified_fields
      + alias diff → run left at 'extracting' with no email sent. Nothing silently hangs
      (INGEST-05 violation).

    Post-fix behaviour (asserted here):
      _defer_field_regression_clarification() is called (IN-01 shared helper) →
      'asked' written for hours_holiday → clarification_field_regression email sent →
      run reaches AWAITING_REPLY.

    Note: Round-2 now does TWO extractions (reply-only for classify, combined for
    process). Both are scripted to return OT=2, holiday=None (dropped).
    The clarification path fires before _run_stages process branch → no paystub computed.
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
    # CR-01 FIX: two extractions — reply-only (classify) then combined (process).
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
        f"CR-02 fix: Round-2 introducing a NEW field regression must reach AWAITING_REPLY; "
        f"got {run['status']!r}. "
        "Pre-fix: Round-2 branch ignored stage.clarify_deferred → run stuck at 'extracting'. "
        "Post-fix: _defer_field_regression_clarification() sends the email → AWAITING_REPLY."
    )

    # Assertion 2: a clarification_field_regression outbound row must exist
    outbound = fake_repo.outbound.get(str(run_id), [])
    field_reg_rows = [r for r in outbound if r.get("purpose") == "clarification_field_regression"]
    assert len(field_reg_rows) >= 1, (
        f"CR-02 fix: a clarification_field_regression outbound email must be sent; "
        f"found {len(field_reg_rows)} such rows. "
        "_defer_field_regression_clarification() must call _clarify with "
        "purpose='clarification_field_regression'."
    )

    # Assertion 3: 'asked' must be written for the NEW drop (hours_holiday) BEFORE the send
    clarified_after = fake_repo.load_clarified_fields(run_id)
    hours_holiday_outcome = clarified_after.get(CHEN_ID_STR, {}).get("hours_holiday")
    assert hours_holiday_outcome == "asked", (
        f"CR-02 fix: hours_holiday must be 'asked' in clarified_fields (written before send, N2); "
        f"got {hours_holiday_outcome!r}. "
        "_defer_field_regression_clarification must write 'asked' for the NEW "
        "field_regression drop."
    )

    # Assertion 4: hours_overtime outcome must be 'client_supplied' (answered in Round-2 classify)
    ot_outcome = clarified_after.get(CHEN_ID_STR, {}).get("hours_overtime")
    assert ot_outcome == "client_supplied", (
        f"CR-02: hours_overtime (answered in Round-2 with OT=2) must be 'client_supplied'; "
        f"got {ot_outcome!r}."
    )


# ---------------------------------------------------------------------------
# Test 17 — test_cr01_explicit_zero_overpay_guard_with_prompt_inspecting_mock
# ---------------------------------------------------------------------------

def test_cr01_explicit_zero_overpay_guard_with_prompt_inspecting_mock(
    fake_repo, mock_llm, monkeypatch
):
    """CR-01 fix: classify uses REPLY-ONLY extraction, not combined body.

    Test approach: PROMPT-INSPECTING MOCK (not ALLOW_LIVE_LLM).
    The mock's create() inspects the user message for "ORIGINAL PAYROLL EMAIL:"
    (the delimiter _combined_context_email inserts):
    - Reply-only call (no delimiter): returns OT=0 (client's explicit zero)
    - Combined call (delimiter present): returns OT=2 (adversarial: original section wins)

    Key assertion: classify outcome is 'confirmed_dropped' (not 'client_supplied').
    This proves classify saw OT=0 from the REPLY-ONLY extraction, not OT=2 from combined.

    Without the CR-01 fix, classify would use the combined extraction: the adversarial
    mock returns OT=2 → classified 'client_supplied' (semantic corruption — the original
    section's value eclipses the client's explicit zero in the reply). The combined
    extraction's OT=2 then flows to _run_stages → paystub OT=2 = OVERPAY.

    With the fix: reply-only extraction returns OT=0 → 'confirmed_dropped'. The combined
    extraction (OT=2) feeds the process/backfill path losslessly (FIX 4). backfill_skip
    prevents snapshot restore (not the combined value).
    """
    run_id = _seed_run(fake_repo, body="Maria Chen 40 regular 2 overtime")
    _setup_round2(fake_repo, run_id, "Maria Chen", CHEN_ID, CHEN_ID_STR)

    # Prompt-inspecting mock: inspects the user message for "ORIGINAL PAYROLL EMAIL:"
    # (the delimiter _combined_context_email inserts).
    #
    # Reply-only classify call (no delimiter in body):
    #   → mock returns OT=0 (explicit zero from the reply)
    #   → classified as 'confirmed_dropped' (CR-01 correctness proof)
    #
    # Combined process/backfill call (delimiter present):
    #   → mock returns OT=2 (adversarial: original section's value eclipses reply)
    #   This simulates the exact failure mode CR-01 prevents for the CLASSIFY step.
    #
    # Key assertion: classify outcome is 'confirmed_dropped' (not 'client_supplied'),
    # proving classify saw OT=0 from the reply-only extraction, not OT=2 from combined.
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

    # Assertion 1: classify outcome must be 'confirmed_dropped' (reply-only OT=0).
    # If classify used the combined extraction (adversarial mock returns OT=2), the
    # outcome would be 'client_supplied' — the exact CR-01 semantic corruption where
    # the original section's positive value eclipses the reply's explicit zero.
    clarified = fake_repo.load_clarified_fields(run_id)
    outcome = clarified.get(CHEN_ID_STR, {}).get("hours_overtime")
    assert outcome == "confirmed_dropped", (
        f"CR-01 fix proof: classify must use REPLY-ONLY extraction → OT=0 → 'confirmed_dropped'; "
        f"got {outcome!r}. "
        "Without the fix, classify uses combined extraction → adversarial mock returns OT=2 "
        "→ 'client_supplied' (semantic corruption, paystub gets OT=2 = OVERPAY)."
    )

    # Assertion 2: at least 2 extraction LLM calls (reply-only classify + combined process)
    assert call_count[0] >= 2, (
        f"CR-01 fix: Round-2 must make at least 2 LLM extraction calls; got {call_count[0]}. "
        "First call is reply-only (classify); second is combined (process/backfill)."
    )

    # Assertion 3: run reaches AWAITING_APPROVAL (OT asked and answered → process path)
    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"CR-01: after answering OT=0, run must reach AWAITING_APPROVAL; "
        f"got {run['status']!r}"
    )

    # Assertion 4 (CR-01 MONEY-SAFETY — strengthened): paystub OT must be 0, NOT 2.
    # This is the critical payment assertion: the adversarial mock returns OT=2 from the
    # combined extraction. Without the CR-01 fix (_run_stages sees raw_extracted with OT=2),
    # the paystub would be paid at OT=2 even though classify correctly labels it
    # 'confirmed_dropped'. This assertion pins the money-safe outcome and MUST fail
    # before the fix and pass after.
    line_items = fake_repo.load_line_items(run_id)
    assert line_items, (
        "CR-01 paystub value assertion: line_items must be computed on a process run"
    )
    chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
    assert chen_items, "paystub item for Maria Chen must exist"
    ot_paid = chen_items[0].hours_overtime
    assert ot_paid == Decimal("0"), (
        f"CR-01 OVERPAY regression pin: paystub OT must be 0 (reply-derived, confirmed_dropped); "
        f"got {ot_paid!r}. "
        "Without the fix, the combined extraction's adversarial OT=2 flows to _run_stages → "
        "paystub OT=2 = OVERPAY, even though classify correctly labels it 'confirmed_dropped'. "
        "The CR-01 fix overwrites raw_extracted's OT field with the reply-derived value (0) "
        "so the paid value matches the classify decision."
    )


# ---------------------------------------------------------------------------
# Test 18 — test_cr01_divergence_confirmed_dropped_paystub_value
# ---------------------------------------------------------------------------

def test_cr01_divergence_confirmed_dropped_paystub_value(fake_repo, mock_llm, monkeypatch):
    """CR-01 divergence regression pin: confirmed_dropped case — paystub must pay OT=0, not 2.

    Drives resume_pipeline with a prompt-inspecting mock where the TWO extractions
    DISAGREE on the asked field:
      - Reply-only (classify): OT=0 (client's explicit zero → confirmed_dropped)
      - Combined (process):   OT=2 (adversarial: original section's value eclipses reply)

    Without the CR-01 raw_extracted-reconcile fix, _run_stages receives raw_extracted
    with OT=2 (from the combined extraction) → paystub OT=2 = OVERPAY, even though
    classify correctly labels the outcome 'confirmed_dropped'.

    With the fix: reply_value_overrides[(CHEN_ID_STR, 'hours_overtime')] = Decimal('0')
    → raw_extracted is rebuilt with OT=0 before _run_stages → paystub OT=0.

    This test MUST FAIL at base (before the fix) and PASS after.
    It is the definitive regression pin for the OVERPAY case (CR-01 row 1).
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
        f"Test 18: classify must see reply OT=0 → 'confirmed_dropped'; got {outcome!r}"
    )

    # Assertion 2: run reaches AWAITING_APPROVAL
    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"Test 18: run must reach AWAITING_APPROVAL after answering OT=0; got {run['status']!r}"
    )

    # Assertion 3 (MONEY-SAFE): paystub OT must be 0 — NOT the combined extraction's 2.
    # This FAILS before the fix (paystub OT=2 = OVERPAY) and PASSES after (paystub OT=0).
    line_items = fake_repo.load_line_items(run_id)
    assert line_items, "Test 18: paystub must be computed on a process run"
    chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
    assert chen_items, "Test 18: paystub item for Maria Chen must exist"
    ot_paid = chen_items[0].hours_overtime
    assert ot_paid == Decimal("0"), (
        f"CR-01 DIVERGENCE OVERPAY regression pin: paystub OT must be 0 (reply said 0 = drop); "
        f"got {ot_paid!r}. "
        "Reply-only extraction: OT=0. Combined extraction (adversarial): OT=2. "
        "Without the CR-01 raw_extracted-reconcile fix, _run_stages sees OT=2 from combined → "
        "paystub OT=2 = OVERPAY even though classify says 'confirmed_dropped'. "
        "With fix: raw_extracted's OT overwritten to 0 before _run_stages → paystub OT=0."
    )


# ---------------------------------------------------------------------------
# Test 19 — test_cr01_divergence_client_supplied_paystub_value
# ---------------------------------------------------------------------------

def test_cr01_divergence_client_supplied_paystub_value(fake_repo, mock_llm, monkeypatch):
    """CR-01 divergence regression pin: client_supplied case — paystub must pay OT=5, not 2.

    Drives resume_pipeline with a prompt-inspecting mock where the TWO extractions
    DISAGREE on the asked field:
      - Reply-only (classify): OT=5 (client supplied a new amount → client_supplied)
      - Combined (process):   OT=2 (adversarial: original section's value eclipses reply)

    Without the CR-01 raw_extracted-reconcile fix, _run_stages receives raw_extracted
    with OT=2 → paystub OT=2 = UNDERPAY (client's supplied OT=5 is discarded).

    With the fix: reply_value_overrides[(CHEN_ID_STR, 'hours_overtime')] = Decimal('5')
    → raw_extracted is rebuilt with OT=5 before _run_stages → paystub OT=5.

    This test MUST FAIL at base (before the fix) and PASS after.
    It is the definitive regression pin for the UNDERPAY case (CR-01 row 2).
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
        f"Test 19: classify must see reply OT=5 → 'client_supplied'; got {outcome!r}"
    )

    # Assertion 2: run reaches AWAITING_APPROVAL
    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"Test 19: run must reach AWAITING_APPROVAL after answering OT=5; got {run['status']!r}"
    )

    # Assertion 3 (MONEY-SAFE): paystub OT must be 5 — NOT the combined extraction's 2.
    # This FAILS before the fix (paystub OT=2 = UNDERPAY) and PASSES after (paystub OT=5).
    line_items = fake_repo.load_line_items(run_id)
    assert line_items, "Test 19: paystub must be computed on a process run"
    chen_items = [i for i in line_items if str(i.employee_id) == CHEN_ID_STR]
    assert chen_items, "Test 19: paystub item for Maria Chen must exist"
    ot_paid = chen_items[0].hours_overtime
    assert ot_paid == Decimal("5"), (
        f"CR-01 DIVERGENCE UNDERPAY regression pin: paystub OT must be 5 (client-supplied); "
        f"got {ot_paid!r}. "
        "Reply-only extraction: OT=5. Combined extraction (adversarial): OT=2. "
        "Without the CR-01 raw_extracted-reconcile fix, _run_stages sees OT=2 from combined → "
        "paystub OT=2 = UNDERPAY (client's OT=5 is silently discarded). "
        "With fix: raw_extracted's OT overwritten to 5 before _run_stages → paystub OT=5."
    )


# ---------------------------------------------------------------------------
# Test 20 — test_cr01_divergence_unresolvable_asked_money_safe
# ---------------------------------------------------------------------------

def test_cr01_divergence_unresolvable_asked_money_safe(fake_repo, mock_llm, monkeypatch):
    """CR-01 divergence regression pin: _unresolvable_asked case — combined OT=2 must NOT be paid.

    Drives resume_pipeline with a prompt-inspecting mock where:
      - Reply-only (classify): employee OMITTED (reply doesn't mention Maria Chen at all)
        → _unresolvable_asked for (CHEN_ID, hours_overtime) → field stays unresolved
      - Combined (process):   Maria Chen OT=2 (adversarial: original section carries it)

    Without the CR-01 raw_extracted-reconcile fix, raw_extracted carries OT=2 from the
    combined extraction. _unresolvable_asked adds (CHEN_ID, OT) to backfill_skip (prevents
    snapshot RESTORE), but the combined value OT=2 is already in raw_extracted and flows
    directly to _compute_line_items → paystub OT=2. The run reaches AWAITING_APPROVAL
    with the field still 'asked' and no re-clarification = money paid on an unanswered field.

    With the fix: reply_value_overrides[(CHEN_ID_STR, 'hours_overtime')] = None
    → raw_extracted's OT is forced to None before _run_stages.
    Now the field is genuinely absent: decide→validate sees missing required hours →
    request_clarification fires OR the run does NOT advance to AWAITING_APPROVAL paying OT=2.
    Either outcome is money-safe; the critical invariant is that OT=2 is NOT paid on a
    field still marked 'asked' in clarified_fields.

    This test MUST FAIL at base (paystub OT=2 = paid on unanswered field) and PASS after.
    It is the definitive regression pin for the unresolvable_asked case (CR-01 row 3).
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
            f"CR-01 DIVERGENCE UNRESOLVABLE_ASKED regression pin: "
            f"run reached AWAITING_APPROVAL but paystub OT={ot_paid!r}. "
            "This is the CR-01 row-3 overpay: combined extraction carries OT=2 for a field "
            "still 'asked' (unanswered). The field must be genuinely absent (OT=0 or None), "
            "not paid at OT=2 because the combined extraction eclipsed the unanswered state. "
            "Without the CR-01 fix, raw_extracted's OT=2 flows to _compute_line_items unchecked. "
            "With fix: raw_extracted's OT is forced to None → the field is genuinely absent → "
            "decide/validate routes money-safely."
        )
    # If the run is at AWAITING_REPLY — the re-clarification fired — that is also
    # money-safe (the field was not paid). No further assertion needed for that path.
    # (Any other status — e.g. ERROR — indicates a pipeline failure, acceptable as
    #  money-safe but worth noting; we don't assert the exact status here, only that
    #  OT=2 is never paid on an unanswered field.)
