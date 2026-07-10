"""The clarify cluster (STRUCT-03, D-09): draft/send a clarification email and
the deferred field-regression clarification helper, plus the code-owned
"what we asked" summary and combined-context email builders.

Carved out of orchestrator.py (Phase 13 Plan 02) — this is the single home for:
clarify (draft + send + pause at AWAITING_REPLY), defer_field_regression_clarification
(the shared Round-1/Round-2 deferred-clarification helper), render_asked_summary,
combined_context_email, and MAX_CLARIFICATION_ROUNDS.
"""
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from app.db import repo
from app.email import gateway
from app.models.contracts import Decision, Extracted, InboundEmail
from app.models.roster import Roster
from app.models.status import RunStatus
from app.pipeline.compose_email import clarification_subject, compose_clarification
from app.pipeline.reconcile_names import normalize_name
from app.pipeline.suggest import suggest_employees

if TYPE_CHECKING:
    from app.pipeline.orchestrator import _RunStagesResult

logger = logging.getLogger("payroll_agent.orchestrator")

# MAX_CLARIFICATION_ROUNDS (D-11-06/D-11-07): the round cap that routes a run to
# needs_operator instead of sending a 4th clarification. Documented derivation
# (STALE_THRESHOLD style, main.py:100-101): the counter increments ONCE per
# clarification SEND (any purpose — 'clarification' and
# 'clarification_field_regression' share one counter, D-11-07 "counts ALL
# clarification sends per run regardless of purpose"), inside clarify's
# post-send finalize transaction. Boundary semantics: counter == 3 means THREE
# sends have already happened; the would-be 4th send is what escalates. RESEARCH
# Open Question #4 resolves to "3 total rounds" = 3 sends allowed, cap check
# below tests `>= MAX_CLARIFICATION_ROUNDS` so the 4th attempt (counter already
# at 3) is the one that diverts to needs_operator instead of sending.
MAX_CLARIFICATION_ROUNDS = 3


def defer_field_regression_clarification(
    run_id: uuid.UUID,
    clarified: dict[str, dict[str, Any]],
    stage: _RunStagesResult,
    combined_email: InboundEmail,
    roster: Roster,
    *,
    llm: Any,
) -> None:
    """Shared helper for deferred field-regression clarification (IN-01, CR-02 fix).

    Called from BOTH the Round-1 branch and the Round-2 branch when _run_stages
    returns clarify_deferred=True. Factoring into one helper prevents the two
    copies from drifting — the Round-2 copy being entirely absent was the CR-02 bug.

    Contract (N2 ordering invariant):
      1. Write 'asked' for every NEW field_regression issue into `clarified`
         dict (mutated in-place).
      2. Persist clarified via set_clarified_fields BEFORE the send.
      3. Call clarify(purpose='clarification_field_regression') to draft +
         send the email and advance to AWAITING_REPLY.

    The caller must `return` immediately after this call — the run is now at
    AWAITING_REPLY and must NOT fall through to the alias-diff.
    """
    # Step 1: Load fresh reconciliation so we can look up emp_id by submitted_name.
    post_run = repo.load_run(run_id)
    post_reconciliation = post_run.get("reconciliation") if post_run else None
    name_to_id_post: dict[str, Any] = {
        m["submitted_name"]: m["matched_employee_id"]
        for m in (post_reconciliation or [])
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
                    emp_key = str(current_emp_id_p)
                    # CX-03 defense-in-depth: never flip a TERMINAL outcome back to
                    # 'asked'. setdefault protects only the OUTER dict; the field
                    # assignment below would otherwise clobber a terminal for a
                    # re-detected drop. With the SET A fix in resume_pipeline this
                    # branch is unreachable for terminals (their re-detection is
                    # suppressed upstream); the guard protects future leak paths.
                    if clarified.get(emp_key, {}).get(field_name_p) in (
                        "confirmed_dropped",
                        "client_supplied",
                        "carried_forward",
                    ):
                        continue
                    clarified.setdefault(emp_key, {})[field_name_p] = "asked"
    # Step 3: Persist 'asked' BEFORE send (N2 invariant — asked-before-send).
    # D-9-06/D-9-01: a single-statement transaction that commits and closes
    # strictly BEFORE Step 5's clarify(...) call below — no transaction ever
    # spans clarify's LLM/provider calls. Steps 1/2/4 are reads/in-memory
    # mutation only, not folded in (nothing to gain from widening the txn).
    with repo.get_connection() as conn, conn.transaction():
        repo.set_clarified_fields(run_id, clarified, conn=conn)

    # Step 4: Load the persisted decision + extracted for clarify.
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
        clarify(
            run_id,
            combined_email,
            persisted_decision,
            roster,
            persisted_extracted,
            llm=llm,
            purpose="clarification_field_regression",
        )


def render_asked_summary(
    decision: Decision | None, clarified_fields: dict[str, dict[str, Any]]
) -> list[str]:
    """Render the code-owned "what we asked" lines from PERSISTED decision facts only
    (D-11-10). NEVER the LLM-drafted outbound clarification body — that anchor must
    stay deterministic and string-testable, not dependent on model phrasing.

    Two sources, both persisted facts:
      - decision.unresolved_names: names the run could not resolve against the roster.
      - clarified_fields: per-employee-id, per-field outcome dict; only entries whose
        outcome is CURRENTLY 'asked' describe a still-open question (a terminal outcome
        — client_supplied / confirmed_dropped / carried_forward — is already answered
        and must not clutter the anchor as if still outstanding).

    decision may be None (first-ever resume, no persisted Decision yet) — treated as
    "no unresolved names" rather than raising.
    """
    lines: list[str] = []
    unresolved_names = list(getattr(decision, "unresolved_names", None) or [])
    for name in unresolved_names:
        lines.append(f"{name}: name could not be matched to a roster employee")
    for emp_id_str, field_outcomes in (clarified_fields or {}).items():
        if not isinstance(field_outcomes, dict):
            continue
        for field, outcome in field_outcomes.items():
            if outcome == "asked":
                lines.append(f"{emp_id_str}: {field} is missing")
    return lines


def combined_context_email(
    reply: InboundEmail,
    original_body: str,
    *,
    asked_summary_lines: list[str],
    prior_replies: list[str],
) -> InboundEmail:
    """Build the extraction-input InboundEmail: ORIGINAL body + a code-owned
    "QUESTIONS WE ASKED" anchor (D-11-10) + ALL consumed prior replies in round
    order (D-11-12/13) + the CURRENT reply.

    Pure function — no DB I/O, returns reply.model_copy(update=...); the passed-in
    reply object is never mutated. The re-extraction must see the original hours (so
    a partial reply doesn't drop them), what was asked (so a bare "40" attributes to
    the right employee/field, D-11-11), every prior round's correction (so a Round-1
    "30, not 40" survives into Round 2's context — CX-01 closure), and the current
    reply. Bounded implicitly by MAX_CLARIFICATION_ROUNDS (11-02's cap keeps
    prior_replies small; no separate limit needed here).
    """
    sections = ["ORIGINAL PAYROLL EMAIL:", original_body, ""]
    if asked_summary_lines:
        sections.append("QUESTIONS WE ASKED:")
        sections.extend(asked_summary_lines)
        sections.append("")
    n_prior = len(prior_replies)
    for i, prior_body in enumerate(prior_replies, start=1):
        sections.append(f"CLARIFICATION REPLY {i} FROM CLIENT:")
        sections.append(prior_body)
        sections.append("")
    sections.append(f"CLARIFICATION REPLY {n_prior + 1} FROM CLIENT (CURRENT):")
    sections.append(reply.body_text)
    combined_body = "\n".join(sections)
    return reply.model_copy(update={"body_text": combined_body})


def clarify(
    run_id: uuid.UUID,
    email: InboundEmail,
    decision: Decision,
    roster: Roster,
    extracted: Extracted,
    *,
    llm: Any,
    purpose: str = "clarification",
) -> None:
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
    get_outbound_for_round idempotency check uses the purpose kwarg so a prior plain
    'clarification' row does NOT suppress the field-regression send).

    D-21-05 — the suggestion-only call: BEFORE composing, ask the cheap (draft) tier
    which roster employee each unresolved name most likely meant, and pass that as
    `suggestions=` so the clarification can be SPECIFIC ("did you mean David
    Reyes?"). CRITICAL: this runs ONLY here, on the request_clarification branch,
    STRICTLY AFTER `decide` has already returned (decision is a parameter, computed
    upstream in _run_stages). The suggestion is advisory COPY — it is NEVER passed
    to decide and NEVER influences final_action. A suggestion failure degrades to
    {} inside suggest_employees, so it can never strand the run.

    D-11-01/D-11-06/D-11-07/D-11-09: the idempotency guard is now keyed on
    (purpose, round) — repo.get_outbound_for_round — instead of purpose alone, so a
    genuinely NEW round's question always sends (WR-05 fix: the old purpose-only
    guard silently parked round 2+ at AWAITING_REPLY with no email out). A cap
    check runs FIRST, before any LLM/gateway call: at MAX_CLARIFICATION_ROUNDS
    reached, the run silently escalates to NEEDS_OPERATOR (no email, no LLM call,
    D-11-09) instead of sending. Placing both checks at the top of clarify covers
    BOTH call sites (_run_stages's direct call and
    defer_field_regression_clarification's Step 5 call) with one guard each.
    """
    # D-11-06/D-11-07/D-11-09: round cap — checked BEFORE the (purpose, round)
    # guard and BEFORE any LLM/gateway call (D-9-01 trivially satisfied: no
    # provider call happens before this check can return). counter >=
    # MAX_CLARIFICATION_ROUNDS means MAX_CLARIFICATION_ROUNDS sends have already
    # happened; this the would-be NEXT send, so it diverts to needs_operator.
    # Escalation is the sole write in its transaction (status-advance-last,
    # D-9-02) — no new outbound row, no new purpose, no client-facing signal
    # (D-11-09 silent handoff).
    current_round = repo.get_clarification_round(run_id)
    if current_round >= MAX_CLARIFICATION_ROUNDS:
        with repo.get_connection() as conn, conn.transaction():
            repo.set_status(run_id, RunStatus.NEEDS_OPERATOR, conn=conn)
        logger.info(
            "run %s escalated to needs_operator after %d rounds (D-11-06/D-11-07/D-11-09)",
            run_id,
            current_round,
        )
        return

    # Finding #2 idempotency guard (CLAR-04), re-keyed to (purpose, round)
    # (D-11-01): check for an existing SENT row at the CURRENT round BEFORE
    # drafting or sending. A found row = a true duplicate (crash-retrigger of the
    # SAME round) → suppress the send and finalize; None = a genuinely new
    # question → proceed. The purpose kwarg still distinguishes this from a
    # confirmation row and from a field-regression clarification (R3-2 fix).
    existing_clari = repo.get_outbound_for_round(
        run_id, purpose=purpose, round=current_round
    )
    if existing_clari is not None:
        logger.info(
            "clarification already sent for run %s (purpose=%r, round=%d) — "
            "skipping duplicate send (finding #2, CLAR-04, D-11-01)",
            run_id,
            purpose,
            current_round,
        )
        # N7 fix: snapshot BEFORE AWAITING_REPLY (PATH 1: idempotency early-return).
        # IS NULL guard in set_pre_clarify_extracted makes this a no-op if already set.
        # D-9-06: both writes commit as one transaction, status-advance last (D-9-02).
        # D-11-01/Pitfall #3: the round advance is DERIVED from the found row's own
        # round (never a blind current_round + 1) — a crash between a send and this
        # finalize self-heals on re-entry because the found row's round is the
        # ground truth of what was actually sent.
        with repo.get_connection() as conn, conn.transaction():
            repo.set_pre_clarify_extracted(run_id, extracted, conn=conn)
            repo.set_clarification_round(
                run_id, existing_clari["round"] + 1, conn=conn
            )
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
    #   4. candidate_ids count == 0 → genuinely unresolved → capture the token
    #      (the nested {"suggested": id|None, "bound": None} value is filled in
    #      AFTER suggest_employees runs below, D-11-14 — capture and persist are
    #      two steps now because the suggestion doesn't exist yet at this point).
    #
    # R2-HIGH COLLISION DETECTION: Do NOT use deterministic_match return value to
    # infer collision. deterministic_match returns None for BOTH zero candidates (no
    # match) AND 2+ candidates (collision). A colliding token like "D. Reyes" returns
    # None yet has 2 candidate_ids. The pre-check MUST count candidate_ids directly.
    _captured_token: str | None = None
    if len(decision.unresolved_names) == 1:
        candidate_token = decision.unresolved_names[0]
        norm_token = normalize_name(candidate_token)
        exact_ids = [
            emp.id for emp in roster.employees if normalize_name(emp.full_name) == norm_token
        ]
        alias_ids = [
            emp.id
            for emp in roster.employees
            if any(normalize_name(a) == norm_token for a in emp.known_aliases)
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
            # Defer the actual set_alias_candidates write until the nested
            # {"suggested": id|None, "bound": None} value can be built below
            # (D-11-14) — suggest_employees hasn't run yet at this point.
            _captured_token = candidate_token
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
    suggest_kwargs: dict[str, Any] = {}
    if llm is not None:
        suggest_kwargs["llm"] = llm
    suggestions = suggest_employees(
        decision.unresolved_names, roster, **suggest_kwargs
    )

    # D-11-14: persist the nested {token: {"suggested": id|None, "bound": None}}
    # candidate shape now that the suggestion is available. suggest_employees
    # returns {submitted_name: suggested_FULL_NAME} — a NAME, not an id
    # (Pitfall #5) — so map the suggested full_name to its employee id via the
    # already-loaded roster (full_name is unique per business). A suggested
    # name that (for any reason) doesn't match a roster full_name maps to
    # suggested=None — the bind check simply never fires for that token
    # (nothing to confirm against). This MUST run AFTER suggest_employees and
    # BEFORE send_outbound — same timing guarantee the old single-step capture
    # gave (D-04), just split across two now-adjacent statements.
    if _captured_token is not None:
        _suggested_full_name = suggestions.get(_captured_token)
        _suggested_id: str | None = None
        if _suggested_full_name is not None:
            for _emp in roster.employees:
                if _emp.full_name == _suggested_full_name:
                    _suggested_id = str(_emp.id)
                    break
        candidates = {_captured_token: {"suggested": _suggested_id, "bound": None}}
        repo.set_alias_candidates(run_id, candidates)
        logger.info(
            "alias candidate suggestion persisted for run %s: %d suggestion(s) "
            "mapped to an employee id (D-11-14 nested shape)",
            run_id,
            1 if _suggested_id is not None else 0,
        )

    compose_kwargs: dict[str, Any] = {"suggestions": suggestions}
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
            round=current_round,
        )
        # N7 fix: snapshot BEFORE AWAITING_REPLY (PATH 2: record_only).
        # IS NULL guard in set_pre_clarify_extracted makes this idempotent.
        # D-9-06: insert_email_message (the intent-recording write, no real Resend
        # call) stays OUTSIDE this transaction (D-9-01) — this block covers only
        # what comes strictly after it, status-advance last (D-9-02).
        # D-11-01/Pitfall #3: round advances to current_round + 1 — the row was
        # JUST written above with round=current_round, so this IS the sent-row's
        # round (not a blind counter increment); a crash before this transaction
        # commits self-heals on re-entry via the (purpose, round) guard above.
        with repo.get_connection() as conn, conn.transaction():
            repo.set_pre_clarify_extracted(run_id, extracted, conn=conn)
            repo.set_clarification_round(run_id, current_round + 1, conn=conn)
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
        round=current_round,
    )
    # N7 fix: snapshot BEFORE AWAITING_REPLY (PATH 3: live gateway).
    # IS NULL guard in set_pre_clarify_extracted makes this idempotent.
    # D-9-06/D-9-01: gateway.send_outbound (the provider call) has ALREADY returned
    # above — this transaction opens strictly AFTER it, covering only the writes
    # that come after the send, status-advance last (D-9-02).
    # D-11-01/Pitfall #3: round advances to current_round + 1 — gateway.send_outbound
    # just wrote the outbound row with round=current_round (threaded through above),
    # so this derives from the row that was actually sent, not a blind increment.
    with repo.get_connection() as conn, conn.transaction():
        repo.set_pre_clarify_extracted(run_id, extracted, conn=conn)
        repo.set_clarification_round(run_id, current_round + 1, conn=conn)
        repo.set_status(run_id, RunStatus.AWAITING_REPLY, conn=conn)  # CLAR-01 pause
