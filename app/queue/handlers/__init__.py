"""Per-`JobKind` handlers — one module per kind, each exposing exactly one
public `handle_<kind>(job: Job) -> None` function.

`app/queue/dispatch.py` imports each handler module as a MODULE OBJECT, never
a bare function name, so a test's `monkeypatch.setattr(pipeline,
"handle_run_pipeline", stub)` seam stays live against the same attribute
`dispatch.handle` reads at call time.

This `__init__.py` deliberately re-exports nothing, for the same reason
`app/queue/__init__.py` does not: every caller imports the specific handler
module it needs, keeping the module-object import discipline visible at
every call site.
"""
from __future__ import annotations
