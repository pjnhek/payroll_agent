"""RunStatusPoll -- the declared response shape of GET /runs/{run_id}/status.

Field order matches the dict literal the route returned before this module
existed (`status`, `badge_class`, `badge_label`, `failure`, `queue_label`,
`queue_badge_class`, `has_open_job`) -- Pydantic's `model_dump_json()` walks
fields in declaration order, so preserving that order keeps the wire body
byte-identical to what the route emitted when it built the response by hand.

Not a `RowProjection` subclass: `RowProjection.from_row` allowlists a raw
repository row, but this shape is never handed one -- it is built directly
from computed presentation values (`badge_class_filter`/`badge_label_filter`,
and `_safe_run_for_browser`'s queue/failure projection), so the allowlist
machinery has nothing to project over here. A plain frozen, extra-forbidding
model carries the same fail-closed intent (an unexpected field raises rather
than silently passing through) without a `from_row` call this shape never
makes.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FailureInfo(BaseModel):
    """Browser-safe terminal-diagnostics projection.

    Field-for-field mirror of `app.routes.runs.FailurePresentation` (a
    `TypedDict`) -- kept as a distinct Pydantic model so it nests cleanly
    inside `RunStatusPoll`/`RunListRow` and round-trips through
    `model_dump_json()`/`openapi-typescript` codegen.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    secondary_label: str | None
    stage: str | None
    reason: str | None
    attempts: str | None


class RunStatusPoll(BaseModel):
    """The seven volatile per-run fields GET /runs/{run_id}/status returns.

    This is a declared sub-shape of `RunListRow` -- `RunListRow` composes
    these same seven fields (see `app/schemas/runs_list.py`) rather than
    restating them, so a poller reading this response can replace the
    volatile half of a list row wholesale and the type system enforces the
    merge. Any later run-detail page can reuse this shape unchanged for its
    own status poll.

    Presentation vocabulary is server-owned: `badge_class`/`badge_label` come
    from `app.routes.templating`'s filter functions and `failure` is
    populated only by `app.routes.runs._safe_failure_presentation` -- never
    re-derived in TypeScript, and never from any other diagnostic source.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    badge_class: str
    badge_label: str
    failure: FailureInfo
    queue_label: str | None
    queue_badge_class: str
    has_open_job: bool
