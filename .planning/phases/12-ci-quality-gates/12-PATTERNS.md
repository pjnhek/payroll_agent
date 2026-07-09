# Phase 12: CI Quality Gates - Pattern Map

**Mapped:** 2026-07-08
**Files analyzed:** 4 (1 new workflow, 1 config edit, 1 doc edit, 1 repo-wide cleanup pass)
**Analogs found:** 4 / 4

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|--------------------|------|-----------|-----------------|----------------|
| `.github/workflows/ci.yml` | config (CI workflow) | event-driven (push trigger → job run) | `.github/workflows/eval.yml` (job/step shape) + `.github/workflows/deploy-migrate.yml` (concurrency block) | role-match (composite of two analogs, no single exact match — this repo has no lint/test-only workflow yet) |
| `pyproject.toml` `[tool.ruff]` / `[tool.ruff.lint]` | config | transform (static config, no runtime flow) | `pyproject.toml` `[tool.pytest.ini_options]` (existing section in same file) | exact (same file, same "tool config block" role) |
| `README.md` badge | config/doc | request-response (rendered markdown, shields.io badge fetch) | No existing badge in this README — greenfield addition | no analog (first badge in the doc) |
| Repo-wide lint cleanup (`app/`, `eval/`, `scripts/`, `tests/`) | transform (mechanical + hand-fix edits) | batch | Existing violation sites themselves are the "analog" — see per-rule sections below | n/a — this is a fix-in-place task, not a new-file task |

## Pattern Assignments

### `.github/workflows/ci.yml` (config, event-driven)

**Primary analog:** `.github/workflows/eval.yml` (job/step recipe) — **Secondary analog:** `.github/workflows/deploy-migrate.yml` (concurrency block, since `eval.yml` has no concurrency group at all)

**House setup recipe — identical across all 4 existing workflows** (`.github/workflows/eval.yml` lines 19-27, `deploy-migrate.yml` lines 27-36, `concurrency-proof.yml` lines 35-42):
```yaml
steps:
  - name: Checkout
    uses: actions/checkout@v4
  - name: Set up uv + Python 3.12
    uses: astral-sh/setup-uv@v5
    with:
      python-version: "3.12"
  - name: Install deps (all groups)
    run: uv sync
```
Copy this verbatim into both the `lint` and `test` jobs (each job needs its own copy of `checkout` + `setup-uv` + `uv sync` — GitHub Actions jobs run on fresh runners, no state sharing between jobs in this repo's existing workflows). Note: `uv sync` (no `--no-dev`) is the house convention for CI — dev group (including `ruff`, `pytest`) is installed, matching `[dependency-groups].dev` in `pyproject.toml`.

**Trigger pattern — deviates from house norm per D-07** (all 4 existing workflows trigger on `branches: ["master"]` only; `ci.yml` must trigger on ALL branches):
```yaml
# eval.yml lines 3-6 (existing house pattern, for contrast — ci.yml does NOT copy this branch filter)
on:
  push:
    branches: ["master"]
  workflow_dispatch:
```
`ci.yml`'s `on:` block per D-07 should read:
```yaml
on:
  push:
  workflow_dispatch:
```
(Omitting `branches:` under `push` means "all branches" — this is the literal-reading deviation D-07 calls for.)

**Concurrency pattern — copy structure from `deploy-migrate.yml` lines 18-20, but flip the boolean per D-09:**
```yaml
# deploy-migrate.yml lines 14-20 (source pattern — note cancel-in-progress:false there, for the opposite reason)
concurrency:
  group: deploy-migrate
  cancel-in-progress: false
```
`ci.yml` per D-09 (lint/test runs are cancellable, unlike a mid-flight DB migration):
```yaml
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true
```
Use `${{ github.ref }}` (not a bare literal like `deploy-migrate`'s static group name) — per-branch groups per D-09, so that pushing to branch A never cancels an in-flight run on branch B; only same-branch superseding pushes cancel each other.

**Two-job structure — no existing analog has 2 independent same-trigger jobs at top level** (`eval.yml` has `check` + `record`, but `record` is gated by `if: github.event_name == 'workflow_dispatch' && inputs.live_record` — a conditional second job, not two parallel unconditional jobs). `ci.yml` per D-10 needs both jobs to run unconditionally on every push:
```yaml
jobs:
  lint:
    name: "Lint (ruff check)"
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Set up uv + Python 3.12
        uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.12"
      - name: Install deps (all groups)
        run: uv sync
      - name: Run ruff check
        run: uv run ruff check .
        # No extra flags/paths (success criterion 3: must byte-for-byte match the
        # local command a developer runs, since ruleset+line-length live in pyproject.toml).

  test:
    name: "Test suite (hermetic)"
    runs-on: ubuntu-latest
    steps:
      - name: Checkout
        uses: actions/checkout@v4
      - name: Set up uv + Python 3.12
        uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.12"
      - name: Install deps (all groups)
        run: uv sync
      - name: Run test suite
        run: uv run pytest -q
        # No DB service, no ALLOW_DB_RESET/ALLOW_LIVE_LLM env vars set (D-11) —
        # tests/conftest.py's two-factor guards make this hermetic by omission.
```

**On the `DATABASE_URL: "placeholder"` question (flagged in code_context as "verify, don't assume"):** `eval.yml` line 31 sets `DATABASE_URL: "placeholder"` for its hermetic `check` job because `eval/run_eval.py --check` imports `app.config`/`Settings` at module load and `pydantic-settings` needs *some* value to validate against (a required field failing fast at import time, per the Tooling Rule pattern). By contrast, `tests/conftest.py` monkeypatches `DATABASE_URL` per-test via fixtures (see Shared Patterns below) rather than relying on a process-wide env var, so the plain `test` job most likely does NOT need the `DATABASE_URL: "placeholder"` env stanza — but this should be confirmed empirically (run `uv run pytest -q` locally with `DATABASE_URL` unset) before the planner locks it in, since a module imported at collection time before any fixture runs could still trip `Settings()` validation.

---

### `pyproject.toml` (config, transform)

**Analog:** the existing `[tool.pytest.ini_options]` section in the same file (lines 38-43) — establishes the house convention for how tool config sections are formatted and commented in this file.

**Existing section pattern to mirror** (`pyproject.toml` lines 38-43):
```toml
[tool.pytest.ini_options]
# Register custom markers so pytest doesn't warn about unknown marks.
markers = [
    "integration: marks tests as requiring a live database (deselect with -m 'not integration')",
    "live_llm: marks tests as hitting real DeepSeek/Kimi APIs (deselect with -m 'not live_llm')",
]
```
Note the house style: a `#` comment directly above the option explaining *why* it's set, then the value as a list literal. Apply the same style to the new `[tool.ruff]` block per D-01/D-02/D-03/D-06:
```toml
[tool.ruff]
line-length = 100  # D-02: measured tradeoff — 100 is manageable; 88 hits 1,297 lines.

[tool.ruff.lint]
# D-01: curated production ruleset (not bare defaults) — import sorting, bugbear,
# pyupgrade, simplify, on top of the pyflakes/pycodestyle-error baseline.
select = ["E", "F", "I", "B", "UP", "SIM"]
# D-03: zero blanket ignores — every violation is fixed or individually noqa'd
# with a stated reason inline. No per-file-ignore blocks (D-03).
```
`ruff` is already declared in `[dependency-groups].dev` (line 27) — no dependency change needed, config-only addition.

---

### `README.md` badge (doc, request-response)

**No existing analog** — this README currently has zero badges (confirmed via grep: no `shields.io` or `badge` references). This is the first badge added to the doc.

**Standard GitHub Actions badge markdown** (house-neutral, follows the universal shields.io-via-GitHub convention; insert directly under the H1 title per D-15, single badge, no eval badge row):
```markdown
# Payroll Agent

[![CI](https://github.com/pjnhek/payroll_agent/actions/workflows/ci.yml/badge.svg)](https://github.com/pjnhek/payroll_agent/actions/workflows/ci.yml)

**▶ [Live App (Live & Deployed)](https://payroll-agent.onrender.com/)**
```
Repo slug confirmed via `git remote -v`: `pjnhek/payroll_agent`. The badge URL path (`actions/workflows/ci.yml/badge.svg`) is GitHub's own generated-badge endpoint keyed to the workflow filename — it will exist automatically once `ci.yml` is committed and has at least one run; no separate badge configuration needed.

---

### Repo-wide lint cleanup (`app/`, `eval/`, `scripts/`, `tests/`)

**No single analog file** — this is a fix-in-place task across the whole tree. Measured baseline (2026-07-08, curated ruleset `E,F,I,B,UP,SIM` at `--line-length 100`, this run superseding the smaller default-rules count in CONTEXT.md's `code_context`):

```
134  E501    line-too-long                          [not autofixable]
 82  I001    unsorted-imports                        [autofixable]
 64  UP017   datetime-timezone-utc                   [autofixable]
 46  SIM117  multiple-with-statements                 [autofixable — SAFE fix under ruff 0.15.18, NOT unsafe-fix-only as originally measured; corrected below]
 30  F401    unused-import                            [autofixable]
 16  UP037   quoted-annotation                        [autofixable]
  8  B904    raise-without-from-inside-except        [not autofixable]
  7  B007    unused-loop-control-variable             [not autofixable]
  7  F821    undefined-name                           [not autofixable]
  6  SIM115  open-file-with-context-handler           [not autofixable]
  3  B905    zip-without-explicit-strict              [not autofixable]
  3  E402    module-import-not-at-top-of-file          [not autofixable]
  3  SIM300  yoda-conditions                          [autofixable]
  2  F841    unused-variable                          [not autofixable]
  1  B017    assert-raises-exception                  [not autofixable]
  1  SIM108  if-else-block-instead-of-if-exp          [not autofixable]
  1  UP035   deprecated-import                        [autofixable]
  1  UP042   replace-str-enum                         [not autofixable]
  1  UP047   non-pep695-generic-function              [not autofixable]
Found 416 errors. 241 fixable with --fix (15 more with --unsafe-fixes).
```

**CORRECTED (2026-07-08, empirically re-verified during Phase 12 revision against ruff 0.15.18, the version pinned in uv.lock):** The `[unsafe-fix only]` classification above for SIM117 was WRONG. Running `uv run ruff check --fix .` (config present, no other flags) on the live repo measurably fixes **315 violations, leaving 176** — i.e. plain `--fix` silently collapses 45 of the 46 SIM117 sites (only `app/db/seed.py:307` survives, because ruff does not mark that one specific site `[*]`-eligible). SIM117 is a SAFE fix in ruff 0.15.18, not unsafe; the `[-]` marker `ruff check --statistics` prints next to SIM117 in the default view means "fixable but not counted toward the plain `--fix` total shown in that summary line," which is a display quirk, not a safety gate — it is unrelated to `--unsafe-fixes` (which only gates a separate, smaller set of 15 fixes ruff itself flags as behaviorally risky).

**Practical consequence:** the original plan (196 fixed / 220 remaining split between Plan 12-01 mechanical autofix and Plan 12-02 hand-fix) is invalid — plain `--fix` fixes 315, not 196, and would have already resolved 45/46 SIM117 sites as an undocumented side effect of the "mechanical, no-control-flow-touched" commit. The corrected split (per user decision, superseding this table's original numbers) uses `uv run ruff check --fix --unfixable SIM117 .` in Plan 12-01: **269 fixed, 222 remaining**, with all 46 SIM117 sites fully preserved for Plan 12-02's deliberate, diff-inspected, bisectable structural-collapse pass. The 222 remaining also includes E402 at 5 sites rather than 3 — two new sites appear in `tests/test_calculate.py:81/84` as a knock-on effect of I001/UP037 reformatting a single-line `# noqa: E402`-commented import into a multi-line parenthesized import, orphaning the noqa from the newly-created line; Plan 12-02 Task 1's per-file E402 handling covers this.

**F821 fix pattern (D-04)** — 7 occurrences, all quoted forward-reference return-type annotations in test helper functions that locally import the referenced model. Example site, `tests/test_calculate.py` (function signature only; full body not needed — the fix is import-location only):
```python
# Current (flagged F821 because "Employee" is a bare string the checker can't resolve
# without a real import in scope at any point in the module):
def _make_salary_employee(*, annual_salary: Decimal, pay_periods_per_year: int, filing_status: str = "single") -> "Employee":
    """Construct a minimal salaried Employee for frequency-invariance tests."""
    from app.models.roster import Employee
    ...
```
Same shape recurs in `tests/test_detect_field_regression.py` (`-> tuple[Roster, "Employee"]`), `tests/test_validate.py` (3 occurrences: `_make_weekly_hourly_employee`, `_make_biweekly_hourly_employee`, `_make_semimonthly_salary_employee`), and 2 more sites. **Fix per D-04**: add `from __future__ import annotations` if not already present (it already is in files like `tests/test_calculate.py` line 8 — confirm per-file) plus a module-level `if TYPE_CHECKING: from app.models.roster import Employee` block, so the forward reference resolves without importing `Employee` eagerly at module scope (avoiding a real circular-import or unnecessary-import problem the local `from app.models.roster import Employee` inside the function body was presumably working around). No existing `TYPE_CHECKING` usage anywhere in the repo (`app/`, `tests/`, `eval/`, `scripts/`) — this introduces the pattern for the first time; apply it consistently across all 7 sites for DRY (per the user's global CLAUDE.md engineering philosophy — flag and consolidate repetition).

**E402 "deliberate late import" pattern** — 3 occurrences, at least one already self-documented with an inline reason comment. `tests/test_gateway.py` line 460:
```python
# ===========================================================================
import resend  # noqa: F401 — installed via 06-01 Task 1; needed for monkeypatching
```
This site already carries a `noqa` — it's an existing individually-justified suppression, consistent with D-03's "noqa allowed only where individually justified with a stated reason." The planner/executor should verify whether the E402 on this exact line is already covered by a `# noqa: E402` too, or only `F401` — if only `F401` is silenced, `E402` will still fire under the new curated ruleset and needs its own justified noqa (D-03), not a structural fix, since the late-import position is intentional (test needs a specific patch/import order documented above the `# ===...` banner). `tests/test_ingest.py` line 125 (`import os` / `import uuid as _uuid_module`) is the same shape — check whether its late-import banner comment likewise documents a deliberate reason before deciding "hand-fix" vs "justified noqa."

**Mechanical autofix majority (CORRECTED):** `I001` (82), `UP017` (64), `F401` (30), `UP037` (16), `SIM300` (3), `UP035` (1) = 196 base classes, but `uv run ruff check --fix .` run plain (no exclusion flag) measurably fixes **315** violations — because SIM117 (46, confirmed SAFE fix under ruff 0.15.18, not unsafe) also gets silently collapsed by plain `--fix`, along with knock-on E501/E402 reformatting. Per user decision (superseding the original "hand-review via `--unsafe-fixes`" framing below), Plan 12-01's autofix task uses `uv run ruff check --fix --unfixable SIM117 .` instead — this fixes **269**, leaving **222**, with SIM117's all 46 sites fully preserved for Plan 12-02's dedicated, diff-inspected, bisectable structural-collapse pass (not gated behind `--unsafe-fixes` at all; SIM117 was never in that 15-fix unsafe set — the `--unsafe-fixes` flag governs a separate, smaller group ruff itself flags as behaviorally risky).

**E501 (134, largest single category, not autofixable)** requires manual line-wrapping — no shortcut; budget the most cleanup time here.

## Shared Patterns

### uv setup recipe (all CI jobs)
**Source:** `.github/workflows/eval.yml` lines 19-27 (identical in all 4 existing workflows)
**Apply to:** Both `lint` and `test` jobs in `ci.yml`
```yaml
- name: Checkout
  uses: actions/checkout@v4
- name: Set up uv + Python 3.12
  uses: astral-sh/setup-uv@v5
  with:
    python-version: "3.12"
- name: Install deps (all groups)
  run: uv sync
```

### Hermeticity via two-factor env guards
**Source:** `tests/conftest.py` (`_HAS_DB` + `ALLOW_DB_RESET` guard) and `tests/test_live_llm.py` (`ALLOW_LIVE_LLM` guard) — referenced in CONTEXT.md code_context, not re-read here since CONTEXT.md already extracted the guard names and this pattern only needs to be *not triggered* (by omission) in `ci.yml`'s `test` job, not modified.
**Apply to:** `ci.yml`'s `test` job — simply don't set `DATABASE_URL`, `ALLOW_DB_RESET`, or `ALLOW_LIVE_LLM` in that job's env, and the existing conftest-level guards skip DB/live-LLM tests automatically. This is the reason D-11 calls the test job "bare `uv run pytest -q` with no DB service and no marker flags."

### Concurrency group shape
**Source:** `.github/workflows/deploy-migrate.yml` lines 18-20
**Apply to:** `ci.yml` top-level `concurrency:` block, with `cancel-in-progress` flipped to `true` per D-09 and group keyed per-branch (`ci-${{ github.ref }}`) rather than the static `deploy-migrate` literal, since ci.yml runs on every branch and must not cross-cancel unrelated branches.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `README.md` badge markup | doc | request-response | No badge exists anywhere in the current README; this is a first-of-its-kind addition, resolved via the universal GitHub Actions badge convention rather than an in-repo analog. |
| `ci.yml`'s exact 2-parallel-unconditional-job shape | config | event-driven | `eval.yml` is the closest sibling but its 2nd job (`record`) is conditionally gated, not a parallel peer — `ci.yml`'s lint/test symmetry has no existing precedent in this repo and is assembled from the shared setup recipe + D-10's explicit requirement. |

## Metadata

**Analog search scope:** `.github/workflows/` (all 4 files read in full), `pyproject.toml` (full file, 44 lines), `README.md` (first 60 lines), `app/`, `eval/`, `scripts/`, `tests/` (scanned via `ruff check --statistics`, not individually read — cleanup is line-level, not file-level, and the violation inventory itself stands in as the "analog" for the fix pattern).
**Files scanned:** 4 workflow files (full read), 1 config file (full read), 1 doc file (partial read), repo-wide ruff scan (416 violations across `app/`, `eval/`, `scripts/`, `tests/`).
**Pattern extraction date:** 2026-07-08
