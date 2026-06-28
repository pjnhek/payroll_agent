"""FastAPI entrypoint — the thin webhook adapter + operator gate routes.

This is a THIN HTTP adapter (RESEARCH Architecture map): no business logic, no
LLM, no calc. It does only the cheap, synchronous, idempotency-critical work, then
schedules the LLM-heavy pipeline as a FastAPI BackgroundTask and returns 200 fast
(INGEST-01, D-A1-01).

Endpoints:
  POST /webhook/inbound          — ingest an InboundEmail, dedupe, sender-match,
                                   clean the body, create the run, schedule run_pipeline
  POST /runs/{run_id}/approve    — hardened approve: CAS claim + _deliver (D-13b error
                                   boundary) → 303 POST-redirect-GET to run detail
  POST /runs/{run_id}/reject     — CAS claim → REJECTED → 303
  POST /runs/{run_id}/retrigger  — claim from ERROR/APPROVED/stale-in-flight → restart
                                   pipeline in background → 303 (INGEST-05, finding #6)
  GET  /runs                     — DASH-01 operator triage queue (Jinja2)
  GET  /runs/{run_id}            — DASH-02/03 run detail 3-column gate (Jinja2)
  GET  /eval                     — DASH-04 eval view (Jinja2)
  GET  /eval/chart.svg           — serve the committed eval chart SVG
  GET  /runs/{run_id}/pdf/{emp}  — HITL-03 on-demand paystub PDF (StreamingResponse)
  POST /demo/send-test           — DASH-05 demo button; mints fresh Message-ID per click

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

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.db import repo
from app.email import gateway
from app.email.clean import clean_body
from app.models.contracts import InboundEmail
from app.models.status import RunStatus

# Staleness threshold for stale in-flight state recovery (finding #6, D-13b extension).
# A run in a recoverable in-flight state (RECEIVED/EXTRACTING/COMPUTED/SENT) whose
# updated_at is older than this threshold may be claimed by retrigger for a fresh start.
# Fresh in-flight runs (recently updated) are never force-restarted.
STALE_THRESHOLD = timedelta(minutes=5)

# UAT #3: in-flight statuses — a run in any of these states is still processing.
# Templates receive an `auto_refresh` boolean driven from this constant so no status
# string is ever hardcoded in the HTML. Terminal statuses never trigger auto-refresh.
# IN-02 (REVIEW-2): awaiting_reply is included so the detail page keeps polling across the
# simulate-reply (and real-reply) transition — the badge advances awaiting_reply →
# extracting → … → needs_approval live, then the run-detail poll reloads once on settle to
# surface the resumed run's data. A run parked at awaiting_reply (no reply yet) simply polls
# with an unchanged badge until the 30-attempt cap, which is harmless.
IN_FLIGHT_STATUSES: frozenset[str] = frozenset(
    {"received", "extracting", "computed", "awaiting_reply"}
)

# UAT #6: curated allowlist of demo fixtures mapped to their seeded business.
# Only fixtures whose from_addr resolves via repo.find_business_by_sender are
# listed here — unknown senders are rejected by the webhook (INGEST-03 / T-05-22).
# Server validates the posted fixture_key against this dict; unknown keys fall
# back to Coastal to prevent SSRF via an arbitrary client-supplied path.
_DEMO_FIXTURES: dict[str, dict] = {
    "coastal_exact": {
        "label": "Coastal Cleaning Co. — exact match",
        "path": "eval/fixtures/01_exact_match_coastal.json",
        "business_name": "Coastal Cleaning Co.",
    },
    "metro_alias": {
        "label": "Metro Deli — stored alias",
        "path": "eval/fixtures/02_stored_alias_metro.json",
        "business_name": "Metro Deli Group",
    },
    "summit_exact": {
        "label": "Summit Tech — exact match",
        "path": "eval/fixtures/12_exact_process_summit.json",
        "business_name": "Summit Tech Solutions",
    },
    "coastal_multi": {
        "label": "Coastal Cleaning Co. — multi-employee",
        "path": "eval/fixtures/10_multi_employee_coastal.json",
        "business_name": "Coastal Cleaning Co.",
    },
    "unknown_shorthand_metro": {
        "label": "Metro Deli — unknown shorthand 'Dave Reyes' (clarify + suggest)",
        "path": "eval/fixtures/04_unknown_shorthand_metro.json",
        "business_name": "Metro Deli Group",
    },
}
_DEMO_FIXTURE_DEFAULT_KEY = "coastal_exact"

# ---------------------------------------------------------------------------
# D-06 / CHANGE-5 / HIGH-2: demo routing constants (06-08)
# ---------------------------------------------------------------------------

# Hardcoded operator email for Path-2 demo binding (D-06 / CHANGE-5 / HIGH-2).
# bind_demo_business writes demo_sender_bindings for Path-2 routing; never user-supplied.
DEMO_OPERATOR_EMAIL = "pjnhek@gmail.com"

# Stable seed .example contacts; NEVER mutated by /demo/bind (HIGH-2 fix).
# Source: app/db/seed.py _BUSINESSES list. These match the seeded contact_email values.
_SEED_CONTACTS: dict[str, str] = {
    "Coastal Cleaning Co.": "payroll@coastalcleaning.example",
    "Metro Deli Group": "hr@metrodeli.example",
    "Summit Tech Solutions": "finance@summittech.example",
}

# Stable seed UUIDs; /demo/compose uses these directly — no find_business_by_sender call (HIGH-2 fix).
# Source: app/db/seed.py _BUSINESSES list (fixed literals, D-11).
_SEED_BUSINESS_IDS: dict[str, uuid.UUID] = {
    "Coastal Cleaning Co.": uuid.UUID("b0000001-0000-0000-0000-000000000001"),
    "Metro Deli Group": uuid.UUID("b0000002-0000-0000-0000-000000000002"),
    "Summit Tech Solutions": uuid.UUID("b0000003-0000-0000-0000-000000000003"),
}

logger = logging.getLogger("payroll_agent.webhook")

app = FastAPI(title="Payroll Agent")

# ---------------------------------------------------------------------------
# Jinja2 templates + static files (DASH-01..05)
# ---------------------------------------------------------------------------

templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Badge class mapping (UI-SPEC Badge Contract)
_BADGE_CLASS: dict[str, str] = {
    "received": "neutral",
    "extracting": "neutral",
    "computing": "neutral",
    "awaiting_reply": "neutral",
    "approved": "neutral",
    "computed": "neutral",
    "awaiting_approval": "pending",
    "sent": "good",
    "reconciled": "good",
    "rejected": "bad",
    "error": "bad",
}

# Badge label mapping (UI-SPEC Badge Contract copywriting)
_BADGE_LABEL: dict[str, str] = {
    "received": "Received",
    "extracting": "Extracting",
    "computing": "Computing",
    "awaiting_reply": "Awaiting Reply",
    "awaiting_approval": "Needs Approval",
    "approved": "Approved",
    "computed": "Computed",
    "sent": "Sent",
    "reconciled": "Complete",
    "rejected": "Rejected",
    "error": "Error",
}


def _badge_class_filter(status: str) -> str:
    """Map a payroll_runs.status to a CSS badge class suffix (UI-SPEC Badge Contract)."""
    return _BADGE_CLASS.get(str(status), "neutral")


def _badge_label_filter(status: str) -> str:
    """Map a payroll_runs.status to its display label (UI-SPEC Copywriting Contract)."""
    return _BADGE_LABEL.get(str(status), str(status).replace("_", " ").title())


templates.env.filters["badge_class"] = _badge_class_filter
templates.env.filters["badge_label"] = _badge_label_filter


# ---------------------------------------------------------------------------
# D-20: Health probes — liveness (no DB) and readiness (SELECT)
# ---------------------------------------------------------------------------


@app.get("/health/live")
def health_live() -> JSONResponse:
    """Liveness probe — no DB hit. Render deploy healthCheckPath target (D-20).

    T-06-02-01: Returns {"status": "ok"} only — no version, no stack, no DB state.
    A Supabase blip during deploy must NOT fail this check (that is why no DB is
    touched here). render.yaml points healthCheckPath at this route.
    """
    return JSONResponse({"status": "ok"})


@app.get("/health/ready")
def health_ready() -> JSONResponse:
    """Readiness probe — runs a real SELECT. GitHub Actions keep-alive target (D-16/D-20).

    Touches a real table (businesses) so Supabase free project registers DB activity
    and does not pause (D-16 / RESEARCH Pitfall 5 / Assumption A7).
    A bare SELECT 1 without a real table may not count as 'use' in Supabase's pause
    detection. On DB failure raises 503 — correct for a failed readiness probe.

    T-06-02-02: On failure raises 503 with "database not ready" only — no connection
    string or stack trace in the response body.
    """
    try:
        from app.db.supabase import get_connection

        with get_connection() as conn:
            conn.execute("SELECT 1 FROM businesses LIMIT 1")
        return JSONResponse({"status": "ready"})
    except Exception as exc:
        logger.error("readiness probe failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="database not ready")


@app.post("/webhook/inbound")
async def inbound(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    """Ingest one inbound email, schedule the pipeline, return 200 fast.

    Route restructure (06-04 HIGH-2 dual-path + HIGH-4 prod auth closure):

    Security ordering (MEDIUM-5 verify-before-parse):
      1. Read raw_body bytes first (needed for HMAC verification against the raw payload).
      2. Check for svix-* signature headers:
         - If svix-* headers present (Resend-signed webhook): verify BEFORE json.loads.
           ValueError from verify → 400 before any JSON parsing.
         - If svix-* headers absent AND allow_unsigned_fixtures=False (prod default):
           return 400 BEFORE json.loads. No need to parse an unauthorized request body.
         - If svix-* headers absent AND allow_unsigned_fixtures=True (dev/test mode):
           proceed to json.loads + parse. Both Resend-envelope and canonical shapes
           proceed through gateway.parse_inbound (which handles both via shape detection).
      3. parse_inbound(raw_body): dual-path, shape detection internal to gateway.
      4. insert_inbound_email: explicit ON CONFLICT DO NOTHING dedup.
         HIGH-4: pipeline enqueued ONLY if a new row was inserted (not a duplicate).
      5. Reply routing, sender auth, create_run, background task (unchanged).

    D-17 is NOT weakened: Resend-envelope payloads with bad/absent sig → 400.
    HIGH-4: canonical-shape POSTs also → 400 in prod (ALLOW_UNSIGNED_FIXTURES=False).
    """
    # Step 1: capture raw body bytes (needed for HMAC verification).
    raw_body: bytes = await request.body()

    settings = get_settings()
    allow_unsigned = settings.allow_unsigned_fixtures

    # Check for svix signature headers (indicates a Resend-signed webhook).
    is_signed = (
        "svix-id" in request.headers
        and "svix-timestamp" in request.headers
        and "svix-signature" in request.headers
    )

    # Step 2: MEDIUM-5 verify-before-parse ordering.
    if is_signed:
        # Signed Resend webhook: verify BEFORE json.loads. ValueError → 400.
        try:
            gateway.verify(raw_body, dict(request.headers), settings.webhook_signing_secret)
        except (ValueError, Exception) as exc:
            logger.warning("webhook signature verification failed: %s", type(exc).__name__)
            return JSONResponse(status_code=400, content={"error": "invalid signature"})
        # Signature passed — proceed to parse.
    elif not allow_unsigned:
        # Unsigned request in prod (ALLOW_UNSIGNED_FIXTURES=False): reject BEFORE json.loads.
        # HIGH-4: this closes the canonical-shape bypass in production — ANY unsigned POST
        # (Resend-envelope OR canonical InboundEmail shape) returns 400.
        logger.warning("unsigned webhook rejected in production (ALLOW_UNSIGNED_FIXTURES=False)")
        return JSONResponse(status_code=400, content={"error": "unsigned webhook not allowed"})
    # else: allow_unsigned=True (dev/test mode) — proceed to parse without verification.

    # Step 3: parse (dual-path: shape detection inside gateway.parse_inbound).
    # Path A (real Resend envelope) does a two-step fetch — resend.EmailsReceiving.get(email_id)
    # — which calls the Resend API and can fail (bad/insufficient RESEND_API_KEY, API error,
    # malformed payload). An unhandled raise here returns a raw 500 to Resend, which then
    # retries the delivery indefinitely and surfaces only as "internal server error" with no
    # diagnostic. Catch it: log the exception type + a hint, and return a clean 502 so the
    # failure is legible and Resend backs off. (Verification already happened above — D-17 intact.)
    try:
        email = gateway.parse_inbound(raw_body)
    except Exception as exc:  # noqa: BLE001 — webhook boundary: never leak a raw 500 to Resend
        logger.error(
            "inbound parse/fetch failed: %s (likely RESEND_API_KEY invalid or "
            "EmailsReceiving.get error) — returning 502, no run created",
            type(exc).__name__,
        )
        return JSONResponse(
            status_code=502,
            content={"error": "inbound parse failed", "reason": type(exc).__name__},
        )

    # FIX C: clean the body BEFORE persisting so email_messages.body_text holds the
    # cleaned text (the single cleaned-body source of truth the extraction reads).
    cleaned = clean_body(email.body_text)

    # Step 4: explicit dedup via ON CONFLICT DO NOTHING RETURNING id.
    # HIGH-4: enqueue pipeline ONLY if a new row was inserted (not a duplicate).
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
def approve(
    run_id: uuid.UUID,
    background_tasks: BackgroundTasks,
) -> RedirectResponse:
    """Hardened approve: CAS claim (AWAITING_APPROVAL → APPROVED) + D-13b delivery.

    Race-safety: claim_status is an atomic CAS — a second concurrent approval loses
    the claim and 303-redirects without running _deliver a second time (T-05-14,
    D-12, FOUND-04). Delivery is synchronous and bounded by D-10b timeout in
    compose_confirmation. On delivery exception: record ERROR (D-13b invariant —
    APPROVED is NOT terminal, so record_run_error can advance it to ERROR).

    PII-safe error logging (D-A1-03): error_reason = type(exc).__name__ ONLY.
    """
    from app.pipeline.orchestrator import _deliver

    claimed = repo.claim_status(run_id, RunStatus.AWAITING_APPROVAL, RunStatus.APPROVED)
    if claimed:
        try:
            # REVIEW-4 WR-01: load_run is INSIDE the D-13b boundary. A transient DB failure
            # during the load (e.g. pooler blip) must route to ERROR + error_reason like any
            # other delivery failure — not leave the run silently stuck at APPROVED with a
            # raw 500 (INGEST-05 "nothing silently hangs"). APPROVED is non-terminal, so
            # record_run_error can advance it to ERROR and the operator can retrigger.
            run = repo.load_run(run_id)
            _deliver(run_id, run)
        except Exception as exc:  # noqa: BLE001 — D-13b error boundary
            # PII-safe: type only — str(exc) may echo model output, submitted names,
            # or raw email content (D-A1-03). run_id is the correlation key for debug.
            logger.warning("delivery of run %s failed: %s", run_id, type(exc).__name__)
            repo.record_run_error(run_id, type(exc).__name__)
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@app.post("/runs/{run_id}/reject")
def reject(run_id: uuid.UUID) -> RedirectResponse:
    """Hardened reject: CAS claim (AWAITING_APPROVAL → REJECTED) → 303.

    claim_status is atomic — a concurrent rejection or approval sees False and no-ops
    (D-12, FOUND-04). Always 303 to run detail regardless of claim outcome.
    """
    repo.claim_status(run_id, RunStatus.AWAITING_APPROVAL, RunStatus.REJECTED)
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@app.post("/runs/{run_id}/retrigger")
def retrigger(
    run_id: uuid.UUID,
    background_tasks: BackgroundTasks,
) -> RedirectResponse:
    """Retrigger a run from ERROR, APPROVED, or stale in-flight states (INGEST-05).

    D-13b extension (finding #6): the retrigger path is extended to also claim from
    stale RECEIVED/EXTRACTING/COMPUTED/SENT states — a worker that died mid-run
    leaves the run stuck with no recovery UI otherwise.

    Stale guard: in-flight claims require updated_at older than STALE_THRESHOLD
    (5 minutes). A freshly-started in-flight run is never force-restarted.

    R2-HIGH stale CAS exclusivity (finding #6): the claim target MUST differ from the
    current status so the conditional UPDATE genuinely changes the row and two
    concurrent retrigger clicks cannot both win. A stale RECEIVED run → EXTRACTING
    (not RECEIVED→RECEIVED which is a no-op). All other stale statuses → RECEIVED.
    This prevents the degenerate case where the conditional UPDATE is a no-op and
    two concurrent callers both see the same row unchanged and both win.

    NOTE: COMPUTED is the correct post-calculation in-flight status (there is no
    COMPUTING member in RunStatus).

    The already-sent confirmation guard in _deliver makes retrigger safe for SENT:
    RECONCILED is the only true terminal-success; a run stranded in SENT (worker died
    between set_status(SENT) and set_status(RECONCILED)) can be safely re-run from
    start because _deliver checks get_outbound_message_id(purpose='confirmation')
    before re-sending.
    """
    # Core CAS claims (always safe — purpose-aware already-sent guard in _deliver
    # prevents duplicate confirmation emails even if the run already sent one).
    claimed = repo.claim_status(
        run_id, RunStatus.ERROR, RunStatus.RECEIVED
    ) or repo.claim_status(
        run_id, RunStatus.APPROVED, RunStatus.RECEIVED
    )

    if not claimed:
        # Stale in-flight recovery (finding #6): only claim if updated_at is stale.
        run = repo.load_run(run_id)
        if run is not None:
            updated_at = run.get("updated_at")
            stale = (
                updated_at is not None
                and datetime.now(tz=timezone.utc) - updated_at > STALE_THRESHOLD
            )
            stale_statuses = {
                RunStatus.RECEIVED.value,
                RunStatus.EXTRACTING.value,
                RunStatus.COMPUTED.value,
                RunStatus.SENT.value,
            }
            if stale and run["status"] in stale_statuses:
                # R2-HIGH stale CAS fix: target MUST differ from current status.
                # RECEIVED→EXTRACTING (not RECEIVED→RECEIVED no-op).
                # All other stale statuses→RECEIVED (EXTRACTING/COMPUTED/SENT→RECEIVED).
                # This guarantees the conditional UPDATE actually changes the row so
                # two concurrent retrigger clicks cannot both win.
                # NOTE: COMPUTING is NOT a RunStatus member — the valid post-calc
                # in-flight state is COMPUTED.
                target = (
                    RunStatus.EXTRACTING
                    if run["status"] == RunStatus.RECEIVED.value
                    else RunStatus.RECEIVED
                )
                claimed = repo.claim_status(
                    run_id, RunStatus(run["status"]), target
                )
                if claimed:
                    logger.info(
                        "stale run %s (%s) claimed to %s (finding #6, D-13b)",
                        run_id,
                        run["status"],
                        target.value,
                    )

    if claimed:
        background_tasks.add_task(_run_pipeline, run_id)
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


# ---------------------------------------------------------------------------
# Helper: build alias-rationale notes from the run's decision resolutions
# ---------------------------------------------------------------------------


def _build_alias_rationale_notes(run: dict, roster_fn) -> list[str]:
    """Build a list of human-readable alias-rationale notes for source='alias' resolutions.

    Called by run_detail to populate the 'Name resolutions' section. Exception-safe:
    any parse error or lookup failure returns [] so a bad JSONB never breaks the route.

    Args:
        run: the run dict (may contain decision JSONB).
        roster_fn: callable(business_id) -> Roster, used to look up employee full names.

    Returns:
        List of strings like "Resolved 'Maria' to Maria Chen (known nickname from a prior confirmed run)."
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
        emp_by_id = {}
        if roster is not None:
            for emp in roster.employees:
                emp_by_id[str(emp.id)] = emp

        notes = []
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
# GET / — recruiter landing page (self-serve demo, Path-1 in-app composer)
# ---------------------------------------------------------------------------


@app.get("/")
def landing(
    request: Request,
    business: str = Query(default=""),
    bound: str = Query(default=""),
):
    """Recruiter landing page with business picker + in-app composer.

    GET /: shows all three businesses; defaults to the first in list.
    GET /?business=<name>: shows the selected business's roster.

    The /demo/bind form is NOT on this page — it is an unlinked operator URL.
    The currently-armed binding (if any) is displayed read-only.
    """
    try:
        businesses = repo.list_businesses()
    except Exception:
        logger.debug("list_businesses unavailable — rendering empty picker")
        businesses = []

    # Resolve selected business name: prefer ?business= query param, else first in list.
    if business in _SEED_CONTACTS:
        selected_business_name = business
    elif businesses:
        selected_business_name = businesses[0]["name"]
    else:
        selected_business_name = ""

    # Resolve employees for the selected business (no DB call if name not in seed IDs).
    employees = []
    if selected_business_name in _SEED_BUSINESS_IDS:
        selected_business_id = _SEED_BUSINESS_IDS[selected_business_name]
        try:
            roster = repo.load_roster_for_business(selected_business_id)
            employees = roster.employees
        except Exception:
            logger.debug("load_roster_for_business unavailable for %s", selected_business_name)

    # Read-only armed business display (Path-2 state).
    try:
        armed_business_id = repo.get_demo_binding(DEMO_OPERATOR_EMAIL)
    except Exception:
        armed_business_id = None

    # Resolve the armed business_id to its human name HERE (not in the template): a
    # Jinja `{% set %}` inside a `{% for %}` does not escape the loop scope, so the
    # template's match always fell back to showing the raw UUID. Match in Python so the
    # landing page shows "Metro Deli Group", not "b0000002-…".
    armed_business_name = None
    if armed_business_id is not None:
        armed_business_name = next(
            (b["name"] for b in businesses if str(b["id"]) == str(armed_business_id)),
            None,
        )

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "businesses": businesses,
            "selected_business_name": selected_business_name,
            "employees": employees,
            "armed_business_id": armed_business_id,
            "armed_business_name": armed_business_name,
            "bound": bound,
            "demo_operator_email": DEMO_OPERATOR_EMAIL,
        },
    )


# ---------------------------------------------------------------------------
# POST /demo/bind — unlinked operator route (NOT on landing page)
# ---------------------------------------------------------------------------


@app.post("/demo/bind")
def demo_bind(
    business_name: str = Form(...),
) -> RedirectResponse:
    """Operator-only: bind an operator email to a business for Path-2 real-email routing.

    Writes to demo_sender_bindings ONLY — businesses.contact_email is NEVER mutated.
    Seed .example contacts remain permanently stable.

    SECURITY: business_name validated against _SEED_CONTACTS allowlist; operator_email
    is the hardcoded DEMO_OPERATOR_EMAIL constant — never user-supplied (T-06-08-02).
    """
    if business_name not in _SEED_CONTACTS:
        return RedirectResponse(url="/", status_code=303)

    success = repo.bind_demo_business(business_name, DEMO_OPERATOR_EMAIL, _SEED_BUSINESS_IDS)
    if success:
        return RedirectResponse(url="/?bound=1", status_code=303)
    return RedirectResponse(url="/", status_code=303)


# ---------------------------------------------------------------------------
# POST /demo/compose — in-app recruiter composer (Path-1, no real email)
# ---------------------------------------------------------------------------


@app.post("/demo/compose")
def demo_compose(
    background_tasks: BackgroundTasks,
    business_name: str = Form(...),
    subject: str = Form(default="Payroll submission"),
    body: str = Form(default=""),
) -> RedirectResponse:
    """Recruiter in-app composer: fires the REAL pipeline for the selected business.

    Routes by stable seed business_id directly (no find_business_by_sender call — HIGH-2
    fix). Sets record_only=True on create_run directly (LOW-6). The pipeline writes
    outbound rows WITHOUT calling Resend — the thread view and simulate-reply still work.

    SECURITY:
    - business_name validated against _SEED_CONTACTS allowlist (T-06-08-02)
    - body capped at 4000 chars, subject at 200 chars before any DB/LLM touch (T-06-08-08)
    - from_addr is allowlist-resolved from _SEED_CONTACTS — never user-supplied (T-06-08-02)
    - body goes to body_text only — no file open, no subprocess, no URL fetch (T-06-08-02)
    - Jinja2 autoescape handles XSS on subsequent rendering (T-06-08-03)
    """
    # Step 1: Validate business_name against allowlist.
    if business_name not in _SEED_CONTACTS:
        return RedirectResponse(url="/", status_code=303)

    # Step 2: Length validation (server-side, before DB or LLM touch).
    if len(body) > 4000 or len(subject) > 200:
        return RedirectResponse(url="/", status_code=303)

    # Step 3: Resolve business_id from stable seed constant — NO find_business_by_sender call.
    # This is the HIGH-2 fix: compose routes by the stable seed UUID directly.
    business_id = _SEED_BUSINESS_IDS[business_name]

    # Step 4: Set from_addr = seed .example contact (stable; never operator email).
    # Used for thread display and simulate-reply's FIX-5 spoof guard.
    from_addr = _SEED_CONTACTS[business_name]

    # Step 5: Build InboundEmail payload (mirrors demo_send_test construction).
    fresh_message_id = f"<{uuid.uuid4()}@demo.payroll-agent.local>"
    inbound_payload = {
        "id": str(uuid.uuid4()),
        "message_id": fresh_message_id,
        "in_reply_to": None,
        "references_header": None,
        "subject": subject or "Payroll submission",
        "from_addr": from_addr,
        "to_addr": "agent@payroll-agent.local",
        "body_text": body,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    try:
        # Step 6: Parse, clean, insert inbound email row.
        email = gateway.parse_inbound(inbound_payload)
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
        if not inserted:
            # Shouldn't happen (fresh uuid4 message_id per click), but handle gracefully.
            logger.warning("demo_compose: duplicate message_id — redirecting to /runs")
            return RedirectResponse(url="/runs", status_code=303)

        # Step 7: Create run with record_only=True passed directly (LOW-6).
        run_id = repo.create_run(
            business_id=business_id,
            source_email_id=email_id,
            record_only=True,
        )

        # Step 8: Schedule pipeline in background; redirect to run detail.
        background_tasks.add_task(_run_pipeline, run_id)
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)

    except Exception:
        logger.exception("demo_compose: failed to create compose run")
        return RedirectResponse(url="/", status_code=303)


# ---------------------------------------------------------------------------
# DASH-01: GET /runs — operator triage queue
# ---------------------------------------------------------------------------


@app.get("/runs")
def runs_list(request: Request):
    """DASH-01: Render the reverse-chronological runs list with status badges."""
    try:
        runs = repo.load_all_runs()
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
            "demo_fixtures": _DEMO_FIXTURES,
            "in_flight_statuses": list(IN_FLIGHT_STATUSES),
        },
    )


# ---------------------------------------------------------------------------
# DASH-02/03: GET /runs/{run_id} — run detail 3-column gate
# ---------------------------------------------------------------------------


@app.get("/runs/{run_id}/status")
def run_status(run_id: uuid.UUID) -> JSONResponse:
    """Lightweight status poll endpoint for the vanilla-JS badge updater (UAT #3/#4).

    Returns {"status": "<status>", "badge_class": "<class>", "badge_label": "<label>"}.
    The JS poller in run_detail.html / runs_list.html calls this every 2s per in-flight
    run, swaps the badge in-place, and stops polling when the status is settled —
    no full-page reload, no dropdown reset.
    """
    try:
        run = repo.load_run(run_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Run not found")
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    status = run.get("status", "")
    return JSONResponse(
        content={
            "status": status,
            "badge_class": _badge_class_filter(status),
            "badge_label": _badge_label_filter(status),
        }
    )


@app.get("/runs/{run_id}")
def run_detail(request: Request, run_id: uuid.UUID):
    """DASH-02/03: Render the 3-column run detail (raw email | extracted | paystubs)
    with decision banner and operator controls gated by status."""
    try:
        run = repo.load_run(run_id)
    except Exception:
        logger.debug("load_run unavailable for run %s", run_id)
        raise HTTPException(status_code=404, detail="Run not found")
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    try:
        raw_email = repo.load_inbound_email(run_id)
        paystubs = repo.load_line_items(run_id)
    except Exception:
        logger.debug("load_inbound_email/load_line_items unavailable for run %s", run_id)
        raw_email = None
        paystubs = []
    # UAT #1: load outbound emails (confirmation / clarification) sent for this run.
    try:
        outbound_emails = repo.load_outbound_emails(run_id)
    except Exception:
        logger.debug("load_outbound_emails unavailable for run %s", run_id)
        outbound_emails = []
    # 06-08: load full thread (inbound source row via OR subquery + all outbound rows).
    try:
        thread_messages = repo.load_thread_messages(run_id)
    except Exception:
        logger.debug("load_thread_messages unavailable for run %s", run_id)
        thread_messages = []
    # 06-08: alias-rationale notes for source='alias' resolutions (PRESENTATION ONLY).
    try:
        alias_rationale_notes = _build_alias_rationale_notes(run, repo.load_roster_for_business)
    except Exception:
        alias_rationale_notes = []
    # D-7.5-08: load clarified_fields for provenance badge rendering in the template.
    # Provides a submitted_name → {field: outcome} lookup so the template can render
    # the four outcome badges (carried-forward / client-removed / client-supplied /
    # awaiting-reply) on field-regression-affected hours rows.
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
    return templates.TemplateResponse(
        request,
        "run_detail.html",
        {
            "run": run,
            "raw_email": raw_email,
            "paystubs": paystubs,
            "outbound_emails": outbound_emails,
            "thread_messages": thread_messages,
            "alias_rationale_notes": alias_rationale_notes,
            "in_flight_statuses": list(IN_FLIGHT_STATUSES),
            "clarified_fields_by_name": clarified_fields_by_name,
        },
    )


# ---------------------------------------------------------------------------
# DASH-04: GET /eval — eval view with headline metrics + chart + per-fixture drill-in
# ---------------------------------------------------------------------------


@app.get("/eval")
def eval_view(request: Request):
    """DASH-04: Render the eval view. Hermetic disk read of committed eval artifacts.

    R2-MEDIUM fix: enriches each per_fixture record with raw_body loaded from the
    committed fixture file at eval/fixtures/<fixture_path>. eval/summary.json does
    NOT store body_text — the body lives in the fixture files. Rendering '—' does
    NOT satisfy DASH-04; each fixture's raw body is shown in the drill-in table.
    """
    summary_path = Path("eval/summary.json")
    summary = json.loads(summary_path.read_text()) if summary_path.exists() else None

    if summary is not None and "per_fixture" in summary:
        fixtures_dir = Path("eval/fixtures")
        for fixture in summary["per_fixture"]:
            fixture_file = fixtures_dir / fixture["fixture_path"]
            if fixture_file.exists():
                fixture_data = json.loads(fixture_file.read_text())
                fixture["raw_body"] = fixture_data.get("body_text", "")
            else:
                fixture["raw_body"] = "‹fixture file missing›"

    return templates.TemplateResponse(
        request,
        "eval.html",
        {
            "summary": summary,
            "demo_fixtures": _DEMO_FIXTURES,
        },
    )


# ---------------------------------------------------------------------------
# GET /eval/chart.svg — serve the committed eval chart
# ---------------------------------------------------------------------------


@app.get("/eval/chart.svg")
def eval_chart():
    """Serve the committed eval/chart.svg as image/svg+xml.

    # D-21: serves committed eval/chart.svg baked into image; relative path requires WORKDIR=/app (Dockerfile).
    """
    chart_path = Path("eval/chart.svg")
    if not chart_path.exists():
        raise HTTPException(status_code=404, detail="eval/chart.svg not found")
    return FileResponse(str(chart_path), media_type="image/svg+xml")


# ---------------------------------------------------------------------------
# HITL-03: GET /runs/{run_id}/pdf/{employee_id} — on-demand paystub PDF
# ---------------------------------------------------------------------------


@app.get("/runs/{run_id}/pdf/{employee_id}")
def paystub_pdf(run_id: uuid.UUID, employee_id: uuid.UUID):
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
    # CR-01 (REVIEW-2/3): sanitize the filename to a safe charset before embedding it in the
    # Content-Disposition header. emp_name can be an LLM-extracted submitted_name (when the
    # matched employee was removed from the roster post-run), so a raw value could carry a
    # double-quote or CRLF and break/inject the header. The re.ASCII flag is REQUIRED:
    # without it Python's unicode-aware \w passes through chars above U+00FF (e.g. "ł", "ı"),
    # which then raise UnicodeEncodeError when Starlette latin-1-encodes the header (500 on
    # any non-latin-1 employee name). re.ASCII restricts \w to [A-Za-z0-9_], always latin-1 safe.
    safe_name = re.sub(r"[^\w.\-]", "_", emp_name, flags=re.ASCII) or "employee"
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="paystub_{safe_name}.pdf"'},
    )


# ---------------------------------------------------------------------------
# DASH-05: POST /demo/send-test — fire demo fixture with FRESH Message-ID per click
# ---------------------------------------------------------------------------


@app.post("/runs/{run_id}/simulate-reply")
def simulate_reply(
    run_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    reply_body: str = Form(default=""),
) -> RedirectResponse:
    """Simulate a client email reply to complete an awaiting_reply run in the demo.

    DEMO-ONLY affordance (Phase 6 replaces this with real inbound webhook traffic).

    Constructs a synthetic InboundEmail that mirrors the RFC threading a real client
    reply would carry (same In-Reply-To / References as the clarification outbound,
    same from_addr as the original inbound sender), then routes it through the REAL
    _route_reply path — no logic duplication, no guard bypass.

    The FIX-5 spoof guard passes because from_addr is taken from the run's own
    source inbound email (the original business contact email), which is the same
    address find_business_by_sender resolves.

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
    except Exception:
        raise HTTPException(status_code=404, detail="Run not found")
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

    # Load the run's source inbound email to get the original sender address.
    # Using from_addr from the original inbound ensures the FIX-5 spoof guard passes
    # (find_business_by_sender will resolve this address to the same business).
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
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
    }

    # Route through the SAME entry as the real webhook uses.
    email = gateway.parse_inbound(synthetic_payload)
    cleaned = clean_body(email.body_text)

    # Insert the synthetic inbound row (mirrors the real webhook path; the
    # uq_message_id unique constraint dedupes if somehow the same synthetic ID
    # appears twice — that is not possible with uuid4 but is handled gracefully).
    try:
        # IN-01 (REVIEW-2): link the synthetic reply row to its run for a complete audit
        # trail. Routing/resume keys off the RFC header chain (not this column), so this
        # is purely for traceability — a join-based audit query now sees the reply.
        repo.insert_inbound_email(
            message_id=email.message_id,
            in_reply_to=email.in_reply_to,
            references_header=email.references_header,
            subject=email.subject,
            from_addr=email.from_addr,
            to_addr=email.to_addr,
            body_text=cleaned,
            run_id=run_id,
        )
    except Exception:
        logger.debug("simulate-reply: insert_inbound_email failed for run %s", run_id)
        return RedirectResponse(url=f"/runs/{run_id}", status_code=303)

    # Hand off to the real reply-routing path — all guards (FIX-5 spoof check,
    # late-reply detection) execute exactly as they would for a real inbound.
    # WR-01 (REVIEW-2): _route_reply returns a JSONResponse when it did NOT resume
    # (spoof-mismatch or late-reply) and None when it scheduled the resume. Surface the
    # non-resume outcome instead of unconditionally logging success.
    handled = _route_reply(email, cleaned, background_tasks)
    if handled is not None:
        logger.warning(
            "simulate-reply: reply NOT resumed for run %s (route returned a response — "
            "spoof-mismatch or late-reply); run stays at awaiting_reply",
            run_id,
        )
    else:
        logger.info(
            "simulate-reply: synthetic reply submitted for run %s (demo-only)", run_id
        )
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@app.post("/demo/send-test")
def demo_send_test(
    background_tasks: BackgroundTasks,
    fixture_key: str = Form(default=_DEMO_FIXTURE_DEFAULT_KEY),
) -> RedirectResponse:
    """DASH-05: Fire a curated demo fixture through the pipeline with a fresh Message-ID.

    UAT #6: accepts an optional fixture_key form field selecting among the
    _DEMO_FIXTURES allowlist. Any unknown / missing key falls back to the default
    (Coastal Cleaning exact match). The client NEVER supplies a file path — the
    server resolves the path from the allowlist (T-05-22 SSRF guard).

    The fixture's original Message-ID is OVERRIDDEN with a fresh uuid4-based
    synthetic ID per click. The uq_message_id UNIQUE constraint on email_messages
    would silently drop a second click if the same ID is reused (MEDIUM finding fix,
    T-05-22b). Each click creates a distinct run visible in the runs list.
    """
    # Server-side allowlist validation — never trust the client-supplied path.
    if fixture_key not in _DEMO_FIXTURES:
        fixture_key = _DEMO_FIXTURE_DEFAULT_KEY
    fixture_meta = _DEMO_FIXTURES[fixture_key]
    fixture_path = Path(fixture_meta["path"])

    if fixture_path.exists():
        fixture_data = json.loads(fixture_path.read_text())
    else:
        # Fallback: build a minimal fixture from the seed business contact_email
        fixture_data = {
            "message_id": "",  # will be overridden below
            "in_reply_to": None,
            "references_header": None,
            "subject": "Demo payroll run",
            "from_addr": "payroll@coastalcleaning.example",
            "to_addr": "agent@payroll-agent.local",
            "body_text": "Maria Chen 40 regular hours. Thanks!",
        }

    # MEDIUM finding fix: mint a fresh synthetic Message-ID per click so the
    # uq_message_id UNIQUE constraint cannot silently drop a repeat click.
    fresh_message_id = f"<{uuid.uuid4()}@demo.payroll-agent.local>"
    fixture_data["message_id"] = fresh_message_id

    # HIGH-1 (R4): resolve from_addr from THIS fixture's business's seed contact via
    # _SEED_CONTACTS constant. Seed .example contacts are permanently stable (06-08
    # HIGH-2 never mutates businesses.contact_email), so this constant is always
    # correct. Each fixture routes to its own business with zero DB coupling and
    # independent of demo_sender_bindings state.
    business_name = fixture_meta.get("business_name")
    from_addr = _SEED_CONTACTS.get(business_name) if business_name else None
    if from_addr is None:
        # Fallback for misconfigured fixture or tests: use the fixture file's from_addr
        from_addr = fixture_data.get("from_addr", "payroll@coastalcleaning.example")

    # Build the InboundEmail payload from the fixture, stripping non-model keys.
    # InboundEmail requires: id, message_id, in_reply_to, references_header,
    # subject, from_addr, to_addr, body_text, created_at.
    inbound_payload = {
        "id": fixture_data.get("id") or str(uuid.uuid4()),
        "message_id": fixture_data["message_id"],
        "in_reply_to": fixture_data.get("in_reply_to"),
        "references_header": fixture_data.get("references_header"),
        "subject": fixture_data.get("subject") or "Demo payroll run",
        "from_addr": from_addr,
        "to_addr": fixture_data.get("to_addr", "agent@payroll-agent.local"),
        "body_text": fixture_data.get("body_text", ""),
        "created_at": fixture_data.get("created_at") or datetime.now(tz=timezone.utc).isoformat(),
    }
    inbound_email = gateway.parse_inbound(inbound_payload)

    cleaned = clean_body(inbound_email.body_text)

    try:
        email_id, inserted = repo.insert_inbound_email(
            message_id=inbound_email.message_id,
            in_reply_to=inbound_email.in_reply_to,
            references_header=inbound_email.references_header,
            subject=inbound_email.subject,
            from_addr=inbound_email.from_addr,
            to_addr=inbound_email.to_addr,
            body_text=cleaned,
            run_id=None,
        )

        if not inserted:
            # Collision is extremely unlikely (uuid4 IDs) but if it happens, redirect anyway.
            logger.warning("demo send-test: unexpected duplicate message_id %s", fresh_message_id)
            return RedirectResponse(url="/runs", status_code=303)

        business_id = repo.find_business_by_sender(inbound_email.from_addr)
        if business_id is None:
            logger.warning("demo send-test: unknown sender %s", inbound_email.from_addr)
            return RedirectResponse(url="/runs", status_code=303)

        run_id = repo.create_run(business_id=business_id, source_email_id=email_id)
        background_tasks.add_task(_run_pipeline, run_id)
        # UAT #2 fix: redirect to /runs queue so the operator can watch the
        # new run appear and advance through statuses (CX improvement).
        # Each click still creates a distinct run (fresh Message-ID per click).
        return RedirectResponse(url="/runs", status_code=303)
    except Exception:
        # DB unavailable: still redirect to /runs rather than returning 500.
        # The run will not be created but the operator can see the (empty) list.
        logger.debug("demo send-test: DB unavailable — redirecting without creating run")

    # Fallback (duplicate Message-ID, unknown sender, or DB error): no specific run
    # to show — land on the triage queue.
    return RedirectResponse(url="/runs", status_code=303)
