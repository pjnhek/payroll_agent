# Phase 8: Data-Layer Hygiene & Diagnostics - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-02
**Phase:** 8-Data-Layer Hygiene & Diagnostics
**Areas discussed:** Todo folding, error_detail content, Dashboard surfacing, Runs-list projection, Index verification

---

## Todo Folding (cross_reference_todos)

| Option | Description | Selected |
|--------|-------------|----------|
| 260623-07 SELECT * fix | load_all_runs explicit column list — IS success criterion 3 | ✓ (folded) |
| 260623-06 dead status | NEEDS_CLARIFICATION declared but never written — invisible dashboard dead-end | ✓ (folded, remove-from-enum option) |
| 260623-01 Ph5 warnings | Deferred Phase 5 review warnings (WR-02/WR-04/WR-05/INFO-02) | ✓ (WR-02 slice folded; rest deferred) |
| 260623-08 loop cap | Re-clarification round cap with operator escape | ✓ selected, but deferred per delegation |

**User's choice:** Selected all four + "pick the best solution for me"
**Notes:** Delegation applied — folded the genuinely data-layer items (07 fully, 06 fully, 01's WR-02 slice); deferred 01's security-flavored findings and 08 (new state-machine capability, not data-layer hygiene). Cosmetic matcher hits (frontend polish, YTD, eval-chart restyle, fixture label) excluded up front as declared out of scope in REQUIREMENTS.md.

---

## error_detail content

| Option | Description | Selected |
|--------|-------------|----------|
| Scrub-then-store | One code path for all exceptions: str(exc)[:200] through a deterministic scrubber redacting emails + roster names/aliases/business contact | ✓ |
| Allowlist by exception family | Full message only for infrastructure types; ValidationError/LLM errors stay type-name-only | |
| Raw str(exc)[:200] | Roadmap's literal wording, no scrubbing | |

**User's choice:** Scrub-then-store (Recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| Stage prefix | "{stage}: {scrubbed message}" — one string, tells the operator WHERE it died | ✓ |
| Message only | Just the scrubbed message | |
| Structured mini-JSON | {stage, message, status_at_failure} JSON string in the TEXT column | |

**User's choice:** Stage prefix (Recommended)
**Notes:** Which call sites pass a stage was captured as Claude discretion (all three, centralized via optional detail param).

---

## Dashboard surfacing

| Option | Description | Selected |
|--------|-------------|----------|
| Run detail only | Extend the existing error banner on run_detail.html; runs list unchanged | ✓ |
| Run detail + runs-list hint | Also truncated detail in the runs-list Summary cell | |

**User's choice:** Run detail only (Recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| Both, detail below | Keep the '⚠ Error — {error_reason}' line untouched; append stage-prefixed detail as a second line when present | ✓ |
| Detail replaces reason | Show only the richer string when detail exists | |

**User's choice:** Both, detail below (Recommended)

---

## Runs-list projection

| Option | Description | Selected |
|--------|-------------|----------|
| SQL-derived summary | Explicit scalars + decision->'gate_reasons'->>0 AS summary_gate_reason + NULL-safe jsonb_array_length(...) AS employee_count; template switches to aliases | ✓ |
| Explicit list incl. 2 JSONB | Name every column but keep decision/extracted_data whole; zero template change | |
| Slim the template | Summary cell derivable from scalars only | |

**User's choice:** SQL-derived summary (Recommended)
**Notes:** Test approach captured as Claude discretion (offline FakeConnection SQL assertion, Phase 2 pattern).

---

## Index verification

| Option | Description | Selected |
|--------|-------------|----------|
| Static guard + live checkpoint | Hermetic schema.sql parse test in CI + blocking human checkpoint querying pg_indexes on Supabase after bootstrap | ✓ |
| Live pg_indexes test | DATABASE_URL-gated integration test in the suite | |
| Static guard only | Trust bootstrap idempotency; never confirm on Supabase | |

**User's choice:** Static guard + live checkpoint (Recommended)

---

## Claude's Discretion

- record_run_error mechanics: optional `detail` param; all three call sites enriched; scrub centralized in one helper.
- Projection test: offline FakeConnection SQL assertion.
- Scrubber internals (regexes, placeholder text, roster-string sourcing).
- Exact scalar column set for load_all_runs (verify against template at implementation).

## Deferred Ideas

- 260623-08 re-clarification loop cap with operator-escape state (new capability; Phase 9+ or own phase).
- 260623-01 remainder: WR-04 Content-Disposition injection, WR-05 path containment, INFO-02 retry-prompt scrub (security-flavored slot).
- Cosmetic todos (260623-02/03/04/05) — declared out of scope for v2 in REQUIREMENTS.md.
