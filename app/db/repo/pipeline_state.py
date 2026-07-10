"""DB repo — JSONB pipeline-state persistence (extracted/decision/line-items/
clarify-round context)."""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, cast

import psycopg

from app.db.repo._shared import _conn_ctx, _nulltx
from app.models.contracts import ClarifiedFields, Decision, Extracted, PaystubLineItem
from app.models.roster import NameMatchResult

logger = logging.getLogger("payroll_agent.repo")


def persist_extracted(
    run_id: uuid.UUID,
    extracted: Extracted,
    conn: psycopg.Connection | None = None,
) -> None:
    """Write the Extracted JSONB + the run's pay-period columns (no status — the
    orchestrator advances state). The pay_period_start/end run columns were left null
    before (review fix): they exist on payroll_runs for the dashboard/queries to read
    off the run row, so populate them from the extraction rather than only the JSONB."""
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

    Takes NO final_status argument (FIX B): persistence helpers never own status
    transitions. The orchestrator calls set_status SEPARATELY to advance state
    after persisting the decision.
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
    """Write the per-run list[NameMatchResult] JSONB ONLY (D-A3-05; no status).

    The deterministic NameMatchResult shape (source/resolved) carries no score, so
    the persisted JSONB is automatically free of any per-name confidence; there is no
    separate name_matches relational write path (dropped in Phase 2.1, D-21-06).
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
    than appending duplicates (RESEARCH Pattern 6 invariant 2).
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
    """MERGE candidates into payroll_runs.alias_candidates JSONB column (D-04, WR-1 fix).

    Separate column (not a key in reconciliation JSONB) so it is NEVER overwritten
    by persist_reconciliation on resume (RESEARCH Open Question #1, D-04 decision).

    WR-1 (11-REVIEW.md): this was a full-column overwrite
    (`alias_candidates = %s`). With 2+ distinct tokens across 2+ rounds, the
    last writer erased every OTHER token's candidate — a client-confirmed
    bind from an earlier round (or an earlier call in the same round) could
    be silently wiped by a later, unrelated capture/suggest/bind write before
    `_write_aliases_if_safe` ever read it at the approval gate.

    The fix: a JSONB `||` merge. `COALESCE(alias_candidates, '{}'::jsonb)`
    handles a NULL starting column (a run that has never captured any
    candidate yet) without erroring on `NULL || jsonb`. `||` keeps every key
    NOT present in the new `candidates` dict untouched, and overwrites only
    the keys the caller passed — exactly the semantics every existing caller
    needs: `_clarify`'s capture writes ONE new token key, STEP C's bind
    writes updates for the SAME tokens it read, and `/resolve`'s
    remember-checkbox writes the tokens it validated. A caller that reads the
    full existing dict and passes a REDUCED copy back is still correct and
    backward-compatible under merge semantics — merging a full dict into
    itself is a no-op for unrelated keys and a correct update for its own.
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
    """Snapshot the pre-clarify extracted data (IS NULL write-once guard, D-19 MONEY-03).

    Uses a CAS UPDATE with `WHERE id = %s AND pre_clarify_extracted IS NULL RETURNING id`
    — atomic check-and-write so the snapshot is written ONLY ONCE on the first call.
    Subsequent calls return False (idempotent no-op). Called BEFORE each of the
    three set_status(AWAITING_REPLY) paths in _clarify (N7 fix).

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
    """Load the pre-clarify extraction snapshot (D-19 MONEY-03).

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
    """Write the clarified_fields JSONB column (D-13 MONEY-03, D-7.5-03b typed-on-write).

    D-7.5-03b: shape validated through ClarifiedFields before persisting — a mislabeled
    carried_forward->confirmed_dropped silently underpays. Four outcomes:
    - asked (awaiting reply)
    - carried_forward (client silent; value from snapshot; RAW reply had None/absent —
      D-7.5-10b/D-7.5-11; does NOT mean client resupplied the same value)
    - confirmed_dropped (explicit zero/none from client; protected from re-backfill
      even though _is_paid(Decimal('0')) is False — D-7.5-11 overpay guard)
    - client_supplied (positive replacement from client — raw reply had the value
      before backfill; NOT same-value resupply mislabeled)

    Raises pydantic.ValidationError if the shape is wrong (any invalid outcome string).
    """
    # D-7.5-03b: validate through ClarifiedFields before serializing.
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
    """Load the clarified_fields JSONB column (D-13 MONEY-03).

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


def get_clarification_round(
    run_id: uuid.UUID, conn: psycopg.Connection | None = None
) -> int:
    """Read payroll_runs.clarification_round (D-11-01). Returns 0 if row missing.

    Zero behavior change in Plan 11-01: nothing calls this yet — the round-guard
    orchestrator work lands in a later plan. The column defaults to 0 for every
    run (old and new), so a caller reading it before that later plan wires the
    increment always sees the pre-Phase-11 value (0).
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
    """Write payroll_runs.clarification_round (D-11-01).

    Caller-joinable transaction (copy of link_email_to_run's shape) so a later
    plan's `_clarify` finalize path can write this in the SAME transaction as
    set_status(AWAITING_REPLY) (D-9-02: status-advance-last).
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        c.execute(
            "UPDATE payroll_runs SET clarification_round = %s, updated_at = now() WHERE id = %s",
            (value, str(run_id)),
        )


def clear_reply_context(
    run_id: uuid.UUID, conn: psycopg.Connection | None = None
) -> None:
    """Null ALL reply-round context on a run in one statement (D-11-04).

    "Context lost means ALL of it": the pre-clarify snapshot, the field-
    regression outcomes, the round counter, AND the suggestion/candidate state
    are cleared together — a retrigger that wipes only some of these would
    leave the round machine (or the alias-suggestion state) referencing a
    conversation that no longer exists. Caller-joinable transaction so a later
    plan's retrigger route can clear strictly AFTER a winning claim_status, in
    the same transaction that commits before _run_pipeline is scheduled
    (Pitfall #8).

    GAP-2/GAP-3 (11-06): this statement ALSO bumps reply_epoch = reply_epoch + 1.
    Without this bump, a retrigger resets clarification_round to 0 but leaves
    the run's PRIOR round-0 'sent' outbound row and any consumed reply rows
    fully intact in email_messages (the append-only audit log is never touched
    here, by design) — so the retriggered run's first clarification would see
    the stale round-0 row and silently suppress the send (GAP-2, WR-05
    reintroduced), and a resume would re-accumulate a stale consumed reply
    from a conversation that no longer exists (GAP-3, mispay risk). The epoch
    bump gives every round-machine read (get_outbound_for_round,
    load_consumed_replies, find_stranded_unconsumed_replies) a scope boundary
    that the retrigger crosses but no stale row can — the historical rows
    remain fully queryable, just invisible to the CURRENT epoch's reads.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        c.execute(
            "UPDATE payroll_runs SET clarified_fields = NULL, pre_clarify_extracted = NULL,"
            " clarification_round = 0, alias_candidates = NULL,"
            " reply_epoch = reply_epoch + 1, updated_at = now()"
            " WHERE id = %s",
            (str(run_id),),
        )


def update_known_alias(
    employee_id: uuid.UUID,
    new_alias: str,
    conn: psycopg.Connection | None = None,
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
