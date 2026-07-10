"""Tests for generate_paystub_pdf (HITL-03, D-11).

PURE function contract: PaystubLineItem + employee metadata in, PDF bytes out.
No DB, no filesystem, no connection.

Coverage:
  - Original contract tests (returns bytes, %PDF magic, pure/no-DB)
  - Richer layout: non-trivial size, valid PDF
  - Salaried path: all hours zero -> Salary row, no crash
  - DASH-02 guards: state_withholding None and pretax_401k zero both omit cleanly
  - Optional params: business_name and filing_status accepted without error
  - Deductions reconciliation: _sum_deductions helper is consistent with table rows
  - UAT #1: hourly_rate threaded in — Rate column renders; salaried path unaffected
"""
from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from app.models.contracts import PaystubLineItem
from app.pipeline.pdf import _sum_deductions, generate_paystub_pdf

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _minimal_item() -> PaystubLineItem:
    """A minimal PaystubLineItem suitable for PDF generation tests.

    All dollar amounts use Decimal("0") except where noted.
    state_withholding=None and pretax_401k=0 to exercise the omit paths.
    """
    now = datetime.now(UTC)
    return PaystubLineItem(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
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


def _hourly_item_multi_bucket() -> PaystubLineItem:
    """PaystubLineItem with multiple non-zero hour buckets and all deductions."""
    now = datetime.now(UTC)
    return PaystubLineItem(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        submitted_name="Jane Smith",
        hours_regular=Decimal("32"),
        hours_overtime=Decimal("8"),
        hours_vacation=Decimal("0"),
        hours_sick=Decimal("4"),
        hours_holiday=Decimal("0"),
        gross_pay=Decimal("2250.00"),
        pretax_401k=Decimal("90.00"),
        fica_ss=Decimal("139.50"),
        fica_medicare=Decimal("32.63"),
        federal_withholding=Decimal("210.00"),
        state_withholding=Decimal("56.25"),
        net_pay=Decimal("1721.62"),
        created_at=now,
        additional_medicare_not_modeled=False,
    )


def _salaried_item() -> PaystubLineItem:
    """PaystubLineItem where ALL hour buckets are zero (salaried employee)."""
    now = datetime.now(UTC)
    return PaystubLineItem(
        id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        employee_id=uuid.uuid4(),
        submitted_name="Salaried Person",
        hours_regular=Decimal("0"),
        hours_overtime=Decimal("0"),
        hours_vacation=Decimal("0"),
        hours_sick=Decimal("0"),
        hours_holiday=Decimal("0"),
        gross_pay=Decimal("5000.00"),
        pretax_401k=Decimal("200.00"),
        fica_ss=Decimal("310.00"),
        fica_medicare=Decimal("72.50"),
        federal_withholding=Decimal("500.00"),
        state_withholding=None,
        net_pay=Decimal("3917.50"),
        created_at=now,
        additional_medicare_not_modeled=False,
    )


_PAY_PERIOD_START = date(2026, 6, 15)
_PAY_PERIOD_END = date(2026, 6, 21)


# ---------------------------------------------------------------------------
# Original contract tests (must remain passing)
# ---------------------------------------------------------------------------


def test_generate_paystub_pdf_returns_bytes():
    """generate_paystub_pdf returns a non-empty bytes object (HITL-03)."""
    item = _minimal_item()
    result = generate_paystub_pdf(
        item, "Test Employee", _PAY_PERIOD_START, _PAY_PERIOD_END
    )
    assert isinstance(result, bytes), "generate_paystub_pdf must return bytes"
    assert len(result) > 0, "returned bytes must be non-empty"


def test_generate_paystub_pdf_valid_pdf_magic():
    """The bytes returned start with b'%PDF' (valid PDF magic bytes; HITL-03)."""
    item = _minimal_item()
    result = generate_paystub_pdf(
        item, "Test Employee", _PAY_PERIOD_START, _PAY_PERIOD_END
    )
    assert result[:4] == b"%PDF", (
        "generate_paystub_pdf must produce a valid PDF (magic bytes b'%PDF' at offset 0)"
    )


def test_generate_paystub_pdf_pure_no_db():
    """Calling generate_paystub_pdf with no DB connection available must not raise.

    The function is a pure stage: data in -> bytes out. No DB, no filesystem write
    (HITL-03: Render ephemeral FS constraint).
    """
    item = _minimal_item()
    result = generate_paystub_pdf(
        item, "Test Employee", _PAY_PERIOD_START, _PAY_PERIOD_END
    )
    assert result is not None, "pure function must return PDF bytes, not None"


# ---------------------------------------------------------------------------
# Richer layout size check
# ---------------------------------------------------------------------------


def test_generate_paystub_pdf_nontrivial_size():
    """The richer multi-section layout produces a non-trivially sized PDF.

    reportlab with built-in Helvetica (not embedded) produces compact PDFs.
    The full stub with five sections (header band, employee block, two tables,
    net-pay band, footer) should comfortably exceed 2 KB.  We use 2000 bytes
    as the lower bound — well above a near-empty document (~200 bytes) and
    achievable even with all-zero minimal fixtures.
    """
    item = _minimal_item()
    result = generate_paystub_pdf(
        item, "Test Employee", _PAY_PERIOD_START, _PAY_PERIOD_END
    )
    assert len(result) > 2_000, (
        f"Expected richer PDF > 2KB, got {len(result)} bytes — layout may be missing"
    )


# ---------------------------------------------------------------------------
# Salaried path (all hours zero)
# ---------------------------------------------------------------------------


def test_generate_paystub_pdf_salaried_renders_without_error():
    """All hour buckets zero -> Salary row path renders without raising."""
    item = _salaried_item()
    result = generate_paystub_pdf(
        item, "Salaried Person", _PAY_PERIOD_START, _PAY_PERIOD_END
    )
    assert result[:4] == b"%PDF"
    assert len(result) > 0


# ---------------------------------------------------------------------------
# DASH-02 / optional field omit paths
# ---------------------------------------------------------------------------


def test_state_withholding_none_renders_cleanly():
    """state_withholding=None omits that row cleanly (DASH-02)."""
    item = _minimal_item()
    assert item.state_withholding is None  # confirm fixture
    result = generate_paystub_pdf(
        item, "Test Employee", _PAY_PERIOD_START, _PAY_PERIOD_END
    )
    assert result[:4] == b"%PDF"


def test_pretax_401k_zero_omits_cleanly():
    """pretax_401k=0 row is omitted cleanly from the deductions table."""
    item = _minimal_item()
    assert item.pretax_401k == Decimal("0")  # confirm fixture
    result = generate_paystub_pdf(
        item, "Test Employee", _PAY_PERIOD_START, _PAY_PERIOD_END
    )
    assert result[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# Optional keyword params: business_name and filing_status
# ---------------------------------------------------------------------------


def test_business_name_does_not_error():
    """Passing business_name renders without error."""
    item = _minimal_item()
    result = generate_paystub_pdf(
        item,
        "Test Employee",
        _PAY_PERIOD_START,
        _PAY_PERIOD_END,
        business_name="Acme Widgets LLC",
    )
    assert result[:4] == b"%PDF"
    assert len(result) > 0


def test_filing_status_does_not_error():
    """Passing filing_status renders without error."""
    item = _minimal_item()
    result = generate_paystub_pdf(
        item,
        "Test Employee",
        _PAY_PERIOD_START,
        _PAY_PERIOD_END,
        filing_status="Single",
    )
    assert result[:4] == b"%PDF"


def test_both_optional_params_together():
    """Passing both business_name and filing_status renders without error."""
    item = _hourly_item_multi_bucket()
    result = generate_paystub_pdf(
        item,
        "Jane Smith",
        _PAY_PERIOD_START,
        _PAY_PERIOD_END,
        business_name="Regional Tax Services",
        filing_status="Married Filing Jointly",
    )
    assert result[:4] == b"%PDF"
    assert len(result) > 0


def test_no_optional_params_unchanged_call_works():
    """Omitting both optional params (existing caller pattern) still works."""
    item = _minimal_item()
    result = generate_paystub_pdf(
        item, "Test Employee", _PAY_PERIOD_START, _PAY_PERIOD_END
    )
    assert result[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# Deductions sum reconciliation
# ---------------------------------------------------------------------------


def test_sum_deductions_reconciles_with_visible_rows():
    """_sum_deductions returns the sum of exactly the rows shown in the table.

    Multi-deduction item with state_withholding and pretax_401k both non-zero.
    """
    item = _hourly_item_multi_bucket()
    assert item.state_withholding is not None
    computed = _sum_deductions(item)
    expected = (
        item.federal_withholding
        + item.fica_ss
        + item.fica_medicare
        + item.state_withholding  # non-None, shown
        + item.pretax_401k       # non-zero, shown
    )
    assert computed == expected, (
        f"_sum_deductions={computed} did not match manual sum={expected}"
    )


def test_sum_deductions_excludes_omitted_rows():
    """_sum_deductions excludes state_withholding=None and pretax_401k=0.

    Ensures the TOTAL DEDUCTIONS band value matches the rendered table rows.
    """
    item = _minimal_item()
    # state_withholding=None, pretax_401k=0 -> only fica_ss + fica_medicare + federal
    computed = _sum_deductions(item)
    expected = item.fica_ss + item.fica_medicare + item.federal_withholding
    assert computed == expected


def test_multi_deduction_pdf_builds():
    """Multi-deduction item with state + 401k builds a valid PDF end-to-end."""
    item = _hourly_item_multi_bucket()
    result = generate_paystub_pdf(
        item, "Jane Smith", _PAY_PERIOD_START, _PAY_PERIOD_END
    )
    assert result[:4] == b"%PDF"
    assert len(result) > 2_000


# ---------------------------------------------------------------------------
# Additional Medicare footnote path
# ---------------------------------------------------------------------------


def test_additional_medicare_flag_renders():
    """additional_medicare_not_modeled=True renders the footnote without error."""
    item = _minimal_item()
    item_with_flag = item.model_copy(update={"additional_medicare_not_modeled": True})
    result = generate_paystub_pdf(
        item_with_flag, "Test Employee", _PAY_PERIOD_START, _PAY_PERIOD_END
    )
    assert result[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# Edge cases: None pay period dates
# ---------------------------------------------------------------------------


def test_no_pay_period_end_renders():
    """pay_period_end=None falls back to start-only label without error."""
    item = _minimal_item()
    result = generate_paystub_pdf(item, "Test Employee", _PAY_PERIOD_START, None)
    assert result[:4] == b"%PDF"


def test_no_pay_period_at_all_renders():
    """Both pay period dates None -> em-dash label, no crash."""
    item = _minimal_item()
    result = generate_paystub_pdf(item, "Test Employee", None, None)
    assert result[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# UAT #1: hourly_rate keyword param — Rate column on earnings table
# ---------------------------------------------------------------------------


def test_hourly_rate_does_not_error():
    """Passing hourly_rate renders without error and returns valid PDF (UAT #1)."""
    item = _minimal_item()
    result = generate_paystub_pdf(
        item,
        "Test Employee",
        _PAY_PERIOD_START,
        _PAY_PERIOD_END,
        hourly_rate=Decimal("20.00"),
    )
    assert isinstance(result, bytes), "generate_paystub_pdf must return bytes"
    assert result[:4] == b"%PDF", "must produce valid PDF when hourly_rate is provided"
    assert len(result) > 2_000, "PDF with rate column must exceed 2KB"


def test_hourly_rate_with_overtime_does_not_error():
    """hourly_rate + overtime hours: OT rate (1.5x) shown without crash."""
    item = _hourly_item_multi_bucket()
    result = generate_paystub_pdf(
        item,
        "Jane Smith",
        _PAY_PERIOD_START,
        _PAY_PERIOD_END,
        hourly_rate=Decimal("25.00"),
    )
    assert result[:4] == b"%PDF"
    assert len(result) > 2_000


def test_hourly_rate_none_salaried_path_unaffected():
    """hourly_rate=None (salaried) omits Rate column cleanly — no fabricated rate."""
    item = _salaried_item()
    result = generate_paystub_pdf(
        item,
        "Salaried Person",
        _PAY_PERIOD_START,
        _PAY_PERIOD_END,
        hourly_rate=None,
    )
    assert result[:4] == b"%PDF"
    assert len(result) > 0


def test_all_optional_params_together():
    """Passing business_name, filing_status, and hourly_rate all at once renders without error."""
    item = _hourly_item_multi_bucket()
    result = generate_paystub_pdf(
        item,
        "Jane Smith",
        _PAY_PERIOD_START,
        _PAY_PERIOD_END,
        business_name="Coastal Cleaning Co.",
        filing_status="Single",
        hourly_rate=Decimal("18.50"),
    )
    assert result[:4] == b"%PDF"
    assert len(result) > 2_000


def test_hourly_rate_omitted_existing_callers_unchanged():
    """Omitting hourly_rate entirely (existing caller pattern) still works."""
    item = _minimal_item()
    result = generate_paystub_pdf(
        item, "Test Employee", _PAY_PERIOD_START, _PAY_PERIOD_END
    )
    assert result[:4] == b"%PDF"
