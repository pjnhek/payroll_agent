---
phase: 17-the-pump
verified: 2026-07-15T00:00:00Z
status: passed
score: 5/5 must-haves verified
gap_resolved_post_verification: true
behavior_unverified: 0
overrides_applied: 0
gaps:
  - truth: "The phase's own committed source passes this repo's permanent hermetic CI gate (`uv run pytest -q`, as run by `.github/workflows/ci.yml`'s `test` job) — no committed phase-17 file trips `tests/test_comment_provenance_guard.py`."
    status: resolved
    resolution: >
      RESOLVED post-verification by the execute-phase orchestrator. The two "review finding #3"
      citations (plus three sibling review-citation smells in the same new 17-05 tests) were
      reworded to state their rationale directly in commit aa5e567. The exact failing check now
      passes: `uv run pytest -q -m "not integration"` → 734 passed, 21 skipped, 0 failed, and the
      comment-provenance guard is green — CI on master is no longer RED. (Separately, code-review
      finding WR-01 was also fixed in commit 04ba3b8: the pump.yml health steps now carry
      `if: always()` so a RED drain step cannot silently skip the /health/schema drift monitor,
      strengthening criterion #4; the drain step's run: was hardened to a block scalar so pump.yml
      is strict-YAML-valid.)
    reason: >
      tests/test_queue_durability.py, committed by plan 17-05 (commit 5d00733, current HEAD is
      ef23629 with no fix commit after it), contains two "review finding #3" phrase citations
      inside docstrings/comments for the new anti-vacuous-proof test
      (test_pump_drains_future_due_job_with_zero_workers). This trips
      tests/test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree — a
      permanent, pre-existing CI gate that plans 17-01, 17-02, 17-03, and 17-04 each explicitly
      treated as a mandatory "Rule 1 - Bug" auto-fix deviation before completing (see their
      SUMMARY.md Deviations sections). 17-05 did not run the full hermetic suite
      (`uv run pytest -q -m "not integration"` or bare `uv run pytest -q`) before finishing — it
      only re-ran the `queueproof`-marker subset — so this violation shipped uncaught. Reproduced
      independently: `uv run pytest -q -m "not integration"` → 1 failed (this test), 732 passed,
      21 skipped. CI's "Test suite (hermetic)" job (`uv run pytest -q`, no DATABASE_URL) runs this
      exact test unconditionally (it needs no live DB) and is therefore RED on current master.
    artifacts:
      - path: "tests/test_queue_durability.py"
        issue: "Line 1155 and line 1183 contain the phrase \"review finding #3\", matching the guard's `finding-ref` pattern `(?i)\\bfinding\\s*#\\s*[0-9]\\b`."
    missing:
      - "Reword the two flagged comment/docstring lines in tests/test_queue_durability.py (around :1155 and :1183) to state the stubbing requirement and its rationale directly, without citing \"review finding #3\" — matching the wording discipline every sibling plan in this phase already applied to its own comments."
      - "Re-run `uv run pytest -q` (or `-q -m \"not integration\"`) after the fix and confirm the comment-provenance guard, and the rest of the hermetic suite, is green."
human_verification:
  - test: "Trigger a real GitHub Actions run of pump.yml (scheduled or workflow_dispatch) against the deployed Render service with PUMP_TOKEN provisioned, and confirm all three curl -f steps go green."
    expected: "The Drain step returns 200 with real counts; /health/ready and /health/schema both return 2xx; no step goes RED."
    why_human: "Requires a live Render deployment, a provisioned PUMP_TOKEN secret matching between GitHub Actions and Render, and an actual GitHub Actions cron/manual run — none of which exist in this local verification environment. The phase's own 17-03 and 17-04 SUMMARYs already flag this as a manual-only verification item."
---

# Phase 17: The Pump Verification Report

**Phase Goal:** Durable storage becomes durable execution — a job scheduled for later actually
fires even when nothing is knocking on the front door.
**Verified:** 2026-07-15
**Status:** passed (the single gap was resolved post-verification — see frontmatter `resolution` and commits aa5e567 + 04ba3b8)
**Re-verification:** Gap closure confirmed by the orchestrator (exact failing check re-run green)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Authenticated `GET /internal/pump` claims/drains due jobs and returns real counts (claimed/done/retried/dead/fenced/queue_depth), not a bare 200 | ✓ VERIFIED | `app/routes/pump.py:84-115` loops `drain.drain_once()` (imported, never forked) under a dual cap, aggregates `DrainOutcome` into `{claimed, done, retried, dead, fenced, queue_depth}` via `repo.count_open_jobs()`. Live-booted via `TestClient`: unauthenticated call → `401 {"detail": "unauthorized"}` (confirms wiring + fail-closed). `tests/test_pump_route.py` (10 tests, all pass) proves 401/200/bounded/infra/D-10 behavior; `-k auth`/`-k bounded`/`-k infra_failure` all green independently re-run. |
| 2 | A future-`available_at` job on a zero-live-worker instance still executes once the pump fires — proven by the queueproof anchor | ✓ VERIFIED | `tests/test_queue_durability.py::test_pump_drains_future_due_job_with_zero_workers` (live Postgres) independently re-run: PASSED. Asserts `live_queue_worker_threads() == []`, `repo.claim_job() is None` while future-dated, drains via `TestClient` → `/internal/pump` (never `drain_once()` directly), `claimed==1`/`done==1`, `orchestrator_calls == [run_id]` (stubbed `pipeline_glue.run_pipeline_now`, no real spend), a by-id row re-read to `state=='done'`, run reaches `COMPUTED` (confirmed non-terminal — `app/routes/runs.py:66-69` lists COMPUTED among in-flight/recoverable statuses), and `queue_depth==0`. Falsifying-mutation RED/GREEN evidence is pasted in 17-05-SUMMARY.md and is internally consistent (no-op drain loop → `claimed==0` RED; revert → GREEN; `git diff --exit-code app/routes/pump.py app/db/repo/jobs.py` clean). |
| 3 | README states the pump cadence, recovery-latency wording, and the 750-instance-hour/month arithmetic in plain checkable numbers | ✓ VERIFIED | README.md:139-166 states 30-minute cadence, nominal/best-effort recovery wording (not an absolute ≤30-min bound), `awake ≈ 15 ÷ cadence` idle-baseline math (~365 of 750 instance-hours), best-effort caveats (GitHub cron delay, 60-day auto-disable, workflow_dispatch, operator retry), the final-attempt-strand residual cited to Phase 18, and the counts-are-a-transport-signal caveat. `keepalive.yml` no longer referenced (0 hits); no stale "≤30-minute worst-case" phrase (0 hits). |
| 4 | `.github/workflows/pump.yml` is the ONLY cron; `keepalive.yml` is gone but both its jobs (`/health/ready` wake + `/health/schema` drift monitor) carry forward as RED-on-fail curl steps | ✓ VERIFIED | `.github/workflows/pump.yml` exists with 3 `curl -f` steps (`/internal/pump` `--max-time 420`, `/health/ready` `--max-time 90`, `/health/schema` `--max-time 90`), a `schedule: */30 * * * *`, `workflow_dispatch`, and a `concurrency` group. `.github/workflows/keepalive.yml` deleted (`git rm`, confirmed via `git log --diff-filter=D`). Only `.github/workflows/` file present: ci.yml, concurrency-proof.yml, deploy-migrate.yml, eval.yml, pump.yml — no second cron. `tests/test_pump_workflow.py` (4 tests) independently re-run: all pass, correctly avoiding the PyYAML `on`→`True` KeyError and comment-substring false positives. |
| 5 | The phase's own committed source passes the project's permanent hermetic CI gate (no regressions introduced) | ✓ RESOLVED (post-verification, commit aa5e567) | Was FAILED — see Gaps `resolution`; the guard trip on `tests/test_queue_durability.py` (17-05) trips `tests/test_comment_provenance_guard.py`. Independently reproduced. |

**Score:** 5/5 truths verified (0 present-but-behavior-unverified) — the single gap (truth #5) was resolved post-verification

### Money-Safety Invariants (explicitly requested)

| Invariant | Status | Evidence |
|---|---|---|
| D-10: double-failure re-raise → 503, never a false 200 | ✓ VERIFIED | `app/queue/drain.py:215-225` — the inner `except` on `fail_job()` itself raising does a bare `raise` (no `DrainOutcome.FENCED` assignment, no swallow); `lease_settled` stays `False`. `app/routes/pump.py:95-111`'s `try/except Exception` catches the propagated exception → `HTTPException(503, "pump unavailable")`, logging only `type(exc).__name__`. Both the narrow (`drain_once`-monkeypatched-to-raise) and the load-bearing real fake-repo chain (`claim_job` → leased job, `dispatch.handle` raises, `repo.fail_job` raises, driven through `TestClient`) tests independently re-run and pass, the latter also asserting `drain.held_tokens() == [token]` **after** the HTTP call (lease retained through the round trip). |
| Constant-time, fail-closed auth | ✓ VERIFIED | `app/routes/pump.py:65-79` — `_authorized()` returns `False` immediately on a falsy `pump_token` (before any compare), else `hmac.compare_digest(got, expected)` (never `==`). `tests/test_pump_route.py -k auth` (4 tests) independently re-run and pass, including the empty-secret-fails-closed-even-with-a-plausible-header case. |
| `claimed == done + retried + dead + fenced` | ✓ VERIFIED | Holds by construction (`app/routes/pump.py:96-101` — each claimed job increments exactly one bucket). Asserted explicitly in `test_auth_correct_token_returns_200_with_counts_invariant` (pass) and implicitly proven again by the live queueproof anchor's `claimed==1`/`done==1` assertions. |

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `app/queue/drain.py` | `DrainOutcome` StrEnum + `drain_once() -> DrainOutcome`, re-raising double-failure | ✓ VERIFIED | Matches must_haves exactly; mypy/ruff clean. |
| `app/db/repo/jobs.py` | `count_open_jobs(conn=None) -> int` | ✓ VERIFIED | `state IN ('pending', 'leased')`, `_conn_ctx` convention, docstring says "Seven functions". |
| `app/db/repo/__init__.py` | `count_open_jobs` re-exported | ✓ VERIFIED | Present in import block and `__all__`. |
| `app/routes/pump.py` | `GET /internal/pump` route | ✓ VERIFIED | Live-booted, wired, fail-closed. |
| `app/config.py` | `Settings.pump_token: str = ""` | ✓ VERIFIED | Present, empty-default convention. |
| `app/main.py` | `include_router(pump.router)` | ✓ VERIFIED | Present; route reachable via TestClient. |
| `.github/workflows/pump.yml` | sole cron, 3 curl -f steps | ✓ VERIFIED | Present, matches spec exactly. |
| `render.yaml` | `PUMP_TOKEN` sync:false | ✓ VERIFIED | Present at line 30-31. |
| `README.md` | cadence/750h/best-effort doc block | ✓ VERIFIED | Present, all grep checks pass. |
| `tests/test_pump_workflow.py` | static workflow structure guard | ✓ VERIFIED | 4 tests, all pass, comment-insensitive. |
| `tests/test_pump_route.py` | hermetic auth/bounded/infra tests | ✓ VERIFIED | 10 tests, all pass (4 auth / 2 bounded / 4 infra_failure). |
| `tests/test_repo_jobs_sql.py` | honest hermetic count_open_jobs test + 3 surface tests updated to seven | ✓ VERIFIED | Confirmed via file read + independent test run. |
| `tests/test_queue_durability.py` | queueproof anchor + live mixed-state count | ⚠️ VERIFIED BUT NOT CLEAN | Both new tests pass (independently re-run against live Postgres, 0 skipped), but the file's own comments trip a separate permanent CI gate — see Gaps. |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `DrainOutcome.__bool__` | `app/queue/worker.py:198` | truthiness contract | ✓ WIRED | EMPTY-only-falsy preserved; worker survival test passes. |
| `drain_once()` re-raise | `worker.py:203` except / `pump.py` try/except | exception propagation | ✓ WIRED | Both catch sites independently confirmed via passing tests. |
| `_authorized()` | `get_settings().pump_token` / `render.yaml` PUMP_TOKEN / `pump.yml` Bearer header | shared secret | ✓ WIRED | Config field present; workflow references `${{ secrets.PUMP_TOKEN }}`; route reads via `get_settings()`. |
| `count_open_jobs` | `pump.py`'s `queue_depth` field | facade call | ✓ WIRED | `repo.count_open_jobs()` called after the drain loop. |
| `@pytest.mark.queueproof` | `concurrency-proof.yml`'s second step | pre-existing marker collection | ✓ WIRED | Zero workflow edits; confirmed via `git log` (no phase-17 commits touch concurrency-proof.yml) and a live re-run showing the new tests collected under the existing marker. |

### Behavioral Spot-Checks (live-executed by this verifier)

| Behavior | Command | Result | Status |
|---|---|---|---|
| Route wired, fails closed with no token | `TestClient(app.main.app).get("/internal/pump")` | `401 {"detail": "unauthorized"}` | ✓ PASS |
| Hermetic pump/workflow/queue-drain/worker test files | `uv run pytest tests/test_pump_route.py tests/test_pump_workflow.py tests/test_repo_jobs_sql.py tests/test_queue_drain.py tests/test_queue_worker.py -q` | 60 passed | ✓ PASS |
| `ruff check .` / `mypy app` | as shown | All checks passed / Success: no issues found in 63 source files | ✓ PASS |
| Live queueproof anchor + mixed-state count (against `postgresql://pnhek@localhost:5432/payroll_pump_proof`) | `DATABASE_URL=... ALLOW_DB_RESET=1 uv run pytest tests/test_queue_durability.py -m queueproof -k "pump or count_open_jobs" -v -rs` | 2 passed | ✓ PASS |
| Whole queueproof marker gate | `DATABASE_URL=... ALLOW_DB_RESET=1 uv run pytest tests/ -m queueproof -v -rs` | 19 passed, 0 skipped | ✓ PASS |
| **Full hermetic suite (as CI runs it)** | `uv run pytest -q -m "not integration"` | **1 failed** (`test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree`), 732 passed, 21 skipped | ✗ FAIL |

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
|---|---|---|---|---|
| PUMP-01 | 17-01, 17-02, 17-04, 17-05 | Authenticated pump endpoint sharing one `drain_once()`, primary execution trigger | ✓ SATISFIED | Route live, auth fail-closed, shared drain_once, non-vacuous live proof. |
| PUMP-02 | 17-03 | 30-min cron cadence + README duty-cycle math | ✓ SATISFIED | pump.yml cadence + README block confirmed. |

No orphaned requirements — REQUIREMENTS.md maps only PUMP-01/PUMP-02 to Phase 17, both claimed and satisfied.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---|---|---|---|
| `tests/test_queue_durability.py` | 1155, 1183 | `finding #3` phrase — trips `test_comment_provenance_guard.py`'s permanent `finding-ref` gate | 🛑 Blocker | CI's hermetic "Test suite" job (`uv run pytest -q`, run on every PR/push to master) is currently RED on this exact commit. No debt-marker comment (TBD/FIXME/XXX) — this is a distinct, repo-specific comment-provenance CI gate that every sibling plan in this same phase (17-01 through 17-04) treated as a mandatory pre-completion fix. |

No TBD/FIXME/XXX markers found in any phase-17-modified file.

### Human Verification Required

1. **Test:** Trigger a real GitHub Actions run of `pump.yml` against the deployed Render service with `PUMP_TOKEN` provisioned (scheduled or via `workflow_dispatch`).
   **Expected:** All three `curl -f` steps (drain, `/health/ready`, `/health/schema`) return 2xx; the drain step's JSON body reports real counts.
   **Why human:** Requires a live Render deployment and matching `PUMP_TOKEN` secrets in both GitHub Actions and Render — not reproducible in this local verification environment. Both 17-03 and 17-04 SUMMARYs already flag this as their own manual-only verification item.

### Gaps Summary

Phase 17 substantively and verifiably achieves its goal: the pump route exists, is authenticated
fail-closed, shares the one `drain_once()` implementation, is proven — by an independently
re-executed, non-vacuous, live-Postgres test — to drain a future-due job on a zero-worker
cold-started instance, and the cron/README/workflow-fold-in criteria are all met exactly as
specified. The D-10 double-failure→503 invariant and the `claimed == done+retried+dead+fenced`
invariant both hold in the live route, not just in test doubles.

The one gap is real and independently reproduced, not a SUMMARY-trust issue: plan 17-05's final
commit (`5d00733`, current HEAD `ef23629`) left two "review finding #3" comment citations in
`tests/test_queue_durability.py` that trip this repo's own permanent
`test_comment_provenance_guard.py` CI gate. Every other plan in this exact phase (17-01, 17-02,
17-03, 17-04) hit and fixed the identical guard as a "Rule 1 - Bug" deviation before calling
itself done — 17-05 is the one plan whose SUMMARY does not show a full hermetic-suite run, and
the gap it consequently missed is exactly the kind that guard exists to catch. This is a small,
mechanical, two-line fix with a well-established precedent in this same phase, and it does not
touch the money-path or the pump's runtime behavior — but it currently makes CI red on master,
which blocks a clean phase close.
