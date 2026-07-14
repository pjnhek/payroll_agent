"""The WRITE side of the human-confirmation learning loop: persisting a nickname.

When the system asks "is 'Dave' your David Reyes?" and the client confirms, this module
is what makes the system stop asking next week. It is the only place an alias is ever
written to employees.known_aliases.

Invariants — every one of them exists to stop the system learning a WRONG name, which
would silently misroute a future employee's pay with no human in the loop:
  - Learn only on CONFIRMATION. A token is written only if a reply actually resolved the
    suggested employee (bind_evidence_for_token), never merely because the token stopped
    appearing.
  - SAME-RECORD evidence. The confirming reply and the resolution must come from one
    reconciliation record, not two independently-satisfied whole-run facts.
  - COLLISION-GUARDED write. safe_to_learn_alias simulates the post-write roster and
    refuses any token that would then be ambiguous.
  - NEVER strand a sent run. Callers wrap this in try/except: an alias-learning failure
    must never fail a payroll that was already delivered.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, cast

import psycopg

from app.db import repo
from app.models.roster import Employee, NameMatchResult, Roster
from app.pipeline.reconcile_names import deterministic_match, normalize_name

logger = logging.getLogger("payroll_agent.orchestrator")


def normalize_candidate(value: object) -> dict[str, Any]:
    """Normalize an alias_candidates VALUE to the nested {"suggested", "bound"} shape.

    alias_candidates is a JSONB {token: VALUE} column. VALUE now carries a per-token
    record — {"suggested": id|None, "bound": id|None} — so one column owns the whole
    capture -> suggest -> bind lifecycle. Older rows stored VALUE as either None or a
    bare employee_id string.

    EVERY site that reads an alias_candidates value must go through this helper. Calling
    dict.get() on a bare string or None raises AttributeError, so a single legacy row
    left in the database would crash the read path outright.

    - None   -> {"suggested": None, "bound": None}   (captured, never resolved)
    - a str  -> {"suggested": None, "bound": value}  (legacy flat shape: the value WAS the
                resolved employee id, so treat it as already bound and keep behaving as
                "learned" — demoting it would make the system re-ask a question the client
                already answered)
    - a dict -> returned AS-IS (already the nested shape; the helper is idempotent)
    """
    if value is None:
        return {"suggested": None, "bound": None}
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    # Legacy flat-bound shape: a bare employee_id string.
    return {"suggested": None, "bound": value}


def bind_evidence_for_token(
    token: str,
    suggested_id: str,
    suggested_full_name: str | None,
    post_reconciliation: list[object],
) -> bool:
    """Decide whether the client's reply actually CONFIRMED this token -> employee alias.

    The evidence must all come from ONE reconciliation record. A bind requires a single
    entry whose normalized submitted_name equals EITHER the token's own normalized text OR
    the suggested employee's normalized canonical full_name (a legitimate confirming reply
    restates one or the other), AND that SAME entry is resolved=True with
    matched_employee_id == suggested_id.

    Why the same-record tie is load-bearing: deriving the bind from two whole-run facts —
    "the suggested employee resolved SOMEWHERE" and "the token disappeared from unresolved
    SOMEWHERE" — lets two completely UNRELATED entries satisfy it. Consider the reply "No,
    Dave didn't work this period; David worked 5 hours separately." 'David' is a new,
    separate submitted_name that resolves to the suggested id, while 'Dave' simply vanishes
    (dropped, never confirmed). Two-fact logic would permanently learn Dave -> David from a
    reply that explicitly DENIED the match — and every future payroll would silently route
    Dave's hours to David.

    suggested_full_name may be None (the suggested employee was not resolvable from the
    roster at capture time, or is not found now). The match set then contains only the
    token's own text. That is fail-CLOSED by construction: a missing full_name can only
    narrow what matches, never widen it, so a lost name means "don't learn", never
    "learn something wrong".
    """
    match_names = {normalize_name(token)}
    if suggested_full_name is not None:
        match_names.add(normalize_name(suggested_full_name))

    if not isinstance(post_reconciliation, list):
        return False
    for entry in post_reconciliation:
        if not isinstance(entry, dict):
            continue
        submitted = normalize_name(entry.get("submitted_name") or "")
        if (
            submitted in match_names
            and entry.get("resolved") is True
            and str(entry.get("matched_employee_id")) == suggested_id
        ):
            return True
    return False


def confirmed_prior_matches(
    prior_matches: list[NameMatchResult] | None,
    current_matches: list[NameMatchResult],
    alias_candidates: dict[str, Any] | None,
    roster: Roster,
) -> list[NameMatchResult] | None:
    """Bridge the CLARIFIED employee's identity into prior_matches. PURE (no DB, no LLM).

    THE DEFECT THIS REPAIRS. `detect_field_regression` (and `backfill_extracted`) build
    their ORIGINAL-side identity map from `prior_matches` filtered to `resolved`. The
    employee a NAME clarification is about was, by definition, UNRESOLVED in the prior
    round — that is why we asked. So the snapshot employee is structurally invisible to
    the drop detector, and an hours line dropped on the clarification reply ("Sandy
    20r/10ot" -> "Yes, Sandra Kim, 40 regular") is silently accepted, backfilled, and
    PAID. The missing thing is an IDENTITY, so the fix belongs in `prior_matches` itself
    — repair it ONCE, here, and every consumer inherits the same identity map. Seeding
    each consumer separately would let them disagree about who the snapshot employee is.

    THE EVIDENCE STANDARD (do not weaken it). The prior round's token ("Sandy") and the
    reply's token ("Sandra Kim") are DIFFERENT STRINGS, and two tempting ways to connect
    them are wrong:

    - Re-reconciling the prior token against the roster FAILS: `write_aliases_if_safe`
      runs at the APPROVAL gate (delivery.deliver), so at resume time "Sandy" is still
      absent from employees.known_aliases and still resolves to nothing.
    - A whole-run SET DIFFERENCE ("employee S newly appears resolved AND the token
      vanished") is FORBIDDEN — it is precisely the two-independent-facts inference that
      `bind_evidence_for_token`'s docstring exists to reject. "No, Dave didn't work;
      David worked 5 hours separately" satisfies both facts and binds a match the client
      explicitly DENIED.

    So the bridge reuses `bind_evidence_for_token` VERBATIM: bind only when ONE
    reconciliation record ties both facts together. The LLM's suggestion (persisted in
    `alias_candidates` by clarification.clarify) merely PROPOSES employee S; the
    deterministic resolver — pure code over the roster — is what CONFIRMS it. That is the
    exact same evidence already trusted to PERMANENTLY write an alias to the roster, a
    strictly higher-stakes action than diffing two hours values.

    Guards, each of which SKIPS the seed on failure:
    - the resolved target id must parse as a UUID and must belong to this roster;
    - COLLISION GUARD: the target must NOT already be mapped by a `resolved`
      prior_matches entry. A prior entry that resolved DIRECTLY is the authoritative
      record and must win. The consumers' identity maps are last-entry-wins, so a bridged
      duplicate would silently overwrite the real snapshot employee with the clarified
      token's row — reporting a drop that never happened;
    - the token itself must not already be a resolved prior submitted_name.

    Returns a NEW list; NEVER mutates the caller's prior_matches. `prior_matches is None`
    returns None unchanged, preserving detect_field_regression's documented honest no-op.
    """
    if prior_matches is None:
        return None
    if not alias_candidates:
        return list(prior_matches)

    already_mapped_ids: set[uuid.UUID] = {
        m.matched_employee_id
        for m in prior_matches
        if m.resolved and m.matched_employee_id is not None
    }
    already_mapped_names: set[str] = {
        m.submitted_name
        for m in prior_matches
        if m.resolved and m.matched_employee_id is not None
    }

    # bind_evidence_for_token reads dicts via .get(), not Pydantic models — serialize once.
    current_as_dicts: list[object] = [m.model_dump(mode="json") for m in current_matches]

    bridged: list[NameMatchResult] = list(prior_matches)
    for token, value in alias_candidates.items():
        cand = normalize_candidate(value)  # a legacy flat row would otherwise crash .get()

        bound = cand.get("bound")
        if bound is not None:
            # ALREADY confirmed — by a prior round's bind, or by the operator ticking
            # "remember this alias" at /resolve. No further evidence needed.
            target_str = str(bound)
        else:
            suggested = cand.get("suggested")
            if suggested is None:
                continue  # nothing was ever proposed for this token
            target_str = str(suggested)
            suggested_full_name = next(
                (e.full_name for e in roster.employees if str(e.id) == target_str), None
            )
            if not bind_evidence_for_token(
                token, target_str, suggested_full_name, current_as_dicts
            ):
                # The client never confirmed this token (or explicitly denied it).
                # This is the whole no-guess guarantee.
                continue

        try:
            target = uuid.UUID(target_str)
        except (ValueError, AttributeError, TypeError):
            continue
        if not any(e.id == target for e in roster.employees):
            continue  # not a member of THIS business's roster
        if target in already_mapped_ids or token in already_mapped_names:
            continue  # COLLISION GUARD — the direct prior resolution wins

        bridged.append(
            NameMatchResult(
                submitted_name=token,
                matched_employee_id=target,
                source="alias",
                resolved=True,
                reason="confirmed at clarification reply",
            )
        )
        # Bar a SECOND candidate in this same call from re-colliding onto this employee.
        already_mapped_ids.add(target)
        already_mapped_names.add(token)

    return bridged


def safe_to_learn_alias(
    token: str,
    target_employee: Employee,
    roster: Roster,
) -> bool:
    """Write-side collision guard: True only if token uniquely resolves to target_employee
    on the FULL roster once the alias has been appended.

    Learning an ambiguous alias is worse than learning nothing: it bakes a permanent
    collision into the roster, so every future run carrying that token gates to
    clarification (or, if the ambiguity were ever resolved by guessing, pays the wrong
    person). This guard simulates the post-write world before committing to it.

    It builds a synthetic roster with the token appended to target_employee's
    known_aliases and re-runs deterministic_match against it. None (ambiguous or no
    match), or a match to a DIFFERENT employee, means do NOT learn — log and skip.
    This catches:
    - Tokens already carried by 2+ employees ("D. Reyes" shared by David and Daniel
      Reyes): the synthetic roster still has 2 candidates -> None -> False.
    - Tokens that would introduce a NEW collision (the token matches another employee's
      exact name or alias): 2 candidates -> None -> False.
    - Unambiguous tokens: only target_employee carries the alias post-append -> True.
    - Idempotent re-adds that remain unambiguous -> True (safe to call twice).

    CRITICAL: never mutate the real roster objects. The synthetic roster is a throwaway
    computation object (Pydantic model_copy, never in-place) — mutating the caller's
    roster here would corrupt the resolution facts the live run is still deciding on.
    """
    synthetic_employees: list[Employee] = []
    for emp in roster.employees:
        if emp.id == target_employee.id:
            new_aliases = list(emp.known_aliases) + [token]
            synthetic_employees.append(
                emp.model_copy(update={"known_aliases": new_aliases})
            )
        else:
            synthetic_employees.append(emp)
    synthetic_roster = roster.model_copy(update={"employees": synthetic_employees})
    result = deterministic_match(token, synthetic_roster)
    return result is not None and result.matched_employee_id == target_employee.id


def write_aliases_if_safe(
    run_id: uuid.UUID,
    run: dict[str, Any],
    roster: Roster,
    conn: psycopg.Connection | None = None,
) -> None:
    """Write any unambiguous, non-colliding alias candidates to employees.known_aliases.

    Called from delivery.deliver BEFORE set_status(SENT). The call site MUST wrap this in
    try/except: any exception in here is logged and swallowed, because an alias-learning
    failure must NEVER strand or fail a payroll run that was otherwise sent successfully.
    Learning a nickname is a convenience; delivering payroll is the product.

    For each token -> candidate in alias_candidates (read through normalize_candidate so a
    legacy flat row cannot crash the loop):
    - Skip if cand["bound"] is None — the client never confirmed this token, so there is
      nothing to learn. This is the guard that keeps a merely-abandoned token from being
      recorded as an accepted alias.
    - Run safe_to_learn_alias (collision guard) — skip if False.
    - Call update_known_alias (an idempotent JSONB append).
    - Refresh current_roster after EACH accepted write, so the next candidate in the same
      batch is validated against the roster as it now stands. Validating a whole batch
      against the stale pre-batch roster would let two candidates that individually look
      safe combine into a collision that the guard never sees.

    conn: an optional caller-supplied connection, so these writes join the caller's
    enclosing transaction (e.g. delivery.deliver's finalize block) instead of
    auto-committing independently. When None, each repo call opens and commits its own
    pooled connection.
    """
    import uuid as _uuid
    run_data = repo.load_run(run_id, conn=conn)
    if run_data is None:
        return
    alias_candidates = run_data.get("alias_candidates") or {}
    if not alias_candidates:
        return

    current_roster = roster  # start with the roster already loaded by delivery.deliver
    for token, value in alias_candidates.items():
        cand = normalize_candidate(value)
        employee_id_str = cand.get("bound")
        if employee_id_str is None:
            # Never confirmed: no reply ever resolved the suggested employee, so the
            # bind-on-confirmation check never fired for this token. Nothing to learn.
            logger.info(
                "alias write skipped for %r: no bound employee_id (never confirmed)",
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

        if not safe_to_learn_alias(token, target_employee, current_roster):
            logger.info(
                "alias write skipped for %r → %s: collision guard fired",
                token,
                employee_id,
            )
            continue

        written = repo.update_known_alias(employee_id, token, conn=conn)
        if written:
            logger.info("alias learned: %r → %s", token, employee_id)
            # Refresh the roster after each accepted write so the next candidate in this
            # batch is checked against the roster as it NOW stands. Reusing the stale
            # pre-batch roster would let two candidates that are each individually safe
            # combine into a collision the guard never sees.
            current_roster = repo.load_roster_for_business(run["business_id"], conn=conn)
        else:
            logger.info(
                "alias write no-op for %r → %s: already present (idempotent)",
                token,
                employee_id,
            )
