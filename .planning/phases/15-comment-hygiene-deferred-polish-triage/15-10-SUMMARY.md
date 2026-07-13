---
phase: 15-comment-hygiene-deferred-polish-triage
plan: 10
requirements-completed: [COMM-01, POLISH-01]
subsystem: test-guard + planning-hygiene
tags: [comment-provenance, ci-guard, static-scanner, todo-closure, milestone-closeout]
status: complete

requires:
  - all ten sibling sweep plans (15-01..15-09, 15-11) — the guard can only be green on a swept tree
provides:
  - permanent CI-riding comment-provenance guard (3 tests, no ci.yml change)
  - an executable, machine-readable record of what is and is not guard-enforced
  - closed todo 260623-01 with a per-item disposition for all seven findings
affects:
  - every future commit touching app/, eval/, scripts/, tests/, schema.sql, templates, stylesheet

tech-stack:
  added: []
  patterns:
    - "static text scanner as a pytest gate, modeled on tests/test_bound01_private_imports.py"
    - "two-directional pattern table: every enforced shape proven to FIRE, every excluded shape proven SILENT"

key-files:
  created:
    - tests/test_comment_provenance_guard.py
    - .planning/todos/completed/260623-01-phase05-review-warnings.md
  modified:
    - app/db/repo/demo.py
    - app/db/seed.py
    - tests/test_dashboard.py
    - tests/test_demo_landing.py
    - tests/test_federal_withholding.py
    - tests/test_models_contracts.py
    - tests/test_orchestrator_states.py
    - tests/test_persistence.py
    - tests/test_seed_roundtrip.py
    - tests/test_status_drift.py
  deleted:
    - .planning/todos/pending/260623-01-phase05-review-warnings.md

decisions:
  - "The decision-ID pattern is word-boundary anchored (\\bD-...). Unanchored, it matches INSIDE BOUND-01 and FOUND-04 — the guard would fail CI on the very requirement IDs it must protect."
  - "'Phase N' stays enforced even though it is textually indistinguishable from an algorithm-step label. The two are not distinguishable, and only one is legitimate; the sanctioned way to enumerate steps is to number them, which is unambiguous and survives a renumbered roadmap."
  - "No bypass/escape-hatch marker was added. An opt-out used zero times is a hole waiting to be used to silence the gate."
  - "RESEARCH.md citations are editorial-only, not enforced: the tax tests cite it as the derivation record for the transcribed IRS bracket numbers — a correctness citation of the same class as the irs.gov ones."

metrics:
  duration: ~35 min
  completed: 2026-07-13
  tasks: 2
  commits: 3
  files_changed: 13
---

# Phase 15 Plan 10: Comment-Provenance Guard + Milestone Closeout Summary

COMM-01 is now an executable invariant rather than an asserted one: a 3-test pytest guard rides the
existing CI job, scans 124 files across the whole swept surface, and proves both that it fires and
that it stays silent where it should. POLISH-01 is closed with a per-item disposition record whose
every claim was re-verified against live source.

## What Was Built

**Task 1 — `tests/test_comment_provenance_guard.py`** (commits `d8442e7` guard, `ac2eaf9` sweep).

Three entry points, because a guard is only as trustworthy as its own proof:

| Test | Proves |
|------|--------|
| `test_no_ticket_provenance_in_source_tree` | the live tree is clean (the permanent gate); emits the machine-readable scan record |
| `test_scanner_flags_every_blocked_shape_and_passes_legitimate_prose` | the scanner FIRES — every one of the 13 enforced rows is exercised against a synthetic sample, and legitimate prose is proven not to trip it |
| `test_editorial_only_shapes_are_not_guard_enforced` | the scanner is SILENT on every documented exclusion — each `EDITORIAL_ONLY_PATTERNS` example is first checked to genuinely BE an instance of its own shape, so a mismatched example cannot make an entry vacuously pass |

**Task 2 — todo 260623-01 closed** (commit `0b790fc`) with all seven findings dispositioned.

## Required Recordings

### The machine-readable scan record (verbatim, from the live gate's stdout)

```
COMMENT-PROVENANCE SCAN RECORD
files_scanned: 124
enforced_patterns: 13
  enforced  decision-id          \bD-(?:[0-9]|[A-Z][0-9])[0-9A-Za-z.\-]*   # a design-decision citation (D-04, D-11-01, D-7.5-08, D-A3-05)
  enforced  review-ticket        \b(?:WR|CR|CX|GAP|R2|NEW|OPS[0-9]*)-[0-9]   # a review or gap ticket ID (WR-01, CR-02, CX-03, GAP-2, R2-1, OPS2-01)
  enforced  fix-ticket           \bFIX[ -](?:[0-9]|[A-Z]\b)   # a numbered or lettered fix ID (FIX-5, FIX C)
  enforced  pitfall-ref          \bPitfall\s*#?\s*[0-9]   # a citation of a numbered pitfall in a planning document
  enforced  review-fix-phrase    (?i)\breview fix\b   # the phrase that attributes code to a review round instead of stating its reason
  enforced  phase-ref            \bPhase [0-9]   # a capital-P project-phase reference (number the steps instead)
  enforced  task-id              \bT-[0-9]+-[0-9]+   # a threat-model or task ID (T-8-07, T-15-01)
  enforced  severity-label       \b(?:HIGH|MEDIUM|LOW)-[0-9]|\bR[0-9]-(?:HIGH|MEDIUM|LOW)\b   # a review-finding severity label (LOW-6, HIGH-2, R2-MEDIUM)
  enforced  reviewer-name        (?i)\bcodex\b   # the name of a review tool, which explains provenance rather than code
  enforced  uat-ref              \bUAT\s*#\s*[0-9]   # a citation of a numbered acceptance-test item
  enforced  finding-ref          (?i)\bfinding\s*#\s*[0-9]   # a citation of a numbered review finding
  enforced  ui-spec-ref          \bUI-SPEC\b   # a citation of the UI design contract document
  enforced  planning-doc-ref     \b(?:PATTERNS|CONTEXT|REQUIREMENTS|ROADMAP|UI-SPEC|PLAN|SUMMARY|REVIEW|DISCUSSION-LOG|VERIFICATION|SKELETON|AI-SPEC)\.md\b   # a citation of a planning document the reader of this code does not have
editorial_only_patterns: 4
  excluded  requirement-id       \b[A-Z]{4,}-[0-9]{2}\b   # Requirement IDs are LIVE traceability into the requirements register, not decayed history; they must never trip the gate.
  excluded  research-derivation-citation \bRESEARCH\.md\b   # The tax tests cite the research note as the DERIVATION RECORD for the transcribed 2026 IRS bracket numbers -- a correctness citation of the same class as the irs.gov ones, deliberately kept.
  excluded  suppression-code     #\s*(?:noqa|type:\s*ignore)   # A noqa/type-ignore code plus its mandatory plain-English reason is a live instruction to the linter, not provenance.
  excluded  external-source-citation \b(?:irs|ssa)\.gov\b   # An external authority for a money constant is exactly the kind of citation a reader CAN act on; the sweep preserved every one.
```

### Extended-vocabulary zero-false-positive evaluation

Every shape the plan named was scanned against the live tree before being admitted. **Eleven of the
thirteen enforced shapes had zero hits.** Two shapes had hits, and both turned out to be **genuine
stragglers, not false positives** — so the extended vocabulary went into the table in full, and the
tree was swept to match. Nothing was dropped for breadth.

The only shape that produced a *true* false positive was the planning-doc filename family: six
`RESEARCH.md` citations in the tax tests. Those are the derivation record for the transcribed 2026
IRS bracket numbers — a correctness citation of the same class as the `irs.gov` ones that plan 15-07
deliberately preserved. So `RESEARCH.md` was split out into `EDITORIAL_ONLY_PATTERNS`, and the rest
of the planning-doc family (`PATTERNS`/`CONTEXT`/`REQUIREMENTS`/`ROADMAP`/`PLAN`/`SUMMARY`/`REVIEW`/…)
is enforced.

### The stragglers the sweep regexes could not see (23 hits, 10 files)

| Shape | Hits | Why the earlier sweeps missed it |
|-------|------|----------------------------------|
| `D-A3-05`, `D-A1-03` | 4 | the base `D-[0-9]` pattern cannot match a decision ID whose block starts with a **letter** |
| `Finding #N` | 11 | not in the per-plan gate regexes at all |
| `Review fix #2`, `review Fix 5`, `Review fix (codex MEDIUM #5)` | 4 | the gate regex matched only the *parenthesized* form |
| `LOW-6` | 4 | severity labels were never in the sweep vocabulary |

All 23 rewritten under the keep-the-constraint-drop-the-label rubric. Comment, docstring, and
failure-message text only. Exactly **one** `assert` line appears in the diff, and it changed its
**message**, not its condition:

```
-    assert run["status"] == "error", "a stage raise must route to ERROR (D-A1-03)"
+    assert run["status"] == "error", "a stage raise must route to ERROR"
```

### The guard is proven capable of failing

Not merely asserted — demonstrated three ways:

1. **On first run it was RED** on the 23 real stragglers above, while both synthetic tests were
   already green. It found live rot on its very first execution.
2. **Deliberate injection.** A planted comment (`# Planted for the failure-capability proof
   (CR-02 / Phase 9 / D-11-01).`) appended to `app/config.py` turned the gate red with a precise
   `app/config.py:78: [decision-id]` hit. Reverted; back to green.
3. **The synthetic self-test** exercises every one of the 13 rows individually, so a row that rots
   into a never-matching regex fails a test rather than silently weakening the gate.

### False-positive fixtures (the ones that would have broken CI)

- **`BOUND-01` / `FOUND-04`** — proven both synthetically *and live*: **14 requirement-ID references
  (BOUND-01, FOUND-04, HITL-02) survive on the scanned tree with the gate green.** Without the `\b`
  anchor, `D-[0-9]` matches inside `BOUN`**`D-0`**`1` and `FOUN`**`D-0`**`4`, and the guard would
  have failed CI on the exact traceability the phase mandates keeping.
- **Algorithm-step prose** — the legitimate-prose fixture pins the sanctioned form the orchestrator
  now uses (`# 1. detect the reply round. 2. backfill the roster. 3. calculate.`), plus lowercase
  "this phase of parsing" / "both phases", `noqa` and `type: ignore` codes, and `irs.gov` citations.
  All scan clean.

### Post-straggler second scan (independent of the guard)

After the last straggler-fix commit, both guard entry points were re-run green **and** an independent
full-vocabulary grep was run over the D-05 file set:

```bash
grep -rEn --include='*.py' --include='*.sql' --include='*.html' --include='*.css' --include='*.md' \
 -e '\bD-([0-9]|[A-Z][0-9])' -e '\b(WR|CR|CX|GAP|R2|NEW|OPS[0-9]*)-[0-9]' -e '\bFIX[ -]([0-9]|[A-Z]\b)' \
 -e '\bPitfall *#? *[0-9]' -e '[Rr]eview [Ff]ix' -e '\bPhase [0-9]' -e '\bT-[0-9]+-[0-9]+' \
 -e '\b(HIGH|MEDIUM|LOW)-[0-9]' -e '\bR[0-9]-(HIGH|MEDIUM|LOW)\b' -e '[Cc]odex' -e '\bUAT *# *[0-9]' \
 -e '[Ff]inding *# *[0-9]' -e '\bUI-SPEC\b' \
 -e '\b(PATTERNS|CONTEXT|REQUIREMENTS|ROADMAP|PLAN|SUMMARY|REVIEW)\.md\b' \
 app eval scripts tests | grep -v 'tests/test_comment_provenance_guard.py'
```

**Empty output, exit 1 (no matches).** Guard: `3 passed`.

## POLISH-01 — every item verified against live source

Four of the seven were already fixed or obsolete; the record says so with file:line evidence rather
than repeating the finding's original assumption. Full detail in the closed todo.

| Item | Disposition |
|------|-------------|
| WR-01 | Fixed & proven (15-01) — by **two** tests: a hermetic route-driven crash/retrigger proof (green on first run; the mandatory failure injection worked, the narrow fallback was NOT taken) **and** a real-Postgres epoch-arbiter append proof, wired into `concurrency-proof.yml` so it actually executes in CI |
| WR-02 | Fixed Phase 8, verified — `app/db/supabase.py:35,54` double-checked locking |
| WR-03 | Fixed Phase 8, verified — `app/db/repo/demo.py:162` explicit column projection. Recorded as **fixed**, not the anticipated "accepted" |
| WR-04 | Fixed Phase 5, verified — `app/routes/runs.py:668` sanitizer + `tests/test_dashboard.py:454` CRLF regression test |
| WR-05 | Fixed Phase 15 (15-11) — `app/routes/dashboard.py:121-128` resolve + `is_relative_to` containment |
| INFO-01 | **Obsolete** — the status was removed; `tests/test_status_drift.py:193` enforces its absence. Adding a badge for an impossible status would re-introduce dead code |
| INFO-02 | Fixed Phase 15 (15-11) — `app/llm/client.py:121` `_scrubbed_validation_summary()` with `include_input=False` |

The dead `"computing"` badge-map entry (`app/routes/templating.py:21,37`) is **deliberately left** —
harmless under the maps' `.get()` defaults, and removing it is a behavior edit outside this phase's
three sanctioned fixes. Recorded as a choice, not an oversight.

## Verification

| Gate | Result |
|------|--------|
| `uv run pytest -q` | **622 passed, 53 skipped** (worktree baseline 619/53 + the 3 new guard tests — exact) |
| `uv run ruff check` | All checks passed |
| `uv run mypy` (strict) | Success: no issues found in 117 source files |
| `uv run python eval/run_eval.py --check` | `--check passed: no regression against committed summary.json` |
| Guard, both entry points, post-straggler | 3 passed |
| Independent second-scan grep | empty (exit 1) |

## Commits

| # | Hash | What |
|---|------|------|
| 1 | `d8442e7` | the guard (RED on 23 live stragglers; both synthetic tests already green) |
| 2 | `ac2eaf9` | the 23-hit straggler sweep — guard to GREEN |
| 3 | `0b790fc` | todo 260623-01 closed with seven dispositions |

## Deviations from Plan

**1. [Rule 2 - Missing critical functionality] The extended vocabulary found 23 live stragglers, not zero**

- **Found during:** Task 1, the mandated extended-vocabulary zero-FP evaluation
- **Issue:** The plan framed the extended shapes as a false-positive risk to be screened. They were
  the opposite: `Finding #N`, `LOW-6`, the un-parenthesized `Review fix`, and letter-block decision
  IDs (`D-A3-05`) were all live in the tree — invisible to the per-plan gate regexes, which is
  precisely why ten sweep plans had left them. Had the guard been written to the base D-08 table
  only, it would have shipped green over 23 pieces of exactly the rot it exists to prevent.
- **Fix:** Admitted all of them to the enforced table and swept the tree to match (commit `ac2eaf9`).
- **Files modified:** 10 (see key-files)

**2. [Judgment] `Phase [0-9]` kept enforced; no escape hatch added**

- **Issue:** The pattern cannot be textually distinguished from an algorithm-step label, and an
  escape-hatch marker was considered.
- **Resolution:** Rejected. An opt-out used zero times is a hole waiting to be used to silence the
  gate. The project already settled this: plan 15-03 renumbered the orchestrator's step labels to
  `1./2./3.`, which is unambiguous, survives a renumbered roadmap, and scans clean. The guard
  enforcing that convention is a feature. The legitimate-prose fixture pins the sanctioned form.

**3. [Scope] STATE.md deliberately NOT modified**

- The plan's `files_modified` lists `.planning/STATE.md`, but this plan ran in a worktree where the
  orchestrator owns that file post-merge. **Handoff:** the Deferred Items table still needs its two
  polish rows — "Phase 05 code-review: deferred Warnings + Info" and "Fixture 10 category-label" —
  moved from deferred to **resolved (Phase 15)**. Everything backing that change is done and
  committed.

## Threat Flags

None. This plan adds a read-only static scanner over source text and rewrites comment/docstring/
message text. No network endpoint, auth path, file-access pattern, or schema change. Plan 15-11's
two security fixes (the `is_relative_to` traversal containment in `app/routes/dashboard.py` and the
`include_input=False` scrub in `app/llm/client.py`) were verified intact and are untouched — both
are now cited as evidence in the closed todo.

## Known Stubs

None.

## Self-Check: PASSED

- `tests/test_comment_provenance_guard.py` — FOUND
- `.planning/todos/completed/260623-01-phase05-review-warnings.md` — FOUND
- `.planning/todos/pending/260623-01-phase05-review-warnings.md` — CONFIRMED ABSENT
- Commits `d8442e7`, `ac2eaf9`, `0b790fc` — all FOUND in `git log`
