"""The DB repo layer — the FULL accessor surface every Phase 2 wave imports.

This module is the single place that mutates run state and persists what the
pipeline decides. It commits the COMPLETE helper set named in the plan (review
FIX 9) so Plans 02/03/04 never discover a missing helper mid-wave:

  Ingest / run lifecycle
    insert_inbound_email   — ON CONFLICT (message_id) DO NOTHING dedupe; persists
                             the ALREADY-CLEANED body it is given (FIX C)
    find_business_by_sender — match from_addr to businesses.contact_email; unknown
                             sender → None so the webhook stops (INGEST-03)
    create_run             — open a payroll_runs row (status='received')
    load_run               — explicit-column dict_row read of one run
    load_source_email      — the original CLEANED inbound body, NOT re-cleaned (FIX C)

  Status / persistence
    set_status             — the ONE AND ONLY writer of payroll_runs.status
    record_run_error       — the ONE documented exception: writes error_reason AND
                             routes its ERROR transition THROUGH set_status (FIX B,
                             so there is still exactly one status-write path)
    persist_extracted      — Extracted JSONB only (no status)
    persist_decision       — Decision JSONB only; takes NO final_status (FIX B)
    persist_reconciliation — list[NameMatchResult] JSONB only (D-A3-05)
    replace_line_items     — DELETE-by-run then insert (idempotency invariant)

  Email / threading
    insert_email_message   — generic append to email_messages (audit log)
    get_outbound_message_id — read the clarification Message-ID back from the
                             linked outbound row (the FIX 3 anchor)
    find_awaiting_reply_for_header — header-chain match restricted to awaiting_reply
    find_any_run_for_header — SAME header match across ANY status (late-reply
                             observability, FIX 10)

  Roster
    load_roster_for_business — explicit EMPLOYEE_COLS + dict_row (no SELECT *)

Discipline (PATTERNS.md / RESEARCH Security Domain):
- Pooled get_connection() + conn.transaction(); %s / named placeholders ONLY.
  NEVER f-string SQL. The header-chain `references` LIKE is a named placeholder.
- JSONB writes use json.dumps(obj.model_dump(mode="json")) so Decimal → JSON
  string round-trips losslessly at the jsonb boundary (D-06).
- Read-backs that rebuild a contract use an explicit column list + dict_row;
  every contract is extra="forbid", so SELECT * would crash on created_at.

Every public helper accepts an optional `conn` so a caller inside an existing
transaction (e.g. the webhook) can pass its connection, and tests can inject a
FakeConnection to assert the SQL offline. When `conn` is None a pooled connection
is opened in its own transaction.
"""
from __future__ import annotations

import contextlib
import json
import logging
import uuid
from typing import Any

import psycopg.rows

from app.db.supabase import get_connection
from app.models.contracts import Decision, Extracted, PaystubLineItem
from app.models.roster import Employee, NameMatchResult, Roster
from app.models.status import RunStatus

logger = logging.getLogger("payroll_agent.repo")

# Explicit column list for rebuilding Employee (no SELECT * — extra="forbid").
EMPLOYEE_COLS = (
    "id, business_id, full_name, known_aliases, pay_type, hourly_rate,"
    " annual_salary, retirement_contribution_pct, filing_status,"
    " step_2_checkbox, step_3_dependents, step_4a_other_income,"
    " step_4b_deductions, ytd_ss_wages, pay_periods_per_year"
)

# Explicit column list for reading a run (only what callers need; no SELECT *).
RUN_COLS = (
    "id, business_id, source_email_id, status, extracted_data, decision,"
    " reconciliation, error_reason, pay_period_start, pay_period_end"
)

# Terminal run statuses (WR-04): once a run reaches one of these, an error must NOT
# overwrite it. APPROVED/SENT/RECONCILED/REJECTED are finalized human/operator
# outcomes (clobbering them destroys the approval audit trail); ERROR is already
# terminal. A late/duplicate-reply resume (cf. CR-02) that hits an exception must not
# be able to flip a human-approved run to ERROR.
_TERMINAL_STATUSES = frozenset(
    {
        RunStatus.APPROVED.value,
        RunStatus.SENT.value,
        RunStatus.RECONCILED.value,
        RunStatus.REJECTED.value,
        RunStatus.ERROR.value,
    }
)


@contextlib.contextmanager
def _conn_ctx(conn):
    """Yield (conn, owns): use the caller's conn, or open a pooled one we own."""
    if conn is not None:
        yield conn, False
    else:
        with get_connection() as owned:
            yield owned, True


# ---------------------------------------------------------------------------
# Ingest / run lifecycle
# ---------------------------------------------------------------------------


def insert_inbound_email(
    *,
    message_id: str,
    in_reply_to: str | None,
    references_header: str | None,
    subject: str | None,
    from_addr: str | None,
    to_addr: str | None,
    body_text: str,
    run_id: uuid.UUID | None = None,
    conn=None,
) -> tuple[uuid.UUID | None, bool]:
    """Insert an inbound email_messages row, idempotent on message_id.

    `body_text` is the ALREADY-CLEANED body (the webhook applies clean_body()
    BEFORE calling this); it is persisted verbatim so the inbound row is the
    cleaned-body source of truth (FIX C). Returns (email_id, inserted) where
    `inserted` is False on a duplicate (ON CONFLICT (message_id) DO NOTHING),
    so the webhook can decide whether to create a second run.
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            row = c.execute(
                """
                INSERT INTO email_messages (
                    run_id, direction, message_id, in_reply_to,
                    references_header, subject, from_addr, to_addr, body_text
                ) VALUES (%s, 'inbound', %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (message_id) DO NOTHING
                RETURNING id
                """,
                (
                    str(run_id) if run_id else None,
                    message_id,
                    in_reply_to,
                    references_header,
                    subject,
                    from_addr,
                    to_addr,
                    body_text,
                ),
            ).fetchone()
    if row is None:
        return None, False
    return uuid.UUID(str(row[0])), True


def find_business_by_sender(from_addr: str, conn=None) -> uuid.UUID | None:
    """Return the business_id whose contact_email matches from_addr, else None.

    An unknown sender returns None so the webhook stops without guessing
    (INGEST-03 access-control seam; T-02-12).
    """
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            "SELECT id FROM businesses WHERE contact_email = %s",
            (from_addr,),
        ).fetchone()
    return uuid.UUID(str(row[0])) if row else None


def create_run(
    *,
    business_id: uuid.UUID,
    source_email_id: uuid.UUID | None,
    pay_period_start: Any | None = None,
    pay_period_end: Any | None = None,
    conn=None,
) -> uuid.UUID:
    """Open a payroll_runs row (status defaults to 'received'); return its id."""
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            row = c.execute(
                """
                INSERT INTO payroll_runs (
                    business_id, source_email_id, pay_period_start, pay_period_end
                ) VALUES (%s, %s, %s, %s)
                RETURNING id
                """,
                (
                    str(business_id),
                    str(source_email_id) if source_email_id else None,
                    pay_period_start,
                    pay_period_end,
                ),
            ).fetchone()
    return uuid.UUID(str(row[0]))


def load_run(run_id: uuid.UUID, conn=None) -> dict | None:
    """Read one run as a dict (explicit columns + dict_row, never SELECT *)."""
    # RUN_COLS is a trusted module constant (no external input); building the
    # statement as a local keeps the parameterized-SQL discipline test green
    # (no inline f-string inside execute(...)). Values stay %s-parameterized.
    sql = "SELECT " + RUN_COLS + " FROM payroll_runs WHERE id = %s"
    with _conn_ctx(conn) as (c, _owns):
        with c.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql, (str(run_id),))
            return cur.fetchone()


def load_source_email(run_id: uuid.UUID, conn=None) -> str | None:
    """Return the run's ORIGINAL CLEANED inbound body, unchanged.

    The body was cleaned at ingest (insert_inbound_email persists the cleaned
    text), so it is read straight from email_messages.body_text with NO
    re-cleaning on read (FIX C; the Plan 04 resume re-extraction context).
    """
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            """
            SELECT em.body_text
            FROM payroll_runs pr
            JOIN email_messages em ON em.id = pr.source_email_id
            WHERE pr.id = %s
            """,
            (str(run_id),),
        ).fetchone()
    return row[0] if row else None


# Explicit column list for rebuilding an InboundEmail from the source email row
# (no SELECT * — InboundEmail is extra="forbid"). The stored body_text is already
# cleaned (FIX C), so the rebuilt InboundEmail carries the cleaned body unchanged.
_INBOUND_COLS = (
    "id, message_id, in_reply_to, references_header, subject, from_addr,"
    " to_addr, body_text, created_at"
)


def load_inbound_email(run_id: uuid.UUID, conn=None):
    """Rebuild the run's source InboundEmail (cleaned body) for the extract stage.

    Returns an InboundEmail or None if the run has no linked source email. The
    body_text is the cleaned body persisted at ingest — NOT re-cleaned (FIX C).
    """
    from app.models.contracts import InboundEmail

    sql = (
        "SELECT " + _INBOUND_COLS + " FROM email_messages em"
        " JOIN payroll_runs pr ON pr.source_email_id = em.id"
        " WHERE pr.id = %s"
    )
    with _conn_ctx(conn) as (c, _owns):
        with c.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql, (str(run_id),))
            row = cur.fetchone()
    return InboundEmail(**row) if row else None


# ---------------------------------------------------------------------------
# Status / persistence
# ---------------------------------------------------------------------------


def set_status(run_id: uuid.UUID, status: RunStatus, conn=None) -> None:
    """The ONE AND ONLY function that writes payroll_runs.status.

    Writes the enum .value (never a string literal). record_run_error is the one
    documented caller that also writes a data column; every other status
    transition in the system routes through here.
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "UPDATE payroll_runs SET status = %s, updated_at = now() WHERE id = %s",
                (RunStatus(status).value, str(run_id)),
            )


def record_run_error(run_id: uuid.UUID, reason: str, conn=None) -> None:
    """Write payroll_runs.error_reason AND advance the run to ERROR.

    The single documented exception to "set_status is the only status writer":
    it writes the error_reason data column itself, then routes its ERROR
    transition THROUGH set_status (FIX B) — so there is still exactly one
    status-write path and no second writer can corrupt the state machine.

    WR-04: this must NOT clobber a run that is already TERMINAL. A late/duplicate
    reply (cf. CR-02) that resumes a run which then hits an exception would otherwise
    flip an approved/sent/reconciled/rejected run to ERROR, destroying the run's real
    state and the approval audit trail. So read the current status inside the same
    transaction first; if it is terminal, log and return WITHOUT writing — defense in
    depth even with CR-02's resume precondition in place. (No-op on terminal includes
    a run already in ERROR — re-stamping it is pointless.)
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            current = c.execute(
                "SELECT status FROM payroll_runs WHERE id = %s", (str(run_id),)
            ).fetchone()
            if current is not None and current[0] in _TERMINAL_STATUSES:
                logger.info(
                    "record_run_error skipped: run %s is terminal (%s) — not "
                    "clobbering to ERROR (WR-04). reason was: %s",
                    run_id,
                    current[0],
                    reason,
                )
                return
            c.execute(
                "UPDATE payroll_runs SET error_reason = %s, updated_at = now() WHERE id = %s",
                (reason, str(run_id)),
            )
            set_status(run_id, RunStatus.ERROR, conn=c)


def persist_extracted(run_id: uuid.UUID, extracted: Extracted, conn=None) -> None:
    """Write the Extracted JSONB + the run's pay-period columns (no status — the
    orchestrator advances state). The pay_period_start/end run columns were left null
    before (review fix): they exist on payroll_runs for the dashboard/queries to read
    off the run row, so populate them from the extraction rather than only the JSONB."""
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "UPDATE payroll_runs SET extracted_data = %s, "
                "pay_period_start = %s, pay_period_end = %s, updated_at = now() "
                "WHERE id = %s",
                (
                    json.dumps(extracted.model_dump(mode="json")),
                    extracted.pay_period_start,
                    extracted.pay_period_end,
                    str(run_id),
                ),
            )


def persist_decision(run_id: uuid.UUID, decision: Decision, conn=None) -> None:
    """Write the Decision JSONB ONLY.

    Takes NO final_status argument (FIX B): persistence helpers never own status
    transitions. The orchestrator calls set_status SEPARATELY to advance state
    after persisting the decision.
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "UPDATE payroll_runs SET decision = %s, updated_at = now() WHERE id = %s",
                (json.dumps(decision.model_dump(mode="json")), str(run_id)),
            )


def persist_reconciliation(
    run_id: uuid.UUID, matches: list[NameMatchResult], conn=None
) -> None:
    """Write the per-run list[NameMatchResult] JSONB ONLY (D-A3-05; no status).

    The deterministic NameMatchResult shape (source/resolved) carries no score, so
    the persisted JSONB is automatically free of any per-name confidence; there is no
    separate name_matches relational write path (dropped in Phase 2.1, D-21-06).
    """
    payload = [m.model_dump(mode="json") for m in matches]
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "UPDATE payroll_runs SET reconciliation = %s, updated_at = now() WHERE id = %s",
                (json.dumps(payload), str(run_id)),
            )


def replace_line_items(
    run_id: uuid.UUID, items: list[PaystubLineItem], conn=None
) -> None:
    """Replace all paystub_line_items for a run (DELETE-by-run then insert).

    The idempotency invariant: a re-trigger / resume re-computes wholesale rather
    than appending duplicates (RESEARCH Pattern 6 invariant 2).
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "DELETE FROM paystub_line_items WHERE run_id = %s", (str(run_id),)
            )
            for it in items:
                c.execute(
                    """
                    INSERT INTO paystub_line_items (
                        id, run_id, employee_id, submitted_name,
                        hours_regular, hours_overtime, hours_vacation, hours_sick,
                        hours_holiday, gross_pay, pretax_401k, fica_ss,
                        fica_medicare, federal_withholding, state_withholding, net_pay
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s
                    )
                    """,
                    (
                        str(it.id),
                        str(it.run_id),
                        str(it.employee_id) if it.employee_id else None,
                        it.submitted_name,
                        it.hours_regular,
                        it.hours_overtime,
                        it.hours_vacation,
                        it.hours_sick,
                        it.hours_holiday,
                        it.gross_pay,
                        it.pretax_401k,
                        it.fica_ss,
                        it.fica_medicare,
                        it.federal_withholding,
                        it.state_withholding,
                        it.net_pay,
                    ),
                )


# ---------------------------------------------------------------------------
# Email / threading
# ---------------------------------------------------------------------------


def insert_email_message(
    *,
    run_id: uuid.UUID | None,
    direction: str,
    message_id: str,
    in_reply_to: str | None = None,
    references_header: str | None = None,
    subject: str | None = None,
    from_addr: str | None = None,
    to_addr: str | None = None,
    body_text: str | None = None,
    conn=None,
) -> uuid.UUID:
    """Append an email_messages row (the append-only audit log). Returns its id."""
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            row = c.execute(
                """
                INSERT INTO email_messages (
                    run_id, direction, message_id, in_reply_to,
                    references_header, subject, from_addr, to_addr, body_text
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    str(run_id) if run_id else None,
                    direction,
                    message_id,
                    in_reply_to,
                    references_header,
                    subject,
                    from_addr,
                    to_addr,
                    body_text,
                ),
            ).fetchone()
    # In real Postgres RETURNING always yields a row; the fallback only matters
    # for the offline FakeConnection path where the caller discards the id.
    return uuid.UUID(str(row[0])) if row else uuid.uuid4()


def get_outbound_message_id(run_id: uuid.UUID, conn=None) -> str | None:
    """Read the clarification Message-ID back from the linked outbound row.

    The outbound Message-ID lives ONLY on the email_messages(direction='outbound',
    run_id) row — the single canonical anchor (FIX 3); there is no
    payroll_runs.clarification_message_id column.
    """
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            """
            SELECT message_id FROM email_messages
            WHERE run_id = %s AND direction = 'outbound'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(run_id),),
        ).fetchone()
    return row[0] if row else None


def _pad_references(references_header: str | None) -> str:
    """Normalize a References header to a single-space-delimited, space-PADDED string.

    WR-02: the header-chain match must compare WHOLE angle-bracketed Message-ID
    tokens, not bare substrings. A References header is RFC-5322 whitespace-separated
    `<id>` tokens; we collapse any run of whitespace (spaces/tabs/folded CRLF) to one
    space and pad both ends with a space, so the SQL can match ` <id> ` as a
    whitespace-bounded token. This stops a stored Message-ID that is a substring of
    another (or of arbitrary attacker-supplied References text) from false-matching:
    ` <a@x> ` cannot appear inside ` <a@xtra> `. Stored synthetic IDs are
    `<uuid4@payroll-agent.local>` so they are angle-bracketed whole tokens. Returns
    " " for an absent/empty header (matches nothing — never the empty-substring trap).
    """
    if not references_header:
        return " "
    return " " + " ".join(references_header.split()) + " "


# The shared, anchored header-chain predicate (WR-02). Both finders use the SAME
# SQL so the resume lookup and the late-reply observability lookup match identically.
# `em.message_id` already carries its surrounding `<...>`; padding the references
# string with spaces (via _pad_references) and the pattern with ` `/` ` makes the
# match a whitespace-bounded WHOLE-token comparison, not an unanchored substring.
# Both placeholders stay NAMED — never interpolated (T-02-01).
_HEADER_MATCH_PREDICATE = (
    "( em.message_id = %(in_reply_to)s"
    " OR %(references)s LIKE '%% ' || em.message_id || ' %%' )"
)


def find_awaiting_reply_for_header(
    *, in_reply_to: str | None, references_header: str | None, conn=None
) -> uuid.UUID | None:
    """Match a reply to its run via the RFC header chain, restricted to awaiting_reply.

    Scans the stored outbound Message-ID against the reply's In-Reply-To AND the
    full References chain. The `references` match is a NAMED placeholder, never
    interpolated (T-02-01), and is anchored on whole tokens (WR-02).
    """
    sql = (
        "SELECT pr.id FROM payroll_runs pr"
        " JOIN email_messages em ON em.run_id = pr.id AND em.direction = 'outbound'"
        " WHERE pr.status = 'awaiting_reply'"
        "   AND " + _HEADER_MATCH_PREDICATE +
        " LIMIT 1"
    )
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            sql,
            {
                "in_reply_to": in_reply_to,
                "references": _pad_references(references_header),
            },
        ).fetchone()
    return uuid.UUID(str(row[0])) if row else None


def find_any_run_for_header(
    *, in_reply_to: str | None, references_header: str | None, conn=None
) -> uuid.UUID | None:
    """The SAME header match across ANY status (late-reply observability, FIX 10).

    A header match to an already-sent/reconciled run is observable as a late
    reply rather than silently dropped. Named placeholders only; whole-token
    anchored (WR-02).
    """
    sql = (
        "SELECT pr.id FROM payroll_runs pr"
        " JOIN email_messages em ON em.run_id = pr.id AND em.direction = 'outbound'"
        " WHERE " + _HEADER_MATCH_PREDICATE +
        " LIMIT 1"
    )
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            sql,
            {
                "in_reply_to": in_reply_to,
                "references": _pad_references(references_header),
            },
        ).fetchone()
    return uuid.UUID(str(row[0])) if row else None


# ---------------------------------------------------------------------------
# Roster
# ---------------------------------------------------------------------------


def load_roster_for_business(business_id: uuid.UUID, conn=None) -> Roster:
    """Rebuild a typed Roster (explicit EMPLOYEE_COLS + dict_row, no SELECT *)."""
    # EMPLOYEE_COLS is a trusted module constant; build the statement as a local
    # (no inline f-string in execute) to keep the parameterized-SQL discipline.
    sql = "SELECT " + EMPLOYEE_COLS + " FROM employees WHERE business_id = %s"
    with _conn_ctx(conn) as (c, _owns):
        with c.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql, (str(business_id),))
            rows = cur.fetchall()
    return Roster(
        business_id=business_id,
        employees=[Employee(**row) for row in rows],
    )


# ---------------------------------------------------------------------------
# Internal: a no-op transaction context for the caller-supplied-conn path.
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _nulltx():
    """No-op CM: when a caller passes their own conn, they own the transaction."""
    yield
