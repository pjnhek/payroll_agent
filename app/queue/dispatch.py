"""The kind-to-handler dispatch table.

`HANDLERS` maps each `JobKind` to a `(module, function_name)` PAIR, never to
a bound function object. `handle(job)` resolves the function by ATTRIBUTE
LOOKUP at dispatch time (`getattr(module, name)(job)`), the same
module-object import discipline `app/routes/pipeline_glue.py` documents for
every router in this codebase. A dict of bound function objects would freeze
in whatever `handle_run_pipeline` was bound to at import time — a test's
`monkeypatch.setattr(pipeline, "handle_run_pipeline", stub)` rebinds the
NAME on the `pipeline` module, not any copy of it a dict might already be
holding, so a dict-of-functions table would make that seam a silent no-op.

`HANDLERS` has exactly one entry today: `JobKind.RUN_PIPELINE`. A CI guard
(appended to `tests/test_job_kind_drift.py`) asserts `set(JobKind) ==
set(HANDLERS)` — set EQUALITY, so a `JobKind` member with no registered
handler fails the build rather than shipping a job that can be enqueued,
claimed, and marked done without ever having run.
"""
from __future__ import annotations

from types import ModuleType

from app.models.job import Job, JobKind
from app.queue.handlers import pipeline

HANDLERS: dict[JobKind, tuple[ModuleType, str]] = {
    JobKind.RUN_PIPELINE: (pipeline, "handle_run_pipeline"),
}


def handle(job: Job) -> None:
    """Dispatch `job` to its registered handler. RAISES on an unknown kind —
    a job marked done without ever having run is the worst possible outcome,
    because it looks exactly like success. There is no silent no-op branch.
    """
    entry = HANDLERS.get(job.kind)
    if entry is None:
        raise ValueError(
            f"dispatch.handle: no handler registered for job kind {job.kind!r} "
            f"(id={job.id}). Every JobKind must have a HANDLERS entry — a job "
            "of a kind with no handler must never be silently marked done."
        )
    module, name = entry
    getattr(module, name)(job)
