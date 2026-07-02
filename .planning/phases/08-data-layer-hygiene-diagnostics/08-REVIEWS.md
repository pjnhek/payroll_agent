---
phase: 8
reviewers: [codex]
reviewed_at: 2026-07-02
rounds: 2  # round 2 = post-replan re-review (replan commit 69919a7)
plans_reviewed: [08-01-PLAN.md, 08-02-PLAN.md, 08-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 8

## Codex Review

I traced the plan claims against the live repo. I did not modify files or run the suite.

## 08-01

**Summary**  
Strong schema/enum baseline plan. It correctly avoids a duplicate `businesses.contact_email` index because the live schema already has `TEXT NOT NULL UNIQUE`, and it updates both fresh-schema and existing-table status constraints. Main gap: the automated drift guard may not prove the new existing-table `DO $$` status CHECK swap.

**Strengths**
- Correctly treats `contact_email` as constraint-index-covered, matching [schema.sql](</Users/pnhek/usf msds/github/payroll_agent/app/db/schema.sql:18>) and the equality lookup in [repo.py](</Users/pnhek/usf msds/github/payroll_agent/app/db/repo.py:175>).
- Reuses the existing idempotent schema style and the proven `DO $$` constraint-swap pattern.
- Keeps the `NEEDS_CLARIFICATION` removal scoped to enum/schema/tests.

**Concerns**
- **MEDIUM:** `tests/test_status_drift.py` currently extracts the first `CHECK (status IN (...))` it finds, so it will validate the inline fresh-table CHECK but not necessarily the new live-table `DO $$` re-add block. A stale `DO $$` value list could slip through unless separately asserted.
- **LOW:** The schema comment still says the status CHECK has “11 values” near [schema.sql](</Users/pnhek/usf msds/github/payroll_agent/app/db/schema.sql:64>); the plan does not explicitly update that stale prose.
- **LOW:** The acceptance text around `grep -c "needs_clarification"` is slightly contradictory. The intended assertion should be simple: zero occurrences in `app/db/schema.sql`.

**Suggestions**
- Add a static test asserting `"needs_clarification"` is absent from the whole schema file and that the `payroll_runs_status_check` `DO $$` block contains the same 10 values as `RunStatus`.
- Update the schema status comment from 11 to 10 values.
- Keep the no-duplicate-index decision for `contact_email`; that part is correct.

**Risk Assessment**  
**LOW-MEDIUM.** The DDL shape is sound, but the live-table CHECK-swap proof needs a tighter automated guard.

## 08-02

**Summary**  
Good data-access plan: centralizing scrub/truncate behavior inside `record_run_error` is the right architecture, and replacing `load_all_runs`’s `SELECT pr.*` directly closes the stated hygiene gap at [repo.py](</Users/pnhek/usf msds/github/payroll_agent/app/db/repo.py:1088>). A few edge cases need tightening before implementation.

**Strengths**
- Central scrubber inside `record_run_error` avoids caller bypass.
- Fail-open behavior is appropriate for an error-path diagnostic feature.
- The tests cover the important scrub-before-truncate boundary case.
- The explicit projection aligns with existing `RUN_COLS` discipline at [repo.py](</Users/pnhek/usf msds/github/payroll_agent/app/db/repo.py:90>).

**Concerns**
- **MEDIUM:** `COALESCE(jsonb_array_length(pr.extracted_data->'employees'), 0)` is SQL-NULL safe, but not robust if the JSON value is `null` or a non-array scalar. That can still error. Corrupt/legacy JSON should not take down the runs list.
- **MEDIUM:** The proposed signature makes `conn` keyword-only. Current in-repo calls use `conn=`, but this is a public repo helper pattern; preserving positional `conn` is safer.
- **MEDIUM:** The scrubber’s exact `str.replace` is case-sensitive and normalization-sensitive. A roster name in different case or Unicode form can leak, which matters because MONEY-02 already established Unicode normalization as a project concern.
- **LOW:** The helper design redacts roster names/aliases and emails, but not any non-email business contact string if one ever appears outside the roster object.

**Suggestions**
- Use a safer employee count expression, e.g. `CASE WHEN jsonb_typeof(pr.extracted_data->'employees') = 'array' THEN jsonb_array_length(...) ELSE 0 END`.
- Prefer `def record_run_error(run_id, reason, conn=None, *, detail_exc=None, stage=None, roster=None)`.
- Normalize names before matching, and consider length-descending replacement or boundary-aware matching to avoid short-alias over-redaction.

**Risk Assessment**  
**MEDIUM.** The plan achieves the core goals, but the JSONB scalar edge case and PII matching semantics should be fixed before execution.

## 08-03

**Summary**  
This is the most important plan and it catches the key `RUN_COLS` data-flow gap: without adding `error_detail` to [RUN_COLS](</Users/pnhek/usf msds/github/payroll_agent/app/db/repo.py:90>), the dashboard route at [main.py](</Users/pnhek/usf msds/github/payroll_agent/app/main.py:904>) could never render the new column. The major blocker is that the main first-run pipeline still cannot roster-scrub errors, because `run_pipeline()` catches outside `_run()` and `_run()`’s `roster` local is not visible.

**Strengths**
- Correctly identifies the DB column → `RUN_COLS` → `load_run` → template path.
- Updates all currently visible production `record_run_error` call sites: [orchestrator.py](</Users/pnhek/usf msds/github/payroll_agent/app/pipeline/orchestrator.py:173>) and [main.py](</Users/pnhek/usf msds/github/payroll_agent/app/main.py:475>).
- Keeps Jinja autoescaping intact for `error_detail`.
- Includes a live Supabase checkpoint with the right pre-migration status count guard.
- Adds the pool singleton lock, which is a reasonable low-risk folded hygiene fix.

**Concerns**
- **HIGH:** `run_pipeline()` will pass no roster, so first-run failures after `_run()` loads the roster at [orchestrator.py](</Users/pnhek/usf msds/github/payroll_agent/app/pipeline/orchestrator.py:191>) are only email-regex scrubbed. If `str(exc)` contains employee names/aliases, OPS2-01’s PII-safe guarantee fails on the main pipeline path.
- **MEDIUM:** Code that writes `error_detail` can run before the live DB checkpoint adds the column. Against a real DB with old schema, `record_run_error` will fail instead of recording the original error.
- **LOW:** `InMemoryRepo.load_all_runs()` in [conftest.py](</Users/pnhek/usf msds/github/payroll_agent/tests/conftest.py:359>) will not mirror the new `summary_gate_reason` / `employee_count` aliases, so route-level fake tests may stop exercising the real list summary contract.
- **LOW:** The live dashboard verification asks for “a real failure” but does not define a deterministic safe way to create one.

**Suggestions**
- Revise the first-run pipeline wiring so the catch block has `roster` when available. The simplest safe shape is to move the try/except boundary into a function scope where `roster = None` is initialized before load and reassigned after `load_roster_for_business`.
- Make schema apply a deployment gate before code that writes `error_detail` runs against any real DB.
- Update `InMemoryRepo.load_all_runs()` to compute the same two aliases.
- Add a deterministic live verification option, such as temporarily setting a test ERROR row’s `error_detail` via SQL and confirming the dashboard render.

**Risk Assessment**  
**MEDIUM-HIGH until the roster-scrub gap is fixed; MEDIUM after.** The plan is otherwise well-structured, but the current first-run data flow does not satisfy the PII-safe diagnostics requirement.

---

## Consensus Summary

Single external reviewer (Codex) this round; consensus is drawn against the internal gsd-plan-checker rounds (iteration 1 blocker + re-verification).

### Agreed Strengths
- The RUN_COLS → load_run → run_detail.html key link (the internal checker's iteration-1 blocker, fixed in revision) is independently confirmed correct by Codex: "Correctly identifies the DB column → RUN_COLS → load_run → template path."
- No duplicate index on `businesses.contact_email` (D-8-09) — both reviewers verified the UNIQUE constraint + equality lookup against live source.
- Centralized scrub-inside-record_run_error architecture (no caller bypass) and fail-open error-path behavior endorsed by both.

### Agreed Concerns
_(raised by Codex; internal checker did not catch these — all verified against live source by the orchestrator)_

1. **HIGH — roster-scope gap on the main pipeline path (08-03):** `run_pipeline()`'s except block (orchestrator.py:181) wraps the `_run()` call, but `roster` is a local *inside* `_run()` (orchestrator.py:200). As planned, the first-run catch-all can only pass `roster=None`, so first-run failures are email-regex-scrubbed only — roster names/aliases in `str(exc)` would leak, failing OPS2-01's "excludes PII" criterion on the most common failure path. VERIFIED against live source. Fix direction: move the try/except boundary (or roster binding) into a scope where `roster = None` is initialized before `load_roster_for_business` and reassigned after, so the except block sees whatever was loaded.
2. **MEDIUM — JSONB scalar edge case (08-02):** `COALESCE(jsonb_array_length(...), 0)` is NULL-safe but errors if `extracted_data->'employees'` is a JSON scalar/`null` literal (non-array). Use `CASE WHEN jsonb_typeof(...) = 'array' THEN jsonb_array_length(...) ELSE 0 END`.
3. **MEDIUM — deploy-order gap (08-03):** code writing `error_detail` can reach a live DB before the checkpoint applies the column — `record_run_error` would then fail instead of recording the original error (the exact failure mode D-8-01b exists to prevent). Sequence the live schema apply before (or make the write tolerant of) the missing column.
4. **MEDIUM — scrubber case/normalization sensitivity (08-02):** exact `str.replace` misses case/Unicode-form variants of roster names (project already treats Unicode normalization as a concern per MONEY-02). Normalize before matching; replace length-descending.
5. **MEDIUM — drift-guard coverage (08-01):** `test_status_drift.py` parses the first inline `CHECK (status IN (...))`, which may not cover the new `DO $$` re-add block — a stale value list in the swap block could slip through. Assert the `DO $$` block's value list matches RunStatus and `needs_clarification` is absent from the whole schema file.
6. **LOW:** stale "11 values" schema comment; `InMemoryRepo.load_all_runs()` should mirror the new aliases; keyword-only `conn` deviates from existing signature convention; live checkpoint lacks a deterministic way to produce an ERROR run.

### Divergent Views
- None substantive. The internal checker passed the plans; Codex agrees on structure but adds data-flow findings the internal rounds missed — consistent with this project's Phase 7.5 pattern (external arg-flow tracing catches what prose-level checks don't).

---

# Round 2 — Codex Re-Review (post-replan, commit 69919a7)

I traced the revised plans against the live repo. I did not modify files.

**Round 1 Findings Disposition**

| Finding | Disposition | Evidence |
|---|---:|---|
| 08-01 drift guard only parsed first status CHECK | FIXED | Live guard uses first-match `re.search` in [tests/test_status_drift.py](/Users/pnhek/usf msds/github/payroll_agent/tests/test_status_drift.py:54). Revised plan adds a separate DO-block parser for `payroll_runs_status_check` in [08-01-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-01-PLAN.md:131). |
| 08-01 stale “11 values” schema comment | FIXED | Comment is currently stale in [schema.sql](/Users/pnhek/usf msds/github/payroll_agent/app/db/schema.sql:59); plan explicitly updates it in [08-01-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-01-PLAN.md:125). |
| 08-01 ambiguous `needs_clarification` grep acceptance | FIXED | Live value exists in [schema.sql](/Users/pnhek/usf msds/github/payroll_agent/app/db/schema.sql:69); plan requires zero occurrences file-wide in [08-01-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-01-PLAN.md:142). |
| 08-02 JSONB scalar edge in `employee_count` | FIXED | Live `load_all_runs` still uses `SELECT pr.*` in [repo.py](/Users/pnhek/usf msds/github/payroll_agent/app/db/repo.py:1095). Plan replaces with `CASE WHEN jsonb_typeof(...) = 'array' ... ELSE 0` in [08-02-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-02-PLAN.md:131). |
| 08-02 `conn` positional compatibility | FIXED | Live signature is positional-compatible in [repo.py](/Users/pnhek/usf msds/github/payroll_agent/app/db/repo.py:370); revised signature preserves `conn` before `*` in [08-02-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-02-PLAN.md:100). |
| 08-02 case/Unicode-insensitive roster scrub | PARTIALLY FIXED | Plan adds NFKC/casefold/longest-first matching in [08-02-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-02-PLAN.md:96), but the proposed “normalized search, original slicing using normalized offsets” is not offset-safe for Unicode normalization/casefold expansions. See new concern below. |
| 08-02 non-email business contact string redaction | NOT FIXED | Live `Roster` contains only employee `full_name` and `known_aliases` in [roster.py](/Users/pnhek/usf msds/github/payroll_agent/app/models/roster.py:36). Plan scrubs emails plus roster names only in [08-02-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-02-PLAN.md:97). This is probably acceptable today because `businesses.contact_email` is an email, but the Round 1 low note remains. |
| 08-03 main pipeline roster-scope gap | FIXED | Live `run_pipeline` catches outside `_run` in [orchestrator.py](/Users/pnhek/usf msds/github/payroll_agent/app/pipeline/orchestrator.py:173), while `roster` is local to `_run` at [orchestrator.py](/Users/pnhek/usf msds/github/payroll_agent/app/pipeline/orchestrator.py:199). Plan moves the catch into `_run` and passes `roster=roster` in [08-03-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-03-PLAN.md:120). |
| 08-03 deploy-order gap | FIXED | Plan makes schema-before-code an explicit live checkpoint/gate in [08-03-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-03-PLAN.md:168). |
| 08-03 `InMemoryRepo.load_all_runs` alias gap | FIXED | Live fake currently returns only `{**run, business_name}` in [conftest.py](/Users/pnhek/usf msds/github/payroll_agent/tests/conftest.py:359). Plan adds `summary_gate_reason` and `employee_count` in [08-03-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-03-PLAN.md:139). |
| 08-03 deterministic live ERROR dashboard verification | FIXED | Plan now includes a set-and-revert SQL verification path in [08-03-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-03-PLAN.md:195). |

**New Concerns**

- **MEDIUM — Unicode scrub algorithm can use wrong spans.**  
  In [08-02-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-02-PLAN.md:97), the plan says to search a normalized message but slice the original string using the normalized match offsets. NFKC/casefold can change string length, so those offsets are not reliable. This can leave partial PII, for example a combining accent after `[REDACTED]`, or redact the wrong adjacent characters. Use an offset-preserving matcher, or normalize by grapheme/character mapping while retaining original spans. Make the Unicode test non-skippable with a constructed accented employee and assert no raw fragments or combining marks remain.

- **MEDIUM — the HIGH roster-scope fix still lacks a behavioral test.**  
  The plan has source grep assertions for `roster=roster` in [08-03-PLAN.md](/Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-03-PLAN.md:149), but existing orchestrator tests only assert `status == "error"` and `error_reason` in [test_orchestrator_states.py](/Users/pnhek/usf msds/github/payroll_agent/tests/test_orchestrator_states.py:104). Add a spy test that forces a failure after `load_roster_for_business` and asserts `record_run_error(..., stage="pipeline", roster=<non-None roster>)`.

- **LOW — short aliases can over-redact inside ordinary words.**  
  The plan’s longest-first approach helps overlapping names, but it is still unbounded substring replacement. Seed aliases include short values like `Tom` and `Maria` in [seed.py](/Users/pnhek/usf msds/github/payroll_agent/app/db/seed.py:83). Consider boundary-aware matching for roster terms to preserve diagnostic value.

**Risk Assessment**

Overall risk: **MEDIUM**. The Round 1 structural issues are mostly fixed, including the important orchestrator scope problem and deployment sequencing. I would not execute unchanged because the Unicode scrub implementation can still violate the PII-safe guarantee, and the main-pipeline roster fix should have a real argument-flow regression test, not just grep checks. After those two adjustments, the plans look ready to execute.

---

## Round 2 Consensus Summary

- **Disposition:** 9/11 Round-1 findings FIXED (traced against live source); 1 PARTIALLY FIXED (Unicode scrub — see R2-1); 1 NOT FIXED but accepted (LOW: non-email business contact strings — Roster carries only employee names/aliases today, contact is an email and email-regex covers it).
- **Internal checker agreement:** the gsd-plan-checker's post-replan verification also passed the roster-scope fix, resume_pipeline right-sizing, and all MEDIUM/LOW fixes — Codex R2 concurs, then goes one level deeper on the scrubber algorithm.

### Open items from Round 2 (to fold into plans before execution)
1. **R2-1 MEDIUM (08-02) — Unicode scrub offset bug:** "search normalized, slice original with normalized offsets" is not offset-safe — NFKC/casefold can change string length, so spans drift → partial PII fragments (e.g. a stray combining mark) or wrong-character redaction. Fix: offset-preserving matching (e.g. per-candidate regex built from the original-name pattern with IGNORECASE, or normalize with an index map back to original spans). Make the accented-employee test constructed and non-skippable; assert no raw fragments/combining marks survive.
2. **R2-2 MEDIUM (08-03) — roster arg-flow needs a behavioral test:** the HIGH fix is only guarded by source-grep assertions. Add a spy test forcing a failure AFTER load_roster_for_business and asserting record_run_error was called with a non-None roster (argument-flow regression test, per this project's Phase 7.5 lesson).
3. **R2-3 LOW (08-02) — short-alias over-redaction:** seed aliases include `Tom`/`Maria`; unbounded substring replacement can redact inside ordinary words. Prefer boundary-aware matching (e.g. `\b`-anchored regex per name) to preserve diagnostic value.

**Codex verdict:** MEDIUM risk — "After those two adjustments, the plans look ready to execute."

---

# Round 3 — Codex Re-Review (post round-3 replan, commit ee20c25)

**Disposition Table**

| Item | Verdict | Evidence |
|---|---|---|
| R2-1 Unicode scrub offset bug | PARTIALLY FIXED | The plan drops normalize-then-slice and specifies per-candidate regexes applied to the original message: [08-02-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-02-PLAN.md:47>), [08-02-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-02-PLAN.md:97>). The constructed accented test is now non-skippable and local-roster based: [08-02-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-02-PLAN.md:89>). However, the planned `\b...\b` boundary can still leave a stray combining mark for decomposed names ending in an accented character; see New Concerns. |
| R2-2 Behavioral roster arg-flow test | FIXED | Plan adds a spy test that wraps `record_run_error`, forces a failure after roster load, and asserts `stage=="pipeline"` plus non-None populated `Roster`: [08-03-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-03-PLAN.md:152>). Live source supports the test path: `run_pipeline` currently catches outside `_run`, while `_run` loads roster before `_run_stages`: [orchestrator.py](</Users/pnhek/usf msds/github/payroll_agent/app/pipeline/orchestrator.py:173>), [orchestrator.py](</Users/pnhek/usf msds/github/payroll_agent/app/pipeline/orchestrator.py:199>). The monkeypatch target is correct because `orchestrator.py` imports the `app.db.repo` module object: [orchestrator.py](</Users/pnhek/usf msds/github/payroll_agent/app/pipeline/orchestrator.py:43>), and `fake_repo` patches that module: [conftest.py](</Users/pnhek/usf msds/github/payroll_agent/tests/conftest.py:606>). |
| R2-3 Short-alias boundary matching | FIXED | Plan wraps each candidate in `\b...\b` and compiles with `re.IGNORECASE`: [08-02-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-02-PLAN.md:100>). It adds a Tom/Tomorrow test: [08-02-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-02-PLAN.md:91>). Live seed confirms real short aliases exist: `Maria` and `Tom`: [seed.py](</Users/pnhek/usf msds/github/payroll_agent/app/db/seed.py:82>), [seed.py](</Users/pnhek/usf msds/github/payroll_agent/app/db/seed.py:195>). |
| Internal-checker blocker: two-way accent map / fixture-lucky test | FIXED | Plan now requires three alternatives per accented char: precomposed, base+combining mark, and bare base: [08-02-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-02-PLAN.md:99>). The test includes a no-covering-alias `Ana Núñez` employee and asserts bare surname fragments `GARCIA` / `NUNEZ` do not survive: [08-02-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-02-PLAN.md:89>). |

**New Concerns**

- MEDIUM: `\b` is not mark-aware for decomposed text. With the planned pattern shape, a candidate ending in an accented character can partially match the bare-base alternative and leave the combining mark behind. Example: a pattern like `\bJos(?:é|e\u0301|e)\b` against NFD `"José"` can substitute only `"Jose"` and leave `"[REDACTED]\u0301"`. This is caused by the planned three-way alternation plus `\b` anchors at [08-02-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-02-PLAN.md:99>) and [08-02-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-02-PLAN.md:100>). Fix: use mark-aware lookarounds such as `(?<![\w\u0300-\u036f])` and `(?![\w\u0300-\u036f])`, and add a test with a full name or alias ending in an accent, e.g. NFD `"José"`, asserting no combining mark is adjacent to `[REDACTED]`.

- LOW: The regex-metachar handling is sound: non-mapped characters are emitted with `re.escape` per [08-02-PLAN.md](</Users/pnhek/usf msds/github/payroll_agent/.planning/phases/08-data-layer-hygiene-diagnostics/08-02-PLAN.md:100>). I do not see a new metachar injection issue.

- LOW: The three-way accent map does not appear to create broad ordinary-word over-redaction beyond the existing intentional behavior that standalone aliases are PII. `Tom` inside `Tomorrow` is covered by the planned boundary test.

Previously fixed Round 1/2 items were not regressed in the plan text: the 08-01 DO-block status guard and zero `needs_clarification` checks remain, `jsonb_typeof` replaces the unsafe JSONB count, `conn` stays positional-compatible, deploy-order is explicit, `RUN_COLS` gets `error_detail`, `InMemoryRepo.load_all_runs` gets the aliases, the pool singleton gets a lock, and live dashboard verification is deterministic.

**Risk Assessment**

Risk: MEDIUM.

I would not execute unchanged. The remaining scrub boundary issue is small in code size but directly touches the PII-safe guarantee. After replacing `\b` with mark-aware boundaries and adding the ending-accent decomposed-name test, I would execute the plans unchanged.

---

## Round 3 Consensus Summary

- **Disposition:** R2-2 (roster arg-flow spy test) FIXED; R2-3 (boundary-aware matching) FIXED; internal-checker unaccented-leak blocker FIXED; R2-1 (Unicode scrub) PARTIALLY FIXED — offset-safety solved, but one boundary refinement remains.
- **No regressions:** all Round-1/2 fixes confirmed intact in plan text (DO-block guard, jsonb_typeof, conn signature, deploy-order gate, RUN_COLS/error_detail, InMemoryRepo aliases, pool lock, deterministic live verification).
- **Reviewer trajectory:** Round 1 → 11 findings; Round 2 → 3 open; Round 3 → 1 open (narrow, mechanical). The loop is converging.

### Open items from Round 3 (to fold into 08-02-PLAN.md before execution)
1. **R3-1 MEDIUM (08-02) — `\b` is not mark-aware for decomposed text:** a candidate ending in an accented character (NFD "José") can match the bare-base alternative ("Jose") with `\b` succeeding before the combining mark — leaving `[REDACTED]` + a stray U+0301, violating the no-combining-marks guarantee. Fix: replace the `\b...\b` anchors with mark-aware lookarounds `(?<![\w\u0300-\u036f])` ... `(?![\w\u0300-\u036f])` in `_compile_name_pattern`, and add a Test 5 variant with an NFD name ending in an accented character asserting no combining mark survives adjacent to `[REDACTED]`.
