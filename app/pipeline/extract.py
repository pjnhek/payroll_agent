"""Extraction: the one place the model READS the email. It never decides anything.

A PURE importable function: it takes typed values (InboundEmail, Roster) plus a code-owned
run_id, calls the one LLM client, and returns the Extracted contract. It does NO DB I/O and
takes no connection, so the eval can call it with fixture inputs.

Invariants:
  - run_id is CODE-OWNED plumbing, never a model field. The model's structured-output
    schema is ExtractionPayload (employees + pay period, extra="forbid", NO run_id).
    extract() validates that payload and then stamps the run_id the orchestrator passed in.
    If run_id were part of the model schema, a hallucinated or injected value could point
    the run's writes at somebody else's payroll.
  - Absent hours stay None. They are NEVER coerced to 0 — a 0 reads as "worked no hours"
    and would pay nothing, whereas None means "the client didn't tell us" and gates the run
    into a clarification.
  - A non-numeric hours value ("forty") is an EXTRACTION-stage parse failure, not a
    downstream validation issue: ExtractedEmployee hours are Decimal|None + ge=0 +
    extra="forbid", so it raises a Pydantic ValidationError inside the client's
    model_validate_json, goes through the one reflective retry, and if it still fails the
    orchestrator turns it into an ERROR. It never reaches validate.py.
"""
from __future__ import annotations

import uuid
from typing import Any

from app.llm import client as llm_client
from app.llm.prompts import extract as extract_prompt
from app.models.contracts import Extracted, ExtractionPayload, InboundEmail
from app.models.roster import Roster


def extract(
    email: InboundEmail,
    roster: Roster,
    *,
    run_id: uuid.UUID,
    llm: Any = llm_client,
) -> Extracted:
    """Extract employees + pay period from a cleaned inbound email.

    The model returns an ExtractionPayload (which carries no run_id); this function stamps
    the code-owned run_id onto it to build the Extracted contract. A non-numeric hours
    value raises while parsing ExtractionPayload, is routed through the client's one
    reflective retry, and then propagates.
    """
    messages = extract_prompt.build_messages(email, roster)
    payload: ExtractionPayload = llm.call_structured(
        "extraction", messages, ExtractionPayload
    )
    # Stamp the code-owned run_id. The model produced only the payload and must never
    # supply the identifier that this run's database writes are keyed on.
    return Extracted(
        run_id=run_id,
        employees=payload.employees,
        pay_period_start=payload.pay_period_start,
        pay_period_end=payload.pay_period_end,
    )
