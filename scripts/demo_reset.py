"""Demo-DB reset helper (D-07) — Phase 6.

Purpose
-------
Between recording takes, Beat 3 persists a learned alias into the database.
A second take of Beat 2 (unknown-shorthand) will therefore resolve instead of
clarify unless the alias is cleared first. This script resets the demo state
so every take starts from the same clean baseline.

Identity model (06-08 additive)
---------------------------------
Under the 06-08 additive model, demo identity is stored in the
``demo_sender_bindings`` table (operator_email → business_id).
The seed .example contacts in ``businesses.contact_email`` are PERMANENTLY STABLE —
they are never mutated by any demo flow (HIGH-2 invariant). This script:

  - Deletes run-level state (paystub_line_items, email_messages, payroll_runs)
    in FK-safe order.
  - Calls ``seed()`` to reset ``known_aliases`` (and other employee fields) via
    ON CONFLICT DO UPDATE — safe, non-destructive to employee identity.
  - Re-UPSERTs the ``demo_sender_bindings`` row (Step 6 re-arm) so the operator
    email routes to the configured demo business. This is idempotent: the binding
    row is NOT cleared by the delete steps above.
  - Never mutates ``businesses.contact_email`` — the businesses table is only ever
    written by ``seed()`` which writes back the stable .example contacts (HIGH-2).

Modes
-----
  (no args)           Print usage and exit 0.  Nothing destructive.
  --confirm           Full demo reset: FK-safe deletes → seed() → re-arm binding.
                      Requires the explicit flag — no interactive prompt, no default.
  --reset-aliases     Reset known_aliases only (non-destructive): seed() + re-arm.
                      No --confirm required.

Usage (uv)
----------
  # Full reset before recording
  uv run python scripts/demo_reset.py --confirm

  # Alias-only reset (keeps run history)
  uv run python scripts/demo_reset.py --reset-aliases
"""
from __future__ import annotations

import os
import sys
import uuid

# ---------------------------------------------------------------------------
# Seed business IDs — stable literals matching app/db/seed.py _BUSINESSES (D-11)
# ---------------------------------------------------------------------------

_SEED_BUSINESS_IDS: dict[str, uuid.UUID] = {
    "Coastal Cleaning Co.": uuid.UUID("b0000001-0000-0000-0000-000000000001"),
    "Metro Deli Group": uuid.UUID("b0000002-0000-0000-0000-000000000002"),
    "Summit Tech Solutions": uuid.UUID("b0000003-0000-0000-0000-000000000003"),
}


# ---------------------------------------------------------------------------
# Re-arm helper — public so tests can call it directly with a FakeConnection
# ---------------------------------------------------------------------------


def _rearm_demo_identity(conn) -> None:
    """Re-UPSERT the demo_sender_bindings row for the env-configured identity.

    Uses DEMO_CONTACT_EMAIL (operator_email) and DEMO_BUSINESS_NAME to resolve
    the business_id from the _SEED_BUSINESS_IDS constant. If either env var is
    missing or the business name is unknown, prints a warning and skips the
    re-arm so the operator knows to bind manually.

    The businesses table is never mutated by this function — the only path that
    writes to businesses is seed() which writes back the stable .example contacts.
    """
    operator_email = os.environ.get("DEMO_CONTACT_EMAIL", "").strip()
    business_name = os.environ.get("DEMO_BUSINESS_NAME", "").strip()
    business_id = _SEED_BUSINESS_IDS.get(business_name)

    if not operator_email or business_id is None:
        print(
            "WARNING: DEMO_CONTACT_EMAIL / DEMO_BUSINESS_NAME not set or invalid — "
            "demo identity not re-armed; run POST /demo/bind manually"
        )
        return

    # Parameterized SQL only — never f-string SQL (project discipline).
    conn.execute(
        """
        INSERT INTO demo_sender_bindings (operator_email, business_id, bound_at)
        VALUES (%s, %s, now())
        ON CONFLICT (operator_email) DO UPDATE
          SET business_id = EXCLUDED.business_id,
              bound_at    = now()
        """,
        (operator_email, str(business_id)),
    )
    print(
        f"Re-armed demo identity: {operator_email} → {business_name} ({business_id})"
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    args = sys.argv[1:]

    if "--confirm" in args:
        _run_full_reset()
    elif "--reset-aliases" in args:
        _run_alias_reset()
    else:
        print(__doc__)
        sys.exit(0)


def _run_full_reset() -> None:
    """Full demo reset: FK-safe ordered deletes → seed() → re-arm binding.

    FK-safe deletion order (derived from schema.sql):
      Step 1 — break circular FK: UPDATE payroll_runs SET source_email_id = NULL
      Step 2 — delete paystub_line_items (FK to payroll_runs)
      Step 3 — delete email_messages (FK to payroll_runs)
      Step 4 — delete payroll_runs
      Step 5 — seed() to reset known_aliases via ON CONFLICT DO UPDATE
      Step 6 — re-UPSERT demo_sender_bindings (re-arm demo identity)

    Note: demo_sender_bindings is NOT in the deletion sequence — it has no FK
    dependency on payroll_runs, email_messages, or paystub_line_items, and it is
    NOT touched by seed(). The re-arm in Step 6 is therefore a safety re-arm
    (idempotent) that ensures the binding row exists regardless.
    """
    from app.db import repo
    from app.db.seed import seed

    with repo._conn_ctx(None) as (conn, _owns):
        # Step 1: break circular FK (payroll_runs.source_email_id → email_messages)
        conn.execute("UPDATE payroll_runs SET source_email_id = NULL")
        print("Cleared payroll_runs.source_email_id (circular FK broken).")

        # Step 2: delete paystub_line_items (FK to payroll_runs via ON DELETE CASCADE,
        # but explicit delete is safer and more auditable than relying on cascade).
        conn.execute("DELETE FROM paystub_line_items")
        print("Deleted paystub_line_items.")

        # Step 3: delete email_messages (FK to payroll_runs)
        conn.execute("DELETE FROM email_messages")
        print("Deleted email_messages.")

        # Step 4: delete payroll_runs
        conn.execute("DELETE FROM payroll_runs")
        print("Deleted payroll_runs.")

    # Step 5: seed() to reset known_aliases — must run outside the delete transaction
    # so its own internal transaction can commit cleanly.
    # seed() uses ON CONFLICT DO UPDATE — safe to run on existing data.
    # seed() touches businesses and employees only (D-11 containment); it never
    # touches payroll_runs, email_messages, or demo_sender_bindings.
    seed()
    print("Seed restored (known_aliases reset, seed .example contacts verified).")

    # Step 6: re-arm demo identity via demo_sender_bindings UPSERT.
    # Must run after seed() so the businesses row is guaranteed to exist.
    from app.db import repo as _repo
    with _repo._conn_ctx(None) as (conn, _owns):
        _rearm_demo_identity(conn)

    print(
        "\nDemo reset complete. Replay the unknown_shorthand_metro fixture to "
        "trigger clarification (Beat 2)."
    )


def _run_alias_reset() -> None:
    """Alias-only reset: seed() to reset known_aliases + re-arm binding.

    Non-destructive (no run/email purge). Does not require --confirm.
    """
    from app.db.seed import seed

    seed()
    print("Seed restored (known_aliases reset, seed .example contacts verified).")

    from app.db import repo as _repo
    with _repo._conn_ctx(None) as (conn, _owns):
        _rearm_demo_identity(conn)

    print("Alias reset complete.")


if __name__ == "__main__":
    try:
        main()
    finally:
        try:
            from app.db.supabase import close_pool
            close_pool()
        except Exception:
            pass
