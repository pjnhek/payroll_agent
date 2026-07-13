---
phase: 15-comment-hygiene-deferred-polish-triage
plan: 08
requirements-completed: [COMM-01, COMM-03]
subsystem: tests
tags: [comment-hygiene, tests, sweep, gateway, threading, delivery, concurrency]
requires:
  - tests/ (the sixteen gateway/threading/validation/clarify/delivery/integration test files)
  - app/db/repo/emails.py (read-only — the live ON CONFLICT arbiter, verified against)
  - app/db/schema.sql (read-only — uq_email_run_purpose_round_epoch, verified against)
provides:
  - sixteen provenance-free test files (comments, docstrings, failure-message strings)
  - tests/test_bound01_private_imports.py — guard test swept, name + BOUND-01 refs + scanner logic intact
  - tests/test_delivery.py — outbound upsert arbiter now factually correct (4-column key)
affects:
  - plan 15-10 (copies test_bound01_private_imports.py's structure for the new comment guard)
tech-stack:
  added: []
  patterns:
    - "word-boundary-anchored gate regex (\\bD-[0-9]) so requirement IDs (BOUND-01, FOUND-04) survive the sweep"
key-files:
  created: []
  modified:
    - tests/test_gateway.py
    - tests/test_threading.py
    - tests/test_validate.py
    - tests/test_bound01_private_imports.py
    - tests/test_clarify.py
    - tests/test_delivery.py
    - tests/test_live_llm.py
    - tests/test_hitl.py
    - tests/test_eval_wiring.py
    - tests/test_concurrency_proof.py
    - tests/test_reconcile.py
    - tests/test_ingest.py
    - tests/test_status_drift.py
    - tests/test_gate.py
    - tests/test_demo_landing.py
    - tests/test_multi_employee_delivery.py
decisions:
  - "Gate regex needs word-boundary anchoring: the plan's literal `D-[0-9]` matches INSIDE requirement IDs (BOUN**D-0**1, FOUN**D-0**4), which the same plan mandates keeping. Used `\\bD-[0-9]`; residual raw hits are exactly BOUND-01 and FOUND-04."
  - "OPS2-03 and D-9-09 were REMOVED (not kept as requirement IDs): the plan's regex explicitly lists `OPS2?-[0-9]`, and only BOUND-01 is carved out by name in the acceptance criteria."
  - "test_delivery.py's arbiter comments were CORRECTED, not merely delabelled — a stripped-but-wrong comment reads as authoritative and is worse than a labelled one."
metrics:
  duration: ~1h
  completed: 2026-07-13
  tasks: 3
  commits: 3
  files-modified: 16
  suite: 615 passed / 51 skipped (identical to pre-sweep baseline)
status: complete
---

# Phase 15 Plan 08: Gateway/Threading/Delivery Test-Cluster Comment Sweep Summary

Sixteen test files swept clean of ticket-ID and process provenance under D-01/D-03 — and one factually-wrong comment cluster in `test_delivery.py` corrected against the live `ON CONFLICT` arbiter rather than merely delabelled.

## What Was Built

Comments, docstrings, and failure-message strings only. **Zero assertion changes** across all sixteen files: every changed `assert` line carries a byte-identical expression on both sides of the diff — only inline failure messages were reworded (verified mechanically, see Self-Check).

**Task 1** — `test_gateway.py`, `test_threading.py`, `test_validate.py`, `test_bound01_private_imports.py` (commit `5a4e470`)
- `test_gateway.py`: the entire "Phase 6 Wave 0 xfail stubs" section header was **stale as well as ticket-laden** — those tests carry no `xfail` marker any more. Replaced with a purpose statement instead of preserving a lie.
- `test_threading.py`: module docstring restated as the five re-entrancy invariants, each with the failure mode it prevents (a spoofed reply steering someone else's payroll; an answer-only reply zeroing out the hours).
- `test_validate.py`: money-relevant, so full D-02 depth kept — the overtime and paid-hours commentary now names the consequence (underpay of the OT premium; a silently-shipped $0 paystub the reconciliation backstop cannot catch, because $0 reconciles perfectly).
- `test_bound01_private_imports.py`: file name, all 5 `BOUND-01` references, `SCAN_ROOTS`, and every line of scanner logic **unchanged**. Its review-provenance prose was rewritten into the blind-spot constraints the code actually encodes (why the receiver walk must resolve nested `ast.Attribute` chains; why the package probe resolves against root *parents*).

**Task 2** — `test_clarify.py`, `test_delivery.py`, `test_live_llm.py`, `test_hitl.py`, `test_eval_wiring.py` (commit `04ebaec`)
- The `test_delivery.py` arbiter correction (below).
- All three `# type: ignore[attr-defined]` markers preserved **on their original lines** with plain-English reasons.

**Task 3** — `test_concurrency_proof.py`, `test_reconcile.py`, `test_ingest.py`, `test_status_drift.py`, `test_gate.py`, `test_demo_landing.py`, `test_multi_employee_delivery.py` (commit `8c9a926`)
- `test_concurrency_proof.py`: name unchanged (the CI workflow references it by filename). Its barrier-thread design rationale is the opposite of provenance — it is the reason the proof is not vacuous — so it was kept in full and sharpened: an HTTP fan-out version of Surfaces A/C **passes even with the `ON CONFLICT` clause deleted**, and `N_INGEST` must stay `<= max_size` or the test flakes on `PoolTimeout` instead of on the invariant.

## The One Correction (beyond the sweep)

`tests/test_delivery.py` described the outbound upsert arbiter as **`ON CONFLICT (run_id, purpose)`** in four places (module docstring, two test docstrings, two assertion failure-messages). That is the *pre-epoch* key.

Verified against live source before touching anything:
- `app/db/repo/emails.py:86` — `ON CONFLICT (run_id, purpose, round, epoch) DO UPDATE`
- `app/db/schema.sql:265` — `CONSTRAINT uq_email_run_purpose_round_epoch UNIQUE (run_id, purpose, round, epoch)`

All four sites now name the real four-column key **and state why `epoch` is in it**: a retrigger resets `clarification_round` to 0, so a fresh round-0 send has the same `(run_id, purpose, round)` tuple as the stale pre-retrigger row — on the narrower 3-column key it would silently UPSERT over an email that was already delivered, corrupting the append-only audit log. The comments now also point a maintainer at `tests/test_email_epoch_arbiter_integration.py` as the real-Postgres proof, since these `FakeConnection` substring assertions (`"ON CONFLICT" in sql.upper()`) structurally **cannot see a column list**.

Assertion expressions left byte-identical.

## Deviations from Plan

### [Rule 3 — Blocking] The plan's gate regex false-positives on the requirement IDs it mandates keeping

**Found during:** Task 1 verification.

**Issue:** The plan's `<verify>` regex contains `D-[0-9]`, which has no word-boundary anchor and therefore matches *inside* `BOUN**D-0**1` and `FOUN**D-0**4`. The same plan requires (`<acceptance_criteria>`) that `test_bound01_private_imports.py` "still contains BOUND-01 references". Both conditions cannot hold simultaneously.

**Fix:** Ran the gate word-boundary-anchored (`\bD-[0-9]`, `\bT-[0-9]+-[0-9]+`, etc.), which is what the sweep_rubric's intent states in prose ("Requirement IDs … are traceability, NOT review tickets — they are not guard-blocked"). Verified the residual raw-regex hits across all sixteen files are **exactly two strings**: `BOUND-01` and `FOUND-04`. Both are requirement IDs the plan explicitly protects.

**Note for plan 15-10:** the comment guard it builds must anchor its ticket patterns on word boundaries, or it will fail CI on every requirement ID ending in `D`.

### [Rule 1 — Judgment call] `OPS2-03` / `D-9-09` removed rather than kept as requirement IDs

`OPS2-03` *is* a v2 requirement ID, but the plan's gate regex explicitly enumerates `OPS2?-[0-9]`, and only `BOUND-01` is carved out by name in the acceptance criteria. Treated the explicit regex as authoritative and removed both from `test_concurrency_proof.py` prose (the surrounding constraint narrative was kept). No requirement traceability is lost — the file name and its CI workflow are the durable link.

## Observations (out of scope — logged, not fixed)

- **`app/db/repo/emails.py` carries an internally-contradictory docstring.** Its `insert_email_message` docstring says the upsert arbitrates on `uq_email_run_purpose_round` *(run_id, purpose, round)* in one paragraph (lines 34–46) and correctly on the four-column key in a later paragraph (lines 57–69). The *code* is correct. This is the same stale-arbiter class of error just fixed in `test_delivery.py`, and `app/db/repo/emails.py` is **not in this plan's file list** — it belongs to whichever plan owns the `app/db/` sweep. Flagging so it is not missed.
- `tests/test_delivery.py` (~line 330) contains a dead duplicate `client.post(...)` whose result is immediately overwritten. Left alone — removing it is a code change, outside this plan's text-only mandate.

## Verification

| Gate | Result |
|------|--------|
| Extended gate grep, all 16 files | **clean** (residual: `BOUND-01`, `FOUND-04` — both mandated) |
| `uv run pytest -q` | **615 passed, 51 skipped** — byte-identical to the pre-sweep baseline |
| `uv run ruff check` | All checks passed |
| `uv run mypy` | Success: no issues found in 114 source files |
| Assertion expressions unchanged | 4 changed `assert` lines, all with identical expressions (message-only edits) |
| `noqa` markers | 16 before / 16 after |
| `type: ignore` markers | 7 before / 7 after |
| `test_bound01_private_imports.py` name + BOUND-01 refs | intact (5 refs) |
| `test_concurrency_proof.py` name | intact (CI workflow references it) |

The 51 skips are the `integration` + `live_llm` tests, correctly auto-skipping in a worktree with no `.env`.

## Self-Check: PASSED

- All 16 modified files exist on disk.
- All 3 commits exist: `5a4e470`, `04ebaec`, `8c9a926`.
- Gate grep clean; suite/ruff/mypy green; test counts identical to baseline (proving behavior neutrality).
- No assertion or scanner logic changed (mechanically verified via `git diff` over `assert` lines).
</content>
</invoke>
