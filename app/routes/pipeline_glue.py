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
from typing import Any

from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse

from app.db import repo
from app.models.contracts import InboundEmail
from app.models.status import RunStatus

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


def resume_pipeline_bg(run_id: uuid.UUID, inbound: InboundEmail) -> None:
    """Background wrapper for resume_pipeline (mirrors run_pipeline_bg's safety net).

    resume_pipeline owns its own try/except error-wrap and persists ERROR on stage
    failure; this outer guard only ensures a catastrophic START failure (e.g. the
    orchestrator failing to import) cannot escape the BackgroundTask. The webhook has
    already returned 200, so a background crash must be logged, never raised."""
    try:
        from app.pipeline.orchestrator import resume_pipeline

        resume_pipeline(run_id, inbound)
    except Exception:  # noqa: BLE001 — background safety net; webhook already 200'd
        logger.exception("resume failed to start for run_id=%s", run_id)


def run_pipeline_now(run_id: uuid.UUID) -> None:
    """Run the orchestrator for a run and let a catastrophic START failure PROPAGATE.

    This is the entrypoint for a caller that can actually DO something with a start
    failure — today, the queue's worker, whose `drain_once` routes any exception into a
    fenced `fail_job` write with backoff and retries the job up to `max_attempts`.

    Never route a queued job through `run_pipeline_bg` instead. That wrapper's swallow is
    correct for a fire-and-forget BackgroundTask and catastrophic for a queued job: the
    handler would return normally, `drain_once` would mark the job `done`, the durable row
    would disappear as a success, and the run would strand mid-flight with nothing left to
    retry it. A payroll run would be silently lost. The whole point of putting the pipeline
    on a durable queue is that a start failure becomes a retry — but only if it is allowed
    to reach the code that retries.

    The orchestrator still owns its own try/except error-wrap and persists ERROR on any
    STAGE failure, so those never reach here. What reaches here is the catastrophic kind:
    the orchestrator failing to import, the database being unreachable at start.
    """
    from app.pipeline.orchestrator import run_pipeline

    run_pipeline(run_id)


def run_pipeline_bg(run_id: uuid.UUID) -> None:
    """Fire-and-forget wrapper for the FastAPI BackgroundTask path (the inbound webhook).

    Swallows a catastrophic start failure because the webhook has ALREADY returned 200 to
    the email gateway — there is no caller left to hand an exception to, and an escaping
    background crash would take down the request's task group. Logged, never raised.

    A caller that CAN act on a start failure must use `run_pipeline_now` instead; see its
    docstring for why routing a queued job through this swallow loses the run.
    """
    try:
        run_pipeline_now(run_id)
    except Exception:  # noqa: BLE001 — background safety net; webhook already 200'd
        logger.exception("pipeline failed to start for run_id=%s", run_id)


def operator_resume_bg(run_id: uuid.UUID, overrides: dict[str, str]) -> None:
    """Background wrapper for the operator-resume path (mirrors resume_pipeline_bg).

    resume_pipeline owns its own try/except error-wrap; this outer guard only ensures
    a catastrophic START failure cannot escape the BackgroundTask — the /resolve route
    has already returned 303, so a background crash must be logged, never raised."""
    try:
        from app.pipeline.orchestrator import resume_pipeline

        resume_pipeline(
            run_id,
            None,
            from_status=RunStatus.NEEDS_OPERATOR,
            overrides=overrides,
        )
    except Exception:  # noqa: BLE001 — background safety net; route already 303'd
        logger.exception("operator resume failed to start for run_id=%s", run_id)
