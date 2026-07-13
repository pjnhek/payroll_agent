"""The decision stage: whether a payroll run may be processed or must ask the client.

decide() is PURE CODE over resolution facts — the system's central claim. It computes
final_action deterministically from the resolved names, run-level collision checks, and
missing fields; that final_action is the SOLE branch source for the orchestrator, the
dashboard, and the eval.

Invariants (each one is what keeps this stage from guessing with money):
  - NO model call. There is no model-proposed action to diverge from, so a prompt-injected
    or hallucinated extraction can never reach a money-moving decision.
  - NO score, NO probability, NO cutoff. A name either resolves against the roster in
    code or it does not. Grading a match on a number and paying anything above a cutoff
    would, by construction, pay somebody on a guess at the margin. (A source-level guard
    test enforces that this module never acquires such a number.)
  - Collisions ALWAYS clarify. Picking a winner between two names that map to one employee
    would be a guess with money; the run stops and asks the client instead.
  - The gate FAILS CLOSED. Every rule below only ever ADDS a reason to clarify, so any path
    that produces no facts (empty extraction, mismatched resolution records) must have an
    explicit rule — otherwise it would silently collapse to "process".
  - A PURE function: typed values in, Decision out. NO DB, NO connection, NO model. The
    eval imports this exact function, so the measured decision is the shipped decision.

Gate rules — force final_action="request_clarification" if ANY:
  0. No extractable employees (extracted.employees == []).
  1. Unresolved name: any NameMatchResult with resolved is False — the name is added to
     unresolved_names with a gate_reason.
  2. Missing required field: any ValidationIssue(issue_type="missing").
  3. Run-level collisions via check_one_to_one(). Collisions are RUN-LEVEL: a name can be
     resolved=True while the run still clarifies on a cross-name collision (two resolved
     names mapping to one employee, or a duplicated submitted name). Kept SEPARATE from
     per-name resolved so two confidently-resolved names can never silently collapse onto
     one employee — which would pay one person twice and the other nothing.
"""
from __future__ import annotations

from uuid import UUID

from app.models.contracts import Decision, Extracted
from app.models.roster import NameMatchResult, ValidationIssue


def check_one_to_one(
    matches: list[NameMatchResult],
    extracted: Extracted,
) -> list[str]:
    """Enforce the submitted-name -> employee one-to-one mapping at the RUN level.

    Returns a list of gate_reasons, one per collision. This is a run-level authority that
    is independent of per-name resolved: a name can be resolved=True and still participate
    in a collision, so two confidently-resolved names can never silently collapse onto one
    employee (paying one twice and the other nothing). Collision shapes:

      (a) two DISTINCT submitted names resolve to the SAME matched_employee_id
          (even when both are resolved=True);
      (b) a submitted name is DUPLICATED in the extraction.

    A name that resolves to no employee is already unresolved (handled as Rule 1 in
    decide); it is NOT re-counted here, so collisions stay distinct from the
    unresolved gate. A clean, collision-free mapping returns [].
    """
    reasons: list[str] = []

    # (a) two distinct submitted names -> the same employee id.
    by_employee: dict[UUID, list[str]] = {}
    for m in matches:
        if m.matched_employee_id is None:
            continue
        by_employee.setdefault(m.matched_employee_id, [])
        # Track only DISTINCT submitted names per employee (a duplicate name is
        # rule (b), not a two-names-to-one collision).
        if m.submitted_name not in by_employee[m.matched_employee_id]:
            by_employee[m.matched_employee_id].append(m.submitted_name)
    for _emp_id, names in by_employee.items():
        if len(names) > 1:
            # gate_reasons are CLIENT-FACING: compose_email/clarify copy them verbatim
            # into the clarification email. Never include the internal employee UUID here —
            # it leaks a database identifier to the client and tells them nothing. The
            # submitted names are what they need to disambiguate.
            reasons.append(
                "two submitted names resolve to one employee: "
                + " + ".join(sorted(names))
            )

    # (b) a duplicated submitted name (same name extracted more than once).
    seen: set[str] = set()
    flagged: set[str] = set()
    for m in matches:
        if m.submitted_name in seen and m.submitted_name not in flagged:
            reasons.append(f"duplicate submitted name: {m.submitted_name}")
            flagged.add(m.submitted_name)
        seen.add(m.submitted_name)

    return reasons


def decide(
    extracted: Extracted,
    matches: list[NameMatchResult],
    issues: list[ValidationIssue],
) -> Decision:
    """Compute the deterministic Decision. final_action is code-owned and binding."""
    gate_reasons: list[str] = []
    unresolved: list[str] = []

    # Rule 0 — a run with NO extractable employees is never auto-processable. Every other
    # rule is reason-ADDITIVE: it fires only by iterating over `matches` / `issues`. A
    # degenerate run with zero extracted employees (an empty, junk, or injected email
    # yielding "employees": []) would otherwise leave gate_reasons empty and collapse to
    # "process" — auto-approving a payroll run with no people in it. This rule fails the
    # gate CLOSED on that case.
    if not extracted.employees:
        gate_reasons.append("no employees could be extracted from the email")

    # Rule 0b — fail closed if `matches` is not one-for-one with the extracted employees.
    # decide() is a PURE public function that the eval calls with arbitrary inputs, so it
    # must not trust that reconcile_names produced exactly one match per submitted name.
    # A missing / extra / duplicate resolution record means an employee could be silently
    # dropped from a "process" run and go unpaid — gate closed instead.
    submitted_names = sorted(e.submitted_name for e in extracted.employees)
    resolution_names = sorted(m.submitted_name for m in matches)
    if extracted.employees and submitted_names != resolution_names:
        gate_reasons.append(
            "resolution records do not match the extracted employees one-for-one"
        )

    # Rule 1 — any name the resolver could not uniquely resolve (resolved is False).
    for m in matches:
        if m.resolved is False:
            if m.submitted_name not in unresolved:
                unresolved.append(m.submitted_name)
            gate_reasons.append(f"{m.submitted_name}: unresolved (no roster match)")

    # Rule 2 — missing required field.
    missing = [i.field for i in issues if i.issue_type == "missing"]
    gate_reasons += [f"missing required field: {f}" for f in missing]

    # Rule 2b — a field that was present in an earlier round has regressed to absent.
    # Regressions feed gate_reasons ONLY; Decision.missing_fields is deliberately NOT
    # widened to include them, because missing_fields drives the "what do we still need"
    # copy and a regressed field is a different question from a never-supplied one.
    regressions = [i.field for i in issues if i.issue_type == "field_regression"]
    gate_reasons += [f"field regression: {f}" for f in regressions]

    # Rule 3 — run-level collisions: kept distinct from Rule 1 so a name that is
    # resolved=True can still gate the run on a cross-name collision.
    gate_reasons += check_one_to_one(matches, extracted)

    final_action = "request_clarification" if gate_reasons else "process"

    return Decision(
        final_action=final_action,
        gate_reasons=gate_reasons,
        unresolved_names=unresolved,
        missing_fields=missing,
        resolutions=matches,
    )
