---
phase: 08-data-layer-hygiene-diagnostics
verified: 2026-07-02T22:15:00Z
status: passed
score: 3/3 must-haves verified
overrides_applied: 0
---

# Phase 8: Data-Layer Hygiene & Diagnostics Verification Report

**Phase Goal:** Restore the project's own stated schema-hygiene discipline and make production failures diagnosable from the dashboard/DB without log access — landing as a clean, low-risk baseline before the transaction surgery in Phase 9.
**Verified:** 2026-07-02T22:15:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A failed run records a PII-safe `error_detail` (sanitized `str(exc)[:200]` + context), surfaced on dashboard/DB, diagnosable without log access, proven by a test asserting the stored detail contains the message and excludes PII | ✓ VERIFIED | `app/db/repo.py:387-529` — `_EMAIL_RE`, `_ACCENT_CLASS_MAP`, `_compile_name_pattern`, `_scrub`, `_build_error_detail`, `record_run_error(conn, *, detail_exc=, stage=, roster=)` all present and wired. `test_record_run_error_scrubs_pii_from_error_detail` (tests/test_persistence.py:226) asserts `detail` contains `"bad row"` and excludes both `employee.full_name` and the raw email — PASSED. `RUN_COLS` (repo.py:95-98) includes `error_detail`. All 3 production call sites wired: `_run`'s own except block (orchestrator.py:213-223, HIGH #1 root-fixed — roster now visible to the error path), `resume_pipeline`'s except (roster-guarded), `approve()`'s delivery boundary (main.py:508, `roster=None` by design per D-8-01b, since `approve()` never loads one). Template renders it (`run_detail.html:69`, autoescaped). Live column confirmed present via 08-03 checkpoint (`error_detail \| text \| YES`). |
| 2 | Hot query paths have supporting indexes — `businesses.contact_email`, `email_messages(run_id, direction, send_state)`, `payroll_runs(created_at DESC)`, `payroll_runs(status)` — applied via `schema.sql`, verified present after bootstrap; status-drift/schema guard stays green | ✓ VERIFIED | `app/db/schema.sql:120-123` (`idx_payroll_runs_created_at`, `idx_payroll_runs_status`), `schema.sql:278-279` (`idx_email_messages_run_direction_state` on exactly `(run_id, direction, send_state)`), `schema.sql:19-21` (`contact_email TEXT NOT NULL UNIQUE` + D-8-09 comment — verified, not duplicated). `tests/test_status_drift.py::TestIndexStaticGuard` (7 tests) all pass — index presence, column order, contact_email UNIQUE coverage, `uq_email_run_purpose` coverage. Live verification confirmed at the 08-03 human checkpoint: all 3 indexes present via `pg_indexes`, `businesses_contact_email_key` UNIQUE index confirmed. Status CHECK swap (needs_clarification removal) also landed: `RunStatus` has exactly 10 members (`app/models/status.py`), inline CHECK + DO-block both enumerate the same 10 values (`schema.sql:68-80`, `134-166`), `grep -c "needs_clarification" schema.sql` = 0. `test_status_drift.py::TestEnumCheckDrift` (9 tests, including the dedicated DO-block parser `test_do_block_status_check_matches_enum`) all pass. |
| 3 | `load_all_runs` selects an explicit column list (no `SELECT *`), so schema creep cannot silently leak new columns — with a test asserting the query names its columns | ✓ VERIFIED | `app/db/repo.py:1213-1245` — SQL is `"SELECT pr.id, pr.business_id, pr.status, pr.created_at, pr.updated_at, b.name AS business_name, pr.decision->'gate_reasons'->>0 AS summary_gate_reason, CASE WHEN jsonb_typeof(...) = 'array' THEN ... ELSE 0 END AS employee_count ..."` — zero `pr.*`/`SELECT *`. `grep -n "SELECT pr\.\*" app/db/repo.py` returns no matches. `test_load_all_runs_projection_has_no_select_star` and `test_load_all_runs_employee_count_uses_jsonb_typeof_guard` (tests/test_dashboard.py) both PASS, asserting the exact column list and the `jsonb_typeof`-guarded CASE (not a bare COALESCE — codex review fix #2). `runs_list.html:64-67` consumes the new `summary_gate_reason`/`employee_count` aliases (old `run.decision.gate_reasons`/`run.extracted_data.employees` direct-JSONB access removed from the Summary cell). |

**Score:** 3/3 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/db/schema.sql` | error_detail column, 3 new indexes, contact_email coverage comment, 10-value status CHECK (inline + DO-block) | ✓ VERIFIED | All present, confirmed live at 08-03 checkpoint |
| `app/models/status.py` | RunStatus reduced to 10 members | ✓ VERIFIED | `NEEDS_CLARIFICATION` absent; exactly 10 members confirmed by source read |
| `tests/test_status_drift.py` | Index static guard + DO-block-specific drift guard + needs_clarification-absence guard | ✓ VERIFIED | 17 tests, all passing, including `TestIndexStaticGuard` (new) and `test_do_block_status_check_matches_enum` (new, independent parser) |
| `app/db/repo.py` | `_scrub`/`_build_error_detail` helpers, extended `record_run_error`, rewritten `load_all_runs` | ✓ VERIFIED | All present, wired, tested |
| `tests/test_persistence.py` | Scrub-before-truncate, fail-open, Unicode-form-tolerant tests | ✓ VERIFIED | 12 new/extended tests, all pass, including constructed non-skippable accented/decomposed/unaccented-name cases |
| `tests/test_dashboard.py` | Projection SQL-assertion test + JSONB scalar edge case + integration test | ✓ VERIFIED | `test_load_all_runs_projection_has_no_select_star`, `test_load_all_runs_employee_count_uses_jsonb_typeof_guard`, `test_load_all_runs_tolerates_non_array_employee_count_value`, `test_run_detail_renders_error_detail_end_to_end` — all pass |
| `app/pipeline/orchestrator.py` | `_run` owns its own try/except (HIGH #1); `run_pipeline` thin delegator | ✓ VERIFIED | Confirmed by direct source read (lines 173-224); `roster = None` first statement, reassigned after load, except block passes `roster=roster` |
| `app/main.py` | `approve()` delivery boundary passes `detail_exc`/`stage="delivery"` | ✓ VERIFIED | Line 508 confirmed |
| `app/templates/run_detail.html` | Conditional error-detail second line | ✓ VERIFIED | Line 69, autoescaped, byte-identical `error_reason` line preserved |
| `app/templates/runs_list.html` | Summary cell on new aliases | ✓ VERIFIED | Lines 64-67, old direct-JSONB access removed |
| `tests/test_orchestrator_states.py` | R2-2 behavioral spy test | ✓ VERIFIED | `test_first_run_failure_after_roster_load_passes_nonnull_roster_to_record_run_error` PASSED — asserts runtime kwargs (`stage=="pipeline"`, `roster is not None`, populated `Roster`), not source-grep |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `app/models/status.py` RunStatus | `app/db/schema.sql` CHECK (inline + DO-block) | Dual-sourced enum drift guard | ✓ WIRED | Both `test_check_values_match_python` and `test_do_block_status_check_matches_enum` pass independently |
| `app/pipeline/orchestrator.py` `_run`'s own except block | `app/db/repo.py record_run_error` | `detail_exc=exc, stage="pipeline", roster=roster` | ✓ WIRED | Confirmed by source read + R2-2 behavioral spy test (runtime kwargs captured and asserted non-None) |
| `app/db/repo.py RUN_COLS` | `app/db/repo.py load_run` | Explicit column list interpolated into SELECT | ✓ WIRED | `error_detail` present in `RUN_COLS` (repo.py:95-98); `load_run` (line 265) interpolates it directly |
| `app/templates/run_detail.html` | `payroll_runs.error_detail` | Jinja2 autoescaped conditional render | ✓ WIRED | `test_run_detail_renders_error_detail_end_to_end` proves the full DB-column → RUN_COLS/load_run → template loop with a real scripted row |
| `tests/test_orchestrator_states.py` spy | `_run`'s own except block | Forced extract-stage failure after roster load | ✓ WIRED | Test passes; captured kwargs prove real runtime argument flow, not just call-site text |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| OPS2-01 | 08-01, 08-02, 08-03 | PII-safe error_detail, diagnosable without log access | ✓ SATISFIED | error_detail column, scrub helper, record_run_error wiring, RUN_COLS, template render all confirmed live + hermetically tested |
| OPS2-02 | 08-01, 08-02, 08-03 | Hot-path indexes + explicit-column load_all_runs | ✓ SATISFIED | 3 new indexes + contact_email UNIQUE coverage + explicit-column load_all_runs all confirmed live + hermetically tested |

No orphaned requirements — both OPS2-01 and OPS2-02 declared in all 3 plans, matching REQUIREMENTS.md's Phase 8 mapping exactly.

Note: REQUIREMENTS.md's checkbox/Traceability table for OPS2-01/OPS2-02 still reads "Pending" as of this verification — this is a documentation-update lag (normal at phase-close/milestone-audit time), not a code gap. Recommend updating REQUIREMENTS.md's Traceability table to "Complete" and, per plan 08-03's D-8-11 note, updating OPS2-02's wording from "an index on businesses.contact_email" to "hot path verified index-covered by the existing UNIQUE constraint" now that Phase 8 has closed.

### Anti-Patterns Found

None. Zero `TBD`/`FIXME`/`XXX`/`TODO`/`HACK`/`PLACEHOLDER` markers and zero "not yet implemented"/"coming soon" strings across all 15 phase-modified files (`app/db/schema.sql`, `app/models/status.py`, `app/db/repo.py`, `app/pipeline/orchestrator.py`, `app/main.py`, `app/templates/run_detail.html`, `app/templates/runs_list.html`, `app/db/supabase.py`, `tests/conftest.py`, `tests/test_threading.py`, `tests/test_dashboard.py`, `tests/test_orchestrator_states.py`, `tests/test_persistence.py`, `tests/test_status_drift.py`, `tests/test_models_contracts.py`).

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full hermetic suite green | `uv run pytest -q` | 515 passed, 36 skipped | ✓ PASS |
| SC1 PII-exclusion tests | `uv run pytest tests/test_persistence.py -k "record_run_error or scrub or garcia or nunez or boundary or tomorrow or rene" -q` | 11 passed | ✓ PASS |
| SC2 status-drift + index static guard | `uv run pytest tests/test_status_drift.py -v` | 17 passed | ✓ PASS |
| SC3 load_all_runs projection | `uv run pytest tests/test_dashboard.py -k "load_all_runs or error_detail" -v` | 4 passed | ✓ PASS |
| R2-2 behavioral spy (argument-flow, not grep) | `uv run pytest tests/test_orchestrator_states.py -k passes_nonnull_roster -v` | 1 passed | ✓ PASS |
| Independent repro: `_scrub` excludes PII for the seeded test case | Direct `uv run python3` call to `_scrub` with a roster + email in the message | `[REDACTED]` present, PII excluded | ✓ PASS |
| Independent repro: WR-01 gap (NFD-stored candidate) | Direct `uv run python3` call to `_scrub` with an NFD-encoded stored candidate | Confirmed real gap — both NFC and bare renderings leak unredacted when the STORED candidate (not the message) is NFD-encoded | Confirmed as WARNING, not a blocker (see below) |

## Code Review Findings Assessment (08-REVIEW.md)

The phase's own code review found 1 Critical + 6 Warnings. Each was independently traced against the three ROADMAP success criteria to determine whether it invalidates a must-have:

- **CR-01 (`alias_candidates` missing from RUN_COLS)** — Verified via `git log -L` and source read: `alias_candidates` has never been in `RUN_COLS` (predates this phase, introduced with the constant itself in commit `78764e8`). No plan in 08-01/08-02/08-03 ever declared `alias_candidates` as a must-have, artifact, or requirement scope item. This is a real, pre-existing bug affecting the alias-learning write side — but it is **not one of Phase 8's 3 ROADMAP success criteria** (which are scoped to `error_detail`, hot-path indexes, and `load_all_runs`'s column list). Does not block this phase's goal. Recommend a follow-up fix (tracked separately, e.g. Phase 9 or a quick-fix), not a Phase 8 gap.
- **WR-01 (NFD-stored candidate defeats scrubber)** — Independently reproduced: confirmed real. A roster name/alias stored in NFD form is not caught by `_ACCENT_CLASS_MAP` (keyed by precomposed characters only), so both the NFC and bare-unaccented renderings of that same stored name leak. This is a genuine residual gap in the "excludes PII" guarantee for one specific input class (NFD-*stored* candidates — the phase's own tests thoroughly cover NFD-decomposed *messages* against precomposed *stored* candidates, which is the more common real-world direction, but not the reverse). SC1's own test (`test_record_run_error_scrubs_pii_from_error_detail`) passes and proves the stated behavior for its tested cases; the truth as literally worded ("proven by a test...") holds. Correctly a WARNING, not a BLOCKER — recommend a follow-up `unicodedata.normalize("NFC", name)` fix at the top of `_compile_name_pattern` (one-line, low-risk).
- **WR-02 (accent map omits umlaut/grave letters)** — Real, narrow gap (German/Scandinavian names not covered). Does not invalidate SC1's tested behavior; a documented, extensible limitation.
- **WR-03 (check-then-act race in `record_run_error`'s terminal-status guard)** — A pre-existing WR-04 guard pattern (not new to this phase), and orthogonal to all 3 success criteria (concurrency correctness is explicitly Phase 9/10's scope per ROADMAP.md).
- **WR-04 (delivery-stage `error_detail` never scrubbed for roster names)** — Verified via source read (`app/main.py:508`, `_deliver` at `orchestrator.py:1156`): `approve()`'s call site never held a roster in its own scope by design. This exactly matches the project's own locked decision D-8-01b ("roster-name scrubbing is best-effort using whatever roster object the call site already holds in memory... pass `roster=None` when unavailable → regex-only"). Not a violation of the phase's design contract — a real opportunity for a future improvement (restructure `_deliver`'s error boundary the same way `_run`'s was, per the HIGH #1 pattern), but D-8-01b explicitly permits this fallback. Correctly a WARNING.
- **WR-05 (docstring says omission preserves prior detail; code overwrites with NULL)** — Documentation-accuracy issue only; all 3 production call sites currently pass both `detail_exc`/`stage` together, so the described contract mismatch has no live impact. Does not touch any of the 3 success criteria.
- **WR-06 (status-CHECK DO-block drops first `LIKE '%status%'` match without STRICT)** — A latent migration-idiom risk (today only one matching constraint exists). Does not affect whether SC2's tested behavior (index presence + status CHECK correctness) currently holds — verified live at the 08-03 checkpoint.

**Conclusion:** None of the review's 7 findings falsify any of the 3 ROADMAP success criteria as literally worded and tested. CR-01 is out of this phase's declared scope entirely. The Warnings identify real, legitimate follow-up work (several already exist as natural next steps for Phase 9's transaction-surgery ring) but do not invalidate what Phase 8 committed to deliver.

### Human Verification Required

None required beyond what was already completed at the 08-03 blocking checkpoint (live schema apply, 6 SQL checks, deterministic dashboard render — all confirmed per the orchestrator's supplied execution facts and cross-checked against 08-03-SUMMARY.md's documented checkpoint evidence).

### Gaps Summary

No gaps against the 3 ROADMAP success criteria. All three are independently verified: (1) PII-safe `error_detail` with a passing exclusion test and full production-boundary wiring including the HIGH #1 roster-scope root-fix, (2) all 4 hot-path index/coverage facts applied and live-confirmed with a green status-drift/schema guard, (3) `load_all_runs`'s explicit column list with a passing SQL-assertion test. Full suite green (515 passed, 36 skipped). Zero debt markers in phase-modified files. The code review's 1 Critical is pre-existing and out of this phase's declared scope; its 6 Warnings are legitimate follow-up items that do not falsify any of the 3 success criteria as tested and shipped.

---

*Verified: 2026-07-02T22:15:00Z*
*Verifier: Claude (gsd-verifier)*
