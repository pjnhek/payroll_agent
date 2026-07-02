---
phase: 08-data-layer-hygiene-diagnostics
fixed_at: 2026-07-02T23:59:00Z
review_path: .planning/phases/08-data-layer-hygiene-diagnostics/08-REVIEW.md
iteration: 1
findings_in_scope: 7
fixed: 7
skipped: 0
status: all_fixed
---

# Phase 8: Code Review Fix Report

**Fixed at:** 2026-07-02T23:59:00Z
**Source review:** .planning/phases/08-data-layer-hygiene-diagnostics/08-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope (critical + warning): 7
- Fixed: 7
- Skipped: 0
- Test suite after all fixes: **525 passed, 37 skipped** (baseline 514 passed, 37 skipped — 11 new regression tests, zero regressions). `uv run pytest -q` was run after every individual fix.
- All commits live on temp branch `gsd-reviewfix/08-14563` (created from `master`), worktree removed; orchestrator handles the fast-forward merge-back.

## Fixed Issues

### CR-01: `alias_candidates` missing from RUN_COLS — alias learning was a silent no-op on a live DB

**Files modified:** `app/db/repo.py`, `tests/test_cr_regressions.py`
**Commit:** ea28e2d
**Applied fix:** Added `alias_candidates` to `RUN_COLS` (with a CR-01 comment documenting the two orchestrator consumers) so `load_run()` surfaces it to `resume_pipeline` STEP A and `_write_aliases_if_safe`. Regression tests mirror the phase's `error_detail` pattern: one pins the constant, one round-trips a scripted dict_row through the REAL `load_run` SQL via `FakeConnection` and asserts both `"alias_candidates" in fake_conn.all_sql()` and the value on the returned run dict — deliberately NOT an InMemoryRepo fake, since a fake returning full dicts is exactly what masked the bug.

### WR-01: NFD-stored roster name/alias defeated the scrubber entirely

**Files modified:** `app/db/repo.py`, `tests/test_persistence.py`
**Commit:** cb90fc5
**Applied fix:** `_compile_name_pattern` now NFC-normalizes the CANDIDATE as its first step (added `import unicodedata`). Offset-safe: only the pattern side changes; the message is never normalized (R2-1 rationale preserved). New test stores an NFD-decomposed "José García" as the candidate and asserts NFC, NFD, and bare renderings all scrub to exactly `failed for [REDACTED] at row 3`.

### WR-02: `_ACCENT_CLASS_MAP` omitted common diacritics — umlaut/grave names leaked in bare rendering

**Files modified:** `app/db/repo.py`, `tests/test_persistence.py`
**Commit:** 33ad4b6
**Applied fix:** Structural fix per the review's suggested alternative: the map is now generated once at import time (`_build_accent_class_map()`) from `unicodedata.decomposition` over the Latin-1 Supplement — 27 entries covering acute/grave/circumflex/umlaut/tilde vowels + ñ + ç. Verified the 7 original hand-transcribed entries are byte-identical in the generated map. Still static, still offset-safe (nothing computed at match time). Letters with no canonical base+mark decomposition (ø æ ß ð) stay absent and fall through to literal escaping as before. Tests: "Björn Müller"/"Amélie Lefèvre" in bare/precomposed/NFD renderings all fully redact; a map-coverage test pins presence/absence sets.

### WR-03: `record_run_error` terminal-status guard was check-then-act, not atomic

**Files modified:** `app/db/repo.py`, `tests/test_persistence.py`, `tests/test_gateway.py`, `tests/test_delivery.py`
**Commit:** 2acf87b
**Applied fix:** Folded the guard into the write using the project's `claim_status` CAS idiom: `UPDATE ... WHERE id = %s AND status <> ALL(%s) RETURNING id`, with the terminal set parameterized from `_TERMINAL_STATUSES` (single source of truth, no inlined literals). `set_status(ERROR)` runs only when the claim returned a row; a terminal (or missing) run logs the skip and returns. Updated the four affected tests: the skip-terminal test now asserts the CAS shape (no `SELECT status`, predicate + RETURNING present, terminal array passed as a param sourced from `_TERMINAL_STATUSES`); the no-roster fail-open test asserts exactly 2 statements and zero SELECTs; two callers now script the RETURNING row.

### WR-04: Delivery-stage `error_detail` never scrubbed for roster names

**Files modified:** `app/pipeline/orchestrator.py`, `app/main.py`, `tests/test_delivery.py`, `tests/test_hitl.py`
**Commit:** 073b6d6
**Applied fix:** Checked locked decision D-8-01b in 08-03-PLAN.md first (line ~140: "approve() never loads one; roster=None is correct by design"). The locked design forbids the error path from LOADING a roster — it does not forbid forwarding one already in memory, and `_deliver` has one in scope after its Step-4 load (the review's cheap-safe-improvement case). Applied: `_deliver` wraps Steps 5–10 in try/except that stashes the already-loaded roster on the raised exception (`exc.payroll_roster`, best-effort via `contextlib.suppress`) and re-raises the ORIGINAL exception unchanged — `_deliver`'s raise-freely contract is preserved. `approve()` forwards `roster=getattr(exc, "payroll_roster", None)` to `record_run_error`; failures before the roster load carry no attribute and keep the locked `roster=None` behavior. Four tests trace the argument flow: post-roster-load failure carries the roster (identity assert), pre-roster-load failure carries none, and two approve-route tests spy `record_run_error` to assert the roster/stage/reason kwargs arriving across the boundary.

### WR-05: Omitting `detail_exc`/`stage` NULLs a prior `error_detail`, contradicting the docstring

**Files modified:** `app/db/repo.py`, `tests/test_persistence.py`
**Commit:** 311dd28
**Applied fix:** Took the review's recommended "truthful docstring + always-overwrite" contract (COALESCE-preserve was rejected in the review itself: a stale detail next to a fresh reason misleads). Docstring now states `error_detail` is ALWAYS written and overwritten with NULL when `detail_exc`/`stage` are omitted, and why that is deliberate. Added a test pinning the contract at the SQL-param level (legacy two-arg call → `params[1] is None`) so docstring and SQL cannot drift apart again.

### WR-06: Status-CHECK DO-block dropped one arbitrary constraint matching `LIKE '%status%'`

**Files modified:** `app/db/schema.sql`, `tests/test_status_drift.py`
**Commit:** e5241a8
**Applied fix:** Both DO-blocks (payroll_runs status AND the mirrored email_messages purpose block the finding called out) now match constraints by their actual COLUMN SET — `contype='c'` + `array_agg(a.attname::text) = ARRAY['status']` via `conkey -> pg_attribute` — never by name substring. A `FOR` loop drops ALL matching constraints (fixes the no-STRICT arbitrary-row hazard), so the named re-ADD can never collide and the block stays idempotent on every bootstrap re-apply. A future `send_status` CHECK can no longer be silently dropped (its conkey is `{send_status}`, not `{status}`); `uq_email_run_purpose` is `contype='u'` and was never at risk from the new matcher. No third copy of the status value list was introduced (the drift guard's two parse points — inline CHECK and DO-block re-add — still cover every list). test_status_drift.py's DO-block parser needed no change (verified: the `payroll_runs_status_check` marker + following `CHECK (status IN (...))` still parse); added a static guard test asserting executable SQL contains no `conname LIKE` and exactly 2 conkey-anchored matchers. Note: the live DB was already migrated this phase with the old block; this change is hermetic and governs future bootstrap re-applies.

## Verification

- Per-fix: full `uv run pytest -q` after every finding (not just syntax checks) — counts progressed 514 → 516 → 517 → 519 → 519 → 523 → 524 → 525 passed, 37 skipped throughout.
- Money-path convention honored: CR-01 and WR-04 regression tests trace argument flow against the real SQL / route boundary, not hermetic fakes.
- Scrub-before-truncate ordering untouched (WR-01/WR-02 change only the candidate/pattern side); the existing boundary-straddle test still passes.

## Commits (on `gsd-reviewfix/08-14563`, from `master`@c5a3768)

| Finding | Commit | Message |
|---------|--------|---------|
| CR-01 | ea28e2d | fix(08): CR-01 add alias_candidates to RUN_COLS so alias learning works on live DB |
| WR-01 | cb90fc5 | fix(08): WR-01 NFC-normalize scrub candidates so NFD-stored names cannot leak |
| WR-02 | 33ad4b6 | fix(08): WR-02 generate accent class map over full Latin-1 so umlaut/grave names cannot leak |
| WR-03 | 2acf87b | fix(08): WR-03 fold terminal-status guard into atomic CAS UPDATE in record_run_error |
| WR-04 | 073b6d6 | fix(08): WR-04 forward _deliver's in-memory roster to delivery error scrub boundary |
| WR-05 | 311dd28 | fix(08): WR-05 document and pin error_detail always-overwrite contract |
| WR-06 | e5241a8 | fix(08): WR-06 column-anchored DO-block constraint drops replace name-fuzzy LIKE match |

---

_Fixed: 2026-07-02T23:59:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
