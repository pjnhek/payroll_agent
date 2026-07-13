"""Extraction stage tests (LLM-03). Mocked LLM, DB-free.

Covers: the code-owned run_id stamping, the no-run_id ExtractionPayload schema,
absent hours preserved as None (never coerced to 0), and a non-numeric extraction
value routing to the reflective retry and then to ERROR.
"""
from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.models.contracts import Extracted, ExtractionPayload
from app.pipeline.extract import extract


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# extract() stamps the code-owned run_id; the model never supplies it
# ---------------------------------------------------------------------------


def test_extract_stamps_code_owned_run_id(inbound_email, roster_from_seed, mock_llm):
    run_id = uuid.UUID("11111111-2222-3333-4444-555555555555")
    mock_llm.script = [
        json.dumps(
            {
                "employees": [
                    {"submitted_name": "Maria Chen", "hours_regular": "40"},
                    {"submitted_name": "James Okafor"},
                ],
                "pay_period_start": "2026-06-15",
                "pay_period_end": None,
            }
        )
    ]

    out = extract(inbound_email, roster_from_seed, run_id=run_id)

    assert isinstance(out, Extracted)
    # The returned Extracted carries the PASSED-IN run_id, not anything model-made.
    assert out.run_id == run_id
    # The response_model handed to the client is ExtractionPayload, never Extracted.
    # (No run_id key was in the scripted JSON, yet Extracted.run_id is populated.)
    assert out.employees[0].submitted_name == "Maria Chen"
    assert out.employees[0].hours_regular == Decimal("40")
    # Absent hours stay None — never coerced to 0. Coercing would pay the employee
    # zero for a period the client simply did not describe.
    assert out.employees[1].hours_regular is None
    assert out.employees[0].hours_overtime is None


def test_payload_schema_has_no_run_id():
    """ExtractionPayload is extra='forbid' with NO run_id — a run_id key raises."""
    # A valid payload (no run_id) validates.
    ok = ExtractionPayload.model_validate_json(
        json.dumps(
            {
                "employees": [{"submitted_name": "Ann", "hours_regular": "10"}],
                "pay_period_start": "2026-06-15",
            }
        )
    )
    assert ok.employees[0].submitted_name == "Ann"
    assert "run_id" not in ExtractionPayload.model_fields

    # A run_id key in the model output is rejected (the model cannot smuggle one).
    with pytest.raises(ValidationError):
        ExtractionPayload.model_validate_json(
            json.dumps(
                {
                    "run_id": str(uuid.uuid4()),
                    "employees": [{"submitted_name": "Ann"}],
                    "pay_period_start": "2026-06-15",
                }
            )
        )


# ---------------------------------------------------------------------------
# A non-numeric hours value routes to the reflective retry, then ERROR
# ---------------------------------------------------------------------------


def test_non_numeric_hours_routes_to_retry_then_error(
    inbound_email, roster_from_seed, mock_llm
):
    """"forty" makes ExtractionPayload.model_validate_json raise → one reflective
    retry; if the retry also fails, the client raises (run destined for ERROR).
    This is the documented non_numeric path — an EXTRACTION-stage parse failure,
    NOT a validate.py issue."""
    bad = json.dumps(
        {
            "employees": [{"submitted_name": "Maria Chen", "hours_regular": "forty"}],
            "pay_period_start": "2026-06-15",
        }
    )
    # Both attempts return the non-numeric value → the client raises after retry.
    mock_llm.script = [bad, bad]

    with pytest.raises(ValidationError):
        extract(inbound_email, roster_from_seed, run_id=uuid.uuid4())

    # Exactly two create() calls: the original + the one reflective retry.
    assert len(mock_llm.calls) == 2, "must retry exactly once before propagating"
