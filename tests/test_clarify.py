"""Clarification draft+send tests (CLAR-01; review FIX 3, FIX B, D-A3-05).

A gated run (final_action == request_clarification) drafts a clarification body
(cheap DRAFT_* tier, free text), the stub gateway sends it and records the
synthetic Message-ID on the linked outbound email_messages(direction='outbound',
run_id) row — the SINGLE canonical anchor, NOT a payroll_runs column — and the run
moves to AWAITING_REPLY via repo.set_status (the sole status writer). A draft that
returns empty content falls back to a templated body so a draft failure never
strands the run. The per-name reconciliation is persisted on the gated branch too,
via the SAME persist_reconciliation call as the clean branch (non-NULL on EVERY run).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.contracts import Decision, InboundEmail
from app.pipeline.compose_email import compose_clarification
from app.pipeline.orchestrator import run_pipeline


# ---------------------------------------------------------------------------
# compose_clarification — drafts a body, falls back to a template on empty content
# ---------------------------------------------------------------------------


class _DraftLLM:
    """A call_text stand-in returning a scripted body (or None for empty content)."""

    def __init__(self, body):
        self._body = body
        self.calls: list[tuple] = []

    def call_text(self, tier, messages, temperature=0.7):
        self.calls.append((tier, messages, temperature))
        return self._body


def _gated_decision() -> Decision:
    return Decision(
        model_action="process",
        gate_triggered=True,
        gate_reasons=["David Reyez: confidence 0.6 < 0.8"],
        final_action="request_clarification",
        unresolved_names=["David Reyez"],
        missing_fields=[],
        confidence=Decimal("0.6"),
        reasons=["model is willing"],
    )


def test_compose_uses_draft_tier_free_text():
    """compose_clarification calls the DRAFT tier free-text path (call_text), NOT a
    JSON-mode structured call, and returns the model's prose body."""
    llm = _DraftLLM("Hi — we need to confirm one name before we can run payroll.")
    body = compose_clarification(_gated_decision(), llm=llm)

    assert llm.calls, "compose must call the draft LLM"
    tier, _messages, _temp = llm.calls[0]
    assert tier == "draft", "the clarification draft uses the DRAFT_* tier"
    assert "confirm" in body.lower()


def test_compose_falls_back_to_template_on_empty_content():
    """Empty model content → a templated clarification body (no raise) so a draft
    failure never strands the run. The fallback mentions the unresolved name."""
    llm = _DraftLLM(None)  # empty content
    body = compose_clarification(_gated_decision(), llm=llm)

    assert body, "an empty draft must fall back to a non-empty templated body"
    assert "David Reyez" in body, "the fallback template surfaces the gate detail"


class _RaisingDraftLLM:
    """A call_text stand-in that RAISES (an API error: auth, rate limit, bad model)."""

    def __init__(self, exc=None):
        self._exc = exc or RuntimeError("simulated draft API error (401/429/bad model)")
        self.calls = 0

    def call_text(self, tier, messages, temperature=0.7):
        self.calls += 1
        raise self._exc


def test_compose_falls_back_to_template_on_api_error(caplog):
    """WR-03 — an API error in the draft call must ALSO fall back to the templated
    body (not raise), so a misconfigured draft tier degrades the email rather than
    ERRORing the run. The fallback is logged so the failure is visible."""
    import logging

    llm = _RaisingDraftLLM()
    with caplog.at_level(logging.WARNING):
        body = compose_clarification(_gated_decision(), llm=llm)

    assert llm.calls == 1, "the draft call was attempted"
    assert body, "an API error must fall back to a non-empty templated body, not raise"
    assert "David Reyez" in body, "the fallback template surfaces the gate detail"
    assert any("draft call failed" in r.message for r in caplog.records), (
        "the API-error fallback must be logged so a dead draft tier is visible (WR-03)"
    )


def test_compose_logs_empty_content_fallback(caplog):
    """WR-03 — an empty-content fallback is also logged, so a silently-templating
    draft tier is visible during a demo."""
    import logging

    llm = _DraftLLM(None)  # empty content
    with caplog.at_level(logging.WARNING):
        compose_clarification(_gated_decision(), llm=llm)

    assert any("empty content" in r.message for r in caplog.records), (
        "the empty-content fallback must be logged (WR-03)"
    )


def test_compose_source_not_json_mode():
    """Source-level: compose_email uses call_text (free text), never call_structured
    / json_object."""
    import pathlib

    from app.pipeline import compose_email

    src = pathlib.Path(compose_email.__file__).read_text()
    assert "call_text" in src
    assert "json_object" not in src
    assert "call_structured" not in src


# ---------------------------------------------------------------------------
# End-to-end gated run via the orchestrator: drafts → sends → awaiting_reply
# ---------------------------------------------------------------------------


def _metrodeli_business_id(fake_repo) -> str:
    return fake_repo.contact_to_business["hr@metrodeli.example"]


def _seed_metrodeli_run(fake_repo, *, body="David Reyez 38 regular hours.") -> uuid.UUID:
    """Seed a Metro Deli inbound email + received run (David Reyez gate target)."""
    email = InboundEmail(
        id=uuid.uuid4(),
        message_id=f"<{uuid.uuid4()}@metrodeli.example>",
        in_reply_to=None,
        references_header=None,
        subject="hours",
        from_addr="hr@metrodeli.example",
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
    return fake_repo.create_run(
        business_id=_metrodeli_business_id(fake_repo), source_email_id=email_id
    )


def _david_reyes_id(fake_repo) -> uuid.UUID:
    biz = _metrodeli_business_id(fake_repo)
    for emp in fake_repo.business_employees[str(biz)]:
        if emp.full_name == "David Reyes":
            return emp.id
    raise AssertionError("seeded David Reyes not found")


def _gate_block_script(fake_repo) -> list[str]:
    """The TWO distinct structured mocks (extract → reconcile) + a draft body.

    Reconcile returns David Reyez → llm_typo → David Reyes @ 0.6 (the model is
    WILLING but sub-threshold); the decision-advisory mock says process. The
    orchestrator's FIFO is extract → reconcile → decide → draft."""
    return [
        json.dumps(
            {
                "employees": [{"submitted_name": "David Reyez", "hours_regular": "38"}],
                "pay_period_start": "2026-06-15",
                "pay_period_end": None,
            }
        ),
        json.dumps(
            {
                "matches": [
                    {
                        "submitted_name": "David Reyez",
                        "matched_employee_id": str(_david_reyes_id(fake_repo)),
                        "match_type": "llm_typo",
                        "confidence": "0.6",
                        "reason": "likely a typo of David Reyes",
                    }
                ]
            }
        ),
        json.dumps({"model_action": "process", "reasons": ["model is willing"]}),
        "Hi — we need to confirm one employee name before running payroll.",
    ]


def test_clarify_sends_and_pauses(fake_repo, mock_llm, monkeypatch):
    """A gated run drafts + stub-sends a clarification, records the Message-ID on the
    outbound email_messages row (retrievable via repo.get_outbound_message_id), and
    pauses at awaiting_reply via repo.set_status (CLAR-01, FIX 3, FIX B)."""
    # Capture the outbound send: the stub gateway records the Message-ID on an
    # outbound email_messages row. The in-memory store mirrors get_outbound_message_id.
    sent: dict = {}

    def _fake_send_outbound(*, run_id, to_addr, subject, body, **kw):
        mid = f"<{uuid.uuid4()}@payroll-agent.local>"
        sent[str(run_id)] = {
            "message_id": mid,
            "to_addr": to_addr,
            "subject": subject,
            "body": body,
        }
        return mid

    import app.email.gateway as gateway_mod

    monkeypatch.setattr(gateway_mod, "send_outbound", _fake_send_outbound, raising=True)

    mock_llm.script = _gate_block_script(fake_repo)
    run_id = _seed_metrodeli_run(fake_repo)

    run_pipeline(run_id)

    run = fake_repo.load_run(run_id)
    assert run["status"] == "awaiting_reply", (
        "a gated run must pause at awaiting_reply (CLAR-01), not needs_clarification"
    )
    # The clarification was sent back to the client (the inbound from_addr).
    assert str(run_id) in sent
    assert sent[str(run_id)]["to_addr"] == "hr@metrodeli.example"
    # The outbound Message-ID was minted and is anchored on the outbound row.
    assert sent[str(run_id)]["message_id"].endswith("@payroll-agent.local>")
    # Reconciliation persisted on the gated branch too (D-A3-05, non-NULL).
    assert run["reconciliation"] is not None
    assert len(run["reconciliation"]) == 1


def test_clarify_persists_reconciliation_single_call():
    """Source-level: the orchestrator has exactly ONE persist_reconciliation call,
    reached by BOTH branches (no second call added on the gated branch — D-A3-05)."""
    import pathlib

    from app.pipeline import orchestrator

    src = pathlib.Path(orchestrator.__file__).read_text()
    assert src.count("persist_reconciliation(") == 1, (
        "exactly one persist_reconciliation call, reached before the branch"
    )


def test_no_clarification_message_id_column_written():
    """FIX 3: the Message-ID is NEVER written to a payroll_runs column — it lives
    only on the outbound email_messages row.

    The orchestrator never mentions such a column at all; the repo may DOCUMENT its
    deliberate absence in prose, but must never SET it on payroll_runs (no UPDATE
    payroll_runs ... clarification_message_id)."""
    import pathlib
    import re

    from app.db import repo
    from app.pipeline import orchestrator

    orch_src = pathlib.Path(orchestrator.__file__).read_text()
    assert "clarification_message_id" not in orch_src

    repo_src = pathlib.Path(repo.__file__).read_text()
    # No UPDATE of a payroll_runs clarification_message_id column anywhere.
    assert not re.search(
        r"payroll_runs[^;]*SET[^;]*clarification_message_id", repo_src, re.IGNORECASE | re.DOTALL
    ), "the Message-ID must never be written to a payroll_runs column (FIX 3)"
