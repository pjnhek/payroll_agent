"""Wave 0 RED stubs: generate_paystub_pdf behavior (HITL-03, D-11).

These tests will fail RED until Wave 2 creates app/pipeline/pdf.py with
a `generate_paystub_pdf` implementation (pure function, reportlab-backed).

PURE function contract: PaystubLineItem + employee metadata in, PDF bytes out.
No DB, no filesystem, no connection.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

# This import FAILS RED until Wave 2 creates app/pipeline/pdf.py.
from app.pipeline.pdf import generate_paystub_pdf

from app.models.contracts import PaystubLineItem


# ---------------------------------------------------------------------------
# Minimal PaystubLineItem fixture
# ---------------------------------------------------------------------------


def _minimal_item() -> PaystubLineItem:
    """A minimal PaystubLineItem suitable for PDF generation tests.

    All dollar amounts use Decimal("0") except net_pay, which is set to a
    readable value so the floor-string tests have something to assert on.
    """
    now = datetime.now(timezone.utc)
    run_id = uuid.uuid4()
    employee_id = uuid.uuid4()
    return PaystubLineItem(
        id=uuid.uuid4(),
        run_id=run_id,
        employee_id=employee_id,
        submitted_name="Test Employee",
        hours_regular=Decimal("40"),
        hours_overtime=Decimal("0"),
        hours_vacation=Decimal("0"),
        hours_sick=Decimal("0"),
        hours_holiday=Decimal("0"),
        gross_pay=Decimal("1600.00"),
        pretax_401k=Decimal("0"),
        fica_ss=Decimal("99.20"),
        fica_medicare=Decimal("23.20"),
        federal_withholding=Decimal("0"),
        state_withholding=None,
        net_pay=Decimal("1477.60"),
        created_at=now,
        additional_medicare_not_modeled=False,
    )


_PAY_PERIOD_START = date(2026, 6, 15)
_PAY_PERIOD_END = date(2026, 6, 21)


# ---------------------------------------------------------------------------
# Test 1: returns non-empty bytes
# ---------------------------------------------------------------------------


def test_generate_paystub_pdf_returns_bytes():
    """generate_paystub_pdf returns a non-empty bytes object (HITL-03).

    Will fail RED until Wave 2 creates app/pipeline/pdf.py.
    """
    item = _minimal_item()
    result = generate_paystub_pdf(
        item, "Test Employee", _PAY_PERIOD_START, _PAY_PERIOD_END
    )
    assert isinstance(result, bytes), "generate_paystub_pdf must return bytes"
    assert len(result) > 0, "returned bytes must be non-empty"


# ---------------------------------------------------------------------------
# Test 2: valid PDF magic bytes
# ---------------------------------------------------------------------------


def test_generate_paystub_pdf_valid_pdf_magic():
    """The bytes returned start with b'%PDF' (valid PDF magic bytes; HITL-03).

    Will fail RED until Wave 2 creates app/pipeline/pdf.py.
    """
    item = _minimal_item()
    result = generate_paystub_pdf(
        item, "Test Employee", _PAY_PERIOD_START, _PAY_PERIOD_END
    )
    assert result[:4] == b"%PDF", (
        "generate_paystub_pdf must produce a valid PDF (magic bytes b'%PDF' at offset 0)"
    )


# ---------------------------------------------------------------------------
# Test 3: pure function — no DB dependency
# ---------------------------------------------------------------------------


def test_generate_paystub_pdf_pure_no_db():
    """Calling generate_paystub_pdf with no DB connection available must not raise.

    The function is a pure stage: data in → bytes out. No DB, no filesystem write
    (HITL-03: Render ephemeral FS constraint). Will fail RED until Wave 2.
    """
    item = _minimal_item()
    # Intentionally pass no DB conn — the function must not need one.
    result = generate_paystub_pdf(
        item, "Test Employee", _PAY_PERIOD_START, _PAY_PERIOD_END
    )
    # If we get here without an exception, the pure-function contract holds.
    assert result is not None, "pure function must return PDF bytes, not None"
