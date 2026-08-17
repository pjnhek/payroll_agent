"""RunListRow / RunsListPage -- the allowlist DTO embedded in GET /runs's page data
island.

Built from the same `_safe_run_for_browser`-reduced row `runs_list.html` rendered
directly before this page converted to React, plus two things computed server-side for
the same reason `_safe_run_for_browser`'s badge vocabulary is: a second implementation
in TypeScript would drift, and formatting a timestamp in the browser would silently
shift it into the viewer's timezone.
"""
from __future__ import annotations

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.schemas._projection import RowProjection
from app.schemas.run_status import FailureInfo, RunStatusPoll

# Re-exported for backward compatibility: `app/schemas/__init__.py` imports
# `FailureInfo` from this module, and `RunStatusPoll` now owns the definition
# -- the poll shape is the seven volatile fields' single source of truth.
__all__ = ["FailureInfo", "RunListRow", "RunsListPage"]


class RunListRow(RunStatusPoll, RowProjection):
    """One row of the /runs list -- exactly the fields `runs_list.html` rendered
    before conversion, no more.

    Composes `RunStatusPoll`'s seven volatile fields (`status`, `badge_class`,
    `badge_label`, `failure`, `queue_label`, `queue_badge_class`, `has_open_job`)
    via multiple inheritance rather than restating them -- a flat field union,
    not a nested sub-object. A flat union is what lets a poller merge its
    `RunStatusPoll` response straight onto an existing row object
    (`{...row, ...pollResponse}` in TypeScript); a nested `poll: RunStatusPoll`
    field would force a different, asymmetric merge shape at every call site.

    `EXCLUDED` names every column a raw run row can carry that this page does not
    display. Two distinct sources feed that row shape in this codebase and both must be
    covered: the real SQL projection (`app/db/repo/demo.py::load_all_runs`, which
    selects a bounded column list) and the in-memory test double
    (`tests/conftest.py::InMemoryRepo.load_all_runs`, which spreads the FULL run record
    -- deliberately, so the info-disclosure test in `tests/test_react_page_render.py`
    has real PII/internal fields to prove are absent from the payload; a trimmed fake
    would make that assertion vacuous). A column present in either source but not
    declared as a field here must be named below, or `RowProjection.from_row` raises.
    """

    EXCLUDED: ClassVar[frozenset[str]] = frozenset(
        {
            # Carried by the real SQL projection but not displayed on the list page
            # (or already stripped by _safe_run_for_browser's denylist -- named here
            # too, defensively, so the allowlist does not depend on that inner layer
            # never changing).
            "business_id",
            "error_reason",
            "error_detail",
            "updated_at",
            "job_attempts",
            "job_max_attempts",
            # Only reachable via the in-memory test double's full-row spread -- the
            # real SQL projection never selects these, but the fake's fuller row is
            # what lets the PII-absence test actually exercise something. Every one
            # of these is a real payroll_runs column (app/db/schema.sql) that the
            # list page has never displayed.
            "source_email_id",
            "reply_epoch",
            "alias_candidates",
            "extracted_data",
            "reconciliation",
            "decision",
            "pre_clarify_extracted",
            "clarified_fields",
            "hours_changes",
            "clarification_round",
            "pay_period_start",
            "pay_period_end",
            "record_only",
            # Test-double-only bookkeeping (tests/conftest.py InMemoryRepo), not a
            # real database column at all.
            "_error_accounted",
        }
    )

    # status, badge_class, badge_label, queue_label, queue_badge_class,
    # has_open_job, failure -- inherited from RunStatusPoll, not restated
    # here.
    id: UUID
    created_at: datetime | None = None
    created_at_display: str
    business_name: str = ""
    summary_gate_reason: str | None = None
    employee_count: int = 0


class RunsListPage(BaseModel):
    """Page-level DTO for GET /runs -- the whole `__INITIAL_DATA__` payload."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    runs: list[RunListRow]
    in_flight_statuses: list[str]
