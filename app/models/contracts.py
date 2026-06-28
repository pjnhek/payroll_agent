"""Pipeline I/O contracts — the DRY seam between every stage, the eval, and the DB.

D-05: all monetary / rate / hours fields are Decimal, never float.
D-06: Decimal serializes to JSON strings via model_dump(mode='json') — protects
      precision at the DB jsonb boundary and in committed eval fixtures.
D-07: these are pipeline data-passing types, NOT 1:1 DB row mirrors.
D-21-01: Decision is purely code-owned — final_action is computed deterministically
      over resolution facts and is the SOLE branch source. There is no model action
      to diverge from (no score, no LLM-judged decision).
D-21-04 / D-21-06: Decision.resolutions carries the per-name resolution detail folded
      into the decision JSONB so the dashboard/eval can read why each name resolved.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.roster import NameMatchResult

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
    contribution_401k_override: Decimal | None = Field(default=None, ge=0, le=1)


class ExtractionPayload(BaseModel):
    """The LLM structured-output schema for extraction (review FIX A).

    Identical to Extracted's JUDGMENT fields MINUS the required run_id. The model
    returns only this payload (employees + pay_period); extract() stamps the
    code-owned run_id to build the full Extracted. This exists because
    Extracted.run_id is REQUIRED and run_id is trusted, code-owned plumbing the
    orchestrator already knows — the model must never invent or echo a trusted
    run_id. extra="forbid" means a run_id key in the model output raises a
    ValidationError (T-02-15), so a trusted run identity can never originate from
    model output.
    """

    model_config = ConfigDict(extra="forbid")

    employees: list[ExtractedEmployee]
    # Nullable for the SAME reason the hours fields are (D-05 / Finding #3): a real
    # email often states no pay period ("hours for this week"), so the LLM returns
    # null — that must flow downstream as "didn't say", NOT crash extraction at
    # parse time. The pay period is informational on the paystub (pdf._period_label
    # already handles None) and is not a money input. (06-05 live-gate regression.)
    pay_period_start: date | None = None
    pay_period_end: date | None = None


class Extracted(BaseModel):
    """Full extraction output for one payroll run."""

    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    employees: list[ExtractedEmployee]
    pay_period_start: date | None = None
    pay_period_end: date | None = None


# ---------------------------------------------------------------------------
# FieldDrop — forward-compat scaffolding for Phase 7.5 (MONEY-03)
# ---------------------------------------------------------------------------


class FieldDrop(BaseModel):
    """Forward-compat scaffolding for Phase 7.5 (MONEY-03). Public field-regression record.

    employee_id is always a real resolved UUID.
    field is always a bare hours-field name (never qualified with submitted_name),
    e.g. "hours_overtime".

    resumed_value semantics (D-13/D-14):
    - resumed_value=None means carried_forward (the reply was silent on this field;
      the original value should be backfilled).
    - resumed_value=Decimal('0') means confirmed_dropped (the client explicitly zeroed
      the field in their reply; honor the removal, do NOT backfill).

    Nothing in Phase 7 emits this type — it is a no-op scaffold. Phase 7.5 builds
    detect_field_regression on top of it.
    """

    model_config = ConfigDict(extra="forbid")

    employee_id: UUID
    field: str
    original_value: Decimal
    resumed_value: Decimal | None


# ---------------------------------------------------------------------------
# Decision — the deterministic decision object (D-21-01 / D-21-04 / LLM-07)
# ---------------------------------------------------------------------------


class Decision(BaseModel):
    """Deterministic decision object — the core thesis of the design.

    final_action is computed PURELY by code over the resolution facts and is the
    SOLE branch source for the orchestrator / dashboard / eval (LLM-07, D-21-03).
    There is no model action to diverge from: decide.py never calls an LLM and
    never reads a score (D-21-01). request_clarification fires when any name is
    unresolved, any cross-name collision exists, or any required field is missing
    — gate_reasons lists exactly what triggered it.

    resolutions is the per-name resolution detail (one NameMatchResult per
    submitted name) folded into the decision JSONB so the dashboard and eval can
    read WHY each name resolved or didn't (D-21-04 / D-21-06); there is no separate
    name_matches table anymore.
    """

    model_config = ConfigDict(extra="forbid")

    final_action: Literal["process", "request_clarification"]
    gate_reasons: list[str]
    unresolved_names: list[str]
    missing_fields: list[str]
    resolutions: list[NameMatchResult]


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
    # Provenance on a computed paystub is employee_id + submitted_name — no score
    # is carried anywhere (D-21-01).
    submitted_name: str
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
    additional_medicare_not_modeled: bool = False
    # User Decision 1 (FIX B): Additional Medicare 0.9% surtax on wages over $200k YTD
    # is NOT modeled. When this flag is True the engine is known to under-withhold by 0.9%
    # above the threshold. The flag makes the limitation observable and test-backed.
    # Default=False so existing callers are unbroken (additive, non-breaking field addition).
