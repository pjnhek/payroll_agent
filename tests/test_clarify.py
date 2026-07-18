"""Clarification draft+send tests (CLAR-01).

A gated run (final_action == request_clarification) drafts a clarification body on the
cheap drafting tier, the gateway sends it and records the synthetic Message-ID on the
linked outbound email_messages row, and the run moves to AWAITING_REPLY.

The invariants these tests hold in place:

- The Message-ID anchor lives on the email_messages row and NOWHERE else — never a
  payroll_runs column. One canonical anchor means the reply-threading lookup can never
  disagree with the audit log.
- A draft that returns empty content (or errors) falls back to a TEMPLATED body. The
  clarification still goes out and still names the suggested employee, so a dead
  drafting tier degrades the prose but never strands the run at awaiting_reply with no
  email sent.
- The per-name reconciliation is persisted on the GATED branch too, through the same
  persist_reconciliation call the clean branch uses — so reconciliation is non-NULL on
  EVERY run and the operator can always see why the gate fired.
- The suggestion is email copy only: it must never reach decide or the persisted
  Decision.
"""
from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from app.models.contracts import Decision, Extracted, InboundEmail
from app.models.job import Job, JobKind
from app.models.roster import NameMatchResult
from app.pipeline.compose_email import compose_clarification
from app.pipeline.orchestrator import run_pipeline


def _script_exact_handoff_release(fake_conn: Any) -> None:
    """Script exact current-handoff ownership before a delivery settlement."""
    fake_conn.script_fetchone((uuid.uuid4(), datetime.now(UTC)))
    fake_conn.script_fetchone((uuid.uuid4(),))

# ---------------------------------------------------------------------------
# compose_clarification — drafts a body, falls back to a template on empty content
# ---------------------------------------------------------------------------


class _DraftLLM:
    """A call_text stand-in returning a scripted body (or None for empty content).

    **kwargs absorbs compose_clarification's timeout_s= without raising TypeError, so
    adding a new keyword to the real call site does not break this double.
    """

    def __init__(self, body: str | None):
        self._body = body
        self.calls: list[tuple[Any, Any, float]] = []

    def call_text(
        self, tier: Any, messages: Any, temperature: float = 0.7, **kwargs: Any
    ) -> str | None:
        self.calls.append((tier, messages, temperature))
        self.last_kwargs = kwargs
        return self._body


def _gated_decision() -> Decision:
    """A deterministically-gated Decision: David Reyez is unresolved, so final_action
    is request_clarification.

    There is no model_action, confidence, or gate_triggered field — the decision is pure
    code over the resolution facts, so there is nothing for a model to disagree with.
    """
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
# The suggestion names a SPECIFIC employee — even on the deterministic floor
# ---------------------------------------------------------------------------


def test_template_names_suggested_employee_when_supplied():
    """The template floor names the likely intended employee, not just the typo.

    "Did you mean David Reyes?" is a question a client can answer in one word; "we could
    not match 'David Reyez'" is not. The specific ask lives in the DETERMINISTIC
    template, so it survives even a total draft-tier failure.
    """
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
        "the suggested employee must be threaded into the draft prompt, or the model "
        "cannot write the specific did-you-mean ask"
    )


def test_compose_clarification_passes_bounded_timeout_s():
    """compose_clarification must pass an explicit, non-None timeout_s to call_text.

    Every LLM call in the pipeline must be time-bounded. An unbounded draft call can
    hang a run for as long as the provider keeps the socket open — which on a sleeping
    free-tier dyno means the run is simply stranded, with the client never asked.
    """
    llm = _DraftLLM("Hi — we need to confirm one name before we can run payroll.")
    compose_clarification(_gated_decision(), llm=llm)

    assert llm.calls, "compose must call the draft LLM"
    assert llm.last_kwargs.get("timeout_s") is not None, (
        "compose_clarification must pass a non-None timeout_s= to call_text — an "
        "unbounded draft call can hang the run indefinitely"
    )


def test_compose_signature_accepts_suggestions():
    """compose_clarification exposes a keyword-only `suggestions` param (the wiring
    contract the orchestrator depends on)."""
    import inspect

    params = inspect.signature(compose_clarification).parameters
    assert "suggestions" in params, "compose_clarification must accept suggestions="


class _RaisingDraftLLM:
    """A call_text stand-in that RAISES (an API error: auth, rate limit, bad model).

    **kwargs absorbs compose_clarification's timeout_s= without raising TypeError, so
    adding a new keyword to the real call site does not break this double.
    """

    def __init__(self, exc: Exception | None = None):
        self._exc = exc or RuntimeError("simulated draft API error (401/429/bad model)")
        self.calls = 0

    def call_text(self, tier: Any, messages: Any, temperature: float = 0.7, **kwargs: Any) -> str:
        self.calls += 1
        raise self._exc


def test_compose_falls_back_to_template_on_api_error(caplog):
    """An API error in the draft call falls back to the template rather than raising.

    A misconfigured or rate-limited drafting tier must degrade the EMAIL, never fail the
    RUN — the client still gets asked, just in the template's words. The fallback is
    logged at WARNING so a permanently-dead draft tier is visible instead of silently
    templating forever.
    """
    import logging

    llm = _RaisingDraftLLM()
    with caplog.at_level(logging.WARNING):
        body = compose_clarification(_gated_decision(), llm=llm)

    assert llm.calls == 1, "the draft call was attempted"
    assert body, "an API error must fall back to a non-empty templated body, not raise"
    assert "David Reyez" in body, "the fallback template surfaces the gate detail"
    assert any("draft call failed" in r.message for r in caplog.records), (
        "the API-error fallback must be logged, or a dead draft tier is invisible"
    )


def test_compose_logs_empty_content_fallback(caplog):
    """The empty-content fallback is logged too.

    An empty draft response produces a perfectly serviceable templated email, so nothing
    downstream looks wrong. Without the log line, a drafting tier that has quietly
    stopped returning content would go unnoticed straight through a demo.
    """
    import logging

    llm = _DraftLLM(None)  # empty content
    with caplog.at_level(logging.WARNING):
        compose_clarification(_gated_decision(), llm=llm)

    assert any("empty content" in r.message for r in caplog.records), (
        "the empty-content fallback must be logged"
    )


def test_clarification_subject_threads_on_original():
    """clarification_subject() threads the clarification onto the original email.

    It takes an OPTIONAL `original_subject`, which it uses rather than ignores: with it,
    the subject becomes `Re: <original>` so mail clients group the conversation; without
    it, the bare constant subject. An already-`Re:`-prefixed input is not double-prefixed.
    """
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
    return str(fake_repo.contact_to_business["hr@metrodeli.example"])


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
    return uuid.UUID(str(fake_repo.create_run(
        business_id=_metrodeli_business_id(fake_repo), source_email_id=email_id
    )))


def _david_reyes_id(fake_repo) -> uuid.UUID:
    biz = _metrodeli_business_id(fake_repo)
    for emp in fake_repo.business_employees[str(biz)]:
        if emp.full_name == "David Reyes":
            return uuid.UUID(str(emp.id))
    raise AssertionError("seeded David Reyes not found")


def _gate_block_script(fake_repo) -> list[str]:
    """The orchestrator FIFO on the clarify branch: extract (structured) → SUGGEST
    (structured) → draft (free text).

    reconcile_names + decide are PURE CODE — no LLM, no confidence, no model action —
    so they consume NO scripted response. If either ever did, this FIFO would desync and
    the draft would receive the suggestion's JSON, which is exactly the failure a script
    entry for those stages should cause. "David Reyez" is not a roster name or a stored
    alias, so the deterministic resolver leaves it unresolved and the gate clarifies. The
    SUGGESTION call then maps it back to "David Reyes" purely for the email copy — it
    never touches the decision. The draft body is last.
    """
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


def test_clarify_reserves_and_queues_before_pausing(fake_repo, mock_llm, monkeypatch):
    """A gated run freezes one clarification slot, queues it, then awaits a reply."""
    from app.queue import wake

    def _direct_send_is_forbidden(**_kwargs):
        raise AssertionError("clarification producer must not call the provider directly")

    wake_calls: list[None] = []
    import app.email.gateway as gateway_mod

    monkeypatch.setattr(gateway_mod, "send_outbound", _direct_send_is_forbidden, raising=True)
    monkeypatch.setattr(wake, "wake", lambda: wake_calls.append(None))

    mock_llm.script = _gate_block_script(fake_repo)
    run_id = _seed_metrodeli_run(fake_repo)

    run_pipeline(run_id)

    run = fake_repo.load_run(run_id)
    assert run["status"] == "awaiting_reply", (
        "a gated run must pause at awaiting_reply (CLAR-01), not needs_clarification"
    )
    outbound = fake_repo.outbound[str(run_id)]
    assert len(outbound) == 1
    assert outbound[0]["send_state"] == "reserved"
    snapshot = fake_repo.load_outbound_snapshot(run_id, outbound[0]["id"])
    assert snapshot is not None
    assert snapshot["to_addr"] == "hr@metrodeli.example"
    assert snapshot["message_id"].endswith("@demo.payroll-agent.local>")
    assert snapshot["in_reply_to"] is not None
    assert snapshot["references_header"] == snapshot["in_reply_to"]
    jobs = [job for job in fake_repo.jobs.values() if job["kind"] == "send_outbound"]
    assert len(jobs) == 1
    assert jobs[0]["email_id"] == snapshot["email_id"]
    assert wake_calls == [None]
    # Reconciliation is persisted on the GATED branch too, so it is non-NULL on every
    # run and the operator can always see why the gate fired.
    assert run["reconciliation"] is not None
    assert len(run["reconciliation"]) == 1
    # The suggestion made the frozen clarification SPECIFIC: the client can confirm with
    # a single word when the queued worker delivers this exact snapshot.
    assert "David Reyes" in snapshot["body_text"]


def test_clarify_reentry_reuses_the_frozen_slot_before_drafting(
    fake_repo, mock_llm, monkeypatch
):
    """A stale re-entry schedules the original slot without a second draft or key."""
    from app.db import repo
    from app.pipeline.clarification import clarify

    mock_llm.script = _gate_block_script(fake_repo)
    run_id = _seed_metrodeli_run(fake_repo)
    run_pipeline(run_id)

    original = fake_repo.outbound[str(run_id)][0]
    original_snapshot = fake_repo.load_outbound_snapshot(run_id, original["id"])
    assert original_snapshot is not None
    fake_repo.runs[str(run_id)]["clarification_round"] = 0

    def _should_not_draft(*_args, **_kwargs):
        raise AssertionError("a frozen clarification must be read before drafting")

    monkeypatch.setattr("app.pipeline.clarification.suggest_employees", _should_not_draft)
    monkeypatch.setattr("app.pipeline.clarification.compose_clarification", _should_not_draft)

    run = fake_repo.load_run(run_id)
    inbound = repo.load_inbound_email(run_id)
    assert inbound is not None
    clarify(
        run_id,
        inbound,
        Decision.model_validate(run["decision"]),
        repo.load_roster_for_business(run["business_id"]),
        Extracted.model_validate(run["extracted_data"]),
        llm=mock_llm,
    )

    replayed = fake_repo.load_outbound_snapshot(run_id, original["id"])
    assert replayed == original_snapshot
    assert fake_repo.runs[str(run_id)]["clarification_round"] == 1
    assert fake_repo.runs[str(run_id)]["status"] == "awaiting_reply"
    jobs = [job for job in fake_repo.jobs.values() if job["kind"] == "send_outbound"]
    assert len(jobs) == 1


def test_clarify_suggestion_never_reaches_the_decision(fake_repo, mock_llm, monkeypatch):
    """The suggestion is email copy and must NEVER reach the persisted Decision.

    The deterministic resolver leaves "David Reyez" unresolved; the suggestion maps it to
    "David Reyes" for the email ONLY. The persisted decision must still show the name
    UNRESOLVED with matched_employee_id null. If the suggested employee ever leaked into
    final_action or resolutions, the LLM would have silently decided who gets paid —
    which is the one thing this system exists to prevent.
    """
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
        "the suggested employee must never leak into the persisted Decision — that "
        "would be the LLM deciding who gets paid"
    )
    for m in run["reconciliation"]:
        assert m["matched_employee_id"] is None, (
            "the unresolved name stays unmatched — the suggestion never resolves it"
        )


def test_orchestrator_suggest_called_after_decide():
    """Source-level: the suggestion is wired strictly AFTER decide, across two modules.

    decide() lives in orchestrator.py; suggest_employees() lives in clarification.py's
    clarify(). Because the two are in different files, a single-file ordering check would
    be vacuous — so this asserts the invariant on BOTH sides of the boundary:
      - orchestrator.py: decide() is called, and the clarify branch calls
        clarification.clarify(...) — never suggest_employees directly;
      - clarification.py: suggest_employees() is present, and decide( is ABSENT entirely.

    Checking only the orchestrator side would let someone call decide() from inside
    clarification.py, AFTER the suggestion — reversing the very ordering this protects.
    """
    import pathlib

    from app.pipeline import clarification, orchestrator

    orch_src = pathlib.Path(orchestrator.__file__).read_text()
    decide_pos = orch_src.index("decision = decide(")
    clarify_call_pos = orch_src.index("clarification.clarify(")
    assert decide_pos < clarify_call_pos, (
        "clarification.clarify must be called AFTER decide() in the orchestrator "
        "source — the suggestion is wired strictly after the decision"
    )
    # decide() takes only (extracted, matches, issues) — the suggestion is never an
    # argument to it.
    decide_call = orch_src[decide_pos : orch_src.index(")", decide_pos) + 1]
    assert "suggest" not in decide_call, (
        "the suggestion must never be passed into decide()"
    )

    clarification_src = pathlib.Path(clarification.__file__).read_text()
    assert "suggest_employees(" in clarification_src, (
        "suggest_employees must be called inside clarification.py's clarify()"
    )
    assert "decide(" not in clarification_src, (
        "clarification.py must never call decide() — the suggestion is advisory copy "
        "only and must never precede or feed the decision; decide() stays exclusively "
        "in orchestrator.py's _run_stages"
    )


def test_clarify_persists_reconciliation_single_call():
    """Source-level: exactly ONE persist_reconciliation call, reached by BOTH branches.

    Placing the call before the branch is what guarantees reconciliation is non-NULL on
    every run. A second call added inside the gated branch would be the first step back
    toward one branch forgetting to persist it at all.
    """
    import pathlib

    from app.pipeline import orchestrator

    src = pathlib.Path(orchestrator.__file__).read_text()
    assert src.count("persist_reconciliation(") == 1, (
        "exactly one persist_reconciliation call, reached before the branch"
    )


def test_no_clarification_message_id_column_written():
    """The Message-ID is NEVER written to a payroll_runs column.

    It lives only on the outbound email_messages row — a single canonical anchor. A
    duplicate copy on payroll_runs could drift out of sync with the append-only audit
    log, and reply threading would then match against a Message-ID the system never
    actually sent. Prose may DOCUMENT the column's deliberate absence; nothing may SET it.
    """
    import importlib
    import inspect
    import pathlib
    import pkgutil
    import re

    import app.db.repo as repo_pkg
    from app.pipeline import orchestrator

    orch_src = pathlib.Path(orchestrator.__file__).read_text()
    assert "clarification_message_id" not in orch_src

    # The facade (repo.__file__) contains no SQL at all, so scanning it alone would make
    # this test vacuous — the scan must cover EVERY module in the package, exactly as
    # test_gateway.py's test_repo_has_no_fstring_sql does. Enumerate the package
    # DYNAMICALLY so a new aggregate module — or SQL added to _shared.py — cannot
    # silently escape the scan.
    modules = {
        m.name: importlib.import_module(f"app.db.repo.{m.name}")
        for m in pkgutil.iter_modules(repo_pkg.__path__)
    }
    known = {"_shared", "demo", "emails", "pipeline_state", "roster", "runs"}
    assert known <= set(modules), (
        f"repo package enumeration lost a known module: {sorted(known - set(modules))}"
    )
    repo_src = "".join(inspect.getsource(m) for m in modules.values())
    # No UPDATE of a payroll_runs clarification_message_id column anywhere.
    assert not re.search(
        r"payroll_runs[^;]*SET[^;]*clarification_message_id", repo_src, re.IGNORECASE | re.DOTALL
    ), "the Message-ID must never be written to a payroll_runs column"


# ---------------------------------------------------------------------------
# Durable clarification delivery settlement
# ---------------------------------------------------------------------------


def _leased_clarification_send_job() -> Job:
    """Return the frozen send-job context used by delivery settlement tests."""
    return Job(
        id=uuid.uuid4(),
        kind=JobKind.SEND_OUTBOUND,
        run_id=uuid.uuid4(),
        email_id=uuid.uuid4(),
        attempts=1,
        max_attempts=8,
        lease_token=uuid.uuid4(),
    )


def test_clarification_delivery_success_preserves_reply_workflow(fake_conn):
    """A sent clarification completes only its frozen slot and leaves reply state intact."""
    from app.db.repo.job_settlement import SettlementOutcome, settle_outbound_delivery_job
    from app.pipeline.result import PipelineOutcome, PipelineReason, PipelineResult, PipelineStage

    job = _leased_clarification_send_job()
    fake_conn.script_fetchone((1, 8, job.run_id, "send_outbound", job.email_id))
    fake_conn.script_fetchone(
        (uuid.uuid4(), datetime.now(UTC), "clarification", 3, 7, "reserved", True)
    )
    fake_conn.script_fetchone(("awaiting_reply",))
    _script_exact_handoff_release(fake_conn)
    fake_conn.script_fetchone((uuid.uuid4(),))
    fake_conn.script_fetchone((uuid.uuid4(),))
    fake_conn.script_fetchone((uuid.uuid4(),))

    outcome = settle_outbound_delivery_job(
        job,
        PipelineResult(
            outcome=PipelineOutcome.OK,
            stage=PipelineStage.DELIVERY,
            reason=PipelineReason.UNCLASSIFIED,
        ),
        conn=fake_conn,
    )

    assert outcome is SettlementOutcome.DONE
    sql = fake_conn.all_sql()
    assert "message.purpose, message.round, message.epoch" in sql
    assert "UPDATE email_messages SET send_state = 'sent'" in sql
    assert "UPDATE payroll_runs SET status = 'sent'" not in sql
    assert "UPDATE payroll_runs SET status = 'needs_operator'" not in sql
    assert "clarification_round" not in sql
    assert "in_reply_to =" not in sql
    assert "references_header =" not in sql


def test_clarification_delivery_retry_reschedules_only_the_original_job(fake_conn):
    """A transient clarification failure remains a reply wait and keeps its thread facts."""
    from app.db.repo.job_settlement import SettlementOutcome, settle_outbound_delivery_job
    from app.pipeline.result import PipelineOutcome, PipelineReason, PipelineResult, PipelineStage

    job = _leased_clarification_send_job()
    fake_conn.script_fetchone((1, 8, job.run_id, "send_outbound", job.email_id))
    fake_conn.script_fetchone(
        (uuid.uuid4(), datetime.now(UTC), "clarification_field_regression", 2, 4, "reserved", True)
    )
    fake_conn.script_fetchone(("awaiting_reply",))
    _script_exact_handoff_release(fake_conn)
    fake_conn.script_fetchone((uuid.uuid4(),))
    fake_conn.script_fetchone((uuid.uuid4(),))

    outcome = settle_outbound_delivery_job(
        job,
        PipelineResult(
            outcome=PipelineOutcome.RETRYABLE,
            stage=PipelineStage.DELIVERY,
            reason=PipelineReason.DELIVERY_TIMEOUT,
        ),
        conn=fake_conn,
    )

    assert outcome is SettlementOutcome.RETRIED
    sql = fake_conn.all_sql()
    assert "state = 'pending', available_at = %s" in sql
    assert "UPDATE email_messages" not in sql
    assert "UPDATE payroll_runs" not in sql
    assert "clarification_round" not in sql
    assert "in_reply_to =" not in sql
    assert "references_header =" not in sql


def test_fenced_clarification_delivery_loser_preserves_reply_workflow(fake_conn):
    """A reclaimed clarification lease cannot alter the stored reply workflow."""
    from app.db.repo.job_settlement import SettlementOutcome, settle_outbound_delivery_job
    from app.pipeline.result import PipelineResult

    job = _leased_clarification_send_job()
    fake_conn.script_fetchone(None)

    assert (
        settle_outbound_delivery_job(job, PipelineResult(), conn=fake_conn)
        is SettlementOutcome.LOST_LEASE
    )
    sql = fake_conn.all_sql()
    assert "INSERT INTO outbound_delivery_attempts" not in sql
    assert "UPDATE email_messages" not in sql
    assert "UPDATE payroll_runs" not in sql
    assert "UPDATE jobs" not in sql


def test_terminal_clarification_delivery_uses_reply_safe_escalation(fake_conn):
    """A non-replayable clarification becomes an operator reply issue, never confirmation review."""
    from app.db.repo.job_settlement import SettlementOutcome, settle_outbound_delivery_job
    from app.pipeline.result import PipelineOutcome, PipelineReason, PipelineResult, PipelineStage

    job = _leased_clarification_send_job()
    fake_conn.script_fetchone((1, 8, job.run_id, "send_outbound", job.email_id))
    fake_conn.script_fetchone(
        (uuid.uuid4(), datetime.now(UTC), "clarification", 1, 2, "reserved", True)
    )
    fake_conn.script_fetchone(("awaiting_reply",))
    _script_exact_handoff_release(fake_conn)
    fake_conn.script_fetchone((uuid.uuid4(),))
    fake_conn.script_fetchone((uuid.uuid4(),))
    fake_conn.script_fetchone((uuid.uuid4(),))

    outcome = settle_outbound_delivery_job(
        job,
        PipelineResult(
            outcome=PipelineOutcome.TERMINAL,
            stage=PipelineStage.DELIVERY,
            reason=PipelineReason.DELIVERY_CONFIGURATION_FAILURE,
        ),
        conn=fake_conn,
    )

    assert outcome is SettlementOutcome.DONE
    sql = fake_conn.all_sql()
    assert "UPDATE payroll_runs SET status = 'needs_operator'" in sql
    assert "UPDATE payroll_runs SET status = 'sent'" not in sql
    assert "UPDATE email_messages" not in sql
    review_params = [
        params
        for statement, params in fake_conn.executed
        if "needs_operator" in str(statement)
    ]
    assert review_params == [
        (
            "ClarificationDeliveryReview",
            "delivery_review:configuration",
            str(job.run_id),
            "awaiting_reply",
        )
    ]
