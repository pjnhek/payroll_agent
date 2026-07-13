"""Roster and judgment-stage I/O shapes — the pure-value contracts.

Every judgment stage (reconcile_names, validate, decide) must be callable by the eval with
nothing but typed fixture inputs and ZERO DB access inside the function. These types are
what make that possible, which is what lets the eval measure the code that actually ships.

Invariants:
  - All monetary / rate fields are Decimal, never float.
  - Employee enforces the pay_type <-> compensation-field invariant at CONSTRUCTION time,
    so an un-computable employee (hourly with no rate, salaried with no salary) fails at
    seed time rather than halfway through a live calc.
  - The validators in this module reject impossible states outright, so downstream stages
    can trust their inputs instead of re-checking them.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ---------------------------------------------------------------------------
# Employee — roster input shape (a pure value, not a DB row mirror)
# ---------------------------------------------------------------------------


class Employee(BaseModel):
    """One employee as a pure value passed into reconcile_names and the calc engine.

    pay_type, filing_status, and pay_periods_per_year are Literal-constrained because
    their complete legal value sets are known. That closes the door on an eval fixture or
    a model-produced payload smuggling in an unrecognized value that the calc would then
    have to guess how to handle.
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

    # W-4 fields (2020+ form). All are dollar amounts the Pub 15-T worksheet adds to or
    # subtracts from the annualized wage, so a NEGATIVE value silently inflates or deflates
    # withholding (step_3_dependents is subtracted, so a negative there over-withholds).
    # ge=0 closes that gate at construction, so a bad value never reaches the calc engine.
    filing_status: Literal["single", "married_jointly", "married_separately"]
    step_2_checkbox: bool
    step_3_dependents: Decimal = Field(ge=0)      # dollar amount, often 0
    step_4a_other_income: Decimal = Field(ge=0)   # other income, often 0
    step_4b_deductions: Decimal = Field(ge=0)     # extra deductions, often 0

    # YTD Social Security wages before this run, used for the $184,500 wage-base cap.
    # A negative would make remaining_cap = 184500 - ytd_ss_wages EXCEED the wage base and
    # break the SS-cap straddle logic, over-withholding Social Security past the legal cap.
    ytd_ss_wages: Decimal = Field(ge=0)

    # Pay schedule. Mirrors the schema.sql CHECK (pay_periods_per_year IN (12,24,26,52)) so
    # an eval fixture or model-produced value cannot drift past the DB contract — the calc
    # annualizes wages by this number, so a bogus value scales withholding by that factor.
    # 52=weekly, 26=biweekly, 24=semi-monthly, 12=monthly
    pay_periods_per_year: Literal[12, 24, 26, 52]

    # ------------------------------------------------------------------
    # Compensation invariant
    # ------------------------------------------------------------------
    @model_validator(mode="after")
    def _require_compensation_field(self) -> Employee:
        """Enforce the pay_type <-> compensation-field requirement at construction time.

        An hourly employee without hourly_rate, or a salaried employee without
        annual_salary, is UN-COMPUTABLE: the calc would fall back to Decimal("0") and
        produce a $0 paycheck. Catching it here — at seed time, before any DB write —
        guarantees a missing calc input can never reach the calc engine mid-run.

        Exclusivity is enforced too: the compensation fields are mutually exclusive per
        pay_type, so a stray off-type field (an hourly employee also carrying an
        annual_salary) is REJECTED rather than left lying around for a later calc path to
        silently pick up and pay from.
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

    reconcile_names(extracted_names, roster) takes this and never loads from the DB inside
    the function — which is exactly what lets the eval drive the real resolver.
    """

    model_config = ConfigDict(extra="forbid")

    business_id: UUID
    employees: list[Employee]

    @model_validator(mode="after")
    def _check_unique_employee_ids(self) -> Roster:
        """Enforce unique employee ids.

        reconcile_names resolves uniqueness over the SET of candidate employee ids, so two
        roster rows sharing one UUID would COLLAPSE to a single candidate — and a name that
        should be flagged as ambiguous would instead resolve cleanly to the wrong person.
        Real DB rows are PK-protected; this guards the pure-Roster path that the eval and
        tests construct by hand.

        business_id consistency is deliberately NOT enforced here — callers build a roster
        with an explicit business_id and the contracts allow it.
        """
        ids = [e.id for e in self.employees]
        if len(ids) != len(set(ids)):
            raise ValueError("Roster has duplicate employee ids")
        return self


# ---------------------------------------------------------------------------
# NameMatchResult — per-name deterministic resolution result
# ---------------------------------------------------------------------------


class NameMatchResult(BaseModel):
    """One per-name deterministic-resolution result returned by reconcile_names.

    Resolution is pure code over roster facts: no score, no model-classified category, just
    deterministic source attribution. A submitted name resolves one of these ways:

    - ``source="exact"`` — exact normalized match (casefold + whitespace-normalize) to
      exactly one employee, with no other employee sharing the normalized name.
    - ``source="alias"`` — matches a stored ``known_alias`` for exactly one employee, with
      no collision. This is the READ side of the human-confirmation learning loop.
    - ``source="none"`` — anything else (no match, typo, first-time nickname, garbled name,
      or ambiguous across employees). The name is left unresolved for the clarify path; the
      resolver never guesses.
    - ``source="operator"`` — a human-stated per-run override (see below).

    ``resolved`` is an EXPLICIT bool rather than something derived from ``source``, so the
    dashboard and eval read the answer directly instead of each re-deriving the rule (and
    risking a divergent re-derivation). ``matched_employee_id`` is None whenever ``source``
    is "none" — an unresolved name maps to no employee. The validator below enforces that
    those three fields can never disagree.
    """

    model_config = ConfigDict(extra="forbid")

    submitted_name: str
    matched_employee_id: UUID | None  # None when source == "none" (unresolved)
    # "operator": a human-stated per-run override, applied by reconcile_names(overrides=...)
    # BEFORE the exact/alias tiers. It is still a resolved, non-guessed result — a human
    # explicitly stated this match — so it carries the same resolution invariant as "exact"
    # and "alias", just with its own provenance tag. The no-guess guarantee is intact: the
    # model never decides; here a person did, and the tag records that.
    source: Literal["exact", "alias", "none", "operator"]
    resolved: bool
    reason: str

    @model_validator(mode="after")
    def _check_resolution_invariant(self) -> NameMatchResult:
        """Reject impossible states so decide() can trust ``resolved``.

        ``source``, ``resolved``, and ``matched_employee_id`` are NOT independent: a
        resolved name must name a real employee, and an unresolved name must name none.
        Without this check, a malformed construction from a test, the eval, or future code
        — ``source="none", resolved=True`` — would sail straight past the decision gate and
        into a payroll run, which is precisely the "silently pay the wrong person" failure
        the whole resolver exists to prevent.
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
# ValidationIssue — per-field output of the validate stage
# ---------------------------------------------------------------------------


class ValidationIssue(BaseModel):
    """One field-validation issue produced by the validate stage.

    issue_type is Literal-constrained to the known legal value set:

    - "missing" — a required field the calc needs is absent. Gates the run to
      clarification via decide().
    - "field_regression" — hours that were present in an earlier round vanished from the
      client's reply. Emitted by validate() from the drops that detect_field_regression
      found on the RAW reply, before backfill.
    - "out_of_bounds" / "non_numeric" — legal values, but NOT reachable from the typed
      pipeline: a negative or non-numeric hours value already fails at the extraction parse
      boundary (ExtractedEmployee is Decimal|None + ge=0), so by the time validate() runs
      every present value is a valid non-negative Decimal.
    """

    model_config = ConfigDict(extra="forbid")

    field: str
    issue_type: Literal["missing", "out_of_bounds", "non_numeric", "field_regression"]
    message: str
