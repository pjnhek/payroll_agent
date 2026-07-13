"""Pipeline I/O contracts — the one shared seam between every stage, the eval, and the DB.

Invariants these types enforce:
  - Every monetary / rate / hours field is Decimal, NEVER float. Binary float error in a
    payroll amount is a wrong number on somebody's paystub.
  - Decimal serializes to a JSON string via model_dump(mode='json'), which preserves
    precision across the JSONB boundary and in committed eval fixtures. Serializing to a
    JSON number would round-trip through a float and silently lose cents.
  - Every model is extra="forbid". A typo'd or model-invented key must raise, not be
    silently dropped — a dropped hours key would zero that line and still reconcile.
  - These are pipeline data-passing types, NOT 1:1 mirrors of DB rows.
  - Decision is purely code-owned: final_action is computed deterministically over the
    resolution facts and is the SOLE branch source. There is no model-proposed action to
    diverge from, and no score anywhere in the type.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.roster import NameMatchResult

# Pydantic v2 already serializes Decimal -> JSON string in model_dump(mode="json") by
# default, so no per-field @field_serializer is needed. test_decimal_json_serialization is
# the behavioral guard that LOCKS that default: if a future Pydantic release ever emitted
# JSON numbers instead, every persisted amount would quietly round-trip through a float.


# ---------------------------------------------------------------------------
# InboundEmail — what the extraction stage receives as input
# ---------------------------------------------------------------------------


class InboundEmail(BaseModel):
    """Parsed, cleaned inbound email.

    body_text is the cleaned body after stripping quoted history and signatures — the
    quoted history of a prior round would otherwise be re-extracted as if it were this
    round's hours. Threading is anchored on message_id.
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
    """Per-employee record returned by the extraction model.

    Hours fields are Decimal | None, and BOTH halves of that type are load-bearing:
    - Decimal keeps hours and money typed exactly (never float).
    - | None lets the model say "the client didn't tell us" so decide() can gate the run
      into a clarification. A non-nullable field would instead crash extraction at parse
      time, and a default of 0 would be worse still — it reads as "worked zero hours" and
      would pay the employee nothing.

    contribution_401k_override is None when the client did not specify a change for this
    run; the pipeline then falls back to the employee's stored default.
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
    """The model's structured-output schema for extraction.

    Identical to Extracted's JUDGMENT fields MINUS run_id. The model returns only this
    payload (employees + pay period); extract() then stamps the code-owned run_id to build
    the full Extracted.

    This type exists specifically to keep run_id OUT of the model's reach. run_id is
    trusted plumbing the orchestrator already knows, and it keys this run's database
    writes — a hallucinated or injected value could point them at another business's
    payroll. extra="forbid" means a run_id key appearing in model output raises a
    ValidationError rather than being accepted, so a trusted identity can never originate
    from model output.
    """

    model_config = ConfigDict(extra="forbid")

    employees: list[ExtractedEmployee]
    # Nullable for the same reason the hours fields are: a real email often states no pay
    # period at all ("hours for this week"), so the model returns null. That must flow
    # downstream as "didn't say" rather than crash extraction at parse time — a required
    # pay_period_start once broke a live run on an ordinary dateless email. The pay period
    # is informational on the paystub (pdf._period_label handles None) and is not a money
    # input, so a missing one is not worth failing a payroll over.
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
# RawFieldDrop — internal submitted_name-keyed field-regression record
# ---------------------------------------------------------------------------


class RawFieldDrop(BaseModel):
    """One hours value that was present in the original email and is gone from the reply.

    detect_field_regression returns list[RawFieldDrop]. submitted_name is from the CURRENT
    (resumed) extraction — the name the client used in their reply, which may differ from
    the name they first used.

    validate() receives these via the raw_field_drops= kwarg, because detection must run
    in the orchestrator on RAW data BEFORE backfill restores the old value.

    resumed_value distinguishes two very different client intents:
      None            -> silence; the client simply didn't mention the field.
      Decimal('0')    -> an explicit zero; the client deliberately removed the hours.
    Collapsing them would either underpay (treating silence as a deliberate removal) or
    overpay (backfilling hours the client explicitly zeroed out).

    This submitted_name-keyed record is the one the shipped pipeline actually uses. (See
    FieldDrop below for an employee_id-keyed variant that was scaffolded but never adopted.)
    """

    model_config = ConfigDict(extra="forbid")

    submitted_name: str
    field: str
    original_value: Decimal = Field(ge=0)
    resumed_value: Decimal | None = Field(default=None, ge=0)


# ---------------------------------------------------------------------------
# ClarifiedFields — typed validator for the clarified_fields JSONB column
# ---------------------------------------------------------------------------

ClarifiedFieldOutcome = Literal["asked", "carried_forward", "confirmed_dropped", "client_supplied"]
"""How a field-regression question was ultimately resolved.

Each label decides whether the original value gets backfilled, so a mislabel is a mispay.
Classification always reads the RAW reply BEFORE backfill, scoped to the fields we asked
about — reading post-backfill would make every outcome look like the client resupplied it.

- "asked": the question was sent; awaiting the client's reply.
- "carried_forward": the client was SILENT. The value comes from the pre-clarify snapshot,
  NOT from the reply. This label means the RAW reply had None/absent for the field — it is
  NOT the same as the client resupplying the identical value (that is "client_supplied").
- "confirmed_dropped": the client explicitly zeroed the field or said "none". Honor the
  removal and do NOT re-backfill. This is an OVERPAY guard: by value alone an explicit
  Decimal('0') looks exactly like an absent field and would otherwise be backfilled,
  paying hours the client just told us to remove.
- "client_supplied": the client replied with a POSITIVE replacement value — the raw
  extraction for this employee/field was present and positive before backfill.
"""


class ClarifiedFields(BaseModel):
    """Typed validator for the clarified_fields JSONB column.

    Shape: {employee_id_str: {field_name: outcome}}.

    Validate on EVERY write. These labels drive backfill, so a mislabel moves money in one
    direction or the other: carried_forward mislabeled as confirmed_dropped silently
    underpays (real hours never restored), and confirmed_dropped mislabeled as
    carried_forward silently overpays (hours the client removed get paid anyway). See
    ClarifiedFieldOutcome above for the full semantics of each label.
    """

    model_config = ConfigDict(extra="forbid")

    outcomes: dict[str, dict[str, ClarifiedFieldOutcome]]

    @classmethod
    def from_dict(
        cls, d: dict[str, dict[str, ClarifiedFieldOutcome]]
    ) -> ClarifiedFields:
        """Validate from a plain dict (outcomes=d)."""
        return cls(outcomes=d)

    def to_dict(self) -> dict[str, dict[str, ClarifiedFieldOutcome]]:
        """Return the raw outcomes dict."""
        return self.outcomes


# ---------------------------------------------------------------------------
# FieldDrop — employee_id-keyed field-regression record (currently unused)
# ---------------------------------------------------------------------------


class FieldDrop(BaseModel):
    """An employee_id-keyed field-regression record.

    CURRENTLY UNUSED: nothing in the codebase constructs, emits, or reads this type. The
    shipped field-regression path is keyed by submitted_name and uses RawFieldDrop
    (detect_field_regression -> validate). This model was scaffolding for an
    employee_id-keyed public record that was never adopted. Do not build on it without
    first deciding whether it should exist at all.

    Its intended semantics, if it is ever revived:
    - employee_id is always a real resolved UUID.
    - field is always a bare hours-field name, never qualified with submitted_name
      (e.g. "hours_overtime").
    - resumed_value=None means carried_forward: the reply was silent, so the original
      value should be backfilled.
    - resumed_value=Decimal('0') means confirmed_dropped: the client explicitly zeroed the
      field, so honor the removal and do NOT backfill.
    """

    model_config = ConfigDict(extra="forbid")

    employee_id: UUID
    field: str
    original_value: Decimal = Field(ge=0)
    resumed_value: Decimal | None = Field(ge=0)


# ---------------------------------------------------------------------------
# Decision — the deterministic decision object
# ---------------------------------------------------------------------------


class Decision(BaseModel):
    """The deterministic decision object — the core thesis of the design.

    final_action is computed PURELY by code over the resolution facts and is the SOLE
    branch source for the orchestrator, the dashboard, and the eval. There is no
    model-proposed action to diverge from: decide.py never calls an LLM.

    Note what this model deliberately does NOT have: any numeric field expressing how sure
    the system is. There is nowhere to put one, which means there is nothing for a future
    caller to threshold on — and a threshold is just a decision to pay somebody on a guess.

    request_clarification fires when any name is unresolved, any cross-name collision
    exists, or any required field is missing. gate_reasons lists exactly what triggered it,
    and is client-facing copy.

    resolutions carries the per-name resolution detail (one NameMatchResult per submitted
    name), folded into the decision JSONB so the dashboard and the eval can read WHY each
    name resolved or didn't. There is no separate name_matches table.
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

    All dollar amounts are Decimal. Hours are NON-nullable here, unlike ExtractedEmployee
    where they may be absent: this is the *computed* output, so by definition every hours
    value was resolved before the calc engine ran. A None reaching this type would mean the
    calc paid on data it never actually had.
    """

    model_config = ConfigDict(extra="forbid")

    id: UUID
    run_id: UUID
    employee_id: UUID | None  # None if the name never resolved
    # Provenance on a computed paystub is exactly employee_id + submitted_name. No score is
    # carried anywhere: the paystub records WHO was paid, never how sure we were.
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
    # The Additional Medicare 0.9% surtax on high wages is NOT modeled. When this flag is
    # True, the engine is KNOWN to under-withhold by 0.9% above the filing-status threshold.
    # The flag exists so that limitation is observable and test-backed on the paystub itself
    # rather than being an invisible gap. Default False keeps the field additive for
    # existing callers.
