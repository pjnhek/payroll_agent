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
    find_run_by_message_id — join-based loser lookup for the webhook's dedup-loser
                             path (DATA-02): insert_inbound_email returns (None, False)
                             on ON CONFLICT, so the loser has no email_id — only the
                             RFC message_id — to resolve the existing run by
    link_email_to_run      — back-fill run_id on an inbound row once ingest
                             classification resolves it to an existing run (WR-03:
                             real reply/late-reply rows join the thread view)

  Status / persistence
    Originally two writers: set_status (unguarded forward transitions inside an
    owned path) and claim_status (atomic guarded claim at every contended gate).
    Now three writers — the third is sweep_stranded_runs (D-9-10/11/12 recovery
    sweep), a SANCTIONED THIRD status writer using the SAME single-statement
    CAS-UPDATE-WHERE-RETURNING idiom as claim_status, scoped to EXACTLY
    {received, extracting, computed} (never the parked awaiting_reply/
    awaiting_approval/approved statuses).
    record_run_error       — the ONE documented exception: writes error_reason AND
                             routes its ERROR transition THROUGH set_status (FIX B,
                             so there is still exactly one status-write path)
    persist_extracted      — Extracted JSONB only (no status)
    persist_decision       — Decision JSONB only; takes NO final_status (FIX B)
    persist_reconciliation — list[NameMatchResult] JSONB only (D-A3-05)
    replace_line_items     — DELETE-by-run then insert (idempotency invariant)
    set_alias_candidates   — write alias_candidates JSONB column (D-04)
    get_clarification_round / set_clarification_round — payroll_runs.clarification_round
                             read/write (D-11-01, Phase 11 round machine; zero behavior
                             change until a later plan wires the increment)
    clear_reply_context    — nulls clarified_fields, pre_clarify_extracted,
                             clarification_round, AND alias_candidates in one
                             statement (D-11-04: "context lost means ALL of it")

  Email / threading
    insert_email_message       — generic append to email_messages (audit log); upserts
                                 on (run_id, purpose, round) for non-NULL purpose outbound
                                 rows (D-11-01: widened from (run_id, purpose); round
                                 defaults to 0 so existing callers are behavior-identical)
    get_outbound_message_id    — purpose-aware + send_state='sent'-filtered read of the
                                 outbound Message-ID (finding #1 + R2-HIGH fix, CLAR-04)
    get_outbound_for_round     — round-aware sibling of get_outbound_message_id; returns
                                 the found row's round so callers derive the next round
                                 from it, never a blind +1 (D-11-01/13, Pitfall #3)
    mark_reply_consumed        — write-once (consumed_round IS NULL guard) marker for an
                                 inbound reply (D-11-02)
    load_consumed_replies      — all consumed inbound replies for a run, round-ordered
                                 (D-11-10/12/13 accumulated-context source)
    get_inbound_by_message_id  — load the PERSISTED inbound row by message_id (D-11-13;
                                 WR-04 redelivery reads this, never the redelivered body)
    find_stranded_unconsumed_replies — stale unconsumed replies against awaiting_reply
                                 runs (D-11-05 auto-resume sweep scope)
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
import re
import unicodedata
import uuid
from typing import Any

import psycopg.rows

from app.db.supabase import get_connection
from app.models.contracts import ClarifiedFields, Decision, Extracted, PaystubLineItem
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
# OPS2-01: error_detail is included alongside error_reason for the same reason
# CR-02 added updated_at — a column missing from this constant is invisible to
# every load_run caller (including the run_detail dashboard route) regardless
# of what record_run_error already wrote into the actual DB row.
# CR-01 (phase-8 review): alias_candidates is included because two orchestrator
# paths read it from load_run() — resume_pipeline's STEP A pre-candidate binding
# and _write_aliases_if_safe at the approval gate. Without it, both paths saw {}
# on a real dict_row and the alias-learning WRITE side was a silent no-op on a
# live DB (masked by InMemoryRepo.load_run returning the full in-memory dict).
RUN_COLS = (
    "id, business_id, source_email_id, status, extracted_data, decision,"
    " reconciliation, error_reason, error_detail, alias_candidates,"
    " pay_period_start, pay_period_end, updated_at"
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


def link_email_to_run(email_id: uuid.UUID, run_id: uuid.UUID, conn=None) -> None:
    """Back-fill run_id on an inbound email row after ingest classification (WR-03).

    The ingest transaction inserts every inbound row with run_id=NULL (for a
    first inbound the run does not exist yet). When classification then resolves
    the row to an EXISTING run (reply_candidate / late_reply), this links the row
    so real client replies appear in load_thread_messages' run-detail thread view
    and in join-based audits — matching the simulate-reply demo path, which passes
    run_id at insert time (main.py demo affordance).

    Safety (phase-9 review WR-03, traced against every email_messages consumer):
    - uq_email_run_purpose UNIQUE (run_id, purpose): inbound rows keep
      purpose=NULL, and Postgres never treats (run_id, NULL) rows as conflicting.
    - Every routing/idempotency query keyed on email_messages.run_id filters
      direction='outbound' (find_awaiting_reply_for_header, find_any_run_for_header,
      get_outbound_message_id, get_outbound_references_chain, load_outbound_emails),
      so linking inbound rows cannot affect reply routing or send idempotency.
    - find_run_by_message_id joins via payroll_runs.source_email_id, not run_id.
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "UPDATE email_messages SET run_id = %s WHERE id = %s",
                (str(run_id), str(email_id)),
            )


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


def find_run_by_message_id(message_id: str, conn=None) -> uuid.UUID | None:
    """Resolve the existing run for an RFC message_id (webhook dedup-loser lookup).

    Keyed on `message_id: str`, deliberately NOT `email_id: uuid.UUID` — checker
    BLOCKER 1 fix. `insert_inbound_email` returns `(None, False)` on `ON CONFLICT
    (message_id) DO NOTHING`, so the webhook's dedup-loser branch never has an
    email_id to pass; `message_id` (the RFC header, already parsed by
    gateway.parse_inbound before the dedup insert runs) is the only key the loser
    possesses. Joins email_messages (uq_message_id UNIQUE, schema.sql:218) to
    payroll_runs via the deferred FK payroll_runs.source_email_id ->
    email_messages.id (schema.sql:312-326).

    Read-only single-lookup (mirrors find_business_by_sender's shape) — no
    c.transaction(), since nothing is written. Returns None if no run's source
    email carries this message_id.
    """
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            """
            SELECT payroll_runs.id
            FROM payroll_runs
            JOIN email_messages ON email_messages.id = payroll_runs.source_email_id
            WHERE email_messages.message_id = %s
            """,
            (message_id,),
        ).fetchone()
    return uuid.UUID(str(row[0])) if row else None


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


# Stranded-run scope (D-9-12): EXACTLY these three in-flight statuses are eligible
# for the recovery sweep. A run parked in awaiting_reply/awaiting_approval/approved
# is waiting on a HUMAN (client reply or operator approval) — that is normal, not
# stranded — so those statuses must NEVER appear here. This list is pinned by an
# explicit unit test (Task 2) asserting both the presence of these three values and
# the absence of the three parked statuses.
_STRANDED_SCOPE_STATUSES: list[str] = ["received", "extracting", "computed"]


def sweep_stranded_runs(threshold_seconds: int, conn=None) -> list[uuid.UUID]:
    """Recover runs stranded mid-flight by a dead background task (D-9-10/11/12).

    SANCTIONED THIRD status writer (alongside set_status/claim_status) — same
    single-statement CAS-UPDATE-WHERE-RETURNING idiom as claim_status, so there
    is no read-then-write TOCTOU window (T-09-01).

    Scope is hardcoded to EXACTLY {received, extracting, computed} — a run
    sitting in awaiting_reply/awaiting_approval/approved is waiting on a human,
    not stranded, and must never be swept (D-9-12, T-09-02). The scope list is
    NOT caller-supplied; widening it requires editing this function's own body,
    which the Task 2 scope-pin unit test immediately fails.

    error_detail is built via SQL CONCATENATION of a static prefix with the
    run's OWN pre-update `status` column value (`%s || status`) — NOT a Python
    literal string containing an unresolved "{status}" placeholder (Codex LOW,
    closed). Postgres evaluates every SET expression against the row's OLD
    values, so `%s || status` on the right-hand side correctly captures the
    PRE-update status even though the same statement's SET clause also
    overwrites `status` to 'error' — this is standard SQL UPDATE semantics
    (the SET list is evaluated once per row against the values as they were
    BEFORE this UPDATE statement runs), not a per-row iteration order effect.

    Returns the list of run ids that were swept (possibly empty).
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            rows = c.execute(
                "UPDATE payroll_runs SET status = %s, error_reason = %s,"
                " error_detail = %s || status, updated_at = now()"
                " WHERE status = ANY(%s)"
                " AND updated_at < now() - (%s || ' seconds')::interval"
                " RETURNING id",
                (
                    RunStatus.ERROR.value,
                    "StrandedRunSwept",
                    "recovery: stranded in-flight (background task died) — swept from ",
                    _STRANDED_SCOPE_STATUSES,
                    str(threshold_seconds),
                ),
            ).fetchall()
    return [uuid.UUID(str(r[0])) for r in rows]


# ---------------------------------------------------------------------------
# PII scrub helpers (OPS2-01, D-8-01/D-8-01b/D-8-02) — offset-safe, per-candidate
# compiled regex, mark-aware-lookaround-anchored, longest-name-first, fail-open.
#
# Design (closes codex R2-1 offset-drift + R2-3 boundary-over-redaction + R3-1
# stray-combining-mark, see 08-02-PLAN.md): each candidate name/alias gets ONE
# compiled re.Pattern built directly from the ORIGINAL (non-normalized) string —
# never from a normalized copy of the message. Every match span the regex engine
# reports is therefore already a valid offset into the original message; there is
# no normalize-then-slice-original translation step, so no offset can drift.
# ---------------------------------------------------------------------------

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_REDACTED = "[REDACTED]"

# Three-way alternation per accented Latin-1 letter that can appear in a roster
# name: (precomposed | base + combining mark | bare unaccented base). The bare-
# base alternative is required because real input (LLM extraction, all-caps email
# rendering) frequently strips diacritics entirely rather than decomposing them —
# a map with only the first two alternatives lets a fully unaccented rendering
# (e.g. "Ana Nunez" for stored "Ana Núñez") leak unredacted.
#
# WR-02 (phase-8 review): generated ONCE AT IMPORT TIME from
# unicodedata.decomposition over the Latin-1 Supplement, replacing the previous
# hand-transcribed 7-entry table (acute vowels + n-tilde + c-cedilla only) whose
# own justification applied equally to the umlaut/grave/circumflex letters it
# omitted — for stored "Björn Müller", the common ASCII-ified rendering
# "Bjorn Muller" leaked entirely. Import-time generation is still STATIC and
# still offset-safe: nothing is computed at match time, and only the CANDIDATE
# pattern is affected — the message is never normalized (the offset-unsafe
# approach R2-1 rejects). Letters with no canonical base+mark decomposition
# (like o-stroke, ae, thorn, eth, sharp-s) are intentionally absent and fall
# through to literal escaping, exactly as before.
def _build_accent_class_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for codepoint in range(0x00C0, 0x0100):  # Latin-1 Supplement letters
        lower = chr(codepoint).lower()
        if len(lower) != 1 or lower in mapping:
            continue
        decomp = unicodedata.decomposition(lower).split()
        # Only canonical two-part decompositions (base + combining mark);
        # compatibility decompositions carry a '<tag>' first element — skip.
        if len(decomp) != 2 or decomp[0].startswith("<"):
            continue
        base, mark = (chr(int(part, 16)) for part in decomp)
        if unicodedata.combining(mark) == 0 or not base.isascii():
            continue
        mapping[lower] = (
            f"(?:{re.escape(lower)}|{re.escape(base)}{re.escape(mark)}|{re.escape(base)})"
        )
    return mapping


_ACCENT_CLASS_MAP: dict[str, str] = _build_accent_class_map()


def _compile_name_pattern(name: str) -> re.Pattern[str]:
    r"""Build ONE compiled, mark-aware-lookaround-anchored pattern for `name`.

    Matches the precomposed form, an NFD-decomposed occurrence, AND a bare-
    unaccented occurrence of `name` -- all directly against the ORIGINAL
    message string (no normalize-then-slice step, so no offset drift, R2-1).
    Anchored with lookarounds -- (?<![\w\u0300-\u036f]) / (?![\w\u0300-\u036f])
    -- instead of bare \b...\b (R3-1): these reject BOTH a following word
    character AND a following combining mark, so a candidate ending in an
    accented character can't match only its bare-base alternative while
    stranding an NFD trailing combining mark next to [REDACTED]. Strictly
    stronger than \b for plain ASCII, so "Tom" still never matches inside
    "Tomorrow" (R2-3).

    WR-01 (phase-8 review): the CANDIDATE is NFC-normalized first. The
    _ACCENT_CLASS_MAP is keyed by precomposed characters, so an NFD-stored
    candidate (e.g. an alias learned from an NFD-encoded client email) would
    otherwise bypass the map entirely — 'e' + combining acute escapes as two
    literal chars and the pattern matches ONLY the NFD rendering, letting the
    NFC and bare-unaccented renderings of the name leak unredacted. Normalizing
    the candidate is offset-safe: only the PATTERN side changes; the message is
    never normalized (the R2-1 offset-drift rationale forbids normalizing the
    message, not the candidate).
    """
    name = unicodedata.normalize("NFC", name)
    fragments: list[str] = []
    for ch in name:
        mapped = _ACCENT_CLASS_MAP.get(ch.lower())
        fragments.append(mapped if mapped is not None else re.escape(ch))
    body = "".join(fragments)
    pattern = r"(?<![\w\u0300-\u036f])" + body + r"(?![\w\u0300-\u036f])"
    return re.compile(pattern, re.IGNORECASE)


def _scrub(message: str, roster: Roster | None = None) -> str:
    """Redact email addresses and (if `roster` given) roster names/aliases.

    Never queries the DB or calls any repo/load function — `roster` is only
    ever the in-memory object the caller already has (D-8-01b, non-negotiable).
    Candidates are applied longest-first so a short alias contained inside a
    longer name/alias (e.g. alias "Dave" inside full_name "Dave Reyes") never
    independently matches and fragments an already-redacted span (R2-1).
    """
    message = _EMAIL_RE.sub(_REDACTED, message)
    if roster is None:
        return message

    candidates: list[str] = []
    for employee in roster.employees:
        if employee.full_name:
            candidates.append(employee.full_name)
        for alias in employee.known_aliases:
            if alias:
                candidates.append(alias)
    candidates.sort(key=len, reverse=True)

    for name in candidates:
        pattern = _compile_name_pattern(name)
        message = pattern.sub(_REDACTED, message)
    return message


def _build_error_detail(
    stage: str, exc: Exception, roster: Roster | None = None
) -> str | None:
    """Scrub-then-compose-then-truncate. Fails open: any internal exception
    returns None so diagnostics never blocks the error path it exists to
    observe (D-8-01b, T-8-02).
    """
    try:
        scrubbed = _scrub(str(exc), roster=roster)
        return f"{stage}: {scrubbed}"[:200]
    except Exception:  # noqa: BLE001 — diagnostics must never break diagnostics
        return None


def record_run_error(
    run_id: uuid.UUID,
    reason: str,
    conn=None,
    *,
    detail_exc: Exception | None = None,
    stage: str | None = None,
    roster: Roster | None = None,
) -> None:
    """Write payroll_runs.error_reason AND advance the run to ERROR.

    The single documented exception to "set_status is the only status writer":
    it writes the error_reason data column itself, then routes its ERROR
    transition THROUGH set_status (FIX B) — so there is still exactly one
    status-write path and no second writer can corrupt the state machine.

    WR-04: this must NOT clobber a run that is already TERMINAL. A late/duplicate
    reply (cf. CR-02) that resumes a run which then hits an exception would otherwise
    flip an approved/sent/reconciled/rejected run to ERROR, destroying the run's real
    state and the approval audit trail. (No-op on terminal includes a run already in
    ERROR — re-stamping it is pointless.)

    WR-03 (phase-8 review): the guard is an atomic compare-and-swap folded into
    the UPDATE's WHERE clause (`status <> ALL(terminal)` + RETURNING), the same
    CAS idiom claim_status uses — NOT a separate SELECT-then-UPDATE. Under READ
    COMMITTED a check-then-act pair lets a concurrent transaction commit a
    terminal status (e.g. _deliver's set_status(SENT) racing a late resume's
    error path) between the read and the write, and the unconditional UPDATE
    would then clobber the terminal run to ERROR — the exact outcome this guard
    exists to prevent. With the CAS, a run that is terminal (or missing) matches
    no row, the claim fails, and set_status(ERROR) is never called.

    OPS2-01 (D-8-01/D-8-01b/D-8-02): the optional keyword-only `detail_exc`/`stage`/
    `roster` params drive a scrubbed, stage-prefixed, 200-char-truncated
    `error_detail` write alongside the existing `error_reason`. `conn` stays
    positional-compatible (review fix #8) — the new params are keyword-only and
    placed AFTER it so every existing call site is unaffected AT THE CALL SITE.

    WR-05 (phase-8 review) — overwrite contract: `error_detail` is ALWAYS written.
    When `detail_exc` or `stage` is omitted it is OVERWRITTEN WITH NULL, erasing
    any previously-persisted detail for this run. This is deliberate: error_reason
    and error_detail always describe the SAME (latest) error — preserving a stale
    detail next to a fresh reason via COALESCE would mislead the operator reading
    the error banner. Callers that want a diagnostic detail must pass BOTH
    `detail_exc` and `stage` (all current production callers do).
    """
    detail = (
        _build_error_detail(stage, detail_exc, roster=roster)
        if (detail_exc is not None and stage is not None)
        else None
    )
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            # WR-03 CAS: the terminal-status predicate lives INSIDE the UPDATE's
            # WHERE clause (claim_status idiom) so no concurrent transaction can
            # commit a terminal status between a read and this write. The terminal
            # set is parameterized from _TERMINAL_STATUSES (single source of
            # truth) — `status <> ALL(%s)` is the NOT-IN form for an array param.
            row = c.execute(
                "UPDATE payroll_runs SET error_reason = %s, error_detail = %s,"
                " updated_at = now() WHERE id = %s AND status <> ALL(%s)"
                " RETURNING id",
                (reason, detail, str(run_id), sorted(_TERMINAL_STATUSES)),
            ).fetchone()
            if row is None:
                logger.info(
                    "record_run_error skipped: run %s is terminal or missing — not "
                    "clobbering to ERROR (WR-04 guard, WR-03 CAS). reason was: %s",
                    run_id,
                    reason,
                )
                return
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


def set_pre_clarify_extracted(
    run_id: uuid.UUID,
    extracted: Extracted,
    conn=None,
) -> bool:
    """Snapshot the pre-clarify extracted data (IS NULL write-once guard, D-19 MONEY-03).

    Uses a CAS UPDATE with `WHERE id = %s AND pre_clarify_extracted IS NULL RETURNING id`
    — atomic check-and-write so the snapshot is written ONLY ONCE on the first call.
    Subsequent calls return False (idempotent no-op). Called BEFORE each of the
    three set_status(AWAITING_REPLY) paths in _clarify (N7 fix).

    Returns True if written (first write), False if already set.
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            row = c.execute(
                "UPDATE payroll_runs SET pre_clarify_extracted = %s, updated_at = now()"
                " WHERE id = %s AND pre_clarify_extracted IS NULL RETURNING id",
                (json.dumps(extracted.model_dump(mode="json")), str(run_id)),
            ).fetchone()
    return row is not None


def load_pre_clarify_extracted(
    run_id: uuid.UUID,
    conn=None,
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
    clarified: dict,
    conn=None,
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
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "UPDATE payroll_runs SET clarified_fields = %s, updated_at = now() WHERE id = %s",
                (json.dumps(clarified), str(run_id)),
            )


def load_clarified_fields(
    run_id: uuid.UUID,
    conn=None,
) -> dict:
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
    return json.loads(row[0]) if isinstance(row[0], str) else row[0]


def get_clarification_round(run_id: uuid.UUID, conn=None) -> int:
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


def set_clarification_round(run_id: uuid.UUID, value: int, conn=None) -> None:
    """Write payroll_runs.clarification_round (D-11-01).

    Caller-joinable transaction (copy of link_email_to_run's shape) so a later
    plan's `_clarify` finalize path can write this in the SAME transaction as
    set_status(AWAITING_REPLY) (D-9-02: status-advance-last).
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "UPDATE payroll_runs SET clarification_round = %s, updated_at = now() WHERE id = %s",
                (value, str(run_id)),
            )


def clear_reply_context(run_id: uuid.UUID, conn=None) -> None:
    """Null ALL reply-round context on a run in one statement (D-11-04).

    "Context lost means ALL of it": the pre-clarify snapshot, the field-
    regression outcomes, the round counter, AND the suggestion/candidate state
    are cleared together — a retrigger that wipes only some of these would
    leave the round machine (or the alias-suggestion state) referencing a
    conversation that no longer exists. Caller-joinable transaction so a later
    plan's retrigger route can clear strictly AFTER a winning claim_status, in
    the same transaction that commits before _run_pipeline is scheduled
    (Pitfall #8).
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            c.execute(
                "UPDATE payroll_runs SET clarified_fields = NULL, pre_clarify_extracted = NULL,"
                " clarification_round = 0, alias_candidates = NULL, updated_at = now()"
                " WHERE id = %s",
                (str(run_id),),
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
    """
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            if purpose is not None:
                # Outbound path with a purpose: upsert on (run_id, purpose, round) so a
                # retry WITHIN a round over a reserved/failed row advances to the new
                # send_state rather than crashing with a unique constraint violation.
                row = c.execute(
                    """
                    INSERT INTO email_messages (
                        run_id, direction, message_id, in_reply_to,
                        references_header, subject, from_addr, to_addr, body_text,
                        purpose, send_state, round
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (run_id, purpose, round) DO UPDATE
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
            f"purpose must be 'clarification', 'confirmation', or 'clarification_field_regression', got {purpose!r}"
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
    """
    if purpose not in ("clarification", "confirmation", "clarification_field_regression"):
        raise ValueError(
            f"purpose must be 'clarification', 'confirmation', or 'clarification_field_regression', got {purpose!r}"
        )
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            """
            SELECT message_id, round FROM email_messages
            WHERE run_id = %s AND direction = 'outbound'
              AND purpose = %s AND send_state = 'sent' AND round = %s
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (str(run_id), purpose, round),
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
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
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
    """
    sql = (
        "SELECT direction, purpose, subject, body_text, message_id,"
        " from_addr, to_addr, consumed_round, created_at"
        " FROM email_messages"
        " WHERE run_id = %s AND direction = 'inbound' AND consumed_round IS NOT NULL"
        " ORDER BY consumed_round ASC"
    )
    with _conn_ctx(conn) as (c, _owns):
        with c.cursor(row_factory=psycopg.rows.dict_row) as cur:
            cur.execute(sql, (str(run_id),))
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
    with _conn_ctx(conn) as (c, _owns):
        with c.cursor(row_factory=psycopg.rows.dict_row) as cur:
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
    """
    sql = (
        "SELECT em.id, em.run_id, em.message_id, em.in_reply_to,"
        " em.references_header, em.subject, em.body_text,"
        " em.from_addr, em.to_addr, em.consumed_round, em.created_at"
        " FROM email_messages em"
        " JOIN payroll_runs pr ON pr.id = em.run_id"
        " WHERE em.direction = 'inbound'"
        "   AND em.consumed_round IS NULL"
        "   AND em.run_id IS NOT NULL"
        "   AND pr.status = %s"
        "   AND em.created_at < now() - (%s || ' seconds')::interval"
    )
    with _conn_ctx(conn) as (c, _owns):
        with c.cursor(row_factory=psycopg.rows.dict_row) as cur:
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

    D-8-07 (OPS2-02): selects an explicit scalar column list — no `pr.*` / `SELECT *`
    — so a new payroll_runs column can never silently reach the dashboard list view
    without an explicit, reviewed SQL edit (T-8-07). Two SQL-computed aliases avoid
    shipping a raw JSONB blob to the list view: `summary_gate_reason` (unchanged,
    already NULL-safe via `->`/`->>` on a NULL `decision` column) and `employee_count`,
    guarded by `jsonb_typeof` (review fix #2 / T-8-12) rather than a bare
    `COALESCE(jsonb_array_length(...), 0)` — the bare form is only NULL-safe for SQL
    NULL and still raises a Postgres error on a non-array JSON scalar/null literal in
    `extracted_data->'employees'`; the `CASE WHEN jsonb_typeof(...) = 'array'` guard
    degrades a corrupt/legacy row to `employee_count = 0` instead of erroring the
    entire runs list.
    """
    sql = (
        "SELECT pr.id, pr.business_id, pr.status, pr.created_at, pr.updated_at,"
        " b.name AS business_name,"
        " pr.decision->'gate_reasons'->>0 AS summary_gate_reason,"
        " CASE WHEN jsonb_typeof(pr.extracted_data->'employees') = 'array'"
        "      THEN jsonb_array_length(pr.extracted_data->'employees')"
        "      ELSE 0 END AS employee_count"
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
