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
from decimal import Decimal

import pytest

# This import WILL FAIL RED — _safe_to_learn_alias does not yet exist.
# Wave 4 Plan 07 Task 2 adds it to app/pipeline/reconcile_names.py.
from app.pipeline.reconcile_names import _safe_to_learn_alias  # noqa: F401 (RED: not yet implemented)

# This import provides get_outbound_message_id for idempotency stub tests.
from app.db.repo import get_outbound_message_id  # noqa: F401 (already exists; used in stubs)

from app.models.roster import Employee, Roster
from app.models.contracts import Decision
from app.models.roster import NameMatchResult


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
    """CLAR-04 finding #2 — Wave 3 implementation target: _clarify idempotency guard.

    When a clarification outbound row already exists for the run (i.e.,
    get_outbound_message_id returns a non-None message_id), re-triggering _clarify
    must NOT call send_outbound a second time.

    This test WILL FAIL RED until Wave 3 adds the idempotency guard to _clarify
    in app/pipeline/orchestrator.py.
    """
    import app.email.gateway as gateway_mod
    from app.pipeline.orchestrator import _clarify
    from app.models.contracts import InboundEmail
    from datetime import datetime, timezone

    send_calls: list = []

    def _fake_send_outbound(**kw):
        send_calls.append(kw)
        return f"<{uuid.uuid4()}@payroll-agent.local>"

    # Mock send_outbound to track calls
    monkeypatch.setattr(gateway_mod, "send_outbound", _fake_send_outbound, raising=True)

    # Mock get_outbound_message_id to return an EXISTING message_id (already sent)
    existing_mid = f"<{uuid.uuid4()}@payroll-agent.local>"
    import app.db.repo as repo_mod
    monkeypatch.setattr(
        repo_mod,
        "get_outbound_message_id",
        lambda run_id, purpose=None, conn=None: existing_mid,
        raising=False,
    )

    # Mock set_status (no-op for this test)
    monkeypatch.setattr(repo_mod, "set_status", lambda *a, **kw: None, raising=False)

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
        created_at=datetime.now(timezone.utc),
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
    _clarify(run_id, email, decision, roster, llm=None)

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
    import app.email.gateway as gateway_mod
    import app.db.repo as repo_mod
    from app.pipeline.orchestrator import _clarify
    from app.models.contracts import InboundEmail
    from datetime import datetime, timezone

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
        created_at=datetime.now(timezone.utc),
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
    _clarify(run_id, email, decision, roster, llm=None)

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
    set_alias_candidates IS called with {"Dave Reyez": None}.

    "Dave Reyez" does NOT appear in any employee's full_name or known_aliases in
    the D-01b roster, so it has zero candidates — genuinely unresolved.

    This test WILL FAIL RED until Wave 4 implements the alias capture in _clarify.
    """
    import app.email.gateway as gateway_mod
    import app.db.repo as repo_mod
    from app.pipeline.orchestrator import _clarify
    from app.models.contracts import InboundEmail
    from datetime import datetime, timezone

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
        created_at=datetime.now(timezone.utc),
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
    _clarify(run_id, email, decision, roster, llm=None)

    assert len(set_alias_candidates_calls) == 1, (
        "set_alias_candidates must be called exactly once for a single unambiguous "
        "unresolved token (Wave 4 implementation target: single-token happy path)"
    )
    candidates = set_alias_candidates_calls[0]["candidates"]
    assert "Dave Reyez" in candidates, (
        "set_alias_candidates must be called with the unresolved token as the key"
    )
    assert candidates["Dave Reyez"] is None, (
        "the value must be None at capture time — resolved_employee_id filled at "
        "resume (D-04: capture {original_token: None} before send)"
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
    import app.email.gateway as gateway_mod
    import app.db.repo as repo_mod
    from app.pipeline.orchestrator import _clarify
    from app.models.contracts import InboundEmail
    from datetime import datetime, timezone

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
        created_at=datetime.now(timezone.utc),
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
    _clarify(run_id, email, decision, roster, llm=None)

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
    import app.email.gateway as gateway_mod
    import app.db.repo as repo_mod
    from app.pipeline.orchestrator import _clarify
    from app.models.contracts import InboundEmail
    from datetime import datetime, timezone

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
        created_at=datetime.now(timezone.utc),
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

    _clarify(run_id, email, decision, roster, llm=None)

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
    """NEW-2 fix: pre-vs-post diff binding correctly handles multi-employee runs.

    Setup:
    - alias_candidates = {"Dave Reyez": None} (the single captured token)
    - PRE-resume reconciliation: maria already resolved + Dave Reyez unresolved
      pre_resolved_ids = {str(maria.id)}
    - POST-resume reconciliation: maria + david both resolved
      post_resolved_ids = {str(maria.id), str(david.id)}

    Expected: repo.set_alias_candidates is called with {"Dave Reyez": str(david.id)}
    The diff (post minus pre) = {str(david.id)} — the newly-resolved employee.

    Verification that "exactly one resolved match" would have FAILED here: there are
    2 resolved employees post-resume (maria + david), so any "count resolved == 1"
    check would silently no-op on a real multi-employee run.
    """
    import app.db.repo as repo_mod
    from app.pipeline.orchestrator import resume_pipeline
    from app.models.contracts import InboundEmail
    from datetime import datetime, timezone

    _biz_id = uuid.UUID("b0000002-0000-0000-0000-000000000002")
    _david_id = uuid.UUID("e0000003-0000-0000-0000-000000000003")
    _maria_id = uuid.UUID("e0000099-0000-0000-0000-000000000099")

    # alias_candidates: the single captured token (Dave Reyez → None, awaiting resolution)
    _alias_candidates = {"Dave Reyez": None}

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

    # Post-resume reconciliation: both maria and david resolved
    _post_reconciliation = [
        {
            "submitted_name": "Maria Perez",
            "matched_employee_id": str(_maria_id),
            "source": "exact",
            "resolved": True,
            "reason": "exact match",
        },
        {
            "submitted_name": "Dave Reyez",
            "matched_employee_id": str(_david_id),
            "source": "alias",
            "resolved": True,
            "reason": "known alias",
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

    from app.models.roster import Roster as _Roster
    _empty_roster = _Roster(business_id=_biz_id, employees=[])

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
        lambda *a, **kw: _empty_roster,
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

    # Mock _run_stages to simulate the post-resume state without running actual stages
    import app.pipeline.orchestrator as orch_mod
    monkeypatch.setattr(
        orch_mod,
        "_run_stages",
        lambda *a, **kw: None,
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
        created_at=datetime.now(timezone.utc),
    )

    resume_pipeline(run_id, inbound, llm=None)

    # Verify set_alias_candidates was called with the bound employee_id
    assert len(_set_alias_candidates_calls) == 1, (
        "set_alias_candidates must be called once at resume to bind the token "
        "to the newly-resolved employee (NEW-2 pre-vs-post diff fix). "
        "With 2 resolved employees post-resume (maria + david), 'exactly one "
        "resolved match' check would have silently no-oped — diff correctly "
        "isolates the NEWLY-resolved employee."
    )
    bound = _set_alias_candidates_calls[0]["candidates"]
    assert "Dave Reyez" in bound, "token 'Dave Reyez' must be in the bound candidates"
    assert bound["Dave Reyez"] == str(_david_id), (
        f"'Dave Reyez' must be bound to david.id ({_david_id}), got {bound['Dave Reyez']!r}. "
        "The diff (post minus pre) = {{str(david.id)}} isolates the newly-resolved employee."
    )


def test_resume_binding_skips_when_no_newly_resolved_employee(monkeypatch):
    """NEW-2 fix: alias binding is skipped when no new employee is resolved.

    Setup:
    - alias_candidates = {"Dave Reyez": None}
    - PRE-resume reconciliation: maria resolved (pre_resolved_ids = {str(maria.id)})
    - POST-resume reconciliation: same — maria still resolved, Dave Reyez still unresolved
      (the reply did not resolve any new employee)
    - newly_resolved_ids = post minus pre = {} (empty)

    Expected: repo.set_alias_candidates is NOT called (no binding to do).
    """
    import app.db.repo as repo_mod
    from app.pipeline.orchestrator import resume_pipeline
    from app.models.contracts import InboundEmail
    from datetime import datetime, timezone

    _biz_id = uuid.UUID("b0000002-0000-0000-0000-000000000002")
    _maria_id = uuid.UUID("e0000099-0000-0000-0000-000000000099")

    _alias_candidates = {"Dave Reyez": None}
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

    import app.pipeline.orchestrator as orch_mod
    monkeypatch.setattr(orch_mod, "_run_stages", lambda *a, **kw: None, raising=False)

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
        created_at=datetime.now(timezone.utc),
    )

    resume_pipeline(run_id, inbound, llm=None)

    assert len(_set_alias_candidates_calls) == 0, (
        "set_alias_candidates must NOT be called when no new employee was resolved "
        "by the reply (newly_resolved_ids = post minus pre = empty). "
        "The binding is skipped — no partial/incorrect bind (NEW-2 fix)."
    )
