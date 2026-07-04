# Deferred Items — Phase 09

Out-of-scope discoveries logged during plan execution, per the executor's scope-boundary rule
(only auto-fix issues directly caused by the current task's changes).

## 09-06 execution (2026-07-04)

- **`tests/test_ingest.py::test_duplicate_delivery_pipeline_runs_once`** and
  **`tests/test_gateway.py::test_inbound_reply_routes_to_correct_run_integration`** — both
  `@pytest.mark.integration` tests fail with `400 Bad Request` when the live-DB suite is run
  in an environment where `ALLOW_UNSIGNED_FIXTURES` is not set (`unsigned webhook rejected in
  production` guard in `app/main.py:318`). Neither test sets `ALLOW_UNSIGNED_FIXTURES=true`
  internally via `monkeypatch.setenv` before posting an unsigned canonical-shape payload,
  unlike sibling tests in the same files (e.g. `tests/test_ingest.py` lines 73/155,
  `tests/test_gateway.py` lines 1098/1511) that do set it.
  - Both tests last modified in plan 09-03 (`1e7af76`), unrelated to 09-06's files
    (`app/pipeline/orchestrator.py`, `tests/test_atomic_persist.py`).
  - Confirmed environment-dependent, not a code regression from 09-06: reproduces in
    isolation (`uv run pytest tests/test_ingest.py::test_duplicate_delivery_pipeline_runs_once`)
    with no other tests run first, and neither test touches the alias-write/clarified-fields
    code paths this plan changed.
  - Out of scope for 09-06's gap-closure contract (WR-01/WR-02 only). Not fixed here.
  - **Action for a future plan/quick-task:** add `monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")`
    to both tests (mirroring the sibling pattern already used elsewhere in the same files).
