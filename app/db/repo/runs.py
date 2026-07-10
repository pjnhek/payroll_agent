"""DB repo — run lifecycle, status CAS, sweep, and error/scrub helpers."""
from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from typing import Any

import psycopg.rows

from app.db.repo._shared import _conn_ctx, _nulltx
from app.models.roster import Roster
from app.models.status import RunStatus

logger = logging.getLogger("payroll_agent.repo")

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
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
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

    GAP-2/GAP-3 (11-06): also stamps epoch = the target run's CURRENT
    reply_epoch (a correlated subquery, no extra round trip). This is the
    only stamping point that can never race a retrigger — the row either
    links before or after the epoch bump, either way it is correctly scoped
    to whichever epoch was current at link time. Never re-read or mutated
    afterward (a row's epoch is a permanent, point-in-time fact).
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        c.execute(
            "UPDATE email_messages SET run_id = %s,"
            " epoch = (SELECT reply_epoch FROM payroll_runs WHERE id = %s)"
            " WHERE id = %s",
            (str(run_id), str(run_id), str(email_id)),
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
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
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
    with _conn_ctx(conn) as (c, _owns), c.cursor(row_factory=psycopg.rows.dict_row) as cur:
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
    with _conn_ctx(conn) as (c, _owns), c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, (str(run_id),))
        row = cur.fetchone()
    return InboundEmail(**row) if row else None


# two writers: set_status (unguarded forward transitions inside an owned path)
# and claim_status (atomic guarded claim at every contended gate). (D-12)
def set_status(run_id: uuid.UUID, status: RunStatus, conn=None) -> None:
    """Unguarded status writer — one of two writers on payroll_runs.status (D-12).

    two writers: set_status (unguarded forward transitions inside an owned path)
    and claim_status (atomic guarded claim at every contended gate).
    Writes the enum .value (never a string literal). record_run_error is the one
    documented caller that also writes a data column; every other uncontended
    status transition in the system routes through here.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
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
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
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
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
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
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
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
