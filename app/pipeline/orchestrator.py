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

import contextlib
import logging
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal

from app.db import repo
from app.email import gateway
from app.models.contracts import Extracted, ExtractedEmployee, InboundEmail
from app.models.roster import NameMatchResult
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
from app.pipeline.validate import _HOURS_FIELDS, _is_paid, detect_field_regression, validate

logger = logging.getLogger("payroll_agent.orchestrator")


@dataclass
class _RunStagesResult:
    """Minimal return value from _run_stages (MONEY-03 D-7.5-02).

    Finding 5 fix: shape carries exactly what resume_pipeline needs — clarify_deferred,
    matches, and issues. Does NOT carry extracted (already persisted by _run_stages).
    D-7.5-11: raw_extracted is captured in resume_pipeline BEFORE the _run_stages call
    (extracted= kwarg), so it never needs to be returned here.
    clarify_deferred=True: ANY field_regression issue exists; _clarify deferred so
    resume_pipeline can write 'asked' BEFORE the send (N2 ordering).
    """

    clarify_deferred: bool = False
    matches: object = None   # list[NameMatchResult]
    issues: object = None    # list[ValidationIssue]


def backfill_extracted(extracted, snapshot, prior_matches, matches, resolved_drops):
    """Fill silence fields from the pre-clarify snapshot (D-7.5-10 Phase 2, MONEY-03).

    Pure function with no DB calls. Operates on Pydantic-validated Extracted objects.
    Employee_id-keyed on BOTH sides (R2-2 fix — D-7.5-10a):
    - snapshot side: employee_id resolved via prior_matches (the SNAPSHOT round's reconciliation)
    - current side: employee_id resolved via matches (the CURRENT round's reconciliation)
    So 'M. Chen' (prior) and 'Maria Chen' (current), same employee_id, land in the same
    backfill slot — the name difference doesn't prevent carry-forward.

    resolved_drops: set[tuple[employee_id_str, field]] — fields to SKIP backfilling.
    This is backfill_skip (from D-7.5-11 TWO-SET MODEL): ONLY confirmed_dropped +
    client_supplied from newly_classified (NOT carried_forward). confirmed_dropped is in
    resolved_drops so the explicit-zero overpay guard fires: _is_paid(Decimal('0')) is
    False so explicit-zero looks backfillable by value alone; the resolved_drops gate
    is the protection. carried_forward is intentionally ABSENT from resolved_drops so
    backfill FILLS it from the snapshot → paystub OT=2.

    Note: suppress_detection (the ALL-answered set) is NOT passed here — it is forwarded
    to validate() only (D-7.5-11 TWO-SET MODEL).

    Returns a new Extracted (copy with silence fields filled from snapshot).
    """
    if snapshot is None:
        return extracted  # no snapshot → no backfill (safe no-op)

    # R2-2 fix: employee_id-keyed on BOTH sides.
    # Build id_to_snapshot_emp: {employee_id_str: ExtractedEmployee} from snapshot + prior_matches.
    name_to_id_prior: dict[str, str] = {
        m.submitted_name: str(m.matched_employee_id)
        for m in (prior_matches or [])
        if m.resolved and m.matched_employee_id is not None
    }
    id_to_snapshot_emp: dict[str, ExtractedEmployee] = {}
    for emp in snapshot.employees:
        emp_id_str = name_to_id_prior.get(emp.submitted_name)
        if emp_id_str is not None:
            id_to_snapshot_emp[emp_id_str] = emp  # last-wins (D-12)

    if not id_to_snapshot_emp:
        # prior_matches empty or none resolved → no backfill (safe no-op)
        return extracted

    # Build name_to_id_current: {submitted_name: employee_id_str} from current matches.
    name_to_id_current: dict[str, str] = {
        m.submitted_name: str(m.matched_employee_id)
        for m in (matches or [])
        if m.resolved and m.matched_employee_id is not None
    }

    _resolved_drops = resolved_drops or set()

    # Build the updated employees list.
    new_employees = []
    for emp in extracted.employees:
        emp_id_str = name_to_id_current.get(emp.submitted_name)  # may be None if unresolved
        snap_emp = id_to_snapshot_emp.get(emp_id_str) if emp_id_str else None

        if snap_emp is None:
            # No snapshot match by employee_id → keep emp as-is, no backfill possible.
            new_employees.append(emp)
            continue

        # Build a dict of field values for the new ExtractedEmployee.
        emp_dict = emp.model_dump()
        for field in _HOURS_FIELDS:
            current_val = getattr(emp, field)
            if not _is_paid(current_val):
                # Silence or explicit zero — check whether to backfill.
                snap_val = getattr(snap_emp, field)
                if _is_paid(snap_val):
                    # Snapshot had a value — eligible for carry-forward.
                    if emp_id_str is not None and (emp_id_str, field) in _resolved_drops:
                        # Field is in resolved_drops (confirmed_dropped or client_supplied):
                        # D-7.5-11 overpay guard — do NOT backfill.
                        # confirmed_dropped: client explicitly zeroed → honor zero (OT=0).
                        # client_supplied: client gave a value → use extracted value.
                        pass
                    else:
                        # Not in resolved_drops → backfill (carry_forward from snapshot).
                        emp_dict[field] = snap_val
        new_employees.append(ExtractedEmployee(**emp_dict))

    return Extracted(
        run_id=extracted.run_id,
        employees=new_employees,
        pay_period_start=extracted.pay_period_start,
        pay_period_end=extracted.pay_period_end,
    )


def run_pipeline(run_id: uuid.UUID, *, llm=None) -> None:
    """Drive one run from received → awaiting_approval (or awaiting_reply on a clarification).

    `llm` is the client module the stages call; defaults to each stage's own
    bound client. Tests inject a mocked client by patching app.llm.client.OpenAI.

    Thin, non-raising delegator (HIGH #1 fix, review round): the error-wrap
    boundary now lives INSIDE `_run` itself, not here — `_run` owns its own
    try/except so its error path can see the `roster` local it already loaded,
    which this outer scope never had access to. `_run` never lets an exception
    escape, so this function needs no try/except of its own; its external
    contract (never raises) is unchanged.
    """
    _run(run_id, llm=llm)


def _run(run_id: uuid.UUID, *, llm) -> None:
    """Load the run, run the four judgment stages, and self-contain any failure.

    HIGH #1 fix: this function owns its OWN try/except (moved here from
    run_pipeline) so that whatever `roster` it has already loaded before a
    failure is visible to its own error path — record_run_error(roster=roster)
    now sees a real, populated Roster for any failure after the load line,
    instead of always None. `roster = None` is the first statement so the name
    is always bound, even if `load_run`/`load_inbound_email` raise before the
    roster is ever loaded.
    """
    roster = None
    try:
        run = repo.load_run(run_id)
        if run is None:
            raise ValueError(f"run {run_id} not found")

        email = repo.load_inbound_email(run_id)
        if email is None:
            raise ValueError(f"run {run_id} has no source email")
        roster = repo.load_roster_for_business(run["business_id"])

        repo.set_status(run_id, RunStatus.EXTRACTING)
        _ = _run_stages(run_id, email, roster, llm=llm)  # discard return — first run, no field-regression
    except Exception as exc:  # noqa: BLE001 — the D-A1-03 error-wrap boundary (moved here from run_pipeline so roster, loaded above, is visible to the error path — HIGH #1 fix)
        # PII-safe summary: the exception TYPE only — str(exc) can echo prompt text,
        # submitted names, or model output, and this `reason` is BOTH logged AND
        # persisted to payroll_runs.error_reason (review fix). run_id is the
        # correlation key for deeper debugging. `roster`, whatever this function
        # had already loaded before the failure, is now passed through so
        # record_run_error's scrub step can exclude real employee names/aliases
        # instead of falling back to email-regex-only scrubbing (HIGH #1).
        reason = type(exc).__name__
        logger.warning("run %s failed: %s", run_id, reason)
        repo.record_run_error(run_id, reason, detail_exc=exc, stage="pipeline", roster=roster)


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
    # HIGH #1 (resume variant): initialize roster=None as the first statement inside
    # the try block, so the name is always bound in the enclosing scope even if the
    # exception fires before the roster load line below (the narrower UnboundLocalError
    # window resume_pipeline has — unlike _run, its own roster load already happens
    # inside the same try block its except clause guards).
    roster = None
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

        # STEP B: D-7.5-11 classify-first + D-7.5-10 three-phase detection block.
        # (Replaces the bare _run_stages call with Round-1/Round-2 logic.)

        # Step E0: Deserialize prior_matches from _pre_reconciliation (R3-3 fix).
        # Empty list on first-ever resume (no prior reconciliation); [] → detect_field_regression
        # returns [] (correct — no drops to detect without a prior run).
        prior_matches: list[NameMatchResult] = [
            NameMatchResult.model_validate(m)
            for m in _pre_reconciliation
            if isinstance(m, dict)
        ]

        # Step E1: Load snapshot and clarified state.
        snapshot = repo.load_pre_clarify_extracted(run_id)    # None on first resume
        clarified = repo.load_clarified_fields(run_id)          # {} on first resume

        # Step E2: Build _resolved_by_name from clarified TERMINAL outcomes (D-14 + KEY TYPE).
        # KEY TYPE: (employee_id_str, field) — NOT (submitted_name, field).
        # clarified.items() already yields emp_id_str keys — NO reverse-lookup needed.
        _resolved_by_name: set[tuple[str, str]] = set()
        for emp_id_str, field_outcomes in clarified.items():
            for field, outcome in field_outcomes.items():
                if outcome in ("confirmed_dropped", "client_supplied"):
                    _resolved_by_name.add((emp_id_str, field))

        # Step E3: Determine which round this is.
        is_round_2 = bool(clarified)  # any clarified_fields entries = at least Round 2

        # Step E4: Round-1 path (no clarified entries — first resume or non-field-regression).
        if not is_round_2:
            stage = _run_stages(
                run_id,
                combined_email,
                roster,
                llm=llm,
                prior=snapshot,           # None on very first resume
                prior_matches=prior_matches,  # [] on very first resume
                resolved_drops=None,      # no confirmed_dropped pairs yet
            )
            # NOTE: no extracted= kwarg on Round-1. _run_stages calls extract() internally.

            if stage.clarify_deferred:
                # IN-01: shared helper writes 'asked', persists, and sends the
                # clarification_field_regression email (N2 ordering preserved).
                # Factored out so Round-1 and Round-2 cannot drift (CR-02 fix).
                _defer_field_regression_clarification(
                    run_id, clarified, stage, combined_email, roster, llm=llm
                )
                return  # run is at AWAITING_REPLY — do not fall through to alias-diff

            # stage.clarify_deferred is False: fall through to STEP C/D alias-diff.

        # Step E5: Round-2 path — D-7.5-11 CLASSIFY-FIRST (answered rounds).
        else:
            # CR-01 FIX: two separate extractions for two different purposes.
            #
            # CLASSIFY needs the REPLY IN ISOLATION so that:
            #   - silence (field absent from reply) → None → carried_forward
            #   - explicit zero ("0 overtime") → Decimal('0') → confirmed_dropped
            # If we classified from combined_email, the original section's positive value
            # (e.g. OT=2) can survive into the extraction, and "0 overtime" in the reply
            # section is eclipsed → classified as client_supplied with raw_val=2 → OVERPAY.
            #
            # PROCESS/BACKFILL needs the COMBINED body so original employees/hours that the
            # client did not re-state are retained (lossless combined extraction, FIX 4).
            #
            # Cost: one extra LLM call on answered rounds — acceptable for money-safety.
            extract_kwargs_r2 = {"run_id": run_id}
            if llm is not None:
                extract_kwargs_r2["llm"] = llm

            # Extraction 1 (CLASSIFY): reply body ONLY — uncombined.
            # `inbound` is the raw reply InboundEmail BEFORE combination (resume_pipeline param).
            # Use it directly so the classify step sees ONLY what the client said in the reply.
            raw_reply_extracted = extract(inbound, roster, **extract_kwargs_r2)

            # Extraction 2 (PROCESS/BACKFILL): combined body — retains original employees/hours.
            raw_extracted = extract(combined_email, roster, **extract_kwargs_r2)

            # D-7.5-11 STEP 1: CLASSIFY the raw REPLY (reply-only) for asked fields ONLY.
            # Do NOT classify all snapshot-paid fields — that mislabels untouched fields
            # (e.g. hours_regular that was always present) as client_supplied.
            # Only fields currently 'asked' get classified.
            #
            # CR-01 FIX: Build the classify lookup from the UNION of current matches
            # (reconcile the raw reply's submitted names) AND prior_matches (snapshot names).
            # Prior-only keying misses restated names: if snapshot had "M. Chen" but the
            # reply says "Maria Chen", the current name is absent from prior_matches-only
            # lookup → raw_emp stays None → field stays "asked" → absent from backfill_skip
            # → snapshot's positive value is silently restored (OVERPAY). The union ensures
            # the reply's current submitted names are always covered.
            #
            # WR-01 FIX: prior_matches go FIRST, current_matches_for_classify go LAST.
            # Dict comprehension is last-wins: current (appended last) overrides prior for
            # any shared submitted_name. This implements "current wins" — a restated name
            # takes the CURRENT resolution. The old code had the order reversed (current
            # first, prior last) which was prior-wins — contradicting the comment.
            raw_reply_submitted = [e.submitted_name for e in raw_reply_extracted.employees]
            current_matches_for_classify = reconcile_names(raw_reply_submitted, roster)
            name_to_id_for_classify: dict[str, str] = {
                m.submitted_name: str(m.matched_employee_id)
                for m in (list(prior_matches) + list(current_matches_for_classify))
                if m.resolved and m.matched_employee_id is not None
            }
            # Build a lookup from raw_reply_extracted: {submitted_name: ExtractedEmployee}.
            # CR-01: uses the REPLY-ONLY extraction so silence == None (not the original value).
            raw_name_to_emp = {emp.submitted_name: emp for emp in raw_reply_extracted.employees}

            # WR-01: staging set for asked fields that cannot be resolved in the raw reply.
            # These are absorbed into backfill_skip in STEP 2 to fail conservatively
            # (under-fill that re-clarifies, never overpay from snapshot restore).
            _unresolvable_asked: set[tuple[str, str]] = set()

            # CR-01 FIX: capture the authoritative reply-derived value for every asked
            # field at classify time, so we can overwrite raw_extracted (the COMBINED
            # extraction) with the correct value before _run_stages sees it (STEP 3).
            # Keys: (emp_id_str, field) — same namespace as newly_classified.
            # Values: the authoritative paid value the paystub MUST use for that field.
            #   client_supplied  → the positive Decimal the reply extraction returned
            #   confirmed_dropped → Decimal('0') (client explicitly zeroed; paired with
            #                       backfill_skip to block snapshot restore)
            #   carried_forward  → None (so Phase-2 backfill_extracted fills from snapshot;
            #                       must force None even if combined extraction carried a
            #                       possibly-wrong positive value)
            #   _unresolvable_asked → None (field genuinely absent; prevents combined value
            #                       from leaking through to the paystub)
            reply_value_overrides: dict[tuple[str, str], Decimal | None] = {}

            # Classify each (emp_id_str, field) with outcome 'asked'.
            newly_classified: set[tuple[str, str]] = set()  # all answered asked fields
            for emp_id_str, field_outcomes in list(clarified.items()):
                for field, outcome in list(field_outcomes.items()):
                    if outcome != "asked":
                        continue  # only reclassify fields that were asked

                    # Find the raw extracted employee for this emp_id_str via the
                    # union lookup (current + prior names → employee_id).
                    raw_emp = None
                    for raw_name, raw_e in raw_name_to_emp.items():
                        if name_to_id_for_classify.get(raw_name) == emp_id_str:
                            raw_emp = raw_e
                            break

                    if raw_emp is None:
                        # WR-01 FIX: Cannot resolve this employee in the raw reply even
                        # after the union lookup — fail conservatively.
                        # Stage in _unresolvable_asked so STEP 2 adds (emp_id_str, field)
                        # to backfill_skip; the field is then NEVER re-backfilled from the
                        # snapshot. Worst case: under-fill that re-clarifies next round.
                        # This invariant prevents snapshot-restore overpay on any asked
                        # field that the classify step cannot resolve.
                        _unresolvable_asked.add((emp_id_str, field))
                        # CR-01 FIX: force None so the combined extraction's value for this
                        # field cannot leak through to the paystub (money-safe under-fill).
                        reply_value_overrides[(emp_id_str, field)] = None
                        continue

                    raw_val = getattr(raw_emp, field, None)
                    # D-7.5-10b + D-7.5-11: classify from RAW reply, before any backfill.
                    if raw_val is not None and raw_val > 0:
                        # Present-positive in raw reply → client supplied a value.
                        clarified[emp_id_str][field] = "client_supplied"
                        # CR-01 FIX: capture the client's supplied value as the authoritative
                        # value — overrides whatever the combined extraction returned.
                        reply_value_overrides[(emp_id_str, field)] = raw_val
                    elif raw_val is not None and raw_val == Decimal("0"):
                        # Explicit Decimal('0') in raw reply → client explicitly zeroed.
                        clarified[emp_id_str][field] = "confirmed_dropped"
                        # CR-01 FIX: force explicit zero (paired with backfill_skip so
                        # snapshot value is not restored by backfill_extracted either).
                        reply_value_overrides[(emp_id_str, field)] = Decimal("0")
                    else:
                        # None/absent in raw reply → client was silent → carry forward.
                        clarified[emp_id_str][field] = "carried_forward"
                        # CR-01 FIX: force None so backfill_extracted can fill from snapshot
                        # (carried_forward is NOT in backfill_skip → backfill FIRES → OT=2).
                        # Must overwrite even if the combined extraction had a value: the
                        # combined body's positive value would otherwise eclipsed the silence.
                        reply_value_overrides[(emp_id_str, field)] = None

                    newly_classified.add((emp_id_str, field))

            # D-7.5-11 STEP 2: Build TWO DISTINCT sets (the two-set fix).
            #
            # SET A — suppress_detection: ALL answered asked fields.
            # = _resolved_by_name (prior terminals) UNION ALL newly_classified.
            # Purpose: stop detect_field_regression / N8 from re-emitting field_regression
            # for any just-answered field. Passed to _run_stages(suppress_detection=) →
            # validate(resolved_drops=suppress_detection). Does NOT reach backfill_extracted.
            suppress_detection: set[tuple[str, str]] = set(_resolved_by_name)
            for pair in newly_classified:
                suppress_detection.add(pair)

            # SET B — backfill_skip: ONLY confirmed_dropped + client_supplied (NOT carried_forward).
            # = _resolved_by_name (prior terminals) UNION only confirmed_dropped + client_supplied
            #   UNION _unresolvable_asked (WR-01: conservative fail for unresolvable asked fields).
            # Purpose: tell backfill_extracted which fields to skip.
            # carried_forward is intentionally ABSENT: backfill FILLS those → paystub OT=2.
            # confirmed_dropped IS present: backfill skips → paystub OT=0 (no overpay).
            # _is_paid(Decimal('0')) is False (explicit zero looks backfillable by value alone);
            # the backfill_skip resolved_drops gate is the protection.
            # WR-01: _unresolvable_asked fields are added to backfill_skip so an unclassifiable
            # asked field is NEVER re-backfilled from the snapshot. Fail conservatively.
            backfill_skip: set[tuple[str, str]] = set(_resolved_by_name)
            for emp_id_str, field in newly_classified:
                outcome = clarified.get(emp_id_str, {}).get(field)
                if outcome in ("confirmed_dropped", "client_supplied"):
                    backfill_skip.add((emp_id_str, field))
                # carried_forward: NOT added → backfill fires → OT=2 from snapshot → paystub
            # WR-01 absorption: unresolvable asked fields are always backfill-skipped.
            backfill_skip.update(_unresolvable_asked)

            # D-7.5-11 STEP 2.5: CR-01 FIX — reconcile the PAID value from the REPLY
            # for every answered asked field before passing raw_extracted to _run_stages.
            #
            # Problem: raw_extracted is the COMBINED extraction (original body + reply).
            # The combined body may carry the original section's value for an asked field
            # (e.g. OT=2 from the original payroll section), eclipsing the reply's answer
            # (e.g. "0 overtime"). backfill_skip only blocks snapshot RESTORE inside
            # backfill_extracted — it has no power over a value the combined extraction
            # already carries. So classify outcome and paid value diverge whenever the two
            # extractions disagree on an asked field (CR-01 regression).
            #
            # Fix: for every (emp_id_str, field) in reply_value_overrides, overwrite
            # the field in raw_extracted's matching employee so the paid value is the
            # same value the classify step decided.
            #
            # Employee-id mapping nuance: the override map is keyed by emp_id_str from
            # the REPLY extraction's reconciliation (name_to_id_for_classify). The
            # COMBINED extraction employees are keyed by submitted_name. We must build
            # a separate name→id map for the combined extraction's employees to bridge
            # the two namespaces correctly.
            if reply_value_overrides:
                # Build name_to_id_combined from the combined extraction's submitted names.
                combined_submitted = [e.submitted_name for e in raw_extracted.employees]
                combined_matches = reconcile_names(combined_submitted, roster)
                name_to_id_combined: dict[str, str] = {
                    m.submitted_name: str(m.matched_employee_id)
                    for m in combined_matches
                    if m.resolved and m.matched_employee_id is not None
                }
                # Build the updated employees list (immutable copy idiom from backfill_extracted).
                new_employees_combined = []
                for emp in raw_extracted.employees:
                    emp_id_combined = name_to_id_combined.get(emp.submitted_name)
                    emp_dict = emp.model_dump()
                    if emp_id_combined is not None:
                        for field in _HOURS_FIELDS:
                            key = (emp_id_combined, field)
                            if key in reply_value_overrides:
                                emp_dict[field] = reply_value_overrides[key]
                    new_employees_combined.append(ExtractedEmployee(**emp_dict))
                raw_extracted = Extracted(
                    run_id=raw_extracted.run_id,
                    employees=new_employees_combined,
                    pay_period_start=raw_extracted.pay_period_start,
                    pay_period_end=raw_extracted.pay_period_end,
                )

            # D-7.5-11 STEP 3: call _run_stages ONCE with TWO DISTINCT sets.
            # - extracted=raw_extracted: combined-body extraction (lossless, retains originals)
            # - suppress_detection=suppress_detection: ALL answered fields → N8 only
            # - resolved_drops=backfill_skip: confirmed_dropped+client_supplied → backfill skip
            # - prior=snapshot, prior_matches=prior_matches_for_backfill: three-phase ordering (D-7.5-10)
            #
            # R2-2 SNAPSHOT-NAME FIX: prior_matches (loaded from post-Round-1 reconciliation)
            # reflects the REPLY names ("Maria Chen"), not the SNAPSHOT names ("M. Chen").
            # backfill_extracted builds name_to_id_prior from prior_matches to map snapshot
            # employees → employee_id; if the snapshot name is absent from prior_matches, no
            # backfill occurs (OT=0 instead of OT=2). Fix: also reconcile the SNAPSHOT's
            # submitted names and merge into prior_matches_for_backfill. The snapshot names
            # resolve via alias → same employee_id, so "M. Chen" + "Maria Chen" both map to
            # CHEN_ID, and the backfill finds the snapshot employee by employee_id.
            if snapshot is not None:
                snapshot_submitted = [e.submitted_name for e in snapshot.employees]
                snapshot_matches = reconcile_names(snapshot_submitted, roster)
                # WR-02: Merge snapshot_matches FIRST, prior_matches LAST.
                # backfill_extracted's name_to_id_prior is last-wins, so prior_matches
                # (persisted snapshot-round reconciliation) overrides snapshot_matches
                # for any shared name — prior is the AUTHORITATIVE snapshot-round record
                # and this is the INTENDED conflict resolution (both point to the same
                # employee_id in the normal case; prior wins when they disagree).
                prior_matches_for_backfill = list(snapshot_matches) + list(prior_matches)
            else:
                prior_matches_for_backfill = prior_matches

            # D-9-06 gap closure (WR-02): persisted BEFORE _run_stages so a crash in
            # _run_stages' own transaction cannot leave a stale 'asked' outcome — this
            # write and the persist-transaction below are independently committed and
            # independently diagnosable, never coupled.
            #
            # The terminal outcomes finalized in STEP 1 above (client_supplied /
            # confirmed_dropped / carried_forward) are already fully resolved in-memory
            # and do NOT depend on _run_stages' return value — stage.clarify_deferred
            # only gates whether _defer_field_regression_clarification ADDS new 'asked'
            # entries for a NEW regression found THIS round; it never touches the
            # classify-first terminal outcomes already in `clarified`. So persisting
            # `clarified` here, before _run_stages runs at all, is safe and mirrors the
            # already-established invariant used by _defer_field_regression_clarification
            # (Step 3 there: write commits and closes strictly before the later
            # LLM/provider-touching call).
            with repo.get_connection() as conn:
                with conn.transaction():
                    repo.set_clarified_fields(run_id, clarified, conn=conn)

            stage = _run_stages(
                run_id,
                combined_email,
                roster,
                llm=llm,
                prior=snapshot,
                prior_matches=prior_matches_for_backfill,
                suppress_detection=suppress_detection,  # ALL answered → N8 only
                resolved_drops=backfill_skip,           # confirmed_dropped+client_supplied → backfill skip
                extracted=raw_extracted,                # combined-body extraction for lossless process
            )

            # D-7.5-11 STEP 4: CR-02 FIX — check clarify_deferred AFTER persisting terminals.
            # If _run_stages deferred (a NEW field_regression appeared this round), the run
            # must send a clarification and return — NOT fall through to the alias-diff.
            # This mirrors Round-1's deferred handling (step ~316-325) and uses the same
            # shared helper (IN-01, _defer_field_regression_clarification). The classify-first
            # terminal outcomes were ALREADY persisted above (D-9-06); this helper only adds
            # the NEW 'asked' entries for the regression detected THIS round, in its own
            # separate closed transaction, before sending the clarification.
            if stage.clarify_deferred:
                _defer_field_regression_clarification(
                    run_id, clarified, stage, combined_email, roster, llm=llm
                )
                return  # run is at AWAITING_REPLY — do not run the alias diff

            # Not deferred: terminal outcomes from classify-first STEP 1 were already
            # persisted above (D-9-06), strictly before _run_stages was called. Fall
            # through to STEP C/D alias-diff (the run is at AWAITING_APPROVAL).

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
        # the resume path was missed when run_pipeline was sanitized). `roster` is
        # guaranteed bound (either None from the top-of-try initialization, or the
        # real Roster if the exception fired after the load line above) — OPS2-01.
        reason = type(exc).__name__
        logger.warning("resume of run %s failed: %s", run_id, reason)
        repo.record_run_error(run_id, reason, detail_exc=exc, stage="resume", roster=roster)


def _defer_field_regression_clarification(
    run_id,
    clarified: dict,
    stage: _RunStagesResult,
    combined_email: InboundEmail,
    roster,
    *,
    llm,
) -> None:
    """Shared helper for deferred field-regression clarification (IN-01, CR-02 fix).

    Called from BOTH the Round-1 branch (lines ~316-352) and the new Round-2
    branch when _run_stages returns clarify_deferred=True.  Factoring into one
    helper prevents the two copies from drifting — the Round-2 copy being
    entirely absent was the CR-02 bug.

    Contract (N2 ordering invariant):
      1. Write 'asked' for every NEW field_regression issue into `clarified`
         dict (mutated in-place).
      2. Persist clarified via set_clarified_fields BEFORE the send.
      3. Call _clarify(purpose='clarification_field_regression') to draft +
         send the email and advance to AWAITING_REPLY.

    The caller must `return` immediately after this call — the run is now at
    AWAITING_REPLY and must NOT fall through to the alias-diff.
    """
    # Step 1: Load fresh reconciliation so we can look up emp_id by submitted_name.
    post_run = repo.load_run(run_id)
    name_to_id_post = {
        m["submitted_name"]: m["matched_employee_id"]
        for m in (post_run.get("reconciliation") or [])
        if isinstance(m, dict) and m.get("matched_employee_id")
    }
    # Step 2: Write 'asked' for each NEW field_regression issue (N2 ordering).
    for issue in (stage.issues or []):
        if issue.issue_type == "field_regression":
            # issue.field format: "{submitted_name}.{field_name}" (IN-03 guard)
            parts = issue.field.rsplit(".", 1)
            if len(parts) == 2:
                submitted_name_p, field_name_p = parts
                current_emp_id_p = name_to_id_post.get(submitted_name_p)
                if current_emp_id_p:
                    clarified.setdefault(str(current_emp_id_p), {})[field_name_p] = "asked"
    # Step 3: Persist 'asked' BEFORE send (N2 invariant — asked-before-send).
    # D-9-06/D-9-01: a single-statement transaction that commits and closes
    # strictly BEFORE Step 5's _clarify(...) call below — no transaction ever
    # spans _clarify's LLM/provider calls. Steps 1/2/4 are reads/in-memory
    # mutation only, not folded in (nothing to gain from widening the txn).
    with repo.get_connection() as conn:
        with conn.transaction():
            repo.set_clarified_fields(run_id, clarified, conn=conn)

    # Step 4: Load the persisted decision + extracted for _clarify.
    run_row = repo.load_run(run_id)
    from app.models.contracts import Decision as _Decision
    persisted_decision = (
        _Decision.model_validate(run_row["decision"])
        if run_row and run_row.get("decision")
        else None
    )
    persisted_extracted = (
        Extracted.model_validate(run_row["extracted_data"])
        if run_row and run_row.get("extracted_data")
        else None
    )
    # Step 5: Send the clarification email (advances run to AWAITING_REPLY).
    if persisted_decision is not None and persisted_extracted is not None:
        _clarify(
            run_id,
            combined_email,
            persisted_decision,
            roster,
            persisted_extracted,
            llm=llm,
            purpose="clarification_field_regression",
        )


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


def _run_stages(
    run_id,
    email,
    roster,
    *,
    llm,
    prior=None,
    prior_matches=None,
    resolved_drops=None,
    suppress_detection=None,
    extracted=None,
) -> _RunStagesResult:
    """The shared four-stage gate path: extract → reconcile → validate → decide →
    persist → branch. Used by BOTH run_pipeline (first run) and resume_pipeline (the
    CLAR-03 re-entry), so the eval-reusable spine and the gate stay DRY and identical.

    D-7.5-11 extracted= kwarg: when supplied, skips the internal extract() call —
    the caller has already called extract() up front (Round-2 classify-first path).
    run_pipeline and Round-1 pass no extracted kwarg (None → internal extract() runs).

    TWO-SET separation (D-7.5-11, the set-conflation fix):
    - suppress_detection=: receives ALL answered asked fields (prior terminals UNION
      ALL newly_classified). Forwarded to validate(resolved_drops=suppress_detection)
      so N8 suppresses field_regression re-emission. Does NOT reach backfill_extracted.
    - resolved_drops=: receives the backfill-skip set (confirmed_dropped UNION
      client_supplied UNION prior terminals; NOT carried_forward). Forwarded to
      backfill_extracted(resolved_drops=resolved_drops). Does NOT reach validate N8.
    Round-1 and run_pipeline pass neither kwarg → both None → no suppression, no skip.

    Returns _RunStagesResult(clarify_deferred, matches, issues).
    """
    # D-7.5-11: if caller supplies pre-extracted data (Round-2 classify-first path),
    # skip the LLM extraction call — extracted is already the raw reply extraction.
    # run_pipeline and Round-1 pass no extracted kwarg (None → internal extract() runs).
    if extracted is None:
        extract_kwargs = {"run_id": run_id}
        if llm is not None:
            extract_kwargs["llm"] = llm
        extracted = extract(email, roster, **extract_kwargs)
    # else: use the supplied pre-extracted value directly (no LLM call)

    submitted_names = [e.submitted_name for e in extracted.employees]
    matches = reconcile_names(submitted_names, roster)  # pure: no llm (D-21-01)

    # D-7.5-10: DETECT-on-RAW → BACKFILL → CALC (three-phase ordering invariant)
    # Phase 1 — DETECT on raw extracted (pre-backfill): the OT 2→None drop is visible here.
    # Phase 2 — BACKFILL: fill silence fields from snapshot (employee_id-keyed via prior_matches).
    # Phase 3 — CALC: validate(BACKFILLED extracted, raw_field_drops=raw_drops) → decide → calc.
    raw_drops = None
    if prior is not None:
        # Phase 1 — DETECT on raw (pre-backfill) extracted.
        # detect_field_regression is called BEFORE backfill so the original OT 2→None
        # drop is visible. D-7.5-10 structural enforcement: NOT called inside validate().
        raw_drops = detect_field_regression(prior, extracted, prior_matches, matches)
        # Phase 2 — BACKFILL: carry silence fields from snapshot into extracted.
        # resolved_drops (= backfill_skip from caller) guards ONLY confirmed_dropped and
        # client_supplied from re-backfill — NOT carried_forward. carried_forward is
        # intentionally absent from resolved_drops so backfill FILLS it from the snapshot
        # (OT=2 → paystub OT=2). suppress_detection is NOT passed here — it is forwarded
        # to validate() only (N8 suppression, not backfill control).
        extracted = backfill_extracted(extracted, prior, prior_matches, matches, resolved_drops)
        # extracted is now the BACKFILLED version; validate/decide/calc use it.

    # Phase 3 — validate on BACKFILLED extracted.
    # resolved_drops= receives suppress_detection (ALL answered fields) for N8 suppression.
    # raw_field_drops= receives pre-computed drops from Phase 1 (detect on raw).
    # Note: resolved_drops (the backfill-skip set) is NOT forwarded here — it only goes
    # to backfill_extracted above (TWO-SET MODEL, D-7.5-11).
    issues = validate(
        extracted,
        roster,
        matches,
        prior=prior,
        prior_matches=prior_matches,
        resolved_drops=suppress_detection,
        raw_field_drops=raw_drops,
    )

    decision = decide(extracted, matches, issues)  # pure: no llm, no score (D-21-01)

    # D-9-04: _compute_line_items is pure computation (no DB, no LLM) — it MUST run
    # BEFORE the transaction opens so a calc exception (e.g. WR-01 integrity-violation
    # raise) never opens a doomed transaction. Computed unconditionally here (cheap,
    # pure) and only USED below on the process branch — this keeps the persist
    # transaction's body free of anything that can raise for a business reason.
    line_items = None
    if decision.final_action == "process":
        line_items = _compute_line_items(run_id, extracted, matches, roster)

    # --- persist DATA on EVERY run BEFORE branching (D-A3-05); OVERWRITES on resume ---
    # D-9-04: one atomic transaction covers persist_extracted/persist_decision/
    # persist_reconciliation and — on the process branch only —
    # replace_line_items/set_status(COMPUTED)/set_status(AWAITING_APPROVAL), with the
    # status-advance LAST (D-9-02). A crash anywhere inside this block rolls back
    # every write in it, including the persists that "already succeeded" before the
    # crash — never just the later ones (D-9-14 fault-injection target).
    with repo.get_connection() as conn:
        with conn.transaction():
            repo.persist_extracted(run_id, extracted, conn=conn)
            repo.persist_decision(run_id, decision, conn=conn)  # data-only (FIX B)
            repo.persist_reconciliation(run_id, matches, conn=conn)  # never NULL on a clean run

            if decision.final_action == "process":
                repo.replace_line_items(run_id, line_items, conn=conn)  # DELETE-by-run then insert
                repo.set_status(run_id, RunStatus.COMPUTED, conn=conn)
                repo.set_status(run_id, RunStatus.AWAITING_APPROVAL, conn=conn)  # HITL-01 pause
    # --- transaction block closed above; `_clarify` (an LLM+provider call) is a
    # SIBLING statement here, never nested inside the `with conn.transaction():`
    # block (D-9-01 — no transaction may span a network/LLM call). ---

    # --- branch SOLELY on final_action (the code-owned deterministic decision) ---
    clarify_deferred = False
    if decision.final_action == "process":
        clarify_deferred = False
    else:  # request_clarification
        # R3-2 fix: defer whenever ANY field_regression issue exists.
        # A mixed-issue email (field_regression + unresolved name) defers under
        # purpose='clarification_field_regression' so the idempotency check uses
        # the correct purpose and the prior 'clarification' row doesn't suppress the send.
        has_field_regression = any(i.issue_type == "field_regression" for i in issues)
        if has_field_regression:
            # Defer: resume_pipeline will write 'asked' BEFORE calling _clarify (N2).
            clarify_deferred = True
        else:
            # Non-field-regression clarification: call _clarify immediately (normal path).
            # D-9-05: this is a sibling statement AFTER the persist transaction closes,
            # never nested inside it — _clarify performs two LLM calls + a provider send.
            _clarify(run_id, email, decision, roster, extracted, llm=llm, purpose="clarification")
            clarify_deferred = False

    return _RunStagesResult(clarify_deferred=clarify_deferred, matches=matches, issues=issues)


def _clarify(run_id, email, decision, roster, extracted, *, llm, purpose="clarification") -> None:
    """Draft a clarification, stub-send it, and pause the run at AWAITING_REPLY.

    The cheap DRAFT_* tier drafts the body (templated fallback on empty content so
    a draft failure never strands the run, CLAR-01). gateway.send_outbound mints a
    synthetic Message-ID and records it on the linked
    email_messages(direction='outbound', run_id) row — the SINGLE canonical anchor
    Plan 04 reads back via the header chain (FIX 3); there is NO payroll_runs
    Message-ID column. Status advances via repo.set_status (the sole writer, FIX B).
    The clarification threads off the client's inbound message_id (In-Reply-To +
    References) so the reply chain resolves in Plan 04.

    extracted: the pre-clarify extraction snapshot (N7 fix — passed to
    set_pre_clarify_extracted before each AWAITING_REPLY path so the snapshot is
    durably persisted at the first clarification send, not overwritten on re-trigger).
    The IS NULL guard in set_pre_clarify_extracted makes all three calls idempotent.

    purpose: 'clarification' (default) or 'clarification_field_regression' (R3-2 fix —
    get_outbound_message_id idempotency check uses the purpose kwarg so a prior plain
    'clarification' row does NOT suppress the field-regression send).

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
    # on re-trigger. The purpose kwarg distinguishes this from a confirmation row
    # and from a field-regression clarification (R3-2 fix: purpose variable used here,
    # not hardcoded 'clarification').
    existing_clari = repo.get_outbound_message_id(run_id, purpose=purpose)
    if existing_clari is not None:
        logger.info(
            "clarification already sent for run %s (purpose=%r) — skipping duplicate send "
            "(finding #2, CLAR-04)",
            run_id,
            purpose,
        )
        # N7 fix: snapshot BEFORE AWAITING_REPLY (PATH 1: idempotency early-return).
        # IS NULL guard in set_pre_clarify_extracted makes this a no-op if already set.
        # D-9-06: both writes commit as one transaction, status-advance last (D-9-02).
        with repo.get_connection() as conn:
            with conn.transaction():
                repo.set_pre_clarify_extracted(run_id, extracted, conn=conn)
                repo.set_status(run_id, RunStatus.AWAITING_REPLY, conn=conn)
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
            purpose=purpose,
            send_state="sent",
        )
        # N7 fix: snapshot BEFORE AWAITING_REPLY (PATH 2: record_only).
        # IS NULL guard in set_pre_clarify_extracted makes this idempotent.
        # D-9-06: insert_email_message (the intent-recording write, no real Resend
        # call) stays OUTSIDE this transaction (D-9-01) — this block covers only
        # what comes strictly after it, status-advance last (D-9-02).
        with repo.get_connection() as conn:
            with conn.transaction():
                repo.set_pre_clarify_extracted(run_id, extracted, conn=conn)
                repo.set_status(run_id, RunStatus.AWAITING_REPLY, conn=conn)
        return
    # else: live Path-2 run — fall through to the real Resend gateway call (unchanged)
    gateway.send_outbound(
        run_id=run_id,
        to_addr=email.from_addr,
        subject=clarification_subject(email.subject),
        body=body,
        in_reply_to=email.message_id,
        references_header=email.message_id,
        purpose=purpose,
        send_state="sent",
    )
    # N7 fix: snapshot BEFORE AWAITING_REPLY (PATH 3: live gateway).
    # IS NULL guard in set_pre_clarify_extracted makes this idempotent.
    # D-9-06/D-9-01: gateway.send_outbound (the provider call) has ALREADY returned
    # above — this transaction opens strictly AFTER it, covering only the writes
    # that come after the send, status-advance last (D-9-02).
    with repo.get_connection() as conn:
        with conn.transaction():
            repo.set_pre_clarify_extracted(run_id, extracted, conn=conn)
            repo.set_status(run_id, RunStatus.AWAITING_REPLY, conn=conn)  # CLAR-01 pause


def _write_aliases_if_safe(run_id: uuid.UUID, run: dict, roster, conn=None) -> None:
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

    conn: optional caller-supplied connection (D-9-04 series) so this call's writes
    join the caller's enclosing transaction (e.g. _deliver's finalize block) rather
    than auto-committing independently. When None (default), each internal repo call
    opens/commits its own pooled connection, exactly as before this plan.
    """
    import uuid as _uuid
    run_data = repo.load_run(run_id, conn=conn)
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

        written = repo.update_known_alias(employee_id, token, conn=conn)
        if written:
            logger.info("alias learned: %r → %s", token, employee_id)
            # BATCH-SAFE: refresh the roster after each accepted write so the next
            # iteration validates against the updated roster state (MEDIUM finding).
            current_roster = repo.load_roster_for_business(run["business_id"], conn=conn)
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
    #
    # gateway.send_outbound already durably flips send_state to 'sent' before returning
    # (D-13c) — this guard's job on a retry-over-sent is to ensure alias learning,
    # which the happy path performs BEFORE advancing status, is not silently skipped
    # just because the send itself was already durable (Codex HIGH-2 fix); the alias
    # write is idempotent-safe to attempt again (write-only-if-unambiguous-and-new,
    # per D-01/D-02) — it will no-op on a second attempt if the alias was already
    # learned.
    existing = repo.get_outbound_message_id(run_id, purpose="confirmation")
    if existing is not None:
        logger.info(
            "confirmation already sent for run %s (%s) — advancing to SENT+RECONCILED "
            "without duplicate send (finding #1, CLAR-04)",
            run_id,
            existing,
        )
        # D-9-08/Codex HIGH-2: the retry-over-sent path needs a roster (this
        # early-return path returns before Step 4's roster load below) to attempt
        # the same idempotent alias write the happy path performs — isolated in its
        # own try/except (mirroring D-13b) since this branch is NOT nested inside
        # the WR-04 try (it returns before that try opens).
        existing_roster = repo.load_roster_for_business(run["business_id"])
        try:
            _write_aliases_if_safe(run_id, run, existing_roster)
        except Exception as alias_exc:  # noqa: BLE001 — D-13b defensive isolation
            logger.warning(
                "alias write skipped for run %s: %s (run continues to SENT)",
                run_id,
                type(alias_exc).__name__,
            )
        with repo.get_connection() as conn:
            with conn.transaction():
                repo.set_status(run_id, RunStatus.SENT, conn=conn)
                repo.set_status(run_id, RunStatus.RECONCILED, conn=conn)
        return

    # Step 2 — Load line items (explicit columns, LOW finding fix).
    paystubs = repo.load_line_items(run_id)

    # Step 3 — Compose the confirmation email body (D-10b hard timeout passed).
    body = compose_confirmation(paystubs, run, timeout_s=3.0)

    # Step 4 — Load roster for employee full names (needed for PDF header).
    roster = repo.load_roster_for_business(run["business_id"])
    emp_by_id = {str(e.id): e for e in roster.employees}

    # WR-04 (phase-8 review): steps 5-10 interpolate roster names (PDF headers,
    # compose/gateway payloads), so an exception raised past this point can carry
    # employee full names in str(exc). Stash the ALREADY-LOADED in-memory roster
    # on the exception and re-raise unchanged — the approve() error boundary reads
    # it via getattr and passes it to record_run_error so _scrub can redact the
    # names. D-8-01b is preserved: the error path never LOADS a roster (forbidden);
    # it only forwards the object this happy path already had in scope. _deliver's
    # contract is also preserved: it still raises freely and never swallows.
    try:
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

        # Steps 8-10 — D-9-07/D-9-08: the email row's send_state flip to 'sent'
        # already committed inside gateway.send_outbound (D-13c) before this
        # transaction opens — this block covers ONLY what remains atomic on this
        # side: alias learning + status advance. A crash between send_outbound's
        # return and this transaction's commit leaves send_state='sent' +
        # status='approved'; a retry hits the hardened already-sent guard above,
        # which completes the alias write and advances status — this is D-9-08's
        # documented at-least-once semantics, now closing the alias-skip gap
        # Codex HIGH-2 found.
        with repo.get_connection() as conn:
            with conn.transaction():
                # Step 8 — Alias write (D-01, D-02): learn any unambiguous alias
                # candidates. MUST be called BEFORE set_status(SENT) (PATTERNS.md
                # line 611 ordering, D-13b). Wrapped in try/except NESTED STRICTLY
                # INSIDE this transaction block (Pitfall 2) so an alias-learning
                # failure NEVER rolls back a genuine delivery — it only skips the
                # alias write itself (D-13b defensive isolation, D-15).
                #
                # D-9-06 gap closure (WR-01): the nested `with conn.transaction()`
                # below is a psycopg3 SAVEPOINT (psycopg3 automatically issues
                # SAVEPOINT/RELEASE SAVEPOINT/ROLLBACK TO SAVEPOINT instead of
                # BEGIN/COMMIT/ROLLBACK when conn.transaction() is entered while
                # already inside an outer transaction). This is what makes the
                # isolation hold for genuine DB-level errors (constraint violations,
                # undefined columns, lock timeouts), not just pure-Python exceptions
                # — without it, a DB-level failure here poisons the WHOLE outer
                # transaction via InFailedSqlTransaction on the very next statement
                # (09-REVIEW.md WR-01): the alias write's own repo helpers run under
                # _nulltx() (a bare no-op) whenever a caller-supplied conn is
                # present, so no savepoint exists at that layer — it must be added
                # by the caller (here), wrapping the whole alias-write call once.
                try:
                    with conn.transaction():
                        _write_aliases_if_safe(run_id, run, roster, conn=conn)
                except Exception as alias_exc:  # noqa: BLE001 — D-13b defensive isolation
                    logger.warning(
                        "alias write skipped for run %s: %s (run continues to SENT)",
                        run_id,
                        type(alias_exc).__name__,
                    )

                # Steps 9-10 — Advance the run: SENT → RECONCILED (both sequential
                # in this synchronous call; RECONCILED is the only terminal-success
                # status). Status-advance last (D-9-02).
                repo.set_status(run_id, RunStatus.SENT, conn=conn)
                repo.set_status(run_id, RunStatus.RECONCILED, conn=conn)
    except Exception as exc:
        # WR-04: attach the in-memory roster for the caller's scrub boundary, then
        # re-raise the ORIGINAL exception unchanged. Attribute assignment is
        # best-effort (suppress) — an exception type rejecting attributes must
        # never mask the real delivery failure.
        with contextlib.suppress(Exception):
            exc.payroll_roster = roster
        raise


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
