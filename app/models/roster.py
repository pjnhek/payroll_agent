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

    # W-4 fields (2020+ form)
    filing_status: Literal["single", "married_jointly", "married_separately"]
    step_2_checkbox: bool
    step_3_dependents: Decimal   # dollar amount, often 0
    step_4a_other_income: Decimal  # other income, often 0
    step_4b_deductions: Decimal   # extra deductions, often 0

    # YTD Social Security wages before this run (for the $184,500 wage-base cap)
    ytd_ss_wages: Decimal

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


# ---------------------------------------------------------------------------
# NameMatchResult — per-name output of reconcile_names (LLM-05 / LLM-09)
# ---------------------------------------------------------------------------


class NameMatchResult(BaseModel):
    """One name-reconciliation result returned by reconcile_names.

    match_type Literal covers the 5 legal values from LLM-05/LLM-09
    (Finding #7 — constrained to known value set).
    confidence 0.0–1.0; values below 0.8 trigger the gate in decide().
    """

    model_config = ConfigDict(extra="forbid")

    submitted_name: str
    matched_employee_id: UUID | None  # None when match_type == "unknown"
    match_type: Literal["exact", "alias", "llm_typo", "llm_nickname", "unknown"]
    confidence: Decimal = Field(ge=0, le=1)  # 0.0–1.0; <0.8 fires the gate (WR-01)
    reason: str


# ---------------------------------------------------------------------------
# ValidationIssue — per-field output of field validation (LLM-06)
# ---------------------------------------------------------------------------


class ValidationIssue(BaseModel):
    """One field-validation issue produced by the validate stage.

    issue_type Literal covers the 3 legal values from LLM-06
    (Finding #7 — constrained to known value set).
    """

    model_config = ConfigDict(extra="forbid")

    field: str
    issue_type: Literal["missing", "out_of_bounds", "non_numeric"]
    message: str
