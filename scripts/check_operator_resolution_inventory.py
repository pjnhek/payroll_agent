"""Read-only, PII-safe inventory for legacy operator resolution generations."""
from __future__ import annotations

import sys
from contextlib import nullcontext
from typing import Any

import psycopg

from app.config import get_settings

_INVENTORY_SQL = """
WITH unresolved AS (
    SELECT pr.id AS run_id, COUNT(r.id)::bigint AS generation_count
      FROM payroll_runs pr
      LEFT JOIN operator_resume_resolutions r ON r.run_id = pr.id
     WHERE pr.status = 'needs_operator'
     GROUP BY pr.id
)
SELECT COUNT(*)::bigint AS unresolved_run_count,
       COUNT(*) FILTER (WHERE generation_count = 1)::bigint
           AS single_generation_run_count,
       COUNT(*) FILTER (WHERE generation_count > 1)::bigint
           AS ambiguous_run_count
  FROM unresolved
"""

_FIELDS = (
    "unresolved_run_count",
    "single_generation_run_count",
    "ambiguous_run_count",
)


def _run(conn: Any) -> int:
    row = conn.execute(_INVENTORY_SQL).fetchone()
    if row is None or len(row) != len(_FIELDS):
        return 2
    counts = tuple(int(value) for value in row)
    for field, value in zip(_FIELDS, counts, strict=True):
        print(f"{field}={value}")
    return 1 if counts[2] else 0


def main(conn: Any | None = None) -> int:
    """Print only three aggregate counts; return nonzero on ambiguity/failure."""
    try:
        connection_context = (
            psycopg.connect(get_settings().database_url, prepare_threshold=None)
            if conn is None
            else nullcontext(conn)
        )
        with connection_context as active_conn:
            return _run(active_conn)
    except Exception:
        # Deployment tooling must never echo driver diagnostics: DB errors can
        # include SQL fragments, identifiers, or provider-returned values.
        return 2


if __name__ == "__main__":
    sys.exit(main())
