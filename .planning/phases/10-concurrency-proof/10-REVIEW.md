---
phase: 10-concurrency-proof
reviewed: 2026-07-07T00:00:00Z
depth: standard
files_reviewed: 2
files_reviewed_list:
  - tests/test_concurrency_proof.py
  - .github/workflows/concurrency-proof.yml
findings:
  critical: 1
  warning: 4
  info: 3
  total: 8
status: issues_found
---

# Phase 10: Code Review Report

**Reviewed:** 2026-07-07T00:00:00Z
**Depth:** standard
**Files Reviewed:** 2
**Status:** issues_found

## Summary

Phase 10 is a test-only capstone: `tests/test_concurrency_proof.py` (3 integration
tests, N=8 fan-out) plus `.github/workflows/concurrency-proof.yml` (ephemeral
postgres:16 CI). Zero production code changed. I reviewed for (a) whether the
concurrency assertions actually prove what the module title claims, (b) flakiness /
live-credit-burn risk, (c) thread-safety of shared collection, and (d) CI secret /
reset hygiene.

The credit-burn defense and CI hygiene are solid: the canonical webhook payload
never touches `resend.EmailsReceiving.get` (offline parse path, confirmed in
`app/email/gateway.py:130-135`), `_stub_pipeline_and_send` correctly patches
`_run_pipeline`, `app.pipeline.orchestrator._deliver` (the import-inside-route
target), and `resend.Emails.send`; `.env` is gitignored + untracked so CI never
inherits the live keys; the postgres password is ephemeral and network-isolated.

The **central problem is that two of the three "concurrency proofs" cannot fail
the way they advertise.** Surfaces A and C fire N=8 threads at an `async def`
route (`/webhook/inbound`) whose body is entirely **synchronous blocking DB I/O
with no `await` yield point between the dedup insert and `create_run`**. Starlette
runs `async def` endpoints on the single event-loop thread, so the eight ingest
transactions execute **one-at-a-time, serialized by the event loop** — they never
overlap at the DB layer. The `ON CONFLICT` / lost-update races these tests claim
to "prove under genuine parallelism" are never actually exercised. Surface B
(`def approve`, a sync route → real threadpool) IS genuinely parallel and does
prove its invariant.

## Critical Issues

### CR-01: Surfaces A and C do not exercise DB-level concurrency — the proof is vacuous for two of three invariants

**File:** `tests/test_concurrency_proof.py:151-215` (Surface A) and `:281-353` (Surface C)
**Issue:**
Both surfaces POST N=8 requests to `/webhook/inbound`. That route is declared
`async def inbound(...)` (`app/main.py:276`) and its entire body — `with
repo.get_connection() as conn: with conn.transaction(): repo.insert_inbound_email(...)
... repo.create_run(...)` (`app/main.py:377-459`) — is **synchronous, blocking
psycopg I/O with no `await` anywhere inside the transaction block** (the only
`await` is `await request.body()` at line 300, before any DB work).

In Starlette/ASGI, an `async def` endpoint runs directly on the event loop. With a
single shared `TestClient` driving all eight threads through one ASGI portal/event
loop, the handler bodies run to completion sequentially — the event loop cannot
switch coroutines mid-body because there is no `await` suspension point between the
`INSERT ... ON CONFLICT` and the `create_run`. **The eight ingest transactions are
therefore serialized, never interleaved.** This directly contradicts the module
docstring ("genuine OS-thread parallelism," "N=8 simultaneous operations,"
"genuinely interleaves") and each test's own docstring ("under genuine
parallelism").

Consequence: Surface A would pass **even if `insert_inbound_email` had no
`ON CONFLICT` clause at all** — the first serialized request inserts the row and
creates the run; the next seven, running strictly afterward, see the committed row
and take the duplicate branch. The MVCC race the test claims to close is never
triggered. Surface C's "no lost update" is likewise proven only against
sequential ingests. These are the two headline invariants (dedup race, lost
update); as written they are green-by-construction, not green-by-correctness.

Contrast: Surface B posts to `def approve` (`app/main.py:748`, a *sync* route),
which Starlette dispatches to its anyio worker threadpool — those eight requests
DO run on distinct OS threads concurrently, so Surface B's CAS proof is real.

**Fix:** Make the ingest race genuinely concurrent. Options, best first:

1. Drive the concurrent inserts against a route/seam that runs in a threadpool, or
   bypass the event-loop serialization by hitting the *sync* DB seam directly from
   N threads with a per-thread barrier so all threads are inside
   `insert_inbound_email` + `create_run` at the same wall-clock instant:

   ```python
   from app.db import repo

   start = threading.Barrier(N)
   results: list = []
   lock = threading.Lock()

   def _ingest():
       start.wait()  # release all N threads simultaneously
       eid, inserted = repo.insert_inbound_email(
           message_id=same_message_id, in_reply_to=None, references_header=None,
           subject="s", from_addr=COASTAL_EMAIL, to_addr="a@b", body_text="x",
       )
       rid = repo.create_run(business_id=COASTAL_BIZ_ID, source_email_id=eid) if inserted else None
       with lock:
           results.append((eid, inserted, rid))

   threads = [threading.Thread(target=_ingest) for _ in range(N)]
   for t in threads: t.start()
   for t in threads: t.join()
   ```

   This forces real overlap through the pool (which also then meaningfully
   exercises the `max_size=5` vs N=8 contention — see WR-01). The final
   `SELECT count(*) == 1` backstop then proves the DB-level `ON CONFLICT`, not the
   event-loop's accidental serialization.

2. If the route surface must be kept, add a `threading.Barrier(N)` and change
   `/webhook/inbound` to a sync route or wrap its DB body in `run_in_threadpool`
   — but that is a production change out of this phase's scope, so option 1 is
   preferred for a test-only phase.

At minimum, the module and per-test docstrings must be corrected to stop claiming
"genuine parallelism" / "genuinely interleaves" for Surfaces A and C until the
serialization is broken, because that claim is the phase's entire stated value
("the evidence behind the production-grade claim").

## Warnings

### WR-01: `max_size=5` pool vs N=8 concurrent holders — real parallelism (once CR-01 is fixed) can starve on a 5s timeout

**File:** `tests/test_concurrency_proof.py:61` and `app/db/supabase.py:52-63`
**Issue:**
`N = 8`, but the app's `ConnectionPool` is `min_size=1, max_size=5` with
`timeout=5` (seconds). The line-61 comment asserts N=8 "stays inside the pool
budget (min=1/max=5)" — that is only true today *because* CR-01's serialization
means at most one connection is ever checked out at a time. The moment the tests
are made genuinely concurrent (the whole point of the phase, per CR-01's fix),
eight threads each holding a connection for the full ingest transaction will
contend for five slots; three threads block on `pool.connection()` and, if the DB
is slow (cold CI runner, container warm-up), can hit the 5s `timeout` and raise
`PoolTimeout` — a flaky failure unrelated to the invariant under test. Surface B's
`ThreadPoolExecutor(max_workers=N)` has the same exposure once its eight sync
requests each open a pooled connection.

**Fix:** Either drop `N` to `<= max_size` (e.g. `N = 5`) for the pool-bound
surfaces, or make the intent explicit and safe: raise the pool ceiling for the
proof (a test-scoped pool or env override) so N=8 real holders fit, and assert the
race under a pool that can actually hold them. Whichever is chosen, correct the
line-61 comment — it currently claims budget-safety that only holds under the
(unintended) serialized execution.

### WR-02: Surface A's `run_ids` set assertion can pass vacuously — it filters out `None`

**File:** `tests/test_concurrency_proof.py:190-194`
**Issue:**
`run_ids = {r.get("run_id") for r in results if r.get("run_id")}` drops every
response whose `run_id` is falsy/`None`, then asserts `len(run_ids) == 1`. The
duplicate-loser branch returns `{"status": "duplicate", "run_id": None}` whenever
`find_run_by_message_id` cannot resolve the winner's run yet (e.g. under a genuine
race where the winner's transaction has not committed at the instant the loser
looks it up — `app/main.py:399-401, 506`). Under real concurrency (post-CR-01),
several losers could legitimately return `run_id: None`; the filter silently
discards them, so `len({winner_run_id}) == 1` passes even if the duplicate-loser
lookup is broken and returns `None` every time. The assertion therefore proves
"the winner has one run_id," not "no duplicate loser fabricated a second run."

The DB `count(*) == 1` backstop at lines 206-213 is the real proof; the set
assertion adds false confidence. **Fix:** assert the loser shape explicitly rather
than filtering it away — e.g. `assert all(r["status"] in {"accepted","duplicate"}
for r in results)` and `assert len([r for r in results if r["status"]=="accepted"])
== 1`, and only then check that any non-null loser `run_id` equals the winner's.
Do not silently drop `None`.

### WR-03: Shared `TestClient` across threads assumes thread-safe reentrancy that Surfaces A/C never actually test

**File:** `tests/test_concurrency_proof.py:169, 177-186, 249, 254-257, 303, 308-312`
**Issue:**
All three surfaces share ONE `TestClient` instance across N threads. Starlette's
`TestClient` is backed by a single anyio portal + event loop; concurrent
`client.post` calls from multiple threads are funneled through that one portal.
For the sync `approve` route (Surface B) this is fine and genuinely parallel at the
*handler* level. But for the async `inbound` route (Surfaces A/C) the shared
portal is exactly what serializes the requests (see CR-01). This is a latent
correctness/observability hazard: the test *looks* concurrent (`threading.Thread`,
`ThreadPoolExecutor`) but the client layer collapses the concurrency for the async
surfaces. A reader will over-trust these tests.

**Fix:** Coupled to CR-01 — if the fix moves Surfaces A/C to a direct repo-seam
barrier, the shared-client concern disappears for them. If any surface keeps
per-thread HTTP, give each thread its own `TestClient(app_main.app)` and document
why (or accept the serialization and re-label the test as "sequential dedup
correctness," not a concurrency proof).

### WR-04: CI runs a destructive `bootstrap --reset` step that is fully redundant with the `seeded_db` fixture and is not guarded by `ALLOW_DB_RESET`

**File:** `.github/workflows/concurrency-proof.yml:43-44` and `app/db/bootstrap.py:76-135`
**Issue:**
The workflow step "Apply schema to ephemeral Postgres" runs
`uv run python -m app.db.bootstrap --reset`, which drops every table
(`_DROP_ORDER` CASCADE) against whatever `DATABASE_URL` points at. Two problems:
(1) it is redundant — the `seeded_db` fixture (`tests/conftest.py:58-74`) already
calls `bootstrap(reset=True)` + `seed()` at module scope, so the CI step's schema
is immediately dropped and re-applied by the first test anyway; (2) `bootstrap()`
honors only the `--reset` argv flag, **not** the `ALLOW_DB_RESET` env two-factor
guard that the test suite relies on. In this CI job the target is an ephemeral,
network-isolated container so there is no data-loss risk, but the pattern is
fragile: if this workflow (or a copy of it) is ever pointed at a `DATABASE_URL`
that is not ephemeral, the unguarded `--reset` step will drop production tables
with no second factor.

**Fix:** Delete the redundant bootstrap step (the fixture handles schema + seed),
or, if you want a fail-fast pre-flight, make it non-destructive
(`uv run python -m app.db.bootstrap` without `--reset`) and let the fixture own the
reset behind its `ALLOW_DB_RESET` guard.

## Info

### IN-01: Docstring claims contradict actual execution semantics

**File:** `tests/test_concurrency_proof.py:1-43, 154-157, 284-291`
**Issue:** Multiple docstrings assert "genuine OS-thread parallelism,"
"genuinely interleaves," "under genuine parallelism," and "Postgres MVCC under
genuine parallelism" for the async-route surfaces. Per CR-01 these are false for
Surfaces A and C. Even after CR-01 is fixed, prune the language to match what each
surface actually demonstrates so the capstone's "standing evidence" narrative is
accurate.
**Fix:** Align docstrings with the corrected execution model once CR-01 lands.

### IN-02: N is a bare magic constant coupling three tests to an unstated pool assumption

**File:** `tests/test_concurrency_proof.py:61`
**Issue:** `N = 8` is documented only by a comment that (per WR-01) is incorrect
about pool budget. The number is load-bearing for every assertion in the file and
is implicitly coupled to `max_size=5`. If the pool size changes, the comment goes
stale silently.
**Fix:** Derive or reference the pool bound explicitly (e.g. import `max_size` or
add an assertion `assert N >= 2`), and fix the comment so the relationship between
`N` and the pool ceiling is stated correctly rather than asserted incorrectly.

### IN-03: `deliver_calls` / `pipeline_calls` are plain lists appended from stubs — safe today only by accident

**File:** `tests/test_concurrency_proof.py:83-96, 179-180`
**Issue:** `pipeline_calls.append` / `deliver_calls.append` run from the stubs.
Surface B is safe because the CAS guarantees exactly one `_deliver` append. Surface
A appends once (one winner). Surface C appends N times, but all appends currently
happen on the single event-loop thread (background tasks for an async route),
so there is no data race *today* — again only because of the serialization in
CR-01. If CR-01 is fixed by moving to genuinely parallel OS threads that append to
these lists, `list.append` is CPython-atomic for the append itself but the
surrounding read-modify patterns (none here yet) would need care. Keep the
existing `threading.Lock` discipline (used for `results` in Surface A) consistently
if these collectors ever become genuinely multi-threaded.
**Fix:** When CR-01's fix introduces real parallel appends, guard shared collectors
with the same `lock` pattern already used at lines 175/179, or use a thread-safe
counter, for consistency and to avoid a future footgun.

---

_Reviewed: 2026-07-07T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
