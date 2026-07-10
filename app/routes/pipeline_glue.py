"""HTTP-to-orchestrator bridge helpers (D-07, BOUND-01 promotion).

Carved out of app/main.py (Phase 13 Plan 03). These seven functions were
previously module-private helpers inside the monolithic main.py
(`_row_to_inbound`, `_reply_sender_ok`, `_finish_reply_resume`, `_route_reply`,
`_resume_pipeline`, `_run_pipeline`, `_operator_resume`) — all promoted to
public names here and imported by every router via a module-object import
(`from app.routes import pipeline_glue`), never a bare-name import, so every
existing monkeypatch.setattr(<module>, <fn>) seam retargets mechanically to
this one owning module.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse

from app.db import repo
from app.models.contracts import InboundEmail
from app.models.status import RunStatus

logger = logging.getLogger("payroll_agent.webhook")


def row_to_inbound(row: dict) -> InboundEmail:
    """Build an InboundEmail from a PERSISTED email_messages row dict (Plan 11-05).

    The single conversion point reused by both the WR-04 duplicate-redelivery
    re-schedule and the D-11-05 stranded-unconsumed-reply runs-list auto-resume.
    Pure — no DB I/O. Uses `row["body_text"]` VERBATIM: it is already the body
    cleaned at first ingest (the authoritative, actually-processed text) — this
    helper must NEVER re-clean it (Pitfall #11a; a redelivered webhook request
    body could diverge from what was actually persisted/processed).

    `row` must supply the full InboundEmail field set (id, message_id,
    in_reply_to, references_header, subject, from_addr, to_addr, body_text,
    created_at) — both `repo.get_inbound_by_message_id` and
    `repo.find_stranded_unconsumed_replies` are widened to return exactly this
    shape (plus run_id, which this helper ignores; the caller already has it).
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


def reply_sender_ok(row: dict, run: dict) -> bool:
    """Re-assert FIX-5's sender revalidation for an already-persisted reply row (GAP-5/CR-5).

    A reply is linked to its run INSIDE the webhook's ingest transaction based
    purely on the RFC header chain (in_reply_to/references) — attacker-
    controllable and NOT authentication. FIX-5 (`find_business_by_sender`
    matching the run's business) is the actual authentication gate, and it is
    the SAME comparison `finish_reply_resume` performs post-commit at first
    delivery. That guard only runs once, on the FIRST delivery, though: any
    OTHER seam capable of re-dispatching `resume_pipeline_bg` from a
    persisted, linked-but-unconsumed reply row (a redelivery, a later
    stranded-reply sweep) must re-assert it too, or a reply that already
    failed FIX-5 once — and was left linked+unconsumed — can still drive the
    run via that seam. This is that shared predicate, reused by both
    re-schedule seams.

    Calls `find_business_by_sender` exactly ONCE (assigned to a local first) —
    no duplicate lookup.
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

    Called AFTER the webhook's ingest transaction has ALREADY classified this
    inbound as a reply-resume candidate (`find_awaiting_reply_for_header` found
    `run_id` INSIDE that transaction, Codex HIGH-1 fix) — this helper does NOT
    re-run that header lookup (re-deriving the classification would reintroduce
    the same race in a different shape). It only performs FIX 5's sender
    re-validation (a pure read-then-branch with no write, so it stays OUTSIDE
    the transaction unchanged in its own logic) and shapes the response /
    schedules the background resume.
    """
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
    background_tasks.add_task(resume_pipeline_bg, run_id, reply_for_resume)
    return JSONResponse(
        status_code=200,
        content={"status": "resumed", "run_id": str(run_id)},
    )


def route_reply(
    email: InboundEmail, cleaned: str, background_tasks: BackgroundTasks
) -> JSONResponse | None:
    """Route a header-bearing inbound as a clarification reply, or None to fall through.

    Used by `simulate_reply` (the demo-only affordance) and any other caller that
    has NOT already classified the inbound inside a transaction — it performs its
    OWN header lookups. The real webhook's `inbound()` route does NOT call this;
    it classifies the reply INSIDE its ingest transaction (Codex HIGH-1 fix) and
    then calls `finish_reply_resume` for the sender-revalidation + response
    shaping, so the header lookups are never re-derived a second time on that path.

    The header chain is the primary AND only Phase 2 routing path (CLAR-02): the
    reply's In-Reply-To / References are matched against stored outbound Message-IDs.
    Subject/provider-thread fallback is a deliberately-deferred P6 concern (real
    provider thread variety) and is NOT built here.

    Decision flow:
      1. find_awaiting_reply_for_header — match restricted to status='awaiting_reply'.
         On a match: delegate to `finish_reply_resume` (FIX 5 sender re-assertion +
         response shaping + background scheduling).
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
        return finish_reply_resume(run_id, email, cleaned, background_tasks)

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


def resume_pipeline_bg(run_id: uuid.UUID, inbound: InboundEmail) -> None:
    """Background wrapper for resume_pipeline (mirrors run_pipeline_bg's safety net).

    resume_pipeline owns its own try/except error-wrap (D-A1-03); this outer guard
    only ensures a catastrophic start failure cannot escape the BackgroundTask (the
    webhook already returned 200)."""
    try:
        from app.pipeline.orchestrator import resume_pipeline

        resume_pipeline(run_id, inbound)
    except Exception:  # noqa: BLE001 — background safety net; webhook already 200'd
        logger.exception("resume failed to start for run_id=%s", run_id)


def run_pipeline_bg(run_id: uuid.UUID) -> None:
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


def operator_resume_bg(run_id: uuid.UUID, overrides: dict[str, str]) -> None:
    """Background wrapper for the operator-resume path (mirrors resume_pipeline_bg).

    resume_pipeline owns its own try/except error-wrap (D-A1-03); this outer
    guard only ensures a catastrophic start failure cannot escape the
    BackgroundTask (the /resolve route already returned 303)."""
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
