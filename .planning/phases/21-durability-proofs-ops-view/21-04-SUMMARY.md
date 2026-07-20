---
phase: 21-durability-proofs-ops-view
plan: 04
subsystem: testing
tags: [pytest, ast-guard, durability-proof, webhook, dedup]

# Dependency graph
requires:
  - phase: 21-durability-proofs-ops-view
    provides: "21-01's registered proof(id=...) marker and 21-12's import-time _HAS_DB pattern"
provides:
  - "PROOF-02 identity on the audited same-Svix-redelivery test (tests/test_webhook_dedup_race.py::test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run)"
  - "An AST/dataflow guard (test_prefetch_dedup_key_derivation_guard) pinning REQUIREMENTS' named PROOF-02 vacuity condition structurally: external_event_id derives only from request.headers or the raw request body, and no provider-parse call precedes the durable-receipt handoff"
  - "Executed, published falsifying-mutation evidence for dedup-key stability (this document)"
affects: [21-10, 21-11]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "AST-over-source structural guards, mirroring tests/test_bound01_private_imports.py and tests/test_fake_repo_pairing.py: pure detection functions (_check_signed_path_derivation, _check_no_provider_parse_before_handoff) scanned against the live tree by one test, proven reachable against synthetic-source violations by companion tests, instead of a text/grep search that a comment could satisfy."
    - "Structural 'AST node position' ordering check (_preorder_positions) built from ast.iter_child_nodes traversal order, not from .lineno/.col_offset file-text coordinates — proves a call precedes/follows another call by tree structure alone."

key-files:
  created: []
  modified:
    - tests/test_webhook_dedup_race.py

key-decisions:
  - "The signed-path/ordering guard's reachability is proven via synthetic AST source strings (ast.parse on constructed snippets), not by literally mutating and reverting app/routes/webhook.py inside the committed test suite — matching tests/test_bound01_private_imports.py's test_scanner_detects_synthetic_violation idiom (tmp_path fixtures) and equally rigorous, since the check functions are pure over whatever AST they are given. A literal live-file mutate/observe/revert cycle was ALSO run manually during this session (see 'Guard reachability proof against the live file' below) to satisfy the acceptance criteria's literal instruction, but is not itself a committed artifact — the permanent regression coverage is the synthetic tests."
  - "The falsifying mutation targets the signed-path assignment only (str(uuid.uuid4()) replacing request.headers['svix-id']), leaving signature verification, the ON CONFLICT arbiter, and the ingest enqueue untouched — the plan's instruction to sever only dedup-key stability, nothing else."

requirements-completed: [PROOF-02]

coverage:
  - id: D1
    description: "PROOF-02 marker carries its id on exactly one test, and that test's four 'exactly one' assertions (inbound_events, jobs, payroll_runs, email_messages) are confirmed present"
    requirement: PROOF-02
    verification:
      - kind: unit
        ref: "uv run pytest tests/ -m \"proof(id='PROOF-02')\" --collect-only -q -> exactly 1 node id (test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run)"
        status: pass
      - kind: other
        ref: "grep -c 'pytest.mark.proof' tests/test_webhook_dedup_race.py -> 1"
        status: pass
    human_judgment: false
  - id: D2
    description: "The pre-fetch dedup-key property (REQUIREMENTS' named vacuity condition) is an executable AST/dataflow assertion, not prose, covering both the signed-path derivation's node structure and the no-parse-before-handoff ordering by AST position"
    requirement: PROOF-02
    verification:
      - kind: unit
        ref: "uv run pytest tests/test_webhook_dedup_race.py::test_prefetch_dedup_key_derivation_guard -v (hermetic, no DB) -> 1 passed"
        status: pass
      - kind: unit
        ref: "tests/test_webhook_dedup_race.py::test_signed_path_guard_reds_when_assignment_is_repointed -> synthetic violation reds the signed-path check"
        status: pass
      - kind: unit
        ref: "tests/test_webhook_dedup_race.py::test_ordering_guard_reds_when_provider_parse_precedes_handoff -> synthetic violation reds the ordering check"
        status: pass
      - kind: unit
        ref: "tests/test_webhook_dedup_race.py::test_ordering_guard_is_clean_when_no_provider_parse_seam_appears -> confirms no false positive"
        status: pass
      - kind: integration
        ref: "Manual live-file reachability proof: temporarily repointed app/routes/webhook.py:143 to a hardcoded constant, observed test_prefetch_dedup_key_derivation_guard red naming the offending expression, restored byte-identically (git diff --stat empty), re-ran green"
        status: pass
    human_judgment: false
  - id: D3
    description: "The dedup-key-stability falsifying mutation was executed live against real Postgres, produced the predicted response-status-set red, and was reverted byte-identically"
    requirement: PROOF-02
    verification:
      - kind: integration
        ref: "GREEN baseline: ALLOW_DB_RESET=1 uv run pytest tests/test_webhook_dedup_race.py -m \"proof(id='PROOF-02')\" -v -rs -> 1 passed, empty skip report, commit f7a7b2d4487a004aa3b877369a445b7192d0d807"
        status: pass
      - kind: integration
        ref: "RED: same command after mutating app/routes/webhook.py:143 to external_event_id = str(uuid.uuid4()) -> 1 failed at the response-status-set assertion (tests/test_webhook_dedup_race.py:296, {'accepted'} == {'accepted', 'duplicate'})"
        status: pass
      - kind: other
        ref: "git diff --stat app/routes/webhook.py after revert -> empty (byte-identical)"
        status: pass
      - kind: integration
        ref: "POST-REVERT green: same command -> 1 passed, empty skip report"
        status: pass
    human_judgment: false

# Metrics
duration: 40min
completed: 2026-07-20
status: complete
---

# Phase 21 Plan 04: Promote and Prove PROOF-02 — Same-Svix-Redelivery Dedup Summary

**Gave the audited same-Svix-redelivery test its PROOF-02 identity, closed REQUIREMENTS' named vacuity condition ("dedup keyed on something available only post-fetch") as an AST/dataflow guard over the live handler instead of prose, and executed the dedup-key-stability falsifying mutation live against real Postgres — red at the predicted response-status-set assertion, reverted byte-identically.**

## Performance

- **Duration:** 40 min
- **Started:** 2026-07-20 (this session)
- **Completed:** 2026-07-20
- **Tasks:** 2 (Task 2 produced no permanent diff — see below)
- **Files modified:** 1 (tests/test_webhook_dedup_race.py)

## Accomplishments

- Audited the incumbent `test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run` against ROADMAP criterion 2's exact wording: confirmed all four "exactly one" assertions were already present (one `inbound_events` row via `event_count == 1`, one `jobs` row via `len(job_rows) == 1`, one `email_messages` row via `email_row[1] == 1`, one `payroll_runs` row via `run_count == 1`). Per D-01, added nothing to the test body beyond the marker and its explanatory docstring.
- Added `@pytest.mark.proof(id="PROOF-02")` (keyword form) to that single test, stacked with its existing `integration`/`queueproof` markers.
- Built a new AST/dataflow companion test, `test_prefetch_dedup_key_derivation_guard`, that resolves two structural properties over the live `app/routes/webhook.py` `inbound` handler purely via `ast` (never a text/substring search):
  1. **Signed-path derivation.** Every assignment to `external_event_id` inside the handler is either the header-derived shape (`ast.Subscript` of `ast.Attribute(attr="headers")` on `ast.Name(id="request")`, keyed the constant `"svix-id"`) or the fixture-branch raw-body-digest shape (a call rooted at `hashlib`). Matched on the assignment's **value node structure**, not rendered source text.
  2. **No-parse-before-handoff ordering.** No call to a name in the enumerated `_PROVIDER_PARSE_SEAM_NAMES` set (`parse_inbound`, `process_inbound_event` — enumerated from live `app/email/gateway.py` and `app/queue/handlers/ingest.py`, not guessed) occupies an earlier **AST node position** (from a pre-order traversal via `ast.iter_child_nodes`, never `.lineno`) than the reference to the `_persist_verified_receipt_sync` durable-receipt handoff.
- Proved the guard's own detection logic is reachable, not dead code, via three companion tests against synthetic AST source (mirroring `tests/test_bound01_private_imports.py`'s `test_scanner_detects_synthetic_violation` idiom): one reds the signed-path check on a repointed assignment, one reds the ordering check on a provider-parse call inserted before the handoff, and one confirms the ordering check does not false-positive against an unrelated call.
- **Additionally**, beyond the committed synthetic tests, manually proved reachability against the actual live file this session: temporarily repointed `app/routes/webhook.py:143` to a hardcoded string constant, ran `test_prefetch_dedup_key_derivation_guard`, observed it red naming the exact offending expression and line, restored the file, confirmed `git diff --stat` was empty, and re-ran green. (See "Guard reachability proof against the live file" below.)
- Executed the dedup-key-stability falsifying mutation live against a real throwaway Postgres (`postgresql://pnhek@localhost:5432/pa_p21_04`): established a GREEN baseline, mutated `external_event_id`'s signed-path assignment to a per-delivery random value (`str(uuid.uuid4())`), observed the predicted RED at the response-status-set assertion, reverted byte-identically, and confirmed a clean re-run GREEN. Full output pasted below.

## Task Commits

1. **Task 1: Audit the incumbent, add the PROOF-02 identity, and assert the pre-fetch key property** - `f7a7b2d4487a004aa3b877369a445b7192d0d807` (feat)
2. **Task 2: Execute the dedup-key falsifying mutation live and capture the red run** - **no commit** (see "Task 2 produced no permanent diff" below)

**Plan metadata:** (this commit)

## Files Created/Modified

- `tests/test_webhook_dedup_race.py` — added `@pytest.mark.proof(id="PROOF-02")` and an explanatory docstring to the incumbent redelivery test; added `_check_signed_path_derivation`, `_check_no_provider_parse_before_handoff`, their supporting AST helpers (`_find_function`, `_is_signed_path_header_derivation`, `_is_raw_body_digest_derivation`, `_external_event_id_assignments`, `_preorder_positions`, `_call_target_name`), the live-source guard test `test_prefetch_dedup_key_derivation_guard`, and three synthetic-reachability tests.

## Task 2 produced no permanent diff

Task 2's action is entirely evidence-gathering: mutate `app/routes/webhook.py`, run the proof, capture the red, revert byte-identically, run the proof again to confirm green. The plan's own acceptance criteria require the revert to leave `git diff --stat app/routes/webhook.py` empty — confirmed. Since the file returns to its exact pre-mutation state and no other file changed during this task, there is nothing to stage or commit for Task 2; the evidence lives entirely in this SUMMARY, per the plan's `<output>` contract ("mutation diff, pasted red, byte-identical revert, named failing assertion, commit SHA, exact re-run command").

## Decisions Made

- **Guard reachability proved by synthetic AST source, not a permanent mutate/revert test.** The committed reachability proofs (`test_signed_path_guard_reds_when_assignment_is_repointed`, `test_ordering_guard_reds_when_provider_parse_precedes_handoff`, `test_ordering_guard_is_clean_when_no_provider_parse_seam_appears`) construct small synthetic handler source strings via `ast.parse` and run the same pure check functions against them, rather than editing and reverting the live `app/routes/webhook.py` as part of the test suite itself. This mirrors `tests/test_bound01_private_imports.py`'s established `test_scanner_detects_synthetic_violation` idiom (its own `tmp_path`-based synthetic-fixture form) and is equally rigorous — the check functions (`_check_signed_path_derivation`, `_check_no_provider_parse_before_handoff`) are pure functions of the AST they are given, so a synthetic tree exercises identical code paths to a mutated live file, without the stability/state risk of editing production source inside a test run. To additionally satisfy the plan's literal acceptance-criteria wording ("temporarily repoint that assignment... observe the guard red... restore"), a live-file mutate/observe/revert cycle was also run manually this session — documented below — but is not itself committed code.
- **Mutation touches only the signed-path assignment.** `external_event_id = request.headers["svix-id"]` → `external_event_id = str(uuid.uuid4())`. This severs only the dedup key's stability across a redelivery (each request independently mints a fresh random value even though both carry the identical `svix-id` header); signature verification, the `inbound_events` `ON CONFLICT (external_event_id) DO NOTHING` arbiter, and the ingest enqueue path are all untouched.

## Guard reachability proof against the live file

Run manually this session, in addition to (not instead of) the committed synthetic tests, to satisfy the plan's literal "temporarily repoint... observe... restore" acceptance-criteria wording:

```
$ grep -n 'external_event_id = request.headers\["svix-id"\]' app/routes/webhook.py
143:        external_event_id = request.headers["svix-id"]
```

Repointed line 143 to `external_event_id = "hardcoded-not-derived-from-headers"`, then:

```
$ env -u DATABASE_URL uv run pytest tests/test_webhook_dedup_race.py::test_prefetch_dedup_key_derivation_guard -v
...
E       AssertionError: PROOF-02 pre-fetch dedup-key guard violation(s) in .../app/routes/webhook.py:
E         line 143: 'external_event_id' is assigned from Constant(value='hardcoded-not-derived-from-headers'), which is neither request.headers['svix-id'] nor a raw-body digest — it may be reading a value only available after a provider fetch
E         no assignment derives 'external_event_id' from request.headers['svix-id'] — the signed-path pre-fetch derivation PROOF-02's vacuity condition requires is missing
tests/test_webhook_dedup_race.py:593: AssertionError
1 failed in 0.09s
```

Restored the file from a pre-mutation copy, then:

```
$ git diff --stat app/routes/webhook.py
(no output — byte-identical restore)

$ env -u DATABASE_URL uv run pytest tests/test_webhook_dedup_race.py::test_prefetch_dedup_key_derivation_guard -v
tests/test_webhook_dedup_race.py::test_prefetch_dedup_key_derivation_guard PASSED [100%]
1 passed in 0.06s
```

## PROOF-02 Falsifying Mutation — Publishable Evidence

**Claim falsified: dedup-key STABILITY.** This mutation does NOT falsify the REQUIREMENTS premise "dedup is keyed on something available only post-fetch (the RFC `Message-ID`)" — that structural premise is pinned by `test_prefetch_dedup_key_derivation_guard` (the AST/dataflow guard added in Task 1), which asserts `external_event_id` derives only from `request.headers`/the raw body and never from a fetched provider message. The mutation below is a narrower, separate claim: it proves that if the transport identity is not STABLE across a redelivery of the same event, the two-layer dedup arbiter no longer catches the duplicate. Publishing this mutation as though it falsified the `Message-ID` premise directly would overstate what it shows; it does not.

**Commit the mutation ran against:** `f7a7b2d4487a004aa3b877369a445b7192d0d807` (Task 1's commit, HEAD at mutation time).

**Mutation diff:**

```diff
--- a/app/routes/webhook.py
+++ b/app/routes/webhook.py
@@ -140,7 +140,7 @@ async def inbound(request: Request) -> JSONResponse:
                 status_code=400,
                 content={"error": "invalid signature"},
             )
-        external_event_id = request.headers["svix-id"]
+        external_event_id = str(uuid.uuid4())
         fixture_payload = False
     elif settings.allow_unsigned_fixtures:
         external_event_id = f"sha256:{hashlib.sha256(raw_body).hexdigest()}"
```

**GREEN baseline (pre-mutation), full command and output:**

```
$ ALLOW_DB_RESET=1 uv run pytest tests/test_webhook_dedup_race.py -m "proof(id='PROOF-02')" -v -rs
collected 6 items / 5 deselected / 1 selected
tests/test_webhook_dedup_race.py::test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run PASSED [100%]
1 passed, 5 deselected, 1 warning in 0.67s
```

No `SKIPPED` line — the empty `-rs` skip report confirms this was a real execution against Postgres, not a self-skip reading as a pass.

**RED (post-mutation), full pasted output:**

```
============================= test session starts ==============================
platform darwin -- Python 3.12.12, pytest-9.1.1, pluggy-1.6.0
collecting ... collected 6 items / 5 deselected / 1 selected

tests/test_webhook_dedup_race.py::test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run FAILED [100%]

=================================== FAILURES ===================================
____ test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run ____

monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x10b2c64b0>
seeded_db = None

    ...
    workers = [threading.Thread(target=_post) for _ in range(2)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    assert len(results) == 2
    assert {result["status_code"] for result in results} == {200}
>   assert {result["status"] for result in results} == {"accepted", "duplicate"}
E   AssertionError: assert {'accepted'} == {'accepted', 'duplicate'}
E
E   Extra items in the right set:
E   'duplicate'
E
E   Full diff:
E     {
E         'accepted',
E   -     'duplicate',
E     }

tests/test_webhook_dedup_race.py:296: AssertionError
---------------------------- Captured stdout setup -----------------------------
Bootstrap target: postgresql://pnhek@localhost:5432/pa_p21_04
RESET: dropping all tables in reverse dependency order — this is destructive
  DROP TABLE IF EXISTS name_matches CASCADE
  ... (full reset+seed output, unremarkable)
Bootstrap complete. Tables applied.
Seeded 3 businesses, 7 employees.
=============================== warnings summary ===============================
tests/test_webhook_dedup_race.py::test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run
  .../starlette/testclient.py:1: StarletteDeprecationWarning: Using `httpx` with `starlette.testclient` is deprecated; install `httpx2` instead.
-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
================== 1 failed, 5 deselected, 1 warning in 0.58s ==================
```

**Observed vs. predicted:** matches the plan's corrected prediction exactly. The named failing assertion is the **response-status-set assertion** (`tests/test_webhook_dedup_race.py:296`, `{result["status"] for result in results} == {"accepted", "duplicate"}`) — with a per-delivery identity, both concurrent deliveries independently insert (each gets a fresh random `external_event_id`, so the `ON CONFLICT (external_event_id)` arbiter never fires), so both responses come back `"accepted"` and the set assertion fails before execution reaches any `inbound_events`/`jobs`/`payroll_runs` count assertion. This is a genuine assertion failure originating in the PROOF-02 test — not a skip, collection error, or signature-verification error — confirming the mutation target is correct.

**Byte-identical revert confirmation:**

```
$ git diff --stat app/routes/webhook.py
(no output)
```

**Post-revert GREEN, full command and output:**

```
$ ALLOW_DB_RESET=1 uv run pytest tests/test_webhook_dedup_race.py -m "proof(id='PROOF-02')" -v -rs
collected 6 items / 5 deselected / 1 selected
tests/test_webhook_dedup_race.py::test_same_svix_redelivery_creates_one_event_one_ingest_job_and_one_run PASSED [100%]
1 passed, 5 deselected, 1 warning in 0.51s
```

**Exact re-run command:**

```
DATABASE_URL="postgresql://pnhek@localhost:5432/pa_p21_04" ALLOW_DB_RESET=1 ALLOW_UNSIGNED_FIXTURES=true \
  uv run pytest tests/test_webhook_dedup_race.py -m "proof(id='PROOF-02')" -v -rs
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Comment-provenance guard violations in the new guard's docstrings**
- **Found during:** Task 1's mandated verification (`uv run pytest -q`, full hermetic suite).
- **Issue:** The first draft of the new marker docstring and the `test_prefetch_dedup_key_derivation_guard` docstring cited a capital-P project-phase reference and a planning-document `.md` filename citation — both flagged by `tests/test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree`, the same class of violation `21-12-SUMMARY.md` already documented hitting once.
- **Fix:** Rewrote both passages in prose describing the constraint itself (the provider fetch runs inside the delayed ingest worker, never inline in the webhook request; a behavioural stability mutation is a separate, narrower claim than this guard) without citing the phase number or the summary filename.
- **Files modified:** tests/test_webhook_dedup_race.py
- **Verification:** `env -u DATABASE_URL uv run pytest -q` — 1216 passed, 104 skipped, 0 failed (comment-provenance guard included and green).
- **Committed in:** f7a7b2d4487a004aa3b877369a445b7192d0d807 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (a bug in this plan's own new docstrings, caught by the plan's own mandated hermetic-suite verification step).
**Impact on plan:** No scope creep — the fix only reworded two docstrings introduced by this plan's own Task 1; no production code (`app/`) was touched by the fix, and the guard's detection logic and test coverage were unaffected.

## Issues Encountered

Running `tests/test_webhook_dedup_race.py`'s two DB-touching tests together (before any change in this plan) showed one flaky failure on a single run (`test_duplicate_webhook_delivery_creates_exactly_one_run` — a different test, not PROOF-02's target, asserting `len(run_rows) == 1` and getting 0). Re-running both tests together immediately after passed cleanly, and each test passes reliably in isolation. This is pre-existing thread-timing flakiness in a test this plan does not modify or depend on (out of scope per the executor's scope boundary — logged here for the record, not fixed).

## User Setup Required

None — no external service configuration required. The throwaway Postgres database (`postgresql://pnhek@localhost:5432/pa_p21_04`) used for this plan's live-DB verification already existed in the worktree environment.

## Next Phase Readiness

- PROOF-02's marker, guard, and mutation evidence are all committed/documented and ready for plans 21-10 (registry) and 21-11 (publication) to consume.
- `uv run pytest tests/ -m "proof(id='PROOF-02')" --collect-only -q` collects exactly one test.
- `ALLOW_DB_RESET=1 uv run pytest tests/ -m queueproof -v -rs` is green (72 passed, 0 skipped) — up from the pre-plan baseline of 71 by exactly the one new guard test this plan added.
- Hermetic suite: 1216 passed, 104 skipped (baseline 1212 + 4 new hermetic-passing tests, 0 regression). `ruff check .` and `uv run mypy --strict app` both clean.
- Full live-DB suite (`-m "not live_llm"`): 1317 passed, 2 skipped, 1 deselected — no regression from the pre-plan baseline.
- `git status --porcelain app/routes/webhook.py` is empty; no residual mutation state.

---
*Phase: 21-durability-proofs-ops-view*
*Completed: 2026-07-20*

## Self-Check: PASSED

- FOUND: tests/test_webhook_dedup_race.py
- FOUND: .planning/phases/21-durability-proofs-ops-view/21-04-SUMMARY.md
- FOUND commit: f7a7b2d4487a004aa3b877369a445b7192d0d807 (Task 1)
