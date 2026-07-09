---
phase: 13
reviewers: [codex]
rounds: 2
reviewed_at: 2026-07-09T21:26:36Z
plans_reviewed: [13-01-PLAN.md, 13-02-PLAN.md, 13-03-PLAN.md, 13-04-PLAN.md]
---

# Cross-AI Plan Review — Phase 13

## Codex Review

# Plan Review — Phase 13

## Overall summary

Not ready to execute as written. The decomposition choices are good, but the plans contain several verified import-flow and test-seam failures that would break the full suite or alter runtime behavior. The largest blockers are the repo facade’s patch semantics, an incomplete orchestrator test census, and route modules missing required bindings/rewiring.

## 13-01 — repo package split

**Summary.** The facade approach is right, but the plan does not preserve the actual `app.db.repo` surface or its monkeypatch behavior.

**Strengths**

- Keeps `from app.db import repo` and `import app.db.repo` as stable caller paths.
- Correctly identifies `_scrub` as a test-exposed private helper.
- Separates DB concerns along reasonable aggregate boundaries.

**Concerns**

- **HIGH:** The proposed facade omits live attributes beyond `_scrub`. Current callers use `repo.get_connection` in [main.py](</Users/pnhek/usf msds/github/payroll_agent/app/main.py:406>), scripts use `repo._conn_ctx`, and tests import `_TERMINAL_STATUSES`, `_ACCENT_CLASS_MAP`, and `_pad_references`. The described facade would break these.
- **HIGH:** Moving `_conn_ctx` to `_shared.py` with a direct `get_connection` import breaks the established `monkeypatch.setattr(repo, "get_connection", ...)` seam. `_shared._conn_ctx` would retain its own binding.
- **HIGH:** Re-exporting functions is insufficient for monkeypatch compatibility. For example, `record_run_error()` calls `set_status()` in its defining module; patching `repo.set_status` on the facade will no longer intercept that call. The same applies to `update_email_message_sent()` → `update_email_message_state()`.
- **HIGH:** The plan’s claimed `create_run()` → `get_record_only_flag()` edge does not exist. [create_run](</Users/pnhek/usf msds/github/payroll_agent/app/db/repo.py:330>) writes the supplied `record_only` boolean directly and cannot call `get_record_only_flag` before it has a run ID. Adding that import/call violates the verbatim-move constraint.
- **MEDIUM:** The source-inspection census is incomplete. `test_claim_status.py` reads `repo.__file__` for “two writers”; `test_gateway.py` expects SQL text in `repo.__file__`; after the split the facade has neither. Only retargeting `test_threading.py` is insufficient.

**Suggestions**

- Define and test an explicit compatibility manifest before deleting `repo.py`: public functions plus `get_connection`, `_conn_ctx`, `_TERMINAL_STATUSES`, `_ACCENT_CLASS_MAP`, `_pad_references`, and `_scrub`.
- Make `_shared._conn_ctx` resolve the facade’s `get_connection` at call time, or deliberately migrate every patch site—prefer the former to satisfy STRUCT-04.
- Add contract tests proving facade patches intercept internal calls, especially `record_run_error` → `set_status`.
- Remove the invented `create_run` cross-aggregate edge and re-derive the real call graph from source.
- Retarget source-wide SQL assertions to the relevant aggregate modules without weakening their checks.

**Risk assessment:** **HIGH.** As written, webhook ingestion, scripts, and many tests lose required repo attributes or patch interception.

## 13-02 — orchestrator split and BOUND-01 promotions

**Summary.** The target module boundaries and module-object imports are sound, but the test-coupling inventory is materially incomplete and `clarification.py` lacks a required runtime import.

**Strengths**

- Keeps the money-sensitive core state machine in `orchestrator.py`.
- Uses module-object calls for new cross-module seams, which is the right patchable pattern.
- Correctly promotes `normalize_name`, `is_paid`, and `HOURS_FIELDS`.

**Concerns**

- **HIGH:** `clarification.py` needs `Extracted` for `Extracted.model_validate(...)` in deferred field-regression handling, but its prescribed imports include only `InboundEmail`. That path will raise `NameError`.
- **HIGH:** Plan 02 cannot achieve its own “full suite green” gate: it omits many tests that directly import or patch moved names. Verified examples include [test_atomic_persist.py](</Users/pnhek/usf msds/github/payroll_agent/tests/test_atomic_persist.py:241>), `test_demo_landing.py`, `test_multi_employee_delivery.py`, `test_alias_full_loop.py`, `test_needs_operator.py`, `test_concurrency_proof.py`, and `test_cr_regressions.py`.
- **HIGH:** Several omitted tests are structural tests, not simple imports. `test_atomic_persist.py` AST-parses `_defer_field_regression_clarification` and `_clarify` as functions in `orchestrator.py`; after the split it must inspect `clarification.py` and account for `clarification.clarify(...)`.
- **MEDIUM:** `MAX_CLARIFICATION_ROUNDS` moves to `clarification.py`, but [test_needs_operator.py](</Users/pnhek/usf msds/github/payroll_agent/tests/test_needs_operator.py:49>) imports it from `orchestrator.py`; it is not in Plan 02’s migration list.
- **MEDIUM:** `_RunStagesResult` remains in `orchestrator.py` while `clarification.py` annotates it. Future annotations avoid immediate failure, but leave a fragile unresolved type boundary for Phase 14.

**Suggestions**

- Expand Plan 02’s files and retarget matrix to every moved-symbol import, dotted patch path, and AST source test before declaring the plan independently green.
- Add `Extracted` explicitly to `clarification.py`; define a narrow protocol or type-only boundary for `_RunStagesResult`.
- Retarget tests to owner modules (`clarification`, `delivery`, `alias_learning`) rather than adding compatibility aliases to `orchestrator.py`.

**Risk assessment:** **HIGH.** Numerous pre-existing tests will fail before Plan 03 can run, so later plans cannot repair them.

## 13-03 — FastAPI route split

**Summary.** The URL-based router ownership is excellent, but the task’s import and helper rewiring instructions conflict with the live code and leave multiple handlers nonfunctional.

**Strengths**

- The `/runs*` grouping preserves a legible operator-gate flow.
- `pipeline_glue` is a good shared HTTP-to-pipeline seam.
- Router registration in thin `main.py` is straightforward and preserves app assembly.

**Concerns**

- **HIGH:** The webhook plan is factually wrong: [inbound](</Users/pnhek/usf msds/github/payroll_agent/app/main.py:519>) does not call `_route_reply`; it performs transactional reply classification, then calls `_finish_reply_resume`. Replacing that with `route_reply` would re-run header lookup outside the transaction and can regress the Phase 9 dedup/race guarantee.
- **HIGH:** The webhook move also needs module-object rewrites for `_reply_sender_ok`, `_row_to_inbound`, `_resume_pipeline`, `_finish_reply_resume`, and `_run_pipeline`; the plan only specifies `route_reply`/`run_pipeline`.
- **HIGH:** `demo_compose` and `demo_send_test` each schedule `_run_pipeline` ([lines 1322 and 1845](</Users/pnhek/usf msds/github/payroll_agent/app/main.py:1322>)); Plan 03 does not rewire either to `pipeline_glue.run_pipeline_bg`.
- **HIGH:** The stated import sets are not executable. Examples: `dashboard.py` needs `Query`, `Path`, `json`, `FileResponse`, and `HTTPException`; `runs.py` needs `re`, `gateway`, `clean_body`, and a logger; `demo.py` needs `BackgroundTasks`, `Path`, `json`, `datetime`/`UTC`, `clean_body`, `pipeline_glue`, and a logger. Every router using existing `logger` calls also needs a logger binding.
- **HIGH:** `runs.py` and dashboard are instructed to import `_DEMO_FIXTURES` from `demo.py`. That is a new cross-module private import and will fail Plan 04’s AST guard. Make shared route constants public or place them in a dedicated public constants module.
- **HIGH:** `landing()` depends on `_SEED_CONTACTS`, `_SEED_BUSINESS_IDS`, and `DEMO_OPERATOR_EMAIL`, but the dashboard import instructions omit all three.
- **MEDIUM:** The test migration misses [test_hitl.py](</Users/pnhek/usf msds/github/payroll_agent/tests/test_hitl.py:81>), which patches `app.main.repo`; thin `main.py` will no longer expose that binding. It also fails to retarget the delivery patch in `test_concurrency_proof.py` from `orchestrator._deliver` to `delivery.deliver`.

**Suggestions**

- Add a complete helper-call matrix per destination module, derived from `rg` before editing.
- Preserve webhook flow exactly: `inbound` must call `pipeline_glue.finish_reply_resume`, not `route_reply`.
- Introduce a public `routes.constants` module, or promote the shared demo constants, before enabling BOUND-01 enforcement.
- Add import-time smoke tests for every router, then a route-count and `/health/live` test before broad test migration.

**Risk assessment:** **HIGH.** The current instructions can cause import-time failures and, more seriously, alter the atomic reply-routing path.

## 13-04 — AST BOUND-01 guard

**Summary.** Choosing an AST guard over Ruff PLC2701 is correct, but the specified guard and verification rules need tightening.

**Strengths**

- `ast.walk()` correctly reaches function-body imports.
- Scanning `app/`, `eval/`, and `scripts/` matches the defined runtime scope.
- Excluding tests is appropriate for intentional internal-unit-test access.

**Concerns**

- **HIGH:** The guard only checks `ImportFrom`; it does not detect `import module; module._private` access. Existing scripts use `repo._conn_ctx`, and Plan 03 introduces private constant imports that the guard will catch only in one syntax form.
- **MEDIUM:** Relative imports and package `__init__.py` module naming are not resolved correctly. `node.level` is ignored, and `app/routes/__init__.py` is computed as `app.routes.__init__`, not `app.routes`.
- **MEDIUM:** The final grep acceptance criteria are impossible as written: `calculate.py` intentionally retains `_HOURS_FIELDS`, and comments outside `validate.py` mention `_is_paid`. Text grep cannot establish cross-module import compliance.
- **MEDIUM:** The proposed synthetic-positive check is good, but should be a `tmp_path` test of the scanner helper rather than manually creating/removing a repository file.

**Suggestions**

- Either scope BOUND-01 explicitly to `from ... import _name`, or extend the scanner to resolve imported module aliases and flag `module._private` attribute access.
- Resolve relative imports before comparing module names; normalize package `__init__.py` paths.
- Replace broad text greps with AST-based assertions targeting the original violation forms.
- Add a unit test that proves detection of both a nested `ImportFrom` violation and the chosen attribute-access policy.

**Risk assessment:** **HIGH.** It will either miss a class of private coupling or fail on the phase’s own planned imports and unrelated retained private symbols.

## Cross-plan blockers

- **HIGH:** Plans 13-01 and 13-02 are both Wave 1 and both modify `tests/test_alias_write.py`. They need serialization or a dedicated integration plan; otherwise parallel execution conflicts.
- **HIGH:** Each split plan promises a green full suite, but Plan 02 leaves broken imports that Plan 03 would only partially repair later. Move every affected test into the plan that moves its production owner.
- **MEDIUM:** Keep the dynamic collected-test baseline, rather than relying on the stale 613 figure; the live research baseline is 663.

Overall phase risk: **HIGH until the above blockers are incorporated.** The desired architecture is achievable without behavior changes, but the current plan needs a corrected import/patch-surface inventory before execution.

---

## Consensus Summary

Single external reviewer (Codex, codex-cli 0.144.0 with repo read access) — consensus not applicable; findings below are single-source but source-verified by the reviewer against the live tree.

### Agreed Strengths
- Decomposition boundaries themselves are sound: per-aggregate repo modules, alias/clarify/delivery carve-outs, URL-based router ownership, thin main.py assembly.
- Module-object imports as the patchable seam pattern is the right mechanism.
- AST guard over ruff PLC2701 is the correct BOUND-01 mechanism.

### Agreed Concerns (highest priority)
1. **Facade patch semantics (13-01, HIGH)** — re-exporting functions does not make `monkeypatch.setattr(repo, "fn", ...)` intercept intra-module calls (`record_run_error` → `set_status`, `_conn_ctx` → `get_connection`); the facade must expose the full live attribute surface (`get_connection`, `_conn_ctx`, `_TERMINAL_STATUSES`, `_ACCENT_CLASS_MAP`, `_pad_references`, `_scrub`) and patches must still intercept.
2. **Incomplete test-coupling census (13-02/13-03, HIGH)** — additional tests import/patch moved names (`test_atomic_persist.py` AST-parses `_defer_field_regression_clarification`/`_clarify`; `test_needs_operator.py` imports `MAX_CLARIFICATION_ROUNDS`; `test_hitl.py` patches `app.main.repo`; `test_concurrency_proof.py` patches `orchestrator._deliver`; plus test_demo_landing, test_multi_employee_delivery, test_alias_full_loop, test_cr_regressions).
3. **Webhook flow fidelity (13-03, HIGH)** — `inbound` calls `_finish_reply_resume` inside a transaction, NOT `_route_reply`; replacing it with `route_reply` re-runs header lookup outside the transaction and can regress the Phase 9 dedup/race guarantee. Router import sets are also non-executable as specified (missing Query/Path/json/logger/etc.), and `_DEMO_FIXTURES` cross-imports would fail the phase's own AST guard.
4. **Factual plan errors (13-01, HIGH)** — the claimed `create_run()` → `get_record_only_flag()` edge does not exist in source; inventing it violates verbatim-move.
5. **AST guard scope (13-04, HIGH/MEDIUM)** — ImportFrom-only misses `module._private` attribute access; relative imports and `__init__.py` module naming unresolved; final grep acceptance criteria impossible (calculate.py legitimately retains `_HOURS_FIELDS`).
6. **Wave-1 write conflict (cross-plan, HIGH)** — 13-01 and 13-02 both modify `tests/test_alias_write.py` in the same wave; needs serialization.
7. **Stale test-count baseline (MEDIUM)** — use the dynamic collected count (research baseline 663), not the 613 figure.

### Divergent Views
None (single reviewer).


---

# Round 2 — Confirming Review of Revised Plans (Codex)

> Reviewed the post-`42a2931` revised plans against the live tree. Round 1 sections above are historical.

## Verdict: NOT READY TO EXECUTE

The revised plans close several Round 1 issues, but four HIGH blockers remain: repo-facade patch semantics, invented repo call edges, Plan 02’s intentionally broken intermediate state, and incomplete test retargets/routes.

### 13-01 — repo package split

| Round 1 finding | Status | Source-verified evidence |
|---|---|---|
| Facade omitted live attributes | PARTIALLY FIXED | The plan now re-exports the identified names, including `_conn_ctx`, `_scrub`, and constants. |
| `_conn_ctx` stopped seeing a facade-patched `get_connection` | FIXED | The proposed call-time lookup through `app.db.repo.get_connection` preserves this seam. |
| Facade patches do not intercept submodule-internal calls | NOT FIXED | `record_run_error()` resolves bare `set_status` in its defining module ([repo.py](/Users/pnhek/usf%20msds/github/payroll_agent/app/db/repo.py:655)); patching facade `repo.set_status` does not alter `runs.set_status`. Existing [test_gateway.py](/Users/pnhek/usf%20msds/github/payroll_agent/tests/test_gateway.py:229) relies on exactly that interception. The same break applies to facade-patched `_scrub` in [test_persistence.py](/Users/pnhek/usf%20msds/github/payroll_agent/tests/test_persistence.py:342). |
| Invented `create_run → get_record_only_flag` edge | FIXED | `create_run` writes the supplied flag directly; the revised plan correctly removes that edge. |
| Incomplete repo source-inspection census | PARTIALLY FIXED | It now covers threading, claim-status, and gateway checks, but misses [test_clarify.py](/Users/pnhek/usf%20msds/github/payroll_agent/tests/test_clarify.py:465), whose `repo.__file__` scan would become a facade-only, vacuous check. |

New concerns:

- **HIGH:** The plan invents two different cross-aggregate edges: `set_pre_clarify_extracted → set_status` and `set_clarification_round → set_status`. Neither exists; both functions only write their own fields ([repo.py](/Users/pnhek/usf%20msds/github/payroll_agent/app/db/repo.py:865), [repo.py](/Users/pnhek/usf%20msds/github/payroll_agent/app/db/repo.py:973)). The prescribed `pipeline_state → runs.set_status` wiring conflicts with the verbatim-move rule.
- **HIGH:** Re-exporting is not a live proxy. Either retarget the affected tests to owner modules (`runs._scrub`, `runs.set_status`, `emails.update_email_message_state`) or deliberately add facade call-time dispatch—then test it. The current “same-module bare-name calls preserve facade patches” explanation is false.

### 13-02 — orchestrator split

| Round 1 finding | Status | Source-verified evidence |
|---|---|---|
| Missing `Extracted` import in clarification module | FIXED | The revised import specification explicitly includes `Extracted`. |
| Omitted moved-symbol test census | NOT FIXED | Several directly affected references remain absent from the task instructions. |
| `test_atomic_persist` AST tests need owner/module-aware updates | FIXED | The proposed `Name → Attribute` and owner-module rewrites cover the two Round 1 AST checks. |
| `MAX_CLARIFICATION_ROUNDS` test import | FIXED | The plan explicitly moves that test import to `clarification.py`. |
| `_RunStagesResult` runtime cycle/type boundary | FIXED | The `TYPE_CHECKING` plan is appropriate. |

New concerns:

- **HIGH:** Plan 02 deliberately leaves `main.py` importing `orchestrator._deliver` until Plan 03, while deleting that name in Plan 02. [approve()](/Users/pnhek/usf%20msds/github/payroll_agent/app/main.py:772) imports it before its error boundary. This violates STRUCT-04’s requirement that the full suite pass after every split, and contradicts Plan 02’s own acceptance criterion that `test_hitl.py` pass. Move this one `main.py` retarget into Plan 02, or do not remove the old symbol until the same commit.
- **HIGH:** The claimed “full” census remains incomplete even within files it names:
  - [test_atomic_persist.py](/Users/pnhek/usf%20msds/github/payroll_agent/tests/test_atomic_persist.py:753) has five `_deliver` imports plus `_write_aliases_if_safe` patches at lines 766 and 940, and a moved `_clarify` patch at line 530. The task only handles two AST tests.
  - [test_alias_write.py](/Users/pnhek/usf%20msds/github/payroll_agent/tests/test_alias_write.py:1441) directly imports `_normalize_candidate` three times and `_write_aliases_if_safe` at line 1471; neither is assigned a retarget.
  - [test_cr_regressions.py](/Users/pnhek/usf%20msds/github/payroll_agent/tests/test_cr_regressions.py:315) has a separate `_deliver` import and aliases helper patch omitted from the task.
  - [test_clarify_rounds.py](/Users/pnhek/usf%20msds/github/payroll_agent/tests/test_clarify_rounds.py:286) AST-parses the owner module and looks for `FunctionDef("_clarify")`; its task text only discusses attribute patches, not this renamed structural target.

### 13-03 — router split

| Round 1 finding | Status | Source-verified evidence |
|---|---|---|
| Webhook must call `finish_reply_resume`, not `route_reply` | FIXED | The revised plan preserves the transaction-classify, post-commit `finish_reply_resume` flow. |
| Missing pipeline-glue helper rewrites | FIXED | The relevant webhook and runs-list helpers are now enumerated. |
| Demo routes still schedule old `_run_pipeline` | FIXED | Both demo routes are directed to `pipeline_glue.run_pipeline_bg`. |
| Router import sets/logger bindings incomplete | PARTIALLY FIXED | Most required imports are now identified, but the planned `runs.py` imports unused `FileResponse`, which will fail Ruff. |
| Demo constants caused private cross-module imports | FIXED | The planned public `DEMO_FIXTURES`, `SEED_CONTACTS`, and `SEED_BUSINESS_IDS` names address this. |
| `test_hitl` patched `main.repo` | FIXED | The proposed retarget to `routes.runs.repo` is correct. |

New concerns:

- **HIGH:** The plan omits `_DEMO_FIXTURE_DEFAULT_KEY`, which is required when defining `demo_send_test` ([main.py](/Users/pnhek/usf%20msds/github/payroll_agent/app/main.py:149), [main.py](/Users/pnhek/usf%20msds/github/payroll_agent/app/main.py:1754)). After `main.py` is thinned, `demo.py` will raise `NameError` at import time unless it moves that same-module constant too.
- **HIGH:** Plan 03 still misses three `app.main._run_pipeline` patches in [test_demo_landing.py](/Users/pnhek/usf%20msds/github/payroll_agent/tests/test_demo_landing.py:811), lines 876, and 933. They use `raising=False`, so they will silently patch a dead attribute while the actual route calls `pipeline_glue.run_pipeline_bg`, potentially invoking real pipeline/LLM behavior.
- **LOW:** Remove `FileResponse` from the specified `runs.py` imports; only `dashboard.py` uses it.

### 13-04 — BOUND-01 AST guard

| Round 1 finding | Status | Source-verified evidence |
|---|---|---|
| ImportFrom-only guard missed `module._private` access | FIXED | The revised design adds imported-module attribute analysis and preserves the repo-facade compatibility exception. |
| Relative imports and `__init__.py` module naming | PARTIALLY FIXED | It normalizes `__init__.py`, but its stated relative-import algorithm is still incomplete. |
| Text-grep acceptance rules were unsound | FIXED | The scanner becomes the source of truth. |
| Synthetic positive check should use `tmp_path` | FIXED | The revised plan makes this a permanent test. |

New concerns:

- **MEDIUM:** The stated `ImportFrom` rule only says to flag names when `node.level == 0`; it never says to apply the same check after resolving a relative import. A future `from .sibling import _private` can therefore evade the guard.
- **MEDIUM:** Normalizing `app/routes/__init__.py` to `app.routes` loses the fact it is a package. For a relative import inside that `__init__.py`, level 1 should resolve from `app.routes`, not from `app`. Preserve an `is_package` flag while resolving.
- **MEDIUM:** The facade exception is described as exempting any imported package `__init__.py`, although only `app.db.repo` is an approved compatibility facade. Limit the exemption to declared facades, or prove all package facades have equivalent boundary contracts.

### Cross-plan closure

| Round 1 finding | Status |
|---|---|
| Wave-1 write conflict on `test_alias_write.py` | FIXED — plans are now serial. |
| Every split independently green | NOT FIXED — Plan 02 explicitly allows the broken `_deliver` state. |
| Stale 613-test baseline | FIXED in approach — plans now require a live collected baseline. |

I could not independently collect the current test count because `uv` cache access is denied by this read-only sandbox; that does not affect the source-level findings above.

Execution should wait for the HIGH items to be incorporated, especially preserving repo monkeypatch semantics and restoring Plan 02’s per-split green guarantee.


---

## Consensus Summary (updated after Round 2)

**Verdict: NOT READY TO EXECUTE.** Round 2 confirms most Round 1 fixes landed (webhook transaction flow, Extracted import, serial waves, dynamic baseline, AST guard attribute-access), but 4 HIGH blockers remain:

1. **13-01 facade patch semantics (NOT FIXED + worse)** — re-exporting is not a live proxy: patching facade `repo.set_status` cannot intercept `record_run_error()`'s bare-name `set_status` call inside its owner module (`tests/test_gateway.py:229` relies on exactly that), same for `_scrub` (`test_persistence.py:342`). Also two NEW invented cross-aggregate edges (`set_pre_clarify_extracted → set_status`, `set_clarification_round → set_status`) that don't exist in source. And `test_clarify.py:465`'s `repo.__file__` scan becomes vacuous. Fix: retarget affected tests to owner modules (runs.set_status, runs._scrub, emails.update_email_message_state) OR add tested call-time facade dispatch; delete the invented edges.
2. **13-02 broken intermediate state (NOT FIXED)** — Plan 02 deletes `orchestrator._deliver` but leaves `app/main.py:772 approve()` importing it until Plan 03, violating STRUCT-04's per-split green gate and Plan 02's own test_hitl acceptance criterion. Fix: move that one main.py retarget into Plan 02.
3. **13-02 census still incomplete within named files** — `test_atomic_persist.py` (5 `_deliver` imports, `_write_aliases_if_safe` patches @766/940, `_clarify` patch @530), `test_alias_write.py` (`_normalize_candidate` ×3 @1441+, `_write_aliases_if_safe` @1471), `test_cr_regressions.py` (@315 `_deliver` import + aliases patch), `test_clarify_rounds.py` (@286 AST FunctionDef("_clarify") structural target).
4. **13-03 import-time NameError + silent dead patches** — `_DEMO_FIXTURE_DEFAULT_KEY` (main.py:149, used @1754 in demo_send_test default) not in the move list → demo.py NameError at import; `test_demo_landing.py` patches `app.main._run_pipeline` with `raising=False` at 811/876/933 → would silently patch a dead attribute while the route calls `pipeline_glue.run_pipeline_bg`, risking REAL pipeline/LLM calls in tests. LOW: unused `FileResponse` in runs.py imports fails ruff.

MEDIUM (13-04): relative-import resolution must apply the same check after resolving `node.level>0`; preserve `is_package` when resolving relative imports inside `__init__.py`; limit the facade exemption to the declared `app.db.repo` facade only.

**Recommended next step:** `/gsd-plan-phase 13 --reviews` (round 2 replan), then a final confirming review before execution.
