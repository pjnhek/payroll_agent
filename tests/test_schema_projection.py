"""GUARD-04: RowProjection.from_row's allowlist -- an undeclared, un-excluded row
column raises UnclassifiedColumnError naming the offending key; a fully classified
row validates. Plan 22-07 extends this module with the RUN_COLS drift test.
"""
from __future__ import annotations

from typing import ClassVar
from uuid import uuid4

import pytest

from app.schemas._projection import RowProjection, UnclassifiedColumnError
from app.schemas.runs_list import RunListRow


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
