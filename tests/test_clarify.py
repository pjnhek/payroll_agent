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
from datetime import UTC, datetime

from app.models.contracts import Decision, InboundEmail
from app.models.roster import NameMatchResult
from app.pipeline.compose_email import compose_clarification
from app.pipeline.orchestrator import run_pipeline

# ---------------------------------------------------------------------------
# compose_clarification — drafts a body, falls back to a template on empty content
# ---------------------------------------------------------------------------


class _DraftLLM:
    """A call_text stand-in returning a scripted body (or None for empty content).

    09-04: **kwargs absorbs compose_clarification's new timeout_s= without
    raising TypeError (mirrors test_compose_confirmation.py's fakes)."""

    def __init__(self, body):
        self._body = body
        self.calls: list[tuple] = []

    def call_text(self, tier, messages, temperature=0.7, **kwargs):
        self.calls.append((tier, messages, temperature))
        self.last_kwargs = kwargs
        return self._body


def _gated_decision() -> Decision:
    """A deterministically-gated Decision (D-21-01/04 shape): David Reyez is
    unresolved, so final_action is request_clarification. No model_action /
    confidence / gate_triggered / reasons exist anymore (the decision is pure
    code over resolution facts)."""
    return Decision(
        final_action="request_clarification",
        gate_reasons=["David Reyez: unresolved (no roster match)"],
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


# ---------------------------------------------------------------------------
# D-21-05 — the suggestion names a SPECIFIC employee (the new Phase 2 hero copy)
# ---------------------------------------------------------------------------


def test_template_names_suggested_employee_when_supplied():
    """When a suggestion is supplied for an unresolved name, the DETERMINISTIC
    template floor names the likely intended employee ("did you mean David
    Reyes?") — so the specific ask survives even a total draft failure (WR-03)."""
    llm = _DraftLLM(None)  # force the template floor
    body = compose_clarification(
        _gated_decision(),
        suggestions={"David Reyez": "David Reyes"},
        llm=llm,
    )

    assert "David Reyez" in body, "the body still surfaces the submitted name"
    assert "David Reyes" in body, "the body names the SPECIFIC suggested employee"
    assert "did you mean" in body.lower(), "the hero copy is a specific did-you-mean ask"


def test_template_generic_fallback_when_no_suggestion():
    """With no suggestion (None / empty), the template falls back to the GENERIC
    ask — it never invents a 'did you mean' for a name we have no suggestion for."""
    llm = _DraftLLM(None)  # force the template floor

    body_none = compose_clarification(_gated_decision(), suggestions=None, llm=llm)
    assert "David Reyez" in body_none
    assert "did you mean" not in body_none.lower(), (
        "no suggestion → no specific did-you-mean line, only the generic ask"
    )

    llm2 = _DraftLLM(None)
    body_empty = compose_clarification(_gated_decision(), suggestions={}, llm=llm2)
    assert "David Reyez" in body_empty
    assert "did you mean" not in body_empty.lower()


def test_compose_threads_suggestion_into_draft_prompt():
    """The suggestion is threaded into the draft prompt so the model can write the
    specific ask — the prompt messages name the suggested employee."""
    llm = _DraftLLM("Hi — did you mean David Reyes? Please confirm.")
    compose_clarification(
        _gated_decision(),
        suggestions={"David Reyez": "David Reyes"},
        llm=llm,
    )

    assert llm.calls, "compose must call the draft LLM"
    _tier, messages, _temp = llm.calls[0]
    prompt_text = " ".join(m["content"] for m in messages)
    assert "David Reyes" in prompt_text, (
        "the suggested employee must be threaded into the draft prompt (D-21-05)"
    )


def test_compose_clarification_passes_bounded_timeout_s():
    """09-04 (Codex HIGH-3): compose_clarification's call_text invocation must pass
    an explicit, non-None timeout_s — previously this call had NO timeout at all,
    the wholly-unbounded gap Codex HIGH-3 flagged."""
    llm = _DraftLLM("Hi — we need to confirm one name before we can run payroll.")
    compose_clarification(_gated_decision(), llm=llm)

    assert llm.calls, "compose must call the draft LLM"
    assert llm.last_kwargs.get("timeout_s") is not None, (
        "compose_clarification must pass a non-None timeout_s= to call_text "
        "(Codex HIGH-3 — this gap was previously wholly unbounded)"
    )


def test_compose_signature_accepts_suggestions():
    """compose_clarification exposes a keyword-only `suggestions` param (the wiring
    contract the orchestrator depends on)."""
    import inspect

    params = inspect.signature(compose_clarification).parameters
    assert "suggestions" in params, "compose_clarification must accept suggestions="


class _RaisingDraftLLM:
    """A call_text stand-in that RAISES (an API error: auth, rate limit, bad model).

    09-04: **kwargs absorbs compose_clarification's new timeout_s= without
    raising TypeError (mirrors test_compose_confirmation.py's fakes)."""

    def __init__(self, exc=None):
        self._exc = exc or RuntimeError("simulated draft API error (401/429/bad model)")
        self.calls = 0

    def call_text(self, tier, messages, temperature=0.7, **kwargs):
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


def test_clarification_subject_threads_on_original():
    """clarification_subject() — WR-05 dropped the dead `decision` param; P6 adds an
    OPTIONAL `original_subject` (used, not ignored) so the clarification threads as a
    reply. No args → the bare constant subject (backward compatible). With the
    original subject → `Re: <original>` so mail clients group the thread. Already
    `Re:`-prefixed input is not double-prefixed."""
    from app.pipeline.compose_email import clarification_subject

    # No args: bare constant subject (Phase-2 / in-app callers, unchanged behavior).
    bare = clarification_subject()
    assert isinstance(bare, str) and bare
    assert not bare.lower().startswith("re:")

    # With original inbound subject: threaded as a reply.
    assert clarification_subject("Payroll hours this week") == "Re: Payroll hours this week"

    # Never double-prefix.
    assert clarification_subject("Re: Payroll hours this week") == "Re: Payroll hours this week"

    # The dropped `decision` misuse is still wrong — a Decision is not a subject string;
    # passing one yields a nonsense subject, but the API no longer pretends to accept it
    # as a meaningful arg (it is positionally the original_subject now). Guard the type
    # contract: callers pass a str | None, never a Decision.
    assert clarification_subject(None) == bare


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
    """The orchestrator FIFO on the clarify branch: extract (structured) → SUGGEST
    (structured) → draft (free text).

    reconcile_names + decide are PURE CODE now (no LLM, no confidence, no
    model_action — D-21-01) so they consume NO scripted response. "David Reyez" is
    not a roster name or stored alias, so the deterministic resolver leaves it
    unresolved and the gate clarifies. The SUGGESTION call (D-21-05) then maps it
    back to "David Reyes" purely for the email copy — it never touches the
    decision. The draft body is last."""
    return [
        json.dumps(
            {
                "employees": [{"submitted_name": "David Reyez", "hours_regular": "38"}],
                "pay_period_start": "2026-06-15",
                "pay_period_end": None,
            }
        ),
        # SUGGESTION (copy only): David Reyez → David Reyes. NEVER feeds decide.
        json.dumps(
            {
                "suggestions": [
                    {
                        "submitted_name": "David Reyez",
                        "suggested_full_name": "David Reyes",
                    }
                ]
            }
        ),
        "Hi — we could not match David Reyez. Did you mean David Reyes?",
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
    # D-21-05 — the SUGGESTION made the sent clarification specific: the body names
    # the suggested employee ("David Reyes"), the new Phase 2 hero copy.
    assert "David Reyes" in sent[str(run_id)]["body"]


def test_clarify_suggestion_never_reaches_the_decision(fake_repo, mock_llm, monkeypatch):
    """T-021-06 — the suggestion is wired AFTER decide and is purely email copy: it
    is NEVER written into the persisted Decision (decision JSONB / reconciliation).

    The deterministic resolver leaves "David Reyez" unresolved; the suggestion maps
    it to "David Reyes" for the email ONLY. The persisted decision must still show
    the name UNRESOLVED with matched_employee_id null — the suggested employee must
    not have leaked into final_action / resolutions."""
    def _fake_send_outbound(*, run_id, to_addr, subject, body, **kw):
        return f"<{uuid.uuid4()}@payroll-agent.local>"

    import app.email.gateway as gateway_mod

    monkeypatch.setattr(gateway_mod, "send_outbound", _fake_send_outbound, raising=True)

    mock_llm.script = _gate_block_script(fake_repo)
    run_id = _seed_metrodeli_run(fake_repo)
    david_id = str(_david_reyes_id(fake_repo))

    run_pipeline(run_id)

    run = fake_repo.load_run(run_id)
    decision = run["decision"]
    # The decision still gates to clarification with the name UNRESOLVED — the
    # suggestion did NOT flip final_action or resolve the name.
    assert decision["final_action"] == "request_clarification"
    assert "David Reyez" in decision["unresolved_names"]
    # The suggested employee id must NOT appear anywhere in the persisted decision
    # or reconciliation — the suggestion is copy only, walled off from the decision.
    assert david_id not in json.dumps(decision), (
        "the suggested employee must never leak into the persisted Decision (T-021-06)"
    )
    for m in run["reconciliation"]:
        assert m["matched_employee_id"] is None, (
            "the unresolved name stays unmatched — the suggestion never resolves it"
        )


def test_orchestrator_suggest_called_after_decide():
    """Source-level: in the orchestrator the suggestion call lives ONLY on the
    clarify branch, AFTER decide has returned (D-21-05). decide() is invoked in
    _run_stages; suggest_employees() is invoked inside _clarify (the else branch),
    so the suggestion can never precede or feed the decision."""
    import pathlib

    from app.pipeline import orchestrator

    src = pathlib.Path(orchestrator.__file__).read_text()
    decide_pos = src.index("decision = decide(")
    suggest_pos = src.index("suggest_employees(")
    assert decide_pos < suggest_pos, (
        "suggest_employees must be called AFTER decide() in the orchestrator source "
        "— the suggestion is wired strictly after the decision (D-21-05)"
    )
    # decide() takes only (extracted, matches, issues) — the suggestion is never an
    # argument to it.
    decide_call = src[decide_pos : src.index(")", decide_pos) + 1]
    assert "suggest" not in decide_call, (
        "the suggestion must never be passed into decide() (D-21-05)"
    )


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
