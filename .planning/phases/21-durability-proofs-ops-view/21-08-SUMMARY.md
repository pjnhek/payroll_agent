---
phase: 21-durability-proofs-ops-view
plan: 08
subsystem: testing
tags: [pytest, postgres, queue, concurrency-proof, threading-barrier, falsifying-mutation]

requires:
  - phase: 21-durability-proofs-ops-view
    provides: "21-13's repair of test_queue_durability.py back to -m queueproof green; 21-14's repair of test_concurrency_proof.py's deliver() stub signature"
provides:
  - "PROOF-04 identity (@pytest.mark.proof(id=\"PROOF-04\")) applied to a genuinely two-thread, barrier-released, distinct-connection reclaim-and-double-fence proof, replacing the single-threaded incumbent"
  - "A companion, deliberately UNORDERED test proving genuine temporal overlap of the two racing connections via intersecting time.monotonic_ns() intervals, plus the order-independent settlement invariant across both possible outcomes"
  - "Executed, evidenced falsification of the expired-lease reclaim clause against a real Postgres — mutation diff, red pytest output naming the exact assertion, byte-identical revert, and post-revert green all captured below"
affects: [21-09, 21-10, 21-11]

tech-stack:
  added: []
  patterns:
    - "A durability proof claiming genuine concurrency needs TWO tests, not one: an ORDERED test (barrier + Event) that reliably reaches the fenced state criterion 4 needs, and an UNORDERED companion (barrier only) that proves the two connections' DB calls actually overlapped via intersecting monotonic-clock brackets — conflating the two repeats the Phase-10 CR-01 vacuous-proof shape (thread count asserted with no overlap assertion)."
    - "Every 'this assertion is reachable' claim in an acceptance criterion was confirmed by a live scratch mutation (force a shared connection id; force a sleep-induced ordering) observed red in this session, then reverted — not asserted from inspection alone."
    - "The repo's comment-provenance guard (tests/test_comment_provenance_guard.py) also polices new test docstrings, not just production code: a bare 'D-04' or a review-shorthand citation like 'CR-01' in a new test docstring trips it exactly as it would in app/. State the constraint in prose; never cite the decision/review id that produced it."

key-files:
  created: []
  modified:
    - tests/test_queue_durability.py

key-decisions:
  - "Followed the plan's Codex-corrected structure exactly: the PROOF-04-tagged test stays ORDERED (barrier + threading.Event) so criterion 4's 'both writes fenced' assertions have a reliably-reachable target; a second, untagged companion test removes the Event and proves genuine overlap instead, asserting the order-independent invariant across both possible outcomes rather than a fixed one."
  - "The companion test's single raced DB call per thread is B's claim_job() vs A's complete_job() (not also fail_job()) — matching the plan's action text ('each thread brackets its DB call', singular) and keeping the overlap proof's two branches cleanly exhaustive (either the reclaim wins and A's stale write is fenced, or A's write lands first and B finds nothing to reclaim)."
  - "Confirmed both branches of the order-independent invariant occur in practice by running the companion test 10 times with -s: observed 'B's reclaim won' 3 times and 'A's write landed first' 7 times, all passing — not a hypothetical dual-branch design, an empirically exercised one."

requirements-completed: [PROOF-04]

coverage:
  - id: D1
    description: "test_expired_lease_is_reclaimed_by_a_second_worker_and_zombie_is_fenced_on_both_writes carries @pytest.mark.proof(id=\"PROOF-04\") as the sole node with that id, and also carries queueproof via the module-level pytestmark; the untagged companion test proves genuine overlap and is deliberately NOT proof-tagged (exactly one test per id)"
    requirement: PROOF-04
    verification:
      - kind: unit
        ref: "uv run pytest tests/ -m \"proof(id='PROOF-04')\" --collect-only -q -> 1 node id"
        status: pass
      - kind: unit
        ref: "uv run pytest tests/ -m proof --collect-only -q -> 4 node ids (PROOF-01..04, all four now present)"
        status: pass
      - kind: other
        ref: "uv run python scripts/check_proof_inventory.py -> exit 0 (was: 'PROOF id ''PROOF-04'' matched no test' before this plan)"
        status: pass
    human_judgment: false
  - id: D2
    description: "The reclaim and both zombie fences are driven from two real OS threads on two distinct psycopg connections, released by a threading.Barrier, never through an HTTP route or TestClient"
    requirement: PROOF-04
    verification:
      - kind: unit
        ref: "connection-identity assertion in both tests; confirmed reachable by temporarily forcing the same id() onto both threads and observing the exact assertion go red (pasted below), then reverting"
        status: pass
      - kind: unit
        ref: "grep -n 'TestClient' tests/test_queue_durability.py's PROOF-04 tests -> no match; both call app.db.repo functions directly"
        status: pass
    human_judgment: false
  - id: D3
    description: "The companion test proves genuine temporal overlap (not thread count) via intersecting time.monotonic_ns() brackets, and asserts the order-independent invariant across both outcomes"
    requirement: PROOF-04
    verification:
      - kind: unit
        ref: "overlap assertion confirmed reachable by temporarily inserting a 0.25s sleep in the zombie thread after the barrier and before its bracket, observing the exact interval-intersection assertion go red (pasted below), then reverting"
        status: pass
      - kind: unit
        ref: "10 consecutive runs with pytest -s: both branches ('B's reclaim won', 'A's write landed first') observed, 10/10 passed"
        status: pass
    human_judgment: false
  - id: D4
    description: "The falsifying mutation (drop the expired-lease OR clause from claim_job's WHERE) was executed live against a real Postgres, reddened the reclaim assertion by name (not a barrier timeout, not a skip), and was reverted byte-identically"
    requirement: PROOF-04
    verification:
      - kind: integration
        ref: "GREEN baseline -> mutation -> RED (assert reclaimed is not None, AssertionError: worker B must have reclaimed the expired lease / assert None is not None) -> byte-identical revert (git diff --stat app/db/repo/jobs.py empty) -> GREEN again; full transcript pasted below"
        status: pass
    human_judgment: false

duration: ~55min
completed: 2026-07-20
status: complete
---

# Phase 21 Plan 08: PROOF-04 — Genuine Two-Thread Race + Executed Reclaim-Clause Falsification Summary

**Replaced the two single-threaded PROOF-04 incumbents (each calling `claim_job()` twice from one test-body thread) with an ordered two-OS-thread proof that both zombie writes are fenced, plus a deliberately unordered companion that proves the two connections genuinely overlapped via intersecting monotonic-clock intervals — then executed the reclaim-clause falsifying mutation live, observed the named reclaim assertion go red, and reverted byte-identically.**

## Performance

- **Duration:** ~55 min
- **Tasks:** 2 of 2 complete (Task 2 produced no lasting source change — the mutation was reverted byte-identically, so there is nothing new to commit beyond Task 1's test rewrite)
- **Files modified:** 1 (`tests/test_queue_durability.py`)

## Accomplishments

### Task 1 — Rewrite both incumbents as genuine two-thread races (commit `895ad7d`)

Replaced `test_expired_lease_is_reclaimed` and `test_zombie_is_fenced_on_BOTH_complete_and_fail` (both single-threaded: `claim_job()` called twice sequentially from the test body, with a direct-SQL lease expiry in between) with two new tests:

1. **`test_expired_lease_is_reclaimed_by_a_second_worker_and_zombie_is_fenced_on_both_writes`** — tagged `@pytest.mark.proof(id="PROOF-04")`. Two real `threading.Thread`s, each opening its own `repo.get_connection()`, meet at a shared `threading.Barrier(2, timeout=30)`. Worker B (thread_b) then reclaims the expired lease via `repo.claim_job(conn=conn)` on its own connection and, once committed, signals a `threading.Event`. Worker A (thread_a) — the zombie, still holding the original stale `lease_token` — waits on that event and only then issues a late `repo.complete_job(...)` **and** a late `repo.fail_job(...)`, both against its own connection. Assertions cover all three parts of ROADMAP criterion 4 as independently named checks: the reclaim minted a new token, `complete_job`'s fence returned `False`, `fail_job`'s fence returned `None` ("the fence people forget", asserted separately from `complete_job`'s), and the final row state/lease-token/attempts reflect only worker B's action. The docstring states explicitly, in its own "WHAT THIS TEST DOES NOT ESTABLISH" section, that the barrier-plus-event structure proves two live workers but not that their writes ever overlapped in time — that claim belongs to the companion test.

2. **`test_expired_lease_reclaim_and_zombie_write_genuinely_race`** — untagged (exactly one test carries `id="PROOF-04"`). Same barrier-released two-thread structure, but with the `threading.Event` and all other happen-before removed: after the barrier, worker B's `claim_job()` and worker A's `complete_job()` (using the pre-expiry stale token) race for real. Each thread brackets its single DB call with `time.monotonic_ns()` readings; the test asserts the two `[start, end]` intervals **intersect** — proof of genuine overlap, not inferred from thread count. It then asserts the **order-independent invariant** across both legitimate outcomes: either B's reclaim wins (A's stale write is fenced, row ends `leased` under B's token) or A's write lands first (B's claim finds nothing eligible, row ends `done`) — and asserts the forbidden "both settlements took effect" state is impossible in either branch. Which branch actually occurred is recorded via `print()` (visible under `pytest -s`).

Thread variables are named `thread_a`/`thread_b` (ordered test) and `thread_reclaim`/`thread_zombie` (companion test) — never `worker` — so the module's static `worker.start()` AST guard (`test_every_worker_start_call_goes_through_the_live_worker_wrapper`) is neither tripped nor evaded. Confirmed unchanged: `git diff tests/test_queue_durability.py` shows no change inside that function, and it still passes.

A comment-provenance-guard violation was introduced mid-task and fixed before committing: two docstring sentences cited `D-04` and `Phase-10 CR-01` directly (this repo's `tests/test_comment_provenance_guard.py` forbids citing the decision/review id that produced a constraint — state the constraint, drop the label). Rewritten to describe the requirement and the vacuous-proof shape in prose. Guard re-verified green before Task 1's commit.

### Task 2 — Execute the reclaim-clause falsifying mutation live (no commit — reverted byte-identical)

**GREEN baseline** (commit `895ad7d`, before mutation):

```
tests/test_queue_durability.py::test_expired_lease_is_reclaimed_by_a_second_worker_and_zombie_is_fenced_on_both_writes PASSED [100%]
======================= 1 passed, 57 deselected in 0.33s =======================
```
`-rs` skip report: empty.

`grep -n "OR (c.state"` against `app/db/repo/jobs.py` first, to confirm the mutation target before touching it: line 411 is a docstring copy of the clause inside `claim_job`'s own docstring; line 443 is the live executable SQL inside the `UPDATE ... WHERE j.id = (SELECT ... WHERE ...)` subquery. Only line 443 was mutated.

**Mutation diff** (against commit `895ad7d`):

```diff
--- a/app/db/repo/jobs.py
+++ b/app/db/repo/jobs.py
@@ -440,7 +440,6 @@ def claim_job(
                         WHERE c.attempts < c.max_attempts
                           AND (
                                 (c.state = 'pending' AND c.available_at <= now())
-                             OR (c.state = 'leased'  AND c.leased_until <  now())
                               )
                         ORDER BY c.priority, c.available_at
                         FOR UPDATE SKIP LOCKED
```

**RED run (with mutation applied) — full pytest output:**

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.1.1, pluggy-1.6.0
collecting ... collected 58 items / 57 deselected / 1 selected

tests/test_queue_durability.py::test_expired_lease_is_reclaimed_by_a_second_worker_and_zombie_is_fenced_on_both_writes FAILED [100%]

=================================== FAILURES ===================================
_ test_expired_lease_is_reclaimed_by_a_second_worker_and_zombie_is_fenced_on_both_writes _

    ... (setup steps 1-2 pass: enqueue, initial claim by the test-body thread,
    direct-SQL lease expiry) ...

    thread_b.join(timeout=35)
    thread_a.join(timeout=35)

    assert not thread_b.is_alive(), "worker B did not finish its reclaim"
    assert not thread_a.is_alive(), "worker A did not finish its late writes"
    assert errors["thread_b"] == [], f"worker B raised: {errors['thread_b']}"
    assert errors["thread_a"] == [], f"worker A raised: {errors['thread_a']}"
    assert sorted(barrier_passes) == ["thread_a", "thread_b"]

    # Separate workers: distinct connections. Necessary, not sufficient, for
    # genuine contention (see docstring) — the overlap claim lives in the
    # companion test below.
    assert connection_ids["thread_a"] != connection_ids["thread_b"]

    reclaimed = results["reclaimed"]
>       assert reclaimed is not None, "worker B must have reclaimed the expired lease"
E       AssertionError: worker B must have reclaimed the expired lease
E       assert None is not None

tests/test_queue_durability.py:2499: AssertionError
---------------------------- Captured stdout setup -----------------------------
Bootstrap target: postgresql://pnhek@localhost:5432/pa_p21_08
RESET: dropping all tables in reverse dependency order — this is destructive
  ... (bootstrap DROP/ALTER lines, unchanged from baseline) ...
Bootstrap complete. Tables applied.
Seeded 3 businesses, 7 employees.
======================= 1 failed, 57 deselected in 0.42s =======================
```

**Named failing assertion:** the **reclaim assertion**, `assert reclaimed is not None, "worker B must have reclaimed the expired lease"` — exactly the target D-05 names ("the original claim SQL that cannot reclaim a `leased` row"). Confirmed this is NOT a `BrokenBarrierError`, NOT a thread timeout, NOT a skip, NOT a collection error: `errors["thread_b"] == []` and `errors["thread_a"] == []` both passed cleanly (thread B's reclaim call itself raised nothing — `claim_job()` legitimately returned `None` because the mutated WHERE clause no longer matches any `leased`+expired row), the barrier was reached by both threads (`sorted(barrier_passes) == ["thread_a", "thread_b"]` passed), and thread A's own late writes never even ran (the test failed before reaching them, at `reclaimed is not None`) — the mutation's effect propagated exactly to the assertion it should, with no upstream noise.

**Byte-identical revert confirmation:** `git checkout -- app/db/repo/jobs.py`; `git diff --stat app/db/repo/jobs.py` produced no output.

**Post-revert GREEN run:**

```
tests/test_queue_durability.py::test_expired_lease_is_reclaimed_by_a_second_worker_and_zombie_is_fenced_on_both_writes PASSED [100%]
======================= 1 passed, 57 deselected in 0.32s =======================
```
`-rs` skip report: empty. `git status --short` clean.

**Exact re-run command for the full cycle:**

```bash
export DATABASE_URL="postgresql://<local-throwaway-db>"
export ALLOW_DB_RESET=1
uv run python -m app.db.bootstrap
uv run pytest tests/test_queue_durability.py -m "proof(id='PROOF-04')" -v -rs   # GREEN baseline
# apply the diff above to app/db/repo/jobs.py
uv run pytest tests/test_queue_durability.py -m "proof(id='PROOF-04')" -v -rs   # RED
git checkout -- app/db/repo/jobs.py                                            # byte-identical revert
uv run pytest tests/test_queue_durability.py -m "proof(id='PROOF-04')" -v -rs   # GREEN again
```

**Commit SHA the mutation ran against:** `895ad7d1cc34706e04feb4d3b9a4041cd00d7066` (Task 1's commit, this plan). This mutation was executed freshly in Phase 21, not inherited from the module docstring's own falsifying-mutation inventory entry (a) — which already named this exact mutation from before this plan touched the file, but had never been re-run against the new two-thread proof this plan introduces.

## Reachability checks for the two "must be provably reachable" acceptance criteria

Both were confirmed live in this session, as scratch (uncommitted) edits, run, observed red, then reverted — never landed in a commit:

1. **Distinct-connection assertion (ordered test).** Temporarily inserted `connection_ids["thread_a"] = connection_ids["thread_b"]` immediately before the equality assertion. Result: `assert 4429287296 != 4429287296` — the exact assertion failed as expected. Reverted.

2. **Overlap-intersection assertion (companion test).** Temporarily inserted `time.sleep(0.25)` in the zombie thread's body, immediately after `barrier.wait()` and before its `time.monotonic_ns()` bracket start. Result: `assert (1037418439815333 <= 1037418703055791 and 1037418699944750 <= 1037418440196875)` — the exact interval-intersection assertion failed (the delayed thread's interval started after the other thread's had already ended). Reverted.

Both edits were made directly in `tests/test_queue_durability.py`, run, confirmed via `ruff check` + the targeted test after reverting, and `git diff` was inspected to confirm the file matched the intended (non-mutated) state before Task 1's commit.

## Task Commits

1. **Task 1: Rewrite both incumbents as genuine two-thread races** - `895ad7d` (feat)
2. **Task 2: Execute the reclaim-clause falsifying mutation live** - no commit (mutation applied and reverted byte-identically within this task; `git diff --stat app/db/repo/jobs.py` is empty at task end, so there is nothing to stage)

## Files Created/Modified

- `tests/test_queue_durability.py` — replaced the two single-threaded PROOF-04 incumbents with a genuinely two-OS-thread, barrier-released ordered proof (`@pytest.mark.proof(id="PROOF-04")`) plus an untagged unordered companion proving genuine overlap and the order-independent settlement invariant.

## Decisions Made

- Kept the PROOF-04-tagged test deterministic (barrier + Event) per the plan's Codex-corrected structure, rather than trying to make the tagged test itself prove overlap — an enforced happen-before and a genuine-race claim are mutually exclusive properties of the same test.
- The companion test races exactly one DB call per thread (`claim_job` vs `complete_job`), not all three writes — this keeps its two branches cleanly exhaustive and matches the plan's "brackets its DB call" (singular) wording; `fail_job`'s fence is covered by the ordered test instead, where it can be asserted as a reliably-reached, independently-named check.
- Chose to prove the companion test's dual-outcome design empirically (10 consecutive runs, both branches observed) rather than asserting it works from code inspection alone.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Comment-provenance-guard violation introduced mid-task**
- **Found during:** Task 1's own hermetic verification run, before committing
- **Issue:** two new docstring sentences cited `D-04` and `Phase-10 CR-01` directly — patterns this repo's `tests/test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree` CI gate explicitly forbids (a decision-id or review-ticket citation instead of stating the constraint in prose).
- **Fix:** rewrote both sentences to describe the requirement ("two real OS threads on separate connections, released by a barrier") and the vacuous-proof shape ("thread count asserted with no overlap assertion... let a prior concurrency proof in this repo serialize through a shared TestClient and still pass") without citing the decision or review id that produced either constraint.
- **Files modified:** `tests/test_queue_durability.py`
- **Verification:** `tests/test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree` passes; full hermetic suite re-run clean (1251 passed, 105 skipped, matching the documented baseline exactly).
- **Committed in:** `895ad7d` (Task 1 commit — folded in before the commit, not a separate commit)

---

**Total deviations:** 1 auto-fixed (1 blocking guard violation). No scope creep — confined to the plan's declared file, and necessary for the plan's own new docstrings to comply with an existing repo-wide CI gate.

## Issues Encountered

None blocking beyond the deviation above.

## Full-Suite Verification (post-plan, confirms no regression)

- `ALLOW_DB_RESET=1 uv run pytest tests/ -m queueproof -v -rs` → **73 passed, 1283 deselected, 0 skipped** (matches the documented current baseline of 73 exactly — net zero change: 2 tests replaced by 2 tests).
- `uv run pytest tests/ -m "proof(id='PROOF-04')" --collect-only -q` → **1 node id** (the ordered test only; the companion is untagged as required).
- `uv run pytest tests/ -m proof --collect-only -q` → **4 node ids** — PROOF-01, PROOF-02, PROOF-03, PROOF-04 all present exactly once, for the first time in this phase.
- `uv run python scripts/check_proof_inventory.py` → **exit 0** (was failing with `PROOF id 'PROOF-04' matched no test` before this plan; now passes with all four proofs accounted for).
- `ALLOW_DB_RESET=1 uv run pytest tests/test_concurrency_proof.py -k exactly_one_wins -v -rs` → **1 passed, 0 skipped** — plan 21-14's repair of this test is untouched and still green.
- `grep -c 'pytest.mark.proof' tests/test_queue_durability.py` → **2** (PROOF-01 from plan 21-03, plus PROOF-04 from this plan).
- `env -u DATABASE_URL uv run pytest -q` (hermetic) → **1251 passed, 105 skipped** (matches the documented current baseline exactly, including the comment-provenance-guard fix landing before this measurement).
- `ALLOW_DB_RESET=1 uv run pytest tests/ -q -rf` (full live-DB) → **1353 passed, 3 skipped** (matches the documented current baseline exactly).
- `uv run ruff check .` → All checks passed.
- `uv run mypy --strict app` → Success: no issues found in 74 source files.
- `git status --porcelain app/db/repo/jobs.py` → empty (no production source change survives this plan).
- `uv run pytest tests/test_queue_durability.py -k worker_start_call -v` → passes unchanged; `git diff tests/test_queue_durability.py` shows no change inside `test_every_worker_start_call_goes_through_the_live_worker_wrapper`.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

- PROOF-04's identity, its two-test structure (ordered fence proof + unordered overlap proof), and this SUMMARY's mutation evidence are ready for plan 21-09 (CI wiring of `check_proof_inventory.py` and/or the AST mutation-target guard) and plan 21-11 (`docs/DURABILITY-PROOFS.md` publication). The "Reachability checks" section above and the "Mutation Evidence" section are written to be cited/consumed directly.
- All four PROOF ids (PROOF-01..04) now collect exactly once under the CI-executed `queueproof and proof(id=...)` intersection; `scripts/check_proof_inventory.py` — the selection-layer completeness gate plan 21-09 will wire into CI — passes end to end for the first time in this phase.
- No production code changes survive this plan: `app/db/repo/jobs.py` is byte-identical to before Task 2's mutation.

## Self-Check: PASSED

- FOUND: tests/test_queue_durability.py
- FOUND: commit 895ad7d1cc34706e04feb4d3b9a4041cd00d7066

---
*Phase: 21-durability-proofs-ops-view*
*Completed: 2026-07-20*
