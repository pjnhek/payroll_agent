"""GUARD-04: RowProjection.from_row's allowlist -- an undeclared, un-excluded row
column raises UnclassifiedColumnError naming the offending key; a fully classified
row validates. This module also carries the RUN_COLS drift test: a column that
reaches app.db.repo.runs.RUN_COLS without a deliberate exposure classification in
app.schemas.run_columns.RUN_COL_CLASSIFICATION fails here, by name.
"""
from __future__ import annotations

import pathlib
from typing import ClassVar
from uuid import uuid4

import pytest

from app.db.repo.runs import RUN_COLS
from app.schemas._projection import RowProjection, UnclassifiedColumnError
from app.schemas.run_columns import RUN_COL_CLASSIFICATION, ColumnExposure
from app.schemas.runs_list import RunListRow

# The fifteen column names read live off app.db.repo.runs.RUN_COLS at the time
# this test was written -- re-derived from source, not copied from a planning
# document. Drift in either direction (a column added or removed from RUN_COLS)
# fails test_run_col_set_is_non_empty_and_known below, by name.
_EXPECTED_RUN_COLS = frozenset(
    {
        "id",
        "business_id",
        "source_email_id",
        "status",
        "reply_epoch",
        "extracted_data",
        "decision",
        "reconciliation",
        "error_reason",
        "error_detail",
        "alias_candidates",
        "hours_changes",
        "pay_period_start",
        "pay_period_end",
        "updated_at",
    }
)


def _parse_run_cols() -> set[str]:
    """Parse RUN_COLS into a set of bare column names.

    Splits on commas and strips surrounding whitespace, so a column written
    with extra whitespace or across a line continuation still matches its
    classification by exact name.
    """
    return {col.strip() for col in RUN_COLS.split(",") if col.strip()}


class _Widget(RowProjection):
    """A minimal RowProjection subclass, independent of RunListRow's specific
    field set, so these tests exercise the base allowlist behavior directly."""

    EXCLUDED: ClassVar[frozenset[str]] = frozenset({"internal_only"})

    name: str


def test_from_row_raises_on_unclassified_column() -> None:
    with pytest.raises(UnclassifiedColumnError, match="mystery_field"):
        _Widget.from_row({"name": "a", "internal_only": 1, "mystery_field": 2})


def test_from_row_error_names_every_unclassified_key_sorted() -> None:
    with pytest.raises(UnclassifiedColumnError) as exc_info:
        _Widget.from_row({"name": "a", "zeta": 1, "alpha": 2})
    message = str(exc_info.value)
    assert "alpha" in message
    assert "zeta" in message
    # sorted(): alpha must be named before zeta in the error message.
    assert message.index("alpha") < message.index("zeta")


def test_from_row_validates_fully_classified_row() -> None:
    widget = _Widget.from_row({"name": "a", "internal_only": 1})
    assert widget.name == "a"


def test_from_row_validates_row_with_no_excluded_keys_present() -> None:
    """EXCLUDED naming a key does not require that key to be present."""
    widget = _Widget.from_row({"name": "a"})
    assert widget.name == "a"


def test_row_projection_extra_forbid_still_applies_to_from_row_output() -> None:
    """from_row filters to declared fields before validating -- an excluded key
    is dropped, not smuggled through model_validate as an ignored extra."""
    widget = _Widget.from_row({"name": "a", "internal_only": "should not survive"})
    assert not hasattr(widget, "internal_only")


def test_run_list_row_excludes_business_id() -> None:
    """GUARD-04 smoke test for the concrete DTO this plan ships: business_id is
    named in EXCLUDED and is not a declared, exposed field."""
    assert "business_id" in RunListRow.EXCLUDED
    assert "business_id" not in RunListRow.model_fields


def test_run_list_row_from_row_raises_on_a_genuinely_new_column() -> None:
    """A repository column neither declared nor excluded -- the exact failure
    mode this allowlist exists to catch before it reaches the browser."""
    row = {
        "id": uuid4(),
        "created_at": None,
        "created_at_display": "—",
        "business_name": "Acme",
        "status": "received",
        "badge_class": "neutral",
        "badge_label": "Received",
        "queue_label": None,
        "queue_badge_class": "neutral",
        "has_open_job": False,
        "failure": {
            "secondary_label": None,
            "stage": None,
            "reason": None,
            "attempts": None,
        },
        "summary_gate_reason": None,
        "employee_count": 0,
        "brand_new_column_nobody_classified_yet": "leak me",
    }
    with pytest.raises(
        UnclassifiedColumnError, match="brand_new_column_nobody_classified_yet"
    ):
        RunListRow.from_row(row)


# ---------------------------------------------------------------------------
# GUARD-04: every RUN_COLS column has exactly one deliberate exposure
# classification. Hermetic -- RUN_COLS is a module constant, so no database
# connection is needed anywhere in this section.
# ---------------------------------------------------------------------------


def test_run_col_set_is_non_empty_and_known() -> None:
    """Guard the guard: without this, an unparseable or emptied RUN_COLS
    constant would make every difference-based assertion below pass on an
    empty set, which is precisely the vacuous pass this guard exists to
    prevent."""
    parsed = _parse_run_cols()
    assert parsed, "RUN_COLS parsed to an empty column set"
    assert parsed == _EXPECTED_RUN_COLS, (
        "RUN_COLS drifted from the expected fifteen columns.\n"
        f"  Missing: {sorted(_EXPECTED_RUN_COLS - parsed)}\n"
        f"  Added:   {sorted(parsed - _EXPECTED_RUN_COLS)}"
    )


def test_every_run_col_is_classified() -> None:
    """A column reaching RUN_COLS with no entry in RUN_COL_CLASSIFICATION is
    neither exposed in a page's response shape nor named internal-only -- the
    exact silent-leak shape GUARD-04 exists to catch, named by column."""
    parsed = _parse_run_cols()
    unclassified = parsed - set(RUN_COL_CLASSIFICATION)
    assert not unclassified, (
        f"column(s) {sorted(unclassified)} reached RUN_COLS while neither "
        "exposed on a page's response shape nor named internal-only in "
        "RUN_COL_CLASSIFICATION (app/schemas/run_columns.py)"
    )


def test_no_classification_entry_is_stale() -> None:
    """A removed column must leave no dangling RUN_COL_CLASSIFICATION entry."""
    parsed = _parse_run_cols()
    stale = set(RUN_COL_CLASSIFICATION) - parsed
    assert not stale, (
        f"RUN_COL_CLASSIFICATION carries entry/entries for {sorted(stale)}, "
        "which no longer appear in RUN_COLS -- remove the stale entry/entries"
    )


def test_list_exposed_columns_are_declared_on_the_list_shape() -> None:
    """Every list-exposed column is a declared RunListRow field; every
    internal-only column is never a declared RunListRow field."""
    for column, exposure in RUN_COL_CLASSIFICATION.items():
        if exposure is ColumnExposure.LIST_EXPOSED:
            assert column in RunListRow.model_fields, (
                f"{column} is classified list_exposed but is not a declared "
                "RunListRow field"
            )
        elif exposure is ColumnExposure.INTERNAL_ONLY:
            assert column in RunListRow.EXCLUDED or column not in (
                RunListRow.model_fields
            ), (
                f"{column} is classified internal_only but is exposed as a "
                "declared RunListRow field with no EXCLUDED entry"
            )


def test_list_and_detail_shapes_are_separate() -> None:
    """The list projection (app.db.repo.demo.load_all_runs) selects a
    created_at column RUN_COLS does not carry at all -- proof that one shared
    response shape between the list and detail pages is structurally
    impossible, not merely undesirable."""
    demo_source = pathlib.Path("app/db/repo/demo.py").read_text()
    assert "pr.created_at" in demo_source, (
        "expected app.db.repo.demo.load_all_runs' SQL to select created_at -- "
        "if this changed, the separation proof below needs re-deriving"
    )
    assert "created_at" not in _parse_run_cols(), (
        "created_at appearing in RUN_COLS would make this separation proof "
        "stale -- the list and detail pages would no longer be structurally "
        "forced apart on this column"
    )
