"""DB repo — email_messages append-only audit log, threading/header lookups."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from typing import Any

import psycopg
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
    conn: psycopg.Connection | None = None,
) -> uuid.UUID:
    """Append an email_messages row (the append-only audit log). Returns its id.

    INVARIANT — the ON CONFLICT arbiter and the DB unique constraint must never
    drift apart. The outbound path below arbitrates on
    (run_id, purpose, round, epoch); the schema's uq_email_run_purpose_round_epoch
    declares exactly those four columns. If either side is widened or narrowed
    without the other, this INSERT either crashes on a constraint it does not
    name or silently mutates a row it should have inserted beside. Change both,
    in the same step, or neither.

    Why each column is in the arbiter:

    - purpose is non-NULL only on outbound rows, so the upsert applies only to
      them. Inbound rows carry purpose=NULL and Postgres treats NULLs as
      DISTINCT in UNIQUE constraints, so inbound rows never conflict and take
      the plain-INSERT branch.
    - round makes a NEW clarification round a NEW row rather than an
      upsert-replace of prior-round history.  The outbound conflict path does
      not apply caller content at all: it returns the existing logical row.
      reserve_outbound_snapshot is the only API allowed to create
      the provider-ready payload for a slot; separate state-transition helpers
      own send_state after that reservation.
    - epoch is stamped from the run's CURRENT reply_epoch via a correlated
      subquery at write time (read once, never re-read or mutated afterward).
      It is NOT optional: a retrigger resets clarification_round to 0, so the
      retriggered run's fresh round-0 send carries the SAME
      (run_id, purpose, round) tuple as the stale pre-retrigger round-0 row.
      Arbitrating on the narrower 3-column key would make a post-retrigger
      send collide with historical evidence. With epoch in the arbiter the two
      rows are distinct conflict targets, so the retriggered send always
      INSERTs a genuinely new logical slot while a same-epoch conflict can
      only return its already-frozen record.

    `round` defaults to 0, so a caller that does not track rounds gets the
    round-0 row that the constraint also bakes round=0 into.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        if purpose is not None:
            # Outbound rows retain the logical send-slot identity, but must never
            # overwrite caller-visible payload fields on a conflict.  Providers use
            # reserve_outbound_snapshot below, which locks and returns the original
            # frozen envelope; this legacy audit helper merely returns the existing id.
            row = c.execute(
                """
                    INSERT INTO email_messages (
                        run_id, direction, message_id, in_reply_to,
                        references_header, subject, from_addr, to_addr, body_text,
                        purpose, send_state, round, epoch
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        (SELECT reply_epoch FROM payroll_runs WHERE id = %s))
                    ON CONFLICT (run_id, purpose, round, epoch) DO NOTHING
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
        if row is None and purpose is not None:
            row = c.execute(
                """
                SELECT id FROM email_messages
                WHERE run_id = %s AND purpose = %s AND round = %s
                  AND epoch = (SELECT reply_epoch FROM payroll_runs WHERE id = %s)
                """,
                (str(run_id), purpose, round, str(run_id)),
            ).fetchone()
    # In real Postgres RETURNING/SELECT yields a row; the fallback only matters for
    # the offline FakeConnection path where the caller discards the id.
    return uuid.UUID(str(row[0])) if row else uuid.uuid4()


def _load_outbound_snapshot_locked(
    c: psycopg.Connection,
    *,
    run_id: uuid.UUID,
    email_id: uuid.UUID,
    lock: bool,
) -> dict[str, Any] | None:
    """Load one owned frozen envelope with explicit provider fields only."""
    lock_sql = " FOR UPDATE OF em, snapshot" if lock else ""
    with c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            """
            SELECT snapshot.id AS snapshot_id, em.id AS email_id, em.run_id,
                   em.purpose, em.round, em.epoch, snapshot.message_id,
                   snapshot.from_addr, snapshot.to_addr, snapshot.reply_to,
                   snapshot.in_reply_to, snapshot.references_header,
                   snapshot.subject, snapshot.body_text, snapshot.reserved_at
              FROM outbound_email_snapshots AS snapshot
              JOIN email_messages AS em ON em.id = snapshot.email_id
             WHERE em.id = %s AND em.run_id = %s AND em.direction = 'outbound'
            """
            + lock_sql,
            (str(email_id), str(run_id)),
        )
        snapshot = cur.fetchone()
        if snapshot is None:
            return None
        cur.execute(
            """
            SELECT id, ordinal, filename, content
              FROM outbound_email_attachments
             WHERE snapshot_id = %s
             ORDER BY ordinal ASC
            """,
            (str(snapshot["snapshot_id"]),),
        )
        snapshot["attachments"] = cur.fetchall() or []
    return snapshot


def reserve_outbound_snapshot(
    *,
    run_id: uuid.UUID,
    purpose: str,
    round: int,
    message_id: str,
    from_addr: str,
    to_addr: str,
    reply_to: str | None,
    in_reply_to: str | None,
    references_header: str | None,
    subject: str,
    body_text: str,
    attachments: Sequence[tuple[str, bytes]],
    conn: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Read or atomically reserve the provider-ready snapshot for one slot.

    The reservation freezes every provider-visible field and byte before a provider
    call. A retry locks and returns this stored record unchanged, never applying its
    caller arguments. Supplying ``conn`` keeps the reservation inside the
    caller-owned transaction with its job enqueue; this function opens a transaction
    only when it owns the connection.
    """
    if purpose not in ("clarification", "confirmation", "clarification_field_regression"):
        raise ValueError(f"unsupported outbound purpose: {purpose!r}")
    if round < 0:
        raise ValueError("round must be non-negative")

    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        # We cannot know an email_id until the absent branch inserts it, so first lock
        # by the unique logical send-slot identity.  The conflict re-read below closes
        # the concurrent absent-branch race without ever writing EXCLUDED content.
        with c.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(
                """
                SELECT em.id AS email_id
                  FROM email_messages AS em
                 WHERE em.run_id = %s AND em.direction = 'outbound'
                   AND em.purpose = %s AND em.round = %s
                   AND em.epoch = (SELECT reply_epoch FROM payroll_runs WHERE id = %s)
                 FOR UPDATE
                """,
                (str(run_id), purpose, round, str(run_id)),
            )
            existing = cur.fetchone()

        if existing is not None:
            snapshot = _load_outbound_snapshot_locked(
                c, run_id=run_id, email_id=uuid.UUID(str(existing["email_id"])), lock=True
            )
            if snapshot is None:
                raise RuntimeError("outbound logical slot exists without a frozen snapshot")
            return snapshot

        row = c.execute(
            """
            INSERT INTO email_messages (
                run_id, direction, message_id, in_reply_to, references_header,
                subject, from_addr, to_addr, body_text, purpose, send_state, round, epoch
            ) VALUES (%s, 'outbound', %s, %s, %s, %s, %s, %s, %s, %s, 'reserved', %s,
                      (SELECT reply_epoch FROM payroll_runs WHERE id = %s))
            ON CONFLICT (run_id, purpose, round, epoch) DO NOTHING
            RETURNING id
            """,
            (
                str(run_id),
                message_id,
                in_reply_to,
                references_header,
                subject,
                from_addr,
                to_addr,
                body_text,
                purpose,
                round,
                str(run_id),
            ),
        ).fetchone()

        if row is None:
            with c.cursor(row_factory=psycopg.rows.dict_row) as cur:
                cur.execute(
                    """
                    SELECT id AS email_id FROM email_messages
                     WHERE run_id = %s AND direction = 'outbound' AND purpose = %s
                       AND round = %s
                       AND epoch = (SELECT reply_epoch FROM payroll_runs WHERE id = %s)
                     FOR UPDATE
                    """,
                    (str(run_id), purpose, round, str(run_id)),
                )
                existing = cur.fetchone()
            if existing is None:
                raise RuntimeError("outbound logical-slot conflict could not be re-read")
            snapshot = _load_outbound_snapshot_locked(
                c, run_id=run_id, email_id=uuid.UUID(str(existing["email_id"])), lock=True
            )
            if snapshot is None:
                raise RuntimeError("outbound logical slot exists without a frozen snapshot")
            return snapshot

        email_id = uuid.UUID(str(row[0]))
        snapshot_row = c.execute(
            """
            INSERT INTO outbound_email_snapshots (
                email_id, message_id, from_addr, to_addr, reply_to, in_reply_to,
                references_header, subject, body_text
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                str(email_id),
                message_id,
                from_addr,
                to_addr,
                reply_to,
                in_reply_to,
                references_header,
                subject,
                body_text,
            ),
        ).fetchone()
        if snapshot_row is None:
            raise RuntimeError("outbound snapshot insert did not return an id")
        snapshot_id = uuid.UUID(str(snapshot_row[0]))
        for ordinal, (filename, content) in enumerate(attachments):
            c.execute(
                """
                INSERT INTO outbound_email_attachments (snapshot_id, ordinal, filename, content)
                VALUES (%s, %s, %s, %s)
                """,
                (str(snapshot_id), ordinal, filename, bytes(content)),
            )

        snapshot = _load_outbound_snapshot_locked(c, run_id=run_id, email_id=email_id, lock=True)
        if snapshot is None:
            raise RuntimeError("new outbound snapshot could not be loaded")
        return snapshot


def load_outbound_snapshot(
    run_id: uuid.UUID,
    email_id: uuid.UUID,
    conn: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Load the one owned, frozen provider payload for a replay handler."""
    with _conn_ctx(conn) as (c, _owns):
        return _load_outbound_snapshot_locked(c, run_id=run_id, email_id=email_id, lock=False)


def load_delivery_review_snapshot(
    run_id: uuid.UUID,
    email_id: uuid.UUID,
    conn: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Return bounded review facts without frozen body or provider payloads.

    The delivery-review projection is intentionally smaller than
    ``load_outbound_snapshot``.  Review callers receive only the facts needed to
    explain the delivery state and references to the frozen attachments; the
    authorized frozen-artifact route owns the separate body reader.
    """
    with _conn_ctx(conn) as (c, _owns), c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            """
            SELECT em.id AS email_id, snapshot.id AS snapshot_id, em.purpose,
                   snapshot.message_id, snapshot.to_addr, snapshot.subject,
                   snapshot.reserved_at,
                   (SELECT count(*) FROM outbound_delivery_attempts AS attempt
                     WHERE attempt.snapshot_id = snapshot.id) AS attempt_count
              FROM outbound_email_snapshots AS snapshot
              JOIN email_messages AS em ON em.id = snapshot.email_id
             WHERE em.id = %s AND em.run_id = %s AND em.direction = 'outbound'
            """,
            (str(email_id), str(run_id)),
        )
        review = cur.fetchone()
        if review is None:
            return None
        cur.execute(
            """
            SELECT id, ordinal, filename
              FROM outbound_email_attachments
             WHERE snapshot_id = %s
             ORDER BY ordinal ASC
            """,
            (str(review["snapshot_id"]),),
        )
        review["attachments"] = cur.fetchall() or []
    return review


def load_snapshot_attachment(
    run_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    attachment_id: uuid.UUID,
    conn: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Read one exact attachment byte record, scoped to its owning run/snapshot."""
    with _conn_ctx(conn) as (c, _owns), c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            """
            SELECT attachment.filename, attachment.content
              FROM outbound_email_attachments AS attachment
              JOIN outbound_email_snapshots AS snapshot ON snapshot.id = attachment.snapshot_id
              JOIN email_messages AS em ON em.id = snapshot.email_id
             WHERE attachment.id = %s AND attachment.snapshot_id = %s
               AND em.run_id = %s AND em.direction = 'outbound'
            """,
            (str(attachment_id), str(snapshot_id), str(run_id)),
        )
        return cur.fetchone()


def get_outbound_message_id(
    run_id: uuid.UUID,
    purpose: str,
    conn: psycopg.Connection | None = None,
) -> str | None:
    """Purpose-aware, current-epoch, send_state-filtered Message-ID lookup.

    Only a row with purpose=X AND send_state='sent' in the run's current reply epoch
    counts as proof-of-delivery. A reserved (pre-send intent, pre-crash) or failed
    row does NOT match — otherwise the delivery guard would read a crashed send as a
    completed one and skip a required email. Historical sent rows remain in the
    append-only audit, but a human retriggered epoch must not treat one as proof for
    the newly authorized confirmation.

    Raises ValueError on an unrecognised purpose value: the guard exists so a caller
    cannot accidentally make a purpose-blind lookup and match the wrong email.
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
              AND epoch = (SELECT reply_epoch FROM payroll_runs WHERE id = %s)
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(run_id), purpose, str(run_id)),
        ).fetchone()
    return row[0] if row else None


def get_outbound_for_round(
    run_id: uuid.UUID,
    purpose: str,
    round: int,
    conn: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Round-aware, send_state-filtered outbound row lookup.

    Same shape as get_outbound_message_id — the invalid-purpose guard and the
    `send_state = 'sent'` proof-of-delivery filter are both preserved — with an
    added `round` filter. Returns a dict (not just the message_id) so callers can
    read the FOUND ROW's round back: the idempotent next round must always be
    derived from this row (`row["round"] + 1`), never from a blind `round + 1` on
    the caller's own counter. Crash-safety of the round increment depends on
    re-deriving it from what was actually sent.

    Scoped to the run's CURRENT epoch via a correlated subquery on the same run_id
    parameter (no extra function parameter). A stale pre-retrigger round-0 row
    belongs to epoch 0 while a retriggered run sits at epoch 1, so this query
    cannot see it — without the epoch filter the guard would read that stale row
    as proof the new question was already asked and silently suppress the send.

    Raises ValueError on an unrecognised purpose value (same guard as
    get_outbound_message_id).
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


def get_unconfirmed_outbound(
    run_id: uuid.UUID,
    *,
    purpose: str,
    round: int = 0,
    conn: psycopg.Connection | None = None,
) -> dict[str, Any] | None:
    """Epoch-scoped read of an UNCONFIRMED outbound reservation for this send slot.

    Complementary to get_outbound_message_id / get_outbound_for_round, never a
    replacement for either. Those two answer "was this message PROVEN sent?" — only a
    send_state='sent' row counts, and finding one means the send is safe to skip and the
    run can finalize. This function answers a DIFFERENT question: "might this message
    already have reached the provider?" A 'reserved' row means a caller wrote
    intent-to-send, called the provider, and has not yet recorded the outcome — the
    provider may have already accepted the message. A 'failed' row means the send raised
    an exception, but that exception can be a timeout AFTER the provider already
    accepted the mail, so 'failed' is not proof of non-delivery either. Neither state
    tells the caller the message was NOT delivered, so a caller that finds a row here
    must not send again — it must refuse and let a human decide.

    Do not widen get_outbound_message_id / get_outbound_for_round to also match
    'reserved'/'failed' instead of adding a function like this one. That would make a
    crashed send look identical to a completed one and skip a required email entirely.
    The two guards are deliberately asymmetric and fail in OPPOSITE directions: the
    proven-sent guards skip on a false-negative risk (a sent row missed means an
    unwanted duplicate); this one blocks on a false-positive risk (an unconfirmed row
    found means a possible duplicate is refused). Merging the two collapses that
    asymmetry and reintroduces the bug either guard alone exists to close.

    EPOCH SCOPING IS THE SAFETY PROPERTY THIS FUNCTION EXISTS TO EXPRESS, not an
    incidental filter. An automatic reclaim of a stranded run never bumps the run's
    reply epoch, so a rewound run stays inside the epoch this function reads — the
    unconfirmed row stays visible and the rerun stays blocked. Only a human-triggered
    context clear bumps the epoch, opening a fresh send slot this function cannot see
    the stale reservation through. That asymmetry is intentional: the machine may never
    grant itself a licence to send a possible duplicate; a human, having inspected the
    situation, may. Dropping the epoch filter here would make every escalated run
    permanently stuck with no way for a human to clear it — trading one bug for a worse
    one.

    The (run_id, purpose, round, epoch) filter is not an arbitrary key: it is exactly
    the send-slot identity insert_email_message's own upsert arbitrates on, and exactly
    the columns the table's own uniqueness constraint declares. Keep this function's
    filter and that arbiter in agreement — the same invariant insert_email_message's own
    docstring pins for itself.

    A caller of this function is expected to keep the detection predicate stable and
    only widen what it DOES about a match — from unconditional refusal today, to a
    provably-safe replay of the same reservation when a replay window still allows it,
    falling back to refusal outside that window. This function's job stays "detect a
    possible duplicate", never "decide what to do about it".

    Raises ValueError on an unrecognised purpose value — same guard as its two siblings,
    so a purpose-blind lookup can never accidentally match the wrong kind of email (a
    confirmation blocked by a crashed clarification, or the reverse).
    """
    if purpose not in ("clarification", "confirmation", "clarification_field_regression"):
        raise ValueError(
            "purpose must be 'clarification', 'confirmation', or "
            f"'clarification_field_regression', got {purpose!r}"
        )
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            """
            SELECT id, message_id, send_state, round, created_at FROM email_messages
            WHERE run_id = %s AND direction = 'outbound'
              AND purpose = %s AND round = %s
              AND epoch = (SELECT reply_epoch FROM payroll_runs WHERE id = %s)
              AND send_state IN ('reserved', 'failed')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(run_id), purpose, round, str(run_id)),
        ).fetchone()
    if row is None:
        return None
    return {
        "email_id": uuid.UUID(str(row[0])),
        "message_id": row[1],
        "send_state": row[2],
        "round": row[3],
        "created_at": row[4],
    }


def mark_reply_consumed(
    message_id: str,
    round: int,
    conn: psycopg.Connection | None = None,
) -> None:
    """Write-once marker: this inbound reply has been consumed at `round`.

    `consumed_round IS NULL` in the WHERE clause makes this write-once — a second
    call (e.g. a webhook redelivery re-scheduling the same message_id) is a silent
    no-op rather than overwriting an already-consumed row with a later round.
    Restricted to direction='inbound' so an outbound row can never be marked
    consumed.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        c.execute(
            "UPDATE email_messages SET consumed_round = %s"
            " WHERE message_id = %s AND direction = 'inbound' AND consumed_round IS NULL",
            (round, message_id),
        )


def load_consumed_replies(
    run_id: uuid.UUID, conn: psycopg.Connection | None = None
) -> list[dict[str, Any]]:
    """Return all consumed inbound replies for a run, round-ordered.

    Same dict_row multi-row shape as load_thread_messages. Filters to
    direction='inbound' AND consumed_round IS NOT NULL, ordered by consumed_round
    ASC so the accumulated-context builder renders every consumed reply in the
    order it was actually processed (not insertion order, which can differ under
    redelivery/retry).

    Scoped to the run's CURRENT epoch via a correlated subquery: a consumed reply
    from a pre-retrigger epoch is invisible to post-retrigger accumulation, so no
    hours from a conversation that no longer exists can leak into the payroll the
    operator approves. The row itself is never deleted — the log stays append-only.
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


def get_inbound_by_message_id(
    message_id: str, conn: psycopg.Connection | None = None
) -> dict[str, Any] | None:
    """Load the PERSISTED inbound row by its RFC message_id.

    A redelivered webhook must resume from the row already written at first ingest
    (cleaned body_text, its linked run_id, consumed_round) — NEVER rebuild an
    InboundEmail from the redelivered request body, which would re-clean/re-parse
    and could diverge from what was actually processed.

    The column list is the FULL InboundEmail field set so `_row_to_inbound` can
    build a valid InboundEmail (extra="forbid") from this row with no second
    lookup.
    """
    with _conn_ctx(conn) as (c, _owns), c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT id, run_id, message_id, in_reply_to, references_header,"
            " subject, body_text, from_addr, to_addr, consumed_round, created_at"
            " FROM email_messages WHERE message_id = %s AND direction = 'inbound'",
            (message_id,),
        )
        return cur.fetchone()


def get_inbound_email_by_id(
    email_id: uuid.UUID, conn: psycopg.Connection | None = None
) -> dict[str, Any] | None:
    """Load one persisted inbound row by its durable database identifier."""
    with _conn_ctx(conn) as (c, _owns), c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            "SELECT id, run_id, message_id, in_reply_to, references_header,"
            " subject, body_text, from_addr, to_addr, consumed_round, created_at"
            " FROM email_messages WHERE id = %s AND direction = 'inbound'",
            (str(email_id),),
        )
        return cur.fetchone()


def update_email_message_sent(message_id: str, conn: psycopg.Connection | None = None) -> None:
    """Flip send_state to 'sent' for the outbound row keyed on SYNTHETIC message_id.

    The WHERE key is the SYNTHETIC message_id minted by send_outbound, NEVER the
    email provider's own id — the provider id is not stored, so keying on it would
    match nothing and leave the row stuck in 'reserved'.

    Only the constrained outbound reserved-to-sent transition is supported here.
    The durable delivery settlement path owns all other state transitions.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        row = c.execute(
            "UPDATE email_messages SET send_state = 'sent' "
            "WHERE message_id = %s AND direction = 'outbound' "
            "AND send_state = 'reserved' RETURNING id",
            (message_id,),
        ).fetchone()
        if row is None:
            raise ValueError(
                "email message is not an outbound row in the reserved state"
            )


def update_email_message_state(
    message_id: str,
    state: str,
    conn: psycopg.Connection | None = None,
) -> None:
    """Retired compatibility seam; arbitrary email state writes are forbidden.

    This symbol remains importable for older integrations, but it fails before
    opening a connection or issuing SQL.  ``update_email_message_sent`` is the only
    compatibility transition retained, and it is constrained to outbound reserved
    rows.  Durable settlement writes are deliberately owned by the fenced job path.
    """
    del message_id, state, conn
    raise RuntimeError(
        "update_email_message_state is retired; use fenced delivery settlement"
    )


def get_outbound_references_chain(
    run_id: uuid.UUID, conn: psycopg.Connection | None = None
) -> str | None:
    """Return the references_header of the most-recent sent outbound row for this run.

    gateway.send_outbound calls this BEFORE the reserved INSERT to load the prior
    accumulated References chain, then appends the new in_reply_to token. Building
    the chain from DB state rather than from ephemeral webhook state is what makes
    threading survive dropped or duplicated deliveries.

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


def load_outbound_emails(
    run_id: uuid.UUID, conn: psycopg.Connection | None = None
) -> list[dict[str, Any]]:
    """Read all outbound email rows for a run (run-detail sent-emails section).

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


def load_thread_messages(
    run_id: uuid.UUID, conn: psycopg.Connection | None = None
) -> list[dict[str, Any]]:
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

    The header-chain match must compare WHOLE angle-bracketed Message-ID tokens,
    not bare substrings. A References header is RFC-5322 whitespace-separated
    `<id>` tokens; we collapse any run of whitespace (spaces/tabs/folded CRLF) to
    one space and pad both ends with a space, so the SQL can match ` <id> ` as a
    whitespace-bounded token. This stops a stored Message-ID that is a substring of
    another (or of arbitrary attacker-supplied References text) from false-matching
    and routing a reply onto the wrong run: ` <a@x> ` cannot appear inside
    ` <a@xtra> `. Stored synthetic IDs are `<uuid4@payroll-agent.local>`, i.e.
    angle-bracketed whole tokens. Returns " " for an absent/empty header, which
    matches nothing — never the empty-substring trap, where "" would match every row.
    """
    if not references_header:
        return " "
    return " " + " ".join(references_header.split()) + " "


# The shared, anchored header-chain predicate. Both finders use the SAME SQL so the
# resume lookup and the late-reply observability lookup can never diverge on which
# run a reply belongs to. `em.message_id` already carries its surrounding `<...>`;
# padding the references string with spaces (via _pad_references) and the pattern
# with ` `/` ` makes this a whitespace-bounded WHOLE-token comparison, not an
# unanchored substring match.
# Both placeholders stay NAMED — never string-interpolated (SQL injection).
_HEADER_MATCH_PREDICATE = (
    "( em.message_id = %(in_reply_to)s OR %(references)s LIKE '%% ' || em.message_id || ' %%' )"
)


def find_awaiting_reply_for_header(
    *,
    in_reply_to: str | None,
    references_header: str | None,
    conn: psycopg.Connection | None = None,
) -> uuid.UUID | None:
    """Match a current-epoch reply to its run, restricted to awaiting_reply.

    Scans the stored outbound Message-ID against the reply's In-Reply-To AND the
    full References chain. The outbound row must carry the run's current
    ``reply_epoch``; older rows remain available only to the separate any-status
    observability lookup. The `references` match is a NAMED placeholder, never
    string-interpolated, and is anchored on whole tokens.
    """
    sql = (
        "SELECT pr.id FROM payroll_runs pr"
        " JOIN email_messages em ON em.run_id = pr.id AND em.direction = 'outbound'"
        " WHERE pr.status = 'awaiting_reply'"
        "   AND em.epoch = pr.reply_epoch"
        "   AND " + _HEADER_MATCH_PREDICATE + " LIMIT 1"
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
    *,
    in_reply_to: str | None,
    references_header: str | None,
    conn: psycopg.Connection | None = None,
) -> uuid.UUID | None:
    """The SAME header match as find_awaiting_reply_for_header, across ANY status.

    A header match to an already-sent/reconciled run is observable as a late reply
    rather than silently dropped. Named placeholders only; whole-token anchored.
    """
    sql = (
        "SELECT pr.id FROM payroll_runs pr"
        " JOIN email_messages em ON em.run_id = pr.id AND em.direction = 'outbound'"
        " WHERE " + _HEADER_MATCH_PREDICATE + " LIMIT 1"
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
