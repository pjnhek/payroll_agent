"""DB repo — run lifecycle, status CAS, and error/scrub helpers."""
from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from typing import Any

import psycopg
import psycopg.rows

from app.db.repo._shared import _conn_ctx, _nulltx
from app.models.contracts import InboundEmail
from app.models.roster import Roster
from app.models.status import RunStatus

logger = logging.getLogger("payroll_agent.repo")

# Explicit column list for reading a run (only what callers need; no SELECT *).
#
# INVARIANT: a column missing from this constant is INVISIBLE to every load_run
# caller — no matter what is actually written into the DB row. The read silently
# yields None (or {} on a dict_row), and the feature that depends on it becomes a
# no-op that no test using an in-memory repo can catch. Three columns are here
# because they were once missing and the omission disabled live behavior:
#
# - updated_at (TIMESTAMPTZ, so psycopg hands back a tz-aware datetime): the
#   retrigger handler's stale-run check read None and always evaluated False,
#   disabling stale-state recovery for RECEIVED/EXTRACTING/COMPUTED/SENT.
# - error_detail: written by record_run_error, but unreadable by the run_detail
#   dashboard route that exists to display it.
# - alias_candidates: read by resume_pipeline's pre-candidate binding and by
#   _write_aliases_if_safe at the approval gate, so its absence made the entire
#   alias-learning WRITE side a silent no-op on a live DB.
#
# Add the column here whenever you add a load_run consumer for it.
RUN_COLS = (
    "id, business_id, source_email_id, status, extracted_data, decision,"
    " reconciliation, error_reason, error_detail, alias_candidates, hours_changes,"
    " pay_period_start, pay_period_end, updated_at"
)

# Terminal run statuses: once a run reaches one of these, an error must NOT
# overwrite it. SENT/RECONCILED/REJECTED are finalized human/operator outcomes —
# clobbering them destroys the approval audit trail; ERROR is already terminal.
# APPROVED is intentionally NOT in this set: an approved run that fails delivery
# must stay recoverable, so record_run_error must be able to advance it to ERROR
# and let the operator retrigger. The audit trail survives via ERROR +
# error_reason, and a human re-approves once the delivery failure is fixed. Adding
# APPROVED here would silently swallow every delivery failure.
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
    conn: psycopg.Connection | None = None,
) -> tuple[uuid.UUID | None, bool]:
    """Insert an inbound email_messages row, idempotent on message_id.

    `body_text` is the ALREADY-CLEANED body (the webhook applies clean_body()
    BEFORE calling this); it is persisted verbatim so the inbound row is the
    single cleaned-body source of truth and nothing downstream re-cleans it.
    Returns (email_id, inserted) where
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


def link_email_to_run(
    email_id: uuid.UUID,
    run_id: uuid.UUID,
    conn: psycopg.Connection | None = None,
) -> None:
    """Back-fill run_id on an inbound email row after ingest classification.

    The ingest transaction inserts every inbound row with run_id=NULL (on a first
    inbound the run does not exist yet). When classification then resolves the row
    to an EXISTING run (reply_candidate / late_reply), this links it, so real
    client replies appear in load_thread_messages' run-detail thread view and in
    join-based audits — matching the simulate-reply demo path, which already passes
    run_id at insert time.

    Why back-filling run_id on an INBOUND row is safe (traced against every
    email_messages consumer):
    - The uq_email_run_purpose UNIQUE (run_id, purpose) constraint cannot fire:
      inbound rows keep purpose=NULL, and Postgres never treats (run_id, NULL)
      rows as conflicting.
    - Every routing/idempotency query keyed on email_messages.run_id also filters
      direction='outbound' (find_awaiting_reply_for_header, find_any_run_for_header,
      get_outbound_message_id, get_outbound_references_chain, load_outbound_emails),
      so linking inbound rows cannot affect reply routing or send idempotency.
    - find_run_by_message_id joins via payroll_runs.source_email_id, not run_id.

    Also stamps epoch = the target run's CURRENT reply_epoch (a correlated subquery,
    no extra round trip). This is the one stamping point that cannot race a
    retrigger: the row links either before or after the epoch bump, and either way
    it is correctly scoped to whichever epoch was current at link time. A row's
    epoch is a permanent point-in-time fact — never re-read or mutated afterward.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        c.execute(
            "UPDATE email_messages SET run_id = %s,"
            " epoch = (SELECT reply_epoch FROM payroll_runs WHERE id = %s)"
            " WHERE id = %s",
            (str(run_id), str(run_id), str(email_id)),
        )


def find_business_by_sender(
    from_addr: str, conn: psycopg.Connection | None = None
) -> uuid.UUID | None:
    """Return the business_id whose contact_email matches from_addr, else None.

    This is the access-control seam: an unknown sender returns None so the webhook
    stops rather than guessing which business an unrecognized email belongs to.

    Additive fallback: with no contact_email match, check demo_sender_bindings for
    an operator-email → business mapping. This lets real-email inbound route via
    the operator's own mailbox binding without mutating any seeded contact_email.
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


def find_run_by_message_id(
    message_id: str, conn: psycopg.Connection | None = None
) -> uuid.UUID | None:
    """Resolve the existing run for an RFC message_id (webhook dedup-loser lookup).

    Keyed on `message_id: str`, deliberately NOT `email_id: uuid.UUID`.
    `insert_inbound_email` returns `(None, False)` on `ON CONFLICT (message_id) DO
    NOTHING`, so the webhook's dedup-loser branch never HAS an email_id to pass;
    the RFC `message_id` (already parsed by gateway.parse_inbound before the dedup
    insert runs) is the only key the loser possesses. Joins email_messages (unique
    on message_id) to payroll_runs via the deferred FK
    payroll_runs.source_email_id -> email_messages.id.

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


def load_business_name(
    business_id: uuid.UUID, conn: psycopg.Connection | None = None
) -> str | None:
    """Return the display name for a business, or None if not found.

    Used by _deliver to enrich the run dict with business_name before composing
    the confirmation email. Kept as a thin targeted helper so load_run stays lean
    (no JOIN imposed on every caller).
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
    conn: psycopg.Connection | None = None,
) -> uuid.UUID:
    """Open a payroll_runs row (status defaults to 'received'); return its id.

    record_only=True marks compose-created (in-app demo) runs that must skip the
    real email-provider call. The orchestrator reads this flag at each
    send_outbound call site (_clarify and _deliver) via get_record_only_flag().
    Live callers omit the argument and get the False default.
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
    if row is None:
        raise RuntimeError("create_run did not return a new run id")
    return uuid.UUID(str(row[0]))


def load_run(
    run_id: uuid.UUID, conn: psycopg.Connection | None = None
) -> dict[str, Any] | None:
    """Read one run as a dict (explicit columns + dict_row, never SELECT *)."""
    # RUN_COLS is a trusted module constant (no external input); building the
    # statement as a local keeps the parameterized-SQL discipline test green
    # (no inline f-string inside execute(...)). Values stay %s-parameterized.
    sql = "SELECT " + RUN_COLS + " FROM payroll_runs WHERE id = %s"
    with _conn_ctx(conn) as (c, _owns), c.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(sql, (str(run_id),))
        return cur.fetchone()


def load_source_email(
    run_id: uuid.UUID, conn: psycopg.Connection | None = None
) -> str | None:
    """Return the run's ORIGINAL CLEANED inbound body, unchanged.

    The body was cleaned at ingest (insert_inbound_email persists the cleaned
    text), so it is read straight from email_messages.body_text with NO re-cleaning
    on read — cleaning twice could diverge from what the pipeline actually
    extracted from, and this body is the resume path's re-extraction context.
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
# (no SELECT * — InboundEmail is extra="forbid", so a stray column raises). The
# stored body_text is already cleaned, so the rebuilt InboundEmail carries the
# cleaned body unchanged.
# Every column is qualified with the `em.` alias: load_inbound_email JOINs
# payroll_runs (which also has `id`, `created_at`), so a bare `id` is ambiguous
# (psycopg AmbiguousColumn). `em.id` still returns a result column named `id`, so
# the InboundEmail(**row) construction is unchanged.
_INBOUND_COLS = (
    "em.id, em.message_id, em.in_reply_to, em.references_header, em.subject,"
    " em.from_addr, em.to_addr, em.body_text, em.created_at"
)


def load_inbound_email(
    run_id: uuid.UUID, conn: psycopg.Connection | None = None
) -> InboundEmail | None:
    """Rebuild the run's source InboundEmail (cleaned body) for the extract stage.

    Returns an InboundEmail or None if the run has no linked source email. The
    body_text is the cleaned body persisted at ingest — never re-cleaned on read.
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


# payroll_runs.status is the state machine, so the public transition API is
# deliberately limited to two writers: set_status (unguarded forward transitions
# inside an owned path) and claim_status (atomic guarded claims at contended gates).
# Narrow context-reset and fenced-settlement coordinators own their own CAS-scoped
# writes; adding another unguarded transition helper here would be a bug.
def set_status(
    run_id: uuid.UUID,
    status: RunStatus,
    conn: psycopg.Connection | None = None,
) -> None:
    """Unguarded status writer — the uncontended half of the two-writer rule.

    Use only where the caller already owns the run and no other actor can be
    transitioning it; use claim_status at any gate two actors can reach at once.
    Writes the enum .value, never a string literal. record_run_error is the one
    caller that also writes a data column alongside the status.
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
    conn: psycopg.Connection | None = None,
) -> bool:
    """Atomic compare-and-swap on payroll_runs.status — the guarded half of the
    two-writer rule, and the primitive behind every contended gate (approve,
    reject, resume, retrigger).

    Returns True if the claim succeeded (the run was in `expected` and is now
    `new`). Returns False if it was NOT in `expected` — the caller logs a
    late/duplicate and drops cleanly WITHOUT re-running the work.

    `WHERE id = %s AND status = %s RETURNING id` in a single statement is what
    makes this safe: exactly one of two concurrent callers gets a row back. A
    read-then-write would leave a TOCTOU window in which both callers see
    `expected` and both proceed — double-approving a payroll.
    """
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        row = c.execute(
            "UPDATE payroll_runs SET status = %s, updated_at = now() "
            "WHERE id = %s AND status = %s RETURNING id",
            (RunStatus(new).value, str(run_id), RunStatus(expected).value),
        ).fetchone()
    return row is not None


# ---------------------------------------------------------------------------
# PII scrub helpers — offset-safe, per-candidate compiled regex, mark-aware
# lookaround-anchored, longest-name-first, fail-open.
#
# CORE RULE: the MESSAGE is never normalized; only the CANDIDATE pattern is. Each
# candidate name/alias compiles to ONE re.Pattern matched directly against the
# ORIGINAL message string. Every span the regex engine reports is therefore already
# a valid offset into that original string. Normalizing the message first would
# force a normalize-then-slice-the-original translation step, and any length change
# from that normalization drifts the offsets — redacting the wrong characters and
# leaving real names exposed.
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
# The map is generated ONCE AT IMPORT TIME from unicodedata.decomposition over the
# whole Latin-1 Supplement, deliberately NOT hand-transcribed: a hand-written table
# covers whichever letters its author happened to think of and silently leaks the
# rest (a table of acute vowels + n-tilde + c-cedilla leaves stored "Björn Müller"
# fully exposed under the common ASCII-ified rendering "Bjorn Muller"). Import-time
# generation is still STATIC and still offset-safe: nothing is computed at match
# time, and only the CANDIDATE pattern is affected — the message is never
# normalized. Letters with no canonical base+mark decomposition (o-stroke, ae,
# thorn, eth, sharp-s) have no entry and fall through to literal escaping.
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
    unaccented occurrence of `name` -- all directly against the ORIGINAL message
    string, with no normalize-then-slice step, so no offset can drift.
    Anchored with lookarounds -- (?<![\w\u0300-\u036f]) / (?![\w\u0300-\u036f])
    -- rather than a bare \b...\b: these reject BOTH a following word character
    AND a following combining mark, so a candidate ending in an accented character
    cannot match only its bare-base alternative and strand an orphaned NFD
    combining mark next to [REDACTED]. They are strictly stronger than \b on plain
    ASCII, so "Tom" still never matches inside "Tomorrow" -- no over-redaction.

    The CANDIDATE is NFC-normalized first. _ACCENT_CLASS_MAP is keyed by
    precomposed characters, so an NFD-stored candidate (e.g. an alias learned from
    an NFD-encoded client email) would otherwise bypass the map entirely: 'e' +
    combining acute escapes as two literal chars, and the pattern then matches ONLY
    the NFD rendering, letting the NFC and bare-unaccented renderings of that name
    leak unredacted. Normalizing the candidate is offset-safe because only the
    PATTERN side changes -- the offset-drift rule forbids normalizing the MESSAGE,
    not the candidate.
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

    NON-NEGOTIABLE: never queries the DB and never calls any repo/load function.
    `roster` is only ever the in-memory object the caller already has. This runs on
    the error path, where a DB call could itself fail and take the error handler
    down with it.

    Candidates are applied longest-first so a short alias contained inside a longer
    name/alias (e.g. alias "Dave" inside full_name "Dave Reyes") never independently
    matches and fragments an already-redacted span.
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
    """Scrub-then-compose-then-truncate.

    Fails open: any internal exception returns None, so diagnostics can never block
    the error path it exists to observe. Scrubbing happens BEFORE truncation —
    truncating first could cut a name mid-token and leave a fragment the redaction
    regex no longer matches.
    """
    try:
        scrubbed = _scrub(str(exc), roster=roster)
        return f"{stage}: {scrubbed}"[:200]
    except Exception:  # noqa: BLE001 — diagnostics must never break diagnostics
        return None


def record_run_error(
    run_id: uuid.UUID,
    reason: str,
    conn: psycopg.Connection | None = None,
    *,
    detail_exc: Exception | None = None,
    stage: str | None = None,
    roster: Roster | None = None,
) -> None:
    """Write payroll_runs.error_reason AND advance the run to ERROR.

    The single sanctioned exception to the two-writer rule: it writes the
    error_reason data column itself, then routes its ERROR transition THROUGH
    set_status — so there is still exactly one status-write path.

    TERMINAL GUARD: this must NOT clobber a run that is already terminal. A
    late/duplicate reply that resumes a run which then raises would otherwise flip
    an approved/sent/reconciled/rejected run to ERROR, destroying the run's real
    state and the approval audit trail. A run already in ERROR is also a no-op —
    re-stamping it is pointless.

    The guard is an atomic compare-and-swap folded into the UPDATE's WHERE clause
    (`status <> ALL(terminal)` + RETURNING), the same idiom as claim_status — NOT a
    SELECT-then-UPDATE. Under READ COMMITTED, a check-then-act pair lets a
    concurrent transaction commit a terminal status (e.g. _deliver's
    set_status(SENT) racing a late resume's error path) between the read and the
    write; the unconditional UPDATE would then clobber that terminal run to ERROR —
    the exact outcome this guard exists to prevent. With the CAS, a terminal (or
    missing) run matches no row, the claim fails, and set_status(ERROR) is never
    called.

    The keyword-only `detail_exc`/`stage`/`roster` params drive a scrubbed,
    stage-prefixed, 200-char-truncated `error_detail` written alongside
    `error_reason`. They sit AFTER `conn` and are keyword-only so `conn` stays
    positional-compatible for existing call sites.

    OVERWRITE CONTRACT: `error_detail` is ALWAYS written. When `detail_exc` or
    `stage` is omitted it is overwritten with NULL, erasing any previously-persisted
    detail. This is deliberate — error_reason and error_detail must always describe
    the SAME (latest) error. Preserving a stale detail beside a fresh reason (via
    COALESCE) would show the operator a diagnostic from a different failure. Callers
    that want a detail must pass BOTH `detail_exc` and `stage`; all production
    callers do.
    """
    detail = (
        _build_error_detail(stage, detail_exc, roster=roster)
        if (detail_exc is not None and stage is not None)
        else None
    )
    with _conn_ctx(conn) as (c, owns), c.transaction() if owns else _nulltx():
        # The terminal-status predicate lives INSIDE the UPDATE's WHERE clause
        # (the claim_status CAS idiom) so no concurrent transaction can commit a
        # terminal status between a read and this write. The terminal set is
        # parameterized from _TERMINAL_STATUSES (single source of truth) —
        # `status <> ALL(%s)` is the NOT-IN form for an array parameter.
        row = c.execute(
            "UPDATE payroll_runs SET error_reason = %s, error_detail = %s,"
            " updated_at = now() WHERE id = %s AND status <> ALL(%s)"
            " RETURNING id",
            (reason, detail, str(run_id), sorted(_TERMINAL_STATUSES)),
        ).fetchone()
        if row is None:
            logger.info(
                "record_run_error skipped: run %s is terminal or missing — not "
                "clobbering to ERROR (terminal-status CAS guard). reason was: %s",
                run_id,
                reason,
            )
            return
        set_status(run_id, RunStatus.ERROR, conn=c)
