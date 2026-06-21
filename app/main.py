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
