# Phase 17: The Pump - Research

**Researched:** 2026-07-15
**Domain:** FastAPI internal endpoint auth, Postgres job-queue drain aggregation, GitHub Actions cron, Render free-tier duty-cycle math
**Confidence:** HIGH (every code claim below is a direct read of live source at the commit this research was done against; the two external numeric claims — Render's 750h and GitHub's 60-day rule — are web-verified and cited)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Pump authentication (criterion #1 — "authenticated")**
- D-01: Bearer-token shared secret. Cron sends `Authorization: Bearer $PUMP_TOKEN`; endpoint compares constant-time against a new `PUMP_TOKEN` env var. `sync:false` in `render.yaml` (like `DATABASE_URL`, `WEBHOOK_SIGNING_SECRET`) + a GitHub Actions repo secret. Machine-to-machine internal auth only — not a step toward operator/dashboard auth.
- D-02: 401 on bad/missing credential. Not 404-to-hide-the-route.
- D-03: Fail closed when `PUMP_TOKEN` is unset/empty — reject every call, never fall open. No dev bypass flag; the test suite calls `drain_once()` directly (Phase 16 D-06), so the HTTP endpoint needs no unauthenticated local path.

**The drain loop and its counts (criterion #1 — "returns real counts, not just a bare 200")**
- D-04: Enrich the shared `drain_once()` to surface each job's terminal outcome — `empty | done | retried | dead | fenced` — so the pump can aggregate exact per-invocation counts of what *this pump run actually did*. Rejected: a snapshot `GROUP BY state` (reflects composition, not this run's work); a claimed+depth-only pump (under-delivers the five-count list). **Load-bearing:** `worker.py:198`'s `if drain.drain_once():` relies on truthiness — `empty` MUST stay falsy, every claimed outcome truthy. The `retried` vs `dead` distinction is decided inside `repo.fail_job` (the `MAX_ATTEMPTS` cap), not in `drain_once` today.
- D-05: Drain-to-empty, bounded by a max-jobs and/or wall-clock safety cap. Pick cap values from the pipeline's measured runtime and document the derivation, the same way `LEASE_SECONDS`/`QUEUE_POLL_SECONDS` were derived (Phase 16 D-03).

**The pump workflow (criterion #4 — the keepalive fold-in)**
- D-06: One job, three `curl -f` steps, 30-minute cron: (1) authenticated `/internal/pump`, (2) `curl -f $RENDER_URL/health/ready`, (3) `curl -f $RENDER_URL/health/schema`. `/health/ready` is kept even though the pump already hits the DB — criterion #4 requires both keepalive jobs to carry over. No splitting into two workflows.
- D-07: Keep `workflow_dispatch` (GitHub auto-disables scheduled workflows after 60 quiet days).
- D-08: `keepalive.yml` deleted this phase, its `RENDER_URL` secret reused, new `PUMP_TOKEN` GitHub secret + `render.yaml` `sync:false` entry added. `deploy-migrate.yml`, `ci.yml`, `concurrency-proof.yml`, `eval.yml` untouched.

**Failure semantics / scope fence against Phase 21 (OPS-01)**
- D-09: 200 + counts even when jobs dead-letter or retry — that is normal queue operation, not a pump failure. `drain_once()` already catches every job-level exception internally. The ops alarm (`job success ≈100% while status='error' > 0`) is OPS-01, Phase 21 — not pulled forward.
- D-10: 5xx (503/500) only on auth or a genuine infra outage (DB unreachable so the pump can't claim or can't read queue depth) — same posture as `/health/ready`/`/health/schema`. Rejected: always-200-with-an-error-field (keeps cron GREEN during a real outage).

### Claude's Discretion
- The exact `PUMP_TOKEN` env var name and the response JSON key names/shape (e.g. `{"claimed": N, "done": N, "retried": N, "dead": N, "queue_depth": N}`).
- `GET` vs `POST` for `/internal/pump`. Either defensible — pick one and note it.
- The precise max-jobs / wall-clock cap values for D-05, derived from measured pipeline runtime.
- Whether queue-depth is read in the same short transaction as the final claim or as a separate cheap `SELECT count(*)`.

### Deferred Ideas (OUT OF SCOPE)
- The ops view + the swallowing-bug alarm — **OPS-01, Phase 21**.
- The `ok`/`retryable`/`terminal` failure contract + real backoff classification — **FAIL-01/02, Phase 18**. Today the pump's `retried`/`dead` counts reflect only crash-reclaim cycles, not classified retries.
- Deleting `sweep_stranded_runs` / the dashboard-page-load-as-cron block — **FAIL-03, Phase 18**.
- Per-invocation adaptive cadence / dynamic cap tuning — out of scope; fixed 30-min cron + static cap constant.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PUMP-01 | Authenticated pump endpoint claims and drains due jobs, sharing ONE `drain_once()` with the worker threads; primary trigger, not redundancy | §Architecture Patterns (route design), §Code Examples (enriched `drain_once`, pump route), §Validation Architecture (the zero-worker durability proof) |
| PUMP-02 | Cron drives the pump every 30 minutes; README documents the duty-cycle math, the 750h ceiling, and the best-effort wording | §"The 750-hour math, re-verified", §Code Examples (`pump.yml`), §Common Pitfalls (curl `--max-time` mismatch) |
</phase_requirements>

## Summary

Phase 17 is smaller than CONTEXT.md's canonical-refs section implies, and the plan should say so explicitly. The two highest-leverage findings from direct source reads: (1) `repo.fail_job` **already returns `JobState | None`**, not the `bool` CONTEXT.md describes — the "retried vs dead" state is already sitting in a local variable inside `drain_once()`, discarded. Enriching `drain_once()`'s return is therefore a matter of *capturing* an existing value, not threading a new one through `fail_job`/`complete_job`'s signatures. (2) The `queueproof` marker + its second CI step in `concurrency-proof.yml` (Phase 16 D-14) is **already fully wired** — a new durability test needs only `pytestmark = [pytest.mark.integration, pytest.mark.queueproof]` (or an addition to an existing `pytestmark` list) and zero workflow edits.

The real cost is elsewhere: **~15 existing test assertions use `assert drain.drain_once() is True` / `is False`** (identity checks against the bool singletons) across 6 files. Changing the return type away from `bool` breaks every one of them regardless of how truthy/falsy the new type is designed to be — `is True` never matches a non-`bool` object. This is the single biggest mechanical cost of D-04 and must be scoped into the plan's task list explicitly, file by file.

Second finding worth flagging: CONTEXT.md's canonical-refs ask the planner to "confirm the existing constant-time-compare seam (the webhook HMAC path) to reuse." **No such reusable seam exists.** The webhook's signature check delegates entirely to `resend.Webhooks.verify()` (the svix SDK) — there is no in-repo `hmac.compare_digest`/`secrets.compare_digest` helper anywhere in `app/`. The Bearer-token compare must be written from scratch using Python's stdlib (`hmac.compare_digest`), which is a two-line addition, not a "reuse."

Third: the pump's own drain loop must be bounded by both a job-count cap and a wall-clock cap (D-05), and the wall-clock cap interacts with GitHub Actions' `curl --max-time`, which `keepalive.yml` already sets to `90` for its two health checks. **CORRECTION (17-REVIEWS findings #1 & #2 — supersedes this doc's original 210s/360s framing throughout):** the 210s figure is the max inter-write STALL GAP (a stall threshold in `runs.py:37-72`), **NOT** a total single-job runtime — do not size the curl timeout from it. The pump step's curl budget is `--max-time 420`, an HONEST NOMINAL accounting = Render cold-start ≤60s + the pump's 120s between-jobs cap + one worst-case job's ≈240s external-call allowance (summed provider timeouts), with deterministic/DB/overhead ON TOP — so 60+120+240 = 420 already, **NO "~60s headroom" is claimed** and a rare worst-case-clarification request can overrun 420. That is safe because CORRECTNESS rests on lease-reclaim (`lease_seconds=900`), not the curl budget: a job with attempts remaining is idempotently re-run next cadence (SKIP LOCKED). 420 is a NOMINAL budget, PROVISIONAL until the live smoke confirms Render's undocumented server-side ceiling (A1), not a proven containment bound. Copying `--max-time 90` onto the pump step would false-RED a pump that is still correctly draining a slow job — size the pump step well above the two health-check steps', not uniformly across all three `pump.yml` steps.

**Primary recommendation:** Ship D-04 as a pure capture-and-map change inside `drain_once()` (no signature changes to `complete_job`/`fail_job`), define the new outcome type as a small `StrEnum` with an overridden `__bool__` living in `app/queue/drain.py` (not `app/models/job.py` — it mirrors nothing in SQL, unlike `JobKind`/`JobState`), rewrite the ~15 `is True`/`is False` assertions to assert the *specific* expected outcome (free proof-strengthening, not just mechanical repair), write the pump route as a plain sync `def` (not `async def`, matching the health-route convention and the codebase's established "blocking work goes off the loop" discipline), and size the pump-step `curl --max-time` independently of the two health-check steps.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Cron scheduling / trigger | External (GitHub Actions) | — | Render free has no background-worker or internal-timer primitive; only inbound HTTP wakes the dyno. |
| Pump authentication | API / Backend (route) | — | Machine-to-machine Bearer check belongs at the route boundary, mirroring the webhook's HMAC-before-parse ordering. |
| Drain loop + aggregation | API / Backend (`app/queue/drain.py`, called from the route) | — | The pump route is a thin caller; the actual claim/dispatch/complete/fail logic must stay identical to what the worker threads call — one shared function, per PUMP-01's "never a fork." |
| Terminal-outcome classification (retried vs dead) | Database / Storage (`repo.fail_job`'s `MAX_ATTEMPTS` CASE) | API / Backend (`drain_once()` reads the already-returned value) | The state transition is decided by the SQL `CASE`; `drain_once()` only needs to observe what `fail_job` already tells it. |
| Queue depth read | Database / Storage | API / Backend (new repo function) | A point-in-time `count(*)`, not part of the claim transaction — Claude's Discretion resolves this as a separate cheap `SELECT`. |
| Duty-cycle math / cadence documentation | Docs (README) | — | Pure arithmetic + a cited dated source; no code path owns it. |
| Schema/readiness drift monitoring | API / Backend (`/health/ready`, `/health/schema`, pre-existing) | External (GitHub Actions curl) | Unchanged this phase — only the workflow file that invokes them moves. |

## Standard Stack

### Core

No new runtime dependencies. Everything Phase 17 needs is already installed:

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `hmac` (stdlib) | 3.12 stdlib | Constant-time Bearer-token compare | `hmac.compare_digest(a, b)` is the canonical Python primitive for this exact problem — timing-safe, no dependency, already the mechanism the codebase's own HMAC path relies on one layer down (inside `resend.Webhooks.verify`). [VERIFIED: direct source read — no in-repo helper exists; stdlib is the only candidate] |
| `fastapi` | already pinned `0.138.0` (project CLAUDE.md) | New `/internal/pump` route | Same router pattern as `app/routes/health.py`. |
| `pydantic-settings` | already pinned `2.14.2` | New `pump_token: str = ""` field | Follows the existing empty-default-secret convention (`resend_api_key`, `webhook_signing_secret`). |

### Package Legitimacy Audit

**Not applicable — this phase installs zero new external packages.** `hmac` is Python stdlib; every other touch point (FastAPI route, pydantic-settings field, psycopg SQL) reuses already-installed, already-audited dependencies from Phase 16. No `uv add` of any kind is required for this phase.

## Architecture Patterns

### System Architecture Diagram

```
                    GitHub Actions cron (*/30 * * * *)  +  workflow_dispatch
                                    │
                                    │  curl -f -H "Authorization: Bearer $PUMP_TOKEN"
                                    ▼
                     GET/POST /internal/pump  (app/routes/pump.py, sync def)
                                    │
                        ┌───────────┴────────────┐
                        │ 1. Bearer check          │──fail──▶ 401 (bad/missing/unset token)
                        │    hmac.compare_digest    │
                        └───────────┬────────────┘
                                    │ ok
                                    ▼
                 loop: while claimed < MAX_JOBS and elapsed < MAX_WALL_CLOCK:
                                    │
                                    ▼
                     drain.drain_once()  ◀── SAME function the 2 worker
                                    │           threads call from worker.py:198
                     ┌──────────────┼───────────────────┐
                     │              │                    │
              repo.claim_job()  (SKIP LOCKED,       returns DrainOutcome
              fences via         reclaim expired          (EMPTY/DONE/
              lease_token)       leases)                  RETRIED/DEAD/
                     │                                    FENCED)
                     ▼
          dispatch.handle(job) → app/queue/handlers/pipeline.py
                     │
        ┌────────────┴─────────────┐
        │ success                   │ raises (rare: import error,
        ▼                           │ record_run_error itself failing)
  repo.complete_job()               ▼
  (fenced on lease_token)     repo.fail_job()  → JobState.DEAD or
        │                     JobState.PENDING (backoff), or None (fenced)
        ▼                           │
   DONE or FENCED             DEAD/RETRIED or FENCED
                                    │
                                    ▼
                     aggregate counts (claimed/done/retried/dead/fenced)
                                    │
                     repo.count_open_jobs()  ── separate cheap SELECT
                                    │
                                    ▼
                     JSON 200 {claimed, done, retried, dead, fenced, queue_depth}
                     (or 5xx only on genuine infra failure — D-10)

  ── in parallel, unaffected by this phase ──
  FastAPI lifespan (app/queue/worker.py) → N daemon threads → same drain.drain_once()
  wake.py Event (in-process signal) → instant retrigger-latency path
```

### Recommended Project Structure

```
app/
├── routes/
│   ├── health.py          # unchanged — /health/live, /health/ready, /health/schema
│   └── pump.py            # NEW — GET/POST /internal/pump; thin route, no business logic
├── queue/
│   ├── drain.py           # MODIFIED — drain_once() -> DrainOutcome (was bool); DrainOutcome defined here
│   ├── worker.py          # UNCHANGED — worker.py:198's `if drain.drain_once():` relies on truthiness only
│   └── dispatch.py        # unchanged
├── db/repo/
│   └── jobs.py            # MODIFIED — +1 function (count_open_jobs or similar); docstring's "six functions" claim becomes wrong and must be updated to seven
├── config.py               # MODIFIED — + pump_token: str = ""
└── main.py                  # MODIFIED — + app.include_router(pump.router)

.github/workflows/
├── keepalive.yml           # DELETED
└── pump.yml                # NEW

render.yaml                 # MODIFIED — + PUMP_TOKEN sync:false entry
README.md                   # MODIFIED — cadence/750h/best-effort doc block
```

### Pattern 1: Capture-don't-thread — enriching `drain_once()`'s return

**What:** `complete_job` already returns `bool`; `fail_job` already returns `JobState | None`. Both values are computed inside `drain_once()` today and discarded (the function returns a bare `True` regardless of which branch ran). D-04's enrichment needs **zero changes** to `repo.complete_job`'s or `repo.fail_job`'s signatures — only `drain_once()` itself needs to hold onto what they already tell it.

**When to use:** Whenever a locked decision's stated cost ("surfacing the outcome truthfully requires the terminal state to bubble up through the fail_job/complete_job return path") doesn't match what a direct read of the current function signatures shows. Always re-verify the described cost against live source before scoping a task around it — CONTEXT.md was written same-day as Phase 16 merged, and it undersold code that was already ahead of its own description.

**Example (the smallest correct diff to `app/queue/drain.py:117-192`):**

```python
# Source: direct read of app/queue/drain.py + app/db/repo/jobs.py, this session.
# DrainOutcome lives HERE, not in app/models/job.py — it mirrors no SQL column
# (unlike JobKind/JobState, which app/models/job.py's own docstring says are
# "CANONICAL; app/db/schema.sql's jobs.kind and jobs.state CHECK constraints
# mirror them verbatim"). DrainOutcome is a pure in-process per-call outcome,
# never persisted, and reuses "done"/"dead" as string values coincidentally —
# it is a DIFFERENT vocabulary layer and must not be added to
# tests/test_job_kind_drift.py's JobKind/JobState collision guard.
class DrainOutcome(enum.StrEnum):
    EMPTY = "empty"      # no claimable job — worker.py:198 must treat this as falsy
    DONE = "done"        # dispatched, complete_job succeeded
    RETRIED = "retried"  # dispatch raised, fail_job moved the row back to pending w/ backoff
    DEAD = "dead"        # dispatch raised, fail_job hit MAX_ATTEMPTS and moved to dead
    FENCED = "fenced"    # complete_job/fail_job returned False/None — lease stolen mid-run

    def __bool__(self) -> bool:
        return self is not DrainOutcome.EMPTY


def drain_once() -> DrainOutcome:
    ...  # claim + _held_tokens bookkeeping UNCHANGED
    if job is None:
        return DrainOutcome.EMPTY

    lease_settled = False
    # NOTE (17-REVIEWS finding #1 — supersedes an earlier draft that seeded
    # `outcome = DrainOutcome.FENCED` and let the double-failure fall through as FENCED):
    # do NOT seed a FENCED catch-all. Set `outcome` EXPLICITLY on each SETTLED branch,
    # and RE-RAISE the double-failure (fail_job's own write failed) so the pump surfaces
    # 503 and the worker loop (worker.py:203) survives. Mapping it to FENCED would let a
    # real DB outage return HTTP 200 (violates D-10).
    try:
        dispatch.handle(job)
        completed = repo.complete_job(job.id, job.lease_token)
        lease_settled = True
        outcome = DrainOutcome.DONE if completed else DrainOutcome.FENCED
    except Exception as exc:  # noqa: BLE001
        try:
            state = repo.fail_job(
                job.id, job.lease_token, error=exc,
                backoff_seconds=_backoff_seconds(job.attempts),
            )
            lease_settled = True
            if state is None:
                outcome = DrainOutcome.FENCED
            else:
                outcome = DrainOutcome.DEAD if state is JobState.DEAD else DrainOutcome.RETRIED
        except Exception:  # noqa: BLE001 — the failure write ITSELF failed (DB outage)
            logger.exception(...)  # unchanged message; lease_settled stays False
            raise                  # RE-RAISE: infra failure → pump 503; worker.py:203 survives
    finally:
        if lease_settled:
            with _held_tokens_lock:
                _held_tokens.discard(job.lease_token)
    return outcome  # reached only when no exception propagated; mypy sees `outcome` bound
```

`worker.py:198`'s `if drain.drain_once():` needs **zero changes** — `DrainOutcome.__bool__` preserves the exact truthiness contract. The double-failure branch RE-RAISES rather than returning, so `return outcome` is reached only on a settled branch (`outcome` is always bound there).

### Pattern 2: The pump route — thin, sync, bounded

**What:** A plain `def` (not `async def`) route, matching `app/routes/health.py`'s convention. Sync is correct here, not merely consistent: FastAPI runs a sync `def` route in the AnyIO threadpool, keeping the event loop free while the drain loop performs blocking psycopg calls and (per job) potentially a 45s+ LLM call inside `dispatch.handle`.

**When to use:** Any new route whose body performs blocking I/O and has no natural `await` point — the same reasoning QUEUE-01 already applied to the webhook's ingest path.

```python
# Source: modeled directly on app/routes/health.py's existing router pattern.
import hmac
import logging
import time

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import repo
from app.queue.drain import DrainOutcome, drain_once

logger = logging.getLogger("payroll_agent.queue")
router = APIRouter()

_MAX_JOBS_PER_PUMP = 20        # see README's duty-cycle section for derivation
_MAX_WALL_CLOCK_SECONDS = 120  # checked BETWEEN drain_once() calls, never mid-call


def _authorized(request: Request) -> bool:
    token = get_settings().pump_token
    if not token:  # D-03: fail closed on an unset/empty secret
        return False
    expected = f"Bearer {token}".encode()
    got = request.headers.get("authorization", "").encode()
    return hmac.compare_digest(got, expected)


@router.get("/internal/pump")
def pump(request: Request) -> JSONResponse:
    if not _authorized(request):
        raise HTTPException(status_code=401, detail="unauthorized")

    counts = dict.fromkeys(("done", "retried", "dead", "fenced"), 0)
    claimed = 0
    deadline = time.monotonic() + _MAX_WALL_CLOCK_SECONDS
    try:
        while claimed < _MAX_JOBS_PER_PUMP and time.monotonic() < deadline:
            outcome = drain_once()
            if outcome is DrainOutcome.EMPTY:
                break
            claimed += 1
            counts[outcome.value] += 1
        queue_depth = repo.count_open_jobs()
    except Exception as exc:  # noqa: BLE001 — D-10: only a genuine infra failure reaches here
        logger.error("pump: infra failure mid-drain: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="pump unavailable") from exc

    return JSONResponse({"claimed": claimed, **counts, "queue_depth": queue_depth})
```

### Anti-Patterns to Avoid
- **Blindly copying `keepalive.yml`'s `curl -f --max-time 90` onto the pump step.** A single pump request's nominal worst case is ≈420s (cold-start ≤60 + 120s between-jobs cap + ≈240s external-call allowance + overhead — NOT the 210s stall gap; see the CORRECTION in Summary and Pitfall 2) — a 90s client timeout would false-RED a pump that is still correctly working. Use `--max-time 420` (nominal, provisional-until-live-smoke); correctness rests on lease-reclaim, not the curl budget.
- **A second, forked drain implementation for the pump.** PUMP-01 is explicit: "sharing ONE `drain_once()` implementation... never a fork." The route must call the exact same function the worker threads call, not a route-local copy of the claim/dispatch/complete/fail sequence.
- **Widening `-m integration` collection to bring in the new durability test.** Already superseded by Phase 16 D-14 — use `@pytest.mark.queueproof` (registered in `pyproject.toml`, already collected by `concurrency-proof.yml`'s second step). No workflow edits needed.
- **A `getattr(repo, ...)` or re-bound-name path to `repo.count_open_jobs`.** Phase 16's D-18 J-1 AST guard rejects files under `app/queue/` that defeat static resolution of repo calls — the pump route itself is under `app/routes/`, not `app/queue/`, so it is outside that specific guard's scope, but any new code added under `app/queue/drain.py` must keep calling `repo.<name>(...)` by plain attribute access.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Constant-time string compare | A manual byte-by-byte loop, or a naive `==` | `hmac.compare_digest(bytes, bytes)` | Stdlib, timing-attack-resistant by construction, zero new dependency. `secrets.compare_digest` is the same function re-exported — either name works; `hmac` is used here since the codebase's only other HMAC-adjacent code already imports the `resend`/svix path, keeping the vocabulary aligned. |
| Bounding a loop against a poison/backlog state | An ad-hoc `while True` with no cap | The two-cap pattern already established for `LEASE_SECONDS`/`QUEUE_POLL_SECONDS` — a documented constant with a derivation comment at the definition site | Consistent with the project's own convention (`app/config.py`'s existing derivation comments) rather than inventing a new documentation style for this one cap. |
| Queue-depth counting | A `GROUP BY state` aggregate reused as "what this pump did" | A plain `SELECT count(*) FROM jobs WHERE state IN ('pending','leased')`, called once, separately from the aggregated per-invocation counts | D-04 explicitly rejects reusing a composition snapshot as the per-invocation counts; queue depth is a *different*, legitimately-composition-based number and should stay a separate, clearly-named field. |

**Key insight:** Every mechanism this phase needs (constant-time compare, a bounded drain loop, a point-in-time count) already has an idiomatic stdlib or in-repo precedent. There is no library gap here — the entire phase is glue plus one enum.

## Common Pitfalls

### Pitfall 1: `is True`/`is False` identity checks break on ANY non-bool return, regardless of truthiness design
**What goes wrong:** Approximately 15 existing assertions across 6 test files do `assert drain.drain_once() is True` or `is False`. `is True` is an identity check against the literal `bool` singleton — it will fail for `DrainOutcome.DONE` (or any other object) even though `bool(DrainOutcome.DONE) == True`.
**Why it happens:** The tests were written when `drain_once()` returned a bare `bool`, and `is True`/`is False` was a defensible, slightly-too-strict style choice at the time.
**How to avoid:** Enumerate every site before starting D-04 and rewrite each to the *specific* expected outcome (stronger than the truthy/falsy check it replaces) rather than a generic `!= DrainOutcome.EMPTY`. Confirmed sites, this session:
- `tests/test_alias_and_run_column_regressions.py:506,561`
- `tests/test_hitl.py:199,225,251`
- `tests/test_queue_drain.py:237,284,308,333,359,404,833` (7 sites — this is the module that owns the "five behaviors" tests and needs the most rewriting, including turning `test_drain_once_empty_queue_returns_false...` and `test_drain_once_handler_raises_calls_fail_job_not_complete_job` into outcome-specific assertions)
- `tests/test_stuck_run_recovery.py:371`
- `tests/test_retrigger_threading.py:208`
- `tests/test_queue_durability.py:1097` (plus a docstring reference at `:994` that should be updated for consistency)
`tests/test_queue_worker.py`'s ~13 `monkeypatch.setattr(drain, "drain_once", lambda: False/True)` sites do **not** need changes — they stub the function with their own bool-returning lambda and never call the real implementation; `worker.py:198`'s truthiness contract is what they exercise, and that contract is unchanged.
**Warning signs:** A test suite that goes from ~600 passing to a wall of `AssertionError: assert <DrainOutcome.DONE: 'done'> is True` the moment `drain_once()`'s return type changes, in a diff that touched no test files.

### Pitfall 2: The drain-loop wall-clock cap and the workflow's `curl --max-time` are the same design decision, made in two different files
**What goes wrong:** `keepalive.yml`'s existing `curl -f --max-time 90` pattern gets copy-pasted onto the new pump step in `pump.yml`. **CORRECTION (17-REVIEWS #1/#2):** the 210s figure from `app/routes/runs.py:37-72`'s `STALE_THRESHOLD` is the max GAP between two consecutive DB writes (a stall threshold), **NOT** a total single-job runtime — do not size the curl timeout from it. Size the pump step from the explicit provider timeouts instead: a single request's nominal worst case ≈ cold-start ≤60s + the pump's 120s between-jobs cap + one worst-case job's ≈240s external-call allowance (extraction/suggestion ≤90s each = `_STRUCTURED_TIMEOUT_S`×2, clarification draft ≤30s, Resend send ≤30s) + deterministic/DB/overhead ON TOP — i.e. 60+120+240 = 420 already, with overhead pushing PAST 420. The wall-clock cap is checked only *between* `drain_once()` calls (correct — never abort mid-job), so a request can begin ONE final job just under the cap. A `--max-time 90` on that step guarantees a false RED on the very first slow job, even though the server-side drain is proceeding correctly and safely (SKIP LOCKED + lease fencing make a client-side timeout harmless to correctness — the job simply finishes on the server and the next pump invocation, or the still-running worker threads, will find it already done).
**Why it happens:** Copying a working pattern verbatim across three near-identical `curl -f` steps in the same job feels like the obviously-safe move, and the two health-check steps genuinely should share `--max-time 90` (they're fast SELECT-only probes) — only the pump step is fundamentally different in worst-case shape.
**How to avoid:** Size the pump step's `--max-time` independently at **`--max-time 420`**, documented as a NOMINAL operating budget (cold-start ≤60 + 120s cap + ≈240s external-call allowance = 420, with overhead ON TOP so **NO headroom is claimed** — the earlier "360 ceiling + ~60s headroom" framing is WITHDRAWN as false, 17-REVIEWS #1), and say so in a comment at that step exactly like `keepalive.yml`'s existing comments explain `--max-time 90`. The value is PROVISIONAL until the live smoke confirms Render's undocumented server-side ceiling (A1); a rare overrun goes RED but is safe because CORRECTNESS rests on lease-reclaim (`lease_seconds=900`), not the curl budget — a job with attempts remaining is idempotently re-run next cadence. Also note (17-REVIEWS #2): if a client-side curl timeout fires, FastAPI/Starlette does **not** cancel a sync `def` route's in-flight AnyIO-threadpool work on client disconnect — the drain continues to completion server-side, so a curl-overrun RED most likely means the job FINISHED SUCCESSFULLY server-side (RED-but-succeeded), a request-level signal only, NOT "auto-retried". That is safe (idempotent, fenced) but worth documenting so a false RED from a slow demo-day event doesn't get misread as data loss.
**Warning signs:** A cron run reports RED on the pump step with a `curl: (28) Operation timed out` while the Render logs show the drain loop completing normally seconds later.

### Pitfall 3: "returns real counts" does not mean "N successful payrolls"
**What goes wrong:** The pump's `done` count is easy to read as "N payrolls processed successfully." It is not. Per `app/queue/handlers/pipeline.py`'s own docstring: a run whose pipeline stage genuinely failed and was caught by the orchestrator's own catch-all still lands the job as `done` — the orchestrator persists `ERROR` on the run and returns *normally*, and that "a failure a human can see completes the job" is the documented, deliberate Phase-16-era behavior (not a Phase 17 regression; FAIL-01/02 in Phase 18 is what will eventually classify this properly). `retried`/`dead` today reflect **only** genuine crash-reclaim cycles (an unrecordable failure — an import error, `record_run_error` itself failing), not classified business-outcome retries.
**Why it happens:** The five-word vocabulary (`claimed/done/retried/dead/fenced`) reads like a health signal; it is a *queue transport* signal.
**How to avoid:** The README's cadence documentation (criterion #3) and any dashboard-adjacent surfacing of these counts should say plainly that `done` counts job invocations that completed without an unrecordable crash, not payrolls that succeeded — and that "job success ≈100% while `status='error' > 0`" is a known, accepted, and explicitly Phase-21-scoped gap (D-09; OPS-01).
**Warning signs:** A recruiter-facing demo claim like "the pump processed N payrolls" when some of those N are ERROR runs already visible to the operator.

### Pitfall 4: `jobs.py`'s own docstring says "six functions, and this is the whole public surface" — it becomes false the moment a queue-depth function is added
**What goes wrong:** `app/db/repo/jobs.py`'s module docstring currently reads *"Six functions, and this is the whole public surface: `enqueue_job`, `claim_job`, `complete_job`, `fail_job`, `release_leases`, `get_job`."* Adding a seventh function (queue-depth count) without updating this line leaves an authoritative-sounding false claim in the file a future reader will trust.
**Why it happens:** It's an easy line to miss — it reads as prose, not as an enforced invariant, but the file's own convention treats these opening docstrings as load-bearing documentation (mirrored by other modules in this codebase, e.g. `drain.py`'s and `worker.py`'s own extensive module docstrings).
**How to avoid:** Update the count and the enumerated list in the same commit that adds the new function. Also re-export the new function through `app/db/repo/__init__.py`'s facade (both the import and `__all__`), matching the existing six.
**Warning signs:** grep for `"Six functions"` after the change — if it still says six, it's stale.

### Pitfall 5: No constant-time-compare seam actually exists in this repo to "reuse"
**What goes wrong:** CONTEXT.md's canonical_refs instructs the planner to "confirm the existing constant-time-compare seam (the webhook HMAC path) to reuse." A direct grep for `compare_digest`/`hmac\.` across `app/` returns **zero hits** [VERIFIED: `grep -rn "compare_digest\|hmac\." app/` — no matches]. The webhook's signature check is entirely delegated to `resend.Webhooks.verify(...)` (the svix SDK), which does its own internal comparison — there is no extractable helper function in this codebase to import and reuse.
**Why it happens:** It's a reasonable-sounding assumption from the outside — "surely there's already a constant-time compare somewhere in a codebase that verifies HMAC signatures" — that doesn't survive a grep.
**How to avoid:** Write the Bearer compare from Python's stdlib directly (2 lines, shown in Pattern 2 above). Do not spend planning time searching for a seam that isn't there.
**Warning signs:** A plan task phrased as "extract the existing compare helper" that, on inspection, has nothing to extract.

## Code Examples

### `pump.yml` — the folded-in workflow

```yaml
# Source: modeled directly on the existing .github/workflows/keepalive.yml,
# which this file replaces. See that file (deleted this phase) for the
# original comment style this preserves.
name: pump

on:
  schedule:
    - cron: "*/30 * * * *"   # every 30 minutes — see README for the duty-cycle math
  workflow_dispatch:          # GitHub auto-disables scheduled workflows after 60
                               # days with no repo COMMIT activity (not workflow
                               # activity) — this is the documented one-click re-enable.

jobs:
  pump:
    name: "Pump due jobs + keep-alive + schema drift"
    runs-on: ubuntu-latest
    steps:
      - name: Validate secrets are set
        run: |
          if [ -z "$RENDER_URL" ] || [ -z "$PUMP_TOKEN" ]; then
            echo "ERROR: RENDER_URL and/or PUMP_TOKEN secret not set."
            exit 1
          fi
        env:
          RENDER_URL: ${{ secrets.RENDER_URL }}
          PUMP_TOKEN: ${{ secrets.PUMP_TOKEN }}

      - name: Drain due jobs via the authenticated pump
        # --max-time is intentionally LARGER than the two health-check steps below, and
        # is a NOMINAL budget, not a proven bound (17-REVIEWS #1): cold-start <=60s + the
        # pump's 120s between-jobs cap + one worst-case job's ~240s external-call allowance
        # = 420, with deterministic/DB/overhead ON TOP (so NO headroom). It is NOT the 210s
        # inter-write stall gap. Correctness rests on lease-reclaim (lease_seconds=900),
        # not this budget: a job with attempts remaining is re-run next cadence (SKIP LOCKED).
        # Provisional until the live smoke confirms Render's server-side ceiling. Do not copy
        # --max-time 90 from the steps below onto this one.
        run: curl -f --max-time 420 -H "Authorization: Bearer $PUMP_TOKEN" "$RENDER_URL/internal/pump"
        env:
          RENDER_URL: ${{ secrets.RENDER_URL }}
          PUMP_TOKEN: ${{ secrets.PUMP_TOKEN }}

      - name: Ping /health/ready (wakes service + touches Supabase)
        run: curl -f --max-time 90 "$RENDER_URL/health/ready"
        env:
          RENDER_URL: ${{ secrets.RENDER_URL }}

      - name: Check /health/schema (drift → RED)
        run: curl -f --max-time 90 "$RENDER_URL/health/schema"
        env:
          RENDER_URL: ${{ secrets.RENDER_URL }}
```

### The queue-depth repo function

```python
# Source: modeled on app/db/repo/jobs.py's existing _conn_ctx/_nulltx convention
# (every function in that module already follows this shape).
def count_open_jobs(conn: psycopg.Connection | None = None) -> int:
    """A point-in-time count of jobs not yet terminal (`pending` or `leased`).
    Used by the pump's response and, later, an ops view (OPS-01). Deliberately
    NOT scoped to "claimable right now" (available_at <= now()) — the useful
    signal here is total outstanding backlog, matching ops-parlance "queue depth."
    """
    with _conn_ctx(conn) as (c, _owns):
        row = c.execute(
            "SELECT count(*) FROM jobs WHERE state IN ('pending', 'leased')"
        ).fetchone()
    return int(row[0]) if row else 0
```

Add to `app/db/repo/__init__.py`'s import list and `__all__`; update `jobs.py`'s module docstring's function count (Pitfall 4).

### Manipulating `available_at` for the durability proof (no `sleep`)

`enqueue_job` exposes no parameter to set a future `available_at` — the column defaults to `now()` [VERIFIED: `app/db/schema.sql:516`]. The existing durability-proof file already establishes the pattern for backdating a different timestamp column without sleeping (`leased_until`, in `test_retrigger_survives_worker_crash_mid_lease`, step 4):

```python
# Source: pattern already used in tests/test_queue_durability.py, step 4 of
# test_retrigger_survives_worker_crash_mid_lease — apply the identical idiom
# to available_at for a "job scheduled with a future available_at" proof.
with repo.get_connection() as conn, conn.transaction():
    conn.execute(
        "UPDATE jobs SET available_at = now() + interval '1 hour' WHERE id = %s",
        (str(job_id),),
    )
# ... assert the job is NOT claimable while future-dated (a claim_job() call
# returns None) ...
with repo.get_connection() as conn, conn.transaction():
    conn.execute(
        "UPDATE jobs SET available_at = now() - interval '1 second' WHERE id = %s",
        (str(job_id),),
    )
# ... now the pump (via the route, or drain.drain_once() directly) must claim it.
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|---------------|--------|
| `keepalive.yml` — 2x/week cron, drains nothing | `pump.yml` — 30-min cron, drains due jobs + keeps both keepalive checks | This phase | `keepalive.yml`'s entire job list is absorbed; it is deleted, not deprecated-in-place. |
| `drain_once() -> bool` | `drain_once() -> DrainOutcome` (StrEnum, truthy except `EMPTY`) | This phase (D-04) | `worker.py` unaffected; ~15 test assertions must be rewritten to the specific outcome value. |
| Two-file-by-name CI selection for live-DB durability proofs | `queueproof`-marker-based selection, already live (Phase 16 D-14) | Phase 16 (already shipped) | No `concurrency-proof.yml` edits needed this phase — only add the marker to the new test module. |

**Deprecated/outdated:**
- `keepalive.yml`'s own comment block explaining `--max-time 90` for its two health checks is correct and should be preserved verbatim in `pump.yml` for those same two steps — only the new pump step needs different sizing (Pitfall 2).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Render's free-tier reverse proxy has no documented hard request-duration limit shorter than the pump's own nominal worst case (~420s: cold-start ≤60 + 120s cap + ≈240s external-call allowance + overhead) | Pitfall 2 / Code Examples (`--max-time 420`) | If Render silently kills long requests server-side (undocumented), a slow pump run could 502 mid-drain even with a generous client `--max-time`. The drain itself is still safe (idempotent, fenced; a job with attempts remaining is lease-reclaimed) but the pump would need to be re-run more often, or the cap tuned tighter, than this research assumes. Live smoke (see VALIDATION.md, review finding #4): drive a DELIBERATELY long-running controlled request — a seeded job whose handler is stubbed/slowed to sleep TOWARD the ~420s cap, with NO paid-provider or duplicate-send behavior — and confirm the request completes rather than 502ing; a routine small backlog finishes in seconds and proves nothing about the ceiling. |
| A2 | `MAX_JOBS_PER_PUMP=20` / `MAX_WALL_CLOCK_SECONDS=120` are reasonable static constants for ~1 email/client/week load | §Code Examples, §Common Pitfalls Pitfall 2 | These are ASSUMED defaults, not measured against a real backlog scenario — if the demo ever simulates a large backlog, the caps may need retuning. Low risk given the stated load. |
| A3 | Placing `DrainOutcome` in `app/queue/drain.py` rather than `app/models/job.py` is the better home | §Pattern 1 | This is a judgment call, not a locked decision — reasonable engineers could put it in `app/models/job.py` for symmetry with `JobKind`/`JobState`. The risk if "wrong" is purely stylistic; no functional impact either way. |

## Open Questions (RESOLVED)

1. **What should `drain_once()` return when `fail_job` itself raises (the double-failure branch)?**
   - **RESOLVED — RE-RAISE (NOT FENCED). This supersedes the earlier "map to FENCED" text, which review round 1 overturned (17-REVIEWS finding #1) and round 3 re-confirmed. Do NOT map the double-failure to FENCED.**
   - The double-failure branch (`fail_job()`'s own write failed — a genuine DB outage that intentionally RETAINS the lease, drain.py:180) is semantically distinct from a SETTLED fence (a write that landed but matched zero rows, drain.py:7). It is an infra failure, not a per-job outcome. Mapping it to a truthy `FENCED` would let the pump route return HTTP 200 during a real outage — a false GREEN cron over a live outage (violates D-10).
   - **Adopted in `17-01-PLAN.md` Task 1:** the inner `except` (the "fail_job itself failed" branch) keeps its existing `logger.exception(...)` message, leaves `lease_settled = False` (token retained for graceful shutdown), then RE-RAISES (bare `raise`). The exception propagates out of `drain_once()`; the worker loop (worker.py:203) catches it and keeps polling, and the pump route's try/except turns it into 503 (RED cron over a real outage). `FENCED` stays reserved for a SETTLED fence.
   - D-04's locked vocabulary stays at exactly five values (`empty|done|retried|dead|fenced`) — an infra failure is an EXCEPTION, not a sixth outcome.

2. **Does Render's free-tier proxy impose an undocumented request-duration ceiling?**
   - **RESOLVED (deferred to live smoke test):** Treat `--max-time 420` as provisional; the verification is a Manual-Only row in `17-VALIDATION.md` (live smoke against the deployed instance once shipped). Carried, not dropped.
   - What we know: no official Render documentation surfaced a specific number via search; only the well-documented 15-minute idle-spindown and ~750h/month budget. [CITED: render.com/docs/free]
   - What's unclear: the actual behavior of a single in-flight request running 3-5+ minutes on a free web service.
   - Recommendation: treat the `--max-time 420` value as provisional and verify once deployed (see A1).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| GitHub Actions (scheduled workflows) | PUMP-02 cron | ✓ (already used by `keepalive.yml`, `concurrency-proof.yml`, `ci.yml`) | — | — |
| Render free web service | PUMP-01/02 (the pump target) | ✓ (already deployed, per STATE.md's "Phase 6 deploy facts") | — | — |
| Python stdlib `hmac` | D-01 auth | ✓ (3.12, already the runtime) | stdlib | — |

No missing dependencies — this phase introduces no new external tool, service, or package requirement.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest, already configured (`pyproject.toml`) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` — `queueproof` marker already registered |
| Quick run command | `uv run pytest tests/test_queue_drain.py tests/test_repo_jobs_sql.py -q` |
| Full suite / live-DB command | `uv run pytest tests/ -m queueproof -v -rs` (already wired into `concurrency-proof.yml`'s second step) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PUMP-01 (criterion #1 — real counts) | `drain_once()` returns the correct specific `DrainOutcome` for each of: empty queue, successful dispatch, handler-raises-retry, handler-raises-dead-letter, fenced completion | hermetic | `uv run pytest tests/test_queue_drain.py -k "drain_once" -q` | Modify existing (5 behaviors already tested by name; rewrite assertions to specific outcome values) |
| PUMP-01 (criterion #1 — auth) | 401 on missing/wrong/empty-secret Bearer token; 200 on correct token | hermetic (TestClient, `WORKER_COUNT=0` already pinned suite-wide) | `uv run pytest tests/test_pump_route.py -q` | ❌ Wave 0 — new file |
| PUMP-01 (criterion #2 — the anti-vacuous-proof anchor) | A job with a future `available_at` (backdated to due, no sleep), **zero live worker threads**, is drained by hitting `/internal/pump` (or `drain.drain_once()` directly per the D-06/Phase-16 convention) — not by an incidentally-running worker | `queueproof` (live Postgres) | `uv run pytest tests/test_queue_durability.py -m queueproof -k pump -v` | ❌ Wave 0 — new test in the existing `test_queue_durability.py` module (reuses its `_isolated_jobs`/`seeded_db` fixtures; **must NOT** request the `live_worker` fixture — the whole point is that no worker exists) |
| PUMP-01 (criterion #1 — queue depth) | `count_open_jobs()` returns the correct count across pending/leased/done/dead mixes | hermetic (`fake_repo`) + `queueproof` (live) | `uv run pytest tests/test_repo_jobs_sql.py -k count_open_jobs -q` | ❌ Wave 0 |
| PUMP-01 (D-05 — bounded drain) | The pump loop stops at the max-jobs cap even when more jobs remain claimable; stops at the wall-clock cap even mid-backlog | hermetic (stub `drain_once` to always return non-EMPTY, assert loop exits at the cap) | `uv run pytest tests/test_pump_route.py -k bounded -q` | ❌ Wave 0 |
| PUMP-02 (criterion #4 — workflow structure) | `pump.yml` exists with 3 `curl -f` steps and `workflow_dispatch`; `keepalive.yml` is gone | static (a small parser/grep-based test, mirroring the discipline of `tests/test_bound01_private_imports.py`'s AST-scan style, OR a manual check — see below) | n/a — see note | n/a |
| PUMP-01 (D-10 — infra failure semantics) | A simulated DB failure during the drain (not a dispatch failure) surfaces as 5xx, not 200 | hermetic (`fake_repo` raising from `claim_job`/`count_open_jobs`) | `uv run pytest tests/test_pump_route.py -k infra_failure -q` | ❌ Wave 0 |

**Note on the workflow-structure check:** this repo has no existing precedent for a Python test parsing a `.yml` workflow file's structure (the CI landmines documented in canonical_refs are about test *selection*, not workflow *content* assertions). A lightweight test is still valuable (e.g. `yaml.safe_load` the file and assert `on.schedule`, `workflow_dispatch` present, and exactly 3 `curl -f` occurrences in the steps) but is a genuinely new pattern for this repo — the plan should treat it as optional polish, not a blocking gate, since the workflow's real correctness is only provable by a live cron firing (out of unit-test reach) and by the manual verification step described below.

### Sampling Rate
- **Per task commit:** the hermetic quick-run command above.
- **Per wave merge:** `uv run pytest tests/ -m queueproof -v -rs` (live Postgres required locally, or defer to the CI gate — this is exactly what `concurrency-proof.yml`'s second step already runs).
- **Phase gate:** full suite green (`uv run pytest -q`) + the `queueproof`-marked durability test demonstrated to fail against a deliberately-reintroduced defect and pass against the real fix, per this project's own PROOF-05 "every proof must be demonstrated able to fail" discipline (already the house style — see `test_queue_durability.py`'s "FALSIFYING MUTATIONS" docstring sections).

### Wave 0 Gaps
- [ ] `tests/test_pump_route.py` — covers PUMP-01's auth (401/200), bounded-drain-loop, and D-10 infra-failure-vs-business-outcome semantics. Hermetic, `fake_repo`-based, following `tests/test_queue_drain.py`'s existing style.
- [ ] A new `queueproof`-marked test appended to `tests/test_queue_durability.py` — the criterion #2 anti-vacuous-proof anchor (see below). Must NOT request `live_worker`; must assert `live_queue_worker_threads() == []` as an explicit precondition, mirroring the existing module's own precondition-assertion discipline (e.g. `test_a_restarted_worker_claims_and_completes_a_real_job`'s pattern of asserting the state it depends on before proceeding).
- [ ] `tests/test_repo_jobs_sql.py` gains hermetic coverage for `count_open_jobs`.
- [ ] The ~15-site test rewrite from `is True`/`is False` to specific `DrainOutcome` values (Pitfall 1) — not a new file, but a real, non-trivial task that should appear explicitly in the plan's task list with its own verification step (a `grep -rn "drain_once() is True\|drain_once() is False" tests/` that returns zero hits once done).

### Designing the anti-vacuous-proof anchor (criterion #2) — the phase's single most important test

**The exact failure state to construct**, per the roadmap's own wording: a job scheduled for later, on an instance with **no live worker threads**, still executes when the pump fires.

**Why this is nearly free to prove correctly in this codebase, and why it would be trivially easy to get vacuously wrong:**

- `tests/conftest.py` already pins `WORKER_COUNT=0` for the entire suite [VERIFIED: `tests/conftest.py:45`, `os.environ["WORKER_COUNT"] = "0"`]. This means **every** `TestClient(app_main.app)` instantiation in the whole test suite already runs with zero live worker threads by construction — the "cold-started instance" state criterion #2 asks for is the suite's *default* posture, not something that needs elaborate staging.
- The **vacuous twin** this must avoid: a test that (a) accidentally requests the `live_worker` fixture (starting a real worker that races ahead and drains the job before the pump call, making the pump's own contribution unprovable), or (b) never actually backdates `available_at`/verifies the row is genuinely due before hitting the pump (so the test would "pass" even if the pump's claim query were broken, because the job was claimable from the moment it was inserted), or (c) asserts only `response.status_code == 200` (satisfied even if the pump claimed zero jobs).
- **The concrete design:**
  1. In a `queueproof`-marked test in `tests/test_queue_durability.py` (reusing its `seeded_db`/`_isolated_jobs` fixtures, and its `_seed_run_for_queue_proof()` helper), enqueue a `run_pipeline` job via `repo.enqueue_job(...)`.
  2. Immediately backdate its `available_at` to the future (e.g. `now() + interval '1 hour'`) via direct SQL (see Code Examples) — this proves the job would NOT be claimable "right now" without the pump/time passing.
  3. Assert `live_queue_worker_threads() == []` explicitly, as its own assertion with its own failure message — the precondition that makes the rest of the test meaningful.
  4. Assert `repo.claim_job()` returns `None` while `available_at` is still future-dated (proves the job is genuinely not claimable yet — the vacuity check for the "future" half of the claim).
  5. Move `available_at` back to the past (simulating "the scheduled moment has arrived, and nothing woke up to notice because there are no workers").
  6. Hit `/internal/pump` via `TestClient(app_main.app)` with a correctly-configured `PUMP_TOKEN` — **not** `drain.drain_once()` directly for this specific test, since the whole point of criterion #2 is that the *endpoint* (the thing cron actually calls) is what does the draining, not the test calling the internal function on its own behalf. (`drain.drain_once()` directly remains the right tool for the *other* durability proofs that are about the claim/lease mechanics, per Phase 16 D-06 — this one test is specifically about the pump's HTTP-level responsibility.)
  7. Assert the response reports `claimed == 1` and the specific outcome bucket incremented (e.g. `done == 1`), not merely `status_code == 200`.
  8. Re-read the job row by its own id (never "a job somewhere") and assert `state == 'done'`.
- **The falsifying mutation to actually run and paste red, per this project's own PROOF-05 discipline:** temporarily reintroduce the pre-Phase-16 bug — strip the `OR (c.state = 'leased' AND c.leased_until < now())`-style future-dated clause, or more directly: temporarily make `/internal/pump`'s route call a no-op stub instead of the real drain loop — confirm the test goes RED (job never reaches `done`, response `claimed == 0`), then revert and confirm GREEN. Paste both outputs into the plan's SUMMARY, matching the existing file's own "FALSIFYING MUTATIONS" documentation convention.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Bearer shared-secret, constant-time compared (`hmac.compare_digest`), fail-closed on empty/unset secret (D-03) — this is machine-to-machine authentication for an internal trigger endpoint, not user authentication; scope stays narrow per D-01's explicit "not a step toward operator/dashboard auth." |
| V3 Session Management | no | No session state — each pump call is a stateless, single Bearer-token check. |
| V4 Access Control | yes | The 401-vs-404 choice (D-02) is itself an access-control disclosure decision: returning 401 (not 404) deliberately reveals the route's existence in exchange for a loud, debuggable cron failure — an accepted, documented tradeoff, not an oversight. |
| V5 Input Validation | n/a | The pump endpoint takes no user-supplied body/params; the only "input" is the Authorization header, validated via V2's control above. |
| V6 Cryptography | yes | `hmac.compare_digest` — never a hand-rolled `==` comparison, which would be timing-attack-vulnerable for a bearer secret compared over the network. |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Timing attack against a naive `token == expected` compare, recovering the secret byte-by-byte via response-latency measurement | Information Disclosure | `hmac.compare_digest`, never `==`, for any secret comparison (D-01; already this phase's own locked decision). |
| A misconfigured deploy ships with `PUMP_TOKEN` unset, silently accepting any/no credential | Elevation of Privilege | Fail-closed (D-03): reject every call when the token is empty, rather than treating an empty expected-value as "auth disabled." The route's `_authorized()` check in Pattern 2 above returns `False` immediately when `token` is falsy, before ever reaching the compare. |
| A poison job or backlog flood pins the pump's HTTP request open indefinitely, exhausting the AnyIO threadpool one call at a time across repeated cron fires | Denial of Service | D-05's dual cap (max-jobs + wall-clock), bounding each individual pump invocation. |
| Route disclosure via 404-vs-401 status-code difference | Information Disclosure (deliberately accepted) | D-02 explicitly chooses 401 over 404 — documented, intentional, because a misconfigured `PUMP_TOKEN` must be loud (cron goes RED), and the endpoint's existence is not itself sensitive (it requires the internal Bearer secret to do anything; it is not a data-disclosure surface). |

## Sources

### Primary (HIGH confidence — direct source reads, this session)
- `app/queue/drain.py`, `app/queue/worker.py`, `app/db/repo/jobs.py`, `app/models/job.py`, `app/db/repo/__init__.py`, `app/main.py`, `app/config.py`, `app/routes/health.py`, `app/routes/webhook.py`, `app/email/gateway.py`, `app/queue/dispatch.py`, `app/queue/handlers/pipeline.py`, `app/db/schema.sql` (jobs table), `render.yaml`, `.github/workflows/keepalive.yml`, `.github/workflows/concurrency-proof.yml`, `pyproject.toml` (markers), `tests/conftest.py`, `tests/test_queue_drain.py`, `tests/test_queue_durability.py`, `tests/test_repo_jobs_sql.py` — read in full or targeted grep this session.
- `git log -p --follow -- app/db/repo/jobs.py` — confirmed `complete_job`/`fail_job`'s return-type signatures have been `bool`/`JobState | None` since their single introducing commit (`2f9ea6b`), never `bool`/`bool`.

### Secondary (MEDIUM confidence — web-verified, dated)
- render.com/docs/free — 750 free instance-hours/month/workspace, 15-minute idle spindown, ~1-minute cold start. [CITED]
- GitHub community discussions + docs.github.com — scheduled workflows disabled after 60 days with no repository **commit** activity (not workflow-run activity specifically). [CITED — worth a precision note in the README's wording: it's repo-commit-activity-based, not workflow-specific]

### Tertiary (LOW confidence — flagged, not authoritative)
- Render's exact request-duration ceiling for free web services was not found in official documentation via search; treated as an open question (see Open Questions #2 / Assumption A1).

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — zero new dependencies, every mechanism already stdlib or in-repo.
- Architecture: HIGH — every code seam cited was read directly this session; the `drain_once()`/`fail_job` return-type finding directly contradicts CONTEXT.md's stated cost and is independently confirmed via `git log -p`.
- Pitfalls: HIGH for the `is True`/`is False` breakage (exact line numbers enumerated via grep) and the missing constant-time-compare seam (confirmed absent via grep); MEDIUM for the `--max-time`/Render-timeout interaction. NOTE (17-REVIEWS #1/#2): the 210s figure this doc originally cited is the max inter-write STALL gap, NOT a single-job runtime — the corrected pump budget is `--max-time 420` (nominal, provisional-until-live-smoke; NO headroom), and correctness rests on lease-reclaim, not the curl budget. Render's own server-side ceiling is unverified — see Open Questions / A1 / VALIDATION's live smoke.

**Research date:** 2026-07-15
**Valid until:** 30 days (stable stdlib/FastAPI/GitHub Actions mechanics; re-verify Render's 750h figure and any request-timeout behavior if this phase slips past a Render pricing-page change).
