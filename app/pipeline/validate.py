"""Stage 3 — deterministic field validation (LLM-06; review FIX 1).

A PURE function: typed values in, list[ValidationIssue] out, NO model, NO DB, NO
connection. It mirrors the issue-collection style of roster.py's
@model_validator (_require_compensation_field): inspect fields, accumulate
problems, return them rather than raising.

It emits issue_type="missing" for an absent REQUIRED hours field and cross-field
sanity issues. "Required" is pay-type aware: an HOURLY employee with no hours at
all is missing data the calc needs; a SALARIED employee computes from
annual_salary and legitimately reports no hours — so the roster is passed in (a
pure value, no DB) to decide what is required. The matched employee is found via
the reconciliation results (Layer 1 in this plan).

FIX 1 — what validate does NOT do: it does NOT (and structurally CANNOT) emit
`non_numeric` or `out_of_bounds` for the ge=0 case. A non-numeric/negative hours
value fails at the EXTRACTION parse boundary (ExtractedEmployee is Decimal|None +
ge=0 + extra="forbid"), routed through the client's one reflective retry → ERROR.
By the time a typed Extracted exists, every present hours value is already a
valid non-negative Decimal — so the typed path can never reach `non_numeric`.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from app.models.contracts import Extracted, RawFieldDrop
from app.models.roster import NameMatchResult, Roster, ValidationIssue

HOURS_FIELDS = (
    "hours_regular",
    "hours_overtime",
    "hours_vacation",
    "hours_sick",
    "hours_holiday",
)


def is_paid(v: Decimal | None) -> bool:
    """True iff value is present AND strictly positive (D-09 shared predicate).

    Decimal('0') is treated the same as None — both count as absent for the
    zero-hours gate. Phase 7.5 detect_field_regression will use this same
    predicate as its second call site.
    """
    return v is not None and v > 0


def _employee_pay_type(
    submitted_name: str,
    matches: list[NameMatchResult],
    roster: Roster,
) -> str | None:
    """Resolve the matched employee's pay_type via the reconciliation results."""
    for m in matches:
        if m.submitted_name == submitted_name and m.matched_employee_id is not None:
            for emp in roster.employees:
                if emp.id == m.matched_employee_id:
                    return emp.pay_type
    return None


def _employee_pay_periods_per_year(
    submitted_name: str,
    matches: list[NameMatchResult],
    roster: Roster,
) -> int | None:
    """Resolve the matched employee's pay_periods_per_year (None if unresolved).

    Mirrors _employee_pay_type exactly — same lookup, different field. Returns None
    when the name is unresolved (no matched_employee_id) so the OT rule skips it;
    the gate already blocks unresolved names from reaching a process run.
    """
    for m in matches:
        if m.submitted_name == submitted_name and m.matched_employee_id is not None:
            for emp in roster.employees:
                if emp.id == m.matched_employee_id:
                    return emp.pay_periods_per_year
    return None


def detect_field_regression(
    original: Extracted,
    resumed: Extracted,
    prior_matches: list | None,
    current_matches: list,
) -> list[RawFieldDrop]:
    """Detect field regressions between the original and resumed extraction (D-7.5-10).

    PUBLIC function — designed to be imported and called directly by orchestrator.py
    in Plan 03. It is NOT called internally by validate().

    D-7.5-10 THREE-PHASE ORDERING:
      This function is step 1 (DETECT). The orchestrator calls it on the RAW resumed
      extraction BEFORE backfill. validate() then receives the pre-computed drops via
      raw_field_drops= kwarg (step 3).

    R3-3 FIX (employee-id-keyed diff): reduces BOTH Extracted to
    {employee_id: ExtractedEmployee} maps using the match results BEFORE diffing.
    'M. Chen' in original and 'Maria Chen' in resumed, both resolving to the same
    employee_id, land in the same diff slot and produce a RawFieldDrop.

    Returns [] immediately when prior_matches is None (honest documented no-op).
    Production (Plan 03) always threads prior_matches from the pre-resume
    reconciliation; this branch never fires on the real resume path.
    """
    # Honest no-op: production always threads prior_matches from pre-resume reconciliation.
    if prior_matches is None:
        return []

    # Build id_to_orig: {employee_id: ExtractedEmployee} from original + prior_matches.
    name_to_id_prior: dict[str, UUID] = {
        m.submitted_name: m.matched_employee_id
        for m in prior_matches
        if m.resolved and m.matched_employee_id is not None
    }
    id_to_orig: dict[UUID, object] = {}
    for emp in original.employees:
        emp_id = name_to_id_prior.get(emp.submitted_name)
        if emp_id is not None:
            id_to_orig[emp_id] = emp  # last-wins (D-12)

    # Build id_to_resumed: {employee_id: ExtractedEmployee} from resumed + current_matches.
    name_to_id_current: dict[str, UUID] = {
        m.submitted_name: m.matched_employee_id
        for m in current_matches
        if m.resolved and m.matched_employee_id is not None
    }
    id_to_resumed: dict[UUID, object] = {}
    for emp in resumed.employees:
        emp_id = name_to_id_current.get(emp.submitted_name)
        if emp_id is not None:
            id_to_resumed[emp_id] = emp  # last-wins (D-12)

    # Diff: iterate employees present in BOTH maps (sorted for determinism, D-27).
    drops: list[RawFieldDrop] = []
    common_ids = sorted(set(id_to_orig) & set(id_to_resumed), key=str)
    for emp_id in common_ids:
        orig_emp = id_to_orig[emp_id]
        resumed_emp = id_to_resumed[emp_id]
        current_name = resumed_emp.submitted_name  # name the client used in the reply

        for field in HOURS_FIELDS:  # reuse module-level constant (DRY, D-09)
            original_val = getattr(orig_emp, field)
            resumed_val = getattr(resumed_emp, field)
            # is_paid: present AND strictly positive (D-09 shared predicate, D-25)
            if is_paid(original_val) and not is_paid(resumed_val):
                drops.append(
                    RawFieldDrop(
                        submitted_name=current_name,
                        field=field,
                        original_value=original_val,
                        resumed_value=resumed_val,  # None=absent, Decimal('0')=explicit zero (D-26)
                    )
                )

    return drops


def validate(
    extracted: Extracted,
    roster: Roster,
    matches: list[NameMatchResult],
    *,
    prior=None,
    prior_matches=None,
    resolved_drops=None,
    raw_field_drops=None,
) -> list[ValidationIssue]:
    """Emit field-validation issues for one run (LLM-06).

    Rules (deterministic, no model):
    - field_regression: pre-computed RawFieldDrop records passed via raw_field_drops=
      kwarg (D-7.5-10). Detection runs in the orchestrator via detect_field_regression()
      BEFORE backfill; validate() receives pre-computed drops and promotes them to
      ValidationIssues. NOT self-detecting.
    - missing: an HOURLY employee with no hours of any kind (all five None). A
      salaried employee with no hours is fine (calc uses annual_salary). An
      unresolved name's pay_type is unknown, so no missing-hours issue is raised
      for it here — the gate already blocks it on the unknown match.

    # prior= is kept for signature compatibility (Plan 01 threaded it). Detection runs
    # in the orchestrator via detect_field_regression(); pre-computed drops arrive via
    # raw_field_drops= (D-7.5-10).
    """
    issues: list[ValidationIssue] = []

    # D-7.5-10: promote pre-computed field regression drops to ValidationIssues.
    # Detection runs in the orchestrator (detect_field_regression on RAW extracted,
    # BEFORE backfill). This function is a consumer, NOT the detector.
    if raw_field_drops is not None and len(raw_field_drops) > 0:
        # TYPE CONTRACT: set[tuple[str, str]] keyed by (employee_id_str, field).
        _resolved_drops: set = resolved_drops or set()

        # Build name→id map for N8 suppression check.
        name_to_id_current: dict[str, UUID] = {
            m.submitted_name: m.matched_employee_id
            for m in matches
            if m.resolved and m.matched_employee_id is not None
        }

        for raw_drop in raw_field_drops:
            current_emp_id = name_to_id_current.get(raw_drop.submitted_name)
            if current_emp_id is None:
                continue  # submitted_name not resolved in current run — skip

            # N8 suppression check (KEY TYPE FIX): str(current_emp_id) to match
            # the (employee_id_str, field) set built by Plan 03 Step E2.
            # DO NOT use (current_emp_id, raw_drop.field) — UUID vs str never matches.
            # DO NOT use (raw_drop.submitted_name, field) — not stable across restated names.
            if (str(current_emp_id), raw_drop.field) in _resolved_drops:
                continue  # confirmed_dropped per D-15 — suppress re-flag

            resumed_display = (
                "absent" if raw_drop.resumed_value is None else str(raw_drop.resumed_value)
            )
            issues.append(
                ValidationIssue(
                    issue_type="field_regression",
                    field=f"{raw_drop.submitted_name}.{raw_drop.field}",
                    message=(
                        f"field regression: {raw_drop.field} was {raw_drop.original_value}, "
                        f"now {resumed_display}"
                    ),
                )
            )

    for emp in extracted.employees:
        any_hours = any(
            is_paid(getattr(emp, f)) for f in HOURS_FIELDS
        )
        if any_hours:
            continue
        pay_type = _employee_pay_type(emp.submitted_name, matches, roster)
        if pay_type == "hourly":
            issues.append(
                ValidationIssue(
                    field=f"{emp.submitted_name}.hours_regular",
                    issue_type="missing",
                    message=(
                        f"hourly employee {emp.submitted_name!r} has no hours "
                        "reported — required for the calc"
                    ),
                )
            )

    # D-05: Over-40-no-OT guard.
    # weekly (ppy=52): regular > 40 with no/zero OT → ambiguous (40+OT or straight time?)
    # biweekly (ppy=26): regular > 80 with no/zero OT → partial detection; honestly labeled
    # ppy in (24, 12): period boundaries cross workweeks — no flag (D-05 documented limitation)
    # Explicit hours_overtime=0 is treated same as absent per D-05 recommended decision:
    # a client who submits 0 OT for >40 regular hours is in the same ambiguous situation.
    for emp in extracted.employees:
        ppy = _employee_pay_periods_per_year(emp.submitted_name, matches, roster)
        if ppy is None:
            continue  # unresolved employee: gate already blocks it, no flag here
        ot = emp.hours_overtime
        # D-05/D-09: absent or zero == "no paid OT" (shared predicate)
        ot_missing = not is_paid(ot)
        if ppy == 52 and emp.hours_regular is not None and emp.hours_regular > 40 and ot_missing:
            issues.append(
                ValidationIssue(
                    field=f"{emp.submitted_name}.hours_overtime",
                    issue_type="missing",
                    message=(
                        f"weekly employee {emp.submitted_name!r} has "
                        f"{emp.hours_regular} regular hours with no overtime — "
                        "is that 40 regular + overtime, or straight time?"
                    ),
                )
            )
        elif ppy == 26 and emp.hours_regular is not None and emp.hours_regular > 80 and ot_missing:
            issues.append(
                ValidationIssue(
                    field=f"{emp.submitted_name}.hours_overtime",
                    issue_type="missing",
                    message=(
                        f"biweekly employee {emp.submitted_name!r} has "
                        f"{emp.hours_regular} regular hours with no overtime — >80 over 2 "
                        "weeks guarantees overtime in at least one week; please provide "
                        "the regular/overtime split. "
                        "(Note: partial detection only for biweekly periods.)"
                    ),
                )
            )
        # ppy in (24, 12): period boundaries cross workweeks — no flag (D-05 documented limitation)

    return issues
