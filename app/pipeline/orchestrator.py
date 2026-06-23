"""The run state machine (INGEST-04, D-A1-02/03). The plain-Python orchestrator.

run_pipeline(run_id) is the explicit state machine: it loads the run + roster, runs
the four PURE judgment stages in order, persists Extracted + Decision + per-name
reconciliation on EVERY run, then branches SOLELY on Decision.final_action. The
decision is computed deterministically by code (decide.py makes no model call and
reads no score, D-21-01/03; the thesis), so there is no separate advisory action to
diverge from. It is NOT LangGraph; Postgres status IS the durable checkpoint.

Persistence vs status (review FIX B): the persist_* helpers write DATA ONLY; the
orchestrator advances state by calling repo.set_status SEPARATELY (set_status is
the sole status writer). A clean run reaching awaiting_approval NEVER leaves
reconciliation NULL (D-A3-05).

Error-wrap (D-A1-03, FIX 7): the whole run is wrapped in try/except; any unhandled
stage exception routes through repo.record_run_error (which writes
payroll_runs.error_reason AND advances to ERROR via set_status), so a failure
reason is persisted, never lost — nothing silently hangs. PII-safe: the reason is
a stage/exception summary, not the raw email body (T-02-11).

FIX A: the code-owned run_id is passed into extract(..., run_id=run_id, ...) so the
resulting Extracted.run_id is the trusted run id — the model never supplies it.

CLAR-03 resume (Plan 04): resume_pipeline(run_id, inbound) re-enters at extraction
idempotently AND losslessly. It rebuilds the extraction CONTEXT from the ORIGINAL
cleaned inbound body (repo.load_source_email — already cleaned at ingest, FIX C)
combined with the clarification reply body (inbound.body_text), passes the run's
code-owned run_id into extract (FIX A), and OVERWRITES extracted_data wholesale
(persist_extracted is a single JSONB cell, never appended) + replaces line items by
run (DELETE-by-run then insert). Because the re-extraction sees the ORIGINAL body,
employees/hours not mentioned in the reply are RETAINED, not lost (FIX 4). The four
judgment stages are factored into a shared _run_stages() so run_pipeline and
resume_pipeline share the exact same gate path — the eval-reusable spine is DRY.
"""
from __future__ import annotations

import logging
import uuid

from app.db import repo
from app.email import gateway
from app.models.contracts import InboundEmail
from app.models.status import RunStatus
from app.pipeline.calculate import calculate
from app.pipeline.compose_email import clarification_subject, compose_clarification
from app.pipeline.decide import decide
from app.pipeline.extract import extract
from app.pipeline.reconcile_names import reconcile_names
from app.pipeline.suggest import suggest_employees
from app.pipeline.validate import validate

logger = logging.getLogger("payroll_agent.orchestrator")


def run_pipeline(run_id: uuid.UUID, *, llm=None) -> None:
    """Drive one run from received → awaiting_approval (or needs_clarification).

    `llm` is the client module the stages call; defaults to each stage's own
    bound client. Tests inject a mocked client by patching app.llm.client.OpenAI.
    """
    try:
        _run(run_id, llm=llm)
    except Exception as exc:  # noqa: BLE001 — the D-A1-03 error-wrap boundary
        # PII-safe summary: the exception TYPE only — str(exc) can echo prompt text,
        # submitted names, or model output, and this `reason` is BOTH logged AND
        # persisted to payroll_runs.error_reason (review fix). run_id is the
        # correlation key for deeper debugging.
        reason = type(exc).__name__
        logger.warning("run %s failed: %s", run_id, reason)
        repo.record_run_error(run_id, reason)


def _run(run_id: uuid.UUID, *, llm) -> None:
    run = repo.load_run(run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")

    email = repo.load_inbound_email(run_id)
    if email is None:
        raise ValueError(f"run {run_id} has no source email")
    roster = repo.load_roster_for_business(run["business_id"])

    repo.set_status(run_id, RunStatus.EXTRACTING)
    _run_stages(run_id, email, roster, llm=llm)


def resume_pipeline(run_id: uuid.UUID, inbound: InboundEmail, *, llm=None) -> None:
    """Re-enter a paused (awaiting_reply) run at extraction on a clarification reply.

    Idempotent AND lossless (CLAR-03, review FIX 4 + FIX C):
      - The extraction CONTEXT is rebuilt from the ORIGINAL cleaned inbound body
        (repo.load_source_email — persisted cleaned at ingest, NOT re-cleaned) +
        the clarification reply body (inbound.body_text). Because the original body
        is included, employees/hours not mentioned in the reply are RETAINED.
      - extract() is passed the run's CODE-OWNED run_id (FIX A); the model returns
        only an ExtractionPayload and extract stamps the trusted run_id.
      - persist_extracted OVERWRITES extracted_data wholesale (one JSONB cell, never
        appended); replace_line_items DELETE-by-run then insert. So a re-trigger is
        safe and a resume never accumulates stale data (RESEARCH Pattern 6 inv 1-2).

    The webhook is the sole caller and only invokes this after BOTH the header-chain
    match (awaiting_reply only) AND the reply-sender revalidation (FIX 5) have passed.

    Status gate (CR-02, D-12, FOUND-04): uses repo.claim_status(AWAITING_REPLY →
    EXTRACTING) — an atomic conditional UPDATE that closes the residual race from
    Phase 2's load-then-check+set pattern. The prior non-atomic pattern left a window
    where a second reply (or an operator approval) could arrive between the status load
    and the EXTRACTING write; claim_status's WHERE status=%s RETURNING id makes the
    check-and-transition atomic. The losing concurrent caller gets False and drops
    cleanly — no re-run, no ERROR route.
    """
    try:
        # Atomic compare-and-swap: claim the run from AWAITING_REPLY → EXTRACTING.
        # This closes CR-02's residual race (the prior load-then-check+set was non-atomic).
        # A duplicate or late reply sees claim=False and drops cleanly — no re-run,
        # no error. D-12, FOUND-04.
        claimed = repo.claim_status(run_id, RunStatus.AWAITING_REPLY, RunStatus.EXTRACTING)
        if not claimed:
            logger.info(
                "resume aborted: run %s claim failed — late/duplicate reply dropped (CR-02, D-12)",
                run_id,
            )
            return

        # load_run is still needed for business_id and other metadata.
        run = repo.load_run(run_id)
        if run is None:
            raise ValueError(f"run {run_id} not found after claim")
        roster = repo.load_roster_for_business(run["business_id"])

        # Rebuild the combined extraction context (original cleaned body + reply body).
        original_body = repo.load_source_email(run_id) or ""
        combined_email = _combined_context_email(inbound, original_body)

        _run_stages(run_id, combined_email, roster, llm=llm)
    except Exception as exc:  # noqa: BLE001 — the D-A1-03 error-wrap boundary (resume)
        # PII-safe: exception TYPE only — str(exc) can echo submitted names / prompt
        # text, and `reason` is logged AND persisted to error_reason (review fix —
        # the resume path was missed when run_pipeline was sanitized).
        reason = type(exc).__name__
        logger.warning("resume of run %s failed: %s", run_id, reason)
        repo.record_run_error(run_id, reason)


def _combined_context_email(reply: InboundEmail, original_body: str) -> InboundEmail:
    """Build the extraction-input InboundEmail combining the ORIGINAL body + the reply.

    The re-extraction must see BOTH the original hours (so a partial reply doesn't
    drop them) and the clarification answer. The combined body is clearly delimited
    so the model can read the original submission and the correction as one context.
    """
    combined_body = (
        "ORIGINAL PAYROLL EMAIL:\n"
        f"{original_body}\n\n"
        "CLARIFICATION REPLY FROM CLIENT:\n"
        f"{reply.body_text}"
    )
    return reply.model_copy(update={"body_text": combined_body})


def _run_stages(run_id, email, roster, *, llm) -> None:
    """The shared four-stage gate path: extract → reconcile → validate → decide →
    persist → branch. Used by BOTH run_pipeline (first run) and resume_pipeline (the
    CLAR-03 re-entry), so the eval-reusable spine and the gate stay DRY and identical.
    """
    # --- the four PURE judgment stages (DB-free; run_id is code-owned, FIX A) ---
    extract_kwargs = {"run_id": run_id}
    if llm is not None:
        extract_kwargs["llm"] = llm
    extracted = extract(email, roster, **extract_kwargs)

    submitted_names = [e.submitted_name for e in extracted.employees]
    matches = reconcile_names(submitted_names, roster)  # pure: no llm (D-21-01)
    issues = validate(extracted, roster, matches)

    decision = decide(extracted, matches, issues)  # pure: no llm, no score (D-21-01)

    # --- persist DATA on EVERY run BEFORE branching (D-A3-05); OVERWRITES on resume ---
    repo.persist_extracted(run_id, extracted)
    repo.persist_decision(run_id, decision)  # data-only (FIX B), two-arg call
    repo.persist_reconciliation(run_id, matches)  # never NULL on a clean run

    # --- branch SOLELY on final_action (the code-owned deterministic decision) ---
    if decision.final_action == "process":
        line_items = _compute_line_items(run_id, extracted, matches, roster)
        repo.replace_line_items(run_id, line_items)  # DELETE-by-run then insert
        repo.set_status(run_id, RunStatus.COMPUTED)
        repo.set_status(run_id, RunStatus.AWAITING_APPROVAL)  # HITL-01 pause
    else:  # request_clarification — draft + stub-send, pause at AWAITING_REPLY
        _clarify(run_id, email, decision, roster, llm=llm)


def _clarify(run_id, email, decision, roster, *, llm) -> None:
    """Draft a clarification, stub-send it, and pause the run at AWAITING_REPLY.

    The cheap DRAFT_* tier drafts the body (templated fallback on empty content so
    a draft failure never strands the run, CLAR-01). gateway.send_outbound mints a
    synthetic Message-ID and records it on the linked
    email_messages(direction='outbound', run_id) row — the SINGLE canonical anchor
    Plan 04 reads back via the header chain (FIX 3); there is NO payroll_runs
    Message-ID column. Status advances via repo.set_status (the sole writer, FIX B).
    The clarification threads off the client's inbound message_id (In-Reply-To +
    References) so the reply chain resolves in Plan 04.

    D-21-05 — the suggestion-only call: BEFORE composing, ask the cheap (draft) tier
    which roster employee each unresolved name most likely meant, and pass that as
    `suggestions=` so the clarification can be SPECIFIC ("did you mean David
    Reyes?"). CRITICAL: this runs ONLY here, on the request_clarification branch,
    STRICTLY AFTER `decide` has already returned (decision is a parameter, computed
    upstream in _run_stages). The suggestion is advisory COPY — it is NEVER passed
    to decide and NEVER influences final_action. A suggestion failure degrades to
    {} inside suggest_employees, so it can never strand the run.
    """
    # Like compose below: only pass `llm` when injected (a test mock). When llm is
    # None (production), suggest_employees binds its own default client — passing
    # llm=None would force the cheap call onto a None client and silently degrade
    # every suggestion to the generic ask.
    suggest_kwargs = {}
    if llm is not None:
        suggest_kwargs["llm"] = llm
    suggestions = suggest_employees(
        decision.unresolved_names, roster, **suggest_kwargs
    )

    compose_kwargs = {"suggestions": suggestions}
    if llm is not None:
        compose_kwargs["llm"] = llm
    body = compose_clarification(decision, **compose_kwargs)

    gateway.send_outbound(
        run_id=run_id,
        to_addr=email.from_addr,
        subject=clarification_subject(),
        body=body,
        in_reply_to=email.message_id,
        references_header=email.message_id,
    )
    repo.set_status(run_id, RunStatus.AWAITING_REPLY)  # CLAR-01 pause


def _compute_line_items(run_id, extracted, matches, roster):
    """Build PaystubLineItems for the resolved (matched) employees on a process run."""
    match_by_name = {m.submitted_name: m for m in matches}
    emp_by_id = {e.id: e for e in roster.employees}

    items = []
    for ee in extracted.employees:
        m = match_by_name.get(ee.submitted_name)
        if m is None or m.matched_employee_id is None:
            continue  # unresolved names never reach a process run (gate blocks them)
        employee = emp_by_id.get(m.matched_employee_id)
        if employee is None:
            # WR-01: on a PROCESS run the gate guarantees every name is resolved to a
            # roster employee. A matched_employee_id with no roster row (e.g. a stale
            # reconciliation persisted against a since-changed roster, or a roster
            # loaded for the wrong business) is an INVARIANT VIOLATION, not an expected
            # skip — silently omitting the employee would ship an incomplete payroll the
            # operator is told is clean. Fail LOUD: raise so the run routes to ERROR
            # (D-A1-03 error-wrap) instead of computing a degraded paystub.
            raise ValueError(
                f"process-run integrity: matched employee {m.matched_employee_id} "
                f"for {ee.submitted_name!r} is not in the loaded roster"
            )
        resolved_hours = {
            "hours_regular": ee.hours_regular,
            "hours_overtime": ee.hours_overtime,
            "hours_vacation": ee.hours_vacation,
            "hours_sick": ee.hours_sick,
            "hours_holiday": ee.hours_holiday,
        }
        item = calculate(
            resolved_hours, employee, ee.contribution_401k_override
        )
        # Stamp the real run identity + the submitted name (the per-name provenance;
        # there is no score on a deterministic resolution, D-21-01/04).
        item = item.model_copy(
            update={
                "run_id": run_id,
                "submitted_name": ee.submitted_name,
            }
        )
        items.append(item)
    return items
