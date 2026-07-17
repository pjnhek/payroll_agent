"""Create durable confirmation delivery intents and complete proven sent recovery."""
from __future__ import annotations

import contextlib
import logging
import re
import uuid
from typing import Any

import psycopg

from app.config import get_settings
from app.db import repo
from app.models.job import JobKind
from app.models.status import RunStatus
from app.pipeline import alias_learning, send_guard
from app.pipeline.compose_email import compose_confirmation, confirmation_subject
from app.pipeline.pdf import generate_paystub_pdf

logger = logging.getLogger("payroll_agent.orchestrator")


def _enriched_confirmation_run(
    run: dict[str, Any], *, conn: psycopg.Connection | None
) -> dict[str, Any]:
    """Return only the first-time composition fields needed by the email helpers."""
    enriched = dict(run)
    business_name = repo.load_business_name(run["business_id"], conn=conn)
    enriched["business_name"] = business_name or "Payroll Run"
    start = run.get("pay_period_start")
    end = run.get("pay_period_end")
    if start and end:
        enriched["pay_period_label"] = f"{start} to {end}"
    elif start:
        enriched["pay_period_label"] = str(start)
    else:
        enriched["pay_period_label"] = ""
    return enriched


def _complete_sent_confirmation(
    run_id: uuid.UUID,
    run: dict[str, Any],
    *,
    conn: psycopg.Connection | None,
) -> None:
    """Finish local post-send work without making a provider request."""
    roster = repo.load_roster_for_business(run["business_id"], conn=conn)
    try:
        if conn is not None:
            with conn.transaction():
                alias_learning.write_aliases_if_safe(run_id, run, roster, conn=conn)
        else:
            alias_learning.write_aliases_if_safe(run_id, run, roster)
    except Exception as alias_exc:  # noqa: BLE001
        logger.warning("alias write skipped for run %s: %s", run_id, type(alias_exc).__name__)
    repo.set_status(run_id, RunStatus.SENT, conn=conn)
    repo.set_status(run_id, RunStatus.RECONCILED, conn=conn)


def _enqueue_confirmation(
    run_id: uuid.UUID,
    email_id: uuid.UUID,
    *,
    conn: psycopg.Connection | None,
) -> None:
    """Insert the one identifier-only job for an immutable confirmation slot."""
    repo.enqueue_job(
        kind=JobKind.SEND_OUTBOUND,
        dedup_key=repo.send_outbound_dedup_key(email_id),
        run_id=run_id,
        email_id=email_id,
        conn=conn,
    )


def deliver(
    run_id: uuid.UUID,
    run: dict[str, Any],
    *,
    conn: psycopg.Connection | None = None,
) -> bool:
    """Reserve and queue one confirmation, returning whether a worker should wake.

    The caller owns the transaction that changes approval state, freezes the snapshot,
    and inserts its identifier-only job.  Provider work is intentionally absent from
    this function; the queue handler reads the stored snapshot later.
    """
    sent_message_id = repo.get_outbound_message_id(
        run_id, purpose="confirmation", conn=conn
    )
    if sent_message_id is not None:
        logger.info("confirmation already sent for run %s", run_id)
        _complete_sent_confirmation(run_id, run, conn=conn)
        return False

    policy = send_guard.outbound_replay_policy(
        run_id, purpose="confirmation", round=0, conn=conn
    )
    if policy.has_existing_snapshot:
        assert policy.email_id is not None
        _enqueue_confirmation(run_id, policy.email_id, conn=conn)
        return True

    composed_run = _enriched_confirmation_run(run, conn=conn)
    paystubs = repo.load_line_items(run_id, conn=conn)
    body = compose_confirmation(paystubs, composed_run, timeout_s=3.0)
    roster = repo.load_roster_for_business(run["business_id"], conn=conn)
    employees = {str(employee.id): employee for employee in roster.employees}

    try:
        attachments: list[tuple[str, bytes]] = []
        for item in paystubs:
            employee = employees.get(str(item.employee_id)) if item.employee_id else None
            employee_name = employee.full_name if employee else (item.submitted_name or "Employee")
            pdf_bytes = generate_paystub_pdf(
                item,
                employee_name,
                run.get("pay_period_start"),
                run.get("pay_period_end"),
                business_name=composed_run.get("business_name"),
                filing_status=employee.filing_status if employee else None,
                hourly_rate=employee.hourly_rate if employee else None,
            )
            safe_name = re.sub(r"[^\w.\-]", "_", employee_name, flags=re.ASCII) or "employee"
            attachments.append((f"paystub_{safe_name}.pdf", pdf_bytes))

        inbound = repo.load_inbound_email(run_id, conn=conn)
        in_reply_to = inbound.message_id if inbound else None
        prior_references = repo.get_outbound_references_chain(run_id, conn=conn)
        references_header = (
            f"{prior_references} {in_reply_to}"
            if prior_references and in_reply_to
            else in_reply_to or prior_references
        )
        settings = get_settings()
        snapshot = repo.reserve_outbound_snapshot(
            run_id=run_id,
            purpose="confirmation",
            round=0,
            message_id=f"<{uuid.uuid4()}@payroll-agent.local>",
            from_addr=settings.resend_from_addr,
            to_addr=inbound.from_addr if inbound else "",
            reply_to=settings.resend_reply_to or None,
            in_reply_to=in_reply_to,
            references_header=references_header,
            subject=confirmation_subject(
                composed_run, inbound.subject if inbound else None
            ),
            body_text=body,
            attachments=attachments,
            conn=conn,
        )
        email_id = snapshot.get("email_id")
        if not isinstance(email_id, uuid.UUID):
            raise RuntimeError("reserved confirmation snapshot lacks its email id")
        _enqueue_confirmation(run_id, email_id, conn=conn)
        return True
    except Exception as exc:
        with contextlib.suppress(Exception):
            exc.payroll_roster = roster  # type: ignore[attr-defined]
        raise
