"""HTTP-to-orchestrator bridge helpers (BOUND-01).

Every router imports these via a module-object import
(`from app.routes import pipeline_glue`), NEVER a bare-name import. A bare-name
import would bind the function object at import time, and the tests'
`monkeypatch.setattr(pipeline_glue, <fn>)` seams would silently stop taking
effect — the router would keep calling the real orchestrator.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.db import repo
from app.models.contracts import InboundEmail
from app.models.job import JobKind
from app.models.status import RunStatus
from app.pipeline.result import PipelineResult, normalize_pipeline_result


def row_to_inbound(row: dict[str, Any]) -> InboundEmail:
    """Build an InboundEmail from a PERSISTED email_messages row dict.

    The single conversion point reused by webhook duplicate redelivery and the durable
    ``RESUME_REPLY`` queue handler. Pure — no DB I/O.

    Uses `row["body_text"]` VERBATIM. That column already holds the body cleaned at
    first ingest — the authoritative, actually-processed text. This helper must NEVER
    re-clean it: a redelivered webhook's request body can diverge from what was
    persisted, and re-cleaning would resume the run against text the run never saw.

    `row` must supply the full InboundEmail field set (id, message_id, in_reply_to,
    references_header, subject, from_addr, to_addr, body_text, created_at). Both
    ``repo.get_inbound_by_message_id`` and ``repo.get_inbound_email_by_id`` return
    exactly this shape (plus routing identifiers this helper ignores because the caller
    already owns them).
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


def reply_sender_ok(
    row: dict[str, Any], run: dict[str, Any], *, conn: Any = None
) -> bool:
    """Re-assert the reply sender revalidation for an already-persisted reply row.

    A reply is linked to its run INSIDE the webhook's ingest transaction based purely
    on the RFC header chain (in_reply_to/references). Those headers are
    attacker-controllable and are NOT authentication. The real authentication gate is
    `find_business_by_sender` matching the run's business. Every durable resume seam
    must re-assert it before converting persisted content or invoking orchestration.
    Otherwise attacker-controlled threading headers could bind a spoofed reply to a
    different business's run. This shared predicate is used by both durable reply
    classification and the identifier-only reply handler.

    Calls `find_business_by_sender` exactly ONCE (assigned to a local first).
    """
    reply_business_id = repo.find_business_by_sender(
        row.get("from_addr") or "", conn=conn
    )
    return reply_business_id is not None and str(reply_business_id) == str(
        run.get("business_id")
    )


class ReplyRoutingOutcome(StrEnum):
    """Fixed reply-producer outcomes safe to cross route and log boundaries."""

    RESUMED = "resumed"
    DUPLICATE_NOOP = "duplicate_noop"
    SENDER_MISMATCH = "sender_mismatch"
    ADVANCED_NOOP = "advanced_noop"
    LATE_REPLY = "late_reply"
    NO_HEADER_MATCH = "no_header_match"
    INVALID_CONTEXT = "invalid_context"


@dataclass(frozen=True, slots=True)
class ReplyRoutingResult:
    """PII-free result of persisting, classifying, and enqueueing one reply."""

    outcome: ReplyRoutingOutcome
    should_wake: bool = False


def _canonical_uuid(value: object) -> uuid.UUID | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return uuid.UUID(str(value))
    except (AttributeError, TypeError, ValueError):
        return None


def _ensure_authorized_reply_job(
    row: dict[str, Any],
    *,
    run_id: uuid.UUID,
    email_id: uuid.UUID,
    conn: Any,
) -> ReplyRoutingResult:
    """Authorize one persisted same-run row and ensure its identifier-only job."""
    if _canonical_uuid(row.get("run_id")) != run_id:
        return ReplyRoutingResult(ReplyRoutingOutcome.INVALID_CONTEXT)
    if row.get("consumed_round") is not None:
        return ReplyRoutingResult(ReplyRoutingOutcome.DUPLICATE_NOOP)

    run = repo.load_run(run_id, conn=conn)
    if run is None or run.get("status") != RunStatus.AWAITING_REPLY.value:
        return ReplyRoutingResult(ReplyRoutingOutcome.ADVANCED_NOOP)
    if not reply_sender_ok(row, run, conn=conn):
        return ReplyRoutingResult(ReplyRoutingOutcome.SENDER_MISMATCH)

    repo.enqueue_job(
        kind=JobKind.RESUME_REPLY,
        dedup_key=f"resume_reply:{run_id}:{email_id}",
        run_id=run_id,
        email_id=email_id,
        conn=conn,
    )
    # Wake even when ON CONFLICT found the same owed job. A redelivery can be the
    # signal that revives already-durable work after a sleeping instance restarts.
    return ReplyRoutingResult(ReplyRoutingOutcome.RESUMED, should_wake=True)


def persist_and_enqueue_reply(
    email: InboundEmail,
    cleaned: str,
    *,
    conn: Any,
) -> ReplyRoutingResult:
    """Persist, classify, authorize, and enqueue a reply in the caller transaction.

    The caller owns commit/rollback and fires ``wake.wake()`` only after this function
    returns and that transaction commits. Duplicate RFC deliveries rehydrate the
    existing row and ensure the same ``resume_reply:{run_id}:{email_id}`` job.
    """
    email_id, inserted = repo.insert_inbound_email(
        message_id=email.message_id,
        in_reply_to=email.in_reply_to,
        references_header=email.references_header,
        subject=email.subject,
        from_addr=email.from_addr,
        to_addr=email.to_addr,
        body_text=cleaned,
        run_id=None,
        conn=conn,
    )

    if not inserted:
        persisted = repo.get_inbound_by_message_id(email.message_id, conn=conn)
        if persisted is None:
            return ReplyRoutingResult(ReplyRoutingOutcome.INVALID_CONTEXT)
        persisted_email_id = _canonical_uuid(persisted.get("id"))
        persisted_run_id = _canonical_uuid(persisted.get("run_id"))
        if persisted_email_id is None or persisted_run_id is None:
            return ReplyRoutingResult(ReplyRoutingOutcome.DUPLICATE_NOOP)
        return _ensure_authorized_reply_job(
            persisted,
            run_id=persisted_run_id,
            email_id=persisted_email_id,
            conn=conn,
        )

    if email_id is None:
        return ReplyRoutingResult(ReplyRoutingOutcome.INVALID_CONTEXT)

    run_id = repo.find_awaiting_reply_for_header(
        in_reply_to=email.in_reply_to,
        references_header=email.references_header,
        conn=conn,
    )
    if run_id is not None:
        repo.link_email_to_run(email_id, run_id, conn=conn)
        persisted = repo.get_inbound_email_by_id(email_id, conn=conn)
        if persisted is None:
            return ReplyRoutingResult(ReplyRoutingOutcome.INVALID_CONTEXT)
        return _ensure_authorized_reply_job(
            persisted,
            run_id=run_id,
            email_id=email_id,
            conn=conn,
        )

    late_run_id = repo.find_any_run_for_header(
        in_reply_to=email.in_reply_to,
        references_header=email.references_header,
        conn=conn,
    )
    if late_run_id is not None:
        repo.link_email_to_run(email_id, late_run_id, conn=conn)
        return ReplyRoutingResult(ReplyRoutingOutcome.LATE_REPLY)

    return ReplyRoutingResult(ReplyRoutingOutcome.NO_HEADER_MATCH)


def resume_pipeline_now(
    run_id: uuid.UUID,
    inbound: InboundEmail | None,
    *,
    from_status: RunStatus = RunStatus.AWAITING_REPLY,
    overrides: dict[str, str] | None = None,
) -> PipelineResult:
    """Invoke the explicit producer contract and reject unsound runtime values."""
    from app.pipeline.orchestrator import resume_pipeline

    return normalize_pipeline_result(
        resume_pipeline(
            run_id,
            inbound,
            from_status=from_status,
            overrides=overrides,
        )
    )


def run_pipeline_now(run_id: uuid.UUID) -> PipelineResult:
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

    The returned value and any escaping failure stay explicit so ``drain_once`` can
    perform fenced settlement. No route-owned procedure may consume or swallow either
    signal before the durable queue sees it.
    """
    from app.pipeline.orchestrator import run_pipeline

    return normalize_pipeline_result(run_pipeline(run_id))
