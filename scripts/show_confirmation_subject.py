"""Phase 5 human-UAT helper: show the most recent outbound CONFIRMATION email's
subject (and body preview) straight from the email_messages table.

Phase 5 has no real email provider yet (that's Phase 6) — gateway.send_outbound
is a stub that records the sent email as an email_messages row. So the subject you
want to eyeball lives in the DB, not an inbox. Run after approving a run.

Usage:
  uv run python scripts/show_confirmation_subject.py
"""

from app.db import repo


def main() -> None:
    with repo._conn_ctx(None) as (c, _owns):
        rows = c.execute(
            """
            SELECT em.created_at, em.run_id, em.subject, em.to_addr, em.purpose,
                   em.send_state, left(em.body_text, 200) AS body_preview
            FROM email_messages em
            WHERE em.direction = 'outbound' AND em.purpose = 'confirmation'
            ORDER BY em.created_at DESC
            LIMIT 5
            """
        ).fetchall()

    if not rows:
        print("No outbound CONFIRMATION emails found yet.")
        print("Approve a run first (dashboard 'Approve & Send'), then re-run this.")
        return

    print(f"Most recent {len(rows)} confirmation email(s):\n")
    for _created_at, run_id, subject, to_addr, _purpose, send_state, body in rows:
        print(f"  run_id     : {run_id}")
        print(f"  to         : {to_addr}")
        print(f"  send_state : {send_state}")
        print(f"  SUBJECT    : {subject}")
        print(f"  body[:200] : {body!r}")
        print("  " + "-" * 60)

    print("\nExpected subject shape (CR-03 fix):")
    print('  "Payroll Confirmation — <real business name> — <start> to <end>"')
    print('  NOT the blank fallback "Payroll Confirmation — Payroll Run — "')


if __name__ == "__main__":
    main()
