---
phase: 13-module-structure-boundaries
fixed_at: 2026-07-09T21:30:00-07:00
review_path: .planning/phases/13-module-structure-boundaries/13-REVIEW.md
iteration: 2
findings_in_scope: 2
fixed: 2
skipped: 0
status: all_fixed
cumulative:
  findings_in_scope: 6
  fixed: 6
  skipped: 0
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

---

# Iteration 2 (2026-07-09T21:30:00-07:00)

**Source review:** 13-REVIEW.md (amended 2026-07-10 with WR-05/WR-06 from the Codex post-execution cross-AI review)

**Summary (iteration 2):**
- Findings in scope: 2 (WR-05, WR-06 — the only findings marked "NOT yet fixed"; WR-01..WR-04 were fixed in iteration 1 and were NOT re-touched; IN-01..IN-04 remain out of scope for `fix_scope: critical_warning`)
- Fixed: 2
- Skipped: 0

## Fixed Issues (iteration 2)

### WR-05: BOUND-01 attribute scan is blind to unaliased dotted imports

**Files modified:** `tests/test_bound01_private_imports.py`
**Commit:** 32302e9
**Applied fix:** The attribute scan now resolves dotted `ast.Attribute` receiver chains: a new `_receiver_dotted_path` helper walks any receiver back to its root `ast.Name` and reconstructs the full dotted path (`app.db.repo.runs` for the receiver of `app.db.repo.runs._scrub`); the scan substitutes the root name's binding and resolves the result exactly like aliased/ImportFrom bindings, with the facade-package exemption applied the same way. Unaliased `ast.Import` bindings were also corrected to map root→root (`import a.b.c` binds local name `a` to the ROOT package `a` per Python semantics — the previous root→full-dotted mapping both misattributed bare `a._x` accesses and left dotted receivers unresolvable). Dotted chains that do not land on a first-party module file/package (e.g. `mod.SomeClass._x`, `pathlib.Path._flavour`) are skipped, so no new false-positive class is introduced. Synthetic fixture extended with `module_g.py` pinning the third import shape: `import pkgroot.module_a` + `pkgroot.module_a._private_thing` MUST flag, while `import pkgroot.sub` + `pkgroot.sub._sub_private` (dotted chain landing on a package `__init__.py`) stays facade-exempt. Pinned expected-violation count updated 4 → 5; module docstring updated to document the third receiver shape.
**Verification:** Guard tests pass. Live probe matrix (all four shapes, probe files written under `app/`, scanner invoked, probes deleted):
1. `import app.db.repo as repo_mod; repo_mod._TERMINAL_STATUSES` → EXEMPT (green) ✓
2. `from app.db.repo import runs; runs._scrub` → DETECTED ✓
3. `import app.db.repo.runs; app.db.repo.runs._scrub` → DETECTED (the WR-05 shape) ✓
4. `import app.db.repo; app.db.repo._conn_ctx` → EXEMPT (facade, dotted shape) ✓
Live tree stays clean with zero violations. All probe files deleted before commit; `git status` clean apart from the intended change.

### WR-06: Repo facade omits `_nulltx` from the pre-split attribute surface

**Files modified:** `app/db/repo/__init__.py`
**Commit:** 3e728ce
**Applied fix:** `_nulltx` is re-exported from `app/db/repo/_shared.py` alongside `_conn_ctx` (added to the import line, `__all__`, and the facade docstring's re-export list, with the docstring rewrapped for the 100-char line limit). This restores the full pre-split live attribute surface (13-01 plan must-have) and makes the BOUND-01 guard docstring's existing `_nulltx` claim (IN-01a) true.
**Verification:** `uv run python -c "from app.db import repo; repo._nulltx"` resolves (`<function _nulltx>`; also present in `repo.__all__`). Ruff clean.

## Skipped Issues (iteration 2)

None — both open findings fixed.

## Session verification (iteration 2)

- Full suite after both fixes: **614 passed, 51 skipped** — identical to the iteration-1 worktree baseline (zero delta; the review's 615/50 figure reflects the reviewer's shell `DATABASE_URL`, absent in the fix environment — see iteration 1's baseline control). No new tests collected (fixture assertions extend existing test functions).
- `uv run ruff check .` → clean.
- BOUND-01 guard file: `uv run pytest tests/test_bound01_private_imports.py -q` → 2 passed.

---

_Fixed: 2026-07-09T21:30:00-07:00_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2_
