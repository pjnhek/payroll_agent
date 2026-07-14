"""Confirmation delivery: send the confirmation email and per-employee paystub PDFs,
learn any client-confirmed alias, and advance the run to SENT/RECONCILED.

This is the last stage of a payroll run and the only one that puts money-bearing
documents in front of the client, so its ordering rules are load-bearing:

- **`deliver` raises freely and never swallows.** The approve() route that calls it owns
  the error boundary. A delivery failure must surface as ERROR; catching it here would
  strand the run in APPROVED with the operator believing the payroll went out.
- **The already-sent guard is purpose-aware.** Only a `purpose='confirmation'` row with
  `send_state='sent'` proves delivery. A purpose-blind lookup would see an earlier
  clarification row and skip the confirmation entirely — the client would be told nothing.
- **The alias write happens BEFORE the status advance, and is isolated.** An
  alias-learning failure logs a warning and never rolls back or strands a genuine
  delivery.
- **No transaction is held open across the provider call.** The send returns first; only
  the alias write and the status advance are wrapped.

`deliver` is called synchronously by app/main.py's approve() route.
"""
from __future__ import annotations

import contextlib
import logging
import re
import uuid
from typing import Any

from app.db import repo
from app.email import gateway
from app.models.status import RunStatus
from app.pipeline import alias_learning, send_guard
from app.pipeline.compose_email import compose_confirmation, confirmation_subject
from app.pipeline.pdf import generate_paystub_pdf

logger = logging.getLogger("payroll_agent.orchestrator")


def deliver(run_id: uuid.UUID, run: dict[str, Any]) -> None:
    """Compose + send the confirmation email + per-employee PDFs.

    Called synchronously by the approve route. Raises freely — the caller wraps this in
    its error boundary (try/except → record_run_error). It NEVER catches exceptions
    internally: a delivery failure must surface to ERROR, not silently strand the run in
    APPROVED while the operator believes the payroll was sent.

    The already-sent guard checks for an existing confirmation row via
    get_outbound_message_id(run_id, purpose='confirmation'). Scoping the check to
    purpose='confirmation' is essential: a purpose-blind lookup would see a clarification
    row sent earlier in the same run and skip the confirmation, so the client never
    receives their payroll.

    The alias write (alias_learning.write_aliases_if_safe) is called BEFORE
    set_status(SENT) and is wrapped in try/except: an alias-learning failure logs a
    warning and must never strand or fail a run whose email already went out.

    The `run` dict is enriched with business_name (loaded via load_business_name) and
    pay_period_label (formatted from pay_period_start / pay_period_end), because
    confirmation_subject() and compose_confirmation() need them for the subject line and
    load_run() deliberately stays lean (no JOIN forced on every caller).
    """
    # Step 0 — Enrich the run dict with fields the confirmation helpers need.
    # load_run() returns business_id but NOT business_name (no JOIN), and pay_period_label
    # is not a column at all. Enrich here, scoped to deliver.
    run = dict(run)  # shallow copy — do not mutate the caller's dict
    biz_name = repo.load_business_name(run["business_id"])
    run["business_name"] = biz_name if biz_name else "Payroll Run"
    start = run.get("pay_period_start")
    end = run.get("pay_period_end")
    if start and end:
        run["pay_period_label"] = f"{start} to {end}"
    elif start:
        run["pay_period_label"] = str(start)
    else:
        run["pay_period_label"] = ""

    # Step 1 — Purpose-aware already-sent guard.
    # Only a row with purpose='confirmation' AND send_state='sent' counts as proof of
    # delivery. A reserved/failed row, or a clarification row, does NOT count — treating a
    # clarification as proof would skip the confirmation and the client would never be
    # told the payroll ran.
    #
    # gateway.send_outbound already durably flips send_state to 'sent' before returning, so
    # on a retry-over-sent this guard's remaining job is to make sure the ALIAS WRITE —
    # which the happy path performs BEFORE advancing status — is not silently skipped just
    # because the send itself was already durable. The alias write is safe to attempt
    # again: it only writes when the candidate is unambiguous and new, so a second attempt
    # no-ops if the alias was already learned.
    existing = repo.get_outbound_message_id(run_id, purpose="confirmation")
    if existing is not None:
        logger.info(
            "confirmation already sent for run %s (%s) — advancing to SENT+RECONCILED "
            "without duplicate send",
            run_id,
            existing,
        )
        # This early-return path returns before Step 4 loads the roster, so it must load
        # one itself in order to attempt the same idempotent alias write the happy path
        # performs. Isolated in its own try/except because this branch is NOT nested inside
        # the roster-stashing try below (it returns before that try opens).
        existing_roster = repo.load_roster_for_business(run["business_id"])
        try:
            alias_learning.write_aliases_if_safe(run_id, run, existing_roster)
        except Exception as alias_exc:  # noqa: BLE001 — an alias-learning failure of ANY
            # type must never fail a run whose email already went out; log and continue.
            logger.warning(
                "alias write skipped for run %s: %s (run continues to SENT)",
                run_id,
                type(alias_exc).__name__,
            )
        with repo.get_connection() as conn, conn.transaction():
            repo.set_status(run_id, RunStatus.SENT, conn=conn)
            repo.set_status(run_id, RunStatus.RECONCILED, conn=conn)
        return

    # An unconfirmed reservation from an earlier, possibly-crashed send attempt means
    # the provider may already hold this confirmation. Refuse to send again and let the
    # caller's error boundary escalate rather than risk a second payroll confirmation
    # reaching the client. round=0 is correct here: a confirmation send never carries a
    # round, so send_outbound's own default (0) is what its reservation row would carry.
    #
    # This is a DIFFERENT asymmetry from Step 1's guard above, and deliberately kept:
    # a PROVEN confirmation (Step 1) is never re-sent, not even after a human retrigger
    # opens a new epoch — the run simply finalizes without emailing again. A POSSIBLE
    # confirmation (this guard) is not re-sent by the machine, but MAY be, once, by a
    # human who opens a new epoch — because the alternative is an escalated run the
    # operator could never resolve.
    send_guard.assert_no_unconfirmed_send(run_id, purpose="confirmation", round=0)

    # Step 2 — Load line items (explicit column list, no SELECT *).
    paystubs = repo.load_line_items(run_id)

    # Step 3 — Compose the confirmation email body (hard timeout on the drafting call).
    body = compose_confirmation(paystubs, run, timeout_s=3.0)

    # Step 4 — Load roster for employee full names (needed for the PDF header).
    roster = repo.load_roster_for_business(run["business_id"])
    emp_by_id = {str(e.id): e for e in roster.employees}

    # Steps 5-10 interpolate roster names (PDF headers, compose/gateway payloads), so an
    # exception raised past this point can carry employee full names inside str(exc).
    # Stash the ALREADY-LOADED in-memory roster on the exception and re-raise it unchanged
    # — the approve() error boundary reads it via getattr and passes it to
    # record_run_error, so the scrubber can redact those names out of the persisted error
    # detail. The error path itself must never LOAD a roster (a DB call on the failure path
    # is forbidden); it only forwards the object this happy path already had in scope.
    # deliver's contract is preserved: it still raises freely and never swallows.
    try:
        # Step 5 — Generate per-employee PDFs (pure, in-memory; nothing touches disk).
        pdf_attachments: list[tuple[str, bytes]] = []
        for item in paystubs:
            emp = emp_by_id.get(str(item.employee_id)) if item.employee_id else None
            emp_name = emp.full_name if emp else (item.submitted_name or "Employee")
            pdf_bytes = generate_paystub_pdf(
                item,
                emp_name,
                run.get("pay_period_start"),
                run.get("pay_period_end"),
                business_name=run.get("business_name"),
                filing_status=emp.filing_status if emp else None,
                hourly_rate=emp.hourly_rate if emp else None,
            )
            # The attachment filename MUST end in .pdf — the provider forwards the filename
            # verbatim, and a name without an extension (e.g. "Maria Chen") arrives as an
            # unrecognized binary blob the recipient's mail client won't open as a PDF.
            # Sanitize exactly like the /runs/{id}/pdf download route so both produce the
            # same name for the same employee.
            safe_name = re.sub(r"[^\w.\-]", "_", emp_name, flags=re.ASCII) or "employee"
            pdf_attachments.append((f"paystub_{safe_name}.pdf", pdf_bytes))

        # Step 6 — Load the inbound email for the reply-to address.
        inbound = repo.load_inbound_email(run_id)
        to_addr = inbound.from_addr if inbound else ""

        # Step 7 — Send, honoring the record-only flag.
        # record_only=True (runs created in-app for the demo): write the outbound row
        # WITHOUT calling the real provider, so a demo run never emails a real address.
        # record_only=False (live runs): call the gateway as normal.
        # Steps 8-10 (alias write + SENT + RECONCILED) run unconditionally for BOTH
        # branches — an in-app run must still learn and still reach a terminal status.
        record_only = repo.get_record_only_flag(run_id)
        if record_only:
            # Record-only delivery: write the confirmation outbound row, no provider call.
            synthetic_mid = f"<{uuid.uuid4()}@demo.payroll-agent.local>"
            repo.insert_email_message(
                run_id=run_id,
                direction="outbound",
                message_id=synthetic_mid,
                in_reply_to=inbound.message_id if inbound else None,
                references_header=inbound.message_id if inbound else None,
                subject=confirmation_subject(run, inbound.subject if inbound else None),
                from_addr=None,
                to_addr=to_addr,
                body_text=body,
                purpose="confirmation",
                send_state="sent",
            )
            # DO NOT return here — fall through to the alias write + status steps below.
        else:
            # The gateway writes send_state='reserved' BEFORE the provider call and flips
            # it to 'sent'/'failed' after, so a crash mid-send is diagnosable rather than
            # invisible.
            gateway.send_outbound(
                run_id=run_id,
                to_addr=to_addr,
                subject=confirmation_subject(run, inbound.subject if inbound else None),
                body=body,
                attachments=pdf_attachments,
                purpose="confirmation",
                send_state="sent",
            )

        # Steps 8-10 — the email row's send_state flip to 'sent' already committed inside
        # gateway.send_outbound before this transaction opens, so this block covers ONLY
        # what remains atomic on this side: alias learning + the status advance. No
        # transaction is held open across the provider call.
        #
        # A crash between send_outbound's return and this transaction's commit leaves
        # send_state='sent' with status='approved'. That is intentional at-least-once
        # delivery: a retry hits the purpose-aware already-sent guard above, which
        # completes the alias write and advances the status without re-emailing the client.
        with repo.get_connection() as conn, conn.transaction():
            # Step 8 — Alias write: learn any unambiguous, client-confirmed alias
            # candidate. MUST run BEFORE set_status(SENT), so a run cannot reach a terminal
            # status having skipped the learning step.
            #
            # The nested `with conn.transaction()` is a psycopg3 SAVEPOINT — psycopg3
            # automatically issues SAVEPOINT / RELEASE SAVEPOINT / ROLLBACK TO SAVEPOINT
            # instead of BEGIN/COMMIT/ROLLBACK when conn.transaction() is entered while
            # already inside an outer transaction. The savepoint is what makes the isolation
            # hold for genuine DB-LEVEL errors (constraint violations, undefined columns,
            # lock timeouts), not merely for pure-Python exceptions. Without it, a DB-level
            # failure in the alias write poisons the WHOLE outer transaction — the very next
            # statement raises InFailedSqlTransaction, so the status advance is lost and a
            # successfully-emailed payroll is left stuck at 'approved'. The alias write's
            # own repo helpers run under a no-op transaction wrapper whenever a
            # caller-supplied conn is present, so no savepoint exists at that layer: it must
            # be added HERE by the caller, wrapping the whole alias-write call once.
            try:
                with conn.transaction():
                    alias_learning.write_aliases_if_safe(run_id, run, roster, conn=conn)
            except Exception as alias_exc:  # noqa: BLE001 — an alias-learning failure of
                # ANY type must never roll back a genuine delivery; log and continue.
                logger.warning(
                    "alias write skipped for run %s: %s (run continues to SENT)",
                    run_id,
                    type(alias_exc).__name__,
                )

            # Steps 9-10 — Advance the run: SENT → RECONCILED (both sequential in this
            # synchronous call; RECONCILED is the only terminal-success status). The status
            # advance is last, so nothing that can fail runs after it.
            repo.set_status(run_id, RunStatus.SENT, conn=conn)
            repo.set_status(run_id, RunStatus.RECONCILED, conn=conn)
    except Exception as exc:
        # Attach the in-memory roster for the caller's scrub boundary, then re-raise the
        # ORIGINAL exception unchanged. The attribute assignment is best-effort and
        # suppressed: an exception type that rejects attribute assignment must never mask
        # the real delivery failure with a secondary error.
        with contextlib.suppress(Exception):
            exc.payroll_roster = roster  # type: ignore[attr-defined]  # deliberate: stash the roster on an arbitrary exception so the caller's scrubber can redact employee names; never restructure — see the comment above the try
        raise
