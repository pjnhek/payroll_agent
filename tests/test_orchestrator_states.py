"""Orchestrator state-machine tests (INGEST-04).

In-memory mocked-LLM assertions (always run, DB-free via fake_repo): the clean run
drives received → ... → awaiting_approval, persists Extracted + Decision +
reconciliation then advances via set_status SEPARATELY; a stage raise returns a
bounded PipelineResult without terminal persistence; the orchestrator branches on
final_action only; extract is called with the code-owned run_id.

The reconcile + decide stages are PURE deterministic code — they take no
llm and make no model call — so the only LLM-scripted calls in these flows are the
extract stage and (on the clarify branch) the free-text clarification draft. The
FIFO mock_llm script therefore carries ONE extract response (+ one draft string on a
clarify run), NOT the dead layer-2 reconcile / advisory-decide responses.
"""
from __future__ import annotations

# This module uses deliberately small dynamic test doubles and monkeypatch seams.
import ast
import json
import pathlib
import uuid
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
from pydantic import BaseModel, ValidationError

from app.models.contracts import InboundEmail
from app.models.status import RunStatus
from app.pipeline.orchestrator import resume_pipeline, run_pipeline
from app.pipeline.result import (
    PipelineOutcome,
    PipelineReason,
    PipelineResult,
    PipelineStage,
    classify_pipeline_exception,
    normalize_pipeline_result,
)


class _RequiredExtractionPayload(BaseModel):
    employee_name: str


def _provider_status_error(
    status_code: int, *, message: str = "provider failure"
) -> APIStatusError:
    request = httpx.Request("POST", "https://provider.invalid/v1/chat/completions")
    response = httpx.Response(status_code, request=request)
    if status_code == 429:
        return RateLimitError(message, response=response, body={"detail": "sensitive"})
    return APIStatusError(message, response=response, body={"detail": "sensitive"})


# ---------------------------------------------------------------------------
# Pipeline result contract and exception classification
# ---------------------------------------------------------------------------


def test_pipeline_result_defaults_fail_closed_and_are_frozen():
    result = PipelineResult()

    assert result.outcome is PipelineOutcome.TERMINAL
    assert result.stage is PipelineStage.UNKNOWN
    assert result.reason is PipelineReason.UNCLASSIFIED
    assert result.diagnostic_code == "unknown:unclassified"
    with pytest.raises(FrozenInstanceError):
        result.outcome = PipelineOutcome.OK  # type: ignore[misc]


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (
            APIConnectionError(
                message="connection failed after employee SECRET-NAME",
                request=httpx.Request("POST", "https://provider.invalid"),
            ),
            PipelineReason.PROVIDER_CONNECTION_FAILURE,
        ),
        (
            APITimeoutError(httpx.Request("POST", "https://provider.invalid")),
            PipelineReason.PROVIDER_TIMEOUT,
        ),
        (_provider_status_error(429), PipelineReason.PROVIDER_RATE_LIMIT),
        (_provider_status_error(500), PipelineReason.PROVIDER_SERVER_FAILURE),
        (_provider_status_error(503), PipelineReason.PROVIDER_SERVER_FAILURE),
    ],
)
def test_extraction_provider_classification_is_retryable_only_for_named_cases(exc, reason):
    result = classify_pipeline_exception(PipelineStage.EXTRACT, exc)

    assert result == PipelineResult(
        outcome=PipelineOutcome.RETRYABLE,
        stage=PipelineStage.EXTRACT,
        reason=reason,
    )


def test_extraction_schema_failure_classification_is_terminal():
    with pytest.raises(ValidationError) as caught:
        _RequiredExtractionPayload.model_validate({})

    result = classify_pipeline_exception(PipelineStage.EXTRACT, caught.value)

    assert result == PipelineResult(
        outcome=PipelineOutcome.TERMINAL,
        stage=PipelineStage.EXTRACT,
        reason=PipelineReason.SCHEMA_OR_PARSE_FAILURE,
    )


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (_provider_status_error(400), PipelineReason.CLIENT_REQUEST_FAILURE),
        (_provider_status_error(401), PipelineReason.CLIENT_REQUEST_FAILURE),
        (RuntimeError("employee SECRET-NAME in raw provider body"), PipelineReason.UNCLASSIFIED),
    ],
)
def test_extraction_terminal_classification_counterexamples(exc, reason):
    result = classify_pipeline_exception(PipelineStage.EXTRACT, exc)

    assert result == PipelineResult(
        outcome=PipelineOutcome.TERMINAL,
        stage=PipelineStage.EXTRACT,
        reason=reason,
    )


@pytest.mark.parametrize("stage", [PipelineStage.CLARIFICATION, PipelineStage.DELIVERY])
@pytest.mark.parametrize(
    "exc",
    [
        APIConnectionError(
            message="provider accepted possibly-sensitive message",
            request=httpx.Request("POST", "https://provider.invalid"),
        ),
        APITimeoutError(httpx.Request("POST", "https://provider.invalid")),
        _provider_status_error(429),
        _provider_status_error(503),
    ],
)
def test_ambiguous_send_stage_classification_is_terminal(stage, exc):
    result = classify_pipeline_exception(stage, exc)

    assert result == PipelineResult(
        outcome=PipelineOutcome.TERMINAL,
        stage=stage,
        reason=PipelineReason.AMBIGUOUS_SEND_FAILURE,
    )


def test_pipeline_result_never_retains_sensitive_exception_content():
    sensitive = "employee SECRET-NAME; provider body SECRET-BODY"
    exc = APIConnectionError(
        message=sensitive,
        request=httpx.Request("POST", "https://provider.invalid"),
    )

    result = classify_pipeline_exception(PipelineStage.EXTRACT, exc)
    serialized = f"{result!r}|{result}|{result.diagnostic_code}"

    assert sensitive not in serialized
    assert "SECRET-NAME" not in serialized
    assert "SECRET-BODY" not in serialized
    assert all(
        isinstance(value, (PipelineOutcome, PipelineStage, PipelineReason))
        for value in (result.outcome, result.stage, result.reason)
    )


# ---------------------------------------------------------------------------
# Temporary legacy-result compatibility adapter
# ---------------------------------------------------------------------------


def test_legacy_result_none_maps_to_one_coarse_ok_result():
    first = normalize_pipeline_result(None)
    second = normalize_pipeline_result(None)

    assert first is second
    assert first == PipelineResult(
        outcome=PipelineOutcome.OK,
        stage=PipelineStage.UNKNOWN,
        reason=PipelineReason.UNCLASSIFIED,
    )


@pytest.mark.parametrize(
    "result",
    [
        PipelineResult(outcome=PipelineOutcome.OK),
        PipelineResult(
            outcome=PipelineOutcome.RETRYABLE,
            stage=PipelineStage.EXTRACT,
            reason=PipelineReason.PROVIDER_TIMEOUT,
        ),
        PipelineResult(
            outcome=PipelineOutcome.TERMINAL,
            stage=PipelineStage.DELIVERY,
            reason=PipelineReason.AMBIGUOUS_SEND_FAILURE,
        ),
    ],
)
def test_legacy_result_preserves_every_explicit_result(result):
    assert normalize_pipeline_result(result) is result


@pytest.mark.parametrize("value", [False, 0, "ok", object()])
def test_legacy_result_rejects_every_other_runtime_value(value):
    with pytest.raises(TypeError, match="PipelineResult or None"):
        normalize_pipeline_result(value)


def test_pipeline_result_source_guard_requires_explicit_producers_without_error_persistence():
    from app.pipeline import orchestrator

    tree = ast.parse(pathlib.Path(orchestrator.__file__).read_text())
    functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    run_pipeline_node = functions["run_pipeline"]
    resume_pipeline_node = functions["resume_pipeline"]
    private_run_node = functions["_run"]
    for node in (run_pipeline_node, private_run_node, resume_pipeline_node):
        assert isinstance(node.returns, ast.Name)
        assert node.returns.id == "PipelineResult"
        assert not any(
            isinstance(child, ast.Return) and child.value is None
            for child in ast.walk(node)
        )

    def _calls_record_run_error(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        return any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "record_run_error"
            for child in ast.walk(node)
        )

    assert not _calls_record_run_error(private_run_node)
    assert not _calls_record_run_error(resume_pipeline_node)


def _seed_run(
    fake_repo: Any, *, business_id: uuid.UUID, body: str = "Maria Chen 40 regular. James salaried."
) -> uuid.UUID:
    """Insert a cleaned inbound email + a received run into the in-memory store."""
    email = InboundEmail(
        id=uuid.uuid4(),
        message_id=f"<{uuid.uuid4()}@coastalcleaning.example>",
        in_reply_to=None,
        references_header=None,
        subject="hours",
        from_addr="payroll@coastalcleaning.example",
        to_addr="agent@payroll-agent.local",
        body_text=body,
        created_at=datetime.now(UTC),
    )
    email_id, _ = fake_repo.insert_inbound_email(
        message_id=email.message_id,
        in_reply_to=None,
        references_header=None,
        subject=email.subject,
        from_addr=email.from_addr,
        to_addr=email.to_addr,
        body_text=email.body_text,
    )
    run_id: uuid.UUID = fake_repo.create_run(business_id=business_id, source_email_id=email_id)
    return run_id


def _coastal_business_id(fake_repo: Any) -> uuid.UUID:
    business_id: uuid.UUID = fake_repo.contact_to_business["payroll@coastalcleaning.example"]
    return business_id


def _clean_script(mock_llm: Any) -> None:
    """Script ONLY the extract call. Maria Chen + James Okafor are exact seed-roster
    names (Business 1), so reconcile resolves both deterministically and decide
    (pure code) returns final_action='process' — no LLM reconcile/decide responses."""
    mock_llm.script = [
        json.dumps(
            {
                "employees": [
                    {"submitted_name": "Maria Chen", "hours_regular": "40"},
                    {"submitted_name": "James Okafor"},
                ],
                "pay_period_start": "2026-06-15",
                "pay_period_end": None,
            }
        ),
    ]


# ---------------------------------------------------------------------------
# Clean run → awaiting_approval; persists decision + reconciliation + extracted
# ---------------------------------------------------------------------------


def test_clean_run_reaches_awaiting_approval(fake_repo, mock_llm):
    _clean_script(mock_llm)
    run_id = _seed_run(fake_repo, business_id=_coastal_business_id(fake_repo))

    result = run_pipeline(run_id)

    run = fake_repo.load_run(run_id)
    assert result.outcome is PipelineOutcome.OK
    assert run["status"] == "awaiting_approval"
    assert run["extracted_data"] is not None
    assert run["decision"] is not None
    assert run["decision"]["final_action"] == "process"
    # NULL reconciliation on a clean run is a FAILURE.
    assert run["reconciliation"] is not None
    assert len(run["reconciliation"]) == 2
    # Line items were computed and replaced for the run.
    assert str(run_id) in fake_repo.line_items
    assert len(fake_repo.line_items[str(run_id)]) == 2


# ---------------------------------------------------------------------------
# Stage failures → bounded results without orchestrator-owned terminal persistence
# ---------------------------------------------------------------------------


def test_extraction_result_classification_is_retryable_without_persisting_error(
    fake_repo, monkeypatch
):
    import app.pipeline.orchestrator as orchestrator_module

    sensitive = "employee SECRET-NAME in provider payload"
    run_id = _seed_run(fake_repo, business_id=_coastal_business_id(fake_repo))
    persisted_errors: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        orchestrator_module,
        "extract",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            APIConnectionError(
                message=sensitive,
                request=httpx.Request("POST", "https://provider.invalid"),
            )
        ),
    )
    monkeypatch.setattr(
        orchestrator_module.repo,
        "record_run_error",
        lambda *args, **_kwargs: persisted_errors.append(args),
    )

    result = run_pipeline(run_id)

    run = fake_repo.load_run(run_id)
    assert result == PipelineResult(
        outcome=PipelineOutcome.RETRYABLE,
        stage=PipelineStage.EXTRACT,
        reason=PipelineReason.PROVIDER_CONNECTION_FAILURE,
    )
    assert run["status"] == RunStatus.EXTRACTING.value
    assert run["error_reason"] is None
    assert persisted_errors == []
    assert "SECRET-NAME" not in repr(result)


def test_compute_result_classification_is_terminal_without_persisting_error(
    fake_repo, mock_llm, monkeypatch
):
    import app.pipeline.orchestrator as orchestrator_module

    _clean_script(mock_llm)
    run_id = _seed_run(fake_repo, business_id=_coastal_business_id(fake_repo))
    persisted_errors: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        orchestrator_module,
        "_compute_line_items",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("employee SECRET-NAME in compute failure")
        ),
    )
    monkeypatch.setattr(
        orchestrator_module.repo,
        "record_run_error",
        lambda *args, **_kwargs: persisted_errors.append(args),
    )

    result = run_pipeline(run_id)

    assert result == PipelineResult(
        outcome=PipelineOutcome.TERMINAL,
        stage=PipelineStage.COMPUTE,
        reason=PipelineReason.UNCLASSIFIED,
    )
    run = fake_repo.load_run(run_id)
    assert run["status"] == RunStatus.EXTRACTING.value
    assert run["error_reason"] is None
    assert persisted_errors == []
    assert "SECRET-NAME" not in repr(result)


def test_persist_result_classification_is_terminal_without_persisting_error(
    fake_repo, mock_llm, monkeypatch
):
    import app.pipeline.orchestrator as orchestrator_module

    _clean_script(mock_llm)
    run_id = _seed_run(fake_repo, business_id=_coastal_business_id(fake_repo))
    persisted_errors: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        orchestrator_module.repo,
        "persist_extracted",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("employee SECRET-NAME in persistence failure")
        ),
    )
    monkeypatch.setattr(
        orchestrator_module.repo,
        "record_run_error",
        lambda *args, **_kwargs: persisted_errors.append(args),
    )

    result = run_pipeline(run_id)

    assert result == PipelineResult(
        outcome=PipelineOutcome.TERMINAL,
        stage=PipelineStage.PERSIST,
        reason=PipelineReason.UNCLASSIFIED,
    )
    assert fake_repo.load_run(run_id)["error_reason"] is None
    assert persisted_errors == []


def test_clarification_result_classification_is_terminal_and_attempts_send_once(
    fake_repo, mock_llm, monkeypatch
):
    import app.pipeline.orchestrator as orchestrator_module

    mock_llm.script = [
        json.dumps(
            {
                "employees": [
                    {"submitted_name": "Unknown Person", "hours_regular": "40"}
                ],
                "pay_period_start": "2026-06-15",
                "pay_period_end": None,
            }
        )
    ]
    run_id = _seed_run(fake_repo, business_id=_coastal_business_id(fake_repo))
    send_attempts = 0

    def _fail_ambiguous_send(*_args, **_kwargs):
        nonlocal send_attempts
        send_attempts += 1
        raise APIConnectionError(
            message="provider may have accepted SECRET-NAME",
            request=httpx.Request("POST", "https://provider.invalid"),
        )

    monkeypatch.setattr(orchestrator_module.clarification, "clarify", _fail_ambiguous_send)

    result = run_pipeline(run_id)

    assert result == PipelineResult(
        outcome=PipelineOutcome.TERMINAL,
        stage=PipelineStage.CLARIFICATION,
        reason=PipelineReason.AMBIGUOUS_SEND_FAILURE,
    )
    assert send_attempts == 1
    assert fake_repo.load_run(run_id)["error_reason"] is None


def test_resume_claim_loser_returns_coarse_ok_result(fake_repo):
    run_id = _seed_run(fake_repo, business_id=_coastal_business_id(fake_repo))

    result = resume_pipeline(run_id, _inbound_for_result_test())

    assert result == PipelineResult(outcome=PipelineOutcome.OK)


def _inbound_for_result_test() -> InboundEmail:
    return InboundEmail(
        id=uuid.uuid4(),
        message_id=f"<reply-{uuid.uuid4()}@test.example>",
        in_reply_to=None,
        references_header=None,
        subject="Re: hours",
        from_addr="payroll@coastalcleaning.example",
        to_addr="agent@payroll-agent.local",
        body_text="Maria Chen 40 regular",
        created_at=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------
# Branches on final_action — an unresolved name deterministically gates to clarify
# ---------------------------------------------------------------------------


def test_unresolved_name_gates_to_clarify(fake_repo, mock_llm):
    """Feed a name absent from the roster: the deterministic resolver leaves it
    unresolved, decide (pure code) sets final_action='request_clarification', and the
    orchestrator follows final_action into the draft+send clarify branch (→
    awaiting_reply). The FIFO script carries the extract response then the free-text
    clarification draft — reconcile + decide make NO LLM call."""
    mock_llm.script = [
        json.dumps(
            {
                "employees": [{"submitted_name": "Totally Unseen Person", "hours_regular": "40"}],
                "pay_period_start": "2026-06-15",
                "pay_period_end": None,
            }
        ),
        "Hi — we need to confirm one employee name before running payroll.",
    ]
    run_id = _seed_run(fake_repo, business_id=_coastal_business_id(fake_repo))

    result = run_pipeline(run_id)

    run = fake_repo.load_run(run_id)
    assert result.outcome is PipelineOutcome.OK
    assert run["decision"]["final_action"] == "request_clarification"
    # The unresolved name is recorded in the deterministic decision.
    assert "Totally Unseen Person" in run["decision"]["unresolved_names"]
    assert run["status"] == "awaiting_reply", (
        "orchestrator must follow final_action (gated → draft+send → awaiting_reply)"
    )
    # Reconciliation is persisted even on the clarify branch.
    assert run["reconciliation"] is not None
    # The clarification was stub-sent and its Message-ID anchored on the outbound row.
    assert fake_repo.get_outbound_message_id(run_id) is not None


def test_process_run_missing_roster_employee_raises():
    """A process run whose resolved match points at an employee_id NOT in the
    loaded roster is an INVARIANT VIOLATION; _compute_line_items must raise, never
    silently drop the employee and ship a short payroll.

    The deterministic resolver can only ever resolve a name to an employee that IS in
    the loaded roster, so this invariant can no longer be reached through the normal
    gate path (the old layer-2 LLM could route a name to an arbitrary id; it is gone,
    the roster). The defensive guard still exists for a stale persisted reconciliation /
    wrong-business roster, so it is exercised directly: hand _compute_line_items a
    resolved NameMatchResult whose matched_employee_id is absent from the roster and
    assert it raises with an integrity message.
    """
    from app.db.seed import seed
    from app.models.contracts import Extracted, ExtractedEmployee
    from app.models.roster import NameMatchResult, Roster
    from app.pipeline.orchestrator import _compute_line_items

    seeded = seed(dry_run=True)
    business_id = seeded.employees[0].business_id
    roster = Roster(
        business_id=business_id,
        employees=[e for e in seeded.employees if e.business_id == business_id],
    )

    ghost_employee_id = uuid.uuid4()  # resolved id NOT in the loaded roster
    extracted = Extracted(
        run_id=uuid.uuid4(),
        employees=[ExtractedEmployee(submitted_name="Mariana Sandoval", hours_regular="40")],
        pay_period_start="2026-06-15",
    )
    matches = [
        NameMatchResult(
            submitted_name="Mariana Sandoval",
            matched_employee_id=ghost_employee_id,
            source="exact",
            resolved=True,
            reason="resolved but points at a non-roster id (stale reconciliation)",
        )
    ]

    with pytest.raises(ValueError, match="integrity"):
        _compute_line_items(extracted.run_id, extracted, matches, roster)


def test_orchestrator_source_never_reads_model_action():
    """Source-level: the orchestrator never references model_action."""
    import pathlib

    from app.pipeline import orchestrator

    src = pathlib.Path(orchestrator.__file__).read_text()
    assert src.count("model_action") == 0, (
        "the orchestrator must branch SOLELY on final_action (never model_action)"
    )


def test_extract_called_with_run_id(fake_repo, mock_llm):
    """The orchestrator passes the run's run_id into extract → the persisted
    Extracted.run_id matches the run."""
    _clean_script(mock_llm)
    run_id = _seed_run(fake_repo, business_id=_coastal_business_id(fake_repo))

    run_pipeline(run_id)

    run = fake_repo.load_run(run_id)
    assert run["extracted_data"]["run_id"] == str(run_id), (
        "Extracted.run_id must be the code-owned run id, never model output"
    )
