---
phase: 04-the-eval-the-proof
reviewed: 2026-06-22T21:00:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - eval/run_eval.py
  - eval/judge.py
  - eval/draft_candidate_emails.py
  - tests/test_eval_wiring.py
  - .github/workflows/eval.yml
  - pyproject.toml
findings:
  critical: 1
  warning: 4
  info: 3
  total: 8
status: resolved
resolved_in: 744a203
resolution_note: "All 8 findings (CR-01, WR-01..04, IN-01..03) fixed and committed. 314 tests pass, ruff clean, --check green."
---

# Phase 04: Code Review Report

**Reviewed:** 2026-06-22T21:00:00Z
**Depth:** standard
**Files Reviewed:** 6
**Status:** issues_found

## Summary

Reviewed the Phase 4 eval harness: the scorer (`eval/run_eval.py`), the LLM-as-judge (`eval/judge.py`), the throwaway draft helper (`eval/draft_candidate_emails.py`), the D-09 wiring smoke test (`tests/test_eval_wiring.py`), the CI workflow (`.github/workflows/eval.yml`), and `pyproject.toml`.

The core scoring math (F1/precision/recall, confusion matrix, per-category aggregation) is correct. The DB-free / lazy-import discipline on the `--check`/scoring paths is well-executed. The `false_process` headline metric is correctly defined and the confusion matrix highlights the right cell. The D-09 wiring test correctly drives the full production spine.

Two issues stand out: the CI `record` job writes extraction caches to the ephemeral runner disk and then discards them (no commit/push step), making the entire `--live_record` trigger a silent no-op in CI. And the `gate_reasons_contains` substring check joins all gate reasons into one string before matching, which can produce false positives when a required substring straddles two adjacent reasons.

---

## Critical Issues

### CR-01: `record` job in eval.yml writes extraction caches to ephemeral CI disk — files are silently discarded

**File:** `.github/workflows/eval.yml:36-54`
**Issue:** The `record` job runs `uv run python eval/run_eval.py --record`, which writes `*_extraction.json` files to the checkout directory on the GitHub Actions runner. There is no `git commit` / `git push` step in the job. When the runner terminates the files are gone. A developer triggering `workflow_dispatch` with `live_record=true` would see a green run but no extraction caches would be updated in the repository. The next `--check` run on `push` would still compare against the old cached extractions, and the "re-record" intent is entirely defeated.

This is a **behavioral lie**: the workflow advertises "Re-record extraction cache" but produces no durable artifact.

**Fix:** Add a commit-and-push step after the re-record step, for example using `stefanzweifel/git-auto-commit-action` or a manual `git` sequence. The commit should only fire when files actually changed (to avoid empty commits):

```yaml
      - name: Commit updated extraction caches
        uses: stefanzweifel/git-auto-commit-action@v5
        with:
          commit_message: "chore(eval): re-record extraction caches [skip ci]"
          file_pattern: "eval/fixtures/*_extraction.json"
```

Alternatively, document explicitly that `--record` must be run locally and the workflow trigger removed or relabeled as a validation-only dry run.

---

## Warnings

### WR-01: `gate_reasons_contains` check joins all gate reasons before substring matching — can produce false positives at reason boundaries

**File:** `eval/run_eval.py:294-296`
**Issue:** The fixture scorer uses `gate_reasons_contains` to do a flexible substring check on gate reasons:

```python
joined = " ".join(decision.gate_reasons)
gate_reasons_match = all(s in joined for s in gate_reasons_contains)
```

Joining all reasons with a space before applying `in` means a required substring can match across two adjacent reasons. For example, if `gate_reasons[0]` ends with `"name: foo"` and `gate_reasons[1]` starts with `"bar baz"`, a `gate_reasons_contains` entry of `"foo bar"` would match even though no single reason contains `"foo bar"`. This means `gate_struct_ok=True` can be reported for a fixture where the individual reason does not contain the expected string — the metric passes for the wrong structural reason.

Current fixture substrings (`"D. Reyes"`, `"Dave Reyes"`) are short names that appear whole within a single reason, so no false match fires today. But the logic is fragile for any future fixture where a substring could coincidentally straddle the join boundary.

**Fix:** Match each required substring against the individual reasons, not the joined string:

```python
gate_reasons_match = all(
    any(s in reason for reason in decision.gate_reasons)
    for s in gate_reasons_contains
)
```

---

### WR-02: Bare `except Exception: continue` in `judge.py` silently disables the D-16 correctness floor

**File:** `eval/judge.py:207-208`
**Issue:** `_load_fixture_expected_employee` wraps its entire inner loop body (JSON load, fixture-ID match, `seed()` call, employee lookup) in a bare `except Exception: continue`. If anything fails — a malformed fixture JSON, a seed import error, a UUID comparison exception — the function silently returns `None`. `judge_draft` then skips the D-16 floor entirely (`if raw_score > 1 and expected_employee_full_name:` never enters), so a draft that names a real but wrong employee would receive a score > 1 instead of being capped at 1. The correctness floor is the central safety property of the judge and it must not be bypassed silently.

```python
# Current — too broad:
        except Exception:
            continue
```

**Fix:** Narrow the exception handling to only swallow `json.JSONDecodeError` and `KeyError` for genuinely malformed fixtures, and let unexpected failures propagate or at least print a warning:

```python
        except (json.JSONDecodeError, KeyError):
            continue
        except Exception as exc:
            print(f"  [judge warn] unexpected error loading fixture {fixture_path}: {exc}")
            continue
```

---

### WR-03: `numpy` used in `_write_svg_chart` but not declared in `pyproject.toml`

**File:** `eval/run_eval.py:680` / `pyproject.toml`
**Issue:** `_write_svg_chart` imports `numpy` (line 680) and uses it for `np.arange`. `numpy` is not listed in `pyproject.toml` under either `[project.dependencies]` or `[dependency-groups].dev` — only `matplotlib>=3.11.0` is declared. Today `numpy` arrives as an undeclared transitive dependency of `matplotlib`, but transitive dependency availability is not guaranteed across `matplotlib` versions or in alternate resolver outputs. A future `uv lock` update or a resolver change could break the `--chart` path silently.

**Fix:** Add `numpy` explicitly to the dev dependency group:

```toml
[dependency-groups]
dev = [
    "matplotlib>=3.11.0",
    "numpy>=1.26.0",
    "pytest",
    "ruff",
]
```

---

### WR-04: `test_eval_wiring.py` does not assert `fica_medicare` or `net_pay` — wiring test has incomplete golden coverage

**File:** `tests/test_eval_wiring.py:98-109`
**Issue:** The D-09 wiring test drives the full spine through `_compute_line_items` and asserts `gross_pay`, `pretax_401k`, `federal_withholding`, and `fica_ss` — but does NOT assert `fica_medicare` or `net_pay`. The comment says "no second net_pay oracle" but `fica_medicare` has a known oracle value (wages × 1.45%, straightforward for Thomas Bergmann), and `net_pay` is the final output that hiring managers/recruiters would scrutinize in a demo. A miscalculation in either field would pass the D-09 wiring gate. Given the project doc states "Well-tested is non-negotiable" and this is the highest-stakes calc unit, the partial golden is a gap.

**Fix:** Add the two missing assertions using computable oracle values:

```python
# fica_medicare: $9,230.77 gross * 1.45% = $133.85 (pretax 401k does not reduce Medicare base)
# net_pay = gross_pay - pretax_401k - fica_ss - fica_medicare - federal_withholding
expected_net = Decimal("9230.77") - Decimal("738.46") - Decimal("37.20") - Decimal("133.85") - Decimal("881.39")
assert item.fica_medicare == Decimal("133.85"), "D-09 wiring: fica_medicare"
assert item.net_pay == expected_net, "D-09 wiring: net_pay"
```

(Verify `fica_medicare` exact rounding against the Phase-3 golden before committing.)

---

## Info

### IN-01: Redundant `import uuid as _uuid` inside `_record_extraction` — `uuid` is already imported at module level

**File:** `eval/run_eval.py:632`
**Issue:** `_record_extraction` contains `import uuid as _uuid` with a `# noqa: PLC0415` comment implying it is an intentional lazy import. However `import uuid` already appears at line 26 (module level). `uuid` is a stdlib module with no connection to `app.config`/`DATABASE_URL`, so the lazy-import discipline does not apply. The alias `_uuid` is also immediately used on line 646 (`_uuid.uuid4()`), making it easy to accidentally miss the top-level `uuid` and be confused about which is canonical.

**Fix:** Remove the redundant lazy import and use the top-level `uuid` directly:

```python
# Remove line 632: import uuid as _uuid  # noqa: PLC0415
# Change line 646:
run_id = uuid.uuid4()  # uses the module-level import
```

---

### IN-02: `seed()` docstring says "6 employees" but the actual count is 7 (Employee 7 — Daniel Reyes added for collision coverage)

**File:** `app/db/seed.py:276`
**Issue:** The `seed()` function docstring reads: `"Seed 3 businesses and 6 employees into the live DB."` The module-level docstring on line 3 correctly says 7 employees, and the `_EMPLOYEES` list contains 7 entries. The function docstring was not updated when Employee 7 (Daniel Reyes) was added for the D-21-02 collision-safety pair. The `print` statement at line 401 will correctly show 7 at runtime, but the docstring misleads readers into thinking the count was intentionally 6.

**Fix:** Update the `seed()` docstring line 276:

```python
"""Seed 3 businesses and 7 employees into the live DB.
```

---

### IN-03: `draft_candidate_emails.py` imports `app.config` and `app.llm.client` at module top level, violating the project's lazy-import discipline for eval scripts

**File:** `eval/draft_candidate_emails.py:8-9`
**Issue:** The other eval scripts (`run_eval.py`, `judge.py`) use lazy imports for anything that transitively calls `get_settings()`, because `Settings.database_url` has no default and fails immediately when `DATABASE_URL` is absent. `draft_candidate_emails.py` imports both `app.config.get_settings` and `app.llm.client.call_text` at the top level, meaning any import of this file (or `pytest` accidentally collecting it) would require `DATABASE_URL` to be set. The script is documented as a throwaway and is not currently imported by anything, so there is no active breakage — but it is inconsistent with the discipline applied everywhere else in the eval directory and could bite a future contributor who imports it.

**Fix:** Move both imports inside `_require_live_llm()` and `if __name__ == "__main__":`, mirroring the pattern used in `judge.py`. The top-level of the file should only contain stdlib imports and constants.

---

_Reviewed: 2026-06-22T21:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
