---
phase: 15-comment-hygiene-deferred-polish-triage
plan: 03
subsystem: pipeline
tags: [comment-hygiene, docstrings, money-path, behavior-neutral]
status: complete

requires:
  - "app/pipeline/orchestrator.py (existing state machine)"
  - "app/pipeline/clarification.py (existing clarify cluster)"
  - "app/pipeline/delivery.py (existing confirmation delivery)"
provides:
  - "provenance-free pipeline orchestration with constraint comments intact"
  - "provenance-free clarification stage"
  - "provenance-free delivery stage at money-path comment depth"
affects: []

tech-stack:
  added: []
  patterns:
    - "AST-diff (docstrings stripped) as the behavior-neutrality proof for a comment-only sweep"

key-files:
  created: []
  modified:
    - app/pipeline/orchestrator.py
    - app/pipeline/clarification.py
    - app/pipeline/delivery.py

decisions:
  - "Algorithm-internal 'Phase 1/2/3' step labels in orchestrator.py were renumbered to '1./2./3.' — they described the detect→backfill→calc ordering, not project phases, but they tripped the `Phase [0-9]` gate regex. Renumbering keeps the ordering documented without a false-positive guard hit."
  - "Ticket IDs embedded in log-message string literals were stripped too. They are user-visible operator output, they trip the gate regex, and the rubric explicitly scopes the sweep to 'comment/docstring/string-literal text'. Nine log strings changed across the three files; no test asserts on them (suite green)."

metrics:
  duration: ~35 min
  completed: 2026-07-13
  tasks: 3
  files: 3
  gate_hits_before: 202
  gate_hits_after: 0
---

# Phase 15 Plan 03: Pipeline Comment Sweep Summary

Swept the three heaviest pipeline files clean of ticket-ID and project-process references while preserving — and in the money-path cases deepening — the constraint-plus-failure-mode documentation they carried.

## What Was Built

Three comment-only commits, one per file. No code moved, no symbol renamed, no test touched.

| Task | File | Gate hits before | after | Commit |
|------|------|-----------------|-------|--------|
| 1 | `app/pipeline/orchestrator.py` (1,045 lines) | 112 | 0 | `a00c585` |
| 2 | `app/pipeline/clarification.py` (478 lines) | 53 | 0 | `e5bfd52` |
| 3 | `app/pipeline/delivery.py` (233 lines) | 37 | 0 | `8b027d4` |

**Fresh manifest first.** Per the plan's review-LOW finding, hit counts were regenerated with the full gate regex at execution time rather than trusted from the discussion-time estimates. The real counts (112/53/37 = 202) ran ~35% higher than the sizing estimates in 15-CONTEXT.md (72/28/23 = 123), because the extended vocabulary (`Codex`, `HIGH-N`, `finding #N`, `R2-HIGH`, `Pitfall`, `PATTERNS.md`) matches many lines the base ticket regex misses. Work was driven off the fresh manifest.

**Module docstrings (COMM-03 / D-04).** Each of the three got a purpose statement plus a genuine invariants paragraph, no history and no TOC:
- `orchestrator.py` — the decision is code-owned (this module never branches on model output); data writes and status writes are separate (`set_status` is the sole status writer); no failure is silent; the run_id is never model-supplied.
- `clarification.py` — the LLM never decides here (the suggestion is advisory copy, wired strictly after the gate); state is written before the email goes out; no transaction spans an LLM/provider call; the run never strands.
- `delivery.py` — raise-don't-swallow; the sent guard is purpose-aware; the alias write precedes the status advance and is isolated; no transaction is held across the provider call.

**Money-path depth (D-02).** `delivery.py` is a named money-path file, and the gate comments in `orchestrator.py`/`clarification.py` are money-relevant. Every surviving comment states the constraint AND the consequence of violating it, in plain English with no ticket vocabulary. Representative examples of what was preserved (and sharpened) rather than trimmed:
- Why the two answered-field sets must stay distinct: putting `carried_forward` in the backfill-skip set pays 0 for a field the client said to carry forward (**underpay**); leaving `confirmed_dropped` out of it restores the snapshot's positive value over the client's explicit zero (**overpay**).
- Why classify must extract the reply **in isolation**: classifying from the combined body lets the original section's OT=2 eclipse the reply's "0 overtime" → labelled `client_supplied` with value 2 → overpay.
- Why detect must run **before** backfill: once backfill has papered over the drop, there is nothing left to detect and the client is never asked.
- Why the alias bind needs **same-record** evidence: the naive two-independent-facts diff would bind `Dave → David` from "No, Dave didn't work this period; David worked 5 hours separately" — a confirmation nobody gave.
- Why colliding tokens are excluded **at capture**: a captured collider is a latent mislearn that permanently misroutes a real person's pay.
- Why the `psycopg3` SAVEPOINT around the alias write matters: without it a DB-level failure poisons the outer transaction (`InFailedSqlTransaction` on the next statement), the status advance is lost, and a **successfully-emailed payroll is left stuck at `approved`**.
- Why the clarify idempotency guard is keyed on `(purpose, round)` and not purpose alone: purpose-only keying silently parks a genuinely-new round-2 question at `awaiting_reply` with no email ever sent — the run waits forever for a reply to a question nobody asked.

**Markers preserved.** `delivery.py` kept both `# noqa: BLE001` and its single `# type: ignore[attr-defined]` on their original lines; only the reason text was rewritten. `orchestrator.py` kept both its `# noqa: BLE001` markers. Counts verified unchanged before/after.

## Verification

All three plan gates green at the final commit:

```
uv run pytest -q   → 615 passed, 51 skipped   (0 assertion changes anywhere)
uv run ruff check  → All checks passed!
uv run mypy        → Success: no issues found in 114 source files
```

Strict mypy passing with `warn_unused_ignores` on is the proof no ignore marker was orphaned or relocated.

**Behavior-neutrality proof (stronger than the plan required).** The plan asked for "no executable-line changes in the diff". A line-level grep is weak evidence for a diff this large, so neutrality was proven structurally instead: for each file, the pre-sweep (HEAD) and post-sweep sources were parsed to an AST, module/class/function docstrings stripped, and the dumps diffed. Result for all three files: **identical, with the sole exception of nine log-message string literals** whose ticket suffixes were removed (e.g. `"...skipping duplicate send (finding #2, CLAR-04, D-11-01)"` → `"...skipping duplicate send"`). Those are in-scope per the rubric's "comment/docstring/string-literal text only" clause, they are operator-facing output that would otherwise leak ticket IDs, and the full suite is green against them.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `Phase 1/2/3` step labels tripped the gate regex**
- **Found during:** Task 1
- **Issue:** `orchestrator.py`'s three-phase ordering invariant (DETECT → BACKFILL → CALC) labelled its own steps "Phase 1 / Phase 2 / Phase 3". These are algorithm steps, not project phases — but the gate regex `Phase [0-9]` matches them, so the task's automated verify could never pass.
- **Fix:** Renumbered to `1. / 2. / 3.` The ordering stays fully documented (including why detect must precede backfill); only the word that collides with the guard vocabulary is gone.
- **Files modified:** `app/pipeline/orchestrator.py`
- **Commit:** `a00c585`
- **Note for plan 15-XX (the D-07 guard test):** the guard's `Phase [0-9]` pattern will false-positive on any legitimate prose using "Phase N" as a step label. D-08 already calls for tuning the regex for zero false positives against the final corpus — this is a concrete instance. A word-boundary/context-sensitive variant, or the capital-P-plus-planning-context form, would be safer.

**2. [Rule 3 - Blocking] E501 on a rewritten trailing comment**
- **Found during:** Task 1
- **Issue:** A rewritten inline comment pushed `repo.persist_decision(...)` to 101 chars (ruff limit 100).
- **Fix:** Shortened the comment ("status is written separately" → "status written separately"). Meaning unchanged.
- **Files modified:** `app/pipeline/orchestrator.py`
- **Commit:** `a00c585`

No Rule 4 (architectural) issues arose. No package installs. No authentication gates.

## Threat Flags

None. The plan's registered threat (T-15-04, "comment-only sweep of money-adjacent gate code must not alter behavior") is mitigated as specified: text-only diffs, AST-verified, unchanged suite + ruff + strict mypy green at every commit, all noqa/ignore markers pinned in place. No new security-relevant surface — no endpoints, auth paths, file access, or schema changes.

## Known Stubs

None.

## Self-Check: PASSED

- `app/pipeline/orchestrator.py` — FOUND
- `app/pipeline/clarification.py` — FOUND
- `app/pipeline/delivery.py` — FOUND
- `.planning/phases/15-comment-hygiene-deferred-polish-triage/15-03-SUMMARY.md` — FOUND
- Commit `a00c585` — FOUND
- Commit `e5bfd52` — FOUND
- Commit `8b027d4` — FOUND
