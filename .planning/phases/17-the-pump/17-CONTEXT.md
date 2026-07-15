# Phase 17: The Pump - Context

**Gathered:** 2026-07-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Durable *storage* becomes durable *execution*. Phase 16 built the `jobs` table, the
lease/claim protocol, and in-process worker threads — but on Render free, the dyno sleeps
after 15 idle minutes and **only inbound HTTP wakes it**. A job retried with a future
`available_at`, or a run sitting on a cold-started instance with no live worker threads,
would otherwise never fire. This phase closes that hole with an **external pump**.

Three things land, and nothing else:

1. **An authenticated `POST/GET /internal/pump` endpoint** that drains due jobs by looping
   the *same* `drain_once()` the worker threads call (PUMP-01 — one shared implementation,
   never a fork), and returns **real counts** (claimed / done / retried / dead / queue-depth),
   not a bare 200.

2. **`.github/workflows/pump.yml`** — a 30-minute cron that hits the pump AND carries forward
   **both** jobs of the deleted `keepalive.yml`: the wake ping (`/health/ready`, which also
   touches Supabase so the free project stays un-paused) and the `/health/schema` drift check.
   `keepalive.yml` is deleted; `pump.yml` becomes the **only** cron hitting the service.

3. **README documentation** of the cadence, the worst-case recovery-latency bound, the
   750-instance-hour/month duty-cycle math (`awake ≈ 15 ÷ cadence`) that forces 30 minutes,
   and the deliberately best-effort wording (GitHub cron can be delayed and auto-disables
   after 60 quiet days; operator retry is the stated fallback).

**Requirements:** PUMP-01, PUMP-02.

**Locked upstream — not re-litigated here:**
- **30-minute cadence** and the 750-hour budget math (design doc §"The 750-hour math";
  PUMP-02). Half the free-tier budget, ≤30-min recovery bound. This is a cron schedule + an
  env var, not architecture.
- **One shared `drain_once()`** between the pump and the workers (PUMP-01; design §108-110).
  The pump is the **primary** execution trigger, not a redundancy — it must work with **zero
  live worker threads** (success criterion #2).
- **`keepalive.yml` is absorbed, both jobs carried forward** (criterion #4) — deleting it
  without the schema-parity check would silently drop the only monitor that catches a manual
  Supabase edit bypassing `deploy-migrate.yml`.

</domain>

<decisions>
## Implementation Decisions

### Pump authentication (criterion #1 — "authenticated")

- **D-01: Bearer-token shared secret.** The cron sends `Authorization: Bearer $PUMP_TOKEN`;
  the endpoint compares it **constant-time** against a new `PUMP_TOKEN` env var. This mirrors
  the existing secret pattern exactly — a `sync:false` entry in `render.yaml` (like
  `DATABASE_URL`, `WEBHOOK_SIGNING_SECRET`) on the app side, a GitHub Actions repo secret on
  the cron side. Keeps the secret out of the URL, access logs, and Actions step output
  (which a query-string token would not). This is **machine-to-machine internal auth only** —
  distinct from, and not a step toward, dashboard/operator auth, which stays the
  known/accepted out-of-scope gap.

- **D-02: 401 Unauthorized on a bad or missing credential.** Honest and standard; the cron's
  `curl -f` turns the run **RED**, so a misconfigured `PUMP_TOKEN` is loudly visible rather
  than a silent no-op pump. Explicitly NOT 404-to-hide-the-route — that would mask a real cron
  misconfiguration as "route gone" and muddy the RED signal we want.

- **D-03: Fail closed when `PUMP_TOKEN` is unset/empty.** A deploy that forgot the secret must
  **reject every pump call** (401 / "pump not configured"), never fall open. There is **no dev
  bypass flag** (unlike `ALLOW_UNSIGNED_FIXTURES` for the webhook): the test suite calls
  `drain_once()` directly (D-06 from Phase 16), so the HTTP endpoint needs no unauthenticated
  local path. Fail-closed is the money-system default for a job-draining trigger.

### The drain loop and its counts (criterion #1 — "returns real counts, not just a bare 200")

- **D-04: Enrich the shared `drain_once()` to surface each job's terminal outcome.** Today it
  returns a bare `bool` (claimed a job, or empty). Change it to return a small outcome value —
  `empty | done | retried | dead | fenced` — so the pump can aggregate **exact** per-invocation
  counts of what *this pump run actually did*. Rejected alternatives: a snapshot
  `SELECT state, count(*) GROUP BY state` (counts would reflect queue *composition*, not this
  pump's work, and skew under any concurrent worker); and a claimed+depth-only pump (would
  under-deliver criterion #1's explicit five-count list).
  - **Load-bearing integration constraint:** the worker loop at `app/queue/worker.py:198`
    (`if drain.drain_once():`) relies on the return's **truthiness** to decide keep-draining
    vs. sleep. The new `empty` outcome MUST remain falsy and every claimed-outcome truthy, so
    the worker keeps working **unchanged** — it simply ignores the richer value.
  - **The `retried` vs `dead` distinction is decided inside `repo.fail_job`**, not in
    `drain_once` today (`fail_job` applies the `MAX_ATTEMPTS` cap → `dead` state). So surfacing
    the outcome truthfully requires the terminal state to bubble up through the
    `fail_job`/`complete_job` return path (currently bool). This is the real cost of D-04 and
    where the planner should focus — see `app/queue/drain.py` (the `complete_job`/`fail_job`
    call sites) and `app/db/repo/jobs.py`.

- **D-05: Drain-to-empty, bounded by a safety cap.** The pump loops `drain_once()` until the
  queue reports empty, but stops at a **max-jobs and/or wall-clock cap** so one HTTP request
  can never run unbounded (poison-loop or backlog-flood guard). At ~1 payroll email/client/week
  the cap is never hit in practice; it exists so a pathological state can't pin the request.
  Rejected: single-`drain_once()`-per-hit (a 30-min cadence would clear one job per 30 min — a
  backlog would take hours); unbounded drain-to-empty (a fast-re-eligible job could run the
  request long). **Pick the cap values from the pipeline's measured runtime and document the
  derivation**, the same way `LEASE_SECONDS`/`QUEUE_POLL_SECONDS` were derived (Phase 16 D-03).

### The pump workflow (criterion #4 — the keepalive fold-in)

- **D-06: One job, three `curl -f` steps, 30-minute cron.** `pump.yml` has a single job with:
  (1) `curl -f` the authenticated `/internal/pump` (Bearer token from the GitHub secret — wakes
  Render + drains); (2) `curl -f $RENDER_URL/health/ready` (wake + Supabase touch, RED on fail);
  (3) `curl -f $RENDER_URL/health/schema` (drift, RED on 503). Every check runs every 30 min.
  This carries `keepalive.yml`'s exact step style and RED-on-non-2xx (`-f`) discipline forward,
  and adds the pump. `/health/ready` is **kept even though the pump already hits the DB** —
  criterion #4 explicitly requires both keepalive jobs, including the readiness wake, to carry
  over. Splitting into two workflows is rejected (violates "pump.yml is the only cron").

- **D-07: Keep a `workflow_dispatch` trigger.** GitHub auto-disables scheduled workflows after
  60 quiet days — the exact reality PUMP-02's best-effort wording calls out. `workflow_dispatch`
  gives one-click re-enable from the Actions tab (carried forward verbatim from
  `keepalive.yml`'s rationale) instead of a trip into repo settings.

- **D-08: `keepalive.yml` is deleted in this phase**, its `RENDER_URL` secret reused, and a new
  `PUMP_TOKEN` GitHub secret + `render.yaml` `sync:false` entry added. `deploy-migrate.yml`,
  `ci.yml`, `concurrency-proof.yml`, and `eval.yml` are untouched.

### Failure semantics / scope fence against Phase 21 (OPS-01)

- **D-09: 200 + counts even when jobs dead-letter or retry.** A dead-lettered or backed-off job
  is **normal queue operation**, not a pump failure — `drain_once()` already catches every
  job-level exception internally and routes it to the fenced `fail_job` (dead-letter/backoff)
  path, so those never bubble to the pump. The pump returns **200 with the count JSON** whenever
  it ran. The `curl -f` therefore does **not** go RED on business outcomes. The
  "job success ≈100% while `payroll_runs.status='error' > 0`" **alarm**, and the ops view that
  surfaces queue depth / oldest-pending age / dead-letter list, are **OPS-01, Phase 21** —
  deliberately NOT pulled forward here.

- **D-10: 5xx (503/500) only on auth or a genuine infra outage.** If the DB is unreachable when
  the pump is hit (pool exhausted, Supabase down) so it can't claim or can't read queue depth,
  the pump returns 5xx and the cron goes **RED** — same posture as `/health/ready` and
  `/health/schema`. Rejected: always-200-with-an-error-field, which would keep the cron GREEN
  during a real outage — the exact silent-failure mode keepalive's `-f` design exists to prevent.

### Claude's Discretion
- The exact `PUMP_TOKEN` env var name and the response JSON key names/shape (e.g.
  `{"claimed": N, "done": N, "retried": N, "dead": N, "queue_depth": N}`) — pick clean,
  self-describing names.
- Whether `/internal/pump` is `POST` or `GET`. `GET` is simplest for a `curl` cron and this is
  an idempotent drain (SKIP LOCKED makes concurrent/repeat hits safe); `POST` is more
  semantically honest for a state-changing action. Either is defensible — pick one and note it.
- The precise max-jobs / wall-clock cap values for D-05, derived from measured pipeline runtime
  and documented at the call site.
- Whether queue-depth is read in the same short transaction as the final claim or as a separate
  cheap `SELECT count(*)` — implementation detail.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### The approved design (authoritative — cadence/budget math is already decided here)
- `docs/superpowers/specs/2026-07-13-durable-execution-design.md` — **§"The constraint that
  shapes everything: durable storage ≠ durable execution"** (lines 80-110: why the pump exists,
  the 750-hour duty-cycle table, the 30-minute decision, and "the pump is the **primary**
  trigger… shares **one** `drain_once()`"). **§"Forced order"** (line 200-206: the pump is
  build-order step 3, before the webhook cutover).
- `.planning/REQUIREMENTS.md` — **PUMP-01** and **PUMP-02** verbatim (lines 48-58), plus
  **"Out of Scope"** (operator authentication is a different axis — D-01's internal auth is not
  it) and **"Accepted residual risk"**.
- `.planning/ROADMAP.md` § "Phase 17: The Pump" (lines 97-110) — the **4 success criteria** this
  phase is graded against. Note criterion #4's emphasis: **both** keepalive jobs carry over.

### Phase 16 foundation this phase builds directly on (read before planning)
- `.planning/phases/16-queue-substrate-unblocked-webhook/16-CONTEXT.md` — the queue substrate
  decisions. Especially **D-06** (workers OFF under test; tests call `drain_once()` directly —
  this is why the pump endpoint needs no dev auth bypass) and **D-14** (the narrow `queueproof`
  CI marker — any new pump durability test marks `queueproof`, not whole-suite `-m integration`).

### Code seams this phase modifies (all confirmed by direct read)
- `app/queue/drain.py:117` — **`drain_once() -> bool`**, the shared single-drain step (D-04
  changes its return type). Its `complete_job` / `fail_job` call sites are where the terminal
  outcome must bubble up. Note the module's own docstring: it lives standalone precisely so a
  "process-external pump" can run one job without importing thread machinery.
- `app/queue/worker.py:198` — **`if drain.drain_once():`** — the truthiness dependency D-04 must
  preserve (`empty` stays falsy).
- `app/db/repo/jobs.py` + `app/db/repo/__init__.py` — `fail_job`/`complete_job` (return bool
  today; D-04 may need the resulting `dead`/`retried` state surfaced) and the facade re-exports.
  A queue-depth read (`SELECT count(*) FROM jobs WHERE state='pending'…`) lands here.
- `app/routes/health.py` — the router pattern to imitate for a new `app/routes/` pump route
  (or fold into an existing router); shows the `/health/ready` (SELECT-touch) and
  `/health/schema` (503-on-drift) contracts the workflow curls.
- `app/main.py` — 16 lines; `app.include_router(...)` is where a new pump router is wired.
- `app/config.py` — `Settings` (pydantic-settings). Add `pump_token: str = ""` following the
  `resend_api_key`/`webhook_signing_secret` empty-default-secret convention. The `# Durable job
  queue` block (`worker_count`/`lease_seconds`/`queue_poll_seconds`) is the section to extend.
- `.github/workflows/keepalive.yml` — **deleted** this phase; its structure (validate
  `RENDER_URL` → `curl -f /health/ready` → `curl -f /health/schema`, the `-f` and
  `workflow_dispatch` rationale in its comments) is the template for `pump.yml`.
- `render.yaml` — add `PUMP_TOKEN` as a `sync:false` secret entry (lines 20-34 pattern).

### CI / test landmines
- `.github/workflows/concurrency-proof.yml:89` — the **only** workflow with a real Postgres,
  selects test files **by name**. Any live-DB pump proof lands here or never runs (per Phase 16
  D-14, mark it `queueproof` and add the narrow second gate — do NOT widen `-m integration`).
- A new `app/routes/` pump route is auto-scanned by `tests/test_bound01_private_imports.py`
  (`SCAN_ROOTS = ["app", …]`) — no cross-module `_private` refs.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`drain_once()` (`app/queue/drain.py`)** — already a standalone, thread-machinery-free single
  drain step built *explicitly* for "a process-external pump that wants to run exactly one job."
  The pump is the caller its docstring anticipated. The DRY seam is already in place; D-04 only
  enriches its return.
- **`app/routes/health.py`** — the exact router + JSONResponse + disclosure-discipline pattern a
  pump route should copy, and the source of the two health contracts `pump.yml` curls.
- **`keepalive.yml`** — a near-complete template: its `-f`-for-RED discipline, the `RENDER_URL`
  fail-fast validation step, the `/health/ready` and `/health/schema` steps, and the
  `workflow_dispatch` rationale all carry forward almost verbatim.
- **`app/config.py` empty-default-secret convention** (`resend_api_key`, `webhook_signing_secret`)
  — `pump_token: str = ""` slots straight in; the fail-closed check (D-03) lives in the route,
  not the settings field (matching how `ALLOW_UNSIGNED_FIXTURES` gates behavior, not config).

### Established Patterns
- **`sync:false` secret → env var → GitHub Actions secret** — the established three-point secret
  topology (`DATABASE_URL`, `WEBHOOK_SIGNING_SECRET`). `PUMP_TOKEN` follows it exactly.
- **Constant-time secret comparison** — the webhook HMAC path already establishes the
  don't-leak-via-timing posture; reuse it for the Bearer compare.
- **`-f`-on-curl = RED-on-failure** — the keepalive design principle (swallowing a failure makes
  a keep-alive silently useless). D-09/D-10 are a direct application: RED on infra/auth, GREEN on
  normal business outcomes.

### Integration Points
- `app/main.py` gains one `include_router` for the pump route (or the route joins an existing
  router).
- `app/config.py::Settings` gains `pump_token`.
- `app/queue/drain.py` `drain_once()` return type changes (ripples to `worker.py`'s truthiness
  check and the pump's aggregation loop; possibly to `repo.fail_job`/`complete_job` returns).
- `.github/workflows/` — `keepalive.yml` deleted, `pump.yml` added.
- `render.yaml` — `PUMP_TOKEN` secret added.
- `README.md` — the cadence/750-hour/best-effort documentation block (PUMP-02, criterion #3).

</code_context>

<specifics>
## Specific Ideas

- **The pump is the guarantee, not the workers.** Success criterion #2 is the thesis of the
  phase: a future-`available_at` job on a just-cold-started instance with **no worker threads
  yet** must still execute when cron fires. The proof must construct exactly that state (no live
  workers, a due job) and show the pump drains it — not lean on in-process workers that happen to
  be up. This is the phase's anti-vacuous-proof anchor.
- **Counts must be truthful, not decorative** — "returns real counts, not just a bare 200" is
  the literal criterion. D-04 exists so the five counts describe what the pump actually did, not
  a queue snapshot that a concurrent worker could skew.
- **The keepalive fold-in is a subtraction that must not lose a monitor.** The trap criterion #4
  guards: deleting `keepalive.yml` and carrying only the wake ping would silently drop the
  `/health/schema` drift check — the only monitor that catches a manual Supabase edit bypassing
  `deploy-migrate.yml`. Both jobs carry over.

</specifics>

<deferred>
## Deferred Ideas

- **The ops view + the swallowing-bug alarm** — queue depth / oldest-pending age / attempts
  distribution / dead-letter list on a page, and the "job success ≈100% while `status='error'
  > 0`" alarm. This is **OPS-01, Phase 21**. D-09 deliberately keeps it out; the pump *reports*
  counts but does not alarm on them.
- **The `ok`/`retryable`/`terminal` failure contract + real backoff classification** —
  **FAIL-01/02, Phase 18.** In Phase 17 the orchestrator still swallows stage failures and
  `attempts` only advances via crash-reclaim (Phase 16 scoping caveat in `app/config.py`), so
  the pump's `retried`/`dead` counts today reflect only crash-reclaim cycles, not classified
  retries. Not a regression; the richer classification lands in Phase 18.
- **Deleting `sweep_stranded_runs` / the dashboard-page-load-as-cron block** — **FAIL-03,
  Phase 18.** The pump and the sweep both being recovery mechanisms is the Phase 18 hazard; this
  phase adds the pump but does not yet remove the sweep.
- **Per-invocation adaptive cadence / dynamic cap tuning** — out of scope; the cadence is a fixed
  30-min cron + env var by design, and the drain cap is a static documented constant.

### Reviewed Todos (not folded)
None — no pending todos matched this phase's scope.

</deferred>

---

*Phase: 17-The Pump*
*Context gathered: 2026-07-14*
