---
phase: 9
slug: atomic-data-integrity
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-03
revised: 2026-07-03
---

# Phase 9 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (via uv) |
| **Config file** | pyproject.toml |
| **Quick run command** | `uv run pytest -q -m "not integration"` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~30 seconds (offline); integration tests require live DB |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -q -m "not integration"`
- **After every plan wave:** Run `uv run pytest -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 60 seconds

---

## Per-Task Verification Map

**Revision note (2026-07-03, post-09-REVIEWS.md):** 09-02/09-03/09-04 task bodies
were revised for Codex HIGH-1/2/3 + MEDIUMs/LOW; 09-01 gained a small SQL/doc
correction; 09-05 is a new, independent (Wave 1) test-only plan recording a
Claude in-session HIGH finding as an explicit deferred known-edge. Rows below are
updated to match the revised task structure — no task IDs were removed, three
gained additional required assertions, and one new plan (09-05) was added.

**Revision note 2 (2026-07-03, post-Codex-Round-2):** 09-04 gained a fix for the
STILL-OPEN HIGH (`call_text`'s own client construction now also gets
`max_retries=0`, closing the `timeout_s × 3` library-retry gap Round-2 caught)
and its SC3 test now exercises the actual `POST /runs/{run_id}/retrigger` route
(not just `repo.claim_status(...)`) per the round-2 MEDIUM finding. 09-05's
known-edge fixture moved to a NEW file, `tests/test_multiround_context_edge.py`
(no module-level skip guard), because `tests/test_resume_pipeline.py`'s
existing `DATABASE_URL`-gated `pytestmark` would have silently skipped it
offline (round-2 MEDIUM). 09-03's SC2 race test now explicitly sets
`ALLOW_UNSIGNED_FIXTURES=true` before constructing its `TestClient`, mirroring
`tests/test_webhook.py`'s existing pattern, so the race's POSTs are not rejected
with 400 (round-2 MEDIUM). The round-2 LOW (offline transaction-shape tests
overclaiming) required NO plan changes: 09-01/09-02/09-03 already use either (a)
SQL-shape assertions against `FakeConnection.executed` (which genuinely records
SQL text, a claim `FakeConnection` CAN support) or (b) AST/indentation checks
against the live source (09-02 Task 1/Task 2, 09-03 Task 1) to prove a call is
positioned inside a `with conn.transaction():` block — no plan asserts
transaction enter/exit ordering from `FakeTransaction`/`FakeConnection`'s call
log (which records no such boundaries, per `tests/conftest.py:104-111`), so no
plan overclaims what the fakes can prove. This is recorded here for traceability
per the round-2 review, not because any plan needed to change.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 09-01-T1 | 09-01 | 1 | DATA-02, DATA-03 | T-09-01, T-09-02 | `sweep_stranded_runs`/`find_run_by_message_id` exist with correct signature + SQL shape; `error_detail` uses SQL concatenation (`\|\| status`) not a literal placeholder (Codex LOW); `sweep_stranded_runs` named as a sanctioned third status writer in the module docstring (Codex MEDIUM) | unit (signature check) | `uv run python -c "from app.db import repo; import inspect; print(inspect.signature(repo.sweep_stranded_runs)); print(inspect.signature(repo.find_run_by_message_id))"` | ❌ Wave 0 | ⬜ pending |
| 09-01-T2 | 09-01 | 1 | DATA-02, DATA-03 | T-09-01, T-09-02, T-09-04 | `get_connection` mockable offline; sweep SQL-shape/scope-pin (including `\|\| status`) + finder join-shape unit tests pass | unit (FakeConnection SQL-shape) | `uv run pytest -q -m "not integration" tests/test_stuck_run_recovery.py` | ❌ Wave 0 | ⬜ pending |
| 09-05-T1 | 09-05 | 1 | DATA-01 | T-09-21 | Hermetic known-edge fixture (own module, `tests/test_multiround_context_edge.py`, NO module-level skip guard — round-2 fix) proves the multi-round context-loss finding is CURRENT behavior (not desired); 09-CONTEXT.md Deferred Ideas records the disposition | unit (offline, fake_repo+mock_llm) | `uv run pytest -q -m "not integration" tests/test_multiround_context_edge.py::test_multi_round_context_loss_known_edge` | ❌ Wave 0 | ⬜ pending |
| 09-02-T1 | 09-02 | 2 | DATA-01 | T-09-05 | `_run_stages` process branch commits as one transaction, status-advance-last; `_clarify` call site stays outside the persist transaction | unit (offline regression) + integration (SC1 fault injection) | `uv run pytest -q -m "not integration" tests/test_orchestrator_states.py tests/test_webhook.py` | ❌ Wave 0 | ⬜ pending |
| 09-02-T2 | 09-02 | 2 | DATA-01 | T-09-06, T-09-07, T-09-16, T-09-19 | `_clarify`/`_deliver` finalize transactions atomic; alias-write isolation (Pitfall 2), WR-04 nesting (WARNING 1), `_defer_field_regression_clarification`'s set_clarified_fields write (checker BLOCKER, round 2) preserved, AND the already-sent guard is hardened to perform idempotent alias finalization before advancing status (Codex HIGH-2 — the send_state flip already commits inside gateway.send_outbound, so the finalize transaction cannot atomically include it; the guard's retry-safety closes the resulting alias-skip gap) | unit (offline) + integration (SC1 fault injection, real DB) | `uv run pytest -q -m "not integration"` | ❌ Wave 0 | ⬜ pending |
| 09-03-T1 | 09-03 | 2 | DATA-02 | T-09-09, T-09-10, T-09-17 | Webhook ingest transaction restructured around a transactional ingest-DECISION (dedup + reply-classification + sender-routing + create_run) that classifies duplicate/reply-resume/reply-late/unknown-sender/new-run INSIDE one transaction, so a header-bearing reply is classified BEFORE `create_run` is ever reachable (Codex HIGH-1, closed) — closes the orphan window; loser reports existing run via `find_run_by_message_id` | unit (offline TestClient) | `uv run pytest -q -m "not integration" tests/test_webhook.py` | ❌ Wave 0 | ⬜ pending |
| 09-03-T2 | 09-03 | 2 | DATA-02, DATA-03 | T-09-11, T-09-12, T-09-18 | Dashboard sweep wired before `load_all_runs`; shared threshold constant documented against the FULL current worst-case picture (call_structured extraction+suggestion, call_text unbounded, Round-2 double extraction — Codex HIGH-3); SC2 concurrency race proof sets `ALLOW_UNSIGNED_FIXTURES=true` before constructing its TestClient (round-2 MEDIUM) and monkeypatches `_run_pipeline` to avoid real LLM work (Codex MEDIUM); reply-context-loss-on-retrigger explicitly documented (Codex MEDIUM) | unit (offline, skip-guarded) + integration (real-thread race, real DB) | `uv run pytest -q -m "not integration"` | ❌ Wave 0 | ⬜ pending |
| 09-04-T1 | 09-04 | 3 | DATA-03 | T-09-13, T-09-20 | `call_structured` gains bounded `timeout=` + `max_retries=0` (closes BOTH the extraction AND suggestion gaps, checker BLOCKER 2 + Codex HIGH-3); `call_text`'s OWN client construction ALSO gains an unconditional `max_retries=0` (closes the STILL-OPEN Codex round-2 HIGH — timeout_s alone left a 3x library-retry multiplier); `compose_clarification`'s `call_text` invocation gains an explicit bounded `timeout_s=` (previously wholly absent, Codex HIGH-3); threshold comment reconciled against the FULL corrected ceiling (Round-2 double extraction counted, call_text gap now timeout_s x 1) | unit (mock/spy on OpenAI client construction + call_text invocation) | `uv run pytest -q -m "not integration" tests/test_llm_client.py` | ❌ Wave 0 | ⬜ pending |
| 09-04-T2 | 09-04 | 3 | DATA-03 | T-09-14 | SC3 end-to-end: strand → sweep → ERROR + sentinel → retrigger (via the ACTUAL `POST /runs/{run_id}/retrigger` route, TestClient, background task monkeypatched — round-2 MEDIUM fix, replaces direct `claim_status` call) → progressing, against real DB | integration (real DB, seeded_db) | `uv run pytest -q -m integration tests/test_stuck_run_recovery.py` | ❌ Wave 0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Live-DB-gated (`@pytest.mark.integration`) test scaffolding for atomicity (SC1) and dedup race (SC2) — follows the existing `tests/test_claim_status.py` pattern. Created across 09-01 (stub), 09-02 (`tests/test_atomic_persist.py`), 09-03 (`tests/test_webhook_dedup_race.py`, `tests/test_webhook.py` regression additions), 09-04 (full `tests/test_stuck_run_recovery.py` implementation).
- [ ] Crash-injection fixture (forced exception between writes) for transaction-boundary tests — implemented per-test via monkeypatched repo helpers (09-02 Tasks 1-2), not a shared fixture, per D-9-14's fault-hook directive.
- [ ] Hermetic known-edge fixture (09-05) for the multi-round context-loss finding — offline only, no live DB/LLM required, own dedicated module (`tests/test_multiround_context_edge.py`, no module-level skip guard — round-2 fix); test-only, no production code touched by that plan.

*FakeConnection (offline double) cannot prove atomicity — only SQL shape; SC1/SC2 require integration-marked tests per RESEARCH.md Pitfall 3.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| (none) | — | — | All Phase 9 behaviors have automated verification — offline (SQL-shape/regression) plus `@pytest.mark.integration` (real/local Postgres) for the three genuine atomicity/concurrency/recovery proofs (SC1/SC2/SC3), plus a dedicated hermetic fixture (09-05) for the deferred known-edge. No manual-only step is required. |

*Default: all phase behaviors have automated verification (offline + integration-gated).*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved (planner revision, 09-REVIEWS.md cross-AI findings closed — Codex HIGH-1/2/3 fixed in 09-03/09-02/09-04 respectively, Codex MEDIUMs/LOW documented in 09-01/09-03, Claude in-session HIGH deferred with fixture in 09-05; Round-2 re-review findings closed — call_text max_retries=0 in 09-04, 09-05 fixture moved to its own unguarded module, 09-03 SC2 race sets ALLOW_UNSIGNED_FIXTURES, 09-04 SC3 now exercises the actual retrigger route, transaction-shape LOW confirmed already satisfied by existing AST/SQL-shape checks)
