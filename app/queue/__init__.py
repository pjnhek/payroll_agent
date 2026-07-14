"""The execution layer between a durable `jobs` row and real work getting done.

This package owns three things, each in its own module so a caller only ever
imports the one it needs: the in-process wake signal (`wake.py`), the
kind-to-handler dispatch table (`dispatch.py`), and the single drain step
(`drain.py`) that claims one job, dispatches it, and completes or fails it.
The per-kind handlers live under `handlers/`.

This `__init__.py` deliberately re-exports nothing. Every caller imports the
specific submodule it needs (`from app.queue import wake`, `from app.queue
import dispatch`) so every cross-module reference stays greppable and a
`monkeypatch.setattr(module, name, ...)` test seam always targets the module
that actually owns the name.
"""
from __future__ import annotations
