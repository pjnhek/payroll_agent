"""DB repo — JSONB pipeline-state persistence (extracted/decision/line-items/
clarify-round context)."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, cast

import psycopg

from app.db.repo._shared import _conn_ctx, _nulltx
from app.models.contracts import (
    ClarifiedFields,
    Decision,
    Extracted,
    HoursChange,
    PaystubLineItem,
)
from app.models.roster import NameMatchResult

logger = logging.getLogger("payroll_agent.repo")


def persist_extracted(
    run_id: uuid.UUID,
    extracted: Extracted,
    conn: psycopg.Connection | None = None,
) -> None:
    """Write the Extracted JSONB + the run's pay-period columns (no status — the
    orchestrator advances state).

    pay_period_start/end are populated on the run row as well as inside the JSONB:
    they exist on payroll_runs precisely so the dashboard and queries can read them
    off the row without unpacking JSONB. Writing only the JSONB leaves them NULL and
    every such reader blind.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
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


def persist_decision(
    run_id: uuid.UUID,
    decision: Decision,
    conn: psycopg.Connection | None = None,
) -> None:
    """Write the Decision JSONB ONLY.

    Takes NO final_status argument: persistence helpers never own status
    transitions. The orchestrator calls set_status SEPARATELY after persisting the
    decision, keeping the state machine's writers countable.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        c.execute(
            "UPDATE payroll_runs SET decision = %s, updated_at = now() WHERE id = %s",
            (json.dumps(decision.model_dump(mode="json")), str(run_id)),
        )


def persist_reconciliation(
    run_id: uuid.UUID,
    matches: list[NameMatchResult],
    conn: psycopg.Connection | None = None,
) -> None:
    """Write the per-run list[NameMatchResult] JSONB ONLY (no status).

    The deterministic NameMatchResult shape (source/resolved) carries no score, so
    the persisted JSONB is structurally free of any per-name confidence value —
    there is nothing for a later reader to mistake for one. This JSONB is the only
    write path for name matches; there is no parallel relational table.
    """
    payload = [m.model_dump(mode="json") for m in matches]
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        c.execute(
            "UPDATE payroll_runs SET reconciliation = %s, updated_at = now() WHERE id = %s",
            (json.dumps(payload), str(run_id)),
        )


def replace_line_items(
    run_id: uuid.UUID,
    items: list[PaystubLineItem],
    conn: psycopg.Connection | None = None,
) -> None:
    """Replace all paystub_line_items for a run (DELETE-by-run then insert).

    The idempotency invariant: a re-trigger / resume re-computes wholesale rather
    than appending. Without the DELETE, a second pass would leave the run holding
    two sets of paystubs and double its reconciled total.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
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
    candidates: dict[str, Any],
    conn: psycopg.Connection | None = None,
) -> None:
    """MERGE candidates into the payroll_runs.alias_candidates JSONB column.

    Alias candidates live in their OWN column, not as a key inside the
    reconciliation JSONB, so persist_reconciliation on resume can never overwrite
    them.

    This is a MERGE, not an assignment, and it must stay one. A full-column
    overwrite (`alias_candidates = %s`) is wrong once a run has 2+ distinct tokens
    across 2+ rounds: the last writer erases every OTHER token's candidate, so a
    client-confirmed bind from an earlier round can be silently wiped by a later,
    unrelated capture/suggest/bind write before `_write_aliases_if_safe` ever reads
    it at the approval gate — and the system quietly fails to learn.

    `COALESCE(alias_candidates, '{}'::jsonb)` handles a NULL starting column (a run
    that has never captured a candidate) without erroring on `NULL || jsonb`. `||`
    leaves every key absent from the new `candidates` dict untouched and overwrites
    only the keys the caller passed — exactly what each caller needs: `_clarify`'s
    capture writes ONE new token key, the bind step updates the SAME tokens it read,
    and `/resolve`'s remember-checkbox writes the tokens it validated. A caller that
    reads the full dict and passes a REDUCED copy back is still correct under merge
    semantics.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        c.execute(
            "UPDATE payroll_runs SET alias_candidates = "
            "COALESCE(alias_candidates, '{}'::jsonb) || %s::jsonb, "
            "updated_at = now() WHERE id = %s",
            (json.dumps(candidates), str(run_id)),
        )


def set_pre_clarify_extracted(
    run_id: uuid.UUID,
    extracted: Extracted,
    conn: psycopg.Connection | None = None,
) -> bool:
    """Snapshot the pre-clarify extracted data, write-once.

    A CAS UPDATE (`WHERE id = %s AND pre_clarify_extracted IS NULL RETURNING id`)
    makes the check-and-write atomic, so the snapshot is captured ONLY on the first
    call. This is the original, pre-clarification money data — a second write would
    overwrite it with post-clarification values, and the carry-forward backfill
    would then "restore" the very field the client dropped. Later calls are
    idempotent no-ops.

    Must be called BEFORE every set_status(AWAITING_REPLY) path in _clarify.

    Returns True if written (first write), False if already set.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        row = c.execute(
            "UPDATE payroll_runs SET pre_clarify_extracted = %s, updated_at = now()"
            " WHERE id = %s AND pre_clarify_extracted IS NULL RETURNING id",
            (json.dumps(extracted.model_dump(mode="json")), str(run_id)),
        ).fetchone()
    return row is not None


def load_pre_clarify_extracted(
    run_id: uuid.UUID,
    conn: psycopg.Connection | None = None,
) -> Extracted | None:
    """Load the pre-clarify extraction snapshot.

    Returns None if the column is NULL (no snapshot taken yet — first resume or
    non-field-regression run). Deserializes via Extracted.model_validate.
    """
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            "SELECT pre_clarify_extracted FROM payroll_runs WHERE id = %s",
            (str(run_id),),
        ).fetchone()
    if row is None or row[0] is None:
        return None
    data = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    return Extracted.model_validate(data)


def set_clarified_fields(
    run_id: uuid.UUID,
    clarified: dict[str, Any],
    conn: psycopg.Connection | None = None,
) -> None:
    """Write the clarified_fields JSONB column, typed-on-write.

    The shape is validated through ClarifiedFields BEFORE persisting, because these
    labels drive money. A carried_forward mislabeled as confirmed_dropped silently
    UNDERPAYS (the snapshot value is never restored); the reverse silently OVERPAYS
    (a field the client explicitly zeroed gets backfilled again). Typing the write
    means an invalid outcome string fails here, not on a paystub.

    Four outcomes:
    - asked — question sent, awaiting the client's reply.
    - carried_forward — client stayed silent (the RAW reply had the field absent or
      None), so the original value is restored from the pre-clarify snapshot. This
      does NOT mean the client re-supplied the same value.
    - confirmed_dropped — client explicitly zeroed/removed the field. Protected from
      re-backfill even though _is_paid(Decimal('0')) is False; without this guard the
      snapshot would refill it and overpay.
    - client_supplied — client sent a positive replacement (present in the raw reply
      before any backfill).

    Raises pydantic.ValidationError if the shape is wrong (any invalid outcome string).
    """
    # Validate through ClarifiedFields before serializing.
    ClarifiedFields(outcomes=clarified)
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        c.execute(
            "UPDATE payroll_runs SET clarified_fields = %s, updated_at = now() WHERE id = %s",
            (json.dumps(clarified), str(run_id)),
        )


def load_clarified_fields(
    run_id: uuid.UUID,
    conn: psycopg.Connection | None = None,
) -> dict[str, Any]:
    """Load the clarified_fields JSONB column.

    Returns {} on NULL (no field-regression outcomes yet — first resume or
    non-field-regression run). Deserializes via json.loads.
    """
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            "SELECT clarified_fields FROM payroll_runs WHERE id = %s",
            (str(run_id),),
        ).fetchone()
    if row is None or row[0] is None:
        return {}
    return (
        cast(dict[str, Any], json.loads(row[0]))
        if isinstance(row[0], str)
        else cast(dict[str, Any], row[0])
    )


def set_hours_changes(
    run_id: uuid.UUID,
    changes: list[HoursChange],
    conn: psycopg.Connection | None = None,
) -> None:
    """Write the hours_changes JSONB column. DATA-ONLY — it never writes status.

    The cross-round paid->paid hours CHANGES the operator must see before approving the
    money (regular 20 -> 40, overtime 10 -> 2). The orchestrator calls this
    UNCONDITIONALLY inside its persist transaction — including with an empty list — so a
    stale value from a dead attempt cannot survive into a run the operator is looking at.
    "No changes" is a fact worth writing, not an absence of one.

    DISPLAY-ONLY by type: HoursChange has no `issue_type`, so nothing written here can be
    promoted to a ValidationIssue or reach decide(). See app/models/contracts.HoursChange.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        c.execute(
            "UPDATE payroll_runs SET hours_changes = %s, updated_at = now() WHERE id = %s",
            (
                json.dumps([ch.model_dump(mode="json") for ch in changes]),
                str(run_id),
            ),
        )


def get_clarification_round(
    run_id: uuid.UUID, conn: psycopg.Connection | None = None
) -> int:
    """Read payroll_runs.clarification_round. Returns 0 if the row is missing.

    The column defaults to 0 for every run, so a run that has never been through a
    clarification round reads as round 0 rather than NULL.
    """
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            "SELECT clarification_round FROM payroll_runs WHERE id = %s",
            (str(run_id),),
        ).fetchone()
    if row is None or row[0] is None:
        return 0
    return int(row[0])


def set_clarification_round(
    run_id: uuid.UUID,
    value: int,
    conn: psycopg.Connection | None = None,
) -> None:
    """Write payroll_runs.clarification_round.

    Caller-joinable transaction (same shape as link_email_to_run) so `_clarify`'s
    finalize path can write the round in the SAME transaction as
    set_status(AWAITING_REPLY). The status advance goes last: a crash between the
    two must leave the run un-advanced rather than parked in awaiting_reply with a
    round counter that never got written.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        c.execute(
            "UPDATE payroll_runs SET clarification_round = %s, updated_at = now() WHERE id = %s",
            (value, str(run_id)),
        )


def clear_reply_context(
    run_id: uuid.UUID, conn: psycopg.Connection | None = None
) -> None:
    """Null ALL reply-round context on a run in one statement.

    Context lost means ALL of it: the pre-clarify snapshot, the field-regression
    outcomes, the round counter, the recorded cross-round hours CHANGES AND the
    suggestion/candidate state are cleared together. A retrigger that wiped only some of
    these would leave the round machine (or the alias-suggestion state) referencing a
    conversation that no longer exists — and hours_changes IS reply-round context: it is a
    diff BETWEEN rounds, so a surviving record would show the operator a change belonging
    to a conversation the retrigger just destroyed. Caller-joinable transaction, so the
    retrigger route can clear strictly AFTER a winning claim_status, in the transaction
    that commits before the pipeline is re-scheduled.

    The statement ALSO bumps reply_epoch = reply_epoch + 1, and that bump is
    load-bearing. This function does NOT touch email_messages — the audit log is
    append-only by design — so after a retrigger the run's PRIOR round-0 'sent'
    outbound row and any consumed reply rows are still sitting there, while
    clarification_round has been reset to 0. Without the epoch bump:
    - the retriggered run's first clarification would find the stale round-0 'sent'
      row, read it as proof the question was already asked, and silently suppress
      the send — parking the run at awaiting_reply with no email out;
    - a resume would re-accumulate a stale consumed reply from the dead
      conversation into the new run's context — hours from a payroll the client
      never re-submitted, i.e. a mispay.

    The bump gives every round-machine read (get_outbound_for_round,
    load_consumed_replies, find_stranded_unconsumed_replies) a scope boundary that
    the retrigger crosses but no stale row can. The historical rows stay fully
    queryable — just invisible to the CURRENT epoch's reads.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        c.execute(
            "UPDATE payroll_runs SET clarified_fields = NULL, pre_clarify_extracted = NULL,"
            " clarification_round = 0, alias_candidates = NULL, hours_changes = NULL,"
            " reply_epoch = reply_epoch + 1, updated_at = now()"
            " WHERE id = %s",
            (str(run_id),),
        )


def update_known_alias(
    employee_id: uuid.UUID,
    new_alias: str,
    conn: psycopg.Connection | None = None,
) -> bool:
    """Idempotently append new_alias to employees.known_aliases.

    PRECONDITION: the caller MUST have already passed _safe_to_learn_alias(). This
    function does NOT re-check for collisions — it only deduplicates the array. An
    alias learned onto the wrong employee silently misroutes that person's pay on
    every future run.

    The conditional `NOT (%s = ANY(known_aliases))` in the WHERE clause appends only
    when the alias is absent, so calling twice cannot double-add. Returns True if
    the alias was actually added, False if it was already present.

    employees.known_aliases is a native TEXT[], so this uses array operators
    (unnest / ANY) — NOT the JSONB ops (to_jsonb / jsonb_agg /
    jsonb_array_elements_text / @>), which would fail against this column type.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
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
