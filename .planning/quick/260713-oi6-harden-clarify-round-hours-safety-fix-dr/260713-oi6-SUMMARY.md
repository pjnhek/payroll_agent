---
phase: quick-260713-oi6
plan: 01
subsystem: pipeline
status: complete
tags: [money-path, clarification, alias-learning, validate, operator-gate, tdd]
requirements-completed: [QUICK-260713-oi6]
dependency-graph:
  requires:
    - app/pipeline/alias_learning.bind_evidence_for_token  # the evidence standard, reused verbatim
    - app/pipeline/validate.is_paid                        # the one shared paid? predicate
    - payroll_runs.alias_candidates                        # {token: {suggested, bound}}, written pre-send
  provides:
    - app/pipeline/alias_learning.confirmed_prior_matches  # the identity bridge
    - app/pipeline/validate.detect_hours_changes           # display-only paid->paid detector
    - app/pipeline/validate._pair_by_employee_id           # the ONE shared id-keyed pairing
    - app/models/contracts.HoursChange                     # the type wall (no issue_type)
    - app/db/repo.set_hours_changes                        # unconditional data-only write
    - payroll_runs.hours_changes                           # nullable JSONB
  affects:
    - app/pipeline/orchestrator._run_stages                # +1 kwarg, +2 calls inside `if prior is not None:`
    - app/templates/run_detail.html                        # the operator banner
tech-stack:
  added: []   # ZERO new dependencies
  patterns:
    - "Repair the DATA (prior_matches), not each CONSUMER — one identity map, three consumers."
    - "Enforce a display-only boundary with a TYPE (no issue_type), not with discipline."
    - "Write [] unconditionally so stale state is structurally impossible, not merely absent."
key-files:
  created:
    - tests/test_clarify_round_hours_safety.py
    - tests/test_detect_hours_changes.py
  modified:
    - app/pipeline/alias_learning.py
    - app/pipeline/orchestrator.py
    - app/pipeline/validate.py
    - app/models/contracts.py
    - app/db/schema.sql
    - app/db/repo/runs.py
    - app/db/repo/pipeline_state.py
    - app/db/repo/__init__.py
    - app/templates/run_detail.html
    - tests/conftest.py
    - tests/test_threading.py
decisions:
  - "The identity bridge binds ONLY on bind_evidence_for_token's same-record evidence. The LLM proposes; the deterministic resolver over the roster confirms. This is the same evidence standard already trusted to PERMANENTLY write an alias to the roster — a strictly higher-stakes act than diffing two hours values, so reusing it here is strictly weaker-stakes."
  - "The bridge is applied to prior_matches ITSELF, once, inside `if prior is not None:` — not seeded per-consumer. The defect was a missing IDENTITY, so the identity map is what gets repaired. Three consumers (detect_field_regression, detect_hours_changes, backfill_extracted) inherit one map and structurally cannot disagree about who the snapshot employee is."
  - "A cross-round paid->paid CHANGE stays DISPLAY-ONLY. The accumulation design (a client's correction wins and is PAID without re-asking) is deliberate and stands; the gap was that the approving human could not SEE the change. HoursChange has no issue_type, so it cannot become a ValidationIssue and cannot reach decide(). decide.py is byte-identical."
  - "hours_changes is written UNCONDITIONALLY (as [] when empty) on every run and every resume, and cleared by clear_reply_context. A stale change record from a dead attempt would invite an operator to approve numbers on the strength of it."
metrics:
  duration: ~35 min
  tasks: 3
  files: 13
  tests-added: 15
  completed: 2026-07-13
---

# Quick Task 260713-oi6: Harden Clarify-Round Hours Safety Summary

**The clarified employee was invisible to the drop detector, and a changed hours value was invisible to the human — both are now closed, one by code, one by the operator's eyes.**

## What Shipped

### 1. The bug (live run e6fa8643) — a dropped hours line now clarifies

`detect_field_regression` builds its ORIGINAL-side identity map from `prior_matches`
filtered to `resolved`. The employee a NAME clarification is about was **unresolved in
the prior round by definition** — that is *why* we asked. So the snapshot employee was
**structurally invisible** to the detector: "Sandy 20r/10ot" → "Yes, Sandra Kim, 40
regular" dropped the overtime line, no drop was seen, backfill silently restored the 10
hours, and the run went straight to AWAITING_APPROVAL with an unasked question about
someone's money.

The missing thing was an **identity**, so the fix repairs `prior_matches` itself rather
than patching each consumer: `alias_learning.confirmed_prior_matches` (pure — no DB, no
LLM) bridges the clarified employee in, reusing `bind_evidence_for_token` **verbatim**.
Applied **once**, inside `_run_stages`'s existing `if prior is not None:` block, so one
augmented list feeds all three consumers.

Two tempting bridges were rejected on the evidence, not on taste:
- **Re-reconciling the prior token** fails outright — `write_aliases_if_safe` runs at the
  *approval* gate, so at resume time "Sandy" is still absent from `known_aliases`.
- **Whole-run set-difference** is forbidden — it is exactly the two-independent-facts
  inference `bind_evidence_for_token` exists to reject ("No, Dave didn't work; David
  worked 5 hours separately" would bind a match the client **denied**).

Guards, each skipping the seed: UUID parse, roster membership, **collision** (an id
already mapped by a `resolved` prior entry is authoritative and wins), and token reuse.

### 2. The gap — a changed hours value is now shown to the operator

A cross-round **paid→paid** change (regular 20→40, overtime 10→2) is invisible to the
drop detector *by design*, and that design is right: the accumulation contract says a
client's correction **wins and is PAID without re-asking** (interrogating a client about
their own correction is what `tests/test_multiround_context_edge.py` exists to prevent).
The real gap was that the human *approving* the payroll never saw the change happen.

`detect_hours_changes` now records it, `payroll_runs.hours_changes` persists it, and an
independent banner on the run-detail page renders it at the approval gate — with
`final_action` still `"process"` and **no new gate reason**.

The display-only boundary is enforced by the **type**, not by discipline: `HoursChange`
has no `issue_type`, so it cannot be constructed into a `ValidationIssue` and cannot
reach `decide()`.

### 3. DRY — one pairing, two detectors

The id-keyed pairing `detect_field_regression` already performed is extracted to a single
`_pair_by_employee_id` (over `_id_keyed`). Two copies could drift on the resolved-filter,
the last-wins rule, or the ordering — and the two detectors would then disagree about who
the snapshot employee is, over the same money. `detect_field_regression` is a **pure
refactor**: its signature, no-op branch, emitted values and ordering are unchanged, proven
by `tests/test_detect_field_regression.py` passing with **zero edits**.

## Task Commits

| Task | Commit | What |
|------|--------|------|
| 1 | `eace91f` | `confirmed_prior_matches` (the identity bridge) + orchestrator wiring + 3 RED-first tests |
| 2 | `02816b4` | `HoursChange` + `_pair_by_employee_id` + `detect_hours_changes` + 9 RED-first unit tests |
| 3 | `43ed368` | `hours_changes` column, `set_hours_changes`, operator banner, the three fakes + 3 RED-first tests |

## TDD Evidence (every test was RED first, for the right reason)

- **Test 1 (the bug)** failed with `got 'awaiting_approval'` — the run silently paying,
  exactly the live defect.
- **Test 2 (the collision guard)** is a red-proof that can only fire *after* the bridge
  exists. Per the plan, the bridge was added, the guard was then **temporarily disabled**,
  and Test 2 went red with the spurious `field regression: Sandra Kim.hours_overtime`
  (the last-entry-wins collapse firing a drop that never happened). The guard was
  restored and the test went green.
- **Test 3 (the denial)** passes pre- and post-change by construction: it asserts the
  bridge does **not** fire, and it is the guard against a future weakening of the evidence
  standard.
- **Tests 4/5/6** failed on the missing `hours_changes` (`ImportError`, then a planted
  stale record surviving).
- `detect_hours_changes` tests failed at collection (`ImportError: cannot import name
  'HoursChange'`).

## Verification (all gates green)

| Gate | Result |
|------|--------|
| `uv run pytest -q` | **644 passed, 52 skipped** |
| `git diff --stat app/pipeline/decide.py` (vs pre-plan) | **EMPTY** — no new gate rule, no new issue_type |
| `git diff tests/test_multiround_context_edge.py` (vs pre-plan) | **EMPTY** — the accumulation contract is untouched |
| `detect_field_regression` signature | **byte-identical** (diffed against pre-plan source; `eval/run_eval.py`'s 4-arg positional call is safe) |
| `uv run ruff check .` | All checks passed |
| `uv run mypy` | Success: no issues found in 119 source files |
| `grep -c '"set_hours_changes"' tests/test_threading.py` | **2** (both tuples — the silent-failure gate) |
| `grep -c '"set_hours_changes"' tests/conftest.py` | **1** |

**Manual trace of e6fa8643 against merged source:** reply drops the OT line → the bridge
resolves "Sandy" → `detect_field_regression` sees `10 → None` → `field_regression` →
`request_clarification` (Test 1). Reply *changes* the OT line → `10 → 2` is paid→paid, so
the drop detector is silent, `detect_hours_changes` records it, `final_action` stays
`process`, `gate_reasons == []`, and the paystub pays **40 / 2** — the client's numbers,
not the snapshot's (Test 4, asserting the PAID VALUE, not just the label).

## Deviations from Plan

**One, cosmetic and named loudly rather than buried:**

**Task 1, Test 3 — "James Ruiz" does not exist in the seed roster.** The plan's deny-case
scenario names a different employee "James Ruiz" for the reply to resolve instead of
Sandra Kim. There is no James Ruiz in `app/db/seed.py`. Sandra Kim is Business 3
(`b0000003`), whose only other employee is **Thomas Bergmann** (`e0000005`), so the test
uses him. The *behavior* under test is unchanged and unweakened — the reply resolves a
**different employee**, no reconciliation record ties the token (or Sandra's canonical
`full_name`) to the suggested id, `bind_evidence_for_token` returns False, and no bridge
occurs. Bergmann is salaried, which also keeps the scenario clean of an unrelated
missing-hours issue.

No other deviations. `decide.py`, `tests/test_multiround_context_edge.py` and
`detect_field_regression`'s signature are all provably untouched; no package was
installed; no architectural change was needed.

**Incidental hardening (not in the plan, kept anyway):** Test 6 plants a *stale*
`hours_changes` record before resuming and demands it be gone. The plan only asked that a
no-change run persist `[]`. Planting the stale value is what actually proves the
unconditional write, rather than proving the value merely happened to be absent.

## Known Stubs

None. No placeholder values, no unwired data paths. The banner renders a persisted
pipeline-computed fact; the column is populated on every run and every resume.

## Threat Flags

None. No new network endpoint, no new auth path, no new file access. The one new
client-derived string rendered to the operator (`submitted_name`) goes through Jinja
autoescaping with `{{ }}` only — never `| safe` — and that name is already rendered
elsewhere on the same page, so there is no new PII surface. Zero new dependencies.

## Self-Check: PASSED

Files verified present on disk: `app/pipeline/alias_learning.py` (`confirmed_prior_matches`),
`app/pipeline/validate.py` (`_pair_by_employee_id`, `detect_hours_changes`),
`app/models/contracts.py` (`HoursChange`), `app/db/schema.sql` (`hours_changes` in both the
CREATE body and the ALTER block), `app/db/repo/pipeline_state.py` (`set_hours_changes`),
`app/templates/run_detail.html` (the banner), `tests/test_clarify_round_hours_safety.py`,
`tests/test_detect_hours_changes.py`.

Commits verified in `git log`: `eace91f`, `02816b4`, `43ed368`.
