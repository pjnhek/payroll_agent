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
        MEDICARE_RATE,
        SS_RATE,
        SS_WAGE_BASE,
        STANDARD_BRACKETS,
        STEP1_STANDARD,
        STEP2_BRACKETS,
        TAX_YEAR,
        BracketRow,
    )


def test_tax_year_is_2026() -> None:
    from app.pipeline.tax_tables_2026 import TAX_YEAR
    assert TAX_YEAR == 2026


def test_fica_constants() -> None:
    from app.pipeline.tax_tables_2026 import MEDICARE_RATE, SS_RATE, SS_WAGE_BASE
    assert Decimal("0.062") == SS_RATE
    assert Decimal("184500") == SS_WAGE_BASE
    assert Decimal("0.0145") == MEDICARE_RATE


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
    """married_separately MUST be the SAME list object as single.

    The IRS publishes one shared column for both statuses. Copying the rows instead of
    aliasing them lets a future edit fix a bracket in one status and silently leave the
    other wrong.
    """
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


def test_single_step2_top_bracket_boundary_verified_against_irs() -> None:
    """Single/MFS Step-2 37% bracket begins at $328,350, base $96,489.63 — verified.

    These figures look wrong under the tempting "MFJ = 2x Single" heuristic, which would
    put the boundary at $200,225. That heuristic does NOT hold for the IRS Step-2
    schedules. Verified against the live IRS source (irs.gov/publications/p15t, 2026,
    retrieved 2026-06-22): the boundary really is $328,350 with base $96,489.63, exactly
    as transcribed.

    This test pins the verified values so a well-meaning "correction" toward the
    heuristic can never be silently applied.
    """
    from app.pipeline.tax_tables_2026 import STEP2_BRACKETS
    top = STEP2_BRACKETS["single"][-1]
    assert top.lower == Decimal("328350"), "IRS-verified Single/MFS Step-2 37% boundary"
    assert top.upper is None
    assert top.base == Decimal("96489.63"), "IRS-verified Single/MFS Step-2 37% base"
    assert top.rate == Decimal("0.37")


# ---------------------------------------------------------------------------
# Bracket base/rate continuity smoke-test.
#
# Each row's base is the cumulative tax at that bracket's lower bound:
#   base[i] ≈ base[i-1] + (lower[i] - lower[i-1]) * rate[i-1]
# A GROSS transcription error (a wrong boundary, or a base off by whole dollars —
# the kind that silently mis-withholds high earners) breaks this identity by dollars.
#
# IMPORTANT — why the tolerance is ~$1, NOT exact equality:
# The IRS publishes whole-cent base amounts that do NOT perfectly satisfy pure
# continuity, because the printed bracket BOUNDARIES are themselves rounded. This was
# verified against the live IRS source for the Single/MFS Step-2 schedule:
#   - 32% row [108,938 - 136,163): IRS prints base $20,512.00; pure continuity gives
#     $20,512.12 (a $0.12 artifact of the rounded $108,938 boundary).
#   - 37% row [328,350 - inf): IRS prints base $96,489.63; continuity gives ~$96,489.45.
# Both printed figures are CORRECT per irs.gov/publications/p15t (2026), confirmed
# 2026-06-22. An exact-equality continuity test would therefore reject the IRS's own
# published tables. The < $1 tolerance catches real (dollar-scale) transcription
# errors while tolerating the IRS's inherent sub-dollar boundary-rounding drift.
# ---------------------------------------------------------------------------
def test_bracket_base_continuity_smoke() -> None:
    """Each bracket base ties to the cumulative tax at its lower bound within < $1.

    Guards against gross (dollar-scale) transcription errors in any of the six
    schedules. Tolerance is sub-dollar by design — see the module comment above for
    why exact equality would (incorrectly) reject the real IRS tables.
    """
    from app.pipeline.tax_tables_2026 import STANDARD_BRACKETS, STEP2_BRACKETS

    seen: set[int] = set()
    for table_name, table in (("STANDARD", STANDARD_BRACKETS), ("STEP2", STEP2_BRACKETS)):
        for status, rows in table.items():
            if id(rows) in seen:  # skip the married_separately alias of single
                continue
            seen.add(id(rows))
            for i in range(1, len(rows)):
                prev, cur = rows[i - 1], rows[i]
                derived = prev.base + (cur.lower - prev.lower) * prev.rate
                drift = abs(cur.base - derived)
                assert drift < Decimal("1"), (
                    f"[{table_name}/{status}] row {i} (lower={cur.lower}): base "
                    f"{cur.base} drifts {drift} from continuity-derived {derived} "
                    f"(>= $1 => likely a real transcription error, not IRS rounding)."
                )


def test_bracket_upper_ties_to_next_lower() -> None:
    """Each row's `upper` must equal the next row's `lower`.

    `BracketRow.upper` is transcribed on all 48 rows but `_find_bracket()` only reads
    `lower`, so `upper` is otherwise dead data that could silently drift out of sync with
    the real boundary (the next row's `lower`). This guard keeps the unused column honest
    so a transcription typo in `upper` can't rot undetected.
    """
    from app.pipeline.tax_tables_2026 import STANDARD_BRACKETS, STEP2_BRACKETS

    seen: set[int] = set()
    for table in (STANDARD_BRACKETS, STEP2_BRACKETS):
        for status, rows in table.items():
            if id(rows) in seen:  # skip the married_separately alias of single
                continue
            seen.add(id(rows))
            for i in range(len(rows) - 1):
                assert rows[i].upper == rows[i + 1].lower, (
                    f"[{status}] row {i}: upper {rows[i].upper} != next.lower "
                    f"{rows[i + 1].lower}"
                )
            assert rows[-1].upper is None, f"[{status}] top row upper must be None"


def test_money_helpers_agree() -> None:
    """IN-02 (review round 2): the two intentionally-duplicated _money() helpers must agree.

    _money() is deliberately copied into federal_withholding.py (for independent
    importability — documented round-1 decision). The risk of duplication is drift: both
    copies must use the identical rounding mode (ROUND_HALF_UP). This locks them together
    so a future edit to one (e.g. switching to ROUND_HALF_EVEN) is caught immediately.
    """
    from app.pipeline.calculate import _money as money_calc
    from app.pipeline.federal_withholding import _money as money_fed

    for v in ("1.005", "2.675", "0.125", "-1.005", "0.00", "99999.999"):
        assert money_calc(Decimal(v)) == money_fed(Decimal(v)), f"drift at {v}"
