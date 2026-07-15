---
phase: 17-the-pump
plan: 03
subsystem: infra
tags: [github-actions, cron, render, keepalive, pump, docs]

requires:
  - phase: 16-queue-substrate-unblocked-webhook
    provides: durable jobs table + lease/claim protocol + drain_once()
provides:
  - "pump.yml: the sole 30-minute cron hitting the service (drain + wake + schema-drift check)"
  - "render.yaml PUMP_TOKEN sync:false secret entry"
  - "README cadence/750h/best-effort documentation block"
  - "tests/test_pump_workflow.py: a committed static regression guard for the keepalive fold-in"
affects: [17-04-internal-pump-route, 18-failure-policy-sweep-deletion]

tech-stack:
  added: []
  patterns:
    - "workflow-level concurrency group (constant name, cancel-in-progress: false) to serialize scheduled vs manual cron runs without racing SKIP LOCKED correctness"
    - "comment-stripped static text/structure guard for workflow YAML (avoids PyYAML's YAML 1.1 unquoted-on boolean coercion and comment-substring false positives)"

key-files:
  created:
    - .github/workflows/pump.yml
    - tests/test_pump_workflow.py
  modified:
    - render.yaml
    - README.md

key-decisions:
  - "pump.yml's authenticated /internal/pump drain uses --max-time 420 (cold-start 60 + 17-04's between-jobs cap 120 + external-call allowance 240, no headroom claimed) — a NOMINAL operating budget, not a proven bound. Correctness rests on lease-reclaim (lease_seconds=900), not the curl timeout."
  - "The two carried-over health checks keep --max-time 90 verbatim from keepalive.yml; only the new pump step gets the larger, independently-derived budget."
  - "keepalive.yml is deleted (not deprecated-in-place); pump.yml reuses its RENDER_URL secret and both of its jobs (wake + schema-drift)."
  - "README recovery wording is NOMINAL/best-effort, not an absolute <=30-minute bound, and explicitly documents the final-attempt lease-strand residual deferred to Phase 18 rather than claiming universal auto-recovery."
  - "The BackgroundTasks limitation bullet was corrected to state the durable queue's TRUE partial-migration state (proven only on operator Retrigger; the inbound-email path still runs on BackgroundTasks) rather than overclaiming a full cutover that has not shipped yet."

patterns-established:
  - "Static, comment-insensitive, hermetic YAML-workflow structure tests as a durable regression guard for security/operational invariants (criterion-style guards), reusable for future workflow-folding changes."

requirements-completed: [PUMP-02]

coverage:
  - id: D1
    description: "pump.yml is the sole cron (30-min schedule + workflow_dispatch + workflow-level concurrency group), with three curl -f steps (authenticated /internal/pump drain, /health/ready, /health/schema) so the schema-drift monitor survives the keepalive fold-in"
    requirement: PUMP-02
    verification:
      - kind: unit
        ref: "tests/test_pump_workflow.py::test_pump_yml_exists_and_keepalive_yml_deleted"
        status: pass
      - kind: unit
        ref: "tests/test_pump_workflow.py::test_exactly_one_scheduled_workflow"
        status: pass
      - kind: unit
        ref: "tests/test_pump_workflow.py::test_pump_yml_carries_all_three_endpoints"
        status: pass
      - kind: unit
        ref: "tests/test_pump_workflow.py::test_pump_yml_has_workflow_dispatch"
        status: pass
    human_judgment: false
  - id: D2
    description: "render.yaml declares PUMP_TOKEN as a sync:false secret entry (never committed as a value)"
    requirement: PUMP-02
    verification:
      - kind: other
        ref: "grep -q 'PUMP_TOKEN' render.yaml"
        status: pass
    human_judgment: false
  - id: D3
    description: "README documents the 30-minute cadence, the awake ~= 15/cadence idle-baseline duty-cycle math, the 750-instance-hour ceiling, best-effort caveats, and the final-attempt-strand recovery residual (cited to Phase 18) without an absolute <=30-min recovery claim"
    requirement: PUMP-02
    verification:
      - kind: other
        ref: "grep checks: 30-minute cadence, 750, awake, baseline/nominal, best-effort, workflow_dispatch/60-day, no keepalive.yml reference, no absolute worst-case phrase, 15/cadence formula, final-attempt/Phase-18 citation — all pass (see Task Commits)"
        status: pass
    human_judgment: true
    rationale: "README wording quality (honest, non-overclaiming, checkable-numbers framing) is a judgment call verified against the plan's explicit prohibitions, not purely mechanical; a human should skim the final prose."
  - id: D4
    description: "Live cron firing (the actual 30-minute GitHub Actions schedule executing against the deployed Render service + real PUMP_TOKEN) is unverified by this plan — it is explicitly a manual-only verification per the phase's validation scope"
    verification: []
    human_judgment: true
    rationale: "This static guard proves workflow STRUCTURE only; confirming the schedule actually fires against production requires the operator to watch a live Actions run after PUMP_TOKEN is provisioned (see User Setup below)."

duration: 15min
completed: 2026-07-15
status: complete
---

# Phase 17 Plan 03: The Pump — Cron Workflow, Secret Wiring, and Cadence Docs Summary

**Folded `keepalive.yml`'s wake+schema-drift checks and a new authenticated `/internal/pump` drain into a single `pump.yml` cron (30-min schedule, workflow-level concurrency guard), added the `PUMP_TOKEN` render.yaml secret, documented the cadence/750h/best-effort math honestly in the README, and shipped a committed static regression test guarding the fold-in.**

## Performance

- **Duration:** ~15 min
- **Completed:** 2026-07-15T14:44:21Z
- **Tasks:** 3/3 completed
- **Files modified:** 4 (1 created workflow, 1 deleted workflow, 1 created test, 2 modified — render.yaml, README.md)

## Accomplishments

- `pump.yml` is now the sole cron hitting the service: a 30-minute `schedule` + `workflow_dispatch` trigger, a workflow-level `concurrency` group (`pump`, `cancel-in-progress: false`) so a scheduled and a manual run can never race a live drain, and three `curl -f` steps in order — the authenticated `/internal/pump` drain (`--max-time 420`), `/health/ready` (wake + Supabase touch, `--max-time 90`), and `/health/schema` (drift → RED, `--max-time 90`).
- The pump step's `--max-time 420` is derived honestly and named term-by-term (cold-start ≤60s + the sibling plan's 120s between-jobs cap + a ≈240s worst-case external-call allowance, no headroom claimed), and the comment explicitly states the correctness guarantee is lease-reclaim (`lease_seconds=900`), not the curl budget — with the final-attempt lease-strand residual named and deferred, not silently omitted.
- `keepalive.yml` is deleted (`git rm`, not deprecated-in-place); `render.yaml` gains a `PUMP_TOKEN` `sync: false` secret entry immediately after `WEBHOOK_SIGNING_SECRET`.
- README's stale `keepalive.yml` sentence is replaced with a full cadence documentation block: the 30-minute cadence, nominal/best-effort recovery wording (explicitly not an absolute ≤30-minute bound), the `awake ≈ 15 ÷ cadence` idle-baseline arithmetic and the 750-instance-hour ceiling that forces 30 minutes over 10, GitHub's cron-delay/60-day-auto-disable caveats, the honest final-attempt-strand recovery residual (cited to Phase 18), and the counts-are-a-transport-signal caveat. The `BackgroundTasks` limitation bullet is corrected to reflect the queue's true partial-migration state rather than overclaiming a full cutover.
- `tests/test_pump_workflow.py` is a hermetic, comment-insensitive static guard: pump.yml exists / keepalive.yml is gone / exactly one workflow is scheduled / all three endpoints survive the fold-in / `workflow_dispatch` is present — proven to avoid both the PyYAML unquoted-`on` boolean-coercion KeyError and the comment-substring false-positive trap.

## Task Commits

Each task was committed atomically:

1. **Task 1: Create pump.yml, delete keepalive.yml, add PUMP_TOKEN to render.yaml** — `4d9306c` (feat)
2. **Task 2: Document the pump cadence, recovery bound, and 750h duty-cycle math in the README** — `a8227ed` (docs)
3. **Task 3: Committed static regression test for criterion #4 (workflow structure guard)** — `da16af9` (test)

**Deviation fix (Rule 1, comment-provenance guard):** `4b3a0a0` (fix) — see Deviations below.

_Plan metadata commit intentionally not separate — see State Updates note below (`commit_docs: true`, `.planning/` not gitignored; the final metadata commit follows this SUMMARY per protocol)._

## Files Created/Modified

- `.github/workflows/pump.yml` — new; the sole cron (30-min schedule + `workflow_dispatch` + `concurrency` group), three `curl -f` steps (drain, ready, schema).
- `.github/workflows/keepalive.yml` — deleted (`git rm`); its `RENDER_URL` secret and both jobs are carried into `pump.yml`.
- `render.yaml` — added `PUMP_TOKEN` `sync: false` entry after `WEBHOOK_SIGNING_SECRET`.
- `README.md` — replaced the stale keepalive sentence with the pump cadence/750h/best-effort documentation block; corrected the `BackgroundTasks` limitation bullet.
- `tests/test_pump_workflow.py` — new; hermetic static structure guard for criterion #4 (4 tests, all pass).

## Decisions Made

- Followed the plan's exact `--max-time 420` derivation and comment content verbatim (cold-start ≤60s + 120s between-jobs cap + ≈240s external-call allowance, no headroom claimed, provisional-until-live-smoke, correctness = lease-reclaim not curl budget).
- `concurrency.group: pump` used a literal constant (not `${{ github.ref }}`) per the plan's explicit instruction, so scheduled and manual runs share one queue.
- README's cadence block was placed as a new subsection ("The pump: cadence, recovery, and the 750-hour budget") inside "Deployment notes", directly replacing the stale keepalive sentence, rather than as a wholly separate top-level section — kept the existing document structure intact.
- Corrected the `BackgroundTasks` README bullet to state the queue's actual partial-migration state (proven only on operator Retrigger per Phase 16; the money-path webhook itself still schedules via `BackgroundTasks` pending a later cutover) instead of the more sweeping "durable queue replaces BackgroundTasks" framing that would have overclaimed what has shipped — verified against `app/routes/webhook.py`'s live `background_tasks.add_task` calls before writing the sentence.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `tests/test_pump_workflow.py`'s own docstring tripped the project's comment-provenance guard**
- **Found during:** Post-task-3 full-suite verification (`uv run pytest -q`)
- **Issue:** The docstring's own summary line read `"...ROADMAP criterion #4 (Phase 17-03): the keepalive-into-pump fold-in..."` — the `Phase 17-03` citation matched the `phase-ref` pattern (`\bPhase [0-9]`) enforced by `tests/test_comment_provenance_guard.py`, a permanent CI gate (from the v3 milestone's comment-hygiene phase) that scans `.github/workflows/*.yml`, `render.yaml`, and `tests/**/*.py` (among other globs) for ticket/decision/phase provenance citations. Source text must explain the code, not cite the phase that produced it.
- **Fix:** Reworded the docstring's opening line to drop the parenthetical phase citation while keeping the "ROADMAP criterion #4" description (not itself a blocked pattern) and the guard's purpose intact.
- **Files modified:** `tests/test_pump_workflow.py`
- **Verification:** `uv run pytest tests/test_comment_provenance_guard.py tests/test_pump_workflow.py -q` → 9 passed; full suite re-run (`uv run pytest -q`) → 724 passed, 68 skipped, 0 failed.
- **Committed in:** `4b3a0a0`

---

**Total deviations:** 1 auto-fixed (Rule 1 — bug/CI-gate fix)
**Impact on plan:** Necessary correctness fix, no scope creep. `pump.yml` and `render.yaml` themselves produced zero comment-provenance violations on first write — only the test file's own docstring needed the correction, caught immediately by the project's existing CI gate rather than shipping silently.

## Issues Encountered

None beyond the auto-fixed deviation above.

## User Setup Required

**External services require manual configuration** before the live cron will actually authenticate and drain jobs (per the plan's `<user_setup>`):

- Generate a random `PUMP_TOKEN` secret (e.g. `openssl rand -hex 32`).
- Add it as a GitHub Actions repo secret (Settings → Secrets and variables → Actions → New secret, name `PUMP_TOKEN`).
- Add the SAME value as the `render.yaml` `PUMP_TOKEN` `sync:false` entry in the Render dashboard — the two values must match.
- Confirm the existing `RENDER_URL` GitHub Actions secret (reused from the deleted `keepalive.yml`) is still set; `pump.yml` depends on it.

This provisioning is a prerequisite for the live cron to succeed, but is not blocking for this plan's own deliverables (workflow structure, secret declaration, docs, and the static test) — it is deferred human setup, consistent with the plan's own scope (the `/internal/pump` route this workflow curls does not exist yet either; it lands in the sibling plan 17-04).

## Next Phase Readiness

- `pump.yml`'s structure is proven by the committed static guard and is ready to receive a working `/internal/pump` route from the sibling plan (17-04), and the `PUMP_TOKEN` env var/setting from that same plan.
- The README's cadence documentation (PUMP-02) is complete and internally consistent with 17-04's `_MAX_WALL_CLOCK_SECONDS` derivation comment (kept numerically coherent per the plan's `key_links`).
- No blockers. The live-cron firing itself remains an operator-driven manual verification (per the phase's validation scope) once `PUMP_TOKEN` is provisioned and 17-04's route ships.

---
*Phase: 17-the-pump*
*Completed: 2026-07-15*

## Self-Check: PASSED

- FOUND: `.github/workflows/pump.yml`
- FOUND: `tests/test_pump_workflow.py`
- FOUND: `render.yaml`
- FOUND: `README.md`
- FOUND: `.planning/phases/17-the-pump/17-03-SUMMARY.md`
- CONFIRMED DELETED: `.github/workflows/keepalive.yml`
- FOUND commit: `4d9306c`
- FOUND commit: `a8227ed`
- FOUND commit: `da16af9`
- FOUND commit: `4b3a0a0`
