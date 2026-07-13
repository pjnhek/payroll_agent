---
phase: 15-comment-hygiene-deferred-polish-triage
plan: 11
subsystem: dashboard + llm-client
tags: [security, path-traversal, information-disclosure, tdd]
requires:
  - app/routes/dashboard.py eval_view
  - app/llm/client.py call_structured
provides:
  - EVAL_SUMMARY_PATH / EVAL_FIXTURES_DIR module constants (monkeypatchable eval data seam)
  - path containment on eval fixture reads (is_relative_to)
  - _scrubbed_validation_summary() — retry prompt no longer echoes model output
affects:
  - plan 15-09 (wave 2 comment sweep of these same four files)
  - plan 15-10 (todo 260623-01 disposition record)
tech-stack:
  added: []
  patterns:
    - "module-level relative Path constants as the test-redirect seam (mirrors eval/run_eval.py FIXTURE_DIR/SUMMARY_PATH)"
    - "pydantic errors(include_url=False, include_input=False) for outbound-safe error summaries"
key-files:
  created: []
  modified:
    - app/routes/dashboard.py
    - tests/test_dashboard.py
    - app/llm/client.py
    - tests/test_llm_client.py
decisions:
  - "Eval path constants stay RELATIVE Path literals (no __file__ anchoring) — behaviour-identical to the old function-local Paths, container WORKDIR=/app unchanged"
  - "Traversal refusal reuses the existing missing-file placeholder rather than adding a new error path"
  - "Retry prompt keeps loc/type/msg (actionable) and drops input values (untrusted echo)"
metrics:
  duration: ~25m
  completed: 2026-07-13
status: complete
---

# Phase 15 Plan 11: POLISH-01 Behavior Fixes (WR-05 + INFO-02) Summary

Path containment on the eval view's fixture reads and a scrubbed LLM retry prompt — both landed test-first, with the escape and the echo each demonstrated failing before the fix.

## Per-Item Outcome

| Item | Status | Where |
|------|--------|-------|
| WR-05 — eval fixture path traversal | **FIXED** | `app/routes/dashboard.py` `eval_view` |
| INFO-02 — ValidationError content echoed to provider | **FIXED** | `app/llm/client.py` `call_structured` |

## Hoisted Dashboard Constants (for plan 15-09)

Final names, both module-level in `app/routes/dashboard.py`, both still relative `Path` literals:

- `EVAL_SUMMARY_PATH = Path("eval/summary.json")`
- `EVAL_FIXTURES_DIR = Path("eval/fixtures")`

`eval_view` reads the constants; `tests/test_dashboard.py` redirects them with
`monkeypatch.setattr(dashboard, ...)`. `grep -c 'monkeypatch.chdir' tests/test_dashboard.py` → **0**
(the shared relative Jinja searchpath is untouched, so `eval.html` still resolves).

## RED Evidence

**WR-05** — `test_eval_view_refuses_fixture_path_traversal` at commit `2e268d0`:

```
E  AssertionError: a fixture_path that escapes the fixtures directory must never have
E  its file contents rendered on the eval page
E  assert 'TRAVERSAL_SENTINEL_CONTENT' not in '<!DOCTYPE h...dy>\n</html>'
E    'TRAVERSAL_SENTINEL_CONTENT' is contained here:
E      ture-raw">TRAVERSAL_SENTINEL_CONTENT</code>
```

The route read `../secret.txt` from outside the fixtures directory and rendered it. Fixed at
`080b80c` by resolving the join and gating it with `is_relative_to(fixtures_root)`; refusals fall
into the identical `"‹fixture file missing›"` placeholder the not-exists branch already used. The
same test's positive control proves a legitimate in-directory fixture still renders its body.

**INFO-02** — `test_retry_prompt_scrubs_validation_input_values` at commit `25b4f39`:

```
E  AssertionError: the retry prompt must not echo values taken from the model's own
E  output back to the provider
E  assert 'SENTINEL_LEAK_XYZ' not in 'Your last o... the schema.'
E    'SENTINEL_LEAK_XYZ' is contained here:
E      ut_value='SENTINEL_LEAK_XYZ', input_type=str]
```

Fixed at `ca53ed9`: `_scrubbed_validation_summary(exc)` formats only `loc`, `type`, and `msg` from
`exc.errors(include_url=False, include_input=False)`. The empty-content `ValueError` still passes
through `str(exc)` (it carries no model output). The one-retry contract, the
`"Return ONLY valid JSON matching the schema."` instruction (the word JSON is load-bearing for
DeepSeek's json_object mode), the second-failure propagation, and the ValueError→ValidationError
normalization are all byte-identical.

## Task Commits

| Commit | Type | What |
|--------|------|------|
| `6636c4f` | refactor | hoist eval data paths to module constants (no behavior change; suite green) |
| `2e268d0` | test | RED: traversal fixture_path renders out-of-directory file contents |
| `080b80c` | fix | `resolve()` + `is_relative_to()` containment; refusals reuse the missing-file placeholder |
| `25b4f39` | test | RED: retry prompt echoes `input_value` back to the provider |
| `ca53ed9` | fix | `_scrubbed_validation_summary()` replaces the raw `exc` interpolation |

## Verification

- `uv run pytest -q` → **617 passed, 51 skipped** (integration/live_llm auto-skip; no `.env` in the worktree, as expected).
- `uv run ruff check` → clean.
- `uv run mypy` → `Success: no issues found in 114 source files` (strict, covers `tests/`).
- `grep -c 'monkeypatch.chdir' tests/test_dashboard.py` → `0`.
- Commit history shows a failing-test commit immediately preceding each fix commit.
- Zero existing assertions were changed; both new tests are additive.

## Threat Register Outcome

| Threat ID | Disposition | Outcome |
|-----------|-------------|---------|
| T-15-01 | mitigate | **Closed** — containment check + regression test driving the real route |
| T-15-02 | mitigate | **Closed** — `include_url=False, include_input=False` summary + regression test |
| T-15-10 | accept | Unchanged — the hoisted constants are server-side module attributes with no user-writable seam; no production code path rebinds them |

## Deviations from Plan

None — plan executed as written. One in-flight correction inside Task 1: the new test's docstring
originally used the literal string `monkeypatch.chdir` while explaining why it is not used, which
tripped the plan's own `grep -c 'monkeypatch.chdir' → 0` acceptance criterion. The docstring was
reworded to describe the hazard in prose before the fix commit.

## Known Stubs

None.

## Notes for Downstream Plans

- **Plan 15-09** sweeps the comments/docstrings of these same four files. The provenance strings in
  the touched files' docstrings were deliberately left untouched here. New comments added by this
  plan (the constants block, the containment rationale, `_scrubbed_validation_summary`'s docstring)
  are already born clean — no ticket IDs, phase numbers, or planning-document citations — and the
  two new test functions contain none either.
- **Plan 15-10** — both remaining POLISH-01 behavior items are now closed; todo 260623-01's WR-05
  and INFO-02 lines can be recorded as fixed with the commits above.

## Self-Check: PASSED

- `app/routes/dashboard.py` — FOUND (contains `is_relative_to`, `EVAL_SUMMARY_PATH`, `EVAL_FIXTURES_DIR`)
- `app/llm/client.py` — FOUND (contains `include_input=False`)
- `tests/test_dashboard.py` — FOUND (contains `test_eval_view_refuses_fixture_path_traversal`)
- `tests/test_llm_client.py` — FOUND (contains `test_retry_prompt_scrubs_validation_input_values`)
- Commits `6636c4f`, `2e268d0`, `080b80c`, `25b4f39`, `ca53ed9` — all present in `git log`
