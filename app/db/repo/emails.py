"""DB repo — email_messages append-only audit log, threading/header lookups."""
from __future__ import annotations

import logging
import uuid

import psycopg.rows

from app.db.repo._shared import _conn_ctx, _nulltx

logger = logging.getLogger("payroll_agent.repo")


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
    round: int = 0,
    conn=None,
) -> uuid.UUID:
    """Append an email_messages row (the append-only audit log). Returns its id.

    When purpose is non-NULL (outbound rows with a purpose value), the INSERT
    upserts on the uq_email_run_purpose_round constraint (run_id, purpose, round)
    (D-11-01: widened from the old 2-column uq_email_run_purpose in the SAME plan
    step as this arbiter change — Pitfall #1, the constraint and the ON CONFLICT
    clause must never drift apart). This turns a retry WITHIN a round over a
    prior 'reserved' or 'failed' row into an advancement to 'sent' rather than a
    unique-constraint crash (NEW-1 D-13c sharpening); a NEW round is a NEW row
    (D-11-01: no upsert-replace of prior-round history).

    `round` defaults to 0, so every existing caller (none of which passes it yet
    in this plan) is behavior-identical: a round-0 row upserts exactly like the
    old (run_id, purpose) arbiter did, because round=0 is now baked into both
    the row and the constraint.

    Inbound rows (purpose=NULL) are unaffected: Postgres treats NULLs as distinct
    in UNIQUE constraints, so inbound rows never conflict.

    GAP-2/GAP-3 (11-06): the OUTBOUND path (purpose is not None) also stamps
    epoch = (SELECT reply_epoch FROM payroll_runs WHERE id = %s) — a single
    correlated subquery against the run being written to, in the INSERT
    column list/values. This reads the CURRENT run epoch at write time (never
    re-read/mutated afterward).

    The ON CONFLICT arbiter is (run_id, purpose, round, epoch) — widened from
    (run_id, purpose, round), matching the widened uq_email_run_purpose_round_epoch
    constraint (GAP-2 fix). This is NOT optional: a retrigger resets
    clarification_round to 0, so the retriggered run's fresh round-0 send has
    the SAME (run_id, purpose, round) tuple as a stale pre-retrigger round-0
    row. Arbiting on the narrower 3-column key would silently UPSERT (mutate)
    that historical row instead of inserting a new one — corrupting the
    append-only audit log on every retrigger. Epoch in the arbiter makes the
    two rows distinct conflict targets, so the retriggered send always INSERTs
    a genuinely new row; an in-round retry (same epoch) still correctly
    upserts in place (Pitfall #1 preserved). Zero caller changes: run_id is
    already a parameter every existing call site (gateway.send_outbound,
    _clarify's record_only branch) passes.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        if purpose is not None:
            # Outbound path with a purpose: upsert on (run_id, purpose, round, epoch)
            # so a retry WITHIN a round AND epoch over a reserved/failed row advances
            # to the new send_state rather than crashing with a unique constraint
            # violation — while a NEW epoch's same-round send is a genuinely
            # different conflict target and always inserts a new row (GAP-2 fix).
            row = c.execute(
                """
                    INSERT INTO email_messages (
                        run_id, direction, message_id, in_reply_to,
                        references_header, subject, from_addr, to_addr, body_text,
                        purpose, send_state, round, epoch
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        (SELECT reply_epoch FROM payroll_runs WHERE id = %s))
                    ON CONFLICT (run_id, purpose, round, epoch) DO UPDATE
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
                    round,
                    str(run_id) if run_id else None,
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
                        purpose, send_state, round
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                    round,
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
    if purpose not in ("clarification", "confirmation", "clarification_field_regression"):
        raise ValueError(
            "purpose must be 'clarification', 'confirmation', or "
            f"'clarification_field_regression', got {purpose!r}"
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


def get_outbound_for_round(
    run_id: uuid.UUID, purpose: str, round: int, conn=None
) -> dict | None:
    """Round-aware and send_state-filtered outbound row lookup (D-11-01/D-11-13).

    Same shape as get_outbound_message_id — the invalid-purpose guard (T-05-09b)
    and the `send_state = 'sent'` proof-of-delivery filter are both preserved —
    with an added `round` filter. Returns a dict (not just the message_id) so
    callers can read the FOUND ROW's round back: the idempotent next round is
    always derived from this row's round (`row["round"] + 1`), never a blind
    `round + 1` on the caller's own counter (Pitfall #3 — crash-safety of the
    round increment depends on re-deriving from what was actually sent).

    Raises ValueError on an unrecognised purpose value (same guard as
    get_outbound_message_id).

    GAP-2 (11-06): also scoped to the run's CURRENT epoch via a correlated
    subquery on the SAME run_id parameter (no new function parameter). This
    is the actual GAP-2 fix — a stale pre-retrigger round-0 row belongs to
    epoch 0, but a retriggered run is now at epoch 1, so this query literally
    cannot see it anymore.
    """
    if purpose not in ("clarification", "confirmation", "clarification_field_regression"):
        raise ValueError(
            "purpose must be 'clarification', 'confirmation', or "
            f"'clarification_field_regression', got {purpose!r}"
        )
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            """
            SELECT message_id, round FROM email_messages
            WHERE run_id = %s AND direction = 'outbound'
              AND purpose = %s AND send_state = 'sent' AND round = %s
              AND epoch = (SELECT reply_epoch FROM payroll_runs WHERE id = %s)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(run_id), purpose, round, str(run_id)),
        ).fetchone()
    if row is None:
        return None
    return {"message_id": row[0], "round": row[1]}


def mark_reply_consumed(message_id: str, round: int, conn=None) -> None:
    """Write-once marker: this inbound reply has been consumed at `round` (D-11-02).

    `consumed_round IS NULL` in the WHERE clause makes this write-once — a
    second call (e.g. WR-04 redelivery re-scheduling the same message_id) is a
    silent no-op rather than overwriting an already-consumed row. Restricted to
    direction='inbound' so an outbound row can never be marked consumed.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        c.execute(
            "UPDATE email_messages SET consumed_round = %s"
            " WHERE message_id = %s AND direction = 'inbound' AND consumed_round IS NULL",
            (round, message_id),
        )


def load_consumed_replies(run_id: uuid.UUID, conn=None) -> list[dict]:
    """Return all consumed inbound replies for a run, round-ordered (D-11-10/12/13).

    Copies load_thread_messages' dict_row multi-row shape. Filters to
    direction='inbound' AND consumed_round IS NOT NULL, ordered by
    consumed_round ASC so a later plan's accumulated-context builder can render
    every consumed reply in the order it was actually processed (not insertion
    order, which can differ under redelivery/retry).

    GAP-3 (11-06): also scoped to the run's CURRENT epoch via a correlated
    subquery. This is the actual GAP-3 fix — a stale consumed reply from a
    pre-retrigger epoch is invisible to the post-retrigger accumulation, even
    though the row is never deleted (append-only preserved).
    """
    sql = (
        "SELECT direction, purpose, subject, body_text, message_id,"
        " from_addr, to_addr, consumed_round, created_at"
        " FROM email_messages"
        " WHERE run_id = %s AND direction = 'inbound' AND consumed_round IS NOT NULL"
        " AND epoch = (SELECT reply_epoch FROM payroll_runs WHERE id = %s)"
        " ORDER BY consumed_round ASC"
    )
    with _conn_ctx(conn) as (c, _owns), c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, (str(run_id), str(run_id)))
        return cur.fetchall() or []


def get_inbound_by_message_id(message_id: str, conn=None) -> dict | None:
    """Load the PERSISTED inbound row by its RFC message_id (D-11-13, Pitfall #11a).

    WR-04 redelivery must resume from the row already written at first ingest
    (cleaned body_text, run_id via WR-03 linking, consumed_round) — NEVER
    rebuild an InboundEmail from a redelivered webhook request body, which
    would re-clean/re-parse and could diverge from what was actually processed.

    Plan 11-05: the column list is widened to the FULL InboundEmail field set
    (id, in_reply_to, references_header, created_at added) so app.main's
    `_row_to_inbound` helper can build a valid InboundEmail (extra="forbid")
    directly from this row with no second lookup.
    """
    with _conn_ctx(conn) as (c, _owns), c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT id, run_id, message_id, in_reply_to, references_header,"
            " subject, body_text, from_addr, to_addr, consumed_round, created_at"
            " FROM email_messages WHERE message_id = %s AND direction = 'inbound'",
            (message_id,),
        )
        return cur.fetchone()


# Round-cap escalation scope (D-11-05): EXACTLY this stale, unconsumed,
# awaiting_reply combination is eligible for the WR-04 auto-resume sweep — a
# deliberately DIFFERENT scope from _STRANDED_SCOPE_STATUSES (received/
# extracting/computed) and from the retrigger stale_statuses list. A reply
# sitting unconsumed against an awaiting_reply run past the staleness
# threshold means the resume webhook never fired (dead background task or
# missed redelivery), not a normal in-flight run — pinned by an explicit unit
# test alongside the other two scope-pin tests (Pitfall #4 item 7).
_STRANDED_REPLY_SCOPE_STATUS = "awaiting_reply"


def find_stranded_unconsumed_replies(threshold_seconds: int, conn=None) -> list[dict]:
    """Find stale unconsumed inbound replies against awaiting_reply runs (D-11-05).

    Joins email_messages (direction='inbound', consumed_round IS NULL,
    run_id IS NOT NULL, created_at older than the staleness threshold) to
    payroll_runs (status = 'awaiting_reply'). Returns reply-row dicts with the
    same fields as get_inbound_by_message_id plus run_id, so the D-11-05 sweep
    hook (Plan 11-05) can re-schedule _resume_pipeline for each one — the CAS
    claim inside resume_pipeline absorbs any double-schedule.

    Plan 11-05: the column list is widened to the FULL InboundEmail field set
    (id, in_reply_to, references_header added; created_at was already
    selected) matching get_inbound_by_message_id's widening, so
    `_row_to_inbound` builds a valid InboundEmail from either query's rows.

    GAP-2/GAP-3 (11-06): the JOIN condition also requires em.epoch = pr.reply_epoch
    (a column comparison across the existing join, not a new subquery). This
    closes a subtler epoch variant: a genuinely stale epoch-0 unconsumed reply
    must never be auto-resumed against a run that has since been retriggered
    into a NEW epoch-1 awaiting_reply state.
    """
    sql = (
        "SELECT em.id, em.run_id, em.message_id, em.in_reply_to,"
        " em.references_header, em.subject, em.body_text,"
        " em.from_addr, em.to_addr, em.consumed_round, em.created_at"
        " FROM email_messages em"
        " JOIN payroll_runs pr ON pr.id = em.run_id AND em.epoch = pr.reply_epoch"
        " WHERE em.direction = 'inbound'"
        "   AND em.consumed_round IS NULL"
        "   AND em.run_id IS NOT NULL"
        "   AND pr.status = %s"
        "   AND em.created_at < now() - (%s || ' seconds')::interval"
    )
    with _conn_ctx(conn) as (c, _owns), c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, (_STRANDED_REPLY_SCOPE_STATUS, str(threshold_seconds)))
        return cur.fetchall() or []


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
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
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
    with _conn_ctx(conn) as (c, _owns), c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, (str(run_id),))
        return cur.fetchall() or []


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
    with _conn_ctx(conn) as (c, _owns), c.cursor(row_factory=psycopg.rows.dict_row) as cur:
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
