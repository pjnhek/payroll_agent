"""The clarify cluster: draft and send a clarification email, then pause the run.

Home for `clarify` (draft + send + pause at AWAITING_REPLY),
`defer_field_regression_clarification` (the shared deferred-clarification helper used by
both the first and subsequent clarification rounds), `render_asked_summary`,
`combined_context_email`, and `MAX_CLARIFICATION_ROUNDS`.

Invariants this module holds:

- **The LLM never decides here.** By the time `clarify` runs, `decide` has already
  returned and the decision is a parameter. The suggestion call ("did you mean David
  Reyes?") is advisory COPY only — it is never passed to `decide` and can never
  influence `final_action`.
- **Intent is written before the email goes out.** Every path freezes the clarification,
  records the reply state, and queues the delivery job before a worker can contact the
  provider, so a fast reply never arrives against an unrecorded question.
- **No transaction spans an LLM or provider call.** Drafting happens before the
  reservation transaction, and the worker contacts the provider after it has committed.
- **The run never strands.** A drafting failure falls back to a deterministic template, a
  suggestion failure degrades to no suggestion, and a run that hits the round cap
  escalates to an operator rather than silently parking with no email out.
"""
from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from app.config import get_settings
from app.db import repo
from app.models.contracts import Decision, Extracted, InboundEmail
from app.models.job import JobKind
from app.models.roster import Roster
from app.models.status import RunStatus
from app.pipeline import send_guard
from app.pipeline.compose_email import clarification_subject, compose_clarification
from app.pipeline.reconcile_names import normalize_name
from app.pipeline.suggest import suggest_employees
from app.queue import wake

if TYPE_CHECKING:
    from app.pipeline.orchestrator import _RunStagesResult

logger = logging.getLogger("payroll_agent.orchestrator")

# The round cap that routes a run to needs_operator instead of sending a 4th
# clarification. Derivation: the counter increments ONCE per clarification SEND, for any
# purpose — plain 'clarification' and 'clarification_field_regression' share one counter,
# so a client cannot be asked six questions by alternating the two purposes. The counter
# is advanced inside clarify's post-send finalize transaction.
#
# Boundary semantics: counter == 3 means THREE sends have already happened, so the
# would-be 4th send is the one that escalates. The cap check below therefore tests
# `>= MAX_CLARIFICATION_ROUNDS`: three rounds are allowed, and the fourth attempt diverts
# to needs_operator instead of sending.
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
    """Record the 'asked' outcomes, then send the field-regression clarification.

    Called from BOTH the first-round branch and the answered-round branch when
    _run_stages returns clarify_deferred=True. It exists as one shared helper precisely
    so the two call sites cannot drift: an earlier version of this logic was inlined in
    the first-round branch and entirely ABSENT from the answered-round branch, so a
    regression detected on a later round was never asked about.

    Contract — the write-before-send ordering is the whole point:
      1. Write 'asked' for every NEW field_regression issue into the `clarified` dict
         (mutated in-place).
      2. Persist `clarified` via set_clarified_fields BEFORE the send.
      3. Call clarify(purpose='clarification_field_regression') to draft + send the email
         and advance to AWAITING_REPLY.
    Sending first would open a window where the client's reply arrives against a question
    whose state was never recorded, and the reply is then classified against nothing.

    The caller must `return` immediately after this call — the run is now at
    AWAITING_REPLY and must NOT fall through to the alias binding.
    """
    # Step 1: Load fresh reconciliation so we can look up emp_id by submitted_name.
    post_run = repo.load_run(run_id)
    post_reconciliation = post_run.get("reconciliation") if post_run else None
    name_to_id_post: dict[str, Any] = {
        m["submitted_name"]: m["matched_employee_id"]
        for m in (post_reconciliation or [])
        if isinstance(m, dict) and m.get("matched_employee_id")
    }
    # Step 2: Write 'asked' for each NEW field_regression issue.
    for issue in (stage.issues or []):
        if issue.issue_type == "field_regression":
            # issue.field format: "{submitted_name}.{field_name}"
            parts = issue.field.rsplit(".", 1)
            if len(parts) == 2:
                submitted_name_p, field_name_p = parts
                current_emp_id_p = name_to_id_post.get(submitted_name_p)
                if current_emp_id_p:
                    emp_key = str(current_emp_id_p)
                    # Defense in depth: never flip a TERMINAL outcome back to 'asked'.
                    # setdefault protects only the OUTER dict; the field assignment below
                    # would otherwise clobber a terminal for a re-detected drop, and the
                    # client would be asked the same answered question forever. The
                    # caller's suppress-detection set already makes this branch
                    # unreachable for terminals; this guard protects future leak paths.
                    if clarified.get(emp_key, {}).get(field_name_p) in (
                        "confirmed_dropped",
                        "client_supplied",
                        "carried_forward",
                    ):
                        continue
                    clarified.setdefault(emp_key, {})[field_name_p] = "asked"
    # Step 3: Persist 'asked' BEFORE the send.
    # A single-statement transaction that commits and closes strictly BEFORE Step 5's
    # clarify(...) call below — no transaction ever spans clarify's LLM/provider calls.
    # Steps 1/2/4 are reads and in-memory mutation only, so there is nothing to gain from
    # widening the transaction to include them.
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
    """Render the code-owned "what we asked" lines from PERSISTED decision facts only.

    NEVER built from the LLM-drafted outbound clarification body: this anchor is what a
    later re-extraction reads to attribute a bare "40" to the right employee and field, so
    it must stay deterministic and string-testable rather than depending on how the model
    happened to phrase the question that round.

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
    "QUESTIONS WE ASKED" anchor + ALL consumed prior replies in round order + the
    CURRENT reply.

    Pure function — no DB I/O, returns reply.model_copy(update=...); the passed-in reply
    object is never mutated.

    Each section earns its place, and dropping any one of them loses money or context:
      - the ORIGINAL hours, so a partial reply does not silently drop the employees the
        client did not restate;
      - what was asked, so a bare "40" attributes to the right employee and field;
      - every prior round's correction, so a first-round "30, not 40" still governs in a
        later round rather than reverting to the original 40;
      - the current reply.
    Bounded implicitly by MAX_CLARIFICATION_ROUNDS — the cap keeps prior_replies small, so
    no separate length limit is needed here.
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
    """Draft a clarification, send it, and pause the run at AWAITING_REPLY.

    The cheap drafting tier drafts the body, falling back to a deterministic template on
    empty content so a draft failure never strands the run. The producer freezes a
    synthetic Message-ID on the linked email_messages(direction='outbound', run_id) row
    before queueing delivery — that row is the SINGLE canonical threading anchor the
    reply path reads back via the header chain; there is deliberately no Message-ID
    column on payroll_runs to drift out of sync with it. Status advances via
    repo.set_status, the sole status writer. The clarification threads off the client's
    inbound message_id (In-Reply-To + References) so the client's reply resolves back to
    this run.

    extracted: the pre-clarify extraction snapshot. It is passed to
    set_pre_clarify_extracted on every AWAITING_REPLY path, so the snapshot is durably
    persisted at the FIRST clarification send and not overwritten on a re-trigger — a
    re-trigger that overwrote it would destroy the very baseline the carry-forward logic
    restores from. The IS NULL guard inside set_pre_clarify_extracted makes all three
    calls idempotent.

    purpose: 'clarification' (default) or 'clarification_field_regression'. The
    idempotency check below is keyed on the purpose, so a prior plain 'clarification' row
    does NOT suppress a field-regression send for the same run.

    The suggestion-only call: BEFORE composing, ask the cheap drafting tier which roster
    employee each unresolved name most likely meant, and pass that as `suggestions=` so
    the clarification can be SPECIFIC ("did you mean David Reyes?"). CRITICAL: this runs
    ONLY here, on the request_clarification branch, STRICTLY AFTER `decide` has already
    returned (the decision is a parameter, computed upstream). The suggestion is advisory
    COPY — it is NEVER passed to decide and NEVER influences final_action, which is what
    keeps every money-moving judgment in code. A suggestion failure degrades to {} inside
    suggest_employees, so it can never strand the run.

    Two guards run at the top, before any LLM or gateway call, and both cover BOTH call
    sites (the direct call from _run_stages and defer_field_regression_clarification's
    Step 5 call):
      - The round cap: at MAX_CLARIFICATION_ROUNDS reached, the run escalates to
        NEEDS_OPERATOR with no email and no LLM call.
      - The idempotency guard, keyed on (purpose, round) rather than purpose alone. Keying
        on purpose alone silently parks a genuinely-new round 2+ question at
        AWAITING_REPLY with no email ever going out — the run waits forever for a reply to
        a question nobody sent.
    """
    # Round cap — checked BEFORE the (purpose, round) guard and BEFORE any LLM/gateway
    # call, so no provider call can happen on a run that is about to escalate.
    # counter >= MAX_CLARIFICATION_ROUNDS means that many sends have already happened, so
    # this is the would-be NEXT send and it diverts to needs_operator instead.
    # The escalation is the sole write in its transaction (status advance last) — no new
    # outbound row, no new purpose, and no client-facing signal: the handoff to the
    # operator is silent to the client.
    current_round = repo.get_clarification_round(run_id)
    if current_round >= MAX_CLARIFICATION_ROUNDS:
        with repo.get_connection() as conn, conn.transaction():
            repo.set_status(run_id, RunStatus.NEEDS_OPERATOR, conn=conn)
        logger.info(
            "run %s escalated to needs_operator after %d rounds",
            run_id,
            current_round,
        )
        return

    # Check for a completed clarification at the current slot before composing a new
    # one. A completed row proves the reply state can be finalized without another
    # draft or provider request.
    existing_clari = repo.get_outbound_for_round(
        run_id, purpose=purpose, round=current_round
    )
    if existing_clari is not None:
        logger.info(
            "clarification already sent for run %s (purpose=%r, round=%d) — "
            "skipping duplicate send",
            run_id,
            purpose,
            current_round,
        )
        # Snapshot BEFORE advancing to AWAITING_REPLY (path 1: the idempotent early
        # return). The IS NULL guard in set_pre_clarify_extracted makes this a no-op if
        # the snapshot is already set. Both writes commit as one transaction, status
        # advance last.
        # The round advance is DERIVED from the found row's own round, never a blind
        # current_round + 1 — the row that was actually sent is the ground truth of what
        # the client received, so a crash between a send and this finalize self-heals on
        # re-entry instead of double-counting a round.
        with repo.get_connection() as conn, conn.transaction():
            repo.set_pre_clarify_extracted(run_id, extracted, conn=conn)
            repo.set_clarification_round(
                run_id, existing_clari["round"] + 1, conn=conn
            )
            repo.set_status(run_id, RunStatus.AWAITING_REPLY, conn=conn)
        return

    # A reservation from an interrupted producer is already a complete provider-ready
    # record. Reuse its identifier-only job before any suggestion or drafting work; the
    # worker will deliver only the frozen snapshot.
    policy = send_guard.outbound_replay_policy(
        run_id, purpose=purpose, round=current_round
    )
    if policy.has_existing_snapshot:
        assert policy.email_id is not None
        with repo.get_connection() as conn, conn.transaction():
            snapshot = repo.load_outbound_snapshot(run_id, policy.email_id, conn=conn)
            if snapshot is None:
                raise RuntimeError("clarification reservation lost its frozen snapshot")
            snapshot_round = snapshot.get("round")
            if isinstance(snapshot_round, bool) or not isinstance(snapshot_round, int):
                raise RuntimeError("clarification reservation has an invalid round")
            repo.enqueue_job(
                kind=JobKind.SEND_OUTBOUND,
                dedup_key=repo.send_outbound_dedup_key(policy.email_id),
                run_id=run_id,
                email_id=policy.email_id,
                conn=conn,
            )
            repo.set_pre_clarify_extracted(run_id, extracted, conn=conn)
            repo.set_clarification_round(run_id, snapshot_round + 1, conn=conn)
            repo.set_status(run_id, RunStatus.AWAITING_REPLY, conn=conn)
        wake.wake()
        return

    # Capture the alias-learning candidate token. This runs AFTER the idempotency guard
    # and BEFORE reservation, so the original token is always captured in the same
    # boundary as the clarification intent — a token captured after the send could be lost
    # to a crash while the client already has the question.
    #
    # Gate sequence:
    #   1. more than one unresolved name → no capture. Learning is single-token only: with
    #      two unresolved names there is no way to attribute a confirming reply to one of
    #      them without guessing.
    #   2. the token matches 2+ roster employees → no capture. A colliding token is
    #      ambiguous, and learning it would permanently misroute one employee's pay.
    #   3. the token matches exactly 1 employee → it already resolves; nothing to learn.
    #   4. the token matches 0 employees → genuinely unresolved → capture it. The nested
    #      {"suggested": id|None, "bound": None} value is filled in AFTER suggest_employees
    #      runs below; capture and persist are two steps because the suggestion does not
    #      exist yet at this point.
    #
    # Collision detection MUST count candidate_ids directly. It cannot infer a collision
    # from deterministic_match's return value: that returns None for BOTH zero candidates
    # (no match) AND 2+ candidates (collision), so a colliding token like "D. Reyes" would
    # look identical to an unresolved one and get captured for learning.
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
            # COLLISION: the token matches 2+ employees — ambiguous at capture time.
            # Colliders are excluded HERE, at capture, not merely at write time: a
            # captured collider is a latent mislearn waiting for a confirming reply.
            logger.info(
                "alias candidate %r excluded at capture: %d candidates (collision)",
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
            # {"suggested": id|None, "bound": None} value can be built below —
            # suggest_employees has not run yet at this point.
            _captured_token = candidate_token
            logger.info(
                "alias candidate captured for run %s: %r "
                "(single-token, genuinely unresolved)",
                run_id,
                candidate_token,
            )
    else:
        logger.info(
            "alias capture skipped for run %s: %d unresolved names "
            "(single-token-only rule)",
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

    # Build the nested {token: {"suggested": id|None, "bound": None}} candidate shape now
    # that the suggestion is available. suggest_employees returns
    # {submitted_name: suggested_FULL_NAME} — a NAME, not an id — so the suggested
    # full_name must be mapped to its employee id via the already-loaded roster
    # (full_name is unique per business). A suggested name that (for any reason) does not
    # match a roster full_name maps to suggested=None, and the bind check simply never
    # fires for that token: there is nothing to confirm against, which is the correct
    # fail-closed behavior. This MUST run AFTER suggest_employees and BEFORE
    # reservation — the same timing guarantee the capture block above relies on, split
    # across two now-adjacent statements.
    candidates: dict[str, dict[str, str | None]] | None = None
    if _captured_token is not None:
        _suggested_full_name = suggestions.get(_captured_token)
        _suggested_id: str | None = None
        if _suggested_full_name is not None:
            for _emp in roster.employees:
                if _emp.full_name == _suggested_full_name:
                    _suggested_id = str(_emp.id)
                    break
        candidates = {_captured_token: {"suggested": _suggested_id, "bound": None}}

    compose_kwargs: dict[str, Any] = {"suggestions": suggestions}
    if llm is not None:
        compose_kwargs["llm"] = llm
    body = compose_clarification(decision, **compose_kwargs)

    # Reserve the exact envelope and queue the worker in one transaction. The worker
    # handles both record-only and provider-backed delivery from this same snapshot.
    settings = get_settings()
    with repo.get_connection() as conn, conn.transaction():
        snapshot = repo.reserve_outbound_snapshot(
            run_id=run_id,
            purpose=purpose,
            round=current_round,
            message_id=f"<{uuid.uuid4()}@demo.payroll-agent.local>",
            from_addr=settings.resend_from_addr,
            to_addr=email.from_addr,
            reply_to=settings.resend_reply_to or None,
            in_reply_to=email.message_id,
            references_header=email.message_id,
            subject=clarification_subject(email.subject),
            body_text=body,
            attachments=(),
            conn=conn,
        )
        email_id = snapshot.get("email_id")
        snapshot_round = snapshot.get("round")
        if not isinstance(email_id, uuid.UUID):
            raise RuntimeError("clarification reservation lacks its email id")
        if isinstance(snapshot_round, bool) or not isinstance(snapshot_round, int):
            raise RuntimeError("clarification reservation has an invalid round")
        repo.enqueue_job(
            kind=JobKind.SEND_OUTBOUND,
            dedup_key=repo.send_outbound_dedup_key(email_id),
            run_id=run_id,
            email_id=email_id,
            conn=conn,
        )
        if candidates is not None:
            repo.set_alias_candidates(run_id, candidates, conn=conn)
        repo.set_pre_clarify_extracted(run_id, extracted, conn=conn)
        repo.set_clarification_round(run_id, snapshot_round + 1, conn=conn)
        repo.set_status(run_id, RunStatus.AWAITING_REPLY, conn=conn)
    wake.wake()
