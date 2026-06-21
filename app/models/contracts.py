"""Pipeline I/O contracts — the DRY seam between every stage, the eval, and the DB.

D-05: all monetary / rate / hours fields are Decimal, never float.
D-06: Decimal serializes to JSON strings via model_dump(mode='json') — protects
      precision at the DB jsonb boundary and in committed eval fixtures.
D-07: these are pipeline data-passing types, NOT 1:1 DB row mirrors.
D-08: Decision carries model_action AND final_action as structurally separate fields —
      code owns final_action; the two can differ when the gate fires.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# D-06: Pydantic v2 already serializes Decimal -> JSON string in
# model_dump(mode="json") by default, so no per-field @field_serializer is
# needed.  test_decimal_json_serialization is the behavioral guard that locks
# this default (WR-04).


# ---------------------------------------------------------------------------
# InboundEmail — what the extraction stage receives as input
# ---------------------------------------------------------------------------


class InboundEmail(BaseModel):
    """Parsed, cleaned inbound email.

    body_text is the cleaned body after stripping quoted history and signatures
    (per INGEST-02 forward contract).  Threading is anchored on message_id.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    message_id: str
    in_reply_to: str | None
    references_header: str | None
    subject: str
    from_addr: str
    to_addr: str
    body_text: str
    created_at: datetime


# ---------------------------------------------------------------------------
# Extracted — structured output of the extraction stage
# ---------------------------------------------------------------------------


class ExtractedEmployee(BaseModel):
    """Per-employee record returned by the extraction LLM.

    Hours fields are Decimal | None (Finding #3 / D-05):
    - Decimal  keeps money/hours typed correctly (not float).
    - | None   lets the extraction LLM signal a missing field so decide()
               can populate missing_fields and gate the run to clarification
               instead of crashing at parse time on a non-nullable field.
    contribution_401k_override is None when the client did not specify a
    change for this run; the pipeline falls back to the stored employee default.
    """

    model_config = ConfigDict(extra="forbid")

    submitted_name: str
    hours_regular: Decimal | None = Field(default=None, ge=0)
    hours_overtime: Decimal | None = Field(default=None, ge=0)
    hours_vacation: Decimal | None = Field(default=None, ge=0)
    hours_sick: Decimal | None = Field(default=None, ge=0)
    hours_holiday: Decimal | None = Field(default=None, ge=0)
    contribution_401k_override: Decimal | None = Field(default=None, ge=0)


class Extracted(BaseModel):
    """Full extraction output for one payroll run."""

    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    employees: list[ExtractedEmployee]
    pay_period_start: date
    pay_period_end: date | None = None


# ---------------------------------------------------------------------------
# Decision — the gated decision object (D-08 / LLM-08)
# ---------------------------------------------------------------------------


class Decision(BaseModel):
    """Gated decision object — the core thesis of the design.

    model_action: what the LLM proposed.
    final_action: what code enforces (the sole branch source, per LLM-07).

    When gate_triggered=True, final_action overrides model_action.
    The structurally-separate fields make the override visible and auditable.
    """

    model_config = ConfigDict(extra="forbid")

    model_action: Literal["process", "request_clarification"]
    gate_triggered: bool
    gate_reasons: list[str]
    final_action: Literal["process", "request_clarification"]
    unresolved_names: list[str]
    missing_fields: list[str]
    confidence: Decimal = Field(ge=0, le=1)  # 0.0–1.0; <0.8 fires the gate (WR-01)
    reasons: list[str]


# ---------------------------------------------------------------------------
# PaystubLineItem — computed output after the calc engine runs
# ---------------------------------------------------------------------------


class PaystubLineItem(BaseModel):
    """Computed paystub for one employee on one run.

    All dollar amounts are Decimal (D-05).  Hours are non-nullable here because
    PaystubLineItem is the *computed* output — by definition all hours are
    resolved before the calc engine runs (unlike ExtractedEmployee where hours
    may be absent from the client email).
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    run_id: UUID
    employee_id: UUID | None  # None if name never resolved
    submitted_name: str
    # Same 0–1 semantic as Decision.confidence / NameMatchResult.confidence, and
    # the one confidence field that reaches the DB (maps to NUMERIC(4,3), max
    # 9.999). Unbounded, a value >9.999 crashes the INSERT and a value in (1,9.999]
    # silently corrupts the audit record. (WR-01-incomplete)
    match_confidence: Decimal = Field(ge=0, le=1)
    hours_regular: Decimal
    hours_overtime: Decimal
    hours_vacation: Decimal
    hours_sick: Decimal
    hours_holiday: Decimal
    gross_pay: Decimal
    pretax_401k: Decimal
    fica_ss: Decimal
    fica_medicare: Decimal
    federal_withholding: Decimal
    state_withholding: Decimal | None
    net_pay: Decimal
    created_at: datetime
