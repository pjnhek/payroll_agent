"""needs_operator escalation proof — the clarification round cap has a human escape.

WHY THIS LIVES IN ITS OWN MODULE (NOT tests/test_resume_pipeline.py):
tests/test_resume_pipeline.py carries a MODULE-LEVEL conditional-skip marker gated on
`os.environ.get("DATABASE_URL")` being unset. This module is genuinely hermetic
(FakeConnection + monkeypatched repo.* + TestClient, no live DB or LLM) and must run
unconditionally offline — putting it there would silently skip it in every hermetic run.

WHAT THIS MODULE PROVES:
After MAX_CLARIFICATION_ROUNDS (3) clarification sends, the next would-be send silently
escalates the run to needs_operator instead of sending a 4th email. No LLM call, no
gateway call, no new outbound row — a silent handoff to a human, not more spam and not a
silent stall. needs_operator is also excluded from every scope list that would otherwise
treat it as in-flight or stranded (the recovery sweep, retrigger's stale-claim scope, and
auto-resume), because it is a settled human-gate state, not a state to recover from.

1. cap boundary — counter=2 lets the 3rd send proceed (gateway called); counter=3 blocks
   the 4th (no gateway call, no llm call, status becomes needs_operator).
2. escalation is silent — no new outbound email row is written.
3. escalation write order — set_status(NEEDS_OPERATOR) is the LAST (in fact the only)
   write of its transaction (an AST pin, shared with test_clarify_rounds.py's
   cap-precedes-transactions test).
4. scope exclusions — "needs_operator" is not in IN_FLIGHT_STATUSES and not in
   retrigger's stale_statuses.
5. badge rendering — a TestClient GET of a needs_operator run's detail page shows the
   "Needs Operator" label, not a raw title-cased fallback.

Money-path discipline: assertions target PERSISTED STATE and BEHAVIOR (gateway/llm called
or not, status value, scope membership) — never log strings, which can be green while the
DB holds something else entirely.
"""
from __future__ import annotations

import ast
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.contracts import Decision, Extracted, ExtractedEmployee, InboundEmail
from app.models.job import Job, JobKind
from app.models.roster import NameMatchResult
from app.models.status import RunStatus
from app.pipeline.clarification import MAX_CLARIFICATION_ROUNDS
from app.pipeline.clarification import clarify as _clarify
from app.pipeline.result import PipelineOutcome, PipelineResult
from app.routes.runs import IN_FLIGHT_STATUSES
from tests.conftest import InMemoryRepo

COASTAL_BIZ_ID = uuid.UUID("b0000001-0000-0000-0000-000000000001")
COASTAL_EMAIL = "payroll@coastalcleaning.example"

client = TestClient(app, raise_server_exceptions=False)


def _bare_roster(business_id: uuid.UUID = COASTAL_BIZ_ID):
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
        created_at=datetime.now(UTC),
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


def _operator_resume_job(
    *,
    run_id: uuid.UUID | None,
    operator_resolution_id: uuid.UUID | None,
    attempts: int = 1,
) -> Job:
    return Job(
        id=uuid.uuid4(),
        kind=JobKind.OPERATOR_RESUME,
        run_id=run_id,
        operator_resolution_id=operator_resolution_id,
        attempts=attempts,
        max_attempts=5,
        lease_token=uuid.uuid4(),
    )


def test_operator_resume_uses_complete_durable_mapping_not_alias_candidates(
    fake_repo, monkeypatch
) -> None:
    from app.pipeline import orchestrator
    from app.queue.handlers import operator_resume

    run_id = uuid.uuid4()
    fake_repo.runs[str(run_id)] = _needs_operator_run_row(
        run_id, COASTAL_BIZ_ID, ["Jimmy", "Maria C"]
    )
    fake_repo.runs[str(run_id)]["status"] = RunStatus.RECEIVED.value
    fake_repo.runs[str(run_id)]["alias_candidates"] = {
        "Jimmy": {"bound": "not-authority"}
    }
    resolution_id = uuid.uuid4()
    complete = {
        "Jimmy": "e0000002-0000-0000-0000-000000000002",
        "Maria C": "e0000001-0000-0000-0000-000000000001",
    }
    fake_repo.create_operator_resume_resolution(run_id, resolution_id, complete)

    calls: list[dict[str, Any]] = []
    explicit = PipelineResult(outcome=PipelineOutcome.OK)

    def _resume(rid, inbound, *, from_status, overrides, **kwargs):
        calls.append(
            {
                "run_id": rid,
                "inbound": inbound,
                "from_status": from_status,
                "overrides": overrides,
            }
        )
        return explicit

    monkeypatch.setattr(orchestrator, "resume_pipeline", _resume)

    result = operator_resume.handle_operator_resume(
        _operator_resume_job(
            run_id=run_id,
            operator_resolution_id=resolution_id,
        )
    )

    assert result is explicit
    assert calls == [
        {
            "run_id": run_id,
            "inbound": None,
            "from_status": RunStatus.RECEIVED,
            "overrides": complete,
        }
    ]


def test_operator_resume_reclaims_without_advancing_epoch(fake_repo, monkeypatch) -> None:
    from app.pipeline import orchestrator
    from app.queue.handlers import operator_resume

    run_id = uuid.uuid4()
    fake_repo.runs[str(run_id)] = _needs_operator_run_row(
        run_id, COASTAL_BIZ_ID, ["Jimmy"]
    )
    run = fake_repo.runs[str(run_id)]
    run["status"] = RunStatus.EXTRACTING.value
    run["reply_epoch"] = 9
    resolution_id = uuid.uuid4()
    fake_repo.create_operator_resume_resolution(
        run_id,
        resolution_id,
        {"Jimmy": "e0000002-0000-0000-0000-000000000002"},
    )
    calls: list[dict[str, str]] = []
    monkeypatch.setattr(
        orchestrator,
        "resume_pipeline",
        lambda _rid, _inbound, *, overrides, **_kwargs: calls.append(overrides),
    )

    assert (
        operator_resume.handle_operator_resume(
            _operator_resume_job(
                run_id=run_id,
                operator_resolution_id=resolution_id,
                attempts=2,
            )
        )
        is None
    )
    assert calls == [{"Jimmy": "e0000002-0000-0000-0000-000000000002"}]
    assert run["reply_epoch"] == 9


def test_operator_resume_rejects_partial_extra_cross_business_and_wrong_run_context(
    fake_repo, monkeypatch, caplog
) -> None:
    from app.pipeline import orchestrator
    from app.queue.handlers import operator_resume

    run_id = uuid.uuid4()
    fake_repo.runs[str(run_id)] = _needs_operator_run_row(
        run_id, COASTAL_BIZ_ID, ["SECRET Jimmy", "SECRET Maria"]
    )
    fake_repo.runs[str(run_id)]["status"] = RunStatus.RECEIVED.value
    calls: list[object] = []
    monkeypatch.setattr(
        orchestrator,
        "resume_pipeline",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    invalid_mappings = [
        {"SECRET Jimmy": "e0000002-0000-0000-0000-000000000002"},
        {
            "SECRET Jimmy": "e0000002-0000-0000-0000-000000000002",
            "SECRET Maria": "e0000001-0000-0000-0000-000000000001",
            "SECRET Extra": "e0000001-0000-0000-0000-000000000001",
        },
        {
            "SECRET Jimmy": "e0000003-0000-0000-0000-000000000003",
            "SECRET Maria": "e0000001-0000-0000-0000-000000000001",
        },
    ]
    results: list[PipelineResult] = []
    for mapping in invalid_mappings:
        resolution_id = uuid.uuid4()
        fake_repo.create_operator_resume_resolution(run_id, resolution_id, mapping)
        results.append(
            operator_resume.handle_operator_resume(
                _operator_resume_job(
                    run_id=run_id,
                    operator_resolution_id=resolution_id,
                )
            )
        )

    wrong_run_resolution = uuid.uuid4()
    other_run_id = uuid.uuid4()
    fake_repo.create_operator_resume_resolution(
        other_run_id,
        wrong_run_resolution,
        {
            "SECRET Jimmy": "e0000002-0000-0000-0000-000000000002",
            "SECRET Maria": "e0000001-0000-0000-0000-000000000001",
        },
    )
    results.append(
        operator_resume.handle_operator_resume(
            _operator_resume_job(
                run_id=run_id,
                operator_resolution_id=wrong_run_resolution,
            )
        )
    )

    assert not calls
    assert all(result.outcome is PipelineOutcome.TERMINAL for result in results)
    assert all(
        result.diagnostic_code == "load:invalid_operator_override_context"
        for result in results
    )
    assert "SECRET" not in caplog.text
    assert "e0000001" not in caplog.text
    assert "e0000002" not in caplog.text
    assert "e0000003" not in caplog.text


def test_operator_resume_requires_both_durable_identifiers(fake_repo) -> None:
    from app.queue.handlers import operator_resume

    with pytest.raises(ValueError, match="run_id"):
        operator_resume.handle_operator_resume(
            _operator_resume_job(
                run_id=None,
                operator_resolution_id=uuid.uuid4(),
            )
        )
    with pytest.raises(ValueError, match="operator_resolution_id"):
        operator_resume.handle_operator_resume(
            _operator_resume_job(
                run_id=uuid.uuid4(),
                operator_resolution_id=None,
            )
        )


def test_operator_resume_resolution_uuid_scopes_distinct_same_epoch_jobs(fake_repo) -> None:
    first = uuid.uuid4()
    second = uuid.uuid4()
    run_id = uuid.uuid4()

    first_job = fake_repo.enqueue_job(
        kind=JobKind.OPERATOR_RESUME,
        dedup_key=f"operator_resume:{first}",
        run_id=run_id,
        operator_resolution_id=first,
    )
    duplicate = fake_repo.enqueue_job(
        kind=JobKind.OPERATOR_RESUME,
        dedup_key=f"operator_resume:{first}",
        run_id=run_id,
        operator_resolution_id=first,
    )
    second_job = fake_repo.enqueue_job(
        kind=JobKind.OPERATOR_RESUME,
        dedup_key=f"operator_resume:{second}",
        run_id=run_id,
        operator_resolution_id=second,
    )

    assert first_job is not None
    assert duplicate is None
    assert second_job is not None and second_job != first_job


def test_operator_resume_same_resolution_redelivery_is_cas_idempotent(
    fake_repo, monkeypatch
) -> None:
    from app.pipeline import orchestrator
    from app.queue.handlers import operator_resume

    run_id = uuid.uuid4()
    fake_repo.runs[str(run_id)] = _needs_operator_run_row(
        run_id, COASTAL_BIZ_ID, ["Jimmy"]
    )
    fake_repo.runs[str(run_id)]["status"] = RunStatus.RECEIVED.value
    resolution_id = uuid.uuid4()
    overrides = {"Jimmy": "e0000002-0000-0000-0000-000000000002"}
    fake_repo.create_operator_resume_resolution(run_id, resolution_id, overrides)
    winners: list[dict[str, str]] = []

    def _resume(rid, _inbound, *, from_status, overrides, **_kwargs):
        if fake_repo.claim_status(rid, from_status, RunStatus.EXTRACTING):
            winners.append(overrides)

    monkeypatch.setattr(orchestrator, "resume_pipeline", _resume)
    job = _operator_resume_job(
        run_id=run_id,
        operator_resolution_id=resolution_id,
    )

    operator_resume.handle_operator_resume(job)
    operator_resume.handle_operator_resume(job)

    assert winners == [overrides]


def test_fake_operator_resume_context_is_strict_stateful_and_recorded(fake_repo) -> None:
    run_id = uuid.uuid4()
    resolution_id = uuid.uuid4()
    mapping = {"Jimmy": "e0000002-0000-0000-0000-000000000002"}

    with pytest.raises(ValueError, match="operator_resume"):
        fake_repo.enqueue_job(
            kind=JobKind.OPERATOR_RESUME,
            dedup_key=f"operator_resume:{uuid.uuid4()}",
            run_id=run_id,
        )
    with pytest.raises(ValueError, match="operator_resume"):
        fake_repo.enqueue_job(
            kind=JobKind.OPERATOR_RESUME,
            dedup_key=f"operator_resume:{uuid.uuid4()}",
            run_id=run_id,
            email_id=uuid.uuid4(),
            operator_resolution_id=resolution_id,
        )

    fake_repo.create_operator_resume_resolution(run_id, resolution_id, mapping)
    fake_repo.create_operator_resume_resolution(run_id, resolution_id, mapping)
    loaded = fake_repo.load_operator_resume_resolution(run_id, resolution_id)
    loaded["Jimmy"] = "mutated caller copy"

    assert fake_repo.load_operator_resume_resolution(run_id, resolution_id) == mapping
    assert [call[0] for call in fake_repo.context_calls[-4:]] == [
        "create_operator_resume_resolution",
        "create_operator_resume_resolution",
        "load_operator_resume_resolution",
        "load_operator_resume_resolution",
    ]

    claimed_id = fake_repo.enqueue_job(
        kind=JobKind.OPERATOR_RESUME,
        dedup_key=f"operator_resume:{resolution_id}",
        run_id=run_id,
        operator_resolution_id=resolution_id,
    )
    claimed = fake_repo.claim_job()
    assert claimed is not None and claimed.id == claimed_id
    assert claimed.run_id == run_id
    assert claimed.email_id is None
    assert claimed.operator_resolution_id == resolution_id


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

    send_calls: list[dict[str, Any]] = []
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
    import app.pipeline.compose_email as compose_mod
    import app.pipeline.suggest as suggest_mod

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
    # Also patch the names as imported into clarification.py — the import-time binding
    # lives in that module's namespace, so patching the source module is not enough.
    import app.pipeline.clarification as clarification_mod
    monkeypatch.setattr(clarification_mod, "suggest_employees", _fail_suggest)
    monkeypatch.setattr(clarification_mod, "compose_clarification", _fail_compose)

    _clarify(run_id, email, decision, roster, extracted, llm=None, purpose="clarification")

    assert fake_repo.runs[str(run_id)]["status"] == "needs_operator", (
        "at the cap, the run must escalate to needs_operator instead of sending"
    )
    # The round counter must NOT advance further on escalation — escalation is a
    # terminal handoff, not another round.
    assert fake_repo.runs[str(run_id)]["clarification_round"] == MAX_CLARIFICATION_ROUNDS


# ===========================================================================
# 2. escalation is silent — no new outbound email row
# ===========================================================================


def test_escalation_writes_no_outbound_row(fake_repo):
    """Escalating to needs_operator must NOT write any new outbound email row —
    no client-facing signal, no new purpose, no template. The handoff is to the
    operator, so the client sees nothing at all."""
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
        "escalation must write ZERO new outbound rows — the handoff to the operator "
        "is silent to the client"
    )


# ===========================================================================
# 3. escalation write order — set_status(NEEDS_OPERATOR) is the sole/last write
# ===========================================================================


def test_escalation_transaction_writes_only_status():
    """AST pin: the cap-escalation `with conn.transaction():` block in clarify's source
    contains set_status as its ONLY tracked write, and does NOT call
    set_clarification_round — escalation is terminal, so advancing the counter there
    would imply a 4th round that never happens.

    The complementary assertion lives in test_clarify_rounds.py (the cap must precede
    every transaction); this one pins the escalation block's CONTENTS.
    """
    import app.pipeline.clarification as clarification_mod

    with open(clarification_mod.__file__) as f:
        src = f.read()
    tree = ast.parse(src)

    func = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "clarify"
    )

    def _call_name(node: ast.AST) -> str | None:
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

    def _tracked_calls(node: ast.AST) -> list[str | None]:
        return [
            _call_name(stmt)
            for stmt in ast.walk(node)
            if _call_name(stmt)
            in ("set_status", "set_clarification_round", "set_pre_clarify_extracted")
        ]

    escalation_blocks = [
        node for node in tx_blocks if _tracked_calls(node) == ["set_status"]
    ]
    assert len(escalation_blocks) == 1, (
        "exactly one transaction block in clarify must contain ONLY a set_status "
        "call — the cap-escalation block"
    )
    # It must be the textually FIRST transaction block (cap check precedes the
    # (purpose, round) guard and any send path).
    first_block = min(tx_blocks, key=lambda n: n.lineno)
    assert escalation_blocks[0] is first_block, (
        "the escalation-only transaction block must be the FIRST transaction "
        "block in clarify's source — the cap check has to run before the guard "
        "and send paths, or a capped run still does work on its way out"
    )


# ===========================================================================
# 4. scope exclusions
# ===========================================================================


def test_needs_operator_excluded_from_in_flight_statuses():
    """needs_operator must NOT be in IN_FLIGHT_STATUSES — it is a settled human-gate
    state, not a processing state, so the recovery sweep must leave it alone."""
    assert "needs_operator" not in IN_FLIGHT_STATUSES


def test_needs_operator_excluded_from_retrigger_stale_statuses():
    """needs_operator must NOT be one of retrigger's stale_statuses (the
    RECEIVED/EXTRACTING/COMPUTED/SENT scope that governs stale-in-flight reclaim).

    An escalated run's recovery path is the operator's resolve form, not a generic
    retrigger-from-original — retriggering would discard the very context the operator
    was escalated to resolve.

    The stale_statuses set literal lives in `_claim_stale_in_flight`, a conn-aware
    helper `retrigger()` calls as one branch of its winning-claim CAS chain (extracted
    so every claim in retrigger's body can join one caller-owned transaction) — not
    inline in `retrigger` itself.
    """
    import inspect

    import app.routes.runs as runs_mod

    src = inspect.getsource(runs_mod._claim_stale_in_flight)
    tree = ast.parse(src)

    stale_sets = [node for node in ast.walk(tree) if isinstance(node, ast.Set)]
    assert stale_sets, (
        "_claim_stale_in_flight's stale_statuses set literal must be present in its "
        "source"
    )

    def _const_values(set_node: ast.Set) -> list[str]:
        values: list[str] = []
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
        "retrigger's stale_statuses must NEVER include NEEDS_OPERATOR — an escalated "
        "run is waiting on a human, not stranded"
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
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
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
# 6. POST /runs/{run_id}/resolve — server-side roster validation, override
#    application, remember-checkbox bind, claim + resume dispatch
# ===========================================================================


def _needs_operator_run_row(
    run_id: uuid.UUID, business_id: uuid.UUID, unresolved_names: list[str]
) -> dict[str, Any]:
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
        "an invalid employee_id must reject the WHOLE POST — the run must stay at "
        "needs_operator, not silently claim/advance. Client-supplied employee ids are "
        "untrusted: an id off this business's roster would pay the wrong person."
    )


def test_resolve_applies_override_and_claims_on_valid_post(monkeypatch, fake_repo):
    """A fully-valid POST (every employee_id on the roster) applies the override and
    dispatches resume — but does NOT itself claim NEEDS_OPERATOR -> EXTRACTING.

    This test deliberately mocks resume_pipeline: it is a narrow unit test of the
    route's validation/override/remember-checkbox logic in isolation, NOT a proof that
    the run actually advances (see
    test_resolve_drives_real_resume_pipeline_to_awaiting_approval below for the
    end-to-end proof that does NOT mock resume_pipeline).

    Because resume_pipeline is mocked here and never performs its own claim, the run's
    status must stay UNCHANGED at needs_operator immediately after the route returns.
    That is what positively proves the route does not pre-claim: a route that CAS'd the
    status itself would leave the run at 'extracting' with nothing left to drive it —
    a double-CAS that strands the run.
    """
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

    resume_calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
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
    # The route must NOT claim NEEDS_OPERATOR -> EXTRACTING itself. resume_pipeline is
    # mocked here (so it never claims), which means the run's status is left UNCHANGED
    # at needs_operator if and only if the route also refrains from pre-claiming. A
    # route that pre-claimed would show 'extracting' here.
    assert fake_repo.runs[str(run_id)]["status"] == "needs_operator", (
        "the /resolve route must NOT claim NEEDS_OPERATOR -> EXTRACTING itself — "
        "resume_pipeline (mocked here) is the SOLE claimer, and two CAS claimers "
        f"strand the run; got status={fake_repo.runs[str(run_id)]['status']!r}"
    )
    # resume_pipeline (via _operator_resume) must still have been scheduled
    # and invoked with the correct run_id and the validated override mapping.
    assert len(resume_calls) == 1, (
        f"expected exactly one resume_pipeline call, got {resume_calls!r}"
    )
    call_args, call_kwargs = resume_calls[0]
    assert call_args[0] == run_id, (
        f"resume_pipeline must be invoked with this run's id; got {call_args!r}"
    )
    assert call_kwargs.get("from_status") == RunStatus.NEEDS_OPERATOR, (
        f"resume_pipeline must be invoked with from_status=NEEDS_OPERATOR; "
        f"got {call_kwargs!r}"
    )
    assert call_kwargs.get("overrides") == {"Jimmy": str(real_emp_id)}, (
        f"resume_pipeline must receive the validated override mapping; "
        f"got {call_kwargs!r}"
    )
    # The remember-checkbox (checked) must have pre-set the bound candidate so the
    # existing approval-gate write path persists it — the alias is still only written
    # behind the single human gate, never here.
    candidates = fake_repo.runs[str(run_id)].get("alias_candidates") or {}
    assert candidates.get("Jimmy") == {
        "suggested": str(real_emp_id),
        "bound": str(real_emp_id),
    }, f"remember-checked token must be pre-bound; got {candidates!r}"


def test_resolve_checkbox_off_does_not_bind(monkeypatch, fake_repo):
    """Remember-checkbox OFF means override-only: the run is fixed, nothing is learned.

    The operator's one-off correction must not become a permanent alias unless they
    explicitly say so.
    """
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
        "checkbox OFF must NOT set a bound candidate — the override applies to this "
        "run only, and nothing is learned"
    )


# ===========================================================================
# 7. /resolve must NOT double-CAS with resume_pipeline.
#
#    This test drives the REAL resume_pipeline (no monkeypatch of resume_pipeline or
#    _operator_resume) end-to-end from a genuinely-reached needs_operator run, through
#    the real HTTP /resolve route, all the way to awaiting_approval.
#
#    It exists because the mocked sibling above
#    (test_resolve_applies_override_and_claims_on_valid_post) can only assert the
#    route's OWN claim — a double-CAS between the route and resume_pipeline hides
#    completely behind that mock and strands the run at 'extracting' in production.
#    Only an unmocked drive through the real seam can catch it.
# ===========================================================================


def _seed_needs_operator_run_real(
    fake_repo: InMemoryRepo,
    *,
    business_id: uuid.UUID,
    from_addr: str,
    unresolved_token: str,
) -> uuid.UUID:
    """Seed a run that has genuinely reached needs_operator via a real inbound email +
    create_run, then set clarification_round/status/decision/reconciliation to exactly
    the state the round-cap escalation branch leaves behind.

    Status is the ONLY field the escalation touches — it does not rewrite decision,
    reconciliation, or alias_candidates. Setting those fields to anything else would
    fabricate a state the pipeline can never actually produce, and the test would prove
    nothing about the real route.
    """
    eid, _ = fake_repo.insert_inbound_email(
        message_id=f"<{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="payroll hours",
        from_addr=from_addr,
        to_addr="agent@payroll-agent.local",
        body_text=f"{unresolved_token} worked 40 regular hours this week.",
    )
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=eid)

    from app.models.contracts import Decision as _Decision

    decision = _Decision(
        final_action="request_clarification",
        gate_reasons=[f"{unresolved_token}: unresolved"],
        unresolved_names=[unresolved_token],
        missing_fields=[],
        resolutions=[
            NameMatchResult(
                submitted_name=unresolved_token,
                matched_employee_id=None,
                source="none",
                resolved=False,
                reason="no roster match",
            )
        ],
    )
    run = fake_repo.runs[str(run_id)]
    run["status"] = "needs_operator"
    run["clarification_round"] = MAX_CLARIFICATION_ROUNDS
    run["decision"] = decision.model_dump(mode="json")
    run["reconciliation"] = [
        m.model_dump(mode="json") for m in decision.resolutions
    ]
    run["alias_candidates"] = {}
    return run_id


def test_resolve_drives_real_resume_pipeline_to_awaiting_approval(fake_repo, mock_llm):
    """A valid /resolve POST must drive the run all the way to awaiting_approval via the
    REAL resume_pipeline — never stranded at extracting.

    The failure mode this pins: if resolve() pre-claims NEEDS_OPERATOR -> EXTRACTING,
    then _operator_resume -> resume_pipeline(from_status=NEEDS_OPERATOR) attempts a
    SECOND claim_status(NEEDS_OPERATOR -> EXTRACTING), which can never succeed (the
    status is already EXTRACTING). resume_pipeline returns early doing nothing, and the
    run sits at 'extracting' forever with no one to advance it. resume_pipeline must be
    the SOLE claimer.
    """
    unresolved_token = "Jimmy"
    run_id = _seed_needs_operator_run_real(
        fake_repo,
        business_id=COASTAL_BIZ_ID,
        from_addr=COASTAL_EMAIL,
        unresolved_token=unresolved_token,
    )

    # A REAL roster employee on the run's OWN business (James Okafor, Business 1) —
    # passes the route's server-side roster validation naturally via fake_repo's real
    # seeded roster, with no roster monkeypatch needed.
    james_id = uuid.UUID("e0000002-0000-0000-0000-000000000002")

    # The operator-resume path has NO new reply to consume (inbound=None), so the
    # Round-2 branch stays off (clarified_fields is empty) and _run_stages takes the
    # Round-1 path with exactly ONE internal extract() call. The override resolves
    # "Jimmy" -> james_id deterministically, so decide() reaches "process" and
    # _run_stages advances the run COMPUTED -> AWAITING_APPROVAL. No suggestion or
    # draft LLM calls fire on the process branch — hence a single scripted response.
    mock_llm.script = [
        json.dumps(
            {
                "employees": [
                    {"submitted_name": unresolved_token, "hours_regular": "40"}
                ],
                "pay_period_start": "2026-06-15",
                "pay_period_end": None,
            }
        ),
    ]

    response = client.post(
        f"/runs/{run_id}/resolve",
        data={"employee_id_0": str(james_id), "remember_0": "on"},
    )
    assert response.status_code in (200, 303)

    final_run = fake_repo.load_run(run_id)
    assert final_run["status"] != "extracting", (
        "the run must NEVER be stranded at 'extracting' after a valid /resolve POST — "
        "that is the double-CAS strand (route claims, then resume_pipeline's claim "
        f"fails and it no-ops); got status={final_run['status']!r}"
    )
    assert final_run["status"] == RunStatus.AWAITING_APPROVAL.value, (
        "a valid /resolve POST must drive the REAL resume_pipeline all the way "
        f"to awaiting_approval; got status={final_run['status']!r}"
    )

    # Money-path assertion: a real paystub line item was actually computed for James at
    # 40 hours. Asserting the status alone would pass on a bare status flip that paid
    # nobody — the computed value is the only proof the process branch genuinely ran.
    line_items = fake_repo.line_items.get(str(run_id)) or []
    assert line_items, "the process branch must have computed real line items"
    james_items = [
        li for li in line_items if str(getattr(li, "employee_id", None)) == str(james_id)
    ]
    assert james_items, (
        f"expected a computed line item for James Okafor ({james_id}); "
        f"got employee_ids={[getattr(li, 'employee_id', None) for li in line_items]!r}"
    )
