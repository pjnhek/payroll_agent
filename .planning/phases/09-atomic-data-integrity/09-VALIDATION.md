---
phase: 9
slug: atomic-data-integrity
status: ready
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-03
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

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 09-01-T1 | 09-01 | 1 | DATA-02, DATA-03 | T-09-01, T-09-02 | `sweep_stranded_runs`/`find_run_by_message_id` exist with correct signature + SQL shape | unit (signature check) | `uv run python -c "from app.db import repo; import inspect; print(inspect.signature(repo.sweep_stranded_runs)); print(inspect.signature(repo.find_run_by_message_id))"` | ❌ Wave 0 | ⬜ pending |
| 09-01-T2 | 09-01 | 1 | DATA-02, DATA-03 | T-09-01, T-09-02, T-09-04 | `get_connection` mockable offline; sweep SQL-shape/scope-pin + finder join-shape unit tests pass | unit (FakeConnection SQL-shape) | `uv run pytest -q -m "not integration" tests/test_stuck_run_recovery.py` | ❌ Wave 0 | ⬜ pending |
| 09-02-T1 | 09-02 | 2 | DATA-01 | T-09-05 | `_run_stages` process branch commits as one transaction, status-advance-last; `_clarify` call site stays outside the persist transaction | unit (offline regression) + integration (SC1 fault injection) | `uv run pytest -q -m "not integration" tests/test_orchestrator_states.py tests/test_webhook.py` | ❌ Wave 0 | ⬜ pending |
| 09-02-T2 | 09-02 | 2 | DATA-01 | T-09-06, T-09-07, T-09-16 | `_clarify`/`_deliver` finalize transactions atomic; alias-write isolation (Pitfall 2), WR-04 nesting (WARNING 1), and `_defer_field_regression_clarification`'s set_clarified_fields write (checker BLOCKER, round 2) preserved | unit (offline) + integration (SC1 fault injection, real DB) | `uv run pytest -q -m "not integration"` | ❌ Wave 0 | ⬜ pending |
| 09-03-T1 | 09-03 | 2 | DATA-02 | T-09-09, T-09-10 | Webhook ingest transaction closes orphan window; loser reports existing run via `find_run_by_message_id` | unit (offline TestClient) | `uv run pytest -q -m "not integration" tests/test_webhook.py` | ❌ Wave 0 | ⬜ pending |
| 09-03-T2 | 09-03 | 2 | DATA-02, DATA-03 | T-09-11, T-09-12 | Dashboard sweep wired before `load_all_runs`; shared threshold constant; SC2 concurrency race proof | unit (offline, skip-guarded) + integration (real-thread race, real DB) | `uv run pytest -q -m "not integration"` | ❌ Wave 0 | ⬜ pending |
| 09-04-T1 | 09-04 | 3 | DATA-03 | T-09-13 | `call_structured` gains bounded `timeout=` + `max_retries=0`, closing the compounding-retry gap (BLOCKER 2); threshold comment reconciled | unit (mock/spy on OpenAI client construction) | `uv run pytest -q -m "not integration" tests/test_llm_client.py` | ❌ Wave 0 | ⬜ pending |
| 09-04-T2 | 09-04 | 3 | DATA-03 | T-09-14 | SC3 end-to-end: strand → sweep → ERROR + sentinel → retrigger → progressing, against real DB | integration (real DB, seeded_db) | `uv run pytest -q -m integration tests/test_stuck_run_recovery.py` | ❌ Wave 0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] Live-DB-gated (`@pytest.mark.integration`) test scaffolding for atomicity (SC1) and dedup race (SC2) — follows the existing `tests/test_claim_status.py` pattern. Created across 09-01 (stub), 09-02 (`tests/test_atomic_persist.py`), 09-03 (`tests/test_webhook_dedup_race.py`), 09-04 (full `tests/test_stuck_run_recovery.py` implementation).
- [ ] Crash-injection fixture (forced exception between writes) for transaction-boundary tests — implemented per-test via monkeypatched repo helpers (09-02 Tasks 1-2), not a shared fixture, per D-9-14's fault-hook directive.

*FakeConnection (offline double) cannot prove atomicity — only SQL shape; SC1/SC2 require integration-marked tests per RESEARCH.md Pitfall 3.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| (none) | — | — | All Phase 9 behaviors have automated verification — offline (SQL-shape/regression) plus `@pytest.mark.integration` (real/local Postgres) for the three genuine atomicity/concurrency/recovery proofs (SC1/SC2/SC3). No manual-only step is required. |

*Default: all phase behaviors have automated verification (offline + integration-gated).*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved (planner revision, checker WARNING 2 closed)
