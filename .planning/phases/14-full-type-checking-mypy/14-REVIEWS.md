---
phase: 14
reviewers: [codex]
reviewed_at: 2026-07-10T17:23:52Z
plans_reviewed: [14-01-PLAN.md, 14-02-PLAN.md, 14-03-PLAN.md, 14-04-PLAN.md, 14-05-PLAN.md, 14-06-PLAN.md, 14-07-PLAN.md, 14-08-PLAN.md, 14-09-PLAN.md]
---

# Cross-AI Plan Review — Phase 14

## Codex Review

# Cross-AI Plan Review — Phase 14

## Summary

The plans are unusually thorough and well grounded in the source, but they are not yet execution-safe as a wave plan. The central blocker is dependency ordering: mypy follows imports, while Plans 02–05 are scheduled in parallel and require zero-error checks that traverse files owned by sibling plans. A second blocker appears in Wave 3: Plan 08 claims to verify the combined output of Plans 06–08 without depending on Plans 06 or 07. There are also smaller command, evidence, and stale-baseline problems. Overall verdict: strong technical direction, but revise before execution.

## Cross-plan findings

### Strengths

- The phase is based on a real strict-mode census rather than speculative annotation estimates.
- The production/test strictness split is explicit and honest. Runtime code remains strict while test bodies are checked with relaxed definition requirements, matching `.planning/phases/14-full-type-checking-mypy/14-CONTEXT.md:20-34`.
- Dynamic-edge policy is sound: raw DB/JSON payloads may use `Any`, while pipeline-domain values should become concrete types.
- The plans preserve the Phase 13 module layout and monkeypatch seams.
- The proposed CI job accurately mirrors the existing pinned-action recipe in `.github/workflows/ci.yml:18-58`.
- Money-path verification is proportionate to risk, especially around calculation, deterministic decisioning, delivery, and withholding.

### Concerns

- **HIGH — The Wave 2 dependency graph is incompatible with mypy’s import traversal.** Plan 03 imports Plan 02-owned modules throughout `app/pipeline/orchestrator.py:52-61`; Plan 04 imports DB, pipeline, models, and gateway modules at `app/routes/runs.py:19-24`; Plan 05 imports DB/models/pipeline modules at `eval/run_eval.py:34-41`. All three depend only on Plan 01. The research itself observed transitive errors, so the per-plan “exit 0” commands cannot reliably succeed while sibling work is incomplete.
- **HIGH — Plan 08 cannot perform its claimed integration check.** It depends only on Plans 02–05 at `.planning/phases/14-full-type-checking-mypy/14-08-PLAN.md:5-6`, but claims to combine Plans 06, 07, and 08 at lines 93-98. Plans 06 and 07 may still be running.
- **MEDIUM — `uv run mypy .` is not the committed parity command.** Passing `.` is a CLI target; it does not mean “use only the `files=` scope.” The locked decision requires bare `uv run mypy`, as stated in `.planning/phases/14-full-type-checking-mypy/14-CONTEXT.md:26-29`.
- **MEDIUM — Test-count baselines are stale.** Plans 06 and 08 cite `614 passed / 20 skipped`, while the latest verified Phase 13 result is `615 passed / 50 skipped` at `.planning/phases/13-module-structure-boundaries/13-VERIFICATION.md:79-112`. Phase 12 also explicitly rejected permanent pinned-count gates because they become maintenance burdens.
- **MEDIUM — “No test blind spot” is somewhat overstated.** `check_untyped_defs` checks function bodies, but unannotated pytest fixture parameters remain `Any`; mypy does not infer fixture injection from `conftest.py`. This still meets the locked tiering decision, but the plans should not claim all fixture-shape errors will be detected.

### Recommended dependency revision

A workable order would be:

1. Plan 01: config and isolated bug fixes.
2. Plan 02: models/config/LLM first, then DB/repo.
3. Plan 03: pipeline, depending on Plan 02.
4. Plans 04 and 05: routes/email/main and eval/scripts, both depending on Plans 02 and 03.
5. Plans 06–08: test groups may run independently.
6. A separate integration task after all three test groups runs bare `uv run mypy`.
7. CI wiring and red-proof last.

Alternatively, intermediate checks can use an explicitly documented import-suppression strategy, but the final gate must remain bare `uv run mypy`.

---

## Plan 14-01

### Summary

The initial configuration and bug triage are well chosen, but gateway ownership is incomplete and the proposed verification command can legitimately remain red.

### Strengths

- The `llm_client` bug is real. `eval/run_eval.py:724` imports a nonexistent symbol, while the established module-object pattern appears at `app/pipeline/extract.py:26`.
- `_find_bracket` is incorrectly widened to `object` at `app/pipeline/federal_withholding.py:45`; `BracketRow` already exists at `app/pipeline/tax_tables_2026.py:24-38`.
- The plan correctly protects the gateway’s existing attribute-access behavior at `app/email/gateway.py:149-169`.
- Configuration is landed before bulk annotation work, giving later work one authoritative baseline.

### Concerns

- **HIGH — Gateway may remain unclean with no later owner.** Plan 01 explicitly allows other errors in `gateway.py` to remain, but Plan 04 excludes it as “already fixed.” The eventual Plan 08 catch-all would then need to modify a file outside its declared scope.
- **HIGH — Task 3’s automated verification is internally inconsistent.** It runs `uv run mypy app/email/gateway.py`, while acceptance permits unrelated errors in that same run. A nonzero command cannot serve as a successful automated gate.
- **MEDIUM — `cast(Any, ...)` contradicts the plan’s own narrow-edge policy.** The shape is stable and known, so the plan should require a small attribute `Protocol`, not offer `Any` as an equally acceptable outcome.
- **LOW — Task 3 is marked TDD even though the gateway behavior test is expected to pass before the typing-only change.** Existing coverage already exercises the attribute access at `tests/test_gateway.py:657-709`.

### Suggestions

- Require a narrow protocol with `headers`, `message_id`, and `text`.
- Either make `gateway.py` fully clean here or move all gateway annotation work to Plan 04.
- Replace the nonzero-prone verification with a targeted output assertion, or defer the full gateway check until its dependencies are clean.

### Risk Assessment

**HIGH** until gateway ownership and verification semantics are corrected.

---

## Plan 14-02

### Summary

The right subsystem is selected, but its internal task order and its relationship to downstream plans need revision.

### Strengths

- Direct measurement before changing facade exports is a good safeguard.
- The facade already has an explicit `__all__` surface at `app/db/repo/__init__.py:77-125`, supporting a minimal response if re-export errors actually appear.
- Dynamic DB-row typing is appropriately distinguished from typed domain objects.
- Full-suite verification is justified because the repo facade is widely imported.

### Concerns

- **HIGH — Task 2 precedes the models task it imports.** `app/db/repo/roster.py:9`, `runs.py:13-14`, and `pipeline_state.py:10-11` all import `app.models`. A strict `mypy app/db/repo/` can therefore report model errors before Task 3 has fixed them.
- **MEDIUM — The plan describes the DB/contracts layer as a prerequisite for sibling plans but leaves all siblings in the same wave.**
- **LOW — The context and research disagree about re-export behavior.** The direct-measurement approach handles this correctly, but the summary should record the actual result.

### Suggestions

- Reorder to: config/models → LLM → DB/repo.
- Make Plans 03–05 depend on the completed typed substrate where their imports require it.
- Preserve the existing facade unless mypy produces a concrete error.

### Risk Assessment

**HIGH** under the current ordering; **LOW–MEDIUM** after reordering.

---

## Plan 14-03

### Summary

The money-path precautions are excellent, but this plan cannot independently reach zero errors under the proposed dependency graph.

### Strengths

- The single sanctioned ignore maps to a genuine dynamic assignment at `app/pipeline/delivery.py:225-232`.
- The downstream read is safely defensive via `getattr` at `app/routes/runs.py:124-130`.
- The plan explicitly prohibits restructuring the delivery exception boundary.
- File-by-file testing around calculation and decision logic is proportionate to payroll risk.

### Concerns

- **HIGH — Pipeline checking traverses Plan 02-owned modules.** `orchestrator.py:52-61` imports DB, models, calculate, extract, and validation; extract further imports LLM code at `app/pipeline/extract.py:26-29`.
- **HIGH — `app/main.py` imports every route package at `app/main.py:7-16`, but those routes are owned by Plan 04.** Making Plan 03’s `mypy app/main.py` clean before Plan 04 is therefore unsafe.
- **MEDIUM — The key-link claim is wrong.** The plan says pipeline modules link into `app/main.py` via pipeline module-object imports, but `app/main.py` imports routers, not pipeline modules.
- **LOW — The plan describes startup/shutdown handlers in `app/main.py`, but the actual file is 16 lines and has none.**

### Suggestions

- Make Plan 03 depend on Plan 02.
- Move `app/main.py` to Plan 04, after route modules are clean.
- Correct the key-link description to the real route-registration mechanism.

### Risk Assessment

**HIGH** because the current zero-error acceptance is not schedulable.

---

## Plan 14-04

### Summary

The HTTP-surface grouping and security-sensitive regression tests are good, but the plan has transitive dependency and source-symbol inaccuracies.

### Strengths

- The operator-gate test selection is strong.
- The plan correctly leaves `getattr(exc, "payroll_roster", None)` unchanged unless mypy proves otherwise; the mechanism is visible at `app/routes/runs.py:129`.
- Route functions already have meaningful FastAPI types to build upon.

### Concerns

- **HIGH — Routes import DB and pipeline modules owned by Plans 02 and 03.** For example, `app/routes/runs.py:19-24` crosses both boundaries.
- **MEDIUM — The `read_first` symbol list is stale.** The plan cites `_run_pipeline`, `_route_reply`, and similar private names, but the actual public functions are `row_to_inbound`, `reply_sender_ok`, `route_reply`, `run_pipeline_bg`, and others at `app/routes/pipeline_glue.py:27-226`.
- **MEDIUM — The plan says it has no overlap and therefore runs safely in parallel, but file non-overlap does not imply mypy-analysis independence.**

### Suggestions

- Depend on Plans 02 and 03.
- Update all cited symbols to the actual Phase 13 public names.
- Move `app/main.py` into this plan so its imported routes are typed in the same dependency unit.

### Risk Assessment

**HIGH** until dependencies are corrected.

---

## Plan 14-05

### Summary

The eval/script scope is reasonable, but it is not independent of the runtime plans and one proposed “safe” script check actually opens the database.

### Strengths

- Dynamic fixture JSON is correctly classified as an acceptable `Any` boundary.
- `eval/run_eval.py` visibly imports the production judgment spine at lines 34-41, preserving eval/production parity.
- The eval regression check is an appropriate behavioral backstop.

### Concerns

- **HIGH — Eval checking traverses pipeline and DB code.** `eval/run_eval.py:34-41` imports modules owned by Plans 02 and 03.
- **MEDIUM — `show_confirmation_subject.py --help` is not side-effect-free.** The script has no argument parser; `main()` immediately opens a DB connection at `scripts/show_confirmation_subject.py:15-26`, and the module always calls `main()` at lines 47-48.
- **LOW — The action refers to annotating “argparse setup,” but these scripts mostly parse `sys.argv` manually; `reset_stuck_runs.py:30-39` is one example.**

### Suggestions

- Depend on Plans 02 and 03.
- Use `uv run python -m py_compile ...` or an import-only smoke test for `show_confirmation_subject.py`.
- Do not invoke operational DB scripts merely to prove annotations preserved executability.

### Risk Assessment

**HIGH** under the current wave; otherwise **MEDIUM**.

---

## Plan 14-06

### Summary

The first test partition is sensible, but its safety claims and baseline counts need calibration.

### Strengths

- The large concurrency/resume files are grouped with their relevant production seams.
- The plan avoids requiring annotations on every test definition.
- It correctly warns against relying on live LLM environment emptiness.

### Concerns

- **MEDIUM — The pinned `614/20` baseline is stale.** Latest verified evidence is `615/50`.
- **MEDIUM — Unchanged pass/skip counts do not prove assertions were not weakened.** An assertion can be changed while test counts remain identical.
- **LOW — `tests/__init__.py` is declared in scope but omitted from the actual mypy command at `.planning/.../14-06-PLAN.md:72-82`.

### Suggestions

- Capture the baseline dynamically at task start, or require only unchanged collection count plus zero test-assertion diff.
- Add `git diff --check`/review criteria for assertion lines rather than treating test counts as proof.
- Include `tests/__init__.py` in the command or remove it from the claimed measured set.

### Risk Assessment

**MEDIUM**.

---

## Plan 14-07

### Summary

Typing shared fixtures is worthwhile, but the plan overstates what those annotations provide to untyped pytest consumers.

### Strengths

- Full-suite testing after `conftest.py` changes is appropriate.
- Shared fixtures are centralized and substantial; `tests/conftest.py` is correctly treated as high blast radius.
- The gateway fake’s attribute shape matches production expectations at `tests/conftest.py:1141-1169`.

### Concerns

- **MEDIUM — mypy does not infer injected fixture parameter types from `conftest.py`.** Annotating a fixture return does not automatically type an unannotated `def test_x(fake_fixture):` parameter; it remains `Any`.
- **MEDIUM — The same stale count problem applies.**
- **LOW — The plan implies other test-group plans depend statically on `conftest.py`; pytest does, but ordinary mypy analysis of an individual test module does not import fixture definitions automatically.**

### Suggestions

- Rephrase the benefit: fixture implementations become checked, while consumers need explicit parameter annotations to receive concrete fixture types.
- Annotate high-value fixture parameters in money/concurrency/security tests where feasible.
- Remove the unsupported claim about cross-file fixture inference.

### Risk Assessment

**MEDIUM**.

---

## Plan 14-08

### Summary

This is the most serious Wave 3 issue: the plan is designated as the integration point without depending on the other test groups.

### Strengths

- Extra protection around withholding test data is excellent.
- The plan recognizes that a combined run can reveal errors not visible in directory-level censuses.
- It includes the right final hermetic suite check.

### Concerns

- **HIGH — Missing dependencies on Plans 06 and 07.** The plan’s own frontmatter contradicts its integration claim at `.planning/.../14-08-PLAN.md:5-6,93-98`.
- **HIGH — Residual errors outside this plan’s file list are authorized to be fixed here.** That defeats file ownership and can collide with concurrently running plans.
- **MEDIUM — `uv run mypy .` violates the locked bare-command parity rule and is incorrectly described as having “no directory arguments.”
- **MEDIUM — The `614/20` baseline conflicts with the verified `615/50` Phase 13 result.

### Suggestions

- Either make Plan 08 depend on Plans 06 and 07, or create a separate post-Wave-3 integration plan.
- Use bare `uv run mypy`.
- Do not allow this plan to modify arbitrary residual files; route residual errors back to their owning plan or a declared integration-fix task.

### Risk Assessment

**HIGH**.

---

## Plan 14-09

### Summary

The CI job design is correct, but the evidence lifecycle is incomplete after the human checkpoint.

### Strengths

- The new job accurately copies the pinned checkout/setup/sync pattern at `.github/workflows/ci.yml:18-58`.
- Bare `uv run mypy` provides the required local/CI parity.
- The single-cause red-proof design is strong.
- Existing workflow permissions remain least-privilege at `.github/workflows/ci.yml:3-5`.

### Concerns

- **MEDIUM — There is no post-checkpoint task to commit and push `14-VERIFICATION.md`.** The plan pushes master before the checkpoint at `.planning/.../14-09-PLAN.md:80-98`, then asks the human to create the evidence file at lines 101-117. The success criteria nevertheless say the evidence is committed.
- **MEDIUM — The branch cleanup instructions omit checking out master before `git branch -D` on the currently checked-out throwaway branch.
- **LOW — A failing Actions job is a blocking CI result, but not necessarily a merge block without branch protection.** The phase criterion only requires a type-error push to fail CI, so this is mostly terminology.
- **LOW — Task 2 allows unspecified “loose-end fixes” despite declaring only `ci.yml` in its file scope.

### Suggestions

- Add a final automated task after approval:
  1. checkout master;
  2. confirm the red-proof branch is gone;
  3. commit `14-VERIFICATION.md` and summary;
  4. push;
  5. confirm the final master run remains green.
- Remove the open-ended loose-end-fix authorization.
- Provide an exact isolated type-error snippet for repeatable red-proofing.

### Risk Assessment

**MEDIUM**.

## Overall Risk Assessment

**HIGH.** The implementation strategy is technically sound, but the current dependency graph makes multiple acceptance criteria impossible or race-prone. Fixing the Wave 2 import dependencies, moving the full-repo check behind all test plans, using bare `uv run mypy`, and completing the CI evidence commit lifecycle would reduce the phase to **LOW–MEDIUM** execution risk.

---

## Consensus Summary

Single-reviewer run (Codex only, per `--codex`); "consensus" below reflects the concerns Codex raised repeatedly across multiple plans rather than agreement between reviewers.

### Agreed Strengths

- Empirical strict-mode census as the planning basis (not speculative estimates) — cited in the cross-plan section and in Plans 01, 02, and 08.
- Production/test strictness split is explicit and matches the locked CONTEXT decisions.
- Money-path verification is proportionate to payroll risk (Plans 03, 08).
- CI job design faithfully mirrors the existing pinned-action recipe (Plan 09).

### Agreed Concerns

Recurring across plans — highest priority:

1. **HIGH — Wave 2 dependency graph vs. mypy import traversal** (raised in cross-plan, 02, 03, 04, 05): Plans 03–05 are scheduled parallel to Plan 02 but their files import Plan-02-owned modules (`app/pipeline/orchestrator.py:52-61`, `app/routes/runs.py:19-24`, `eval/run_eval.py:34-41`), so per-plan "exit 0" acceptance is not schedulable as written. Recommended order: 01 → 02 → 03 → {04, 05} → {06, 07, 08} → integration → 09.
2. **HIGH — Plan 08 integration check lacks dependencies on Plans 06/07** (cross-plan + Plan 08): frontmatter depends only on 02–05 while claiming to combine 06–08 output; it also authorizes fixes outside its declared file list, breaking file ownership.
3. **MEDIUM — `uv run mypy .` violates the locked bare-command parity rule** (cross-plan + Plan 08): the final gate must be bare `uv run mypy` per `14-CONTEXT.md:26-29`.
4. **MEDIUM — Stale pinned test baseline `614 passed / 20 skipped`** (Plans 06, 07, 08): latest verified Phase 13 result is `615 passed / 50 skipped`; capture baseline dynamically instead of pinning.
5. **HIGH — Plan 01 gateway ownership gap + internally inconsistent Task 3 gate**: Plan 01 tolerates residual `gateway.py` errors while Plan 04 excludes the file as "already fixed," leaving no owner; and its `uv run mypy app/email/gateway.py` gate can legitimately stay nonzero.

### Divergent Views

None — single reviewer. Notable single-mention findings worth a look during replanning: `show_confirmation_subject.py --help` opens a live DB connection (Plan 05); mypy does not infer fixture parameter types from `conftest.py` annotations (Plan 07); Plan 09 lacks a post-checkpoint task to commit `14-VERIFICATION.md`.
