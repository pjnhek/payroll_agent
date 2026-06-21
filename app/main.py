"""FastAPI entrypoint — the thin webhook adapter + crude operator re-entry.

This is a THIN HTTP adapter (RESEARCH Architecture map): no business logic, no
LLM, no calc. It does only the cheap, synchronous, idempotency-critical work, then
schedules the LLM-heavy pipeline as a FastAPI BackgroundTask and returns 200 fast
(INGEST-01, D-A1-01).

Endpoints:
  POST /webhook/inbound       — ingest an InboundEmail, dedupe, sender-match, clean
                                the body, create the run, schedule run_pipeline
  POST /runs/{run_id}/approve — crude operator approve (awaiting_approval → approved)
  POST /runs/{run_id}/reject  — crude operator reject  (awaiting_approval → rejected)

Webhook flow (RESEARCH §Pattern 1):
  1. parse → InboundEmail via gateway.parse_inbound
  2. clean the body via clean_body() BEFORE the insert (review FIX C) so
     email_messages.body_text is the cleaned source of truth
  3. dedupe via repo.insert_inbound_email (ON CONFLICT (message_id) DO NOTHING);
     on a duplicate, return 200 and create NO second run (INGEST-01/FOUND-02)
  4. route sender → business via repo.find_business_by_sender; on None (unknown
     sender) log + return 200 with NO run (INGEST-03 — never guess)
  5. repo.create_run(status='received'), link the source email
  6. background_tasks.add_task(run_pipeline, run_id) and return 200 fast

Under fastapi.testclient.TestClient the BackgroundTask runs SYNCHRONOUSLY before
client.post() returns, so the end-to-end test asserts the pause with no server and
no sleeps (RESEARCH §Pattern 1 testability fact).
"""
from __future__ import annotations

import logging
import uuid

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import JSONResponse

from app.db import repo
from app.email import gateway
from app.email.clean import clean_body
from app.models.contracts import InboundEmail
from app.models.status import RunStatus

logger = logging.getLogger("payroll_agent.webhook")

app = FastAPI(title="Payroll Agent")


@app.post("/webhook/inbound")
def inbound(email: InboundEmail, background_tasks: BackgroundTasks) -> JSONResponse:
    """Ingest one inbound email, schedule the pipeline, return 200 fast."""
    # parse_inbound is a near-passthrough in Phase 2 (FastAPI already validated the
    # body into InboundEmail); route it through the seam so the P6 provider parser
    # has a single home.
    email = gateway.parse_inbound(email.model_dump(mode="json"))

    # FIX C: clean the body BEFORE persisting so email_messages.body_text holds the
    # cleaned text (the single cleaned-body source of truth the extraction reads).
    cleaned = clean_body(email.body_text)

    email_id, inserted = repo.insert_inbound_email(
        message_id=email.message_id,
        in_reply_to=email.in_reply_to,
        references_header=email.references_header,
        subject=email.subject,
        from_addr=email.from_addr,
        to_addr=email.to_addr,
        body_text=cleaned,
        run_id=None,
    )

    # Duplicate delivery (ON CONFLICT DO NOTHING → not inserted): no second run.
    if not inserted:
        logger.info("duplicate inbound message_id=%s — no second run", email.message_id)
        return JSONResponse(
            status_code=200,
            content={"status": "duplicate", "message_id": email.message_id},
        )

    # ── Reply routing (CLAR-02/03) ────────────────────────────────────────────
    # If this inbound carries an In-Reply-To / References header, it may be a
    # clarification reply to a paused run. Route it on the RFC header chain BEFORE
    # the ordinary first-ingest path so a reply resumes its run instead of opening
    # a second one. Returns a response if the inbound was handled as a reply
    # (resumed, spoof-rejected, or late); None to fall through to first ingest.
    if email.in_reply_to or email.references_header:
        handled = _route_reply(email, cleaned, background_tasks)
        if handled is not None:
            return handled

    # Sender access control (INGEST-03): unknown sender → log + stop, no run.
    business_id = repo.find_business_by_sender(email.from_addr)
    if business_id is None:
        logger.warning("unknown sender from_addr=%s — stopped, no run", email.from_addr)
        return JSONResponse(
            status_code=200,
            content={"status": "unknown_sender", "from_addr": email.from_addr},
        )

    run_id = repo.create_run(business_id=business_id, source_email_id=email_id)

    # Schedule the LLM-heavy pipeline AFTER the 200 (in prod); SYNCHRONOUS under
    # TestClient so the end-to-end test can assert the pause immediately.
    background_tasks.add_task(_run_pipeline, run_id)

    return JSONResponse(
        status_code=200,
        content={"status": "accepted", "run_id": str(run_id)},
    )


def _route_reply(
    email: InboundEmail, cleaned: str, background_tasks: BackgroundTasks
) -> JSONResponse | None:
    """Route a header-bearing inbound as a clarification reply, or None to fall through.

    The header chain is the primary AND only Phase 2 routing path (CLAR-02): the
    reply's In-Reply-To / References are matched against stored outbound Message-IDs.
    Subject/provider-thread fallback is a deliberately-deferred P6 concern (real
    provider thread variety) and is NOT built here.

    Decision flow:
      1. find_awaiting_reply_for_header — match restricted to status='awaiting_reply'.
         On a match: RE-ASSERT the reply sender against the matched run's business
         (review FIX 5) before resuming — a spoofed reply on a guessed/leaked
         Message-ID must not bypass INGEST-03. Sender mismatch → log + NOT resumed.
         Sender match → set EXTRACTING (sole writer) + schedule resume_pipeline.
      2. Else find_any_run_for_header — a header match to a run in ANY OTHER status
         (sent/reconciled/rejected/computed) is a LATE REPLY: log it, do NOT resume
         (FIX 10; CLAR-03 invariant 4).
      3. No header match at all → return None so the caller treats it as an ordinary
         inbound (first ingest).
    """
    run_id = repo.find_awaiting_reply_for_header(
        in_reply_to=email.in_reply_to,
        references_header=email.references_header,
    )
    if run_id is not None:
        # FIX 5 — re-assert the reply sender against the matched run's business
        # (the original inbound sender / businesses.contact_email). Reuse the SAME
        # comparison find_business_by_sender performs at first ingest (INGEST-03).
        run = repo.load_run(run_id)
        expected_business_id = run["business_id"] if run else None
        reply_business_id = repo.find_business_by_sender(email.from_addr)
        if reply_business_id is None or str(reply_business_id) != str(
            expected_business_id
        ):
            logger.warning(
                "reply sender from_addr=%s does NOT match run %s business — "
                "not resumed (spoof guard, FIX 5)",
                email.from_addr,
                run_id,
            )
            return JSONResponse(
                status_code=200,
                content={"status": "sender_mismatch", "run_id": str(run_id)},
            )

        # Sender revalidated → schedule the resume (idempotent + lossless, FIX 4).
        # CR-02: do NOT flip EXTRACTING here. The orchestrator owns that transition
        # (resume_pipeline, after re-asserting the run is still awaiting_reply under
        # the same code path that mutates it). Setting EXTRACTING in the webhook —
        # a DIFFERENT context from the BackgroundTask that does the work — is the
        # exact seam the status race lived in: it would also defeat resume_pipeline's
        # new precondition (the run would already be EXTRACTING, never awaiting_reply).
        # The run stays awaiting_reply until the background resume claims it.
        reply_for_resume = email.model_copy(update={"body_text": cleaned})
        background_tasks.add_task(_resume_pipeline, run_id, reply_for_resume)
        return JSONResponse(
            status_code=200,
            content={"status": "resumed", "run_id": str(run_id)},
        )

    # No awaiting_reply match — is it a LATE reply to an already-advanced run? (FIX 10)
    late_run_id = repo.find_any_run_for_header(
        in_reply_to=email.in_reply_to,
        references_header=email.references_header,
    )
    if late_run_id is not None:
        logger.info(
            "late reply: header matched run %s not in awaiting_reply — not resumed "
            "(FIX 10)",
            late_run_id,
        )
        return JSONResponse(
            status_code=200,
            content={"status": "late_reply", "run_id": str(late_run_id)},
        )

    # No header match → fall through to ordinary first ingest.
    return None


def _resume_pipeline(run_id: uuid.UUID, inbound: InboundEmail) -> None:
    """Background wrapper for resume_pipeline (mirrors _run_pipeline's safety net).

    resume_pipeline owns its own try/except error-wrap (D-A1-03); this outer guard
    only ensures a catastrophic start failure cannot escape the BackgroundTask (the
    webhook already returned 200)."""
    try:
        from app.pipeline.orchestrator import resume_pipeline

        resume_pipeline(run_id, inbound)
    except Exception:  # noqa: BLE001 — background safety net; webhook already 200'd
        logger.exception("resume failed to start for run_id=%s", run_id)


def _run_pipeline(run_id: uuid.UUID) -> None:
    """Run the orchestrator for a run.

    The orchestrator owns its own try/except error-wrap (D-A1-03) and persists
    ERROR on any stage failure. This outer guard exists ONLY so a catastrophic
    failure (e.g. the orchestrator itself failing to import/start) can never
    propagate out of the BackgroundTask — the webhook already returned 200, so a
    background crash must be logged, not raised. It does NOT swallow stage errors;
    those are caught and persisted inside run_pipeline before they reach here."""
    try:
        from app.pipeline.orchestrator import run_pipeline

        run_pipeline(run_id)
    except Exception:  # noqa: BLE001 — background safety net; webhook already 200'd
        logger.exception("pipeline failed to start for run_id=%s", run_id)


@app.post("/runs/{run_id}/approve")
def approve(run_id: uuid.UUID) -> JSONResponse:
    """Crude operator approve: require awaiting_approval → set APPROVED (HITL-01).

    No confirmation email / PDF / FOR-UPDATE guard — those are HITL-02/03 / FOUND-04
    = Phase 5. This proves the gate pauses and resumes via the sole set_status writer.
    """
    return _operator_transition(run_id, RunStatus.APPROVED)


@app.post("/runs/{run_id}/reject")
def reject(run_id: uuid.UUID) -> JSONResponse:
    """Crude operator reject: require awaiting_approval → set REJECTED (HITL-01)."""
    return _operator_transition(run_id, RunStatus.REJECTED)


def _operator_transition(run_id: uuid.UUID, target: RunStatus) -> JSONResponse:
    run = repo.load_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run not found")
    if run["status"] != RunStatus.AWAITING_APPROVAL.value:
        raise HTTPException(
            status_code=409,
            detail=f"run is {run['status']}, not awaiting_approval",
        )
    repo.set_status(run_id, target)
    return JSONResponse(
        status_code=200,
        content={"status": target.value, "run_id": str(run_id)},
    )
