---
phase: 15-comment-hygiene-deferred-polish-triage
plan: 09
requirements-completed: [COMM-01, COMM-03]
subsystem: web-layer (routes, llm, email, config, templates, tests)
tags: [comment-hygiene, docstrings, provenance-sweep, text-only]
requires:
  - plan 15-11's containment + retry-prompt fixes (wave dependency, merged into base)
provides:
  - thirty-six comment-clean files under the extended D-08 gate vocabulary
  - a phase-free user-visible demo caption in run_detail.html
affects:
  - plan 15-10 (tree-wide guard can now go green over this surface)
tech-stack:
  added: []
  patterns:
    - "AST-diff verification (docstring-stripped, string-blanked) as the proof that a comment sweep changed no executable code"
key-files:
  created: []
  modified:
    - app/routes/runs.py
    - app/routes/pipeline_glue.py
    - app/routes/webhook.py
    - app/routes/demo.py
    - app/routes/health.py
    - app/routes/templating.py
    - app/routes/dashboard.py
    - app/routes/__init__.py
    - app/llm/client.py
    - app/llm/prompts/extract.py
    - app/llm/prompts/clarify.py
    - app/llm/prompts/suggest.py
    - app/llm/prompts/__init__.py
    - app/email/gateway.py
    - app/email/clean.py
    - app/config.py
    - app/templates/run_detail.html
    - app/templates/eval.html
    - app/templates/runs_list.html
    - app/static/style.css
    - tests/test_dashboard.py
    - tests/test_llm_client.py
    - tests/test_stuck_run_recovery.py
    - tests/test_combined_context.py
    - tests/test_webhook.py
    - tests/test_orchestrator_states.py
    - tests/test_demo_fixtures.py
    - tests/test_suggest.py
    - tests/test_extract.py
    - tests/test_claim_status.py
    - tests/test_webhook_dedup_race.py
    - tests/test_decide_field_regression.py
    - tests/test_bootstrap_safe_url.py
    - tests/test_schema_introspect.py
    - tests/test_pdf.py
    - tests/test_compose_confirmation.py
decisions:
  - "Money-path comments were rewritten to state the FAILURE MODE, not merely the constraint — every mispay/double-send/spoof mechanism now says what breaks if it is removed"
  - "Ticket IDs were stripped from logger message text as well as comments; no test pins those strings"
  - "The one-off CLAR2-03/05 citation was dropped rather than kept: it appears nowhere else in the codebase and collides with the gate's R2-[0-9] pattern (the live requirement family is CLAR-0*)"
  - "Verification is AST-based, not grep-based: docstring-stripped + string-blanked AST dumps prove executable structure is byte-identical to base"
metrics:
  duration: ~75m
  completed: 2026-07-13
status: complete
---

# Phase 15 Plan 09: Web-Layer + Test-File Comment Sweep Summary

Thirty-six files swept clean of ticket-ID and process provenance under the extended
D-08 gate vocabulary, with every money-path comment rewritten to state the failure mode
it prevents — and AST-verified to have changed no executable code.

## Per-Task Outcome

| Task | Files | Gate | Commit |
|------|-------|------|--------|
| 1 — app/routes/ | 8 | zero hits; ruff clean; 44 passed / 2 skipped | `aa8d6bf` |
| 2 — llm, email, config, 3 templates, CSS | 12 | zero hits; ruff clean; 54 passed / 3 skipped | `28fada3` |
| 3 — the sixteen remaining test files | 16 | zero hits; full suite + ruff + strict mypy green | `4c80a57` |

Extended gate (D-08 subset + `UI-SPEC` / `UAT #` / `Codex` / `HIGH-N` / `finding #` /
`R2-HIGH`) returns **zero hits** across all thirty-six files.

## Verification

- `uv run pytest -q` → **619 passed, 53 skipped** (see the baseline note below).
- `uv run ruff check` → clean.
- `uv run mypy` → `Success: no issues found in 116 source files` (strict, covers `tests/`).
- Extended gate grep over all 36 files → zero matches.
- Test collection identical to base: 145 test functions before and after; the only name
  delta is the one sanctioned rename.

### Baseline correction (worth recording)

The execution brief stated the base was **620 passed / 52 skipped** and instructed me to
match it. My tree produced **619 / 53**. Rather than assume a regression, I ran the suite
against a pristine `git archive` export of the base commit (`a16c605`) in an isolated
directory: **it also produces 619 passed / 53 skipped**. The 620/52 figure in the brief
was off by one; the sweep introduced no regression. Collected totals match either way
(672).

### Proof the sweep is text-only

Grep-diffing a comment sweep cannot distinguish a reworded comment from a changed
statement, so verification is AST-based. For each file I parsed the base version and the
swept version, stripped all docstrings, blanked every string constant, and compared
`ast.dump` output:

- **All 20 app/ files: structure IDENTICAL.**
- **15 of 16 test files: structure IDENTICAL.** The lone exception,
  `tests/test_stuck_run_recovery.py`, differs solely because a function *name* changed
  (the sanctioned rename below) — a name is structurally load-bearing in the AST.

A second pass listed every string constant that changed. Outside docstrings, the only
string edits are **logger message text and assertion-failure messages** (ticket IDs
removed from human-readable output). No prompt payload, SQL literal, status value, or
route path was touched — confirmed by explicit enumeration, not inspection.

## 15-11's Security Fixes: Intact

Both fixes from plan 15-11 (which this plan's wave dependency exists to sequence after)
are untouched and their tests still pass:

| Fix | Evidence |
|-----|----------|
| Path-traversal containment (`app/routes/dashboard.py`) | `EVAL_SUMMARY_PATH` / `EVAL_FIXTURES_DIR` still module-level; `resolve()` + `is_relative_to(fixtures_root)` pair intact; `test_eval_view_refuses_fixture_path_traversal` **passes** |
| Scrubbed retry prompt (`app/llm/client.py`) | `_scrubbed_validation_summary()` intact with `errors(include_url=False, include_input=False)`; `test_retry_prompt_scrubs_validation_input_values` **passes** |

Where a comment described either fix, it was rewritten to state the CONSTRAINT — what
breaks if the mechanism is removed — never to soften it. The dashboard containment
comment now names the escape it prevents; the client docstring now says re-enabling
`include_input` returns untrusted model output to a third party.

## Money-Path Comments: Depth Kept, Failure Mode Added (D-02)

The sweep deliberately made these comments *stronger*, not shorter. Each now names the
concrete failure it prevents:

- **`runs.py` Content-Disposition sanitizer** — keeps the full injection narration and now
  states that an unsanitized `emp_name` (which can be LLM-extracted, hence attacker-shaped)
  could "terminate the filename early or inject an entire extra response header", plus the
  `re.ASCII` / latin-1 500 rationale. Ends with "Do not loosen this pattern."
- **`runs.py` approve gate** — a lost CAS claim means "the client would receive the payroll
  confirmation twice".
- **`runs.py` retrigger stale-CAS exclusivity** — if the claim target equalled the current
  status the UPDATE is a no-op and "BOTH would win — running the pipeline twice over the
  same payroll".
- **`runs.py` retrigger vs. sweep scope divergence** — spells out that adding SENT to the
  sweep "would auto-re-run runs that already emailed the client. Do NOT 'fix' this into parity."
- **`pipeline_glue.py` / `webhook.py` sender revalidation** — the RFC header chain is
  forgeable; without the re-check, a redelivery or a dashboard load "would launder the
  spoofed reply straight into the pipeline".
- **`webhook.py` ingest transaction** — states both invariants (no orphan rows; a reply can
  never spuriously create a second run) and why classification must happen *inside* the txn.
- **`client.py` retry compounding** — keeps the full derivation that omitting
  `max_retries=0` makes the worst case `timeout x 3 x 2` = **six times** the timeout, and
  notes the stale-run sweep threshold is derived against this figure.
- **`extract.py` null-vs-zero** — coercing absent hours to 0 "would turn 'the client forgot
  to tell us' into 'this employee worked zero hours' and pay them nothing".
- **`gateway.py` References chain** — losing the anchor means "the reply arrives as an
  unrelated first ingest".

## The User-Visible String

`app/templates/run_detail.html` line ~108, the only rendered provenance string in the app:

- before: `(demo only — Phase 6 uses real inbound webhook)`
- after: `(demo only — production uses the real inbound webhook)`

Pre-checked `tests/`, `eval/` and `app/` for a pinned literal of the old caption — none
existed, so no expected-string update was needed.

## Deviations from Plan

**1. [Rule 3 — blocking] The `CLAR2-03/05` citation collides with the gate regex**
- **Found during:** Task 3, `tests/test_combined_context.py` line 1.
- **Issue:** The plan's rubric says requirement IDs are traceability and should be kept.
  `CLAR2-03` *looks* like one, but it trips the gate's `R2-[0-9]` pattern (`CLA` + `R2-0`),
  so the task gate could not go green while it remained.
- **Resolution:** Grepped the whole codebase — `CLAR2` appears **exactly once**, in that one
  docstring. The live requirement family is `CLAR-01/02/03` (used in `clarify.py`,
  `pipeline_glue.py`, `test_clarify.py`). `CLAR2-03/05` is a one-off citation, not a live
  traceability ID, so dropping it loses nothing. Docstring now opens "Combined-context
  accumulation tests for the multi-round clarification path."
- **Commit:** `4c80a57`

**2. [D-06 rename] One ticket-prefixed test name**
- `test_sweep_stranded_runs_scope_pin_d_9_12` → `test_sweep_stranded_runs_scope_pin`.
  Collect-count neutral (1 → 1). Grepped for references to the old name across `.py`, `.md`
  and `.yml` outside `.planning/` — none exist. A sibling docstring that named the old
  function was updated in the same commit.

**3. [Scope, honored] Behavior edits declined**
Per the plan's scope note, `templating.py`'s dead `"computing"` badge entry was left in
place and no `needs_clarification` entry was added. No control flow was changed anywhere.

**4. Baseline count in the brief was off by one** — see "Baseline correction" above. Not a
deviation in the work; recorded so the verifier does not chase a phantom regression.

## Threat Register Outcome

| Threat ID | Disposition | Outcome |
|-----------|-------------|---------|
| T-15-04 | mitigate | **Closed** — text-only rule enforced by AST diff (structure identical, string deltas enumerated); prompt json-mode requirement re-asserted by source grep; suite + ruff + mypy green per commit |
| T-15-06 | mitigate | **Closed** — the sanitizer's failure-mode comment is not merely preserved but sharpened; the regression test (`test_paystub_pdf_content_disposition_sanitized`, incl. the CRLF and non-latin-1 cases) still passes |

## Threat Flags

None. This plan introduced no network endpoint, auth path, file-access pattern, or schema
change — it changed comment and docstring text plus one rendered caption.

## Known Stubs

None.

## Notes for Downstream Plans

- **Plan 15-10** — this surface (36 files) is clean under the *extended* vocabulary, which
  is wider than the D-08 guard subset. Two legitimate residual patterns remain repo-wide and
  must be preserved by the guard's word-boundary handling: `BOUND-01` and `FOUND-04` contain
  the substring `D-0`, so the guard regex must use `\bD-[0-9]`, not `D-[0-9]`. Without the
  boundary it will flag both requirement IDs as violations.
- If the guard's vocabulary includes `R2-[0-9]`, note it also matches the `CLAR2-*` shape.
  That family is now absent from the codebase, but a future author reintroducing a `CLAR2-`
  ID would trip the guard.

## Self-Check: PASSED

- `app/routes/runs.py` — FOUND (sanitizer failure-mode comment present)
- `app/routes/dashboard.py` — FOUND (`is_relative_to` containment present)
- `app/llm/client.py` — FOUND (`include_input=False` present)
- `app/templates/run_detail.html` — FOUND (contains "production uses the real inbound webhook")
- Extended gate grep over all 36 files — ZERO HITS
- Commits `aa8d6bf`, `28fada3`, `4c80a57` — all present in `git log`
- `.planning/STATE.md` / `.planning/ROADMAP.md` — NOT modified (confirmed via `git diff --name-only` against base)
