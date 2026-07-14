"""Clarify-round hours safety — the identity bridge and the display-only change record.

WHY THIS LIVES IN ITS OWN MODULE (NOT tests/test_resume_pipeline.py):
tests/test_resume_pipeline.py carries a MODULE-LEVEL conditional-skip marker gated on
`os.environ.get("DATABASE_URL")`. That marker silently skips the ENTIRE module —
including any new test added to it — whenever DATABASE_URL is unset at collection time.
These fixtures are genuinely hermetic (fake_repo + mock_llm only, no live DB/LLM) and
must run unconditionally offline, so this module carries NO module-level
conditional-skip marker of any kind. A guard that silently skips is not a guard.

WHAT THIS MODULE PROVES (the hole found in live run e6fa8643):

`detect_field_regression` builds its ORIGINAL-side identity map from `prior_matches`
filtered to `resolved`. The employee a NAME clarification is about was, by definition,
UNRESOLVED in the prior round — so that employee is structurally absent from the
original-side map, and a dropped hours line on the clarification reply ("Sandy 20r/10ot"
-> "Yes, Sandra Kim, 40 regular") is silently accepted and PAID with the overtime
restored by backfill and never questioned.

The fix repairs `prior_matches` ITSELF (the actual defect) rather than patching each
consumer: `alias_learning.confirmed_prior_matches` bridges the clarified employee's
identity in, using the SAME same-record confirmation evidence
(`bind_evidence_for_token`) that is already trusted to PERMANENTLY write an alias to the
roster — a strictly higher-stakes action than diffing two hours values.

The second half: a cross-round paid->paid VALUE CHANGE (20 -> 40 regular, 10 -> 2 OT) is
invisible to `detect_field_regression` BY DESIGN (the accumulation design — the reply's
corrected value wins and is PAID without re-asking; see
tests/test_multiround_context_edge.py). It is now RECORDED and SHOWN to the operator at
the approval gate, and it remains DISPLAY-ONLY: `final_action` stays "process" and no new
gate_reason appears.
"""
from __future__ import annotations

# JSON-shaped fixtures and UUIDs cross dynamic repository seams in these tests.
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi.testclient import TestClient

from app.main import app
from app.models.contracts import Extracted, ExtractedEmployee, InboundEmail
from app.models.roster import NameMatchResult
from app.models.status import RunStatus
from app.pipeline.orchestrator import resume_pipeline

client = TestClient(app, raise_server_exceptions=False)

# ---------------------------------------------------------------------------
# Stable identifiers — Business 3 / Summit Tech (seed.py).
#   Sandra Kim      e0000006  hourly, biweekly (ppy=26)
#   Thomas Bergmann e0000005  salaried (no hours required) — the "different employee"
#                             the deny-case reply resolves instead of Sandra.
# Sandra is BIWEEKLY, so 40 regular hours never trips validate()'s over-40-no-OT rule
# (that rule fires at >80 for ppy=26). The scenarios therefore isolate exactly the
# behavior under test.
# ---------------------------------------------------------------------------
SUMMIT_BIZ_ID = uuid.UUID("b0000003-0000-0000-0000-000000000003")
SUMMIT_EMAIL = "finance@summittech.example"
SANDRA_ID = uuid.UUID("e0000006-0000-0000-0000-000000000006")
SANDRA_ID_STR = str(SANDRA_ID)
BERGMANN_ID = uuid.UUID("e0000005-0000-0000-0000-000000000005")


# ---------------------------------------------------------------------------
# Helpers (mirrors tests/test_multiround_context_edge.py — copied, not imported,
# so this module stays import-independent of any DATABASE_URL-guarded module).
# ---------------------------------------------------------------------------


def _mk_extracted(
    employees_data: list[dict[str, Any]],
    run_id: uuid.UUID | None = None,
) -> Extracted:
    if run_id is None:
        run_id = uuid.uuid4()
    return Extracted(
        run_id=run_id,
        employees=[ExtractedEmployee(**e) for e in employees_data],
        pay_period_start=date(2026, 6, 15),
        pay_period_end=None,
    )


def _mk_match(
    name: str,
    emp_id: uuid.UUID | None,
    source: str = "exact",
    resolved: bool = True,
) -> NameMatchResult:
    if not resolved:
        return NameMatchResult(
            submitted_name=name,
            matched_employee_id=None,
            source="none",
            resolved=False,
            reason="no roster match",
        )
    return NameMatchResult(
        submitted_name=name,
        matched_employee_id=emp_id,
        source=source,
        resolved=True,
        reason=source,
    )


def _seed_run(fake_repo, *, body: str) -> uuid.UUID:
    eid, _ = fake_repo.insert_inbound_email(
        message_id=f"<{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="payroll hours",
        from_addr=SUMMIT_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text=body,
    )
    run_id: uuid.UUID = fake_repo.create_run(
        business_id=SUMMIT_BIZ_ID,
        source_email_id=eid,
    )
    return run_id


def _inbound(body: str) -> InboundEmail:
    return InboundEmail(
        id=uuid.uuid4(),
        message_id=f"<reply-{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="Re: payroll hours",
        from_addr=SUMMIT_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text=body,
        created_at=datetime.now(UTC),
    )


def _extraction_json(employees: list[dict[str, Any]]) -> str:
    return json.dumps(
        {
            "employees": employees,
            "pay_period_start": "2026-06-15",
            "pay_period_end": None,
        }
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


def _seed_clarify_round(
    fake_repo,
    *,
    original_body: str,
    snapshot_employees: list[dict[str, Any]],
    prior_matches: list[NameMatchResult],
    alias_candidates: dict[str, Any],
) -> uuid.UUID:
    """Seed a run parked at AWAITING_REPLY mid-name-clarification.

    This is the exact persisted state the live run e6fa8643 was in when its reply
    arrived: a pre-clarify snapshot, a reconciliation in which the clarified name is
    UNRESOLVED, and an alias_candidates record carrying the LLM's suggestion (written by
    clarification.clarify before the question went out).
    """
    run_id = _seed_run(fake_repo, body=original_body)
    fake_repo.set_pre_clarify_extracted(
        run_id, _mk_extracted(snapshot_employees, run_id=run_id)
    )
    fake_repo.persist_reconciliation(run_id, prior_matches)
    fake_repo.set_alias_candidates(run_id, alias_candidates)
    fake_repo.runs[str(run_id)]["status"] = RunStatus.AWAITING_REPLY.value
    return run_id


def _pending_candidate(employee_id: uuid.UUID) -> dict[str, Any]:
    """The nested alias_candidates shape: suggested by the LLM, not yet confirmed."""
    return {"suggested": str(employee_id), "bound": None}


def _field_regression_reasons(decision: dict[str, Any]) -> list[str]:
    return [r for r in (decision.get("gate_reasons") or []) if "field regression" in r]


# ---------------------------------------------------------------------------
# Test 1 — THE BUG. A dropped hours line on a NAME-clarification reply must clarify.
# ---------------------------------------------------------------------------


def test_dropped_hours_on_name_clarification_reply_clarifies(fake_repo, mock_llm):
    """Live run e6fa8643's hole: "Sandy 20r/10ot" -> "Yes, Sandra Kim, 40 regular".

    The overtime line VANISHED from the reply. Before the identity bridge,
    detect_field_regression's original-side map was built from prior_matches filtered to
    `resolved` — and "Sandy" was UNRESOLVED in the prior round BY DEFINITION (that is why
    we asked). So the snapshot employee was structurally invisible, no drop was detected,
    backfill silently restored the 10 OT hours, and the run went straight to
    AWAITING_APPROVAL with an unasked question about someone's money.

    After the bridge: the reply's own reconciliation record ties "Sandra Kim" to the
    persisted suggestion, so "Sandy" is bridged into prior_matches, the OT drop IS seen,
    and the run asks.
    """
    run_id = _seed_clarify_round(
        fake_repo,
        original_body="Sandy 20 hours, 10 hrs OT",
        snapshot_employees=[
            {"submitted_name": "Sandy", "hours_regular": "20", "hours_overtime": "10"}
        ],
        prior_matches=[_mk_match("Sandy", None, resolved=False)],
        alias_candidates={"Sandy": _pending_candidate(SANDRA_ID)},
    )

    # Combined extraction: ONE employee, "Sandra Kim", 40 regular, NO overtime.
    mock_llm.script = [
        _extraction_json([{"submitted_name": "Sandra Kim", "hours_regular": "40"}]),
        _suggestion_json({}),
        "Could you confirm Sandra Kim's overtime hours?",
    ]

    resume_pipeline(run_id, _inbound("Yes, Sandra Kim - 40 regular"))

    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_REPLY.value, (
        f"a dropped overtime line on a NAME-clarification reply must re-clarify, not "
        f"silently pay; got {run['status']!r}. AWAITING_APPROVAL here means "
        "detect_field_regression is still blind to the clarified employee — the "
        "prior_matches identity bridge has regressed."
    )
    decision = run["decision"]
    assert decision["final_action"] == "request_clarification", (
        f"final_action must be request_clarification; got {decision['final_action']!r}"
    )
    reasons = _field_regression_reasons(decision)
    assert any("hours_overtime" in r for r in reasons), (
        f"a field_regression gate_reason naming hours_overtime must be present; got "
        f"gate_reasons={decision.get('gate_reasons')!r}"
    )


# ---------------------------------------------------------------------------
# Test 2 — NO FALSE POSITIVE. The collision guard.
# ---------------------------------------------------------------------------


def test_bridge_never_collides_with_an_already_resolved_prior_match(fake_repo, mock_llm):
    """A prior entry that resolved DIRECTLY is authoritative and must win the bridge.

    Setup: the snapshot lists the SAME person twice — "Sandra Kim"(20r) first, then
    "Sandy"(20r/10ot). prior_matches resolves "Sandra Kim" directly; "Sandy" is
    unresolved. The reply confirms Sandy = Sandra Kim and reports 20 regular, no OT.

    The snapshot ORDER is load-bearing. Without the collision guard, the bridged "Sandy"
    entry maps to the SAME employee id, and detect_field_regression's original-side map is
    last-entry-wins — so "Sandy"(overtime=10) overwrites "Sandra Kim"(overtime=None) as
    the original side, and a drop that never happened is reported. The client is asked a
    question about hours they never sent.

    The guard: an employee id already mapped by a RESOLVED prior_matches entry can never
    be re-seeded by the bridge.
    """
    run_id = _seed_clarify_round(
        fake_repo,
        original_body="Sandra Kim 20 hours. Sandy 20 hours, 10 hrs OT",
        snapshot_employees=[
            # ORDER IS LOAD-BEARING — see the docstring.
            {"submitted_name": "Sandra Kim", "hours_regular": "20"},
            {"submitted_name": "Sandy", "hours_regular": "20", "hours_overtime": "10"},
        ],
        prior_matches=[
            _mk_match("Sandra Kim", SANDRA_ID),
            _mk_match("Sandy", None, resolved=False),
        ],
        alias_candidates={"Sandy": _pending_candidate(SANDRA_ID)},
    )

    mock_llm.script = [
        _extraction_json([{"submitted_name": "Sandra Kim", "hours_regular": "20"}]),
        _suggestion_json({}),
        "Could you confirm Sandra Kim's hours?",
    ]

    resume_pipeline(run_id, _inbound("Yes, Sandy is Sandra Kim. 20 regular."))

    run = fake_repo.load_run(run_id)
    decision = run["decision"]
    assert _field_regression_reasons(decision) == [], (
        f"the bridge must NOT seed an employee already mapped by a RESOLVED prior entry "
        f"— the direct resolution is authoritative. A field_regression here is the "
        f"last-entry-wins collision firing a drop that never happened; got "
        f"gate_reasons={decision.get('gate_reasons')!r}"
    )
    assert decision["final_action"] == "process", (
        f"final_action must be process (nothing was dropped); got "
        f"{decision['final_action']!r}"
    )


# ---------------------------------------------------------------------------
# Test 3 — NO BIND WITHOUT CONFIRMATION. The misname deny case.
# ---------------------------------------------------------------------------


def test_bridge_does_not_fire_when_the_client_denies_the_match(fake_repo, mock_llm):
    """"No, that's not Sandra — I meant Thomas Bergmann" must NEVER bridge Sandy -> Sandra.

    The LLM only PROPOSED Sandra Kim. The deterministic resolver is what CONFIRMS, and
    here it resolves a DIFFERENT employee entirely. No reconciliation record ties the
    token (or Sandra's canonical full_name) to the suggested id, so
    bind_evidence_for_token returns False and no bridge occurs.

    If the bridge fired on the suggestion alone, Sandra's snapshot hours (20r/10ot) would
    enter the diff against an employee the client explicitly said was someone else — and
    the system would ask about, or carry forward, hours belonging to nobody in this run.

    Asserted on the ABSENCE of a Sandra-Kim field_regression, not on the status: the run
    may still clarify for its own unrelated reasons.
    """
    run_id = _seed_clarify_round(
        fake_repo,
        original_body="Sandy 20 hours, 10 hrs OT",
        snapshot_employees=[
            {"submitted_name": "Sandy", "hours_regular": "20", "hours_overtime": "10"}
        ],
        prior_matches=[_mk_match("Sandy", None, resolved=False)],
        alias_candidates={"Sandy": _pending_candidate(SANDRA_ID)},
    )

    # The reply resolves Thomas Bergmann — never Sandra Kim.
    mock_llm.script = [
        _extraction_json([{"submitted_name": "Thomas Bergmann"}]),
        _suggestion_json({}),
        "Thanks — confirming.",
    ]

    resume_pipeline(
        run_id, _inbound("No, that's not Sandra - I meant Thomas Bergmann.")
    )

    run = fake_repo.load_run(run_id)
    decision = run["decision"]
    reasons = _field_regression_reasons(decision)
    assert reasons == [], (
        f"a DENIED match must never bridge: no field_regression may be attributed to "
        f"Sandra Kim's snapshot hours when the client said the person is someone else; "
        f"got {reasons!r}"
    )

    # The bridge must not have entered the persisted reconciliation either — the
    # suggestion alone is not evidence.
    recon = run.get("reconciliation") or []
    assert not any(
        m.get("submitted_name") == "Sandy" and m.get("resolved") is True for m in recon
    ), (
        f"'Sandy' must never resolve on a denial reply; got reconciliation={recon!r}"
    )
    # And the alias candidate must remain UNBOUND (nothing was confirmed).
    cand = (run.get("alias_candidates") or {}).get("Sandy") or {}
    assert cand.get("bound") is None, (
        f"the alias candidate must stay unbound on a denial; got {cand!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — THE LIVE RUN (e6fa8643). A CHANGE is recorded, and STILL processes.
# ---------------------------------------------------------------------------


def _run_the_live_scenario(fake_repo, mock_llm) -> uuid.UUID:
    """Reproduce live run e6fa8643 end to end. Shared by Tests 4 and 5.

    Original: "Sandy 20 hours, 10 hrs OT". We clarify on the unresolved name "Sandy".
    Reply: "Yes, Sandra kim but only 40r regular, 2 hrs ot" — the client CONFIRMS the
    identity and CHANGES both hours values in the same breath.
    """
    run_id = _seed_clarify_round(
        fake_repo,
        original_body="Sandy 20 hours, 10 hrs OT",
        snapshot_employees=[
            {"submitted_name": "Sandy", "hours_regular": "20", "hours_overtime": "10"}
        ],
        prior_matches=[_mk_match("Sandy", None, resolved=False)],
        alias_candidates={"Sandy": _pending_candidate(SANDRA_ID)},
    )
    mock_llm.script = [
        _extraction_json(
            [
                {
                    "submitted_name": "Sandra Kim",
                    "hours_regular": "40",
                    "hours_overtime": "2",
                }
            ]
        ),
    ]
    resume_pipeline(
        run_id, _inbound("Yes, Sandra kim but only 40r regular, 2 hrs ot")
    )
    return run_id


def test_cross_round_hours_change_is_recorded_but_never_gates(fake_repo, mock_llm):
    """The live run: both hours values CHANGED. Process anyway — but RECORD it.

    All four assertions matter, and (d) is not redundant with (b):
      (a) the run still reaches AWAITING_APPROVAL — the accumulation design is intact;
      (b) final_action == 'process' with EMPTY gate_reasons — no new gate rule appeared;
      (c) the change is PERSISTED as two records, so the operator approves a fact the
          pipeline actually computed rather than a render-time re-derivation;
      (d) the paystub PAYS 40 and 2. Asserting the LABEL without asserting the PAID VALUE
          is exactly how this codebase has been bitten before.
    """
    run_id = _run_the_live_scenario(fake_repo, mock_llm)
    run = fake_repo.load_run(run_id)

    # (a) the accumulation design is intact — the corrected values are simply paid.
    assert run["status"] == RunStatus.AWAITING_APPROVAL.value, (
        f"a CHANGE (not a drop) must not re-clarify — the reply's corrected value wins "
        f"and is paid; got {run['status']!r}"
    )

    # (b) no new gate rule. decide.py gained nothing.
    decision = run["decision"]
    assert decision["final_action"] == "process", (
        f"final_action must stay 'process'; got {decision['final_action']!r}"
    )
    assert decision["gate_reasons"] == [], (
        f"a recorded hours CHANGE must never produce a gate_reason — HoursChange has no "
        f"issue_type and can never reach decide(); got {decision['gate_reasons']!r}"
    )

    # (c) the change is persisted — two records, both transitions.
    persisted = run.get("hours_changes")
    assert persisted, (
        f"the cross-round change must be PERSISTED on the run row so the operator "
        f"approves a pipeline-computed fact, not a render-time guess; got {persisted!r}"
    )
    by_field = {c["field"]: c for c in persisted}
    assert set(by_field) == {"hours_regular", "hours_overtime"}, (
        f"exactly the two changed fields must be recorded; got {persisted!r}"
    )
    assert Decimal(str(by_field["hours_regular"]["original_value"])) == Decimal("20")
    assert Decimal(str(by_field["hours_regular"]["resumed_value"])) == Decimal("40")
    assert Decimal(str(by_field["hours_overtime"]["original_value"])) == Decimal("10")
    assert Decimal(str(by_field["hours_overtime"]["resumed_value"])) == Decimal("2")

    # (d) THE MONEY. The paystub pays the client's NEW numbers, not the snapshot's.
    line_items = fake_repo.load_line_items(run_id)
    assert line_items, "a process run must compute a paystub"
    sandra = [i for i in line_items if str(i.employee_id) == SANDRA_ID_STR]
    assert sandra, f"a paystub line item for Sandra Kim ({SANDRA_ID_STR}) must exist"
    assert sandra[0].hours_regular == Decimal("40"), (
        f"the PAID regular hours must be the client's corrected 40, not the snapshot's "
        f"20; got {sandra[0].hours_regular!r}"
    )
    assert sandra[0].hours_overtime == Decimal("2"), (
        f"the PAID overtime must be the client's corrected 2, not the snapshot's 10 "
        f"(a backfill restoring 10 here is an OVERPAY); got {sandra[0].hours_overtime!r}"
    )


# ---------------------------------------------------------------------------
# Test 5 — THE OPERATOR SEES IT, at the gate where they approve the money.
# ---------------------------------------------------------------------------


def test_operator_sees_the_hours_change_on_the_run_detail_page(fake_repo, mock_llm):
    """The whole point of Change 2: the human approving the payroll can SEE the change.

    Asserted on RENDERED TEXT, not on the template source — a banner that exists in the
    file but never renders (wrong branch, wrong variable name) protects nobody.
    """
    run_id = _run_the_live_scenario(fake_repo, mock_llm)

    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200, (
        f"GET /runs/{{id}} must render; got {response.status_code}"
    )
    body = response.text

    assert "changed" in body.lower(), (
        "the run detail page must carry a 'changed' affordance telling the operator the "
        "client altered hours on their reply"
    )
    assert "Sandra Kim" in body, "the banner must name the employee whose hours changed"
    for value in ("20", "40", "10", "2"):
        assert value in body, (
            f"the banner must render the {value} side of the transitions "
            "(20 -> 40 regular, 10 -> 2 overtime)"
        )


# ---------------------------------------------------------------------------
# Test 6 — NO STALE STATE. The write is unconditional, so [] is structural.
# ---------------------------------------------------------------------------


def test_a_run_with_no_change_persists_an_empty_hours_changes(fake_repo, mock_llm):
    """hours_changes is written on EVERY run and EVERY resume — even when it is empty.

    A stale value here would show the operator a change from a DEAD attempt and invite
    them to approve numbers on the strength of it. Writing [] unconditionally makes that
    structurally impossible rather than only accidentally absent — which is why the seed
    below plants a stale record and demands it be gone.
    """
    run_id = _seed_clarify_round(
        fake_repo,
        original_body="Sandra Kim 20 hours",
        snapshot_employees=[{"submitted_name": "Sandra Kim", "hours_regular": "20"}],
        prior_matches=[_mk_match("Sandra Kim", SANDRA_ID)],
        alias_candidates={},
    )
    # Plant a STALE change record from a hypothetical earlier attempt.
    fake_repo.runs[str(run_id)]["hours_changes"] = [
        {
            "submitted_name": "Sandra Kim",
            "field": "hours_regular",
            "original_value": "99",
            "resumed_value": "1",
        }
    ]

    # The reply changes nothing — 20 regular, same as the snapshot.
    mock_llm.script = [
        _extraction_json([{"submitted_name": "Sandra Kim", "hours_regular": "20"}]),
    ]
    resume_pipeline(run_id, _inbound("Yes, 20 hours is right."))

    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.AWAITING_APPROVAL.value
    assert run.get("hours_changes") == [], (
        f"a run with no cross-round change must persist an EMPTY list, overwriting any "
        f"stale value — the write is unconditional; got {run.get('hours_changes')!r}"
    )
