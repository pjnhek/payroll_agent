"""Everything under /runs* — the operator gate + run detail (D-06).

Carved out of app/main.py (Phase 13 Plan 03): list, detail, status, approve,
reject, resolve, retrigger, pdf, simulate-reply, plus the runs_list
stranded-sweep block.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import UTC, datetime, timedelta
from io import BytesIO

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse

from app.db import repo
from app.email import gateway
from app.email.clean import clean_body
from app.models.status import RunStatus
from app.pipeline import delivery
from app.routes import pipeline_glue
from app.routes.demo import DEMO_FIXTURES
from app.routes.templating import badge_class_filter, badge_label_filter, templates

logger = logging.getLogger("payroll_agent.webhook")

router = APIRouter()

# Staleness threshold for stale in-flight state recovery (finding #6, D-13b extension;
# D-9-13/D-9-10/11/12, 09-03/09-04). SHARED by BOTH retrigger()'s stale-in-flight claim
# AND runs_list()'s recovery sweep (repo.sweep_stranded_runs) — ONE constant, two
# use sites (D-9-13: "keep ONE shared constant unless tracing shows they genuinely
# need different values" — no such need was found).
#
# 09-04 (closing Codex HIGH-3, both rounds, AND RESEARCH.md Assumption A1): the
# previous (09-03) 65-minute value was DELIBERATELY CONSERVATIVE, documenting the
# UNTIGHTENED worst case pending this plan. This plan closes every gap that was
# counted against that conservative figure, so the threshold is now re-derived
# against the FULLY-tightened, CORRECTLY-COUNTED ceiling:
#   (a) call_structured (app/llm/client.py) — used for BOTH extraction AND the
#       clarification suggestion (app/pipeline/suggest.py:81) — now passes an
#       explicit timeout=_STRUCTURED_TIMEOUT_S (45.0s) AND max_retries=0 to its
#       OpenAI(...) client construction, so the library's own retry layer can no
#       longer compound with the app's own `for attempt in (1, 2):` reflective
#       retry. Ceiling per call: _STRUCTURED_TIMEOUT_S x 2 app-attempts = 90s.
#   (b) resume Round-2's back-to-back double extraction (orchestrator.py:377,380 —
#       raw_reply_extracted = extract(inbound, ...) THEN raw_extracted =
#       extract(combined_email, ...), verified live) — TWO calls through (a) before
#       the next DB write: _STRUCTURED_TIMEOUT_S x 2 app-attempts x 2 = 180s (3 min).
#   (c) call_text (app/llm/client.py) — ALL callers, including
#       compose_clarification (app/pipeline/compose_email.py) — now gets an
#       UNCONDITIONAL max_retries=0 on its own client construction (closing the
#       Codex round-2 STILL-OPEN finding that call_text has no app-level retry
#       loop, so the library's own max_retries=2 was the sole, previously-uncounted
#       retry layer). compose_clarification's own call now ALSO passes an explicit
#       timeout_s=_CLARIFICATION_TIMEOUT_S (30.0s, app/pipeline/compose_email.py).
#       Ceiling: _CLARIFICATION_TIMEOUT_S x 1 = 30s.
# (b) and (c) are SEQUENTIAL on the clarify branch (extraction happens, THEN,
# separately, a clarification draft may be composed) — not concurrent — so they
# SUM, not multiply: 180s + 30s = 210s (3.5 min) is the full, correctly-derived
# worst-case gap between two consecutive DB writes on the longest real path.
# STALE_THRESHOLD is tightened to 15 minutes — comfortably (~4x) above the 3.5-min
# ceiling, while remaining far short of the old 65-minute value now that the true
# ceiling is known and bounded by construction, not merely assumed. A run in a
# recoverable in-flight state (RECEIVED/EXTRACTING/COMPUTED, plus SENT for
# retrigger only — see the scope-divergence comment on retrigger's stale_statuses
# below) whose updated_at is older than this threshold may be claimed/swept for a
# fresh start; fresh in-flight runs are never force-restarted.
STALE_THRESHOLD = timedelta(minutes=15)
STALE_THRESHOLD_SECONDS = int(STALE_THRESHOLD.total_seconds())

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


@router.post("/runs/{run_id}/approve")
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
    claimed = repo.claim_status(run_id, RunStatus.AWAITING_APPROVAL, RunStatus.APPROVED)
    if claimed:
        try:
            # REVIEW-4 WR-01: load_run is INSIDE the D-13b boundary. A transient DB failure
            # during the load (e.g. pooler blip) must route to ERROR + error_reason like any
            # other delivery failure — not leave the run silently stuck at APPROVED with a
            # raw 500 (INGEST-05 "nothing silently hangs"). APPROVED is non-terminal, so
            # record_run_error can advance it to ERROR and the operator can retrigger.
            run = repo.load_run(run_id)
            delivery.deliver(run_id, run)
        except Exception as exc:  # noqa: BLE001 — D-13b error boundary
            # PII-safe: type only — str(exc) may echo model output, submitted names,
            # or raw email content (D-A1-03). run_id is the correlation key for debug.
            logger.warning("delivery of run %s failed: %s", run_id, type(exc).__name__)
            # OPS2-01 + WR-04 (phase-8 review): approve() never loads a roster itself
            # (D-8-01b — the error path must never LOAD one), but _deliver stashes the
            # roster it already loaded for PDF/compose interpolation on any exception
            # raised past that point (exc.payroll_roster). Forward it so _scrub can
            # redact employee names from the delivery error_detail — the boundary
            # where names are MOST likely to appear in exception text. Failures
            # before _deliver's roster load carry no attribute → None (locked design).
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
    """Hardened reject: CAS claim (AWAITING_APPROVAL OR NEEDS_OPERATOR → REJECTED) → 303.

    claim_status is atomic — a concurrent rejection or approval sees False and no-ops
    (D-12, FOUND-04). Always 303 to run detail regardless of claim outcome.

    D-11-08 extension: needs_operator is also a valid reject source (one of the
    escalation's two exits — resolve+resume, or reject). The `or` short-circuits:
    if the first CAS wins (run was awaiting_approval), the second is skipped; if
    it loses, the second CAS attempts the needs_operator claim. At most one of
    the two can ever succeed for a given run (they target mutually exclusive
    prior statuses), so there is no risk of a double-claim race between them.
    """
    repo.claim_status(
        run_id, RunStatus.AWAITING_APPROVAL, RunStatus.REJECTED
    ) or repo.claim_status(run_id, RunStatus.NEEDS_OPERATOR, RunStatus.REJECTED)
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@router.post("/runs/{run_id}/resolve")
async def resolve(
    run_id: uuid.UUID, request: Request, background_tasks: BackgroundTasks
) -> RedirectResponse:
    """Operator resolve+resume for a needs_operator run (D-11-08, D-11-16, Security V4).

    Form shape (per unresolved name/token, dynamic field names keyed by the
    LOOP INDEX over decision.unresolved_names — never the raw token text, so a
    field name can never collide with an ill-formed/injected token string):
      - employee_id_{i}: the operator-selected roster employee id for token i
      - remember_{i}: checkbox, present (any value) = ON, absent = OFF (D-11-16
        default-checked in the template; unchecked posts nothing for that key)

    Security V4 (server-side roster validation): every posted employee_id MUST
    belong to `load_roster_for_business(run.business_id)` — never trust the
    dropdown. ANY invalid/unknown/cross-business id rejects the WHOLE POST (no
    partial apply, no state change) — the run stays needs_operator and the
    operator sees the same page again (a malformed/tampered request is simply
    a no-op, not a partial misroute).

    On a valid POST: apply the mapping as the per-run override (drives
    resolution via reconcile_names(overrides=...) inside resume_pipeline); for
    each remember-checked token, ALSO pre-set the candidate's `bound` field so
    the existing single-human-gate write path (_write_aliases_if_safe, called
    from _deliver at approval) persists it — checkbox OFF means override-only,
    nothing learned (D-11-16). The route does NOT claim NEEDS_OPERATOR ->
    EXTRACTING itself (GAP-1/CR-1 fix, 11-REVIEW.md): it unconditionally
    schedules the operator-resume in the background, and resume_pipeline's own
    claim_status(NEEDS_OPERATOR -> EXTRACTING) CAS is the SOLE claim in this
    path — exactly mirroring how the webhook's reply-resume path never
    pre-claims either. A concurrent double-submit or a stale reload is
    absorbed by resume_pipeline's existing "late/duplicate reply/resolve
    dropped" no-op (a failed claim there just returns early), not by a
    route-level pre-check — the prior pre-claim raced resume_pipeline's own
    claim and always lost, silently stranding the run in EXTRACTING forever.
    Always 303 — post-commit scheduling only (no LLM/provider call in this
    request's synchronous path).
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

    # Security V4: validate EVERY posted employee_id against the run's OWN
    # business roster before applying anything. Reject the WHOLE POST (no
    # partial apply) on any invalid/unknown/cross-business id.
    overrides: dict[str, str] = {}
    remember_tokens: set[str] = set()
    for i, token in enumerate(unresolved_names):
        posted_id = form.get(f"employee_id_{i}")
        if posted_id is None or str(posted_id) not in roster_ids:
            logger.warning(
                "resolve: rejected whole POST for run %s — invalid/missing "
                "employee_id at index %d (Security V4)",
                run_id,
                i,
            )
            return RedirectResponse(url=f"/runs/{run_id}", status_code=303)
        overrides[token] = str(posted_id)
        if form.get(f"remember_{i}") is not None:
            remember_tokens.add(token)

    # Apply the validated mapping as the per-run override (drives resolution
    # deterministically before reconcile_names's exact/alias tiers) AND, for
    # each remember-checked token, pre-set `bound` on the candidate so the
    # existing single-human-gate write path persists the alias at approval
    # (D-11-16: checkbox OFF = override only, nothing learned).
    if remember_tokens:
        existing_candidates = run.get("alias_candidates") or {}
        updated_candidates = dict(existing_candidates)
        for token in remember_tokens:
            employee_id = overrides[token]
            updated_candidates[token] = {"suggested": employee_id, "bound": employee_id}
        repo.set_alias_candidates(run_id, updated_candidates)

    # GAP-1/CR-1 fix: no route-level pre-claim. resume_pipeline (invoked via
    # operator_resume_bg) performs its OWN claim_status(NEEDS_OPERATOR ->
    # EXTRACTING) CAS exactly once — this is now the ONLY claim in the entire
    # path. Unconditionally schedule; resume_pipeline's claim is what actually
    # gates whether the run advances.
    background_tasks.add_task(pipeline_glue.operator_resume_bg, run_id, overrides)
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@router.post("/runs/{run_id}/retrigger")
def retrigger(
    run_id: uuid.UUID,
    background_tasks: BackgroundTasks,
) -> RedirectResponse:
    """Retrigger a run from ERROR, APPROVED, or stale in-flight states (INGEST-05).

    D-13b extension (finding #6): the retrigger path is extended to also claim from
    stale RECEIVED/EXTRACTING/COMPUTED/SENT states — a worker that died mid-run
    leaves the run stuck with no recovery UI otherwise.

    Stale guard: in-flight claims require updated_at older than STALE_THRESHOLD
    (09-03: shared with runs_list()'s recovery sweep — see the constant's own
    comment for the honest current worst-case rationale). A freshly-started
    in-flight run is never force-restarted.

    09-03 (Codex MEDIUM, reply-context-loss on retrigger — accepted, documented):
    a stranded run that entered via a clarification REPLY (i.e. one with non-empty
    clarified_fields or a pre_clarify_extracted snapshot), once claimed here
    (whether by the ERROR/APPROVED CAS above or the stale in-flight branch below),
    is dispatched to run_pipeline_bg — NOT resume_pipeline_bg — because retrigger
    has no way to know a stranded run was originally entered via a reply. Per D-9-10
    ("never auto-restart" — the operator retrigger IS the accepted recovery
    mechanism), this is NOT changed here: adding reply-aware retrigger dispatch is
    new state-machine capability, out of scope (deferred alongside 260623-08, see
    09-CONTEXT.md Deferred Ideas). The retriggered run restarts cleanly from the
    ORIGINAL inbound email; the in-flight reply context that was being processed
    when it stranded is lost. This is a known, accepted limitation — the operator
    retains full visibility (the run reaches ERROR, diagnosable) and can manually
    re-send the clarification's context via a fresh email if the retriggered run's
    result looks wrong.

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
                and datetime.now(tz=UTC) - updated_at > STALE_THRESHOLD
            )
            # 09-03 (checker WARNING 3, prior review round): this scope is FOUR
            # statuses, including SENT — deliberately DIVERGENT from
            # repo.sweep_stranded_runs's D-9-12 scope (EXACTLY THREE:
            # received/extracting/computed). "Keep ONE shared constant" (the
            # THRESHOLD VALUE, STALE_THRESHOLD_SECONDS) does NOT mean "keep ONE
            # shared scope LIST" — the two lists structurally diverge by design
            # and must NOT be made to converge: a SENT run has already durably
            # committed the provider-send evidence (D-13c) and belongs to
            # retrigger's own re-run path (safe via _deliver's already-sent
            # idempotency guard), not the sweep's "background task died before
            # persisting anything durable" scope. Do NOT "fix" this into parity.
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
        # WR-06 (D-11-04, Plan 11-05): "context lost means ALL of it" — clear
        # clarified_fields + pre_clarify_extracted + the round counter +
        # suggestion/candidate state AFTER the winning claim (both branches
        # above converge here) and BEFORE run_pipeline_bg is scheduled, so
        # is_round_2 = bool(clarified) sees a genuinely fresh run and no
        # provenance badge can outlive the data that produced it.
        # clear_reply_context opens its own committed transaction (conn=None)
        # — a durable unit that does NOT span the LLM-heavy run_pipeline_bg
        # background task (Pitfall #8).
        repo.clear_reply_context(run_id)
        logger.info("run_id=%s reply context cleared on retrigger (WR-06)", run_id)
        background_tasks.add_task(pipeline_glue.run_pipeline_bg, run_id)
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
# DASH-01: GET /runs — operator triage queue
# ---------------------------------------------------------------------------


@router.get("/runs")
def runs_list(request: Request, background_tasks: BackgroundTasks):
    """DASH-01: Render the reverse-chronological runs list with status badges.

    D-9-10/11 (09-03): sweeps stranded in-flight runs to ERROR BEFORE loading the
    list, so a run whose background task died mid-flight becomes visible as a
    diagnosable ERROR on the very NEXT dashboard load — GET /runs is the one HTTP
    entry point Render's free tier guarantees will be hit periodically. The sweep
    call is wrapped in the SAME try/except-swallow-on-DB-unavailable style the
    route already uses for load_all_runs — a sweep failure must never 500 the
    dashboard.

    D-11-05 (Plan 11-05): beside the sweep, this same try-block also re-schedules
    resume_pipeline_bg for every stale, unconsumed reply against an awaiting_reply
    run (repo.find_stranded_unconsumed_replies) — the recovery route for a
    redelivery that never arrived. Scope is EXACTLY awaiting_reply + unconsumed +
    stale, which structurally EXCLUDES needs_operator runs (D-11-06: those exit
    only via /resolve or reject, never an autonomous re-schedule). The CAS claim
    inside resume_pipeline absorbs any double-schedule; a failure here must never
    500 the dashboard, same swallow-on-failure style as the sweep.
    """
    try:
        repo.sweep_stranded_runs(STALE_THRESHOLD_SECONDS)
        for reply_row in repo.find_stranded_unconsumed_replies(STALE_THRESHOLD_SECONDS):
            # GAP-5/CR-5: re-assert FIX-5 before dispatching this stranded-sweep
            # re-schedule — a reply that already failed sender revalidation on
            # first delivery (left linked+unconsumed) must never be auto-
            # resumed by a later dashboard load either. load_run is needed
            # anyway to get business_id for the check.
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
                    "run_id=%s stranded-sweep resume blocked — sender mismatch "
                    "persists (GAP-5/CR-5 fix)",
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
    """Lightweight status poll endpoint for the vanilla-JS badge updater (UAT #3/#4).

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
def run_detail(request: Request, run_id: uuid.UUID):
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
    # D-11-08: for a needs_operator run, the template needs (a) the business's
    # roster employees to populate each unresolved name's dropdown and (b) the
    # persisted per-token suggestion (D-11-14 nested alias_candidates shape) to
    # pre-select the LLM's advisory guess. Both are best-effort — a load
    # failure degrades to an empty dropdown/no pre-selection rather than a
    # 500, matching every other try/except-debug block on this route.
    roster_employees: list = []
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


@router.post("/runs/{run_id}/simulate-reply")
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
    pipeline_glue.route_reply path — no logic duplication, no guard bypass.

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
        "created_at": datetime.now(tz=UTC).isoformat(),
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
    # WR-04 (Phase 13 review): route_reply returns a JSONResponse on EVERY
    # header match — {"status": "resumed"} when it scheduled the background
    # resume, {"status": "sender_mismatch"} / {"status": "late_reply"} when a
    # guard stopped it — and None ONLY when the header matched nothing (the
    # synthetic reply went nowhere). The previous None-check logged "NOT
    # resumed" on every successful resume; branch on the actual outcome.
    handled = pipeline_glue.route_reply(email, cleaned, background_tasks)
    outcome = json.loads(handled.body)["status"] if handled is not None else "no_header_match"
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
