---
phase: 14-full-type-checking-mypy
reviewed: 2026-07-10T22:17:41Z
depth: standard
files_reviewed: 77
files_reviewed_list:
  - .github/workflows/ci.yml
  - pyproject.toml
  - app/db/repo/_shared.py
  - app/db/repo/demo.py
  - app/db/repo/emails.py
  - app/db/repo/pipeline_state.py
  - app/db/repo/roster.py
  - app/db/repo/runs.py
  - app/db/schema_introspect.py
  - app/email/gateway.py
  - app/llm/client.py
  - app/llm/prompts/clarify.py
  - app/llm/prompts/extract.py
  - app/llm/prompts/suggest.py
  - app/models/contracts.py
  - app/pipeline/alias_learning.py
  - app/pipeline/calculate.py
  - app/pipeline/clarification.py
  - app/pipeline/compose_email.py
  - app/pipeline/decide.py
  - app/pipeline/delivery.py
  - app/pipeline/extract.py
  - app/pipeline/federal_withholding.py
  - app/pipeline/orchestrator.py
  - app/pipeline/pdf.py
  - app/pipeline/suggest.py
  - app/pipeline/validate.py
  - app/routes/dashboard.py
  - app/routes/demo.py
  - app/routes/pipeline_glue.py
  - app/routes/runs.py
  - app/routes/webhook.py
  - eval/draft_candidate_emails.py
  - eval/judge.py
  - eval/run_eval.py
  - scripts/demo_reset.py
  - scripts/reset_stuck_runs.py
  - tests/conftest.py
  - tests/test_alias_full_loop.py
  - tests/test_alias_write.py
  - tests/test_atomic_persist.py
  - tests/test_bootstrap_timeouts.py
  - tests/test_calculate.py
  - tests/test_claim_status.py
  - tests/test_clarify.py
  - tests/test_clarify_rounds.py
  - tests/test_combined_context.py
  - tests/test_compose_confirmation.py
  - tests/test_compose_email_field_regression.py
  - tests/test_concurrency_proof.py
  - tests/test_cr_regressions.py
  - tests/test_dashboard.py
  - tests/test_delivery.py
  - tests/test_demo_landing.py
  - tests/test_eval_wiring.py
  - tests/test_federal_withholding.py
  - tests/test_gateway.py
  - tests/test_hitl.py
  - tests/test_ingest.py
  - tests/test_llm_client.py
  - tests/test_models_contracts.py
  - tests/test_multi_employee_delivery.py
  - tests/test_multiround_context_edge.py
  - tests/test_needs_operator.py
  - tests/test_orchestrator_states.py
  - tests/test_pdf.py
  - tests/test_persistence.py
  - tests/test_reply_redelivery.py
  - tests/test_resume_pipeline.py
  - tests/test_retrigger_epoch.py
  - tests/test_schema_introspect.py
  - tests/test_seed_roundtrip.py
  - tests/test_stuck_run_recovery.py
  - tests/test_suggest.py
  - tests/test_threading.py
  - tests/test_webhook.py
  - tests/test_webhook_dedup_race.py
findings:
  critical: 0
  warning: 5
  info: 6
  total: 11
status: issues_found
---

# Phase 14: Code Review Report

**Reviewed:** 2026-07-10T22:17:41Z
**Depth:** standard
**Files Reviewed:** 77 (entire phase diff `6c48d7b~1..2c1cbd0`, planning artifacts excluded)
**Status:** issues_found

## Summary

Phase 14's diff was reviewed line-by-line against the locked "behavior-neutral, annotation-only" contract, with the money paths (`calculate.py`, `federal_withholding.py`, `orchestrator._compute_line_items`), every `cast()`, every `# type: ignore`, all mypy-narrowing `assert`s, and the full test diff traced for silent behavior or assertion changes.

**Verified claims (independently reproduced, not taken on faith):**
- Bare `uv run mypy` passes: `Success: no issues found in 114 source files` — and 114 equals the exact count of `.py` files under `app/ eval/ scripts/ tests/`, so no scope was silently dropped by `files`/`explicit_package_bases`.
- `uv run ruff check .` clean; hermetic suite (`env -u DATABASE_URL -u ALLOW_DB_RESET -u ALLOW_LIVE_LLM uv run pytest -q`) green: **616 passed, 50 skipped** (skips are the guarded DB/live-LLM tests — expected).
- The CI `typecheck` job matches its siblings: identical SHA-pinned `actions/checkout` and `astral-sh/setup-uv`, inherits top-level `permissions: contents: read`, uses `uv sync --locked`, runs bare `uv run mypy` (exact D-06 local/CI parity), and is blocking (no `continue-on-error`).
- The one **real bug mypy exposed** — `eval/run_eval.py` `--record` imported a nonexistent name (`from app.llm.client import llm_client`; no such symbol exists in that module, so `--record` mode would have crashed with ImportError) — was fixed per D-08 discipline: test commit `e8b93f2` (adds `test_record_extraction_llm_client_import_resolves`) lands **before** fix commit `8d21737`, in a dedicated pair. I verified the new test is hermetic: `FIXTURE_DIR` is monkeypatched to an empty tmp dir (no LLM call possible) and `_extraction_model_id()` is env-only (no `app.config`/DATABASE_URL touch).
- Money-path neutrality holds: `_to_decimal`'s `cast(Decimal | int | str, value)` is a runtime no-op guarded by the pre-existing bool/float rejections above it; `pdf.py`'s `ot_rate` condition rewrite (`if show_rate` → `if hourly_rate is not None`) is tautologically equivalent; `_find_bracket` narrowing to `BracketRow` changes nothing at runtime; no Decimal/float boundary moved.
- The five added narrowing `assert`s (webhook.py ×3, orchestrator.py ×2) sit on invariants already enforced by the surrounding `outcome`/branch coupling — unreachable today (see IN-01 for the `-O` caveat).
- No test assertion was weakened, no fixture value changed, no `raising=False` added on previously-strict patches, no stubbed seam went live. The `test_delivery.py`/`test_combined_context.py` monkeypatch-target rewrites resolve to the same module objects (orchestrator binds `from app.pipeline.extract import extract` at module level, so restoring `app.pipeline.extract.extract` is identity-equal to the old saved original).

What keeps this from a clean pass: the **ignore-policy erosion in tests** (WR-01/WR-02) and three casts that forfeit checking mypy could have provided (WR-03/WR-04), plus an avoidable 4-way duplication on the LLM call path (WR-05).

## Warnings

### WR-01: Module-wide `# mypy: disable-error-code` blankets silence bug-catching codes across 9 entire test files

**File:** `tests/test_clarify_rounds.py:42`, `tests/test_compose_confirmation.py:15`, `tests/test_cr_regressions.py:24`, `tests/test_eval_wiring.py:12`, `tests/test_hitl.py:17`, `tests/test_llm_client.py:15`, `tests/test_multiround_context_edge.py:53`, `tests/test_orchestrator_states.py:18`, `tests/test_schema_introspect.py:3`
**Issue:** The phase's D-09 policy is zero-tolerance, individually-justified narrow ignores. These files instead use file-scoped `# mypy: disable-error-code="..."` directives that disable codes for **every line in the module**, including future ones. `type-arg`/`no-untyped-call` are low-risk, but `union-attr` (test_cr_regressions), `attr-defined` (test_eval_wiring, test_hitl, test_orchestrator_states), `arg-type` (test_eval_wiring, test_schema_introspect), and `no-any-return` are exactly the codes that catch typo'd attribute access and wrong-argument bugs — the kind that make a test silently vacuous. A new test added to any of these files gets zero checking for those codes, with no per-line marker to prompt review.
**Fix:** Replace each module directive with inline `# type: ignore[code] — reason` at the actual offending lines (the same pattern `app/pipeline/delivery.py:232` already demonstrates), or at minimum shrink each directive to the codes provably needed and drop `union-attr`/`arg-type`/`attr-defined` where only a handful of lines trigger them:
```python
# instead of module-wide:
post_run = load_run(rid)
assert post_run is not None   # narrows union-attr away without any ignore
```

### WR-02: Inline `# type: ignore[...]` comments missing the D-09-required reason

**File:** `tests/test_atomic_persist.py:362-364`, `tests/test_combined_context.py:466`, `tests/test_combined_context.py:470`
**Issue:** D-09 locks every ignore to "error code + reason". These five carry the code but no reason:
```python
roster = _bare_roster(_biz_id)  # type: ignore[no-untyped-call]
email = _bare_inbound()  # type: ignore[no-untyped-call]
decision = _bare_decision()  # type: ignore[no-untyped-call]
...
orch_mod.extract = _spy_extract  # type: ignore[attr-defined]
orch_mod.extract = real_extract  # type: ignore[attr-defined]
```
The `attr-defined` pair in test_combined_context is doubly odd: `extract` **is** a defined attribute of the orchestrator module (it's imported at `orchestrator.py:60`), so the ignore is masking mypy's complaint about *assigning to* a module attribute — the reason comment matters precisely because the code alone doesn't explain that.
**Fix:** Append reasons, e.g. `# type: ignore[no-untyped-call] — legacy untyped helper, module is check_untyped_defs-only` and `# type: ignore[attr-defined] — deliberate module-attr spy swap, restored in finally`. Better for the `_bare_*` trio: annotate the three helpers (`def _bare_roster(business_id: uuid.UUID = ...) -> Roster:`) and delete the ignores outright.

### WR-03: `InMemoryRepo.load_run` cast hides `None` and diverges from the real repo contract

**File:** `tests/conftest.py:371-374`
**Issue:**
```python
def load_run(
    self, run_id: uuid.UUID, conn: Any = None
) -> dict[str, Any]:
    return cast(dict[str, Any], self.runs.get(str(run_id)))
```
The production seam this fake mirrors (`app/db/repo/runs.py:load_run`) was annotated `-> dict[str, Any] | None` in this same phase, and production callers were given explicit None-guards (`app/routes/runs.py:113-114`, `app/pipeline/clarification.py:71`). The fake now *lies*: `.get()` returns `None` for a missing run, but the cast stamps it `dict[str, Any]`, so any test exercising a missing-run path type-checks clean while carrying a typed None. A behavioral fake whose signature diverges from the real seam is exactly how the fake stops proving what production does.
**Fix:**
```python
def load_run(
    self, run_id: uuid.UUID, conn: Any = None
) -> dict[str, Any] | None:
    return self.runs.get(str(run_id))
```
(callers inside conftest that index the result already hold invariants that the run exists, or can add `assert`.)

### WR-04: `cast(resend.Emails.SendParams, {...})` on the outbound-send dict forfeits TypedDict checking on a money-adjacent path

**File:** `app/email/gateway.py:272-292`
**Issue:** `SendParams` is a TypedDict, so annotating the variable directly (`send_params: resend.Emails.SendParams = {...}`) would make mypy structurally check every key and value of the literal — the exact protection this phase exists to add. Wrapping the literal in `cast()` instead turns the whole dict unchecked: a future misspelled key (`"attachements"`), a wrong value type, or a removed SDK field will type-check clean and only fail live against Resend. The phase context explicitly asks for scrutiny of casts that could hide mismatches; this one is on the path that emails paystub PDFs to clients.
**Fix:** Prefer the direct annotation; if some entry genuinely fails checking (e.g. the `headers` comprehension), isolate *that one entry* with a typed local rather than casting the whole literal:
```python
headers: dict[str, str] = {k: v for k, v in [...] if v}
send_params: resend.Emails.SendParams = {
    "from": from_addr or get_settings().resend_from_addr,
    "to": [to_addr],
    "subject": subject,
    "text": body,
    "headers": headers,
    "attachments": [...],
}
```
Lines 297+ then mutate `send_params["reply_to"]` under full checking too.

### WR-05: `client.chat.completions.create()` duplicated into 4 near-identical blocks to dodge a `**extra` typing issue

**File:** `app/llm/client.py:147-168` (call_structured), `app/llm/client.py:246-263` (call_text); plus the duplicated `OpenAI(...)` constructor pair at `app/llm/client.py:238-246`
**Issue:** The pre-phase code built kwargs dynamically; the phase replaced it with if/else branches that repeat the full `create(...)` call — 4 copies of the model/messages/temperature/response_format/max_tokens parameter list across the two functions. Any future parameter change (e.g. bumping `_MAX_TOKENS` handling, adding a `seed`) must now be made in two places per function; drift between the DeepSeek and non-DeepSeek branches would silently change extraction determinism (`temperature=0`) or JSON mode on one provider only. The duplication is avoidable *within strict typing*: the openai v2 SDK accepts `extra_body: Body | None = None` and `timeout: ... | NotGiven = NOT_GIVEN`, so a single call site type-checks.
**Fix:**
```python
resp = client.chat.completions.create(
    model=cfg.model,
    messages=convo,
    temperature=0,
    response_format={"type": "json_object"},
    max_tokens=_MAX_TOKENS,
    extra_body=_NON_THINKING_EXTRA_BODY if _is_deepseek(cfg.model) else None,
)
```
and in call_text: `timeout=timeout_s if timeout_s is not None else NOT_GIVEN` on a single `OpenAI(...)` construction (import `NOT_GIVEN` from `openai`).

## Info

### IN-01: Production-path narrowing `assert`s vanish under `python -O`

**File:** `app/routes/webhook.py:156`, `app/routes/webhook.py:275`, `app/routes/webhook.py:299`, `app/pipeline/orchestrator.py:327`, `app/pipeline/orchestrator.py:962`
**Issue:** All five asserts are on invariants that hold today (each is coupled to the `outcome` value or to an immediately-preceding branch), so behavior is neutral. But they live on the live webhook/orchestrator request path, and `assert` compiles away under `-O` — if a future refactor breaks the `outcome` coupling, an optimized deployment proceeds with `None` instead of failing fast.
**Fix:** For the webhook trio specifically, prefer explicit guards: `if run_id is None: raise RuntimeError("new_run outcome without run_id")`. The orchestrator pair is lower risk (pure-function context) and can stay.

### IN-02: `raise TypeError("run not found")` is a misleading exception type

**File:** `app/routes/runs.py:115-116`
**Issue:** The new None-guard in `approve` raises `TypeError` for a missing DB row. It's caught by the route's broad `except Exception` boundary either way (so behavior is fine — arguably better than the old `AttributeError` inside `deliver`), but `TypeError` mislabels a lookup failure in `error_reason`/logs.
**Fix:** `raise LookupError(f"run {run_id} not found at approve")` (or `RuntimeError`).

### IN-03: `_fmt` docstring is stale after the annotation narrowed it to Decimal

**File:** `app/pipeline/pdf.py:104-106`
**Issue:** Signature is now `def _fmt(val: Decimal) -> str` but the docstring still says "Format a Decimal or numeric value".
**Fix:** Update to "Format a Decimal as $X,XXX.XX."

### IN-04: `call_text(**kwargs: object)` accepts and silently discards caller kwargs

**File:** `app/llm/client.py:200-205`
**Issue:** Pre-existing behavior (the old body never forwarded `**kwargs` either), but the phase annotated it rather than questioning it. A caller passing e.g. `max_tokens=...` gets no error and no effect. All current production callers use only named params, so this is latent, not live.
**Fix:** Drop `**kwargs` from the signature (test fakes already tolerate keyword absorption on their own side), or forward it into `create()`.

### IN-05: `cast(dict[str, Any], repo.load_run(...))` used where `assert is not None` would keep the runtime check

**File:** `tests/test_atomic_persist.py:217-218` (and the repeated pattern at test_atomic_persist.py:555, 680, 775+; `tests/test_stuck_run_recovery.py:307,335,377`; `tests/test_persistence.py:644`)
**Issue:** These casts erase the Optional instead of narrowing it. At `test_atomic_persist.py:217-218` the code has **both** — `post_run = cast(dict[str, Any], repo.load_run(run_id))` immediately followed by `assert post_run is not None` — where the cast makes the assert vacuous to mypy (only the runtime check survives). `assert`-narrowing alone gives the same mypy result *plus* a real failure message if the run vanished. Other files in the same phase (test_gateway.py:467, test_alias_write.py:1568) already use the better pattern.
**Fix:** Replace the casts with `run = repo.load_run(run_id); assert run is not None`.

### IN-06: Scripts type the psycopg connection as `Any` while app code types it `psycopg.Connection`

**File:** `scripts/demo_reset.py:66`, `scripts/reset_stuck_runs.py:21`
**Issue:** D-10 confines `Any` to dynamic edges (JSONB, LLM JSON, DB rows). A psycopg connection is not a dynamic edge — every repo function in `app/db/repo/` was typed `psycopg.Connection | None` in this same phase. The scripts' `conn: Any` / `c: Any` un-checks all method calls on those objects.
**Fix:** `def _rearm_demo_identity(conn: psycopg.Connection) -> None:` (add `import psycopg`), same for `_counts`.

---

## Notes on things checked and cleared

- **pyproject `[tool.mypy]`**: strict bundle + pydantic plugin over the full repo; the only overrides are the tests annotation-relaxation (`check_untyped_defs=true` kept on, per D-02) and a scoped `reportlab.*` `ignore_missing_imports` with justification — no broad exclude/ignore sneaked in. `files` covers 114/114 `.py` files.
- **CI typecheck job (D-06)**: bare `uv run mypy` == local command; blocking; SHA pins byte-identical to lint/test jobs; `uv sync --locked`; inherits `permissions: contents: read`. Job name says "--strict" while strictness comes from config — cosmetic only, parity is real.
- **`_ReceivedEmailLike` Protocol** (gateway.py:58-64): matches the phase mandate; `cast(Any)` was avoided; the cast target documents the Resend ResponseDict `__getattr__` runtime reality.
- **`ClarifiedFields.from_dict/to_dict` annotations**: callers pass `dict[str, Any]` from JSONB — assignable; Pydantic still validates at runtime; no behavior change.
- **`create_run` None-guard** (app/db/repo/runs.py:255-256): converts an impossible `row[0]` TypeError into an explicit RuntimeError — strictly better, unreachable for `INSERT ... RETURNING`.
- **`json.loads(bytes(handled.body))`** (runs.py:799): `bytes()` over an already-bytes/memoryview body — no-op wrap.
- **test_gateway.py:1215** `set_status(run_id, RunStatus.AWAITING_REPLY)` (was string `"awaiting_reply"`): conforms the test to the now-typed signature; integration behavior identical.
- **test_bootstrap_timeouts.py** patch target moved from `bootstrap.psycopg` to the `psycopg` module — same object, monkeypatch-reverted; equivalent.
- **No live-LLM leakage**: the only new test touching the eval `--record` path (`test_record_extraction_llm_client_import_resolves`) redirects `FIXTURE_DIR` to an empty tmp dir; the loop body (the only LLM call site) never executes, and the model-id print is env-only.

---

_Reviewed: 2026-07-10T22:17:41Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
