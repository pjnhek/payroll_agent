"""Stage 4 — the DECISION stage + THE CODE GATE (LLM-07/08/09). THE THESIS.

The model proposes; code disposes. decide() does TWO structurally-separate things:
  (a) ask the LLM for an advisory model_action ("process"|"request_clarification")
      + reasons — the ONLY LLM call here; and
  (b) compute the code-owned final_action that hard-blocks regardless of what the
      model said.

final_action is the SOLE branch source for the orchestrator, dashboard, and eval —
nothing downstream EVER reads model_action. A model talked into "process" by a
prompt-injected email is still code-blocked on a sub-0.8 / missing-field name
(T-02-08).

A PURE function: typed values in, Decision out. NO DB, NO connection. Decision has
NO run_id field, so decide() returns a Decision directly (no run_id stamping —
that pattern applies only to extract()/Extracted, FIX A).

Gate rules (code, no model) — force final_action="request_clarification" if ANY:
  0. No extractable employees: extracted.employees == [] (CR-01). The other rules
     are reason-additive (they iterate matches/issues), so a zero-employee run would
     otherwise leave the gate empty and collapse final_action to model_action.
  1. Sub-threshold confidence: any NameMatchResult.confidence < Decimal("0.8").
     Evaluated PER NAME (D-A3-03a) — NOT against the collapsed scalar, so one 0.6
     name cannot hide behind three 1.0s.
  2. Unresolved name: match_type == "unknown" or matched_employee_id is None.
  3. Missing required field: any ValidationIssue(issue_type="missing").
  4. One-to-one mapping violations (LLM-09) via check_one_to_one() — a real,
     called function returning gate_reasons; the three collision rules land in
     Plan 03 by extending it.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.llm import client as llm_client
from app.llm.prompts import decide as decide_prompt
from app.models.contracts import Decision, Extracted
from app.models.roster import NameMatchResult, ValidationIssue


class _ModelAdvice(BaseModel):
    """The model's advisory output: action + reasons. The code gate owns the rest."""

    model_config = ConfigDict(extra="forbid")

    model_action: Literal["process", "request_clarification"]
    reasons: list[str] = []

# The locked confidence threshold (CLAUDE.md / D-A4-01). Decimal, never float —
# the all-Decimal contract convention, and a float 0.8 has no exact binary form.
_THRESHOLD = Decimal("0.8")


def check_one_to_one(
    matches: list[NameMatchResult],
    extracted: Extracted,
) -> list[str]:
    """Enforce the submitted-name → employee one-to-one mapping (LLM-09, D-A3-02).

    Returns a list of gate_reasons, one per collision. The SAME real function
    shipped empty-but-real in Plan 02 (signature UNCHANGED; still called inside
    decide()), now extended with the three pure-code collision rules so a confident
    model can never let a name silently collapse onto another employee:

      (a) two DISTINCT submitted names resolve to the SAME matched_employee_id;
      (b) a submitted name is DUPLICATED in the extraction;
      (c) a submitted name resolves to NO roster employee (matched_employee_id is
          None) — overlaps decide()'s Rule 2 but kept distinct as its own
          collision gate_reason for legibility/audit.

    A clean, collision-free mapping returns [] (no false gate on a legitimately
    clean run), preserving the Plan-02 stub-shape contract.
    """
    reasons: list[str] = []

    # (a) two distinct submitted names → the same employee_id.
    by_employee: dict = {}
    for m in matches:
        if m.matched_employee_id is None:
            continue
        by_employee.setdefault(m.matched_employee_id, [])
        # Track only DISTINCT submitted names per employee (a duplicate name is
        # rule (b), not a two-names-to-one collision).
        if m.submitted_name not in by_employee[m.matched_employee_id]:
            by_employee[m.matched_employee_id].append(m.submitted_name)
    for emp_id, names in by_employee.items():
        if len(names) > 1:
            reasons.append(
                "two submitted names resolve to one employee: "
                + " + ".join(sorted(names))
                + f" → {emp_id}"
            )

    # (b) a duplicated submitted name (same name extracted more than once).
    seen: set = set()
    flagged: set = set()
    for m in matches:
        if m.submitted_name in seen and m.submitted_name not in flagged:
            reasons.append(f"duplicate submitted name: {m.submitted_name}")
            flagged.add(m.submitted_name)
        seen.add(m.submitted_name)

    # (c) a name resolving to no roster employee.
    for m in matches:
        if m.matched_employee_id is None:
            reasons.append(
                f"{m.submitted_name}: resolves to no roster employee (one-to-one)"
            )

    return reasons


def _ask_model(
    extracted: Extracted,
    matches: list[NameMatchResult],
    issues: list[ValidationIssue],
    *,
    llm,
) -> tuple[str, list[str]]:
    """Advisory-only LLM call → (model_action, reasons). Never binding."""
    messages = decide_prompt.build_messages(extracted, matches, issues)
    payload = llm.call_structured("decision", messages, _ModelAdvice)
    return payload.model_action, list(payload.reasons)


def decide(
    extracted: Extracted,
    matches: list[NameMatchResult],
    issues: list[ValidationIssue],
    *,
    llm=llm_client,
) -> Decision:
    """Compute the gated Decision. final_action is code-owned and binding."""
    model_action, reasons = _ask_model(extracted, matches, issues, llm=llm)

    gate_reasons: list[str] = []
    unresolved: list[str] = []

    # Rule 0 — a run with NO extractable employees is never auto-processable (CR-01).
    # Every other rule is reason-ADDITIVE: it fires only by iterating over `matches`
    # / `issues`. A degenerate run with zero extracted employees (an empty/junk/
    # prompt-injected email yielding "employees": []) therefore leaves gate_reasons
    # empty, collapses final_action = model_action, and lets a "process" advisory
    # reach an EMPTY payroll the operator is told is clean. This explicit rule fails
    # the gate CLOSED on that case. It does NOT touch the per-name confidence test
    # below: that still evaluates EACH NameMatchResult.confidence against
    # Decimal("0.8"), never the collapsed scalar.
    if not extracted.employees:
        gate_reasons.append("no employees could be extracted from the email")

    # Rule 1 — per-name sub-0.8 confidence (EACH name, not the collapsed scalar).
    for m in matches:
        if m.confidence < _THRESHOLD:
            if m.submitted_name not in unresolved:
                unresolved.append(m.submitted_name)
            gate_reasons.append(
                f"{m.submitted_name}: confidence {m.confidence} < {_THRESHOLD}"
            )

    # Rule 2 — unresolved name (no roster match).
    for m in matches:
        if m.match_type == "unknown" or m.matched_employee_id is None:
            if m.submitted_name not in unresolved:
                unresolved.append(m.submitted_name)
            gate_reasons.append(f"{m.submitted_name}: unresolved (no roster match)")

    # Rule 3 — missing required field.
    missing = [i.field for i in issues if i.issue_type == "missing"]
    gate_reasons += [f"missing required field: {f}" for f in missing]

    # Rule 4 — one-to-one mapping (pure code; empty-but-real in this plan).
    gate_reasons += check_one_to_one(matches, extracted)

    gate_fired = bool(gate_reasons)
    final_action = "request_clarification" if gate_fired else model_action

    # Confidence collapse = min() over all names (weakest link); 1.0 for a clean
    # run with no LLM-layer names (D-A3-03a). Audit/eval scalar ONLY — the gate
    # above evaluates EACH name, never this scalar.
    confidence = min(
        (m.confidence for m in matches), default=Decimal("1.0")
    )

    return Decision(
        model_action=model_action,
        gate_triggered=(final_action != model_action) or gate_fired,
        gate_reasons=gate_reasons,
        final_action=final_action,
        unresolved_names=unresolved,
        missing_fields=missing,
        confidence=confidence,
        reasons=reasons,
    )
