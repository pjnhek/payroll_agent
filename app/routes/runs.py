"""Everything under /runs* — the operator gate + run detail.

list, detail, status, approve, reject, resolve, retrigger, pdf, simulate-reply,
plus the runs_list stranded-sweep block.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from io import BytesIO
from typing import Any

import psycopg
from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response, StreamingResponse

from app.db import repo
from app.email import gateway
from app.email.clean import clean_body
from app.models.job import JobKind
from app.models.roster import Employee, Roster
from app.models.status import RunStatus
from app.pipeline import delivery
from app.queue import wake
from app.routes import pipeline_glue
from app.routes.demo import DEMO_FIXTURES
from app.routes.templating import badge_class_filter, badge_label_filter, templates

logger = logging.getLogger("payroll_agent.webhook")

router = APIRouter()

# Staleness threshold for stale in-flight state recovery. SHARED by BOTH retrigger()'s
# stale-in-flight claim AND runs_list()'s recovery sweep (repo.sweep_stranded_runs) —
# ONE constant, two use sites. Keep it that way unless tracing shows the two sites
# genuinely need different values; two drifting thresholds would let a run be swept by
# one path while the other still considers it live.
#
# The value must sit safely ABOVE the worst-case gap between two consecutive DB writes
# on the longest real path, or the sweep will yank a run that is merely slow, not stuck
# — restarting a payroll that is mid-flight. It is derived, not guessed:
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
# older than this may be claimed/swept for a fresh start; fresh in-flight runs are
# never force-restarted.
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


@router.post("/runs/{run_id}/approve")
def approve(
    run_id: uuid.UUID,
    background_tasks: BackgroundTasks,
) -> RedirectResponse:
    """The single human gate: CAS claim (AWAITING_APPROVAL → APPROVED), then deliver.

    Race-safety: claim_status is an atomic compare-and-set. A second concurrent approval
    (double-click, two operator tabs) LOSES the claim and 303-redirects without running
    delivery again — otherwise the client would receive the payroll confirmation twice.

    Delivery is synchronous and bounded by the compose_confirmation timeout. On a
    delivery exception the run is recorded as ERROR: APPROVED is deliberately NOT a
    terminal status, precisely so record_run_error can advance it and the operator can
    retrigger rather than the run wedging at APPROVED with no confirmation sent.

    Error logging is PII-safe: error_reason is type(exc).__name__ ONLY.
    """
    claimed = repo.claim_status(run_id, RunStatus.AWAITING_APPROVAL, RunStatus.APPROVED)
    if claimed:
        try:
            # load_run is INSIDE the error boundary on purpose. A transient DB failure
            # during the load (e.g. a pooler blip) must route to ERROR + error_reason
            # like any other delivery failure — not leave the run silently stuck at
            # APPROVED behind a raw 500 (INGEST-05: "nothing silently hangs"). APPROVED
            # is non-terminal, so record_run_error can advance it to ERROR and the
            # operator can retrigger.
            run = repo.load_run(run_id)
            if run is None:
                raise TypeError("run not found")
            delivery.deliver(run_id, run)
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
    run_id: uuid.UUID, request: Request, background_tasks: BackgroundTasks
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

    On a valid POST: persist a fresh immutable operator-resolution generation containing
    the complete validated mapping. In that same transaction, each remember-checked
    token gets a bound alias candidate for the existing approval-gate learning path.
    Checkbox OFF means override-only — nothing is learned, but the token remains in the
    complete durable mapping.

    This route does NOT claim NEEDS_OPERATOR -> EXTRACTING itself. After the transaction
    commits, it schedules operator-resume with run_id plus operator_resolution_id only,
    and resume_pipeline's own
    claim_status(NEEDS_OPERATOR -> EXTRACTING) CAS is the SOLE claim in the path —
    mirroring the webhook's reply-resume path, which likewise never pre-claims. A
    route-level pre-claim races resume_pipeline's own claim and always loses, which
    strands the run in EXTRACTING forever; a concurrent double-submit or stale reload is
    instead absorbed by resume_pipeline's existing "duplicate resolve dropped" no-op (a
    failed claim there simply returns early).

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
    remember_tokens: set[str] = set()
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
        if form.get(f"remember_{i}") is not None:
            remember_tokens.add(token)

    operator_resolution_id = uuid.uuid4()
    with repo.get_connection() as conn, conn.transaction():
        # Re-check the authoritative generation inside the caller-owned transaction.
        # A stale tab that raced another operator action must create neither a mapping,
        # alias-learning state, nor process-local work.
        conn.execute(
            "SELECT id FROM payroll_runs WHERE id = %s FOR UPDATE",
            (str(run_id),),
        )
        current = repo.load_run(run_id, conn=conn)
        current_decision = (current or {}).get("decision") or {}
        if (
            current is None
            or current.get("status") != RunStatus.NEEDS_OPERATOR.value
            or str(current.get("business_id")) != str(run.get("business_id"))
            or current_decision.get("unresolved_names") != unresolved_names
        ):
            return RedirectResponse(url=f"/runs/{run_id}", status_code=303)

        # The immutable mapping is the COMPLETE money-moving authority. Optional
        # alias_candidates is partial learning intent and can never substitute for it.
        # Both writes join this transaction so persistence is all-or-nothing.
        repo.create_operator_resume_resolution(
            run_id,
            operator_resolution_id,
            overrides,
            conn=conn,
        )
        if remember_tokens:
            existing_candidates = current.get("alias_candidates") or {}
            updated_candidates = dict(existing_candidates)
            for token in remember_tokens:
                employee_id = overrides[token]
                updated_candidates[token] = {
                    "suggested": employee_id,
                    "bound": employee_id,
                }
            repo.set_alias_candidates(run_id, updated_candidates, conn=conn)

    # The authoritative generation is committed before a worker can observe its id.
    # No route-level pre-claim: resume_pipeline remains the sole owner of the forward
    # NEEDS_OPERATOR -> EXTRACTING transition for this first attempt.
    background_tasks.add_task(
        pipeline_glue.operator_resume_bg, run_id, operator_resolution_id
    )
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


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
    # This scope is FOUR statuses, including SENT — deliberately DIVERGENT
    # from repo.sweep_stranded_runs's scope (EXACTLY THREE:
    # received/extracting/computed). Sharing ONE threshold VALUE
    # (STALE_THRESHOLD_SECONDS) does NOT mean sharing one scope LIST: the two
    # lists diverge by design and must NOT be converged. A SENT run has already
    # durably committed the provider-send evidence, so it belongs to retrigger's
    # operator-initiated re-run path — safe only because delivery's already-sent
    # idempotency guard suppresses a second confirmation. It does NOT belong to
    # the sweep, whose scope is "the background task died before persisting
    # anything durable". Adding SENT to the sweep would auto-re-run runs that
    # already emailed the client. Do NOT "fix" this into parity.
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
        # run_pipeline_bg. A "lost job" for exactly the run this retrigger was meant to
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
    CAS below or the stale in-flight branch — is dispatched to run_pipeline_bg, NOT
    resume_pipeline_bg, because retrigger cannot tell that the stranded run was entered
    via a reply. Runs are never auto-restarted; the operator's retrigger IS the accepted
    recovery mechanism, and making retrigger reply-aware is new state-machine capability,
    deliberately out of scope. Consequence: the retriggered run restarts cleanly from the
    ORIGINAL inbound email, and the in-flight reply context it was processing when it
    stranded is lost. The operator retains full visibility (the run reaches ERROR and is
    diagnosable) and can re-send the clarification context as a fresh email if the
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
def runs_list(request: Request, background_tasks: BackgroundTasks) -> Response:
    """DASH-01: Render the reverse-chronological runs list with status badges.

    Sweeps stranded in-flight runs to ERROR BEFORE loading the list, so a run whose
    background task died mid-flight becomes visible as a diagnosable ERROR on the very
    NEXT dashboard load. This route carries the sweep because GET /runs is the one HTTP
    entry point Render's free tier guarantees will be hit periodically — there is no
    cron. The sweep call is wrapped in the SAME swallow-on-DB-unavailable try/except the
    route already uses for load_all_runs: a sweep failure must never 500 the dashboard.

    The same try-block also re-schedules resume_pipeline_bg for every stale, unconsumed
    reply against an awaiting_reply run (repo.find_stranded_unconsumed_replies) — the
    recovery route for a redelivery that never arrived. Scope is EXACTLY
    awaiting_reply + unconsumed + stale, which structurally EXCLUDES needs_operator runs:
    those exit only via /resolve or reject, never via an autonomous re-schedule, because
    an escalated run is waiting on a human judgment that no sweep can supply. The CAS
    claim inside resume_pipeline absorbs any double-schedule.
    """
    try:
        repo.sweep_stranded_runs(STALE_THRESHOLD_SECONDS)
        for reply_row in repo.find_stranded_unconsumed_replies(STALE_THRESHOLD_SECONDS):
            # Re-assert the sender revalidation before dispatching this stranded-sweep
            # re-schedule. A spoofed reply that already failed the sender check on
            # first delivery is left linked+unconsumed — exactly what this sweep picks
            # up — so without the re-check a mere dashboard load would auto-resume it.
            # load_run is needed anyway to get business_id for the check.
            candidate_run = repo.load_run(reply_row["run_id"])
            if candidate_run is not None and pipeline_glue.reply_sender_ok(
                reply_row, candidate_run
            ):
                background_tasks.add_task(
                    pipeline_glue.resume_pipeline_bg,
                    reply_row["run_id"],
                    pipeline_glue.row_to_inbound(reply_row),
                )
            elif candidate_run is not None:
                logger.warning(
                    "run_id=%s stranded-sweep resume blocked — sender mismatch persists",
                    reply_row["run_id"],
                )
    except Exception:
        logger.debug("sweep_stranded_runs unavailable — skipping this page load")
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
            "demo_fixtures": DEMO_FIXTURES,
            "in_flight_statuses": list(IN_FLIGHT_STATUSES),
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
    status = run.get("status", "")
    return JSONResponse(
        content={
            "status": status,
            "badge_class": badge_class_filter(status),
            "badge_label": badge_label_filter(status),
        }
    )


@router.get("/runs/{run_id}")
def run_detail(request: Request, run_id: uuid.UUID) -> Response:
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
    if run.get("status") == RunStatus.NEEDS_OPERATOR.value:
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
            "roster_employees": roster_employees,
            "unresolved_suggestions": unresolved_suggestions,
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
    background_tasks: BackgroundTasks,
    reply_body: str = Form(default=""),
) -> RedirectResponse:
    """Simulate a client email reply to complete an awaiting_reply run in the demo.

    DEMO-ONLY affordance; in production a real inbound webhook carries the reply.

    Constructs a synthetic InboundEmail that mirrors the RFC threading a real client
    reply would carry (same In-Reply-To / References as the clarification outbound,
    same from_addr as the original inbound sender), then routes it through the REAL
    pipeline_glue.route_reply path — no logic duplication, no guard bypass.

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

    # Insert the synthetic inbound row (mirrors the real webhook path; the
    # uq_message_id unique constraint dedupes if somehow the same synthetic ID
    # appears twice — that is not possible with uuid4 but is handled gracefully).
    try:
        # Link the synthetic reply row to its run for a complete audit trail. Routing
        # and resume key off the RFC header chain, not this column, so the link is
        # purely for traceability — it lets a join-based audit query see the reply.
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

    # Hand off to the real reply-routing path — all guards (the sender spoof check,
    # late-reply detection) execute exactly as they would for a real inbound.
    # Branch on route_reply's BODY, not on None: it returns a JSONResponse on EVERY
    # header match — {"status": "resumed"} when it scheduled the background resume, and
    # {"status": "sender_mismatch"} / {"status": "late_reply"} when a guard stopped it —
    # and None ONLY when the header matched nothing at all. A bare None-check reads a
    # successful resume as a failure and logs "NOT resumed" on every happy path.
    handled = pipeline_glue.route_reply(email, cleaned, background_tasks)
    outcome = (
        json.loads(bytes(handled.body))["status"]
        if handled is not None
        else "no_header_match"
    )
    if outcome == "resumed":
        logger.info(
            "simulate-reply: resume scheduled for run %s (demo-only)", run_id
        )
    else:
        logger.warning(
            "simulate-reply: reply NOT resumed for run %s (outcome=%s); "
            "run stays at awaiting_reply",
            run_id,
            outcome,
        )
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
