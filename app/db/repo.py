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
    two writers: set_status (unguarded forward transitions inside an owned path)
    and claim_status (atomic guarded claim at every contended gate)
    record_run_error       — the ONE documented exception: writes error_reason AND
                             routes its ERROR transition THROUGH set_status (FIX B,
                             so there is still exactly one status-write path)
    persist_extracted      — Extracted JSONB only (no status)
    persist_decision       — Decision JSONB only; takes NO final_status (FIX B)
    persist_reconciliation — list[NameMatchResult] JSONB only (D-A3-05)
    replace_line_items     — DELETE-by-run then insert (idempotency invariant)
    set_alias_candidates   — write alias_candidates JSONB column (D-04)

  Email / threading
    insert_email_message       — generic append to email_messages (audit log); upserts
                                 on (run_id, purpose) for non-NULL purpose outbound rows
    get_outbound_message_id    — purpose-aware + send_state='sent'-filtered read of the
                                 outbound Message-ID (finding #1 + R2-HIGH fix, CLAR-04)
    update_email_message_sent  — flip send_state to 'sent' WHERE message_id=synthetic_id
                                 (06-04 D-13c success path; HIGH-1 schema-verified SQL)
    update_email_message_state — parameterized flip of send_state WHERE message_id=synthetic_id
                                 (06-04 HIGH-3 failed-state flip; HIGH-1 schema-verified SQL)
    get_outbound_references_chain — most-recent sent outbound references_header for a run
                                 (06-04 D-14 durable threading DB-load helper)
    find_awaiting_reply_for_header — header-chain match restricted to awaiting_reply
    find_any_run_for_header    — SAME header match across ANY status (late-reply
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
# CR-02 fix: updated_at is included so load_run() returns it as a tz-aware
# datetime (the column is TIMESTAMPTZ — psycopg returns tz-aware datetimes).
# Without it, the retrigger handler's stale-run check always evaluated to False
# (run.get("updated_at") was always None) and the stale-state recovery branch
# for RECEIVED/EXTRACTING/COMPUTED/SENT was permanently disabled.
RUN_COLS = (
    "id, business_id, source_email_id, status, extracted_data, decision,"
    " reconciliation, error_reason, pay_period_start, pay_period_end, updated_at"
)

# Terminal run statuses (WR-04): once a run reaches one of these, an error must NOT
# overwrite it. SENT/RECONCILED/REJECTED are finalized human/operator outcomes
# (clobbering them destroys the approval audit trail); ERROR is already terminal.
# NOTE: APPROVED is intentionally NOT in this set (D-13b critical finding): an
# approved run that fails delivery must be recoverable — record_run_error must be
# able to advance it to ERROR so the operator can retrigger. A human re-approves
# after the delivery failure is fixed; the audit trail is preserved via ERROR +
# error_reason. Adding APPROVED here would silently swallow delivery failures.
_TERMINAL_STATUSES = frozenset(
    {
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

    Additive fallback: if no contact_email match, check demo_sender_bindings for
    operator-email → business mapping (HIGH-2 fix; never mutates businesses table).
    This allows Path-2 real-email inbound to route via the operator's Gmail binding
    without changing any seed contact_email value.
    """
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            "SELECT id FROM businesses WHERE contact_email = %s",
            (from_addr,),
        ).fetchone()
        if row is not None:
            return uuid.UUID(str(row[0]))
        # Additive fallback: check demo_sender_bindings for operator email → business_id
        binding_row = c.execute(
            "SELECT business_id FROM demo_sender_bindings WHERE operator_email = %s",
            (from_addr,),
        ).fetchone()
        return uuid.UUID(str(binding_row[0])) if binding_row else None


def load_business_name(business_id: uuid.UUID, conn=None) -> str | None:
    """Return the display name for a business, or None if not found.

    Used by _deliver (CR-03 fix) to enrich the run dict with business_name
    before composing the confirmation email. Kept as a thin targeted helper
    so load_run stays lean (no JOIN for every caller).
    """
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            "SELECT name FROM businesses WHERE id = %s",
            (str(business_id),),
        ).fetchone()
    return str(row[0]) if row else None


def create_run(
    *,
    business_id: uuid.UUID,
    source_email_id: uuid.UUID | None,
    pay_period_start: Any | None = None,
    pay_period_end: Any | None = None,
    record_only: bool = False,
    conn=None,
) -> uuid.UUID:
    """Open a payroll_runs row (status defaults to 'received'); return its id.

    record_only=True: compose-created (in-app demo) runs that should skip the real
    Resend provider call. The orchestrator reads this flag at each send_outbound call
    site (_clarify and _deliver) via get_record_only_flag(). LOW-6: passing
    record_only=True directly to create_run is cleaner than create-then-set_record_only.
    Existing callers supply no record_only arg and get the False default — no behavior
    change for live runs.
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            row = c.execute(
                """
                INSERT INTO payroll_runs (
                    business_id, source_email_id, pay_period_start, pay_period_end,
                    record_only
                ) VALUES (%s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    str(business_id),
                    str(source_email_id) if source_email_id else None,
                    pay_period_start,
                    pay_period_end,
                    record_only,
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
# Every column is qualified with the `em.` alias: load_inbound_email JOINs
# payroll_runs (which also has `id`, `created_at`), so a bare `id` is ambiguous
# (psycopg AmbiguousColumn). `em.id` still returns a result column named `id`, so
# the InboundEmail(**row) construction is unchanged.
_INBOUND_COLS = (
    "em.id, em.message_id, em.in_reply_to, em.references_header, em.subject,"
    " em.from_addr, em.to_addr, em.body_text, em.created_at"
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
    """Unguarded status writer — one of two writers on payroll_runs.status (D-12).

    two writers: set_status (unguarded forward transitions inside an owned path)
    and claim_status (atomic guarded claim at every contended gate).
    Writes the enum .value (never a string literal). record_run_error is the one
    documented caller that also writes a data column; every other uncontended
    status transition in the system routes through here.
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "UPDATE payroll_runs SET status = %s, updated_at = now() WHERE id = %s",
                (RunStatus(status).value, str(run_id)),
            )


def claim_status(
    run_id: uuid.UUID,
    expected: RunStatus,
    new: RunStatus,
    conn=None,
) -> bool:
    """Atomic compare-and-swap on payroll_runs.status (D-12, FOUND-04).

    two writers: set_status (unguarded forward transitions inside an owned path)
    and claim_status (atomic guarded claim at every contended gate).

    Returns True if the claim succeeded (run was in `expected` and is now `new`).
    Returns False if the run was NOT in `expected` — caller logs a late/duplicate
    and drops cleanly (does not re-run the work).

    The SQL uses WHERE id = %s AND status = %s RETURNING id so only one concurrent
    caller gets a row back; the other gets None and drops cleanly (T-05-01).
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            row = c.execute(
                "UPDATE payroll_runs SET status = %s, updated_at = now() "
                "WHERE id = %s AND status = %s RETURNING id",
                (RunStatus(new).value, str(run_id), RunStatus(expected).value),
            ).fetchone()
    return row is not None


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


def set_alias_candidates(
    run_id: uuid.UUID,
    candidates: dict,
    conn=None,
) -> None:
    """Write alias_candidates to payroll_runs.alias_candidates JSONB column (D-04).

    Separate column (not a key in reconciliation JSONB) so it is NEVER overwritten
    by persist_reconciliation on resume (RESEARCH Open Question #1, D-04 decision).
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "UPDATE payroll_runs SET alias_candidates = %s, updated_at = now() WHERE id = %s",
                (json.dumps(candidates), str(run_id)),
            )


def update_known_alias(
    employee_id: uuid.UUID,
    new_alias: str,
    conn=None,
) -> bool:
    """Idempotently append new_alias to employees.known_aliases (D-01).

    Caller MUST have already called _safe_to_learn_alias() — this function does
    NOT re-check collision; it only deduplicates the TEXT[] array.

    Uses a conditional UPDATE with `NOT (%s = ANY(known_aliases))` in the WHERE
    clause so the alias is only appended when absent. Returns True if the alias
    was actually added, False if it was already present (idempotent: safe to call
    twice without creating a double-add, D-01 idempotency).

    employees.known_aliases is TEXT[] (schema.sql line 32) — native TEXT[] array
    operators (unnest / ANY) are used, NOT JSONB ops (to_jsonb / jsonb_agg /
    jsonb_array_elements_text / @>). CR-01 fix.
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            row = c.execute(
                """
                UPDATE employees
                SET known_aliases = array(
                    SELECT DISTINCT unnest(known_aliases || ARRAY[%s::text])
                )
                WHERE id = %s
                  AND NOT (%s = ANY(known_aliases))
                RETURNING id
                """,
                (new_alias, str(employee_id), new_alias),
            ).fetchone()
    return row is not None


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
    purpose: str | None = None,
    send_state: str | None = None,
    conn=None,
) -> uuid.UUID:
    """Append an email_messages row (the append-only audit log). Returns its id.

    When purpose is non-NULL (outbound rows with a purpose value), the INSERT
    upserts on the uq_email_run_purpose constraint (run_id, purpose). This turns a
    retry over a prior 'reserved' or 'failed' row into an advancement to 'sent'
    rather than a unique-constraint crash (NEW-1 D-13c sharpening).

    Inbound rows (purpose=NULL) are unaffected: Postgres treats NULLs as distinct
    in UNIQUE constraints, so inbound rows never conflict.
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            if purpose is not None:
                # Outbound path with a purpose: upsert on (run_id, purpose) so a
                # retry over a reserved/failed row advances to the new send_state
                # rather than crashing with a unique constraint violation.
                row = c.execute(
                    """
                    INSERT INTO email_messages (
                        run_id, direction, message_id, in_reply_to,
                        references_header, subject, from_addr, to_addr, body_text,
                        purpose, send_state
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (run_id, purpose) DO UPDATE
                        SET send_state = EXCLUDED.send_state,
                            message_id = EXCLUDED.message_id,
                            subject = EXCLUDED.subject,
                            body_text = EXCLUDED.body_text,
                            created_at = now()
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
                        purpose,
                        send_state,
                    ),
                ).fetchone()
            else:
                # Inbound path (purpose=NULL): plain insert with no upsert on purpose
                # (NULLs are DISTINCT in Postgres UNIQUE constraints).
                row = c.execute(
                    """
                    INSERT INTO email_messages (
                        run_id, direction, message_id, in_reply_to,
                        references_header, subject, from_addr, to_addr, body_text,
                        purpose, send_state
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        purpose,
                        send_state,
                    ),
                ).fetchone()
    # In real Postgres RETURNING always yields a row; the fallback only matters
    # for the offline FakeConnection path where the caller discards the id.
    return uuid.UUID(str(row[0])) if row else uuid.uuid4()


def get_outbound_message_id(run_id: uuid.UUID, purpose: str, conn=None) -> str | None:
    """Purpose-aware and send_state-filtered outbound Message-ID lookup (finding #1 + R2-HIGH).

    Only a row with purpose=X AND send_state='sent' counts as proof-of-delivery.
    A reserved (pre-send intent, pre-crash) or failed row does NOT match — preventing
    the delivery guard from skipping a required send after a crash (R2-HIGH: D-13c
    crash-safe proof-of-send, Codex finding #1 fix, CLAR-04).

    Raises ValueError on an unrecognised purpose value (invalid-purpose guard prevents
    accidental purpose-blind calls — T-05-09b).
    """
    if purpose not in ("clarification", "confirmation"):
        raise ValueError(
            f"purpose must be 'clarification' or 'confirmation', got {purpose!r}"
        )
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            """
            SELECT message_id FROM email_messages
            WHERE run_id = %s AND direction = 'outbound'
              AND purpose = %s AND send_state = 'sent'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(run_id), purpose),
        ).fetchone()
    return row[0] if row else None


def update_email_message_sent(message_id: str, conn=None) -> None:
    """Flip send_state to 'sent' for the outbound row keyed on SYNTHETIC message_id.

    06-04 D-13c success path. HIGH-1 schema-verified SQL: email_messages has
    send_state but NO provider_message_id and NO updated_at — the SET clause sets
    ONLY send_state='sent'. WHERE key is the SYNTHETIC message_id minted by
    send_outbound (BLOCKER-3: never the Resend provider id). Two %s placeholders:
    the 'sent' state and the synthetic message_id.

    Delegates to update_email_message_state for parameterized SQL discipline and
    testability (tests can assert 'sent' appears in the params tuple).
    """
    update_email_message_state(message_id, "sent", conn=conn)


def update_email_message_state(message_id: str, state: str, conn=None) -> None:
    """Parameterized flip of send_state for the outbound row keyed on SYNTHETIC message_id.

    06-04 HIGH-3 failed-state flip. HIGH-1 schema-verified SQL: email_messages has
    send_state but NO updated_at in the SET clause (column does not exist). WHERE key
    is the SYNTHETIC message_id minted by send_outbound (BLOCKER-3). Two %s placeholders:
    the new state and the synthetic message_id.
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "UPDATE email_messages SET send_state = %s WHERE message_id = %s",
                (state, message_id),
            )


def get_outbound_references_chain(run_id: uuid.UUID, conn=None) -> str | None:
    """Return the references_header of the most-recent sent outbound row for this run.

    06-04 D-14 durable threading DB-load helper. gateway.send_outbound calls this
    BEFORE the reserved INSERT to load the prior accumulated References chain, then
    appends the new in_reply_to token. Building from DB state (not ephemeral webhook
    state) means the chain survives dropped/duplicated deliveries.

    Returns None if no sent outbound row exists for this run (first outbound send).
    """
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            """
            SELECT references_header FROM email_messages
            WHERE run_id = %s AND direction = 'outbound' AND send_state = 'sent'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(run_id),),
        ).fetchone()
    return row[0] if row else None


def load_outbound_emails(run_id: uuid.UUID, conn=None) -> list[dict]:
    """Read all outbound email rows for a run (UAT #1 — run detail sent-emails section).

    Returns rows with the fields needed for display: direction, purpose, subject,
    body_text, message_id, created_at. Ordered oldest-first so confirmation/
    clarification appear in send order. Read-only; never mutates run state.

    Explicit column list (no SELECT *) per repo discipline. Parameterized SQL only.
    """
    sql = (
        "SELECT direction, purpose, subject, body_text, message_id, created_at"
        " FROM email_messages"
        " WHERE run_id = %s AND direction = 'outbound'"
        " ORDER BY created_at"
    )
    with _conn_ctx(conn) as (c, _owns):
        with c.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql, (str(run_id),))
            return cur.fetchall() or []


# ---------------------------------------------------------------------------
# Demo routing helpers (06-08): demo_sender_bindings + record_only + thread view
# ---------------------------------------------------------------------------


def list_businesses(conn=None) -> list[dict]:
    """Return all businesses ordered by name for the landing page picker.

    Explicit column list (no SELECT *) per repo discipline. Returns [] on empty.
    """
    sql = "SELECT id, name, contact_email FROM businesses ORDER BY name"
    with _conn_ctx(conn) as (c, _owns):
        with c.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql)
            return cur.fetchall() or []


def bind_demo_business(
    business_name: str,
    operator_email: str,
    seed_business_ids: dict,
    conn=None,
) -> bool:
    """UPSERT operator email → business into demo_sender_bindings (HIGH-2 fix).

    NEVER touches businesses.contact_email. The seed .example contacts are permanently
    stable. Only demo_sender_bindings is written. The operator_email is the hardcoded
    DEMO_OPERATOR_EMAIL constant from the call site — never user-supplied.

    Args:
        business_name: validated against the seed_business_ids allowlist.
        operator_email: the hardcoded operator email (DEMO_OPERATOR_EMAIL).
        seed_business_ids: dict[str, UUID] of the three stable seed businesses.

    Returns:
        True on success, False if business_name is not in the allowlist.
    """
    business_id = seed_business_ids.get(business_name)
    if business_id is None:
        return False  # unknown business name — allowlist enforced at route layer too
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                """
                INSERT INTO demo_sender_bindings (operator_email, business_id, bound_at)
                VALUES (%s, %s, now())
                ON CONFLICT (operator_email) DO UPDATE
                    SET business_id = EXCLUDED.business_id,
                        bound_at    = now()
                """,
                (operator_email, str(business_id)),
            )
    return True


def get_demo_binding(operator_email: str, conn=None) -> "uuid.UUID | None":
    """Return the business_id bound to operator_email in demo_sender_bindings, or None.

    Used by find_business_by_sender's additive check AND by GET / to display the
    currently-armed business (read-only — never mutates any state).
    """
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            "SELECT business_id FROM demo_sender_bindings WHERE operator_email = %s",
            (operator_email,),
        ).fetchone()
    return uuid.UUID(str(row[0])) if row else None


def set_record_only(run_id: uuid.UUID, conn=None) -> None:
    """Set record_only = TRUE on a run.

    Ad-hoc repair helper. In normal operation, create_run(record_only=True) is used
    directly (LOW-6 — no separate UPDATE needed at compose time).
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "UPDATE payroll_runs SET record_only = TRUE WHERE id = %s",
                (str(run_id),),
            )


def get_record_only_flag(run_id: uuid.UUID, conn=None) -> bool:
    """Return the record_only flag for a run.

    Returns False if the run is not found (safe default: live Resend path).
    Called by the orchestrator at each send_outbound call site (_clarify and _deliver).
    """
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            "SELECT record_only FROM payroll_runs WHERE id = %s",
            (str(run_id),),
        ).fetchone()
    if row is None:
        return False
    return bool(row[0])


def load_thread_messages(run_id: uuid.UUID, conn=None) -> list[dict]:
    """Return ALL email_messages rows for a run including the source inbound.

    The source inbound row was inserted with run_id=NULL at ingest — this OR clause
    captures it via payroll_runs.source_email_id so the full conversation thread
    (inbound request → clarification → reply → confirmation) appears in the thread view.

    Two %s params: (str(run_id), str(run_id)) — one for the run_id= check and one for
    the source_email_id subquery. Results are ordered chronologically (ASC).
    """
    sql = (
        "SELECT direction, purpose, subject, body_text, message_id,"
        " from_addr, to_addr, created_at"
        " FROM email_messages"
        " WHERE run_id = %s"
        "    OR id = (SELECT source_email_id FROM payroll_runs WHERE id = %s)"
        " ORDER BY created_at ASC"
    )
    with _conn_ctx(conn) as (c, _owns):
        with c.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql, (str(run_id), str(run_id)))
            return cur.fetchall() or []


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


def load_line_items(run_id: uuid.UUID, conn=None) -> list[PaystubLineItem]:
    """Return the paystub line items for a run (explicit column list — no SELECT *).

    LOW finding fix: explicit SELECT list matches PaystubLineItem fields.
    NOTE: additional_medicare_not_modeled is a PaystubLineItem model field (default=False)
    but is NOT a DB column in paystub_line_items — omitted from the SELECT list and the
    model uses its Python default (False). Never invent a column that does not exist.
    """
    sql = (
        "SELECT id, run_id, employee_id, submitted_name,"
        " hours_regular, hours_overtime, hours_vacation, hours_sick, hours_holiday,"
        " gross_pay, pretax_401k, fica_ss, fica_medicare, federal_withholding,"
        " state_withholding, net_pay, created_at"
        " FROM paystub_line_items WHERE run_id = %s ORDER BY employee_id"
    )
    with _conn_ctx(conn) as (c, _owns):
        with c.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql, (str(run_id),))
            rows = cur.fetchall()
    return [PaystubLineItem(**row) for row in rows]


def load_all_runs(conn=None) -> list[dict]:
    """Return all payroll runs in reverse-chronological order, with business_name.

    Used by the runs-list route (DASH-01). Joins businesses to surface business_name
    without requiring a second query in the route layer.
    """
    sql = (
        "SELECT pr.*, b.name as business_name"
        " FROM payroll_runs pr"
        " JOIN businesses b ON pr.business_id = b.id"
        " ORDER BY pr.created_at DESC"
    )
    with _conn_ctx(conn) as (c, _owns):
        with c.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql)
            return cur.fetchall() or []


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
