---
phase: 21-durability-proofs-ops-view
plan: 11
subsystem: docs
tags: [documentation, durability-proofs, readme, rot-guard, comment-provenance]

# Dependency graph
requires:
  - phase: 21-durability-proofs-ops-view
    provides: "21-03/04/05/08's executed, evidenced falsifying mutations for PROOF-01..04 (mutation diffs, pasted reds, byte-identical reverts, commit SHAs); 21-09's completeness gate and its own two falsifications; 21-10's MUTATION_TARGETS registry (the machine-checked source of truth this document's assertion text and file/function mentions were verified against, not transcribed from any plan's prediction)"
provides:
  - "docs/DURABILITY-PROOFS.md — the published evidence document, one section per PROOF-01..05 (claim, mutation diff, pasted red naming the observed assertion, byte-identical revert with commit SHA, re-run command) plus the three accepted residuals and a pointer to /ops"
  - "A relative README link to the document, next to the existing architecture-diagram link"
  - "tests/test_durability_docs.py — a hermetic rot guard binding the document to scripts.check_proof_inventory.EXPECTED_PROOF_IDS and tests.test_proof_mutation_targets.MUTATION_TARGETS"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "A published document's claims are pinned to the machine-checked registry that already verified them against live source (MUTATION_TARGETS), not restated from a plan's prediction — the same discipline the registry itself applies to the mutations."

key-files:
  created:
    - docs/DURABILITY-PROOFS.md
    - tests/test_durability_docs.py
  modified:
    - README.md

key-decisions:
  - "Every named failing assertion published was cross-checked against both its proof's own SUMMARY (21-03/04/05/08) and the MUTATION_TARGETS registry (21-10) before being written — all three agreed for all four proofs. PROOF-01 (claimed.attempts == 1) and PROOF-04 (reclaimed is not None) contain no string literals, so the observed pytest transcript's assertion text and the registry's ast.unparse()-normalized text are byte-identical. PROOF-02 and PROOF-03 both compare set/subscript expressions containing string literals, so the registry's ast.unparse()-normalized form renders with single quotes while the live pytest transcript (captured verbatim from each proof's SUMMARY) renders with the source file's double quotes — both forms are published explicitly, the transcript for readability and a separate 'Named failing assertion' line in the registry's exact single-quoted form so the rot guard's literal substring check holds."
  - "PROOF-03's mutation diff explicitly names its enclosing function, send_reserved_outbound_snapshot in app/email/gateway.py, and PROOF-02's/PROOF-04's/PROOF-01's diffs carry it via their own @@ hunk headers (inbound, claim_job) — found missing while writing the rot guard's file/function check, not assumed present."
  - "Commands were split by safety per the plan's Codex-corrected instruction: every one of the four proofs' re-run commands needs a real Postgres and ALLOW_DB_RESET=1, so all four carry the DATABASE_URL=<throwaway-postgres-url> prerequisite marker and warning and were never auto-executed against this worktree's actual database. The completeness gate (PROOF-05) and the mutation-target registry guard are fully hermetic and WERE executed as verification — uv run python -m scripts.check_proof_inventory, uv run pytest tests/test_proof_mutation_targets.py -v, and the pre-fetch structural guard shown in PROOF-02's section all ran clean in this session."
  - "tests/test_durability_docs.py stays outside the proof/queueproof marker selections (it is a documentation guard, not a durability proof) and was written with no decision-ID/ticket/phase citations in its docstrings and comments — this repo's comment-provenance guard scans tests/ (unlike docs/**, which is explicitly out of scope) and caught one such citation ('D-08's shape') before this plan's Task 2 commit; rewritten in prose and reverified green."

requirements-completed: []  # PROOF-01..05 and OPS-01 are not complete — Task 3's human checkpoint (this plan) and 21-07's Task 3 (the live baseline + drain-while-firing proof) are both still open.

coverage:
  - id: D1
    description: "docs/DURABILITY-PROOFS.md exists, is reachable from the README, and contains a section for each of PROOF-01..05 — claim, mutation diff, pasted red naming the observed failing assertion, byte-identical revert with commit SHA, and a re-run command, each assertion text cross-checked against its proof's SUMMARY and the MUTATION_TARGETS registry before publication"
    requirement: "PROOF-01"
    verification:
      - kind: unit
        ref: "uv run python -c \"import pathlib; d=pathlib.Path('docs/DURABILITY-PROOFS.md').read_text(); print(all(i in d for i in ('PROOF-01','PROOF-02','PROOF-03','PROOF-04','PROOF-05')))\" -> True"
        status: pass
      - kind: unit
        ref: "uv run pytest tests/test_durability_docs.py -v -> 11 passed"
        status: pass
    human_judgment: false
  - id: D2
    description: "PROOF-03's two declared halves (structural fence refusal at count=1, genuine replay at count=2 with identity preserved) and PROOF-04's ordered-vs-genuine-contention distinction (with the ordered test's own stated non-coverage) are published as separate claims, not collapsed into one"
    requirement: "PROOF-03"
    verification:
      - kind: other
        ref: "manual read of docs/DURABILITY-PROOFS.md's PROOF-03 and PROOF-04 sections against 21-05-SUMMARY.md and 21-08-SUMMARY.md"
        status: pass
    human_judgment: false
  - id: D3
    description: "The residuals section states all three D-08 items explicitly (Two Generals / exactly-once unachievable, best-effort ~30-minute recovery including the 60-day auto-disable, retrigger-can-resend under the epoch-scoped claim) and is pinned by a test that reds when any one phrase is deleted"
    requirement: "PROOF-05"
    verification:
      - kind: unit
        ref: "tests/test_durability_docs.py::TestResidualsSectionIsPresent::test_all_three_residual_phrases_are_present, ::test_deleting_one_residual_phrase_reds"
        status: pass
    human_judgment: false
  - id: D4
    description: "Commands are split by safety: every hermetic command shown was executed and confirmed to run as written; every live-DB command carries the DATABASE_URL=<throwaway-postgres-url> prerequisite and was never auto-executed, pinned by a guard that reds if the marker is dropped from any block containing ALLOW_DB_RESET=1"
    requirement: "PROOF-05"
    verification:
      - kind: unit
        ref: "tests/test_durability_docs.py::TestLiveDatabaseCommandsCarryThePrerequisiteMarker (both tests)"
        status: pass
      - kind: other
        ref: "uv run python -m scripts.check_proof_inventory (exit 0), uv run pytest tests/test_proof_mutation_targets.py -v (31 passed), uv run pytest tests/test_webhook_dedup_race.py::test_prefetch_dedup_key_derivation_guard -v (1 passed) — all three hermetic commands shown in the document, executed in this session"
        status: pass
    human_judgment: false
  - id: D5
    description: "The rot guard (tests/test_durability_docs.py) is red-proofed live in-session (a typo'd assertion phrase and a dropped DATABASE_URL marker each observed reddening, naming the exact violation) and the no-false-positive half is demonstrated (the conforming, committed document passes clean) — not merely asserted"
    requirement: "PROOF-05"
    verification:
      - kind: other
        ref: "See 'Rot-Guard Red-Proof (this session)' below for both falsification transcripts and the byte-identical reverts"
        status: pass
    human_judgment: false
  - id: D6
    description: "/ops legibility and the published evidence reading as evidence — a human judgment call, per the plan's Task 3"
    verification: []
    human_judgment: true
    rationale: "The plan's Task 3 is a blocking checkpoint:human-verify requiring the operator to load the deployed /ops page and confirm each panel reads as a comparison (not a bare number), the as-of stamp is static, the nav and dead-letter links behave as specified, the page renders with JavaScript disabled, and to read one full proof section plus the residuals section from docs/DURABILITY-PROOFS.md and confirm it reads as evidence. This worktree has no deployed-service access and no way to substitute a human's reading of prose for a human's reading of prose — Task 3 is pending, not executed."

duration: ~50min (Tasks 1-2; Task 3 pending)
completed: 2026-07-20
---

# Phase 21 Plan 11: Publish the Durability Evidence Document Summary

**Published `docs/DURABILITY-PROOFS.md`, linked it from the README, and added a hermetic rot guard binding it to the phase's machine-checked mutation registry — every claim's mutation diff, pasted red, and named failing assertion cross-checked against both the source SUMMARY and `MUTATION_TARGETS` before publication, and the guard itself red-proofed live in this session. Task 3's human checkpoint (`/ops` legibility and the published evidence reading as evidence) is pending.**

See `docs/DURABILITY-PROOFS.md` for the durability claims themselves — this Summary does not
duplicate that content (D-07: the document is the single source of truth).

## Performance

- **Duration:** ~50 min (Tasks 1–2, autonomous)
- **Tasks:** 2 of 3 complete; Task 3 = PENDING human-verify checkpoint (`gate="blocking"`)
- **Files modified:** 3 (2 created: `docs/DURABILITY-PROOFS.md`, `tests/test_durability_docs.py`)

## Accomplishments

- **Task 1.** Wrote `docs/DURABILITY-PROOFS.md`: a framing paragraph, one section each for
  PROOF-01 through PROOF-04 (claim / mutation diff / pasted red naming the observed assertion /
  byte-identical revert with commit SHA / re-run command), a PROOF-05 section for the
  completeness gate (its own two live falsifications — a typo'd id, a dropped `queueproof`
  marker), the three D-08 residuals stated without hedging, and a closing pointer to `/ops`.
  Every mutation diff, red transcript, and named assertion was transcribed from the six prior
  plans' SUMMARYs (21-03, 21-04, 21-05, 21-08, 21-09, 21-10) — never re-derived or re-worded —
  and cross-checked against `tests/test_proof_mutation_targets.py`'s `MUTATION_TARGETS` registry
  before being written. The document cites no plan number, wave number, or `.planning/` path.
- **Task 2.** Added a relative README link next to the existing architecture-diagram link, and
  built `tests/test_durability_docs.py` — 11 hermetic tests covering all seven of the plan's
  required checks: the document exists with every proof id plus the completeness-gate section;
  the README link resolves to the real file; every `MUTATION_TARGETS` entry's file and enclosing
  function are mentioned in prose; every entry's recorded `assertion_text` (the exact
  `ast.unparse()`-normalized form the registry itself verified against live source) is present
  verbatim; all three residual phrases are present and independently deletable-to-red; no
  `.planning/` path leaks into the published text; and every live-DB command block (signalled by
  `ALLOW_DB_RESET=1`) carries the `DATABASE_URL=<throwaway-postgres-url>` prerequisite marker.
- While writing the rot guard, found and fixed two real gaps in Task 1's first draft: PROOF-03's
  mutation diff did not name its enclosing function (`send_reserved_outbound_snapshot`), and two
  of the four assertion texts (PROOF-02, PROOF-03) were published only in the pytest transcript's
  double-quoted form, not the registry's single-quoted `ast.unparse()` form the guard checks —
  both fixed by adding an explicit "Named failing assertion" line in the registry's exact form,
  alongside the verbatim transcript.
- Red-proofed the rot guard twice, live, in this session (see below), and confirmed the
  no-false-positive half: the conforming, committed document passes all 11 checks clean.

## Task Commits

1. **Task 1: Write the evidence document and the residuals section** - `2f70016` (docs)
2. **Task 2: Link the document from the README and guard both against rot** - `93979df` (docs)
3. **Task 3 (checkpoint): Human verification — `/ops` legibility and the published evidence** - PENDING human-verify checkpoint (NOT executed; see "Pending Human Checkpoint" below)

## Files Created/Modified

- `docs/DURABILITY-PROOFS.md` — new published evidence document (five proof sections, residuals,
  `/ops` pointer).
- `README.md` — one added sentence linking `docs/DURABILITY-PROOFS.md` next to the existing
  architecture-diagram link.
- `tests/test_durability_docs.py` — new hermetic rot guard, 11 tests across 5 test classes.

## Rot-Guard Red-Proof (this session)

Both required falsification shapes were executed live against the committed document, observed
reddening with the correct violation named, and reverted byte-identically — not merely asserted
from inspection.

**1. A drifted assertion text.** Renamed `claimed.attempts` to `claimed.attempts_TYPO` inside
PROOF-01's published prose (leaving the registry itself untouched):

```
E       AssertionError: ["PROOF-01: 'claimed.attempts == 1' not found in document"]
```

`git checkout -- docs/DURABILITY-PROOFS.md` reverted byte-identically (`git diff --stat` empty);
re-ran clean.

**2. A dropped live-DB prerequisite marker.** Removed `DATABASE_URL=<throwaway-postgres-url> `
from PROOF-01's re-run command, leaving `ALLOW_DB_RESET=1` (the live-DB signal) intact:

```
E       AssertionError: found a live-database command block missing the
        'DATABASE_URL=<throwaway-postgres-url>' prerequisite marker:
E         # WARNING: destructive, ALLOW_DB_RESET-guarded fixtures. Never point at a production database.
E         ALLOW_DB_RESET=1 \
E           uv run pytest tests/test_queue_durability.py -m "proof(id='PROOF-01')" -v -rs
```

`git checkout -- docs/DURABILITY-PROOFS.md` reverted byte-identically; re-ran clean.

**No-false-positive half.** With the document restored to its committed, conforming state:
`env -u DATABASE_URL uv run pytest tests/test_durability_docs.py -v` → **11 passed**, all seven
required checks present as distinctly named tests.

## Decisions Made

See `key-decisions` in the frontmatter for the full rationale on: (1) the single-quote-vs-double-
quote assertion-text publication (registry `ast.unparse()` form vs. the live pytest transcript's
literal form, both published), (2) adding the missing `send_reserved_outbound_snapshot` function
name to PROOF-03's diff, (3) the hermetic/live-DB command split and which commands were actually
executed as verification, and (4) the comment-provenance-guard fix in the rot guard's own
docstring.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Comment-provenance-guard violation in the rot guard's own docstring**
- **Found during:** Task 2's mandated verification (`uv run pytest tests/ -m "not integration and not live_llm" -q`, full hermetic suite), before Task 2's commit.
- **Issue:** A code comment in `tests/test_durability_docs.py` cited "D-08's shape" — a decision-id citation this repo's `tests/test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree` forbids in `tests/` (unlike `docs/**`, which is explicitly out of that guard's scope).
- **Fix:** Rewrote the comment to describe the constraint in prose ("the three accepted limits the document states plainly alongside its claims") without citing the decision id.
- **Files modified:** `tests/test_durability_docs.py`.
- **Verification:** `env -u DATABASE_URL uv run pytest tests/test_comment_provenance_guard.py::test_no_ticket_provenance_in_source_tree -q` → 1 passed, before Task 2's commit.
- **Committed in:** `93979df` (Task 2 commit — caught and fixed before the commit was made).

**2. [Rule 1 - Bug] PROOF-03's diff omitted its enclosing function; two assertion texts were published only in the wrong quoting convention**
- **Found during:** Writing `tests/test_durability_docs.py`'s file/function and assertion-text checks against the just-written Task 1 document, before Task 2's commit.
- **Issue:** `MUTATION_TARGETS["PROOF-03"].function_name` (`send_reserved_outbound_snapshot`) did not appear anywhere in the document's PROOF-03 section — the diff snippet showed only the mutated line, no `@@` hunk header naming the function. Separately, `MUTATION_TARGETS["PROOF-02"]` and `["PROOF-03"]`'s `assertion_text` fields (derived via `ast.unparse()`, which normalizes to single-quoted strings) did not appear verbatim in the document, which had published only the pytest transcript's literal double-quoted form.
- **Fix:** Added the `@@ def send_reserved_outbound_snapshot(` hunk header to PROOF-03's diff, and added an explicit "Named failing assertion:" line in each affected section using the registry's exact `ast.unparse()`-normalized text, alongside (not instead of) the verbatim transcript.
- **Files modified:** `docs/DURABILITY-PROOFS.md`.
- **Verification:** `env -u DATABASE_URL uv run pytest tests/test_durability_docs.py -v` → 11 passed.
- **Committed in:** `93979df` (Task 2 commit — folded in before the commit, not a separate commit).

---

**Total deviations:** 2 auto-fixed (both Rule 1). No scope creep — both fixes stayed inside this
plan's own declared files and made the plan's own stated acceptance criteria hold.

## Issues Encountered

One process note, not a deviation: an initial pass at writing the rot-guard's fenced-code-block
regex (`` ```(?:bash)?\n(.*?)``` ``) mispaired blocks whenever a ```` ```diff ```` block preceded a
plain ```` ``` ```` block, because the regex treated the diff block's own closing fence as a new
block's opening fence. Fixed by matching any language tag (`` ```[\w-]*\n(.*?)\n``` ``) so pairing
follows document order regardless of fence language. Caught by the guard's own tests failing with
an empty result where a non-empty one was expected, before Task 2's commit — not shipped broken.

## User Setup Required

**Human verification required before this plan can close (Task 3, blocking checkpoint).** See
the plan's own `<how-to-verify>` for the exact six-step procedure. Summarized:

1. Load `/ops` on the deployed service and confirm each of the four panels reads as a comparison
   (depth split, oldest-due-pending age vs. the pump-cadence bound, attempts vs. max, dead-letter
   attempts vs. max per row) — not a bare number.
2. Confirm the "as of" stamp is present and static (does not move if the page is left open).
3. Confirm the nav reads `Pyrl | Runs | Eval | Ops` with no button/form/dismiss control anywhere
   on `/ops`.
4. Click a dead-letter (or alarm) row and confirm it lands on that run's detail page.
5. Disable JavaScript and reload `/ops`; confirm it still renders fully.
6. Open `docs/DURABILITY-PROOFS.md` from the README link, read one proof section end to end and
   confirm it is re-runnable as written, and read the residuals section and confirm it reads as
   the boundary a careful evaluator would want stated.

Resume with a continuation agent once this is done, per the plan's `<resume-signal>` ("approved",
or a description of what did not read the way it should).

## Next Phase Readiness

- Tasks 1–2 are fully complete, committed, and verified: hermetic suite 1303 passed / 105 skipped
  (baseline 1292/105 + this plan's 11 new tests, 0 regressions); `ruff check .` and
  `uv run mypy --strict app` both clean; the four hermetic commands the document shows
  (`check_proof_inventory`, `test_proof_mutation_targets.py`, and the PROOF-02 structural guard)
  were all executed in this session and ran clean.
- This plan's `requirements-completed` frontmatter is deliberately empty — PROOF-01 through
  PROOF-05 and OPS-01 are not complete until Task 3 is approved, and separately 21-07's own Task 3
  (the live baseline + drain-while-firing proof) remains its own open checkpoint. Phase 21 cannot
  close until both are resolved.
- No blockers beyond the pending human checkpoints.

---
*Phase: 21-durability-proofs-ops-view*
*Completed (autonomous tasks): 2026-07-20; Task 3 = pending human checkpoint*

## Self-Check: PASSED

- FOUND: docs/DURABILITY-PROOFS.md
- FOUND: README.md (link present, resolves)
- FOUND: tests/test_durability_docs.py
- FOUND commit: 2f70016 (Task 1)
- FOUND commit: 93979df (Task 2)
- CONFIRMED: git status clean, both rot-guard falsifications reverted byte-identical
