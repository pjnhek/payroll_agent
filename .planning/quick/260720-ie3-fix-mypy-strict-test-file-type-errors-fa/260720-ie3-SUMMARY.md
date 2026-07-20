---
quick_id: 260720-ie3
status: complete
one-liner: Resolved all 19 `uv run mypy --strict` errors across 6 test files via casts/generic-type-args/annotation-widening only — zero test-behavior change.
key-files:
  modified:
    - tests/test_queue_durability.py
    - tests/test_pump_workflow.py
    - tests/test_queue_config.py
    - tests/test_demo_landing.py
    - tests/test_ops_route.py
    - tests/test_proof_mutation_targets.py
metrics:
  duration: "~15 min"
  completed: 2026-07-20
---

# Quick Task 260720-ie3: Fix mypy --strict Test-File Type Errors — Summary

## What was done

Applied the plan's 6 enumerated, mechanical type-hygiene edits exactly as specified — casts, generic type-args, and one annotation widening — to clear all 19 `uv run mypy` (strict) errors in `tests/`. No assertion, parametrization, fixture value, or control-flow change was made anywhere.

1. **`tests/test_queue_durability.py`** (7 errors → 0): added `cast` to the existing `from typing import Any` line; cast `results["reclaimed"]` and `outcomes["reclaim"]` to `"Job | None"` at their two binding sites so the existing `assert reclaimed is not None` / `if reclaimed is not None:` checks narrow to `Job` for the `.id`/`.lease_token`/`.attempts` reads. `zombie_completed = outcomes["zombie"]` left untouched (no attribute access on it).

2. **`tests/test_pump_workflow.py`** (3 errors → 0): added `from typing import Any`; changed `_steps() -> list[dict]`, `_drain_index(steps: list[dict]) -> int`, and `_alarm_index(steps: list[dict]) -> int` to use `list[dict[str, Any]]`.

3. **`tests/test_queue_config.py`** (3 errors → 0): added `from typing import Any, cast`; `_workflow_steps() -> list[dict]` → `list[dict[str, Any]]`, with its return wrapped in `cast("list[dict[str, Any]]", ...)` to clear the no-any-return on the `yaml.safe_load` subscript chain; `_proof_running_steps` param and return both widened to `list[dict[str, Any]]`.

4. **`tests/test_demo_landing.py`** (3 errors → 0): `Any` was already imported. Annotated the two `run = {` literals (lines 1226 and 1312 pre-edit) as `run: dict[str, Any] = {` — these are the two functions whose nested `run["decision"]["resolutions"][0][...] = ...` subscript-assignments failed. The two other `run = {` literals (557, 1165) were left untouched — confirmed by grep they do not error and are unrelated.

5. **`tests/test_ops_route.py`** (2 errors → 0): added `from collections.abc import Iterable, Iterator` and `from typing import Any`; annotated the recursive generator `_flatten_routes(routes)` → `_flatten_routes(routes: Iterable[Any]) -> Iterator[Any]`. Used `Any` deliberately for the element type (not a narrower Starlette route type) per the plan's rationale — a narrower type would break the downstream `.path` attribute access and require touching assertions, which the constraints forbid.

6. **`tests/test_proof_mutation_targets.py`** (1 error → 0): widened the first binding inside `_resolve_assignment`'s `ast.Assign` branch from `value = node.value` to `value: ast.expr | None = node.value`, matching the type of the later `ast.AnnAssign` branch's `node.value` (`ast.expr | None`). The existing `if value is None: continue` immediately below both branches already narrows it back to `ast.expr` for downstream use — no logic change.

## Deviations from Plan

None — plan executed exactly as written. All line-number anchors in the plan matched current-master (files had not drifted since the plan was authored the same day).

## Verification (actual command output)

**Baseline (captured before editing):**
```
$ env -u DATABASE_URL uv run pytest -q
...
1303 passed, 107 skipped, 1 warning in 48.29s
```

**mypy — before (confirmed matches plan's enumerated 19 errors exactly):**
```
$ uv run mypy
tests/test_proof_mutation_targets.py:220: error: Incompatible types in assignment ...  [assignment]
tests/test_pump_workflow.py:141: error: Missing type arguments for generic type "dict"  [type-arg]
tests/test_pump_workflow.py:150: error: Missing type arguments for generic type "dict"  [type-arg]
tests/test_pump_workflow.py:160: error: Missing type arguments for generic type "dict"  [type-arg]
tests/test_queue_config.py:179: error: Missing type arguments for generic type "dict"  [type-arg]
tests/test_queue_config.py:181: error: Returning Any from function declared to return "list[dict[Any, Any]]"  [no-any-return]
tests/test_queue_config.py:184: error: Missing type arguments for generic type "dict"  [type-arg]
tests/test_queue_durability.py:2492/2493/2507/2508/2627/2628/2633: error: "object" has no attribute ...  [attr-defined]
tests/test_ops_route.py:87/127: error: Call to untyped function "_flatten_routes" in typed context  [no-untyped-call]
tests/test_demo_landing.py:1297/1385/1386: error: Value of type "object" is not indexable  [index]
Found 19 errors in 6 files (checked 170 source files)
```

**mypy — after:**
```
$ uv run mypy
Success: no issues found in 170 source files
```

**Hermetic pytest — after (identical to captured baseline):**
```
$ env -u DATABASE_URL uv run pytest -q
...
1303 passed, 107 skipped, 1 warning in 48.83s
```

**Diff scope (`git diff --stat`):**
```
 tests/test_demo_landing.py           | 4 ++--
 tests/test_ops_route.py              | 4 +++-
 tests/test_proof_mutation_targets.py | 2 +-
 tests/test_pump_workflow.py          | 7 ++++---
 tests/test_queue_config.py           | 7 ++++---
 tests/test_queue_durability.py       | 6 +++---
 6 files changed, 17 insertions(+), 13 deletions(-)
```
Confirmed: exactly the 6 named test files, no production code, no docs. Full `git diff` reviewed line-by-line — every changed line is an added/edited type annotation, `cast(...)` call, or generic type-arg; no changed assertion, value, or control flow.

Also ran `uv run ruff check` on all 6 files — all checks passed (no new lint issues introduced).

## Commits

- `2335a0c` — `fix(260720-ie3): resolve mypy --strict errors in 6 test files`

## Self-Check: PASSED

- FOUND: tests/test_queue_durability.py (edited, exists)
- FOUND: tests/test_pump_workflow.py (edited, exists)
- FOUND: tests/test_queue_config.py (edited, exists)
- FOUND: tests/test_demo_landing.py (edited, exists)
- FOUND: tests/test_ops_route.py (edited, exists)
- FOUND: tests/test_proof_mutation_targets.py (edited, exists)
- FOUND: commit 2335a0c in `git log --oneline`
