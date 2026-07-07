# Phase 10: Concurrency Proof - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-07
**Phase:** 10-concurrency-proof
**Areas discussed:** Deliverable shape, Run environment, Parallelism model, Approve-race level, Artifact form, Scale (N)

---

## Deliverable shape

| Option | Description | Selected |
|--------|-------------|----------|
| New unified proof harness | A single new test module firing all three surfaces + asserting all four invariants as one hiring-manager-pointable artifact; existing per-surface tests stay as units | ✓ |
| Formalize + extend existing | Fill gaps in existing per-surface tests + a thin index tying them together; no single artifact | |
| You decide | Delegated to Claude | |

**User's choice:** New unified proof harness
**Notes:** Matches ROADMAP's "the capstone deliverable: the artifact a hiring manager can point to" framing.

---

## Run environment

| Option | Description | Selected |
|--------|-------------|----------|
| CI job w/ ephemeral Postgres | GitHub Actions job spins up a service Postgres so the proof RUNS on every push — standing evidence, real caught regressions | ✓ |
| Local-only, documented | Keep it integration-marked/skip-guarded; document the local invocation; no CI wiring | |
| You decide | Delegated to Claude | |

**User's choice:** CI job with ephemeral Postgres
**Notes:** A skip-guarded test that never runs proves nothing — credibility of "fails loudly as a regression guard" depends on execution. Follows existing eval.yml pattern.

---

## Parallelism model

| Option | Description | Selected |
|--------|-------------|----------|
| Threads + real local Postgres | Reuse the proven ThreadPoolExecutor / real-Postgres / TestClient pattern; GIL irrelevant since contention is in the DB | ✓ |
| Multiprocessing | Separate processes to sidestep the GIL; heavier fixtures, harder connection sharing; overkill | |
| You decide | Delegated to Claude | |

**User's choice:** Threads + real local Postgres
**Notes:** The race is resolved in Postgres's MVCC, not Python — threads are sufficient and reuse existing infra.

---

## Approve-race level

| Option | Description | Selected |
|--------|-------------|----------|
| Through the HTTP /approve route | Two concurrent POSTs to /runs/{id}/approve — proves end-to-end (route → CAS → delivery); LLM/provider stubbed | ✓ |
| At the claim_status primitive | Race repo.claim_status directly (like the existing test) — simpler but misses route-level regressions | |
| You decide | Delegated to Claude | |

**User's choice:** Through the HTTP /approve route
**Notes:** Catches route-level double-approval bugs above the CAS; requires stubbing the LLM draft/suggestion + send so the race is the only thing under test.

---

## Artifact form

| Option | Description | Selected |
|--------|-------------|----------|
| Test + named-invariant assertions | The test module IS the proof — each invariant is a named test with an explanatory docstring; no separate report | ✓ |
| Test + a short PROOF.md writeup | Tests plus a committed markdown writeup; more recruiter-legible but a second artifact to keep in sync | |
| You decide | Delegated to Claude | |

**User's choice:** Test + named-invariant assertions
**Notes:** The code is the proof — matches the codebase's explain-the-why comment style; avoids drift from a separate report.

---

## Scale (N)

| Option | Description | Selected |
|--------|-------------|----------|
| Small fixed N (~5–10), deterministic | Enough to interleave and expose a broken invariant; fast, non-flaky, deterministic assertions | ✓ |
| Larger N (50–100) as a load flavor | Leans into "load" framing but risks pool exhaustion (max=5) + CI flakiness; not stronger proof | |
| You decide | Delegated to Claude | |

**User's choice:** Small fixed N (~5–10), deterministic
**Notes:** The invariant holds at any N≥2 (Postgres resolves it regardless of N); a small N keeps CI green and quick. Planner must respect the min=1/max=5 pool budget.

---

## Claude's Discretion

- Exact module/test/function names and internal organization of the three surfaces.
- Exact N per surface within the ~5–10 band.
- Whether the "concurrent runs" surface uses distinct parallel `message_id`s or reuses the dedup harness.
- CI workflow specifics (Postgres image/version, bootstrap reuse, single job vs. matrix) — follow eval.yml.
- Whether to also backfill test_claim_status.py with the HTTP-route approval race (capstone is the required home; backfill optional if trivially cheap).

## Deferred Ideas

- Guard-hardening the unguarded `set_status` writes against a swept-but-alive run (Phase 9's D-9-13 tension) — only if this proof shows the window matters in practice.
- Larger-N load/soak benchmark (throughput numbers) — rejected for the capstone as theater; its own out-of-band exercise if ever wanted for the writeup.
