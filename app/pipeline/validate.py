"""Deterministic field validation — the issues that make a run clarify instead of pay.

A PURE function: typed values in, list[ValidationIssue] out. NO model, NO DB, NO
connection. It mirrors roster.py's @model_validator style: inspect fields, accumulate
problems, return them rather than raising.

It emits issue_type="missing" for an absent REQUIRED hours field. "Required" is PAY-TYPE
AWARE, and that distinction is money-relevant in both directions: an HOURLY employee with
no hours at all is missing the data the calc needs (paying them would compute $0 gross),
while a SALARIED employee legitimately reports no hours (their gross comes from
annual_salary, so flagging them would stall every salaried run). The roster is therefore
passed in as a pure value (no DB) so the rule can ask what each employee actually is; the
matched employee is found via the reconciliation results.

What validate does NOT do: it does not (and structurally cannot) emit `non_numeric` or
`out_of_bounds`. A non-numeric or negative hours value fails earlier, at the EXTRACTION
parse boundary (ExtractedEmployee is Decimal|None + ge=0 + extra="forbid"), and is routed
through the client's one reflective retry. By the time a typed Extracted exists, every
present hours value is already a valid non-negative Decimal.

This module also hosts TWO pure cross-round hours-diff detectors over ONE shared pairing
(_pair_by_employee_id), and the split between them is deliberate:

  detect_field_regression  paid -> UNPAID (dropped, or explicitly zeroed). Its RawFieldDrops
                           become ValidationIssues and DO GATE the run — the client is asked.
  detect_hours_changes     paid -> PAID, different value. Its HoursChanges are DISPLAY-ONLY:
                           never passed to validate(), never passed to decide(), rendered to
                           the human operator at the approval gate. HoursChange has no
                           `issue_type`, so it cannot become a ValidationIssue — the type is
                           the enforcement, not the convention.

Do not merge them. Their triggers are disjoint on purpose (a zeroed line is a REGRESSION,
not a change, because is_paid(Decimal('0')) is False), so no money event is ever
double-reported through two mechanisms. Every cross-round change a client makes is either
gated by code or visible to the human; neither is silently swallowed.
"""
from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from app.models.contracts import Extracted, ExtractedEmployee, HoursChange, RawFieldDrop
from app.models.roster import NameMatchResult, Roster, ValidationIssue

HOURS_FIELDS = (
    "hours_regular",
    "hours_overtime",
    "hours_vacation",
    "hours_sick",
    "hours_holiday",
)


def is_paid(v: Decimal | None) -> bool:
    """True iff value is present AND strictly positive.

    Decimal('0') is treated the same as None — both count as "not paid". This is the ONE
    shared predicate for "were these hours actually paid?", used by both the missing-hours
    rule and detect_field_regression. Keeping it shared is what stops the two rules from
    disagreeing about whether an explicit zero counts, which would let a dropped hours
    line slip through one check while the other flags it.
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


def _id_keyed(
    extracted: Extracted,
    matches: list[NameMatchResult],
) -> dict[UUID, ExtractedEmployee]:
    """Reduce one Extracted to {employee_id: ExtractedEmployee} via its match list.

    Only `resolved` matches with a non-None matched_employee_id contribute. Last entry
    wins if one employee appears twice under two names.
    """
    name_to_id: dict[str, UUID] = {
        m.submitted_name: m.matched_employee_id
        for m in matches
        if m.resolved and m.matched_employee_id is not None
    }
    id_keyed: dict[UUID, ExtractedEmployee] = {}
    for emp in extracted.employees:
        emp_id = name_to_id.get(emp.submitted_name)
        if emp_id is not None:
            id_keyed[emp_id] = emp
    return id_keyed


def _pair_by_employee_id(
    original: Extracted,
    resumed: Extracted,
    prior_matches: list[NameMatchResult],
    current_matches: list[NameMatchResult],
) -> list[tuple[ExtractedEmployee, ExtractedEmployee]]:
    """Pair the SAME PERSON across the round boundary. The one identity map, shared.

    Keyed by EMPLOYEE ID, never by submitted name: 'M. Chen' in the original and 'Maria
    Chen' in the reply are one person, and a name-keyed pairing would see two strangers —
    the drop (or the change) would go unnoticed.

    Both hours-diff detectors in this module call THIS helper. Exactly one implementation
    of the pairing may exist here: two copies could drift on the resolved-filter, the
    last-entry-wins rule, or the ordering, and the two detectors would then disagree about
    who the snapshot employee is — over the same money.

    Sorted by employee id string so BOTH detectors' output order is deterministic (the
    regression reasons become client-facing email copy; the changes become operator-facing
    page copy — unstable ordering churns both).
    """
    id_to_orig = _id_keyed(original, prior_matches)
    id_to_resumed = _id_keyed(resumed, current_matches)
    common_ids = sorted(set(id_to_orig) & set(id_to_resumed), key=str)
    return [(id_to_orig[i], id_to_resumed[i]) for i in common_ids]


def detect_field_regression(
    original: Extracted,
    resumed: Extracted,
    prior_matches: list[NameMatchResult] | None,
    current_matches: list[NameMatchResult],
) -> list[RawFieldDrop]:
    """Detect hours that were present in the original email but vanished from the reply.

    A client answering a clarification often re-types the whole roster and silently drops
    a line they already sent. Backfill would then quietly restore the old value with no
    trace — so detection MUST run on the RAW resumed extraction, BEFORE backfill. This is
    that detection step; the orchestrator calls it and hands the resulting drops to
    validate() via the raw_field_drops= kwarg. validate() is the consumer, not the
    detector — do not move detection into it, or it will run post-backfill and see nothing.

    PUBLIC function: the orchestrator imports and calls it directly. It is NOT called
    internally by validate().

    The diff is keyed by EMPLOYEE ID, not by submitted name (see _pair_by_employee_id).

    Returns [] immediately when prior_matches is None (an honest, documented no-op).
    Production always threads prior_matches from the pre-resume reconciliation, so this
    branch never fires on the real resume path.
    """
    # Honest no-op: production always threads prior_matches from pre-resume reconciliation.
    if prior_matches is None:
        return []

    drops: list[RawFieldDrop] = []
    for orig_emp, resumed_emp in _pair_by_employee_id(
        original, resumed, prior_matches, current_matches
    ):
        current_name = resumed_emp.submitted_name  # name the client used in the reply

        for field in HOURS_FIELDS:
            original_val = getattr(orig_emp, field)
            resumed_val = getattr(resumed_emp, field)
            # A regression is "was paid, now isn't" — is_paid() treats an explicit 0 the
            # same as absent, so zeroing out a line is caught, not just deleting it.
            if is_paid(original_val) and not is_paid(resumed_val):
                drops.append(
                    RawFieldDrop(
                        submitted_name=current_name,
                        field=field,
                        original_value=original_val,
                        # None means the line is gone; Decimal('0') means explicitly zeroed.
                        # Both are regressions; the distinction is preserved for the copy.
                        resumed_value=resumed_val,
                    )
                )

    return drops


def detect_hours_changes(
    original: Extracted,
    resumed: Extracted,
    prior_matches: list[NameMatchResult] | None,
    current_matches: list[NameMatchResult],
) -> list[HoursChange]:
    """Detect hours values the client CHANGED (paid -> paid, different) across a round.

    PUBLIC pure function, DISPLAY-ONLY. The orchestrator calls it, persists the result to
    payroll_runs.hours_changes, and the operator sees it on the approval page. It is NEVER
    passed to validate() and NEVER reaches decide(): `HoursChange` has no `issue_type`, so
    it structurally cannot become a `ValidationIssue`. That type wall is the guarantee.

    Why it is not a gate: the accumulation design stands — a client's corrected value WINS
    and is PAID without re-asking (tests/test_multiround_context_edge.py). The gap this
    closes is that the human APPROVING the payroll could not see the change had happened.
    Every money-moving change a client makes across a clarification round is now either
    GATED BY CODE (a drop -> clarify) or VISIBLE TO THE HUMAN (a change -> banner).
    Neither is silently swallowed.

    The trigger is DISJOINT from detect_field_regression's, and that is load-bearing: a
    drop (10 -> None) and an explicit zeroing (10 -> Decimal('0')) are both paid -> UNPAID
    (is_paid(Decimal('0')) is False), so they belong to the regression detector and are
    silent here. Otherwise one money event would be reported twice through two mechanisms.
    An ADDED line (None -> 40) is an explicit non-goal: paid->paid only.

    Like detect_field_regression: runs on the RAW pre-backfill extraction (post-backfill
    the change is papered over), and returns [] when prior_matches is None — the same
    honest no-op.
    """
    if prior_matches is None:
        return []

    changes: list[HoursChange] = []
    for orig_emp, resumed_emp in _pair_by_employee_id(
        original, resumed, prior_matches, current_matches
    ):
        current_name = resumed_emp.submitted_name  # name the client used in the reply

        for field in HOURS_FIELDS:
            original_val = getattr(orig_emp, field)
            resumed_val = getattr(resumed_emp, field)
            if (
                is_paid(original_val)
                and is_paid(resumed_val)
                and original_val != resumed_val
            ):
                changes.append(
                    HoursChange(
                        submitted_name=current_name,
                        field=field,
                        original_value=original_val,
                        resumed_value=resumed_val,
                    )
                )

    return changes


def validate(
    extracted: Extracted,
    roster: Roster,
    matches: list[NameMatchResult],
    *,
    prior: Extracted | None = None,
    prior_matches: list[NameMatchResult] | None = None,
    resolved_drops: set[tuple[str, str]] | None = None,
    raw_field_drops: list[RawFieldDrop] | None = None,
) -> list[ValidationIssue]:
    """Emit field-validation issues for one run.

    Rules (deterministic, no model):
    - field_regression: pre-computed RawFieldDrop records arrive via the raw_field_drops=
      kwarg. Detection runs in the orchestrator (detect_field_regression) on the RAW
      resumed extraction BEFORE backfill; validate() only promotes those drops to
      ValidationIssues. It is deliberately NOT self-detecting — by the time validate()
      runs, backfill has already restored the dropped values and there is nothing to see.
    - missing: an HOURLY employee with no hours of any kind. A salaried employee with no
      hours is fine (the calc uses annual_salary). An unresolved name has an unknown
      pay_type, so no missing-hours issue is raised for it here — the decision gate
      already blocks the run on the unresolved match.

    prior= is kept for signature compatibility; detection lives in the orchestrator.
    """
    issues: list[ValidationIssue] = []

    # Promote pre-computed field-regression drops to ValidationIssues. This function is
    # the consumer, NOT the detector (see the docstring: detection must precede backfill).
    if raw_field_drops is not None and len(raw_field_drops) > 0:
        # Keyed by (employee_id_str, field) — see the suppression check below.
        _resolved_drops: set[tuple[str, str]] = resolved_drops or set()

        # name -> employee id, for the already-confirmed-drop suppression check.
        name_to_id_current: dict[str, UUID] = {
            m.submitted_name: m.matched_employee_id
            for m in matches
            if m.resolved and m.matched_employee_id is not None
        }

        for raw_drop in raw_field_drops:
            current_emp_id = name_to_id_current.get(raw_drop.submitted_name)
            if current_emp_id is None:
                continue  # submitted_name not resolved in current run — skip

            # Suppress drops the client has already confirmed are intentional, so the
            # system stops re-asking the same question every round.
            # The key MUST be (str(employee_id), field):
            #   - a raw UUID key never compares equal to the stored str key, so every drop
            #     would be re-flagged forever and the run could never leave clarification;
            #   - a submitted_name key is not stable across a restated/corrected name, so
            #     a confirmed drop would resurface the moment the client re-types the name.
            if (str(current_emp_id), raw_drop.field) in _resolved_drops:
                continue  # already confirmed dropped by the client — do not re-flag

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

    # Over-40-no-OT guard. calculate() pays overtime ONLY when the client reports it
    # explicitly, so a client who lumps overtime into hours_regular would be silently
    # UNDERPAID (their OT hours paid at straight time). This rule refuses to guess which
    # reading is right and asks the client instead.
    #   weekly (ppy=52):   regular > 40 with no/zero OT → ambiguous (40 + OT, or straight time?)
    #   biweekly (ppy=26): regular > 80 with no/zero OT → >80 across two weeks guarantees OT in
    #                      at least one of them. Partial detection only — 45 + 35 across the two
    #                      weeks is 80 total yet still has 5 OT hours, and we cannot see the
    #                      per-week split. The message says so honestly rather than implying
    #                      the check is complete.
    #   ppy 24 / 12:       semi-monthly and monthly period boundaries cross workweeks, so no
    #                      hours total implies overtime. No flag — a documented blind spot.
    # An explicit hours_overtime=0 is treated the same as absent: a client who reports 0 OT
    # alongside >40 regular hours is in exactly the same ambiguous situation as one who
    # omitted the field.
    for emp in extracted.employees:
        ppy = _employee_pay_periods_per_year(emp.submitted_name, matches, roster)
        if ppy is None:
            continue  # unresolved employee: the decision gate already blocks it, no flag here
        ot = emp.hours_overtime
        ot_missing = not is_paid(ot)  # absent or zero both mean "no paid OT"
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
        # ppy 24 / 12: period boundaries cross workweeks — no flag (documented blind spot above)

    return issues
