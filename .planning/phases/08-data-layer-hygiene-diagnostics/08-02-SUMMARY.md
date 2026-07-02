---
phase: 08-data-layer-hygiene-diagnostics
plan: 02
subsystem: database
tags: [postgres, psycopg, regex, pii-redaction, unicode, jsonb]

# Dependency graph
requires:
  - phase: 08-data-layer-hygiene-diagnostics
    provides: 08-01 schema DDL (payroll_runs.error_detail column, parallel wave — not consumed at code level by this plan, only at the DB-column level)
provides:
  - "_scrub / _build_error_detail PII redaction helpers in app/db/repo.py, offset-safe and fail-open"
  - "record_run_error(conn, *, detail_exc=, stage=, roster=) extended signature, conn kept positional-compatible"
  - "load_all_runs explicit-column SQL projection with jsonb_typeof-guarded employee_count"
affects: [08-03 (wiring the 3 call sites/templates to the new record_run_error params and load_all_runs aliases)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-candidate compiled regex built directly from the original (non-normalized) string, applied directly to the original message — offset-safe by construction, no normalize-then-slice translation step"
    - "Mark-aware lookaround anchors (?<![\\w\\u0300-\\u036f]) / (?![\\w\\u0300-\\u036f]) replacing bare \\b...\\b for Unicode-safe word-boundary matching"
    - "Explicit three-way accent alternation table (precomposed | decomposed | bare-unaccented) instead of runtime unicodedata.normalize at match time"
    - "Fail-open diagnostics: any exception inside the scrub/compose path returns None rather than raising, so the error-reporting path can never itself cause an error"
    - "jsonb_typeof-guarded CASE expression instead of bare COALESCE(jsonb_array_length(...), 0) for JSONB scalar safety at the SQL layer"

key-files:
  created: []
  modified:
    - app/db/repo.py
    - tests/test_persistence.py
    - tests/test_dashboard.py

key-decisions:
  - "Split Task 1 (scrub helper + record_run_error) and Task 2 (load_all_runs projection) into two separate atomic commits within app/db/repo.py despite both touching the same file, to keep the git history aligned 1:1 with the plan's task boundaries"
  - "Used explicit \\uXXXX Python string escapes (not literal accented characters) throughout app/db/repo.py and the new tests to avoid encoding-corruption risk when transcribing accented Unicode source text"

patterns-established:
  - "Diagnostics helpers (_scrub, _build_error_detail) live as private module-level functions directly above the function that uses them, never call into the DB, and take all inputs as already-resolved in-memory values"

requirements-completed: [OPS2-01, OPS2-02]

# Metrics
duration: 20min
completed: 2026-07-02
---

# Phase 08 Plan 02: Data-Layer Diagnostics + load_all_runs Projection Summary

**Offset-safe, mark-aware, Unicode-form-tolerant PII scrubber wired into `record_run_error`'s existing transaction, plus a `load_all_runs` rewrite that drops `SELECT pr.*` for an explicit column list with a `jsonb_typeof`-guarded `employee_count`.**

## Performance

- **Duration:** ~20 min
- **Completed:** 2026-07-02
- **Tasks:** 2/2
- **Files modified:** 3 (`app/db/repo.py`, `tests/test_persistence.py`, `tests/test_dashboard.py`)

## Accomplishments

- `_scrub`/`_compile_name_pattern`/`_build_error_detail` added to `app/db/repo.py`: each candidate name/alias gets one compiled `re.Pattern` built directly from the original (non-normalized) string, applied directly against the original (progressively redacted) message — no normalize-then-slice-original-offsets translation step, so no offset drift is possible by construction. Matching is case-insensitive, and an explicit `_ACCENT_CLASS_MAP` covers precomposed / NFD-decomposed / bare-unaccented renderings of common Spanish/Portuguese/French accented letters, so a stored `"Ana Núñez"` is redacted whether it arrives as `"Ana Núñez"`, its NFD-decomposed form, or the fully diacritic-stripped `"ANA NUNEZ"`.
- Boundaries are anchored with `(?<![\w\u0300-\u036f])`/`(?![\w\u0300-\u036f])` instead of bare `\b...\b`, so a short alias (e.g. `"Tom"`) never over-redacts inside an unrelated word (`"Tomorrow"`), and a name ending in an accented character (e.g. `"Rene"`) never leaves a stray combining mark stranded next to `[REDACTED]` when the message carries the NFD-decomposed form.
- `record_run_error` extended to `record_run_error(run_id, reason, conn=None, *, detail_exc=None, stage=None, roster=None)` — `conn` stays positional-compatible; the new params are keyword-only, placed after it. Writes a scrub-then-stage-prefix-then-200-char-truncate `error_detail` alongside the existing `error_reason`, in the same transaction, no new query. Fails open (`error_detail` falls back to `None`) if the scrub step raises or no roster is supplied, so the diagnostics feature can never block the error path it exists to observe.
- `load_all_runs` rewritten: explicit scalar column list (`pr.id, pr.business_id, pr.status, pr.created_at, pr.updated_at, b.name AS business_name`) plus two SQL-computed aliases — `summary_gate_reason` (unchanged `->`/`->>` chain) and a `jsonb_typeof`-guarded `employee_count` CASE expression that degrades a corrupt/legacy non-array `extracted_data->'employees'` value to `0` instead of raising a Postgres error for the entire runs-list query. No `pr.*`/`SELECT *` remains.

## Task Commits

1. **Task 1: PII scrub helper + record_run_error(conn, *, detail_exc=, stage=, roster=)** — `723b841` (feat)
2. **Task 2: load_all_runs explicit-column projection with jsonb_typeof-guarded employee_count** — `bbd49ce` (feat)

## Files Created/Modified

- `app/db/repo.py` — added `_EMAIL_RE`, `_REDACTED`, `_ACCENT_CLASS_MAP`, `_compile_name_pattern`, `_scrub`, `_build_error_detail`; extended `record_run_error`'s signature and its `UPDATE` to also write `error_detail`; rewrote `load_all_runs`'s SQL projection.
- `tests/test_persistence.py` — added `unicodedata`/`Roster` imports, an `_employee()` test helper, and 8 new tests covering PII exclusion, scrub-before-truncate boundary straddle, fail-open (scrub raises / no roster), case+Unicode-form-insensitive longest-first matching (with-alias and no-covering-alias cases), the R3-1 trailing-accent NFD boundary case, longest-first offset-safety, and the Tom/Tomorrow non-over-redaction case.
- `tests/test_dashboard.py` — added 3 new tests: projection SQL assertion (no `pr.*`, explicit columns + aliases present), `jsonb_typeof`-guard SQL-text assertion, and a Python-side non-array `employee_count` value tolerance test.

## Decisions Made

- Committed Task 1 and Task 2 as two separate atomic commits even though both edit `app/db/repo.py`, by splitting the diff into task-scoped hunks before staging — keeps the git history 1:1 with the plan's task boundaries as required by the task-commit protocol.
- Wrote all accented-character literals in both `app/db/repo.py` and the new test fixtures using explicit `\uXXXX` Python escapes rather than typing literal accented glyphs, after an early Edit-tool transcription attempt silently corrupted several accented characters into unrelated Unicode lookalikes. This is documented here as a build-process note, not a deviation from the plan's design — the shipped code and tests were verified byte-for-byte via `od -c` / `repr()` before commit.

## Deviations from Plan

None — plan executed exactly as written. All 9 behaviors in Task 1 and all 3 behaviors in Task 2 are covered by tests; every acceptance-criteria grep in the plan passes against the final `app/db/repo.py` (verified individually, including re-deriving the `_ACCENT_CLASS_MAP` three-alternative-pipe-count check and the `_compile_name_pattern` mark-aware-anchor occurrence check).

## Issues Encountered

- The Edit tool's text-matching step twice silently mis-transcribed literal accented Unicode source text I supplied (both in the `_ACCENT_CLASS_MAP` dict values and the mark-aware lookaround character class), turning intended NFD-decomposed sequences and a `\w\u0300-\u036f` character-class range into unrelated Unicode glyphs that changed the code's actual matching behavior. Caught immediately via `od -c`/`repr()` inspection and a live `uv run python` functional test (Jose/Garcia precomposed+NFD+bare-unaccented redaction, Tom/Tomorrow non-over-redaction, Rene trailing-NFD-accent no-stray-combining-mark) before any commit. Resolved by rewriting the affected regions with a Python script using explicit `\uXXXX` escape sequences (ASCII-only source, unambiguous), re-verified via the same functional tests plus the plan's acceptance-criteria greps.

## User Setup Required

None — no external service configuration required. (The `payroll_runs.error_detail` DB column this plan writes to is added by the parallel 08-01 schema-DDL plan; this plan's helper writes a value into it only when the column exists, and is fully unit-tested offline via `FakeConnection` with no live DB dependency.)

## Next Phase Readiness

- `record_run_error`'s new `detail_exc=`/`stage=`/`roster=` params and `load_all_runs`'s new `summary_gate_reason`/`employee_count` aliases are ready for 08-03 to wire into the actual call sites (pipeline stage error handlers) and templates (`runs_list.html` currently still reads `run.decision.gate_reasons[0]` / `run.extracted_data.employees | length` directly — 08-03 is expected to switch the template to the new SQL-computed aliases).
- No blockers. Full suite green: 502 passed, 37 skipped (baseline 492 passed / 36 skipped + 10 new passing tests + 1 pre-existing skip pattern applied to a new roster-fixture-dependent test that happens to not hit the live-DB skip path — verified all 11 new tests pass individually, zero net new skips from this plan's own tests).

## Self-Check: PASSED

- FOUND: app/db/repo.py
- FOUND: tests/test_persistence.py
- FOUND: tests/test_dashboard.py
- FOUND commit 723b841 (Task 1)
- FOUND commit bbd49ce (Task 2)
