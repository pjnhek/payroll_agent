"""needs_operator escalation proof — CLAR2-02 escalation half (Phase 11 Plan 02).

WHY THIS LIVES IN ITS OWN MODULE (NOT tests/test_resume_pipeline.py):
tests/test_resume_pipeline.py carries a MODULE-LEVEL conditional-skip marker
gated on `os.environ.get("DATABASE_URL")` being unset (the 09-REVIEWS.md /
test_multiround_context_edge.py convention this module restates). This module
is genuinely hermetic (FakeConnection + monkeypatched repo.* + TestClient, no
live DB/LLM) and runs unconditionally offline — no module-level skip marker.

WHAT THIS MODULE PROVES:
D-11-06/D-11-07/D-11-09 — after MAX_CLARIFICATION_ROUNDS (3) clarification
sends, the next would-be send silently escalates the run to needs_operator
instead of sending a 4th email. No LLM call, no gateway call, no new outbound
row (D-11-09 silent handoff). needs_operator is also excluded from every
scope list that would otherwise treat it as an in-flight or stranded state
(D-11-06's "excluded from sweep scope, retrigger's stale-claim scope, and
D-11-05 auto-resume by design").

1. cap boundary (Open Q4 pin) — counter=2 lets the 3rd send proceed (gateway
   called); counter=3 blocks the 4th (no gateway call, no llm call, status
   becomes needs_operator).
2. escalation is silent (D-11-09) — no new outbound email row is written.
3. escalation write order — set_status(NEEDS_OPERATOR) is the LAST (in fact
   the only) write of its transaction (AST pin, shared with
   test_clarify_rounds.py's cap-precedes-transactions test).
4. scope exclusions — "needs_operator" not in IN_FLIGHT_STATUSES (imported
   from app.main) and not in retrigger's stale_statuses.
5. badge rendering — TestClient GET of a needs_operator run's detail page
   shows the "Needs Operator" label, not a raw title-cased fallback.

Money-path discipline (Phase 7.5 lesson): assertions target PERSISTED
STATE/BEHAVIOR (gateway/llm called or not, status value, scope membership),
never log strings.
"""
from __future__ import annotations

import ast
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi.testclient import TestClient

from app.main import IN_FLIGHT_STATUSES, app
from app.models.contracts import Decision, Extracted, ExtractedEmployee, InboundEmail
from app.models.roster import NameMatchResult
from app.pipeline.orchestrator import MAX_CLARIFICATION_ROUNDS, _clarify

COASTAL_BIZ_ID = uuid.UUID("b0000001-0000-0000-0000-000000000001")
COASTAL_EMAIL = "payroll@coastalcleaning.example"

client = TestClient(app, raise_server_exceptions=False)


def _bare_roster(business_id=COASTAL_BIZ_ID):
    from app.models.roster import Roster

    return Roster(business_id=business_id, employees=[])


def _bare_inbound() -> InboundEmail:
    return InboundEmail(
        id=uuid.uuid4(),
        message_id="<orig@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="hours",
        from_addr=COASTAL_EMAIL,
        to_addr="agent@payroll-agent.local",
        body_text="David Reyez 38 hours",
        created_at=datetime.now(timezone.utc),
    )


def _bare_decision() -> Decision:
    return Decision(
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


def _bare_extracted(run_id: uuid.UUID) -> Extracted:
    return Extracted(
        run_id=run_id,
        employees=[ExtractedEmployee(submitted_name="__stub__", hours_regular=Decimal("0"))],
    )


# ===========================================================================
# 1. cap boundary (Open Question #4 pin)
# ===========================================================================


def test_below_cap_send_proceeds(monkeypatch, fake_repo, mock_llm):
    """counter=2 (< MAX_CLARIFICATION_ROUNDS=3): the 3rd send proceeds — gateway
    IS called, status stays awaiting_reply, NOT needs_operator."""
    assert MAX_CLARIFICATION_ROUNDS == 3

    import app.email.gateway as gateway_mod

    run_id = uuid.uuid4()
    email = _bare_inbound()
    decision = _bare_decision()
    extracted = _bare_extracted(run_id)
    roster = _bare_roster()

    fake_repo.runs[str(run_id)] = {
        "id": run_id,
        "status": "extracting",
        "business_id": COASTAL_BIZ_ID,
        "clarification_round": 2,
    }
    fake_repo.outbound[str(run_id)] = []

    send_calls: list = []
    real_send_outbound = gateway_mod.send_outbound

    def _spy_send_outbound(**kw):
        send_calls.append(kw)
        return real_send_outbound(**kw)

    monkeypatch.setattr(gateway_mod, "send_outbound", _spy_send_outbound)

    _clarify(run_id, email, decision, roster, extracted, llm=None, purpose="clarification")

    assert len(send_calls) == 1, "the 3rd send (counter=2 -> 3) must proceed, not escalate"
    assert fake_repo.runs[str(run_id)]["status"] == "awaiting_reply"
    assert fake_repo.runs[str(run_id)]["clarification_round"] == 3


def test_at_cap_send_escalates_with_no_gateway_or_llm_call(monkeypatch, fake_repo):
    """counter=3 (== MAX_CLARIFICATION_ROUNDS): the would-be 4th send must NOT
    call the gateway and must NOT call the LLM (suggest_employees /
    compose_clarification) — the cap check returns before either seam is
    reached. Status becomes needs_operator."""
    import app.email.gateway as gateway_mod
    import app.pipeline.suggest as suggest_mod
    import app.pipeline.compose_email as compose_mod

    run_id = uuid.uuid4()
    email = _bare_inbound()
    decision = _bare_decision()
    extracted = _bare_extracted(run_id)
    roster = _bare_roster()

    fake_repo.runs[str(run_id)] = {
        "id": run_id,
        "status": "extracting",
        "business_id": COASTAL_BIZ_ID,
        "clarification_round": MAX_CLARIFICATION_ROUNDS,
    }
    fake_repo.outbound[str(run_id)] = []

    def _fail_send_outbound(**kw):
        raise AssertionError("gateway.send_outbound must NOT be called at the cap")

    def _fail_suggest(*a, **kw):
        raise AssertionError("suggest_employees (LLM call) must NOT be called at the cap")

    def _fail_compose(*a, **kw):
        raise AssertionError("compose_clarification (LLM call) must NOT be called at the cap")

    monkeypatch.setattr(gateway_mod, "send_outbound", _fail_send_outbound)
    monkeypatch.setattr(suggest_mod, "suggest_employees", _fail_suggest)
    monkeypatch.setattr(compose_mod, "compose_clarification", _fail_compose)
    # Also patch the names as imported into orchestrator (import-time binding).
    import app.pipeline.orchestrator as orch_mod
    monkeypatch.setattr(orch_mod, "suggest_employees", _fail_suggest)
    monkeypatch.setattr(orch_mod, "compose_clarification", _fail_compose)

    _clarify(run_id, email, decision, roster, extracted, llm=None, purpose="clarification")

    assert fake_repo.runs[str(run_id)]["status"] == "needs_operator", (
        "at the cap, the run must escalate to needs_operator instead of sending"
    )
    # Round counter must NOT advance further on escalation (D-11-09: escalation
    # is terminal/silent, not another round).
    assert fake_repo.runs[str(run_id)]["clarification_round"] == MAX_CLARIFICATION_ROUNDS


# ===========================================================================
# 2. escalation is silent (D-11-09) — no new outbound email row
# ===========================================================================


def test_escalation_writes_no_outbound_row(fake_repo):
    """Escalating to needs_operator must NOT write any new outbound email row —
    no client-facing signal, no new purpose, no template (D-11-09)."""
    run_id = uuid.uuid4()
    email = _bare_inbound()
    decision = _bare_decision()
    extracted = _bare_extracted(run_id)
    roster = _bare_roster()

    fake_repo.runs[str(run_id)] = {
        "id": run_id,
        "status": "extracting",
        "business_id": COASTAL_BIZ_ID,
        "clarification_round": MAX_CLARIFICATION_ROUNDS,
    }
    fake_repo.outbound[str(run_id)] = []

    _clarify(run_id, email, decision, roster, extracted, llm=None, purpose="clarification")

    assert fake_repo.outbound.get(str(run_id), []) == [], (
        "escalation must write ZERO new outbound rows (D-11-09 silent handoff)"
    )


# ===========================================================================
# 3. escalation write order — set_status(NEEDS_OPERATOR) is the sole/last write
# ===========================================================================


def test_escalation_transaction_writes_only_status():
    """AST pin: the cap-escalation `with conn.transaction():` block in
    _clarify's source contains set_status as its only tracked write and does
    NOT call set_clarification_round (escalation is terminal, D-11-09) — the
    complementary assertion to test_clarify_rounds.py's cap-precedes-
    transactions test, focused on the escalation block's CONTENTS.
    """
    import app.pipeline.orchestrator as orch_mod

    src = open(orch_mod.__file__).read()
    tree = ast.parse(src)

    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_clarify"
    )

    def _call_name(node):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Attribute):
                return f.attr
        return None

    tx_blocks = [
        node
        for node in ast.walk(func)
        if isinstance(node, ast.With)
        and any(
            isinstance(item.context_expr, ast.Call)
            and isinstance(item.context_expr.func, ast.Attribute)
            and item.context_expr.func.attr == "transaction"
            for item in node.items
        )
    ]

    def _tracked_calls(node):
        return [
            _call_name(stmt)
            for stmt in ast.walk(node)
            if _call_name(stmt) in ("set_status", "set_clarification_round", "set_pre_clarify_extracted")
        ]

    escalation_blocks = [
        node for node in tx_blocks if _tracked_calls(node) == ["set_status"]
    ]
    assert len(escalation_blocks) == 1, (
        "exactly one transaction block in _clarify must contain ONLY a "
        "set_status call (the cap-escalation block, D-11-09)"
    )
    # It must be the textually FIRST transaction block (cap check precedes the
    # (purpose, round) guard and any send path).
    first_block = min(tx_blocks, key=lambda n: n.lineno)
    assert escalation_blocks[0] is first_block, (
        "the escalation-only transaction block must be the FIRST transaction "
        "block in _clarify's source (cap check runs before the guard/send paths)"
    )


# ===========================================================================
# 4. scope exclusions
# ===========================================================================


def test_needs_operator_excluded_from_in_flight_statuses():
    """needs_operator must NOT be in app.main.IN_FLIGHT_STATUSES — it is a
    settled human-gate escalation state, not a processing state (D-11-06)."""
    assert "needs_operator" not in IN_FLIGHT_STATUSES


def test_needs_operator_excluded_from_retrigger_stale_statuses():
    """needs_operator must NOT be one of retrigger's stale_statuses (the
    RECEIVED/EXTRACTING/COMPUTED/SENT scope that governs stale-in-flight
    reclaim) — an escalated run's recovery path is the D-11-08 resolve form,
    not a generic retrigger-from-original (D-11-06)."""
    import inspect

    import app.main as main_mod

    src = inspect.getsource(main_mod.retrigger)
    tree = ast.parse(src)

    stale_sets = [node for node in ast.walk(tree) if isinstance(node, ast.Set)]
    assert stale_sets, "retrigger's stale_statuses set literal must be present in its source"

    def _const_values(set_node):
        values = []
        for elt in set_node.elts:
            # Each element is RunStatus.<MEMBER>.value — an ast.Attribute chain.
            if isinstance(elt, ast.Attribute) and elt.attr == "value":
                inner = elt.value
                if isinstance(inner, ast.Attribute):
                    values.append(inner.attr)
        return values

    all_members = [m for s in stale_sets for m in _const_values(s)]
    assert "RECEIVED" in all_members and "EXTRACTING" in all_members, (
        "sanity: expected retrigger's stale_statuses to reference RunStatus members"
    )
    assert "NEEDS_OPERATOR" not in all_members, (
        "retrigger's stale_statuses must NEVER include NEEDS_OPERATOR (D-11-06)"
    )


# ===========================================================================
# 5. badge rendering
# ===========================================================================


def test_run_detail_renders_needs_operator_badge_label(monkeypatch):
    """GET /runs/{id} for a needs_operator run must render the 'Needs Operator'
    label (not a raw title-cased fallback like 'Needs Operator' coincidentally
    matching — assert the badge class is also the dedicated 'escalate' class,
    not the generic 'neutral' fallback a missing dict entry would produce)."""
    from app.db import repo as _repo

    run_id = uuid.uuid4()
    needs_operator_run = {
        "id": run_id,
        "business_id": uuid.uuid4(),
        "source_email_id": uuid.uuid4(),
        "status": "needs_operator",
        "extracted_data": None,
        "decision": None,
        "reconciliation": None,
        "error_reason": None,
        "pay_period_start": None,
        "pay_period_end": None,
        "updated_at": None,
    }
    monkeypatch.setattr(_repo, "load_run", lambda rid, conn=None: needs_operator_run)
    monkeypatch.setattr(_repo, "load_inbound_email", lambda rid, conn=None: None)
    monkeypatch.setattr(_repo, "load_line_items", lambda rid, conn=None: [])
    monkeypatch.setattr(_repo, "load_outbound_emails", lambda rid, conn=None: [])

    response = client.get(f"/runs/{run_id}")
    assert response.status_code == 200
    assert "Needs Operator" in response.text, (
        "the needs_operator run's badge must render the 'Needs Operator' label"
    )
    assert "badge-escalate" in response.text, (
        "the needs_operator run's badge must use the dedicated 'escalate' CSS "
        "class, not a generic/fallback class"
    )


def test_runs_list_renders_needs_operator_badge_label(monkeypatch):
    """GET /runs must also render the 'Needs Operator' label + escalate class
    for a needs_operator row in the runs list table."""
    from app.db import repo as _repo

    run_id = uuid.uuid4()
    needs_operator_run = {
        "id": run_id,
        "business_id": uuid.uuid4(),
        "status": "needs_operator",
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
        "pay_period_start": None,
        "pay_period_end": None,
    }
    monkeypatch.setattr(_repo, "sweep_stranded_runs", lambda *a, **kw: [])
    monkeypatch.setattr(_repo, "load_all_runs", lambda *a, **kw: [needs_operator_run])

    response = client.get("/runs")
    assert response.status_code == 200
    assert "Needs Operator" in response.text
    assert "badge-escalate" in response.text


# ===========================================================================
# 6. POST /runs/{run_id}/resolve — server-side roster validation (Security V4),
#    override application, remember-checkbox bind, claim + resume dispatch
#    (D-11-08, D-11-16, Phase 11 Plan 04)
# ===========================================================================


def _needs_operator_run_row(run_id, business_id, unresolved_names):
    from app.models.contracts import Decision as _Decision

    decision = _Decision(
        final_action="request_clarification",
        gate_reasons=[f"{n}: unresolved" for n in unresolved_names],
        unresolved_names=unresolved_names,
        missing_fields=[],
        resolutions=[
            NameMatchResult(
                submitted_name=n,
                matched_employee_id=None,
                source="none",
                resolved=False,
                reason="no roster match",
            )
            for n in unresolved_names
        ],
    )
    return {
        "id": run_id,
        "business_id": business_id,
        "status": "needs_operator",
        "decision": decision.model_dump(mode="json"),
        "alias_candidates": {},
        "clarification_round": MAX_CLARIFICATION_ROUNDS,
    }


def test_resolve_rejects_whole_post_on_invalid_employee_id(monkeypatch, fake_repo):
    """Security V4: a posted employee_id NOT on the run's own business roster
    must reject the WHOLE POST — no state change, no partial apply."""
    from app.models.roster import Employee, Roster

    biz_id = COASTAL_BIZ_ID
    real_emp_id = uuid.uuid4()
    roster = Roster(
        business_id=biz_id,
        employees=[
            Employee(
                id=real_emp_id,
                business_id=biz_id,
                full_name="Real Employee",
                known_aliases=[],
                pay_type="hourly",
                hourly_rate=Decimal("20.00"),
                annual_salary=None,
                retirement_contribution_pct=Decimal("0.00"),
                filing_status="single",
                step_2_checkbox=False,
                step_3_dependents=Decimal("0"),
                step_4a_other_income=Decimal("0"),
                step_4b_deductions=Decimal("0"),
                ytd_ss_wages=Decimal("0.00"),
                pay_periods_per_year=52,
            )
        ],
    )

    run_id = uuid.uuid4()
    run_row = _needs_operator_run_row(run_id, biz_id, ["Jimmy"])
    fake_repo.runs[str(run_id)] = run_row

    import app.db.repo as repo_mod
    monkeypatch.setattr(
        repo_mod, "load_roster_for_business", lambda *a, **kw: roster, raising=False
    )

    # A cross-business / arbitrary UUID that is NOT on this roster.
    bogus_id = str(uuid.uuid4())
    response = client.post(
        f"/runs/{run_id}/resolve",
        data={"employee_id_0": bogus_id, "remember_0": "on"},
    )
    assert response.status_code in (200, 303), (
        "the route must not 500 on a rejected POST — it redirects as a no-op"
    )
    # State must NOT have changed: still needs_operator, no override applied.
    assert fake_repo.runs[str(run_id)]["status"] == "needs_operator", (
        "an invalid employee_id must reject the WHOLE POST — the run must "
        "stay at needs_operator, not silently claim/advance (Security V4)"
    )


def test_resolve_applies_override_and_claims_on_valid_post(monkeypatch, fake_repo):
    """A fully-valid POST (every employee_id on the roster) applies the
    override, claims NEEDS_OPERATOR -> EXTRACTING, and dispatches resume."""
    from app.models.roster import Employee, Roster

    biz_id = COASTAL_BIZ_ID
    real_emp_id = uuid.uuid4()
    roster = Roster(
        business_id=biz_id,
        employees=[
            Employee(
                id=real_emp_id,
                business_id=biz_id,
                full_name="Real Employee",
                known_aliases=[],
                pay_type="hourly",
                hourly_rate=Decimal("20.00"),
                annual_salary=None,
                retirement_contribution_pct=Decimal("0.00"),
                filing_status="single",
                step_2_checkbox=False,
                step_3_dependents=Decimal("0"),
                step_4a_other_income=Decimal("0"),
                step_4b_deductions=Decimal("0"),
                ytd_ss_wages=Decimal("0.00"),
                pay_periods_per_year=52,
            )
        ],
    )

    run_id = uuid.uuid4()
    run_row = _needs_operator_run_row(run_id, biz_id, ["Jimmy"])
    fake_repo.runs[str(run_id)] = run_row

    import app.db.repo as repo_mod
    monkeypatch.setattr(
        repo_mod, "load_roster_for_business", lambda *a, **kw: roster, raising=False
    )

    resume_calls: list = []
    monkeypatch.setattr(
        "app.pipeline.orchestrator.resume_pipeline",
        lambda *a, **kw: resume_calls.append((a, kw)),
        raising=False,
    )

    response = client.post(
        f"/runs/{run_id}/resolve",
        data={"employee_id_0": str(real_emp_id), "remember_0": "on"},
    )
    assert response.status_code in (200, 303)
    assert fake_repo.runs[str(run_id)]["status"] == "extracting", (
        "a valid POST must claim NEEDS_OPERATOR -> EXTRACTING"
    )
    # The remember-checkbox (checked) must have pre-set the bound candidate so
    # the existing approval-gate write path persists it (D-11-16).
    candidates = fake_repo.runs[str(run_id)].get("alias_candidates") or {}
    assert candidates.get("Jimmy") == {
        "suggested": str(real_emp_id),
        "bound": str(real_emp_id),
    }, f"remember-checked token must be pre-bound; got {candidates!r}"


def test_resolve_checkbox_off_does_not_bind(monkeypatch, fake_repo):
    """D-11-16: remember-checkbox OFF means override-only — nothing learned."""
    from app.models.roster import Employee, Roster

    biz_id = COASTAL_BIZ_ID
    real_emp_id = uuid.uuid4()
    roster = Roster(
        business_id=biz_id,
        employees=[
            Employee(
                id=real_emp_id,
                business_id=biz_id,
                full_name="Real Employee",
                known_aliases=[],
                pay_type="hourly",
                hourly_rate=Decimal("20.00"),
                annual_salary=None,
                retirement_contribution_pct=Decimal("0.00"),
                filing_status="single",
                step_2_checkbox=False,
                step_3_dependents=Decimal("0"),
                step_4a_other_income=Decimal("0"),
                step_4b_deductions=Decimal("0"),
                ytd_ss_wages=Decimal("0.00"),
                pay_periods_per_year=52,
            )
        ],
    )

    run_id = uuid.uuid4()
    run_row = _needs_operator_run_row(run_id, biz_id, ["Jimmy"])
    fake_repo.runs[str(run_id)] = run_row

    import app.db.repo as repo_mod
    monkeypatch.setattr(
        repo_mod, "load_roster_for_business", lambda *a, **kw: roster, raising=False
    )
    monkeypatch.setattr(
        "app.pipeline.orchestrator.resume_pipeline", lambda *a, **kw: None, raising=False
    )

    # No remember_0 key posted at all (checkbox unchecked never submits its field).
    response = client.post(
        f"/runs/{run_id}/resolve",
        data={"employee_id_0": str(real_emp_id)},
    )
    assert response.status_code in (200, 303)
    candidates = fake_repo.runs[str(run_id)].get("alias_candidates") or {}
    assert "Jimmy" not in candidates, (
        "checkbox OFF must NOT set a bound candidate — override-only, "
        "nothing learned (D-11-16)"
    )
