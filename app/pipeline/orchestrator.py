"""The plain-Python run state machine: drives one payroll run through its stages.

`run_pipeline(run_id)` loads the run and roster, executes the four PURE judgment
stages in order, persists Extracted + Decision + per-name reconciliation on EVERY
run, then branches SOLELY on `Decision.final_action`. Postgres `payroll_runs.status`
is the durable checkpoint; there is no graph framework and no autonomous loop.

Invariants this module exists to hold:

- **The decision is code-owned.** `decide.py` makes no model call and reads no score,
  so there is no advisory model action for the orchestrator to diverge from. This
  module never branches on model output — only on `final_action`.
- **Data writes and status writes are separate.** The `persist_*` helpers write DATA
  ONLY; state advances exclusively through `repo.set_status`, which is the sole status
  writer. A clean run reaching `awaiting_approval` therefore never leaves reconciliation
  NULL.
- **Failures cross one bounded boundary.** Both entry points return `PipelineResult`
  values classified by their active stage. They never persist terminal state themselves;
  background wrappers and the durable drain each own exactly one settlement path.
- **The run_id is never model-supplied.** `extract(..., run_id=run_id, ...)` stamps the
  code-owned run id onto the result.

`resume_pipeline(run_id, inbound)` re-enters a paused run at extraction idempotently
and losslessly: it rebuilds the extraction context from the ORIGINAL cleaned inbound
body plus the clarification reply, so employees and hours the client did not restate
in the reply are retained rather than dropped. Both entry points funnel through the
shared `_run_stages()` spine, so the first run and every resume traverse the exact
same gate path and the eval can score that same spine.

Module layout: the alias-learning rule set lives in `alias_learning.py`, the clarify
cluster in `clarification.py`, and confirmation delivery in `delivery.py`. Those two
collaborators are imported as module objects (not as bare functions) so a test that
monkeypatches an attribute patches the owning module, and the seam stays where the
code lives.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from app.db import repo
from app.models.contracts import (
    Extracted,
    ExtractedEmployee,
    HoursChange,
    InboundEmail,
    PaystubLineItem,
)
from app.models.roster import NameMatchResult, Roster, ValidationIssue
from app.models.status import RunStatus
from app.pipeline import alias_learning, clarification
from app.pipeline.calculate import calculate
from app.pipeline.decide import decide
from app.pipeline.extract import extract
from app.pipeline.reconcile_names import reconcile_names
from app.pipeline.result import (
    PipelineOutcome,
    PipelineResult,
    PipelineStage,
    classify_pipeline_exception,
)
from app.pipeline.validate import (
    HOURS_FIELDS,
    detect_field_regression,
    detect_hours_changes,
    is_paid,
    validate,
)

logger = logging.getLogger("payroll_agent.orchestrator")


@dataclass
class _RunStagesResult:
    """The minimal handoff from _run_stages back to its caller.

    Carries exactly what resume_pipeline needs — clarify_deferred, matches, issues —
    and deliberately NOT the extracted data: _run_stages has already persisted that,
    and the caller that needs the raw extraction captured it before the call.

    clarify_deferred=True means at least one field_regression issue exists, so the
    clarification send is deferred; resume_pipeline must write the 'asked' outcomes
    BEFORE the email goes out, or a reply could arrive against a question whose state
    was never recorded.
    """

    clarify_deferred: bool = False
    matches: list[NameMatchResult] | None = None
    issues: list[ValidationIssue] | None = None


@dataclass
class _StageTracker:
    """Mutable bounded stage shared with the outer exception boundary."""

    active: PipelineStage = PipelineStage.LOAD


_OK_RESULT = PipelineResult(outcome=PipelineOutcome.OK)


def backfill_extracted(
    extracted: Extracted,
    snapshot: Extracted | None,
    prior_matches: list[NameMatchResult] | None,
    matches: list[NameMatchResult] | None,
    resolved_drops: set[tuple[str, str]] | None,
) -> Extracted:
    """Fill fields the client went silent on from the pre-clarify snapshot.

    Pure function: no DB calls, operates on Pydantic-validated Extracted objects.

    Keyed by employee_id on BOTH sides, never by submitted name:
    - snapshot side: employee_id resolved via prior_matches (the snapshot round's
      reconciliation)
    - current side: employee_id resolved via matches (this round's reconciliation)
    So "M. Chen" (prior) and "Maria Chen" (current) — same employee — land in the same
    backfill slot. Keying by name instead would miss the carry-forward whenever the
    client restates a name differently, paying 0 for a field they meant to keep
    (underpay).

    resolved_drops: set[(employee_id_str, field)] — fields to SKIP backfilling. It holds
    ONLY the confirmed_dropped and client_supplied outcomes, never carried_forward:
    - confirmed_dropped MUST be here. `is_paid(Decimal('0'))` is False, so a client's
      explicit zero looks backfillable by value alone; this gate is the only thing
      stopping the snapshot's positive value from being silently restored (overpay).
    - carried_forward MUST be absent, so backfill actually fires and restores the
      snapshot value the client chose to leave unstated.

    The separate "suppress detection" set is not passed here — it goes to validate()
    only. Conflating the two is what produces either an overpay or an infinite
    re-clarification loop.

    Returns a new Extracted (copy with silence fields filled from the snapshot).
    """
    if snapshot is None:
        return extracted  # no snapshot → no backfill (safe no-op)

    # Employee-id-keyed on BOTH sides.
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
            id_to_snapshot_emp[emp_id_str] = emp  # last-wins

    if not id_to_snapshot_emp:
        # prior_matches empty or none resolved → no backfill (safe no-op)
        return extracted

    # Build name_to_id_current: {submitted_name: employee_id_str} from current matches.
    name_to_id_current: dict[str, str] = {
        m.submitted_name: str(m.matched_employee_id)
        for m in (matches or [])
        if m.resolved and m.matched_employee_id is not None
    }

    _resolved_drops: set[tuple[str, str]] = resolved_drops or set()

    # Build the updated employees list.
    new_employees: list[ExtractedEmployee] = []
    for emp in extracted.employees:
        emp_id_str = name_to_id_current.get(emp.submitted_name)  # may be None if unresolved
        snap_emp = id_to_snapshot_emp.get(emp_id_str) if emp_id_str else None

        if snap_emp is None:
            # No snapshot match by employee_id → keep emp as-is, no backfill possible.
            new_employees.append(emp)
            continue

        # Build a dict of field values for the new ExtractedEmployee.
        emp_dict = emp.model_dump()
        for field in HOURS_FIELDS:
            current_val = getattr(emp, field)
            if not is_paid(current_val):
                # Silence or explicit zero — check whether to backfill.
                snap_val = getattr(snap_emp, field)
                if is_paid(snap_val):
                    # Snapshot had a value — eligible for carry-forward.
                    if emp_id_str is not None and (emp_id_str, field) in _resolved_drops:
                        # The client already resolved this field, so the snapshot must NOT
                        # overwrite their answer:
                        #   confirmed_dropped → they explicitly zeroed it; honor the zero.
                        #   client_supplied   → they gave a value; use the extracted value.
                        # Restoring the snapshot here would overpay.
                        pass
                    else:
                        # Client went silent → carry the snapshot value forward.
                        emp_dict[field] = snap_val
        new_employees.append(ExtractedEmployee(**emp_dict))

    return Extracted(
        run_id=extracted.run_id,
        employees=new_employees,
        pay_period_start=extracted.pay_period_start,
        pay_period_end=extracted.pay_period_end,
    )


def run_pipeline(run_id: uuid.UUID, *, llm: Any = None) -> PipelineResult:
    """Drive one run from received → awaiting_approval (or awaiting_reply on a clarification).

    `llm` is the client module the stages call; defaults to each stage's own
    bound client. Tests inject a mocked client by patching app.llm.client.OpenAI.

    Deliberately a thin, non-raising delegator: the classification boundary lives inside
    `_run`, which returns one bounded outcome on every path.
    """
    return _run(run_id, llm=llm)


def _run(run_id: uuid.UUID, *, llm: Any) -> PipelineResult:
    """Load and execute a run, reducing every exception to a bounded result."""
    stage = _StageTracker()
    try:
        stage.active = PipelineStage.LOAD
        run = repo.load_run(run_id)
        if run is None:
            raise ValueError(f"run {run_id} not found")

        email = repo.load_inbound_email(run_id)
        if email is None:
            raise ValueError(f"run {run_id} has no source email")
        roster = repo.load_roster_for_business(run["business_id"])

        stage.active = PipelineStage.PERSIST
        repo.set_status(run_id, RunStatus.EXTRACTING)
        # discard return — first run, no field-regression
        _ = _run_stages(run_id, email, roster, llm=llm, stage_tracker=stage)
        return _OK_RESULT
    except Exception as exc:  # noqa: BLE001 — one bounded producer catch boundary
        result = classify_pipeline_exception(stage.active, exc)
        logger.warning("run %s failed: %s", run_id, result.diagnostic_code)
        return result


def resume_pipeline(
    run_id: uuid.UUID,
    inbound: InboundEmail | None = None,
    *,
    llm: Any = None,
    from_status: RunStatus = RunStatus.AWAITING_REPLY,
    overrides: dict[str, str] | None = None,
) -> PipelineResult:
    """Re-enter a paused run at extraction — on a clarification reply, or on an
    operator's needs_operator resolve+resume action.

    Idempotent AND lossless:
      - The extraction CONTEXT is rebuilt from the ORIGINAL cleaned inbound body
        (repo.load_source_email — persisted cleaned at ingest, NOT re-cleaned) +
        the clarification reply body (inbound.body_text). Because the original body
        is included, employees/hours not mentioned in the reply are RETAINED; dropping
        them would pay only the employees the client happened to restate.
      - extract() is passed the run's CODE-OWNED run_id; the model returns only an
        ExtractionPayload and extract stamps the trusted run_id.
      - persist_extracted OVERWRITES extracted_data wholesale (one JSONB cell, never
        appended); replace_line_items DELETEs by run then inserts. So a re-trigger is
        safe and a resume never accumulates stale data.

    The webhook is the sole caller of the default (from_status=AWAITING_REPLY,
    inbound=<the reply>) path, and only invokes it after BOTH the header-chain
    match (awaiting_reply only) AND the reply-sender revalidation have passed.

    Operator resume shares this one path rather than getting a parallel implementation:
    the `/runs/{run_id}/resolve` route calls this with `from_status=
    RunStatus.NEEDS_OPERATOR` and `inbound=None`. When `inbound` is None there is no NEW
    reply to consume — the "current reply" section of the combined extraction context is
    simply absent (a synthetic empty-body InboundEmail is substituted so the shared
    context-accumulation code stays byte-identical for both callers; the ORIGINAL body
    plus ALL already-consumed replies still populate the context in full).
    `overrides` (submitted_name -> employee_id_str) is threaded straight to
    `_run_stages(overrides=...)` so the operator's server-validated mapping resolves
    deterministically before reconcile_names's exact/alias tiers.

    Status gate: uses repo.claim_status(from_status → EXTRACTING) — an atomic conditional
    UPDATE. A load-then-check-then-set pattern leaves a window where a second reply (or an
    operator approval) can arrive between the status load and the EXTRACTING write, and
    both would then run the run; claim_status's `WHERE status=%s RETURNING id` makes the
    check-and-transition atomic. The losing concurrent caller gets False and drops
    cleanly — no re-run, no ERROR route.
    """
    stage_tracker = _StageTracker()
    try:
        # Atomic compare-and-swap: claim the run from from_status → EXTRACTING.
        # A duplicate or late reply/resolve sees claim=False and drops cleanly — no
        # re-run, no error.
        stage_tracker.active = PipelineStage.PERSIST
        claimed = repo.claim_status(run_id, from_status, RunStatus.EXTRACTING)
        if not claimed:
            logger.info(
                "resume aborted: run %s claim failed from %s — late/duplicate "
                "reply/resolve dropped",
                run_id,
                from_status,
            )
            return _OK_RESULT

        # Operator resume has no NEW reply to consume — substitute a synthetic empty-body
        # InboundEmail so every downstream line that reads `inbound.message_id` /
        # `inbound.body_text` (mark_reply_consumed, the prior_replies exclusion filter,
        # combined_context_email) stays exactly the same code path for both callers.
        # mark_reply_consumed is a no-op for a synthetic message_id that was never
        # persisted as an inbound row (the real repo's UPDATE simply matches zero rows;
        # InMemoryRepo's mirror looks up self.emails and finds nothing) — there is nothing
        # to consume when there is no real reply, by construction.
        _operator_resume = inbound is None
        if _operator_resume:
            inbound = InboundEmail(
                id=uuid.uuid4(),
                message_id=f"<operator-resume-{run_id}@payroll-agent.local>",
                in_reply_to=None,
                references_header=None,
                subject="",
                from_addr="",
                to_addr="",
                body_text="",
                created_at=datetime.now(UTC),
            )
        assert inbound is not None

        # Write the consumed marker the INSTANT processing actually starts (immediately
        # after the winning CAS claim, before anything else runs). This is the READ side of
        # the clarification round machine and belongs HERE — not in clarify, which owns the
        # send-side round counter only. mark_reply_consumed is write-once (guarded on
        # `consumed_round IS NULL`), so a duplicate/redelivered claim that somehow still
        # reaches this line cannot overwrite an already-recorded round. This single UPDATE
        # stands OUTSIDE any LLM/provider transaction — it does not join the classify/extract
        # work below. Without this write, load_consumed_replies returns empty forever and the
        # multi-round context accumulation below is a runtime no-op, even though hermetic
        # tests seeded with fake consumed rows would still pass.
        stage_tracker.active = PipelineStage.PERSIST
        repo.mark_reply_consumed(
            inbound.message_id, round=repo.get_clarification_round(run_id)
        )

        # load_run is still needed for business_id and other metadata.
        stage_tracker.active = PipelineStage.LOAD
        run = repo.load_run(run_id)
        if run is None:
            raise ValueError(f"run {run_id} not found after claim")
        roster = repo.load_roster_for_business(run["business_id"])

        # Alias binding, step A: load alias_candidates and the pre-resume reconciliation
        # BEFORE _run_stages — needed for the pending-token lookup below and for the
        # prior_matches deserialization in step E0.
        #
        # The bind decision deliberately does NOT diff a pre-resolved-id SET against a
        # post-resolved-id SET. That whole-run diff is exactly what let an UNRELATED
        # reconciliation entry satisfy a bind (see alias_learning.bind_evidence_for_token):
        # it would learn an alias nobody confirmed. Only _pre_candidates and
        # _pre_reconciliation are needed here.
        pre_run_data = repo.load_run(run_id)
        _pre_candidates = (pre_run_data.get("alias_candidates") or {}) if pre_run_data else {}
        _pre_reconciliation = (pre_run_data.get("reconciliation") or []) if pre_run_data else []

        # Step B: the classify-first / three-phase-detection block for a resumed run.

        # Step E0: deserialize prior_matches from the persisted reconciliation.
        # Empty list on the first-ever resume (no prior reconciliation); [] makes
        # detect_field_regression return [] — correct, since there are no drops to detect
        # without a prior run.
        prior_matches: list[NameMatchResult] = [
            NameMatchResult.model_validate(m)
            for m in _pre_reconciliation
            if isinstance(m, dict)
        ]

        # Step E1: Load snapshot and clarified state.
        snapshot = repo.load_pre_clarify_extracted(run_id)    # None on first resume
        clarified = repo.load_clarified_fields(run_id)          # {} on first resume

        # Rebuild the combined extraction context: ORIGINAL body + a code-owned
        # "QUESTIONS WE ASKED" anchor + ALL consumed prior replies in round order + the
        # current reply. The anchor and the accumulation are built from persisted
        # decision/clarified_fields facts, never from the LLM-drafted outbound body — the
        # model's own prose is not a trustworthy record of what we asked.
        original_body = repo.load_source_email(run_id) or ""
        from app.models.contracts import Decision as _Decision

        _pre_decision = (
            _Decision.model_validate(pre_run_data["decision"])
            if pre_run_data and pre_run_data.get("decision")
            else None
        )
        asked_summary_lines = clarification.render_asked_summary(_pre_decision, clarified)
        # prior_replies = every OTHER consumed reply for this run, in round order. The reply
        # THIS call is processing was just marked consumed above — exclude it by message_id
        # so it is never duplicated as both a prior entry and the current reply.
        _consumed_rows = repo.load_consumed_replies(run_id)
        prior_replies = [
            row["body_text"]
            for row in _consumed_rows
            if row.get("message_id") != inbound.message_id
        ]
        combined_email = clarification.combined_context_email(
            inbound,
            original_body,
            asked_summary_lines=asked_summary_lines,
            prior_replies=prior_replies,
        )

        # Step E2: build the prior-terminal sets from the already-clarified outcomes.
        # KEY TYPE: (employee_id_str, field) — NOT (submitted_name, field), because a
        # client who restates a name differently must still hit the same key.
        # clarified.items() already yields emp_id_str keys — no reverse lookup needed.
        #
        # The three terminal outcomes split across the two downstream sets differently, so
        # they are collected into TWO distinct sets here:
        #   _resolved_by_name      — confirmed_dropped + client_supplied. Seeds BOTH the
        #                            suppress-detection set and the backfill-skip set.
        #   _prior_carried_forward — carried_forward. Seeds suppress-detection ONLY, so a
        #                            prior-round carried_forward field cannot be re-detected
        #                            as the same paid→absent drop in a later round (which
        #                            would flip the terminal back to 'asked' and re-ask
        #                            forever). It must NEVER reach backfill-skip:
        #                            carried_forward fields stay backfillable from the
        #                            snapshot, and skipping them would pay 0 for a field the
        #                            client said to carry forward (underpay).
        _resolved_by_name: set[tuple[str, str]] = set()
        _prior_carried_forward: set[tuple[str, str]] = set()
        for emp_id_str, field_outcomes in clarified.items():
            for field, outcome in field_outcomes.items():
                if outcome in ("confirmed_dropped", "client_supplied"):
                    _resolved_by_name.add((emp_id_str, field))
                elif outcome == "carried_forward":
                    _prior_carried_forward.add((emp_id_str, field))

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
                overrides=overrides,      # operator mapping, else None
                alias_candidates=_pre_candidates,  # the identity bridge (see _run_stages)
                stage_tracker=stage_tracker,
            )
            # NOTE: no extracted= kwarg on Round-1. _run_stages calls extract() internally.

            if stage.clarify_deferred:
                # The shared helper writes 'asked', persists, and only THEN sends the
                # clarification_field_regression email — the ordering that guarantees a fast
                # reply can never arrive against an unrecorded question. Factored out so the
                # Round-1 and Round-2 paths cannot drift apart.
                stage_tracker.active = PipelineStage.CLARIFICATION
                clarification.defer_field_regression_clarification(
                    run_id, clarified, stage, combined_email, roster, llm=llm
                )
                return _OK_RESULT  # do not fall through to alias binding

            # stage.clarify_deferred is False: fall through to the alias-binding steps.

        # Step E5: Round-2 path — classify-first (answered rounds).
        else:
            # TWO separate extractions, for two different purposes.
            #
            # CLASSIFY needs the REPLY IN ISOLATION so that:
            #   - silence (field absent from reply) → None → carried_forward
            #   - explicit zero ("0 overtime") → Decimal('0') → confirmed_dropped
            # Classifying from combined_email instead lets the original section's positive
            # value (e.g. OT=2) survive into the extraction and eclipse the reply's
            # "0 overtime" → the field is classified client_supplied with raw_val=2 →
            # OVERPAY.
            #
            # PROCESS/BACKFILL needs the COMBINED body so original employees/hours the
            # client did not restate are retained (lossless combined extraction).
            #
            # Cost: one extra LLM call on answered rounds — acceptable for money-safety.
            extract_kwargs_r2 = {"run_id": run_id}
            if llm is not None:
                extract_kwargs_r2["llm"] = llm

            # Extraction 1 (CLASSIFY): reply body ONLY — uncombined.
            # `inbound` is the raw reply InboundEmail BEFORE combination (resume_pipeline param).
            # Use it directly so the classify step sees ONLY what the client said in the reply.
            stage_tracker.active = PipelineStage.EXTRACT
            raw_reply_extracted = extract(inbound, roster, **extract_kwargs_r2)

            # Extraction 2 (PROCESS/BACKFILL): combined body — retains original employees/hours.
            stage_tracker.active = PipelineStage.EXTRACT
            raw_extracted = extract(combined_email, roster, **extract_kwargs_r2)

            # STEP 1: CLASSIFY the raw REPLY (reply-only) for asked fields ONLY.
            # Do NOT classify all snapshot-paid fields — that mislabels untouched fields
            # (e.g. an hours_regular that was always present) as client_supplied.
            # Only fields currently 'asked' get classified.
            #
            # Build the classify lookup from the UNION of current matches (reconcile the raw
            # reply's submitted names) AND prior_matches (snapshot names). Prior-only keying
            # misses restated names: if the snapshot had "M. Chen" but the reply says
            # "Maria Chen", the current name is absent from a prior-only lookup → raw_emp
            # stays None → the field stays 'asked' → it is absent from the backfill-skip set
            # → the snapshot's positive value is silently restored (OVERPAY). The union
            # ensures the reply's current submitted names are always covered.
            #
            # Order matters: prior_matches go FIRST, current_matches_for_classify LAST. The
            # dict comprehension is last-wins, so current overrides prior for any shared
            # submitted_name — "current wins", i.e. a restated name takes the CURRENT
            # resolution. Reversing the order silently makes it prior-wins.
            stage_tracker.active = PipelineStage.COMPUTE
            raw_reply_submitted = [e.submitted_name for e in raw_reply_extracted.employees]
            current_matches_for_classify = reconcile_names(raw_reply_submitted, roster)
            name_to_id_for_classify: dict[str, str] = {
                m.submitted_name: str(m.matched_employee_id)
                for m in (list(prior_matches) + list(current_matches_for_classify))
                if m.resolved and m.matched_employee_id is not None
            }
            # Build a lookup from raw_reply_extracted: {submitted_name: ExtractedEmployee}.
            # This uses the REPLY-ONLY extraction, so silence really is None rather than the
            # original body's value.
            raw_name_to_emp = {emp.submitted_name: emp for emp in raw_reply_extracted.employees}

            # Staging set for asked fields that cannot be resolved in the raw reply. These
            # are absorbed into the backfill-skip set in STEP 2 so the failure mode is an
            # under-fill that re-clarifies next round, never a snapshot-restore overpay.
            _unresolvable_asked: set[tuple[str, str]] = set()

            # Capture the authoritative reply-derived value for every asked field at classify
            # time, so the COMBINED extraction can be overwritten with the correct value
            # before _run_stages ever sees it (STEP 2.5). Without this, the classify OUTCOME
            # and the PAID value can disagree.
            # Keys: (emp_id_str, field) — same namespace as newly_classified.
            # Values: the authoritative paid value the paystub MUST use for that field.
            #   client_supplied  → the positive Decimal the reply extraction returned
            #   confirmed_dropped → Decimal('0') (client explicitly zeroed; paired with the
            #                       backfill-skip set to block snapshot restore)
            #   carried_forward  → None (so the backfill phase fills from the snapshot; must
            #                       force None even if the combined extraction carried a
            #                       possibly-wrong positive value)
            #   unresolvable      → None (field genuinely absent; prevents the combined value
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
                        # This employee cannot be resolved in the raw reply even after the
                        # union lookup — fail conservatively. Stage the pair in
                        # _unresolvable_asked so STEP 2 adds it to the backfill-skip set;
                        # the field is then NEVER re-backfilled from the snapshot. Worst
                        # case is an under-fill that re-clarifies next round. This is what
                        # prevents a snapshot-restore overpay on any asked field the classify
                        # step cannot resolve.
                        _unresolvable_asked.add((emp_id_str, field))
                        # Force None so the combined extraction's value for this field cannot
                        # leak through to the paystub (money-safe under-fill).
                        reply_value_overrides[(emp_id_str, field)] = None
                        continue

                    raw_val = getattr(raw_emp, field, None)
                    # Classify from the RAW reply, before any backfill can mask the answer.
                    if raw_val is not None and raw_val > 0:
                        # Present-positive in raw reply → client supplied a value.
                        clarified[emp_id_str][field] = "client_supplied"
                        # The client's supplied value is authoritative — it overrides whatever
                        # the combined extraction returned.
                        reply_value_overrides[(emp_id_str, field)] = raw_val
                    elif raw_val is not None and raw_val == Decimal("0"):
                        # Explicit Decimal('0') in raw reply → client explicitly zeroed.
                        clarified[emp_id_str][field] = "confirmed_dropped"
                        # Force the explicit zero, paired with the backfill-skip set so the
                        # snapshot value is not restored by the backfill phase either.
                        reply_value_overrides[(emp_id_str, field)] = Decimal("0")
                    else:
                        # None/absent in raw reply → client was silent → carry forward.
                        clarified[emp_id_str][field] = "carried_forward"
                        # Force None so the backfill phase can fill from the snapshot
                        # (carried_forward is NOT in the backfill-skip set → backfill FIRES).
                        # This must overwrite even when the combined extraction had a value:
                        # the combined body's positive value would otherwise eclipse the
                        # client's silence and the snapshot would never be consulted.
                        reply_value_overrides[(emp_id_str, field)] = None

                    newly_classified.add((emp_id_str, field))

            # STEP 2: build TWO DISTINCT sets. Conflating them is a money bug in both
            # directions, so they are constructed separately and never aliased.
            #
            # SET A — suppress_detection: ALL prior terminals + ALL answered asked fields.
            # = _resolved_by_name (prior confirmed_dropped + client_supplied)
            #   UNION _prior_carried_forward (prior carried_forward)
            #   UNION ALL newly_classified.
            # Purpose: stop detect_field_regression / validate from re-emitting
            # field_regression for any already-resolved or just-answered field. Passed to
            # _run_stages(suppress_detection=) → validate(resolved_drops=suppress_detection).
            # Does NOT reach backfill_extracted.
            # Why prior carried_forward must be here: within round N a carried_forward
            # outcome is protected by newly_classified, but in round N+1 it would be in
            # NEITHER set, so the same paid→absent drop is re-detected and the terminal flips
            # back to 'asked' — the client is asked the same question forever.
            suppress_detection: set[tuple[str, str]] = set(_resolved_by_name)
            suppress_detection.update(_prior_carried_forward)
            for pair in newly_classified:
                suppress_detection.add(pair)

            # SET B — backfill_skip: ONLY confirmed_dropped + client_supplied (NOT carried_forward).
            # = _resolved_by_name (prior confirmed_dropped + client_supplied)
            #   UNION newly-classified confirmed_dropped + client_supplied
            #   UNION _unresolvable_asked (conservative fail for unresolvable asked fields).
            # Purpose: tell backfill_extracted which fields to skip.
            # carried_forward (both prior-round via _prior_carried_forward and
            # newly-classified) is intentionally ABSENT: backfill FILLS those from the
            # snapshot. Adding them here would zero out a field the client said to carry
            # forward — underpay.
            # confirmed_dropped IS present: backfill skips it, so the paystub honors the
            # client's zero. `is_paid(Decimal('0'))` is False, so an explicit zero looks
            # backfillable by value alone; this set is the only protection against restoring
            # the snapshot's positive value — overpay.
            # _unresolvable_asked is folded in so an unclassifiable asked field is NEVER
            # re-backfilled from the snapshot. Fail conservatively.
            backfill_skip: set[tuple[str, str]] = set(_resolved_by_name)
            for emp_id_str, field in newly_classified:
                outcome = clarified.get(emp_id_str, {}).get(field)
                if outcome in ("confirmed_dropped", "client_supplied"):
                    backfill_skip.add((emp_id_str, field))
                # carried_forward: NOT added → backfill fires → snapshot value reaches the paystub
            backfill_skip.update(_unresolvable_asked)

            # STEP 2.5: reconcile the PAID value from the REPLY for every answered asked
            # field before passing raw_extracted to _run_stages.
            #
            # Problem: raw_extracted is the COMBINED extraction (original body + reply). The
            # combined body may carry the ORIGINAL section's value for an asked field (e.g.
            # OT=2 from the original payroll section), eclipsing the reply's answer (e.g.
            # "0 overtime"). The backfill-skip set only blocks a snapshot RESTORE inside
            # backfill_extracted — it has no power over a value the combined extraction
            # already carries. So the classify OUTCOME and the PAID value diverge whenever
            # the two extractions disagree on an asked field: the run is labelled
            # confirmed_dropped and still pays 2 hours of overtime.
            #
            # Fix: for every (emp_id_str, field) in reply_value_overrides, overwrite the field
            # in raw_extracted's matching employee so the paid value is the same value the
            # classify step decided.
            #
            # Employee-id mapping nuance: the override map is keyed by emp_id_str from the
            # REPLY extraction's reconciliation (name_to_id_for_classify), while the COMBINED
            # extraction's employees are keyed by submitted_name. A separate name→id map must
            # be built for the combined extraction to bridge the two namespaces correctly.
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
                        for field in HOURS_FIELDS:
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

            # STEP 3: call _run_stages ONCE with the TWO DISTINCT sets.
            # - extracted=raw_extracted: combined-body extraction (lossless, retains originals)
            # - suppress_detection: ALL answered fields → validate suppression only
            # - resolved_drops=backfill_skip: confirmed_dropped+client_supplied → backfill skip
            # - prior=snapshot, prior_matches=prior_matches_for_backfill: the detect→backfill→calc
            #   ordering
            #
            # Snapshot-name subtlety: prior_matches (loaded from the post-Round-1
            # reconciliation) reflects the REPLY names ("Maria Chen"), not the SNAPSHOT names
            # ("M. Chen"). backfill_extracted builds its snapshot lookup from prior_matches;
            # if the snapshot name is absent from prior_matches, no backfill occurs and the
            # paystub pays 0 for a field that should have carried forward (underpay). Fix:
            # also reconcile the SNAPSHOT's own submitted names and merge them in. The
            # snapshot names resolve via alias to the same employee_id, so "M. Chen" and
            # "Maria Chen" both map to the same employee and the backfill finds the snapshot
            # employee by employee_id.
            if snapshot is not None:
                snapshot_submitted = [e.submitted_name for e in snapshot.employees]
                snapshot_matches = reconcile_names(snapshot_submitted, roster)
                # Merge snapshot_matches FIRST, prior_matches LAST. backfill_extracted's
                # snapshot lookup is last-wins, so prior_matches (the persisted
                # snapshot-round reconciliation) overrides snapshot_matches for any shared
                # name — prior is the AUTHORITATIVE snapshot-round record, and this is the
                # INTENDED conflict resolution (both point to the same employee_id in the
                # normal case; prior wins when they disagree).
                prior_matches_for_backfill = list(snapshot_matches) + list(prior_matches)
            else:
                prior_matches_for_backfill = prior_matches

            # Persist the terminals BEFORE _run_stages, in their own closed transaction, so a
            # crash inside _run_stages' transaction cannot leave a stale 'asked' outcome
            # behind. The two writes are independently committed and independently
            # diagnosable, never coupled.
            #
            # The terminal outcomes finalized in STEP 1 above (client_supplied /
            # confirmed_dropped / carried_forward) are already fully resolved in-memory and
            # do NOT depend on _run_stages' return value — stage.clarify_deferred only gates
            # whether defer_field_regression_clarification ADDS new 'asked' entries for a NEW
            # regression found THIS round; it never touches the classify-first terminal
            # outcomes already in `clarified`. So persisting `clarified` here, before
            # _run_stages runs at all, is safe, and it mirrors the same invariant
            # defer_field_regression_clarification relies on: the state write commits and
            # closes strictly before any LLM/provider-touching call.
            stage_tracker.active = PipelineStage.PERSIST
            with repo.get_connection() as conn, conn.transaction():
                repo.set_clarified_fields(run_id, clarified, conn=conn)

            stage = _run_stages(
                run_id,
                combined_email,
                roster,
                llm=llm,
                prior=snapshot,
                prior_matches=prior_matches_for_backfill,
                suppress_detection=suppress_detection,  # ALL answered → validate suppression only
                resolved_drops=backfill_skip,           # confirmed_dropped+client_supplied
                # → backfill skip
                extracted=raw_extracted,                # combined-body extraction, lossless
                overrides=overrides,                    # operator mapping, else None
                alias_candidates=_pre_candidates,       # the identity bridge
                stage_tracker=stage_tracker,
            )

            # STEP 4: check clarify_deferred AFTER persisting terminals. If _run_stages
            # deferred (a NEW field_regression appeared this round), the run must send a
            # clarification and return — NOT fall through to alias binding. This mirrors
            # Round-1's deferred handling and uses the same shared helper. The classify-first
            # terminal outcomes were ALREADY persisted above; this helper only adds the NEW
            # 'asked' entries for the regression detected THIS round, in its own separate
            # closed transaction, before sending the clarification.
            if stage.clarify_deferred:
                stage_tracker.active = PipelineStage.CLARIFICATION
                clarification.defer_field_regression_clarification(
                    run_id, clarified, stage, combined_email, roster, llm=llm
                )
                return _OK_RESULT  # do not run the alias binding

            # Not deferred: the terminal outcomes from classify-first STEP 1 were already
            # persisted above, strictly before _run_stages was called. Fall through to alias
            # binding (the run is at AWAITING_APPROVAL).

        # Alias binding, step C: bind on explicit client CONFIRMATION.
        #
        # The system only learns an alias from evidence a human actually stated. A naive
        # implementation computes two facts INDEPENDENTLY over the whole run's post-resume
        # reconciliation — (a) the suggested employee S newly appears as resolved SOMEWHERE,
        # (b) the token is gone from the unresolved list SOMEWHERE — and binds whenever both
        # happen to be true. Those two facts can be satisfied by two completely UNRELATED
        # reconciliation entries: "No, Dave didn't work this period; David worked 5 hours
        # separately" would bind Dave → David with no confirmation at all.
        #
        # Evidence model actually used (alias_learning.bind_evidence_for_token): bind
        # {token: {"suggested": S, "bound": S}} iff ONE post-resume reconciliation entry ties
        # BOTH facts together — its submitted_name (normalized) equals either the token's own
        # text or S's own canonical full_name, AND that SAME entry is resolved=True with
        # matched_employee_id == S. A bare confirming "yes" still works, because the
        # code-owned asked-anchor in the extraction context lets extraction attribute the
        # reply to the suggested canonical name, which is what causes that single record to
        # resolve to S.
        #
        # MISNAME GUARD: if the reply resolves a DIFFERENT employee J (not the suggested S) —
        # e.g. "no, I meant James" — then no reconciliation entry has matched_employee_id == S
        # and no bind occurs. J is a non-suggested resolution; nobody proposed J for this
        # token, so the never-learn-from-inference guarantee holds. Learning here would
        # permanently misroute a real person's pay.
        _candidates_normalized = {
            tok: alias_learning.normalize_candidate(val) for tok, val in _pre_candidates.items()
        }
        _pending_tokens = [
            tok for tok, cand in _candidates_normalized.items()
            if cand.get("bound") is None and cand.get("suggested") is not None
        ]
        if _pending_tokens:
            stage_tracker.active = PipelineStage.LOAD
            post_run_data = repo.load_run(run_id)
            _post_reconciliation = (
                (post_run_data.get("reconciliation") or []) if post_run_data else []
            )

            _updated_candidates = dict(_pre_candidates)
            _any_bound = False
            for _token in _pending_tokens:
                _suggested_id = str(_candidates_normalized[_token]["suggested"])
                # Resolve the suggested employee's OWN canonical full_name from the
                # already-loaded roster — a legitimate confirming reply restates THIS name,
                # not the original unresolved token. Not found (should not happen; the id was
                # persisted from this same roster at capture time) → None, so the helper falls
                # back to matching the token's own text only: fail-closed, never fail-open.
                _suggested_full_name = next(
                    (
                        _emp.full_name
                        for _emp in roster.employees
                        if str(_emp.id) == _suggested_id
                    ),
                    None,
                )
                if alias_learning.bind_evidence_for_token(
                    _token, _suggested_id, _suggested_full_name, _post_reconciliation
                ):
                    _updated_candidates[_token] = {
                        "suggested": _suggested_id,
                        "bound": _suggested_id,
                    }
                    _any_bound = True
                    logger.info(
                        "alias candidate bound at resume: the token's own "
                        "submitted-name record resolved to the persisted "
                        "suggestion",
                    )
                else:
                    logger.info(
                        "alias binding skipped for run %s: no reconciliation "
                        "record ties the token to its persisted suggestion — "
                        "no confirmed evidence to bind",
                        run_id,
                    )
            if _any_bound:
                stage_tracker.active = PipelineStage.PERSIST
                repo.set_alias_candidates(run_id, _updated_candidates)
        return _OK_RESULT
    except Exception as exc:  # noqa: BLE001 — one bounded producer catch boundary
        result = classify_pipeline_exception(stage_tracker.active, exc)
        logger.warning("resume of run %s failed: %s", run_id, result.diagnostic_code)
        return result


def _run_stages(
    run_id: uuid.UUID,
    email: InboundEmail,
    roster: Roster,
    *,
    llm: Any,
    prior: Extracted | None = None,
    prior_matches: list[NameMatchResult] | None = None,
    resolved_drops: set[tuple[str, str]] | None = None,
    suppress_detection: set[tuple[str, str]] | None = None,
    extracted: Extracted | None = None,
    overrides: dict[str, str] | None = None,
    alias_candidates: dict[str, Any] | None = None,
    stage_tracker: _StageTracker | None = None,
) -> _RunStagesResult:
    """The shared gate path: extract → reconcile → validate → decide → persist → branch.

    Used by BOTH run_pipeline (first run) and resume_pipeline (the clarification re-entry),
    so the gate is identical on every path and the eval scores the exact same spine
    production runs on. Any gate logic added outside this function is logic the eval
    cannot see.

    extracted= kwarg: when supplied, the internal extract() call is skipped because the
    caller already ran extraction up front (the classify-first resume path). run_pipeline
    and the Round-1 resume pass no extracted kwarg, so the internal extract() runs.

    The two set-kwargs are deliberately SEPARATE, and conflating them is a money bug:
    - suppress_detection=: ALL answered asked fields (prior terminals UNION all newly
      classified). Forwarded to validate(resolved_drops=suppress_detection) so a field the
      client already answered is not re-emitted as a field_regression and re-asked forever.
      Does NOT reach backfill_extracted.
    - resolved_drops=: the backfill-skip set (confirmed_dropped UNION client_supplied UNION
      prior terminals; NOT carried_forward). Forwarded to
      backfill_extracted(resolved_drops=...) so the snapshot cannot overwrite a value the
      client explicitly resolved. Does NOT reach validate.
    Round-1 and run_pipeline pass neither kwarg → both None → no suppression, no skip.

    overrides=: an optional submitted_name -> employee_id_str map forwarded straight to
    reconcile_names(overrides=...) so an operator-resolved name wins BEFORE the exact/alias
    tiers. None (the default, and every pre-existing caller) is behavior-identical.

    alias_candidates=: the run's persisted {token: {"suggested", "bound"}} record. Used
    ONCE, inside the `if prior is not None:` block, to rebind the local `prior_matches`
    through alias_learning.confirmed_prior_matches — the IDENTITY BRIDGE. The employee a
    name-clarification is about was UNRESOLVED in the prior round by definition, so it is
    missing from prior_matches and every consumer that keys off it is blind to that
    employee. The augmentation happens exactly ONCE and the single augmented list then
    feeds all THREE consumers (detect_field_regression, detect_hours_changes, and
    backfill_extracted). Seeding them separately would let the three disagree about WHO
    the snapshot employee is — the same class of bug validate.py's is_paid docstring
    warns about ("Keeping it shared is what stops the two rules from disagreeing").
    run_pipeline passes nothing: its `prior` is None, so the block never runs.

    Returns _RunStagesResult(clarify_deferred, matches, issues).
    """
    # If the caller supplies pre-extracted data (the classify-first resume path), skip the
    # LLM extraction call. run_pipeline and Round-1 pass no extracted kwarg, so the internal
    # extract() runs.
    if extracted is None:
        if stage_tracker is not None:
            stage_tracker.active = PipelineStage.EXTRACT
        extract_kwargs = {"run_id": run_id}
        if llm is not None:
            extract_kwargs["llm"] = llm
        extracted = extract(email, roster, **extract_kwargs)
    # else: use the supplied pre-extracted value directly (no LLM call)

    if stage_tracker is not None:
        stage_tracker.active = PipelineStage.COMPUTE
    submitted_names = [e.submitted_name for e in extracted.employees]
    # pure code — no model call, no score
    matches = reconcile_names(submitted_names, roster, overrides=overrides)

    # Ordering invariant, in this exact order: DETECT on raw → BACKFILL → CALC.
    # 1. DETECT on the raw extraction (pre-backfill): the OT 2→None drop is only visible
    #    here. Once backfill has run, the drop has been papered over and there is nothing
    #    left to detect, so the client is never asked about it.
    # 2. BACKFILL: fill silence fields from the snapshot (employee_id-keyed).
    # 3. CALC: validate(BACKFILLED extracted, raw_field_drops=raw_drops) → decide → calc.
    raw_drops = None
    hours_changes: list[HoursChange] = []
    if prior is not None:
        # 0. BRIDGE the clarified employee's identity into prior_matches, ONCE, before any
        # consumer reads it. The clarified employee was UNRESOLVED in the prior round by
        # definition, so without this the drop detector is structurally blind to exactly
        # the person the clarification is about. One augmented list, three consumers.
        prior_matches = alias_learning.confirmed_prior_matches(
            prior_matches, matches, alias_candidates, roster
        )
        # 1. DETECT on the raw (pre-backfill) extraction. detect_field_regression is called
        # here rather than inside validate() precisely so it cannot accidentally be run
        # after the backfill.
        raw_drops = detect_field_regression(prior, extracted, prior_matches, matches)
        # 1b. DETECT the paid->paid CHANGES on the same raw extraction, for the same reason:
        # post-backfill the change is papered over. These are DISPLAY-ONLY — they are
        # persisted for the operator's approval page and deliberately NOT passed to
        # validate() or decide(). HoursChange has no issue_type, so the money gate cannot
        # see them even by accident.
        hours_changes = detect_hours_changes(prior, extracted, prior_matches, matches)
        # 2. BACKFILL: carry silence fields from the snapshot into extracted.
        # resolved_drops (the backfill-skip set) guards ONLY confirmed_dropped and
        # client_supplied from re-backfill — NOT carried_forward, which is intentionally
        # absent so backfill FILLS it from the snapshot and the client's carry-forward is
        # honored. suppress_detection is NOT passed here: it controls validate, not backfill.
        extracted = backfill_extracted(extracted, prior, prior_matches, matches, resolved_drops)
        # extracted is now the BACKFILLED version; validate/decide/calc use it.

    # 3. CALC: validate on the BACKFILLED extraction.
    # resolved_drops= here receives suppress_detection (ALL answered fields) so an answered
    # field is not re-emitted as a regression. raw_field_drops= receives the drops computed
    # in step 1 (detected on the raw extraction).
    # Note the deliberate asymmetry: the backfill-skip set is NOT forwarded here — it only
    # reaches backfill_extracted above.
    issues = validate(
        extracted,
        roster,
        matches,
        prior=prior,
        prior_matches=prior_matches,
        resolved_drops=suppress_detection,
        raw_field_drops=raw_drops,
    )

    decision = decide(extracted, matches, issues)  # pure code — no model call, no score

    # _compute_line_items is pure computation (no DB, no LLM) — it MUST run BEFORE the
    # transaction opens, so a calc exception (e.g. the integrity-violation raise below)
    # never opens a doomed transaction. It is computed unconditionally here (cheap, pure)
    # and only USED on the process branch; this keeps the persist transaction's body free of
    # anything that can raise for a business reason.
    line_items: list[PaystubLineItem] | None = None
    if decision.final_action == "process":
        if stage_tracker is not None:
            stage_tracker.active = PipelineStage.COMPUTE
        line_items = _compute_line_items(run_id, extracted, matches, roster)

    # --- persist DATA on EVERY run BEFORE branching; OVERWRITES on resume ---
    # One atomic transaction covers persist_extracted/persist_decision/
    # persist_reconciliation and — on the process branch only —
    # replace_line_items/set_status(COMPUTED)/set_status(AWAITING_APPROVAL), with the
    # status-advance LAST. A crash anywhere inside this block rolls back every write in it,
    # including the persists that "already succeeded" before the crash — never just the later
    # ones. A partial commit here is exactly the half-written run (paystubs replaced, status
    # stale) the transaction exists to prevent.
    if stage_tracker is not None:
        stage_tracker.active = PipelineStage.PERSIST
    with repo.get_connection() as conn, conn.transaction():
        repo.persist_extracted(run_id, extracted, conn=conn)
        repo.persist_decision(run_id, decision, conn=conn)  # data-only; status written separately
        repo.persist_reconciliation(run_id, matches, conn=conn)  # never NULL on a clean run
        # UNCONDITIONAL — including the empty list on a first run or an unchanged resume.
        # Writing [] every time makes a stale record from a dead attempt structurally
        # impossible rather than only accidentally absent: the operator must never be shown
        # a change belonging to a conversation this run no longer has. DATA-ONLY: never
        # passed to validate(), never passed to decide().
        repo.set_hours_changes(run_id, hours_changes, conn=conn)

        if decision.final_action == "process":
            assert line_items is not None
            repo.replace_line_items(run_id, line_items, conn=conn)  # DELETE-by-run then insert
            repo.set_status(run_id, RunStatus.COMPUTED, conn=conn)
            repo.set_status(run_id, RunStatus.AWAITING_APPROVAL, conn=conn)  # the one human gate
    # --- transaction block closed above; `clarification.clarify` (an LLM + provider call) is a
    # SIBLING statement here, never nested inside the `with conn.transaction():` block. No
    # transaction may span a network/LLM call — a slow provider would hold the DB connection
    # and its locks open for the length of the call. ---

    # --- branch SOLELY on final_action (the code-owned deterministic decision) ---
    clarify_deferred = False
    if decision.final_action == "process":
        clarify_deferred = False
    else:  # request_clarification
        # Defer whenever ANY field_regression issue exists. A mixed-issue email
        # (field_regression + unresolved name) must defer under
        # purpose='clarification_field_regression' so the idempotency check uses the correct
        # purpose and a prior 'clarification' row does not suppress the send — otherwise the
        # run parks at awaiting_reply with no email ever going out.
        has_field_regression = any(i.issue_type == "field_regression" for i in issues)
        if has_field_regression:
            # Defer: resume_pipeline writes the 'asked' outcomes BEFORE calling
            # clarification.clarify, so a fast reply can never arrive against an unrecorded
            # question.
            clarify_deferred = True
        else:
            # Non-field-regression clarification: call clarification.clarify immediately
            # (normal path). This is a sibling statement AFTER the persist transaction
            # closes, never nested inside it — clarify performs two LLM calls plus a provider
            # send.
            if stage_tracker is not None:
                stage_tracker.active = PipelineStage.CLARIFICATION
            clarification.clarify(
                run_id, email, decision, roster, extracted, llm=llm, purpose="clarification"
            )
            clarify_deferred = False

    return _RunStagesResult(clarify_deferred=clarify_deferred, matches=matches, issues=issues)


def _compute_line_items(
    run_id: uuid.UUID,
    extracted: Extracted,
    matches: list[NameMatchResult],
    roster: Roster,
) -> list[PaystubLineItem]:
    """Build PaystubLineItems for the resolved (matched) employees on a process run."""
    match_by_name = {m.submitted_name: m for m in matches}
    emp_by_id = {e.id: e for e in roster.employees}

    items: list[PaystubLineItem] = []
    for ee in extracted.employees:
        m = match_by_name.get(ee.submitted_name)
        if m is None or m.matched_employee_id is None:
            continue  # unresolved names never reach a process run (gate blocks them)
        employee = emp_by_id.get(m.matched_employee_id)
        if employee is None:
            # On a PROCESS run the gate guarantees every name resolved to a roster employee.
            # A matched_employee_id with no roster row (e.g. a stale reconciliation persisted
            # against a since-changed roster, or a roster loaded for the wrong business) is an
            # INVARIANT VIOLATION, not an expected skip — silently omitting the employee would
            # ship an incomplete payroll the operator is told is clean, and that employee goes
            # unpaid. Fail LOUD: raise so the run routes to ERROR instead of computing a
            # degraded paystub.
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
            cast(dict[str, object], resolved_hours),
            employee,
            ee.contribution_401k_override,
        )
        # Stamp the real run identity + the submitted name (the per-name provenance;
        # there is no score on a deterministic resolution).
        item = item.model_copy(
            update={
                "run_id": run_id,
                "submitted_name": ee.submitted_name,
            }
        )
        items.append(item)
    return items
