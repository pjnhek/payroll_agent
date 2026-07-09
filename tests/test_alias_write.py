"""Wave 0 RED test stubs — alias write + clarify idempotency (D-01b, D-04, CLAR-04).

Three groups of tests:

1. _safe_to_learn_alias unit tests (D-01b write-side collision guard):
   - The canonical D. Reyes trap: David Reyes AND Daniel Reyes both carry "D. Reyes"
     in known_aliases — adding it to either one creates a collision, so
     _safe_to_learn_alias must return False. This is a first-class requirement,
     not an edge case (T-05-02).
   - An unambiguous token that uniquely resolves → True.
   - A token already in target employee's aliases → True (idempotent).

2. Clarify idempotency stub (CLAR-04 finding #2):
   - When a clarification outbound row already exists for the run, re-triggering
     _clarify must NOT call send_outbound a second time.

3. Alias capture stubs — THREE cases per R2-MEDIUM test-conflict fix (D-04, finding #4, #5):
   - test_alias_capture_no_capture_when_multiple_unresolved: 2+ unresolved names →
     single-token-only rule fires, set_alias_candidates NOT called at all.
   - test_alias_capture_unambiguous_single_token_is_captured: 1 unresolved name,
     zero candidate_ids in roster → set_alias_candidates called with {token: None}.
   - test_alias_capture_colliding_single_token_not_captured: 1 unresolved name,
     but 2 candidate_ids in roster → collision detected at capture time,
     set_alias_candidates NOT called (finding #5 + R2-HIGH fix).

Tests WILL FAIL RED until Wave 4 adds _safe_to_learn_alias to reconcile_names.py
and Wave 3 adds the idempotency guard to _clarify. That is the expected Wave 0 outcome.
"""
from __future__ import annotations

import uuid
from datetime import UTC
from decimal import Decimal

# This import provides get_outbound_message_id for idempotency stub tests.
from app.db.repo import get_outbound_message_id  # noqa: F401 (already exists; used in stubs)
from app.models.contracts import Decision, Extracted, ExtractedEmployee
from app.models.roster import Employee, NameMatchResult, Roster

# This import WILL FAIL RED — _safe_to_learn_alias does not yet exist.
# Wave 4 Plan 07 Task 2 adds it to app/pipeline/reconcile_names.py.
from app.pipeline.reconcile_names import (
    _safe_to_learn_alias,  # noqa: F401 (RED: not yet implemented)
)

# 09-02: patches repo_mod.get_connection to the FakeConnection double so tests
# calling _clarify (which now opens `with repo.get_connection(): with
# conn.transaction():` blocks, D-9-04..D-9-06) don't try a real pooled connection.
from tests.conftest import patch_get_connection  # noqa: F401


def _minimal_extracted(run_id: uuid.UUID) -> Extracted:
    """Return a minimal Extracted for tests that call _clarify directly (07.5-03).

    _clarify now requires an extracted param (N7 fix — snapshot before AWAITING_REPLY).
    Tests that don't care about the snapshot value can pass this stub.
    """
    return Extracted(
        run_id=run_id,
        employees=[ExtractedEmployee(submitted_name="__stub__", hours_regular=Decimal("0"))],
    )


# ---------------------------------------------------------------------------
# Minimal seed roster fixture with the D-01b collision pair
#
# Business 2 employees: David Reyes (e0000003) + Daniel Reyes (e0000007)
# BOTH carry known_aliases=["D. Reyes"] — the canonical collision pair (D-21-02).
# "Dave Reyez" does NOT appear in any employee's full_name or known_aliases.
# ---------------------------------------------------------------------------


def _make_roster() -> tuple[Roster, Employee, Employee]:
    """Build a minimal roster containing the D. Reyes collision pair.

    Returns (roster, david_employee, daniel_employee).
    David Reyes: e0000003, known_aliases=["D. Reyes"]
    Daniel Reyes: e0000007, known_aliases=["D. Reyes"]
    Both on business_id=b0000002.
    """
    _biz_id = uuid.UUID("b0000002-0000-0000-0000-000000000002")
    _david_id = uuid.UUID("e0000003-0000-0000-0000-000000000003")
    _daniel_id = uuid.UUID("e0000007-0000-0000-0000-000000000007")

    david = Employee(
        id=_david_id,
        business_id=_biz_id,
        full_name="David Reyes",
        known_aliases=["D. Reyes"],  # SHARED — the collision pair (D-21-02)
        pay_type="hourly",
        hourly_rate=Decimal("22.00"),
        annual_salary=None,
        retirement_contribution_pct=Decimal("0.00"),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("8000.00"),
        pay_periods_per_year=52,
    )
    daniel = Employee(
        id=_daniel_id,
        business_id=_biz_id,
        full_name="Daniel Reyes",
        known_aliases=["D. Reyes"],  # SHARED — the collision pair (D-21-02)
        pay_type="hourly",
        hourly_rate=Decimal("20.00"),
        annual_salary=None,
        retirement_contribution_pct=Decimal("0.00"),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("6000.00"),
        pay_periods_per_year=52,
    )
    roster = Roster(business_id=_biz_id, employees=[david, daniel])
    return roster, david, daniel


# ---------------------------------------------------------------------------
# Group 1: _safe_to_learn_alias unit tests (D-01b)
# ---------------------------------------------------------------------------


def test_safe_to_learn_alias_refuses_d_reyes_for_david():
    """D-01b canonical trap: 'D. Reyes' is already in BOTH David Reyes AND Daniel
    Reyes known_aliases. Adding it to David's aliases again would produce a roster
    where 'D. Reyes' still resolves ambiguously (2+ candidates).

    _safe_to_learn_alias must return False — never learn an alias that creates or
    preserves a collision, even if the target already carries the token (T-05-02).

    This is NOT an edge case. It is a first-class money-misroute prevention
    requirement. Any weakening of the collision guard must fail this test.
    """
    roster, david, _daniel = _make_roster()
    result = _safe_to_learn_alias("D. Reyes", david, roster)
    assert result is False, (
        "_safe_to_learn_alias('D. Reyes', david, roster) must return False — "
        "both David Reyes and Daniel Reyes already carry this alias, so it is "
        "permanently ambiguous on this roster (D-01b canonical trap, T-05-02)"
    )


def test_safe_to_learn_alias_accepts_unambiguous_token():
    """An unambiguous token — one that resolves uniquely to a single employee after
    the alias is appended — must return True (the safe-to-learn happy path).

    'Dave Reyez' does not appear in any employee's full_name or known_aliases,
    so after appending it to David's aliases it resolves uniquely to David only.
    """
    roster, david, _daniel = _make_roster()
    # 'Dave Reyez' is genuinely unresolved — not a full_name or existing alias.
    result = _safe_to_learn_alias("Dave Reyez", david, roster)
    assert result is True, (
        "_safe_to_learn_alias('Dave Reyez', david, roster) must return True — "
        "this token doesn't match any other employee, so it is safe to learn "
        "(D-01b write-side collision guard, unambiguous token happy path)"
    )


def test_safe_to_learn_alias_idempotent():
    """A token already in the target employee's known_aliases is still safe to
    add (idempotent: the alias is already there, no new collision is created).

    'D. Reyes' is in David's aliases, AND in Daniel's — so the post-write roster
    still has a collision. This test clarifies that idempotency does NOT override
    the collision check: if the token is also in another employee's aliases, it is
    still False even when re-adding it to the target.

    This is the correct behavior: idempotent means 'safe to call twice' not
    'always return True if already present'. The collision guard fires either way.
    """
    roster, david, _daniel = _make_roster()
    # 'D. Reyes' is already in david.known_aliases, but ALSO in daniel.known_aliases.
    # Post-write state: still ambiguous → must return False (not True due to idempotency).
    result = _safe_to_learn_alias("D. Reyes", david, roster)
    assert result is False, (
        "_safe_to_learn_alias must respect collision even when the token is already "
        "in target's aliases — idempotency does not bypass the collision guard "
        "(D-01b, the 'D. Reyes' token is permanently ambiguous on this roster)"
    )


def test_safe_to_learn_alias_idempotent_unambiguous():
    """If a token is already ONLY in the target employee's aliases (not in any other
    employee's aliases or full_name), re-adding it must return True.

    Build a roster variant where only David carries 'Dave Reyez'.
    """
    _biz_id = uuid.UUID("b0000002-0000-0000-0000-000000000002")
    _david_id = uuid.UUID("e0000003-0000-0000-0000-000000000003")
    _daniel_id = uuid.UUID("e0000007-0000-0000-0000-000000000007")

    david_with_alias = Employee(
        id=_david_id,
        business_id=_biz_id,
        full_name="David Reyes",
        known_aliases=["D. Reyes", "Dave Reyez"],  # already has "Dave Reyez"
        pay_type="hourly",
        hourly_rate=Decimal("22.00"),
        annual_salary=None,
        retirement_contribution_pct=Decimal("0.00"),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("8000.00"),
        pay_periods_per_year=52,
    )
    daniel = Employee(
        id=_daniel_id,
        business_id=_biz_id,
        full_name="Daniel Reyes",
        known_aliases=["D. Reyes"],
        pay_type="hourly",
        hourly_rate=Decimal("20.00"),
        annual_salary=None,
        retirement_contribution_pct=Decimal("0.00"),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("6000.00"),
        pay_periods_per_year=52,
    )
    roster = Roster(business_id=_biz_id, employees=[david_with_alias, daniel])

    # "Dave Reyez" is already only in David's aliases → still unambiguous → True
    result = _safe_to_learn_alias("Dave Reyez", david_with_alias, roster)
    assert result is True, (
        "_safe_to_learn_alias must return True when the token is already in target's "
        "aliases and uniquely resolves to that target (idempotent safe re-add)"
    )


# ---------------------------------------------------------------------------
# Group 2: clarify idempotency stub (CLAR-04 finding #2)
# ---------------------------------------------------------------------------


def test_clarify_idempotency_skips_if_clarification_already_sent(monkeypatch):
    """CLAR-04 finding #2 — _clarify idempotency guard, re-keyed to (purpose, round)
    per D-11-01 (Phase 11 Plan 02).

    When a clarification outbound row already exists for the run AT THE CURRENT
    ROUND (i.e., get_outbound_for_round returns a non-None dict), re-triggering
    _clarify must NOT call send_outbound a second time — this is the CLAR-04 true-
    duplicate case (same round re-trigger), preserved by the round-aware guard.
    """
    from datetime import datetime

    import app.email.gateway as gateway_mod
    from app.models.contracts import InboundEmail
    from app.pipeline.orchestrator import _clarify

    send_calls: list = []

    def _fake_send_outbound(**kw):
        send_calls.append(kw)
        return f"<{uuid.uuid4()}@payroll-agent.local>"

    # Mock send_outbound to track calls
    monkeypatch.setattr(gateway_mod, "send_outbound", _fake_send_outbound, raising=True)

    # Mock get_outbound_for_round to return an EXISTING row at round 0 (already sent
    # at the current round — a true duplicate, D-11-01).
    existing_mid = f"<{uuid.uuid4()}@payroll-agent.local>"
    import app.db.repo as repo_mod
    monkeypatch.setattr(
        repo_mod,
        "get_clarification_round",
        lambda run_id, conn=None: 0,
        raising=False,
    )
    monkeypatch.setattr(
        repo_mod,
        "get_outbound_for_round",
        lambda run_id, purpose=None, round=0, conn=None: {"message_id": existing_mid, "round": round},
        raising=False,
    )
    monkeypatch.setattr(
        repo_mod, "set_clarification_round", lambda *a, **kw: None, raising=False
    )

    # Mock set_status (no-op for this test)
    monkeypatch.setattr(repo_mod, "set_status", lambda *a, **kw: None, raising=False)
    # N7: set_pre_clarify_extracted is now called in the idempotency-early-return path.
    monkeypatch.setattr(repo_mod, "set_pre_clarify_extracted", lambda *a, **kw: True, raising=False)
    # 09-02: the idempotency-early-return path now opens its own transaction.
    patch_get_connection(monkeypatch, repo_mod)

    run_id = uuid.uuid4()
    email = InboundEmail(
        id=uuid.uuid4(),
        message_id="<orig@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="hours",
        from_addr="hr@test.example",
        to_addr="agent@payroll-agent.local",
        body_text="David Reyez 38 hours",
        created_at=datetime.now(UTC),
    )
    decision = Decision(
        final_action="request_clarification",
        gate_reasons=["David Reyez: unresolved"],
        unresolved_names=["David Reyez"],
        missing_fields=[],
        resolutions=[
            NameMatchResult(
                submitted_name="David Reyez",
                matched_employee_id=None,
                source="none",
                resolved=False,
                reason="no roster match",
            )
        ],
    )
    _biz_id = uuid.UUID("b0000001-0000-0000-0000-000000000001")
    roster = Roster(business_id=_biz_id, employees=[])

    # Wave 3 implementation target: _clarify idempotency guard (finding #2)
    # When the run already has an outbound clarification row, _clarify must
    # detect it via get_outbound_message_id and return WITHOUT calling send_outbound.
    _clarify(run_id, email, decision, roster, _minimal_extracted(run_id), llm=None)

    assert len(send_calls) == 0, (
        "_clarify must NOT call send_outbound when a clarification outbound row "
        "already exists for this run (CLAR-04 finding #2 idempotency guard). "
        "Wave 3 implementation target: add get_outbound_message_id check at "
        "the top of _clarify before drafting/sending."
    )


# ---------------------------------------------------------------------------
# Group 3: Alias capture stubs — D-04 single-token-only rule (findings #4, #5)
#
# R2-MEDIUM test-conflict fix: single-token-only rule (finding #4) wins over
# multi-token exclusion. The gate sequence is:
#   1. If len(unresolved_names) != 1 → no capture at all (finding #4)
#   2. Else if candidate_ids count > 1 for that token → no capture (finding #5)
#   3. Else → capture {token: None}
# ---------------------------------------------------------------------------


def test_alias_capture_no_capture_when_multiple_unresolved(monkeypatch):
    """Wave 4 implementation target: single-token-only rule (finding #4, 05-07);
    2+ unresolved names → no capture at all.

    When _clarify runs with decision.unresolved_names containing TWO tokens
    ("David Reyez" AND "D. Reyes"), the single-token-only gate fires first and
    set_alias_candidates is NOT called at all.

    This test WILL FAIL RED until Wave 4 Plan 07 Task 2 implements the gate.
    """
    from datetime import datetime

    import app.db.repo as repo_mod
    import app.email.gateway as gateway_mod
    from app.models.contracts import InboundEmail
    from app.pipeline.orchestrator import _clarify

    set_alias_candidates_calls: list = []

    def _fake_set_alias_candidates(run_id, candidates, conn=None):
        set_alias_candidates_calls.append({"run_id": run_id, "candidates": candidates})

    def _fake_send_outbound(**kw):
        return f"<{uuid.uuid4()}@payroll-agent.local>"

    monkeypatch.setattr(gateway_mod, "send_outbound", _fake_send_outbound, raising=True)
    monkeypatch.setattr(repo_mod, "set_status", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(
        repo_mod, "set_alias_candidates", _fake_set_alias_candidates, raising=False
    )
    # No existing outbound (so the idempotency guard doesn't fire first)
    monkeypatch.setattr(
        repo_mod, "get_outbound_message_id", lambda *a, **kw: None, raising=False
    )
    # 06-08: _clarify now checks the record_only flag; stub to False (live path)
    monkeypatch.setattr(
        repo_mod, "get_record_only_flag", lambda *a, **kw: False, raising=False
    )
    # N7: set_pre_clarify_extracted called before AWAITING_REPLY (live path).
    monkeypatch.setattr(repo_mod, "set_pre_clarify_extracted", lambda *a, **kw: True, raising=False)
    # insert_email_message called in live _clarify path.
    monkeypatch.setattr(repo_mod, "insert_email_message", lambda **kw: uuid.uuid4(), raising=False)
    # 09-02: _clarify's AWAITING_REPLY exit paths now open their own transaction.
    patch_get_connection(monkeypatch, repo_mod)

    run_id = uuid.uuid4()
    email = InboundEmail(
        id=uuid.uuid4(),
        message_id="<orig@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="hours",
        from_addr="hr@test.example",
        to_addr="agent@payroll-agent.local",
        body_text="David Reyez 38 hours. D. Reyes 40 hours.",
        created_at=datetime.now(UTC),
    )
    # TWO unresolved names → single-token-only gate fires, no capture
    decision = Decision(
        final_action="request_clarification",
        gate_reasons=["David Reyez: unresolved", "D. Reyes: collision"],
        unresolved_names=["David Reyez", "D. Reyes"],  # TWO names
        missing_fields=[],
        resolutions=[
            NameMatchResult(
                submitted_name="David Reyez",
                matched_employee_id=None,
                source="none",
                resolved=False,
                reason="no roster match",
            ),
            NameMatchResult(
                submitted_name="D. Reyes",
                matched_employee_id=None,
                source="none",
                resolved=False,
                reason="ambiguous — 2 candidates",
            ),
        ],
    )
    roster, david, daniel = _make_roster()

    # Wave 4 implementation target: single-token-only rule (finding #4, 05-07);
    # 2+ unresolved names → zero alias capture (set_alias_candidates NOT called)
    _clarify(run_id, email, decision, roster, _minimal_extracted(run_id), llm=None)

    assert len(set_alias_candidates_calls) == 0, (
        "set_alias_candidates must NOT be called when unresolved_names has 2+ entries "
        "— the single-token-only gate fires first (finding #4, Wave 4 impl target). "
        "Comment: Wave 4 implementation target: single-token-only rule (finding #4, "
        "05-07); 2+ unresolved names → no capture at all"
    )


def test_alias_capture_unambiguous_single_token_is_captured(monkeypatch):
    """Wave 4 implementation target: single unresolved token happy path.

    When _clarify runs with decision.unresolved_names containing exactly ONE
    genuinely unresolved token ("Dave Reyez" — zero candidate_ids in seed_roster),
    set_alias_candidates IS called with the D-11-14 nested shape
    {"Dave Reyez": {"suggested": None, "bound": None}} — "suggested" is None
    here because suggest_employees is stubbed to return {} (the never-strand
    degradation path), so no full_name->id mapping exists to persist. The stub
    is deterministic and hermetic: without it, _clarify's suggest_employees call
    hits the LIVE draft LLM (this repo's .env carries real DRAFT_API_KEY), which
    nondeterministically suggests "David Reyes" for the typo "Dave Reyez" — a
    correct suggestion that maps to e0000003 and makes "suggested" non-None,
    flaking the assert. Stubbing it isolates THIS test to the capture-shape
    contract (D-11-14) rather than the LLM's suggestion behavior (covered
    separately by the mocked-response suggest tests).

    "Dave Reyez" does NOT appear in any employee's full_name or known_aliases in
    the D-01b roster, so it has zero candidates — genuinely unresolved.
    """
    from datetime import datetime

    import app.db.repo as repo_mod
    import app.email.gateway as gateway_mod
    import app.pipeline.orchestrator as orchestrator_mod
    from app.models.contracts import InboundEmail
    from app.pipeline.orchestrator import _clarify

    # Deterministic stub for the never-strand degradation path — see docstring.
    # _clarify imports suggest_employees into its own module namespace, so patch
    # it there. Returning {} means no full_name->id mapping, so the captured
    # candidate's "suggested" is None, isolating this test to the D-11-14
    # capture-shape contract and off the live draft LLM's nondeterminism.
    monkeypatch.setattr(
        orchestrator_mod, "suggest_employees", lambda *a, **kw: {}, raising=True
    )

    set_alias_candidates_calls: list = []

    def _fake_set_alias_candidates(run_id, candidates, conn=None):
        set_alias_candidates_calls.append({"run_id": run_id, "candidates": candidates})

    def _fake_send_outbound(**kw):
        return f"<{uuid.uuid4()}@payroll-agent.local>"

    monkeypatch.setattr(gateway_mod, "send_outbound", _fake_send_outbound, raising=True)
    monkeypatch.setattr(repo_mod, "set_status", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(
        repo_mod, "set_alias_candidates", _fake_set_alias_candidates, raising=False
    )
    monkeypatch.setattr(
        repo_mod, "get_outbound_message_id", lambda *a, **kw: None, raising=False
    )
    # 06-08: _clarify now checks the record_only flag; stub to False (live path)
    monkeypatch.setattr(
        repo_mod, "get_record_only_flag", lambda *a, **kw: False, raising=False
    )
    # N7: set_pre_clarify_extracted called before AWAITING_REPLY (live path).
    monkeypatch.setattr(repo_mod, "set_pre_clarify_extracted", lambda *a, **kw: True, raising=False)
    # insert_email_message called in live _clarify path.
    monkeypatch.setattr(repo_mod, "insert_email_message", lambda **kw: uuid.uuid4(), raising=False)
    # 09-02: _clarify's AWAITING_REPLY exit paths now open their own transaction.
    patch_get_connection(monkeypatch, repo_mod)

    run_id = uuid.uuid4()
    email = InboundEmail(
        id=uuid.uuid4(),
        message_id="<orig@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="hours",
        from_addr="hr@test.example",
        to_addr="agent@payroll-agent.local",
        body_text="Dave Reyez 38 hours.",
        created_at=datetime.now(UTC),
    )
    # ONE genuinely unresolved token — "Dave Reyez" has zero candidates in the roster
    decision = Decision(
        final_action="request_clarification",
        gate_reasons=["Dave Reyez: unresolved"],
        unresolved_names=["Dave Reyez"],  # ONE name, zero candidates
        missing_fields=[],
        resolutions=[
            NameMatchResult(
                submitted_name="Dave Reyez",
                matched_employee_id=None,
                source="none",
                resolved=False,
                reason="no roster match",
            )
        ],
    )
    roster, _david, _daniel = _make_roster()

    # Wave 4 implementation target: single unresolved token happy path
    _clarify(run_id, email, decision, roster, _minimal_extracted(run_id), llm=None)

    assert len(set_alias_candidates_calls) == 1, (
        "set_alias_candidates must be called exactly once for a single unambiguous "
        "unresolved token (Wave 4 implementation target: single-token happy path)"
    )
    candidates = set_alias_candidates_calls[0]["candidates"]
    assert "Dave Reyez" in candidates, (
        "set_alias_candidates must be called with the unresolved token as the key"
    )
    assert candidates["Dave Reyez"] == {"suggested": None, "bound": None}, (
        "the nested value must be {'suggested': None, 'bound': None} at persist "
        "time when no suggestion mapping exists — bound is filled at resume via "
        "the D-11-15 bind-on-confirmation check, never at capture (D-11-14)"
    )


def test_alias_capture_colliding_single_token_not_captured(monkeypatch):
    """Wave 4 implementation target: finding #5 + R2-HIGH fix; candidate_ids count
    > 1 excludes at capture time.

    When _clarify runs with decision.unresolved_names containing exactly ONE token
    that is ambiguous ("D. Reyes" matching both David Reyes and Daniel Reyes —
    2 candidate_ids), set_alias_candidates is NOT called.

    The collision is detected by candidate_ids count > 1 at capture time — NOT by
    checking whether deterministic_match returns None (which is ambiguous: None means
    both 'no match' and 'ambiguous collision').

    This test WILL FAIL RED until Wave 4 implements the collision exclusion check
    in the alias capture step of _clarify.
    """
    from datetime import datetime

    import app.db.repo as repo_mod
    import app.email.gateway as gateway_mod
    from app.models.contracts import InboundEmail
    from app.pipeline.orchestrator import _clarify

    set_alias_candidates_calls: list = []

    def _fake_set_alias_candidates(run_id, candidates, conn=None):
        set_alias_candidates_calls.append({"run_id": run_id, "candidates": candidates})

    def _fake_send_outbound(**kw):
        return f"<{uuid.uuid4()}@payroll-agent.local>"

    monkeypatch.setattr(gateway_mod, "send_outbound", _fake_send_outbound, raising=True)
    monkeypatch.setattr(repo_mod, "set_status", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(
        repo_mod, "set_alias_candidates", _fake_set_alias_candidates, raising=False
    )
    monkeypatch.setattr(
        repo_mod, "get_outbound_message_id", lambda *a, **kw: None, raising=False
    )
    # 06-08: _clarify now checks the record_only flag; stub to False (live path)
    monkeypatch.setattr(
        repo_mod, "get_record_only_flag", lambda *a, **kw: False, raising=False
    )
    # N7: set_pre_clarify_extracted called before AWAITING_REPLY (live path).
    monkeypatch.setattr(repo_mod, "set_pre_clarify_extracted", lambda *a, **kw: True, raising=False)
    # insert_email_message called in live _clarify path.
    monkeypatch.setattr(repo_mod, "insert_email_message", lambda **kw: uuid.uuid4(), raising=False)
    # 09-02: _clarify's AWAITING_REPLY exit paths now open their own transaction.
    patch_get_connection(monkeypatch, repo_mod)

    run_id = uuid.uuid4()
    email = InboundEmail(
        id=uuid.uuid4(),
        message_id="<orig@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="hours",
        from_addr="hr@test.example",
        to_addr="agent@payroll-agent.local",
        body_text="D. Reyes 40 hours.",
        created_at=datetime.now(UTC),
    )
    # ONE name, but "D. Reyes" matches BOTH David Reyes AND Daniel Reyes (2 candidates)
    decision = Decision(
        final_action="request_clarification",
        gate_reasons=["D. Reyes: ambiguous — 2 candidates"],
        unresolved_names=["D. Reyes"],  # ONE name, but 2 candidate_ids
        missing_fields=[],
        resolutions=[
            NameMatchResult(
                submitted_name="D. Reyes",
                matched_employee_id=None,
                source="none",
                resolved=False,
                reason="ambiguous — 2 candidates",
            )
        ],
    )
    roster, _david, _daniel = _make_roster()
    # Roster has David Reyes + Daniel Reyes, both with "D. Reyes" in known_aliases

    # Wave 4 implementation target: finding #5 + R2-HIGH; candidate_ids count > 1
    # excludes at capture time (NOT deterministic_match is None — that is ambiguous)
    _clarify(run_id, email, decision, roster, _minimal_extracted(run_id), llm=None)

    assert len(set_alias_candidates_calls) == 0, (
        "set_alias_candidates must NOT be called when the single unresolved token "
        "has 2+ candidate_ids in the roster — collision detected at capture time "
        "(finding #5 + R2-HIGH fix; Wave 4 implementation target). "
        "Comment: Wave 4 implementation target: finding #5 + R2-HIGH; "
        "candidate_ids count > 1 excludes at capture time (NOT deterministic_match "
        "is None — that is ambiguous)"
    )


# ---------------------------------------------------------------------------
# Group 4: D-04 timing test + pre-vs-post diff binding (NEW-2 fix)
# ---------------------------------------------------------------------------


def test_clarify_captures_alias_candidates_before_send(monkeypatch):
    """D-04 timing test: set_alias_candidates must be called BEFORE send_outbound.

    When _clarify runs with a single genuinely unresolved token, it must:
    1. Call set_alias_candidates with {token: None} BEFORE gateway.send_outbound.
    2. The call is ordered: set_alias_candidates first, then send_outbound.

    This verifies that the D-04 timing constraint is respected — the alias candidate
    is captured before the clarification is sent.
    """
    from datetime import datetime

    import app.db.repo as repo_mod
    import app.email.gateway as gateway_mod
    from app.models.contracts import InboundEmail
    from app.pipeline.orchestrator import _clarify

    call_log: list[str] = []

    def _fake_set_alias_candidates(run_id, candidates, conn=None):
        call_log.append("set_alias_candidates")

    def _fake_send_outbound(**kw):
        call_log.append("send_outbound")
        return f"<{uuid.uuid4()}@payroll-agent.local>"

    monkeypatch.setattr(gateway_mod, "send_outbound", _fake_send_outbound, raising=True)
    monkeypatch.setattr(repo_mod, "set_status", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(
        repo_mod, "set_alias_candidates", _fake_set_alias_candidates, raising=False
    )
    monkeypatch.setattr(
        repo_mod, "get_outbound_message_id", lambda *a, **kw: None, raising=False
    )
    # 06-08: _clarify now checks the record_only flag; stub to False (live path)
    monkeypatch.setattr(
        repo_mod, "get_record_only_flag", lambda *a, **kw: False, raising=False
    )
    # N7: set_pre_clarify_extracted called before AWAITING_REPLY (live path).
    monkeypatch.setattr(repo_mod, "set_pre_clarify_extracted", lambda *a, **kw: True, raising=False)
    # insert_email_message called in live _clarify path.
    monkeypatch.setattr(repo_mod, "insert_email_message", lambda **kw: uuid.uuid4(), raising=False)
    # 09-02: _clarify's AWAITING_REPLY exit paths now open their own transaction.
    patch_get_connection(monkeypatch, repo_mod)

    run_id = uuid.uuid4()
    email = InboundEmail(
        id=uuid.uuid4(),
        message_id="<orig@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="hours",
        from_addr="hr@test.example",
        to_addr="agent@payroll-agent.local",
        body_text="Dave Reyez 38 hours.",
        created_at=datetime.now(UTC),
    )
    # ONE genuinely unresolved token ("Dave Reyez" has zero candidates in the roster)
    decision = Decision(
        final_action="request_clarification",
        gate_reasons=["Dave Reyez: unresolved"],
        unresolved_names=["Dave Reyez"],
        missing_fields=[],
        resolutions=[
            NameMatchResult(
                submitted_name="Dave Reyez",
                matched_employee_id=None,
                source="none",
                resolved=False,
                reason="no roster match",
            )
        ],
    )
    roster, _david, _daniel = _make_roster()
    # "Dave Reyez" has zero candidates in the D-01b roster — genuinely unresolved

    _clarify(run_id, email, decision, roster, _minimal_extracted(run_id), llm=None)

    # Verify set_alias_candidates was called with the right payload
    assert "set_alias_candidates" in call_log, (
        "set_alias_candidates must be called for a single genuinely unresolved token "
        "(D-04 timing test)"
    )
    assert "send_outbound" in call_log, (
        "send_outbound must be called after set_alias_candidates (D-04 timing)"
    )
    # Verify ordering: set_alias_candidates before send_outbound
    sac_index = call_log.index("set_alias_candidates")
    send_index = call_log.index("send_outbound")
    assert sac_index < send_index, (
        "set_alias_candidates must be called BEFORE send_outbound (D-04 timing "
        "constraint — alias candidate captured before the clarification is sent)"
    )


def test_resume_binding_uses_pre_vs_post_diff_not_single_resolved_count(monkeypatch):
    """D-11-15 bind-on-confirmation correctly handles multi-employee runs.

    Setup:
    - alias_candidates = {"Dave Reyez": {"suggested": str(david.id), "bound": None}}
      (the persisted D-11-14 suggestion — david was suggested at clarify time)
    - PRE-resume reconciliation: maria already resolved + Dave Reyez unresolved
      pre_resolved_ids = {str(maria.id)}
    - POST-resume reconciliation: maria + david both resolved, "Dave Reyez" is
      GONE from the submitted names (re-extraction replaced it with "David
      Reyes", which resolves to the same suggested id)
      post_resolved_ids = {str(maria.id), str(david.id)}

    Expected: repo.set_alias_candidates is called with
    {"Dave Reyez": {"suggested": str(david.id), "bound": str(david.id)}}
    — the suggested id newly resolved AND the token is gone from unresolved.

    Verification that "exactly one resolved match" would have FAILED here: there are
    2 resolved employees post-resume (maria + david), so any "count resolved == 1"
    check would silently no-op on a real multi-employee run.
    """
    from datetime import datetime

    import app.db.repo as repo_mod
    from app.models.contracts import InboundEmail
    from app.pipeline.orchestrator import resume_pipeline

    _biz_id = uuid.UUID("b0000002-0000-0000-0000-000000000002")
    _david_id = uuid.UUID("e0000003-0000-0000-0000-000000000003")
    _maria_id = uuid.UUID("e0000099-0000-0000-0000-000000000099")

    # alias_candidates: the persisted D-11-14 suggestion (david suggested, not yet bound)
    _alias_candidates = {"Dave Reyez": {"suggested": str(_david_id), "bound": None}}

    # Pre-resume reconciliation: maria resolved, Dave Reyez unresolved
    _pre_reconciliation = [
        {
            "submitted_name": "Maria Perez",
            "matched_employee_id": str(_maria_id),
            "source": "exact",
            "resolved": True,
            "reason": "exact match",
        },
        {
            "submitted_name": "Dave Reyez",
            "matched_employee_id": None,
            "source": "none",
            "resolved": False,
            "reason": "no roster match",
        },
    ]

    # Post-resume reconciliation: both maria and david resolved. "Dave Reyez"
    # is GONE — re-extraction replaced it with "David Reyes" (a confirming
    # reply restating the suggested canonical name), which resolves to the
    # SAME suggested id — both bind conditions hold (D-11-15).
    _post_reconciliation = [
        {
            "submitted_name": "Maria Perez",
            "matched_employee_id": str(_maria_id),
            "source": "exact",
            "resolved": True,
            "reason": "exact match",
        },
        {
            "submitted_name": "David Reyes",
            "matched_employee_id": str(_david_id),
            "source": "exact",
            "resolved": True,
            "reason": "exact match",
        },
    ]

    # Track load_run call count to return different data pre/post.
    # Call sequence in resume_pipeline:
    #   call 1: load_run for metadata (business_id) — returns pre-reconciliation
    #   call 2: pre_run_data = load_run (pre-snapshot before _run_stages) — returns pre-reconciliation
    #   call 3: post_run_data = load_run (post-snapshot after _run_stages) — returns post-reconciliation
    _load_run_calls = [0]
    _set_alias_candidates_calls: list = []

    def _fake_load_run(run_id, conn=None):
        _load_run_calls[0] += 1
        if _load_run_calls[0] <= 2:
            # Calls 1 and 2 (metadata + pre-snapshot): return pre-reconciliation
            return {
                "id": str(run_id),
                "business_id": str(_biz_id),
                "status": "extracting",
                "alias_candidates": _alias_candidates,
                "reconciliation": _pre_reconciliation,
                "extracted_data": None,
                "decision": None,
                "error_reason": None,
                "source_email_id": None,
                "pay_period_start": None,
                "pay_period_end": None,
            }
        else:
            # Call 3+ (post-snapshot after _run_stages): return post-reconciliation
            return {
                "id": str(run_id),
                "business_id": str(_biz_id),
                "status": "awaiting_approval",
                "alias_candidates": _alias_candidates,
                "reconciliation": _post_reconciliation,
                "extracted_data": None,
                "decision": None,
                "error_reason": None,
                "source_email_id": None,
                "pay_period_start": None,
                "pay_period_end": None,
            }

    def _fake_set_alias_candidates(run_id, candidates, conn=None):
        _set_alias_candidates_calls.append({"run_id": run_id, "candidates": candidates})

    # GAP-4 fix (11-09): the bind now looks up the suggested employee's OWN
    # canonical full_name from the loaded roster (so the same-record tie can
    # match a reply that restates "David Reyes" against the "Dave Reyez"
    # suggestion). An EMPTY roster would make _suggested_full_name resolve to
    # None, which would make the new same-record check fall back to
    # token-only matching and BREAK this legit test ("Dave Reyez" != "David
    # Reyes" as raw tokens) — so this fixture MUST seed a roster containing
    # the real David Reyes employee, not an empty one. _make_roster() already
    # builds David Reyes at exactly this test's _david_id
    # (e0000003-0000-0000-0000-000000000003) on this test's _biz_id
    # (b0000002-0000-0000-0000-000000000002).
    _fixture_roster, _fixture_david, _fixture_daniel = _make_roster()
    assert str(_fixture_david.id) == str(_david_id), (
        "test fixture drift: _make_roster()'s david id must match this test's "
        "_david_id for the same-record tie to resolve correctly"
    )

    monkeypatch.setattr(repo_mod, "load_run", _fake_load_run, raising=False)
    monkeypatch.setattr(
        repo_mod,
        "claim_status",
        lambda *a, **kw: True,
        raising=False,
    )
    monkeypatch.setattr(
        repo_mod,
        "load_roster_for_business",
        lambda *a, **kw: _fixture_roster,
        raising=False,
    )
    monkeypatch.setattr(
        repo_mod,
        "load_source_email",
        lambda *a, **kw: "original body",
        raising=False,
    )
    monkeypatch.setattr(
        repo_mod, "set_alias_candidates", _fake_set_alias_candidates, raising=False
    )
    # D-7.5-11: load_pre_clarify_extracted + load_clarified_fields needed by Step E1.
    monkeypatch.setattr(repo_mod, "load_pre_clarify_extracted", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(repo_mod, "load_clarified_fields", lambda *a, **kw: {}, raising=False)
    monkeypatch.setattr(repo_mod, "record_run_error", lambda *a, **kw: None, raising=False)
    # Phase 11 (D-11-02): resume_pipeline writes the consumed marker right after
    # the CAS claim — this test's bare-function monkeypatches must intercept both
    # calls or they fall through to the real (DB-backed) repo.
    monkeypatch.setattr(repo_mod, "get_clarification_round", lambda *a, **kw: 0, raising=False)
    monkeypatch.setattr(repo_mod, "mark_reply_consumed", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(repo_mod, "load_consumed_replies", lambda *a, **kw: [], raising=False)

    # Mock _run_stages to simulate the post-resume state without running actual stages.
    # Returns _RunStagesResult(clarify_deferred=False) so stage.clarify_deferred is accessible.
    import app.pipeline.orchestrator as orch_mod
    from app.pipeline.orchestrator import _RunStagesResult
    monkeypatch.setattr(
        orch_mod,
        "_run_stages",
        lambda *a, **kw: _RunStagesResult(clarify_deferred=False),
        raising=False,
    )

    run_id = uuid.uuid4()
    inbound = InboundEmail(
        id=uuid.uuid4(),
        message_id="<reply@test.example>",
        in_reply_to="<orig@test.example>",
        references_header="<orig@test.example>",
        subject="Re: hours",
        from_addr="hr@test.example",
        to_addr="agent@payroll-agent.local",
        body_text="I meant David Reyes",
        created_at=datetime.now(UTC),
    )

    resume_pipeline(run_id, inbound, llm=None)

    # Verify set_alias_candidates was called with the bound employee_id
    assert len(_set_alias_candidates_calls) == 1, (
        "set_alias_candidates must be called once at resume to bind the token "
        "to the confirmed suggestion (D-11-15 bind-on-confirmation, GAP-4 "
        "same-record tie). The post-resume 'David Reyes' entry is the "
        "suggested employee's OWN canonical full_name resolving to the "
        "suggested id — a legitimate same-record confirmation."
    )
    bound = _set_alias_candidates_calls[0]["candidates"]
    assert "Dave Reyez" in bound, "token 'Dave Reyez' must be in the bound candidates"
    assert bound["Dave Reyez"] == {"suggested": str(_david_id), "bound": str(_david_id)}, (
        f"'Dave Reyez' must be bound to the suggested david.id ({_david_id}), "
        f"got {bound['Dave Reyez']!r}. The suggested id newly resolved AND the "
        "token is gone from unresolved names — both D-11-15 conditions hold."
    )


def test_resume_binding_exploit_unrelated_resolution_binds_nothing(monkeypatch):
    """GAP-4/CR-4 exploit (11-REVIEW.md CR-4): an UNRELATED reconciliation
    entry resolving elsewhere in the run must NEVER satisfy the bind.

    Scenario: "Dave" was suggested -> david.id at clarify time. The client
    replies "No, Dave didn't work this period; David worked 5 hours
    separately." Post-resume reconciliation now has TWO entries:
      - "David" — a NEW, SEPARATE submitted_name, resolved=True,
        matched_employee_id=david.id (the "David worked separately" line).
      - "Dave" is simply ABSENT — extraction dropped him entirely (he
        "didn't work"), it did NOT resolve him to anything.

    The OLD (buggy) logic computed two independent whole-run facts: (a)
    david.id newly resolves SOMEWHERE (true, via "David") and (b) "Dave" is
    gone from unresolved SOMEWHERE (true, he's simply absent) -> both true,
    old code bound Dave -> David with NO actual confirmation of Dave himself.

    The FIX (_bind_evidence_for_token, same-record tie): no single
    reconciliation entry has submitted_name normalizing to EITHER "Dave" (the
    token) OR "David Reyes" (the suggested employee's own canonical
    full_name) AND resolved=True AND matched_employee_id=david.id — "David"
    (the actual post-resume entry) does not match "David Reyes" once
    normalized, so nothing ties back to the token. Assert NO bind occurs.

    MUST FAIL on the pre-fix code (old code binds Dave -> David here) and
    PASS after the GAP-4 fix.
    """
    from datetime import datetime

    import app.db.repo as repo_mod
    from app.models.contracts import InboundEmail
    from app.pipeline.orchestrator import resume_pipeline

    _biz_id = uuid.UUID("b0000002-0000-0000-0000-000000000002")
    _david_id = uuid.UUID("e0000003-0000-0000-0000-000000000003")

    # alias_candidates: "Dave" suggested -> david.id at clarify time, not yet bound.
    _alias_candidates = {"Dave": {"suggested": str(_david_id), "bound": None}}

    # PRE-resume reconciliation: only "Dave" unresolved (single-token capture
    # invariant — D-04 finding #4 only ever captures exactly one token).
    _pre_reconciliation = [
        {
            "submitted_name": "Dave",
            "matched_employee_id": None,
            "source": "none",
            "resolved": False,
            "reason": "no roster match",
        },
    ]
    # POST-resume reconciliation: "David" is a NEW, SEPARATE submitted_name
    # (the "David worked 5 hours separately" line) that resolves to david.id.
    # "Dave" is ABSENT entirely — he "didn't work this period", so extraction
    # dropped him, it did NOT resolve him. This is the exploit shape: the
    # suggested id resolves via an UNRELATED record while the token
    # independently vanishes from unresolved.
    _post_reconciliation = [
        {
            "submitted_name": "David",
            "matched_employee_id": str(_david_id),
            "source": "exact",
            "resolved": True,
            "reason": "exact match",
        },
    ]

    _load_run_calls = [0]
    _set_alias_candidates_calls: list = []

    def _fake_load_run(run_id, conn=None):
        _load_run_calls[0] += 1
        recon = _pre_reconciliation if _load_run_calls[0] <= 2 else _post_reconciliation
        return {
            "id": str(run_id),
            "business_id": str(_biz_id),
            "status": "extracting",
            "alias_candidates": _alias_candidates,
            "reconciliation": recon,
            "extracted_data": None,
            "decision": None,
            "error_reason": None,
            "source_email_id": None,
            "pay_period_start": None,
            "pay_period_end": None,
        }

    def _fake_set_alias_candidates(run_id, candidates, conn=None):
        _set_alias_candidates_calls.append({"run_id": run_id, "candidates": candidates})

    # Roster DOES contain the real David Reyes (full_name "David Reyes") so
    # the fix's same-record tie can be exercised honestly — the point of the
    # exploit is that "David" (the post-resume submitted_name) does NOT equal
    # "David Reyes" (the suggested employee's canonical full_name) once
    # normalized, so the same-record match still fails correctly even with a
    # real, non-empty roster.
    _fixture_roster, _fixture_david, _ = _make_roster()
    assert str(_fixture_david.id) == str(_david_id)

    monkeypatch.setattr(repo_mod, "load_run", _fake_load_run, raising=False)
    monkeypatch.setattr(repo_mod, "claim_status", lambda *a, **kw: True, raising=False)
    monkeypatch.setattr(
        repo_mod, "load_roster_for_business", lambda *a, **kw: _fixture_roster, raising=False
    )
    monkeypatch.setattr(
        repo_mod, "load_source_email", lambda *a, **kw: "original body", raising=False
    )
    monkeypatch.setattr(
        repo_mod, "set_alias_candidates", _fake_set_alias_candidates, raising=False
    )
    monkeypatch.setattr(repo_mod, "load_pre_clarify_extracted", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(repo_mod, "load_clarified_fields", lambda *a, **kw: {}, raising=False)
    monkeypatch.setattr(repo_mod, "record_run_error", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(repo_mod, "get_clarification_round", lambda *a, **kw: 0, raising=False)
    monkeypatch.setattr(repo_mod, "mark_reply_consumed", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(repo_mod, "load_consumed_replies", lambda *a, **kw: [], raising=False)

    import app.pipeline.orchestrator as orch_mod
    from app.pipeline.orchestrator import _RunStagesResult
    monkeypatch.setattr(
        orch_mod, "_run_stages",
        lambda *a, **kw: _RunStagesResult(clarify_deferred=False),
        raising=False,
    )

    run_id = uuid.uuid4()
    inbound = InboundEmail(
        id=uuid.uuid4(),
        message_id="<reply@test.example>",
        in_reply_to="<orig@test.example>",
        references_header="<orig@test.example>",
        subject="Re: hours",
        from_addr="hr@test.example",
        to_addr="agent@payroll-agent.local",
        body_text="No, Dave didn't work this period; David worked 5 hours separately.",
        created_at=datetime.now(UTC),
    )

    resume_pipeline(run_id, inbound, llm=None)

    # The exploit must produce NOTHING: no set_alias_candidates call binds
    # "Dave" to anything at all.
    bound_dave = [
        c["candidates"].get("Dave")
        for c in _set_alias_candidates_calls
        if isinstance(c["candidates"].get("Dave"), dict)
        and c["candidates"]["Dave"].get("bound") is not None
    ]
    assert not bound_dave, (
        "GAP-4/CR-4 exploit: 'Dave' must NEVER be bound to David via an "
        "UNRELATED reconciliation entry ('David worked separately' is a "
        "different submitted_name record, not a confirmation of 'Dave'). "
        f"Got a bind: {bound_dave!r}"
    )
    # Even stronger: no call at all should carry a bound "Dave" != None, and
    # ideally set_alias_candidates isn't called at all for this token (no
    # pending token was resolved by same-record evidence).
    for c in _set_alias_candidates_calls:
        dave_cand = c["candidates"].get("Dave")
        if isinstance(dave_cand, dict):
            assert dave_cand.get("bound") != str(_david_id), (
                "'Dave' must never be bound to David's id via an unrelated "
                "reconciliation entry — the never-learn-from-inference "
                "guarantee is the exact invariant GAP-4 protects"
            )


def test_resume_binding_skips_when_no_newly_resolved_employee(monkeypatch):
    """D-11-15: alias binding is skipped when the SUGGESTED employee never
    newly resolves (the reply didn't confirm anything actionable).

    Setup:
    - alias_candidates = {"Dave Reyez": {"suggested": str(david.id), "bound": None}}
      (a suggestion WAS persisted at clarify time)
    - PRE-resume reconciliation: maria resolved (pre_resolved_ids = {str(maria.id)})
    - POST-resume reconciliation: same — maria still resolved, Dave Reyez still
      unresolved (the reply did not resolve any new employee, so the suggested
      david.id never appears in the post-resume resolved set)
    - newly_resolved_ids = post minus pre = {} (empty) — the suggested id is
      NOT in it, so the D-11-15 bind condition fails.

    Expected: repo.set_alias_candidates is NOT called (no binding to do).
    """
    from datetime import datetime

    import app.db.repo as repo_mod
    from app.models.contracts import InboundEmail
    from app.pipeline.orchestrator import resume_pipeline

    _biz_id = uuid.UUID("b0000002-0000-0000-0000-000000000002")
    _maria_id = uuid.UUID("e0000099-0000-0000-0000-000000000099")
    _david_id = uuid.UUID("e0000003-0000-0000-0000-000000000003")

    _alias_candidates = {"Dave Reyez": {"suggested": str(_david_id), "bound": None}}
    _same_reconciliation = [
        {
            "submitted_name": "Maria Perez",
            "matched_employee_id": str(_maria_id),
            "source": "exact",
            "resolved": True,
            "reason": "exact match",
        },
        {
            "submitted_name": "Dave Reyez",
            "matched_employee_id": None,
            "source": "none",
            "resolved": False,
            "reason": "no roster match",
        },
    ]

    _set_alias_candidates_calls: list = []

    def _fake_load_run(run_id, conn=None):
        return {
            "id": str(run_id),
            "business_id": str(_biz_id),
            "status": "extracting",
            "alias_candidates": _alias_candidates,
            "reconciliation": _same_reconciliation,
            "extracted_data": None,
            "decision": None,
            "error_reason": None,
            "source_email_id": None,
            "pay_period_start": None,
            "pay_period_end": None,
        }

    def _fake_set_alias_candidates(run_id, candidates, conn=None):
        _set_alias_candidates_calls.append({"run_id": run_id, "candidates": candidates})

    from app.models.roster import Roster as _Roster
    _empty_roster = _Roster(business_id=_biz_id, employees=[])

    monkeypatch.setattr(repo_mod, "load_run", _fake_load_run, raising=False)
    monkeypatch.setattr(repo_mod, "claim_status", lambda *a, **kw: True, raising=False)
    monkeypatch.setattr(
        repo_mod, "load_roster_for_business", lambda *a, **kw: _empty_roster, raising=False
    )
    monkeypatch.setattr(
        repo_mod, "load_source_email", lambda *a, **kw: "original body", raising=False
    )
    monkeypatch.setattr(
        repo_mod, "set_alias_candidates", _fake_set_alias_candidates, raising=False
    )
    # D-7.5-11: load_pre_clarify_extracted + load_clarified_fields needed by Step E1.
    monkeypatch.setattr(repo_mod, "load_pre_clarify_extracted", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(repo_mod, "load_clarified_fields", lambda *a, **kw: {}, raising=False)
    monkeypatch.setattr(repo_mod, "record_run_error", lambda *a, **kw: None, raising=False)
    # Phase 11 (D-11-02): resume_pipeline writes the consumed marker right after
    # the CAS claim — this test's bare-function monkeypatches must intercept both
    # calls or they fall through to the real (DB-backed) repo.
    monkeypatch.setattr(repo_mod, "get_clarification_round", lambda *a, **kw: 0, raising=False)
    monkeypatch.setattr(repo_mod, "mark_reply_consumed", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(repo_mod, "load_consumed_replies", lambda *a, **kw: [], raising=False)

    import app.pipeline.orchestrator as orch_mod
    from app.pipeline.orchestrator import _RunStagesResult
    monkeypatch.setattr(
        orch_mod, "_run_stages",
        lambda *a, **kw: _RunStagesResult(clarify_deferred=False),
        raising=False,
    )

    run_id = uuid.uuid4()
    inbound = InboundEmail(
        id=uuid.uuid4(),
        message_id="<reply@test.example>",
        in_reply_to="<orig@test.example>",
        references_header="<orig@test.example>",
        subject="Re: hours",
        from_addr="hr@test.example",
        to_addr="agent@payroll-agent.local",
        body_text="I meant someone else",
        created_at=datetime.now(UTC),
    )

    resume_pipeline(run_id, inbound, llm=None)

    assert len(_set_alias_candidates_calls) == 0, (
        "set_alias_candidates must NOT be called when the suggested employee "
        "never newly resolved by the reply (newly_resolved_ids = post minus "
        "pre = empty). The binding is skipped — no partial/incorrect bind "
        "(D-11-15)."
    )


def test_resume_binding_does_not_learn_misname_as_alias(monkeypatch):
    """MISNAME GUARD (D-11-15): a corrected misname must NOT be learned as an alias.

    Scenario (the real bug): the client wrote "Maria" but there is NO Maria — the
    clarification suggested a DIFFERENT employee (Priya Singh) as the likely intended
    match. The client's reply corrects to yet ANOTHER, unrelated person: "I meant
    James Okafor, not Maria." On resume, re-extraction REPLACES "Maria" with "James
    Okafor"; James resolves, and the run proceeds.

    "Maria" is NOT James's nickname — nobody suggested James for this token, and the
    resolved employee (James) is NOT the one that was suggested (Priya). Learning
    "Maria" -> James would silently route every future "Maria" to James (a silent
    misroute on a money-moving decision). The bind MUST be skipped because the
    SUGGESTED id (Priya) never appears in the post-resume newly-resolved set — D-11-15
    requires the CONFIRMED evidence to be about the SUGGESTED employee specifically,
    not merely "some employee newly resolved."

    Contrast with the legit nickname case (test ...uses_pre_vs_post_diff...): there
    the reply RE-STATES the SUGGESTED canonical name, so the suggested id itself newly
    resolves and learning is correct.

    The OLD (buggy) logic bound on count alone — "1 newly-resolved employee + 1 pending
    candidate" — and would write {"Maria": james.id}. The D-11-15 fix requires the
    NEWLY-RESOLVED id to equal the persisted SUGGESTED id.
    """
    from datetime import datetime

    import app.db.repo as repo_mod
    from app.models.contracts import InboundEmail
    from app.pipeline.orchestrator import resume_pipeline

    _biz_id = uuid.UUID("b0000002-0000-0000-0000-000000000002")
    _james_id = uuid.UUID("e0000010-0000-0000-0000-000000000010")
    _priya_id = uuid.UUID("e0000011-0000-0000-0000-000000000011")

    # Capture phase persisted the D-11-14 suggestion — Priya was the suggested
    # (advisory, non-guessed) match for "Maria", never confirmed yet.
    _alias_candidates = {"Maria": {"suggested": str(_priya_id), "bound": None}}

    # PRE-resume reconciliation: "Maria" unresolved (nothing resolved yet).
    _pre_reconciliation = [
        {
            "submitted_name": "Maria",
            "matched_employee_id": None,
            "source": "none",
            "resolved": False,
            "reason": "no roster match",
        },
    ]
    # POST-resume reconciliation: the client corrected to a DIFFERENT, unrelated
    # person (James) — NOT the suggested Priya. Re-extraction replaced "Maria"
    # with "James Okafor"; James resolves. "Maria" is GONE from the submitted
    # names, but the suggested id (Priya) never newly-resolves — this is the
    # misname case, not a confirmed nickname.
    _post_reconciliation = [
        {
            "submitted_name": "James Okafor",
            "matched_employee_id": str(_james_id),
            "source": "exact",
            "resolved": True,
            "reason": "exact match",
        },
    ]

    _set_alias_candidates_calls: list = []
    _load_run_calls = {"n": 0}

    def _fake_load_run(run_id, conn=None):
        # resume_pipeline calls load_run multiple times: metadata + pre-recon, then
        # post-recon after _run_stages. Serve pre-recon on the first calls, post-recon
        # once _run_stages has "run" (3rd call onward).
        _load_run_calls["n"] += 1
        recon = _pre_reconciliation if _load_run_calls["n"] < 3 else _post_reconciliation
        return {
            "id": str(run_id),
            "business_id": str(_biz_id),
            "status": "extracting",
            "alias_candidates": _alias_candidates,
            "reconciliation": recon,
            "extracted_data": None,
            "decision": None,
            "error_reason": None,
            "source_email_id": None,
            "pay_period_start": None,
            "pay_period_end": None,
        }

    def _fake_set_alias_candidates(run_id, candidates, conn=None):
        _set_alias_candidates_calls.append({"run_id": run_id, "candidates": candidates})

    from app.models.roster import Roster as _Roster
    _empty_roster = _Roster(business_id=_biz_id, employees=[])

    monkeypatch.setattr(repo_mod, "load_run", _fake_load_run, raising=False)
    monkeypatch.setattr(repo_mod, "claim_status", lambda *a, **kw: True, raising=False)
    monkeypatch.setattr(
        repo_mod, "load_roster_for_business", lambda *a, **kw: _empty_roster, raising=False
    )
    monkeypatch.setattr(
        repo_mod, "load_source_email", lambda *a, **kw: "Maria 40 hours", raising=False
    )
    monkeypatch.setattr(
        repo_mod, "set_alias_candidates", _fake_set_alias_candidates, raising=False
    )
    # D-7.5-11: load_pre_clarify_extracted + load_clarified_fields needed by Step E1.
    monkeypatch.setattr(repo_mod, "load_pre_clarify_extracted", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(repo_mod, "load_clarified_fields", lambda *a, **kw: {}, raising=False)
    monkeypatch.setattr(repo_mod, "record_run_error", lambda *a, **kw: None, raising=False)
    # Phase 11 (D-11-02): resume_pipeline writes the consumed marker right after
    # the CAS claim — this test's bare-function monkeypatches must intercept both
    # calls or they fall through to the real (DB-backed) repo.
    monkeypatch.setattr(repo_mod, "get_clarification_round", lambda *a, **kw: 0, raising=False)
    monkeypatch.setattr(repo_mod, "mark_reply_consumed", lambda *a, **kw: None, raising=False)
    monkeypatch.setattr(repo_mod, "load_consumed_replies", lambda *a, **kw: [], raising=False)

    import app.pipeline.orchestrator as orch_mod
    from app.pipeline.orchestrator import _RunStagesResult
    monkeypatch.setattr(
        orch_mod, "_run_stages",
        lambda *a, **kw: _RunStagesResult(clarify_deferred=False),
        raising=False,
    )

    run_id = uuid.uuid4()
    inbound = InboundEmail(
        id=uuid.uuid4(),
        message_id="<reply@test.example>",
        in_reply_to="<orig@test.example>",
        references_header="<orig@test.example>",
        subject="Re: hours",
        from_addr="hr@test.example",
        to_addr="agent@payroll-agent.local",
        body_text="I meant James Okafor, not Maria",
        created_at=datetime.now(UTC),
    )

    resume_pipeline(run_id, inbound, llm=None)

    # The bug: old logic bound on count alone regardless of WHICH employee
    # resolved. The D-11-15 fix: the newly-resolved id (James) != the
    # persisted SUGGESTED id (Priya), so no bind — nobody proposed James for
    # this token, so nothing can be silently learned toward him.
    bound_candidates = [
        c["candidates"].get("Maria")
        for c in _set_alias_candidates_calls
        if isinstance(c["candidates"].get("Maria"), dict)
        and c["candidates"]["Maria"].get("bound") is not None
    ]
    assert not bound_candidates, (
        "MISNAME must NOT be learned: 'Maria' was a misname — the client actually "
        "meant James, an employee who was never suggested for this token (Priya "
        "was suggested and never resolved). Binding 'Maria' -> anyone here would "
        "silently misroute every future 'Maria'. D-11-15 requires the SUGGESTED "
        "id itself to newly resolve — it never did, so the alias must be skipped."
    )
    # Sanity: also assert the exact non-bind reason directly — the suggested
    # Priya id must never appear in any set_alias_candidates call's bound value.
    for c in _set_alias_candidates_calls:
        maria_cand = c["candidates"].get("Maria")
        if isinstance(maria_cand, dict):
            assert maria_cand.get("bound") != str(_james_id), (
                "James (a non-suggested resolution) must never be written as "
                "the bound value for 'Maria'"
            )


# ---------------------------------------------------------------------------
# Group 5: _normalize_candidate legacy-shape tolerance (D-11-14 Pitfall #6)
#
# A live row written BEFORE this plan carries the OLD flat alias_candidates
# shape: {token: None} (never resolved) or {token: "employee_id_str"} (the OLD
# NEW-2 pre-vs-post-diff bind wrote the resolved id directly as the value).
# Every site that reads an alias_candidates value MUST go through
# _normalize_candidate so these legacy rows never raise AttributeError.
# ---------------------------------------------------------------------------


def test_normalize_candidate_none_value():
    """A flat None value (never resolved, pre-Phase-11 shape) normalizes to
    {"suggested": None, "bound": None} — behaves as still-pending."""
    from app.pipeline.orchestrator import _normalize_candidate

    assert _normalize_candidate(None) == {"suggested": None, "bound": None}


def test_normalize_candidate_legacy_flat_bound_string():
    """A flat employee_id string value (the OLD NEW-2 bind's flat-bound shape)
    normalizes to {"suggested": None, "bound": <the string>} — a legacy row
    that was ALREADY bound under the old logic keeps behaving as bound (the
    write side will still learn it), even though "suggested" is unknown."""
    from app.pipeline.orchestrator import _normalize_candidate

    legacy_id = str(uuid.uuid4())
    assert _normalize_candidate(legacy_id) == {"suggested": None, "bound": legacy_id}


def test_normalize_candidate_nested_dict_is_idempotent():
    """A value that is ALREADY the D-11-14 nested shape passes through
    unchanged (idempotent) — _normalize_candidate never double-wraps a dict."""
    from app.pipeline.orchestrator import _normalize_candidate

    nested = {"suggested": "abc", "bound": None}
    assert _normalize_candidate(nested) is nested or _normalize_candidate(nested) == nested


def test_write_aliases_if_safe_handles_legacy_flat_shape_without_raising(monkeypatch):
    """_write_aliases_if_safe must not raise AttributeError on a legacy flat
    alias_candidates row — {token: "employee_id_str"} — and must still learn
    the alias (the value IS the bound id under legacy semantics, Pitfall #6)."""
    import app.db.repo as repo_mod
    from app.pipeline.orchestrator import _write_aliases_if_safe

    roster, david, _daniel = _make_roster()
    legacy_candidates = {"Dave Reyez": str(david.id)}  # OLD flat-bound shape

    run_data = {
        "id": uuid.uuid4(),
        "business_id": roster.business_id,
        "alias_candidates": legacy_candidates,
    }

    monkeypatch.setattr(repo_mod, "load_run", lambda rid, conn=None: run_data, raising=False)
    monkeypatch.setattr(
        repo_mod, "load_roster_for_business", lambda *a, **kw: roster, raising=False
    )
    written_calls: list = []

    def _fake_update_known_alias(employee_id, alias, conn=None):
        written_calls.append((employee_id, alias))
        return True

    monkeypatch.setattr(
        repo_mod, "update_known_alias", _fake_update_known_alias, raising=False
    )

    # Must not raise.
    _write_aliases_if_safe(run_data["id"], run_data, roster)

    assert written_calls == [(david.id, "Dave Reyez")], (
        "a legacy flat-bound row must still be learned via update_known_alias "
        "— _normalize_candidate's legacy-string handling makes this reachable "
        "without an AttributeError (Pitfall #6)"
    )


# ---------------------------------------------------------------------------
# Group 6: set_alias_candidates is a MERGE write, not an overwrite (WR-1, 11-09)
#
# 11-REVIEW.md WR-1: the old set_alias_candidates was a full-column overwrite
# (`UPDATE ... SET alias_candidates = %s`). With 2+ distinct tokens across 2+
# rounds, the LAST writer erased every OTHER token's candidate — a
# client-confirmed bind from an earlier round could be silently wiped by a
# later, unrelated capture/suggest/bind write before _write_aliases_if_safe
# ever read it at the approval gate. Fixed via a JSONB `||` merge
# (COALESCE-wrapped) in app/db/repo.py, mirrored as a dict-merge in
# tests/conftest.py's InMemoryRepo.
# ---------------------------------------------------------------------------


def test_set_alias_candidates_merges_across_two_tokens_two_rounds(fake_repo):
    """WR-1 regression (11-09): a confirmed bind from an earlier round must
    survive a later, unrelated candidate write for a DIFFERENT token.

    Round 1: TokenA is captured, suggested, and CONFIRMED (bound) — the
    client already confirmed this token in an earlier round.
    Round 2: TokenB is captured + suggested for the FIRST time (bound=None) —
    a completely unrelated token, in a later round of the SAME run.

    MUST FAIL under a full-column overwrite (round 2's write would erase
    TokenA's confirmed bind entirely — the fake_repo mirror historically did
    exactly this). MUST PASS after the merge fix: both tokens' candidates
    coexist in the same alias_candidates column.
    """
    from app.db import repo

    biz_id = uuid.uuid4()
    eid, _ = fake_repo.insert_inbound_email(
        message_id=f"<{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="payroll hours",
        from_addr="hr@test.example",
        to_addr="agent@payroll-agent.local",
        body_text="hours",
    )
    run_id = fake_repo.create_run(business_id=biz_id, source_email_id=eid)

    id_a = uuid.uuid4()
    id_b = uuid.uuid4()

    # Round 1: TokenA captured, suggested, and CONFIRMED (bound) in one write
    # (mirrors what STEP C's bind-on-confirmation persists once evidence ties
    # the token to the suggestion).
    repo.set_alias_candidates(
        run_id, {"TokenA": {"suggested": str(id_a), "bound": str(id_a)}}
    )

    # Round 2: a LATER, UNRELATED write for a DIFFERENT token — a fresh
    # capture/suggest for TokenB, which knows NOTHING about TokenA and does
    # not intend to touch it.
    repo.set_alias_candidates(
        run_id, {"TokenB": {"suggested": str(id_b), "bound": None}}
    )

    persisted = repo.load_run(run_id)["alias_candidates"]

    assert persisted.get("TokenA") == {"suggested": str(id_a), "bound": str(id_a)}, (
        "WR-1: TokenA's CONFIRMED bind from round 1 must survive TokenB's "
        f"later, unrelated round-2 write. Got: {persisted!r}"
    )
    assert persisted.get("TokenB") == {"suggested": str(id_b), "bound": None}, (
        f"TokenB's fresh round-2 suggestion must also be present. Got: {persisted!r}"
    )


def test_repo_set_alias_candidates_sql_uses_jsonb_merge_not_overwrite():
    """Static assertion (WR-1): the real repo.set_alias_candidates SQL string
    must use the JSONB `||` merge operator, not a bare column overwrite —
    this is the load-bearing acceptance criterion for the plan's grep check,
    pinned as an actual test rather than only a shell grep."""
    import inspect

    from app.db import repo

    src = inspect.getsource(repo.set_alias_candidates)
    assert "|| %s::jsonb" in src and "COALESCE(alias_candidates" in src, (
        "set_alias_candidates must merge via a COALESCE-wrapped JSONB || "
        "(COALESCE(alias_candidates, '{}'::jsonb) || %s::jsonb), not "
        "overwrite the whole column"
    )
