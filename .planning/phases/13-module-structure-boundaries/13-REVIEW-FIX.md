---
phase: 13-module-structure-boundaries
fixed_at: 2026-07-09T20:15:00-07:00
review_path: .planning/phases/13-module-structure-boundaries/13-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 13: Code Review Fix Report

**Fixed at:** 2026-07-09T20:15:00-07:00
**Source review:** .planning/phases/13-module-structure-boundaries/13-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 4 (fix_scope: critical_warning — WR-01..WR-04; 4 Info findings out of scope)
- Fixed: 4
- Skipped: 0

## Fixed Issues

### WR-01: BOUND-01 scanner's facade-package exemption never fires (search-root/parent confusion)

**Files modified:** `tests/test_bound01_private_imports.py`
**Commit:** 3363ca3
**Applied fix:** `scan_tree_for_violations` now passes `[root_parent]` (the scan root's PARENT — the directory dotted module names resolve against) into `_scan_attribute_violations`, instead of the scan roots themselves; `_is_package_import_target`'s parameter was renamed to `root_parents` with a docstring documenting the WR-01 confusion. Added synthetic fixture `module_e.py` (`import pkgroot as pkg_facade` + `pkg_facade._private_thing`) asserting the facade-boundary exemption branch actually fires, in contrast to module_b's still-flagged submodule import.
**Verification:** Guard tests pass. Live probe `import app.db.repo as repo_mod; repo_mod._TERMINAL_STATUSES` under `app/` no longer flags (gate green with probe present); counter-probe `import app.db.repo.runs as runs_mod; runs_mod._scrub(...)` correctly fails the gate.

### WR-02: BOUND-01 attribute scan is blind to `ImportFrom`-bound modules

**Files modified:** `tests/test_bound01_private_imports.py`
**Commit:** 96680cd
**Applied fix:** The bound-module map now also records `ast.ImportFrom` aliases whose resolved dotted target (`{base}.{alias.name}`, relative forms resolved via `_resolve_import_from_target`) is a first-party module file or package under the root parents (new `_is_first_party_module` helper). TYPE_CHECKING-guarded ImportFroms are skipped (they never run — mirrors the ImportFrom scan). The D-01/D-03 `app.db.repo`-internal plumbing exemption (`_in_declared_plumbing_package`) is now applied in the attribute scan too, mirroring the ImportFrom scan, so a repo submodule binding `_shared` stays legitimate by declared design. Synthetic fixture `module_f.py` pins both: `from pkgroot import module_a as bound_mod` + `bound_mod._private_thing` MUST flag (the previously-invisible class), while `from pkgroot import sub` + `sub._sub_private` is package-facade-exempt (total synthetic violations 3 → 4).
**Verification:** Guard tests pass. Live probe `from app.db.repo import runs; runs._scrub("x")` correctly fails the gate (blind spot closed); probe `from app.db import repo; repo._conn_ctx(None)` passes (facade exemption fires on ImportFrom-resolved targets). Live tree stays clean — the scripts' pre-existing `repo._conn_ctx` facade accesses are now visible AND correctly exempt.

### WR-03: Repo-layer source sweeps hardcode the five aggregate modules

**Files modified:** `tests/test_gateway.py`, `tests/test_clarify.py`
**Commit:** 48a5b64
**Applied fix:** `test_repo_has_no_fstring_sql` and `test_no_clarification_message_id_column_written` now enumerate `app/db/repo` dynamically via `pkgutil.iter_modules(repo_pkg.__path__)` + `importlib.import_module`, concatenating source from every module in the package (including `_shared.py`, previously unswept). A known-module floor assertion (`{"_shared", "demo", "emails", "pipeline_state", "roster", "runs"} <= set(modules)`) guards against a vacuously-empty or lossy enumeration. A future sixth aggregate module is swept automatically.
**Verification:** Both tests pass; ruff clean.

### WR-04: `simulate_reply` outcome logging is inverted

**Files modified:** `app/routes/runs.py`, `app/routes/pipeline_glue.py`
**Commit:** 32ec59d
**Status note:** fixed — requires human verification (inverted-condition class: the new branch keys off the parsed `{"status": ...}` outcome; correctness was traced against `route_reply`'s three return paths and the affected route tests pass, but no test asserts the log lines themselves).
**Applied fix:** `simulate_reply` now parses `json.loads(handled.body)["status"]` (or `"no_header_match"` on `None`) and logs `info("resume scheduled ...")` only for `"resumed"`, with the warning path reporting the actual outcome (`sender_mismatch` / `late_reply` / `no_header_match`). The false "returns a JSONResponse when it did NOT resume" comment is replaced with the true contract. `route_reply`'s docstring in `pipeline_glue.py` now documents the return contract explicitly (JSONResponse on EVERY header match; `None` = no header match only, NOT the success signal). Behavior-preserving: scheduling and guards untouched; diagnostics only.
**Verification:** `tests/test_dashboard.py`, `test_hitl.py`, `test_cr_regressions.py`, `test_webhook.py` all pass (58 passed, 2 skipped); grep confirms no test asserts on the old log strings; ruff clean.

## Skipped Issues

None — all in-scope findings fixed. (IN-01..IN-04 are Info-tier and out of scope for `fix_scope: critical_warning`.)

## Session verification

- Full suite after all fixes: **614 passed, 51 skipped** (worktree environment).
- Baseline control: the **unmodified base commit** (05da4cf) run in an identical environment also yields **614 passed, 51 skipped** — zero delta from the fixes. The review's 615/50 baseline reflects one env-conditional test (shell `DATABASE_URL` present in the reviewer's environment, absent here — all 51 skips are DATABASE_URL / live-key conditional).
- `uv run ruff check .` → clean.

---

_Fixed: 2026-07-09T20:15:00-07:00_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
