"""Everything under /runs* — operator list, gate, recovery action, and detail."""
from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any, TypedDict, cast

import psycopg
from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse

import app.db.repo as repo
import app.pipeline.delivery as delivery
import app.queue.wake as wake
from app.email import gateway
from app.email.clean import clean_body
from app.models.job import JobKind
from app.models.roster import Employee, Roster
from app.models.status import RunStatus
from app.routes import pipeline_glue
from app.routes.demo import DEMO_FIXTURES
from app.routes.templating import badge_class_filter, badge_label_filter, templates

__all__ = ["router", "delivery", "wake"]

logger = logging.getLogger("payroll_agent.webhook")

router = APIRouter()

# Staleness threshold for the operator-authorized retrigger path. Automatic recovery is
# queue-owned; this value exists only to decide whether a human may restart an in-flight
# run through the explicit Retrigger action.
#
# The value must sit safely ABOVE the worst-case gap between two consecutive DB writes
# on the longest real path, or Retrigger could restart a run that is merely slow, not
# stuck. It is derived, not guessed:
#   (a) call_structured (app/llm/client.py) — used for BOTH extraction AND the
#       clarification suggestion (app/pipeline/suggest.py) — passes an explicit
#       timeout=_STRUCTURED_TIMEOUT_S (45.0s) AND max_retries=0 to its OpenAI(...)
#       client construction, so the library's own retry layer cannot compound with the
#       app's `for attempt in (1, 2):` reflective retry. Both of those must stay pinned
#       or this ceiling silently multiplies.
#       Ceiling per call: _STRUCTURED_TIMEOUT_S x 2 app-attempts = 90s.
#   (b) The resume path's back-to-back double extraction (orchestrator.py: extract the
#       reply, THEN extract the combined email) — TWO calls through (a) before the next
#       DB write: 45s x 2 app-attempts x 2 calls = 180s (3 min).
#   (c) call_text (app/llm/client.py) — ALL callers, including compose_clarification
#       (app/pipeline/compose_email.py) — gets an UNCONDITIONAL max_retries=0 on its
#       client construction. It has no app-level retry loop, so without that the
#       library's default max_retries=2 would be an uncounted retry layer.
#       compose_clarification also passes an explicit timeout_s=_CLARIFICATION_TIMEOUT_S
#       (30.0s). Ceiling: 30s x 1 = 30s.
# (b) and (c) are SEQUENTIAL on the clarify branch (extraction happens, then a
# clarification draft may be composed) — not concurrent — so they SUM rather than
# multiply: 180s + 30s = 210s (3.5 min) worst case.
#
# 15 minutes is ~4x that ceiling. A run in a recoverable in-flight state
# (RECEIVED/EXTRACTING/COMPUTED, plus SENT for retrigger only — see the
# scope-divergence comment on retrigger's stale_statuses below) whose updated_at is
# older than this may be claimed for a fresh operator-authorized start; fresh in-flight
# runs are never force-restarted.
STALE_THRESHOLD = timedelta(minutes=15)
STALE_THRESHOLD_SECONDS = int(STALE_THRESHOLD.total_seconds())

# In-flight statuses — a run in any of these states is still processing.
# Templates receive an `auto_refresh` boolean driven from this constant so no status
# string is ever hardcoded in the HTML. Terminal statuses never trigger auto-refresh.
# awaiting_reply is included deliberately: without it the detail page stops polling the
# moment a clarification goes out, and the reply-driven transition (awaiting_reply →
# extracting → … → needs_approval) would never appear without a manual refresh. A run
# parked at awaiting_reply with no reply yet simply polls with an unchanged badge until
# the 30-attempt cap, which is harmless.
IN_FLIGHT_STATUSES: frozenset[str] = frozenset(
    {"received", "extracting", "computed", "awaiting_reply"}
)


class FailurePresentation(TypedDict):
    """Browser-safe projection of persisted terminal diagnostics."""

    secondary_label: str | None
    stage: str | None
    reason: str | None
    attempts: str | None


_STAGE_LABELS = {
    "unknown": "Unknown stage",
    "load": "Load",
    "extract": "Extraction",
    "persist": "Persistence",
    "clarification": "Clarification",
    "compute": "Computation",
    "delivery": "Delivery",
}
_REASON_LABELS = {
    "unclassified": "Unclassified failure",
    "provider_connection_failure": "Provider connection failure",
    "provider_timeout": "Provider timeout",
    "provider_rate_limit": "Provider rate limit",
    "provider_server_failure": "Provider server failure",
    "schema_or_parse_failure": "Schema or parse failure",
    "client_request_failure": "Client request failure",
    "ambiguous_send_failure": "Ambiguous send failure",
    "invalid_operator_override_context": "Invalid operator override context",
    "final_attempt_lease_expired": "Final attempt lease expired",
}
_DIAGNOSTIC_CODE_RE = re.compile(
    r"^(?P<stage>[a-z_]+):(?P<reason>[a-z_]+)"
    r"(?:;attempts=(?P<attempts>[0-9]+)/(?P<max_attempts>[0-9]+))?$"
)
_EXHAUSTION_REASONS = frozenset({"RetryExhausted", "FinalAttemptLeaseExpired"})
_QUEUE_LABELS = frozenset({"Running", "Queued", "Retry queued"})
_QUEUE_BADGE_CLASSES = {
    "Running": "running",
    "Queued": "neutral",
    "Retry queued": "neutral",
}
_DELIVERY_REVIEW_CATEGORY_LABELS = {
    "transport": "Transport uncertainty",
    "provider_5xx": "Provider service failure",
    "rate_limited": "Provider rate limit",
    "payload_mismatch": "Frozen payload mismatch",
    "authorization": "Provider authorization issue",
    "validation": "Provider validation issue",
    "configuration": "Delivery configuration issue",
    "final_attempt_lease_expired": "Final attempt lease expired",
    "unknown": "Unknown delivery outcome",
}
_DELIVERY_REVIEW_PURPOSES = {
    "DeliveryReview": frozenset({"confirmation"}),
    "ClarificationDeliveryReview": frozenset(
        {"clarification", "clarification_field_regression"}
    ),
}
_DELIVERY_REVIEW_MARKERS = frozenset(_DELIVERY_REVIEW_PURPOSES)
_NEW_CONFIRMATION_ACKNOWLEDGEMENT = "AUTHORIZE A NEW CONFIRMATION"


def _bounded_attempts(attempts: object, max_attempts: object) -> str | None:
    """Format only small, internally consistent integer attempt counters."""
    if isinstance(attempts, bool) or isinstance(max_attempts, bool):
        return None

    def _as_int(value: object) -> int | None:
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isascii() and value.isdigit():
            return int(value)
        return None

    current = _as_int(attempts)
    maximum = _as_int(max_attempts)
    if current is None or maximum is None:
        return None
    if not (1 <= current <= maximum <= 100):
        return None
    return f"{current} of {maximum} attempts"


def _safe_failure_presentation(run: dict[str, Any]) -> FailurePresentation:
    """Reduce persisted diagnostics to the fixed browser-visible vocabulary.

    ``error_detail`` and any future ``last_error`` value are treated as hostile.  A
    value is rendered only when the entire diagnostic string matches the fixed
    stage/reason grammar and the run-level reason agrees with that grammar.
    """
    generic: FailurePresentation = {
        "secondary_label": None,
        "stage": None,
        "reason": None,
        "attempts": None,
    }
    if run.get("status") != RunStatus.ERROR.value:
        return generic

    error_reason = run.get("error_reason")
    detail = run.get("error_detail")
    if not isinstance(error_reason, str) or not isinstance(detail, str):
        return generic
    match = _DIAGNOSTIC_CODE_RE.fullmatch(detail)
    if match is None:
        return generic
    stage_code = match.group("stage")
    detail_reason = match.group("reason")
    stage = _STAGE_LABELS.get(stage_code)
    reason = _REASON_LABELS.get(detail_reason)
    if stage is None or reason is None:
        return generic

    if error_reason == "FinalAttemptLeaseExpired":
        if (stage_code, detail_reason) != (
            "unknown",
            "final_attempt_lease_expired",
        ):
            return generic
    elif error_reason == "RetryExhausted":
        if detail_reason == "final_attempt_lease_expired":
            return generic
    elif error_reason != detail_reason:
        return generic

    attempts = _bounded_attempts(
        match.group("attempts"), match.group("max_attempts")
    )
    if attempts is None:
        attempts = _bounded_attempts(
            run.get("job_attempts"), run.get("job_max_attempts")
        )
    return {
        "secondary_label": (
            "Retries exhausted" if error_reason in _EXHAUSTION_REASONS else None
        ),
        "stage": stage,
        "reason": reason,
        "attempts": attempts,
    }


def _safe_run_for_browser(run: dict[str, Any]) -> dict[str, Any]:
    """Copy a run and reduce diagnostics/queue state to fixed browser vocabulary."""
    safe_run = dict(run)
    safe_run["failure"] = _safe_failure_presentation(run)
    queue_label = run.get("queue_label")
    if queue_label not in _QUEUE_LABELS:
        queue_label = None
    safe_run["queue_label"] = queue_label
    safe_run["queue_badge_class"] = (
        _QUEUE_BADGE_CLASSES[queue_label] if queue_label is not None else "neutral"
    )
    safe_run["has_open_job"] = queue_label is not None
    raw_fields = {
        "error_reason",
        "error_detail",
        "last_error",
        "available_at",
        "attempts",
        "max_attempts",
        "payload",
        "diagnostics",
    }
    for field in tuple(safe_run):
        if field in raw_fields or field.startswith("job_"):
            safe_run.pop(field, None)
    return safe_run


def _safe_run_with_queue_projection(
    run_id: uuid.UUID, run: dict[str, Any]
) -> dict[str, Any]:
    """Attach the authoritative open-job label, degrading to no label on read error."""
    projected = dict(run)
    try:
        projected["queue_label"] = repo.get_run_queue_label(run_id)
    except Exception:
        logger.debug("queue projection unavailable for run %s", run_id)
        projected["queue_label"] = None
    return _safe_run_for_browser(projected)


def _load_delivery_review(
    run_id: uuid.UUID, *, conn: psycopg.Connection | None = None
) -> dict[str, Any] | None:
    """Load one purpose-owned review while its frozen reservation is actionable."""
    run = repo.load_run(run_id, conn=conn)
    review_reason = run.get("error_reason") if run is not None else None
    if (
        run is None
        or run.get("status") != RunStatus.NEEDS_OPERATOR.value
        or review_reason not in _DELIVERY_REVIEW_PURPOSES
    ):
        return None
    detail = run.get("error_detail")
    if not isinstance(detail, str) or not detail.startswith("delivery_review:"):
        return None
    category = detail.removeprefix("delivery_review:")
    if category not in _DELIVERY_REVIEW_CATEGORY_LABELS:
        return None
    allowed_purposes = _DELIVERY_REVIEW_PURPOSES[review_reason]
    pending = None
    for purpose in allowed_purposes:
        pending = repo.get_unconfirmed_outbound(run_id, purpose=purpose, conn=conn)
        if pending is not None:
            break
    if pending is None or not isinstance(pending.get("email_id"), uuid.UUID):
        return None
    review = repo.load_delivery_review_snapshot(
        run_id, pending["email_id"], conn=conn
    )
    if review is None or review.get("email_id") != pending["email_id"]:
        return None
    review_purpose = review.get("purpose")
    if review_purpose not in allowed_purposes:
        return None
    if not isinstance(review.get("snapshot_id"), uuid.UUID):
        return None
    attempts = review.get("attempt_count")
    if isinstance(attempts, bool) or not isinstance(attempts, int):
        return None
    if not 0 <= attempts <= 100:
        return None
    return {
        "category": category,
        "review_kind": "confirmation"
        if review_reason == "DeliveryReview"
        else "clarification",
        "review": review,
    }


def _safe_delivery_review_projection(
    run_id: uuid.UUID, delivery_review: dict[str, Any]
) -> dict[str, Any]:
    """Expose only the finite review facts and frozen artifact references."""
    review = delivery_review["review"]
    attachments: list[dict[str, str]] = []
    for attachment in review.get("attachments", []):
        attachment_id = attachment.get("id") if isinstance(attachment, dict) else None
        filename = attachment.get("filename") if isinstance(attachment, dict) else None
        if isinstance(attachment_id, uuid.UUID) and isinstance(filename, str):
            attachments.append(
                {
                    "filename": filename,
                    "url": (
                        f"/runs/{run_id}/delivery-review/attachments/{attachment_id}"
                    ),
                }
            )
    return {
        "purpose": review["purpose"],
        "review_kind": delivery_review["review_kind"],
        "recipient": review["to_addr"],
        "subject": review["subject"],
        "reserved_at": review["reserved_at"],
        "attempt_count": review["attempt_count"],
        "failure_category": _DELIVERY_REVIEW_CATEGORY_LABELS[delivery_review["category"]],
        "message_id": review["message_id"],
        "email_url": f"/runs/{run_id}/delivery-review/email",
        "attachments": attachments,
    }


def _is_delivery_review_marker(run: dict[str, Any] | None) -> bool:
    """Identify review-owned runs before generic operator recovery can mutate them."""
    return bool(
        run is not None
        and run.get("status") == RunStatus.NEEDS_OPERATOR.value
        and run.get("error_reason") in _DELIVERY_REVIEW_MARKERS
    )


def _snapshot_clone_fields(
    snapshot: dict[str, Any],
) -> tuple[list[tuple[str, bytes]], dict[str, str | None]]:
    """Validate the stored envelope before cloning its exact provider-visible bytes."""
    text_fields = (
        "from_addr",
        "to_addr",
        "reply_to",
        "in_reply_to",
        "references_header",
        "subject",
        "body_text",
    )
    envelope: dict[str, str | None] = {}
    for field in text_fields:
        value = snapshot.get(field)
        if value is not None and not isinstance(value, str):
            raise ValueError("stored confirmation has an invalid frozen envelope")
        envelope[field] = value
    required = ("from_addr", "to_addr", "subject", "body_text")
    if any(not isinstance(envelope[field], str) for field in required):
        raise ValueError("stored confirmation lacks a frozen envelope field")
    attachments: list[tuple[str, bytes]] = []
    for attachment in snapshot.get("attachments", []):
        if not isinstance(attachment, dict):
            raise ValueError("stored confirmation has an invalid attachment")
        filename = attachment.get("filename")
        content = attachment.get("content")
        if not isinstance(filename, str) or not isinstance(content, bytes):
            raise ValueError("stored confirmation has an invalid attachment")
        attachments.append((filename, bytes(content)))
    return attachments, envelope


@router.post("/runs/{run_id}/approve")
def approve(
    run_id: uuid.UUID,
) -> RedirectResponse:
    """The single human gate: claim approval, freeze delivery, and queue the send.

    Race-safety: claim_status is an atomic compare-and-set. A second concurrent approval
    (double-click, two operator tabs) LOSES the claim and 303-redirects without running
    delivery again — otherwise the client would receive the payroll confirmation twice.

    The same transaction owns the approval claim, immutable confirmation reservation,
    and identifier-only send job. Provider work starts only after that transaction has
    committed and a worker has claimed the job. While delivery is owed, APPROVED remains
    the business state and the queue supplies the delivery projection.

    Error logging is PII-safe: error_reason is type(exc).__name__ ONLY.
    """
    should_wake = False
    try:
        with repo.get_connection() as conn, conn.transaction():
            claimed = repo.claim_status(
                run_id,
                RunStatus.AWAITING_APPROVAL,
                RunStatus.APPROVED,
                conn=conn,
            )
            if not claimed:
                return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
            # load_run is INSIDE the error boundary on purpose. A transient DB failure
            # during the load must route to ERROR rather than leave the run silently
            # stuck at APPROVED behind a raw 500.
            run = repo.load_run(run_id, conn=conn)
            if run is None:
                raise TypeError("run not found")
            should_wake = delivery.deliver(run_id, run, conn=conn)
    except Exception as exc:  # noqa: BLE001 — delivery error boundary
        # PII-safe: log the exception TYPE only. str(exc) may echo model output,
        # submitted employee names, or raw email content. run_id is the correlation
        # key for debugging.
        logger.warning("delivery of run %s failed: %s", run_id, type(exc).__name__)
        # approve() must never LOAD a roster itself — the error path loading one
        # would turn a DB outage into a second failure inside the handler. But
        # delivery.deliver stashes the roster it ALREADY loaded (for PDF/compose
        # interpolation) onto any exception raised past that point, as
        # exc.payroll_roster. Forward it so the scrubber can redact employee names
        # from the delivery error_detail — that text is the boundary where names
        # are most likely to leak. Failures raised BEFORE deliver's roster load
        # carry no such attribute, hence the getattr default of None.
        repo.record_run_error(
            run_id,
            type(exc).__name__,
            detail_exc=exc,
            stage="delivery",
            roster=getattr(exc, "payroll_roster", None),
        )
    if should_wake:
        wake.wake()
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@router.post("/runs/{run_id}/reject")
def reject(run_id: uuid.UUID) -> RedirectResponse:
    """Reject: CAS claim (AWAITING_APPROVAL OR NEEDS_OPERATOR → REJECTED) → 303.

    claim_status is atomic — a concurrent rejection or approval sees False and no-ops,
    so a rejected run can never also be delivered. Always 303 to run detail regardless
    of the claim outcome.

    needs_operator is also a valid reject source (one of the escalation's two exits —
    resolve+resume, or reject). The `or` short-circuits: if the first CAS wins (the run
    was awaiting_approval) the second is skipped; if it loses, the second CAS attempts
    the needs_operator claim. The two target mutually exclusive prior statuses, so at
    most one can ever succeed for a given run — there is no double-claim race between
    them.
    """
    repo.claim_status(
        run_id, RunStatus.AWAITING_APPROVAL, RunStatus.REJECTED
    ) or repo.claim_status(run_id, RunStatus.NEEDS_OPERATOR, RunStatus.REJECTED)
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@router.post("/runs/{run_id}/resolve")
async def resolve(
    run_id: uuid.UUID, request: Request
) -> RedirectResponse:
    """Operator resolve+resume for a needs_operator run.

    Form shape (per unresolved name/token, dynamic field names keyed by the LOOP INDEX
    over decision.unresolved_names — never by the raw token text, so a field name can
    never collide with an ill-formed or injected token string):
      - employee_id_{i}: the operator-selected roster employee id for token i
      - remember_{i}: checkbox, present (any value) = ON, absent = OFF (default-checked
        in the template; an unchecked box posts nothing at all for that key)

    Server-side roster validation: every posted employee_id MUST belong to
    `load_roster_for_business(run.business_id)` — never trust the dropdown. ANY
    invalid / unknown / cross-business id rejects the WHOLE POST, with no partial apply
    and no state change: the run stays needs_operator and the operator sees the same
    page again. Applying a POST partially would silently route some hours to the wrong
    employee — a tampered request must be a clean no-op, not a partial misroute.

    On a valid POST: commit a fresh immutable generation plus its identifier-only
    OPERATOR_RESUME job in one transaction. The repository lock, not worker order,
    selects the first committed generation as authority. Every later committed
    generation remains auditable and gets its own job, but redirects with only the
    fixed ``resolution_superseded`` flag. Alias candidates are deliberately not
    projected here; winner preparation in the durable handler is the only projection
    boundary.

    Always 303 — scheduling only, no LLM/provider call in this request's synchronous path.
    """
    try:
        run = repo.load_run(run_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    if run.get("status") != RunStatus.NEEDS_OPERATOR.value:
        # Not (or no longer) awaiting an operator resolution — no-op redirect
        # rather than erroring; a stale page reload/double-submit is harmless.
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
    if _is_delivery_review_marker(run):
        # Delivery uncertainty is a separate operator decision. In particular, do
        # not let a clarification that may already have reached the client become an
        # alias write or a generic pipeline restart through this form.
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)

    decision = run.get("decision") or {}
    unresolved_names = decision.get("unresolved_names") or []
    if not unresolved_names:
        # Nothing to resolve (shouldn't normally happen for a needs_operator
        # run, but fail safe rather than 500 on a malformed/legacy row).
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)

    try:
        roster = repo.load_roster_for_business(run["business_id"])
    except Exception:
        logger.warning("resolve: roster load failed for run %s", run_id)
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
    roster_ids = {str(emp.id) for emp in roster.employees}

    form = await request.form()

    # Validate EVERY posted employee_id against the run's OWN business roster before
    # applying anything. Reject the WHOLE POST — no partial apply — on any
    # invalid/unknown/cross-business id: a partially-applied mapping would pay some
    # employees against another business's roster.
    overrides: dict[str, str] = {}
    remember: dict[str, bool] = {}
    for i, token in enumerate(unresolved_names):
        posted_id = form.get(f"employee_id_{i}")
        if posted_id is None or str(posted_id) not in roster_ids:
            logger.warning(
                "resolve: rejected whole POST for run %s — invalid/missing "
                "employee_id at index %d",
                run_id,
                i,
            )
            return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
        overrides[token] = str(posted_id)
        remember[token] = form.get(f"remember_{i}") is not None

    operator_resolution_id = uuid.uuid4()
    try:
        with repo.get_connection() as conn, conn.transaction():
            submission = repo.commit_operator_resume_resolution(
                run_id,
                operator_resolution_id,
                overrides,
                remember,
                conn=conn,
            )
            repo.enqueue_job(
                kind=JobKind.OPERATOR_RESUME,
                dedup_key=repo.operator_resume_dedup_key(
                    run_id, operator_resolution_id
                ),
                run_id=run_id,
                operator_resolution_id=operator_resolution_id,
                conn=conn,
            )
    except ValueError:
        # A stale or conflicting browser submission is a bounded no-op. Do not expose
        # names, mappings, employee ids, or the competing generation in the response.
        logger.info("resolve generation rejected by authoritative state")
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)

    # Commit is visible before the worker can observe the wake signal.
    wake.wake()
    suffix = "?resolution_superseded=1" if not submission.authoritative else ""
    return RedirectResponse(url=f"/runs/{run_id}{suffix}", status_code=303)


def _claim_stale_in_flight(run_id: uuid.UUID, conn: psycopg.Connection) -> bool:
    """Stale in-flight recovery: claim a RECEIVED/EXTRACTING/COMPUTED/SENT run whose
    updated_at is genuinely stale. Conn-aware extraction of retrigger()'s inline logic —
    same scope, same rule, same comments; the ONLY change from the original inline block
    is that every repo call below threads `conn=conn` into retrigger()'s caller-owned
    transaction instead of each opening its own.

    Returns False (no-op) if the run is missing, not stale, or outside the stale scope.
    Returns True when the caller may proceed to clear_reply_context + enqueue_job — for
    EXTRACTING/COMPUTED/SENT that means this call ALSO won a real status CAS; for
    RECEIVED it means the staleness check passed with no status write at all (see the
    branch's own comment for why a write there would be actively wrong under QUEUE-02).
    """
    run = repo.load_run(run_id, conn=conn)
    if run is None:
        return False
    updated_at = run.get("updated_at")
    stale = (
        updated_at is not None
        and datetime.now(tz=UTC) - updated_at > STALE_THRESHOLD
    )
    # This operator-authorized scope is FOUR statuses, including SENT. A SENT run has
    # already durably committed provider-send evidence, so it is safe to include only
    # because delivery's already-sent idempotency guard suppresses a second
    # confirmation. Automatic queue recovery has its own transport-state policy and
    # must never copy this browser action's business-state scope.
    stale_statuses = {
        RunStatus.RECEIVED.value,
        RunStatus.EXTRACTING.value,
        RunStatus.COMPUTED.value,
        RunStatus.SENT.value,
    }
    if not (stale and run["status"] in stale_statuses):
        return False

    if run["status"] == RunStatus.RECEIVED.value:
        # QUEUE-02: a stale RECEIVED run has no other real state to claim FROM —
        # RECEIVED->RECEIVED is a no-op UPDATE and grants no exclusivity (a second,
        # concurrently-blocked UPDATE re-evaluates its WHERE clause against the
        # post-commit row and ALSO succeeds). Pre-Phase-16 that forced a jump straight
        # to EXTRACTING purely to get a real, differing status write. Under the queue,
        # that jump actively breaks the enqueued job: the drained handler's OWN sole
        # forward transition is claim_status(RECEIVED -> EXTRACTING) — INVARIANT J-1's
        # one permitted forward writer — and it would find the run already sitting at
        # EXTRACTING and lose its claim, completing the job without ever calling
        # execute the pipeline. A "lost job" for exactly the run this retrigger was meant to
        # revive. So this branch performs NO status write and leaves the run genuinely
        # at RECEIVED, exactly the state the handler's forward claim expects to find.
        # Exclusivity between two concurrent retrigger clicks is provided one layer
        # down instead: both may pass this check and both may enqueue a job (a
        # harmless extra row, with its own epoch bump), but the handler's forward CAS
        # is itself a genuine single-winner claim on drain — only the job that drains
        # first ever advances the run past RECEIVED; every later one loses its claim
        # and completes as a no-op, exactly like any other lost forward CAS.
        logger.info("stale RECEIVED run %s eligible for retrigger re-enqueue", run_id)
        return True

    # The claim target MUST differ from the current status: every stale status here
    # (EXTRACTING/COMPUTED/SENT) claims back to RECEIVED. This guarantees the
    # conditional UPDATE actually changes the row, so two concurrent retrigger clicks
    # cannot both win and run the pipeline twice — and it leaves the run at RECEIVED,
    # exactly what the drained job's own forward claim_status(RECEIVED -> EXTRACTING)
    # expects to find.
    # NOTE: COMPUTING is NOT a RunStatus member — the valid post-calc
    # in-flight state is COMPUTED.
    claimed = repo.claim_status(
        run_id, RunStatus(run["status"]), RunStatus.RECEIVED, conn=conn
    )
    if claimed:
        logger.info(
            "stale run %s (%s) claimed to %s",
            run_id,
            run["status"],
            RunStatus.RECEIVED.value,
        )
    return claimed


@router.post("/runs/{run_id}/retrigger")
def retrigger(run_id: uuid.UUID) -> RedirectResponse:
    """Retrigger a run from ERROR, APPROVED, or stale in-flight states (INGEST-05).

    Retrigger can also claim from stale RECEIVED/EXTRACTING/COMPUTED/SENT states: a
    worker that died mid-run otherwise leaves the run stuck forever with no recovery UI.
    See `_claim_stale_in_flight` for that branch's full scope/rule.

    QUEUE-02: the winning CAS (either the ERROR/APPROVED core claim or the stale
    in-flight claim), the reply-context clear, and the durable job enqueue ALL commit
    inside ONE caller-owned transaction below. A crash anywhere in that block means
    nothing happened at all — no state advanced without a job, and no job without a
    state advance. `wake.wake()` fires strictly AFTER the block exits and the
    transaction has committed: firing it any earlier would let the woken worker race
    ahead of visibility, find nothing to claim, and go back to sleep — degrading
    Retrigger from instant to the queue's slow poll interval.

    KNOWN LIMITATION — reply-context loss on retrigger (accepted, not a bug): a stranded
    run that originally entered via a clarification REPLY (non-empty clarified_fields or
    a pre_clarify_extracted snapshot), once claimed here — by either the ERROR/APPROVED
    CAS below or the stale in-flight branch — enqueues an identifier-only RUN_PIPELINE
    job because retrigger cannot tell that the stranded run was entered via a reply.
    Runs are never auto-restarted; the operator's retrigger IS the accepted recovery
    mechanism, and making retrigger reply-aware is new state-machine capability,
    deliberately out of scope. Consequence: the durable handler restarts cleanly from
    the ORIGINAL inbound email, and the in-flight reply context it was processing when
    it stranded is lost. The operator retains full visibility (the run reaches ERROR and
    is diagnosable) and can re-send the clarification context as a fresh email if the
    retriggered result looks wrong.

    NOTE: COMPUTED is the correct post-calculation in-flight status; there is no
    COMPUTING member in RunStatus.

    Retrigger is safe for SENT because delivery re-checks
    get_outbound_message_id(purpose='confirmation') before sending. RECONCILED is the
    only true terminal-success state; a run stranded in SENT (worker died between
    set_status(SENT) and set_status(RECONCILED)) can be re-run from the start without
    the client receiving a second confirmation email.
    """
    with repo.get_connection() as conn, conn.transaction():
        # A possible provider acceptance must be resolved through its purpose-aware
        # delivery review. Guard before any status CAS, context clear, or job enqueue.
        if _is_delivery_review_marker(repo.load_run(run_id, conn=conn)):
            return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
        # Core CAS claims — always safe: delivery's purpose-aware already-sent guard
        # prevents a duplicate confirmation email even if the run already sent one.
        claimed = (
            repo.claim_status(run_id, RunStatus.ERROR, RunStatus.RECEIVED, conn=conn)
            or repo.claim_status(
                run_id, RunStatus.APPROVED, RunStatus.RECEIVED, conn=conn
            )
            or _claim_stale_in_flight(run_id, conn=conn)
        )
        if claimed:
            # Context lost means ALL of it. Clear clarified_fields + pre_clarify_extracted
            # + the round counter + suggestion/candidate state AFTER the winning claim
            # (every branch above converges here) and BEFORE the pipeline re-run is
            # enqueued. The retriggered run re-extracts from the ORIGINAL email, so any
            # surviving reply context would be stale: is_round_2 = bool(clarified) would
            # misread a fresh run as a round-2 resume, and a provenance badge would
            # outlive the data that produced it — pointing at values the run no longer
            # holds. clear_reply_context ALSO bumps reply_epoch and returns the new
            # value — the discriminator the dedup_key below keys on, so a SECOND
            # legitimate retrigger is never swallowed by ON CONFLICT against the FIRST
            # retrigger's now-done job row.
            epoch = repo.clear_reply_context(run_id, conn=conn)
            repo.enqueue_job(
                kind=JobKind.RUN_PIPELINE,
                run_id=run_id,
                dedup_key=f"run_pipeline:{run_id}:{epoch}",
                conn=conn,
            )
    # ── Transaction committed. Everything below is post-commit. ────────────────────
    if claimed:
        logger.info("run_id=%s reply context cleared on retrigger", run_id)
        # Strictly after commit — see the docstring above for why firing this any
        # earlier defeats the point of the wake signal.
        wake.wake()
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


# ---------------------------------------------------------------------------
# Helper: build alias-rationale notes from the run's decision resolutions
# ---------------------------------------------------------------------------


def _build_alias_rationale_notes(
    run: dict[str, Any], roster_fn: Callable[[uuid.UUID], Roster]
) -> list[str]:
    """Build a list of human-readable alias-rationale notes for source='alias' resolutions.

    Called by run_detail to populate the 'Name resolutions' section. Exception-safe:
    any parse error or lookup failure returns [] so a bad JSONB never breaks the route.

    Args:
        run: the run dict (may contain decision JSONB).
        roster_fn: callable(business_id) -> Roster, used to look up employee full names.

    Returns:
        List of strings like "Resolved 'Maria' to Maria Chen (known nickname from a
        prior confirmed run)."
    """
    try:
        decision = run.get("decision")
        if not decision:
            return []
        resolutions = decision.get("resolutions", [])
        if not resolutions:
            return []

        business_id = run.get("business_id")
        roster = roster_fn(business_id) if business_id else None
        emp_by_id: dict[str, Employee] = {}
        if roster is not None:
            for emp in roster.employees:
                emp_by_id[str(emp.id)] = emp

        notes: list[str] = []
        for res in resolutions:
            if res.get("source") != "alias":
                continue
            submitted_name = res.get("submitted_name", "")
            matched_id = res.get("matched_employee_id")
            if matched_id and str(matched_id) in emp_by_id:
                full_name = emp_by_id[str(matched_id)].full_name
            else:
                full_name = matched_id or "unknown"
            notes.append(
                f"Resolved '{submitted_name}' to {full_name} "
                "(known nickname from a prior confirmed run)."
            )
        return notes
    except Exception:  # noqa: BLE001 — exception-safe; route must never 500 from this
        return []


# ---------------------------------------------------------------------------
# DASH-01: GET /runs — operator triage queue
# ---------------------------------------------------------------------------


@router.get("/runs")
def runs_list(
    request: Request,
    demo_queue_error: str = Query(default=""),
) -> Response:
    """DASH-01: Read and render the reverse-chronological runs list.

    This unauthenticated GET is deliberately side-effect free. Durable queue workers
    own automatic recovery; operators use explicit mutation routes such as Retrigger.
    """
    try:
        runs = [_safe_run_for_browser(run) for run in repo.load_all_runs()]
    except Exception:
        # DB unavailable (no pool / no connection): render empty list rather than 500.
        # This keeps the dashboard functional during test runs and Render cold-starts
        # before the pool is warmed up.
        logger.debug("load_all_runs unavailable — rendering empty list")
        runs = []
    return templates.TemplateResponse(
        request,
        "runs_list.html",
        {
            "runs": runs,
            "demo_fixtures": DEMO_FIXTURES,
            "in_flight_statuses": list(IN_FLIGHT_STATUSES),
            "demo_queue_error": bool(demo_queue_error),
        },
    )


# ---------------------------------------------------------------------------
# DASH-02/03: GET /runs/{run_id} — run detail 3-column gate
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/status")
def run_status(run_id: uuid.UUID) -> JSONResponse:
    """Lightweight status poll endpoint for the vanilla-JS badge updater.

    Returns {"status": "<status>", "badge_class": "<class>", "badge_label": "<label>"}.
    The JS poller in run_detail.html / runs_list.html calls this every 2s per in-flight
    run, swaps the badge in-place, and stops polling when the status is settled —
    no full-page reload, no dropdown reset.
    """
    try:
        run = repo.load_run(run_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    safe_run = _safe_run_with_queue_projection(run_id, run)
    status = safe_run.get("status", "")
    return JSONResponse(
        content={
            "status": status,
            "badge_class": badge_class_filter(status),
            "badge_label": badge_label_filter(status),
            "failure": safe_run["failure"],
            "queue_label": safe_run["queue_label"],
            "queue_badge_class": safe_run["queue_badge_class"],
            "has_open_job": safe_run["has_open_job"],
        }
    )


@router.get("/runs/{run_id}/delivery-review/email")
def delivery_review_email(run_id: uuid.UUID) -> Response:
    """Serve the reviewable frozen email without regenerating delivery content."""
    delivery_review = _load_delivery_review(run_id)
    if delivery_review is None:
        raise HTTPException(status_code=404, detail="Frozen delivery review not found")
    email_id = delivery_review["review"]["email_id"]
    snapshot = repo.load_outbound_snapshot(run_id, email_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Frozen delivery review not found")
    subject = snapshot.get("subject")
    body = snapshot.get("body_text")
    message_id = snapshot.get("message_id")
    in_reply_to = snapshot.get("in_reply_to")
    references_header = snapshot.get("references_header")
    if not all(isinstance(value, str) for value in (subject, body, message_id)):
        raise HTTPException(status_code=404, detail="Frozen delivery review not found")
    subject_text = cast(str, subject)
    body_text = cast(str, body)
    message_id_text = cast(str, message_id)
    lines = [f"Subject: {subject_text}", f"Message-ID: {message_id_text}"]
    if isinstance(in_reply_to, str):
        lines.append(f"In-Reply-To: {in_reply_to}")
    if isinstance(references_header, str):
        lines.append(f"References: {references_header}")
    lines.extend(("", body_text))
    purpose = snapshot.get("purpose")
    filename = (
        "frozen-confirmation.txt"
        if purpose == "confirmation"
        else "frozen-clarification.txt"
    )
    return Response(
        content="\n".join(lines),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/runs/{run_id}/delivery-review/attachments/{attachment_id}")
def delivery_review_attachment(
    run_id: uuid.UUID, attachment_id: uuid.UUID
) -> StreamingResponse:
    """Stream one owned frozen attachment only while its review remains actionable."""
    delivery_review = _load_delivery_review(run_id)
    if delivery_review is None:
        raise HTTPException(status_code=404, detail="Frozen delivery review not found")
    attachment = repo.load_snapshot_attachment(
        run_id,
        delivery_review["review"]["snapshot_id"],
        attachment_id,
    )
    if attachment is None:
        raise HTTPException(status_code=404, detail="Frozen attachment not found")
    filename = attachment.get("filename")
    content = attachment.get("content")
    if not isinstance(filename, str) or not isinstance(content, bytes):
        raise HTTPException(status_code=404, detail="Frozen attachment not found")
    safe_filename = re.sub(r"[^\w.\-]", "_", filename, flags=re.ASCII) or "attachment"
    return StreamingResponse(
        BytesIO(content),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_filename}"'},
    )


@router.post("/runs/{run_id}/delivery-review/retry-now")
def retry_delivery_now(run_id: uuid.UUID) -> RedirectResponse:
    """Advance one existing eligible delivery job and wake only after commit."""
    should_wake = False
    try:
        with repo.get_connection() as conn, conn.transaction():
            delivery_review = _load_delivery_review(run_id, conn=conn)
            if delivery_review is not None:
                outcome = repo.advance_existing_send_job_due_now(
                    run_id,
                    delivery_review["review"]["email_id"],
                    conn=conn,
                )
                should_wake = outcome == repo.AdvanceSendJobOutcome.ADVANCED
    except Exception:
        logger.warning("delivery retry-now unavailable for run %s", run_id)
    if should_wake:
        wake.wake()
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@router.post("/runs/{run_id}/delivery-review/clarification/retry-now")
def retry_clarification_delivery_now(run_id: uuid.UUID) -> RedirectResponse:
    """Reopen only the existing frozen clarification job while replay is eligible."""
    should_wake = False
    try:
        with repo.get_connection() as conn, conn.transaction():
            delivery_review = _load_delivery_review(run_id, conn=conn)
            if delivery_review is not None and delivery_review["review_kind"] == (
                "clarification"
            ):
                outcome = repo.advance_existing_clarification_delivery_review_job_due_now(
                    run_id,
                    delivery_review["review"]["email_id"],
                    conn=conn,
                )
                should_wake = outcome == repo.AdvanceSendJobOutcome.ADVANCED
    except Exception:
        logger.warning("clarification delivery retry unavailable for run %s", run_id)
    if should_wake:
        wake.wake()
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


def _finish_clarification_delivery_review(
    run_id: uuid.UUID, target: RunStatus
) -> RedirectResponse:
    """CAS a clarification review to a provider-free explicit operator outcome."""
    try:
        with repo.get_connection() as conn, conn.transaction():
            delivery_review = _load_delivery_review(run_id, conn=conn)
            if delivery_review is not None and delivery_review["review_kind"] == (
                "clarification"
            ):
                repo.claim_status(
                    run_id,
                    RunStatus.NEEDS_OPERATOR,
                    target,
                    conn=conn,
                )
    except Exception:
        logger.warning("clarification delivery review outcome unavailable for run %s", run_id)
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@router.post("/runs/{run_id}/delivery-review/clarification/mark-handled")
def mark_clarification_delivery_handled(run_id: uuid.UUID) -> RedirectResponse:
    """Acknowledge the frozen question without sending another provider request."""
    return _finish_clarification_delivery_review(run_id, RunStatus.AWAITING_REPLY)


@router.post("/runs/{run_id}/delivery-review/clarification/reject")
def reject_clarification_delivery(run_id: uuid.UUID) -> RedirectResponse:
    """Reject an ambiguous clarification without alias writes or provider work."""
    return _finish_clarification_delivery_review(run_id, RunStatus.REJECTED)


@router.post("/runs/{run_id}/delivery-review/mark-delivered")
def mark_delivery_delivered(run_id: uuid.UUID) -> RedirectResponse:
    """Resolve delivery uncertainty without another provider request."""
    try:
        with repo.get_connection() as conn, conn.transaction():
            if _load_delivery_review(run_id, conn=conn) is not None:
                repo.claim_status(
                    run_id,
                    RunStatus.NEEDS_OPERATOR,
                    RunStatus.RECONCILED,
                    conn=conn,
                )
    except Exception:
        logger.warning("mark delivery review unavailable for run %s", run_id)
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@router.post("/runs/{run_id}/delivery-review/authorize")
def authorize_new_confirmation(
    run_id: uuid.UUID,
    acknowledgement: str = Form(default=""),
) -> RedirectResponse:
    """Create one explicit new confirmation slot from the stored frozen snapshot."""
    if acknowledgement != _NEW_CONFIRMATION_ACKNOWLEDGEMENT:
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)

    should_wake = False
    try:
        with repo.get_connection() as conn, conn.transaction():
            delivery_review = _load_delivery_review(run_id, conn=conn)
            if delivery_review is None:
                return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
            if not repo.claim_status(
                run_id,
                RunStatus.NEEDS_OPERATOR,
                RunStatus.APPROVED,
                conn=conn,
            ):
                return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
            original = repo.load_outbound_snapshot(
                run_id, delivery_review["review"]["email_id"], conn=conn
            )
            if original is None:
                raise ValueError("frozen confirmation disappeared during authorization")
            attachments, envelope = _snapshot_clone_fields(original)
            repo.clear_reply_context(run_id, conn=conn)
            replacement = repo.reserve_outbound_snapshot(
                run_id=run_id,
                purpose="confirmation",
                round=0,
                message_id=f"<{uuid.uuid4()}@payroll-agent.local>",
                from_addr=cast(str, envelope["from_addr"]),
                to_addr=cast(str, envelope["to_addr"]),
                reply_to=envelope["reply_to"],
                in_reply_to=envelope["in_reply_to"],
                references_header=envelope["references_header"],
                subject=cast(str, envelope["subject"]),
                body_text=cast(str, envelope["body_text"]),
                attachments=attachments,
                conn=conn,
            )
            email_id = replacement.get("email_id")
            if not isinstance(email_id, uuid.UUID):
                raise ValueError("replacement confirmation lacks an email id")
            repo.enqueue_job(
                kind=JobKind.SEND_OUTBOUND,
                dedup_key=repo.send_outbound_dedup_key(email_id),
                run_id=run_id,
                email_id=email_id,
                conn=conn,
            )
            should_wake = True
    except Exception:
        logger.warning("new confirmation authorization unavailable for run %s", run_id)
    if should_wake:
        wake.wake()
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@router.get("/runs/{run_id}")
def run_detail(
    request: Request,
    run_id: uuid.UUID,
    resolution_superseded: str = Query(default=""),
) -> Response:
    """DASH-02/03: Render the 3-column run detail (raw email | extracted | paystubs)
    with decision banner and operator controls gated by status."""
    try:
        run = repo.load_run(run_id)
    except Exception as exc:
        logger.debug("load_run unavailable for run %s", run_id)
        raise HTTPException(status_code=404, detail="Run not found") from exc
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        raw_email = repo.load_inbound_email(run_id)
        paystubs = repo.load_line_items(run_id)
    except Exception:
        logger.debug("load_inbound_email/load_line_items unavailable for run %s", run_id)
        raw_email = None
        paystubs = []
    # Load outbound emails (confirmation / clarification) sent for this run.
    try:
        outbound_emails = repo.load_outbound_emails(run_id)
    except Exception:
        logger.debug("load_outbound_emails unavailable for run %s", run_id)
        outbound_emails = []
    # Load the full thread (inbound source row via OR subquery + all outbound rows).
    try:
        thread_messages = repo.load_thread_messages(run_id)
    except Exception:
        logger.debug("load_thread_messages unavailable for run %s", run_id)
        thread_messages = []
    # Alias-rationale notes for source='alias' resolutions. PRESENTATION ONLY — these
    # never feed back into resolution or the calc.
    try:
        alias_rationale_notes = _build_alias_rationale_notes(run, repo.load_roster_for_business)
    except Exception:
        alias_rationale_notes = []
    # Load clarified_fields for provenance badge rendering in the template. Provides a
    # submitted_name → {field: outcome} lookup so the template can render the four
    # outcome badges (carried-forward / client-removed / client-supplied /
    # awaiting-reply) on the hours rows a clarification round touched.
    try:
        clarified_fields_by_id = repo.load_clarified_fields(run_id) or {}
        # Build reconciliation lookup: submitted_name → employee_id_str
        recon = (run.get("reconciliation") or []) if run else []
        name_to_emp_id: dict[str, str] = {}
        for m in recon:
            if isinstance(m, dict) and m.get("matched_employee_id"):
                name_to_emp_id[m["submitted_name"]] = str(m["matched_employee_id"])
        # Build submitted_name → {field: outcome} lookup for template access
        clarified_fields_by_name: dict[str, dict[str, str]] = {}
        for submitted_name, emp_id_str in name_to_emp_id.items():
            field_outcomes = clarified_fields_by_id.get(emp_id_str)
            if field_outcomes:
                clarified_fields_by_name[submitted_name] = field_outcomes
    except Exception:
        logger.debug("load_clarified_fields unavailable for run %s", run_id)
        clarified_fields_by_name = {}
    # For a needs_operator run, the template needs (a) the business's roster employees
    # to populate each unresolved name's dropdown and (b) the persisted per-token
    # suggestion (the nested alias_candidates shape) to pre-select the LLM's ADVISORY
    # guess — the operator still makes the call. Both loads are best-effort: a failure
    # degrades to an empty dropdown / no pre-selection rather than a 500, matching every
    # other try/except-debug block on this route.
    roster_employees: list[Employee] = []
    unresolved_suggestions: dict[str, str] = {}
    if run.get("status") == RunStatus.NEEDS_OPERATOR.value and not _is_delivery_review_marker(
        run
    ):
        try:
            roster_employees = repo.load_roster_for_business(run["business_id"]).employees
        except Exception:
            logger.debug("load_roster_for_business unavailable for run %s", run_id)
            roster_employees = []
        try:
            alias_candidates = run.get("alias_candidates") or {}
            for token, value in alias_candidates.items():
                cand = value if isinstance(value, dict) else {}
                suggested = cand.get("suggested")
                if suggested is not None:
                    unresolved_suggestions[token] = str(suggested)
        except Exception:
            unresolved_suggestions = {}
    delivery_review: dict[str, Any] | None = None
    delivery_review_marker = _is_delivery_review_marker(run)
    if run.get("status") == RunStatus.NEEDS_OPERATOR.value:
        try:
            review = _load_delivery_review(run_id)
            if review is not None:
                delivery_review = _safe_delivery_review_projection(run_id, review)
        except Exception:
            logger.debug("delivery review unavailable for run %s", run_id)
    return templates.TemplateResponse(
        request,
        "run_detail.html",
        {
            "run": _safe_run_with_queue_projection(run_id, run),
            "raw_email": raw_email,
            "paystubs": paystubs,
            "outbound_emails": outbound_emails,
            "thread_messages": thread_messages,
            "alias_rationale_notes": alias_rationale_notes,
            "in_flight_statuses": list(IN_FLIGHT_STATUSES),
            "clarified_fields_by_name": clarified_fields_by_name,
            "roster_employees": roster_employees,
            "unresolved_suggestions": unresolved_suggestions,
            "resolution_superseded": bool(resolution_superseded),
            "delivery_review": delivery_review,
            "delivery_review_marker": delivery_review_marker,
        },
    )


# ---------------------------------------------------------------------------
# HITL-03: GET /runs/{run_id}/pdf/{employee_id} — on-demand paystub PDF
# ---------------------------------------------------------------------------


@router.get("/runs/{run_id}/pdf/{employee_id}")
def paystub_pdf(run_id: uuid.UUID, employee_id: uuid.UUID) -> StreamingResponse:
    """HITL-03: Stream a per-employee paystub PDF. Generated in-memory; no disk write."""
    from app.pipeline.pdf import generate_paystub_pdf

    paystubs = repo.load_line_items(run_id)
    item = next(
        (p for p in paystubs if str(p.employee_id) == str(employee_id)), None
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Paystub not found")

    run = repo.load_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    roster = repo.load_roster_for_business(run["business_id"])
    emp = next((e for e in roster.employees if e.id == employee_id), None)
    emp_name = emp.full_name if emp else item.submitted_name

    pdf_bytes = generate_paystub_pdf(
        item,
        emp_name,
        run.get("pay_period_start"),
        run.get("pay_period_end"),
        business_name=repo.load_business_name(run["business_id"]),
        filing_status=emp.filing_status if emp else None,
        hourly_rate=emp.hourly_rate if emp else None,
    )
    # Sanitize the filename to a safe charset BEFORE embedding it in the Content-Disposition
    # header. emp_name can be an LLM-extracted submitted_name (when the matched employee was
    # removed from the roster post-run), so a raw value could carry a double-quote or a CRLF
    # — enough to terminate the filename early or inject an entire extra response header.
    # The re.ASCII flag is REQUIRED: without it Python's unicode-aware \w passes through
    # chars above U+00FF (e.g. "ł", "ı"), which then raise UnicodeEncodeError when Starlette
    # latin-1-encodes the header — a 500 on any non-latin-1 employee name. re.ASCII restricts
    # \w to [A-Za-z0-9_], which is always latin-1 safe. Do not loosen this pattern.
    safe_name = re.sub(r"[^\w.\-]", "_", emp_name, flags=re.ASCII) or "employee"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="paystub_{safe_name}.pdf"'},
    )


@router.post("/runs/{run_id}/simulate-reply")
def simulate_reply(
    run_id: uuid.UUID,
    reply_body: str = Form(default=""),
) -> RedirectResponse:
    """Simulate a client email reply to complete an awaiting_reply run in the demo.

    DEMO-ONLY affordance; in production a real inbound webhook carries the reply.

    Constructs a synthetic InboundEmail that mirrors the RFC threading a real client
    reply would carry (same In-Reply-To / References as the clarification outbound,
    same from_addr as the original inbound sender), then persists, authorizes, and
    enqueues it through the same durable reply classifier as delayed ingest.

    The sender spoof guard passes because from_addr is taken from the run's own source
    inbound email (the original business contact email), which is the same address
    find_business_by_sender resolves. Synthesizing any other from_addr here would be
    correctly rejected by that guard.

    Guards:
    - 303 no-op if run.status != 'awaiting_reply' (nothing to reply to)
    - 303 no-op if no clarification Message-ID exists in outbound rows
    - 303 no-op if the run's source inbound email cannot be loaded
    - SSRF-safe: no client-supplied run targeting beyond the path run_id;
      reply_body is used only as body_text of the synthetic email (no headers)
    """
    # Load the run; 404 if missing.
    try:
        run = repo.load_run(run_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")

    # Guard: only act for awaiting_reply runs.
    if run.get("status") != RunStatus.AWAITING_REPLY.value:
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)

    # Look up the clarification outbound Message-ID.
    try:
        clar_mid = repo.get_outbound_message_id(run_id, purpose="clarification")
    except Exception:
        clar_mid = None
    if not clar_mid:
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)

    # Load the run's source inbound email to get the original sender address. Using
    # from_addr from the original inbound is what lets the sender spoof guard pass —
    # find_business_by_sender resolves this address to the same business.
    try:
        source_inbound = repo.load_inbound_email(run_id)
    except Exception:
        source_inbound = None
    if source_inbound is None:
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)

    from_addr = source_inbound.from_addr
    to_addr = source_inbound.to_addr
    original_subject = source_inbound.subject or "your payroll question"

    # Build the synthetic reply payload.  Fresh message_id each call so the
    # uq_message_id UNIQUE constraint never rejects a repeat simulation click.
    synthetic_message_id = f"<{uuid.uuid4()}@sim-reply.payroll-agent.local>"
    synthetic_payload = {
        "id": str(uuid.uuid4()),
        "message_id": synthetic_message_id,
        "in_reply_to": clar_mid,
        "references_header": clar_mid,
        "subject": "Re: " + original_subject,
        "from_addr": from_addr,
        "to_addr": to_addr,
        "body_text": reply_body,
        "created_at": datetime.now(tz=UTC).isoformat(),
    }

    # Route through the SAME entry as the real webhook uses.
    email = gateway.parse_inbound(synthetic_payload)
    cleaned = clean_body(email.body_text)

    try:
        with repo.get_connection() as conn, conn.transaction():
            routed = pipeline_glue.persist_and_enqueue_reply(
                email,
                cleaned,
                conn=conn,
            )
    except Exception:
        logger.warning("simulate-reply durable enqueue failed")
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)

    if routed.should_wake:
        wake.wake()
        logger.info("simulate-reply durable resume queued")
    else:
        logger.info("simulate-reply no-op outcome=%s", routed.outcome.value)
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
