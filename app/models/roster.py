"""D-14 roster / judgment-stage I/O shapes.

Every judgment stage (reconcile_names, validate, decide) must be callable by the
eval with only typed fixture inputs — zero DB access inside the function.  These
types are the pure-value contracts that make that possible.

D-05: all monetary / rate fields are Decimal, never float.
D-10 / FOUND-06: Employee enforces the pay_type ↔ compensation field invariant
   via @model_validator so a missing calc input fails at construction time
   (seed time) rather than mid-demo during the calc engine.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Employee — roster input shape (not a DB row mirror, per D-07/D-14)
# ---------------------------------------------------------------------------


class Employee(BaseModel):
    """One employee as a pure value passed into reconcile_names / calc engine.

    Fields follow FOUND-06 (calc input set) + build plan data model.
    pay_type / filing_status / pay_type are Literal-constrained (Finding #7)
    because their complete legal value sets are known from REQUIREMENTS.md now.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    business_id: UUID
    full_name: str
    known_aliases: list[str]

    # Compensation — mutually exclusive per pay_type
    pay_type: Literal["hourly", "salary"]
    hourly_rate: Decimal | None = Field(
        default=None, ge=0
    )  # required when pay_type == "hourly"
    annual_salary: Decimal | None = Field(
        default=None, ge=0
    )  # required when pay_type == "salary"

    # Retirement
    retirement_contribution_pct: Decimal = Field(ge=0, le=1)  # e.g. 0.03 for 3%

    # W-4 fields (2020+ form). All four are dollar amounts the Pub 15-T worksheet
    # adds/subtracts, so a negative silently inflates or deflates withholding
    # (step_3_dependents is *subtracted*). ge=0 closes the validation gate so a
    # bad value never reaches the calc engine. (WR-08)
    filing_status: Literal["single", "married_jointly", "married_separately"]
    step_2_checkbox: bool
    step_3_dependents: Decimal = Field(ge=0)      # dollar amount, often 0
    step_4a_other_income: Decimal = Field(ge=0)   # other income, often 0
    step_4b_deductions: Decimal = Field(ge=0)     # extra deductions, often 0

    # YTD Social Security wages before this run (for the $184,500 wage-base cap).
    # A negative makes remaining_cap = 184500 - ytd_ss_wages exceed the wage base,
    # breaking the SS-cap straddle logic. (WR-08)
    ytd_ss_wages: Decimal = Field(ge=0)

    # Pay schedule — mirrors schema.sql CHECK (pay_periods_per_year IN (12,24,26,52))
    # so an eval fixture / LLM-produced value can't drift past the contract (WR-02).
    pay_periods_per_year: Literal[12, 24, 26, 52]  # 52=weekly, 26=biweekly, 24=semi-monthly, 12=monthly

    # ------------------------------------------------------------------
    # D-10 / FOUND-06 compensation invariant
    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _require_compensation_field(self) -> "Employee":
        """Enforce pay_type ↔ compensation field requirement at construction.

        An hourly employee without hourly_rate, or a salaried employee without
        annual_salary, is un-computable.  Catching this at seed time (before any
        DB write) guarantees a missing calc input never reaches the calc engine
        mid-demo.

        Exclusivity is enforced as well (WR-07): the docstring claims the comp
        fields are "mutually exclusive per pay_type," so a stray off-type field
        (e.g. an hourly employee carrying an annual_salary) is rejected rather
        than left to be silently picked up by a later calc path.
        """
        if self.pay_type == "hourly":
            if self.hourly_rate is None:
                raise ValueError(
                    "hourly_rate is required when pay_type is 'hourly'"
                )
            if self.annual_salary is not None:
                raise ValueError(
                    "annual_salary must be None when pay_type is 'hourly'"
                )
        if self.pay_type == "salary":
            if self.annual_salary is None:
                raise ValueError(
                    "annual_salary is required when pay_type is 'salary'"
                )
            if self.hourly_rate is not None:
                raise ValueError(
                    "hourly_rate must be None when pay_type is 'salary'"
                )
        return self


# ---------------------------------------------------------------------------
# Roster — pure value passed into reconcile_names
# ---------------------------------------------------------------------------


class Roster(BaseModel):
    """A business's complete employee list as a typed value.

    reconcile_names(extracted_names, roster) accepts this — it never loads
    from the DB inside the function (D-14 acceptance bar).
    """

    model_config = ConfigDict(extra="forbid")

    business_id: UUID
    employees: list[Employee]

    @model_validator(mode="after")
    def _check_unique_employee_ids(self) -> "Roster":
        """Enforce unique employee ids (review fix).

        reconcile_names resolves uniqueness over the SET of candidate employee ids, so
        two roster rows sharing one UUID would collapse to one candidate and could
        wrongly resolve an ambiguous name. Real DB rows are PK-protected; this guards
        the pure-Roster path the eval constructs (D-14 — the eval uses these types).
        (business_id consistency is intentionally NOT enforced here — callers build a
        roster with an explicit business_id and the existing contracts allow it.)
        """
        ids = [e.id for e in self.employees]
        if len(ids) != len(set(ids)):
            raise ValueError("Roster has duplicate employee ids")
        return self


# ---------------------------------------------------------------------------
# NameMatchResult — per-name DETERMINISTIC resolution result (D-21-01 / D-21-04)
# ---------------------------------------------------------------------------


class NameMatchResult(BaseModel):
    """One per-name deterministic-resolution result returned by reconcile_names.

    Resolution is pure code over roster facts (D-21-01) — no score, no LLM-classified
    category, just deterministic source attribution. A submitted name resolves one
    of three ways:

    - ``source="exact"`` — exact normalized match (casefold + whitespace-normalize)
      to exactly one employee, with no other employee sharing the normalized name.
    - ``source="alias"`` — matches a stored ``known_alias`` for exactly one
      employee, no collision (the READ side of the learning loop, D-21-07).
    - ``source="none"`` — anything else (no match, typo, first-time nickname,
      garbled, ambiguous) — the name is left unresolved for the clarify path.

    ``resolved`` is an EXPLICIT bool (not derived from ``source``) for legibility
    per D-21-04: the dashboard/eval read ``resolved`` directly rather than
    re-deriving the rule. ``matched_employee_id`` is None whenever ``source`` is
    "none" (an unresolved name maps to no employee).
    """

    model_config = ConfigDict(extra="forbid")

    submitted_name: str
    matched_employee_id: UUID | None  # None when source == "none" (unresolved)
    # "operator" (D-11-08/Open Question #2, Phase 11 Plan 04): a human-stated
    # per-run override applied by reconcile_names(overrides=...) BEFORE the
    # exact/alias tiers. It is still a resolved, non-guessed result — a human
    # explicitly stated the match — so it carries the same resolution invariant
    # as "exact"/"alias" below, just with its own distinct provenance tag (the
    # no-guess guarantee holds: the LLM never decides; a human did here).
    source: Literal["exact", "alias", "none", "operator"]
    resolved: bool
    reason: str

    @model_validator(mode="after")
    def _check_resolution_invariant(self) -> "NameMatchResult":
        """Reject impossible states so decide() can trust ``resolved`` (review fix).

        ``source`` and ``resolved`` are not independent: a resolved name MUST name a
        real employee, and an unresolved name MUST name none. Without this, a
        malformed construction (a test, the eval, or future code) like
        ``source="none", resolved=True`` would silently sail past the gate.
        """
        if self.source == "none":
            if self.resolved or self.matched_employee_id is not None:
                raise ValueError(
                    "source='none' requires resolved=False and matched_employee_id=None"
                )
        else:  # "exact" | "alias" | "operator"
            if not self.resolved or self.matched_employee_id is None:
                raise ValueError(
                    f"source={self.source!r} requires resolved=True and a "
                    "non-null matched_employee_id"
                )
        return self


# ---------------------------------------------------------------------------
# ValidationIssue — per-field output of field validation (LLM-06)
# ---------------------------------------------------------------------------


class ValidationIssue(BaseModel):
    """One field-validation issue produced by the validate stage.

    issue_type Literal covers the legal values from LLM-06
    (Finding #7 — constrained to known value set).

    "field_regression" is a forward-compat value added for Phase 7.5 (D-17).
    Nothing in Phase 7 emits it — it is a harmless no-op scaffold so Phase 7.5
    can reference it without a mid-plan Literal change.
    """

    model_config = ConfigDict(extra="forbid")

    field: str
    issue_type: Literal["missing", "out_of_bounds", "non_numeric", "field_regression"]
    message: str
