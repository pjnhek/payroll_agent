"""HTTP-to-orchestrator bridge helpers (BOUND-01).

Every router imports these via a module-object import
(`from app.routes import pipeline_glue`), NEVER a bare-name import. A bare-name
import would bind the function object at import time, and the tests'
`monkeypatch.setattr(pipeline_glue, <fn>)` seams would silently stop taking
effect — the router would keep calling the real orchestrator.
"""
from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from typing import Any, cast

from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.db import repo
from app.models.contracts import Decision, InboundEmail
from app.models.job import JobKind
from app.models.status import RunStatus
from app.pipeline.result import (
    PipelineOutcome,
    PipelineReason,
    PipelineResult,
    PipelineStage,
    normalize_pipeline_result,
)
from app.queue import wake

logger = logging.getLogger("payroll_agent.webhook")


def row_to_inbound(row: dict[str, Any]) -> InboundEmail:
    """Build an InboundEmail from a PERSISTED email_messages row dict.

    The single conversion point reused by both the duplicate-redelivery re-schedule
    and the stranded-unconsumed-reply runs-list auto-resume. Pure — no DB I/O.

    Uses `row["body_text"]` VERBATIM. That column already holds the body cleaned at
    first ingest — the authoritative, actually-processed text. This helper must NEVER
    re-clean it: a redelivered webhook's request body can diverge from what was
    persisted, and re-cleaning would resume the run against text the run never saw.

    `row` must supply the full InboundEmail field set (id, message_id, in_reply_to,
    references_header, subject, from_addr, to_addr, body_text, created_at). Both
    `repo.get_inbound_by_message_id` and `repo.find_stranded_unconsumed_replies`
    return exactly this shape (plus run_id, which this helper ignores — the caller
    already has it).
    """
    return InboundEmail(
        id=row["id"],
        message_id=row["message_id"],
        in_reply_to=row.get("in_reply_to"),
        references_header=row.get("references_header"),
        subject=row.get("subject") or "",
        from_addr=row.get("from_addr") or "",
        to_addr=row.get("to_addr") or "",
        body_text=row["body_text"],
        created_at=row["created_at"],
    )


def reply_sender_ok(row: dict[str, Any], run: dict[str, Any]) -> bool:
    """Re-assert the reply sender revalidation for an already-persisted reply row.

    A reply is linked to its run INSIDE the webhook's ingest transaction based purely
    on the RFC header chain (in_reply_to/references). Those headers are
    attacker-controllable and are NOT authentication. The real authentication gate is
    `find_business_by_sender` matching the run's business — the SAME comparison
    `finish_reply_resume` performs post-commit at first delivery.

    But that guard runs only ONCE, on the first delivery. Any OTHER seam capable of
    re-dispatching `resume_pipeline_bg` from a persisted, linked-but-unconsumed reply
    row (a webhook redelivery, a later stranded-reply sweep) must re-assert it too.
    Otherwise a spoofed reply that already failed the sender check once — and was
    therefore left linked+unconsumed, which is exactly the state those seams resume
    from — can still drive the run to payroll. This is that shared predicate, reused
    by both re-schedule seams.

    Calls `find_business_by_sender` exactly ONCE (assigned to a local first).
    """
    reply_business_id = repo.find_business_by_sender(row.get("from_addr") or "")
    return reply_business_id is not None and str(reply_business_id) == str(
        run.get("business_id")
    )


def finish_reply_resume(
    run_id: uuid.UUID,
    email: InboundEmail,
    cleaned: str,
    background_tasks: BackgroundTasks,
) -> JSONResponse:
    """Post-commit sender-revalidation + response-shaping for a reply-resume candidate.

    Called AFTER the webhook's ingest transaction has ALREADY classified this inbound
    as a reply-resume candidate (`find_awaiting_reply_for_header` found `run_id` INSIDE
    that transaction). This helper does NOT re-run that header lookup — re-deriving the
    classification post-commit reintroduces the duplicate-run race in a different shape.
    It only performs the sender re-validation (a pure read-then-branch with no write, so
    it is safe outside the transaction) and shapes the response / schedules the resume.
    """
    # Re-assert the reply sender against the matched run's business (the original
    # inbound sender / businesses.contact_email). Same comparison
    # find_business_by_sender performs at first ingest (INGEST-03). The header chain
    # alone is forgeable — this is the gate that stops a spoofed reply from steering
    # someone else's payroll run.
    run = repo.load_run(run_id)
    expected_business_id = run["business_id"] if run else None
    reply_business_id = repo.find_business_by_sender(email.from_addr)
    if reply_business_id is None or str(reply_business_id) != str(
        expected_business_id
    ):
        logger.warning(
            "reply sender from_addr=%s does NOT match run %s business — "
            "not resumed (spoof guard)",
            email.from_addr,
            run_id,
        )
        return JSONResponse(
            status_code=200,
            content={"status": "sender_mismatch", "run_id": str(run_id)},
        )

    # Sender revalidated → schedule the resume (idempotent + lossless).
    # Do NOT flip the run to EXTRACTING here. The orchestrator owns that transition
    # (resume_pipeline, which re-asserts the run is still awaiting_reply under the
    # same code path that mutates it). Setting EXTRACTING in the webhook — a DIFFERENT
    # context from the BackgroundTask that does the work — is the exact seam the status
    # race lived in, and it would also defeat resume_pipeline's own precondition: the
    # run would already be EXTRACTING and never awaiting_reply, so the resume would
    # refuse to claim it and the reply would be dropped on the floor.
    # The run stays awaiting_reply until the background resume claims it.
    reply_for_resume = email.model_copy(update={"body_text": cleaned})
    background_tasks.add_task(resume_pipeline_bg, run_id, reply_for_resume)
    return JSONResponse(
        status_code=200,
        content={"status": "resumed", "run_id": str(run_id)},
    )


def route_reply(
    email: InboundEmail, cleaned: str, background_tasks: BackgroundTasks
) -> JSONResponse | None:
    """Route a header-bearing inbound as a clarification reply, or None to fall through.

    Used by `simulate_reply` (the demo-only affordance) and any other caller that has
    NOT already classified the inbound inside a transaction — it performs its OWN header
    lookups. The real webhook's `inbound()` route does NOT call this: it classifies the
    reply INSIDE its ingest transaction and then calls `finish_reply_resume` for the
    sender revalidation + response shaping, so the header lookups are never re-derived
    a second time on that path (re-deriving them post-commit reopens the duplicate-run
    race the transaction exists to close).

    The header chain is the only routing path (CLAR-02): the reply's In-Reply-To /
    References are matched against stored outbound Message-IDs. There is deliberately no
    subject/provider-thread fallback.

    Decision flow:
      1. find_awaiting_reply_for_header — match restricted to status='awaiting_reply'.
         On a match: delegate to `finish_reply_resume` (sender re-assertion + response
         shaping + background scheduling).
      2. Else find_any_run_for_header — a header match to a run in ANY OTHER status
         (sent/reconciled/rejected/computed) is a LATE REPLY: log it, do NOT resume.
         Resuming an already-advanced run would re-drive a settled payroll
         (CLAR-03 invariant 4).
      3. No header match at all → return None so the caller treats it as an ordinary
         inbound (first ingest).

    Return contract — read this before branching on the result. A JSONResponse is
    returned on EVERY header match, with the body's {"status": ...} distinguishing the
    outcome: "resumed" (background resume scheduled), "sender_mismatch" (spoof guard),
    or "late_reply". A non-None return does NOT mean "not resumed". None means ONLY
    "no header match; fall through to ordinary first ingest" — treating None as the
    success signal inverts the whole contract.
    """
    run_id = repo.find_awaiting_reply_for_header(
        in_reply_to=email.in_reply_to,
        references_header=email.references_header,
    )
    if run_id is not None:
        return finish_reply_resume(run_id, email, cleaned, background_tasks)

    # No awaiting_reply match — is it a LATE reply to an already-advanced run?
    late_run_id = repo.find_any_run_for_header(
        in_reply_to=email.in_reply_to,
        references_header=email.references_header,
    )
    if late_run_id is not None:
        logger.info(
            "late reply: header matched run %s not in awaiting_reply — not resumed",
            late_run_id,
        )
        return JSONResponse(
            status_code=200,
            content={"status": "late_reply", "run_id": str(late_run_id)},
        )

    # No header match → fall through to ordinary first ingest.
    return None


def resume_pipeline_now(
    run_id: uuid.UUID,
    inbound: InboundEmail | None,
    *,
    from_status: RunStatus = RunStatus.AWAITING_REPLY,
    overrides: dict[str, str] | None = None,
) -> PipelineResult | None:
    """Invoke the temporary producer contract and propagate its exact result."""
    from app.pipeline.orchestrator import resume_pipeline

    resume = cast(Callable[..., PipelineResult | None], resume_pipeline)
    return resume(
        run_id,
        inbound,
        from_status=from_status,
        overrides=overrides,
    )


def _consume_background_result(
    run_id: uuid.UUID,
    value: PipelineResult | None,
    *,
    kind: JobKind,
    email_id: uuid.UUID | None = None,
) -> None:
    """Hand one first-attempt result to the durable failure policy."""
    result = normalize_pipeline_result(value)
    if result.outcome is PipelineOutcome.OK:
        return
    if result.outcome is PipelineOutcome.TERMINAL:
        repo.settle_background_terminal(run_id, result)
        return

    from app.queue.drain import _backoff_seconds

    settled = repo.enqueue_classified_retry(
        run_id,
        result,
        kind=kind,
        email_id=email_id,
        available_in_seconds=_backoff_seconds(1),
    )
    if settled is repo.SettlementOutcome.RETRIED:
        wake.wake()


def resume_pipeline_bg(run_id: uuid.UUID, inbound: InboundEmail) -> None:
    """Background wrapper for resume_pipeline (mirrors run_pipeline_bg's safety net).

    resume_pipeline owns its own try/except error-wrap and persists ERROR on stage
    failure; this outer guard only ensures a catastrophic START failure (e.g. the
    orchestrator failing to import) cannot escape the BackgroundTask. The webhook has
    already returned 200, so a background crash must be logged, never raised."""
    try:
        result = resume_pipeline_now(run_id, inbound)
        _consume_background_result(
            run_id,
            result,
            kind=JobKind.RESUME_REPLY,
            email_id=inbound.id,
        )
    except Exception:  # noqa: BLE001 — background safety net; webhook already 200'd
        logger.error("resume failed to start for run_id=%s", run_id)


def run_pipeline_now(run_id: uuid.UUID) -> PipelineResult | None:
    """Run the orchestrator and let whatever escapes it PROPAGATE to the caller.

    WHAT ACTUALLY ESCAPES — be precise here, because the useful contract is much narrower
    than "catastrophic failures retry", and an over-broad promise in this docstring reads
    as a guarantee the code does not make. `run_pipeline` owns a catch-all that persists
    ERROR on the run and then returns NORMALLY. So a stage failure never reaches here — and
    neither does a transient database error on the pipeline's first read, which is caught,
    recorded as ERROR, and returned. The ONLY things that escape are the failures the
    orchestrator's own boundary could not RECORD: the orchestrator module failing to
    import, or `record_run_error` itself failing (usually the same outage that caused the
    original failure).

    That line is the right one, and it is worth stating as the rule it is: **if the
    orchestrator managed to write ERROR, a human can SEE the run and retrigger it — the job
    did its work and completes. If it could write nothing at all, the failure is invisible
    to everyone (no ERROR on the run, no operator prompt), so the job MUST retry rather
    than complete, or the run is lost with no trace.** Retry is the fallback for failures
    nobody can see, not a general retry policy. Auto-retrying a recorded transient DB error
    into a genuine re-run is a SEPARATE design decision and is deliberately not made here.

    This is the entrypoint for the caller that can act on that: the queue's `drain_once`,
    which routes an escaping exception into a fenced `fail_job` write with backoff and
    retries up to `max_attempts`.

    Never route a queued job through `run_pipeline_bg` instead. That wrapper's swallow is
    right for a fire-and-forget BackgroundTask and fatal for a queued job: the handler would
    return normally, `drain_once` would read that as success and mark the job `done`, and
    the durable row that was the run's only chance of ever executing would be deleted. A
    payroll run, silently lost.
    """
    from app.pipeline.orchestrator import run_pipeline

    run = cast(Callable[[uuid.UUID], PipelineResult | None], run_pipeline)
    return run(run_id)


def run_pipeline_bg(run_id: uuid.UUID) -> None:
    """Fire-and-forget wrapper for the FastAPI BackgroundTask path (the inbound webhook).

    Swallows a catastrophic start failure because the webhook has ALREADY returned 200 to
    the email gateway — there is no caller left to hand an exception to, and an escaping
    background crash would take down the request's task group. Logged, never raised.

    A caller that CAN act on a start failure must use `run_pipeline_now` instead; see its
    docstring for why routing a queued job through this swallow loses the run.
    """
    try:
        result = run_pipeline_now(run_id)
        _consume_background_result(run_id, result, kind=JobKind.RUN_PIPELINE)
    except Exception:  # noqa: BLE001 — background safety net; webhook already 200'd
        logger.error("pipeline failed to start for run_id=%s", run_id)


def _load_operator_resume_mapping(
    run_id: uuid.UUID,
    operator_resolution_id: uuid.UUID,
) -> dict[str, str] | None:
    """Reload and validate one complete durable operator authority generation."""
    try:
        run = repo.load_run(run_id)
        if run is None:
            return None
        decision = Decision.model_validate(run.get("decision"))
        unresolved = decision.unresolved_names
        if not unresolved or len(unresolved) != len(set(unresolved)):
            return None
        overrides = repo.load_operator_resume_resolution(
            run_id, operator_resolution_id
        )
        if set(overrides) != set(unresolved):
            return None
        roster = repo.load_roster_for_business(run["business_id"])
        roster_ids = {str(employee.id) for employee in roster.employees}
        if any(employee_id not in roster_ids for employee_id in overrides.values()):
            return None
        return overrides
    except (KeyError, TypeError, ValueError, ValidationError):
        return None


def operator_resume_bg(
    run_id: uuid.UUID, operator_resolution_id: uuid.UUID
) -> None:
    """Consume one committed operator generation through the durable result policy."""
    try:
        overrides = _load_operator_resume_mapping(run_id, operator_resolution_id)
        if overrides is None:
            invalid = PipelineResult(
                stage=PipelineStage.LOAD,
                reason=PipelineReason.INVALID_OPERATOR_OVERRIDE_CONTEXT,
            )
            repo.settle_background_terminal(
                run_id,
                invalid,
                expected_status=RunStatus.NEEDS_OPERATOR,
            )
            logger.warning(
                "operator resume context invalid for run_id=%s resolution_id=%s "
                "code=%s",
                run_id,
                operator_resolution_id,
                invalid.diagnostic_code,
            )
            return

        result = normalize_pipeline_result(
            resume_pipeline_now(
                run_id,
                None,
                from_status=RunStatus.NEEDS_OPERATOR,
                overrides=overrides,
            )
        )
        if result.outcome is PipelineOutcome.OK:
            return
        if result.outcome is PipelineOutcome.TERMINAL:
            repo.settle_background_terminal(run_id, result)
            return

        from app.queue.drain import _backoff_seconds

        settled = repo.enqueue_operator_resume_retry(
            run_id,
            operator_resolution_id,
            result,
            available_in_seconds=_backoff_seconds(1),
        )
        if settled is repo.SettlementOutcome.RETRIED:
            wake.wake()
    except Exception:  # noqa: BLE001 — background safety net; route already 303'd
        logger.error("operator resume failed to start for run_id=%s", run_id)
