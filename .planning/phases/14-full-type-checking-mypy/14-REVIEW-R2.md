---
phase: 14-full-type-checking-mypy
reviewed: 2026-07-10T23:13:29Z
depth: deep
files_reviewed: 15
files_reviewed_list:
  - app/email/gateway.py
  - app/llm/client.py
  - tests/conftest.py
  - tests/test_atomic_persist.py
  - tests/test_clarify_rounds.py
  - tests/test_combined_context.py
  - tests/test_compose_confirmation.py
  - tests/test_cr_regressions.py
  - tests/test_delivery.py
  - tests/test_eval_wiring.py
  - tests/test_hitl.py
  - tests/test_llm_client.py
  - tests/test_multiround_context_edge.py
  - tests/test_orchestrator_states.py
  - tests/test_schema_introspect.py
findings:
  critical: 0
  warning: 1
  info: 2
  total: 3
status: issues_found
---

# Phase 14: Code Review Report — Round 2 (confirming round on fix commits)

**Reviewed:** 2026-07-10T23:13:29Z
**Depth:** deep
**Files Reviewed:** 15 (full diff of fix commits 9a2c210, 3305888, 7f59de3, ef732d4, 3aa0539 — range `493064b..3aa0539`, docs commits excluded; every hunk read)
**Status:** issues_found (1 Warning, 2 Info — no behavioral, proof-strength, or wire regression in any fix)

## Summary

This round reviewed ONLY the five WR-01..WR-05 fix commits, adversarially: every hunk of the 843-line diff was read, the SDK-equivalence claims were verified empirically against the installed `openai` and `resend` packages in `.venv` (not taken on faith), and the full verification battery was re-run.

**Independently reproduced:**
- `uv run mypy` → `Success: no issues found in 114 source files`
- `uv run ruff check .` → `All checks passed!`
- Hermetic suite (`env -u DATABASE_URL -u ALLOW_DB_RESET -u ALLOW_LIVE_LLM uv run pytest -q`) → **616 passed, 50 skipped** — exactly the expected counts.
- `grep` of the fix range: **zero** new `raising=False`, `pytest.skip`, `xfail`, broadened `except`, or fixture-value changes.
- **Zero** module-wide `# mypy: disable-error-code` directives and **zero** bare (codeless) ignores remain anywhere in `app/ eval/ scripts/ tests/`.
- Because `[tool.mypy] strict = true` includes `warn_unused_ignores` (and the `tests.*` override relaxes only the four annotation flags), the clean mypy run is itself proof that **every surviving inline ignore is actually needed** — none is dead weight.

## Per-Fix Verdicts

| Fix | Commit | Verdict |
|-----|--------|---------|
| WR-01 (9 test files, blanket disables → real annotations) | 9a2c210 | **ISSUE — Warning (WR-R2-01)**: one introduced *false* annotation in a test helper (`str` where the runtime value is `uuid.UUID`). All other hunks proof-preserving; no test weakened. |
| WR-02 (`_bare_*` trio + spy-swap ignore reasons) | 3305888 | **CONFIRMED-SOUND** |
| WR-03 (`InMemoryRepo.load_run` → `dict[str, Any] \| None`) | 7f59de3 | **CONFIRMED-SOUND** |
| WR-04 (gateway `SendParams` cast → direct TypedDict annotation) | ef732d4 | **CONFIRMED-SOUND** |
| WR-05 (llm client single call sites) | 3aa0539 | **CONFIRMED-SOUND** |

### WR-01 trace (9a2c210) — the big one

Every hunk in the 9 files was checked against the charter's four failure modes:

- **(a) Pass-by-skipping asserts:** The two added narrowing asserts (`tests/test_cr_regressions.py:233` after `repo_mod.load_run(...)`; `tests/test_delivery.py:434` after `store.load_run(...)`) convert what was previously a `TypeError`/`KeyError` on `None` subscript into an explicit assert failure. Both still FAIL the test on `None` — nothing is skipped, no previously-exercised case is bypassed. No `assert isinstance` was added anywhere in the range.
- **(b) Fake/helper annotation semantics:** All annotated helpers (`_DraftLLM`, `_RaisingDraftLLM`, `_FakeOpenAI` family, `_script_in_sync`, `_call_name`, `_seed_run`, `_set_tier_env`, `_minimal_run`) keep identical defaults, return values, and signatures. `_minimal_run() -> dict[str, str]` is truthful (both values are str). One exception — see WR-R2-01 below.
- **(c) Production branch changes:** One hunk is NOT purely typing: `tests/test_eval_wiring.py:94` changes `_compute_line_items("00000000-…")` → `_compute_line_items(uuid.UUID("00000000-…"))`. Traced: `_compute_line_items` (app/pipeline/orchestrator.py:996) uses `run_id` only in `item.model_copy(update={"run_id": run_id, …})` — `model_copy(update=…)` does NOT validate, so the old str was stamped raw into the item; the test asserts only the money fields (gross/401k/withholding/FICA/net), never `run_id`. No branch of production code changes; the new value matches what production actually passes (a UUID). Proof-preserving and strictly more production-faithful. All seven golden money assertions are byte-identical.
- **(d) Surviving per-line ignores (4, not 3):** each verified needed (warn_unused_ignores would flag otherwise) and reason-accurate:
  - `tests/test_eval_wiring.py:148` `[attr-defined]` — `eval/run_eval.py:41` really does bind `_normalize` as a private re-export (`from app.pipeline.reconcile_names import normalize_name as _normalize`); under strict's `no_implicit_reexport` the import errors; the test deliberately imports run_eval's own binding to prove the eval uses the NFC-fixed normalizer. Accurate.
  - `tests/test_hitl.py:82` and `tests/test_orchestrator_states.py:162` `[attr-defined]` — both patch a module's private `repo` import binding (non-re-exported module attr under strict). Reasons accurate; both seams are exactly what the code under test calls.
  - `tests/test_hitl.py:180` `[attr-defined]` — `exc.payroll_roster` mirrors `app/pipeline/delivery.py:232`, which sets the same best-effort debug attribute with the same ignore code. Accurate.
- **(e) Non-typing hunks:** the `uuid.UUID(...)` argument change (cleared above, item c); the `Roster` import hoisted from function-local to module top in test_atomic_persist/test_clarify_rounds (no side effects — `app.models.roster` was already imported at module top for `NameMatchResult`); `tests/test_schema_introspect.py`'s new `_diff` helper wrapping `diff_against_live` in `cast("psycopg.Connection[tuple[Any, ...]]", conn)` — runtime no-op over the same FakeConnection, replacing the old module-wide `arg-type` blanket with one documented seam bridge. All five `_diff` call sites are mechanical substitutions; scripted rows and assertions untouched.

### WR-02 trace (3305888)

`_bare_roster(business_id: uuid.UUID) -> Roster` / `_bare_inbound() -> InboundEmail` / `_bare_decision() -> Decision` — bodies byte-identical, the only call site passes `_biz_id` (a `uuid.UUID`), no defaults changed; the three `no-untyped-call` ignores deleted outright (the better option R1 suggested). The two spy-swap ignores in test_combined_context now carry reasons that are verifiably accurate: the swap targets `orch_mod.extract` (the orchestrator's own module-level binding) and the `finally` block does restore `real_extract`.

### WR-03 trace (7f59de3)

Fake now: `def load_run(self, run_id: uuid.UUID, conn: Any = None) -> dict[str, Any] | None: return self.runs.get(str(run_id))` — mirrors the real seam `app/db/repo/runs.py:260` (`(run_id: uuid.UUID, conn: psycopg.Connection | None = None) -> dict[str, Any] | None`) exactly.

**Runtime is provably unchanged**: the pre-fix `cast()` was static-only — `.get()` already returned `None` for a missing run. All 113 `load_run(` call sites across tests/ were enumerated: the overwhelming majority go through the `Any`-typed `fake_repo` fixture (statically unchecked before AND after — no behavior or checking change), the `cast(dict[str, Any], repo.load_run(...))` sites in test_atomic_persist/test_stuck_run_recovery/test_persistence hit the *real* repo module (unaffected by the fake's annotation; IN-05 from R1 remains open by design — it was Info, not in this fix's scope), and the ONE caller that statically sees the fake's new Optional (`tests/test_delivery.py:433`, `store = InMemoryRepo()` typed directly) got the correct `assert final_run is not None` narrowing — found-run behavior identical, missing-run now fails with a message instead of a TypeError. conftest itself never calls `self.load_run` internally.

### WR-04 trace (ef732d4)

The rebuilt literal is **key-for-key and value-for-value identical** to the pre-fix cast version:
- Keys: `from`/`to`/`subject`/`text`/`headers`/`attachments` — same six, none renamed/dropped/added; `reply_to` still added only in the post-build `if _reply_to:` branch (untouched by the commit).
- Values: identical expressions (`from_addr or get_settings().resend_from_addr`, `[to_addr]`, same headers comprehension with the same only-if-truthy filter over the same three header tuples, same `base64.b64encode(pdf_bytes).decode()` per attachment). The attachments dict-comprehension → typed for-loop is semantically identical including the always-present-even-when-empty `[]` (matching pre-fix behavior for both `headers` and `attachments`).
- **mypy really checks it now**: `send_params: resend.Emails.SendParams = {...}` is a direct TypedDict annotation; verified against the installed resend SDK that `SendParams.attachments` is `NotRequired[List[Union[Attachment, RemoteAttachment]]]` (the typed local matches exactly, so invariance holds), `Attachment.content: Union[List[int], str]` accepts the base64 str, and `resend.Attachment`/`resend.RemoteAttachment` are top-level exports. The only cast left in gateway.py is the pre-existing inbound `_ReceivedEmailLike` cast (cleared in R1) — nothing on the send path launders through `cast`/`Any`, and the later `send_params["reply_to"] = _reply_to` mutation is now checked too.

### WR-05 trace (3aa0539)

Wire-equivalence verified against the installed openai SDK, **empirically**, not just by reading:
- `make_request_options` (openai/_base_client.py:2042): `if extra_body is not None: options["extra_json"] = ...` — `extra_body=None` merges nothing into the request body; `Completions.create`'s `extra_body` default IS `None`. So non-DeepSeek sends byte-identical requests to the old kwarg-omitted branch, for BOTH `call_structured` and `call_text`.
- DeepSeek branch: `call_structured` passes `_NON_THINKING_EXTRA_BODY` (no deepcopy — same as pre-fix), `call_text` passes `copy.deepcopy(_NON_THINKING_EXTRA_BODY)` (deepcopy preserved — same as pre-fix). Both toggles intact.
- Per-branch params identical: `temperature=0` + `response_format={"type":"json_object"}` + `_MAX_TOKENS` in call_structured; caller `temperature` + `_MAX_TOKENS` (no response_format) in call_text.
- Timeout/retries: executed `OpenAI(api_key='x')` vs `OpenAI(api_key='x', timeout=NOT_GIVEN)` in the project venv — both resolve to `Timeout(connect=5.0, read=600, write=600, pool=600)`; `NOT_GIVEN` is the constructor's literal default, so it is NOT the `timeout=None` (no-timeout) semantics. `max_retries=0` unconditional in both old branches and the new single site. `call_structured`'s `timeout=_STRUCTURED_TIMEOUT_S, max_retries=0` untouched.
- The two updated assertions are equivalent-or-stronger: `kwargs.get("extra_body") is None` protects the same wire property as the old `"extra_body" not in kwargs` (given the verified SDK None-elision) and still fails if the toggle leaks to a non-DeepSeek tier; `inst.timeout is NOT_GIVEN` is strictly STRONGER than the old `inst.timeout is None` — the old assertion could not distinguish "omitted" from a hypothetical regression to explicit `timeout=None` (which would disable the timeout entirely); the new one fails on that regression. The deepseek-positive assertions (`"extra_body" in kwargs` + `["thinking"]["type"] == "disabled"`) are unchanged.

## Warnings

### WR-R2-01: `test_orchestrator_states.py` annotates business_id as `str` where the runtime value is `uuid.UUID`

**File:** `tests/test_orchestrator_states.py:30` (`_seed_run(..., *, business_id: str, ...)`) and `tests/test_orchestrator_states.py:57-59` (`_coastal_business_id(fake_repo: Any) -> str` with `business_id: str = fake_repo.contact_to_business[...]`)
**Issue:** Introduced by 9a2c210. `fake_repo.contact_to_business` is built in conftest as `{b["contact_email"]: b["id"] for b in seeded.businesses}`, and the seed ids are `uuid.UUID(...)` literals (`app/db/seed.py:52,58,64`); `InMemoryRepo.create_run` itself declares `business_id: uuid.UUID` (`tests/conftest.py:341-344`). The new annotations assert `str` on a value that is a `uuid.UUID` at runtime — mypy cannot catch the lie because `fake_repo` is `Any`-typed, so the annotation on the local is trusted unverified. No behavior changes and no test is weakened, but this is a false type statement planted by the very fix whose contract was "replace blankets with *real* annotations": a future edit that trusts it (e.g. `business_id.lower()`, or an f-string comparison against a str-keyed dict) type-checks clean and breaks at runtime. Note the sibling hunks in the same file got this right (`run_id: uuid.UUID = fake_repo.create_run(...)`).
**Fix:** Two-line change:
```python
def _seed_run(
    fake_repo: Any, *, business_id: uuid.UUID, body: str = "Maria Chen 40 regular. James salaried."
) -> uuid.UUID: ...

def _coastal_business_id(fake_repo: Any) -> uuid.UUID:
    business_id: uuid.UUID = fake_repo.contact_to_business["payroll@coastalcleaning.example"]
    return business_id
```
(`uv run mypy` stays green — all uses flow back into `Any`-typed fake seams.)

## Info

### IN-R2-01: Pre-existing reasonless inline ignore at `test_llm_client.py:202` survived both rounds

**File:** `tests/test_llm_client.py:202`
**Issue:** `tier="decision",  # type: ignore[arg-type]` carries a code but no D-09 reason. NOT introduced by the fix range (present at 493064b; originated in phase 02.1 commit d5bbef4) and not among the five lines R1's WR-02 listed — so the WR-02 fix is not at fault — but it is the same policy-gap class WR-02 closed, in a file both rounds touched. The ignore itself is legitimate (deliberately passing a removed tier to assert the `ValueError`).
**Fix:** `# type: ignore[arg-type]  # deliberately passing the removed 'decision' tier to prove it raises (D-21-05)`.

### IN-R2-02: `call_text`'s DeepSeek non-thinking toggle has no test pin (pre-existing gap, now on rewritten code)

**File:** `tests/test_llm_client.py` (absence), `app/llm/client.py:249-251`
**Issue:** The only `extra_body` assertions (lines 223-225, 238-240) exercise `call_structured`. No test asserts that `call_text` sends the deepseek toggle (or the deepcopy). This gap predates the fix range — the pre-fix file had the identical coverage — so WR-05 weakened nothing; but WR-05 rewrote exactly that call site, and its correctness is currently proven only by this review's source trace, not by a test.
**Fix:** Add a `call_text` sibling of `test_deepseek_tier_sends_non_thinking_toggle` asserting `create_calls[0]["extra_body"]["thinking"]["type"] == "disabled"` (and, for the deepcopy contract, that the recorded dict `is not _NON_THINKING_EXTRA_BODY`).

---

## Verdict

All five fixes do what R1 asked, with zero behavioral, proof-strength, security, or wire-level regressions — the two SDK-equivalence claims (extra_body None-elision; `timeout=NOT_GIVEN` == omitted, NOT `None`) were confirmed empirically against the installed openai 2.x in `.venv`, the gateway send dict is key/value-identical under real TypedDict checking, the fake repo now matches the real seam, and the two rewritten test assertions are equivalent-or-stronger. The single defect found (WR-R2-01) is a non-behavioral false annotation in one test helper, invisible to mypy through an `Any` seam, with a two-line fix.

**READY** — no blockers; WR-R2-01 (Warning) should be fixed in a trivial follow-up alongside the two Info items, but nothing in the five fix commits needs to be reverted or re-verified.

_Reviewed: 2026-07-10T23:13:29Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: deep_
