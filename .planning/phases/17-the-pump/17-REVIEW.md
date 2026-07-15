---
phase: 17-the-pump
reviewed: 2026-07-15T15:21:59Z
depth: deep
files_reviewed: 10
files_reviewed_list:
  - app/queue/drain.py
  - app/routes/pump.py
  - app/config.py
  - app/main.py
  - app/db/repo/jobs.py
  - app/db/repo/__init__.py
  - .github/workflows/pump.yml
  - render.yaml
  - README.md
  - tests/test_pump_route.py
findings:
  critical: 0
  warning: 2
  info: 3
  total: 5
status: issues_found
---

# Phase 17: Code Review Report — "The Pump"

**Reviewed:** 2026-07-15T15:21:59Z
**Depth:** deep (cross-file: pump route ↔ drain_once ↔ repo facade ↔ cron/render/README)
**Files Reviewed:** 10 production + infra (tests spot-checked for false confidence)
**Status:** issues_found

## Summary

The core money-path invariants the phase set out to guarantee **hold under trace**:

- **D-10 (no false GREEN over an outage) is intact.** `drain_once()`'s inner
  `except` re-raises the double-failure (`app/queue/drain.py:225`) instead of
  mapping it to a truthy `FENCED`; the pump route wraps the whole drain loop
  *and* the `count_open_jobs()` read in one `try/except Exception` that maps any
  propagated exception to HTTP 503 (`app/routes/pump.py:95-111`). `outcome` is
  provably bound on every path that reaches `return outcome` (the re-raise
  terminates the only branch that doesn't set it), so there is no possibly-unbound
  200-with-garbage path.
- **Auth is correct.** Constant-time `hmac.compare_digest` over the full
  `Bearer <token>` bytes, fail-closed on empty/unset `PUMP_TOKEN` *before* the
  compare, 401 (not 404) on any failure (`app/routes/pump.py:65-90`).
- **503 disclosure discipline holds.** Only `type(exc).__name__` is logged; the
  client body is the fixed `"pump unavailable"`. `raise ... from exc` sets
  `__cause__` but Starlette's HTTPException handler does not emit a traceback, so
  no `str(exc)` / connection string leaks.
- **The dual bound is real.** `claimed < _MAX_JOBS_PER_PUMP` caps iterations
  unconditionally (max 20) and `time.monotonic() < deadline` caps wall-clock
  between jobs; the loop cannot spin forever even if `drain_once()` never returns
  `EMPTY`. The `-k bounded` wall-clock test genuinely isolates the wall-clock
  branch (patches `pump_module.time` only, jumps the clock after N<max iterations).
- **The invariant `claimed == done + retried + dead + fenced` holds by
  construction** — each non-EMPTY iteration increments `claimed` and exactly one
  bucket keyed by `outcome.value`.
- **No SQL injection surface.** `count_open_jobs` uses a fully static literal
  `WHERE state IN ('pending', 'leased')` with an empty params tuple; every sibling
  in `jobs.py` uses placeholders. No f-string SQL. No cross-module `_private`
  imports in the new route (facade `repo.*` + public `drain` symbols). No
  `--no-verify`.

Two issues are worth fixing before this is considered done, plus three nits. The
most material is an infra-workflow ordering bug that **directly contradicts a
guarantee the workflow's own comment claims to provide**.

## Warnings

### WR-01: A failing pump step silently suppresses the schema-drift and keepalive monitors it claims to protect

**File:** `.github/workflows/pump.yml:62-114`
**Issue:** The three curl steps run sequentially with `curl -f` (fail on non-2xx)
and **none carries an `if:` condition**. GitHub Actions skips every subsequent
step once a step exits non-zero. So when the pump step (`--max-time 420` curl to
`/internal/pump`) fails, the two steps after it — `Ping /health/ready` (the
Render wake + Supabase touch) and `Check /health/schema` (drift → RED) — **do not
run at all**.

This is exactly the failure the design says it prevented. The phase itself
documents that a rare worst-case-clarification request *can* overrun 420 and go
RED ("acceptable-and-documented"), and any persistent pump-route regression
returns 503 on every cadence. On those runs:
- `/health/schema` drift monitoring is silently skipped — a manual Supabase edit
  bypassing `deploy-migrate.yml` (the *only* thing this check catches) goes
  unnoticed for as long as the pump stays RED.
- `/health/ready`'s Supabase touch is skipped (lower impact — the pump step also
  hits the DB, and one missed 30-min ping is far inside Supabase's pause window).

The workflow comment at lines 96-99 and 111-113 explicitly asserts the opposite:
*"carried forward verbatim from keepalive.yml so a pump-route regression can't
silently also lose this wake+touch signal"* and *"the check that would silently
disappear."* The code guarantees the reverse of its stated invariant: coupling an
independent monitor *behind* a `-f` step that is designed to go RED means the
monitor disappears precisely when the pump is unhealthy.

**Fix:** Add `if: always()` (or `if: '!cancelled()'`) to the two health steps so
they run regardless of the pump step's exit status, restoring their independence:
```yaml
      - name: Ping /health/ready (wakes service + touches Supabase via SELECT)
        if: always()
        run: curl -f --max-time 90 "$RENDER_URL/health/ready"
        env:
          RENDER_URL: ${{ secrets.RENDER_URL }}

      - name: Check /health/schema (drift → RED)
        if: always()
        run: curl -f --max-time 90 "$RENDER_URL/health/schema"
        env:
          RENDER_URL: ${{ secrets.RENDER_URL }}
```
(The job still goes RED overall because the failed pump step's status
propagates — you keep the loud signal while decoupling the monitors.)

### WR-02: `complete_job` raising after a successful dispatch re-enqueues an already-executed job (pre-existing; money-path — confirm idempotency)

**File:** `app/queue/drain.py:180-213`
**Issue:** In the success `try`, `dispatch.handle(job)` runs first, then
`repo.complete_job(...)`. If `dispatch.handle` succeeds (payroll pipeline ran,
confirmation possibly sent) but `repo.complete_job` then *raises* (a transient
error on the completion write specifically — e.g. a serialization failure or a
mid-statement disconnect), control falls into the outer `except`, which calls
`repo.fail_job` → the job is backed off and **re-dispatched next cadence**. That
is a second execution of a job whose real-world side effects already happened.

This is **not a Phase-17 regression** — the `try` structure (dispatch → complete,
with a shared `except` calling `fail_job`) predates this phase; P17 only changed
the return type and added the inner re-raise. It is also *likely mitigated* by the
pipeline's at-most-once status CAS + `send_guard` (per project design), which
should make a re-run a no-op rather than a double-pay/double-send. It is flagged
because it sits squarely on the money path and the mitigation lives in a
different module (`dispatch.handle`), not here.

**Fix:** No change required in `drain.py` if idempotency is truly guaranteed —
but confirm it explicitly: add/point to a test that runs `dispatch.handle` twice
for the same `run_id` and asserts no second confirmation email and no second
payroll write. If that guarantee is not airtight, narrow the completion-write
failure so it does not route through `fail_job` (a completed-but-unrecorded job
should fence/park, not retry the handler).

## Info

### IN-01: `queue_depth` counts `leased` rows, so it never reaches 0 during active work and permanently counts the final-attempt strand

**File:** `app/db/repo/jobs.py:287-307`
**Issue:** `count_open_jobs` counts `state IN ('pending', 'leased')`. This is
documented as intentional ("total outstanding depth"), but two consequences are
worth stating for the operator-facing consumer: (1) a job the pump is actively
draining is `leased`, so `queue_depth` is non-zero whenever anything is in
flight; (2) the documented final-attempt lease-strand (`attempts == max_attempts`,
`leased`, expired — never re-selectable until Phase-18's dead-letter transition)
is counted **forever**, so a healthy drained queue can still report a permanent
nonzero `queue_depth`. Both are already accepted residuals (T-17-16); noted only
so a future dashboard panel does not treat `queue_depth == 0` as a liveness SLO.
**Fix:** None this phase. When the Phase-18 dead-letter transition lands, ensure
`count_open_jobs` (or a companion metric) distinguishes truly-actionable backlog
from stranded/in-flight leases.

### IN-02: Response buckets couple implicitly to `DrainOutcome.value` strings; a mismatch masquerades as a 503 infra failure

**File:** `app/routes/pump.py:92,101`
**Issue:** `counts = dict.fromkeys(("done","retried","dead","fenced"), 0)` then
`counts[outcome.value] += 1` relies on the enum's string values exactly matching
these literal keys. If a future edit renames a `DrainOutcome` value without
updating this tuple, the `KeyError` is caught by the honest catch-all and
reported as HTTP 503 "pump unavailable" — a real programming error disguised as an
infra outage (and a RED cron with a misleading cause). Low likelihood, but the
coupling is invisible.
**Fix:** Derive the keys from the enum, e.g.
`counts = {o.value: 0 for o in DrainOutcome if o is not DrainOutcome.EMPTY}`, so
the buckets can never drift from the vocabulary.

### IN-03: `count_open_jobs` breaks the module's uniform cursor idiom

**File:** `app/db/repo/jobs.py:305-307`
**Issue:** Every other function in `jobs.py` opens an explicit
`c.cursor(...) as cur` inside the `_conn_ctx` block; `count_open_jobs` instead
calls connection-level `c.execute(...).fetchone()`. It works (psycopg3
`Connection.execute` creates an implicit cursor), and the SQL is safe, but the
one-off style diverges from the "same convention every other function uses"
promise in its own docstring and in `test_every_function_takes_conn_and_uses_conn_ctx`.
**Fix (optional):** For consistency, mirror the sibling shape:
```python
    with _conn_ctx(conn) as (c, _owns), c.cursor() as cur:
        cur.execute("SELECT count(*) FROM jobs WHERE state IN ('pending', 'leased')")
        row = cur.fetchone()
    return int(row[0]) if row else 0
```

---

_Reviewed: 2026-07-15T15:21:59Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
