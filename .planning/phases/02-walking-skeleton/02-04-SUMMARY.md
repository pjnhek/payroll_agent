---
phase: 02-walking-skeleton
plan: 04
subsystem: pipeline
tags: [reply-routing, header-chain-threading, idempotent-resume, sender-revalidation, clar-03, live-llm-gate, message-id-anchor]

# Dependency graph
requires:
  - phase: 02-walking-skeleton (Plan 01)
    provides: "The FULL repo surface — find_awaiting_reply_for_header (awaiting_reply-only resume lookup), find_any_run_for_header (late-reply observability, FIX 10), load_source_email (cleaned inbound body, FIX C), find_business_by_sender (INGEST-03 sender match), set_status (sole writer, FIX B), persist_extracted/decision/reconciliation, replace_line_items, get_outbound_message_id (FIX-3 anchor) — all parameterized; the live_llm marker + ALLOW_LIVE_LLM two-factor flag + allow_live_llm Settings field"
  - phase: 02-walking-skeleton (Plan 02)
    provides: "The orchestrator run_pipeline state machine + the four pure stages (extract stamps the code-owned run_id via ExtractionPayload, FIX A; reconcile/validate/decide), the in-memory fake_repo + FIFO mock_llm conftest, the webhook /webhook/inbound (dedupe + sender-match + body-clean)"
  - phase: 02-walking-skeleton (Plan 03)
    provides: "The clarify draft+send branch (gateway.send_outbound mints the synthetic Message-ID on the outbound email_messages row, the FIX-3 anchor) + the AWAITING_REPLY pause; the David Reyez gate-block hero fixture; the conftest InMemoryRepo outbound surface (insert_email_message + get_outbound_message_id)"
provides:
  - "Header-chain reply routing (CLAR-02): a header-bearing inbound is routed to its paused run BEFORE first ingest via repo.find_awaiting_reply_for_header (awaiting_reply only), so a reply resumes its run instead of opening a second one; subject/provider-thread fallback is a deliberately-deferred P6 concern, NOT built"
  - "Reply sender revalidation (FIX 5): after the header match, reply.from_addr is re-asserted against the matched run's business (reusing find_business_by_sender) — a mismatch is logged and NOT resumed, so a spoofed reply on a guessed/leaked Message-ID cannot bypass INGEST-03"
  - "Late-reply observability (FIX 10): a header match to a run NOT in awaiting_reply (sent/reconciled/rejected/computed) is found via repo.find_any_run_for_header and logged as a late reply, NOT resumed"
  - "orchestrator.resume_pipeline(run_id, inbound): idempotent AND lossless re-entry at extraction — rebuilds the context from (original cleaned body via load_source_email + reply body), passes the code-owned run_id into extract (FIX A), overwrites extracted_data wholesale + replaces line items by run (FIX 4 + FIX C); shares the _run_stages() gate path with run_pipeline"
  - "fixtures/clarify_reply.json: a canonical reply InboundEmail with a substitutable __CLARIFICATION_MESSAGE_ID__ placeholder + a from_addr matching the run's business + an answer-only body (corrects David Reyes WITHOUT restating hours) — completes the clarify→reply→resume loop with ZERO real email (EMAIL-01)"
  - "tests/test_live_llm.py: the env-gated two-factor live hero exit-gate test (D-A4-01a) — skips by default; the live RUN is a human checkpoint (Task 3)"
affects: [walking-skeleton, pipeline, orchestrator, eval, dashboard]

# Tech tracking
tech-stack:
  added: []  # no new packages — reuses Plan 01-03 deps; no install task (T-04-SC)
  patterns:
    - "Reply-vs-first-ingest routing: a header-bearing inbound is routed on the RFC In-Reply-To/References chain BEFORE the sender-match→create_run path, so the header chain (the primary AND only Phase 2 routing path) resumes the paused run; no-header inbounds fall through unchanged"
    - "Two-lookup reply decisioning: find_awaiting_reply_for_header (resume, awaiting_reply only) THEN find_any_run_for_header (late-reply log) — the resume path and the late-reply observation are structurally separate calls"
    - "Sender revalidation on the reply path: the SAME find_business_by_sender comparison used at first ingest is re-applied to the matched run's business, so INGEST-03 holds on replies too (a guessed Message-ID is not sufficient to resume)"
    - "Lossless idempotent re-entry: re-extraction runs over (original cleaned body + reply body) so a partial reply never drops original hours; extracted_data is overwritten (single JSONB cell, never appended) and line items replaced by run"
    - "Shared _run_stages() gate path: run_pipeline (first run) and resume_pipeline (CLAR-03 re-entry) call the IDENTICAL four-stage + persist + branch core, so the gate and the eval-reusable spine stay DRY"
    - "Live-vs-mock provenance as a structured LOG field (FIX 12): source='live'/'mock' derived from Settings.allow_live_llm — NEVER a key inside the extra=forbid Decision and NEVER a schema column"

key-files:
  created:
    - fixtures/clarify_reply.json
    - tests/test_threading.py
    - tests/test_live_llm.py
  modified:
    - app/main.py
    - app/pipeline/orchestrator.py
    - tests/conftest.py

key-decisions:
  - "Reply routing happens in the webhook BEFORE the first-ingest sender-match, gated on the inbound carrying an in_reply_to/references — so a reply resumes its run while a no-header inbound falls through to ordinary first ingest unchanged. The reply email_messages row is still inserted (append-only audit) before routing."
  - "resume_pipeline owns its OWN try/except error-wrap (mirroring run_pipeline's D-A1-03 boundary) so a resume-stage failure routes through record_run_error to ERROR, never silently hangs the awaiting_reply run."
  - "The four judgment stages were factored out of _run into a shared _run_stages(run_id, email, roster, *, llm) so run_pipeline and resume_pipeline share the EXACT same gate + persistence + branch path (DRY) — the resume differs ONLY in WHAT email body is fed (original+reply vs the inbound)."
  - "The live-vs-mock marker (FIX 12) is emitted by the live test itself as a structured log field derived from Settings.allow_live_llm; an always-runs guard test pins that smuggling a 'source' key into the extra=forbid Decision raises a ValidationError — proving the marker is NOT a Decision field."

patterns-established:
  - "Header-chain reply routing in the webhook: dedupe → (if header-bearing) find_awaiting_reply_for_header → revalidate sender → resume, else find_any_run_for_header → late-reply log, else fall through to first ingest."
  - "Combined-context re-extraction: _combined_context_email(reply, original_body) builds a delimited 'ORIGINAL … / CLARIFICATION REPLY …' body so the model sees both the original hours and the correction — partial replies are lossless."
  - "Env-gated live exit test mirroring the live-DB two-factor guard: _HAS_LLM_KEYS + _LIVE_LLM, @pytest.mark.live_llm; runs the hero fixture through the IDENTICAL pure stages the eval reuses (DB-free, code-owned run_id) and asserts model-says-process AND sub-0.8 confidence AND final_action=request_clarification."

requirements-completed: [CLAR-02, CLAR-03, EMAIL-01]
# Note: D-A4-01a (the LIVE hero exit gate) is the Task-3 human checkpoint — PENDING, not complete.

# Metrics
duration: 8min
completed: 2026-06-21
---

# Phase 2 Plan 04: Clarify→Reply→Resume Loop (slice c) Summary

**Slice (c), the LAST and trickiest re-entrancy piece (D-A5-01): a fixture reply POSTed to the same inbound webhook routes to its paused run via the RFC In-Reply-To/References header chain (awaiting_reply only), the reply sender is re-asserted against the matched run's business (a spoofed reply on a guessed Message-ID cannot bypass INGEST-03), the run re-enters at extraction idempotently AND losslessly over (original cleaned body + reply body) so a partial reply never loses the original hours, and a late reply to an already-resolved run is logged but not resumed. The full clarify→reply→resume loop is now exercisable end-to-end with ZERO real email. Tasks 1-2 complete; Task 3 (the LIVE hero-fixture exit gate, D-A4-01a) is a PENDING human checkpoint.**

## Status: 2 of 3 tasks complete — Task 3 is a pending human checkpoint

| Task | Name | Status | Commit |
|------|------|--------|--------|
| 1 | Header-chain reply routing (CLAR-02) + sender revalidation (FIX 5) + idempotent re-entry (CLAR-03, FIX 4) | ✅ Complete | `47f83f1` |
| 2 | Reply-fixture injection completing the clarify→reply→resume loop (EMAIL-01) | ✅ Complete | `c7138f7` |
| 3 | **Live hero-fixture exit gate (D-A4-01a) — real models say process AND code gate blocks on sub-0.8** | ⏸️ **PENDING — human checkpoint** | scaffolding `94cfc41` |

Task 3 is a `checkpoint:human-verify` (`gate="blocking-human"`): it requires real DeepSeek/Kimi credentials + confirmed model IDs and is a human judgment of the demo narrative ("the model was willing; the code said no" on LIVE output). The executor authored the env-gated test file (`tests/test_live_llm.py`, skips by default) but did NOT run it live and did NOT approve the gate. See **Pending Human Checkpoint** below.

## Performance

- **Duration:** ~8 min (Tasks 1-2 + the live-test scaffolding)
- **Started:** 2026-06-21T10:51:39Z
- **Completed (Tasks 1-2):** 2026-06-21T10:59:23Z
- **Tasks:** 2 of 3 complete (Task 3 = pending human checkpoint)
- **Files modified:** 6 (3 created, 3 modified)

## Accomplishments

- **Header-chain reply routing (CLAR-02):** `app/main.py` now routes a header-bearing inbound to its paused run via `repo.find_awaiting_reply_for_header` (restricted to `status='awaiting_reply'`, parameterized LIKE on references — `%(references)s`, never interpolated) BEFORE the first-ingest sender-match, so a reply resumes its run instead of opening a second one. A reply matching via In-Reply-To OR the full References chain both route. Subject/provider-thread fallback is a deliberately-deferred P6 concern (real-provider thread variety) and is NOT built — per CLAR-02 the RFC header chain is the primary AND only proven path.
- **Reply sender revalidation (FIX 5 — safety):** after the header match, `reply.from_addr` is re-asserted against the matched run's business `contact_email` (reusing the same `find_business_by_sender` comparison used at first ingest). A mismatch is logged and NOT resumed — a spoofed reply on a guessed/leaked Message-ID cannot bypass INGEST-03. A matching sender resumes normally.
- **Late-reply observability (FIX 10):** when `find_awaiting_reply_for_header` returns None, `repo.find_any_run_for_header` is consulted — a header match to a run NOT in awaiting_reply (sent/reconciled/rejected/computed) is logged as a LATE REPLY (`status="late_reply"`) and NOT resumed (only awaiting_reply runs resume).
- **Idempotent + lossless re-entry (CLAR-03, FIX 4 + FIX A + FIX C):** `orchestrator.resume_pipeline(run_id, inbound)` rebuilds the extraction context from `repo.load_source_email(run_id)` (the ORIGINAL cleaned inbound body, NOT re-cleaned) combined with the reply body, passes the run's CODE-OWNED `run_id` into `extract()` (the model returns only an ExtractionPayload; extract stamps run_id), then `persist_extracted` OVERWRITES `extracted_data` wholesale + `replace_line_items` DELETEs-by-run then inserts. Because the re-extraction sees the original body, employees/hours not mentioned in the reply are RETAINED, not lost. The four judgment stages are factored into a shared `_run_stages()` so `run_pipeline` and `resume_pipeline` share the EXACT same gate path.
- **The full loop with ZERO real email (EMAIL-01):** `fixtures/clarify_reply.json` (a `__CLARIFICATION_MESSAGE_ID__` placeholder, `from_addr=hr@metrodeli.example` so it passes FIX-5, an answer-only body correcting "David Reyes" WITHOUT restating hours) drives the gate-block fixture → awaiting_reply → read back the clarification Message-ID via `get_outbound_message_id` (the FIX-3 anchor) → substitute → **ASSERT the substitution took BEFORE the POST** (WARNING 8 — a broken substitution fails LOUDLY, not silently via the no-match branch) → POST → resume → advance, computing a paystub for the now-resolved employee.
- **Live exit-gate scaffolding (D-A4-01a):** `tests/test_live_llm.py` is the env-gated two-factor live test (`_HAS_LLM_KEYS` + `ALLOW_LIVE_LLM`, `@pytest.mark.live_llm`) that runs the hero fixture through the REAL DeepSeek/Kimi models via the IDENTICAL pure stages the eval reuses (DB-free, code-owned run_id) and asserts model-says-process AND sub-0.8 confidence AND `final_action=="request_clarification"`. It SKIPS by default; an always-runs guard (`test_live_marker_is_not_a_decision_field`) pins FIX 12 (the source marker is a structured log field, NOT a Decision key). **The live RUN is the Task-3 human checkpoint — not executed here.**
- **Mocked suite green: 159 passed, 12 deselected** (up from 145; +14 new tests — 13 threading + 1 always-runs FIX-12 guard; no regressions). The live hero test + 11 integration round-trips deselect, as designed.

## Task Commits

1. **Task 1: Header-chain reply routing + sender revalidation + idempotent resume** — `47f83f1` (feat)
2. **Task 2: Reply-fixture injection completing the clarify→reply→resume loop (EMAIL-01)** — `c7138f7` (feat)
3. **Task 3 SCAFFOLDING: env-gated live hero-fixture exit-gate test (D-A4-01a)** — `94cfc41` (test) — *the test file only; the live RUN is the pending human checkpoint*

**Plan metadata:** committed separately with this SUMMARY.md + STATE.md + ROADMAP.md + REQUIREMENTS.md.

## Files Created/Modified

- `app/main.py` — `_route_reply()` routes a header-bearing inbound (find_awaiting_reply_for_header → FIX-5 sender revalidation → resume; else find_any_run_for_header → late-reply log; else fall through). `_resume_pipeline()` background wrapper (mirrors `_run_pipeline`'s safety net).
- `app/pipeline/orchestrator.py` — `resume_pipeline(run_id, inbound)` (idempotent + lossless re-entry, own error-wrap), `_combined_context_email()` (original body + reply body), `_run_stages()` (the shared four-stage gate path used by both run_pipeline and resume_pipeline).
- `fixtures/clarify_reply.json` — the canonical reply InboundEmail (placeholder + run-business from_addr + answer-only body).
- `tests/test_threading.py` — 13 threading tests: header match (in_reply_to + References + parameterized-LIKE guard), sender revalidation (mismatch not resumed / match resumes), partial-reply-preserves-hours, run_id stamping, idempotent resume, late-reply-not-resumed, both-lookups-in-webhook, the full loop with pre-POST substitution assertion, fixture validation, no-match graceful handling.
- `tests/test_live_llm.py` — the env-gated live hero exit-gate test (skips by default) + the always-runs FIX-12 Decision-field guard.
- `tests/conftest.py` — InMemoryRepo gains `find_awaiting_reply_for_header` + `find_any_run_for_header` (mirroring the repo SQL semantics) so the full reply→resume loop runs offline.

## Decisions Made

- **Reply routing precedes first ingest, gated on a header being present.** A header-bearing inbound tries the header chain; a no-header inbound falls straight through to the ordinary sender-match→create_run path. The reply's email_messages row is still inserted (append-only audit) before routing, so the audit trail is complete regardless of branch.
- **resume_pipeline owns its own D-A1-03 error-wrap** (mirroring run_pipeline) so a resume-stage failure routes through record_run_error to ERROR — an awaiting_reply run can never silently hang on a bad reply.
- **The four stages were factored into a shared `_run_stages()`** so the gate + persistence + branch path is IDENTICAL for the first run and the resume — the resume differs ONLY in the email body fed (original+reply vs the inbound).
- **The live-vs-mock marker (FIX 12) is a structured log field emitted by the live test**, derived from `Settings.allow_live_llm`; an always-runs guard test proves a `source` key in the `extra="forbid"` Decision raises a ValidationError — so the marker is provably NOT a Decision field and NOT a schema column.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] conftest InMemoryRepo extended with the two header-chain lookups**
- **Found during:** Task 1 (the webhook-driven reply→resume tests)
- **Issue:** The webhook's new `_route_reply` calls `repo.find_awaiting_reply_for_header` and `repo.find_any_run_for_header`, but the Plan 01/02/03 `fake_repo` (InMemoryRepo) did not patch them. Left unpatched, the webhook called the REAL repo functions against a live DB connection — the in-memory reply→resume loop could not be asserted offline, and the runs leaked onto the pooled DB-connection path (visible as `pool-1-worker` thread-shutdown warnings).
- **Fix:** Added `find_awaiting_reply_for_header` (awaiting_reply-only) + `find_any_run_for_header` (any-status) to InMemoryRepo — mirroring the repo SQL semantics exactly (outbound Message-ID == in_reply_to OR ∈ references_header) — and registered both in the `fake_repo` monkeypatch list. The full reply→resume loop now runs fully in RAM.
- **Files modified:** tests/conftest.py
- **Verification:** all 13 threading tests green offline (no pool-thread warnings); the full mocked suite green (159).
- **Committed in:** `47f83f1` (Task 1)

---

**Total deviations:** 1 auto-fixed (1 blocking test-harness gap).
**Impact on plan:** A test-side fix demanded by this plan's own production wiring (the webhook now calls the two header-chain lookups the conftest had not mirrored) — no production scope creep, no contract field added, no new dependency, no signature change. Every locked invariant holds: header-chain routing (awaiting_reply only), parameterized SQL, FIX 5 sender revalidation, FIX 10 late-reply observability, FIX 4/A/C lossless idempotent re-entry, the FIX-3 Message-ID anchor, and FIX 12 (the marker is a log field, not a Decision key).

## Known Stubs
None. Header-chain routing, sender revalidation, the late-reply branch, the idempotent+lossless resume, the reply fixture, and the env-gated live test are all wired and exercised by green tests. The only remaining work is the LIVE RUN of the exit gate, which is the Task-3 human checkpoint (a model-behavior property no mock can assert), not a stub.

## Pending Human Checkpoint (Task 3 — D-A4-01a)

**Type:** `checkpoint:human-verify` (`gate="blocking-human"`)

**What is awaited:** A one-time LIVE run of the hero fixture against the REAL configured DeepSeek/Kimi models, judged by a human, proving the demo narrative: the real model genuinely returns `model_action=="process"` (willing) at a per-name confidence `< 0.8` so the code gate fires → `final_action=="request_clarification"`. The mocked suite passing is NECESSARY but NOT SUFFICIENT (D-A5-01); this gate proves the DEMO the mock cannot.

**How to verify (operator steps):**
1. Confirm the exact DeepSeek/Kimi non-reasoning model IDs + the DeepSeek non-thinking request parameter from the provider consoles and pin them in `.env` (STATE.md open blocker; legacy `deepseek-chat`/`deepseek-reasoner` retire 2026/07/24 — never alias to them).
2. (Optional) A tiny live smoke-test (temperature=0, max_tokens=5 per tier) to confirm creds + IDs resolve + non-thinking mode is accepted.
3. Run: `ALLOW_LIVE_LLM=1 EXTRACTION_API_KEY=… DECISION_API_KEY=… .venv/bin/python -m pytest tests/test_live_llm.py::test_hero_fixture_live -m live_llm -x`
4. EXPECTED: the real model matches David Reyez → David Reyes and returns `process` at sub-0.8 confidence so the gate fires → `final_action=="request_clarification"` ("the model was willing; the code said no" on REAL output).
5. Confirm the live-vs-mock marker is recorded as a structured LOG field (`source="live"`), NOT a key inside the `extra="forbid"` Decision and NOT a schema column (FIX 12).
6. IF the model self-clarifies (gate never fires) OR returns confidence ≥0.8: TUNE the submitted-name variant (`David Reyez`) and/or the reconcile prompt (AI-SPEC §7) and repeat — a human-judgment loop, not an automated pass/fail.
7. For the recording, capture the exact good run (hosted APIs are not bit-deterministic even at temperature 0).

**Resume signal:** Type "approved" once the live run genuinely produces model-says-process AND gate-blocks-on-sub-0.8 (tune + repeat first if it self-clarifies or returns ≥0.8) and the marker is recorded as a structured log field outside the Decision object, or describe the issue.

## Issues Encountered
- The reply fixture's `from_addr` MUST equal the gate-block run's business `contact_email` (`hr@metrodeli.example`) or the FIX-5 sender revalidation would (correctly) refuse to resume it. The fixture and the full-loop test both pin this, and the answer-only body (no restated hours) exercises the FIX-4 partial-reply-preserves-hours path.
- The plan's `files_modified` lists `app/email/gateway.py`; no gateway change was needed — the FIX-3 outbound Message-ID anchor + `get_outbound_message_id` read-back were already complete in Plan 01/03, and the reply routing reads that anchor through the repo. No gateway edit was made (no deviation; the surface was already sufficient).

## User Setup Required
The Task-3 live run requires real provider credentials (the open STATE.md blocker, unchanged): confirm the exact DeepSeek/Kimi model IDs + the DeepSeek non-thinking request parameter from the consoles and set `EXTRACTION_API_KEY` + `DECISION_API_KEY` + `ALLOW_LIVE_LLM=1`. Config-driven, so confirmation is a one-line `.env` change, not a code change.

## Next Phase Readiness
- **Slice (c) code is complete:** both pause states (`awaiting_reply`, `awaiting_approval`) are now fully wired and exercisable end-to-end with zero real email; the resume loop is safe (sender-revalidated) and lossless (re-extracts over original+reply). The ONLY remaining Phase 2 item is the Task-3 LIVE exit gate (a human checkpoint).
- The threading + resume logic reuses the IDENTICAL pure judgment stages the Phase 4 eval calls; per-name reconciliation + the Decision are persisted (overwritten) on every resume for offline scoring.
- Open blocker (unchanged): exact provider model IDs + the non-thinking request param before the live hero run.

## Self-Check: PASSED

All 3 created files (`fixtures/clarify_reply.json`, `tests/test_threading.py`, `tests/test_live_llm.py`) + the 3 modified files exist on disk, and all 3 task commits (`47f83f1`, `c7138f7`, `94cfc41`) are present in git history. (Task 3's live RUN is intentionally NOT executed — it is the pending human checkpoint.)

---
*Phase: 02-walking-skeleton*
*Tasks 1-2 completed: 2026-06-21 — Task 3 awaiting human checkpoint*
