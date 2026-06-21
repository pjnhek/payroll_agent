"""Stage 1 — extraction (LLM-03; review FIX A, FIX 1).

A PURE importable function: it takes typed values (InboundEmail, Roster) and a
code-owned run_id, calls the one LLM client, and returns the Extracted contract.
It does NO DB I/O and takes no connection (purity = no-DB, NOT no-run_id) so the
Phase 4 eval can call it with fixture inputs.

FIX A — run_id is code-owned plumbing, NOT an LLM field:
  The LLM structured-output schema is ExtractionPayload (employees + pay_period,
  extra="forbid", NO run_id). extract() validates that payload, then CONSTRUCTS
  Extracted(run_id=run_id, **payload) stamping the run_id the orchestrator passed
  in — exactly like `roster` is passed in. The model never invents or echoes a
  trusted run_id.

FIX 1 — the non_numeric path is an EXTRACTION-stage parse failure:
  Because ExtractedEmployee hours are Decimal|None + ge=0 + extra="forbid", a
  non-numeric value ("forty") raises a Pydantic ValidationError INSIDE the
  client's model_validate_json of ExtractionPayload → the ONE reflective retry →
  raise if still failing → the orchestrator converts the raise to ERROR. It NEVER
  reaches validate.py. Absent hours stay None (load-bearing — never coerced to 0).
"""
from __future__ import annotations

import uuid

from app.llm import client as llm_client
from app.llm.prompts import extract as extract_prompt
from app.models.contracts import Extracted, ExtractionPayload, InboundEmail
from app.models.roster import Roster


def extract(
    email: InboundEmail,
    roster: Roster,
    *,
    run_id: uuid.UUID,
    llm=llm_client,
) -> Extracted:
    """Extract employees + pay period from a cleaned inbound email.

    The LLM returns an ExtractionPayload (no run_id); this stamps the code-owned
    run_id to build the required Extracted contract (FIX A). A non-numeric hours
    value raises at parse time of ExtractionPayload, routed through the client's
    one reflective retry, then propagates (FIX 1).
    """
    messages = extract_prompt.build_messages(email, roster)
    payload: ExtractionPayload = llm.call_structured(
        "extraction", messages, ExtractionPayload
    )
    # FIX A: stamp the code-owned run_id; the model produced only the payload.
    return Extracted(
        run_id=run_id,
        employees=payload.employees,
        pay_period_start=payload.pay_period_start,
        pay_period_end=payload.pay_period_end,
    )
