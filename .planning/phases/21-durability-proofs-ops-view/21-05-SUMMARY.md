---
phase: 21-durability-proofs-ops-view
plan: 05
subsystem: testing
tags: [live-postgres, concurrency-proof, exactly-once-send, idempotency-key, queue-durability, delivery]

# Dependency graph
requires:
  - phase: 21-durability-proofs-ops-view
    provides: "The `proof(id=...)` marker (21-01) and the reserve->settle outbound contract + resend mock hazard warning (21-14) this proof builds on"
provides:
  - "PROOF-03: the one durability proof with no incumbent coverage — a worker crashing between Resend accepting a send and the local `sent` commit sends no second email, proven against a real Postgres with three named teeth asserted on persisted values (byte-identical message_id, exact provider-call counts, identical Idempotency-Key)"
  - "The two-independent-lease correction from cross-AI review (Codex): Half A (job lease expired, handoff owner lease still active) proves the app-level fence structurally refuses a second call; Half B (both leases expired) proves a genuine replay reaches the provider safely because its identity is unchanged"
  - "Executed, observed-red, byte-identical-reverted falsification evidence for the pre-Phase-20 send path (a freshly-minted-per-attempt Idempotency-Key), satisfying ROADMAP criterion 3's non-vacuity requirement"
affects: [21-11]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Crash-between-accept-and-commit simulated by wrapping the real settle_outbound_delivery_job in a test-owned `repo.get_connection()` + `conn.transaction()` and raising before that transaction commits — an injected-seam failure against a real Postgres, not a hard connection kill, so the proof is deterministic under a shared CI Postgres."
    - "Two-lease reclaim staged explicitly as two separate SQL UPDATE statements (jobs.leased_until alone for half A; jobs.leased_until + outbound_provider_handoffs.owner_leased_until together for half B), each followed by its own repo.claim_job() + repo.authorize_outbound_provider_handoff() call, rather than a single combined expiry — the split is the test's whole point."

key-files:
  created: []
  modified:
    - tests/test_send_idempotency.py

key-decisions:
  - "Followed the plan's Codex-corrected two-half design exactly: half A predeclares count=1 (structural fence refusal, asserted by its own reason `active_handoff_unexpired`), half B predeclares count=2 (genuine replay, safe because the Idempotency-Key is unchanged) — never a single 'assert >=1, decide after observing' assertion."
  - "Chose mutation candidate (i) — freshly-minted-per-attempt Idempotency-Key at the gateway provider seam (app/email/gateway.py:167) — over candidate (ii) (dropping reserve_outbound_snapshot's ON CONFLICT clause), because this test's replay mechanism never calls reserve_outbound_snapshot a second time (it re-authorizes the ALREADY-frozen snapshot via the handoff adoption path), so candidate (ii) would have had zero effect and produced a false pass, not a genuine red."
  - "Drove the crash and both replay attempts through the individual repo functions (`claim_job`, `authorize_outbound_provider_handoff`, `gateway.send_reserved_outbound_snapshot`, `settle_outbound_delivery_job`) rather than `drain.drain_once()`, mirroring the established idiom in tests/test_queue_durability.py's own worker-crash proof (`test_retrigger_survives_worker_crash_mid_lease`'s explicit 'NEVER drain_once() here' note) — drain_once() runs a handler to completion and cannot stop mid-lease at the exact injection point this proof needs."

requirements-completed: [PROOF-03]

coverage:
  - id: D1
    description: "PROOF-03 exists as a live-Postgres test asserting the three named teeth (byte-identical message_id, exact provider-call counts predeclared at 1 and 2, identical Idempotency-Key), split into a fence-refusal half and a genuine-replay half per the two-independent-lease correction, collected uniquely by the proof(id='PROOF-03') marker expression and also selected by -m queueproof"
    requirement: "PROOF-03"
    verification:
      - kind: integration
        ref: "tests/test_send_idempotency.py::test_crash_between_provider_accept_and_local_sent_commit_sends_no_second_email"
        status: pass
    human_judgment: false

duration: ~45min
completed: 2026-07-20
status: complete
---

# Phase 21 Plan 05: Crash-Between-Accept-and-Commit Durability Proof (PROOF-03) Summary

**A new live-Postgres proof for the one durability claim with no incumbent test — a worker crashing between Resend's provider-accept and the local `sent` commit sends no second email — with three teeth asserted on persisted values and a falsifying mutation executed, observed red, and byte-identically reverted in this session.**

## Performance

- **Duration:** ~45 min
- **Tasks:** 2 of 2 complete
- **Files modified:** 1 (tests/test_send_idempotency.py)

## Accomplishments

- Added `test_crash_between_provider_accept_and_local_sent_commit_sends_no_second_email` to `tests/test_send_idempotency.py`, carrying `@_SKIP_LIVE_DB`, `@pytest.mark.integration`, `@pytest.mark.queueproof`, and `@pytest.mark.proof(id="PROOF-03")` — the only node id selected by `-m "proof(id='PROOF-03')"`.
- Seeds a run through `APPROVED` with a frozen `confirmation` reservation (`repo.reserve_outbound_snapshot`) and its `SEND_OUTBOUND` job, capturing the frozen `message_id` before any send.
- **Attempt 1:** claims the job, authorizes the provider handoff, sends via a gateway double patched on `resend.Emails.send` (correct two-argument signature — the exact hazard flagged from plan 21-14's wave-0 finding), then simulates the crash by calling the real `settle_outbound_delivery_job(job, result, conn=crash_conn)` inside a test-owned `repo.get_connection()` + `conn.transaction()` and raising before that transaction commits. Confirmed after the rollback: the reservation is still `reserved`, the handoff is still active (`released_at IS NULL`), the job is still `leased`, and the `message_id` is unchanged.
- **Half A** (job lease expired only): reclaims the job via a fresh `claim_job()`, confirms the handoff's own `owner_leased_until` is still active by direct SQL read, and asserts `authorize_outbound_provider_handoff` returns `ProviderHandoffActive(reason="active_handoff_unexpired")` — the app-level fence refuses the second attempt before the provider is ever called. Provider-call count asserted as the exact integer `1`.
- **Half B** (both `jobs.leased_until` and `outbound_provider_handoffs.owner_leased_until` expired): reclaims a second time, confirms the SAME handoff row is adopted (not recreated — `authorization3.handoff_id == authorization1.handoff_id`), and drives a genuine second send. Provider-call count asserted as the exact integer `2`. Both calls' Idempotency-Keys are asserted equal to each other AND equal to the one `message_id` captured before attempt 1. Settlement completes to `SettlementOutcome.DONE`, the run reaches `RECONCILED`, and exactly one `email_messages` row for this run/purpose/epoch reaches `send_state = 'sent'`.
- Confirmed the byte-identical `message_id` assertion is reachable by temporarily inverting it to `!=` locally, observing the genuine red (`AssertionError: assert '<proof03-...>' != '<proof03-...>'`), then reverting.
- Executed the falsifying mutation live (Task 2, below), confirmed the RED, and byte-identically reverted.

## Task Commits

1. **Task 1: Build the crash-between-accept-and-commit proof** - `9796bdc` (test)
2. **Task 2: Execute the pre-Phase-20-send-path mutation live and capture the red run** - no commit (the mutation was applied and reverted within this session; `git diff --stat app/email/gateway.py app/db/repo/emails.py` is empty — see falsification evidence below)

## Files Created/Modified

- `tests/test_send_idempotency.py` — added `test_crash_between_provider_accept_and_local_sent_commit_sends_no_second_email` (PROOF-03) and its `import resend` at module scope

## Falsification Evidence (D-05, non-vacuity)

**GREEN baseline** (commit `9796bdc`, `HEAD` at the time of mutation):

```
ALLOW_DB_RESET=1 uv run pytest tests/test_send_idempotency.py -m "proof(id='PROOF-03')" -v -rs
tests/test_send_idempotency.py::test_crash_between_provider_accept_and_local_sent_commit_sends_no_second_email PASSED [100%]
1 passed, 41 deselected in 0.34s
```

**Mutation candidate chosen: (i) — freshly-minted Idempotency-Key at the provider seam.**

Not candidate (ii) (dropping `reserve_outbound_snapshot`'s `ON CONFLICT (run_id, purpose, round, epoch) DO NOTHING`): this proof's replay never calls `reserve_outbound_snapshot` a second time — the replay re-authorizes the ALREADY-frozen snapshot through the handoff-adoption path (`authorize_outbound_provider_handoff`'s adopt-UPDATE), so mutating the reservation's conflict clause would have zero effect on this test and would produce a false, meaningless pass rather than a genuine red.

**Mutation diff** (`app/email/gateway.py`, one line, at the `resend.Emails.send` call site the plan named — confirmed via `grep -n` on live source before mutating, not a docstring copy):

```diff
-        resend.Emails.send(send_params, {"idempotency_key": message_id})
+        resend.Emails.send(send_params, {"idempotency_key": str(uuid.uuid4())})
```

**RED output** (full, `ALLOW_DB_RESET=1 uv run pytest tests/test_send_idempotency.py -m "proof(id='PROOF-03')" -v -rs`):

```
tests/test_send_idempotency.py::test_crash_between_provider_accept_and_local_sent_commit_sends_no_second_email FAILED [100%]

=================================== FAILURES ===================================
_ test_crash_between_provider_accept_and_local_sent_commit_sends_no_second_email _
...
        # TEETH 1 + 2: every recorded provider call, across BOTH halves, carries
        # an Idempotency-Key equal to the ONE message_id captured before attempt 1.
>       assert provider_calls[0]["idempotency_key"] == captured_message_id
E       AssertionError: assert '72039660-c2b...-82f260abe8b6' == '<proof03-eda...-agent.local>'
E
E         - <proof03-edacf629-b505-4b68-b93e-104a1d206ef3@payroll-agent.local>
E         + 72039660-c2b2-4818-a7e9-82f260abe8b6

tests/test_send_idempotency.py:872: AssertionError
======================= 1 failed, 41 deselected in 0.43s =======================
```

**Named failing assertion:** `provider_calls[0]["idempotency_key"] == captured_message_id` — teeth 2, the identical-Idempotency-Key assertion, comparing two genuinely differing identity strings (a fresh per-attempt random UUID vs. the one frozen `message_id`). Not a skip, not a collection error, not an unrelated database error — a direct falsification of the exact non-vacuity property REQUIREMENTS names.

**Byte-identical revert confirmation:**

```
$ git diff --stat app/email/gateway.py app/db/repo/emails.py
(no output)
```

**Post-revert re-run** (`ALLOW_DB_RESET=1 uv run pytest tests/test_send_idempotency.py -m "proof(id='PROOF-03')" -v -rs`): `1 passed, 41 deselected in 0.34s`, empty skip report.

**Commit SHA the mutation ran against:** `9796bdc017113e01a18a8366bdc38d3cf9eba85a`

**Exact re-run command:** `ALLOW_DB_RESET=1 uv run pytest tests/test_send_idempotency.py -m "proof(id='PROOF-03')" -v -rs`

## Decisions Made

- See `key-decisions` in frontmatter — mutation-candidate choice, two-half design fidelity, and the individual-repo-function drive mechanism (not `drain.drain_once()`).

## Deviations from Plan

None — plan executed exactly as written, including the Codex-corrected two-half design already baked into the plan text.

## Issues Encountered

None. `app/queue/drain.py` was read to confirm the crash-simulation seam claim (the settlement call at `drain.py:247` sits outside any try/except in the success branch, so an exception there propagates straight out of `drain_once()`) — confirmed in live source, matching the plan's `<read_first>` citation.

## User Setup Required

None.

## Next Phase Readiness

- PROOF-03 is live, unique under `proof(id='PROOF-03')`, and selected by `-m queueproof` (72 passed, 0 skipped — baseline 71 + this one).
- Hermetic suite: 1212 passed, 105 skipped (baseline 1212/104 — the +1 skip is this new test's own `_SKIP_LIVE_DB` guard firing under the hermetic run with no `DATABASE_URL`, not a regression).
- `ruff check .` clean; `uv run mypy --strict app` clean (73 source files); `uv run mypy --strict tests/test_send_idempotency.py` clean.
- `git status --porcelain app/email/gateway.py app/db/repo/emails.py` is empty at plan end.
- Plan 21-11 can publish PROOF-03's two distinct claims (half A's structural-fence-refusal count=1, half B's genuine-replay count=2 with identity preserved) as separate evidence, per the plan's `<output>` instruction.

---
*Phase: 21-durability-proofs-ops-view*
*Completed: 2026-07-20*

## Self-Check: PASSED

- FOUND: tests/test_send_idempotency.py::test_crash_between_provider_accept_and_local_sent_commit_sends_no_second_email
- FOUND: commit `9796bdc` (Task 1)
- FOUND: `.planning/phases/21-durability-proofs-ops-view/21-05-SUMMARY.md`
