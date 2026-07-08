"""CLI wrapper over schema_introspect.diff_against_live for the deploy-migrate
CI post-flight step (and manual use). Exit 0 = in_sync, 1 = drift.

    uv run python -m app.db.check_schema
"""
from __future__ import annotations

import json
import sys

from app.db.schema_introspect import diff_against_live
from app.db.supabase import get_connection


def main() -> int:
    with get_connection() as conn:
        diff = diff_against_live(conn)
    if diff.is_in_sync:
        print("schema check: in_sync")
        return 0
    print("schema check: DRIFT DETECTED")
    print(json.dumps(diff.as_missing_dict(), indent=2, sort_keys=True))
    return 1


if __name__ == "__main__":
    sys.exit(main())
