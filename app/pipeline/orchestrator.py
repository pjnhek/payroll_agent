"""The run state machine (INGEST-04, D-A1-02/03). The plain-Python orchestrator.

run_pipeline(run_id) is the explicit state machine: it loads the run + roster, runs
the four PURE judgment stages in order, persists Extracted + Decision + per-name
reconciliation on EVERY run, then branches SOLELY on Decision.final_action. The
decision is computed deterministically by code (decide.py makes no model call and
reads no score, D-21-01/03; the thesis), so there is no separate advisory action to
diverge from. It is NOT LangGraph; Postgres status IS the durable checkpoint.

Persistence vs status (review FIX B): the persist_* helpers write DATA ONLY; the
orchestrator advances state by calling repo.set_status SEPARATELY (set_status is
the sole status writer). A clean run reaching awaiting_approval NEVER leaves
reconciliation NULL (D-A3-05).

Error-wrap (D-A1-03, FIX 7): the whole run is wrapped in try/except; any unhandled
stage exception routes through repo.record_run_error (which writes
payroll_runs.error_reason AND advances to ERROR via set_status), so a failure
reason is persisted, never lost — nothing silently hangs. PII-safe: the reason is
a stage/exception summary, not the raw email body (T-02-11).

FIX A: the code-owned run_id is passed into extract(..., run_id=run_id, ...) so the
resulting Extracted.run_id is the trusted run id — the model never supplies it.

CLAR-03 resume (Plan 04): resume_pipeline(run_id, inbound) re-enters at extraction
idempotently AND losslessly. It rebuilds the extraction CONTEXT from the ORIGINAL
cleaned inbound body (repo.load_source_email — already cleaned at ingest, FIX C)
combined with the clarification reply body (inbound.body_text), passes the run's
code-owned run_id into extract (FIX A), and OVERWRITES extracted_data wholesale
(persist_extracted is a single JSONB cell, never appended) + replaces line items by
run (DELETE-by-run then insert). Because the re-extraction sees the ORIGINAL body,
employees/hours not mentioned in the reply are RETAINED, not lost (FIX 4). The four
judgment stages are factored into a shared _run_stages() so run_pipeline and
resume_pipeline share the exact same gate path — the eval-reusable spine is DRY.
"""
from __future__ import annotations

import logging
import re
import uuid

from app.db import repo
from app.email import gateway
from app.models.contracts import InboundEmail
from app.models.status import RunStatus
from app.pipeline.calculate import calculate
from app.pipeline.compose_email import (
    clarification_subject,
    compose_clarification,
    compose_confirmation,
    confirmation_subject,
)
from app.pipeline.decide import decide
from app.pipeline.extract import extract
from app.pipeline.pdf import generate_paystub_pdf
from app.pipeline.reconcile_names import _safe_to_learn_alias, reconcile_names
from app.pipeline.suggest import suggest_employees
from app.pipeline.validate import validate

logger = logging.getLogger("payroll_agent.orchestrator")


def run_pipeline(run_id: uuid.UUID, *, llm=None) -> None:
    """Drive one run from received → awaiting_approval (or needs_clarification).

    `llm` is the client module the stages call; defaults to each stage's own
    bound client. Tests inject a mocked client by patching app.llm.client.OpenAI.
    """
    try:
        _run(run_id, llm=llm)
    except Exception as exc:  # noqa: BLE001 — the D-A1-03 error-wrap boundary
        # PII-safe summary: the exception TYPE only — str(exc) can echo prompt text,
        # submitted names, or model output, and this `reason` is BOTH logged AND
        # persisted to payroll_runs.error_reason (review fix). run_id is the
        # correlation key for deeper debugging.
        reason = type(exc).__name__
        logger.warning("run %s failed: %s", run_id, reason)
        repo.record_run_error(run_id, reason)


def _run(run_id: uuid.UUID, *, llm) -> None:
    run = repo.load_run(run_id)
    if run is None:
        raise ValueError(f"run {run_id} not found")

    email = repo.load_inbound_email(run_id)
    if email is None:
        raise ValueError(f"run {run_id} has no source email")
    roster = repo.load_roster_for_business(run["business_id"])

    repo.set_status(run_id, RunStatus.EXTRACTING)
    _run_stages(run_id, email, roster, llm=llm)


def resume_pipeline(run_id: uuid.UUID, inbound: InboundEmail, *, llm=None) -> None:
    """Re-enter a paused (awaiting_reply) run at extraction on a clarification reply.

    Idempotent AND lossless (CLAR-03, review FIX 4 + FIX C):
      - The extraction CONTEXT is rebuilt from the ORIGINAL cleaned inbound body
        (repo.load_source_email — persisted cleaned at ingest, NOT re-cleaned) +
        the clarification reply body (inbound.body_text). Because the original body
        is included, employees/hours not mentioned in the reply are RETAINED.
      - extract() is passed the run's CODE-OWNED run_id (FIX A); the model returns
        only an ExtractionPayload and extract stamps the trusted run_id.
      - persist_extracted OVERWRITES extracted_data wholesale (one JSONB cell, never
        appended); replace_line_items DELETE-by-run then insert. So a re-trigger is
        safe and a resume never accumulates stale data (RESEARCH Pattern 6 inv 1-2).

    The webhook is the sole caller and only invokes this after BOTH the header-chain
    match (awaiting_reply only) AND the reply-sender revalidation (FIX 5) have passed.

    Status gate (CR-02, D-12, FOUND-04): uses repo.claim_status(AWAITING_REPLY →
    EXTRACTING) — an atomic conditional UPDATE that closes the residual race from
    Phase 2's load-then-check+set pattern. The prior non-atomic pattern left a window
    where a second reply (or an operator approval) could arrive between the status load
    and the EXTRACTING write; claim_status's WHERE status=%s RETURNING id makes the
    check-and-transition atomic. The losing concurrent caller gets False and drops
    cleanly — no re-run, no ERROR route.
    """
    try:
        # Atomic compare-and-swap: claim the run from AWAITING_REPLY → EXTRACTING.
        # This closes CR-02's residual race (the prior load-then-check+set was non-atomic).
        # A duplicate or late reply sees claim=False and drops cleanly — no re-run,
        # no error. D-12, FOUND-04.
        claimed = repo.claim_status(run_id, RunStatus.AWAITING_REPLY, RunStatus.EXTRACTING)
        if not claimed:
            logger.info(
                "resume aborted: run %s claim failed — late/duplicate reply dropped (CR-02, D-12)",
                run_id,
            )
            return

        # load_run is still needed for business_id and other metadata.
        run = repo.load_run(run_id)
        if run is None:
            raise ValueError(f"run {run_id} not found after claim")
        roster = repo.load_roster_for_business(run["business_id"])

        # Rebuild the combined extraction context (original cleaned body + reply body).
        original_body = repo.load_source_email(run_id) or ""
        combined_email = _combined_context_email(inbound, original_body)

        # D-04 alias binding — PRE-VS-POST DIFF (NEW-2 fix).
        # Capture the pre-resume resolved employee_id set BEFORE _run_stages so we can
        # diff against the post-resume set to find the NEWLY-resolved employee.
        #
        # The "exactly one resolved match" assumption is wrong for realistic runs: a
        # multi-employee submission has MANY resolved employees after resume (the
        # already-resolved originals PLUS the newly-corrected one). Pre-vs-post diff
        # isolates exactly the one employee that changed from unresolved to resolved.
        #
        # Implementation:
        # STEP A: Load alias_candidates and pre-resume reconciliation BEFORE _run_stages.
        pre_run_data = repo.load_run(run_id)
        _pre_candidates = (pre_run_data.get("alias_candidates") or {}) if pre_run_data else {}
        _pre_reconciliation = (pre_run_data.get("reconciliation") or []) if pre_run_data else []
        # Build the pre-resume resolved employee_id set (strings for reliable comparison).
        # reconciliation is stored as JSONB list[dict] with key "matched_employee_id".
        _pre_resolved_ids: set[str] = set()
        if isinstance(_pre_reconciliation, list):
            for _m in _pre_reconciliation:
                if isinstance(_m, dict) and _m.get("matched_employee_id") is not None:
                    _pre_resolved_ids.add(str(_m["matched_employee_id"]))

        # STEP B: Run the four judgment stages as normal.
        _run_stages(run_id, combined_email, roster, llm=llm)

        # STEP C: Capture post-resume resolved employee_id set AFTER _run_stages.
        # _run_stages calls persist_reconciliation which overwrites the reconciliation
        # column — load_run here gets the freshly-written post-resume reconciliation.
        _none_tokens = [tok for tok, val in _pre_candidates.items() if val is None]
        if _none_tokens and _pre_candidates:
            from app.pipeline.reconcile_names import _norm

            post_run_data = repo.load_run(run_id)
            _post_reconciliation = (post_run_data.get("reconciliation") or []) if post_run_data else []
            _post_resolved_ids: set[str] = set()
            if isinstance(_post_reconciliation, list):
                for _m in _post_reconciliation:
                    if isinstance(_m, dict) and _m.get("matched_employee_id") is not None:
                        _post_resolved_ids.add(str(_m["matched_employee_id"]))

            # STEP D: Diff and bind — MISNAME GUARD (token-must-match-resolved-name).
            # The NEWLY-resolved employee is in post but NOT in pre.
            _newly_resolved_ids = _post_resolved_ids - _pre_resolved_ids
            # CRITICAL: count alone ("1 newly-resolved + 1 pending candidate") is NOT
            # sufficient to learn an alias. If the client MISNAMED someone — wrote
            # "Maria" but meant a different person, James — the reply corrects it to
            # "James Okafor", James newly-resolves, and the old count-only rule would
            # bind {"Maria": james.id}. "Maria" is NOT James's nickname; learning it
            # would silently misroute every future "Maria". A legitimate alias is one
            # the client RE-STATED (e.g. "Dave Reyez"), so its resolved entry's
            # submitted_name still matches the candidate token. Only bind when the
            # pending token actually appears as the submitted_name of a resolved,
            # newly-resolved entry — the token must be evidenced, not inferred.
            _bound = False
            if len(_none_tokens) == 1 and len(_newly_resolved_ids) == 1:
                _token = _none_tokens[0]
                _norm_token = _norm(_token)
                _newly_id = next(iter(_newly_resolved_ids))
                _token_resolved_to_newly = any(
                    isinstance(_m, dict)
                    and _m.get("resolved") is True
                    and str(_m.get("matched_employee_id")) == _newly_id
                    and _norm(_m.get("submitted_name") or "") == _norm_token
                    for _m in (_post_reconciliation if isinstance(_post_reconciliation, list) else [])
                )
                if _token_resolved_to_newly:
                    _updated_candidates = dict(_pre_candidates)
                    _updated_candidates[_token] = str(_newly_id)
                    repo.set_alias_candidates(run_id, _updated_candidates)
                    _bound = True
                    logger.info(
                        "alias candidate bound at resume: %r → %s "
                        "(token matched resolved submitted_name; pre-vs-post diff)",
                        _token,
                        _newly_id,
                    )
                else:
                    logger.info(
                        "alias binding skipped for run %s: candidate token %r was not "
                        "the submitted_name of the newly-resolved employee — likely a "
                        "misname/correction to a different person, not a nickname "
                        "(misname guard, NEW-2)",
                        run_id,
                        _token,
                    )
            if not _bound and not (len(_none_tokens) == 1 and len(_newly_resolved_ids) == 1):
                logger.info(
                    "alias binding skipped for run %s: %d newly-resolved, "
                    "%d pending candidates; expected 1 each (NEW-2)",
                    run_id,
                    len(_newly_resolved_ids),
                    len(_none_tokens),
                )
    except Exception as exc:  # noqa: BLE001 — the D-A1-03 error-wrap boundary (resume)
        # PII-safe: exception TYPE only — str(exc) can echo submitted names / prompt
        # text, and `reason` is logged AND persisted to error_reason (review fix —
        # the resume path was missed when run_pipeline was sanitized).
        reason = type(exc).__name__
        logger.warning("resume of run %s failed: %s", run_id, reason)
        repo.record_run_error(run_id, reason)


def _combined_context_email(reply: InboundEmail, original_body: str) -> InboundEmail:
    """Build the extraction-input InboundEmail combining the ORIGINAL body + the reply.

    The re-extraction must see BOTH the original hours (so a partial reply doesn't
    drop them) and the clarification answer. The combined body is clearly delimited
    so the model can read the original submission and the correction as one context.
    """
    combined_body = (
        "ORIGINAL PAYROLL EMAIL:\n"
        f"{original_body}\n\n"
        "CLARIFICATION REPLY FROM CLIENT:\n"
        f"{reply.body_text}"
    )
    return reply.model_copy(update={"body_text": combined_body})


def _run_stages(run_id, email, roster, *, llm) -> None:
    """The shared four-stage gate path: extract → reconcile → validate → decide →
    persist → branch. Used by BOTH run_pipeline (first run) and resume_pipeline (the
    CLAR-03 re-entry), so the eval-reusable spine and the gate stay DRY and identical.
    """
    # --- the four PURE judgment stages (DB-free; run_id is code-owned, FIX A) ---
    extract_kwargs = {"run_id": run_id}
    if llm is not None:
        extract_kwargs["llm"] = llm
    extracted = extract(email, roster, **extract_kwargs)

    submitted_names = [e.submitted_name for e in extracted.employees]
    matches = reconcile_names(submitted_names, roster)  # pure: no llm (D-21-01)
    issues = validate(extracted, roster, matches)

    decision = decide(extracted, matches, issues)  # pure: no llm, no score (D-21-01)

    # --- persist DATA on EVERY run BEFORE branching (D-A3-05); OVERWRITES on resume ---
    repo.persist_extracted(run_id, extracted)
    repo.persist_decision(run_id, decision)  # data-only (FIX B), two-arg call
    repo.persist_reconciliation(run_id, matches)  # never NULL on a clean run

    # --- branch SOLELY on final_action (the code-owned deterministic decision) ---
    if decision.final_action == "process":
        line_items = _compute_line_items(run_id, extracted, matches, roster)
        repo.replace_line_items(run_id, line_items)  # DELETE-by-run then insert
        repo.set_status(run_id, RunStatus.COMPUTED)
        repo.set_status(run_id, RunStatus.AWAITING_APPROVAL)  # HITL-01 pause
    else:  # request_clarification — draft + stub-send, pause at AWAITING_REPLY
        _clarify(run_id, email, decision, roster, llm=llm)


def _clarify(run_id, email, decision, roster, *, llm) -> None:
    """Draft a clarification, stub-send it, and pause the run at AWAITING_REPLY.

    The cheap DRAFT_* tier drafts the body (templated fallback on empty content so
    a draft failure never strands the run, CLAR-01). gateway.send_outbound mints a
    synthetic Message-ID and records it on the linked
    email_messages(direction='outbound', run_id) row — the SINGLE canonical anchor
    Plan 04 reads back via the header chain (FIX 3); there is NO payroll_runs
    Message-ID column. Status advances via repo.set_status (the sole writer, FIX B).
    The clarification threads off the client's inbound message_id (In-Reply-To +
    References) so the reply chain resolves in Plan 04.

    D-21-05 — the suggestion-only call: BEFORE composing, ask the cheap (draft) tier
    which roster employee each unresolved name most likely meant, and pass that as
    `suggestions=` so the clarification can be SPECIFIC ("did you mean David
    Reyes?"). CRITICAL: this runs ONLY here, on the request_clarification branch,
    STRICTLY AFTER `decide` has already returned (decision is a parameter, computed
    upstream in _run_stages). The suggestion is advisory COPY — it is NEVER passed
    to decide and NEVER influences final_action. A suggestion failure degrades to
    {} inside suggest_employees, so it can never strand the run.
    """
    # Finding #2 idempotency guard (CLAR-04): check for an existing clarification row
    # BEFORE drafting or sending. If one already exists and was sent, skip the send
    # and restore status to AWAITING_REPLY — prevents duplicate clarification emails
    # on re-trigger. The purpose='clarification' arg distinguishes this from a
    # confirmation row (finding #1 complement).
    existing_clari = repo.get_outbound_message_id(run_id, purpose="clarification")
    if existing_clari is not None:
        logger.info(
            "clarification already sent for run %s — skipping duplicate send "
            "(finding #2, CLAR-04)",
            run_id,
        )
        repo.set_status(run_id, RunStatus.AWAITING_REPLY)
        return

    # D-04 alias_candidates capture (finding #4 single-token-only + finding #5
    # capture-time exclusion). This runs AFTER the idempotency guard and BEFORE
    # send_outbound so that the original token is always captured in the same
    # transaction boundary as the clarification intent.
    #
    # Gate sequence (R2-MEDIUM test-conflict fix):
    #   1. len(unresolved_names) != 1 → no capture (finding #4 single-token-only)
    #   2. candidate_ids count > 1 for the token → no capture (finding #5 + R2-HIGH)
    #   3. candidate_ids count == 1 → already resolves; not a learning target
    #   4. candidate_ids count == 0 → genuinely unresolved → capture {token: None}
    #
    # R2-HIGH COLLISION DETECTION: Do NOT use deterministic_match return value to
    # infer collision. deterministic_match returns None for BOTH zero candidates (no
    # match) AND 2+ candidates (collision). A colliding token like "D. Reyes" returns
    # None yet has 2 candidate_ids. The pre-check MUST count candidate_ids directly.
    if len(decision.unresolved_names) == 1:
        candidate_token = decision.unresolved_names[0]
        from app.pipeline.reconcile_names import _norm
        norm_token = _norm(candidate_token)
        exact_ids = [
            emp.id for emp in roster.employees if _norm(emp.full_name) == norm_token
        ]
        alias_ids = [
            emp.id
            for emp in roster.employees
            if any(_norm(a) == norm_token for a in emp.known_aliases)
        ]
        candidate_ids = set(exact_ids) | set(alias_ids)

        if len(candidate_ids) > 1:
            # COLLISION: token matches 2+ employees — ambiguous at capture time.
            # Excluded per finding #5 + D-04 (colliders excluded AT emit time, not
            # just at write time). R2-HIGH: candidate_ids count is the only reliable
            # collision signal — deterministic_match None is insufficient.
            logger.info(
                "alias candidate %r excluded at capture: %d candidates "
                "(collision, finding #5, D-04, R2-HIGH)",
                candidate_token,
                len(candidate_ids),
            )
        elif len(candidate_ids) == 1:
            # Token already resolves uniquely to one employee — NOT an unresolved
            # alias the system needs to learn (it already works without the alias).
            logger.info(
                "alias candidate %r skipped at capture: already resolves uniquely "
                "(not an unresolved alias, not a learning target)",
                candidate_token,
            )
        else:
            # Zero candidates: token is GENUINELY UNRESOLVED — eligible for alias learning.
            # Capture {original_token: None}; resolved_employee_id filled at resume.
            candidates = {candidate_token: None}
            repo.set_alias_candidates(run_id, candidates)
            logger.info(
                "alias candidate captured for run %s: %r "
                "(single-token, genuinely unresolved, D-04 timing)",
                run_id,
                candidate_token,
            )
    else:
        logger.info(
            "alias capture skipped for run %s: %d unresolved names "
            "(single-token-only rule, finding #4)",
            run_id,
            len(decision.unresolved_names),
        )

    # Like compose below: only pass `llm` when injected (a test mock). When llm is
    # None (production), suggest_employees binds its own default client — passing
    # llm=None would force the cheap call onto a None client and silently degrade
    # every suggestion to the generic ask.
    suggest_kwargs = {}
    if llm is not None:
        suggest_kwargs["llm"] = llm
    suggestions = suggest_employees(
        decision.unresolved_names, roster, **suggest_kwargs
    )

    compose_kwargs = {"suggestions": suggestions}
    if llm is not None:
        compose_kwargs["llm"] = llm
    body = compose_clarification(decision, **compose_kwargs)

    # HIGH-1 record-only branch (06-08) — placed HERE, after alias-candidate capture
    # (set_alias_candidates above) and body composition, BEFORE gateway.send_outbound.
    # CRITICAL HIGH-2 ordering: the record_only check MUST come after both the D-04
    # alias-candidate capture block and the body composition block so they ALWAYS run
    # unconditionally — this is what makes Beat 3 work on in-app (record_only) runs:
    # the alias is captured in the clarification step, so the follow-up compose resolves
    # without a second clarification ("it learned"). A record_only check BEFORE alias
    # capture would silently break Beat 3 for all in-app runs (HIGH-2 ordering fix).
    record_only = repo.get_record_only_flag(run_id)
    if record_only:
        # Path-1 (in-app compose) record-only delivery: write the outbound row
        # WITHOUT calling the real Resend provider. uuid is already imported at
        # module level — do NOT re-import inside the function body.
        synthetic_mid = f"<{uuid.uuid4()}@demo.payroll-agent.local>"
        repo.insert_email_message(
            run_id=run_id,
            direction="outbound",
            message_id=synthetic_mid,
            in_reply_to=email.message_id,
            references_header=email.message_id,
            subject=clarification_subject(email.subject),
            from_addr=None,
            to_addr=email.from_addr,
            body_text=body,
            purpose="clarification",
            send_state="sent",
        )
        repo.set_status(run_id, RunStatus.AWAITING_REPLY)
        return
    # else: live Path-2 run — fall through to the real Resend gateway call (unchanged)
    gateway.send_outbound(
        run_id=run_id,
        to_addr=email.from_addr,
        subject=clarification_subject(email.subject),
        body=body,
        in_reply_to=email.message_id,
        references_header=email.message_id,
        purpose="clarification",
        send_state="sent",
    )
    repo.set_status(run_id, RunStatus.AWAITING_REPLY)  # CLAR-01 pause


def _write_aliases_if_safe(run_id: uuid.UUID, run: dict, roster) -> None:
    """Write any unambiguous, non-colliding alias candidates to employees.known_aliases.

    Called in _deliver BEFORE set_status(SENT) (D-13b ordering — PATTERNS.md line 611).
    Must be wrapped in try/except at the call site: any internal exception is logged and
    swallowed so an alias-learning failure NEVER strands or fails a successfully-sent run
    (D-13b defensive isolation).

    For each token → employee_id_str in alias_candidates:
    - Skip if employee_id_str is None (never got resolved — name wasn't clarified).
    - Call _safe_to_learn_alias (D-01b collision guard) — skip if False.
    - Call update_known_alias (D-01 idempotent JSONB append).
    - BATCH-SAFE: refresh current_roster after each accepted alias write so the NEXT
      iteration validates against the updated roster (MEDIUM finding — prevents multiple
      candidates in one approval batch from interacting unsafely).
    """
    import uuid as _uuid
    run_data = repo.load_run(run_id)
    if run_data is None:
        return
    alias_candidates = run_data.get("alias_candidates") or {}
    if not alias_candidates:
        return

    current_roster = roster  # start with the roster already loaded by _deliver
    for token, employee_id_str in alias_candidates.items():
        if employee_id_str is None:
            # Never resolved (no clarification reply that identified this employee).
            logger.info(
                "alias write skipped for %r: no resolved employee_id (never clarified)",
                token,
            )
            continue

        try:
            employee_id = _uuid.UUID(str(employee_id_str))
        except (ValueError, AttributeError):
            logger.warning(
                "alias write skipped for %r: invalid employee_id_str %r",
                token,
                employee_id_str,
            )
            continue

        target_employee = next(
            (e for e in current_roster.employees if e.id == employee_id), None
        )
        if target_employee is None:
            logger.info(
                "alias write skipped for %r → %s: employee not found in roster",
                token,
                employee_id,
            )
            continue

        if not _safe_to_learn_alias(token, target_employee, current_roster):
            logger.info(
                "alias write skipped for %r → %s: collision guard fired (D-01b)",
                token,
                employee_id,
            )
            continue

        written = repo.update_known_alias(employee_id, token)
        if written:
            logger.info("alias learned: %r → %s", token, employee_id)
            # BATCH-SAFE: refresh the roster after each accepted write so the next
            # iteration validates against the updated roster state (MEDIUM finding).
            current_roster = repo.load_roster_for_business(run["business_id"])
        else:
            logger.info(
                "alias write no-op for %r → %s: already present (idempotent)",
                token,
                employee_id,
            )


def _deliver(run_id: uuid.UUID, run: dict) -> None:
    """Compose + send the confirmation email + per-employee PDFs.

    Called synchronously by the approve route. Raises freely — the caller (approve
    handler) wraps this in the D-13b error boundary (try/except → record_run_error).
    NEVER catches exceptions internally: a delivery failure must surface to ERROR,
    not silently strand the run in APPROVED.

    CLAR-04 purpose-aware idempotency guard (finding #1): checks for an existing
    confirmation row via get_outbound_message_id(run_id, purpose='confirmation').
    A purpose-blind lookup would incorrectly skip the confirmation if a clarification
    had been sent earlier — purpose='confirmation' scopes the check correctly.

    D-01/D-02 alias write: _write_aliases_if_safe is called BEFORE set_status(SENT)
    (PATTERNS.md line 611 ordering), wrapped in try/except (D-13b defensive isolation —
    alias write failure logs a warning and never strands or fails a sent run).

    CR-03 fix: run is enriched with business_name (loaded from businesses via
    load_business_name) and pay_period_label (formatted from pay_period_start /
    pay_period_end) so confirmation_subject() and compose_confirmation() produce the
    correct subject line. load_run() stays lean (no JOIN for every caller).
    """
    # Step 0 — Enrich run dict with fields needed by confirmation helpers (CR-03).
    # load_run() returns business_id but NOT business_name (no JOIN) and NOT
    # pay_period_label (non-existent column). Enrich here, scoped to _deliver.
    run = dict(run)  # shallow copy — do not mutate the caller's dict
    biz_name = repo.load_business_name(run["business_id"])
    run["business_name"] = biz_name if biz_name else "Payroll Run"
    start = run.get("pay_period_start")
    end = run.get("pay_period_end")
    if start and end:
        run["pay_period_label"] = f"{start} to {end}"
    elif start:
        run["pay_period_label"] = str(start)
    else:
        run["pay_period_label"] = ""

    # Step 1 — Purpose-aware already-sent guard (finding #1, CLAR-04):
    # Only a row with purpose='confirmation' AND send_state='sent' counts as proof-of-
    # delivery. A reserved/failed row or a clarification row does NOT count.
    existing = repo.get_outbound_message_id(run_id, purpose="confirmation")
    if existing is not None:
        logger.info(
            "confirmation already sent for run %s (%s) — advancing to SENT+RECONCILED "
            "without duplicate send (finding #1, CLAR-04)",
            run_id,
            existing,
        )
        repo.set_status(run_id, RunStatus.SENT)
        repo.set_status(run_id, RunStatus.RECONCILED)
        return

    # Step 2 — Load line items (explicit columns, LOW finding fix).
    paystubs = repo.load_line_items(run_id)

    # Step 3 — Compose the confirmation email body (D-10b hard timeout passed).
    body = compose_confirmation(paystubs, run, timeout_s=3.0)

    # Step 4 — Load roster for employee full names (needed for PDF header).
    roster = repo.load_roster_for_business(run["business_id"])
    emp_by_id = {str(e.id): e for e in roster.employees}

    # Step 5 — Generate per-employee PDFs (pure, in-memory — HITL-03).
    pdf_attachments: list[tuple[str, bytes]] = []
    for item in paystubs:
        emp = emp_by_id.get(str(item.employee_id)) if item.employee_id else None
        emp_name = emp.full_name if emp else (item.submitted_name or "Employee")
        pdf_bytes = generate_paystub_pdf(
            item,
            emp_name,
            run.get("pay_period_start"),
            run.get("pay_period_end"),
            business_name=run.get("business_name"),
            filing_status=emp.filing_status if emp else None,
            hourly_rate=emp.hourly_rate if emp else None,
        )
        # The attachment filename MUST end in .pdf — Resend forwards the filename
        # verbatim, and a name without an extension (e.g. "Maria Chen") arrives as an
        # unrecognized binary blob the recipient's mail client won't open as a PDF.
        # Sanitize like the /runs/{id}/pdf download route so both produce the same name.
        safe_name = re.sub(r"[^\w.\-]", "_", emp_name, flags=re.ASCII) or "employee"
        pdf_attachments.append((f"paystub_{safe_name}.pdf", pdf_bytes))

    # Step 6 — Load the inbound email for the reply-to address.
    inbound = repo.load_inbound_email(run_id)
    to_addr = inbound.from_addr if inbound else ""

    # Step 7 — Send. HIGH-1 record-only branch (06-08): check record_only flag.
    # record_only=True (compose-created runs): write outbound row WITHOUT calling Resend.
    # record_only=False (live Path-2 runs): keep calling gateway.send_outbound unchanged.
    # Steps 8-10 (alias write + SENT + RECONCILED) run unconditionally for BOTH branches.
    record_only = repo.get_record_only_flag(run_id)
    if record_only:
        # Path-1 record-only delivery: write the confirmation outbound row WITHOUT Resend.
        synthetic_mid = f"<{uuid.uuid4()}@demo.payroll-agent.local>"
        repo.insert_email_message(
            run_id=run_id,
            direction="outbound",
            message_id=synthetic_mid,
            in_reply_to=inbound.message_id if inbound else None,
            references_header=inbound.message_id if inbound else None,
            subject=confirmation_subject(run, inbound.subject if inbound else None),
            from_addr=None,
            to_addr=to_addr,
            body_text=body,
            purpose="confirmation",
            send_state="sent",
        )
        # DO NOT return here — fall through to alias write + status steps below.
    else:
        # Phase 6 live-provider swap writes send_state='reserved' BEFORE the provider call
        # and flips to 'sent'/'failed' after — no code change needed here; the column exists.
        gateway.send_outbound(
            run_id=run_id,
            to_addr=to_addr,
            subject=confirmation_subject(run, inbound.subject if inbound else None),
            body=body,
            attachments=pdf_attachments,
            purpose="confirmation",
            send_state="sent",
        )

    # Step 8 — Alias write (D-01, D-02): learn any unambiguous alias candidates.
    # MUST be called BEFORE set_status(SENT) (PATTERNS.md line 611 ordering, D-13b).
    # Wrapped in try/except so an alias-learning failure NEVER strands or fails the run
    # (D-13b defensive isolation — alias write is independently droppable, D-15).
    try:
        _write_aliases_if_safe(run_id, run, roster)
    except Exception as alias_exc:  # noqa: BLE001 — D-13b defensive isolation
        logger.warning(
            "alias write skipped for run %s: %s (run continues to SENT)",
            run_id,
            type(alias_exc).__name__,
        )

    # Steps 9-10 — Advance the run: SENT → RECONCILED (both sequential in this
    # synchronous call; RECONCILED is the only terminal-success status).
    repo.set_status(run_id, RunStatus.SENT)
    repo.set_status(run_id, RunStatus.RECONCILED)


def _compute_line_items(run_id, extracted, matches, roster):
    """Build PaystubLineItems for the resolved (matched) employees on a process run."""
    match_by_name = {m.submitted_name: m for m in matches}
    emp_by_id = {e.id: e for e in roster.employees}

    items = []
    for ee in extracted.employees:
        m = match_by_name.get(ee.submitted_name)
        if m is None or m.matched_employee_id is None:
            continue  # unresolved names never reach a process run (gate blocks them)
        employee = emp_by_id.get(m.matched_employee_id)
        if employee is None:
            # WR-01: on a PROCESS run the gate guarantees every name is resolved to a
            # roster employee. A matched_employee_id with no roster row (e.g. a stale
            # reconciliation persisted against a since-changed roster, or a roster
            # loaded for the wrong business) is an INVARIANT VIOLATION, not an expected
            # skip — silently omitting the employee would ship an incomplete payroll the
            # operator is told is clean. Fail LOUD: raise so the run routes to ERROR
            # (D-A1-03 error-wrap) instead of computing a degraded paystub.
            raise ValueError(
                f"process-run integrity: matched employee {m.matched_employee_id} "
                f"for {ee.submitted_name!r} is not in the loaded roster"
            )
        resolved_hours = {
            "hours_regular": ee.hours_regular,
            "hours_overtime": ee.hours_overtime,
            "hours_vacation": ee.hours_vacation,
            "hours_sick": ee.hours_sick,
            "hours_holiday": ee.hours_holiday,
        }
        item = calculate(
            resolved_hours, employee, ee.contribution_401k_override
        )
        # Stamp the real run identity + the submitted name (the per-name provenance;
        # there is no score on a deterministic resolution, D-21-01/04).
        item = item.model_copy(
            update={
                "run_id": run_id,
                "submitted_name": ee.submitted_name,
            }
        )
        items.append(item)
    return items
