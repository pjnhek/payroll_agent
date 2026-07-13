"""Overpay guards for the Round-2 classify lookup and the backfill skip set.

Test level: unit — exercises the classify lookup logic and backfill_extracted
directly with no DB, no LLM, and no full pipeline integration. The orchestrator's
Round-2 classify block is tested by constructing the exact objects it operates on
and asserting two invariants:

  Restated name: a name the client restates differently in the reply ("Maria Chen"
      in reply vs "M. Chen" in the snapshot) must still resolve to the correct
      employee_id via the UNION lookup, so the asked field is classified as
      "confirmed_dropped" instead of being left "asked". Left "asked", the field
      is not in backfill_skip and the snapshot's positive value is restored over
      the client's explicit zero — an OVERPAY.

  Unresolvable asked field: when an asked employee is genuinely absent from the
      raw reply even after the union lookup, (emp_id_str, field) must land in
      backfill_skip so backfill_extracted does NOT restore the snapshot's positive
      value. The worst case must be an under-fill that re-clarifies, never a
      silent overpay.

The union lookup lives in `name_to_id_for_classify` construction: the union of
current_matches_for_classify + prior_matches covers restated names. The
unresolvable case is staged in `_unresolvable_asked` and absorbed into
backfill_skip.

See also: tests/test_detect_field_regression.py — the same restated-name problem
in detect_field_regression.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.models.contracts import Extracted, ExtractedEmployee
from app.models.roster import Employee, NameMatchResult, Roster
from app.pipeline.orchestrator import backfill_extracted
from app.pipeline.reconcile_names import reconcile_names

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _employee(
    emp_id: uuid.UUID,
    full_name: str,
    known_aliases: list[str] | None = None,
) -> Employee:
    biz_id = uuid.UUID("b0000001-0000-0000-0000-000000000001")
    return Employee(
        id=emp_id,
        business_id=biz_id,
        full_name=full_name,
        known_aliases=known_aliases or [],
        pay_type="hourly",
        hourly_rate=Decimal("20.00"),
        annual_salary=None,
        retirement_contribution_pct=Decimal("0.05"),
        filing_status="single",
        step_2_checkbox=False,
        step_3_dependents=Decimal("0"),
        step_4a_other_income=Decimal("0"),
        step_4b_deductions=Decimal("0"),
        ytd_ss_wages=Decimal("0"),
        pay_periods_per_year=52,
    )


def _match(
    submitted_name: str,
    emp_id: uuid.UUID,
    source: str = "exact",
) -> NameMatchResult:
    return NameMatchResult(
        submitted_name=submitted_name,
        matched_employee_id=emp_id,
        source=source,
        resolved=True,
        reason="match",
    )


def _extracted(submitted_name: str, hours_overtime: Decimal | None) -> Extracted:
    return Extracted(
        run_id=uuid.uuid4(),
        employees=[
            ExtractedEmployee(
                submitted_name=submitted_name,
                hours_regular=Decimal("40"),
                hours_overtime=hours_overtime,
            )
        ],
        pay_period_start=date(2026, 6, 15),
        pay_period_end=date(2026, 6, 21),
    )


# ---------------------------------------------------------------------------
# Restated name + zeroed field → confirmed_dropped, no overpay
# ---------------------------------------------------------------------------


def test_restated_name_classify_resolves_to_correct_employee():
    """'Maria Chen' in the reply restates 'M. Chen' from the snapshot.

    The union lookup (current_matches_for_classify + prior_matches) must resolve
    'Maria Chen' to the same employee_id as 'M. Chen', so the asked field can
    be classified from the raw reply value.

    This is the unit-level exercise of the classify lookup construction in
    orchestrator.py's Round-2 block.
    """
    chen_id = uuid.uuid4()

    # Roster has "Maria Chen" as the canonical full name.
    emp = _employee(chen_id, "Maria Chen", known_aliases=["M. Chen"])
    biz_id = emp.business_id
    roster = Roster(business_id=biz_id, employees=[emp])

    # prior_matches: snapshot round submitted "M. Chen" → chen_id (alias match).
    prior_matches = [_match("M. Chen", chen_id, source="alias")]

    # raw_extracted: reply submitted "Maria Chen" with OT explicitly zeroed.
    raw_extracted = _extracted("Maria Chen", hours_overtime=Decimal("0"))

    # Reproduce the classify lookup:
    # UNION of current matches (reconcile raw reply names) + prior_matches.
    raw_submitted = [e.submitted_name for e in raw_extracted.employees]
    current_matches_for_classify = reconcile_names(raw_submitted, roster)

    # The union dict — current first (restated name), prior as fallback.
    name_to_id_for_classify: dict[str, str] = {
        m.submitted_name: str(m.matched_employee_id)
        for m in (list(current_matches_for_classify) + list(prior_matches))
        if m.resolved and m.matched_employee_id is not None
    }

    # Both the restated name ("Maria Chen") AND the prior name ("M. Chen")
    # must resolve to the same employee_id.
    assert name_to_id_for_classify.get("Maria Chen") == str(chen_id), (
        "'Maria Chen' (current name) must resolve to chen_id in the union lookup"
    )
    assert name_to_id_for_classify.get("M. Chen") == str(chen_id), (
        "'M. Chen' (prior name) must also be in the union lookup as fallback"
    )


def test_restated_name_zeroed_field_classified_as_confirmed_dropped():
    """Full scenario: restated name + OT explicitly zeroed → confirmed_dropped.

    Setup:
    - Snapshot: "M. Chen" with OT=Decimal('2').
    - Reply: "Maria Chen" with OT=Decimal('0') (explicit zero).
    - clarified state: {chen_id_str: {"hours_overtime": "asked"}}.

    Without the union lookup (OVERPAY):
      "Maria Chen" absent from a prior-only name_to_id_for_classify → raw_emp=None
      → field stays "asked" → not in backfill_skip → backfill restores OT=2 → OVERPAY.

    With the union lookup (asserted here):
      "Maria Chen" in union lookup → raw_emp resolved → OT=Decimal('0') →
      classified as "confirmed_dropped" → in backfill_skip → backfill skips →
      the client's explicit zero survives (not re-backfilled).
    """
    chen_id = uuid.uuid4()
    chen_id_str = str(chen_id)

    emp = _employee(chen_id, "Maria Chen", known_aliases=["M. Chen"])
    biz_id = emp.business_id
    roster = Roster(business_id=biz_id, employees=[emp])

    # prior_matches from snapshot round (submitted "M. Chen").
    prior_matches = [_match("M. Chen", chen_id, source="alias")]

    # Snapshot: "M. Chen" with OT=2 (what was asked about).
    snapshot = _extracted("M. Chen", hours_overtime=Decimal("2"))

    # Raw reply: "Maria Chen" with OT=Decimal('0') — client explicitly zeroed.
    raw_extracted = _extracted("Maria Chen", hours_overtime=Decimal("0"))

    # Current matches from the union lookup.
    raw_submitted = [e.submitted_name for e in raw_extracted.employees]
    current_matches_for_classify = reconcile_names(raw_submitted, roster)

    name_to_id_for_classify: dict[str, str] = {
        m.submitted_name: str(m.matched_employee_id)
        for m in (list(current_matches_for_classify) + list(prior_matches))
        if m.resolved and m.matched_employee_id is not None
    }

    # Simulate the orchestrator's classify loop.
    raw_name_to_emp = {emp.submitted_name: emp for emp in raw_extracted.employees}
    clarified: dict[str, dict[str, str]] = {chen_id_str: {"hours_overtime": "asked"}}
    newly_classified: set[tuple[str, str]] = set()
    _unresolvable_asked: set[tuple[str, str]] = set()

    for emp_id_str, field_outcomes in list(clarified.items()):
        for field, outcome in list(field_outcomes.items()):
            if outcome != "asked":
                continue

            raw_emp = None
            for raw_name, raw_e in raw_name_to_emp.items():
                if name_to_id_for_classify.get(raw_name) == emp_id_str:
                    raw_emp = raw_e
                    break

            if raw_emp is None:
                _unresolvable_asked.add((emp_id_str, field))
                continue

            raw_val = getattr(raw_emp, field, None)
            if raw_val is not None and raw_val > 0:
                clarified[emp_id_str][field] = "client_supplied"
            elif raw_val is not None and raw_val == Decimal("0"):
                clarified[emp_id_str][field] = "confirmed_dropped"
            else:
                clarified[emp_id_str][field] = "carried_forward"
            newly_classified.add((emp_id_str, field))

    # The field must be classified as confirmed_dropped, NOT left "asked".
    outcome = clarified[chen_id_str]["hours_overtime"]
    assert outcome == "confirmed_dropped", (
        f"OT=Decimal('0') for a restated name must classify as 'confirmed_dropped', "
        f"got {outcome!r}"
    )
    assert (chen_id_str, "hours_overtime") in newly_classified, (
        "(chen_id_str, 'hours_overtime') must be in newly_classified"
    )

    # Build backfill_skip as the orchestrator does, including the absorption of
    # the unresolvable-asked staging set.
    _resolved_by_name: set[tuple[str, str]] = set()  # no prior terminals in this scenario
    backfill_skip: set[tuple[str, str]] = set(_resolved_by_name)
    for e_id, fld in newly_classified:
        oc = clarified.get(e_id, {}).get(fld)
        if oc in ("confirmed_dropped", "client_supplied"):
            backfill_skip.add((e_id, fld))
    backfill_skip.update(_unresolvable_asked)

    # Confirmed_dropped must be in backfill_skip (the overpay guard).
    assert (chen_id_str, "hours_overtime") in backfill_skip, (
        "a confirmed_dropped field must be in backfill_skip to prevent snapshot-restore"
    )

    # Now verify backfill_extracted honours backfill_skip (no re-backfill).
    # current matches for backfill: "Maria Chen" → chen_id.
    current_matches = list(current_matches_for_classify)

    final = backfill_extracted(
        raw_extracted,    # reply extracted: OT=Decimal('0')
        snapshot,         # snapshot: OT=Decimal('2')
        prior_matches,    # prior: "M. Chen" → chen_id
        current_matches,  # current: "Maria Chen" → chen_id
        backfill_skip,    # resolved_drops: {(chen_id_str, 'hours_overtime')}
    )

    # The final extracted OT must NOT be 2 (no snapshot restore = no overpay).
    final_emp = final.employees[0]
    assert final_emp.hours_overtime != Decimal("2"), (
        "a confirmed_dropped OT must NOT be re-backfilled from the snapshot (would be OVERPAY)"
    )
    # Specifically it should remain as the raw reply value (Decimal('0')).
    # _is_paid(Decimal('0')) is False — but the backfill_skip guard must fire FIRST,
    # so the explicit zero (not the snapshot's 2) is preserved.
    assert final_emp.hours_overtime == Decimal("0"), (
        "the explicit zero from the raw reply must be preserved, not replaced by snapshot OT=2"
    )


# ---------------------------------------------------------------------------
# Unresolvable asked employee → backfill_skip, not overpay
# ---------------------------------------------------------------------------


def test_unresolvable_asked_field_added_to_backfill_skip():
    """If an asked employee is absent from the raw reply even after the union
    lookup, (emp_id_str, field) is staged in _unresolvable_asked and absorbed into
    backfill_skip. The snapshot's positive value is NOT restored.

    This is defense-in-depth against the same root cause as the restated-name
    case: the unresolvable case is rare (the union lookup covers restated names),
    but when it does fire, the outcome must be conservative (no overpay).
    """
    alice_id = uuid.uuid4()
    alice_id_str = str(alice_id)

    emp = _employee(alice_id, "Alice", known_aliases=[])
    biz_id = emp.business_id
    roster = Roster(business_id=biz_id, employees=[emp])

    # prior_matches: Alice was in the snapshot round.
    prior_matches = [_match("Alice", alice_id)]

    # Snapshot: Alice with OT=3.
    snapshot = _extracted("Alice", hours_overtime=Decimal("3"))

    # Raw reply: completely omits Alice — she is not in the reply at all.
    # (E.g. the client replied about a different employee only.)
    raw_extracted = Extracted(
        run_id=uuid.uuid4(),
        employees=[],  # Alice absent from reply
        pay_period_start=date(2026, 6, 15),
    )

    # Simulate classify lookup: Alice not in raw reply → name_to_id_for_classify
    # will have "Alice" from prior_matches but raw_name_to_emp is empty.
    raw_submitted = [e.submitted_name for e in raw_extracted.employees]  # []
    current_matches_for_classify = reconcile_names(raw_submitted, roster)  # []

    name_to_id_for_classify: dict[str, str] = {
        m.submitted_name: str(m.matched_employee_id)
        for m in (list(current_matches_for_classify) + list(prior_matches))
        if m.resolved and m.matched_employee_id is not None
    }
    # "Alice" is in name_to_id_for_classify (from prior), but raw_name_to_emp is empty
    # → raw_emp will be None for Alice (she's not in the raw reply).
    raw_name_to_emp = {e.submitted_name: e for e in raw_extracted.employees}

    clarified: dict[str, dict[str, str]] = {alice_id_str: {"hours_overtime": "asked"}}
    newly_classified: set[tuple[str, str]] = set()
    _unresolvable_asked: set[tuple[str, str]] = set()

    for emp_id_str, field_outcomes in list(clarified.items()):
        for field, outcome in list(field_outcomes.items()):
            if outcome != "asked":
                continue
            raw_emp = None
            for raw_name, raw_e in raw_name_to_emp.items():
                if name_to_id_for_classify.get(raw_name) == emp_id_str:
                    raw_emp = raw_e
                    break
            if raw_emp is None:
                _unresolvable_asked.add((emp_id_str, field))
                continue
            # classify... (not reached because Alice is absent)

    # The unresolvable field must be staged.
    assert (alice_id_str, "hours_overtime") in _unresolvable_asked, (
        "an asked field for an absent employee must be in _unresolvable_asked"
    )
    assert (alice_id_str, "hours_overtime") not in newly_classified, (
        "an absent employee must NOT appear in newly_classified"
    )

    # Build backfill_skip and absorb _unresolvable_asked.
    _resolved_by_name: set[tuple[str, str]] = set()
    backfill_skip: set[tuple[str, str]] = set(_resolved_by_name)
    for e_id, fld in newly_classified:
        oc = clarified.get(e_id, {}).get(fld)
        if oc in ("confirmed_dropped", "client_supplied"):
            backfill_skip.add((e_id, fld))
    backfill_skip.update(_unresolvable_asked)

    assert (alice_id_str, "hours_overtime") in backfill_skip, (
        "an unresolvable asked field must be in backfill_skip after absorption"
    )

    # Verify backfill_extracted respects the skip: Alice's OT=3 must NOT be restored.
    # Note: with an empty raw_extracted (no Alice row), backfill has nothing to
    # backfill into anyway — but we verify the gate works correctly with a synthetic
    # current_extracted that has Alice with OT=None (silence case).
    current_extracted_with_alice = _extracted("Alice", hours_overtime=None)
    current_matches = [_match("Alice", alice_id)]

    final = backfill_extracted(
        current_extracted_with_alice,
        snapshot,
        prior_matches,
        current_matches,
        backfill_skip,
    )

    final_emp = final.employees[0]
    assert final_emp.hours_overtime is None or final_emp.hours_overtime != Decimal("3"), (
        "an unresolvable asked field must NOT be re-backfilled from the snapshot (no overpay)"
    )


# ---------------------------------------------------------------------------
# _field_regression_lines guards against a malformed gate_reason
# ---------------------------------------------------------------------------


def test_field_regression_lines_skips_malformed_reason():
    """_field_regression_lines must not crash on a gate_reason with no '.'.

    A gate_reason without '.' in the qualified part (after the prefix) is
    malformed. `qualified.rsplit('.', 1)` returns a 1-element list for such a
    string, so an unguarded 2-element unpack raises ValueError. The length check
    (`if len(parts) != 2: continue`) skips it silently instead.
    """
    from app.pipeline.compose_email import _field_regression_lines

    # Malformed: no "." in the qualified portion — should skip, not crash.
    malformed_reasons = [
        "field regression: no_dot_here",
        "field regression: ",
    ]
    result = _field_regression_lines(malformed_reasons)
    assert result == [], (
        "a malformed gate_reason (no '.') must produce no lines, not raise ValueError"
    )


def test_field_regression_lines_normal_case_still_works():
    """The malformed-reason guard must not regress the normal (correctly-dotted) case."""
    from app.pipeline.compose_email import _field_regression_lines

    reasons = [
        "field regression: M. Chen.hours_overtime",
        "field regression: Alice.hours_regular",
    ]
    result = _field_regression_lines(reasons)
    assert len(result) == 2, "Normal dotted gate_reasons must still produce lines"
    assert "M. Chen" in result[0], "rsplit last-dot must parse 'M. Chen' as submitted_name"
    assert "hours_overtime" in result[0], (
        "rsplit last-dot must parse 'hours_overtime' as field_name"
    )
    assert "Alice" in result[1]
    assert "hours_regular" in result[1]
