---
phase: 13
reviewers: [codex]
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
