"""Confirmation delivery (STRUCT-03, D-09): compose + send the confirmation
email and per-employee PDFs, and learn any confirmed alias candidates before
advancing the run to SENT/RECONCILED.

Carved out of orchestrator.py (Phase 13 Plan 02) — this is the single home for
`deliver`, called synchronously by app/main.py's approve() route.
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
from app.pipeline import alias_learning
from app.pipeline.compose_email import compose_confirmation, confirmation_subject
from app.pipeline.pdf import generate_paystub_pdf

logger = logging.getLogger("payroll_agent.orchestrator")


def deliver(run_id: uuid.UUID, run: dict[str, Any]) -> None:
    """Compose + send the confirmation email + per-employee PDFs.

    Called synchronously by the approve route. Raises freely — the caller (approve
    handler) wraps this in the D-13b error boundary (try/except → record_run_error).
    NEVER catches exceptions internally: a delivery failure must surface to ERROR,
    not silently strand the run in APPROVED.

    CLAR-04 purpose-aware idempotency guard (finding #1): checks for an existing
    confirmation row via get_outbound_message_id(run_id, purpose='confirmation').
    A purpose-blind lookup would incorrectly skip the confirmation if a clarification
    had been sent earlier — purpose='confirmation' scopes the check correctly.

    D-01/D-02 alias write: alias_learning.write_aliases_if_safe is called BEFORE
    set_status(SENT) (PATTERNS.md line 611 ordering), wrapped in try/except (D-13b
    defensive isolation — alias write failure logs a warning and never strands or
    fails a sent run).

    CR-03 fix: run is enriched with business_name (loaded from businesses via
    load_business_name) and pay_period_label (formatted from pay_period_start /
    pay_period_end) so confirmation_subject() and compose_confirmation() produce the
    correct subject line. load_run() stays lean (no JOIN for every caller).
    """
    # Step 0 — Enrich run dict with fields needed by confirmation helpers (CR-03).
    # load_run() returns business_id but NOT business_name (no JOIN) and NOT
    # pay_period_label (non-existent column). Enrich here, scoped to deliver.
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

    # Step 1 — Purpose-aware already-sent guard (finding #1, CLAR-04):
    # Only a row with purpose='confirmation' AND send_state='sent' counts as proof-of-
    # delivery. A reserved/failed row or a clarification row does NOT count.
    #
    # gateway.send_outbound already durably flips send_state to 'sent' before returning
    # (D-13c) — this guard's job on a retry-over-sent is to ensure alias learning,
    # which the happy path performs BEFORE advancing status, is not silently skipped
    # just because the send itself was already durable (Codex HIGH-2 fix); the alias
    # write is idempotent-safe to attempt again (write-only-if-unambiguous-and-new,
    # per D-01/D-02) — it will no-op on a second attempt if the alias was already
    # learned.
    existing = repo.get_outbound_message_id(run_id, purpose="confirmation")
    if existing is not None:
        logger.info(
            "confirmation already sent for run %s (%s) — advancing to SENT+RECONCILED "
            "without duplicate send (finding #1, CLAR-04)",
            run_id,
            existing,
        )
        # D-9-08/Codex HIGH-2: the retry-over-sent path needs a roster (this
        # early-return path returns before Step 4's roster load below) to attempt
        # the same idempotent alias write the happy path performs — isolated in its
        # own try/except (mirroring D-13b) since this branch is NOT nested inside
        # the WR-04 try (it returns before that try opens).
        existing_roster = repo.load_roster_for_business(run["business_id"])
        try:
            alias_learning.write_aliases_if_safe(run_id, run, existing_roster)
        except Exception as alias_exc:  # noqa: BLE001 — D-13b defensive isolation
            logger.warning(
                "alias write skipped for run %s: %s (run continues to SENT)",
                run_id,
                type(alias_exc).__name__,
            )
        with repo.get_connection() as conn, conn.transaction():
            repo.set_status(run_id, RunStatus.SENT, conn=conn)
            repo.set_status(run_id, RunStatus.RECONCILED, conn=conn)
        return

    # Step 2 — Load line items (explicit columns, LOW finding fix).
    paystubs = repo.load_line_items(run_id)

    # Step 3 — Compose the confirmation email body (D-10b hard timeout passed).
    body = compose_confirmation(paystubs, run, timeout_s=3.0)

    # Step 4 — Load roster for employee full names (needed for PDF header).
    roster = repo.load_roster_for_business(run["business_id"])
    emp_by_id = {str(e.id): e for e in roster.employees}

    # WR-04 (phase-8 review): steps 5-10 interpolate roster names (PDF headers,
    # compose/gateway payloads), so an exception raised past this point can carry
    # employee full names in str(exc). Stash the ALREADY-LOADED in-memory roster
    # on the exception and re-raise unchanged — the approve() error boundary reads
    # it via getattr and passes it to record_run_error so _scrub can redact the
    # names. D-8-01b is preserved: the error path never LOADS a roster (forbidden);
    # it only forwards the object this happy path already had in scope. deliver's
    # contract is also preserved: it still raises freely and never swallows.
    try:
        # Step 5 — Generate per-employee PDFs (pure, in-memory — HITL-03).
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
            # The attachment filename MUST end in .pdf — Resend forwards the filename
            # verbatim, and a name without an extension (e.g. "Maria Chen") arrives as an
            # unrecognized binary blob the recipient's mail client won't open as a PDF.
            # Sanitize like the /runs/{id}/pdf download route so both produce the same name.
            safe_name = re.sub(r"[^\w.\-]", "_", emp_name, flags=re.ASCII) or "employee"
            pdf_attachments.append((f"paystub_{safe_name}.pdf", pdf_bytes))

        # Step 6 — Load the inbound email for the reply-to address.
        inbound = repo.load_inbound_email(run_id)
        to_addr = inbound.from_addr if inbound else ""

        # Step 7 — Send. HIGH-1 record-only branch (06-08): check record_only flag.
        # record_only=True (compose-created runs): write outbound row WITHOUT calling Resend.
        # record_only=False (live Path-2 runs): keep calling gateway.send_outbound unchanged.
        # Steps 8-10 (alias write + SENT + RECONCILED) run unconditionally for BOTH branches.
        record_only = repo.get_record_only_flag(run_id)
        if record_only:
            # Path-1 record-only delivery: write the confirmation outbound row WITHOUT Resend.
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
            # DO NOT return here — fall through to alias write + status steps below.
        else:
            # Phase 6 live-provider swap writes send_state='reserved' BEFORE the provider call
            # and flips to 'sent'/'failed' after — no code change needed here; the column exists.
            gateway.send_outbound(
                run_id=run_id,
                to_addr=to_addr,
                subject=confirmation_subject(run, inbound.subject if inbound else None),
                body=body,
                attachments=pdf_attachments,
                purpose="confirmation",
                send_state="sent",
            )

        # Steps 8-10 — D-9-07/D-9-08: the email row's send_state flip to 'sent'
        # already committed inside gateway.send_outbound (D-13c) before this
        # transaction opens — this block covers ONLY what remains atomic on this
        # side: alias learning + status advance. A crash between send_outbound's
        # return and this transaction's commit leaves send_state='sent' +
        # status='approved'; a retry hits the hardened already-sent guard above,
        # which completes the alias write and advances status — this is D-9-08's
        # documented at-least-once semantics, now closing the alias-skip gap
        # Codex HIGH-2 found.
        with repo.get_connection() as conn, conn.transaction():
            # Step 8 — Alias write (D-01, D-02): learn any unambiguous alias
            # candidates. MUST be called BEFORE set_status(SENT) (PATTERNS.md
            # line 611 ordering, D-13b). Wrapped in try/except NESTED STRICTLY
            # INSIDE this transaction block (Pitfall 2) so an alias-learning
            # failure NEVER rolls back a genuine delivery — it only skips the
            # alias write itself (D-13b defensive isolation, D-15).
            #
            # D-9-06 gap closure (WR-01): the nested `with conn.transaction()`
            # below is a psycopg3 SAVEPOINT (psycopg3 automatically issues
            # SAVEPOINT/RELEASE SAVEPOINT/ROLLBACK TO SAVEPOINT instead of
            # BEGIN/COMMIT/ROLLBACK when conn.transaction() is entered while
            # already inside an outer transaction). This is what makes the
            # isolation hold for genuine DB-level errors (constraint violations,
            # undefined columns, lock timeouts), not just pure-Python exceptions
            # — without it, a DB-level failure here poisons the WHOLE outer
            # transaction via InFailedSqlTransaction on the very next statement
            # (09-REVIEW.md WR-01): the alias write's own repo helpers run under
            # _nulltx() (a bare no-op) whenever a caller-supplied conn is
            # present, so no savepoint exists at that layer — it must be added
            # by the caller (here), wrapping the whole alias-write call once.
            try:
                with conn.transaction():
                    alias_learning.write_aliases_if_safe(run_id, run, roster, conn=conn)
            except Exception as alias_exc:  # noqa: BLE001 — D-13b defensive isolation
                logger.warning(
                    "alias write skipped for run %s: %s (run continues to SENT)",
                    run_id,
                    type(alias_exc).__name__,
                )

            # Steps 9-10 — Advance the run: SENT → RECONCILED (both sequential
            # in this synchronous call; RECONCILED is the only terminal-success
            # status). Status-advance last (D-9-02).
            repo.set_status(run_id, RunStatus.SENT, conn=conn)
            repo.set_status(run_id, RunStatus.RECONCILED, conn=conn)
    except Exception as exc:
        # WR-04: attach the in-memory roster for the caller's scrub boundary, then
        # re-raise the ORIGINAL exception unchanged. Attribute assignment is
        # best-effort (suppress) — an exception type rejecting attributes must
        # never mask the real delivery failure.
        with contextlib.suppress(Exception):
            exc.payroll_roster = roster  # type: ignore[attr-defined]  # WR-04: best-effort debug attribute on an arbitrary exception, suppressed if assignment fails; never restructure — see WR-04 comment above
        raise
