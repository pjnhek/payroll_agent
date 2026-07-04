# Deferred Items — Phase 09

Out-of-scope discoveries logged during plan execution, per the executor's scope-boundary rule
(only auto-fix issues directly caused by the current task's changes).

## 09-06 execution (2026-07-04)

- **`tests/test_ingest.py::test_duplicate_delivery_pipeline_runs_once`** — the
  `@pytest.mark.integration` test fails with `400 Bad Request` when the live-DB suite is run
  in an environment where `ALLOW_UNSIGNED_FIXTURES` is not set (`unsigned webhook rejected in
  production` guard in `app/main.py:318`). The test does not set `ALLOW_UNSIGNED_FIXTURES=true`
  internally via `monkeypatch.setenv` before posting an unsigned canonical-shape payload,
  unlike sibling tests in the same files (e.g. `tests/test_ingest.py` lines 73/155,
  `tests/test_gateway.py` lines 1098/1511) that do set it.
  - Last modified in plan 09-03 (`1e7af76`), unrelated to 09-06's files
    (`app/pipeline/orchestrator.py`, `tests/test_atomic_persist.py`).
  - Confirmed environment-dependent, not a code regression from 09-06: reproduces in
    isolation (`uv run pytest tests/test_ingest.py::test_duplicate_delivery_pipeline_runs_once`)
    with no other tests run first, and the test does not touch the alias-write/clarified-fields
    code paths this plan changed.
  - Out of scope for 09-06's gap-closure contract (WR-01/WR-02 only). Not fixed here.
  - **Action for a future plan/quick-task:** add `monkeypatch.setenv("ALLOW_UNSIGNED_FIXTURES", "true")`
    to the test (mirroring the sibling pattern already used elsewhere in the same file).
  - **Correction (phase-9 review WR-07, fixed in the review-fix pass):** an earlier version
    of this entry also attributed a live failure of
    `tests/test_gateway.py::test_inbound_reply_routes_to_correct_run_integration` to the
    missing `ALLOW_UNSIGNED_FIXTURES` env var. That was inaccurate — the test makes NO HTTP
    request (it calls `repo.find_awaiting_reply_for_header` directly), so the prod-auth guard
    never applies. Its actual live failure mode was a stale
    `@pytest.mark.xfail(strict=True, reason="implemented in 06-04")` decorator on an
    implemented, passing behavior: in a live-DB environment the test XPASSed and `strict=True`
    converted that into a hard suite failure. The stale marker has been removed (WR-07 fix),
    per the file's own convention (test_gateway.py ~lines 450-456: an XPASS is the signal to
    remove the markers).
