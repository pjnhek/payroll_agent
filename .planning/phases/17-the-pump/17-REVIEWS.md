---
phase: 17
reviewers: [codex]
review_round: 2
reviewed_at: 2026-07-15T04:25:53Z
plans_reviewed: [17-01-PLAN.md,17-02-PLAN.md,17-03-PLAN.md,17-04-PLAN.md,17-05-PLAN.md]
supersedes: "round 1 (commit bdc91d9) — its 3 HIGH + mediums were incorporated in commit 9614161; round-1 detail lives in git history"
---

# Cross-AI Plan Review — Phase 17 (Round 2, confirming)

> Round 1 (Codex) found 3 HIGH + 5 MEDIUM; all were incorporated or explicitly deferred/rejected in the replan (commit `9614161`). This round-2 confirming review checks those fixes against source and looks for fix-induced regressions. **Only the still-open findings below are actionable** — the CONFIRMED items require no further plan change.

## Codex Review (Round 2)

## 1) Summary

The revisions materially improve the plans, but two gaps remain:

- The `fail_job()` double-failure behavior is correct, though the planned route-level test is weaker than the plan’s own stated requirement.
- The wall-clock derivation is still not a defensible upper bound. It omits cold-start time and treats external-call timeout totals as though they include application work.
- The durability proof now correctly stubs the real pipeline and is non-vacuous.

Overall risk: **HIGH**, driven by the unresolved request-timeout derivation.

## 2) Per-fix confirmation

### Fix #1 — double failure must propagate: PARTIAL

The production design is correct.

- `lease_settled` starts false at `app/queue/drain.py:152`.
- The current double-failure branch logs but does not settle the lease at `app/queue/drain.py:180-187`.
- Adding a bare `raise` there still executes the `finally`, but the token is discarded only when `lease_settled` is true at `app/queue/drain.py:188-191`. Therefore the token remains retained.
- The worker catches exceptions around the entire iteration and continues the loop at `app/queue/worker.py:184-211`.
- Shutdown releases the retained token once through `repo.release_leases(drain.held_tokens())` at `app/queue/worker.py:237-260`. The database release is token-fenced, so a stale token is harmless; the existing test documents that at `tests/test_queue_drain.py:808-811`.
- No other production caller exists today: the only current application call is the worker at `app/queue/worker.py:198`. Direct test callers are explicitly scheduled for conversion.

The unit-test reconciliation is also correct: the revised plan retains the token assertion and changes the call to `pytest.raises`.

The remaining gap is the route test. The plan promises an end-to-end hermetic case—“handler raises AND fail_job raises → 503 + lease retained”—at `17-04-PLAN.md:26`, but the actual task only monkeypatches `drain_once()` to raise at `17-04-PLAN.md:197-200`. That proves exception-to-503 mapping, but not that the real double-failure path both propagates and retains its token through the HTTP call.

The worker-survival test is underspecified too. It signals only the throwing first call, then says to assert that the worker “keeps polling” at `17-01-PLAN.md:194-198`. Merely checking `thread.is_alive()` would not prove a second iteration occurred.

### Fix #2 — 420-second curl derivation: REGRESSED

The revision correctly recognizes that 210 seconds is an inter-write gap, not an entire job-runtime bound. The source explicitly says so at `app/routes/runs.py:43-64`.

However, the replacement derivation still overclaims:

- Structured extraction/suggestion can consume up to two 45-second attempts each; the shared timeout and retry structure are documented at `app/llm/client.py:47-71` and implemented at `app/llm/client.py:218-248`.
- Clarification drafting adds a 30-second call at `app/pipeline/compose_email.py:33-39` and `app/pipeline/compose_email.py:177-183`.
- The live clarification path then performs a Resend network send at `app/pipeline/clarification.py:492-503` and `app/email/gateway.py:339-340`.
- The installed Resend client defaults to another 30-second requests timeout at `.venv/lib/python3.12/site-packages/resend/http_client_requests.py:13-14,33-42`.

Thus 240 seconds is approximately the sum of external-call timeout allowances: `90 + 90 + 30 + 30`. It leaves no quantified time for deterministic calculation, PDF/data preparation where applicable, database calls, scheduling overhead, or network/SDK overhead. Calling it “conservative” is unsupported.

More importantly, `curl --max-time 420` also includes Render cold start. The existing workflow itself budgets as much as 60 seconds for that at `.github/workflows/keepalive.yml:39-46`. The plan’s claimed request ceiling is:

`120s between-jobs cap + 240s final job + up to 60s cold start = 420s`

That consumes the full curl limit before ordinary overhead. The claimed “~60s headroom” at `17-03-PLAN.md:54-58` and `17-04-PLAN.md:57-60` does not exist.

### Fix #3 — durability proof stubs the pipeline: CONFIRMED

This correction is complete.

- The queue handler really invokes `pipeline_glue.run_pipeline_now(run_id)` at `app/queue/handlers/pipeline.py:154-159`.
- The orchestrator catches normal stage failures, records ERROR, and returns at `app/pipeline/orchestrator.py:221-247`; therefore a job can otherwise reach `done` while payroll processing failed.
- The proposed test patches the correct module-object seam and records `orchestrator_calls` at `17-05-PLAN.md:110-125`.
- This mirrors the existing proven seam at `tests/test_queue_durability.py:1016-1027`.
- Asserting `orchestrator_calls == [run_id]`, job state `done`, run status `computed`, `claimed == 1`, `done == 1`, and `queue_depth == 0` proves the intended handler ran exactly once and prevents an ERROR-run false positive.
- `WORKER_COUNT=0` is hard-set before application import at `tests/conftest.py:37-45`, while the explicit thread scan at `tests/conftest.py:67-75` supplies the additional no-worker precondition.
- The module already carries `integration` and `queueproof` markers at `tests/test_queue_durability.py:112-118`, and the CI marker-based gate already collects it at `.github/workflows/concurrency-proof.yml:105-159`.

### Round-1 MEDIUM bundle: CONFIRMED

The medium fixes are properly represented:

- All three stale six-function tests are identified from the actual locations at `tests/test_repo_jobs_sql.py:193-219`, `:228-239`, and `:242-263`, and the plan updates all three.
- The hermetic `count_open_jobs` claim is honestly limited to integer conversion and exact SQL text; live mixed-state behavior is moved to the real-Postgres proof.
- The workflow guard avoids the PyYAML 1.1 `on:` coercion trap and adds a committed criterion-#4 test.
- Both pump test plans require settings-cache cleanup after the test, matching the existing before/after fixture at `tests/test_repo_jobs_sql.py:28-31`.
- The pump response invariant `claimed == done + retried + dead + fenced` is explicitly constructed and tested.
- The catch-all wording now acknowledges that unexpected programming errors also become 503.

## 3) New/missed concerns

### HIGH — `--max-time 420` has zero demonstrated margin

This is the main unresolved issue. The new derivation fixes the category error around 210 seconds but introduces another: it ignores cold-start time and describes the 240-second external-call total as though it also covers local work.

A nominal worst case already reaches 420 seconds before ordinary overhead:

`60 cold start + 120 loop allowance + 240 external calls = 420`

That can produce false-red cron runs against healthy but slow processing.

### MEDIUM — route-level double-failure test contradicts its must-have

`17-04-PLAN.md:26` requires the real handler/failure-write chain and lease-retention assertion. The task at `17-04-PLAN.md:197-200` substitutes an already-raised exception. The latter is useful but does not replace the former.

This should either be corrected to exercise the real `drain_once()` path through `TestClient`, or the must-have should be weakened explicitly. Given the round-1 resolution, the former is appropriate.

### LOW — worker survival proof needs a second-iteration handshake

The planned first-call Event proves only that the exception occurred. Require a second Event or `calls >= 2` condition after the exception. Otherwise “thread remains alive” can pass while the worker never actually resumed polling.

### LOW — `COMPUTED` is mislabeled as terminal

The revised durability plan repeatedly calls `COMPUTED` terminal. Source comments classify it as recoverable/in-flight at `app/routes/runs.py:66-69`, and normal processing immediately advances `COMPUTED` to `AWAITING_APPROVAL` at `app/pipeline/orchestrator.py:1010-1014`.

This does not make the test vacuous—the status still distinguishes the stubbed success path from ERROR/EXTRACTING—but the plan should call it an observable post-handler status, not terminal.

### LOW — scheduled-workflow static test should ignore comments

The current keepalive file contains `schedule:` in both prose and YAML at `.github/workflows/keepalive.yml:5-19`. A simple “file contains `schedule:` or `cron:`” scan is comment-sensitive. The committed test should either strip comment-only lines or parse YAML using the documented `data.get(True, data.get("on"))` workaround.

## 4) Suggestions

1. Rework the timeout arithmetic before execution:

   - Include cold start explicitly.
   - Treat 240 seconds as external-call allowance, not complete job runtime.
   - Either raise the curl ceiling with documented margin or reduce the route cap.
   - If a hard bound is required, ensure every provider call has an explicit wall-clock timeout.

2. Add two route tests:

   - A narrow `drain_once raises → 503` mapping test.
   - A real fake-repo chain: handler raises, `fail_job` raises, endpoint returns 503, retained token is asserted.

3. Make the worker test wait for a confirmed second `drain_once()` invocation.

4. Replace “terminal COMPUTED” with “observable COMPUTED status set by the stub.”

5. Make the cron-count static guard comment-insensitive.

## 5) Overall risk

**HIGH**

The core queue semantics and durability proof are now strong. The remaining high risk is operational: the revised 420-second timeout is presented as safely derived, but source tracing shows no actual headroom and a credible healthy execution can exceed it.

---

## Consensus Summary (Round 2)

Single source-grounded reviewer (Codex). It CONFIRMED Fix #3 (pipeline stub) and the whole MEDIUM bundle as complete and correct, CONFIRMED Fix #1's production design (traced lease retention + worker survival + token-fenced release + no other callers), but found the Fix #2 timeout re-derivation **REGRESSED** and surfaced one internal contradiction plus three LOWs. Overall risk **HIGH — operational**, driven entirely by the unresolved timeout margin.

### Still-open / actionable

1. **HIGH — `--max-time 420` has no demonstrated margin (Fix #2 regressed) [17-03, 17-04].**
   The re-derivation fixed the 210s category error but introduced another: ~240s is the *sum of external-call timeout allowances* on the clarification path (extraction 2×45 `app/llm/client.py:218-248`, suggestion 2×45, clarification draft 30 `app/pipeline/compose_email.py:177-183`, Resend send 30 `resend/http_client_requests.py:13-14`), leaving zero quantified time for deterministic compute, DB, and scheduling — so calling it "conservative total job runtime" is unsupported. Worse, `curl --max-time 420` also spans Render **cold-start** (up to 60s per `.github/workflows/keepalive.yml:39-46`): `60 + 120 loop + 240 external = 420`, consuming the full curl limit before overhead. The claimed "~60s headroom" (`17-03-PLAN.md:54-58`, `17-04-PLAN.md:57-60`) does not exist → a healthy-but-slow pump can go **false-RED**.
   *Fix:* budget cold-start explicitly; treat 240s as external-call *allowance* not total runtime; either raise the curl ceiling with real documented margin OR lower the route cap; ideally hard-bound job runtime by ensuring every provider call has an explicit wall-clock timeout, then derive from that bound.

2. **MEDIUM — the 17-04 route double-failure test contradicts its own must-have.**
   `17-04-PLAN.md:26` (must_haves) promises the real handler + `fail_job`-raises chain → 503 + lease retained, but the task at `17-04-PLAN.md:197-200` only monkeypatches `drain_once()` to raise — proving exception→503 mapping, not the real double-failure path + token retention through the HTTP call. *Fix:* add a second route test exercising the real fake-repo chain (handler raises, `fail_job` raises, 503, retained-token asserted), or weaken the must-have. The former is right given round-1's resolution.

3. **LOW — worker-survival test needs a second-iteration handshake [17-01].** `17-01-PLAN.md:194-198` signals only the throwing first call; `thread.is_alive()` can pass without the worker ever resuming polling. Require a second Event / `calls >= 2` after the exception.

4. **LOW — `COMPUTED` mislabeled "terminal" [17-05].** Source classifies COMPUTED as recoverable/in-flight (`app/routes/runs.py:66-69`) and normal processing advances COMPUTED→AWAITING_APPROVAL (`app/pipeline/orchestrator.py:1010-1014`). Not vacuous (it still distinguishes the stubbed success path from ERROR), but relabel it "observable post-handler status set by the stub," not terminal.

5. **LOW — criterion-#4 static cron guard is comment-sensitive [17-03].** `keepalive.yml` has `schedule:` in prose too (`:5-19`); a plain substring scan is comment-sensitive. Strip comment-only lines or use the documented `data.get(True, data.get("on"))` YAML parse.

### Confirmed complete (no further action)
- **Fix #1 production design** — re-raise retains the token (`drain.py:188-191` discards only when `lease_settled`, which stays false), worker loop survives (`worker.py:184-211`), shutdown release is token-fenced, no other production caller. Unit-test reconciliation correct.
- **Fix #3** — stub patches the correct seam (`17-05` ↔ `test_queue_durability.py:1016-1027`); `orchestrator_calls == [run_id]` + status assertion defeats the ERROR-run false positive.
- **MEDIUM bundle** — all three six-function tests, honest hermetic count, PyYAML `on:` avoidance + committed criterion-#4 test, settings-cache teardown, `claimed==sum` invariant, honest catch-all wording.

### My read (orchestrator triage)
The timeout derivation has now been wrong **twice** — that's the "reviews keep hitting one spot → the approach is the bug" signal. Deriving a `curl --max-time` from a hand-estimated job runtime is fragile because the clarification path's real ceiling is the *sum of provider timeouts + cold-start*, which isn't a tidy number. The durable fix is to **hard-bound total job runtime** (every provider/Resend call already carries an explicit timeout — make that the derivation basis) and set curl = cold-start + that bound + real margin. Finding #2 is operational (false-RED cron), not money/correctness — but a cron that cries wolf is exactly what keepalive's `-f` discipline exists to prevent, so it's worth another pass. Findings #2–#5 are all cheap and localized. Recommend a final `--reviews` replan.

### Divergent Views
None — single reviewer.
