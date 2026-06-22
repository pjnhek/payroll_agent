---
phase: 4
reviewers: [codex]
reviewed_at: 2026-06-22T18:31:29Z
rounds: 4
plans_reviewed: [04-01-PLAN.md, 04-02-PLAN.md, 04-03-PLAN.md, 04-04-PLAN.md]
reviewer_versions:
  codex: codex-cli 0.135.0
---

# Cross-AI Plan Review — Phase 4 (The Eval)

> **Four review rounds, appended in order below.** R1: 13 findings (scoring credibility). R2: confirmed all 13 fixed; found 8 new (2 HIGH cross-plan-consistency bugs the R1 edits introduced + 6 MED/LOW). R3: confirmed all 8 R2 fixes + no regressions; found 1 HIGH (the D-09 test didn't actually test decide→calculate wiring — it had survived all prior rounds) + 3 MED/LOW. R4: confirmed all 4 R3 fixes + no regressions; found 2 (1 MED `--record` advertised-live-but-stub + 1 LOW `--db` skip crashes on absent DATABASE_URL), both on the optional/honesty seam. All findings across all rounds resolved. Finding rate: 13 → 8 → 4 → 2.

---

# Round 1

## Codex Review

## Summary

The plans are directionally strong and mostly aligned with the phase thesis: they preserve the DRY seam by importing production `reconcile_names`, `validate`, and `decide`; they make false-process visible; and they keep the judge/DB work optional. However, there are several credibility-breaking issues that should be fixed before execution. The biggest problems are that extraction caches are planned as hand-authored "correct stubs," path-A deterministic scoring uses cached extraction instead of labeled expected extraction, reconciliation scoring ignores `matched_employee_id`, and the false-process rate/chart are defined incorrectly enough to mislead.

## Strengths

- The DRY-seam intent is explicit: `run_eval.py` imports the real `reconcile_names`, `validate`, and `decide`, not parallel logic.
- The phase is sensibly split: fixture corpus, scorer, chart/CI, then optional judge/DB.
- D-09 is well scoped: one `calculate()` smoke test reusing the Phase-3 Thomas Bergmann golden, avoiding a second net-pay oracle.
- The suite includes multiple intended `process` fixtures, so "always clarify" is at least visible as a bad baseline.
- CI correctly aims to use the same `run_eval.py --check` entrypoint, not a separate scorer.
- Scope discipline is mostly good: 04-04 is explicitly optional and 04-01..03 are intended to ship alone.

## Concerns

- **HIGH — 04-01 Task 1 / 04-02 Task 2:** The `_extraction.json` files are described as "stubbed" caches that match expected extraction. That makes extraction F1 artificially perfect and does not test the real LLM extraction failure mode D-06 is meant to catch. If these are not raw recorded extractor outputs, the extraction metric is not credible.
- **HIGH — 04-02 Task 2:** Path-A deterministic scoring is wrong as written. D-07 says isolated scoring should feed the labeled expected extraction into `reconcile_names → validate → decide`; the plan feeds `actual_extracted` from cache. Once caches become real LLM output, deterministic decision accuracy becomes confounded by extraction errors.
- **HIGH — 04-02 Task 2:** Reconciliation scoring ignores `expected_matched_employee_id`. It only checks `source` and `resolved`, so a wrong-but-real match can pass as correct. That directly violates D-02's reason for labeling the intended employee.
- **HIGH — 04-02 Task 2 / 04-03 Task 1:** The false-process rate denominator is likely wrong. The plan uses `false_process / (false_process + true_process)`, which is "among actual process decisions, how many were wrong." The risk metric should be at least reported as `false_process / expected_clarify_total`, because the dangerous failure is "cases that should clarify but processed."
- **HIGH — 04-03 Task 1:** The chart highlights the wrong confusion-matrix cell. With the proposed table, `table[1, 2]` is false-process; `table[2, 2]` is true-clarify. The current plan would visually mark the safe cell as dangerous.
- **HIGH — 04-01 Task 1:** Several fixture instructions show wrong employee UUIDs, e.g. `00000000-...0001` instead of seeded `e0000001-...0001`. The validation script does not check `expected_matched_employee_id` against seed data, so bad labels could silently land.
- **MEDIUM — 04-02 Task 2:** Extraction precision/recall uses dicts keyed by normalized name, which collapses duplicate extracted employees. A duplicated pay line is a dangerous extraction failure and should count as an extra/hallucinated employee, not disappear during scoring.
- **MEDIUM — 04-02 Task 2:** `--check` appears to compare only a subset of metrics. It should include gate-structure accuracy, per-category decision fractions, confusion counts, reconciliation counts, and extraction field accuracy, or regressions can pass CI.
- **MEDIUM — 04-02 Task 2 / 04-03 Task 1:** The chart leads with extraction F1, but the phase requirement says extraction field accuracy. Employee-set F1 alone can stay perfect while hours are wrong. Field accuracy should be first-class in summary and chart.
- **MEDIUM — 04-02 Task 2:** `_write_summary_json()` imports `app.config` to get `extraction_model_id`, which requires `DATABASE_URL`. That makes local eval require `DATABASE_URL=placeholder`, even though eval should be DB-free by default.
- **MEDIUM — 04-04 Task 1:** The DB write is said to derive from `summary.json`, but the action writes from in-memory `fixture_results`/`aggregated`. That breaks the "summary is authoritative" rule.
- **LOW — 04-03 Task 2:** The YAML verification uses `import yaml`, but PyYAML is not a declared dependency. Either add it as dev-only or verify with a simpler grep/parse strategy.
- **LOW — 04-04 Task 1:** The verification command masks failure with `|| echo`, so a broken `--db` implementation could appear acceptable.

## Suggestions

- **04-01 Task 1:** For D-05 caches, require a separate `*_extraction.json` generated by `--record`, with metadata showing model ID and recorded timestamp. Include at least one fixture whose cache deliberately diverges from expected (invented employee / hours) so F1 < 1.0 is demonstrable.
- **04-02 Task 2:** Implement two explicit inputs: `expected_extracted = Extracted.model_validate(...)` for isolated deterministic scoring (path A), and `cached_extracted` only for extraction scoring or optional end-to-end scoring (path B).
- **04-02 Task 2:** Reconciliation correctness should require `source`, `resolved`, and `matched_employee_id` to match expected. For unresolved cases, assert `matched_employee_id is None`.
- **04-02/04-03:** Report false-process as both count and rate over expected-clarify cases: `false_process / (false_process + true_clarify)`. Optionally also show precision-style `false_process / actual_process_total`, but do not make that the headline.
- **04-03 Task 1:** Fix the confusion-matrix cell highlight to `table[1, 2]`.
- **04-01 Task 1:** Add fixture validation that every non-null `expected_matched_employee_id` exists in the roster for that fixture's `from_addr`.
- **04-02 Task 2:** Use multiset/list alignment for extracted employees so duplicates count as false positives.
- **04-02/04-03:** Make extraction field accuracy visible in `summary.json`, `--check`, and `chart.svg`, not only employee-set F1.
- **04-02 Task 2:** Avoid importing `app.config` for `extraction_model_id` during normal eval. Read `EXTRACTION_MODEL` from env with a default, or catch settings failure and record the default model string.
- **04-04 Task 1:** If implemented, load `eval/summary.json` inside `_write_db_results()` and derive rows from that parsed object.

## Risk Assessment

**HIGH** until the extraction-cache and scoring issues are corrected. The plan has the right architecture, but as written it can produce a polished chart that overstates proof: hand-authored extraction caches hide LLM invention, deterministic scoring is not isolated, wrong-real name matches can pass, and the false-process headline can be mathematically misleading. Once those are fixed, the phase risk drops to **MEDIUM/LOW** because the DRY production-function seam and CI shape are otherwise solid.

---

## Consensus Summary

Single reviewer (Codex). Findings independently verified against the plan text and the codebase before acceptance:

### Verified-correct, accepted for fix
1. **Hand-authored extraction caches make F1 vacuously perfect** (HIGH) — the D-06 invention-guard tests nothing as written. Confirmed: 04-01 Task 1 says the stub "MATCHES what a correct extraction would return."
2. **Path-A feeds cache, not labeled expected** (HIGH) — confirmed at 04-02:204-210; contradicts D-07's "feed the labeled expected extraction" for isolated scoring.
3. **Reconciliation ignores `matched_employee_id`** (HIGH) — confirmed at 04-02:234-238; a wrong-but-real match passes, defeating D-02's stated purpose.
4. **Chart highlights `table[2,2]` (true-clarify, the SAFE cell)** (HIGH) — confirmed at 04-03:145-146; false-process is at `table[1,2]`. Verified against matplotlib 0-indexed-including-header table semantics.
5. **Wrong/malformed seed UUIDs in fixtures** (HIGH) — confirmed: plan writes `00000000-...-00000000001` (wrong prefix + 11-digit final group); real seed UUIDs are `e0000001-0000-0000-0000-000000000001` (verified in app/db/seed.py:80). No validation guards `expected_matched_employee_id`.
6. **Dict-keyed extraction collapses duplicate employees** (MEDIUM) — a duplicated pay line is a dangerous failure that should count as a false positive.
7. **`--check` compares only a metric subset** (MEDIUM) — gate-structure / decision / field-accuracy regressions could pass CI.
8. **Extraction *field* accuracy under-surfaced vs employee-set F1** (MEDIUM) — EVAL-04 specifies "extraction field accuracy"; F1 can be perfect while hours are wrong.
9. **Normal eval requires `DATABASE_URL=placeholder`** (MEDIUM) — `_write_summary_json` imports `app.config` for the model id; eval should be DB-free.
10. **DB write derives from in-memory, not `summary.json`** (MEDIUM) — confirmed at 04-04:95; violates "summary is authoritative."
11. **`|| echo` masks `--db` failure in verify** (LOW) — confirmed at 04-04:105.

### Accepted with modification
- **False-process denominator** (HIGH): the **count** is the unambiguous headline and stays loudest; add the risk-style rate `false_process / (false_process + true_clarify)` = false_process / expected_clarify_total as the primary rate, and keep (optionally) the precision-style rate clearly labeled — do NOT make precision-style the headline.

### Pushed back / down-scoped
- **PyYAML not declared** (LOW): rather than add a dep, the verify is switched to a dependency-free parse so the eval doesn't grow a dev dependency just for a CI-yaml smoke check.

All fixes applied directly to the plan files (concrete + surgical); see commit. The DRY seam, D-09 golden reuse, hermetic-CI shape, and scope tiering were confirmed sound and unchanged.

---

# Round 2 (re-review after Round-1 fixes)

## Codex Review (Round 2)

**Summary.** Round-2 fixes are directionally stronger, especially PATH-A isolation, `matched_employee_id` scoring, Counter-based extraction alignment, and the false-process denominator/cell. Two hard blockers found: 04-03 called `_write_summary_json` with the wrong signature, and 04-01 allowed `pay_period_start: null` while 04-02 validates it as required. (Codex also independently checked `astral-sh/setup-uv@v5` action metadata and confirmed `python-version` is a valid input — no CI-action finding.)

### Prior-fix verification (all 13)
- CONFIRMED-FIXED (11): #2 PATH-A isolation, #3 reconciliation matched_employee_id, #4 false-process denominator, #5 chart dangerous cell (`table[1,2]` re-derived correct), #6 seed UUIDs + roster validation, #7 duplicate alignment (Counter), #8 `--check` breadth, #9 field accuracy first-class, #11 DB write derives from summary, #12 PyYAML fallback, #13 `--db` failure masking.
- PARTIALLY-FIXED (2): #1 extraction caches (divergence now required, but `--record` is still a stub so caches aren't raw recorded output — by D-07 design; honesty framing added); #10 DB-free eval (main path fixed, but the 04-02 threat-model text still claimed `_write_summary_json` imports config / DATABASE_URL required).

### New findings (Round 2)
- **HIGH — 04-03 Task 1:** `_write_summary_json(fixture_results, aggregated)` called with 2 args; 04-02 requires `suite_run_id` 3rd arg. (Introduced by the Round-1 signature change.)
- **HIGH — 04-01/04-02 schema mismatch:** 04-01 allowed `expected.extracted.pay_period_start: null`; `Extracted.pay_period_start` is required non-null and `_expected_to_extracted` validates through it.
- **MEDIUM — 04-01:** divergence validation only checked `divergent >= 2`, didn't enforce one precision-miss + one field-miss, and used dicts (collapses duplicate-only divergence).
- **MEDIUM — 04-01:** contradictory `_note`-in-cache instruction (cache is `extra="forbid"`).
- **MEDIUM — 04-01:** bad fixture examples — whitespace "typo" normalizes to exact; James Okafor is SALARY (bad missing-hours candidate).
- **MEDIUM — 04-04:** DB rows referenced per-fixture `reconciliation_accuracy` scalar; 04-02 per-fixture result has a reconciliation LIST, not a scalar.
- **LOW — 04-04:** judge verification still masked failures with `|| echo`.
- **LOW — 04-04:** objective said `run_eval.py` gets a `--judge` flag; task says judge.py is standalone.

**Overall risk (Round 2): HIGH until the signature mismatch + nullable pay-period schema are fixed.**

## Round-2 Resolution (all applied — see commit)

| Finding | Sev | Resolution |
|---------|-----|------------|
| `_write_summary_json` signature | HIGH | 04-03 now keeps 04-02's 3-arg call (`…, suite_run_id`) and only ADDS the chart step; no second/2-arg call. |
| `pay_period_start` nullable | HIGH | 04-01 schema marks it REQUIRED non-null; validation script asserts `exp['extracted']['pay_period_start']` truthy on every fixture. |
| divergence one-of-each | MED | validator now requires ≥1 precision-miss (multiset difference) AND ≥1 field-miss, using `Counter` (no dict collapse). |
| `_note` contradiction | MED | removed `_note`-in-cache; divergences recorded in a sidecar `eval/fixtures/DIVERGENCES.md`; cache stays pure `Extracted` JSON. |
| bad fixture examples | MED | typo fixtures use character-level misspellings (not whitespace); missing-hours uses Maria (hourly); fixture 13 reassigned to David Reyes by exact full name (hourly, distinct business); files_modified renamed `_coastal`→`_metro`. |
| DB `reconciliation_accuracy` | MED | 04-04 derives the scalar from the per-fixture reconciliation list (`correct/total`); every metric's extraction path from the entry is now spelled out. |
| judge `\|\| echo` mask | LOW | replaced with an `rc`-capture + sentinel-grep that only passes on a genuine SystemExit. |
| `--judge` flag inconsistency | LOW | objective corrected: judge.py is standalone, no `--judge` on run_eval.py. |
| #10 stale threat-model text | (carry) | 04-02 trust-boundary + T-04-07 rows rewritten: DB-free scoring/--check, app.config only on --record. |
| #1 honesty | (carry) | 04-03 chart adds a gray caption: extraction scored against replayed caches (not a live model run) until --record. |

---

# Round 3 (re-review after Round-2 fixes)

## Codex Review (Round 3)

**Summary.** Not a rubber stamp. All 8 Round-2 fixes CONFIRMED-FIXED; no Round-1 fix regressed; the cross-plan summary.json key contract is coherent (04-03 and 04-04 only read keys 04-02 produces). One HIGH new issue that had survived all prior rounds: the D-09 "decide→calculate wiring" test only called `calculate()` directly — duplicating the Phase-3 golden and testing NONE of the wiring it claims to close. Plus 3 medium/low execution cleanups.

### Round-2 fix verification — all 8 CONFIRMED-FIXED
signature mismatch · nullable pay_period_start · divergence one-precision+one-field via Counter · `_note` contradiction · bad fixture examples (incl. David-full-name exact resolve validated against seed) · DB reconciliation_accuracy from list · judge `|| echo` mask · `--judge` flag inconsistency. **Regression check: none.** Scope discipline intact; 04-01..03 still shippable without 04-04.

### New findings (Round 3)
- **HIGH — 04-02 Task 1:** the D-09 "decide→calculate wiring smoke test" did NOT test decide→calculate wiring — it only called `calculate(zero_hours, thomas_bergmann)` directly, duplicating the existing Phase-3 calculate golden and exercising none of the `reconcile_names → validate → decide → calculate` join D-09 exists to close.
- **MEDIUM — 04-01 Task 1:** the recommended precision-miss host was misleading — "fabricate hours for Maria on 07" is a same-name FIELD miss, not a PRECISION miss (the validator counts precision only when `cache_names - exp_names` has an extra employee). Following 07/08 literally would make both field misses and fail the `precision_miss_fixtures >= 1` assertion.
- **MEDIUM — 04-03 frontmatter:** `uv add --dev matplotlib` updates `uv.lock`, but `uv.lock` was missing from `files_modified` — a commit/CI reproducibility miss.
- **LOW — 04-03 verify:** the final automated verify used `DATABASE_URL=placeholder` for `--chart`/`--check` while the action text says DB-free `env -u DATABASE_URL`, so it wouldn't catch a reintroduced config import.

**Overall risk (Round 3): HIGH until the D-09 wiring test is corrected; otherwise MEDIUM/LOW.**

## Round-3 Resolution (all applied — see commit)

| Finding | Sev | Resolution |
|---------|-----|------------|
| D-09 doesn't test wiring | HIGH | Rewrote tests/test_eval_wiring.py: it now drives `12_exact_process_summit` through reconcile_names → validate → decide, asserts `final_action=="process"`, then computes the paystub via the PRODUCTION `app.pipeline.orchestrator._compute_line_items` (the exact decide→calculate join) and asserts the Thomas Bergmann Phase-3 golden. Acceptance criteria + key_links + must_haves updated to require the orchestrator import and `_compute_line_items` (not a bare `calculate()` call). Still no second net_pay oracle — reuses the trusted golden. |
| precision-miss host misleading | MED | 04-01 now specifies the PRECISION miss as a PHANTOM employee on a multi-employee fixture (name not in expected → `cache_names - exp_names` non-empty) and the FIELD miss as wrong hours on a same-name employee (08); the two live on different fixtures so both validator assertions fire. Removed the contradictory "07 fabricates Maria's hours = invention" note. |
| uv.lock missing from files_modified | MED | Added `uv.lock` to 04-03 `files_modified`; the `uv add --dev` step + acceptance criteria now require committing both pyproject.toml and uv.lock. |
| 04-03 verify used =placeholder | LOW | All 04-03 run-command verifies (task + final verification block) switched to `env -u DATABASE_URL` so a reintroduced app.config import on the scoring/chart path is caught, not masked. (eval.yml's own `DATABASE_URL: "placeholder"` stays — harmless belt-and-suspenders; the record job needs it.) |

---

# Round 4 (re-review after Round-3 fixes)

## Codex Review (Round 4)

**Summary.** All 4 Round-3 fixes CONFIRMED-FIXED; no earlier fix regressed. Codex verified the D-09 rewrite end-to-end — confirming `validate.py:57` explicitly allows a salaried employee with null hours, so the test's `final_action=="process"` precondition genuinely holds, and `_compute_line_items` requires the matched id in the roster (which fixture 12 satisfies). Two new findings, both on the `--record` honesty contract.

### Round-3 fix verification — all 4 CONFIRMED-FIXED
D-09 now a real wiring test (drives the fixture through reconcile→validate→decide→_compute_line_items, not bare calculate) · phantom-employee precision-miss vs same-name field-miss correctly separated · uv.lock in files_modified · 04-03 verifies use `env -u DATABASE_URL`. **Regression check: none** (PATH-A still expected-extraction, reconciliation still requires matched_employee_id, false-process denominator still expected-clarify, chart still highlights table[1,2], --check still full-metric).

### New findings (Round 4)
- **MEDIUM — `--record` advertised as live but planned as a stub (cross-plan contradiction).** D-05 (HARD exit bar) and the 04-03 `workflow_dispatch` "Live re-record" job (runs `run_eval.py --record`) both promise live extraction; 04-01 says caches are overwritten by genuine extractor output after `--record`; but 04-02 said the live loop was intentionally NOT implemented. Consequence: a "Live re-record" run would produce no real caches — a materially misleading workflow path.
- **LOW — optional `--db` skip path crashes when DATABASE_URL is absent.** 04-04 said the DB stub "skips silently otherwise," but the action imported `get_settings()` before checking `database_url`; `Settings.database_url` is required with no default (config.py:27), so an unset env var raises before the skip branch. Affects optional 04-04 only.

**Overall risk (Round 4): MEDIUM for the full set (the `--record` contradiction); LOW for the exit bar if 04-04 is deferred.**

## Round-4 Resolution (all applied — see commit)

| Finding | Sev | Resolution |
|---------|-----|------------|
| `--record` stub vs advertised-live | MED | Reclassified per CONTEXT: D-05 (the record step) is HARD exit bar; only D-07 path-(b) end-to-end SCORING is "if time" — I had conflated them in R1. 04-02 now specs a REAL `_record_extraction()`: gated by `_require_live_llm()`, imports `extract` + `llm_client` inside the function, calls the production `extract(email, roster, run_id=…, llm=llm_client)` once per fixture and overwrites each `*_extraction.json` with `model_dump_json`. The synthetic day-one divergences are documented as a bootstrap that `--record` replaces (the divergence validator runs against committed day-one caches, so no regression). must_haves/artifact/import-note updated; "stub" language removed. The workflow_dispatch "Live re-record" job is now truthful. |
| `--db` skip crashes on absent DATABASE_URL | LOW | 04-04 now reads `os.environ.get("DATABASE_URL")` BEFORE any app.config import; unset/placeholder → "DB write skipped" + exit 0 with no `get_settings()` call (avoids the required-field fail-fast). Added a verify case `env -u DATABASE_URL … --db` asserting clean exit 0, plus an acceptance criterion and a guard grep for `os.environ.get("DATABASE_URL")`. |

**Convergence:** R1:13 → R2:8 → R3:4 → R4:2 (1 MED + 1 LOW, both on the `--record`/DB honesty seam, none on the core scoring credibility). The exit bar (04-01..03) is execution-ready.
