---
phase: 17
slug: the-pump
status: approved
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-14
approved: 2026-07-14
validated: 2026-07-15
---

# Phase 17 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `17-RESEARCH.md` § Validation Architecture. Per-task IDs are
> assigned by the planner/executor; the requirement→test mapping and Wave 0
> gaps below are fixed by research.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (already configured — no Wave 0 install) |
| **Config file** | `pyproject.toml` `[tool.pytest.ini_options]` — the `queueproof` marker is already registered |
| **Quick run command** | `uv run pytest tests/test_pump_route.py tests/test_queue_drain.py tests/test_repo_jobs_sql.py -q` |
| **Full suite command** | `uv run pytest -q` (hermetic) |
| **Live-DB command** | `uv run pytest tests/ -m queueproof -v -rs` (already wired into `concurrency-proof.yml`'s second step) |
| **Estimated runtime** | hermetic quick-run ~seconds; full hermetic suite tens of seconds; `queueproof` needs a live Postgres (`DATABASE_URL`) |

---

## Sampling Rate

- **After every task commit:** Run the quick-run command above.
- **After every plan wave:** Run the full hermetic suite; run the `queueproof` command if a live Postgres is available locally, otherwise defer to the `concurrency-proof.yml` CI gate.
- **Before `/gsd-verify-work`:** Full hermetic suite green **and** the `queueproof` durability anchor demonstrated able to fail (falsifying mutation → RED) and pass against the real fix (PROOF-05 house discipline).
- **Max feedback latency:** ~60 seconds (hermetic quick-run).

---

## Per-Task Verification Map

*Task IDs (`17-NN-NN`) are assigned by the planner. Rows below fix the requirement → test binding the tasks must satisfy; the executor fills Task ID / Status.*

| Requirement | Behavior under test | Threat Ref | Secure Behavior | Test Type | Automated Command | Status / File |
|-------------|---------------------|------------|-----------------|-----------|-------------------|---------------|
| PUMP-01 (criterion #1 — real counts) | `drain_once()` returns the correct specific `DrainOutcome` for each of: empty, done, retried, dead, fenced | — | N/A | hermetic | `uv run pytest tests/test_queue_drain.py -k drain_once -q` | ✅ `tests/test_queue_drain.py` (5 tests green) |
| PUMP-01 (criterion #1 — auth) | 401 on missing/wrong/empty-secret Bearer; 200 on correct token | T-17-01 (timing), T-17-02 (fail-open) | constant-time `hmac.compare_digest`; fail-closed when `PUMP_TOKEN` unset | hermetic (`TestClient`, `WORKER_COUNT=0` pinned) | `uv run pytest tests/test_pump_route.py -k auth -q` | ✅ `tests/test_pump_route.py` (4 tests green) |
| PUMP-01 (criterion #2 — anti-vacuous anchor) | Future-`available_at` job, **zero live worker threads**, drained by hitting `/internal/pump` — not by an incidental worker | — | N/A | `queueproof` (live PG) | `uv run pytest tests/test_queue_durability.py -m queueproof -k pump -v` | ✅ `tests/test_queue_durability.py::test_pump_drains_future_due_job_with_zero_workers` (no `live_worker`; asserts `live_queue_worker_threads() == []`; falsifying mutation demonstrated RED — PROOF-05) |
| PUMP-01 (criterion #1 — queue depth) | `count_open_jobs()` correct across pending/leased/done/dead mixes | — | N/A | hermetic (`fake_repo`) + `queueproof` | `uv run pytest tests/test_repo_jobs_sql.py -k count_open_jobs -q` | ✅ `tests/test_repo_jobs_sql.py` (2 hermetic tests green) + live mixed-state count in `test_queue_durability.py` |
| PUMP-01 (D-05 — bounded drain) | Loop stops at max-jobs cap and at wall-clock cap even mid-backlog | T-17-03 (DoS) | dual cap bounds each invocation | hermetic (stub `drain_once` non-EMPTY, assert loop exits at cap) | `uv run pytest tests/test_pump_route.py -k bounded -q` | ✅ `tests/test_pump_route.py` (2 tests green) |
| PUMP-01 (D-10 — infra failure semantics) | DB failure during drain surfaces as 5xx, not 200 | — | RED cron on real infra outage | hermetic (`fake_repo` raising from `claim_job`/`count_open_jobs`) | `uv run pytest tests/test_pump_route.py -k infra_failure -q` | ✅ `tests/test_pump_route.py` (4 tests green) |
| PUMP-02 (criterion #4 — workflow structure) | `pump.yml` has schedule + `workflow_dispatch` + exactly 3 `curl -f` steps; `keepalive.yml` is gone | — | N/A | static (`yaml.safe_load` assert) | `uv run pytest tests/test_pump_workflow.py -q` | ✅ `tests/test_pump_workflow.py` (5 tests green — shipped as automated, not manual) |

*Status legend: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky · W0 = Wave 0 file not yet created.*

---

## Wave 0 Requirements

- [x] `tests/test_pump_route.py` — **new file**. Auth (401/200), bounded-drain-loop cap, D-10 infra-failure-vs-business-outcome semantics. Hermetic, `fake_repo`-based, following `tests/test_queue_drain.py`'s style. *(10 tests, all green.)*
- [x] New `queueproof`-marked test appended to `tests/test_queue_durability.py` — the criterion #2 anti-vacuous anchor. Must **not** request `live_worker`; must assert `live_queue_worker_threads() == []` as an explicit precondition, mirroring the module's existing precondition-assertion discipline. *(`test_pump_drains_future_due_job_with_zero_workers` — signature `(seeded_db, monkeypatch)`, no `live_worker`; asserts zero threads at :1222; passes against live Postgres.)*
- [x] `tests/test_repo_jobs_sql.py` — add hermetic coverage for `count_open_jobs`. *(2 hermetic tests green.)*
- [x] The ~15-site rewrite of `assert drain.drain_once() is True/False` → specific `DrainOutcome` assertions (Pitfall 1). Not a new file, but a real task; done-check: `grep -rn "drain_once() is True\|drain_once() is False" tests/` returns zero hits. *(Verified 2026-07-15: zero hits.)*

*Existing infrastructure (pytest, `queueproof` marker, `concurrency-proof.yml` second step, `WORKER_COUNT=0` suite pin) covers everything else — no framework install needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| A live GitHub cron actually fires `pump.yml` and drains a due job on the deployed Render instance | PUMP-02 (criterion #2, end-to-end) | GitHub scheduled cron + a real Render deploy cannot run inside the unit suite | After deploy: seed a due `run_pipeline` job, trigger `pump.yml` via `workflow_dispatch`, confirm the Actions run is GREEN and the seeded job reaches `state='done'`. |
| Render free-tier request-duration ceiling ≥ the pump's nominal worst case (~420s: cold-start ≤60 + 120s between-jobs cap + ≈240s external-call allowance + overhead — NOT the 210s inter-write stall gap; 17-REVIEWS #1/#2) | PUMP-01 / D-05 | Render's server-side request ceiling is undocumented (Open Question #2 / Assumption A1) | **Drive a DELIBERATELY long-running controlled request that crosses the ceiling being validated (17-REVIEWS #4 — a routine "small backlog" finishes in seconds and proves nothing):** seed ONE `run_pipeline` job whose handler is stubbed/slowed to `sleep` TOWARD the ~420s cap (e.g. a temporary env-gated slow-handler or a monkeypatched sleep on the deployed instance), with NO paid-provider call and NO real client send, then hit the deployed `/internal/pump` and time the response. PASS = the request returns a 200 count JSON (no proxy-level 502/timeout truncates it) at a duration ≥ the `--max-time 420` / `_MAX_WALL_CLOCK_SECONDS` region → Render's ceiling is above the pump's nominal worst case, so `--max-time 420` and the 120s cap are safe. FAIL = a 502/proxy timeout truncates the response before ~420s → Render's server-side ceiling is BELOW the budget; tighten `_MAX_WALL_CLOCK_SECONDS` (and the curl `--max-time`) below the observed ceiling. The drain stays correct either way (idempotent, lease-fenced; a job with attempts remaining is reclaimed next cadence). |
| `/health/schema` still fails RED on a manual Supabase drift after the keepalive fold-in | PUMP-02 (criterion #4 trap) | Requires a deliberately-drifted live schema; the point is that the monitor survived the `keepalive.yml → pump.yml` absorption | Confirm `pump.yml`'s `/health/schema` curl step goes RED when the live schema diverges from `schema.sql` (the drift monitor keepalive shipped must not be silently dropped). |

---

## Validation Sign-Off

Plan-level checks below verified by gsd-plan-checker (2026-07-14); the two execution-time boxes were closed by the post-execution validation audit (2026-07-15).

- [x] All tasks have `<automated>` verify or a Wave 0 dependency (workflow-structure shipped as an automated static guard; live-cron is the only manual carve-out, justified above)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 60s
- [x] Criterion #2 anchor demonstrated able to fail (falsifying mutation pasted RED) per PROOF-05 — *executed in 17-05; RED/GREEN evidence in 17-05-SUMMARY.md, mutation documented in the anchor docstring (test_queue_durability.py:1166-1171), confirmed by 17-VERIFICATION.md truth #2*
- [x] `nyquist_compliant: true` set in frontmatter
- [x] `wave_0_complete` — *all four Wave 0 items shipped and green (audit 2026-07-15)*

**Approval:** validation strategy approved 2026-07-14 (gsd-plan-checker, 0 blockers); execution-time boxes closed by post-execution audit 2026-07-15 (0 gaps).

## Validation Audit 2026-07-15

State A audit of the executed phase against this contract. Every requirement row is COVERED by a green automated test; all four Wave 0 items shipped; the criterion #2 anchor is non-vacuous and its falsifying mutation is demonstrated. The comment-provenance CI gate that 17-VERIFICATION flagged (truth #5) is green in the current tree (fixed in commit aa5e567).

| Metric | Count |
|--------|-------|
| Requirements audited | 7 rows (PUMP-01 × 6, PUMP-02 × 1) |
| Gaps found | 0 |
| Resolved | 0 (none needed) |
| Escalated | 0 |

Live checks run this audit: quick-run `tests/test_pump_route.py tests/test_queue_drain.py tests/test_repo_jobs_sql.py` → 44 passed; `tests/test_comment_provenance_guard.py` → 5 passed; `tests/test_pump_workflow.py` → 5 passed; all per-requirement `-k` selectors resolve to the expected test counts; anchor confirmed to omit `live_worker` and assert zero worker threads.
