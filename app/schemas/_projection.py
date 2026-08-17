"""RowProjection -- the allowlist DTO base every browser-facing schema builds on.

`app/routes/runs.py::_safe_run_for_browser`'s DENYLIST (raw diagnostics, job-internal
fields) stays in place as an inner layer -- this module adds an ALLOWLIST above it, one
layer closer to the browser. A repository row key that is neither a declared Pydantic
field nor a column named in `EXCLUDED` raises `UnclassifiedColumnError` rather than
silently reaching the browser. This is the same fail-closed convention this repo already
applies to the pump token and the bootstrap fence: refuse rather than degrade.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar, Self

from pydantic import BaseModel, ConfigDict


class UnclassifiedColumnError(RuntimeError):
    """A repository row carried a key that is neither exposed nor consciously
    excluded -- a schema drift the allowlist refuses to pass through silently."""


class RowProjection(BaseModel):
    """An allowlist projection over a raw repository row.

    Subclasses declare the fields that ARE exposed to the browser as ordinary Pydantic
    fields, and name every OTHER column the row may carry in the class-level `EXCLUDED`
    frozenset. `from_row` raises `UnclassifiedColumnError` for any row key that is in
    neither set, so a new or renamed database column can never silently reach the
    browser without a reviewed schema edit -- the allowlist equivalent of
    `load_all_runs`'s explicit-column-list discipline, one layer up.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Overridden per subclass. Empty by default: a subclass that declares no
    # exclusions must expose (or actually receive) only its own declared fields.
    EXCLUDED: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> Self:
        """Validate `row` against this model's allowlist.

        Raises `UnclassifiedColumnError` naming every row key that is neither a
        declared field nor a member of `EXCLUDED`. Only declared-field keys are
        handed to `model_validate` -- an excluded key is dropped, not leaked
        through as an ignored extra.
        """
        unknown = set(row) - set(cls.model_fields) - cls.EXCLUDED
        if unknown:
            raise UnclassifiedColumnError(
                f"{cls.__name__}: unclassified row column(s) {sorted(unknown)} -- "
                "declare the field on the model or name it in EXCLUDED"
            )
        return cls.model_validate({k: v for k, v in row.items() if k in cls.model_fields})
