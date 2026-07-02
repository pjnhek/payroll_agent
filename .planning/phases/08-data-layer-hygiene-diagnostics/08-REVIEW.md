---
phase: 08-data-layer-hygiene-diagnostics
reviewed: 2026-07-02T21:29:48Z
depth: standard
files_reviewed: 15
files_reviewed_list:
  - app/db/repo.py
  - app/db/schema.sql
  - app/db/supabase.py
  - app/main.py
  - app/models/status.py
  - app/pipeline/orchestrator.py
  - app/templates/run_detail.html
  - app/templates/runs_list.html
  - tests/conftest.py
  - tests/test_dashboard.py
  - tests/test_models_contracts.py
  - tests/test_orchestrator_states.py
  - tests/test_persistence.py
  - tests/test_status_drift.py
  - tests/test_threading.py
findings:
  critical: 1
  warning: 6
  info: 5
  total: 12
status: issues_found
---

# Phase 8: Code Review Report

**Reviewed:** 2026-07-02T21:29:48Z
**Depth:** standard
**Files Reviewed:** 15
**Status:** issues_found

## Summary

Reviewed the OPS2-01 PII-scrubbing diagnostics path (`_scrub` / `_compile_name_pattern` / `_build_error_detail` / `record_run_error`), the `load_all_runs` explicit projection, the schema additions (error_detail column, 3 indexes, status CHECK DO-block swap), the orchestrator/main wiring, both templates, and the 6 test files. All 121 in-scope hermetic tests pass (`uv run pytest -q`, 2 live-DB skips). Findings below were verified by tracing argument flow against live source and, for the scrubber, by executing probe inputs against the real `_scrub` — not by reading prose.

The headline: the phase's own RUN_COLS comment ("a column missing from this constant is invisible to every load_run caller") describes a bug class that is **live right now** for `alias_candidates` — the alias-learning write side and the resume-time candidate binding are dead no-ops against a real database, masked by the hermetic `InMemoryRepo` whose `load_run` returns full dicts. The scrubber itself is well-built for its reviewed cases (offset-safe, mark-aware boundaries verified), but two unreviewed input classes defeat it entirely.

## Critical Issues

### CR-01: `alias_candidates` missing from RUN_COLS — alias learning and resume binding are silent no-ops on a live DB

**File:** `app/db/repo.py:95-98` (RUN_COLS), consumed at `app/pipeline/orchestrator.py:292` and `app/pipeline/orchestrator.py:1096-1101`
**Issue:** `RUN_COLS` is:

```
"id, business_id, source_email_id, status, extracted_data, decision,"
" reconciliation, error_reason, error_detail, pay_period_start, pay_period_end, updated_at"
```

`alias_candidates` is absent (verified via `git log -L`: it has never been in RUN_COLS since the constant was created in 78764e8). Two orchestrator paths read it from `load_run()`:

1. `resume_pipeline` STEP A (`orchestrator.py:292`): `_pre_candidates = (pre_run_data.get("alias_candidates") or {})` — always `{}` on a real dict_row, so `_none_tokens` is always empty and the STEP C/D pre-vs-post diff that binds a pending candidate token to the newly-resolved employee **never executes** (`if _none_tokens and _pre_candidates:` is always False).
2. `_write_aliases_if_safe` (`orchestrator.py:1096-1101`): `alias_candidates = run_data.get("alias_candidates") or {}` — always `{}`, so the function returns before writing any alias at the approval gate.

Net effect: `set_alias_candidates` writes `{token: None}` at clarify time (that half works — it has its own dedicated writer), but the candidate is never bound at resume and never persisted to `employees.known_aliases` at approval. The "human-confirmation learning loop" WRITE side (a headline feature per CLAUDE.md) is disabled in production. Every hermetic test passes because `tests/conftest.py::InMemoryRepo.load_run` returns the full in-memory run dict *including* `alias_candidates` — the exact fixture-vs-reality gap this project has been burned by before (live-gate dateless-email bug).

This is pre-existing (not introduced by phase 8's diff), but phase 8's stated deliverable OPS2-01 explicitly audited this bug class for `error_detail` and documented the failure mode in the RUN_COLS comment (`repo.py:88-94`) without checking the constant's other consumers.

**Fix:**
```python
RUN_COLS = (
    "id, business_id, source_email_id, status, extracted_data, decision,"
    " reconciliation, error_reason, error_detail, alias_candidates,"
    " pay_period_start, pay_period_end, updated_at"
)
```
Plus a non-hermetic-shaped regression test: script a `FakeConnection` dict_row through the real `repo.load_run` (the pattern `test_run_detail_renders_error_detail_end_to_end` already uses) and assert `"alias_candidates" in fake_conn.all_sql()`. Longer-term: derive the InMemoryRepo run-dict keys from RUN_COLS so the fake cannot carry keys the real projection omits.

## Warnings

### WR-01: An NFD-stored roster name/alias defeats the scrubber entirely

**File:** `app/db/repo.py:409-429` (`_compile_name_pattern`)
**Issue:** The pattern is built char-by-char from the raw candidate string. `_ACCENT_CLASS_MAP` is keyed by *precomposed* characters only. If the stored candidate is NFD-decomposed (e.g. an alias learned via `update_known_alias` from an NFD-encoded client email — the token comes straight from LLM extraction of the raw body), the map lookup never fires: `'e'` escapes as bare `e`, then `'́'` escapes as a literal combining mark. The resulting pattern matches only the NFD rendering. Verified by executing the real `_scrub`:

```
candidate stored as NFD "José García":
  _scrub("failed for José García at row 3")  -> "failed for José García at row 3"   # NFC leaks
  _scrub("failed for Jose Garcia at row 3")  -> "failed for Jose Garcia at row 3"   # bare leaks
```

Both renderings of the full name reach `error_detail` and the dashboard unredacted — total redaction failure for that name, not a fragment. The R2-1 offset-drift rationale forbids normalizing the *message*; normalizing the *candidate* is offset-safe (only the pattern side changes).
**Fix:** First line of `_compile_name_pattern`:
```python
name = unicodedata.normalize("NFC", name)
```
Add a test with an NFD-stored candidate vs NFC/bare message renderings (the existing R2-1 test only varies the message, never the stored candidate).

### WR-02: `_ACCENT_CLASS_MAP` omits common diacritics — bare renderings of umlaut/grave names leak

**File:** `app/db/repo.py:398-406`
**Issue:** The map covers acute vowels + ñ + ç only. The map's own justification ("real input frequently strips diacritics entirely") applies equally to ü/ö/ä/à/è/ì/ò/ù. Verified: for stored `"Björn Müller"`, `_scrub("failed for Bjorn Muller")` returns the input unchanged — the full name leaks in its most common ASCII-ified rendering. German/Scandinavian names are not exotic roster content.
**Fix:** Extend the transcribed table with the remaining Latin-1 letters (ä ö ü à è ì ò ù â ê î ô û ë ï) using the same three-way alternation, or generate the table once at import time from `unicodedata.decomposition` over the Latin-1 range (still static, still offset-safe — only candidates are affected).

### WR-03: `record_run_error`'s terminal-status guard is check-then-act, not atomic

**File:** `app/db/repo.py:510-529`
**Issue:** The WR-04 guard does `SELECT status` then a separate unconditional `UPDATE ... WHERE id = %s`. Under READ COMMITTED, a concurrent transaction can commit `sent`/`reconciled` (e.g. `_deliver`'s `set_status(SENT)` racing a late resume's error path) between the read and the write; the UPDATE then clobbers the terminal run to ERROR — the exact outcome WR-04 exists to prevent. The docstring's "read the current status inside the same transaction" does not make check-then-act atomic. `claim_status` already demonstrates the correct CAS pattern in this file.
**Fix:** Fold the guard into the write:
```sql
UPDATE payroll_runs SET error_reason = %s, error_detail = %s, updated_at = now()
WHERE id = %s AND status NOT IN ('sent','reconciled','rejected','error')
RETURNING id
```
If no row returns, log the skip (preserves the current log message); only call `set_status(ERROR)` when the claim succeeded. Alternatively `SELECT ... FOR UPDATE`.

### WR-04: Delivery-stage `error_detail` is never scrubbed for roster names

**File:** `app/main.py:508`, `app/pipeline/orchestrator.py:1156-1294` (`_deliver`)
**Issue:** `approve()` calls `record_run_error(..., detail_exc=exc, stage="delivery")` with no roster, so `_scrub` runs email-regex-only. The comment claims "this boundary has no roster to pass," but `_deliver` itself loads a roster at Step 4 and interpolates `emp_name` into PDF generation and `submitted_name`/business context into `compose_confirmation` — a reportlab/compose/gateway exception raised after that point can carry employee full names in `str(exc)`, which then persist to `error_detail` and render on the run-detail error banner. This is the one error boundary where roster names are *most* likely to appear in exception text, and the only one with no name redaction.
**Fix:** Have `_deliver` attach the loaded roster to failures it raises (e.g. `exc.add_note()` is not scrub-usable, so instead: wrap Steps 4+ in `_deliver` so the caller-visible exception is re-raised after the roster is stashed on it, or move the `record_run_error` call into `_deliver`'s own boundary where `roster` is in scope — mirroring the HIGH #1 fix already applied to `_run`). D-8-01b forbids the *scrubber* loading a roster; it does not forbid the error boundary passing one it already has.

### WR-05: Omitting `detail_exc`/`stage` actively NULLs a previously-persisted `error_detail`, contradicting the docstring

**File:** `app/db/repo.py:503-527`
**Issue:** The docstring says "When `detail_exc` or `stage` is omitted, `error_detail` is left `None` (unchanged behavior)." The UPDATE unconditionally sets `error_detail = %s` with `detail = None`, so a legacy-shape two-arg call (explicitly kept "positional-compatible" for existing call sites) *erases* any prior error's diagnostic. All three current production callers pass both kwargs, so impact is latent — but the contract that justified keeping the two-arg shape is documented incorrectly, and the next caller written against the docstring will silently destroy diagnostics.
**Fix:** Either make the docstring truthful ("error_detail is overwritten with NULL"), or preserve on omission:
```sql
SET error_reason = %s, error_detail = COALESCE(%s, error_detail), updated_at = now()
```
(Preserving is arguably wrong too — a stale detail next to a fresh reason misleads. Truthful docstring + always-overwrite is the simpler correct contract.)

### WR-06: Status-CHECK DO-block drops one arbitrary constraint matching `LIKE '%status%'`

**File:** `app/db/schema.sql:134-166`
**Issue:** `SELECT conname INTO _con_name ... WHERE conname LIKE '%status%'` without `STRICT` silently takes an arbitrary single row when multiple constraints match, and the LIKE is name-fuzzy: any future CHECK on `payroll_runs` whose name contains "status" (e.g. a hypothetical `payroll_runs_send_status_check`) would be **dropped and never restored** — the re-ADD only recreates the 10-value status check. The same fuzzy-DROP pattern exists in the mirrored `email_messages` purpose block. Today only one matching constraint exists, so this is latent, but executing `DROP CONSTRAINT` off a substring match is a dangerous migration idiom that fails silently.
**Fix:** Match the constraint by its definition, not its name — narrow with `pg_get_constraintdef(oid) LIKE '%status IN%'`, or better: drop only when the definition differs from the target 10-value set (also eliminates the wasteful DROP+revalidate ACCESS EXCLUSIVE churn on every non-destructive bootstrap re-apply).

## Info

### IN-01: Non-roster spellings of employee names leak into `error_detail` by design

**File:** `app/db/repo.py:432-457`
**Issue:** Roster-only scrubbing (D-8-01b, locked) cannot redact a typo'd submitted name — the most common content of an unresolved-name failure. Verified: with roster `David Reyes` (alias `Dave`), `_scrub("cannot resolve 'Dave Reyez'")` → `"cannot resolve '[REDACTED] Reyez'"` — the surname fragment survives. Accepted design limitation; documenting the residual risk here so it is a recorded decision, not an unnoticed gap.
**Fix:** None required for v1; if this becomes a concern, redact capitalized-token bigrams adjacent to a redacted span.

### IN-02: Redundant exception tuple in webhook verify

**File:** `app/main.py:273`
**Issue:** `except (ValueError, Exception) as exc:` — `Exception` subsumes `ValueError`; the tuple misleads readers into thinking the catch is narrow when it swallows everything (including bugs inside `gateway.verify`) as a 400.
**Fix:** `except Exception as exc:` with the existing `# noqa: BLE001`-style justification, or genuinely narrow the catch.

### IN-03: `resume_pipeline` comment contradicts the code (harmless)

**File:** `app/pipeline/orchestrator.py:251-256`
**Issue:** Comment says `roster=None` is "the first statement inside the try block"; it is actually the statement *before* `try:`. The binding guarantee holds either way — comment drift only.
**Fix:** Update the comment.

### IN-04: `test_exactly_three_new_indexes` asserts a file-global count

**File:** `tests/test_status_drift.py:296-300`
**Issue:** `sql.count("CREATE INDEX IF NOT EXISTS") == 3` counts every index in schema.sql, not the three OPS2-02 ones — any future legitimate index fails this test with a message ("expected exactly 3 ... in schema.sql") that reads like the new index is the bug. Acceptable as a deliberate forcing function; flagged so the future failure is understood as "update the count after review," not "delete the index."
**Fix:** Assert the three named indexes individually exist (already done by the sibling tests) and drop the global count, or rename/extend the assertion message to say the count must be bumped when a reviewed index is added.

### IN-05: No min-length constraint on `full_name`/aliases — a whitespace-only candidate would over-redact everything

**File:** `app/db/repo.py:445-451`, `app/models/roster.py:38-39`
**Issue:** `_scrub` filters falsy candidates (`if employee.full_name` / `if alias`) but `" "` is truthy; a whitespace-only stored name/alias would compile to a pattern matching every space, turning the whole detail into `[REDACTED]`-joined tokens. Fail direction is over-redaction (safe for PII, useless for diagnostics). Also `_EMAIL_RE` partially redacts unicode local parts (`marí[REDACTED]` for `maría.chen@x.test`), leaving a short name fragment.
**Fix:** `if employee.full_name.strip()` / `if alias.strip()` in the candidate loop; optionally add `min_length=1`-after-strip validation on the Employee model.

---

_Reviewed: 2026-07-02T21:29:48Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
