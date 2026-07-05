---
phase: 11
slug: clarification-round-machine-alias-learning
status: approved
nyquist_compliant: true
wave_0_complete: false
created: 2026-07-05
---

# Phase 11 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Populated from the 5 approved plans (11-01…11-05) after plan-checker re-verification passed.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (via uv-managed venv, Python 3.12) |
| **Config file** | `pyproject.toml` (`[tool.pytest.ini_options]`; markers `integration`, `live_llm`) |
| **Quick run command** | `uv run pytest -q -m "not integration and not live_llm"` |
| **Full suite command** | `uv run pytest -q` |
| **Estimated runtime** | ~10–25 seconds (offline suite; hermetic, LLM mocked) |

---

## Sampling Rate

- **After every task commit:** Run `uv run pytest -q -m "not integration and not live_llm"` plus the task's own `<automated>` command.
- **After every plan wave:** Run `uv run pytest -q` (full suite).
- **Before `/gsd-verify-work`:** Full suite must be green.
- **Max feedback latency:** ~25 seconds (offline suite).

---

## Per-Task Verification Map

Task IDs follow `11-{plan}-{task}`. Every task carries an automated `<automated>` verify (Nyquist Dimension 8a PASS); commands are copied verbatim from the plans.

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 11-01-01 | 01 | 1 | CLAR2-01/02 | T-11-01 | Schema adds needs_operator (both CHECK spots), round/consumed_round cols, widened uq constraint — no status-enum drift | unit | `uv run pytest -q tests/test_status_drift.py && grep -c "needs_operator" app/db/schema.sql …` | ✅ (test_status_drift.py) | ⬜ pending |
| 11-01-02 | 01 | 1 | CLAR2-01/02 | T-11-02 | insert_email_message ON CONFLICT arbiter matches the 3-col constraint; no upsert-replace of round history | unit | `uv run pytest -q -m "not integration and not live_llm" && grep -q "ON CONFLICT (run_id, purpose, round)" app/db/repo.py …` | ✅ | ⬜ pending |
| 11-01-03 | 01 | 1 | CLAR2-01/02 | T-11-03 | Full offline suite green — zero behavior change (round defaults to 0 everywhere) | regression | `uv run pytest -q -m "not integration and not live_llm"` | ✅ | ⬜ pending |
| 11-02-01 | 02 | 2 | CLAR2-01 | T-11-04 | Round-aware (purpose, round) guard: a new round's question sends; MAX_CLARIFICATION_ROUNDS=3 cap | unit | `uv run pytest -q -m "not integration and not live_llm" && grep -q "MAX_CLARIFICATION_ROUNDS = 3" … && grep -q "get_outbound_for_round" …` | ✅ | ⬜ pending |
| 11-02-02 | 02 | 2 | CLAR2-02 | T-11-05 | needs_operator badge + excluded from sweep/retrigger-stale/IN_FLIGHT scope | unit | `uv run pytest -q tests/test_stuck_run_recovery.py tests/test_dashboard.py && grep …"needs_operator" app/main.py` | ✅ | ⬜ pending |
| 11-02-03 | 02 | 2 | CLAR2-01/02 | T-11-06 | New-question-sends / same-round-suppressed / crash-idempotent round advance / cap escalation with NO LLM + NO gateway | unit | `uv run pytest -q tests/test_clarify_rounds.py tests/test_needs_operator.py && uv run pytest -q -m "not integration and not live_llm"` | ❌ W0 (test_clarify_rounds.py, test_needs_operator.py) | ⬜ pending |
| 11-03-01 | 03 | 3 | CLAR2-05 | T-11-16 | mark_reply_consumed called AFTER the resume CAS claim — the load-bearing seam for accumulation + stranded detection | unit | `uv run pytest -q -m "not integration and not live_llm" && grep -q "mark_reply_consumed" app/pipeline/orchestrator.py` | ✅ | ⬜ pending |
| 11-03-02 | 03 | 3 | CLAR2-03/05 | T-11-07/08 | _combined_context_email = pure fn (ORIGINAL + code-owned asked-anchor + ALL consumed replies in round order); consumed row PRODUCED BY resume_pipeline, not seeded | unit | `uv run pytest -q tests/test_combined_context.py && … && grep -q "asked_summary_lines" … && grep -q "load_consumed_replies" …` | ❌ W0 (test_combined_context.py) | ⬜ pending |
| 11-03-03 | 03 | 3 | CLAR2-03 | T-11-09 | Resume extraction prompt carries absent-if-unaddressed; still-absent asked field re-gates through decide | unit | `uv run pytest -q -m "not integration and not live_llm" && grep -qi "attribut" app/llm/prompts/extract.py` | ✅ | ⬜ pending |
| 11-03-04 | 03 | 3 | CLAR2-05 | T-11-10 | CX-01 closed: Round-1 "30, not 40" pays hours_regular=30 (paid VALUE); known-edge fixture assertion flips | unit | `uv run pytest -q tests/test_combined_context.py tests/test_multiround_context_edge.py && uv run pytest -q -m "not integration and not live_llm"` | ✅ (test_multiround_context_edge.py) | ⬜ pending |
| 11-04-01 | 04 | 4 | CLAR2-04 | T-11-11 | Nested {token:{suggested,bound}} persistence; suggest_employees output mapped to employee id at persist | unit | `uv run pytest -q tests/test_alias_write.py && … && grep -q "_normalize_candidate" … && grep -q "\"suggested\"" …` | ✅ (test_alias_write.py) | ⬜ pending |
| 11-04-02 | 04 | 4 | CLAR2-04 | T-11-12/13 | Operator resolve form + resume route; server-side roster validation (Security V4); remember-checkbox | unit | `uv run pytest -q tests/test_dashboard.py tests/test_needs_operator.py && … && grep -q "overrides" app/pipeline/reconcile_names.py && grep -q "/resolve" app/main.py` | ❌ W0 (test_needs_operator.py) | ⬜ pending |
| 11-04-03 | 04 | 4 | CLAR2-04 | T-11-14/15 | D-11-17 full-loop stops-asking with REAL resolution; misname ("no, I meant James") binds NOTHING; 2nd submission resolves via stored-alias, NO clarification | integration (hermetic) | `uv run pytest -q tests/test_alias_full_loop.py tests/test_alias_write.py && uv run pytest -q -m "not integration and not live_llm"` | ❌ W0 (test_alias_full_loop.py) | ⬜ pending |
| 11-05-01 | 05 | 5 | CLAR2-06 | T-11-17 | _row_to_inbound rebuilds InboundEmail from authoritative persisted body; repo select widened (in_reply_to, references) | unit | `uv run pytest -q -m "not integration and not live_llm" && grep -q "def _row_to_inbound" app/main.py && grep -q "in_reply_to" app/db/repo.py` | ✅ | ⬜ pending |
| 11-05-02 | 05 | 5 | CLAR2-06 | T-11-18/19 | WR-04 duplicate-branch reschedule (consumed_round IS NULL + awaiting_reply); D-11-05 stranded auto-resume from runs-list; needs_operator EXCLUDED | unit | `uv run pytest -q tests/test_reply_redelivery.py && … && grep -q "get_inbound_by_message_id" app/main.py && grep -q "find_stranded_unconsumed_replies" app/main.py` | ❌ W0 (test_reply_redelivery.py) | ⬜ pending |
| 11-05-03 | 05 | 5 | CLAR2-07 | T-11-20 | WR-06 retrigger clear: clear_reply_context called at post-claim convergence BEFORE _run_pipeline; all 4 reply-context columns cleared; stale badge cannot reproduce | unit | `uv run pytest -q tests/test_cr_regressions.py && … && grep -q "clear_reply_context" app/main.py` | ✅ (test_cr_regressions.py) | ⬜ pending |
| 11-05-04 | 05 | 5 | CLAR2-06/07 | T-11-17…20 | Redelivery/stranded matrix + retrigger clear-all-context, no regression to webhook/runs-list/retrigger routes | regression | `uv run pytest -q tests/test_reply_redelivery.py tests/test_cr_regressions.py && uv run pytest -q -m "not integration and not live_llm"` | ❌ W0 (test_reply_redelivery.py) | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

Net-new test modules that must be created before their asserting tasks run (existing modules are extended in place, not stubbed):

- [ ] `tests/test_clarify_rounds.py` — CLAR2-01 round machine (11-02-03)
- [ ] `tests/test_needs_operator.py` — CLAR2-02 cap/escape + resolve-form scope (11-02-03, 11-04-02)
- [ ] `tests/test_combined_context.py` — CLAR2-03/05 anchor + accumulation, incl. the consumed-marker real-row assertion (11-03-02)
- [ ] `tests/test_alias_full_loop.py` — CLAR2-04 stops-asking loop with REAL resolution (11-04-03)
- [ ] `tests/test_reply_redelivery.py` — CLAR2-06 redelivery/stranded matrix (11-05-02, 11-05-04)

Extended-in-place (already exist): `test_status_drift.py`, `test_stuck_run_recovery.py`, `test_dashboard.py`, `test_multiround_context_edge.py` (assertion flips), `test_alias_write.py` (nested shape), `test_cr_regressions.py` (retrigger clear).

*No test framework install required — pytest infrastructure already present.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live schema migration (needs_operator CHECK, round columns, widened uq constraint, backfill DO-block) applied against Supabase | CLAR2-01/02/06/07 | DDL runs at a blocking human checkpoint against the live pooler (Phase 8 idempotent DO-block pattern); not exercised by the hermetic offline suite | Apply the 11-01 migration at the operator checkpoint; confirm `\d payroll_runs` shows `clarification_round`, the status CHECK includes `needs_operator`, and `uq_email_run_purpose_round` exists; re-run to confirm idempotency |

*All other phase behaviors have automated verification.*

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (every task has one)
- [x] Wave 0 covers all net-new test modules
- [x] No watch-mode flags
- [x] Feedback latency < 25s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-07-05 (plan-checker re-verification PASSED — 4 prior blockers closed, no new blockers)
