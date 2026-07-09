---
phase: 12-ci-quality-gates
reviewed: 2026-07-09T18:50:12Z
depth: standard
files_reviewed: 63
files_reviewed_list:
  - .github/workflows/ci.yml
  - README.md
  - app/db/bootstrap.py
  - app/db/repo.py
  - app/db/seed.py
  - app/db/supabase.py
  - app/email/gateway.py
  - app/llm/client.py
  - app/main.py
  - app/models/contracts.py
  - app/models/roster.py
  - app/models/status.py
  - app/pipeline/calculate.py
  - app/pipeline/decide.py
  - app/pipeline/orchestrator.py
  - app/pipeline/tax_tables_2026.py
  - app/pipeline/validate.py
  - eval/run_eval.py
  - pyproject.toml
  - scripts/reset_stuck_runs.py
  - scripts/show_confirmation_subject.py
  - tests/conftest.py
  - tests/test_alias_full_loop.py
  - tests/test_alias_write.py
  - tests/test_atomic_persist.py
  - tests/test_calculate.py
  - tests/test_check_schema_cli.py
  - tests/test_claim_status.py
  - tests/test_clarify.py
  - tests/test_clarify_rounds.py
  - tests/test_combined_context.py
  - tests/test_compose_confirmation.py
  - tests/test_compose_email_field_regression.py
  - tests/test_concurrency_proof.py
  - tests/test_cr01_classify_union.py
  - tests/test_cr_regressions.py
  - tests/test_dashboard.py
  - tests/test_delivery.py
  - tests/test_demo_landing.py
  - tests/test_detect_field_regression.py
  - tests/test_eval_wiring.py
  - tests/test_federal_withholding.py
  - tests/test_gateway.py
  - tests/test_health_schema.py
  - tests/test_hitl.py
  - tests/test_ingest.py
  - tests/test_live_llm.py
  - tests/test_llm_client.py
  - tests/test_models_contracts.py
  - tests/test_multi_employee_delivery.py
  - tests/test_multiround_context_edge.py
  - tests/test_needs_operator.py
  - tests/test_orchestrator_states.py
  - tests/test_pdf.py
  - tests/test_persistence.py
  - tests/test_reconcile.py
  - tests/test_reply_redelivery.py
  - tests/test_resume_pipeline.py
  - tests/test_retrigger_epoch.py
  - tests/test_stuck_run_recovery.py
  - tests/test_suggest.py
  - tests/test_tax_tables_2026.py
  - tests/test_threading.py
  - tests/test_validate.py
findings:
  critical: 0
  warning: 3
  info: 5
  total: 8
status: issues_found
cross_ai: codex gpt-5.6-terra (2026-07-09) — confirmed all internal findings, added WR-03
---

# Phase 12: Code Review Report

**Reviewed:** 2026-07-09T18:50:12Z
**Depth:** standard
**Files Reviewed:** 63
**Status:** issues_found

## Summary

Phase 12 claimed a behavior-neutral lint cleanup (ruff E,F,I,B,UP,SIM @ line-length 100)
plus a new CI workflow. The review's primary hypothesis — that a "mechanical" fix silently
changed behavior — was tested by reading the full diff of every `app/`, `eval/`, `scripts/`,
and config file against `e01aa606`, plus targeted scans of all 43 test-file diffs. Each
high-risk change class from the review brief was traced:

1. **UP042 StrEnum (`app/models/status.py`)** — every rendering site of `RunStatus` was
   audited. All DB writes go through `.value` (`repo.set_status`/`claim_status`/
   `sweep_stranded_runs`); the dashboard badge filters (`app/main.py:225-232`) receive DB
   strings, not enum members; f-string interpolation was already value-based on 3.12 for the
   old `(str, Enum)` mixin. Exactly ONE `str()`-path rendering delta exists: a log line in
   `orchestrator.py` (IN-01, log-only, no consumer). No money-path or SQL-path change.
2. **SIM117 nested-with collapses (46 sites)** — all verified. The `_conn_ctx(conn) as
   (c, owns), c.transaction() if owns else _nulltx()` pattern in `app/db/repo.py` is correct
   (with-items evaluate left-to-right; `as` binds before the next item). The reindented
   `POST /webhook/inbound` transaction block in `app/main.py:406-487` was re-read in full —
   the if/elif/else routing tree (duplicate / reply_candidate / late_reply / fall-through /
   ordinary ingest) is structurally identical. The 3-level collapse in
   `eval/run_eval.py:_write_db_results` preserves connect → transaction → cursor ordering.
3. **B904 `raise ... from`** — all sites add chaining only; no handler logic changed. The
   `raise last_error from exc` in `app/llm/client.py:174` changes only `__cause__`.
4. **B007/F841** — `_emp_id` in `decide.py:check_one_to_one` verified unused in loop body;
   `_run_id_str` (conftest), `_created_at`/`_purpose` (show_confirmation_subject),
   `_sql`/`_params` (test loops) all verified. Side-effectful RHS calls were retained
   (`_result = update_known_alias(...)`, `_send_params_hints = ...__annotations__`).
5. **UP047 (`app/llm/client.py`)** — `def call_structured[T: BaseModel](...)` carries the
   bound; the old `TypeVar("T", bound=BaseModel)` was removed. Semantically equivalent.
6. **E501 string splits** — every split user-facing/SQL/log string was re-concatenated and
   compared character-for-character: repo.py purpose-ValueError messages, bootstrap.py print
   (double space before `(D-21-06` preserved), reset_stuck_runs prompts, run_eval chart
   footnote, validate.py field-regression message (extracted to `resumed_display`, identical
   output). No missing-space joins found.
7. **F821/TYPE_CHECKING un-quoting** — `app/models/roster.py`, `app/models/contracts.py`,
   `tests/test_calculate.py`, `tests/test_detect_field_regression.py` all carry
   `from __future__ import annotations`, so un-quoted self-referencing annotations are safe.
8. **ci.yml** — commands are exactly `uv run ruff check .` and `uv run pytest -q`; concurrency
   group cancels superseded runs; no secrets referenced; README badge URL matches the actual
   remote (`pjnhek/payroll_agent`). Hardening gaps found (WR-01, WR-02).

Independent gate verification: `uv run ruff check .` → **All checks passed**; hermetic
`uv run pytest -q` (DATABASE_URL/ALLOW_DB_RESET/ALLOW_LIVE_LLM unset) → **613 passed,
50 skipped**. Two apparent >100-char lines were false positives (byte-counting of em-dashes;
the one genuinely long line at `tests/test_gateway.py:460` is exempted by ruff's documented
pragma-comment E501 exception — see IN-03).

No blockers. Two CI-hardening warnings and five info items.

## Warnings

### WR-01: ci.yml has no `permissions:` block — GITHUB_TOKEN runs with default (potentially write) scope

**File:** `.github/workflows/ci.yml:1-50`
**Issue:** Neither the workflow nor its jobs declare `permissions:`. The lint/test jobs need
only read access to checkout, but the injected `GITHUB_TOKEN` receives the repository default
— which is read/write for repos/orgs still on the legacy default. Combined with a
third-party action resolved by mutable tag (WR-02), this violates least-privilege: a
compromised action could push commits or tamper with releases using the ambient token.
**Fix:**
```yaml
name: ci

permissions:
  contents: read

on:
  push:
  workflow_dispatch:
```

### WR-02: Third-party actions pinned to mutable tags, not commit SHAs

**File:** `.github/workflows/ci.yml:19,22,36,39`
**Issue:** `actions/checkout@v4` and `astral-sh/setup-uv@v5` are mutable references. If either
tag is force-moved (as happened in the 2025 `tj-actions` supply-chain incident), the workflow
executes attacker-controlled code with the job's token. `astral-sh/setup-uv` is a third-party
(non-`actions/`) publisher, where SHA-pinning is the accepted baseline.
**Fix:** Pin to full commit SHAs with a tag comment, e.g.:
```yaml
- uses: actions/checkout@08eba0b27e820071cde6df949e0beb9ba4906955  # v4.x
- uses: astral-sh/setup-uv@<full-sha-of-v5-release>  # v5
```
(Resolve the exact SHAs from each repo's release page; Dependabot `github-actions` ecosystem
can keep them current.)

## Info

### IN-01: The one detected behavior delta from UP042 — log rendering of `from_status` changed

**File:** `app/pipeline/orchestrator.py:381-388`
**Issue:** `logger.info("resume aborted: run %s claim failed from %s — ...", run_id,
from_status)` passes a `RunStatus` member through `%s`, which calls `str()`. Old
`(str, enum.Enum)` mixin: `"RunStatus.AWAITING_REPLY"`. New `enum.StrEnum`:
`"awaiting_reply"`. This is the single place in `app/`, `eval/`, and `scripts/` where an
enum member reaches a `str()`/`%s` rendering path, so the "behavior-neutral" claim holds
everywhere except this log line's text. No test asserts it and no consumer parses it — the
new form is arguably better — but it should be on the record since the phase contract was
zero behavior change.
**Fix:** None required. If strict neutrality matters for log-grep tooling, use
`from_status.value` explicitly (same output, self-documenting).

### IN-02: Copy-pasted noqa justification is wrong on tax-table imports

**File:** `tests/test_calculate.py:85,88`
**Issue:** The split `from app.pipeline.tax_tables_2026 import (...)` blocks carry
`# noqa: E402 — appended after existing imports; uuid is stdlib` — the "uuid is stdlib"
rationale was copy-pasted from the `import uuid` line above and is meaningless here. D-03
requires *individually-justified* inline noqa comments; this one misleads the next reader.
**Fix:** `# noqa: E402 — appended after existing imports (mid-file test section)` on each
of the three tax-table import blocks.

### IN-03: 150+ char line survives E501 only via ruff's pragma-comment exemption

**File:** `tests/test_gateway.py:460`
**Issue:** `import resend  # noqa: F401, E402 — installed via 06-01 Task 1; needed for
monkeypatching, imported late to keep the patch target order documented above` is ~150
characters. It passes `ruff check` only because E501 exempts lines whose overage is caused
by a pragma comment — not because it was fixed or explicitly suppressed. That silently
sidesteps the D-03 convention (every violation fixed or individually noqa'd with the code
named).
**Fix:** Keep `# noqa: F401, E402` short on the import line and move the prose rationale to
a comment line above it.

### IN-04: `zip(..., strict=False)` chosen for neutrality where `strict=True` is the correct contract

**File:** `eval/run_eval.py:807,817,845`
**Issue:** The B905 fixes annotate the chart-annotation zips with `strict=False`, freezing
today's behavior (silent truncation on length drift). All three pair a bar container with the
exact list that produced it, so lengths are equal by construction — `strict=True` would turn
a future refactor bug into a loud error instead of silently mislabeled eval charts (the
project's "legible eval chart" is a first-class deliverable).
**Fix:** Follow-up (post behavior-neutral phase): flip these three to `strict=True`.

### IN-05: CI triggers/limits — no `pull_request` trigger, no job timeouts

**File:** `.github/workflows/ci.yml:3-5,15,32`
**Issue:** `on: push` covers same-repo branches, but a PR opened from a fork gets no required
check, and no `timeout-minutes` is set on either job (a hung test holds a runner for GitHub's
360-minute default). Low impact for a single-author repo, but cheap to close.
**Fix:** Add `pull_request:` to the trigger block and `timeout-minutes: 15` on both jobs.

---

_Reviewed: 2026-07-09T18:50:12Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_


---

## Cross-AI Review (Codex, gpt-5.6-terra — 2026-07-09)

Independent adversarial pass over the same diff (base `e01aa606..HEAD`), with repo access; ran ruff + 69 targeted tests itself. **No additional payroll, transaction-scope, calculation, decisioning, prompt, file-lifecycle, or runtime-type drift found** — the behavior-neutral claim holds apart from the already-known IN-01 log-rendering delta.

### WR-03 (WARNING, new): CI does not enforce the committed lockfile

`.github/workflows/ci.yml` lines 27 and 45 run plain `uv sync`, which may update `uv.lock` rather than assert it. A `pyproject.toml` change without a regenerated lockfile would resolve and test uncommitted dependency versions in CI, letting a stale-lockfile state merge green. Fix: `uv sync --locked` in both jobs.

### Verification of internal findings

WR-01 confirmed (no `permissions:` block) · WR-02 confirmed (tag-pinned actions) · IN-01 confirmed (`orchestrator.py:387` StrEnum log delta) · IN-02 confirmed · IN-03 confirmed · IN-04 confirmed (all three eval-chart zips `strict=False`) · IN-05 confirmed.

### Verdict

Behavior-neutral claim materially true; overall risk **MEDIUM**, driven entirely by CI hardening/reproducibility gaps (WR-01/WR-02/WR-03), not payroll runtime logic.
