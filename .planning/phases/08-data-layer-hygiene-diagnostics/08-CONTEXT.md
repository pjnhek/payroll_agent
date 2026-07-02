# Phase 8: Data-Layer Hygiene & Diagnostics - Context

**Gathered:** 2026-07-02
**Amended:** 2026-07-02 — post-discussion review pass (scrub ordering, scrubber fail-open, two stale audit-index assumptions verified against live schema)
**Status:** Ready for planning

<domain>
## Phase Boundary

Additive, low-risk data-layer fixes that land a clean baseline before Phase 9's transaction surgery: (1) a PII-safe `error_detail` on failed runs so production failures are diagnosable from the dashboard/DB without log access (OPS2-01, audit HIGH-05); (2) the four hot-path indexes plus an explicit column list in `load_all_runs` (OPS2-02, audit HIGH-01/HIGH-02). Plus three folded hygiene todos that touch the same surfaces (see Folded Todos). No behavior changes to the pipeline, decisioning, or money path.

</domain>

<decisions>
## Implementation Decisions

### error_detail content (OPS2-01)
- **D-8-01 Scrub-then-store, scrub BEFORE truncate:** one code path for ALL exceptions — the FULL `str(exc)` is passed through a deterministic scrubber that redacts email addresses (regex) and any roster `full_name`/`known_alias`/business contact string present in the message, and the result is THEN truncated to 200 chars. Order is load-bearing: truncating first can cut a sensitive string in half (`"maria.gonzalez@exam"`) so the redaction regex no longer matches the remnant — partial PII leaks. Rejected: per-exception-family allowlist (leaves LLM/ValidationError failures — the most common production failure — undiagnosable) and raw `str(exc)[:200]` (ValidationError embeds LLM output which embeds client PII; fails the "excludes PII" half of the success criterion).
- **D-8-01b Scrubber is fail-open and exception-safe:** the scrubber runs in the ERROR path, where the DB may be the thing that's down (the v1 webhook 500 / pooler blip is OPS2-01's headline case) — it must NEVER load the roster from the DB. Email-regex scrubbing always runs (no DB needed); roster-name scrubbing is best-effort using whatever roster object the call site already holds in memory (pass `roster=None` when unavailable → regex-only). If the scrub helper itself raises for any reason, `record_run_error` still lands today's type-name-only write — the diagnostics feature must never swallow the error it exists to record.
- **D-8-02 Stage prefix:** `error_detail` format is `"{stage}: {scrubbed message}"` (e.g. `"extract: 2 validation errors for ExtractionPayload…"`). One human-readable string in one nullable TEXT column — no second column, no JSON.
- **D-8-03 error_reason unchanged:** `error_reason` keeps storing `type(exc).__name__` exactly as today (D-A1-03 carried forward). `error_detail` is a NEW nullable column, additive via the established `ADD COLUMN IF NOT EXISTS` migration pattern in `schema.sql`.
- **D-8-04 Test shape (from success criterion 1):** a test must assert the stored detail CONTAINS the sanitized exception message and EXCLUDES seeded PII (roster names/aliases, email addresses) — feed a synthetic exception whose message embeds both and assert the split. MUST include: (a) a case where a sensitive string straddles the 200-char boundary (proves scrub-before-truncate ordering); (b) a case where the scrubber is given no roster / a raising scrubber, asserting `record_run_error` still writes the type-name-only fallback (proves D-8-01b fail-open).

### Dashboard surfacing
- **D-8-05 Run detail only:** `error_detail` renders on `run_detail.html`'s existing error banner. The runs list keeps its status badge unchanged — operator clicks through to diagnose.
- **D-8-06 Both lines, detail below:** the existing `⚠ Error — {error_reason}` line stays byte-identical (existing tests/muscle memory intact); the stage-prefixed detail is appended as a second line ONLY when present. Old runs with NULL detail render exactly as today — the nullable column degrades gracefully.

### Runs-list projection (OPS2-02 / success criterion 3)
- **D-8-07 SQL-derived summary:** `load_all_runs` selects an explicit scalar column list plus two SQL expressions: `decision->'gate_reasons'->>0 AS summary_gate_reason` and a NULL-safe `jsonb_array_length(extracted_data->'employees') AS employee_count` (guard the NULL/missing-key case — `jsonb_array_length` on NULL input must not error). NO JSONB blob crosses the wire for the list view. Rejected: explicit list that still ships `decision`/`extracted_data` whole (satisfies "no SELECT *" literally but leaves the WR-03 perf note open) and slimming the template (loses the gate-reason triage preview).
- **D-8-08 Template follows the aliases:** `runs_list.html`'s Summary cell switches from `run.decision.gate_reasons[0]` / `run.extracted_data.employees | length` to the two new aliases. This is the ONLY template consumer; `run_detail.html` continues to load the full run via its own path.

### Index verification (OPS2-02 / success criterion 2)
- **D-8-09 Indexes: verify coverage, don't duplicate (two audit assumptions are STALE — verified against live schema 2026-07-02):**
  - `businesses.contact_email` — **DO NOT create.** The column is already `NOT NULL UNIQUE` (schema.sql:19) and Postgres backs every UNIQUE constraint with an index; the query is plain equality with no `lower()` wrapper (repo.py:188 `WHERE contact_email = %s`), so the constraint index fully serves the hot path. A second index would be a pure-write-overhead duplicate. OPS2-02 is satisfied for this path by VERIFYING the constraint-backed index (static guard + pg_indexes checkpoint), not by creating one. If a substitute is wanted, the genuinely unindexed lookup on this path is `demo_sender_bindings.operator_email` (repo.py:195) — optional, trivial at demo scale.
  - `email_messages(run_id, direction, send_state)` — create it, BUT the planner must verify the actual query predicates at repo.py:845 and :967 before locking column order (don't copy the audit's guess); note `uq_email_run_purpose (run_id, purpose)` already serves run_id-prefixed outbound lookups and `uq_message_id` serves reply-header matching, so this composite is marginal — justified by hygiene, not measured need.
  - `payroll_runs(created_at DESC)` and `payroll_runs(status)` — create as specified (`load_all_runs` ORDER BY; `find_awaiting_reply_for_header` filters `pr.status = 'awaiting_reply'` at repo.py:1020).
  - All new indexes as `CREATE INDEX IF NOT EXISTS` in `schema.sql`, applied by the existing idempotent bootstrap. (schema.sql currently contains ZERO explicit index statements — these are the first.)
- **D-8-10 Static guard + live checkpoint:** CI proof is a hermetic test parsing `schema.sql` (same style as `test_status_drift`) asserting the new `CREATE INDEX IF NOT EXISTS` statements AND the coverage facts above (contact_email UNIQUE present, uq_email_run_purpose present); the live proof is a blocking human checkpoint — run bootstrap against Supabase, query `pg_indexes`, confirm every hot path listed in OPS2-02 is index-covered (constraint-backed or new). Matches every prior live-migration checkpoint (name_matches DROP, 7.5 CHECK swap). Rejected: a DATABASE_URL-gated live test in the suite (the project deliberately keeps live-DB tests out of CI).
- **D-8-11 If OPS2-02's literal wording matters for closure:** the requirement names a `businesses.contact_email` index; the honest closure is "hot path verified index-covered by the existing UNIQUE constraint" — update the REQUIREMENTS.md wording at phase close rather than shipping a duplicate index to tick the box.

### Claude's Discretion
- **record_run_error mechanics:** `record_run_error` gains an optional `detail` param; all three call sites (orchestrator `run_pipeline` catch-all, resume-path boundary, `main.py` approve/deliver boundary) pass their stage name + exception. Centralize the scrub in one helper so no caller can bypass it.
- **Projection test:** offline FakeConnection SQL assertion (established Phase 2 repo-test pattern) asserting the query names its columns and contains no `pr.*`.
- **Scrubber internals:** exact regexes and redaction placeholder text are planner/executor calls — keep it pure and unit-testable. (Roster sourcing is NOT discretionary — D-8-01b locks passed-in-only, never load-at-call.)
- **Exact scalar column set for load_all_runs:** whatever the runs-list row actually renders (id, business_id, status, created_at, updated_at + business_name join) — verify against the template at implementation time.

### Folded Todos
- **260623-07 — load_all_runs SELECT \*:** IS success criterion 3; folded so the todo closes with the phase. Resolution = D-8-07/D-8-08.
- **260623-06 — NEEDS_CLARIFICATION dead status:** declared in `status.py` + schema CHECK but never written (`_clarify` goes straight to AWAITING_REPLY); invisible dashboard dead-end. Folded because this phase already exercises the schema/enum drift-guard surface. Take the todo's TIGHTEST option: REMOVE it from the enum + schema CHECK. Verified touch points (grep 2026-07-02) — exactly four: `app/models/status.py:19` (enum member), `app/db/schema.sql:69` (CHECK value), `app/pipeline/orchestrator.py:174` (stale docstring — update wording), `tests/test_models_contracts.py:130` (expected-values list). `tests/test_clarify.py:341` asserts the status is NOT used — stays green. Migration: the CHECK-constraint swap needs the 7.5 D-7.5-03a pattern (single-transaction DROP+ADD with the full literal value list), and the live-DB apply joins the same human checkpoint as the indexes — which MUST first run `SELECT count(*) FROM payroll_runs WHERE status = 'needs_clarification'` and confirm 0, since ADD CONSTRAINT validates existing rows and a legacy row would fail the swap.
- **260623-01 (WR-02 slice only) — thread-unsafe pool singleton:** guard the module-level `ConnectionPool` init in `app/db/supabase.py` (or document why single-worker makes it safe). Folded as data-layer hygiene; the todo's other findings stay deferred (see Reviewed Todos).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase definition
- `.planning/ROADMAP.md` — Phase 8 entry: goal, success criteria 1–3, audit findings closed (HIGH-05, MED data-layer, MED SELECT *)
- `.planning/REQUIREMENTS.md` — OPS2-01, OPS2-02 exact wording; v2 Out of Scope table (cosmetic items stay out)

### Code touch points
- `app/db/schema.sql` — `error_reason` at :93; additive `ADD COLUMN IF NOT EXISTS` migration block at :108 (the pattern `error_detail` follows); status CHECK (NEEDS_CLARIFICATION removal); currently zero CREATE INDEX statements
- `app/db/repo.py` — `record_run_error` :370 (gains `detail=`); `load_all_runs` :1088 (`SELECT pr.*` to replace); `RUN_COLS` :92 (the explicit-column discipline to match); status-writer contract comments :19, :99–102
- `app/pipeline/orchestrator.py` — `record_run_error` call sites :188 (run_pipeline catch-all) and :667 (resume boundary)
- `app/main.py` — `record_run_error` call site :506 (approve/deliver boundary, D-13b comment block :486–499)
- `app/models/status.py` — `RunStatus` enum (NEEDS_CLARIFICATION removal)
- `app/templates/run_detail.html` — :68 error banner (append detail line)
- `app/templates/runs_list.html` — :64–67 Summary cell (switch to `summary_gate_reason` / `employee_count` aliases)
- `tests/test_status_drift.py` — the schema/enum drift guard that must stay green through both the new column and the CHECK swap; also the style model for the new index static guard

### Folded todos (full problem statements)
- `.planning/todos/pending/260623-07-load-all-runs-select-star.md`
- `.planning/todos/pending/260623-06-needs-clarification-dead-status.md`
- `.planning/todos/pending/260623-01-phase05-review-warnings.md` — WR-02 slice folded; WR-04/WR-05/INFO-02 deferred

### Prior-phase patterns to reuse
- `.planning/phases/07.5-clarification-reply-field-regression/07.5-CONTEXT.md` — D-7.5-03a single-transaction DROP+ADD CHECK migration pattern (needed for the NEEDS_CLARIFICATION removal)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `RUN_COLS` / `EMPLOYEE_COLS` / `_INBOUND_COLS` constants in `repo.py`: the explicit-column-list discipline `load_all_runs` should join.
- FakeConnection offline SQL-assertion test pattern (Phase 2): asserts parameterized SQL text without a live DB — reuse for the projection test.
- `test_status_drift.py` static-file guard pattern: parse a source artifact, assert parity — the model for the index static guard.
- Idempotent bootstrap (`app/db/bootstrap.py`) re-applies `schema.sql`; `CREATE INDEX IF NOT EXISTS` and `ADD COLUMN IF NOT EXISTS` slot straight in.

### Established Patterns
- D-A1-03: `error_reason` = exception type name only — unchanged; `error_detail` is additive alongside it.
- Two sanctioned status writers (`set_status` owned-path, `claim_status` CAS at contended gates) — this phase touches neither.
- Live-DB migrations execute at a blocking human checkpoint, never silently in CI (Phase 02.1 P03, Phase 7.5 N4 precedent).

### Integration Points
- `record_run_error` is the single funnel for run failures — enriching it covers all three error boundaries at once.
- `run_detail.html` error banner already renders `error_reason` + retrigger hint; detail is one added conditional line.
- The runs-list route hands `load_all_runs` dicts straight to the template — alias names are the contract between D-8-07 and D-8-08.

</code_context>

<specifics>
## Specific Ideas

- error_detail example shape the user approved: `"extract: 2 validation errors for ExtractionPayload…"` — stage token, colon, scrubbed truncated message.
- The PII test should seed an exception message containing BOTH a roster name and an email address and assert both are redacted while the rest of the message survives.

</specifics>

<deferred>
## Deferred Ideas

### Reviewed Todos (not folded)
- **260623-08 — re-clarification loop cap with operator-escape state:** a new state-machine capability (counter column + new run state + dashboard controls), not data-layer hygiene. Keep deterministic no-guess guarantee when it lands; candidate for Phase 9+ or its own phase.
- **260623-01 remainder — WR-04 (Content-Disposition filename injection), WR-05 (path containment on eval/summary.json reads), INFO-02 (scrub ValidationError content echoed to the provider in the LLM retry prompt):** security/LLM hygiene, not data-layer; keep as pending todos for a security-flavored slot.
- **Cosmetic todos (260623-02 frontend progressive enhancement, 260623-03 paystub YTD, 260623-04 eval-chart restyle, 260623-05 fixture-10 label note):** explicitly declared out of scope for v2 in REQUIREMENTS.md — untouched.

</deferred>

---

*Phase: 8-Data-Layer Hygiene & Diagnostics*
*Context gathered: 2026-07-02*
