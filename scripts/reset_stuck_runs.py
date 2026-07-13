"""Demo-DB hygiene helper: inspect run statuses and clear stuck or stale runs.

Modes:
  --list                 show run counts by status (default if no flag)
  --fail-stuck [MINUTES]  mark runs stuck in an in-flight status (received/extracting/
                          computed) older than MINUTES (default 10) as 'error' so they
                          stop showing as in-flight (and become retriggerable). Non-destructive.
  --purge-all            DELETE every run + its email_messages (FULL demo reset). Destructive —
                          asks for confirmation. Use before recording a clean demo.

Run with: uv run python scripts/reset_stuck_runs.py --list
"""
import sys
from typing import Any

from app.db import repo

IN_FLIGHT = ("received", "extracting", "computed")


def _counts(c: Any) -> None:
    rows = c.execute(
        "SELECT status, count(*) FROM payroll_runs GROUP BY status ORDER BY count(*) DESC"
    ).fetchall()
    for status, n in rows:
        print(f"  {n:4d}  {status}")
    total = c.execute("SELECT count(*) FROM payroll_runs").fetchone()[0]
    print(f"  ---- total: {total}")


def main() -> None:
    args = sys.argv[1:]
    mode = args[0] if args else "--list"

    with repo._conn_ctx(None) as (c, _owns):
        if mode == "--list":
            print("Run counts by status:")
            _counts(c)

        elif mode == "--fail-stuck":
            minutes = int(args[1]) if len(args) > 1 else 10
            # Never f-string SQL: `= ANY(%s::text[])` takes the status list as a single
            # bound array parameter, so the status values stay data and can never be
            # interpolated into the statement text.
            rows = c.execute(
                "UPDATE payroll_runs SET status='error', "
                "error_reason=COALESCE(error_reason,'stuck-in-flight (manual reset)') "
                "WHERE status = ANY(%s::text[]) "
                "AND updated_at < now() - (%s || ' minutes')::interval "
                "RETURNING id",
                (list(IN_FLIGHT), str(minutes)),
            ).fetchall()
            print(f"Marked {len(rows)} stuck run(s) (older than {minutes}m) as 'error'.")
            print("After:")
            _counts(c)

        elif mode == "--purge-all":
            print(
                "DESTRUCTIVE: this deletes ALL runs + email_messages. "
                "Type 'PURGE' to confirm: ",
                end="",
            )
            try:
                confirm = input().strip()
            except EOFError:
                # Non-interactive shell (e.g. piped/heredoc). Require --yes to proceed.
                confirm = "PURGE" if "--yes" in args else ""
            if confirm != "PURGE":
                print(
                    "Aborted (no confirmation). Re-run and type PURGE, "
                    "or add --yes for non-interactive."
                )
                return
            # payroll_runs and email_messages have a CIRCULAR FK
            # (payroll_runs.source_email_id -> email_messages.id, and
            #  email_messages.run_id -> payroll_runs.id). Break the run->email
            # reference FIRST, then delete email_messages, then payroll_runs.
            c.execute("UPDATE payroll_runs SET source_email_id = NULL")
            c.execute("DELETE FROM email_messages")
            c.execute("DELETE FROM payroll_runs")
            print("All runs + email_messages deleted. Demo DB is clean.")

        else:
            print(__doc__)


if __name__ == "__main__":
    main()
