"""Tests for the 2026 federal tax constants module (tax_tables_2026.py).

All assertions are structural / identity checks — no computation is tested here.
The golden suite (test_federal_withholding.py) exercises the bracket numbers end-to-end.

Sources verified against: irs.gov/pub/irs-pdf/p15t.pdf (retrieved 2026-06-22)
and ssa.gov/oact/cola/cbb.html.
"""
from __future__ import annotations

from decimal import Decimal


def test_module_imports_cleanly() -> None:
    """Module imports with no DB or network access (pure constants)."""
    from app.pipeline.tax_tables_2026 import (  # noqa: F401
        TAX_YEAR,
        SS_RATE,
        SS_WAGE_BASE,
        MEDICARE_RATE,
        STANDARD_BRACKETS,
        STEP2_BRACKETS,
        STEP1_STANDARD,
        BracketRow,
    )


def test_tax_year_is_2026() -> None:
    from app.pipeline.tax_tables_2026 import TAX_YEAR
    assert TAX_YEAR == 2026


def test_fica_constants() -> None:
    from app.pipeline.tax_tables_2026 import SS_RATE, SS_WAGE_BASE, MEDICARE_RATE
    assert SS_RATE == Decimal("0.062")
    assert SS_WAGE_BASE == Decimal("184500")
    assert MEDICARE_RATE == Decimal("0.0145")


def test_step1_standard_mfj() -> None:
    """Line 1g proxy for MFJ is $12,900 — NOT the 2026 standard deduction ($32,200)."""
    from app.pipeline.tax_tables_2026 import STEP1_STANDARD
    assert STEP1_STANDARD["married_jointly"] == Decimal("12900")
    # Must NOT be the 2026 standard deduction
    assert STEP1_STANDARD["married_jointly"] != Decimal("32200")


def test_step1_standard_single() -> None:
    """Line 1g proxy for Single is $8,600 — NOT the 2026 standard deduction ($16,100)."""
    from app.pipeline.tax_tables_2026 import STEP1_STANDARD
    assert STEP1_STANDARD["single"] == Decimal("8600")
    assert STEP1_STANDARD["single"] != Decimal("16100")


def test_step1_standard_mfs_equals_single() -> None:
    """MFS line 1g proxy matches Single ($8,600)."""
    from app.pipeline.tax_tables_2026 import STEP1_STANDARD
    assert STEP1_STANDARD["married_separately"] == Decimal("8600")


def test_mfs_standard_brackets_alias_single() -> None:
    """married_separately MUST be the same list object as single (Pitfall #4)."""
    from app.pipeline.tax_tables_2026 import STANDARD_BRACKETS
    assert STANDARD_BRACKETS["married_separately"] is STANDARD_BRACKETS["single"]


def test_mfs_step2_brackets_alias_single() -> None:
    """married_separately STEP2 MUST be the same list object as single."""
    from app.pipeline.tax_tables_2026 import STEP2_BRACKETS
    assert STEP2_BRACKETS["married_separately"] is STEP2_BRACKETS["single"]


def test_all_statuses_present_in_standard_brackets() -> None:
    from app.pipeline.tax_tables_2026 import STANDARD_BRACKETS
    for key in ["married_jointly", "single", "married_separately"]:
        assert key in STANDARD_BRACKETS, f"Missing key: {key}"


def test_all_statuses_present_in_step2_brackets() -> None:
    from app.pipeline.tax_tables_2026 import STEP2_BRACKETS
    for key in ["married_jointly", "single", "married_separately"]:
        assert key in STEP2_BRACKETS, f"Missing key: {key}"


def test_standard_brackets_have_8_rows_each() -> None:
    from app.pipeline.tax_tables_2026 import STANDARD_BRACKETS
    assert len(STANDARD_BRACKETS["married_jointly"]) == 8
    assert len(STANDARD_BRACKETS["single"]) == 8


def test_step2_brackets_have_8_rows_each() -> None:
    from app.pipeline.tax_tables_2026 import STEP2_BRACKETS
    assert len(STEP2_BRACKETS["married_jointly"]) == 8
    assert len(STEP2_BRACKETS["single"]) == 8


def test_bracket_rates_are_fractions_not_percentages() -> None:
    """All BracketRow.rate values must be < 1 (fractions, not percentages like 12)."""
    from app.pipeline.tax_tables_2026 import STANDARD_BRACKETS, STEP2_BRACKETS
    for brackets in [STANDARD_BRACKETS, STEP2_BRACKETS]:
        for status, rows in brackets.items():
            for row in rows:
                assert row.rate < Decimal("1"), (
                    f"[{status}] rate {row.rate} looks like a percentage, not a fraction"
                )


def test_top_bracket_has_none_upper() -> None:
    """The top bracket in each table has upper=None (no upper bound)."""
    from app.pipeline.tax_tables_2026 import STANDARD_BRACKETS, STEP2_BRACKETS
    for brackets in [STANDARD_BRACKETS, STEP2_BRACKETS]:
        for status, rows in brackets.items():
            if status == "married_separately":
                continue  # alias — already checked via "single"
            assert rows[-1].upper is None, (
                f"[{status}] top bracket upper should be None, got {rows[-1].upper}"
            )


def test_module_header_contains_source_urls(tmp_path) -> None:
    """The module docstring must contain both source URLs and retrieval date."""
    import inspect
    import app.pipeline.tax_tables_2026 as m
    source = inspect.getfile(m)
    with open(source) as f:
        content = f.read()
    assert "irs.gov/pub/irs-pdf/p15t.pdf" in content
    assert "ssa.gov/oact/cola/cbb.html" in content
    assert "Retrieved: 2026-06-22" in content


def test_mfj_standard_first_bracket_lower_is_zero() -> None:
    """MFJ standard first row starts at $0."""
    from app.pipeline.tax_tables_2026 import STANDARD_BRACKETS
    assert STANDARD_BRACKETS["married_jointly"][0].lower == Decimal("0")


def test_single_standard_first_bracket_lower_is_zero() -> None:
    """Single standard first row starts at $0."""
    from app.pipeline.tax_tables_2026 import STANDARD_BRACKETS
    assert STANDARD_BRACKETS["single"][0].lower == Decimal("0")


def test_mfj_step2_first_bracket_lower_is_zero() -> None:
    """MFJ step2 first row starts at $0."""
    from app.pipeline.tax_tables_2026 import STEP2_BRACKETS
    assert STEP2_BRACKETS["married_jointly"][0].lower == Decimal("0")


def test_single_step2_first_bracket_lower_is_zero() -> None:
    """Single step2 first row starts at $0."""
    from app.pipeline.tax_tables_2026 import STEP2_BRACKETS
    assert STEP2_BRACKETS["single"][0].lower == Decimal("0")


# Spot-check key bracket thresholds from RESEARCH.md Deliverable 1, Table 1A.1
def test_mfj_standard_second_bracket_lower() -> None:
    """MFJ standard: second bracket starts at $19,300."""
    from app.pipeline.tax_tables_2026 import STANDARD_BRACKETS
    row = STANDARD_BRACKETS["married_jointly"][1]
    assert row.lower == Decimal("19300")
    assert row.rate == Decimal("0.10")


def test_single_standard_second_bracket() -> None:
    """Single standard: second bracket starts at $7,500, 10%."""
    from app.pipeline.tax_tables_2026 import STANDARD_BRACKETS
    row = STANDARD_BRACKETS["single"][1]
    assert row.lower == Decimal("7500")
    assert row.rate == Decimal("0.10")


# Spot-check Step-2 brackets (verbatim transcription, NOT halved from standard)
def test_mfj_step2_second_bracket() -> None:
    """MFJ Step-2 second bracket: $16,100, 10% (verbatim from RESEARCH.md 1A.2)."""
    from app.pipeline.tax_tables_2026 import STEP2_BRACKETS
    row = STEP2_BRACKETS["married_jointly"][1]
    assert row.lower == Decimal("16100")
    assert row.rate == Decimal("0.10")


def test_single_step2_second_bracket() -> None:
    """Single/MFS Step-2 second bracket: $8,050, 10% (verbatim from RESEARCH.md 1A.2)."""
    from app.pipeline.tax_tables_2026 import STEP2_BRACKETS
    row = STEP2_BRACKETS["single"][1]
    assert row.lower == Decimal("8050")
    assert row.rate == Decimal("0.10")
