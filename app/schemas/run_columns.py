"""RUN_COL_CLASSIFICATION -- an explicit three-way exposure decision for every
column app.db.repo.runs.RUN_COLS selects.

Every column `app.db.repo.runs.RUN_COLS` selects is one serialization away from
an unauthenticated browser. `_safe_run_for_browser` (app/routes/runs.py) is a
DENYLIST: it strips a fixed, named set of raw diagnostic/job-internal fields,
but a column it does not explicitly strip passes through untouched. Seven of
the fifteen live columns -- the business identifier, the source email
identifier, the reply epoch, the alias candidates, the extracted data, the
reconciliation, and the decision -- leak through that denylist today. Nothing
in the denylist itself would stop an eighth column from joining them tomorrow.

This module is the layer that stops it: every column name in `RUN_COLS` gets a
deliberate, named exposure decision -- exposed on the list shape, exposed on
the detail shape, or internal-only -- and the drift test in
`tests/test_schema_projection.py` fails by column name the moment a column
reaches `RUN_COLS` without one.

What this mapping does NOT establish: it proves no column is unclassified, not
that every exposed column is safe to expose. A column can be deliberately,
correctly classified `detail_exposed` and still carry PII if the field it is
declared on renders raw text with no reduction -- that is a property of the
declared field's own implementation, not of this mapping. This mapping closes
one specific gap: a NEW or RENAMED column silently riding the existing
denylist through to the browser with nobody having made a decision about it.

This module lives in `app/schemas/`, one layer above the repository, rather
than beside `RUN_COLS` in `app/db/repo/runs.py`. `app/db/` is the fenced
database package this milestone does not edit; a browser-exposure decision is
a presentation-layer concern, not a schema concern, and belongs with the other
allowlist DTOs that already make that same layering choice.
"""
from __future__ import annotations

import enum


class ColumnExposure(enum.StrEnum):
    """The three exposure outcomes a `payroll_runs` column can have."""

    LIST_EXPOSED = "list_exposed"
    DETAIL_EXPOSED = "detail_exposed"
    INTERNAL_ONLY = "internal_only"


# Every key here is transcribed from the live `app.db.repo.runs.RUN_COLS`
# constant, not copied from a planning document. The drift test re-parses
# RUN_COLS independently and fails by name on any set mismatch in either
# direction, so this mapping cannot silently go stale.
RUN_COL_CLASSIFICATION: dict[str, ColumnExposure] = {
    # Declared RunListRow fields (app/schemas/runs_list.py) -- exposed on the
    # /runs list page today.
    "id": ColumnExposure.LIST_EXPOSED,
    "status": ColumnExposure.LIST_EXPOSED,
    # The seven columns that leak through _safe_run_for_browser's denylist
    # untouched today (see this module's docstring). Four of the seven are
    # never rendered anywhere -- business_id, source_email_id, and
    # reply_epoch drive server-side roster lookups and dedup bookkeeping
    # only, and alias_candidates drives pipeline resolution state only --
    # so they are classified internal-only.
    "business_id": ColumnExposure.INTERNAL_ONLY,
    "source_email_id": ColumnExposure.INTERNAL_ONLY,
    "reply_epoch": ColumnExposure.INTERNAL_ONLY,
    "alias_candidates": ColumnExposure.INTERNAL_ONLY,
    # The other three of the seven -- extracted_data, reconciliation, and
    # decision -- ARE rendered today, raw, in app/templates/run_detail.html
    # (the "Extracted data and reconciliation" section and the decision
    # banner). A future detail page conversion is the phase that turns these
    # into declared fields of its own DTO; this mapping records the
    # deliberate decision that they belong on the detail shape, not that a
    # field for them exists yet.
    "extracted_data": ColumnExposure.DETAIL_EXPOSED,
    "reconciliation": ColumnExposure.DETAIL_EXPOSED,
    "decision": ColumnExposure.DETAIL_EXPOSED,
    # hours_changes is also rendered raw in run_detail.html today (the
    # cross-round hours-change list) -- same detail-shape decision as above.
    "hours_changes": ColumnExposure.DETAIL_EXPOSED,
    # error_reason/error_detail are hostile diagnostic text: _safe_run_for_
    # browser already pops both out of the row entirely before any DTO sees
    # it, and RunListRow.EXCLUDED names them defensively too. Only a fixed,
    # bounded vocabulary derived FROM them (never the raw values) ever
    # reaches the browser, via app.routes.runs._safe_failure_presentation.
    "error_reason": ColumnExposure.INTERNAL_ONLY,
    "error_detail": ColumnExposure.INTERNAL_ONLY,
    # updated_at drives the operator-retrigger staleness check only and is
    # never rendered.
    "updated_at": ColumnExposure.INTERNAL_ONLY,
    # pay_period_start/end are read server-side to build the on-demand
    # paystub PDF (app/routes/runs.py::paystub_pdf, app/pipeline/pdf.py) --
    # an already-gated, separate download route, not a field of the run
    # list or run detail page's own JSON/HTML response shape. Neither date
    # appears as raw text in either page's markup today.
    "pay_period_start": ColumnExposure.INTERNAL_ONLY,
    "pay_period_end": ColumnExposure.INTERNAL_ONLY,
}
