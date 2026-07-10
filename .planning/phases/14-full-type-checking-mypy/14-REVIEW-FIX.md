---
phase: 14-full-type-checking-mypy
fixed_at: 2026-07-10T23:59:00Z
review_path: .planning/phases/14-full-type-checking-mypy/14-REVIEW.md
iteration: 1
findings_in_scope: 5
fixed: 5
skipped: 0
status: all_fixed
---

# Phase 14: Code Review Fix Report

**Fixed at:** 2026-07-10T23:59:00Z
**Source review:** .planning/phases/14-full-type-checking-mypy/14-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 5 (fix_scope: critical_warning — 0 Critical, 5 Warning; 6 Info findings out of scope)
- Fixed: 5
- Skipped: 0

**Verification (all gates re-run after every fix and cumulatively at the end):**
- Bare `uv run mypy`: `Success: no issues found in 114 source files`
- `uv run ruff check .`: clean
- Full hermetic suite (`env -u DATABASE_URL -u ALLOW_DB_RESET -u ALLOW_LIVE_LLM uv run pytest -q`): **count-identical to the pre-fix baseline**. In the isolated fix worktree (no untracked `.env`) both the pre-fix base commit and the post-fix tree produce **615 passed / 51 skipped** — the one-test delta vs the review's 616/50 is purely environmental (`tests/test_dashboard.py:767` skips when no live DB is reachable; the main repo's `.env` supplies `DATABASE_URL` via pydantic-settings even with shell vars stripped). No test file involved in that skip was touched by any fix. In the main checkout with `.env` present the suite is expected to remain 616/50.

## Fixed Issues

### WR-01: Module-wide `# mypy: disable-error-code` blankets across 9 test files

**Files modified:** `tests/test_clarify_rounds.py`, `tests/test_compose_confirmation.py`, `tests/test_cr_regressions.py`, `tests/test_eval_wiring.py`, `tests/test_hitl.py`, `tests/test_llm_client.py`, `tests/test_multiround_context_edge.py`, `tests/test_orchestrator_states.py`, `tests/test_schema_introspect.py`
**Commit:** 9a2c210
**Applied fix:** Deleted all 9 file-scoped directives and resolved every one of the 69 errors they were masking at the source, per D-09:
- **Real annotations** for the untyped helpers/fakes that caused all `no-untyped-call` errors: `_bare_roster`, `_call_name`, `_calls_in_block` (test_clarify_rounds); `_DraftLLM`/`_RaisingDraftLLM` (test_compose_confirmation); the `_FakeOpenAI` family + `_set_tier_env` (test_llm_client); `_seed_run`, `_clean_script`, `_coastal_business_id` (test_orchestrator_states); `_script_in_sync` (test_schema_introspect); `_mk_extracted`, `_extraction_json` (test_multiround_context_edge).
- **Generic type arguments** added everywhere `type-arg` fired (`list[dict[str, Any]]`, `dict[str, Any]`, `tuple[Any, ...]`, `list[uuid.UUID]`, `list[str | None]`).
- **`assert run is not None` narrowing** for the `union-attr` on `load_run` (test_cr_regressions:241, the review's suggested pattern) and typed locals (`run_id: uuid.UUID = ...`) for the `no-any-return` sites.
- **Behavior-neutral conversions**: test_eval_wiring's `_compute_line_items` str arg wrapped in `uuid.UUID(...)` (Pydantic coerced it to the same UUID anyway); test_schema_introspect gained a single documented `_diff` adapter that casts `FakeConnection` to `psycopg.Connection` at one seam instead of 5 raw `arg-type` errors.
- **Three targeted per-line ignores, each with a reason** (the only ignores kept): `test_eval_wiring.py` (deliberate import of run_eval's private `_normalize` re-export binding to prove the eval itself uses the NFC-fixed normalizer), `test_hitl.py` (patching the route module's private `repo` import binding — the exact seam approve() calls — and mirroring delivery.py's WR-04 debug-attribute pattern), `test_orchestrator_states.py` (patching the orchestrator module's private `repo` binding).
All 69 tests in the touched files pass hermetically.

### WR-02: Inline `# type: ignore[...]` comments missing the D-09-required reason

**Files modified:** `tests/test_atomic_persist.py`, `tests/test_combined_context.py`
**Commit:** 3305888
**Applied fix:** Took the review's preferred option for the `_bare_*` trio: annotated `_bare_roster(business_id: uuid.UUID) -> Roster`, `_bare_inbound() -> InboundEmail`, `_bare_decision() -> Decision` and deleted the three reason-less `no-untyped-call` ignores outright. Appended the required reasons to the two `attr-defined` ignores in test_combined_context (deliberate module-attr spy swap over orchestrator's own `extract` binding, restored in finally).

### WR-03: `InMemoryRepo.load_run` cast hides `None` and diverges from the real repo contract

**Files modified:** `tests/conftest.py`, `tests/test_delivery.py`
**Commit:** 7f59de3
**Applied fix:** Applied the review's exact fix — `load_run` now returns `dict[str, Any] | None` truthfully (cast removed, unused `cast` import dropped), matching the production seam `app/db/repo/runs.py:load_run`. The one call site full-repo mypy then flagged (`test_delivery.py:433`) was narrowed with an explicit `assert final_run is not None` carrying a real failure message.

### WR-04: `cast(resend.Emails.SendParams, {...})` forfeits TypedDict checking on the outbound-send dict

**Files modified:** `app/email/gateway.py`
**Commit:** ef732d4
**Applied fix:** Replaced the whole-literal cast with the review's direct-annotation pattern: a typed `headers: dict[str, str]` local (comprehension narrowing handles the `if v` filter), an explicitly-typed `attachments_payload: list[resend.Attachment | resend.RemoteAttachment]` built with a per-element `resend.Attachment` annotation (comprehension-built dict literals don't infer TypedDicts — verified against the installed SDK's `SendParams`/`Attachment` definitions), and `send_params: resend.Emails.SendParams = {...}`. Every key/value of the money-adjacent literal, including the later `reply_to` mutation, is now structurally checked. Runtime dict/list contents are identical.

### WR-05: `client.chat.completions.create()` duplicated into 4 near-identical branches

**Files modified:** `app/llm/client.py`, `tests/test_llm_client.py`
**Commit:** 3aa0539
**Applied fix:** Applied the review's exact fix: single `create(...)` call per function with `extra_body=_NON_THINKING_EXTRA_BODY if _is_deepseek(cfg.model) else None` (call_text keeps its `copy.deepcopy`), and one `OpenAI(...)` construction in call_text with `timeout=timeout_s if timeout_s is not None else NOT_GIVEN` (`NOT_GIVEN` imported from `openai`). `extra_body=None` and `timeout=NOT_GIVEN` are the SDK defaults — nothing changes on the wire; extraction stays `temperature=0` + `json_object` on both providers from one parameter list. Two test assertions that inspected raw fake-recorded kwargs were updated to the wire-equivalent checks (`kwargs.get("extra_body") is None`; `inst.timeout is NOT_GIVEN`) with explanatory messages; no assertion was weakened (a non-DeepSeek tier sending the toggle still fails).

## Skipped Issues

None — all findings were fixed.

---

_Fixed: 2026-07-10T23:59:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
