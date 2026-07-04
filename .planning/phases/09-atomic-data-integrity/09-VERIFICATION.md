---
phase: 09-atomic-data-integrity
verified: 2026-07-04T00:00:00Z
status: gaps_found
score: 5/7 must-haves verified
overrides_applied: 0
gaps:
  - truth: "Each multi-write pipeline operation is atomic (DATA-01) — a crash mid-sequence never leaves a half-written run"
    status: failed
    reason: "resume_pipeline's Round-2 non-deferred fall-through branch calls repo.set_clarified_fields(run_id, clarified) at orchestrator.py:618 with NO conn= parameter — a bare, independently auto-committing write that runs OUTSIDE and AFTER _run_stages' own transaction (which already committed AWAITING_APPROVAL). A crash between the two commits leaves an APPROVABLE run whose clarified_fields provenance ('asked') contradicts the actually-paid line items, AND silently skips the STEP C/D alias-candidate diff that only runs after this line. 09-02's plan only wrapped this SAME helper's OTHER call site (inside _defer_field_regression_clarification, the deferred branch) in a transaction — the non-deferred Round-2 fall-through at line 618 was never addressed. Confirmed by direct source read (app/pipeline/orchestrator.py:586-620) and independently found by 09-REVIEW.md's WR-02."
    artifacts:
      - path: "app/pipeline/orchestrator.py"
        issue: "Line 618: repo.set_clarified_fields(run_id, clarified) — no conn=, not wrapped in any with conn.transaction(): block, and it is the ONLY multi-write pipeline call site among _run_stages/_clarify/_deliver/_defer_field_regression_clarification that 09-02 left unwrapped"
    missing:
      - "Wrap the Round-2 non-deferred repo.set_clarified_fields(run_id, clarified) call (orchestrator.py:618) so it commits atomically with (or strictly before, mirroring the deferred branch's pattern) the _run_stages status advance — either thread conn= through into _run_stages' own transaction, or persist clarified BEFORE calling _run_stages on this path (the outcomes are already final at that point and do not depend on _run_stages' result)."
      - "A fault-injection test proving a crash between _run_stages' commit and this set_clarified_fields commit leaves a diagnosable state (not a silently-dropped alias-diff + stale provenance)."
  - truth: "A forced _write_aliases_if_safe exception still results in _deliver reaching RECONCILED — the D-13b alias-write isolation is preserved inside the new transaction boundary"
    status: failed
    reason: "The claimed isolation only holds for pure-Python exceptions (exactly what the plan's fault-injection test monkeypatches). update_known_alias (called transitively by _write_aliases_if_safe) executes via `with c.transaction() if owns else _nulltx():` (app/db/repo.py:911) — when a caller-supplied conn is present, _nulltx() is a bare `yield` with NO savepoint (confirmed: app/db/repo.py:1416-1418, `def _nulltx(): yield`). If any SQL statement inside the alias path fails at the database level (constraint violation, lock timeout, serialization failure), the enclosing Postgres transaction enters the aborted state; the try/except swallows the Python exception, but the immediately-following repo.set_status(run_id, RunStatus.SENT, conn=conn) then raises InFailedSqlTransaction, and the WHOLE finalize block (including the already-sent email's status advance) rolls back — the run ERRORs after a genuine send, contradicting the code comment's claim that alias failure 'NEVER rolls back a genuine delivery.' Recovery exists via retrigger's already-sent guard, but the specific must-have (RECONCILED is still reached) is false for DB-level alias-write errors."
    artifacts:
      - path: "app/pipeline/orchestrator.py"
        issue: "Lines 1368-1389: try/except around _write_aliases_if_safe has no savepoint boundary — a DB-level error inside it still poisons the enclosing conn.transaction()"
      - path: "app/db/repo.py"
        issue: "_nulltx() (lines 1416-1418) is a no-op context manager used whenever a caller supplies conn — no SAVEPOINT is ever established for nested writes under a shared connection"
    missing:
      - "Give the alias write its own nested transaction (psycopg3 nested `with conn.transaction():` = SAVEPOINT) so a DB-level error inside it rolls back only the alias work, not the finalize transaction, per 09-REVIEW.md WR-01's suggested fix."
      - "A live-DB fault-injection test that makes a real SQL statement in the alias path fail (not a monkeypatched Python raise) and asserts the run still reaches RECONCILED."
deferred: []
human_verification: []
---

# Phase 9: Atomic Data Integrity Verification Report

**Phase Goal:** The data layer becomes correct under concurrency and crashes — the senior-engineer signal of the milestone. Every multi-write pipeline operation commits atomically, duplicate webhook deliveries can never create a second run even when raced, and a background task that dies mid-flight leaves a *recoverable* run rather than a permanently-stranded one.
**Verified:** 2026-07-04
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `sweep_stranded_runs` marks only `{received, extracting, computed}` runs stale past threshold as ERROR, never parked statuses | VERIFIED | `app/db/repo.py::sweep_stranded_runs` — single CAS UPDATE, scope list pinned by `tests/test_stuck_run_recovery.py` (offline SQL-shape test + live-DB `test_parked_statuses_never_swept_live`); code read confirms scope is exactly `["received","extracting","computed"]` |
| 2 | A swept run carries a distinguishing `error_reason`/`error_detail` sentinel, readable via `repo.load_run` | VERIFIED | `error_reason="StrandedRunSwept"`, `error_detail` built via SQL concatenation (`%s \|\| status`) capturing the actual pre-update status — confirmed by code read and `test_stranded_run_swept_and_retriggerable` |
| 3 | `find_run_by_message_id` resolves the existing run for the webhook's dedup-loser path via a JOIN on `email_messages` | VERIFIED | `app/db/repo.py::find_run_by_message_id` — join-based lookup keyed on `message_id: str` (not the unavailable `email_id`), called from `main.py`'s duplicate-outcome branch; confirmed by code read |
| 4 | **DATA-01: Each multi-write pipeline operation is atomic** (`_run_stages`, `_deliver`, AND every resume-path write sequence) | **FAILED** | `_run_stages`' process branch, `_clarify`'s three exit paths, `_defer_field_regression_clarification`'s write, and `_deliver`'s finalize sequence ARE genuinely wrapped (confirmed by code read + 6 passing integration tests per 09-02-SUMMARY.md). BUT `resume_pipeline`'s Round-2 non-deferred fall-through calls `repo.set_clarified_fields(run_id, clarified)` (orchestrator.py:618) with no `conn=`, entirely outside and after `_run_stages`' already-committed transaction — a genuine half-written-run window the phase's own mandate exists to close. Confirmed by direct source read; independently found by `09-REVIEW.md` WR-02. |
| 5 | `_deliver`'s alias-write isolation: a forced `_write_aliases_if_safe` failure still reaches RECONCILED | **FAILED** | True only for pure-Python exceptions. `update_known_alias` (app/db/repo.py:911) uses `_nulltx()` (a no-op, no SAVEPOINT) whenever a caller-supplied `conn` is present — confirmed by code read (`app/db/repo.py:1416-1418`). A DB-level error in the alias path poisons the whole finalize transaction, causing a real send to end in ERROR rather than RECONCILED, contradicting the plan's own must-have and code comment. Independently found by `09-REVIEW.md` WR-01. |
| 6 | **DATA-02: Two concurrent duplicate webhook deliveries result in exactly one run**; a header-bearing reply is classified before `create_run` is reachable | VERIFIED | `inbound()`'s transactional ingest-decision block classifies duplicate/reply/unknown-sender/new-run inside ONE transaction before any `create_run` call; confirmed by code read (`app/main.py:369-441`) — `create_run` is structurally unreachable on `reply_candidate`/`late_reply`/`duplicate` outcomes. Reviewer independently traced the MVCC blocking semantics as sound. `tests/test_webhook_dedup_race.py` exists and is correctly structured (skip-guarded, not executed live in this environment — no `DATABASE_URL`). |
| 7 | **DATA-03: A run whose background task died mid-flight becomes a recoverable ERROR** via sweep + the actual retrigger route | VERIFIED | `runs_list()` calls `sweep_stranded_runs` before `load_all_runs()` (confirmed by code read); `test_stranded_run_swept_and_retriggerable` exercises the actual `POST /runs/{run_id}/retrigger` route via `TestClient` (not just the claim primitive) per 09-04-SUMMARY.md — correctly structured, skip-guarded pending live DB. |

**Score:** 5/7 truths verified (DATA-02 and DATA-03's core claims hold; DATA-01's literal "each multi-write pipeline operation is atomic" claim is falsified by one confirmed, unaddressed call site, plus one claimed isolation guarantee that does not hold for DB-level errors)

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `app/db/repo.py::sweep_stranded_runs` | CAS UPDATE, sanctioned third status writer | VERIFIED | Present, correct SQL shape, documented in module docstring, unit-tested |
| `app/db/repo.py::find_run_by_message_id` | Join-based dedup-loser lookup | VERIFIED | Present, correct signature (`message_id: str`), unit-tested |
| `app/pipeline/orchestrator.py` (`_run_stages`, `_clarify`, `_deliver`, `_defer_field_regression_clarification`) | Transaction-wrapped write sequences | PARTIAL | `_run_stages`, `_clarify`'s three exit paths, `_deliver`'s finalize sequence, and `_defer_field_regression_clarification`'s Step 3 are correctly wrapped. **Round-2's non-deferred `set_clarified_fields` call (line 618) is NOT wrapped** — see gap #1. |
| `app/main.py::inbound` | Transactional ingest-decision block | VERIFIED | One `with repo.get_connection(): with conn.transaction():` block correctly classifies 5 outcomes before any background task scheduling |
| `app/main.py::runs_list` | Sweep wired before `load_all_runs` | VERIFIED | Confirmed by code read |
| `tests/test_atomic_persist.py` | SC1 fault-injection proof | VERIFIED (existence + structure) | 3 offline + 6 integration tests present; integration tests reported green against a real local Postgres per 09-02-SUMMARY.md (not independently re-run live in this environment — no `DATABASE_URL`) |
| `tests/test_webhook_dedup_race.py` | SC2 real-thread concurrency proof | VERIFIED (existence + structure) | Present, correctly structured; skip-guarded, not executed live here |
| `tests/test_stuck_run_recovery.py` | SC3 end-to-end recovery proof via actual route | VERIFIED (existence + structure) | Present, correctly structured; skip-guarded, not executed live here |
| `tests/test_multiround_context_edge.py` | Known-edge fixture, no production code change | VERIFIED | Present, no module-level skip guard, runs offline (confirmed by direct test run) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `_run_stages` | `payroll_runs` status/data columns | Single `conn.transaction()` block, status-advance-last | VERIFIED | Confirmed by code read (lines ~868-905) |
| `_clarify`'s 3 exit paths | `payroll_runs` | `set_pre_clarify_extracted` + `set_status(AWAITING_REPLY)` in one block each | VERIFIED | Confirmed by code read |
| `_deliver` main finalize | `payroll_runs`/alias tables | Alias try/except nested inside `conn.transaction()`, nested inside WR-04's outer try/except | PARTIAL | Nesting/placement correct (WR-04 preservation confirmed), but the try/except does NOT actually isolate DB-level failures — see gap #2 (WR-01) |
| `resume_pipeline` Round-2 (non-deferred) | `payroll_runs.clarified_fields` | **NONE — bare auto-committing call, no `conn=`** | **NOT_WIRED** | `orchestrator.py:618` — confirmed by code read; this is the gap the plan never addressed |
| `inbound()` | `payroll_runs`/`email_messages` | One transaction, reply-classification-before-`create_run` | VERIFIED | Confirmed by code read; reviewer independently traced MVCC semantics |
| `runs_list()` | `repo.sweep_stranded_runs` | One-line call before `load_all_runs()`, try/except swallowed | VERIFIED | Confirmed by code read |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| DATA-01 | 09-02, 09-05 | Each multi-write pipeline operation is atomic | **BLOCKED** | `resume_pipeline`'s Round-2 non-deferred `set_clarified_fields` write (orchestrator.py:618) is unwrapped — a genuine half-written-run window remains. `_deliver`'s alias-isolation claim also does not hold for DB-level errors (WR-01). Both confirmed by direct source read, both independently found by 09-REVIEW.md. |
| DATA-02 | 09-01, 09-03 | Duplicate webhook deliveries never create a second run | SATISFIED | Transactional ingest-decision block correctly classifies before `create_run`; reply-vs-new-run race (Codex HIGH-1) closed; confirmed by code read. Adjacent gaps (WR-03 unlinked reply rows, WR-04 permanently-dropped replies on post-commit-pre-schedule failure) are real but do not falsify the literal "exactly one run" claim — they are a related-but-distinct reply-processing completeness concern. |
| DATA-03 | 09-01, 09-03, 09-04 | Stuck run recoverable via sweep or retrigger | SATISFIED | Sweep wired into `GET /runs`; SC3 proven end-to-end via the actual retrigger route; threshold correctly and conservatively derived (with one documented under-count in the code comment itself, IN-02, not a correctness gap). |

**Orphaned requirements check:** REQUIREMENTS.md maps exactly DATA-01/DATA-02/DATA-03 to Phase 9; all three appear in plan frontmatter (`09-01`: DATA-02/03; `09-02`: DATA-01; `09-03`: DATA-02/03; `09-04`: DATA-03; `09-05`: DATA-01). No orphaned requirements.

### Anti-Patterns Found

Carried forward from `09-REVIEW.md` (standard-depth code review, 0 Critical / 4 Warning / 6 Info) — independently re-confirmed against live source during this verification, not merely trusted from the review document:

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `app/pipeline/orchestrator.py` | 618 | Unwrapped `repo.set_clarified_fields(run_id, clarified)` call, no `conn=` | 🛑 BLOCKER (this verification) | Falsifies DATA-01's must-have; promoted from review WARNING to verification gap since it directly contradicts a phase-must-have, not merely a code-quality concern |
| `app/pipeline/orchestrator.py` | 1368-1389 | Alias-write try/except has no savepoint; `_nulltx()` used under shared `conn` | 🛑 BLOCKER (this verification) | Falsifies an explicit plan must-have ("forced exception still reaches RECONCILED"); promoted from review WARNING for the same reason |
| `app/main.py` | 373-383 | Reply rows never back-filled with `run_id` after classification (WR-03) | ⚠️ WARNING | Real client replies invisible in thread view / audit joins. Does not falsify a Phase 9 must-have literally, but is a genuine completeness gap in exactly the code this phase restructured. |
| `app/main.py` | 385-454, 600-611 | Duplicate redelivery of a reply never re-triggers resume; a resume task that dies pre-claim has no recovery route (WR-04) | ⚠️ WARNING | A persisted-but-never-processed reply is functionally the same failure class as a "silently stranded run" — adjacent to, but not literally, the DATA-02/03 must-haves as worded. |
| `app/main.py` | 66-101 | `STALE_THRESHOLD` code comment omits `suggest_employees`'s 90s ceiling and the Resend SDK's 30s timeout from its stated derivation (IN-02) | ℹ️ INFO | Threshold value itself remains safe (~5x margin); only the comment's math is incomplete — flagged so nobody re-derives a tighter threshold from the stated (incomplete) sum later |
| `app/main.py` | 1062-1065 | Sweep failures logged at DEBUG, not WARNING (IN-05) | ℹ️ INFO | A persistently-failing recovery sweep would be invisible at default log levels |
| `app/main.py` | 311 | Overbroad `except (ValueError, Exception)` (IN-01) | ℹ️ INFO | Masks genuine bugs as "invalid signature" 400s |
| `app/llm/client.py` | 78, 146-148, 240-242 | Inconsistent deep-copy of `_NON_THINKING_EXTRA_BODY` (IN-03) | ℹ️ INFO | Latent mutation-corruption risk if a downstream caller ever mutates `extra_body` |
| `app/main.py` | 631-635 | Unused `background_tasks` param on `approve()` (IN-04) | ℹ️ INFO | Dead parameter, no functional impact |
| `app/pipeline/orchestrator.py` | 624-625 | Redundant condition in alias-diff gate (IN-06) | ℹ️ INFO | Dead second operand, no functional impact |

No unreferenced `TBD`/`FIXME`/`XXX` debt markers found in the phase's modified files.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full offline suite is green | `uv run pytest -q -m "not integration"` | 545 passed, 21 skipped, 25 deselected, 0 failed | PASS |
| Live-DB integration tests skip cleanly (no `DATABASE_URL` in this environment) | `uv run pytest -q -m integration tests/test_atomic_persist.py tests/test_webhook_dedup_race.py tests/test_stuck_run_recovery.py` | 9 skipped, 12 deselected | PASS (clean skip, not silent pass — genuinely not executed against a real Postgres in this environment) |
| `set_clarified_fields`'s Round-2 non-deferred call site is unwrapped | `sed -n '586,620p' app/pipeline/orchestrator.py` | Line 618: bare `repo.set_clarified_fields(run_id, clarified)`, no `conn=`, no enclosing `with conn.transaction():` | FAIL (confirms gap #1) |
| `_nulltx()` provides no savepoint under a shared `conn` | `grep -n "_nulltx" -A2 app/db/repo.py` (definition at 1416-1418) | `def _nulltx(): yield` — bare no-op | FAIL (confirms gap #2) |
| `insert_inbound_email` always inserts with `run_id=None`; no back-fill after classification | `grep -n "run_id=None" app/main.py`; read `WR-03`'s cited block | Confirmed — `run_id=None` at insert, no `UPDATE email_messages SET run_id` anywhere in `inbound()` | Confirms WR-03 (WARNING, not a phase-must-have failure) |

### Probe Execution

No dedicated `scripts/*/tests/probe-*.sh` probes declared for this phase; none found via `find scripts -path '*/tests/probe-*.sh'`. Step 7c: SKIPPED (no probes declared or discovered for this phase).

### Human Verification Required

None identified. Every must-have and gap in this report was resolvable via direct source inspection, git history, and running the offline test suite — no visual, real-time, or external-service-dependent behavior is in scope for this phase.

### Gaps Summary

Phase 9 delivers substantial, verifiable atomicity work: the `_run_stages` process branch, `_clarify`'s three exit paths, `_deliver`'s main finalize sequence, the transactional webhook ingest (closing the Codex HIGH-1 reply-vs-new-run race), and the stranded-run sweep + end-to-end retrigger proof are all real, correctly wired, and independently confirmed by direct code reading — not merely SUMMARY.md narrative. DATA-02 and DATA-03's literal success criteria hold.

However, DATA-01's literal must-have — "each multi-write pipeline operation is atomic" — is falsified by two confirmed gaps, both independently corroborated by the phase's own `09-REVIEW.md` (WR-01, WR-02) and re-verified here directly against live source (not trusted from the review document alone):

1. **`resume_pipeline`'s Round-2 non-deferred fall-through** (`orchestrator.py:618`) calls `repo.set_clarified_fields(run_id, clarified)` as a bare, independently-committing write, entirely outside `_run_stages`' own already-committed transaction. This is the one multi-write sequence on the resume path that 09-02's transaction wiring did not fold in — the plan wrapped the SAME helper's OTHER call site (inside the deferred branch) but missed this one. A crash between the two commits leaves an approvable run with contradictory provenance and a silently-skipped alias-candidate diff.

2. **`_deliver`'s alias-write isolation claim** does not hold for DB-level errors. `_nulltx()` (used whenever a caller-supplied `conn` is present) provides no savepoint, so a genuine SQL-level failure in the alias path poisons the whole finalize transaction, causing a run to ERROR after a real send — contradicting both the plan's must-have and its own code comment. The plan's fault-injection test only exercises the pure-Python-exception path, so it does not actually prove the invariant it claims to prove.

Both gaps are precise, actionable, and scoped — not "the design needs to be rethought." A follow-up plan should (a) wrap or move the Round-2 `set_clarified_fields` write per the same pattern already used for the deferred branch, and (b) add a nested `conn.transaction()` (SAVEPOINT) around the alias write inside `_deliver`'s finalize block, per `09-REVIEW.md` WR-01/WR-02's own suggested fixes — plus fault-injection tests that exercise genuine DB-level failures, not only monkeypatched Python exceptions.

The remaining review findings (WR-03, WR-04, IN-01 through IN-06) are real but do not individually falsify a phase must-have as literally worded; they are flagged as WARNING/INFO for follow-up but do not block this phase's goal from being considered substantively (if not completely) achieved once the two BLOCKER gaps above are closed.

---

_Verified: 2026-07-04_
_Verifier: Claude (gsd-verifier)_
