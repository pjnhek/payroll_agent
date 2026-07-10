"""Alias-learning rule set (STRUCT-03, D-10): normalize/capture/write the
human-confirmation learning loop's WRITE side.

Carved out of orchestrator.py (Phase 13 Plan 02) — this is the single home for:
normalize_candidate (D-11-14 legacy-shape tolerance), bind_evidence_for_token
(GAP-4/CR-4 same-record evidence tie), write_aliases_if_safe (the write-side
collision-guarded persist), and safe_to_learn_alias (D-01b write-side collision
guard, relocated verbatim from reconcile_names.py).
"""
from __future__ import annotations

import logging
import uuid

from app.db import repo
from app.pipeline.reconcile_names import deterministic_match, normalize_name

logger = logging.getLogger("payroll_agent.orchestrator")


def normalize_candidate(value) -> dict:
    """Normalize an alias_candidates VALUE to the D-11-14 nested shape.

    {token: VALUE} historically stored VALUE as either None (never resolved) or
    a bare employee_id string (the OLD NEW-2 pre-vs-post-diff bind wrote this
    flat shape directly). D-11-14 replaces that with a richer per-token record
    {"suggested": id|None, "bound": id|None} so one column owns the full
    capture -> suggest -> bind lifecycle. Every site that READS an
    alias_candidates value (the bind check in resume_pipeline AND
    write_aliases_if_safe) must go through this helper so a legacy flat row
    from before this plan never raises AttributeError (Pitfall #6) — dict.get
    on a bare string/None would blow up without this normalization.

    - None            -> {"suggested": None, "bound": None}   (never resolved)
    - a str            -> {"suggested": None, "bound": value}  (OLD flat-bound
                          shape — the pre-vs-post diff bind wrote the resolved
                          id directly as the value; treat it as already-bound
                          so a live legacy row keeps behaving as "learned")
    - a dict            -> returned AS-IS (already the nested shape; idempotent)
    """
    if value is None:
        return {"suggested": None, "bound": None}
    if isinstance(value, dict):
        return value
    # Legacy flat-bound shape: a bare employee_id string.
    return {"suggested": None, "bound": value}


def bind_evidence_for_token(
    token: str,
    suggested_id: str,
    suggested_full_name: str | None,
    post_reconciliation: list,
) -> bool:
    """GAP-4/CR-4 fix: tie the bind decision to a SINGLE reconciliation record.

    The old bind-on-confirmation (D-11-15/NEW-2) computed two facts INDEPENDENTLY
    over the WHOLE run's post-resume reconciliation: (a) the suggested employee id
    newly appears as resolved SOMEWHERE, and (b) the token is gone from unresolved
    SOMEWHERE. Both facts can be satisfied by two completely UNRELATED
    reconciliation entries — e.g. "No, Dave didn't work this period; David worked
    5 hours separately" makes "David" (a new, separate submitted_name) resolve to
    the suggested id, while "Dave" simply vanishes (dropped, not resolved) — and
    the old logic bound Dave -> David with no actual confirmation.

    The fix: a bind requires ONE reconciliation entry whose submitted_name,
    normalized, equals EITHER the token's own normalized text OR the suggested
    employee's own normalized canonical full_name (a legitimate confirming reply
    restates that name), AND that SAME entry is resolved=True with
    matched_employee_id == suggested_id. This is the SAME-RECORD tie: the
    evidence must all come from one record, never two independently-satisfied
    whole-run facts.

    suggested_full_name may be None (the suggested employee could not be
    resolved from the roster at capture time, or is not found now) — the match
    set then only contains the token's own text, which is fail-closed (never
    fail-open): a missing full_name can only narrow what matches, never widen it.
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


def safe_to_learn_alias(
    token: str,
    target_employee,
    roster,
) -> bool:
    """Return True only if token uniquely resolves to target_employee on the full roster
    AFTER the alias is appended (D-01b write-side collision guard).

    Uses deterministic_match on a synthetic roster to simulate the post-write state.
    If deterministic_match returns None (ambiguous or no match) or resolves to a
    DIFFERENT employee, return False — do NOT learn (log and skip).

    The synthetic roster appends the token to the target employee's known_aliases only.
    This correctly detects:
    - Tokens already carried by 2+ employees (e.g. "D. Reyes" shared by David and
      Daniel Reyes): the synthetic roster still has 2 candidates → None → False.
    - Tokens that would introduce a NEW collision (token matches another employee's
      exact name or alias): synthetic roster has 2 candidates → None → False.
    - Unambiguous tokens: only target_employee carries the alias post-append → True.
    - Idempotent re-adds that are still unambiguous: True (safe to call twice).

    CRITICAL: Do NOT mutate the actual roster objects. The synthetic roster is a
    temporary computation object only (uses Pydantic v2 model_copy, never in-place).
    """
    synthetic_employees = []
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


def write_aliases_if_safe(run_id: uuid.UUID, run: dict, roster, conn=None) -> None:
    """Write any unambiguous, non-colliding alias candidates to employees.known_aliases.

    Called in delivery.deliver BEFORE set_status(SENT) (D-13b ordering — PATTERNS.md
    line 611). Must be wrapped in try/except at the call site: any internal exception
    is logged and swallowed so an alias-learning failure NEVER strands or fails a
    successfully-sent run (D-13b defensive isolation).

    For each token → candidate in alias_candidates (D-11-14 nested shape,
    normalized via normalize_candidate for legacy-flat-row tolerance,
    Pitfall #6):
    - Skip if cand["bound"] is None (never confirmed — no reply resolved the
      SUGGESTED employee; D-11-15 bind-on-confirmation never fired for this
      token).
    - Call safe_to_learn_alias (D-01b collision guard) — skip if False.
    - Call update_known_alias (D-01 idempotent JSONB append).
    - BATCH-SAFE: refresh current_roster after each accepted alias write so the NEXT
      iteration validates against the updated roster (MEDIUM finding — prevents multiple
      candidates in one approval batch from interacting unsafely).

    conn: optional caller-supplied connection (D-9-04 series) so this call's writes
    join the caller's enclosing transaction (e.g. delivery.deliver's finalize block)
    rather than auto-committing independently. When None (default), each internal
    repo call opens/commits its own pooled connection, exactly as before this plan.
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
            # Never confirmed (no reply resolved the SUGGESTED employee — D-11-15
            # bind-on-confirmation never fired for this token).
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
