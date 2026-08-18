"""Public surface of app.schemas -- browser-facing allowlist DTOs.

Sibling to app/models/ (the internal judgment-stage contracts), NOT under app/db/ --
this package sits above the repo layer and decides what a repository row is allowed
to expose to the browser. Every DTO here is an ALLOWLIST built on RowProjection:
a repository row key that is neither a declared field nor a named-excluded column
raises UnclassifiedColumnError rather than silently reaching the browser.
"""
from app.schemas._projection import RowProjection, UnclassifiedColumnError
from app.schemas.run_status import RunStatusPoll
from app.schemas.runs_list import FailureInfo, RunListRow, RunsListPage

__all__ = [
    "RowProjection",
    "UnclassifiedColumnError",
    "FailureInfo",
    "RunListRow",
    "RunsListPage",
    "RunStatusPoll",
]
