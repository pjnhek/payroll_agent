# Phase 8: Data-Layer Hygiene & Diagnostics - Research

**Researched:** 2026-07-02
**Domain:** Postgres schema hygiene (indexes, column projection), PII-safe error diagnostics, dead-enum removal
**Confidence:** HIGH

## Summary

Phase 8 is additive, low-risk data-layer work with no new external dependencies — everything needed already exists in the stdlib (`re`), the existing `psycopg`/schema.sql discipline, and established test patterns (`FakeConnection`, `test_status_drift.py`, `roster_from_seed`). Every code touch point named in CONTEXT.md was re-verified against live source in this session and matches exactly: `record_run_error` (repo.py:370), `load_all_runs` (repo.py:1088, `SELECT pr.*` confirmed), `RUN_COLS` (repo.py:90-93), the three call sites (orchestrator.py:188, :667; main.py:506), `RunStatus.NEEDS_CLARIFICATION` (status.py:19), the status CHECK (schema.sql:66-78), and `businesses.contact_email NOT NULL UNIQUE` (schema.sql:19) served by an equality-only query (repo.py:188, `find_business_by_sender`).

Two of D-8-09's stale-audit corrections are reconfirmed: (1) `businesses.contact_email` is already constraint-indexed and the lookup is plain equality — no new index needed; (2) `email_messages` composite-index column order must be verified against the REAL predicates, not copied from the audit's guess. Tracing repo.py:751-852 and :954-975 in this session found the actual hot predicates are `run_id = %s AND direction = 'outbound' [AND purpose = %s] AND send_state = 'sent'` (in `get_outbound_message_id` and `get_outbound_references_chain`) and `run_id = %s AND direction = 'outbound'` with an `ORDER BY created_at` (in `load_outbound_emails`) — all three share the `(run_id, direction)` prefix, with `send_state` as a further filter on two of the three. `load_thread_messages` (repo.py:964-971) uses an OR predicate (`run_id = %s OR id = subquery`) that a composite index cannot serve identically — it degrades to a `run_id`-only lookup for its first branch, which the same composite still covers as a prefix.

**Primary recommendation:** Build `error_detail` as ONE centralized helper (`_scrub_and_truncate` or similar) called from inside `record_run_error` itself — not from each of the three call sites — so the scrub-then-truncate ordering (D-8-01) and fail-open behavior (D-8-01b) are enforced in exactly one place and no caller can bypass them. Lock the `email_messages` composite index as `(run_id, direction, send_state)` — this column order serves all three verified predicates as a prefix match (two of three filter on all three columns; the third filters on the first two and uses `send_state` implicitly via the `ORDER BY created_at` on a small per-run row count). Do NOT create a `businesses.contact_email` index (already constraint-backed).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Error detail scrubbing + storage | API / Backend (`app/db/repo.py`) | — | `record_run_error` is the single funnel for all 3 error boundaries; scrubbing must happen in the data-access layer so no caller can bypass it (locked: Claude's Discretion note in CONTEXT.md) |
| Error detail rendering | Frontend Server (SSR, Jinja2) | — | `run_detail.html` reads the already-scrubbed `error_detail` column verbatim; no client-side logic, no re-scrubbing at render time |
| Index creation | Database / Storage (`schema.sql`) | — | Pure DDL; idempotent bootstrap applies it |
| Index verification | Database / Storage (live checkpoint) + API (static guard test) | — | Two-layer proof: CI parses schema.sql (hermetic), a human runs `pg_indexes` against the live Supabase instance (the project's established live-migration checkpoint pattern) |
| Runs-list projection | API / Backend (`load_all_runs` SQL) | Frontend Server (template consumes aliases) | SQL computes `summary_gate_reason` / `employee_count` server-side so no JSONB blob crosses the wire — matches D-8-07's "no JSONB blob crosses the wire for the list view" |
| NEEDS_CLARIFICATION removal | API / Backend (`status.py` enum) | Database / Storage (CHECK constraint) | Dual-sourced enum drift guard (`test_status_drift.py`) already enforces Python↔SQL parity; removal must update both sides atomically |
| Pool singleton thread-safety | API / Backend (`app/db/supabase.py`) | — | In-process module state; no DB/network tier involved |

## Standard Stack

### Core
No new libraries. This phase uses only what is already installed and pinned:

| Library | Version (installed) | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `psycopg[binary,pool]` | 3.3.4 (pinned, `pyproject.toml`) | DDL execution via bootstrap, parameterized SQL | Already the project's sole DB driver; no change needed |
| Python stdlib `re` | 3.12 | Email-regex + name-token scrubbing | Matches existing project convention (`app/email/clean.py` uses module-level compiled `re.compile(...)` patterns) — no third-party PII/regex library needed for two deterministic patterns |
| `pytest` | pinned dev dep | New tests: scrub ordering, fail-open, index static guard, projection SQL assertion | Existing test runner; `uv run pytest -q` |

### Supporting
None — no new runtime or dev dependencies are required for this phase.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled `re` scrubber | A PII-detection library (e.g. `presidio`, `scrubadub`) | Massive overkill for two deterministic patterns (email regex + roster-name substring match against an in-memory list); adds a dependency + package-legitimacy burden for a data-layer hygiene phase whose whole point is minimizing surface area. Rejected. |
| SQL-computed `summary_gate_reason`/`employee_count` aliases | Python-side post-processing of full JSONB after SELECT | Defeats the purpose of D-8-07 ("no JSONB blob crosses the wire") — the whole point is the DB computes the scalar, not the app fetching the blob and then discarding most of it. Rejected. |

**Installation:** None — no `uv add` needed. Confirm nothing changed:
```bash
uv sync --no-dev   # no-op; pyproject.toml/uv.lock untouched by this phase
```

**Version verification:** N/A — no packages added or upgraded this phase.

## Package Legitimacy Audit

**Not applicable.** This phase installs zero external packages — every capability (regex scrubbing, JSONB SQL expressions, index DDL, static-file test parsing) is covered by the stdlib and the project's existing pinned dependencies (`psycopg`, `pytest`). The Package Legitimacy Gate is skipped per its own scope ("whenever this phase installs external packages").

## Architecture Patterns

### System Architecture Diagram

```
                    ┌─────────────────────────────────────────────┐
                    │         3 error boundaries (unchanged        │
                    │         call sites, enriched call)            │
                    │                                               │
  orchestrator.py   │  run_pipeline() catch-all  (:188)            │
  :188, :667        │  resume_pipeline() catch-all (:667)          │
  main.py :506       │  approve() delivery boundary (:506)          │
                    └───────────────┬───────────────────────────────┘
                                    │  record_run_error(run_id, reason,
                                    │      detail=str(exc), stage="...",
                                    │      roster=roster_or_None)
                                    ▼
                    ┌───────────────────────────────────────────────┐
                    │  repo.record_run_error()  (repo.py:370)        │
                    │                                                │
                    │  1. read current status (existing WR-04 guard) │
                    │  2. IF terminal -> log + return (unchanged)    │
                    │  3. NEW: _build_error_detail(stage, exc, roster)│
                    │       -> scrub(str(exc)) THEN truncate(200)    │
                    │       -> fail-open: any scrub exception ->     │
                    │          detail=None, error_reason unaffected  │
                    │  4. UPDATE error_reason (unchanged) +          │
                    │     error_detail (NEW nullable col)            │
                    │  5. set_status(ERROR)  (unchanged, FIX B)      │
                    └───────────────┬───────────────────────────────┘
                                    │
                                    ▼
                    ┌───────────────────────────────────────────────┐
                    │  payroll_runs.error_detail  (NEW nullable TEXT)│
                    └───────────────┬───────────────────────────────┘
                                    │  read on GET /runs/{id}
                                    ▼
                    ┌───────────────────────────────────────────────┐
                    │  run_detail.html error banner (:66-69)         │
                    │  existing line: "Error — {error_reason}"       │
                    │  NEW conditional 2nd line: {error_detail}      │
                    │  when-present, byte-identical fallback for NULL│
                    └───────────────────────────────────────────────┘

  Separately (no data dependency on the above):

  load_all_runs()  ──SQL──▶  explicit column list + 2 computed aliases
  (repo.py:1088)             (summary_gate_reason, employee_count)
                                    │
                                    ▼
                         runs_list.html Summary cell
                         (switches from run.decision.gate_reasons[0] /
                          run.extracted_data.employees|length to the
                          2 new SQL aliases — D-8-08)

  schema.sql (4 new CREATE INDEX IF NOT EXISTS) ──▶ idempotent bootstrap
                                                     ──▶ live Supabase
                                                     (human checkpoint verifies
                                                      via pg_indexes)
```

### Recommended Project Structure
No new files/folders — all changes land inside existing modules:
```
app/
├── db/
│   ├── repo.py          # record_run_error gains detail param + centralized scrub call;
│   │                     # load_all_runs SQL rewritten (explicit cols + 2 aliases)
│   └── schema.sql        # +1 ALTER TABLE ADD COLUMN IF NOT EXISTS error_detail TEXT;
│                          # +4 CREATE INDEX IF NOT EXISTS; NEEDS_CLARIFICATION CHECK swap
├── models/
│   └── status.py         # RunStatus.NEEDS_CLARIFICATION member removed
├── pipeline/
│   └── orchestrator.py   # 2 call sites pass detail=str(exc), stage=, roster= (if in scope)
├── main.py                # 1 call site (approve boundary) passes detail=str(exc), stage=
└── templates/
    ├── run_detail.html    # +1 conditional line for error_detail
    └── runs_list.html      # Summary cell aliases swapped

tests/
├── test_persistence.py        # extend record_run_error tests: detail param, scrub ordering
├── test_status_drift.py        # new index static guard + updated status count (11→10)
├── test_dashboard.py            # load_all_runs projection assertion, error_detail rendering
└── (new or extended)            # dedicated scrubber unit tests if pulled into a helper module
```

### Pattern 1: Centralized scrub-then-truncate inside `record_run_error`
**What:** All PII scrubbing logic lives in ONE function called from inside `repo.record_run_error`, not duplicated at each of the 3 call sites. Call sites pass the raw exception object (or `str(exc)`) plus a `stage` label and (optionally) the `roster` object already in their local scope.
**When to use:** Any time a new error boundary is added in the future — it gets scrubbing for free by calling `record_run_error`, matching the existing "single funnel" architecture note in CONTEXT.md.
**Example (design sketch, not yet in codebase):**
```python
# app/db/repo.py — additive change to record_run_error's signature and body

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_REDACTED = "[REDACTED]"

def _scrub(message: str, roster=None) -> str:
    """Deterministic, fail-open PII scrub. NEVER loads roster from DB (D-8-01b)."""
    scrubbed = _EMAIL_RE.sub(_REDACTED, message)
    if roster is not None:
        for employee in roster.employees:
            names = [employee.full_name, *employee.known_aliases]
            for name in names:
                if name:
                    scrubbed = scrubbed.replace(name, _REDACTED)
    return scrubbed


def _build_error_detail(stage: str, exc: Exception, roster=None) -> str | None:
    """Scrub-THEN-truncate (D-8-01 ordering); fail-open on any scrub error (D-8-01b)."""
    try:
        scrubbed = _scrub(str(exc), roster=roster)
        return f"{stage}: {scrubbed}"[:200]
    except Exception:  # noqa: BLE001 — diagnostics must never break diagnostics
        return None


def record_run_error(
    run_id: uuid.UUID,
    reason: str,
    *,
    detail_exc: Exception | None = None,
    stage: str | None = None,
    roster=None,
    conn=None,
) -> None:
    ...
    detail = None
    if detail_exc is not None and stage is not None:
        detail = _build_error_detail(stage, detail_exc, roster=roster)
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            current = c.execute(...).fetchone()
            if current is not None and current[0] in _TERMINAL_STATUSES:
                return
            c.execute(
                "UPDATE payroll_runs SET error_reason = %s, error_detail = %s, "
                "updated_at = now() WHERE id = %s",
                (reason, detail, str(run_id)),
            )
            set_status(run_id, RunStatus.ERROR, conn=c)
```
*Design note, not yet verified against a Source URL — this is a design sketch derived from the existing `record_run_error` body (repo.py:370-404) re-verified this session, not a copy-paste from any external doc. Exact parameter names are Claude's Discretion per CONTEXT.md.*

### Pattern 2: NULL-safe SQL-computed projection aliases (D-8-07)
**What:** `load_all_runs` replaces `SELECT pr.*` with an explicit scalar column list plus two computed SQL expressions, guarding the NULL/missing-key case so `jsonb_array_length` never errors.
**When to use:** Any list-view query that currently ships a full JSONB blob to render one summary field.
**Verified fact (this session, via WebSearch cross-check):** `jsonb_array_length(NULL::jsonb)` returns SQL NULL, it does NOT raise — so the "guard" requirement in D-8-07 is about avoiding a NULL `employee_count` in the rendered dict (which the template would need `or 0` / `| default(0)` to handle), not about a runtime SQL error. Still, wrap in `COALESCE` for a clean `0` rather than pushing the NULL-to-zero conversion into Jinja.
```sql
-- Source: verified against PostgreSQL JSON Functions docs
-- (https://www.postgresql.org/docs/current/functions-json.html) — jsonb_array_length
-- returns NULL on NULL input, confirmed via WebSearch cross-check this session.
SELECT
    pr.id, pr.business_id, pr.status, pr.created_at, pr.updated_at,
    b.name AS business_name,
    pr.decision->'gate_reasons'->>0 AS summary_gate_reason,
    COALESCE(
        jsonb_array_length(pr.extracted_data->'employees'), 0
    ) AS employee_count
FROM payroll_runs pr
JOIN businesses b ON pr.business_id = b.id
ORDER BY pr.created_at DESC
```
**Note on exact column set:** CONTEXT.md D-8-07/discretion says "whatever the runs-list row actually renders — verify against the template at implementation time." Verified this session: `runs_list.html` (lines 56-72) renders `run.created_at`, `run.business_name`, `run.status` (via `badge_class`/`badge_label` filters), and the Summary cell (currently `run.decision.gate_reasons[0]` / `run.extracted_data.employees|length`, to be replaced). `run.id` is also used for the row's `data-run-id` and the "View" link href. `business_id` and `updated_at` are not directly rendered by `runs_list.html` but `updated_at` at minimum should stay for consistency with `RUN_COLS`'s existing inclusion pattern (repo.py:85-89 notes it was a past bug source when omitted) — confirm at implementation time whether the runs-list route or any JS polling (the in-flight poll script referenced near run_detail.html:60) reads it.

### Pattern 3: Composite index column order derived from traced predicates, not audit guesses (D-8-09)
**What:** `(run_id, direction, send_state)` as the column order for the new `email_messages` index.
**Verified predicates this session (repo.py, live source):**

| Function | Line(s) | Predicate | Uses index prefix |
|----------|---------|-----------|-------------------|
| `get_outbound_message_id` | 769-771 | `run_id = %s AND direction = 'outbound' AND purpose = %s AND send_state = 'sent'` | `(run_id, direction, send_state)` — `purpose` is a 4th column not in this index but `uq_email_run_purpose` already covers `(run_id, purpose)` |
| `get_outbound_references_chain` | 824-828 | `run_id = %s AND direction = 'outbound' AND send_state = 'sent'` + `ORDER BY created_at DESC LIMIT 1` | Full 3-column match; index avoids a sort if `created_at` were appended, but per-run outbound row count is tiny (≤3 in this schema — clarification/confirmation/field-regression) so this is a hygiene win, not a measured-need one (matches D-8-09's own framing) |
| `load_outbound_emails` | 843-848 | `run_id = %s AND direction = 'outbound'` + `ORDER BY created_at` | 2-column prefix match; `send_state` unused here but doesn't hurt as a trailing column |
| `load_thread_messages` | 964-971 | `run_id = %s OR id = (subquery)` | OR predicate — Postgres can use the index for the `run_id = %s` branch (bitmap OR with a primary-key lookup for the second branch), but this is NOT the query this composite index was justified by |
| `find_awaiting_reply_for_header` / `find_any_run_for_header` | 1008-1058 | JOIN `email_messages em ON em.run_id = pr.id AND em.direction = 'outbound'` + header LIKE match | `(run_id, direction)` prefix helps the join; the LIKE-anchored header match itself is not index-servable by this composite |

**Conclusion:** `(run_id, direction, send_state)` is the correct column order — it's a strict prefix match for 2 of 3 named predicates and a 2-column prefix match for the third and for the JOIN condition in the header-match finders. This confirms D-8-09's instruction that the audit's guessed order should not be blindly copied, and independently arrives at the same order CONTEXT.md already names — the verification step's value here is confirming the order is right for the RIGHT reasons (traced predicates), not rubber-stamping.

### Pattern 4: Single-transaction DROP+ADD CHECK migration (D-7.5-03a, reused for NEEDS_CLARIFICATION removal)
**What:** The `email_messages.purpose` CHECK swap at schema.sql:178-199 is the exact template to copy for the `payroll_runs.status` CHECK swap (removing `'needs_clarification'`).
**Source:** `app/db/schema.sql` lines 178-199 (live source, this session) — the introspect-by-name-then-drop, explicit-literal-re-add pattern, all inside one `DO $$ ... END $$;` block so a mid-migration failure can never leave the CHECK dropped-but-not-re-added.
```sql
-- Adapted pattern for payroll_runs.status (mirrors email_messages.purpose swap above)
DO $$
DECLARE
    _con_name TEXT;
BEGIN
    SELECT conname INTO _con_name
    FROM pg_constraint
    WHERE contype = 'c'
      AND conrelid = 'payroll_runs'::regclass
      AND conname LIKE '%status%';
    IF _con_name IS NOT NULL THEN
        EXECUTE 'ALTER TABLE payroll_runs DROP CONSTRAINT ' || quote_ident(_con_name);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'payroll_runs_status_check'
          AND conrelid = 'payroll_runs'::regclass
    ) THEN
        ALTER TABLE payroll_runs ADD CONSTRAINT payroll_runs_status_check
            CHECK (status IN (
                'received','extracting','awaiting_reply','computed',
                'awaiting_approval','approved','sent','reconciled',
                'rejected','error'
            ));
    END IF;
END;
$$;
```
**Pre-migration guard (from CONTEXT.md, verified as necessary):** `ADD CONSTRAINT` validates ALL existing rows against the new CHECK. Before running this on the live DB, the human checkpoint MUST run `SELECT count(*) FROM payroll_runs WHERE status = 'needs_clarification'` and confirm `0` — a legacy row in that status would fail the swap and leave the constraint dropped if not handled (this is exactly why the DROP+ADD is one transaction: a failed ADD rolls back the DROP too, so worst case is a no-op, not a half-migrated table — but a human should still verify the count before attempting, per the checkpoint discipline).

### Anti-Patterns to Avoid
- **Scrubbing at each call site instead of centrally:** would let a future 4th error boundary forget to scrub, silently reintroducing the exact PII leak this phase closes. Centralize in `record_run_error`.
- **Truncate-then-scrub:** explicitly named and rejected in D-8-01 — cutting a string mid-PII-token defeats the regex. The new tests (D-8-04a) exist specifically to catch a regression here.
- **Loading the roster from the DB inside the error path:** D-8-01b is explicit — the DB may be the thing that's down. Roster scrubbing must be best-effort using whatever the caller already holds; `roster=None` degrades to regex-only, never a fresh query.
- **A second index on `businesses.contact_email`:** would be a pure-write-overhead duplicate of the existing UNIQUE-constraint-backed index. Verify, don't duplicate (D-8-09).
- **Copying the email_messages column order from the audit without checking predicates:** explicitly called out in CONTEXT.md — the audit's guess must be re-derived from live query text, which this research does (see Pattern 3 table above).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PII detection at enterprise scale | A general-purpose PII classifier/NER model | The existing deterministic pattern: email regex (stdlib `re`) + exact roster-name substring match (list already in memory) | The phase's PII surface is narrow and enumerable — exactly 2 categories (emails, roster names/aliases/business contact strings) already available as pure in-memory values. A general classifier is unverifiable, slow, and adds a dependency for a data-layer hygiene phase whose thesis is minimal, auditable surface area. |
| Schema migrations across environments | Alembic / a migration framework | The project's existing `schema.sql` + idempotent `ADD COLUMN IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` / DO-block CHECK-swap pattern | Explicitly out of scope per CLAUDE.md ("no Alembic — schema.sql is the source of truth") and already proven out in Phase 2/7.5. A single-author greenfield demo does not need a versioned migration framework. |
| Index selection | Guessing or copying from an audit doc | Trace the actual query predicates in the live repo.py source, as done in this research (Pattern 3) | An unverified guess risks either a useless index (wrong column order = no prefix match) or a missing one; the audit's own guess was flagged stale by D-8-09 and this research independently re-derives the same conclusion FROM the traced predicates. |

**Key insight:** Everything in this phase is either (a) already-proven project pattern reused verbatim (DO-block CHECK swap, `ADD COLUMN IF NOT EXISTS`, `FakeConnection` test style) or (b) two small deterministic regex/substring rules. There is no case in this phase where reaching for a library beats the 10-20 lines of stdlib code — that itself is evidence the phase is correctly scoped as "hygiene," not a feature build.

## Runtime State Inventory

> Included because this phase folds in a rename/removal: `NEEDS_CLARIFICATION` status value removal (folded todo 260623-06) is a live-value removal, which is state-inventory-relevant even though it's not a full rename phase.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `payroll_runs.status = 'needs_clarification'` — a live row in this status would fail the CHECK-swap ADD CONSTRAINT. Verified this session: `_clarify()` (orchestrator.py) routes to `AWAITING_REPLY`, never writes `NEEDS_CLARIFICATION` — the enum member is declared but never assigned by any code path (confirmed by grep: no `RunStatus.NEEDS_CLARIFICATION` assignment anywhere in `app/`). | Human checkpoint MUST run `SELECT count(*) FROM payroll_runs WHERE status = 'needs_clarification'` before the live CHECK swap and confirm `0` (CONTEXT.md already specifies this; re-confirmed here as necessary, not optional, because ADD CONSTRAINT validates all existing rows). No data migration expected to be needed, but the check is not skippable. |
| Live service config | None — this phase touches no n8n/Datadog/Tailscale/Cloudflare-style external service config. All 4 touch points are pure Python source + one CHECK constraint. | None. |
| OS-registered state | None — no Task Scheduler, pm2, launchd, systemd involved. Single Render web service (render.yaml, no workers flag = 1 uvicorn process). | None. |
| Secrets/env vars | None — no env var or secret name is renamed or removed by this phase (no `error_detail`-related config; scrubber regexes are hardcoded, not env-configurable). | None. |
| Build artifacts | None — no package renamed, no `pyproject.toml`/`uv.lock` change (zero new dependencies). | None. |

**The canonical question answered:** After every file in the repo is updated for the NEEDS_CLARIFICATION removal, the only runtime system with the old value cached is the live `payroll_runs` table's status column — verified via a pre-migration `SELECT count(*)` guard, not assumed.

## Common Pitfalls

### Pitfall 1: Truncate-then-scrub PII leak
**What goes wrong:** If `str(exc)[:200]` truncates BEFORE the redaction regex runs, a sensitive string straddling the 200-char boundary (e.g. `"...client email: maria.gonzalez@exam"`) has its trailing half cut off, so the email regex no longer matches the remnant — partial PII (a real name + a partial, still-identifying email fragment) leaks into the DB.
**Why it happens:** Truncation and scrubbing look like they can be applied in either order if you're not thinking about string-boundary interaction; naive implementations often truncate first because it feels like "step 1: shrink the input."
**How to avoid:** Scrub the FULL `str(exc)` first, THEN truncate to 200 chars (D-8-01, locked). The stage-prefix is applied to the scrubbed-then-truncated result, or applied before truncation and included in the 200-char budget — CONTEXT.md's example shape (`"extract: 2 validation errors for ExtractionPayload…"`) suggests the prefix eats into the budget; confirm exact truncation point (prefix-inclusive vs prefix-additional) at implementation time, but the SCRUB-then-TRUNCATE ordering itself is non-negotiable.
**Warning signs:** A test that seeds a sensitive string exactly at the 200-char boundary and asserts it's NOT present in the stored detail (D-8-04a) — if this test is missing or trivially placed (sensitive string at position 10, not position ~195-205), the ordering bug can hide.

### Pitfall 2: Diagnostics feature breaks the very error path it's meant to observe
**What goes wrong:** If the new scrub/detail-building code itself raises (e.g. a roster object with an unexpected shape, a regex catastrophic-backtracking edge case, an encoding error), and that exception is NOT caught, `record_run_error` itself fails — meaning a run that hit a real production error now ALSO fails to record ANY error_reason, turning a diagnosable failure into a silent hang. This is strictly worse than the status quo.
**Why it happens:** Diagnostic/observability code is often written assuming happy-path inputs because "it's just for debugging" — but it runs in the error path, which by definition sees the messiest, least-anticipated inputs.
**How to avoid:** D-8-01b is explicit: wrap the detail-building step in its own try/except so that ANY exception there falls back to today's type-name-only write (the existing `error_reason` UPDATE must proceed regardless of what `_build_error_detail` does). Test this directly (D-8-04b): pass a scrubber/roster that raises, assert `record_run_error` still succeeds and writes the type-name fallback.
**Warning signs:** A test suite that only exercises the happy path of the scrubber (valid roster, valid exception message) without a "scrubber raises" case would let this regress silently.

### Pitfall 3: NULL vs missing-key confusion in the JSONB projection
**What goes wrong:** `decision->'gate_reasons'->>0` and `jsonb_array_length(extracted_data->'employees')` both need to handle THREE distinct cases per run: the JSONB column itself is SQL NULL (run hasn't reached that stage yet), the key exists but is a JSON `null`, or the key is simply absent from the object. All three produce SQL NULL when chained through `->`/`->>`, which is actually the convenient case — Postgres's `->` operator on a NULL input returns NULL rather than erroring, so the chain is naturally NULL-safe already. The trap is assuming you need defensive `CASE WHEN` logic when a `COALESCE` at the outermost level is sufficient.
**Why it happens:** JSONB NULL-propagation semantics are easy to get wrong from memory; both under-guarding (an early run with `decision IS NULL` causing a genuine SQL error) and over-guarding (unnecessary CASE/EXISTS checks) are seen in the wild.
**How to avoid:** Verified this session via WebSearch cross-check against PostgreSQL JSON function docs: `jsonb_array_length(NULL)` returns NULL, not an error. A single outer `COALESCE(jsonb_array_length(...), 0)` is sufficient — no nested CASE needed. Same for `->>'0'` on a NULL `decision` column: the chain short-circuits to NULL, which Jinja already renders gracefully (the current template's `{% if run.decision and run.decision.gate_reasons %}` guard shows this NULL-handling is already the established pattern client-side; the new aliases make it happen server-side instead).
**Warning signs:** A test seeding a run with `decision = NULL` (e.g. a run still at `received`/`extracting`) that asserts `load_all_runs()` doesn't raise and returns `summary_gate_reason = None`, `employee_count = 0`.

### Pitfall 4: `record_run_error` signature change breaks existing call-site assumptions across ~7 test files
**What goes wrong:** `record_run_error` is called/mocked/monkeypatched in `conftest.py` (`InMemoryRepo.record_run_error`), `test_delivery.py`, `test_gateway.py`, `test_persistence.py`, `test_alias_write.py` (monkeypatched to a no-op lambda), `test_threading.py` (has its own fake with matching signature), and the 3 real call sites. Adding new keyword-only params is safe IF they're all optional with sensible defaults — but `InMemoryRepo.record_run_error` (conftest.py:331) and `test_threading.py`'s fake (line ~700) both hard-code the 2-positional-arg signature and would silently NOT exercise the new `detail`/`stage`/`roster` params unless updated, meaning webhook/orchestrator-level integration tests would pass while giving zero coverage to the new behavior through the full stack.
**Why it happens:** Adding an optional kwarg to a widely-mocked function is technically backward-compatible (no test breaks), which can create false confidence that "everything still works" when actually the new logic is untested end-to-end.
**How to avoid:** After adding the param, update `InMemoryRepo.record_run_error` (conftest.py:331) and `test_threading.py`'s fake to accept and route the new kwargs too (even if they just no-op them), so integration-style tests exercise the new call shape without erroring on unexpected kwargs. The dedicated unit tests (D-8-04) against the REAL `repo.record_run_error` with `FakeConnection` are the actual proof of the scrub logic — the fakes just need to not choke on the new call shape.
**Warning signs:** A `TypeError: record_run_error() got an unexpected keyword argument` surfacing only when running the full suite (not the new unit tests in isolation) — check `InMemoryRepo` and the `test_threading.py` fake explicitly before considering the phase test-complete.

## Code Examples

### Verified: current `record_run_error` full body (repo.py:370-404, this session)
```python
# Source: live repo.py, verified 2026-07-02
def record_run_error(run_id: uuid.UUID, reason: str, conn=None) -> None:
    with _conn_ctx(conn) as (c, owns):
        with c.transaction() if owns else _nulltx():
            current = c.execute(
                "SELECT status FROM payroll_runs WHERE id = %s", (str(run_id),)
            ).fetchone()
            if current is not None and current[0] in _TERMINAL_STATUSES:
                logger.info(
                    "record_run_error skipped: run %s is terminal (%s) — not "
                    "clobbering to ERROR (WR-04). reason was: %s",
                    run_id, current[0], reason,
                )
                return
            c.execute(
                "UPDATE payroll_runs SET error_reason = %s, updated_at = now() WHERE id = %s",
                (reason, str(run_id)),
            )
            set_status(run_id, RunStatus.ERROR, conn=c)
```
This is the exact function the phase extends. The new `error_detail` column write slots into the same `UPDATE` statement (adding `error_detail = %s` and a new bound param) — no new query, no new transaction.

### Verified: three call sites (this session, exact line numbers confirmed)
```python
# app/pipeline/orchestrator.py:179-188 (run_pipeline catch-all)
try:
    _run(run_id, llm=llm)
except Exception as exc:  # noqa: BLE001
    reason = type(exc).__name__
    logger.warning("run %s failed: %s", run_id, reason)
    repo.record_run_error(run_id, reason)   # <- gains detail=str(exc), stage="pipeline"

# app/pipeline/orchestrator.py:661-667 (resume_pipeline catch-all)
except Exception as exc:  # noqa: BLE001
    reason = type(exc).__name__
    logger.warning("resume of run %s failed: %s", run_id, reason)
    repo.record_run_error(run_id, reason)   # <- gains detail=str(exc), stage="resume"

# app/main.py:502-506 (approve() delivery boundary)
except Exception as exc:  # noqa: BLE001
    logger.warning("delivery of run %s failed: %s", run_id, type(exc).__name__)
    repo.record_run_error(run_id, type(exc).__name__)  # <- gains detail=str(exc), stage="delivery"
```
**Roster availability caveat (verified this session):** In `run_pipeline`'s `_run()` (line 199) and `resume_pipeline` (line 247), `roster = repo.load_roster_for_business(...)` executes early — but if the exception is raised BEFORE that line (e.g. `load_run` returns `None` at line 193-194 or 245-246, raising `ValueError`), `roster` is undefined in the enclosing scope at the point of the `except` block. Any implementation passing `roster=roster` into `record_run_error` from these catch blocks must guard for `UnboundLocalError` — e.g. initialize `roster = None` at the top of `_run`/`resume_pipeline`, or wrap the `record_run_error` call site's roster lookup in a safe accessor. `main.py`'s `approve()` boundary has no roster in scope at all (never loads one) — `roster=None` there is correct, not a gap, since D-8-01b already specifies `roster=None` degrades to regex-only.

### Verified: schema.sql CHECK-swap template to reuse (lines 174-199, this session)
See Pattern 4 above for the full adapted block.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `error_reason = type(exc).__name__` only (D-A1-03) | `error_reason` unchanged + NEW `error_detail` (scrubbed message, nullable) | This phase (Phase 8) | A production failure like the v1 webhook 500 becomes diagnosable from the dashboard without log access — the stated OPS2-01 outcome |
| `SELECT pr.*` in `load_all_runs` | Explicit scalar column list + 2 computed SQL aliases | This phase | Schema creep can no longer silently leak new JSONB columns to the dashboard route; smaller payload per list-view request |
| No indexes at all in schema.sql | 4 new `CREATE INDEX IF NOT EXISTS` statements | This phase | First indexes the project has ever declared explicitly (schema.sql currently has zero `CREATE INDEX` statements, confirmed by grep this session) |
| `NEEDS_CLARIFICATION` declared but dead (never written) | Removed from enum + CHECK | This phase (folded todo 260623-06) | Removes an invisible dashboard dead-end value; the drift-guard test count drops from 11 to 10 |

**Deprecated/outdated:** None — this phase does not touch any deprecated library or API; it is entirely internal schema/code hygiene.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Exact final parameter names for `record_run_error` (`detail_exc`, `stage`, `roster` vs alternatives) are a design sketch, not yet implemented — CONTEXT.md explicitly leaves "record_run_error mechanics" as Claude's Discretion | Pattern 1 (Code Examples) | Low — purely a naming/shape choice within an already-locked behavioral contract (D-8-01/D-8-01b/D-8-02); any reasonable shape satisfies the success criteria |
| A2 | The exact scalar column set for `load_all_runs` (whether `business_id`/`updated_at` are kept) is deferred to implementation-time template verification, per CONTEXT.md's own instruction | Pattern 2 | Low — CONTEXT.md already flags this as intentionally deferred; the research confirms current template usage but the final list is an implementation decision, not a research gap |
| A3 | `jsonb_array_length(NULL)` returns NULL (not an error) — verified via WebSearch cross-check against PostgreSQL docs, not against a live query in THIS database (no live DB connection available in this research session) | Pattern 2, Pitfall 3 | Low — this is well-established, stable Postgres JSON-function behavior across all supported versions (9.5+ per the docs page checked); if wrong, the fix is a one-line COALESCE addition which the plan already recommends defensively |

**All other claims in this research were verified directly against live source code in this session** (repo.py, schema.sql, orchestrator.py, main.py, status.py, templates, conftest.py, test_status_drift.py, render.yaml, Dockerfile) or against the project's own committed CONTEXT.md/REQUIREMENTS.md/STATE.md — no training-data guesses about THIS codebase's structure were used unverified.

## Open Questions (RESOLVED)

1. **Does `render.yaml`'s single-instance deploy make the WR-02 pool-singleton race purely theoretical, or does uvicorn's threadpool for sync routes/BackgroundTasks make it real even at 1 process?**
   - What we know: `render.yaml` declares one `type: web` service with no `numInstances`/scaling block (effectively 1 instance on Render free tier); the Dockerfile CMD runs `uvicorn app.main:app` with no `--workers` flag (1 process). But FastAPI/Starlette run sync path operations (including `BackgroundTasks`) in a threadpool executor within that single process — so two concurrent first-requests (e.g. an inbound webhook POST and a concurrent dashboard GET) could both hit `get_pool()`'s `if _pool is None:` check before either finishes constructing the pool.
   - What's unclear: Whether this has ever actually manifested (creating two pools, one leaked) — no incident evidence either way in STATE.md's blockers/concerns.
   - Recommendation: Treat as real (not purely theoretical) given the threadpool mechanism, and implement the minimal fix: either a `threading.Lock()` around the check-then-create in `get_pool()`, or document explicitly why single-worker Render deployment makes the exposure window negligible (accepting the documented-not-fixed option is legitimate per CONTEXT.md's phrasing "guard the module-level ConnectionPool init ... or document why single-worker makes it safe" — but the reasoning above suggests "single-worker" alone does NOT make it safe against the threadpool race, so documentation-only is likely the wrong choice unless a stronger argument is found at implementation time).

2. **Exact truncation semantics: does the 200-char budget include the `"{stage}: "` prefix or is truncation applied to the message body only, with the prefix always intact?**
   - What we know: D-8-02 example shape is `"extract: 2 validation errors for ExtractionPayload…"` — a single string. D-8-01 says "the result is THEN truncated to 200 chars" after scrubbing, implying the whole composed string (prefix + scrubbed message) is what's truncated to 200.
   - What's unclear: Whether a case exists where `stage` itself could be so long it eats a meaningful fraction of the 200-char budget (unlikely — stage names are short literals like "extract"/"resume"/"delivery") — this is a non-issue in practice but worth confirming the test (D-8-04a straddle-boundary case) accounts for the prefix length when constructing the boundary-straddling test string.
   - Recommendation: Compose `f"{stage}: {scrubbed}"` first, THEN slice `[:200]` on the composed string — matches the literal reading of D-8-01/D-8-02 and is what the Code Examples pattern above implements.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `uv` | All dev/test commands | ✓ | (project-pinned via `.python-version` 3.12) | — |
| `pytest` | New/extended tests | ✓ | pinned dev dep; full suite ran green (492 passed, 36 skipped) this session | — |
| Local Postgres or `DATABASE_URL` | Live-DB migration checkpoint (index creation, CHECK swap, pre-migration count guard) | Not verified in this research session (no `DATABASE_URL` probed/connected) | — | The live checkpoint is a human-run, blocking gate per project convention (D-8-10) — not something this research session executes; CI/hermetic tests do not need a live DB (matches project's "no live-DB tests in CI" rule) |

**Missing dependencies with no fallback:** None — the live-DB checkpoint is BY DESIGN a human-run step, not an automated dependency this phase's automated tests require.

**Missing dependencies with fallback:** None applicable — all automated verification (static schema.sql parsing, FakeConnection SQL assertions, scrub-logic unit tests) is DB-free by design, matching `test_status_drift.py`'s own "no DB connection needed" self-check pattern (which this phase's new index static guard should copy, including its `test_no_db_connection_needed` AST-based import guard).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (pinned dev dependency), registered via `[tool.pytest.ini_options]` in `pyproject.toml` |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`, lines 38-43) — markers `integration` (live DB) and `live_llm` (real API) already registered |
| Quick run command | `uv run pytest tests/test_status_drift.py tests/test_persistence.py tests/test_dashboard.py -q` |
| Full suite command | `uv run pytest -q` (verified this session: 492 passed, 36 skipped, 122s — the skips are `integration`/`live_llm`-marked tests requiring `DATABASE_URL`/live API keys, correctly absent in this sandboxed research session) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| OPS2-01 (success criterion 1) | `error_detail` contains scrubbed message, excludes PII | unit | `uv run pytest tests/test_persistence.py -k record_run_error -q` | ✅ extend existing file (record_run_error tests already there at lines 139-194) |
| OPS2-01 (D-8-04a) | Scrub-before-truncate ordering (sensitive string straddles 200-char boundary) | unit | `uv run pytest tests/test_persistence.py -k straddle -q` (new test, name illustrative) | ❌ Wave 0 — new test |
| OPS2-01 (D-8-04b) | Fail-open: scrubber raises or roster=None → type-name-only fallback still written | unit | `uv run pytest tests/test_persistence.py -k fail_open -q` (new test) | ❌ Wave 0 — new test |
| OPS2-02 (success criterion 2) | 4 new indexes present in schema.sql (static guard) | unit (hermetic) | `uv run pytest tests/test_status_drift.py -k index -q` (extend file with new index-guard test class, mirroring `TestEnumCheckDrift`) | ❌ Wave 0 — extend `test_status_drift.py` |
| OPS2-02 (success criterion 2, live proof) | Indexes actually applied + queryable via `pg_indexes` after bootstrap | manual-only (blocking human checkpoint) | `psql $DATABASE_URL -c "SELECT indexname FROM pg_indexes WHERE tablename IN ('email_messages','payroll_runs','businesses');"` after `uv run python -m app.db.bootstrap` | N/A — manual by design (D-8-10, matches prior live-migration checkpoints) |
| OPS2-02 (success criterion 3) | `load_all_runs` names explicit columns, no `pr.*` | unit (hermetic, FakeConnection) | `uv run pytest tests/test_dashboard.py -k load_all_runs -q` (new test using `fake_conn` fixture, asserting `"pr.*"` not in `fake_conn.all_sql()` and specific column names ARE present) | ❌ Wave 0 — new test |
| OPS2-02 (D-8-08 template consumer) | `runs_list.html` renders `summary_gate_reason`/`employee_count` aliases correctly (including NULL cases) | integration (route-level, existing `test_runs_list_returns_200`-style) | `uv run pytest tests/test_dashboard.py -k runs_list -q` | ✅ extend existing `test_runs_list_returns_200` (line 35) and related tests |
| Folded: NEEDS_CLARIFICATION removal | Enum + CHECK removed, drift guard stays green, count 11→10 | unit (hermetic) | `uv run pytest tests/test_status_drift.py tests/test_models_contracts.py -q` | ✅ existing files, both need line-level updates (status.py enum member removal auto-fixes `test_status_drift.py`'s dual-source check; `test_status_exact_count_is_eleven` needs its literal `11`→`10` and rename; `test_models_contracts.py:130`'s expected-values list needs the value removed) |
| Folded: WR-02 pool-singleton guard | Thread-safety guard (lock) present, or documented safe | unit (if lock added) | `uv run pytest tests/ -k supabase -q` (new/extended test on `app/db/supabase.py`, e.g. asserting `get_pool()` uses a lock or documenting the safety argument as a docstring assertion) | ❌ Wave 0 if a code guard is added; N/A if documentation-only is chosen (see Open Question 1) |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_status_drift.py tests/test_persistence.py tests/test_dashboard.py -q` (targets the 3 files this phase touches most; ~1-3s based on `test_status_drift.py`'s 0.02s baseline)
- **Per wave merge:** `uv run pytest -q` (full suite; ~122s baseline this session, no live-DB/live-LLM tests run without env vars set)
- **Phase gate:** Full suite green before `/gsd-verify-work`, PLUS the D-8-10 live checkpoint (`pg_indexes` query against bootstrapped Supabase) run and confirmed by a human before phase close

### Wave 0 Gaps
- [ ] `tests/test_persistence.py` — extend with D-8-04a (straddle-boundary scrub-before-truncate) and D-8-04b (fail-open) cases, using the existing `fake_conn` fixture and `roster_from_seed` fixture (both already in `conftest.py`)
- [ ] `tests/test_status_drift.py` — extend with a new index-guard test class (mirror `TestEnumCheckDrift`'s pattern: parse `schema.sql` for `CREATE INDEX IF NOT EXISTS` statements, assert the 4 named indexes exist with correct column lists; also assert the `businesses.contact_email` UNIQUE constraint is still present as the substitute proof for that hot path); update `test_status_exact_count_is_eleven` to `test_status_exact_count_is_ten` (or similar) after NEEDS_CLARIFICATION removal
- [ ] `tests/test_dashboard.py` — new test asserting `load_all_runs`'s SQL text contains no `pr.*` / `SELECT *` and does name explicit columns (FakeConnection SQL-assertion style, matching the established Phase 2 pattern); extend `test_runs_list_returns_200`-adjacent tests to cover the new alias rendering including a NULL-decision run
- [ ] `tests/test_models_contracts.py` — update line 130's expected-values list to drop `"needs_clarification"`
- [ ] Framework install: none — `pytest` already present; no new test framework needed

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Phase touches no auth surface |
| V3 Session Management | no | Phase touches no session surface |
| V4 Access Control | no | No new routes; existing access model (single-operator dashboard, no auth per project's documented free-tier demo scope) unchanged |
| V5 Input Validation | no (indirect) | `error_detail`'s INPUT is an internal exception message, not user-facing input requiring validation — the relevant control here is output sanitization (redaction), covered below under a data-protection lens, not V5 |
| V6 Cryptography | no | No crypto surface touched |
| V9 Data Protection (informal — ASVS V8 in some version numbering; treating as the operative category) | **yes** | Deterministic PII redaction (regex email match + exact roster-name/alias substring match) applied BEFORE any exception-derived text is persisted or rendered — the core OPS2-01 control |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Sensitive data exposure via verbose error messages (raw `str(exc)` persisted/logged, exposing client PII, submitted names, or LLM prompt/output content) | Information Disclosure | Scrub-then-truncate deterministic redaction (D-8-01), applied centrally in `record_run_error` so no future caller can bypass it; this is the exact vulnerability class OPS2-01/audit HIGH-05 exists to close |
| Diagnostic/observability code introducing a NEW failure mode in the error path itself (scrubber raises, breaking the very error recording it's meant to support) | Denial of Service (soft — a silently-hung run, not a crash) | Fail-open design (D-8-01b): any exception inside the scrub/detail-building step falls back to the pre-existing type-name-only write; the diagnostics feature can degrade but must never prevent `error_reason` + `ERROR` status from being recorded |
| Schema-creep information disclosure via `SELECT *` (a future column added to `payroll_runs` — e.g. a new sensitive field — silently starts flowing to the dashboard list view with no explicit review) | Information Disclosure | Explicit column list in `load_all_runs` (D-8-07) — a new column requires an explicit, reviewed addition to the SELECT list before it can reach the dashboard, matching the project's existing `RUN_COLS`/`EMPLOYEE_COLS` discipline elsewhere in `repo.py` |
| Roster data loaded from the DB inside a degraded/DB-down error path, compounding an outage (a second DB call inside the handler for a DB-related failure) | Denial of Service / cascading failure | D-8-01b: the scrubber NEVER loads the roster from the DB — it only uses a roster object already resident in the caller's memory, or `None` (regex-only). This is both a correctness and a resilience control. |

## Sources

### Primary (HIGH confidence — live source verified this session)
- `app/db/repo.py` (1129 lines) — `record_run_error` (:370-404), `load_all_runs` (:1088-1103), `RUN_COLS` (:90-93), `find_business_by_sender` (:175-198), `get_outbound_message_id` (:751-777), `get_outbound_references_chain` (:811-831), `load_outbound_emails` (:834-852), `load_thread_messages` (:954-975), `find_awaiting_reply_for_header` / `find_any_run_for_header` (:1008-1058)
- `app/db/schema.sql` (258 lines) — full file read; `businesses.contact_email` (:19), `payroll_runs` status CHECK (:61-78), zero pre-existing `CREATE INDEX` statements (confirmed via grep), `email_messages.purpose` DROP+ADD CHECK pattern (:174-199)
- `app/pipeline/orchestrator.py` (1310 lines) — `run_pipeline` (:173-188), `_run` (:191-202), `resume_pipeline` (:205-260+), catch blocks at :179-188 and :661-667
- `app/main.py` (1309 lines) — `approve()` D-13b boundary (:475-507)
- `app/models/status.py` (27 lines) — `RunStatus` enum, `NEEDS_CLARIFICATION` at :19
- `app/models/roster.py` (140+ lines) — `Employee`/`Roster` shapes for scrubber design
- `app/email/clean.py` (40+ lines) — existing project regex convention (module-level `re.compile`)
- `app/db/supabase.py` (83 lines) — full file, `get_pool()` unguarded lazy singleton
- `tests/test_status_drift.py` (163 lines) — full file, the index-guard test model
- `tests/conftest.py` (330+ lines) — `FakeConnection`/`FakeCursor`/`FakeTransaction` (:81-167), `roster_from_seed` fixture (:196-204), `InMemoryRepo.record_run_error` (:331-339)
- `tests/test_persistence.py` (:135-194) — existing `record_run_error` test suite
- `render.yaml`, `Dockerfile` — full files, confirm single Render web service / single uvicorn process, no `--workers` flag
- `.planning/phases/07.5-clarification-reply-field-regression/07.5-CONTEXT.md` — D-7.5-03a migration pattern (verified against the schema.sql implementation it describes)
- `.planning/todos/pending/260623-01-phase05-review-warnings.md` — original WR-01 through WR-05/INFO-01/INFO-02 wording
- `pyproject.toml` — `[tool.pytest.ini_options]` markers, Python version pin
- `.planning/config.json` — `nyquist_validation: true`, `security_enforcement: true` confirmed
- Full test suite run this session: `uv run pytest -q` → 492 passed, 36 skipped, 122.16s

### Secondary (MEDIUM confidence — WebSearch verified against official docs)
- PostgreSQL JSON Functions and Operators documentation (postgresql.org) — `jsonb_array_length(NULL)` returns NULL (not an error); cross-checked via WebSearch this session, not executed against a live DB in this research session (no `DATABASE_URL` available)

### Tertiary (LOW confidence)
None — every claim in this research is either directly verified against live project source in this session or cross-checked against official PostgreSQL documentation.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new dependencies; all existing pinned versions unchanged
- Architecture: HIGH — every file/line reference re-verified against live source this session, not trusted from CONTEXT.md's remembered line numbers
- Pitfalls: HIGH — derived directly from tracing the actual call-site code (roster scope, terminal-status guard, JSONB NULL semantics) rather than generic best-practice lists

**Research date:** 2026-07-02
**Valid until:** Stable — this is internal-codebase research with no external API/library version dependency; valid until the next phase touches the same files (Phase 9 explicitly builds on this phase's schema, per the phase description's stated sequencing rationale)
