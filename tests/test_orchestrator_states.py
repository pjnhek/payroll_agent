"""Orchestrator state-machine tests (INGEST-04, D-A1-03; FIX A, FIX B, FIX 7).

In-memory mocked-LLM assertions (always run, DB-free via fake_repo): the clean run
drives received → ... → awaiting_approval, persists Extracted + Decision +
reconciliation then advances via set_status SEPARATELY; a stage raise routes
through record_run_error; the orchestrator branches on final_action only and never
reads model_action; extract is called with the code-owned run_id.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest

from app.models.contracts import InboundEmail
from app.pipeline.orchestrator import run_pipeline


def _seed_run(fake_repo, *, business_id, body="Maria Chen 40 regular. James salaried."):
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
        created_at=datetime.now(timezone.utc),
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
    run_id = fake_repo.create_run(business_id=business_id, source_email_id=email_id)
    return run_id


def _coastal_business_id(fake_repo) -> str:
    return fake_repo.contact_to_business["payroll@coastalcleaning.example"]


def _clean_script(mock_llm):
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
        json.dumps({"model_action": "process", "reasons": ["clean"]}),
    ]


# ---------------------------------------------------------------------------
# Clean run → awaiting_approval; persists decision + reconciliation + extracted
# ---------------------------------------------------------------------------


def test_clean_run_reaches_awaiting_approval(fake_repo, mock_llm):
    _clean_script(mock_llm)
    run_id = _seed_run(fake_repo, business_id=_coastal_business_id(fake_repo))

    run_pipeline(run_id)

    run = fake_repo.load_run(run_id)
    assert run["status"] == "awaiting_approval"
    assert run["extracted_data"] is not None
    assert run["decision"] is not None
    assert run["decision"]["final_action"] == "process"
    # NULL reconciliation on a clean run is a FAILURE (D-A3-05).
    assert run["reconciliation"] is not None
    assert len(run["reconciliation"]) == 2
    # Line items were computed and replaced for the run.
    assert str(run_id) in fake_repo.line_items
    assert len(fake_repo.line_items[str(run_id)]) == 2


# ---------------------------------------------------------------------------
# A stage raise → record_run_error (error_reason + ERROR via set_status)
# ---------------------------------------------------------------------------


def test_stage_raise_sets_error(fake_repo, mock_llm, monkeypatch):
    # Force the extract stage to raise by scripting a permanently-invalid payload
    # (a non-numeric value fails BOTH the original call and the retry → raise).
    bad = json.dumps(
        {
            "employees": [{"submitted_name": "Maria Chen", "hours_regular": "forty"}],
            "pay_period_start": "2026-06-15",
        }
    )
    mock_llm.script = [bad, bad]
    run_id = _seed_run(fake_repo, business_id=_coastal_business_id(fake_repo))

    run_pipeline(run_id)

    run = fake_repo.load_run(run_id)
    assert run["status"] == "error", "a stage raise must route to ERROR (D-A1-03)"
    assert run["error_reason"], "the failure reason must be persisted (FIX 7)"


# ---------------------------------------------------------------------------
# Branches on final_action only — never reads model_action
# ---------------------------------------------------------------------------


def test_branches_on_final_action_not_model_action(fake_repo, mock_llm):
    """Feed an unresolved name: the model says 'process' but the gate forces
    clarify, and the orchestrator follows final_action (→ awaiting_reply via the
    draft+send clarify branch), proving it never branches on model_action.

    The residual name triggers the layer-2 reconcile call (extract → reconcile →
    decide → draft), so the FIFO script carries FOUR responses: the reconcile
    wrapper returns an `unknown` (no roster match) so the gate blocks regardless,
    then a free-text clarification body."""
    mock_llm.script = [
        json.dumps(
            {
                "employees": [{"submitted_name": "Totally Unseen Person", "hours_regular": "40"}],
                "pay_period_start": "2026-06-15",
                "pay_period_end": None,
            }
        ),
        json.dumps(
            {
                "matches": [
                    {
                        "submitted_name": "Totally Unseen Person",
                        "matched_employee_id": None,
                        "match_type": "unknown",
                        "confidence": "0.0",
                        "reason": "no roster employee matches",
                    }
                ]
            }
        ),
        json.dumps({"model_action": "process", "reasons": ["model is willing"]}),
        "Hi — we need to confirm one employee name before running payroll.",
    ]
    run_id = _seed_run(fake_repo, business_id=_coastal_business_id(fake_repo))

    run_pipeline(run_id)

    run = fake_repo.load_run(run_id)
    assert run["decision"]["model_action"] == "process"
    assert run["decision"]["final_action"] == "request_clarification"
    assert run["status"] == "awaiting_reply", (
        "orchestrator must follow final_action (gated → draft+send → awaiting_reply)"
    )
    # Reconciliation is persisted even on the clarify branch (D-A3-05).
    assert run["reconciliation"] is not None
    # The clarification was stub-sent and its Message-ID anchored on the outbound row.
    assert fake_repo.get_outbound_message_id(run_id) is not None


def test_orchestrator_source_never_reads_model_action():
    """Source-level: the orchestrator never references model_action."""
    import pathlib

    from app.pipeline import orchestrator

    src = pathlib.Path(orchestrator.__file__).read_text()
    assert src.count("model_action") == 0, (
        "the orchestrator must branch SOLELY on final_action (never model_action)"
    )


def test_extract_called_with_run_id(fake_repo, mock_llm):
    """FIX A: the orchestrator passes the run's run_id into extract → the persisted
    Extracted.run_id matches the run."""
    _clean_script(mock_llm)
    run_id = _seed_run(fake_repo, business_id=_coastal_business_id(fake_repo))

    run_pipeline(run_id)

    run = fake_repo.load_run(run_id)
    assert run["extracted_data"]["run_id"] == str(run_id), (
        "Extracted.run_id must be the code-owned run id (FIX A)"
    )
